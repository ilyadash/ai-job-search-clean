# habr-career-search-cli

CLI for searching jobs on [Career.Habr](https://career.habr.com) — the IT job
board of Habr. No authentication, no API key, **zero runtime dependencies**: it
runs with just `bun`.

Search and detail only. The site's documented API
([career.habr.com/info/api](https://career.habr.com/info/api)) is an
employer/CRM integration (OAuth2, company's own vacancies and their incoming
responses) and offers no candidate-side search or apply endpoint, so this CLI
reads the public listing pages instead. Responding to a vacancy
("Откликнуться") is a manual step on the site: the form is behind a login, the
site's robots.txt disallows `/vacancies/*/responses`, and this CLI never
authenticates.

## Data source

Each public page embeds its full server-side state in one
`<script type="application/json" data-ssr-state="true">` block; the CLI parses
that JSON rather than the rendered markup. Endpoints, query parameters, and the
observed schema are documented in [`../url-reference.md`](../url-reference.md).

## Usage

```bash
bun run src/cli.ts search -q "python" -l Москва --level junior,middle --jobage 14 --limit 20
bun run src/cli.ts search -q "NLP" --level junior,middle --remote --format table
bun run src/cli.ts detail 1000168741 --format plain
```

Flags: `--query/-q`, `--location/-l` (city name or numeric `city_id`),
`--level` (intern, junior, middle, senior, lead), `--remote`, `--jobage`
(client-side freshness window), `--sort relevance|date`, `--page`, `--limit/-n`,
`--format json|table|plain`.

Run the tests offline:

```bash
bun test
bun run typecheck
```

Personal use only — keep volume low, no bulk collection. Read the code before
running it; see the repo's contributing notes on borrowed portal skills.
