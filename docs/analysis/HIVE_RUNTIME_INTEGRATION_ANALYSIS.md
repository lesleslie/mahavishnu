# Hive-Mahavishnu Runtime Integration Analysis

## Executive Summary

**Runtime Compatibility Score: 8/10**

The Mahavishnu pool infrastructure provides a solid foundation for executing Hive-generated agent graphs. Key strengths include the existing dependency graph system, WebSocket streaming, and multi-pool architecture. The primary gap is the absence of an agent graph execution engine.

---

## 1. Current Pool Infrastructure Analysis

### 1.1 Pool Types and Capabilities

| Pool Type | Latency | Isolation | Scalability | Best For |
|-----------|---------|-----------|-------------|----------|
| **MahavishnuPool** | Low (<10ms) | Process-level | Dynamic (min-max workers) | Development, debugging, CI/CD |
| **SessionBuddyPool** | Medium (~50ms) | Remote process | Fixed (3 workers) | Distributed workloads, memory integration |
| **KubernetesPool** | Medium-High | Container | Auto-scaling via HPA | Production, cloud-native |

### 1.2 Key Infrastructure Components

**PoolManager** (`/Users/les/Projects/mahavishnu/mahavishnu/pools/manager.py`):
- O(log n) heap-based routing via `_get_least_loaded_pool()`
- Concurrent collection with `asyncio.gather()` for 10x performance
- 4 routing strategies: `ROUND_ROBIN`, `LEAST_LOADED`, `RANDOM`, `AFFINITY`
- Message bus for inter-pool communication

**BasePool Interface** (`/Users/les/Projects/mahavishnu/mahavishnu/pools/base.py`):
```python
class BasePool(ABC):
    async def start(self) -> str
    async def execute_task(self, task: dict[str, Any]) -> dict[str, Any]
    async def execute_batch(self, tasks: list[dict[str, Any]]) -> dict[str, dict[str, Any]]
    async def scale(self, target_worker_count: int) -> None
    async def health_check(self) -> dict[str, Any]
    async def get_metrics(self) -> PoolMetrics
    async def collect_memory(self) -> list[dict[str, Any]]
    async def stop(self) -> None
```

**WorkerManager** (`/Users/les/Projects/mahavishnu/mahavishnu/workers/manager.py`):
- Worker types: `terminal-qwen`, `terminal-claude`, `container-executor`
- Semaphore-based concurrency control (`max_concurrent: int`)
- Batch execution with concurrent `asyncio.gather()`

### 1.3 Dependency Graph System

**Existing Implementation** (`/Users/les/Projects/mahavishnu/mahavishnu/core/dependency_graph.py`):

```python
class DependencyGraph:
    # Core operations
    def add_task(self, task_id: str, metadata: dict | None) -> None
    def add_dependency(self, dependency_id: str, dependent_id: str, ...) -> DependencyEdge

    # Graph queries
    def get_dependencies(self, task_id: str) -> list[str]
    def get_dependents(self, task_id: str) -> list[str]
    def get_ready_tasks() -> list[str]  # Tasks with satisfied dependencies
    def get_blocked_tasks() -> list[str]

    # Algorithms
    def topological_sort() -> list[str]  # Kahn's algorithm
    def detect_cycles() -> list[list[str]]  # DFS-based cycle detection
    def has_cycle() -> bool
    def get_transitive_dependencies(self, task_id: str) -> set[str]

    # Serialization
    def to_dict() -> dict[str, Any]
    @classmethod
    def from_dict(cls, data: dict) -> DependencyGraph
```

**Key Features for Hive Integration**:
- DAG enforcement with cycle detection
- Topological sort for execution ordering
- Status tracking per edge (`PENDING`, `SATISFIED`, `FAILED`, `CANCELLED`)
- Task metadata storage

### 1.4 WebSocket Infrastructure

**MahavishnuWebSocketServer** (`/Users/les/Projects/mahavishnu/mahavishnu/websocket/server.py`):

```python
class MahavishnuWebSocketServer(WebSocketServer):
    # Channels
    # - workflow:{workflow_id}
    # - pool:{pool_id}
    # - worker:{worker_id}
    # - global

    # Broadcast methods
    async def broadcast_workflow_started(self, workflow_id: str, metadata: dict)
    async def broadcast_workflow_stage_completed(self, workflow_id: str, stage_name: str, result: dict)
    async def broadcast_workflow_completed(self, workflow_id: str, final_result: dict)
    async def broadcast_workflow_failed(self, workflow_id: str, error: str)
    async def broadcast_worker_status_changed(self, worker_id: str, status: str, pool_id: str)
    async def broadcast_pool_status_changed(self, pool_id: str, status: dict)
```

**Security Features**:
- Token bucket rate limiting per connection
- JWT authentication support
- TLS/WSS encryption
- Channel-based authorization

### 1.5 Memory Aggregation

**MemoryAggregator** (`/Users/les/Projects/mahavishnu/mahavishnu/pools/memory_aggregator.py`):

```python
class MemoryAggregator:
    # Collect and sync
    async def collect_and_sync(self, pool_manager) -> dict[str, Any]

    # Cross-pool search via Session-Buddy
    async def cross_pool_search(self, query: str, pool_manager, limit: int) -> list[dict]

    # Sync to Akosha for analytics
    async def _sync_to_akosha(self, summary: dict) -> None
```

---

## 2. Hive Agent Graph Format Analysis

### 2.1 Expected Hive Graph Structure

Based on typical agent graph frameworks (LangGraph, Agno, etc.):

```python
# Expected Hive Graph Format
{
    "graph_id": "ulid_xxx",
    "name": "Research Assistant Graph",
    "version": "1.0.0",
    "nodes": [
        {
            "node_id": "researcher",
            "node_type": "agent",  # agent, tool, router, conditional
            "config": {
                "model": "claude-3-sonnet",
                "system_prompt": "You are a researcher...",
                "tools": ["web_search", "read_file"],
                "max_iterations": 10
            },
            "inputs": ["query"],
            "outputs": ["research_result"]
        },
        {
            "node_id": "summarizer",
            "node_type": "agent",
            "config": {
                "model": "claude-3-haiku",
                "system_prompt": "Summarize the research...",
            },
            "inputs": ["research_result"],
            "outputs": ["summary"]
        }
    ],
    "edges": [
        {
            "source": "entry",
            "target": "researcher",
            "edge_type": "always"
        },
        {
            "source": "researcher",
            "target": "summarizer",
            "edge_type": "on_success"
        },
        {
            "source": "summarizer",
            "target": "exit",
            "edge_type": "always"
        }
    ],
    "entry_point": "researcher",
    "exit_points": ["exit"],
    "state_schema": {
        "query": "str",
        "research_result": "str | None",
        "summary": "str | None"
    }
}
```

### 2.2 Graph-to-Execution Mapping

| Hive Node Type | Mahavishnu Execution Strategy |
|----------------|-------------------------------|
| `agent` | Execute via WorkerManager on MahavishnuPool |
| `tool` | Execute as function call (local or remote) |
| `router` | Conditional logic in executor |
| `conditional` | Branch evaluation in executor |
| `parallel` | Spawn concurrent workers via `execute_batch()` |
| `human_input` | WebSocket event for user input |

---

## 3. Recommended Pool Strategy

### 3.1 Primary Recommendation: Hybrid Approach

**For Hive Agent Execution**:

1. **MahavishnuPool for Agent Nodes**
   - Low latency for LLM calls (already network-bound)
   - Dynamic scaling based on graph parallelism
   - Direct access to Session-Buddy for memory

2. **SessionBuddyPool for Memory-Intensive Operations**
   - Cross-session memory persistence
   - 3 workers per instance for parallel memory queries
   - Native Session-Buddy integration

3. **KubernetesPool for Production (Future)**
   - Horizontal scaling for high-throughput
   - Isolation for untrusted agent code
   - Cloud resource management

### 3.2 Pool Selection Algorithm

```python
def select_pool_for_node(node: HiveNode) -> str:
    """Select optimal pool for Hive node execution."""

    if node.node_type == "agent":
        # Agents need low latency and LLM access
        return "mahavishnu"

    elif node.node_type == "tool":
        if node.config.get("requires_memory"):
            return "session_buddy"
        return "mahavishnu"

    elif node.node_type == "parallel":
        # Parallel execution benefits from more workers
        return "mahavishnu"  # Supports dynamic scaling

    else:
        return "mahavishnu"  # Default
```

---

## 4. Graph-to-Execution Pipeline Design

### 4.1 Pipeline Components

```
[ Hive Graph JSON ]
        |
        v
[ GraphParser ]          # Parse and validate Hive format
        |
        v
[ GraphCompiler ]        # Convert to Mahavishnu DependencyGraph
        |
        v
[ ExecutionPlanner ]     # Generate execution plan with parallel stages
        |
        v
[ GraphExecutor ]        # Execute nodes respecting dependencies
        |
        v
[ ResultAggregator ]     # Collect results, update state
```

### 4.2 Core Implementation Classes

```python
# File: /Users/les/Projects/mahavishnu/mahavishnu/hive/graph_parser.py

from pydantic import BaseModel
from typing import Any

class HiveNode(BaseModel):
    node_id: str
    node_type: str  # agent, tool, router, conditional, parallel
    config: dict[str, Any]
    inputs: list[str]
    outputs: list[str]

class HiveEdge(BaseModel):
    source: str
    target: str
    edge_type: str  # always, on_success, on_failure, conditional

class HiveGraph(BaseModel):
    graph_id: str
    name: str
    version: str
    nodes: list[HiveNode]
    edges: list[HiveEdge]
    entry_point: str
    exit_points: list[str]
    state_schema: dict[str, str]


class GraphParser:
    """Parse Hive graph format into internal representation."""

    @staticmethod
    def parse(raw_graph: dict[str, Any]) -> HiveGraph:
        """Parse and validate Hive graph JSON."""
        return HiveGraph(**raw_graph)

    @staticmethod
    def validate(graph: HiveGraph) -> list[str]:
        """Validate graph structure. Returns list of errors."""
        errors = []

        # Check for orphan nodes
        connected_nodes = set()
        for edge in graph.edges:
            connected_nodes.add(edge.source)
            connected_nodes.add(edge.target)

        for node in graph.nodes:
            if node.node_id not in connected_nodes:
                if node.node_id != graph.entry_point and node.node_id not in graph.exit_points:
                    errors.append(f"Orphan node: {node.node_id}")

        # Check for missing entry point
        node_ids = {n.node_id for n in graph.nodes}
        if graph.entry_point not in node_ids:
            errors.append(f"Entry point not found: {graph.entry_point}")

        return errors
```

```python
# File: /Users/les/Projects/mahavishnu/mahavishnu/hive/graph_compiler.py

from mahavishnu.core.dependency_graph import (
    DependencyGraph,
    DependencyType,
    DependencyStatus,
)

class GraphCompiler:
    """Compile Hive graph to Mahavishnu DependencyGraph."""

    def compile(self, hive_graph: HiveGraph) -> DependencyGraph:
        """Convert Hive graph to execution dependency graph."""
        dag = DependencyGraph()

        # Add all nodes as tasks
        for node in hive_graph.nodes:
            dag.add_task(
                task_id=node.node_id,
                metadata={
                    "node_type": node.node_type,
                    "config": node.config,
                    "inputs": node.inputs,
                    "outputs": node.outputs,
                }
            )

        # Add edges as dependencies
        for edge in hive_graph.edges:
            dep_type = self._map_edge_type(edge.edge_type)
            dag.add_dependency(
                dependency_id=edge.source,
                dependent_id=edge.target,
                dependency_type=dep_type,
                metadata={"edge_type": edge.edge_type},
            )

        return dag

    def _map_edge_type(self, edge_type: str) -> DependencyType:
        """Map Hive edge type to DependencyType."""
        mapping = {
            "always": DependencyType.BLOCKS,
            "on_success": DependencyType.REQUIRES,
            "on_failure": DependencyType.RELATED,
            "conditional": DependencyType.SUBTASK,
        }
        return mapping.get(edge_type, DependencyType.BLOCKS)
```

```python
# File: /Users/les/Projects/mahavishnu/mahavishnu/hive/execution_planner.py

from dataclasses import dataclass
from typing import Any

@dataclass
class ExecutionStage:
    stage_id: int
    node_ids: list[str]  # Nodes that can run in parallel
    dependencies: list[str]  # Stages that must complete first

@dataclass
class ExecutionPlan:
    graph_id: str
    stages: list[ExecutionStage]
    total_nodes: int
    max_parallelism: int

class ExecutionPlanner:
    """Generate parallel execution plan from dependency graph."""

    def plan(self, dag: DependencyGraph, hive_graph: HiveGraph) -> ExecutionPlan:
        """Create execution plan with parallel stages."""
        stages = []
        completed = set()
        remaining = set(dag.get_all_tasks())

        stage_id = 0
        while remaining:
            # Find nodes with all dependencies satisfied
            ready = []
            for task_id in remaining:
                deps = dag.get_dependencies(task_id)
                if all(d in completed for d in deps):
                    ready.append(task_id)

            if not ready:
                # Cycle or error
                raise RuntimeError(f"No ready tasks, possible cycle. Remaining: {remaining}")

            # Group by execution profile for optimal parallelism
            stage = ExecutionStage(
                stage_id=stage_id,
                node_ids=ready,
                dependencies=[s.stage_id for s in stages],
            )
            stages.append(stage)

            completed.update(ready)
            remaining -= set(ready)
            stage_id += 1

        return ExecutionPlan(
            graph_id=hive_graph.graph_id,
            stages=stages,
            total_nodes=len(dag),
            max_parallelism=max(len(s.node_ids) for s in stages),
        )
```

```python
# File: /Users/les/Projects/mahavishnu/mahavishnu/hive/graph_executor.py

import asyncio
from typing import Any
from mahavishnu.pools.manager import PoolManager, PoolSelector
from mahavishnu.websocket.server import MahavishnuWebSocketServer

class GraphExecutor:
    """Execute Hive graph using Mahavishnu pools."""

    def __init__(
        self,
        pool_manager: PoolManager,
        websocket_server: MahavishnuWebSocketServer | None = None,
    ):
        self.pool_manager = pool_manager
        self.ws_server = websocket_server
        self._execution_states: dict[str, dict[str, Any]] = {}

    async def execute(
        self,
        hive_graph: HiveGraph,
        execution_plan: ExecutionPlan,
        initial_state: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute graph according to plan with state management."""
        execution_id = hive_graph.graph_id
        state = initial_state.copy()

        # Track execution
        self._execution_states[execution_id] = {
            "status": "running",
            "current_stage": 0,
            "completed_nodes": [],
            "failed_nodes": [],
            "state": state,
        }

        # Broadcast start
        if self.ws_server:
            await self.ws_server.broadcast_workflow_started(
                execution_id,
                {"graph_name": hive_graph.name, "total_stages": len(execution_plan.stages)}
            )

        try:
            for stage in execution_plan.stages:
                # Update state
                self._execution_states[execution_id]["current_stage"] = stage.stage_id

                # Execute stage (nodes can run in parallel)
                stage_results = await self._execute_stage(
                    stage, hive_graph, state, execution_id
                )

                # Update state with results
                for node_id, result in stage_results.items():
                    if result.get("success"):
                        state.update(result.get("outputs", {}))
                        self._execution_states[execution_id]["completed_nodes"].append(node_id)
                    else:
                        self._execution_states[execution_id]["failed_nodes"].append(node_id)
                        # Handle failure based on edge type

                # Broadcast stage completion
                if self.ws_server:
                    await self.ws_server.broadcast_workflow_stage_completed(
                        execution_id, f"stage_{stage.stage_id}", stage_results
                    )

            # Mark complete
            self._execution_states[execution_id]["status"] = "completed"

            # Broadcast completion
            if self.ws_server:
                await self.ws_server.broadcast_workflow_completed(execution_id, state)

            return {
                "success": True,
                "execution_id": execution_id,
                "final_state": state,
                "completed_nodes": self._execution_states[execution_id]["completed_nodes"],
            }

        except Exception as e:
            self._execution_states[execution_id]["status"] = "failed"

            if self.ws_server:
                await self.ws_server.broadcast_workflow_failed(execution_id, str(e))

            return {
                "success": False,
                "execution_id": execution_id,
                "error": str(e),
                "partial_state": state,
            }

    async def _execute_stage(
        self,
        stage: ExecutionStage,
        hive_graph: HiveGraph,
        state: dict[str, Any],
        execution_id: str,
    ) -> dict[str, dict[str, Any]]:
        """Execute all nodes in a stage concurrently."""
        node_map = {n.node_id: n for n in hive_graph.nodes}
        tasks = []

        for node_id in stage.node_ids:
            node = node_map[node_id]
            task = self._execute_node(node, state, execution_id)
            tasks.append((node_id, task))

        # Execute all nodes concurrently
        results = await asyncio.gather(
            *[t[1] for t in tasks],
            return_exceptions=True,
        )

        return {
            tasks[i][0]: self._format_result(r)
            for i, r in enumerate(results)
        }

    async def _execute_node(
        self,
        node: HiveNode,
        state: dict[str, Any],
        execution_id: str,
    ) -> dict[str, Any]:
        """Execute single node via appropriate pool."""
        # Select pool based on node type
        pool_type = self._select_pool_for_node(node)

        # Prepare task
        task = {
            "prompt": self._build_prompt(node, state),
            "node_type": node.node_type,
            "config": node.config,
            "execution_id": execution_id,
            "node_id": node.node_id,
        }

        # Route to pool
        result = await self.pool_manager.route_task(
            task,
            pool_selector=PoolSelector.LEAST_LOADED,
        )

        return result

    def _select_pool_for_node(self, node: HiveNode) -> str:
        """Select optimal pool for node type."""
        if node.node_type == "agent":
            return "mahavishnu"
        elif node.node_type == "tool" and node.config.get("requires_memory"):
            return "session_buddy"
        return "mahavishnu"

    def _build_prompt(self, node: HiveNode, state: dict[str, Any]) -> str:
        """Build execution prompt from node config and state."""
        system_prompt = node.config.get("system_prompt", "")

        # Inject state values for node inputs
        input_values = {}
        for input_name in node.inputs:
            if input_name in state:
                input_values[input_name] = state[input_name]

        return f"{system_prompt}\n\nInputs: {input_values}"

    def _format_result(self, result: Any) -> dict[str, Any]:
        """Format execution result."""
        if isinstance(result, Exception):
            return {"success": False, "error": str(result)}
        return result if isinstance(result, dict) else {"success": True, "output": result}
```

---

## 5. Execution Lifecycle

### 5.1 Initialization Phase

```python
async def initialize_hive_execution(
    hive_graph: dict[str, Any],
    pool_manager: PoolManager,
    session_buddy_client: Any,
) -> tuple[HiveGraph, DependencyGraph, ExecutionPlan]:
    """Initialize Hive graph for execution."""

    # 1. Parse graph
    parser = GraphParser()
    graph = parser.parse(hive_graph)
    errors = parser.validate(graph)
    if errors:
        raise ValueError(f"Invalid graph: {errors}")

    # 2. Compile to DAG
    compiler = GraphCompiler()
    dag = compiler.compile(graph)

    # 3. Generate execution plan
    planner = ExecutionPlanner()
    plan = planner.plan(dag, graph)

    # 4. Initialize memory context via Session-Buddy
    await session_buddy_client.store_memory({
        "content": f"Initializing graph: {graph.name}",
        "metadata": {
            "type": "hive_graph_initialization",
            "graph_id": graph.graph_id,
            "node_count": len(graph.nodes),
            "timestamp": datetime.utcnow().isoformat(),
        }
    })

    return graph, dag, plan
```

### 5.2 Execution Phase with Streaming

```python
async def execute_with_streaming(
    graph: HiveGraph,
    plan: ExecutionPlan,
    initial_input: dict[str, Any],
    pool_manager: PoolManager,
    ws_server: MahavishnuWebSocketServer,
) -> AsyncIterator[dict[str, Any]]:
    """Execute graph with real-time streaming updates."""

    executor = GraphExecutor(pool_manager, ws_server)
    state = initial_input.copy()

    # Subscribe client to workflow channel
    channel = f"workflow:{graph.graph_id}"

    for stage in plan.stages:
        # Yield stage start
        yield {
            "event": "stage_started",
            "stage_id": stage.stage_id,
            "nodes": stage.node_ids,
        }

        # Execute stage
        stage_results = await executor._execute_stage(stage, graph, state, graph.graph_id)

        # Yield stage results
        yield {
            "event": "stage_completed",
            "stage_id": stage.stage_id,
            "results": stage_results,
        }

        # Update state
        for node_id, result in stage_results.items():
            if result.get("success"):
                state.update(result.get("outputs", {}))

    # Yield final result
    yield {
        "event": "execution_completed",
        "final_state": state,
    }
```

### 5.3 Evolution Phase (Graph Modification)

```python
class GraphEvolutionManager:
    """Handle runtime graph modifications and redeployment."""

    def __init__(self, pool_manager: PoolManager):
        self.pool_manager = pool_manager
        self._active_graphs: dict[str, tuple[HiveGraph, ExecutionPlan]] = {}

    async def evolve_graph(
        self,
        graph_id: str,
        modifications: dict[str, Any],
    ) -> dict[str, Any]:
        """Apply modifications to running graph.

        Modifications:
        - Add/remove nodes
        - Change edge connections
        - Update node configurations
        - Adjust parallelism
        """
        if graph_id not in self._active_graphs:
            return {"success": False, "error": "Graph not active"}

        current_graph, current_plan = self._active_graphs[graph_id]

        # Apply modifications
        new_graph = self._apply_modifications(current_graph, modifications)

        # Recompile and replan
        compiler = GraphCompiler()
        new_dag = compiler.compile(new_graph)

        planner = ExecutionPlanner()
        new_plan = planner.plan(new_dag, new_graph)

        # Hot-swap (for future stages only)
        self._active_graphs[graph_id] = (new_graph, new_plan)

        return {
            "success": True,
            "graph_id": graph_id,
            "modifications_applied": list(modifications.keys()),
            "new_max_parallelism": new_plan.max_parallelism,
        }

    async def checkpoint_graph(self, graph_id: str) -> dict[str, Any]:
        """Create checkpoint for graph state."""
        if graph_id not in self._active_graphs:
            return {"success": False, "error": "Graph not active"}

        graph, plan = self._active_graphs[graph_id]

        # Serialize graph and state
        checkpoint = {
            "graph_id": graph_id,
            "graph": graph.model_dump(),
            "timestamp": datetime.utcnow().isoformat(),
        }

        # Persist via Session-Buddy
        # ...

        return checkpoint
```

---

## 6. API Specification

### 6.1 Graph Submission Endpoint

```python
# File: /Users/les/Projects/mahavishnu/mahavishnu/mcp/tools/hive_tools.py

from fastmcp import FastMCP
from pydantic import BaseModel

class SubmitGraphRequest(BaseModel):
    graph: dict[str, Any]  # Hive graph JSON
    initial_state: dict[str, Any] = {}
    execution_config: dict[str, Any] = {
        "pool_type": "mahavishnu",
        "max_parallelism": 10,
        "timeout_seconds": 300,
        "enable_streaming": True,
    }

class SubmitGraphResponse(BaseModel):
    execution_id: str
    status: str  # "queued", "running", "failed"
    graph_id: str
    estimated_duration_seconds: float | None

@mcp.tool()
async def hive_submit_graph(request: SubmitGraphRequest) -> SubmitGraphResponse:
    """Submit Hive-generated agent graph for execution.

    Args:
        request: Graph submission request with:
            - graph: Hive graph JSON (nodes, edges, entry/exit points)
            - initial_state: Initial state values for graph inputs
            - execution_config: Pool type, parallelism, timeout settings

    Returns:
        Execution ID and status for tracking

    Example:
        ```python
        result = await hive_submit_graph({
            "graph": {
                "graph_id": "research_001",
                "nodes": [...],
                "edges": [...],
                "entry_point": "researcher",
            },
            "initial_state": {"query": "What is quantum computing?"},
            "execution_config": {"pool_type": "mahavishnu"}
        })
        ```
    """
    # Implementation
    pass
```

### 6.2 Execution Status Streaming

```python
class ExecutionStatusRequest(BaseModel):
    execution_id: str
    include_state: bool = False
    include_intermediate_results: bool = False

class ExecutionStatusResponse(BaseModel):
    execution_id: str
    status: str  # "running", "completed", "failed", "paused"
    current_stage: int
    total_stages: int
    completed_nodes: list[str]
    failed_nodes: list[str]
    state: dict[str, Any] | None
    error: str | None

@mcp.tool()
async def hive_get_status(request: ExecutionStatusRequest) -> ExecutionStatusResponse:
    """Get current execution status.

    Args:
        request: Status request with:
            - execution_id: Execution to query
            - include_state: Include current graph state
            - include_intermediate_results: Include node outputs

    Returns:
        Current execution status and progress
    """
    pass

# WebSocket streaming (native)
# ws://localhost:8690/workflow/{execution_id}
# Events: stage_started, node_completed, stage_completed, execution_completed
```

### 6.3 Evolution Hook

```python
class EvolveGraphRequest(BaseModel):
    execution_id: str
    modifications: dict[str, Any]  # Graph modifications to apply

class EvolveGraphResponse(BaseModel):
    success: bool
    applied_modifications: list[str]
    new_plan_summary: dict[str, Any]
    error: str | None

@mcp.tool()
async def hive_evolve_graph(request: EvolveGraphRequest) -> EvolveGraphResponse:
    """Apply runtime modifications to executing graph.

    Supported Modifications:
    - add_node: Add new node to graph
    - remove_node: Remove node (if not running)
    - update_node_config: Change node configuration
    - add_edge: Add new edge connection
    - remove_edge: Remove edge
    - scale_parallelism: Adjust max parallel workers

    Args:
        request: Evolution request with execution_id and modifications

    Returns:
        Result of applying modifications

    Example:
        ```python
        result = await hive_evolve_graph({
            "execution_id": "exec_123",
            "modifications": {
                "add_node": {
                    "node_id": "reviewer",
                    "node_type": "agent",
                    "config": {"model": "claude-3-opus"}
                },
                "add_edge": {
                    "source": "summarizer",
                    "target": "reviewer"
                }
            }
        })
        ```
    """
    pass
```

### 6.4 Complete API Summary

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `hive_submit_graph` | MCP Tool | Submit graph for execution |
| `hive_get_status` | MCP Tool | Query execution status |
| `hive_evolve_graph` | MCP Tool | Modify running graph |
| `hive_list_executions` | MCP Tool | List active executions |
| `hive_cancel_execution` | MCP Tool | Cancel running execution |
| `hive_checkpoint` | MCP Tool | Create execution checkpoint |
| `hive_restore` | MCP Tool | Restore from checkpoint |
| `ws://host:8690/workflow/{id}` | WebSocket | Real-time execution stream |

---

## 7. Integration with Bodai Ecosystem

### 7.1 Memory Enhancement (Session-Buddy)

Replace Hive's stub memory with Session-Buddy:

```python
class HiveMemoryAdapter:
    """Adapter between Hive memory API and Session-Buddy."""

    def __init__(self, session_buddy_client):
        self.client = session_buddy_client

    async def store(self, key: str, value: Any, metadata: dict | None = None):
        """Store memory via Session-Buddy."""
        await self.client.store_memory({
            "content": json.dumps(value),
            "metadata": {
                "hive_key": key,
                "type": "hive_memory",
                **(metadata or {}),
            }
        })

    async def retrieve(self, key: str) -> Any | None:
        """Retrieve memory via Session-Buddy."""
        results = await self.client.search_conversations({
            "query": f"hive_key:{key}",
            "limit": 1,
        })
        if results:
            return json.loads(results[0]["content"])
        return None

    async def search(self, query: str, limit: int = 10) -> list[Any]:
        """Semantic search via Session-Buddy."""
        return await self.client.search_conversations({
            "query": query,
            "limit": limit,
        })
```

### 7.2 Quality Enhancement (Crackerjack)

Replace Hive's stub quality with Crackerjack:

```python
class HiveQualityAdapter:
    """Adapter between Hive quality API and Crackerjack."""

    def __init__(self, crackerjack_client):
        self.client = crackerjack_client

    async def evaluate_output(
        self,
        output: str,
        criteria: dict[str, Any],
    ) -> dict[str, Any]:
        """Evaluate output quality via Crackerjack."""
        # Run quality checks
        results = await self.client.run_quality_checks({
            "code": output,
            "checks": criteria.get("checks", ["lint", "type", "test"]),
        })

        return {
            "score": results.get("score", 0),
            "passed": results.get("passed", False),
            "details": results.get("details", {}),
        }
```

### 7.3 Analytics Enhancement (Akosha)

Cross-graph analytics via Akosha:

```python
class HiveAnalyticsAdapter:
    """Adapter for Akosha analytics integration."""

    def __init__(self, akosha_client):
        self.client = akosha_client

    async def record_execution_metrics(
        self,
        graph_id: str,
        execution_id: str,
        metrics: dict[str, Any],
    ):
        """Record execution metrics to Akosha."""
        await self.client.aggregate_metrics({
            "source": "hive",
            "graph_id": graph_id,
            "execution_id": execution_id,
            "metrics": metrics,
            "timestamp": datetime.utcnow().isoformat(),
        })

    async def get_graph_performance(self, graph_id: str) -> dict[str, Any]:
        """Get historical performance for graph pattern."""
        return await self.client.detect_patterns({
            "type": "graph_performance",
            "graph_id": graph_id,
        })
```

---

## 8. Implementation Roadmap

### Phase 1: Core Infrastructure (Week 1-2)
- [ ] Create `mahavishnu/hive/` module structure
- [ ] Implement `GraphParser` for Hive graph format
- [ ] Implement `GraphCompiler` to DependencyGraph
- [ ] Implement `ExecutionPlanner` for parallel stages

### Phase 2: Execution Engine (Week 3-4)
- [ ] Implement `GraphExecutor` with pool routing
- [ ] Add WebSocket streaming for execution events
- [ ] Implement state management across nodes
- [ ] Add error handling and retry logic

### Phase 3: API Layer (Week 5)
- [ ] Create MCP tools for graph submission
- [ ] Implement status streaming endpoint
- [ ] Add evolution hook for graph modifications
- [ ] Create checkpoint/restore functionality

### Phase 4: Ecosystem Integration (Week 6)
- [ ] Integrate Session-Buddy for memory
- [ ] Integrate Crackerjack for quality
- [ ] Integrate Akosha for analytics
- [ ] Add monitoring dashboards

---

## 9. Risk Assessment

| Risk | Impact | Mitigation |
|------|--------|------------|
| Hive graph format incompatible with DAG | High | Add format adapter layer |
| Parallel execution exceeds pool capacity | Medium | Dynamic pool scaling |
| WebSocket connection drops during stream | Medium | Reconnect with replay |
| Graph evolution causes inconsistent state | High | Version-controlled state updates |
| Memory pressure from large graphs | Medium | Implement graph partitioning |

---

## 10. Conclusion

The Mahavishnu pool infrastructure is well-suited for Hive agent execution with these key advantages:

1. **Existing Dependency Graph**: Direct mapping from Hive graphs to Mahavishnu DAG
2. **Pool Flexibility**: MahavishnuPool for low latency, SessionBuddyPool for memory
3. **WebSocket Streaming**: Built-in real-time event broadcasting
4. **Memory Aggregation**: Native Session-Buddy integration
5. **Adaptive Routing**: Statistical router for intelligent pool selection

**Primary Gap**: Need to implement the Hive-specific execution layer (GraphParser, GraphCompiler, GraphExecutor).

**Recommended Next Step**: Implement Phase 1 core infrastructure to validate the integration concept.
