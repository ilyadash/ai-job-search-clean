#!/usr/bin/env python3
"""Deterministic plain-text checks for /apply cover letters.

The cover letter is pasted verbatim into a portal field, so the mechanical
rules are enforced here rather than by re-reading the file with the model:
body-only structure, no markup/LaTeX/placeholders, the active template's
length limits, no em-dashes, and no banned gap phrases.

Content judgement (targeting, factual grounding, voice) stays with the agent.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_FILE = (
    ROOT
    / ".claude"
    / "skills"
    / "job-application-assistant"
    / "06-cover-letter-templates.md"
)
DEFAULT_WORDS = (250, 300)

GREETING_RE = re.compile(
    r"(?i)^(здравствуйте|добрый день|добрый вечер|доброе утро|приветствую|"
    r"hello\b|hi\b|dear\b|hallo\b|hej\b|bonjour\b)"
)
SIGNOFF_RE = re.compile(
    r"(?i)(с уважением|с наилучшими пожеланиями|спасибо за внимание|"
    r"sincerely|best regards|kind regards|regards\b|"
    r"med venlig hilsen|venlig hilsen|mit freundlichen grüßen|mfg\b)"
)
BANNED_PHRASES = (
    "сразу обозначу границы",
    "чего у меня пока нет",
    "чего у меня нет",
    "вне моего стека",
    "не мой стек",
    "у меня нет опыта",
    "я не умею",
)
WORD_RANGE_RE = re.compile(r"(\d+)\s*(?:[-–]\s*(\d+))?")


def parse_word_range(value: str) -> tuple[int, int]:
    match = WORD_RANGE_RE.search(value or "")
    if not match:
        raise ValueError(f"invalid word range: {value!r}")
    low = int(match.group(1))
    high = int(match.group(2) or match.group(1))
    if low < 1 or high < low:
        raise ValueError(f"invalid word range: {value!r}")
    return low, high


def template_limits(repo: Path = ROOT) -> tuple[tuple[int, int], int | None]:
    """(word range, character cap) from the active template, if any."""
    path = repo / ".claude" / "skills" / "job-application-assistant" / "06-cover-letter-templates.md"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return DEFAULT_WORDS, None
    block = re.search(
        r"(?is)<!--\s*BEGIN ACTIVE-TEMPLATE.*?-->(.*?)<!--\s*END ACTIVE-TEMPLATE\s*-->",
        text,
    )
    if not block:
        return DEFAULT_WORDS, None
    body = block.group(1).replace("*", "")
    words = DEFAULT_WORDS
    match = re.search(
        r"(?i)Word limit:\s*`?(\d+)\s*(?:[-–]\s*(\d+))?`?", body
    )
    if match:
        words = (int(match.group(1)), int(match.group(2) or match.group(1)))
    chars: int | None = None
    cap = re.search(r"(?i)Character limit:\s*`?(none|\d+)`?", body)
    if cap and cap.group(1).lower() != "none":
        chars = int(cap.group(1))
    if cap is None or chars is None and not cap:
        manifest = re.search(r"(?i)Manifest:\s*`([^`]+)`", body)
        if manifest:
            manifest_path = repo / manifest.group(1)
            try:
                manifest_text = manifest_path.read_text(encoding="utf-8").replace("*", "")
            except OSError:
                manifest_text = ""
            cap = re.search(
                r"(?i)Character limit:\s*(none|\d+)", manifest_text
            )
            if cap and cap.group(1).lower() != "none":
                chars = int(cap.group(1))
            if not match:
                word = re.search(
                    r"(?i)Word limit:\s*(\d+)\s*(?:[-–]\s*(\d+))?", manifest_text
                )
                if word:
                    words = (int(word.group(1)), int(word.group(2) or word.group(1)))
    return words, chars


def body_text(text: str) -> str:
    """The letter body: everything between the greeting and the sign-off."""
    lines = text.splitlines()
    non_empty = [line for line in lines if line.strip()]
    if len(non_empty) < 3:
        return ""
    return "\n".join(non_empty[1:-2]).strip()


def body_word_count(text: str) -> int:
    return len(body_text(text).split())


def check_letter(
    path: Path | str,
    words: tuple[int, int] = DEFAULT_WORDS,
    chars: int | None = None,
    language: str | None = None,
) -> list[tuple[bool, str]]:
    findings: list[tuple[bool, str]] = []
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        return [(False, f"cannot read letter: {exc}")]

    lines = text.splitlines()
    non_empty = [(index, line) for index, line in enumerate(lines) if line.strip()]
    if len(non_empty) < 3:
        return [(False, "letter needs a greeting, a body and a sign-off/signature")]

    first_index, greeting = non_empty[0]
    signoff_index, signoff = non_empty[-2]
    name_index, name = non_empty[-1]

    findings.append(
        (
            bool(GREETING_RE.match(greeting.strip())),
            f"greeting: {greeting.strip()[:80]!r}",
        )
    )
    findings.append(
        (
            bool(SIGNOFF_RE.search(signoff)),
            f"sign-off: {signoff.strip()[:80]!r}",
        )
    )
    findings.append(
        (bool(name.strip()), f"signature: {name.strip()[:80]!r}")
    )

    body_lines = lines[first_index + 1 : signoff_index]
    body = "\n".join(body_lines).strip()
    body_words = len(body.split())
    findings.append(
        (
            words[0] <= body_words <= words[1],
            f"body words: {body_words} (limit {words[0]}-{words[1]})",
        )
    )

    total_chars = len(text)
    if chars:
        findings.append(
            (
                total_chars <= chars,
                f"characters: {total_chars} (limit {chars})",
            )
        )
    else:
        findings.append((True, f"characters: {total_chars} (no limit)"))

    problems: list[str] = []
    for index, line in enumerate(lines, start=1):
        if re.search(r"\\[A-Za-z]+", line):
            problems.append(f"line {index}: LaTeX command")
        if re.search(r"\*\*|__|`", line):
            problems.append(f"line {index}: markdown markup")
        if re.search(r"^\s{0,3}#{1,6}\s", line):
            problems.append(f"line {index}: markdown heading")
        if re.search(r"\[[A-Z][A-Z0-9_ -]{1,}\]", line):
            problems.append(f"line {index}: unresolved placeholder")
        if re.search(r"<[A-Z][A-Z0-9_ -]{1,}>", line):
            problems.append(f"line {index}: unresolved placeholder")
        if re.search(r"\{\{[^}]+\}\}", line):
            problems.append(f"line {index}: unresolved placeholder")
        if "—" in line or "--" in line:
            problems.append(f"line {index}: em-dash")
    findings.append((not problems, "markup/placeholders/em-dashes: " + ("; ".join(problems) if problems else "none")))

    lowered = text.casefold()
    banned = [phrase for phrase in BANNED_PHRASES if phrase in lowered]
    findings.append(
        (
            not banned,
            "banned gap phrases: " + (", ".join(banned) if banned else "none"),
        )
    )

    if language:
        cyrillic = len(re.findall(r"[А-Яа-яЁё]", text))
        latin = len(re.findall(r"[A-Za-z]", text))
        if language == "ru":
            findings.append((cyrillic >= latin, f"language: ru (cyrillic {cyrillic}, latin {latin})"))
        elif language == "en":
            findings.append((latin >= cyrillic, f"language: en (cyrillic {cyrillic}, latin {latin})"))
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check a plain-text cover letter")
    parser.add_argument("path", help="cover letter .txt path")
    parser.add_argument("--words", help="word range override, e.g. 75-250")
    parser.add_argument("--chars", type=int, help="character cap override")
    parser.add_argument("--language", choices=("ru", "en"))
    args = parser.parse_args(argv)

    if args.words:
        try:
            words = parse_word_range(args.words)
        except ValueError as exc:
            parser.error(str(exc))
    else:
        words, _ = template_limits(ROOT)
    chars = args.chars
    if chars is None and not args.words:
        _, chars = template_limits(ROOT)

    findings = check_letter(args.path, words=words, chars=chars, language=args.language)
    for ok, message in findings:
        print(f"{'PASS' if ok else 'FAIL'} {message}")
    result = all(ok for ok, _ in findings)
    print(f"RESULT: {'PASS' if result else 'FAIL'}")
    return 0 if result else 1


if __name__ == "__main__":
    sys.exit(main())
