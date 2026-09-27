"""Markdown exporter — converts card dicts back to .mahavishnu/board.md."""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from oneiric.actions.data import DataTransformAction
from oneiric.core.logging import get_logger

logger = get_logger(__name__)


def render_board(cards: list[dict[str, Any]]) -> str:
    """Render cards grouped by section, with checkbox markers.

    Cards missing the ``status`` field are silently dropped (defensive —
    ``parse_board`` always sets it). The output ends with a single
    trailing newline to match POSIX text-file conventions.
    """
    by_section: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for card in cards:
        status = card.get("status")
        if status is None:
            continue
        by_section[status].append(card)

    lines: list[str] = []
    for section in ("backlog", "ready", "in_progress", "done"):
        section_cards = by_section.get(section, [])
        if not section_cards:
            continue
        title = section.replace("_", " ").title()
        lines.append(f"## {title}")
        lines.append("")
        for card in section_cards:
            marker = "x" if section == "done" else " "
            lines.append(
                f"- [{marker}] {card['id']} | {card['pool']} | {card['prompt']}"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


async def transform_for_export(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Use Oneiric DataTransformAction to select fields for export.

    Per the action kit, the ``include_fields`` payload key restricts the
    output to the documented wire shape. ``title``/``expected_revision``
    are intentionally dropped from exported markdown.
    """
    transform = DataTransformAction()
    transformed: list[dict[str, Any]] = []
    for card in cards:
        result = await transform.execute(
            {"data": card, "include_fields": ["id", "status", "pool", "prompt"]}
        )
        if "data" in result:
            transformed.append(result["data"])
    return transformed
