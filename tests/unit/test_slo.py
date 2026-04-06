"""Tests for core/slo.py — SLO calculations, thresholds, and reporting."""
from datetime import UTC, datetime, timedelta

import pytest

from mahavishnu.core.slo import (
    SLOCalculator,
    SLO_THRESHOLDS,
    check_slo_threshold,
    generate_slo_report,
    record_poll,
    record_reindex,
    record_event_published,
    record_event_delivered,
    set_service_up,
)


def _now() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------------------
# SLOCalculator.freshness_slo
# ---------------------------------------------------------------------------


class TestFreshnessSLO:
    def test_all_compliant(self):
        times = {f"repo{i}": _now() - timedelta(seconds=30) for i in range(10)}
        result = SLOCalculator.freshness_slo(times)
        assert result["compliance_pct"] == 100.0
        assert result["meets_slo"] is True
        assert result["violating_repos"] == []

    def test_none_compliant(self):
        times = {f"repo{i}": _now() - timedelta(hours=1) for i in range(5)}
        result = SLOCalculator.freshness_slo(times)
        assert result["compliance_pct"] == 0.0
        assert result["meets_slo"] is False
        assert len(result["violating_repos"]) == 5

    def test_partial_compliance(self):
        times = {
            "repo1": _now() - timedelta(seconds=30),  # compliant
            "repo2": _now() - timedelta(minutes=10),  # violating
        }
        result = SLOCalculator.freshness_slo(times)
        assert result["compliance_pct"] == 50.0
        assert result["compliant"] == 1
        assert result["total"] == 2
        assert len(result["violating_repos"]) == 1

    def test_empty_dict(self):
        result = SLOCalculator.freshness_slo({})
        assert result["compliance_pct"] == 100.0
        assert result["total"] == 0

    def test_custom_target_minutes(self):
        times = {"repo1": _now() - timedelta(minutes=3)}  # Within 5 min, but over 2 min
        result = SLOCalculator.freshness_slo(times, target_minutes=2)
        assert result["meets_slo"] is False


# ---------------------------------------------------------------------------
# SLOCalculator.polling_success_slo
# ---------------------------------------------------------------------------


class TestPollingSuccessSLO:
    def test_perfect_rate(self):
        data = {"repo1": {"success": 100, "failure": 0}}
        result = SLOCalculator.polling_success_slo(data)
        assert result["success_rate_pct"] == 100.0
        assert result["meets_slo"] is True

    def test_degraded(self):
        data = {"repo1": {"success": 98, "failure": 2}}
        result = SLOCalculator.polling_success_slo(data)
        assert result["success_rate_pct"] == 98.0
        assert result["meets_slo"] is False

    def test_empty_data(self):
        result = SLOCalculator.polling_success_slo({})
        assert result["success_rate_pct"] == 100.0

    def test_all_failures(self):
        data = {"repo1": {"success": 0, "failure": 10}}
        result = SLOCalculator.polling_success_slo(data)
        assert result["success_rate_pct"] == 0.0
        assert result["meets_slo"] is False

    def test_multiple_repos_aggregated(self):
        data = {
            "repo1": {"success": 90, "failure": 10},
            "repo2": {"success": 95, "failure": 5},
        }
        result = SLOCalculator.polling_success_slo(data)
        assert result["total_success"] == 185
        assert result["total_failure"] == 15
        assert result["success_rate_pct"] == 92.5


# ---------------------------------------------------------------------------
# SLOCalculator.availability_slo
# ---------------------------------------------------------------------------


class TestAvailabilitySLO:
    def test_empty_checks(self):
        result = SLOCalculator.availability_slo([])
        assert result["availability_pct"] == 100.0
        assert result["meets_slo"] is True

    def test_all_up(self):
        checks = [{"timestamp": _now() - timedelta(minutes=i * 5), "up": True} for i in range(10)]
        result = SLOCalculator.availability_slo(checks)
        assert result["availability_pct"] == 100.0
        assert result["meets_slo"] is True

    def test_with_downtime(self):
        now = _now()
        checks = [
            {"timestamp": now - timedelta(minutes=30), "up": True},
            {"timestamp": now - timedelta(minutes=20), "up": False},
            {"timestamp": now - timedelta(minutes=10), "up": True},
        ]
        result = SLOCalculator.availability_slo(checks, window_hours=1)
        assert result["downtime_seconds"] > 0
        # 10 min downtime in 1 hour = ~83.3% availability
        assert result["availability_pct"] < 100.0

    def test_currently_down(self):
        now = _now()
        checks = [
            {"timestamp": now - timedelta(minutes=10), "up": True},
            {"timestamp": now - timedelta(minutes=1), "up": False},
        ]
        result = SLOCalculator.availability_slo(checks, window_hours=1)
        assert result["downtime_seconds"] > 0

    def test_checks_outside_window(self):
        now = _now()
        checks = [
            {"timestamp": now - timedelta(hours=48), "up": False},  # Outside 24h window
        ]
        result = SLOCalculator.availability_slo(checks, window_hours=24)
        assert result["availability_pct"] == 100.0


# ---------------------------------------------------------------------------
# check_slo_threshold
# ---------------------------------------------------------------------------


class TestCheckSloThreshold:
    def test_ok_status(self):
        result = check_slo_threshold("freshness", 96.0)
        assert result["status"] == "ok"
        assert result["level"] == "info"

    def test_warning_status(self):
        # Freshness warning threshold is 90, so 91 should be ok, 89 should be warning
        result = check_slo_threshold("freshness", 89.0)
        assert result["status"] == "warning"
        assert result["level"] == "warning"

    def test_critical_status(self):
        result = check_slo_threshold("freshness", 80.0)
        assert result["status"] == "critical"
        assert result["level"] == "critical"

    def test_unknown_type(self):
        # Unknown type has no thresholds dict, so thresholds['warning'] raises KeyError
        # on the "warning" branch (line 367). This documents a known bug in check_slo_threshold
        # where it uses hardcoded key access instead of .get() on line 367.
        with pytest.raises(KeyError, match="warning"):
            check_slo_threshold("unknown_type", 50.0)


# ---------------------------------------------------------------------------
# SLO_THRESHOLDS
# ---------------------------------------------------------------------------


class TestSloThresholds:
    def test_all_types_defined(self):
        assert "freshness" in SLO_THRESHOLDS
        assert "polling" in SLO_THRESHOLDS
        assert "availability" in SLO_THRESHOLDS
        assert "event_delivery" in SLO_THRESHOLDS

    def test_thresholds_have_warning_and_critical(self):
        for slo_type, thresholds in SLO_THRESHOLDS.items():
            assert "warning" in thresholds
            assert "critical" in thresholds
            assert thresholds["warning"] > thresholds["critical"]


# ---------------------------------------------------------------------------
# generate_slo_report
# ---------------------------------------------------------------------------


class TestGenerateSloReport:
    def test_all_meet_slo(self):
        freshness = {"meets_slo": True, "compliance_pct": 96.0}
        polling = {"meets_slo": True, "success_rate_pct": 99.5}
        availability = {"meets_slo": True, "availability_pct": 99.95}
        report = generate_slo_report(freshness, polling, availability)
        assert report["overall_meets_slo"] is True
        assert "timestamp" in report

    def test_some_fail(self):
        freshness = {"meets_slo": False, "compliance_pct": 80.0}
        polling = {"meets_slo": True, "success_rate_pct": 99.5}
        availability = {"meets_slo": True, "availability_pct": 99.95}
        report = generate_slo_report(freshness, polling, availability)
        assert report["overall_meets_slo"] is False
        assert len(report["recommendations"]) > 0


# ---------------------------------------------------------------------------
# Metric recording functions (just verify no errors)
# ---------------------------------------------------------------------------


class TestMetricRecording:
    def test_record_poll_success(self):
        record_poll("repo1", "success", 0.5)

    def test_record_poll_failure(self):
        record_poll("repo1", "failure", 1.0)

    def test_record_reindex(self):
        record_reindex("repo1", "success", 5.0)

    def test_record_event_published(self):
        record_event_published("code.graph.indexed")

    def test_record_event_delivered(self):
        record_event_delivered("code.graph.indexed", "session-buddy", "success", 0.1)

    def test_set_service_up(self):
        set_service_up(True)
        set_service_up(False)
