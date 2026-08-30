"""Integration test for the Phase 2 settle lifecycle.

Exercises the full settle pipeline:

1. ``worker_run_with_settle`` spawns a worker AND persists a settle
   record (state=PROPOSED) to the local dead-letter file BEFORE any
   file write.
2. After observing the ``proposed`` state via ``worker_settle(...,
   action="select")``, the run is in SELECTED.
3. After ``worker_settle(..., action="apply")`` with a non-conflicting
   binding content, the run reaches APPLIED via ``git merge-file``.

The test does NOT mock the merge — it actually shells out to git so
the conflict-detection path is exercised end-to-end. If git is not on
PATH the test skips (so it doesn't fail in CI sandboxes without git).
"""

from __future__ import annotations

from datetime import UTC, datetime
import shutil
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.integration

# Skip the entire module if git is missing — the merge implementation
# shells out to ``git merge-file``.
pytestmark = pytest.mark.integration
git_available = shutil.which("git") is not None
if not git_available:
    pytest.skip("git not on PATH; cannot exercise 3-way merge", allow_module_level=True)


from mahavishnu.settle.persistence import (
    load_record_sync,
)
from mahavishnu.settle.state_machine import (
    SettleState,
)


@pytest.fixture
def isolated_dhara_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect dead-letter writes to tmp_path."""
    dl_dir = tmp_path / "settle-dead-letter"
    dl_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        "mahavishnu.settle.persistence.SETTLE_DEAD_LETTER_DIR", dl_dir
    )
    return dl_dir


@pytest.fixture
def fake_manager() -> MagicMock:
    """Mock ``DurableWorkerManager`` that records spawn calls."""

    manager = MagicMock()
    manager.spawn = MagicMock(
        return_value=MagicMock(
            worker_id="w-test-1",
            record=MagicMock(
                worker_id="w-test-1",
                state="running",
                last_seen_at=datetime.now(UTC),
                created_at=datetime.now(UTC),
            ),
        )
    )
    return manager


async def test_full_settle_lifecycle_apply(isolated_dhara_dir, fake_manager, monkeypatch):
    """End-to-end: PROPOSED -> SELECTED -> APPLIED via git merge-file.

    The binding base is "hello\n". The worker produces "hello world\n"
    which is a clean additive change against the base, so git's 3-way
    merge succeeds with no conflict markers.
    """
    from mahavishnu.mcp.tools import worker_contract_tools as tools

    monkeypatch.setattr(tools, "_durable_manager", fake_manager)
    monkeypatch.setattr(tools, "_settle_dhara", None)  # force dead-letter path

    # 1. Spawn worker + register settle record BEFORE file write.
    launch = await tools.worker_run_with_settle(
        task_signature="hello-world",
        bindings=[{"path": "hello.txt", "base": "hello\n"}],
    )
    assert launch["run_ref"].startswith("settle-")
    assert launch["worker_id"] == "w-test-1"
    assert launch["state"] == SettleState.PROPOSED.value

    # 2. Settle record is persisted to the dead-letter BEFORE spawn
    # (the test confirms the contract: file exists immediately).
    safe = launch["run_ref"].replace("/", "_").replace("..", "_")[:200]
    dead_letter_file = isolated_dhara_dir / f"{safe}.json"
    assert dead_letter_file.exists(), "dead-letter must exist before launch"
    record = load_record_sync(launch["run_ref"], dhara=None)
    assert record is not None
    assert record.state == SettleState.PROPOSED

    # 3. Observe PROPOSED state via select action.
    selected = await tools.worker_settle(launch["run_ref"], "select")
    assert selected["state"] == SettleState.SELECTED.value
    assert selected["legal_next"] == ["apply", "release", "discard"]

    # 4. Apply — git merge-file runs against the binding.base.
    applied = await tools.worker_settle(
        launch["run_ref"],
        "apply",
        bindings_content={"hello.txt": "hello world\n"},
    )
    assert applied["state"] == SettleState.APPLIED.value
    assert "merge" in applied
    assert "merged" in applied["merge"]
    assert applied["merge"]["conflict_count"] == 0
    assert "hello.txt" in applied["merge"]["merged"]


async def test_full_settle_lifecycle_release(isolated_dhara_dir, fake_manager, monkeypatch):
    """End-to-end: PROPOSED -> SELECTED -> RELEASED (no merge)."""
    from mahavishnu.mcp.tools import worker_contract_tools as tools

    monkeypatch.setattr(tools, "_durable_manager", fake_manager)
    monkeypatch.setattr(tools, "_settle_dhara", None)

    launch = await tools.worker_run_with_settle(
        task_signature="discard-me",
        bindings=[{"path": "x", "base": ""}],
    )
    assert launch["state"] == SettleState.PROPOSED.value

    selected = await tools.worker_settle(launch["run_ref"], "select")
    assert selected["state"] == SettleState.SELECTED.value

    released = await tools.worker_settle(launch["run_ref"], "release")
    assert released["state"] == SettleState.RELEASED.value
    assert released["legal_next"] == []


async def test_apply_conflict_returns_structured_error(
    isolated_dhara_dir, fake_manager, monkeypatch
):
    """Apply with conflicting content must NOT advance state and must return the merged-with-markers text."""
    from mahavishnu.mcp.tools import worker_contract_tools as tools

    monkeypatch.setattr(tools, "_durable_manager", fake_manager)
    monkeypatch.setattr(tools, "_settle_dhara", None)

    launch = await tools.worker_run_with_settle(
        task_signature="conflict-test",
        bindings=[{"path": "x", "base": "line1\nline2\nline3\n"}],
    )
    # Move to SELECTED first.
    await tools.worker_settle(launch["run_ref"], "select")

    # Two divergent edits to the same base — git merge-file will flag a conflict.
    ours = "line1\nWORKER_EDITED\nline3\n"
    theirs = "line1\nUSER_EDITED\nline3\n"
    result = await tools.worker_settle(
        launch["run_ref"],
        "apply",
        bindings_content={"x": ours},
        bindings_theirs={"x": theirs},
    )
    assert result["state"] == "merge_conflict"
    assert "conflicts" in result
    # State must NOT have advanced — re-read the record.
    record = load_record_sync(launch["run_ref"], dhara=None)
    assert record is not None
    assert record.state == SettleState.SELECTED


async def test_illegal_transition_returns_error(
    isolated_dhara_dir, fake_manager, monkeypatch
):
    """Trying to ``apply`` from PROPOSED is illegal."""
    from mahavishnu.mcp.tools import worker_contract_tools as tools

    monkeypatch.setattr(tools, "_durable_manager", fake_manager)
    monkeypatch.setattr(tools, "_settle_dhara", None)

    launch = await tools.worker_run_with_settle(
        task_signature="illegal",
        bindings=[{"path": "x", "base": ""}],
    )
    result = await tools.worker_settle(
        launch["run_ref"], "apply", bindings_content={"x": ""}
    )
    assert result["state"] == "illegal_transition"
    assert result["current_state"] == SettleState.PROPOSED.value


async def test_persists_before_launch(isolated_dhara_dir, fake_manager, monkeypatch):
    """The settle record must exist on disk BEFORE spawn is invoked.

    This is the load-bearing property: a process crash between record
    creation and worker file write must NOT leave a worker writing
    without an audit trail.
    """
    from mahavishnu.mcp.tools import worker_contract_tools as tools

    spawn_call_order: list[str] = []

    def spy_spawn(*_args, **_kwargs):
        spawn_call_order.append("spawn")
        # At the moment spawn is called, the dead-letter file MUST exist.
        # The run_ref is not yet known to the spy, so we look for ANY
        # *.json file in the dead-letter dir.
        files = list(isolated_dhara_dir.glob("*.json"))
        assert len(files) >= 1, (
            "spawn was called before the settle record was persisted"
        )
        return MagicMock(
            worker_id="w-test-2",
            record=MagicMock(
                worker_id="w-test-2",
                state="running",
                last_seen_at=datetime.now(UTC),
                created_at=datetime.now(UTC),
            ),
        )

    fake_manager.spawn = MagicMock(side_effect=spy_spawn)
    monkeypatch.setattr(tools, "_durable_manager", fake_manager)
    monkeypatch.setattr(tools, "_settle_dhara", None)

    launch = await tools.worker_run_with_settle(
        task_signature="order-check",
        bindings=[{"path": "x", "base": ""}],
    )
    assert spawn_call_order == ["spawn"]
    assert launch["state"] == SettleState.PROPOSED.value


async def test_invalid_action_returns_error(
    isolated_dhara_dir, fake_manager, monkeypatch
):
    """An unknown action string returns ``state=invalid_action`` without crashing."""
    from mahavishnu.mcp.tools import worker_contract_tools as tools

    monkeypatch.setattr(tools, "_durable_manager", fake_manager)
    monkeypatch.setattr(tools, "_settle_dhara", None)

    launch = await tools.worker_run_with_settle(
        task_signature="bogus-action",
        bindings=[{"path": "x", "base": ""}],
    )
    result = await tools.worker_settle(launch["run_ref"], "frobnicate")
    assert result["state"] == "invalid_action"


async def test_missing_run_ref_returns_error(monkeypatch):
    """worker_settle with an unknown run_ref returns state=not_found."""
    from mahavishnu.mcp.tools import worker_contract_tools as tools

    monkeypatch.setattr(tools, "_settle_dhara", None)
    result = await tools.worker_settle("settle-does-not-exist", "select")
    assert result["state"] == "not_found"


def test_websocket_server_allows_settle_channel_for_worker_read():
    """``settle:`` and ``run:`` channels are gated on ``worker:read``."""
    from mahavishnu.websocket.server import MahavishnuWebSocketServer

    # Instantiate a minimal server to call the instance method. The
    # ``_can_subscribe_to_channel`` method only uses ``self`` to access
    # class attributes — none are required for the permission check.
    server = MahavishnuWebSocketServer.__new__(MahavishnuWebSocketServer)
    method = server._can_subscribe_to_channel

    user_with_worker = {"permissions": ["worker:read"]}
    assert method(user_with_worker, "settle:settle-abcd1234") is True
    assert method(user_with_worker, "run:w-xyz") is True

    user_without_worker = {"permissions": ["foo:read"]}
    assert method(user_without_worker, "settle:settle-abcd1234") is False
    assert method(user_without_worker, "run:w-xyz") is False

    admin_user = {"permissions": ["admin"]}
    assert method(admin_user, "settle:settle-abcd1234") is True
