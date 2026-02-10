# ORB Learning Feedback Loops - Architecture Analysis

**Status**: Architecture Complete - Ready for Implementation
**Created**: 2026-02-09
**Type**: Architecture Enhancement

---

## Executive Summary

The ORB ecosystem has **excellent foundational infrastructure** for learning feedback loops. After comprehensive exploration, I've identified that **80% of the required infrastructure already exists** - we primarily need to integrate and extend existing systems rather than build from scratch.

### Key Findings

**Existing Strengths:**
- ✅ SONA router already learns (89% accuracy, EWC++ continual learning)
- ✅ Swarm intelligence has epsilon-greedy exploration (Honeybee consensus)
- ✅ All components track performance metrics
- ✅ Message bus provides event streaming infrastructure
- ✅ HotStore offers persistent semantic search (DuckDB + vectors)
- ✅ Quality components capture detailed outcomes

**Critical Gaps:**
- ❌ No centralized learning database
- ❌ No feedback capture mechanism
- ❌ No pattern extraction from session data
- ❌ No adaptive quality thresholds
- ❌ No cross-component learning integration

### Strategic Recommendation

**Leverage existing infrastructure** instead of building new systems:
1. Extend HotStore for learning database (semantic + persistent)
2. Build on SONA router's learning capabilities
3. Add feedback capture to all MCP tools
4. Extract patterns from Session-Buddy data
5. Implement adaptive quality in Crackerjack

**Estimated Timeline**: 8 weeks for full 4-layer system
**Quick Wins**: 5 days for basic execution intelligence

---

## Component Analysis

### 1. Mahavishnu: Routing & Coordination

#### Model Router (`mahavishnu/core/model_router.py`)

**Existing Capabilities:**
```python
class ModelRouterStats:
    total_routes: int
    tier_distribution: dict[ModelTier, int]
    total_cost_savings_usd: float
    avg_cost_savings_percent: float
    routes_by_confidence: dict[str, int]
    recent_routes: list[ModelRouting]  # Last 100
```

**Learning Enhancements Needed:**
```python
class LearningRouterStats(ModelRouterStats):
    # Track actual vs predicted performance
    outcome_tracking: dict[str, list[TaskOutcome]]

    # Per-tier performance history
    tier_performance_history: dict[ModelTier, PerformanceHistory]

    # Auto-tuning suggestions
    auto_tuning_suggestions: list[TuningRecommendation]

    # Cost prediction accuracy
    prediction_accuracy: dict[ModelTier, float]
```

**Integration Points:**
- Add telemetry hooks in `route_task()` method
- Capture execution outcomes via callback
- Compare predicted vs. actual performance
- Store in learning database

#### SONA Router (`mahavishnu/core/learning_router.py`, 542 lines)

**Existing Learning Infrastructure:**
```python
class SONARouter:
    neural_network: SimpleNeuralNetwork  # Already learning!
    ewc: EWCConfig  # Elastic Weight Consolidation (anti-forgetting)
    session_buddy: SessionBuddyConfig  # Historical context
    learning_rate: float  # Adaptive learning

    # 89% routing accuracy
```

**Key Insight**: SONA **already has continual learning**! We can extend it for multi-objective optimization (cost + quality + speed).

**Enhancement Strategy:**
- Add feedback signals from Crickerjack quality results
- Incorporate user acceptance/rejection signals
- Multi-arm bandit for exploration vs. exploitation
- Extend scope beyond adapter routing to pool/swarm selection

#### Pool Management (`mahavishnu/pools/`)

**Existing Metrics:**
```python
class PoolMetrics:
    pool_id: str
    status: PoolStatus
    active_workers: int
    total_workers: int
    tasks_completed: int
    tasks_failed: int
    avg_task_duration: float
    memory_usage_mb: float
```

**Pool Selection Strategies:**
- `ROUND_ROBIN`: Distribute evenly
- `LEAST_LOADED`: O(log n) heap-based routing
- `RANDOM`: Random selection
- `AFFINITY`: Route to same pool for related tasks

**Learning Enhancements:**
- Track per-pool performance over time
- Use learned performance scores for routing
- Add "LEARNED" strategy (model-based selection)
- Message bus event stream for real-time learning

#### Swarm Coordination (`mahavishnu/core/swarm_coordinator.py`, 1100 lines)

**Existing Learning Features:**

**HoneybeeConsensus** (Multi-Armed Bandit):
```python
class HoneybeeConsensus:
    epsilon: float = 0.1  # Exploration rate
    quality_scores: dict[str, float]  # Agent performance

    def select_agent(self) -> str:
        # Epsilon-greedy: explore vs. exploit
        if random() < self.epsilon:
            return random.choice(agents)  # Explore
        else:
            return max(quality_scores)  # Exploit
```

**AdaptiveQueen** (Performance Tracking):
```python
class AdaptiveQueen(Queen):
    performance_history: list[SwarmResult]  # Last 100 tasks

    def learn_from_results(self, results: list[SwarmResult]):
        # Update strategy based on outcomes
        pass
```

**HiveMind Memory**:
```python
class HiveMind:
    queen_memory: dict[str, list[SwarmResult]]  # Per-queen history
    active_swarms: dict[str, list[Any]]
```

**Learning Enhancements:**
- Extend HoneybeeConsensus with contextual bandits
- Centralize queen memory in learning database
- Add Thompson sampling for better exploration
- Track topology/protocol effectiveness over time

---

### 2. Session-Buddy: Memory & Knowledge

#### Quality Engine (`session_buddy/quality_engine.py`)

**Existing Capabilities:**
```python
def should_suggest_compact() -> (bool, str):
    """Heuristic analysis for context compaction."""

def _analyze_context_compaction() -> list[str]:
    """Generate recommendations."""

def _store_context_summary(conversation_summary):
    """Persist to memory."""
```

**Learning Enhancements:**
- Analyze successful sessions for reusable patterns
- Extract solution templates from session summaries
- Build quality trend analysis per project
- Generate context recommendations

#### Advanced Search (`session_buddy/advanced_search.py`)

**Existing Capabilities:**
- Semantic search with multiple strategies
- Context optimization
- Memory compaction
- Knowledge persistence

**Learning Enhancements:**
- Pattern extraction from search queries
- Solution library indexing
- Cross-session pattern detection
- Automatic insight generation

#### Code Graph Integration (`mahavishnu/session_buddy/integration.py`)

**Existing Capabilities:**
```python
class CodeGraphAnalyzer:
    def index_code_graph(repo_path: str)
    def get_function_context(function_name: str)
    def find_related_code(symbol: str)
    def index_documentation(repo_path: str)
```

**Learning Enhancements:**
- Structural pattern extraction (common code patterns)
- Documentation-based solution library
- Cross-project code pattern detection
- API usage pattern analysis

---

### 3. Akosha: Analytics & Patterns

#### OTel Ingester (`mahavishnu/ingesters/otel_ingester.py`)

**Existing Capabilities:**
```python
class OtelIngester:
    # DuckDB-based vector storage (zero dependencies!)
    def ingest_trace(trace_data)
    def ingest_batch(traces)
    def search_traces(query, limit, threshold)  # Semantic search!
    def get_trace_by_id(trace_id)
```

**Key Features:**
- DuckDB storage (no Docker/PostgreSQL)
- Semantic embeddings (384-dim via sentence-transformers)
- HNSW vector index for fast similarity search
- System ID tracking (per-model analytics)
- Embedding cache (1000 entries FIFO)

**Learning Enhancements:**
- Extend to execution records (not just traces)
- Build solution library on top of HotStore
- Pattern similarity search
- Performance prediction from embeddings

---

### 4. Crackerjack: Quality Control

#### Quality API (`crackerjack/api.py`)

**Existing Capabilities:**
```python
class QualityCheckResult:
    success: bool
    fast_hooks_passed: bool
    comprehensive_hooks_passed: bool
    errors: list[str]
    warnings: list[str]
    duration: float

class TestResult:
    success: bool
    passed_count: int
    failed_count: int
    coverage_percentage: float
```

**Learning Enhancements:**
- Track failure rates per check type
- Project maturity assessment algorithm
- Dynamic threshold adjustment
- Streamlined workflows for stable projects

---

### 5. Message Bus & Events

#### Message Bus (`mahavishnu/mcp/protocols/message_bus.py`)

**Existing Event Types:**
```python
class MessageType(Enum):
    TASK_DELEGATE = "task_delegate"
    RESULT_SHARE = "result_share"
    STATUS_UPDATE = "status_update"
    HEARTBEAT = "heartbeat"
    POOL_CREATED = "pool_created"
    POOL_CLOSED = "pool_closed"
    TASK_COMPLETED = "task_completed"
```

**Learning Events to Add:**
```python
FEEDBACK_SUBMITTED = "feedback_submitted"
PATTERN_EXTRACTED = "pattern_extracted"
QUALITY_THRESHOLD_ADJUSTED = "quality_threshold_adjusted"
ROUTING_TUNED = "routing_tuned"
```

**Stats Tracking:**
```python
{
    "pools_with_queues": int,
    "queue_sizes": dict[pool_id, size],
    "subscriber_counts": dict[msg_type, count],
    "max_queue_size": int
}
```

**Learning Integration:**
- Subscribe to TASK_COMPLETED for outcome capture
- Publish new learning events for system-wide awareness
- Event-driven updates to learning database

---

## Data Storage Strategy

### Current Storage

| Component | Storage Type | Use Case |
|-----------|-------------|----------|
| Session-Buddy | SQLite | Sessions, reflections |
| Akosha | DuckDB | OTel traces with embeddings |
| Mahavishnu | In-memory | Router stats, pool metrics |
| Crackerjack | Files | Test results, reports |

### Learning Database Schema

**Recommended: Extend HotStore (DuckDB) for learning data**

```sql
-- Execution records
CREATE TABLE executions (
    task_id UUID PRIMARY KEY,
    timestamp TIMESTAMP,
    task_type VARCHAR,
    repo VARCHAR,
    model_tier VARCHAR,
    pool_type VARCHAR,
    swarm_topology VARCHAR,
    success BOOLEAN,
    duration_seconds FLOAT,
    cost_estimate FLOAT,
    actual_cost FLOAT,
    quality_score INT,
    embedding FLOAT[384]  -- Semantic embedding
);

-- Solution patterns
CREATE TABLE solutions (
    pattern_id UUID PRIMARY KEY,
    extracted_at TIMESTAMP,
    task_context VARCHAR,
    solution_summary VARCHAR,
    success_rate FLOAT,
    usage_count INT,
    repos_used_in VARCHAR[],
    embedding FLOAT[384]
);

-- Feedback (opt-in attribution)
CREATE TABLE feedback (
    feedback_id UUID PRIMARY KEY,
    task_id UUID REFERENCES executions(task_id),
    timestamp TIMESTAMP,
    feedback_type VARCHAR,
    rating INT,
    comment VARCHAR,
    user_id UUID  -- NULL = anonymous
);

-- Quality policies (adaptive)
CREATE TABLE quality_policies (
    policy_id UUID PRIMARY KEY,
    repo VARCHAR,
    project_maturity VARCHAR,  -- new/stable/mature
    coverage_threshold FLOAT,
    strictness_level VARCHAR,
    last_adjusted TIMESTAMP,
    adjustment_reason VARCHAR
);
```

**Benefits:**
- ✅ Zero dependencies (DuckDB embedded)
- ✅ Semantic search via HNSW index
- ✅ Persistent storage
- ✅ SQL query interface
- ✅ Vector similarity search

---

## Extension Points

### MCP Tool Enhancement Pattern

**Before:**
```python
@mcp.tool()
async def pool_execute(
    pool_id: str,
    prompt: str,
    timeout: int = 300
) -> dict[str, Any]:
    result = await pool_manager.execute_on_pool(pool_id, task)
    return result
```

**After:**
```python
from typing import Optional

FeedbackRating = Literal["thumbs_up", "thumbs_down", "neutral"]

@mcp.tool()
async def pool_execute(
    pool_id: str,
    prompt: str,
    timeout: int = 300,
    feedback: Optional[dict] = None  # NEW
) -> dict[str, Any]:
    result = await pool_manager.execute_on_pool(pool_id, task)

    # Capture feedback if provided
    if feedback:
        await learning_system.record_feedback(
            task_id=result["task_id"],
            feedback=feedback,
            user_id=None  # Anonymous unless provided
        )

    return {
        **result,
        "task_id": result["task_id"],  # For feedback correlation
        "feedback_captured": feedback is not None
    }
```

### CLI Feedback Commands

**Add to `mahavishnu/cli.py`:**
```python
@app.command()
def feedback(
    task_id: str,
    rating: int = typer.Option(..., min=1, max=5),
    comment: str = typer.Option("", "--comment", "-c"),
    anonymous: bool = typer.Option(True, "--anonymous/--attributed")
):
    """Submit feedback for a completed task."""
    learning_system.submit_feedback(
        task_id=task_id,
        rating=rating,
        comment=comment,
        anonymous=anonymous
    )
```

---

## Implementation Roadmap

### Phase 1: Execution Intelligence (Weeks 1-2)

**Leverage Existing:**
- `ModelRouterStats` → Add outcome tracking
- `PoolMetrics` → Add performance history
- `HiveMind` memory → Centralize in learning database
- Message bus → Subscribe to TASK_COMPLETED events

**Build New:**
- Extend HotStore schema for execution records
- Add telemetry hooks to adapters
- Build auto-tuning for router thresholds

**Deliverables:**
1. Execution telemetry capture
2. Historical performance database
3. Auto-tuning for model router
4. Pool selection optimization

**Files to Modify:**
- `mahavishnu/core/model_router.py` - Add outcome tracking
- `mahavishnu/pools/manager.py` - Add performance history
- `mahavishnu/mcp/tools/pool_tools.py` - Add telemetry hooks
- `mahavishnu/ingesters/otel_ingester.py` - Extend schema

**Files to Create:**
- `mahavishnu/learning/execution/__init__.py` - Execution intelligence module
- `mahavishnu/learning/execution/telemetry.py` - Telemetry capture
- `mahavishnu/learning/execution/auto_tuner.py` - Auto-tuning engine
- `mahavishnu/learning/database.py` - Learning database interface

---

### Phase 2: Knowledge Synthesis (Weeks 3-4)

**Leverage Existing:**
- Session-Buddy's `quality_engine.py` → Pattern extraction
- OTel ingester → Semantic search for solutions
- Code graph analysis → Structural patterns

**Build New:**
- Pattern extraction algorithms
- Solution library API
- MCP tools for solution recommendations

**Deliverables:**
1. Pattern extraction from session data
2. Solution library with semantic search
3. Cross-project pattern detection
4. Automatic insight generation

**Files to Modify:**
- `session_buddy/quality_engine.py` - Add pattern extraction
- `mahavishnu/session_buddy/integration.py` - Add solution indexing
- `mahavishnu/ingesters/otel_ingester.py` - Add solution search

**Files to Create:**
- `mahavishnu/learning/knowledge/__init__.py` - Knowledge synthesis module
- `mahavishnu/learning/knowledge/pattern_extractor.py` - Pattern extraction
- `mahavishnu/learning/knowledge/solution_library.py` - Solution library
- `mahavishnu/mcp/tools/solution_tools.py` - Solution recommendation tools

---

### Phase 3: Adaptive Quality (Weeks 5-6)

**Leverage Existing:**
- Crackerjack's `QualityCheckResult` → Failure tracking
- Test results → Project maturity scoring
- Hook performance → Threshold optimization

**Build New:**
- Maturity assessment algorithm
- Dynamic threshold adjustment
- Risk-based coverage requirements

**Deliverables:**
1. Project maturity assessment
2. Dynamic quality thresholds
3. Risk-based test coverage requirements
4. Streamlined workflows for stable projects

**Files to Modify:**
- `crackerjack/api.py` - Add adaptive quality logic
- `mahavishnu/core/production_validation.py` - Maturity tracking

**Files to Create:**
- `mahavishnu/learning/quality/__init__.py` - Adaptive quality module
- `mahavishnu/learning/quality/maturity_assessor.py` - Maturity assessment
- `mahavishnu/learning/quality/adaptive_thresholds.py` - Dynamic thresholds

---

### Phase 4: Feedback Integration (Weeks 7-8)

**Leverage Existing:**
- MCP tool infrastructure → Add feedback params
- Message bus → Feedback events
- HotStore → Feedback persistence

**Build New:**
- Feedback capture UI/CLI hooks
- Feedback aggregation and weighting
- Policy adjustment engine
- A/B testing framework

**Deliverables:**
1. Feedback capture UI/CLI hooks
2. Feedback aggregation and weighting
3. Policy adjustment engine
4. A/B testing framework for improvements

**Files to Modify:**
- `mahavishnu/cli.py` - Add feedback commands
- `mahavishnu/mcp/tools/*.py` - Add feedback parameters to all tools
- `mahavishnu/mcp/protocols/message_bus.py` - Add feedback events

**Files to Create:**
- `mahavishnu/learning/feedback/__init__.py` - Feedback integration module
- `mahavishnu/learning/feedback/capture.py` - Feedback capture
- `mahavishnu/learning/feedback/aggregation.py` - Feedback weighting
- `mahavishnu/learning/feedback/policy_engine.py` - Reinforcement learning

---

## Quick Wins (First Week)

### Day 1: Extend Router Stats
```python
# mahavishnu/core/model_router.py
class LearningRouterStats(ModelRouterStats):
    outcome_tracking: dict[str, list[TaskOutcome]] = field(default_factory=dict)
    prediction_accuracy: dict[ModelTier, float] = field(default_factory=dict)
```

### Day 2: Subscribe to Message Bus
```python
# mahavishnu/learning/execution/telemetry.py
async def capture_task_completed(message: dict):
    """Subscribe to TASK_COMPLETED events."""
    execution = ExecutionRecord.from_message(message)
    await learning_db.store_execution(execution)
```

### Day 3: Add Feedback Parameter
```python
# mahavishnu/mcp/tools/pool_tools.py
@mcp.tool()
async def pool_execute(
    pool_id: str,
    prompt: str,
    feedback: Optional[dict] = None  # NEW
) -> dict:
    # ... existing logic ...
    if feedback:
        await learning_system.record_feedback(...)
```

### Day 4-5: Store Executions in HotStore
```python
# mahavishnu/learning/database.py
class LearningDatabase:
    def __init__(self, otel_ingester: OtelIngester):
        self.ingester = otel_ingester

    async def store_execution(self, execution: ExecutionRecord):
        """Extend HotStore schema for executions."""
        await self.ingester.ingest_execution(execution)
```

---

## Privacy & Security

### Feedback Attribution

**Opt-in Model:**
```python
{
    "feedback_id": "uuid",
    "task_id": "uuid",
    "rating": 5,
    "comment": "Perfect model choice",
    "user_id": null,  # NULL = anonymous (default)
    "timestamp": "2026-02-09T10:35:00Z"
}
```

**User Choice:**
```bash
# Anonymous by default
mahavishnu feedback --task-id abc123 --rating 5

# Attributed (opt-in)
mahavishnu feedback --task-id abc123 --rating 5 --attributed
```

### Data Isolation

**Per-Project Learning:**
```sql
CREATE TABLE executions (
    ...
    repo VARCHAR,  -- Isolate by repository
    ...
);

-- Query patterns
SELECT * FROM executions
WHERE repo = 'mahavishnu'
  AND task_type = 'refactor';
```

**Cross-Project Learning (Opt-in):**
```yaml
# settings/mahavishnu.yaml
learning:
  cross_project_learning: false  # Default: isolated
  anonymous_aggregation: true    # Aggregate patterns only
```

---

## Success Metrics

### Layer 1: Execution Intelligence
- **Metric**: Cost prediction accuracy improvement
- **Target**: ±10% → ±5% (50% improvement)
- **Measurement**: Compare predicted vs. actual cost over time

### Layer 2: Knowledge Synthesis
- **Metric**: Solution reuse rate
- **Target**: 0% → 30% of tasks use suggested solutions
- **Measurement**: Track pattern application frequency

### Layer 3: Adaptive Quality
- **Metric**: Quality gate efficiency
- **Target**: Reduce check time by 20% for stable projects
- **Measurement**: Compare duration before/after adaptive thresholds

### Layer 4: Feedback Integration
- **Metric**: Feedback capture rate
- **Target**: 50% of tasks include feedback
- **Measurement**: Feedback submissions / total tasks

---

## Open Questions

1. **Data Retention**: What's the minimum retention period for learning?
   - **Recommendation**: 90 days for execution records, 1 year for patterns

2. **Opt-in vs. Opt-out**: Should learning be opt-in or opt-out?
   - **Recommendation**: Opt-in for cross-project learning, opt-out for single-project

3. **Conflicting Feedback**: How to handle disagreements between users?
   - **Recommendation**: Weight by user trust score, aggregate by expertise

4. **Pattern Isolation**: Share patterns across all repos or keep isolated?
   - **Recommendation**: Default isolated, opt-in for sharing with anonymization

---

## Next Steps

1. ✅ **Architecture analysis complete** - Ready for implementation
2. **Present to Backend Architect** - Review data structures and storage
3. **Present to UX Designer** - Review feedback capture mechanisms
4. **Create detailed implementation plan** - Break down Phase 1 into tasks
5. **Set up learning database** - Extend HotStore schema
6. **Begin Phase 1 implementation** - Execution intelligence

---

**Status**: Ready for Implementation
**Confidence**: High (80% of infrastructure exists)
**Estimated Timeline**: 8 weeks for full 4-layer system
