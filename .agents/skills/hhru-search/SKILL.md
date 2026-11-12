---
name: hhru-search
version: 1.0.0
description: >
  Use this skill whenever the user wants to search for jobs in Russia, find
  Russian job listings, or look up a specific hh.ru vacancy — even if they do
  not mention hh.ru explicitly. Invoke for open positions, vacancies, and
  hiring in Moscow, Saint Petersburg, or any Russian city or region, and for
  remote roles on the Russian market. Trigger phrases include: hh.ru, hhru,
  headhunter, вакансии, найти работу, работа в России, поиск работы, вакансия,
  резюме, ML-инженер вакансии, Python вакансии, remote работа, job search
  russia, russian jobs, jobs in moscow.
context: fork
enabled: true  # set to false to keep this portal installed but have /scrape skip it
allowed-tools: Bash(bun run .agents/skills/hhru-search/cli/src/cli.ts *)
---

# hh.ru Search Skill

Search live job listings from **hh.ru** (HeadHunter), the largest Russian job
board, through its official public API (`https://api.hh.ru`). Unlike the other
shipped portals, hh.ru's vacancy search is **credentialed**: anonymous requests
are rejected with HTTP 403 (captcha), so a token is required.

## Setup (required once)

The CLI reads credentials **only** from environment variables — never a flag:

| Variable | Required | Meaning |
|---|---|---|
| `HH_API_TOKEN` | yes | Access token for your hh.ru application/user (from https://dev.hh.ru) |
| `HH_USER_AGENT` | recommended | `AppName/1.0 (contact@email)` — sent as `User-Agent` and `HH-User-Agent`; without it the CLI sends `hhru-search-cli/1.0 (personal job search)` |

In this Docker-first repo, put them in `.env.docker` (gitignored, loaded by
`docker-compose.yml` via `env_file`) and **recreate the container** so the
processes see the variables:

```
HH_API_TOKEN=<your token>
HH_USER_AGENT=hhru-search-cli/1.0 (your@email)
```

If `HH_API_TOKEN` is unset, the CLI exits 1 with a `MISSING_CREDENTIALS` error
naming the variable — it never falls through to an unauthenticated request that
would fail confusingly with a captcha.

## Commands

### Search job listings

```bash
bun run .agents/skills/hhru-search/cli/src/cli.ts search [flags]
```

Key flags:
- `--query <text>` / `-q <text>` — keywords (title, skill, role). Optional.
- `--location <place>` / `-l <place>` — city/region name (`"Москва"`, `"Moscow"`, `"Санкт-Петербург"`) or a numeric area id. Optional.
- `--area <id>` / `-a <id>` — numeric hh.ru area id (alternative to `--location`).
- `--jobage <days>` — posted within N days (1–30). Maps to hh.ru `period`.
- `--experience <ids>` — comma-separated: `noExperience`, `between1And3`, `between3And6`, `moreThan6`.
- `--employment <ids>` — comma-separated: `full`, `part`, `project`, `fly-in-fly-out`.
- `--work-format <ids>` — comma-separated: `remote`, `hybrid`, `onsite`, `field-work`.
- `--schedule-by-days <ids>` — comma-separated: `five-on-two-off`, `seven-on-zero-off`.
- `--order-by <mode>` — `relevance` (default), `publication_time`, `salary_desc`, `salary_asc`.
- `--page <n>` — 1-indexed page. Default 1.
- `--per-page <n>` — results per request, 1–100. Default 100.
- `--limit <n>` / `-n <n>` — cap on results emitted (may fetch extra pages).
- `--format json|table|plain` — default `json`.

### Fetch full job detail

```bash
bun run .agents/skills/hhru-search/cli/src/cli.ts detail <id|url> [--format json|plain]
```

Accepts a bare id (`12345678`), an `hh.ru/vacancy/...` URL, an
`api.hh.ru/vacancies/...` URL, or a `vacancyId=` query link. Returns the full
description (HTML converted to text), key skills, experience, employment, work
format, salary, apply link, and an `isActive` flag (`false` when the vacancy is
archived or closed for applicants).

## Usage examples

```bash
# ML roles in Moscow, posted in the last 14 days
bun run .agents/skills/hhru-search/cli/src/cli.ts search -q "ML-инженер" -l Москва --jobage 14 --limit 20 --format table

# NLP roles in Saint Petersburg, remote only
bun run .agents/skills/hhru-search/cli/src/cli.ts search -q "NLP" -l "Санкт-Петербург" --work-format remote --format json

# Python backend roles for juniors
bun run .agents/skills/hhru-search/cli/src/cli.ts search -q "Python" -l Москва --experience noExperience,between1And3 --format table

# Full details for one posting
bun run .agents/skills/hhru-search/cli/src/cli.ts detail https://hh.ru/vacancy/12345678 --format plain
```

## Output formats

| Format | Best for |
|--------|----------|
| `json` | Default — `/scrape` consumption, passing ids to `detail` |
| `table` | Quick human-readable scanning |
| `plain` | Reading a single job's full detail (`detail` command) |

Search JSON: `{ "meta": { "count", "found", "page", "pages", "per_page" }, "results": [...] }`.
Every result carries at least `id`, `title`, `company`, `location`, `date`
(publication date), and `url` — missing values are `null`, never omitted.
Errors go to **stderr** as `{ "error": "...", "code": "..." }` with exit 1.

## Notes

- **Token required.** Anonymous search returns HTTP 403 captcha; 401/403 from
  the API surface as `UNAUTHORIZED` / `FORBIDDEN` / `CAPTCHA_REQUIRED` errors.
- **`no_magic=true` is always sent** so hh.ru never silently rewrites the query
  into extra filters the caller did not ask for.
- **No deadline field.** hh.ru vacancies have no application-deadline field, so
  `deadline` is always `null` in detail output; postings are archived instead.
- **Pagination depth** is capped by hh.ru at 2000 results; `--page` ×
  `--per-page` beyond that exits 1 with `BAD_ARG`.
- **Rate limits**: 429/5xx are retried with exponential backoff (max ~6 tries).
- **Location resolution**: `Москва`/`Moscow` and `Санкт-Петербург`/`СПб`
  resolve from a built-in alias table; other names resolve through the public
  `/areas` dictionary (anonymously accessible), and numeric ids pass through.
- `career.habr.com` (IT niche) is not covered by this CLI — `/scrape` falls
  back to WebSearch for it.
