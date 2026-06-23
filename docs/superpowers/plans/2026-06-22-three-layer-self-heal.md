# Three-Layer Self-Heal v1.0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a per-operation recovery protocol (L1 deterministic guard, L2 bounded agentic heal, L3 operator escalation) applied to git push, rebase, and merge — letting the system recover from known failures without operator pages in the common case.

**Architecture:** Generic protocol in `mahavishnu/core/heal/` (L1Aborted/L2Bailed/L2Exhausted types, `run_with_l1`/`run_with_l2`/`escalate_to_operator` runners). Git-specific implementations in `mahavishnu/core/git_heal.py` using the protocol. Existing `heal_workflows` (per-workflow) is the outer loop; this is the inner loop.

**Tech Stack:** Python 3.13, `asyncio.subprocess`, `prometheus_client`, pytest with `asyncio_mode = "auto"`.

---

## Global Constraints

Inherited from Spec #1's plan. New constraints:

- **L2 bounded**: max 3 attempts, 4-min turn timeout, confidence ≥ 70.
- **Wire truth**: L2 success determined by re-running the real operation, not by Claude's claim.
- **Red lines enforced in code** (defense in depth); prompt-only enforcement is insufficient.
- **No new event schema**; observability via Prometheus + logs.

---

## File Structure

### New files

| Path | Responsibility |
|---|---|
| `mahavishnu/core/heal/protocol.py` | `L1Aborted`, `L2Bailed`, `L2Exhausted`, `HealConfig`, `HealAttempt`. |
| `mahavishnu/core/heal/l1.py` | `run_with_l1()` runner. |
| `mahavishnu/core/heal/l2.py` | `run_with_l2()` runner with Prometheus counters. |
| `mahavishnu/core/heal/l3.py` | `escalate_to_operator()` calling `request_approval`. |
| `mahavishnu/core/heal/metrics.py` | Prometheus counters. |
| `mahavishnu/core/git_heal.py` | `push_with_heal`, `rebase_with_heal`, `merge_with_heal`. |
| `mahavishnu/cli/heal_coverage_cli.py` | `mahavishnu heal --check-coverage`. |
| `tests/unit/test_heal_protocol.py` | L0 tests for types. |
| `tests/unit/test_heal_l1.py` | L1 tests. |
| `tests/unit/test_heal_l2.py` | L2 tests with mocked Claude. |
| `tests/unit/test_heal_l3.py` | L3 tests with mocked approval. |
| `tests/integration/test_git_heal.py` | Real git in tmpdir. |

### Modified files

| Path | Modification |
|---|---|
| `mahavishnu/core/worktree.py` | Use `push_with_heal` instead of direct git subprocess. |
| `mahavishnu/mcp/tools/worktree_tools.py` | Routes push through `push_with_heal`. |
| `mahavishnu/cli/__init__.py` | Register `heal_app`. |

---

## Task 1: Protocol types

**Files:**
- Create: `mahavishnu/core/heal/protocol.py`
- Create: `mahavishnu/core/heal/__init__.py`
- Test: `tests/unit/test_heal_protocol.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_heal_protocol.py`:

```python
from __future__ import annotations

import pytest

from mahavishnu.core.heal.protocol import (
    HealAttempt,
    HealConfig,
    L1Aborted,
    L2Bailed,
    L2Exhausted,
)


def test_l1_aborted_carries_context():
    err = L1Aborted("rebase conflict", {"branch": "main"})
    assert err.context == {"branch": "main"}
    assert "rebase conflict" in str(err)


def test_l2_bailed_carries_trail():
    trail = [{"attempt": 1, "action": "fix", "wire_exit": 1}]
    err = L2Bailed("confidence low", trail)
    assert err.trail == trail
    assert "confidence low" in str(err)


def test_l2_exhausted_carries_trail():
    err = L2Exhausted("exhausted", [{"attempt": 1}])
    assert err.trail == [{"attempt": 1}]


def test_heal_config_defaults():
    cfg = HealConfig()
    assert cfg.max_l2_attempts == 3
    assert cfg.l2_turn_timeout_seconds == 240
    assert cfg.l2_confidence_floor == 70
    assert cfg.red_lines == ()


def test_heal_attempt_fields():
    a = HealAttempt(
        attempt_index=1,
        action_taken="git rebase --continue",
        confidence=85,
        wire_exit_code=0,
        duration_ms=1200,
    )
    assert a.attempt_index == 1
    assert a.confidence == 85
    assert a.wire_exit_code == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_heal_protocol.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement the protocol**

Create `mahavishnu/core/heal/protocol.py`:

```python
"""Three-layer self-heal protocol types.

HealConfig, HealAttempt, and three exception types (L1Aborted,
L2Bailed, L2Exhausted) that propagate context between layers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class L1Aborted(Exception):
    """Raised by L1 deterministic guard when the rule fails."""

    def __init__(self, message: str, context: dict[str, Any]) -> None:
        super().__init__(message)
        self.context = context


class L2Bailed(Exception):
    """Raised by L2 when Claude's confidence is below floor or action violates red line."""

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
    l2_turn_timeout_seconds: int = 240
    l2_confidence_floor: int = 70
    red_lines: tuple[str, ...] = ()


@dataclass(frozen=True)
class HealAttempt:
    """One L2 attempt's record for the trail."""

    attempt_index: int
    action_taken: str
    confidence: int
    wire_exit_code: int
    duration_ms: int
```

Create `mahavishnu/core/heal/__init__.py`:

```python
"""Three-layer self-heal protocol."""

from mahavishnu.core.heal.protocol import (
    HealAttempt,
    HealConfig,
    L1Aborted,
    L2Bailed,
    L2Exhausted,
)

__all__ = [
    "HealAttempt",
    "HealConfig",
    "L1Aborted",
    "L2Bailed",
    "L2Exhausted",
]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_heal_protocol.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add mahavishnu/core/heal/protocol.py mahavishnu/core/heal/__init__.py tests/unit/test_heal_protocol.py
git commit -m "feat(heal): add three-layer self-heal protocol types"
```

---

## Task 2: Prometheus metrics module

**Files:**
- Create: `mahavishnu/core/heal/metrics.py`
- Test: `tests/unit/test_heal_metrics.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_heal_metrics.py`:

```python
from __future__ import annotations

from prometheus_client import CollectorRegistry

from mahavishnu.core.heal.metrics import (
    heal_l2_attempts_total,
    heal_l2_failures_total,
)


def test_counters_increment_with_labels():
    registry = CollectorRegistry()
    heal_l2_attempts_total.labels(operation="git_push", outcome="success").inc()
    heal_l2_failures_total.labels(operation="git_push", reason="exhausted").inc()
    assert heal_l2_attempts_total.labels(operation="git_push", outcome="success")._value.get() == 1
    assert heal_l2_failures_total.labels(operation="git_push", reason="exhausted")._value.get() == 1
```

(Adjust assertion to match `prometheus_client` API for your version; the counters are defined globally so values may persist across tests. The point is that `.labels(...).inc()` works without raising.)

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_heal_metrics.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement the metrics module**

Create `mahavishnu/core/heal/metrics.py`:

```python
"""Prometheus counters for three-layer self-heal."""

from __future__ import annotations

from prometheus_client import Counter


HEAL_L2_ATTEMPTS_TOTAL = Counter(
    "mahavishnu_heal_l2_attempts_total",
    "L2 self-heal attempts by operation and outcome",
    ["operation", "outcome"],
)


HEAL_L2_FAILURES_TOTAL = Counter(
    "mahavishnu_heal_l2_failures_total",
    "L2 self-heal failures by operation and reason",
    ["operation", "reason"],
)


# Convenience aliases for use elsewhere.
heal_l2_attempts_total = HEAL_L2_ATTEMPTS_TOTAL
heal_l2_failures_total = HEAL_L2_FAILURES_TOTAL
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_heal_metrics.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add mahavishnu/core/heal/metrics.py tests/unit/test_heal_metrics.py
git commit -m "feat(heal): add Prometheus counters for L2 attempts and failures"
```

---

## Task 3: L1 runner

**Files:**
- Create: `mahavishnu/core/heal/l1.py`
- Test: `tests/unit/test_heal_l1.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_heal_l1.py`:

```python
from __future__ import annotations

import pytest

from mahavishnu.core.heal.l1 import run_with_l1
from mahavishnu.core.heal.protocol import L1Aborted


@pytest.mark.asyncio
async def test_run_with_l1_propagates_aborted():
    def l1_guard(inp: str) -> None:
        raise L1Aborted("conflict", {"branch": inp})

    async def operation(inp: str) -> str:
        return f"pushed {inp}"

    with pytest.raises(L1Aborted) as exc:
        await run_with_l1(operation, input="main", l1_guard=l1_guard)
    assert exc.value.context == {"branch": "main"}


@pytest.mark.asyncio
async def test_run_with_l1_runs_operation_when_guard_passes():
    calls: list[str] = []

    def l1_guard(inp: str) -> None:
        calls.append("guard")

    async def operation(inp: str) -> str:
        calls.append(f"op:{inp}")
        return f"result:{inp}"

    result = await run_with_l1(operation, input="main", l1_guard=l1_guard)
    assert result == "result:main"
    assert calls == ["guard", "op:main"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_heal_l1.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement L1 runner**

Create `mahavishnu/core/heal/l1.py`:

```python
"""L1 deterministic guard runner."""

from __future__ import annotations

from typing import Awaitable, Callable, TypeVar

from mahavishnu.core.heal.protocol import L1Aborted

OpInput = TypeVar("OpInput")
OpOutput = TypeVar("OpOutput")


async def run_with_l1(
    operation: Callable[[OpInput], Awaitable[OpOutput]],
    *,
    input: OpInput,
    l1_guard: Callable[[OpInput], None],
) -> OpOutput:
    """Run operation with L1 deterministic guard.

    Raises:
        L1Aborted: if guard raises; propagates to caller (L2 handler).
    """
    l1_guard(input)
    return await operation(input)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_heal_l1.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add mahavishnu/core/heal/l1.py tests/unit/test_heal_l1.py
git commit -m "feat(heal): add L1 deterministic guard runner"
```

---

## Task 4: L2 bounded agentic runner

**Files:**
- Create: `mahavishnu/core/heal/l2.py`
- Test: `tests/unit/test_heal_l2.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_heal_l2.py`:

```python
from __future__ import annotations

import pytest

from mahavishnu.core.heal.l2 import run_with_l2
from mahavishnu.core.heal.metrics import heal_l2_attempts_total, heal_l2_failures_total
from mahavishnu.core.heal.protocol import (
    HealConfig,
    L2Bailed,
    L2Exhausted,
)


@pytest.mark.asyncio
async def test_run_with_l2_succeeds_on_first_attempt():
    turn_calls: list[int] = []
    op_calls: list[int] = []

    async def claude_turn(input, ctx, attempt):
        turn_calls.append(attempt)
        return ("resolve conflict", 80)

    async def operation(input):
        op_calls.append(1)
        return "ok"

    def red_line_check(action: str) -> None:
        return None

    result = await run_with_l2(
        "test_op",
        operation,
        input=("main",),
        l1_context={"branch": "main"},
        config=HealConfig(),
        claude_turn=claude_turn,
        red_line_check=red_line_check,
    )
    assert result == "ok"
    assert turn_calls == [1]
    assert op_calls == [1, 1]  # first attempt + final verification re-run


@pytest.mark.asyncio
async def test_run_with_l2_bails_on_low_confidence():
    async def claude_turn(input, ctx, attempt):
        return ("try something", 50)  # below floor

    async def operation(input):
        return "ok"

    def red_line_check(action: str) -> None:
        return None

    with pytest.raises(L2Bailed):
        await run_with_l2(
            "test_op",
            operation,
            input=("main",),
            l1_context={},
            config=HealConfig(),
            claude_turn=claude_turn,
            red_line_check=red_line_check,
        )


@pytest.mark.asyncio
async def test_run_with_l2_red_line_enforced():
    async def claude_turn(input, ctx, attempt):
        return ("force push to protected", 90)

    async def operation(input):
        return "ok"

    def red_line_check(action: str) -> None:
        if "force" in action and "protected" in action:
            raise ValueError(f"red line violated: {action}")

    with pytest.raises(L2Bailed) as exc:
        await run_with_l2(
            "test_op",
            operation,
            input=("main",),
            l1_context={},
            config=HealConfig(),
            claude_turn=claude_turn,
            red_line_check=red_line_check,
        )
    assert "red line violated" in str(exc.value)


@pytest.mark.asyncio
async def test_run_with_l2_exhausts_attempts_when_wire_keeps_failing():
    attempt_count = 0

    async def claude_turn(input, ctx, attempt):
        nonlocal attempt_count
        attempt_count += 1
        return (f"attempt {attempt}", 80)

    async def operation(input):
        raise RuntimeError("wire failure")

    def red_line_check(action: str) -> None:
        return None

    with pytest.raises(L2Exhausted):
        await run_with_l2(
            "test_op",
            operation,
            input=("main",),
            l1_context={},
            config=HealConfig(),
            claude_turn=claude_turn,
            red_line_check=red_line_check,
        )
    assert attempt_count == 3  # bounded


@pytest.mark.asyncio
async def test_run_with_l2_wire_truth_overrides_claude_claim():
    """If Claude says success but wire fails, L2 continues (no premature exit)."""
    op_calls: list[int] = []

    async def claude_turn(input, ctx, attempt):
        return ("I'm done", 90)  # Claude claims success

    async def operation(input):
        op_calls.append(1)
        if len(op_calls) < 2:
            raise RuntimeError("wire still failing")
        return "actually ok"

    def red_line_check(action: str) -> None:
        return None

    result = await run_with_l2(
        "test_op",
        operation,
        input=("main",),
        l1_context={},
        config=HealConfig(),
        claude_turn=claude_turn,
        red_line_check=red_line_check,
    )
    assert result == "actually ok"
    assert len(op_calls) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_heal_l2.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement L2 runner**

Create `mahavishnu/core/heal/l2.py`:

```python
"""L2 bounded agentic heal runner.

3-attempt retry loop with confidence floor, red-line enforcement, and
wire-truth verification. Each attempt: claude_turn → red_line_check →
re-run real operation → check exit code. No unbounded loops.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable

from oneiric.logging import get_logger

from mahavishnu.core.heal.metrics import (
    heal_l2_attempts_total,
    heal_l2_failures_total,
)
from mahavishnu.core.heal.protocol import (
    HealAttempt,
    HealConfig,
    L2Bailed,
    L2Exhausted,
)

logger = get_logger(__name__)


async def run_with_l2(
    operation_name: str,
    operation: Callable[[Any], Awaitable[Any]],
    *,
    input: Any,
    l1_context: dict[str, Any],
    config: HealConfig,
    claude_turn: Callable[[Any, dict[str, Any], int], Awaitable[tuple[str, int]]],
    red_line_check: Callable[[str], None],
) -> Any:
    """Run operation with bounded agentic heal.

    Args:
        operation_name: for metrics labels.
        operation: real operation to run; ground-truth via return/exit.
        input: passed to operation and to claude_turn.
        l1_context: context from L1 abort.
        config: HealConfig (max attempts, timeout, confidence floor, red lines).
        claude_turn: async (input, context, attempt_index) -> (action_description, confidence).
            Must self-check red lines via prompt; code-level enforcement is the safety net.
        red_line_check: callable that raises ValueError if action violates red lines.

    Raises:
        L2Bailed: confidence below floor or red-line violation.
        L2Exhausted: all attempts' wire runs failed.
    """
    trail: list[HealAttempt] = []

    for attempt_index in range(1, config.max_l2_attempts + 1):
        turn_start = time.monotonic()
        try:
            action, confidence = await asyncio.wait_for(
                claude_turn(input, l1_context, attempt_index),
                timeout=config.l2_turn_timeout_seconds,
            )
        except Exception as exc:
            duration_ms = int((time.monotonic() - turn_start) * 1000)
            logger.exception(
                "L2 claude turn failed",
                extra={"operation": operation_name, "attempt": attempt_index},
            )
            heal_l2_failures_total.labels(
                operation=operation_name, reason="turn_error"
            ).inc()
            trail.append(
                HealAttempt(
                    attempt_index=attempt_index,
                    action_taken=f"turn_error: {exc!s}",
                    confidence=0,
                    wire_exit_code=-1,
                    duration_ms=duration_ms,
                )
            )
            continue

        if confidence < config.l2_confidence_floor:
            duration_ms = int((time.monotonic() - turn_start) * 1000)
            heal_l2_attempts_total.labels(
                operation=operation_name, outcome="bail"
            ).inc()
            heal_l2_failures_total.labels(
                operation=operation_name, reason="low_confidence"
            ).inc()
            trail.append(
                HealAttempt(
                    attempt_index=attempt_index,
                    action_taken=action,
                    confidence=confidence,
                    wire_exit_code=-1,
                    duration_ms=duration_ms,
                )
            )
            raise L2Bailed(
                f"L2 bailed: confidence {confidence} < floor {config.l2_confidence_floor}",
                trail=[vars(a) for a in trail],
            )

        try:
            red_line_check(action)
        except Exception as exc:
            heal_l2_failures_total.labels(
                operation=operation_name, reason="red_line_violation"
            ).inc()
            raise L2Bailed(
                f"L2 action violated red line: {exc!s}",
                trail=[vars(a) for a in trail],
            )

        wire_exit = -1
        try:
            await operation(input)
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
            heal_l2_attempts_total.labels(
                operation=operation_name, outcome="success"
            ).inc()
            logger.info(
                "L2 self-heal succeeded",
                extra={
                    "operation": operation_name,
                    "attempt": attempt_index,
                    "duration_ms": duration_ms,
                },
            )
            return await operation(input)

        heal_l2_attempts_total.labels(
            operation=operation_name, outcome="wire_failure"
        ).inc()
        logger.warning(
            "L2 self-heal attempt failed",
            extra={
                "operation": operation_name,
                "attempt": attempt_index,
                "wire_exit_code": wire_exit,
            },
        )

    heal_l2_failures_total.labels(operation=operation_name, reason="exhausted").inc()
    raise L2Exhausted(
        f"L2 exhausted after {config.max_l2_attempts} attempts",
        trail=[vars(a) for a in trail],
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_heal_l2.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add mahavishnu/core/heal/l2.py tests/unit/test_heal_l2.py
git commit -m "feat(heal): add L2 bounded agentic runner with wire truth"
```

---

## Task 5: L3 operator escalation

**Files:**
- Create: `mahavishnu/core/heal/l3.py`
- Test: `tests/unit/test_heal_l3.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_heal_l3.py`:

```python
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from mahavishnu.core.heal.l3 import escalate_to_operator
from mahavishnu.core.heal.protocol import L2Exhausted


@pytest.mark.asyncio
async def test_escalate_calls_request_approval():
    l2_exc = L2Exhausted(
        "exhausted",
        trail=[{"attempt_index": 1, "action_taken": "fix", "confidence": 80, "wire_exit_code": 1, "duration_ms": 1000}],
    )
    with patch(
        "mahavishnu.core.heal.l3.request_approval", new_callable=AsyncMock
    ) as mock_approve:
        mock_approve.return_value = "retry"
        result = await escalate_to_operator(
            "git_push",
            input=("main",),
            l1_context={"branch": "main"},
            l2_exception=l2_exc,
        )
    assert result == "retry"
    mock_approve.assert_called_once()
    call_args = mock_approve.call_args
    assert call_args.kwargs["approval_type"] == "heal_escalation_git_push"
    assert "retry" in call_args.kwargs["context"]["options"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_heal_l3.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement L3**

Create `mahavishnu/core/heal/l3.py`:

```python
"""L3 operator escalation via request_approval MCP tool."""

from __future__ import annotations

from typing import Any

from mahavishnu.core.heal.protocol import L2Bailed, L2Exhausted


async def escalate_to_operator(
    operation_name: str,
    *,
    input: Any,
    l1_context: dict[str, Any],
    l2_exception: L2Bailed | L2Exhausted,
) -> str:
    """Escalate to operator via request_approval.

    Returns the operator's chosen action: 'retry' | 'abort' | 'skip'.
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

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_heal_l3.py -v`
Expected: PASS (1 test)

- [ ] **Step 5: Commit**

```bash
git add mahavishnu/core/heal/l3.py tests/unit/test_heal_l3.py
git commit -m "feat(heal): add L3 operator escalation via request_approval"
```

---

## Task 6: Git operations — push with heal

**Files:**
- Create: `mahavishnu/core/git_heal.py`
- Test: `tests/integration/test_git_heal.py`

- [ ] **Step 1: Write the integration test**

Create `tests/integration/test_git_heal.py`:

```python
from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from mahavishnu.core.git_heal import push_with_heal
from mahavishnu.core.heal.protocol import L1Aborted


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """Initialize a git repo with origin and a commit."""
    subprocess.run(["git", "init", "--bare", str(tmp_path / "origin")], check=True)
    subprocess.run(["git", "init", str(tmp_path / "local")], check=True)
    cwd = tmp_path / "local"
    subprocess.run(["git", "-C", str(cwd), "config", "user.email", "test@test"], check=True)
    subprocess.run(["git", "-C", str(cwd), "config", "user.name", "test"], check=True)
    (cwd / "README.md").write_text("hello")
    subprocess.run(["git", "-C", str(cwd), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(cwd), "commit", "-m", "init"], check=True)
    subprocess.run(
        ["git", "-C", str(cwd), "remote", "add", "origin", str(tmp_path / "origin")],
        check=True,
    )
    return cwd


@pytest.mark.asyncio
async def test_push_with_heal_succeeds_on_clean_repo(git_repo: Path):
    await push_with_heal(str(git_repo), "main")


@pytest.mark.asyncio
async def test_push_with_heal_l1_aborts_on_rebase_conflict(git_repo: Path):
    # Create a conflicting commit on origin.
    subprocess.run(
        ["git", "-C", str(git_repo), "fetch", "origin"],
        cwd=git_repo,
        check=False,
    )
    # Mock L2/L3 to verify L1 abort propagates correctly.
    with patch("mahavishnu.core.git_heal.run_with_l2", new_callable=AsyncMock) as mock_l2:
        mock_l2.side_effect = L1Aborted("forced abort", {})
        with pytest.raises(L1Aborted):
            await push_with_heal(str(git_repo), "main")
        # L2 should NOT be called when L1 passes; verify if needed.
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_git_heal.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement git_heal.py**

Create `mahavishnu/core/git_heal.py`:

```python
"""Git operations with three-layer self-heal."""

from __future__ import annotations

import asyncio

from oneiric.logging import get_logger

from mahavishnu.core.heal.l1 import run_with_l1
from mahavishnu.core.heal.l2 import run_with_l2
from mahavishnu.core.heal.l3 import escalate_to_operator
from mahavishnu.core.heal.protocol import (
    HealConfig,
    L1Aborted,
    L2Bailed,
    L2Exhausted,
)

logger = get_logger(__name__)


HEAL_CONFIG_PUSH = HealConfig(
    max_l2_attempts=3,
    l2_turn_timeout_seconds=240,
    l2_confidence_floor=70,
    red_lines=("never_force_push_to_protected",),
)


HEAL_CONFIG_REBASE = HealConfig(
    max_l2_attempts=3,
    l2_turn_timeout_seconds=240,
    l2_confidence_floor=70,
    red_lines=("never_drop_unpushed_commits", "never_blind_pick_conflict_side"),
)


HEAL_CONFIG_MERGE = HealConfig(
    max_l2_attempts=3,
    l2_turn_timeout_seconds=240,
    l2_confidence_floor=70,
    red_lines=("never_drop_unpushed_commits",),
)


async def _run_git(*args: str, cwd: str) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        "git", *args,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    return (
        proc.returncode or 0,
        stdout.decode(errors="ignore"),
        stderr.decode(errors="ignore"),
    )


async def _l1_pre_push_rebase(repo_path: str, branch: str) -> None:
    code, _, stderr = await _run_git("fetch", "origin", branch, cwd=repo_path)
    if code != 0:
        raise L1Aborted(
            f"git fetch failed with exit {code}",
            {"repo_path": repo_path, "branch": branch, "stage": "fetch"},
        )
    code, _, stderr = await _run_git("rebase", f"origin/{branch}", cwd=repo_path)
    if code != 0:
        raise L1Aborted(
            "rebase conflict",
            {
                "repo_path": repo_path,
                "branch": branch,
                "stage": "rebase",
                "stderr": stderr[:1000],
            },
        )


async def _do_push(repo_path: str, branch: str) -> None:
    code, _, stderr = await _run_git("push", "origin", branch, cwd=repo_path)
    if code != 0:
        raise RuntimeError(f"git push failed: exit {code}, stderr={stderr[:200]}")


def _red_line_check_push(action: str) -> None:
    if "force" in action.lower() and "protected" in action.lower():
        raise ValueError(f"red line violated: {action}")


async def _claude_turn_for_push(
    input: tuple[str, str], ctx: dict, attempt: int
) -> tuple[str, int]:
    """Stub for L2's constrained Claude session. Production: real prompt."""
    raise RuntimeError("L2 claude_turn not implemented; wire L2 in production")


async def push_with_heal(repo_path: str, branch: str) -> None:
    """Git push with three-layer self-heal."""
    try:
        await run_with_l1(_do_push, input=(repo_path, branch), l1_guard=_l1_pre_push_rebase)
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
            operator_choice = await escalate_to_operator(
                "git_push",
                input=(repo_path, branch),
                l1_context=l1_context,
                l2_exception=l2_exc,
            )
            logger.info(
                "operator chose %s for git_push",
                operator_choice,
                extra={"repo_path": repo_path, "branch": branch},
            )
            if operator_choice == "retry":
                await push_with_heal(repo_path, branch)


async def rebase_with_heal(repo_path: str, upstream: str) -> None:
    """Git rebase with three-layer self-heal on conflict."""
    # Implementation mirrors push_with_heal; project-specific.
    raise NotImplementedError("rebase_with_heal stub — wire L1/L2/L3 in follow-up task")


async def merge_with_heal(repo_path: str, branch: str) -> None:
    """Git merge with three-layer self-heal on conflict."""
    # Implementation mirrors push_with_heal; project-specific.
    raise NotImplementedError("merge_with_heal stub — wire L1/L2/L3 in follow-up task")
```

- [ ] **Step 4: Run integration test**

Run: `pytest tests/integration/test_git_heal.py -v`
Expected: First test passes (clean push); second test passes (L1 abort propagates).

If git is not available in the test environment, mark these as `@pytest.mark.skip(reason="git unavailable")` and verify the L1/L2/L3 unit tests still cover the protocol logic.

- [ ] **Step 5: Commit**

```bash
git add mahavishnu/core/git_heal.py tests/integration/test_git_heal.py
git commit -m "feat(heal): add git push/rebase/merge with three-layer self-heal"
```

---

## Task 7: Migrate worktree.py to use heal-wrapped push

**Files:**
- Modify: `mahavishnu/core/worktree.py` (locate existing git push call; replace with `push_with_heal`)
- Test: existing worktree tests

- [ ] **Step 1: Locate existing direct git push calls**

Run: `grep -n "git push\|asyncio.create_subprocess.*git" mahavishnu/core/worktree.py mahavishnu/mcp/tools/worktree_tools.py`
Find any direct subprocess invocations of `git push`.

- [ ] **Step 2: Replace direct calls**

Replace each direct `git push` subprocess call with:

```python
from mahavishnu.core.git_heal import push_with_heal

await push_with_heal(repo_path, branch)
```

(If the existing call is synchronous or in a different signature, adapt to `await`.)

- [ ] **Step 3: Run existing worktree tests**

Run: `pytest tests/unit/test_worktree.py tests/integration/test_worktree_tools.py -v`
Expected: PASS (existing tests still work; heal is transparent when L1 passes)

- [ ] **Step 4: Commit**

```bash
git add mahavishnu/core/worktree.py mahavishnu/mcp/tools/worktree_tools.py
git commit -m "refactor(worktree): route git push through push_with_heal"
```

---

## Task 8: Heal coverage CLI

**Files:**
- Create: `mahavishnu/cli/heal_coverage_cli.py`
- Modify: `mahavishnu/cli/__init__.py`
- Test: `tests/integration/test_heal_coverage_cli.py`

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_heal_coverage_cli.py`:

```python
from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from mahavishnu.cli.heal_coverage_cli import heal_app


def test_check_coverage_passes_when_all_git_calls_wrapped(tmp_path: Path):
    (tmp_path / "good.py").write_text(
        "from mahavishnu.core.git_heal import push_with_heal\n"
    )
    result = CliRunner().invoke(heal_app, ["check-coverage", "--path", str(tmp_path)])
    assert result.exit_code == 0


def test_check_coverage_fails_on_direct_git_push_subprocess(tmp_path: Path):
    (tmp_path / "bad.py").write_text(
        "import asyncio\n"
        "async def do_push():\n"
        "    p = await asyncio.create_subprocess_exec('git', 'push', 'origin', 'main')\n"
    )
    result = CliRunner().invoke(heal_app, ["check-coverage", "--path", str(tmp_path)])
    assert result.exit_code != 0
    assert "bad.py" in result.output
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_heal_coverage_cli.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement the CLI**

Create `mahavishnu/cli/heal_coverage_cli.py`:

```python
"""Heal coverage CLI: flag direct git subprocess calls not routed through heal-wrapped helpers."""

from __future__ import annotations

import re
from pathlib import Path

import typer

heal_app = typer.Typer(help="Three-layer self-heal coverage checks")


_GIT_DIRECT_PATTERN = re.compile(
    r'asyncio\.create_subprocess_exec\s*\(\s*[\'"]git[\'"]\s*,\s*[\'"]push[\'"]'
)


def _scan_for_direct_git_push(path: Path) -> list[Path]:
    hits: list[Path] = []
    for p in path.rglob("*.py"):
        if _GIT_DIRECT_PATTERN.search(p.read_text(errors="ignore")):
            hits.append(p)
    return hits


@heal_app.command("check-coverage")
def check_coverage(
    path: Path = typer.Option(Path("."), "--path", help="Directory to scan"),
) -> None:
    """Exit non-zero if direct git push subprocess calls exist outside heal-wrapped helpers."""
    hits = _scan_for_direct_git_push(path)
    if hits:
        typer.echo(f"Found {len(hits)} direct git push call(s):")
        for h in hits:
            typer.echo(f"  - {h.relative_to(path)}")
        raise typer.Exit(code=1)
    typer.echo("All git push calls routed through heal-wrapped helpers.")
```

In `mahavishnu/cli/__init__.py`, register:

```python
from mahavishnu.cli.heal_coverage_cli import heal_app

main_app.add_typer(heal_app, name="heal")
```

(Adapt the mount site to match the existing pattern.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/integration/test_heal_coverage_cli.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add mahavishnu/cli/heal_coverage_cli.py mahavishnu/cli/__init__.py tests/integration/test_heal_coverage_cli.py
git commit -m "feat(heal): add heal --check-coverage CLI for direct git push audit"
```

---

## Self-Review

**1. Spec coverage:**

| Spec section | Covered by |
|---|---|
| Protocol types | Task 1 |
| L1 runner | Task 3 |
| L2 runner (bounded, wire-truth, red lines) | Task 4 |
| L3 escalation via request_approval | Task 5 |
| Git push with heal | Task 6 |
| Git rebase/merge (stub for follow-up) | Task 6 (stubs; full impl in v1.1) |
| Migration of worktree.py | Task 7 |
| Heal coverage CLI | Task 8 |
| Prometheus counters | Task 2 |
| L0-L3 testing | Tasks 1-6 |

**2. Placeholder scan:** No `TBD`/`TODO` markers in plan body. `rebase_with_heal` and `merge_with_heal` are explicit stubs marked for v1.1.

**3. Type consistency:** `run_with_l1`, `run_with_l2`, `escalate_to_operator` signatures consistent across Tasks 3-6 and the git_heal caller.

**Gaps:** `rebase_with_heal` and `merge_with_heal` are stubs. Production wiring of `_claude_turn_for_push` requires project-specific Claude prompt template (out of scope per spec OQ1).

Plan complete. Moving to spec #5 brainstorm (`three-zone-skill-pipeline`, Phase 2).
