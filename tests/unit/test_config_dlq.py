"""Unit tests for core.config_dlq constants."""

from __future__ import annotations

from mahavishnu.core import config_dlq


def test_dlq_config_fields_contains_expected_entries() -> None:
    fields = config_dlq.DLQ_CONFIG_FIELDS
    assert "dlq_enabled" in fields
    assert "dlq_max_size" in fields
    assert "dlq_default_retry_policy" in fields
    assert "dlq_default_max_retries" in fields
    assert "dlq_retry_processor_enabled" in fields
    assert "dlq_retry_interval_seconds" in fields
    assert "validate_dlq_retry_policy" in fields
    assert "never" in fields and "linear" in fields and "exponential" in fields


def test_dlq_yaml_config_example_contains_expected_values() -> None:
    yaml_cfg = config_dlq.DLQ_YAML_CONFIG
    assert "dlq_enabled: true" in yaml_cfg
    assert "dlq_max_size: 10000" in yaml_cfg
    assert "dlq_default_retry_policy: exponential" in yaml_cfg
    assert "dlq_default_max_retries: 3" in yaml_cfg
    assert "dlq_retry_processor_enabled: true" in yaml_cfg
    assert "dlq_retry_interval_seconds: 60" in yaml_cfg


def test_dlq_env_vars_example_contains_expected_names() -> None:
    env_vars = config_dlq.DLQ_ENV_VARS
    assert "MAHAVISHNU_DLQ_ENABLED" in env_vars
    assert "MAHAVISHNU_DLQ_MAX_SIZE" in env_vars
    assert "MAHAVISHNU_DLQ_DEFAULT_RETRY_POLICY" in env_vars
    assert "MAHAVISHNU_DLQ_DEFAULT_MAX_RETRIES" in env_vars
    assert "MAHAVISHNU_DLQ_RETRY_PROCESSOR_ENABLED" in env_vars
    assert "MAHAVISHNU_DLQ_RETRY_INTERVAL_SECONDS" in env_vars
