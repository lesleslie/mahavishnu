---
status: active
role: implementation
topic: convergence-control-plane
date: 2026-07-16
last_reviewed: 2026-07-16
superseded_by: null
blocks_on: []
---

# Session-Buddy Checkpoint Stash-Clobber Fix Design

## Context

On 2026-07-15, the auto-checkpoint hook observed during the
comprehensive-hooks-cleanup wave re-applied a `git stash` *while a
subagent was actively working*, clobbering the agent's in-flight edits.
This is a sibling observation to the parent memory's commit-ordering
symptom (`session-buddy-checkpoint-hooks-fire-during-subagent-sessions`).
The parent memory tracks commits appearing between plan and implementer;
this new pattern tracks the *working tree* being silently overwritten
mid-task.

The current behavior is unsafe: the checkpoint cycle includes a
`git stash` → work → `git stash pop` (or equivalent) sequence that has a
race window during which a concurrent subagent's edits can be
overwritten. The fix must eliminate this race without losing the
analytic value that checkpoints provide.

## Constraints (from user clarification)

These are non-negotiable. Any implementation that violates them does
not satisfy this design.

1. **End-of-task checkpoint is mandatory.** Every subagent session
   ends with a checkpoint, period.
1. **Midpoint checkpoint is conditional.** It fires only when it adds
   value to the current worker's decision-making *or* session/worker
   analytics. Otherwise, it is silent.
1. **Working tree is never mutated by a checkpoint.** Snapshot capture
   is read-only; restore is a separate explicit user action.
1. **Failures fail closed.** Mechanism error → skip checkpoint, log
   loudly. No silent fallback to the old stash-based behavior.
1. **Hybrid approach is welcome.** Combining elements of multiple
   strategies is preferred over a pure single-strategy choice.

## Design summary

Three orthogonal guarantees, layered:

```
POLICY (when to fire)
  ├── End-of-task: always fires (after subagent commit if applicable)
  └── Midpoint: fires only when value-add criteria are met

MECHANISM (how to fire safely)
  └── Stash-free snapshot via `git diff > /tmp/snap-<uuid>.patch`
      Snapshot is read-only w.r.t. the working tree.

FALLBACK (when mechanism unavailable)
  └── Defer checkpoint until subagent finishes (Option A semantics)
      Used only if snapshot mechanism errors AND no subagent is active.
```

## Architecture

### Location (with explicit uncertainty)

**Primary recommendation**: implement in `session-buddy` (the
`store_conversation_checkpoint` tool). This is the choke point — fixing
the mechanism at its source means every caller (mahavishnu, future
tools) gets the fix automatically.

**Backup**: if the stash mechanism actually lives in `crackerjack`
(given the commit messages are signed "checkpoint: crackerjack (quality:
NN/100)"), implement there instead. Both options fix the root cause;
session-buddy is preferred because of caller-multiplicity.

**Tertiary (avoid)**: implementing in `mahavishnu` (the caller). This
would leave the underlying mechanism unchanged for other callers and
is a band-aid.

**Verification probe required before locking location**:

1. `grep -rn "stash\|subprocess.*git" /Users/les/Projects/session-buddy/session_buddy/mcp/ --include="*.py"`
1. `find /Users/les/Projects/crackerjack -maxdepth 6 -name "*.py" -path "*quality*" -exec grep -l "stash\|git commit" {} \;`
1. Trace one auto-checkpoint commit message back to its commit-creating function.

Probe runs in \<2 minutes and either confirms or refutes the location
hypothesis before the implementation begins.

### High-level flow

```
Claude Code pre_checkpoint hook
        │
        ▼
Orchestrator.run_checkpoint(phase, hook_request)
        │
        ▼
Policy.decide(phase, hook_request)
        │
        ├──► SubagentDetector.is_active()
        ├──► WorkingTreeInspector.get_stats()
        │
        ▼ PolicyDecision
   ┌────┴────┐
fire        skip
   │          │
   ▼          ▼
Snapshot    log reason;
.capture()  return
   │        fired=False
   ▼
forward_to(existing session-buddy tool)
   │
   ▼
CheckpointResult → caller / hook
```

## Components

Four units, each with one purpose, isolated interfaces, independently
testable. Composition root wires them.

### 1. `SubagentDetector`

**Purpose**: Signal whether a subagent is currently in flight.

**Interface**:

```python
class SubagentDetector:
    def __init__(self, working_dir: Path, signal_source: SignalSource):
        ...

    def is_active(self) -> bool:
        """True if a subagent is currently executing against working_dir."""

    def wait_until_idle(self, timeout: float = 60.0) -> bool:
        """Block until subagent is idle or timeout. Returns True if idle."""


class SignalSource(Protocol):
    def read(self) -> bool: ...
    def write(self, active: bool) -> None: ...
```

**Dependencies**: Pluggable `SignalSource` — lockfile, env var, or
MCP probe. Concrete implementations plug in here.

**Location**: New file `session_buddy/checkpoint/subagent_detector.py`.

### 2. `SnapshotMechanism`

**Purpose**: Capture working-tree state as a read-only snapshot.

**Interface**:

```python
class SnapshotMechanism:
    def __init__(self, working_dir: Path, snapshot_dir: Path):
        ...

    def capture(self, label: str) -> Snapshot:
        """Capture current working-tree state. Returns Snapshot with path + metadata."""

    def restore(self, snapshot: Snapshot) -> RestoreResult:
        """Apply a snapshot to the working tree. Returns success/failure."""


@dataclass
class Snapshot:
    path: Path           # /tmp/snap-<uuid>.patch
    label: str
    captured_at: datetime
    parent_commit: str
    dirty_files: list[str]
```

**Dependencies**: `git` CLI via `subprocess` with timeout.

**Key property**: `capture()` only writes a file; never mutates the
working tree. Restoring is a separate explicit step.

**Location**: New file `session_buddy/checkpoint/snapshot.py`.

### 3. `CheckpointPolicy`

**Purpose**: Decide whether a checkpoint should fire, given current state.

**Interface**:

```python
@dataclass
class PolicyDecision:
    should_fire: bool
    reason: str  # human-readable, always non-empty


@dataclass
class MidpointCriteria:
    """List of independent value-add signals. ANY signal firing triggers a midpoint.

    Per user clarification: midpoint fires when it helps the current worker's
    decision-making OR session/worker analytics. This is OR (any-of) semantics,
    not AND (all-of). Each signal is evaluated independently; the policy
    fires if any signal is active.
    """
    signals: list[ValueAddSignal] = field(default_factory=lambda: [
        TimeElapsedSignal(min_seconds=300.0),
        DirtyFilesSignal(min_count=5),
    ])


class ValueAddSignal(Protocol):
    """One independent reason a midpoint might be valuable."""
    def is_active(self, working_tree: WorkingTreeInspector) -> bool: ...
    def describe(self) -> str: ...  # human-readable, e.g. "5 min elapsed"


@dataclass
class TimeElapsedSignal:
    min_seconds: float = 300.0

    def is_active(self, working_tree: WorkingTreeInspector) -> bool:
        return working_tree.seconds_since_last_commit() >= self.min_seconds


@dataclass
class DirtyFilesSignal:
    min_count: int = 5

    def is_active(self, working_tree: WorkingTreeInspector) -> bool:
        return working_tree.dirty_file_count() >= self.min_count


class CheckpointPolicy:
    def __init__(
        self,
        *,
        always_end: bool = True,
        midpoint_enabled: bool = True,
        midpoint_criteria: MidpointCriteria,
        subagent_detector: SubagentDetector,
        working_tree: WorkingTreeInspector,
    ):
        ...

    def decide(self, *, phase: CheckpointPhase, hook_request: bool = False) -> PolicyDecision:
        """Phase is one of: END_OF_TASK, MIDPOINT_TIME, MIDPOINT_DIRTINESS, HOOK_REQUESTED.
        Returns should_fire=True iff:
          - phase == END_OF_TASK (always fires), OR
          - hook_request (user explicit override), OR
          - midpoint_enabled AND any signal in midpoint_criteria is active
            AND subagent_detector.is_active() is False
        """


class CheckpointPhase(str, Enum):
    END_OF_TASK = "end_of_task"
    MIDPOINT_TIME = "midpoint_time"
    MIDPOINT_DIRTINESS = "midpoint_dirtiness"
    HOOK_REQUESTED = "hook_requested"
```

**Dependencies**: `SubagentDetector`, `WorkingTreeInspector`.

**Location**: New file `session_buddy/checkpoint/policy.py`.

### 4. `CheckpointOrchestrator`

**Purpose**: Compose policy + mechanism + subagent-detector + fallback.

**Interface**:

```python
class CheckpointOrchestrator:
    def __init__(
        self,
        *,
        policy: CheckpointPolicy,
        snapshot: SnapshotMechanism,
        subagent_detector: SubagentDetector,
        forward_to: Callable[[CheckpointResult], Awaitable[None]],
    ):
        ...

    async def run_checkpoint(
        self, *, phase: CheckpointPhase, hook_request: bool = False
    ) -> CheckpointResult:
        """Decide → capture (if firing) → forward to existing tool."""


@dataclass
class CheckpointResult:
    fired: bool
    snapshot_id: str | None
    session_buddy_id: str | None
    decision_reason: str  # always populated
    error: str | None
```

**Dependencies**: All three previous components + the existing
`store_conversation_checkpoint` tool (the orchestrator wraps, doesn't
replace).

**Location**: New file `session_buddy/checkpoint/orchestrator.py`.
Re-exports from `session_buddy/checkpoint/__init__.py` for callers.

### Cross-cutting concerns

- No component knows the others' internal state. Policy asks detector
  for a boolean; orchestrator asks policy for a decision; mechanism
  just writes a file.
- Failure isolation: if the snapshot mechanism errors, the orchestrator
  can fall back to the policy's deferral path. If the policy errors,
  the orchestrator fails closed (skip the checkpoint, log loudly).
- Observability: every component emits structured logs with consistent
  fields (`session_id`, `working_dir`, `phase`, `decision_reason`).
  Decision reasoning is captured in `PolicyDecision.reason` so an
  out-of-band observer can reconstruct *why* a checkpoint did or
  didn't fire.

## Data flow

### Five sequences

1. **Midpoint fires (happy path)**: trigger → policy.decide → detector
   not active + criteria met → capture → forward_to → result.
1. **End-of-task fires (always)**: trigger → policy.decide (always
   true for END_OF_TASK) → wait_until_idle if detector active →
   capture → forward_to → result.
1. **Midpoint deferred (subagent active)**: trigger → policy.decide →
   detector active → return fired=False with reason. End-of-task will
   fire when subagent commits (Sequence 2).
1. **Fallback (snapshot unavailable)**: policy.decide says yes →
   capture() raises → orchestrator catches → fail closed (skip +
   log). No retry against the old stash-based behavior.
1. **Subagent starts mid-snapshot**: capture in progress, subagent
   writes files concurrently → capture completes (may be slightly
   inconsistent diff) → forward_to → subagent continues. Working
   tree is never mutated, so the agent's edits are safe.

### Invariants (the contract the design must preserve)

1. The working tree is never mutated by a checkpoint.
1. `PolicyDecision.reason` is always non-empty.
1. Every `CheckpointResult` includes `decision_reason`.
1. Snapshot files are immutable after `capture()` returns.
1. Failures fail closed.
1. Subagent active → midpoint checkpoint deferred (no exceptions).
   End-of-task may `wait_until_idle()` instead.

## Error handling

### Per-component error responses

**`SnapshotMechanism`**: git binary missing, timeout, write failure →
fail closed, log ERROR. Empty working tree → soft success, skip
forward_to (no point checkpointing a clean tree).

**`SubagentDetector`**: lockfile permission error, malformed signal →
fail open to "active" (assume subagent active, defer). Safer to defer
unnecessarily than to risk clobber. `wait_until_idle()` timeout →
fail closed.

**`Policy`**: working tree inspector fails (not in git repo) → fail
closed. Criterion evaluation throws → fail closed.

**`forward_to` (existing session-buddy tool)**: unreachable / 5xx →
retry once with exponential backoff, then fail closed. 4xx → no
retry, fail closed. Snapshot file remains on disk for manual recovery.

**`restore` (manual, user-initiated)**: patch file missing → fail loud
with snapshot id. `git apply` conflicts → fail loud, print hunks, no
auto-resolve. Working tree drift from parent_commit → warn, show drift
summary, user decides.

### Cleanup contract

Snapshot files (the only persistent artifact) have explicit cleanup
semantics:

- **TTL-based**: 7-day default TTL. Background cleanup task removes
  expired snapshots.
- **Session-end hook**: Lists all snapshots for the working dir in
  the session-end log; operator can run cleanup command.
- **Manual**: `session-buddy checkpoint cleanup-snapshots [--older-than=Nd]`.
- **On success or failure**: snapshot files are *kept* for at least
  the TTL window. The failure case is the most likely time the user
  wants to inspect.

### Concurrency

- Two simultaneous checkpoint requests → `asyncio.Lock` per working
  directory; second waits. No data corruption.
- Checkpoint during restore → orchestrator lock blocks checkpoint
  until restore completes. Documented in restore help text.

### Operator-visible signals

Each error path emits:

1. Structured log at WARNING or ERROR with consistent fields.
1. Metric increment: `checkpoint_failures_total{reason="..."}` (one
   per failure reason).
1. Optional alert hook (out of scope; leaves the hook point).

## Testing

### Test pyramid

```
End-to-end (real Claude Code + real subagent + real git) — 1-2 tests
    ▲
Orchestrator integration (mocked components, real asyncio) — 10-20
    ▲
Component unit tests — 50-100
    ▲
Property-based invariant tests — 10-20
```

### Property-based invariant test (keystone)

```python
@given(
    dirty_files=st.lists(st.text(min_size=1, max_size=20), min_size=0, max_size=50, unique=True),
    subagent_active=st.booleans(),
    checkpoint_phase=st.sampled_from(list(CheckpointPhase)),
)
def test_working_tree_never_mutated_by_checkpoint(tmp_git_repo, dirty_files, subagent_active, checkpoint_phase):
    write_files(tmp_git_repo, dirty_files)
    before = hash_working_tree(tmp_git_repo)

    detector = MockSubagentDetector(subagent_active)
    policy = CheckpointPolicy(subagent_detector=detector, ...)
    orchestrator = CheckpointOrchestrator(policy=policy, snapshot=SnapshotMechanism(tmp_git_repo, ...), ...)

    result = asyncio.run(orchestrator.run_checkpoint(phase=checkpoint_phase))

    after = hash_working_tree(tmp_git_repo)
    assert before == after, f"Working tree mutated! Result: {result}"
```

### Regression test for the original bug

```python
def test_stash_clobber_regression(tmp_git_repo):
    """Regression test for the 2026-07-15 stash-clobber observation."""
    write_files(tmp_git_repo, ["modified.py", "new_file.py"])
    write_lockfile(tmp_git_repo)

    stash_invocations = []
    def spy_git(*args, **kwargs):
        if "stash" in args:
            stash_invocations.append(args)
        return real_git(*args, **kwargs)

    with mock.patch("subprocess.run", spy_git):
        result = asyncio.run(orchestrator.run_checkpoint(phase=MIDPOINT_TIME))

    assert result.fired == False
    assert "subagent active" in result.decision_reason
    assert stash_invocations == [], f"git stash was called: {stash_invocations}"
    assert hash_working_tree(tmp_git_repo) == before_hash
```

### Coverage target

90%+ on the new `session_buddy/checkpoint/` module (higher than the
project default 80% because this is safety-critical code).

### Test infrastructure

- `hypothesis` for property-based tests.
- `pytest-asyncio` with `asyncio_mode = "auto"`.
- `pytest-mock` for the subprocess spy.
- Existing project markers (`unit`, `integration`, `property`, `slow`)
  — no new markers needed.

## Deferred decisions

These are policy knobs that should be tuned by usage, not locked in
by this design. Implementation should make them configurable.

| Decision | Default | Tuning point |
|---|---|---|
| `MidpointCriteria.signals` | `[TimeElapsedSignal(300.0), DirtyFilesSignal(5)]` | Per-project, per-user via config — any signal firing triggers a checkpoint (OR semantics) |
| `TimeElapsedSignal.min_seconds` | 300.0 (5 min) | Tunable per-deployment |
| Snapshot TTL | 7 days | Operator-configurable |
| `wait_until_idle()` timeout | 60.0s | Operator-configurable |
| Snapshot dir | `/tmp/snap-<uuid>.patch` | System-config |
| `SignalSource` concrete impl | TBD (lockfile vs env var vs MCP) | Decided in implementation phase |

## Tracking

- **Originating observation**: 2026-07-15 comprehensive-hooks-cleanup wave
  (`docs/followups/2026-07-15-comprehensive-hooks-cleanup-checkpoint.md`)
- **Defect record**: `docs/followups/2026-07-15-sb-checkpoint-stash-clobber.md`
- **Pickup prompt** (future-session verification):
  `docs/followups/2026-07-15-pickup-bodai-hooks-and-sb-debug.md` (Step 3e
  - acceptance criterion #6)
- **Parent memory**:
  `~/.claude/projects/-Users-les-Projects-mahavishnu/memory/session-buddy-checkpoint-hooks-fire-during-subagent-sessions.md`
- **Recovery procedure** (sibling memory): `drift-bundling-recovery`

## Implementation gate

User has stated: "let's not commit to anything until some code work is
done." This spec is approved for design but implementation does not
begin until the user signals readiness. Next step (when ready):
invoke `superpowers:writing-plans` to create the implementation plan
from this spec.
