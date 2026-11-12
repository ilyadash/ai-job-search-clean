---
name: document-extraction
version: 1.0.0
description: >
  Extract text from career documents (CVs, diplomas, scans, LinkedIn exports)
  when the default Read tool cannot parse them. Use for legacy .doc/RTF files,
  PDFs without a text layer, and images that need OCR. Trigger phrases: read
  .doc, extract text from document, OCR scan, recognise text, распознай скан,
  извлеки текст из документа, прочитай .doc, прочитай .pdf, конвертируй резюме
  в текст.
allowed-tools: Read, Bash(file *), Bash(catdoc *), Bash(antiword *), Bash(pdftotext *), Bash(pdftoppm *), Bash(tesseract *), Bash(python3 *)
---

# Document Extraction

Turn career documents into plain text the workflow can actually read. The
container ships the tools this skill relies on: `antiword`, `catdoc`,
`pdftotext`/`pdftoppm` (poppler-utils) and `tesseract` with the `eng` and `rus`
language packs.

> **Never install packages at runtime.** `pip`, `apt-get` and global `npm`
> installs fail here by design (read-only root filesystem) and are not the fix
> for a missing tool. If something is genuinely missing - a binary or a Python
> module - say which one and why it is needed, then continue without it; the
> user adds it to the container image (Dockerfile) instead.

## When to use

- `/setup` Path A or `/expand` hits a document the `Read` tool returns garbage
  or an error for (legacy `.doc`, RTF, scanned PDFs, images).
- A document "reads" as empty or as binary noise.
- Someone asks you to read a CV/diploma/certificate that is a scan.

## Step 1: detect the real format

Extensions lie. Always start with:

```bash
file "/work/documents/<subdir>/<name>"
```

A `.doc` can really be RTF (Word says so: `Rich Text Format`), a `.pdf` can be
a container with no text layer, a `.png` can be a photo of a page.

## Step 2: extract by format

| Detected format | Command |
|---|---|
| Real Word 97-2003 (`.doc`) | `antiword "file.doc"` (fallback: `catdoc "file.doc"`) |
| RTF, including `.doc` files that antiword rejects with "not a Word Document … probably a Rich Text Format file" | `catdoc "file.doc"` |
| `.docx` | `python3` with `zipfile` on `word/document.xml` (see below) |
| PDF with a text layer | `pdftotext -layout "file.pdf" -` |
| Scanned PDF (pdftotext returns almost nothing) | render then OCR: `pdftoppm -r 200 -png "file.pdf" /tmp/page && for f in /tmp/page-*.png; do tesseract "$f" - -l rus+eng; done` |
| PNG / JPG | `tesseract "file.png" - -l rus+eng` |
| Plain text with odd encoding (e.g. Windows-1251) | `python3` decode: `open(path, "rb").read().decode("cp1251")`, fall back to `errors="replace"` |

`.docx` extraction without extra libraries:

```bash
python3 - "file.docx" <<'PY'
import re, sys, zipfile
with zipfile.ZipFile(sys.argv[1]) as z:
    xml = z.read("word/document.xml").decode("utf-8", "replace")
xml = xml.replace("</w:p>", "\n")
print(re.sub(r"<[^>]+>", "", xml))
PY
```

## Step 3: verify the extraction

- Size matters: `... | wc -c`. A multi-page document yielding < ~100 bytes
  means the text layer was missing - switch to the OCR path.
- Reject garbage: `(cid:NNN)` markers, `�` replacement characters, or long runs
  of control symbols mean the wrong decoder was used.
- Never feed raw binary to the model as a reading strategy; extract first, then
  quote only the text.

## Step 4: long output

For anything longer than a screenful, save it and read it back - it is reusable
and keeps the conversation manageable:

```bash
... > /tmp/<name>.txt && wc -c /tmp/<name>.txt
```

Then `Read` `/tmp/<name>.txt`.

## Notes

- Images and scans are handled by `tesseract` and `pdftoppm` - PIL/Pillow is
  not needed and must not be installed.
- Russian text needs `-l rus+eng` in tesseract; without it OCR returns
  transliterated noise.
- If OCR quality is poor, retry with a higher DPI (`-r 300`) or a single page
  (`-f 1 -l 1`).
- If a document cannot be extracted at all, say so explicitly and continue with
  the remaining sources. Never invent content for an unreadable file.
