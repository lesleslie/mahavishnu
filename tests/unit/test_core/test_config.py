"""Tests for PoolConfig (settings) — defaults and bounds for the new
auto_spawn* fields added in Task 1 of the pool-bootstrap plan
(2026-10-09-pool-bootstrap-mcp-tool.md).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from mahavishnu.core.config import PoolConfig


def test_pools_settings_auto_spawn_defaults() -> None:
    """PoolConfig (settings) auto_spawn* fields default to safe off + sensible sizes."""
    settings = PoolConfig()
    assert settings.auto_spawn is False
    assert settings.auto_spawn_type == "mahavishnu"
    assert settings.auto_spawn_min_workers == 1
    assert settings.auto_spawn_max_workers == 3


def test_pools_settings_auto_spawn_min_workers_bounds() -> None:
    """auto_spawn_min_workers rejects values outside [1, 10]."""
    with pytest.raises(ValidationError):
        PoolConfig(auto_spawn_min_workers=0)
    with pytest.raises(ValidationError):
        PoolConfig(auto_spawn_min_workers=11)


def test_pools_settings_auto_spawn_max_workers_bounds() -> None:
    """auto_spawn_max_workers rejects values outside [1, 100]."""
    with pytest.raises(ValidationError):
        PoolConfig(auto_spawn_max_workers=0)
    with pytest.raises(ValidationError):
        PoolConfig(auto_spawn_max_workers=101)
