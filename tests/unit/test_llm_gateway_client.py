"""Tests for client-side Bifrost gateway helpers."""

from __future__ import annotations

from mahavishnu.llm_gateway import CacheMode, RouteClass
from mahavishnu.llm_gateway.client import (
    ProtocolFamily,
    build_gateway_envelope,
    default_provider_for_protocol,
    gateway_api_base,
    gateway_path,
    qualify_model,
    recommended_cache_mode,
)


def test_gateway_path_matches_protocol() -> None:
    assert gateway_path(ProtocolFamily.OPENAI) == "/v1/chat/completions"
    assert gateway_path(ProtocolFamily.ANTHROPIC) == "/anthropic/v1/messages"


def test_gateway_api_base_matches_protocol() -> None:
    assert gateway_api_base(ProtocolFamily.OPENAI, base_url="http://127.0.0.1:8471") == (
        "http://127.0.0.1:8471/v1"
    )
    assert gateway_api_base(
        ProtocolFamily.ANTHROPIC,
        base_url="http://127.0.0.1:8471/",
    ) == "http://127.0.0.1:8471/anthropic"


def test_qualify_model_is_idempotent() -> None:
    assert qualify_model("glm-5-turbo", provider="zai-openai") == "zai-openai/glm-5-turbo"
    assert qualify_model("anthropic/GLM-4.7", provider="anthropic") == "anthropic/GLM-4.7"


def test_default_provider_follows_protocol_family() -> None:
    assert default_provider_for_protocol(ProtocolFamily.OPENAI).value == "zai-openai"
    assert default_provider_for_protocol(ProtocolFamily.ANTHROPIC).value == "anthropic"


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
        protocol_family=ProtocolFamily.ANTHROPIC,
        model="GLM-4.5-Air",
        prompt="summarize this diff",
        task_label="think",
    )

    assert envelope.url == "http://127.0.0.1:8471/anthropic/v1/messages"
    assert envelope.api_base == "http://127.0.0.1:8471/anthropic"
    assert envelope.request.model == "anthropic/GLM-4.5-Air"
    assert envelope.request.route_class is RouteClass.THINK
    assert envelope.request.request_headers["x-bf-task"] == "think"
    assert envelope.request.request_headers["x-bf-cache-type"] == "direct"
    assert envelope.request.request_headers["x-bf-cache-ttl"] == "300"


def test_build_gateway_envelope_allows_openai_override_and_no_cache() -> None:
    envelope = build_gateway_envelope(
        caller_id="direct-openai-client",
        protocol_family=ProtocolFamily.OPENAI,
        model="glm-5-turbo",
        prompt="describe this image",
        task_label="image",
        trusted_wrapper=True,
    )

    assert envelope.url == "http://127.0.0.1:8471/v1/chat/completions"
    assert envelope.api_base == "http://127.0.0.1:8471/v1"
    assert envelope.request.model == "zai-openai/glm-5-turbo"
    assert envelope.request.route_class is RouteClass.IMAGE
    assert envelope.request.cache_headers == {}
