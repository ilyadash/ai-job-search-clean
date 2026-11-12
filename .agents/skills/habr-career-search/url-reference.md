# Habr Career — URL and parsing reference

Maintainer notes for `habr-career-search`. Everything here was verified against
live pages on **2026-10-01**. When the site changes, this is the file to update
alongside `cli/src/helpers.ts`.

## Access rules

- Public pages, no credentials. `robots.txt` allows `/vacancies` and
  `/vacancies/{id}`.
- `robots.txt` disallows `/vacancies/*/responses` and `/responses` — do not
  automate responses.
- The documented API (`/api/*`, OAuth2) is an employer/CRM integration: it
  exposes the company's own paid vacancies, their incoming responses, and
  dictionaries. There is no candidate-side search endpoint and no
  submit-response endpoint. `/api/v1/...` requests without a session return
  401, and robots.txt disallows `/v1`.
- The CLI sends `Mozilla/5.0 (compatible; habr-career-search-cli/1.0)`,
  `Accept-Language: ru-RU`, retries 429/5xx with exponential backoff, and
  treats 404 as not found.

## Search endpoint

```
GET https://career.habr.com/vacancies?q=<query>&type=all[&city_id=<id>][&qid=<id>][&remote=true][&sort=date][&page=N]
```

| Param | Meaning | Observed values |
|---|---|---|
| `q` | keyword query (title/skill/role). Optional; omit to list everything | any text |
| `type` | listing tab | `all` |
| `city_id` | city filter | Москва=678, Санкт-Петербург=679, Екатеринбург=693, Пермь=722, Томск=736, Уфа=740, Сочи=3394, Липецк=712 |
| `qid` | qualification filter. **One value per request** (comma is not OR) | intern=1, junior=3, middle=4, senior=5, lead=6 |
| `remote` | remote-only | `true` |
| `sort` | result order | `relevance` (default), `date` (newest first) |
| `page` | 1-indexed page, 25 results per page | 1..N |

Notes:
- `qid=2` is unused/empty. Unknown levels must be rejected by the CLI, not
  passed through.
- There is no date/recency filter; recency is client-side over
  `publishedDate.date`.
- Multi-level filtering requires one request per `qid` (the CLI merges and
  dedupes by vacancy id).

## Detail endpoint

```
GET https://career.habr.com/vacancies/<id>
```

A vacancy URL always ends in the numeric id; `detail` accepts the bare id or
the full URL (and 404s otherwise).

## SSR state contract

Every listing/detail page embeds one JSON block:

```html
<script type="application/json" data-ssr-state="true">{ ... }</script>
```

The CLI parses that JSON, never the rendered markup. A page that returns 200
without a parseable blob is treated as a parse failure (`SEARCH_FAILED` /
`PARSE_FAILED`), not as "no results" — a bot-wall or error page renders no
blob.

### Listing state (`/vacancies`)

```
{
  "search": { "query", "order": "relevance"|"date", "filters": {...}, "groups": [...] },
  "filtersData": { "skills", "companies", "location", "locations" },
  "vacancies": {
    "list": [ {
      "id": 1000168684,
      "href": "/vacancies/1000168684",
      "title": "ML-инженер (Python ...)",
      "remoteWork": false,
      "qualification": "Middle",
      "salaryQualification": { "title": "Средний (Middle)", "href": "/vacancies?qid=4" },
      "publishedDate": { "date": "2026-09-29T10:23:58+03:00", "title": "29 сентября" },
      "company": { "id", "alias_name", "href", "title", "accredited" },
      "salary": { "from", "to", "currency", "formatted" },
      "locations": [ { "title": "Москва", "href": "/vacancies?city_id=678" } ],
      "skills": [ { "title": "Python", "href": "..." } ],
      "archived": false
    } ],
    "meta": { "totalResults", "perPage": 25, "currentPage", "totalPages" }
  }
}
```

Mapping used by the CLI:

| CLI field | Source |
|---|---|
| `id` | `vacancies.list[].id` (stringified) |
| `title` | `vacancies.list[].title` |
| `company` | `vacancies.list[].company.title` |
| `companyUrl` | `BASE_URL + company.href` |
| `location` | `locations[].title` joined with ", ", falling back to `location.title` |
| `date` | first 10 chars of `publishedDate.date` (ISO with +03:00 offset) |
| `url` | `BASE_URL + href` |
| `publishedAt` | full `publishedDate.date` (used by `--jobage`) |
| `qualification` | `qualification` |
| `salary` | `salary.formatted` (`""` → null) |
| `remoteWork` | `remoteWork` |
| `skills` | `skills[].title` |
| `archived` | `archived` |

### Detail state (`/vacancies/<id>`)

```
{
  "vacancy": {
    ... same card fields as above ...,
    "description": "<p>...</p><ul><li>...</li></ul>",
    "humanCityNames": "Москва, Санкт-Петербург, Самара",
    "employment": "full_time",
    "archived": false
  },
  "company": { "name", "url", "href", "rating", ... },
  "guest": { "hasResponse", "publishedAt", "file", "href", "author" },
  "similar": [ ... ]
}
```

- `description` is HTML; the CLI converts it to text, keeping `<br>`, block
  closings (`</p>`, `</li>`, `</h3>`, ...) as newlines and decoding entities.
- `isActive` = `vacancy.archived !== true`. Habr archives expired postings;
  there is no deadline field, so `deadline` is always `null`.
- `guest.hasResponse` reflects whether the logged-out visitor has responded —
  null for guests; it is not parsed.

## Verified quirks

- `sort=date` combined with `page=N`, `qid`, and `city_id` all compose
  correctly (verified 2026-10-01).
- `remoteWork`/`remote_work`/`work_format` params do nothing; the working
  remote filter is `remote=true`.
- `filtersData.locations` is empty on plain listing pages, so city names are
  resolved from the alias table in `helpers.ts` (or a numeric id), never
  guessed.
- Occasional transient pages return 200 without the state blob (observed once
  during reconnaissance). `--jobage 14` re-fetches pages until the window is
  drained, so a single bad page can surface as an error; `htmlFetch`'s backoff
  plus the one-retry parser guard in the health check cover the common flakes.
