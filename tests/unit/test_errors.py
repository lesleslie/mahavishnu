"""Unit tests for error handling hierarchy."""
import pytest
from mahavishnu.core.errors import ConfigurationError, ValidationError, AdapterError


def test_error_hierarchy():
    """Test that custom errors inherit from appropriate base classes."""
    # All custom errors should inherit from Exception
    assert issubclass(ConfigurationError, Exception)
    assert issubclass(ValidationError, Exception)
    assert issubclass(AdapterError, Exception)


def test_configuration_error():
    """Test ConfigurationError functionality."""
    error = ConfigurationError(message="Test config error", details={"key": "value"})
    
    assert str(error) == "Test config error"
    assert error.details == {"key": "value"}
    assert error.message == "Test config error"


def test_validation_error():
    """Test ValidationError functionality."""
    error = ValidationError(message="Test validation error", details={"field": "value"})
    
    assert str(error) == "Test validation error"
    assert error.details == {"field": "value"}
    assert error.message == "Test validation error"


def test_adapter_error():
    """Test AdapterError functionality."""
    error = AdapterError(message="Test adapter error", details={"adapter": "test"})
    
    assert str(error) == "Test adapter error"
    assert error.details == {"adapter": "test"}
    assert error.message == "Test adapter error"