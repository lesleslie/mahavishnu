"""Unit tests for mahavishnu/core/self_heal/.

Spec #4: three-layer-self-heal. Phase 2 builds the L1 (transient retry)
and L3 (rule extraction) layers. L2 was already a no-op (C4 fix from a
prior plan) and is pinned here as a regression.

Layer responsibilities:

- L1 (transient retry): bounded retry with exponential backoff for
  transient failures. Sub-second cost in the common case; bounded cost
  on the worst path (3 attempts x max backoff).
- L2 (no-op): deterministic pass-through. Exists so the recovery protocol
  has a marker between L1 and L3, and so future L2 implementations
  (e.g. bounded agentic heal per the spec) can be slotted in without
  re-wiring callers. The marker string is the canonical regression pin.
- L3 (rule extraction): when an operation ultimately fails, the failure
  is summarized into a ``RuleRecord`` and persisted in the in-memory
  ``RuleStore`` (Dhara-backed implementation is a follow-up; v0 uses an
  in-memory store so callers can plug it in immediately).

Substrate status: ``sql_blocked`` (audit log table is gated on Dhara
schema migration; v0 is in-memory). Dhara wiring is a follow-up.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from mahavishnu.core.self_heal import (
    L1RetryExhausted,
    L2Noop,
    RuleRecord,
    RuleStore,
    apply_rule,
    extract_rule,
    l1_retry,
    record_rule,
)


# ---------------------------------------------------------------------------
# L1 - transient retry with exponential backoff
# ---------------------------------------------------------------------------


class TestL1Retry:
    """L1 is a bounded retry decorator for transient failures."""

    @pytest.mark.asyncio
    async def test_returns_first_success_without_retry(self) -> None:
        calls = 0

        async def op() -> str:
            nonlocal calls
            calls += 1
            return "ok"

        result = await l1_retry(op, max_attempts=3, base_backoff=0.001)
        assert result == "ok"
        assert calls == 1

    @pytest.mark.asyncio
    async def test_retries_until_success(self) -> None:
        calls = 0

        async def op() -> str:
            nonlocal calls
            calls += 1
            if calls < 3:
                raise RuntimeError("transient")
            return "eventually-ok"

        result = await l1_retry(op, max_attempts=3, base_backoff=0.001)
        assert result == "eventually-ok"
        assert calls == 3

    @pytest.mark.asyncio
    async def test_raises_after_max_attempts(self) -> None:
        calls = 0

        async def op() -> str:
            nonlocal calls
            calls += 1
            raise RuntimeError(f"always-fail-{calls}")

        with pytest.raises(L1RetryExhausted) as exc_info:
            await l1_retry(op, max_attempts=3, base_backoff=0.001)
        # Last exception is the final attempt's failure.
        assert "always-fail-3" in str(exc_info.value)
        assert calls == 3

    @pytest.mark.asyncio
    async def test_attempts_use_exponential_backoff(self) -> None:
        # Three attempts -> sleeps of base_backoff, 2*base_backoff between them
        # (i.e. after attempt 1 and after attempt 2; no sleep after attempt 3).
        sleep_intervals: list[float] = []

        async def fake_sleep(seconds: float) -> None:
            sleep_intervals.append(seconds)

        calls = 0

        async def op() -> str:
            nonlocal calls
            calls += 1
            if calls < 3:
                raise RuntimeError("transient")
            return "ok"

        await l1_retry(
            op,
            max_attempts=3,
            base_backoff=0.01,
            sleeper=fake_sleep,
        )
        # Three attempts: sleep after attempt 1 and attempt 2; never after final.
        assert sleep_intervals == [0.01, 0.02]
        assert calls == 3

    @pytest.mark.asyncio
    async def test_backoff_uses_real_sleep_by_default(self) -> None:
        # When no sleeper override is given, real ``asyncio.sleep`` runs.
        # Use a small base to keep the test fast.
        calls = 0

        async def op() -> str:
            nonlocal calls
            calls += 1
            if calls < 2:
                raise RuntimeError("transient")
            return "ok"

        start = time.monotonic()
        result = await l1_retry(op, max_attempts=2, base_backoff=0.01)
        elapsed = time.monotonic() - start
        assert result == "ok"
        # One backoff of 0.01s minimum; allow generous slack for CI jitter.
        assert elapsed >= 0.01

    @pytest.mark.asyncio
    async def test_max_attempts_must_be_positive(self) -> None:
        async def op() -> str:
            return "ok"

        with pytest.raises(ValueError):
            await l1_retry(op, max_attempts=0, base_backoff=0.001)


# ---------------------------------------------------------------------------
# L2 - no-op regression pin
# ---------------------------------------------------------------------------


class TestL2Noop:
    """L2 is a deterministic pass-through. The marker is the regression pin."""

    def test_marker_is_canonical_string(self) -> None:
        # Hard pin: if anyone changes the marker without thinking through
        # the downstream consumers (callers grep for this), this test fails.
        assert L2Noop.MARKER == "noop_recovery"

    @pytest.mark.asyncio
    async def test_noop_returns_value_unchanged(self) -> None:
        async def op(x: int) -> int:
            return x * 2

        result = await L2Noop.run(op, 5)
        assert result == 10

    @pytest.mark.asyncio
    async def test_noop_propagates_exceptions(self) -> None:
        async def op() -> None:
            raise RuntimeError("still broken")

        with pytest.raises(RuntimeError, match="still broken"):
            await L2Noop.run(op)


# ---------------------------------------------------------------------------
# L3 - rule extraction and RuleStore
# ---------------------------------------------------------------------------


class TestExtractRule:
    """``extract_rule`` summarises a failure into a RuleRecord."""

    def test_extract_from_exception(self) -> None:
        rule = extract_rule(
            operation="git_push",
            exception=RuntimeError("non-fast-forward"),
            context={"branch": "main", "repo": "/tmp/repo"},
        )
        assert rule.operation == "git_push"
        assert rule.error_type == "RuntimeError"
        assert "non-fast-forward" in rule.message
        assert rule.context == {"branch": "main", "repo": "/tmp/repo"}
        # Stable id so duplicate failures dedupe.
        assert rule.rule_id

    def test_extract_strips_sensitive_context_keys(self) -> None:
        # Defensive: tokens, passwords, secrets must not end up in rules.
        rule = extract_rule(
            operation="http_call",
            exception=RuntimeError("401"),
            context={
                "url": "https://api.example.com/v1",
                "authorization": "Bearer SECRET-TOKEN-VALUE",
                "password": "hunter2",
            },
        )
        # Sensitive keys are scrubbed from the persisted context.
        assert "authorization" not in rule.context
        assert "password" not in rule.context
        assert rule.context["url"] == "https://api.example.com/v1"

    def test_rule_id_is_deterministic_for_same_failure(self) -> None:
        a = extract_rule(
            operation="git_push",
            exception=RuntimeError("non-fast-forward"),
            context={"branch": "main"},
        )
        b = extract_rule(
            operation="git_push",
            exception=RuntimeError("non-fast-forward"),
            context={"branch": "main"},
        )
        assert a.rule_id == b.rule_id


class TestRuleStore:
    """In-memory v0 of the audit log; Dhara-backed implementation follows."""

    def test_record_and_retrieve(self) -> None:
        store = RuleStore()
        rule = RuleRecord(
            rule_id="abc",
            operation="git_push",
            error_type="RuntimeError",
            message="non-fast-forward",
            context={"branch": "main"},
            created_at=0.0,
        )
        record_rule(store, rule)
        assert apply_rule(store, "git_push") is rule

    def test_empty_store_returns_none(self) -> None:
        store = RuleStore()
        assert apply_rule(store, "git_push") is None

    def test_apply_rule_returns_most_recent_for_operation(self) -> None:
        store = RuleStore()
        older = RuleRecord(
            rule_id="older",
            operation="git_push",
            error_type="RuntimeError",
            message="first",
            context={},
            created_at=1.0,
        )
        newer = RuleRecord(
            rule_id="newer",
            operation="git_push",
            error_type="RuntimeError",
            message="second",
            context={},
            created_at=2.0,
        )
        record_rule(store, older)
        record_rule(store, newer)
        # apply_rule returns the most recent rule for the operation.
        assert apply_rule(store, "git_push") is newer

    def test_apply_rule_filters_by_operation(self) -> None:
        store = RuleStore()
        push_rule = RuleRecord(
            rule_id="p",
            operation="git_push",
            error_type="RuntimeError",
            message="push",
            context={},
            created_at=1.0,
        )
        rebase_rule = RuleRecord(
            rule_id="r",
            operation="git_rebase",
            error_type="RuntimeError",
            message="rebase",
            context={},
            created_at=2.0,
        )
        record_rule(store, push_rule)
        record_rule(store, rebase_rule)
        assert apply_rule(store, "git_push") is push_rule
        assert apply_rule(store, "git_rebase") is rebase_rule
        assert apply_rule(store, "git_unrelated") is None

    def test_dedupe_by_rule_id(self) -> None:
        # Recording the same rule twice is idempotent (stable rule_id).
        store = RuleStore()
        rule = RuleRecord(
            rule_id="dedupe-id",
            operation="git_push",
            error_type="RuntimeError",
            message="m",
            context={"branch": "main"},
            created_at=1.0,
        )
        record_rule(store, rule)
        record_rule(store, rule)
        # Only one entry in the underlying list.
        assert len(store.records) == 1


# ---------------------------------------------------------------------------
# Integration: L1 retry exhaustion flows into L3 rule extraction
# ---------------------------------------------------------------------------


class TestLayerComposition:
    """The three layers compose: L1 retry -> L2 no-op -> L3 rule on fail."""

    @pytest.mark.asyncio
    async def test_l1_failure_extracted_to_l3_rule(self) -> None:
        store = RuleStore()
        calls = 0

        async def op() -> str:
            nonlocal calls
            calls += 1
            raise RuntimeError(f"transient-{calls}")

        try:
            await l1_retry(op, max_attempts=3, base_backoff=0.001)
        except L1RetryExhausted as exc:
            # The wrapped exception is the final attempt's failure.
            rule = extract_rule(
                operation="test_op",
                exception=exc.cause,
                context={"branch": "main"},
            )
            record_rule(store, rule)

        recovered = apply_rule(store, "test_op")
        assert recovered is not None
        assert recovered.error_type == "RuntimeError"
        assert "transient-3" in recovered.message
        assert recovered.context == {"branch": "main"}