"""EventEnvelope — typed, versioned event envelope with full metadata.


All events flowing through Mahavishnu must use EventEnvelope
 to guarantee:
- Unique identity (event_id)
- Versioned schema (version, semver)
- Causal tracing (correlation_id)
- Deterministic serialization (JSON)
- Source attribution (source)
- Timestamp in UTC
- Type safety via Pydantic validation

"""

from __future__ import annotations

from datetime import UTC, datetime
import json
from typing import Any
import uuid
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class EventVersion:
    """Semantic version in MAJOR.MINOR.PATCH format.

    Provides:
    - Parsing from string
    - Compatibility checking (backward compatible within same MAJOR)
    - Bumping helpers
    - Comparison operators

    Examples:
        >>> v = EventVersion("1.0.0")
        >>> v.major
        1
        >>> v.minor
        0
        >>> v.patch
        0
        >>> v.is_compatible_with(EventVersion("1.0.7"))
        True  # backward compatible
        >>> EventVersion("2.0.0").is_compatible_with(EventVersion("1.0.0"))
        False  # major version bump
    """

    def __init__(self, version_str: str) -> None:
        parts = version_str.split(".")
        if len(parts) != 3:
            raise ValueError(f"Invalid version format: {version_str!r} Expected MAJOR.MINOR.PATCH")
        self.major = int(parts[0])
        self.minor = int(parts[1])
        self.patch = int(parts[2])

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"

    def __repr__(self) -> str:
        return f"EventVersion({self})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, EventVersion):
            return NotImplemented
        return self.major == other.major and self.minor == other.minor and self.patch == other.patch

    def __hash__(self) -> int:
        return hash((self.major, self.minor, self.patch))

    def __lt__(self, other: EventVersion) -> bool:
        if not isinstance(other, EventVersion):
            return NotImplemented
        return (self.major, self.minor, self.patch) < (
            other.major,
            other.minor,
            other.patch,
        )

    def is_compatible_with(self, other: EventVersion) -> bool:
        """Check backward compatibility.

        Two versions are compatible if they share the same MAJOR version.
        This is the "producer version" check — can this producer's
        schema be read by a consumer expecting `other`?

        Args:
            other: Consumer's expected version.

        Returns:
            True if backward-compatible (same major, producer minor >= consumer minor).
        """
        return self.major == other.major and self.minor >= other.minor

    def bump_patch(self) -> EventVersion:
        """Create a new version with PATCH incremented."""
        return EventVersion(f"{self.major}.{self.minor}.{self.patch + 1}")

    def bump_minor(self) -> EventVersion:
        """Create a new version with MINOR incremented, PATCH reset."""
        return EventVersion(f"{self.major}.{self.minor + 1}.0")

    def bump_major(self) -> EventVersion:
        """Create a new version with MAJOR incremented, MINOR and PATCH reset."""
        return EventVersion(f"{self.major + 1}.0.0")

    @classmethod
    def parse(cls, version_str: str) -> EventVersion:
        """Parse a version string into EventVersion."""
        return cls(version_str)


class EventEnvelope(BaseModel):
    """Typed, versioned event envelope for full metadata.

    All inter-component events in Mahavishnu must use this envelope
    to ensure:
    - Unique identity and traceability
    - Version-aware schema compatibility
    - Causal tracing across services
    - Deterministic JSON serialization
    - Source attribution for audit trails

    Design Principles:
    - Envelope metadata is required (never None)
    - Payload is untyped dict (domain-specific validation in schema registry)
    - Serialized to canonical JSON for storage/transit
    - Backward-compatible consumers within same MAJOR version
    """

    model_config = {"frozen": True}

    event_id: UUID = Field(
        default_factory=uuid.uuid4,
        description="Unique event identifier (UUIDv4)",
    )
    event_type: str = Field(
        ...,
        description="Event type from domain enum (e.g., 'code.graph.indexed')",
        min_length=1,
        max_length=128,
    )
    version: str = Field(
        default="1.0.0",
        description="Schema version in MAJOR.MINOR.PATCH format",
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Event timestamp in UTC",
    )
    source: str = Field(
        ...,
        description="Source component (e.g., 'code_index_service', 'task_store')",
        min_length=1,
        max_length=128,
    )
    correlation_id: UUID | None = Field(
        default=None,
        description="Correlation ID for tracing across services",
    )
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Domain-specific event payload",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata (tracing, audit, etc.)",
    )

    @field_validator("version")
    @classmethod
    def _validate_version(cls, v: str) -> str:
        EventVersion(v)  # Raises ValueError if invalid
        return v

    @field_validator("event_type")
    @classmethod
    def _validate_event_type(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("event_type must be non-empty")
        return v

    def to_dict(self) -> dict[str, Any]:
        """Serialize to canonical dictionary.

        Ensures deterministic ordering for storage and transit.
        UUIDs in string format. Timestamps in ISO 8601 format.
        """
        return {
            "event_id": str(self.event_id),
            "event_type": self.event_type,
            "version": self.version,
            "timestamp": self.timestamp.isoformat(),
            "source": self.source,
            "correlation_id": str(self.correlation_id) if self.correlation_id else None,
            "payload": self.payload,
            "metadata": self.metadata,
        }

    def to_json(self) -> str:
        """Serialize to canonical JSON string with deterministic key ordering."""
        return json.dumps(self.to_dict(), sort_keys=True)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EventEnvelope:
        """Deserialize from dictionary.

        Handles both new envelope format and legacy format migration.

        Args:
            data: Dictionary in envelope or legacy format.

        Returns:
            EventEnvelope instance.
        """
        # Handle legacy format (no version field)
        if "version" not in data:
            data = {**data, "version": "0.1.0"}
        if "correlation_id" not in data:
            data = {**data, "correlation_id": None}
        if "metadata" not in data:
            data = {**data, "metadata": {}}
        if "event_id" not in data:
            # Legacy format uses 'id' field
            data = {**data, "event_id": data.pop("id", uuid.uuid4())}

        return cls(**data)

    @classmethod
    def from_json(cls, json_str: str) -> EventEnvelope:
        """Deserialize from JSON string."""
        data = json.loads(json_str)
        return cls.from_dict(data)
