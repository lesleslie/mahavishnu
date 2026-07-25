#!/usr/bin/env python3
"""Launch wrapper: sources ~/.config/secrets.env into os.environ, then exec's
the Mahavishnu MCP server.

Why this exists:
    launchd-managed processes don't inherit shell init files (no .zshrc / .zshenv
    sourcing), so the consolidated secrets file must be read explicitly. This
    wrapper bridges that gap by parsing secrets.env and merging its values
    into os.environ before exec'ing the MCP server.

Source format (one per line, comments allowed with leading `#`):
    export KEY='value'
    export KEY="value"
    export KEY=value  # no quotes, simple unquoted value
    KEY='value'       # bare assignment also accepted

Key names are upper-cased to match the env-var convention expected by
downstream consumers (e.g. Agno adapter's _get_api_key("MINIMAX_API_KEY")).
"""

from __future__ import annotations

import os
import re
from pathlib import Path
import sys

SECRETS_ENV = Path.home() / ".config" / "secrets.env"
MCP_PROGRAM = "/Users/les/Projects/mahavishnu/.venv/bin/python"
MCP_ARGS = ("-m", "mahavishnu", "mcp", "start")

# Matches: optional `export `, KEY, =, then a quoted or unquoted value.
# Captures: (1) key, (2) quote char or empty, (3) value
_LINE_RE = re.compile(
    r"""^\s*(?:export\s+)?([A-Z0-9_]+)\s*=\s*(['"]?)(.*?)\2\s*$"""
)


def _strip_comment(value: str) -> str:
    """Strip an inline `# comment` from a value, but not from inside quotes.

    We assume the regex already removed the surrounding quotes, so a `#` here
    is only safe to strip if it doesn't appear before an unescaped quote
    (we never have one at this point). For secrets.env values that contain
    `#` (e.g. JWTs with `#` in the header), the quotes in the source file
    protect them — so this only fires for unquoted values.
    """
    idx = value.find(" #")
    return value if idx < 0 else value[:idx].rstrip()


def load_secrets() -> dict[str, str]:
    """Parse ~/.config/secrets.env into a {KEY: value} dict.

    Returns upper-cased keys so they can be merged into os.environ unchanged.
    Returns {} if the file is missing or unreadable.
    """
    if not SECRETS_ENV.exists():
        return {}
    result: dict[str, str] = {}
    try:
        with SECRETS_ENV.open() as f:
            for raw in f:
                line = raw.rstrip("\n")
                # Skip blank lines and full-line comments
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                m = _LINE_RE.match(line)
                if not m:
                    continue
                key, _quote, value = m.group(1), m.group(2), m.group(3)
                result[key.upper()] = _strip_comment(value)
    except OSError:
        return {}
    return result


def main() -> int:
    secrets = load_secrets()
    for key, value in secrets.items():
        os.environ.setdefault(key, value)

    # exec replaces the Python process — same PID, just transitioned to the MCP server.
    # This means launchd sees a single process and doesn't lose supervision.
    os.execvp(MCP_PROGRAM, (MCP_PROGRAM, *MCP_ARGS))
    return 1  # unreachable


if __name__ == "__main__":
    sys.exit(main())
