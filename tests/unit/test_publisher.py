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

    async def test_rejects_envelope_without_topic_or_event_type(self) -> None:
        """An envelope carrying neither wire shape is rejected.

        The previous contract fell back to ``getattr(envelope, 'topic',
        'unknown')`` and published it anyway. An envelope with no topic
        cannot be published (the bridge needs one), and labelling it
        ``"unknown"`` hid the failure behind a constant metric label.
        """
        publisher = AsyncMock()
        publisher.publish = AsyncMock(return_value=None)
        set_publisher(publisher)
        envelope: Any = object()
        result = await safe_publish(envelope)
        assert result is False
        publisher.publish.assert_not_awaited()


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


class _RecordingBridge:
    """Duck-typed stand-in for Oneiric's ``EventBridge``.

    Captures the ``(topic, payload, headers)`` triple the real
    ``EventBridgePublisher`` forwards, so the test can assert on the
    wire shape without a live EventBridge.
    """

    def __init__(self) -> None:
        self.emitted: list[tuple[str, dict[str, Any], dict[str, Any]]] = []

    async def emit(
        self,
        topic: str,
        payload: dict[str, Any],
        headers: dict[str, Any],
    ) -> None:
        self.emitted.append((topic, payload, headers))


def _publish_metric_samples() -> dict[tuple[str, str], float]:
    """Return the ``(envelope_topic, result) -> value`` map of the counter.

    Read straight from the Prometheus registry, not from log capture:
    ``publisher.py`` uses the oneiric/structlog logger flavour, for
    which ``caplog`` is void.
    """
    from mahavishnu.core._producer_metrics import EVENTBRIDGE_PUBLISH_TOTAL

    samples: dict[tuple[str, str], float] = {}
    for metric in EVENTBRIDGE_PUBLISH_TOTAL.collect():
        for sample in metric.samples:
            if sample.name.endswith("_created"):
                continue
            key = (sample.labels["envelope_topic"], sample.labels["result"])
            samples[key] = sample.value
    return samples


def _changed_samples(
    before: dict[tuple[str, str], float],
    after: dict[tuple[str, str], float],
) -> set[tuple[str, str]]:
    """Return the label pairs whose counter value changed between snapshots."""
    return {
        key
        for key in set(before) | set(after)
        if before.get(key, 0.0) != after.get(key, 0.0)
    }


class TestSafePublishCanonicalEnvelope:
    """F30 regression: safe_publish must hand the publisher a canonical
    Oneiric envelope.

    The publisher protocol
    (``mahavishnu.core.events.canonical.OneiricEventPublisherProtocol``)
    requires a Oneiric envelope (``topic`` / ``payload`` / ``headers``).
    ``safe_publish`` used to forward the Mahavishnu Pydantic envelope
    unchanged, so every publish raised ``AttributeError`` inside the
    publisher and was swallowed by the bare ``except Exception``.
    """

    async def test_real_publisher_receives_canonical_wire_shape(self) -> None:
        from mahavishnu.core.events.contract import create_event_envelope
        from mahavishnu.core.events.eventbridge_adapter import EventBridgePublisher

        bridge = _RecordingBridge()
        set_publisher(EventBridgePublisher(bridge))
        envelope = create_event_envelope(
            event_type="ecosystem.event.received",
            source="mahavishnu.webhooks.ecosystem.git-monitor",
            payload={"source": "git-monitor", "data": {"pr_url": "https://x/y"}},
            metadata={"severity": "info"},
        )

        result = await safe_publish(envelope)

        assert result is True
        assert len(bridge.emitted) == 1
        topic, payload, headers = bridge.emitted[0]
        # The Mahavishnu ``event_type`` becomes the Oneiric ``topic``.
        assert topic == "ecosystem.event.received"
        assert payload == {"source": "git-monitor", "data": {"pr_url": "https://x/y"}}
        assert headers["source"] == "mahavishnu.webhooks.ecosystem.git-monitor"
        assert headers["event_id"] == str(envelope.event_id)
        assert headers["version"] == envelope.version
        assert headers["timestamp"] == envelope.timestamp.isoformat()
        assert headers["metadata"] == {"severity": "info"}

    async def test_metric_label_carries_the_real_topic(self) -> None:
        from mahavishnu.core.events.contract import create_event_envelope
        from mahavishnu.core.events.eventbridge_adapter import EventBridgePublisher

        bridge = _RecordingBridge()
        set_publisher(EventBridgePublisher(bridge))
        envelope = create_event_envelope(
            event_type="f30.metric.label.topic",
            source="mahavishnu.test.publisher",
            payload={"k": "v"},
        )

        before = _publish_metric_samples()

        assert await safe_publish(envelope) is True

        after = _publish_metric_samples()
        # Exactly one label pair moved, and it carries the real topic.
        # The old code labelled every publish "unknown" (in whichever
        # result bucket), so this also pins the label's *value* — not
        # merely that some counter moved.
        assert _changed_samples(before, after) == {
            ("f30.metric.label.topic", "success")
        }

    async def test_skip_path_label_carries_the_real_topic(self) -> None:
        """The skip path (no publisher wired) also labels the real topic.

        ``skip`` is the default configuration — ``EventBridgeConfig``
        ships ``enabled=False`` / ``dry_run=True`` — so this is the
        branch that was reporting ``"unknown"`` in every live
        deployment.
        """
        from mahavishnu.core.events.contract import create_event_envelope

        set_publisher(None)
        envelope = create_event_envelope(
            event_type="f30.metric.label.skip",
            source="mahavishnu.test.publisher",
            payload={"k": "v"},
        )

        before = _publish_metric_samples()

        assert await safe_publish(envelope) is False

        after = _publish_metric_samples()
        assert _changed_samples(before, after) == {("f30.metric.label.skip", "skip")}

    async def test_canonical_envelope_passes_through_unchanged(self) -> None:
        """An already-canonical envelope is forwarded as-is.

        ``safe_publish`` is public API: callers that already hold a
        Oneiric envelope (e.g. the ``mahavishnu_publisher`` workflow
        path) must not have it mangled by a second conversion.
        """
        from mahavishnu.core.events.canonical import create_oneiric_envelope
        from mahavishnu.core.events.eventbridge_adapter import EventBridgePublisher

        bridge = _RecordingBridge()
        set_publisher(EventBridgePublisher(bridge))
        canonical = create_oneiric_envelope(
            topic="workflow.started",
            payload={"workflow_id": "wf_1"},
            source="mahavishnu",
        )

        result = await safe_publish(canonical)

        assert result is True
        assert len(bridge.emitted) == 1
        topic, payload, headers = bridge.emitted[0]
        assert topic == "workflow.started"
        assert payload == {"workflow_id": "wf_1"}
        assert headers is canonical.headers
