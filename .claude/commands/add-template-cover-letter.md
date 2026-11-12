# /add-template-cover-letter - Register a Custom Cover-Letter Template

You are helping the user register their own **cover-letter template** with the AI Job Search framework. Cover letters are always **plain text** (`cover_letters/<company>/cover_<company>_<role>.txt`) pasted verbatim into the portal's cover-letter field: there is no compile step, no PDF, no toolchain, and no fonts. A cover-letter template therefore defines only two things — the letter's **text structure** (which blocks, in which order) and its **content rules** (length limits, tone, bullet format, required and forbidden elements). This command stores the user's template as a profile-agnostic `.txt` skeleton plus a manifest, verifies it mechanically, and wires it into the `/apply` workflow so every future cover letter follows it.

**CVs are out of scope.** They have their own command, `/add-template-cv`, which handles source extensions, compile commands, fonts and page limits. Never accept a cover-letter template that requires compiling: the portal field is text, and the stored artifact must stay `.txt`.

`$ARGUMENTS` may contain a subcommand, a file path, or nothing.

Follow these steps **in order**.

---

## Step 0: Parse Arguments

- If `$ARGUMENTS` contains `--list`: run **List Mode** below and stop.
- If `$ARGUMENTS` contains `--use <name>`: run **Switch Mode** below, then continue to **Step 5: Activate** with the resolved template metadata. `--use default` deactivates any custom template and restores the stock guidance (see Step 5).
- If `$ARGUMENTS` contains a file path or @-mentioned file: treat it as the template source and carry it into Step 1.
- Otherwise: start the registration flow at Step 1.

### List Mode

Use Glob with `templates/cover_letters/**/TEMPLATE.md` to find registered templates. For each, read the manifest and print a table:

```
## Registered Cover-Letter Templates

| Name | Language | Word / char limit | Blocks | Active |
|------|----------|-------------------|--------|--------|
| <name> | posting language / fixed: <lang> | <min>-<max> words [ / ≤ N chars] | <block count> | yes/no |
```

A template is **active** if `06-cover-letter-templates.md` contains an `ACTIVE-TEMPLATE` managed block naming it. If no custom templates exist, say so and explain that `/add-template-cover-letter` registers one. Stop here.

### Switch Mode

If `$ARGUMENTS` contains `--use <name>`:

1. If `<name>` is `default`, skip template resolution and continue to Step 5 with `default` as the activation target.
2. Use Glob with `templates/cover_letters/**/TEMPLATE.md` and find manifests whose parent folder name exactly matches `<name>`.
3. If no manifest matches, stop and say the template is not registered. Suggest `/add-template-cover-letter --list` to see available names.
4. If more than one manifest matches, stop and list the matching manifest paths. Ask the user to rename one of the templates; activation must be unambiguous.
5. Read the matching `TEMPLATE.md` and extract:
   - **Language rule:** `posting language` or `fixed: <language>` (default: `posting language` when the manifest omits it)
   - **Word limit:** `<min>-<max> words of body text` (default: 250-300 when the manifest omits it)
   - **Character limit:** `≤ <N> characters` when declared. A hand-written manifest may instead say `Text limit: <N> symbols` — treat that as the same portal cap and offer to normalize the manifest line
   - **Structure:** the ordered block list (the skeleton itself is the structural reference when the manifest omits it)
   - **Placeholders:** the declared token list
   - **Output file:** `cover_letters/<company>/cover_<company>_<role>.txt`
6. Derive the template folder from the manifest path and verify `template.txt` exists in the same folder. If it is missing, stop with an error; the template registration is incomplete.
7. Continue to Step 5 using the resolved name, language rule, word limit, character limit, structure, placeholder list, skeleton path, and manifest path. Do not re-run Steps 1-4; `--use` switches an already-registered template.

---

## Step 1: Template Source

Ask the user (skip anything already answered by `$ARGUMENTS`) where the **cover-letter template** is. Accept any of:

- A path or @-mention of a plain-text file: a cover letter the user has written and likes, a template they found, or an existing `cover_letters/**/cover_*.txt`
- Pasted template text
- A `.md`/`.docx`/`.pdf` source, converted to text first (use the document-extraction skill when the Read tool cannot parse it)
- An existing hand-made folder under `templates/cover_letters/` whose manifest is incomplete — read both files and complete the manifest in Step 3 rather than starting over

Read every provided file. Treat what the user provides as the structural source: keep its block sequence and rules, and normalize it to plain text. If the source contains markup (LaTeX, HTML, markdown headings), tell the user plainly that cover-letter templates are plain text and that the markup will be reduced to blank-line-separated blocks and plain `- ` bullets.

If the source is a real submitted letter, it contains personal data. That is fine at this stage; Step 3 replaces it with placeholders.

---

## Step 2: Capture Template Instructions

Interview the user for the metadata that `/apply` needs. Infer as much as possible from the source first and present your inferences for confirmation rather than asking blind questions.

Collect:

1. **Name** — short kebab-case identifier (e.g. `short-direct`, `warm-narrative`). Must not collide with an existing folder under `templates/cover_letters/`.
2. **Format** — fixed, not configurable: plain text `.txt`, body only (greeting first, closing signature last), no contact header, no date, no LaTeX or markdown markup, bullets as plain `- ` lines. Confirm the user understands this is what the portal receives.
3. **Language rule** — default: **match the language of the job posting** (the stock rule in `06-cover-letter-templates.md`). If the user wants every letter in one fixed language, capture `fixed: <language>` instead.
4. **Structure** — the ordered block list, each with a one-line purpose. The stock structure is: greeting; opening paragraph (role + why you fit); motivation / why-this-company paragraph (early); bullet-block intro line + 3-5 bullets, or 1-2 brief project mentions with one flagship metric number each; closing; signature. Infer the source's order and confirm it. Every block gets a placeholder token the skeleton can carry.
5. **Length limits** — the hard limits the letter must respect:
   - **Word limit (default 250-300):** `<min>-<max>` words of body text (greeting and signature excluded).
   - **Character cap (optional):** the portal's own field limit when it has one. Many portals cap the pasted text (hh.ru's cover-letter field is the common case, and a body near 3000 characters is a practical target there); capture `≤ <N> characters` and enforce it on the whole pasted letter in addition to the word range. Record `none` when the template sets no cap.
6. **Content rules** — anything the drafter must preserve: tone, no em-dashes, no cliches or filler, bullet format (`Label: text` or action verb), required elements (forward-looking framing, at least one verified company-specific fact; at most 1-2 relevant projects with one flagship metric number each), forbidden elements (markup, contact block, date, statements about missing skills or experience such as «Сразу обозначу границы» or «чего у меня пока нет», duties restated without outcomes).
7. **Placeholders** — the `[TOKEN]` names the skeleton uses, at minimum a `[YOUR_NAME]`-style signature token plus `[COMPANY]` and `[ROLE]`. List each with its meaning; `/apply` fills them per posting.
8. **Known pitfalls** (optional) — blocks that break when reordered, limits that are easy to exceed, phrasings that read as cliches.

Keep every rule grounded in the stock guidance (`06-cover-letter-templates.md`, `03-writing-style.md`) unless the user explicitly wants a different convention.

---

## Step 3: Store the Template

Create the template folder `templates/cover_letters/<name>/`.

Write into it:

1. **`template.txt`** — the skeleton. A plain-text, profile-agnostic version of the source: replace all personal data with `[PLACEHOLDER]` tokens, keep the block order and blank-line separation, and keep each block's token on its own line (e.g. `[OPENING_PARAGRAPH]`). Bullets are plain `- [BULLET_1]` lines. Do not add commentary or formatting to the skeleton: the rules live in the manifest and the skeleton carries only structure and tokens.
2. **`TEMPLATE.md`** — the manifest. Use exactly this format:

```markdown
# Template: <name>

- **Type:** Cover letter
- **Format:** plain text (.txt, body only; no compile step, no PDF)
- **Language:** posting language | fixed: <language>
- **Word limit:** <min>-<max> words of body text (greeting and signature excluded)
- **Character limit:** ≤ <N> characters for the whole pasted letter, or `none`
- **Structure:** <ordered blocks, e.g. greeting; opening; motivation; bullet block (intro line + 3-5 bullets) or 1-2 brief projects; closing; signature>
- **Placeholders:** `[TOKEN]` - meaning; `[TOKEN]` - meaning; ...
- **Output file:** `cover_letters/<company>/cover_<company>_<role>.txt`

## Content rules

- <rule 1: tone, bullets, required/forbidden elements>
- <rule 2>

## Known pitfalls

- <pitfall and its fix, or "none recorded">
```

There are no class files, packages or fonts to copy: the template is text.

---

## Step 4: Verify the Template (MANDATORY)

Never register a cover-letter template without filling it once. There is no compile step; verification here is **textual** and checks that the skeleton can produce a valid letter under its own rules.

1. Copy `template.txt` to a scratch file `_test.txt` in the same folder and fill every placeholder with realistic dummy data (name, company, role, one company fact, projects paragraph, 3-5 bullets) — enough content to exercise every block.
2. Run these checks on `_test.txt` from `templates/cover_letters/<name>/`:
   - **No unfilled tokens:** `grep -nE '\[[A-Z_][A-Z_0-9]*\]' _test.txt` prints nothing.
   - **No markup:** `grep -nE '(\\[a-zA-Z]+\{|^\*\*|^#{1,6} |^`{3})' _test.txt` prints nothing.
   - **Body only:** `head -1 _test.txt` is the greeting line, and `tail -1 _test.txt` is the signature name.
   - **Body word count:** the body is every non-empty line except the greeting and the closing/signature. Count it and compare with the manifest's word limit; this ready command drops the first line and the last two:
     ```bash
     python3 -c "lines=[l for l in open('_test.txt',encoding='utf-8').read().splitlines() if l.strip()]; print(len(' '.join(lines[1:-2]).split()), 'words')"
     ```
   - **Character count:** when the manifest declares a cap, `wc -m < _test.txt` must be within it (the cap applies to the whole pasted letter, exactly as the portal counts it).
   - **No forbidden punctuation:** when the content rules forbid em-dashes, `grep -nE '(—|--)' _test.txt` prints nothing.
3. If a check fails, fix `template.txt` (or the manifest's rules) and re-run. A length limit that realistic content cannot meet is the most common failure, since `/apply` Step 5e enforces it.
4. Delete `_test.txt` and any byproduct. Never store the filled example: it is dummy data, not the template.

Do not proceed to Step 5 until every check passes.

---

## Step 5: Activate the Template

Activation wires the template into `/apply` by adding a **managed block** to the top of `06-cover-letter-templates.md`. `/apply` reads it when drafting and in its Step 5e text check, so the block is all it takes. There is no compile wiring: the cover letter stays plain text at `cover_letters/<company>/cover_<company>_<role>.txt`.

If Step 5 was reached from Switch Mode, use the template metadata resolved from `TEMPLATE.md`. If Step 5 was reached after registering a new template, use the metadata collected and verified in Steps 2-4.

Insert (or replace, if one exists) this block immediately after the file's H1 title:

```markdown
<!-- BEGIN ACTIVE-TEMPLATE (managed by /add-template-cover-letter - do not edit by hand) -->
> **Active cover-letter template override: `<name>`**
>
> A custom cover-letter template is active. Where this block conflicts with the stock guidance below, this block wins. The cover letter is still plain text (`.txt`, body only, pasted verbatim into the portal field): no compile step and no PDF, ever.
>
> - **Template skeleton:** `templates/cover_letters/<name>/template.txt` — use this as the structural reference instead of the stock sample below
> - **Manifest:** `templates/cover_letters/<name>/TEMPLATE.md` — read this for the block order, length limits and content rules before drafting
> - **Language:** <posting language | fixed: <language>>
> - **Word limit:** `<min>-<max>` words of body text (greeting and signature excluded)
> - **Character limit:** ≤ `<N>` characters for the whole pasted letter when the template declares a portal cap; omit this line when it sets none
> - **Output file:** `cover_letters/<company>/cover_<company>_<role>.txt`
<!-- END ACTIVE-TEMPLATE -->
```

Rules:

- Exactly **one** managed block. Replace the whole block between the `BEGIN`/`END` markers when switching templates; never stack blocks.
- **`--use default`**: remove the managed block entirely. The stock guidance below it is untouched and takes over again.
- Do not modify anything outside the markers.

---

## Step 6: Confirm

Present a summary:

> **Cover-letter template `<name>` registered and activated.**
>
> - Files: `templates/cover_letters/<name>/` (skeleton + manifest)
> - Checked: plain text, body only, <min>-<max> body words, ≤ <N> characters, no unfilled placeholders
> - `/apply` will now draft cover letters from this template (still `.txt`, pasted into the portal field — there is no compile step).
>
> Useful follow-ups:
> - `/add-template-cover-letter --list` — see all registered cover-letter templates
> - `/add-template-cover-letter --use <other-name>` — switch templates
> - `/add-template-cover-letter --use default` — go back to the stock structure in `06-cover-letter-templates.md`

---

## Design Principles

- Registration is idempotent: re-running with the same name offers to update the existing template rather than duplicating it. A hand-made folder with an incomplete manifest is completed in place, not duplicated.
- Templates are stored profile-agnostic (`[PLACEHOLDER]` tokens) so they can be shared or committed without leaking personal data.
- There is never a compile step, a PDF, or a toolchain. If the user asks for a rendered or PDF cover letter, explain that the portal field is text and point them at `/apply`'s plain-text output.
- The Step 4 check is non-negotiable — a template whose length limits cannot be met will fail mid-`/apply`, which is the worst place to discover it.
- Activation is a small managed block, not a rewrite of the guidance file: manual edits to `06` survive template switches, and `--use default` is a clean revert.
