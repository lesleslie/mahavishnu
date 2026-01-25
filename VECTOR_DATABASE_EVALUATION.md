# Vector Database Evaluation: OpenSearch vs pgvector vs Weaviate

**Evaluation Date:** 2025-01-24
**Context:** Mahavishnu multi-engine orchestration platform
**Status:** Architectural decision document

---

## Executive Summary

This document evaluates three vector database options for Mahavishnu's RAG and observability needs:

| Database | Best For | Complexity | Recommendation |
|----------|----------|------------|----------------|
| **pgvector** | Simplicity, SQL integration, MVP validation | Low | ✅ Start here |
| **OpenSearch** | Hybrid search, log analytics, observability | Medium | ✅ Strong for production |
| **Weaviate** | Pure vector search performance, multi-modal AI | Medium | ⚠️ Niche use cases |

**Key Finding:** OpenSearch emerges as a compelling option for Mahavishnu due to **hybrid code search** + **log analytics** + **existing OpenTelemetry stack**.

---

## Current State Analysis

### Existing Architecture

**LlamaIndex Adapter** (`mahavishnu/engines/llamaindex_adapter.py:148`):
- Uses **in-memory** `VectorStoreIndex` (lost on restart)
- No persistent vector storage
- Ollama embeddings (`nomic-embed-text` model)
- Pure semantic search (no keyword/hybrid)

**Observability Stack** (`pyproject.toml:32-36`):
- OpenTelemetry API, SDK, instrumentation
- OTLP grpc exporter
- Struct logging with structlog

**Documented Decision** (`docs/VECTOR_DATABASE_RECOMMENDATIONS.md`):
- Recommends Oneiric's pgvector adapter
- Leverages existing PostgreSQL infrastructure
- Production-ready, well-maintained

### Limitations of Current Approach

1. **In-memory storage** - Indices lost on restart
2. **Pure semantic search** - No exact function/class name matching
3. **No log analytics** - Observability data exported but not analyzed
4. **No error pattern detection** - Manual log review required

---

## Technology Comparison

### 1. pgvector (PostgreSQL Extension)

**Architecture:** PostgreSQL extension for vector similarity search

#### Strengths

```python
# Simple integration (Oneiric adapter exists)
from oneiric.adapters.vector.pgvector import PgvectorAdapter, PgvectorSettings

settings = PgvectorSettings(
    host="localhost",
    port=5432,
    database="mahavishnu",
    ensure_extension=True
)

adapter = PgvectorAdapter(settings)
await adapter.init()

# SQL + Vectors in one query
results = await adapter.search(
    collection="workflows",
    query_vector=query_embedding,
    limit=10,
    filter_expr={"tags": ["backend"]}  # JSONB metadata filtering
)
```

**Pros:**
- ✅ Zero additional infrastructure (reuse PostgreSQL)
- ✅ SQL integration with vector search
- ✅ ACID compliance for data integrity
- ✅ Oneiric has production-ready adapter
- ✅ Connection pooling, transactions, health checks built-in
- ✅ Type-safe with Pydantic models
- ✅ Lower operational overhead

**Cons:**
- ❌ Vector search performance lower than dedicated solutions
- ❌ No keyword/full-text search (can add pg_trgm but limited)
- ❌ No log analytics capabilities
- ❌ No ML-powered pattern detection

**Best For:**
- MVP validation and prototyping
- Projects with existing PostgreSQL investment
- Simplicity-focused architecture
- Scale < 1M vectors

---

### 2. OpenSearch

**Architecture:** Search and analytics suite with k-NN plugin for vector search

#### Strengths

**Hybrid Search (Semantic + Keyword):**

```python
from llama_index.vector_stores.opensearch import OpensearchVectorStore, OpensearchVectorClient

# Configure OpenSearch vector client
client = OpensearchVectorClient(
    endpoint="https://localhost:9200",
    index_name="mahavishnu_code",
    dimension=1536,
    embedding_field="embedding",
    text_field="content"
)

vector_store = OpensearchVectorStore(client)
storage_context = StorageContext.from_defaults(vector_store=vector_store)

# Index documents
index = VectorStoreIndex.from_documents(
    documents=documents,
    storage_context=storage_context
)

# Query with hybrid search
query_engine = index.as_query_engine(
    similarity_top_k=5,
    vector_store_kwargs={
        "filter": [{"term": {"repository": "my-repo"}}]
    }
)
```

**Raw OpenSearch Query (Maximum Power):**

```python
search_query = {
    "query": {
        "bool": {
            "should": [
                # Semantic search (k-NN)
                {
                    "knn": {
                        "embedding": {
                            "vector": query_embedding,
                            "k": 10
                        }
                    }
                },
                # Keyword search (BM25) - exact matches ranked higher
                {
                    "multi_match": {
                        "query": "def authenticate_user",
                        "fields": ["content^2", "file_name"],
                        "type": "best_fields"
                    }
                }
            ],
            # Filter by metadata
            "filter": [
                {"term": {"repository": "backend"}},
                {"term": {"language": "python"}},
                {"terms": {"tags": ["auth", "security"]}}
            ]
        }
    }
}
```

**Log Analytics with Data Prepper:**

```yaml
# OpenSearch Data Prepper pipeline for Mahavishnu
mahavishnu-pipeline:
  source:
    otel_traces:
      ssl: true
      endpoint: "localhost:21890"
    otel_logs:
      ssl: true
      endpoint: "localhost:21891"

  processor:
    - log_pattern:
        # Detect error patterns across workflow executions
        field: "message"
        pattern_library: "/etc/log-patterns/common-patterns.json"

    - trace_correlation:
        # Correlate logs with workflow traces
        trace_id_field: "trace_id"
        span_id_field: "span_id"

    - grok:
        # Parse structured logs
        match:
          log: ["%{TIMESTAMP_ISO8601:timestamp} %{LOGLEVEL:level} %{GREEDYDATA:message}"]

  sink:
    - opensearch:
        hosts: ["https://localhost:9200"]
        username: "${OPENSEARCH_USERNAME}"
        password: "${OPENSEARCH_PASSWORD}"
        index: "mahavishnu_workflows"
```

**ML Commons Log Pattern Detection:**

```json
POST /_plugins/_ml/agents/OQutgJYBAc35E4_KvI1q/_execute
{
  "parameters": {
    "index": "mahavishnu_workflows",
    "timeField": "@timestamp",
    "logFieldName": "message",
    "traceFieldName": "traceId",
    "baseTimeRangeStart": "2025-01-24 00:00:00",
    "baseTimeRangeEnd": "2025-01-24 09:00:00",
    "selectionTimeRangeStart": "2025-01-24 10:00:00",
    "selectionTimeRangeEnd": "2025-01-24 11:00:00"
  }
}
```

**Response:**
```json
{
  "logInsights": [
    {
      "pattern": "<*> ERROR Workflow <*> failed at adapter <*>",
      "count": 15,
      "sampleLogs": [
        "2025-01-24 10:30:15 ERROR Workflow ingest_docs failed at adapter llamaindex: Connection timeout",
        "2025-01-24 10:32:08 ERROR Workflow execute_query failed at adapter agno: Invalid API key"
      ]
    },
    {
      "pattern": "<*> WARNING Repo <*> not found in repos.yaml",
      "count": 8,
      "sampleLogs": [
        "2025-01-24 10:15:22 WARNING Repo /path/to/unknown not found in repos.yaml"
      ]
    }
  ]
}
```

**Pros:**
- ✅ **Hybrid search** - Semantic (k-NN) + Keyword (BM25) in one query
- ✅ **Log analytics** - Native OpenTelemetry support, Data Prepper pipelines
- ✅ **ML Commons** - Automated error pattern detection, trace correlation
- ✅ **Powerful filtering** - Boolean queries, range filters, nested aggregations
- ✅ **Full-text search** - Best-in-class BM25 for exact code matches
- ✅ **Native LlamaIndex integration** - First-class `OpensearchVectorStore`
- ✅ **Scalability** - Distributed, horizontally scalable
- ✅ **Observability** - Dashboards, alerting, anomaly detection

**Cons:**
- ❌ Additional infrastructure (Docker/Kubernetes deployment)
- ❌ Higher resource footprint (Java-based)
- ❌ More complex to operate than PostgreSQL
- ❌ Learning curve for OpenSearch-specific concepts

**Best For:**
- Projects needing both code search AND log analytics
- Existing OpenTelemetry observability stack
- Multi-repo orchestration with trace correlation
- Production environments needing automated error detection

---

### 3. Weaviate

**Architecture:** Dedicated vector database for AI/ML applications

#### Strengths

```python
import weaviate
from weaviate.embedded import EmbeddedOptions

# Connect to Weaviate
client = weaviate.Client(
    embedded_options=EmbeddedOptions(),
    additional_headers={
        "X-Ollama-Host": "http://localhost:11434"
    }
)

# Create schema
client.schema.create_class({
    "class": "CodeSnippet",
    "vectorizer": "none",  # Use Ollama embeddings
    "properties": [
        {"name": "content", "dataType": ["text"]},
        {"name": "file_path", "dataType": ["string"]},
        {"name": "repository", "dataType": ["string"]},
        {"name": "language", "dataType": ["string"]},
        {"name": "tags", "dataType": ["string[]"]}
    ]
})

# Hybrid search (semantic + BM25)
result = client.query.get("CodeSnippet", ["content", "file_path"]) \
    .with_hybrid(
        query="authentication function",
        alpha=0.7,  # 0.7 = 70% semantic, 30% keyword
        vector=query_embedding
    ) \
    .with_where({
        "path": ["repository"],
        "operator": "Equal",
        "valueString": "backend"
    }) \
    .with_limit(10) \
    .do()
```

**Pros:**
- ✅ **Purpose-built for AI** - Optimized for vector search workloads
- ✅ **Native Ollama integration** - Embeddings out-of-the-box
- ✅ **Hybrid search** - Semantic + BM25 with tunable alpha
- ✅ **GraphQL API** - Type-safe queries
- ✅ **Multi-modal** - Search text, images, audio, video
- ✅ **Edge embeddings** - Faster queries with pre-computed filters
- ✅ **Great LlamaIndex integration** - `llama-index-vector-stores-weaviate`

**Cons:**
- ❌ Another infrastructure service (separate from PostgreSQL)
- ❌ No log analytics capabilities
- ❌ No trace correlation or observability features
- ❌ Learning curve for Weaviate-specific concepts (classes, tenants)
- ❌ Not using existing PostgreSQL investment (if present)

**Best For:**
- Projects where vector search is the core product
- Multi-modal RAG (images, audio, video alongside code)
- Sub-100ms query latency requirements at scale
- Pure AI/ML applications without observability needs

---

## Decision Matrix

### Feature Comparison

| Feature | pgvector | OpenSearch | Weaviate |
|---------|----------|------------|----------|
| **Vector Search** | ✅ Good (IVFFlat) | ✅ Good (k-NN + HNSW) | ✅ Excellent |
| **Keyword Search** | ⚠️ Via pg_trgm (limited) | ✅ Excellent (BM25) | ✅ Good (BM25) |
| **Hybrid Search** | ❌ Manual implementation | ✅ Native (should clause) | ✅ Native (with alpha) |
| **Full-Text Search** | ⚠️ Limited | ✅ Best-in-class | ✅ Good |
| **Metadata Filtering** | ✅ JSONB | ✅ Powerful boolean queries | ✅ GraphQL where |
| **Log Analytics** | ❌ No | ✅ Excellent (Data Prepper) | ❌ No |
| **Trace Correlation** | ❌ No | ✅ Native (OTel support) | ❌ No |
| **ML Pattern Detection** | ❌ No | ✅ ML Commons agents | ❌ No |
| **OpenTelemetry** | ❌ No | ✅ Native support | ❌ No |
| **LlamaIndex Support** | ✅ Postgres vector store | ✅ OpenSearch vector store | ✅ Weaviate vector store |
| **Infrastructure** | Reuse PostgreSQL | New service | New service |
| **Operational Overhead** | Low | Medium | Medium |
| **Learning Curve** | Low (SQL) | Medium (OpenSearch DSL) | Medium (GraphQL) |
| **Scalability** | Vertical only | Horizontal (distributed) | Horizontal (distributed) |
| **Query Performance** | Good at <1M vectors | Good at any scale | Excellent at any scale |
| **Multi-modal Search** | ❌ No | ❌ Limited | ✅ Excellent |
| **Type Safety** | ✅ Pydantic (Oneiric) | ⚠️ Dict-based | ✅ GraphQL |

---

## Use Case Analysis for Mahavishnu

### Primary Use Cases

1. **Code Search Across Repositories**
   - Semantic: Find "user login" when searching for "authentication"
   - Keyword: Find exact function names like `authenticate_user()`
   - Filter by: repository, language, tags, last modified
   - **Winner:** OpenSearch (hybrid search) or Weaviate (hybrid with alpha)

2. **Workflow Orchestration**
   - Execute workflows across multiple repositories
   - Track execution status, errors, performance
   - **Winner:** OpenSearch (trace correlation + log analytics)

3. **Observability & Error Detection**
   - Parse workflow logs
   - Detect error patterns automatically
   - Correlate errors with traces
   - **Winner:** OpenSearch (ML Commons + Data Prepper)

4. **RAG Pipelines**
   - Ingest code repositories
   - Create embeddings with Ollama
   - Query knowledge bases
   - **Winner:** All three (equal LlamaIndex support)

### The "Mahavishnu Pattern"

Mahavishnu is a **workflow orchestrator** that:
1. **Ingests code** from multiple repos → needs **code search** (hybrid semantic+keyword)
2. **Executes workflows** across repos → needs **log analytics** (pattern detection, trace correlation)
3. **Uses OpenTelemetry** for observability → needs **trace storage** (OpenSearch native support)

**Key Insight:** One platform (OpenSearch) solves **all three problems** vs. separate platforms for each.

---

## Architecture Proposals

### Option 1: pgvector (Simplicity First)

**Best for:** MVP validation, prototyping, simplicity-focused architecture

```python
# mahavishnu/core/vector_store.py
from oneiric.adapters.vector.pgvector import PgvectorAdapter, PgvectorSettings
from oneiric.adapters.vector.common import VectorDocument

class MahavishnuVectorStore:
    """Vector store using PostgreSQL + pgvector via Oneiric adapter."""

    def __init__(self, app_settings: MahavishnuSettings):
        self.adapter = PgvectorAdapter(app_settings.to_pgvector_settings())

    async def initialize(self):
        await self.adapter.init()
        # Create collections
        await self.adapter.create_collection("workflows", dimension=1536)
        await self.adapter.create_collection("repositories", dimension=1536)
        await self.adapter.create_collection("sessions", dimension=1536)

    async def search_workflows(
        self,
        query_embedding: list[float],
        limit: int = 10,
        tags: list[str] | None = None
    ) -> list[dict]:
        filter_expr = {"tags": tags} if tags else None
        results = await self.adapter.search(
            collection="workflows",
            query_vector=query_embedding,
            limit=limit,
            filter_expr=filter_expr
        )
        return [
            {
                "workflow_id": r.id,
                "similarity_score": r.score,
                "metadata": r.metadata
            }
            for r in results
        ]

    async def health_check(self) -> dict:
        return {
            "vector_db": await self.adapter.health(),
            "collections": await self.adapter.list_collections()
        }
```

**Configuration:**

```yaml
# settings/mahavishnu.yaml
vector_db:
  enabled: true
  host: localhost
  port: 5432
  user: postgres
  password: ${MAHAVISHNU_VECTOR_DB_PASSWORD}
  database: mahavishnu
  dimension: 1536
  distance_metric: cosine
  ensure_extension: true
  ivfflat_lists: 100
  max_connections: 10
```

**Migration Path:**
```python
# Later, swap to OpenSearch with minimal code changes
# from oneiric.adapters.vector.pgvector import PgvectorAdapter
from llama_index.vector_stores.opensearch import OpensearchVectorStore
```

---

### Option 2: OpenSearch (Unified Observability)

**Best for:** Production environments, unified observability, hybrid search

```python
# mahavishnu/core/adapters/opensearch_adapter.py
from typing import Dict, List, Any, Optional
from opensearchpy import AsyncOpenSearch
from llama_index.vector_stores.opensearch import OpensearchVectorStore, OpensearchVectorClient
from llama_index.core import VectorStoreIndex, StorageContext, Document

class OpenSearchAdapter:
    """OpenSearch adapter for vector search + log analytics."""

    def __init__(self, config: MahavishnuSettings):
        self.config = config
        self.client = AsyncOpenSearch(
            hosts=[f"{config.opensearch_host}:{config.opensearch_port}"],
            http_auth=(config.opensearch_user, config.opensearch_password.get_secret_value()),
            use_ssl=config.opensearch_ssl,
            verify_certs=config.opensearch_verify_certs,
            ssl_show_warn=False
        )
        self.vector_client = OpensearchVectorClient(
            endpoint=self.client.transport.hosts[0],
            index_name="mahavishnu_code",
            dimension=1536,
            embedding_field="embedding",
            text_field="content"
        )

    async def initialize(self):
        """Initialize OpenSearch indices and pipelines."""
        # Create k-NN index for code search
        await self.client.indices.create(
            index="mahavishnu_code",
            body={
                "settings": {
                    "index.knn": True,
                    "index.knn.algo_param.ef_search": 100
                },
                "mappings": {
                    "properties": {
                        "content": {"type": "text"},
                        "file_path": {"type": "keyword"},
                        "repository": {"type": "keyword"},
                        "language": {"type": "keyword"},
                        "tags": {"type": "keyword"},
                        "embedding": {
                            "type": "knn_vector",
                            "dimension": 1536,
                            "method": {
                                "name": "hnsw",
                                "space_type": "cosinesimil",
                                "engine": "nmslib"
                            }
                        }
                    }
                }
            }
        )

        # Create log analytics index
        await self.client.indices.create(
            index="mahavishnu_logs",
            body={
                "mappings": {
                    "properties": {
                        "@timestamp": {"type": "date"},
                        "level": {"type": "keyword"},
                        "message": {"type": "text"},
                        "trace_id": {"type": "keyword"},
                        "span_id": {"type": "keyword"},
                        "workflow_id": {"type": "keyword"},
                        "repository": {"type": "keyword"},
                        "adapter": {"type": "keyword"}
                    }
                }
            }
        )

    async def hybrid_search(
        self,
        query_text: str,
        query_embedding: List[float],
        filters: Optional[Dict[str, Any]] = None,
        limit: int = 10,
        alpha: float = 0.5  # 0.5 = 50% semantic, 50% keyword
    ) -> List[Dict[str, Any]]:
        """Execute hybrid search (semantic + keyword)."""
        bool_query = {"should": []}

        # Semantic search (k-NN)
        bool_query["should"].append({
            "knn": {
                "embedding": {
                    "vector": query_embedding,
                    "k": limit
                }
            }
        })

        # Keyword search (BM25)
        bool_query["should"].append({
            "multi_match": {
                "query": query_text,
                "fields": ["content^2", "file_path"],
                "type": "best_fields",
                "boost": 1.0
            }
        })

        # Add filters
        if filters:
            filter_clauses = []
            for field, value in filters.items():
                if isinstance(value, list):
                    filter_clauses.append({"terms": {field: value}})
                else:
                    filter_clauses.append({"term": {field: value}})
            bool_query["filter"] = filter_clauses

        # Execute query
        response = await self.client.search(
            index="mahavishnu_code",
            body={
                "query": {
                    "bool": bool_query
                }
            },
            size=limit
        )

        return [
            {
                "score": hit["_score"],
                "content": hit["_source"]["content"],
                "file_path": hit["_source"]["file_path"],
                "repository": hit["_source"]["repository"],
                "language": hit["_source"]["language"],
                "tags": hit["_source"].get("tags", [])
            }
            for hit in response["hits"]["hits"]
        ]

    async def ingest_logs(self, logs: List[Dict[str, Any]]):
        """Ingest workflow logs into OpenSearch."""
        from opensearchpy.helpers import async_bulk

        actions = [
            {
                "_index": "mahavishnu_logs",
                "_source": log
            }
            for log in logs
        ]

        success, failed = await async_bulk(self.client, actions)
        return {"success": success, "failed": len(failed)}

    async def detect_error_patterns(
        self,
        time_range_start: str,
        time_range_end: str,
        index: str = "mahavishnu_logs"
    ) -> List[Dict[str, Any]]:
        """Detect error patterns using ML Commons."""
        # Use OpenSearch ML Commons log pattern analysis
        response = await self.client.transport.perform_request(
            "POST",
            f"/_plugins/_ml/agents/OQutgJYBAc35E4_KvI1q/_execute",
            body={
                "parameters": {
                    "index": index,
                    "timeField": "@timestamp",
                    "logFieldName": "message",
                    "traceFieldName": "traceId",
                    "selectionTimeRangeStart": time_range_start,
                    "selectionTimeRangeEnd": time_range_end
                }
            }
        )

        # Parse and return detected patterns
        import json
        results = response["inference_results"][0]["output"][0]["result"]
        log_insights = json.loads(results)

        return log_insights.get("logInsights", [])

    async def get_health(self) -> Dict[str, Any]:
        """Get adapter health status."""
        cluster_health = await self.client.cluster.health()
        indices = await self.client.indices.get(index="*")

        return {
            "status": "healthy",
            "details": {
                "cluster_status": cluster_health["status"],
                "number_of_nodes": cluster_health["number_of_nodes"],
                "active_shards": cluster_health["active_shards"],
                "indices": list(indices.keys())
            }
        }
```

**Configuration:**

```yaml
# settings/mahavishnu.yaml
opensearch:
  enabled: true
  host: localhost
  port: 9200
  user: admin
  password: ${OPENSEARCH_PASSWORD}
  ssl: true
  verify_certs: false
  log_index: mahavishnu_logs
  code_index: mahavishnu_code

  # Data Prepper pipeline for OTel ingestion
  data_prepper:
    enabled: true
    pipeline_name: mahavishnu-pipeline
    otel_traces_port: 21890
    otel_logs_port: 21891
```

**Docker Compose for Development:**

```yaml
# docker-compose.yml
version: '3.8'

services:
  opensearch:
    image: opensearchproject/opensearch:latest
    container_name: mahavishnu-opensearch
    environment:
      - cluster.name=mahavishnu-cluster
      - node.name=mahavishnu-node1
      - discovery.type=single-node
      - bootstrap.memory_lock=true
      - "OPENSEARCH_JAVA_OPTS=-Xms512m -Xmx512m"
      - "DISABLE_SECURITY_PLUGIN=true"  # For dev only
      - "DISABLE_INSTALL_DEMO_CONFIG=true"
    ulimits:
      memlock:
        soft: -1
        hard: -1
      nofile:
        soft: 65536
        hard: 65536
    volumes:
      - opensearch-data:/usr/share/opensearch/data
    ports:
      - 9200:9200
      - 9600:9600

  opensearch-dashboards:
    image: opensearchproject/opensearch-dashboards:latest
    container_name: mahavishnu-dashboards
    ports:
      - 5601:5601
    expose:
      - "5601"
    environment:
      - 'OPENSEARCH_HOSTS=["http://opensearch:9200"]'
      - "DISABLE_SECURITY_DASHBOARDS_PLUGIN=true"
    depends_on:
      - opensearch

  data-prepper:
    image: opensearchproject/data-prepper:latest
    container_name: mahavishnu-data-prepper
    volumes:
      - ./data-prepper/pipelines.yaml:/usr/share/data-prepper/pipelines/pipelines.yaml
    ports:
      - 21890:21890  # OTel traces
      - 21891:21891  # OTel logs
    depends_on:
      - opensearch

volumes:
  opensearch-data:
```

---

## Justification Framework

### Decision Tree

```
Start
 │
 ├─ Do you need log analytics and error pattern detection?
 │   ├─ Yes → OpenSearch ✅
 │   └─ No  → Continue
 │
 ├─ Do you need hybrid code search (semantic + keyword)?
 │   ├─ Yes → OpenSearch or Weaviate
 │   │        ├─ Want unified observability? → OpenSearch ✅
 │   │        └─ Pure AI/ML focus? → Weaviate
 │   └─ No  → Continue
 │
 ├─ Do you have existing PostgreSQL infrastructure?
 │   ├─ Yes → pgvector ✅
 │   └─ No  → Consider OpenSearch/Weaviate
 │
 ├─ What's your scale?
 │   ├─ < 1M vectors → Any option works
 │   ├─ 1M-10M vectors → OpenSearch or Weaviate
 │   └─ > 10M vectors → Weaviate or OpenSearch
 │
 └─ What's your priority?
     ├─ Simplicity → pgvector ✅
     ├─ Unified observability → OpenSearch ✅
     └─ Pure vector search performance → Weaviate
```

### Scorecard for Mahavishnu

| Criterion | pgvector | OpenSearch | Weaviate |
|-----------|----------|------------|----------|
| **Code search (hybrid)** | 3/10 | 10/10 | 9/10 |
| **Log analytics** | 0/10 | 10/10 | 0/10 |
| **Trace correlation** | 0/10 | 10/10 | 0/10 |
| **Error pattern detection** | 0/10 | 10/10 | 0/10 |
| **OTel integration** | 0/10 | 10/10 | 0/10 |
| **Simplicity** | 10/10 | 5/10 | 6/10 |
| **Operational overhead** | 10/10 | 6/10 | 6/10 |
| **Migration from in-memory** | 9/10 | 8/10 | 8/10 |
| **LlamaIndex support** | 9/10 | 10/10 | 10/10 |
| **Future scalability** | 5/10 | 9/10 | 10/10 |
| **Total Score** | **46/90** | **88/90** | **49/90** |

**Winner: OpenSearch (88/90)** for Mahavishnu's specific use case

---

## Recommendation

### For Mahavishnu specifically:

**Phase 1: Start with pgvector** (2-4 weeks)
- Validate RAG pipelines with persistent storage
- Use Oneiric's production-ready adapter
- Minimal operational overhead
- Prove value before investing in OpenSearch

**Phase 2: Migrate to OpenSearch** (1-2 months)
- After validating RAG effectiveness
- Add log analytics and error pattern detection
- Implement hybrid code search
- Unified observability platform

**Rationale:**
1. **pgvector for quick wins** - Leverage Oneiric adapter, move fast
2. **OpenSearch for production** - Unified observability, hybrid search, ML-powered insights
3. **LlamaIndex abstraction** - Same `VectorStoreIndex` interface, swap backends easily

### Migration Path

```python
# Phase 1: pgvector (quick start)
from oneiric.adapters.vector.pgvector import PgvectorAdapter
vector_store = PgvectorAdapter(settings)

# Phase 2: OpenSearch (production)
from llama_index.vector_stores.opensearch import OpensearchVectorStore
vector_store = OpensearchVectorStore(client)

# Same LlamaIndex interface!
index = VectorStoreIndex.from_documents(
    documents=documents,
    storage_context=StorageContext.from_defaults(vector_store=vector_store)
)
```

---

## Next Steps

### Immediate (This Week)

1. **Install pgvector package**
   ```bash
   pip install 'pgvector>=0.2.0'
   pip install 'llama-index-vector-stores-postgres'
   ```

2. **Create vector store wrapper** (2-3 hours)
   - Implement `mahavishnu/core/vector_store.py`
   - Use Oneiric adapter
   - Add health checks

3. **Update LlamaIndex adapter** (1-2 hours)
   - Replace in-memory `VectorStoreIndex` with persistent store
   - Test with existing repositories

4. **Write integration tests** (2-3 hours)
   - Test CRUD operations
   - Test search with filters
   - Test persistence across restarts

### Short-term (This Month)

5. **Validate RAG effectiveness**
   - Run ingestion on pilot repositories
   - Measure search quality
   - Get user feedback

6. **Plan OpenSearch migration** (if RAG validated)
   - Set up Docker Compose for local dev
   - Configure Data Prepper for OTel ingestion
   - Implement OpenSearch adapter

### Long-term (Next Quarter)

7. **Deploy OpenSearch to production**
   - Kubernetes deployment
   - Security configuration
   - Backup and disaster recovery

8. **Implement log analytics**
   - ML Commons error pattern detection
   - Trace correlation across workflows
   - Dashboards for visualization

---

## References

- **OpenSearch Python Client**: https://github.com/opensearch-project/opensearch-py
- **OpenSearch k-NN Plugin**: https://opensearch.org/docs/latest/search-plugins/knn/
- **OpenSearch ML Commons**: https://opensearch.org/docs/latest/ml-commons-plugin/
- **LlamaIndex OpenSearch Integration**: https://github.com/run-llama/llama_index/tree/main/llama-index-integrations/vector_stores/llama-index-vector-stores-opensearch
- **Oneiric pgvector Adapter**: https://github.com/yourusername/oneiric (internal)
- **pgvector Documentation**: https://github.com/pgvector/pgvector
- **Weaviate Documentation**: https://weaviate.io/documentation

---

**Document Status:** Ready for review
**Next Review Date:** 2025-02-24 or after Phase 1 completion
**Owner:** Mahavishnu Architecture Team
