"""Style SOP content validator."""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

from mahavishnu.core.style_sop import load_style_sop

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


def check_content(content: str, start_path: Path | None = None) -> list[dict[str, Any]]:
    """Check content against the active SOP. Returns list of violations.

    Each violation is {pattern, message, source_sop}.
    """
    sop = load_style_sop(start_path)
    violations: list[dict[str, Any]] = []
    for ban in sop["frontmatter"].get("bans", []):
        pattern = ban.get("pattern", "")
        message = ban.get("message", "Banned pattern")
        try:
            if re.search(pattern, content, re.MULTILINE):
                violations.append(
                    {
                        "pattern": pattern,
                        "message": message,
                        "source_sop": str(sop["source_path"]),
                    }
                )
        except re.error as exc:
            logger.warning(
                "skipping invalid regex pattern in SOP",
                extra={"pattern": pattern, "error": str(exc)},
            )
    return violations
