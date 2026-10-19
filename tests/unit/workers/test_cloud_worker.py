"""Tests for CloudWorker and its Bifrost routing (REQ-BIFROST-008).

The plan §5 Phase 2 contract: ``_build_fallback_chain`` reads the
``minimax`` provider's ``base_url`` from
``oneiric.adapters.llm.bifrost.get_router().resolve(LLMProvider.OPENAI)``
when the router is enabled + routed, otherwise falls back to
``config.minimax_url``. The ``llama_server`` provider is unchanged —
local providers stay direct.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from mahavishnu.workers.cloud_worker import (
    CloudWorkerConfig,
    _build_fallback_chain,
    _resolve_minimax_base_url,
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


def _captured_minimax_url(captured_settings: list) -> str:
    """Return the minimax provider's ``base_url`` from a captured
    ``LLMSettings`` instance. Patches ``FallbackChain.from_settings``
    to record the constructed settings so the test can inspect the
    per-provider URLs without touching the chain's private state.
    """
    if not captured_settings:
        return ""
    return captured_settings[0].providers["minimax"]["base_url"]


class TestResolveMinimaxBaseUrl:
    """Unit tests for the URL resolver helper."""

    def test_returns_config_default_when_router_disabled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from oneiric.adapters.llm.bifrost import reset_router_for_tests

        monkeypatch.delenv("ONEIRIC_BIFROST_ENABLED", raising=False)
        reset_router_for_tests()
        config = CloudWorkerConfig(minimax_url="https://api.minimax.io/v1")
        assert _resolve_minimax_base_url(config) == "https://api.minimax.io/v1"

    def test_returns_router_url_with_v1_suffix(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _enable_bifrost(monkeypatch, routes=("qwen_route",))
        config = CloudWorkerConfig(minimax_url="https://api.minimax.io/v1")
        # The oneiric router returns http://127.0.0.1:8471/ (Pydantic
        # HttpUrl adds trailing slash). The helper appends /v1.
        assert _resolve_minimax_base_url(config) == "http://127.0.0.1:8471/v1"


class TestBuildFallbackChainBifrostRouting:
    """REQ-BIFROST-008: the chain's minimax base_url comes from oneiric."""

    def test_chain_uses_router_when_enabled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _enable_bifrost(monkeypatch, routes=("qwen_route",))

        captured: list = []
        real_from_settings = None
        from mcp_common.llm import FallbackChain

        real_from_settings = FallbackChain.from_settings

        def capture(settings):  # type: ignore[no-untyped-def]
            captured.append(settings)
            return real_from_settings(settings)

        config = CloudWorkerConfig(
            minimax_url="https://api.minimax.io/v1",
            llama_server_url="http://localhost:8081",
        )
        with patch.object(FallbackChain, "from_settings", side_effect=capture):
            _build_fallback_chain(config)

        assert len(captured) == 1
        assert (
            captured[0].providers["minimax"]["base_url"]
            == "http://127.0.0.1:8471/v1"
        )
        # llama_server is unchanged — local providers stay direct.
        assert (
            captured[0].providers["llama_server"]["base_url"]
            == "http://localhost:8081"
        )
        # The chain order is preserved (minimax primary, llama_server
        # secondary).
        assert captured[0].fallback_chain == ["minimax", "llama_server"]

    def test_chain_uses_config_url_when_router_disabled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from oneiric.adapters.llm.bifrost import reset_router_for_tests

        monkeypatch.delenv("ONEIRIC_BIFROST_ENABLED", raising=False)
        reset_router_for_tests()

        captured: list = []
        from mcp_common.llm import FallbackChain

        real_from_settings = FallbackChain.from_settings

        def capture(settings):  # type: ignore[no-untyped-def]
            captured.append(settings)
            return real_from_settings(settings)

        config = CloudWorkerConfig(
            minimax_url="https://api.minimax.io/v1",
            llama_server_url="http://localhost:8081",
        )
        with patch.object(FallbackChain, "from_settings", side_effect=capture):
            _build_fallback_chain(config)

        assert len(captured) == 1
        # No router → use config default (the operator env var or
        # the public MiniMax OpenAI-compatible endpoint).
        assert (
            captured[0].providers["minimax"]["base_url"]
            == "https://api.minimax.io/v1"
        )

    def test_chain_does_not_route_anthropic(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The router's CLAUDE_ROUTE only affects the Agno factory's
        ``ANTHROPIC_BASE_URL`` injection. The CloudWorker's
        FallbackChain has no Anthropic tier — its anthropic support
        is the legacy/removed path. With the new oneiric routing,
        the chain is a 2-tier minimax → llama_server; the chain
        providers dict has no anthropic entry.
        """
        from oneiric.adapters.llm.bifrost import reset_router_for_tests
        from mcp_common.llm import FallbackChain

        monkeypatch.setenv("ONEIRIC_BIFROST_ENABLED", "true")
        monkeypatch.setenv("ONEIRIC_BIFROST_ROUTES", "claude_route,qwen_route")
        monkeypatch.delenv("BIFROST_ALLOW_REMOTE", raising=False)
        reset_router_for_tests()

        captured: list = []
        real_from_settings = FallbackChain.from_settings

        def capture(settings):  # type: ignore[no-untyped-def]
            captured.append(settings)
            return real_from_settings(settings)

        config = CloudWorkerConfig()
        with patch.object(FallbackChain, "from_settings", side_effect=capture):
            _build_fallback_chain(config)

        assert "anthropic" not in captured[0].providers
        # minimax IS in the providers (it's the primary tier).
        assert "minimax" in captured[0].providers
        # And the minimax URL is the oneiric-router URL with /v1.
        assert (
            captured[0].providers["minimax"]["base_url"]
            == "http://127.0.0.1:8471/v1"
        )
