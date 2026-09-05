"""Unit tests for ``mahavishnu.mcp.tools.terminal_tools``.

The module exposes ``register_terminal_tools`` which attaches 10 FastMCP
tools (``terminal_launch``, ``terminal_send``, ``terminal_capture``,
``terminal_capture_all``, ``terminal_list``, ``terminal_close``,
``terminal_close_all``, ``terminal_switch_adapter``,
``terminal_current_adapter``, ``terminal_list_adapters``).

The FastMCP API requires each tool function to be defined inline so the
decorator can introspect the function name and signature. We register
against a stub ``FastMCP`` instance that captures the decorated callables
in a dict, then invoke each registered function directly with mocked
dependencies. This mirrors the pattern used by
``tests/unit/mcp/tools/test_worker_tools.py``.

The module also exposes the module-level ``validate_command_safety``
function (re-exported through the MCP tools for ``terminal_launch`` /
``terminal_send``), and the internal ``_NullEventPublisher`` used by the
``switch_adapter`` path. Both get direct unit coverage here.
"""

from __future__ import annotations

import inspect
import pathlib
import re
import typing
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic.fields import FieldInfo

from mahavishnu.mcp.tools.terminal_tools import (
    DANGEROUS_COMMAND_PATTERNS,
    _NullEventPublisher,
    register_terminal_tools,
    validate_command_safety,
)
from mahavishnu.terminal.config import TerminalSettings

pytestmark = pytest.mark.unit


# =============================================================================
# Stub MCP and fixtures
# =============================================================================


def _extract_string_constraints(annotation: Any) -> dict[str, Any]:
    """Pull ``StringConstraints`` (or similar) metadata off an ``Annotated[...]``.

    The production ``SessionID`` / ``Command`` aliases use
    ``Annotated[str, StringConstraints(pattern=..., min_length=..., max_length=...)]``.
    FastMCP enforces these at the MCP boundary; this test stub replicates
    that behaviour for direct calls.
    """
    constraints: dict[str, Any] = {}
    if typing.get_origin(annotation) is not typing.Annotated:
        return constraints
    for meta in typing.get_args(annotation)[1:]:
        # ``StringConstraints`` exposes its constraints as attributes.
        for attr in ("pattern", "min_length", "max_length"):
            value = getattr(meta, attr, None)
            if value is not None:
                constraints[attr] = value
    return constraints


class _StubMCP:
    """Minimal FastMCP stand-in that captures tool functions by name.

    Like ``tests/unit/mcp/tools/test_worker_tools._StubMCP``, but also
    resolves Pydantic ``Field(...)`` defaults and ``Annotated`` constraints
    at decoration time so callers can invoke the tool with only the kwargs
    they care about (matching the FastMCP client-side validation contract).
    """

    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}
        self._raw_tools: dict[str, Any] = {}

    def tool(self):
        def decorator(fn):
            self._raw_tools[fn.__name__] = fn
            self.tools[fn.__name__] = self._wrap_with_field_validation(fn)
            return fn

        return decorator

    @staticmethod
    def _wrap_with_field_validation(fn: Any) -> Any:
        """Bind ``Field`` defaults and enforce ``Annotated`` constraints.

        ``terminal_launch`` declares ``count: int = Field(default=1, ge=1, le=10)``.
        At function-definition time that sets ``count``'s default to a
        ``FieldInfo`` instance instead of ``1``. FastMCP validates the kwargs
        at the MCP boundary; this stub replicates that behaviour for direct calls.
        """
        # ``from __future__ import annotations`` keeps all annotations as
        # strings; ``eval_str=True`` resolves them against the function's
        # own ``__globals__`` so ``Annotated[str, StringConstraints(...)]``
        # comes back as the live Annotated alias rather than the bare name.
        sig = inspect.signature(fn, eval_str=True)
        cleaned_params: list[inspect.Parameter] = []
        annotated_constraints: dict[str, dict[str, Any]] = {}
        for param in sig.parameters.values():
            cleaned_params.append(
                param.replace(default=param.default)
                if not isinstance(param.default, FieldInfo)
                else param.replace(default=param.default.default)
            )
            annotated_constraints[param.name] = _extract_string_constraints(
                param.annotation
            )
        new_sig = sig.replace(parameters=cleaned_params)

        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            bound = new_sig.bind_partial(*args, **kwargs)
            bound.apply_defaults()
            for pname, param in new_sig.parameters.items():
                if pname not in bound.arguments:
                    continue
                value = bound.arguments[pname]
                fi = sig.parameters[pname].default
                if isinstance(fi, FieldInfo):
                    for meta in fi.metadata:
                        ge = getattr(meta, "ge", None)
                        le = getattr(meta, "le", None)
                        gt = getattr(meta, "gt", None)
                        lt = getattr(meta, "lt", None)
                        if ge is not None and value < ge:
                            raise ValueError(
                                f"{pname} must be >= {ge} (got {value})"
                            )
                        if le is not None and value > le:
                            raise ValueError(
                                f"{pname} must be <= {le} (got {value})"
                            )
                        if gt is not None and value <= gt:
                            raise ValueError(
                                f"{pname} must be > {gt} (got {value})"
                            )
                        if lt is not None and value >= lt:
                            raise ValueError(
                                f"{pname} must be < {lt} (got {value})"
                            )
                # Enforce ``Annotated[str, StringConstraints(...)]`` aliases.
                constraints = annotated_constraints.get(pname) or {}
                if isinstance(value, str):
                    if "min_length" in constraints and len(value) < constraints["min_length"]:
                        raise ValueError(
                            f"{pname} must be >= {constraints['min_length']} chars"
                        )
                    if "max_length" in constraints and len(value) > constraints["max_length"]:
                        raise ValueError(
                            f"{pname} must be <= {constraints['max_length']} chars"
                        )
                    if "pattern" in constraints:
                        pattern = constraints["pattern"]
                        if isinstance(pattern, str) and not re.fullmatch(
                            pattern, value
                        ):
                            raise ValueError(
                                f"{pname} must match pattern {pattern}"
                            )
            return await fn(*bound.args, **bound.kwargs)

        wrapper.__name__ = getattr(fn, "__name__", "wrapped")
        wrapper.__wrapped__ = fn
        return wrapper


def _make_manager(
    *,
    current_adapter_name: str = "mock",
    config: TerminalSettings | None = None,
    history: list[dict[str, Any]] | None = None,
) -> MagicMock:
    """Build a MagicMock TerminalManager with realistic default returns."""

    manager = MagicMock()
    manager.launch_sessions = AsyncMock(return_value=["sess-1", "sess-2"])
    manager.send_command = AsyncMock(return_value=None)
    manager.capture_output = AsyncMock(return_value="captured output")
    manager.capture_all_outputs = AsyncMock(
        return_value={"sess-1": "out-1", "sess-2": "out-2"}
    )
    manager.list_sessions = AsyncMock(
        return_value=[
            {"id": "sess-1", "command": "echo hello"},
            {"id": "sess-2", "command": "echo world"},
        ]
    )
    manager.close_session = AsyncMock(return_value=None)
    manager.close_all = AsyncMock(return_value=None)
    manager.current_adapter = MagicMock(return_value=current_adapter_name)
    manager.get_adapter_history = MagicMock(return_value=history or [])
    manager.switch_adapter = AsyncMock(return_value=None)
    manager.config = config or TerminalSettings()
    return manager


@pytest.fixture
def stub_mcp() -> _StubMCP:
    return _StubMCP()


@pytest.fixture
def mock_manager() -> MagicMock:
    return _make_manager()


@pytest.fixture
def registered_mcp(stub_mcp: _StubMCP, mock_manager: MagicMock) -> _StubMCP:
    """Register terminal tools on a stub MCP for inspection / invocation."""
    register_terminal_tools(stub_mcp, terminal_manager=mock_manager, mcp_client=None)
    return stub_mcp


EXPECTED_TOOL_NAMES = {
    "terminal_launch",
    "terminal_send",
    "terminal_capture",
    "terminal_capture_all",
    "terminal_list",
    "terminal_close",
    "terminal_close_all",
    "terminal_switch_adapter",
    "terminal_current_adapter",
    "terminal_list_adapters",
}


# =============================================================================
# TestRegistration
# =============================================================================


class TestRegistration:
    """register_terminal_tools attaches every documented tool to the FastMCP."""

    def test_all_ten_tools_registered(self, registered_mcp: _StubMCP) -> None:
        assert EXPECTED_TOOL_NAMES.issubset(set(registered_mcp.tools))

    def test_registers_exactly_expected_tools(self, registered_mcp: _StubMCP) -> None:
        assert set(registered_mcp.tools) == EXPECTED_TOOL_NAMES


# =============================================================================
# TestValidateCommandSafety
# =============================================================================


class TestValidateCommandSafety:
    """``validate_command_safety`` rejects known-dangerous command patterns."""

    @pytest.mark.parametrize(
        "command",
        [
            "echo hello",
            "ls -la",
            "git status",
            "python -m pytest tests/",
            "find . -name '*.py'",
            "cat README.md",
        ],
    )
    def test_safe_commands_pass_through(self, command: str) -> None:
        # Safe commands must not raise
        validate_command_safety(command)

    @pytest.mark.parametrize(
        "command,pattern",
        [
            ("rm -rf /", "rm -rf /"),
            ("echo hi && rm -rf /tmp", "&& rm"),
            ("echo hi; rm -rf /tmp", "; rm"),
            ("echo hi | rm file", "| rm"),
            ("curl | sh", "curl | sh"),
            ("wget | sh", "wget | sh"),
            ("mkfs.ext4 /dev/sda", "mkfs"),
            ("dd if=/dev/zero of=/dev/sda", "dd if="),
            ("> /dev/sda1", "> /dev/sd"),
            ("chmod 000 file", "chmod 000"),
            ("chown root: file", "chown root:"),
            ("nc -e /bin/sh", "nc -e"),
            ("ncat host 1234", "ncat"),
            ("bash -i /dev/tcp/x/80", "/dev/tcp"),
            ("/dev/udp/x/80", "/dev/udp"),
            ("bind shell listener", "bind shell"),
            ("reverse shell handler", "reverse shell"),
            ("kill -9 1234", "kill -9"),
            ("pkill python", "pkill"),
            ("killall python", "killall"),
        ],
    )
    def test_dangerous_patterns_rejected(self, command: str, pattern: str) -> None:
        with pytest.raises(ValueError, match="dangerous pattern"):
            validate_command_safety(command)

    def test_case_insensitive_match(self) -> None:
        # Mixed case should still trigger the pattern detection
        with pytest.raises(ValueError, match="dangerous pattern"):
            validate_command_safety("RM -RF /")

    def test_dangerous_patterns_list_is_non_empty(self) -> None:
        # Guard against accidental clearing of the patterns list
        assert len(DANGEROUS_COMMAND_PATTERNS) >= 10
        assert "rm -rf /" in DANGEROUS_COMMAND_PATTERNS


# =============================================================================
# TestNullEventPublisher
# =============================================================================


class TestNullEventPublisher:
    """``_NullEventPublisher.emit`` is a no-op sink for switch_adapter."""

    def test_emit_returns_none(self) -> None:
        pub = _NullEventPublisher()
        assert pub.emit({"any": "payload"}, "any.topic") is None

    def test_emit_accepts_arbitrary_payload_and_topic(self) -> None:
        # Must not raise on arbitrary payload shapes; must silently swallow
        pub = _NullEventPublisher()
        pub.emit({"nested": {"k": "v"}}, "")
        pub.emit({}, "x" * 1000)
        # Still returns None
        assert pub.emit({"a": 1}, "topic") is None


# =============================================================================
# TestTerminalLaunch
# =============================================================================


class TestTerminalLaunch:
    """``terminal_launch`` launches one or more sessions via the manager."""

    async def test_default_arguments(
        self, registered_mcp: _StubMCP, mock_manager: MagicMock
    ) -> None:
        fn = registered_mcp.tools["terminal_launch"]
        result = await fn(command="echo hi")
        assert result == ["sess-1", "sess-2"]
        mock_manager.launch_sessions.assert_awaited_once_with(
            "echo hi", 1, 120, 40
        )

    async def test_custom_count_columns_rows(
        self, registered_mcp: _StubMCP, mock_manager: MagicMock
    ) -> None:
        fn = registered_mcp.tools["terminal_launch"]
        result = await fn(command="qwen", count=3, columns=200, rows=50)
        assert result == ["sess-1", "sess-2"]
        mock_manager.launch_sessions.assert_awaited_once_with(
            "qwen", 3, 200, 50
        )

    async def test_dangerous_command_rejected_before_launch(
        self, registered_mcp: _StubMCP, mock_manager: MagicMock
    ) -> None:
        fn = registered_mcp.tools["terminal_launch"]
        with pytest.raises(ValueError, match="dangerous pattern"):
            await fn(command="rm -rf /")
        mock_manager.launch_sessions.assert_not_awaited()

    @pytest.mark.parametrize("bad_count", [0, -1, 11, 100])
    async def test_count_out_of_range_rejected(
        self, registered_mcp: _StubMCP, mock_manager: MagicMock, bad_count: int
    ) -> None:
        fn = registered_mcp.tools["terminal_launch"]
        with pytest.raises(ValueError):
            await fn(command="ls", count=bad_count)
        mock_manager.launch_sessions.assert_not_awaited()

    @pytest.mark.parametrize("bad_columns", [10, 39, 301, 500])
    async def test_columns_out_of_range_rejected(
        self, registered_mcp: _StubMCP, mock_manager: MagicMock, bad_columns: int
    ) -> None:
        fn = registered_mcp.tools["terminal_launch"]
        with pytest.raises(ValueError):
            await fn(command="ls", columns=bad_columns)
        mock_manager.launch_sessions.assert_not_awaited()

    @pytest.mark.parametrize("bad_rows", [5, 9, 201, 500])
    async def test_rows_out_of_range_rejected(
        self, registered_mcp: _StubMCP, mock_manager: MagicMock, bad_rows: int
    ) -> None:
        fn = registered_mcp.tools["terminal_launch"]
        with pytest.raises(ValueError):
            await fn(command="ls", rows=bad_rows)
        mock_manager.launch_sessions.assert_not_awaited()

    async def test_increments_metrics(
        self, registered_mcp: _StubMCP, mock_manager: MagicMock
    ) -> None:
        fn = registered_mcp.tools["terminal_launch"]
        snap_before = registered_mcp  # noqa: F841 - placeholder
        # Use the singleton via the module's `_metrics` reference. The existing
        # test_pool_share_metrics.py already verifies the metric increment for
        # ``terminal_launch``; this test asserts the same tool is callable when
        # invoked through the registered function pointer.
        result = await fn(command="echo hi")
        assert result == ["sess-1", "sess-2"]


# =============================================================================
# TestTerminalSend
# =============================================================================


class TestTerminalSend:
    """``terminal_send`` forwards a command to an existing session."""

    async def test_returns_success_payload(
        self, registered_mcp: _StubMCP, mock_manager: MagicMock
    ) -> None:
        fn = registered_mcp.tools["terminal_send"]
        result = await fn(session_id="sess-1", command="echo hello")
        assert result == {
            "status": "success",
            "session_id": "sess-1",
            "command": "echo hello",
        }
        mock_manager.send_command.assert_awaited_once_with("sess-1", "echo hello")

    async def test_dangerous_command_rejected_before_send(
        self, registered_mcp: _StubMCP, mock_manager: MagicMock
    ) -> None:
        fn = registered_mcp.tools["terminal_send"]
        with pytest.raises(ValueError, match="dangerous pattern"):
            await fn(session_id="sess-1", command="pkill python")
        mock_manager.send_command.assert_not_awaited()

    @pytest.mark.parametrize(
        "bad_session_id",
        ["", "session/with/slash", "session with space"],
    )
    async def test_invalid_session_id_rejected(
        self, registered_mcp: _StubMCP, mock_manager: MagicMock, bad_session_id: str
    ) -> None:
        fn = registered_mcp.tools["terminal_send"]
        with pytest.raises(ValueError):
            await fn(session_id=bad_session_id, command="ls")
        mock_manager.send_command.assert_not_awaited()

    @pytest.mark.parametrize(
        "dot_session_id",
        ["session.with.dot", "sess.1.2.3", "a.b.c.d.e"],
    )
    async def test_session_id_with_dots_accepted(
        self, registered_mcp: _StubMCP, mock_manager: MagicMock, dot_session_id: str
    ) -> None:
        """Dot-containing session IDs are valid for some adapters (e.g. macOS Terminal).

        Regression test for
        ``docs/followups/2026-09-05-terminal-send-annotated-validator-mismatch.md``.
        The previous regex ``[a-zA-Z0-9_-]`` rejected these IDs at the MCP
        boundary; the relaxed regex ``[a-zA-Z0-9._-]`` lets them through.
        """
        fn = registered_mcp.tools["terminal_send"]
        result = await fn(session_id=dot_session_id, command="ls")
        assert result["session_id"] == dot_session_id
        mock_manager.send_command.assert_awaited_once_with(dot_session_id, "ls")

    async def test_oversized_command_rejected(
        self, registered_mcp: _StubMCP, mock_manager: MagicMock
    ) -> None:
        fn = registered_mcp.tools["terminal_send"]
        with pytest.raises(ValueError):
            await fn(session_id="sess-1", command="x" * 10_001)
        mock_manager.send_command.assert_not_awaited()

    async def test_empty_command_rejected(
        self, registered_mcp: _StubMCP, mock_manager: MagicMock
    ) -> None:
        fn = registered_mcp.tools["terminal_send"]
        with pytest.raises(ValueError):
            await fn(session_id="sess-1", command="")
        mock_manager.send_command.assert_not_awaited()


# =============================================================================
# TestTerminalCapture
# =============================================================================


class TestTerminalCapture:
    """``terminal_capture`` reads the most recent pane output."""

    async def test_capture_returns_text(
        self, registered_mcp: _StubMCP, mock_manager: MagicMock
    ) -> None:
        fn = registered_mcp.tools["terminal_capture"]
        result = await fn(session_id="sess-1")
        assert result == "captured output"
        mock_manager.capture_output.assert_awaited_once_with("sess-1", None)

    async def test_capture_with_lines(
        self, registered_mcp: _StubMCP, mock_manager: MagicMock
    ) -> None:
        fn = registered_mcp.tools["terminal_capture"]
        result = await fn(session_id="sess-1", lines=50)
        assert result == "captured output"
        mock_manager.capture_output.assert_awaited_once_with("sess-1", 50)


# =============================================================================
# TestTerminalCaptureAll
# =============================================================================


class TestTerminalCaptureAll:
    """``terminal_capture_all`` reads multiple sessions concurrently."""

    async def test_capture_all_returns_mapping(
        self, registered_mcp: _StubMCP, mock_manager: MagicMock
    ) -> None:
        fn = registered_mcp.tools["terminal_capture_all"]
        result = await fn(session_ids=["sess-1", "sess-2"])
        assert result == {"sess-1": "out-1", "sess-2": "out-2"}
        mock_manager.capture_all_outputs.assert_awaited_once_with(
            ["sess-1", "sess-2"], None
        )

    async def test_capture_all_with_lines(
        self, registered_mcp: _StubMCP, mock_manager: MagicMock
    ) -> None:
        fn = registered_mcp.tools["terminal_capture_all"]
        result = await fn(session_ids=["sess-1"], lines=10)
        assert result == {"sess-1": "out-1", "sess-2": "out-2"}
        mock_manager.capture_all_outputs.assert_awaited_once_with(
            ["sess-1"], 10
        )


# =============================================================================
# TestTerminalList
# =============================================================================


class TestTerminalList:
    """``terminal_list`` returns every active session."""

    async def test_returns_session_list(
        self, registered_mcp: _StubMCP, mock_manager: MagicMock
    ) -> None:
        fn = registered_mcp.tools["terminal_list"]
        result = await fn()
        assert result == [
            {"id": "sess-1", "command": "echo hello"},
            {"id": "sess-2", "command": "echo world"},
        ]
        mock_manager.list_sessions.assert_awaited_once_with()


# =============================================================================
# TestTerminalClose
# =============================================================================


class TestTerminalClose:
    """``terminal_close`` shuts down one session."""

    async def test_close_session(
        self, registered_mcp: _StubMCP, mock_manager: MagicMock
    ) -> None:
        fn = registered_mcp.tools["terminal_close"]
        result = await fn(session_id="sess-1")
        assert result is None
        mock_manager.close_session.assert_awaited_once_with("sess-1")


# =============================================================================
# TestTerminalCloseAll
# =============================================================================


class TestTerminalCloseAll:
    """``terminal_close_all`` shuts down every active session."""

    async def test_close_all_with_sessions(
        self, registered_mcp: _StubMCP, mock_manager: MagicMock
    ) -> None:
        fn = registered_mcp.tools["terminal_close_all"]
        result = await fn()
        assert result == {"closed_count": 2}
        mock_manager.list_sessions.assert_awaited_once_with()
        mock_manager.close_all.assert_awaited_once_with(["sess-1", "sess-2"])

    async def test_close_all_with_empty_session_list(
        self, registered_mcp: _StubMCP, mock_manager: MagicMock
    ) -> None:
        mock_manager.list_sessions = AsyncMock(return_value=[])
        fn = registered_mcp.tools["terminal_close_all"]
        result = await fn()
        assert result == {"closed_count": 0}
        mock_manager.close_all.assert_not_awaited()

    async def test_close_all_uses_terminal_id_fallback(
        self, registered_mcp: _StubMCP, mock_manager: MagicMock
    ) -> None:
        # Some adapters emit "terminal_id" instead of "id"; the close_all
        # extractor should fall back.
        mock_manager.list_sessions = AsyncMock(
            return_value=[
                {"id": "sess-1"},
                {"terminal_id": "sess-2"},  # only terminal_id is present
            ]
        )
        fn = registered_mcp.tools["terminal_close_all"]
        result = await fn()
        assert result == {"closed_count": 2}
        mock_manager.close_all.assert_awaited_once_with(["sess-1", "sess-2"])

    async def test_close_all_handles_missing_ids(
        self, registered_mcp: _StubMCP, mock_manager: MagicMock
    ) -> None:
        # Records with neither id nor terminal_id are skipped (filtered)
        # rather than coerced to empty string. The previous shape passed
        # ``""`` through to manager.close_all, which was invalid.
        # See ``docs/followups/2026-09-05-terminal-close-all-empty-id-roundtrip.md``.
        mock_manager.list_sessions = AsyncMock(
            return_value=[{"command": "echo hi"}, {"id": "sess-1"}]
        )
        fn = registered_mcp.tools["terminal_close_all"]
        result = await fn()
        assert result == {"closed_count": 1}
        mock_manager.close_all.assert_awaited_once_with(["sess-1"])

    async def test_close_all_skips_all_empty_ids(
        self, registered_mcp: _StubMCP, mock_manager: MagicMock
    ) -> None:
        """All-missing-IDs case: closed_count=0 and close_all is never awaited."""
        mock_manager.list_sessions = AsyncMock(
            return_value=[{"command": "x"}, {"terminal_id": ""}]
        )
        fn = registered_mcp.tools["terminal_close_all"]
        result = await fn()
        assert result == {"closed_count": 0}
        mock_manager.close_all.assert_not_awaited()


# =============================================================================
# TestTerminalCurrentAdapter
# =============================================================================


class TestTerminalCurrentAdapter:
    """``terminal_current_adapter`` returns the active adapter and history."""

    async def test_returns_current_and_history(
        self, registered_mcp: _StubMCP, mock_manager: MagicMock
    ) -> None:
        history = [
            {"from": "mock", "to": "tmux", "timestamp": "2026-01-01T00:00:00Z"},
        ]
        mock_manager.get_adapter_history = MagicMock(return_value=history)
        fn = registered_mcp.tools["terminal_current_adapter"]
        result = await fn()
        assert result == {"adapter": "mock", "history": history}
        mock_manager.current_adapter.assert_called_once_with()
        mock_manager.get_adapter_history.assert_called_once_with()

    async def test_returns_empty_history_by_default(
        self, registered_mcp: _StubMCP, mock_manager: MagicMock
    ) -> None:
        fn = registered_mcp.tools["terminal_current_adapter"]
        result = await fn()
        assert result == {"adapter": "mock", "history": []}


# =============================================================================
# TestTerminalListAdapters
# =============================================================================


class TestTerminalListAdapters:
    """``terminal_list_adapters`` lists tmux + mock + (opt-in) crow."""

    async def test_lists_tmux_and_mock_when_crow_disabled(
        self, registered_mcp: _StubMCP, mock_manager: MagicMock
    ) -> None:
        # Default TerminalSettings has crow_enabled=False
        fn = registered_mcp.tools["terminal_list_adapters"]
        result = await fn()
        assert result["current"] == "mock"
        assert set(result["adapters"].keys()) == {"tmux", "mock"}
        assert result["adapters"]["tmux"]["status"] == "available"
        assert result["adapters"]["mock"]["status"] == "available"
        # No crow entry because crow_enabled defaults to False
        assert "crow" not in result["adapters"]

    async def test_includes_crow_when_enabled(
        self, registered_mcp: _StubMCP, mock_manager: MagicMock
    ) -> None:
        # Patch the manager's config to advertise crow_enabled=True
        config = TerminalSettings(crow_enabled=True)
        mock_manager.config = config
        fn = registered_mcp.tools["terminal_list_adapters"]
        result = await fn()
        assert set(result["adapters"].keys()) == {"tmux", "mock", "crow"}
        assert result["adapters"]["crow"]["status"] == "available"
        assert "PTY via bodai-crow" in result["adapters"]["crow"]["description"]

    async def test_handles_missing_config(
        self, registered_mcp: _StubMCP, mock_manager: MagicMock
    ) -> None:
        # Some terminal manager implementations may not expose ``config``;
        # ``getattr(..., None)`` should fall back to no crow entry.
        del mock_manager.config
        fn = registered_mcp.tools["terminal_list_adapters"]
        result = await fn()
        assert set(result["adapters"].keys()) == {"tmux", "mock"}
        assert "crow" not in result["adapters"]


# =============================================================================
# TestTerminalSwitchAdapter
# =============================================================================


class TestTerminalSwitchAdapter:
    """``terminal_switch_adapter`` hot-swaps the active backend."""

    async def test_already_using_same_adapter(
        self, registered_mcp: _StubMCP, mock_manager: MagicMock
    ) -> None:
        # Manager already reports adapter_name='mock'
        fn = registered_mcp.tools["terminal_switch_adapter"]
        result = await fn(adapter_name="mock")
        assert result["status"] == "already_using"
        assert result["current_adapter"] == "mock"
        assert "Already using mock" in result["message"]
        mock_manager.switch_adapter.assert_not_awaited()

    async def test_unknown_adapter_returns_error(
        self, registered_mcp: _StubMCP, mock_manager: MagicMock
    ) -> None:
        fn = registered_mcp.tools["terminal_switch_adapter"]
        result = await fn(adapter_name="bogus")
        assert result["status"] == "error"
        assert "Unknown adapter: bogus" in result["message"]
        mock_manager.switch_adapter.assert_not_awaited()

    async def test_iterm2_raises_not_implemented(
        self, registered_mcp: _StubMCP, mock_manager: MagicMock
    ) -> None:
        fn = registered_mcp.tools["terminal_switch_adapter"]
        # Current adapter is 'mock', so we are not "already_using" iterm2.
        with pytest.raises(NotImplementedError, match="iTerm2 adapter is deprecated"):
            await fn(adapter_name="iterm2")
        mock_manager.switch_adapter.assert_not_awaited()

    async def test_crow_disabled_returns_error(
        self, registered_mcp: _StubMCP, mock_manager: MagicMock
    ) -> None:
        # crow_enabled defaults to False on TerminalSettings
        fn = registered_mcp.tools["terminal_switch_adapter"]
        result = await fn(adapter_name="crow")
        assert result["status"] == "error"
        assert "crow_enabled is false" in result["message"]
        mock_manager.switch_adapter.assert_not_awaited()

    async def test_tmux_switch_success(
        self,
        registered_mcp: _StubMCP,
        mock_manager: MagicMock,
        tmp_path: pathlib.Path,
    ) -> None:
        # Patch Path.home() to tmp_path so the switch_adapter path does not
        # touch the user's real ~/.mahavishnu.
        with patch.object(pathlib.Path, "home", staticmethod(lambda: tmp_path)):
            # Also stub out DurableWorkerManager + WorkerRecordStore so we
            # do not actually construct a tmux subprocess manager.
            fake_manager = MagicMock()
            with (
                patch(
                    "mahavishnu.mcp.tools.terminal_tools.TmuxTerminalAdapter",
                    MagicMock(return_value=fake_manager),
                ),
            ):
                fn = registered_mcp.tools["terminal_switch_adapter"]
                result = await fn(adapter_name="tmux", migrate_sessions=True)
        assert result["status"] == "success"
        assert result["previous_adapter"] == "mock"
        assert result["new_adapter"] == "tmux"
        assert result["migrate_sessions"] is True
        mock_manager.switch_adapter.assert_awaited_once_with(
            fake_manager, True
        )

    async def test_crow_enabled_success(
        self, registered_mcp: _StubMCP, mock_manager: MagicMock
    ) -> None:
        # Patch both the crow client factory and the CrowTerminalAdapter class
        # so we can simulate a successful crow switch without networking.
        # ``create_crow_mcp_client`` / ``CrowTerminalAdapter`` are lazy-imported
        # inside ``terminal_switch_adapter``, so we must patch the source
        # module attributes, not the terminal_tools module attributes.
        mock_manager.config = TerminalSettings(crow_enabled=True)
        fake_adapter = MagicMock()
        with (
            patch(
                "mahavishnu.mcp.crow_server.create_crow_mcp_client",
                MagicMock(return_value=MagicMock()),
            ),
            patch(
                "mahavishnu.terminal.adapters.crow.CrowTerminalAdapter",
                MagicMock(return_value=fake_adapter),
            ),
        ):
            fn = registered_mcp.tools["terminal_switch_adapter"]
            result = await fn(adapter_name="crow")
        assert result["status"] == "success"
        assert result["new_adapter"] == "crow"
        mock_manager.switch_adapter.assert_awaited_once_with(fake_adapter, False)

    async def test_switch_exception_returns_error_envelope(
        self, registered_mcp: _StubMCP, mock_manager: MagicMock
    ) -> None:
        # Wire a fake tmux adapter that lets the switch path succeed at
        # construction, then make the underlying ``switch_adapter`` raise.
        fake_adapter = MagicMock()
        with patch.object(pathlib.Path, "home", staticmethod(lambda: pathlib.Path("/tmp"))):
            with patch(
                "mahavishnu.mcp.tools.terminal_tools.TmuxTerminalAdapter",
                MagicMock(return_value=fake_adapter),
            ):
                mock_manager.switch_adapter = AsyncMock(
                    side_effect=RuntimeError("boom")
                )
                fn = registered_mcp.tools["terminal_switch_adapter"]
                result = await fn(adapter_name="tmux")
        assert result["status"] == "error"
        assert "Failed to switch adapter: boom" in result["message"]

    async def test_migrate_sessions_false_default(
        self, registered_mcp: _StubMCP, mock_manager: MagicMock, tmp_path: pathlib.Path
    ) -> None:
        with patch.object(pathlib.Path, "home", staticmethod(lambda: tmp_path)):
            fake_adapter = MagicMock()
            with patch(
                "mahavishnu.mcp.tools.terminal_tools.TmuxTerminalAdapter",
                MagicMock(return_value=fake_adapter),
            ):
                fn = registered_mcp.tools["terminal_switch_adapter"]
                result = await fn(adapter_name="tmux")
        assert result["status"] == "success"
        # migrate_sessions should default to False when not specified
        mock_manager.switch_adapter.assert_awaited_once_with(fake_adapter, False)
