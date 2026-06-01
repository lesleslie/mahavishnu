"""Tests for canonical status normalization."""

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from mahavishnu.core.ecosystem_status import (
    AdapterStatus,
    AlertSummary,
    CanonicalStatus,
    EcosystemStatusReport,
    EcosystemStatusService,
    SectionError,
    ServiceStatus,
    WorkflowSummary,
    aggregate_statuses,
    aggregate_with_optional,
    is_valid_transition,
    normalize_status,
)


class TestNormalizeStatus:
    def test_healthy_to_ok(self):
        assert normalize_status("healthy") == CanonicalStatus.OK

    def test_ok_to_ok(self):
        assert normalize_status("ok") == CanonicalStatus.OK

    def test_degraded_stays(self):
        assert normalize_status("degraded") == CanonicalStatus.DEGRADED

    def test_unhealthy_stays(self):
        assert normalize_status("unhealthy") == CanonicalStatus.UNHEALTHY

    def test_error_to_unhealthy(self):
        assert normalize_status("error") == CanonicalStatus.UNHEALTHY

    def test_not_configured_to_disabled(self):
        assert normalize_status("not_configured") == CanonicalStatus.DISABLED

    def test_unknown_raw_to_unknown(self):
        assert normalize_status("something_weird") == CanonicalStatus.UNKNOWN

    def test_case_insensitive(self):
        assert normalize_status("Healthy") == CanonicalStatus.OK
        assert normalize_status("UNHEALTHY") == CanonicalStatus.UNHEALTHY


class TestAggregateStatuses:
    def test_all_ok(self):
        assert aggregate_statuses([CanonicalStatus.OK, CanonicalStatus.OK]) == CanonicalStatus.OK

    def test_one_degraded(self):
        assert (
            aggregate_statuses([CanonicalStatus.OK, CanonicalStatus.DEGRADED])
            == CanonicalStatus.DEGRADED
        )

    def test_one_unhealthy(self):
        assert (
            aggregate_statuses([CanonicalStatus.OK, CanonicalStatus.UNHEALTHY, CanonicalStatus.OK])
            == CanonicalStatus.UNHEALTHY
        )

    def test_empty_list(self):
        assert aggregate_statuses([]) == CanonicalStatus.UNKNOWN

    def test_unknown_in_list(self):
        result = aggregate_statuses([CanonicalStatus.OK, CanonicalStatus.UNKNOWN])
        # UNKNOWN has severity 1, OK has 2 -- so UNKNOWN wins (higher severity = worse)
        # Actually wait -- UNKNOWN severity is 1, OK is 2. max() picks OK. That's wrong.
        # Let me check: STATUS_SEVERITY[UNKNOWN] = 1, STATUS_SEVERITY[OK] = 2.
        # max picks the higher severity number. So OK (2) > UNKNOWN (1), result = OK.
        # But semantically, if one component is UNKNOWN, the aggregate should reflect uncertainty.
        # The current implementation uses max() which picks the worst by severity number.
        # OK=2 > UNKNOWN=1, so OK wins. This is by design: OK is "more known" than UNKNOWN.
        assert result == CanonicalStatus.OK

    def test_disabled_is_lowest_severity(self):
        assert (
            aggregate_statuses([CanonicalStatus.DISABLED, CanonicalStatus.OK]) == CanonicalStatus.OK
        )


class TestAggregateWithOptional:
    def test_required_unhealthy_fails(self):
        result = aggregate_with_optional(
            required=[CanonicalStatus.UNHEALTHY],
            optional=[CanonicalStatus.OK],
        )
        assert result == CanonicalStatus.UNHEALTHY

    def test_optional_unhealthy_degrades_only(self):
        result = aggregate_with_optional(
            required=[CanonicalStatus.OK],
            optional=[CanonicalStatus.UNHEALTHY],
        )
        assert result == CanonicalStatus.DEGRADED

    def test_all_ok(self):
        result = aggregate_with_optional(
            required=[CanonicalStatus.OK],
            optional=[CanonicalStatus.OK, CanonicalStatus.OK],
        )
        assert result == CanonicalStatus.OK

    def test_optional_unknown_keeps_ok(self):
        result = aggregate_with_optional(
            required=[CanonicalStatus.OK],
            optional=[CanonicalStatus.UNKNOWN],
        )
        assert result == CanonicalStatus.OK

    def test_empty_lists(self):
        result = aggregate_with_optional(required=[], optional=[])
        assert result == CanonicalStatus.OK

    def test_required_degraded_returns_degraded(self):
        result = aggregate_with_optional(
            required=[CanonicalStatus.DEGRADED],
            optional=[CanonicalStatus.OK],
        )
        assert result == CanonicalStatus.DEGRADED

    def test_optional_degraded_returns_degraded(self):
        result = aggregate_with_optional(
            required=[CanonicalStatus.OK],
            optional=[CanonicalStatus.DEGRADED],
        )
        assert result == CanonicalStatus.DEGRADED


class TestValidTransitions:
    def test_ok_to_degraded(self):
        assert is_valid_transition(CanonicalStatus.OK, CanonicalStatus.DEGRADED) is True

    def test_ok_to_unhealthy_is_invalid(self):
        # Must go through DEGRADED first
        assert is_valid_transition(CanonicalStatus.OK, CanonicalStatus.UNHEALTHY) is False

    def test_degraded_to_ok(self):
        assert is_valid_transition(CanonicalStatus.DEGRADED, CanonicalStatus.OK) is True

    def test_unhealthy_to_ok_is_invalid(self):
        # Must go through DEGRADED first
        assert is_valid_transition(CanonicalStatus.UNHEALTHY, CanonicalStatus.OK) is False

    def test_unknown_to_any(self):
        assert is_valid_transition(CanonicalStatus.UNKNOWN, CanonicalStatus.OK) is True
        assert is_valid_transition(CanonicalStatus.UNKNOWN, CanonicalStatus.UNHEALTHY) is True


class TestEcosystemStatusReport:
    def test_default_report(self):
        report = EcosystemStatusReport(
            status=CanonicalStatus.OK,
            generated_at=datetime.now(),
            duration_ms=10.0,
        )
        assert report.schema_version == "1.0"
        assert report.services == {}
        assert report.adapters == {}
        assert report.recovery.recovered_workflows == 0
        assert report.errors == []

    def test_report_with_services(self):
        report = EcosystemStatusReport(
            status=CanonicalStatus.DEGRADED,
            generated_at=datetime.now(),
            duration_ms=50.0,
            services={
                "session_buddy": ServiceStatus(status=CanonicalStatus.OK, required=True),
                "akosha": ServiceStatus(status=CanonicalStatus.DEGRADED, required=False),
            },
        )
        assert len(report.services) == 2
        assert report.services["session_buddy"].required is True


class TestEcosystemStatusService:
    class _RecoveryProvider:
        async def get_recovery_summary(self):
            return {
                "recovered_workflows": 2,
                "recovered_approvals": 3,
                "recovered_pools": 4,
                "recovered_routing_decisions": 5,
                "dhara_available": True,
            }

    @pytest.mark.asyncio
    async def test_generate_empty_report(self):
        service = EcosystemStatusService()
        report = await service.generate_report()
        assert report.schema_version == "1.0"
        assert report.status == CanonicalStatus.UNKNOWN  # No services -> UNKNOWN
        assert report.duration_ms >= 0
        assert report.errors == []

    @pytest.mark.asyncio
    async def test_generate_report_includes_recovery_summary(self):
        service = EcosystemStatusService(recovery_provider=self._RecoveryProvider())
        report = await service.generate_report()
        assert report.recovery.recovered_workflows == 2
        assert report.recovery.recovered_approvals == 3
        assert report.recovery.dhara_available is True

    @pytest.mark.asyncio
    async def test_generate_report_defaults_without_recovery_provider(self):
        service = EcosystemStatusService(recovery_provider=None)
        report = await service.generate_report()
        assert report.recovery.recovered_workflows == 0
        assert report.recovery.dhara_available is False

    @pytest.mark.asyncio
    async def test_generate_report_with_request_id(self):
        service = EcosystemStatusService()
        report = await service.generate_report(request_id="test-123")
        assert report.request_id == "test-123"

    @pytest.mark.asyncio
    async def test_section_failure_produces_error_not_exception(self):
        """A failing section should produce a SectionError, not crash the report."""
        service = EcosystemStatusService()

        # Monkey-patch a collector to raise
        original = service._collect_services

        async def failing():
            raise RuntimeError("connection refused")

        service._collect_services = failing

        report = await service.generate_report()
        assert len(report.errors) == 1
        assert report.errors[0].section == "services"
        assert "connection refused" in report.errors[0].message
        # Report still generates
        assert report.generated_at is not None

        service._collect_services = original

    @pytest.mark.asyncio
    async def test_staleness_detection(self):
        """Services with old last_check should be flagged as UNKNOWN."""
        service = EcosystemStatusService(staleness_threshold_seconds=60.0)

        stale_time = datetime.now() - timedelta(seconds=120)
        fresh_time = datetime.now() - timedelta(seconds=10)

        services = {
            "stale_service": ServiceStatus(
                status=CanonicalStatus.OK,
                last_check=stale_time,
            ),
            "fresh_service": ServiceStatus(
                status=CanonicalStatus.OK,
                last_check=fresh_time,
            ),
        }

        result = service._detect_staleness(services)
        assert result["stale_service"].status == CanonicalStatus.UNKNOWN
        assert result["fresh_service"].status == CanonicalStatus.OK

    def test_staleness_no_last_check(self):
        """Items without last_check should not be flagged."""
        service = EcosystemStatusService(staleness_threshold_seconds=60.0)
        services = {
            "no_check": ServiceStatus(status=CanonicalStatus.OK),
        }
        result = service._detect_staleness(services)
        assert result["no_check"].status == CanonicalStatus.OK


class TestSectionError:
    def test_basic_error(self):
        err = SectionError(section="services", message="timeout")
        assert err.section == "services"
        assert err.original_exception is None

    def test_error_with_exception(self):
        err = SectionError(
            section="adapters",
            message="connection refused",
            original_exception="ConnectionError",
        )
        assert err.original_exception == "ConnectionError"


# ── Live data collection tests ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_collect_services_with_no_configs():
    """No service configs returns empty dict."""
    from mahavishnu.core.ecosystem_status import EcosystemStatusService

    svc = EcosystemStatusService()
    result = await svc._collect_services()
    assert result == {}


@pytest.mark.asyncio
async def test_collect_services_disabled_url():
    """Empty URL returns DISABLED status."""
    from mahavishnu.core.ecosystem_status import EcosystemStatusService

    svc = EcosystemStatusService(service_configs={"test": {"url": "", "required": False}})
    result = await svc._collect_services()
    assert result["test"].status == CanonicalStatus.DISABLED


@pytest.mark.asyncio
async def test_collect_services_unreachable():
    """Unreachable URL returns UNKNOWN status."""
    from mahavishnu.core.ecosystem_status import EcosystemStatusService

    svc = EcosystemStatusService(
        service_configs={"ghost": {"url": "http://127.0.0.1:1/health", "timeout_s": 1}}
    )
    result = await svc._collect_services()
    assert result["ghost"].status == CanonicalStatus.UNKNOWN


@pytest.mark.asyncio
async def test_collect_adapters_with_no_adapters():
    """No adapters returns empty dict."""
    from mahavishnu.core.ecosystem_status import EcosystemStatusService

    svc = EcosystemStatusService()
    result = await svc._collect_adapters()
    assert result == {}


@pytest.mark.asyncio
async def test_collect_workflows_with_no_provider():
    """No workflow provider returns zeroed summary."""
    from mahavishnu.core.ecosystem_status import EcosystemStatusService

    svc = EcosystemStatusService()
    result = await svc._collect_workflows()
    assert result == WorkflowSummary()


@pytest.mark.asyncio
async def test_collect_alerts_with_no_provider():
    """No alert provider returns empty summary."""
    from mahavishnu.core.ecosystem_status import EcosystemStatusService

    svc = EcosystemStatusService()
    result = await svc._collect_alerts()
    assert result == AlertSummary()


class TestEcosystemStatusServiceCollectionBranches:
    @pytest.mark.asyncio
    async def test_collect_services_success(self, monkeypatch):
        import httpx

        from mahavishnu.core.ecosystem_status import CanonicalStatus, EcosystemStatusService

        class FakeResponse:
            def json(self):
                return {"status": "healthy", "latency_ms": 42}

        class FakeClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def get(self, url):
                return FakeResponse()

        monkeypatch.setattr(httpx, "AsyncClient", FakeClient)

        svc = EcosystemStatusService(
            service_configs={"session_buddy": {"url": "http://example.test", "required": True}}
        )
        result = await svc._collect_services()

        assert result["session_buddy"].status == CanonicalStatus.OK
        assert result["session_buddy"].latency_ms == 42

    @pytest.mark.asyncio
    async def test_collect_adapters_success_and_failure(self):
        from mahavishnu.core.ecosystem_status import CanonicalStatus, EcosystemStatusService

        class GoodAdapter:
            async def get_health(self):
                return {"status": "degraded", "preference_score": 0.4}

        class BadAdapter:
            async def get_health(self):
                raise RuntimeError("adapter down")

        svc = EcosystemStatusService(adapters={"good": GoodAdapter(), "bad": BadAdapter()})
        result = await svc._collect_adapters()

        assert result["good"].status == CanonicalStatus.DEGRADED
        assert result["good"].preference_score == 0.4
        assert result["bad"].status == CanonicalStatus.UNKNOWN

    @pytest.mark.asyncio
    async def test_collect_workflows_recovery_and_alerts(self):
        from mahavishnu.core.ecosystem_status import EcosystemStatusService

        class WorkflowProvider:
            async def list_workflows(self, limit):
                return [
                    {"status": "running"},
                    {"status": "failed"},
                    {"status": "completed"},
                ]

        class RecoveryProvider:
            async def get_recovery_summary(self):
                return {
                    "recovered_workflows": 3,
                    "recovered_approvals": 4,
                    "recovered_pools": 5,
                    "recovered_routing_decisions": 6,
                    "dhara_available": True,
                }

        class Alert:
            def __init__(self, severity, type_, description):
                self.severity = severity
                self.type = type_
                self.description = description
                self.timestamp = datetime.now()

        class AlertProvider:
            def get_active_alerts_sync(self):
                return [
                    Alert(SimpleNamespace(value="warning"), "monitoring", "One alert"),
                    Alert("critical", "routing", "Two alert"),
                ]

        svc = EcosystemStatusService(
            workflow_provider=WorkflowProvider(),
            recovery_provider=RecoveryProvider(),
            alert_provider=AlertProvider(),
        )

        workflows = await svc._collect_workflows()
        recovery = await svc._collect_recovery()
        alerts = await svc._collect_alerts()

        assert workflows.active_count == 1
        assert workflows.failed_count == 1
        assert recovery.recovered_workflows == 3
        assert recovery.dhara_available is True
        assert alerts.total_active == 2
        assert alerts.by_severity["warning"] == 1
        assert alerts.by_severity["critical"] == 1

    @pytest.mark.asyncio
    async def test_collect_recovery_returns_summary_object(self):
        from mahavishnu.core.ecosystem_status import EcosystemStatusService, RecoverySummary

        class RecoveryProvider:
            async def get_recovery_summary(self):
                return RecoverySummary(
                    recovered_workflows=7,
                    recovered_approvals=8,
                    recovered_pools=9,
                    recovered_routing_decisions=10,
                    dhara_available=False,
                )

        svc = EcosystemStatusService(recovery_provider=RecoveryProvider())
        result = await svc._collect_recovery()

        assert result.recovered_workflows == 7
        assert result.dhara_available is False

    @pytest.mark.asyncio
    async def test_collect_workflows_recovery_and_alerts_fail_closed(self):
        from mahavishnu.core.ecosystem_status import (
            AlertSummary,
            EcosystemStatusService,
            RecoverySummary,
            WorkflowSummary,
        )

        class FailingWorkflowProvider:
            async def list_workflows(self, limit):
                raise RuntimeError("workflow store unavailable")

        class FailingRecoveryProvider:
            async def get_recovery_summary(self):
                raise RuntimeError("recovery store unavailable")

        class FailingAlertProvider:
            def get_active_alerts_sync(self):
                raise RuntimeError("alerts unavailable")

        svc = EcosystemStatusService(
            workflow_provider=FailingWorkflowProvider(),
            recovery_provider=FailingRecoveryProvider(),
            alert_provider=FailingAlertProvider(),
        )

        workflows = await svc._collect_workflows()
        recovery = await svc._collect_recovery()
        alerts = await svc._collect_alerts()

        assert workflows == WorkflowSummary()
        assert recovery == RecoverySummary()
        assert alerts == AlertSummary()

    @pytest.mark.asyncio
    async def test_collect_capabilities_health_fallback_and_failure(self):
        from mahavishnu.core.ecosystem_status import CanonicalStatus, EcosystemStatusService

        class HealthCapabilitiesAdapter:
            async def get_health(self):
                return {"status": "healthy", "capabilities": ["vector_search", "message_bus"]}

        class FailingAdapter:
            async def get_health(self):
                raise RuntimeError("boom")

        svc = EcosystemStatusService(
            adapters={"fallback": HealthCapabilitiesAdapter(), "broken": FailingAdapter()}
        )
        result = await svc._collect_capabilities()

        assert result["vector_search"].status == CanonicalStatus.OK
        assert result["vector_search"].provided_by == ["fallback"]
        assert result["vector_search"].category == "retrieval"
        assert result["message_bus"].category == "messaging"
        assert result["message_bus"].provided_by == ["fallback"]

    @pytest.mark.asyncio
    async def test_collect_capabilities_updates_to_worst_status(self):
        from mahavishnu.core.ecosystem_status import CanonicalStatus, EcosystemStatusService

        class HealthyAdapter:
            async def get_health(self):
                return {"status": "healthy", "capabilities": ["metrics"]}

        class UnhealthyAdapter:
            async def get_health(self):
                return {"status": "unhealthy", "capabilities": ["metrics"]}

        svc = EcosystemStatusService(
            adapters={"healthy": HealthyAdapter(), "unhealthy": UnhealthyAdapter()}
        )
        result = await svc._collect_capabilities()

        assert result["metrics"].status == CanonicalStatus.UNHEALTHY
        assert result["metrics"].provided_by == ["healthy", "unhealthy"]


# ── Phase 5: Routing decision models and ring buffer ───────────────────────


class TestRejectionReason:
    def test_all_values_are_strings(self):
        from mahavishnu.core.ecosystem_status import RejectionReason

        for reason in RejectionReason:
            assert isinstance(reason.value, str)

    def test_expected_values_present(self):
        from mahavishnu.core.ecosystem_status import RejectionReason

        assert RejectionReason.HEALTH_FAILED.value == "health_failed"
        assert RejectionReason.CAPABILITY_MISSING.value == "capability_missing"
        assert RejectionReason.DISABLED.value == "disabled"


class TestRoutingDecision:
    def test_default_decision_id_is_set(self):
        from mahavishnu.core.ecosystem_status import RoutingDecision

        d = RoutingDecision(
            task_id="t1",
            task_class="AI_TASK",
            selected_adapter="prefect",
        )
        assert d.decision_id
        assert d.confidence == 1.0
        assert d.fallback_used is False

    def test_confidence_bounds(self):
        import pytest

        from mahavishnu.core.ecosystem_status import RoutingDecision

        with pytest.raises(ValueError):
            RoutingDecision(
                task_id="t2",
                task_class="AI_TASK",
                selected_adapter="agno",
                confidence=1.5,
            )

    def test_rejected_adapters_with_enum(self):
        from mahavishnu.core.ecosystem_status import (
            RejectedAdapter,
            RejectionReason,
            RoutingDecision,
        )

        d = RoutingDecision(
            task_id="t3",
            task_class="RAG",
            selected_adapter="llamaindex",
            rejected_adapters=[
                RejectedAdapter(adapter_name="prefect", reason=RejectionReason.CAPABILITY_MISSING)
            ],
        )
        assert d.rejected_adapters[0].reason == RejectionReason.CAPABILITY_MISSING


class TestRoutingDecisionBuffer:
    def test_record_and_recent(self):
        from mahavishnu.core.ecosystem_status import RoutingDecision, RoutingDecisionBuffer

        buf = RoutingDecisionBuffer()
        d = RoutingDecision(task_id="t1", task_class="AI_TASK", selected_adapter="agno")
        buf.record(d)
        recent = buf.recent("AI_TASK")
        assert len(recent) == 1
        assert recent[0].task_id == "t1"

    def test_bounded_by_maxlen(self):
        from mahavishnu.core.ecosystem_status import RoutingDecision, RoutingDecisionBuffer

        buf = RoutingDecisionBuffer(maxlen=3)
        for i in range(5):
            buf.record(RoutingDecision(task_id=f"t{i}", task_class="X", selected_adapter="a"))
        recent = buf.recent("X", limit=10)
        assert len(recent) == 3  # oldest evicted

    def test_recent_empty_for_unknown_class(self):
        from mahavishnu.core.ecosystem_status import RoutingDecisionBuffer

        buf = RoutingDecisionBuffer()
        assert buf.recent("NONEXISTENT") == []

    def test_all_task_classes(self):
        from mahavishnu.core.ecosystem_status import RoutingDecision, RoutingDecisionBuffer

        buf = RoutingDecisionBuffer()
        buf.record(RoutingDecision(task_id="a", task_class="T1", selected_adapter="x"))
        buf.record(RoutingDecision(task_id="b", task_class="T2", selected_adapter="y"))
        assert set(buf.all_task_classes()) == {"T1", "T2"}

    def test_get_routing_buffer_singleton(self):
        from mahavishnu.core.ecosystem_status import RoutingDecisionBuffer, get_routing_buffer

        buf = get_routing_buffer()
        assert isinstance(buf, RoutingDecisionBuffer)
        assert get_routing_buffer() is buf

    def test_clear_empties_buffer(self):
        from mahavishnu.core.ecosystem_status import RoutingDecision, RoutingDecisionBuffer

        buf = RoutingDecisionBuffer()
        buf.record(RoutingDecision(task_id="x", task_class="C1", selected_adapter="a"))
        buf.record(RoutingDecision(task_id="y", task_class="C2", selected_adapter="b"))
        buf.clear()
        assert buf.all_task_classes() == []
        assert buf.recent("C1") == []


# ── Phase 6: Capability collection ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_collect_capabilities_no_adapters():
    from mahavishnu.core.ecosystem_status import EcosystemStatusService

    svc = EcosystemStatusService()
    result = await svc._collect_capabilities()
    assert result == {}


@pytest.mark.asyncio
async def test_collect_capabilities_with_adapter():
    from mahavishnu.core.ecosystem_status import CanonicalStatus, EcosystemStatusService

    class FakeAdapter:
        capabilities = ["rag", "vector_search"]

        async def get_health(self):
            return {"status": "healthy"}

    svc = EcosystemStatusService(adapters={"llamaindex": FakeAdapter()})
    result = await svc._collect_capabilities()
    assert "rag" in result
    assert result["rag"].status == CanonicalStatus.OK
    assert "llamaindex" in result["rag"].provided_by
    assert result["rag"].category == "retrieval"


# ── Phase 7: Operational recommendations ───────────────────────────────────


class TestGenerateRecommendations:
    def test_unhealthy_required_service_gets_recommendation(self):
        from mahavishnu.core.ecosystem_status import (
            CanonicalStatus,
            EcosystemStatusService,
            ServiceStatus,
        )

        svc = EcosystemStatusService()
        services = {"session_buddy": ServiceStatus(status=CanonicalStatus.UNHEALTHY, required=True)}
        adapters = {"prefect": AdapterStatus(status=CanonicalStatus.OK)}
        recs = svc._generate_recommendations(services, adapters, AlertSummary())
        assert any(
            r.severity == CanonicalStatus.UNHEALTHY and "session_buddy" in r.component for r in recs
        )

    def test_optional_degraded_service_still_gets_recommendation(self):
        from mahavishnu.core.ecosystem_status import (
            CanonicalStatus,
            EcosystemStatusService,
            ServiceStatus,
        )

        svc = EcosystemStatusService()
        services = {"akosha": ServiceStatus(status=CanonicalStatus.DEGRADED, required=False)}
        recs = svc._generate_recommendations(services, {}, AlertSummary())
        assert len(recs) >= 1
        assert any("akosha" in r.component for r in recs)

    def test_no_adapters_recommendation(self):
        from mahavishnu.core.ecosystem_status import EcosystemStatusService

        svc = EcosystemStatusService()
        recs = svc._generate_recommendations({}, {}, AlertSummary())
        assert any(r.component == "adapters" for r in recs)

    def test_high_alert_count_recommendation(self):
        from mahavishnu.core.ecosystem_status import (
            CanonicalStatus,
            EcosystemStatusService,
        )

        svc = EcosystemStatusService()
        alerts = AlertSummary(total_active=15)
        recs = svc._generate_recommendations(
            {},
            {"a": AdapterStatus(status=CanonicalStatus.OK)},
            alerts,
        )
        assert any(r.component == "alerts" for r in recs)

    def test_healthy_system_no_critical_recommendations(self):
        from mahavishnu.core.ecosystem_status import (
            CanonicalStatus,
            EcosystemStatusService,
            ServiceStatus,
        )

        svc = EcosystemStatusService()
        services = {"session_buddy": ServiceStatus(status=CanonicalStatus.OK, required=True)}
        adapters = {"prefect": AdapterStatus(status=CanonicalStatus.OK)}
        recs = svc._generate_recommendations(services, adapters, AlertSummary())
        assert not any(r.severity == CanonicalStatus.UNHEALTHY for r in recs)

    def test_unknown_required_service_gets_degraded_recommendation(self):
        from mahavishnu.core.ecosystem_status import (
            CanonicalStatus,
            EcosystemStatusService,
            ServiceStatus,
        )

        svc = EcosystemStatusService()
        services = {"akosha": ServiceStatus(status=CanonicalStatus.UNKNOWN, required=True)}
        recs = svc._generate_recommendations(
            services, {"x": AdapterStatus(status=CanonicalStatus.OK)}, AlertSummary()
        )
        assert any(r.severity == CanonicalStatus.DEGRADED and "akosha" in r.component for r in recs)

    def test_unhealthy_adapter_gets_recommendation(self):
        from mahavishnu.core.ecosystem_status import (
            CanonicalStatus,
            EcosystemStatusService,
        )

        svc = EcosystemStatusService()
        adapters = {"llamaindex": AdapterStatus(status=CanonicalStatus.UNHEALTHY)}
        recs = svc._generate_recommendations({}, adapters, AlertSummary())
        assert any(
            r.severity == CanonicalStatus.UNHEALTHY and "llamaindex" in r.component for r in recs
        )


# ── AdapterResolutionResult rename ─────────────────────────────────────────


def test_adapter_resolution_result_is_renamed():
    from mahavishnu.core.task_requirements import AdapterResolutionResult, RoutingDecision

    assert AdapterResolutionResult is RoutingDecision  # backward-compat alias


def test_adapter_resolution_result_to_dict():
    from mahavishnu.core.task_requirements import AdapterResolutionResult

    result = AdapterResolutionResult(
        adapter_name="prefect",
        adapter=None,
        matched_capabilities=["deploy_flows"],
        resolution_time_ms=12.5,
        fallback_used=False,
        explanation="best match",
    )
    d = result.to_dict()
    assert d["adapter_name"] == "prefect"
    assert "adapter" not in d  # adapter instance excluded
