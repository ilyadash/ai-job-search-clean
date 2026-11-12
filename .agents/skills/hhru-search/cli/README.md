# hhru-search-cli

Zero-dependency CLI for searching jobs on [hh.ru](https://hh.ru) through the
official HeadHunter API (`https://api.hh.ru`). Runs anywhere `bun` is available.

## Setup (required)

Vacancy search/detail require an access token — anonymous requests are rejected
with HTTP 403 (captcha). Put the credentials in `.env.docker` in the repo root
(gitignored) and recreate the container:

```
HH_API_TOKEN=<your token>
HH_USER_AGENT=hhru-search-cli/1.0 (your@email)
```

`HH_USER_AGENT` is sent as both `User-Agent` and `HH-User-Agent` (hh.ru requires
the latter and asks for an app name plus a contact email). Without
`HH_API_TOKEN`, every search/detail call exits 1 with a `MISSING_CREDENTIALS`
error instead of making an unauthenticated request.

## Usage

```bash
bun run .agents/skills/hhru-search/cli/src/cli.ts search -q "ML-инженер" -l Москва --jobage 14 --limit 20 --format table
bun run .agents/skills/hhru-search/cli/src/cli.ts detail 12345678 --format plain
```

See `../SKILL.md` for the full flag reference and `../url-reference.md` for the
API mapping.

## Development

```bash
bun install          # dev types only
bun run typecheck
bun run test         # live tests skip without HH_API_TOKEN
```
