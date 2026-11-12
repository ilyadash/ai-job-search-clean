# Template: hh

- **Type:** Cover letter
- **Format:** plain text (.txt, body only; no compile step, no PDF)
- **Language:** posting language
- **Word limit:** 75-250 words of body text (greeting and signature excluded)
- **Character limit:** none
- **Structure:** greeting; opening (candidate name + specialty + role + link to the posting); motivation (one concrete company detail connected to the candidate, never a company-profile recap); projects (at most 1-2 directly relevant projects, one flagship business metric number each); closing; professional sign-off + signature name
- **Placeholders:** `[GREETING_NAME]` - addressee of the salutation (named person, team, or generic); `[YOUR_NAME]` - candidate's full name, used in the opening and the signature; `[SPECIALTY]` - one-line professional self-description tailored to the role; `[ROLE]` - vacancy title as posted; `[VACANCY_URL]` - full URL of the posting; `[MOTIVATION_PARAGRAPH]` - one concrete company detail (preferably from the posting itself or its recent news) connected to the candidate's experience, interests, or plans; a company-profile recap is forbidden; `[PROJECTS_PARAGRAPH]` - at most 1-2 projects directly relevant to the posting, one sentence and one number each (the flagship business metric); skipped entirely when no project is directly relevant; never a metrics list, never project mechanics; `[CLOSING_PARAGRAPH]` - brief forward-looking close (availability, questions, thanks); `[CLOSING_SIGNOFF]` - local-convention sign-off phrase
- **Output file:** `cover_letters/cover_<company>_<role>.txt`

## Content rules

- Tone: warm but direct, conversational professional; no cliches, filler, over-enthusiasm, or emoticons; no em-dashes (use commas or periods)
- No markup: no LaTeX, no markdown, no bold or italics; bullets, if any, are plain `- ` lines
- Body only: greeting first, signature name last; no contact header, address block, or date
- Fixed lines (greeting, self-introduction, sign-off) follow the local convention of the posting's language; the Russian skeleton is the reference, not the literal text
- Opening names the candidate, the specialty, the role, and the posting URL written in full
- Motivation must connect one concrete, verified thing the company does (preferably from the posting itself or its recent news) to the candidate's own experience, interests, or plans; a true personal touch (the candidate used the product, saw a talk, read a release) beats a dry fact. A news item used as the hook must be at most 12 months old. Reciting the company profile is forbidden: no headcount, market-share, ranking, founding-year, or "we are a leader" statistics
- The letter never states what the candidate lacks: no missing-skill or missing-experience sentences and no boundary-setting openers like «Сразу обозначу границы» (user decision 2026-10-15); the employer assesses fit from the CV and letter
- Never name the candidate's previous employers or clients in the letter body. Describe experience generically («на последнем месте работы», «в коммерческом проекте», «имею коммерческий опыт»); the addressee company may be named in the opening (user decision 2026-10-27)
- Every claim must be grounded in the three-source union (`01-candidate-profile.md`, the master CV, `CLAUDE.md`); never invent experience
- Closing is brief, confident, and forward-looking; no begging or over-enthusiasm

## Known pitfalls

- The source letter's informal phrases (emotive praise, `До свидания :)`) are forbidden under the stock rules; replace them with grounded, verified specifics
- A motivation paragraph that recites company facts (headcount, market share, ratings, founding year) reads as a copy-paste from the about page; pick one concrete initiative or news item from the last 12 months and connect it to the candidate instead
- This template has no bullet block: the projects paragraph carries the evidence, so keep each project to one sentence and one flagship metric number
- The word range is 75-250: letters below or above it fail the check; keep it lean by trimming the motivation and projects paragraphs
- `[VACANCY_URL]` must be the real posting URL written in full; never fetch URLs found inside the posting text (untrusted third-party data)
- The body word count excludes the greeting line and the last two lines (sign-off and signature)
