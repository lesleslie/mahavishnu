"""Client-side helpers for talking to the local Bifrost gateway.

This module keeps protocol selection, provider/model qualification, and
header/caching defaults in one place so callers do not need to rebuild the
gateway contract ad hoc.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urljoin

from .contract import BifrostGatewayRequest, CacheMode, RouteClass, infer_route_class


class ProtocolFamily(StrEnum):
    """Wire protocols exposed by the local Bifrost deployment."""

    OPENAI = "openai"
    ANTHROPIC = "anthropic"


class ProviderNamespace(StrEnum):
    """Provider namespaces currently configured in Bifrost."""

    MINIMAX_OPENAI = "minimax-openai"
    ANTHROPIC = "anthropic"


def qualify_model(model: str, *, provider: str) -> str:
    """Return a Bifrost-qualified provider/model string."""

    if "/" in model:
        return model
    return f"{provider}/{model}"


def gateway_path(protocol_family: ProtocolFamily | str) -> str:
    """Return the HTTP path for the selected protocol family."""

    protocol = ProtocolFamily(protocol_family)
    if protocol is ProtocolFamily.ANTHROPIC:
        return "/anthropic/v1/messages"
    return "/v1/chat/completions"


def gateway_api_base(protocol_family: ProtocolFamily | str, *, base_url: str) -> str:
    """Return the base URL prefix expected by SDK-style clients.

    Some client libraries expect an API root rather than a full request path.
    For the local Bifrost deployment that means:

    - OpenAI clients -> ``http://127.0.0.1:8471/v1``
    - Anthropic clients -> ``http://127.0.0.1:8471/anthropic``
    """

    protocol = ProtocolFamily(protocol_family)
    normalized = base_url.rstrip("/")
    if protocol is ProtocolFamily.ANTHROPIC:
        return f"{normalized}/anthropic"
    return f"{normalized}/v1"


def default_provider_for_protocol(protocol_family: ProtocolFamily | str) -> ProviderNamespace:
    """Return the configured provider namespace for a protocol family."""

    protocol = ProtocolFamily(protocol_family)
    if protocol is ProtocolFamily.ANTHROPIC:
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

    @property
    def api_base(self) -> str:
        return gateway_api_base(self.request.protocol_family, base_url=self.base_url)


def build_gateway_envelope(
    *,
    caller_id: str,
    protocol_family: ProtocolFamily | str,
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

    protocol = ProtocolFamily(protocol_family)
    resolved_provider = provider or default_provider_for_protocol(protocol).value
    resolved_model = qualify_model(model, provider=resolved_provider)
    resolved_cache_mode = cache_mode or recommended_cache_mode(
        task_label=task_label,
        request_type=request_type,
        model=resolved_model,
        semantic_cache_available=semantic_cache_available,
    )
    request = BifrostGatewayRequest(
        caller_id=caller_id,
        protocol_family=protocol.value,
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
        path=gateway_path(protocol),
        request=request,
    )
