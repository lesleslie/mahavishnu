# Phase 4 Policy Adjustment Engine & A/B Testing - Implementation Plan

## Overview

This document outlines the implementation of Phase 4 of the ORB Learning Feedback Loops system: Policy Adjustment Engine & A/B Testing Framework.

## Context

**Completed Phases:**
- Phase 1: Execution Intelligence (telemetry capture, database storage, semantic search)
- Phase 2: Quality Control (automated quality gates, validation pipeline)
- Phase 3: Knowledge Graph (solution patterns, contextual recommendations)

**Current Phase (Phase 4):**
- Policy Adjustment Engine with reinforcement learning
- A/B testing framework for policy validation
- Multi-arm bandit optimization

## Architecture

### Policy Engine (`mahavishnu/learning/policy/`)

```
policy/
├── __init__.py           # Package exports
├── adjustment.py         # Policy adjustment engine
├── reinforcement.py      # Reinforcement learning (Q-learning)
└── bandit.py             # Multi-arm bandit optimization
```

#### 1. Policy Adjustment Engine (`adjustment.py`)

**Purpose:** Load, validate, and apply policy changes based on feedback.

**Key Features:**
- Load current policies from database
- Adjust policies based on aggregated feedback
- Validate policy changes before applying
- Rollback mechanism for bad policies
- Audit trail for all policy changes

**Data Models:**

```python
class PolicyAdjustment(BaseModel):
    """Single policy adjustment record."""
    policy_id: UUID
    adjustment_type: str  # "threshold", "weight", "routing"
    old_value: float
    new_value: float
    reason: str
    feedback_count: int
    confidence: float
    applied_at: datetime

class PolicySnapshot(BaseModel):
    """Snapshot of policy state for rollback."""
    snapshot_id: UUID
    policies: dict[str, float]
    timestamp: datetime
    performance_metrics: dict[str, float]
```

**Key Methods:**

```python
class PolicyAdjustmentEngine:
    async def load_policies(self, repo: str) -> dict[str, float]
    async def propose_adjustments(self, feedback: list[FeedbackRecord]) -> list[PolicyAdjustment]
    async def validate_adjustment(self, adjustment: PolicyAdjustment) -> bool
    async def apply_adjustment(self, adjustment: PolicyAdjustment) -> None
    async def create_snapshot(self) -> PolicySnapshot
    async def rollback_to_snapshot(self, snapshot_id: UUID) -> None
    async def get_adjustment_history(self, repo: str, days: int) -> list[PolicyAdjustment]
```

#### 2. Reinforcement Learning (`reinforcement.py`)

**Purpose:** Implement Q-learning for adaptive routing policies.

**State Space:**
- Task context: task_type, repo, complexity_score
- File context: file_count, estimated_tokens
- Historical context: recent_success_rate, avg_quality

**Action Space:**
- Model selection: small, medium, large
- Pool selection: mahavishnu, session-buddy, kubernetes
- Routing confidence: 0.0-1.0

**Reward Function:**
```python
def calculate_reward(execution: ExecutionRecord, feedback: Optional[FeedbackRecord]) -> float:
    """Calculate reward for reinforcement learning.

    Returns:
        +1.0: Excellent feedback, success, quality > 80
        +0.5: Good feedback, success
        +0.2: Success, no feedback
        -0.3: Fair feedback or quality < 60
        -1.0: Poor feedback or failure
    """
```

**Key Methods:**

```python
class QLearningRouter:
    def __init__(self, learning_rate: float = 0.1, discount_factor: float = 0.9, epsilon: float = 0.1)
    async def get_state(self, task: dict) -> str
    async def select_action(self, state: str) -> str  # ε-greedy
    async def update_q_value(self, state: str, action: str, reward: float, next_state: str) -> None
    async def learn_from_execution(self, execution: ExecutionRecord, feedback: Optional[FeedbackRecord]) -> None
    async def save_q_table(self, path: str) -> None
    async def load_q_table(self, path: str) -> None
```

#### 3. Multi-Arm Bandit (`bandit.py`)

**Purpose:** Optimize exploration/exploitation tradeoff for routing decisions.

**Algorithms:**
1. **Epsilon-Greedy**: ε=0.1, 10% exploration
2. **UCB (Upper Confidence Bound)**: Optimism in face of uncertainty
3. **Thompson Sampling**: Bayesian optimization with Beta priors

**Key Methods:**

```python
class EpsilonGreedyBandit:
    async def select_arm(self, context: dict) -> str
    async def update_reward(self, arm: str, reward: float) -> None

class UCBBandit:
    async def select_arm(self, context: dict) -> str
    async def update_reward(self, arm: str, reward: float) -> None

class ThompsonSamplingBandit:
    async def select_arm(self, context: dict) -> str
    async def update_reward(self, arm: str, reward: float) -> None
```

### A/B Testing Framework (`mahavishnu/learning/experiments/`)

```
experiments/
├── __init__.py           # Package exports
├── ab_testing.py         # A/B testing framework
└── metrics.py            # Experiment metrics and statistics
```

#### 4. A/B Testing (`ab_testing.py`)

**Purpose:** Run controlled experiments to validate policy changes.

**Data Models:**

```python
class ExperimentVariant(BaseModel):
    """Single variant in an A/B test."""
    variant_id: str  # "control", "treatment_a", "treatment_b"
    description: str
    policy_config: dict[str, Any]
    traffic_allocation: float  # 0.0-1.0

class Experiment(BaseModel):
    """A/B test experiment."""
    experiment_id: UUID
    name: str
    hypothesis: str
    variants: list[ExperimentVariant]
    status: str  # "draft", "running", "completed", "failed"
    start_time: Optional[datetime]
    end_time: Optional[datetime]
    min_sample_size: int
    metrics: list[str]  # ["success_rate", "avg_duration", "cost"]
```

**Key Methods:**

```python
class ABTestingFramework:
    async def create_experiment(self, experiment: Experiment) -> UUID
    async def assign_variant(self, task: dict) -> str  # Stratified random assignment
    async def record_metric(self, experiment_id: UUID, variant_id: str, metric: str, value: float) -> None
    async def analyze_results(self, experiment_id: UUID) -> dict[str, Any]
    async def check_significance(self, experiment_id: UUID) -> bool
    async def stop_early(self, experiment_id: UUID, reason: str) -> None
    async def get_recommendation(self, experiment_id: UUID) -> str  # Which variant won?
```

**Statistical Tests:**
- Student's t-test for continuous metrics (duration, cost)
- Chi-square test for categorical metrics (success rate)
- Fisher's exact test for small samples
- Welch's t-test for unequal variances

**Early Stopping Rules:**
- **Success winner**: p < 0.01, effect size > 0.5, min_samples_reached
- **Failure loser**: p > 0.5 (control winning), min_samples_reached
- **Futility stop**: Power analysis shows < 20% chance of reaching significance

#### 5. Experiment Metrics (`metrics.py`)

**Purpose:** Calculate statistical metrics for experiments.

**Key Metrics:**

```python
class ExperimentMetrics:
    async def calculate_success_rate(self, variant_data: list[dict]) -> float
    async def calculate_avg_duration(self, variant_data: list[dict]) -> float
    async def calculate_avg_cost(self, variant_data: list[dict]) -> float
    async def calculate_quality_score(self, variant_data: list[dict]) -> float

    # Statistical calculations
    async def calculate_confidence_interval(self, data: list[float], confidence: float = 0.95) -> tuple[float, float]
    async def calculate_effect_size(self, control: list[float], treatment: list[float]) -> float  # Cohen's d
    async def calculate_p_value(self, control: list[float], treatment: list[float], test: str = "ttest") -> float
    async def calculate_statistical_power(self, effect_size: float, sample_size: int, alpha: float = 0.05) -> float

    # Bayesian metrics
    async def calculate_posterior(self, prior: tuple[float, float], data: list[int]) -> tuple[float, float]
    async def calculate_prob_best(self, posteriors: list[tuple[float, float]]) -> list[float]
```

## Integration Points

### Database Schema Extensions

Add to `learning.db` schema:

```sql
-- Policy storage
CREATE TABLE policies (
    repo VARCHAR NOT NULL,
    policy_name VARCHAR NOT NULL,
    policy_value FLOAT NOT NULL,
    last_adjusted TIMESTAMP,
    adjustment_reason TEXT,
    PRIMARY KEY (repo, policy_name)
);

-- Policy audit log
CREATE TABLE policy_adjustments (
    adjustment_id UUID PRIMARY KEY,
    repo VARCHAR NOT NULL,
    policy_name VARCHAR NOT NULL,
    old_value FLOAT,
    new_value FLOAT,
    reason TEXT,
    feedback_count INT,
    confidence FLOAT,
    applied_at TIMESTAMP,
    snapshot_id UUID
);

-- Policy snapshots (for rollback)
CREATE TABLE policy_snapshots (
    snapshot_id UUID PRIMARY KEY,
    repo VARCHAR NOT NULL,
    policies JSON NOT NULL,
    performance_metrics JSON,
    created_at TIMESTAMP
);

-- Q-table for reinforcement learning
CREATE TABLE q_table (
    state VARCHAR NOT NULL,
    action VARCHAR NOT NULL,
    q_value FLOAT NOT NULL,
    update_count INT DEFAULT 0,
    last_updated TIMESTAMP,
    PRIMARY KEY (state, action)
);

-- Experiments
CREATE TABLE experiments (
    experiment_id UUID PRIMARY KEY,
    name VARCHAR NOT NULL,
    hypothesis TEXT,
    variants JSON NOT NULL,
    status VARCHAR NOT NULL,
    start_time TIMESTAMP,
    end_time TIMESTAMP,
    min_sample_size INT,
    metrics JSON
);

-- Experiment assignments
CREATE TABLE experiment_assignments (
    assignment_id UUID PRIMARY KEY,
    experiment_id UUID NOT NULL,
    task_id UUID NOT NULL,
    variant_id VARCHAR NOT NULL,
    assigned_at TIMESTAMP
);

-- Experiment metrics
CREATE TABLE experiment_metrics (
    metric_id UUID PRIMARY KEY,
    experiment_id UUID NOT NULL,
    variant_id VARCHAR NOT NULL,
    metric_name VARCHAR NOT NULL,
    metric_value FLOAT NOT NULL,
    recorded_at TIMESTAMP
);
```

### SONARouter Integration

Update `SONARARouter` to use policy engine:

```python
class SONARouter:
    def __init__(self, ...):
        # Existing initialization
        self.policy_engine = PolicyAdjustmentEngine(db)
        self.rl_agent = QLearningRouter()
        self.bandit = ThompsonSamplingBandit()

    async def route_task(self, task: dict) -> RouteDecision:
        # 1. Get Q-learning action (exploration)
        state = await self.rl_agent.get_state(task)
        rl_action = await self.rl_agent.select_action(state)

        # 2. Get bandit recommendation (exploitation)
        bandit_arm = await self.bandit.select_arm(task)

        # 3. Get current policy baseline
        policy = await self.policy_engine.load_policies(task.get("repo", "default"))

        # 4. Combine recommendations (ensemble)
        # Weight: 40% RL, 40% bandit, 20% policy
        final_decision = self._ensemble_decisions(rl_action, bandit_arm, policy)

        return final_decision

    async def learn_from_outcome(self, task_id: str, outcome: dict, feedback: Optional[FeedbackRecord]) -> None:
        # Update Q-learning
        await self.rl_agent.learn_from_execution(outcome, feedback)

        # Update bandit
        reward = self._calculate_reward(outcome, feedback)
        await self.bandit.update_reward(outcome.get("action"), reward)

        # Trigger policy adjustment if needed
        if feedback and feedback.satisfaction in ["fair", "poor"]:
            await self.policy_engine.propose_adjustments([feedback])
```

### MCP Tools

Add to `mahavishnu/mcp/tools/`:

```python
@mcp.tool()
async def create_policy_experiment(
    name: str,
    hypothesis: str,
    variants: list[dict],
    min_sample_size: int = 100,
) -> str:
    """Create A/B test for policy validation.

    Args:
        name: Experiment name
        hypothesis: Hypothesis statement
        variants: List of variant configs [{"variant_id": "control", ...}, ...]
        min_sample_size: Minimum samples per variant

    Returns:
        Experiment ID
    """

@mcp.tool()
async def get_policy_recommendations(
    repo: str,
    task_type: Optional[str] = None,
) -> dict:
    """Get policy recommendations from RL and bandit.

    Args:
        repo: Repository name
        task_type: Optional task type filter

    Returns:
        Policy recommendations with confidence scores
    """

@mcp.tool()
async def analyze_experiment_results(
    experiment_id: str,
) -> dict:
    """Analyze A/B test results with statistics.

    Args:
        experiment_id: Experiment UUID

    Returns:
        Statistical analysis with p-values, effect sizes, recommendation
    """

@mcp.tool()
async def rollback_policy(
    repo: str,
    snapshot_id: str,
) -> dict:
    """Rollback policy to previous snapshot.

    Args:
        repo: Repository name
        snapshot_id: Snapshot UUID

    Returns:
        Rollback confirmation
    """
```

## Testing Strategy

### Unit Tests

**Policy Engine Tests** (`tests/unit/test_learning/test_policy/`):
- `test_adjustment.py`: Test policy adjustment logic
- `test_reinforcement.py`: Test Q-learning updates
- `test_bandit.py`: Test bandit algorithms

**Experiments Tests** (`tests/unit/test_learning/test_experiments/`):
- `test_ab_testing.py`: Test experiment lifecycle
- `test_metrics.py`: Test statistical calculations

### Integration Tests

- `test_policy_integration.py`: Test policy → router integration
- `test_experiment_integration.py`: Test A/B test → policy adjustment

### Test Coverage Goals

- Unit tests: 85%+ coverage
- Integration tests: Key workflows covered
- Statistical tests: Validate with known distributions

## Implementation Order

1. **Database schema**: Add new tables for policies, experiments
2. **Policy adjustment engine**: Core policy management
3. **Reinforcement learning**: Q-learning implementation
4. **Multi-arm bandit**: Three algorithms
5. **A/B testing framework**: Experiment management
6. **Metrics module**: Statistical calculations
7. **SONARouter integration**: Ensemble routing
8. **MCP tools**: User-facing interfaces
9. **Tests**: Comprehensive test coverage
10. **Documentation**: Usage examples and API docs

## Success Criteria

- [ ] Policy adjustment engine functional with rollback
- [ ] Q-learning converges to better routing (> 5% improvement)
- [ ] Bandit algorithms balance exploration/exploitation
- [ ] A/B tests correctly detect significant differences
- [ ] Statistical tests produce valid p-values and effect sizes
- [ ] Early stopping prevents wasted experiments
- [ ] Integration with SONARouter working
- [ ] MCP tools accessible and documented
- [ ] Test coverage > 85%
- [ ] Documentation complete with examples

## Risks and Mitigations

**Risk 1: RL instability**
- Mitigation: Conservative learning rate (α=0.1), experience replay buffer

**Risk 2: Statistical errors**
- Mitigation: Use scipy.stats for calculations, validate with known distributions

**Risk 3: Policy drift**
- Mitigation: Rate limits on adjustments, manual approval for large changes

**Risk 4: Experiment bias**
- Mitigation: Stratified random assignment, covariate adjustment

## Dependencies

```python
# Required
duckdb >= 0.9.0
pydantic >= 2.0
numpy >= 1.24.0

# Optional (for advanced statistics)
scipy >= 1.10.0  # Statistical tests
statsmodels >= 0.14.0  # Advanced statistics

# Optional (for visualization)
matplotlib >= 3.7.0
plotly >= 5.14.0
```

## Next Steps

1. Create directory structure
2. Implement database schema extensions
3. Build policy adjustment engine
4. Implement reinforcement learning
5. Build bandit algorithms
6. Implement A/B testing framework
7. Add metrics and statistics
8. Integrate with SONARouter
9. Add MCP tools
10. Write comprehensive tests
11. Document usage examples

---

**Estimated Timeline**: 3-4 days for full implementation

**Status**: Planning complete, ready to implement
