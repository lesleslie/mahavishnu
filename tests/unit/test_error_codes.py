"""Guard tests for error codes and TerminalError implementation."""

from __future__ import annotations

import pytest

from mahavishnu.core.errors import ErrorCode
from mahavishnu.terminal.adapters.mcpretentious import (
    SessionNotFoundError,
    TerminalError,
)


@pytest.mark.unit
class TestErrorCodeRegistration:
    """Test error code registration and uniqueness."""

    def test_crow_mcp_unavailable_error_code_registered(self) -> None:
        """Verify MHV-307 error code exists and is accessible."""
        assert ErrorCode.CROW_MCP_UNAVAILABLE == "MHV-307"
        assert hasattr(ErrorCode, "CROW_MCP_UNAVAILABLE")

    def test_no_duplicate_error_code_values(self) -> None:
        """Verify no two ErrorCode members share the same value."""
        error_codes = {member.value for member in ErrorCode}
        all_members = [member for member in ErrorCode]
        assert len(error_codes) == len(all_members), (
            f"Duplicate error code values detected. "
            f"Found {len(all_members)} members but only {len(error_codes)} unique values."
        )


@pytest.mark.unit
class TestTerminalErrorCustomCode:
    """Test TerminalError accepts custom error codes."""

    def test_terminal_error_accepts_custom_error_code(self) -> None:
        """Verify TerminalError accepts and stores custom error_code."""
        custom_message = "MCP server unavailable"
        error = TerminalError(
            custom_message,
            error_code=ErrorCode.CROW_MCP_UNAVAILABLE,
        )
        assert error.error_code == ErrorCode.CROW_MCP_UNAVAILABLE
        assert error.message == custom_message

    def test_terminal_error_backward_compatible_default_code(self) -> None:
        """Verify TerminalError uses default INTERNAL_ERROR when no code specified."""
        custom_message = "Generic terminal error"
        error = TerminalError(custom_message)
        assert error.error_code == ErrorCode.INTERNAL_ERROR
        assert error.message == custom_message

    def test_terminal_error_with_details_and_custom_code(self) -> None:
        """Verify TerminalError accepts details alongside custom code."""
        custom_message = "Session creation failed"
        custom_details = {"session_id": "sess_123", "reason": "timeout"}
        error = TerminalError(
            custom_message,
            error_code=ErrorCode.CROW_MCP_UNAVAILABLE,
            details=custom_details,
        )
        assert error.error_code == ErrorCode.CROW_MCP_UNAVAILABLE
        assert error.details == custom_details


@pytest.mark.unit
class TestSessionNotFoundErrorBackcompat:
    """Test SessionNotFoundError compatibility after TerminalError change."""

    def test_session_not_found_error_still_works(self) -> None:
        """Verify SessionNotFoundError still functions correctly."""
        error = SessionNotFoundError(
            "Session sess_123 not found",
            details={"session_id": "sess_123"},
        )
        assert isinstance(error, TerminalError)
        assert error.message == "Session sess_123 not found"
        assert error.details == {"session_id": "sess_123"}
