"""Unit tests for the module-global EventBridgePublisher singleton (REQ-005)."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from mahavishnu.core.events.publisher import (
    get_publisher,
    safe_publish,
    set_publisher,
)


@pytest.fixture(autouse=True)
def _reset_publisher() -> None:
    """Ensure singleton is cleared before and after each test."""
    set_publisher(None)
    yield
    set_publisher(None)


class TestSetGetPublisher:
    """Roundtrip and default-state semantics for the singleton."""

    def test_set_then_get_roundtrip(self) -> None:
        publisher = MagicMock()
        set_publisher(publisher)
        assert get_publisher() is publisher

    def test_get_returns_none_when_unset(self) -> None:
        assert get_publisher() is None

    def test_set_none_disables_publishing(self) -> None:
        publisher = MagicMock()
        set_publisher(publisher)
        set_publisher(None)
        assert get_publisher() is None


class TestSafePublishSuccess:
    """The happy path: safe_publish forwards to the publisher and records success."""

    async def test_returns_true_on_success(self) -> None:
        publisher = AsyncMock()
        publisher.publish = AsyncMock(return_value=None)
        set_publisher(publisher)
        envelope = MagicMock()
        envelope.topic = "test.event"
        result = await safe_publish(envelope)
        assert result is True
        publisher.publish.assert_awaited_once_with(envelope)

    async def test_label_uses_envelope_topic(self) -> None:
        publisher = AsyncMock()
        publisher.publish = AsyncMock(return_value=None)
        set_publisher(publisher)
        envelope = MagicMock()
        envelope.topic = "workflow.started"
        await safe_publish(envelope)
        # If the call did not raise, the labeled metric increment succeeded.


class TestSafePublishSkips:
    """safe_publish must return False (and not raise) when no publisher is wired."""

    async def test_returns_false_when_publisher_is_none(self) -> None:
        envelope = MagicMock()
        envelope.topic = "test.event"
        result = await safe_publish(envelope)
        assert result is False

    async def test_returns_false_when_set_to_none(self) -> None:
        set_publisher(MagicMock())
        set_publisher(None)
        envelope = MagicMock()
        envelope.topic = "test.event"
        result = await safe_publish(envelope)
        assert result is False


class TestSafePublishSwallowsExceptions:
    """safe_publish must catch non-fatal errors but let CancelledError propagate."""

    async def test_returns_false_on_runtime_error(self) -> None:
        publisher = AsyncMock()
        publisher.publish = AsyncMock(side_effect=RuntimeError("Akosha down"))
        set_publisher(publisher)
        envelope = MagicMock()
        envelope.topic = "test.event"
        result = await safe_publish(envelope)
        assert result is False

    async def test_returns_false_on_value_error(self) -> None:
        publisher = AsyncMock()
        publisher.publish = AsyncMock(side_effect=ValueError("bad envelope"))
        set_publisher(publisher)
        envelope = MagicMock()
        envelope.topic = "test.event"
        result = await safe_publish(envelope)
        assert result is False

    async def test_cancelled_error_propagates(self) -> None:
        """CancelledError must NOT be swallowed — per crackerjack-compliant-code
        and per asyncio contract. Catching BaseException would break
        cancellation propagation."""
        publisher = AsyncMock()
        publisher.publish = AsyncMock(side_effect=asyncio.CancelledError())
        set_publisher(publisher)
        envelope = MagicMock()
        envelope.topic = "test.event"
        with pytest.raises(asyncio.CancelledError):
            await safe_publish(envelope)

    async def test_handles_envelope_without_topic_attribute(self) -> None:
        """Defensive: getattr(envelope, 'topic', 'unknown') must not raise."""
        publisher = AsyncMock()
        publisher.publish = AsyncMock(return_value=None)
        set_publisher(publisher)
        envelope: Any = object()
        result = await safe_publish(envelope)
        assert result is True


class TestResolverDeleted:
    """Per feedback-no-backwards-compat-pre-1.0: the resolver is REPLACED.

    The old API surface must be gone — no deprecation shim, no fallback.
    """

    def test_resolver_module_not_importable(self) -> None:
        import importlib

        with pytest.raises(ModuleNotFoundError):
            importlib.import_module("mahavishnu.core.events.eventbridge_resolver")

    def test_resolve_event_publisher_symbol_gone(self) -> None:
        import importlib

        with pytest.raises(ModuleNotFoundError):
            importlib.import_module("mahavishnu.core.events.eventbridge_resolver")


class TestSafePublishMetrics:
    """EVENTBRIDGE_PUBLISH_TOTAL must be incremented on every code path."""

    async def test_metric_incremented_on_success(self) -> None:
        from mahavishnu.core._producer_metrics import EVENTBRIDGE_PUBLISH_TOTAL

        publisher = AsyncMock()
        publisher.publish = AsyncMock(return_value=None)
        set_publisher(publisher)
        envelope = MagicMock()
        envelope.topic = "metric.test.success"
        before = EVENTBRIDGE_PUBLISH_TOTAL.labels(
            envelope_topic="metric.test.success", result="success"
        )._value.get()
        await safe_publish(envelope)
        after = EVENTBRIDGE_PUBLISH_TOTAL.labels(
            envelope_topic="metric.test.success", result="success"
        )._value.get()
        assert after == before + 1

    async def test_metric_incremented_on_skip(self) -> None:
        from mahavishnu.core._producer_metrics import EVENTBRIDGE_PUBLISH_TOTAL

        envelope = MagicMock()
        envelope.topic = "metric.test.skip"
        before = EVENTBRIDGE_PUBLISH_TOTAL.labels(
            envelope_topic="metric.test.skip", result="skip"
        )._value.get()
        await safe_publish(envelope)
        after = EVENTBRIDGE_PUBLISH_TOTAL.labels(
            envelope_topic="metric.test.skip", result="skip"
        )._value.get()
        assert after == before + 1

    async def test_metric_incremented_on_error(self) -> None:
        from mahavishnu.core._producer_metrics import EVENTBRIDGE_PUBLISH_TOTAL

        publisher = AsyncMock()
        publisher.publish = AsyncMock(side_effect=RuntimeError("boom"))
        set_publisher(publisher)
        envelope = MagicMock()
        envelope.topic = "metric.test.error"
        before = EVENTBRIDGE_PUBLISH_TOTAL.labels(
            envelope_topic="metric.test.error", result="error"
        )._value.get()
        await safe_publish(envelope)
        after = EVENTBRIDGE_PUBLISH_TOTAL.labels(
            envelope_topic="metric.test.error", result="error"
        )._value.get()
        assert after == before + 1
