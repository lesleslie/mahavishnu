"""Unit tests for configuration validation."""

import pytest

from mahavishnu.core.config import MahavishnuSettings


def test_default_config_values():
    """Test that default configuration values are set correctly."""
    config = MahavishnuSettings()

    assert config.repos_path == "settings/ecosystem.yaml"
    assert config.max_concurrent_workflows == 10
    assert config.adapters.prefect_enabled is True
    assert config.adapters.llamaindex_enabled is True  # Enabled in settings/mahavishnu.yaml
    assert config.adapters.agno_enabled is True  # Enabled in settings/mahavishnu.yaml
    assert config.qc.enabled is True
    assert config.qc.min_score == 80
    assert config.session.enabled is True
    assert config.session.checkpoint_interval == 60
    assert config.resilience.retry_max_attempts == 3
    assert config.resilience.retry_base_delay == 1.0
    assert config.resilience.circuit_breaker_threshold == 5
    assert config.resilience.timeout_per_repo == 300
    assert config.observability.metrics_enabled is True
    assert config.observability.tracing_enabled is True
    assert config.observability.otlp_endpoint == "http://localhost:4317"
    assert config.auth.enabled is False
    # SECURITY: Empty connection string by default, not default credentials
    assert config.otel_storage.connection_string == ""


def test_config_custom_values():
    """Test that custom configuration values are respected."""
    config = MahavishnuSettings(
        repos_path="/custom/path.yaml", max_concurrent_workflows=20, qc={"min_score": 90}
    )

    assert config.repos_path == "/custom/path.yaml"
    assert config.max_concurrent_workflows == 20
    assert config.qc.min_score == 90


def test_config_validation_bounds():
    """Test that configuration validation enforces bounds."""
    # Test qc_min_score bounds
    with pytest.raises(ValueError):
        MahavishnuSettings(qc={"min_score": -1})

    with pytest.raises(ValueError):
        MahavishnuSettings(qc={"min_score": 101})

    # Test checkpoint_interval bounds
    with pytest.raises(ValueError):
        MahavishnuSettings(session={"checkpoint_interval": 5})

    with pytest.raises(ValueError):
        MahavishnuSettings(session={"checkpoint_interval": 601})

    # Test retry_max_attempts bounds
    with pytest.raises(ValueError):
        MahavishnuSettings(resilience={"retry_max_attempts": 0})

    with pytest.raises(ValueError):
        MahavishnuSettings(resilience={"retry_max_attempts": 11})

    # Test retry_base_delay bounds
    with pytest.raises(ValueError):
        MahavishnuSettings(resilience={"retry_base_delay": 0.05})

    with pytest.raises(ValueError):
        MahavishnuSettings(resilience={"retry_base_delay": 61.0})

    # Test circuit_breaker_threshold bounds
    with pytest.raises(ValueError):
        MahavishnuSettings(resilience={"circuit_breaker_threshold": 0})

    with pytest.raises(ValueError):
        MahavishnuSettings(resilience={"circuit_breaker_threshold": 101})

    # Test timeout_per_repo bounds
    with pytest.raises(ValueError):
        MahavishnuSettings(resilience={"timeout_per_repo": 25})

    with pytest.raises(ValueError):
        MahavishnuSettings(resilience={"timeout_per_repo": 3601})


class TestOTelStorageConnectionStringSecurity:
    """Security tests for OTel storage connection string validation."""

    def test_empty_connection_string_when_disabled(self):
        """Test that empty connection string is allowed when storage is disabled."""
        config = MahavishnuSettings(otel_storage={"enabled": False, "connection_string": ""})
        assert config.otel_storage.connection_string == ""

    def test_empty_connection_string_rejected_when_enabled(self):
        """Test that empty connection string is rejected when storage is enabled."""
        with pytest.raises(ValueError, match="connection_string must be set"):
            MahavishnuSettings(otel_storage={"enabled": True, "connection_string": ""})

    def test_default_password_rejected(self):
        """Test that connection string with 'password@' is rejected."""
        with pytest.raises(ValueError, match="contains insecure default credentials"):
            MahavishnuSettings(
                otel_storage={
                    "enabled": True,
                    "connection_string": "postgresql://postgres:password@localhost:5432/otel_traces",
                }
            )

    def test_postgres_postgres_rejected(self):
        """Test that postgres:postgres@ credentials are rejected."""
        with pytest.raises(ValueError, match="contains insecure default credentials"):
            MahavishnuSettings(
                otel_storage={
                    "enabled": True,
                    "connection_string": "postgresql://postgres:postgres@localhost:5432/otel_traces",
                }
            )

    def test_explicit_default_password_rejected(self):
        """Test that explicit postgres:password@ is rejected."""
        with pytest.raises(ValueError, match="contains insecure default credentials"):
            MahavishnuSettings(
                otel_storage={
                    "enabled": True,
                    "connection_string": "postgresql://postgres:password@localhost:5432/otel_traces",
                }
            )

    def test_admin_admin_rejected(self):
        """Test that admin:admin@ credentials are rejected."""
        with pytest.raises(ValueError, match="contains insecure default credentials"):
            MahavishnuSettings(
                otel_storage={
                    "enabled": True,
                    "connection_string": "postgresql://admin:admin@localhost:5432/otel_traces",
                }
            )

    def test_root_root_rejected(self):
        """Test that root:root@ credentials are rejected."""
        with pytest.raises(ValueError, match="contains insecure default credentials"):
            MahavishnuSettings(
                otel_storage={
                    "enabled": True,
                    "connection_string": "postgresql://root:root@localhost:5432/otel_traces",
                }
            )

    def test_test_test_rejected(self):
        """Test that test:test@ credentials are rejected."""
        with pytest.raises(ValueError, match="contains insecure default credentials"):
            MahavishnuSettings(
                otel_storage={
                    "enabled": True,
                    "connection_string": "postgresql://test:test@localhost:5432/otel_traces",
                }
            )

    def test_case_insensitive_pattern_matching(self):
        """Test that pattern matching is case-insensitive."""
        with pytest.raises(ValueError, match="contains insecure default credentials"):
            MahavishnuSettings(
                otel_storage={
                    "enabled": True,
                    "connection_string": "postgresql://postgres:PASSWORD@localhost:5432/otel_traces",
                }
            )

        with pytest.raises(ValueError, match="contains insecure default credentials"):
            MahavishnuSettings(
                otel_storage={
                    "enabled": True,
                    "connection_string": "postgresql://POSTGRES:POSTGRES@localhost:5432/otel_traces",
                }
            )

    def test_invalid_scheme_rejected(self):
        """Test that non-PostgreSQL schemes are rejected."""
        with pytest.raises(ValueError, match="must use postgresql:// or postgres:// scheme"):
            MahavishnuSettings(
                otel_storage={
                    "enabled": True,
                    "connection_string": "mysql://user:pass@localhost:3306/db",
                }
            )

        with pytest.raises(ValueError, match="must use postgresql:// or postgres:// scheme"):
            MahavishnuSettings(
                otel_storage={
                    "enabled": True,
                    "connection_string": "mongodb://user:pass@localhost:27017/db",
                }
            )

    def test_postgres_scheme_accepted(self):
        """Test that postgres:// scheme (short form) is accepted."""
        config = MahavishnuSettings(
            otel_storage={
                "enabled": True,
                "connection_string": "postgres://user:StrongPassword123!@localhost:5432/otel_traces",
            }
        )
        assert (
            config.otel_storage.connection_string
            == "postgres://user:StrongPassword123!@localhost:5432/otel_traces"
        )

    def test_missing_at_separator_rejected(self):
        """Test that connection string without @ separator is rejected."""
        with pytest.raises(ValueError, match="missing '@' separator"):
            MahavishnuSettings(
                otel_storage={
                    "enabled": True,
                    "connection_string": "postgresql://localhost:5432/otel_traces",
                }
            )

    def test_missing_database_rejected(self):
        """Test that connection string without database name is rejected."""
        with pytest.raises(ValueError, match="missing database name"):
            MahavishnuSettings(
                otel_storage={
                    "enabled": True,
                    "connection_string": "postgresql://user:pass@localhost:5432",
                }
            )

    def test_valid_connection_string_accepted(self):
        """Test that valid connection string with strong password is accepted."""
        config = MahavishnuSettings(
            otel_storage={
                "enabled": True,
                "connection_string": "postgresql://otel_user:xK9$mP2@nL5*qR7!localhost:5432/otel_traces",
            }
        )
        assert (
            config.otel_storage.connection_string
            == "postgresql://otel_user:xK9$mP2@nL5*qR7!localhost:5432/otel_traces"
        )

    def test_valid_connection_string_with_port(self):
        """Test that valid connection string with custom port is accepted."""
        config = MahavishnuSettings(
            otel_storage={
                "enabled": True,
                "connection_string": "postgresql://otel_user:SecurePass456@db.example.com:5433/otel_traces",
            }
        )
        assert (
            config.otel_storage.connection_string
            == "postgresql://otel_user:SecurePass456@db.example.com:5433/otel_traces"
        )

    def test_strong_password_with_special_characters(self):
        """Test that strong passwords with special characters are accepted."""
        config = MahavishnuSettings(
            otel_storage={
                "enabled": True,
                "connection_string": "postgresql://user:P@ssw0rd!#$@localhost:5432/db",
            }
        )
        assert "P@ssw0rd!#$@" in config.otel_storage.connection_string

    def test_password_not_containing_insecure_patterns(self):
        """Test that passwords containing but not matching insecure patterns are accepted."""
        # "password" as part of a longer secure password should be allowed
        config = MahavishnuSettings(
            otel_storage={
                "enabled": True,
                "connection_string": "postgresql://user:MypasswordIsVeryLong456!@localhost:5432/db",
            }
        )
        # This should work because it's not exactly "password@"
        assert "MypasswordIsVeryLong456!@" in config.otel_storage.connection_string

    def test_connection_string_with_unix_socket(self):
        """Test that Unix socket connection strings are validated."""
        # Unix socket paths should still pass format validation
        config = MahavishnuSettings(
            otel_storage={
                "enabled": True,
                "connection_string": "postgresql://user:SecurePass@%2Fvar%2Frun%2Fpostgresql:5432/db",
            }
        )
        assert (
            config.otel_storage.connection_string
            == "postgresql://user:SecurePass@%2Fvar%2Frun%2Fpostgresql:5432/db"
        )

    def test_connection_string_with_ssl_mode(self):
        """Test that connection strings with SSL parameters are accepted."""
        config = MahavishnuSettings(
            otel_storage={
                "enabled": True,
                "connection_string": "postgresql://user:SecurePass123@localhost:5432/db?sslmode=require",
            }
        )
        assert (
            config.otel_storage.connection_string
            == "postgresql://user:SecurePass123@localhost:5432/db?sslmode=require"
        )

    def test_environment_variable_override_description(self):
        """Test that error messages reference environment variable for setup."""
        with pytest.raises(ValueError, match="MAHAVISHNU_OTEL_STORAGE__CONNECTION_STRING"):
            MahavishnuSettings(otel_storage={"enabled": True, "connection_string": ""})

        with pytest.raises(ValueError, match="MAHAVISHNU_OTEL_STORAGE__CONNECTION_STRING"):
            MahavishnuSettings(
                otel_storage={
                    "enabled": True,
                    "connection_string": "postgresql://postgres:password@localhost:5432/db",
                }
            )
