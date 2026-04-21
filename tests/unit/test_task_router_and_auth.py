"""Tests for workers/task_router.py, core/auth.py, and core/workflow_state.py.

- task_router: pure functions — classify prompts, route to models
- auth: JWT token lifecycle with PyJWT (real signing, no mocks needed)
- workflow_state: local-memory CRUD (OpenSearch path mocked)
"""

import re
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from mahavishnu.workers.task_router import (
    DEFAULT_OLLAMA_ROUTING,
    DEFAULT_ZAI_ROUTING,
    TASK_PATTERNS,
    TaskCategory,
    classify_task,
    get_model_for_task,
)
from mahavishnu.core.auth import JWTAuth, TokenPayload, get_auth_from_config


# =========================================================================
# TaskCategory enum
# =========================================================================


class TestTaskCategory:
    def test_is_str_enum(self):
        assert isinstance(TaskCategory.CODE_GENERATION, str)
        assert TaskCategory.CODE_GENERATION == "code_generation"

    def test_all_values(self):
        expected = {
            "code_generation", "code_review", "debugging", "refactoring",
            "documentation", "testing", "reasoning", "creative",
            "analysis", "vision", "embedding", "general", "swarm", "quick",
        }
        assert set(TaskCategory) == expected

    def test_task_patterns_cover_all_categories(self):
        # GENERAL is the fallback, not in TASK_PATTERNS
        for cat in TaskCategory:
            if cat != TaskCategory.GENERAL:
                assert cat in TASK_PATTERNS
        assert TaskCategory.GENERAL not in TASK_PATTERNS


# =========================================================================
# classify_task
# =========================================================================


class TestClassifyTask:
    def test_empty_prompt(self):
        assert classify_task("") == TaskCategory.GENERAL

    def test_none_prompt(self):
        # None is coerced to string internally, falls through to GENERAL
        assert classify_task(None) == TaskCategory.GENERAL

    def test_code_generation(self):
        assert classify_task("Write a function to parse JSON") == TaskCategory.CODE_GENERATION

    def test_code_generation_create(self):
        assert classify_task("Create a new API endpoint for users") == TaskCategory.CODE_GENERATION

    def test_code_generation_build(self):
        assert classify_task("Build a class for database connections") == TaskCategory.CODE_GENERATION

    def test_code_generation_script(self):
        assert classify_task("Write a script to automate deployment") == TaskCategory.CODE_GENERATION

    def test_code_review(self):
        # "code review" must appear as a phrase to beat CODE_GENERATION
        assert classify_task("code review the implementation") == TaskCategory.CODE_REVIEW

    def test_code_review_pr(self):
        assert classify_task("Check this pull request for issues") == TaskCategory.CODE_REVIEW

    def test_debugging(self):
        assert classify_task("Fix the bug in the authentication module") == TaskCategory.DEBUGGING

    def test_debugging_error(self):
        assert classify_task("The error says NoneType has no attribute 'foo'") == TaskCategory.DEBUGGING

    def test_debugging_traceback(self):
        assert classify_task("Here's the traceback from the crash") == TaskCategory.DEBUGGING

    def test_debugging_failing(self):
        assert classify_task("The tests are failing") == TaskCategory.DEBUGGING

    def test_refactoring(self):
        assert classify_task("Refactor the user service to use dependency injection") == TaskCategory.REFACTORING

    def test_refactoring_simplify(self):
        # "Simplify" alone might not score high enough vs other categories
        assert classify_task("Refactor and simplify the payment module") == TaskCategory.REFACTORING

    def test_documentation(self):
        # Need a prompt that scores documentation higher than code_generation
        # "document" scores 1 for docs, "comment" scores 1 for docs = 2
        assert classify_task("Document and comment the API endpoints") == TaskCategory.DOCUMENTATION

    def test_documentation_readme(self):
        assert classify_task("Update the README with installation instructions") == TaskCategory.DOCUMENTATION

    def test_testing(self):
        # Use pytest to uniquely identify testing without triggering code_generation
        assert classify_task("Run pytest and add mocks for coverage") == TaskCategory.TESTING

    def test_testing_coverage(self):
        assert classify_task("Increase test coverage for auth module") == TaskCategory.TESTING

    def test_testing_pytest(self):
        assert classify_task("Add pytest fixtures for database tests") == TaskCategory.TESTING

    def test_reasoning(self):
        assert classify_task("Compare the trade-offs between REST and GraphQL") == TaskCategory.REASONING

    def test_creative(self):
        assert classify_task("Brainstorm ideas for the new dashboard design") == TaskCategory.CREATIVE

    def test_analysis(self):
        assert classify_task("Analyze the performance metrics from last month") == TaskCategory.ANALYSIS

    def test_vision_context(self):
        assert classify_task(
            "describe this", context={"has_image": True}
        ) == TaskCategory.VISION

    def test_vision_file_type(self):
        assert classify_task(
            "what is this", context={"file_type": "image/png"}
        ) == TaskCategory.VISION

    def test_embedding_context(self):
        assert classify_task(
            "process this", context={"embedding": True}
        ) == TaskCategory.EMBEDDING

    def test_vector_context(self):
        assert classify_task(
            "handle this data", context={"vector": True}
        ) == TaskCategory.EMBEDDING

    def test_swarm(self):
        assert classify_task("Run batch processing across multiple workers") == TaskCategory.SWARM

    def test_quick(self):
        # "Quick" alone might score on other categories too — "quick summary" is unique
        assert classify_task("Quick summary of the changes") == TaskCategory.QUICK

    def test_general_fallback(self):
        assert classify_task("hello world") == TaskCategory.GENERAL

    def test_case_insensitive(self):
        assert classify_task("WRITE A FUNCTION") == TaskCategory.CODE_GENERATION

    def test_context_none(self):
        assert classify_task("write code", context=None) == TaskCategory.CODE_GENERATION


# =========================================================================
# get_model_for_task
# =========================================================================


class TestGetModelForTask:
    def test_ollama_routing(self):
        model, category = get_model_for_task(
            "Write a Python function",
            DEFAULT_OLLAMA_ROUTING,
            "qwen2.5-coder:7b",
        )
        assert category == TaskCategory.CODE_GENERATION
        assert model == "qwen2.5-coder:7b"

    def test_zai_routing(self):
        model, category = get_model_for_task(
            "Compare REST vs GraphQL",
            DEFAULT_ZAI_ROUTING,
            "glm-4.5",
        )
        assert category == TaskCategory.REASONING
        assert model == "glm-5.1"

    def test_default_model_fallback(self):
        custom_routing: dict[TaskCategory, str] = {}
        model, category = get_model_for_task(
            "unknown prompt",
            custom_routing,
            "fallback-model",
        )
        assert model == "fallback-model"

    def test_zai_vision(self):
        model, category = get_model_for_task(
            "describe image",
            DEFAULT_ZAI_ROUTING,
            "glm-4.5",
            context={"has_image": True},
        )
        assert category == TaskCategory.VISION
        assert model == "GLM-4.5V"

    def test_returns_tuple(self):
        result = get_model_for_task("test this", DEFAULT_OLLAMA_ROUTING, "default")
        assert isinstance(result, tuple)
        assert len(result) == 2


# =========================================================================
# TASK_PATTERNS completeness
# =========================================================================


class TestTaskPatterns:
    def test_all_patterns_are_valid_regex(self):
        for category, patterns in TASK_PATTERNS.items():
            for pattern in patterns:
                # Should not raise
                re.compile(pattern)

    def test_patterns_non_empty(self):
        for category, patterns in TASK_PATTERNS.items():
            assert len(patterns) > 0, f"{category} has no patterns"

    def test_default_routing_covers_all_categories(self):
        for cat in TaskCategory:
            assert cat in DEFAULT_OLLAMA_ROUTING, f"Missing ollama routing for {cat}"
            assert cat in DEFAULT_ZAI_ROUTING, f"Missing zai routing for {cat}"


# =========================================================================
# JWTAuth
# =========================================================================


SECRET = "a" * 32  # minimum length


class TestJWTAuth:
    def test_secret_too_short(self):
        with pytest.raises(ValueError, match="32 characters"):
            JWTAuth(secret="short")

    def test_create_token(self):
        auth = JWTAuth(secret=SECRET)
        token = auth.create_token(user_id="user-1")
        assert isinstance(token, str)
        assert len(token) > 0

    def test_create_token_with_scopes(self):
        auth = JWTAuth(secret=SECRET)
        token = auth.create_token(user_id="user-1", scopes=["admin"])
        payload = auth.verify_token(token)
        assert payload["scopes"] == ["admin"]

    def test_create_token_default_scopes(self):
        auth = JWTAuth(secret=SECRET)
        token = auth.create_token(user_id="user-1")
        payload = auth.verify_token(token)
        assert payload["scopes"] == ["read", "execute"]

    def test_verify_token(self):
        auth = JWTAuth(secret=SECRET)
        token = auth.create_token(user_id="user-42")
        payload = auth.verify_token(token)
        assert payload["sub"] == "user-42"
        assert payload["user_id"] == "user-42"

    def test_verify_token_returns_token_payload(self):
        auth = JWTAuth(secret=SECRET)
        token = auth.create_token(user_id="u1")
        payload = auth.verify_token(token)
        assert isinstance(payload, TokenPayload)

    def test_token_payload_attribute_access(self):
        auth = JWTAuth(secret=SECRET)
        token = auth.create_token(user_id="u1", scopes=["admin"])
        payload = auth.verify_token(token)
        assert payload.user_id == "u1"
        assert payload.sub == "u1"
        assert payload.scopes == ["admin"]

    def test_token_payload_missing_attribute_raises(self):
        auth = JWTAuth(secret=SECRET)
        token = auth.create_token(user_id="u1")
        payload = auth.verify_token(token)
        with pytest.raises(AttributeError):
            _ = payload.nonexistent_key

    def test_verify_token_default_username(self):
        """Username is set from user_id if not in token."""
        auth = JWTAuth(secret=SECRET)
        token = auth.create_token(user_id="alice")
        payload = auth.verify_token(token)
        assert payload.get("username") == "alice"

    def test_invalid_signature(self):
        auth = JWTAuth(secret=SECRET)
        token = auth.create_token(user_id="u1")
        bad_auth = JWTAuth(secret="b" * 32)
        from mahavishnu.core.errors import AuthenticationError
        with pytest.raises(AuthenticationError, match="signature"):
            bad_auth.verify_token(token)

    def test_expired_token(self):
        auth = JWTAuth(secret=SECRET, expire_minutes=-1)
        token = auth.create_token(user_id="u1")
        from mahavishnu.core.errors import AuthenticationError
        with pytest.raises(AuthenticationError, match="expired"):
            auth.verify_token(token)

    def test_malformed_token(self):
        auth = JWTAuth(secret=SECRET)
        from mahavishnu.core.errors import AuthenticationError
        with pytest.raises(AuthenticationError, match="decode"):
            auth.verify_token("not-a-jwt")

    def test_create_access_token_basic(self):
        auth = JWTAuth(secret=SECRET)
        token = auth.create_access_token(claims={"sub": "u1"})
        payload = auth.verify_token(token)
        assert payload["sub"] == "u1"

    def test_create_access_token_with_user_id(self):
        auth = JWTAuth(secret=SECRET)
        token = auth.create_access_token(claims={"user_id": "u2"})
        payload = auth.verify_token(token)
        assert payload["user_id"] == "u2"

    def test_create_access_token_no_subject_raises(self):
        auth = JWTAuth(secret=SECRET)
        with pytest.raises(ValueError, match="sub.*user_id"):
            auth.create_access_token(claims={"role": "admin"})

    def test_create_access_token_extra_claims(self):
        auth = JWTAuth(secret=SECRET)
        token = auth.create_access_token(
            claims={"sub": "u1"},
            extra_claims={"department": "engineering"},
        )
        payload = auth.verify_token(token)
        # Known behavior: extra_claims gets nested as a single key in the JWT
        assert payload.get("extra_claims", {}).get("department") == "engineering"

    def test_create_access_token_preserves_scopes(self):
        auth = JWTAuth(secret=SECRET)
        token = auth.create_access_token(
            claims={"sub": "u1", "scopes": ["admin"]},
        )
        payload = auth.verify_token(token)
        assert payload["scopes"] == ["admin"]

    def test_create_token_extra_claims(self):
        auth = JWTAuth(secret=SECRET)
        token = auth.create_token(user_id="u1", team="backend")
        payload = auth.verify_token(token)
        assert payload["team"] == "backend"

    def test_custom_algorithm(self):
        auth = JWTAuth(secret=SECRET, algorithm="HS384")
        token = auth.create_token(user_id="u1")
        payload = auth.verify_token(token)
        assert payload["sub"] == "u1"

    def test_different_secrets_isolate(self):
        auth_a = JWTAuth(secret="a" * 32)
        auth_b = JWTAuth(secret="b" * 32)
        token_a = auth_a.create_token(user_id="shared-user")
        from mahavishnu.core.errors import AuthenticationError
        with pytest.raises(AuthenticationError):
            auth_b.verify_token(token_a)


# =========================================================================
# get_auth_from_config
# =========================================================================


class TestGetAuthFromConfig:
    def test_auth_disabled(self):
        config = MagicMock()
        config.auth = None
        assert get_auth_from_config(config) is None

    def test_auth_enabled_false(self):
        config = MagicMock()
        config.auth.enabled = False
        assert get_auth_from_config(config) is None

    def test_auth_enabled(self):
        config = MagicMock()
        config.auth.enabled = True
        with patch("mahavishnu.core.auth.MultiAuthHandler", return_value=MagicMock()) as mock_handler:
            handler = get_auth_from_config(config)
            assert handler is not None
            mock_handler.assert_called_once_with(config)

    def test_no_auth_attribute(self):
        config = MagicMock(spec=[])  # no .auth attribute
        assert get_auth_from_config(config) is None


# =========================================================================
# WorkflowState (local-memory path)
# =========================================================================


class TestWorkflowState:
    @pytest.fixture
    def ws(self):
        # Local-memory only (no OpenSearch)
        from mahavishnu.core.workflow_state import WorkflowState
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            state = WorkflowState(opensearch_client=None)
        return state

    async def test_create(self, ws):
        state = await ws.create("wf-1", {"task": "deploy"}, ["repo-a"])
        assert state["id"] == "wf-1"
        assert state["status"] == "pending"
        assert state["task"] == {"task": "deploy"}
        assert state["repos"] == ["repo-a"]
        assert state["progress"] == 0
        assert state["results"] == []

    async def test_get(self, ws):
        await ws.create("wf-2", {"task": "test"}, ["repo-b"])
        state = await ws.get("wf-2")
        assert state is not None
        assert state["id"] == "wf-2"

    async def test_get_missing(self, ws):
        assert await ws.get("nonexistent") is None

    async def test_update(self, ws):
        await ws.create("wf-3", {"task": "x"}, ["repo-a"])
        await ws.update("wf-3", status="running", progress=50)
        state = await ws.get("wf-3")
        assert state["status"] == "running"
        assert state["progress"] == 50
        assert "updated_at" in state

    async def test_update_missing(self, ws):
        # Should not raise
        await ws.update("nonexistent", status="running")

    async def test_delete(self, ws):
        await ws.create("wf-4", {"task": "y"}, ["repo-a"])
        await ws.delete("wf-4")
        assert await ws.get("wf-4") is None

    async def test_delete_missing(self, ws):
        # Should not raise
        await ws.delete("nonexistent")

    async def test_update_progress(self, ws):
        await ws.create("wf-5", {"task": "z"}, ["repo-a", "repo-b"])
        await ws.update_progress("wf-5", completed=1, total=2)
        state = await ws.get("wf-5")
        assert state["progress"] == 50

    async def test_update_progress_zero_total(self, ws):
        await ws.create("wf-5b", {"task": "z"}, ["repo-a"])
        await ws.update_progress("wf-5b", completed=1, total=0)
        state = await ws.get("wf-5b")
        assert state["progress"] == 0

    async def test_list_workflows(self, ws):
        await ws.create("wf-6", {"task": "a"}, ["repo-a"])
        await ws.create("wf-7", {"task": "b"}, ["repo-b"])
        workflows = await ws.list_workflows()
        assert len(workflows) == 2

    async def test_list_workflows_filter(self, ws):
        await ws.create("wf-8", {"task": "a"}, ["repo-a"])
        await ws.update("wf-8", status="completed")
        await ws.create("wf-9", {"task": "b"}, ["repo-b"])
        from mahavishnu.core.status import WorkflowStatus
        completed = await ws.list_workflows(status=WorkflowStatus.COMPLETED)
        assert len(completed) == 1

    async def test_list_workflows_limit(self, ws):
        for i in range(5):
            await ws.create(f"wf-limit-{i}", {"task": f"t{i}"}, [f"repo-{i}"])
        first_two = await ws.list_workflows(limit=2)
        assert len(first_two) == 2

    async def test_add_result(self, ws):
        await ws.create("wf-10", {"task": "build"}, ["repo-a"])
        await ws.add_result("wf-10", {"repo": "repo-a", "success": True})
        state = await ws.get("wf-10")
        assert len(state["results"]) == 1
        assert state["results"][0]["repo"] == "repo-a"

    async def test_add_error(self, ws):
        await ws.create("wf-11", {"task": "test"}, ["repo-a"])
        await ws.add_error("wf-11", {"repo": "repo-a", "error": "failed"})
        state = await ws.get("wf-11")
        assert len(state["errors"]) == 1

    async def test_get_completed_count(self, ws):
        await ws.create("wf-12", {"task": "deploy"}, ["repo-a", "repo-b"])
        await ws.add_result("wf-12", {"repo": "repo-a"})
        await ws.add_error("wf-12", {"repo": "repo-b"})
        count = await ws.get_completed_count("wf-12")
        assert count == 2

    async def test_get_completed_count_missing(self, ws):
        assert await ws.get_completed_count("nonexistent") == 0

    async def test_add_result_missing_workflow(self, ws):
        # Should not raise
        await ws.add_result("nonexistent", {"repo": "x"})

    async def test_add_error_missing_workflow(self, ws):
        # Should not raise
        await ws.add_error("nonexistent", {"error": "x"})

    async def test_deprecation_warning(self):
        from mahavishnu.core.workflow_state import WorkflowState
        with pytest.warns(DeprecationWarning, match="legacy"):
            WorkflowState(opensearch_client=None)

    async def test_opensearch_fallback_on_get(self):
        """When OpenSearch is configured but get fails, falls back to local."""
        from mahavishnu.core import workflow_state as ws_mod
        from mahavishnu.core.workflow_state import WorkflowState
        import warnings

        mock_os = AsyncMock()
        mock_os.index = AsyncMock()
        mock_os.get = AsyncMock(side_effect=Exception("OS down"))

        orig_available = ws_mod.OPENSEARCH_AVAILABLE
        ws_mod.OPENSEARCH_AVAILABLE = True

        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", DeprecationWarning)
                ws = WorkflowState(opensearch_client=mock_os)
                ws.local_states["wf-os-1"] = {
                    "id": "wf-os-1", "status": "pending",
                    "task": {"x": 1}, "repos": ["a"],
                    "results": [], "errors": [],
                }

            result = await ws.get("wf-os-1")
            assert result is not None
            assert result["id"] == "wf-os-1"
        finally:
            ws_mod.OPENSEARCH_AVAILABLE = orig_available

    async def test_opensearch_fallback_on_list(self):
        """When OpenSearch is configured but search fails, falls back to local."""
        from mahavishnu.core import workflow_state as ws_mod
        from mahavishnu.core.workflow_state import WorkflowState
        import warnings

        mock_os = AsyncMock()
        mock_os.index = AsyncMock()
        mock_os.search = AsyncMock(side_effect=Exception("OS down"))

        orig_available = ws_mod.OPENSEARCH_AVAILABLE
        ws_mod.OPENSEARCH_AVAILABLE = True

        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", DeprecationWarning)
                ws = WorkflowState(opensearch_client=mock_os)
                ws.local_states["wf-os-2"] = {
                    "id": "wf-os-2", "status": "pending",
                    "task": {"y": 1}, "repos": ["b"],
                    "results": [], "errors": [],
                }

            workflows = await ws.list_workflows()
            assert len(workflows) == 1
        finally:
            ws_mod.OPENSEARCH_AVAILABLE = orig_available

    async def test_opensearch_fallback_on_delete(self):
        """OpenSearch delete fails → falls back to local storage."""
        from mahavishnu.core.workflow_state import WorkflowState
        import warnings

        mock_os = AsyncMock()
        mock_os.index = AsyncMock()
        mock_os.delete = AsyncMock(side_effect=Exception("OS down"))

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            ws = WorkflowState(opensearch_client=mock_os)
            await ws.create("wf-os-3", {"task": "z"}, ["repo-c"])
            await ws.delete("wf-os-3")

        assert await ws.get("wf-os-3") is None

    async def test_opensearch_create_stores_remotely(self):
        """With OS client, create() calls opensearch.index()."""
        from mahavishnu.core.workflow_state import WorkflowState, OPENSEARCH_AVAILABLE
        import warnings

        if not OPENSEARCH_AVAILABLE:
            pytest.skip("OpenSearch not installed")

        mock_os = AsyncMock()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            ws = WorkflowState(opensearch_client=mock_os)
            await ws.create("wf-os-4", {"task": "remote"}, ["repo-d"])

        mock_os.index.assert_called_once()
        call_args = mock_os.index.call_args
        assert call_args.kwargs["id"] == "wf-os-4"

    async def test_opensearch_update_stores_remotely(self):
        from mahavishnu.core.workflow_state import WorkflowState, OPENSEARCH_AVAILABLE
        import warnings

        if not OPENSEARCH_AVAILABLE:
            pytest.skip("OpenSearch not installed")

        mock_os = AsyncMock()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            ws = WorkflowState(opensearch_client=mock_os)
            await ws.update("wf-os-5", status="running")

        mock_os.update.assert_called_once()
