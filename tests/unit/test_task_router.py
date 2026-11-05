"""Tests for mahavishnu.core.model_routing.

Phase 3b (Plan v3): the routing primitives were atomically migrated
from ``mahavishnu/workers/task_router.py`` to ``mahavishnu/core/model_routing.py``.
Test file path kept as ``tests/unit/test_task_router.py`` to preserve CI
guard identity; only the import targets changed.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from mahavishnu.core.model_routing import (
    DEFAULT_LLAMA_SERVER_ROUTING,
    DEFAULT_MINIMAX_ROUTING,
    DEFAULT_RUNPOD_PUBLIC_ROUTING,
    RateLimitConfig,
    RateLimiter,
    TaskCategory,
    classify_task,
    configure_rate_limiter,
    gateway_openai_base_url,
    get_model_for_task,
    get_rate_limiter,
    resolve_llama_server_routing,
    resolve_minimax_routing,
    resolve_runpod_public_routing,
    routing_to_task_map,
)


class TestTaskCategoryValues:
    """Test TaskCategory enum members."""

    def test_all_expected_categories_exist(self):
        """All expected TaskCategory values are present."""
        expected = {
            "code_generation",
            "code_review",
            "debugging",
            "refactoring",
            "documentation",
            "testing",
            "reasoning",
            "creative",
            "analysis",
            "vision",
            "embedding",
            "general",
            "swarm",
            "quick",
            "ml_inference",
            "agent_loop",
        }
        actual = {c.value for c in TaskCategory}
        assert expected.issubset(actual)


class TestClassifyTask:
    """Test task classification logic."""

    def test_empty_prompt_returns_general(self):
        """Empty prompt must return GENERAL category."""
        assert classify_task("") == TaskCategory.GENERAL

    def test_code_generation_keywords(self):
        """Prompts with code generation keywords are classified correctly."""
        prompts = [
            "write a function to sort a list",
            "create a new API endpoint",
            "implement a cache",
            "generate a class for users",
        ]
        for prompt in prompts:
            assert classify_task(prompt) == TaskCategory.CODE_GENERATION, f"Failed: {prompt}"

    def test_debugging_keywords(self):
        """Prompts with debugging keywords are classified correctly."""
        prompts = [
            "debug the authentication flow",
            "fix the memory leak",
            "resolve the timeout error",
            "troubleshoot the connection issue",
        ]
        for prompt in prompts:
            assert classify_task(prompt) == TaskCategory.DEBUGGING, f"Failed: {prompt}"

    def test_code_review_keywords(self):
        """Prompts with review keywords are classified correctly."""
        prompts = [
            "audit the implementation for security issues",
        ]
        for prompt in prompts:
            assert classify_task(prompt) == TaskCategory.CODE_REVIEW, f"Failed: {prompt}"

    def test_refactoring_keywords(self):
        """Prompts with refactoring keywords are classified correctly."""
        prompts = [
            "refactor the user service to use dependency injection",
            "restructure the codebase into cleaner modules",
            "reorganize the data layer separation",
        ]
        for prompt in prompts:
            assert classify_task(prompt) == TaskCategory.REFACTORING, f"Failed: {prompt}"

    def test_documentation_keywords(self):
        """Prompts with documentation keywords are classified correctly."""
        prompts = [
            "describe the architecture in a user guide",
        ]
        for prompt in prompts:
            assert classify_task(prompt) == TaskCategory.DOCUMENTATION, f"Failed: {prompt}"

    def test_testing_keywords(self):
        """Prompts with testing keywords are classified correctly."""
        prompts = [
            "add pytest fixtures for database isolation",
            "mock the external API calls",
        ]
        for prompt in prompts:
            assert classify_task(prompt) == TaskCategory.TESTING, f"Failed: {prompt}"

    def test_reasoning_keywords(self):
        """Prompts with reasoning keywords are classified correctly."""
        prompts = [
            "why does this approach reduce database queries",
            "compare the two algorithms by time complexity",
        ]
        for prompt in prompts:
            assert classify_task(prompt) == TaskCategory.REASONING, f"Failed: {prompt}"

    def test_analysis_keywords(self):
        """Prompts with analysis keywords are classified correctly."""
        prompts = [
            "analyze the performance metrics for the query pipeline",
            "assess the memory usage patterns in the worker pool",
            "evaluate the throughput statistics across all endpoints",
        ]
        for prompt in prompts:
            assert classify_task(prompt) == TaskCategory.ANALYSIS, f"Failed: {prompt}"

    def test_swarm_keywords(self):
        """Prompts with swarm/parallel keywords are classified correctly."""
        prompts = [
            "run 100 tasks in parallel across the worker pool",
            "batch process all items in the queue concurrently",
            "scale the workers across multiple machines for bulk operations",
        ]
        for prompt in prompts:
            assert classify_task(prompt) == TaskCategory.SWARM, f"Failed: {prompt}"

    def test_quick_keywords(self):
        """Prompts with quick/fast keywords are classified correctly."""
        prompts = [
            "brief summary of the deployment steps needed right now",
            "fast response needed for this customer escalation",
        ]
        for prompt in prompts:
            assert classify_task(prompt) == TaskCategory.QUICK, f"Failed: {prompt}"

    def test_ml_inference_keywords(self):
        """Prompts with ML inference keywords are classified correctly."""
        prompts = [
            "run inference on the fine-tuned model checkpoint for classification",
            "load the weights and serve predictions on the GPU",
            "deploy the ML model for real-time inference on requests",
        ]
        for prompt in prompts:
            assert classify_task(prompt) == TaskCategory.ML_INFERENCE, f"Failed: {prompt}"

    def test_vision_context_overrides_text(self):
        """Vision context flag overrides text-based classification."""
        assert classify_task("analyze the code", context={"has_image": True}) == TaskCategory.VISION
        assert (
            classify_task("check the metrics", context={"file_type": "image/png"})
            == TaskCategory.VISION
        )

    def test_embedding_context_overrides_text(self):
        """Embedding context flag overrides text-based classification."""
        assert classify_task("run the task", context={"embedding": True}) == TaskCategory.EMBEDDING
        assert classify_task("process the data", context={"vector": True}) == TaskCategory.EMBEDDING

    def test_unknown_prompt_returns_general(self):
        """Prompts with no matching patterns return GENERAL."""
        assert classify_task("hello world") == TaskCategory.GENERAL

    def test_multiple_patterns_takes_highest_score(self):
        """When multiple categories match, highest score wins."""
        # "debug" matches DEBUGGING, "write" matches CODE_GENERATION
        result = classify_task("write code to debug the error")
        assert result in (TaskCategory.DEBUGGING, TaskCategory.CODE_GENERATION)


class TestGetModelForTask:
    """Test model selection from routing tables."""

    def test_uses_category_routing(self):
        """get_model_for_task uses routing table for known category."""
        model, cat = get_model_for_task(
            "write a function",
            DEFAULT_LLAMA_SERVER_ROUTING,
            "default-model",
        )
        assert cat == TaskCategory.CODE_GENERATION
        assert model == "qwen3.5"

    def test_fallback_to_default_for_unknown(self):
        """Unknown categories fall back to default model."""
        routing = {}
        model, _cat = get_model_for_task(
            "write a function",
            routing,
            "fallback-model",
        )
        assert model == "fallback-model"

    def test_minimax_latency_bucket_routes_to_flash(self):
        """Latency-sensitive categories route to MiniMax-M3.1-Flash.

        Covers SWARM, QUICK, AGENT_LOOP, CREATIVE, and GENERAL — the
        categories that historically wanted a speed-tier model. They
        now route to ``MiniMax-M3.1-Flash`` (added 2026-10-19; verified
        available on the MiniMax API). The earlier ``MiniMax-M3-highspeed``
        variant does not exist on the MiniMax API (returns error 2013,
        verified 2026-09-16); if any of these regress to that stale
        name in YAML or code, this test fires.

        Test history:
        - Pre 2026-09-16: asserted ``"highspeed" in model`` (the OLD
          behavior); CI went red once the routing collapsed to M3.
        - Post 2026-09-16 fix (commit 9d337b30): asserted all five
          categories route to ``MiniMax-M3``.
        - Post 2026-10-19 update: re-routed the latency bucket to
          ``MiniMax-M3.1-Flash``. This test now pins that routing.
        """
        latency_cats = (
            TaskCategory.SWARM,
            TaskCategory.QUICK,
            TaskCategory.AGENT_LOOP,
            TaskCategory.CREATIVE,
            TaskCategory.GENERAL,
        )
        for cat in latency_cats:
            model, _ = get_model_for_task("do it fast", DEFAULT_MINIMAX_ROUTING, "default")
            assert model == "MiniMax-M3.1-Flash", (
                f"{cat} should route to MiniMax-M3.1-Flash (the speed-tier "
                f"M-series variant the MiniMax API exposes). Got {model!r}. "
                f"If a future MiniMax model is added, update this "
                f"assertion AND DEFAULT_MINIMAX_ROUTING together."
            )
            assert "highspeed" not in model, (
                f"{cat} resolved to a non-existent MiniMax-M3-highspeed "
                f"variant — that model name is rejected with error "
                f"2013 by the MiniMax API. Got {model!r}."
            )

    def test_llama_server_single_model_all_categories(self):
        """Llama-server uses single model for all categories."""
        for cat in TaskCategory:
            model, _ = get_model_for_task("do something", DEFAULT_LLAMA_SERVER_ROUTING, "x")
            assert model == "qwen3.5", f"Expected qwen3.5 for {cat}, got {model}"


class TestRoutingToTaskMap:
    """Test routing table format conversion."""

    def test_converts_category_keys_to_string(self):
        """routing_to_task_map converts TaskCategory keys to string keys."""
        routing = {
            TaskCategory.CODE_GENERATION: "qwen2.5-coder:7b",
            TaskCategory.REASONING: "llama3:8b",
        }
        result = routing_to_task_map(routing)
        assert "code_generation" in result
        assert "reasoning" in result
        assert result["code_generation"] == "qwen2.5-coder:7b"


# =========================================================================
# Operator-config routing guards
# =========================================================================


class TestRoutingCoverage:
    """Guard the *coverage* of the operator routing config.

    ``settings/models.yaml`` is the operator's source of truth for
    task-to-model routing; the in-code ``DEFAULT_*_ROUTING`` tables are the
    built-in fallback. This guard makes sure neither side can drop a
    category on the floor.

    It deliberately does NOT assert that the two sides agree on model ids.
    They are allowed to differ -- that is the operator exercising the
    config. What must hold is that every category resolves to a model in
    every table.
    """

    @staticmethod
    def _settings_path(name: str) -> Path:
        return Path(__file__).resolve().parents[2] / "settings" / name

    @classmethod
    def _load_yaml_provider_routing(cls, provider_name: str) -> dict[str, str]:
        """Load ``provider_name.task_routing`` from settings/models.yaml."""
        raw = yaml.safe_load(cls._settings_path("models.yaml").read_text()) or {}
        block = raw.get(provider_name)
        if not isinstance(block, dict):
            return {}
        routing = block.get("task_routing")
        return dict(routing) if isinstance(routing, dict) else {}

    @pytest.mark.req(["REQ-YAML-005"])
    @pytest.mark.parametrize("provider", ["minimax", "llama_server", "runpod_public"])
    def test_operator_config_covers_every_category(self, provider: str) -> None:
        """Every TaskCategory must be named by the operator config.

        A category missing here falls back to the built-in table, so the
        route survives -- but the operator's config is then not describing
        the system. That is how the EMBEDDING and llama_server gaps
        survived the original sync guard: it only checked the YAML-to-code
        direction, so a category absent from the YAML was invisible.
        """
        routing = self._load_yaml_provider_routing(provider)
        assert routing, f"settings/models.yaml must declare a {provider} block"

        named = {key.upper() for key in routing}
        missing = {category.name for category in TaskCategory} - named
        assert not missing, (
            f"{provider}.task_routing in settings/models.yaml does not cover "
            f"{sorted(missing)}; the operator config must name every TaskCategory"
        )

    @pytest.mark.parametrize(
        "table",
        [DEFAULT_MINIMAX_ROUTING, DEFAULT_LLAMA_SERVER_ROUTING, DEFAULT_RUNPOD_PUBLIC_ROUTING],
    )
    def test_builtin_tables_cover_every_category(self, table) -> None:
        """The built-in fallback must route every category.

        It is the only table a deployment without the operator config has.
        """
        missing = {category.name for category in TaskCategory} - {
            category.name for category in table
        }
        assert not missing, f"built-in routing table is missing {sorted(missing)}"

    @pytest.mark.parametrize(
        "resolver",
        [resolve_minimax_routing, resolve_llama_server_routing, resolve_runpod_public_routing],
    )
    def test_effective_tables_cover_every_category(self, resolver) -> None:
        """The effective table must route every category."""
        table = resolver()
        missing = {category.name for category in TaskCategory} - {
            category.name for category in table
        }
        assert not missing, f"effective routing table is missing {sorted(missing)}"

    def test_fallback_keys_avoid_retired_models(self):
        """The FALLBACK meta-keys must not point at a retired MiniMax model.

        MiniMax closes M2.7/M2.5 to new users on 2026-10-19 and retires them
        on 2026-11-18, so a fallback entry naming an M2.x model is a routing
        dead end waiting to happen. Nothing else catches it: the built-in
        table does not carry these meta-keys.
        """
        raw = self._load_yaml_provider_routing("minimax")
        fallbacks = {k: v for k, v in raw.items() if k.startswith("FALLBACK")}

        assert fallbacks, "the FALLBACK meta-keys must still be present"
        for key, model in fallbacks.items():
            assert "M2." not in model, (
                f"{key} points at retired model {model!r}; "
                f"MiniMax retires the M2.x line on 2026-11-18"
            )

        assert fallbacks["FALLBACK"] == "MiniMax-M3"
        assert fallbacks["FALLBACK_HIGHSPEED"] == "MiniMax-M3.1-Flash"

    def test_yaml_covers_high_traffic_categories(self):
        """The operator config must cover the categories every prompt hits.

        A category missing from the config falls through to the built-in
        default -- fine for niche categories but a quality hazard for
        high-traffic ones. The CI guard enforces the floor.
        """
        yaml_routing = self._load_yaml_provider_routing("minimax")

        required = {
            "CODE_GENERATION",
            "CODE_REVIEW",
            "DEBUGGING",
            "REFACTORING",
            "TESTING",
            "REASONING",
            "ANALYSIS",
            "DOCUMENTATION",
            "SWARM",
            "QUICK",
            "AGENT_LOOP",
            "CREATIVE",
            "GENERAL",
        }
        missing = required - set(yaml_routing.keys())
        assert not missing, f"YAML must cover high-traffic categories: {sorted(missing)}"

    @pytest.mark.req(["REQ-YAML-007"])
    def test_no_dead_models_path_key(self) -> None:
        """``settings/mahavishnu.yaml`` must not declare an unread ``models_path``.

        The key was accepted by ``MahavishnuSettings`` (``extra="allow"``)
        and read by nothing, so it looked like a live knob. The override is
        ``MAHAVISHNU_MODELS_PATH``; the default path needs no key.
        """
        raw = yaml.safe_load(self._settings_path("mahavishnu.yaml").read_text()) or {}
        assert "models_path" not in raw, (
            "settings/mahavishnu.yaml declares models_path, which no code reads; "
            "use MAHAVISHNU_MODELS_PATH or delete the key"
        )


class TestRateLimiter:
    """Test rate limiting functionality."""

    def test_config_defaults(self):
        """RateLimitConfig has correct defaults."""
        config = RateLimitConfig(limit=10)
        assert config.limit == 10
        assert config.window_seconds == 60.0

    @pytest.mark.asyncio
    async def test_allows_requests_under_limit(self):
        """Requests under rate limit are allowed."""
        config = RateLimitConfig(limit=5, window_seconds=60.0)
        limiter = RateLimiter(config)

        for _ in range(5):
            result = await limiter.check_and_record("model1", "user1")
            assert result is True

    @pytest.mark.asyncio
    async def test_blocks_requests_over_limit(self):
        """Requests over rate limit are blocked."""
        config = RateLimitConfig(limit=3, window_seconds=60.0)
        limiter = RateLimiter(config)

        for _ in range(3):
            await limiter.check_and_record("model1", "user1")

        result = await limiter.check_and_record("model1", "user1")
        assert result is False

    @pytest.mark.asyncio
    async def test_different_keys_independent(self):
        """Different model/user keys have independent rate limits."""
        config = RateLimitConfig(limit=2, window_seconds=60.0)
        limiter = RateLimiter(config)

        assert await limiter.check_and_record("model1", "user1") is True
        assert await limiter.check_and_record("model1", "user1") is True
        assert await limiter.check_and_record("model1", "user1") is False

        assert await limiter.check_and_record("model2", "user1") is True
        assert await limiter.check_and_record("model1", "user2") is True


class TestRateLimiterModuleLevel:
    """Test module-level rate limiter configuration."""

    def test_configure_and_get(self):
        """configure_rate_limiter and get_rate_limiter work together."""
        config = RateLimitConfig(limit=100)
        configure_rate_limiter(config)
        assert get_rate_limiter() is not None
        assert get_rate_limiter()._config.limit == 100

    def test_get_rate_limiter_none_when_unset(self):
        """get_rate_limiter returns None before configuration."""
        import mahavishnu.core.model_routing as tr

        tr._rate_limiter = None
        assert get_rate_limiter() is None


class TestGatewayOpenAIBaseUrl:
    """The gateway's OpenAI-compatible root, with exactly one ``/v1``.

    Both LLM consumers -- the CloudWorker's FallbackChain and the Agno
    adapter's provider factory -- need the gateway's OpenAI-compatible
    root, and both used to append ``/v1`` unconditionally. That was
    right until oneiric changed its router default to include the
    suffix (cd59122, 2026-10-19), after which both produced
    ``http://127.0.0.1:8471/v1/v1`` -- a path the gateway does not
    serve.

    Measured against the running gateway on 2026-11-02: a ``POST`` to
    the doubled path returns ``405 Method Not Allowed``. A ``GET`` would
    not have shown the problem -- Bifrost's dashboard serves its SPA
    fallback for *any* unmatched path, so every unmatched ``GET``
    returns ``200`` with the dashboard HTML.
    """

    @pytest.mark.parametrize(
        ("resolved", "expected"),
        [
            # oneiric's current default: already carries /v1.
            ("http://127.0.0.1:8471/v1", "http://127.0.0.1:8471/v1"),
            ("http://127.0.0.1:8471/v1/", "http://127.0.0.1:8471/v1"),
            # The pre-cd59122 default: bare gateway root, needs the suffix.
            ("http://127.0.0.1:8471", "http://127.0.0.1:8471/v1"),
            ("http://127.0.0.1:8471/", "http://127.0.0.1:8471/v1"),
        ],
    )
    def test_suffix_is_applied_idempotently(self, resolved: str, expected: str) -> None:
        assert gateway_openai_base_url(resolved) == expected

    def test_result_is_idempotent(self) -> None:
        """Applying it twice changes nothing -- the property that matters."""
        once = gateway_openai_base_url("http://127.0.0.1:8471/v1")
        assert gateway_openai_base_url(once) == once
