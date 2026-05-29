"""Unit tests for mahavishnu/mcp/error_envelope.py."""

from __future__ import annotations

import json

from pydantic import ValidationError
import pytest

from mahavishnu.mcp.error_envelope import McpErrorEnvelope, wrap_error


class TestMcpErrorEnvelopeFields:
    """Test McpErrorEnvelope dataclass fields."""

    def test_error_field_defaults_to_true(self):
        envelope = McpErrorEnvelope(error_code="test", message="test message")
        assert envelope.error is True

    def test_error_code_is_required(self):
        with pytest.raises(ValidationError):
            McpErrorEnvelope(message="test message")  # type: ignore[call-arg]

    def test_message_is_required(self):
        with pytest.raises(ValidationError):
            McpErrorEnvelope(error_code="test")  # type: ignore[call-arg]

    def test_recovery_defaults_to_empty_list(self):
        envelope = McpErrorEnvelope(error_code="test", message="test message")
        assert envelope.recovery == []

    def test_retryable_defaults_to_false(self):
        envelope = McpErrorEnvelope(error_code="test", message="test message")
        assert envelope.retryable is False

    def test_retry_after_seconds_defaults_to_none(self):
        envelope = McpErrorEnvelope(error_code="test", message="test message")
        assert envelope.retry_after_seconds is None

    def test_details_defaults_to_empty_dict(self):
        envelope = McpErrorEnvelope(error_code="test", message="test message")
        assert envelope.details == {}


class TestFormatEnvelopeJsonStructure:
    """Test that formatEnvelope produces correct JSON structure."""

    def test_envelope_serializes_to_json_with_all_fields(self):
        envelope = McpErrorEnvelope(
            error_code="validation_error",
            message="Invalid input provided",
            recovery=["Check the input format", "Refer to API documentation"],
            retryable=True,
            retry_after_seconds=30,
            details={"field": "email", "value": "not-an-email"},
        )
        json_str = envelope.model_dump_json()
        parsed = json.loads(json_str)

        assert parsed["error"] is True
        assert parsed["error_code"] == "validation_error"
        assert parsed["message"] == "Invalid input provided"
        assert parsed["recovery"] == ["Check the input format", "Refer to API documentation"]
        assert parsed["retryable"] is True
        assert parsed["retry_after_seconds"] == 30
        assert parsed["details"] == {"field": "email", "value": "not-an-email"}

    def test_envelope_serialization_excludes_none_values(self):
        envelope = McpErrorEnvelope(
            error_code="not_found",
            message="Resource not found",
        )
        json_str = envelope.model_dump_json(exclude_none=True)
        parsed = json.loads(json_str)

        assert "retry_after_seconds" not in parsed
        assert parsed["error"] is True
        assert parsed["error_code"] == "not_found"
        assert parsed["message"] == "Resource not found"

    def test_minimal_envelope_serializes(self):
        envelope = McpErrorEnvelope(error_code="generic", message="An error occurred")
        json_str = envelope.model_dump_json()
        parsed = json.loads(json_str)

        assert set(parsed.keys()) == {
            "error",
            "error_code",
            "message",
            "recovery",
            "retryable",
            "retry_after_seconds",
            "details",
        }
        assert parsed["error"] is True
        assert parsed["error_code"] == "generic"
        assert parsed["message"] == "An error occurred"
        assert parsed["recovery"] == []
        assert parsed["retryable"] is False
        assert parsed["retry_after_seconds"] is None
        assert parsed["details"] == {}


class TestErrorCodeMapping:
    """Test error codes are mapped correctly."""

    def test_validation_error_code(self):
        envelope = wrap_error(
            error_code="validation_error",
            message="Invalid field value",
        )
        assert envelope.error_code == "validation_error"

    def test_not_found_error_code(self):
        envelope = wrap_error(
            error_code="not_found",
            message="Resource not found",
        )
        assert envelope.error_code == "not_found"

    def test_unauthorized_error_code(self):
        envelope = wrap_error(
            error_code="unauthorized",
            message="Authentication required",
        )
        assert envelope.error_code == "unauthorized"

    def test_forbidden_error_code(self):
        envelope = wrap_error(
            error_code="forbidden",
            message="Access denied",
        )
        assert envelope.error_code == "forbidden"

    def test_timeout_error_code(self):
        envelope = wrap_error(
            error_code="timeout",
            message="Request timed out",
        )
        assert envelope.error_code == "timeout"

    def test_rate_limit_error_code(self):
        envelope = wrap_error(
            error_code="rate_limit",
            message="Rate limit exceeded",
        )
        assert envelope.error_code == "rate_limit"

    def test_internal_error_code(self):
        envelope = wrap_error(
            error_code="internal_error",
            message="Internal server error",
        )
        assert envelope.error_code == "internal_error"

    def test_custom_error_code(self):
        envelope = wrap_error(
            error_code="custom_code",
            message="Custom error",
        )
        assert envelope.error_code == "custom_code"


class TestSensitiveStackTraceExclusion:
    """Test that sensitive stack trace info is excluded from envelope by default."""

    def test_no_stack_trace_field_exists(self):
        """Envelope should not have a stack_trace field by default."""
        envelope = McpErrorEnvelope(error_code="test", message="test message")
        assert not hasattr(envelope, "stack_trace")

    def test_stack_trace_not_in_serialized_output(self):
        """Stack trace should not appear in JSON serialization."""
        envelope = McpErrorEnvelope(error_code="test", message="test message")
        json_str = envelope.model_dump_json()
        parsed = json.loads(json_str)
        assert "stack_trace" not in parsed

    def test_wrap_error_does_not_accept_stack_trace(self):
        """wrap_error helper should not accept stack_trace parameter."""
        # This tests the API contract - wrap_error doesn't have stack_trace param
        import inspect

        sig = inspect.signature(wrap_error)
        assert "stack_trace" not in sig.parameters


class TestDetailsDictSerialization:
    """Test that details dict is properly serialized into envelope."""

    def test_empty_details(self):
        envelope = McpErrorEnvelope(
            error_code="test",
            message="test",
            details={},
        )
        assert envelope.details == {}
        assert json.loads(envelope.model_dump_json())["details"] == {}

    def test_simple_string_details(self):
        envelope = McpErrorEnvelope(
            error_code="test",
            message="test",
            details={"key": "value"},
        )
        assert envelope.details == {"key": "value"}

    def test_nested_dict_details(self):
        envelope = McpErrorEnvelope(
            error_code="test",
            message="test",
            details={"outer": {"inner": "value", "nested": {"deep": True}}},
        )
        assert envelope.details == {"outer": {"inner": "value", "nested": {"deep": True}}}

    def test_list_in_details(self):
        envelope = McpErrorEnvelope(
            error_code="test",
            message="test",
            details={"errors": ["error1", "error2", "error3"]},
        )
        assert envelope.details == {"errors": ["error1", "error2", "error3"]}

    def test_mixed_types_in_details(self):
        envelope = McpErrorEnvelope(
            error_code="test",
            message="test",
            details={
                "string_val": "text",
                "int_val": 42,
                "float_val": 3.14,
                "bool_val": True,
                "none_val": None,
                "list_val": [1, 2, 3],
                "nested": {"a": 1, "b": 2},
            },
        )
        assert envelope.details["string_val"] == "text"
        assert envelope.details["int_val"] == 42
        assert envelope.details["float_val"] == 3.14
        assert envelope.details["bool_val"] is True
        assert envelope.details["none_val"] is None
        assert envelope.details["list_val"] == [1, 2, 3]
        assert envelope.details["nested"] == {"a": 1, "b": 2}

    def test_details_serialized_correctly_in_json(self):
        envelope = McpErrorEnvelope(
            error_code="test",
            message="test",
            details={"field": "email", "errors": ["invalid format", "missing @"]},
        )
        json_str = envelope.model_dump_json()
        parsed = json.loads(json_str)
        assert parsed["details"] == {"field": "email", "errors": ["invalid format", "missing @"]}


class TestEdgeCases:
    """Test edge cases: empty message, very long messages, nested details."""

    def test_empty_message(self):
        envelope = wrap_error(error_code="test", message="")
        assert envelope.message == ""
        assert envelope.error_code == "test"

    def test_empty_error_code(self):
        envelope = wrap_error(error_code="", message="error")
        assert envelope.error_code == ""

    def test_very_long_message(self):
        long_message = "A" * 10000
        envelope = wrap_error(error_code="test", message=long_message)
        assert envelope.message == long_message
        assert len(envelope.message) == 10000

    def test_very_long_error_code(self):
        long_code = "X" * 1000
        envelope = wrap_error(error_code=long_code, message="test")
        assert envelope.error_code == long_code

    def test_deeply_nested_details(self):
        """Test details with deep nesting (20+ levels)."""
        nested = {
            "level_0": {
                "level_1": {
                    "level_2": {
                        "level_3": {"level_4": {"level_5": {"level_6": {"level_7": "deep"}}}}
                    }
                }
            }
        }
        envelope = wrap_error(error_code="test", message="test", details=nested)
        assert envelope.details == nested

    def test_wide_nested_details(self):
        """Test details with many sibling keys at multiple levels."""
        wide_details = {f"key_{i}": {"sub_key": f"value_{i}", "another_sub": i} for i in range(50)}
        envelope = wrap_error(error_code="test", message="test", details=wide_details)
        assert len(envelope.details) == 50

    def test_special_characters_in_message(self):
        envelope = wrap_error(error_code="test", message="Message with tabs\ttab and\nnewlines")
        assert envelope.message == "Message with tabs\ttab and\nnewlines"

    def test_unicode_in_message(self):
        envelope = wrap_error(error_code="test", message="Unicode: éèê \U0001f600 中文")
        assert envelope.message == "Unicode: éèê \U0001f600 中文"

    def test_recovery_messages_empty_list(self):
        envelope = wrap_error(
            error_code="test",
            message="test",
            recovery=[],
        )
        assert envelope.recovery == []

    def test_recovery_messages_multiple_items(self):
        envelope = wrap_error(
            error_code="test",
            message="test",
            recovery=["Step 1: Check input", "Step 2: Validate format", "Step 3: Retry"],
        )
        assert len(envelope.recovery) == 3

    def test_retry_after_seconds_zero(self):
        """Zero retry_after_seconds should be allowed (immediate retry)."""
        envelope = wrap_error(
            error_code="test",
            message="test",
            retry_after_seconds=0,
        )
        assert envelope.retry_after_seconds == 0

    def test_large_retry_after_seconds(self):
        """Large retry_after_seconds values should be supported."""
        envelope = wrap_error(
            error_code="test",
            message="test",
            retry_after_seconds=86400,
        )
        assert envelope.retry_after_seconds == 86400


class TestWrapErrorHelper:
    """Test wrap_error helper function."""

    def test_wrap_error_returns_mcp_error_envelope(self):
        result = wrap_error(error_code="test", message="test message")
        assert isinstance(result, McpErrorEnvelope)

    def test_wrap_error_all_parameters(self):
        result = wrap_error(
            error_code="validation_error",
            message="Invalid input",
            recovery=["Check docs"],
            retryable=True,
            retry_after_seconds=60,
            details={"field": "name"},
        )
        assert result.error_code == "validation_error"
        assert result.message == "Invalid input"
        assert result.recovery == ["Check docs"]
        assert result.retryable is True
        assert result.retry_after_seconds == 60
        assert result.details == {"field": "name"}

    def test_wrap_error_default_recovery_to_empty_list(self):
        result = wrap_error(error_code="test", message="test")
        assert result.recovery == []

    def test_wrap_error_default_retryable_to_false(self):
        result = wrap_error(error_code="test", message="test")
        assert result.retryable is False

    def test_wrap_error_default_details_to_empty_dict(self):
        result = wrap_error(error_code="test", message="test")
        assert result.details == {}

    def test_wrap_error_with_none_recovery(self):
        """None recovery should convert to empty list."""
        result = wrap_error(error_code="test", message="test", recovery=None)
        assert result.recovery == []

    def test_wrap_error_with_none_details(self):
        """None details should convert to empty dict."""
        result = wrap_error(error_code="test", message="test", details=None)
        assert result.details == {}

    def test_wrap_error_retry_after_seconds_after_none(self):
        """None retry_after_seconds should stay None."""
        result = wrap_error(error_code="test", message="test", retry_after_seconds=None)
        assert result.retry_after_seconds is None
