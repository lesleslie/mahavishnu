# Semantic Embeddings Quick Start

## Prerequisites

```bash
# Install Ollama
brew install ollama

# Start Ollama
ollama serve

# Pull embedding model (one-time)
ollama pull nomic-embed-text
```

## Initialization

```bash
# Initialize database (one-time)
python scripts/init_learning_db.py --db-path data/learning.db

# Generate test data (optional)
python3 -c "
import duckdb
conn = duckdb.connect('data/learning.db')
# ... add test records
"
```

## Generate Embeddings

```bash
# Generate embeddings for all records
python scripts/generate_ollama_embeddings.py --db-path data/learning.db

# Regenerate all embeddings
python scripts/generate_ollama_embeddings.py --db-path data/learning.db --regenerate
```

## Test Semantic Search

```bash
# Test search with query
python scripts/generate_ollama_embeddings.py \
  --db-path data/learning.db \
  --test-search "database query optimization"
```

## Programmatic Usage

```python
import duckdb
import httpx

# Setup
conn = duckdb.connect('data/learning.db')
conn.execute("INSTALL vss")
conn.execute("LOAD vss")

# Generate query embedding
async with httpx.AsyncClient() as client:
    response = await client.post(
        "http://localhost:11434/api/embeddings",
        json={"model": "nomic-embed-text", "prompt": "your query"},
    )
    query_emb = response.json()["embedding"]

# Search
array_str = "[" + ",".join(str(x) for x in query_emb) + "]"
results = conn.execute(f"""
    SELECT task_description, list_cosine_similarity(embedding, '{array_str}'::FLOAT[]) as sim
    FROM executions
    WHERE embedding IS NOT NULL
    ORDER BY sim DESC
    LIMIT 10
""").fetchall()
```

## Performance

- **Search Time:** ~8-10ms
- **Embedding Time:** ~400ms
- **Accuracy:** 75-85% similarity
- **Dimensions:** 768 (nomic-embed-text)

## Troubleshooting

**Ollama not running:**

```bash
ollama serve
```

**Model not found:**

```bash
ollama pull nomic-embed-text
```

**Database not initialized:**

```bash
python scripts/init_learning_db.py --db-path data/learning.db
```

## Files

- `scripts/init_learning_db.py` - Database initialization
- `scripts/generate_ollama_embeddings.py` - Embedding generation
- `docs/SEMANTIC_EMBEDDINGS_COMPLETE.md` - Full documentation
