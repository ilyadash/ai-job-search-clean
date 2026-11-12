#!/usr/bin/env python3
"""Replace the master CV (cv/main_example.tex) with a personal-data-free stub.

/reset's `templates` branch restores cv/main_example.tex from
`upstream/master`. When that remote is unavailable (a hand-off copy without
.git, or an unfetched fork), this script is the fallback. It replaces the whole
file with the bundled pristine stock template (tools/stock_main_example.tex),
so no name, contact details, work history, or publication is left behind. If
the bundled template is missing, it falls back to stubbing only the moderncv
contact macros in place.

This script is destructive by design: it is meant for /reset's fallback or a
throwaway copy, never for a CV you want to keep.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

STOCK = Path(__file__).resolve().parent / "stock_main_example.tex"

# (regex, replacement). The regexes are anchored to the moderncv contact macros
# so body text is never touched.
_MACROS = [
    (r"\\name\{[^{}]*\}\{[^{}]*\}", r"\\name{[First]}{[Last]}"),
    (r"\\address\{[^{}]*\}\{[^{}]*\}\{[^{}]*\}", r"\\address{[Your Address, City, Country]}{}{}"),
    (r"\\phone(?:\[[^{}]*\])?\{[^{}]*\}", r"\\phone[mobile]{[+XX XXXXXXXXXX]}"),
    (r"\\email\{[^{}]*\}", r"\\email{[your.email@example.com]}"),
    (r"\\extrainfo\{[^{}]*\}", r"\\extrainfo{[https://linkedin.com/in/your-profile] [https://github.com/your-username]}"),
]

# Substrings that mark a field as already a placeholder (not personal data).
_PLACEHOLDER_MARKERS = (
    "[First]", "[Last]", "[Your Address", "[+XX ",
    "[your.email@example.com]", "your-profile", "your-username",
)


def _is_comment(line: str) -> bool:
    """True for a full-line LaTeX comment (leading `%` after whitespace)."""
    return line.lstrip().startswith("%")


def _replace_with_stock(path: Path) -> int:
    path.write_text(STOCK.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"sanitize_master_cv: replaced {path} with the bundled stock template")
    return 0


def _stub_contacts(path: Path) -> int:
    original = path.read_text(encoding="utf-8")
    changed = 0
    out_lines = []
    for line in original.splitlines(keepends=True):
        # Never touch comment lines: e.g. the template's own note about
        # `\address{}{}{} fails` is documentation, not a contact field.
        if _is_comment(line):
            out_lines.append(line)
            continue
        for pattern, replacement in _MACROS:
            line, n = re.subn(pattern, replacement, line)
            changed += n
        out_lines.append(line)

    text = "".join(out_lines)
    if text != original:
        path.write_text(text, encoding="utf-8")
    print(f"sanitize_master_cv: rewrote {changed} contact field(s) in {path}")

    # Verify nothing personal survives in the three most sensitive macros.
    # Comments are excluded for the same reason the rewrite skips them.
    code = "".join(line for line in text.splitlines(keepends=True) if not _is_comment(line))
    personal = []
    for label, pattern in (
        ("name", r"\\name\{([^{}]*)\}\{([^{}]*)\}"),
        ("phone", r"\\phone(?:\[[^{}]*\])?\{([^{}]*)\}"),
        ("email", r"\\email\{([^{}]*)\}"),
    ):
        match = re.search(pattern, code)
        if match and not any(marker in match.group(0) for marker in _PLACEHOLDER_MARKERS):
            personal.append((label, match.group(0)))
    if personal:
        for label, value in personal:
            print(f"sanitize_master_cv: WARNING - {label} still looks personal: {value}", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str]) -> int:
    path = Path(argv[1]) if len(argv) > 1 else Path("cv/main_example.tex")
    if not path.exists():
        print(f"sanitize_master_cv: {path} not found; nothing to sanitize", file=sys.stderr)
        return 0
    if STOCK.exists():
        return _replace_with_stock(path)
    return _stub_contacts(path)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
