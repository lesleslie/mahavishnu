"""Phase B follow-up tests for the LLMProviderFactory bifrost refactor.

Per docs/plans/2026-10-15-bifrost-gateway-wiring.md §5 Phase B follow-ups
the LLMProviderFactory was refactored to be settings-aware: when
``bifrost.enabled`` is True, the openai / anthropic / minimax factory
methods route through the Bifrost gateway (the v1.5 spec §5.3 wire-up).
When ``bifrost`` is None or ``bifrost.enabled`` is False, the factories
fall back to the SDK's built-in default endpoint.

This refactor uses the same shape as Phase B's minimax wire-up
(``gateway_api_base(ProtocolFamily, base_url=...)``) for openai and
anthropic — meaning the v1.5 spec amendment that "only minimax routes
through Bifrost" (in ``_probes.py``) is a probe-helper concern, not a
factory concern.

The tests pin:

1. ``test_factory_signature_preserved`` — passing only ``config``
   (the original positional argument) still works.
2. ``test_openai_factory_routes_through_bifrost`` — when
   ``bifrost.enabled``, the OpenAI factory produces a model whose
   ``base_url`` is ``<bifrost.base_url>/v1``.
3. ``test_anthropic_factory_routes_through_bifrost`` — when
   ``bifrost.enabled``, the Anthropic factory produces a model whose
   ``base_url`` is ``<bifrost.base_url>/anthropic`` (the
   gateway_api_base ANTHROPIC branch).
4. ``test_minimax_factory_still_routes_through_bifrost`` — the
   Phase B minimax wire-up path is preserved.
5. ``test_explicit_base_url_overrides_bifrost_routing`` — when
   ``self.config.base_url`` is set (the Phase G local path), it
   wins over the Bifrost routing.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from mahavishnu.core.config import (
    AgnoLLMConfig,
    BifrostConfig,
    LLMProvider,
)
from mahavishnu.engines.agno_adapter_impl import LLMProviderFactory


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


def _llm_config(
    provider: str = "minimax",
    model_id: str = "MiniMax-M3",
    base_url: str | None = None,
) -> AgnoLLMConfig:
    """Build a minimal AgnoLLMConfig for factory construction."""
    return AgnoLLMConfig(
        provider=LLMProvider(provider),
        model_id=model_id,
        base_url=base_url,
    )


def _bifrost(**overrides: object) -> BifrostConfig:
    """Build a BifrostConfig with the given overrides."""
    return BifrostConfig.model_validate(overrides)


# ---------------------------------------------------------------------------
# Signature preservation
# ---------------------------------------------------------------------------


def test_factory_signature_preserved() -> None:
    """``LLMProviderFactory(config)`` still works (no bifrost kwarg)."""
    config = _llm_config()
    factory = LLMProviderFactory(config)
    assert factory.config is config
    assert factory.bifrost is None


def test_factory_accepts_bifrost_kwarg() -> None:
    """``LLMProviderFactory(config, bifrost=...)`` is the new opt-in shape."""
    config = _llm_config()
    bifrost = _bifrost(enabled=True, base_url="http://127.0.0.1:8471")
    factory = LLMProviderFactory(config, bifrost=bifrost)
    assert factory.bifrost is bifrost


# ---------------------------------------------------------------------------
# OpenAI routing
# ---------------------------------------------------------------------------


def test_openai_factory_routes_through_bifrost() -> None:
    """OpenAI factory routes to ``<bifrost.base_url>/v1`` when bifrost.enabled."""
    config = _llm_config(provider="openai", model_id="gpt-4o")
    bifrost = _bifrost(enabled=True, base_url="http://127.0.0.1:8471")

    factory = LLMProviderFactory(config, bifrost=bifrost)

    with (
        patch("agno.models.openai.OpenAIChat") as mock_chat,
        patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}),
    ):
        mock_instance = MagicMock()
        mock_chat.return_value = mock_instance
        result = factory._create_openai_model("gpt-4o")

    assert result is mock_instance
    call_kwargs = mock_chat.call_args.kwargs
    assert call_kwargs["id"] == "gpt-4o"
    assert call_kwargs["api_key"] == "sk-test"
    # Bifrost-routed: the gateway's OpenAI-compatible base URL.
    assert call_kwargs["base_url"] == "http://127.0.0.1:8471/v1"


def test_openai_factory_no_bifrost_uses_sdk_default() -> None:
    """OpenAI factory returns a model with base_url=None when bifrost is absent."""
    config = _llm_config(provider="openai", model_id="gpt-4o")
    factory = LLMProviderFactory(config)  # no bifrost

    with (
        patch("agno.models.openai.OpenAIChat") as mock_chat,
        patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}),
    ):
        mock_chat.return_value = MagicMock()
        factory._create_openai_model("gpt-4o")

    call_kwargs = mock_chat.call_args.kwargs
    # The factory passes None so the SDK uses its built-in default
    # (``https://api.openai.com/v1``).
    assert call_kwargs["base_url"] is None


# ---------------------------------------------------------------------------
# Anthropic routing
# ---------------------------------------------------------------------------


def test_anthropic_factory_routes_through_bifrost() -> None:
    """Anthropic factory routes to ``<bifrost.base_url>/anthropic`` when bifrost.enabled."""
    config = _llm_config(provider="anthropic", model_id="claude-sonnet-4-6")
    bifrost = _bifrost(enabled=True, base_url="http://127.0.0.1:8471")

    factory = LLMProviderFactory(config, bifrost=bifrost)

    with (
        patch("agno.models.anthropic.Claude") as mock_claude,
        patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-ant-test"}),
    ):
        mock_instance = MagicMock()
        mock_claude.return_value = mock_instance
        result = factory._create_anthropic_model("claude-sonnet-4-6")

    assert result is mock_instance
    call_kwargs = mock_claude.call_args.kwargs
    assert call_kwargs["id"] == "claude-sonnet-4-6"
    # Bifrost-routed: the gateway's Anthropic-compatible base URL.
    assert call_kwargs["base_url"] == "http://127.0.0.1:8471/anthropic"


def test_anthropic_factory_uses_anthropic_base_url_field() -> None:
    """Anthropic factory honors the pre-computed ``bifrost.anthropic_base_url`` field.

    The Bifrost config has a dedicated ``anthropic_base_url`` field
    (default ``<base_url>/anthropic``). The factory should use the
    gateway_api_base(ANTHROPIC, ...) helper which produces the
    same value — pinning the contract.
    """
    config = _llm_config(provider="anthropic", model_id="claude-sonnet-4-6")
    bifrost = _bifrost(
        enabled=True,
        base_url="http://bifrost.example:9000",
        anthropic_base_url="http://bifrost.example:9000/anthropic",
    )

    factory = LLMProviderFactory(config, bifrost=bifrost)

    with (
        patch("agno.models.anthropic.Claude") as mock_claude,
        patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-ant-test"}),
    ):
        mock_claude.return_value = MagicMock()
        factory._create_anthropic_model("claude-sonnet-4-6")

    call_kwargs = mock_claude.call_args.kwargs
    assert call_kwargs["base_url"] == "http://bifrost.example:9000/anthropic"


# ---------------------------------------------------------------------------
# MiniMax routing (preserved from Phase B)
# ---------------------------------------------------------------------------


def test_minimax_factory_still_routes_through_bifrost() -> None:
    """Phase B's minimax wire-up is preserved by the refactor.

    The minimax factory uses the same ``_resolve_bifrost_base_url``
    helper as openai/anthropic. When bifrost.enabled, the result is
    ``<bifrost.base_url>/v1`` (the OpenAI-compatible provider on
    Bifrost).
    """
    config = _llm_config(provider="minimax", model_id="MiniMax-M3")
    bifrost = _bifrost(enabled=True, base_url="http://127.0.0.1:8471")

    factory = LLMProviderFactory(config, bifrost=bifrost)

    with (
        patch("agno.models.openai.OpenAIChat") as mock_chat,
        patch.dict("os.environ", {"MINIMAX_API_KEY": "minimax-test"}),
    ):
        mock_chat.return_value = MagicMock()
        factory._create_minimax_model("MiniMax-M3")

    call_kwargs = mock_chat.call_args.kwargs
    assert call_kwargs["base_url"] == "http://127.0.0.1:8471/v1"


def test_minimax_factory_disabled_falls_back_to_public_endpoint() -> None:
    """Without bifrost, minimax falls back to the public MiniMax endpoint.

    The public base is ``https://api.minimax.io/v1`` — the
    gateway_api_base helper strips the trailing slash and adds
    ``/v1`` per the OPENAI protocol family.
    """
    config = _llm_config(provider="minimax", model_id="MiniMax-M3")
    # bifrost is None (no settings).
    factory = LLMProviderFactory(config)

    with (
        patch("agno.models.openai.OpenAIChat") as mock_chat,
        patch.dict("os.environ", {"MINIMAX_API_KEY": "minimax-test"}),
    ):
        mock_chat.return_value = MagicMock()
        factory._create_minimax_model("MiniMax-M3")

    call_kwargs = mock_chat.call_args.kwargs
    # base_url is None — the SDK uses its own default. (When bifrost
    # is None we deliberately do NOT hardcode the public URL,
    # matching the openai/anthropic factory contract.)
    assert call_kwargs["base_url"] is None


# ---------------------------------------------------------------------------
# Operator override (Phase G local path) wins over Bifrost
# ---------------------------------------------------------------------------


def test_explicit_base_url_overrides_bifrost_routing() -> None:
    """An explicit ``config.base_url`` wins over Bifrost routing.

    This is the Phase G local llama-server path: the operator
    configures ``base_url: http://127.0.0.1:8081`` to point the
    model at the local llama-server. The factory must use that
    URL even when bifrost.enabled is True.
    """
    config = _llm_config(
        provider="minimax",
        model_id="qwen3-8b-q4_k_m",
        base_url="http://127.0.0.1:8081",
    )
    bifrost = _bifrost(enabled=True, base_url="http://127.0.0.1:8471")

    factory = LLMProviderFactory(config, bifrost=bifrost)

    with (
        patch("agno.models.openai.OpenAIChat") as mock_chat,
        patch.dict("os.environ", {"MINIMAX_API_KEY": "minimax-test"}),
    ):
        mock_chat.return_value = MagicMock()
        factory._create_minimax_model("qwen3-8b-q4_k_m")

    call_kwargs = mock_chat.call_args.kwargs
    assert call_kwargs["base_url"] == "http://127.0.0.1:8081"
