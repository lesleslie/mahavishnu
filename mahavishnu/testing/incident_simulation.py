"""Incident Response Simulation for Mahavishnu.

Provides incident simulation capabilities for:
- On-call training
- Runbook validation
- Incident response procedure testing
- SRE team preparedness

Usage:
    python -m mahavishnu.testing.incident_simulation --scenario database_outage
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, UTC
from enum import Enum
from typing import Any
from pathlib import Path

logger = logging.getLogger(__name__)


class IncidentSeverity(str, Enum):
    """Incident severity levels."""

    T0 = "t0"  # Emergency - complete outage
    T1 = "t1"  # Critical - major feature broken
    T2 = "t2"  # High - degraded performance
    T3 = "t3"  # Medium - minor issue
    T4 = "t4"  # Low - cosmetic issue


class IncidentPhase(str, Enum):
    """Incident response phases."""

    DETECTION = "detection"
    TRIAGE = "triage"
    INVESTIGATION = "investigation"
    MITIGATION = "mitigation"
    RESOLUTION = "resolution"
    POSTMORTEM = "postmortem"


@dataclass
class IncidentScenario:
    """Definition of an incident scenario."""

    id: str
    name: str
    description: str
    severity: IncidentSeverity
    symptoms: list[str]
    affected_components: list[str]
    runbook_reference: str
    expected_mitigation_time_minutes: int
    steps: list[dict[str, Any]] = field(default_factory=list)


# Predefined incident scenarios
INCIDENT_SCENARIOS: dict[str, IncidentScenario] = {
    "database_outage": IncidentScenario(
        id="INC-001",
        name="Database Connection Pool Exhaustion",
        description="All database connections are exhausted, causing task operations to fail",
        severity=IncidentSeverity.T1,
        symptoms=[
            "HTTP 503 errors on /api/v1/tasks endpoints",
            "Error logs showing 'connection pool exhausted'",
            "P99 latency spiking to >5s",
            "Success rate dropping below 95%",
        ],
        affected_components=["PostgreSQL", "Task API", "Webhook Handler"],
        runbook_reference="docs/runbooks/deployment.md#database-issues",
        expected_mitigation_time_minutes=15,
        steps=[
            {
                "phase": "detection",
                "action": "Acknowledge alert within 5 minutes",
                "success_criteria": "Alert acknowledged in PagerDuty",
            },
            {
                "phase": "triage",
                "action": "Check database connection metrics",
                "command": "mahavishnu db pool status",
                "success_criteria": "Identify pool exhaustion",
            },
            {
                "phase": "investigation",
                "action": "Check for long-running queries",
                "command": "psql -c 'SELECT * FROM pg_stat_activity WHERE state = active'",
                "success_criteria": "Identify blocking queries",
            },
            {
                "phase": "mitigation",
                "action": "Reset connection pool",
                "command": "mahavishnu db pool reset",
                "success_criteria": "Connections restored",
            },
            {
                "phase": "resolution",
                "action": "Verify service health",
                "command": "curl -s https://mahavishnu.example.com/health",
                "success_criteria": "Health check returns 200",
            },
        ],
    ),
    "high_error_rate": IncidentScenario(
        id="INC-002",
        name="Elevated Error Rate",
        description="Task creation API returning 5xx errors at elevated rate",
        severity=IncidentSeverity.T2,
        symptoms=[
            "Error rate > 5% on task creation",
            "User reports of failed task creation",
            "Error budget burning at 2x normal rate",
        ],
        affected_components=["Task API", "NLP Parser"],
        runbook_reference="docs/runbooks/on_call_handbook.md#common-alerts",
        expected_mitigation_time_minutes=30,
        steps=[
            {
                "phase": "detection",
                "action": "Check error rate dashboard",
                "success_criteria": "Confirm error rate elevation",
            },
            {
                "phase": "triage",
                "action": "Identify error type breakdown",
                "command": "mahavishnu task stats --errors --group-by type",
                "success_criteria": "Identify dominant error type",
            },
            {
                "phase": "investigation",
                "action": "Check recent deployments",
                "command": "mahavishnu deployments list --last 24h",
                "success_criteria": "Identify potential cause",
            },
            {
                "phase": "mitigation",
                "action": "Roll back if deployment-related",
                "command": "kubectl rollout undo deployment/mahavishnu",
                "success_criteria": "Error rate decreasing",
            },
        ],
    ),
    "latency_spike": IncidentScenario(
        id="INC-003",
        name="P99 Latency SLO Breach",
        description="Task query latency exceeds SLO targets",
        severity=IncidentSeverity.T2,
        symptoms=[
            "P99 latency > 500ms for task creation",
            "Slow page loads in UI",
            "Grafana showing latency spike",
        ],
        affected_components=["Task API", "PostgreSQL", "Redis Cache"],
        runbook_reference="docs/runbooks/on_call_handbook.md#performance-degradation",
        expected_mitigation_time_minutes=20,
        steps=[
            {
                "phase": "detection",
                "action": "Check latency dashboard",
                "success_criteria": "Confirm latency spike",
            },
            {
                "phase": "triage",
                "action": "Identify slow operations",
                "command": "mahavishnu metrics latency --p99 --last 15m",
                "success_criteria": "Identify affected endpoints",
            },
            {
                "phase": "investigation",
                "action": "Check database query performance",
                "command": "psql -c 'SELECT * FROM pg_stat_statements ORDER BY total_time DESC LIMIT 10'",
                "success_criteria": "Find slow queries",
            },
            {
                "phase": "mitigation",
                "action": "Clear cache if stale data",
                "command": "mahavishnu cache clear",
                "success_criteria": "Latency improving",
            },
        ],
    ),
    "webhook_failure": IncidentScenario(
        id="INC-004",
        name="Webhook Processing Failure",
        description="GitHub webhooks failing validation",
        severity=IncidentSeverity.T2,
        symptoms=[
            "Webhook events not creating tasks",
            "HMAC validation failures in logs",
            "GitHub integration showing errors",
        ],
        affected_components=["Webhook Handler", "Task API"],
        runbook_reference="docs/runbooks/security.md#webhook-issues",
        expected_mitigation_time_minutes=15,
        steps=[
            {
                "phase": "detection",
                "action": "Check webhook error logs",
                "success_criteria": "Identify failure pattern",
            },
            {
                "phase": "triage",
                "action": "Verify webhook secret configuration",
                "command": "mahavishnu config get webhook.secret",
                "success_criteria": "Confirm secret is set",
            },
            {
                "phase": "investigation",
                "action": "Test webhook signature validation",
                "command": "mahavishnu webhook test --verify-signature",
                "success_criteria": "Identify validation issue",
            },
            {
                "phase": "mitigation",
                "action": "Update webhook secret if rotated",
                "command": "mahavishnu config set webhook.secret $NEW_SECRET",
                "success_criteria": "Webhooks processing successfully",
            },
        ],
    ),
    "complete_outage": IncidentScenario(
        id="INC-005",
        name="Complete Service Outage",
        description="All Mahavishnu services are unavailable",
        severity=IncidentSeverity.T0,
        symptoms=[
            "All health checks failing",
            "No responses from any endpoint",
            "Complete error budget consumption",
            "Customer reports of complete inability to use service",
        ],
        affected_components=["All Services", "Database", "Cache"],
        runbook_reference="docs/runbooks/disaster_recovery.md",
        expected_mitigation_time_minutes=60,
        steps=[
            {
                "phase": "detection",
                "action": "Page all on-call engineers",
                "success_criteria": "Team assembled in war room",
            },
            {
                "phase": "triage",
                "action": "Assess scope of outage",
                "command": "mahavishnu health check --all",
                "success_criteria": "Identify affected components",
            },
            {
                "phase": "investigation",
                "action": "Check infrastructure status",
                "command": "kubectl get pods -n mahavishnu",
                "success_criteria": "Identify failing pods",
            },
            {
                "phase": "mitigation",
                "action": "Initiate DR procedures if needed",
                "command": "./scripts/dr-failover.sh",
                "success_criteria": "Services recovering",
            },
            {
                "phase": "resolution",
                "action": "Full service restoration",
                "command": "mahavishnu health check --all",
                "success_criteria": "All health checks passing",
            },
            {
                "phase": "postmortem",
                "action": "Schedule postmortem within 24 hours",
                "success_criteria": "Postmortem scheduled",
            },
        ],
    ),
}


@dataclass
class SimulationResult:
    """Result of a simulation step."""

    step_number: int
    phase: str
    action: str
    expected_criteria: str
    completed: bool
    time_taken_seconds: float
    notes: str = ""


@dataclass
class SimulationReport:
    """Complete simulation report."""

    scenario_id: str
    scenario_name: str
    severity: str
    start_time: str
    end_time: str
    total_duration_seconds: float
    steps_completed: int
    steps_total: int
    passed: bool
    results: list[SimulationResult]
    recommendations: list[str]

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "scenario_id": self.scenario_id,
            "scenario_name": self.scenario_name,
            "severity": self.severity,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "total_duration_seconds": round(self.total_duration_seconds, 2),
            "steps_completed": self.steps_completed,
            "steps_total": self.steps_total,
            "passed": self.passed,
            "results": [
                {
                    "step_number": r.step_number,
                    "phase": r.phase,
                    "action": r.action,
                    "expected_criteria": r.expected_criteria,
                    "completed": r.completed,
                    "time_taken_seconds": round(r.time_taken_seconds, 2),
                    "notes": r.notes,
                }
                for r in self.results
            ],
            "recommendations": self.recommendations,
        }


class IncidentSimulator:
    """Simulates incidents for training and validation."""

    def __init__(self, output_file: str | None = None):
        self.output_file = output_file
        self.current_phase = IncidentPhase.DETECTION

    def list_scenarios(self) -> list[dict[str, str]]:
        """List available scenarios."""
        return [
            {
                "id": s.id,
                "name": s.name,
                "severity": s.severity.value,
                "description": s.description[:100] + "...",
            }
            for s in INCIDENT_SCENARIOS.values()
        ]

    async def run_simulation(
        self,
        scenario_id: str,
        interactive: bool = False,
    ) -> SimulationReport:
        """Run an incident simulation."""
        if scenario_id not in INCIDENT_SCENARIOS:
            raise ValueError(f"Unknown scenario: {scenario_id}")

        scenario = INCIDENT_SCENARIOS[scenario_id]
        start_time = datetime.now(UTC)
        results: list[SimulationResult] = []

        print(f"\n{'='*60}")
        print(f"INCIDENT SIMULATION: {scenario.name}")
        print(f"{'='*60}")
        print(f"\n📋 Severity: {scenario.severity.value.upper()}")
        print(f"📝 Description: {scenario.description}")
        print(f"\n⚠️  Symptoms:")
        for symptom in scenario.symptoms:
            print(f"   • {symptom}")
        print(f"\n🔗 Runbook: {scenario.runbook_reference}")
        print(f"\n⏱️  Expected Mitigation: {scenario.expected_mitigation_time_minutes} minutes")
        print(f"\n{'='*60}\n")

        for i, step in enumerate(scenario.steps, 1):
            print(f"\n📌 Step {i}/{len(scenario.steps)} - {step['phase'].upper()}")
            print(f"   Action: {step['action']}")

            if "command" in step:
                print(f"   Command: {step['command']}")

            print(f"   Success Criteria: {step['success_criteria']}")

            step_start = time.time()

            if interactive:
                input("\n   Press Enter when step is complete...")
                completed = True
                notes = input("   Notes (optional): ")
            else:
                # Automated simulation - simulate step completion
                await asyncio.sleep(random.uniform(0.5, 2.0))
                completed = True
                notes = "Simulated completion"

            step_time = time.time() - step_start

            result = SimulationResult(
                step_number=i,
                phase=step["phase"],
                action=step["action"],
                expected_criteria=step["success_criteria"],
                completed=completed,
                time_taken_seconds=step_time,
                notes=notes,
            )
            results.append(result)

            status = "✓" if completed else "✗"
            print(f"   {status} Completed in {step_time:.2f}s")

        end_time = datetime.now(UTC)
        duration = (end_time - start_time).total_seconds()

        # Generate recommendations
        recommendations = self._generate_recommendations(scenario, results, duration)

        report = SimulationReport(
            scenario_id=scenario.id,
            scenario_name=scenario.name,
            severity=scenario.severity.value,
            start_time=start_time.isoformat(),
            end_time=end_time.isoformat(),
            total_duration_seconds=duration,
            steps_completed=sum(1 for r in results if r.completed),
            steps_total=len(results),
            passed=all(r.completed for r in results),
            results=results,
            recommendations=recommendations,
        )

        if self.output_file:
            Path(self.output_file).write_text(json.dumps(report.to_dict(), indent=2))

        return report

    def _generate_recommendations(
        self,
        scenario: IncidentScenario,
        results: list[SimulationResult],
        total_duration: float,
    ) -> list[str]:
        """Generate recommendations based on simulation results."""
        recommendations = []

        # Check if within expected time
        expected_minutes = scenario.expected_mitigation_time_minutes
        actual_minutes = total_duration / 60

        if actual_minutes > expected_minutes:
            recommendations.append(
                f"Mitigation took {actual_minutes:.1f}min vs expected {expected_minutes}min. "
                "Consider updating runbook with faster procedures."
            )

        # Check for incomplete steps
        incomplete = [r for r in results if not r.completed]
        if incomplete:
            recommendations.append(
                f"{len(incomplete)} steps were not completed. "
                "Review runbook clarity and ensure all steps are actionable."
            )

        # Check for slow phases
        phase_times: dict[str, float] = {}
        for r in results:
            phase_times[r.phase] = phase_times.get(r.phase, 0) + r.time_taken_seconds

        slow_phases = [(p, t) for p, t in phase_times.items() if t > 60]
        if slow_phases:
            for phase, time_val in slow_phases:
                recommendations.append(
                    f"Phase '{phase}' took {time_val:.1f}s. "
                    "Consider adding automation or clearer instructions."
                )

        # Scenario-specific recommendations
        if scenario.severity == IncidentSeverity.T0:
            recommendations.append(
                "For T0 incidents, ensure war room is opened immediately and "
                "stakeholders are notified within 15 minutes."
            )

        return recommendations


def print_report(report: SimulationReport) -> None:
    """Print simulation report."""
    print(f"\n{'='*60}")
    print("SIMULATION COMPLETE")
    print(f"{'='*60}")

    status = "✅ PASSED" if report.passed else "❌ FAILED"
    print(f"\n{status}")
    print(f"\n📊 Summary:")
    print(f"   Scenario: {report.scenario_name}")
    print(f"   Severity: {report.severity.upper()}")
    print(f"   Duration: {report.total_duration_seconds:.1f}s")
    print(f"   Steps: {report.steps_completed}/{report.steps_total} completed")

    if report.recommendations:
        print(f"\n💡 Recommendations:")
        for rec in report.recommendations:
            print(f"   • {rec}")

    print(f"\n{'='*60}")


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Incident Response Simulation")
    parser.add_argument(
        "--scenario",
        type=str,
        default=None,
        help="Scenario ID to run (omit to list scenarios)",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List available scenarios",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Run in interactive mode",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output file for JSON report",
    )

    args = parser.parse_args()

    simulator = IncidentSimulator(output_file=args.output)

    if args.list or not args.scenario:
        print("Available Incident Scenarios:")
        print("=" * 60)
        for scenario in simulator.list_scenarios():
            print(f"\n📌 {scenario['id']}: {scenario['name']}")
            print(f"   Severity: {scenario['severity'].upper()}")
            print(f"   {scenario['description']}")
        print("\nUse --scenario <id> to run a simulation")
        return 0

    report = await simulator.run_simulation(
        args.scenario,
        interactive=args.interactive,
    )
    print_report(report)

    return 0 if report.passed else 1


if __name__ == "__main__":
    exit(asyncio.run(main()))
