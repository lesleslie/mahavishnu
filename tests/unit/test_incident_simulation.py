"""Tests for incident_simulation module."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from io import StringIO
import sys

import pytest

from mahavishnu.testing.incident_simulation import (
    INCIDENT_SCENARIOS,
    IncidentPhase,
    IncidentScenario,
    IncidentSeverity,
    IncidentSimulator,
    SimulationReport,
    SimulationResult,
    print_report,
)


class TestIncidentSeverity:
    """Tests for IncidentSeverity enum."""

    def test_all_five_values_exist(self):
        """Test all 5 severity levels are defined."""
        assert IncidentSeverity.T0.value == "t0"
        assert IncidentSeverity.T1.value == "t1"
        assert IncidentSeverity.T2.value == "t2"
        assert IncidentSeverity.T3.value == "t3"
        assert IncidentSeverity.T4.value == "t4"

    def test_count(self):
        """Test exactly 5 severity levels."""
        assert len(list(IncidentSeverity)) == 5

    def test_values_are_strings(self):
        """Test values are string-based (StrEnum)."""
        for severity in IncidentSeverity:
            assert isinstance(severity.value, str)


class TestIncidentPhase:
    """Tests for IncidentPhase enum."""

    def test_all_six_values_exist(self):
        """Test all 6 phase values are defined."""
        assert IncidentPhase.DETECTION.value == "detection"
        assert IncidentPhase.TRIAGE.value == "triage"
        assert IncidentPhase.INVESTIGATION.value == "investigation"
        assert IncidentPhase.MITIGATION.value == "mitigation"
        assert IncidentPhase.RESOLUTION.value == "resolution"
        assert IncidentPhase.POSTMORTEM.value == "postmortem"

    def test_count(self):
        """Test exactly 6 phases."""
        assert len(list(IncidentPhase)) == 6

    def test_values_are_strings(self):
        """Test values are string-based (StrEnum)."""
        for phase in IncidentPhase:
            assert isinstance(phase.value, str)


class TestIncidentScenario:
    """Tests for IncidentScenario dataclass."""

    def test_database_outage_scenario(self):
        """Test database_outage scenario structure."""
        scenario = INCIDENT_SCENARIOS["database_outage"]
        assert scenario.id == "INC-001"
        assert scenario.name == "Database Connection Pool Exhaustion"
        assert scenario.severity == IncidentSeverity.T1
        assert "All database connections are exhausted" in scenario.description
        assert len(scenario.symptoms) > 0
        assert "PostgreSQL" in scenario.affected_components
        assert scenario.expected_mitigation_time_minutes == 15
        assert len(scenario.steps) > 0

    def test_high_error_rate_scenario(self):
        """Test high_error_rate scenario structure."""
        scenario = INCIDENT_SCENARIOS["high_error_rate"]
        assert scenario.id == "INC-002"
        assert scenario.name == "Elevated Error Rate"
        assert scenario.severity == IncidentSeverity.T2
        assert len(scenario.steps) > 0

    def test_latency_spike_scenario(self):
        """Test latency_spike scenario structure."""
        scenario = INCIDENT_SCENARIOS["latency_spike"]
        assert scenario.id == "INC-003"
        assert scenario.name == "P99 Latency SLO Breach"
        assert scenario.severity == IncidentSeverity.T2

    def test_webhook_failure_scenario(self):
        """Test webhook_failure scenario structure."""
        scenario = INCIDENT_SCENARIOS["webhook_failure"]
        assert scenario.id == "INC-004"
        assert scenario.name == "Webhook Processing Failure"
        assert scenario.severity == IncidentSeverity.T2

    def test_complete_outage_scenario(self):
        """Test complete_outage scenario structure."""
        scenario = INCIDENT_SCENARIOS["complete_outage"]
        assert scenario.id == "INC-005"
        assert scenario.name == "Complete Service Outage"
        assert scenario.severity == IncidentSeverity.T0
        assert scenario.expected_mitigation_time_minutes == 60

    def test_all_scenarios_have_required_fields(self):
        """Test all predefined scenarios have all required fields."""
        for scenario_id, scenario in INCIDENT_SCENARIOS.items():
            assert scenario.id, f"Scenario {scenario_id} missing id"
            assert scenario.name, f"Scenario {scenario_id} missing name"
            assert scenario.description, f"Scenario {scenario_id} missing description"
            assert scenario.severity, f"Scenario {scenario_id} missing severity"
            assert scenario.symptoms, f"Scenario {scenario_id} missing symptoms"
            assert scenario.affected_components, f"Scenario {scenario_id} missing affected_components"
            assert scenario.runbook_reference, f"Scenario {scenario_id} missing runbook_reference"
            assert scenario.expected_mitigation_time_minutes > 0, f"Scenario {scenario_id} missing mitigation time"


class TestSimulationResult:
    """Tests for SimulationResult dataclass."""

    def test_field_access(self):
        """Test SimulationResult fields can be accessed."""
        result = SimulationResult(
            step_number=1,
            phase="detection",
            action="Acknowledge alert",
            expected_criteria="Alert acknowledged",
            completed=True,
            time_taken_seconds=1.5,
            notes="Test note",
        )
        assert result.step_number == 1
        assert result.phase == "detection"
        assert result.action == "Acknowledge alert"
        assert result.expected_criteria == "Alert acknowledged"
        assert result.completed is True
        assert result.time_taken_seconds == 1.5
        assert result.notes == "Test note"

    def test_default_notes(self):
        """Test SimulationResult default notes is empty string."""
        result = SimulationResult(
            step_number=1,
            phase="detection",
            action="Acknowledge alert",
            expected_criteria="Alert acknowledged",
            completed=True,
            time_taken_seconds=1.5,
        )
        assert result.notes == ""


class TestSimulationReport:
    """Tests for SimulationReport dataclass."""

    def test_field_access(self):
        """Test SimulationReport fields can be accessed."""
        report = SimulationReport(
            scenario_id="INC-001",
            scenario_name="Database Outage",
            severity="t1",
            start_time="2024-01-01T00:00:00Z",
            end_time="2024-01-01T00:15:00Z",
            total_duration_seconds=900.0,
            steps_completed=5,
            steps_total=5,
            passed=True,
            results=[],
            recommendations=["Test recommendation"],
        )
        assert report.scenario_id == "INC-001"
        assert report.scenario_name == "Database Outage"
        assert report.severity == "t1"
        assert report.total_duration_seconds == 900.0
        assert report.steps_completed == 5
        assert report.steps_total == 5
        assert report.passed is True
        assert report.recommendations == ["Test recommendation"]

    def test_to_dict(self):
        """Test SimulationReport.to_dict() returns correct structure."""
        report = SimulationReport(
            scenario_id="INC-001",
            scenario_name="Database Outage",
            severity="t1",
            start_time="2024-01-01T00:00:00Z",
            end_time="2024-01-01T00:15:00Z",
            total_duration_seconds=900.0,
            steps_completed=5,
            steps_total=5,
            passed=True,
            results=[
                SimulationResult(
                    step_number=1,
                    phase="detection",
                    action="Acknowledge alert",
                    expected_criteria="Alert acknowledged",
                    completed=True,
                    time_taken_seconds=1.5,
                    notes="Test note",
                )
            ],
            recommendations=["Recommendation 1"],
        )
        result_dict = report.to_dict()

        assert result_dict["scenario_id"] == "INC-001"
        assert result_dict["scenario_name"] == "Database Outage"
        assert result_dict["severity"] == "t1"
        assert result_dict["total_duration_seconds"] == 900.0
        assert result_dict["steps_completed"] == 5
        assert result_dict["steps_total"] == 5
        assert result_dict["passed"] is True
        assert len(result_dict["results"]) == 1
        assert result_dict["results"][0]["step_number"] == 1
        assert result_dict["results"][0]["phase"] == "detection"
        assert result_dict["results"][0]["notes"] == "Test note"
        assert result_dict["recommendations"] == ["Recommendation 1"]

    def test_to_dict_rounds_values(self):
        """Test to_dict() rounds float values."""
        report = SimulationReport(
            scenario_id="INC-001",
            scenario_name="Test",
            severity="t2",
            start_time="2024-01-01T00:00:00Z",
            end_time="2024-01-01T00:05:00Z",
            total_duration_seconds=300.123456,
            steps_completed=2,
            steps_total=2,
            passed=True,
            results=[
                SimulationResult(
                    step_number=1,
                    phase="detection",
                    action="Test action",
                    expected_criteria="Test criteria",
                    completed=True,
                    time_taken_seconds=10.123456,
                    notes="",
                )
            ],
            recommendations=[],
        )
        result_dict = report.to_dict()
        assert result_dict["total_duration_seconds"] == 300.12
        assert result_dict["results"][0]["time_taken_seconds"] == 10.12


class TestIncidentSimulator:
    """Tests for IncidentSimulator class."""

    def test_list_scenarios(self):
        """Test list_scenarios returns list of scenario summaries."""
        simulator = IncidentSimulator()
        scenarios = simulator.list_scenarios()

        assert isinstance(scenarios, list)
        assert len(scenarios) == 5  # 5 predefined scenarios

        for scenario in scenarios:
            assert "id" in scenario
            assert "name" in scenario
            assert "severity" in scenario
            assert "description" in scenario

    def test_list_scenarios_contains_all_ids(self):
        """Test list_scenarios includes all scenario IDs."""
        simulator = IncidentSimulator()
        scenarios = simulator.list_scenarios()
        scenario_ids = [s["id"] for s in scenarios]

        assert "INC-001" in scenario_ids
        assert "INC-002" in scenario_ids
        assert "INC-003" in scenario_ids
        assert "INC-004" in scenario_ids
        assert "INC-005" in scenario_ids

    @pytest.mark.asyncio
    async def test_run_simulation(self):
        """Test run_simulation executes scenario and returns report."""
        simulator = IncidentSimulator()
        report = await simulator.run_simulation("database_outage", interactive=False)

        assert isinstance(report, SimulationReport)
        assert report.scenario_id == "INC-001"
        assert report.scenario_name == "Database Connection Pool Exhaustion"
        assert report.severity == "t1"
        assert report.steps_total == 5
        assert report.steps_completed == 5
        assert report.passed is True
        assert len(report.results) == 5
        assert report.start_time is not None
        assert report.end_time is not None

    @pytest.mark.asyncio
    async def test_run_simulation_unknown_scenario_raises(self):
        """Test run_simulation raises ValueError for unknown scenario."""
        simulator = IncidentSimulator()
        with pytest.raises(ValueError, match="Unknown scenario"):
            await simulator.run_simulation("nonexistent_scenario")

    @pytest.mark.asyncio
    async def test_run_simulation_complete_outage(self):
        """Test run_simulation for complete_outage scenario (6 steps)."""
        simulator = IncidentSimulator()
        report = await simulator.run_simulation("complete_outage", interactive=False)

        assert report.scenario_id == "INC-005"
        assert report.steps_total == 6
        assert report.steps_completed == 6
        assert report.passed is True
        # T0 should generate war room recommendation
        assert len(report.recommendations) > 0

    @pytest.mark.asyncio
    async def test_run_simulation_stores_results(self):
        """Test run_simulation stores phase and action in results."""
        simulator = IncidentSimulator()
        report = await simulator.run_simulation("database_outage", interactive=False)

        phases_seen = set(r.phase for r in report.results)
        assert "detection" in phases_seen
        assert "triage" in phases_seen
        assert "investigation" in phases_seen
        assert "mitigation" in phases_seen
        assert "resolution" in phases_seen

        actions_seen = [r.action for r in report.results]
        assert len(actions_seen) == 5


class TestPrintReport:
    """Tests for print_report function."""

    def test_print_report_outputs_to_stdout(self):
        """Test print_report writes to stdout."""
        report = SimulationReport(
            scenario_id="INC-001",
            scenario_name="Test Scenario",
            severity="t2",
            start_time="2024-01-01T00:00:00Z",
            end_time="2024-01-01T00:10:00Z",
            total_duration_seconds=600.0,
            steps_completed=3,
            steps_total=3,
            passed=True,
            results=[],
            recommendations=["Recommendation 1", "Recommendation 2"],
        )

        captured = StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured
        try:
            print_report(report)
        finally:
            sys.stdout = old_stdout

        output = captured.getvalue()
        assert "SIMULATION COMPLETE" in output
        assert "PASSED" in output
        assert "Test Scenario" in output
        assert "T2" in output
        assert "600.0" in output or "600" in output
        assert "3/3" in output
        assert "Recommendation 1" in output
        assert "Recommendation 2" in output

    def test_print_report_shows_failed_status(self):
        """Test print_report shows FAILED for non-passed report."""
        report = SimulationReport(
            scenario_id="INC-001",
            scenario_name="Failed Scenario",
            severity="t1",
            start_time="2024-01-01T00:00:00Z",
            end_time="2024-01-01T00:05:00Z",
            total_duration_seconds=300.0,
            steps_completed=2,
            steps_total=4,
            passed=False,
            results=[],
            recommendations=["More training needed"],
        )

        captured = StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured
        try:
            print_report(report)
        finally:
            sys.stdout = old_stdout

        output = captured.getvalue()
        assert "FAILED" in output
        assert "2/4" in output

    def test_print_report_no_recommendations(self):
        """Test print_report handles empty recommendations."""
        report = SimulationReport(
            scenario_id="INC-001",
            scenario_name="Clean Scenario",
            severity="t3",
            start_time="2024-01-01T00:00:00Z",
            end_time="2024-01-01T00:05:00Z",
            total_duration_seconds=300.0,
            steps_completed=3,
            steps_total=3,
            passed=True,
            results=[],
            recommendations=[],
        )

        captured = StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured
        try:
            print_report(report)
        finally:
            sys.stdout = old_stdout

        output = captured.getvalue()
        assert "Recommendations:" not in output or output.count("Recommendations:") == 0


class TestMain:
    """Tests for main() async CLI entry point."""

    @pytest.mark.asyncio
    async def test_main_list_scenarios(self):
        """Test main() with --list flag returns 0."""
        from mahavishnu.testing.incident_simulation import main
        import argparse

        # Capture stdout
        captured = StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured
        try:
            # Mock sys.argv
            old_argv = sys.argv
            sys.argv = ["incident_simulation", "--list"]
            try:
                result = await main()
            finally:
                sys.argv = old_argv
        finally:
            sys.stdout = old_stdout

        output = captured.getvalue()
        assert result == 0
        assert "Available Incident Scenarios" in output
        assert "INC-001" in output
        assert "INC-002" in output

    @pytest.mark.asyncio
    async def test_main_runs_scenario(self):
        """Test main() with valid scenario returns 0 on pass."""
        from mahavishnu.testing.incident_simulation import main

        old_argv = sys.argv
        sys.argv = ["incident_simulation", "--scenario", "database_outage"]
        captured = StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured
        try:
            try:
                result = await main()
            finally:
                sys.argv = old_argv
        finally:
            sys.stdout = old_stdout

        output = captured.getvalue()
        assert result == 0
        assert "SIMULATION COMPLETE" in output

    @pytest.mark.asyncio
    async def test_main_invalid_scenario_raises(self):
        """Test main() with invalid scenario raises ValueError."""
        from mahavishnu.testing.incident_simulation import main

        old_argv = sys.argv
        sys.argv = ["incident_simulation", "--scenario", "nonexistent"]
        try:
            with pytest.raises(ValueError, match="Unknown scenario"):
                await main()
        finally:
            sys.argv = old_argv