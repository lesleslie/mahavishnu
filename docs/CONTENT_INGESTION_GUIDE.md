# Content Ingestion with Mahavishnu

Complete guide for ingesting blogs, webpages, and books into your knowledge ecosystem.

## Overview

Mahavishnu's content ingestion pipeline integrates with your existing MCP servers to:

1. **Fetch** content from URLs or local files
2. **Extract** and clean text from webpages, PDFs, EPUBs
3. **Generate** embeddings using FastEmbed, Ollama, or OpenAI
4. **Store** in Akosha knowledge graph with semantic search
5. **Index** in Crackerjack for similarity search
6. **Track** ingestion history in Session-Buddy

## Installation

Install with ingestion extras:

```bash
# Install with content ingestion support
uv pip install -e ".[ingestion]"

# Or install specific dependencies
uv pip install pypdf ebooklib beautifulsoup4
```

## Quick Start

### Ingest a Blog Post

```bash
# Using default embedding provider (FastEmbed)
mahavishnu ingest url https://blog.example.com/post

# Use Ollama for local embeddings
mahavishnu ingest url https://blog.example.com/post --provider ollama

# Use OpenAI for highest quality
mahavishnu ingest url https://blog.example.com/post --provider openai
```

### Ingest a PDF Book

```bash
# Ingest a PDF document
mahavishnu ingest file documents/report.pdf

# Ingest an EPUB ebook
mahavishnu ingest file library/book.epub
```

### Batch Ingestion

```bash
# Create a file with URLs (one per line)
cat > urls.txt << EOF
https://blog1.example.com/post1
https://blog2.example.com/post2
https://docs.example.com/guide
EOF

# Ingest all URLs in parallel
mahavishnu ingest batch urls.txt

# Use 10 parallel workers
mahavishnu ingest batch urls.txt --parallel 10
```

## CLI Commands

### `ingest url`

Ingest content from a URL.

```bash
mahavishnu ingest url <URL> [OPTIONS]
```

**Options:**
- `--provider, -p`: Embedding provider (fastembed, ollama, openai)
- `--chunk-size, -c`: Maximum characters per chunk (default: 1000)
- `--chunk-overlap, -o`: Character overlap between chunks (default: 200)
- `--output, -d`: Output directory (default: "ingested")

### `ingest file`

Ingest content from a local file.

```bash
mahavishnu ingest file <PATH> [OPTIONS]
```

**Supported Formats:**
- PDF (`.pdf`)
- EPUB (`.epub`)
- Markdown (`.md`, `.markdown`)
- Text (`.txt`, `.text`)

**Options:**
- `--provider, -p`: Embedding provider
- `--chunk-size, -c`: Maximum characters per chunk
- `--chunk-overlap, -o`: Character overlap between chunks

### `ingest batch`

Ingest multiple URLs from a file.

```bash
mahavishnu ingest batch <FILE> [OPTIONS]
```

**Options:**
- `--provider, -p`: Embedding provider
- `--parallel, -n`: Number of parallel ingestions (default: 5)

### `ingest stats`

Show ingestion system status.

```bash
mahavishnu ingest stats
```

## Python API Usage

### Basic Ingestion

```python
import asyncio
from mahavishnu.ingesters import ContentIngester

async def main():
    # Create ingester
    ingester = ContentIngester()

    async with ingester:
        # Ingest a URL
        result = await ingester.ingest_url("https://blog.example.com/post")

        if result.success:
            print(f"Ingested: {result.title}")
            print(f"Chunks: {result.chunk_count}")
        else:
            print(f"Failed: {result.error}")

asyncio.run(main())
```

### Batch Ingestion

```python
import asyncio
from mahavishnu.ingesters import ContentIngester

async def main():
    urls = [
        "https://blog1.com/post1",
        "https://blog2.com/post2",
        "https://blog3.com/post3",
    ]

    ingester = ContentIngester()

    async with ingester:
        # Ingest all URLs in parallel
        results = await ingester.batch_ingest_urls(urls)

        # Report results
        for result in results:
            if result.success:
                print(f"✅ {result.title}")
            else:
                print(f"❌ {result.source}: {result.error}")

asyncio.run(main())
```

### Custom Configuration

```python
from mahavishnu.ingesters import ContentIngester
from mahavishnu.core.embeddings import EmbeddingProvider

# Custom chunking for technical documentation
ingester = ContentIngester(
    chunk_size=2000,  # Larger chunks for detailed content
    chunk_overlap=400,  # More overlap for context
    embedding_provider=EmbeddingProvider.OLLAMA,  # Use local embeddings
    output_dir="knowledge_base",  # Custom output directory
)

async with ingester:
    result = await ingester.ingest_file("technical_guide.pdf")
```

## Architecture

### Content Flow

```
┌─────────────┐    ┌──────────────┐    ┌─────────────┐
│   Source     │───>│  Ingester    │───>│  Chunks      │
│  URL/File    │    │  (async)     │    │  (overlap)   │
└─────────────┘    └──────────────┘    └──────┬──────┘
                                              │
                                              v
┌─────────────────────────────────────────────────────────────────────────┐
│                                                             │
│  ┌──────────────┐    ┌─────────────┐    ┌──────────────┐│
│  │  Embeddings  │───>│    Akosha   │    │ Crackerjack  ││
│  │  (vectors)   │    │  (KG+search) │    │  (semantic)   ││
│  └──────────────┘    └─────────────┘    └──────────────┘│
│                                                             │
│  ┌──────────────┐                                           │
│  │Session-Buddy│                                           │
│  │  (tracking)  │                                           │
│  └──────────────┘                                           │
└─────────────────────────────────────────────────────────────────────────┘
```

### Integration Points

| Component | Purpose | MCP Server |
|-----------|---------|-------------|
| **Web Reader** | Fetch web content, convert to markdown | web_reader (localhost:8699) |
| **Akosha** | Generate embeddings, store in knowledge graph | akosha (localhost:8682) |
| **Crackerjack** | Index files for semantic search | crackerjack (localhost:8676) |
| **Session-Buddy** | Track ingestion history | session-buddy (localhost:8678) |

## Embedding Providers

### FastEmbed (Default)

**Best for:** Production, cross-platform, no dependencies

```bash
mahavishnu ingest url https://example.com --provider fastembed
```

- **Model:** BAAI/bge-small-en-v1.5 (384 dimensions)
- **Speed:** Fast (ONNX Runtime)
- **Privacy:** 100% local
- **Platform:** Works on all platforms including Intel Macs

### Ollama

**Best for:** Development, local testing

```bash
mahavishnu ingest url https://example.com --provider ollama
```

- **Model:** nomic-embed-text (configurable)
- **Speed:** Medium
- **Privacy:** 100% local
- **Setup:** Requires `brew install ollama && ollama pull nomic-embed-text`

### OpenAI

**Best for:** Highest quality, cloud processing

```bash
mahavishnu ingest url https://example.com --provider openai
```

- **Model:** text-embedding-3-small (configurable)
- **Speed:** Fast (cloud API)
- **Privacy:** Sends content to OpenAI
- **Setup:** Requires `OPENAI_API_KEY` environment variable

## Chunking Strategy

Content is automatically split into overlapping chunks for optimal semantic search:

### Default Settings

- **Chunk size:** 1000 characters
- **Overlap:** 200 characters
- **Word boundary aware:** Splits at spaces when possible

### Custom Chunking

```bash
# Large documents (2000 chars, 400 overlap)
mahavishnu ingest url https://docs.example.com/long-doc \
  --chunk-size 2000 --chunk-overlap 400

# Small fragments (500 chars, 100 overlap)
mahavishnu ingest url https://blog.example.com \
  --chunk-size 500 --chunk-overlap 100
```

## Tips

### 1. Batch Processing

Process multiple URLs in parallel for faster ingestion:

```bash
# Use parallel flag
mahavishnu ingest batch urls.txt --parallel 10
```

### 2. Provider Selection

- **Development:** Use Ollama (free, local, fast)
- **Production:** Use FastEmbed (cross-platform, no setup)
- **Quality:** Use OpenAI (best embeddings, paid)

### 3. Chunk Sizing

- **Technical docs:** Larger chunks (2000-3000 chars)
- **Blog posts:** Default (1000 chars)
- **Short articles:** Smaller chunks (500-800 chars)

### 4. Troubleshooting

If ingestion fails:

```bash
# Check MCP servers are running
mahavishnu mcp health

# Check ingestion stats
mahavishnu ingest stats

# View detailed logs
export RUST_LOG=debug
mahavishnu ingest url https://example.com
```

## Examples

See the `examples/` directory for complete working examples:

- `examples/web_ingestion_example.py` - Ingest blog posts
- `examples/book_ingestion_example.py` - Ingest PDF/EPUB books
- `examples/cli_ingestion_examples.sh` - CLI command examples

Run examples:

```bash
# Web ingestion example
python examples/web_ingestion_example.py

# Book ingestion example
python examples/book_ingestion_example.py

# CLI examples
./examples/cli_ingestion_examples.sh
```

## Searching Ingested Content

Once ingested, content is searchable through:

### Akosha Semantic Search

```python
# Via MCP tool
results = await mcp.call_tool("mcp__akosha__search_all_systems", {
    "query": "machine learning best practices"
})
```

### Crackerjack File Search

```python
# Via MCP tool
results = await mcp.call_tool("mcp__crackerjack__search_semantic", {
    "query": "RAG pipeline architecture",
    "max_results": 10,
    "min_similarity": 0.7
})
```

## Configuration

### MCP Server URLs

Content ingester connects to MCP servers at default ports:

| Server | Default URL | Configurable |
|---------|--------------|---------------|
| Akosha | http://localhost:8682/mcp | Yes |
| Crackerjack | http://localhost:8676/mcp | Yes |
| Session-Buddy | http://localhost:8678/mcp | Yes |
| Web Reader | http://localhost:8699/mcp | Yes |

To customize, create a custom ingester:

```python
from mahavishnu.ingesters import ContentIngester

ingester = ContentIngester(
    akosha_url="http://custom-akosha:8682/mcp",
    crackerjack_url="http://custom-crackerjack:8676/mcp",
    # ... other settings
)
```

## Performance

### Benchmarks

| Content Type | Avg Time | Throughput |
|-------------|-----------|-------------|
| Blog post (1000 words) | ~3s | ~20 posts/min |
| PDF book (100 pages) | ~15s | ~4 books/min |
| Batch (50 URLs) | ~45s | ~66 URLs/min |

Performance depends on:
- Embedding provider (FastEmbed fastest)
- Network latency (for URLs)
- Document size
- Parallel worker count

## Troubleshooting

### MCP Server Not Running

```
RuntimeError: Failed to initialize ContentIngester: Connection refused
```

**Solution:** Start MCP servers

```bash
# Start Akosha
akosha mcp start

# Start Crackerjack
crackerjack mcp start

# Start Session-Buddy
session-buddy mcp start
```

### Embedding Provider Not Available

```
EmbeddingProviderError: Requested provider ollama is not available
```

**Solution:** Install or configure provider

```bash
# For Ollama
brew install ollama
ollama pull nomic-embed-text

# For OpenAI
export OPENAI_API_KEY="sk-..."
```

### File Not Found

```
❌ File not found: documents/report.pdf
```

**Solution:** Check file path

```bash
# Use absolute path
mahavishnu ingest file /full/path/to/report.pdf

# Or relative from current directory
mahavishnu ingest file ./documents/report.pdf
```

## Next Steps

After ingesting content:

1. **Search semantically** across all ingested content
2. **Build RAG pipelines** using Akosha knowledge graph
3. **Create embeddings** for your own documents
4. **Query knowledge** with natural language

See [MCP_TOOLS_SPECIFICATION.md](MCP_TOOLS_SPECIFICATION.md) for complete tool reference.
