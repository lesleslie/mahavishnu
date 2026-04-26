"""Tests for MCP error envelope and ecosystem tool validation."""

import pytest
from datetime import datetime

from mahavishnu.mcp.error_envelope import McpErrorEnvelope, wrap_error


class TestMcpErrorEnvelope:
    def test_defaults(self):
        env = McpErrorEnvelope(error_code="MHV-500", message="test")
        assert env.error is True
        assert env.retryable is False
        assert env.retry_after_seconds is None
        assert env.recovery == []
        assert env.details == {}

    def test_full_construction(self):
        env = McpErrorEnvelope(
            error_code="MHV-501",
            message="service unavailable",
            recovery=["retry", "check logs"],
            retryable=True,
            retry_after_seconds=30,
            details={"service": "session_buddy"},
        )
        assert env.error_code == "MHV-501"
        assert len(env.recovery) == 2
        assert env.retry_after_seconds == 30
        assert env.details["service"] == "session_buddy"

    def test_json_serialization(self):
        env = McpErrorEnvelope(error_code="MHV-500", message="test")
        data = env.model_dump(mode="json")
        assert data["error"] is True
        assert "error_code" in data


class TestWrapError:
    def test_basic(self):
        env = wrap_error("MHV-500", "something failed")
        assert env.error_code == "MHV-500"
        assert env.message == "something failed"

    def test_with_options(self):
        env = wrap_error(
            "MHV-502",
            "timeout",
            recovery=["increase timeout"],
            retryable=True,
            retry_after_seconds=60,
        )
        assert env.retryable is True
        assert env.retry_after_seconds == 60
        assert env.recovery == ["increase timeout"]


class TestCanonicalStatus:
    def test_all_values(self):
        from mahavishnu.core.ecosystem_status import CanonicalStatus

        values = {s.value for s in CanonicalStatus}
        assert values == {"ok", "degraded", "unhealthy", "unknown", "disabled"}

    def test_severity_ordering(self):
        from mahavishnu.core.ecosystem_status import CanonicalStatus, STATUS_SEVERITY

        order = [
            CanonicalStatus.DISABLED,
            CanonicalStatus.UNKNOWN,
            CanonicalStatus.OK,
            CanonicalStatus.DEGRADED,
            CanonicalStatus.UNHEALTHY,
        ]
        for i in range(len(order) - 1):
            assert STATUS_SEVERITY[order[i]] < STATUS_SEVERITY[order[i + 1]]


class TestNormalizeStatus:
    def test_common_mappings(self):
        from mahavishnu.core.ecosystem_status import CanonicalStatus, normalize_status

        assert normalize_status("healthy") == CanonicalStatus.OK
        assert normalize_status("degraded") == CanonicalStatus.DEGRADED
        assert normalize_status("unhealthy") == CanonicalStatus.UNHEALTHY
        assert normalize_status("error") == CanonicalStatus.UNHEALTHY
        assert normalize_status("not_configured") == CanonicalStatus.DISABLED

    def test_unknown_raw(self):
        from mahavishnu.core.ecosystem_status import CanonicalStatus, normalize_status

        assert normalize_status("something_weird") == CanonicalStatus.UNKNOWN


class TestAggregateStatuses:
    def test_all_ok(self):
        from mahavishnu.core.ecosystem_status import CanonicalStatus, aggregate_statuses

        result = aggregate_statuses([CanonicalStatus.OK, CanonicalStatus.OK])
        assert result == CanonicalStatus.OK

    def test_mixed_with_unhealthy(self):
        from mahavishnu.core.ecosystem_status import CanonicalStatus, aggregate_statuses

        result = aggregate_statuses([CanonicalStatus.OK, CanonicalStatus.UNHEALTHY])
        assert result == CanonicalStatus.UNHEALTHY

    def test_optional_degraded_only(self):
        from mahavishnu.core.ecosystem_status import CanonicalStatus, aggregate_statuses

        result = aggregate_statuses([CanonicalStatus.OK, CanonicalStatus.DEGRADED])
        assert result == CanonicalStatus.DEGRADED

    def test_empty_list_returns_unknown(self):
        from mahavishnu.core.ecosystem_status import CanonicalStatus, aggregate_statuses

        result = aggregate_statuses([])
        assert result == CanonicalStatus.UNKNOWN


class TestEcosystemStatusReport:
    def test_report_creation_with_mock_data(self):
        from mahavishnu.core.ecosystem_status import (
            CanonicalStatus,
            EcosystemStatusReport,
            ServiceStatus,
        )

        report = EcosystemStatusReport(
            status=CanonicalStatus.OK,
            generated_at=datetime.now(),
            duration_ms=12.5,
            request_id="test-123",
            services={
                "session_buddy": ServiceStatus(
                    status=CanonicalStatus.OK,
                    required=True,
                ),
                "crackerjack": ServiceStatus(
                    status=CanonicalStatus.DEGRADED,
                    required=False,
                ),
            },
        )
        assert report.status == CanonicalStatus.OK
        assert len(report.services) == 2
        assert report.schema_version == "1.0"

    def test_report_model_dump(self):
        from mahavishnu.core.ecosystem_status import (
            CanonicalStatus,
            EcosystemStatusReport,
        )

        report = EcosystemStatusReport(
            status=CanonicalStatus.OK,
            generated_at=datetime.now(),
            duration_ms=5.0,
        )
        data = report.model_dump()
        assert "status" in data
        assert "generated_at" in data
        assert "services" in data
        assert "adapters" in data
        assert "capabilities" in data
        assert "workflows" in data
        assert "alerts" in data
        assert "recommendations" in data
        assert "errors" in data

    def test_report_json_serialization(self):
        from mahavishnu.core.ecosystem_status import (
            CanonicalStatus,
            EcosystemStatusReport,
        )

        report = EcosystemStatusReport(
            status=CanonicalStatus.OK,
            generated_at=datetime.now(),
            duration_ms=5.0,
        )
        json_data = report.model_dump(mode="json")
        assert json_data["status"] == "ok"
        assert json_data["schema_version"] == "1.0"
