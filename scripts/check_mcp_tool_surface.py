#!/usr/bin/env python3
"""Guard the Bodai fleet's MCP tool surface.

# Implements: REQ-MCPTD-007

Implements Phase 4 of ``docs/plans/2026-11-07-mcp-tool-disambiguation.md``.
The plan's own framing is the reason this exists: *the next duplicate
fails the build instead of waiting to be found.*

Four checks run over the fleet's ``tools/list`` responses:

1. **No empty description.** FastMCP publishes ``description: null`` when
   the registered function has no docstring, and MCP clients that
   require a description count those tools as invalid (qwen-code does
   exactly this — ``invalidToolCount: serverTools.filter(x => !x.name ||
   !x.description).length``). A tool with no description cannot be
   chosen by a model reading the tool list.
2. **No duplicate bare name across servers**, except the shared
   baseline set, which is asserted as an explicit allowlist.
3. **No registry drift.** Every name in mahavishnu's ``TOOL_VERSIONS``
   registry must be served by the server, and every served tool must be
   advertised in the registry. A phantom advertises a tool that does
   not exist; an unadvertised tool exists but is invisible to
   ``discover_tools``.
4. **One parameter signature per shared name**, with an allowlist for
   the intentional per-service differences.

Two modes:

- ``--live`` (default) probes each server over MCP HTTP.
- ``--fixture PATH`` analyses a checked-in snapshot instead, which is
  what CI uses when the servers are down.

A server that cannot be reached is *skipped* in live mode, not failed:
the fleet is often partially up, and a guard that reports a fleet
outage as a tool defect trains people to ignore it.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "mcp_surface" / "tools_list.json"

# The fleet's MCP endpoints. Keyed by the config entry name, which is
# also the prefix the Claude Code namespace uses.
SERVER_URLS: dict[str, str] = {
    "mahavishnu": "http://localhost:8680/mcp",
    "crackerjack": "http://localhost:8676/mcp",
    "session-buddy": "http://localhost:8678/mcp",
    "akosha": "http://localhost:8682/mcp",
    "oneiric": "http://localhost:8681/mcp",
}

# Per-request timeout, in seconds. Generous because these are local
# servers that stall under load — oneiric has been observed taking
# nine seconds to answer ``initialize`` while the machine is busy. A
# timeout that fires on a healthy-but-slow server would train people to
# ignore the guard.
REQUEST_TIMEOUT = 45

# The server whose tool surface the version registry describes.
# ``TOOL_VERSIONS`` is mahavishnu's own registry.
REGISTRY_OWNER = "mahavishnu"

# The shared baseline set. These names are deliberately served by more
# than one server, so a duplicate for them is not a finding. Anything
# outside this set that appears on two servers is.
SHARED_BASELINE_TOOLS = frozenset(
    {
        "discover_tools",
        "get_channel_sessions",
        "get_health",
        "get_liveness",
        "get_readiness",
        "health_check_all",
        "health_check_service",
        "pycharm_health",
        "query_local_traces",
        "track_channel_session",
        "wait_for_all_dependencies",
        "wait_for_dependency",
    }
)

# Shared names whose parameter signature legitimately differs per
# service. Each entry names the servers that differ and why.
#
# - ``discover_tools``: mahavishnu adds a ``capability`` gate.
# - ``get_channel_sessions``: mahavishnu filters by ``user_id``;
#   session-buddy by ``token``.
# - ``health_check_service``: mahavishnu names the argument
#   ``service_name``; the shared library names it ``service_name_arg``
#   and adds ``health_path``.
# - ``track_channel_session``: session-buddy adds ``event_id`` and
#   ``event_version``.
# - ``wait_for_dependency``: mahavishnu names the argument
#   ``service_name``; the shared library names it ``dep_service_name``
#   and adds ``health_path``.
SIGNATURE_EXCEPTIONS: dict[str, str] = {
    "discover_tools": "mahavishnu adds a capability gate",
    "get_channel_sessions": "mahavishnu filters by user_id, session-buddy by token",
    "health_check_service": "mahavishnu uses service_name, the shared library uses service_name_arg",
    "track_channel_session": "session-buddy adds event_id and event_version",
    "wait_for_dependency": "mahavishnu uses service_name, the shared library uses dep_service_name",
}


@dataclass
class ToolRecord:
    """One tool as advertised by one server."""

    name: str
    description: str | None
    signature: str
    server: str

    @property
    def has_description(self) -> bool:
        """True when the tool carries a usable description."""
        return bool((self.description or "").strip())


@dataclass
class Surface:
    """The analysed tool surface of a set of servers."""

    tools: dict[str, list[ToolRecord]] = field(
        default_factory=lambda: defaultdict(list)
    )
    unreachable: list[str] = field(default_factory=list)

    @property
    def served_names(self) -> set[str]:
        """Every tool name any reachable server serves."""
        return {record.name for records in self.tools.values() for record in records}


# ---------------------------------------------------------------------------
# Live probing
# ---------------------------------------------------------------------------


def _post(
    url: str, payload: dict[str, Any], session_id: str | None
) -> tuple[list[Any], str | None]:
    """POST a JSON-RPC message to an MCP HTTP endpoint.

    Returns the decoded responses and the session id, if the server
    issued one.
    """
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode(), method="POST"
    )
    request.add_header("Content-Type", "application/json")
    request.add_header("Accept", "application/json, text/event-stream")
    if session_id:
        request.add_header("mcp-session-id", session_id)
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
        issued = response.headers.get("mcp-session-id") or session_id
        body = response.read().decode()

    messages: list[Any] = []
    for line in body.splitlines():
        if line.startswith("data: "):
            messages.append(json.loads(line[6:]))
        elif line.strip().startswith("{"):
            messages.append(json.loads(line))
    return messages, issued


def fetch_tools(url: str) -> list[dict[str, Any]]:
    """Run the MCP handshake and return the server's ``tools/list``."""
    messages, session_id = _post(
        url,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "check-mcp-tool-surface", "version": "1"},
            },
        },
        None,
    )
    if not any("result" in message for message in messages):
        raise RuntimeError(f"{url}: initialize returned no result")

    notify = urllib.request.Request(
        url,
        data=json.dumps(
            {"jsonrpc": "2.0", "method": "notifications/initialized"}
        ).encode(),
        method="POST",
    )
    notify.add_header("Content-Type", "application/json")
    notify.add_header("Accept", "application/json, text/event-stream")
    if session_id:
        notify.add_header("mcp-session-id", session_id)
    try:
        urllib.request.urlopen(notify, timeout=REQUEST_TIMEOUT).read()
    except urllib.error.URLError, OSError:
        # The notification is a courtesy; a server that rejects it still
        # serves tools.
        pass

    messages, _ = _post(
        url,
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        session_id,
    )
    for message in messages:
        if "result" in message and "tools" in message["result"]:
            return message["result"]["tools"]
    raise RuntimeError(f"{url}: tools/list returned no tools array")


def probe_live(urls: dict[str, str]) -> Surface:
    """Probe every server, skipping the ones that cannot be reached."""
    surface = Surface()
    for server, url in urls.items():
        try:
            raw_tools = fetch_tools(url)
        except (urllib.error.URLError, OSError, RuntimeError, TimeoutError) as error:
            surface.unreachable.append(f"{server} ({error})")
            continue
        for tool in raw_tools:
            surface.tools[server].append(
                ToolRecord(
                    name=tool.get("name") or "",
                    description=tool.get("description"),
                    signature=signature_of(tool.get("inputSchema") or {}),
                    server=server,
                )
            )
    return surface


# ---------------------------------------------------------------------------
# Fixture mode
# ---------------------------------------------------------------------------


def load_fixture(path: Path) -> Surface:
    """Analyse a checked-in snapshot of the fleet's tools/list."""
    return load_fixture_from_payload(json.loads(path.read_text(encoding="utf-8")))


def load_fixture_from_payload(payload: dict[str, Any]) -> Surface:
    """Analyse a snapshot already parsed into a dict."""
    surface = Surface()
    for server, entry in payload.get("servers", {}).items():
        for tool in entry.get("tools", []):
            surface.tools[server].append(
                ToolRecord(
                    name=tool.get("name") or "",
                    description=tool.get("description"),
                    signature=tool.get("signature") or "",
                    server=server,
                )
            )
    return surface


def signature_of(schema: dict[str, Any]) -> str:
    """A stable signature for a tool's input schema.

    Two tools with the same signature accept the same arguments, so a
    caller can swap one for the other.
    """
    properties = schema.get("properties") or {}
    required = set(schema.get("required") or [])
    parts = sorted(
        f"{name}:{json.dumps(prop.get('type'), sort_keys=True)}{'*' if name in required else ''}"
        for name, prop in properties.items()
    )
    return "|".join(parts)


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


def check_descriptions(surface: Surface) -> list[str]:
    """Every served tool must carry a non-empty description."""
    findings = []
    for server in sorted(surface.tools):
        for record in surface.tools[server]:
            if not record.has_description:
                findings.append(
                    f"{server}: {record.name} has no description. FastMCP derives the "
                    "description from the function docstring, so the registered "
                    "function needs one."
                )
    return findings


def check_duplicates(surface: Surface) -> list[str]:
    """No name may be served by two servers outside the shared allowlist."""
    owners: dict[str, list[str]] = defaultdict(list)
    for server in sorted(surface.tools):
        for record in surface.tools[server]:
            owners[record.name].append(server)

    findings = []
    for name, servers in sorted(owners.items()):
        if len(servers) < 2 or name in SHARED_BASELINE_TOOLS:
            continue
        findings.append(
            f"{name} is served by {servers}. Component-prefixed names must be "
            "unique across the fleet; only the shared baseline set may repeat."
        )
    return findings


def check_registry(surface: Surface) -> list[str]:
    """The version registry must match the tools its own server serves.

    ``TOOL_VERSIONS`` is mahavishnu's registry, so it is compared with
    mahavishnu's surface. Comparing it with the fleet would report every
    other server's tools as unadvertised, which says nothing about this
    registry.
    """
    try:
        sys.path.insert(0, str(REPO_ROOT))
        from mahavishnu.mcp.tool_versions import TOOL_VERSIONS
    except ImportError as error:
        return [f"could not import the tool version registry: {error}"]

    served = {record.name for record in surface.tools.get(REGISTRY_OWNER, [])}
    if not served:
        return [
            (
                f"the {REGISTRY_OWNER} server served no tools, so the registry "
                "cannot be checked against it"
            )
        ]
    registered = set(TOOL_VERSIONS)

    findings = []
    for name in sorted(registered - served):
        findings.append(
            f"{name} is advertised by get_tool_versions but {REGISTRY_OWNER} "
            "does not serve it. A phantom entry sends callers looking for a "
            "tool that does not exist."
        )
    for name in sorted(served - registered):
        findings.append(
            f"{name} is served by {REGISTRY_OWNER} but missing from "
            "get_tool_versions, so discover_tools cannot find it."
        )
    return findings


def check_signatures(surface: Surface) -> list[str]:
    """A shared name must accept the same arguments on every server."""
    by_name: dict[str, list[ToolRecord]] = defaultdict(list)
    for server in sorted(surface.tools):
        for record in surface.tools[server]:
            by_name[record.name].append(record)

    findings = []
    for name, records in sorted(by_name.items()):
        if len(records) < 2 or name in SIGNATURE_EXCEPTIONS:
            continue
        signatures = {record.signature for record in records}
        if len(signatures) > 1:
            grouped: dict[str, list[str]] = defaultdict(list)
            for record in records:
                grouped[record.signature].append(record.server)
            detail = "; ".join(
                f"{sorted(servers)} -> {signature}"
                for signature, servers in sorted(grouped.items())
            )
            findings.append(
                f"{name} has different parameter signatures per server: {detail}"
            )
    return findings


CHECKS = (
    ("empty description", check_descriptions),
    ("duplicate tool name", check_duplicates),
    ("version registry drift", check_registry),
    ("parameter signature drift", check_signatures),
)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def analyse(surface: Surface) -> dict[str, list[str]]:
    """Run every check and return the findings per check."""
    return {label: check(surface) for label, check in CHECKS}


def capture(urls: dict[str, str], path: Path) -> int:
    """Write a snapshot of the live fleet to ``path``.

    The snapshot is what CI analyses when the servers are down, so it
    has to be regenerated whenever the fleet's surface changes.
    """
    surface = probe_live(urls)
    if surface.unreachable:
        for unreachable in surface.unreachable:
            print(f"  skipped (unreachable): {unreachable}")
        print(
            "Refusing to write a snapshot with missing servers — the result "
            "would look like those servers publish no tools.",
            file=sys.stderr,
        )
        return 2

    payload = {
        "servers": {
            server: {
                "url": url,
                "tools": [
                    {
                        "name": record.name,
                        "description": record.description,
                        "signature": record.signature,
                    }
                    for record in sorted(records, key=lambda item: item.name)
                ],
            }
            for server, url in urls.items()
            for records in [surface.tools.get(server, [])]
        }
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"Wrote {path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run the guard and return a process exit code."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--live",
        action="store_true",
        help="probe the running servers (default)",
    )
    mode.add_argument(
        "--fixture",
        type=Path,
        help=f"analyse a checked-in snapshot instead of probing (default: {DEFAULT_FIXTURE})",
    )
    mode.add_argument(
        "--capture",
        type=Path,
        metavar="PATH",
        help="write a snapshot of the live fleet to PATH and exit",
    )
    args = parser.parse_args(argv)

    if args.capture is not None:
        return capture(SERVER_URLS, args.capture)

    if args.fixture is not None:
        fixture = args.fixture
        if not fixture.is_file():
            print(f"fixture not found: {fixture}", file=sys.stderr)
            return 2
        surface = load_fixture(fixture)
        print(f"Analysing the checked-in snapshot at {fixture}")
    else:
        surface = probe_live(SERVER_URLS)
        print("Analysing the live fleet")
        for unreachable in surface.unreachable:
            print(f"  skipped (unreachable): {unreachable}")

    findings = analyse(surface)
    total = sum(len(items) for items in findings.values())

    print()
    print(f"Servers analysed: {len(surface.tools)}")
    print(f"Distinct tool names: {len(surface.served_names)}")
    print()

    for label, items in findings.items():
        if not items:
            print(f"  ok    {label}")
            continue
        print(f"  FAIL  {label} ({len(items)})")
        for item in items:
            print(f"          {item}")

    print()
    if total:
        print(f"{total} violation(s) found.")
        return 1
    print("No violations.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
