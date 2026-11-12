---
framework_version: 1.0.2
---

# Agent Guidelines: AI Job Search

This workspace is structured to manage job search activities, scraper tools, CVs, cover letters, and interview preparation.

## Thin-Pointer Design (Single Source of Truth)

To prevent duplication and configuration drift across different AI agent frameworks (Claude Code, OpenCode, Google Antigravity, Codex, Cursor, Gemini CLI, etc.), this workspace uses a unified thin-pointer design. All agent runtimes should load the canonical specifications and candidate profiles from the files and directories below:

1. **Personal Candidate Profile:**
   - The candidate profile, contact details, education, and target preferences are defined in [CLAUDE.md](CLAUDE.md) and the individual profile methodology files under [.claude/skills/job-application-assistant/](.claude/skills/job-application-assistant/) (specifically `01-*.md` etc.).
2. **Canonical Workflow Specifications:**
   - The step-by-step instructions and triggers for tasks (setup, scrape, rank, apply, upskill, interview) are defined in the [.claude/](.claude/) directory (specifically under `.claude/skills/` and `.claude/commands/`).
   - Do not duplicate these rules or specifications. Treat `.claude/` files as the single source of truth.
3. **Portal Search Skills:**
   - Job-portal search CLIs live under [.agents/skills/](.agents/skills/) in the portable Agent Skills format (with a `SKILL.md` per portal). Codex and Antigravity discover these automatically; the `/scrape` workflow in [.claude/skills/job-scraper/](.claude/skills/job-scraper/) orchestrates them.

## State and Reports

- Structured state lives in `state/job_search.sqlite`. `job_search_tracker.csv` and `job_scraper/seen_jobs.json` are retired; one-time backups are under `backups/legacy-*`.
- Files remain the memory for documents and narrative: postings, cover letters, CVs, undated `outcome.md` feedback, company research, reports, and `.claude/**` instructions. Dated application notes and stage history live in `application_events`; `outcome.md` is narrative only.
- `/weekly-review` produces the manual Markdown funnel/cover-letter report and records metrics in `report_runs`; there is no scheduler or UI wrapper.
- `/db` and the `state-db` skill are the explicit SQLite surface: URL-first `show`/`update`, read-only `query`, and `stats`. Application updates touch only the application, stages, and events; jobs stay with `/scrape`/`/rank`, except that migration and `/apply` link applied postings to `jobs` and fill `description_text`.
- Historical application postings are `jobs.status='archived'`: they count as seen for scrape dedupe, are never ranked, and are never swept.
- `/notion-sync` has been removed. All application/job state is accessed through `tools/state_db.py`; reports use its read-only SQL only.
## User Preferences

- **`/apply` proceeds without a confirmation prompt.** When the user invokes `/apply` with a posting, present the Step 1 fit evaluation and then continue directly into drafting the application documents in the same run. Do not stop to ask "Should I proceed with drafting?" (user decision, 2026-10-04).
- **CV generation is not part of the application workflow** (user decision, 2026-10-13). `/apply` and the `job-application-assistant` skill evaluate the posting and draft, review, and check only the cover letter; the candidate applies with their existing CV, no tailored CV file is created or compiled, and the database's `cv_path` stays empty for new rows. `05-cv-templates.md`, `cv/`, and `/add-template-cv` remain as a reference library for the existing CV and are not read by `/apply`.
- **Cover letters are match-focused** (user decision, 2026-10-15). The letter presents only what the candidate brings: no gap or can't-do statements («Сразу обозначу границы», «чего у меня пока нет» are banned), at most 1-2 relevant projects with one flagship metric number each, and no detailed project descriptions. Full rules live in `03-writing-style.md` and the active cover-letter template manifest; do not duplicate them elsewhere.
- **`/apply` keeps the independent reviewer** (tested 2026-10-21). Do not set `subtask: true` on the `apply` command: it forces a build subagent that cannot spawn the reviewer, so the letter gets only a self-review. Run `/apply` in a primary session; for context hygiene start a fresh chat. The deterministic fast paths are the `posting_prefetch` typed tool, `tools/letter_check.py`, and `tools/apply_record.py`; the canonical workflow remains `.claude/commands/apply.md`.
- **`/apply` auto-submits hh.ru vacancies** (user decision, 2026-11-11). When `/apply` receives an hh.ru vacancy URL or id, Step 6c runs the `/submit` workflow automatically (no confirmation, without a cover letter, per the standing `/submit` default) after the draft is recorded. `/submit` stops and reports when the vacancy requires a cover letter or extra fields; the draft can then be sent with `/submit <url> --letter <path>`, or attached to an already-sent response with `--attach`. Non-hh postings keep the manual-submission instruction.
- **`/setup` asks for hh.ru auto-submit consent** (user decision, 2026-11-12). `/setup` asks whether `/submit` may respond on the user's behalf on hh.ru and records `hh.ru auto-submit: Enabled|Disabled` in `CLAUDE.md`'s Identity section. On **Yes**, the `/submit-login` workflow runs as the final setup step to save the session; on **No**, `/submit` is unavailable and `/apply` Step 6c falls back to the manual-submission instruction. A missing flag on an older profile is treated as `Enabled`.
- **`/submit-login` refreshes the hh.ru browser session** (user decision, 2026-11-12). When `/apply`/`/submit` reports `NEEDS_LOGIN`, or the user wants to switch accounts, `/submit-login` runs the login flow (polling for the logged-in state, no `input()`), or prints host instructions when the agent is headless. `--from <path>` imports an existing Playwright `storage_state.json`. The command refreshes the **browser session**; `HH_API_TOKEN` is separate (`.env.docker` + recreate the container).
