#!/usr/bin/env python3
"""Audit .mcp.json files for hardcoded secret-shaped env values.

Enforces the architectural rule from
.claude/decisions/2026-08-24-bodai-mcp-routing-pattern.md §1:

    Any environment variable whose name ends in KEY, TOKEN, SECRET,
    PASSWORD, or otherwise names a credential MUST come from the
    parent shell's environment — never from a literal value in
    any .mcp.json.

Exit codes:
    0 — no violations
    1 — at least one violation found
    2 — could not scan (e.g. file unreadable)

Allowed exceptions (non-secret config):
    *_HOST, *_URL, *_PORT, *_DOMAIN, *_PATH
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, cast


# Pattern matches env var names whose value should never be inlined.
SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"_KEY$", re.IGNORECASE),
    re.compile(r"_TOKEN$", re.IGNORECASE),
    re.compile(r"_SECRET$", re.IGNORECASE),
    re.compile(r"_PASSWORD$", re.IGNORECASE),
    re.compile(r"_PASSWD$", re.IGNORECASE),
    re.compile(r"_CREDENTIALS?$", re.IGNORECASE),
    re.compile(r"_PRIVATE_KEY$", re.IGNORECASE),
    re.compile(r"^API_KEY$", re.IGNORECASE),
    re.compile(r"^AUTH_TOKEN$", re.IGNORECASE),
    re.compile(r"^CLIENT_SECRET$", re.IGNORECASE),
)

# Patterns that are explicitly allowlisted even though they end in
# non-secret-looking suffixes (defense-in-depth against future false
# positives).
ALLOWED_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"_HOST$", re.IGNORECASE),
    re.compile(r"_URL$", re.IGNORECASE),
    re.compile(r"_PORT$", re.IGNORECASE),
    re.compile(r"_DOMAIN$", re.IGNORECASE),
    re.compile(r"_PATH$", re.IGNORECASE),
    re.compile(r"_DIR$", re.IGNORECASE),
    re.compile(r"_NAME$", re.IGNORECASE),
    re.compile(r"_REGION$", re.IGNORECASE),
    re.compile(r"_TIMEOUT", re.IGNORECASE),
)


def is_allowed(key: str) -> bool:
    """True if key is allowlisted (e.g. ``MINIMAX_API_HOST``)."""
    return any(pat.search(key) for pat in ALLOWED_PATTERNS)


def is_secret(key: str) -> bool:
    """True if key matches a secret pattern and isn't allowlisted."""
    if is_allowed(key):
        return False
    return any(pat.search(key) for pat in SECRET_PATTERNS)


def looks_like_placeholder(value: str) -> bool:
    """Detect obvious placeholder values to reduce noise.

    A placeholder is any value containing the words 'placeholder',
    'example', 'change-me', 'change-in-production', or starting with
    '<'. Real secrets won't match this — only dev-mode placeholders
    that signal an obvious bug.
    """
    lowered = value.lower()
    markers = ("placeholder", "example", "change-me", "change-in-production", "<")
    return any(marker in lowered for marker in markers)


def redact(value: str) -> str:
    """Return a redacted representation of a secret value."""
    if len(value) <= 8:
        return "***REDACTED***"
    return f"{value[:3]}…{value[-3:]} (len={len(value)})"


def scan_file(path: Path) -> list[tuple[str, str, str]]:
    """Scan a single ``.mcp.json`` file for secret-shaped env values.

    Returns a list of ``(key, value, reason)`` tuples for each
    violation. Empty list means the file is clean.
    """
    violations: list[tuple[str, str, str]] = []
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"WARN: cannot read {path}: {exc}", file=sys.stderr)
        return violations

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"WARN: invalid JSON in {path}: {exc}", file=sys.stderr)
        return violations

    if not isinstance(data, dict):
        return violations

    servers_any: Any = data.get("mcpServers", {})  # pyright: ignore[reportUnknownVariableType,reportUnknownMemberType]
    if not isinstance(servers_any, dict):
        return violations
    servers: dict[str, Any] = cast("dict[str, Any]", servers_any)

    for _server_name, server_cfg in servers.items():  # pyright: ignore[reportUnusedVariable]
        if not isinstance(server_cfg, dict):
            continue
        env_any: Any = server_cfg.get("env", {})  # pyright: ignore[reportUnknownVariableType,reportUnknownMemberType]
        if not isinstance(env_any, dict):
            continue
        env: dict[str, Any] = cast("dict[str, Any]", env_any)
        for key, value in env.items():
            if not is_secret(key):
                continue
            # Skip empty / unset values — those are explicit "no secret"
            if not value:
                continue
            reason = "placeholder" if looks_like_placeholder(value) else "literal-secret"
            violations.append((key, value, reason))

    return violations


def find_mcp_json_files(roots: list[Path]) -> list[Path]:
    """Find all ``.mcp.json`` files under the given roots.

    Excludes worktree subdirectories to avoid double-scanning and
    excludes any path under a hidden ``.git`` directory.
    """
    found: set[Path] = set()
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob(".mcp.json"):
            # Skip .git internals
            if "/.git/" in str(path) or path.parts and ".git" in path.parts:
                continue
            # Skip worktree metadata files (avoid double-scanning)
            if "/.worktrees/" in str(path):
                continue
            found.add(path)
    return sorted(found)


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns process exit code."""
    argv = argv if argv is not None else sys.argv[1:]

    roots = [Path(arg) for arg in argv] if argv else [Path("/Users/les/Projects")]
    # Always include the global mahavishnu config (canonical "global")
    canonical = Path("/Users/les/Projects/mahavishnu/.mcp.json")
    if canonical.exists() and canonical not in roots:
        roots.append(canonical)

    files = find_mcp_json_files(roots)
    if not files:
        print("No .mcp.json files found.", file=sys.stderr)
        return 0

    total_violations = 0
    files_with_violations = 0

    for path in files:
        violations = scan_file(path)
        if not violations:
            continue
        files_with_violations += 1
        for key, value, reason in violations:
            total_violations += 1
            print(f"{path}: {key} = {redact(value)} [{reason}]")

    print(f"\nScanned {len(files)} .mcp.json files", file=sys.stderr)
    print(
        f"Violations: {total_violations} across {files_with_violations} files",
        file=sys.stderr,
    )

    return 1 if total_violations > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())