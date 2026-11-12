# /submit-login - Refresh the hh.ru Session used by `/submit`

You are refreshing the saved hh.ru browser session that `/submit` drives with
Playwright. `$ARGUMENTS` may carry:

- `--from <path>` - import an existing Playwright `storage_state.json` instead of
  logging in interactively (the path is resolved from the repository root;
  absolute paths are accepted too).
- `--no-verify` - skip the follow-up session check.

The session file is `state/hh_storage_state.json` (gitignored). It is a
credential: never print its contents, never ask the user to paste cookies into
the chat.

Follow these steps exactly in order.

---

## Step 0: Detect where the agent runs

Run the probe (use `python` instead of `python3` on Windows):

```bash
python3 -c "import os, platform; print('headed' if platform.system() == 'Windows' or os.environ.get('DISPLAY') else 'headless')"
```

- `headed` - continue to Step 1.
- `headless` - continue to Step 2.

---

## Step 1: Headed - run the login

Import an existing artifact:

```bash
python3 tools/hh_apply.py login --from "<path>" --json
```

Otherwise run the interactive login:

```bash
python3 tools/hh_apply.py login --json
```

Tell the user a browser window opens: they sign in (password/captcha/2FA/SMS)
and the script saves `state/hh_storage_state.json` as soon as it detects the
signed-in page. It waits up to `HH_LOGIN_TIMEOUT` seconds (300 by default).

Read the JSON `status`:

- **`OK`** - continue to Step 3 (unless `--no-verify`).
- **`ERROR`** / `reason=login_required` - the login did not finish or the state
  could not be saved. Report `message` and let the user retry; do not claim the
  session was refreshed.

A fresh browser context is used, so the user can sign in as a **different
account** and overwrite the previous file.

---

## Step 2: Headless (container) - print instructions

Do **not** launch a browser: this environment has no display. Tell the user to
run, from the repository root (the folder with `Makefile` and `tools/`):

1. `make login` (host-side; on Linux with a different interpreter:
   `make login PYTHON=python3`), or `python tools/hh_apply.py login`.
2. Sign in in the opened browser (captcha/2FA/SMS). The script waits and saves
   `state/hh_storage_state.json` when it detects the login.
3. The container reads that file through the `.:/work` mount; nothing needs to
   be copied.
4. To use an existing Playwright `storage_state.json`, put it inside the
   repository and run `/submit-login --from "<path relative to the repo root>"`.
5. Never paste cookie contents into the chat.

Then continue to Step 3 (unless `--no-verify`): the file the user just saved on
the host is already visible in the container.

---

## Step 3: Verify (unless `--no-verify`)

```bash
python3 tools/hh_apply.py verify --json
```

- **`OK`** - the session is active. Report the account only when `message`
  carries a name after «сессия активна:»; hh.ru often shows a generic
  «Резюме и профиль» label, so say «сессия активна» and skip the account.
- **`NEEDS_LOGIN`** - the session is missing, expired or unreadable. Report it
  and repeat Step 1/2 once; if it fails again, stop and say the session needs a
  manual refresh.

---

## Step 4: Report

Summarise in a short block:

- where the session is saved (`state/hh_storage_state.json`);
- which account, if it is known;
- next step: `/submit <url>` (or `/apply <url>` for a full application).

---

## Important Rules

1. **The storage_state file is a credential.** Never print it, never quote
   cookie values, never ask the user to paste cookies. `--from` validates only
   the structure (`cookies`/`origins`).
2. **This command refreshes the browser session only.** `HH_API_TOKEN` (used by
   `/scrape` and the `/submit` pre-flight vacancy check) is separate: update it
   in `.env.docker` and recreate the container (`docker compose up -d`).
3. **Do not hardcode an absolute repository path** in commands or docs: use the
   repository root, `make login`, or a path relative to it.
4. **Never edit the session file by hand** and never create it from scratch;
   `login` or `login --from` is the only writer.
