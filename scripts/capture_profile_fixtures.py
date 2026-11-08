"""Capture golden fixtures for each tool profile.

Uses the production ``build_mahavishnu_mcp_server()`` entry point so the
captured fixtures match what ``test_wiring.py`` sees at runtime. The
previous capture path went through ``register_profile_tools`` directly,
which undercounts tools because it bypasses the mcp-common
``apply_tool_profile`` helper that adds the always-on groups (health,
lifecycle, ecosystem, etc.).
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

    from mahavishnu.mcp.server import build_mahavishnu_mcp_server

    server = await build_mahavishnu_mcp_server()
    tools = await server.server.list_tools()
    names = sorted(t.name for t in tools)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(names, indent=2) + "\n")
    print(f"profile={profile} count={len(names)} path={output_path}")


async def capture_production(output_path: Path) -> None:
    """Capture the tool list a client of the *running* server actually sees.

    The running server registers its profile groups through the legacy
    dispatcher in ``mahavishnu/mcp/bootstrap.py::register_profile_tools``,
    not the canonical W0 helper this script otherwise uses. The two
    surfaces are not identical — the legacy dispatcher does not dispatch
    every group in ``REGISTRATION_MAP`` — so each gets its own fixture:

    - ``full/`` — the canonical surface (``build_mahavishnu_mcp_server``)
    - ``full_production/`` — what the running server exposes

    README.md and CLAUDE.md quote the production surface, because that is
    what a user of the server can call.
    """
    os.environ["MAHAVISHNU_TOOL_PROFILE"] = "full"

    from mahavishnu.mcp.bootstrap import register_profile_tools
    from mahavishnu.mcp.server_core import FastMCPServer
    from mahavishnu.mcp.tools.profiles import FULL_REGISTRATIONS

    server = FastMCPServer()
    await register_profile_tools(server, set(FULL_REGISTRATIONS))
    names = sorted(t.name for t in await server.server.list_tools())
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(names, indent=2) + "\n")
    print(f"profile=full (production) count={len(names)} path={output_path}")


async def main() -> None:
    fixtures_dir = Path("tests/fixtures")
    fixtures_dir.mkdir(parents=True, exist_ok=True)
    for profile in ("minimal", "standard", "full"):
        await capture(profile, fixtures_dir / profile / "tool_names.json")
    await capture_production(fixtures_dir / "full_production" / "tool_names.json")


if __name__ == "__main__":
    asyncio.run(main())
