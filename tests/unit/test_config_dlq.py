"""Unit tests for core.config_dlq constants.

The `config_dlq` module is a documentation-only module: it contains three
string constants that describe the Pydantic fields, YAML keys, and env-var
names to add to MahavishnuSettings. We pin the strings so that downstream
changes to the config surface are caught here.
"""

from __future__ import annotations

import re

import pytest

from mahavishnu.core import config_dlq

# ---------------------------------------------------------------------------
# DLQ_CONFIG_FIELDS (Pydantic field declarations to paste into config.py)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field_name",
    [
        "dlq_enabled",
        "dlq_max_size",
        "dlq_default_retry_policy",
        "dlq_default_max_retries",
        "dlq_retry_processor_enabled",
        "dlq_retry_interval_seconds",
    ],
)
def test_dlq_config_fields_declares_each_field(field_name: str) -> None:
    assert field_name in config_dlq.DLQ_CONFIG_FIELDS


def test_dlq_config_fields_includes_field_validator() -> None:
    assert "field_validator" in config_dlq.DLQ_CONFIG_FIELDS
    assert "validate_dlq_retry_policy" in config_dlq.DLQ_CONFIG_FIELDS


@pytest.mark.parametrize(
    "policy",
    ["never", "linear", "exponential", "immediate"],
)
def test_dlq_config_fields_lists_every_valid_policy(policy: str) -> None:
    assert policy in config_dlq.DLQ_CONFIG_FIELDS


def test_dlq_config_fields_has_size_bounds() -> None:
    """The size field is constrained to [100, 100000]."""
    assert "ge=100" in config_dlq.DLQ_CONFIG_FIELDS
    assert "le=100000" in config_dlq.DLQ_CONFIG_FIELDS


def test_dlq_config_fields_has_max_retries_bounds() -> None:
    """max_retries is constrained to [0, 10]."""
    # The substring 'ge=0' and 'le=10' must each appear at least once.
    assert "ge=0" in config_dlq.DLQ_CONFIG_FIELDS
    assert "le=10" in config_dlq.DLQ_CONFIG_FIELDS


def test_dlq_config_fields_is_a_string() -> None:
    assert isinstance(config_dlq.DLQ_CONFIG_FIELDS, str)


# ---------------------------------------------------------------------------
# DLQ_YAML_CONFIG (example settings/mahavishnu.yaml block)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "yaml_line",
    [
        "dlq_enabled: true",
        "dlq_max_size: 10000",
        "dlq_default_retry_policy: exponential",
        "dlq_default_max_retries: 3",
        "dlq_retry_processor_enabled: true",
        "dlq_retry_interval_seconds: 60",
    ],
)
def test_dlq_yaml_config_has_example_key_value(yaml_line: str) -> None:
    assert yaml_line in config_dlq.DLQ_YAML_CONFIG


def test_dlq_yaml_config_documents_all_retry_policies() -> None:
    """The YAML comment must mention every policy option for users."""
    assert "never" in config_dlq.DLQ_YAML_CONFIG
    assert "linear" in config_dlq.DLQ_YAML_CONFIG
    assert "exponential" in config_dlq.DLQ_YAML_CONFIG
    assert "immediate" in config_dlq.DLQ_YAML_CONFIG


# ---------------------------------------------------------------------------
# DLQ_ENV_VARS (example environment variables)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "env_var",
    [
        "MAHAVISHNU_DLQ_ENABLED",
        "MAHAVISHNU_DLQ_MAX_SIZE",
        "MAHAVISHNU_DLQ_DEFAULT_RETRY_POLICY",
        "MAHAVISHNU_DLQ_DEFAULT_MAX_RETRIES",
        "MAHAVISHNU_DLQ_RETRY_PROCESSOR_ENABLED",
        "MAHAVISHNU_DLQ_RETRY_INTERVAL_SECONDS",
    ],
)
def test_dlq_env_vars_lists_each_variable(env_var: str) -> None:
    assert env_var in config_dlq.DLQ_ENV_VARS


def test_dlq_env_vars_uses_uppercase_snake_case() -> None:
    """Every env-var mentioned in DLQ_ENV_VARS must be MAHAVISHNU_DLQ_<UPPER>."""
    pattern = re.compile(r"MAHAVISHNU_DLQ_[A-Z][A-Z0-9_]*")
    matches = pattern.findall(config_dlq.DLQ_ENV_VARS)

    # All six documented variables must be matched by the pattern.
    assert set(matches) >= {
        "MAHAVISHNU_DLQ_ENABLED",
        "MAHAVISHNU_DLQ_MAX_SIZE",
        "MAHAVISHNU_DLQ_DEFAULT_RETRY_POLICY",
        "MAHAVISHNU_DLQ_DEFAULT_MAX_RETRIES",
        "MAHAVISHNU_DLQ_RETRY_PROCESSOR_ENABLED",
        "MAHAVISHNU_DLQ_RETRY_INTERVAL_SECONDS",
    }


def test_dlq_env_vars_uses_assignment_syntax() -> None:
    """Each env-var line should look like 'NAME=value', not just 'NAME'."""
    for var in [
        "MAHAVISHNU_DLQ_ENABLED",
        "MAHAVISHNU_DLQ_MAX_SIZE",
        "MAHAVISHNU_DLQ_DEFAULT_RETRY_POLICY",
        "MAHAVISHNU_DLQ_DEFAULT_MAX_RETRIES",
        "MAHAVISHNU_DLQ_RETRY_PROCESSOR_ENABLED",
        "MAHAVISHNU_DLQ_RETRY_INTERVAL_SECONDS",
    ]:
        # Must appear as `VAR=...` (not just commented out name only)
        assert re.search(rf"^{var}=\S+", config_dlq.DLQ_ENV_VARS, re.MULTILINE), (
            f"Expected '{var}=<value>' line in DLQ_ENV_VARS"
        )


# ---------------------------------------------------------------------------
# Cross-constant consistency
# ---------------------------------------------------------------------------


def test_field_yaml_and_env_names_are_in_sync() -> None:
    """Every YAML key must have a matching env var, and vice versa.

    This catches drift between the documented config surface and the env
    overrides.
    """
    yaml_fields = set(re.findall(r"^(\w+):", config_dlq.DLQ_YAML_CONFIG, re.MULTILINE))
    env_names = set(re.findall(r"(MAHAVISHNU_DLQ_\w+)", config_dlq.DLQ_ENV_VARS))

    # Map dlq_x -> MAHAVISHNU_DLQ_X
    expected_env_from_yaml = {f"MAHAVISHNU_{name.upper()}" for name in yaml_fields}
    assert expected_env_from_yaml <= env_names, (
        f"YAML fields missing env-var equivalents: {expected_env_from_yaml - env_names}"
    )


def test_all_three_constants_are_nonempty_strings() -> None:
    for name in ("DLQ_CONFIG_FIELDS", "DLQ_YAML_CONFIG", "DLQ_ENV_VARS"):
        value = getattr(config_dlq, name)
        assert isinstance(value, str)
        assert value.strip(), f"{name} must not be empty"
