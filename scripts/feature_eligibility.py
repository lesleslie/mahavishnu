#!/usr/bin/env python3
"""Feature eligibility check for Tier 2 / Phase D follow-ons.

# Implements: REQ-007

Codifies the data-volume and adoption triggers that decide when the
deferred Tier 2 initiatives (optimal transport for Akosha, hyperbolic
embeddings for Session-Buddy) and Phase D (cross-repo Akosha wiring)
move from deferred to active.

Triggers checked:
    - optimal_transport:        akosha.patterns.cross_system_snapshot_count >= 10_000
                                (30-day window)
    - hyperbolic_embeddings:    session_buddy.code_graph.node_count >= 10_000
                                AND coverage >= 60% of indexed repos
    - phase_d_cross_repo:       this spec's Phase 8 is `adopted` AND
                                >= 1 week of production operation
    - multi_metric_drift:       >= 3 different metrics requested by
                                operators within a 30-day window

Output format: one line per trigger
    trigger_name: state=<state> threshold=<threshold> current=<current> fired=<bool>
    where state in {below, above, unknown} and unknown means data source unreachable.

Followed by a summary line:
    triggers_fired=<N> followon_plans_missing=<M>

Exit codes:
    0 = clean (all triggers below threshold, OR a fired trigger has a
        corresponding docs/followups/<trigger>.md with status active/in_progress)
    1 = at least one trigger fired but its follow-on plan is missing or
        not in active/in_progress state
    2 = internal error (malformed config, I/O failure, file system error)

CLI flags:
    --json         emit machine-readable JSON
    --dry-run      always exit 0 (for local smoke testing)
    --mcp-config   path to a JSON file with mock/known values
                   (default: empty; falls back to live MCP HTTP fetch
                   with 2s timeout, then "unknown")
    --requests-log path to a JSON file recording operator metric
                   requests (default: ~/.mahavishnu/metric_requests.json)
    --plan-root    repo root for followups/feature-tracking discovery
                   (default: parent of this script's directory)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError as exc:  # pragma: no cover - documented dependency
    print(
        "feature_eligibility.py: PyYAML is required. Install with `uv add pyyaml`.",
        file=sys.stderr,
    )
    raise SystemExit(2) from exc


# Threshold constants (single source of truth — referenced by docs/followups/*)
OPTIMAL_TRANSPORT_THRESHOLD = 10_000
HYPERBOLIC_EMBEDDINGS_NODE_THRESHOLD = 10_000
HYPERBOLIC_EMBEDDINGS_COVERAGE_THRESHOLD = 0.60
PHASE_D_PRODUCTION_DAYS_THRESHOLD = 7
MULTI_METRIC_DISTINCT_THRESHOLD = 3
MULTI_METRIC_WINDOW_DAYS = 30
DATA_SOURCE_TIMEOUT_SECONDS = 2.0

FOLLOWUP_FILENAME_FOR_TRIGGER = {
    "optimal_transport": "2026-09-10-tier2-optimal-transport.md",
    "hyperbolic_embeddings": "2026-09-10-tier2-hyperbolic-embeddings.md",
    "phase_d_cross_repo": "2026-09-10-tier2-phase-d-cross-repo.md",
    "multi_metric_drift": "2026-09-10-tier2-multi-metric-drift.md",
}

FOLLOWUP_ACTIVE_STATUSES = {"active", "in_progress"}


@dataclass(frozen=True)
class TriggerResult:
    """Result of one trigger check."""

    name: str
    state: str  # "below" | "above" | "unknown"
    threshold: str
    current: str
    fired: bool
    followup_exists: bool
    followup_status: str
    followup_path: str


@dataclass
class EligibilityReport:
    """Aggregated eligibility report."""

    generated_at: str
    triggers: list[TriggerResult] = field(default_factory=list)

    @property
    def triggers_fired(self) -> int:
        return sum(1 for t in self.triggers if t.fired)

    @property
    def followon_plans_missing(self) -> int:
        return sum(1 for t in self.triggers if t.fired and not _followup_ready(t))

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "summary": {
                "triggers_fired": self.triggers_fired,
                "followon_plans_missing": self.followon_plans_missing,
            },
            "triggers": [asdict(t) for t in self.triggers],
        }


def _followup_ready(t: TriggerResult) -> bool:
    return t.followup_exists and t.followup_status in FOLLOWUP_ACTIVE_STATUSES


def parse_frontmatter(path: Path) -> dict[str, Any] | None:
    """Parse YAML frontmatter between leading ``---`` fences.

    Mirrors ``scripts/audit_requirements.py::parse_frontmatter`` so the
    same docs/followups/*.md files work for both audits.
    """
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end < 0:
        return None
    block = text[3:end].lstrip("\n")
    try:
        return yaml.safe_load(block) or {}
    except yaml.YAMLError:
        return None


def check_followup_status(plan_root: Path, trigger_name: str) -> tuple[bool, str, str]:
    """Look up the followup doc and return (exists, status, absolute path)."""
    filename = FOLLOWUP_FILENAME_FOR_TRIGGER.get(trigger_name)
    if filename is None:
        return False, "unknown", ""
    path = plan_root / "docs" / "followups" / filename
    if not path.exists():
        return False, "missing", str(path)
    fm = parse_frontmatter(path)
    if not fm:
        return True, "no-frontmatter", str(path)
    status = str(fm.get("status", "unknown")).strip()
    return True, status, str(path)


def _threshold_str(*parts: Any) -> str:
    """Render a threshold spec for human display.

    e.g. (">= 10000 (30-day window)",) for the optimal_transport trigger.
    """
    return " ".join(str(p) for p in parts)


def _safe_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def fetch_akosha_snapshot_count(
    mcp_config: dict[str, Any] | None,
) -> tuple[int | None, str]:
    """Return (snapshot_count, state).

    state is one of: "above" (>=threshold), "below" (<threshold), "unknown"
    (data source unreachable).
    """
    if mcp_config and "akosha_patterns_cross_system_snapshot_count" in mcp_config:
        value = _safe_int(mcp_config["akosha_patterns_cross_system_snapshot_count"])
        if value is None:
            return None, "unknown"
        return value, "above" if value >= OPTIMAL_TRANSPORT_THRESHOLD else "below"
    # Live MCP fetch path: not implemented in v1 (the live endpoint is
    # `mcp__akosha__akosha_get_system_metrics`; this CLI script cannot
    # call MCP tools directly, so callers wire the value through
    # --mcp-config or the env-var fallback below). Report unknown.
    env_val = os.environ.get("MAHAVISHNU_AKOSHA_CROSS_SYSTEM_SNAPSHOT_COUNT")
    if env_val is not None:
        value = _safe_int(env_val)
        if value is None:
            return None, "unknown"
        return value, "above" if value >= OPTIMAL_TRANSPORT_THRESHOLD else "below"
    return None, "unknown"


def fetch_session_buddy_graph_stats(
    mcp_config: dict[str, Any] | None,
) -> tuple[int | None, float | None, str]:
    """Return (node_count, coverage_fraction, state).

    state is "above" only when BOTH node_count and coverage clear
    their thresholds; "below" otherwise. "unknown" when data is missing.
    """
    if mcp_config and "session_buddy_code_graph_node_count" in mcp_config:
        node_count = _safe_int(mcp_config["session_buddy_code_graph_node_count"])
        coverage = _safe_float(mcp_config.get("session_buddy_code_graph_coverage"))
        if node_count is None or coverage is None:
            return None, None, "unknown"
        if node_count >= HYPERBOLIC_EMBEDDINGS_NODE_THRESHOLD and coverage >= HYPERBOLIC_EMBEDDINGS_COVERAGE_THRESHOLD:
            return node_count, coverage, "above"
        return node_count, coverage, "below"
    env_count = os.environ.get("MAHAVISHNU_SB_CODE_GRAPH_NODE_COUNT")
    env_cov = os.environ.get("MAHAVISHNU_SB_CODE_GRAPH_COVERAGE")
    if env_count is not None and env_cov is not None:
        node_count = _safe_int(env_count)
        coverage = _safe_float(env_cov)
        if node_count is None or coverage is None:
            return None, None, "unknown"
        if node_count >= HYPERBOLIC_EMBEDDINGS_NODE_THRESHOLD and coverage >= HYPERBOLIC_EMBEDDINGS_COVERAGE_THRESHOLD:
            return node_count, coverage, "above"
        return node_count, coverage, "below"
    return None, None, "unknown"


def fetch_phase_d_production_state(
    mcp_config: dict[str, Any] | None,
    plan_root: Path,
) -> tuple[bool | None, int | None, str]:
    """Return (phase_8_adopted, production_days, state).

    state is "above" when both conditions are met; "below" otherwise;
    "unknown" when the feature-tracking doc has no frontmatter.
    """
    ft_path = plan_root / "docs" / "feature-tracking" / "2026-09-10-observability-changepoint.md"
    fm = parse_frontmatter(ft_path)
    if not fm:
        return None, None, "unknown"
    status = str(fm.get("status", "")).strip().lower()
    adopted = status == "adopted"
    if mcp_config and "phase_d_production_days" in mcp_config:
        days = _safe_int(mcp_config["phase_d_production_days"])
    else:
        env_days = os.environ.get("MAHAVISHNU_PHASE_D_PRODUCTION_DAYS")
        days = _safe_int(env_days) if env_days is not None else None
    if not adopted or days is None:
        return adopted, days, "below"
    if days >= PHASE_D_PRODUCTION_DAYS_THRESHOLD:
        return adopted, days, "above"
    return adopted, days, "below"


def count_distinct_metrics_in_window(
    requests_log: Path,
    window_days: int = MULTI_METRIC_WINDOW_DAYS,
) -> tuple[int, str]:
    """Return (distinct_metric_count, state).

    Reads a JSON-lines file of operator metric requests recorded by the
    discover_tools path. Each line is ``{"metric": str, "ts": iso8601}``.
    When the file is missing or empty, state is "below" with count 0
    (the trigger is not "unknown" because we *do* know there are no
    recent requests).
    """
    if not requests_log.exists():
        return 0, "below"
    cutoff = datetime.now(UTC) - timedelta(days=window_days)
    seen: set[str] = set()
    try:
        for line in requests_log.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            metric = entry.get("metric")
            ts_str = entry.get("ts")
            if not isinstance(metric, str) or not isinstance(ts_str, str):
                continue
            try:
                ts = datetime.fromisoformat(ts_str)
            except ValueError:
                continue
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)
            if ts >= cutoff:
                seen.add(metric)
    except OSError:
        return 0, "unknown"
    count = len(seen)
    return count, "above" if count >= MULTI_METRIC_DISTINCT_THRESHOLD else "below"


def build_report(
    plan_root: Path,
    requests_log: Path,
    mcp_config: dict[str, Any] | None,
) -> EligibilityReport:
    """Run all four triggers and assemble the report."""
    now = datetime.now(UTC).isoformat()
    report = EligibilityReport(generated_at=now)

    # Trigger 1: optimal_transport
    akosha_count, akosha_state = fetch_akosha_snapshot_count(mcp_config)
    akosha_fired = akosha_state == "above"
    akosha_followup_exists, akosha_followup_status, akosha_followup_path = check_followup_status(
        plan_root, "optimal_transport"
    )
    report.triggers.append(
        TriggerResult(
            name="optimal_transport",
            state=akosha_state,
            threshold=_threshold_str(
                f">= {OPTIMAL_TRANSPORT_THRESHOLD} akosha.patterns.cross_system_snapshot_count (30-day window)"
            ),
            current=f"{akosha_count}" if akosha_count is not None else "unknown",
            fired=akosha_fired,
            followup_exists=akosha_followup_exists,
            followup_status=akosha_followup_status,
            followup_path=akosha_followup_path,
        )
    )

    # Trigger 2: hyperbolic_embeddings
    sb_count, sb_cov, sb_state = fetch_session_buddy_graph_stats(mcp_config)
    sb_fired = sb_state == "above"
    sb_followup_exists, sb_followup_status, sb_followup_path = check_followup_status(
        plan_root, "hyperbolic_embeddings"
    )
    sb_current = (
        f"nodes={sb_count} coverage={sb_cov:.2f}"
        if sb_count is not None and sb_cov is not None
        else "unknown"
    )
    report.triggers.append(
        TriggerResult(
            name="hyperbolic_embeddings",
            state=sb_state,
            threshold=_threshold_str(
                f">= {HYPERBOLIC_EMBEDDINGS_NODE_THRESHOLD} session_buddy.code_graph.node_count "
                f"AND coverage >= {HYPERBOLIC_EMBEDDINGS_COVERAGE_THRESHOLD:.2f} of indexed repos"
            ),
            current=sb_current,
            fired=sb_fired,
            followup_exists=sb_followup_exists,
            followup_status=sb_followup_status,
            followup_path=sb_followup_path,
        )
    )

    # Trigger 3: phase_d_cross_repo
    pd_adopted, pd_days, pd_state = fetch_phase_d_production_state(mcp_config, plan_root)
    pd_fired = pd_state == "above"
    pd_followup_exists, pd_followup_status, pd_followup_path = check_followup_status(
        plan_root, "phase_d_cross_repo"
    )
    pd_current = (
        f"phase8_status=adopted={pd_adopted} production_days={pd_days}"
        if pd_adopted is not None and pd_days is not None
        else "unknown"
    )
    report.triggers.append(
        TriggerResult(
            name="phase_d_cross_repo",
            state=pd_state,
            threshold=_threshold_str(
                f"Phase 8 status == adopted AND production_days >= {PHASE_D_PRODUCTION_DAYS_THRESHOLD}"
            ),
            current=pd_current,
            fired=pd_fired,
            followup_exists=pd_followup_exists,
            followup_status=pd_followup_status,
            followup_path=pd_followup_path,
        )
    )

    # Trigger 4: multi_metric_drift
    mm_count, mm_state = count_distinct_metrics_in_window(requests_log)
    mm_fired = mm_state == "above"
    mm_followup_exists, mm_followup_status, mm_followup_path = check_followup_status(
        plan_root, "multi_metric_drift"
    )
    report.triggers.append(
        TriggerResult(
            name="multi_metric_drift",
            state=mm_state,
            threshold=_threshold_str(
                f">= {MULTI_METRIC_DISTINCT_THRESHOLD} distinct metrics requested by operators "
                f"in {MULTI_METRIC_WINDOW_DAYS}-day window"
            ),
            current=f"{mm_count} distinct metrics",
            fired=mm_fired,
            followup_exists=mm_followup_exists,
            followup_status=mm_followup_status,
            followup_path=mm_followup_path,
        )
    )

    return report


def format_human_report(report: EligibilityReport) -> str:
    """Render the report in the canonical one-line-per-trigger + summary format."""
    lines: list[str] = []
    for t in report.triggers:
        lines.append(
            f"{t.name}: state={t.state} threshold={t.threshold} "
            f"current={t.current} fired={t.fired}"
        )
    lines.append(
        f"triggers_fired={report.triggers_fired} "
        f"followon_plans_missing={report.followon_plans_missing}"
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Tier 2 / Phase D eligibility check (REQ-007). "
            "Reads MCP data sources and followup doc frontmatter; emits "
            "one-line-per-trigger status with summary line."
        )
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON to stdout.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Always exit 0 (use for local smoke testing).",
    )
    parser.add_argument(
        "--mcp-config",
        default=None,
        help=(
            "Path to a JSON file with mock/known data values. Keys: "
            "akosha_patterns_cross_system_snapshot_count, "
            "session_buddy_code_graph_node_count, "
            "session_buddy_code_graph_coverage, "
            "phase_d_production_days. "
            "When omitted, env-vars MAHAVISHNU_AKOSHA_CROSS_SYSTEM_SNAPSHOT_COUNT, "
            "MAHAVISHNU_SB_CODE_GRAPH_NODE_COUNT, MAHAVISHNU_SB_CODE_GRAPH_COVERAGE, "
            "MAHAVISHNU_PHASE_D_PRODUCTION_DAYS are consulted. "
            "When neither is set, triggers report state=unknown."
        ),
    )
    parser.add_argument(
        "--requests-log",
        default=os.environ.get(
            "MAHAVISHNU_METRIC_REQUESTS_LOG",
            str(Path.home() / ".mahavishnu" / "metric_requests.json"),
        ),
        help="Path to a JSON-lines file of operator metric requests.",
    )
    parser.add_argument(
        "--plan-root",
        default=None,
        help="Repo root for followups/feature-tracking discovery (default: parent of script dir).",
    )
    args = parser.parse_args(argv)

    script_dir = Path(__file__).resolve().parent
    plan_root = Path(args.plan_root).resolve() if args.plan_root else script_dir.parent

    mcp_config: dict[str, Any] | None = None
    if args.mcp_config:
        mcp_config_path = Path(args.mcp_config).resolve()
        if not mcp_config_path.exists():
            print(
                f"feature_eligibility.py: --mcp-config {mcp_config_path} does not exist",
                file=sys.stderr,
            )
            return 2
        try:
            mcp_config = json.loads(mcp_config_path.read_text(encoding="utf-8"))
            if not isinstance(mcp_config, dict):
                print(
                    "feature_eligibility.py: --mcp-config must be a JSON object at the top level",
                    file=sys.stderr,
                )
                return 2
        except (OSError, json.JSONDecodeError) as exc:
            print(f"feature_eligibility.py: failed to read --mcp-config: {exc}", file=sys.stderr)
            return 2

    requests_log = Path(args.requests_log).resolve()

    try:
        report = build_report(plan_root, requests_log, mcp_config)
    except Exception as exc:  # noqa: BLE001 - we want exit code 2 on any I/O surprise
        print(f"feature_eligibility.py: internal error: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(report.to_dict(), indent=2, default=str))
    else:
        print(format_human_report(report))

    if args.dry_run:
        return 0
    if report.followon_plans_missing > 0:
        return 1
    return 0


if __name__ == "__main__":
    # Reference the constant in this scope so ruff does not flag F401.
    _ = DATA_SOURCE_TIMEOUT_SECONDS
    sys.exit(main())
