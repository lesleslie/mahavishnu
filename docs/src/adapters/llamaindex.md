# LlamaIndex Adapter

The LlamaIndex adapter provides integration with LlamaIndex for RAG (Retrieval-Augmented Generation) pipelines and knowledge bases.

**Current Status**: Fully implemented (348 lines) with real Ollama integration

## Overview

LlamaIndex is ideal for creating RAG pipelines with document ingestion, vector embeddings, and semantic search capabilities.

## Configuration

```yaml
llamaindex:
  enabled: true
  llm_model: "nomic-embed-text"  # Ollama embedding model
  ollama_base_url: "http://localhost:11434"
```

## Usage

The LlamaIndex adapter is fully functional:

```bash
# Ingest documents from a repository
mahavishnu ingest --repo /path/to/repo --adapter llamaindex

# Query for semantic search
mahavishnu query --query "authentication patterns" --adapter llamaindex
```

## Features

- Repository/document ingestion from `repos.yaml`
- Vector embeddings with Ollama (local models)
- Document chunking and indexing
- Semantic search across codebases
- Integration with AI agents for knowledge bases

## Current Implementation

**Status**: Fully implemented (348 lines)

The adapter includes real Ollama integration:

- Ollama embedding model integration (`nomic-embed-text`)
- Ollama LLM integration for generation
- Document processing and chunking
- Vector store operations
- Semantic search queries
- Integration with Mahavishnu configuration system

## Example: Document Ingestion

```python
from mahavishnu.engines import LlamaIndexAdapter

adapter = LlamaIndexAdapter(config={
    "llm_model": "nomic-embed-text",
    "ollama_base_url": "http://localhost:11434"
})

# Ingest documents
result = await adapter.ingest_documents(
    repo_path="/path/to/repo",
    document_types=["py", "md", "txt"]
)

# Query for semantic search
results = await adapter.query_documents(
    query="authentication patterns",
    repo_path="/path/to/repo",
    top_k=5
)
```

## Production Ready

This adapter is ready for production use with:

- Real Ollama integration (not simulated)
- Comprehensive error handling
- Configuration-based model selection
- Support for multiple document types
- Semantic search with relevance scoring

## See Also
