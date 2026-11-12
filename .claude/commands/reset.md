# /reset - Reset Candidate Data and Start Over

You are resetting parts of the job search framework back to a blank state so the user can start fresh with `/setup`.

**This command is destructive.** Nothing is deleted until the user explicitly confirms. Follow these steps exactly in order.

---

## Step 0: Parse Scope from Arguments

Check `$ARGUMENTS` for a scope keyword:

- `profile` — clears candidate data from the skill files only (framework structure preserved).
- `templates` — deletes per-company CVs and cover letters, restores the master CV to the stock template, and resets registered CV/cover-letter templates to placeholders.
- `memory` — blanks the candidate profile section in `CLAUDE.md` and removes the candidate's name from agent markdown files (`03-writing-style.md`; verifies `AGENTS.md`).
- `documents` — deletes user-provided files from the `documents/` folder only.
- `state` — deletes the SQLite tracker, the hh.ru browser session, debug captures, and derived reports.
- `backups` — deletes everything under `backups/` and recreates its `.gitkeep` placeholder.
- `all` — all six of the above.

If `$ARGUMENTS` is empty, this is a **full wipe**: equivalent to `all`, but Step 1/2 begin with the full warning and a `Да`/`Нет` confirmation.

If `$ARGUMENTS` contains an unrecognized keyword, ask:

> **What would you like to reset?**
>
> - **`profile`** — Clears candidate data from the skill files (profile, behavioral, STAR examples, profile statements, personalized evaluation criteria, search queries). The framework structure is preserved.
> - **`templates`** — Deletes per-company CVs and cover letters and restores the master CV / registered templates to placeholders. Use this before handing a fork over.
> - **`memory`** — Blanks `CLAUDE.md` and removes the candidate's name from agent markdown files.
> - **`documents`** — Deletes files you placed in `documents/` (CV PDFs, LinkedIn export, diplomas, references, project summaries, pasted postings, application archives). Folder structure and `README.md` are preserved.
> - **`state`** — Deletes the SQLite tracker, the hh.ru session, debug captures, and derived reports.
> - **`backups`** — Deletes everything under `backups/` and recreates its `.gitkeep` placeholder.
> - **`all`** — All six of the above.
>
> Reply with one of the seven keywords above.

Wait for the user's response before continuing.

---

## Step 1: Show Exactly What Will Be Cleared

Before doing anything, show the user precisely what will be wiped. Only show the sections for the selected scope (all six for a full wipe).

### If scope includes `profile`:

Read the current state of these files and report whether each has content or is already empty:

- `.claude/skills/job-application-assistant/01-candidate-profile.md`
- `.claude/skills/job-application-assistant/02-behavioral-profile.md`
- `.claude/skills/job-application-assistant/04-job-evaluation.md` *(personalized match areas, career goals, and life-situation constraints only — the scoring framework is preserved)*
- `.claude/skills/job-application-assistant/05-cv-templates.md` *(profile statements section and the contact block inside the LaTeX template only — framework structure is preserved)*
- `.claude/skills/job-application-assistant/06-cover-letter-templates.md` *(signature in the plain-text sample only — framework structure is preserved)*
- `.claude/skills/job-application-assistant/07-interview-prep.md` *(STAR examples and STAR candidates sections only — framework structure is preserved)*
- `.claude/skills/job-scraper/search-queries.md` *(role titles, domain keywords, and location terms only — query structure is preserved)*

This list must stay in step with what `/setup` Step 3 populates: every skill file it writes candidate data into is cleared here.

Present as:

```
## Profile reset will clear:

- 01-candidate-profile.md — [has content / already empty]
  Full file will be replaced with a blank template.

- 02-behavioral-profile.md — [has content / already empty]
  Full file will be replaced with a blank template.

- 04-job-evaluation.md — [has personalized criteria / already blank]
  Your match areas, career goals, energizing/draining tasks, life-situation
  constraints, and the Location & Logistics lines (commute range, relocation
  stance) will be restored to placeholders. The scoring framework is preserved.

- 05-cv-templates.md — [has profile statements or contact details / already blank]
  Profile statement templates will be cleared and the contact block in the LaTeX
  template restored to placeholders. LaTeX structure and tailoring guidelines are preserved.

- 06-cover-letter-templates.md — [has a personalized signature / already blank]
  The signature in the plain-text sample will be restored to `[YOUR_NAME]`.

- 07-interview-prep.md — [has STAR examples / already blank]
  STAR examples and any STAR candidate stubs will be cleared. The framework is preserved.

- job-scraper/search-queries.md — [has personalized queries / already blank]
  Your job boards, role titles, domain keywords, city, commute tiers, target
  level, excluded domains, and working languages will be restored to
  placeholders. The query structure is preserved.

The following files are NOT touched (they contain framework rules, not candidate data):
  - 03-writing-style.md — the writing rules stay; any scattered name is cleared by `memory`.

Personal data outside the skill files is covered by the other branches:
  - CLAUDE.md and 03-writing-style.md's name → `memory`
  - cv/ and cover_letters/ → `templates`
```

### If scope includes `templates`:

List per-company folders and the personal fields that will be reset. Use Glob to enumerate `cv/<company>/` and `cover_letters/<company>/`.

Present as:

```
## Templates reset will:

Delete per-company artifacts:
  cv/<company>/            (each folder: .tex, .pdf, .aux, .log, .out)
  cover_letters/<company>/ (each folder: .txt, .tex, .pdf)

Delete build artifacts:
  cv/main_example.pdf, main_example.aux, main_example.log, main_example.out

Restore to placeholders (NOT deleted):
  cv/main_example.tex — replaced with the pristine stock template
    (\name{[First]}{[Last]}, [Your Address, City, Country],
     [+XX XXXXXXXXXX], [your.email@example.com]).
  templates/cv/*/template.tex and templates/cover_letters/*/template.txt —
    any embedded name/contact data replaced with [PLACEHOLDER] tokens.

Preserved:
  templates/*/TEMPLATE.md, templates/README.md
```

Restoring `cv/main_example.tex` needs `upstream/master`. If `git show upstream/master:cv/main_example.tex` fails, say so in the preview and tell the user the master CV will be replaced with the bundled stock template (`tools/stock_main_example.tex`) - no personal name, contacts, history, or publications remain.

### If scope includes `memory`:

Read `CLAUDE.md` and `03-writing-style.md` and report whether they contain the candidate's real name, and whether `AGENTS.md` is clean.

Present as:

```
## Memory reset will clear:

- CLAUDE.md — [has the candidate profile / already blank]
  The "## Candidate Profile ... ## Repo Structure" block will be replaced with a
  placeholder skeleton. The workflow rules and repo structure are preserved.

- 03-writing-style.md — [has the candidate name / already clean]
  The scattered name will be replaced with [YOUR_NAME]. The writing rules are preserved.

- AGENTS.md — [clean / check manually]
  Expected to contain no personal data; left unchanged.
```

### If scope includes `documents`:

Use Glob to list all files present in `documents/cv/`, `documents/linkedin/`, `documents/diplomas/`, `documents/references/`, `documents/projects/`, `documents/postings/`, and `documents/applications/`.

Include nested and hidden user entries in the inventory. Each subfolder's tracked `.gitkeep` is a scaffold placeholder: exclude it from the deletion list and from the empty/non-empty decision, and preserve it.

Present as:

```
## Documents reset will delete:

documents/cv/
  - [filename] or "(empty)"

documents/linkedin/
  - [filename] or "(empty)"

documents/diplomas/
  - [filename] or "(empty)"

documents/references/
  - [filename] or "(empty)"

documents/projects/
  - [filename] or "(empty)"

documents/postings/
  - [filename] or "(empty)"

documents/applications/
  - [subfolder/filename] or "(empty)"

documents/README.md — NOT deleted (instructions file)
```

If all document subfolders are already empty, state "All document subfolders are already empty — nothing to delete." and skip the confirmation step for this scope.

### If scope includes `state`:

List the present state files and derived reports.

Present as:

```
## State reset will delete:

- state/job_search.sqlite        [present / absent]
- state/hh_storage_state.json   [present / absent]  (hh.ru browser session)
- state/hh_debug/               [present / absent]
- state/import-report.json      [present / absent]
- reports/weekly-*.md and root funnel-*.md  [list or "(none)"]

NOT deleted:
  state/migrations/  (schema used to recreate the tracker on next use)
```

### If scope includes `backups`:

List the present backup files and folders.

Present as:

```
## Backups reset will delete:

- backups/<everything>          [list, or "(empty)"]

NOT deleted:
  backups/.gitkeep  (recreated as an empty placeholder)
```

---

## Step 2: Require Explicit Confirmation

**Full wipe (`$ARGUMENTS` empty or `all`):** state what will be deleted in one short paragraph, remind the user of the per-branch arguments (`profile`, `templates`, `memory`, `documents`, `state`, `backups`), then ask:

> **This cannot be undone. Continue with the full wipe?**
>
> Reply **`Да`** to confirm, or **`Нет`** to cancel.

Wait for the user's response.

- Exactly `Да` (case-insensitive) → proceed to Step 3 and run all six branches in order: `profile → templates → memory → documents → state → backups`.
- Anything else → abort and tell them "Reset cancelled. Nothing was changed."

**Single branch (`$ARGUMENTS` is one keyword):** present the confirmation prompt:

> **This cannot be undone.**
>
> Type **`RESET`** (all caps) to confirm, or anything else to cancel.

Wait for the user's response.

- Exactly `RESET` → proceed to Step 3 for that branch.
- Anything else → abort and tell them "Reset cancelled. Nothing was changed."

---

## Step 3: Execute the Reset

Run only the sections for the selected scope. For a full wipe, run them in this order so each preview stays truthful: `profile → templates → memory → documents → state → backups`.

### Profile reset

Every skill file under `.claude/skills/job-application-assistant/` opens with a `---` frontmatter block carrying its `framework_version` marker. That marker is framework data, not candidate data: `tools/check_framework_version.py` fails a file without it, and `tools/check_upstream_updates.py` cannot compare the file against upstream. Never remove or rewrite it - the two full-file replacements below keep it and replace only what follows.

**For `01-candidate-profile.md`**, keep the file's `---` frontmatter block exactly as it is and replace everything below it with:

```markdown
# Candidate Profile

<!-- Run /setup to populate this file -->

## Identity

### Languages

| Language | Level | Notes |
|----------|-------|-------|

## Education

## Professional Experience

## Independent Projects

## Technical Skills

## Publications

## Awards

## References
```

**For `02-behavioral-profile.md`**, keep the file's `---` frontmatter block exactly as it is and replace everything below it with:

```markdown
# Behavioral Profile

<!-- Run /setup to populate this file -->

## Overview

## Core Behavioral Drives

## Strongest Behaviors

## How You Work Best

## Growth Areas (frame positively in applications)

## Mapping to Job Posting Language

## Management Style Preferences

## Using This in Applications
```

**For `04-job-evaluation.md`**, restore the values `/setup` Step 3.4 personalized back to their placeholder tokens, leaving every surrounding line untouched:

| Line to restore | Token |
|---|---|
| `**Strong match areas:**` | `[YOUR_PRIMARY_SKILLS]` |
| `**Moderate match areas:**` | `[YOUR_SECONDARY_SKILLS]` |
| `**Weak match areas:**` | `[SKILLS_YOU_LACK]` |
| `**Strong:**` (Experience Match) | `[YOUR_DIRECT_EXPERIENCE_DOMAINS]` |
| `**Moderate:**` (Experience Match) | `[YOUR_ADJACENT_EXPERIENCE]` |
| `**Entry-level:**` (Experience Match) | `[ROLES_WITH_LIMITED_EXPERIENCE]` |
| the three `**Career goals:**` bullets | `[YOUR_CAREER_GOAL_1]`, `[YOUR_CAREER_GOAL_2]`, `[YOUR_CAREER_GOAL_3]` |
| `- Tasks that energize:` | `[YOUR_ENERGIZING_TASKS]` |
| `- Tasks that drain:` | `[YOUR_DRAINING_TASKS]` |
| `- **Security**:` | `[YOUR_FINANCIAL_SITUATION_CONTEXT]` |
| `- **Flexibility**:` | `[YOUR_SCHEDULE_CONSTRAINTS]` |
| `- **Professional development**:` | `[YOUR_GROWTH_PRIORITIES]` |
| `- Within commute range (` … `): PASS` | `[YOUR_COMMUTE_RANGE]` |
| `- Requires relocation: FLAG — ` … | `[YOUR_RELOCATION_STANCE]` |

Also remove any `## Calibration from Past Applications` section, which `/setup` Path A writes from the user's own application outcomes.

**Dimension 4 (Location & Logistics)** carries two personalized lines — the commute range and the relocation stance. Restore them per the two rows above; leave the `Remote / hybrid` and `Frequent international travel` lines intact (they are framework, not candidate data).

Leave the rest of `04-job-evaluation.md` intact: the five scoring dimensions and their score bands, the weighting, the Seniority Gate, the Language Gate, the red-flag guidance, the Company Research Checklist and cache schema, and the salary benchmark section. If `/setup` Step 3.4 ever personalizes a value not in the table above, add it here too.

**For `05-cv-templates.md`**, locate the section that begins with the line `**Create 2-3 profile statement templates for your main role types:**` and extends through the role-specific template blocks, including any statements labeled *[Used for: <company>_<role>]* that `/setup` Path A extracted from archived applications. Stop before the paragraph that begins "Statements labeled" - that is framework guidance, not candidate data. Replace only that section with:

```markdown
**Create 2-3 profile statement templates for your main role types:**

<!-- SETUP: These are populated based on your background -->
```

Then restore the contact block inside the file's LaTeX template to its placeholder tokens: `\name{[FIRST_NAME]}{[LAST_NAME]}`, `\address{[YOUR_ADDRESS]}{}{}`, `\phone[mobile]{[YOUR_PHONE]}`, `\email{[YOUR_EMAIL]}`, the `\extrainfo{...}` line's `[YOUR_LINKEDIN_URL]` and `[YOUR_GITHUB_URL]`, and `[YOUR_NAME]` in the `pdftitle`. Leave all other content in `05-cv-templates.md` intact.

**For `06-cover-letter-templates.md`**, restore the signature in the plain-text sample to its placeholder token: replace the name after "С уважением," with `[YOUR_NAME]`. Leave all other content in `06-cover-letter-templates.md` intact - the letter structure, opening patterns, and closing formulations are framework, not candidate data. If `/setup` Step 3.6 ever personalizes anything beyond the signature, add it here too.

**For `07-interview-prep.md`**, locate and remove:
- The entire `## Ready-Made STAR Examples` section and all numbered STAR examples under it
- Any `## STAR Candidates (Complete Manually)` section added by `/setup` Path A

Replace with:

```markdown
## Ready-Made STAR Examples

<!-- Run /setup to populate STAR examples from your actual experience -->
```

Leave all other content in `07-interview-prep.md` intact (STAR format explanation, tough questions, questions to ask interviewers, phone/video tips, follow-up etiquette, roleplay guidelines).

**For `.claude/skills/job-scraper/search-queries.md`**, restore the values `/setup` Step 3.9 personalized back to their placeholder tokens:

- **Search Sites**: the board names back to `[YOUR_JOB_BOARD]`, `[YOUR_INDUSTRY_JOB_BOARD]`, `[YOUR_ADDITIONAL_JOB_BOARD]`, and the LinkedIn filter back to `[YOUR_COUNTRY]` / `[YOUR_CITY]`.
- **Query Categories**: the four priority headings back to `[YOUR_PRIMARY_ROLE_TYPE]`, `[YOUR_DOMAIN_EXPERTISE]`, `[YOUR_ADJACENT_ROLE_TYPE]`, and `Broader Technical / Consulting`; inside the query blocks, the titles, skills, and domain terms back to `[YOUR_PRIMARY_JOB_TITLE_1]`, `[YOUR_PRIMARY_JOB_TITLE_2]`, `[YOUR_ADJACENT_TITLE_1]`, `[YOUR_ADJACENT_TITLE_2]`, `[YOUR_KEY_SKILL]`, `[YOUR_DOMAIN_KEYWORD_1]`, `[YOUR_DOMAIN_KEYWORD_2]`, `[YOUR_DOMAIN]`, and the location terms back to `[YOUR_CITY]`, `[YOUR_COUNTRY]`, `[YOUR_REGION]`.
- **Location Filter**: the commute tiers back to `[YOUR_CITY]`, `[ACCEPTABLE_AREA_1]`, `[ACCEPTABLE_AREA_2]`, `[BORDERLINE_AREA]`, `[TOO_FAR_AREA]`.
- **Level Filter**: the target level back to `[YOUR_TARGET_LEVEL]` and the «Приоритет» note back to `[YOUR_SEARCH_PRIORITY]`; leave the seniority-marker list and the portal CLI examples intact (framework).
- **Domain Exclusions**: the excluded domain back to `[YOUR_EXCLUDED_DOMAINS]`; leave the client-side exclusion mechanics and the nice-to-have exception intact.
- **Language Filter**: the working-language list back to `[YOUR_LANGUAGES]`.
- Remove any extra priority categories or translated query duplicates `/setup` added beyond the four shipped tiers.

Leave the rest of the file intact: the portal-CLI and WebSearch-fallback explanation, the Language scope note, the "organize by function, not job title" guidance, and the Date and Adapting Queries sections.

### Templates reset

First restore the master CV from the pristine upstream template. In a normal checkout the `upstream` remote provides it; if it is missing or the fetch failed, the command warns and replaces `cv/main_example.tex` with the bundled stock template (`tools/stock_main_example.tex`), so no personal data remains. The restore writes to a temporary file so a failed `git show` cannot truncate the existing CV.

```bash
if git show upstream/master:cv/main_example.tex > cv/main_example.tex.tmp 2>/dev/null; then
  mv cv/main_example.tex.tmp cv/main_example.tex
else
  rm -f cv/main_example.tex.tmp
  printf 'Note: upstream/master unavailable - replacing cv/main_example.tex with the bundled stock template.\n' >&2
  python tools/sanitize_master_cv.py
fi
```

Then delete the per-company artifacts and the master CV's build outputs. Run this block only after the confirmation above. It is POSIX shell on purpose (the Bash tool runs zsh on macOS, and a bash-only builtin fails there). `find` deletes nested entries without any glob setting; `-type d` under `cv/` keeps `cv/main_example.tex` while removing every company folder. If `cv/` or `cover_letters/` is a symbolic link, stop before deleting anything.

```bash
(
  set -e
  for root in cv cover_letters; do
    if [ -L "$root" ]; then
      printf 'Reset stopped: %s is a symbolic link.\n' "$root" >&2
      exit 1
    fi
  done
  find cv -mindepth 1 -maxdepth 1 -type d -exec rm -rf -- {} +
  rm -f cv/main_example.pdf cv/main_example.aux cv/main_example.log cv/main_example.out
  if [ -d cover_letters ]; then
    find cover_letters -mindepth 1 -maxdepth 1 ! -name .gitkeep -exec rm -rf -- {} +
  fi
)
```

Finally restore any personal data embedded in registered templates to placeholders. Registered templates are supposed to be profile-agnostic (`templates/README.md`), so this closes a leak rather than rewriting the template. Apply these replacements to `templates/cv/*/template.tex` and `templates/cover_letters/*/template.txt`:

| Replace | With |
|---|---|
| the candidate's full name | `[FIRST_NAME] [LAST_NAME]` |
| the candidate's city/country | `[CITY, COUNTRY]` |
| the candidate's phone | `[+XX XXXXXXXXXX]` |
| the candidate's email (both `mailto:` and displayed text) | `[your.email@example.com]` |
| the candidate's GitHub URL | `[https://github.com/your-username]` |
| the candidate's LinkedIn URL | `[https://linkedin.com/in/your-profile]` |

Preserve `templates/*/TEMPLATE.md` and `templates/README.md` — they are framework manifests, not candidate data.

### Memory reset

**For `CLAUDE.md`**, replace the whole `## Candidate Profile` section (from that heading up to, but not including, `## Repo Structure`) with the following skeleton, keeping every heading, comment, and the `## Repo Structure` block below it:

```markdown
## Candidate Profile

<!-- This section is auto-populated by /setup. You can also fill it in manually. -->

### Identity
- **Name:** [YOUR_NAME]
- **Location:** [YOUR_LOCATION]
- **Languages:**
  | Language | Level |
  |----------|-------|
  | [LANGUAGE] | [LEVEL] |

- **CV language:** [YOUR_CV_LANGUAGE]
- **hh.ru auto-submit:** [ENABLED_OR_DISABLED]
- **Status:** [YOUR_STATUS]
- **LinkedIn headline:** [YOUR_LINKEDIN_HEADLINE]

### Education
<!-- List your degrees, most recent first -->

### Professional Experience
<!-- List your roles, most recent first -->

### Technical Skills

### Certifications
<!-- List relevant certifications with dates -->

### Publications
<!-- List peer-reviewed publications, if any -->

### Awards
<!-- List relevant awards, hackathons, competitions -->

### Behavioral Profile
<!-- Your behavioral assessment results (PI, DISC, Myers-Briggs, or self-assessment) -->

### What Excites You
<!-- What motivates you professionally -->

### Target Sectors
<!-- Industries and companies you're targeting -->

### Deal-breakers
<!-- Hard constraints on job search. Language requirements are handled separately. -->
```

Also replace the `# Job Application Assistant for <name>` title line with `# Job Application Assistant`.

**For `.claude/skills/job-application-assistant/03-writing-style.md`**, read the candidate's real name with `tests/_candidate.py` (`read_profile_name()` / `candidate_name()`) and replace every occurrence of it in the file with `[YOUR_NAME]`. If the profile already returns a placeholder, leave the file unchanged. Do not touch the writing rules themselves.

**For `AGENTS.md`**, verify it contains no personal data (it is a thin pointer). Leave it unchanged.

### Documents reset

For each non-empty document subfolder, delete all user entries, including nested folders and hidden files. Preserve the seven top-level subfolders, their `.gitkeep` placeholders, and `documents/README.md`. Run the following block only after the confirmation above. It is POSIX shell on purpose: the Bash tool runs whatever shell the user has, which is zsh on macOS, and a bash-only builtin such as `shopt` fails there with `command not found` before anything is deleted. `find` lists hidden entries and nested folders without any glob setting. If `documents/` or any of its seven roots is a symbolic link, stop before deleting anything and ask the user to replace that linked root with a local document folder.

```bash
(
  set -e
  for directory in documents documents/cv documents/linkedin documents/diplomas documents/references documents/projects documents/postings documents/applications; do
    if [ -L "$directory" ]; then
      printf 'Reset stopped: %s is a symbolic link.\n' "$directory" >&2
      exit 1
    fi
  done
  for directory in documents/cv documents/linkedin documents/diplomas documents/references documents/projects documents/postings documents/applications; do
    [ -d "$directory" ] || continue
    find "$directory" -mindepth 1 -maxdepth 1 ! -name .gitkeep -exec rm -rf -- {} +
  done
)
```

### State reset

Delete the operational state and derived reports. Preserve `state/migrations/` (the schema used to recreate the tracker on next use). Run this block only after the confirmation above.

```bash
(
  set -e
  rm -f state/job_search.sqlite state/job_search.sqlite-* \
        state/job_search.sqlite-wal state/job_search.sqlite-shm \
        state/hh_storage_state.json state/import-report.json
  rm -rf state/hh_debug
  if [ -d reports ]; then
    find reports -mindepth 1 -maxdepth 1 ! -name .gitkeep -exec rm -rf -- {} +
  fi
  rm -f funnel-*.md
)
```

### Backups reset

Delete everything under `backups/` and recreate its `.gitkeep` placeholder. Run this block only after the confirmation above.

```bash
(
  set -e
  if [ -L backups ]; then
    printf 'Reset stopped: backups is a symbolic link.\n' >&2
    exit 1
  fi
  find backups -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +
  touch backups/.gitkeep
)
```

---

## Step 4: Confirm What Was Done and Next Steps

After the reset is complete, report:

```
## Reset complete

### Cleared
[List each file/folder that was actually modified or cleared]

### Unchanged
[List anything that was already empty or was intentionally preserved]
```

Then tell the user what to do next based on what was reset:

**If profile was reset:**
> The skill files are now blank. Run `/setup` to repopulate them. The command auto-detects any files in your `documents/` folder and offers to read from there; otherwise it walks you through a CV import or interactive interview.

**If templates were reset:**
> Per-company CVs and cover letters are gone; `cv/main_example.tex` is restored to the pristine stock template (or replaced with the bundled stock template when `upstream/master` was unavailable), and registered templates are placeholder-only again. Add per-company files as you apply, or run `/add-template-cv` / `/add-template-cover-letter` to register a custom template.

**If memory was reset:**
> `CLAUDE.md` now holds the blank profile skeleton and the candidate name is gone from agent markdown files. Run `/setup` to repopulate the profile.

**If documents were reset:**
> Your user documents are now cleared. The folder structure, `.gitkeep` placeholders, and `documents/README.md` are preserved. Add your career documents and run `/setup` to populate your profile.

**If state was reset:**
> The SQLite tracker, the hh.ru browser session, debug captures, and derived reports are gone; `state/migrations/` is preserved. The tracker is recreated empty on the next `/db`, `/scrape`, `/apply`, or `/outcome`. Log in again with `/submit-login` before the next auto-submit.

**If backups was reset:**
> The `backups/` folder is empty (only `.gitkeep` remains). One-time legacy backups are gone; the current SQLite tracker and report outputs are not affected by this branch.

**After a full wipe (`all` / bare `/reset`):**
> Everything above is cleared. Add documents to `documents/` (or skip and use the CV import / interview path), then run `/setup`, then `/submit-login` when you are ready to apply on hh.ru.
