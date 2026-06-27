"""Unit tests for mahavishnu/workflows/progress.py.

Spec #10 (live-observe-presence-over-gate): ProgressSnapshot model +
WorkflowProgressRecorder interface + HTTP CRUD call stub.

The substrate is `http_blocked (/workflows/<id>/progress-snapshots)` per
the Workstream C substrate status — so the recorder records in-process
and the HTTP call is a TODO stub that the substrate work will fill in.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from mahavishnu.workflows.progress import (
    ProgressSnapshot,
    WorkflowProgressRecorder,
    list_progress_snapshots,
    record_progress_snapshot,
)

# ---------------------------------------------------------------------------
# ProgressSnapshot model
# ---------------------------------------------------------------------------


class TestProgressSnapshotModel:
    def test_required_fields_present(self) -> None:
        snap = ProgressSnapshot(
            workflow_id="wf-1",
            step="load_data",
            percent=25,
            message="Loaded 250 rows",
        )
        assert snap.workflow_id == "wf-1"
        assert snap.step == "load_data"
        assert snap.percent == 25
        assert snap.message == "Loaded 250 rows"

    def test_default_timestamp_is_utc_now(self) -> None:
        before = datetime.now(UTC)
        snap = ProgressSnapshot(
            workflow_id="wf-1",
            step="init",
            percent=0,
            message="starting",
        )
        after = datetime.now(UTC)
        assert before <= snap.ts <= after

    def test_default_timestamp_is_utc_aware(self) -> None:
        snap = ProgressSnapshot(
            workflow_id="wf-1",
            step="init",
            percent=0,
            message="starting",
        )
        assert snap.ts.tzinfo is not None
        assert snap.ts.utcoffset() is not None

    def test_explicit_timestamp_is_preserved(self) -> None:
        ts = datetime(2026, 6, 27, 10, 30, 0, tzinfo=UTC)
        snap = ProgressSnapshot(
            workflow_id="wf-1",
            step="init",
            percent=0,
            message="starting",
            ts=ts,
        )
        assert snap.ts == ts

    def test_percent_must_be_in_range_low(self) -> None:
        with pytest.raises(ValueError, match="percent"):
            ProgressSnapshot(
                workflow_id="wf-1",
                step="bad",
                percent=-1,
                message="oops",
            )

    def test_percent_must_be_in_range_high(self) -> None:
        with pytest.raises(ValueError, match="percent"):
            ProgressSnapshot(
                workflow_id="wf-1",
                step="bad",
                percent=101,
                message="oops",
            )

    def test_is_frozen(self) -> None:
        snap = ProgressSnapshot(
            workflow_id="wf-1",
            step="init",
            percent=0,
            message="starting",
        )
        with pytest.raises(FrozenInstanceError):
            snap.percent = 50  # type: ignore[misc]

    def test_to_payload_returns_serializable_dict(self) -> None:
        ts = datetime(2026, 6, 27, 10, 30, 0, tzinfo=UTC)
        snap = ProgressSnapshot(
            workflow_id="wf-1",
            step="load",
            percent=42,
            message="halfway",
            ts=ts,
        )
        payload = snap.to_payload()
        assert isinstance(payload, dict)
        assert payload["workflow_id"] == "wf-1"
        assert payload["step"] == "load"
        assert payload["percent"] == 42
        assert payload["message"] == "halfway"
        assert payload["ts"] == ts.isoformat()


# ---------------------------------------------------------------------------
# WorkflowProgressRecorder interface
# ---------------------------------------------------------------------------


class TestWorkflowProgressRecorder:
    def test_records_snapshot_in_order(self) -> None:
        recorder = WorkflowProgressRecorder(workflow_id="wf-1")
        snap1 = recorder.record(step="init", percent=0, message="starting")
        snap2 = recorder.record(step="load", percent=50, message="loaded")
        snap3 = recorder.record(step="done", percent=100, message="finished")

        snapshots = recorder.snapshots
        assert len(snapshots) == 3
        assert snapshots[0] == snap1
        assert snapshots[1] == snap2
        assert snapshots[2] == snap3

    def test_recorded_snapshots_are_progress_snapshot_instances(self) -> None:
        recorder = WorkflowProgressRecorder(workflow_id="wf-1")
        snap = recorder.record(step="init", percent=0, message="starting")
        assert isinstance(snap, ProgressSnapshot)

    def test_workflow_id_propagates_to_snapshots(self) -> None:
        recorder = WorkflowProgressRecorder(workflow_id="wf-xyz")
        snap = recorder.record(step="init", percent=0, message="starting")
        assert snap.workflow_id == "wf-xyz"

    def test_latest_returns_most_recent_snapshot(self) -> None:
        recorder = WorkflowProgressRecorder(workflow_id="wf-1")
        recorder.record(step="init", percent=0, message="starting")
        snap2 = recorder.record(step="load", percent=50, message="loaded")
        assert recorder.latest() == snap2

    def test_latest_returns_none_when_empty(self) -> None:
        recorder = WorkflowProgressRecorder(workflow_id="wf-1")
        assert recorder.latest() is None

    def test_clear_empties_recordings(self) -> None:
        recorder = WorkflowProgressRecorder(workflow_id="wf-1")
        recorder.record(step="init", percent=0, message="starting")
        recorder.clear()
        assert recorder.snapshots == []
        assert recorder.latest() is None

    def test_clear_does_not_reset_workflow_id(self) -> None:
        recorder = WorkflowProgressRecorder(workflow_id="wf-1")
        recorder.clear()
        assert recorder.workflow_id == "wf-1"

    def test_percent_validation_inside_recorder(self) -> None:
        recorder = WorkflowProgressRecorder(workflow_id="wf-1")
        with pytest.raises(ValueError, match="percent"):
            recorder.record(step="bad", percent=200, message="oops")


# ---------------------------------------------------------------------------
# Module-level convenience functions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_progress_snapshot_attaches_to_module_recorders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The module-level helper must keep a per-workflow recorder so that
    `list_progress_snapshots` returns the snapshots in order across calls.
    """
    from mahavishnu.workflows import progress as progress_mod

    progress_mod._recorders.clear()  # type: ignore[attr-defined]

    snap = await record_progress_snapshot(
        workflow_id="wf-mod",
        step="init",
        percent=10,
        message="hello",
    )
    assert snap.workflow_id == "wf-mod"
    assert snap.percent == 10

    snapshots = await list_progress_snapshots("wf-mod")
    assert len(snapshots) == 1
    assert snapshots[0] == snap


@pytest.mark.asyncio
async def test_record_progress_snapshot_persists_to_dhara_when_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the substrate HTTP client returns a 2xx, we call it; this is
    the Workstream C stub — substrate is http_blocked so the call should
    be skipped gracefully without raising.
    """
    from mahavishnu.workflows import progress as progress_mod

    progress_mod._recorders.clear()  # type: ignore[attr-defined]

    # substrate unavailable → recorder still records, no exception raised
    snap = await record_progress_snapshot(
        workflow_id="wf-no-http",
        step="init",
        percent=10,
        message="hello",
    )
    assert snap.workflow_id == "wf-no-http"
    assert snap.percent == 10

    snapshots = await list_progress_snapshots("wf-no-http")
    assert len(snapshots) == 1
    assert snapshots[0] == snap


@pytest.mark.asyncio
async def test_record_progress_snapshot_tolerates_substrate_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Even when the substrate HTTP client raises, the recorder must
    persist the snapshot in-process so operators can still query locally.
    """
    from mahavishnu.workflows import progress as progress_mod

    progress_mod._recorders.clear()  # type: ignore[attr-defined]

    # Patch the persister to simulate substrate failure
    failing_persister = AsyncMock(
        side_effect=RuntimeError("http_blocked: substrate unavailable"),
    )
    monkeypatch.setattr(progress_mod, "_persister", failing_persister)

    snap = await record_progress_snapshot(
        workflow_id="wf-fail",
        step="init",
        percent=10,
        message="hello",
    )
    # In-process recorder still has the snapshot
    snapshots = await list_progress_snapshots("wf-fail")
    assert len(snapshots) == 1
    assert snapshots[0] == snap


def test_module_exports() -> None:
    """The module's public surface must include the documented symbols."""
    from mahavishnu.workflows import progress as progress_mod

    for name in (
        "ProgressSnapshot",
        "WorkflowProgressRecorder",
        "record_progress_snapshot",
        "list_progress_snapshots",
    ):
        assert hasattr(progress_mod, name), f"missing public symbol: {name}"


# ---------------------------------------------------------------------------
# CLI watch stub
# ---------------------------------------------------------------------------


class TestCLIWatchStub:
    def test_cli_app_is_typer_instance(self) -> None:
        import typer as typer_mod

        from mahavishnu.workflows.cli_watch import watch_app

        assert isinstance(watch_app, typer_mod.Typer)

    def test_watch_command_emits_current_snapshot_once(self) -> None:
        """`workflow watch <id> --once` prints snapshots and exits."""
        from typer.testing import CliRunner

        from mahavishnu.workflows import progress as progress_mod
        from mahavishnu.workflows.cli_watch import watch_app

        progress_mod._recorders.clear()  # type: ignore[attr-defined]

        async def _seed() -> None:
            await progress_mod.record_progress_snapshot(
                workflow_id="wf-cli",
                step="init",
                percent=10,
                message="hello",
            )
            await progress_mod.record_progress_snapshot(
                workflow_id="wf-cli",
                step="done",
                percent=100,
                message="bye",
            )

        asyncio_mod = __import__("asyncio")
        asyncio_mod.run(_seed())

        result = CliRunner().invoke(watch_app, ["watch", "wf-cli", "--once"])
        assert result.exit_code == 0
        assert "wf-cli" in result.output
        assert "init" in result.output
        assert "done" in result.output
        assert "hello" in result.output
        assert "bye" in result.output

    def test_emit_command_records_via_persister(self) -> None:
        """`workflow emit <id>` records a snapshot through the public API."""
        from typer.testing import CliRunner

        from mahavishnu.workflows import progress as progress_mod
        from mahavishnu.workflows.cli_watch import watch_app

        progress_mod._recorders.clear()  # type: ignore[attr-defined]

        result = CliRunner().invoke(
            watch_app,
            [
                "emit",
                "wf-cli-emit",
                "--step",
                "load",
                "--percent",
                "42",
                "--message",
                "halfway",
            ],
        )
        assert result.exit_code == 0
        assert "recorded snapshot" in result.output

        # Confirm it landed in the recorder
        asyncio_mod = __import__("asyncio")
        snaps = asyncio_mod.run(progress_mod.list_progress_snapshots("wf-cli-emit"))
        assert len(snaps) == 1
        assert snaps[0].step == "load"
        assert snaps[0].percent == 42
        assert snaps[0].message == "halfway"
