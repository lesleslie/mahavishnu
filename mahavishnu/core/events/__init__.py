"""Typed Event Envelope + Governance (I9).

Versioned, type-safe event envelope for schema validation for Mahavishnu.

 ecosystem.

All event producers MUST use EventEnvelope to ensure:
 required fields, version
 compatibility,
and payload schema are enforced by CI.
 Back-compatibility guarantees are provided by correlation_id tracing.
 and
 deterministic serialization.
 This module provides:
- EventEnvelope: The typed envelope model with full metadata
- EventVersion: Semantic version parsing and compatibility checks
- EventSchemaRegistry: Registry of known event schemas for validation
- CompatibilityPolicy: Versioning rules and compatibility guarantees
- Migration helpers for upgrading legacy events to envelope format

Usage:

    from mahavishnu.core.events.envelope import EventEnvelope, EventVersion
    from mahavishnu.core.events.schema_registry import EventSchemaRegistry
    from mahavishnu.core.events.compatibility import CompatibilityPolicy
    from mahavishnu.core.events.migration import migrate_event
"""

from mahavishnu.core.errors import MahavishnuError as MahavishnuError
