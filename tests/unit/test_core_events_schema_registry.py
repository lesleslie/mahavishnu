"""Unit tests for mahavishnu/core/events/schema_registry.py.

Focuses on the EventSchemaRegistry API: registration, validation, lookup,
version handling, and the SchemaError class.
"""

from __future__ import annotations

import pytest

from mahavishnu.core.errors import ErrorCode
from mahavishnu.core.events.envelope import EventEnvelope
from mahavishnu.core.events.schema_registry import (
    EventSchema,
    EventSchemaRegistry,
    SchemaError,
)

pytestmark = pytest.mark.unit


# ============================== Fixtures ==============================


@pytest.fixture
def registry() -> EventSchemaRegistry:
    """Fresh registry pre-loaded with built-in schemas."""
    return EventSchemaRegistry()


@pytest.fixture
def custom_schema() -> EventSchema:
    """A schema not provided by built-ins."""
    return EventSchema(
        event_type="custom.test.event",
        version="1.0.0",
        required_fields=["foo", "bar"],
        field_types={"foo": "str", "bar": "int"},
        description="A custom test event",
    )


@pytest.fixture
def valid_envelope() -> EventEnvelope:
    """A valid envelope matching a built-in schema."""
    return EventEnvelope(
        event_type="worker.started",
        source="test_runner",
        payload={"worker_id": "w1", "worker_type": "container"},
    )


# ============================== SchemaError ==============================


class TestSchemaError:
    """Tests for SchemaError exception."""

    def test_basic_construction(self):
        err = SchemaError("validation failed")
        assert err.message == "validation failed"
        assert err.error_code == ErrorCode.VALIDATION_ERROR
        assert err.details == {}

    def test_with_details(self):
        err = SchemaError("bad", details={"field": "foo"})
        assert err.details == {"field": "foo"}

    def test_is_an_exception(self):
        err = SchemaError("x")
        assert isinstance(err, Exception)


# ============================== EventSchema ==============================


class TestEventSchema:
    """Tests for the EventSchema Pydantic model."""

    def test_minimal_schema(self):
        s = EventSchema(event_type="some.event")
        assert s.event_type == "some.event"
        assert s.version == "1.0.0"
        assert s.required_fields == []
        assert s.field_types == {}
        assert s.description == ""

    def test_full_schema(self, custom_schema: EventSchema):
        assert custom_schema.event_type == "custom.test.event"
        assert custom_schema.required_fields == ["foo", "bar"]
        assert custom_schema.field_types == {"foo": "str", "bar": "int"}

    def test_empty_event_type_invalid(self):
        with pytest.raises(Exception):  # Pydantic ValidationError
            EventSchema(event_type="")

    def test_invalid_version_invalid(self):
        with pytest.raises(ValueError, match="Invalid version format"):
            EventSchema(event_type="ok", version="not-semver")


# ============================== Built-in schema registration ==============================


class TestBuiltinSchemas:
    """The registry should pre-load Mahavishnu built-in schemas."""

    def test_code_graph_indexed_registered(self, registry: EventSchemaRegistry):
        assert registry.is_registered("code.graph.indexed")

    def test_worker_started_registered(self, registry: EventSchemaRegistry):
        assert registry.is_registered("worker.started")

    def test_worker_stopped_registered(self, registry: EventSchemaRegistry):
        assert registry.is_registered("worker.stopped")

    def test_backup_started_registered(self, registry: EventSchemaRegistry):
        assert registry.is_registered("backup.started")

    def test_pool_spawned_registered(self, registry: EventSchemaRegistry):
        assert registry.is_registered("pool.spawned")

    def test_workflow_started_registered(self, registry: EventSchemaRegistry):
        assert registry.is_registered("workflow.started")

    def test_task_created_registered(self, registry: EventSchemaRegistry):
        assert registry.is_registered("task.created")

    def test_list_schemas_returns_all(self, registry: EventSchemaRegistry):
        all_schemas = registry.list_schemas()
        assert len(all_schemas) >= 13  # built-in count
        types = {s.event_type for s in all_schemas}
        assert "worker.started" in types
        assert "pool.scaled" in types


# ============================== register / duplicate detection ==============================


class TestRegister:
    """register() add / duplicate behavior."""

    def test_register_new_schema(self, registry: EventSchemaRegistry, custom_schema: EventSchema):
        registry.register(custom_schema)
        assert registry.is_registered("custom.test.event")

    def test_register_duplicate_raises(
        self, registry: EventSchemaRegistry, custom_schema: EventSchema
    ):
        registry.register(custom_schema)
        with pytest.raises(ValueError, match="already registered"):
            registry.register(custom_schema)

    def test_register_different_versions(self, registry: EventSchemaRegistry):
        s1 = EventSchema(event_type="x.y", version="1.0.0")
        s2 = EventSchema(event_type="x.y", version="2.0.0")
        registry.register(s1)
        registry.register(s2)  # different version → allowed
        assert registry.is_registered("x.y", "1.0.0")
        assert registry.is_registered("x.y", "2.0.0")


# ============================== get_schema ==============================


class TestGetSchema:
    """Get schema by event type + version."""

    def test_get_existing_schema(self, registry: EventSchemaRegistry):
        s = registry.get_schema("worker.started", "1.0.0")
        assert s is not None
        assert s.event_type == "worker.started"

    def test_get_missing_returns_none(self, registry: EventSchemaRegistry):
        assert registry.get_schema("nonexistent.event") is None

    def test_get_default_version(self, registry: EventSchemaRegistry):
        s = registry.get_schema("worker.started")  # default version 1.0.0
        assert s is not None


# ============================== is_registered ==============================


class TestIsRegistered:
    """is_registered semantics."""

    def test_unknown_returns_false(self, registry: EventSchemaRegistry):
        assert registry.is_registered("never.registered") is False

    def test_known_returns_true(self, registry: EventSchemaRegistry):
        assert registry.is_registered("worker.started", "1.0.0") is True

    def test_wrong_version_returns_false(self, registry: EventSchemaRegistry):
        assert registry.is_registered("worker.started", "99.0.0") is False


# ============================== validate ==============================


class TestValidate:
    """Validation of EventEnvelope payloads."""

    def test_valid_envelope_no_errors(
        self, registry: EventSchemaRegistry, valid_envelope: EventEnvelope
    ):
        errors = registry.validate(valid_envelope)
        assert errors == []

    def test_unknown_event_type_reports_error(self, registry: EventSchemaRegistry):
        env = EventEnvelope(
            event_type="totally.unknown.event",
            source="test",
            payload={},
        )
        errors = registry.validate(env)
        assert any("No schema registered" in e for e in errors)

    def test_missing_required_field(self, registry: EventSchemaRegistry):
        env = EventEnvelope(
            event_type="worker.started",
            source="test",
            payload={"worker_id": "w1"},  # missing worker_type
        )
        errors = registry.validate(env)
        assert any("worker_type" in e for e in errors)

    def test_wrong_field_type(self, registry: EventSchemaRegistry):
        env = EventEnvelope(
            event_type="worker.started",
            source="test",
            payload={"worker_id": 123, "worker_type": "container"},  # worker_id wrong
        )
        errors = registry.validate(env)
        assert any("expected str" in e for e in errors)

    def test_validate_with_custom_schema(
        self, registry: EventSchemaRegistry, custom_schema: EventSchema
    ):
        registry.register(custom_schema)
        env = EventEnvelope(
            event_type="custom.test.event",
            source="t",
            payload={"foo": "ok", "bar": 42},
        )
        assert registry.validate(env) == []

    def test_validate_custom_schema_missing_fields(
        self, registry: EventSchemaRegistry, custom_schema: EventSchema
    ):
        registry.register(custom_schema)
        env = EventEnvelope(
            event_type="custom.test.event",
            source="t",
            payload={"foo": "ok"},
        )
        errors = registry.validate(env)
        assert any("bar" in e for e in errors)

    def test_version_mismatch_reports_error(self, registry: EventSchemaRegistry):
        # Register only 1.0.0; envelope claims 2.0.0 → version mismatch path
        s = EventSchema(event_type="mismatch.evt", version="1.0.0")
        registry.register(s)
        env = EventEnvelope(
            event_type="mismatch.evt",
            version="2.0.0",
            source="t",
            payload={},
        )
        errors = registry.validate(env)
        assert any("Version mismatch" in e for e in errors)

    def test_compatible_version_no_mismatch(self, registry: EventSchemaRegistry):
        # Same major, lower minor on registered → backward compatible
        s = EventSchema(event_type="compat.evt", version="1.5.0")
        registry.register(s)
        env = EventEnvelope(
            event_type="compat.evt",
            version="1.2.0",
            source="t",
            payload={},
        )
        errors = registry.validate(env)
        # No version mismatch (registered 1.5.0 is compatible with consumer 1.2.0)
        assert not any("Version mismatch" in e for e in errors)


# ============================== _schema_key helper ==============================


class TestSchemaKey:
    """The private _schema_key helper."""

    def test_key_format(self):
        key = EventSchemaRegistry._schema_key("a.b", "1.2.3")
        assert key == "a.b:1.2.3"
