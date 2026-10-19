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
    resolve_probe_endpoint,
)


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
