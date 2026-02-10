# Swarm Coordination System

## Overview

The Swarm Coordination System provides advanced multi-pool orchestration with biological-inspired patterns. It enables distributed task execution across multiple worker pools using sophisticated coordination topologies and consensus protocols.

## Architecture

### Core Components

1. **SwarmCoordinator** - Main entry point for swarm operations
2. **HiveMind** - Queen-worker coordination system
3. **Topology Implementations** - 4 coordination patterns
4. **Consensus Protocols** - 5 decision-making algorithms
5. **Specialized Workers** - 8 worker types with unique capabilities

## Swarm Topologies

### 1. Hierarchical (Queen-Worker)

**Best for**: Complex multi-phase tasks with clear leadership

```python
from mahavishnu.core.swarm_coordinator import (
    SwarmCoordinator,
    SwarmTopology,
    QueenType,
    WorkerType
)

coordinator = SwarmCoordinator(pool_manager)

result = await coordinator.execute_swarm_task(
    objective={"task": "Build API", "requirements": ["fast", "tested"]},
    topology=SwarmTopology.HIERARCHICAL,
    queen_type=QueenType.STRATEGIC,
    worker_types=[WorkerType.SCOUT, WorkerType.BUILDER, WorkerType.HARVESTER]
)
```

**Pattern**:
- Queen creates strategy and decomposes into subtasks
- Workers execute subtasks in parallel
- Queen aggregates results and learns

**Use Cases**:
- Long-term project planning
- Multi-stage development
- Complex system design

### 2. Mesh (Peer-to-Peer)

**Best for**: Parallel exploration and consensus building

```python
result = await coordinator.execute_swarm_task(
    objective={"task": "Explore solutions"},
    topology=SwarmTopology.MESH,
    consensus=ConsensusProtocol.MAJORITY
)
```

**Pattern**:
- All pools execute task in parallel
- Results aggregated via consensus protocol
- No single point of failure

**Use Cases**:
- Solution exploration
- Parallel processing
- Redundant execution

### 3. Ring (Sequential)

**Best for**: Pipeline processing with incremental improvement

```python
result = await coordinator.execute_swarm_task(
    objective={"task": "Refactor code"},
    topology=SwarmTopology.RING
)
```

**Pattern**:
- Task passes through pools sequentially
- Each pool builds on previous result
- Results collected at each step

**Use Cases**:
- Code refinement
- Data pipelines
- Incremental optimization

### 4. Star (Centralized)

**Best for**: Coordinated execution with central aggregation

```python
result = await coordinator.execute_swarm_task(
    objective={"task": "Distributed testing"},
    topology=SwarmTopology.STAR
)
```

**Pattern**:
- Central pool coordinates
- Satellites execute assigned work
- Central pool aggregates results

**Use Cases**:
- Distributed testing
- Coordinated deployment
- Central monitoring

## Consensus Protocols

### 1. Majority Vote

Simple democratic consensus - most common result wins.

```python
from mahavishnu.core.swarm_coordinator import ConsensusProtocol

result = await coordinator.execute_swarm_task(
    objective={"task": "Choose approach"},
    consensus=ConsensusProtocol.MAJORITY
)
```

**Best for**: General purpose, fast decisions

### 2. Weighted Voting

Votes weighted by pool performance/history.

```python
from mahavishnu.core.swarm_coordinator import WeightedConsensus

consensus = WeightedConsensus(weights=[0.5, 0.3, 0.2])
result = await consensus.resolve(results)
```

**Best for**: Performance-aware decisions

### 3. PBFT (Practical Byzantine Fault Tolerance)

Tolerates faulty nodes with 3f+1 total nodes.

```python
result = await coordinator.execute_swarm_task(
    objective={"task": "Critical decision"},
    consensus=ConsensusProtocol.PBFT
)
```

**Best for**: Critical systems, fault tolerance

**Requirements**: 3f+1 nodes for f fault tolerance

### 4. Raft

Leader election with log replication.

```python
result = await coordinator.execute_swarm_task(
    objective={"task": "Maintain consistency"},
    consensus=ConsensusProtocol.RAFT
)
```

**Best for**: Strong consistency requirements

### 5. Honeybee (Waggle Dance)

Quality-weighted random selection with exploration.

```python
result = await coordinator.execute_swarm_task(
    objective={"task": "Explore and optimize"},
    consensus=ConsensusProtocol.HONEYBEE
)
```

**Best for**: Exploration-exploitation balance

**Features**:
- Mostly follows best solution
- Occasionally explores alternatives
- Inspired by bee decision-making

## Hive Mind System

### Queen Types

#### Strategic Queen

Long-term planning and strategy.

```python
queen = StrategicQueen(pool_manager)
strategy = await queen.create_strategy(objective)
# Timeline: long-term
# Workers: Scout, Builder, Harvester
```

**Capabilities**:
- Strategic decomposition
- Long-term optimization
- Insight extraction

#### Tactical Queen

Medium-term tactics and patterns.

```python
queen = TacticalQueen(pool_manager)
strategy = await queen.create_strategy(objective)
# Timeline: medium-term
# Workers: Forager, Soldier, Guard
```

**Capabilities**:
- Tactical optimization
- Pattern identification
- Quality validation

#### Adaptive Queen

Real-time adaptation based on performance.

```python
queen = AdaptiveQueen(pool_manager)
strategy = await queen.create_strategy(objective)
# Timeline: short-term
# Workers: Nurse, Cleaner, Guard (if poor performance)
# Workers: Scout, Forager, Guard (if good performance)
```

**Capabilities**:
- Performance-based adaptation
- Real-time adjustment
- Continuous learning

### Worker Specializations

#### 1. Scout (Explorer)

**Strategy**: Exploration
**Specialty**: High novelty discovery

```python
worker = HiveWorker(pool, WorkerType.SCOUT)
result = await worker.execute({"task": "explore"})
# Result includes: novelty=0.8
```

**Use Cases**:
- Solution space exploration
- Novel approaches
- Creative alternatives

#### 2. Harvester (Collector)

**Strategy**: Collection
**Specialty**: Efficient resource gathering

```python
worker = HiveWorker(pool, WorkerType.HARVESTER)
result = await worker.execute({"task": "collect"})
# Result includes: efficiency=0.9
```

**Use Cases**:
- Result collection
- Resource gathering
- Data aggregation

#### 3. Builder (Constructor)

**Strategy**: Construction
**Specialty**: Robust structure building

```python
worker = HiveWorker(pool, WorkerType.BUILDER)
result = await worker.execute({"task": "build"})
# Result includes: robustness=0.85
```

**Use Cases**:
- Code construction
- System building
- Architecture creation

#### 4. Nurse (Maintainer)

**Strategy**: Maintenance
**Specialty**: System stability

```python
worker = HiveWorker(pool, WorkerType.NURSE)
result = await worker.execute({"task": "maintain"})
# Result includes: stability=0.95
```

**Use Cases**:
- System maintenance
- Health monitoring
- Stability assurance

#### 5. Soldier (Defender)

**Strategy**: Defense
**Specialty**: Error resilience

```python
worker = HiveWorker(pool, WorkerType.SOLDIER)
result = await worker.execute({"task": "defend"})
# Result includes: resilience=0.9
```

**Use Cases**:
- Error handling
- Resilience testing
- Fault tolerance

#### 6. Forager (Optimizer)

**Strategy**: Optimization
**Specialty**: Optimal path finding

```python
worker = HiveWorker(pool, WorkerType.FORAGER)
result = await worker.execute({"task": "optimize"})
# Result includes: optimality=0.88
```

**Use Cases**:
- Performance optimization
- Path optimization
- Resource efficiency

#### 7. Cleaner (Purifier)

**Strategy**: Purification
**Specialty**: Redundancy removal

```python
worker = HiveWorker(pool, WorkerType.CLEANER)
result = await worker.execute({"task": "clean"})
# Result includes: clarity=0.92
```

**Use Cases**:
- Code cleanup
- Redundancy removal
- Simplification

#### 8. Guard (Validator)

**Strategy**: Validation
**Specialty**: Quality assurance

```python
worker = HiveWorker(pool, WorkerType.GUARD)
result = await worker.execute({"task": "validate"})
# Result includes: quality=0.93
```

**Use Cases**:
- Quality validation
- Standards enforcement
- Compliance checking

## Usage Examples

### Basic Swarm Execution

```python
from mahavishnu.core.swarm_coordinator import SwarmCoordinator
from mahavishnu.pools import PoolManager

# Initialize
pool_manager = PoolManager(terminal_manager=tm, message_bus=bus)
coordinator = SwarmCoordinator(pool_manager)

# Execute task
result = await coordinator.execute_swarm_task(
    objective={
        "task": "Write REST API",
        "requirements": ["fast", "tested", "documented"]
    },
    topology=SwarmTopology.HIERARCHICAL,
    consensus=ConsensusProtocol.MAJORITY,
    queen_type=QueenType.STRATEGIC
)

# Check results
if result.success:
    print(f"Task completed in {result.execution_time_ms:.2f}ms")
    print(f"Consensus reached: {result.consensus_reached}")
    print(f"Results: {result.results}")
```

### Advanced Configuration

```python
# Custom worker selection
result = await coordinator.execute_swarm_task(
    objective={"task": "Complex development"},
    topology=SwarmTopology.MESH,
    consensus=ConsensusProtocol.WEIGHTED,
    queen_type=QueenType.TACTICAL,
    worker_types=[
        WorkerType.FORAGER,  # Find optimal approach
        WorkerType.BUILDER,  # Build solution
        WorkerType.GUARD     # Validate quality
    ]
)
```

### Fault-Tolerant Execution

```python
# Use PBFT for fault tolerance
result = await coordinator.execute_swarm_task(
    objective={"task": "Critical operation"},
    topology=SwarmTopology.MESH,
    consensus=ConsensusProtocol.PBFT,
    queen_type=QueenType.ADAPTIVE
)

# System tolerates 1 faulty node with 4 total nodes
assert result.consensus_reached
```

### Queen Memory and Learning

```python
# Get queen insights
hive_mind = coordinator.hive_mind

strategic_insights = await hive_mind.get_queen_insights(QueenType.STRATEGIC)
for insight in strategic_insights:
    print(f"Task: {insight.task_id}, Success: {insight.success}")

# Queens learn from past executions
# Strategic queen: extracts insights
# Tactical queen: identifies patterns
# Adaptive queen: adapts based on performance
```

## API Reference

### SwarmCoordinator

```python
class SwarmCoordinator:
    """Main coordinator for swarm operations."""

    async def execute_swarm_task(
        self,
        objective: dict[str, Any],
        topology: SwarmTopology = SwarmTopology.HIERARCHICAL,
        consensus: ConsensusProtocol = ConsensusProtocol.MAJORITY,
        queen_type: QueenType = QueenType.STRATEGIC,
        worker_types: Optional[list[WorkerType]] = None
    ) -> SwarmResult:
        """Execute task using swarm coordination."""

    async def get_topology_status(self) -> dict:
        """Get status of available topologies."""

    async def get_swarm_metrics(self) -> dict:
        """Get swarm coordination metrics."""
```

### SwarmResult

```python
@dataclass
class SwarmResult:
    """Result from swarm execution."""
    task_id: str                      # Unique task identifier
    success: bool                      # Execution success
    results: list[dict[str, Any]]     # Execution results
    consensus_reached: bool            # Consensus achieved
    execution_time_ms: float           # Execution time
    pool_results: dict[str, Any]       # Pool-specific results
    metadata: dict[str, Any]           # Execution metadata
```

### HiveMind

```python
class HiveMind:
    """Hive Mind coordination with queen-worker patterns."""

    async def coordinate(
        self,
        objective: dict[str, Any],
        queen_type: QueenType,
        worker_types: list[WorkerType],
        topology: SwarmTopology,
        consensus: ConsensusProtocol
    ) -> SwarmResult:
        """Coordinate swarm to achieve objective."""

    async def get_queen_insights(
        self,
        queen_type: QueenType
    ) -> list[SwarmResult]:
        """Get historical insights from queen."""
```

## Best Practices

### 1. Topology Selection

- **Hierarchical**: Use for complex, multi-phase tasks
- **Mesh**: Use for parallel exploration
- **Ring**: Use for pipeline processing
- **Star**: Use for coordinated execution

### 2. Consensus Selection

- **Majority**: Default choice for most cases
- **Weighted**: Use with performance-aware pools
- **PBFT**: Use for critical systems
- **Raft**: Use for strong consistency
- **Honeybee**: Use for exploration tasks

### 3. Queen Selection

- **Strategic**: Long-term planning (days/weeks)
- **Tactical**: Medium-term tasks (hours/days)
- **Adaptive**: Real-time adaptation (seconds/minutes)

### 4. Worker Selection

Match workers to task phases:
- **Discovery phase**: Scout, Forager
- **Building phase**: Builder, Harvester
- **Validation phase**: Guard, Nurse
- **Optimization phase**: Forager, Cleaner
- **Defense phase**: Soldier, Guard

## Performance Considerations

### Scalability

- **Hierarchical**: O(n) workers, scales well
- **Mesh**: O(n²) communication, use with < 10 pools
- **Ring**: O(n) sequential, predictable latency
- **Star**: O(n) communication, central bottleneck risk

### Fault Tolerance

- **Hierarchical**: Queen failure = total failure
- **Mesh**: High fault tolerance
- **Ring**: Single point failure possible
- **Star**: Central pool failure = total failure

### Consensus Cost

- **Majority**: Fast, O(n)
- **Weighted**: Fast, O(n)
- **PBFT**: Slower, O(n²)
- **Raft**: Medium, O(n log n)
- **Honeybee**: Fast, O(n)

## Error Handling

The swarm coordination system handles errors gracefully:

```python
# Individual worker failures don't stop swarm
result = await coordinator.execute_swarm_task(
    objective={"task": "robust execution"}
)

# Check for partial failures
exceptions = result.metadata.get("exceptions", 0)
if exceptions > 0:
    print(f"Completed with {exceptions} worker failures")

# Results still aggregated from successful workers
assert result.success  # May be True even with partial failures
```

## Monitoring and Metrics

```python
# Get swarm metrics
metrics = await coordinator.get_swarm_metrics()
print(f"Hive mind memory entries: {metrics['hive_mind_memory']}")
print(f"Active swarms: {metrics['active_swarms']}")

# Get topology status
status = await coordinator.get_topology_status()
print(f"Available topologies: {status['available_topologies']}")
print(f"Available protocols: {status['available_protocols']}")
```

## Testing

See `tests/unit/test_swarm_coordinator.py` for comprehensive examples:

- Topology tests (4 tests)
- Consensus protocol tests (8 tests)
- Worker specialization tests (8 tests)
- Queen behavior tests (3 tests)
- Hive Mind tests (2 tests)
- Factory tests (6 tests)
- Coordinator tests (3 tests)
- Fault tolerance tests (2 tests)
- Integration tests (1 test)

**Total**: 37 comprehensive tests

## Future Enhancements

Potential improvements:

1. **Dynamic Topology Switching** - Change topology during execution
2. **Adaptive Worker Allocation** - Auto-select workers based on task
3. **Swarm Communication** - Direct worker-to-worker communication
4. **Swarm Learning** - Cross-swarm knowledge sharing
5. **Hybrid Topologies** - Combine multiple topologies
6. **Real-time Monitoring** - Live swarm visualization
7. **Performance Prediction** - Estimate execution time
8. **Resource Optimization** - Balance load across pools

## References

- Biological inspiration: Honeybee waggle dance, ant colony optimization
- Distributed systems: Raft, PBFT, gossip protocols
- Swarm intelligence: Particle swarm, flocking algorithms
- Consensus theory: Byzantine generals, CAP theorem
