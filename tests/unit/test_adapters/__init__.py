"""Test suite for Mahavishnu orchestration adapters.

This package contains comprehensive tests for all adapter implementations:
- AgnoAdapter: Agent-based orchestration with LLM integration
- PrefectAdapter: Flow-based orchestration with Prefect
- LlamaIndexAdapter: RAG pipelines with vector embeddings

Test coverage includes:
- Adapter initialization and configuration
- Task execution (code sweep, quality check, etc.)
- Error handling and retry logic
- Health checks
- Concurrent processing
- Integration scenarios
- Edge cases
"""
