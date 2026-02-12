"""Minimal adapter test."""

def test_simple():
    from mahavishnu.adapters.rag.llamaindex_adapter import LlamaIndexAdapter
    adapter = LlamaIndexAdapter()
    assert adapter.name == "llamaindex"
