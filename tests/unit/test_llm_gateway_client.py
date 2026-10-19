"""Tests for client-side Bifrost gateway helpers.

Phase 2 of the bifrost plan (2026-10-17) removed
``ProtocolFamily`` and ``gateway_api_base`` — the mahavishnu
call sites now resolve the base URL through the oneiric
``BifrostLLMRouter`` directly. The remaining functions in
``mahavishnu.llm_gateway.client`` take ``protocol_family: str``
instead of the deleted enum. These tests cover the surviving
surface; the deleted helpers' tests are gone.
"""

from __future__ import annotations

from mahavishnu.llm_gateway import CacheMode, RouteClass
from mahavishnu.llm_gateway.client import (
    build_gateway_envelope,
    default_provider_for_protocol,
    gateway_path,
    qualify_model,
    recommended_cache_mode,
)


def test_gateway_path_matches_protocol() -> None:
    # Protocol values are plain strings (the deleted ProtocolFamily
    # enum's values are preserved for wire compatibility).
    assert gateway_path("openai") == "/v1/chat/completions"
    assert gateway_path("anthropic") == "/anthropic/v1/messages"


def test_qualify_model_is_idempotent() -> None:
    assert qualify_model("MiniMax-M2.7", provider="minimax-openai") == (
        "minimax-openai/MiniMax-M2.7"
    )
    assert qualify_model("anthropic/GLM-4.7", provider="anthropic") == "anthropic/GLM-4.7"


def test_default_provider_follows_protocol_family() -> None:
    assert default_provider_for_protocol("openai").value == "minimax-openai"
    assert default_provider_for_protocol("anthropic").value == "anthropic"


def test_recommended_cache_mode_prefers_direct_without_semantic_provider() -> None:
    assert recommended_cache_mode(task_label="think") is CacheMode.DIRECT
    assert recommended_cache_mode(task_label="background") is CacheMode.DIRECT
    assert recommended_cache_mode(task_label="image") is CacheMode.OFF


def test_recommended_cache_mode_can_select_semantic_when_available() -> None:
    assert (
        recommended_cache_mode(task_label="web_search", semantic_cache_available=True)
        is CacheMode.SEMANTIC
    )


def test_build_gateway_envelope_resolves_url_model_headers_and_cache() -> None:
    envelope = build_gateway_envelope(
        caller_id="claude-code",
        protocol_family="anthropic",
        model="GLM-4.5-Air",
        prompt="summarize this diff",
        task_label="think",
    )

    assert envelope.url == "http://127.0.0.1:8471/anthropic/v1/messages"
    assert envelope.request.model == "anthropic/GLM-4.5-Air"
    assert envelope.request.route_class is RouteClass.THINK
    assert envelope.request.request_headers["x-bf-task"] == "think"
    assert envelope.request.request_headers["x-bf-cache-type"] == "direct"
    assert envelope.request.request_headers["x-bf-cache-ttl"] == "300"


def test_build_gateway_envelope_allows_openai_override_and_no_cache() -> None:
    envelope = build_gateway_envelope(
        caller_id="direct-openai-client",
        protocol_family="openai",
        model="glm-5-turbo",
        prompt="describe this image",
        task_label="image",
        trusted_wrapper=True,
    )

    assert envelope.url == "http://127.0.0.1:8471/v1/chat/completions"
    assert envelope.request.model == "minimax-openai/glm-5-turbo"
    assert envelope.request.route_class is RouteClass.IMAGE
    assert envelope.request.cache_headers == {}
