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
    assert cfg.poll_interval_seconds == 2.0
    assert cfg.task_timeout_seconds == 300


from mahavishnu.workers.task_router import TaskCategory, classify_task


def test_task_category_agent_loop_exists():
    assert TaskCategory.AGENT_LOOP == "agent_loop"


def test_classify_task_agent_loop():
    prompt = "run an agent loop to autonomously complete this multi-step workflow"
    category = classify_task(prompt)
    assert category == TaskCategory.AGENT_LOOP
