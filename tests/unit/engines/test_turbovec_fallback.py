from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def _make_adapter() -> "LlamaIndexAdapter":  # noqa: UP037
    """Return a LlamaIndexAdapter with a minimal mock config."""
    from mahavishnu.engines.llamaindex_adapter_impl import LlamaIndexAdapter

    mock_config = MagicMock()
    mock_config.llamaindex = MagicMock()
    mock_config.llamaindex.opensearch_url = "http://localhost:9200"
    mock_config.llamaindex.opensearch_index = "test-index"
    adapter = LlamaIndexAdapter.__new__(LlamaIndexAdapter)
    adapter.config = mock_config
    adapter.vector_store = None
    adapter._vector_backend = "unset"
    return adapter


@pytest.mark.unit
def test_vector_backend_is_opensearch_when_opensearch_available() -> None:
    """When OpenSearch connects successfully, _vector_backend = 'opensearch'."""
    adapter = _make_adapter()

    mock_store = MagicMock()
    mock_client_cls = MagicMock(return_value=MagicMock())

    with patch(
        "mahavishnu.engines.llamaindex_adapter_impl.OpensearchVectorStore",
        return_value=mock_store,
    ), patch(
        "llama_index.vector_stores.opensearch.OpensearchVectorClient",
        mock_client_cls,
    ):
        adapter._setup_vector_store()

    assert adapter._vector_backend == "opensearch"
    assert adapter.vector_store is mock_store


@pytest.mark.unit
def test_vector_backend_is_turbovec_when_opensearch_unavailable_and_turbovec_installed() -> None:
    """When OpenSearch fails and turbovec is installed, _vector_backend = 'turbovec'."""
    adapter = _make_adapter()
    mock_turbo = MagicMock()

    with patch(
        "mahavishnu.engines.llamaindex_adapter_impl.OpensearchVectorStore",
        side_effect=ConnectionError("OpenSearch down"),
    ), patch.dict(
        "sys.modules",
        {
            "turbovec": MagicMock(),
            "turbovec.integrations": MagicMock(),
            "turbovec.integrations.llamaindex": MagicMock(TurboVec=lambda: mock_turbo),
        },
    ):
        adapter._setup_vector_store()

    assert adapter._vector_backend == "turbovec"
    assert adapter.vector_store is mock_turbo


@pytest.mark.unit
def test_vector_backend_is_memory_implicit_when_neither_available() -> None:
    """When OpenSearch fails and turbovec is absent, _vector_backend = 'memory-implicit'."""
    adapter = _make_adapter()

    with patch(
        "mahavishnu.engines.llamaindex_adapter_impl.OpensearchVectorStore",
        side_effect=ConnectionError("OpenSearch down"),
    ), patch.dict("sys.modules", {"turbovec": None}):
        adapter._setup_vector_store()

    assert adapter._vector_backend == "memory-implicit"
    assert adapter.vector_store is None
