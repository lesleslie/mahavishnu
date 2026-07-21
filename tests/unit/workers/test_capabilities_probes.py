from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from mahavishnu.workers.capabilities import (
    WorkerCapabilityState,
    evaluate_worker_capabilities,
)
from mahavishnu.workers.capabilities._probes import (
    _probe_provider_request,
)

if TYPE_CHECKING:
    import pytest


@dataclass
class C:
    runtime: str | None = None
    socket_path: str | None = None


@dataclass
class W:
    enabled: bool = True
    container: C = field(default_factory=C)


@dataclass
class S:
    workers: W = field(default_factory=W)


def test_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENCLAW_GATEWAY_URL", "http://127.0.0.1:1")
    r = evaluate_worker_capabilities("gateway-openclaw", settings=S(), force_live=True)
    assert r.state is WorkerCapabilityState.READY


def test_healthy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENCLAW_GATEWAY_URL", "http://gateway.test")

    class R:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict[str, bool]:
            return {"healthy": True}

    class A:
        def __init__(self, *a: object, **k: object) -> None:
            pass

        async def __aenter__(self) -> A:
            return self

        async def __aexit__(self, *a: object) -> None:
            pass

        async def get(self, *a: object, **k: object) -> R:
            return R()

    monkeypatch.setattr("httpx.AsyncClient", A)
    r = evaluate_worker_capabilities("gateway-openclaw", settings=S(), force_live=True)
    assert r.state is WorkerCapabilityState.AVAILABLE


# ---------------------------------------------------------------------------
# Security: refuse to send Authorization: Bearer <token> over plain http://
# (finding #5 — auth header without TLS).
# ---------------------------------------------------------------------------


def test_openclaw_gateway_rejects_insecure_http_with_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The OpenClaw gateway probe refuses to send Bearer tokens over http://."""
    monkeypatch.setenv("OPENCLAW_GATEWAY_URL", "http://gateway.test")
    monkeypatch.setenv("OPENCLAW_GATEWAY_TOKEN", "sk-test12345678abcdef")

    r = evaluate_worker_capabilities("gateway-openclaw", settings=S(), force_live=True)

    failed_checks = [c for c in r.checks if c.status == "fail"]
    assert failed_checks, "expected at least one failed check"
    assert any(c.safe_reason == "insecure_endpoint" for c in failed_checks)


def test_openclaw_gateway_allows_http_without_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The OpenClaw gateway probe permits http:// when no token is supplied (the existing test_unreachable flow)."""
    monkeypatch.setenv("OPENCLAW_GATEWAY_URL", "http://127.0.0.1:1")
    monkeypatch.delenv("OPENCLAW_GATEWAY_TOKEN", raising=False)

    r = evaluate_worker_capabilities("gateway-openclaw", settings=S(), force_live=True)

    # No insecure_endpoint check is added when no token is configured.
    assert not any(c.safe_reason == "insecure_endpoint" for c in r.checks)


def test_openclaw_gateway_allows_https_with_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The OpenClaw gateway probe accepts https:// URLs that carry tokens."""
    monkeypatch.setenv("OPENCLAW_GATEWAY_URL", "https://gateway.test")
    monkeypatch.setenv("OPENCLAW_GATEWAY_TOKEN", "sk-test12345678abcdef")

    # We expect the probe to attempt the real HTTPS request (which will fail with
    # an httpx.ConnectError, not insecure_endpoint). The point is the scheme
    # check must NOT short-circuit before the network call.
    r = evaluate_worker_capabilities("gateway-openclaw", settings=S(), force_live=True)
    assert not any(c.safe_reason == "insecure_endpoint" for c in r.checks)


def test_provider_request_rejects_insecure_http(monkeypatch: pytest.MonkeyPatch) -> None:
    """_probe_provider_request refuses http:// URLs when an API key is set."""
    monkeypatch.setenv("MINIMAX_API_KEY", "sk-test12345678abcdef")

    check = asyncio.run(
        _probe_provider_request(
            "minimax", "MINIMAX_API_KEY", "http://api.minimax.io/v1/models"
        )
    )

    assert check.status == "fail"
    assert check.safe_reason == "insecure_endpoint"


def test_provider_request_returns_missing_when_no_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When no API key is set, _probe_provider_request returns 'missing' (not insecure_endpoint)."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    check = asyncio.run(
        _probe_provider_request(
            "openai", "OPENAI_API_KEY", "http://api.openai.com/v1/models"
        )
    )

    assert check.status == "fail"
    assert check.safe_reason == "missing"
    # No insecure_endpoint error when no token was configured.
    assert check.safe_reason != "insecure_endpoint"


def test_provider_request_accepts_https_with_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_probe_provider_request accepts https:// URLs when an API key is set (no scheme error)."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test12345678abcdef")

    check = asyncio.run(
        _probe_provider_request(
            "anthropic", "ANTHROPIC_API_KEY", "https://api.anthropic.com/v1/models"
        )
    )

    # The request will likely fail because the network is unavailable in tests,
    # but the failure reason must NOT be insecure_endpoint (the scheme check
    # must have passed).
    assert check.safe_reason != "insecure_endpoint"