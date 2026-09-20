"""Tests for ``mahavishnu.acp.protocol`` — Pydantic wire-format models.

Two complementary layers of coverage:

1. **Spec-name parametrized drift gate** (``test_acp_spec_field_names``) — the
   CI gate for future spec drift. If ACP renames a field, this test fires
   before the runtime dispatcher does.
2. **Per-model round-trip + validation tests** — happy path, ``extra="forbid"``
   rejection, field-cap enforcement, and the wire-shape invariants the plan
   explicitly enumerates (``sessionUpdate`` as discriminator, ``sessionId``
   mandatory on notifications, etc.).

Markers: ``@pytest.mark.unit`` (fast/isolated) and ``@pytest.mark.acp``
(subsystem grouping). The plan deliberately chose ``acp`` (matching the
``mcp`` marker convention) over the more specific ``acp-stdio`` so the
filter ``-m acp`` catches the whole subsystem, not just the e2e cases.
"""

from __future__ import annotations

from pydantic import TypeAdapter, ValidationError
import pytest

from mahavishnu.acp.protocol import (
    CLIENT_NAME_MAX,
    CLIENT_VERSION_MAX,
    PROMPT_MAX,
    PROTOCOL_VERSION_MAX,
    SESSION_ID_MAX,
    AgentMessageChunk,
    AuthenticateRequest,
    ClientInfo,
    InitializeRequest,
    InitializeResponse,
    JsonRpcError,
    JsonRpcErrorResponse,
    JsonRpcRequest,
    JsonRpcResponse,
    McpCapabilities,
    SessionCancelRequest,
    SessionContent,
    SessionNewResponse,
    SessionPromptRequest,
    SessionUpdate,
    StatusUpdate,
    TextContent,
    ToolCallUpdate,
)

pytestmark = [pytest.mark.unit, pytest.mark.acp]


# ---------------------------------------------------------------------------
# Spec-name drift gate
# ---------------------------------------------------------------------------

# Each entry: (human-readable wire shape name, dict literal, model class,
# tuple path to the field that must exist). The dict literal is parsed as
# the wire-format JSON the agent/client would receive over stdio. If ACP
# renames a field in a future version, this test fails before the runtime
# dispatcher does.
#
# The ``field_path`` tuple lets us assert nested field names (e.g.,
# ``mcpCapabilities`` lives under ``agentCapabilities``, not at the top
# level of ``InitializeResponse``).
SPEC_FIELD_NAMES: list[tuple[str, dict, type, tuple[str, ...]]] = [
    (
        "InitializeResponse.agentCapabilities.mcpCapabilities (not mcp)",
        {
            "protocolVersion": "0.0.1",
            "agentCapabilities": {"loadSession": False, "mcpCapabilities": {"http": False, "sse": False}},
        },
        InitializeResponse,
        ("agentCapabilities", "mcpCapabilities"),
    ),
    (
        "ToolCallUpdate.toolCallId (not tool_call_id)",
        {
            "sessionUpdate": "tool_call_update",
            "sessionId": "00000000-0000-4000-8000-000000000000",
            "toolCallId": "call-1",
            "status": "running",
        },
        ToolCallUpdate,
        ("toolCallId",),
    ),
    (
        "SessionNewResponse.sessionId (not session_id)",
        {"sessionId": "00000000-0000-4000-8000-000000000000"},
        SessionNewResponse,
        ("sessionId",),
    ),
]


@pytest.mark.parametrize(
    ("label", "wire_shape", "model_cls", "field_path"),
    SPEC_FIELD_NAMES,
    ids=[entry[0] for entry in SPEC_FIELD_NAMES],
)
def test_acp_spec_field_names(
    label: str, wire_shape: dict, model_cls: type, field_path: tuple[str, ...]
) -> None:
    """Spec-name drift gate: each wire shape must parse against its ACP-spec field names."""
    parsed = model_cls.model_validate(wire_shape)
    dumped = parsed.model_dump()

    # Walk the path through the dumped structure, asserting each step exists.
    cursor: object = dumped
    for segment in field_path:
        assert isinstance(cursor, dict), (
            f"{label}: cannot descend into {segment!r}; cursor is {type(cursor).__name__}"
        )
        assert segment in cursor, (
            f"{label}: expected field {segment!r} missing from {sorted(cursor)} "
            f"(path so far: {'.'.join(field_path[:field_path.index(segment)])})"
        )
        cursor = cursor[segment]


# ---------------------------------------------------------------------------
# Initialize handshake
# ---------------------------------------------------------------------------

class TestInitialize:
    """``initialize`` request/response round-trip + invariants."""

    def test_request_round_trip(self) -> None:
        req = InitializeRequest(
            protocolVersion="0.0.1",
            clientInfo=ClientInfo(name="smoke", version="0.0.1"),
        )
        wire = req.model_dump()
        assert wire["protocolVersion"] == "0.0.1"
        assert wire["clientInfo"]["name"] == "smoke"
        assert InitializeRequest.model_validate(wire) == req

    def test_response_default_load_session_false(self) -> None:
        """Plan Decision 1: v1 returns -32003 for ``session/load``; loadSession defaults to False."""
        resp = InitializeResponse(protocolVersion="0.0.1")
        assert resp.agentCapabilities.loadSession is False
        assert resp.agentCapabilities.mcpCapabilities.http is False
        assert resp.agentCapabilities.mcpCapabilities.sse is False

    def test_response_round_trip_preserves_camel_case(self) -> None:
        """The wire format must serialize as ``agentCapabilities`` (not snake_case)."""
        resp = InitializeResponse(protocolVersion="0.0.1")
        wire = resp.model_dump()
        assert "agentCapabilities" in wire
        assert "agent_capabilities" not in wire

    def test_protocol_version_oversized_rejected(self) -> None:
        with pytest.raises(ValidationError):
            InitializeRequest(
                protocolVersion="x" * (PROTOCOL_VERSION_MAX + 1),
                clientInfo=ClientInfo(name="smoke", version="0.0.1"),
            )

    def test_extra_fields_rejected(self) -> None:
        """``extra=\"forbid\"`` rejects unknown fields at the Pydantic layer."""
        with pytest.raises(ValidationError):
            InitializeRequest.model_validate(
                {
                    "protocolVersion": "0.0.1",
                    "clientInfo": {"name": "smoke", "version": "0.0.1"},
                    "rogueField": "value",
                }
            )


class TestAuthenticate:
    """``authenticate`` request validation."""

    def test_method_id_must_be_bearer(self) -> None:
        with pytest.raises(ValidationError):
            AuthenticateRequest.model_validate(
                {"methodId": "mtls", "token": "x"}
            )

    def test_valid_bearer_round_trips(self) -> None:
        req = AuthenticateRequest(methodId="bearer", token="opaque-token")
        assert req.methodId == "bearer"
        assert AuthenticateRequest.model_validate(req.model_dump()) == req


# ---------------------------------------------------------------------------
# Session lifecycle
# ---------------------------------------------------------------------------

class TestSessionNew:
    def test_session_id_round_trips(self) -> None:
        sid = "00000000-0000-4000-8000-000000000000"
        resp = SessionNewResponse(sessionId=sid)
        assert resp.sessionId == sid
        assert SessionNewResponse.model_validate(resp.model_dump()) == resp

    def test_oversized_session_id_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SessionNewResponse(sessionId="x" * (SESSION_ID_MAX + 1))


# ---------------------------------------------------------------------------
# Session content
# ---------------------------------------------------------------------------

class TestSessionPrompt:
    def test_text_content_round_trip(self) -> None:
        req = SessionPromptRequest(
            sessionId="00000000-0000-4000-8000-000000000000",
            content=[TextContent(type="text", text="hello")],
        )
        assert req.content[0].text == "hello"
        assert req.content[0].type == "text"

    def test_content_discriminates_on_type(self) -> None:
        adapter: TypeAdapter = TypeAdapter(SessionContent)
        parsed = adapter.validate_python({"type": "text", "text": "x"})
        assert isinstance(parsed, TextContent)

    def test_prompt_oversized_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SessionPromptRequest(
                sessionId="00000000-0000-4000-8000-000000000000",
                content=[TextContent(type="text", text="x" * (PROMPT_MAX + 1))],
            )


# ---------------------------------------------------------------------------
# Session updates — discriminator + mandatory sessionId
# ---------------------------------------------------------------------------

class TestSessionUpdate:
    """``SessionUpdate`` is the discriminated-union wire shape for notifications."""

    def test_session_update_discriminator_is_session_update(self) -> None:
        """Plan explicit invariant: discriminator key is ``sessionUpdate``, NOT ``type``."""
        adapter: TypeAdapter = TypeAdapter(SessionUpdate)
        chunk = adapter.validate_python(
            {
                "sessionUpdate": "agent_message_chunk",
                "sessionId": "00000000-0000-4000-8000-000000000000",
                "content": {"type": "text", "text": "x"},
            }
        )
        assert isinstance(chunk, AgentMessageChunk)

    def test_session_id_missing_rejected(self) -> None:
        """Plan explicit invariant: ``sessionId`` is mandatory on every notification."""
        adapter: TypeAdapter = TypeAdapter(SessionUpdate)
        with pytest.raises(ValidationError):
            adapter.validate_python(
                {
                    "sessionUpdate": "agent_message_chunk",
                    "content": {"type": "text", "text": "x"},
                }
            )

    def test_unknown_session_update_type_rejected(self) -> None:
        adapter: TypeAdapter = TypeAdapter(SessionUpdate)
        with pytest.raises(ValidationError):
            adapter.validate_python(
                {
                    "sessionUpdate": "unknown_subtype",
                    "sessionId": "00000000-0000-4000-8000-000000000000",
                }
            )

    def test_tool_call_update_status_values(self) -> None:
        adapter: TypeAdapter = TypeAdapter(SessionUpdate)
        for status in ("running", "completed", "failed"):
            parsed = adapter.validate_python(
                {
                    "sessionUpdate": "tool_call_update",
                    "sessionId": "00000000-0000-4000-8000-000000000000",
                    "toolCallId": "call-1",
                    "status": status,
                }
            )
            assert isinstance(parsed, ToolCallUpdate)
            assert parsed.status == status

    def test_status_update_session_status_values(self) -> None:
        adapter: TypeAdapter = TypeAdapter(SessionUpdate)
        for status in ("working", "completed", "failed"):
            parsed = adapter.validate_python(
                {
                    "sessionUpdate": "status",
                    "sessionId": "00000000-0000-4000-8000-000000000000",
                    "status": status,
                }
            )
            assert isinstance(parsed, StatusUpdate)
            assert parsed.status == status


class TestSessionCancel:
    def test_session_cancel_round_trip(self) -> None:
        req = SessionCancelRequest(sessionId="00000000-0000-4000-8000-000000000000")
        assert SessionCancelRequest.model_validate(req.model_dump()) == req


# ---------------------------------------------------------------------------
# JSON-RPC 2.0 envelopes
# ---------------------------------------------------------------------------

class TestJsonRpcEnvelopes:
    def test_request_envelope_round_trip(self) -> None:
        req = JsonRpcRequest(
            jsonrpc="2.0",
            id=1,
            method="initialize",
            params={"protocolVersion": "0.0.1"},
        )
        wire = req.model_dump()
        assert wire["jsonrpc"] == "2.0"
        assert wire["id"] == 1
        assert wire["method"] == "initialize"
        assert JsonRpcRequest.model_validate(wire) == req

    def test_request_envelope_rejects_wrong_jsonrpc_version(self) -> None:
        with pytest.raises(ValidationError):
            JsonRpcRequest.model_validate(
                {"jsonrpc": "1.0", "id": 1, "method": "x"}
            )

    def test_response_envelope_round_trip(self) -> None:
        resp = JsonRpcResponse(jsonrpc="2.0", id=1, result={"ok": True})
        wire = resp.model_dump()
        assert wire["jsonrpc"] == "2.0"
        assert wire["id"] == 1
        assert wire["result"] == {"ok": True}
        assert JsonRpcResponse.model_validate(wire) == resp

    def test_error_envelope_shape(self) -> None:
        err = JsonRpcError(code=-32601, message="Method not found", data=None)
        assert err.code == -32601
        assert err.message == "Method not found"

    def test_error_response_envelope_round_trip(self) -> None:
        err_resp = JsonRpcErrorResponse(
            jsonrpc="2.0",
            id=1,
            error=JsonRpcError(code=-32601, message="Method not found"),
        )
        wire = err_resp.model_dump()
        assert wire["error"]["code"] == -32601
        assert JsonRpcErrorResponse.model_validate(wire) == err_resp

    def test_response_envelope_rejects_extra_fields(self) -> None:
        with pytest.raises(ValidationError):
            JsonRpcResponse.model_validate(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {"ok": True},
                    "rogueField": "value",
                }
            )


# ---------------------------------------------------------------------------
# Sub-shape sanity checks (catch refactors that silently break invariants)
# ---------------------------------------------------------------------------

class TestSubShapes:
    def test_mcp_capabilities_extra_forbid(self) -> None:
        with pytest.raises(ValidationError):
            McpCapabilities.model_validate({"http": False, "sse": False, "ftp": False})

    def test_client_info_field_caps(self) -> None:
        with pytest.raises(ValidationError):
            ClientInfo(name="x" * (CLIENT_NAME_MAX + 1), version="0.0.1")
        with pytest.raises(ValidationError):
            ClientInfo(name="smoke", version="x" * (CLIENT_VERSION_MAX + 1))

    def test_agent_capabilities_default_factory(self) -> None:
        """Each ``InitializeResponse`` carries its own default ``AgentCapabilities`` instance."""
        resp_a = InitializeResponse(protocolVersion="0.0.1")
        resp_b = InitializeResponse(protocolVersion="0.0.1")
        assert resp_a.agentCapabilities is not resp_b.agentCapabilities
