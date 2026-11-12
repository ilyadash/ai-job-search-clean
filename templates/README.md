# Custom Templates

This folder holds user-registered **CV** templates (LaTeX, Typst, or any other toolchain with a declared compile command, managed by `/add-template-cv`) and **cover-letter** templates (plain text only, managed by `/add-template-cover-letter`). The framework works out of the box with its stock template (moderncv for CVs; the plain-text structure in `06-cover-letter-templates.md` for cover letters) — this folder only gets content when you register your own.

## Layout

```
templates/
├── cv/
│   └── <template-name>/
│       ├── template.<ext>  # Profile-agnostic skeleton ([PLACEHOLDER] tokens), e.g. template.tex or template.typ
│       ├── TEMPLATE.md      # Manifest: source extension, compile command, fonts, page limit, style rules, pitfalls
│       ├── *.cls / *.sty    # Custom class/style files, or Typst packages (if the template needs them)
│       └── fonts/           # Bundled font files (if not using system fonts)
└── cover_letters/
    └── <template-name>/
        ├── template.txt      # Plain-text, profile-agnostic skeleton ([PLACEHOLDER] tokens)
        └── TEMPLATE.md       # Manifest: language rule, body word limit + portal character cap, block structure, content rules, pitfalls
```

## How it works

- `/add-template-cv` interviews you for a CV template's instructions (source extension, compile command, fonts, style rules, page limit), stores the files here, and runs a mandatory test compile before registering anything.
- Activating a CV template adds a managed block to `05-cv-templates.md`. In this fork `/apply` does not draft or compile CVs — the block is a reference for the existing CV, not workflow wiring.
- `/add-template-cover-letter` does the text-only equivalent for cover letters: it stores a profile-agnostic `.txt` skeleton plus the structure, content rules, body word limit and any portal character cap, verifies them textually (there is no compile step to run), and activates them via a managed block in `06-cover-letter-templates.md`. The letter itself stays plain text and is never compiled.
- `/add-template-cv --list` shows registered CV templates; `/add-template-cv --use <name>` switches; `/add-template-cv --use default` reverts to the stock moderncv template. The same flags work on `/add-template-cover-letter`, whose `--use default` reverts to the stock `06` structure.
- Templates of both kinds are stored with `[PLACEHOLDER]` tokens instead of personal data, so they are safe to commit and share.
