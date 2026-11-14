"""Tests for CloudWorker and its Bifrost routing (REQ-BIFROST-008).

The plan §5 Phase 2 contract: ``_build_fallback_chain`` reads the
``minimax`` provider's ``base_url`` from
``oneiric.adapters.llm.bifrost.get_router().resolve(LLMProvider.OPENAI)``
when the router is enabled + routed, otherwise falls back to
``config.minimax_url``. The ``llama_server`` provider is unchanged —
local providers stay direct.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from mahavishnu.bifrost.cache_headers import (
    TRAFFIC_CLASS_WORKER,
    resolve_cache_bucket,
)
from mahavishnu.core.model_routing import (
    MODELS_CONFIG_PATH_ENV,
    _reset_routing_cache,
)
from mahavishnu.workers.cloud_worker import (
    CloudWorkerConfig,
    _build_fallback_chain,
    _resolve_minimax_endpoint,
)

if TYPE_CHECKING:
    from pathlib import Path


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
    # The optional RunPod tier is an operator feature, not part of these
    # Bifrost routing tests. Prevent a developer-shell environment variable
    # from changing the asserted fallback chain.
    monkeypatch.delenv("RUNPOD_PUBLIC_ENDPOINT_ID", raising=False)
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

    def test_returns_router_url_with_v1_suffix(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
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
        changed its router default to include ``/v1`` -- a path the
        gateway does not serve (``POST`` returns 405 Method Not
        Allowed). The helper has to accept both forms.
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

    def test_chain_uses_router_when_enabled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _enable_bifrost(monkeypatch, routes=("qwen_route",))

        captured: list = []
        real_from_settings = None
        from oneiric.adapters.llm import FallbackChain

        real_from_settings = FallbackChain.from_settings

        def capture(settings):
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
            captured[0].providers["minimax"]["base_url"] == "http://127.0.0.1:8471/v1"
        )
        # llama_server is unchanged — local providers stay direct.
        assert (
            captured[0].providers["llama_server"]["base_url"] == "http://localhost:8081"
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
        from oneiric.adapters.llm import FallbackChain

        real_from_settings = FallbackChain.from_settings

        def capture(settings):
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
            captured[0].providers["minimax"]["base_url"] == "https://api.minimax.io/v1"
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
        from oneiric.adapters.llm import FallbackChain
        from oneiric.adapters.llm.bifrost import reset_router_for_tests

        monkeypatch.setenv("ONEIRIC_BIFROST_ENABLED", "true")
        monkeypatch.setenv("ONEIRIC_BIFROST_ROUTES", "claude_route,qwen_route")
        monkeypatch.delenv("BIFROST_ALLOW_REMOTE", raising=False)
        reset_router_for_tests()

        captured: list = []
        real_from_settings = FallbackChain.from_settings

        def capture(settings):
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
            captured[0].providers["minimax"]["base_url"] == "http://127.0.0.1:8471/v1"
        )


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
        from oneiric.adapters.llm import FallbackChain

        captured: list = []
        real_from_settings = FallbackChain.from_settings

        def capture(settings):
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

    def test_no_gateway_headers_when_routed_direct(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A direct-to-MiniMax provider must not carry gateway headers."""
        from oneiric.adapters.llm.bifrost import reset_router_for_tests

        monkeypatch.delenv("ONEIRIC_BIFROST_ENABLED", raising=False)
        reset_router_for_tests()
        monkeypatch.setenv("BIFROST_VIRTUAL_KEY", "sk-bf-test-key")

        captured = self._capture(monkeypatch)
        assert captured[0].providers["minimax"]["default_headers"] == {}

    def test_cache_type_follows_the_configured_mode(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``direct`` reaches the request as ``x-bf-cache-type: direct``."""
        _enable_bifrost(monkeypatch, routes=("qwen_route",))
        monkeypatch.setenv("BIFROST_VIRTUAL_KEY", "sk-bf-test-key")
        monkeypatch.setenv("ONEIRIC_BIFROST_CACHE_MODE", "direct")

        captured = self._capture(monkeypatch)
        headers = captured[0].providers["minimax"]["default_headers"]
        assert headers["x-bf-cache-type"] == "direct"
        # The bucket is derived from the traffic class and the credential
        # the request presents, so it is not the shared default.
        assert headers["x-bf-cache-key"] == resolve_cache_bucket(
            TRAFFIC_CLASS_WORKER, "sk-bf-test-key"
        )
        assert headers["x-bf-cache-key"] != "default"

    def test_semantic_mode_leaves_the_lookup_to_the_gateway(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``semantic`` must not pin the lookup to the semantic path.

        Sending ``x-bf-cache-type`` limits the lookup to one path. Leaving
        it off is Bifrost's documented default -- the free exact-match path
        first, similarity as the fallback -- and the only order in which a
        request over the embedding model's input ceiling still gets a
        lookup at all.
        """
        _enable_bifrost(monkeypatch, routes=("qwen_route",))
        monkeypatch.setenv("BIFROST_VIRTUAL_KEY", "sk-bf-test-key")
        monkeypatch.setenv("ONEIRIC_BIFROST_CACHE_MODE", "semantic")

        captured = self._capture(monkeypatch)
        headers = captured[0].providers["minimax"]["default_headers"]
        assert "x-bf-cache-type" not in headers
        assert headers["x-bf-cache-key"] == resolve_cache_bucket(
            TRAFFIC_CLASS_WORKER, "sk-bf-test-key"
        )

    def test_off_mode_suppresses_the_cache_write(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
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
        monkeypatch.setattr(
            "mahavishnu.bifrost.cache_headers.resolve_virtual_key", lambda: None
        )

        captured = self._capture(monkeypatch)
        headers = captured[0].providers["minimax"]["default_headers"]
        assert "x-bf-vk" not in headers
        # No credential means the gateway rejects the request anyway, but
        # the bucket is still derived rather than shared.
        assert headers["x-bf-cache-key"] == resolve_cache_bucket(
            TRAFFIC_CLASS_WORKER, None
        )
        assert headers["x-bf-cache-key"] != "default"
        assert "x-bf-cache-type" not in headers


class TestDefaultModelIsNotRetired:
    """``CloudWorkerConfig.model`` must not name a retired MiniMax model.

    It is the fallback for any task category the routing table does not
    cover, so a retired name here is a silent dead end for exactly the
    requests nobody thought to route. MiniMax closes M2.7/M2.5 to new users
    on 2026-10-19 and retires them on 2026-11-18.
    """

    def test_default_model_is_current(self) -> None:
        assert CloudWorkerConfig().model == "MiniMax-M3"

    def test_default_model_is_not_a_retired_m2_model(self) -> None:
        model = CloudWorkerConfig().model
        assert "M2." not in model, (
            f"default model {model!r} is on the retired M2.x line (upstream retirement 2026-11-18)"
        )


class TestReasoningEffortPolicy:
    """The operator's thinking-depth policy reaches the provider config.

    ``settings/models.yaml`` carries ``minimax.reasoning_effort`` -- a map
    from the *resolved* model id to an effort level. The cloud worker hands
    that map to oneiric's ``ProviderConfig``, which looks the level up by
    the model it is about to call.

    A model id that is not in the map is a configuration miss: the provider
    logs it and falls back to that model's provider default, which on
    ``MiniMax-M3.1-Flash`` is ``max`` -- the deepest, slowest tier. That
    makes a rename in the routing table a real hazard, so it gets a test.
    """

    @pytest.fixture(autouse=True)
    def _clean_routing_cache(self):
        """Reset the parsed operator config around every test."""
        _reset_routing_cache()
        yield
        _reset_routing_cache()

    @staticmethod
    def _write_config(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        body: str,
    ) -> None:
        """Point the operator-config loader at a temporary file."""
        path = tmp_path / "models.yaml"
        path.write_text(body, encoding="utf-8")
        monkeypatch.setenv(MODELS_CONFIG_PATH_ENV, str(path))
        _reset_routing_cache()

    def test_configured_map_reaches_the_provider_config(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The operator's map survives the trip into ``ProviderConfig``.

        The map is validated on the way in: oneiric's ``ProviderConfig``
        rejects an effort level outside its vocabulary, and an invalid
        level must fail there rather than be quietly dropped by the
        loader -- a dropped entry would put ``MiniMax-M3.1-Flash`` back
        on its ``max`` provider default.
        """
        from oneiric.adapters.llm.config import ProviderConfig

        self._write_config(
            tmp_path,
            monkeypatch,
            "minimax:\n"
            "  reasoning_effort:\n"
            "    'MiniMax-M3': 'adaptive'\n"
            "    'MiniMax-M3.1-Flash': 'low'\n",
        )

        captured: list = []
        from oneiric.adapters.llm import FallbackChain

        real_from_settings = FallbackChain.from_settings

        def capture(settings):
            captured.append(settings)
            return real_from_settings(settings)

        with patch.object(FallbackChain, "from_settings", side_effect=capture):
            _build_fallback_chain(CloudWorkerConfig())

        assert len(captured) == 1
        raw = captured[0].providers["minimax"]
        assert raw["reasoning_effort"] == {
            "MiniMax-M3": "adaptive",
            "MiniMax-M3.1-Flash": "low",
        }
        # The same dict oneiric hands to ProviderConfig -- so this asserts
        # the policy survives validation, not merely that it was copied.
        provider_config = ProviderConfig(**raw)
        assert provider_config.reasoning_effort == {
            "MiniMax-M3": "adaptive",
            "MiniMax-M3.1-Flash": "low",
        }

    def test_renamed_model_id_is_reported_as_a_configuration_miss(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A model the policy does not name is reported, not silently kept.

        The operator renames the flash model in the routing table and
        forgets the policy. The provider must log the miss, because the
        alternative -- the provider default -- is ``max`` on that model.

        The provider's resolver is reached directly: the public path
        (``execute``) would issue a live HTTP call to MiniMax, and the
        warning is emitted before the request is built.
        """
        import logging

        self._write_config(
            tmp_path,
            monkeypatch,
            "minimax:\n"
            "  task_routing:\n"
            "    SWARM: 'MiniMax-M3.1-Flash-v2'\n"
            "  reasoning_effort:\n"
            "    'MiniMax-M3': 'adaptive'\n",
        )

        chain = _build_fallback_chain(CloudWorkerConfig())
        minimax = next(p for p in chain._providers if p.name == "minimax")

        with caplog.at_level(logging.WARNING, logger="oneiric.adapters.llm.provider"):
            effort = minimax._resolve_reasoning_effort("MiniMax-M3.1-Flash-v2")

        assert effort is None, "a model with no policy entry falls back to the default"
        assert "has no reasoning_effort entry" in caplog.text
        assert "MiniMax-M3.1-Flash-v2" in caplog.text
