______________________________________________________________________

## name: search-insights description: Use when querying Akosha for semantic search, time-series analytics, or knowledge graph queries. Use when user asks to search across sessions, find patterns, analyze trends, or query entity relationships.

# Search Insights

## Overview

## Available MCP Servers

| Server | Port | Context Mode | Relevant Tools | Default Timeout |
|--------|------|-------------|---------------|----------------|
| akosha | 8682 | summary | mcp\_\_akosha\_\_search_all_systems, mcp\_\_akosha\_\_correlate_systems, mcp\_\_akosha\_\_detect_anomalies | 60s |
| session-buddy | 8678 | grep | mcp\_\_session-buddy\_\_search_conversations, mcp\_\_session-buddy\_\_store_reflection | 30s |

Akosha aggregates memories from 100-100,000 Session-Buddy instances and provides three powerful query modes: semantic search (vector embeddings), time-series analytics (trends/anomalies), and knowledge graph queries (entity relationships).

**Core principle:** Search across ALL your systems' conversations, not just the current session.

## When to Use

**Use when:**

- Searching for past solutions or patterns
- Analyzing trends across sessions over time
- Finding entity relationships and connections
- Detecting anomalies in workflow patterns
- Querying cross-project knowledge
- Finding conversations by semantic similarity

**Don't use when:**

- Capturing new insights (use `capture-insights`)
- Managing Session-Buddy sessions (use `manage-sessions`)
- Simple text search (use Session-Buddy's quick search)

## Query Modes

**3 Query Modes:**

| Mode | Purpose | Latency | Best For |
|------|---------|---------|----------|
| **Semantic Search** | Find by meaning, not keywords | \<100ms | "How do I..." queries |
| **Time-Series Analytics** | Trends, anomalies, correlations | \<500ms | Pattern analysis |
| **Knowledge Graph** | Entity relationships, paths | \<200ms | Connected concepts |

## Quick Reference

```python
# Via Akosha MCP server

# 1. Semantic search
results = await mcp.call_tool("mcp__akosha__search_all_systems", {
    "query": "database connection pooling"
})

# 2. Time-series trends
trends = await mcp.call_tool("mcp__akosha__analyze_trends", {
    "metric": "workflow_duration",
    "time_range": "last_30_days"
})

# 3. Knowledge graph query
graph = await mcp.call_tool("mcp__akosha__query_knowledge_graph", {
    "entity": "authentication",
    "relationship": "connected_to"
})

# 4. Anomaly detection
anomalies = await mcp.call_tool("mcp__akosha__detect_anomalies", {
    "metric": "error_rate",
    "threshold": 2.0  # 2x standard deviations
})
```

## Implementation

### Step 1: Semantic Search

**Search by meaning:**

```python
results = await mcp.call_tool("mcp__akosha__search_all_systems", {
    "query": "How do I fix async Rust borrowing errors?",
    "limit": 10,
    "similarity_threshold": 0.7  # Only high-quality matches
})
```

**How it works:**

1. Query is converted to vector embedding (local ONNX, no API calls)
1. Compared against all stored conversation embeddings
1. Returns ranked results by semantic similarity
1. Each result includes: session_id, timestamp, similarity score, excerpt

**Result format:**

```json
{
    "results": [
        {
            "session_id": "session_abc123",
            "timestamp": "2025-01-15T10:30:00Z",
            "similarity": 0.89,
            "excerpt": "Use Arc<T> instead of Rc<T> for async tasks...",
            "metadata": {
                "project": "auth-service",
                "tags": ["rust", "async", "ownership"]
            }
        }
    ]
}
```

**Search strategies:**

```python
# Broad search
results = await mcp.call_tool("mcp__akosha__search_all_systems", {
    "query": "database optimization"
})

# Project-specific
results = await mcp.call_tool("mcp__akosha__search_all_systems", {
    "query": "database optimization",
    "filters": {
        "project": "user-service"
    }
})

# Time-bound
results = await mcp.call_tool("mcp__akosha__search_all_systems", {
    "query": "authentication patterns",
    "time_range": "last_90_days"
})
```

### Step 2: Time-Series Analytics

**Trend analysis:**

```python
trends = await mcp.call_tool("mcp__akosha__analyze_trends", {
    "metric": "workflow_completion_rate",
    "time_range": "last_30_days",
    "aggregation": "daily"
})
```

**Available metrics:**

- `workflow_completion_rate` - % of workflows that succeed
- `workflow_duration` - Average execution time
- `error_rate` - Frequency of errors per session
- `insight_capture_rate` - Insights captured per hour
- `session_length` - Average session duration

**Trend operations:**

```python
# Moving average
trends = await mcp.call_tool("mcp__akosha__analyze_trends", {
    "metric": "workflow_duration",
    "operations": ["moving_average"],
    "window": 7  # 7-day moving average
})

# Anomaly detection
anomalies = await mcp.call_tool("mcp__akosha__detect_anomalies", {
    "metric": "error_rate",
    "method": "zscore",
    "threshold": 2.5  # Detect outliers 2.5 stddev from mean
})

# Correlation analysis
correlations = await mcp.call_tool("mcp__akosha__analyze_trends", {
    "metrics": ["workflow_duration", "session_length"],
    "operations": ["correlation"]
})
```

**Example anomaly detection:**

```python
# Detect unusual error spikes
anomalies = await mcp.call_tool("mcp__akosha__detect_anomalies", {
    "metric": "error_rate",
    "threshold": 2.0
})

# Output:
{
    "anomalies": [
        {
            "timestamp": "2025-01-10T14:30:00Z",
            "value": 0.15,  # 15% error rate
            "expected": 0.02,  # Expected 2%
            "severity": "high",
            "related_events": ["deploy_v2.3", "database_upgrade"]
        }
    ]
}
```

### Step 3: Knowledge Graph Queries

**Entity relationships:**

```python
# Find connected entities
graph = await mcp.call_tool("mcp__akosha__query_knowledge_graph", {
    "entity": "authentication",
    "relationship": "connected_to",
    "depth": 2  # 2-hop connections
})
```

**Query types:**

```python
# Direct connections
graph = await mcp.call_tool("mcp__akosha__query_knowledge_graph", {
    "entity": "database",
    "relationship": "depends_on"
})

# Path finding
path = await mcp.call_tool("mcp__akosha__find_path", {
    "from_entity": "api",
    "to_entity": "database",
    "max_depth": 3
})

# Entity neighbors
neighbors = await mcp.call_tool("mcp__akosha__query_knowledge_graph", {
    "entity": "microservice"
})
```

**Graph visualization:**

```python
# Get subgraph for visualization
subgraph = await mcp.call_tool("mcp__akosha__query_knowledge_graph", {
    "entity": "payment",
    "relationship": "*",
    "depth": 2,
    "format": "mermaid"  # Returns Mermaid diagram source
})
```

**Example knowledge graph query:**

```python
# User: "What's related to authentication?"

graph = await mcp.call_tool("mcp__akosha__query_knowledge_graph", {
    "entity": "authentication"
})

# Returns relationships like:
# authentication → CONNECTED_TO → session
# authentication → MENTIONED_WITH → jwt
# authentication → SOLVES → login_error
```

### Step 4: Three-Tier Storage Queries

**Storage tiers:**
| Tier | Storage | Access Latency | Retention | Use For |
|------|---------|----------------|----------|---------|
| **Hot** | In-memory | \<10ms | Current session | Active work |
| **Warm** | On-disk (SQLite) | \<50ms | Last 30 days | Recent history |
| **Cold** | Cloud R2 | \<500ms | Forever | Archive |

**Query across tiers:**

```python
# Automatic tier selection
results = await mcp.call_tool("mcp__akosha__search_all_systems", {
    "query": "database schema design",
    "tiers": ["hot", "warm", "cold"]  # Search all
})

# Specific tier
results = await mcp.call_tool("mcp__akosha__search_all_systems", {
    "query": "database schema design",
    "tiers": ["warm"]  # Recent sessions only
})
```

**Data lifecycle:**

1. **Hot** → Active in current Session-Buddy instance
1. **Warm** → Automatically synced to Akosha every 5 minutes
1. **Cold** → Archived to Cloud R2 after 30 days

## Advanced Analytics

### Pattern Detection

```python
# Detect recurring problems
patterns = await mcp.call_tool("mcp__akosha__detect_anomalies", {
    "query": "timeout errors",
    "min_frequency": 3  # Must occur 3+ times
})

# Find common solutions
solutions = await mcp.call_tool("mcp__akosha__search_all_systems", {
    "problem": "database connection pool exhausted",
    "success_only": true
})
```

### Cross-Project Insights

```python
# Aggregate insights across projects
insights = await mcp.call_tool("mcp__akosha__get_system_metrics", {
    "group_by": "project",
    "metrics": ["error_rate", "workflow_success", "insight_density"]
})
```

### Comparative Analysis

```python
# Compare projects
comparison = await mcp.call_tool("mcp__akosha__correlate_systems", {
    "systems": ["auth-service", "user-service"],
    "metrics": ["workflow_duration", "error_rate"]
})
```

## Common Mistakes

| Mistake | Symptom | Fix |
|---------|---------|-----|
| **Keyword search instead of semantic** | No results for "borrowing" when searching "ownership" | Use semantic search, not keyword matching |
| **Not using filters** | Too many irrelevant results | Filter by project, time range, tags |
| **Ignoring anomaly threshold** | Too many false positives | Adjust threshold based on your data |
| **Not exploring graph depth** | Missing important connections | Increase depth parameter to 2-3 hops |
| **Forgetting cold storage** | Missing older insights | Always search all 3 tiers |

## Real-World Impact

**Before this skill:**

- Manual grep across repos → 30+ minutes per search
- No cross-project knowledge sharing → repeated solutions
- No trend visibility → recurring issues undetected

**After this skill:**

- Semantic search → \<100ms across all sessions
- Dependency-aware search → insights flow to related projects
- Anomaly detection → proactive issue identification

## Example Workflows

**Finding Past Solutions:**

```python
# User: "We're seeing database pool exhaustion again"

# Search for past solutions
solutions = await mcp.call_tool("mcp__akosha__search_all_systems", {
    "query": "database connection pool exhausted solution",
    "filters": {"tags": ["production", "incident"]},
    "time_range": "last_365_days"
})

# Find what worked before
for result in solutions["results"]:
    print(f"Found in {result['session_id']}:")
    print(f"  {result['excerpt']}")
```

**Trend Analysis:**

```python
# User: "Are our workflows getting slower?"

# Analyze workflow duration trends
trends = await mcp.call_tool("mcp__akosha__analyze_trends", {
    "metric": "workflow_duration",
    "time_range": "last_90_days",
    "operations": ["moving_average", "trend"]
})

if trends["trend"] == "increasing":
    print(f"⚠️  Workflows slowing by {trends['slope']:.2f}ms/day")
```

**Knowledge Graph Exploration:**

```python
# User: "What systems are affected by authentication changes?"

# Find authentication connections
graph = await mcp.call_tool("mcp__akosha__query_knowledge_graph", {
    "entity": "authentication",
    "relationship": "affects",
    "depth": 2
})

for entity in graph["connected_entities"]:
    print(f"  - {entity} (impact: {entity['impact_score']})")
```

## Performance

**Query latency:**

- Semantic search: \<100ms (100K sessions)
- Time-series query: \<500ms (aggregated)
- Knowledge graph: \<200ms (local graph traversal)

**Scalability:**

- Tested up to 100K Session-Buddy instances
- Linear performance scaling
- Sub-100ms semantic search at full scale

## Related Skills

- **REQUIRED:** `capture-insights` - Capture before searching
- **REQUIRED:** `search-sessions` - Session-Buddy semantic search
- **REQUIRED:** Session-Buddy MCP tools - For session-specific queries

## Related Documentation

- [Akosha README](https://github.com/lesleslie/akosha) - Complete documentation
- MCP Tools Spec - Akosha MCP tools
- Privacy Architecture - Local embeddings, 100% private
