#!/usr/bin/env python3
"""Launch wrapper: reads ~/.config/oneiric/local.yaml `secrets:` block into os.environ,
then exec's the Mahavishnu MCP server.

Why this exists:
    launchd-managed processes don't inherit shell init files (no .zshrc sourcing)
    AND user secrets have been migrated out of .zshrc into Oneiric's XDG-local YAML
    (see ~/.zshrc line 213: "OPENAI_API_KEY, MINIMAX_API_KEY, POSTMAN_API_KEY
    moved to ~/.config/oneiric/local.yaml (2026-06-23)").
    This wrapper bridges that gap.

The wrapper reads secrets with key names normalized to upper-case (matching the
env-var convention expected by the Agno adapter's _get_api_key("MINIMAX_API_KEY")
and similar downstream consumers).
"""

from __future__ import annotations

import os
from pathlib import Path
import sys

ONIRIC_LOCAL_YAML = Path.home() / ".config" / "oneiric" / "local.yaml"
MCP_PROGRAM = "/Users/les/Projects/mahavishnu/.venv/bin/python"
MCP_ARGS = ("-m", "mahavishnu", "mcp", "start")


def load_secrets() -> dict[str, str]:
    """Load secret env vars from Oneiric XDG-local YAML.

    Schema (one level of grouping under `secrets:`, currently `inline:`):
        secrets:
          inline:
            MINIMAX_API_KEY: <value>
            OPENAI_API_KEY: <value>
            ...

    The `inline` group is intended for env vars that go directly into process
    env. Returns upper-cased keys so they can be merged into os.environ.

    Falls back to flat `secrets: {KEY: ...}` if no `inline:` subgroup exists,
    so older / simpler configs keep working.
    """
    if not ONIRIC_LOCAL_YAML.exists():
        return {}
    try:
        import yaml
    except ImportError:
        return {}

    with ONIRIC_LOCAL_YAML.open() as f:
        data = yaml.safe_load(f) or {}

    secrets = data.get("secrets")
    if not isinstance(secrets, dict):
        return {}

    # Prefer `secrets.inline:` subgroup; fall back to flat `secrets:` mapping
    source = secrets.get("inline", secrets) if isinstance(secrets.get("inline"), dict) else secrets
    return {str(k).upper(): str(v) for k, v in source.items()}


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
