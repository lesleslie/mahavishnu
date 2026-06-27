"""Crackerjack skill: anti-ai-flavor-check.

Validates generated content (MR descriptions, commit messages, etc.)
against the active style SOP. Returns violations with source SOP path.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mahavishnu.core.style_sop import load_style_sop
from mahavishnu.core.style_sop_validator import check_content


def run_anti_ai_flavor_check(content: str, file_path: Path) -> dict[str, Any]:
    """Crackerjack skill entry point.

    Args:
        content: the generated content (MR description, commit message, etc.)
        file_path: where the content was generated; used for SOP discovery.

    Returns:
        {"violations": [...], "sop_source": "..."}
    """
    violations = check_content(content, file_path.parent)
    sop = load_style_sop(file_path.parent)
    return {
        "violations": violations,
        "sop_source": str(sop["source_path"]) if sop["source_path"] else None,
    }
