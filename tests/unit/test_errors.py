"""Unit tests for error handling hierarchy."""

from mahavishnu.core.errors import AdapterError, ConfigurationError, ValidationError


def test_error_hierarchy():
    """Test that custom errors inherit from appropriate base classes."""
    # All custom errors should inherit from Exception
    assert issubclass(ConfigurationError, Exception)
    assert issubclass(ValidationError, Exception)
    assert issubclass(AdapterError, Exception)


def test_configuration_error():
    """Test ConfigurationError functionality."""
    error = ConfigurationError(message="Test config error", details={"key": "value"})

    # New error format includes error code and recovery guidance
    assert "Test config error" in str(error)
    assert "MHV-001" in str(error)
    assert error.details == {"key": "value"}
    assert error.message == "Test config error"


def test_validation_error():
    """Test ValidationError functionality."""
    error = ValidationError(message="Test validation error", details={"field": "value"})

    # New error format includes error code and recovery guidance
    assert "Test validation error" in str(error)
    assert "MHV-003" in str(error)
    assert error.details == {"field": "value"}
    assert error.message == "Test validation error"


def test_adapter_error():
    """Test AdapterError functionality."""
    error = AdapterError(message="Test adapter error", details={"adapter": "test"})

    # New error format includes error code and recovery guidance
    assert "Test adapter error" in str(error)
    assert "MHV-007" in str(error)
    assert error.details == {"adapter": "test"}
    assert error.message == "Test adapter error"
