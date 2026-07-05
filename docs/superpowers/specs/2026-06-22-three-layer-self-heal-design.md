# Three-Layer Self-Heal v1.0 — Design

**Status:** Draft (brainstormed 2026-06-22)
**Phase:** 2 (Workflow Evolution)
**Source:** `Building a Production Agent Harness` — Layer 4 ("Self-Healing Loops"). The article's L1/L2/L3 pattern is a partial-function recovery: deterministic fast path → bounded agentic retry → operator escalation. Designed to recover from *known* failures without pages.

**Depends on:** `completion-report-schema-v1` (L2's Claude sessions emit reports via Spec #1's publisher), `precommitment-hypothesis-lock` and `confidence-ceiling-gate` (L2's Claude sessions run through both gates).

**Note on scope:** Per spec, this defines the protocol AND applies it to git operations as the canonical implementation. Worker recovery, MCP tool failures, and persistence errors adopt the same protocol in follow-up specs.

______________________________________________________________________

## Overview

This spec defines `ThreeLayerHeal[OpInput, OpOutput]` — a generic recovery protocol that wraps a single operation in three layers:

- **L1 — Deterministic guard.** Synchronous, sub-second, rule-based. Always-on. Free (no Claude cost). For git push: `git fetch && git rebase` first; if clean, proceed; if conflict, raise `L1Aborted` with conflict context.
- **L2 — Bounded agentic heal.** Spawns a constrained Claude session with the failure context + tight red lines. Up to 3 attempts per incident, 4-minute timeout per Claude turn. Each attempt: run Claude → re-run the real operation → check exit code (ground truth on the wire). Confidence ≥ 70 required for Claude to act; below → bail to L3.
- **L3 — Operator escalation.** When L2 bails or exhausts attempts, escalate via Mahavishnu's existing `request_approval` MCP tool. Operator sees the full trail and chooses: retry, abort, or skip.

This spec applies the protocol to three git operations: `git push`, `git rebase`, and `git merge` conflict resolution.

**Architectural property:** L1/L2/L3 are about **per-operation recovery**, distinct from `heal_workflows` (per-workflow recovery). They compose: `heal_workflows` is the outer loop (workflow failed → retry the whole workflow); L1/L2/L3 is the inner loop (one operation failed → recover this step without escalating to the outer loop).

______________________________________________________________________

## Goals

- **G1.** Recover from known git failures (rebase conflicts, transient push rejections) without operator intervention in the common case.
- **G2.** Bound L2's Claude cost: 3 attempts × 4 minutes maximum. No unbounded loops.
- **G3.** Ground truth on the wire: L2 success is determined by re-running the real git operation, not by Claude's self-report.
- **G4.** Reuse existing Mahavishnu observability: structured logs + Prometheus counters. No new event schema.
- **G5.** Reuse existing operator escalation surface (`request_approval` MCP tool). No new notification path.

## Non-Goals

- **N1.** Replacing or modifying `heal_workflows` (the per-workflow recovery tool). L1/L2/L3 is the inner loop; `heal_workflows` is the outer loop.
- **N2.** Defining L1/L2/L3 for worker recovery, MCP tool failures, or persistence errors. Those operation classes adopt the protocol in follow-up specs.
- **N3.** A new event type for heal attempts. Activity surfaces via logs + metrics; the protocol is invisible to Spec #1's report pipeline at the API surface (L2's Claude sessions still emit reports via Spec #1's publisher, but the L2 retry logic itself is opaque).
- **N4.** Auto-recovery from failures with security implications (force-push to protected branches, dropping unpushed commits). L2 has hard red lines that prevent these regardless of operator approval.

______________________________________________________________________

## Architecture & Data Flow

```
Operation (e.g., git push):
  L1: deterministic_guard(operation)
    ├─ Rule passes (clean rebase) → operation() → return result
    └─ Rule fails (conflict) → raise L1Aborted(context)

  L2: bounded_agentic_heal(operation, l1_context)
    ├─ for attempt in 1..3:
    │    ├─ claude_turn(prompt_with_failure_context)  ← 4-min timeout
    │    ├─ if confidence < 70 OR Claude declines → break
    │    ├─ execute action (e.g., resolve conflict)
    │    └─ re_run(operation())  ← ground truth on the wire
    │         ├─ exit 0 → return result (L2 success)
    │         └─ non-zero → continue
    ├─ attempts exhausted → raise L2Exhausted(trail)
    └─ Claude confidence < 70 → raise L2Bailed(trail)

  L3: escalate_to_operator(operation, l1_context, l2_trail)
    └─ request_approval(
         summary=f"L2 unable to recover {operation}",
         context={l1_context, l2_trail},
         options=["retry", "abort", "skip"],
       )
       └─ operator decision drives next action
```

**Key properties:**

1. **L1 is synchronous and free.** Runs on every operation; no token cost; catches the common case.
1. **L2 is bounded.** 3 attempts × 4 min = 12 min max per operation. No surprise costs.
1. **L2 trusts the wire, not Claude.** Each attempt's success is determined by `git push exit 0`, not by Claude saying "fixed it."
1. **L3 reuses existing infrastructure.** `request_approval` already does operator escalation; L3 just calls it with structured context.
1. **L2 attempts emit reports.** L2's constrained Claude session runs through Spec #1's publisher, so Akosha sees L2 attempt activity in the same observability stream as regular work.

______________________________________________________________________

## Protocol Types

```python
# mahavishnu/core/heal/protocol.py

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

OpInput = TypeVar("OpInput")
OpOutput = TypeVar("OpOutput")


class L1Aborted(Exception):
    """Raised by L1 when the deterministic rule fails.

    Carries context for L2 to consume.
    """

    def __init__(self, message: str, context: dict[str, Any]) -> None:
        super().__init__(message)
        self.context = context


class L2Bailed(Exception):
    """Raised by L2 when Claude's confidence is below threshold or Claude declines to act."""

    def __init__(self, message: str, trail: list[dict[str, Any]]) -> None:
        super().__init__(message)
        self.trail = trail


class L2Exhausted(Exception):
    """Raised by L2 when all retry attempts fail."""

    def __init__(self, message: str, trail: list[dict[str, Any]]) -> None:
        super().__init__(message)
        self.trail = trail


@dataclass(frozen=True)
class HealConfig:
    """Per-operation healing configuration."""

    max_l2_attempts: int = 3
    l2_turn_timeout_seconds: int = 240  # 4 minutes
    l2_confidence_floor: int = 70
    red_lines: tuple[str, ...] = ()  # e.g. ("never_force_push_to_protected",)


@dataclass(frozen=True)
class HealAttempt:
    """One L2 attempt's record for the trail."""

    attempt_index: int
    action_taken: str
    confidence: int
    wire_exit_code: int
    duration_ms: int
```

______________________________________________________________________

## L1 — Deterministic Guard

```python
# mahavishnu/core/heal/l1.py

from __future__ import annotations

from typing import Awaitable, Callable

from mahavishnu.core.heal.protocol import L1Aborted, OpInput, OpOutput


async def run_with_l1(
    operation: Callable[[OpInput], Awaitable[OpOutput]],
    *,
    input: OpInput,
    l1_guard: Callable[[OpInput], Awaitable[None]],
) -> OpOutput:
    """Run operation with L1 deterministic guard.

    1. Run l1_guard synchronously. If it raises L1Aborted, propagate to caller (L2 handler).
    2. If l1_guard returns normally, run operation and return result.
    """
    await l1_guard(input)
    return await operation(input)
```

L1 is intentionally minimal — a guard function plus a runner. The guard raises `L1Aborted` on failure; the runner propagates the exception.

______________________________________________________________________

## L2 — Bounded Agentic Heal

```python
# mahavishnu/core/heal/l2.py

from __future__ import annotations

import time
from typing import Awaitable, Callable

from oneiric.logging import get_logger
from prometheus_client import Counter

from mahavishnu.core.heal.protocol import (
    HealAttempt,
    HealConfig,
    L1Aborted,
    L2Bailed,
    L2Exhausted,
    OpInput,
    OpOutput,
)

logger = get_logger(__name__)

HEAL_ATTEMPTS_TOTAL = Counter(
    "mahavishnu_heal_l2_attempts_total",
    "L2 self-heal attempts by operation and outcome",
    ["operation", "outcome"],
)
HEAL_FAILURES_TOTAL = Counter(
    "mahavishnu_heal_l2_failures_total",
    "L2 self-heal failures (bail or exhausted)",
    ["operation", "reason"],
)


async def run_with_l2(
    operation_name: str,
    operation: Callable[[OpInput], Awaitable[OpOutput]],
    *,
    input: OpInput,
    l1_context: dict,
    config: HealConfig,
    claude_turn: Callable[[OpInput, dict, int], Awaitable[tuple[str, int]]],
    red_line_check: Callable[[str], None],
) -> OpOutput:
    """Run operation with bounded agentic heal on L1 failure.

    Args:
        operation_name: for metrics labels.
        operation: the actual operation to run.
        input: the input to the operation.
        l1_context: context from the L1 abort.
        config: HealConfig (max attempts, timeout, confidence floor).
        claude_turn: async (input, context, attempt_index) -> (action_description, confidence).
            Must respect red_line_check before returning action.
        red_line_check: callable that raises if action violates red lines.

    Raises:
        L2Bailed: if Claude confidence < floor or Claude declines.
        L2Exhausted: if all attempts fail.
    """
    trail: list[HealAttempt] = []

    for attempt_index in range(1, config.max_l2_attempts + 1):
        turn_start = time.monotonic()
        try:
            action, confidence = await claude_turn(
                input, l1_context, attempt_index
            )
        except Exception as exc:
            logger.exception(
                "L2 claude turn failed",
                extra={"operation": operation_name, "attempt": attempt_index},
            )
            HEAL_FAILURES_TOTAL.labels(operation=operation_name, reason="turn_error").inc()
            trail.append(
                HealAttempt(
                    attempt_index=attempt_index,
                    action_taken=f"turn_error: {exc!s}",
                    confidence=0,
                    wire_exit_code=-1,
                    duration_ms=int((time.monotonic() - turn_start) * 1000),
                )
            )
            continue

        if confidence < config.l2_confidence_floor:
            HEAL_ATTEMPTS_TOTAL.labels(operation=operation_name, outcome="bail").inc()
            HEAL_FAILURES_TOTAL.labels(operation=operation_name, reason="low_confidence").inc()
            trail.append(
                HealAttempt(
                    attempt_index=attempt_index,
                    action_taken=action,
                    confidence=confidence,
                    wire_exit_code=-1,
                    duration_ms=int((time.monotonic() - turn_start) * 1000),
                )
            )
            raise L2Bailed(
                f"L2 bailed: confidence {confidence} < floor {config.l2_confidence_floor}",
                trail=[vars(a) for a in trail],
            )

        # Red line enforcement (defense in depth — Claude should self-check via prompt,
        # but the protocol enforces hard rules).
        try:
            red_line_check(action)
        except Exception as exc:
            HEAL_FAILURES_TOTAL.labels(operation=operation_name, reason="red_line_violation").inc()
            raise L2Bailed(
                f"L2 action violated red line: {exc!s}",
                trail=[vars(a) for a in trail],
            )

        # Ground truth on the wire: run the real operation exactly once.
        # (C4 fix: previously this code called `await operation(input)` twice on
        # success — once to capture exit code, then again to return its result.
        # Side-effecting operations (git push) must NOT execute twice. Capture
        # the result on the same call.)
        wire_exit = -1
        result = None
        try:
            result = await operation(input)
            wire_exit = 0
        except Exception as exc:
            wire_exit = getattr(exc, "returncode", 1)

        duration_ms = int((time.monotonic() - turn_start) * 1000)
        trail.append(
            HealAttempt(
                attempt_index=attempt_index,
                action_taken=action,
                confidence=confidence,
                wire_exit_code=wire_exit,
                duration_ms=duration_ms,
            )
        )

        if wire_exit == 0:
            HEAL_ATTEMPTS_TOTAL.labels(operation=operation_name, outcome="success").inc()
            logger.info(
                "L2 self-heal succeeded",
                extra={
                    "operation": operation_name,
                    "attempt": attempt_index,
                    "duration_ms": duration_ms,
                },
            )
            return result  # type: ignore[return-value]

        HEAL_ATTEMPTS_TOTAL.labels(operation=operation_name, outcome="wire_failure").inc()
        logger.warning(
            "L2 self-heal attempt failed",
            extra={
                "operation": operation_name,
                "attempt": attempt_index,
                "wire_exit_code": wire_exit,
            },
        )

    HEAL_FAILURES_TOTAL.labels(operation=operation_name, reason="exhausted").inc()
    raise L2Exhausted(
        f"L2 exhausted after {config.max_l2_attempts} attempts",
        trail=[vars(a) for a in trail],
    )
```

______________________________________________________________________

## L3 — Operator Escalation

```python
# mahavishnu/core/heal/l3.py

from __future__ import annotations

from typing import Any

from mahavishnu.core.heal.protocol import L2Bailed, L2Exhausted, OpInput


async def escalate_to_operator(
    operation_name: str,
    *,
    input: OpInput,
    l1_context: dict[str, Any],
    l2_exception: L2Bailed | L2Exhausted,
) -> str:
    """Escalate to operator via request_approval.

    Returns the operator's chosen action: "retry" | "abort" | "skip".
    """
    from mahavishnu.mcp.tools.approval_tools import request_approval

    trail_summary = "\n".join(
        f"  attempt {a['attempt_index']}: {a['action_taken']} "
        f"(confidence={a['confidence']}, wire_exit={a['wire_exit_code']})"
        for a in l2_exception.trail
    )

    return await request_approval(
        approval_type=f"heal_escalation_{operation_name}",
        context={
            "operation": operation_name,
            "l1_context": l1_context,
            "l2_failure": type(l2_exception).__name__,
            "l2_trail": trail_summary,
            "options": ["retry", "abort", "skip"],
        },
    )
```

______________________________________________________________________

## Git Operations: Three Canonical Implementations

### Git push with rebase-guard

```python
# mahavishnu/core/git_heal.py

from __future__ import annotations

import asyncio

from mahavishnu.core.heal.l1 import run_with_l1
from mahavishnu.core.heal.l2 import run_with_l2
from mahavishnu.core.heal.l3 import escalate_to_operator
from mahavishnu.core.heal.protocol import (
    HealConfig,
    L1Aborted,
    L2Bailed,
    L2Exhausted,
)


HEAL_CONFIG_PUSH = HealConfig(
    max_l2_attempts=3,
    l2_turn_timeout_seconds=240,
    l2_confidence_floor=70,
    red_lines=("never_force_push_to_protected",),
)


async def _l1_pre_push_rebase(repo_path: str, branch: str) -> None:
    """Fetch and rebase; abort with conflict context if rebase fails."""
    proc = await asyncio.create_subprocess_exec(
        "git", "-C", repo_path, "fetch", "origin", branch,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await proc.wait()
    if proc.returncode != 0:
        raise L1Aborted(
            f"git fetch failed with exit {proc.returncode}",
            {"repo_path": repo_path, "branch": branch, "stage": "fetch"},
        )
    proc = await asyncio.create_subprocess_exec(
        "git", "-C", repo_path, "rebase", f"origin/{branch}",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise L1Aborted(
            "rebase conflict — fetch+rebase failed",
            {
                "repo_path": repo_path,
                "branch": branch,
                "stage": "rebase",
                "stderr": stderr.decode(errors="ignore")[:1000],
            },
        )


async def _do_push(repo_path: str, branch: str) -> None:
    proc = await asyncio.create_subprocess_exec(
        "git", "-C", repo_path, "push", "origin", branch,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await proc.wait()
    if proc.returncode != 0:
        raise RuntimeError(f"git push failed with exit {proc.returncode}")


def _red_line_check_push(action: str) -> None:
    if "force" in action.lower() and "protected" in action.lower():
        raise ValueError(f"red line violated: {action}")


async def push_with_heal(repo_path: str, branch: str) -> None:
    """Git push with three-layer self-heal."""
    try:
        await run_with_l1(
            _do_push, input=(repo_path, branch), l1_guard=_l1_pre_push_rebase
        )
        return
    except L1Aborted as l1_exc:
        l1_context = l1_exc.context
        try:
            await run_with_l2(
                "git_push",
                _do_push,
                input=(repo_path, branch),
                l1_context=l1_context,
                config=HEAL_CONFIG_PUSH,
                claude_turn=_claude_turn_for_push,
                red_line_check=_red_line_check_push,
            )
            return
        except (L2Bailed, L2Exhausted) as l2_exc:
            await escalate_to_operator(
                "git_push",
                input=(repo_path, branch),
                l1_context=l1_context,
                l2_exception=l2_exc,
            )
            # Operator decision drives the next action (retry/abort/skip).
            # Implementation depends on operator's response.
```

(`_claude_turn_for_push` is project-specific — a constrained Claude session with prompt including the failure context, red lines, and a JSON output contract. Stubbed here; the spec focuses on the protocol, not the Claude prompt template.)

### Git rebase with conflict-resolution

```python
HEAL_CONFIG_REBASE = HealConfig(
    max_l2_attempts=3,
    l2_turn_timeout_seconds=240,
    l2_confidence_floor=70,
    red_lines=("never_drop_unpushed_commits", "never_blind_pick_conflict_side"),
)


async def rebase_with_heal(repo_path: str, upstream: str) -> None:
    """Git rebase with three-layer self-heal on conflict."""
    # Similar structure to push_with_heal.
    # L1: attempt rebase directly.
    # L2: on conflict, spawn Claude to resolve conflicts.
    # L3: if L2 can't resolve, escalate.
    ...
```

### Git merge with conflict-resolution

```python
HEAL_CONFIG_MERGE = HealConfig(
    max_l2_attempts=3,
    l2_turn_timeout_seconds=240,
    l2_confidence_floor=70,
    red_lines=("never_drop_unpushed_commits",),
)


async def merge_with_heal(repo_path: str, branch: str) -> None:
    """Git merge with three-layer self-heal on conflict."""
    # Similar structure.
    ...
```

______________________________________________________________________

## Adoption & Migration

| Version | Adoption |
|---|---|
| **v1.0** | Protocol + git operations shipped. New code uses `push_with_heal`, `rebase_with_heal`, `merge_with_heal` instead of direct subprocess calls. |
| **v1.1** | Existing `mahavishnu/core/worktree.py` and `mahavishnu/mcp/tools/worktree_tools.py` migrated to use the heal-wrapped versions. Direct subprocess calls log deprecation warnings. |
| **v2.0** | All git operations in Mahavishnu's codebase use the heal-wrapped versions. Direct calls removed. |

**CLI aid:** A new `mahavishnu heal --check-coverage` command scans the codebase for direct `asyncio.create_subprocess_exec("git", ...)` calls and flags those that aren't routed through the heal-wrapped helpers.

______________________________________________________________________

## Storage & Retrieval

No schema change. Activity surfaces via:

- **Prometheus counters** (already exposed by Mahavishnu's metrics endpoint): `mahavishnu_heal_l2_attempts_total{operation, outcome}`, `mahavishnu_heal_l2_failures_total{operation, reason}`.
- **Structured logs** at INFO/WARNING/ERROR levels with operation name, attempt index, confidence, wire exit code.
- **L2's Claude session reports** via Spec #1's pipeline (the Claude session itself runs through the publisher).

**No Dhara tables.** Heal activity is ephemeral; consumers needing history use Prometheus + logs.

______________________________________________________________________

## Error Handling

| Failure | Detection | Response |
|---|---|---|
| L1 rule fails | `L1Aborted` raised by guard | Caught by `push_with_heal`; L2 invoked. |
| L2 Claude confidence < 70 | Computed in `run_with_l2` | `L2Bailed` raised; L3 escalates. |
| L2 Claude action violates red line | `red_line_check` raises | `L2Bailed` raised; L3 escalates. (Hard rule; no override.) |
| L2 all attempts exhausted | Loop terminates without success | `L2Exhausted` raised; L3 escalates. |
| L3 `request_approval` fails (operator unreachable) | Exception in `escalate_to_operator` | Bubbles up to caller; caller decides (typically abort the workflow). |
| Wire re-run times out (git hangs) | Subprocess timeout | Treated as wire failure; counts as L2 attempt failure. |
| L2 turn exceeds 4-minute timeout | `claude_turn` returns timeout error | Treated as turn_error; counts as L2 attempt failure. |

______________________________________________________________________

## Testing Strategy

| Layer | Tests |
|---|---|
| **L0 (pure boundary)** | Protocol types: `L1Aborted`, `L2Bailed`, `L2Exhausted` carry correct context. `HealConfig` defaults. `HealAttempt` fields. |
| **L1 (file isolation)** | `run_with_l1` propagates `L1Aborted` correctly; runs operation when guard returns normally. |
| **L2 (service isolation)** | `run_with_l2` with mocked `claude_turn` and `operation`: counts attempts, enforces confidence floor, red lines, exhausts attempts, raises correct exception type. Bounded retry (max 3 attempts). Prometheus counters increment correctly. |
| **L3 (service isolation)** | `escalate_to_operator` calls `request_approval` with correct context. Returns operator's choice. |
| **L2 wire-truth** | Mocked `claude_turn` returns action; `run_with_l2` re-runs `operation` and checks exit code. Wire exit != 0 → continue. Wire exit == 0 → success regardless of Claude's claim. |
| **L3 (integration)** | End-to-end with mocked `request_approval`: L1 fail → L2 fail → operator approval "retry" → re-invokes L1. |
| **Git operations (integration)** | Real git in tmpdir: `push_with_heal` succeeds on clean repo; L1 fails on rebase conflict; L2 (mocked Claude) resolves; L3 escalates when L2 bails. |
| **L4 (production replay)** | After first production incident, encode actor + state + git state as a regression test. |

**Coverage target:** `tests/unit/test_heal_protocol.py`, `tests/unit/test_heal_l2.py` ≥ 95% line coverage.

______________________________________________________________________

## Implementation Module Paths

| Component | Path |
|---|---|
| Protocol types | `mahavishnu/core/heal/protocol.py` |
| L1 runner | `mahavishnu/core/heal/l1.py` |
| L2 runner | `mahavishnu/core/heal/l2.py` |
| L3 escalation | `mahavishnu/core/heal/l3.py` |
| Git operations | `mahavishnu/core/git_heal.py` |
| Prometheus counters | `mahavishnu/core/heal/metrics.py` |
| Coverage CLI | `mahavishnu/cli/heal_coverage_cli.py` |
| L0/L1/L2 tests | `tests/unit/test_heal_protocol.py`, `tests/unit/test_heal_l1.py`, `tests/unit/test_heal_l2.py` |
| L3 tests | `tests/unit/test_heal_l3.py` |
| Git integration tests | `tests/integration/test_git_heal.py` |
| L4 regression tests | `tests/integration/test_heal_regression.py` |

______________________________________________________________________

## Trade-offs & Alternatives Considered

| Choice | Why this | Why not the alternative |
|---|---|---|
| L1/L2/L3 are partial functions with `try/except` | Idiomatic Python; minimal new abstraction | Generic strategy pattern — over-engineered for the problem |
| L2 uses bounded retry (3 attempts × 4 min) | Article-faithful; bounded cost | Unbounded retry — runaway costs in production |
| Wire truth via re-running the real operation | Article-faithful; impossible for Claude to game | Trust Claude's self-report — known failure mode |
| L3 reuses `request_approval` MCP | Existing infrastructure; no new notification path | New Slack/email path — additional surface, more config |
| L2 emits iteration reports via Spec #1's publisher (Claude session) | Akosha sees heal activity in the standard stream | New `workflow.heal.attempt` event — new schema, new consumer |
| Red lines enforced in code, not just prompt | Defense in depth; Claude cannot bypass | Prompt-only red lines — known failure mode (jailbreak) |
| Three git operations in v1.0 | Article-faithful scope; demonstrates the pattern | All operations (git + worker + MCP + persistence) — too large for one spec |
| No new event schema | Reuse existing observability | New event type for heal attempts — couples protocol to schema |

______________________________________________________________________

## Open Questions / Future Work

- **OQ1.** Claude prompt template for L2: project-specific. Out of scope for protocol spec; documented as implementation guidance.
- **OQ2.** Apply the protocol to worker recovery (MCP tool failures, retry transient errors). Follow-up spec.
- **OQ3.** Apply the protocol to persistence failures (Dhara write retry). Follow-up spec.
- **OQ4.** Apply the protocol to MCP tool failures (rate limits, transient errors). Follow-up spec.
- **OQ5.** L2 Claude session's `metadata.heal_attempt_index` field on its emitted IterationReports. Convention; not enforced. Documented as guidance.

______________________________________________________________________

## Success Criteria

- **SC1.** Protocol types implemented; L1/L2/L3 runners implemented with full L0–L2 test coverage.
- **SC2.** Git operations (`push_with_heal`, `rebase_with_heal`, `merge_with_heal`) implemented and tested against real git in tmpdir.
- **SC3.** L2 enforces: bounded retry (max 3 attempts), 4-min turn timeout, confidence ≥ 70, hard red lines.
- **SC4.** Wire truth: L2 success is determined by re-running the real git operation, not by Claude's claim.
- **SC5.** Prometheus counters exposed: `mahavishnu_heal_l2_attempts_total`, `mahavishnu_heal_l2_failures_total`.
- **SC6.** L3 escalation reuses `request_approval` MCP tool; operator sees full L2 trail.
- **SC7.** L1/L2/L3 compose with `heal_workflows` (outer loop) without conflict; both can run on the same workflow.
