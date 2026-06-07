"""Unit tests for the shared terminal-worker execution protocol.

Covers ``mahavishnu.workers.protocol`` which defines:

- ``ProgressSnapshot`` TypedDict
- ``TerminalWorkerProtocol`` structural Protocol
- ``is_terminal_worker`` TypeGuard
"""

from __future__ import annotations

from typing import Any

import pytest

from mahavishnu.core.status import WorkerStatus
from mahavishnu.workers.base import WorkerResult
from mahavishnu.workers.protocol import (
    ProgressSnapshot,
    TerminalWorkerProtocol,
    is_terminal_worker,
)

pytestmark = pytest.mark.unit


# =============================================================================
# Fixtures
# =============================================================================


def _make_progress_dict() -> ProgressSnapshot:
    """Helper to build a valid ``ProgressSnapshot`` instance."""
    return {
        "status": "running",
        "session_id": "sess-1",
        "output_preview": "hello",
        "duration_seconds": 1.5,
        "worker_type": "terminal",
        "worker_name": "primary",
        "category": "shell",
    }


class _ConformingWorker:
    """Minimal concrete implementation of ``TerminalWorkerProtocol``."""

    worker_type: str = "test-worker"
    session_id: str | None = None

    async def start(self) -> str:
        self.session_id = "sess-x"
        return self.session_id

    async def execute(self, task: dict[str, Any]) -> WorkerResult:
        return WorkerResult(
            worker_id="w-1",
            status=WorkerStatus.COMPLETED,
            output=str(task),
        )

    async def stop(self) -> None:
        self.session_id = None

    async def status(self) -> WorkerStatus:
        return WorkerStatus.RUNNING if self.session_id else WorkerStatus.PENDING

    async def get_progress(self) -> ProgressSnapshot:
        return {
            "status": "running" if self.session_id else "pending",
            "session_id": self.session_id,
            "output_preview": "",
            "duration_seconds": 0.0,
            "worker_type": self.worker_type,
            "worker_name": "conforming",
            "category": "test",
        }

    async def health_check(self) -> dict[str, Any]:
        return {"healthy": True}


class _MissingStart:
    worker_type: str = "missing-start"
    session_id: str | None = None

    async def execute(self, task: dict[str, Any]) -> WorkerResult: ...  # type: ignore[override]

    async def stop(self) -> None: ...

    async def status(self) -> WorkerStatus: ...

    async def get_progress(self) -> ProgressSnapshot: ...

    async def health_check(self) -> dict[str, Any]: ...


class _WrongWorkerType:
    """Conforms in shape but ``worker_type`` is not a string."""

    worker_type: int = 1  # type: ignore[assignment]
    session_id: str | None = None

    async def start(self) -> str: ...

    async def execute(self, task: dict[str, Any]) -> WorkerResult: ...

    async def stop(self) -> None: ...

    async def status(self) -> WorkerStatus: ...

    async def get_progress(self) -> ProgressSnapshot: ...

    async def health_check(self) -> dict[str, Any]: ...


# =============================================================================
# ProgressSnapshot TypedDict
# =============================================================================


class TestProgressSnapshot:
    """Behaviour of the ``ProgressSnapshot`` TypedDict."""

    def test_keys_required(self) -> None:
        """``ProgressSnapshot`` declares the documented keys."""
        annotations = ProgressSnapshot.__annotations__
        for key in (
            "status",
            "session_id",
            "output_preview",
            "duration_seconds",
            "worker_type",
            "worker_name",
            "category",
        ):
            assert key in annotations, f"Missing key: {key}"

    def test_construct_via_dict_literal(self) -> None:
        snap = _make_progress_dict()
        assert snap["status"] == "running"
        assert snap["session_id"] == "sess-1"
        assert snap["output_preview"] == "hello"
        assert snap["duration_seconds"] == 1.5
        assert snap["worker_type"] == "terminal"
        assert snap["worker_name"] == "primary"
        assert snap["category"] == "shell"

    def test_session_id_can_be_none(self) -> None:
        snap: ProgressSnapshot = {
            "status": "pending",
            "session_id": None,
            "output_preview": "",
            "duration_seconds": 0.0,
            "worker_type": "test",
            "worker_name": "test",
            "category": "test",
        }
        assert snap["session_id"] is None

    def test_isinstance_via_typed_dict(self) -> None:
        """TypedDict instances are still dicts at runtime."""
        snap = _make_progress_dict()
        assert isinstance(snap, dict)
        # TypedDict provides functional access
        assert snap.get("status") == "running"


# =============================================================================
# TerminalWorkerProtocol
# =============================================================================


class TestTerminalWorkerProtocol:
    """Behaviour of the ``TerminalWorkerProtocol`` Protocol class."""

    def test_protocol_is_defined(self) -> None:
        assert TerminalWorkerProtocol is not None
        # Protocol is a typing construct, not a regular class
        from typing import Protocol as _Protocol

        assert issubclass(TerminalWorkerProtocol, _Protocol)

    def test_protocol_docstring_present(self) -> None:
        """The protocol's docstring explains the contract guarantees."""
        assert TerminalWorkerProtocol.__doc__ is not None
        assert "start" in TerminalWorkerProtocol.__doc__
        assert "execute" in TerminalWorkerProtocol.__doc__

    def test_required_attributes(self) -> None:
        """Protocol declares worker_type and session_id."""
        annotations = TerminalWorkerProtocol.__annotations__
        assert "worker_type" in annotations
        assert "session_id" in annotations

    def test_required_async_methods(self) -> None:
        members = {name for name in dir(TerminalWorkerProtocol) if not name.startswith("_")}
        for method in (
            "start",
            "execute",
            "stop",
            "status",
            "get_progress",
            "health_check",
        ):
            assert method in members, f"Missing protocol method: {method}"

    def test_conforming_class_has_all_members(self) -> None:
        """Spot-check the fixture implementation has every required member."""
        worker = _ConformingWorker()
        for attr in (
            "worker_type",
            "session_id",
            "start",
            "execute",
            "stop",
            "status",
            "get_progress",
            "health_check",
        ):
            assert hasattr(worker, attr), f"ConformingWorker missing {attr}"


# =============================================================================
# is_terminal_worker TypeGuard
# =============================================================================


class TestIsTerminalWorker:
    """Behaviour of the ``is_terminal_worker`` TypeGuard."""

    def test_conforming_instance_returns_true(self) -> None:
        worker = _ConformingWorker()
        assert is_terminal_worker(worker) is True

    def test_missing_method_returns_false(self) -> None:
        assert is_terminal_worker(_MissingStart()) is False

    def test_non_string_worker_type_returns_false(self) -> None:
        """Even if shape matches, non-str ``worker_type`` fails the guard."""
        assert is_terminal_worker(_WrongWorkerType()) is False

    def test_builtin_object_returns_false(self) -> None:
        assert is_terminal_worker(object()) is False

    def test_plain_string_returns_false(self) -> None:
        assert is_terminal_worker("not-a-worker") is False

    def test_dict_returns_false(self) -> None:
        assert is_terminal_worker({}) is False

    def test_none_returns_false(self) -> None:
        assert is_terminal_worker(None) is False

    def test_uses_hasattr_not_getattr_magic(self) -> None:
        """``is_terminal_worker`` relies on ``hasattr`` checks, not type annotations.

        It only inspects *attribute names* and the type of ``worker_type``,
        not whether the class was registered as a Protocol implementer.
        """

        # A class that only declares attribute names but no methods passes
        # the attribute-existence checks. The TypeGuard still returns False
        # because the method attributes are missing.
        class AttributesOnly:
            worker_type = "x"
            session_id = None
            # No start/execute/stop/status/get_progress/health_check

        assert is_terminal_worker(AttributesOnly()) is False

    def test_class_object_itself_also_checked(self) -> None:
        """The guard examines the same shape for class and instance."""
        # Both the class and its instance have the documented members.
        assert is_terminal_worker(_ConformingWorker) is True
        assert is_terminal_worker(_ConformingWorker()) is True

    def test_partial_attribute_set_fails(self) -> None:
        """An instance with only some attributes still fails."""

        class Partial:
            worker_type = "x"
            session_id = None
            # No methods

        assert is_terminal_worker(Partial()) is False


# =============================================================================
# Module exports
# =============================================================================


class TestModuleExports:
    """The module's ``__all__`` exports are importable and documented."""

    def test_all_exports_present(self) -> None:
        from mahavishnu.workers import protocol

        for name, ref in (
            ("ProgressSnapshot", ProgressSnapshot),
            ("TerminalWorkerProtocol", TerminalWorkerProtocol),
            ("is_terminal_worker", is_terminal_worker),
        ):
            assert name in protocol.__all__
            assert getattr(protocol, name) is ref

    def test_is_terminal_worker_is_callable(self) -> None:
        assert callable(is_terminal_worker)
