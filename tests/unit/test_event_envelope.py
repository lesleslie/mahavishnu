"""Tests for EventEnvelope, EventVersion, schema registry, and compatibility policy.

Covers:
- EventEnvelope creation and serialization
- EventVersion parsing and comparison
- Schema registration and validation
- Compatibility policy checking
- Legacy event migration
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import ValidationError
import pytest

from mahavishnu.core.events.compatibility import (
    CompatibilityLevel,
    CompatibilityPolicy,
)
from mahavishnu.core.events.envelope import EventEnvelope, EventVersion
from mahavishnu.core.events.migration import (
    migrate_legacy_event_bus_event,
    migrate_legacy_task_event,
    migrate_legacy_webhook_event,
)
from mahavishnu.core.events.schema_registry import (
    EventSchema,
    EventSchemaRegistry,
)

# =============================================================================
# EventVersion Tests
# =================================================================


class TestEventVersion:
    """Test EventVersion parsing and comparison."""

    def test_parse_valid_version(self):
        v = EventVersion("1.0.0")
        assert v.major == 1
        assert v.minor == 0
        assert v.patch == 0
        assert str(v) == "1.0.0"

    def test_parse_rejects_invalid_format(self):
        with pytest.raises(ValueError, match="Invalid version format"):
            EventVersion("1.0")
        with pytest.raises(ValueError, match="Invalid version format"):
            EventVersion("1.0.0.0")
        with pytest.raises(ValueError, match="Invalid version format"):
            EventVersion("not_a_version")

    def test_equality_and_hashing(self):
        v1 = EventVersion("1.0.0")
        v2 = EventVersion("1.0.0")
        v3 = EventVersion("1.0.1")
        assert v1 == v2
        assert v1 != v3
        assert hash(v1) == hash(v2)
        assert hash(v1) != hash(v3)

    def test_ordering(self):
        versions = [
            EventVersion("1.0.0"),
            EventVersion("1.0.1"),
            EventVersion("1.1.0"),
            EventVersion("2.0.0"),
        ]
        assert sorted(versions) == versions
        assert EventVersion("1.0.0") < EventVersion("1.0.1")
        assert EventVersion("1.0.1") < EventVersion("1.1.0")

    def test_compatibility_same_major(self):
        v = EventVersion("1.0.0")
        # Producer 1.0.0 is compatible with consumer expecting 1.0.5 (consumer has higher minor, but
        # same major — consumer accepts any 1.x). Actually is_compatible_with checks
        # self.minor >= other.minor, so producer 1.0.0 IS compatible with consumer 1.0.0 only.
        assert v.is_compatible_with(EventVersion("1.0.0"))
        # Producer 1.1.0 is compatible with consumer 1.0.0 (producer has higher minor)
        assert EventVersion("1.1.0").is_compatible_with(EventVersion("1.0.0"))
        # Different major is never compatible
        assert not v.is_compatible_with(EventVersion("2.0.0"))

    def test_compatibility_higher_minor(self):
        # Producer v1.2.0 is compatible with consumer v1.0.0 (producer minor >= consumer minor)
        assert EventVersion("1.2.0").is_compatible_with(EventVersion("1.0.0"))
        # Producer v1.0.0 is NOT compatible with consumer v1.2.0 (producer minor < consumer minor)
        assert not EventVersion("1.0.0").is_compatible_with(EventVersion("1.2.0"))

    def test_bump_patch(self):
        bumped = EventVersion("1.0.5").bump_patch()
        assert bumped == EventVersion("1.0.6")

    def test_bump_minor(self):
        bumped = EventVersion("1.2.3").bump_minor()
        assert bumped == EventVersion("1.3.0")

    def test_bump_major(self):
        bumped = EventVersion("1.2.3").bump_major()
        assert bumped == EventVersion("2.0.0")

    def test_parse_factory(self):
        v = EventVersion.parse("3.14.2")
        assert v.major == 3
        assert v.minor == 14
        assert v.patch == 2


# =============================================================================
# EventEnvelope Tests
# =================================================================


class TestEventEnvelope:
    """Test EventEnvelope creation and serialization."""

    def test_create_minimal_envelope(self):
        envelope = EventEnvelope(
            event_type="test.event",
            source="test_service",
        )
        assert isinstance(envelope.event_id, UUID)
        assert envelope.version == "1.0.0"
        assert isinstance(envelope.timestamp, datetime)
        assert envelope.source == "test_service"
        assert envelope.payload == {}
        assert envelope.correlation_id is None

    def test_create_full_envelope(self):
        corr_id = UUID("12345678-1234-1234-1234-123456789012")
        causation_id = UUID("87654321-4321-4321-4321-210987654321")
        envelope = EventEnvelope(
            event_type="code.graph.indexed",
            version="1.2.0",
            source="code_index_service",
            correlation_id=corr_id,
            causation_id=causation_id,
            payload={"repo": "/path/to/repo", "stats": {"files": 42}},
            metadata={"trace_id": "abc-123"},
        )
        assert envelope.correlation_id == corr_id
        assert envelope.causation_id == causation_id
        assert envelope.payload["repo"] == "/path/to/repo"
        assert envelope.metadata["trace_id"] == "abc-123"
        assert envelope.version == "1.2.0"

    def test_version_validation(self):
        # Valid versions
        EventEnvelope(event_type="test", source="s", version="1.0.0")
        EventEnvelope(event_type="test", source="s", version="2.14.3")
        # Invalid versions
        with pytest.raises(ValueError):
            EventEnvelope(event_type="test", source="s", version="not_a_version")
        with pytest.raises(ValueError):
            EventEnvelope(event_type="test", source="s", version="1.0")

    def test_event_type_validation(self):
        with pytest.raises(ValidationError):
            EventEnvelope(event_type="", source="s")
        with pytest.raises(ValidationError):
            EventEnvelope(event_type="   ", source="s")

    def test_to_dict_and_from_dict_roundtrip(self):
        corr_id = UUID("12345678-1234-1234-1234-123456789012")
        causation_id = UUID("87654321-4321-4321-4321-210987654321")
        original = EventEnvelope(
            event_type="code.graph.indexed",
            version="1.2.0",
            source="code_index_service",
            correlation_id=corr_id,
            causation_id=causation_id,
            payload={"repo": "/path", "files": 42},
            metadata={"trace": "abc"},
        )
        d = original.to_dict()
        assert isinstance(d["event_id"], str)
        assert isinstance(d["timestamp"], str)
        assert d["event_type"] == "code.graph.indexed"
        assert d["correlation_id"] == str(corr_id)
        assert d["causation_id"] == str(causation_id)
        restored = EventEnvelope.from_dict(d)
        assert restored.event_id == original.event_id
        assert restored.event_type == original.event_type
        assert restored.version == original.version
        assert restored.source == original.source
        assert restored.correlation_id == original.correlation_id
        assert restored.causation_id == original.causation_id
        assert restored.payload == original.payload
        assert restored.metadata == original.metadata

    def test_to_json_and_from_json_roundtrip(self):
        envelope = EventEnvelope(
            event_type="test.event",
            source="test_service",
            payload={"key": "value"},
        )
        json_str = envelope.to_json()
        deserialized = EventEnvelope.from_json(json_str)
        assert deserialized.event_id == envelope.event_id
        assert deserialized.payload == envelope.payload

    def test_canonical_json_ordering(self):
        """Verify JSON has deterministic key ordering."""
        import json

        envelope = EventEnvelope(
            event_type="test.event",
            source="test_service",
        )
        parsed = json.loads(envelope.to_json())
        keys = list(parsed.keys())
        assert keys == sorted(keys)

    def test_correlation_id_none_serialization(self):
        """Verify None correlation_id serializes correctly."""
        envelope = EventEnvelope(event_type="test", source="s")
        d = envelope.to_dict()
        assert d["correlation_id"] is None

    def test_from_dict_legacy_missing_all_optional_fields(self):
        """from_dict fills in version, correlation_id, metadata, event_id when absent."""
        from mahavishnu.core.events.envelope import EventEnvelope

        data = {
            "event_type": "test.legacy",
            "source": "legacy_service",
            "timestamp": "2024-01-01T00:00:00",
        }
        env = EventEnvelope.from_dict(data)
        assert env.event_type == "test.legacy"
        assert env.version is not None
        assert env.correlation_id is None
        assert env.metadata == {}
        assert env.event_id is not None

    def test_event_version_eq_with_non_version(self):
        """__eq__ returns NotImplemented for non-EventVersion types."""
        from mahavishnu.core.events.envelope import EventVersion

        v = EventVersion("1.0.0")
        result = v.__eq__(42)
        assert result is NotImplemented

    def test_event_version_lt_with_non_version(self):
        """__lt__ returns NotImplemented for non-EventVersion types."""
        from mahavishnu.core.events.envelope import EventVersion

        v = EventVersion("1.0.0")
        result = v.__lt__(42)  # type: ignore[arg-type]
        assert result is NotImplemented


# =============================================================================
# Schema Registry Tests
# =================================================================


class TestEventSchema:
    """Test EventSchema model."""

    def test_create_schema(self):
        schema = EventSchema(
            event_type="code.graph.indexed",
            version="1.0.0",
            required_fields=["repo"],
            field_types={"repo": "str", "stats": "dict"},
            description="Code graph indexing event",
        )
        assert schema.event_type == "code.graph.indexed"
        assert schema.version == "1.0.0"
        assert schema.required_fields == ["repo"]
        assert schema.field_types == {"repo": "str", "stats": "dict"}

    def test_schema_invalid_version(self):
        with pytest.raises(ValueError):
            EventSchema(event_type="test", version="invalid")


class TestEventSchemaRegistry:
    """Test EventSchemaRegistry registration and validation."""

    def test_register_schema(self):
        registry = EventSchemaRegistry()
        schema = EventSchema(
            event_type="custom.test_event",
            version="1.0.0",
            required_fields=["test_id"],
            field_types={"test_id": "str"},
        )
        registry.register(schema)
        assert registry.is_registered("custom.test_event", "1.0.0")

    def test_register_duplicate_schema_raises(self):
        registry = EventSchemaRegistry()
        schema = EventSchema(event_type="test.event", version="1.0.0")
        registry.register(schema)
        with pytest.raises(ValueError, match="Schema already registered"):
            registry.register(schema)

    def test_validate_valid_event(self):
        registry = EventSchemaRegistry()
        schema = EventSchema(
            event_type="test.event",
            version="1.0.0",
            required_fields=["task_id"],
            field_types={"task_id": "str"},
        )
        registry.register(schema)
        envelope = EventEnvelope(
            event_type="test.event",
            version="1.0.0",
            source="test",
            payload={"task_id": "abc-123"},
        )
        errors = registry.validate(envelope)
        assert errors == []

    def test_validate_missing_required_field(self):
        registry = EventSchemaRegistry()
        schema = EventSchema(
            event_type="test.event",
            version="1.0.0",
            required_fields=["task_id", "status"],
        )
        registry.register(schema)
        envelope = EventEnvelope(
            event_type="test.event",
            version="1.0.0",
            source="test",
            payload={"task_id": "abc-123"},
        )
        errors = registry.validate(envelope)
        assert len(errors) == 1
        assert "status" in errors[0]
        assert "Missing required field" in errors[0]

    def test_validate_wrong_field_type(self):
        registry = EventSchemaRegistry()
        schema = EventSchema(
            event_type="test.event",
            version="1.0.0",
            required_fields=["count"],
            field_types={"count": "int"},
        )
        registry.register(schema)
        envelope = EventEnvelope(
            event_type="test.event",
            version="1.0.0",
            source="test",
            payload={"count": "not_an_int"},
        )
        errors = registry.validate(envelope)
        assert len(errors) == 1
        assert "expected int" in errors[0]

    def test_validate_unregistered_event_type(self):
        registry = EventSchemaRegistry()
        envelope = EventEnvelope(
            event_type="unknown.event",
            version="1.0.0",
            source="test",
        )
        errors = registry.validate(envelope)
        assert len(errors) == 1
        assert "No schema registered" in errors[0]

    def test_builtin_schemas_registered(self):
        registry = EventSchemaRegistry()
        assert registry.is_registered("code.graph.indexed", "1.0.0")
        assert registry.is_registered("worker.started", "1.0.0")
        assert registry.is_registered("workflow.started", "1.0.0")
        assert registry.is_registered("pool.spawned", "1.0.0")
        assert registry.is_registered("backup.started", "1.0.0")
        assert registry.is_registered("task.created", "1.0.0")


# =============================================================================
# Compatibility Policy Tests
# =================================================================


class TestCompatibilityPolicy:
    """Test CompatibilityPolicy version checking."""

    def test_compatible_same_version(self):
        result = CompatibilityPolicy.check_compatibility(
            producer_version=EventVersion("1.0.0"),
            consumer_version=EventVersion("1.0.0"),
        )
        assert result == CompatibilityLevel.PATCH

    def test_compatible_minor_bump(self):
        result = CompatibilityPolicy.check_compatibility(
            producer_version=EventVersion("1.1.0"),
            consumer_version=EventVersion("1.0.0"),
        )
        assert result == CompatibilityLevel.MINOR

    def test_breaking_major_change(self):
        result = CompatibilityPolicy.check_compatibility(
            producer_version=EventVersion("2.0.0"),
            consumer_version=EventVersion("1.0.0"),
        )
        assert result == CompatibilityLevel.MAJOR

    def test_is_breaking_change(self):
        assert CompatibilityPolicy.is_breaking_change(EventVersion("1.0.0"), EventVersion("2.0.0"))
        assert not CompatibilityPolicy.is_breaking_change(
            EventVersion("1.0.0"), EventVersion("1.0.1")
        )
        assert not CompatibilityPolicy.is_breaking_change(
            EventVersion("1.0.0"), EventVersion("1.1.0")
        )

    def test_validate_version_transition_valid(self):
        errors = CompatibilityPolicy.validate_version_transition(
            old_version=EventVersion("1.0.0"),
            new_version=EventVersion("1.0.1"),
        )
        assert errors == []

    def test_validate_downgrade_rejected(self):
        errors = CompatibilityPolicy.validate_version_transition(
            old_version=EventVersion("1.0.1"),
            new_version=EventVersion("1.0.0"),
        )
        assert len(errors) > 0
        assert any("downgrade" in e.lower() for e in errors)

    def test_validate_breaking_transition(self):
        errors = CompatibilityPolicy.validate_version_transition(
            old_version=EventVersion("1.0.0"),
            new_version=EventVersion("2.0.0"),
        )
        assert len(errors) > 0
        assert any("Breaking change" in e for e in errors)

    def test_policy_summary(self):
        summary = CompatibilityPolicy.get_policy_summary()
        assert "current_version" in summary
        assert "rules" in summary
        assert summary["current_version"] == "1.0.0"


# =============================================================================
# Legacy Migration Tests
# =================================================================


class TestLegacyMigration:
    """Test migration from legacy event formats."""

    def test_migrate_event_bus_event(self):
        legacy = {
            "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            "type": "code.graph.indexed",
            "data": {"repo": "/path/to/repo", "files": 42},
            "timestamp": "2026-04-05T12:00:00+00:00",
            "source": "code_index_service",
            "version": 1,
        }
        envelope = migrate_legacy_event_bus_event(legacy)
        assert isinstance(envelope, EventEnvelope)
        assert envelope.event_type == "code.graph.indexed"
        assert envelope.version == "1.0.0"
        assert envelope.source == "code_index_service"
        assert envelope.payload["repo"] == "/path/to/repo"
        assert envelope.payload["files"] == 42
        assert envelope.metadata["migrated_from"] == "event_bus_v1"

    def test_migrate_task_event(self):
        legacy = {
            "event_type": "created",
            "task_id": "task-123",
            "data": {"title": "Test task"},
            "timestamp": "2026-04-05T12:00:00+00:00",
            "metadata": {"priority": "high"},
        }
        envelope = migrate_legacy_task_event(legacy)
        assert isinstance(envelope, EventEnvelope)
        assert envelope.event_type == "task.created"
        assert envelope.source == "task_notifications"
        assert envelope.payload["task_id"] == "task-123"
        assert envelope.payload["title"] == "Test task"
        assert envelope.metadata["migrated_from"] == "task_event_v1"
        assert envelope.metadata["priority"] == "high"

    def test_migrate_webhook_event(self):
        legacy = {
            "event_id": "c3d4e5f6-a7b8-9012-cdef-123456789012",
            "source": "github",
            "event_type": "push",
            "repository": "lesleslie/mahavishnu",
            "received_at": "2026-04-05T12:00:00+00:00",
            "sender": "lesleslie",
        }
        envelope = migrate_legacy_webhook_event(legacy)
        assert isinstance(envelope, EventEnvelope)
        assert envelope.event_type == "webhook.push"
        assert envelope.source == "webhook.github"
        assert envelope.version == "1.0.0"
        assert envelope.payload["repository"] == "lesleslie/mahavishnu"
        assert envelope.payload["sender"] == "lesleslie"

    def test_migrate_version_conversion(self):
        """Legacy integer versions convert to semver strings."""
        from mahavishnu.core.events.migration import _migrate_version

        assert _migrate_version(1) == "1.0.0"
        assert _migrate_version(2) == "2.0.0"
        assert _migrate_version("1.0.0") == "1.0.0"

    def test_migrate_with_correlation_id(self):
        legacy = {
            "id": "b2c3d4e5-f6a7-8901-bcde-f12345678901",
            "type": "worker.started",
            "data": {"worker_type": "terminal-qwen"},
            "timestamp": "2026-04-05T12:00:00+00:00",
            "source": "worker_manager",
            "version": 1,
        }
        corr_id = UUID("98765432-9876-9876-9876-987654321098")
        envelope = migrate_legacy_event_bus_event(legacy, correlation_id=corr_id)
        assert envelope.correlation_id == corr_id

    def test_generic_migrate_event(self):
        """Test the generic event bus migration function."""
        legacy = {
            "id": "d4e5f6a7-b8c9-0123-defa-234567890123",
            "type": "some.event",
            "data": {"key": "value"},
            "timestamp": "2026-04-05T12:00:00+00:00",
            "source": "some_service",
            "version": 1,
        }
        envelope = migrate_legacy_event_bus_event(legacy)
        assert isinstance(envelope, EventEnvelope)
        assert envelope.version == "1.0.0"
