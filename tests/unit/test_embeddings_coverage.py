"""Comprehensive coverage tests for mahavishnu.core.embeddings."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.core.embeddings import (
    BatchEmbeddingRequest,
    BudgetConfig,
    BudgetExceededError,
    CircuitBreaker,
    CircuitState,
    EmbeddingProvider,
    EmbeddingProviderError,
    EmbeddingProviderInterface,
    EmbeddingQuery,
    EmbeddingRequest,
    EmbeddingResult,
    EmbeddingService,
    EmbeddingServiceError,
    FastEmbedProvider,
    OllamaProvider,
    OpenAIProvider,
    RateLimitConfig,
    SecureEmbeddingService,
    ServiceOverloadedError,
    cosine_similarity,
    embed,
    euclidean_distance,
    get_embedding_service,
    get_secure_embedding_service,
)

# -----------------------------------------------------------------------------
# Enum / exception sanity
# -----------------------------------------------------------------------------


class TestEmbeddingProvider:
    def test_values(self):
        assert EmbeddingProvider.FASTEMBED.value == "fastembed"
        assert EmbeddingProvider.OLLAMA.value == "ollama"
        assert EmbeddingProvider.OPENAI.value == "openai"
        assert EmbeddingProvider.SENTENCE_TRANSFORMERS.value == "sentence_transformers"


class TestExceptionHierarchy:
    def test_embedding_provider_error_is_service_error(self):
        assert issubclass(EmbeddingProviderError, EmbeddingServiceError)

    def test_budget_exceeded_error_attributes(self):
        err = BudgetExceededError("u1", 10, 5)
        assert err.user_id == "u1"
        assert err.current == 10
        assert err.limit == 5
        assert "u1" in str(err)
        assert "10/5" in str(err)

    def test_service_overloaded_is_service_error(self):
        err = ServiceOverloadedError("oops")
        assert isinstance(err, EmbeddingServiceError)


# -----------------------------------------------------------------------------
# EmbeddingResult
# -----------------------------------------------------------------------------


class TestEmbeddingResult:
    def test_dimension_inferred_from_first_embedding(self):
        r = EmbeddingResult(
            embeddings=[[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]],
            model="m",
            provider=EmbeddingProvider.FASTEMBED,
        )
        assert r.dimension == 3
        assert isinstance(r.model_version, str)
        assert len(r.model_version) == 16
        assert r.created_at is not None

    def test_empty_embeddings_default_dimension_zero(self):
        r = EmbeddingResult(embeddings=[], model="m", provider=EmbeddingProvider.FASTEMBED)
        assert r.dimension == 0

    def test_explicit_dimension_used(self):
        r = EmbeddingResult(
            embeddings=[[0.0, 0.0]],
            model="m",
            provider=EmbeddingProvider.OLLAMA,
            dimension=999,
        )
        assert r.dimension == 999

    def test_explicit_model_version_used(self):
        r = EmbeddingResult(
            embeddings=[[0.0]],
            model="m",
            provider=EmbeddingProvider.OPENAI,
            model_version="abc123",
        )
        assert r.model_version == "abc123"

    def test_explicit_created_at_used(self):
        from datetime import datetime

        dt = datetime(2020, 1, 1)
        r = EmbeddingResult(
            embeddings=[[0.0]],
            model="m",
            provider=EmbeddingProvider.FASTEMBED,
            created_at=dt,
        )
        assert r.created_at == dt

    def test_compute_model_version_is_stable(self):
        r1 = EmbeddingResult([[0.0]], "m", EmbeddingProvider.OLLAMA)
        r2 = EmbeddingResult([[0.0]], "m", EmbeddingProvider.OLLAMA)
        assert r1.model_version == r2.model_version

    def test_different_providers_different_versions(self):
        r1 = EmbeddingResult([[0.0]], "m", EmbeddingProvider.OLLAMA)
        r2 = EmbeddingResult([[0.0]], "m", EmbeddingProvider.OPENAI)
        assert r1.model_version != r2.model_version

    def test_different_models_different_versions(self):
        r1 = EmbeddingResult([[0.0]], "m1", EmbeddingProvider.OLLAMA)
        r2 = EmbeddingResult([[0.0]], "m2", EmbeddingProvider.OLLAMA)
        assert r1.model_version != r2.model_version

    def test_is_compatible_with_same(self):
        a = EmbeddingResult([[0.0] * 3], "m", EmbeddingProvider.OLLAMA)
        b = EmbeddingResult([[0.0] * 3], "m", EmbeddingProvider.OLLAMA)
        assert a.is_compatible_with(b) is True

    def test_is_compatible_with_different_version(self):
        a = EmbeddingResult([[0.0] * 3], "m", EmbeddingProvider.OLLAMA, model_version="v1")
        b = EmbeddingResult([[0.0] * 3], "m", EmbeddingProvider.OLLAMA, model_version="v2")
        assert a.is_compatible_with(b) is False

    def test_is_compatible_with_different_dimension(self):
        a = EmbeddingResult([[0.0] * 3], "m", EmbeddingProvider.OLLAMA, dimension=3)
        b = EmbeddingResult([[0.0] * 4], "m", EmbeddingProvider.OLLAMA, dimension=4)
        assert a.is_compatible_with(b) is False

    def test_to_metadata(self):
        r = EmbeddingResult(
            embeddings=[[0.1, 0.2]],
            model="my-model",
            provider=EmbeddingProvider.OPENAI,
        )
        meta = r.to_metadata()
        assert meta["model"] == "my-model"
        assert meta["provider"] == "openai"
        assert meta["dimension"] == 2
        assert isinstance(meta["model_version"], str)
        assert "created_at" in meta

    def test_repr_includes_summary(self):
        r = EmbeddingResult(
            embeddings=[[0.0] * 4, [0.0] * 4],
            model="m",
            provider=EmbeddingProvider.FASTEMBED,
        )
        text = repr(r)
        assert "EmbeddingResult" in text
        assert "fastembed" in text
        assert "count=2" in text


# -----------------------------------------------------------------------------
# CircuitBreaker
# -----------------------------------------------------------------------------


class TestCircuitBreaker:
    def test_initial_state_closed(self):
        cb = CircuitBreaker()
        assert cb.state == CircuitState.CLOSED
        assert cb.can_execute() is True
        assert cb.is_open is False

    def test_record_failure_increments_count(self):
        cb = CircuitBreaker(failure_threshold=2)
        cb.record_failure()
        assert cb.failure_count == 1
        assert cb.state == CircuitState.CLOSED
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert cb.is_open is True

    def test_open_circuit_blocks_execution_within_timeout(self):
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=60.0)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        # within timeout, still open
        assert cb.can_execute() is False

    def test_open_circuit_transitions_to_half_open_after_timeout(self):
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.0)
        cb.record_failure()
        # recovery_timeout 0 means next call to can_execute transitions
        # we need to ensure last_failure_time was set, then advance time
        cb.last_failure_time = time.monotonic() - 10.0
        assert cb.can_execute() is True
        assert cb.state == CircuitState.HALF_OPEN

    def test_half_open_success_closes_circuit(self):
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.0)
        cb.state = CircuitState.HALF_OPEN
        cb.failure_count = 3
        cb.record_success()
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0

    def test_half_open_failure_reopens(self):
        cb = CircuitBreaker(failure_threshold=10, recovery_timeout=0.0)
        cb.state = CircuitState.HALF_OPEN
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_record_success_in_closed_no_change(self):
        cb = CircuitBreaker()
        cb.record_success()
        assert cb.state == CircuitState.CLOSED

    def test_is_open_property(self):
        cb = CircuitBreaker()
        cb.state = CircuitState.OPEN
        assert cb.is_open is True
        cb.state = CircuitState.CLOSED
        assert cb.is_open is False


# -----------------------------------------------------------------------------
# Abstract interface existence
# -----------------------------------------------------------------------------


class TestProviderInterface:
    def test_interface_is_abstract(self):
        # Cannot instantiate the abstract class directly
        with pytest.raises(TypeError):
            EmbeddingProviderInterface()  # type: ignore[abstract]

    def test_subclass_must_implement_abstract_methods(self):
        class Incomplete(EmbeddingProviderInterface):
            pass

        with pytest.raises(TypeError):
            Incomplete()  # type: ignore[abstract]


# -----------------------------------------------------------------------------
# FastEmbedProvider
# -----------------------------------------------------------------------------


class TestFastEmbedProvider:
    def test_default_model(self):
        p = FastEmbedProvider()
        assert p.model == "BAAI/bge-small-en-v1.5"
        assert p._client is None

    def test_custom_model(self):
        p = FastEmbedProvider(model="custom/model")
        assert p.model == "custom/model"

    def test_is_available_true(self):
        assert FastEmbedProvider().is_available() is True

    async def test_empty_texts_returns_empty_result(self):
        p = FastEmbedProvider()
        r = await p.embed([])
        assert r.embeddings == []
        assert r.model == p.model
        assert r.provider == EmbeddingProvider.FASTEMBED
        assert r.dimension == 0

    async def test_fallback_embed_when_fastembed_missing(self):
        FastEmbedProvider()
        # Force fallback by raising ImportError on from fastembed import TextEmbedding
        with (
            patch.dict("sys.modules", {"fastembed": None}),
            patch(
                "builtins.__import__",
                side_effect=ImportError("no fastembed"),
            ),
        ):
            # Instead of messing with __import__, just call _load_client
            # and ensure that the fallback is used when fastembed raises.
            pass
        # Easier: directly construct the fallback
        fb = FastEmbedProvider._FallbackTextEmbedding("test-model")
        out = list(fb.embed(["hello", "world"]))
        assert len(out) == 2
        assert len(out[0]) == 384
        assert len(out[1]) == 384

    async def test_embed_with_fallback_path(self):
        """Force the import branch to use the fallback class and embed."""
        p = FastEmbedProvider(model="m")
        # Pre-load client with the fallback
        p._client = FastEmbedProvider._FallbackTextEmbedding(p.model)
        r = await p.embed(["a", "b"])
        assert len(r.embeddings) == 2
        assert r.dimension == 384
        assert r.provider == EmbeddingProvider.FASTEMBED

    async def test_load_client_import_error_sets_fallback(self):
        p = FastEmbedProvider()
        # Simulate ImportError by patching the import inside _load_client
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "fastembed":
                raise ImportError("simulated")
            return real_import(name, *args, **kwargs)

        with patch.object(builtins, "__import__", side_effect=fake_import):
            await p._load_client()
        assert p._client is not None
        assert isinstance(p._client, FastEmbedProvider._FallbackTextEmbedding)


# -----------------------------------------------------------------------------
# OllamaProvider
# -----------------------------------------------------------------------------


class TestOllamaProvider:
    def test_defaults(self):
        p = OllamaProvider()
        assert p.model == "nomic-embed-text"
        assert p.base_url == "http://localhost:11434"
        assert p._client is None

    def test_custom(self):
        p = OllamaProvider(model="x", base_url="http://example.com")
        assert p.model == "x"
        assert p.base_url == "http://example.com"

    async def test_get_client_creates_once(self):
        p = OllamaProvider()
        c1 = await p._get_client()
        c2 = await p._get_client()
        assert c1 is c2
        await c1.aclose()

    async def test_empty_texts(self):
        p = OllamaProvider()
        r = await p.embed([])
        assert r.embeddings == []
        assert r.provider == EmbeddingProvider.OLLAMA
        assert r.dimension == 0

    async def test_embed_success(self):
        p = OllamaProvider()
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = [
            {"embedding": [0.1, 0.2, 0.3]},
            {"embedding": [0.4, 0.5, 0.6]},
        ]
        client = AsyncMock()
        client.post.return_value = response
        p._client = client
        r = await p.embed(["a", "b"])
        assert len(r.embeddings) == 2
        assert r.embeddings[0] == [0.1, 0.2, 0.3]

    async def test_embed_non_200_raises(self):
        p = OllamaProvider()
        response = MagicMock()
        response.status_code = 500
        response.text = "boom"
        client = AsyncMock()
        client.post.return_value = response
        p._client = client
        with pytest.raises(EmbeddingServiceError) as exc:
            await p.embed(["x"])
        assert "500" in str(exc.value)
        assert "boom" in str(exc.value)

    def test_is_available_true_when_socket_open(self):
        p = OllamaProvider()
        with patch("socket.socket") as mock_socket:
            sock_instance = MagicMock()
            sock_instance.connect_ex.return_value = 0
            mock_socket.return_value = sock_instance
            assert p.is_available() is True

    def test_is_available_false_when_socket_closed(self):
        p = OllamaProvider()
        with patch("socket.socket") as mock_socket:
            sock_instance = MagicMock()
            sock_instance.connect_ex.return_value = 1
            mock_socket.return_value = sock_instance
            assert p.is_available() is False

    def test_is_available_false_on_exception(self):
        p = OllamaProvider()
        with patch("socket.socket", side_effect=OSError("fail")):
            assert p.is_available() is False


# -----------------------------------------------------------------------------
# OpenAIProvider
# -----------------------------------------------------------------------------


class TestOpenAIProvider:
    def test_defaults(self):
        p = OpenAIProvider()
        assert p.model == "text-embedding-3-small"
        assert p.api_key is None
        assert p._client is None

    def test_custom_key(self):
        p = OpenAIProvider(model="text-embedding-3-large", api_key="k")
        assert p.model == "text-embedding-3-large"
        assert p.api_key == "k"

    async def test_get_client_uses_explicit_key(self):
        p = OpenAIProvider(api_key="explicit")
        c = await p._get_client()
        assert "Authorization" in c.headers
        assert c.headers["Authorization"] == "Bearer explicit"
        await c.aclose()

    async def test_get_client_reads_env_var(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "env-key")
        p = OpenAIProvider()
        c = await p._get_client()
        assert c.headers["Authorization"] == "Bearer env-key"
        assert p.api_key == "env-key"
        await c.aclose()

    async def test_get_client_raises_when_no_key(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        p = OpenAIProvider()
        with pytest.raises(EmbeddingProviderError) as exc:
            await p._get_client()
        assert "API key" in str(exc.value)

    async def test_empty_texts(self):
        p = OpenAIProvider(api_key="k")
        r = await p.embed([])
        assert r.embeddings == []
        assert r.provider == EmbeddingProvider.OPENAI
        assert r.dimension == 0

    async def test_embed_success(self):
        p = OpenAIProvider(api_key="k")
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            "data": [
                {"embedding": [0.1, 0.2]},
                {"embedding": [0.3, 0.4]},
            ]
        }
        client = AsyncMock()
        client.post.return_value = response
        p._client = client
        r = await p.embed(["a", "b"])
        assert len(r.embeddings) == 2
        assert r.embeddings[0] == [0.1, 0.2]

    async def test_embed_non_200_raises(self):
        p = OpenAIProvider(api_key="k")
        response = MagicMock()
        response.status_code = 429
        response.text = "rate limited"
        client = AsyncMock()
        client.post.return_value = response
        p._client = client
        with pytest.raises(EmbeddingServiceError) as exc:
            await p.embed(["x"])
        assert "429" in str(exc.value)

    def test_is_available_true_with_env(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "k")
        assert OpenAIProvider().is_available() is True

    def test_is_available_false_without_env(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        assert OpenAIProvider().is_available() is False


# -----------------------------------------------------------------------------
# EmbeddingService (deprecated)
# -----------------------------------------------------------------------------


class TestEmbeddingService:
    def test_warns_on_init(self):
        with pytest.warns(DeprecationWarning):
            EmbeddingService()

    def test_unknown_provider_raises(self):
        s = EmbeddingService(provider=EmbeddingProvider.SENTENCE_TRANSFORMERS)
        with pytest.raises(EmbeddingProviderError):
            s._get_provider(EmbeddingProvider.SENTENCE_TRANSFORMERS)

    def test_circuit_breaker_created_with_config(self):
        s = EmbeddingService(
            circuit_breaker_config={"failure_threshold": 2, "recovery_timeout": 1.0}
        )
        cb = s._get_circuit_breaker(EmbeddingProvider.FASTEMBED)
        assert cb.failure_threshold == 2
        assert cb.recovery_timeout == 1.0

    def test_get_provider_caches_instance(self):
        s = EmbeddingService(provider=EmbeddingProvider.FASTEMBED)
        a = s._get_provider(EmbeddingProvider.FASTEMBED)
        b = s._get_provider(EmbeddingProvider.FASTEMBED)
        assert a is b

    def test_get_provider_for_ollama(self):
        s = EmbeddingService(provider=EmbeddingProvider.OLLAMA)
        p = s._get_provider(EmbeddingProvider.OLLAMA)
        assert isinstance(p, OllamaProvider)

    def test_get_provider_for_openai(self):
        s = EmbeddingService(provider=EmbeddingProvider.OPENAI)
        p = s._get_provider(EmbeddingProvider.OPENAI)
        assert isinstance(p, OpenAIProvider)

    async def test_embed_empty_returns_empty(self):
        s = EmbeddingService(provider=EmbeddingProvider.FASTEMBED)
        r = await s.embed([])
        assert r.embeddings == []
        assert r.dimension == 0

    async def test_embed_uses_preferred_provider_fastembed(self):
        s = EmbeddingService(provider=EmbeddingProvider.FASTEMBED)
        # Use fallback provider path (fastembed not installed) for deterministic
        s._providers[EmbeddingProvider.FASTEMBED] = FastEmbedProvider(model="m")
        s._providers[
            EmbeddingProvider.FASTEMBED
        ]._client = FastEmbedProvider._FallbackTextEmbedding("m")
        r = await s.embed(["x"])
        assert len(r.embeddings) == 1

    async def test_embed_preferred_provider_unavailable_no_fallback_raises(self):
        """When the preferred provider is unavailable and fallback disabled, raise."""
        s = EmbeddingService(provider=EmbeddingProvider.OPENAI, auto_fallback=False)
        # Simulate provider not available by using a stub that returns False
        stub = MagicMock()
        stub.is_available.return_value = False
        s._providers[EmbeddingProvider.OPENAI] = stub
        with pytest.raises(EmbeddingProviderError):
            await s.embed(["x"])

    async def test_embed_with_circuit_breaker_open_no_fallback_raises(self):
        s = EmbeddingService(provider=EmbeddingProvider.OPENAI, auto_fallback=False)
        # Force the circuit breaker open
        cb = s._get_circuit_breaker(EmbeddingProvider.OPENAI)
        cb.state = CircuitState.OPEN
        cb.last_failure_time = time.monotonic()  # not yet timed out
        with pytest.raises(EmbeddingProviderError) as exc:
            await s.embed(["x"])
        assert "Circuit breaker" in str(exc.value)

    async def test_embed_with_circuit_breaker_open_with_fallback(self):
        # When the preferred provider's circuit is open and allow_fallback
        # is True (auto-fallback path), the service falls back to the
        # next available provider.
        s = EmbeddingService(provider=EmbeddingProvider.OPENAI, auto_fallback=True)
        cb = s._get_circuit_breaker(EmbeddingProvider.OPENAI)
        cb.state = CircuitState.OPEN
        cb.last_failure_time = time.monotonic()
        # Stub fastembed to succeed
        stub = FastEmbedProvider(model="m")
        stub._client = FastEmbedProvider._FallbackTextEmbedding("m")
        s._providers[EmbeddingProvider.FASTEMBED] = stub
        # Call the internal _embed_with_circuit_breaker directly with
        # allow_fallback=True (the public embed() method always passes
        # allow_fallback=False for the explicit-provider path).
        r = await s._embed_with_circuit_breaker(
            EmbeddingProvider.OPENAI, ["hi"], allow_fallback=True
        )
        assert len(r.embeddings) == 1
        assert r.provider == EmbeddingProvider.FASTEMBED

    async def test_embed_preferred_provider_failure_with_fallback(self):
        s = EmbeddingService(provider=EmbeddingProvider.OPENAI, auto_fallback=True)
        # Provide OPENAI stub that raises
        oa = MagicMock()
        oa.is_available.return_value = True
        oa.embed = AsyncMock(side_effect=RuntimeError("openai down"))
        s._providers[EmbeddingProvider.OPENAI] = oa
        # Provide FastEmbed stub that succeeds
        fe = FastEmbedProvider(model="m")
        fe._client = FastEmbedProvider._FallbackTextEmbedding("m")
        s._providers[EmbeddingProvider.FASTEMBED] = fe
        # Call internal method with allow_fallback=True (public embed()
        # always passes allow_fallback=False for the explicit-provider path).
        r = await s._embed_with_circuit_breaker(
            EmbeddingProvider.OPENAI, ["x"], allow_fallback=True
        )
        assert r.provider == EmbeddingProvider.FASTEMBED
        cb_oa = s._get_circuit_breaker(EmbeddingProvider.OPENAI)
        assert cb_oa.failure_count == 1

    async def test_embed_fallback_skips_excluded(self):
        s = EmbeddingService(auto_fallback=True)
        # All providers will fail: FastEmbed raises, Ollama raises, OpenAI raises
        fe = MagicMock()
        fe.is_available.return_value = True
        fe.embed = AsyncMock(side_effect=RuntimeError("nope"))
        s._providers[EmbeddingProvider.FASTEMBED] = fe
        ol = MagicMock()
        ol.is_available.return_value = True
        ol.embed = AsyncMock(side_effect=RuntimeError("nope"))
        s._providers[EmbeddingProvider.OLLAMA] = ol
        oa = MagicMock()
        oa.is_available.return_value = True
        oa.embed = AsyncMock(side_effect=RuntimeError("nope"))
        s._providers[EmbeddingProvider.OPENAI] = oa
        with pytest.raises(EmbeddingServiceError) as exc:
            await s.embed(["x"])
        assert "No embedding provider" in str(exc.value)

    async def test_embed_fallback_skips_circuit_breaker_open(self):
        s = EmbeddingService(auto_fallback=True)
        # Open circuit for FastEmbed; make Ollama succeed
        cb = s._get_circuit_breaker(EmbeddingProvider.FASTEMBED)
        cb.state = CircuitState.OPEN
        cb.last_failure_time = time.monotonic()
        ol = MagicMock()
        ol.is_available.return_value = True
        ol.embed = AsyncMock(
            return_value=EmbeddingResult([[0.1, 0.2]], "m", EmbeddingProvider.OLLAMA)
        )
        s._providers[EmbeddingProvider.OLLAMA] = ol
        r = await s.embed(["x"])
        assert r.provider == EmbeddingProvider.OLLAMA

    async def test_embed_fallback_skips_unavailable_provider(self):
        s = EmbeddingService(auto_fallback=True)
        # FastEmbed unavailable
        fe = MagicMock()
        fe.is_available.return_value = False
        s._providers[EmbeddingProvider.FASTEMBED] = fe
        # Ollama succeeds
        ol = MagicMock()
        ol.is_available.return_value = True
        ol.embed = AsyncMock(
            return_value=EmbeddingResult([[0.5, 0.6]], "m", EmbeddingProvider.OLLAMA)
        )
        s._providers[EmbeddingProvider.OLLAMA] = ol
        r = await s.embed(["x"])
        assert r.provider == EmbeddingProvider.OLLAMA

    async def test_embed_fallback_records_failure_on_error(self):
        s = EmbeddingService(auto_fallback=True)
        fe = MagicMock()
        fe.is_available.return_value = True
        fe.embed = AsyncMock(side_effect=RuntimeError("fastembed fail"))
        s._providers[EmbeddingProvider.FASTEMBED] = fe
        ol = MagicMock()
        ol.is_available.return_value = True
        ol.embed = AsyncMock(
            return_value=EmbeddingResult([[0.7, 0.8]], "m", EmbeddingProvider.OLLAMA)
        )
        s._providers[EmbeddingProvider.OLLAMA] = ol
        r = await s.embed(["x"])
        assert r.provider == EmbeddingProvider.OLLAMA
        cb_fe = s._get_circuit_breaker(EmbeddingProvider.FASTEMBED)
        assert cb_fe.failure_count == 1

    async def test_embed_records_success(self):
        s = EmbeddingService(provider=EmbeddingProvider.FASTEMBED)
        fe = FastEmbedProvider(model="m")
        fe._client = FastEmbedProvider._FallbackTextEmbedding("m")
        s._providers[EmbeddingProvider.FASTEMBED] = fe
        cb = s._get_circuit_breaker(EmbeddingProvider.FASTEMBED)
        # Pre-set half-open to verify transition to closed
        cb.state = CircuitState.HALF_OPEN
        cb.failure_count = 9
        r = await s.embed(["x"])
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0
        assert r.provider == EmbeddingProvider.FASTEMBED

    async def test_embed_batch_empty(self):
        s = EmbeddingService(provider=EmbeddingProvider.FASTEMBED)
        assert await s.embed_batch([]) == []

    async def test_embed_batch_returns_results(self):
        s = EmbeddingService(provider=EmbeddingProvider.FASTEMBED)
        fe = FastEmbedProvider(model="m")
        fe._client = FastEmbedProvider._FallbackTextEmbedding("m")
        s._providers[EmbeddingProvider.FASTEMBED] = fe
        results = await s.embed_batch([["a", "b"], ["c"]])
        assert len(results) == 2
        assert all(isinstance(r, EmbeddingResult) for r in results)

    async def test_embed_batch_returns_exception_for_failure(self):
        s = EmbeddingService(provider=EmbeddingProvider.FASTEMBED, auto_fallback=True)
        fe = MagicMock()
        fe.is_available.return_value = True
        fe.embed = AsyncMock(side_effect=RuntimeError("boom"))
        s._providers[EmbeddingProvider.FASTEMBED] = fe
        results = await s.embed_batch([["a"]])
        assert len(results) == 1
        # The exception is captured via gather return_exceptions
        assert isinstance(results[0], Exception)

    def test_get_available_providers(self):
        s = EmbeddingService(auto_fallback=True)
        fe = MagicMock()
        fe.is_available.return_value = True
        ol = MagicMock()
        ol.is_available.return_value = False
        oa = MagicMock()
        oa.is_available.return_value = False
        s._providers[EmbeddingProvider.FASTEMBED] = fe
        s._providers[EmbeddingProvider.OLLAMA] = ol
        s._providers[EmbeddingProvider.OPENAI] = oa
        available = s.get_available_providers()
        assert EmbeddingProvider.FASTEMBED in available
        assert EmbeddingProvider.OLLAMA not in available
        assert EmbeddingProvider.OPENAI not in available

    def test_get_available_providers_handles_errors(self):
        s = EmbeddingService(auto_fallback=True)
        fe = MagicMock()
        fe.is_available.side_effect = RuntimeError("nope")
        ol = MagicMock()
        ol.is_available.return_value = False
        oa = MagicMock()
        oa.is_available.return_value = False
        s._providers[EmbeddingProvider.FASTEMBED] = fe
        s._providers[EmbeddingProvider.OLLAMA] = ol
        s._providers[EmbeddingProvider.OPENAI] = oa
        assert s.get_available_providers() == []


# -----------------------------------------------------------------------------
# Singleton helpers
# -----------------------------------------------------------------------------


class TestGetEmbeddingService:
    def test_singleton_returns_same_instance(self):
        import mahavishnu.core.embeddings as mod

        mod._default_service = None
        a = get_embedding_service()
        b = get_embedding_service()
        assert a is b
        # reset for other tests
        mod._default_service = None

    def test_singleton_recreated_when_provider_changes(self):
        import mahavishnu.core.embeddings as mod

        mod._default_service = None
        a = get_embedding_service(provider=EmbeddingProvider.OLLAMA)
        b = get_embedding_service(provider=EmbeddingProvider.OPENAI)
        assert a is not b
        mod._default_service = None


class TestEmbedFunction:
    async def test_embed_returns_lists(self):
        import mahavishnu.core.embeddings as mod

        mod._default_service = None
        # Patch the service inside the singleton
        with patch("mahavishnu.core.embeddings.get_embedding_service") as gs:
            service = MagicMock()
            result = MagicMock()
            result.embeddings = [[0.1, 0.2]]
            service.embed = AsyncMock(return_value=result)
            gs.return_value = service
            out = await embed(["x"])
        assert out == [[0.1, 0.2]]


# -----------------------------------------------------------------------------
# Math helpers
# -----------------------------------------------------------------------------


class TestCosineSimilarity:
    def test_identical_vectors(self):
        assert cosine_similarity([1, 0, 0], [1, 0, 0]) == pytest.approx(1.0)

    def test_orthogonal_vectors(self):
        assert cosine_similarity([1, 0], [0, 1]) == pytest.approx(0.0)

    def test_opposite_vectors(self):
        assert cosine_similarity([1, 0], [-1, 0]) == pytest.approx(-1.0)

    def test_zero_vector(self):
        assert cosine_similarity([0, 0, 0], [1, 2, 3]) == 0.0

    def test_length_mismatch(self):
        with pytest.raises(ValueError):
            cosine_similarity([1, 2], [1, 2, 3])


class TestEuclideanDistance:
    def test_identical(self):
        assert euclidean_distance([0, 0], [0, 0]) == 0.0

    def test_simple(self):
        assert euclidean_distance([0, 0], [3, 4]) == pytest.approx(5.0)

    def test_length_mismatch(self):
        with pytest.raises(ValueError):
            euclidean_distance([1], [1, 2])


# -----------------------------------------------------------------------------
# Security models
# -----------------------------------------------------------------------------


class TestEmbeddingRequest:
    def test_basic(self):
        r = EmbeddingRequest(text="hello", user_id="u1")
        assert r.text == "hello"
        assert r.user_id == "u1"
        assert r.system_id is None

    def test_sanitize_text_strips_control_chars(self):
        r = EmbeddingRequest(text="  hello\x00\x01world  ", user_id="u1")
        assert "\x00" not in r.text
        assert "\x01" not in r.text
        # The validator strips surrounding whitespace
        assert r.text == "helloworld" or r.text.strip() == "helloworld"

    def test_sanitize_text_keeps_newlines_and_tabs(self):
        r = EmbeddingRequest(text="a\nb\tc", user_id="u1")
        assert "\n" in r.text
        assert "\t" in r.text

    def test_sanitize_text_normalizes_unicode(self):
        # NFKC normalization
        r = EmbeddingRequest(text="½", user_id="u1")
        assert r.text == "1⁄2"  # 1/2 NFKC form has 3 chars

    def test_sanitize_id_strips_invalid_chars(self):
        r = EmbeddingRequest(text="x", user_id="abc!@#def", system_id="foo bar")
        # '!' '#' and ' ' are stripped
        assert "!" not in r.user_id
        assert "#" not in r.user_id
        assert " " not in r.system_id

    def test_sanitize_id_none(self):
        r = EmbeddingRequest(text="x", user_id="u1", system_id=None)
        assert r.system_id is None

    def test_min_length_text(self):
        with pytest.raises(Exception):
            EmbeddingRequest(text="", user_id="u1")

    def test_min_length_user_id(self):
        with pytest.raises(Exception):
            EmbeddingRequest(text="x", user_id="")

    def test_max_length_text(self):
        with pytest.raises(Exception):
            EmbeddingRequest(text="x" * 100_001, user_id="u1")

    def test_max_length_user_id(self):
        with pytest.raises(Exception):
            EmbeddingRequest(text="x", user_id="u" * 257)


class TestBatchEmbeddingRequest:
    def test_basic(self):
        r = BatchEmbeddingRequest(texts=["a", "b"], user_id="u1")
        assert len(r.texts) == 2
        assert r.user_id == "u1"

    def test_min_length_texts(self):
        with pytest.raises(Exception):
            BatchEmbeddingRequest(texts=[], user_id="u1")

    def test_max_length_texts(self):
        with pytest.raises(Exception):
            BatchEmbeddingRequest(texts=["x"] * 101, user_id="u1")

    def test_validate_texts_strips_control_chars(self):
        r = BatchEmbeddingRequest(texts=["a\x00b", "c\x0fd"], user_id="u1")
        for t in r.texts:
            assert "\x00" not in t
            assert "\x0f" not in t

    def test_validate_texts_keeps_newlines_tabs(self):
        r = BatchEmbeddingRequest(texts=["a\nb", "c\td"], user_id="u1")
        assert r.texts[0] == "a\nb"
        assert r.texts[1] == "c\td"

    def test_oversized_text_raises(self):
        big = "x" * 100_001
        with pytest.raises(Exception):
            BatchEmbeddingRequest(texts=[big], user_id="u1")

    def test_sanitize_id(self):
        r = BatchEmbeddingRequest(texts=["a"], user_id="u 1", system_id="a b")
        assert " " not in r.user_id
        assert " " not in r.system_id

    def test_sanitize_id_none(self):
        r = BatchEmbeddingRequest(texts=["a"], user_id="u1", system_id=None)
        assert r.system_id is None


class TestEmbeddingQuery:
    def test_basic(self):
        q = EmbeddingQuery(query="hello")
        assert q.query == "hello"
        assert q.limit == 10
        assert q.threshold == 0.0

    def test_sanitize_query_strips_control_chars(self):
        q = EmbeddingQuery(query="hi\x00there")
        assert "\x00" not in q.query

    def test_sanitize_query_keeps_newlines_tabs(self):
        q = EmbeddingQuery(query="hi\nthere\tx")
        assert "\n" in q.query
        assert "\t" in q.query

    def test_sanitize_query_doubles_quotes(self):
        q = EmbeddingQuery(query="O'Reilly")
        assert "''" in q.query

    def test_sanitize_query_normalizes_unicode(self):
        q = EmbeddingQuery(query="½")
        # NFKC -> 1⁄2
        assert q.query == "1⁄2"

    def test_limit_bounds(self):
        with pytest.raises(Exception):
            EmbeddingQuery(query="x", limit=0)
        with pytest.raises(Exception):
            EmbeddingQuery(query="x", limit=1001)

    def test_threshold_bounds(self):
        with pytest.raises(Exception):
            EmbeddingQuery(query="x", threshold=-0.1)
        with pytest.raises(Exception):
            EmbeddingQuery(query="x", threshold=1.1)

    def test_min_length_query(self):
        with pytest.raises(Exception):
            EmbeddingQuery(query="")

    def test_max_length_query(self):
        with pytest.raises(Exception):
            EmbeddingQuery(query="x" * 10_001)


# -----------------------------------------------------------------------------
# Configs
# -----------------------------------------------------------------------------


class TestRateLimitConfig:
    def test_defaults(self):
        c = RateLimitConfig()
        assert c.max_batch_size == 100
        assert c.max_text_length == 100_000
        assert c.max_concurrent == 5
        assert c.timeout_seconds == 60.0


class TestBudgetConfig:
    def test_defaults(self):
        c = BudgetConfig()
        assert c.enabled is False
        assert c.daily_limit == 1_000_000
        assert c.alert_threshold == 0.8


# -----------------------------------------------------------------------------
# SecureEmbeddingService
# -----------------------------------------------------------------------------


class TestSecureEmbeddingService:
    def test_init_defaults(self):
        s = SecureEmbeddingService()
        assert s._rate_limit.max_concurrent == 5
        assert s._budget.enabled is False

    def test_hash_text_stable(self):
        s = SecureEmbeddingService()
        h1 = s._hash_text("hello")
        h2 = s._hash_text("hello")
        assert h1 == h2
        assert len(h1) == 64  # sha256 hex

    def test_hash_text_different_inputs(self):
        s = SecureEmbeddingService()
        assert s._hash_text("a") != s._hash_text("b")

    def test_check_rate_limit_allows_under_threshold(self):
        s = SecureEmbeddingService()
        for _ in range(5):
            assert s._check_rate_limit("u1") is True

    def test_check_rate_limit_blocks_at_100(self):
        s = SecureEmbeddingService()
        # Pre-fill the user with 100 timestamps
        s._request_counts["u1"] = [time.time()] * 100
        assert s._check_rate_limit("u1") is False

    def test_check_rate_limit_different_users(self):
        s = SecureEmbeddingService()
        for _ in range(100):
            s._check_rate_limit("u1")
        # u2 should still be allowed
        assert s._check_rate_limit("u2") is True

    def test_check_rate_limit_clears_old_timestamps(self):
        s = SecureEmbeddingService()
        # Old timestamps beyond 60s window
        s._request_counts["u1"] = [time.time() - 120.0] * 200
        assert s._check_rate_limit("u1") is True
        assert len(s._request_counts["u1"]) == 1

    async def test_embed_secure_success(self):
        s = SecureEmbeddingService()
        s._service = MagicMock()
        s._service.embed = AsyncMock(
            return_value=EmbeddingResult([[0.1, 0.2]], "m", EmbeddingProvider.FASTEMBED)
        )
        req = EmbeddingRequest(text="hi", user_id="u1")
        r = await s.embed_secure(req)
        assert len(r.embeddings) == 1

    async def test_embed_secure_rate_limited(self):
        s = SecureEmbeddingService()
        s._request_counts["u1"] = [time.time()] * 100
        req = EmbeddingRequest(text="hi", user_id="u1")
        with pytest.raises(ServiceOverloadedError):
            await s.embed_secure(req)

    async def test_embed_batch_secure_empty_chunk_processed(self):
        s = SecureEmbeddingService()
        s._service = MagicMock()
        s._service.embed = AsyncMock(
            return_value=EmbeddingResult([[0.0, 0.1]], "m", EmbeddingProvider.FASTEMBED)
        )
        req = BatchEmbeddingRequest(texts=["a", "b", "c"], user_id="u1")
        results = await s.embed_batch_secure(req)
        # 3 texts / 10 chunk_size = 1 chunk
        assert len(results) == 1
        assert isinstance(results[0], EmbeddingResult)

    async def test_embed_batch_secure_multiple_chunks(self):
        s = SecureEmbeddingService()
        s._service = MagicMock()
        s._service.embed = AsyncMock(
            return_value=EmbeddingResult([[0.0]], "m", EmbeddingProvider.FASTEMBED)
        )
        texts = [f"text-{i}" for i in range(25)]
        req = BatchEmbeddingRequest(texts=texts, user_id="u1")
        results = await s.embed_batch_secure(req)
        # 25/10 = 3 chunks
        assert len(results) == 3

    async def test_embed_batch_secure_oversize_raises(self):
        s = SecureEmbeddingService()
        s._request_counts["u1"] = [time.time()] * 100
        # Build a request that is *just* over the rate limit; we need the
        # service to raise ServiceOverloadedError on rate-limit even when the
        # batch size check would otherwise pass.
        req = BatchEmbeddingRequest(texts=["a"], user_id="u1")
        with pytest.raises(ServiceOverloadedError):
            await s.embed_batch_secure(req)

    async def test_embed_batch_secure_handles_chunk_failure(self):
        s = SecureEmbeddingService()
        s._service = MagicMock()
        s._service.embed = AsyncMock(side_effect=RuntimeError("chunk fail"))
        req = BatchEmbeddingRequest(texts=["a", "b"], user_id="u1")
        results = await s.embed_batch_secure(req)
        assert len(results) == 1
        assert isinstance(results[0], RuntimeError)

    async def test_embed_batch_secure_rate_limited(self):
        s = SecureEmbeddingService()
        s._request_counts["u1"] = [time.time()] * 100
        req = BatchEmbeddingRequest(texts=["a"], user_id="u1")
        with pytest.raises(ServiceOverloadedError):
            await s.embed_batch_secure(req)

    async def test_embed_batch_secure_oversize_batch_via_rate_limit(self):
        s = SecureEmbeddingService()
        # Reduce rate limit's max_batch_size to 1
        s._rate_limit = RateLimitConfig(max_batch_size=1)
        # Build a request with 2 texts -- the Pydantic max_length=100 is the
        # real limit, but we want to exercise the runtime check that the
        # service does. Build a manually-constructed request object.

        # Pydantic max_length=100 on texts allows up to 100; we just need
        # enough to exceed the runtime max_batch_size=1 but Pydantic still
        # accepts 2. We construct the model with `model_construct` to skip
        # validation, then call the service.
        req = BatchEmbeddingRequest.model_construct(texts=["a", "b"], user_id="u1", system_id=None)
        # rate limit is 100/min; ensure not blocked
        assert s._check_rate_limit(req.user_id) is True
        with pytest.raises(ServiceOverloadedError):
            await s.embed_batch_secure(req)


class TestGetSecureEmbeddingService:
    def test_singleton(self):
        import mahavishnu.core.embeddings as mod

        mod._secure_service = None
        a = get_secure_embedding_service()
        b = get_secure_embedding_service()
        assert a is b
        mod._secure_service = None
