"""Unit tests for configuration validation."""
import pytest
from mahavishnu.core.config import MahavishnuSettings


def test_default_config_values():
    """Test that default configuration values are set correctly."""
    config = MahavishnuSettings()
    
    assert config.repos_path == "repos.yaml"
    assert config.max_concurrent_workflows == 10
    assert config.prefect_enabled is True
    assert config.llamaindex_enabled is True
    assert config.agno_enabled is True
    assert config.qc_enabled is True
    assert config.qc_min_score == 80
    assert config.session_enabled is True
    assert config.checkpoint_interval == 60
    assert config.retry_max_attempts == 3
    assert config.retry_base_delay == 1.0
    assert config.circuit_breaker_threshold == 5
    assert config.timeout_per_repo == 300
    assert config.metrics_enabled is True
    assert config.tracing_enabled is True
    assert config.otlp_endpoint == "http://localhost:4317"
    assert config.auth_enabled is False


def test_config_custom_values():
    """Test that custom configuration values are respected."""
    config = MahavishnuSettings(
        repos_path="/custom/path.yaml",
        max_concurrent_workflows=20,
        qc_min_score=90
    )
    
    assert config.repos_path == "/custom/path.yaml"
    assert config.max_concurrent_workflows == 20
    assert config.qc_min_score == 90


def test_config_validation_bounds():
    """Test that configuration validation enforces bounds."""
    # Test qc_min_score bounds
    with pytest.raises(ValueError):
        MahavishnuSettings(qc_min_score=-1)
    
    with pytest.raises(ValueError):
        MahavishnuSettings(qc_min_score=101)
    
    # Test checkpoint_interval bounds
    with pytest.raises(ValueError):
        MahavishnuSettings(checkpoint_interval=5)
    
    with pytest.raises(ValueError):
        MahavishnuSettings(checkpoint_interval=601)
    
    # Test retry_max_attempts bounds
    with pytest.raises(ValueError):
        MahavishnuSettings(retry_max_attempts=0)
    
    with pytest.raises(ValueError):
        MahavishnuSettings(retry_max_attempts=11)
    
    # Test retry_base_delay bounds
    with pytest.raises(ValueError):
        MahavishnuSettings(retry_base_delay=0.05)
    
    with pytest.raises(ValueError):
        MahavishnuSettings(retry_base_delay=61.0)
    
    # Test circuit_breaker_threshold bounds
    with pytest.raises(ValueError):
        MahavishnuSettings(circuit_breaker_threshold=0)
    
    with pytest.raises(ValueError):
        MahavishnuSettings(circuit_breaker_threshold=101)
    
    # Test timeout_per_repo bounds
    with pytest.raises(ValueError):
        MahavishnuSettings(timeout_per_repo=25)
    
    with pytest.raises(ValueError):
        MahavishnuSettings(timeout_per_repo=3601)