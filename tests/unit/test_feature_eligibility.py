"""Tests for scripts/feature_eligibility.py (REQ-007)."""
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest


# Load scripts/feature_eligibility.py as a module so the tests don't
# require `mahavishnu` on sys.path. Mirrors the pattern used by
# tests/unit/test_audit_type_checking_runtime_refs.py.
SCRIPT_PATH = Path(__file__).resolve().parent.parent.parent / "scripts" / "feature_eligibility.py"
SPEC = importlib.util.spec_from_file_location("feature_eligibility", SCRIPT_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"could not load {SCRIPT_PATH}")
feature_eligibility = importlib.util.module_from_spec(SPEC)
sys.modules["feature_eligibility"] = feature_eligibility
SPEC.loader.exec_module(feature_eligibility)


@pytest.fixture
def plan_root(tmp_path: Path) -> Path:
    """Create a plan_root with followup and feature-tracking docs."""
    followups = tmp_path / "docs" / "followups"
    followups.mkdir(parents=True)
    feature_tracking = tmp_path / "docs" / "feature-tracking"
    feature_tracking.mkdir(parents=True)
    return tmp_path


def _write_followup(plan_root: Path, trigger_name: str, status: str) -> None:
    filename = feature_eligibility.FOLLOWUP_FILENAME_FOR_TRIGGER[trigger_name]
    path = plan_root / "docs" / "followups" / filename
    path.write_text(
        f"---\nstatus: {status}\nrole: deferred\n"
        f"date: 2026-09-10\ntopic: tier2-{trigger_name}\n---\n\n# stub\n",
        encoding="utf-8",
    )


def _write_phase8(plan_root: Path, status: str) -> None:
    path = plan_root / "docs" / "feature-tracking" / "2026-09-10-observability-changepoint.md"
    path.write_text(
        f"---\nstatus: {status}\nname: changepoint\nrole: implementation\n"
        f"date: 2026-09-10\nlast_reviewed: 2026-09-10\nowner: ops\n---\n\n# stub\n",
        encoding="utf-8",
    )


def test_clean_run_no_triggers_fired(plan_root: Path) -> None:
    """No MCP config + no requests log + no followups: all triggers below/unknown, exit 0."""
    report = feature_eligibility.build_report(plan_root, requests_log=plan_root / "no.log", mcp_config=None)
    assert report.triggers_fired == 0
    assert report.followon_plans_missing == 0
    # optimal_transport: unknown (no data)
    assert report.triggers[0].state == "unknown"
    # multi_metric_drift: below (no log file)
    assert report.triggers[3].state == "below"
    # summary line renders correctly
    summary = feature_eligibility.format_human_report(report).splitlines()[-1]
    assert summary == "triggers_fired=0 followon_plans_missing=0"


def test_optimal_transport_below_threshold(plan_root: Path) -> None:
    """5000 < 10000 -> below, fired=False."""
    _write_followup(plan_root, "optimal_transport", "active")
    cfg = {"akosha_patterns_cross_system_snapshot_count": 5000}
    report = feature_eligibility.build_report(plan_root, plan_root / "no.log", cfg)
    trig = report.triggers[0]
    assert trig.name == "optimal_transport"
    assert trig.state == "below"
    assert trig.fired is False
    assert trig.followup_exists is True
    assert trig.followup_status == "active"
    assert report.triggers_fired == 0
    assert report.followon_plans_missing == 0


def test_optimal_transport_fires_followup_exists(plan_root: Path) -> None:
    """20000 >= 10000 -> above, fired=True, followup active -> followon_plans_missing=0."""
    _write_followup(plan_root, "optimal_transport", "active")
    cfg = {"akosha_patterns_cross_system_snapshot_count": 20_000}
    report = feature_eligibility.build_report(plan_root, plan_root / "no.log", cfg)
    trig = report.triggers[0]
    assert trig.state == "above"
    assert trig.fired is True
    assert report.triggers_fired == 1
    assert report.followon_plans_missing == 0


def test_optimal_transport_fires_followup_missing(plan_root: Path) -> None:
    """20000 >= 10000 -> above but no followup doc -> followon_plans_missing=1."""
    cfg = {"akosha_patterns_cross_system_snapshot_count": 20_000}
    report = feature_eligibility.build_report(plan_root, plan_root / "no.log", cfg)
    assert report.triggers[0].fired is True
    assert report.triggers[0].followup_exists is False
    assert report.followon_plans_missing == 1


def test_hyperbolic_requires_both_thresholds(plan_root: Path) -> None:
    """Coverage OK but nodes below threshold -> still below."""
    cfg = {
        "session_buddy_code_graph_node_count": 5000,
        "session_buddy_code_graph_coverage": 0.65,
    }
    report = feature_eligibility.build_report(plan_root, plan_root / "no.log", cfg)
    trig = report.triggers[1]
    assert trig.state == "below"
    assert trig.fired is False


def test_hyperbolic_fires_when_both_clear(plan_root: Path) -> None:
    cfg = {
        "session_buddy_code_graph_node_count": 15_000,
        "session_buddy_code_graph_coverage": 0.75,
    }
    report = feature_eligibility.build_report(plan_root, plan_root / "no.log", cfg)
    assert report.triggers[1].state == "above"
    assert report.triggers[1].fired is True


def test_phase_d_requires_phase8_adopted(plan_root: Path) -> None:
    """phase8 not adopted (built) -> below regardless of production days."""
    _write_phase8(plan_root, "built")
    cfg = {"phase_d_production_days": 30}
    report = feature_eligibility.build_report(plan_root, plan_root / "no.log", cfg)
    trig = report.triggers[2]
    assert trig.state == "below"
    assert trig.fired is False


def test_phase_d_fires_when_phase8_adopted_and_days_clear(plan_root: Path) -> None:
    _write_phase8(plan_root, "adopted")
    cfg = {"phase_d_production_days": 14}
    report = feature_eligibility.build_report(plan_root, plan_root / "no.log", cfg)
    trig = report.triggers[2]
    assert trig.state == "above"
    assert trig.fired is True


def test_phase_d_unknown_when_no_feature_tracking_doc(plan_root: Path) -> None:
    report = feature_eligibility.build_report(plan_root, plan_root / "no.log", None)
    assert report.triggers[2].state == "unknown"
    assert report.triggers[2].fired is False


def test_multi_metric_drift_below_threshold(plan_root: Path, tmp_path: Path) -> None:
    log = tmp_path / "requests.log"
    now = datetime.now(UTC)
    log.write_text(
        json.dumps({"metric": "pool_queue_depth", "ts": now.isoformat()}) + "\n"
        + json.dumps({"metric": "workflow_duration_p99", "ts": now.isoformat()}) + "\n",
        encoding="utf-8",
    )
    report = feature_eligibility.build_report(plan_root, log, None)
    trig = report.triggers[3]
    assert trig.state == "below"
    assert trig.fired is False
    assert trig.current == "2 distinct metrics"


def test_multi_metric_drift_fires_at_3(plan_root: Path, tmp_path: Path) -> None:
    log = tmp_path / "requests.log"
    now = datetime.now(UTC)
    entries = "\n".join(
        json.dumps({"metric": f"metric_{i}", "ts": now.isoformat()}) for i in range(5)
    )
    log.write_text(entries, encoding="utf-8")
    report = feature_eligibility.build_report(plan_root, log, None)
    trig = report.triggers[3]
    assert trig.state == "above"
    assert trig.fired is True
    assert trig.current == "5 distinct metrics"


def test_multi_metric_drift_window_excludes_old(plan_root: Path, tmp_path: Path) -> None:
    """Metrics older than 30 days are excluded from the count."""
    log = tmp_path / "requests.log"
    now = datetime.now(UTC)
    old = (now - timedelta(days=45)).isoformat()
    log.write_text(
        json.dumps({"metric": "metric_a", "ts": old}) + "\n"
        + json.dumps({"metric": "metric_b", "ts": old}) + "\n"
        + json.dumps({"metric": "metric_c", "ts": now.isoformat()}) + "\n",
        encoding="utf-8",
    )
    report = feature_eligibility.build_report(plan_root, log, None)
    trig = report.triggers[3]
    assert trig.state == "below"
    assert trig.current == "1 distinct metrics"


def test_multi_metric_drift_empty_file(plan_root: Path, tmp_path: Path) -> None:
    log = tmp_path / "requests.log"
    log.write_text("", encoding="utf-8")
    report = feature_eligibility.build_report(plan_root, log, None)
    assert report.triggers[3].state == "below"
    assert report.triggers[3].fired is False


def test_format_human_report_includes_all_triggers(plan_root: Path) -> None:
    report = feature_eligibility.build_report(plan_root, plan_root / "no.log", None)
    lines = feature_eligibility.format_human_report(report).splitlines()
    assert len(lines) == 5  # 4 triggers + 1 summary
    assert lines[0].startswith("optimal_transport:")
    assert lines[1].startswith("hyperbolic_embeddings:")
    assert lines[2].startswith("phase_d_cross_repo:")
    assert lines[3].startswith("multi_metric_drift:")
    assert lines[4].startswith("triggers_fired=")


def test_to_dict_serializable(plan_root: Path) -> None:
    report = feature_eligibility.build_report(plan_root, plan_root / "no.log", None)
    # Should round-trip through json.dumps
    encoded = json.dumps(report.to_dict(), indent=2, default=str)
    decoded = json.loads(encoded)
    assert decoded["summary"]["triggers_fired"] == 0
    assert len(decoded["triggers"]) == 4


def test_main_dry_run_exits_zero_with_fired_trigger(plan_root: Path, tmp_path: Path) -> None:
    """Even with a fired trigger, --dry-run exits 0."""
    cfg = tmp_path / "cfg.json"
    cfg.write_text(json.dumps({"akosha_patterns_cross_system_snapshot_count": 50_000}), encoding="utf-8")
    rc = feature_eligibility.main([
        "--mcp-config", str(cfg),
        "--plan-root", str(plan_root),
        "--dry-run",
    ])
    assert rc == 0


def test_main_exits_1_when_fired_without_followup(plan_root: Path, tmp_path: Path) -> None:
    cfg = tmp_path / "cfg.json"
    cfg.write_text(json.dumps({"akosha_patterns_cross_system_snapshot_count": 50_000}), encoding="utf-8")
    rc = feature_eligibility.main([
        "--mcp-config", str(cfg),
        "--plan-root", str(plan_root),
    ])
    assert rc == 1


def test_main_exits_0_when_fired_with_active_followup(plan_root: Path, tmp_path: Path) -> None:
    _write_followup(plan_root, "optimal_transport", "active")
    cfg = tmp_path / "cfg.json"
    cfg.write_text(json.dumps({"akosha_patterns_cross_system_snapshot_count": 50_000}), encoding="utf-8")
    rc = feature_eligibility.main([
        "--mcp-config", str(cfg),
        "--plan-root", str(plan_root),
    ])
    assert rc == 0


def test_main_exits_2_on_missing_mcp_config(tmp_path: Path) -> None:
    rc = feature_eligibility.main([
        "--mcp-config", str(tmp_path / "does_not_exist.json"),
        "--plan-root", str(tmp_path),
    ])
    assert rc == 2


def test_main_json_output(tmp_path: Path) -> None:
    """--json emits parseable JSON to stdout."""
    import io
    from contextlib import redirect_stdout
    buf = io.StringIO()
    rc = feature_eligibility.main([
        "--json",
        "--plan-root", str(tmp_path),
        "--dry-run",
    ])
    # rc non-0 acceptable here (no followups, may exit 1); we just care
    # that stdout was JSON.
    with redirect_stdout(buf):
        feature_eligibility.main([
            "--json",
            "--plan-root", str(tmp_path),
            "--dry-run",
        ])
    payload = json.loads(buf.getvalue())
    assert "triggers" in payload
    assert len(payload["triggers"]) == 4
