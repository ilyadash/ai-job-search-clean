---
name: habr-career-search
version: 1.0.0
description: >
  Use this skill whenever the user wants to search for IT/tech jobs on Habr
  Career (career.habr.com, Хабр Карьера), find Russian tech vacancies, or look
  up a specific Habr Career posting — even if they do not mention the site
  explicitly. Trigger phrases include: habr career, хабр карьера, карьера хабр,
  вакансии хабр, вакансии it, найти работу в it, поиск работы разработчик,
  python вакансии, ml вакансии, nlp вакансии, data scientist вакансии,
  вакансии москва, удалённая работа, remote it, middle вакансия, junior
  вакансия, отклик на вакансию.
context: fork
enabled: true  # set to false to keep this portal installed but have /scrape skip it
allowed-tools: Bash(bun run .agents/skills/habr-career-search/cli/src/cli.ts *)
---

# Habr Career Search Skill

Search live job listings from **career.habr.com** (Хабр Карьера), the IT/tech
job board of Habr. No authentication, no API key, and **zero runtime
dependencies** — it runs with just `bun`.

> **Why not the official API?** The documented API at
> [career.habr.com/info/api](https://career.habr.com/info/api) is an
> employer/CRM integration (OAuth2): it exposes the company's own paid
> vacancies, their incoming responses, and dictionaries. It has no
> candidate-side vacancy search and no endpoint to submit a response, so this
> skill reads the public listing pages instead. See
> [url-reference.md](url-reference.md) for the page/SSR contract.

> **Search and detail only.** Responding to a vacancy ("Откликнуться") happens
> manually on the site: the form is behind a login and the site's robots.txt
> disallows `/vacancies/*/responses`. This skill never authenticates and never
> submits a response. `/apply` prepares the CV and cover letter, then the user
> submits through the vacancy page.

## When to use this skill

- Search IT/tech vacancies on Habr Career by keyword, city, level, or remote
- Filter by qualification (intern/junior/middle/senior/lead) and recency
  (`--jobage`, applied client-side — the site has no recency filter)
- Fetch one posting's full description by id or URL

## Commands

### Search job listings

```bash
bun run .agents/skills/habr-career-search/cli/src/cli.ts search [flags]
```

Key flags:
- `--query <text>` / `-q <text>` — keywords (title, skill, role). Optional.
- `--location <place>` / `-l <place>` — city name (`"Москва"`, `"Moscow"`,
  `"СПб"`) or a numeric `city_id`. Optional; omit for all of Russia.
- `--level <names>` — comma-separated qualification values:
  `intern`, `junior`, `middle`, `senior`, `lead`. Optional. The site accepts
  one `qid` per request, so a multi-level value issues one request per level
  and merges the results.
- `--remote` — remote-only vacancies (the site's `remote=true`).
- `--jobage <days>` — posted within N days. Applied **client-side**; implies
  `--sort date` unless `--sort` is given.
- `--sort <mode>` — `relevance` (default) | `date`.
- `--page <n>` — 1-indexed page (25 results/page). Default 1.
- `--limit <n>` / `-n <n>` — cap on results emitted (client-side).
- `--format json|table|plain` — default `json`.

### Fetch full job detail

```bash
bun run .agents/skills/habr-career-search/cli/src/cli.ts detail <id|url> [--format json|plain]
```

Accepts a bare id (`1000168741`) or a `career.habr.com/vacancies/...` URL.
Returns the full description (HTML converted to text), company, city names,
qualification, employment type, salary, skills, and an `isActive` flag
(`false` when the vacancy is archived). `deadline` is always `null` — Habr
vacancies carry no application deadline; postings are archived instead.

## Usage examples

```bash
# Junior/Middle Python roles in Moscow, posted in the last 14 days
bun run .agents/skills/habr-career-search/cli/src/cli.ts search -q "python" -l Москва --level junior,middle --jobage 14 --limit 20 --format json

# NLP/AI roles, remote, new this week
bun run .agents/skills/habr-career-search/cli/src/cli.ts search -q "NLP" --level junior,middle --remote --jobage 7 --format table

# All middle Data Scientist postings, newest first
bun run .agents/skills/habr-career-search/cli/src/cli.ts search -q "Data Scientist" --level middle --sort date --limit 10 --format table

# Full details for one posting
bun run .agents/skills/habr-career-search/cli/src/cli.ts detail https://career.habr.com/vacancies/1000168741 --format plain
```

## Output formats

| Format | Best for |
|--------|----------|
| `json` | Default — `/scrape` consumption, passing ids to `detail` |
| `table` | Quick human-readable scanning |
| `plain` | Reading a single job's full detail (`detail` command) |

Search JSON: `{ "meta": { "count", "page", "total" }, "results": [...] }`.
Every result carries at least `id`, `title`, `company`, `location`, `date`
(`YYYY-MM-DD`), and `url` (missing values are `null`, never omitted), plus
`qualification`, `salary`, `remoteWork`, `skills`, `publishedAt`, `archived`.
Errors go to **stderr** as `{ "error": "...", "code": "..." }` with exit 1.

## Notes

- **No credentials.** Public pages only; the site's `/api/v1/...` endpoints are
  session-authenticated and are never called.
- **Recency is client-side.** The listing has no date filter; `--jobage` keeps
  results whose `publishedAt` is inside the window after fetching, and with
  `--sort date` paging stops once a full page is older than the window.
- **Bounded paging.** One command fetches at most 10 pages (250 listings).
- **Level ids:** intern=1, junior=3, middle=4, senior=5, lead=6.
- **City ids:** the small alias table covers Москва (678), Санкт-Петербург
  (679), Екатеринбург, Пермь, Томск, Уфа, Сочи, Липецк; pass a numeric
  `--location` for any other city.
- **Personal use only.** Keep volume low and don't use it for bulk data
  collection; the CLI sends an honest User-Agent and backs off on 429/5xx.
- **Responding to a vacancy is manual.** Use the vacancy URL; the site's
  response form requires login.
