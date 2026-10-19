"""Helpers for the local Bifrost LLM gateway contract.

Phase 2 of the bifrost plan (2026-10-17) removed the
``ProtocolFamily`` enum and the ``gateway_api_base`` helper. The
mahavishnu call sites now resolve the base URL through the oneiric
``BifrostLLMRouter`` directly. Phase 7 deletes this whole module.
"""

from .client import (
    GatewayRequestEnvelope,
    ProviderNamespace,
    build_gateway_envelope,
    default_provider_for_protocol,
    gateway_path,
    qualify_model,
    recommended_cache_mode,
)
from .contract import (
    BifrostGatewayRequest,
    CacheMode,
    RouteClass,
    hash_prompt,
    infer_route_class,
)

__all__ = [
    "BifrostGatewayRequest",
    "CacheMode",
    "GatewayRequestEnvelope",
    "ProviderNamespace",
    "RouteClass",
    "build_gateway_envelope",
    "default_provider_for_protocol",
    "gateway_path",
    "hash_prompt",
    "infer_route_class",
    "qualify_model",
    "recommended_cache_mode",
]
