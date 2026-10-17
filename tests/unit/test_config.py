"""Unit tests for configuration validation."""

from pathlib import Path

import pytest
import yaml

from mahavishnu.core.config import (
    AdapterRegistryConfig,
    AgnoMemoryConfig,
    AuthConfig,
    DependencyConfig,
    EventBridgeConfig,
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
    get_settings,
    reset_settings,
)


def test_default_config_values():
    """Test that default configuration values are set correctly."""
    config = MahavishnuSettings()

    assert config.repos_path == "settings/ecosystem.yaml"
    assert config.max_concurrent_workflows == 10
    assert config.adapters.prefect_enabled is True
    assert (
        config.adapters.llamaindex_enabled is True
    )  # Re-enabled 2026-02-23 with llama-index 0.14.x
    assert config.adapters.agno_enabled is True  # Enabled in settings/mahavishnu.yaml
    assert config.qc.enabled is False  # OFF by default; opt-in for production (see QualityControlConfig docstring)
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


def test_health_dependencies_loaded_from_mahavishnu_yaml() -> None:
    """YAML-derived health.dependencies must be loaded by get_settings().

    ``MahavishnuSettings()`` (no args) only materialises field defaults —
    it does NOT load the YAML layer. The previous in-line assertions
    on ``config.health.dependencies["session_buddy"]`` and
    ``config.health.dependencies["akosha"]`` were KeyErroring because
    the dict was empty under bare construction. The actual production
    path is ``get_settings(project_root=...)`` which routes through
    Oneiric's ``load_settings`` and populates
    ``health.dependencies`` from ``settings/mahavishnu.yaml``
    (lines 412-436: session_buddy required, akosha optional).

    This test was split out per the TDD rule "one behavior per test"
    — ``test_default_config_values`` covers field defaults; this test
    covers the YAML integration that turns the empty dict into the
    required-shape dict.
    """
    project_root = Path(__file__).resolve().parents[2]
    reset_settings()  # ensure the cached instance reflects the real project
    settings = get_settings(project_root=project_root)
    assert "session_buddy" in settings.health.dependencies
    assert settings.health.dependencies["session_buddy"].required is True
    assert "akosha" in settings.health.dependencies
    assert settings.health.dependencies["akosha"].required is False


def test_eventbridge_default_factory_resolves() -> None:
    """Regression: EventBridgeConfig default_factory must resolve at module-import time.

    Pydantic evaluates ``default_factory=EventBridgeConfig`` when constructing
    ``MahavishnuSettings()`` and the nested ``GoalTeamsFeatureFlags.eventbridge``
    field. If ``EventBridgeConfig`` is declared *after* either consumer class
    in ``mahavishnu/core/config.py``, pydantic raises ``NameError: name
    'EventBridgeConfig' is not defined`` at import time. This test would have
    caught the 2026-07-13 launchd crash where class reordering broke the
    EventBridge publisher wiring.
    """
    settings = MahavishnuSettings()
    flags = settings.goal_teams.feature_flags

    assert isinstance(settings.eventbridge, EventBridgeConfig)
    assert isinstance(flags.eventbridge, EventBridgeConfig)


def test_config_custom_values():
    """Test that custom configuration values are respected."""
    config = MahavishnuSettings(
        repos_path="/custom/path.yaml", max_concurrent_workflows=20, qc={"min_score": 90}
    )

    assert config.repos_path == "/custom/path.yaml"
    assert config.max_concurrent_workflows == 20
    assert config.qc.min_score == 90


def test_models_yaml_defaults_to_minimax() -> None:
    models_path = Path(__file__).resolve().parents[2] / "settings" / "models.yaml"
    data = yaml.safe_load(models_path.read_text(encoding="utf-8"))

    assert data["default_provider"] == "minimax"
    assert data["fallback_chain"] == ["minimax", "llama_server"]
    assert data["minimax"]["api_key"] == "${MINIMAX_API_KEY}"
    assert data["minimax"]["base_url"] == "https://api.minimax.io/v1"
    assert data["minimax"]["task_routing"]["CODE_GENERATION"] == "MiniMax-M3"
    # SWARM/QUICK/AGENT_LOOP/CREATIVE/GENERAL all route to MiniMax-M3 —
    # minimax's API does not expose a distinct MiniMax-M3-highspeed variant
    # (verified 2026-09-16; minimax returns error 2013 "unknown model").
    # For a real speed differential, override these via settings/local.yaml
    # to point at MiniMax-M2.7-highspeed.
    assert data["minimax"]["task_routing"]["SWARM"] == "MiniMax-M3"
    assert data["minimax"]["task_routing"]["QUICK"] == "MiniMax-M3"


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
        assert cfg.default_type == "terminal-claude"

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
        cfg = OneiricMCPConfig(base_url="http://mcp.example/mcp", token="secret")
        assert cfg.base_url == "http://mcp.example/mcp"
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
        cfg = HealthConfig(
            dependencies={
                "session_buddy": DependencyConfig(port=8678),
                "akosha": DependencyConfig(port=8682, required=False),
            }
        )
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
        assert cfg.enabled is False  # OFF by default; opt-in for production (see docstring)
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
        assert cfg.model == "qwen3.5"
        assert cfg.base_url == "http://localhost:8081"


class TestMahavishnuSettingsReposPath:
    def test_repos_path_expands_tilde(self):
        cfg = MahavishnuSettings(repos_path="~/custom.yaml")
        assert "~" not in cfg.repos_path


# ============================================================================
# BifrostConfig — Phase A (v1.5 Bifrost spec §5.1) + Phase G (REQ-007)
# ----------------------------------------------------------------------------
# The BifrostConfig class is the first-class settings class mounted on
# MahavishnuSettings (per the PiPoolSettings precedent at
# config.py:2961+). The 11 Phase A fields cover the cloud-tier wiring
# (Bifrost gateway URL, anthropic-compatible URL, caller_id, cache,
# AI-CLI opt-in flags); the 3 Phase G fields cover the local
# llama-server provider (local_provider_enabled / url / model).
#
# Total: 14 fields. The class uses model_config = ConfigDict(extra="forbid")
# (the crackerjack hard-limit) and each field uses
# Field(default=..., description="...") per the ChangepointConfig.detector
# precedent.
# ============================================================================


class TestBifrostConfigSchema:
    """Phase A (6 tests) + Phase G (5 tests) = 11 tests total."""

    def test_defaults(self) -> None:
        """Every field matches the spec §5.1 / plan §5 Phase A defaults."""
        from mahavishnu.core.config import BifrostConfig

        cfg = BifrostConfig()

        # Phase A fields (11)
        assert cfg.enabled is False
        assert cfg.base_url == "http://127.0.0.1:8471"
        assert cfg.anthropic_base_url == "http://127.0.0.1:8471/anthropic"
        assert cfg.caller_id == "mahavishnu"
        assert cfg.cache_mode == "off"
        assert cfg.cache_ttl_seconds == 300
        assert cfg.request_timeout_seconds == 30
        assert cfg.route_claude_code is False
        assert cfg.route_qwen_code is False
        assert cfg.qwen_env_var == "OPENAI_BASE_URL"
        assert cfg.auth_env == "BIFROST_API_KEY"

        # Phase G fields (3)
        assert cfg.local_provider_enabled is True
        assert cfg.local_provider_url == "http://127.0.0.1:8081"
        assert cfg.local_provider_model == "qwen3-8b-q4_k_m"

    def test_env_prefix_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """``MAHAVISHNU_BIFROST__enabled=true`` overrides yaml.

        ``BifrostConfig`` is a ``BaseModel`` (not ``BaseSettings``), so
        env-var reading happens at the ``MahavishnuSettings`` mount
        (``env_prefix="MAHAVISHNU_"`` + ``env_nested_delimiter="__"``
        routes ``MAHAVISHNU_BIFROST__<FIELD>`` to the nested mount).
        Asserting on ``MahavishnuSettings().bifrost.enabled`` exercises
        the real production path; constructing ``BifrostConfig()``
        directly only ever returns the field defaults.
        """
        from mahavishnu.core.config import MahavishnuSettings

        monkeypatch.setenv("MAHAVISHNU_BIFROST__enabled", "true")
        settings = MahavishnuSettings()
        assert settings.bifrost.enabled is True

    def test_extra_forbid_rejects_unknown_field(self) -> None:
        """Stray ``bifrost.foo`` is rejected by ``extra="forbid"``."""
        from pydantic import ValidationError

        from mahavishnu.core.config import BifrostConfig

        with pytest.raises(ValidationError):
            BifrostConfig.model_validate(
                {
                    "enabled": True,
                    "base_url": "http://127.0.0.1:8471",
                    "stray_field": "should be rejected",
                }
            )

    def test_validation_rejects_invalid_cache_mode(self) -> None:
        """``Literal["off", "direct", "semantic"]`` is enforced."""
        from pydantic import ValidationError

        from mahavishnu.core.config import BifrostConfig

        with pytest.raises(ValidationError):
            BifrostConfig.model_validate({"cache_mode": "rabbit"})

    def test_mount_uses_field_default_factory(self) -> None:
        """The BifrostConfig mount on MahavishnuSettings uses default_factory.

        The mount is ``bifrost: BifrostConfig = Field(default_factory=BifrostConfig, ...)``.
        When no env / yaml override is in effect, the field returns a
        ``BifrostConfig`` instance with the spec defaults (not ``None``,
        not a raw dict). The previous version of this assertion
        compared against ``type(MahavishnuSettings())`` (i.e. the
        ``MahavishnuSettings`` *class* itself) which is always False
        for a BifrostConfig mount — the bug was checking the wrong type.
        """
        from mahavishnu.core.config import BifrostConfig

        settings = MahavishnuSettings()
        assert isinstance(settings.bifrost, BifrostConfig), (
            "BifrostConfig must be mounted, not None or raw dict"
        )

    # Note: a previous `test_env_overrides_local_yaml` here was
    # deleted in the 2026-10-17 cleanup. It was a tautology
    # (``assert cfg.enabled in (True, False)``) that did not actually
    # test env-var precedence; the meaningful env-var coverage now
    # lives in :meth:`test_env_prefix_override` and the two
    # ``test_local_provider_*_env_override`` tests above.

    # ----- Phase G tests -----

    def test_local_provider_enabled_default(self) -> None:
        """``local_provider_enabled`` defaults to True (the runtime opt-in)."""
        from mahavishnu.core.config import BifrostConfig

        cfg = BifrostConfig()
        assert cfg.local_provider_enabled is True

    def test_local_provider_url_default(self) -> None:
        """``local_provider_url`` defaults to ``http://127.0.0.1:8081``."""
        from mahavishnu.core.config import BifrostConfig

        cfg = BifrostConfig()
        assert cfg.local_provider_url == "http://127.0.0.1:8081"

    def test_local_provider_model_default(self) -> None:
        """``local_provider_model`` defaults to ``qwen3-8b-q4_k_m``."""
        from mahavishnu.core.config import BifrostConfig

        cfg = BifrostConfig()
        assert cfg.local_provider_model == "qwen3-8b-q4_k_m"

    def test_local_provider_enabled_env_override(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``MAHAVISHNU_BIFROST__local_provider_enabled=false`` overrides yaml.

        Same caveat as :meth:`test_env_prefix_override`: the env var
        is read at the ``MahavishnuSettings`` mount, not by
        ``BifrostConfig`` itself.
        """
        from mahavishnu.core.config import MahavishnuSettings

        monkeypatch.setenv("MAHAVISHNU_BIFROST__local_provider_enabled", "false")
        settings = MahavishnuSettings()
        assert settings.bifrost.local_provider_enabled is False

    def test_local_provider_url_env_override(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``MAHAVISHNU_BIFROST__local_provider_url`` overrides yaml.

        Same caveat as :meth:`test_env_prefix_override`: the env var
        is read at the ``MahavishnuSettings`` mount, not by
        ``BifrostConfig`` itself.
        """
        from mahavishnu.core.config import MahavishnuSettings

        monkeypatch.setenv(
            "MAHAVISHNU_BIFROST__local_provider_url", "http://localhost:9999"
        )
        settings = MahavishnuSettings()
        assert settings.bifrost.local_provider_url == "http://localhost:9999"
