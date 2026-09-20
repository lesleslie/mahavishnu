"""Tests for ACP-related EventBridge emissions from worker lifecycle hooks.

These tests verify that worker dispatch boundaries emit ``tool_call.started``
and ``tool_call.completed`` envelopes at the right lifecycle moments, per
plan §Phase 1 Task 5. They do NOT exercise the full EventBridge → ACP
synthesizer pipeline (that lives in ``tests/unit/acp/test_events.py``);
they verify only the worker-side emission call shape.

The plan's positive assertion is: "apple_container.py and e2b_sandbox.py
both emit the two new envelope types". These tests pin that.

We patch at the worker-module import site (``apple_container.publish_*``,
``e2b_sandbox.publish_*``) rather than at the source module
(``mahavishnu_publisher.publish_*``). This catches a class of regression
where a worker stops importing the publisher — the patch lives at the
worker's namespace, so a missing import surfaces here rather than
silently producing empty captures.
"""

from __future__ import annotations

from typing import Any

import pytest

from mahavishnu.workers import apple_container, e2b_sandbox

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Capture helpers — patches the worker's imported publish_* names
# ---------------------------------------------------------------------------

class _Capture:
    """Records every call to the publish_* functions the worker module sees."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def _started(self, **kwargs: Any) -> None:
        self.calls.append(("started", kwargs))

    async def _completed(self, **kwargs: Any) -> None:
        self.calls.append(("completed", kwargs))


@pytest.fixture
def captured_apple(monkeypatch: pytest.MonkeyPatch) -> _Capture:
    cap = _Capture()
    monkeypatch.setattr(apple_container, "publish_tool_call_started", cap._started)
    monkeypatch.setattr(
        apple_container, "publish_tool_call_completed", cap._completed
    )
    return cap


@pytest.fixture
def captured_e2b(monkeypatch: pytest.MonkeyPatch) -> _Capture:
    cap = _Capture()
    monkeypatch.setattr(e2b_sandbox, "publish_tool_call_started", cap._started)
    monkeypatch.setattr(
        e2b_sandbox, "publish_tool_call_completed", cap._completed
    )
    return cap


# ---------------------------------------------------------------------------
# AppleContainerWorker
# ---------------------------------------------------------------------------

class TestAppleContainerEmission:
    """apple_container.start emits tool_call.started; .stop emits tool_call.completed."""

    def _make_worker(self, monkeypatch: pytest.MonkeyPatch) -> Any:
        # Bypass the platform gate so we can construct the worker on Intel/Linux.
        monkeypatch.setattr(apple_container, "is_apple_container_supported", lambda: True)

        # Stub the CLI seam so start/stop succeed without a real ``container`` binary.
        async def fake_run_cli(*argv: str, timeout: float | None = None) -> tuple[int, str, str]:
            if argv and argv[0] == "run":
                return (0, "container-id-abc123", "")
            if argv and argv[0] == "stop":
                return (0, "", "")
            return (0, "", "")

        monkeypatch.setattr(apple_container, "_run_cli", fake_run_cli)
        return apple_container.AppleContainerWorker()

    @pytest.mark.asyncio
    async def test_start_emits_tool_call_started(
        self, monkeypatch: pytest.MonkeyPatch, captured_apple: _Capture
    ) -> None:
        worker = self._make_worker(monkeypatch)
        await worker.start()
        # Exactly one started emission, no completed.
        assert len(captured_apple.calls) == 1
        kind, kwargs = captured_apple.calls[0]
        assert kind == "started"
        assert kwargs["worker_id"] == "apple-container"
        assert kwargs["task_id"] == "container-id-abc123"
        # session_id is None at the worker boundary; WorkerManager wires
        # the per-call session_id in a follow-on. See plan §Phase 1 Task 5.
        assert kwargs.get("session_id") is None

    @pytest.mark.asyncio
    async def test_stop_emits_tool_call_completed_with_completed_outcome(
        self, monkeypatch: pytest.MonkeyPatch, captured_apple: _Capture
    ) -> None:
        worker = self._make_worker(monkeypatch)
        await worker.start()
        await worker.stop()
        # One started + one completed.
        assert len(captured_apple.calls) == 2
        kinds = [k for k, _ in captured_apple.calls]
        assert kinds == ["started", "completed"]
        _, kwargs = captured_apple.calls[1]
        assert kwargs["worker_id"] == "apple-container"
        assert kwargs["task_id"] == "container-id-abc123"
        assert kwargs["outcome"] == "completed"

    @pytest.mark.asyncio
    async def test_stop_with_cli_failure_emits_completed_with_failed_outcome(
        self, monkeypatch: pytest.MonkeyPatch, captured_apple: _Capture
    ) -> None:
        """A failed stop must still emit a completion — with outcome=failed."""
        worker = self._make_worker(monkeypatch)

        async def fail_stop(*argv: str, timeout: float | None = None) -> tuple[int, str, str]:
            if argv and argv[0] == "run":
                return (0, "container-id-abc123", "")
            if argv and argv[0] == "stop":
                raise OSError("runtime cli unavailable")
            return (0, "", "")

        monkeypatch.setattr(apple_container, "_run_cli", fail_stop)

        await worker.start()
        with pytest.raises(RuntimeError):
            await worker.stop()
        # started + completed (with outcome=failed).
        kinds = [k for k, _ in captured_apple.calls]
        assert kinds == ["started", "completed"]
        _, kwargs = captured_apple.calls[1]
        assert kwargs["outcome"] == "failed"

    @pytest.mark.asyncio
    async def test_stop_without_start_is_noop(
        self, monkeypatch: pytest.MonkeyPatch, captured_apple: _Capture
    ) -> None:
        """Calling stop on an un-started worker must not emit anything."""
        worker = self._make_worker(monkeypatch)
        await worker.stop()
        assert captured_apple.calls == []


# ---------------------------------------------------------------------------
# E2BSandboxWorker
# ---------------------------------------------------------------------------

class TestE2BSandboxEmission:
    """e2b_sandbox.start emits tool_call.started; .stop emits tool_call.completed."""

    def _make_worker(self, monkeypatch: pytest.MonkeyPatch) -> Any:
        # The E2B SDK is an optional dependency; stub AsyncSandbox so we don't
        # require it at test time.
        class _FakeSandbox:
            sandbox_id = "e2b-sandbox-xyz"

            def __init__(self) -> None:
                pass

            async def kill(self) -> None:
                return None

        class _FakeAsyncSandbox:
            @staticmethod
            async def create(**_kwargs: Any) -> _FakeSandbox:
                return _FakeSandbox()

        import sys

        e2b_module = type(sys)("e2b")
        sandbox_module = type(sys)("e2b.sandbox")
        sandbox_module.AsyncSandbox = _FakeAsyncSandbox  # type: ignore[attr-defined]
        sys.modules["e2b"] = e2b_module
        sys.modules["e2b.sandbox"] = sandbox_module
        e2b_sandbox.e2b = e2b_module  # type: ignore[attr-defined]
        e2b_sandbox.AsyncSandbox = _FakeAsyncSandbox  # type: ignore[attr-defined]

        return e2b_sandbox.E2BSandboxWorker(template="base", timeout=300)

    @pytest.mark.asyncio
    async def test_start_emits_tool_call_started(
        self, monkeypatch: pytest.MonkeyPatch, captured_e2b: _Capture
    ) -> None:
        worker = self._make_worker(monkeypatch)
        await worker.start()
        assert len(captured_e2b.calls) == 1
        kind, kwargs = captured_e2b.calls[0]
        assert kind == "started"
        assert kwargs["worker_id"] == "e2b-sandbox"
        assert kwargs["task_id"] == "e2b-sandbox-xyz"
        assert kwargs.get("session_id") is None

    @pytest.mark.asyncio
    async def test_stop_emits_tool_call_completed_with_completed_outcome(
        self, monkeypatch: pytest.MonkeyPatch, captured_e2b: _Capture
    ) -> None:
        worker = self._make_worker(monkeypatch)
        await worker.start()
        await worker.stop()
        kinds = [k for k, _ in captured_e2b.calls]
        assert kinds == ["started", "completed"]
        _, kwargs = captured_e2b.calls[1]
        assert kwargs["worker_id"] == "e2b-sandbox"
        assert kwargs["task_id"] == "e2b-sandbox-xyz"
        assert kwargs["outcome"] == "completed"


# ---------------------------------------------------------------------------
# Sanity: the canonical publisher still works (not broken by the wire-up)
# ---------------------------------------------------------------------------

class TestPublisherSanity:
    """The publisher helpers must construct envelopes even when no publisher is passed."""

    @pytest.mark.asyncio
    async def test_publish_tool_call_started_no_publisher_is_noop(self) -> None:
        from mahavishnu.core.events.mahavishnu_publisher import (
            publish_tool_call_started,
        )

        # Should complete without raising; publisher=None means no-op.
        await publish_tool_call_started(
            worker_id="test",
            task_id="t1",
            session_id="s1",
        )

    @pytest.mark.asyncio
    async def test_publish_tool_call_completed_no_publisher_is_noop(self) -> None:
        from mahavishnu.core.events.mahavishnu_publisher import (
            publish_tool_call_completed,
        )

        await publish_tool_call_completed(
            worker_id="test",
            task_id="t1",
            outcome="failed",
            session_id="s1",
        )

    @pytest.mark.asyncio
    async def test_publish_tool_call_started_with_recorder(self) -> None:
        """With a recorder publisher, the envelope's topic and payload are correct."""
        from mahavishnu.core.events.mahavishnu_publisher import (
            TOPIC_TOOL_CALL_STARTED,
            publish_tool_call_started,
        )

        class Recorder:
            def __init__(self) -> None:
                self.published: list[Any] = []

            def publish(self, envelope: Any) -> None:
                self.published.append(envelope)

        rec = Recorder()
        await publish_tool_call_started(
            worker_id="test",
            task_id="t1",
            name="my-tool",
            session_id="s1",
            publisher=rec,
        )
        assert len(rec.published) == 1
        env = rec.published[0]
        assert env.topic == TOPIC_TOOL_CALL_STARTED
        assert env.payload["session_id"] == "s1"
        assert env.payload["task_id"] == "t1"
        assert env.payload["name"] == "my-tool"

    @pytest.mark.asyncio
    async def test_publish_tool_call_completed_with_recorder(self) -> None:
        from mahavishnu.core.events.mahavishnu_publisher import (
            TOPIC_TOOL_CALL_COMPLETED,
            publish_tool_call_completed,
        )

        class Recorder:
            def __init__(self) -> None:
                self.published: list[Any] = []

            def publish(self, envelope: Any) -> None:
                self.published.append(envelope)

        rec = Recorder()
        await publish_tool_call_completed(
            worker_id="test",
            task_id="t1",
            outcome="failed",
            session_id="s1",
            publisher=rec,
        )
        assert len(rec.published) == 1
        env = rec.published[0]
        assert env.topic == TOPIC_TOOL_CALL_COMPLETED
        assert env.payload["session_id"] == "s1"
        assert env.payload["outcome"] == "failed"
