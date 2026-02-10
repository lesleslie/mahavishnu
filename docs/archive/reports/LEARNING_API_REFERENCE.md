# Learning Feedback System - API Reference

Complete API documentation for the learning feedback system components.

## Table of Contents

- [LearningDatabase](#learningdatabase)
- [TelemetryCapture](#telemetrycapture)
- [FeedbackCapturer](#feedbackcapturer)
- [SONARouter](#sonarouter)
- [MCP Tools](#mcp-tools)
- [CLI Commands](#cli-commands)
- [Data Models](#data-models)

---

## LearningDatabase

Dedicated DuckDB-based database for storing and querying execution analytics.

**Location:** `mahavishnu/learning/database.py`

### Constructor

```python
def __init__(
    database_path: str = "data/learning.db",
    embedding_model: str = "all-MiniLM-L6-v2",
    pool_size: int = 4,
)
```

**Parameters:**
- `database_path` - Path to DuckDB database file (default: "data/learning.db")
- `embedding_model` - Sentence transformer model name (default: "all-MiniLM-L6-v2")
- `pool_size` - Connection pool size (default: 4)

**Raises:**
- `ImportError` - If sentence-transformers not installed

**Example:**
```python
from mahavishnu.learning.database import LearningDatabase

db = LearningDatabase(
    database_path="data/learning.db",
    embedding_model="all-MiniLM-L6-v2",
    pool_size=4,
)
await db.initialize()
```

### Methods

#### `initialize()`

Initialize database schema and connection pool.

```python
async def initialize() -> None
```

**Creates:**
- `executions` table
- Composite indexes
- Materialized views (tier_performance, pool_performance, solution_patterns)
- Loads embedding model

**Raises:**
- `RuntimeError` - If initialization fails

**Example:**
```python
await db.initialize()
```

#### `store_execution()`

Store execution record with semantic embedding.

```python
async def store_execution(
    execution: ExecutionRecord
) -> None
```

**Parameters:**
- `execution` - ExecutionRecord to store

**Side Effects:**
- Generates semantic embedding from task description
- Inserts record into database
- Logs task ID on success

**Raises:**
- `RuntimeError` - If database not initialized

**Example:**
```python
from mahavishnu.learning.models import ExecutionRecord
from datetime import UTC, datetime
from uuid import uuid4

record = ExecutionRecord(
    task_id=uuid4(),
    timestamp=datetime.now(UTC),
    task_type="refactor",
    task_description="Optimize database queries",
    repo="my-repo",
    file_count=5,
    estimated_tokens=5000,
    model_tier="medium",
    pool_type="mahavishnu",
    routing_confidence=0.85,
    complexity_score=60,
    success=True,
    duration_seconds=45.2,
    quality_score=85,
    cost_estimate=0.003,
    actual_cost=0.0028,
)

await db.store_execution(record)
```

#### `find_similar_executions()`

Find semantically similar past executions.

```python
async def find_similar_executions(
    task_description: str,
    repo: str | None = None,
    limit: int = 10,
    days_back: int = 90,
    threshold: float = 0.7,
) -> list[dict[str, Any]]
```

**Parameters:**
- `task_description` - Query description
- `repo` - Optional repository filter
- `limit` - Maximum results to return (default: 10)
- `days_back` - Search window in days (default: 90)
- `threshold` - Minimum similarity score 0.0-1.0 (default: 0.7)

**Returns:**
```python
[
    {
        "task_id": "abc-123",
        "timestamp": "2025-02-09T10:30:00Z",
        "task_type": "refactor",
        "repo": "my-repo",
        "model_tier": "medium",
        "pool_type": "mahavishnu",
        "success": True,
        "duration_seconds": 45.2,
        "quality_score": 85,
        "task_description": "Optimize database queries",
        "solution_summary": "Added composite index",
        "similarity": 0.92,
    },
    ...
]
```

**Raises:**
- `RuntimeError` - If database not initialized

**Example:**
```python
similar = await db.find_similar_executions(
    task_description="Improve query performance",
    repo="my-repo",
    limit=5,
    threshold=0.8,
)

for execution in similar:
    print(f"{execution['task_type']}: {execution['similarity']:.2f}")
```

#### `get_tier_performance()`

Get tier performance metrics from materialized view.

```python
async def get_tier_performance(
    repo: str | None = None,
    days_back: int = 30,
) -> list[dict[str, Any]]
```

**Parameters:**
- `repo` - Optional repository filter
- `days_back` - Time window in days (default: 30)

**Returns:**
```python
[
    {
        "repo": "my-repo",
        "model_tier": "medium",
        "task_type": "refactor",
        "date": "2025-02-09",
        "total_executions": 150,
        "successful_count": 142,
        "avg_duration": 45.2,
        "avg_cost": 0.003,
        "avg_quality": 85.5,
        "p95_duration": 78.3,
    },
    ...
]
```

**Raises:**
- `RuntimeError` - If database not initialized

**Example:**
```python
performance = await db.get_tier_performance(
    repo="my-repo",
    days_back=7,
)

for tier in performance:
    print(f"{tier['model_tier']}: {tier['avg_quality']:.1f} quality")
```

#### `get_pool_performance()`

Get pool performance metrics from materialized view.

```python
async def get_pool_performance(
    repo: str | None = None,
    days_back: int = 7,
) -> list[dict[str, Any]]
```

**Parameters:**
- `repo` - Optional repository filter
- `days_back` - Time window in days (default: 7)

**Returns:**
```python
[
    {
        "pool_type": "mahavishnu",
        "repo": "my-repo",
        "hour": "2025-02-09T10:00:00Z",
        "total_tasks": 25,
        "successful_tasks": 24,
        "avg_duration": 42.1,
        "avg_cost": 0.0028,
        "success_rate": 0.96,
    },
    ...
]
```

**Raises:**
- `RuntimeError` - If database not initialized

**Example:**
```python
pools = await db.get_pool_performance(days_back=1)

for pool in pools:
    print(f"{pool['pool_type']}: {pool['success_rate']:.1%} success")
```

#### `get_solution_patterns()`

Get top solution patterns by success rate.

```python
async def get_solution_patterns(
    repo: str | None = None,
    min_usage: int = 5,
    limit: int = 10,
) -> list[dict[str, Any]]
```

**Parameters:**
- `repo` - Optional repository filter
- `min_usage` - Minimum usage count (default: 5)
- `limit` - Maximum results to return (default: 10)

**Returns:**
```python
[
    {
        "solution_summary": "Added composite index on user_id",
        "repo": "my-repo",
        "task_types": ["refactor", "optimization"],
        "usage_count": 15,
        "success_count": 14,
        "avg_quality": 88.5,
        "first_seen": "2025-01-15T10:00:00Z",
        "last_seen": "2025-02-09T15:30:00Z",
        "success_rate": 0.933,
    },
    ...
]
```

**Raises:**
- `RuntimeError` - If database not initialized

**Example:**
```python
patterns = await db.get_solution_patterns(
    repo="my-repo",
    min_usage=10,
    limit=5,
)

for pattern in patterns:
    print(f"{pattern['solution_summary']}: {pattern['success_rate']:.1%}")
```

#### `close()`

Close database connection pool.

```python
async def close() -> None
```

**Example:**
```python
await db.close()
```

#### Async Context Manager

```python
async def __aenter__(self) -> "LearningDatabase"
async def __aexit__(self, exc_type, exc_val, exc_tb) -> None
```

**Example:**
```python
async with LearningDatabase("data/learning.db") as db:
    await db.initialize()
    await db.store_execution(record)
    # Automatically closed on exit
```

---

## TelemetryCapture

Capture telemetry from model router and pool manager.

**Location:** `mahavishnu/learning/execution/telemetry.py`

### Constructor

```python
def __init__(
    message_bus: MessageBus,
    batch_size: int = 100,
    batch_timeout: float = 5.0,
)
```

**Parameters:**
- `message_bus` - Message bus for event publishing
- `batch_size` - Batch size for aggregation (default: 100)
- `batch_timeout` - Batch timeout in seconds (default: 5.0)

**Example:**
```python
from mahavishnu.learning.execution.telemetry import TelemetryCapture
from mahavishnu.mcp.protocols.message_bus import MessageBus

telemetry = TelemetryCapture(
    message_bus=MessageBus(),
    batch_size=100,
    batch_timeout=5.0,
)
```

### Methods

#### `initialize()`

Initialize telemetry capture and subscribe to events.

```python
async def initialize() -> None
```

**Subscribes to:**
- `MessageType.TASK_COMPLETED` events

**Example:**
```python
await telemetry.initialize()
```

#### `capture_routing_decision()`

Capture model routing decision.

```python
async def capture_routing_decision(
    data: dict[str, Any],
) -> None
```

**Parameters:**
```python
{
    "task_id": str,              # Unique task identifier
    "routing": ModelRouting,      # Routing decision object
    "timestamp": datetime,        # Routing timestamp
    "task_data": {                # Optional task specification
        "type": str,
        "description": str,
        "repo": str,
        "files": list[str],
        "estimated_tokens": int,
        ...
    },
}
```

**Side Effects:**
- Stores routing decision
- Publishes `routing_decision` event to message bus

**Example:**
```python
await telemetry.capture_routing_decision({
    "task_id": "task-abc-123",
    "routing": routing_decision,
    "timestamp": datetime.now(UTC),
    "task_data": {
        "type": "refactor",
        "description": "Optimize queries",
        "repo": "my-repo",
        "files": ["models.py"],
        "estimated_tokens": 5000,
    },
})
```

#### `capture_execution_outcome()`

Capture task execution outcome.

```python
async def capture_execution_outcome(
    data: dict[str, Any],
) -> None
```

**Parameters:**
```python
{
    "task_id": str,               # Unique task identifier
    "success": bool,              # Execution success status
    "duration_seconds": float,    # Execution duration
    "quality_score": int | None,  # Quality gate score (optional)
    "error_type": ErrorType | None,  # Error type if failed (optional)
    "error_message": str | None,  # Error message if failed (optional)
    "actual_cost": float | None,  # Actual execution cost (optional)
    "pool_id": str | None,        # Pool that executed task (optional)
}
```

**Side Effects:**
- Stores execution outcome
- If routing decision exists, publishes complete `execution_record` event
- Cleans up stored routing decision

**Example:**
```python
await telemetry.capture_execution_outcome({
    "task_id": "task-abc-123",
    "success": True,
    "duration_seconds": 45.2,
    "quality_score": 85,
    "actual_cost": 0.003,
    "pool_id": "pool-local",
})
```

#### `get_routing_decisions_count()`

Get count of stored routing decisions.

```python
def get_routing_decisions_count() -> int
```

**Returns:**
- Number of routing decisions awaiting execution outcomes

**Example:**
```python
count = telemetry.get_routing_decisions_count()
print(f"Pending routing decisions: {count}")
```

#### `get_execution_outcomes_count()`

Get count of stored execution outcomes.

```python
def get_execution_outcomes_count() -> int
```

**Returns:**
- Number of execution outcomes awaiting routing decisions

**Example:**
```python
count = telemetry.get_execution_outcomes_count()
print(f"Pending execution outcomes: {count}")
```

#### `shutdown()`

Shutdown telemetry capture and cleanup resources.

```python
async def shutdown() -> None
```

**Example:**
```python
await telemetry.shutdown()
```

---

## FeedbackCapturer

Smart feedback capture with contextual prompts.

**Location:** `mahavishnu/learning/feedback/capture.py`

### Constructor

```python
def __init__(
    enable_prompts: bool = True,
    privacy_notice_path: Optional[Path] = None,
)
```

**Parameters:**
- `enable_prompts` - Whether to enable interactive prompts (default: True)
- `privacy_notice_path` - Path to store privacy notice flag (default: ~/.mahavishnu/privacy-notice-viewed)

**Example:**
```python
from mahavishnu.learning.feedback.capture import FeedbackCapturer

capturer = FeedbackCapturer(
    enable_prompts=True,
)
```

### Methods

#### `should_prompt_for_feedback()`

Determine if we should prompt for feedback.

```python
def should_prompt_for_feedback(
    context: FeedbackPromptContext
) -> bool
```

**Parameters:**
- `context` - Task execution context

**Returns:**
- `True` if feedback prompt is appropriate

**Smart Prompting Rules:**
- DON'T prompt if task < 10 seconds (trivial)
- DON'T prompt if user rated 5+ tasks in last hour (fatigue)
- DON'T prompt in non-interactive terminals (CI/CD)
- DO prompt if task > 2 minutes (significant effort)
- DO prompt if model was auto-selected (routing decision)
- DO prompt if task failed (learning opportunity)
- DO prompt if swarm was used (complex orchestration)

**Example:**
```python
from mahavishnu.learning.feedback.models import FeedbackPromptContext
from uuid import uuid4

context = FeedbackPromptContext(
    task_id=uuid4(),
    task_type="refactor",
    model_tier="medium",
    pool_type="mahavishnu",
    task_duration_seconds=150.0,  # 2.5 minutes
    task_succeeded=True,
    auto_selected_model=True,
)

if capturer.should_prompt_for_feedback(context):
    feedback = capturer.prompt_for_feedback(context)
```

#### `prompt_for_feedback()`

Prompt user for contextual feedback.

```python
def prompt_for_feedback(
    context: FeedbackPromptContext,
) -> Optional[FeedbackRecord]
```

**Parameters:**
- `context` - Task execution context

**Returns:**
- `FeedbackRecord` if user provided feedback
- `None` if user skipped

**Prompts:**
1. "Was the model choice appropriate? [Y/n]"
2. "Was the execution speed acceptable? [Y/n]"
3. "Did the output meet your expectations? [Y/n]"
4. "What went wrong?" (if fair/poor)
5. "Any additional context?" (optional)
6. "Who should see this feedback?" (private/team/public)

**Example:**
```python
feedback = capturer.prompt_for_feedback(context)

if feedback:
    print(f"Satisfaction: {feedback.satisfaction}")
    print(f"Issue type: {feedback.issue_type}")
    print(f"Visibility: {feedback.visibility}")
```

#### `is_interactive_terminal()` (static)

Detect if running in an interactive terminal.

```python
@staticmethod
def is_interactive_terminal() -> bool
```

**Returns:**
- `True` if terminal is interactive (not CI/CD)

**Checks:**
- stdin is a TTY
- CI environment variables (CI, GITHUB_ACTIONS, etc.)

**Example:**
```python
if FeedbackCapturer.is_interactive_terminal():
    print("Running in interactive mode")
```

---

## SONARouter

Self-Optimizing Neural Architecture router for intelligent adapter routing.

**Location:** `mahavishnu/core/learning_router.py`

### Constructor

```python
def __init__(
    config: Optional[SONAConfig] = None,
    settings: Optional["MahavishnuSettings"] = None,
)
```

**Parameters:**
- `config` - Router configuration (default: SONAConfig())
- `settings` - Mahavishnu settings (default: MahavishnuSettings())

**Example:**
```python
from mahavishnu.core.learning_router import SONARouter, SONAConfig

router = SONARouter(
    config=SONAConfig(
        learning_rate=0.001,
        update_frequency=100,
    ),
)
```

### Methods

#### `route_task()`

Route task to best adapter using neural network.

```python
async def route_task(
    task: dict
) -> RouteDecision
```

**Parameters:**
```python
{
    "description": str,  # Task description
    "files": list[str],  # Files affected
    "estimated_tokens": int,  # Token estimate
    "scheduled": bool,  # Is scheduled task
    ...
}
```

**Returns:**
```python
RouteDecision(
    adapter_id=AdapterType.LLAMAINDEX,
    confidence=0.85,
    reason="Selected llamaindex - task requires RAG, neural confidence: 0.85",
    neural_score=0.85,
    expected_quality=0.78,
    learning_data={
        "features": {...},
        "all_scores": {...},
    },
)
```

**Example:**
```python
decision = await router.route_task({
    "description": "Build RAG pipeline for document search",
    "files": ["rag.py", "vector_store.py"],
    "estimated_tokens": 8000,
    "scheduled": True,
})

print(f"Selected: {decision.adapter_id}")
print(f"Confidence: {decision.confidence:.2f}")
print(f"Reason: {decision.reason}")
```

#### `learn_from_outcome()`

Learn from task execution outcome.

```python
async def learn_from_outcome(
    task_id: str,
    outcome: dict,
) -> None
```

**Parameters:**
```python
{
    "quality": float,  # Quality score 0-1
    "execution_time": float,  # Execution time in seconds
    "success": bool,  # Success status
    ...
}
```

**Side Effects:**
- Stores outcome in task history
- Updates EWC if needed (every update_frequency tasks)

**Example:**
```python
await router.learn_from_outcome(
    "task-abc-123",
    {
        "quality": 0.85,
        "execution_time": 45.2,
        "success": True,
    },
)
```

#### `get_statistics()`

Get router statistics.

```python
def get_statistics() -> dict[str, Any]
```

**Returns:**
```python
{
    "total_routes": 150,
    "adapter_distribution": {
        "llamaindex": 45,
        "agno": 38,
        "langgraph": 35,
        "prefect": 32,
    },
    "avg_confidence": 0.82,
    "accuracy_history": [0.75, 0.78, 0.82, 0.85, 0.89],
    "tasks_learned": 145,
}
```

**Example:**
```python
stats = router.get_statistics()
print(f"Total routes: {stats['total_routes']}")
print(f"Average confidence: {stats['avg_confidence']:.2f}")
print(f"Adapter distribution: {stats['adapter_distribution']}")
```

#### `save_model()`

Save model weights to disk.

```python
async def save_model(
    path: str | Path
) -> None
```

**Parameters:**
- `path` - Path to save model

**Saves:**
- Neural network weights and biases
- EWC Fisher matrices and optimal parameters
- Configuration
- Statistics

**Example:**
```python
await router.save_model("models/sona_router.json")
```

#### `load_model()`

Load model weights from disk.

```python
async def load_model(
    path: str | Path
) -> None
```

**Parameters:**
- `path` - Path to load model from

**Loads:**
- Neural network weights and biases
- EWC Fisher matrices and optimal parameters
- Configuration

**Example:**
```python
await router.load_model("models/sona_router.json")
```

---

## MCP Tools

Feedback tools available via MCP protocol.

**Location:** `mahavishnu/mcp/tools/feedback_tools.py`

### `submit_feedback`

Submit feedback for a completed task.

```python
@mcp.tool()
async def submit_feedback(
    task_id: str,
    satisfaction: Literal["excellent", "good", "fair", "poor"],
    issue_type: Optional[Literal["wrong_model", "too_slow", "poor_quality", "other"]] = None,
    comment: Optional[str] = None,
    visibility: Literal["private", "team", "public"] = "private",
) -> dict
```

**Parameters:**
- `task_id` - Task identifier
- `satisfaction` - Satisfaction level (excellent/good/fair/poor)
- `issue_type` - Issue type (required for fair/poor)
- `comment` - Additional context (optional, max 2000 chars)
- `visibility` - Privacy level (private/team/public, default: private)

**Returns:**
```python
{
    "feedback_id": "fb-abc-123",
    "status": "submitted",
    "message": "Thank you! Your feedback helps improve routing accuracy.",
    "impact": "This positive feedback reinforces current routing patterns.",
    "visibility": "private",
}
```

**Validation:**
- `issue_type` required for fair/poor ratings
- `comment` required when issue_type="other"

**Example:**
```python
result = await mcp.call_tool("submit_feedback", {
    "task_id": "abc-123",
    "satisfaction": "excellent",
    "visibility": "private",
})
```

### `feedback_help`

Get help with the feedback system.

```python
@mcp.tool()
async def feedback_help() -> dict
```

**Returns:**
```python
{
    "title": "ORB Learning Feedback System",
    "purpose": "Your feedback helps improve model selection accuracy, pool routing efficiency, and swarm coordination strategies.",
    "privacy": {
        "default": "private",
        "description": "Stored only on your machine, never shared",
        "levels": {
            "private": "Only you, stored locally",
            "team": "Your team, for learning (anonymized)",
            "public": "Global patterns, cannot identify you",
        },
    },
    "satisfaction_levels": {...},
    "issue_types": {...},
    "cli_commands": {...},
    "learn_more": "https://mahavishnu.dev/learning-privacy",
}
```

**Example:**
```python
help = await mcp.call_tool("feedback_help", {})
print(help["purpose"])
```

---

## CLI Commands

Feedback management via command line.

### `mahavishnu feedback submit`

Submit feedback for a completed task.

```bash
mahavishnu feedback submit \
  --task-id abc-123 \
  --satisfaction excellent \
  --visibility private
```

**Options:**
- `--task-id` - Task identifier (required)
- `--satisfaction` - Satisfaction level (excellent/good/fair/poor, required)
- `--issue-type` - Issue type (required for fair/poor)
- `--comment` - Additional context (optional)
- `--visibility` - Privacy level (private/team/public, default: private)

### `mahavishnu feedback --history`

View your feedback history.

```bash
mahavishnu feedback --history
```

**Output:**
```
╭──────────────────────────────────────────────────────╮
│ Feedback History                                    │
╞══════════════════════════════════════════════════════╡
│ abc-123 | excellent | 2025-02-09T10:30:00Z │ private │
│ def-456 | fair      | 2025-02-09T11:15:00Z │ team    │
╰──────────────────────────────────────────────────────╯
```

### `mahavishnu feedback --export`

Export your feedback data.

```bash
mahavishnu feedback --export feedback.json
```

**Export format:**
```json
[
  {
    "feedback_id": "fb-abc-123",
    "task_id": "abc-123",
    "satisfaction": "excellent",
    "timestamp": "2025-02-09T10:30:00Z",
    "visibility": "private"
  },
  ...
]
```

### `mahavishnu feedback --delete`

Delete specific feedback entry.

```bash
mahavishnu feedback --delete abc-123
```

### `mahavishnu feedback --clear-all`

Clear all feedback (with confirmation).

```bash
mahavishnu feedback --clear-all
```

**Prompts:**
```
⚠️  This will delete all feedback. Continue? [y/N]: y
✓ Cleared 25 feedback entries
```

---

## Data Models

### ExecutionRecord

Complete execution record for learning analytics.

```python
class ExecutionRecord(BaseModel):
    # Identification
    task_id: UUID
    timestamp: datetime

    # Task characteristics
    task_type: str
    task_description: str
    repo: str
    file_count: int
    estimated_tokens: int

    # Routing decisions
    model_tier: str
    pool_type: str
    swarm_topology: Optional[str]
    routing_confidence: float
    complexity_score: int

    # Execution outcomes
    success: bool
    duration_seconds: float
    quality_score: Optional[int]

    # Cost tracking
    cost_estimate: float
    actual_cost: float

    # Error context
    error_type: Optional[ErrorType]
    error_message: Optional[str]

    # User feedback
    user_accepted: Optional[bool]
    user_rating: Optional[int]

    # Resource utilization
    peak_memory_mb: Optional[float]
    cpu_time_seconds: Optional[float]

    # Solution extraction
    solution_summary: Optional[str]

    # Metadata
    metadata: dict[str, Any]
```

**Methods:**
- `calculate_embedding_content()` - Generate content for embedding
- `calculate_prediction_error()` - Calculate prediction accuracy
- `to_dict()` - Convert to dictionary
- `from_dict()` - Create from dictionary

### FeedbackSubmission

Feedback submission for a completed task.

```python
class FeedbackSubmission(BaseModel):
    task_id: UUID
    satisfaction: SatisfactionLevel
    issue_type: Optional[IssueType]
    comment: Optional[str]
    visibility: VisibilityLevel
    contextual_rating: Optional[ContextualRating]
    feedback_id: UUID
    timestamp: datetime
```

**Methods:**
- `get_anonymized_data()` - Get anonymized representation

### SatisfactionLevel

Satisfaction levels for task feedback.

```python
class SatisfactionLevel(str, Enum):
    EXCELLENT = "excellent"  # ⭐⭐⭐⭐⭐
    GOOD = "good"            # ⭐⭐⭐⭐
    FAIR = "fair"            # ⭐⭐⭐
    POOR = "poor"            # ⭐⭐
```

### IssueType

Specific issues for fair/poor ratings.

```python
class IssueType(str, Enum):
    WRONG_MODEL = "wrong_model"    # Model too small/large
    TOO_SLOW = "too_slow"          # Execution too slow
    POOR_QUALITY = "poor_quality"  # Output quality poor
    OTHER = "other"                # Other issue
```

### VisibilityLevel

Feedback visibility and sharing levels.

```python
class VisibilityLevel(str, Enum):
    PRIVATE = "private"  # Only you, stored locally
    TEAM = "team"        # Your team, for learning
    PUBLIC = "public"    # Global patterns, anonymized
```

### RouteDecision

Routing decision with metadata.

```python
class RouteDecision(BaseModel):
    adapter_id: AdapterType
    confidence: float
    reason: str
    neural_score: float
    expected_quality: float
    learning_data: dict[str, Any]
```

### SONAConfig

Configuration for SONA router.

```python
class SONAConfig(BaseModel):
    enabled: bool
    neural_network: NeuralNetworkConfig
    ewc: EWCConfig
    session_buddy: SessionBuddyConfig
    learning_rate: float
    update_frequency: int
    history_window: int
```

---

## Type Aliases

```python
AdapterType = Literal["llamaindex", "agno", "langgraph", "prefect"]
ErrorType = Literal["timeout", "quality_gate", "crash", "validation", "unknown"]
```

---

## Next Steps

- **[Quick Start Guide](LEARNING_FEEDBACK_LOOPS_QUICKSTART.md)** - Get started with feedback
- **[Integration Guide](LEARNING_INTEGRATION_GUIDE.md)** - Integrate with your components
- **[Troubleshooting](LEARNING_TROUBLESHOOTING.md)** - Common issues and solutions
