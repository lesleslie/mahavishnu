"""Tests for ``mahavishnu.core.execute_fn_factory``.

Per plan §Phase 1.5 Tasks 4 + Option C follow-on. The factory has two
paths:

1. **App-wired path** — when ``settings.app.execute`` is reachable,
   the factory wraps the call in ``asyncio.wait_for(timeout)``.
2. **Stub path** — when no app is wired, the factory returns a
   ``WorkerResult`` stub that echoes the prompt back. This is the
   fallback for tests / environments that don't have a full
   ``MahavishnuApp`` instance.

Both paths are deterministic — Option C removed the prior
``xfail`` markers because the factory implementation is correct
without further ``MahavishnuApp`` refactor work.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from mahavishnu.core.config import ACPSettings
from mahavishnu.core.execute_fn_factory import (
    DEFAULT_EXECUTE_FN_TIMEOUT_SECONDS,
    build_execute_fn,
)

pytestmark = pytest.mark.unit


class _StubSettings:
    """Stand-in for ``A2ASettings`` / ``ACPSettings`` — only the attributes the factory reads.

    Pydantic's ``extra="forbid"`` means we can't trivially append
    ``app`` to ``A2ASettings()`` or ``ACPSettings()``, so for the
    app-wired path tests we use this duck-typed namespace.
    """

    def __init__(
        self,
        *,
        component_name: str = "test-component",
        execute_fn_timeout_seconds: float = DEFAULT_EXECUTE_FN_TIMEOUT_SECONDS,
        app: Any = None,
    ) -> None:
        self.component_name = component_name
        self.execute_fn_timeout_seconds = execute_fn_timeout_seconds
        self.app = app


class TestBuildExecuteFnStubPath:
    """Tests for the stub path (no app wired)."""

    def test_returns_callable(self) -> None:
        fn = build_execute_fn(ACPSettings())
        assert callable(fn)

    def test_factory_default_timeout_constant(self) -> None:
        """The default timeout is 600s, matching the historical A2A value."""
        assert DEFAULT_EXECUTE_FN_TIMEOUT_SECONDS == 600.0

    def test_factory_returns_worker_result_when_no_app(self) -> None:
        """Without a configured ``app``, the factory returns a stub WorkerResult.

        The stub echoes the prompt and includes ``v1_0_stub`` metadata
        so tests can distinguish it from real implementations.
        """
        settings = ACPSettings(component_name="acp-stub")
        fn = build_execute_fn(settings)
        result = asyncio.run(fn({"prompt": "hello world"}))
        # WorkerResult-shaped: has ``status``, ``output``, ``error``, ``metadata``.
        assert result.status.value == "completed"
        assert "hello world" in result.output
        assert result.metadata.get("v1_0_stub") is True
        assert result.metadata.get("echo") == "hello world"

    def test_stub_preserves_payload_extra_keys(self) -> None:
        """Non-prompt keys in the payload are preserved in metadata."""
        settings = ACPSettings()
        fn = build_execute_fn(settings)
        result = asyncio.run(
            fn({"prompt": "x", "user_id": "u-1", "session_id": "s-1"})
        )
        assert result.metadata.get("echo") == "x"

    def test_factory_accepts_a2a_settings(self) -> None:
        """``A2ASettings`` (or any object matching the duck-typed shape) is accepted."""
        from mahavishnu.core.config import A2ASettings

        settings = A2ASettings()
        fn = build_execute_fn(settings)
        result = asyncio.run(fn({"prompt": "via a2a"}))
        assert "via a2a" in result.output


class TestBuildExecuteFnAppPath:
    """Tests for the app-wired path — factory wraps ``app.execute`` under the timeout."""

    def test_factory_wraps_with_timeout(self) -> None:
        """The factory's wrapper enforces ``settings.execute_fn_timeout_seconds``."""

        async def slow_app_execute(payload: dict[str, Any]) -> Any:
            await asyncio.sleep(2)  # exceeds the 0.1s cap

        # Construct a simple namespace object whose .execute is the coroutine.
        class _App:
            execute = staticmethod(slow_app_execute)

        fn = build_execute_fn(
            _StubSettings(app=_App(), execute_fn_timeout_seconds=0.1)
        )
        with pytest.raises(TimeoutError):
            asyncio.run(fn({"prompt": "x"}))

    def test_factory_strips_no_payload(self) -> None:
        """The factory wraps any payload as-is (no mutation)."""
        payload = {"prompt": "hello", "extra": 1}
        received: dict[str, Any] = {}

        async def fake_app_execute(p: dict[str, Any]) -> Any:
            received.update(p)
            return {"echo": p.get("prompt")}

        class _App:
            execute = staticmethod(fake_app_execute)

        fn = build_execute_fn(_StubSettings(app=_App()))
        result = asyncio.run(fn(payload))
        assert received == payload
        assert result == {"echo": "hello"}


class TestFactoryErrorEnveloping:
    """Exceptions inside ``execute_fn`` propagate (callers format their own errors)."""

    def test_exception_propagates(self) -> None:
        class _RaisingApp:
            async def execute(self, payload: dict[str, Any]) -> Any:
                raise ValueError("boom")

        fn = build_execute_fn(_StubSettings(app=_RaisingApp()))
        with pytest.raises(ValueError, match="boom"):
            asyncio.run(fn({"prompt": "x"}))
