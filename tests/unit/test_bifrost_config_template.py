"""Guards on the Bifrost gateway config template.

The gateway's config store is authoritative at runtime and the template is
what seeds it. Three failure modes there are **silent** -- the gateway starts
cleanly, health is green, and the request simply does not work:

1. A custom provider whose name collides with a *standard* provider name.
   Upstream refuses such a name outright -- the providers API answers HTTP
   400, "Custom provider cannot be same as a standard provider" -- and the
   config-file import on this deployment did not register the provider
   either: the store held no ``anthropic`` row, so every Claude Code request
   failed with ``failed to get config for provider anthropic: not found``
   until the provider was renamed to ``minimax-anthropic``.
2. ``allowed_requests`` and ``request_path_overrides`` are keyed by Bifrost
   request type. ``messages`` is not one of them -- the Anthropic HTTP route
   bridges to Bifrost's ``responses`` type -- so a provider configured with
   ``{"messages": true}`` allows *nothing*, because unspecified fields default
   to false.
3. A routing rule that pins the *model* rather than the provider silently
   overrides the caller's model. Claude Code selects the model per request
   class, so a pinned model downgrades the 1M-context variant without any
   error. Upstream keeps the incoming model when a target omits it.
4. A key-level *alias* whose name is missing from the key's ``models``
   allowlist. Bifrost treats alias names as model identifiers for key
   selection and allowlists, so an alias the allowlist does not list cannot
   select the key -- the request fails with ``no_key_supports_model`` exactly
   as it did before the alias was added. Upstream issue
   maximhq/bifrost#3278 documents this; the alias and the allowlist entry
   must both be present.

These tests pin those contracts against the upstream Bifrost schemas.

Note that these tests see the **template** only. The live store in
``~/.config/bifrost/config.db`` is a separate artifact, seeded from the
template; a rule or provider that is correct here can still be missing from
a store that was never re-seeded.

req: REQ-BIFROST-038, REQ-BIFROST-039
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

TEMPLATE_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "bifrost" / "config.template.json"
)

#: Standard provider names (Bifrost ``schemas.ModelProvider``). A custom
#: provider may not reuse one of these -- the config store drops it.
STANDARD_PROVIDER_NAMES = frozenset(
    {
        "anthropic",
        "azure",
        "bedrock",
        "bedrock_mantle",
        "byteplus",
        "cerebras",
        "cloudflare",
        "cohere",
        "databricks",
        "deepseek",
        "elevenlabs",
        "fireworks",
        "gemini",
        "groq",
        "huggingface",
        "minimax",
        "mistral",
        "nebius",
        "ollama",
        "openai",
        "opencode-go",
        "opencode-zen",
        "openrouter",
        "parasail",
        "perplexity",
        "replicate",
        "runware",
        "runway",
        "sagemaker",
        "sarvam",
        "sgl",
        "typesafe",
        "vertex",
        "vllm",
        "wafer",
        "xai",
    }
)

#: Valid request-type keys (Bifrost ``schemas.AllowedRequests`` and the
#: ``schemas.RequestType`` constants). Note the absence of ``messages``:
#: Bifrost's Anthropic HTTP route bridges to the generic ``responses`` type.
REQUEST_TYPES = frozenset(
    {
        "list_models",
        "model_retrieve",
        "text_completion",
        "text_completion_stream",
        "chat_completion",
        "chat_completion_stream",
        "responses",
        "responses_stream",
        "responses_retrieve",
        "responses_retrieve_stream",
        "responses_delete",
        "responses_cancel",
        "responses_input_items",
        "count_tokens",
        "compaction",
        "embedding",
        "rerank",
        "decisions",
        "ocr",
        "speech",
        "speech_stream",
        "transcription",
        "transcription_stream",
        "image_generation",
        "image_generation_stream",
        "image_edit",
        "image_edit_stream",
        "image_variation",
        "video_generation",
        "video_edit",
        "video_retrieve",
        "video_download",
        "video_delete",
        "video_list",
        "video_remix",
        "batch_create",
        "batch_list",
        "batch_retrieve",
        "batch_cancel",
        "batch_delete",
        "batch_results",
        "file_upload",
        "file_list",
        "file_retrieve",
        "file_delete",
        "file_content",
        "container_create",
        "container_list",
        "container_retrieve",
        "container_delete",
        "container_file_create",
        "container_file_list",
    }
)


#: Providers whose keys carry Claude model aliases onto MiniMax models.
#: Both surfaces get them so the behaviour does not depend on which one a
#: client happens to reach.
ALIASED_PROVIDERS = ("minimax-anthropic", "minimax-openai")

#: Claude model ids that first-party Anthropic tooling asks for by name.
#: The security-review plugin and Claude Code's bundled ``claude-api`` skill
#: both request these; with no alias the gateway answers "no keys found that
#: support model" and the caller fails silently -- a commit review that
#: returns no verdict, a capability probe that never runs.
CLAUDE_MODEL_IDS = (
    "claude-opus-5-5",
    "claude-opus-5.5",
    "claude-opus-4-6",
    "claude-sonnet-5-5",
    "claude-sonnet-4-6",
    "claude-sonnet-4.6",
    "claude-haiku-5-5",
    "claude-haiku-4-5",
    "claude-fable-5-1",
    "claude-mythos-5-1",
)


def _template() -> dict[str, Any]:
    return json.loads(TEMPLATE_PATH.read_text(encoding="utf-8"))


def _providers() -> dict[str, Any]:
    return _template().get("providers") or {}


def _rules() -> list[dict[str, Any]]:
    return _template().get("governance", {}).get("routing_rules") or []


def _rule(rule_id: str) -> dict[str, Any]:
    for rule in _rules():
        if rule.get("id") == rule_id:
            return rule
    raise AssertionError(f"routing rule {rule_id!r} is missing from the template")


def test_custom_provider_names_do_not_collide_with_standard_providers() -> None:
    """A custom provider may not be named after a standard provider.

    Upstream's providers API rejects such a name with HTTP 400 ("Custom
    provider cannot be same as a standard provider"), and the config-file
    import did not register the provider on this deployment either. Either
    way the provider never exists, and every request that should have used
    it falls through to whatever else claims the model.
    """
    for name, provider in _providers().items():
        if not (provider.get("custom_provider_config") or {}):
            continue
        assert name not in STANDARD_PROVIDER_NAMES, (
            f"custom provider {name!r} collides with a standard Bifrost provider "
            f"name; upstream refuses the name and the config-store import did "
            f"not register it. Give it a distinct name."
        )


def test_allowed_requests_keys_are_valid_request_types() -> None:
    """``allowed_requests`` keys must be real request types.

    Unspecified fields default to false, so a single wrong key can leave a
    provider allowing nothing at all.
    """
    for name, provider in _providers().items():
        allowed = (provider.get("custom_provider_config") or {}).get("allowed_requests")
        if allowed is None:
            continue
        unknown = set(allowed) - REQUEST_TYPES
        assert not unknown, (
            f"provider {name!r} has unknown allowed_requests keys {sorted(unknown)}; "
            f"they will be ignored and every other operation defaults to false"
        )


def test_request_path_override_keys_are_valid_request_types() -> None:
    """``request_path_overrides`` is keyed by request type too.

    A wrong key means the override is silently dropped and the provider posts
    to its default path -- which for the Anthropic base type is
    ``/v1/responses``, not the Anthropic-native ``/v1/messages``.
    """
    for name, provider in _providers().items():
        overrides = (provider.get("custom_provider_config") or {}).get(
            "request_path_overrides"
        )
        if not overrides:
            continue
        unknown = set(overrides) - REQUEST_TYPES
        assert not unknown, (
            f"provider {name!r} has unknown request_path_overrides keys {sorted(unknown)}"
        )


def test_governance_rule_targets_reference_configured_providers() -> None:
    """A rule target must name a provider the template actually configures.

    The rule engine resolves the target provider against the config store;
    an unknown provider id is not an error at write time -- the request
    simply falls through to the fallback chain.
    """
    providers = _providers()
    for rule in _template().get("governance", {}).get("routing_rules", []):
        for target in rule.get("targets") or []:
            provider = target.get("provider")
            if provider is None:
                continue
            assert provider in providers, (
                f"rule {rule.get('id')!r} targets provider {provider!r}, "
                f"which the template does not configure"
            )


def test_the_anthropic_native_provider_exists_and_is_usable() -> None:
    """The Anthropic-native MiniMax provider must survive the import.

    This is the provider Claude Code needs: it reaches MiniMax over
    MiniMax's own ``/anthropic/v1/messages``, which returns genuine
    Anthropic responses with signed thinking blocks.
    """
    provider = _providers().get("minimax-anthropic")
    assert provider is not None, (
        "the Anthropic-native MiniMax provider is missing; Claude Code would "
        "fall through to the OpenAI-compatible provider, where reasoning "
        "arrives inline in the assistant text"
    )

    cpc = provider["custom_provider_config"]
    assert cpc["base_provider_type"] == "anthropic"
    assert cpc["allowed_requests"]["responses"] is True
    assert cpc["request_path_overrides"]["responses"].endswith("/v1/messages")
    assert provider["network_config"]["base_url"] == "https://api.minimax.io"


def test_the_openai_compatible_provider_still_allows_chat_completion() -> None:
    """The worker's route must keep working.

    The Mahavishnu cloud worker talks to the gateway over
    ``/v1/chat/completions``. If the Anthropic-native provider ends up
    claiming the model for that route too, the worker breaks.
    """
    cpc = _providers()["minimax-openai"]["custom_provider_config"]
    assert cpc["allowed_requests"]["chat_completion"] is True
    assert cpc["allowed_requests"]["chat_completion_stream"] is True


def test_the_anthropic_native_provider_allows_count_tokens() -> None:
    """Claude Code's token-count call must not be refused by the provider.

    ``POST /v1/messages/count_tokens`` is a first-class Anthropic route.
    The route header travels on *every* request, so the token-count call
    matches the Anthropic-native rule too. If the provider does not allow
    ``count_tokens``, the gateway answers "operation not allowed" instead of
    a token count. The path override matters too: MiniMax's Anthropic
    surface lives under ``/anthropic/``, so the default Anthropic path
    is unrouted and the gateway answers ``405 Method Not Allowed``.
    """
    cpc = _providers()["minimax-anthropic"]["custom_provider_config"]

    assert cpc["allowed_requests"].get("count_tokens") is True, (
        "the Anthropic-native provider refuses count_tokens, so Claude Code's "
        "token-count call fails on the route that carries x-bf-route"
    )
    assert cpc["request_path_overrides"].get("count_tokens") == (
        "/anthropic/v1/messages/count_tokens"
    ), (
        "count_tokens must be routed at MiniMax's Anthropic-native path; "
        "the default Anthropic path does not exist on that host"
    )


def test_the_anthropic_native_rule_does_not_pin_the_model() -> None:
    """The rule must pin the provider, not the model.

    Claude Code picks the model per request class -- ``MiniMax-M3`` for the
    opus and sonnet slots, ``MiniMax-M3.1-Flash`` for the haiku slot. A
    target that names a model overwrites the caller's choice outright, which
    silently moves the fast slot onto the heavy model with no error and no
    log line. Upstream keeps the incoming model when the target omits it.
    """
    for target in _rule("route-anthropic-native")["targets"]:
        assert not target.get("model"), (
            "the Anthropic-native rule pins a model; upstream overwrites the "
            "caller's model identifier with it, which moves Claude Code's "
            "haiku slot onto the heavy model. Omit 'model' and let the "
            "incoming model through."
        )


def test_the_anthropic_native_provider_covers_every_model_claude_code_sends() -> None:
    """The provider's key must list the model ids Claude Code actually sends.

    The rule lets the caller's model through, so the provider's key has to
    support it -- a model that is not in the key's list resolves to
    ``no_key_supports_model``.
    """
    models = {
        model
        for key in _providers()["minimax-anthropic"]["keys"]
        for model in key["models"]
    }
    for model in ("MiniMax-M3", "MiniMax-M3.1-Flash"):
        assert model in models, (
            f"{model!r} is missing from the Anthropic-native provider's key; "
            f"Claude Code sends it and the rule no longer substitutes a model"
        )


def test_the_retired_1m_spelling_is_not_allowlisted() -> None:
    """The ``[1m]`` spelling must not be in any key's model list.

    Claude Code strips the suffix before the request goes on the wire, so
    nothing sends it. Keeping it allowlisted was actively *worse* than
    dropping it: with the entry present, key selection matched the key and
    Bifrost then handed MiniMax an id the provider rejects
    (``invalid params, unknown model 'MiniMax-M3[1m]' (2013)``). Without the
    entry, key selection does not match and the request falls through to the
    rule's fallback -- a model that exists -- and is served.
    """
    for provider_id in ALIASED_PROVIDERS:
        for key in _providers()[provider_id]["keys"]:
            assert "MiniMax-M3[1m]" not in key["models"], (
                f"{provider_id}/{key['name']}: the retired '[1m]' spelling is "
                f"still allowlisted, which makes Bifrost forward an id "
                f"MiniMax rejects"
            )


def test_the_anthropic_native_rule_fallback_can_serve_the_same_request() -> None:
    """A fallback must be able to serve the request type the rule produces.

    The Anthropic HTTP route bridges every request to Bifrost's ``responses``
    request type. A provider that only allows ``chat_completion`` cannot
    serve it, so a fallback pointing at one is inert: the request fails hard
    instead of degrading to a working answer.
    """
    providers = _providers()
    fallbacks = _rule("route-anthropic-native").get("fallbacks") or []
    assert fallbacks == [
        "openai/gpt-5.4-mini",
    ], "OpenAI GPT-5.4 mini should be the Anthropic-route fallback"
    for fallback in fallbacks:
        provider_id = fallback.split("/", 1)[0]
        provider = providers.get(provider_id)
        assert provider is not None, (
            f"fallback {fallback!r} names a provider the template does not configure"
        )
        custom = provider.get("custom_provider_config") or {}
        can_serve_responses = (
            custom.get("allowed_requests", {}).get("responses") is True
            if custom
            else provider_id == "openai"
        )
        assert can_serve_responses, (
            f"fallback {fallback!r} points at a provider that does not allow the "
            f"'responses' request type, which is what the Anthropic route "
            f"produces -- the fallback cannot serve it"
        )
    openai_models = {
        model for key in providers["openai"]["keys"] for model in key["models"]
    }
    assert "gpt-5.4-mini" in openai_models, (
        "the OpenAI fallback model must be present in the provider key allowlist"
    )


def test_claude_model_ids_are_aliased_on_both_minimax_providers() -> None:
    """The Claude ids first-party tooling sends must resolve to a MiniMax model.

    A Claude Code *plugin* calls the Anthropic API directly and picks its own
    model id, so it asks the gateway for ``claude-opus-5-5`` regardless of
    what the session's model settings say. Without an alias the request is
    refused with ``no_key_supports_model`` and the caller fails silently --
    observed on 2026-11-06 as a security review that returned no verdict on
    three separate commits.
    """
    providers = _providers()
    for provider_id in ALIASED_PROVIDERS:
        provider = providers.get(provider_id)
        assert provider is not None, (
            f"provider {provider_id!r} is missing from the template"
        )
        aliases = {
            alias for key in provider["keys"] for alias in (key.get("aliases") or {})
        }
        missing = sorted(set(CLAUDE_MODEL_IDS) - aliases)
        assert not missing, (
            f"provider {provider_id!r} has no alias for {missing}; a client "
            f"asking for those ids gets 'no keys found that support model'"
        )


def test_alias_names_are_also_in_the_key_allowlist() -> None:
    """An alias name must appear in the key's ``models`` list as well.

    Bifrost treats alias names as model identifiers for key selection and
    allowlists. When the allowlist is restricted -- and these keys' are --
    the alias name has to be listed there too, or the gateway cannot select
    the key for it and the request fails exactly as it did before the alias
    was added. Upstream maximhq/bifrost#3278 documents this.
    """
    for provider_id in ALIASED_PROVIDERS:
        for key in _providers()[provider_id]["keys"]:
            aliases = key.get("aliases") or {}
            models = set(key["models"])
            missing = sorted(set(aliases) - models)
            assert not missing, (
                f"{provider_id}/{key['name']}: alias names {missing} are absent "
                f"from 'models'; the gateway cannot select this key for them, "
                f"so the alias never takes effect"
            )


def test_alias_targets_are_models_the_key_actually_serves() -> None:
    """An alias must resolve to a model the same key is allowed to call.

    The alias is resolved after key selection and before the provider call,
    so a target the key does not serve fails at the provider -- a different
    failure from the one the alias was added to fix.
    """
    for provider_id in ALIASED_PROVIDERS:
        for key in _providers()[provider_id]["keys"]:
            models = set(key["models"])
            unsupported = sorted(
                f"{alias} -> {target}"
                for alias, target in (key.get("aliases") or {}).items()
                if target not in models
            )
            assert not unsupported, (
                f"{provider_id}/{key['name']}: aliases resolve to models this "
                f"key does not serve: {unsupported}"
            )


def test_alias_targets_land_on_the_right_minimax_counterpart() -> None:
    """Opus is MiniMax-M3; Sonnet and Haiku are the concise MiniMax-M3.1-Flash.

    An alias substitutes a model, so the mapping is a deliberate choice about
    which MiniMax model answers for the Claude id -- not an arbitrary one.

    The tiering is not cosmetic. The security-review plugin calls
    ``claude-opus-5-5`` first and falls back to ``claude-sonnet-4-6`` when the
    primary yields no verdict. On a review-sized diff MiniMax-M3's adaptive
    thinking consumes the whole ``max_tokens`` budget and the response comes
    back thinking-only -- no text block, so no verdict. MiniMax-M3.1-Flash
    answers the same payload in a fraction of the budget with usable text.
    Putting the concise model on the Sonnet id is therefore what makes the
    fallback land, while Opus keeps the stronger analysis on the primary
    attempt.
    """
    for provider_id in ALIASED_PROVIDERS:
        for key in _providers()[provider_id]["keys"]:
            for alias, target in (key.get("aliases") or {}).items():
                if any(family in alias for family in ("opus", "fable", "mythos")):
                    assert target == "MiniMax-M3", (
                        f"{provider_id}/{key['name']}: {alias!r} resolves to "
                        f"{target!r}; the reasoning-grade Claude ids map to "
                        f"MiniMax-M3"
                    )
                if any(family in alias for family in ("sonnet", "haiku")):
                    assert target == "MiniMax-M3.1-Flash", (
                        f"{provider_id}/{key['name']}: {alias!r} resolves to "
                        f"{target!r}; the Sonnet and Haiku ids map to the "
                        f"concise MiniMax-M3.1-Flash -- the Sonnet id is what "
                        f"the security-review plugin falls back to, and it has "
                        f"to fit inside the plugin's max_tokens budget"
                    )


def test_no_alias_points_at_a_claude_model() -> None:
    """An alias must not chain into another Claude id.

    Claude ids are not served by this gateway at all, so an alias that
    resolved to one would fail at the provider exactly like the request it
    was meant to rescue.
    """
    for provider_id in ALIASED_PROVIDERS:
        for key in _providers()[provider_id]["keys"]:
            for alias, target in (key.get("aliases") or {}).items():
                assert not target.startswith("claude-"), (
                    f"{provider_id}/{key['name']}: alias {alias!r} resolves to "
                    f"{target!r}, which this gateway does not serve"
                )


#: The tiers the complexity analyzer can publish.
COMPLEXITY_TIERS = ("SIMPLE", "MEDIUM", "COMPLEX")


def _analyzer() -> dict[str, Any]:
    return _template().get("governance", {}).get("complexity_analyzer_config") or {}


def _tiers_in(rule: dict[str, Any]) -> set[str]:
    """The complexity tiers a rule's CEL expression references."""
    expression = rule.get("cel_expression") or ""
    return {tier for tier in COMPLEXITY_TIERS if tier in expression}


def test_the_complexity_analyzer_is_configured_with_the_decision_classifier() -> None:
    """The analyzer must be present and use the decision classifier.

    The decision classifier is the one that understands a *task*; the
    semantic one matches a request against reference phrases, which is a
    much weaker signal for coding work. Omitting the block entirely is
    silent: the gateway starts clean, the rule that references
    ``complexity_tier`` simply never matches, and every request falls
    through to normal routing.
    """
    analyzer = _analyzer()
    assert analyzer, (
        "governance.complexity_analyzer_config is missing; the complexity "
        "rule's complexity_tier never resolves and the router never fires"
    )
    assert analyzer.get("classifier") == "decision", (
        f"classifier is {analyzer.get('classifier')!r}; the decision classifier "
        f"(TypeSafe Jev) is the one that judges the task"
    )
    decision = analyzer.get("decision") or {}
    assert decision.get("provider") == "typesafe", (
        f"decision.provider is {decision.get('provider')!r}; the config "
        f"declares a 'typesafe' provider, so the decision model must resolve "
        f"through it"
    )
    assert decision.get("model"), "decision.model must name the decision model"


def test_session_aware_routing_is_enabled() -> None:
    """``session.enabled`` must be on.

    Without it, a turn's first call (the one carrying the human text) is
    classified and routed by tier, while the turn's continuation calls --
    the tool-result requests -- carry no new human text, get no tier, and
    fall through to the caller's model. One turn would then run on two
    models: the model that decides the next action and the model that
    reads the tool result. Session state keeps the tier for the whole
    session, so the turn stays on one model.

    The cost of enabling it is bounded because the tier policy is
    downward-only: an escalated session stops being classified and reverts
    to the caller's model, which is today's behaviour. A session with no
    id is classified on its own, so the flag is a no-op there.
    """
    session = _analyzer().get("session") or {}
    assert session.get("enabled") is True, (
        "session.enabled must be true; without it a single turn is split "
        "across two models and the provider's prompt cache misses at the "
        "seam"
    )


def test_the_complexity_policy_only_ever_downgrades() -> None:
    """Only the Simple tier may carry a model target.

    Claude Code picks its model per request class -- ``MiniMax-M3`` for the
    opus and sonnet slots, ``MiniMax-M3.1-Flash`` for the haiku slot. A
    rule that pins a model for a higher tier overrides that selection: the
    haiku slot would be pushed onto the heavy model, and the security-review
    plugin's deliberate Sonnet fallback would be overridden back onto
    ``MiniMax-M3``, whose adaptive thinking truncates the response before
    any text block is emitted.

    Downward-only also bounds the ratchet: an escalated session stops
    being classified and reverts to the caller's model, so the policy can
    never cost more than it does today.
    """
    tiered = [rule for rule in _rules() if _tiers_in(rule)]
    assert tiered, "no rule references complexity_tier; the router never fires"

    for rule in tiered:
        assert _tiers_in(rule) == {"SIMPLE"}, (
            f"rule {rule.get('id')!r} references {sorted(_tiers_in(rule))}; "
            f"only SIMPLE may be routed by tier"
        )
        for target in rule.get("targets") or []:
            assert target.get("model") == "MiniMax-M3.1-Flash", (
                f"rule {rule.get('id')!r} targets {target.get('model')!r}; the "
                f"downward-only target is the concise MiniMax-M3.1-Flash"
            )


def test_the_complexity_rule_precedes_the_anthropic_native_rule() -> None:
    """The tier rule must be evaluated first.

    Routing rules are first-match-wins with the lower priority number
    evaluated first, and Claude Code sends ``x-bf-route`` on every
    request -- so ``route-anthropic-native`` (priority 5) matches every
    Claude Code request. A tier rule at priority 5 or above is dead code
    on that path: it is never reached.
    """
    complexity = _rule("route-complexity-simple")
    native = _rule("route-anthropic-native")

    assert complexity["priority"] < native["priority"], (
        f"the complexity rule's priority ({complexity['priority']}) is not "
        f"ahead of route-anthropic-native ({native['priority']}); the "
        f"anthropic-native rule matches every Claude Code request and the "
        f"tier rule would never be evaluated"
    )


def test_the_complexity_rule_is_scoped_to_the_claude_code_route() -> None:
    """The rule must require the route header.

    A Claude Code *plugin* calls the Anthropic API directly and picks its
    own model id, so it reaches the gateway without ``x-bf-route``. An
    unscoped tier rule would capture that traffic too and pin a model over
    the plugin's own choice -- the choice its fallback depends on.
    """
    expression = _rule("route-complexity-simple")["cel_expression"]
    assert "x-bf-route" in expression, (
        "the complexity rule must be guarded by the x-bf-route header so it "
        "only reaches the Claude Code harness and not direct-SDK callers"
    )


def test_the_typesafe_provider_is_configured_for_the_decision_model() -> None:
    """The decision model's provider must exist with an env-backed key.

    ``typesafe`` is a standard Bifrost provider name, so it takes no
    ``custom_provider_config`` -- upstream knows its endpoint and its
    ``decisions`` request type. The key still has to resolve, or Bifrost
    drops it at startup and every classification fails with
    ``no_key_supports_model``.
    """
    provider = _providers().get("typesafe")
    assert provider is not None, (
        "the 'typesafe' provider is missing; the decision classifier has "
        "nothing to resolve against"
    )
    assert not provider.get("custom_provider_config"), (
        "'typesafe' is a standard provider name; adding custom_provider_config "
        "to it collides with upstream's standard provider"
    )
    values = [key.get("value") for key in provider.get("keys") or []]
    assert "env.TYPESAFE_API_KEY" in values, (
        f"the typesafe provider's key values are {values}; the decision model "
        f"needs the env-backed TypeSafe credential"
    )


def test_the_complexity_target_model_is_allowlisted_by_the_provider_key() -> None:
    """The target model must be servable by the provider's key.

    Bifrost resolves a key before dispatching upstream. A model the key
    does not list resolves to ``no_key_supports_model``, and the request
    falls through to the rule's fallback instead of the intended tier.
    """
    models = {
        model
        for key in _providers()["minimax-anthropic"]["keys"]
        for model in key["models"]
    }
    for target in _rule("route-complexity-simple")["targets"]:
        assert target["model"] in models, (
            f"{target['model']!r} is not in the Anthropic-native provider's "
            f"key allowlist; the tier rule cannot dispatch it"
        )


def test_the_complexity_rule_fallback_can_serve_the_anthropic_route() -> None:
    """The fallback must allow the ``responses`` request type.

    The Anthropic HTTP route bridges every request to Bifrost's
    ``responses`` request type. A fallback pointing at a provider that
    only allows ``chat_completion`` is inert: the request fails hard
    instead of degrading to a working answer.
    """
    providers = _providers()
    fallbacks = _rule("route-complexity-simple").get("fallbacks") or []
    assert fallbacks == [
        "openai/gpt-5.6-luna",
    ], "GPT-5.6 Luna should be the SIMPLE-tier fallback"
    for fallback in fallbacks:
        provider_id = fallback.split("/", 1)[0]
        provider = providers.get(provider_id)
        assert provider is not None, (
            f"fallback {fallback!r} names a provider the template does not configure"
        )
        custom = provider.get("custom_provider_config") or {}
        can_serve_responses = (
            custom.get("allowed_requests", {}).get("responses") is True
            if custom
            else provider_id == "openai"
        )
        assert can_serve_responses, (
            f"fallback {fallback!r} points at a provider that does not allow "
            f"the 'responses' request type, which is what the Anthropic "
            f"route produces -- the fallback cannot serve it"
        )
    openai_models = {
        model for key in providers["openai"]["keys"] for model in key["models"]
    }
    assert "gpt-5.6-luna" in openai_models, (
        "the OpenAI fallback model must be present in the provider key allowlist"
    )


def test_the_background_and_classify_routes_use_the_luna_fallback_chain() -> None:
    """Cheap background routes should fall back to Luna before local inference.

    The live store already uses GPT-5.6 Luna as the first OpenAI fallback for
    these routes, which keeps the template aligned with the deployed config and
    avoids drifting back to the older GPT-5.3 Codex fallback.
    """
    providers = _providers()
    for route_id in ("route-background", "route-classify"):
        fallbacks = _rule(route_id).get("fallbacks") or []
        assert fallbacks == [
            "openai/gpt-5.6-luna",
            "llama-server/qwen3-8b-q4_k_m",
        ], f"{route_id} should prefer GPT-5.6 Luna before local inference"
        for fallback in fallbacks:
            provider_id = fallback.split("/", 1)[0]
            assert provider_id in providers, (
                f"fallback {fallback!r} names a provider the template does not configure"
            )
