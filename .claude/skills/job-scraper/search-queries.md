# Search Queries for Job Scraper

<!-- Populated by /setup. Update with /setup --section search when priorities change. -->

## Installed portal CLIs (primary for `/scrape`)

`/scrape` discovers every portal skill under `.agents/skills/*/SKILL.md` and runs its CLI first. Shipped country-agnostic CLIs include `linkedin-search`; market-specific skills (e.g. `hhru-search`) and any skill you add with `/add-portal` are included the same way. You do **not** need a matching `site:` line below for those CLIs to run.

The `site:` query templates in this file are the **WebSearch fallback** — for portals without a CLI, company career pages, or when a CLI fails. For this market, **hh.ru** (largest Russian board) is covered by the installed **`hhru-search` CLI skill** (official API; requires `HH_API_TOKEN` in `.env.docker` — see its SKILL.md Setup). **career.habr.com** (IT niche) is covered by the installed **`habr-career-search` CLI skill** (public pages, no credentials; search/detail only — response to a vacancy is submitted manually on the site).

**Language scope:** write every query category in every language listed in your CLAUDE.md Languages table (typically 1-2, sometimes more). A posting requiring a language you have *not* declared, as a job condition, is excluded before scoring; a posting requiring a *higher level* than you declared in a language you *do* work in is flagged for your own judgment, not excluded — see `04-job-evaluation.md`'s Language Gate, the single source of truth for this rule. Translate each category's keywords rather than machine-translating word-for-word (e.g. "Frontend Developer" -> "Desarrollador Frontend", not a literal word-for-word translation) if you work in more than one language.

## Search Sites

Primary (your market's job boards):
- **[YOUR_JOB_BOARD]** - [your market's main job board]
- **[YOUR_INDUSTRY_JOB_BOARD]** - [industry or tech-niche board]
- **[YOUR_ADDITIONAL_JOB_BOARD]** - [any additional board for your market]
- **linkedin.com/jobs** - LinkedIn job listings (filter: [YOUR_COUNTRY] / [YOUR_CITY]); also covered by `linkedin-search` CLI

Secondary (company career pages via Google):
- Direct Google searches with `site:` filters for known target companies

## Query Categories

Queries are grouped by priority. Write **each category in every language from your Languages table** (see Language scope above): your primary market's language first, then English for remote/global roles. Combine each query with your location terms ([YOUR_CITY]) where the site supports it.

**Search keywords (from the candidate profile):** [YOUR_KEY_SKILL], [YOUR_DOMAIN_KEYWORD_1], [YOUR_DOMAIN_KEYWORD_2]

**Organize by function, not job title.** The same underlying work carries different titles across companies and markets. Name each priority category after the function it covers, and list several plausible job titles as query variants within that category rather than betting an entire priority tier on one exact title string.

### Priority 1: [YOUR_PRIMARY_ROLE_TYPE]

[Your strongest and most desired role direction: what the function is and why it leads the search.]

```
site:[YOUR_JOB_BOARD] "[YOUR_PRIMARY_JOB_TITLE_1]" [YOUR_CITY]
site:[YOUR_JOB_BOARD] "[YOUR_PRIMARY_JOB_TITLE_2]" [YOUR_CITY]
site:[YOUR_INDUSTRY_JOB_BOARD] "[YOUR_DOMAIN_KEYWORD_1]" [YOUR_CITY]
site:linkedin.com/jobs "[YOUR_PRIMARY_JOB_TITLE_1]" [YOUR_COUNTRY]
```

### Priority 2: [YOUR_DOMAIN_EXPERTISE]

Core [YOUR_DOMAIN] direction.

```
site:[YOUR_JOB_BOARD] "[YOUR_DOMAIN_EXPERTISE]" [YOUR_CITY]
site:[YOUR_JOB_BOARD] "[YOUR_DOMAIN_KEYWORD_2]" [YOUR_CITY]
site:[YOUR_INDUSTRY_JOB_BOARD] "[YOUR_DOMAIN]" [YOUR_CITY]
site:linkedin.com/jobs "[YOUR_DOMAIN_EXPERTISE]" [YOUR_COUNTRY]
```

### Priority 3: [YOUR_ADJACENT_ROLE_TYPE]

Adjacent roles that leverage transferable experience (secondary direction).

```
site:[YOUR_JOB_BOARD] "[YOUR_ADJACENT_TITLE_1]" [YOUR_CITY]
site:[YOUR_JOB_BOARD] "[YOUR_ADJACENT_TITLE_2]" [YOUR_CITY]
site:[YOUR_JOB_BOARD] "[YOUR_KEY_SKILL]" [YOUR_CITY]
```

### Priority 4: Broader Technical / Consulting

Wider net.

```
site:[YOUR_JOB_BOARD] "[YOUR_ADJACENT_TITLE_1]" [YOUR_REGION]
site:[YOUR_JOB_BOARD] "[YOUR_ADJACENT_TITLE_2]" [YOUR_REGION]
site:[YOUR_JOB_BOARD] [YOUR_KEY_SKILL] [YOUR_CITY]
```

## Location Filter

When evaluating results, verify the job location against the candidate's stated preferences. Define acceptable areas:
- [YOUR_CITY] (ideal)
- Remote (ideal)
- [ACCEPTABLE_AREA_1] (acceptable)
- [ACCEPTABLE_AREA_2] (acceptable)
- [BORDERLINE_AREA] (borderline)
- [TOO_FAR_AREA] (too far)

## Level Filter

Target level: **[YOUR_TARGET_LEVEL]**. Postings above the target level are excluded client-side. The rule lives in CLAUDE.md's Deal-breakers, and `04-job-evaluation.md`'s Seniority Gate is the single source of truth for classifying a posting.

Exclude when the title carries a senior-or-above marker (Senior, Sr., Lead, Team/Tech Lead, Head, Chief, Principal, Staff, Старший, Ведущий, Главный, Эксперт, Руководитель) or the posting requires more experience than the target band. Within the target band, prefer the level named in your target over the levels below it.

**Приоритет:** [YOUR_SEARCH_PRIORITY]

Apply the filter at the portal wherever the CLI supports it — never invent a flag:

```bash
# hh.ru: exclude the «более 6 лет» bucket (noExperience + 1-3 + 3-6)
bun run .agents/skills/hhru-search/cli/src/cli.ts search -q "ML-инженер" -l Москва --jobage 14 --experience noExperience,between1And3,between3And6 --limit 20 --format json

# Хабр Карьера: intern + junior + middle, Moscow, last 14 days
bun run .agents/skills/habr-career-search/cli/src/cli.ts search -q "python" -l Москва --level intern,junior,middle --jobage 14 --limit 20 --format json
```

- **hhru-search:** `--experience noExperience,between1And3,between3And6` (values are comma-separated; dropping `between3And6` would also cut most Middle roles)
- **habr-career-search:** `--level intern,junior,middle` (one request per level, merged; `intern`/`junior`/`middle`/`senior`/`lead`)
- **linkedin-search:** no level flag — filter on the title and drop the result if the posting states senior/lead requirements

The WebSearch/`site:` fallback queries below cannot carry these filters; apply the title/experience rule to their results manually before adding them to the pool.

## Domain Exclusions

**[YOUR_EXCLUDED_DOMAINS]** is excluded: [why you have no relevant skills and none are planned]. Never add queries targeting it; exclude these results before scoring. This section is the single source of truth for the classification, used by `/scrape` and `/rank`.

Client-side exclusion rules (title + snippet + the posting's own skill tags):
- Exclude when [YOUR_EXCLUDED_DOMAINS] is the core specialization: [core titles and terms for the excluded domain]
- Exclude on **required** [YOUR_EXCLUDED_DOMAINS] signals: [required tools and methods for the excluded domain]
- A [YOUR_EXCLUDED_DOMAINS] mention labelled «будет плюсом» / nice-to-have is **not** an exclusion: keep the posting, score it normally, and treat the skill as a gap
- Exclude when `[YOUR_EXCLUDED_DOMAINS]` appears among the posting's skill tags — hhru `detail` → `keySkills`, habr `detail` → `skills` (tags are treated as required unless the posting itself marks the skill as a bonus)
- Do **not** exclude on a bare `CV` token — on Russian boards it also means «резюме»
- One exception: a peripheral mention of the excluded domain in an otherwise matching role, with no skill tag and no core work in that domain, is not a specialization
- Do **not** rely on portal-side `NOT` operators for this: hh.ru's query language over-matches here (`NOT CV` also drops postings that mention «CV/резюме» in the text), so the run may lose good results

The WebSearch/`site:` fallback queries below cannot carry these rules either — apply them to the results manually.

## Language Filter

Your working languages and levels are in CLAUDE.md's Languages table ([YOUR_LANGUAGES]). When filtering scraped results, apply `04-job-evaluation.md`'s Language Gate: a posting requiring a language you haven't declared at all is excluded; a posting requiring a higher level than you declared in a language you do work in is not excluded, flag it clearly instead (see `job-scraper/SKILL.md`'s Step 3 "Quick Fit Assessment" for how the flag surfaces in `/scrape` output). Postings simply *written* in a language you don't work in, that don't require it on the job, are fine.

## Date Filter

Only include jobs posted within the last 14 days, or with an application deadline that has not yet passed. If a posting date cannot be determined, include it but flag as "date unknown".

## Adapting Queries

If the user specifies a focus area, select queries from the matching category and also generate 2-3 custom queries for that focus. For example:
- "/scrape [focus_area]" -> relevant category queries + custom focus-specific queries
