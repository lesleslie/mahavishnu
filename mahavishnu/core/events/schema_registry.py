"""Schema registry for event types with versioned schemas.

Provides validation of event payloads against registered schemas
and compatibility checking between event versions.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field, field_validator

from mahavishnu.core.errors import ErrorCode, MahavishnuError
from mahavishnu.core.events.envelope import EventEnvelope, EventVersion

logger = logging.getLogger(__name__)


class SchemaError(MahavishnuError):
    """Raised when event schema validation fails."""

    def __init__(self, message: str, details: dict | None = None) -> None:
        super().__init__(message, ErrorCode.VALIDATION_ERROR, details=details or {})


class EventSchema(BaseModel):
    """Schema definition for a registered event type.

    Attributes:
        event_type: The event type string (e.g., 'code.graph.indexed')
        version: Schema version string
        required_fields: Top-level fields required in the payload
        field_types: Expected types for payload fields (field_name -> type_name)
        description: Human-readable description of this event type
    """

    event_type: str = Field(..., min_length=1)
    version: str = Field(default="1.0.0")
    required_fields: list[str] = Field(default_factory=list)
    field_types: dict[str, str] = Field(default_factory=dict)
    description: str = Field(default="")

    @field_validator("version")
    @classmethod
    def _validate_version(cls, v: str) -> str:
        EventVersion(v)
        return v


class EventSchemaRegistry:
    """Registry of known event schemas for validation.

    Maintains a mapping of (event_type, version) -> EventSchema.

    Supports:
    - Registering new schemas
    - Validating events against registered schemas
    - Checking compatibility between versions
    - Listing all registered schemas
    """

    def __init__(self) -> None:
        self._schemas: dict[str, EventSchema] = {}
        self._register_builtin_schemas()

    def register(self, schema: EventSchema) -> None:
        """Register a schema for an event type.

        Args:
            schema: Schema definition to register.

        Raises:
            ValueError: If a schema with same type and version already exists.
        """
        key = self._schema_key(schema.event_type, schema.version)
        if key in self._schemas:
            raise ValueError(
                f"Schema already registered: {schema.event_type} v{schema.version}"
            )
        self._schemas[key] = schema
        logger.debug(f"Registered schema: {key}")

    def validate(self, envelope: EventEnvelope) -> list[str]:
        """Validate an event envelope against registered schemas.

        Checks:
        1. Schema exists for event_type
        2. Version is compatible with registered version
        3. All required fields are present in payload
        4. Field types match expected types

        Args:
            envelope: Event envelope to validate.

        Returns:
            List of validation errors (empty if valid).
        """
        errors: list[str] = []
        key = self._schema_key(envelope.event_type, envelope.version)

        # Check if schema is registered
        if key not in self._schemas:
            # Try finding any schema for this event type
            type_keys = [k for k in self._schemas if k.startswith(f"{envelope.event_type}:")]
            if not type_keys:
                errors.append(
                    f"No schema registered for event_type '{envelope.event_type}'"
                )
                return errors

            # Find the latest registered version for this type
            latest_key = type_keys[-1]
            schema = self._schemas[latest_key]

            # Check version compatibility
            registered_ver = EventVersion(schema.version)
            event_ver = EventVersion(envelope.version)
            if not registered_ver.is_compatible_with(event_ver):
                errors.append(
                    f"Version mismatch: event v{envelope.version}, "
                    f"registered v{schema.version}"
                )
        else:
            schema = self._schemas[key]

        # Check required fields
        payload = envelope.payload
        for field_name in schema.required_fields:
            if field_name not in payload:
                errors.append(f"Missing required field: {field_name}")

        # Check field types
        for field_name, expected_type in schema.field_types.items():
            if field_name in payload:
                actual = type(payload[field_name]).__name__
                if actual != expected_type:
                    errors.append(
                        f"Field '{field_name}': expected {expected_type}, got {actual}"
                    )

        return errors

    def is_registered(self, event_type: str, version: str = "1.0.0") -> bool:
        """Check if a schema is registered for the event type and version."""
        key = self._schema_key(event_type, version)
        return key in self._schemas

    def get_schema(self, event_type: str, version: str = "1.0.0") -> EventSchema | None:
        """Get the schema for an event type and version.

        Args:
            event_type: Event type string.
            version: Schema version string.

        Returns:
            EventSchema if found, None otherwise.
        """
        key = self._schema_key(event_type, version)
        return self._schemas.get(key)

    def list_schemas(self) -> list[EventSchema]:
        """List all registered schemas."""
        return list(self._schemas.values())

    @staticmethod
    def _schema_key(event_type: str, version: str) -> str:
        return f"{event_type}:{version}"

    def _register_builtin_schemas(self) -> None:
        """Register built-in schemas for Mahavishnu event types."""
        builtin_schemas = [
            EventSchema(
                event_type="code.graph.indexed",
                version="1.0.0",
                required_fields=["repo_path", "nodes_count"],
                field_types={
                    "repo_path": "str",
                    "nodes_count": "int",
                    "commit_hash": "str",
                },
                description="Code graph indexing completed",
            ),
            EventSchema(
                event_type="worker.started",
                version="1.0.0",
                required_fields=["worker_id", "worker_type"],
                field_types={
                    "worker_id": "str",
                    "worker_type": "str",
                },
                description="Worker process started",
            ),
            EventSchema(
                event_type="worker.stopped",
                version="1.0.0",
                required_fields=["worker_id"],
                field_types={
                    "worker_id": "str",
                    "exit_code": "int",
                },
                description="Worker process stopped",
            ),
            EventSchema(
                event_type="worker.status_changed",
                version="1.0.0",
                required_fields=["worker_id", "status"],
                field_types={
                    "worker_id": "str",
                    "status": "str",
                },
                description="Worker status changed",
            ),
            EventSchema(
                event_type="worker.error",
                version="1.0.0",
                required_fields=["worker_id", "error"],
                field_types={
                    "worker_id": "str",
                    "error": "str",
                },
                description="Worker encountered error",
            ),
            EventSchema(
                event_type="backup.started",
                version="1.0.0",
                required_fields=["backup_type"],
                field_types={"backup_type": "str"},
                description="Backup operation started",
            ),
            EventSchema(
                event_type="backup.completed",
                version="1.0.0",
                required_fields=["backup_id"],
                field_types={"backup_id": "str"},
                description="Backup operation completed",
            ),
            EventSchema(
                event_type="backup.failed",
                version="1.0.0",
                required_fields=["error"],
                field_types={"error": "str"},
                description="Backup operation failed",
            ),
            EventSchema(
                event_type="backup.restored",
                version="1.0.0",
                required_fields=["backup_id"],
                field_types={"backup_id": "str"},
                description="Backup restored successfully",
            ),
            EventSchema(
                event_type="pool.spawned",
                version="1.0.0",
                required_fields=["pool_id", "pool_type"],
                field_types={
                    "pool_id": "str",
                    "pool_type": "str",
                },
                description="Worker pool spawned",
            ),
            EventSchema(
                event_type="pool.closed",
                version="1.0.0",
                required_fields=["pool_id"],
                field_types={"pool_id": "str"},
                description="Worker pool closed",
            ),
            EventSchema(
                event_type="pool.scaled",
                version="1.0.0",
                required_fields=["pool_id", "target_workers"],
                field_types={
                    "pool_id": "str",
                    "target_workers": "int",
                },
                description="Worker pool scaled",
            ),
            EventSchema(
                event_type="workflow.started",
                version="1.0.0",
                required_fields=["workflow_id"],
                field_types={"workflow_id": "str"},
                description="Workflow execution started",
            ),
            EventSchema(
                event_type="task.created",
                version="1.0.0",
                required_fields=["task_id"],
                field_types={"task_id": "str"},
                description="Task created",
            ),
        ]
        for schema in builtin_schemas:
            try:
                self.register(schema)
            except ValueError:
                pass  # Already registered, skip
