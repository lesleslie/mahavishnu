"""Unit tests for configuration validation."""

import pytest

from mahavishnu.core.config import (
    AdapterRegistryConfig,
    AgnoMemoryConfig,
    AuthConfig,
    DependencyConfig,
    GoalParsingConfig,
    GoalTeamsConfig,
    GoalTeamsFeatureFlags,
    GoalTeamsLimitsConfig,
    HealthConfig,
    HNSWIndexConfig,
    IntegrationConfig,
    LLMConfig,
    MahavishnuSettings,
    MonitoringConfig,
    ObservabilityConfig,
    OneiricMCPConfig,
    PoolConfig,
    PrefectConfig,
    QualityControlConfig,
    ResilienceConfig,
    SessionBuddyPollingConfig,
    SessionConfig,
    SubscriptionAuthConfig,
    WorkerConfig,
)


def test_default_config_values():
    """Test that default configuration values are set correctly."""
    config = MahavishnuSettings()

    assert config.repos_path == "settings/ecosystem.yaml"
    assert config.max_concurrent_workflows == 10
    assert config.adapters.prefect_enabled is True
    assert config.adapters.llamaindex_enabled is True  # Re-enabled 2026-02-23 with llama-index 0.14.x
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
    # Startup-critical dependency defaults
    assert config.health.dependencies["session_buddy"].required is True
    assert config.health.dependencies["akosha"].required is False
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


# ============================================================================
# Additional Pydantic Model Tests
# ============================================================================


class TestAuthConfigValidation:
    """Test AuthConfig validator."""

    def test_disabled_without_secret(self):
        cfg = AuthConfig()
        assert cfg.enabled is False
        assert cfg.secret is None

    def test_enabled_with_secret(self):
        cfg = AuthConfig(enabled=True, secret="s3cret-key")
        assert cfg.enabled is True

    def test_enabled_without_secret_raises(self):
        with pytest.raises(Exception, match="secret must be set"):
            AuthConfig(enabled=True)

    def test_algorithm_default(self):
        cfg = AuthConfig()
        assert cfg.algorithm == "HS256"

    def test_expire_minutes_range(self):
        with pytest.raises(Exception):
            AuthConfig(expire_minutes=2)
        with pytest.raises(Exception):
            AuthConfig(expire_minutes=1500)


class TestSubscriptionAuthConfigValidation:
    def test_enabled_requires_secret(self):
        with pytest.raises(Exception, match="secret must be set"):
            SubscriptionAuthConfig(enabled=True)

    def test_disabled_without_secret_ok(self):
        cfg = SubscriptionAuthConfig()
        assert cfg.enabled is False


class TestPoolConfigDefaults:
    def test_defaults(self):
        cfg = PoolConfig()
        assert cfg.enabled is True
        assert cfg.default_type == "mahavishnu"
        assert cfg.routing_strategy == "least_loaded"
        assert cfg.min_workers == 1
        assert cfg.max_workers == 10

    def test_min_workers_range(self):
        with pytest.raises(Exception):
            PoolConfig(min_workers=0)

    def test_max_workers_range(self):
        with pytest.raises(Exception):
            PoolConfig(max_workers=200)


class TestWorkerConfigValidation:
    def test_defaults(self):
        cfg = WorkerConfig()
        assert cfg.enabled is True
        assert cfg.max_concurrent == 10
        assert cfg.default_type == "terminal-qwen"

    def test_max_concurrent_range(self):
        with pytest.raises(Exception):
            WorkerConfig(max_concurrent=0)
        with pytest.raises(Exception):
            WorkerConfig(max_concurrent=200)


class TestOneiricMCPConfigValidation:
    def test_defaults(self):
        cfg = OneiricMCPConfig()
        assert cfg.enabled is False
        assert cfg.base_url == "http://localhost:8683/mcp"
        assert cfg.token is None

    def test_custom_base_url_and_token(self):
        cfg = OneiricMCPConfig(base_url="http://dhara.example/mcp", token="secret")
        assert cfg.base_url == "http://dhara.example/mcp"
        assert cfg.token == "secret"

    def test_cache_ttl_range(self):
        with pytest.raises(Exception):
            OneiricMCPConfig(cache_ttl_sec=3601)


class TestHealthConfigValidation:
    def test_defaults(self):
        cfg = HealthConfig()
        assert cfg.enabled is True
        assert cfg.check_timeout_seconds == 5
        assert cfg.dependencies == {}

    def test_with_dependencies(self):
        cfg = HealthConfig(dependencies={
            "session_buddy": DependencyConfig(port=8678),
            "akosha": DependencyConfig(port=8682, required=False),
        })
        assert "session_buddy" in cfg.dependencies
        assert cfg.dependencies["akosha"].required is False


class TestDependencyConfigValidation:
    def test_defaults(self):
        cfg = DependencyConfig()
        assert cfg.host == "localhost"
        assert cfg.port == 8080
        assert cfg.required is True
        assert cfg.timeout_seconds == 30

    def test_port_range(self):
        with pytest.raises(Exception):
            DependencyConfig(port=0)
        with pytest.raises(Exception):
            DependencyConfig(port=70000)


class TestSessionBuddyPollingConfigValidation:
    def test_defaults(self):
        cfg = SessionBuddyPollingConfig()
        assert cfg.enabled is False
        assert cfg.interval_seconds == 30
        assert "get_activity_summary" in cfg.metrics_to_collect

    def test_interval_range(self):
        with pytest.raises(Exception):
            SessionBuddyPollingConfig(interval_seconds=3)


class TestHNSWIndexConfigValidation:
    def test_defaults(self):
        cfg = HNSWIndexConfig()
        assert cfg.m == 16
        assert cfg.ef_construction == 64
        assert cfg.ef_search == 40

    def test_m_range(self):
        with pytest.raises(Exception):
            HNSWIndexConfig(m=2)
        with pytest.raises(Exception):
            HNSWIndexConfig(m=60)

    def test_ef_construction_range(self):
        with pytest.raises(Exception):
            HNSWIndexConfig(ef_construction=10)

    def test_ef_search_range(self):
        with pytest.raises(Exception):
            HNSWIndexConfig(ef_search=5)


class TestGoalTeamsConfigValidation:
    def test_defaults(self):
        cfg = GoalTeamsConfig()
        assert cfg.enabled is False
        assert isinstance(cfg.goal_parsing, GoalParsingConfig)
        assert isinstance(cfg.limits, GoalTeamsLimitsConfig)
        assert isinstance(cfg.feature_flags, GoalTeamsFeatureFlags)


class TestGoalParsingConfigValidation:
    def test_defaults(self):
        cfg = GoalParsingConfig()
        assert cfg.min_length == 10
        assert cfg.max_length == 2000

    def test_min_length_range(self):
        with pytest.raises(Exception):
            GoalParsingConfig(min_length=0)


class TestGoalTeamsLimitsConfigValidation:
    def test_defaults(self):
        cfg = GoalTeamsLimitsConfig()
        assert cfg.max_teams_per_user == 10
        assert cfg.team_ttl_hours == 24

    def test_ttl_range(self):
        with pytest.raises(Exception):
            GoalTeamsLimitsConfig(team_ttl_hours=200)


class TestPrefectConfigValidation:
    def test_workspace_requires_api_key(self):
        with pytest.raises(Exception, match="api_key must be set"):
            PrefectConfig(workspace="myorg/myspace")

    def test_workspace_with_api_key_ok(self):
        cfg = PrefectConfig(workspace="myorg/myspace", api_key="pk_xxx")
        assert cfg.workspace == "myorg/myspace"


class TestIntegrationConfigDefaults:
    def test_defaults(self):
        cfg = IntegrationConfig()
        assert cfg.pydantic_ai_enabled is False
        assert cfg.openclaw_webhooks_enabled is True
        assert cfg.cross_platform_memory_enabled is True


class TestAdapterRegistryConfigDefaults:
    def test_defaults(self):
        cfg = AdapterRegistryConfig()
        assert cfg.enabled is True
        assert "mahavishnu.adapters.*" in cfg.allowlist_patterns
        assert cfg.cache_ttl_seconds == 300


class TestAgnoMemoryConfigValidation:
    def test_defaults(self):
        cfg = AgnoMemoryConfig()
        assert cfg.enabled is True
        assert cfg.db_path == "data/agno.db"
        assert cfg.num_history_runs == 10

    def test_history_runs_range(self):
        with pytest.raises(Exception):
            AgnoMemoryConfig(num_history_runs=200)


class TestResilienceConfigDefaults:
    def test_defaults(self):
        cfg = ResilienceConfig()
        assert cfg.retry_max_attempts == 3
        assert cfg.circuit_breaker_threshold == 5
        assert cfg.timeout_per_repo == 300


class TestObservabilityConfigDefaults:
    def test_defaults(self):
        cfg = ObservabilityConfig()
        assert cfg.metrics_enabled is True
        assert cfg.tracing_enabled is True
        assert cfg.otlp_endpoint == "http://localhost:4317"


class TestQualityControlConfigDefaults:
    def test_defaults(self):
        cfg = QualityControlConfig()
        assert cfg.enabled is True
        assert cfg.min_score == 80
        assert "linting" in cfg.checks


class TestSessionConfigDefaults:
    def test_defaults(self):
        cfg = SessionConfig()
        assert cfg.enabled is True
        assert cfg.checkpoint_interval == 60


class TestMonitoringConfigDefaults:
    def test_defaults(self):
        cfg = MonitoringConfig()
        assert cfg.routing_metrics_port == 9091
        assert cfg.routing_metrics_enabled is True


class TestLLMConfigDefaults:
    def test_defaults(self):
        cfg = LLMConfig()
        assert cfg.model == "nomic-embed-text"
        assert cfg.ollama_base_url == "http://localhost:11434"


class TestMahavishnuSettingsReposPath:
    def test_repos_path_expands_tilde(self):
        cfg = MahavishnuSettings(repos_path="~/custom.yaml")
        assert "~" not in cfg.repos_path
