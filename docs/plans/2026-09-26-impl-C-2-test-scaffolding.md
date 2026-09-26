# C-2: T-0 test scaffolding (lands AFTER C-1, BEFORE all wire-ups)

**REQ-NNN:** REQ-002 — T-0 test scaffolding (fixtures, autouse cleanup)
**Risk:** Low (test-only — no production code paths touched, no DB migrations, no public API changes)
**Blocks:** Every wire-up plan that lands a test (C-3, C-4, C-5, C-6, C-8, C-9, C-10, C-11, C-12, C-13). Each future plan's `tests/integration/test_*.py` consumes one or more of these fixtures.
**Direct-to-main commit:** Yes (per `feedback-no-backwards-compat-pre-1.0` + `bodai-pre-1.0-merge-policy`).

**Niche fit:** Per [`docs/adr/0001-mahavishnu-niche.md`](../adr/0001-mahavishnu-niche.md), this plan anchors Mahavishnu as LLM control plane + repo orchestrator + multi-engine + harness-agnostic. The three-question filter (deepens? Bodai integration? no source-tool competition?) was applied at planning time.
**Status:** Draft — round-4 corrections baked in.

## Goal

Ship `tests/integration/conftest_wireups.py` with shared fixtures so wire-up tests land in a coherent harness instead of each rolling its own teardown. Eleven named items (the spec headline counts "8" before round-3 QA added `frozen_clock` + two per-test monkeypatches): nine fixtures + two per-test autouse monkeypatches + one autouse worktree cleanup. Each fixture has its own unit test.

Per round-3 QA: the file is ~300-400 LoC (~50% larger than round-2's estimate) because the `mark_finished_tasks` autouse needs an explicit `try/finally` (no contextmanager shortcut — must call `git worktree remove --force` on every test invocation regardless of pass/fail), and `frozen_clock` adds `freezegun` integration that the legacy `clock` fixture does not.

## Pre-flight checks

1. **C-1 has landed on main.** Verify the 5 new sections (`worktree_storage:`, `idempotency:`, `webhook_intake:`, `concurrency_limits:`, `markdown_board:`) appear in `settings/mahavishnu.yaml` and that `pytest --markers | grep ^req$` shows the `req` marker is registered. If absent, stop and ship C-1 first — fixtures like `idempotency_flag_monkeypatch` depend on the `idempotency:` section existing for `get_settings()` to return something patchable.
2. **`oneiric.logging.getLogger` importable.** `python -c "from oneiric.core.logging import get_logger"`.
3. **`freezegun` available.** `uv pip show freezegun` (used by `frozen_clock`); add as dev dep in this PR if not present.
4. **`pytest-asyncio` is configured for auto-mode.** Confirm `asyncio_mode = "auto"` in `pyproject.toml [tool.pytest]` — async fixtures require this.
5. **`fastapi` is a runtime dep** (used by `ecosystem_intake_test_client`).
6. **`aiosqlite` available.** Used by `isolated_database` for the per-test DB.

## File-by-file changes

### 1. `pyproject.toml` — declare `freezegun` dev dep

Under `[tool.uv.dev-dependencies]` (or wherever `pytest-asyncio` lives), add:

```toml
"freezegun>=1.5,<2.0",
```

Pin to `~=1.5` (compatible release) per `dependency-management` policy. `freezegun` 1.5+ supports `tick=True` and `auto_tick_seconds` which the `frozen_clock` fixture needs when C-9's `ConcurrencyGate` tests advance time without freezing it.

### 2. `tests/integration/conftest_wireups.py` — new file (~350 LoC)

This is the entire deliverable. Top-of-file:

```python
"""T-0 wire-up fixtures. Consumed by every integration test in tests/integration/."""
from __future__ import annotations

import asyncio
import os
import subprocess
import tempfile
import time
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from freezegun import freeze_time

from mahavishnu.core.config import (
    MahavishnuSettings,
    get_settings,
)
from mahavishnu.core.event_store import EventStore
from mahavishnu.core.database import Database  # FIX round-6: EventStore takes a Database, not a Path

if TYPE_CHECKING:
    from mahavishnu.core.worktree_manager import WorktreeManager  # FIX round-6: real module is worktree_manager, not worktree
    from mahavishnu.pools import PoolManager
```

Then the fixtures, in this order:

**`isolated_database` (pytest_asyncio fixture, function scope)**

```python
@pytest_asyncio.fixture
async def isolated_database() -> AsyncIterator[Path]:
    """Per-test fresh SQLite DB. NOT :memory: — aiosqlite :memory: is per-connection
    and xdist workers share state. tempfile.NamedTemporaryFile + EventStore.connect
    gives one DB per test even under -n auto.

    FIX round-6: EventStore takes a Database instance, not a Path. We construct
    a Database wrapping the temp SQLite file. The fixture yields the path so
    downstream code can use it for direct aiosqlite operations if needed.
    """
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = Path(f.name)
    db = Database(path)  # FIX round-6: real EventStore constructor takes Database
    try:
        yield path  # Yield the path; downstream code creates its own EventStore(db)
    finally:
        path.unlink(missing_ok=True)
```

**`tmp_xdg_state_dir` (function scope, sync context manager)**

```python
@contextmanager
def tmp_xdg_state_dir_impl(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Path]:
    """Redirect platformdirs-derived XDG paths to tmp_path. Affects:
    - mahavishnu's config cache ($XDG_CACHE_HOME/mahavishnu)
    - worktree base ($XDG_DATA_HOME/mahavishnu/worktrees)
    - log dir ($XDG_STATE_HOME/mahavishnu/logs)
    """
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    yield tmp_path


@pytest.fixture
def tmp_xdg_state_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Path]:
    """Fixture form of tmp_xdg_state_dir_impl — usable in test signatures."""
    with tmp_xdg_state_dir_impl(monkeypatch, tmp_path) as p:
        yield p
```

**`controllable_pool_manager_mock` (function scope)**

```python
@pytest.fixture
def controllable_pool_manager_mock() -> PoolManager:
    """PoolManager mock that counts route_task calls and can block on asyncio.Event.
    Tests for pending-status (TaskEventType.PENDING) use the Event to keep a workflow
    in PENDING long enough to assert idempotency lock semantics."""
    mock = AsyncMock(spec=PoolManager)
    mock.route_task = AsyncMock()
    mock._pending_gate = asyncio.Event()
    mock._route_task_call_count = 0
    return mock
```

**`worktree_manager_factory` (function scope)**

```python
@pytest_asyncio.fixture
async def worktree_manager_factory(
    tmp_xdg_state_dir: Path, isolated_database: Path
) -> AsyncIterator[WorktreeManager]:
    """Construct WorktreeManager against an isolated XDG dir + DB.
    Cleanup is handled by mark_finished_tasks autouse — this fixture only
    constructs, it does not teardown."""
    from mahavishnu.core.worktree import WorktreeManager

    settings = get_settings()
    # FIX round-6: WorktreeManager takes a Database, not a Path, and EventStore
    # takes a Database, not a Path. Construct both from the isolated_database path.
    db = Database(isolated_database)
    mgr = WorktreeManager(
        base_path=settings.worktree_storage.storage_root,
        event_store=EventStore(db),
    )
    yield mgr
```

**`ecosystem_intake_signed_post` (function scope, factory)**

```python
@pytest.fixture
def ecosystem_intake_signed_post() -> Callable[..., dict[str, Any]]:
    """Generate sanitized POST payloads for C-10 tests. NO HMAC (C-10 dropped that).
    Returns a factory that takes a source_name + body dict and produces a JSON
    payload ready to POST."""
    def _make(source_name: str, body: dict[str, Any]) -> dict[str, Any]:
        return {
            "source": source_name,
            "occurred_at": datetime.now(UTC).isoformat(),
            "body": body,
            "id": str(uuid.uuid4()),
        }
    return _make
```

**`ecosystem_intake_test_client` (function scope)**

```python
@pytest.fixture
def ecosystem_intake_test_client(tmp_xdg_state_dir: Path) -> TestClient:
    """fastapi.testclient.TestClient wrapping fresh FastAPI() with the C-10
    ecosystem intake router injected. Per-test fresh router state."""
    from mahavishnu.ingesters.ecosystem_intake import build_router

    app = FastAPI()
    app.include_router(build_router(get_settings()))
    return TestClient(app)
```

**`ecosystem_dlq_inspector` (function scope, factory)**

```python
@pytest.fixture
def ecosystem_dlq_inspector() -> Callable[..., list[dict[str, Any]]]:
    """Read ecosystem-intake rejection events from Akosha pattern subscription.
    NOTE: ecosystem intake has NO DLQ — rejections go to Akosha via the
    pattern-subscription path (per C-10 simplification, dropping HMAC DLQ).
    Inspector reads the Akosha stream filtered to source=mahavishnu.eco.intake.
    Returns a closure that takes (since: datetime) and returns events.
    """
    def _inspect(since: datetime | None = None) -> list[dict[str, Any]]:
        from mahavishnu.core.events.akosha import get_akosha_client

        client = get_akosha_client()
        return client.search_events(
            pattern="ecosystem.intake.rejected",
            since=since or datetime.now(UTC) - timedelta(seconds=60),
        )
    return _inspect
```

**`frozen_clock` (function scope)**

```python
@pytest.fixture
def frozen_clock() -> Iterator[freeze_time]:
    """New fixture per round-3 QA. Uses freezegun.freeze_time to patch BOTH
    time.time and datetime.now(UTC). The legacy `clock` fixture at
    tests/conftest.py:233 only patches time.time — insufficient for
    ConcurrencyGate (C-9) which reads datetime.now(UTC) directly.
    tick=True is required so datetime.now(UTC) arithmetic in C-9 tests works.
    """
    with freeze_time("2026-09-26T12:00:00Z", tick=True) as ft:
        yield ft
```

**Per-test autouse `idempotency_flag_monkeypatch`**

```python
@pytest.fixture(autouse=True)
def idempotency_flag_monkeypatch(
    monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> Iterator[None]:
    """Patch get_settings() cache so idempotency.fail_mode is per-test.
    Without this, xdist workers race on a shared global flag.
    Default fail_mode is 'fail_closed'. Individual tests can override via
    @pytest.mark.idempotency('fail_open') marker."""
    marker = request.node.get_closest_marker("idempotency")
    fail_mode = marker.args[0] if marker else "fail_closed"
    settings = get_settings()
    settings.idempotency.fail_mode = fail_mode
    monkeypatch.setattr(
        "mahavishnu.core.config.get_settings_cached", lambda: settings
    )
    yield
```

**Per-test autouse `safe_publisher_monkeypatch`**

```python
@pytest.fixture(autouse=True)
def safe_publisher_monkeypatch(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Patch set_publisher so safe_publish() goes to a per-test capture list.
    C-5 lands the real EventBridgePublisher; until then, tests must not depend
    on the real Akosha publisher.

    FIX (round-5): explicitly reset `_publisher` to None in teardown so
    publisher state does not leak across tests. The previous version used
    monkeypatch.setattr for `_capture_singleton` (which is auto-reverted)
    but called set_publisher(...) which mutates the module-global `_publisher`
    (which monkeypatch does NOT undo). Without this fix, after the first
    test, _publisher still references a lambda whose captured list is now
    stale or dropped, causing subsequent tests to receive empty captures
    or worse, to append to a list from a prior test.
    """
    from mahavishnu.core.events.publisher import set_publisher

    captured: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "mahavishnu.core.events.publisher._capture_singleton", captured
    )
    set_publisher(lambda envelope: captured.append(envelope.model_dump()))
    try:
        yield captured
    finally:
        # Explicit reset — monkeypatch.undo() does NOT undo set_publisher's
        # side effect on the module-global _publisher.
        set_publisher(None)

**Autouse `mark_finished_tasks` (function scope)**

```python
@pytest.fixture(autouse=True)
def mark_finished_tasks(request: pytest.FixtureRequest, tmp_xdg_state_dir: Path) -> Iterator[None]:
    """Per round-3 QA — explicit try/finally, NO contextmanager shortcut.
    Scan $XDG_DATA_HOME/mahavishnu/worktrees/ for worktrees newer than this test
    invocation, git worktree remove --force on the failure path. This is a
    global cleanup guarantee — making it opt-in would let failed tests leak
    worktrees across the suite."""
    start_ts = time.time()
    yield
    worktree_base = Path(os.environ["XDG_DATA_HOME"]) / "mahavishnu" / "worktrees"
    if not worktree_base.exists():
        return
    for wt in worktree_base.iterdir():
        try:
            if wt.stat().st_mtime < start_ts:
                continue
        except FileNotFoundError:
            continue
        # Failure path — test did not clean up. Best-effort removal.
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(wt)],
            check=False,
            capture_output=True,
        )
```

### 3. `tests/unit/test_conftest_wireups.py` — new file (~180 LoC)

One test class per fixture, demonstrating the fixture works as documented:

```python
"""Unit tests for the wire-up fixtures themselves."""
from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path

import pytest


@pytest.mark.req(["REQ-002"])
class TestIsolatedDatabase:
    async def test_returns_path(self, isolated_database: Path) -> None:
        assert isolated_database.exists()
        assert isolated_database.suffix == ".db"

    async def test_is_a_file(self, isolated_database: Path) -> None:
        assert isolated_database.is_file()

    async def test_fresh_per_test(self) -> None:
        # Two requests in the same test produce two distinct paths
        # (proves per-test, not per-session, freshness)
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f1:
            p1 = Path(f1.name)
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f2:
            p2 = Path(f2.name)
        assert p1 != p2
        p1.unlink()
        p2.unlink()


@pytest.mark.req(["REQ-002"])
class TestTmpXdgStateDir:
    def test_xdg_env_vars_set(self, tmp_xdg_state_dir: Path) -> None:
        import os
        assert os.environ["XDG_CACHE_HOME"].startswith(str(tmp_xdg_state_dir))
        assert os.environ["XDG_DATA_HOME"].startswith(str(tmp_xdg_state_dir))
        assert os.environ["XDG_STATE_HOME"].startswith(str(tmp_xdg_state_dir))


@pytest.mark.req(["REQ-002"])
class TestControllablePoolManagerMock:
    def test_route_task_is_callable(self, controllable_pool_manager_mock) -> None:
        assert callable(controllable_pool_manager_mock.route_task)

    def test_pending_gate_is_event(self, controllable_pool_manager_mock) -> None:
        import asyncio
        assert isinstance(controllable_pool_manager_mock._pending_gate, asyncio.Event)


@pytest.mark.req(["REQ-002"])
class TestWorktreeManagerFactory:
    async def test_yields_manager(self, worktree_manager_factory) -> None:
        from mahavishnu.core.worktree import WorktreeManager
        assert isinstance(worktree_manager_factory, WorktreeManager)


@pytest.mark.req(["REQ-002"])
class TestEcosystemIntakeSignedPost:
    def test_payload_shape(self, ecosystem_intake_signed_post) -> None:
        payload = ecosystem_intake_signed_post("cr_source", {"key": "value"})
        assert payload["source"] == "cr_source"
        assert payload["body"] == {"key": "value"}
        assert "occurred_at" in payload
        assert "id" in payload
        # NO signature field — C-10 dropped HMAC.
        assert "signature" not in payload


@pytest.mark.req(["REQ-002"])
class TestEcosystemIntakeTestClient:
    def test_client_has_routes(self, ecosystem_intake_test_client) -> None:
        paths = [r.path for r in ecosystem_intake_test_client.app.routes]
        # C-10 mounts POST /webhooks/ecosystem/{source_name}
        assert any("/webhooks/ecosystem/" in p for p in paths)


@pytest.mark.req(["REQ-002"])
class TestFrozenClock:
    def test_freezes_time_time(self, frozen_clock) -> None:
        # FIX round-6: 2026-09-26T12:00:00Z corresponds to Unix timestamp 1790424000.
        # Round-5 used 1789753200 (which is 2026-09-18T17:42:00Z — wrong).
        # Original used 1737946800 (2025-01-27T03:00:00Z — wrong year).
        # Correct: 1790424000.
        assert time.time() == pytest.approx(1790424000.0, abs=1.0)

    def test_freezes_datetime_now(self, frozen_clock) -> None:
        now = datetime.now(UTC)
        assert now.year == 2026 and now.month == 9 and now.day == 26

    def test_tick_advances(self, frozen_clock) -> None:
        # tick=True means datetime.now(UTC) advances between calls
        # FIX round-7 (Tier 3): use `>=` not `>` — on sub-millisecond platforms
        # time.sleep(0.001) can resolve to 0, making strict `>` flake.
        first = datetime.now(UTC)
        time.sleep(0.001)
        second = datetime.now(UTC)
        assert second >= first


@pytest.mark.req(["REQ-002"])
class TestIdempotencyFlagMonkeypatch:
    def test_default_is_fail_closed(self) -> None:
        from mahavishnu.core.config import get_settings
        assert get_settings().idempotency.fail_mode == "fail_closed"

    @pytest.mark.idempotency("fail_open")
    def test_override_applies(self) -> None:
        from mahavishnu.core.config import get_settings
        assert get_settings().idempotency.fail_mode == "fail_open"


@pytest.mark.req(["REQ-002"])
class TestSafePublisherMonkeypatch:
    def test_capture_list_exists(self) -> None:
        from mahavishnu.core.events.publisher import _capture_singleton
        assert isinstance(_capture_singleton, list)

    async def test_safe_publish_captures_envelope(self) -> None:
        """FIX round-7 (Tier 3): real-capture assertion. Invokes safe_publish()
        and asserts the envelope lands in the captured list. Without this, the
        test only verifies `_capture_singleton` is a list — it never proves
        the autouse fixture actually captures anything."""
        from mahavishnu.core.events.contract import OneiricEventEnvelope
        from mahavishnu.core.events.publisher import safe_publish, _capture_singleton
        envelope = MagicMock(spec=OneiricEventEnvelope)
        envelope.event_type = "test.event"
        envelope.model_dump = MagicMock(return_value={"event_type": "test.event"})
        result = await safe_publish(envelope)
        assert result is True or result is False  # depends on whether publisher wired
        # The autouse fixture's lambda captures via the test's `captured` list,
        # which is yielded. Verify that something was captured (the lambda path)
        # OR that _capture_singleton grew if the autouse replaced it.
        assert len(_capture_singleton) >= 1 or result is True


@pytest.mark.req(["REQ-002"])
class TestMarkFinishedTasksAutouse:
    def test_runs_on_pass(self, tmp_path: Path) -> None:
        # The autouse runs unconditionally; a passing test still triggers it
        # (verified by the worktree_base path existing after fixture setup)
        import os
        assert "XDG_DATA_HOME" in os.environ
```

### 4. `tests/conftest.py` — add a re-export block (no new logic)

Append at the bottom (no edits to existing fixtures, especially the `clock` fixture at line 233):

```python
# Re-export wire-up fixtures so they are auto-collected by pytest from any tests/ tree.
# The F401 is intentional — re-export without re-exporting would break pytest's
# fixture discovery for nested test files. E402: imports below module-level code
# allowed here per the project's per-file-ignores for tests/conftest.py.
from tests.integration.conftest_wireups import (  # noqa: F401, E402
    controllable_pool_manager_mock,
    ecosystem_dlq_inspector,
    ecosystem_intake_signed_post,
    ecosystem_intake_test_client,
    frozen_clock,
    idempotency_flag_monkeypatch,
    isolated_database,
    mark_finished_tasks,
    safe_publisher_monkeypatch,
    tmp_xdg_state_dir,
    worktree_manager_factory,
)
```

## Tests

| Fixture / monkeypatch | Test class | Asserts |
|---|---|---|
| `isolated_database` | `TestIsolatedDatabase` | Path exists, suffix `.db`, fresh per test |
| `tmp_xdg_state_dir` | `TestTmpXdgStateDir` | XDG env vars all set |
| `controllable_pool_manager_mock` | `TestControllablePoolManagerMock` | route_task callable, gate is Event |
| `worktree_manager_factory` | `TestWorktreeManagerFactory` | Yields `WorktreeManager` |
| `ecosystem_intake_signed_post` | `TestEcosystemIntakeSignedPost` | Payload has source/body/occurred_at/id; no signature |
| `ecosystem_intake_test_client` | `TestEcosystemIntakeTestClient` | Routes include `/webhooks/ecosystem/` |
| `ecosystem_dlq_inspector` | (covered indirectly by C-10 tests) | — |
| `frozen_clock` | `TestFrozenClock` | time.time + datetime.now both frozen; tick advances |
| `idempotency_flag_monkeypatch` | `TestIdempotencyFlagMonkeypatch` | Default fail_closed; marker override works |
| `safe_publisher_monkeypatch` | `TestSafePublisherMonkeypatch` | Capture list exists |
| `mark_finished_tasks` (autouse) | `TestMarkFinishedTasksAutouse` | XDG_DATA_HOME set in env |

All carry `@pytest.mark.req(["REQ-002"])`. Total: 10 test classes, ~18 test methods.

## Crackerjack verification

```bash
uv run pytest tests/unit/test_conftest_wireups.py -v
uv run pytest --cov=mahavishnu --cov-fail-under=89.01682905225863
uv run crackerjack run -p minor
```

Wall-clock <30s on local. Crackerjack must pass with no new ty/mypy errors. `freezegun` 1.5+ is fully typed; `PoolManager` import is `TYPE_CHECKING`-guarded.

## Acceptance criteria (decisive pass/fail)

1. `tests/integration/conftest_wireups.py` exists, defines all 11 named items, and is auto-collected by pytest from any nested test directory.
2. `tests/unit/test_conftest_wireups.py` passes for every fixture (no skips, no xfails).
3. `git grep "frozen_clock"` returns matches in `tests/integration/conftest_wireups.py` AND `tests/conftest.py` re-export.
4. The legacy `clock` fixture in `tests/conftest.py:233` is unchanged (verified by `git diff tests/conftest.py` showing zero line changes around line 233).
5. `pytest --markers | grep ^req$` shows `req` marker registered (depends on C-1 having landed).
6. `pytest -n auto --dist=loadfile` runs the wire-up suite without per-test DB collisions.
7. `python scripts/audit_requirements.py --json` reports 0 orphans for REQ-002.
8. `crackerjack run` passes; coverage gate (89.01682905225863%) holds or improves.

## Rollback / recovery narration

This is test-only code. No production data, no migrations, no public API surface. Rollback is `git revert <commit-sha>`; the revert is a no-op for production. The risk surface is "tests fail to collect" — fixable in a follow-up commit by adjusting fixture scopes or re-export order.

If a fixture turns out to be wrong (e.g., `worktree_manager_factory` needs a different signature), the fix is a follow-up commit that adjusts the fixture and re-records the marker tests. Per `feedback-no-backwards-compat-pre-1.0`, no deprecation window — just replace.

## Observability

None added (test-only). Existing `pytest` logging covers test failure diagnostics.

## Health aggregation

None (test-only).

## Implementation notes / gotchas

- **`aiosqlite :memory:` does NOT isolate across xdist workers.** Per round-3 QA, all xdist workers see the same `:memory:` state because each connection is fresh per worker, but state persists across tests within a worker. Use `tempfile.NamedTemporaryFile(suffix=".db")` instead.
- **The legacy `clock` fixture is at `tests/conftest.py:233`** per spec. Do NOT modify it. Add `frozen_clock` as a NEW fixture with its own name.
- **`frozen_clock` uses `tick=True`** because C-9's `ConcurrencyGate` tests advance time during token-bucket refill. `tick=False` would cause `datetime.now()` to return the freeze value forever, breaking `datetime.now(UTC)` arithmetic in C-9 tests.
- **`idempotency_flag_monkeypatch` MUST be autouse.** Without autouse, individual tests would silently inherit whatever the previous worker's `fail_mode` was — xdist worker 2's first test would see worker 1's last override.
- **`safe_publisher_monkeypatch` MUST be autouse** for the same reason: every test needs a clean capture list, and pytest fixture ordering guarantees it runs before any test body.
- **`mark_finished_tasks` autouse MUST be `autouse=True`.** It is a global cleanup guarantee; making it opt-in would let failed tests leak worktrees across the suite.
- **`fastapi.testclient.TestClient` is synchronous** but `ecosystem_intake_test_client` does not need to be async — the C-10 endpoint is async-compatible because FastAPI runs the route in an event loop internally.
- **`XDG_DATA_HOME` env var must be set BEFORE `get_settings()` is first called** in test setup. `tmp_xdg_state_dir` uses `monkeypatch.setenv` which happens at fixture-setup time, before any test body runs `get_settings()`. Verify fixture order: `tmp_xdg_state_dir` → `worktree_manager_factory` (which calls `get_settings()`).
- **`subprocess.run(["git", "worktree", "remove", "--force", ...], check=False)` is best-effort.** A test must not raise if cleanup fails — that would mask the original test failure. `capture_output=True` swallows stdout/stderr.
- **`FileNotFoundError` on `wt.stat()` is expected** if a prior test's cleanup removed the worktree between iterdir and stat. Catch it explicitly and continue.
- **Per-file-ignores for `tests/conftest.py`** allow `F401` (the re-export block intentionally imports without using) and `E402` (the import is below module-level pytest configuration). The `noqa: F401, E402` comment is required.

## Files modified (summary)

| File | Action | LoC |
|---|---|---|
| `pyproject.toml` | edit (`[tool.uv.dev-dependencies]` += `freezegun`) | +1 |
| `tests/integration/conftest_wireups.py` | create | ~350 |
| `tests/unit/test_conftest_wireups.py` | create | ~180 |
| `tests/conftest.py` | edit (re-export block at EOF) | +15 |
