# hh.ru API reference (for maintainers)

Data source: HeadHunter public API v3, `https://api.hh.ru`.
OpenAPI spec: `https://api.hh.ru/openapi/specification/public` (the exhaustive,
machine-readable parameter list; the Markdown docs at
`https://github.com/hhru/api` migrate to it).

## Authentication and required headers

- All `/vacancies` search and detail requests require
  `Authorization: Bearer <access_token>`.
  Verified live 2026-10-01: anonymous `GET /vacancies` → **HTTP 403**
  `{"errors":[{"type":"forbidden"}]}`, while `GET /areas` stays anonymous (200).
- `HH-User-Agent` header is **required** by the OpenAPI spec for these
  endpoints: "Название приложения и контактная почта разработчика", example
  `MyApp/1.0 (my-app-feedback@example.com)`.
- A plain `User-Agent` header is also required:
  `GET /vacancies` without it → **HTTP 400** `Bad User-Agent header`.
- 403 responses from hh.ru are either auth/permission failures or the captcha
  requirement (`ErrorsCommonCaptchaErrors`): the CLI inspects
  `errors[].type` for `captcha` and reports `CAPTCHA_REQUIRED` vs `FORBIDDEN`.

## Endpoints used

| Purpose | Method + path | Notes |
|---|---|---|
| Search vacancies | `GET /vacancies` | `page` is 0-indexed in the API; the CLI exposes 1-indexed `--page` |
| Vacancy detail | `GET /vacancies/{vacancy_id}` | 404 = not found / no access |
| Area dictionary | `GET /areas` | Anonymous; used for `--location` name resolution |

### `GET /vacancies` parameters the CLI maps

| CLI flag | API param | Notes |
|---|---|---|
| `--query` | `text` | hh.ru query language applies |
| `--location` / `--area` | `area` | numeric id; names resolved via aliases or `/areas` |
| `--jobage` | `period` | days; CLI enforces 1–30 |
| `--experience` | `experience` | `noExperience` / `between1And3` / `between3And6` / `moreThan6` |
| `--employment` | `employment_form` | `FULL` / `PART` / `PROJECT` / `FLY_IN_FLY_OUT` (replaces deprecated `employment`) |
| `--work-format` | `work_format` | `ON_SITE` / `REMOTE` / `HYBRID` / `FIELD_WORK` (replaces deprecated `schedule`) |
| `--schedule-by-days` | `work_schedule_by_days` | `FIVE_ON_TWO_OFF` / `SEVEN_ON_ZERO_OFF` |
| `--order-by` | `order_by` | `relevance` / `publication_time` / `salary_desc` / `salary_asc` (`distance` needs coordinates) |
| `--page` | `page` | API default 0; CLI passes `page - 1` |
| `--per-page` | `per_page` | API default 10, `maximum: 100`; CLI default 100 |
| always | `no_magic` | `true`, so hh.ru never injects filters from natural-language text |

Pagination depth: `page * per_page` must stay ≤ 2000, otherwise the API errors
(and the CLI fails early with `BAD_ARG`).

### Response fields mapped (search items and detail)

`VacanciesVacanciesItem` for search, `VacanciesVacancy` for detail:

| API field | CLI field |
|---|---|
| `id` | `id` |
| `name` | `title` |
| `employer.name` / `employer.alternate_url` | `company` / `companyUrl` |
| `area.name` | `location` |
| `published_at` (`YYYY-MM-DDThh:mm:ss±hhmm`) | `date` (first 10 chars) |
| `alternate_url` | `url` |
| `apply_alternate_url` | `applyUrl` |
| `salary_range` (preferred) or `salary` | `salary` |
| `experience.name` | `experience` |
| `employment_form.name` (fallback `employment.name`) | `employment` |
| `work_format[].name` | `workFormat` |
| `work_schedule_by_days[].name` | `scheduleByDays` |
| `professional_roles[].name` | `professionalRoles` |
| `snippet.requirement` + `snippet.responsibility` | `snippet` (HTML stripped) |
| `description` (HTML) | `description` (tags stripped, paragraphs preserved) |
| `key_skills[].name` | `keySkills` |
| `archived`, `closed_for_applicants` | `archived`, `isActive = !archived && !closed_for_applicants` |
| — | `deadline: null` (hh.ru has **no** application-deadline field; the only `expires_at` in the spec belongs to chat file uploads) |

## Quirks to remember when maintaining the parser

- The API is JSON, not HTML — no markup parsing to maintain. Field renames are
  the breakage mode; when hh.ru deprecates a field it usually adds a
  replacement (e.g. `employment` → `employment_form`, `schedule` →
  `work_format` + `work_schedule_by_days`). Check the OpenAPI spec when a field
  goes missing.
- `archived` is a real boolean in the OpenAPI schema, but the older "nano"
  vacancy representation historically returned the string `"false"` — the CLI
  compares with `!== true`, so either shape maps correctly.
- Unknown query parameters are ignored by hh.ru ("Неизвестные параметры …
  игнорируются"), which is why the CLI rejects unknown flags itself and always
  sends `no_magic=true`: a silently dropped filter is worse than an error.
- Captcha (403) is normally a symptom of a missing/invalid token for this
  method, not of excessive volume; 429 is the rate-limit signal and is retried
  with backoff.
