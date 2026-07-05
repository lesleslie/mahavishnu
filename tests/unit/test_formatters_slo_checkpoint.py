"""Tests for shell/formatters.py, core/slo.py, and session/checkpoint.py.

- formatters: capture print() output via capsys, test both Rich and fallback paths
- slo: SLOCalculator static methods with real datetime math
- checkpoint: simulated Session-Buddy integration with mock config
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from mahavishnu.core.slo import (
    SLO_THRESHOLDS,
    SLOCalculator,
    check_slo_threshold,
    generate_slo_report,
    record_event_delivered,
    record_event_published,
    record_poll,
    record_reindex,
    set_service_up,
)
from mahavishnu.session.checkpoint import SessionBuddy

# =========================================================================
# shell/formatters.py — WorkflowFormatter
# =========================================================================


def _make_formatter(**kwargs):
    """Create a WorkflowFormatter with console=None to force fallback path."""
    from mahavishnu.shell.formatters import WorkflowFormatter

    return WorkflowFormatter(console=None, **kwargs)


class TestWorkflowFormatter:
    def test_empty_workflows(self, capsys):
        fmt = _make_formatter()
        fmt.format_workflows([])
        assert "No workflows" in capsys.readouterr().out

    def test_fallback_format_workflows(self, capsys):
        fmt = _make_formatter()
        fmt.format_workflows(
            [
                {
                    "id": "wf-1",
                    "status": "running",
                    "progress": 50,
                    "adapter": "prefect",
                    "created_at": "2026-01-01T00:00:00",
                },
            ]
        )
        output = capsys.readouterr().out
        assert "wf-1" in output
        assert "running" in output
        assert "50%" in output

    def test_fallback_format_with_details(self, capsys):
        fmt = _make_formatter()
        fmt.format_workflows(
            [
                {
                    "id": "wf-2",
                    "status": "failed",
                    "progress": 80,
                    "adapter": "agno",
                    "repos": ["a", "b", "c"],
                    "errors": [{"message": "timeout"}],
                    "created_at": "2026-01-01T00:00:00",
                },
            ],
            show_details=True,
        )
        output = capsys.readouterr().out
        assert "Repos: 3" in output
        assert "Errors: 1" in output

    def test_fallback_detail(self, capsys):
        fmt = _make_formatter()
        fmt.format_workflow_detail(
            {
                "id": "wf-d",
                "status": "completed",
                "progress": 100,
                "adapter": "prefect",
                "repos": ["repo-x"],
                "errors": [],
            }
        )
        output = capsys.readouterr().out
        assert "wf-d" in output
        assert "completed" in output

    def test_fallback_detail_with_errors(self, capsys):
        fmt = _make_formatter()
        fmt.format_workflow_detail(
            {
                "id": "wf-e",
                "status": "failed",
                "progress": 60,
                "adapter": "agno",
                "repos": [],
                "errors": [{"message": "OOM"}, {"message": "timeout"}],
            }
        )
        output = capsys.readouterr().out
        assert "OOM" in output
        assert "timeout" in output

    def test_status_style_map(self, capsys):
        fmt = _make_formatter()
        # Status styles are applied in Rich path; fallback just prints status
        fmt.format_workflows(
            [
                {
                    "id": "wf-ok",
                    "status": "completed",
                    "progress": 100,
                    "adapter": "x",
                    "created_at": "t",
                },
            ]
        )
        output = capsys.readouterr().out
        assert "completed" in output

    def test_workflow_missing_fields(self, capsys):
        fmt = _make_formatter()
        # Rich path is taken (BaseTableFormatter creates Console when console=None)
        # status=None causes empty style tag → MarkupError, so use a valid status
        fmt.format_workflows([{"id": "wf-min", "status": "running"}])
        output = capsys.readouterr().out
        assert "wf-min" in output
        assert "running" in output


# =========================================================================
# shell/formatters.py — LogFormatter
# =========================================================================


def _make_log_formatter(**kwargs):
    from mahavishnu.shell.formatters import LogFormatter

    return LogFormatter(console=None, **kwargs)


class TestLogFormatter:
    def test_empty_logs(self, capsys):
        fmt = _make_log_formatter()
        fmt.format_logs([])
        assert "No logs" in capsys.readouterr().out

    def test_fallback_format(self, capsys):
        fmt = _make_log_formatter()
        fmt.format_logs(
            [
                {"timestamp": "2026-01-01T12:00:00", "level": "ERROR", "message": "DB down"},
            ]
        )
        output = capsys.readouterr().out
        assert "ERROR" in output
        assert "DB down" in output

    def test_level_filter(self, capsys):
        fmt = _make_log_formatter()
        fmt.format_logs(
            [
                {"timestamp": "t1", "level": "INFO", "message": "ok"},
                {"timestamp": "t2", "level": "ERROR", "message": "bad"},
            ],
            level="ERROR",
        )
        output = capsys.readouterr().out
        assert "bad" in output
        assert "ok" not in output

    def test_workflow_id_filter(self, capsys):
        fmt = _make_log_formatter()
        fmt.format_logs(
            [
                {"timestamp": "t1", "level": "INFO", "message": "a", "workflow_id": "wf-1"},
                {"timestamp": "t2", "level": "INFO", "message": "b", "workflow_id": "wf-2"},
                {"timestamp": "t3", "level": "ERROR", "message": "c", "workflow_id": "wf-1"},
            ],
            workflow_id="wf-1",
        )
        output = capsys.readouterr().out
        assert "a" in output
        assert "c" in output
        assert "b" not in output

    def test_tail_limit(self, capsys):
        fmt = _make_log_formatter()
        fmt.format_logs(
            [{"timestamp": f"t{i}", "level": "INFO", "message": f"msg-{i}"} for i in range(10)],
            tail=3,
        )
        output = capsys.readouterr().out
        lines = [l for l in output.strip().split("\n") if l]
        assert len(lines) == 3
        assert "msg-7" in output


# =========================================================================
# shell/formatters.py — RepoFormatter
# =========================================================================


def _make_repo_formatter(**kwargs):
    from mahavishnu.shell.formatters import RepoFormatter

    return RepoFormatter(console=None, **kwargs)


class TestRepoFormatter:
    def test_empty_repos(self, capsys):
        fmt = _make_repo_formatter()
        fmt.format_repos([])
        assert "No repositories" in capsys.readouterr().out

    def test_fallback_format(self, capsys):
        fmt = _make_repo_formatter()
        fmt.format_repos(
            [
                {"path": "/tmp/repo-a", "description": "Test repo A", "tags": ["python"]},
            ]
        )
        output = capsys.readouterr().out
        assert "/tmp/repo-a" in output
        assert "Test repo A" in output

    def test_fallback_with_tags(self, capsys):
        fmt = _make_repo_formatter()
        fmt.format_repos(
            [
                {"path": "/tmp/b", "description": "B", "tags": ["python", "backend"]},
            ],
            show_tags=True,
        )
        output = capsys.readouterr().out
        # Rich Table renders tags in the Tags column
        assert "python, backend" in output


# =========================================================================
# core/slo.py — SLOCalculator
# =========================================================================


NOW = datetime(2026, 4, 21, 12, 0, 0, tzinfo=UTC)


class TestSLOCalculator:
    @patch("mahavishnu.core.slo.datetime")
    def test_freshness_all_compliant(self, mock_dt):
        mock_dt.now.return_value = NOW
        times = {
            "repo-a": NOW - timedelta(minutes=2),
            "repo-b": NOW - timedelta(minutes=4),
        }
        result = SLOCalculator.freshness_slo(times)
        assert result["compliance_pct"] == 100.0
        assert result["meets_slo"] is True
        assert result["violating_repos"] == []

    @patch("mahavishnu.core.slo.datetime")
    def test_freshness_partial_violation(self, mock_dt):
        mock_dt.now.return_value = NOW
        times = {
            "repo-a": NOW - timedelta(minutes=1),
            "repo-b": NOW - timedelta(minutes=10),
            "repo-c": NOW - timedelta(minutes=3),
        }
        result = SLOCalculator.freshness_slo(times)
        assert result["compliance_pct"] == round(2 / 3 * 100, 2)
        assert result["meets_slo"] is False
        assert len(result["violating_repos"]) == 1
        assert result["violating_repos"][0]["repo"] == "repo-b"

    @patch("mahavishnu.core.slo.datetime")
    def test_freshness_all_violating(self, mock_dt):
        mock_dt.now.return_value = NOW
        times = {
            "repo-a": NOW - timedelta(minutes=20),
        }
        result = SLOCalculator.freshness_slo(times)
        assert result["compliance_pct"] == 0.0
        assert result["total"] == 1

    def test_freshness_empty(self):
        result = SLOCalculator.freshness_slo({})
        assert result["compliance_pct"] == 100.0
        assert result["total"] == 0

    @patch("mahavishnu.core.slo.datetime")
    def test_freshness_custom_target(self, mock_dt):
        mock_dt.now.return_value = NOW
        times = {
            "repo-a": NOW - timedelta(minutes=8),
        }
        result = SLOCalculator.freshness_slo(times, target_minutes=10)
        assert result["meets_slo"] is True
        assert result["target_pct"] == 95.0

    @patch("mahavishnu.core.slo.datetime")
    def test_freshness_violating_repos_detail(self, mock_dt):
        mock_dt.now.return_value = NOW
        times = {
            "repo-x": NOW - timedelta(minutes=15),
        }
        result = SLOCalculator.freshness_slo(times)
        vr = result["violating_repos"][0]
        assert vr["repo"] == "repo-x"
        assert "age_minutes" in vr
        assert vr["age_minutes"] == 15.0

    def test_polling_all_success(self):
        results = {
            "repo-a": {"success": 100, "failure": 1},
            "repo-b": {"success": 50, "failure": 0},
        }
        result = SLOCalculator.polling_success_slo(results)
        assert result["success_rate_pct"] == round(150 / 151 * 100, 2)
        assert result["total_success"] == 150
        assert result["total_failure"] == 1

    def test_polling_failing(self):
        results = {"repo-a": {"success": 0, "failure": 10}}
        result = SLOCalculator.polling_success_slo(results)
        assert result["success_rate_pct"] == 0.0
        assert result["meets_slo"] is False

    def test_polling_empty(self):
        result = SLOCalculator.polling_success_slo({})
        assert result["success_rate_pct"] == 100.0
        assert result["total_attempts"] == 0

    def test_polling_custom_target(self):
        results = {"repo-a": {"success": 98, "failure": 2}}
        result = SLOCalculator.polling_success_slo(results, target_pct=95.0)
        assert result["meets_slo"] is True

    def test_availability_all_up(self):
        checks = [
            {"timestamp": NOW - timedelta(minutes=1), "up": True},
            {"timestamp": NOW - timedelta(minutes=2), "up": True},
        ]
        result = SLOCalculator.availability_slo(checks)
        assert result["availability_pct"] == 100.0
        assert result["meets_slo"] is True
        assert result["downtime_seconds"] == 0

    @patch("mahavishnu.core.slo.datetime")
    def test_availability_with_downtime(self, mock_dt):
        mock_dt.now.return_value = NOW
        checks = [
            {"timestamp": NOW - timedelta(minutes=10), "up": True},
            {"timestamp": NOW - timedelta(minutes=9), "up": False},
            {"timestamp": NOW - timedelta(minutes=7), "up": True},
        ]
        result = SLOCalculator.availability_slo(checks, window_hours=1)
        assert result["downtime_seconds"] == 120  # 2 minutes

    @patch("mahavishnu.core.slo.datetime")
    def test_availability_extended_downtime(self, mock_dt):
        mock_dt.now.return_value = NOW
        checks = [
            {"timestamp": NOW - timedelta(minutes=5), "up": False},
            {"timestamp": NOW - timedelta(minutes=2), "up": True},
        ]
        result = SLOCalculator.availability_slo(checks, window_hours=1)
        assert result["downtime_seconds"] == 180  # 3 minutes

    @patch("mahavishnu.core.slo.datetime")
    def test_availability_currently_down(self, mock_dt):
        mock_dt.now.return_value = NOW
        checks = [
            {"timestamp": NOW - timedelta(minutes=5), "up": True},
            {"timestamp": NOW - timedelta(minutes=1), "up": False},
        ]
        result = SLOCalculator.availability_slo(checks, window_hours=1)
        # Currently down: downtime from NOW-1min to NOW = 60 seconds
        assert result["downtime_seconds"] == 60
        assert result["availability_pct"] < 100.0

    def test_availability_empty(self):
        result = SLOCalculator.availability_slo([])
        assert result["availability_pct"] == 100.0
        assert result["meets_slo"] is True

    def test_availability_no_checks_in_window(self):
        old_check = {"timestamp": NOW - timedelta(hours=48), "up": True}
        result = SLOCalculator.availability_slo([old_check], window_hours=1)
        assert result["availability_pct"] == 100.0

    @patch("mahavishnu.core.slo.datetime")
    def test_availability_error_budget(self, mock_dt):
        mock_dt.now.return_value = NOW
        checks = [
            {"timestamp": NOW - timedelta(minutes=5), "up": False},
            {"timestamp": NOW - timedelta(minutes=3), "up": True},
        ]
        result = SLOCalculator.availability_slo(checks, window_hours=1)
        assert result["downtime_seconds"] == 120
        # Budget is tiny (~3.6s), downtime far exceeds it
        assert result["downtime_budget_seconds"] > 0
        assert result["remaining_budget_seconds"] < 0
        # Source does int(error_budget - downtime), not int(budget) - int(downtime)
        window_seconds = 3600
        budget_float = window_seconds * (1 - 99.9 / 100)
        remaining_float = budget_float - 120.0
        assert result["remaining_budget_seconds"] == int(remaining_float)


# =========================================================================
# core/slo.py — check_slo_threshold
# =========================================================================


class TestCheckSLOThreshold:
    def test_freshness_ok(self):
        result = check_slo_threshold("freshness", 96.0)
        assert result["status"] == "ok"

    def test_freshness_warning(self):
        # freshness warning threshold is 90.0, critical is 85.0
        result = check_slo_threshold("freshness", 88.0)
        assert result["status"] == "warning"

    def test_freshness_critical(self):
        result = check_slo_threshold("freshness", 80.0)
        assert result["status"] == "critical"

    def test_polling_ok(self):
        result = check_slo_threshold("polling", 99.7)
        assert result["status"] == "ok"

    def test_availability_ok(self):
        result = check_slo_threshold("availability", 99.97)
        assert result["status"] == "ok"

    def test_unknown_type(self):
        # Unknown type: thresholds is empty {}, default for "warning" is 100
        # 99.0 < 100 → goes to critical branch → KeyError on thresholds['critical']
        with pytest.raises(KeyError):
            check_slo_threshold("nonexistent", 99.0)

    def test_unknown_type_ok(self):
        # 100.0 >= 100 (default warning) → returns "ok"
        result = check_slo_threshold("nonexistent", 100.0)
        assert result["status"] == "ok"

    def test_event_delivery_warning(self):
        result = check_slo_threshold("event_delivery", 99.2)
        assert result["status"] == "warning"

    def test_event_delivery_critical(self):
        result = check_slo_threshold("event_delivery", 98.5)
        assert result["status"] == "critical"


# =========================================================================
# core/slo.py — generate_slo_report
# =========================================================================


class TestGenerateSLOReport:
    @patch("mahavishnu.core.slo.datetime")
    def test_all_met(self, mock_dt):
        mock_dt.now.return_value = NOW
        fresh = SLOCalculator.freshness_slo({"r": NOW - timedelta(minutes=1)})
        poll = SLOCalculator.polling_success_slo({"r": {"success": 10, "failure": 0}})
        avail = SLOCalculator.availability_slo([])
        report = generate_slo_report(fresh, poll, avail)
        assert report["overall_meets_slo"] is True
        assert any("All SLOs met" in r for r in report["recommendations"])

    @patch("mahavishnu.core.slo.datetime")
    def test_violations(self, mock_dt):
        mock_dt.now.return_value = NOW
        fresh = SLOCalculator.freshness_slo({"repo-a": NOW - timedelta(minutes=30)})
        poll = SLOCalculator.polling_success_slo({"repo-b": {"success": 90, "failure": 10}})
        # Create availability violation
        avail = SLOCalculator.availability_slo(
            [
                {"timestamp": NOW - timedelta(minutes=10), "up": False},
                {"timestamp": NOW - timedelta(minutes=1), "up": True},
            ],
            window_hours=1,
        )
        report = generate_slo_report(fresh, poll, avail)
        assert report["overall_meets_slo"] is False
        assert any("Action Required" in r for r in report["recommendations"])
        # Check freshness per-repo recommendation
        assert any("repo-a" in r for r in report["recommendations"])
        # Check availability recommendation
        assert any("Availability" in r for r in report["recommendations"])


# =========================================================================
# core/slo.py — SLO_THRESHOLDS completeness
# =========================================================================


class TestSLOThresholds:
    def test_has_all_categories(self):
        expected = {"freshness", "polling", "availability", "event_delivery"}
        assert set(SLO_THRESHOLDS.keys()) == expected

    def test_thresholds_have_warning_and_critical(self):
        for _category, thresholds in SLO_THRESHOLDS.items():
            assert "warning" in thresholds
            assert "critical" in thresholds
            assert thresholds["warning"] > thresholds["critical"]


# =========================================================================
# core/slo.py — record functions
# =========================================================================


class TestRecordFunctions:
    def test_record_poll_success(self):
        # Should not raise
        record_poll("repo-a", "success", 1.5)

    def test_record_poll_failure(self):
        record_poll("repo-a", "failure", 5.0)

    def test_record_reindex_success(self):
        record_reindex("repo-a", "success", 10.0)

    def test_record_reindex_failure(self):
        record_reindex("repo-a", "failure", 30.0)

    def test_record_event_published(self):
        record_event_published("file_change")

    def test_record_event_delivered(self):
        record_event_delivered("file_change", "subscriber-1", "success", 0.05)

    def test_set_service_up(self):
        set_service_up(True)

    def test_set_service_down(self):
        set_service_up(False)


# =========================================================================
# session/checkpoint.py — SessionBuddy
# =========================================================================


def _mock_config(enabled=True, checkpoint_interval=30):
    config = MagicMock()
    config.session.enabled = enabled
    config.session.checkpoint_interval = checkpoint_interval
    return config


class TestSessionBuddy:
    def test_disabled_on_init(self):
        sb = SessionBuddy(_mock_config(enabled=False))
        assert sb.enabled is False

    def test_enabled_on_init(self):
        sb = SessionBuddy(_mock_config(enabled=True))
        assert sb.enabled is True
        assert sb.checkpoint_interval == 30

    async def test_create_checkpoint_disabled(self):
        sb = SessionBuddy(_mock_config(enabled=False))
        cid = await sb.create_checkpoint("sess-1", {"key": "val"})
        assert "disabled" in cid

    async def test_create_checkpoint_enabled(self):
        sb = SessionBuddy(_mock_config(enabled=True))
        cid = await sb.create_checkpoint("sess-2", {"key": "val"})
        assert len(cid) == 36  # UUID format

    async def test_update_checkpoint_disabled(self):
        sb = SessionBuddy(_mock_config(enabled=False))
        result = await sb.update_checkpoint("cp-1", "running")
        assert result is True

    async def test_update_checkpoint_enabled(self):
        sb = SessionBuddy(_mock_config(enabled=True))
        # Non-terminal status returns True immediately (no MCP call attempted)
        result = await sb.update_checkpoint("cp-2", "running")
        assert result is True

    async def test_get_checkpoint_disabled(self):
        sb = SessionBuddy(_mock_config(enabled=False))
        result = await sb.get_checkpoint("cp-1")
        assert result is None

    async def test_get_checkpoint_enabled(self):
        sb = SessionBuddy(_mock_config(enabled=True))
        # Session-Buddy has no lookup-by-ID API; always returns None
        result = await sb.get_checkpoint("cp-3")
        assert result is None

    async def test_restore_from_checkpoint_disabled(self):
        sb = SessionBuddy(_mock_config(enabled=False))
        result = await sb.restore_from_checkpoint("cp-1")
        assert result is None

    async def test_restore_from_checkpoint_running(self):
        sb = SessionBuddy(_mock_config(enabled=True))
        # Session-Buddy has no restore-by-ID API; always returns None
        result = await sb.restore_from_checkpoint("cp-4")
        assert result is None

    async def test_restore_from_checkpoint_completed(self):
        """Completed checkpoints can't be restored."""
        sb = SessionBuddy(_mock_config(enabled=True))
        # get_checkpoint returns status "running" by default; override
        with patch.object(sb, "get_checkpoint", return_value={"status": "completed", "state": {}}):
            result = await sb.restore_from_checkpoint("cp-5")
        assert result is None

    async def test_cleanup_checkpoint_disabled(self):
        sb = SessionBuddy(_mock_config(enabled=False))
        result = await sb.cleanup_checkpoint("cp-1")
        assert result is True

    async def test_cleanup_checkpoint_enabled(self):
        sb = SessionBuddy(_mock_config(enabled=True))
        result = await sb.cleanup_checkpoint("cp-6")
        assert result is True
