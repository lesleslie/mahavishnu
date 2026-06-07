"""Unit tests for ``mahavishnu.terminal.adapters.base.TerminalAdapter``.

The base class is an ``abc.ABC`` so we cannot instantiate it directly. These
tests verify that the abstract interface is properly declared and that a
concrete subclass has to implement all required methods.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from mahavishnu.terminal.adapters.base import TerminalAdapter

# =============================================================================
# Fixtures
# =============================================================================


class _CompleteAdapter(TerminalAdapter):
    """Concrete subclass that fully implements the abstract interface."""

    @property
    def adapter_name(self) -> str:
        return "complete"

    async def launch_session(
        self,
        command: str,
        columns: int = 80,
        rows: int = 24,
        **kwargs: Any,
    ) -> str:
        return "sid"

    async def send_command(self, session_id: str, command: str) -> None:
        return None

    async def capture_output(
        self,
        session_id: str,
        lines: int | None = None,
    ) -> str:
        return ""

    async def close_session(self, session_id: str) -> None:
        return None

    async def list_sessions(self) -> list[dict[str, Any]]:
        return []


class _MissingLaunchAdapter(TerminalAdapter):
    """Concrete subclass missing launch_session."""

    @property
    def adapter_name(self) -> str:
        return "missing-launch"

    async def send_command(self, session_id: str, command: str) -> None:
        return None

    async def capture_output(
        self,
        session_id: str,
        lines: int | None = None,
    ) -> str:
        return ""

    async def close_session(self, session_id: str) -> None:
        return None

    async def list_sessions(self) -> list[dict[str, Any]]:
        return []


# =============================================================================
# Abstract Behavior Tests
# =============================================================================


class TestTerminalAdapterAbstract:
    """Tests that the TerminalAdapter ABC is correctly defined."""

    def test_cannot_instantiate_abstract_class(self):
        """Direct instantiation should raise TypeError because the class is abstract."""
        with pytest.raises(TypeError):
            TerminalAdapter()  # type: ignore[abstract]

    def test_incomplete_subclass_cannot_be_instantiated(self):
        """A subclass missing an abstract method should still raise TypeError."""
        with pytest.raises(TypeError):
            _MissingLaunchAdapter()  # type: ignore[abstract]

    def test_complete_subclass_can_be_instantiated(self):
        """A fully-implemented subclass should be instantiable."""
        adapter = _CompleteAdapter()
        assert isinstance(adapter, TerminalAdapter)

    def test_adapter_name_is_abstract_property(self):
        """``adapter_name`` should be declared abstract on the base class."""
        # adapter_name is decorated with @property and @abstractmethod
        abstract_methods = TerminalAdapter.__abstractmethods__
        assert "adapter_name" in abstract_methods
        assert "launch_session" in abstract_methods
        assert "send_command" in abstract_methods
        assert "capture_output" in abstract_methods
        assert "close_session" in abstract_methods
        assert "list_sessions" in abstract_methods

    def test_subclass_overriding_with_property_is_concrete(self):
        """A subclass that supplies a property satisfies the abstract requirement."""
        adapter = _CompleteAdapter()
        assert adapter.adapter_name == "complete"


# =============================================================================
# Concrete Adapter Behavior Tests
# =============================================================================


class TestConcreteAdapterMethods:
    """Tests that concrete subclass methods are callable as declared."""

    def test_launch_session_returns_session_id(self):
        adapter = _CompleteAdapter()
        # Replace the async method with an AsyncMock so we can call it without awaits
        adapter.launch_session = AsyncMock(return_value="abc123")  # type: ignore[method-assign]
        import asyncio

        result = asyncio.run(adapter.launch_session("qwen", 100, 30))
        assert result == "abc123"
        adapter.launch_session.assert_awaited_once()

    def test_send_command_runs(self):
        adapter = _CompleteAdapter()
        adapter.send_command = AsyncMock()  # type: ignore[method-assign]
        import asyncio

        asyncio.run(adapter.send_command("sid", "ls"))
        adapter.send_command.assert_awaited_once_with("sid", "ls")

    def test_capture_output_runs(self):
        adapter = _CompleteAdapter()
        adapter.capture_output = AsyncMock(return_value="hello")  # type: ignore[method-assign]
        import asyncio

        result = asyncio.run(adapter.capture_output("sid", lines=10))
        assert result == "hello"
        adapter.capture_output.assert_awaited_once_with("sid", lines=10)

    def test_close_session_runs(self):
        adapter = _CompleteAdapter()
        adapter.close_session = AsyncMock()  # type: ignore[method-assign]
        import asyncio

        asyncio.run(adapter.close_session("sid"))
        adapter.close_session.assert_awaited_once_with("sid")

    def test_list_sessions_returns_list(self):
        adapter = _CompleteAdapter()
        adapter.list_sessions = AsyncMock(return_value=[{"id": "sid"}])  # type: ignore[method-assign]
        import asyncio

        result = asyncio.run(adapter.list_sessions())
        assert result == [{"id": "sid"}]


# =============================================================================
# Parameterised Tests
# =============================================================================


@pytest.mark.parametrize(
    "abstract_name",
    [
        "adapter_name",
        "launch_session",
        "send_command",
        "capture_output",
        "close_session",
        "list_sessions",
    ],
)
class TestAbstractMembersDeclared:
    """Ensure every member the contract promises is abstract."""

    def test_member_is_abstract(self, abstract_name: str):
        assert abstract_name in TerminalAdapter.__abstractmethods__
