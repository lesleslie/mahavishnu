"""Production Agno adapter for multi-agent AI orchestration.

This module implements the AgnoAdapter using the real Agno SDK (v3.1.2+)
for agent-based workflows with multi-agent team support.

Key Features:
- Multi-agent team orchestration
- Native MCP tool integration
- Native Agno tools (file operations, code analysis)
- Multiple LLM provider support (Anthropic, OpenAI, llama_server, MiniMax)
- Memory and session management
- OpenTelemetry instrumentation

SDK Verified: 2026-10-29 against Agno v3.1.11 (the pyproject floor is 3.1.2)
"""

from __future__ import annotations

import asyncio
from collections import deque
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
import json
import logging
import os
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, ClassVar, Literal, cast

import httpx2 as httpx
from oneiric.adapters.metadata import AdapterMetadata
from tenacity import retry, stop_after_attempt, wait_exponential

from ..bifrost.cache_headers import (
    TRAFFIC_CLASS_AGNO_ANTHROPIC,
    TRAFFIC_CLASS_AGNO_OPENAI,
    build_gateway_headers,
)
from ..bifrost.models import VIRTUAL_KEY_ENV
from ..core.adapters.base import AdapterCapabilities, AdapterType, OrchestratorAdapter
from ..core.capabilities import (
    Capability,
    CapabilityKind,
    CapabilityState,
    TypeSchema,
)

# Canonical Agno config schema — imported from core.config.
# The previous duplicates of LLMProvider, MemoryBackend, AgnoLLMConfig,
# AgnoMemoryConfig, AgnoToolsConfig, AgnoAdapterConfig lived in this module
# and caused `isinstance(config.agno, AgnoAdapterConfig)` to fail silently
# because the two classes were distinct objects. That made `_get_agno_config`
# return the engine's defaults (provider=llama_server) instead of the user-configured
# values (provider=minimax).
from ..core.config import (
    GATEWAY_ANTHROPIC_MODEL_ID,
    AgnoAdapterConfig,
    AgnoLLMConfig,
    AgnoMemoryConfig,
    AgnoToolsConfig,
    LLMProvider,
    MemoryBackend,
    default_model_for,
)
from ..core.errors import (
    AgnoError,
    ConfigurationError,
    ErrorCode,
)
from ..core.errors import (
    TimeoutError as MahavishnuTimeoutError,
)
from ..core.model_routing import gateway_openai_base_url
from .agno_fallback_model import FallbackModel

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Generator
    from contextlib import AbstractContextManager

    from agno.agent import Agent
    from agno.run.agent import RunOutput
    from agno.team import Team

    from .agno_teams.config import TeamConfig
    from .agno_teams.manager import AgentTeamManager, TeamRunResult
else:
    from .agno_teams.manager import TeamRunResult

logger = logging.getLogger(__name__)


# ============================================================================
# Bifrost routing helpers (oneiric.router integration)
# ============================================================================


@contextmanager
def _anthropic_base_url_ctx(explicit_base_url: str | None = None) -> Generator[None]:
    """Module-level helper backing
    :meth:`LLMProviderFactory._anthropic_base_url_ctx`.

    Resolves the oneiric Bifrost router's ``ANTHROPIC_BASE_URL``,
    sets it for the duration of the ``with`` block, and restores
    the prior value on exit (or removes the env var if it was
    previously unset). No-op when the router is not routed.

    Args:
        explicit_base_url: An operator-supplied endpoint, used verbatim
            and taking precedence over the router. When None the router
            is consulted.

    The Anthropic SDK reads ``ANTHROPIC_BASE_URL`` at client
    ``__init__`` time. Scoping the mutation to the ``Claude(...)``
    call avoids:

    - permanent ``os.environ`` mutation across the process
      lifetime (sibling workers / probes / diagnostics would see
      the stale gateway URL after the first Anthropic factory call),
    - test pollution — the prior value is restored on ``__exit__``
      so other test classes are not affected by a test that set
      the env var.
    """
    from oneiric.adapters.llm.bifrost import get_router
    from oneiric.adapters.llm.llm_interface import LLMProvider

    if explicit_base_url is not None:
        resolved: str | None = explicit_base_url
    else:
        resolved = get_router().resolve(LLMProvider.ANTHROPIC)
    if resolved is None:
        yield
        return
    previous = os.environ.get("ANTHROPIC_BASE_URL")
    os.environ["ANTHROPIC_BASE_URL"] = resolved
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("ANTHROPIC_BASE_URL", None)
        else:
            os.environ["ANTHROPIC_BASE_URL"] = previous


# ============================================================================
# Agent Results
# ============================================================================


@dataclass
class AgentRunResult:
    """Result from a single agent run."""

    agent_name: str
    content: str
    run_id: str
    success: bool = True
    error: str | None = None
    tokens_used: int = 0
    latency_ms: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


# ============================================================================
# LLM Provider Factory
# ============================================================================


@dataclass(frozen=True)
class _ResolvedEndpoint:
    """Where a provider's LLM calls should go, and how to authenticate.

    Attributes:
        base_url: The endpoint base URL, or ``None`` to use the Agno SDK
            provider's own default (e.g. ``https://api.openai.com/v1``).
        via_gateway: True when the URL came from the oneiric Bifrost
            router rather than an operator override. The gateway
            authenticates with a *virtual key* — it rejects a provider's
            own API key with ``401 virtual_key_required`` — so the
            credential differs from the direct-provider case.
        api_key_env: Environment variable holding the credential.
            ``None`` for local providers that need no authentication.
        gateway_model_id: Model id the gateway's provider surface serves,
            when it differs from the provider's own catalogue. The
            gateway's ``anthropic`` provider is Anthropic-protocol
            *shaped* but MiniMax-backed, so it serves MiniMax model ids.
    """

    base_url: str | None
    via_gateway: bool
    api_key_env: str | None
    gateway_model_id: str | None = None


class LLMProviderFactory:
    """Factory for creating LLM model instances for Agno agents.

    Uses the verified Agno v3.1.x import paths:
    - OpenAIChat from agno.models.openai
    - OpenAIChat (llama_server) from agno.models.openai.like
    - Claude from agno.models.anthropic

    IMPORTANT: Model instantiation uses `id=` parameter, NOT `model=`.

    Providers are tried in order: the configured provider first, then each
    entry of ``AgnoLLMConfig.fallback_providers``. The first provider with
    usable credentials wins, so a missing MiniMax key degrades to the
    local llama-server rather than failing the adapter outright.
    """

    def __init__(
        self,
        config: AgnoLLMConfig,
    ):
        """Initialize factory with LLM configuration.

        Args:
            config: LLM configuration specifying provider and model settings.

        The prior ``bifrost: BifrostConfig | None = None`` parameter
        was removed in Phase 7 (REQ-BIFROST-005). The factory now
        consults the oneiric ``BifrostLLMRouter`` directly via
        ``get_router()._settings`` — caller-spoofable settings were
        a real attack surface (a caller could pass
        ``BifrostConfig(enabled=True, base_url=...)`` to override
        the file-config). The router is the single source of truth.
        """
        self.config = config
        self._model_instance = None

    _PROVIDER_FACTORY_METHODS: ClassVar[dict[str, str]] = {
        LLMProvider.OPENAI: "_create_openai_model",
        LLMProvider.ANTHROPIC: "_create_anthropic_model",
        LLMProvider.LLAMA_SERVER: "_create_llama_server_model",
        LLMProvider.MINIMAX: "_create_minimax_model",
    }

    #: Standard credential env var per provider. Mirrors
    #: ``AgnoLLMConfig._default_api_key_env``; kept here so the factory can
    #: resolve a *fallback* provider's credential without reconstructing a
    #: whole config for it.
    _PROVIDER_API_KEY_ENV: ClassVar[dict[str, str | None]] = {
        LLMProvider.ANTHROPIC: "ANTHROPIC_API_KEY",
        LLMProvider.OPENAI: "OPENAI_API_KEY",
        LLMProvider.MINIMAX: "MINIMAX_API_KEY",
        LLMProvider.LLAMA_SERVER: None,  # local, no key required
    }

    def _instantiate_model(
        self,
        provider: str,
        model_id: str,
        factory_name: str,
        endpoint: _ResolvedEndpoint,
    ) -> Any:
        try:
            instance = getattr(self, factory_name)(model_id, endpoint)
            logger.info(f"Created LLM model: provider={provider}, model_id={model_id}")
            return instance
        except ImportError as e:
            raise AgnoError(
                f"Failed to import LLM provider '{provider}': {e}",
                error_code=ErrorCode.AGNO_LLM_PROVIDER_ERROR,
                details={"provider": provider, "import_error": str(e)},
            ) from e

    def _effective_providers(self) -> list[LLMProvider]:
        """The ordered provider chain: configured provider, then fallbacks.

        Duplicates are dropped so a provider listed both as the primary and
        as a fallback is only tried once.
        """
        chain: list[LLMProvider] = [self.config.provider]
        for provider in self.config.fallback_providers:
            if provider not in chain:
                chain.append(provider)
        return chain

    def _model_id_for(self, provider: LLMProvider, endpoint: _ResolvedEndpoint) -> str:
        """Model id to use for ``provider``.

        The configured provider keeps whatever the operator pinned. A
        *fallback* uses its own default, because model ids are
        provider-scoped — ``MiniMax-M3`` is meaningless to llama-server and
        the MiniMax API rejects unknown model names outright.

        A gateway-routed provider prefers the gateway's own catalogue id
        (``endpoint.gateway_model_id``) unless the operator pinned a model
        id explicitly, because the gateway's provider surface may serve a
        different catalogue than the upstream vendor's.
        """
        if provider == self.config.provider and "model_id" in self.config.model_fields_set:
            return self.config.model_id
        if endpoint.gateway_model_id is not None:
            return endpoint.gateway_model_id
        if provider == self.config.provider:
            return self.config.model_id
        return default_model_for(provider)

    def _gateway_url(self, provider: LLMProvider) -> str | None:
        """The Bifrost gateway URL for ``provider``, or None when not routed.

        Returns None when the router is disabled or the provider's route is
        not configured — in which case the caller falls back to the
        provider's own public endpoint.
        """
        from oneiric.adapters.llm.bifrost import get_router
        from oneiric.adapters.llm.llm_interface import LLMProvider as OneiricLLMProvider

        if provider is LLMProvider.ANTHROPIC:
            resolved = get_router().resolve(OneiricLLMProvider.ANTHROPIC)
            return str(resolved) if resolved is not None else None

        resolved = get_router().resolve(OneiricLLMProvider.OPENAI)
        if resolved is None:
            return None
        return gateway_openai_base_url(resolved)

    def _resolve_endpoint(self, provider: LLMProvider) -> _ResolvedEndpoint:
        """Resolve the endpoint and credential for ``provider``.

        Resolution order:

        1. ``self.config.base_url`` — explicit operator override. Not
           treated as a gateway URL, so the provider's own API key is used.
        2. The oneiric Bifrost router — when enabled and the matching
           route is configured. The gateway validates a *virtual key*
           (``BIFROST_VIRTUAL_KEY``), not the provider's own key, so this
           resolves the credential to the virtual key.
        3. The provider's public API — ``base_url=None`` lets the Agno SDK
           use its own default endpoint.

        llama-server is local: it always targets ``http://localhost:8081``
        (or an operator override) and needs no credential.

        The configured ``base_url`` and ``api_key_env`` apply to the
        *configured* provider only. A fallback provider resolves its own
        endpoint and its own credential, so the primary's key is never
        sent to a different vendor.
        """
        is_primary = provider == self.config.provider
        if provider is LLMProvider.LLAMA_SERVER:
            # The local endpoint is only overridden by the configured
            # base_url when llama-server *is* the configured provider —
            # a base_url set for a cloud provider must not be inherited
            # by the local fallback.
            base_url = self.config.base_url if is_primary else None
            return _ResolvedEndpoint(
                base_url=base_url or "http://localhost:8081",
                via_gateway=False,
                api_key_env=None,
            )

        # The configured ``api_key_env`` belongs to the *configured*
        # provider. A fallback provider must use its own standard env var,
        # otherwise the primary's credential would be sent to a different
        # vendor's endpoint — e.g. MINIMAX_API_KEY posted to OpenAI.
        if is_primary:
            api_key_env = self.config.api_key_env or self._PROVIDER_API_KEY_ENV.get(provider)
        else:
            api_key_env = self._PROVIDER_API_KEY_ENV.get(provider)

        # Likewise, an explicit base_url overrides the gateway only for
        # the provider it was configured for.
        if is_primary and self.config.base_url:
            return _ResolvedEndpoint(self.config.base_url, False, api_key_env)

        gateway_url = self._gateway_url(provider)
        if gateway_url is not None:
            gateway_model_id = (
                GATEWAY_ANTHROPIC_MODEL_ID if provider is LLMProvider.ANTHROPIC else None
            )
            return _ResolvedEndpoint(gateway_url, True, VIRTUAL_KEY_ENV, gateway_model_id)

        return _ResolvedEndpoint(None, False, api_key_env)

    def _provider_available(self, provider: LLMProvider, endpoint: _ResolvedEndpoint) -> bool:
        """Whether ``provider`` can serve a request in the current environment.

        Availability is credential presence: a cloud provider without its
        key (or without the gateway virtual key when routed through
        Bifrost) cannot be used. llama-server is local and is always
        considered available.
        """
        if provider is LLMProvider.LLAMA_SERVER:
            return True
        if endpoint.api_key_env is None:
            return False
        return bool(os.getenv(endpoint.api_key_env))

    def _available_models(self) -> tuple[list[tuple[LLMProvider, Any]], Exception | None]:
        """Build a model for every provider in the chain that is usable.

        Providers are walked in chain order. A provider whose credentials
        are missing is skipped; a provider that fails to construct is
        skipped too, so one broken provider does not disable the rest of
        the chain. An ``ImportError`` propagates — that is a broken SDK
        integration, not a provider outage, and failing over would hide it.

        Returns:
            ``(models, last_error)`` — the ordered ``(provider, model)``
            pairs for the usable providers, and the last construction
            error when at least one provider was reachable but failed.
        """
        built: list[tuple[LLMProvider, Any]] = []
        last_error: Exception | None = None
        chain = self._effective_providers()

        for provider in chain:
            factory_name = self._PROVIDER_FACTORY_METHODS.get(provider)
            if factory_name is None:
                if provider == self.config.provider:
                    raise AgnoError(
                        f"Unsupported LLM provider: {provider}",
                        error_code=ErrorCode.AGNO_LLM_PROVIDER_ERROR,
                        details={"provider": provider},
                    )
                logger.warning("Skipping unsupported Agno LLM fallback provider: %s", provider)
                continue

            endpoint = self._resolve_endpoint(provider)
            if not self._provider_available(provider, endpoint):
                logger.warning(
                    "Agno LLM provider %s unavailable (no usable credential for %s); "
                    "trying next provider in the chain",
                    provider,
                    endpoint.api_key_env or "<none>",
                )
                continue

            model_id = self._model_id_for(provider, endpoint)
            try:
                model = self._instantiate_model(provider, model_id, factory_name, endpoint)
            except (AgnoError, ConfigurationError) as exc:  # fmt: skip
                if "import_error" in getattr(exc, "details", {}):
                    raise
                last_error = exc
                logger.warning(
                    "Agno LLM provider %s failed to initialize (%s); trying next provider",
                    provider,
                    exc,
                )
                continue
            # A provider-side failure must not abort the chain — the next
            # provider in the chain gets its turn.
            except Exception as e:  # noqa: BLE001, RUF100
                last_error = AgnoError(
                    f"Failed to create LLM model: {e}",
                    error_code=ErrorCode.AGNO_LLM_PROVIDER_ERROR,
                    details={"provider": provider, "model_id": model_id, "error": str(e)},
                )
                logger.warning(
                    "Agno LLM provider %s failed to initialize (%s); trying next provider",
                    provider,
                    e,
                )
                continue

            logger.info(
                "Agno LLM provider available: provider=%s model_id=%s base_url=%s gateway=%s",
                provider,
                model_id,
                endpoint.base_url or "<sdk default>",
                endpoint.via_gateway,
            )
            built.append((provider, model))

        return built, last_error

    def create_model_chain(self) -> Any:
        """Create the model the adapter uses, wired for per-call failover.

        Every usable provider in the chain is built. When more than one is
        available the result is a :class:`FallbackModel`, so a provider
        that fails *mid-run* — after the agent has already made tool calls
        — falls through to the next one instead of failing the whole run.

        Returns:
            A single model instance when only one provider is usable,
            otherwise a :class:`FallbackModel` over the usable providers.

        Raises:
            AgnoError: If the configured provider is not supported, or if
                every reachable provider failed to initialize.
            ConfigurationError: If no provider in the chain has a usable
                credential.
        """
        if self._model_instance is not None:
            return self._model_instance

        built, last_error = self._available_models()
        if not built:
            if last_error is not None:
                raise last_error
            primary_env = self._PROVIDER_API_KEY_ENV.get(self.config.provider)
            raise ConfigurationError(
                f"API key not found. Set {primary_env} environment variable.",
                details={
                    "chain": [p.value for p in self._effective_providers()],
                    "env_var": primary_env,
                },
            )

        models = [model for _, model in built]
        self._model_instance = models[0] if len(models) == 1 else FallbackModel(models=models)
        logger.info(
            "Agno LLM chain resolved: providers=%s",
            [provider.value for provider, _ in built],
        )
        return self._model_instance

    def create_model(self) -> Any:
        """Create and return the primary LLM model instance.

        Providers are tried in order — the configured provider first, then
        each entry of ``fallback_providers``. The first provider with
        usable credentials wins, so a missing MiniMax key degrades to the
        local llama-server instead of failing the adapter.

        Returns:
            LLM model instance (OpenAIChat or Claude)

        Raises:
            AgnoError: If the configured provider is not supported, or if
                every provider in the chain failed to initialize.
            ConfigurationError: If no provider in the chain has a usable
                credential.
        """
        chain = self.create_model_chain()
        if isinstance(chain, FallbackModel):
            return chain.models[0]
        return chain

    def _create_openai_model(self, model_id: str, endpoint: _ResolvedEndpoint) -> Any:
        """Create OpenAI model instance.

        Routing (resolved by :meth:`_resolve_endpoint`):
        - ``self.config.base_url`` (explicit) wins always.
        - Else if the oneiric Bifrost router is enabled+routed
          (REQ-BIFROST-002), routes through the gateway at
          ``<router.base_url>/v1`` (the Bifrost OpenAI-compatible
          provider) and authenticates with the gateway virtual key.
        - Else falls back to the SDK default (no base_url — the
          Agno OpenAIChat resolves to ``https://api.openai.com/v1``).

        Args:
            model_id: OpenAI model identifier (e.g., 'gpt-4o', 'gpt-4o-mini')
            endpoint: Resolved endpoint and credential.

        Returns:
            OpenAIChat model instance
        """
        from agno.models.openai import OpenAIChat

        api_key = self._get_api_key(endpoint.api_key_env)

        # req: REQ-BIFROST-035, REQ-BIFROST-037
        #
        # When the request is routed through the Bifrost gateway it needs
        # the gateway's ``x-bf-vk`` header -- the gateway rejects a
        # provider key -- and the ``x-bf-cache-*`` headers that make the
        # operator's ``cache_mode`` setting mean something. The same
        # header builder the cloud worker uses serves both callers, so
        # there is one definition of what a gateway request carries.
        default_headers: dict[str, str] = {}
        if endpoint.via_gateway and endpoint.base_url:
            default_headers = build_gateway_headers(
                endpoint.base_url, traffic_class=TRAFFIC_CLASS_AGNO_OPENAI
            )

        # Use id= parameter (NOT model=) per the Agno v3.1.x API
        return OpenAIChat(
            id=model_id,
            api_key=api_key,
            base_url=endpoint.base_url,
            default_headers=default_headers,
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
        )

    def _create_anthropic_model(self, model_id: str, endpoint: _ResolvedEndpoint) -> Any:
        """Create Anthropic Claude model instance.

        Routing (resolved by :meth:`_resolve_endpoint`):
        - ``self.config.base_url`` (explicit) wins always.
        - Else if the oneiric Bifrost router is enabled+routed
          (REQ-BIFROST-002), sets ``ANTHROPIC_BASE_URL`` from
          ``get_router().resolve(LLMProvider.ANTHROPIC)`` so the
          Anthropic SDK picks it up at client construction. The
          router already returns the gateway's anthropic path
          (``<base>/anthropic``), so no suffix is appended here.
          The env-var mutation is scoped to the ``Claude(...)`` call
          via :meth:`_anthropic_base_url_ctx` — the prior value
          (or absence) is restored on context exit.
        - Else falls back to the SDK default (no env var set — the
          Agno Claude resolves to ``https://api.anthropic.com``).

        Args:
            model_id: Claude model identifier (e.g., 'claude-sonnet-4-6')
            endpoint: Resolved endpoint and credential.

        Returns:
            Claude model instance
        """
        from agno.models.anthropic import Claude

        api_key = self._get_api_key(endpoint.api_key_env)
        # req: REQ-BIFROST-035, REQ-BIFROST-037
        #
        # Same gateway header set as the OpenAI path -- the gateway's
        # anthropic surface authenticates the same way.
        default_headers: dict[str, str] = {}
        if endpoint.via_gateway and endpoint.base_url:
            default_headers = build_gateway_headers(
                endpoint.base_url, traffic_class=TRAFFIC_CLASS_AGNO_ANTHROPIC
            )
        # Claude (Anthropic) is constructed via the Anthropic SDK which
        # reads ``ANTHROPIC_BASE_URL`` at client init. The oneiric
        # Bifrost router's anthropic_base_url is pre-formatted
        # ``<base>/anthropic`` (matches the v1.5 spec).
        with self._anthropic_base_url_ctx(explicit_base_url=endpoint.base_url):
            return Claude(
                id=model_id,
                api_key=api_key,
                default_headers=default_headers,
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
            )

    def _create_llama_server_model(self, model_id: str, endpoint: _ResolvedEndpoint) -> Any:
        """Create llama.cpp server (llama_server) model instance for local LLM.

        Uses Agno's OpenAIChat in OpenAI-compatible mode against a llama.cpp
        HTTP server. The server requires no auth, so ``api_key="no-auth"`` is
        passed to satisfy the OpenAIChat client.

        llama-server is the canonical *local fallback* provider
        (default ``http://localhost:8081``); it is not part of the Bifrost
        cloud-tier routing, and the Bifrost router is intentionally
        ignored here.

        Args:
            model_id: llama.cpp model identifier (e.g., 'qwen3.5', 'llama2')
            endpoint: Resolved endpoint and credential.

        Returns:
            OpenAIChat model instance pointed at the local llama.cpp server
        """
        from agno.models.openai.like import OpenAIChat

        return OpenAIChat(
            id=model_id,
            base_url=endpoint.base_url,
            api_key="no-auth",
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
        )

    def _create_minimax_model(self, model_id: str, endpoint: _ResolvedEndpoint) -> Any:
        """Create MiniMax model instance using the OpenAI-compatible endpoint.

        Routing (resolved by :meth:`_resolve_endpoint`):
        - ``self.config.base_url`` (explicit) wins always — used by
          the Phase G local llama-server path.
        - Else if the oneiric Bifrost router is enabled+routed,
          routes through the gateway at ``<router.base_url>/v1`` and
          authenticates with the gateway virtual key.
        - Else falls back to the public MiniMax OpenAI-compatible
          endpoint (the SDK's built-in default; no ``base_url``
          is passed).

        Args:
            model_id: MiniMax model identifier (e.g., 'MiniMax-M3'). Note: 'MiniMax-M3-highspeed' is not a valid model name on minimax's API — use 'MiniMax-M3' or 'MiniMax-M2.7-highspeed' instead.
            endpoint: Resolved endpoint and credential.

        Returns:
            OpenAIChat model instance configured for MiniMax
        """
        from agno.models.openai import OpenAIChat

        api_key = self._get_api_key(endpoint.api_key_env)

        return OpenAIChat(
            id=model_id,
            api_key=api_key,
            base_url=endpoint.base_url,
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
        )

    def _anthropic_base_url_ctx(
        self, explicit_base_url: str | None = None
    ) -> AbstractContextManager[None]:
        """Context manager that sets ``ANTHROPIC_BASE_URL`` for the duration
        of the ``with`` block, then restores the prior value (or removes the
        env var if it was previously unset).

        The Anthropic SDK reads ``ANTHROPIC_BASE_URL`` at client
        ``__init__`` time. Scoping the mutation to the ``Claude(...)``
        call avoids:

        - permanent ``os.environ`` mutation across the process
          lifetime (sibling workers / probes / diagnostics would
          see the stale gateway URL after the first Anthropic
          factory call),
        - test pollution — the prior value is restored on
          ``__exit__`` so other test classes are not affected by
          a test that set the env var.

        Args:
            explicit_base_url: An operator-supplied endpoint, used
                verbatim. When None the oneiric Bifrost router is
                consulted instead.

        If neither an explicit URL nor a routed gateway is available, the
        context manager is a no-op and the SDK default
        (``https://api.anthropic.com``) takes over.
        """
        return _anthropic_base_url_ctx(explicit_base_url)

    def _get_api_key(self, env_var: str | None) -> str:
        """Get API key from environment.

        Args:
            env_var: Environment variable name holding the credential.
                ``None`` means the provider needs no authentication (the
                local llama-server).

        Returns:
            API key string

        Raises:
            ConfigurationError: If API key is not set
        """
        if env_var is None:
            raise ConfigurationError(
                "No API key environment variable configured for this provider.",
                details={"env_var": env_var},
            )
        api_key = os.getenv(env_var)

        if not api_key:
            raise ConfigurationError(
                f"API key not found. Set {env_var} environment variable.",
                details={"env_var": env_var},
            )

        return api_key


# ============================================================================
# Bifrost dispatch heartbeat (Phase B follow-up)
# ----------------------------------------------------------------------------
# The heartbeat is the bridge between the Agno dispatch surface (which
# Agno owns internally — ``agent.arun`` does not expose the underlying
# HTTP call) and the Bifrost observability surface (the master + local
# counter series in prometheus_metrics.py and the bifrost.log envelope
# the e2e test_agno_dispatch_emits_caller_id greps).
#
# Per Phase B's deferred-work note, the counter increment path was
# "invasive" when wired at the factory's model-creation call site. The
# non-invasive seam is the per-agent ``_run_agent`` call (success +
# failure paths), which is the highest-fidelity "an LLM was invoked"
# signal we own. Granularity is "one heartbeat per agent run" — not
# per-HTTP-retry, which is the right shape for Bifrost observability
# (we care about "did an LLM go through Bifrost?" not "did each retry
# get counted?").
#
# The log write uses compact JSON (``separators=(",", ":")``) so the
# e2e test's grep ``"caller_id":"mahavishnu"`` matches byte-for-byte
# (default ``json.dumps`` produces spaces around ``:`` and ``,``).
# ============================================================================

_BIFROST_LOG_PATH: Path = Path.home() / ".local/state/mcp/logs/bifrost.log"
_BIFROST_HEARTBEAT_CALLER_ID: str = "mahavishnu"


def _bifrost_dispatch_heartbeat(
    *,
    provider: str,
    model: str,
    route_class: str,
    outcome: str,
    latency_seconds: float,
    failure_reason: str | None = None,
    is_local: bool = False,
    caller_id: str = _BIFROST_HEARTBEAT_CALLER_ID,
) -> None:
    """Increment bifrost dispatch counters and append a compact JSON line to bifrost.log.

    Phase B's missing heartbeat. Called from
    :meth:`AgnoAdapter._run_agent` on every LLM dispatch (success and
    failure paths). Emits:

    - ``mahavishnu_bifrost_dispatch_total{outcome, provider, route_class}``
    - ``mahavishnu_bifrost_dispatch_latency_seconds{provider, route_class}``
    - ``mahavishnu_bifrost_dispatch_failures_total{provider, reason}`` on failure
    - ``mahavishnu_bifrost_local_dispatch_total{outcome, provider, route_class}`` if local

    Plus a compact JSON envelope to
    ``~/.local/state/mcp/logs/bifrost.log`` so the e2e
    ``test_agno_dispatch_emits_caller_id`` can grep it. The log line
    uses the exact key/value shape the test asserts on
    (``"caller_id":"mahavishnu"`` — no spaces, compact JSON).

    Counter increments and log writes are best-effort: a Prometheus
    registry failure or an unwritable log path must never break the
    dispatch path.
    """
    # Counter emit. Wrapped in a try/except so a registry failure
    # (e.g. duplicate registration under a different worker) cannot
    # turn a successful LLM run into a 500.
    try:
        from mahavishnu.observability.prometheus_metrics import (
            bifrost_dispatch_failures_total,
            bifrost_dispatch_latency_seconds,
            bifrost_dispatch_total,
            bifrost_local_dispatch_total,
        )

        bifrost_dispatch_total(outcome=outcome, provider=provider, route_class=route_class)
        bifrost_dispatch_latency_seconds(
            provider=provider, route_class=route_class, seconds=latency_seconds
        )
        if outcome == "failure" and failure_reason:
            bifrost_dispatch_failures_total(provider=provider, reason=failure_reason)
        if is_local:
            bifrost_local_dispatch_total(
                outcome=outcome, provider=provider, route_class=route_class
            )
    except Exception:  # best-effort metric emit; dispatch must not break on a metric failure
        logger.exception("bifrost_dispatch_heartbeat: counter emit failed")

    # Append a compact JSON line to bifrost.log. Best-effort; the
    # /health route's bifrost feed is the canonical observability
    # surface — this log line is the e2e test's grep target.
    try:
        _BIFROST_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        envelope: dict[str, object] = {
            "caller_id": caller_id,
            "provider": provider,
            "model": model,
            "route_class": route_class,
            "outcome": outcome,
            "latency_seconds": latency_seconds,
        }
        if failure_reason:
            envelope["failure_reason"] = failure_reason
        with _BIFROST_LOG_PATH.open("a", encoding="utf-8") as fh:
            # Compact JSON: no whitespace between separators, so the
            # e2e grep ``"caller_id":"mahavishnu"`` matches.
            fh.write(json.dumps(envelope, separators=(",", ":")) + "\n")
    except OSError:  # best-effort log write; dispatch must not break on a log failure
        logger.debug("bifrost_dispatch_heartbeat: bifrost.log write failed")


def _resolve_dispatch_heartbeat_args(
    agno_llm_config: AgnoLLMConfig,
) -> tuple[str, str, str, bool]:
    """Derive the heartbeat's (provider, model, route_class, is_local) tuple.

    - ``provider`` is the LLM provider's enum value (e.g. ``"minimax"``,
      ``"openai"``). Same for every dispatch in a given adapter
      instance; resolved once at the top of ``_run_agent`` to avoid
      three attribute lookups per call.
    - ``model`` is the LLM model_id.
    - ``route_class`` is the v1.5 spec's per-task bucket. The
      current adapter doesn't surface task_label at the LLM-call
      level (the LLMProviderFactory.create_model() takes no task
      context), so the heartbeat uses a flat ``"default"``. Future
      v1.6+ work can thread the task_label through Agno and call
      :func:`mahavishnu.llm_gateway.contract.infer_route_class`.
    - ``is_local`` is True when the resolved base_url points to
      localhost / 127.0.0.1 (the Phase G local-provider path).
      Other providers stay direct; only the local llama-server
      increments the local_dispatch counter.

    Returns:
        ``(provider_value, model_id, "default", is_local)`` tuple.
    """
    base_url = getattr(agno_llm_config, "base_url", None) or ""
    is_local = base_url.startswith(("http://localhost", "http://127.0.0.1"))
    return (
        agno_llm_config.provider.value,
        agno_llm_config.model_id,
        "default",
        is_local,
    )


# ============================================================================
# MCP Tools Integration
# ============================================================================


class MCPToolsRegistry:
    """Registry for MCP tools integration with Agno agents.

    Uses Agno's native MCPTools for seamless tool integration.
    Supports SSE and stdio transports.
    """

    def __init__(self, config: AgnoToolsConfig):
        """Initialize MCP tools registry.

        Args:
            config: Tool configuration with MCP server URL and settings
        """
        self.config = config
        self._mcp_tools: Any | None = None
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize MCP tools connection.

        Raises:
            AgnoError: If MCP connection fails
        """
        if self._initialized:
            return

        try:
            from agno.tools.mcp import MCPTools

            configured = self.config.mcp_transport
            if configured == "stdio":
                transport: Literal["stdio", "sse", "streamable-http"] = "stdio"
            elif configured == "sse":
                transport: Literal["stdio", "sse", "streamable-http"] = "sse"
            elif configured == "streamable-http":
                transport: Literal["stdio", "sse", "streamable-http"] = "streamable-http"
            else:
                transport: Literal["stdio", "sse", "streamable-http"] = "sse"
            self._mcp_tools = MCPTools(
                url=self.config.mcp_server_url,
                transport=transport,
            )

            self._initialized = True
            logger.info(
                f"MCP tools initialized: url={self.config.mcp_server_url}, "
                f"transport={self.config.mcp_transport}"
            )

        except Exception as e:  # MCP tools are optional — degrade silently  # background task — broad catch is the documented contract  # noqa: BLE001, RUF100
            logger.warning(f"Failed to initialize MCP tools: {e}")
            # Don't raise - MCP tools are optional
            self._initialized = True

    def get_tools(self) -> list[Any]:
        """Get list of tools for agent use.

        Returns:
            List of tool instances (may be empty if MCP not available)
        """
        if self._mcp_tools is not None:
            return [self._mcp_tools]
        return []

    async def close(self) -> None:
        """Close MCP tools connection."""
        self._mcp_tools = None
        self._initialized = False


# ============================================================================
# Native Tools Registry (Phase 3)
# ============================================================================


class NativeToolsRegistry:
    """Registry for native Agno tools.

    Provides file operations and code analysis tools that can be used
    directly by Agno agents without MCP integration.
    """

    def __init__(self, enabled: bool = True):
        """Initialize native tools registry.

        Args:
            enabled: Whether to enable native tools
        """
        self.enabled = enabled
        self._tools: list[Any] = []

    def get_tools(self) -> list[Any]:
        """Get list of native tool functions.

        Returns:
            List of native tool functions
        """
        if not self.enabled:
            return []

        if self._tools:
            return self._tools

        try:
            # Import native tools from agno_tools module
            from .agno_tools import ALL_TOOLS

            self._tools = list(ALL_TOOLS)
            logger.debug(f"Loaded {len(self._tools)} native tools")
            return self._tools

        except ImportError as e:
            logger.warning(f"Failed to import native tools: {e}")
            return []

    def get_available_tools(self) -> list[str]:
        """Get list of available native tool names.

        Returns:
            List of tool names
        """
        tools = self.get_tools()
        names = []
        for t in tools:
            # Agno Function objects have a .name attribute
            if hasattr(t, "name"):
                names.append(t.name)
            elif hasattr(t, "__name__"):
                names.append(t.__name__)
            else:
                names.append(str(t))
        return names


# ============================================================================
# Main AgnoAdapter Implementation
# ============================================================================


class AgnoAdapter(OrchestratorAdapter):
    """Production Agno adapter for multi-agent AI orchestration.

    This adapter implements the OrchestratorAdapter interface using the
    real Agno SDK (v3.1.2+) for multi-agent team workflows.

    Key Capabilities:
    - Multi-agent team orchestration (supports_multi_agent=True)
    - Native MCP tool integration
    - Native Agno tools (file operations, code analysis) (Phase 3)
    - Multiple LLM providers (Anthropic, OpenAI, llama_server)
    - Memory and session management
    - Batch execution support

    Example:
        ```python
        from mahavishnu.core.config import MahavishnuSettings
        from mahavishnu.engines.agno_adapter_impl import AgnoAdapter

        settings = MahavishnuSettings()
        adapter = AgnoAdapter(config=settings)
        await adapter.initialize()

        # Single agent execution
        result = await adapter.execute(
            task={"type": "code_sweep", "params": {}},
            repos=["/path/to/repo"]
        )

        # Multi-agent team execution (Phase 2)
        from mahavishnu.engines.agno_teams import TeamConfig, TeamMode
        team_config = TeamConfig(
            name="review_team",
            mode=TeamMode.COORDINATE,
            leader=MemberConfig(...),
            members=[MemberConfig(...)],
        )
        team_id = await adapter.create_team(team_config)
        result = await adapter.run_team(team_id, "Review this code")

        await adapter.shutdown()
        ```
    """

    # Class-level constants
    ADAPTER_VERSION: ClassVar[str] = "1.0.0"
    MIN_AGNO_VERSION: ClassVar[str] = "3.1.2"

    def __init__(self, config: Any | None = None, api_url: str | None = None) -> None:
        """Initialize Agno adapter with configuration.

        Args:
            config: MahavishnuSettings instance containing Agno configuration
            api_url: Optional compatibility override for legacy tests and callers
        """
        if config is None and api_url is not None:
            config = SimpleNamespace(api_url=api_url)

        self.config = config

        # Extract Agno-specific configuration
        self.agno_config = self._get_agno_config(config)
        self.api_url = (
            api_url
            or getattr(self.agno_config.tools, "mcp_server_url", None)
            or "http://localhost:8000"
        )

        # Initialize internal state
        self._client: Any | None = None
        self._initialized = False
        self._llm_factory: LLMProviderFactory | None = None
        self._mcp_registry: MCPToolsRegistry | None = None
        self._native_tools_registry: NativeToolsRegistry | None = None
        self._agents: dict[str, Agent] = {}
        self._teams: dict[str, Team] = {}
        self._semaphore: asyncio.Semaphore | None = None
        self._team_manager: AgentTeamManager | None = None
        self._execution_log: deque[dict[str, Any]] = deque(maxlen=200)

        # Set up capabilities
        self._capabilities = AdapterCapabilities(
            can_deploy_flows=True,
            can_monitor_execution=True,
            can_cancel_workflows=True,
            can_sync_state=True,
            supports_batch_execution=True,
            supports_multi_agent=True,
            has_cloud_ui=False,
        )

    def _get_agno_config(self, config: Any) -> AgnoAdapterConfig:
        """Extract Agno configuration from settings.

        Args:
            config: MahavishnuSettings or AgnoAdapterConfig instance

        Returns:
            AgnoAdapterConfig instance
        """
        if isinstance(config, AgnoAdapterConfig):
            return config

        # Try to get agno config from MahavishnuSettings
        if hasattr(config, "agno") and isinstance(config.agno, AgnoAdapterConfig):
            return config.agno

        # Fall back to default config
        return AgnoAdapterConfig()

    @property
    def adapter_type(self) -> AdapterType:
        """Return adapter type enum."""
        return AdapterType.AGNO

    @property
    def name(self) -> str:
        """Return adapter name."""
        return "agno"

    @property
    def capabilities(self) -> AdapterCapabilities:
        """Return adapter capabilities."""
        return self._capabilities

    @property
    def provides(self) -> list[Capability]:
        """Capabilities this engine exposes to the conductor.

        Surfaces multi-agent team orchestration, task decomposition, and
        tool-use loops so the worker-registry-capability-refactor conductor
        (Phase 3a) can route agent-team workloads here.
        """
        return [
            Capability(
                id="engine:multi-agent-team",
                kind=CapabilityKind.ENGINE,
                description="Multi-agent team orchestration with role assignment",
                io_in=TypeSchema(),
                io_out=TypeSchema(),
                state=CapabilityState.EPHEMERAL,
            ),
            Capability(
                id="engine:task-decomposition",
                kind=CapabilityKind.ENGINE,
                description="Decompose complex goals into agent-runnable subtasks",
                io_in=TypeSchema(),
                io_out=TypeSchema(),
                state=CapabilityState.EPHEMERAL,
            ),
            Capability(
                id="engine:tool-use-loop",
                kind=CapabilityKind.ENGINE,
                description="Agent loop with native tool calling and MCP integration",
                io_in=TypeSchema(),
                io_out=TypeSchema(),
                state=CapabilityState.EPHEMERAL,
            ),
        ]

    @property
    def agent_team_manager(self) -> AgentTeamManager | None:
        """Get the agent team manager instance.

        Returns:
            AgentTeamManager instance if initialized, None otherwise.
        """
        return self._team_manager

    async def initialize(self) -> None:
        """Initialize Agno adapter.

        This method:
        1. Validates Agno SDK version
        2. Initializes LLM provider factory
        3. Initializes MCP tools registry
        4. Initializes native tools registry (Phase 3)
        5. Sets up concurrency semaphore
        6. Initializes team manager (Phase 2)

        Raises:
            AgnoError: If initialization fails
        """
        if self._initialized:
            logger.warning("AgnoAdapter already initialized")
            return

        logger.info("Initializing AgnoAdapter...")

        try:
            # Validate Agno SDK
            self._validate_agno_sdk()

            # Initialize LLM provider factory. Phase 7 removed the
            # ``bifrost`` kwarg — the factory now consults
            # ``get_router()._settings`` directly.
            self._llm_factory = LLMProviderFactory(self.agno_config.llm)

            # Initialize MCP tools registry
            self._mcp_registry = MCPToolsRegistry(self.agno_config.tools)
            await self._mcp_registry.initialize()

            # Initialize native tools registry (Phase 3)
            self._native_tools_registry = NativeToolsRegistry(
                enabled=self.agno_config.tools.enable_native_tools
            )

            # Set up concurrency semaphore
            self._semaphore = asyncio.Semaphore(self.agno_config.max_concurrent_agents)

            # Initialize team manager (Phase 2)
            await self._initialize_team_manager()

            self._initialized = True
            # NOTE (2026-10-05): the previous "compatibility ping" — a plain
            # ``httpx.AsyncClient.get(self.api_url)`` — was removed. It
            # 1) didn't actually verify MCP compatibility (a GET on an
            # MCP endpoint doesn't exercise JSON-RPC, streamable-http
            # framing, or any protocol surface), 2) was guaranteed to
            # race the FastMCP server's bind() at startup (the bind
            # completes on the launcher thread; this init runs as a
            # background task scheduled in launch_mcp.py), and 3) the
            # resulting ``All connection attempts failed`` warning was
            # cosmetic noise in the rollup. The init's real
            # compatibility proof is the ``MCPToolsRegistry.initialize``
            # call at line 630 (which actually constructs the MCP
            # client) plus the SDK version + team manager validation.
            # ``_client`` is kept because ``shutdown()`` closes it.
            self._client = httpx.AsyncClient(base_url=self.api_url)
            logger.info(
                f"AgnoAdapter initialized successfully: "
                f"provider={self.agno_config.llm.provider.value}, "
                f"model={self.agno_config.llm.model_id}, "
                f"native_tools={len(self.get_available_tools())}"
            )

        except Exception as e:  # translate any factory error to typed AgnoError at init boundary
            logger.error(f"Failed to initialize AgnoAdapter: {e}")
            raise AgnoError(
                f"AgnoAdapter initialization failed: {e}",
                error_code=ErrorCode.CONFIGURATION_ERROR,
                details={"error": str(e)},
            ) from e

    async def _initialize_team_manager(self) -> None:
        """Initialize the agent team manager for multi-agent orchestration."""
        from .agno_teams.manager import AgentTeamManager

        # Get all tools (MCP + native)
        all_tools = self._get_all_tools()

        self._team_manager = AgentTeamManager(
            llm_factory=self._llm_factory,
            mcp_tools=all_tools,
            max_concurrent_agents=self.agno_config.max_concurrent_agents,
        )

        logger.debug("AgentTeamManager initialized")

    def _validate_agno_sdk(self) -> None:
        """Validate Agno SDK is available with correct version.

        Raises:
            AgnoError: If Agno SDK is not available or version mismatch
        """
        try:
            import agno

            version = getattr(agno, "__version__", "unknown")
            logger.debug(f"Agno SDK version: {version}")

            # Version check could be added here if needed
            # For now, we just verify imports work

        except ImportError as e:
            raise AgnoError(
                "Agno SDK not installed. Install with: pip install agno>=3.1.2",
                error_code=ErrorCode.CONFIGURATION_ERROR,
                details={"import_error": str(e)},
            ) from e

    def _get_all_tools(self) -> list[Any]:
        """Get all available tools (MCP + native).

        Returns:
            Combined list of MCP and native tools
        """
        tools = []

        # Add MCP tools
        if self._mcp_registry:
            tools.extend(self._mcp_registry.get_tools())

        # Add native tools (Phase 3)
        if self._native_tools_registry:
            tools.extend(self._native_tools_registry.get_tools())

        return tools

    def get_available_tools(self) -> list[str]:
        """Get list of available native tool names.

        Returns:
            List of tool names that can be used by agents
        """
        if self._native_tools_registry:
            return self._native_tools_registry.get_available_tools()
        return []

    # ========================================================================
    # Team Management Methods (Phase 2)
    # ========================================================================

    async def create_team(self, config: TeamConfig) -> str:
        """Create an agent team from configuration.

        Args:
            config: TeamConfig instance defining the team structure.

        Returns:
            Unique team ID string.

        Raises:
            AgnoError: If team creation fails or adapter not initialized.
        """
        if not self._initialized:
            await self.initialize()

        if not self._team_manager:
            raise AgnoError(
                "Team manager not initialized",
                error_code=ErrorCode.CONFIGURATION_ERROR,
            )

        team_id = await self._team_manager.create_team(config)
        self._execution_log.append(
            {
                "kind": "team_created",
                "team_id": team_id,
                "team_name": getattr(config, "name", team_id),
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        return team_id

    async def create_team_from_yaml(self, yaml_path: str) -> str:
        """Create a team from a YAML configuration file.

        Args:
            yaml_path: Path to the YAML configuration file.

        Returns:
            Unique team ID string.

        Raises:
            AgnoError: If file loading or team creation fails.
        """
        if not self._initialized:
            await self.initialize()

        if not self._team_manager:
            raise AgnoError(
                "Team manager not initialized",
                error_code=ErrorCode.CONFIGURATION_ERROR,
            )

        return await self._team_manager.create_team_from_yaml(yaml_path)

    async def run_team(
        self,
        team_id: str,
        task: str,
        mode: str | None = None,
        session_id: str | None = None,
    ) -> TeamRunResult:
        """Run a team task and return aggregated results.

        Args:
            team_id: Team ID returned from create_team().
            task: Task/prompt for the team to process.
            mode: Optional mode override (coordinate, route, broadcast).
            session_id: Optional session ID for memory continuity.

        Returns:
            TeamRunResult with responses from all participating agents.

        Raises:
            AgnoError: If team execution fails or team not found.
        """
        if not self._initialized:
            await self.initialize()

        if not self._team_manager:
            raise AgnoError(
                "Team manager not initialized",
                error_code=ErrorCode.CONFIGURATION_ERROR,
            )

        result = await self._team_manager.run_team(team_id, task, mode, session_id)
        self._execution_log.append(
            {
                "kind": "team_run",
                "team_id": team_id,
                "task": task,
                "mode": mode or "coordinate",
                "session_id": session_id,
                "response_count": len(getattr(result, "responses", []) or []),
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        return result

    async def get_team(self, team_id: str) -> Team | None:
        """Get a team instance by ID.

        Args:
            team_id: Team ID to look up.

        Returns:
            Team instance if found, None otherwise.
        """
        if not self._team_manager:
            return None
        return await self._team_manager.get_team(team_id)

    def list_teams(self) -> list[str]:
        """List all team IDs.

        Returns:
            List of team ID strings.
        """
        if not self._team_manager:
            return []
        return self._team_manager.list_teams()

    def get_execution_log(self, limit: int = 25) -> list[dict[str, Any]]:
        """Return recent execution summaries for cockpit views."""
        if limit <= 0:
            return []
        return list(self._execution_log)[-limit:]

    async def delete_team(self, team_id: str) -> bool:
        """Delete a team and cleanup resources.

        Args:
            team_id: Team ID to delete.

        Returns:
            True if team was deleted, False if not found.
        """
        if not self._team_manager:
            return False
        return await self._team_manager.delete_team(team_id)

    # ========================================================================
    # Single Agent Methods (Phase 1)
    # ========================================================================

    async def _create_agent(
        self,
        name: str,
        role: str | None = None,
        instructions: str | None = None,
        tools: list[Any] | None = None,
        model: Any | None = None,
    ) -> Agent:
        """Create an Agno agent instance.

        Args:
            name: Agent name
            role: Agent role description
            instructions: Agent instructions
            tools: Optional list of tools (defaults to all available tools)
            model: Optional LLM model (uses default if not provided)

        Returns:
            Configured Agent instance

        Raises:
            AgnoError: If agent creation fails
        """
        from agno.agent import Agent

        if role is None or instructions is None:
            task_type = name
            name = f"{task_type}_agent"
            role = f"Agent for {task_type} operations"
            instructions = self._get_task_instructions(task_type)

        if model is None:
            model = self._get_llm()

        if tools is None:
            # Use all available tools (MCP + native) (Phase 3)
            tools = self._get_all_tools()

        try:
            agent = Agent(
                name=name,
                role=role,
                instructions=instructions,
                model=model,
                tools=tools,
            )

            # Cache the agent
            self._agents[name] = agent

            logger.debug(f"Created agent: name={name}, role={role}, tools={len(tools)}")
            return agent

        except Exception as e:  # translate any factory/IO error to typed AgnoError
            raise AgnoError(
                f"Failed to create agent '{name}': {e}",
                error_code=ErrorCode.AGNO_AGENT_NOT_FOUND,
                details={"agent_name": name, "error": str(e)},
            ) from e

    def _create_mock_agent(self, task_type: str) -> Any:
        """Create a lightweight fallback agent for mocked or offline runs."""

        async def arun(message: str) -> Any:
            return SimpleNamespace(
                content=f"Mock response for {task_type}",
                run_id=f"mock-{task_type}",
                messages=[],
            )

        return SimpleNamespace(name=f"{task_type}_mock_agent", arun=arun)

    def _has_agno_block(self) -> bool:
        """Whether the caller's config carries a real ``agno`` block.

        A ``MahavishnuSettings`` object always exposes ``.agno`` as an
        ``AgnoAdapterConfig``, which makes that block authoritative. A
        ``MagicMock`` or a plain namespace does not, so the legacy flat
        shapes stay in play for those callers.
        """
        if isinstance(self.config, AgnoAdapterConfig):
            return True
        return isinstance(getattr(self.config, "agno", None), AgnoAdapterConfig)

    def _resolve_legacy_llm_config(self) -> AgnoLLMConfig:
        """Resolve the Agno LLM configuration.

        Precedence, highest first:

        1. An explicit legacy ``llm_provider`` on the config marks the
           caller as a pre-``agno``-block caller, so the legacy flat
           shapes (``llm.model``, ``llm.base_url``) are honoured with it.
        2. Otherwise a real ``agno.llm`` block is authoritative and is
           used verbatim.
        3. Otherwise the legacy flat shapes are consulted on their own,
           falling back to the ``agno.llm`` defaults.

        Rule 2 is what keeps the *top-level* ``llm:`` block — the
        llama-server endpoint that exists for LlamaIndex — from hijacking
        the Agno provider. Before it, every Agno call went to
        ``localhost:8081`` even with ``agno.llm.provider: minimax``
        configured: 146 s per call, against 1.8 s via MiniMax.
        """
        legacy_provider = getattr(self.config, "llm_provider", None)
        # A MagicMock auto-creates any attribute, so only a real string
        # counts as an explicit legacy directive.
        explicit_legacy_provider = legacy_provider if isinstance(legacy_provider, str) else None

        if explicit_legacy_provider is None and self._has_agno_block():
            return self.agno_config.llm

        llm_config = getattr(self.config, "llm", None)

        def _clean_str(value: Any) -> str | None:
            return value if isinstance(value, str) and value else None

        def _clean_number(value: Any) -> int | float | None:
            return value if isinstance(value, (int, float)) else None

        provider_value = getattr(self.config, "llm_provider", None)
        if provider_value is None and llm_config is not None:
            provider_value = getattr(llm_config, "provider", None)

        model_id = None
        if llm_config is not None:
            model_id = _clean_str(getattr(llm_config, "model_id", None)) or _clean_str(
                getattr(llm_config, "model", None)
            )

        base_url = None
        if llm_config is not None:
            base_url = _clean_str(getattr(llm_config, "base_url", None))

        api_key_env = (
            _clean_str(getattr(llm_config, "api_key_env", None)) if llm_config is not None else None
        )
        temperature = (
            _clean_number(getattr(llm_config, "temperature", None))
            if llm_config is not None
            else None
        )
        max_tokens = (
            _clean_number(getattr(llm_config, "max_tokens", None))
            if llm_config is not None
            else None
        )

        if temperature is None:
            temperature = self.agno_config.llm.temperature
        if max_tokens is None:
            max_tokens = self.agno_config.llm.max_tokens

        try:
            provider = (
                provider_value
                if isinstance(provider_value, LLMProvider)
                else LLMProvider(provider_value)
                if isinstance(provider_value, str)
                else self.agno_config.llm.provider
            )
        except ValueError as exc:
            raise ConfigurationError(
                f"Unsupported LLM provider: {provider_value}",
                details={"provider": provider_value},
            ) from exc

        # The model id, credential, and endpoint are all provider-scoped.
        # Only inherit them from the parent config when the legacy shape
        # resolves to the *same* provider — otherwise the MiniMax model id
        # would be sent to llama-server (or the MiniMax endpoint to the
        # Anthropic SDK), and the derived credential would name the wrong
        # env var.
        parent_llm = self.agno_config.llm
        same_provider = provider == parent_llm.provider

        return AgnoLLMConfig(
            provider=provider,
            model_id=model_id
            or (parent_llm.model_id if same_provider else default_model_for(provider)),
            api_key_env=api_key_env or (parent_llm.api_key_env if same_provider else None),
            base_url=base_url or (parent_llm.base_url if same_provider else None),
            fallback_providers=list(parent_llm.fallback_providers),
            temperature=temperature,
            max_tokens=int(max_tokens),
        )

    def _get_llm(self) -> Any:
        """Compatibility helper that returns the configured LLM model."""
        if self._llm_factory is None:
            # Phase 7 removed the ``bifrost`` kwarg — the factory now
            # consults ``get_router()._settings`` directly. Legacy
            # callers that pre-date the oneiric router still get
            # direct routing when the router is disabled.
            self._llm_factory = LLMProviderFactory(
                self._resolve_legacy_llm_config(),
            )

        try:
            return self._llm_factory.create_model_chain()
        except AgnoError as exc:
            message = str(exc)
            if "Unsupported LLM provider" in message:
                raise ConfigurationError(message, details=getattr(exc, "details", None)) from exc
            if "Failed to import LLM provider" in message:
                raise ImportError(message) from exc
            raise

    async def _run_agent(
        self,
        agent: Agent,
        message: str,
        context: dict[str, Any] | None = None,
        session_id: str | None = None,
    ) -> AgentRunResult:
        """Run an agent with a message and return structured result.

        Args:
            agent: Agent instance to run
            message: Message/prompt for the agent
            context: Optional context dictionary
            session_id: Optional session ID for memory

        Returns:
            AgentRunResult with response content and metadata

        Raises:
            AgnoError: If agent execution fails
        """
        import time

        start_time = time.monotonic()
        # Resolve the dispatch metadata once; the heartbeat fires
        # with the same provider / model / route_class on every
        # exit path (success, timeout, generic failure).
        hb_provider, hb_model, hb_route_class, hb_is_local = _resolve_dispatch_heartbeat_args(
            self.agno_config.llm
        )

        try:
            # Run agent with timeout
            async with asyncio.timeout(self.agno_config.default_timeout_seconds):
                response: RunOutput = await agent.arun(message)

            latency_ms = (time.monotonic() - start_time) * 1000

            # Extract content from response
            content = self._extract_content(response)

            # Heartbeat: log + counters for the successful dispatch.
            _bifrost_dispatch_heartbeat(
                provider=hb_provider,
                model=hb_model,
                route_class=hb_route_class,
                outcome="success",
                latency_seconds=latency_ms / 1000.0,
                is_local=hb_is_local,
            )

            return AgentRunResult(
                agent_name=agent.name or "unknown_agent",
                content=content,
                run_id=getattr(response, "run_id", "unknown"),
                success=True,
                latency_ms=latency_ms,
                metadata={"session_id": session_id, "context": context},
            )

        except TimeoutError:
            latency_ms = (time.monotonic() - start_time) * 1000
            _bifrost_dispatch_heartbeat(
                provider=hb_provider,
                model=hb_model,
                route_class=hb_route_class,
                outcome="failure",
                latency_seconds=latency_ms / 1000.0,
                failure_reason="timeout",
                is_local=hb_is_local,
            )
            raise MahavishnuTimeoutError(
                operation=f"agent_run:{agent.name}",
                timeout_seconds=self.agno_config.default_timeout_seconds,
                details={"agent_name": agent.name, "latency_ms": latency_ms},
            ) from None
        except Exception as e:  # translate any agent runtime error to typed AgnoError
            latency_ms = (time.monotonic() - start_time) * 1000
            _bifrost_dispatch_heartbeat(
                provider=hb_provider,
                model=hb_model,
                route_class=hb_route_class,
                outcome="failure",
                latency_seconds=latency_ms / 1000.0,
                failure_reason=type(e).__name__,
                is_local=hb_is_local,
            )
            raise AgnoError(
                f"Agent '{agent.name}' execution failed: {e}",
                error_code=ErrorCode.AGNO_TOOL_EXECUTION_ERROR,
                details={
                    "agent_name": agent.name,
                    "error": str(e),
                    "latency_ms": latency_ms,
                },
            ) from e

    def _extract_content(self, response: RunOutput) -> str:
        """Extract content from Agno RunOutput.

        Args:
            response: RunOutput from agent execution

        Returns:
            String content from response
        """
        # Try different content extraction methods
        if hasattr(response, "content") and response.content:
            if isinstance(response.content, str):
                return response.content
            return str(response.content)

        if hasattr(response, "messages") and response.messages:
            # Extract from last message
            last_message = response.messages[-1]
            if hasattr(last_message, "content"):
                return str(last_message.content)

        # Fallback to string representation
        return str(response)

    @asynccontextmanager
    async def _require_semaphore(self) -> AsyncGenerator[asyncio.Semaphore]:
        """Yield the concurrency semaphore or raise if not initialized."""
        sem = self._semaphore
        if sem is None:
            raise AgnoError(
                "AgnoAdapter semaphore not initialized",
                error_code=ErrorCode.CONFIGURATION_ERROR,
            )
        yield sem

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
    )
    async def _process_single_repo(
        self,
        repo: str,
        task: dict[str, Any],
    ) -> dict[str, Any]:
        """Process a single repository with Agno agent.

        Args:
            repo: Repository path
            task: Task specification

        Returns:
            Processing result dictionary
        """
        async with self._require_semaphore():
            task_type = task.get("type", "default")

            try:
                # Create agent for task type
                agent = await self._create_agent(task_type)
                if agent is None:
                    agent = self._create_mock_agent(task_type)

                # Build prompt based on task type
                prompt = self._build_task_prompt(task_type, repo, task)

                # Run agent
                result = await self._run_agent(
                    agent=agent,
                    message=prompt,
                    context={"repo_path": repo, "task": task},
                )

                return {
                    "repo": repo,
                    "status": "completed",
                    "result": {
                        "operation": task_type,
                        "content": result.content,
                        "run_id": result.run_id,
                        "latency_ms": result.latency_ms,
                    },
                    "task_id": task.get("id", "unknown"),
                }

            except MahavishnuTimeoutError as e:
                return {
                    "repo": repo,
                    "status": "timeout",
                    "error": str(e),
                    "task_id": task.get("id", "unknown"),
                }
            except AgnoError as e:
                return {
                    "repo": repo,
                    "status": "failed",
                    "error": e.message,
                    "error_code": e.error_code.value,
                    "task_id": task.get("id", "unknown"),
                }
            except Exception as e:  # per-repo failure is recorded, not raised; aggregate continues
                logger.exception(f"Unexpected error processing repo {repo}")
                return {
                    "repo": repo,
                    "status": "failed",
                    "error": str(e),
                    "task_id": task.get("id", "unknown"),
                }

    def _get_task_instructions(self, task_type: str) -> str:
        """Get agent instructions for task type.

        Args:
            task_type: Type of task

        Returns:
            Instruction string for agent
        """
        instructions = {
            "code_sweep": """You are a code analysis agent. Analyze the repository
for code quality, potential improvements, and best practices. Focus on:
- Code structure and organization
- Potential bugs or issues
- Performance considerations
- Documentation completeness

Use available tools like read_file, analyze_code, and search_code to explore the codebase.""",
            "quality_check": """You are a quality assurance agent. Evaluate the
repository against quality standards. Check for:
- Code style compliance
- Test coverage indicators
- Security best practices
- Maintainability concerns

Use available tools to examine code files and provide a detailed assessment.""",
            "focused_review": """You are a code analysis agent working on a
strictly bounded task. The task names one exact file to read.

Rules:
- Read ONLY the file named in the task.
- Do NOT list directories, do NOT search the repository, and do NOT
  follow imports into other files.
- Answer in at most 5 bullet points, then stop.

Your job is to finish, not to explore. Once you have read the named
file, answer immediately.""",
            "default": """You are a helpful AI assistant. Process the given task
using available tools and provide clear, actionable responses.

Available tools include:
- read_file: Read file contents
- write_file: Write content to files
- list_directory: List directory contents
- search_files: Search for files by pattern
- analyze_code: Analyze Python code for complexity and issues
- search_code: Search for code patterns in repositories
- get_function_signature: Get function signatures from code""",
        }
        return instructions.get(task_type, instructions["default"])

    async def _post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        """POST JSON payload to the compatibility API endpoint."""
        url = f"{self.api_url.rstrip('/')}/{path.lstrip('/')}"
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload)
            if response.status_code >= 400:
                raise AgnoError(
                    f"Agno API request failed: {response.status_code}",
                    error_code=ErrorCode.AGNO_TOOL_EXECUTION_ERROR,
                    details={"url": url, "status_code": response.status_code},
                )

            json_attr = getattr(response, "json", None)
            data = json_attr() if callable(json_attr) else json_attr
            if isinstance(data, dict):
                return data
            return {}

    async def create_crew(self, crew_name: str, crew_config: dict[str, Any]) -> str:
        """Create a crew via the compatibility API."""
        if not self._initialized:
            await self.initialize()

        payload = {"crew_name": crew_name, "crew_config": crew_config}
        data = await self._post_json("/crews", payload)
        crew_id = data.get("crew_id") or data.get("id") or crew_name
        return str(crew_id)

    async def execute_task(self, crew_id: str, task: dict[str, Any]) -> str:
        """Execute a single crew task via the compatibility API."""
        if not self._initialized:
            await self.initialize()

        payload = {"crew_id": crew_id, "task": task}
        data = await self._post_json("/tasks", payload)
        execution_id = data.get("execution_id") or data.get("id") or crew_id
        return str(execution_id)

    async def execute_task_batch(self, crew_id: str, tasks: list[dict[str, Any]]) -> list[str]:
        """Execute a batch of tasks via the compatibility API."""
        results: list[str] = []
        for task in tasks:
            results.append(await self.execute_task(crew_id=crew_id, task=task))
        return results

    def _build_task_prompt(
        self,
        task_type: str,
        repo: str,
        task: dict[str, Any],
    ) -> str:
        """Build prompt for agent based on task.

        Args:
            task_type: Type of task
            repo: Repository path
            task: Task specification

        Returns:
            Prompt string for agent
        """
        params = task.get("params", {})

        if task_type == "code_sweep":
            return f"""Analyze the repository at {repo} for code quality and
improvement opportunities. Focus on: {params.get("focus", "general analysis")}.

Use available tools (read_file, list_directory, search_files, analyze_code) to explore the codebase and provide specific,
actionable recommendations."""

        if task_type == "quality_check":
            return f"""Perform a quality check on the repository at {repo}.
Evaluate against: {params.get("standards", "Python best practices")}.

Use available tools to examine the code and provide a compliance score and list any issues found."""

        if task_type == "focused_review":
            # A bounded task: one named file, one question, one answer.
            # The whole-repository task types ("code_sweep",
            # "quality_check", "default") hand the agent an open-ended
            # brief over a whole repo, and the agent explores until the
            # adapter's own budget expires -- the run reports a top-level
            # "completed" while every repo underneath timed out.
            target = str(params.get("target", "")).strip()
            question = str(
                params.get("focus")
                or "Summarise what this file does and list its public functions."
            )
            if target and not Path(target).is_absolute():
                target = str(Path(repo) / target)
            return f"""Review the file {target}.

{question}

Read ONLY that file. Do not list directories, do not search the
repository, and do not read any other file. Answer with at most 5
bullet points."""

        # Default prompt
        return f"""Process the following task for repository {repo}:

Task type: {task_type}
Parameters: {params}

Use available tools to complete the task and provide a summary."""

    async def execute(
        self,
        task: dict[str, Any],
        repos: list[str],
    ) -> dict[str, Any]:
        """Execute a task using Agno agents across repositories.

        This is the main entry point for the OrchestratorAdapter interface.
        It creates agents for each repository and executes them concurrently.

        Args:
            task: Task specification with type and parameters
            repos: List of repository paths to process

        Returns:
            Execution result with status, results per repo, and metadata

        Raises:
            AgnoError: If execution fails critically
        """
        if not self._initialized:
            await self.initialize()

        logger.info(f"Executing Agno task: type={task.get('type')}, repos={len(repos)}")

        try:
            # Process repositories concurrently with semaphore
            results = await asyncio.gather(
                *[self._process_single_repo(repo, task) for repo in repos],
                return_exceptions=True,
            )

            # Convert exceptions to error results
            processed_results: list[dict[str, Any]] = []
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    processed_results.append(
                        {
                            "repo": repos[i],
                            "status": "failed",
                            "error": str(result),
                            "task_id": task.get("id", "unknown"),
                        }
                    )
                else:
                    processed_results.append(cast("dict[str, Any]", result))

            # Calculate success/failure counts
            success_count = sum(1 for r in processed_results if r.get("status") == "completed")
            failure_count = len(processed_results) - success_count
            self._execution_log.append(
                {
                    "kind": "task_batch",
                    "task_type": task.get("type", "default"),
                    "repos": list(repos),
                    "success_count": success_count,
                    "failure_count": failure_count,
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            )

            return {
                "status": "completed",
                "engine": "agno",
                "engine_version": self.ADAPTER_VERSION,
                "task": task,
                "repos_processed": len(repos),
                "results": processed_results,
                "success_count": success_count,
                "failure_count": failure_count,
                "adapter": "AgnoAdapter",
                "timestamp": datetime.now(UTC).isoformat(),
            }

        except Exception as e:  # CLI/MCP entry point — translate any error to typed AgnoError
            logger.exception("Agno execution failed")
            raise AgnoError(
                f"Agno execution failed: {e}",
                error_code=ErrorCode.INTERNAL_ERROR,
                details={"task": task, "repos": repos, "error": str(e)},
            ) from e

    async def get_health(self) -> dict[str, Any]:
        """Get adapter health status.

        Returns:
            Dict with 'status' key ('healthy', 'degraded', 'unhealthy')
            and adapter-specific health details.
        """
        health_details = {
            "adapter": "agno",
            "version": self.ADAPTER_VERSION,
            "configured": self.agno_config is not None,
            "initialized": self._initialized,
            "llm_provider": self.agno_config.llm.provider.value if self.agno_config else None,
            "model_id": self.agno_config.llm.model_id if self.agno_config else None,
            "agents_cached": len(self._agents),
            "teams_count": len(self._teams),
            "mcp_tools_initialized": self._mcp_registry._initialized
            if self._mcp_registry
            else False,
            "team_manager_initialized": self._team_manager is not None,
            "native_tools_count": len(self.get_available_tools()),
        }

        # Determine health status
        if not self._initialized:
            return {
                "status": "unhealthy",
                "details": {**health_details, "reason": "Adapter not initialized"},
            }

        # Test LLM provider availability
        try:
            if self._llm_factory:
                # Just check if factory is configured, don't create model
                health_details["llm_configured"] = True
        except Exception as e:  # health probe — degrade, don't fail  # background task — broad catch is the documented contract  # noqa: BLE001, RUF100
            return {
                "status": "degraded",
                "details": {**health_details, "llm_error": str(e)},
            }

        return {"status": "healthy", "details": health_details}

    async def cleanup(self) -> None:
        """Cleanup adapter resources."""
        await self.shutdown()

    async def shutdown(self) -> None:
        """Gracefully shutdown adapter and cleanup resources.

        This method:
        1. Closes MCP tools connections
        2. Shuts down team manager
        3. Clears agent cache
        4. Resets initialization state
        """
        logger.info("Shutting down AgnoAdapter...")

        # Shutdown team manager
        if self._team_manager:
            await self._team_manager.shutdown()
            self._team_manager = None

        # Close MCP tools
        if self._mcp_registry:
            await self._mcp_registry.close()

        # Clear caches
        self._agents.clear()
        self._teams.clear()
        self._execution_log.clear()

        # Reset state
        self._initialized = False
        self._llm_factory = None
        self._mcp_registry = None
        self._native_tools_registry = None
        self._semaphore = None

        if self._client is not None:
            close_method = getattr(self._client, "aclose", None)
            if callable(close_method):
                try:
                    await close_method()
                except Exception as e:  # shutdown cleanup — best-effort, never fatal  # background task — broad catch is the documented contract  # background task — broad catch is the documented contract  # noqa: BLE001, RUF100
                    logger.warning(f"Error closing Agno client session: {e}")
        self._client = None

        logger.info("AgnoAdapter shutdown complete")


# ============================================================================
# Module Exports
# ============================================================================

__all__ = [
    "AgentRunResult",
    "AgnoAdapter",
    "AgnoAdapterConfig",
    "AgnoLLMConfig",
    "AgnoMemoryConfig",
    "AgnoToolsConfig",
    "LLMProvider",
    "LLMProviderFactory",
    "MCPToolsRegistry",
    "MemoryBackend",
    "NativeToolsRegistry",
    "TeamRunResult",
    # Entry point function
    "agno_adapter_entries",
]


# =============================================================================
# Entry Point for Hybrid Adapter Registry
# =============================================================================


def agno_adapter_entries() -> list[AdapterMetadata]:
    """Entry point for Agno adapter registration.

    This function is called by Oneiric's plugin discovery
    (``oneiric.adapters`` entry-point group) to register the Agno adapter.
    The returned ``AdapterMetadata`` instances are consumed by
    ``oneiric.plugins._normalize_candidates`` and turned into
    ``Candidate`` records on the resolver.
    """
    return [
        AdapterMetadata(
            category="orchestration",
            provider="agno",
            factory="mahavishnu.engines.agno_adapter_impl.AgnoAdapter",
            description="Agno multi-agent AI orchestration engine",
            capabilities=[
                "multi_agent",
                "tool_use",
                "team_coordination",
                "mcp_tools",
                "native_tools",
                "memory_management",
            ],
            priority=85,
        )
    ]
