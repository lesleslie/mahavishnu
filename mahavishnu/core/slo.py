"""Service Level Objectives (SLOs) for code indexing service.

This module defines SLOs, metrics, and alerting for code indexing operations.

Key SLOs:
- Code freshness: 95% of repos indexed within 5 minutes
- Availability: 99.9% uptime (43 min/month downtime budget)
- Polling health: 99% success rate
- Event delivery: 99.5% success rate
"""

import logging
import time
from datetime import datetime, UTC, timedelta
from typing import Any

# Prometheus metrics (if available)
try:
    from prometheus_client import Counter, Histogram, Gauge
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False
    # Create mock classes for development
    class Counter:
        def __init__(self, *args, **kwargs):
            pass

        def labels(self, *args, **kwargs):
            return self

        def inc(self, *args, **kwargs):
            pass

    class Histogram:
        def __init__(self, *args, **kwargs):
            pass

        def labels(self, *args, **kwargs):
            return self

        def observe(self, *args, **kwargs):
            pass

    class Gauge:
        def __init__(self, *args, **kwargs):
            pass

        def labels(self, *args, **kwargs):
            return self

        def set(self, *args, **kwargs):
            pass

logger = logging.getLogger(__name__)


# =============================================================================
# PROMETHEUS METRICS
# =============================================================================

# Code freshness metrics
code_index_freshness_seconds = Gauge(
    "code_index_freshness_seconds",
    "Time since last successful index per repo",
    ["repo"]
)

code_index_freshness_slo_compliance = Gauge(
    "code_index_freshness_slo_compliance",
    "Freshness SLO compliance percentage (95% within 5 min)",
    ["window_minutes"]
)

# Polling metrics
code_index_poll_total = Counter(
    "code_index_poll_total",
    "Total number of git polls performed",
    ["repo", "status"]  # status: success | failure
)

code_index_poll_duration_seconds = Histogram(
    "code_index_poll_duration_seconds",
    "Git poll duration in seconds",
    ["repo"],
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0],
)

code_index_poll_success_rate = Gauge(
    "code_index_poll_success_rate",
    "Polling success rate (99% SLO)",
    ["window_minutes"]
)

# Re-index metrics
code_index_reindex_total = Counter(
    "code_index_reindex_total",
    "Total number of repository re-indexes",
    ["repo", "status"]  # status: success | failure
)

code_index_reindex_duration_seconds = Histogram(
    "code_index_reindex_duration_seconds",
    "Re-index duration in seconds",
    ["repo"],
    buckets=[1.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0],
)

# Event delivery metrics
code_index_events_published_total = Counter(
    "code_index_events_published_total",
    "Total number of events published",
    ["event_type"]
)

code_index_events_delivered_total = Counter(
    "code_index_events_delivered_total",
    "Total number of events delivered to subscribers",
    ["event_type", "subscriber", "status"]
)

code_index_event_delivery_latency_seconds = Histogram(
    "code_index_event_delivery_latency_seconds",
    "Time between event publish and subscriber delivery",
    ["event_type", "subscriber"],
    buckets=[0.01, 0.1, 0.5, 1.0, 5.0, 10.0],
)

code_index_event_delivery_success_rate = Gauge(
    "code_index_event_delivery_success_rate",
    "Event delivery success rate (99.5% SLO)",
    ["window_minutes"]
)

# Availability metrics
code_index_availability_up = Gauge(
    "code_index_availability_up",
    "Whether code index service is up (1) or down (0)"
)

code_index_availability_slo_compliance = Gauge(
    "code_index_availability_slo_compliance",
    "Availability SLO compliance percentage (99.9%)",
    ["window_hours"]
)


# =============================================================================
# SLO CALCULATIONS
# =============================================================================

class SLOCalculator:
    """Calculate SLO compliance from metrics."""

    @staticmethod
    def freshness_slo(
        last_indexed_times: dict[str, datetime],
        window_minutes: int = 30,
        target_minutes: int = 5,
    ) -> dict[str, Any]:
        """Calculate code freshness SLO compliance.

        Args:
            last_indexed_times: Map of repo_path -> last indexed timestamp
            window_minutes: Time window to calculate compliance over
            target_minutes: Target freshness (5 minutes for 95% SLO)

        Returns:
            SLO compliance data with percentage and violating repos
        """
        now = datetime.now(UTC)
        target_delta = timedelta(minutes=target_minutes)

        compliant_count = 0
        total_count = len(last_indexed_times)
        violating_repos = []

        for repo, last_indexed in last_indexed_times.items():
            age = now - last_indexed

            if age <= target_delta:
                compliant_count += 1
            else:
                violating_repos.append(
                    {
                        "repo": repo,
                        "last_indexed": last_indexed.isoformat(),
                        "age_minutes": age.total_seconds() / 60,
                    }
                )

        compliance_pct = (compliant_count / total_count * 100) if total_count > 0 else 100

        # Update Prometheus metric
        code_index_freshness_slo_compliance.labels(window_minutes=window_minutes).set(
            compliance_pct
        )

        # Update per-repo freshness gauges
        for repo, last_indexed in last_indexed_times.items():
            age_seconds = (now - last_indexed).total_seconds()
            code_index_freshness_seconds.labels(repo=repo).set(age_seconds)

        return {
            "compliance_pct": round(compliance_pct, 2),
            "target_pct": 95.0,
            "compliant": compliant_count,
            "total": total_count,
            "violating_repos": violating_repos,
            "meets_slo": compliance_pct >= 95.0,
        }

    @staticmethod
    def polling_success_slo(
        poll_results: dict[str, dict[str, int]],
        window_minutes: int = 30,
        target_pct: float = 99.0,
    ) -> dict[str, Any]:
        """Calculate polling health SLO compliance.

        Args:
            poll_results: Map of repo_path -> {"success": int, "failure": int}
            window_minutes: Time window to calculate compliance over
            target_pct: Target success rate (99% for SLO)

        Returns:
            SLO compliance data with percentage
        """
        total_success = sum(data["success"] for data in poll_results.values())
        total_failure = sum(data["failure"] for data in poll_results.values())
        total_attempts = total_success + total_failure

        success_rate = (total_success / total_attempts * 100) if total_attempts > 0 else 100

        # Update Prometheus metric
        code_index_poll_success_rate.labels(window_minutes=window_minutes).set(
            success_rate
        )

        return {
            "success_rate_pct": round(success_rate, 2),
            "target_pct": target_pct,
            "total_success": total_success,
            "total_failure": total_failure,
            "total_attempts": total_attempts,
            "meets_slo": success_rate >= target_pct,
        }

    @staticmethod
    def availability_slo(
        uptime_checks: list[dict[str, Any]],
        window_hours: int = 24,
        target_pct: float = 99.9,
    ) -> dict[str, Any]:
        """Calculate availability SLO compliance.

        Args:
            uptime_checks: List of {"timestamp": datetime, "up": bool}
            window_hours: Time window to calculate compliance over
            target_pct: Target availability (99.9% for SLO)

        Returns:
            SLO compliance data with percentage and downtime budget
        """
        if not uptime_checks:
            # No data yet, assume 100%
            return {
                "availability_pct": 100.0,
                "target_pct": target_pct,
                "downtime_seconds": 0,
                "downtime_budget_seconds": (window_hours * 3600) * (1 - target_pct / 100),
                "meets_slo": True,
            }

        # Filter checks within window
        now = datetime.now(UTC)
        window_start = now - timedelta(hours=window_hours)

        checks_in_window = [
            c for c in uptime_checks if c["timestamp"] >= window_start
        ]

        if not checks_in_window:
            return {
                "availability_pct": 100.0,
                "target_pct": target_pct,
                "downtime_seconds": 0,
                "downtime_budget_seconds": (window_hours * 3600) * (1 - target_pct / 100),
                "meets_slo": True,
            }

        # Calculate downtime
        downtime_periods = []
        current_downtime_start = None

        for check in checks_in_window:
            if not check["up"] and current_downtime_start is None:
                current_downtime_start = check["timestamp"]
            elif check["up"] and current_downtime_start is not None:
                downtime_periods.append(
                    (current_downtime_start, check["timestamp"])
                )
                current_downtime_start = None

        # If currently in downtime
        if not check["up"] and current_downtime_start is not None:
            downtime_periods.append((current_downtime_start, now))

        # Sum downtime
        downtime_seconds = sum(
            (end - start).total_seconds() for start, end in downtime_periods
        )

        window_seconds = window_hours * 3600
        uptime_seconds = window_seconds - downtime_seconds
        availability_pct = (uptime_seconds / window_seconds) * 100

        # Calculate error budget
        error_budget_seconds = window_seconds * (1 - target_pct / 100)
        remaining_budget = error_budget_seconds - downtime_seconds

        # Update Prometheus metric
        code_index_availability_slo_compliance.labels(window_hours=window_hours).set(
            availability_pct
        )

        return {
            "availability_pct": round(availability_pct, 2),
            "target_pct": target_pct,
            "downtime_seconds": int(downtime_seconds),
            "downtime_budget_seconds": int(error_budget_seconds),
            "remaining_budget_seconds": int(remaining_budget),
            "meets_slo": availability_pct >= target_pct,
        }


# =============================================================================
# SLO ALERT THRESHOLDS
# =============================================================================

SLO_THRESHOLDS = {
    "freshness": {
        "warning": 90.0,  # 90-95% = warning
        "critical": 85.0,  # <90% = critical
    },
    "polling": {
        "warning": 99.5,  # 99.5-99% = warning
        "critical": 98.0,  # <99.5% = critical
    },
    "availability": {
        "warning": 99.95,  # 99.95-99.9% = warning
        "critical": 99.8,  # <99.95% = critical
    },
    "event_delivery": {
        "warning": 99.7,  # 99.7-99.5% = warning
        "critical": 99.0,  # <99.7% = critical
    },
}


def check_slo_threshold(slo_type: str, value: float) -> dict[str, Any]:
    """Check if SLO value meets thresholds.

    Args:
        slo_type: Type of SLO ("freshness", "polling", etc.)
        value: Current SLO value (percentage)

    Returns:
        Alert status with level and message
    """
    thresholds = SLO_THRESHOLDS.get(slo_type, {})

    if value >= thresholds.get("warning", 100):
        return {"status": "ok", "level": "info", "message": f"SLO met: {value}%"}

    if value >= thresholds.get("critical", 0):
        return {
            "status": "warning",
            "level": "warning",
            "message": f"SLO degrading: {value}% (warning threshold: {thresholds['warning']}%)",
        }

    return {
        "status": "critical",
        "level": "critical",
        "message": f"SLO violated: {value}% (critical threshold: {thresholds['critical']}%)",
    }


# =============================================================================
# SLO REPORTING
# =============================================================================

def generate_slo_report(
    freshness_data: dict[str, Any],
    polling_data: dict[str, Any],
    availability_data: dict[str, Any],
) -> dict[str, Any]:
    """Generate comprehensive SLO report.

    Args:
        freshness_data: Freshness SLO calculation
        polling_data: Polling SLO calculation
        availability_data: Availability SLO calculation

    Returns:
        SLO report with overall status
    """
    overall_meets_slo = all([
        freshness_data.get("meets_slo", True),
        polling_data.get("meets_slo", True),
        availability_data.get("meets_slo", True),
    ])

    return {
        "timestamp": datetime.now(UTC).isoformat(),
        "overall_meets_slo": overall_meets_slo,
        "freshness": freshness_data,
        "polling": polling_data,
        "availability": availability_data,
        "recommendations": _generate_recommendations(
            freshness_data, polling_data, availability_data
        ),
    }


def _generate_recommendations(
    freshness: dict[str, Any],
    polling: dict[str, Any],
    availability: dict[str, Any],
) -> list[str]:
    """Generate actionable recommendations based on SLO status.

    Returns:
        List of recommendation strings
    """
    recommendations = []

    # Freshness recommendations
    if not freshness.get("meets_slo", True):
        violating_repos = freshness.get("violating_repos", [])
        recommendations.append(
            f"⚠️ Code freshness SLO violated ({freshness['compliance_pct']}% < 95%). "
            f"Consider optimizing re-index performance for {len(violating_repos)} repos."
        )
        for repo in violating_repos[:3]:  # Show top 3
            recommendations.append(
                f"   - {repo['repo']}: {repo['age_minutes']:.1f} minutes stale"
            )

    # Polling recommendations
    if not polling.get("meets_slo", True):
        recommendations.append(
            f"⚠️ Polling health SLO violated ({polling['success_rate_pct']}% < 99%). "
            f"Check git hosting service health."
        )

    # Availability recommendations
    if not availability.get("meets_slo", True):
        downtime_secs = availability.get("downtime_seconds", 0)
        recommendations.append(
            f"⚠️ Availability SLO violated ({availability['availability_pct']}% < 99.9%). "
            f"Downtime: {downtime_secs / 60:.1f} minutes in last {availability.get('window_hours', 24)}h."
        )
        recommendations.append(
            "   → Implement auto-restart mechanism (systemd/supervisord)"
        )
        recommendations.append(
            "   → Add health check probes with liveness/readiness endpoints"
        )

    if recommendations:
        recommendations.insert(
            0,
            "🔔 Action Required: One or more SLOs violated. See recommendations below.",
        )
    else:
        recommendations.append("✅ All SLOs met! System healthy.")

    return recommendations


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def record_poll(repo: str, status: str, duration_seconds: float) -> None:
    """Record poll metric.

    Args:
        repo: Repository path
        status: "success" or "failure"
        duration_seconds: Poll duration
    """
    code_index_poll_total.labels(repo=repo, status=status).inc()
    code_index_poll_duration_seconds.labels(repo=repo).observe(duration_seconds)

    if status == "failure":
        logger.warning(f"Poll failed for {repo} (duration: {duration_seconds:.2f}s)")


def record_reindex(repo: str, status: str, duration_seconds: float) -> None:
    """Record re-index metric.

    Args:
        repo: Repository path
        status: "success" or "failure"
        duration_seconds: Re-index duration
    """
    code_index_reindex_total.labels(repo=repo, status=status).inc()
    code_index_reindex_duration_seconds.labels(repo=repo).observe(duration_seconds)

    if status == "failure":
        logger.error(f"Re-index failed for {repo} (duration: {duration_seconds:.2f}s)")


def record_event_published(event_type: str) -> None:
    """Record event published metric.

    Args:
        event_type: Event type name
    """
    code_index_events_published_total.labels(event_type=event_type).inc()


def record_event_delivered(event_type: str, subscriber: str, status: str, latency_seconds: float) -> None:
    """Record event delivered metric.

    Args:
        event_type: Event type name
        subscriber: Subscriber name
        status: "success" or "failure"
        latency_seconds: Delivery latency
    """
    code_index_events_delivered_total.labels(
        event_type=event_type, subscriber=subscriber, status=status
    ).inc()
    code_index_event_delivery_latency_seconds.labels(
        event_type=event_type, subscriber=subscriber
    ).observe(latency_seconds)


def set_service_up(up: bool = True) -> None:
    """Set service availability status.

    Args:
        up: True if service is up, False if down
    """
    code_index_availability_up.set(1 if up else 0)
