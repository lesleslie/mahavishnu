# Session-Buddy Worker Integration Proposals

**Date**: 2026-01-30
**Status**: Architectural Proposals
**Priority**: High - Defines next-phase worker orchestration

---

## Executive Summary

Session-Buddy has **limited worker management capabilities** (manages background agents like the ConsciousAgent), but is not a full worker orchestration system. This document proposes **3 architectural approaches** for integrating Session-Buddy with Mahavishnu's worker system, ranging from lightweight integration to full hierarchical orchestration.

---

## Current State Analysis

### Session-Buddy Capabilities

**Current Session-Buddy Features:**
- ✅ **Memory Storage**: `store_memory`, `search_memories` (persistent knowledge)
- ✅ **ConsciousAgent**: Background memory optimization (1 agent instance)
- ✅ **Session Tracking**: Checkpoints, session lifecycle management
- ✅ **Knowledge Graph**: Entity extraction, relationship mapping
- ❌ **No Worker Spawning**: Cannot launch terminals/containers
- ❌ **No Task Distribution**: Cannot execute tasks across workers
- ❌ **No Progress Monitoring**: Cannot track worker execution

**What Session-Buddy CAN Do:**
- Store worker execution results as memories
- Provide semantic search over worker outputs
- Maintain conversation context across worker sessions
- Background analysis (ConsciousAgent for memory optimization)

### Mahavishnu Worker Capabilities

**Current Mahavishnu Features:**
- ✅ **Worker Spawning**: Launch Qwen/Claude terminals, containers
- ✅ **Task Execution**: Execute prompts across workers
- ✅ **Progress Monitoring**: stream-json parsing, status tracking
- ✅ **Concurrent Execution**: Semaphore-based limiting (1-100 workers)
- ⚠️ **Session-Buddy Storage**: Stub integration (not fully implemented)

**What Mahavishnu DOES:**
- Spawns and manages worker lifecycles
- Distributes tasks across workers
- Monitors execution progress
- Aggregates results

---

## Architectural Proposal 1: Lightweight Storage Integration ⚡

**Complexity**: Low | **Effort**: 1-2 days | **Value**: High

### Overview

Mahavishnu manages workers; Session-Buddy provides persistent storage and search. Session-Buddy remains a **passive knowledge store**.

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Mahavishnu Orchestrator                   │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │              WorkerManager (Active)                      │ │
│  │  - Spawn Qwen/Claude/Container workers                  │ │
│  │  - Execute tasks                                       │ │
│  │  - Monitor progress                                    │ │
│  └─────────────────────────────────────────────────────────┘ │
│                          │                                    │
│                          ▼                                    │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │         Session-Buddy Client (Storage Only)             │ │
│  │  - store_memory(worker results)                        │ │
│  │  - search_memories(find past executions)                │ │
│  └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

### Implementation

**Step 1**: Complete Session-Buddy storage in workers
```python
# mahavishnu/workers/terminal.py
async def _store_result_in_session_buddy(self, result, task):
    """Store worker execution result in Session-Buddy."""
    if not self.session_buddy_client:
        return

    await self.session_buddy_client.call_tool(
        "store_memory",
        arguments={
            "content": result.output,
            "metadata": {
                "type": "worker_execution",
                "worker_id": result.worker_id,
                "worker_type": self.worker_type,
                "task_prompt": task.get("prompt"),
                "status": result.status.value,
                "duration_seconds": result.duration_seconds,
                "timestamp": result.timestamp,
                "repo": task.get("repo"),
                "command": task.get("command"),
            }
        }
    )
```

**Step 2**: Add MCP tool for searching worker history
```python
# mahavishnu/mcp/tools/worker_tools.py

@mcp.tool()
async def worker_search_history(
    query: str,
    worker_type: str | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Search historical worker executions via Session-Buddy.

    Args:
        query: Search query (semantic or keyword)
        worker_type: Filter by worker type
        limit: Max results (default: 10)

    Returns:
        List of matching worker executions
    """
    if not session_buddy_client:
        raise RuntimeError("Session-Buddy not connected")

    # Search via Session-Buddy's semantic search
    memories = await session_buddy_client.call_tool(
        "search_memories",
        arguments={
            "query": f"{query} {worker_type or ''}",
            "category": "worker_execution",
            "limit": limit,
        }
    )

    return memories.get("results", [])
```

### Pros & Cons

✅ **Pros:**
- Simple to implement (1-2 days)
- Clear separation of concerns
- Mahavishnu controls orchestration
- Session-Buddy focuses on knowledge storage
- No changes to Session-Buddy required

❌ **Cons:**
- Session-Buddy doesn't manage workers
- No hierarchical orchestration
- Single point of integration

---

## Architectural Proposal 2: Hierarchical Orchestration 🏗️

**Complexity**: Medium | **Effort**: 3-5 days | **Value**: Very High

### Overview

**Mahavishnu manages Session-Buddy instances**, each managing up to 3 workers. Session-Buddy becomes a **worker pool manager** with Mahavishnu as the orchestrator.

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                Mahavishnu Orchestrator (Top Level)            │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │          WorkerPoolManager (NEW)                         │ │
│  │  - Launch Session-Buddy instances                       │ │
│  │  - Distribute work across pools                          │ │
│  │  - Monitor pool health                                  │ │
│  └─────────────────────────────────────────────────────────┘ │
│                          │                                    │
│        ┌─────────────────┼─────────────────┐                 │
│        │                 │                 │                 │
│        ▼                 ▼                 ▼                 │
│  ┌──────────┐      ┌──────────┐      ┌──────────┐           │
│  │  Pool 1  │      │  Pool 2  │      │  Pool 3  │           │
│  │ (SB Inst) │      │ (SB Inst) │      │ (SB Inst) │           │
│  └────┬─────┘      └────┬─────┘      └────┬─────┘           │
│       │                │                │                   │
│       └─────┬────────────┴────┬────────────┘                   │
│             │                 │                              │
│  Each Session-Buddy manages 3 workers:                       │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │           Session-Buddy Instance (Worker Pool)          │ │
│  │  ┌──────────────┬──────────────┬──────────────┐         │ │
│  │  │   Worker 1   │   Worker 2   │   Worker 3   │         │ │
│  │  │   (Qwen)     │  (Claude)    │ (Container)  │         │ │
│  │  └──────────────┴──────────────┴──────────────┘         │ │
│  │  - Spawn workers (via Mahavishnu API)                   │ │
│  │  - Distribute tasks within pool                         │ │
│  │  - Store results in local memory                       │ │
│  │  - Push to Akosha on shutdown                         │ │
│  └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
                   ┌─────────────────────┐
                   │   Akosha (Central)  │
                   │  - Aggregate results │
                   │  - Cross-pool search │
                   └─────────────────────┘
```

### Implementation

**Phase 1**: Add WorkerPoolManager to Mahavishnu

```python
# mahavishnu/workers/pool_manager.py (NEW)

class WorkerPool:
    """A pool of 3 workers managed by Session-Buddy instance."""

    def __init__(
        self,
        pool_id: str,
        session_buddy_client: Any,
        worker_manager: WorkerManager,
    ):
        self.pool_id = pool_id
        self.session_buddy_client = session_buddy_client
        self.worker_manager = worker_manager
        self.workers: dict[str, BaseWorker] = {}
        self.max_workers = 3

    async def allocate_workers(
        self,
        worker_types: list[str],
    ) -> dict[str, str]:
        """Allocate workers for this pool.

        Returns:
            Mapping of allocation_id -> worker_id
        """
        if len(worker_types) > self.max_workers:
            raise ValueError(f"Pool max 3 workers, requested {len(worker_types)}")

        allocated = {}
        for i, worker_type in enumerate(worker_types):
            worker_ids = await self.worker_manager.spawn_workers(
                worker_type=worker_type,
                count=1,
            )
            allocation_id = f"{self.pool_id}_worker_{i}"
            allocated[allocation_id] = worker_ids[0]
            self.workers[allocation_id] = worker_ids[0]

        return allocated

    async def execute_on_pool(
        self,
        tasks: list[dict[str, Any]],
    ) -> dict[str, WorkerResult]:
        """Execute tasks across pool workers."""
        # Distribute tasks across workers in pool
        allocation_ids = list(self.workers.keys())

        results = {}
        for allocation_id, task in zip(allocation_ids, tasks):
            worker_id = self.workers[allocation_id]
            result = await self.worker_manager.execute_task(
                worker_id=worker_id,
                task=task,
            )
            results[allocation_id] = result

        return results

    async def shutdown_and_push(self):
        """Shutdown pool and push results to Akosha."""
        # Collect all worker results
        results = await self.worker_manager.collect_results(
            worker_ids=list(self.workers.values())
        )

        # Push to Akosha via Session-Buddy
        if self.session_buddy_client:
            await self.session_buddy_client.call_tool(
                "push_to_akosha",
                arguments={
                    "pool_id": self.pool_id,
                    "results": [r.to_dict() for r in results.values()],
                    "timestamp": datetime.now().isoformat(),
                }
            )

        # Close all workers
        await self.worker_manager.close_all()


class WorkerPoolManager:
    """Manage multiple Session-Buddy worker pools."""

    def __init__(
        self,
        worker_manager: WorkerManager,
        session_buddy_factory: Any,
        max_pools: int = 10,
    ):
        self.worker_manager = worker_manager
        self.session_buddy_factory = session_buddy_factory
        self.max_pools = max_pools
        self.pools: dict[str, WorkerPool] = {}

    async def create_pool(
        self,
        pool_config: dict[str, Any],
    ) -> str:
        """Create a new worker pool.

        Args:
            pool_config: {pool_id, worker_types}

        Returns:
            pool_id
        """
        if len(self.pools) >= self.max_pools:
            raise RuntimeError(f"Max {self.max_pools} pools reached")

        pool_id = pool_config.get("pool_id", f"pool_{len(self.pools)}")

        # Create Session-Buddy client for this pool
        sb_client = await self.session_buddy_factory.create_instance()

        # Create worker pool
        pool = WorkerPool(
            pool_id=pool_id,
            session_buddy_client=sb_client,
            worker_manager=self.worker_manager,
        )

        # Allocate workers
        await pool.allocate_workers(pool_config.get("worker_types", ["terminal-qwen"]))

        self.pools[pool_id] = pool
        return pool_id

    async def execute_on_pools(
        self,
        pool_tasks: dict[str, list[dict[str, Any]]],
    ) -> dict[str, dict[str, WorkerResult]]:
        """Execute tasks across multiple pools.

        Args:
            pool_tasks: {pool_id: [tasks]}

        Returns:
            {pool_id: {allocation_id: WorkerResult}}
        """
        results = {}
        for pool_id, tasks in pool_tasks.items():
            pool = self.pools.get(pool_id)
            if not pool:
                raise ValueError(f"Pool not found: {pool_id}")

            pool_results = await pool.execute_on_pool(tasks)
            results[pool_id] = pool_results

        return results

    async def shutdown_pool(self, pool_id: str):
        """Shutdown a pool and push to Akosha."""
        pool = self.pools.get(pool_id)
        if pool:
            await pool.shutdown_and_push()
            del self.pools[pool_id]
```

**Phase 2**: Add Akosha Integration Tools

```python
# mahavishnu/mcp/tools/pool_tools.py (NEW)

@mcp.tool()
async def pool_create(
    worker_types: list[str] = ["terminal-qwen", "terminal-claude", "container-executor"],
    pool_id: str | None = None,
) -> dict[str, Any]:
    """Create a new worker pool managed by Session-Buddy.

    Args:
        worker_types: List of worker types (max 3)
        pool_id: Optional custom pool ID

    Returns:
        Pool creation result with pool_id
    """
    pool_mgr = get_worker_pool_manager()

    pool_id = await pool_mgr.create_pool({
        "pool_id": pool_id,
        "worker_types": worker_types,
    })

    return {
        "pool_id": pool_id,
        "status": "created",
        "workers": worker_types,
    }

@mcp.tool()
async def pool_execute(
    pool_id: str,
    tasks: list[dict[str, Any]],
) -> dict[str, Any]:
    """Execute tasks on a specific pool.

    Args:
        pool_id: Pool identifier
        tasks: List of tasks (max 3)

    Returns:
        Execution results by allocation
    """
    pool_mgr = get_worker_pool_manager()

    results = await pool_mgr.execute_on_pools({
        pool_id: tasks,
    })

    return {
        "pool_id": pool_id,
        "results": results[pool_id],
    }

@mcp.tool()
async def pool_shutdown(pool_id: str) -> dict[str, Any]:
    """Shutdown a pool and push results to Akosha.

    Args:
        pool_id: Pool to shutdown

    Returns:
        Shutdown confirmation
    """
    pool_mgr = get_worker_pool_manager()

    await pool_mgr.shutdown_pool(pool_id)

    return {
        "pool_id": pool_id,
        "status": "shutdown",
        "pushed_to_akosha": True,
    }
```

### Pros & Cons

✅ **Pros:**
- Hierarchical orchestration (Mahavishnu → Session-Buddy → Workers)
- Session-Buddy manages small worker groups (3 workers each)
- Natural scaling: Add more pools for more workers
- Session-Buddy instances can be ephemeral (container-friendly)
- Each pool has local memory + Akosha backup

❌ **Cons:**
- More complex architecture
- Requires Session-Buddy enhancements (worker allocation APIs)
- Multiple Session-Buddy instances to manage
- Pool lifecycle management overhead

---

## Architectural Proposal 3: Container-Native Session-Buddy 🐳

**Complexity**: High | **Effort**: 5-7 days | **Value**: Very High

### Overview

**Each container gets its own Session-Buddy instance** that pushes memories to Akosha before shutdown. Mahavishnu orchestrates containers, not workers directly.

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                Mahavishnu Orchestrator                       │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │          ContainerOrchestrator (NEW)                    │ │
│  │  - Launch containers with embedded Session-Buddy        │ │
│  │  - Distribute work across containers                    │ │
│  │  - Monitor container health                            │ │
│  └─────────────────────────────────────────────────────────┘ │
│                          │                                    │
│        ┌─────────────────┼─────────────────┐                 │
│        │                 │                 │                 │
│        ▼                 ▼                 ▼                 │
│  ┌──────────┐      ┌──────────┐      ┌──────────┐           │
│  │Container │      │Container │      │Container │           │
│  │   #1     │      │   #2     │      │   #3     │           │
│  └────┬─────┘      └────┬─────┘      └────┬─────┘           │
│       │                │                │                   │
│       └─────────┬──────┴──────────────┘                   │
│                 │                                         │
│                 ▼                                         │
│  ┌────────────────────────────────────────────────────────┐ │
│  │       Container (isolated environment)                 │ │
│  │  ┌──────────────────────────────────────────────────┐ │ │
│  │  │    Session-Buddy (Embedded Instance)             │ │ │
│  │  │  ┌────────────────────────────────────────────┐  │ │ │
│  │  │  │         Workers (managed by SB)             │  │ │
│  │  │  │  ┌─────────┬─────────┬─────────┐           │  │ │ │
│  │  │  │  │Worker 1 │Worker 2 │Worker 3 │           │  │ │ │
│  │  │  │  │(Qwen)   │(Claude) │(Script) │           │  │ │ │
│  │  │  │  └─────────┴─────────┴─────────┘           │  │ │ │
│  │  │  └────────────────────────────────────────────┘  │ │ │
│  │  │                                                    │ │ │
│  │  │  On Container Shutdown:                           │ │ │
│  │  │  1. Collect all worker results                     │ │ │
│  │  │  2. Push to Akosha (via sidecar)                  │ │ │
│  │  │  3. Shutdown gracefully                             │ │ │
│  │  └──────────────────────────────────────────────────┘ │ │
│  └────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
                   ┌─────────────────────┐
                   │   Akosha (Central)  │
                   │  - Aggregate results │
                   │  - Persistent storage │
                   └─────────────────────┘
```

### Implementation

**Phase 1**: Container Image with Embedded Session-Buddy

```dockerfile
# Dockerfile.worker-container
FROM python:3.13-slim

# Install dependencies
RUN pip install session-buddy mahavishnu-worker

# Copy Session-Buddy configuration
COPY settings/worker-sb.yaml /app/settings/

# Expose MCP port for Akosha sync
EXPOSE 8678

# Entry point: Start Session-Buddy with workers
CMD ["python", "-m", "session_buddy.worker_server", "--mode=container"]
```

**Phase 2**: Session-Buddy Worker Server (New)

```python
# session_buddy/worker_server.py (NEW in Session-Buddy)

"""Session-Buddy server that manages workers in containerized environments."""

import asyncio
import signal
from pathlib import Path

from session_buddy.core.server import SessionBuddyServer
from session_buddy.worker.manager import ContainerWorkerManager


class ContainerSessionBuddy:
    """Session-Buddy instance that manages workers within a container.

    Lifecycle:
    1. Start on container launch
    2. Spawn up to 3 workers
    3. Execute tasks pushed from Mahavishnu
    4. Collect results
    5. Push to Akosha on shutdown signal
    """

    def __init__(self, config_path: Path):
        self.config_path = config_path
        self.server = SessionBuddyServer(config_path)
        self.worker_manager = ContainerWorkerManager(
            max_workers=3,
            session_buddy_client=self.server,
        )
        self._running = False

    async def start(self):
        """Start containerized Session-Buddy with workers."""
        await self.server.start()

        # Spawn initial workers (from config)
        worker_types = self.get_configured_workers()
        await self.worker_manager.spawn_workers(worker_types)

        self._running = True

        # Setup shutdown signal handler
        signal.signal(signal.SIGTERM, self._handle_shutdown)

    async def wait_for_tasks(self):
        """Wait for tasks from Mahavishnu via MCP."""
        while self._running:
            # Check for task queue (from Mahavishnu)
            tasks = await self.server.get_pending_tasks()

            if tasks:
                # Execute on available workers
                await self.worker_manager.execute_batch(tasks)

            await asyncio.sleep(1)

    def _handle_shutdown(self, signum, frame):
        """Handle shutdown signal - push to Akosha before exit."""
        asyncio.create_task(self._shutdown_and_push())

    async def _shutdown_and_push(self):
        """Shutdown workers and push results to Akosha."""
        self._running = False

        # Collect all worker results
        results = await self.worker_manager.collect_all_results()

        # Push to Akosha via sidecar or direct API
        await self.server.push_to_akosha(results)

        # Shutdown workers
        await self.worker_manager.shutdown_all()

        # Shutdown Session-Buddy
        await self.server.stop()
```

**Phase 3**: Mahavishnu Container Orchestrator

```python
# mahavishnu/workers/container_orchestrator.py (NEW)

class ContainerWorkerPool:
    """Orchestrate containers that each contain Session-Buddy + workers."""

    def __init__(
        self,
        docker_client: Any,
        mahavishnu_config: Any,
    ):
        self.docker_client = docker_client
        self.config = mahavishnu_config
        self.containers: dict[str, Any] = {}

    async def spawn_container_pool(
        self,
        count: int = 3,
        worker_config: dict[str, Any] | None = None,
    ) -> list[str]:
        """Spawn multiple containers, each with Session-Buddy + workers.

        Args:
            count: Number of containers to spawn
            worker_config: Worker types for each container

        Returns:
            List of container IDs
        """
        container_ids = []

        for i in range(count):
            # Launch container with embedded Session-Buddy
            container_id = await self._launch_worker_container(
                container_name=f"worker-pool-{i}",
                worker_config=worker_config,
            )
            container_ids.append(container_id)

        return container_ids

    async def _launch_worker_container(
        self,
        container_name: str,
        worker_config: dict[str, Any] | None,
    ) -> str:
        """Launch a single container with Session-Buddy + workers."""

        # Prepare environment with config
        env_vars = {
            "WORKER_TYPES": ",".join(worker_config.get("types", ["terminal-qwen"])),
            "AKOSHA_ENDPOINT": self.config.akosha_endpoint,
            "SESSION_BUDDY_MODE": "container",
        }

        # Launch container
        container_id = await self.docker_client.containers.create(
            image="mahavishnu/worker-container:latest",
            name=container_name,
            environment=env_vars,
            ports={"8678/tcp": None},  # Session-Buddy MCP port
        )

        # Wait for Session-Buddy to start
        await asyncio.sleep(5)

        # Connect to container's Session-Buddy
        sb_client = await self._connect_to_container_sb(container_id)

        # Store container info
        self.containers[container_id] = {
            "name": container_name,
            "sb_client": sb_client,
            "status": "running",
        }

        return container_id

    async def distribute_tasks_to_containers(
        self,
        tasks: list[dict[str, Any]],
    ) -> dict[str, dict[str, WorkerResult]]:
        """Distribute tasks across container pools.

        Args:
            tasks: List of tasks to distribute

        Returns:
            {container_id: {worker_id: WorkerResult}}
        """
        # Round-robin distribution
        container_ids = list(self.containers.keys())
        results = {}

        for i, task in enumerate(tasks):
            container_id = container_ids[i % len(container_ids)]
            container = self.containers[container_id]

            # Send task to container's Session-Buddy
            container_result = await container["sb_client"].call_tool(
                "execute_task",
                arguments={"task": task},
            )

            results[container_id] = container_result

        return results

    async def shutdown_container_pool(
        self,
        push_to_akosha: bool = True,
    ):
        """Shutdown all containers and optionally push results to Akosha."""
        for container_id, container in self.containers.items():
            # Send shutdown signal (triggers graceful shutdown + push)
            await self.docker_client.containers.stop(container_id)

            # Wait for graceful shutdown
            await asyncio.sleep(2)

            # Remove container
            await self.docker_client.containers.remove(container_id)

        self.containers.clear()
```

### Pros & Cons

✅ **Pros:**
- Fully isolated worker environments
- Each container has local Session-Buddy for fast memory access
- Natural for Kubernetes/Docker Swarm deployment
- Easy scaling: Launch more containers
- Akosha aggregation provides global search

❌ **Cons:**
- Most complex architecture
- Requires container image building
- Resource overhead (Session-Buddy per container)
- Network latency between Mahavishnu and containers

---

## Comparison & Recommendation

| Feature | Proposal 1: Storage | Proposal 2: Hierarchical | Proposal 3: Containers |
|---------|-------------------|------------------------|-------------------|
| **Complexity** | ⭐ Low | ⭐⭐⭐ Medium | ⭐⭐⭐⭐⭐ High |
| **Effort** | 1-2 days | 3-5 days | 5-7 days |
| **Scalability** | ⭐⭐⭐ Good | ⭐⭐⭐⭐ Excellent | ⭐⭐⭐⭐⭐ Best |
| **Isolation** | ⭐⭐ Low | ⭐⭐⭐ Medium | ⭐⭐⭐⭐⭐ Best |
| **Kubernetes** | ⭐⭐ Compatible | ⭐⭐⭐ Good | ⭐⭐⭐⭐⭐ Native |
| **Development Speed** | ⭐⭐⭐⭐ Fastest | ⭐⭐⭐ Medium | ⭐ Slowest |

### Recommendation: Start with Proposal 1, Evolve to Proposal 2

**Phase 1 (Now)**: Implement **Proposal 1: Lightweight Storage Integration**
- Complete Session-Buddy storage in existing workers
- Add `worker_search_history` MCP tool
- Enables persistent worker execution history
- Low effort, high value

**Phase 2 (Later)**: Implement **Proposal 2: Hierarchical Orchestration**
- Add `WorkerPoolManager` to Mahavishnu
- Session-Buddy instances manage 3-worker pools
- Better resource utilization
- Natural scaling path

**Phase 3 (Future)**: Consider **Proposal 3: Container-Native** if needed
- For Kubernetes deployments
- For extreme isolation requirements
- When multi-tenant isolation is critical

---

## Akosha Integration

All three proposals assume **Akosha** as the central aggregation point:

### Akosha's Role

1. **Aggregation**: Collect results from multiple pools/containers
2. **Search**: Global search across all worker executions
3. **Persistence**: Long-term storage (beyond Session-Buddy's scope)
4. **Analytics**: Cross-worker pattern detection, trend analysis

### Akosha API (Required)

```python
# Akosha MCP tools (to be implemented)

@mcp.tool()
async def akosha_push_results(
    pool_id: str,
    results: list[WorkerResult],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    """Push worker results to Akosha for aggregation."""
    # Implementation in Akosha repo
    pass

@mcp.tool()
async def akosha_search_workers(
    query: str,
    time_range: tuple[str, str] | None = None,
    worker_types: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Search worker executions across all pools/containers."""
    pass
```

---

## Implementation Roadmap

### Sprint 1: Complete Proposal 1 (Week 1)
1. ✅ Finish Session-Buddy storage in workers
2. ✅ Add `worker_search_history` MCP tool
3. ✅ Add metadata enrichment (repo, branch, commit)
4. ✅ Test semantic search over worker outputs

### Sprint 2: Design Proposal 2 (Week 2)
1. ✅ Design `WorkerPool` class
2. ✅ Design `WorkerPoolManager` class
3. ✅ Define Session-Buddy worker allocation API
4. ✅ Create architecture diagrams

### Sprint 3: Implement Proposal 2 (Weeks 3-4)
1. ✅ Implement `WorkerPool` in Mahavishnu
2. ✅ Extend Session-Buddy with worker management APIs
3. ✅ Add pool MCP tools (`pool_create`, `pool_execute`, `pool_shutdown`)
4. ✅ Implement Akosha push on pool shutdown
5. ✅ Integration testing

### Sprint 4: Proposal 3 Design (Week 5) - If Needed
1. ✅ Container image with embedded Session-Buddy
2. ✅ Session-Buddy worker server
3. ✅ Mahavishnu container orchestrator
4. ✅ Kubernetes deployment manifests

---

## Next Steps

**Immediate Actions** (Proposal 1):
1. Complete Session-Buddy storage in `TerminalAIWorker._store_result_in_session_buddy()`
2. Add `worker_search_history` MCP tool
3. Test semantic search over past executions
4. Document worker history search patterns

**Future Considerations**:
- Should Mahavishnu launch Session-Buddy instances? → **Yes**, for Proposal 2
- Should containers have embedded Session-Buddy? → **Maybe**, for Proposal 3
- How to handle worker failures in pools? → **Pool-level retry logic**
- How to load balance across pools? → **Round-robin with health checks**

---

**Summary**: Start simple with storage integration, evolve to hierarchical orchestration as needs grow. Session-Buddy complements Mahavishnu's worker orchestration with persistent knowledge storage and semantic search.
