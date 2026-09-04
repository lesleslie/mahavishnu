"""Coverage tests for mahavishnu.core.budget_watchdog.

The :mod:`mahavishnu.core.budget_watchdog` module ships an in-memory
``InMemoryBudgetStore`` plus an async ``run_watchdog_cycle`` kernel
designed for unit-test use. These tests exercise the public surface
(test fake + cycle + lease semantics) without spinning up the real
Dhara substrate. The original tests live under ``tests/budget/``; this
file exists only to give the public surface coverage without modifying
the existing suite.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from mahavishnu.cli.sop_cli import sop_app
from mahavishnu.core.budget import BudgetRecord, BudgetState, BudgetUsage
from mahavishnu.core.budget_watchdog import (
    InMemoryBudgetStore,
    WatchdogCycleResult,
    WatchdogMetrics,
    run_watchdog_cycle,
)
from mahavishnu.quality.anti_ai_flavor_check import run_anti_ai_flavor_check
from mahavishnu.settle.persistence import (
    _dead_letter_append,
    _dead_letter_load,
    load_record_sync,
    persist_initial,
    persist_initial_async,
    persist_transition,
    settle_key,
)
from mahavishnu.settle.state_machine import (
    Binding,
    SettleAction,
    SettleRunRecord,
    SettleState,
)


def _run(coro):
    """Helper to drive coroutines from sync tests."""
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture
def store() -> InMemoryBudgetStore:
    return InMemoryBudgetStore()


class TestInMemoryBudgetStoreBasic:
    async def test_get_and_put_round_trip(self, store: InMemoryBudgetStore) -> None:
        await store.put("k", {"v": 1})
        assert await store.get("k") == {"v": 1}

    async def test_get_missing_returns_none(self, store: InMemoryBudgetStore) -> None:
        assert await store.get("missing") is None

    async def test_put_wraps_non_dict(self, store: InMemoryBudgetStore) -> None:
        await store.put("k", "value")
        assert await store.get("k") == {"value": "value"}

    async def test_put_with_ttl_attaches_expiry(self, store: InMemoryBudgetStore) -> None:
        await store.put("k", {"v": 1}, ttl_seconds=60)
        stored = await store.get("k")
        assert stored is not None
        assert stored.get("ttl_seconds") == 60
        assert "expires_at" in stored

    async def test_list_keys_strips_prefix(self, store: InMemoryBudgetStore) -> None:
        await store.put("pfx/a", {"v": 1})
        await store.put("pfx/b", {"v": 2})
        await store.put("other/c", {"v": 3})
        keys = await store.list_keys("pfx/")
        assert sorted(keys) == ["a", "b"]


class TestInMemoryBudgetStoreLeases:
    async def test_acquire_then_release(self, store: InMemoryBudgetStore) -> None:
        assert await store.try_acquire_lease("L", "h1", ttl_seconds=60) is True
        await store.release_lease("L", "h1")

    async def test_acquire_held_by_other_returns_false(
        self, store: InMemoryBudgetStore
    ) -> None:
        assert await store.try_acquire_lease("L", "h1", ttl_seconds=60) is True
        assert await store.try_acquire_lease("L", "h2", ttl_seconds=60) is False

    async def test_release_by_non_holder_is_noop(
        self, store: InMemoryBudgetStore
    ) -> None:
        await store.try_acquire_lease("L", "h1", ttl_seconds=60)
        # Releasing as a different holder should not clear the lease.
        await store.release_lease("L", "h2")
        # h1 can still re-acquire (it's idempotent / refresh).
        assert await store.try_acquire_lease("L", "h1", ttl_seconds=60) is True


class TestInMemoryBudgetStoreSeedingAndFailure:
    async def test_seed_record_persists(self, store: InMemoryBudgetStore) -> None:
        record = BudgetRecord(
            workflow_id="wf-1",
            state=BudgetState.ACTIVE,
            started_at=datetime.now(UTC),
        )
        store.seed_record(record)
        stored = await store.get("mahavishni://budgets/wf-1.json")
        assert stored is not None
        assert stored["state"] == "active"

    async def test_fail_next_op_simulates_dhara_down(
        self, store: InMemoryBudgetStore
    ) -> None:
        store.fail_next_op = "put"
        with pytest.raises(RuntimeError, match="simulated"):
            await store.put("k", {"v": 1})

    async def test_fail_next_op_consumed_after_one_shot(
        self, store: InMemoryBudgetStore
    ) -> None:
        store.fail_next_op = "get"
        with pytest.raises(RuntimeError):
            await store.get("k")
        # Second call should not raise.
        await store.get("k")


class TestRunWatchdogCycleHappyPath:
    async def test_empty_store_returns_no_records(
        self, store: InMemoryBudgetStore
    ) -> None:
        async def usage_source(_workflow_id: str):
            return None

        result = await run_watchdog_cycle(
            store=store,
            holder="h1",
            lease_ttl_seconds=60,
            usage_source=usage_source,
        )
        assert isinstance(result, WatchdogCycleResult)
        assert result.lease_acquired is True
        assert result.records_scanned == 0
        assert result.records_transitioned == 0

    async def test_cycle_increments_cycles_metric(
        self, store: InMemoryBudgetStore
    ) -> None:
        metrics = WatchdogMetrics()

        async def usage_source(_workflow_id: str):
            return None

        await run_watchdog_cycle(
            store=store,
            holder="h1",
            lease_ttl_seconds=60,
            usage_source=usage_source,
            metrics=metrics,
        )
        assert metrics.cycles == 1


class TestAntiAiFlavorCheck:
    """Smoke tests for the crackerjack skill entry point."""

    def test_returns_violations_and_sop_source(self) -> None:
        with TemporaryDirectory() as root:
            file_path = Path(root) / "mr.md"
            file_path.write_text("Co-Authored-By: Claude\n")
            result = run_anti_ai_flavor_check(
                "Co-Authored-By: Claude\n", file_path
            )
            assert "violations" in result
            assert "sop_source" in result
            # The packaged default SOP bans "Co-Authored-By:\s*Claude"
            assert any(
                "Co-Authored-By" in v.get("pattern", "")
                for v in result["violations"]
            )

    def test_clean_content_has_no_violations(self) -> None:
        with TemporaryDirectory() as root:
            file_path = Path(root) / "mr.md"
            file_path.write_text("")
            result = run_anti_ai_flavor_check(
                "Just plain narrative text with no banned patterns.",
                file_path,
            )
            assert result["violations"] == []


class TestSOPCliCommands:
    """Smoke tests for the SOP evolution Typer CLI."""

    def test_sop_list_empty(self) -> None:
        runner = CliRunner()
        result = runner.invoke(sop_app, ["list", "--project", "empty-proj"])
        assert result.exit_code == 0
        assert "(none)" in result.stdout

    def test_sop_list_json_output(self) -> None:
        runner = CliRunner()
        result = runner.invoke(
            sop_app, ["list", "--project", "json-proj", "--json"]
        )
        assert result.exit_code == 0
        # JSON should mention the project id and contain "sops" key.
        assert "json-proj" in result.stdout
        assert '"sops"' in result.stdout

    def test_sop_show_missing_exits_nonzero(self) -> None:
        runner = CliRunner()
        result = runner.invoke(
            sop_app, ["show", "--project", "any", "--name", "missing-sop"]
        )
        assert result.exit_code != 0
        assert "not found" in result.stdout.lower() or "ERROR" in result.stdout

    def test_sop_propose_with_no_failure_modes(self) -> None:
        runner = CliRunner()
        result = runner.invoke(
            sop_app, ["propose", "--project", "any", "--threshold", "3"]
        )
        assert result.exit_code == 0
        assert "No new suggestions" in result.stdout or "0 failure-mode" in result.stdout


class TestBackupCLICommands:
    """Smoke tests for the backup CLI's internal ``_do_*`` helpers."""

    def test_do_backup_list_no_backups(self) -> None:
        from unittest.mock import AsyncMock, MagicMock

        from mahavishnu import backup_cli

        fake_app = MagicMock(name="MahavishnuApp")
        fake_manager = MagicMock(name="BackupManager")
        fake_manager.list_backups = AsyncMock(return_value=[])
        fake_manager_cls = MagicMock(return_value=fake_manager)
        fake_app_cls = MagicMock(return_value=fake_app)

        with (
            patch.dict(
                "sys.modules",
                {
                    "mahavishnu.core.app": MagicMock(
                        MahavishnuApp=fake_app_cls
                    ),
                    "mahavishnu.core.backup_recovery": MagicMock(
                        BackupManager=fake_manager_cls
                    ),
                },
            ),
        ):
            import importlib

            importlib.reload(backup_cli)
            try:
                backup_cli._do_backup_list()
            finally:
                importlib.reload(backup_cli)

    def test_do_backup_restore_failure_exits_nonzero(self) -> None:
        from typer import Exit as TyperExit

        from mahavishnu import backup_cli

        fake_manager = MagicMock(name="BackupManager")
        fake_manager.restore_backup = AsyncMock(return_value=False)
        fake_app = MagicMock(name="MahavishnuApp")

        with (
            patch.object(backup_cli, "MahavishnuApp", fake_app, create=True),
            patch.object(backup_cli, "BackupManager", fake_manager, create=True),
        ):
            with pytest.raises((SystemExit, TyperExit)):
                backup_cli._do_backup_restore("missing-backup-id")


class TestSettlePersistence:
    """Smoke tests for ``mahavishnu.settle.persistence`` using a fake Dhara."""

    def _make_record(self, run_ref: str = "run-1") -> SettleRunRecord:
        now = datetime.now(UTC)
        return SettleRunRecord(
            run_ref=run_ref,
            worker_id="w-1",
            task_signature="sig-1",
            bindings=(Binding(path="src/a.py", base="old-content"),),
            state=SettleState.PROPOSED,
            created_at=now,
            updated_at=now,
            transitions=(
                {
                    "from": SettleState.PROPOSED.value,
                    "to": SettleState.SELECTED.value,
                },
            ),
        )

    def test_settle_key_format(self) -> None:
        assert settle_key("run-x") == "settle/v1/run-x"

    def test_persist_initial_writes_dead_letter_when_no_dhara(self) -> None:
        record = self._make_record()
        with TemporaryDirectory() as dl_root:
            with patch(
                "mahavishnu.settle.persistence.SETTLE_DEAD_LETTER_DIR",
                Path(dl_root),
            ):
                returned = persist_initial(record, dhara=None)
                assert returned is record
                # Dead-letter file should exist.
                files = list(Path(dl_root).iterdir())
                assert len(files) == 1
                # Round-trip via _dead_letter_load.
                loaded = _dead_letter_load("run-1")
                assert loaded is not None
                assert loaded.run_ref == "run-1"

    def test_persist_initial_async_with_dhara(self) -> None:
        record = self._make_record()
        fake_dhara = MagicMock()
        fake_dhara.put = AsyncMock(return_value=None)
        # Run in a fresh loop to avoid "loop closed" issues.
        loop = asyncio.new_event_loop()
        try:
            returned = loop.run_until_complete(
                persist_initial_async(record, dhara=fake_dhara)
            )
            assert returned is record
            fake_dhara.put.assert_awaited_once()
        finally:
            loop.close()

    def test_persist_transition_with_dhara(self) -> None:
        record = self._make_record("run-2")
        fake_dhara = MagicMock()
        fake_dhara.put = AsyncMock(return_value=None)
        loop = asyncio.new_event_loop()
        try:
            returned = loop.run_until_complete(
                persist_transition(record, dhara=fake_dhara)
            )
            assert returned is record
            fake_dhara.put.assert_awaited_once()
        finally:
            loop.close()

    def test_load_record_sync_falls_back_to_dead_letter(self) -> None:
        record = self._make_record("run-3")
        with TemporaryDirectory() as dl_root:
            with patch(
                "mahavishnu.settle.persistence.SETTLE_DEAD_LETTER_DIR",
                Path(dl_root),
            ):
                _dead_letter_append(record)
                loaded = load_record_sync("run-3", dhara=None)
                assert loaded is not None
                assert loaded.run_ref == "run-3"
                assert loaded.bindings[0].path == "src/a.py"


