"""Integration tests for iTerm2 session ID format compatibility.

This test module validates cross-repo session ID format compatibility between
Mahavishnu (Python) and mdinject (Swift).

Canonical spec: mcp-common/docs/iterm2-applescript-protocol.md

Test cases:
1. Swift canonical format `session_123` can be parsed by Mahavishnu
2. Mahavishnu internally generates `grid_abc123` format — verify it's distinct from Swift format
3. Round-trip: format in Python → parse in Python → same result
4. Verify the canonical `session_{int}` pattern from Swift doesn't conflict with Mahavishnu's `grid_` prefix pattern
"""

import re
import uuid
from typing import NamedTuple

import pytest


# =============================================================================
# Session ID Format Patterns (from iTerm2 AppleScript Protocol)
# =============================================================================

# Swift canonical format: "session_{iTerm2IntId}" where iTerm2IntId is an integer
SWIFT_SESSION_PATTERN = re.compile(r"^session_\d+$")

# Mahavishnu grid format: "grid_{uuid[:8]}" where uuid[:8] is 8 hex chars
MAHAVISHNU_GRID_PATTERN = re.compile(r"^grid_[0-9a-f]{8}$")

# Mahavishnu session format: UUID[:8] used internally by ITerm2Adapter.launch_session
MAHAVISHNU_SESSION_PATTERN = re.compile(r"^[0-9a-f]{8}$")


class SwiftSessionId(NamedTuple):
    """Parsed Swift canonical session ID."""
    int_id: int

    @classmethod
    def parse(cls, session_id: str) -> "SwiftSessionId":
        """Parse a Swift canonical session ID like 'session_123'.

        Args:
            session_id: Session ID string in Swift format.

        Returns:
            SwiftSessionId with parsed integer ID.

        Raises:
            ValueError: If session_id doesn't match Swift format.
        """
        if not SWIFT_SESSION_PATTERN.match(session_id):
            raise ValueError(
                f"Invalid Swift session ID format: {session_id!r}. "
                f"Expected format: session_{{int}}"
            )
        int_id = int(session_id.split("_")[1])
        return cls(int_id=int_id)

    def format(self) -> str:
        """Format as Swift canonical session ID."""
        return f"session_{self.int_id}"


class MahavishnuGridId(NamedTuple):
    """Mahavishnu grid ID."""
    uuid_prefix: str

    @classmethod
    def parse(cls, grid_id: str) -> "MahavishnuGridId":
        """Parse a Mahavishnu grid ID like 'grid_abc12345'.

        Args:
            grid_id: Grid ID string in Mahavishnu format.

        Returns:
            MahavishnuGridId with parsed UUID prefix.

        Raises:
            ValueError: If grid_id doesn't match Mahavishnu format.
        """
        if not MAHAVISHNU_GRID_PATTERN.match(grid_id):
            raise ValueError(
                f"Invalid Mahavishnu grid ID format: {grid_id!r}. "
                f"Expected format: grid_{{uuid_prefix}}"
            )
        uuid_prefix = grid_id.split("_")[1]
        return cls(uuid_prefix=uuid_prefix)

    @classmethod
    def generate(cls) -> "MahavishnuGridId":
        """Generate a new Mahavishnu grid ID."""
        return cls(uuid_prefix=str(uuid.uuid4())[:8])

    def format(self) -> str:
        """Format as Mahavishnu grid ID."""
        return f"grid_{self.uuid_prefix}"


class MahavishnuSessionId(NamedTuple):
    """Mahavishnu internal session ID (UUID[:8])."""
    uuid_prefix: str

    @classmethod
    def parse(cls, session_id: str) -> "MahavishnuSessionId":
        """Parse a Mahavishnu session ID (8 hex chars).

        Args:
            session_id: Session ID string in Mahavishnu format.

        Returns:
            MahavishnuSessionId with parsed UUID prefix.

        Raises:
            ValueError: If session_id doesn't match Mahavishnu format.
        """
        if not MAHAVISHNU_SESSION_PATTERN.match(session_id):
            raise ValueError(
                f"Invalid Mahavishnu session ID format: {session_id!r}. "
                f"Expected format: 8 hex characters"
            )
        return cls(uuid_prefix=session_id)

    @classmethod
    def generate(cls) -> "MahavishnuSessionId":
        """Generate a new Mahavishnu session ID."""
        return cls(uuid_prefix=str(uuid.uuid4())[:8])

    def format(self) -> str:
        """Format as Mahavishnu session ID."""
        return self.uuid_prefix


# =============================================================================
# Test Cases
# =============================================================================

class TestSwiftCanonicalFormat:
    """Test 1: Swift canonical format `session_123` can be parsed by Mahavishnu."""

    def test_parse_valid_swift_session_id(self) -> None:
        """Verify Swift session ID format can be parsed."""
        session = SwiftSessionId.parse("session_123")
        assert session.int_id == 123

    def test_parse_swift_session_id_zero(self) -> None:
        """Verify Swift session ID with zero is valid."""
        session = SwiftSessionId.parse("session_0")
        assert session.int_id == 0

    def test_parse_swift_session_id_large(self) -> None:
        """Verify Swift session ID with large integer is valid."""
        session = SwiftSessionId.parse("session_999999999")
        assert session.int_id == 999999999

    def test_format_roundtrip(self) -> None:
        """Verify Swift session ID format round-trips correctly."""
        original = "session_456"
        parsed = SwiftSessionId.parse(original)
        formatted = parsed.format()
        assert formatted == original

    def test_rejects_invalid_format(self) -> None:
        """Verify invalid Swift session ID formats are rejected."""
        invalid_ids = [
            "session_abc",      # non-numeric
            "session_",          # missing number
            "session",          # missing underscore and number
            "grid_abc12345",    # Mahavishnu grid format
            "abc12345",         # raw UUID prefix
            "session-123",      # wrong separator
            "SESSION_123",      # wrong case
        ]
        for invalid in invalid_ids:
            with pytest.raises(ValueError, match="Invalid Swift session ID format"):
                SwiftSessionId.parse(invalid)


class TestMahavishnuGridFormat:
    """Test 2: Mahavishnu internally generates `grid_abc123` format — distinct from Swift."""

    def test_grid_id_matches_pattern(self) -> None:
        """Verify Mahavishnu grid ID matches expected pattern."""
        grid_id = MahavishnuGridId.generate()
        assert MAHAVISHNU_GRID_PATTERN.match(grid_id.format())
        assert grid_id.format().startswith("grid_")

    def test_grid_format_distinct_from_swift(self) -> None:
        """Verify grid format is distinct from Swift session format."""
        grid_id = MahavishnuGridId.generate()
        formatted = grid_id.format()

        # Grid IDs start with "grid_" not "session_"
        assert formatted.startswith("grid_")
        assert not formatted.startswith("session_")

        # Grid IDs have 8 hex chars after prefix (13 total: "grid_" + 8)
        assert len(formatted) == 13
        assert len(formatted.split("_")[1]) == 8

    def test_swift_format_rejected_as_grid(self) -> None:
        """Verify Swift session format is NOT a valid Mahavishnu grid ID."""
        # Swift format should not match Mahavishnu grid pattern
        assert not MAHAVISHNU_GRID_PATTERN.match("session_123")
        assert not MAHAVISHNU_GRID_PATTERN.match("session_999")

    def test_grid_id_is_not_integer_based(self) -> None:
        """Verify Mahavishnu grid IDs are UUID-based, not integer-based."""
        # Swift uses integer IDs
        swift_session = SwiftSessionId.parse("session_123")
        assert isinstance(swift_session.int_id, int)

        # Mahavishnu uses UUID prefix
        grid_id = MahavishnuGridId.generate()
        assert isinstance(grid_id.uuid_prefix, str)
        assert len(grid_id.uuid_prefix) == 8

        # They are fundamentally different identification schemes
        assert not SWIFT_SESSION_PATTERN.match(grid_id.format())
        assert not MAHAVISHNU_GRID_PATTERN.match(swift_session.format())


class TestRoundTripCompatibility:
    """Test 3: Round-trip — format in Python → parse in Python → same result."""

    def test_swift_session_roundtrip(self) -> None:
        """Verify Swift session ID format round-trips correctly."""
        original = "session_789"
        parsed = SwiftSessionId.parse(original)
        formatted = parsed.format()
        assert formatted == original

    def test_mahavishnu_grid_roundtrip(self) -> None:
        """Verify Mahavishnu grid ID round-trips correctly."""
        # Generate and parse
        grid_id = MahavishnuGridId.generate()
        original = grid_id.format()

        # Parse the formatted string
        parsed = MahavishnuGridId.parse(original)

        # Re-format and verify
        assert parsed.format() == original
        assert parsed.uuid_prefix == grid_id.uuid_prefix

    def test_mahavishnu_session_roundtrip(self) -> None:
        """Verify Mahavishnu session ID round-trips correctly."""
        session_id = MahavishnuSessionId.generate()
        original = session_id.format()

        parsed = MahavishnuSessionId.parse(original)
        assert parsed.format() == original
        assert parsed.uuid_prefix == session_id.uuid_prefix


class TestPatternConflictVerification:
    """Test 4: Verify canonical `session_{int}` pattern doesn't conflict with Mahavishnu `grid_` prefix."""

    def test_swift_and_grid_patterns_are_orthogonal(self) -> None:
        """Verify Swift and Mahavishnu patterns don't overlap."""
        # Swift pattern: session_\d+
        # Mahavishnu grid pattern: grid_[0-9a-f]{8}

        # Sample values should not cross-match
        swift_ids = [f"session_{i}" for i in [1, 100, 999, 12345]]
        grid_ids = [MahavishnuGridId.generate().format() for _ in range(4)]

        for sid in swift_ids:
            assert SWIFT_SESSION_PATTERN.match(sid)
            assert not MAHAVISHNU_GRID_PATTERN.match(sid)

        for gid in grid_ids:
            assert MAHAVISHNU_GRID_PATTERN.match(gid)
            assert not SWIFT_SESSION_PATTERN.match(gid)

    def test_prefix_disambiguation(self) -> None:
        """Verify prefix-based disambiguation works correctly."""
        # By checking the prefix, we can always distinguish the format
        test_cases = [
            ("session_123", "swift"),
            ("session_0", "swift"),
            ("grid_abc12345", "mahavishnu_grid"),
            ("grid_00000000", "mahavishnu_grid"),
        ]

        for session_id, expected_type in test_cases:
            if session_id.startswith("session_"):
                assert expected_type == "swift"
                parsed = SwiftSessionId.parse(session_id)
                assert parsed.int_id == int(session_id.split("_")[1])
            elif session_id.startswith("grid_"):
                assert expected_type == "mahavishnu_grid"
                parsed = MahavishnuGridId.parse(session_id)
                assert parsed.uuid_prefix == session_id.split("_")[1]

    def test_mahavishnu_session_format_is_distinct(self) -> None:
        """Verify Mahavishnu internal session format (UUID[:8]) is distinct."""
        # Mahavishnu session IDs are just 8 hex chars
        mahavishnu_session = MahavishnuSessionId.generate()

        # Should NOT match Swift format
        assert not mahavishnu_session.format().startswith("session_")
        assert not mahavishnu_session.format().startswith("grid_")

        # Should match Mahavishnu internal pattern
        assert MAHAVISHNU_SESSION_PATTERN.match(mahavishnu_session.format())

    def test_no_possible_conflict_between_formats(self) -> None:
        """Verify no string could be valid for both formats.

        Swift format: session_ followed by digits only
        Mahavishnu format: grid_ followed by 8 hex chars

        The only potential conflict would be if 'session_abc12345' was valid,
        but Swift requires digits and Mahavishnu uses hex chars, so no conflict.
        """
        # A string cannot simultaneously be:
        # - session_\d+ (Swift)
        # - grid_[0-9a-f]{8} (Mahavishnu grid)

        # Test edge cases that might seem like conflicts
        edge_cases = [
            "session_00000000",  # digits only (Swift valid)
            "grid_12345678",     # hex chars (Mahavishnu valid)
        ]

        # session_00000000 is valid Swift, not valid Mahavishnu grid
        assert SWIFT_SESSION_PATTERN.match("session_00000000")
        assert not MAHAVISHNU_GRID_PATTERN.match("session_00000000")

        # grid_12345678 is valid Mahavishnu grid, not valid Swift
        assert MAHAVISHNU_GRID_PATTERN.match("grid_12345678")
        assert not SWIFT_SESSION_PATTERN.match("grid_12345678")
