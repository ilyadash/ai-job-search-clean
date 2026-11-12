# Template: mlmentor-resume

- **Type:** CV
- **Source extension:** .tex
- **Engine/toolchain:** pdflatex for Latin CVs; lualatex for Russian CVs (display label only)
- **Page limit:** 1 page(s)
- **Fonts:** Latin CVs: Lato, via the TeX Live `lato` package (Type1 under pdflatex - must be installed with the TeX distribution). Russian CVs: DejaVu Sans via fontspec under lualatex (installed system font). FontAwesome5 (TeX Live) for the contact icons. No bundled font files.
- **Class/packages:** `article` class; geometry, inputenc, mdwlist, lato, fontenc, textcomp, fontawesome5, enumitem, hyperref for Latin CVs (all from TeX Live); Russian CVs replace inputenc/lato/fontenc with fontspec (see Russian CV variant below). `mdwlist` provides the `itemize*` tight-list environment used for experience bullets.

## Compile command

    cd cv && rm -f <file>.pdf && mkdir -p build && pdflatex -interaction=nonstopmode -output-directory=build <file>.tex && mv build/<file>.pdf ./

## Russian CV variant (the profile's CV language is Russian)

Lato's T1 Type1 fonts have no Cyrillic glyphs, and this TeX installation has no T2A encoding or Russian hyphenation patterns: a Russian CV compiled with the default preamble exits 0, reports the right page count, and silently drops every Cyrillic character. For Russian CVs, swap only the font block and keep the rest of the preamble and document identical:

- Remove `\usepackage[utf8]{inputenc}`, `\usepackage[default]{lato}` and `\usepackage[T1]{fontenc}`; add:
  `\usepackage{fontspec}`, `\setsansfont{DejaVu Sans}`, `\setmainfont{DejaVu Sans}`, `\emergencystretch=3em`
  (`\emergencystretch` absorbs long Russian words that cannot hyphenate without patterns.)
- Compile with lualatex using the same build-dir pattern:

    cd cv && rm -f <file>.pdf && mkdir -p build && lualatex -interaction=nonstopmode -output-directory=build <file>.tex && mv build/<file>.pdf ./

The 1-page limit and every style rule below are unchanged. Worked example: `cv/main_цемрос_mlинженер.tex`.

## Style rules

- 10pt letterpaper `article`; margins top/bottom 0.3in, left/right 0.5in; `\pagestyle{empty}` (no page number)
- Body font is Lato (`\usepackage[default]{lato}`, T1) for Latin CVs; DejaVu Sans (fontspec) for Russian CVs
- Centered contact header: name in `{\LARGE \textbf{...}}`, location on the next line, then a single row of phone / email / GitHub / LinkedIn spread with `\hfill` (FontAwesome5 icons plus link text)
- Each section is introduced by `\hrule` followed by a negative `\vspace` (-0.5em or -1em) to tighten the rule-to-heading gap
- Section order: Desired Position, Experience (N+ years), Skills (optional, commented out in the skeleton), Education, Languages
- Entries use `\headerrow{left}{right}` (a `tabular*` with `\extracolsep{\fill}`): organization left / location right, then italic role left / date range right
- Tight lists: experience and education use `itemize` with `leftmargin=1em, noitemsep`; experience bullets are `itemize*` (mdwlist) with `\parskip=0.1em`. Top-level experience labels are blank (no bullet), second level is `$\bullet$`
- Date format: full month name + year joined by a single ASCII hyphen, `Present` for the current role (e.g. `June 2024 - August 2025`). This deliberately differs from the sample source, which used `--`: LaTeX renders `--` as a U+2013 en dash, which the framework's `--ascii-dates` ATS check rejects (a confirmed Workday import failure). Keep `--` only in prose numeric ranges, never in dates.
- Keep the contact row to four items; `\hfill` spreads them edge-to-edge

## Known pitfalls

- The source used the legacy FontAwesome 4 macro `\faLinkedinSquare`, which `fontawesome5` does not define. The skeleton uses `\faLinkedin` (square LinkedIn logo); do not revert.
- Latin CVs must use pdflatex: under lualatex/xelatex the `lato` package looks for OpenType `Lato-*.ttf` fonts that are not installed and the compile dies with `Package fontspec Error: The font "Lato-Regular" cannot be found`. pdflatex loads the Type1 fonts shipped with TeX Live instead. Russian CVs use the lualatex + DejaVu variant documented above.
- With the default pdflatex preamble, a Russian CV compiles with exit 0 and the correct page count while every Cyrillic character is dropped (T1 has no Cyrillic). Always use the Russian CV variant above and confirm Cyrillic round-trips in the extracted text layer before presenting.
- A `[PLACEHOLDER]` token placed directly after `\item` is parsed as the item's custom label rather than body text. The skeleton braces such tokens (`\item {[TARGET_ROLE]}`); keep the braces when substituting.
- `\unindentsection` is unused and its width argument (`-0.5#1`) is malformed; do not use it.
- `\DeclareFontFamily{U}{fontawesomeOne}` / `\FAone` are vestigial FontAwesome 4 declarations kept from the source; harmless under pdflatex.
- pypdf's default (`plain`) text extraction inserts a phantom space inside words starting with a kerned capital T (`T eam`, `T echnology`, `T ools`). This is a pypdf quirk - DejaVu Sans under lualatex shows it too - not a defect in the PDF: Poppler (`pdftotext`) and pypdf's `extraction_mode='layout'` extract the same file cleanly. If a `tools/verify_pdf.py --contains` check fails on such a word, confirm with `pdftotext` before editing the CV.
- `hyperref` is loaded without `hidelinks`/`colorlinks`, so default link boxes are drawn around the email/GitHub/LinkedIn links. This is inherited from the source; add `\hypersetup{hidelinks}` to the preamble only if the boxes are unwanted.
- `\renewcommand\labelitemi{}` and `\labelitemii{$\bullet$}` sit at top level just before the Experience list, so they apply to the rest of the document: only Desired Position keeps a bullet, while Experience/Education/Languages entries are unbulleted by design. Moving the renewcommands inside a group (or later) restores bullets.
- The commented-out blocks (extra COMPANY_2 entry and the Skills section) are optional structure: uncomment and fill them, or delete them as needed.
- Geometry is very tight (0.3in top/bottom); overflowing content is cut off rather than flowing to a second page, so /apply's 1-page limit is enforced by trimming content, not by adding pages.
