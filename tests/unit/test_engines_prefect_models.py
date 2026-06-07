"""Unit tests for Prefect Pydantic response models.

Covers ``mahavishnu.engines.prefect_models`` which defines the
``DeploymentResponse``, ``FlowRunResponse``, ``ScheduleResponse``,
``WorkPoolResponse``, and ``LogEntry`` Pydantic models used to wrap
Prefect API responses in a type-safe way.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import ValidationError
import pytest

from mahavishnu.engines.prefect_models import (
    DeploymentResponse,
    FlowRunResponse,
    LogEntry,
    ScheduleResponse,
    WorkPoolResponse,
)

pytestmark = pytest.mark.unit


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def fixed_now() -> datetime:
    """Return a fixed, tz-aware UTC timestamp for deterministic tests."""
    return datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def minimal_deployment(fixed_now: datetime) -> dict:
    """Minimal valid kwargs for ``DeploymentResponse``."""
    return {
        "id": "dep-1",
        "name": "prod-deployment",
        "flow_name": "etl-flow",
        "flow_id": "flow-1",
        "created_at": fixed_now,
    }


@pytest.fixture
def minimal_flow_run(fixed_now: datetime) -> dict:
    """Minimal valid kwargs for ``FlowRunResponse``."""
    return {
        "id": "run-1",
        "name": "run-name",
        "flow_id": "flow-1",
        "state_type": "COMPLETED",
        "state_name": "Completed",
        "created_at": fixed_now,
    }


@pytest.fixture
def minimal_schedule(fixed_now: datetime) -> dict:
    """Minimal valid kwargs for ``ScheduleResponse``."""
    return {
        "id": "sched-1",
        "deployment_id": "dep-1",
        "schedule": {"cron": "0 9 * * *"},
        "active": True,
        "created_at": fixed_now,
    }


@pytest.fixture
def minimal_work_pool(fixed_now: datetime) -> dict:
    """Minimal valid kwargs for ``WorkPoolResponse``."""
    return {
        "name": "default-pool",
        "type": "process",
        "created_at": fixed_now,
    }


@pytest.fixture
def minimal_log(fixed_now: datetime) -> dict:
    """Minimal valid kwargs for ``LogEntry``."""
    return {
        "timestamp": fixed_now,
        "level": "INFO",
        "message": "started",
        "flow_run_id": "run-1",
    }


# =============================================================================
# DeploymentResponse
# =============================================================================


class TestDeploymentResponse:
    """Behaviour of the ``DeploymentResponse`` Pydantic model."""

    def test_minimal_construction_uses_defaults(self, minimal_deployment: dict) -> None:
        dep = DeploymentResponse(**minimal_deployment)
        assert dep.id == "dep-1"
        assert dep.name == "prod-deployment"
        assert dep.flow_name == "etl-flow"
        assert dep.flow_id == "flow-1"
        # Defaulted fields
        assert dep.schedule is None
        assert dep.parameters == {}
        assert dep.work_pool_name is None
        assert dep.work_queue_name is None
        assert dep.paused is False
        assert dep.tags == []
        assert dep.description is None
        assert dep.version is None
        assert dep.updated_at is None

    def test_full_construction_preserves_all_fields(self, minimal_deployment: dict) -> None:
        dep = DeploymentResponse(
            **minimal_deployment,
            schedule={"cron": "*/5 * * * *"},
            parameters={"env": "prod"},
            work_pool_name="default",
            work_queue_name="default",
            paused=True,
            tags=["etl", "prod"],
            description="Nightly ETL",
            version="1.2.3",
            updated_at=datetime(2026, 1, 2, tzinfo=UTC),
        )
        assert dep.schedule == {"cron": "*/5 * * * *"}
        assert dep.parameters == {"env": "prod"}
        assert dep.work_pool_name == "default"
        assert dep.work_queue_name == "default"
        assert dep.paused is True
        assert dep.tags == ["etl", "prod"]
        assert dep.description == "Nightly ETL"
        assert dep.version == "1.2.3"
        assert dep.updated_at == datetime(2026, 1, 2, tzinfo=UTC)

    def test_default_factory_does_not_share_state(self) -> None:
        """Each model instance must own its own list/dict defaults."""
        dep_a = DeploymentResponse(
            id="1",
            name="a",
            flow_name="a",
            flow_id="1",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            tags=["a"],
        )
        dep_b = DeploymentResponse(
            id="2",
            name="b",
            flow_name="b",
            flow_id="2",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        dep_a.tags.append("shared-mutation")
        assert dep_b.tags == []

    def test_missing_required_field_raises(self, minimal_deployment: dict) -> None:
        del minimal_deployment["name"]
        with pytest.raises(ValidationError) as exc_info:
            DeploymentResponse(**minimal_deployment)
        # Pydantic reports the missing field
        assert "name" in str(exc_info.value)

    def test_missing_created_at_raises(self, minimal_deployment: dict) -> None:
        del minimal_deployment["created_at"]
        with pytest.raises(ValidationError) as exc_info:
            DeploymentResponse(**minimal_deployment)
        assert "created_at" in str(exc_info.value)

    def test_serialization_roundtrip(self, minimal_deployment: dict) -> None:
        dep = DeploymentResponse(
            **minimal_deployment,
            schedule={"cron": "0 * * * *"},
            parameters={"x": 1},
            work_pool_name="p1",
            paused=True,
            tags=["t1"],
            version="v1",
            updated_at=datetime(2026, 6, 1, tzinfo=UTC),
        )
        dumped = dep.model_dump()
        restored = DeploymentResponse(**dumped)
        assert restored == dep

    def test_parameters_default_is_independent_dict(self, minimal_deployment: dict) -> None:
        dep = DeploymentResponse(**minimal_deployment)
        dep.parameters["mutated"] = True
        other = DeploymentResponse(**minimal_deployment)
        assert "mutated" not in other.parameters


# =============================================================================
# FlowRunResponse
# =============================================================================


class TestFlowRunResponse:
    """Behaviour of the ``FlowRunResponse`` Pydantic model."""

    def test_minimal_construction_uses_defaults(self, minimal_flow_run: dict) -> None:
        run = FlowRunResponse(**minimal_flow_run)
        assert run.id == "run-1"
        assert run.name == "run-name"
        assert run.flow_id == "flow-1"
        assert run.state_type == "COMPLETED"
        assert run.state_name == "Completed"
        # Defaulted fields
        assert run.deployment_id is None
        assert run.parameters == {}
        assert run.tags == []
        assert run.updated_at is None
        assert run.start_time is None
        assert run.end_time is None
        assert run.total_run_time_seconds is None
        assert run.estimated_run_time_seconds is None
        assert run.work_queue_name is None

    def test_full_construction_preserves_all_fields(self, minimal_flow_run: dict) -> None:
        started = datetime(2026, 1, 1, 12, 1, 0, tzinfo=UTC)
        ended = datetime(2026, 1, 1, 12, 5, 0, tzinfo=UTC)
        run = FlowRunResponse(
            **minimal_flow_run,
            deployment_id="dep-1",
            parameters={"x": 1, "y": "z"},
            tags=["prod"],
            updated_at=ended,
            start_time=started,
            end_time=ended,
            total_run_time_seconds=240.0,
            estimated_run_time_seconds=300.0,
            work_queue_name="default",
        )
        assert run.deployment_id == "dep-1"
        assert run.parameters == {"x": 1, "y": "z"}
        assert run.tags == ["prod"]
        assert run.start_time == started
        assert run.end_time == ended
        assert run.total_run_time_seconds == 240.0
        assert run.estimated_run_time_seconds == 300.0
        assert run.work_queue_name == "default"

    def test_state_type_is_freeform_string(self, minimal_flow_run: dict) -> None:
        """``state_type`` should accept any string (Prefect-defined values)."""
        for state in ("PENDING", "RUNNING", "COMPLETED", "FAILED", "CANCELLED"):
            run = FlowRunResponse(
                **{**minimal_flow_run, "state_type": state, "state_name": state.title()}
            )
            assert run.state_type == state

    def test_missing_state_type_raises(self, minimal_flow_run: dict) -> None:
        del minimal_flow_run["state_type"]
        with pytest.raises(ValidationError) as exc_info:
            FlowRunResponse(**minimal_flow_run)
        assert "state_type" in str(exc_info.value)

    def test_serialization_roundtrip(self, minimal_flow_run: dict) -> None:
        run = FlowRunResponse(
            **minimal_flow_run,
            parameters={"a": 1},
            tags=["t"],
            total_run_time_seconds=1.5,
        )
        restored = FlowRunResponse(**run.model_dump())
        assert restored == run


# =============================================================================
# ScheduleResponse
# =============================================================================


class TestScheduleResponse:
    """Behaviour of the ``ScheduleResponse`` Pydantic model."""

    def test_minimal_construction(self, minimal_schedule: dict) -> None:
        sched = ScheduleResponse(**minimal_schedule)
        assert sched.id == "sched-1"
        assert sched.deployment_id == "dep-1"
        assert sched.schedule == {"cron": "0 9 * * *"}
        assert sched.active is True
        assert sched.created_at == datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        assert sched.updated_at is None

    def test_schedule_dict_accepts_arbitrary_keys(self, minimal_schedule: dict) -> None:
        sched = ScheduleResponse(
            **{
                **minimal_schedule,
                "schedule": {"interval": 3600, "timezone": "UTC", "anchor_date": "2026-01-01"},
            }
        )
        assert sched.schedule["interval"] == 3600
        assert sched.schedule["timezone"] == "UTC"

    def test_inactive_schedule_preserved(self, minimal_schedule: dict) -> None:
        sched = ScheduleResponse(**{**minimal_schedule, "active": False})
        assert sched.active is False

    def test_missing_schedule_field_raises(self, minimal_schedule: dict) -> None:
        del minimal_schedule["schedule"]
        with pytest.raises(ValidationError) as exc_info:
            ScheduleResponse(**minimal_schedule)
        assert "schedule" in str(exc_info.value)

    def test_serialization_roundtrip(self, minimal_schedule: dict) -> None:
        sched = ScheduleResponse(
            **minimal_schedule,
            updated_at=datetime(2026, 6, 1, tzinfo=UTC),
        )
        restored = ScheduleResponse(**sched.model_dump())
        assert restored == sched


# =============================================================================
# WorkPoolResponse
# =============================================================================


class TestWorkPoolResponse:
    """Behaviour of the ``WorkPoolResponse`` Pydantic model."""

    def test_minimal_construction_uses_defaults(self, minimal_work_pool: dict) -> None:
        pool = WorkPoolResponse(**minimal_work_pool)
        assert pool.name == "default-pool"
        assert pool.type == "process"
        assert pool.description is None
        assert pool.is_paused is False
        assert pool.concurrency_limit is None
        assert pool.updated_at is None

    def test_full_construction(self, minimal_work_pool: dict) -> None:
        pool = WorkPoolResponse(
            **minimal_work_pool,
            description="Main pool",
            is_paused=True,
            concurrency_limit=10,
            updated_at=datetime(2026, 1, 2, tzinfo=UTC),
        )
        assert pool.description == "Main pool"
        assert pool.is_paused is True
        assert pool.concurrency_limit == 10
        assert pool.updated_at == datetime(2026, 1, 2, tzinfo=UTC)

    def test_concurrency_limit_zero_allowed(self, minimal_work_pool: dict) -> None:
        pool = WorkPoolResponse(**{**minimal_work_pool, "concurrency_limit": 0})
        assert pool.concurrency_limit == 0

    def test_missing_name_raises(self, minimal_work_pool: dict) -> None:
        del minimal_work_pool["name"]
        with pytest.raises(ValidationError) as exc_info:
            WorkPoolResponse(**minimal_work_pool)
        assert "name" in str(exc_info.value)

    def test_serialization_roundtrip(self, minimal_work_pool: dict) -> None:
        pool = WorkPoolResponse(
            **minimal_work_pool,
            description="d",
            is_paused=True,
            concurrency_limit=5,
        )
        restored = WorkPoolResponse(**pool.model_dump())
        assert restored == pool


# =============================================================================
# LogEntry
# =============================================================================


class TestLogEntry:
    """Behaviour of the ``LogEntry`` Pydantic model."""

    def test_minimal_construction(self, minimal_log: dict) -> None:
        log = LogEntry(**minimal_log)
        assert log.timestamp == datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        assert log.level == "INFO"
        assert log.message == "started"
        assert log.flow_run_id == "run-1"
        assert log.task_run_id is None

    def test_with_task_run_id(self, minimal_log: dict) -> None:
        log = LogEntry(
            **{
                **minimal_log,
                "task_run_id": "task-1",
                "level": "ERROR",
                "message": "boom",
            }
        )
        assert log.task_run_id == "task-1"
        assert log.level == "ERROR"
        assert log.message == "boom"

    def test_level_accepts_arbitrary_string(self, minimal_log: dict) -> None:
        """Log level is a free-form string in the model."""
        for level in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
            log = LogEntry(**{**minimal_log, "level": level})
            assert log.level == level

    def test_missing_message_raises(self, minimal_log: dict) -> None:
        del minimal_log["message"]
        with pytest.raises(ValidationError) as exc_info:
            LogEntry(**minimal_log)
        assert "message" in str(exc_info.value)

    def test_serialization_roundtrip(self, minimal_log: dict) -> None:
        log = LogEntry(**{**minimal_log, "task_run_id": "t1"})
        restored = LogEntry(**log.model_dump())
        assert restored == log

    def test_datetime_serialization_isoformat(self, minimal_log: dict) -> None:
        log = LogEntry(**minimal_log)
        # Pydantic v2 model_dump produces datetime objects by default
        # JSON roundtrip should yield ISO strings
        json_payload = log.model_dump_json()
        assert "2026-01-01" in json_payload


# =============================================================================
# Cross-model behaviour
# =============================================================================


class TestModelExports:
    """Validate the module's public exports."""

    def test_all_models_importable(self) -> None:
        from mahavishnu.engines import prefect_models

        for name in (
            "DeploymentResponse",
            "FlowRunResponse",
            "ScheduleResponse",
            "WorkPoolResponse",
            "LogEntry",
        ):
            assert name in prefect_models.__all__
            assert hasattr(prefect_models, name)

    def test_models_allow_extra_fields_by_default(self, minimal_log: dict) -> None:
        """Pydantic v2 default is to ignore extras; ensure no surprise error."""
        log = LogEntry(**{**minimal_log, "unknown_field": "ignored"})
        assert log.message == "started"
