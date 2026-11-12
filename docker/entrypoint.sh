#!/usr/bin/env bash
#
# Container entrypoint for the ai-job-search agent image.
#
# Responsibilities:
#   1. Verify the repository is mounted at /work.
#   2. Seed bun node_modules for the portal CLIs from the prebuilt copy baked
#      into the image, so the first run needs no package-registry access.
#   3. Render the container OpenCode config from docker/services.json plus the
#      MODEL_* environment variables (tools/render_opencode_config.py) and
#      export it via OPENCODE_CONFIG_CONTENT, which outranks the project's
#      opencode.json.
#   4. Warn when the selected model server is unreachable.
#   5. exec the requested command (default: opencode).
#
# This script runs as the unprivileged `agent` user and never writes outside
# /work, /home/agent and tmpfs.

set -euo pipefail

REPO="${WORKDIR:-/work}"
RENDER_CONFIG="$REPO/tools/render_opencode_config.py"
REGISTRY="$REPO/docker/services.json"

if [[ ! -d "$REPO/.agents/skills" ]]; then
  echo "entrypoint: '$REPO' is not the ai-job-search repository." >&2
  echo "entrypoint: mount the repository at /work (see docker-compose.yml)." >&2
  exit 1
fi

# On Windows the bind mount is owned by root while the container runs as
# UID 1000, which makes git refuse the repository as "dubious ownership".
if [[ -d "$REPO/.git" ]] && command -v git >/dev/null 2>&1; then
  if ! git config --global --get-all safe.directory | grep -qxF "$REPO"; then
    git config --global --add safe.directory "$REPO"
  fi
fi

# GitHub access for the agent. GH_TOKEN and the commit identity come from
# .env.docker (gitignored; see env.docker.example). Without GH_TOKEN this is a
# no-op, so the container still works fully local.
if [[ -d "$REPO/.git" ]] && command -v git >/dev/null 2>&1; then
  if [[ -n "${GIT_USER_NAME:-}" ]] && ! git config --global --get user.name >/dev/null 2>&1; then
    git config --global user.name "$GIT_USER_NAME"
  fi
  if [[ -n "${GIT_USER_EMAIL:-}" ]] && ! git config --global --get user.email >/dev/null 2>&1; then
    git config --global user.email "$GIT_USER_EMAIL"
  fi
  if [[ -n "${GH_TOKEN:-}" ]] && command -v gh >/dev/null 2>&1; then
    # Wire git's credential helper through gh, which reads GH_TOKEN from the
    # environment. Writes ~/.gitconfig in the agent-home volume, never the
    # repository's .git/config (shared with the host).
    if ! gh auth setup-git >/dev/null 2>&1; then
      echo "entrypoint: warning: 'gh auth setup-git' failed; git push may not authenticate" >&2
    fi
  fi
fi

for cli_dir in "$REPO"/.agents/skills/*/cli; do
  [[ -d "$cli_dir" ]] || continue
  if [[ ! -d "$cli_dir/node_modules" ]]; then
    portal="$(basename "$(dirname "$cli_dir")")"
    prebuilt="/opt/portal-deps/.agents/skills/$portal/cli/node_modules"
    if [[ -d "$prebuilt" ]]; then
      echo "entrypoint: seeding node_modules for $portal"
      cp -R "$prebuilt" "$cli_dir/node_modules"
    else
      echo "entrypoint: warning: no prebuilt node_modules for $portal;" >&2
      echo "entrypoint: run 'bun install' in .agents/skills/$portal/cli inside the container." >&2
    fi
  fi
done

export OPENCODE_CONFIG_CONTENT
if ! OPENCODE_CONFIG_CONTENT="$(python3 "$RENDER_CONFIG" --registry "$REGISTRY")"; then
  echo "entrypoint: failed to render the OpenCode config from $REGISTRY" >&2
  echo "entrypoint: check MODEL_SERVICE/MODEL_NAME/MODEL_BASE_URL (see CHEATSHEET.md)." >&2
  exit 1
fi

# Preflight the model server the rendered config points at, so a stopped server
# is visible before the TUI starts.
model_url="$(python3 "$RENDER_CONFIG" --registry "$REGISTRY" --health-url 2>/dev/null || true)"

if [[ -n "$model_url" && "${OPENCODE_SKIP_MODEL_CHECK:-0}" != "1" ]]; then
  if ! curl -fsS --max-time 5 "$model_url" >/dev/null 2>&1; then
    echo "entrypoint: warning: model server not reachable at $model_url" >&2
    echo "entrypoint: start it on the host (see CHEATSHEET.md) and allow local-network access." >&2
  fi
fi

exec "$@"
