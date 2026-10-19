"""Client-side helpers for talking to the local Bifrost gateway.

This module keeps protocol selection, provider/model qualification, and
header/caching defaults in one place so callers do not need to rebuild the
gateway contract ad hoc.

Phase 2 of the bifrost plan (2026-10-17) removed the
``ProtocolFamily`` enum and the ``gateway_api_base`` helper — the
mahavishnu call sites now resolve the base URL through the oneiric
``BifrostLLMRouter`` directly (per REQ-BIFROST-002). The remaining
functions take ``protocol_family: str`` instead of the deleted enum.
Phase 7 deletes this whole module.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urljoin

from .contract import BifrostGatewayRequest, CacheMode, RouteClass, infer_route_class


class ProviderNamespace(StrEnum):
    """Provider namespaces currently configured in Bifrost."""

    MINIMAX_OPENAI = "minimax-openai"
    ANTHROPIC = "anthropic"


# Phase 2 note: the value strings match the prior
# ``ProtocolFamily.OPENAI`` / ``ProtocolFamily.ANTHROPIC`` values
# so the existing ``BifrostGatewayRequest.protocol_family`` field
# keeps its wire format.
_PROTOCOL_OPENAI = "openai"
_PROTOCOL_ANTHROPIC = "anthropic"


def qualify_model(model: str, *, provider: str) -> str:
    """Return a Bifrost-qualified provider/model string."""

    if "/" in model:
        return model
    return f"{provider}/{model}"


def gateway_path(protocol_family: str) -> str:
    """Return the HTTP path for the selected protocol family."""

    if protocol_family == _PROTOCOL_ANTHROPIC:
        return "/anthropic/v1/messages"
    return "/v1/chat/completions"


def default_provider_for_protocol(protocol_family: str) -> ProviderNamespace:
    """Return the configured provider namespace for a protocol family."""

    if protocol_family == _PROTOCOL_ANTHROPIC:
        return ProviderNamespace.ANTHROPIC
    return ProviderNamespace.MINIMAX_OPENAI


def recommended_cache_mode(
    *,
    task_label: str | None = None,
    request_type: str | None = None,
    model: str | None = None,
    semantic_cache_available: bool = False,
) -> CacheMode:
    """Return a conservative cache recommendation for a request shape.

    The current deployment defaults to direct cache because Bifrost is running
    in direct-only mode until an embedding strategy is configured.
    """

    route_class = infer_route_class(
        task_label=task_label,
        request_type=request_type,
        model=model,
    )
    if route_class is RouteClass.IMAGE:
        return CacheMode.OFF
    if route_class in {RouteClass.WEB_SEARCH, RouteClass.THINK, RouteClass.LONG_CONTEXT}:
        return CacheMode.SEMANTIC if semantic_cache_available else CacheMode.DIRECT
    return CacheMode.DIRECT


@dataclass(frozen=True, slots=True)
class GatewayRequestEnvelope:
    """Fully resolved outbound request metadata for a Bifrost call."""

    base_url: str
    path: str
    request: BifrostGatewayRequest

    @property
    def url(self) -> str:
        return urljoin(self.base_url.rstrip("/") + "/", self.path.lstrip("/"))


def build_gateway_envelope(
    *,
    caller_id: str,
    protocol_family: str,
    model: str,
    prompt: str,
    task_label: str | None = None,
    request_type: str | None = None,
    base_url: str = "http://127.0.0.1:8471",
    provider: str | None = None,
    trusted_wrapper: bool = True,
    cache_mode: CacheMode | None = None,
    cache_ttl_seconds: int | None = 300,
    cache_threshold: float | None = None,
    semantic_cache_available: bool = False,
) -> GatewayRequestEnvelope:
    """Build a resolved Bifrost request envelope for a client call."""

    resolved_provider = provider or default_provider_for_protocol(protocol_family).value
    resolved_model = qualify_model(model, provider=resolved_provider)
    resolved_cache_mode = cache_mode or recommended_cache_mode(
        task_label=task_label,
        request_type=request_type,
        model=resolved_model,
        semantic_cache_available=semantic_cache_available,
    )
    request = BifrostGatewayRequest(
        caller_id=caller_id,
        protocol_family=protocol_family,
        provider=resolved_provider,
        model=resolved_model,
        prompt=prompt,
        task_label=task_label,
        request_type=request_type,
        trusted_wrapper=trusted_wrapper,
        cache_mode=resolved_cache_mode,
        cache_ttl_seconds=cache_ttl_seconds if resolved_cache_mode is not CacheMode.OFF else None,
        cache_threshold=cache_threshold,
    )
    return GatewayRequestEnvelope(
        base_url=base_url,
        path=gateway_path(protocol_family),
        request=request,
    )
