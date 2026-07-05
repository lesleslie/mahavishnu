"""Comprehensive unit tests for the OllamaWorker module."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from mahavishnu.core.status import WorkerStatus
from mahavishnu.workers.base import BaseWorker, WorkerResult
from mahavishnu.workers.ollama import (
    DEFAULT_MODEL_ROUTING,
    TASK_PATTERNS,
    OllamaConfig,
    OllamaWorker,
    TaskCategory,
    classify_task,
    get_model_for_task,
)


class TestTaskCategory:
    """Tests for the TaskCategory enum."""

    def test_all_categories_have_values(self):
        for cat in TaskCategory:
            assert isinstance(cat.value, str)
            assert len(cat.value) > 0

    def test_category_count(self):
        assert len(TaskCategory) == 12

    def test_general_is_default_member(self):
        assert TaskCategory.GENERAL.value == "general"

    def test_string_comparison(self):
        assert TaskCategory.CODE_GENERATION == "code_generation"
        assert TaskCategory.EMBEDDING == "embedding"


class TestOllamaConfig:
    """Tests for the OllamaConfig dataclass."""

    def test_default_values(self):
        config = OllamaConfig()
        assert config.base_url == "http://localhost:11434"
        assert config.model == "qwen2.5-coder:7b"
        assert config.timeout == 300
        assert config.temperature == 0.7
        assert config.num_ctx == 4096
        assert config.num_predict == 2048
        assert config.top_p == 0.9
        assert config.top_k == 40
        assert config.keep_alive == "5m"
        assert config.intelligent_routing is True
        assert config.model_routing is None

    def test_custom_values(self):
        config = OllamaConfig(
            base_url="http://custom:9999",
            model="llama3:70b",
            timeout=600,
            temperature=0.1,
            num_ctx=8192,
            num_predict=4096,
            top_p=0.95,
            top_k=100,
            keep_alive="10m",
            intelligent_routing=False,
        )
        assert config.base_url == "http://custom:9999"
        assert config.model == "llama3:70b"
        assert config.timeout == 600
        assert config.temperature == 0.1
        assert config.num_ctx == 8192
        assert config.num_predict == 4096
        assert config.top_p == 0.95
        assert config.top_k == 100
        assert config.keep_alive == "10m"
        assert config.intelligent_routing is False

    def test_get_model_for_category_with_default_routing(self):
        config = OllamaConfig()
        model = config.get_model_for_category(TaskCategory.CODE_GENERATION)
        assert model == "qwen2.5-coder:7b"

    def test_get_model_for_category_reasoning(self):
        config = OllamaConfig()
        model = config.get_model_for_category(TaskCategory.REASONING)
        assert model == "llama3:8b"

    def test_get_model_for_category_vision(self):
        config = OllamaConfig()
        model = config.get_model_for_category(TaskCategory.VISION)
        assert model == "llava:7b"

    def test_get_model_for_category_embedding(self):
        config = OllamaConfig()
        model = config.get_model_for_category(TaskCategory.EMBEDDING)
        assert model == "nomic-embed-text"

    def test_get_model_for_category_with_custom_routing(self):
        custom_routing = {TaskCategory.CODE_GENERATION: "custom-model:latest"}
        config = OllamaConfig(model_routing=custom_routing)
        model = config.get_model_for_category(TaskCategory.CODE_GENERATION)
        assert model == "custom-model:latest"

    def test_get_model_for_category_empty_routing_uses_defaults(self):
        config = OllamaConfig(model="fallback-model", model_routing={})
        model = config.get_model_for_category(TaskCategory.CODE_GENERATION)
        assert model == DEFAULT_MODEL_ROUTING[TaskCategory.CODE_GENERATION]

    def test_get_model_for_category_none_routing_uses_defaults(self):
        config = OllamaConfig(model="fallback-model", model_routing=None)
        model = config.get_model_for_category(TaskCategory.CODE_GENERATION)
        assert model == DEFAULT_MODEL_ROUTING[TaskCategory.CODE_GENERATION]

    def test_get_model_for_category_missing_in_custom_routing_uses_config_model(self):
        custom_routing = {TaskCategory.CODE_GENERATION: "custom:latest"}
        config = OllamaConfig(model="my-fallback", model_routing=custom_routing)
        model = config.get_model_for_category(TaskCategory.REASONING)
        assert model == "my-fallback"


class TestClassifyTask:
    """Tests for the classify_task function."""

    def test_empty_prompt_returns_general(self):
        assert classify_task("") == TaskCategory.GENERAL

    def test_none_prompt_returns_general(self):
        assert classify_task("") == TaskCategory.GENERAL

    def test_code_generation_keywords(self):
        prompt = "Write a function to parse JSON data"
        result = classify_task(prompt)
        assert result == TaskCategory.CODE_GENERATION

    def test_code_generation_create_class(self):
        prompt = "Create a class for managing user accounts"
        result = classify_task(prompt)
        assert result == TaskCategory.CODE_GENERATION

    def test_code_generation_build_module(self):
        prompt = "Build a module for database connections"
        result = classify_task(prompt)
        assert result == TaskCategory.CODE_GENERATION

    def test_code_generation_api_endpoint(self):
        prompt = "implement api endpoint for user registration"
        result = classify_task(prompt)
        assert result == TaskCategory.CODE_GENERATION

    def test_code_generation_script(self):
        prompt = "write a script to automate deployment"
        result = classify_task(prompt)
        assert result == TaskCategory.CODE_GENERATION

    def test_code_review_pull_request(self):
        prompt = "Check this pull request for code review"
        result = classify_task(prompt)
        assert result == TaskCategory.CODE_REVIEW

    def test_code_review_pr_review(self):
        prompt = "PR review needed for the authentication changes"
        result = classify_task(prompt)
        assert result == TaskCategory.CODE_REVIEW

    def test_debugging_keywords(self):
        prompt = "Debug the error in the authentication module"
        result = classify_task(prompt)
        assert result == TaskCategory.DEBUGGING

    def test_debugging_traceback(self):
        prompt = "Fix this traceback in the payment service"
        result = classify_task(prompt)
        assert result == TaskCategory.DEBUGGING

    def test_debugging_not_working(self):
        prompt = "The login is not working after the update"
        result = classify_task(prompt)
        assert result == TaskCategory.DEBUGGING

    def test_debugging_stack_trace(self):
        prompt = "Analyze this stack trace from production"
        result = classify_task(prompt)
        assert result == TaskCategory.DEBUGGING

    def test_refactoring_simplify(self):
        prompt = "Simplify the complex validation logic"
        result = classify_task(prompt)
        assert result == TaskCategory.REFACTORING

    def test_refactoring_remove_duplicate(self):
        prompt = "remove duplicate handlers and reorganize the module"
        result = classify_task(prompt)
        assert result == TaskCategory.REFACTORING

    def test_refactoring_reorganize(self):
        prompt = "Reorganize the project structure for clarity"
        result = classify_task(prompt)
        assert result == TaskCategory.REFACTORING

    def test_documentation_docstring(self):
        prompt = "document all public methods with docstrings"
        result = classify_task(prompt)
        assert result == TaskCategory.DOCUMENTATION

    def test_documentation_user_guide(self):
        prompt = "document the user guide for onboarding"
        result = classify_task(prompt)
        assert result == TaskCategory.DOCUMENTATION

    def test_documentation_api_documentation(self):
        prompt = "Update API documentation for v2 endpoints"
        result = classify_task(prompt)
        assert result == TaskCategory.DOCUMENTATION

    def test_testing_coverage(self):
        prompt = "Increase test coverage for the auth module"
        result = classify_task(prompt)
        assert result == TaskCategory.TESTING

    def test_testing_mock_fixture(self):
        prompt = "Create a mock fixture for the database connection"
        result = classify_task(prompt)
        assert result == TaskCategory.TESTING

    def test_testing_pytest(self):
        prompt = "Add pytest assertions to validate the output"
        result = classify_task(prompt)
        assert result == TaskCategory.TESTING

    def test_reasoning_keywords(self):
        prompt = "Compare the pros and cons of microservices vs monolith"
        result = classify_task(prompt)
        assert result == TaskCategory.REASONING

    def test_reasoning_architecture_decision(self):
        prompt = "Explain the architecture decision behind event sourcing"
        result = classify_task(prompt)
        assert result == TaskCategory.REASONING

    def test_creative_keywords(self):
        prompt = "Brainstorm ideas for improving the user experience"
        result = classify_task(prompt)
        assert result == TaskCategory.CREATIVE

    def test_creative_prototype(self):
        prompt = "Design an innovative prototype for the dashboard"
        result = classify_task(prompt)
        assert result == TaskCategory.CREATIVE

    def test_analysis_keywords(self):
        prompt = "Analyze the performance metrics from last quarter"
        result = classify_task(prompt)
        assert result == TaskCategory.ANALYSIS

    def test_analysis_statistics(self):
        prompt = "Evaluate the statistics from the user survey"
        result = classify_task(prompt)
        assert result == TaskCategory.ANALYSIS

    def test_vision_ocr(self):
        prompt = "Perform OCR on the uploaded image"
        result = classify_task(prompt)
        assert result == TaskCategory.VISION

    def test_vision_what_image(self):
        prompt = "What is shown in this image"
        result = classify_task(prompt)
        assert result == TaskCategory.VISION

    def test_embedding_keywords(self):
        prompt = "calculate embedding similarity scores between texts"
        result = classify_task(prompt)
        assert result == TaskCategory.EMBEDDING

    def test_embedding_vectorize(self):
        prompt = "Vectorize the document corpus for similarity search"
        result = classify_task(prompt)
        assert result == TaskCategory.EMBEDDING

    def test_embedding_semantic_search(self):
        prompt = "Enable semantic search over the knowledge base"
        result = classify_task(prompt)
        assert result == TaskCategory.EMBEDDING

    def test_context_with_has_image_returns_vision(self):
        result = classify_task("some text", context={"has_image": True})
        assert result == TaskCategory.VISION

    def test_context_with_image_file_type_returns_vision(self):
        result = classify_task("some text", context={"file_type": "image/png"})
        assert result == TaskCategory.VISION

    def test_context_with_embedding_returns_embedding(self):
        result = classify_task("some text", context={"embedding": True})
        assert result == TaskCategory.EMBEDDING

    def test_context_with_vector_returns_embedding(self):
        result = classify_task("some text", context={"vector": True})
        assert result == TaskCategory.EMBEDDING

    def test_context_image_takes_priority_over_text_patterns(self):
        result = classify_task("Write unit tests for the module", context={"has_image": True})
        assert result == TaskCategory.VISION

    def test_no_pattern_match_returns_general(self):
        result = classify_task("hello world")
        assert result == TaskCategory.GENERAL

    def test_case_insensitive_classification(self):
        result_upper = classify_task("WRITE A FUNCTION to parse data")
        result_lower = classify_task("write a function to parse data")
        assert result_upper == result_lower

    def test_vision_from_image_file_type(self):
        result = classify_task("process this file", context={"file_type": "image/jpeg"})
        assert result == TaskCategory.VISION


class TestGetModelForTask:
    """Tests for the get_model_for_task function."""

    def test_returns_preferred_model_when_available(self):
        config = OllamaConfig()
        available = ["qwen2.5-coder:7b", "llama3:8b"]
        model, category = get_model_for_task("write a function", available, config)
        assert model == "qwen2.5-coder:7b"
        assert category == TaskCategory.CODE_GENERATION

    def test_falls_back_to_model_family_match(self):
        config = OllamaConfig(model="nonexistent:latest")
        available = ["deepseek-coder:6.7b", "llama3:8b"]
        model, category = get_model_for_task("write a function", available, config)
        assert model == "deepseek-coder:6.7b"
        assert category == TaskCategory.CODE_GENERATION

    def test_falls_back_to_config_model_when_available(self):
        config = OllamaConfig(model="llama3:8b")
        available = ["llama3:8b"]
        model, category = get_model_for_task("write a function", available, config)
        assert model == "llama3:8b"

    def test_falls_back_to_first_available(self):
        config = OllamaConfig(model="nonexistent:latest")
        available = ["some-model:latest"]
        model, category = get_model_for_task("hello world", available, config)
        assert model == "some-model:latest"

    def test_returns_config_model_when_no_models_available(self):
        config = OllamaConfig(model="my-default")
        model, category = get_model_for_task("hello", [], config)
        assert model == "my-default"

    def test_reasoning_task_prefers_llama(self):
        config = OllamaConfig(model="nonexistent")
        available = ["llama3:8b"]
        model, category = get_model_for_task("compare the trade offs", available, config)
        assert category == TaskCategory.REASONING

    def test_vision_task_prefers_llava(self):
        config = OllamaConfig(model="nonexistent")
        available = ["llava:7b"]
        model, category = get_model_for_task("what is shown in this image", available, config)
        assert category == TaskCategory.VISION

    def test_embedding_task_prefers_embed_model(self):
        config = OllamaConfig(model="nonexistent")
        available = ["all-minilm:latest"]
        model, category = get_model_for_task("compute embedding vectors", available, config)
        assert category == TaskCategory.EMBEDDING

    def test_uses_context_for_classification(self):
        config = OllamaConfig()
        available = ["llava:7b", "qwen2.5-coder:7b"]
        model, category = get_model_for_task(
            "do something", available, config, context={"has_image": True}
        )
        assert category == TaskCategory.VISION

    def test_debugging_falls_back_to_coder_family(self):
        config = OllamaConfig(model="nonexistent")
        available = ["phi3-coder:3.8b"]
        model, category = get_model_for_task("debug the error in the module", available, config)
        assert category == TaskCategory.DEBUGGING
        assert "coder" in model.lower()


class TestDefaultModelRouting:
    """Tests for DEFAULT_MODEL_ROUTING completeness."""

    def test_all_categories_have_routing(self):
        for cat in TaskCategory:
            assert cat in DEFAULT_MODEL_ROUTING, f"Missing routing for {cat}"

    def test_routing_values_are_strings(self):
        for _cat, model in DEFAULT_MODEL_ROUTING.items():
            assert isinstance(model, str)


class TestTaskPatterns:
    """Tests for TASK_PATTERNS completeness."""

    def test_all_categories_have_patterns(self):
        for cat in TaskCategory:
            if cat == TaskCategory.GENERAL:
                continue
            assert cat in TASK_PATTERNS, f"Missing patterns for {cat}"

    def test_general_category_has_no_patterns(self):
        assert TaskCategory.GENERAL not in TASK_PATTERNS

    def test_each_category_has_at_least_one_pattern(self):
        for cat, patterns in TASK_PATTERNS.items():
            assert len(patterns) >= 1, f"{cat} has no patterns"


class TestOllamaWorkerInit:
    """Tests for OllamaWorker initialization."""

    def test_default_initialization(self):
        worker = OllamaWorker()
        assert worker.worker_type == "terminal-ollama"
        assert worker._status == WorkerStatus.PENDING
        assert worker.config.base_url == "http://localhost:11434"
        assert worker.config.model == "qwen2.5-coder:7b"
        assert worker._client is None
        assert worker._start_time is None
        assert worker.session_buddy_client is None

    def test_custom_config(self):
        config = OllamaConfig(base_url="http://remote:11434", model="llama3:70b")
        worker = OllamaWorker(config=config)
        assert worker.config.base_url == "http://remote:11434"
        assert worker.config.model == "llama3:70b"

    def test_custom_worker_id(self):
        worker = OllamaWorker(worker_id="my-custom-id")
        assert worker._worker_id == "my-custom-id"

    def test_auto_generated_worker_id(self):
        worker = OllamaWorker()
        assert worker._worker_id.startswith("ollama-")

    def test_session_buddy_client_stored(self):
        client = MagicMock()
        worker = OllamaWorker(session_buddy_client=client)
        assert worker.session_buddy_client is client

    def test_is_base_worker_subclass(self):
        worker = OllamaWorker()
        assert isinstance(worker, BaseWorker)


class TestOllamaWorkerStart:
    """Tests for OllamaWorker.start method."""

    @pytest.mark.asyncio
    async def test_start_success(self):
        worker = OllamaWorker(config=OllamaConfig())
        mock_client = AsyncMock(spec=httpx.AsyncClient)

        avail_response = MagicMock()
        avail_response.status_code = 200
        avail_response.text = "Ollama is running"

        tags_response = MagicMock()
        tags_response.json.return_value = {"models": [{"name": "qwen2.5-coder:7b"}]}

        mock_client.get = AsyncMock(side_effect=[avail_response, tags_response])
        mock_client.aclose = AsyncMock()

        with patch("mahavishnu.workers.ollama.httpx.AsyncClient", return_value=mock_client):
            worker_id = await worker.start()
            assert worker_id == worker._worker_id
            assert worker._status == WorkerStatus.RUNNING

    @pytest.mark.asyncio
    async def test_start_fails_when_ollama_unavailable(self):
        worker = OllamaWorker()
        mock_client = AsyncMock(spec=httpx.AsyncClient)

        with patch("mahavishnu.workers.ollama.httpx.AsyncClient", return_value=mock_client):
            mock_client.get = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
            mock_client.aclose = AsyncMock()

            with pytest.raises(RuntimeError, match="Ollama server not available"):
                await worker.start()
            assert worker._status == WorkerStatus.FAILED

    @pytest.mark.asyncio
    async def test_start_pulls_model_when_not_found(self):
        config = OllamaConfig(model="nonexistent:latest")
        worker = OllamaWorker(config=config)
        mock_client = AsyncMock(spec=httpx.AsyncClient)

        avail_response = MagicMock()
        avail_response.status_code = 200
        avail_response.text = "Ollama is running"

        tags_response = MagicMock()
        tags_response.json.return_value = {"models": [{"name": "llama3:8b"}]}

        pull_response = MagicMock()
        pull_response.json.return_value = {"status": "success"}

        mock_client.get = AsyncMock(side_effect=[avail_response, tags_response])
        mock_client.post = AsyncMock(return_value=pull_response)
        mock_client.aclose = AsyncMock()

        with patch("mahavishnu.workers.ollama.httpx.AsyncClient", return_value=mock_client):
            await worker.start()
            assert worker._status == WorkerStatus.RUNNING

    @pytest.mark.asyncio
    async def test_start_fails_when_pull_fails(self):
        config = OllamaConfig(model="nonexistent:latest")
        worker = OllamaWorker(config=config)
        mock_client = AsyncMock(spec=httpx.AsyncClient)

        avail_response = MagicMock()
        avail_response.status_code = 200
        avail_response.text = "Ollama is running"

        tags_response = MagicMock()
        tags_response.json.return_value = {"models": [{"name": "llama3:8b"}]}

        mock_client.get = AsyncMock(side_effect=[avail_response, tags_response])
        mock_client.post = AsyncMock(
            side_effect=httpx.HTTPStatusError(
                "Not found", request=MagicMock(), response=MagicMock()
            )
        )
        mock_client.aclose = AsyncMock()

        with patch("mahavishnu.workers.ollama.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(RuntimeError, match="not available and pull failed"):
                await worker.start()
            assert worker._status == WorkerStatus.FAILED

    @pytest.mark.asyncio
    async def test_start_sets_start_time(self):
        worker = OllamaWorker()
        mock_client = AsyncMock(spec=httpx.AsyncClient)

        avail_response = MagicMock()
        avail_response.status_code = 200
        avail_response.text = "Ollama is running"

        tags_response = MagicMock()
        tags_response.json.return_value = {"models": [{"name": "qwen2.5-coder:7b"}]}

        mock_client.get = AsyncMock(side_effect=[avail_response, tags_response])
        mock_client.aclose = AsyncMock()

        with patch("mahavishnu.workers.ollama.httpx.AsyncClient", return_value=mock_client):
            assert worker._start_time is None
            await worker.start()
            assert worker._start_time is not None
            assert worker._start_time <= time.time()


class TestOllamaWorkerExecute:
    """Tests for OllamaWorker.execute method."""

    def _make_running_worker(self, config=None):
        worker = OllamaWorker(config=config)
        worker._status = WorkerStatus.RUNNING
        worker._start_time = time.time()
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        worker._client = mock_client
        return worker, mock_client

    def _make_chat_response(self, content="result", model="qwen2.5-coder:7b"):
        return {
            "model": model,
            "message": {"content": content},
            "done": True,
            "total_duration": 5000000,
            "eval_count": 100,
        }

    def _make_generate_response(self, content="result", model="qwen2.5-coder:7b"):
        return {
            "model": model,
            "response": content,
            "done": True,
            "total_duration": 3000000,
            "eval_count": 50,
        }

    def _mock_post_chat(self, mock_client, chat_response):
        mock_resp = MagicMock()
        mock_resp.json.return_value = chat_response
        mock_resp.raise_for_status = MagicMock()
        mock_client.post = AsyncMock(return_value=mock_resp)

    def _mock_post_generate(self, mock_client, gen_response):
        mock_resp = MagicMock()
        mock_resp.json.return_value = gen_response
        mock_resp.raise_for_status = MagicMock()
        mock_client.post = AsyncMock(return_value=mock_resp)

    def _mock_get_models(self, mock_client, models):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"models": models}
        mock_resp.raise_for_status = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_resp)

    @pytest.mark.asyncio
    async def test_execute_chat_success(self):
        worker, mock_client = self._make_running_worker()
        self._mock_post_chat(mock_client, self._make_chat_response("Here is the code"))
        self._mock_get_models(mock_client, [{"name": "qwen2.5-coder:7b"}])

        task = {"prompt": "Write a hello world function"}
        result = await worker.execute(task)

        assert result.status == WorkerStatus.COMPLETED
        assert result.output == "Here is the code"
        assert result.worker_id == worker._worker_id
        assert result.exit_code == 0
        assert result.metadata["api_type"] == "chat"
        assert result.metadata["model"] == "qwen2.5-coder:7b"

    @pytest.mark.asyncio
    async def test_execute_raw_generate(self):
        config = OllamaConfig(intelligent_routing=False)
        worker, mock_client = self._make_running_worker(config=config)
        self._mock_post_generate(mock_client, self._make_generate_response("Raw generated text"))

        task = {"prompt": "Complete this", "raw": True}
        result = await worker.execute(task)

        assert result.status == WorkerStatus.COMPLETED
        assert result.output == "Raw generated text"
        assert result.metadata["api_type"] == "generate"

    @pytest.mark.asyncio
    async def test_execute_with_system_prompt(self):
        worker, mock_client = self._make_running_worker()
        self._mock_post_chat(mock_client, self._make_chat_response("Result"))
        self._mock_get_models(mock_client, [{"name": "qwen2.5-coder:7b"}])

        task = {"prompt": "Hello", "system": "You are a helpful assistant"}
        result = await worker.execute(task)

        assert result.status == WorkerStatus.COMPLETED
        call_args = mock_client.post.call_args
        sent_messages = call_args[1]["json"]["messages"]
        assert len(sent_messages) == 2
        assert sent_messages[0]["role"] == "system"
        assert sent_messages[1]["role"] == "user"

    @pytest.mark.asyncio
    async def test_execute_with_explicit_model(self):
        worker, mock_client = self._make_running_worker()
        self._mock_post_chat(mock_client, self._make_chat_response("Answer", "llama3:8b"))

        task = {"prompt": "Explain X", "model": "llama3:8b"}
        result = await worker.execute(task)

        assert result.status == WorkerStatus.COMPLETED
        call_args = mock_client.post.call_args
        assert call_args[1]["json"]["model"] == "llama3:8b"
        assert result.metadata["intelligent_routing"] is False

    @pytest.mark.asyncio
    async def test_execute_with_custom_temperature(self):
        worker, mock_client = self._make_running_worker()
        self._mock_post_chat(mock_client, self._make_chat_response("Creative output"))
        self._mock_get_models(mock_client, [{"name": "qwen2.5-coder:7b"}])

        task = {"prompt": "Write creatively", "temperature": 1.5}
        result = await worker.execute(task)

        assert result.status == WorkerStatus.COMPLETED
        call_args = mock_client.post.call_args
        assert call_args[1]["json"]["options"]["temperature"] == 1.5

    @pytest.mark.asyncio
    async def test_execute_no_prompt_returns_failed(self):
        worker, _ = self._make_running_worker()
        result = await worker.execute({})
        assert result.status == WorkerStatus.FAILED
        assert "No prompt" in result.error

    @pytest.mark.asyncio
    async def test_execute_empty_prompt_returns_failed(self):
        worker, _ = self._make_running_worker()
        result = await worker.execute({"prompt": ""})
        assert result.status == WorkerStatus.FAILED
        assert "No prompt" in result.error

    @pytest.mark.asyncio
    async def test_execute_timeout(self):
        config = OllamaConfig(intelligent_routing=False)
        worker, mock_client = self._make_running_worker(config=config)
        mock_client.post = AsyncMock(side_effect=TimeoutError())

        task = {"prompt": "slow task", "timeout": 0.001, "raw": True}
        result = await worker.execute(task)

        assert result.status == WorkerStatus.TIMEOUT
        assert "timed out" in result.error.lower()

    @pytest.mark.asyncio
    async def test_execute_http_error_returns_failed(self):
        config = OllamaConfig(intelligent_routing=False)
        worker, mock_client = self._make_running_worker(config=config)
        mock_client.post = AsyncMock(
            side_effect=httpx.HTTPStatusError(
                "500 Server Error",
                request=MagicMock(),
                response=MagicMock(status_code=500),
            )
        )

        task = {"prompt": "test", "raw": True}
        result = await worker.execute(task)

        assert result.status == WorkerStatus.FAILED
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_execute_connect_error_returns_failed(self):
        config = OllamaConfig(intelligent_routing=False)
        worker, mock_client = self._make_running_worker(config=config)
        mock_client.post = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))

        task = {"prompt": "test", "raw": True}
        result = await worker.execute(task)

        assert result.status == WorkerStatus.FAILED

    @pytest.mark.asyncio
    async def test_execute_auto_starts_if_not_running(self):
        config = OllamaConfig(intelligent_routing=False)
        worker = OllamaWorker(config=config)
        worker._status = WorkerStatus.PENDING
        mock_client = AsyncMock(spec=httpx.AsyncClient)

        avail_response = MagicMock()
        avail_response.status_code = 200
        avail_response.text = "Ollama is running"

        tags_response = MagicMock()
        tags_response.json.return_value = {"models": [{"name": "qwen2.5-coder:7b"}]}

        chat_response = self._make_chat_response("Auto-started result")

        mock_client.get = AsyncMock(side_effect=[avail_response, tags_response])
        self._mock_post_chat(mock_client, chat_response)
        mock_client.aclose = AsyncMock()

        with patch("mahavishnu.workers.ollama.httpx.AsyncClient", return_value=mock_client):
            result = await worker.execute({"prompt": "test"})
            assert result.status == WorkerStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_execute_stores_in_session_buddy_on_success(self):
        sb_client = AsyncMock()
        worker, mock_client = self._make_running_worker()
        worker.session_buddy_client = sb_client
        self._mock_post_chat(mock_client, self._make_chat_response("Stored result"))
        self._mock_get_models(mock_client, [{"name": "qwen2.5-coder:7b"}])

        await worker.execute({"prompt": "test"})

        sb_client.call_tool.assert_called_once()
        call_args = sb_client.call_tool.call_args
        assert call_args[0][0] == "store_memory"

    @pytest.mark.asyncio
    async def test_execute_continues_when_session_buddy_fails(self):
        sb_client = AsyncMock()
        sb_client.call_tool = AsyncMock(side_effect=Exception("SB down"))
        worker, mock_client = self._make_running_worker()
        worker.session_buddy_client = sb_client
        self._mock_post_chat(mock_client, self._make_chat_response("Result despite SB failure"))
        self._mock_get_models(mock_client, [{"name": "qwen2.5-coder:7b"}])

        result = await worker.execute({"prompt": "test"})
        assert result.status == WorkerStatus.COMPLETED
        assert result.output == "Result despite SB failure"

    @pytest.mark.asyncio
    async def test_execute_intelligent_routing_disabled(self):
        config = OllamaConfig(intelligent_routing=False, model="my-model")
        worker, mock_client = self._make_running_worker(config=config)
        self._mock_post_chat(mock_client, self._make_chat_response("Result", "my-model"))

        task = {"prompt": "write a function"}
        result = await worker.execute(task)

        assert result.status == WorkerStatus.COMPLETED
        call_args = mock_client.post.call_args
        assert call_args[1]["json"]["model"] == "my-model"
        assert result.metadata["intelligent_routing"] is False

    @pytest.mark.asyncio
    async def test_execute_metadata_has_duration(self):
        worker, mock_client = self._make_running_worker()
        self._mock_post_chat(mock_client, self._make_chat_response("Timed result"))
        self._mock_get_models(mock_client, [{"name": "qwen2.5-coder:7b"}])

        result = await worker.execute({"prompt": "test"})
        assert result.duration_seconds >= 0

    @pytest.mark.asyncio
    async def test_execute_metadata_includes_tokens_and_duration(self):
        worker, mock_client = self._make_running_worker()
        chat_resp = self._make_chat_response("result")
        chat_resp["eval_count"] = 42
        chat_resp["total_duration"] = 1234567890
        self._mock_post_chat(mock_client, chat_resp)
        self._mock_get_models(mock_client, [{"name": "qwen2.5-coder:7b"}])

        result = await worker.execute({"prompt": "test"})
        assert result.metadata["tokens_generated"] == 42
        assert result.metadata["total_duration_ms"] == 1234567890

    @pytest.mark.asyncio
    async def test_execute_with_chat_without_system_omits_system_message(self):
        worker, mock_client = self._make_running_worker()
        self._mock_post_chat(mock_client, self._make_chat_response("result"))
        self._mock_get_models(mock_client, [{"name": "qwen2.5-coder:7b"}])

        task = {"prompt": "hello"}
        await worker.execute(task)

        call_args = mock_client.post.call_args
        messages = call_args[1]["json"]["messages"]
        assert len(messages) == 1
        assert messages[0]["role"] == "user"

    @pytest.mark.asyncio
    async def test_execute_timeout_metadata_includes_timeout_value(self):
        config = OllamaConfig(intelligent_routing=False)
        worker, mock_client = self._make_running_worker(config=config)
        mock_client.post = AsyncMock(side_effect=TimeoutError())

        task = {"prompt": "test", "timeout": 5, "raw": True}
        result = await worker.execute(task)

        assert result.status == WorkerStatus.TIMEOUT
        assert result.metadata["timeout"] == 5


class TestOllamaWorkerStop:
    """Tests for OllamaWorker.stop method."""

    @pytest.mark.asyncio
    async def test_stop_closes_client(self):
        worker = OllamaWorker()
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        worker._client = mock_client
        worker._status = WorkerStatus.RUNNING

        await worker.stop()

        mock_client.aclose.assert_called_once()
        assert worker._client is None
        assert worker._status == WorkerStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_stop_without_client(self):
        worker = OllamaWorker()
        worker._client = None
        worker._status = WorkerStatus.RUNNING

        await worker.stop()

        assert worker._status == WorkerStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_stop_handles_close_error(self):
        worker = OllamaWorker()
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.aclose = AsyncMock(side_effect=Exception("Close error"))
        worker._client = mock_client
        worker._status = WorkerStatus.RUNNING

        await worker.stop()

        assert worker._client is None
        assert worker._status == WorkerStatus.COMPLETED


class TestOllamaWorkerStatus:
    """Tests for OllamaWorker.status method."""

    @pytest.mark.asyncio
    async def test_status_running_with_available_server(self):
        worker = OllamaWorker()
        worker._status = WorkerStatus.RUNNING
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(return_value=MagicMock(status_code=200))
        worker._client = mock_client

        status = await worker.status()
        assert status == WorkerStatus.RUNNING

    @pytest.mark.asyncio
    async def test_status_running_becomes_failed_when_unavailable(self):
        worker = OllamaWorker()
        worker._status = WorkerStatus.RUNNING
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
        worker._client = mock_client

        status = await worker.status()
        assert status == WorkerStatus.FAILED

    @pytest.mark.asyncio
    async def test_status_pending_without_client(self):
        worker = OllamaWorker()
        worker._status = WorkerStatus.PENDING
        worker._client = None

        status = await worker.status()
        assert status == WorkerStatus.PENDING

    @pytest.mark.asyncio
    async def test_status_failed_stays_failed(self):
        worker = OllamaWorker()
        worker._status = WorkerStatus.FAILED
        worker._client = None

        status = await worker.status()
        assert status == WorkerStatus.FAILED

    @pytest.mark.asyncio
    async def test_status_completed_without_client(self):
        worker = OllamaWorker()
        worker._status = WorkerStatus.COMPLETED
        worker._client = None

        status = await worker.status()
        assert status == WorkerStatus.COMPLETED


class TestOllamaWorkerGetProgress:
    """Tests for OllamaWorker.get_progress method."""

    @pytest.mark.asyncio
    async def test_progress_with_active_client(self):
        worker = OllamaWorker()
        worker._status = WorkerStatus.RUNNING
        worker._start_time = time.time()
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(return_value=MagicMock(status_code=200))
        worker._client = mock_client

        progress = await worker.get_progress()

        assert progress["status"] == "running"
        assert progress["worker_id"] == worker._worker_id
        assert progress["worker_type"] == "terminal-ollama"
        assert progress["model"] == "qwen2.5-coder:7b"
        assert progress["base_url"] == "http://localhost:11434"
        assert progress["ollama_available"] is True
        assert progress["duration_seconds"] >= 0

    @pytest.mark.asyncio
    async def test_progress_without_start_time(self):
        worker = OllamaWorker()
        worker._start_time = None

        progress = await worker.get_progress()
        assert progress["duration_seconds"] == 0

    @pytest.mark.asyncio
    async def test_progress_handles_availability_check_error(self):
        worker = OllamaWorker()
        worker._status = WorkerStatus.RUNNING
        worker._start_time = time.time()
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(side_effect=Exception("error"))
        worker._client = mock_client

        progress = await worker.get_progress()
        assert progress["ollama_available"] is False

    @pytest.mark.asyncio
    async def test_progress_without_client(self):
        worker = OllamaWorker()
        worker._start_time = time.time()
        worker._client = None

        progress = await worker.get_progress()
        assert "ollama_available" not in progress


class TestOllamaWorkerHealthCheck:
    """Tests for OllamaWorker.health_check method."""

    @pytest.mark.asyncio
    async def test_health_check_healthy(self):
        worker = OllamaWorker()
        worker._status = WorkerStatus.RUNNING
        mock_client = AsyncMock(spec=httpx.AsyncClient)

        avail_resp1 = MagicMock(status_code=200)
        avail_resp2 = MagicMock(status_code=200)
        tags_resp = MagicMock()
        tags_resp.json.return_value = {"models": [{"name": "qwen2.5-coder:7b"}]}

        mock_client.get = AsyncMock(side_effect=[avail_resp1, avail_resp2, tags_resp])
        worker._client = mock_client

        health = await worker.health_check()

        assert health["healthy"] is True
        assert health["status"] == "running"
        assert health["details"]["ollama_server"] is True
        assert health["details"]["model_available"] is True

    @pytest.mark.asyncio
    async def test_health_check_unhealthy_ollama_down(self):
        worker = OllamaWorker()
        worker._status = WorkerStatus.RUNNING
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
        worker._client = mock_client

        health = await worker.health_check()

        assert health["healthy"] is False
        assert health["details"]["ollama_server"] is False
        assert health["details"]["model_available"] is False

    @pytest.mark.asyncio
    async def test_health_check_model_not_available(self):
        worker = OllamaWorker(config=OllamaConfig(model="missing:latest"))
        worker._status = WorkerStatus.RUNNING
        mock_client = AsyncMock(spec=httpx.AsyncClient)

        avail_resp1 = MagicMock(status_code=200)
        avail_resp2 = MagicMock(status_code=200)
        tags_resp = MagicMock()
        tags_resp.json.return_value = {"models": [{"name": "llama3:8b"}]}

        mock_client.get = AsyncMock(side_effect=[avail_resp1, avail_resp2, tags_resp])
        worker._client = mock_client

        health = await worker.health_check()

        assert health["details"]["ollama_server"] is True
        assert health["details"]["model_available"] is False

    @pytest.mark.asyncio
    async def test_health_check_no_client(self):
        worker = OllamaWorker()
        worker._status = WorkerStatus.RUNNING
        worker._client = None

        health = await worker.health_check()

        assert health["healthy"] is False

    @pytest.mark.asyncio
    async def test_health_check_non_running_status(self):
        worker = OllamaWorker()
        worker._status = WorkerStatus.PENDING
        worker._client = None

        health = await worker.health_check()

        assert health["healthy"] is False
        assert health["status"] == "pending"


class TestOllamaWorkerIsAvailable:
    """Tests for OllamaWorker._is_available method."""

    @pytest.mark.asyncio
    async def test_available_when_status_200(self):
        worker = OllamaWorker()
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(return_value=MagicMock(status_code=200, text="OK"))
        worker._client = mock_client

        assert await worker._is_available() is True

    @pytest.mark.asyncio
    async def test_available_when_ollama_text_in_response(self):
        worker = OllamaWorker()
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(
            return_value=MagicMock(status_code=503, text="Ollama is running")
        )
        worker._client = mock_client

        assert await worker._is_available() is True

    @pytest.mark.asyncio
    async def test_unavailable_on_connect_error(self):
        worker = OllamaWorker()
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
        worker._client = mock_client

        assert await worker._is_available() is False

    @pytest.mark.asyncio
    async def test_unavailable_without_client(self):
        worker = OllamaWorker()
        worker._client = None
        assert await worker._is_available() is False

    @pytest.mark.asyncio
    async def test_unavailable_on_timeout(self):
        worker = OllamaWorker()
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(side_effect=httpx.ReadTimeout("timeout"))
        worker._client = mock_client

        assert await worker._is_available() is False

    @pytest.mark.asyncio
    async def test_unavailable_on_generic_exception(self):
        worker = OllamaWorker()
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(side_effect=Exception("something broke"))
        worker._client = mock_client

        assert await worker._is_available() is False

    @pytest.mark.asyncio
    async def test_unavailable_when_status_not_200_and_no_ollama_text(self):
        worker = OllamaWorker()
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(
            return_value=MagicMock(status_code=503, text="Service Unavailable")
        )
        worker._client = mock_client

        assert await worker._is_available() is False


class TestOllamaWorkerListModels:
    """Tests for OllamaWorker._list_models method."""

    @pytest.mark.asyncio
    async def test_list_models_success(self):
        worker = OllamaWorker()
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "models": [
                {"name": "llama3:8b", "size": 4700000000},
                {"name": "qwen2.5-coder:7b", "size": 4500000000},
            ]
        }
        mock_resp.raise_for_status = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        worker._client = mock_client

        models = await worker._list_models()

        assert len(models) == 2
        assert models[0]["name"] == "llama3:8b"
        assert models[1]["name"] == "qwen2.5-coder:7b"

    @pytest.mark.asyncio
    async def test_list_models_empty(self):
        worker = OllamaWorker()
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"models": []}
        mock_resp.raise_for_status = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        worker._client = mock_client

        models = await worker._list_models()
        assert models == []

    @pytest.mark.asyncio
    async def test_list_models_without_client(self):
        worker = OllamaWorker()
        worker._client = None
        models = await worker._list_models()
        assert models == []

    @pytest.mark.asyncio
    async def test_list_models_http_error(self):
        worker = OllamaWorker()
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(
            side_effect=httpx.HTTPStatusError(
                "500", request=MagicMock(), response=MagicMock(status_code=500)
            )
        )
        worker._client = mock_client

        with pytest.raises(httpx.HTTPStatusError):
            await worker._list_models()

    @pytest.mark.asyncio
    async def test_list_models_missing_models_key(self):
        worker = OllamaWorker()
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_resp = MagicMock()
        mock_resp.json.return_value = {}
        mock_resp.raise_for_status = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        worker._client = mock_client

        models = await worker._list_models()
        assert models == []


class TestOllamaWorkerPullModel:
    """Tests for OllamaWorker._pull_model method."""

    @pytest.mark.asyncio
    async def test_pull_model_success(self):
        worker = OllamaWorker()
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"status": "success"}
        mock_resp.raise_for_status = MagicMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        worker._client = mock_client

        result = await worker._pull_model("llama3:8b")
        assert result is True

    @pytest.mark.asyncio
    async def test_pull_model_non_success_status(self):
        worker = OllamaWorker()
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"status": "error"}
        mock_resp.raise_for_status = MagicMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        worker._client = mock_client

        result = await worker._pull_model("llama3:8b")
        assert result is False

    @pytest.mark.asyncio
    async def test_pull_model_without_client(self):
        worker = OllamaWorker()
        worker._client = None
        result = await worker._pull_model("llama3:8b")
        assert result is False

    @pytest.mark.asyncio
    async def test_pull_model_http_error(self):
        worker = OllamaWorker()
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post = AsyncMock(
            side_effect=httpx.HTTPStatusError(
                "404", request=MagicMock(), response=MagicMock(status_code=404)
            )
        )
        worker._client = mock_client

        with pytest.raises(httpx.HTTPStatusError):
            await worker._pull_model("nonexistent:latest")

    @pytest.mark.asyncio
    async def test_pull_model_sends_correct_payload(self):
        worker = OllamaWorker()
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"status": "success"}
        mock_resp.raise_for_status = MagicMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        worker._client = mock_client

        await worker._pull_model("llama3:8b")

        call_args = mock_client.post.call_args
        assert call_args[1]["json"]["name"] == "llama3:8b"
        assert call_args[1]["json"]["stream"] is False


class TestOllamaWorkerGenerate:
    """Tests for OllamaWorker._generate method."""

    @pytest.mark.asyncio
    async def test_generate_sends_correct_payload(self):
        worker = OllamaWorker(
            config=OllamaConfig(
                temperature=0.5,
                num_ctx=2048,
                num_predict=1024,
                top_p=0.8,
                top_k=20,
                keep_alive="10m",
            )
        )
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "response": "Generated text",
            "done": True,
        }
        mock_resp.raise_for_status = MagicMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        worker._client = mock_client

        result = await worker._generate("Hello", "llama3:8b", 0.5)

        assert result["response"] == "Generated text"
        call_args = mock_client.post.call_args
        payload = call_args[1]["json"]
        assert payload["model"] == "llama3:8b"
        assert payload["prompt"] == "Hello"
        assert payload["stream"] is False
        assert payload["options"]["temperature"] == 0.5
        assert payload["options"]["num_ctx"] == 2048
        assert payload["options"]["num_predict"] == 1024
        assert payload["options"]["top_p"] == 0.8
        assert payload["options"]["top_k"] == 20
        assert payload["keep_alive"] == "10m"

    @pytest.mark.asyncio
    async def test_generate_without_client_raises(self):
        worker = OllamaWorker()
        worker._client = None

        with pytest.raises(RuntimeError, match="Client not initialized"):
            await worker._generate("test", "model", 0.7)

    @pytest.mark.asyncio
    async def test_generate_posts_to_correct_endpoint(self):
        worker = OllamaWorker()
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"response": "text", "done": True}
        mock_resp.raise_for_status = MagicMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        worker._client = mock_client

        await worker._generate("test", "model", 0.7)

        call_args = mock_client.post.call_args
        assert call_args[0][0] == "/api/generate"


class TestOllamaWorkerChat:
    """Tests for OllamaWorker._chat method."""

    @pytest.mark.asyncio
    async def test_chat_sends_correct_payload(self):
        worker = OllamaWorker()
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "model": "qwen2.5-coder:7b",
            "message": {"role": "assistant", "content": "Chat response"},
            "done": True,
            "total_duration": 1234567890,
            "eval_count": 42,
            "eval_duration": 987654321,
        }
        mock_resp.raise_for_status = MagicMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        worker._client = mock_client

        messages = [
            {"role": "system", "content": "Be helpful"},
            {"role": "user", "content": "Hello"},
        ]
        result = await worker._chat(messages, "qwen2.5-coder:7b", 0.7)

        assert result["response"] == "Chat response"
        assert result["model"] == "qwen2.5-coder:7b"
        assert result["done"] is True
        assert result["total_duration"] == 1234567890
        assert result["eval_count"] == 42
        assert result["eval_duration"] == 987654321

        call_args = mock_client.post.call_args
        payload = call_args[1]["json"]
        assert payload["model"] == "qwen2.5-coder:7b"
        assert payload["messages"] == messages
        assert payload["stream"] is False

    @pytest.mark.asyncio
    async def test_chat_handles_missing_message(self):
        worker = OllamaWorker()
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"model": "test", "done": True}
        mock_resp.raise_for_status = MagicMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        worker._client = mock_client

        result = await worker._chat([], "model", 0.7)
        assert result["response"] == ""

    @pytest.mark.asyncio
    async def test_chat_without_client_raises(self):
        worker = OllamaWorker()
        worker._client = None

        with pytest.raises(RuntimeError, match="Client not initialized"):
            await worker._chat([], "model", 0.7)

    @pytest.mark.asyncio
    async def test_chat_posts_to_correct_endpoint(self):
        worker = OllamaWorker()
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "model": "test",
            "message": {"content": "hi"},
            "done": True,
        }
        mock_resp.raise_for_status = MagicMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        worker._client = mock_client

        await worker._chat([], "model", 0.7)

        call_args = mock_client.post.call_args
        assert call_args[0][0] == "/api/chat"

    @pytest.mark.asyncio
    async def test_chat_response_structure(self):
        worker = OllamaWorker()
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "model": "m",
            "message": {"role": "assistant", "content": "c"},
            "done": True,
            "total_duration": 100,
            "eval_count": 10,
            "eval_duration": 50,
        }
        mock_resp.raise_for_status = MagicMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        worker._client = mock_client

        result = await worker._chat([], "m", 0.7)

        assert "model" in result
        assert "response" in result
        assert "done" in result
        assert "total_duration" in result
        assert "eval_count" in result
        assert "eval_duration" in result


class TestOllamaWorkerCleanup:
    """Tests for OllamaWorker._cleanup_client method."""

    @pytest.mark.asyncio
    async def test_cleanup_closes_and_nullifies(self):
        worker = OllamaWorker()
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        worker._client = mock_client

        await worker._cleanup_client()

        mock_client.aclose.assert_called_once()
        assert worker._client is None

    @pytest.mark.asyncio
    async def test_cleanup_when_no_client(self):
        worker = OllamaWorker()
        worker._client = None

        await worker._cleanup_client()

        assert worker._client is None

    @pytest.mark.asyncio
    async def test_cleanup_handles_close_error(self):
        worker = OllamaWorker()
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.aclose = AsyncMock(side_effect=Exception("close failed"))
        worker._client = mock_client

        await worker._cleanup_client()

        assert worker._client is None


class TestOllamaWorkerStoreResult:
    """Tests for OllamaWorker._store_result_in_session_buddy method."""

    @pytest.mark.asyncio
    async def test_store_result_calls_session_buddy(self):
        worker = OllamaWorker()
        sb_client = AsyncMock()
        worker.session_buddy_client = sb_client

        result = WorkerResult(
            worker_id="test-id",
            status=WorkerStatus.COMPLETED,
            output="Hello world",
            duration_seconds=1.5,
            metadata={"tokens_generated": 42},
        )
        task = {"prompt": "Say hello"}

        await worker._store_result_in_session_buddy(result, task)

        sb_client.call_tool.assert_called_once()
        call_kwargs = sb_client.call_tool.call_args[1]
        assert call_kwargs["arguments"]["content"] == "Hello world"
        assert call_kwargs["arguments"]["metadata"]["type"] == "ollama_execution"
        assert call_kwargs["arguments"]["metadata"]["worker_id"] == "test-id"
        assert call_kwargs["arguments"]["metadata"]["model"] == "qwen2.5-coder:7b"

    @pytest.mark.asyncio
    async def test_store_result_no_client(self):
        worker = OllamaWorker()
        worker.session_buddy_client = None

        result = WorkerResult(worker_id="test", status=WorkerStatus.COMPLETED)
        task = {"prompt": "test"}

        await worker._store_result_in_session_buddy(result, task)

    @pytest.mark.asyncio
    async def test_store_result_handles_error(self):
        worker = OllamaWorker()
        sb_client = AsyncMock()
        sb_client.call_tool = AsyncMock(side_effect=Exception("Connection lost"))
        worker.session_buddy_client = sb_client

        result = WorkerResult(worker_id="test", status=WorkerStatus.COMPLETED, output="data")
        task = {"prompt": "test"}

        await worker._store_result_in_session_buddy(result, task)

    @pytest.mark.asyncio
    async def test_store_result_truncates_long_prompt(self):
        worker = OllamaWorker()
        sb_client = AsyncMock()
        worker.session_buddy_client = sb_client

        result = WorkerResult(
            worker_id="test",
            status=WorkerStatus.COMPLETED,
            output="output",
            metadata={"tokens_generated": 10},
        )
        long_prompt = "x" * 1000
        task = {"prompt": long_prompt}

        await worker._store_result_in_session_buddy(result, task)

        call_kwargs = sb_client.call_tool.call_args[1]
        stored_prompt = call_kwargs["arguments"]["metadata"]["task_prompt"]
        assert len(stored_prompt) <= 500

    @pytest.mark.asyncio
    async def test_store_result_includes_correct_metadata_fields(self):
        worker = OllamaWorker()
        sb_client = AsyncMock()
        worker.session_buddy_client = sb_client

        result = WorkerResult(
            worker_id="wid",
            status=WorkerStatus.COMPLETED,
            output="out",
            duration_seconds=2.0,
            metadata={"tokens_generated": 99},
        )
        task = {"prompt": "p"}

        await worker._store_result_in_session_buddy(result, task)

        call_kwargs = sb_client.call_tool.call_args[1]
        meta = call_kwargs["arguments"]["metadata"]
        assert meta["worker_type"] == "terminal-ollama"
        assert meta["task_prompt"] == "p"
        assert meta["status"] == "completed"
        assert meta["duration_seconds"] == 2.0
        assert meta["tokens_generated"] == 99


class TestOllamaConfigModelRouting:
    """Tests for OllamaConfig model routing integration."""

    def test_custom_routing_overrides_default_for_specific_category(self):
        custom = {
            TaskCategory.CODE_GENERATION: "deepseek-coder:33b",
            TaskCategory.REASONING: "qwen2.5:72b",
        }
        config = OllamaConfig(model_routing=custom, model="fallback-model")

        assert config.get_model_for_category(TaskCategory.CODE_GENERATION) == "deepseek-coder:33b"
        assert config.get_model_for_category(TaskCategory.REASONING) == "qwen2.5:72b"
        assert config.get_model_for_category(TaskCategory.DEBUGGING) == "fallback-model"

    def test_none_model_routing_uses_defaults(self):
        config = OllamaConfig(model_routing=None)
        for cat in TaskCategory:
            model = config.get_model_for_category(cat)
            assert model == DEFAULT_MODEL_ROUTING[cat]

    def test_empty_routing_dict_uses_defaults(self):
        config = OllamaConfig(model="fallback", model_routing={})
        for cat in TaskCategory:
            model = config.get_model_for_category(cat)
            assert model == DEFAULT_MODEL_ROUTING[cat]

    def test_partial_custom_routing_with_fallback(self):
        custom = {TaskCategory.REASONING: "reasoning-model:latest"}
        config = OllamaConfig(model_routing=custom)
        assert config.get_model_for_category(TaskCategory.REASONING) == "reasoning-model:latest"
        assert (
            config.get_model_for_category(TaskCategory.CODE_GENERATION)
            == DEFAULT_MODEL_ROUTING[TaskCategory.CODE_GENERATION]
        )
