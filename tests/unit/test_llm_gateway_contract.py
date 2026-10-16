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


# ============================================================================
# Phase G (v1.5 Bifrost spec) — local llama-server contract changes
# ----------------------------------------------------------------------------
# The Phase G amendment adds two new RouteClass enum members
# (CLASSIFY, EXTRACT) and corresponding entries in _TASK_LABEL_MAP.
# These tests are the contract-layer Phase G change verification:
# they prove the enum and the alias map are wired such that the
# Bifrost ``route-classify`` routing rule's CEL matcher has possible
# matching header values. Without these, the rule is structurally
# dead code (caught by the 3-lens review).
# ============================================================================


def test_classify_routes_via_classify_route_class() -> None:
    """A request with task_label="classify" emits ``x-bf-route: classify``.

    Phase G contract change verification (plan §5 Phase G exit
    criteria). The contract's ``route_headers`` only emits values
    from the ``RouteClass`` enum, so the ``route-classify`` Bifrost
    rule's CEL matcher depends on this enum member existing.
    """
    request = BifrostGatewayRequest(
        caller_id="mahavishnu",
        protocol_family="openai",
        provider="llama-server",
        model="qwen3-8b-q4_k_m",
        prompt="classify: positive sentiment",
        task_label="classify",
        trusted_wrapper=True,
    )
    assert request.route_class is RouteClass.CLASSIFY
    assert request.route_class.value == "classify"
    assert request.route_headers["x-bf-task"] == "classify"
    assert request.route_headers["x-bf-route"] == "classify"


def test_extract_routes_via_extract_route_class() -> None:
    """A request with task_label="extract" emits ``x-bf-route: extract``.

    Companion to ``test_classify_routes_via_classify_route_class``;
    the EXTRACT enum member is the narrower "extract structured
    data from text" task class. The Bifrost ``route-classify``
    rule's CEL matcher includes both ``classify`` and ``extract``
    header values (see the v1.5-amended rule in
    ``config/bifrost/config.template.json``).
    """
    request = BifrostGatewayRequest(
        caller_id="mahavishnu",
        protocol_family="openai",
        provider="llama-server",
        model="qwen3-8b-q4_k_m",
        prompt='extract: {"name": "value"}',
        task_label="extract",
        trusted_wrapper=True,
    )
    assert request.route_class is RouteClass.EXTRACT
    assert request.route_class.value == "extract"
    assert request.route_headers["x-bf-task"] == "extract"
    assert request.route_headers["x-bf-route"] == "extract"


def test_classify_aliases_resolve_to_classify_route_class() -> None:
    """Both ``classify`` and ``classification`` task labels map to ``RouteClass.CLASSIFY``.

    The Phase G amendment added two entries to ``_TASK_LABEL_MAP``
    so callers can use either the underscored form (``classify``)
    or the natural-language form (``classification``). The same
    pattern applies to ``extract`` / ``extraction``.
    """
    for alias in ("classify", "classification"):
        request = BifrostGatewayRequest(
            caller_id="mahavishnu",
            protocol_family="openai",
            provider="llama-server",
            model="qwen3-8b-q4_k_m",
            prompt=f"({alias}) prompt",
            task_label=alias,
            trusted_wrapper=True,
        )
        assert request.route_class is RouteClass.CLASSIFY, f"alias {alias!r} did not resolve"

    for alias in ("extract", "extraction"):
        request = BifrostGatewayRequest(
            caller_id="mahavishnu",
            protocol_family="openai",
            provider="llama-server",
            model="qwen3-8b-q4_k_m",
            prompt=f"({alias}) prompt",
            task_label=alias,
            trusted_wrapper=True,
        )
        assert request.route_class is RouteClass.EXTRACT, f"alias {alias!r} did not resolve"


def test_local_provider_empty_api_key_does_not_send_bearer() -> None:
    """An empty ``api_key`` for the local provider emits no Authorization header.

    Phase G silent-failure guard (plan §5 Phase G exit criteria).
    The local llama-server binds to ``127.0.0.1:8081`` with no
    auth requirement; the env-var ``LLAMA_SERVER_API_KEY`` is
    read but defaults to empty. A naive wrapper that always
    emits ``Authorization: Bearer <key>`` would send
    ``Authorization: Bearer `` (empty bearer) which llama-server
    rejects as malformed. This test asserts the contract: an
    empty key → no Authorization header.

    Note: the actual header emission is in the future
    ``mcp-common`` ``ProviderConfig.extra_headers`` integration
    (Phase B's mcp-common PR). For now we test the contract
    shape: ``BifrostGatewayRequest.cache_headers`` and
    ``route_headers`` must NOT include ``Authorization`` when no
    auth is configured.
    """
    request = BifrostGatewayRequest(
        caller_id="mahavishnu",
        protocol_family="openai",
        provider="llama-server",
        model="qwen3-8b-q4_k_m",
        prompt="classify: x",
        task_label="classify",
        trusted_wrapper=True,
        cache_mode=CacheMode.OFF,
    )
    # The contract headers don't currently carry Authorization
    # (that's the mcp-common ``extra_headers`` concern). What we
    # CAN test is that the contract surface doesn't accidentally
    # include one.
    for header_name in request.request_headers:
        assert not header_name.lower().startswith("authorization"), (
            f"empty api_key leaked Authorization header: {header_name!r}"
        )
