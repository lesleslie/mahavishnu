"""Tests for the Bifrost gateway contract helpers."""

from __future__ import annotations

from mahavishnu.llm_gateway import (
    BifrostGatewayRequest,
    CacheMode,
    RouteClass,
    hash_prompt,
    infer_route_class,
)


def test_hash_prompt_is_stable_for_trivial_whitespace() -> None:
    assert hash_prompt("hello world") == hash_prompt("  hello world  ")
    assert hash_prompt("hello\r\nworld") == hash_prompt("hello\nworld")


def test_infer_route_class_prefers_task_label() -> None:
    assert infer_route_class(task_label="think") is RouteClass.THINK
    assert infer_route_class(task_label="background") is RouteClass.BACKGROUND
    assert infer_route_class(task_label="web_search") is RouteClass.WEB_SEARCH


def test_infer_route_class_falls_back_to_request_type_and_model() -> None:
    assert infer_route_class(request_type="image") is RouteClass.IMAGE
    assert infer_route_class(model="glm-vision-pro") is RouteClass.IMAGE
    assert infer_route_class(model="glm-5-mini") is RouteClass.CHEAP
    assert infer_route_class(model="glm-5-long-context") is RouteClass.LONG_CONTEXT
    assert infer_route_class() is RouteClass.DEFAULT


def test_trusted_wrapper_emits_route_and_cache_headers() -> None:
    request = BifrostGatewayRequest(
        caller_id="claude-code",
        protocol_family="anthropic",
        provider="zai",
        model="glm-5",
        prompt="write a parser",
        task_label="think",
        trusted_wrapper=True,
        cache_mode=CacheMode.DIRECT,
        cache_ttl_seconds=300,
        cache_threshold=0.92,
    )

    assert request.route_class is RouteClass.THINK
    assert request.prompt_hash == hash_prompt("write a parser")
    assert request.route_headers["x-bf-task"] == "think"
    assert request.route_headers["x-bf-route"] == "think"
    assert request.cache_headers["x-bf-cache-key"] == request.cache_scope_key
    assert request.cache_headers["x-bf-cache-type"] == "direct"
    assert request.cache_headers["x-bf-cache-ttl"] == "300"
    assert request.cache_headers["x-bf-cache-threshold"] == "0.92"
    assert request.request_headers["x-bf-task"] == "think"


def test_untrusted_wrapper_does_not_emit_sensitive_headers() -> None:
    request = BifrostGatewayRequest(
        caller_id="direct-client",
        protocol_family="openai",
        provider="zai",
        model="glm-5",
        prompt="print hello",
        task_label="image",
        trusted_wrapper=False,
        cache_mode=CacheMode.SEMANTIC,
        cache_ttl_seconds=60,
    )

    assert request.route_class is RouteClass.IMAGE
    assert request.route_headers == {}
    assert request.cache_headers == {}
    assert request.request_headers == {}


def test_cache_scope_key_is_namespaced_by_client_and_route() -> None:
    base = BifrostGatewayRequest(
        caller_id="codex",
        protocol_family="openai",
        provider="zai",
        model="glm-5",
        prompt="same prompt",
        task_label="default",
        trusted_wrapper=True,
        cache_mode=CacheMode.DIRECT,
    )
    other_client = BifrostGatewayRequest(
        caller_id="qwen",
        protocol_family="openai",
        provider="zai",
        model="glm-5",
        prompt="same prompt",
        task_label="default",
        trusted_wrapper=True,
        cache_mode=CacheMode.DIRECT,
    )
    other_route = BifrostGatewayRequest(
        caller_id="codex",
        protocol_family="openai",
        provider="zai",
        model="glm-5",
        prompt="same prompt",
        task_label="think",
        trusted_wrapper=True,
        cache_mode=CacheMode.DIRECT,
    )

    assert base.cache_scope_key != other_client.cache_scope_key
    assert base.cache_scope_key != other_route.cache_scope_key
