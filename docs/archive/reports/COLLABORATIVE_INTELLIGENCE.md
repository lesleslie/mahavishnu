# Collaborative Intelligence System

Integration #17 for the Mahavishnu ecosystem - Multi-agent collaboration, knowledge sharing, and emergent swarm intelligence.

## Overview

The Collaborative Intelligence system enables true emergent intelligence from agent collaboration through:

- **Agent Registry**: Discovery, capability tracking, reputation scoring
- **Knowledge Sharing**: Experience, failures, solutions, best practices, code
- **Collaboration Protocols**: Task delegation, result aggregation, consensus, voting
- **Swarm Intelligence**: PSO, ACO, Bee Algorithm, Firefly optimization
- **Collective Decision Making**: Voting, consensus, expert weighting, averaging

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│              CollaborativeIntelligence Orchestrator          │
├─────────────────────────────────────────────────────────────┤
│  ┌───────────────┐  ┌──────────────┐  ┌─────────────────┐ │
│  │ AgentRegistry │  │KnowledgeShare│  │Collaboration    │ │
│  │               │  │              │  │Protocol         │ │
│  │ - Discovery   │  │ - Experience │  │ - Delegation    │ │
│  │ - Reputation  │  │ - Failures   │  │ - Aggregation   │ │
│  │ - Health      │  │ - Solutions  │  │ - Consensus     │ │
│  └───────────────┘  │ - Best Prac  │  │ - Voting        │ │
│                     │ - Code       │  └─────────────────┘ │
│  ┌───────────────┐  └──────────────┘  ┌─────────────────┐ │
│  │SwarmIntelligence│                │CollectiveDecision│ │
│  │                │                │Making            │ │
│  │ - PSO          │                │ - Voting         │ │
│  │ - ACO          │                │ - Consensus      │ │
│  │ - Bee Algorithm│                │ - Expert Weight  │ │
│  │ - Firefly      │                │ - Averaging      │ │
│  └───────────────┘                └─────────────────┘ │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                      Integrations                            │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐ │
│  │ A2A Protocol │  │ Knowledge    │  │  FastAPI         │ │
│  │              │  │ Graph        │  │  Endpoints       │ │
│  └──────────────┘  └──────────────┘  └──────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

## Installation

```python
from mahavishnu.integrations import (
    CollaborativeIntelligence,
    AgentMetadata,
    AgentCapabilities,
    KnowledgeType,
    CollaborationStrategy,
    SwarmAlgorithm,
)
```

## Quick Start

### 1. Initialize the System

```python
from mahavishnu.integrations import CollaborativeIntelligence

# Create collaborative intelligence instance
ci = CollaborativeIntelligence(
    knowledge_graph_service=kg_service,  # Optional
    a2a_protocol=a2a_protocol,           # Optional
)
```

### 2. Register Agents

```python
# Register agent with capabilities
await ci.registry.register_agent(
    AgentMetadata(
        agent_id="python-pro-001",
        name="Python Expert",
        type="python-pro",
        location="localhost:8001",
        capabilities=AgentCapabilities(
            primary=["code_generation", "test_creation"],
            secondary=["documentation"],
            expertise_domains=["python", "testing", "fastapi"],
        ),
        reputation_score=0.85,
        trust_level=TrustLevel.VERIFIED,
    )
)
```

### 3. Share Knowledge

```python
# Share successful experience
await ci.knowledge.share_experience(
    agent_id="python-pro-001",
    experience="Use pytest fixtures for test isolation and setup",
    context="testing",
    confidence=0.95,
    tags=["pytest", "testing", "fixtures"],
)

# Share failure lesson
await ci.knowledge.share_failure(
    agent_id="python-pro-001",
    failure="Forgot to clean up database fixtures",
    lesson_learned="Always use pytest autouse fixtures for cleanup",
    context="testing",
    confidence=0.90,
)

# Share solution
await ci.knowledge.share_solution(
    agent_id="python-pro-001",
    problem="Need async database testing",
    solution="Use pytest-asyncio with async fixture",
    context="testing",
    confidence=0.92,
)

# Share best practice
await ci.knowledge.share_best_practice(
    agent_id="python-pro-001",
    practice="Keep tests independent and isolated",
    rationale="Enables parallel test execution",
    context="testing",
    confidence=0.88,
)

# Share reusable code
await ci.knowledge.share_code(
    agent_id="python-pro-001",
    code="""
@pytest.fixture
async def db_session():
    async with create_session() as session:
        yield session
""",
    description="Async database session fixture",
    language="python",
    context="testing",
    confidence=1.0,
)
```

### 4. Collaborate on Tasks

```python
# Delegate task and aggregate results
result = await ci.collaborate(
    task="Implement secure user authentication with JWT",
    required_capabilities=["code_generation", "security_audit"],
    strategy=CollaborationStrategy.WEIGHTED_VOTING,
    share_knowledge=True,
)

print(f"Decision: {result.final_decision}")
print(f"Confidence: {result.confidence:.2%}")
print(f"Consensus: {result.consensus_level:.2%}")
print(f"Agents involved: {len(result.agents_involved)}")
```

### 5. Run Swarm Optimization

```python
# Define objective function
def objective_function(params):
    """Hyperparameter optimization objective."""
    learning_rate, batch_size, dropout = params
    # Simulate model training and return loss
    loss = simulate_training(learning_rate, batch_size, dropout)
    return loss

# Run particle swarm optimization
best_params, best_loss, swarm_state = await ci.optimize_with_swarm(
    objective_function=objective_function,
    algorithm=SwarmAlgorithm.PARTICLE_SWARM,
    dimensions=3,
    num_particles=30,
    max_iterations=100,
)

print(f"Best parameters: {best_params}")
print(f"Best loss: {best_loss:.4f}")
print(f"Iterations: {swarm_state.iteration}")
```

## Components

### Agent Registry

Track and discover agents with capabilities, reputation, and health monitoring.

```python
# Register agent
await ci.registry.register_agent(agent_metadata)

# Discover agents by capability
agents = await ci.registry.discover_agents(
    capabilities=["code_generation", "security_audit"],
    min_reputation=0.7,
    trust_level=TrustLevel.VERIFIED,
    status=AgentStatus.ACTIVE,
    limit=10,
)

# Update agent reputation
new_reputation = await ci.registry.update_reputation(
    agent_id="python-pro-001",
    success=True,
    task_difficulty=0.8,
)

# Get stale agents
stale = await ci.registry.get_stale_agents(timeout=timedelta(seconds=60))

# Registry statistics
stats = await ci.registry.get_agent_stats()
```

### Knowledge Sharing

Share and discover knowledge across agents with 8 knowledge types.

#### Knowledge Types

1. **EXPERIENCE**: Successful patterns and approaches
2. **FAILURE**: Lessons learned from failures
3. **SOLUTION**: Working solutions to problems
4. **BEST_PRACTICE**: Optimization and best practices
5. **CODE**: Reusable code components
6. **PATTERN**: Design patterns and architectural patterns
7. **ANOMALY**: Detected anomalies and outliers
8. **INSIGHT**: Derived insights from data analysis

```python
# Search knowledge
results = await ci.knowledge.search_knowledge(
    query="pytest fixtures",
    knowledge_types=[KnowledgeType.EXPERIENCE, KnowledgeType.CODE],
    context="testing",
    tags=["pytest"],
    min_confidence=0.7,
    limit=10,
)

# Record knowledge usage
await ci.knowledge.record_usage(
    fragment_id=fragment_id,
    success=True,
)

# Get trending knowledge
trending = await ci.knowledge.get_trending_knowledge(days=7, limit=10)
```

### Collaboration Protocol

Enable agent collaboration with 8+ strategies.

#### Collaboration Strategies

1. **MAJORITY_VOTE**: Most common decision wins
2. **WEIGHTED_VOTING**: Vote weighted by reputation
3. **CONSENSUS**: Reach agreement through discussion
4. **EXPERT_WEIGHTING**: Trust expert agents more
5. **AVERAGING**: Average agent predictions
6. **QUORUM**: Require minimum agreements
7. **STACKELBERG**: Leader-follower game theory
8. **PARETO**: Pareto optimal solutions

```python
# Direct delegation
result = await ci.collaboration.delegate_and_aggregate(
    task="Design API architecture",
    required_capabilities=["api_design", "security"],
    strategy=CollaborationStrategy.CONSENSUS,
    min_agents=3,
    max_agents=5,
    context={"project": "ecommerce", "timeline": "2 weeks"},
    deadline=datetime.now(UTC) + timedelta(hours=24),
)
```

### Swarm Intelligence

Optimization algorithms for emergent problem solving.

#### Supported Algorithms

1. **Particle Swarm Optimization (PSO)**: Parameter tuning, optimization
2. **Ant Colony Optimization (ACO)**: Path finding, routing
3. **Bee Algorithm**: Resource allocation, scheduling
4. **Firefly Algorithm**: Clustering, multi-modal optimization

```python
# Particle Swarm Optimization
best_solution, best_fitness, state = await ci.swarm.particle_swarm_optimization(
    objective_function=objective,
    dimensions=5,
    bounds=((0.0, 1.0), (0.0, 1.0), (0.0, 1.0), (0.0, 1.0), (0.0, 1.0)),
    num_particles=30,
    max_iterations=200,
    w=0.729,      # Inertia weight
    c1=1.49445,   # Cognitive parameter
    c2=1.49445,   # Social parameter
)

# Ant Colony Optimization
best_path, best_distance, state = await ci.swarm.ant_colony_optimization(
    distance_matrix=distance_matrix,
    num_ants=20,
    max_iterations=100,
    alpha=1.0,           # Pheromone importance
    beta=2.0,            # Heuristic importance
    evaporation_rate=0.5,
    q=1.0,              # Pheromone deposit
)

# Bee Algorithm
best_position, best_fitness, state = await ci.swarm.bee_algorithm(
    objective_function=objective,
    dimensions=10,
    bounds=[(-5.0, 5.0)] * 10,
    num_bees=50,
    max_iterations=150,
    num_elite=10,
    num_best=25,
)

# Firefly Algorithm
best_position, best_fitness, state = await ci.swarm.firefly_algorithm(
    objective_function=objective,
    dimensions=3,
    bounds=[(-10.0, 10.0)] * 3,
    num_fireflies=25,
    max_iterations=100,
    alpha=0.2,      # Randomization
    beta0=1.0,     # Attractiveness at r=0
    gamma=1.0,     # Light absorption
)
```

### Collective Decision Making

Group intelligence for decision making.

```python
# Weighted voting
result = await ci.decision.vote(
    proposals=[
        {"id": "A", "approach": "Microservices"},
        {"id": "B", "approach": "Monolith"},
    ],
    voter_agent_ids=["agent-001", "agent-002", "agent-003"],
)

# Consensus building
result = await ci.decision.build_consensus(
    proposals=proposals,
    agent_ids=agent_ids,
    max_rounds=5,
    agreement_threshold=0.8,
)

# Average predictions
result = await ci.decision.average_predictions(
    predictions=[0.85, 0.90, 0.88, 0.87],
    agent_ids=["agent-001", "agent-002", "agent-003", "agent-004"],
)

# Expert-weighted decision
result = await ci.decision.expert_weighted_decision(
    proposals=proposals,
    agent_ids=agent_ids,
    domain="machine_learning",
)
```

## Advanced Usage

### Reputation Management

```python
# Agent reputation updates automatically
new_rep = await ci.registry.update_reputation(
    agent_id="agent-001",
    success=True,
    task_difficulty=0.8,
)

# Reputation affects weighted voting
agent = await ci.registry.get_agent("agent-001")
print(f"Reputation: {agent.reputation_score:.2%}")
print(f"Success rate: {agent.success_rate:.2%}")
print(f"Total tasks: {agent.total_tasks}")
```

### Trust Levels

```python
from mahavishnu.integrations import TrustLevel

# Trust levels affect agent selection
TRUSTED > VERIFIED > MONITORED > UNTRUSTED > SANCTIONED

# Filter by trust level
agents = await ci.registry.discover_agents(
    capabilities=["security_audit"],
    trust_level=TrustLevel.TRUSTED,
    min_reputation=0.8,
)
```

### Swarm Convergence

```python
# Monitor swarm convergence
best_solution, best_fitness, state = await ci.optimize_with_swarm(
    objective_function=objective,
    algorithm=SwarmAlgorithm.PARTICLE_SWARM,
    dimensions=5,
    max_iterations=100,
)

# Analyze convergence
import matplotlib.pyplot as plt

plt.plot(state.convergence_history)
plt.xlabel("Iteration")
plt.ylabel("Fitness")
plt.title("Swarm Convergence")
plt.show()

# Check convergence rate
convergence_rate = (
    state.convergence_history[0] - state.convergence_history[-1]
) / len(state.convergence_history)
print(f"Convergence rate: {convergence_rate:.4f} per iteration")
```

### Knowledge Lifecycle

```python
# Share knowledge with confidence
fragment = await ci.knowledge.share_experience(
    agent_id="agent-001",
    experience="Use async/await for I/O operations",
    context="performance",
    confidence=0.90,
)

# Record usage (success increases confidence)
await ci.knowledge.record_usage(fragment.id, success=True)

# Confidence evolves with usage
fragment = ci.knowledge._fragments[fragment.id]
print(f"Usage count: {fragment.usage_count}")
print(f"Success rate: {fragment.success_count / fragment.usage_count:.2%}")
print(f"Current confidence: {fragment.confidence:.2%}")
```

## Integration with A2A Protocol

```python
# Initialize with A2A protocol
ci = CollaborativeIntelligence(a2a_protocol=a2a)

# Import agents from A2A
await ci.initialize_from_a2a()

# Agents from A2A are now in registry
agents = await ci.registry.list_agents()
print(f"Registered {len(agents)} agents from A2A")
```

## Performance Considerations

### Scalability

- **Agent Registry**: O(1) lookup by ID, O(n) discovery by capability
- **Knowledge Search**: O(n) text search, can be optimized with embeddings
- **Swarm Algorithms**: O(iterations × population_size × dimensions)
- **Decision Making**: O(agents) for most strategies

### Optimization Tips

1. **Use capability indexing** for fast agent discovery
2. **Limit knowledge searches** with context and tags
3. **Tune swarm parameters** for your problem size
4. **Cache agent metadata** to reduce registry lookups
5. **Use async operations** for parallel agent communication

## Best Practices

### Agent Registration

```python
# DO: Register with detailed capabilities
await ci.registry.register_agent(
    AgentMetadata(
        agent_id="python-pro-001",
        name="Python Expert",
        type="python-pro",
        location="localhost:8001",
        capabilities=AgentCapabilities(
            primary=["code_generation", "test_creation", "api_design"],
            secondary=["documentation", "code_review"],
            expertise_domains=["python", "fastapi", "pytest"],
            performance_history={
                "avg_task_time": 120,  # seconds
                "success_rate": 0.92,
            },
        ),
        reputation_score=0.85,
        trust_level=TrustLevel.VERIFIED,
        metadata={
            "max_concurrent_tasks": 5,
            "specializations": ["async", "testing", "api"],
        },
    )
)

# DON'T: Register with minimal information
await ci.registry.register_agent(
    AgentMetadata(
        agent_id="agent-001",
        name="Agent",
        type="generic",
        location="unknown",
        capabilities=AgentCapabilities(primary=[]),
    )
)
```

### Knowledge Sharing

```python
# DO: Share specific, actionable knowledge
await ci.knowledge.share_experience(
    agent_id="agent-001",
    experience="Use pytest.mark.asyncio for async test functions",
    context="testing",
    confidence=0.95,
    tags=["pytest", "async", "testing"],
)

# DON'T: Share vague knowledge
await ci.knowledge.share_experience(
    agent_id="agent-001",
    experience="Write good tests",  # Too vague
    context="testing",
    confidence=0.5,
)
```

### Collaboration

```python
# DO: Use appropriate strategy for task
result = await ci.collaborate(
    task="Select database technology",
    required_capabilities=["database_expertise"],
    strategy=CollaborationStrategy.EXPERT_WEIGHTING,  # Use expert judgment
    share_knowledge=True,
)

# DON'T: Use wrong strategy
result = await ci.collaborate(
    task="Select database technology",
    required_capabilities=["database_expertise"],
    strategy=CollaborationStrategy.MAJORITY_VOTE,  # Wrong for expert decision
)
```

## Error Handling

```python
from mahavishnu.integrations import with_timeout, retry_on_failure

# Add timeout to operations
wrapped = with_timeout(
    ci.collaborate,
    timeout_seconds=30.0,
)
result = await wrapped(task="...", required_capabilities=["..."])

# Retry on failure
@retry_on_failure(max_retries=3, delay=1.0)
async def flaky_collaboration():
    return await ci.collaborate(...)

# Handle insufficient agents
try:
    result = await ci.collaborate(
        task="Complex task",
        required_capabilities=["rare_capability"],
        min_agents=10,
    )
except ValueError as e:
    print(f"Not enough agents: {e}")
    # Fallback to individual agent
```

## Monitoring

```python
# System statistics
stats = await ci.get_system_stats()
print(f"Total agents: {stats['registry']['total_agents']}")
print(f"Knowledge fragments: {stats['knowledge_fragments']}")
print(f"Active collaborations: {stats['active_collaborations']}")
print(f"Active swarms: {stats['active_swarms']}")

# Agent health
stale_agents = await ci.registry.get_stale_agents()
if stale_agents:
    print(f"Warning: {len(stale_agents)} stale agents detected")

# Knowledge trends
trending = await ci.knowledge.get_trending_knowledge(days=7)
print(f"Top {len(trending)} trending knowledge items:")
for item in trending:
    print(f"  - {item.type}: {item.context} (used {item.usage_count} times)")
```

## Testing

```python
import pytest
from mahavishnu.integrations import (
    CollaborativeIntelligence,
    AgentMetadata,
    AgentCapabilities,
)

@pytest.mark.asyncio
async def test_agent_collaboration():
    # Setup
    ci = CollaborativeIntelligence()

    await ci.registry.register_agent(
        AgentMetadata(
            agent_id="test-agent",
            name="Test Agent",
            type="test",
            location="localhost",
            capabilities=AgentCapabilities(
                primary=["test_capability"],
            ),
        )
    )

    # Test
    result = await ci.collaborate(
        task="Test task",
        required_capabilities=["test_capability"],
    )

    # Assert
    assert result.confidence > 0.0
    assert len(result.agents_involved) >= 1
```

## API Reference

### Models

#### AgentMetadata
- `agent_id`: Unique identifier
- `name`: Display name
- `type`: Agent type
- `location`: Network location
- `status`: Current status (ACTIVE, IDLE, BUSY, etc.)
- `capabilities`: Agent capabilities
- `trust_level`: Trust level (TRUSTED, VERIFIED, etc.)
- `reputation_score`: 0.0 to 1.0
- `success_rate`: Task success rate

#### KnowledgeFragment
- `id`: Unique identifier
- `type`: Knowledge type
- `content`: Knowledge content
- `source_agent_id`: Creator agent
- `context`: Application context
- `confidence`: 0.0 to 1.0
- `tags`: Discovery tags
- `usage_count`: Times used
- `success_count`: Successful uses

#### CollaborationResult
- `request_id`: Request identifier
- `agents_involved`: Participating agents
- `decisions`: Individual decisions
- `final_decision`: Aggregated decision
- `confidence`: Result confidence
- `strategy_used`: Strategy employed
- `consensus_level`: Agreement level

#### SwarmState
- `algorithm`: Algorithm used
- `iteration`: Current iteration
- `best_solution`: Best position found
- `best_fitness`: Best fitness value
- `convergence_history`: Fitness over iterations

## Examples

### Example 1: Multi-Agent Code Review

```python
# Register specialized agents
await ci.registry.register_agent(
    AgentMetadata(
        agent_id="security-agent",
        name="Security Expert",
        type="security",
        location="localhost:8001",
        capabilities=AgentCapabilities(
            primary=["security_audit", "vulnerability_scan"],
            expertise_domains=["security", "owasp"],
        ),
        reputation_score=0.95,
    )
)

await ci.registry.register_agent(
    AgentMetadata(
        agent_id="performance-agent",
        name="Performance Expert",
        type="performance",
        location="localhost:8002",
        capabilities=AgentCapabilities(
            primary=["performance_analysis", "optimization"],
            expertise_domains=["performance", "profiling"],
        ),
        reputation_score=0.90,
    )
)

# Collaborative code review
result = await ci.collaborate(
    task="Review authentication module",
    required_capabilities=["security_audit", "performance_analysis"],
    strategy=CollaborationStrategy.EXPERT_WEIGHTING,
    share_knowledge=True,
)

print(f"Review decision: {result.final_decision}")
print(f"Confidence: {result.confidence:.2%}")
```

### Example 2: Hyperparameter Optimization

```python
# Define objective
def objective(params):
    learning_rate, batch_size, dropout, epochs, optimizer = params
    # Train model and return validation loss
    loss = train_model(
        learning_rate=learning_rate,
        batch_size=int(batch_size),
        dropout=dropout,
        epochs=int(epochs),
        optimizer_type=["adam", "sgd", "rmsprop"][int(optimizer)],
    )
    return loss

# Run PSO optimization
best_params, best_loss, state = await ci.optimize_with_swarm(
    objective_function=objective,
    algorithm=SwarmAlgorithm.PARTICLE_SWARM,
    dimensions=5,
    bounds=[
        (1e-5, 1e-1),      # learning_rate
        (16, 256),         # batch_size
        (0.0, 0.5),        # dropout
        (10, 200),         # epochs
        (0, 2),            # optimizer index
    ],
    num_particles=40,
    max_iterations=150,
)

print(f"Best loss: {best_loss:.4f}")
print(f"Best params: lr={best_params[0]:.6f}, "
      f"batch={int(best_params[1])}, "
      f"dropout={best_params[2]:.3f}")
```

### Example 3: Route Optimization with ACO

```python
# Create distance matrix (e.g., delivery locations)
import numpy as np

num_locations = 10
distance_matrix = np.random.rand(num_locations, num_locations) * 100
distance_matrix = (distance_matrix + distance_matrix.T) / 2  # Symmetric
np.fill_diagonal(distance_matrix, 0)

# Run ACO for shortest path
best_path, best_distance, state = await ci.swarm.ant_colony_optimization(
    distance_matrix=distance_matrix.tolist(),
    num_ants=30,
    max_iterations=200,
    alpha=1.0,   # Pheromone importance
    beta=2.5,    # Heuristic importance
    evaporation_rate=0.3,
)

print(f"Shortest distance: {best_distance:.2f}")
print(f"Best path: {best_path}")
```

## Troubleshooting

### Issue: No agents discovered

**Problem**: `discover_agents()` returns empty list.

**Solution**:
```python
# Check agents are registered
agents = await ci.registry.list_agents()
print(f"Registered agents: {len(agents)}")

# Check capability index
stats = await ci.registry.get_agent_stats()
print(f"Capabilities: {stats['capabilities_count']}")

# Verify capability names match
agent = await ci.registry.get_agent("agent-001")
print(f"Agent capabilities: {agent.capabilities.primary}")
```

### Issue: Low consensus level

**Problem**: Collaboration has low consensus despite multiple agents.

**Solution**:
```python
# Use different strategy
result = await ci.collaborate(
    task="...",
    required_capabilities=["..."],
    strategy=CollaborationStrategy.CONSENSUS,  # Try consensus building
    max_agents=10,  # Involve more agents
)

# Or use expert weighting for expert domains
result = await ci.collaborate(
    task="...",
    required_capabilities=["..."],
    strategy=CollaborationStrategy.EXPERT_WEIGHTING,
)
```

### Issue: Swarm not converging

**Problem**: Swarm algorithm doesn't find good solution.

**Solution**:
```python
# Increase population/iterations
best_solution, best_fitness, state = await ci.optimize_with_swarm(
    objective_function=objective,
    algorithm=SwarmAlgorithm.PARTICLE_SWARM,
    dimensions=5,
    num_particles=50,      # Increase from 20
    max_iterations=300,    # Increase from 100
)

# Check convergence
if state.convergence_history[-1] > threshold:
    print("Warning: Swarm did not converge well")
    print("Consider adjusting algorithm parameters")
```

## Future Enhancements

- Multi-objective optimization
- Federated learning integration
- Reinforcement learning agents
- Dynamic strategy selection
- Knowledge graph integration
- Real-time collaboration streams
- Agent negotiation protocols
- Distributed consensus (Raft, Paxos)

## References

- Swarm Intelligence: "Swarm Intelligence" by Kennedy and Eberhart
- ACO: "Ant Colony Optimization" by Dorigo and Stutzle
- Multi-agent systems: "Multiagent Systems" by Wooldridge
- Collective intelligence: "The Wisdom of Crowds" by Surowiecki

## License

Part of the Mahavishnu ecosystem. See main project license.
