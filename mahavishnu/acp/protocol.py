"""ACP wire-format Pydantic models.

Every message type Mahavishnu sends or receives over the Agent Client
Protocol (ACP) stdio JSON-RPC 2.0 boundary is modeled here with ``extra="forbid"``
Pydantic models. Field shapes follow the ACP spec (camelCase discriminator,
mandatory ``sessionId`` on every notification) — *not* the A2A conventions.

## Design rules

- **Snake-case Pydantic field names are not used;** the wire format preserves
  ACP's camelCase (``sessionUpdate``, ``mcpCapabilities``, ``sessionId``). Per
  ``mahavishnu/a2a/card.py``, we annotate with ``# noqa: N815`` to silence
  the camelCase linter rule rather than rename fields.
- **All inbound models use ``extra="forbid"``** so that unknown fields are
  rejected at the Pydantic layer before they reach the dispatcher. This is the
  spec-drift guard: if ACP adds a field we don't model, clients that send it
  get a clean Pydantic validation error instead of silent acceptance.
- **String fields carry ``max_length`` caps** so oversized payloads are
  rejected at the Pydantic layer before they reach ``execute_fn``. The caps
  come from the v1.0 plan §Phase 1 Task 2 (final bullet) and reflect ACP's
  reasonable-input expectations, not a security boundary (the dispatcher's
  stdin reader is the real boundary, with its 1 MB line cap).
- **Session IDs are RFC 4122 v4 UUIDs** in v1. v1.5 will migrate to v7
  (time-ordered) per the persistence bundle (v1.5.4) once persistence ships.

## Module map

The wire shapes are grouped by direction and lifecycle phase:

- ``InitializeRequest`` / ``InitializeResponse`` — handshake
- ``AuthenticateRequest`` — bearer auth gate
- ``SessionNewRequest`` / ``SessionNewResponse`` — session creation
- ``SessionPromptRequest`` — client → agent prompt
- ``SessionCancelRequest`` — client → agent cancel
- ``SessionUpdate`` (discriminated union) — agent → client notification stream
- ``JsonRpcRequest`` / ``JsonRpcResponse`` / ``JsonRpcErrorResponse`` /
  ``JsonRpcError`` — JSON-RPC 2.0 envelopes (used by the dispatcher in Phase 2)
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# === Field caps (plan §Phase 1 Task 2, final bullet) ===

PROTOCOL_VERSION_MAX: int = 32
SESSION_ID_MAX: int = 64
CLIENT_NAME_MAX: int = 64
CLIENT_VERSION_MAX: int = 32
PROMPT_MAX: int = 100_000  # 100 KB; the dispatcher's stdin cap is 1 MB


# === Initialize handshake ===

class McpCapabilities(BaseModel):
    """ACP ``agentCapabilities.mcpCapabilities`` sub-shape.

    ``http`` and ``sse`` are the two MCP-over-ACP capability flags. Both
    default to ``False`` in v1 (no MCP-over-ACP; that ships with v1.5.2
    when the upstream RFD stabilizes).
    """

    model_config = ConfigDict(extra="forbid")

    http: bool = False
    sse: bool = False


class AgentCapabilities(BaseModel):
    """ACP ``agentCapabilities`` — what the agent supports.

    ``loadSession`` defaults to ``False`` in v1 (the v1 dispatcher returns
    ``-32003 Not implemented`` for ``session/load`` per plan Decision 1).
    The v1.5.1 persistence bundle flips this to ``True``.
    """

    model_config = ConfigDict(extra="forbid")

    loadSession: bool = False  # noqa: N815 — ACP spec field name
    mcpCapabilities: McpCapabilities = Field(default_factory=McpCapabilities)  # noqa: N815


class ClientInfo(BaseModel):
    """ACP ``clientInfo`` — identifies the ACP client."""

    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, Field(max_length=CLIENT_NAME_MAX)]
    version: Annotated[str, Field(max_length=CLIENT_VERSION_MAX)]


class InitializeRequest(BaseModel):
    """ACP ``initialize`` request (client → agent)."""

    model_config = ConfigDict(extra="forbid")

    protocolVersion: Annotated[str, Field(max_length=PROTOCOL_VERSION_MAX)]  # noqa: N815
    clientInfo: ClientInfo  # noqa: N815
    agentCapabilities: AgentCapabilities | None = None  # noqa: N815


class InitializeResponse(BaseModel):
    """ACP ``initialize`` response (agent → client)."""

    model_config = ConfigDict(extra="forbid")

    protocolVersion: Annotated[str, Field(max_length=PROTOCOL_VERSION_MAX)]  # noqa: N815
    agentCapabilities: AgentCapabilities = Field(default_factory=AgentCapabilities)  # noqa: N815


# === Authentication ===

class AuthenticateRequest(BaseModel):
    """ACP ``authenticate`` request (client → agent).

    ``methodId`` is constrained to ``"bearer"`` in v1. Future authentication
    methods (e.g., mTLS, SSH key) would extend this union. The bearer ``token``
    is intentionally not length-capped here — the dispatcher enforces
    reasonable limits and logs the value with a redaction filter (Phase 2).
    """

    model_config = ConfigDict(extra="forbid")

    methodId: Literal["bearer"]  # noqa: N815
    token: str


# === Session lifecycle ===

class SessionNewRequest(BaseModel):
    """ACP ``session/new`` request (client → agent).

    No parameters in v1 — the session ID is assigned by the agent. v1.5
    may add optional metadata (working directory, model selection).
    """

    model_config = ConfigDict(extra="forbid")


class SessionNewResponse(BaseModel):
    """ACP ``session/new`` response (agent → client).

    ``sessionId`` is an RFC 4122 v4 UUID string in v1. The v1.5.4
    persistence bundle migrates to v7 (time-ordered) once the persistence
    file format (v1.5.1) is in place.
    """

    model_config = ConfigDict(extra="forbid")

    sessionId: str = Field(  # noqa: N815
        min_length=1,
        max_length=SESSION_ID_MAX,
    )


# === Session content (discriminated union by ``type``) ===

class TextContent(BaseModel):
    """ACP text content payload."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["text"]
    text: Annotated[str, Field(max_length=PROMPT_MAX)]


SessionContent = Annotated[
    TextContent,
    Field(discriminator="type"),
]
"""ACP ``session/prompt`` content list element. Discriminated by ``type``.

Only ``text`` is supported in v1; image/audio/etc. are deferred to v1.5+.
"""


# === Session prompts and cancel ===

class SessionPromptRequest(BaseModel):
    """ACP ``session/prompt`` request (client → agent)."""

    model_config = ConfigDict(extra="forbid")

    sessionId: Annotated[str, Field(min_length=1, max_length=SESSION_ID_MAX)]  # noqa: N815
    content: list[SessionContent]


class SessionCancelRequest(BaseModel):
    """ACP ``session/cancel`` request (client → agent)."""

    model_config = ConfigDict(extra="forbid")

    sessionId: Annotated[str, Field(min_length=1, max_length=SESSION_ID_MAX)]  # noqa: N815


# === Session update notifications (agent → client) ===

ToolCallStatus = Literal["running", "completed", "failed"]
SessionStatus = Literal["working", "completed", "failed"]


class AgentMessageChunk(BaseModel):
    """``agent_message_chunk`` session update subtype.

    Carries a single text content payload as part of the streamed response
    from the agent. Multiple chunks may arrive before a terminal
    ``status: "completed"`` ``StatusUpdate``.
    """

    model_config = ConfigDict(extra="forbid")

    sessionUpdate: Literal["agent_message_chunk"] = "agent_message_chunk"  # noqa: N815
    sessionId: Annotated[str, Field(min_length=1, max_length=SESSION_ID_MAX)]  # noqa: N815
    content: TextContent


class ToolCallUpdate(BaseModel):
    """``tool_call_update`` session update subtype.

    Notifies the client that a tool call has changed state. ``toolCallId``
    is opaque to the client; it ties together the ``running`` →
    ``completed``/``failed`` transitions. ``title`` and ``content`` are
    optional UX affordances for clients that want to render the tool call
    inline (Toad uses these to show "running tool X" status).
    """

    model_config = ConfigDict(extra="forbid")

    sessionUpdate: Literal["tool_call_update"] = "tool_call_update"  # noqa: N815
    sessionId: Annotated[str, Field(min_length=1, max_length=SESSION_ID_MAX)]  # noqa: N815
    toolCallId: Annotated[str, Field(min_length=1, max_length=SESSION_ID_MAX)]  # noqa: N815
    status: ToolCallStatus
    title: str | None = None
    content: list[SessionContent] | None = None


class StatusUpdate(BaseModel):
    """``status`` session update subtype.

    Marks session lifecycle transitions. ``status="completed"`` is terminal
    for a successful run; ``status="failed"`` is terminal with an error;
    ``status="working"`` is intermediate (e.g., the agent has accepted the
    prompt but has not yet produced any chunks).
    """

    model_config = ConfigDict(extra="forbid")

    sessionUpdate: Literal["status"] = "status"  # noqa: N815
    sessionId: Annotated[str, Field(min_length=1, max_length=SESSION_ID_MAX)]  # noqa: N815
    status: SessionStatus


SessionUpdate = Annotated[
    AgentMessageChunk | ToolCallUpdate | StatusUpdate,
    Field(discriminator="sessionUpdate"),
]
"""ACP ``session/update`` notification payload. Discriminated by ``sessionUpdate``.

``sessionId`` is mandatory on every variant — clients can route notifications
to the right session without parsing the full envelope.
"""


# === JSON-RPC 2.0 envelopes ===

class JsonRpcRequest(BaseModel):
    """JSON-RPC 2.0 request envelope (``id`` is required for ACP requests).

    ACP uses JSON-RPC 2.0 over stdio. ``id`` is required on requests (so the
    client can correlate responses); the dispatcher sets it to ``None`` on
    notifications (which ACP does not currently use, but the field is
    permissive for forward compatibility).
    """

    model_config = ConfigDict(extra="forbid")

    jsonrpc: Literal["2.0"] = "2.0"
    id: int | str | None
    method: str
    params: dict[str, Any] | None = None


class JsonRpcError(BaseModel):
    """JSON-RPC 2.0 error object."""

    model_config = ConfigDict(extra="forbid")

    code: int
    message: str
    data: Any = None


class JsonRpcResponse(BaseModel):
    """JSON-RPC 2.0 success response envelope."""

    model_config = ConfigDict(extra="forbid")

    jsonrpc: Literal["2.0"] = "2.0"
    id: int | str | None
    result: Any


class JsonRpcErrorResponse(BaseModel):
    """JSON-RPC 2.0 error response envelope."""

    model_config = ConfigDict(extra="forbid")

    jsonrpc: Literal["2.0"] = "2.0"
    id: int | str | None
    error: JsonRpcError


__all__ = [
    "CLIENT_NAME_MAX",
    "CLIENT_VERSION_MAX",
    "PROMPT_MAX",
    "PROTOCOL_VERSION_MAX",
    "SESSION_ID_MAX",
    "AgentCapabilities",
    "AgentMessageChunk",
    "AuthenticateRequest",
    "ClientInfo",
    "InitializeRequest",
    "InitializeResponse",
    "JsonRpcError",
    "JsonRpcErrorResponse",
    "JsonRpcRequest",
    "JsonRpcResponse",
    "McpCapabilities",
    "SessionCancelRequest",
    "SessionContent",
    "SessionNewRequest",
    "SessionNewResponse",
    "SessionPromptRequest",
    "SessionStatus",
    "SessionUpdate",
    "StatusUpdate",
    "TextContent",
    "ToolCallStatus",
    "ToolCallUpdate",
]
