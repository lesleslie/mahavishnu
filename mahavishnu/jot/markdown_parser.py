"""Markdown parser for our jot board files.

Scoped to the .mahavishnu/board.md format ONLY. Not a generic
markdown-board engine (per mahavishnu niche filter).
"""

from __future__ import annotations

import re
from typing import Any
from uuid import uuid4

from oneiric.actions.data import ValidationSchemaAction
from oneiric.core.logging import get_logger

from mahavishnu.core.errors import MarkdownParseError

logger = get_logger(__name__)


CARD_SECTION_VALUES: tuple[str, ...] = (
    "backlog",
    "ready",
    "in_progress",
    "done",
)
"""Validation enum values for MHCard.status.

Explicit tuple per crackerjack-compliant-code — passing
``list(TaskCategory)`` would create an enum dependency on the routing
layer.
"""


async def parse_board(content: str) -> list[dict[str, Any]]:
    """Parse .mahavishnu/board.md into a list of card dicts.

    Format (one card per section)::

        ## Backlog
        - [ ] card-id | pool | prompt text
        - [ ] card-id-2 | pool | prompt text

        ## Ready
        - [x] card-id-3 | pool | prompt text (completed)

    Sections are identified by ``## <name>`` headers. Cards are
    identified by checkbox items. Each parsed card is validated against
    the Oneiric ValidationSchemaAction schema.
    """
    sections = _split_by_headers(content)
    cards: list[dict[str, Any]] = []
    for section_name, section_body in sections.items():
        status = _section_to_status(section_name)
        if status is None:
            continue
        for line in section_body.splitlines():
            stripped = line.strip()
            if not stripped.startswith("- ["):
                continue
            card = _parse_card_line(stripped, status)
            if card is not None:
                cards.append(card)

    if not cards:
        return []

    validator = ValidationSchemaAction()
    fields = _card_field_rules()
    failures: list[str] = []
    for card in cards:
        result = await validator.execute({"data": card, "fields": fields})
        if result.get("errors"):
            failures.append(f"{card.get('id', '?')}: {result['errors']}")
    if failures:
        raise MarkdownParseError(
            f"validation failed for {len(failures)} card(s): " + "; ".join(failures[:3])
        )
    return cards


def _split_by_headers(content: str) -> dict[str, str]:
    """Split markdown by ``## <name>`` headers; return name -> body map."""
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in content.splitlines():
        m = re.match(r"^##\s+(.+)$", line)
        if m:
            current = m.group(1).strip()
            sections[current] = []
        elif current is not None:
            sections[current].append(line)
    return {k: "\n".join(v) for k, v in sections.items()}


def _section_to_status(name: str) -> str | None:
    """Map section header name to a CARD_SECTION_VALUES value.

    Headers may use either case and either spaces or underscores
    (e.g. ``## In Progress`` or ``## in_progress``). Normalize both
    spaces and underscores before substring matching so a single
    CARD_SECTION_VALUES entry canonically resolves either form.
    """
    lower = name.lower().strip().replace("_", " ").replace("  ", " ").strip()
    for valid in CARD_SECTION_VALUES:
        # CARD_SECTION_VALUES uses underscores; the normalized header
        # uses spaces. Translate the underscore form to space form for
        # the membership check.
        canonical_spaced = valid.replace("_", " ")
        if canonical_spaced in lower:
            return valid
    return None


def _parse_card_line(line: str, status: str) -> dict[str, Any] | None:
    """Parse ``- [ ] card-id | pool | prompt`` into a card dict.

    ``status`` is rewritten to ``done`` when the checkbox marker is ``x``
    or ``X``; callers that read parse_board's return list should treat
    the per-card ``status`` field as authoritative.
    """
    if line.startswith(("- [x]", "- [X]")):
        status = "done"
        line = line[5:].strip()
    elif line.startswith("- [ ]"):
        line = line[5:].strip()
    else:
        return None
    parts = [p.strip() for p in line.split("|", 2)]
    if len(parts) < 3:
        return None
    card_id = parts[0] or str(uuid4())
    return {
        "id": card_id,
        "status": status,
        "pool": parts[1],
        "title": card_id,
        "prompt": parts[2],
        "expected_revision": None,
    }


def _card_field_rules() -> list[dict[str, Any]]:
    """Field rules for Oneiric ValidationSchemaAction.

    Oneiric's ``ValidationFieldRule`` only supports Literal
    ``["str","int","float","bool","dict","list","any"]`` — there is no
    ``enum`` type and no per-field ``values`` constraint. Enum membership
    is enforced by ``parse_board`` post-validation via ``status``-field
    substring matching done in :func:`_section_to_status`.

    The schema is permissive on extra keys so callers may attach hints
    (e.g. ``expected_revision``) without tripping the validator.
    """
    return [
        {"name": "id", "type": "str", "required": True, "allow_null": False},
        {"name": "status", "type": "str", "required": True, "allow_null": False},
        {"name": "pool", "type": "str", "required": True, "allow_null": False},
        {"name": "title", "type": "str", "required": True, "allow_null": False},
        {"name": "prompt", "type": "str", "required": True, "allow_null": False},
        {
            "name": "expected_revision",
            "type": "int",
            "required": False,
            "allow_null": True,
        },
    ]
