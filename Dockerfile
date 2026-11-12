# Agent container for ai-job-search.
#
# Runs the OpenCode 2 CLI plus the full document toolchain (Bun, Python,
# TeX Live, poppler) in an unprivileged, read-only container. The repository
# is bind-mounted at /work by docker-compose.yml; the local model server
# (LM Studio) stays on the host and is reached via host.docker.internal.
#
# Only .agents/ enters the build stage, so personal data cannot end up in an
# image layer even if .dockerignore is edited by mistake.

# --- Stage 1: pre-install portal CLI dependencies ---------------------------
FROM oven/bun:1 AS portal-deps
WORKDIR /src
COPY .agents/skills .agents/skills
RUN set -eux; \
    for dir in .agents/skills/*/cli; do \
      echo "bun install: $dir"; \
      (cd "$dir" && bun install); \
    done

# --- Stage 2: runtime --------------------------------------------------------
FROM node:22-bookworm-slim

ARG OPENCODE_VERSION=2.2.5

# Keep Playwright's browsers out of /home/agent: docker-compose mounts an
# agent-home volume there, which would hide an image-layer browser cache on an
# already-created volume. /opt is baked into the image and always present.
ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    HOME=/home/agent \
    PATH=/opt/venv/bin:$PATH \
    BUN_INSTALL=/home/agent/.bun \
    OPENCODE_DISABLE_AUTOUPDATE=true \
    PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright

RUN usermod --login agent --home /home/agent --move-home node \
 && groupmod --new-name agent node \
 && chown -R agent:agent /home/agent

# The TeX package set mirrors the debian-bookworm leg of
# .github/workflows/ci.yml, which is proven to compile the stock moderncv CV
# (cover letters are plain text). antiword/catdoc read legacy
# .doc files and tesseract OCRs scans/images that /setup and /expand would
# otherwise get stuck on.
# libatomic1 is required by Playwright's bundled Node driver; node:22-bookworm-slim
# omits it, and without it `playwright install` cannot start at all (so its own
# `--with-deps` never runs). The rest of Chromium's system libraries are installed
# by `playwright install --with-deps chromium` below.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      antiword \
      ca-certificates \
      catdoc \
      curl \
      file \
      gh \
      git \
      libatomic1 \
      poppler-utils \
      python3 \
      python3-venv \
      tesseract-ocr \
      tesseract-ocr-eng \
      tesseract-ocr-rus \
      texlive-fonts-extra \
      texlive-fonts-recommended \
      texlive-latex-extra \
      texlive-luatex \
  && rm -rf /var/lib/apt/lists/*

COPY --from=oven/bun:1 /usr/local/bin/bun /usr/local/bin/bun

RUN python3 -m venv /opt/venv \
 && /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
 && /opt/venv/bin/pip install --no-cache-dir pypdf pyyaml openpyxl aiogram pydantic-settings \
 && /opt/venv/bin/pip install --no-cache-dir playwright \
 && /opt/venv/bin/playwright install --with-deps chromium \
 && chmod -R a+rX /opt/ms-playwright \
 && npm install -g "@opencode/cli@${OPENCODE_VERSION}" \
 && npm cache clean --force \
 && printf 'export PATH=/opt/venv/bin:$PATH\n' > /etc/profile.d/venv-path.sh \
 && chown -R agent:agent /home/agent

RUN mkdir -p /work

COPY --from=portal-deps /src/.agents /opt/portal-deps/.agents
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN sed -i 's/\r$//' /usr/local/bin/entrypoint.sh \
 && chmod 0755 /usr/local/bin/entrypoint.sh \
 && chmod -R a+rX /opt/portal-deps

USER agent
WORKDIR /work

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["opencode"]
