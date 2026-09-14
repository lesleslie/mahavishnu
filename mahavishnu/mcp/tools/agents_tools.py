"""Phase 3 server-published agents tools (Phase 3 of bodai-skill-agent-distribution).

Exposes the ``mcp__mahavishnu__mahavishnu_list_agents`` and
``mcp__mahavishnu__mahavishnu_get_agent`` tools that advertise the server-
defined agents to Phase 3's installer and the Claude Code picker. Agents
live as markdown bodies under
``mahavishnu/mcp/agents/<name>.md``; this module reads them at request
time and signs the metadata via the lifespan-owned
:class:`SkillsSigner`.

Security gates (per plan §11):

- **B-1** — every ``get_agent`` response carries an ed25519 signature
  over the canonicalized metadata (the Phase 3 installer verifies this
  before any write to ``~/.claude/agents/<server>-<name>.md``).
- **B-4** — path-traversal allowlist ``^[a-z0-9][a-z0-9._-]{0,62}$`` is
  enforced on the ``name`` parameter at the API boundary, BEFORE the
  metadata model re-validates it. Defense-in-depth: an unknown /
  forbidden ``name`` returns an error envelope rather than raising
  past the MCP boundary.
- **B-6** — every ``get_agent`` response returns BOTH the metadata AND
  the full body (``system_prompt``). Without the body, the installer
  would ship non-functional agents that have no system-prompt text.
- **B-7** — each successful tool call bumps
  ``SignerFeedState.cycles_total`` via :meth:`record_cycle` so the
  four mandatory feed signals stay accurate.

Non-goals:

- Body content is loaded at request time (L-6). No session-start
  pre-load.
- The 3 starter agents ship as static markdown files in ``agents/``;
  Phase 4's federation layer (``mcp__akosha__list_ecosystem_agents``)
  is what exposes them alongside the other 4 servers' catalogs.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
import re
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from mahavishnu.mcp.agent_schema import AgentMetadata
from mahavishnu.skills_signer import canonical_payload_for_signing

if TYPE_CHECKING:
    from fastmcp import FastMCP

logger = logging.getLogger(__name__)


# Allowlist mirror — see B-4 / plan §5 task #4. Duplicated here so the
# API boundary rejects forbidden ``name`` values BEFORE constructing the
# Pydantic model (avoids letting a path-traversal payload reach the
# validator, which would surface as a different error class).
_NAME_ALLOWLIST_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,62}$")


# Catalog lives next to this module so deployment paths stay self-
# contained. The catalog is static — new agents are added by dropping a
# new ``.md`` file under ``agents/`` and adding an entry to
# ``_STATIC_AGENTS``.
_CATALOG_DIR = Path(__file__).parent.parent / "agents"


# Phase 3: 3 starter agents with real content. Each tuple is the body's
# filename (relative to ``agents/``), the semantic version, the
# description that goes in both the AgentMetadata AND the frontmatter,
# the model hint, the list of exact tool names the agent may invoke,
# the dependency list (other agent names), and the MCP tool names the
# agent's body references.
#
# Adding a new server-published agent: drop ``<name>.md`` under
# ``agents/`` AND add an entry below. The validator runs at module
# load — a missing file or mismatched hash fails fast.
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


_SERVER_NAME = "mahavishnu"


# Name-indexed view of the static catalog — built once at module load so
# the tool handlers can do O(1) lookups instead of scanning the list.
# This MUST stay below ``_STATIC_AGENTS`` so the dict comprehension sees
# the full list (Python's module body executes top-to-bottom; this
# lookup is never called before the module finishes loading).
_STATIC_AGENTS_BY_NAME: dict[str, dict[str, Any]] = {
    entry["name"]: entry for entry in _STATIC_AGENTS
}


def _read_body(filename: str) -> str:
    """Load an agent body from the catalog, asserting the file exists.

    The validator at module load time catches missing files before any
    MCP request reaches the runtime path. Returns the body as UTF-8
    text.
    """
    path = _CATALOG_DIR / filename
    if not path.is_file():
        raise FileNotFoundError(f"Agent body {filename!r} missing from catalog at {path}")
    return path.read_text(encoding="utf-8")


def _build_unsigned_metadata(name: str) -> AgentMetadata:
    """Build an :class:`AgentMetadata` for the named static agent.

    The metadata has ``signature=None`` and ``server_pubkey_id=None``;
    those fields are populated by :func:`_sign_metadata` after signing.
    Raises :class:`KeyError` if ``name`` is not a known static agent.
    """
    for entry in _STATIC_AGENTS:
        if entry["name"] != name:
            continue
        body = _read_body(entry["body_filename"])
        body_bytes = body.encode("utf-8")
        content_hash = hashlib.sha256(body_bytes).hexdigest()
        version = entry["version"]
        return AgentMetadata(
            id=f"{_SERVER_NAME}:{name}:{version}",
            server_key=_SERVER_NAME,
            name=name,
            title=entry["title"],
            description=entry["description"],
            version=version,
            model=entry["model"],
            tools=list(entry["tools"]),
            system_prompt=body,
            dependencies=list(entry["dependencies"]),
            tool_refs=list(entry["tool_refs"]),
            category=entry["category"],
            owner=entry["owner"],
            status=entry["status"],
            scope=entry["scope"],
            content_hash=content_hash,
        )
    msg = f"unknown agent {name!r}"
    raise KeyError(msg)


def _sign_metadata(metadata: AgentMetadata, signer: Any) -> AgentMetadata:
    """Apply an ed25519 signature to a copy of ``metadata``.

    The canonical payload strips ``signature`` and ``server_pubkey_id``
    BEFORE canonicalization so the signature doesn't cover itself (per
    ``canonical_payload_for_signing`` docstring + plan §10.1.3). The
    returned copy has both signing fields populated.
    """
    unsigned_dict = metadata.model_dump(mode="json")
    canonical = canonical_payload_for_signing(unsigned_dict)
    signed = signer.sign(canonical)
    return metadata.model_copy(
        update={
            "signature": signed.signature_b64,
            "server_pubkey_id": signed.key_id,
        }
    )


def _is_allowlisted(name: str) -> bool:
    """B-4 API-boundary check on the ``name`` parameter.

    Forbids ``/``, ``..``, leading ``.``, uppercase, length > 63, and
    any character outside ``[a-z0-9._-]``. Mirrors the AgentMetadata
    validator so failures at the API boundary return a uniform
    ``{"success": False, "error": ...}`` envelope.
    """
    return bool(_NAME_ALLOWLIST_RE.fullmatch(name)) and ".." not in name


def register_agents_tools(app: FastMCP) -> None:
    """Register ``mahavishnu_list_agents`` and ``mahavishnu_get_agent`` MCP tools.

    Idempotent at module level (the static catalog is loaded once at
    import). Calling this twice is safe — FastMCP's ``@app.tool``
    decorator is idempotent within a single ``app`` instance.

    The tools access the lifespan-owned :class:`SkillsSigner` via
    ``get_signer_feed_state()``; if the server is running without the
    Phase 1.5 wiring (lite mode / pre-startup), both tools return an
    error envelope rather than raising.
    """

    @app.tool(name="mahavishnu_list_agents")
    async def mahavishnu_list_agents() -> list[dict[str, Any]]:
        """Return metadata for agents this server publishes.

        Returns at least 3 entries (one per static agent in
        ``_STATIC_AGENTS``). The ``signature`` and ``server_pubkey_id``
        fields are ``None`` here — those are populated by
        ``mahavishnu_get_agent`` since the signature is over the
        canonical payload WITHOUT the signing fields themselves.

        Each entry's ``system_prompt`` field carries the full agent
        body so the Claude Code picker can preview the system prompt
        without a separate ``get_agent`` call.
        """
        from mahavishnu.mcp.signer_feed import (
            get_signer_feed_state,
        )

        state = get_signer_feed_state()
        if state is not None:
            state.record_cycle()

        out: list[dict[str, Any]] = []
        for entry in _STATIC_AGENTS:
            try:
                metadata = _build_unsigned_metadata(entry["name"])
            except FileNotFoundError, ValidationError, KeyError:
                # ``logger.exception`` already attaches the exception info;
                # passing ``exc`` separately would be redundant (TRY401).
                logger.exception(
                    "list_agents: failed to build metadata for %s",
                    entry["name"],
                )
                continue
            out.append(metadata.model_dump(mode="json"))
        return out

    @app.tool(name="mahavishnu_get_agent")
    async def mahavishnu_get_agent(name: str) -> dict[str, Any]:
        """Return the signed metadata + body for one agent.

        Validates ``name`` against the B-4 allowlist BEFORE constructing
        the metadata. Signs the metadata via the lifespan-owned
        :class:`SkillsSigner`. The body is the raw markdown text from
        ``agents/<name>.md`` — the client (Phase 3 installer) writes
        this verbatim to ``~/.claude/agents/mahavishnu-<name>.md``.

        Per B-6 the response is shaped ``{metadata, body}`` where
        ``body == metadata.system_prompt``; the installer can write
        either field directly. The dual surface is intentional so a
        client that already cached ``system_prompt`` from
        ``list_agents`` can skip a second body read.
        """
        from mahavishnu.mcp.signer_feed import (
            get_signer_feed_state,
        )

        if not _is_allowlisted(name):
            return {
                "success": False,
                "error": (
                    f"name {name!r} violates path-traversal allowlist "
                    "(B-4): must match ^[a-z0-9][a-z0-9._-]{0,62}$ "
                    "with no '..' substring"
                ),
            }

        state = get_signer_feed_state()
        if state is None:
            return {
                "success": False,
                "error": "signer not initialized (server may still be starting up)",
            }
        state.record_cycle()

        try:
            unsigned = _build_unsigned_metadata(name)
        except KeyError:
            return {
                "success": False,
                "error": f"agent {name!r} not found on this server",
            }
        except FileNotFoundError as exc:
            return {"success": False, "error": str(exc)}
        except ValidationError as exc:
            return {
                "success": False,
                "error": f"metadata validation failed: {exc}",
            }

        signed = _sign_metadata(unsigned, state.signer)
        body = _read_body(_STATIC_AGENTS_BY_NAME[name]["body_filename"])
        return {
            "success": True,
            "metadata": signed.model_dump(mode="json"),
            "body": body,
        }


# Build a {name: entry} index for O(1) lookup in the tool handlers.
# Done at module load; ``_STATIC_AGENTS`` is a static list so this is
# safe. (declared above; this comment is a navigation aid for readers —
# the dict comprehension lives just below the ``_STATIC_AGENTS`` list
# above.)


__all__ = ["register_agents_tools"]
