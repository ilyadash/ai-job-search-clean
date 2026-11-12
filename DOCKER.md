# Running AI Job Search in Docker

The container keeps the agent away from your host: OpenCode and its toolchain
(Bun, Python, TeX Live, poppler, antiword/catdoc for legacy `.doc` files, and
tesseract for OCR) run in an unprivileged, read-only container whose only host
mount is this repository. The default model is **DeepSeek Flash** (cloud); an
optional LM Studio server on the host can be used instead.

Commands and keybinds: [CHEATSHEET.md](CHEATSHEET.md) or `make help`. How the
container picks a server and model is defined in code, not prose:

- `docker/services.json` — adapter registry (host, port, base URL, default model);
- `tools/render_opencode_config.py` — renders `OPENCODE_CONFIG_CONTENT` from
  the registry plus `MODEL_*` environment variables.

```
┌─ container: agent (CPU-only, read-only rootfs) ──────────────────────────┐
│  OpenCode CLI · Bun · Python · TeX Live · poppler                        │
│  /work        ← bind mount: this repository                              │
│  /home/agent  ← named volume: auth, sessions, caches                     │
└──────┬──────────────────────────────────┬─────────────────────────────────┘
       │ HTTPS → api.deepseek.com         │ HTTP → host:1234
┌──────▼──────────────────────────┐  ┌────▼──────────────────────────────┐
│ DeepSeek (default)              │  │ LM Studio (optional)             │
│ deepseek-flash                  │  │ qwen3.5-9b, gemma-4-12b          │
└─────────────────────────────────┘  └───────────────────────────────────┘
```

`host` is `host.docker.internal`. The default is DeepSeek Flash; LM Studio is
optional. Other hosted providers can be added through OpenCode's auth store
([Cloud providers](#cloud-providers)).

## Model services

The registry ships three adapters:

- **`deepseek`** (default) — DeepSeek Flash at `https://api.deepseek.com`.
  Set `MODEL_API_KEY` in `.env.docker`. The service sets `healthCheck: false`,
  so the entrypoint does not probe `/models` (DeepSeek does not expose a
  compatible health endpoint the way local servers do).
- **`lmstudio`** — LM Studio on port 1234. Enable **Serve on Local Network**,
  load a tool-capable model, set the context length to at least 32k.
- **`custom`** — any OpenAI-compatible endpoint via `MODEL_BASE_URL`; set
  `MODEL_API_KEY` when the endpoint requires one.

Only LM Studio needs a host port; allow 1234 through Windows Firewall, scoped
to the WSL subnet if possible. Verify from the host with
`curl.exe http://localhost:1234/v1/models`.

## Cloud providers

The default registry service is `deepseek` (`https://api.deepseek.com`,
model `deepseek-flash`). Put the key in `.env.docker`:

```
MODEL_API_KEY=sk-...
```

The renderer injects it as the provider API key; no `opencode auth login` is
needed for this path. To use another hosted provider (OpenAI, Anthropic,
OpenRouter, ...), connect it through OpenCode's auth store:

```powershell
docker compose run --rm agent opencode auth login
```

Credentials are written to `~/.local/share/opencode/auth.json` inside the
`agent-home` volume: they survive `docker compose down`/recreation and never
enter the repository.

Select the model per session:

- in the TUI: `/models` → the provider → e.g. `deepseek/deepseek-flash`;
- one-off CLI runs:
  `docker compose run --rm agent opencode run --standalone -m deepseek/deepseek-flash "..."`.

The `MODEL_*` variables select a registry service (including `deepseek` and
`custom`); other hosted providers are connected through the auth store and
chosen with `/models`.

If you use LM Studio and no local server is running, set
`OPENCODE_SKIP_MODEL_CHECK=1` in `.env.docker` to silence the entrypoint's
preflight warning; the TUI starts either way. DeepSeek skips that probe
automatically because its registry entry has `healthCheck: false`.

Privacy and cost: a cloud model ships the conversation — including whatever the
agent read from your profile, `documents/`, and postings — to that provider and
bills you per token. LM Studio keeps all of it on the machine. The container's
egress is not filtered in either case (see [Security model](#security-model)).

## Choosing a service and model

| Variable | Meaning | Default |
|---|---|---|
| `MODEL_SERVICE` | registry id (`deepseek`, `lmstudio`, `custom`) | `deepseek` |
| `MODEL_NAME` | exact model id; empty uses the registry default (`deepseek-flash`) | empty |
| `SMALL_MODEL_NAME` | small-model id | same as `MODEL_NAME` |
| `MODEL_PORT` | overrides the registry port | registry |
| `MODEL_BASE_URL` | explicit base URL; selects `custom` unless a service is set | registry |
| `MODEL_DISCOVER` | `0` disables model discovery | `1` |
| `MODEL_API_KEY` | API key for hosted services | empty |
| `OPENCODE_MODEL` | full `<service>/<model>` reference, highest priority | empty |

```powershell
# persistent, in .env.docker (gitignored; copy env.docker.example)
#   MODEL_SERVICE=deepseek
#   MODEL_NAME=deepseek-flash
#   MODEL_API_KEY=sk-...

# per run, local LM Studio instead
docker compose run --rm -e MODEL_SERVICE=lmstudio -e MODEL_NAME=qwen/qwen3.5-9b agent
```

Inspect what the container resolved:

```powershell
docker compose run --rm agent bash -lc "python3 tools/render_opencode_config.py --list"
```

## Build and run

```powershell
docker compose build
docker compose run --rm agent        # OpenCode TUI
docker compose run --rm agent bash   # shell inside the container
```

The first build downloads the TeX Live package set (needed for the CV) and
produces an image of several GB; later rebuilds reuse the layer cache. On first
start the entrypoint seeds `node_modules` for the portal CLIs from the copy
baked into the image, so no package registry access is needed.

## Data and persistence

| Mount | Contents | Lifetime |
|---|---|---|
| `.:/work` | The repository: profile, `documents/`, SQLite state database, generated CVs and cover letters | Your working tree |
| `agent-home:/home/agent` | OpenCode auth (`auth.json`), session database, bun/npm caches | Named Docker volume |

Nothing else from the host is visible inside the container: no Docker socket,
no user profile, no SSH keys. Cloud provider credentials survive container
recreation too (see [Cloud providers](#cloud-providers)):

```powershell
docker compose run --rm agent opencode auth login
```

## GitHub access (optional)

The agent can fetch from and push to your private fork when you provide a
token. Credentials and commit identity live in `.env.docker` (gitignored; copy
`env.docker.example`):

| Variable | Meaning |
|---|---|
| `GH_TOKEN` | fine-grained PAT: this repository only, `Contents: Read and write`, `Metadata: Read`, short expiry |
| `GIT_USER_NAME` / `GIT_USER_EMAIL` | identity for agent-created commits (use the GitHub noreply address) |

On startup the entrypoint applies the identity and wires git's credential
helper through `gh` (`gh auth setup-git`); without `GH_TOKEN` both steps are
skipped and the container stays fully local.

Verify (does not push anything):

```powershell
docker compose run --rm agent bash -lc "gh auth status; cd /work && git fetch origin && git push --dry-run"
```

`origin` is your private fork; `upstream` and `opencode-upstream` are public
and need no token. If you later want the agent to open pull requests, add the
`Pull requests: Read and write` permission — pull/push alone does not need it.
Branch protection on the working branch (no force-push, review required) is the
real guard against unwanted pushes.

## Telegram bot (optional)

A regular aiogram bot. Forward it the AI
recruiter's question and it returns a 2-4 sentence draft grounded in your
profile; you copy the draft into the recruiter chat.

1. Create a bot with [@BotFather](https://t.me/BotFather) and copy its token.
2. Find your numeric user id: message [@userinfobot](https://t.me/userinfobot),
   or press `/start` in your bot — it replies with the id it saw.
3. In `.env.docker` (gitignored; copy `env.docker.example`):

   ```
   TELEGRAM_BOT_TOKEN=123456:replace_me
   TELEGRAM_ALLOWED_USER_ID=123456789
   ```

4. `make telegram-up`; check with `make telegram-status`; stop with
   `make telegram-down`.

By default an answer has no time limit. Set `TELEGRAM_ANSWER_TIMEOUT` to a
positive number of seconds to cap one run; unset or `0` disables the cap.

How it works: the bot runs the headless agent
(`opencode run --standalone --format json "<expanded /chat-answer prompt>"`)
with a **read-only** OpenCode profile — the agent can read your profile files
and search them, but cannot write, run shell commands, browse, ask questions,
or read paths outside `/work`, so prompt-injection in a forwarded message
cannot act on the machine. Question/draft pairs are audited to `audit.jsonl`
in the `telegram-home` volume.

**Context for answers.** Send `/add-vacancy https://hh.ru/vacancy/<id>`. The bot
first looks the vacancy up in the SQLite state database (by the vacancy id in
the `source` URL, or by company+role for rows without a URL) and uses the
archived `documents/applications/<company>_<role>/job_posting.md` when present —
no hh request. Only when no usable archive exists does it fetch the vacancy
through the shipped `hhru-search` CLI (official hh.ru API; needs
`HH_API_TOKEN` in `.env.docker`). The text is saved as `job-description.md` and
included in every answer until you replace or clear it. A `drafted` database row
(not yet sent) or a missing application row is reported as a warning, never a
refusal. Arbitrary text contexts: `/add-context <name>` and send the text next;
`/contexts` lists what is saved; `/clear-context <name|all>` removes it.
Contexts live in the bot's `telegram-home` volume (`contexts/<user id>/`) — the
repository and the TUI workflow never see them; that isolation is deliberate.

**Model for the bot.** By default it follows the same `MODEL_*` selection
(DeepSeek Flash). Bot-only overrides can point the bot at another model; they
fall back to `MODEL_*`:

```
MODEL_API_KEY=sk-...              # shared fallback key
TELEGRAM_MODEL_SERVICE=deepseek
TELEGRAM_MODEL_NAME=deepseek-flash
TELEGRAM_MODEL_API_KEY=sk-...     # bot-only key
```

`deepseek` is a registry entry (`docker/services.json`) pointing at
`https://api.deepseek.com`; local services need no key. See also
[Cloud providers](#cloud-providers).

## Apply helpers

`/apply` has three deterministic fast paths:

- `posting_prefetch` typed tool (`.opencode/plugins/apply-prefetch.ts` -> `tools/apply_prefetch.py`): archive-first, then the hh.ru API with `HH_API_TOKEN`/`HH_USER_AGENT` from `.env.docker`, then robots.txt + browser headers for other URLs. The posting brief is injected into the prompt; a failed prefetch falls back to `09-web-research.md`.
- `tools/letter_check.py`: mechanical plain-text checks (active template limits, markup, placeholders, em-dashes, banned gap phrases).
- `tools/apply_record.py`: application-row upsert + archive copy, following Step 6b's rules.
- `state_db` typed tool (`.opencode/plugins/state-db.ts` -> `tools/state_db.py`): URL-first `show`/`update`, read-only `query`, and standard `stats`. Application updates never touch the jobs table.

Run `/apply` in a fresh chat. Do not set `subtask: true` on the `apply` command: a build subagent cannot spawn the reviewer, so the letter gets only a self-review (tested 2026-10-21).

## hh.ru auto-apply (`/submit`)

`/submit <url|id>` sends the response on hh.ru through Playwright. The image
installs Playwright and headless Chromium; the browser runs unprivileged with
`--no-sandbox`. `/submit` applies **without** a cover letter by default and
stops (sending nothing) when a vacancy requires one, asks screener questions,
or the resume is missing/ambiguous. `/apply` runs `/submit` automatically when
it receives an hh.ru vacancy; other portals keep the manual instruction.

- `tools/hh_apply.py` drives one vacancy (`check` / `apply` / `attach` /
  `status`) and returns JSON; `tools/hh_apply_record.py` writes the `applied`
  row and the hh negotiation source.
- **One-time login.** The container has no display. Export the session once on a
  machine with a browser (`pip install playwright && python -m playwright
  install chromium`, then `python tools/hh_apply.py login`) and let it save
  `state/hh_storage_state.json` (gitignored). The container reads that file
  through the `.:/work` mount. If it is missing or expired, `/submit` returns
  `NEEDS_LOGIN`.
- **Refresh the session (`/submit-login`).** `/submit-login` in the chat either
  runs the login flow (on a headed machine it opens a browser and waits up to
  `HH_LOGIN_TIMEOUT` seconds for a real sign-in, no `Enter` press) or, when the
  agent is headless, prints the host-side instructions. On the host the shortest
  path is `make login` from the repository root (or
  `python tools/hh_apply.py login`). The session is written to
  `state/hh_storage_state.json` and the container sees it immediately through
  the `.:/work` mount - no copy step. `login` uses a fresh browser context, so
  signing in as a different account overwrites the file and switches accounts.
  `login --from "<path>"` imports an existing Playwright `storage_state.json`
  (validated structurally; cookie values are never printed).
  `HH_API_TOKEN` is a separate credential for `/scrape` and the pre-flight
  vacancy check: update it in `.env.docker` and recreate the container.
- **Resume.** Choose which hh.ru resume to send with `HH_RESUME_TITLE` (or
  `HH_RESUME_ID`) in `.env.docker`. With neither set, the only active resume is
  used; several resumes stop the run.
- Add a later draft to an already-sent response with
  `/submit <url> --attach --letter "<path>"`; hh.ru only allows this when the
  employer permits editing a response, otherwise it reports
  `response_not_editable`.

## Security model

The compose file applies an unprivileged user (UID 1000), a read-only root
filesystem with tmpfs `/tmp` and `/run`, `cap_drop: ALL`, `no-new-privileges`,
`pids_limit: 256`, `mem_limit: 4g`, `cpus: 2.0`, and publishes no ports.

The rendered config also grants the agent full tool permissions
(an allow-all `permissions` rule in `tools/render_opencode_config.py`), so it
runs without approval prompts — the container itself is the boundary. Remove
that rule from the renderer to get prompts back. Within that boundary the agent
can irreversibly change anything under `/work`, including gitignored files such
as `documents/` and the state database, so keep a backup and enable branch
protection on the remote.

Two honest caveats:

- **Egress is not filtered yet.** The container can reach any host on the
  network, and `host.docker.internal` exposes host services (that is how the
  model servers are reached). An allowlist requires an internal network plus a
  forward proxy; validate that OpenCode/Bun honor `HTTP_PROXY` first.
- **This is not a sandbox against prompt injection.** Postings are untrusted
  input and the workflow's defenses are instruction-level. See
  [SECURITY.md](SECURITY.md).

## Updating

- **Repository:** `git fetch upstream && git merge <release>` — nothing to
  rebuild.
- **Image:** `docker compose build --pull` after toolchain changes. To move the
  OpenCode version, change `OPENCODE_VERSION` in the `Dockerfile`; the image
  installs the V2 package `@opencode/cli`. Keep the local
  `.opencode/package.json` (`@opencode/plugin`, gitignored) on the same 2.x
  version when typechecking plugins outside the container.

## Troubleshooting

**"cannot connect to the Docker API"** — Docker Desktop is not running.

**`entrypoint: warning: model server not reachable at ...`** — start LM Studio
with "Serve on Local Network" and check the firewall port. The container still
starts; the agent just has no local model. DeepSeek skips the probe because its
registry entry has `healthCheck: false`. If you use LM Studio and no local
server is running, set `OPENCODE_SKIP_MODEL_CHECK=1` in `.env.docker` to skip
the probe.

**"Failed to initialize OpenTUI render library"** — keep the `exec` flag on the
`/tmp` tmpfs in `docker-compose.yml`; Docker mounts tmpfs `noexec` by default.

**Telegram bot replies "Нет доступа. Ваш id: ..."** — add that id to
`TELEGRAM_ALLOWED_USER_ID` in `.env.docker` and restart the bot
(`make telegram-down && make telegram-up`).

**`telegram-bot: TELEGRAM_BOT_TOKEN is not set`** — create the bot with
[@BotFather](https://t.me/BotFather) and put the token in `.env.docker`.
