"""Embedding shim — delegates to oneiric.

The original implementation in this file owned its own mock-only
``EmbeddingService`` with explicit provider selection
(``EmbeddingProvider.FASTEMBED | OLLAMA | OPENAI``). After the hybrid
chain refactor in oneiric
(``oneiric/docs/plans/2026-08-22-hybrid-embeddings-design.md``), the
canonical embedding service lives in
``oneiric.adapters.observability.embeddings.EmbeddingService``.

This shim:

- Keeps the public import path for any caller that imports
  ``mahavishnu.core.embeddings``
- Re-exports ``EmbeddingProvider`` (kept as a deprecated enum so old
  ``--provider fastembed|ollama|openai`` CLI flags don't break)
- Re-exports ``cosine_similarity``, ``euclidean_distance``, the error
  classes, and the Pydantic models unchanged
- Replaces ``EmbeddingService.embed`` with a oneiric-backed
  implementation that uses the 5-backend probe chain
  (llama_cpp → ollama → minimax → model2vec → mock)

Future work: remove the provider enum, drop the explicit ``--provider``
CLI flag, and prune the now-unreachable provider classes
(``FastEmbedProvider``, ``OllamaProvider``, ``OpenAIProvider``). For
now they remain importable but the public ``EmbeddingService.embed``
path is the oneiric chain.
"""

from __future__ import annotations

import logging
from enum import StrEnum
from typing import Any

import numpy as np

from oneiric.adapters.observability.embedding_settings import (
    EmbeddingSettings as _OneiricEmbeddingSettings,
)
from oneiric.adapters.observability.embeddings import (
    EmbeddingService as _OneiricEmbeddingService,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Re-export legacy types for backward compatibility
# ---------------------------------------------------------------------------


class EmbeddingProvider(StrEnum):
    """Legacy provider sentinel. Retained for backward-compatible imports.

    The actual backend selection now happens inside oneiric's
    probe chain (llama_cpp → ollama → minimax → model2vec → mock).
    See ``oneiric/docs/plans/2026-08-22-hybrid-embeddings-design.md``.

    Use ``EmbeddingSettings`` from
    ``oneiric.adapters.observability.embedding_settings`` to configure
    which legs participate in the probe chain.
    """

    FASTEMBED = "fastembed"
    OLLAMA = "ollama"
    OPENAI = "openai"


# Error types — kept so callers that ``except EmbeddingServiceError``
# continue to work.
class EmbeddingServiceError(Exception):
    """Base exception for embedding errors."""


class EmbeddingProviderError(EmbeddingServiceError):
    """Raised when a specific provider fails."""


# ---------------------------------------------------------------------------
# Lightweight data containers (preserved for backward compatibility)
# ---------------------------------------------------------------------------


class EmbeddingResult:
    """Result envelope returned by ``EmbeddingService.embed``.

    Retained for backward compatibility. New code should use
    ``oneiric.adapters.observability.embeddings.EmbeddingService``
    directly and read ``backend_name()`` / ``dimension()`` /
    ``is_available()`` from the service.
    """

    def __init__(
        self,
        embeddings: list[list[float]],
        provider: EmbeddingProvider | str | None = None,
        model: str | None = None,
        dimension: int | None = None,
    ) -> None:
        self.embeddings = embeddings
        self.provider = provider
        self.model = model
        self.dimension = dimension or (len(embeddings[0]) if embeddings else 0)

    def __repr__(self) -> str:
        return (
            f"EmbeddingResult(embeddings={len(self.embeddings)} vectors, "
            f"dimension={self.dimension}, provider={self.provider!r}, "
            f"model={self.model!r})"
        )


# ---------------------------------------------------------------------------
# Helpers (unchanged — pure-Python / numpy, no external deps)
# ---------------------------------------------------------------------------


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two equal-length vectors."""
    arr_a = np.asarray(a, dtype=np.float32)
    arr_b = np.asarray(b, dtype=np.float32)
    return float(np.dot(arr_a, arr_b))


def euclidean_distance(a: list[float], b: list[float]) -> float:
    """Euclidean (L2) distance between two equal-length vectors."""
    arr_a = np.asarray(a, dtype=np.float32)
    arr_b = np.asarray(b, dtype=np.float32)
    return float(np.linalg.norm(arr_a - arr_b))


# ---------------------------------------------------------------------------
# EmbeddingService — delegates to oneiric's hybrid chain
# ---------------------------------------------------------------------------


class EmbeddingService(_OneiricEmbeddingService):
    """Backwards-compatible ``EmbeddingService`` that delegates to oneiric.

    The original constructor accepted ``provider=``, ``model_name=``,
    ``auto_fallback=``, and ``circuit_breaker_config=`` for explicit
    provider selection. Those kwargs are now retained for API
    compatibility but ignored — the active backend is selected by
    oneiric's probe chain at ``initialize()`` time.

    The ``embed()`` method continues to return an ``EmbeddingResult``
    envelope so legacy callers don't need to change.
    """

    def __init__(
        self,
        provider: EmbeddingProvider | str | None = None,
        model_name: str | None = None,
        auto_fallback: bool = True,
        circuit_breaker_config: dict[str, Any] | None = None,
    ) -> None:
        # The new chain always tries the most-preferred leg first; we
        # accept ``provider`` for backward compatibility but it has no
        # effect on backend selection. Settings stay at defaults.
        settings = _OneiricEmbeddingSettings()
        super().__init__(settings=settings, model_name=model_name)
        # Auto-initialize lazily on first call.
        self._initialized: bool = False
        # Stash ignored kwargs for callers reading the instance after
        # construction (debugging aid).
        self._legacy_provider = provider
        self._legacy_circuit_breaker_config = circuit_breaker_config
        self._legacy_auto_fallback = auto_fallback

    async def _ensure_initialized(self) -> None:
        if not self._initialized:
            await self.initialize()
            self._initialized = True

    async def embed(
        self,
        texts: list[str],
        **_kwargs: Any,
    ) -> EmbeddingResult:
        """Embed a batch of texts via the oneiric chain.

        Returns an ``EmbeddingResult`` for backward compatibility. The
        ``provider`` and ``model`` fields are filled from the active
        backend (``self.backend_name()``) since the chain no longer
        has a single configured provider.
        """
        await self._ensure_initialized()
        try:
            vectors = await self.encode_batch(list(texts))
        except (RuntimeError, OSError, ValueError) as exc:
            raise EmbeddingServiceError(str(exc)) from exc
        embeddings = [v.tolist() for v in vectors]
        return EmbeddingResult(
            embeddings=embeddings,
            provider=self.backend_name(),
            model=self.backend_name(),
            dimension=self.dimension(),
        )


# ---------------------------------------------------------------------------
# Singleton factory (legacy API)
# ---------------------------------------------------------------------------


_embedding_service: EmbeddingService | None = None


def get_embedding_service() -> EmbeddingService:
    """Return the process-wide singleton embedding service.

    Backwards-compatible factory retained for callers that
    imported ``mahavishnu.core.embeddings.get_embedding_service``.
    """
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService()
    return _embedding_service


__all__ = [
    "EmbeddingProvider",
    "EmbeddingResult",
    "EmbeddingService",
    "EmbeddingServiceError",
    "EmbeddingProviderError",
    "cosine_similarity",
    "euclidean_distance",
    "get_embedding_service",
]
