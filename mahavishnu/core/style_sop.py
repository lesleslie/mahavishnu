"""Style SOP discovery and parsing."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def discover_style_sop(start_path: Path | None = None) -> Path | None:
    """Walk up from start_path looking for .bodai/style-sop.md.

    Returns the path or None if no SOP is found within the filesystem root.
    """
    start = (start_path or Path.cwd()).resolve()
    current = start
    while True:
        candidate = current / ".bodai" / "style-sop.md"
        if candidate.exists():
            return candidate
        if current.parent == current:
            return None
        current = current.parent


_PACKAGED_DEFAULT_SOP = Path(__file__).parent.parent / "style-sop.md"


def _parse_sop(path: Path) -> dict[str, Any]:
    text = path.read_text()
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end > 0:
            frontmatter = yaml.safe_load(text[4:end]) or {}
            body = text[end + 5 :]
        else:
            frontmatter = {}
            body = text
    else:
        frontmatter = {}
        body = text
    return {
        "frontmatter": frontmatter,
        "body": body,
        "source_path": path,
    }


def load_style_sop(start_path: Path | None = None) -> dict[str, Any]:
    """Load the active SOP. Returns {frontmatter, body, source_path}.

    Discovery order:
    1. .bodai/style-sop.md walking up from start_path
    2. Packaged default at mahavishnu/style-sop.md
    3. Empty SOP (no bans)
    """
    repo_sop = discover_style_sop(start_path)
    if repo_sop:
        return _parse_sop(repo_sop)
    if _PACKAGED_DEFAULT_SOP.exists():
        return _parse_sop(_PACKAGED_DEFAULT_SOP)
    return {
        "frontmatter": {"bans": [], "required_disclosures": []},
        "body": "",
        "source_path": None,
    }
