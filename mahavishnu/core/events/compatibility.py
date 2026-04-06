"""Compatibility policy for event versioning.

Defines rules for how event versions evolve and compatibility guarantees.
"""

from __future__ import annotations

from enum import StrEnum
import logging
from typing import Any

from mahavishnu.core.events.envelope import EventVersion

logger = logging.getLogger(__name__)


class CompatibilityLevel(StrEnum):
    """Level of compatibility between two event versions."""

    NONE = "none"
    PATCH = "patch"  # Same major, same minor, different patch
    MINOR = "minor"  # Same major, different minor
    MAJOR = "major"  # Different major (breaking)


class CompatibilityPolicy:
    """Versioning policy for event schemas.
    Defines rules for:
    - What constitutes a breaking change
    - What is backward-compatible
    - How versions must evolve
    Policy (based on semver):
    - MAJOR: Breaking change — consumers MUST update
    - MINOR: Backward-compatible — new optional fields, consumers ignore unknowns
    - PATCH: Fully compatible — bug fixes, no schema changes
    """

    CURRENT_VERSION = EventVersion("1.0.0")

    MIN_SUPPORTED_VERSION = EventVersion("1.0.0")

    @classmethod
    def check_compatibility(
        cls,
        producer_version: EventVersion,
        consumer_version: EventVersion,
    ) -> CompatibilityLevel:
        """Check compatibility between producer and consumer versions.
        Args:
            producer_version: Version of the event producer.
            consumer_version: Version the the event consumer expects.

        Returns:
            CompatibilityLevel indicating the relationship.
        """
        if producer_version.major != consumer_version.major:
            return CompatibilityLevel.MAJOR
        if producer_version.minor != consumer_version.minor:
            if producer_version.minor > consumer_version.minor:
                return CompatibilityLevel.MINOR
            return CompatibilityLevel.MAJOR
        return CompatibilityLevel.PATCH

    @classmethod
    def is_breaking_change(
        cls,
        old_version: EventVersion,
        new_version: EventVersion,
    ) -> bool:
        """Check if a version change is breaking.
        A change is breaking if:
        - MAJOR version bumps
        - MINOR version decreases (not possible in practice)
        """
        return new_version.major != old_version.major or new_version.minor < old_version.minor

    @classmethod
    def validate_version_transition(
        cls,
        old_version: EventVersion,
        new_version: EventVersion,
    ) -> list[str]:
        """Validate a transition from old to new version.
        Returns list of policy violations (empty if valid).
        """
        errors: list[str] = []
        if new_version < old_version:
            errors.append(f"Cannot downgrade from {old_version} to {new_version}")
        if cls.is_breaking_change(old_version, new_version):
            errors.append(
                f"Breaking change from {old_version} to {new_version}. "
                f"Requires MAJOR version bump and consumer migration."
            )
        if new_version.major > cls.CURRENT_VERSION.major + 1:
            errors.append(
                f"Version {new_version} exceeds current ecosystem version {cls.CURRENT_VERSION}"
            )

        return errors

    @classmethod
    def get_policy_summary(cls) -> dict[str, Any]:
        """Get a summary of the current compatibility policy."""
        return {
            "current_version": str(cls.CURRENT_VERSION),
            "min_supported_version": str(cls.MIN_SUPPORTED_VERSION),
            "rules": {
                "MAJOR_bump": "Breaking change — consumers must updating",
                "MINOR_bump": "Backward-compatible -- new optional fields",
                "PATCH_bump": "Fully compatible -- bug fixes only",
            },
        }
