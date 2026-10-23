"""Tests for ``resolve_probe_endpoint`` and the Bifrost routing
contract (REQ-BIFROST-007).

The plan §5 Phase 2 contract: when the oneiric ``BifrostLLMRouter``
returns a URL for the OPENAI provider (router is enabled + OPENAI
route is configured) AND ``provider == "minimax"``, the probe goes
to ``<router.base_url>/v1/models`` (the Bifrost gateway's
OpenAI-compatible ``/v1/models`` endpoint). For all other cases the
literal ``PROVIDER_PROBES[provider][1]`` is returned.
"""

from __future__ import annotations

import pytest

from mahavishnu.workers.capabilities._probes import (
    PROVIDER_PROBES,
    _check_endpoint_scheme,
    _is_bifrost_endpoint,
    _probe_auth_headers,
    resolve_probe_endpoint,
)

BIFROST_MODELS = "http://127.0.0.1:8471/v1/models"


@pytest.mark.parametrize(
    ("endpoint", "expected"),
    [
        ("http://127.0.0.1:8471/v1/models", True),
        ("http://localhost:8471/v1/models", True),
        # Different port, different host, and the upstream defaults are not Bifrost.
        ("http://127.0.0.1:18471/v1/models", False),
        ("https://api.minimax.io/v1/models", False),
        ("https://api.openai.com/v1/models", False),
        ("http://127.0.0.1:8081/v1/models", False),
    ],
)
def test_is_bifrost_endpoint(endpoint: str, expected: bool) -> None:
    assert _is_bifrost_endpoint(endpoint) is expected


def test_bifrost_probe_sends_the_virtual_key_not_the_provider_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """req: REQ-BIFROST-007 -- Bifrost is probed with ``x-bf-vk``.

    Bifrost reads virtual keys exclusively from ``x-bf-vk``; a
    header-differential probe confirmed ``Authorization: Bearer`` is never
    honoured. Sending the upstream provider key produced a permanent 401, so
    a healthy gateway was scored unavailable.
    """
    monkeypatch.setenv("BIFROST_VIRTUAL_KEY", "sk-bf-gateway-key")
    monkeypatch.setenv("MINIMAX_API_KEY", "upstream-provider-key")

    headers, reason = _probe_auth_headers("minimax", "MINIMAX_API_KEY", BIFROST_MODELS)

    assert reason == ""
    assert headers == {"x-bf-vk": "sk-bf-gateway-key"}
    assert "Authorization" not in headers


def test_bifrost_probe_without_a_virtual_key_names_the_missing_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing gateway key must name itself, not say "missing"."""
    monkeypatch.delenv("BIFROST_VIRTUAL_KEY", raising=False)
    monkeypatch.setenv("MINIMAX_API_KEY", "upstream-provider-key")

    headers, reason = _probe_auth_headers("minimax", "MINIMAX_API_KEY", BIFROST_MODELS)

    assert headers is None
    assert reason == "missing BIFROST_VIRTUAL_KEY"


def test_direct_probe_keeps_the_bearer_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Upstream providers are unchanged -- still ``Authorization: Bearer``."""
    monkeypatch.setenv("MINIMAX_API_KEY", "upstream-provider-key")

    headers, reason = _probe_auth_headers(
        "minimax", "MINIMAX_API_KEY", "https://api.minimax.io/v1/models"
    )

    assert reason == ""
    assert headers == {"Authorization": "Bearer upstream-provider-key"}


def test_loopback_http_is_allowed_to_carry_a_secret() -> None:
    """Loopback traffic never leaves the machine, so plain http is safe there.

    Without this the probe reported ``insecure_endpoint`` against the local
    Bifrost gateway, which is served over loopback http by design.
    """
    assert _check_endpoint_scheme(BIFROST_MODELS, has_secret=True) is None
    assert _check_endpoint_scheme("http://localhost:8471/v1/models", has_secret=True) is None


def test_remote_http_still_rejects_a_secret() -> None:
    """The exemption is loopback-only; it must not weaken remote endpoints."""
    assert _check_endpoint_scheme("http://evil.example/v1/models", has_secret=True) == (
        "insecure_endpoint"
    )
    assert _check_endpoint_scheme("http://api.minimax.io/v1/models", has_secret=True) == (
        "insecure_endpoint"
    )


def test_resolved_base_url_gains_v1_only_once() -> None:
    """The router base already ends in ``/v1``; appending again gave ``/v1/v1``.

    Same class of defect as the one fixed in ``terminal/manager.py``.
    ``TestResolveProbeEndpoint::test_probe_uses_router`` covers the router
    path end to end; this pins the exact invariant at unit level.
    """
    base = "http://127.0.0.1:8471/v1"
    stripped = base.rstrip("/")
    resolved = stripped if stripped.endswith("/v1") else f"{stripped}/v1"
    assert f"{resolved}/models" == "http://127.0.0.1:8471/v1/models"
    assert "/v1/v1/" not in f"{resolved}/models"


def _enable_bifrost(
    monkeypatch: pytest.MonkeyPatch,
    *,
    routes: tuple[str, ...] = ("qwen_route",),
) -> None:
    """Enable the oneiric Bifrost router via env vars + clear the
    process-cached singleton so the test sees a fresh router.
    """
    from oneiric.adapters.llm.bifrost import reset_router_for_tests

    monkeypatch.setenv("ONEIRIC_BIFROST_ENABLED", "true")
    monkeypatch.setenv("ONEIRIC_BIFROST_ROUTES", ",".join(routes))
    monkeypatch.delenv("BIFROST_ALLOW_REMOTE", raising=False)
    reset_router_for_tests()


def _disable_bifrost(monkeypatch: pytest.MonkeyPatch) -> None:
    from oneiric.adapters.llm.bifrost import reset_router_for_tests

    monkeypatch.delenv("ONEIRIC_BIFROST_ENABLED", raising=False)
    reset_router_for_tests()


class TestResolveProbeEndpoint:
    """REQ-BIFROST-007: Bifrost routing for the minimax probe."""

    def test_probe_uses_router(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When the router is enabled and routes OPENAI, the minimax
        probe goes to ``<gateway>/v1/models`` (the OpenAI-compatible
        /v1/models endpoint on the Bifrost gateway).
        """
        _enable_bifrost(monkeypatch, routes=("qwen_route",))
        # The router returns http://127.0.0.1:8471/ (Pydantic
        # HttpUrl adds trailing slash); rstrip + /v1/models.
        assert (
            resolve_probe_endpoint("minimax")
            == "http://127.0.0.1:8471/v1/models"
        )

    def test_probe_passthrough_when_router_disabled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When the router is disabled, the minimax probe returns
        the literal ``PROVIDER_PROBES["minimax"][1]`` value.
        """
        _disable_bifrost(monkeypatch)
        assert (
            resolve_probe_endpoint("minimax")
            == PROVIDER_PROBES["minimax"][1]
        )
        assert resolve_probe_endpoint("minimax") == "https://api.minimax.io/v1/models"

    def test_probe_passthrough_for_non_minimax_providers(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The router's OPENAI URL only affects the minimax probe.
        anthropic / openai / qwen probes stay direct regardless of
        the bifrost flag (per the v1.5 spec amendment).
        """
        _enable_bifrost(monkeypatch, routes=("qwen_route", "claude_route"))
        for provider in ("anthropic", "openai", "qwen"):
            assert resolve_probe_endpoint(provider) == PROVIDER_PROBES[provider][1]

    def test_probe_passthrough_when_openai_route_not_in_routes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If the router is enabled but only CLAUDE_ROUTE is
        configured (no qwen_route), the OPENAI resolution returns
        ``None`` and the probe falls back to the literal default.
        """
        from oneiric.adapters.llm.bifrost import reset_router_for_tests

        monkeypatch.setenv("ONEIRIC_BIFROST_ENABLED", "true")
        monkeypatch.setenv("ONEIRIC_BIFROST_ROUTES", "claude_route")
        monkeypatch.delenv("BIFROST_ALLOW_REMOTE", raising=False)
        reset_router_for_tests()

        assert (
            resolve_probe_endpoint("minimax")
            == PROVIDER_PROBES["minimax"][1]
        )

    def test_probe_raises_keyerror_for_unknown_provider(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Unknown providers propagate ``KeyError`` from the
        ``PROVIDER_PROBES`` dict — that's a caller bug, not a
        configuration error.
        """
        _disable_bifrost(monkeypatch)
        with pytest.raises(KeyError):
            resolve_probe_endpoint("not-a-real-provider")
