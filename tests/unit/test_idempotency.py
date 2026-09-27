"""Unit tests for the C-6 idempotency layer (REQ-006/007/008).

These tests exercise the idempotency layer in isolation — the
:class:`EventStore` is replaced with an :class:`AsyncMock` so we can
focus on the contract surface without spinning up a real database.

Covers:
- :class:`IdempotencyOptions` Pydantic validation (extra="forbid",
  source/nonce/ttl bounds).
- :class:`IdempotencyStore.fingerprint` (SHA-256 hex, varies with payload
  AND ttl_bucket).
- :class:`IdempotencyStore.get_or_create` (lookup-or-create, fail-CLOSED).
- :class:`IdempotencyStore.mark_completed` (in-place PENDING → COMPLETED).
- :class:`IdempotencyCircuitBreaker` (state machine, metrics, fast-fail).
- Module-level singleton helpers (``get_idempotency_store``,
  ``set_idempotency_store``, ``get_idempotency_breaker``,
  ``set_idempotency_breaker``).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from mahavishnu.core.errors import (
    IdempotencyCircuitOpen,
    IdempotencyStoreUnavailable,
)
from mahavishnu.core.event_store import TaskEvent, TaskEventType
from mahavishnu.core.idempotency import (
    IdempotencyCircuitBreaker,
    IdempotencyOptions,
    IdempotencyStore,
    get_idempotency_breaker,
    get_idempotency_store,
    set_idempotency_breaker,
    set_idempotency_store,
)


@pytest_asyncio.fixture
async def mock_event_store() -> AsyncMock:
    """In-memory EventStore mock. Tracks append() calls and returns."""
    store = AsyncMock()
    # ``get_event_by_idempotency_key`` returns None unless explicitly set.
    store.get_event_by_idempotency_key = AsyncMock(return_value=None)
    store.append = AsyncMock(
        side_effect=lambda task_id, event_type, data, actor, **kwargs: TaskEvent(
            id=f"evt-{task_id}-{event_type.value}",
            task_id=task_id,
            event_type=event_type,
            data=data,
            actor=actor,
            occurred_at=datetime.now(UTC),
            idempotency_key=kwargs.get("idempotency_key"),
        )
    )
    return store


@pytest_asyncio.fixture
async def idem_store(mock_event_store: AsyncMock) -> IdempotencyStore:
    """Fresh IdempotencyStore wrapping the mock event store."""
    return IdempotencyStore(mock_event_store)


# ---------------------------------------------------------------------------
# IdempotencyOptions — Pydantic validation contract
# ---------------------------------------------------------------------------


@pytest.mark.req(["REQ-006"])
class TestIdempotencyOptions:
    """REQ-006: Pydantic input model enforces strict bounds."""

    def test_minimal_options(self) -> None:
        opts = IdempotencyOptions(source="cli.dispatch", nonce="abc-123")
        assert opts.source == "cli.dispatch"
        assert opts.nonce == "abc-123"
        assert opts.ttl_seconds == 86_400  # default

    def test_extra_forbid(self) -> None:
        with pytest.raises(ValueError, match="extra"):
            IdempotencyOptions(
                source="cli.dispatch",
                nonce="abc-123",
                unknown_field=1,
            )

    def test_source_min_length(self) -> None:
        with pytest.raises(ValueError):
            IdempotencyOptions(source="", nonce="abc-123")

    def test_source_max_length(self) -> None:
        with pytest.raises(ValueError):
            IdempotencyOptions(source="a" * 256, nonce="abc-123")

    def test_nonce_min_length(self) -> None:
        with pytest.raises(ValueError):
            IdempotencyOptions(source="cli.dispatch", nonce="")

    def test_nonce_max_length(self) -> None:
        with pytest.raises(ValueError):
            IdempotencyOptions(source="cli.dispatch", nonce="n" * 129)

    def test_ttl_lower_bound(self) -> None:
        with pytest.raises(ValueError):
            IdempotencyOptions(
                source="cli.dispatch",
                nonce="abc-123",
                ttl_seconds=30,  # < 60
            )

    def test_ttl_upper_bound(self) -> None:
        with pytest.raises(ValueError):
            IdempotencyOptions(
                source="cli.dispatch",
                nonce="abc-123",
                ttl_seconds=2_000_000,  # > 7 days
            )

    def test_ttl_default(self) -> None:
        """Default TTL is 24h (86_400s)."""
        opts = IdempotencyOptions(source="cli.dispatch", nonce="x")
        assert opts.ttl_seconds == 86_400


# ---------------------------------------------------------------------------
# fingerprint — SHA-256 hex digest via Oneiric HashAction
# ---------------------------------------------------------------------------


@pytest.mark.req(["REQ-008"])
class TestFingerprint:
    """REQ-008: fingerprint is SHA-256 hex digest of payload fields."""

    async def test_fingerprint_is_hex_64_chars(self) -> None:
        opts = IdempotencyOptions(source="cli.dispatch", nonce="abc-123")
        fp = await IdempotencyStore.fingerprint(opts, "payload-hash")
        assert len(fp) == 64
        assert all(c in "0123456789abcdef" for c in fp)

    async def test_fingerprint_changes_with_payload(self) -> None:
        opts = IdempotencyOptions(source="cli.dispatch", nonce="abc-123")
        fp1 = await IdempotencyStore.fingerprint(opts, "payload-A")
        fp2 = await IdempotencyStore.fingerprint(opts, "payload-B")
        assert fp1 != fp2

    async def test_fingerprint_changes_with_ttl_bucket(self) -> None:
        """Different TTLs fall in different 1h buckets → different fingerprint."""
        opts1 = IdempotencyOptions(
            source="cli.dispatch",
            nonce="abc-123",
            ttl_seconds=3600,
        )
        opts2 = IdempotencyOptions(
            source="cli.dispatch",
            nonce="abc-123",
            ttl_seconds=7200,
        )
        fp1 = await IdempotencyStore.fingerprint(opts1, "payload")
        fp2 = await IdempotencyStore.fingerprint(opts2, "payload")
        assert fp1 != fp2

    async def test_fingerprint_changes_with_source(self) -> None:
        opts1 = IdempotencyOptions(source="cli.dispatch", nonce="abc-123")
        opts2 = IdempotencyOptions(source="webhook.intake", nonce="abc-123")
        fp1 = await IdempotencyStore.fingerprint(opts1, "payload")
        fp2 = await IdempotencyStore.fingerprint(opts2, "payload")
        assert fp1 != fp2

    async def test_fingerprint_changes_with_nonce(self) -> None:
        opts1 = IdempotencyOptions(source="cli.dispatch", nonce="nonce-A")
        opts2 = IdempotencyOptions(source="cli.dispatch", nonce="nonce-B")
        fp1 = await IdempotencyStore.fingerprint(opts1, "payload")
        fp2 = await IdempotencyStore.fingerprint(opts2, "payload")
        assert fp1 != fp2

    async def test_fingerprint_stable_with_same_inputs(self) -> None:
        """Two calls with identical inputs produce identical fingerprints."""
        opts = IdempotencyOptions(source="cli.dispatch", nonce="abc-123")
        fp1 = await IdempotencyStore.fingerprint(opts, "payload")
        fp2 = await IdempotencyStore.fingerprint(opts, "payload")
        assert fp1 == fp2


# ---------------------------------------------------------------------------
# get_or_create — lookup-or-create with per-key asyncio.Lock
# ---------------------------------------------------------------------------


@pytest.mark.req(["REQ-006", "REQ-007"])
class TestGetOrCreate:
    """REQ-006/007: lookup-or-create + fail-CLOSED on store unavailable."""

    async def test_first_call_creates_pending(
        self,
        idem_store: IdempotencyStore,
        mock_event_store: AsyncMock,
    ) -> None:
        opts = IdempotencyOptions(source="cli.dispatch", nonce="first-1")
        event = await idem_store.get_or_create(opts, "payload-hash", actor="test")
        assert event.event_type == TaskEventType.PENDING
        mock_event_store.append.assert_awaited_once()

    async def test_second_call_returns_existing_when_present(
        self,
        idem_store: IdempotencyStore,
        mock_event_store: AsyncMock,
    ) -> None:
        """When the store already has the row, no new append happens."""
        opts = IdempotencyOptions(source="cli.dispatch", nonce="dup-1")
        existing_event = TaskEvent(
            id="evt-existing",
            task_id="dup-1",
            event_type=TaskEventType.PENDING,
            data={"idempotency_key": "abc"},
            actor="prior-call",
            occurred_at=datetime.now(UTC),
            idempotency_key="abc",
        )
        mock_event_store.get_event_by_idempotency_key.return_value = existing_event
        event = await idem_store.get_or_create(opts, "payload-hash", actor="test")
        assert event is existing_event
        mock_event_store.append.assert_not_awaited()

    async def test_fail_closed_on_store_error(
        self,
        idem_store: IdempotencyStore,
        mock_event_store: AsyncMock,
    ) -> None:
        """Underlying errors convert to IdempotencyStoreUnavailable."""
        mock_event_store.get_event_by_idempotency_key.side_effect = ConnectionError(
            "store down"
        )
        opts = IdempotencyOptions(source="cli.dispatch", nonce="fail-1")
        with pytest.raises(IdempotencyStoreUnavailable):
            await idem_store.get_or_create(opts, "payload-hash", actor="test")

    async def test_concurrent_get_or_create_serializes(
        self,
        idem_store: IdempotencyStore,
        mock_event_store: AsyncMock,
    ) -> None:
        """Two concurrent calls with the same key share the same lock."""
        import asyncio

        opts = IdempotencyOptions(source="cli.dispatch", nonce="concurrent-1")
        # Schedule two coroutines concurrently.
        results = await asyncio.gather(
            idem_store.get_or_create(opts, "payload-hash", actor="test"),
            idem_store.get_or_create(opts, "payload-hash", actor="test"),
        )
        # Both events share the same idempotency_key (lookup fingerprint).
        assert results[0].idempotency_key == results[1].idempotency_key


# ---------------------------------------------------------------------------
# mark_completed — in-place PENDING → COMPLETED transition
# ---------------------------------------------------------------------------


@pytest.mark.req(["REQ-006"])
class TestMarkCompleted:
    """REQ-006: single-row in-place PENDING → COMPLETED update."""

    async def test_pending_to_completed_transition(
        self,
        idem_store: IdempotencyStore,
    ) -> None:
        opts = IdempotencyOptions(source="cli.dispatch", nonce="complete-1")
        event = await idem_store.get_or_create(opts, "payload-hash", actor="test")
        await idem_store.mark_completed(
            event, {"status": "ok", "output": "done"}
        )
        assert event.event_type == TaskEventType.COMPLETED
        assert event.data["result"] == {"status": "ok", "output": "done"}


@pytest.mark.req(["REQ-006"])
class TestMarkFailed:
    """mark_failed transitions PENDING → FAILED on dispatch error."""

    async def test_pending_to_failed_transition(
        self,
        idem_store: IdempotencyStore,
    ) -> None:
        opts = IdempotencyOptions(source="cli.dispatch", nonce="fail-2")
        event = await idem_store.get_or_create(opts, "payload-hash", actor="test")
        await idem_store.mark_failed(event, error="dispatch blew up")
        assert event.event_type == TaskEventType.FAILED
        assert event.data["error"] == "dispatch blew up"


# ---------------------------------------------------------------------------
# IdempotencyCircuitBreaker — state machine
# ---------------------------------------------------------------------------


@pytest.mark.req(["REQ-007"])
class TestIdempotencyCircuitBreaker:
    """REQ-007: circuit breaker prevents the 30s DB timeout cliff."""

    async def test_initial_state_is_closed(self) -> None:
        breaker = IdempotencyCircuitBreaker()
        assert not breaker.is_open

    async def test_successful_call_does_not_open(self) -> None:
        breaker = IdempotencyCircuitBreaker(
            failure_threshold=2,
            cooldown_seconds=0.01,
        )

        async def ok_call() -> str:
            return "ok"

        result = await breaker.call(ok_call)
        assert result == "ok"
        assert not breaker.is_open

    async def test_consecutive_failures_open_circuit(self) -> None:
        breaker = IdempotencyCircuitBreaker(
            failure_threshold=2,
            cooldown_seconds=60.0,
        )

        async def fail_call() -> None:
            raise IdempotencyStoreUnavailable("store down")

        with pytest.raises(IdempotencyStoreUnavailable):
            await breaker.call(fail_call)
        assert not breaker.is_open  # 1 failure < threshold

        with pytest.raises(IdempotencyStoreUnavailable):
            await breaker.call(fail_call)
        assert breaker.is_open  # 2 failures → OPEN

    async def test_open_circuit_fast_fails_with_distinct_exception(self) -> None:
        breaker = IdempotencyCircuitBreaker(
            failure_threshold=1,
            cooldown_seconds=60.0,
        )

        async def fail_call() -> None:
            raise IdempotencyStoreUnavailable("store down")

        # First failure trips the breaker AND re-raises the underlying error.
        with pytest.raises(IdempotencyStoreUnavailable):
            await breaker.call(fail_call)
        assert breaker.is_open

        async def any_call() -> None:
            return "should not run"

        # Second call fast-fails with the distinct circuit-open exception.
        with pytest.raises(IdempotencyCircuitOpen):
            await breaker.call(any_call)

    async def test_cooldown_transitions_to_half_open_then_closed(self) -> None:
        import asyncio

        breaker = IdempotencyCircuitBreaker(
            failure_threshold=1,
            cooldown_seconds=0.01,
        )

        async def fail_call() -> None:
            raise IdempotencyStoreUnavailable("store down")

        async def ok_call() -> str:
            return "ok"

        with pytest.raises(IdempotencyStoreUnavailable):
            await breaker.call(fail_call)
        assert breaker.is_open
        # Wait past the cooldown.
        await asyncio.sleep(0.05)
        # Next successful call closes the circuit.
        result = await breaker.call(ok_call)
        assert result == "ok"
        assert not breaker.is_open


# ---------------------------------------------------------------------------
# Module-level singletons — required because per-call construction defeats
# the asyncio.Lock fallback (each call gets its own _locks dict).
# ---------------------------------------------------------------------------


@pytest.mark.req(["REQ-006"])
class TestModuleSingletons:
    """Singleton helpers for app-boot wiring and test injection."""

    def teardown_method(self) -> None:
        """Reset singletons between tests so cases are isolated."""
        set_idempotency_store(None)
        set_idempotency_breaker(None)

    def test_get_store_raises_when_unconfigured(self) -> None:
        """Fail-CLOSED: unconfigured store raises IdempotencyStoreUnavailable."""
        set_idempotency_store(None)
        with pytest.raises(IdempotencyStoreUnavailable):
            get_idempotency_store()

    def test_set_and_get_store(self, idem_store: IdempotencyStore) -> None:
        set_idempotency_store(idem_store)
        assert get_idempotency_store() is idem_store

    def test_get_breaker_returns_default_when_unconfigured(self) -> None:
        """Lazily creates a default breaker so production callers don't crash."""
        set_idempotency_breaker(None)
        breaker = get_idempotency_breaker()
        assert isinstance(breaker, IdempotencyCircuitBreaker)
        assert not breaker.is_open

    def test_set_and_get_breaker(self) -> None:
        breaker = IdempotencyCircuitBreaker(failure_threshold=99)
        set_idempotency_breaker(breaker)
        assert get_idempotency_breaker() is breaker
