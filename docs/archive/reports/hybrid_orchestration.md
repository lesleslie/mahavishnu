# Hybrid Orchestration Patterns

**Module**: `mahavishnu.patterns.hybrid_orchestration`

**Purpose**: Decision tree and patterns for combining multiple orchestrators in Mahavishnu.

---

## Overview

Mahavishnu supports four orchestration engines, each optimized for different use cases:

| Orchestrator | Best For | Complexity | Stateful | Routing | Scheduling |
|--------------|----------|------------|----------|---------|------------|
| **Agno** | Simple agent tasks | Low | ❌ | ❌ | ❌ |
| **LangGraph** | Multi-stage workflows, approvals | High | ✅ | ✅ | ❌ |
| **LlamaIndex** | RAG pipelines, document analysis | Medium | ❌ | ❌ | ❌ |
| **Prefect** | Scheduled workflows, DAGs | High | ❌ | ❌ | ✅ |

---

## Quick Start

### Automatic Selection

```python
from mahavishnu.patterns.hybrid_orchestration import select_orchestrator

# Select based on requirements
orch_type = select_orchestrator(
    task_type="approval_workflow",
    requires_state=True,
    requires_routing=True,
)
# Returns: OrchestratorType.LANGGRAPH
```

### Recommendation by Description

```python
from mahavishnu.patterns.hybrid_orchestration import recommend_orchestrator

orc_type, profile = recommend_orchestrator(
    "Need to analyze documents and get approval"
)
# Returns: (OrchestratorType.LLAMAINDEX, profile)
```

### Hybrid Workflow

```python
from mahavishnu.patterns.hybrid_orchestration import HybridOrchestrator

hybrid = HybridOrchestrator()

result = await hybrid.execute({
    "stages": [
        {
            "type": "llamaindex",
            "task": {"type": "document_analysis", "docs": ["doc1.pdf"]},
        },
        {
            "type": "langgraph",
            "task": {
                "workflow": {"nodes": ["analyze", "approve"]},
                "input": {...}
            },
        },
        {
            "type": "agno",
            "task": {"agents": ["implementer"], "input": {...}},
        },
    ]
})
```

---

## Decision Tree

### When to Use Each Orchestrator

#### Agno
✅ **Use for:**
- Simple single-agent tasks
- Quick prototyping
- Low-latency execution
- Direct API calls

❌ **Avoid for:**
- Complex workflows
- Stateful operations
- Scheduled tasks

```python
# Example: Simple agent execution
from mahavishnu.patterns.hybrid_orchestration import select_orchestrator

orch_type = select_orchestrator(
    task_type="simple_task",
)
# Returns: OrchestratorType.AGNO
```

---

#### LangGraph
✅ **Use for:**
- Multi-stage workflows
- Approval workflows
- Conditional routing
- State persistence and recovery
- Human-in-the-loop

❌ **Avoid for:**
- Simple single-agent tasks
- Scheduled workflows

```python
# Example: Approval workflow
from mahavishnu.patterns.hybrid_orchestration import select_orchestrator

orch_type = select_orchestrator(
    task_type="approval_workflow",
    requires_state=True,
    requires_routing=True,
)
# Returns: OrchestratorType.LANGGRAPH
```

**Example Workflow:**
```python
workflow = {
    "nodes": [
        "analyze",
        "security_check",
        "performance_check",
        "approve",
        "implement",
    ],
    "conditional": {
        "approve": lambda s: "implement"
        if not s.get("critical_issues")
        else "end"
    },
}
```

---

#### LlamaIndex
✅ **Use for:**
- Document analysis
- RAG (Retrieval-Augmented Generation) pipelines
- Knowledge extraction
- Vector search
- PDF processing

❌ **Avoid for:**
- Non-RAG tasks
- Complex routing

```python
# Example: RAG workflow
from mahavishnu.patterns.hybrid_orchestration import select_orchestrator

orch_type = select_orchestrator(
    task_type="rag_workflow",
)
# Returns: OrchestratorType.LLAMAINDEX
```

---

#### Prefect
✅ **Use for:**
- Scheduled workflows
- DAG-based tasks
- ETL pipelines
- Batch jobs
- Periodic tasks

❌ **Avoid for:**
- Simple real-time tasks
- Low-latency requirements

```python
# Example: Scheduled batch job
from mahavishnu.patterns.hybrid_orchestration import select_orchestrator

orch_type = select_orchestrator(
    task_type="batch_job",
    requires_scheduling=True,
)
# Returns: OrchestratorType.PREFECT
```

---

## Hybrid Patterns

### Pattern 1: Document Analysis → Approval

```python
from mahavishnu.patterns.hybrid_orchestration import HybridOrchestrator

hybrid = HybridOrchestrator()

result = await hybrid.execute({
    "stages": [
        {
            "type": "llamaindex",
            "task": {
                "type": "document_analysis",
                "docs": ["requirements.pdf"],
            },
        },
        {
            "type": "langgraph",
            "task": {
                "workflow": {
                    "nodes": ["review", "approve", "implement"],
                    "conditional": {
                        "approve": lambda s: "implement" if s["approved"] else "end"
                    },
                },
                "input": {"requirements": "..."},
            },
        },
    ]
})
```

---

### Pattern 2: RAG → Conditional Routing

```python
result = await hybrid.execute({
    "stages": [
        {
            "type": "llamaindex",
            "task": {
                "type": "rag_workflow",
                "query": "How do I implement auth?",
            },
        },
        {
            "type": "langgraph",
            "task": {
                "workflow": {
                    "nodes": ["analyze", "route", "implement"],
                    "conditional": {
                        "route": lambda s: "implement_jwt"
                        if s["use_jwt"]
                        else "implement_session"
                    },
                },
            },
        },
    ]
})
```

---

### Pattern 3: Scheduled → Multi-Stage

```python
result = await hybrid.execute({
    "stages": [
        {
            "type": "prefect",
            "task": {
                "type": "scheduled_etl",
                "schedule": "0 2 * * *",  # 2 AM daily
            },
        },
        {
            "type": "langgraph",
            "task": {
                "workflow": {
                    "nodes": ["extract", "transform", "load", "verify"],
                },
            },
        },
    ]
})
```

---

## Orchestrator Profiles

### Agno Profile

```python
from mahavishnu.patterns.hybrid_orchestration import OrchestratorSelector

selector = OrchestratorSelector()
profile = selector.get_profile(OrchestratorType.AGNO)

print(f"Name: {profile.name}")
print(f"Complexity: {profile.complexity}")
print(f"Stateful: {profile.stateful}")
print(f"Strengths: {profile.strengths}")
print(f"Weaknesses: {profile.weaknesses}")
print(f"Best For: {profile.best_for}")
```

**Output:**
```
Name: Agno
Complexity: low
Stateful: False
Strengths: ['Simple agent execution', 'Fast setup', 'Low overhead', 'Direct API calls']
Weaknesses: ['No state management', 'Limited routing', 'No scheduling']
Best For: ['Simple agent tasks', 'Quick prototyping', 'Single-stage workflows', 'Low-latency execution']
```

---

## API Reference

### OrchestratorSelector

```python
class OrchestratorSelector:
    """Decision tree for selecting orchestrators."""

    def select(
        self,
        task_type: str,
        requires_state: bool = False,
        requires_routing: bool = False,
        requires_scheduling: bool = False,
    ) -> OrchestratorType:
        """Select orchestrator based on task characteristics."""

    def get_profile(self, orchestrator_type: OrchestratorType) -> OrchestratorProfile:
        """Get orchestrator profile."""

    def list_all_profiles(self) -> dict[OrchestratorType, OrchestratorProfile]:
        """Get all orchestrator profiles."""
```

---

### HybridOrchestrator

```python
class HybridOrchestrator:
    """Combine multiple orchestrators in a single workflow."""

    async def execute(self, task: dict[str, Any], repos: list[str]) -> dict[str, Any]:
        """Execute multi-stage hybrid workflow."""

    def recommend_orchestrator(
        self,
        task_description: str,
    ) -> tuple[OrchestratorType, OrchestratorProfile]:
        """Recommend orchestrator based on task description."""
```

---

### Convenience Functions

```python
def select_orchestrator(
    task_type: str,
    requires_state: bool = False,
    requires_routing: bool = False,
    requires_scheduling: bool = False,
) -> OrchestratorType:
    """Select orchestrator for task."""

def recommend_orchestrator(
    task_description: str,
) -> tuple[OrchestratorType, OrchestratorProfile]:
    """Recommend orchestrator for task description."""

def get_orchestrator_guide() -> dict[str, str]:
    """Get quick reference guide for orchestrators."""
```

---

## Quick Reference Guide

```python
from mahavishnu.patterns.hybrid_orchestration import get_orchestrator_guide

guide = get_orchestrator_guide()

for task, orchestrator in guide.items():
    print(f"{task}: {orchestrator}")
```

**Output:**
```
Simple agent task: agno
Document analysis: llamaindex
RAG pipeline: llamaindex
Approval workflow: langgraph
Multi-stage workflow: langgraph
Scheduled task: prefect
DAG-based task: prefect
ETL pipeline: prefect
Low-latency execution: agno
Stateful workflow: langgraph
Conditional routing: langgraph
Human-in-the-loop: langgraph
```

---

## Best Practices

### 1. Match Orchestrator to Requirements

```python
# ✅ Good: Match requirements to orchestrator
if requires_approval:
    use_langgraph()
elif requires_rag:
    use_llamaindex()
elif requires_scheduling:
    use_prefect()
else:
    use_agno()

# ❌ Bad: Always use the most complex orchestrator
use_langgraph()  # Overkill for simple tasks
```

---

### 2. Use Hybrid for Multi-Stage Workflows

```python
# ✅ Good: Hybrid for different stages
hybrid.execute({
    "stages": [
        {"type": "llamaindex", "task": {...}},  # Document analysis
        {"type": "langgraph", "task": {...}},   # Approval
        {"type": "agno", "task": {...}},        # Implementation
    ]
})

# ❌ Bad: Force everything into one orchestrator
langgraph.execute({
    "nodes": ["document_analysis", "approval", "implementation"],
    # LlamaIndex is better for document_analysis
    # Agno is better for implementation
})
```

---

### 3. Let the Selector Decide

```python
# ✅ Good: Use selector for automatic choice
from mahavishnu.patterns.hybrid_orchestration import select_orchestrator

orch_type = select_orchestrator(
    task_type="my_task",
    requires_state=True,
)
# Automatically selects best orchestrator

# ❌ Bad: Hardcode orchestrator choice
orch_type = OrchestratorType.LANGGRAPH  # What if requirements change?
```

---

## Testing

```python
# Test orchestrator selection
from mahavishnu.patterns.hybrid_orchestration import OrchestratorSelector

selector = OrchestratorSelector()

# Test scheduled task
assert selector.select(
    task_type="batch",
    requires_scheduling=True,
) == OrchestratorType.PREFECT

# Test RAG task
assert selector.select(
    task_type="rag_workflow",
) == OrchestratorType.LLAMAINDEX

# Test stateful task
assert selector.select(
    task_type="generic",
    requires_state=True,
) == OrchestratorType.LANGGRAPH

# Test default
assert selector.select(
    task_type="simple",
) == OrchestratorType.AGNO
```

---

## Performance Considerations

### Orchestrator Overhead

| Orchestrator | Setup Time | Runtime | Overhead |
|--------------|------------|---------|----------|
| Agno | <10ms | Fast | Lowest |
| LlamaIndex | 50-100ms | Medium | Low |
| LangGraph | 100-200ms | Medium | High (checkpointing) |
| Prefect | 200-500ms | Slow | Highest |

### Recommendations

- **Simple tasks**: Use Agno for minimal overhead
- **RAG workflows**: Use LlamaIndex for optimized vector search
- **Stateful workflows**: Accept LangGraph overhead for checkpointing benefits
- **Scheduled tasks**: Accept Prefect overhead for scheduling capabilities

---

## Troubleshooting

### Issue: Orchestrator Selection Not Optimal

**Symptom**: Selected orchestrator doesn't match requirements

**Solution**: Check requirements parameters
```python
# Check requirements
orch_type = select_orchestrator(
    task_type="my_task",
    requires_state=True,  # Did you set this?
    requires_routing=True,  # Did you set this?
    requires_scheduling=False,  # Did you set this?
)
```

---

### Issue: Hybrid Workflow Fails

**Symptom**: Hybrid workflow raises ValueError

**Solution**: Check stage structure
```python
# Each stage must have 'type' and 'task'
{
    "stages": [
        {
            "type": "llamaindex",  # Required
            "task": {...},           # Required
        },
    ]
}
```

---

## Examples

### Example 1: CI/CD Pipeline with Approval

```python
from mahavishnu.patterns.hybrid_orchestration import HybridOrchestrator

hybrid = HybridOrchestrator()

result = await hybrid.execute({
    "stages": [
        {
            "type": "agno",
            "task": {
                "agents": ["tester"],
                "task": "Run tests",
            },
        },
        {
            "type": "langgraph",
            "task": {
                "workflow": {
                    "nodes": ["review", "approve", "deploy"],
                    "conditional": {
                        "approve": lambda s: "deploy" if s["approved"] else "end"
                    },
                },
                "input": {"test_results": "..."},
            },
        },
    ]
})
```

---

### Example 2: Document-Based Code Generation

```python
result = await hybrid.execute({
    "stages": [
        {
            "type": "llamaindex",
            "task": {
                "type": "document_analysis",
                "docs": ["spec.pdf", "requirements.docx"],
            },
        },
        {
            "type": "agno",
            "task": {
                "agents": ["python-pro"],
                "task": "Generate code from spec",
                "input": {"spec": "..."},
            },
        },
    ]
})
```

---

### Example 3: Scheduled Data Pipeline

```python
result = await hybrid.execute({
    "stages": [
        {
            "type": "prefect",
            "task": {
                "type": "scheduled_etl",
                "schedule": "0 2 * * *",
                "sources": ["database1", "api1"],
            },
        },
        {
            "type": "langgraph",
            "task": {
                "workflow": {
                    "nodes": ["extract", "transform", "load", "verify"],
                },
            },
        },
    ]
})
```

---

## Further Reading

- [LangGraph Adapter Documentation](./langgraph_adapter.md)
- [LlamaIndex Adapter Documentation](./llamaindex_adapter.md)
- [Orchestrator Architecture](./ORCHESTRATOR_ARCHITECTURE.md)
- [Multi-Agent Workflows](./MULTI_AGENT_WORKFLOWS.md)
