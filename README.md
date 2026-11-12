<p align="center">
  <img src="assets/mascot/pip_flight_loop.gif" alt="Pip, the courier bird" width="200">
</p>

# AI Job Search

*The job search that runs on your machine.*

[![CI](https://github.com/ai-job-search-dev/ai-job-search/actions/workflows/ci.yml/badge.svg)](https://github.com/ai-job-search-dev/ai-job-search/actions/workflows/ci.yml)

An AI-powered job application framework built on [Claude Code](https://claude.com/claude-code), with additive [OpenCode 2](https://opencode.ai/v2/docs) compatibility. Fork it, fill in your profile, and let your agent evaluate job postings, write cover letters, prepare you for interviews, and (on hh.ru) send the response for you. You apply with your existing CV: the workflow never tailors or recompiles it.

> Note: This is an independent open-source project and is not affiliated with, endorsed by, sponsored by, or maintained by Anthropic. Anthropic and Claude Code are referenced only to describe the toolchain this workflow uses.
>
> This project has **no affiliated cryptocurrency, token, or paid sponsorship program**. Anything claiming otherwise is unauthorized and should be treated as a scam. The only way to support the project is contributing on GitHub.

## What this is

A structured workflow that turns Claude Code or OpenCode into a full-stack job application assistant. The core workflow (self-profiling, fit evaluation, and the drafter-reviewer application pipeline) is **language- and country-agnostic**. The job portal search skills cover some markets out of the box (`linkedin-search`, plus market-specific skills such as `hhru-search` and `habr-career-search` for Russia), and the pattern is designed to be extended to any local job board with `/add-portal`.

```
/setup          /scrape              /apply <url>
  |                |                     |
  v                v                     v
Fill in        Search job           Evaluate fit
your profile   portals              Score & recommend
  |                |                     |
  v                v                     v
Profile        Present matches      Draft cover letter
files ready    with fit ratings     (plain text; hh.ru auto-submits)
                   |                     |
                   v                     v
               Pick a match         Reviewer agent critiques
               -> /apply            -> Revise -> Final output
```

The framework encodes career guidance best practices, including structured evaluation criteria, forward-looking cover letter framing, and optional salary benchmarking.

## Prerequisites

- [Claude Code](https://claude.com/claude-code) (CLI). Claude Code has no free tier: you need a Claude Pro/Max/Team subscription or Anthropic API credits (pay-per-token, usually cheaper for occasional use). Using a different agent tool (Codex, Antigravity, Gemini CLI)? Start at [`AGENTS.md`](AGENTS.md) - the portal search skills work there out of the box, and [community forks](https://github.com/ai-job-search-dev/ai-job-search/discussions/78) adapt the full workflow.
- Python 3.10+
- [Bun](https://bun.sh) (for job search CLI tools)
- Optional: LaTeX distribution with `lualatex` — [TeX Live](https://tug.org/texlive/), [MacTeX](https://tug.org/mactex/), [TinyTeX](https://yihui.org/tinytex/), or [MiKTeX](https://miktex.org/) — only for the reference CV template library (`/add-template-cv`) and for `tools/verify_pdf.py`. `/apply` neither drafts nor compiles a CV: you apply with your existing CV, and the cover letter is plain text pasted into the portal's field, so an application needs no TeX engine. If using a minimal TeX install such as TinyTeX or BasicTeX, install the extra packages listed in [SETUP.md](SETUP.md#minimal-tex-install-tinytexbasictex).
- Optional: `pip install pypdf` for PDF text extraction in `tools/verify_pdf.py` and the template reference docs (BSD; no Poppler required). Poppler `pdftotext` remains a fallback (macOS: `brew install poppler`, Debian/Ubuntu: `apt install poppler-utils`, Windows: `choco install poppler`). If both are missing, the CV reference checks degrade to a visual read.
- For hh.ru search: an `HH_API_TOKEN` (create an application at [dev.hh.ru](https://dev.hh.ru)). Anonymous search returns HTTP 403, so `hhru-search` exits with `MISSING_CREDENTIALS` until the token is set. `/submit` additionally needs a saved browser session; `/setup` (or `/submit-login`) creates it.

## Quick start

> 🎥 **Prefer to see it in action first?** [The Next New Thing did a hands-on walkthrough](https://www.youtube.com/watch?v=HoVxjMNFYv4) of how the workflow is actually used, from setup to a finished application (recorded August 2026 - commands may have evolved since).

### 1. Fork and clone

```bash
gh repo fork ai-job-search-dev/ai-job-search --clone
cd ai-job-search
```

> [!IMPORTANT]
> **A fork of this repo is always public** — GitHub does not allow private forks of
> public repositories — and `/setup` (step 3 below) writes your personal data (name,
> contact details, employment history, salary expectations) into **tracked** files.
> If this copy is for your own job search rather than for contributing changes back,
> use a **private repository** with this repo as `upstream` instead — the two-minute
> recipe is in [SETUP.md section 8](SETUP.md#8-pulling-upstream-updates-into-your-fork),
> and every update workflow works identically. Fork only to contribute.

### 2. Install job search tools

```bash
python3 tools/install_portal_clis.py   # Windows: python tools\install_portal_clis.py
```

It runs `bun install` in every portal CLI under `.agents/skills/*/cli/` — discovered, not listed, so a portal you add with `/add-portal` or copy from another fork is included on a fresh clone. Every install runs with `--ignore-scripts`, and a CLI whose `package.json` declares an install-time lifecycle script, `trustedDependencies` or `workspaces`, or that has a `bunfig.toml` or `.npmrc` beside it, is skipped and reported rather than run. `--dry-run` shows what it would install.

The shipped `linkedin-search`, `hhru-search`, and `habr-career-search` CLIs have zero runtime dependencies and run with plain `bun`; `bun install` only pulls TypeScript dev types, so the install is optional for them. `hhru-search` additionally needs `HH_API_TOKEN` in the environment (see [Prerequisites](#prerequisites)).

### 3. Set up your profile

Claude Code:
```bash
claude
# Then inside Claude Code:
/setup
```

OpenCode:
```bash
opencode
# Then inside OpenCode:
/setup
```

`/setup` offers three paths: read your `documents/` folder if you have one populated (CV PDF, LinkedIn export, diplomas, reference letters, past applications), import a single CV pasted in chat, or walk through an interview. It auto-detects what you have and asks. Documents-folder mode is idempotent and safe to re-run as you add more material; see `documents/README.md` for the layout.

At the end it asks whether `/submit` may respond to hh.ru vacancies on your behalf. Answer **Yes** and `/setup` saves your hh.ru browser session via `/submit-login`, which lets `/apply` send hh.ru responses automatically; answer **No** and `/submit` stays unavailable, with `/apply` falling back to manual submission. The decision is stored as `hh.ru auto-submit: Enabled|Disabled` in `CLAUDE.md`, and re-running `/setup` can flip it later.

### 4. Search for jobs

```bash
/scrape
```

The command works the same way in OpenCode. This searches multiple job portals for positions matching your profile, deduplicates results, and presents them sorted by fit. Pick a match to run `/apply` on it directly — or, when a scrape returns more jobs than you want to eyeball, run `/rank` to batch-score them all against the fit framework and get a ranked shortlist first.

### 5. Apply to a job

```bash
/apply https://hh.ru/vacancy/12345678
```

If the URL can't be fetched (some job portals block automated access), you can paste the job description directly instead:

```bash
/apply <paste the full job description here>
```

The command works the same way in OpenCode. This runs the full workflow: evaluate fit, draft the cover letter, review with a second agent, revise, and present the final output. The candidate applies with their existing CV, which this workflow does not modify.

For an hh.ru vacancy with auto-submit enabled, `/apply` also sends the response through `/submit` - without the cover letter by default - and reports the result (`APPLIED`, or `ACTION_REQUIRED` when the vacancy demands a letter or extra fields). Send the draft with `/submit <url> --letter <path>`, or add it to an already-sent response with `/submit <url> --attach --letter <path>`. Every other portal keeps the manual instruction: open the posting, attach your CV, paste the letter.

Postings are treated as untrusted input (the workflow follows no instructions embedded in them and fetches no links from their body), but agentic defenses are instruction-level, not a sandbox - on an unfamiliar job board, skim what was fetched and written before you hit send. Details in [SECURITY.md](SECURITY.md).

### Optional: run the agent in Docker

If you would rather keep the agent off your host, the repository ships a Docker setup. OpenCode and the full toolchain (Bun, Python, TeX Live, poppler) run in an unprivileged, read-only container with this repository as its only host mount. The default model is DeepSeek Flash (cloud); an optional LM Studio server can stay on the host and keep using the GPU. See [DOCKER.md](DOCKER.md) for host setup, the security model, and troubleshooting.

## Other commands

`/setup`, `/scrape`, and `/apply` form the core workflow. Fourteen more commands extend it once your profile is in place. All commands work identically in OpenCode — the same `/command` syntax loads the same workflow files.

- **`/interview`** preps you for a scheduled interview on a tracked application. It builds a stage-specific prep pack from the application's archive (the exact posting, the CV and cover letter the interviewer actually read, feedback recorded from earlier rounds), researches the company and interviewers with a verify-before-use rule, maps likely questions to your STAR examples, and offers a mock interview following the roleplay protocol in `07-interview-prep.md`. Gaps get honest bridge answers, never invented experience.
- **`/outcome`** records what happened to an application - interview stages, offers, rejections, silence. It archives the submitted CV, cover letter, and posting text into `documents/applications/<company>_<role>/`, keeps structured status/stages and dated notes in the SQLite state database (`application_events`), and keeps `outcome.md` as undated narrative feedback only. It also owns the stretch before there is an outcome to record: `/outcome followup` surfaces open applications that have gone quiet (default 10 days), drafts a short channel-appropriate follow-up in your writing style using only claims from the materials you already submitted (drafts only, never sends; at most twice per application), and offers a thank-you note in the same turn an interview stage is recorded. Once a few applications resolve, it points you back to `/setup` to calibrate the fit framework from what actually got interviews.
- **`/weekly-review`** produces a manual weekly funnel and cover-letter review from the SQLite state database: it prints Markdown tables in chat and saves `reports/weekly-YYYY-MM-DD.md`. It is the analysis layer over `/html-report`'s optional dashboard.
- **`/db`** is the explicit SQLite entry point: `show`/`update` an application by vacancy URL, `stats` for the standard metrics, or a read-only `query`. It backs the `state-db` skill and the `state_db` typed tool; updates touch only the application, its stages, and its events.
- **`/rank`** bridges `/scrape` and `/apply`: it batch-scores all newly scraped postings against the fit framework (parallel agents fetch each posting and score the five evaluation dimensions) and returns a ranked shortlist with honest per-job strengths and gaps. Deal-breakers veto, deadlines get urgency flags, dead postings get marked expired. Pick a number and it hands off to the full `/apply` workflow.
- **`/expand`** enriches your profile by scanning public sources you've already linked in it (GitHub repos, portfolio site, Kaggle, Google Scholar) and looking up syllabi for named courses and certifications. Discovered competencies are added to your profile with a source tag. Useful right after `/setup` to surface skills that documents alone don't make explicit.
- **`/upskill`** analyzes the gap between your profile, your tracked job postings, and your ranked-but-untracked postings (`/rank`'s recorded gaps in the jobs table) — or a single posting via `/upskill <URL>`. Produces a prioritized heatmap of skill gaps and a learning plan with web-searched study resources and time estimates. Useful for career planning between applications.
- **`/html-report`** generates a self-contained HTML dashboard from the SQLite state database and the application archives — stat cards, status/sector/channel/funnel charts (inline SVG, no external dependencies), and a filterable applications table. Opens directly in a browser, fully offline. Re-run it any time after `/apply` or `/outcome` adds new entries.
- **`/submit`** sends a response to an hh.ru vacancy with Playwright, using the saved session. By default it applies without the cover letter; `--letter <path>` pastes one into the form, and `--attach --letter <path>` adds one to a response already sent. It honors the `hh.ru auto-submit:` flag in `CLAUDE.md` and stops when auto-submit was disabled at setup. `/apply` calls it automatically for hh.ru postings; run it directly to resend or to attach a letter later.
- **`/submit-login`** refreshes the saved hh.ru browser session (`state/hh_storage_state.json`, gitignored): interactive login on a machine with a display, host instructions when the agent is headless, and `--from <path>` to import an existing Playwright `storage_state.json`. Use it when `/submit` reports `NEEDS_LOGIN`, or to switch accounts. `HH_API_TOKEN` is separate and lives in `.env.docker` for the container.
- **`/chat-answer`** drafts a short, honest answer to a question an AI interviewer or recruiter chatbot has just asked. Paste its message, get 2-4 sentences grounded in your profile files, and send it yourself; sensitive topics such as salary come with a warning.
- **`/add-template-cv`** registers a CV template (LaTeX, Typst, or another toolchain): source extension, compile command, fonts, style rules, page limit, plus a mandatory test compile. In this fork it manages the CV template as a reference library — `/apply` neither drafts nor compiles a CV, so the registered template is not invoked by an application. Its text-only sibling **`/add-template-cover-letter`** registers a cover-letter structure — a plain-text skeleton plus content rules, a body word limit and any portal character cap — with no compile step, ever, and does wire into `/apply`. See [Custom templates](#custom-templates) below.
- **`/add-portal`** generates a job-portal search skill for a job board in your market. It investigates the portal (search URL pattern, result structure, access rules), scaffolds the CLI skill from the same structure as the shipped ones, and test-runs a live query before registering. See [Job search tools](#job-search-tools) below.

`/reset` is also available, see [Starting over](#starting-over) below.

## File structure

```
ai-job-search/
├── CLAUDE.md                          # Main candidate profile + workflow rules
├── .claude/
│   ├── commands/
│   │   ├── apply.md                   # /apply workflow (drafter-reviewer + automatic hh.ru submission)
│   │   ├── setup.md                   # /setup onboarding (documents folder, CV import, or interview)
│   │   ├── submit.md                  # /submit send an hh.ru response via Playwright
│   │   ├── submit-login.md            # /submit-login refresh the saved hh.ru browser session
│   │   ├── expand.md                  # /expand competency enrichment from documents and online presence
│   │   ├── add-template-cv.md            # /add-template-cv register a custom CV template (LaTeX, Typst, ...)
│   │   ├── add-template-cover-letter.md # /add-template-cover-letter register a plain-text cover-letter template
│   │   ├── add-portal.md              # /add-portal generate a job-portal search skill for your market
│   │   ├── rank.md                    # /rank triage scraped jobs into a ranked shortlist
│   │   ├── outcome.md                 # /outcome undated narrative, archive materials
│   │   ├── interview.md               # /interview stage-specific prep pack + mock interview
│   │   ├── chat-answer.md             # /chat-answer short answer to a live chat question
│   │   ├── html-report.md             # /html-report generate application tracker dashboard
│   │   ├── db.md                      # /db SQLite state by URL
│   │   ├── weekly-review.md           # /weekly-review funnel and cover-letter report
│   │   └── reset.md                   # /reset wipe profile, templates, memory, documents, state, backups
│   ├── agents/
│   │   ├── application-reviewer.md    # Independent cover-letter reviewer (/apply)
│   │   ├── hh-applier.md              # hh.ru form-filling subagent (/submit)
│   │   ├── posting-fetcher.md         # Read-only posting fetch (/apply, /rank)
│   │   └── posting-scorer.md          # Fit-scoring subagent (/rank)
│   ├── skills/
│   │   ├── job-application-assistant/  # Core application skill
│   │   │   ├── SKILL.md               # Skill definition
│   │   │   ├── 01-candidate-profile.md # Your education, experience, skills
│   │   │   ├── 02-behavioral-profile.md# PI/DISC/personality assessment
│   │   │   ├── 03-writing-style.md    # Tone, structure, do's and don'ts
│   │   │   ├── 04-job-evaluation.md   # Scoring framework for job fit
│   │   │   ├── 05-cv-templates.md     # CV template reference (not used by /apply)
│   │   │   ├── 06-cover-letter-templates.md # Plain-text cover letter guide
│   │   │   ├── 07-interview-prep.md   # STAR examples + interview framework
│   │   │   ├── 08-application-forms.md# Application form fields and portal limits
│   │   │   ├── 09-web-research.md     # Web research and fetching rules
│   │   │   └── 10-reviewer.md         # Reviewer agent instructions
│   │   ├── job-scraper/               # Job search orchestration + search-queries.md
│   │   ├── state-db/                  # /db skill: SQLite schema and read-only queries
│   │   ├── document-extraction/       # Text extraction for .doc/RTF/PDF scans (OCR)
│   │   └── upskill/                   # /upskill skill gap analysis and learning plan
│   └── settings.json                  # Claude Code permissions (shared, scoped)
├── opencode.json                      # OpenCode 2 config (bridges to .claude/commands/)
├── AGENTS.md                          # Thin pointer for non-Claude runtimes
├── .opencode/plugins/                 # Typed tools: apply-prefetch, hh-apply, state-db
├── .agents/skills/                    # Job portal CLI tools
│   ├── hhru-search/                   # hh.ru job listings (Russia, official API, needs HH_API_TOKEN)
│   ├── habr-career-search/            # Career.Habr IT job board (Russia, public pages)
│   ├── linkedin-search/               # LinkedIn public job listings (country-agnostic)
│   └── …                              # any market-specific skill you add with /add-portal
├── cv/
│   ├── main_example.tex               # moderncv LaTeX template (master CV, stays at the root)
│   └── <company>/
│       └── main_<company>_<role>.tex  # Per-company CVs (reference library, not generated by /apply)
├── cover_letters/
│   └── <company>/
│       └── cover_<company>_<role>.txt # Per-company plain-text cover letters, pasted into portal forms
├── templates/                         # Custom CV and cover-letter templates (/add-template-cv, /add-template-cover-letter)
│   └── README.md                      # Folder layout instructions
├── documents/                         # Career source materials for /setup Path A and /expand
│   ├── README.md                      # Folder layout instructions
│   ├── cv/                            # Master CV (PDF or .tex)
│   ├── linkedin/                      # LinkedIn profile export (PDF)
│   ├── diplomas/                      # Degree certificates and transcripts
│   ├── projects/                      # Project summaries and portfolio notes
│   ├── postings/                      # Pasted or saved job postings
│   ├── references/                    # Reference letters
│   └── applications/                  # Application archives (<company>_<role>/)
├── company_research/                  # Per-company research from /apply and /interview (personal, gitignored)
├── reports/                           # /weekly-review and /html-report output (personal, gitignored)
├── state/                             # SQLite tracker, migrations, saved hh.ru session (personal data gitignored; migrations tracked)
├── job_scraper/                       # Scraper scratch space (job state now lives in SQLite)
├── upskill/                           # /upskill report output (markdown reports per run)
├── tests/                             # Python unittest suite run by CI on Linux 3.10-3.14 and Windows
├── docker/                            # Container entrypoint + service model config
├── Dockerfile                         # OpenCode + toolchain image (see DOCKER.md)
├── docker-compose.yml                 # Compose service for the agent container
├── Makefile                           # Docker/tooling shortcuts (make help)
├── .github/workflows/                 # ci.yml, release.yml, upstream-watch.yml
├── salary_lookup.py                   # Salary benchmarking tool (BYO data)
├── tools/
│   ├── state_db.py                    # SQLite state CLI (show/update/stats/query)
│   ├── hh_apply.py                    # Playwright hh.ru response form (used by /submit)
│   ├── hh_apply_record.py             # Record hh.ru submission results
│   ├── letter_check.py                # Deterministic cover-letter checks
│   ├── apply_prefetch.py              # /apply posting fetch and normalization
│   ├── apply_record.py                # /apply draft recording
│   ├── posting_guard.py               # Posting integrity gate (hidden text, instruction-like lines)
│   ├── install_portal_clis.py         # bun install for every portal CLI (--ignore-scripts)
│   ├── check_framework_version.py     # CI check: framework_version bumped when skill files change
│   ├── check_upstream_updates.py      # Preview which personalized files an upstream update touches
│   ├── convert_salary_excel.py        # Convert salary Excel to JSON
│   ├── lint_skills.py                 # CI lint for skills, commands, settings.json
│   ├── robots_check.py                # Gate the browser-header retry against robots.txt
│   ├── security_guards.py             # CI guards: permission allowlist, gitignore rules, manifests
│   ├── upstream_triage.py             # Sort upstream commits into worth-reviewing vs probably-skip
│   ├── verify_layout.py               # Measure a compiled PDF's page layout (holes, orphans, footer collisions)
│   ├── verify_pdf.py                  # Verify a compiled PDF's page count and extractable text
│   ├── README_SALARY_TOOL.md          # Salary tool setup instructions
│   └── …                              # fetch/parse helpers, Telegram gateway
└── SETUP.md                           # Detailed setup guide
```

## How `/apply` works

The `/apply` command runs a **drafter-reviewer workflow** that produces a cover letter; the candidate applies with their existing CV (`cv/`):

1. **Parse** the job posting (URL or text)
2. **Evaluate fit** against your profile (skills, experience, culture, location, career alignment)
3. **Draft** a plain-text cover letter (body only, ready to paste into the portal's field)
4. **Spawn a reviewer agent** that researches the company and critiques the draft
5. **Revise** based on the reviewer's feedback
6. **Check the letter as text**: length limits, structure, language matches the posting, no markup, final proofread
7. **Submit on hh.ru** when the posting is an hh.ru vacancy and auto-submit is enabled: `/submit` sends the response without the letter by default and reports `APPLIED` or `ACTION_REQUIRED`
8. **Present** the final output with a verification checklist

All claims in the cover letter are verified against your actual profile. The system never fabricates skills or experience. On other portals the workflow stops at the paste-ready letter and the manual submission instruction.

### Using with OpenCode

This project works with [OpenCode 2](https://opencode.ai/v2/docs) as an additive alternative to Claude Code. The canonical workflow files live in `.claude/` — OpenCode reads them directly via `{file:...}` references in `opencode.json`, so there is no parallel config tree to maintain.

```bash
opencode
# Inside OpenCode:
/setup
/scrape
/apply <job URL or description>
/rank
/interview
```

Commands, prompts, and output contracts are identical. OpenCode just needs one extra file (`opencode.json`) that tells it where to find each workflow. See `AGENTS.md` for the architecture.

> **Note:** The OpenCode `permissions` array in `opencode.json` uses a curated allowlist for `shell` commands (matching upstream's `.claude/settings.json` posture). Only workflow-essential commands are auto-approved: `bun run`, `bun install`, `lualatex`, `pdftotext`, `python salary_lookup.py`, and the workflow scripts `tools/letter_check.py`, `tools/apply_record.py`, `tools/state_db.py`, `tools/hh_apply.py`, `tools/hh_apply_record.py`. Other commands prompt for confirmation. `external_directory` asks before touching paths outside the project.

### What makes this workflow different

- **Drafter-reviewer separation.** The drafter writes; a second Claude agent, spawned with a fresh context, researches the company and critiques the draft. The drafter then revises. This catches missed keywords, weak framing, and generic language that a single pass often leaves in.
- **Token-efficient reviewer dispatch.** The reviewer agent receives the draft inline rather than re-reading it, and the verification checklist runs once at the end of the workflow rather than being duplicated by both agents.

## Customization

### Which files to edit manually

If you prefer editing files directly instead of using `/setup`:

| File | What to change |
|------|---------------|
| `CLAUDE.md` | Your full profile (name, education, experience, skills, goals) |
| `01-candidate-profile.md` | Structured version of your CV data |
| `02-behavioral-profile.md` | Your behavioral assessment or self-assessment |
| `04-job-evaluation.md` | Skill match areas, career goals, motivation filters |
| `05-cv-templates.md` | CV template reference and profile statements (not used by `/apply`) |
| `07-interview-prep.md` | Your STAR examples from actual experience |
| `.claude/skills/job-scraper/search-queries.md` | Job search queries for your skills and location |

### Updating your search queries

As your priorities evolve, you can reconfigure just the job search without re-running the full profile setup:

```
/setup --section search
```

This re-runs the search configuration interview: which roles to target, which skills to search for, which locations, and which portals. It also suggests role types you may not have considered based on your profile.

### Custom templates

The cover letter is plain text (`06-cover-letter-templates.md`) pasted into the portal's application field; it has no compile step. The candidate applies with their existing CV (`cv/`), and this fork's `/apply` does not draft or compile CVs.

`/add-template-cv` remains available as a library for managing the existing CV template — LaTeX, [Typst](https://typst.app/), or any other toolchain that compiles to PDF from the command line — but it is **not wired into `/apply`** in this fork:

```
/add-template-cv
```

Point it at your source file (a `.tex` file plus any `.cls`/`.sty` files or bundled fonts; a `.typ` file plus any local packages; or an equivalent for another toolchain). The command interviews you for the template's instructions — source extension, compile command, fonts and where they live, style rules to preserve, hard page limit — stores everything under `templates/`, and runs a mandatory test compile. Templates are stored with `[PLACEHOLDER]` tokens instead of personal data, so they're safe to commit and share.

- `/add-template-cv --list` shows registered templates
- `/add-template-cv --use <name>` switches between them
- `/add-template-cv --use default` reverts to the stock moderncv template

If you prefer doing it by hand, the manual route still works: update the guidance in `05-cv-templates.md`.

#### Custom cover-letter templates

Cover letters stay plain text — the portal field is text, so there is nothing to compile. To register your own structure for them, run:

```
/add-template-cover-letter
```

Point it at a letter you like (a `.txt` file, pasted text, or an existing `cover_letters/**/cover_*.txt`; convert `.docx`/`.pdf` sources to text first). It captures the block structure (greeting, opening, motivation, bullet block or 1-2 brief projects, closing), the body word limit (250-300 by default) and any portal character cap (e.g. hh.ru's cover-letter field), the content rules, and the `[PLACEHOLDER]` tokens; stores a profile-agnostic `template.txt` plus a manifest under `templates/cover_letters/`; runs textual checks (plain text, body only, word and character counts, no unfilled tokens — there is no compile step to run); and activates it for `/apply` via a managed block in `06-cover-letter-templates.md`. The same flags work: `/add-template-cover-letter --list`, `--use <name>`, and `--use default` to revert to the stock structure.

Works the same way in OpenCode — both template commands load their workflow files.

### Job search tools

The market-specific portal skills in `.agents/skills/` (e.g. `hhru-search`) demonstrate the pattern for building a job-portal integration for a specific market. If your market isn't covered, run:

```
/add-portal
```

Give it your local job board's URL. The command investigates the portal (search-URL pattern, result-page structure, robots.txt/access rules), scaffolds a CLI skill with the same structure, commands, and output contract as the shipped ones, and test-runs a live query before registering anything. Auth-walled portals are declined, and portals with restrictive terms get a prominent personal-use-only warning in the generated skill. The generated skill is market-specific and lives in your fork; the generator itself is the universal part.

Maintaining a fork adapted to your market or language? Add it to the [Community forks & adaptations](https://github.com/ai-job-search-dev/ai-job-search/discussions/78) thread so others can find it.

For **country-agnostic** starting points, use the one field- and country-agnostic skill the repo ships:

- **`linkedin-search`** — built on LinkedIn's public, unauthenticated `jobs-guest` endpoints. Field-agnostic, **zero runtime dependencies** (runs with just `bun`), and takes the search location as an explicit flag, so it works for any market out of the box (`-l "Berlin, Germany"`, `-l "Mumbai, Maharashtra, India"`, `-l "Remote"`, …). Intended for **personal use only** — automated access is against LinkedIn's Terms of Service, so keep volume low. See `.agents/skills/linkedin-search/SKILL.md`.

### Extending the framework: portals, templates, criteria - and borrowing from other forks

Everything above adds up to an extension model, so here it is stated plainly. The framework has three extension points, and none of them require touching upstream:

1. **Portal skills** - the module system for job boards. Every `*-search` skill is a self-contained folder under `.agents/skills/` with the same contract (a `search`/`detail` CLI, `--format json|table|plain` output, an `enabled:` flag in its `SKILL.md`, its own tests). `/scrape` auto-discovers any installed skill that follows the contract - nothing to register, nothing to wire up. `/add-portal` generates new ones; the [community portal index](https://github.com/ai-job-search-dev/ai-job-search/discussions/78) catalogs the ones other forks have built.
2. **Document templates** - `/add-template-cv` registers any CV toolchain that compiles to PDF from the command line, LaTeX or otherwise (a reference library in this fork: `/apply` neither drafts nor compiles a CV). Cover letters are plain text by design; `/add-template-cover-letter` registers their plain-text structure and content rules, and is wired into `/apply` (no compile step exists or is ever added).
3. **Evaluation criteria** - deal-breakers and preferences in your profile are free-form, and the evaluation rubric scores against whatever you put there. "Strong parental-leave terms", "minimum salary X per my union's scale", "no on-call" - each is one profile line, no code, and it carries real weight in `/rank` and `/apply` fit evaluations. Language is the one deal-breaker type with dedicated, structured handling: `/setup` captures every language you work in and your level (asked directly, or inferred from your CV/LinkedIn export) into a `Languages` table, and the Language Gate (`04-job-evaluation.md`) hard-rejects a posting that requires a language you haven't declared at all, while flagging - not auto-rejecting - one that asks for a higher level than you declared in a language you do work in, so a borderline case (a strict "fluent" bar against your own B1/B2, say) gets your judgment instead of a silent drop.

**Borrowing a portal skill from another fork** is the intended way to get a board that upstream doesn't ship: find it in the [portal index](https://github.com/ai-job-search-dev/ai-job-search/discussions/78), open that fork, and copy the one folder into your own `.agents/skills/`. Before you run it:

- **Read the code.** All of it - these CLIs run pre-approved on your machine (`.claude/settings.json` allowlists them) against your career data. Check that the only network calls go to the job board it claims to search, that `package.json` has no `dependencies` and no lifecycle scripts (`postinstall` etc.), and that nothing reads or writes outside its own folder.
- **Run its tests offline** (`bun test` in the skill's `cli/` directory) - a well-built skill's tests pass with no network access.
- Check the `enabled:` flag and the skill's own ToS notes.

The copy step is manual on purpose. Your settings already allow installed portal skills to run without asking each time - so an installer that fetched them from third-party repos for you would skip the one check that matters: you, reading the code first. There isn't one, and that's a security decision rather than a missing feature.

Market-specific *data sources* (a national salary database, local award-rate tables) follow the same pattern as portals: they belong in a market fork, shared via [#78](https://github.com/ai-job-search-dev/ai-job-search/discussions/78), not upstream.

### Salary benchmarking

The salary tool works with any salary data you provide (union statistics, Glassdoor exports, personal research, etc.). See `tools/README_SALARY_TOOL.md` for the expected format and setup. If you don't have salary data, the salary step is simply skipped.

### Starting over

To wipe your personal data and start fresh:

```
/reset              # full wipe: profile + templates + memory + documents + state + backups
/reset profile      # clears skill files, preserves framework rules
/reset templates    # deletes per-company CVs/letters, restores the master CV
/reset memory       # blanks CLAUDE.md and removes the name from agent markdown
/reset documents    # deletes files from documents/ folder
/reset state        # deletes the SQLite tracker, hh session, and derived reports
/reset backups      # deletes everything under backups/, keeps the .gitkeep placeholder
```

`/reset` shows exactly what will be deleted. The bare command asks `Да`/`Нет` and then runs all six branches; a single branch requires you to type `RESET` to confirm. Nothing is deleted until you confirm.

### Staying up to date

Upstream moves fast. Rather than pulling raw `master` and hoping, update your fork to a tagged [release](../../releases) - a weekly checkpoint that passed CI, with its changes listed on the release page. `python3 tools/check_upstream_updates.py` previews exactly which of your personalized files an update touches before you merge, and `python3 tools/upstream_triage.py` sorts the commits you're behind into "worth reviewing" vs "probably skip" (a weekly workflow can post this to a rolling issue). Full walkthrough in [SETUP.md, section 8](SETUP.md#8-pulling-upstream-updates-into-your-fork).

## Tips for better results

### Profile depth matters

The single biggest factor in output quality is how much detail you put into your profile. A thin profile produces generic applications; a detailed one enables genuinely tailored results.

- **Role descriptions:** Don't just list job titles. Describe what you actually did in each position: specific projects, tools used, responsibilities, and measurable achievements. The more material you provide, the more precisely the system can reframe your experience for different roles.
- **Skills in context:** Instead of listing "Python" or "project management," describe how and where you applied them. "Built ML pipelines for customer churn prediction in Python using scikit-learn" gives the system far more to work with than "Python, machine learning."
- **All onboarding paths work:** Whether you point `/setup` at your `documents/` folder, paste a single CV, or walk through the interview, the principle is the same: richer input produces sharper output.

### Career path discovery

The framework supports two distinct modes of job searching:

- **Explicit targeting:** You know which roles or sectors you want. The system helps refine and prioritize based on fit.
- **Latent opportunity discovery:** By analyzing your full history (not just job titles, but the actual work you did), the system can surface career paths you haven't considered. Transferable skills that map to unexpected industries, patterns in what you enjoyed or excelled at, or emerging roles that combine your domain expertise with new technology.

To get the most from this, invest time during `/setup` in describing not just your experience, but what energized you, what drained you, and what you'd want more of. This context directly shapes how the system evaluates fit and which roles it surfaces during `/scrape`.

## Contributing

Thinking about a PR? Read [CONTRIBUTING.md](CONTRIBUTING.md) first - it explains what gets merged, what lives in forks, and why.

## Acknowledgements

- [Mikkel Krogholm](https://github.com/mikkelkrogsholm) ([skills repo](https://github.com/mikkelkrogsholm/skills)) for the job search CLI skills
- Built with [Claude Code](https://claude.com/claude-code) by [Anthropic](https://anthropic.com)

## License

MIT
