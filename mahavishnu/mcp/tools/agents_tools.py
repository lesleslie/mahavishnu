"""Phase 3 server-published agents tools (Phase 3 of bodai-skill-agent-distribution).

Exposes the ``mcp__mahavishnu__mahavishnu_list_agents`` and
``mcp__mahavishnu__mahavishnu_get_agent`` tools that advertise the
server-defined agents to the Phase 3 installer and the Claude Code
picker. Agents live as markdown bodies under
``mahavishnu/mcp/agents/<name>.md``.

This module is a thin server-specific wrapper around
:func:`mcp_common.agents_tools.build_register_agents_tools`. The
factory owns the mechanism — the B-4 allowlist, B-6 body
normalization + content-hash, the wire shape, the success/error
envelope, and the tool registration plumbing. Mahavishnu owns the
policy: the catalog, where bodies live, the tool name prefix
(``"mahavishnu_"``), how the signer is acquired (lifespan via
``signer_feed.get_signer_feed_state()``), and the signing function
(canonicalization via mahavishnu's local
``canonical_payload_for_signing``).

Security gates (per plan §11):

- **B-1** — every ``get_agent`` response carries an ed25519 signature
  over the canonicalized metadata. The Phase 3 installer verifies
  this before any write to ``~/.claude/agents/mahavishnu-<name>.md``.
- **B-4** — the path-traversal allowlist
  ``^[a-z0-9][a-z0-9._-]{0,62}$`` lives in
  ``mcp_common.canonical_schemas._validators.NAME_OR_SERVER_RE``;
  the factory enforces it at the API boundary. The per-server
  regex copy that used to live here is gone.
- **B-6** — ``get_agent`` returns ``body == system_prompt``. The
  factory computes ``content_hash`` from the stripped body and
  the schema's body-integrity model_validator asserts the hash
  matches the system_prompt bytes.
- **B-7** — each successful tool call invokes ``on_call``, which
  bumps ``SignerFeedState.cycles_total`` via
  :meth:`record_cycle` so the four mandatory feed signals stay
  accurate.

Non-goals:

- Body content is loaded at request time (L-6). No session-start
  pre-load.
- The 3 starter agents ship as static markdown files in
  ``mahavishnu/mcp/agents/``; Phase 4's federation layer
  (``mcp__akosha__list_ecosystem_agents``) is what exposes them
  alongside the other 4 servers' catalogs.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from mcp_common.agents_tools import build_register_agents_tools
from mcp_common.canonical_schemas.agent import AgentCanonicalSchema

if TYPE_CHECKING:
    from fastmcp import FastMCP

logger = logging.getLogger(__name__)


# Catalog lives one level up from this module so the agents dir
# matches the project layout (other Bodai components also keep
# their agents under ``<package>/agents/``). New agents are added
# by dropping a new ``.md`` file under ``agents/`` AND adding an
# entry to ``_STATIC_AGENTS``.
_CATALOG_DIR = Path(__file__).parent.parent / "agents"


# Phase 3: 3 starter agents with real content. Each dict is the body's
# filename (relative to ``agents/``), the semantic version, the
# agent's picker description, the Claude Code model, the list of
# exact tool names the agent may invoke, and the optional governance
# metadata.
#
# Adding a new server-published agent: drop ``<name>.md`` under
# ``agents/`` AND add an entry below. The factory's catalog
# validation runs at module load — a missing file or duplicate name
# fails fast.
_STATIC_AGENTS: list[dict[str, Any]] = [
    {
        "name": "mahavishnu-specialist",
        "body_filename": "mahavishnu-specialist.md",
        "version": "1.0.0",
        "title": "Mahavishnu Orchestration Specialist",
        "description": (
            "Use when the user explicitly asks for Mahavishnu-specific "
            "orchestration guidance — pool routing, workflow triggers, "
            "or cross-repo dispatch — and the picker has surfaced this "
            "agent. Do not auto-trigger. Drives pool_route_execute / "
            "trigger_workflow / dispatch_to_pool with the least_loaded "
            "selector and surfaces degraded-pool fallbacks to the user "
            "before dispatching."
        ),
        "model": "sonnet",
        "tools": [
            "mcp__mahavishnu__pool_route_execute",
            "mcp__mahavishnu__pool_health",
            "mcp__mahavishnu__trigger_workflow",
            "mcp__mahavishnu__list_workflows",
            "mcp__mahavishnu__get_workflow_status",
            "mcp__mahavishnu__dispatch_to_pool",
        ],
        "tool_refs": [
            "mcp__mahavishnu__pool_route_execute",
            "mcp__mahavishnu__pool_health",
            "mcp__mahavishnu__trigger_workflow",
            "mcp__mahavishnu__dispatch_to_pool",
        ],
        "dependencies": ["pool-router-agent", "workflow-monitor"],
        "category": "orchestration",
        "owner": "mahavishnu",
        "status": "active",
        "scope": "user-global",
    },
    {
        "name": "pool-router-agent",
        "body_filename": "pool-router-agent.md",
        "version": "1.0.0",
        "title": "Mahavishnu Pool Router Strategist",
        "description": (
            "Use when the user asks for pool-selector advice — which "
            "selector (least_loaded, round_robin, random, affinity) is "
            "right for the current workload. Do not auto-trigger. Reads "
            "pool_health, weights against the workload shape, and "
            "recommends a selector with the tradeoffs spelled out "
            "before any dispatch."
        ),
        "model": "sonnet",
        "tools": [
            "mcp__mahavishnu__pool_health",
            "mcp__mahavishnu__pool_list",
        ],
        "tool_refs": [
            "mcp__mahavishnu__pool_health",
            "mcp__mahavishnu__pool_list",
        ],
        "dependencies": [],
        "category": "orchestration",
        "owner": "mahavishnu",
        "status": "active",
        "scope": "user-global",
    },
    {
        "name": "workflow-monitor",
        "body_filename": "workflow-monitor.md",
        "version": "1.0.0",
        "title": "Mahavishnu Workflow Status Reviewer",
        "description": (
            "Use when the user asks for the status of a Mahavishnu-"
            "launched durable workflow or wants to interpret a "
            "workflow_id. Do not auto-trigger. Polls "
            "get_workflow_status, distinguishes Prefect flows from "
            "Agno agent loops and LlamaIndex RAG pipelines, and "
            "surfaces a partial-status flag when the workflow is "
            "mid-stage."
        ),
        "model": "sonnet",
        "tools": [
            "mcp__mahavishnu__get_workflow_status",
            "mcp__mahavishnu__list_workflows",
            "mcp__mahavishnu__cancel_workflow",
        ],
        "tool_refs": [
            "mcp__mahavishnu__get_workflow_status",
            "mcp__mahavishnu__list_workflows",
        ],
        "dependencies": [],
        "category": "orchestration",
        "owner": "mahavishnu",
        "status": "active",
        "scope": "user-global",
    },
]


_SERVER_KEY = "mahavishnu"


# Name-indexed view of the static catalog — built once at module
# load so the body loader can do O(1) lookups instead of scanning
# the list.
_STATIC_AGENTS_BY_NAME: dict[str, dict[str, Any]] = {
    entry["name"]: entry for entry in _STATIC_AGENTS
}


# --- Body source (server-specific) ------------------------------------


def _read_body(filename: str) -> str:
    """Load an agent body from the catalog, asserting the file exists."""
    path = _CATALOG_DIR / filename
    if not path.is_file():
        raise FileNotFoundError(
            f"Agent body {filename!r} missing from catalog at {path}"
        )
    return path.read_text(encoding="utf-8")


def _body_loader(name: str) -> str:
    """Factory's body source: read the file from disk.

    The factory's ``_build_unsigned_metadata`` calls this on demand
    for any catalog entry that doesn't carry ``system_prompt``
    inline. The factory strips the returned string and computes
    the B-6 content_hash from the stripped bytes.
    """
    return _read_body(_STATIC_AGENTS_BY_NAME[name]["body_filename"])


# --- Signing policy (server-specific) ---------------------------------


def _sign(metadata: AgentCanonicalSchema) -> AgentCanonicalSchema:
    """Apply an ed25519 signature using the lifespan-owned signer.

    The factory hands the unsigned metadata to this callable and
    receives the signed copy. Acquires the signer via
    :func:`mahavishnu.mcp.signer_feed.get_signer_feed_state`
    (lifespan-owned), canonicalizes via mahavishnu's local
    :func:`canonical_payload_for_signing` (which strips the
    ``signature`` + ``server_pubkey_id`` fields before signing so
    the signature doesn't cover itself), and attaches the result.

    Raises if the signer feed state isn't initialized (server
    still starting up, or pre-Phase-1.5 lite mode). The factory
    converts the exception into the standard error envelope.
    """
    from mahavishnu.mcp.signer_feed import get_signer_feed_state
    from mahavishnu.skills_signer import canonical_payload_for_signing

    state = get_signer_feed_state()
    if state is None:
        raise RuntimeError(
            "signer not initialized (server may still be starting up)"
        )

    canonical = canonical_payload_for_signing(metadata.to_dict())
    signed = state.signer.sign(canonical)
    return metadata.model_copy(
        update={
            "signature": signed.signature_b64,
            "server_pubkey_id": signed.key_id,
        }
    )


# --- B-7 cycle bump (server-specific) ---------------------------------


def _on_call() -> None:
    """B-7: bump ``SignerFeedState.cycles_total`` on every tool call.

    The factory invokes this at the start of every list_agents and
    get_agent call so the four mandatory feed signals stay
    accurate. No-op if the signer feed state isn't initialized
    yet (matches the pre-refactor behavior).
    """
    from mahavishnu.mcp.signer_feed import get_signer_feed_state

    state = get_signer_feed_state()
    if state is not None:
        state.record_cycle()


# --- Tool registration ------------------------------------------------


def register_agents_tools(app: FastMCP) -> None:
    """Register ``mahavishnu_list_agents`` and ``mahavishnu_get_agent`` MCP tools.

    Idempotent at module level (the static catalog is loaded once
    at import). Calling this twice is safe — FastMCP's
    ``@app.tool`` decorator is idempotent within a single
    ``app`` instance.

    Delegates to :func:`mcp_common.agents_tools.build_register_agents_tools`
    with mahavishnu's catalog, body source, signing policy, cycle-bump
    hook, and tool name prefix. The wire shape, allowlist
    enforcement, and envelope contract all live in the factory;
    mahavishnu only owns the data, the signer, and the prefix.
    """
    build_register_agents_tools(
        server_key=_SERVER_KEY,
        catalog=_STATIC_AGENTS,
        body_loader=_body_loader,
        sign=_sign,
        on_call=_on_call,
        tool_name_prefix=f"{_SERVER_KEY}_",
        # The hook and any in-flight clients expect the
        # "mahavishnu_" prefix on both tool names.
    )(app)


__all__ = ["register_agents_tools", "AgentCanonicalSchema"]
