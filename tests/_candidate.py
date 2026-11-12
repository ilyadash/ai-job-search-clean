"""Read the candidate's name from the personal-data profile at test runtime.

The repository principle is that committed code is profile-agnostic: personal
data is added at runtime by ``/setup`` (see ``templates/README.md`` and
``tests/test_placeholder_integrity.py``). Tests must therefore not hardcode
the candidate's real name. They read it from the profile and fall back to a
synthetic name when the profile is still a placeholder (the upstream template)
or empty (e.g. between ``/reset profile`` and ``/setup``).
"""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SKILL_PROFILE = (
    REPO
    / ".claude"
    / "skills"
    / "job-application-assistant"
    / "01-candidate-profile.md"
)
CLAUDE_MD = REPO / "CLAUDE.md"

# Synthetic, profile-agnostic fallback. Committed code may hardcode this name;
# it must never hardcode the candidate's real one.
SAMPLE_NAME = "Иван Иванов"

_NAME_RE = re.compile(r"^\s*-\s*\*\*Name:\*\*\s*(.+?)\s*$", re.MULTILINE)
# A value is a placeholder when it is empty or entirely wrapped in square
# brackets, e.g. ``[YOUR_NAME]`` or ``[First] [Last]``.
_PLACEHOLDER_RE = re.compile(r"^\[.*\]$")


def _read_name(path: Path) -> str:
    """The ``- **Name:**`` value from one profile file, or '' when absent."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    match = _NAME_RE.search(text)
    if not match:
        return ""
    # Drop a trailing inline HTML comment, if any.
    return match.group(1).split("<!--", 1)[0].strip()


def read_profile_name(repo: Path = REPO) -> tuple[str, bool]:
    """``(name, is_placeholder)`` for the candidate, read from the profile.

    Tries the skill profile first, then ``CLAUDE.md``. A value is a placeholder
    when it is empty or entirely wrapped in square brackets (``[YOUR_NAME]``,
    ``[First] [Last]``).
    """
    skill = (
        repo
        / ".claude"
        / "skills"
        / "job-application-assistant"
        / "01-candidate-profile.md"
    )
    claude = repo / "CLAUDE.md"
    for path in (skill, claude):
        value = _read_name(path)
        if not value:
            continue
        return value, bool(_PLACEHOLDER_RE.match(value))
    return "", True


def candidate_name(repo: Path = REPO) -> str:
    """The real name when the profile carries one, else ``SAMPLE_NAME``."""
    name, is_placeholder = read_profile_name(repo)
    return SAMPLE_NAME if is_placeholder or not name else name


def signature_name(full_name: str) -> str:
    """How the name appears on a letter sign-off: surname + first name.

    For ``Фамилия Имя Отчество`` this drops the patronymic (the first two
    tokens); a two-token Western name is returned unchanged.
    """
    tokens = full_name.split()
    if len(tokens) >= 2:
        return " ".join(tokens[:2])
    return full_name.strip()
