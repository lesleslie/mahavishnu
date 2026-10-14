# C-5: EventBridgePublisher module-global singleton (WP-precond-2)

**REQ-NNN:** REQ-005 — EventBridgePublisher singleton module (replaces server-scoped path; single-API)
**Risk:** Medium (replaces existing API surface; downstream callers must migrate; no dual-API per `feedback-no-backwards-compat-pre-1.0`)
**Blocks:** Every wire-up that publishes to Akosha (C-6 idempotency, C-10 ecosystem intake, C-13 crackerjack review-pr)
**Direct-to-main commit:** Yes (per `feedback-no-backwards-compat-pre-1.0` + `bodai-pre-1.0-merge-policy`).

**Niche fit:** Per [`docs/adr/0001-mahavishnu-niche.md`](../adr/0001-mahavishnu-niche.md), this plan anchors Mahavishnu as LLM control plane + repo orchestrator + multi-engine + harness-agnostic. The three-question filter (deepens? Bodai integration? no source-tool competition?) was applied at planning time.

**Status:** Draft — round-4 corrections baked in (single-API, no dual-mode).

## Goal

Provide a module-global singleton publisher so wire-ups have a real acquisition point. **Per the no-backcompat policy, the module-global replaces the existing server-scoped `eventbridge_resolver.resolve_event_publisher(server)` path entirely** — both cannot coexist; one replaces the other. The dual-API shim that would normally exist during a transition window is explicitly dropped.

The existing `mahavishnu/core/events/eventbridge_resolver.py` (`eventbridge_resolver.resolve_event_publisher(server)`) is **deleted** in this commit. Downstream callers that previously imported from the resolver now import from the new singleton module.

## Pre-flight checks

1. **`oneiric.logging.getLogger` importable.** `python -c "from oneiric.core.logging import get_logger"`. The plan uses `get_logger(__name__)` per crackerjack-compliant-code ("Use the Oneiric logger — not stdlib `logging`").

1. **Existing publisher implementation exists.** Verify `mahavishnu/core/events/eventbridge_adapter.py` exposes `EventBridgePublisher` with a `publish(envelope) -> None` async method. The singleton wraps this — it does not reimplement the publish logic.

   FIX round-6: `mahavishnu/core/events/mahavishnu_publisher.py` ALSO exists (9593 bytes; exports `publish_workflow_started`, `publish_workflow_completed`, `publish_workflow_failed`, etc.) and is imported by `mahavishnu/websocket/server.py:656-674`. The new `publisher.py` (added by this plan) and `mahavishnu_publisher.py` are distinct modules. **C-5 does NOT migrate or delete `mahavishnu_publisher.py`** — that module is workflow-publish-specific (publish_workflow_started/completed/failed) and serves a different concern than the singleton helper (`safe_publish` for arbitrary envelopes). Both modules coexist in `mahavishnu/core/events/`. **Acceptance criterion #2.5: both `publisher.py` and `mahavishnu_publisher.py` exist; no import collision; `websocket/server.py` continues to import from `mahavishnu_publisher.py`.**

1. **`mahavishnu/factories.py:_wire_eventbridge_publisher` exists.** This is where `set_publisher()` will be called at app boot.

   FIX round-6: the real signature is `_wire_eventbridge_publisher(server)` (synchronous, takes a server arg, calls `resolve_event_publisher(settings, server=server, bridge=bridge)` internally). The plan's Before/After snippets showed `(server) -> EventBridgePublisher` which is correct; the new version is `_wire_eventbridge_publisher(server) -> EventBridgePublisher` (synchronous, NOT async, returns the publisher instance) and calls `set_publisher(publisher)` as a side effect.

1. **All downstream callers of `resolve_event_publisher(server)` identified.** `grep -r "resolve_event_publisher" mahavishnu/` to enumerate the migration scope. Each caller must be updated to use `get_publisher()` instead.

   FIX round-6: `tests/unit/test_eventbridge_resolver.py` exists (5 test methods, imports `resolve_event_publisher`). When C-5 deletes `eventbridge_resolver.py`, this test file becomes an orphan. **C-5 must also DELETE `tests/unit/test_eventbridge_resolver.py`** (it tests the deleted module's SUT — there is nothing left to test). Acceptance criterion updated: the test file is removed in the same commit.

1. **C-1 has landed.** The settings section referenced in `factories.py` (likely `eventbridge:` or similar) must exist for `set_publisher()` to wire at boot.

1. **C-3 has landed.** `IdempotencyStoreUnavailable` exception exists (used by C-6's fail-closed path; not by C-5 directly, but related wiring).

## File-by-file changes

### 1. `mahavishnu/core/events/publisher.py` — new file (~50 LoC)

The entire singleton module:

```python
"""Module-global EventBridgePublisher singleton.

Per feedback-no-backwards-compat-pre-1.0, this replaces the server-scoped
eventbridge_resolver.resolve_event_publisher(server) path entirely. There is
no dual-API; downstream callers MUST use get_publisher() / safe_publish().

Wire at app boot via set_publisher() in mahavishnu/factories.py:_wire_eventbridge_publisher.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from oneiric.core.logging import get_logger

if TYPE_CHECKING:
    from mahavishnu.core.events.contract import OneiricEventEnvelope
    from mahavishnu.core.events.eventbridge_adapter import EventBridgePublisher

_publisher: EventBridgePublisher | None = None
logger = get_logger(__name__)


def set_publisher(publisher: EventBridgePublisher | None) -> None:
    """Inject the publisher singleton. Called by mahavishnu/factories.py at app boot.
    Passing None disables publishing — useful for tests and degraded mode."""
    global _publisher
    _publisher = publisher


def get_publisher() -> EventBridgePublisher | None:
    """Return the injected publisher, or None if not configured.
    All wire-up Akosha integrations MUST handle None gracefully (log + metric, no-op)."""
    return _publisher


async def safe_publish(envelope: OneiricEventEnvelope) -> bool:
    """Fire-and-forget publish. Returns True if published, False if skipped
    (Akosha down or unconfigured).

    NEVER raises — observability must never block the dispatch path.
    Catches Exception (not BaseException) so CancelledError propagates
    per crackerjack-compliant-code."""
    publisher = get_publisher()
    if publisher is None:
        EVENTBRIDGE_PUBLISH_TOTAL.labels(
            envelope_event_type=getattr(envelope, "event_type", "unknown"),
            result="skip",
        ).inc()
        return False
    try:
        await publisher.publish(envelope)
        EVENTBRIDGE_PUBLISH_TOTAL.labels(
            envelope_event_type=envelope.event_type,
            result="success",
        ).inc()
        return True
    except Exception:
        EVENTBRIDGE_PUBLISH_TOTAL.labels(
            envelope_event_type=getattr(envelope, "event_type", "unknown"),
            result="error",
        ).inc()
        logger.exception(
            "EventBridge publish failed",
            extra={"envelope_event_type": getattr(envelope, "event_type", None)},
        )
        return False
```

Note: `safe_publisher_monkeypatch` from C-2 captures envelopes by patching `_capture_singleton` and calling `set_publisher()`. C-5's real `set_publisher` writes to `_publisher`. The two coexist cleanly because `_capture_singleton` is in `publisher.py` but only set by the test fixture; production code reads `_publisher`.

### 2. `mahavishnu/core/events/eventbridge_resolver.py` — DELETE

```bash
git rm mahavishnu/core/events/eventbridge_resolver.py
```

Per `feedback-no-backwards-compat-pre-1.0`, no deprecation window. The resolver is deleted; downstream callers are migrated in the same commit.

If downstream callers cannot be migrated in the same commit (e.g., they're in a separate package not in this repo), this plan must be split. **Verify by `grep -r "resolve_event_publisher" mahavishnu/` first** — if any in-repo callers exist, migrate them in this commit.

### 3. `mahavishnu/factories.py` — wire `set_publisher()` at boot

Read `mahavishnu/factories.py` and find `_wire_eventbridge_publisher`. The function constructs an `EventBridgePublisher` instance and previously handed it to callers via the resolver. Replace the wiring so it injects via `set_publisher()`:

```python
# Before (deleted pattern):
async def _wire_eventbridge_publisher(server) -> EventBridgePublisher:
    publisher = EventBridgePublisher(server)
    return publisher  # callers retrieve via eventbridge_resolver.resolve_event_publisher(server)

# After:
async def _wire_eventbridge_publisher() -> EventBridgePublisher:
    """Construct the publisher and inject via module-global singleton.
    Returns the publisher for backward-compat with the existing call sites
    that read it from the return value (those are migrated in this commit too)."""
    from mahavishnu.core.events.publisher import set_publisher
    from mahavishnu.core.events.eventbridge_adapter import EventBridgePublisher

    publisher = EventBridgePublisher(...)  # existing construction logic
    set_publisher(publisher)
    return publisher  # returned for any in-commit migration sites
```

Find all call sites of `_wire_eventbridge_publisher(server)` in `mahavishnu/factories.py` and remove the `server` argument. They were passing the server to the resolver; now the singleton is process-global.

### 4. `mahavishnu/core/metrics.py` — add `EVENTBRIDGE_PUBLISH_TOTAL` metric

Append to the metrics module:

```python
EVENTBRIDGE_PUBLISH_TOTAL = Counter(
    "eventbridge_publish_total",
    "Total EventBridge publish attempts, labeled by envelope event_type and result.",
    labelnames=["envelope_event_type", "result"],
)
```

`result` is one of `"success"`, `"skip"` (no publisher configured), `"error"` (publish raised). Operators alert on `rate(eventbridge_publish_total{result="error"}[5m]) > 0.1`.

### 5. `mahavishnu/core/events/__init__.py` — re-export the singleton helpers

Add at the top:

```python
"""Events package — re-exports the singleton publisher helpers."""
from mahavishnu.core.events.publisher import (
    get_publisher,
    safe_publish,
    set_publisher,
)

__all__ = ["get_publisher", "safe_publish", "set_publisher"]
```

This lets downstream code use `from mahavishnu.core.events import safe_publish` (flat import per Oneiric convention).

### 6. `tests/unit/test_publisher.py` — new file (~150 LoC)

Five test classes covering all required paths:

```python
"""Unit tests for the module-global EventBridgePublisher singleton."""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from mahavishnu.core.events.contract import OneiricEventEnvelope
from mahavishnu.core.events.publisher import (
    get_publisher,
    safe_publish,
    set_publisher,
)


@pytest.mark.req(["REQ-005"])
class TestSetGetPublisher:
    def test_set_then_get_roundtrip(self) -> None:
        publisher = MagicMock()
        set_publisher(publisher)
        assert get_publisher() is publisher

    def test_get_returns_none_when_unset(self) -> None:
        # Reset to None explicitly
        set_publisher(None)
        assert get_publisher() is None

    def teardown_method(self, method) -> None:
        # Reset singleton after each test to avoid bleed-through
        set_publisher(None)


@pytest.mark.req(["REQ-005"])
class TestSafePublishSuccess:
    async def test_returns_true_on_success(self) -> None:
        publisher = AsyncMock()
        publisher.publish = AsyncMock(return_value=None)
        set_publisher(publisher)
        envelope = MagicMock(spec=OneiricEventEnvelope)
        envelope.event_type = "test.event"
        result = await safe_publish(envelope)
        assert result is True
        publisher.publish.assert_awaited_once_with(envelope)

    def teardown_method(self, method) -> None:
        set_publisher(None)


@pytest.mark.req(["REQ-005"])
class TestSafePublishSkips:
    async def test_returns_false_when_publisher_is_none(self) -> None:
        set_publisher(None)
        envelope = MagicMock(spec=OneiricEventEnvelope)
        envelope.event_type = "test.event"
        result = await safe_publish(envelope)
        assert result is False


@pytest.mark.req(["REQ-005"])
class TestSafePublishSwallowsExceptions:
    async def test_returns_false_on_publish_exception(self) -> None:
        publisher = AsyncMock()
        publisher.publish = AsyncMock(side_effect=RuntimeError("Akosha down"))
        set_publisher(publisher)
        envelope = MagicMock(spec=OneiricEventEnvelope)
        envelope.event_type = "test.event"
        result = await safe_publish(envelope)
        assert result is False  # swallowed — never raises

    async def test_cancelled_error_propagates(self) -> None:
        """CancelledError must NOT be swallowed — per crackerjack-compliant-code
        and per asyncio contract. Catching BaseException would break cancellation."""
        import asyncio

        publisher = AsyncMock()
        publisher.publish = AsyncMock(side_effect=asyncio.CancelledError())
        set_publisher(publisher)
        envelope = MagicMock(spec=OneiricEventEnvelope)
        envelope.event_type = "test.event"
        with pytest.raises(asyncio.CancelledError):
            await safe_publish(envelope)

    def teardown_method(self, method) -> None:
        set_publisher(None)


@pytest.mark.req(["REQ-005"])
class TestResolverDeleted:
    """Per feedback-no-backwards-compat-pre-1.0: the resolver is REPLACED, not deprecated.
    Verify the old API is gone."""

    def test_resolver_module_not_importable(self) -> None:
        import importlib
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module("mahavishnu.core.events.eventbridge_resolver")

    def test_resolver_symbol_gone(self) -> None:
        import importlib
        with pytest.raises(ImportError):
            # The old `from ... import eventbridge_resolver` pattern must fail
            importlib.import_module(
                "mahavishnu.core.events.eventbridge_resolver"
            ).resolve_event_publisher  # ty: ignore[unresolved-attribute]
```

The `teardown_method` ensures singleton state does not bleed between tests. C-2's `safe_publisher_monkeypatch` autouse fixture also resets, but explicit teardown is belt-and-braces.

### 7. `mahavishnu/core/events/eventbridge_adapter.py` — verify `publish(envelope)` signature

Read `mahavishnu/core/events/eventbridge_adapter.py` and confirm:

- The class is named `EventBridgePublisher`.
- It exposes an async method `publish(envelope: OneiricEventEnvelope) -> None` (or similar — adjust the type hint if different).

If the method is named differently (e.g., `send`, `emit`, `dispatch`), the test above must use that name. The plan assumes `publish`; verify before landing.

## Tests

| Test class | Coverage |
|---|---|
| `TestSetGetPublisher` | Roundtrip; default None |
| `TestSafePublishSuccess` | Returns True on successful publish |
| `TestSafePublishSkips` | Returns False when publisher is None |
| `TestSafePublishSwallowsExceptions` | Returns False on RuntimeError; propagates CancelledError |
| `TestResolverDeleted` | Old resolver module is not importable |

All carry `@pytest.mark.req(["REQ-005"])`. Total: 5 test classes, ~8 test methods.

## Crackerjack verification

```bash
uv run pytest tests/unit/test_publisher.py -v
uv run pytest --cov=mahavishnu --cov-fail-under=89.01682905225863
uv run crackerjack run -p minor
```

## Acceptance criteria (decisive pass/fail)

1. `mahavishnu/core/events/publisher.py` exists with `set_publisher`, `get_publisher`, `safe_publish` exports.
1. `mahavishnu/core/events/eventbridge_resolver.py` is deleted (`git log --diff-filter=D --name-only` shows it removed).
1. `grep -r "resolve_event_publisher" mahavishnu/` returns zero matches (all callers migrated).
1. `safe_publish()` returns True on success / False on None / False on exception (without raising).
1. `safe_publish()` propagates `asyncio.CancelledError` (does not catch `BaseException`).
1. `mahavishnu/factories.py:_wire_eventbridge_publisher` calls `set_publisher()` at boot.
1. `mahavishnu/core/metrics.py` has `EVENTBRIDGE_PUBLISH_TOTAL` Counter with labels `(envelope_event_type, result)`.
1. `python scripts/audit_requirements.py --json` reports REQ-005 wired (markers present, no orphans).
1. `crackerjack run` passes; coverage gate holds.

## Rollback / recovery narration

This is a **single-API replacement** with no dual-mode fallback. Rollback is `git revert <commit-sha>` — but per `feedback-no-backwards-compat-pre-1.0`, the revert must be followed by forward commits restoring the new behavior (the old resolver path is gone and cannot be resurrected cleanly).

In practice: if downstream code (C-6, C-10, C-13) cannot land in the same release window as C-5, they MUST land in the same release window anyway — there is no "ship C-5 alone" path. If a downstream consumer (e.g., a plugin not in this repo) still imports `resolve_event_publisher`, that consumer breaks immediately on C-5 merge.

**Mitigation:** before merging C-5, run `grep -r "resolve_event_publisher" --include="*.py" .` across the entire Bodai ecosystem (not just mahavishnu). Coordinate migrations in any downstream consumers.

## Observability added

One new Prometheus metric (covered above):

- `eventbridge_publish_total{envelope_event_type, result}` — Counter; result ∈ {success, skip, error}

Operators alert on `rate(eventbridge_publish_total{result="error"}[5m]) > 0.1`. The `result="skip"` counter tells operators when publishing is silently disabled (publisher not configured) — useful for diagnosing misconfigured deployments.

## Health aggregation

None directly added. The `eventbridge_publish_total{result="error"}` rate is the de facto health signal — operators set up Prometheus alerting instead of a `/health` check, because publish failures should not make the whole `/health` endpoint 503 (other Mahavishnu subsystems are unaffected).

## Implementation notes / gotchas

- **The resolver is REPLACED, not deprecated.** No `DeprecationWarning`, no fallback. Per `feedback-no-backwards-compat-pre-1.0`.
- **`safe_publish` catches `Exception`, not `BaseException`.** This is per crackerjack-compliant-code AND per asyncio contract — catching `BaseException` would break cancellation propagation. The test `test_cancelled_error_propagates` enforces this.
- **`OneiricEventEnvelope` import is `TYPE_CHECKING`-guarded.** The plan uses `from typing import TYPE_CHECKING` and the `if TYPE_CHECKING:` block, matching Oneiric conventions.
- **Project-standard logger is `oneiric.logging.getLogger`.** NOT `import logging` and NOT `print()`. Per crackerjack-compliant-code.
- **`logger.exception(...)` is used (NOT `logger.error(..., exc_info=True)`).** Per crackerjack-compliant-code.
- **The `_capture_singleton` mechanism in C-2** is set by the `safe_publisher_monkeypatch` test fixture. The real `_publisher` is what `set_publisher` writes to. The two are independent — `safe_publish` reads `_publisher`, not `_capture_singleton`. Tests bypass the real publisher by setting `set_publisher(lambda_envelope)` which writes a callable to `_publisher`; the callable captures into the test's local list.
- **`eventbridge_publish_total` is incremented even on the None-publisher path** (`result="skip"`). Without this, operators cannot distinguish "publisher not configured" from "publisher broken but never called".
- **`factories.py` changes are minimal** — replace `eventbridge_resolver.resolve_event_publisher(server)` with `set_publisher(publisher)` at the existing construction site.
- **All `grep -r "resolve_event_publisher" mahavishnu/` matches must be migrated.** If a match is in a comment or docstring, fix it; do not leave stale references.

## Files modified (summary)

| File | Action | LoC |
|---|---|---|
| `mahavishnu/core/events/publisher.py` | create | ~70 |
| `mahavishnu/core/events/eventbridge_resolver.py` | delete | -50 |
| `mahavishnu/factories.py` | edit (replace resolver wiring with `set_publisher`) | -5/+5 |
| `mahavishnu/core/metrics.py` | edit (add `EVENTBRIDGE_PUBLISH_TOTAL`) | +7 |
| `mahavishnu/core/events/__init__.py` | edit (re-export singleton helpers) | +8 |
| `tests/unit/test_publisher.py` | create | +150 |
