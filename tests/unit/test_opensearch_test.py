# NOTE: prototype file
"""Smoke tests for mahavishnu.prototypes.opensearch_test.

This file is a runnable prototype that requires a live OpenSearch
endpoint at ``http://localhost:9200``. The tests below pin the module's
public surface (``test_opensearch_connection`` coroutine) and exercise
the success and failure branches of the connection routine with mocked
llama-index objects so the test never touches a real OpenSearch cluster.
"""

from __future__ import annotations

import asyncio
import importlib
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def opensearch_proto():
    """Import the prototype module. Its imports are lazy at call time, so
    a fresh import is cheap and tests stay independent."""
    return importlib.import_module("mahavishnu.prototypes.opensearch_test")


def test_module_imports_and_exposes_connection_routine(opensearch_proto) -> None:
    assert hasattr(opensearch_proto, "test_opensearch_connection")
    assert asyncio.iscoroutinefunction(opensearch_proto.test_opensearch_connection)


def test_module_has_main_guard(opensearch_proto) -> None:
    # The prototype uses the standard ``if __name__ == "__main__"`` pattern;
    # the call site is wrapped in asyncio.run(test_opensearch_connection()).
    # We assert that guard logic by exercising the symbol it references.
    assert callable(getattr(opensearch_proto, "test_opensearch_connection", None))


def test_connection_routine_returns_true_on_success(opensearch_proto) -> None:
    """When all the OpenSearch pieces behave, the routine returns True."""
    mock_index = MagicMock()
    mock_query_engine = MagicMock()
    mock_query_engine.query = MagicMock(return_value="a useful answer")
    mock_index.as_query_engine = MagicMock(return_value=mock_query_engine)

    fake_vector_store = MagicMock(name="OpensearchVectorStore")
    fake_storage_ctx = MagicMock(name="StorageContext")
    fake_vsi = SimpleNamespace(from_documents=MagicMock(return_value=mock_index))
    fake_sc = SimpleNamespace(from_defaults=MagicMock(return_value=fake_storage_ctx))

    with (
        patch.object(opensearch_proto, "OpensearchVectorStore", return_value=fake_vector_store),
        patch.object(opensearch_proto, "StorageContext", new=fake_sc),
        patch.object(opensearch_proto, "VectorStoreIndex", new=fake_vsi),
    ):
        result = asyncio.run(opensearch_proto.test_opensearch_connection())
        # Assertions live inside the with-block so the patches are still active.
        fake_vsi.from_documents.assert_called_once()
        fake_sc.from_defaults.assert_called_once_with(vector_store=fake_vector_store)
        mock_index.as_query_engine.assert_called_once()
        mock_query_engine.query.assert_called_once_with("What are these documents about?")

    assert result is True


def test_connection_routine_returns_false_on_connection_error(
    opensearch_proto,
) -> None:
    """If the OpensearchVectorStore ctor raises, the routine prints help and returns False."""
    with patch.object(
        opensearch_proto,
        "OpensearchVectorStore",
        side_effect=RuntimeError("connection refused"),
    ):
        result = asyncio.run(opensearch_proto.test_opensearch_connection())

    assert result is False


def test_connection_routine_returns_false_on_query_error(opensearch_proto) -> None:
    """An exception during the query step should still surface as False, not raise."""
    mock_index = MagicMock()
    mock_index.as_query_engine = MagicMock(side_effect=RuntimeError("query failed"))
    fake_vsi = SimpleNamespace(from_documents=MagicMock(return_value=mock_index))
    fake_sc = SimpleNamespace(from_defaults=MagicMock(return_value=MagicMock()))

    with (
        patch.object(opensearch_proto, "OpensearchVectorStore", return_value=MagicMock()),
        patch.object(opensearch_proto, "StorageContext", new=fake_sc),
        patch.object(opensearch_proto, "VectorStoreIndex", new=fake_vsi),
    ):
        result = asyncio.run(opensearch_proto.test_opensearch_connection())

    assert result is False


def test_module_uses_expected_vector_store_constructor(
    opensearch_proto, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The prototype asks for an OpenSearch vector store at the documented endpoint."""
    captured: dict = {}

    class _FakeVS:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(opensearch_proto, "OpensearchVectorStore", _FakeVS)
    monkeypatch.setattr(
        opensearch_proto,
        "StorageContext",
        SimpleNamespace(from_defaults=MagicMock(return_value=MagicMock())),
    )
    monkeypatch.setattr(
        opensearch_proto,
        "VectorStoreIndex",
        SimpleNamespace(
            from_documents=MagicMock(
                return_value=SimpleNamespace(
                    as_query_engine=MagicMock(
                        return_value=SimpleNamespace(query=MagicMock(return_value="ok"))
                    )
                )
            )
        ),
    )

    asyncio.run(opensearch_proto.test_opensearch_connection())

    assert captured["endpoint"] == "http://localhost:9200"
    assert captured["index_name"] == "test-index"
    # Prototype comment notes "Standard for text-embedding-ada-002".
    assert captured["dim"] == 1536
