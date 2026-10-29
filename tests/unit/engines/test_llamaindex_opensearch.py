"""The OpenSearch vector store's index must be creatable and writable.

Three independent facts about the environment, each of which broke index
creation or the first write, and none of which is visible in the
adapter's own code:

- OpenSearch 3.x removed the ``nmslib`` engine for new indices, and the
  llama-index client defaults to it.
- The ``faiss`` engine needs native shared libraries that the plugin
  artifact does not ship; a write without them kills the node with
  ``UnsatisfiedLinkError``.
- The embedding dimension has to match what the model produces. It was
  hardcoded to 768 (nomic-embed-text) while the local llama-server may
  be serving a different GGUF.
"""

from __future__ import annotations

from typing import Any, Self
from unittest.mock import patch

import pytest

from mahavishnu.engines import llamaindex_adapter_impl as impl


class _Config:
    llm_model = "qwen3.5"
    llama_server_url = "http://localhost:8081"
    opensearch_endpoint = "http://localhost:9200"
    opensearch_index_name = "mahavishnu_code"
    metrics_enabled = False


@pytest.fixture
def captured_client() -> Any:
    """Capture the OpensearchVectorClient construction, do not connect.

    The client is imported INSIDE ``_setup_vector_store``, so the patch
    has to land on the source module, not on the adapter's namespace.
    """
    captured: dict[str, Any] = {}

    class _FakeClient:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    class _FakeStore:
        def __init__(self, client: Any) -> None:
            self.client = client

    with (
        patch("llama_index.vector_stores.opensearch.OpensearchVectorClient", _FakeClient),
        patch("llama_index.vector_stores.opensearch.OpensearchVectorStore", _FakeStore),
    ):
        yield captured


def test_the_engine_is_the_pure_java_one(captured_client: dict[str, Any]) -> None:
    """HNSW, run by Lucene -- not faiss, whose native libs are not shipped.

    The faiss engine needs ``libopensearchknn_faiss_avx2`` and friends.
    The plugin artifact does not contain them, so a write to a faiss
    index kills the OpenSearch node outright.
    """
    impl.LlamaIndexAdapter(config=_Config())

    assert captured_client["engine"] == "lucene"
    assert captured_client["engine"] != "nmslib", (
        "OpenSearch 3.x removed nmslib for new indices; the client's default "
        "cannot be used"
    )


def test_the_dimension_comes_from_the_model_not_a_constant(
    captured_client: dict[str, Any],
) -> None:
    """The index dimension must match the embeddings the model produces.

    A hardcoded 768 is right for nomic-embed-text and wrong for
    everything else; a mismatch rejects every write.
    """
    adapter = impl.LlamaIndexAdapter(config=_Config())
    adapter._embeddings_base_url = "http://localhost:8081/v1"
    adapter._llm_model = "some-model"

    responses = {
        "http://localhost:9200/mahavishnu_code/_mapping": http_status_error(
            404, "http://localhost:9200/mahavishnu_code/_mapping"
        ),
        "http://localhost:8081/v1/embeddings": embedding_response(4096),
    }

    with patch.object(impl.httpx, "Client", _fake_client(responses)):
        assert adapter._resolve_embedding_dim("http://localhost:9200", "mahavishnu_code") == 4096


def test_the_existing_index_mapping_wins(captured_client: dict[str, Any]) -> None:
    """The index's own mapping is authoritative -- it is what writes match.

    Reading it costs one cheap HTTP call, where asking the model costs a
    real embedding call (~1.1s on a local 8B).
    """
    adapter = impl.LlamaIndexAdapter(config=_Config())
    adapter._embeddings_base_url = "http://localhost:8081/v1"
    adapter._llm_model = "some-model"

    responses = {
        "http://localhost:9200/mahavishnu_code/_mapping": mapping_response(768),
    }

    with patch.object(impl.httpx, "Client", _fake_client(responses)):
        assert adapter._resolve_embedding_dim("http://localhost:9200", "mahavishnu_code") == 768


# ---------------------------------------------------------------------------
# fakes
# ---------------------------------------------------------------------------


class _FakeResponse:
    """The slice of ``httpx.Response`` the adapter's HTTP helper uses."""

    def __init__(self, payload: Any = None, error: Exception | None = None) -> None:
        self._payload = payload
        self._error = error

    def raise_for_status(self) -> None:
        if self._error is not None:
            raise self._error

    def json(self) -> Any:
        return self._payload


def _fake_client(responses: dict[str, Any]) -> Any:
    """A stand-in for ``httpx.Client`` that answers from ``responses``.

    The adapter fetches through ``httpx.Client.request``, so the URL it
    asked for is the URL the test asserts on -- an unexpected one is a
    test failure rather than a silent pass.
    """

    class _Client:
        def __init__(self, **kwargs: Any) -> None:
            self._kwargs = kwargs

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *exc: object) -> None:
            return None

        def request(self, method: str, url: str, **kwargs: Any) -> Any:
            if url not in responses:
                raise AssertionError(f"unexpected url {url!r}")
            return responses[url]

    return _Client


def mapping_response(dimension: int) -> _FakeResponse:
    return _FakeResponse(
        {
            "mahavishnu_code": {
                "mappings": {
                    "properties": {
                        "embedding": {"type": "knn_vector", "dimension": dimension}
                    }
                }
            }
        }
    )


def embedding_response(dimension: int) -> _FakeResponse:
    return _FakeResponse({"data": [{"embedding": [0.0] * dimension}]})


def http_status_error(status: int, url: str) -> _FakeResponse:
    """A response whose ``raise_for_status`` fails -- an index that is absent."""
    request = impl.httpx.Request("GET", url)
    response = impl.httpx.Response(status, request=request)
    return _FakeResponse(
        error=impl.httpx.HTTPStatusError(f"HTTP Error {status}", request=request, response=response)
    )
