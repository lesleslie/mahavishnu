"""Tests for Hatchet adapter — P10 implementation."""

from __future__ import annotations

import importlib

import pytest


def test_hatchet_sdk_importable():
    """hatchet-sdk must be listed as an optional dep and installed."""
    hatchet = importlib.import_module("hatchet_sdk")
    assert hatchet is not None


from mahavishnu.core.adapters.base import AdapterType


def test_adapter_type_hatchet_exists():
    assert AdapterType.HATCHET == "hatchet"


from mahavishnu.core.config import AdapterConfig, HatchetConfig


def test_adapter_config_has_hatchet_enabled():
    cfg = AdapterConfig()
    assert cfg.hatchet_enabled is False


def test_hatchet_config_defaults():
    cfg = HatchetConfig()
    assert cfg.server_url == "localhost:7077"
    assert cfg.namespace == "mahavishnu"
    assert cfg.max_runs == 10
