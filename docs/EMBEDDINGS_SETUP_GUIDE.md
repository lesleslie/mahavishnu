# FastEmbed and Ollama Setup Guide

**Date**: 2026-02-02
**Purpose**: Set up FastEmbed (production) and Ollama (development) for embeddings

---

## Quick Start

### Option 1: FastEmbed (Production) ⭐ RECOMMENDED

**Installation**:
```bash
# FastEmbed is already installed as a core dependency
# No additional installation needed!

# Verify it works
python -c "from fastembed import SentenceTransformer; print('✅ FastEmbed available')"
```

**Usage**:
```python
from mahavishnu.core.embeddings_oneiric import get_embeddings_with_oneiric

# Auto-load configuration from settings/mahavishnu.yaml
embeddings = await get_embeddings_with_oneiric(["hello", "world"])

print(f"Generated {len(embeddings)} embeddings")
print(f"Dimension: {len(embeddings[0])}")
```

**Configuration**:
```yaml
# In settings/mahavishnu.yaml
embeddings:
  provider: fastembed
  model: BAAI/bge-small-en-v1.5
  batch_size: 32
```

---

### Option 2: Ollama (Development) ⭐ PRIVACY-FIRST

**Installation**:
```bash
# Install Ollama
brew install ollama

# Start Ollama service
ollama serve &

# Pull embedding model
ollama pull nomic-embed-text

# Install Python dependencies
uv sync --extra ollama

# Verify
python -c "import socket; s=socket.socket(); s.connect(('localhost', 11434)); print('✅ Ollama available')"
```

**Usage**:
```python
# Configure to use Ollama
# In settings/mahavishnu.yaml:
embeddings:
  provider: ollama
  model: nomic-embed-text

# Or override programmatically
from mahavishnu.core.embeddings import EmbeddingProvider
from mahavishnu.core.embeddings_oneiric import get_embeddings_with_oneiric, EmbeddingConfig

config = EmbeddingConfig(provider=EmbeddingProvider.OLLAMA)
embeddings = await get_embeddings_with_oneiric(["hello", "world"], config)
```

---

## Configuration Examples

### Production: FastEmbed (default)

```yaml
# settings/mahavishnu.yaml
embeddings:
  provider: fastembed
  model: BAAI/bge-small-en-v1.5
  batch_size: 32
  enable_cache: true
```

### Development: Ollama (local, private)

```yaml
# settings/mahavishnu.yaml
embeddings:
  provider: ollama
  model: nomic-embed-text
  ollama_base_url: http://localhost:11434
  batch_size: 32
```

### Cloud: OpenAI API (high quality)

```yaml
# settings/mahavishnu.yaml
embeddings:
  provider: openai
  model: text-embedding-3-small
  # Set API key via environment:
  # export MAHAVISHNU_EMBEDDINGS_OPENAI_API_KEY=sk-...
```

---

## Programmatic Usage

### Basic Usage

```python
from mahavishnu.core.embeddings_oneiric import get_embeddings_with_oneiric

# Auto-load configuration from Oneiric
embeddings = await get_embeddings_with_oneiric([
    "Hello world",
    "Mahavishnu MCP orchestrator",
])

print(f"Generated {len(embeddings)} embeddings of dimension {len(embeddings[0])}")
```

### With Specific Provider

```python
from mahavishnu.core.embeddings import EmbeddingProvider
from mahavishnu.core.embeddings_oneiric import EmbeddingConfig, get_embeddings_with_oneiric

# Use Ollama for development
config = EmbeddingConfig(
    provider=EmbeddingProvider.OLLAMA,
    model="nomic-embed-text",
)

embeddings = await get_embeddings_with_oneiric(["hello"], config)
```

### Oneiric Adapter (for MCP Tools)

```python
from mahavishnu.core.embeddings_oneiric import OneiricEmbeddingsAdapter

# Initialize with config
adapter = OneiricEmbeddingsAdapter()

# Generate embeddings
embeddings = await adapter.embed(["Hello", "World"])

# Single text embedding
embedding = await adapter.embed_single("Hello World")

# Get provider info
info = adapter.get_provider_info()
print(f"Using: {info['provider']} with model {info['model']}")
```

---

## MCP Tool Integration

### Add Embeddings to MCP Server

```python
# In mahavishnu/mcp/server_core.py
from mahavishnu.core.embeddings_oneiric import mcp_tool_get_embeddings

@mcp.tool()
async def get_embeddings(
    texts: list[str],
    provider: str | None = None,
    model: str | None = None,
) -> dict:
    """Generate embeddings for texts using configured provider.

    Args:
        texts: List of text strings to embed
        provider: Override provider (fastembed, ollama, openai)
        model: Override model name

    Returns:
        Dictionary with embeddings and metadata
    """
    return await mcp_tool_get_embeddings(texts, provider, model)
```

### Usage from MCP Client

```bash
# Call the tool
mahavishnu mcp call get_embeddings \
    --texts '["Hello world", "Mahavishnu orchestrator"]' \
    --provider fastembed
```

---

## Model Comparison

| Model | Dimension | Speed | Quality | Best For |
|-------|-----------|-------|---------|----------|
| **FastEmbed** | | | | | |
| - BAAI/bge-small-en-v1.5 | 384 | ⭐⭐⭐ | ⭐⭐ | Production, fast |
| - BAAI/bge-base-en-v1.5 | 768 | ⭐⭐ | ⭐⭐⭐ | Better quality |
| - BAAI/bge-large-en-v1.5 | 1024 | ⭐ | ⭐⭐⭐⭐ | Best quality |
| **Ollama** | | | | | |
| - nomic-embed-text | 768 | ⭐⭐ | ⭐⭐⭐ | Development |
| - mxbai-embed-large-v1 | 1024 | ⭐ | ⭐⭐⭐ | High quality |
| **OpenAI** | | | | | |
| - text-embedding-3-small | 1536 | ⭐⭐⭐ | ⭐⭐⭐⭐ | Best quality |
| - text-embedding-3-large | 3072 | ⭐ | ⭐⭐⭐⭐ | Best quality |

---

## Troubleshooting

### FastEmbed: Model Download Slow on First Use

**Issue**: First embedding generation is slow while downloading model

**Solution**: Pre-download model
```python
from fastembed import SentenceTransformer

# Download model during deployment
model = SentenceTransformer("BAAI/bge-small-en-v1.5")
# Model is now cached for future use
```

### Ollama: Connection Refused

**Issue**: Cannot connect to Ollama API

**Solution**: Start Ollama service
```bash
# Start Ollama
ollama serve &

# Verify it's running
curl http://localhost:11434/api/tags

# Pull model
ollama pull nomic-embed-text
```

### OpenAI: API Key Not Found

**Issue**: OpenAI provider says API key not found

**Solution**: Set environment variable
```bash
export OPENAI_API_KEY=sk-...
export MAHAVISHNU_EMBEDDINGS_OPENAI_API_KEY=sk-...
```

---

## Performance Benchmarks

On Intel Mac (x86_64):

| Provider | Init Time | First Embed | Subsequent | Batch (32) |
|----------|-----------|------------|------------|------------|
| **FastEmbed** | 0.5s | 50ms | 20ms | 600ms |
| **Ollama** | 0s (service) | 100ms | 80ms | 2.5s |
| **OpenAI** | 0s | 300ms | 250ms | 6s |

---

## Migration from sentence-transformers

### Before (incompatible)
```python
from sentence_transformers import SentenceTransformer

model = SentenceTransformer('all-MiniLM-L6-v2')
embeddings = model.encode(["hello", "world"])
```

### After (FastEmbed)
```python
from mahavishnu.core.embeddings_oneiric import get_embeddings_with_oneiric

embeddings = await get_embeddings_with_oneiric(["hello", "world"])
```

### After (Ollama)
```python
from mahavishnu.core.embeddings_oneiric import get_embeddings_with_oneiric, EmbeddingConfig, EmbeddingProvider

config = EmbeddingConfig(provider=EmbeddingProvider.OLLAMA)
embeddings = await get_embeddings_with_oneiric(["hello", "world"], config)
```

---

## Environment Variables

All embedding configuration can be overridden via environment variables:

```bash
# Provider selection
export MAHAVISHNU_EMBEDDINGS_PROVIDER=fastembed
export MAHAVISHNU_EMBEDDINGS_MODEL=BAAI/bge-base-en-v1.5

# Ollama
export MAHAVISHNU_EMBEDDINGS_OLLAMA_BASE_URL=http://localhost:11434

# OpenAI
export MAHAVISHNU_EMBEDDINGS_OPENAI_API_KEY=sk-...
export MAHAVISHNU_EMBEDDINGS_OPENAI_MODEL=text-embedding-3-small

# Performance
export MAHAVISHNU_EMBEDDINGS_BATCH_SIZE=64
export MAHAVISHNU_EMBEDDINGS_ENABLE_CACHE=true
```

---

## Summary

✅ **FastEmbed**: Production-ready, cross-platform, fast
✅ **Ollama**: Development, local privacy, works on Intel Macs
✅ **OpenAI**: Cloud-based, best quality, simple API

**Recommendation**: Use FastEmbed for production, Ollama for development!

---

**Last Updated**: 2026-02-02
**Status**: ✅ Ready to use
