"""Regression tests for nested config source resolution.

Tracks the bug described in
``docs/followups/2026-06-29-pydantic-settings-source-resolution.md``.

pydantic-settings' default ``_settings_build_values`` merges sources
with ``state = deep_update(source_state, state)`` — which makes the
*earlier* source win. The override on ``MahavishnuSettings._settings_build_values``
swaps the merge direction so later sources (env > local.yaml >
mahavishnu.yaml > defaults) take precedence, and pushes the
``InitSettingsSource`` to the end of the source list so init kwargs
remain the documented highest-precedence source.

These tests pin the contract: every nested config subtree must accept
env-var and ``settings/local.yaml`` overrides, not just the few that
happen to be absent from ``settings/mahavishnu.yaml``.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import pytest
import yaml

from mahavishnu.core.config import MahavishnuSettings

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# Field-probe table
# ---------------------------------------------------------------------------
# Each row: (subtree, leaf, env-var-suffix, raw-env-value).
# Pick a primitive (str/bool/int) so we can set it via env var and
# assert via attribute access. Pick subtrees that DO appear in
# settings/mahavishnu.yaml so we exercise the actual bug, not just
# "value not present in any source".

FIELD_PROBES: list[tuple[str, str, str, str]] = [
    # The canonical repro from the followup:
    ("opensearch", "endpoint", "OPENSEARCH__ENDPOINT", "http://probe:9200"),
    ("opensearch", "use_ssl", "OPENSEARCH__USE_SSL", "false"),
    ("opensearch", "verify_certs", "OPENSEARCH__VERIFY_CERTS", "false"),
    ("opensearch", "ssl_assert_hostname", "OPENSEARCH__SSL_ASSERT_HOSTNAME", "false"),
    # Subtree absent from mahavishnu.yaml — must still be settable via env:
    ("agno", "enabled", "AGNO__ENABLED", "false"),
    # Other in-mahavishnu.yaml subtrees:
    ("auth", "algorithm", "AUTH__ALGORITHM", "RS256"),
    ("prefect", "enabled", "PREFECT__ENABLED", "false"),
    ("otel_ingester", "similarity_threshold", "OTEL_INGESTER__SIMILARITY_THRESHOLD", "0.5"),
    ("pools", "min_workers", "POOLS__MIN_WORKERS", "7"),
    ("pools", "routing_strategy", "POOLS__ROUTING_STRATEGY", "round_robin"),
    ("qc", "min_score", "QC__MIN_SCORE", "42"),
    ("resilience", "retry_max_attempts", "RESILIENCE__RETRY_MAX_ATTEMPTS", "9"),
    ("session", "enabled", "SESSION__ENABLED", "false"),
    ("workers", "max_concurrent", "WORKERS__MAX_CONCURRENT", "3"),
    ("llm", "model", "LLM__MODEL", "test-model"),
    ("hatchet", "namespace", "HATCHET__NAMESPACE", "probe-ns"),
    ("oneiric_mcp", "base_url", "ONEIRIC_MCP__BASE_URL", "http://probe-dhara:8683/mcp"),
    ("adapter_registry", "cache_ttl_seconds", "ADAPTER_REGISTRY__CACHE_TTL_SECONDS", "99"),
    (
        "dhara_state",
        "max_routing_buffer_age_seconds",
        "DHARA_STATE__MAX_ROUTING_BUFFER_AGE_SECONDS",
        "120",
    ),
    ("monitoring", "routing_metrics_enabled", "MONITORING__ROUTING_METRICS_ENABLED", "false"),
    ("monitoring", "routing_metrics_port", "MONITORING__ROUTING_METRICS_PORT", "11111"),
    ("session_buddy_polling", "interval_seconds", "SESSION_BUDDY_POLLING__INTERVAL_SECONDS", "99"),
    ("learning", "enabled", "LEARNING__ENABLED", "true"),
    ("integrations", "pydantic_ai_enabled", "INTEGRATIONS__PYDANTIC_AI_ENABLED", "true"),
    ("integrations", "omo_enabled", "INTEGRATIONS__OMO_ENABLED", "true"),
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """Wipe MAHAVISHNU_* env vars and clear the settings cache per test."""
    for k in list(os.environ):
        if k.startswith("MAHAVISHNU_"):
            monkeypatch.delenv(k, raising=False)
    import mahavishnu.core.config as cfg_mod

    cfg_mod._settings_cache = None
    yield
    cfg_mod._settings_cache = None


# ---------------------------------------------------------------------------
# Parametric: env var wins over YAML default
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("subtree", "leaf", "suffix", "raw"), FIELD_PROBES)
def test_env_var_overrides_yaml_default(
    monkeypatch: pytest.MonkeyPatch,
    subtree: str,
    leaf: str,
    suffix: str,
    raw: str,
) -> None:
    """An env var on any nested subtree must take precedence over YAML defaults.

    Regression for the bug where pydantic-settings' default merge made
    the FIRST source win, so ``settings/mahavishnu.yaml`` masked env-var
    overrides for subtrees that appeared in that file (notably
    opensearch).
    """
    monkeypatch.setenv(f"MAHAVISHNU_{suffix}", raw)

    s = MahavishnuSettings()

    actual = getattr(getattr(s, subtree), leaf)
    if isinstance(actual, bool):
        assert str(actual).lower() == raw.lower(), (
            f"{subtree}.{leaf} = {actual!r}, env var MAHAVISHNU_{suffix}={raw!r} was ignored"
        )
    else:
        assert str(actual) == raw, (
            f"{subtree}.{leaf} = {actual!r}, env var MAHAVISHNU_{suffix}={raw!r} was ignored"
        )


def test_env_var_overrides_opensearch_full_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The exact reproduction from the followup — all four opensearch fields."""
    monkeypatch.setenv("MAHAVISHNU_OPENSEARCH__ENDPOINT", "http://localhost:9200")
    monkeypatch.setenv("MAHAVISHNU_OPENSEARCH__USE_SSL", "false")
    monkeypatch.setenv("MAHAVISHNU_OPENSEARCH__VERIFY_CERTS", "false")
    monkeypatch.setenv("MAHAVISHNU_OPENSEARCH__SSL_ASSERT_HOSTNAME", "false")

    s = MahavishnuSettings()

    assert s.opensearch.endpoint == "http://localhost:9200"
    assert s.opensearch.use_ssl is False
    assert s.opensearch.verify_certs is False
    assert s.opensearch.ssl_assert_hostname is False


# ---------------------------------------------------------------------------
# Two-level deep path
# ---------------------------------------------------------------------------


def test_env_var_overrides_two_level_deep(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two-level-deep path on a nested model: agno.llm.provider."""
    monkeypatch.setenv("MAHAVISHNU_AGNO__LLM__PROVIDER", "anthropic")
    s = MahavishnuSettings()
    assert s.agno.llm.provider == "anthropic"


def test_env_var_overrides_three_level_deep(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Three-level-deep path: hatchet.<field> works through nested models."""
    monkeypatch.setenv("MAHAVISHNU_HATCHET__NAMESPACE", "from-env-3")
    s = MahavishnuSettings()
    assert s.hatchet.namespace == "from-env-3"


# ---------------------------------------------------------------------------
# local.yaml precedence
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("subtree", "leaf", "expected"),
    [
        ("opensearch", "endpoint", "http://from-local:9200"),
        ("opensearch", "use_ssl", False),
        ("opensearch", "verify_certs", False),
        ("auth", "algorithm", "RS256"),
        ("qc", "min_score", 99),
    ],
)
def test_local_yaml_overrides_committed_yaml(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    subtree: str,
    leaf: str,
    expected: str | bool | int,
) -> None:
    """settings/local.yaml must override settings/mahavishnu.yaml for any subtree."""
    _install_yaml(monkeypatch, tmp_path, local_overrides={subtree: {leaf: expected}})

    s = MahavishnuSettings()
    actual = getattr(getattr(s, subtree), leaf)
    if isinstance(expected, bool):
        assert actual is expected
    else:
        assert actual == expected


def test_env_var_wins_over_local_yaml(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Env var must beat settings/local.yaml (highest non-init precedence)."""
    _install_yaml(
        monkeypatch,
        tmp_path,
        local_overrides={
            "opensearch": {
                "endpoint": "http://from-local:9200",
                "use_ssl": False,
            },
        },
    )
    monkeypatch.setenv("MAHAVISHNU_OPENSEARCH__ENDPOINT", "http://from-env:9200")

    s = MahavishnuSettings()
    assert s.opensearch.endpoint == "http://from-env:9200"
    assert s.opensearch.use_ssl is False  # from local.yaml (env did not set)


# ---------------------------------------------------------------------------
# Defaults and init-kwargs precedence (highest + lowest sources)
# ---------------------------------------------------------------------------


def test_init_kwargs_win_over_everything(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """init kwargs remain the documented highest-precedence source."""
    monkeypatch.setenv("MAHAVISHNU_OPENSEARCH__ENDPOINT", "http://from-env:9200")
    s = MahavishnuSettings(opensearch={"endpoint": "http://from-init:9200"})
    assert s.opensearch.endpoint == "http://from-init:9200"


def test_defaults_unchanged_when_no_overrides(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sanity check: with no env vars and no local.yaml present, defaults stand."""
    # Run with an empty dir so the only YAML source is what we install.
    _install_yaml(monkeypatch, tmp_path, main_only=True)

    s = MahavishnuSettings()
    # Defaults from the temporary mahavishnu.yaml we wrote:
    assert s.opensearch.endpoint == "https://default:9200"
    assert s.opensearch.use_ssl is True
    assert s.opensearch.verify_certs is True
    assert s.qc.min_score == 80


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _install_yaml(
    monkeypatch: pytest.MonkeyPatch,
    directory: Path,
    local_overrides: dict[str, Any] | None = None,
    main_only: bool = False,
) -> None:
    """Install a temp settings/mahavishnu.yaml (and optionally local.yaml).

    Rewrites ``settings_customise_sources`` to look in ``directory`` so
    the test gets a hermetic, predictable source order.
    """
    main_yaml = directory / "mahavishnu.yaml"
    main_yaml.write_text(
        yaml.safe_dump(
            {
                "opensearch": {
                    "endpoint": "https://default:9200",
                    "use_ssl": True,
                    "verify_certs": True,
                    "ssl_assert_hostname": True,
                },
                "qc": {"min_score": 80},
                "auth": {"algorithm": "HS256", "expire_minutes": 60},
            }
        )
    )

    if not main_only:
        local_yaml = directory / "local.yaml"
        local_yaml.write_text(yaml.safe_dump(local_overrides or {}))

    from pydantic_settings import YamlConfigSettingsSource

    import mahavishnu.core.config as cfg_mod

    def _patched(settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings):
        yaml_sources = []
        for name in ("mahavishnu.yaml", "local.yaml"):
            path = directory / name
            if path.exists():
                yaml_sources.append(YamlConfigSettingsSource(settings_cls, path))
        return (init_settings, *yaml_sources, env_settings, dotenv_settings, file_secret_settings)

    # Replace on the class — the call below in pydantic-settings passes
    # init_settings as a kwarg, so the function signature must match.
    monkeypatch.setattr(
        cfg_mod.MahavishnuSettings,
        "settings_customise_sources",
        staticmethod(_patched),
    )
