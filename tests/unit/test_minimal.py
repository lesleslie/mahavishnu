"""Minimal adapter test."""

def test_simple():
    from mahavishnu.engines.llamaindex_adapter_impl import LlamaIndexAdapter
    adapter = LlamaIndexAdapter()
    assert adapter.name == "llamaindex"
