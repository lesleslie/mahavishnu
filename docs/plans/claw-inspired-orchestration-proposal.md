# Claw-Inspired Orchestration Enhancements for Mahavishnu

**Created**: 2026-04-09
**Status**: Draft
**Source**: Conceptual extraction from claw-code's architecture (not code porting)

## Overview

Three orchestration patterns from claw-code that would strengthen Mahavishnu's
existing infrastructure. All three build on current capabilities rather than
replacing them.

## 1. Verification Loops

**Priority**: First (smallest surface area, immediate value)

### Problem

Workflows execute tasks but don't validate results. If a code change fails tests,
the failure is reported but not automatically fed back for repair. This forces
human intervention on every test failure.

### Proposed Design

```
┌─────────┐     ┌──────────┐     ┌───────────┐     ┌──────────┐
│ Execute  │────▶│  Test    │────▶│ Evaluate  │────▶│  Done    │
│  Task    │     │  Runner  │     │  Gate     │     │          │
└────▲─────┘     └──────────┘     └─────┬─────┘     └──────────┘
     │                                │
     │           ┌──────────┐         │ pass
     │           │ Feedback │◀────────┘
     │           │ Builder  │
     │           └────┬─────┘
     │                │ fail
     └────────────────┘
```

**New component**: `VerificationLoop` in `mahavishnu/core/verification.py`

```python
@dataclass
class VerificationConfig:
    max_retries: int = 3                    # max feedback cycles
    quality_gates: list[QualityGate]        # lint, test, coverage, typecheck
    feedback_builder: FeedbackBuilder       # formats failures for re-prompt
    on_pass: str = "complete"               # "complete" | "notify" | "continue"
    on_exhaust: str = "fail"                # "fail" | "notify" | "escalate"

@dataclass
class QualityGate:
    name: str               # "pytest", "ruff", "mypy"
    command: str            # shell command to run
    parser: GateParser      # extracts pass/fail + failure details
    required: bool = True   # False = warning only

@dataclass
class VerificationResult:
    passed: bool
    gate_results: list[GateResult]
    cycles_used: int
    total_duration_seconds: float
    feedback_history: list[str]             # what was fed back each cycle
```

**Integration points**:

- `trigger_workflow` gains optional `verification: VerificationConfig`
- Existing `get_workflow_status` shows cycle count and current gate results
- Crackerjack integration: quality gates can delegate to `crackerjack_run(command="test")` or `crackerjack_run(command="check")` instead of raw shell commands

### Example MCP tool call

```json
{
  "adapter": "langgraph",
  "task_type": "code_change",
  "params": {
    "description": "Fix off-by-one in pagination",
    "verification": {
      "max_retries": 3,
      "quality_gates": [
        {"name": "pytest", "command": "uv run pytest tests/unit/test_pagination.py -x"},
        {"name": "ruff", "command": "uv run ruff check mahavishnu/core/pagination.py"}
      ]
    }
  }
}
```

### What exists today

- `trigger_workflow` — task execution
- `get_workflow_status` — status tracking
- `worker_execute` — single worker execution
- `crackerjack_run` — test/lint/check with AI auto-fix

### What's new

- The feedback loop (test fail → format failures → re-execute with feedback)
- Quality gates as configurable, composable objects
- Cycle tracking and exhaustion handling

______________________________________________________________________

## 2. Event Router Service

**Priority**: Second (solves Slack hang, helps Session-Buddy)

### Problem

Events (worker completions, heartbeats, cost alerts, system health) currently flow
through the agent's context window or ad-hoc `send_repository_message` calls. This:

- Bloats context windows with monitoring noise
- Causes hangs when slow event handlers block parallel tool calls (Slack hang bug)
- Makes it hard to route the right events to the right consumers

### Proposed Design

```
                    ┌──────────────────┐
   Workers ────────▶│                  │────▶ Session-Buddy (heartbeats)
   Workflows ─────▶│   Event Router   │────▶ Nanobot (user notification)
   Health checks ─▶│                  │────▶ Grafana (metrics, alerts)
   Crackerjack ───▶│                  │────▶ Logger (audit trail)
                    └──────────────────┘
                           │
                    ┌──────┴──────┐
                    │  Routing    │
                    │  Rules      │
                    └─────────────┘
```

**New component**: `EventRouter` in `mahavishnu/core/events.py`

```python
@dataclass
class Event:
    type: str                    # "worker.completed", "workflow.failed", "health.degraded"
    source: str                  # "worker-pool", "crackerjack", "session-buddy"
    payload: dict                # event-specific data
    timestamp: datetime
    routing_key: str | None = None  # optional override

@dataclass
class RoutingRule:
    match_type: str              # exact match or glob on event.type
    match_source: str | None     # filter by source
    consumer: str                # registered consumer name
    priority: int = 0            # higher = processed first
    filter_fn: Callable | None = None  # optional custom filter

class EventRouter:
    consumers: dict[str, EventConsumer]
    rules: list[RoutingRule]

    async def emit(self, event: Event) -> None
    def register_consumer(self, name: str, consumer: EventConsumer) -> None
    def add_rule(self, rule: RoutingRule) -> None
```

**Built-in consumers**:

- `SessionBuddyConsumer` — forwards relevant events to SB MCP tools
- `NotificationConsumer` — queues user-facing notifications (Slack, terminal)
- `LogConsumer` — writes to structured log (JSONL, optional Loki push)
- `OTelConsumer` — converts events to OTel spans/metrics (future Tempo integration)

### Routing examples

```yaml
# settings/mahavishnu.yaml
event_router:
  enabled: true
  consumers:
    - name: session-buddy
      type: session_buddy
    - name: notifications
      type: notification
    - name: audit-log
      type: log
      path: logs/events.jsonl
  rules:
    - match_type: "worker.completed"
      consumer: session-buddy
    - match_type: "workflow.failed"
      consumer: notifications
      priority: 10
    - match_type: "health.*"
      consumer: notifications
    - match_type: "*"
      consumer: audit-log
```

### What exists today

- `send_repository_message` — point-to-point message passing between repos
- `worker_monitor` — polling-based status checks
- OTel metrics/tracing (partially configured)

### What's new

- Decoupled pub/sub instead of point-to-point
- Events never enter the agent context window unless explicitly routed there
- Priority-based routing with filtering
- Pluggable consumers (not hardcoded to SB or Slack)

### Relation to Slack hang bug

Events currently flow through the agent context → parallel tool calls → slow
handlers block everything. With the router, events bypass the context window
entirely and go directly to consumers.

______________________________________________________________________

## 3. Role-Based Multi-Agent Coordination

**Priority**: Third (most complex, builds on 1 + 2)

### Problem

Workers are flat — every worker is a generic `terminal-*` executor. There's no
structured way to say "plan this, then implement it, then verify it." Complex
tasks require manual orchestration.

### Proposed Design

```
                    ┌──────────────────┐
                    │   Coordinator    │
                    │  (task planner)  │
                    └────────┬─────────┘
                             │ spec
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
        ┌──────────┐  ┌──────────┐  ┌──────────┐
        │Architect │  │Executor  │  │Reviewer  │
        │(planner) │  │(coder)   │  │(checker) │
        └──────────┘  └────┬─────┘  └──────────┘
                           │
                    ┌──────┴──────┐
                    │ Verification │
                    │   Loop (#1)  │
                    └─────────────┘
```

**New component**: `Coordinator` in `mahavishnu/core/coordinator.py`

```python
@dataclass
class Role:
    name: str                    # "architect", "executor", "reviewer"
    worker_type: str             # maps to existing worker types
    system_prompt: str           # role-specific instructions
    max_turns: int = 1           # how many cycles this role gets
    tools: list[str] | None = None  # restrict tools per role

@dataclass
class CoordinationPlan:
    task: str                    # high-level task description
    roles: list[Role]            # ordered role sequence
    handoff_strategy: str = "sequential"  # "sequential" | "fan_out" | "iterative"
    max_rounds: int = 3          # for iterative: how many full cycles

class Coordinator:
    async def execute(self, plan: CoordinationPlan) -> CoordinationResult
    async def handoff(self, from_role: str, to_role: str, context: dict) -> None
```

**Role definitions** (built-in, overridable):

| Role | Worker Type | Purpose | Key Tools |
|------|------------|---------|-----------|
| Architect | terminal-qwen | Analyze task, produce implementation spec | read_file, grep, glob |
| Executor | terminal-claude | Implement spec, write code | write_file, edit_file, exec |
| Reviewer | crackerjack | Validate output, run quality gates | crackerjack_run, pycharm diagnostics |

**Handoff flow**:

1. **Architect** receives task → produces `spec.md` (approach, files to change, tests to write)
1. **Executor** receives spec → implements changes → saves diff
1. **Reviewer** receives spec + diff → runs verification loop (#1) → passes or requests fixes
1. If reviewer requests fixes → back to Executor with feedback (counts as new round)
1. After `max_rounds` or pass → Coordinator reports final result

### Integration with existing workers

No new worker types needed. Roles map to existing `worker_spawn` types:

```python
plan = CoordinationPlan(
    task="Add retry logic to the Prefect adapter",
    roles=[
        Role(name="architect", worker_type="terminal-qwen",
             system_prompt="Analyze the codebase and write a brief implementation spec."),
        Role(name="executor", worker_type="terminal-claude",
             system_prompt="Implement the spec. Make minimal, focused changes."),
        Role(name="reviewer", worker_type="terminal-qwen",
             system_prompt="Run tests and lint. Report pass or specific failures."),
    ],
    max_rounds=2,
)
```

### What exists today

- `worker_spawn` / `worker_execute` — spawn and run workers
- `tool_pool.py` — assemble filtered tool sets (claw-code, could adapt concept)
- `permissions.py` — deny-list for tools (claw-code, concept applies here)

### What's new

- Sequential/fan-out/iterative handoff strategies
- Role-scoped tool restrictions (architect can't edit files, reviewer can't write)
- Spec-based coordination (output of one role is structured input to next)
- Round counting and exhaustion handling

______________________________________________________________________

## Implementation Roadmap

### Phase 1: Verification Loops (~1 week)

- [ ] `mahavishnu/core/verification.py` — `VerificationLoop`, `QualityGate`, `GateParser`
- [ ] Wire into `trigger_workflow` as optional param
- [ ] Update `get_workflow_status` to show verification state
- [ ] Crackerjack integration for quality gates
- [ ] Tests: unit for gate parsing, integration for full retry loop

### Phase 2: Event Router (~1-2 weeks)

- [ ] `mahavishnu/core/events.py` — `EventRouter`, `Event`, `RoutingRule`
- [ ] Built-in consumers: log, notification
- [ ] YAML config under `event_router` in settings
- [ ] Session-Buddy consumer (defers to SB MCP tools)
- [ ] Tests: routing rules, consumer dispatch, config loading

### Phase 3: Multi-Agent Coordination (~2 weeks)

- [ ] `mahavishnu/core/coordinator.py` — `Coordinator`, `CoordinationPlan`, `Role`
- [ ] Role-to-worker mapping using existing spawn/execute API
- [ ] Sequential handoff strategy
- [ ] Integration with verification loop (reviewer role uses it)
- [ ] Tests: role handoff, iterative rounds, tool scoping

### Dependencies

- Phase 1 is standalone
- Phase 2 is standalone
- Phase 3 depends on Phase 1 (reviewer uses verification loops)
- Phase 3 benefits from Phase 2 (events for coordination lifecycle)

______________________________________________________________________

## Open Questions

1. **Verification feedback format** — How much test output should go back to the executor? Full stdout, filtered failures only, or AI-summarized?
1. **Event persistence** — Should the event router persist events to Postgres/Dhara, or is in-memory + log sufficient for single-user dev?
1. **Coordinator isolation** — Should coordinated tasks run in a dedicated workspace/copy to avoid conflicts with the main workspace?
1. **Role system prompts** — Ship built-in prompts or require user configuration?
