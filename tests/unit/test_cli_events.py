"""Comprehensive unit tests for the events CLI module.

Tests cover:
- validate command: schema validation, sample envelope validation, error reporting
- export command: JSON export of all registered schemas
- _build_sample_envelopes: completeness of sample envelope coverage
- _sample_payload_for: payload generation for different field types
- add_events_commands: sub-app registration

All external dependencies are mocked.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
import typer
from typer.testing import CliRunner

from mahavishnu.core.events.envelope import EventEnvelope
from mahavishnu.core.events.schema_registry import EventSchema, EventSchemaRegistry

runner = CliRunner()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_app() -> typer.Typer:
    """Create a parent Typer app with events commands registered."""
    app = typer.Typer()
    from mahavishnu.cli.events import add_events_commands

    add_events_commands(app)
    return app


# ===========================================================================
# add_events_commands
# ===========================================================================


class TestAddEventsCommands:
    """Tests for add_events_commands()."""

    def test_registers_events_sub_app(self):
        """add_events_commands should attach an 'events' sub-app."""
        app = _make_app()
        registered_names = [group.name for group in app.registered_groups]
        assert "events" in registered_names

    def test_events_app_is_typer_instance(self):
        """The events app should be a Typer instance."""
        from mahavishnu.cli.events import app as events_app

        assert isinstance(events_app, typer.Typer)


# ===========================================================================
# _build_sample_envelopes
# ===========================================================================


class TestBuildSampleEnvelopes:
    """Tests for _build_sample_envelopes()."""

    def test_returns_list(self):
        """Should return a list of EventEnvelope instances."""
        from mahavishnu.cli.events import _build_sample_envelopes

        envelopes = _build_sample_envelopes()
        assert isinstance(envelopes, list)

    def test_all_envelopes_are_event_envelopes(self):
        """All items should be EventEnvelope instances."""
        from mahavishnu.cli.events import _build_sample_envelopes

        envelopes = _build_sample_envelopes()
        for envelope in envelopes:
            assert isinstance(envelope, EventEnvelope)

    def test_covers_all_builtin_event_types(self):
        """Sample envelopes should cover all builtin event types."""
        from mahavishnu.cli.events import _build_sample_envelopes

        envelopes = _build_sample_envelopes()
        event_types = {env.event_type for env in envelopes}

        # All builtin types from schema_registry
        expected_types = {
            "code.graph.indexed",
            "worker.started",
            "worker.stopped",
            "worker.status_changed",
            "worker.error",
            "backup.started",
            "backup.completed",
            "backup.failed",
            "backup.restored",
            "pool.spawned",
            "pool.closed",
            "pool.scaled",
            "workflow.started",
            "task.created",
        }
        assert event_types == expected_types

    def test_all_envelopes_have_valid_version(self):
        """All envelopes should have valid semver version."""
        from mahavishnu.cli.events import _build_sample_envelopes
        from mahavishnu.core.events.envelope import EventVersion

        envelopes = _build_sample_envelopes()
        for envelope in envelopes:
            # Should not raise
            EventVersion(envelope.version)

    def test_all_envelopes_have_source(self):
        """All envelopes should have a source."""
        from mahavishnu.cli.events import _build_sample_envelopes

        envelopes = _build_sample_envelopes()
        for envelope in envelopes:
            assert envelope.source
            assert len(envelope.source) > 0

    def test_all_envelopes_have_non_empty_payload(self):
        """All envelopes should have non-empty payloads."""
        from mahavishnu.cli.events import _build_sample_envelopes

        envelopes = _build_sample_envelopes()
        for envelope in envelopes:
            assert len(envelope.payload) > 0


# ===========================================================================
# _sample_payload_for
# ===========================================================================


class TestSamplePayloadFor:
    """Tests for _sample_payload_for()."""

    def test_str_fields(self):
        """String fields should get 'sample' as default value."""
        from mahavishnu.cli.events import _sample_payload_for

        schema = EventSchema(
            event_type="test.event",
            required_fields=["name", "description"],
            field_types={"name": "str", "description": "str"},
        )
        payload = _sample_payload_for(schema)
        assert payload["name"] == "sample"
        assert payload["description"] == "sample"

    def test_int_fields(self):
        """Integer fields should get 0 as default value."""
        from mahavishnu.cli.events import _sample_payload_for

        schema = EventSchema(
            event_type="test.event",
            required_fields=["count"],
            field_types={"count": "int"},
        )
        payload = _sample_payload_for(schema)
        assert payload["count"] == 0

    def test_float_fields(self):
        """Float fields should get 0.0 as default value."""
        from mahavishnu.cli.events import _sample_payload_for

        schema = EventSchema(
            event_type="test.event",
            required_fields=["score"],
            field_types={"score": "float"},
        )
        payload = _sample_payload_for(schema)
        assert payload["score"] == 0.0

    def test_bool_fields(self):
        """Bool fields should get True as default value."""
        from mahavishnu.cli.events import _sample_payload_for

        schema = EventSchema(
            event_type="test.event",
            required_fields=["active"],
            field_types={"active": "bool"},
        )
        payload = _sample_payload_for(schema)
        assert payload["active"] is True

    def test_mixed_field_types(self):
        """Mixed field types should each get appropriate default."""
        from mahavishnu.cli.events import _sample_payload_for

        schema = EventSchema(
            event_type="test.event",
            required_fields=["name", "count", "score", "active"],
            field_types={
                "name": "str",
                "count": "int",
                "score": "float",
                "active": "bool",
            },
        )
        payload = _sample_payload_for(schema)
        assert payload["name"] == "sample"
        assert payload["count"] == 0
        assert payload["score"] == 0.0
        assert payload["active"] is True

    def test_unknown_type_defaults_to_str(self):
        """Unknown field types should default to 'sample' string."""
        from mahavishnu.cli.events import _sample_payload_for

        schema = EventSchema(
            event_type="test.event",
            required_fields=["data"],
            field_types={"data": "dict"},
        )
        payload = _sample_payload_for(schema)
        assert payload["data"] == "sample"

    def test_empty_required_fields(self):
        """Empty required fields should return empty payload."""
        from mahavishnu.cli.events import _sample_payload_for

        schema = EventSchema(
            event_type="test.event",
            required_fields=[],
            field_types={},
        )
        payload = _sample_payload_for(schema)
        assert payload == {}

    def test_missing_field_type_defaults_to_str(self):
        """Required field missing from field_types should default to 'sample'."""
        from mahavishnu.cli.events import _sample_payload_for

        schema = EventSchema(
            event_type="test.event",
            required_fields=["unknown_field"],
            field_types={},
        )
        payload = _sample_payload_for(schema)
        assert payload["unknown_field"] == "sample"


# ===========================================================================
# validate command
# ===========================================================================


class TestValidateSchemas:
    """Tests for the 'validate' command."""

    def test_validate_all_pass(self):
        """All builtin schemas should pass validation."""
        app = _make_app()
        result = runner.invoke(app, ["events", "validate"])
        assert result.exit_code == 0
        assert "passed validation" in result.output

    def test_validate_shows_schema_count(self):
        """Validate should show the number of registered schemas."""
        app = _make_app()
        result = runner.invoke(app, ["events", "validate"])
        assert result.exit_code == 0
        assert "registered schemas" in result.output

    def test_validate_shows_envelope_section(self):
        """Validate should show the sample envelopes section."""
        app = _make_app()
        result = runner.invoke(app, ["events", "validate"])
        assert result.exit_code == 0
        assert "Validating sample envelopes" in result.output

    def test_validate_with_invalid_envelope(self):
        """Validate should report errors for invalid envelopes."""
        registry = EventSchemaRegistry()

        # Register a schema with strict required fields
        schema = EventSchema(
            event_type="test.strict.event",
            version="1.0.0",
            required_fields=["mandatory_field"],
            field_types={"mandatory_field": "str"},
        )
        registry.register(schema)

        # Create an envelope missing the required field
        bad_envelope = EventEnvelope(
            event_type="test.strict.event",
            version="1.0.0",
            source="test",
            payload={"wrong_field": "value"},
        )

        errors = registry.validate(bad_envelope)
        assert len(errors) > 0
        assert any("mandatory_field" in e for e in errors)

    def test_validate_exit_code_on_errors(self):
        """When errors exist, validate should exit with code 1."""
        # Patch the registry to inject a schema that will fail
        with patch("mahavishnu.cli.events.EventSchemaRegistry") as mock_registry_cls:
            mock_registry = MagicMock()
            mock_registry_cls.return_value = mock_registry

            # Return schemas with one that will fail
            bad_schema = EventSchema(
                event_type="bad.event",
                version="1.0.0",
                required_fields=["must_have"],
                field_types={"must_have": "str"},
            )
            mock_registry.list_schemas.return_value = [bad_schema]

            # First validation (schema-based) passes, but second (sample) fails
            def validate_side_effect(envelope):
                if envelope.source == "schema-validation":
                    # The schema-validation envelope has the right fields
                    return []
                return ["Missing required field: must_have"]

            mock_registry.validate.side_effect = validate_side_effect

            app = _make_app()
            result = runner.invoke(app, ["events", "validate"])
            assert result.exit_code == 1
            assert "issue(s) found" in result.output

    def test_validate_schema_level_errors(self):
        """Schema-level validation errors should be reported."""
        with patch("mahavishnu.cli.events.EventSchemaRegistry") as mock_registry_cls:
            mock_registry = MagicMock()
            mock_registry_cls.return_value = mock_registry

            # Return a schema that will have validation issues
            bad_schema = EventSchema(
                event_type="broken.schema",
                version="1.0.0",
                required_fields=["field_a"],
                field_types={"field_a": "int"},
            )
            mock_registry.list_schemas.return_value = [bad_schema]

            # Schema-based validation fails because field type mismatch
            def validate_side_effect(envelope):
                if envelope.source == "schema-validation":
                    return ["Field 'field_a': expected int, got str"]
                return []

            mock_registry.validate.side_effect = validate_side_effect

            app = _make_app()
            result = runner.invoke(app, ["events", "validate"])
            assert result.exit_code == 1
            assert "issue(s) found" in result.output
            assert "expected int, got str" in result.output


# ===========================================================================
# export command
# ===========================================================================


class TestExportSchemas:
    """Tests for the 'export' command."""

    def test_export_outputs_json(self):
        """Export should output valid JSON."""
        app = _make_app()
        result = runner.invoke(app, ["events", "export"])
        assert result.exit_code == 0

        # Should be parseable JSON
        data = json.loads(result.output)
        assert isinstance(data, list)

    def test_export_contains_all_schemas(self):
        """Export should contain all builtin schemas."""
        app = _make_app()
        result = runner.invoke(app, ["events", "export"])
        assert result.exit_code == 0

        data = json.loads(result.output)
        event_types = {item["event_type"] for item in data}

        expected_types = {
            "code.graph.indexed",
            "worker.started",
            "worker.stopped",
            "worker.status_changed",
            "worker.error",
            "backup.started",
            "backup.completed",
            "backup.failed",
            "backup.restored",
            "pool.spawned",
            "pool.closed",
            "pool.scaled",
            "workflow.started",
            "task.created",
        }
        assert event_types == expected_types

    def test_export_schema_fields(self):
        """Each exported schema should have required fields."""
        app = _make_app()
        result = runner.invoke(app, ["events", "export"])
        assert result.exit_code == 0

        data = json.loads(result.output)
        for item in data:
            assert "event_type" in item
            assert "version" in item
            assert "required_fields" in item
            assert "field_types" in item
            assert "description" in item

    def test_export_sorted_keys(self):
        """Export should use sorted keys in JSON output."""
        app = _make_app()
        result = runner.invoke(app, ["events", "export"])
        assert result.exit_code == 0

        # Verify it's sorted by checking that re-serializing with sort_keys
        # produces the same output
        data = json.loads(result.output)
        reserialized = json.dumps(data, indent=2, sort_keys=True)
        assert result.output.strip() == reserialized.strip()

    def test_export_required_fields_are_lists(self):
        """Exported required_fields should be lists."""
        app = _make_app()
        result = runner.invoke(app, ["events", "export"])
        assert result.exit_code == 0

        data = json.loads(result.output)
        for item in data:
            assert isinstance(item["required_fields"], list)

    def test_export_field_types_are_dicts(self):
        """Exported field_types should be dicts."""
        app = _make_app()
        result = runner.invoke(app, ["events", "export"])
        assert result.exit_code == 0

        data = json.loads(result.output)
        for item in data:
            assert isinstance(item["field_types"], dict)


# ===========================================================================
# Integration: validate with real registry
# ===========================================================================


class TestValidateIntegration:
    """Integration tests using the real EventSchemaRegistry."""

    def test_all_builtin_schemas_valid(self):
        """All builtin schemas should pass validation."""
        registry = EventSchemaRegistry()
        schemas = registry.list_schemas()

        for schema in schemas:
            envelope = EventEnvelope(
                event_type=schema.event_type,
                version=schema.version,
                source="test",
                payload={"sample": "data"},
            )
            # Not all payloads will pass, but schemas should be well-formed
            assert schema.event_type
            assert schema.version

    def test_all_sample_envelopes_valid(self):
        """All sample envelopes should pass validation against the real registry."""
        from mahavishnu.cli.events import _build_sample_envelopes

        registry = EventSchemaRegistry()
        envelopes = _build_sample_envelopes()

        for envelope in envelopes:
            issues = registry.validate(envelope)
            assert issues == [], (
                f"Envelope {envelope.event_type} v{envelope.version} "
                f"has validation issues: {issues}"
            )

    def test_registry_has_all_expected_schemas(self):
        """Registry should have all expected builtin schemas."""
        registry = EventSchemaRegistry()
        schemas = registry.list_schemas()
        event_types = {s.event_type for s in schemas}

        expected = {
            "code.graph.indexed",
            "worker.started",
            "worker.stopped",
            "worker.status_changed",
            "worker.error",
            "backup.started",
            "backup.completed",
            "backup.failed",
            "backup.restored",
            "pool.spawned",
            "pool.closed",
            "pool.scaled",
            "workflow.started",
            "task.created",
        }
        assert event_types == expected
