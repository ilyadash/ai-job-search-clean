---
framework_version: 1.1.2
---

# Cover Letter Guide (Plain Text)

<!-- BEGIN ACTIVE-TEMPLATE (managed by /add-template-cover-letter - do not edit by hand) -->
> **Active cover-letter template override: `hh`**
>
> A custom cover-letter template is active. Where this block conflicts with the stock guidance below, this block wins. The cover letter is still plain text (`.txt`, body only, pasted verbatim into the portal field): no compile step and no PDF, ever.
>
> - **Template skeleton:** `templates/cover_letters/hh/template.txt` — use this as the structural reference instead of the stock sample below
> - **Manifest:** `templates/cover_letters/hh/TEMPLATE.md` — read this for the block order, length limits and content rules before drafting
> - **Language:** posting language
> - **Word limit:** `75-250` words of body text (greeting and signature excluded)
> - **Output file:** `cover_letters/<company>/cover_<company>_<role>.txt`
<!-- END ACTIVE-TEMPLATE -->

The cover letter is a **plain-text file** — `cover_letters/<company>/cover_<company>_<role>.txt`, grouped in the company's subfolder. It is pasted verbatim into the portal's cover-letter field (the "Сопроводительное письмо" box on hh.ru, the response form on Habr Career, and equivalents elsewhere), so the file contains **no LaTeX, no markdown, and no layout markup** — only the text the employer will read.

**Body only.** Start with the greeting and end with the signature. No contact header, no address block, no date: the portal already knows who you are, and those lines waste the first screen of the field.

**Custom templates.** The structure below is the default. `/add-template-cover-letter` registers your own plain-text template — a `[PLACEHOLDER]` skeleton plus the structure, content rules and body word limit to enforce — and its `ACTIVE-TEMPLATE` managed block at the top of this file overrides the structure and limits below whenever it is present. Registration and use stay text-only, like the letter itself: no compile step and no PDF, ever.

## Structure

The letter is written in **the language of the job posting** — the sample below is Russian:

```text
Здравствуйте, [Имя]!

[Открывающий абзац: роль и главная причина, почему вы подходите. 2-3 предложения.]

[Абзац-подводка к списку: что вы можете принести в команду.]

- [Конкретный результат или навык 1, отвечающий требованию вакансии]
- [Конкретный результат или навык 2]
- [Конкретный результат или навык 3]

[Почему именно эта компания и продукт — со ссылкой на проверенный конкретный факт.]

[1-2 релевантных проекта, кратко: по одному числу на каждый - ключевая бизнес-метрика результата. 1-2 предложения.]

Буду рад обсудить, как мой опыт может помочь вашей команде. Спасибо за внимание к резюме!

С уважением,
[YOUR_NAME]
```

English equivalents for the greeting and closing: `Dear [Name],` ... `I look forward to hearing from you.` / `Kind regards,`.

## Rules

### Formatting — none
- No `**bold**`, `_italics_`, backticks, or link syntax; bullets are plain `- ` lines and nothing else
- No LaTeX commands (`\textbf{}`, `\item`, ...) — the field renders them literally
- No em-dashes; use commas or periods instead
- One blank line between paragraphs; write emails and URLs out in full if they must appear

### Salutation
- Named person if the posting names one: "Здравствуйте, Иван Иванович!" / "Dear [First Last],"
- Known team: "Здравствуйте, команда «[Компания]»!" / "Dear [Company] hiring team,"
- Generic: "Здравствуйте!" / "Dear Hiring Manager," — never "To whom it may concern"

### Length — honour the active template override
- When a custom template's `ACTIVE-TEMPLATE` block is present, its word limit wins (hh: 75-250 body words). Without an override, 250-300 words of body text.
- Opening paragraph + bullet block + closing paragraph = 3 blocks; add a 4th only when the others are short
- When adding company-specific content, trim other content to compensate rather than growing the letter
- The portal field shows roughly a screenful at a time; a wall of text loses the reader

### Bullet lists
- Introduce the list with one short line naming the offer ("Что я могу принести в вашу команду:")
- 3-5 bullets; each starts with a plain label (`Label: text`) or an action verb
- Every bullet answers a posting requirement or names a concrete result — never a duty restated as an achievement

### Honesty and grounding
- Every claim must be grounded in the three-source union (`01-candidate-profile.md`, the master CV `cv/main_example.tex`, `CLAUDE.md`); never invent experience. The letter presents only what the candidate brings: missing skills, tools or experience are not mentioned, and boundary-setting openers like «Сразу обозначу границы» are banned (user decision 2026-10-15)
- Every company-specific statement must be independently verified before inclusion (see `03-writing-style.md` and `09-web-research.md`)

### Non-English letters
- Write naturally in the posting's language, not translated word-for-word
- Adjust the closing to local convention ("С уважением,", "Kind regards,", "Med venlig hilsen,")

## Checklist Before Finalizing
- [ ] Body only: greeting first line, signature last line, no header/date/contacts
- [ ] No markup: no LaTeX, no markdown; bullets are plain `- ` lines
- [ ] Body length within the active template's limit (hh override: 75-250 words; no override: 250-300)
- [ ] Language matches the job posting
- [ ] No em-dashes, no cliches, no empty filler
- [ ] No gap or can't-do statements («Сразу обозначу границы», «чего у меня пока нет»): the letter presents only strengths
- [ ] At most 1-2 projects, each with one flagship metric number; no detailed project descriptions
- [ ] Every claim backed by the profile sources; every company claim independently verified
- [ ] Forward-looking framing: what you will solve, not just past duties
- [ ] Motivation connects one concrete company detail (preferably from the posting or its recent news) to your own experience or interests; no company-profile recap (headcount, market share, rankings, founding year)
- [ ] Company name and role correct throughout; salutation appropriate
- [ ] No placeholder text left (`[Имя]`, `[Company]`, `[Должность]`, ...)

## Patterns Observed in Past Applications

(Source: archived cover letters in `documents/applications/` — ГКУ «Инфогород» [AI Developer] and АО «Оператор информационной системы» [ML-Engineer], October 2026. Tone-level findings live in `03-writing-style.md`; this section records structure only.)

- **Bullet block intro:** the list is introduced by a line naming the offer, "Что я могу принести в вашу команду:" / "Что я могу принести в ваши задачи:", followed by 3-5 bullets with plain category labels.
- **Motivation paragraph placed early**, naming the employer's concrete product or scale (e.g. ГИС ЖКХ modernization, the Digital Twin of Moscow) instead of generic praise.
- **No gap paragraphs (user decision 2026-10-15):** letters present only what the candidate brings; missing skills, tools or experience are never stated («Сразу обозначу границы», «Чего у меня пока нет» and similar are banned). Relevant projects stay brief: at most 1-2, one flagship metric number each.
- **Closing:** "Буду рад обсудить, как мой опыт … Спасибо за внимание к резюме!"; an English-proficiency sentence ("Английский C1: свободно читаю техническую документацию.") is included when the posting touches language.
- **Compact no-bullet form (observed late October 2026):** 37 of 40 archived `.txt` letters use no bullet block; 36 open with a name-first self-intro, 35 include the vacancy link, and the median body is about 158 words. The «Что я могу принести» bullet block survives in only 3 letters. This matches the active hh template's 75-250 word limit: 2-3 short paragraphs and 1-2 flagship metrics instead of a bullet list.
- **Locality sentence (November 2026):** a single sentence on geography and working format sits just before the closing line, in 18 of 40 letters — «Живу в Москве, готов работать удалённо или обсудить переезд», «Переезд в Санкт-Петербург и работу в офисе рассматриваю». It is one sentence, never a logistics paragraph, and appears only when the posting names a city, a format or relocation.

## Submission Notes
- The `.txt` file is the deliverable — copy its contents into the portal field as-is
- Submit only the documents the employer asks for
- Where a portal accepts a file attachment for the letter, the same `.txt` can be attached; the text field remains the primary path
