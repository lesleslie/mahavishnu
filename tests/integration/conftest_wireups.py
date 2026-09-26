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


@pytest_asyncio.fixture
async def worktree_manager_factory(
    tmp_xdg_state_dir: Path, isolated_database: Path
) -> AsyncIterator[WorktreeManager]:
    """Construct WorktreeManager against an isolated XDG dir + DB.
    Cleanup is handled by mark_finished_tasks autouse — this fixture only
    constructs, it does not teardown."""
    from mahavishnu.core.worktree_manager import WorktreeManager

    settings = get_settings()
    # FIX round-6: WorktreeManager takes a Database, not a Path, and EventStore
    # takes a Database, not a Path. Construct both from the isolated_database path.
    db = Database(isolated_database)
    mgr = WorktreeManager(
        base_path=settings.worktree_storage.storage_root,
        event_store=EventStore(db),
    )
    yield mgr


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


@pytest.fixture
def ecosystem_intake_test_client(tmp_xdg_state_dir: Path) -> TestClient:
    """fastapi.testclient.TestClient wrapping fresh FastAPI() with the C-10
    ecosystem intake router injected. Per-test fresh router state."""
    from mahavishnu.ingesters.ecosystem_intake import build_router

    app = FastAPI()
    app.include_router(build_router(get_settings()))
    return TestClient(app)


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
