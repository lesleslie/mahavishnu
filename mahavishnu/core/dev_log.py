"""Audit-log writer for the trunk-based agent-review workflow.

Per REQ-003 (spec §Requirements). Concurrency: file-lock on append +
atomic rename so a crash mid-write leaves the previous log intact.
Best-effort session-buddy mirror via mcp__session_buddy__store_reflection.

Implements: REQ-003
"""

from __future__ import annotations

import fcntl
import json
from pathlib import Path
import sys
from typing import Any

from .paths import DEV_LOG_DIR, get_dev_log_path


def _format_frontmatter(metadata: dict[str, Any]) -> str:
    """Render metadata as YAML frontmatter.

    Scalars are emitted as ``key: value``; lists of scalars become
    block lists; lists of dicts become block lists with each dict's
    scalar fields rendered as indented keys (reviewers per spec §4.3);
    top-level dicts are JSON-serialized inline (push/cleanup blocks).
    """
    lines = ["---"]
    for key, value in metadata.items():
        if value is None:
            continue
        if isinstance(value, list):
            lines.append(f"{key}:")
            for item in value:
                if isinstance(item, dict):
                    for sub_key, sub_value in item.items():
                        lines.append(f"  - {sub_key}: {_yaml_scalar(sub_value)}")
                else:
                    lines.append(f"  - {_yaml_scalar(item)}")
        elif isinstance(value, dict):
            lines.append(f"{key}: {json.dumps(value, sort_keys=True, separators=(',', ':'))}")
        else:
            lines.append(f"{key}: {_yaml_scalar(value)}")
    lines.append("---")
    return "\n".join(lines) + "\n\n"


def _yaml_scalar(value: Any) -> str:
    """Render a scalar as a YAML inline value.

    Strings are quoted only when they would otherwise be parsed as
    something else (numeric, bool, null, or contain a YAML-special
    token); ints/bools/None round-trip; strings without quoting land as
    bare scalars so the reviewers dict reads naturally.
    """
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        if value == "":
            return '""'
        # Quote anything that YAML 1.1 would coerce to bool/null/num,
        # or that contains a YAML-special character.
        lowered = value.strip().lower()
        yaml_special = {
            "true",
            "false",
            "yes",
            "no",
            "on",
            "off",
            "null",
            "~",
            "nan",
            "inf",
            "-inf",
        }
        if lowered in yaml_special:
            return json.dumps(value)
        try:
            float(value)
            return json.dumps(value)
        except ValueError:
            pass
        if any(
            ch in value
            for ch in (
                ":",
                "#",
                "{",
                "}",
                "[",
                "]",
                ",",
                "&",
                "*",
                "!",
                "|",
                ">",
                "'",
                '"',
                "%",
                "@",
                ">",
                "<",
                "?",
                "\n",
                "\t",
            )
        ):
            return json.dumps(value)
        return value
    return json.dumps(value, separators=(",", ":"))


def write_entry(
    metadata: dict[str, Any],
    body: str,
    *,
    mirror_to_session_buddy: bool = True,
) -> Path:
    """Append an audit entry to the dev log. Returns the file path written.

    Args:
        metadata: YAML frontmatter fields (date, branch, reviewers, gate,
            merge, push, cleanup, etc.).
        body: Markdown body of the entry (semantic-commit summary, etc.).
        mirror_to_session_buddy: If True, mirror to session-buddy via
            mcp__session_buddy__store_reflection. Failure is logged
            and reflected as ``session_buddy_reflection_id: null`` in
            the frontmatter; local file is canonical.

    Returns:
        Path to the file written.

    Concurrency: ``fcntl.flock`` on a per-directory lock file + atomic
    rename so a crash mid-write leaves the previous log intact.
    """
    date = str(metadata.get("date", ""))
    branch_slug = str(metadata.get("branch", "unknown"))
    filename = f"{date}-{branch_slug}.md"
    target = get_dev_log_path(filename)
    target.parent.mkdir(parents=True, exist_ok=True)

    frontmatter = _format_frontmatter(metadata)
    full_content = frontmatter + body

    lock_path = DEV_LOG_DIR / ".write.lock"
    lock_path.touch(exist_ok=True)
    with open(lock_path, "w") as lock_fd:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        try:
            tmp_path = target.with_suffix(".md.tmp")
            tmp_path.write_text(full_content)
            tmp_path.rename(target)
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)

    if mirror_to_session_buddy:
        _mirror_to_session_buddy(metadata, body, target)

    return target


def _mirror_to_session_buddy(metadata: dict[str, Any], body: str, target: Path) -> None:
    """Best-effort session-buddy mirror. On success, the target file's
    session_buddy_reflection_id field is set to the returned UUID. On
    failure, logs to stderr; entry remains canonical.
    """
    try:
        # Lazy import: the MCP client is only available in the running
        # server context. Tests stub this via monkeypatch.
        from mcp__session_buddy import store_reflection  # type: ignore[import-not-found]
    except ImportError:
        # MCP client not available; per spec §4.3 record the failure
        # in the frontmatter and log to stderr.
        _set_session_buddy_reflection_id(target, "null")
        print(
            f"[dev_log] session-buddy MCP client unavailable; "
            f"local entry at {target} is canonical.",
            file=sys.stderr,
        )
        return

    try:
        result = store_reflection(
            content=f"# dev-log mirror\n\n{body}",
            tags=["dev-log", "merge-workflow"],
        )
        reflection_id = getattr(result, "id", None)
        if reflection_id:
            _set_session_buddy_reflection_id(target, reflection_id)
    except Exception as exc:  # pragma: no cover
        # Mirror is best-effort. Per spec §4.3 record the failure in the
        # frontmatter and log to stderr; entry remains canonical.
        _set_session_buddy_reflection_id(target, "null")
        print(
            f"[dev_log] session-buddy mirror failed: {exc!r}; "
            f"local entry at {target} is canonical.",
            file=sys.stderr,
        )


def _set_session_buddy_reflection_id(target: Path, reflection_id: str) -> None:
    """Update the YAML frontmatter on `target` to set
    session_buddy_reflection_id (replaces or inserts before closing ---).
    """
    text = target.read_text()
    if "session_buddy_reflection_id:" in text:
        new_lines = [
            line
            for line in text.splitlines()
            if not line.startswith("session_buddy_reflection_id:")
        ]
        new_lines.insert(
            len(new_lines) - 1,
            f"session_buddy_reflection_id: {reflection_id}",
        )
        target.write_text("\n".join(new_lines) + "\n")
    else:
        if text.rstrip().endswith("---"):
            text = text.rstrip()[:-3].rstrip()
            text += f"\nsession_buddy_reflection_id: {reflection_id}\n---\n"
        else:
            text += f"\nsession_buddy_reflection_id: {reflection_id}\n"
        target.write_text(text)
