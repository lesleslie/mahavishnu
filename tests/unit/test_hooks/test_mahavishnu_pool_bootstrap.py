"""Tests for the SessionStart pool-bootstrap hook script.

The script lives at .claude/hooks/mahavishnu-pool-bootstrap.py
and at ~/.qwen/hooks/sessionstart/mahavishnu-pool-bootstrap.py. We test
the importable helpers rather than the script entry point because
the entry point is exercised by the integration test in Task 12.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import uuid
from pathlib import Path

import httpx
import pytest


def _load_module() -> object:
    """Load the hook script as a module for direct testing."""
    path = (
        Path(__file__).parent.parent.parent.parent
        / ".claude" / "hooks" / "mahavishnu-pool-bootstrap.py"
    )
    spec = importlib.util.spec_from_file_location("mahavishnu_pool_bootstrap_hook", path)
    if spec is None or spec.loader is None:
        pytest.skip(f"hook script not found at {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["mahavishnu_pool_bootstrap_hook"] = module
    spec.loader.exec_module(module)
    return module


def test_format_result_skipped() -> None:
    mod = _load_module()
    result = {"status": "skipped", "pools_active_after": 3}
    rendered = mod._format_result(result)
    assert "already populated" in rendered
    assert "3" in rendered


def test_format_result_spawned() -> None:
    mod = _load_module()
    result = {"status": "spawned", "pool_id": "auto-id-42"}
    rendered = mod._format_result(result)
    assert "spawned" in rendered
    assert "auto-id-42" in rendered


def test_format_result_failed() -> None:
    mod = _load_module()
    result = {"status": "failed", "error": "MCP down"}
    rendered = mod._format_result(result)
    assert "FAILED" in rendered
    assert "MCP down" in rendered


def test_invoke_bootstrap_sends_jsonrpc_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify the wire shape is JSON-RPC 2.0 tools/call, NOT /tools/<name>."""
    mod = _load_module()
    captured: dict[str, object] = {}

    class _FakeResponse:
        status_code = 200

        def json(self) -> dict[str, object]:
            return {
                "jsonrpc": "2.0",
                "id": str(uuid.uuid4()),
                "result": {"status": "spawned", "pool_id": "abc"},
            }

    def _fake_post(self: object, url: str, **kwargs: object) -> _FakeResponse:
        captured["url"] = url
        captured["body"] = kwargs.get("json")
        return _FakeResponse()

    monkeypatch.setattr(httpx.Client, "post", _fake_post)
    out = mod._invoke_bootstrap()
    assert out == {"status": "spawned", "pool_id": "abc"}
    # The wire target is /mcp (NOT /tools/pool_bootstrap)
    assert captured["url"] == "http://localhost:8680/mcp"
    # The body is JSON-RPC 2.0
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["jsonrpc"] == "2.0"
    assert body["method"] == "tools/call"
    assert body["params"]["name"] == "pool_bootstrap"


def test_invoke_bootstrap_returns_none_on_connection_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """When the MCP server is unreachable, the helper returns None and the script proceeds in degraded mode."""
    mod = _load_module()

    def _raise(self: object, *args: object, **kwargs: object) -> None:
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx.Client, "post", _raise)
    out = mod._invoke_bootstrap()
    assert out is None
