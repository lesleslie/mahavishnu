"""Bifrost request contract helpers.

This module captures the minimum CCR-like behavior we want to preserve while
removing CCR from the required path:

- task / route labels
- trusted-header handling
- cache key scoping
- prompt hashing for stable cache keys
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from hashlib import sha256
from typing import Final


class RouteClass(StrEnum):
    """CCR-compatible route buckets mapped to Bifrost route labels."""

    DEFAULT = "default"
    THINK = "think"
    BACKGROUND = "background"
    LONG_CONTEXT = "long_context"
    WEB_SEARCH = "web_search"
    IMAGE = "image"
    HIGH_THROUGHPUT = "high_throughput"
    CHEAP = "cheap"


class CacheMode(StrEnum):
    """Cache policy hints understood by the local wrapper."""

    DIRECT = "direct"
    SEMANTIC = "semantic"
    OFF = "off"


_TASK_LABEL_MAP: Final[dict[str, RouteClass]] = {
    "default": RouteClass.DEFAULT,
    "think": RouteClass.THINK,
    "background": RouteClass.BACKGROUND,
    "longcontext": RouteClass.LONG_CONTEXT,
    "long_context": RouteClass.LONG_CONTEXT,
    "websearch": RouteClass.WEB_SEARCH,
    "web_search": RouteClass.WEB_SEARCH,
    "image": RouteClass.IMAGE,
    "vision": RouteClass.IMAGE,
    "multimodal": RouteClass.IMAGE,
    "highthroughput": RouteClass.HIGH_THROUGHPUT,
    "high_throughput": RouteClass.HIGH_THROUGHPUT,
    "cheap": RouteClass.CHEAP,
}

_REQUEST_TYPE_MAP: Final[dict[str, RouteClass]] = {
    "text": RouteClass.DEFAULT,
    "chat": RouteClass.DEFAULT,
    "reasoning": RouteClass.THINK,
    "analysis": RouteClass.THINK,
    "background": RouteClass.BACKGROUND,
    "web_search": RouteClass.WEB_SEARCH,
    "search": RouteClass.WEB_SEARCH,
    "image": RouteClass.IMAGE,
    "vision": RouteClass.IMAGE,
    "multimodal": RouteClass.IMAGE,
}


def _normalize_token(value: str) -> str:
    return value.strip().lower().replace("-", "_").replace(" ", "_")


def hash_prompt(prompt: str) -> str:
    """Return a stable prompt hash for cache key construction."""

    normalized = prompt.replace("\r\n", "\n").strip()
    return sha256(normalized.encode("utf-8")).hexdigest()


def infer_route_class(
    *,
    task_label: str | None = None,
    request_type: str | None = None,
    model: str | None = None,
) -> RouteClass:
    """Infer the most specific route class from the available metadata."""

    if task_label:
        normalized = _normalize_token(task_label)
        route = _TASK_LABEL_MAP.get(normalized)
        if route is not None:
            return route

    if request_type:
        normalized = _normalize_token(request_type)
        route = _REQUEST_TYPE_MAP.get(normalized)
        if route is not None:
            return route

    if model:
        normalized = _normalize_token(model)
        if any(token in normalized for token in ("vision", "image", "multimodal", "visionary")):
            return RouteClass.IMAGE
        if any(token in normalized for token in ("long", "context")):
            return RouteClass.LONG_CONTEXT
        if any(token in normalized for token in ("cheap", "mini", "fast", "turbo")):
            return RouteClass.CHEAP

    return RouteClass.DEFAULT


def _format_scope_part(value: str | None) -> str:
    return _normalize_token(value) if value else "*"


@dataclass(frozen=True, slots=True)
class BifrostGatewayRequest:
    """Immutable request plan for a Bifrost-backed client call."""

    caller_id: str
    protocol_family: str
    provider: str
    model: str
    prompt: str
    task_label: str | None = None
    request_type: str | None = None
    trusted_wrapper: bool = False
    cache_mode: CacheMode = CacheMode.OFF
    cache_ttl_seconds: int | None = None
    cache_threshold: float | None = None
    cache_key_prefix: str | None = None
    route_class: RouteClass = field(init=False)
    prompt_hash: str = field(init=False)

    def __post_init__(self) -> None:
        route_class = infer_route_class(
            task_label=self.task_label,
            request_type=self.request_type,
            model=self.model,
        )
        object.__setattr__(self, "route_class", route_class)
        object.__setattr__(self, "prompt_hash", hash_prompt(self.prompt))

    @property
    def cache_scope_key(self) -> str:
        """Return the cache scope used to prevent cross-client contamination."""

        parts = [
            _format_scope_part(self.cache_key_prefix),
            _format_scope_part(self.caller_id),
            _format_scope_part(self.protocol_family),
            _format_scope_part(self.provider),
            _format_scope_part(self.model),
            self.route_class.value,
            self.prompt_hash,
        ]
        return ":".join(parts)

    @property
    def route_headers(self) -> dict[str, str]:
        """Return Bifrost route headers when the caller is trusted."""

        if not self.trusted_wrapper:
            return {}

        headers = {
            "x-bf-task": self.route_class.value,
            "x-bf-route": self.route_class.value,
        }
        if self.request_type:
            headers["x-bf-request-type"] = _normalize_token(self.request_type)
        return headers

    @property
    def cache_headers(self) -> dict[str, str]:
        """Return Bifrost cache headers when the caller is trusted."""

        if not self.trusted_wrapper or self.cache_mode is CacheMode.OFF:
            return {}

        headers: dict[str, str] = {
            "x-bf-cache-key": self.cache_scope_key,
            "x-bf-cache-type": self.cache_mode.value,
        }
        if self.cache_ttl_seconds is not None:
            headers["x-bf-cache-ttl"] = str(self.cache_ttl_seconds)
        if self.cache_threshold is not None:
            headers["x-bf-cache-threshold"] = f"{self.cache_threshold:g}"
        return headers

    @property
    def request_headers(self) -> dict[str, str]:
        """Return the full header set the wrapper should send to Bifrost."""

        headers = {}
        headers.update(self.route_headers)
        headers.update(self.cache_headers)
        return headers

    def without_prompt(self) -> dict[str, str]:
        """Serialize the gateway request without embedding the prompt text."""

        return {
            "caller_id": self.caller_id,
            "protocol_family": self.protocol_family,
            "provider": self.provider,
            "model": self.model,
            "task_label": self.task_label or "",
            "request_type": self.request_type or "",
            "trusted_wrapper": str(self.trusted_wrapper).lower(),
            "route_class": self.route_class.value,
            "prompt_hash": self.prompt_hash,
            "cache_mode": self.cache_mode.value,
            "cache_scope_key": self.cache_scope_key,
        }
