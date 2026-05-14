"""Tests for the deterministic C5 golden-path prep packet."""

from __future__ import annotations

from tests.fixtures.golden_path_fixture import (
    golden_path_contract_packet,
    golden_path_incident_fixture,
)


def test_golden_path_fixture_is_deterministic() -> None:
    fixture = golden_path_incident_fixture()

    assert fixture.incident_id == "INC-20260511-001"
    assert fixture.correlation_id == "corr-20260511-golden-path-001"
    assert fixture.workflow_id == "wf-20260511-golden-path-001"
    assert fixture.issue_id == "ISSUE-2048"
    assert fixture.repo == "mahavishnu"
    assert fixture.detection_source == "Mahavishnu quality gate + event spine"
    assert "quality gate failure" in fixture.summary.lower()


def test_golden_path_contract_packet_includes_expected_services() -> None:
    packet = golden_path_contract_packet()

    assert packet["fixture"]["correlation_id"] == "corr-20260511-golden-path-001"
    assert len(packet["service_contracts"]) == 4
    repos = {contract["repo"] for contract in packet["service_contracts"]}
    assert repos == {"crackerjack", "session-buddy", "akosha", "dhara"}


def test_golden_path_trace_assertions_reference_one_correlation_id() -> None:
    fixture = golden_path_incident_fixture()
    correlation_id = fixture.correlation_id

    assert any(correlation_id in assertion for assertion in fixture.trace_assertions)
    assert any("Session-Buddy" in assertion for assertion in fixture.trace_assertions)
    assert any("Dhara" in assertion for assertion in fixture.trace_assertions)


def test_golden_path_operator_transcript_covers_expected_stages() -> None:
    fixture = golden_path_incident_fixture()
    transcript = "\n".join(fixture.operator_transcript)

    assert "Incident detected" in transcript
    assert "Crackerjack" in transcript
    assert "Session-Buddy" in transcript
    assert "approval" in transcript.lower()
    assert "Dhara" in transcript
    assert "Akosha" in transcript
