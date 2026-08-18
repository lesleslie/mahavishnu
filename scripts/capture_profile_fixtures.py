"""Capture golden fixtures for each tool profile.

Used by Task 2 (W1.1: Backfill mahavishnu) to capture the current
output of each profile BEFORE the refactor to apply_tool_profile().
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path


async def capture(profile: str, output_path: Path) -> None:
    """Capture the tool list for the given profile to output_path."""
    os.environ["MAHAVISHNU_TOOL_PROFILE"] = profile

    from mahavishnu.mcp.bootstrap import register_profile_tools
    from mahavishnu.mcp.server_core import FastMCPServer
    from mahavishnu.mcp.tools.profiles import PROFILE_REGISTRATIONS, get_active_profile

    server = FastMCPServer()
    resolved = get_active_profile()
    methods_set = set(PROFILE_REGISTRATIONS[resolved])
    await register_profile_tools(server, methods_set)
    tools = await server.server.list_tools()
    names = sorted(t.name for t in tools)
    output_path.write_text(json.dumps(names, indent=2) + "\n")
    print(f"profile={profile} count={len(names)} path={output_path}")


async def main() -> None:
    fixtures_dir = Path("tests/fixtures")
    fixtures_dir.mkdir(parents=True, exist_ok=True)
    for profile in ("minimal", "standard", "full"):
        await capture(profile, fixtures_dir / profile / "tool_names.json")


if __name__ == "__main__":
    asyncio.run(main())
