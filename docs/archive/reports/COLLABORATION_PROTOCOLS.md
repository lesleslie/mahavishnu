# Collaborative Intelligence Protocols

**Integration #17**: Collaborative Intelligence
**Version**: 1.0.0
**Status**: Production Ready

This document describes the protocols, algorithms, and coordination patterns for multi-agent collaborative intelligence and swarm coordination in the Mahavishnu orchestration platform.

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Agent Discovery Protocol](#agent-discovery-protocol)
4. [Knowledge Sharing Protocol](#knowledge-sharing-protocol)
5. [Collaboration Modes](#collaboration-modes)
6. [Voting and Decision Making](#voting-and-decision-making)
7. [Consensus Building](#consensus-building)
8. [Reputation System](#reputation-system)
9. [Swarm Intelligence](#swarm-intelligence)
10. [Message Formats](#message-formats)
11. [Coordination Patterns](#coordination-patterns)
12. [Visualization and Monitoring](#visualization-and-monitoring)
13. [Best Practices](#best-practices)
14. [API Reference](#api-reference)

---

## Overview

Collaborative Intelligence enables multiple AI agents to work together organically, sharing knowledge, building consensus, and making collective decisions. The system is inspired by swarm intelligence in nature (ant colonies, bird flocks, fish schools) and democratic decision-making processes.

### Key Concepts

- **Agent Capabilities**: What each agent can do (15 capabilities across 5 categories)
- **Knowledge Sharing**: Agents share insights, patterns, and best practices
- **Collaboration Modes**: Parallel, sequential, debate, consensus, voting, swarm
- **Reputation System**: Track agent trustworthiness and expertise
- **Consensus Building**: Democratic decision-making algorithms
- **Swarm Optimization**: Emergent problem-solving through agent interaction

### Benefits

- **Emergent Intelligence**: Collective intelligence greater than sum of parts
- **Resilience**: No single point of failure
- **Scalability**: Add agents without redesign
- **Quality**: Multiple perspectives reduce errors
- **Learning**: Knowledge sharing accelerates improvement

---

## Architecture

### System Components

```
┌─────────────────────────────────────────────────────────────┐
│                  Collaborative Intelligence                 │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │   Agent      │  │   Agent      │  │   Agent      │      │
│  │  Registry    │  │  Discovery   │  │ Reputation   │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
│                                                               │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │   Knowledge  │  │  Consensus   │  │    Swarm     │      │
│  │    Base      │  │   Builder    │  │ Optimizer    │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
│                                                               │
│  ┌──────────────────────────────────────────────────────┐   │
│  │            A2A Protocol Layer                        │   │
│  │  (Agent Registration, Task Delegation, Result Aggregation) │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### Data Flow

1. **Agent Registration**: Agents register capabilities with protocol
2. **Discovery**: Other agents discover capable peers
3. **Collaboration**: Agents form groups for tasks
4. **Knowledge Sharing**: Agents share insights with swarm
5. **Reputation Update**: Agent reputations updated based on outcomes
6. **Learning**: Swarm knowledge base grows over time

---

## Agent Discovery Protocol

### Capability Declaration

Agents declare capabilities using the `AgentCapability` enum:

```python
class AgentCapability(str, Enum):
    # Code capabilities
    CODE_ANALYSIS = "code_analysis"
    CODE_GENERATION = "code_generation"
    CODE_REFACTORING = "code_refactoring"
    CODE_REVIEW = "code_review"
    TEST_GENERATION = "test_generation"

    # System capabilities
    SYSTEM_DIAGNOSTICS = "system_diagnostics"
    PERFORMANCE_TUNING = "performance_tuning"
    SECURITY_AUDIT = "security_audit"

    # Documentation
    DOC_GENERATION = "doc_generation"
    DOC_REVIEW = "doc_review"

    # Data capabilities
    DATA_ANALYSIS = "data_analysis"
    DATA_VISUALIZATION = "data_visualization"
    DATA_PIPELINE = "data_pipeline"

    # Infrastructure
    DEPLOYMENT = "deployment"
    MONITORING = "monitoring"
    LOGGING_ANALYSIS = "logging_analysis"
```

### Registration Flow

```
Agent                      Protocol
│                           │
├── REGISTER(agent_desc) ──>│
│                           ├── Index by capability
│                           ├── Store descriptor
│                           └── ACK ─────────────────────>│
│                           │
```

**Request Format**:
```json
{
  "type": "register",
  "agent": {
    "id": "python-pro-001",
    "name": "Python Expert",
    "agent_type": "python-pro",
    "capabilities": [
      "code_analysis",
      "code_generation",
      "test_generation"
    ],
    "max_concurrent_tasks": 5,
    "metadata": {}
  }
}
```

**Response Format**:
```json
{
  "type": "register_ack",
  "status": "success",
  "agent_id": "python-pro-001",
  "timestamp": "2026-02-05T12:00:00Z"
}
```

### Discovery Algorithm

```python
def discover_capable_agents(
    capability: AgentCapability,
    min_availability: float = 0.0,
) -> List[AgentDescriptor]:
    """
    Discover agents sorted by availability.

    Args:
        capability: Required capability
        min_availability: Minimum availability ratio (0.0 to 1.0)

    Returns:
        List of capable agents sorted by availability
    """
    # 1. Lookup capability index
    agent_ids = capability_index.get(capability, [])

    # 2. Filter by availability
    capable = [
        agents[aid]
        for aid in agent_ids
        if agents[aid].availability_ratio >= min_availability
    ]

    # 3. Sort by availability (most available first)
    capable.sort(key=lambda a: a.availability_ratio, reverse=True)

    return capable
```

### Availability Calculation

```python
availability_ratio = 1.0 - (current_tasks / max_concurrent_tasks)

# Examples:
# - 0/5 tasks → 100% available
# - 2/5 tasks → 60% available
# - 5/5 tasks → 0% available (busy)
```

---

## Knowledge Sharing Protocol

### Knowledge Entry Structure

```python
@dataclass
class KnowledgeEntry:
    """A piece of shared knowledge."""

    id: str
    type: KnowledgeType  # pattern, solution, lesson, best_practice, etc.
    topic: str
    content: str
    source_agent: str
    confidence: float  # 0.0 to 1.0
    created_at: datetime
    tags: List[str]
    upvotes: int
    downvotes: int
    metadata: Dict[str, Any]
```

### Knowledge Types

```python
class KnowledgeType(str, Enum):
    PATTERN = "pattern"              # Design patterns
    SOLUTION = "solution"            # Solutions to problems
    LESSON = "lesson"                # Lessons learned
    BEST_PRACTICE = "best_practice"  # Best practices
    ANTIPATTERN = "antipattern"      # Anti-patterns to avoid
    INSIGHT = "insight"              # Insights and discoveries
    METRIC = "metric"                # Metrics and measurements
```

### Sharing Flow

```
Agent A                    Knowledge Base
│                               │
├── SHARE(knowledge) ──────────>│
│                               ├── Store entry
│                               ├── Update reputation
│                               ├── Index by topic/tags
│                               └── ACK ─────────────────>│
│                               │
```

**Request Format**:
```json
{
  "type": "share_knowledge",
  "knowledge": {
    "type": "best_practice",
    "topic": "API Design",
    "content": "Use RESTful principles for API design",
    "source_agent": "python-pro-001",
    "confidence": 0.95,
    "tags": ["api", "rest", "design"]
  }
}
```

### Knowledge Retrieval

```python
def get_knowledge(
    topic: Optional[str] = None,
    knowledge_type: Optional[KnowledgeType] = None,
    tags: Optional[List[str]] = None,
    limit: int = 20,
) -> List[KnowledgeEntry]:
    """
    Retrieve knowledge from swarm.

    Ranking: confidence * (1 + upvotes - downvotes)
    """
    entries = list(knowledge_base.values())

    # Apply filters
    if topic:
        entries = [e for e in entries if topic.lower() in e.topic.lower()]

    if knowledge_type:
        entries = [e for e in entries if e.type == knowledge_type]

    if tags:
        entries = [e for e in entries if any(t in e.tags for t in tags)]

    # Sort by quality score
    entries.sort(
        key=lambda e: e.confidence * (1 + e.upvotes - e.downvotes),
        reverse=True
    )

    return entries[:limit]
```

### Knowledge Voting

Agents can vote on knowledge entries to surface high-quality content:

```python
def vote_knowledge(
    knowledge_id: str,
    agent_id: str,
    upvote: bool = True,
) -> bool:
    """Vote on knowledge entry."""
    if knowledge_id in knowledge_base:
        entry = knowledge_base[knowledge_id]
        if upvote:
            entry.upvotes += 1
        else:
            entry.downvotes += 1
        return True
    return False
```

---

## Collaboration Modes

### Mode Comparison

| Mode | Description | Use Case | Coordination |
|------|-------------|----------|--------------|
| **Parallel** | All agents work independently | Code generation, testing | Low |
| **Sequential** | Agents work in sequence | Refactoring, review | Medium |
| **Debate** | Agents discuss and debate | Architecture decisions | High |
| **Consensus** | Agents build agreement | Design choices | Very High |
| **Voting** | Agents vote on options | Binary decisions | Medium |
| **Swarm** | Emergent intelligence | Optimization, search | Dynamic |

### Parallel Collaboration

All agents work independently on the same task:

```
Task: "Implement REST API"
│
├── Agent 1: Implement /users endpoint
├── Agent 2: Implement /posts endpoint
├── Agent 3: Implement /comments endpoint
└── Agent 4: Write tests
```

**Algorithm**:
```python
async def parallel_collaboration(
    task: str,
    participants: List[str],
) -> CollaborationResult:
    """Execute parallel collaboration."""
    # Assign subtasks to each agent
    subtasks = partition_task(task, len(participants))

    # Execute concurrently
    results = await asyncio.gather(*[
        agent.execute(subtask)
        for agent, subtask in zip(participants, subtasks)
    ])

    # Aggregate results
    return aggregate_results(results)
```

### Sequential Collaboration

Agents work in sequence, each building on previous work:

```
Task: "Refactor legacy code"
│
├── Agent 1: Analyze code structure
│   ↓
├── Agent 2: Identify refactoring opportunities
│   ↓
├── Agent 3: Apply refactoring patterns
│   ↓
└── Agent 4: Verify and test
```

**Algorithm**:
```python
async def sequential_collaboration(
    task: str,
    participants: List[str],
) -> CollaborationResult:
    """Execute sequential collaboration."""
    context = {}

    # Execute in sequence
    for i, agent in enumerate(participants):
        subtask = derive_subtask(task, i, context)
        result = await agent.execute(subtask)
        context.update(result.context)

    return final_result(context)
```

### Debate Mode

Agents discuss and debate, exchanging arguments:

```
Topic: "Microservices vs Monolith"
│
├── Agent A: Pro-microservices arguments
├── Agent B: Pro-monolith arguments
├── Agent C: Synthesis and counter-arguments
├── Agent D: Final recommendation
└── Agent E: Risk assessment
```

**Algorithm**:
```python
async def debate_collaboration(
    topic: str,
    participants: List[str],
    rounds: int = 3,
) -> DebateResult:
    """Execute debate collaboration."""
    messages = []

    for round_num in range(rounds):
        # Each agent provides argument
        for agent in participants:
            argument = await agent.provide_argument(topic, messages)
            messages.append({
                "agent": agent.id,
                "argument": argument,
                "round": round_num
            })

    # Synthesize final position
    synthesis = await synthesize_debate(messages)
    return synthesis
```

### Consensus Mode

Agents work toward agreement:

```
Topic: "API Authentication Strategy"
│
├── Round 1:
│   ├── Agent A: JWT
│   ├── Agent B: OAuth2
│   ├── Agent C: API keys
│   └── Facilitator: Identify convergence
│
├── Round 2:
│   ├── Agent A: OAuth2 (modified)
│   ├── Agent B: OAuth2 (agrees)
│   ├── Agent C: Hybrid approach
│   └── Facilitator: Narrow options
│
└── Round 3:
    ├── All: OAuth2 + API keys fallback
    └── Facilitator: Consensus reached!
```

**Algorithm**:
```python
async def consensus_collaboration(
    topic: str,
    participants: List[str],
    strategy: ConsensusStrategy = ConsensusStrategy.DELPHI,
    max_rounds: int = 3,
) -> ConsensusResult:
    """Execute consensus collaboration."""
    positions = {p: None for p in participants}

    for round_num in range(max_rounds):
        # Gather positions
        for agent in participants:
            positions[agent] = await agent.get_position(topic, positions)

        # Check convergence
        if check_convergence(positions):
            return ConsensusResult(
                reached=True,
                agreement=positions.values()[0],
                rounds=round_num + 1
            )

        # Facilitator provides feedback
        feedback = facilitate(positions)
        await broadcast_feedback(participants, feedback)

    return ConsensusResult(reached=False)
```

### Swarm Mode

Emergent intelligence through agent interaction:

```
Objective: "Optimize database queries"
│
├── Initialize swarm (100 agents)
│   ├── Random initial solutions
│   └── Set pheromone trails
│
├── Iteration 1-100:
│   ├── Each agent explores solution space
│   ├── Leave pheromones on good solutions
│   ├── Evaporate pheromones on poor solutions
│   └── Agents follow pheromone trails
│
└── Converge on optimal solution
```

**Algorithm**:
```python
async def swarm_optimization(
    objective: str,
    agents: List[str],
    iterations: int = 100,
) -> SwarmResult:
    """Execute swarm optimization."""
    # Initialize
    solutions = {a: random_solution() for a in agents}
    pheromones = defaultdict(float)

    for i in range(iterations):
        # Each agent explores
        for agent in agents:
            solution = await agent.explore(pheromones)
            quality = evaluate_solution(solution)

            # Update pheromones
            if quality > threshold:
                pheromones[solution] += quality

        # Evaporate
        for solution in list(pheromones.keys()):
            pheromones[solution] *= 0.95

        # Check convergence
        if convergence(pheromones) > 0.9:
            break

    return best_solution(pheromones)
```

---

## Voting and Decision Making

### Proposal Structure

```python
@dataclass
class Proposal:
    """A proposal for voting."""

    id: str
    title: str
    description: str
    proposed_by: str
    votes: List[Vote]
    vote_type: VoteType
    created_at: datetime
    closes_at: Optional[datetime]
    status: str  # open, passed, rejected, failed
```

### Vote Types

```python
class VoteType(str, Enum):
    MAJORITY = "majority"        # >50% yes votes
    SUPERMAJORITY = "supermajority"  # >66% yes votes
    UNANIMOUS = "unanimous"      # 100% yes votes
    WEIGHTED = "weighted"        # Weighted by reputation
    QUORUM = "quorum"            # Minimum participation required
```

### Voting Algorithms

#### Majority Vote

```python
def check_majority(proposal: Proposal) -> str:
    """Check majority vote."""
    total = len(proposal.votes)
    yes = sum(1 for v in proposal.votes if v.decision)

    if total == 0:
        return "open"

    ratio = yes / total

    if ratio > 0.5:
        return "passed"
    elif ratio < 0.5:
        return "rejected"
    else:
        return "open"  # Tie
```

#### Supermajority Vote

```python
def check_supermajority(proposal: Proposal) -> str:
    """Check supermajority vote (>66%)."""
    total = len(proposal.votes)
    yes = sum(1 for v in proposal.votes if v.decision)

    if total == 0:
        return "open"

    ratio = yes / total

    if ratio > 0.66:
        return "passed"
    elif ratio < 0.34 and total > 5:  # Can't reach supermajority
        return "rejected"
    else:
        return "open"
```

#### Weighted Vote

```python
def check_weighted(proposal: Proposal) -> str:
    """Check weighted vote (by reputation)."""
    yes_weight = sum(v.weight for v in proposal.votes if v.decision)
    no_weight = sum(v.weight for v in proposal.votes if not v.decision)
    total = yes_weight + no_weight

    if total == 0:
        return "open"

    ratio = yes_weight / total

    if ratio > 0.5:
        return "passed"
    elif ratio < 0.5:
        return "rejected"
    else:
        return "open"
```

### Voting Flow

```
Agent A (Proposer)          Protocol                   Swarm
│                                                    │
├── CREATE_PROPOSAL ────────>│                        │
│                           ├── Store proposal        │
│                           └── Broadcast ───────────>│
│                                                    │
Agent B, C, D (Voters)                               │
│                           │                        │
├── CAST_VOTE(yes) ─────────>│                        │
│                           ├── Accumulate votes     │
│                           ├── Check threshold     │
│                           └── Update status       │
│                           │                        │
                           ├── Broadcast result ────>│
                           └── ACK ────────────────>│
```

---

## Consensus Building

### Consensus Strategies

```python
class ConsensusStrategy(str, Enum):
    DELPHI = "delphi"                      # Iterative expert opinion
    NOMINAL_GROUP = "nominal_group"        # Structured discussion
    CONSENSUS_75 = "consensus_75"          # 75% agreement required
    CONSENSUS_100 = "consensus_100"        # 100% agreement required
    MAJORITY_FALLBACK = "majority_fallback"  # Fall back to majority
```

### Delphi Method

Iterative expert opinion with controlled feedback:

```
Round 1:
  Agent A: Position X (confidence: 0.6)
  Agent B: Position Y (confidence: 0.7)
  Agent C: Position Z (confidence: 0.5)

  Facilitator: Positions are diverse, consider convergence

Round 2:
  Agent A: Position Y (confidence: 0.7) [moved toward B]
  Agent B: Position Y (confidence: 0.8) [maintained]
  Agent C: Position Y (confidence: 0.6) [moved toward B]

  Facilitator: Convergence detected, final round

Round 3:
  Agent A: Position Y (confidence: 0.8)
  Agent B: Position Y (confidence: 0.9)
  Agent C: Position Y (confidence: 0.7)

  Facilitator: Consensus reached on Position Y
```

**Algorithm**:
```python
async def delphi_consensus(
    topic: str,
    participants: List[str],
    max_rounds: int = 3,
) -> ConsensusResult:
    """Delphi consensus method."""
    positions = {}
    round_results = []

    for round_num in range(1, max_rounds + 1):
        # Gather positions
        for agent in participants:
            positions[agent] = await agent.get_position(
                topic,
                round_results,  # Previous round feedback
            )

        # Calculate convergence
        convergence = calculate_convergence(positions)

        round_results.append({
            "round": round_num,
            "positions": positions.copy(),
            "convergence": convergence,
            "feedback": generate_feedback(positions, convergence)
        })

        # Check for consensus
        if convergence >= 0.8:
            return ConsensusResult(
                reached=True,
                agreement=most_common(positions),
                rounds=round_num,
                final_convergence=convergence
            )

    # No consensus
    return ConsensusResult(
        reached=False,
        agreement=None,
        rounds=max_rounds,
        final_convergence=round_results[-1]["convergence"]
    )
```

### Nominal Group Technique

Structured discussion with prioritization:

```
Step 1: Silent Generation
  Agent A: Idea 1, Idea 2
  Agent B: Idea 3, Idea 4, Idea 5
  Agent C: Idea 6

Step 2: Round-Robin Sharing
  Agent A shares: Idea 1, Idea 2
  Agent B shares: Idea 3, Idea 4, Idea 5
  Agent C shares: Idea 6

Step 3: Group Discussion
  All agents discuss and clarify ideas

Step 4: Ranking
  Agent A ranks: 5, 3, 1, 6, 4, 2
  Agent B ranks: 3, 5, 4, 1, 6, 2
  Agent C ranks: 3, 4, 5, 1, 2, 6

Step 5: Aggregation
  Idea 1: 5+4+4 = 13
  Idea 3: 3+5+5 = 13
  Idea 4: 2+3+4 = 9
  ...
  Consensus: Ideas 1 and 3 (tie)
```

**Algorithm**:
```python
async def nominal_group_consensus(
    topic: str,
    participants: List[str],
) -> ConsensusResult:
    """Nominal group technique."""
    # Step 1: Silent generation
    ideas = {}
    for agent in participants:
        ideas[agent] = await agent.generate_ideas(topic)

    # Step 2: Round-robin sharing (implicit via ideas collection)

    # Step 3: Group discussion
    all_ideas = list(set([i for ideas_list in ideas.values() for i in ideas_list]))
    await discuss_ideas(participants, all_ideas)

    # Step 4: Ranking
    rankings = {}
    for agent in participants:
        rankings[agent] = await agent.rank_ideas(all_ideas)

    # Step 5: Aggregation
    aggregated = aggregate_rankings(rankings)
    top_idea = aggregated[0]

    return ConsensusResult(
        reached=True,
        agreement=top_idea,
        rounds=1,
        details=aggregated
    )
```

### Consensus Thresholds

| Strategy | Agreement Required | Use Case |
|----------|-------------------|----------|
| CONSENSUS_100 | 100% | Critical decisions, safety |
| CONSENSUS_75 | 75% | Important decisions |
| MAJORITY_FALLBACK | 100% → 51% | When consensus fails |
| DELPHI | Convergence ≥ 80% | Expert opinion |
| NOMINAL_GROUP | Top-ranked | Structured decisions |

---

## Reputation System

### Reputation Score Structure

```python
@dataclass
class ReputationScore:
    """Reputation score for an agent."""

    agent_id: str
    total_score: float           # Overall score
    successful_tasks: int        # Successful completions
    failed_tasks: int            # Failed tasks
    votes_cast: int              # Participation in voting
    knowledge_contributions: int # Knowledge shared
    collaboration_participations: int  # Collaborations joined
    consensus_agreements: int    # Consensus reached
    last_updated: datetime
    history: List[Dict[str, Any]]
```

### Reputation Levels

```python
def reputation_level(score: float) -> str:
    """Calculate reputation level."""
    if score >= 100:
        return "expert"      # Trusted authority
    elif score >= 50:
        return "senior"      # Experienced contributor
    elif score >= 20:
        return "intermediate"  # Regular participant
    elif score >= 5:
        return "junior"      # New but proven
    else:
        return "novice"      # Unproven
```

### Score Calculation

```python
def update_reputation(
    reputation: ReputationScore,
    event: ReputationEvent,
) -> None:
    """Update reputation based on event."""

    if event.type == "task_completed":
        # Success: +5 * confidence
        reputation.successful_tasks += 1
        reputation.total_score += 5.0 * event.confidence

    elif event.type == "task_failed":
        # Failure: -2.5 (partial penalty)
        reputation.failed_tasks += 1
        reputation.total_score -= 2.5

    elif event.type == "knowledge_shared":
        # Knowledge: +5 * confidence
        reputation.knowledge_contributions += 1
        reputation.total_score += 5.0 * event.confidence

    elif event.type == "vote_cast":
        # Voting: +0.5 (participation)
        reputation.votes_cast += 1
        reputation.total_score += 0.5

    elif event.type == "consensus_reached":
        # Consensus: +10 (significant)
        reputation.consensus_agreements += 1
        reputation.total_score += 10.0

    elif event.type == "knowledge_upvoted":
        # Upvote: +2
        reputation.total_score += 2.0

    elif event.type == "knowledge_downvoted":
        # Downvote: -1
        reputation.total_score -= 1.0

    # Prevent negative scores
    reputation.total_score = max(0.0, reputation.total_score)
    reputation.last_updated = datetime.now(UTC)
```

### Reputation Weighting

Reputation influences vote weight and task selection:

```python
def vote_weight(agent_id: str) -> float:
    """Calculate vote weight based on reputation."""
    reputation = get_reputation(agent_id)

    # Base weight: 1.0
    # Bonus: reputation_score / 100
    # Expert (100+): 2.0x weight
    # Senior (50+): 1.5x weight
    # Junior (5+): 1.05x weight
    # Novice: 1.0x weight

    return 1.0 + (reputation.total_score / 100.0)
```

### Reputation Decay

To prevent stagnation, reputation decays slowly over time:

```python
def apply_reputation_decay(reputation: ReputationScore) -> None:
    """Apply time-based decay to reputation."""
    days_since_update = (datetime.now(UTC) - reputation.last_updated).days

    # Decay rate: 0.1% per day
    # After 1 year: ~30% decay
    # Active agents maintain reputation

    decay_factor = 1.0 - (0.001 * days_since_update)
    reputation.total_score *= max(0.7, decay_factor)
```

---

## Swarm Intelligence

### Particle Swarm Optimization (PSO)

Inspired by bird flocking behavior:

```python
@dataclass
class Particle:
    """A particle in the swarm."""
    position: List[float]      # Current solution
    velocity: List[float]      # Direction and speed
    best_position: List[float] # Personal best
    best_fitness: float        # Personal best fitness

async def particle_swarm_optimization(
    objective: Callable[[List[float]], float],
    dimensions: int,
    swarm_size: int = 30,
    iterations: int = 100,
) -> SwarmResult:
    """Particle swarm optimization."""

    # Initialize swarm
    particles = [
        Particle(
            position=random_vector(dimensions),
            velocity=random_vector(dimensions),
            best_position=None,
            best_fitness=float('-inf')
        )
        for _ in range(swarm_size)
    ]

    global_best_position = None
    global_best_fitness = float('-inf')

    # Main loop
    for iteration in range(iterations):
        for particle in particles:
            # Evaluate fitness
            fitness = objective(particle.position)

            # Update personal best
            if fitness > particle.best_fitness:
                particle.best_fitness = fitness
                particle.best_position = particle.position.copy()

            # Update global best
            if fitness > global_best_fitness:
                global_best_fitness = fitness
                global_best_position = particle.position.copy()

        # Update velocities and positions
        for particle in particles:
            # PSO equations
            r1, r2 = random(), random()
            cognitive = 2.0 * r1 * (particle.best_position - particle.position)
            social = 2.0 * r2 * (global_best_position - particle.position)

            particle.velocity = (
                0.7 * particle.velocity +  # Inertia
                cognitive +
                social
            )

            particle.position += particle.velocity

        # Check convergence
        if converged(global_best_fitness, iteration):
_nearby(particles)):
            break

    return SwarmResult(
        best_solution=global_best_position,
        best_fitness=global_best_fitness,
        iterations=iteration + 1
    )
```

### Ant Colony Optimization (ACO)

Inspired by ant foraging behavior:

```python
async def ant_colony_optimization(
    graph: Graph,
    start: Node,
    end: Node,
    ant_count: int = 20,
    iterations: int = 100,
) -> SwarmResult:
    """Ant colony optimization for path finding."""

    pheromones = defaultdict(float)  # Edge -> pheromone level
    best_path = None
    best_length = float('inf')

    for iteration in range(iterations):
        all_paths = []

        # Each ant constructs a path
        for _ in range(ant_count):
            path = construct_path(graph, start, end, pheromones)
            length = path_length(path)
            all_paths.append((path, length))

            # Update best
            if length < best_length:
                best_length = length
                best_path = path

        # Evaporate pheromones
        for edge in pheromones:
            pheromones[edge] *= 0.95  # Evaporation rate

        # Deposit pheromones
        for path, length in all_paths:
            # Shorter paths get more pheromones
            deposit = 1.0 / length
            for edge in path.edges():
                pheromones[edge] += deposit

    return SwarmResult(
        best_solution=best_path,
        best_fitness=1.0 / best_length,
        iterations=iterations
    )

def construct_path(
    graph: Graph,
    start: Node,
    end: Node,
    pheromones: Dict[Edge, float],
) -> Path:
    """Construct path based on pheromones."""
    current = start
    path = [current]

    while current != end:
        neighbors = graph.neighbors(current)

        # Calculate probabilities
        probabilities = []
        for neighbor in neighbors:
            edge = (current, neighbor)
            pheromone = pheromones[edge]
            heuristic = 1.0 / distance(current, neighbor)
            probabilities.append(pheromone * heuristic)

        # Normalize
        total = sum(probabilities)
        probabilities = [p / total for p in probabilities]

        # Choose next node
        current = random_choice(neighbors, probabilities)
        path.append(current)

    return path
```

### Swarm Coordination Patterns

#### 1. Leader-Follower Pattern

```
Leader Agent discovers optimal solution
│
├── Broadcasts pheromone trail
│
└── Follower Agents reinforce best solution
```

#### 2. Distributed Pattern

```
All Agents explore independently
│
├── Share discoveries periodically
│
└── Converge on consensus
```

#### 3. Hierarchical Pattern

```
Level 1 Agents (Strategic)
│
├── Level 2 Agents (Tactical)
│   │
│   └── Level 3 Agents (Operational)
```

---

## Message Formats

### Discovery Message

```json
{
  "type": "discover",
  "capability": "code_analysis",
  "min_availability": 0.5,
  "max_results": 10,
  "request_id": "req-001"
}
```

**Response**:
```json
{
  "type": "discover_response",
  "agents": [
    {
      "id": "python-pro-001",
      "name": "Python Expert",
      "type": "python-pro",
      "capabilities": ["code_analysis", "code_generation"],
      "availability_ratio": 0.8,
      "current_tasks": 1,
      "max_concurrent_tasks": 5
    }
  ],
  "request_id": "req-001"
}
```

### Knowledge Share Message

```json
{
  "type": "share_knowledge",
  "knowledge": {
    "id": "knowledge-001",
    "type": "best_practice",
    "topic": "API Design",
    "content": "Use RESTful principles",
    "source_agent": "python-pro-001",
    "confidence": 0.95,
    "tags": ["api", "rest"],
    "timestamp": "2026-02-05T12:00:00Z"
  }
}
```

### Collaboration Start Message

```json
{
  "type": "start_collaboration",
  "session": {
    "id": "collab-001",
    "task": "Design REST API",
    "mode": "debate",
    "participants": ["agent-001", "agent-002", "agent-003"],
    "parameters": {
      "rounds": 3,
      "timeout": 300
    }
  }
}
```

### Vote Message

```json
{
  "type": "cast_vote",
  "vote": {
    "proposal_id": "proposal-001",
    "agent_id": "agent-001",
    "decision": true,
    "confidence": 0.9,
    "rationale": "This approach is most scalable",
    "weight": 1.5,
    "timestamp": "2026-02-05T12:00:00Z"
  }
}
```

### Consensus Message

```json
{
  "type": "consensus_round",
  "round": {
    "round_number": 2,
    "topic": "Architecture style",
    "strategy": "delphi",
    "positions": {
      "agent-001": "Microservices",
      "agent-002": "Microservices",
      "agent-003": "Monolith"
    },
    "convergence": 0.67,
    "feedback": "Partial convergence, continue discussion"
  }
}
```

---

## Coordination Patterns

### Ring Coordination

Agents coordinate in a ring topology:

```
Agent A → Agent B → Agent C → Agent D → Agent A
```

**Use Case**: Sequential processing, pipeline workflows

### Star Coordination

Central coordinator manages agents:

```
        Coordinator
         /    |    \
        A     B     C
```

**Use Case**: Task distribution, result aggregation

### Mesh Coordination

All agents communicate with all others:

```
    A —— B
    | \  |
    |  \ |
    D —— C
```

**Use Case**: Peer-to-peer collaboration, consensus building

### Tree Coordination

Hierarchical coordination:

```
       Root
      / | \
     A  B  C
    /|  |
   D E  F
```

**Use Case**: Multi-level decision making, delegation

---

## Visualization and Monitoring

### Swarm Visualization

```python
def visualize_swarm(
    agents: List[AgentDescriptor],
    collaborations: List[CollaborationSession],
    knowledge: List[KnowledgeEntry],
) -> Visualization:
    """Generate swarm visualization."""
    # Create network graph
    graph = NetworkGraph()

    # Add agent nodes
    for agent in agents:
        graph.add_node(
            agent.id,
            label=agent.name,
            capabilities=agent.capabilities,
            availability=agent.availability_ratio,
        )

    # Add collaboration edges
    for collab in collaborations:
        for i, p1 in enumerate(collab.participants):
            for p2 in collab.participants[i+1:]:
                graph.add_edge(p1, p2, type="collaboration")

    # Add knowledge edges
    topic_groups = defaultdict(list)
    for entry in knowledge:
        topic_groups[entry.topic].append(entry.source_agent)

    for topic, contributors in topic_groups.items():
        if len(contributors) > 1:
            for i, c1 in enumerate(contributors):
                for c2 in contributors[i+1:]:
                    graph.add_edge(c1, c2, type="knowledge", topic=topic)

    return graph.render()
```

### Knowledge Graph Visualization

```python
def visualize_knowledge_graph(
    knowledge: List[KnowledgeEntry],
) -> Visualization:
    """Generate knowledge graph visualization."""
    graph = KnowledgeGraph()

    # Create topic nodes
    topics = set(k.topic for k in knowledge)
    for topic in topics:
        entries = [k for k in knowledge if k.topic == topic]
        graph.add_topic_node(
            topic,
            entry_count=len(entries),
            avg_confidence=sum(k.confidence for k in entries) / len(entries),
        )

    # Create agent nodes
    agents = set(k.source_agent for k in knowledge)
    for agent in agents:
        agent_entries = [k for k in knowledge if k.source_agent == agent]
        graph.add_agent_node(
            agent,
            contribution_count=len(agent_entries),
        )

    # Link agents to topics
    for entry in knowledge:
        graph.add_contribution_edge(
            entry.source_agent,
            entry.topic,
            confidence=entry.confidence,
            entry_type=entry.type,
        )

    return graph.render()
```

### Real-Time Monitoring

```python
async def monitor_swarm(
    engine: CollaborativeIntelligenceEngine,
    refresh_interval: int = 2,
) -> None:
    """Real-time swarm monitoring dashboard."""

    while True:
        # Gather metrics
        status = engine.get_swarm_status()

        # Display
        clear_screen()
        print_header(f"Swarm Monitor - {datetime.now()}")
        print_metrics(status)
        print_active_collaborations(engine)
        print_active_proposals(engine)
        print_recent_knowledge(engine)

        await asyncio.sleep(refresh_interval)
```

---

## Best Practices

### 1. Agent Capability Design

**DO**:
- Declare specific, focused capabilities
- Keep capability list manageable (3-7 capabilities)
- Align capabilities with actual abilities

**DON'T**:
- Overdeclare capabilities (reputation penalty)
- Declare vague or overlapping capabilities
- Change capabilities frequently

### 2. Knowledge Sharing

**DO**:
- Share high-quality, actionable knowledge
- Provide confidence estimates
- Tag knowledge appropriately
- Vote on others' knowledge

**DON'T**:
- Share low-confidence knowledge as fact
- Spam the knowledge base
- Share duplicate knowledge
- Downvote competing knowledge unfairly

### 3. Collaboration Participation

**DO**:
- Choose appropriate collaboration mode
- Participate actively and constructively
- Respect other agents' contributions
- Build on others' ideas

**DON'T**:
- Dominate discussions
- Dismiss others' perspectives
- Withhold relevant information
- Create unnecessary conflicts

### 4. Voting

**DO**:
- Vote based on evidence and expertise
- Provide rationale for votes
- Consider reputation weights
- Participate in important votes

**DON'T**:
- Vote strategically to manipulate outcomes
- Ignore reputation-based weighting
 abstain from important votes
- Follow the herd blindly

### 5. Consensus Building

**DO**:
- Approach consensus with open mind
- Provide constructive feedback
- Converge toward agreement
- Use appropriate consensus strategy

**DON'T**:
- Refuse to compromise
- Dismiss consensus strategies
- Block consensus unnecessarily
// Leave process before agreement

---

## API Reference

### CLI Commands

#### `mahavishnu swarm agents`
List all agents in the swarm.

```bash
mahavishnu swarm agents [--capability CAP] [--available] [--json]
```

#### `mahavishnu swarm discover`
Discover agents by capability.

```bash
mahavishnu swarm discover --capability CAP [--min-availability N] [--max-count N]
```

#### `mahavishnu swarm share`
Share knowledge with the swarm.

```bash
mahavishnu swarm share --topic TOPIC --content CONTENT [--type TYPE] [--confidence N]
```

#### `mahavishnu swarm knowledge`
Show shared knowledge base.

```bash
mahavishnu swarm knowledge [--topic TOPIC] [--type TYPE] [--limit N]
```

#### `mahavishnu swarm collaborate`
Start a collaboration session.

```bash
mahavishnu swarm collaborate --task TASK [--mode MODE] [--participants LIST]
```

#### `mahavishnu swarm vote`
Create a proposal for voting.

```bash
mahavishnu swarm vote --title TITLE [--description DESC] [--vote-type TYPE]
```

#### `mahavishnu swarm consensus`
Build consensus among agents.

```bash
mahavishnu swarm consensus --topic TOPIC [--strategy STRATEGY] [--rounds N]
```

#### `mahavishnu swarm optimize`
Run swarm optimization.

```bash
mahavishnu swarm optimize --swarm-id ID --objective OBJ [--iterations N]
```

#### `mahavishnu swarm reputation`
Show agent reputation scores.

```bash
mahavishnu swarm reputation [--agent-id ID]
```

#### `mahavishnu swarm monitor`
Real-time swarm monitoring.

```bash
mahavishnu swarm monitor [--interval N]
```

### Python API

#### CollaborativeIntelligenceEngine

```python
from mahavishnu.integrations.collaborative_intelligence_cli import (
    CollaborativeIntelligenceEngine,
    KnowledgeEntry,
    CollaborationMode,
    ConsensusStrategy,
)

# Create engine
engine = CollaborativeIntelligenceEngine()

# Share knowledge
entry = KnowledgeEntry(
    type=KnowledgeType.BEST_PRACTICE,
    topic="API Design",
    content="Use RESTful principles",
    source_agent="python-pro-001",
    confidence=0.95,
)
engine.share_knowledge(entry)

# Start collaboration
session = await engine.start_collaboration(
    task="Design REST API",
    mode=CollaborationMode.DEBATE,
    participants=["agent-001", "agent-002", "agent-003"],
)

# Build consensus
result = await engine.build_consensus(
    topic="Architecture style",
    participants=["agent-001", "agent-002"],
    strategy=ConsensusStrategy.DELPHI,
)

# Check reputation
reputation = engine.get_reputation("python-pro-001")
```

---

## Conclusion

The Collaborative Intelligence protocols provide a comprehensive framework for multi-agent coordination, enabling:

- **Organic Collaboration**: Agents work together naturally
- **Knowledge Sharing**: Swarm learning accelerates improvement
- **Democratic Decision Making**: Voting and consensus building
- **Reputation Tracking**: Quality and trustworthiness emerge
- **Swarm Intelligence**: Emergent problem-solving

These protocols lay the foundation for sophisticated multi-agent systems that can tackle complex tasks through collective intelligence.

---

**Document Version**: 1.0.0
**Last Updated**: 2026-02-05
**Author**: Mahavishn Collaborative Intelligence Team
