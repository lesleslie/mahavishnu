"""Tests for mahavishnu.workers.task_router."""

from __future__ import annotations

import pytest

from mahavishnu.workers.task_router import (
    DEFAULT_LLAMA_SERVER_ROUTING,
    DEFAULT_MINIMAX_ROUTING,
    DEFAULT_OLLAMA_ROUTING,
    RateLimitConfig,
    RateLimiter,
    TaskCategory,
    classify_task,
    configure_rate_limiter,
    get_model_for_task,
    get_rate_limiter,
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
            DEFAULT_OLLAMA_ROUTING,
            "default-model",
        )
        assert cat == TaskCategory.CODE_GENERATION
        assert model == "qwen2.5-coder:7b"

    def test_fallback_to_default_for_unknown(self):
        """Unknown categories fall back to default model."""
        routing = {}
        model, cat = get_model_for_task(
            "write a function",
            routing,
            "fallback-model",
        )
        assert model == "fallback-model"

    def test_minimax_highspeed_for_swarm_quick(self):
        """MiniMax routing uses highspeed variant for SWARM and QUICK."""
        for cat in (TaskCategory.SWARM, TaskCategory.QUICK):
            model, _ = get_model_for_task("do it fast", DEFAULT_MINIMAX_ROUTING, "default")
            assert "highspeed" in model, f"{cat} should use highspeed model, got {model}"

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
        import mahavishnu.workers.task_router as tr

        tr._rate_limiter = None
        assert get_rate_limiter() is None
