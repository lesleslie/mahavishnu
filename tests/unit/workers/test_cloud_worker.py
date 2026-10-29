"""Tests for CloudWorker and its Bifrost routing (REQ-BIFROST-008).

The plan §5 Phase 2 contract: ``_build_fallback_chain`` reads the
``minimax`` provider's ``base_url`` from
``oneiric.adapters.llm.bifrost.get_router().resolve(LLMProvider.OPENAI)``
when the router is enabled + routed, otherwise falls back to
``config.minimax_url``. The ``llama_server`` provider is unchanged —
local providers stay direct.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from mahavishnu.workers.cloud_worker import (
    CloudWorkerConfig,
    _build_fallback_chain,
    _resolve_minimax_endpoint,
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
        url, via_gateway = _resolve_minimax_endpoint(config)
        assert url == "https://api.minimax.io/v1"
        assert via_gateway is False

    def test_returns_router_url_with_v1_suffix(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _enable_bifrost(monkeypatch, routes=("qwen_route",))
        config = CloudWorkerConfig(minimax_url="https://api.minimax.io/v1")
        # The oneiric router returns http://127.0.0.1:8471/v1/ (Pydantic
        # HttpUrl adds trailing slash). The helper must not append a
        # second /v1.
        url, via_gateway = _resolve_minimax_endpoint(config)
        assert url == "http://127.0.0.1:8471/v1"
        assert via_gateway is True

    @pytest.mark.parametrize(
        ("router_url", "expected"),
        [
            # oneiric's current default (cd59122): already carries /v1.
            ("http://127.0.0.1:8471/v1", "http://127.0.0.1:8471/v1"),
            ("http://127.0.0.1:8471/v1/", "http://127.0.0.1:8471/v1"),
            # The pre-cd59122 default: bare gateway root, needs the suffix.
            ("http://127.0.0.1:8471", "http://127.0.0.1:8471/v1"),
            ("http://127.0.0.1:8471/", "http://127.0.0.1:8471/v1"),
        ],
    )
    def test_v1_suffix_is_applied_idempotently(
        self,
        monkeypatch: pytest.MonkeyPatch,
        router_url: str,
        expected: str,
    ) -> None:
        """The suffix is added only when it is missing.

        Appending unconditionally produced ``/v1/v1`` once oneiric
        changed its router default to include ``/v1`` -- a path that
        404s at the gateway. The helper has to accept both forms.
        """
        import oneiric.adapters.llm.bifrost as bifrost_mod

        class _FakeRouter:
            def resolve(self, provider: object) -> str:
                return router_url

        monkeypatch.setattr(bifrost_mod, "get_router", lambda: _FakeRouter())

        config = CloudWorkerConfig(minimax_url="https://api.minimax.io/v1")
        url, _ = _resolve_minimax_endpoint(config)
        assert url == expected


class TestBuildFallbackChainBifrostRouting:
    """REQ-BIFROST-008: the chain's minimax base_url comes from oneiric."""

    def test_chain_uses_router_when_enabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
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
        assert captured[0].providers["minimax"]["base_url"] == "http://127.0.0.1:8471/v1"
        # llama_server is unchanged — local providers stay direct.
        assert captured[0].providers["llama_server"]["base_url"] == "http://localhost:8081"
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
        assert captured[0].providers["minimax"]["base_url"] == "https://api.minimax.io/v1"

    def test_chain_does_not_route_anthropic(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The router's CLAUDE_ROUTE only affects the Agno factory's
        ``ANTHROPIC_BASE_URL`` injection. The CloudWorker's
        FallbackChain has no Anthropic tier — its anthropic support
        is the legacy/removed path. With the new oneiric routing,
        the chain is a 2-tier minimax → llama_server; the chain
        providers dict has no anthropic entry.
        """
        from mcp_common.llm import FallbackChain
        from oneiric.adapters.llm.bifrost import reset_router_for_tests

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
        assert captured[0].providers["minimax"]["base_url"] == "http://127.0.0.1:8471/v1"


class TestBuildFallbackChainGatewayHeaders:
    """REQ-BIFROST-035: a gateway-routed provider carries the virtual key.

    Bifrost rejects a provider key with ``401 - virtual key is
    required``, so a request that reaches the gateway must carry the
    virtual key in ``x-bf-vk``. The same header set carries the cache
    headers that make ``cache_mode`` effective (REQ-BIFROST-037).
    """

    @staticmethod
    def _capture(monkeypatch: pytest.MonkeyPatch) -> list:
        """Build the chain with ``LLMSettings`` captured."""
        from mcp_common.llm import FallbackChain

        captured: list = []
        real_from_settings = FallbackChain.from_settings

        def capture(settings):  # type: ignore[no-untyped-def]
            captured.append(settings)
            return real_from_settings(settings)

        with patch.object(FallbackChain, "from_settings", side_effect=capture):
            _build_fallback_chain(CloudWorkerConfig())
        return captured

    def test_gateway_headers_present_when_routed_via_bifrost(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The minimax provider carries ``x-bf-vk`` when the router is on."""
        _enable_bifrost(monkeypatch, routes=("qwen_route",))
        monkeypatch.setenv("BIFROST_VIRTUAL_KEY", "sk-bf-test-key")

        captured = self._capture(monkeypatch)
        headers = captured[0].providers["minimax"]["default_headers"]
        assert headers["x-bf-vk"] == "sk-bf-test-key"

    def test_no_gateway_headers_when_routed_direct(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A direct-to-MiniMax provider must not carry gateway headers."""
        from oneiric.adapters.llm.bifrost import reset_router_for_tests

        monkeypatch.delenv("ONEIRIC_BIFROST_ENABLED", raising=False)
        reset_router_for_tests()
        monkeypatch.setenv("BIFROST_VIRTUAL_KEY", "sk-bf-test-key")

        captured = self._capture(monkeypatch)
        assert captured[0].providers["minimax"]["default_headers"] == {}

    def test_cache_type_follows_the_configured_mode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """``cache_mode`` reaches the request as ``x-bf-cache-type``."""
        _enable_bifrost(monkeypatch, routes=("qwen_route",))
        monkeypatch.setenv("BIFROST_VIRTUAL_KEY", "sk-bf-test-key")
        monkeypatch.setenv("ONEIRIC_BIFROST_CACHE_MODE", "semantic")

        captured = self._capture(monkeypatch)
        headers = captured[0].providers["minimax"]["default_headers"]
        assert headers["x-bf-cache-type"] == "semantic"
        assert headers["x-bf-cache-key"] == "default"

    def test_off_mode_suppresses_the_cache_write(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """``cache_mode: off`` becomes ``x-bf-cache-no-store``."""
        _enable_bifrost(monkeypatch, routes=("qwen_route",))
        monkeypatch.setenv("BIFROST_VIRTUAL_KEY", "sk-bf-test-key")
        monkeypatch.setenv("ONEIRIC_BIFROST_CACHE_MODE", "off")

        captured = self._capture(monkeypatch)
        headers = captured[0].providers["minimax"]["default_headers"]
        assert headers["x-bf-cache-no-store"] == "true"
        assert "x-bf-cache-type" not in headers

    def test_no_virtual_key_yields_no_virtual_key_header(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Without a virtual key the provider carries no ``x-bf-vk``.

        An empty ``x-bf-vk`` would still 401; sending nothing keeps the
        failure honest and lets the worker log the misconfiguration.

        The CACHE headers are still sent, though. ``cache_mode`` is an
        operator retention control: if a missing credential also dropped
        ``x-bf-cache-no-store``, then ``cache_mode: off`` would silently
        become "cache everything" and the gateway would write the prompt
        and response into the shared cache.
        """
        _enable_bifrost(monkeypatch, routes=("qwen_route",))
        monkeypatch.delenv("BIFROST_VIRTUAL_KEY", raising=False)
        monkeypatch.setattr("mahavishnu.bifrost.cache_headers.resolve_virtual_key", lambda: None)

        captured = self._capture(monkeypatch)
        headers = captured[0].providers["minimax"]["default_headers"]
        assert "x-bf-vk" not in headers
        assert headers["x-bf-cache-key"] == "default"
        assert headers["x-bf-cache-type"] == "semantic"
