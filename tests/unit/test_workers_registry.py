"""Capability metadata tests for mahavishnu.workers.registry.WorkerConfig.

Covers the new fields added in Task 3 of the worker-readiness plan:
required_env, required_settings, auth_kind, runtime_kind, one_shot, endpoint.
"""

from __future__ import annotations

import pytest

from mahavishnu.workers.registry import (
    WORKER_REGISTRY,
    AuthKind,
    RuntimeKind,
    WorkerCategory,
    WorkerConfig,
    resolve_worker_type,
)

pytestmark = pytest.mark.unit


def test_worker_config_has_capability_fields() -> None:
    cfg = WorkerConfig(
        name="test",
        worker_type="test-x",
        command="echo",
        category=WorkerCategory.SHELL,
        required_env=["MINIMAX_API_KEY"],
        required_settings=["workers.enabled"],
        auth_kind=AuthKind.API_KEY,
        runtime_kind=RuntimeKind.NONE,
        one_shot=False,
    )
    assert cfg.required_env == ["MINIMAX_API_KEY"]
    assert cfg.required_settings == ["workers.enabled"]
    assert cfg.auth_kind is AuthKind.API_KEY
    assert cfg.runtime_kind is RuntimeKind.NONE
    assert cfg.one_shot is False


def test_registry_entries_have_default_capability_metadata() -> None:
    for worker_type, cfg in WORKER_REGISTRY.items():
        assert isinstance(cfg.required_env, list), f"{worker_type} required_env not list"
        assert isinstance(cfg.required_settings, list), (
            f"{worker_type} required_settings not list"
        )
        assert cfg.auth_kind in set(AuthKind), f"{worker_type} auth_kind invalid"
        assert cfg.runtime_kind in set(RuntimeKind), f"{worker_type} runtime_kind invalid"
        assert isinstance(cfg.one_shot, bool), f"{worker_type} one_shot not bool"


def test_resolve_worker_type_does_not_infer_gateway_from_env(monkeypatch) -> None:
    monkeypatch.delenv("OPENCLAW_GATEWAY_URL", raising=False)
    monkeypatch.delenv("OPENCLAW_GATEWAY_TOKEN", raising=False)
    result = resolve_worker_type("terminal-claude", task_type="communication", prompt="reply")
    assert result == "terminal-claude"


def test_resolve_worker_type_does_not_inject_openclaw_when_terminal(
    monkeypatch,
) -> None:
    monkeypatch.setenv("OPENCLAW_GATEWAY_URL", "http://gateway.test")
    result = resolve_worker_type("terminal-claude", task_type="general", prompt="hi")
    assert result == "terminal-claude"
