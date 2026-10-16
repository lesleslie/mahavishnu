#!/usr/bin/env python3
"""SessionStart hook: mirror Bodai specialist agents to ~/.claude/agents/.

Background: each Bodai server (akosha, mahavishnu, crackerjack) publishes
specialist agents via list_agents + get_agent (Phase 3, commit f3eadda7
for crackerjack). The local Claude Code picker reads ~/.claude/agents/
— so an agent that exists server-side but has no local stub is invisible
to the picker. The LLM probes for "crackerjack-specialist" etc. and
finds nothing. This hook closes that gap.

At SessionStart it fans out to each Bodai server's list_agents; for any
agent whose ~/.claude/agents/<name>.md is absent, writes a minimal
9-line YAML stub (body stays server-side and is fetched via
mcp__<server>__<server>_get_agent on demand).

Wire protocol notes (FastMCP streamable-HTTP transport):

1. Every session must start with an `initialize` JSON-RPC call. The
   server responds with an `mcp-session-id` header. ALL subsequent
   calls on that logical session must include that header — otherwise
   the server returns HTTP 400 "Missing session ID". This bit the
   existing mahavishnu-pool-bootstrap.py hook silently; this hook
   handles it explicitly.
2. Successful tool calls return chunked `text/event-stream` bodies,
   not plain JSON. Each SSE event is `event: message\\ndata: {json}\\n\\n`
   — the parser below strips the `data:` prefix and decodes the
   embedded JSON. Error responses are plain JSON, so we try both.
3. FastMCP's `wrap_result: true` (default) wraps the tool's return
   value in `{"result": <value>}`. `_extract_agents` checks for that
   key, plus `agents`/`results`/`items` for tools that return a
   dict directly.

Mirrors the pattern of mahavishnu-pool-bootstrap.py: best-effort
federation, broad except → exit 0 so SessionStart never blocks.
Per-server soft-fail at three layers: initialize, call, write.

Scope: per-repo (registered in this project's .claude/settings.json).
For user-global coverage, mirror the script to ~/.claude/hooks/ and add
the same entry to ~/.claude/settings.json — file is portable as-is.
"""
from __future__ import annotations

import json
import os
import re
import sys
from urllib.parse import urlparse

import httpx

# Wire-protocol helpers (initialize handshake, SSE parsing, tools/call)
# live in a sibling module so the same fix applies to every Bodai hook
# that talks FastMCP streamable-HTTP. See _bodai_mcp_client.py docstring
# for the wire shape and the session-handshake rationale.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _bodai_mcp_client import call_tool, init_session  # noqa: E402

EVENT_NAME = "SessionStart"
REQUEST_TIMEOUT_SECONDS = 1.0
USER_AGENTS_DIR = os.path.expanduser("~/.claude/agents")

# Agent name validation: lowercase letter, then 2-63 chars of
# [a-z0-9_-]. Matches the slug convention used by
# Bodai server registry entries. Anything outside this
# pattern is rejected — agent names flow into FILE NAMES on
# disk, so a too-broad regex becomes a path-traversal
# primitive (e.g. ``../../../etc/passwd``) or a YAML
# structural corruption primitive.
_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{2,63}$")

# URL allowlist for the env-var override. Only the default
# loopback URLs and the documented Bodai server hostnames are
# trusted; anything else falls back to the default. This is a
# defense-in-depth SSRF guard — the env var is set by the
# user's shell, so a malicious process could redirect the
# hook to an attacker-controlled server. Restricting to the
# known Bodai hostnames (or loopback) limits the blast radius.
_ALLOWED_URL_HOSTS: frozenset[str] = frozenset(
    {
        "localhost",
        "127.0.0.1",
        "::1",
        # Documented Bodai server hostnames. Add new servers
        # here, not in code scattered elsewhere.
        "akosha.local",
        "mahavishnu.local",
        "crackerjack.local",
    }
)


def _validate_url(url: str) -> str | None:
    """Return ``url`` iff its scheme is http(s) AND its host is
    loopback or in ``_ALLOWED_URL_HOSTS``. Otherwise None — the
    caller falls back to the default URL.
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https"):
        return None
    host = (parsed.hostname or "").lower()
    if host not in _ALLOWED_URL_HOSTS:
        return None
    return url


# (server_key, default_mcp_url, tool_name)
SERVERS: list[tuple[str, str, str]] = [
    ("akosha", "http://localhost:8682/mcp", "list_agents"),
    ("mahavishnu", "http://localhost:8680/mcp", "mahavishnu_list_agents"),
    ("crackerjack", "http://localhost:8676/mcp", "crackerjack_list_agents"),
    # Phase 4 §11 federation: extend the agent mirror to every Bodai
    # server that exposes list_agents via the Phase 3 factory in
    # mcp_common.agents_tools. session-buddy uses the underscore
    # server_key (``session_buddy_`` prefix on tool names).
    # oneiric synthesizes its catalog at module load from
    # oneiric/adapters/<domain>/ so the mirror picks up 17 entries
    # (1 cross-domain + 16 per-domain specialists).
    ("session-buddy", "http://localhost:8678/mcp", "session_buddy_list_agents"),
    ("oneiric", "http://localhost:8684/mcp", "oneiric_list_agents"),
]


def _yaml_single_quote(s: str) -> str:
    """YAML single-quoted string: double every internal single quote.

    Single-quoted YAML strings (``'foo'``) interpret ONLY the
    ``''`` escape — no other backslash sequences. That makes
    this the safest quote style for values that come from an
    untrusted source (a network response). Newlines inside the
    value are preserved verbatim (the value collapses to a
    single space in YAML's folded style, which is what the
    description field wants).
    """
    return "'" + s.replace("'", "''") + "'"


def _safe_parse_payload() -> dict[str, object]:
    """Parse stdin JSON; return empty dict on any parse failure."""
    try:
        raw = sys.stdin.read()
    except Exception:  # hook handler — broad catch is the documented contract  # noqa: BLE001
        return {}
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _stub_for_agent(agent: object) -> str:
    """Render the YAML-only stub matching the existing ~/.claude/agents/*.md convention.

    Convention (verified against akosha/mahavishnu/oneiric stubs):
    YAML frontmatter only — name, description (>-, folded), model.
    No body, since the canonical body lives at <server>/mcp/agents/<name>.md
    and is fetched by mcp__<server>__<server>_get_agent on demand.

    All three fields are SINGLE-QUOTED YAML strings via
    :func:`_yaml_single_quote` to prevent YAML-injection from a
    malicious or env-redirected server. The agent ``name`` is
    additionally validated against ``_NAME_PATTERN`` (slug
    convention) and rejected on mismatch — it flows into the
    FILE NAME on disk, so a too-broad regex would become a
    path-traversal / structural-corruption primitive.
    """
    if not isinstance(agent, dict):
        return ""
    raw_name = agent.get("name")
    if not isinstance(raw_name, str) or not _NAME_PATTERN.match(raw_name.strip()):
        return ""
    name = raw_name.strip()
    description = str(agent.get("description") or "").strip()
    model = str(agent.get("model") or "sonnet").strip()
    # Model name goes through the same slug guard as the agent
    # name — anything not matching the slug pattern is replaced
    # with the safe default. Real Bodai server responses use
    # well-known model IDs (claude-sonnet-4-6, minimax-m3, etc.)
    # that match the pattern.
    if not _NAME_PATTERN.match(model):
        model = "sonnet"

    body = [
        "---",
        f"name: {_yaml_single_quote(name)}",
        f"description: {_yaml_single_quote(description)}",
        f"model: {_yaml_single_quote(model)}",
        "---",
        "",
    ]
    return "\n".join(body)


def _materialize(agents: list[object]) -> tuple[int, list[str]]:
    """Write stubs for agents whose ~/.claude/agents/<name>.md is absent.

    Returns (count_written, names_written). Idempotent: existing files
    are never overwritten. Per-write soft-fail: any OSError is logged
    and the agent is silently skipped.
    """
    written = 0
    names: list[str] = []
    for agent in agents:
        if not isinstance(agent, dict):
            continue
        raw_name = agent.get("name")
        if not isinstance(raw_name, str):
            continue
        # Re-validate the name pattern at the materialization
        # site too — defense in depth against a future change to
        # ``_stub_for_agent`` that loosens the guard.
        if not _NAME_PATTERN.match(raw_name.strip()):
            continue
        name = raw_name.strip()
        target = os.path.join(USER_AGENTS_DIR, f"{name}.md")
        if os.path.exists(target):
            continue
        stub = _stub_for_agent(agent)
        if not stub:
            continue
        try:
            os.makedirs(USER_AGENTS_DIR, exist_ok=True)
            with open(target, "w", encoding="utf-8") as fh:
                fh.write(stub)
        except Exception as exc:  # hook handler — broad catch is the documented contract  # noqa: BLE001
            sys.stderr.write(
                f"Hook output: bodai-agent-mirror write failed for {name}: {exc!r}\n"
            )
            sys.stderr.flush()
            continue
        written += 1
        names.append(name)
    return written, names


def _extract_agents(result: object) -> list[object] | None:
    """Pull the agents list out of either an array or wrapped-dict shape.

    FastMCP's ``wrap_result: true`` puts the tool's return value inside
    ``{"result": <value>}``. Some tools return ``{"agents": [...]}`` or
    ``{"data": [...]}`` directly. Handles all three.
    """
    if isinstance(result, list):
        return result
    if isinstance(result, dict):
        # Common wrapped shapes, in priority order.
        for key in ("result", "agents", "results", "items"):
            value = result.get(key)
            if isinstance(value, list):
                return value
        # Defensive: first list-valued key whose first element is a dict.
        for value in result.values():
            if isinstance(value, list) and value and isinstance(value[0], dict):
                return value
    return None


def _fetch_server_agents(client: httpx.Client, url: str, tool_name: str) -> tuple[list[object] | None, str | None]:
    """Per-server full lifecycle: initialize → tools/call → return agents.

    Returns (agents, error). On success: (list, None). On failure:
    (None, "<reason>"). Either way, never raises — all exceptions are
    caught and surfaced as error strings for the summary.
    """
    session_id = init_session(client, url)
    if session_id is None:
        return None, "initialize failed"
    result = call_tool(client, url, tool_name, session_id, {})
    if result is None:
        return None, "call failed"
    agents = _extract_agents(result)
    if agents is None:
        return None, "unexpected payload shape"
    return agents, None


def main() -> int:
    """SessionStart entry point. Always returns 0."""
    payload = _safe_parse_payload()
    summary_parts: list[str] = []
    total_written = 0
    total_seen = 0
    failures: list[str] = []

    for server_key, default_url, tool_name in SERVERS:
        env_url = os.environ.get(f"{server_key.upper()}_MCP_URL")
        # ``_validate_url`` returns the env-var URL iff its host
        # is loopback or in the Bodai allowlist; otherwise None
        # — the caller falls back to the default. This is the
        # SSRF guard: a malicious or misconfigured env var
        # cannot redirect the hook to an attacker-controlled
        # server.
        url = _validate_url(env_url) if env_url else None
        if url is None:
            url = default_url
        try:
            with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS) as client:
                agents, error = _fetch_server_agents(client, url, tool_name)
        except Exception as exc:  # hook handler — broad catch is the documented contract  # noqa: BLE001
            failures.append(f"{server_key}: lifecycle raised {exc!r}")
            continue
        if agents is None:
            failures.append(f"{server_key}: {error}")
            continue
        total_seen += len(agents)
        written, names = _materialize(agents)
        total_written += written
        if written:
            summary_parts.append(f"{server_key}: wrote {written} ({', '.join(names)})")
        else:
            summary_parts.append(f"{server_key}: {len(agents)} catalog, 0 added")

    if failures:
        sys.stderr.write(
            "Hook output: bodai-agent-mirror partial failures: " + "; ".join(failures) + "\n"
        )
        sys.stderr.flush()

    if total_written:
        ctx = f"Bodai agent mirror: wrote {total_written} new stub(s) — " + "; ".join(summary_parts) + "."
    elif failures and total_seen == 0:
        ctx = "Bodai agent mirror: all Bodai servers unreachable; session proceeds in degraded mode."
    else:
        ctx = f"Bodai agent mirror: {total_seen} catalog agent(s), all already present, 0 added."

    output = {
        "hookSpecificOutput": {
            "hookEventName": EVENT_NAME,
            "additionalContext": ctx,
        }
    }
    try:
        print(json.dumps(output))
    except Exception as exc:  # hook handler — broad catch is the documented contract  # noqa: BLE001
        sys.stderr.write(f"Hook output: json.dumps failed: {exc!r}\n")
        sys.stderr.flush()

    # Bridge audit would go here, mirroring mahavishnu-pool-bootstrap.py.
    # Skipped for v1; add handle() call when the bridge accepts this
    # event type without raising.
    del payload  # consumed only for the eventual bridge call.

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # hook handler — broad catch is the documented contract  # noqa: BLE001
        sys.stderr.write("Hook output: bodai-agent-mirror unhandled error\n")
        sys.stderr.flush()
        sys.exit(0)