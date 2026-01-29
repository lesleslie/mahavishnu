"""Unit tests for base adapter interface."""
import pytest
from abc import ABC, abstractmethod
from mahavishnu.core.adapters.base import OrchestratorAdapter


def test_orchestrator_adapter_is_abstract():
    """Test that OrchestratorAdapter is an abstract base class."""
    assert issubclass(OrchestratorAdapter, ABC)

    # Cannot instantiate abstract class
    with pytest.raises(TypeError):
        OrchestratorAdapter()


def test_adapter_has_required_methods():
    """Test that OrchestratorAdapter defines required abstract methods."""
    assert hasattr(OrchestratorAdapter, 'execute')
    assert hasattr(OrchestratorAdapter, 'get_health')

    # Check that methods are marked as abstract
    assert getattr(OrchestratorAdapter.execute, '__isabstractmethod__', False)
    assert getattr(OrchestratorAdapter.get_health, '__isabstractmethod__', False)
