"""Security validation for skill synthesis inputs.

Ensures draft skills are safe to store and cannot escape their namespace.
All checks are pure functions with no side effects and no persistence writes.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mahavishnu.core.skill_governance import SkillDraft

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_SKILL_BODY_LENGTH: int = 100_000

DANGEROUS_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("__import__", re.compile(r"__import__\s*\(")),
    ("exec(", re.compile(r"\bexec\s*\(")),
    ("eval(", re.compile(r"\beval\s*\(")),
    ("compile(", re.compile(r"\bcompile\s*\(")),
    ("globals(", re.compile(r"\bglobals\s*\(")),
    ("locals(", re.compile(r"\blocals\s*\(")),
    ("getattr(", re.compile(r"\bgetattr\s*\(")),
    ("setattr(", re.compile(r"\bsetattr\s*\(")),
    ("delattr(", re.compile(r"\bdelattr\s*\(")),
]

# Patterns that indicate filesystem or network access.
# These produce *warnings*, not hard errors, because legitimate skills
# may reference (but not invoke) these APIs in documentation strings.
_FS_ACCESS_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("open(", re.compile(r"\bopen\s*\(")),
    ("Path(", re.compile(r"\bPath\s*\(")),
    ("pathlib", re.compile(r"\bpathlib\b")),
    ("os.path", re.compile(r"\bos\.path\b")),
]

_NETWORK_ACCESS_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("requests.", re.compile(r"\brequests\.")),
    ("httpx.", re.compile(r"\bhttpx\.")),
    ("urllib", re.compile(r"\burllib\b")),
    ("socket.", re.compile(r"\bsocket\.")),
    ("http.client", re.compile(r"\bhttp\.client\b")),
]

# Characters that must not appear in skill names (path traversal).
_PATH_SEPARATOR_CHARS = frozenset({"/", "\\", "."})

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def sanitize_skill_body(body: str) -> str:
    """Sanitize a skill body for safe storage.

    Steps:
    1. Strip dangerous patterns by replacing them with a comment marker.
    2. Collapse excessive whitespace (3+ consecutive blank lines become 2).
    3. Truncate to ``MAX_SKILL_BODY_LENGTH`` characters.

    Args:
        body: Raw skill body text.

    Returns:
        Sanitized body string safe for persistence.
    """
    sanitized = body

    # Remove dangerous patterns.
    for _label, pattern in DANGEROUS_PATTERNS:
        sanitized = pattern.sub(f"# [REDACTED: {_label}]", sanitized)

    # Collapse 3+ consecutive blank lines into exactly 2.
    sanitized = re.sub(r"\n{4,}", "\n\n\n", sanitized)

    # Enforce maximum length.
    if len(sanitized) > MAX_SKILL_BODY_LENGTH:
        sanitized = sanitized[:MAX_SKILL_BODY_LENGTH]
        logger.warning("Skill body truncated to %d characters.", MAX_SKILL_BODY_LENGTH)

    return sanitized


def validate_draft_isolation(draft: SkillDraft) -> list[str]:
    """Check that a draft cannot escape its namespace.

    Returns a list of human-readable issue descriptions.  An empty list
    means the draft passed all isolation checks.

    Checks:
    1. Skill name must not contain path separators (``/``, ``\\``, ``..``).
    2. Skill name must not start with underscore (reserved for internals).
    3. Body must not contain filesystem access patterns (warning).
    4. Body must not contain network access patterns (warning).
    """
    issues: list[str] = []

    # 1. Path separators in name.
    name = draft.name
    if any(ch in name for ch in _PATH_SEPARATOR_CHARS):
        issues.append(
            f"Skill name '{name}' contains path separator characters "
            f"(one of {sorted(_PATH_SEPARATOR_CHARS)})."
        )

    # 2. Leading underscore.
    if name.startswith("_"):
        issues.append(
            f"Skill name '{name}' starts with underscore, which is reserved for Python internals."
        )

    # 3. Filesystem access patterns in body.
    for label, pattern in _FS_ACCESS_PATTERNS:
        if pattern.search(draft.body):
            issues.append(
                f"Body contains filesystem access pattern '{label}'. "
                f"Ensure this is intentional and sandboxed."
            )

    # 4. Network access patterns in body.
    for label, pattern in _NETWORK_ACCESS_PATTERNS:
        if pattern.search(draft.body):
            issues.append(
                f"Body contains network access pattern '{label}'. "
                f"Ensure this is intentional and sandboxed."
            )

    return issues


def is_draft_namespace(skill_id: str) -> bool:
    """Return ``True`` if *skill_id* belongs to the draft namespace.

    Draft skills are identified by the ``draft/`` prefix.
    """
    return skill_id.startswith("draft/")


__all__ = [
    "DANGEROUS_PATTERNS",
    "MAX_SKILL_BODY_LENGTH",
    "is_draft_namespace",
    "sanitize_skill_body",
    "validate_draft_isolation",
]
