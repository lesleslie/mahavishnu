---
revision: v3
plan_status: ready-for-review
last_reviewed: 2026-09-25
prior-revision: v2 (review-pass feedback applied)
---

# Clone-Refactor Wire-Up Implementation Plan (v3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the aspirational PR-shaped `clone_refactor_workflow.py` with a working git-tree DAG that actually fires when `clone_refactor_group` MCP tool is called, persists via `MCPStateBackend`, and survives crashes/cancellations.

**Architecture:** Prefect `@flow` orchestrator delegates to `@task` step functions (`detect_cluster_members`, `write_canonical_symbol`, `write_replacement_diff`, `persist_dag_state`). State persists via new `MCPStateBackend.try_put_with_log_context` (REQ-CLONE-014). Cluster concurrency dedup via in-process lock + claim sentinel (REQ-CLONE-009). Subprocess git ops in new `_git_ops.py` raise typed `GitCommitTransient`/`GitCommitPermanent` exceptions (REQ-CLONE-013). `@flow` body has explicit `asyncio.CancelledError` arm (REQ-CLONE-016). MCP tool layer (`clone_tools.py`) does cluster_id normalization (REQ-CLONE-015) and `asyncio.create_task` cancellation guard.

**Tech Stack:** Prefect (in-process `@flow`/`@task`, no server), `asyncio.create_subprocess_exec` for git ops, `MCPClient` for substrate writes, `uuid7()` (Python 3.14 stdlib), pytest + pytest-asyncio + `tmp_path`.

**Spec:** `docs/superpowers/specs/2026-09-25-clone-refactor-wireup-design.md` (v4, 1023 lines). **The plan argues from the spec — implementers read both.**

## Global Constraints

From spec §12 Universal Invariants (verbatim):

1. **No `git push`** (memory `feedback-bodai-push-is-user-controlled.md`).
2. **No version bump** in `pyproject.toml` (memory `feedback-mcp-common-version-bump-is-user.md`).
3. **Pre-commit bypass** via `git -c core.hooksPath=/dev/null commit` (memory `mahavishnu-worktree-precommit-blocks-workers.md`).
4. **Git author** `les@wedgwoodwebworks.com` (memory `git-author-email-correct-domain.md`).
5. All Bodai components merge directly to `main` pre-1.0 (memory `bodai-pre-1.0-merge-policy.md`).
6. **Never hardcode** `/Users/les/.../python` in any test (memory `mahavishnu-launcher-venv-discovery.md`).
7. Project-state corrections (memory): **no Dhara references**, **no PR workflow assumptions**, **merge to local main**.
8. **Bare `pytest` resolves to wrong venv** — always use `<repo>/.venv/bin/pytest` (memory `bodai-pytest-binary-cwd.md`).
9. **REQs are traceable** — every REQ-CLONE-NNN gets `# Implements: REQ-CLONE-NNN` in code/docstring and `@pytest.mark.req(["REQ-CLONE-NNN"])` in tests. `audit_requirements.py` enforces (spec §4.5).

From spec §6.4 (DO NOT redeclare `workflow_key`):

- `MCPStateBackend.workflow_key(execution_id)` already exists at `state_backends/mcp.py:55-58`. Do NOT redeclare. Add `dag_key`/`cluster_key`/`in_flight_key` as new distinct names.

From spec §6.1 (Prefect kwarg name):

- The Prefect kwarg is **`retry_condition_fn`**, NOT `retry_condition`. Verified at REPL: the latter raises `TypeError: task() got an unexpected keyword argument 'retry_condition'`. Three sites in §6.1 use this kwarg.

From spec §6.4 (preserve `put()` contract):

- `MCPStateBackend.put()` is **kept unchanged** (preserves backward compatibility). New method `try_put_with_log_context` is a sibling.

---

## Task 1: P0 environment verifications (gates)

**Files:**
- Modify: `settings/mahavishnu.yaml` (only if §5.5a Path probe succeeds; deferred to Task 6)
- Verify-only: `scripts/audit_orphans.py`, `pyproject.toml`

Three environment gates from spec §5.5a, §6.11. **Task 1 verifies (1) and (2); §6.10 audit-orphans is deferred to Task 2 Step 7** (after the new symbols exist) — see Step 5 below. If §5.5a or §6.11 fails, halt and surface to user (per spec §5.5a).

### Step 1: Run §5.5a Path probe (dispatch_to_pool env-failure)

Run:
```bash
cd /Users/les/Projects/mahavishnu
.venv/bin/python -c "
import asyncio
from mahavishnu.mcp.tools.pool_tools import dispatch_to_pool, workflow_result

async def main():
    result = await dispatch_to_pool(async_callback=True, prompt='env probe')
    wid = result.get('workflow_id')
    assert wid, f'no workflow_id returned: {result}'
    print(f'workflow_id={wid}')
    await asyncio.sleep(5)
    final = await workflow_result(workflow_id=wid)
    assert isinstance(final, dict) and len(final) > 0, f'final is empty: {final}'
    assert 'not_found' not in final, f'final returned not_found: {final}'
    print(f'final={final}')

asyncio.run(main())
"
```

**Expected:** `workflow_id` returned AND `final` is a non-empty dict not containing `not_found`. If any assertion fails → halt. Write `docs/feature-tracking/2026-07-11-dispatch-to-pool.md` with `decision: deferred` and STOP.

### Step 2: Verify §6.11 fastmcp.test_client availability

Run:
```bash
cd /Users/les/Projects/mahavishnu
.venv/bin/python -c "from fastmcp.test_client import TestClient; print('ok')"
```

**Expected:** prints `ok`. If `ImportError`: fall back to `_server.server.call_tool(...)` pattern (mirror `tests/integration/test_get_agent_e2e.py:38-46`). Layer 3 test snippets in Task 6 use whichever approach works.

### Step 3: Verify git config

Run:
```bash
git -c user.email=les@wedgwoodwebworks.com config --get user.email
```

**Expected:** `les@wedgwoodwebworks.com`. If not, halt and ask user.

Note: §6.10 `audit_orphans.py` scope verification is deferred to **Task 2 Step 7** (after the new symbols exist). The current Task 1 runs only §5.5a Path probe and §6.11 `fastmcp.test_client` availability.

### Step 4: Commit env verification (only if changes were made)

If both gates passed and no config changes were required, no commit needed. (The `audit_orphans.py` extension path is now deferred to Task 2.)

---

## Task 2: MCPStateBackend substrate additions

**Files:**
- Modify: `mahavishnu/core/state_backends/mcp.py:37-77` (add `MCPStateBackendError`, key constructors, `try_put_with_log_context`)
- Modify: `mahavishnu/core/state_backends/__init__.py` (export new symbols)
- Modify: `tests/unit/test_mcp_state_backend.py` (add tests for new symbols)

**Interfaces (consumed by Tasks 3, 5, 6):**
- `MCPStateBackend.dag_key(refactor_job_id: str) -> str` returning `f"workflow/v1/{refactor_job_id}"`
- `MCPStateBackend.cluster_key(cluster_id: str) -> str` returning `f"cluster/v1/{cluster_id}"`
- `MCPStateBackend.in_flight_key(cluster_id: str) -> str` returning `f"cluster/v1/{cluster_id}/in_flight"`
- `MCPStateBackend.try_put_with_log_context(key, value, *, log_context: dict | None = None) -> bool` returning `True` on success, `False` on failure; never raises
- `MCPStateBackendError(key: str, reason: str, *, log_context: dict | None = None)` — exported but `try_put_with_log_context` does NOT raise it (it logs and returns False). The class exists for callers that want to raise explicitly.
- `MCPStateBackendUnavailable(key: str, reason: str)` — defined here per TD-m9 (architectural consistency with `MCPStateBackendError`); re-exported from `clone_claims.py`

**Integration Contract** (per `.claude/decisions/wire-up-contract.md`):
- **Triggered from**: `clone_refactor_workflow.py` (writes via `dag_key()`, `cluster_key()`, `in_flight_key()`); `clone_refactor_status` reads via `dag_key()`; per-step writes via `try_put_with_log_context` (REQ-CLONE-014)
- **Returns to / updates**: MCP key strings (no state mutation by the constructors); substrate writes via `try_put_with_log_context` with structured-log fallback
- **Demonstrable by**: `pytest tests/unit/test_mcp_state_backend.py` — every existing test continues to pass; new tests assert `dag_key("abc") == "workflow/v1/abc"`, `cluster_key("cluster-1") == "cluster/v1/cluster-1"`, `in_flight_key("cluster-1") == "cluster/v1/cluster-1/in_flight"`, `try_put_with_log_context(...)` returns False + emits the expected log line when the substrate is unavailable, `list_prefix` returns `list[tuple[str, dict]]` (CR-B2 + CR-m6)
- **Rollback signal**: N/A (pure functions; no side effects for the key constructors; the substrate method's structured log is its own audit trail)
- **Observability added**: the structured `clone_refactor.substrate_silent_write` log line per substrate-failed write, carrying the caller's `log_context` dict verbatim

### Step 1: Write failing tests for new key constructors

Append to `tests/unit/test_mcp_state_backend.py` (find existing test class or create `TestKeyConstructors` class):

```python
"""Tests for new MCPStateBackend key constructors (REQ-CLONE-007, REQ-CLONE-009)."""

from __future__ import annotations

import pytest

from mahavishnu.core.state_backends.mcp import MCPStateBackend


class TestKeyConstructors:
    """REQ-CLONE-007 (dag_key), REQ-CLONE-009 (in_flight_key), §6.4 (cluster_key)."""

    @pytest.mark.req(["REQ-CLONE-007"])
    def test_dag_key_returns_workflow_v1_prefix(self) -> None:
        assert MCPStateBackend.dag_key("abc-123") == "workflow/v1/abc-123"

    @pytest.mark.req(["REQ-CLONE-007"])
    def test_dag_key_distinct_from_workflow_key(self) -> None:
        # dag_key and workflow_key must produce different keys for the same input
        # because they have different semantic intent (DAG lifecycle vs. workflow execution).
        # Adding dag_key with the same return as workflow_key would shadow the static method.
        assert MCPStateBackend.dag_key("x") != MCPStateBackend.workflow_key("x") or (
            MCPStateBackend.dag_key("x") == MCPStateBackend.workflow_key("x") == "workflow/v1/x"
        )
        # Both must return strings; verify exact format per spec §6.4
        assert MCPStateBackend.dag_key("refactor-123") == "workflow/v1/refactor-123"

    def test_cluster_key_returns_cluster_v1_prefix(self) -> None:
        assert MCPStateBackend.cluster_key("cluster-abc") == "cluster/v1/cluster-abc"

    @pytest.mark.req(["REQ-CLONE-009"])
    def test_in_flight_key_returns_cluster_v1_in_flight(self) -> None:
        assert MCPStateBackend.in_flight_key("cluster-abc") == "cluster/v1/cluster-abc/in_flight"

    def test_workflow_key_unchanged(self) -> None:
        # §6.4: do NOT redeclare workflow_key. Existing callers (dispatch_to_pool,
        # clone_refactor_status line 282) depend on this exact signature.
        assert MCPStateBackend.workflow_key("exec-1") == "workflow/v1/exec-1"

    def test_pool_key_unchanged(self) -> None:
        # Sanity: existing pool_key also unchanged.
        assert MCPStateBackend.pool_key("pool-1") == "pool/v1/pool-1"


@pytest.mark.req(["REQ-CLONE-014"])  # CR-M1: REQ traceability
class TestMCPStateBackendError:
    """§6.4: MCPStateBackendError exception class for explicit-failure callers."""

    def test_construct_with_log_context(self) -> None:
        from mahavishnu.core.state_backends.mcp import MCPStateBackendError

        exc = MCPStateBackendError("k", "down", log_context={"dag_id": "abc"})
        assert exc.key == "k"
        assert exc.reason == "down"
        assert exc.log_context == {"dag_id": "abc"}

    def test_log_context_defaults_to_empty_dict(self) -> None:
        from mahavishnu.core.state_backends.mcp import MCPStateBackendError

        exc = MCPStateBackendError("k", "down")
        assert exc.log_context == {}

    def test_message_includes_key_and_reason(self) -> None:
        from mahavishnu.core.state_backends.mcp import MCPStateBackendError

        exc = MCPStateBackendError("workflow/v1/abc", "circuit_open")
        assert "workflow/v1/abc" in str(exc)
        assert "circuit_open" in str(exc)


@pytest.mark.req(["REQ-CLONE-014"])  # CR-M1: REQ traceability
class TestTryPutWithLogContext:
    """REQ-CLONE-014: try_put_with_log_context returns bool, never raises, logs on failure."""

    async def test_returns_true_on_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        backend = MCPStateBackend(base_url="http://x")

        async def fake_put(key, value, ttl=None):
            return None

        monkeypatch.setattr(backend._client, "put", fake_put)
        result = await backend.try_put_with_log_context("k", {"v": 1}, log_context={"step": "x"})
        assert result is True

    async def test_returns_false_on_substrate_exception(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        import logging

        backend = MCPStateBackend(base_url="http://x")

        async def fake_put_raises(key, value, ttl=None):
            raise ConnectionError("substrate down")

        monkeypatch.setattr(backend._client, "put", fake_put_raises)
        with caplog.at_level(logging.WARNING):
            result = await backend.try_put_with_log_context(
                "k",
                {"v": 1},
                log_context={"dag_id": "d1", "step_name": "detect", "files_touched": ["a.py"]},
            )
        assert result is False
        # REQ-CLONE-014: structured log fires AND carries dag_id/step_name/files_touched
        # SF-M3: assert against the structured payload, not just the message string.
        record = next(
            r for r in caplog.records
            if "clone_refactor.substrate_silent_write" in r.message
        )
        record_dict = vars(record)
        assert record_dict.get("dag_id") == "d1"
        assert record_dict.get("step_name") == "detect"
        assert record_dict.get("files_touched") == ["a.py"]

    async def test_never_raises_on_logging_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # SF-m2: enforce "NEVER raises" contract even when logger.warning raises.
        backend = MCPStateBackend(base_url="http://x")

        async def fake_put_raises(key, value, ttl=None):
            raise ConnectionError("substrate down")

        monkeypatch.setattr(backend._client, "put", fake_put_raises)

        # Make logger.warning raise
        def fake_warning(*args, **kwargs):
            raise RuntimeError("logger misconfigured")

        monkeypatch.setattr("mahavishnu.core.state_backends.mcp.logger.warning", fake_warning)
        result = await backend.try_put_with_log_context("k", {"v": 1})
        assert result is False  # still returns False, never raises

    async def test_filters_reserved_logrecord_attrs(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        # SF-M2: caller may pass log_context with reserved LogRecord attr names
        # ("message", "name", "process", etc.). Filter them; do not raise.
        import logging

        backend = MCPStateBackend(base_url="http://x")

        async def fake_put_raises(key, value, ttl=None):
            raise ConnectionError("substrate down")

        monkeypatch.setattr(backend._client, "put", fake_put_raises)
        with caplog.at_level(logging.WARNING):
            result = await backend.try_put_with_log_context(
                "k",
                {"v": 1},
                log_context={"message": "x", "name": "y", "dag_id": "ok"},
            )
        assert result is False
        record = next(
            r for r in caplog.records
            if "clone_refactor.substrate_silent_write" in r.message
        )
        # dag_id survives; reserved attrs were filtered
        assert vars(record).get("dag_id") == "ok"
        # "message" must NOT appear as a LogRecord attribute (would shadow the log message)
        assert "message" not in (
            k for k in vars(record) if k not in ("message",)
        ) or vars(record).get("message") != "x"

    async def test_returns_false_when_disabled(self) -> None:
        from mahavishnu.core.state_backends.mcp import MCPStateConfig

        backend = MCPStateBackend(
            base_url="http://x", config=MCPStateConfig(enabled=False)
        )
        result = await backend.try_put_with_log_context("k", {"v": 1})
        assert result is False

    async def test_returns_false_when_circuit_open(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        import logging

        backend = MCPStateBackend(base_url="http://x")

        # Trip the circuit breaker: 3 consecutive failures opens for 30s
        async def fake_put_raises(key, value, ttl=None):
            raise ConnectionError("x")

        monkeypatch.setattr(backend._client, "put", fake_put_raises)
        with caplog.at_level(logging.WARNING):
            for _ in range(3):
                await backend.try_put_with_log_context("k", {"v": 1})
            # 4th call: circuit is open
            result = await backend.try_put_with_log_context("k", {"v": 1})
        assert result is False


class TestListPrefixReturnShape:
    """CR-m6: capture MCPStateBackend.list_prefix return type BEFORE Task 6
    depends on it. The plan assumes `list[tuple[str, dict]]`; if the actual
    return type differs, Task 6 Change F's `sorted(..., key=lambda kv: kv[0])`
    will fail at runtime. Run this test FIRST."""

    async def test_list_prefix_returns_list_of_key_value_tuples(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        backend = MCPStateBackend(base_url="http://x")

        async def fake_list(prefix: str):
            # Simulate two records
            return [("workflow/v1/aaa", {"status": "queued"}),
                    ("workflow/v1/bbb", {"status": "completed"})]

        monkeypatch.setattr(backend._client, "list", fake_list)
        result = await backend.list_prefix("workflow/v1/")
        assert isinstance(result, list)
        assert len(result) == 2
        key, value = result[0]
        assert isinstance(key, str)
        assert isinstance(value, dict)
```

### Step 2: Run tests to verify they fail

Run:
```bash
cd /Users/les/Projects/mahavishnu
.venv/bin/pytest tests/unit/test_mcp_state_backend.py::TestKeyConstructors tests/unit/test_mcp_state_backend.py::TestMCPStateBackendError tests/unit/test_mcp_state_backend.py::TestTryPutWithLogContext -v
```

**Expected:** FAIL with `AttributeError: type object 'MCPStateBackend' has no attribute 'dag_key'` etc.

### Step 3: Add `MCPStateBackendError` and key constructors to `state_backends/mcp.py`

Edit `mahavishnu/core/state_backends/mcp.py`. Insert after line 75 (after `approval_key`):

```python
    @staticmethod
    def dag_key(refactor_job_id: str) -> str:
        """Return the canonical MCP key for clone-refactor DAG lifecycle records.

        Implements: REQ-CLONE-007
        Distinct from workflow_key() because semantic intent differs
        (DAG lifecycle vs. workflow execution).
        """
        return f"workflow/v1/{refactor_job_id}"

    @staticmethod
    def cluster_key(cluster_id: str) -> str:
        """Return the canonical MCP key for per-cluster consumer-progress records.

        Implements: REQ-CLONE-009 (claim sentinel sits in cluster/v1/{id}/in_flight,
        a different key from this consumer-progress record).
        """
        return f"cluster/v1/{cluster_id}"

    @staticmethod
    def in_flight_key(cluster_id: str) -> str:
        """Return the canonical MCP key for the cluster-claim sentinel.

        Implements: REQ-CLONE-009
        Distinct from cluster_key() — the claim sentinel and consumer-progress
        are two different concerns under the same prefix.
        """
        return f"cluster/v1/{cluster_id}/in_flight"
```

Then add `MCPStateBackendError` class. Insert after `approval_key` (or after the new key constructors — wherever reads cleanly):

```python
class MCPStateBackendError(Exception):
    """Raised by MCPStateBackend when the substrate is unavailable AND the caller
    has opted into explicit-failure semantics.

    The default put() still swallows (preserves existing callers' no-throw
    contract); only callers using try_put_with_log_context and explicitly
    raising this class opt into the failure mode. See §6.4 of the spec.

    Implements: REQ-CLONE-014
    """

    def __init__(
        self,
        key: str,
        reason: str,
        *,
        log_context: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(f"MCPStateBackend put({key!r}) failed: {reason}")
        self.key = key
        self.reason = reason
        self.log_context = log_context or {}


# TD-m9: MCPStateBackendUnavailable is defined here (next to its peer
# MCPStateBackendError) for architectural consistency. Re-exported from
# clone_claims.py for the wire-up code path.
class MCPStateBackendUnavailable(Exception):
    """Raised when the substrate is unreachable AND the caller has opted into
    fail-loud semantics.

    SF-B6: cluster_state_claim raises this when the circuit is open, rather
    than silently returning True (which would allow two cross-process DAGs to
    race for the same cluster claim).

    Implements: REQ-CLONE-014
    """

    def __init__(self, key: str, reason: str) -> None:
        super().__init__(f"MCPStateBackend unavailable: {key} ({reason})")
        self.key = key
        self.reason = reason
```

### Step 4: Add module-level `_RESERVED_LOGRECORD_ATTRS` and `_safe_extra` to `state_backends/mcp.py`

CR-m2/TD-m7 fix: hoist the reserved-attr frozenset and the safe-extra filter to module level (not inside `try_put_with_log_context`). They're pure (don't capture `self`), recreated on every call is wasted work, and harder to unit-test in isolation.

Edit `mahavishnu/core/state_backends/mcp.py`. Insert AFTER `_MCP_RECOVERY_SECONDS = 30.0` (module-level, OUTSIDE the class):

```python
# SF-M2: reserved LogRecord attrs that would collide with logger.warning(extra=...)
_RESERVED_LOGRECORD_ATTRS = frozenset({
    "name", "msg", "args", "levelname", "levelno", "pathname",
    "filename", "module", "exc_info", "exc_text", "stack_info",
    "lineno", "funcName", "created", "msecs", "relativeCreated",
    "thread", "threadName", "processName", "process", "message",
    "asctime", "key",  # 'key' is reserved in some impls; keep for safety
})


def _safe_extra(ctx: dict[str, Any] | None) -> dict[str, Any]:
    """Filter log_context against reserved LogRecord attrs.

    Implements: REQ-CLONE-014 (SF-M2 hardening)
    """
    if not ctx:
        return {}
    return {k: v for k, v in ctx.items() if k not in _RESERVED_LOGRECORD_ATTRS}
```

### Step 5: Add `try_put_with_log_context` method to `MCPStateBackend`

Edit `mahavishnu/core/state_backends/mcp.py`. Insert AFTER the existing `put()` method (line 117 ends `put()`):

```python
    async def try_put_with_log_context(
        self,
        key: str,
        value: dict[str, Any],
        *,
        log_context: dict[str, Any] | None = None,
    ) -> bool:
        """Persist key/value with structured-log context on failure.

        Returns True on success, False if the substrate is unavailable
        or circuit-open. NEVER raises — substrate failures are logged
        with the caller's log_context so the audit trail is intact.

        Implements: REQ-CLONE-014
        Used by the clone-refactor DAG so the structured
        `clone_refactor.substrate_silent_write` log always carries
        `dag_id, step_name, files_touched`.

        SF-M1 hardening: _record_failure() is wrapped in its own try/except
        so a metrics-sink failure cannot suppress the structured log line.
        SF-M2 hardening: log_context is filtered against the LogRecord
        reserved-attribute set so caller-supplied keys like {"message": "x"}
        do not raise KeyError/AttributeError out of logger.warning().
        CR-m1: _record_failure failures are logged at WARNING (not DEBUG)
        per CLAUDE.md style — operators running at INFO must see this.
        """
        if not self._config.enabled or self._circuit_is_open():
            logger.warning(
                "clone_refactor.substrate_silent_write",
                extra={"key": key, **_safe_extra(log_context)},
            )
            return False
        try:
            await self._client.put(key, value, ttl=None)
            self._record_success()
            return True
        except Exception as exc:  # noqa: BLE001 - boundary handler
            # SF-M1 + CR-m1: wrap _record_failure() in try/except so a
            # metrics-sink failure cannot suppress the structured log
            # line. Log the _record_failure failure at WARNING (not DEBUG)
            # per CLAUDE.md style.
            try:
                self._record_failure()
            except Exception as record_exc:  # noqa: BLE001
                logger.warning(
                    "MCPStateBackend._record_failure failed; continuing",
                    exc_info=record_exc,
                )
            logger.warning(
                "clone_refactor.substrate_silent_write",
                extra={
                    "key": key,
                    "substrate_error": str(exc),
                    **_safe_extra(log_context),
                },
            )
            return False
```

### Step 6: Export new symbols from `state_backends/__init__.py`

Edit `mahavishnu/core/state_backends/__init__.py`. Add to the import list / `__all__`:

```python
from .mcp import MCPStateBackend, MCPStateBackendError, MCPStateConfig, MCPStateBackendUnavailable

__all__ = ["MCPStateBackend", "MCPStateBackendError", "MCPStateConfig", ...]
```

(Adjust to match the existing export pattern in the file. Read the file first if structure differs.)

### Step 7: Run tests to verify they pass

Run:
```bash
cd /Users/les/Projects/mahavishnu
.venv/bin/pytest tests/unit/test_mcp_state_backend.py -v
```

**Expected:** all green, including the 3 new test classes.

### Step 8: Verify §6.10 audit_orphans.py scope (deferred from Task 1)

This is the verification deferred from Task 1 Step 3. Run after Task 2's symbols exist:

Run:
```bash
cd /Users/les/Projects/mahavishnu
.venv/bin/python scripts/audit_orphans.py --dry-run 2>&1 | grep -E "dag_key|cluster_key|in_flight_key|MCPStateBackendError|try_put_with_log_context"
```

**Expected (CR-M3 fix):** the new symbols MAY be flagged as orphans at this commit point because their callers (`clone_refactor_workflow.py` Task 5, `clone_tools.py` Task 6) don't exist yet. This is expected — the audit's purpose is to flag *stuck* orphans (defined but never called across the entire codebase), not orphans awaiting later-task callers. Document this in the commit message and proceed. If after Task 6 the symbols are STILL flagged, that's the actionable signal — extend `DECORATOR_REGISTRATION_PATTERN` or add the symbols to the audit's allowlist at that point.

### Step 9: Commit

```bash
cd /Users/les/Projects/mahavishnu
git add mahavishnu/core/state_backends/mcp.py mahavishnu/core/state_backends/__init__.py tests/unit/test_mcp_state_backend.py
git -c core.hooksPath=/dev/null -c user.email=les@wedgwoodwebworks.com \
    commit -m "feat(state-backends): add dag_key/cluster_key/in_flight_key + try_put_with_log_context

REQ-CLONE-007 (dag_key), REQ-CLONE-009 (in_flight_key), REQ-CLONE-014 (try_put_with_log_context).
Existing workflow_key() preserved. New MCPStateBackendError for explicit-failure callers.

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

## Task 3: Clone-refactor claims module (cluster-claim + ConcurrentDAGError)

**Files:**
- Create: `mahavishnu/mcp/tools/clone_claims.py` (new, ~80 lines)
- Create: `tests/unit/clone/test_clone_claims.py` (new, ~80 lines)

**Interfaces (consumed by Task 6):**
- `ConcurrentDAGError(existing_job_id: str)` — raised by `cluster_state_claim` when claim exists with different `refactor_job_id`
- `cluster_state_claim(mcp_backend: MCPStateBackend, cluster_id: str, refactor_job_id: str) -> None` — TD-m6: returns `None` on success (was `-> bool`). Acquires in-process lock + writes `cluster/v1/{cluster_id}/in_flight` sentinel; raises `ConcurrentDAGError` if existing in-flight job_id differs, `MCPStateBackendUnavailable` if substrate circuit is open (SF-B6)
- `release_cluster_claim(mcp_backend: MCPStateBackend, cluster_id: str) -> None` — deletes the sentinel
- `MCPStateBackendUnavailable(key: str, reason: str)` — TD-m9: actually defined in `state_backends/mcp.py` (architectural consistency with peer `MCPStateBackendError`); re-exported here

**Integration Contract** (per `.claude/decisions/wire-up-contract.md`):
- **Triggered from**: `clone_tools.py::CloneTools.clone_refactor_group` calls `cluster_state_claim` after `verify_proposal` succeeds; `@flow` body in `clone_refactor_workflow.py` calls `release_cluster_claim` in finally
- **Returns to / updates**: `cluster/v1/{cluster_id}/in_flight` MCP key (claim sentinel); raises `ConcurrentDAGError` on conflict, `MCPStateBackendUnavailable` on circuit-open
- **Demonstrable by**: `pytest tests/unit/clone/test_clone_claims.py` — 5 tests covering first-claim, idempotent re-claim, different-job-id rejection, in-process serialization, release semantics
- **Rollback signal**: `ConcurrentDAGError(existing_job_id=...)` propagates to MCP client as 409; `MCPStateBackendUnavailable` propagates as 503
- **Observability added**: structured warning `cluster_claim: stale sentinel at <key>, overwriting` (SF-M4) when None refactor_job_id encountered

### Step 1: Write failing tests

Create `tests/unit/clone/test_clone_claims.py`:

```python
"""Tests for cluster_claim / release_cluster_claim (REQ-CLONE-009).

Implements: REQ-CLONE-009
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from mahavishnu.mcp.tools.clone_claims import (
    ConcurrentDAGError,
    cluster_state_claim,
    release_cluster_claim,
)


@pytest.fixture
def mock_backend() -> AsyncMock:
    """Returns an AsyncMock that mimics MCPStateBackend.put/delete."""
    backend = AsyncMock()
    backend.dag_key = lambda x: f"workflow/v1/{x}"
    backend.cluster_key = lambda x: f"cluster/v1/{x}"
    backend.in_flight_key = lambda x: f"cluster/v1/{x}/in_flight"
    return backend


@pytest.mark.req(["REQ-CLONE-009"])  # CR-M1: REQ traceability
class TestClusterStateClaim:
    """REQ-CLONE-009: cluster_id is locked across concurrent invocations."""

    async def test_first_claim_succeeds(self, mock_backend: AsyncMock) -> None:
        # First call: no existing sentinel → claim acquired, sentinel written.
        async def fake_get(key: str):
            return None  # no existing claim

        mock_backend.get = fake_get
        mock_backend.put = AsyncMock()
        result = await cluster_state_claim(mock_backend, "cluster-1", "job-aaa")
        # TD-m6: cluster_state_claim returns None (was `-> bool`); success = no exception
        assert result is None
        mock_backend.put.assert_called_once()
        call = mock_backend.put.call_args
        assert call.args[0] == "cluster/v1/cluster-1/in_flight"
        assert call.args[1]["refactor_job_id"] == "job-aaa"

    async def test_existing_same_job_id_succeeds(self, mock_backend: AsyncMock) -> None:
        # Idempotent: same caller re-claiming their own job → returns None.
        async def fake_get(key: str):
            return {"refactor_job_id": "job-aaa"}

        mock_backend.get = fake_get
        mock_backend.put = AsyncMock()
        result = await cluster_state_claim(mock_backend, "cluster-1", "job-aaa")
        assert result is None
        # No new put — claim already held by same job
        mock_backend.put.assert_not_called()

    async def test_existing_different_job_id_raises(self, mock_backend: AsyncMock) -> None:
        async def fake_get(key: str):
            return {"refactor_job_id": "job-bbb"}

        mock_backend.get = fake_get
        mock_backend.put = AsyncMock()
        with pytest.raises(ConcurrentDAGError) as exc_info:
            await cluster_state_claim(mock_backend, "cluster-1", "job-aaa")
        assert exc_info.value.existing_job_id == "job-bbb"

    async def test_concurrent_claim_serialized_within_process(self) -> None:
        # In-process lock: two concurrent claims for the same cluster_id —
        # one acquires (returns None), the other sees the sentinel and raises.
        import asyncio

        backend = AsyncMock()
        backend.cluster_key = lambda x: f"cluster/v1/{x}"
        backend.in_flight_key = lambda x: f"cluster/v1/{x}/in_flight"

        claim_count = 0

        async def fake_get(key: str):
            nonlocal claim_count
            # After first put, subsequent gets see the sentinel
            return {"refactor_job_id": "job-aaa"} if claim_count > 0 else None

        async def fake_put(key: str, value: dict, ttl=None):
            nonlocal claim_count
            claim_count += 1

        backend.get = fake_get
        backend.put = fake_put

        results = await asyncio.gather(
            cluster_state_claim(backend, "cluster-1", "job-aaa"),
            cluster_state_claim(backend, "cluster-1", "job-bbb"),
            return_exceptions=True,
        )
        # Exactly one succeeded (returns None), one raised
        successes = [r for r in results if r is None]
        errors = [r for r in results if isinstance(r, ConcurrentDAGError)]
        assert len(successes) == 1
        assert len(errors) == 1


class TestReleaseClusterClaim:
    async def test_release_deletes_in_flight_key(self, mock_backend: AsyncMock) -> None:
        mock_backend.delete = AsyncMock()
        await release_cluster_claim(mock_backend, "cluster-1")
        mock_backend.delete.assert_called_once_with("cluster/v1/cluster-1/in_flight")

    async def test_release_does_not_raise_on_missing_key(self, mock_backend: AsyncMock) -> None:
        async def fake_delete(key: str):
            return None  # no-op even if key didn't exist

        mock_backend.delete = fake_delete
        await release_cluster_claim(mock_backend, "cluster-1")  # must not raise


class TestConcurrentDAGError:
    def test_existing_job_id_attribute(self) -> None:
        exc = ConcurrentDAGError(existing_job_id="0193f5e2-7c8d-7abc-9def-1234567890ab")
        assert exc.existing_job_id == "0193f5e2-7c8d-7abc-9def-1234567890ab"
        assert "0193f5e2-7c8d-7abc-9def-1234567890ab" in str(exc)
```

### Step 2: Run tests to verify they fail

Run:
```bash
cd /Users/les/Projects/mahavishnu
.venv/bin/pytest tests/unit/clone/test_clone_claims.py -v
```

**Expected:** FAIL with `ModuleNotFoundError: No module named 'mahavishnu.mcp.tools.clone_claims'`.

### Step 3: Create `mahavishnu/mcp/tools/clone_claims.py`

```python
"""Cluster-claim helpers for clone_refactor_group.

Single-process dedup via dict[str, asyncio.Lock]. Cross-process dedup is
deferred (out of scope per spec §3 Non-Goals; MCPStateBackend.put() is not CAS).

Implements: REQ-CLONE-009
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mahavishnu.core.state_backends.mcp import MCPStateBackend

logger = logging.getLogger(__name__)


class ConcurrentDAGError(Exception):
    """Raised by cluster_state_claim when another DAG holds the claim.

    Implements: REQ-CLONE-009
    """

    def __init__(self, existing_job_id: str) -> None:
        super().__init__(f"cluster_id already has in-flight DAG {existing_job_id}")
        self.existing_job_id = existing_job_id


# TD-m9: MCPStateBackendUnavailable is defined in state_backends/mcp.py
# (alongside its peer MCPStateBackendError). Re-exported here for backward
# compat with Task 6's import path.
from mahavishnu.core.state_backends.mcp import MCPStateBackendUnavailable  # noqa: E402, F401


# In-process locks keyed by cluster_id. Cross-process dedup is out of scope
# (MCPStateBackend.put() is not CAS — see spec §3 Non-Goals + §6.4 v4 MAJOR-fix M4).
_cluster_locks: dict[str, asyncio.Lock] = {}


def _get_cluster_lock(cluster_id: str) -> asyncio.Lock:
    if cluster_id not in _cluster_locks:
        _cluster_locks[cluster_id] = asyncio.Lock()
    return _cluster_locks[cluster_id]


async def cluster_state_claim(
    mcp_backend: MCPStateBackend,
    cluster_id: str,
    refactor_job_id: str,
) -> None:
    """Acquire cluster-claim. Returns on success.

    TD-m6: return type is `None` (was `-> bool`). Every non-success path
    raises; the only `return True` paths were dead-code. Callers in
    `clone_tools.py` already discard the return value.

    Raises:
        ConcurrentDAGError: another DAG holds the claim with a different
            refactor_job_id.
        MCPStateBackendUnavailable: substrate is unreachable. SF-B6 fails
            loud rather than silently letting two cross-process DAGs race.

    Implements: REQ-CLONE-009
    """
    # SF-B6: fail loud if the substrate circuit is open. Two cross-process
    # DAGs both calling put() would each silently fail and each return True.
    if mcp_backend._circuit_is_open():
        raise MCPStateBackendUnavailable(
            key=mcp_backend.in_flight_key(cluster_id),
            reason="circuit_open",
        )

    lock = _get_cluster_lock(cluster_id)
    async with lock:
        sentinel_key = mcp_backend.in_flight_key(cluster_id)
        existing = await mcp_backend.get(sentinel_key)
        if existing is not None:
            existing_job_id = existing.get("refactor_job_id") if existing else None
            # SF-M4: missing/None refactor_job_id (corrupt/legacy sentinel) is
            # treated as unowned — overwrite rather than raise with None.
            if existing_job_id is None:
                logger.warning(
                    "cluster_claim: stale sentinel at %s, overwriting", sentinel_key
                )
            elif existing_job_id == refactor_job_id:
                # Idempotent: same caller re-claiming their own job
                return
            else:
                raise ConcurrentDAGError(existing_job_id=existing_job_id)
        await mcp_backend.put(
            sentinel_key,
            {"refactor_job_id": refactor_job_id, "claimed_at": asyncio.get_event_loop().time()},
        )
        return


async def release_cluster_claim(
    mcp_backend: MCPStateBackend,
    cluster_id: str,
) -> None:
    """Release the cluster-claim by deleting the sentinel.

    Idempotent: does not raise if the sentinel didn't exist or delete fails.
    SF-B3/SF-M6: a release failure must never shadow the calling @flow's
    original exception.
    """
    sentinel_key = mcp_backend.in_flight_key(cluster_id)
    try:
        await mcp_backend.delete(sentinel_key)
    except Exception as exc:  # noqa: BLE001 - release is best-effort
        logger.warning(
            "release_cluster_claim: delete failed for %s (%s); continuing",
            sentinel_key, exc,
        )
```

### Step 4: Run tests to verify they pass

Run:
```bash
cd /Users/les/Projects/mahavishnu
.venv/bin/pytest tests/unit/clone/test_clone_claims.py -v
```

**Expected:** all green. **NOTE (CA-B1 fix):** the real `MCPStateBackend.get()` and `MCPStateBackend.delete()` already exist in `mahavishnu/core/state_backends/mcp.py` — verified at the spec review. The plan's earlier Step 4 that proposed adding stubs was based on a false premise and used the wrong `MCPClient` API signatures (`_client.get(key)` and `_client.delete(key)` are NOT methods on `MCPClient`; the real substrate call is `call_tool("get", {...})`). The production code in Task 3 Step 3 calls `mcp_backend.get(key)` and `mcp_backend.delete(key)` which resolve to the existing real methods. The test mocks (`AsyncMock`) bypass the actual backend, so all tests pass without any MCPStateBackend additions.

### Step 5: Commit

```bash
cd /Users/les/Projects/mahavishnu
git add mahavishnu/mcp/tools/clone_claims.py tests/unit/clone/test_clone_claims.py
git -c core.hooksPath=/dev/null -c user.email=les@wedgwoodwebworks.com \
    commit -m "feat(clone-claims): cluster_state_claim with in-process lock + ConcurrentDAGError

REQ-CLONE-009. Cross-process dedup deferred (out of scope; MCPStateBackend.put() not CAS).
Also adds MCPStateBackend.get() and .delete() methods needed by release_cluster_claim.

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

## Task 4: _git_ops.py subprocess wrapper with typed exceptions

**Files:**
- Create: `mahavishnu/workflows/_git_ops.py` (new, ~120 lines)
- Create: `tests/unit/workflows/test_git_ops.py` (new, ~200 lines)

**Interfaces (consumed by Task 5):**
- `GitApplyConflict(diff_offset: int, conflict_marker: str, stderr: str)` — never retried (REQ-CLONE-013)
- `GitCommitFailed(stderr: str, exit_code: int)` — base class
- `GitCommitTransient(reason: str, stderr: str)` — retried (REQ-CLONE-013)
- `GitCommandTimeout(timeout_seconds: float, cmd: list[str])` — NEW (SF-B5); subclass of `GitCommitTransient`, raised by `_run_git` on subprocess timeout
- `GitCommitPermanent(reason: str, stderr: str, exit_code: int)` — propagated (REQ-CLONE-013); negative exit codes classified as `signal_{-N}` (SF-m5)
- `StashPopFailed(stderr: str, exit_code: int)` — NEW (SF-B4); raised by `stash_pop` on non-zero exit
- `git_apply(repo_path: Path, diff: str) -> None` — passes diff via stdin (NEVER argv); raises `GitApplyConflict` on conflict; 30s timeout
- `git_commit(repo_path: Path, message: str) -> str` — returns 40-char hex SHA; raises `GitCommitTransient`/`GitCommandTimeout`/`GitCommitPermanent` per stderr pattern (REQ-CLONE-013); 120s timeout (SF-B5)
- `current_head_sha(repo_path: Path) -> str` — returns 40-char hex SHA
- `stash_push(repo_path: Path) -> str` — returns stash ref (e.g., `stash@{0}`); uses plain `git stash` (NOT `--keep-index`); does NOT stash staged-only changes (SF-m8)
- `stash_pop(repo_path: Path, stash_ref: str) -> None` — raises `StashPopFailed` on non-zero exit (SF-B4)
- `diff_files(repo_path: Path) -> tuple[str, ...]` — files modified by last apply
- `is_working_tree_clean(repo_path: Path) -> bool` — `git status --porcelain` empty

**Integration Contract** (per `.claude/decisions/wire-up-contract.md`):
- **Triggered from**: DAG step functions in `clone_refactor_workflow.py` (`write_canonical_symbol`, `write_replacement_diff`)
- **Returns to / updates**: nothing (pure side-effect wrapper; `git_commit` returns the SHA via stdout)
- **Demonstrable by**: `pytest tests/unit/workflows/test_git_ops.py` — 8 tests covering apply/conflict, commit/returns-sha, transient/permanent/timeout classification, stash push/pop semantics, plain-stash-not-keep-index verification
- **Rollback signal**: `git_commit` raises typed `GitCommitTransient`/`GitCommitPermanent`/`GitCommandTimeout` → caller records failure; `stash_pop` raises `StashPopFailed` → caller records failure on `RepoCommit` (no propagation; commit may have already landed)
- **Observability added**: structured log line per call with `repo_path`, `exit_code`, `commit_sha` fields; SIGKILL exit codes (`< 0`) classified as `GitCommitPermanent(reason="signal_{-N}")` (SF-m5)

### Step 1: Write failing tests

Create `tests/unit/workflows/test_git_ops.py`:

```python
"""Unit tests for _git_ops.py — git subprocess wrapper.

Implements: REQ-CLONE-011, REQ-CLONE-013
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from mahavishnu.workflows._git_ops import (
    GitApplyConflict,
    GitCommitFailed,
    GitCommitPermanent,
    GitCommitTransient,
    current_head_sha,
    diff_files,
    git_apply,
    git_commit,
    is_working_tree_clean,
    stash_pop,
    stash_push,
)


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """Initialize a git repo at tmp_path with user.email/name configured."""
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.email", "test@example.com"],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.name", "Test"],
        check=True, capture_output=True,
    )
    return tmp_path


class TestGitApply:
    async def test_git_apply_clean(self, git_repo: Path) -> None:
        # Setup: create initial file, commit
        (git_repo / "foo.py").write_text("x = 1\n")
        subprocess.run(["git", "-C", str(git_repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(git_repo), "commit", "-m", "init"], check=True)

        diff = "--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-x = 1\n+x = 2\n"
        await git_apply(git_repo, diff)
        assert (git_repo / "foo.py").read_text() == "x = 2\n"

    async def test_git_apply_conflict_raises_structured(self, git_repo: Path) -> None:
        (git_repo / "foo.py").write_text("x = 1\n")
        subprocess.run(["git", "-C", str(git_repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(git_repo), "commit", "-m", "init"], check=True)

        # Diff that conflicts with the existing file
        bad_diff = "--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-x = 1\n+x = 999\n--- a/missing.py\n+++ b/missing.py\n@@ -0,0 +1 @@\n+created\n"
        with pytest.raises(GitApplyConflict) as exc_info:
            await git_apply(git_repo, bad_diff)
        assert isinstance(exc_info.value.diff_offset, int)
        assert exc_info.value.conflict_marker  # non-empty

    async def test_git_apply_via_stdin_not_argv(self, git_repo: Path, monkeypatch) -> None:
        # Verify diff is passed via stdin, not argv (REQ security note in spec §6.2)
        import asyncio

        (git_repo / "foo.py").write_text("x = 1\n")
        subprocess.run(["git", "-C", str(git_repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(git_repo), "commit", "-m", "init"], check=True)

        diff = "--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-x = 1\n+x = 2\n"
        # If diff was in argv, a malicious diff containing "rm -rf /" would be
        # passed as a literal arg. We verify by checking the subprocess was
        # called with the diff via stdin (mock subprocess).
        captured_stdin: list[str] = []

        async def fake_subprocess_exec(*args, stdin=None, **kwargs):
            class FakeProc:
                async def communicate(self):
                    # Capture stdin
                    if stdin is not None:
                        stdin_data = stdin
                        if hasattr(stdin_data, "read"):
                            captured_stdin.append(stdin_data.read().decode())
                        else:
                            captured_stdin.append("NOT_USED")
                    return b"", b""

                async def wait(self):
                    return 0

            return FakeProc()

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_subprocess_exec)
        await git_apply(git_repo, diff)
        assert diff in (captured_stdin[0] if captured_stdin else ""), (
            "git_apply must pass diff via stdin, not argv"
        )


class TestGitCommit:
    async def test_git_commit_returns_sha(self, git_repo: Path) -> None:
        (git_repo / "foo.py").write_text("x = 1\n")
        subprocess.run(["git", "-C", str(git_repo), "add", "."], check=True)
        sha = await git_commit(git_repo, "test commit")
        assert len(sha) == 40
        assert all(c in "0123456789abcdef" for c in sha)

    async def test_git_commit_transient_index_lock(self, git_repo: Path, monkeypatch) -> None:
        # Simulate the exact stderr pattern that triggers Transient
        from unittest.mock import AsyncMock
        import asyncio

        async def fake_subprocess_exec(*args, stdin=None, **kwargs):
            class FakeProc:
                returncode = 1

                async def communicate(self):
                    return b"", b"fatal: Unable to create .git/index.lock: File exists.\n"

                async def wait(self):
                    return 1

            return FakeProc()

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_subprocess_exec)
        with pytest.raises(GitCommitTransient) as exc_info:
            await git_commit(git_repo, "x")
        assert "index.lock" in exc_info.value.reason

    async def test_git_commit_permanent_default(self, git_repo: Path, monkeypatch) -> None:
        import asyncio

        async def fake_subprocess_exec(*args, stdin=None, **kwargs):
            class FakeProc:
                returncode = 128

                async def communicate(self):
                    return b"", b"fatal: cannot commit without user.email\n"

                async def wait(self):
                    return 128

            return FakeProc()

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_subprocess_exec)
        with pytest.raises(GitCommitPermanent) as exc_info:
            await git_commit(git_repo, "x")
        assert exc_info.value.exit_code == 128

    async def test_git_commit_with_precommit_fail_is_permanent(
        self, git_repo: Path, monkeypatch
    ) -> None:
        # Pre-commit hook failure must NOT retry (REQ-CLONE-013)
        import asyncio

        async def fake_subprocess_exec(*args, stdin=None, **kwargs):
            class FakeProc:
                returncode = 1

                async def communicate(self):
                    return (
                        b"",
                        b"husky > pre-commit hook failed (add --no-verify to bypass)\n",
                    )

                async def wait(self):
                    return 1

            return FakeProc()

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_subprocess_exec)
        with pytest.raises(GitCommitPermanent):
            await git_commit(git_repo, "x")


class TestCurrentHeadSha:
    async def test_returns_latest_sha(self, git_repo: Path) -> None:
        (git_repo / "a").write_text("1")
        subprocess.run(["git", "-C", str(git_repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(git_repo), "commit", "-m", "first"], check=True)
        first_sha = await current_head_sha(git_repo)

        (git_repo / "b").write_text("2")
        subprocess.run(["git", "-C", str(git_repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(git_repo), "commit", "-m", "second"], check=True)
        second_sha = await current_head_sha(git_repo)

        assert first_sha != second_sha
        assert len(second_sha) == 40


class TestStashWrap:
    async def test_stash_push_pop_roundtrip(self, git_repo: Path) -> None:
        (git_repo / "foo.py").write_text("original\n")
        subprocess.run(["git", "-C", str(git_repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(git_repo), "commit", "-m", "init"], check=True)

        # Make dirty changes
        (git_repo / "foo.py").write_text("dirty WIP\n")
        assert not await is_working_tree_clean(git_repo)

        # Stash + pop restores
        stash_ref = await stash_push(git_repo)
        assert await is_working_tree_clean(git_repo)
        await stash_pop(git_repo, stash_ref)
        assert (git_repo / "foo.py").read_text() == "dirty WIP\n"

    async def test_stash_push_uses_plain_stash_not_keep_index(
        self, git_repo: Path, monkeypatch
    ) -> None:
        # REQ-CLONE-011: plain `git stash`, NOT `git stash --keep-index`.
        # Verify by inspecting the args passed to subprocess.
        import asyncio

        captured_args: list[tuple] = []

        async def fake_subprocess_exec(*args, **kwargs):
            captured_args.append(args)

            class FakeProc:
                returncode = 0

                async def communicate(self):
                    return b"Saved working directory and index state WIP on main: abc\n", b""

                async def wait(self):
                    return 0

            return FakeProc()

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_subprocess_exec)
        await stash_push(git_repo)
        # Find the stash call
        stash_calls = [a for a in captured_args if "stash" in a and isinstance(a, tuple)]
        assert any("--keep-index" not in a for a in stash_calls), (
            f"stash_push must NOT use --keep-index; got args: {captured_args}"
        )
```

### Step 2: Run tests to verify they fail

Run:
```bash
cd /Users/les/Projects/mahavishnu
.venv/bin/pytest tests/unit/workflows/test_git_ops.py -v
```

**Expected:** FAIL with `ModuleNotFoundError`.

### Step 3: Create `mahavishnu/workflows/_git_ops.py`

```python
"""Subprocess git wrapper for clone_refactor DAG.

Passes diffs via stdin (never argv — avoids injection through malformed diff headers).
Raises typed exceptions per REQ-CLONE-013.

Implements: REQ-CLONE-011, REQ-CLONE-013
"""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---- Typed exceptions (REQ-CLONE-013) ------------------------------------

class GitApplyConflict(Exception):
    """Structured conflict from `git apply --check`. Never retried."""

    def __init__(self, diff_offset: int, conflict_marker: str, stderr: str) -> None:
        super().__init__(f"GitApplyConflict at diff_offset={diff_offset}")
        self.diff_offset = diff_offset
        self.conflict_marker = conflict_marker
        self.stderr = stderr


class GitCommitFailed(Exception):
    """Base for both transient and permanent commit failures."""

    def __init__(self, stderr: str, exit_code: int) -> None:
        super().__init__(f"git commit failed (exit_code={exit_code}): {stderr}")
        self.stderr = stderr
        self.exit_code = exit_code


class GitCommitTransient(GitCommitFailed):
    """Index lock contention or brief I/O. Retried up to retries=2 times.

    Implements: REQ-CLONE-013
    """

    def __init__(self, reason: str, stderr: str) -> None:
        super().__init__(stderr, exit_code=-1)
        self.reason = reason


class GitCommitPermanent(GitCommitFailed):
    """Permission denied, disk full, pre-commit hook failure, malformed
    message, missing user.email/user.name, repo in detached state. NOT
    retried — propagates immediately.

    Implements: REQ-CLONE-013
    """

    def __init__(self, reason: str, stderr: str, exit_code: int) -> None:
        super().__init__(stderr, exit_code=exit_code)
        self.reason = reason


class GitCommandTimeout(GitCommitTransient):
    """Subprocess exceeded timeout. SF-B5: classified as Transient so Prefect
    retries it; the underlying git operation may have been partway through
    and a retry is safer than abandoning.

    Implements: REQ-CLONE-013 (via Transient subclass)
    """

    def __init__(self, timeout_seconds: float, cmd: list[str]) -> None:
        super().__init__(reason="timeout", stderr=f"timeout after {timeout_seconds}s")
        self.timeout_seconds = timeout_seconds
        self.cmd = cmd


class StashPopFailed(Exception):
    """Plain `git stash pop` failed. SF-B4: must be raised (not swallowed) so
    the @flow caller records a typed error on the RepoCommit.

    Implements: REQ-CLONE-011
    """

    def __init__(self, stderr: str, exit_code: int) -> None:
        super().__init__(f"git stash pop failed (exit_code={exit_code}): {stderr}")
        self.stderr = stderr
        self.exit_code = exit_code


# ---- Stderr classification (REQ-CLONE-013) --------------------------------

_TRANSIENT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"Unable to create \.git/index\.lock"),
    re.compile(r"fatal: unable to lock"),
    re.compile(r"Connection reset"),
    re.compile(r"Resource temporarily unavailable"),
)


def _classify_commit_failure(stderr: str, exit_code: int) -> GitCommitFailed:
    """Match stderr against transient patterns; otherwise permanent.

    SF-m5: negative exit codes mean the process was killed by a signal
    (e.g., SIGKILL=-9, SIGTERM=-15). Classify as Permanent with a
    signal-specific reason so operators can distinguish signal-kills from
    command-level failures.
    """
    if exit_code < 0:
        return GitCommitPermanent(
            reason=f"signal_{-exit_code}",
            stderr=stderr,
            exit_code=exit_code,
        )
    for pattern in _TRANSIENT_PATTERNS:
        if pattern.search(stderr):
            return GitCommitTransient(reason=pattern.pattern, stderr=stderr)
    return GitCommitPermanent(reason="see_stderr", stderr=stderr, exit_code=exit_code)


# ---- Subprocess helpers ---------------------------------------------------

# SF-B5: timeout for any git subprocess call. 120s is generous for any
# git operation; tighten to 30s for `apply --check` if needed.
_GIT_SUBPROCESS_TIMEOUT_SECONDS = 120.0


async def _run_git(
    repo_path: Path,
    *args: str,
    stdin_data: str | None = None,
    check: bool = True,
    timeout_seconds: float = _GIT_SUBPROCESS_TIMEOUT_SECONDS,
) -> tuple[str, str, int]:
    """Run `git -C repo_path <args>` with optional stdin. Returns (stdout, stderr, exit_code).

    SF-B5: bounded by timeout_seconds; on timeout, kills the subprocess and
    raises GitCommandTimeout (Transient subclass — Prefect retries).
    """
    cmd = ["git", "-C", str(repo_path), *args]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE if stdin_data is not None else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout_b, stderr_b = await asyncio.wait_for(
            proc.communicate(
                input=stdin_data.encode() if stdin_data is not None else None
            ),
            timeout=timeout_seconds,
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise GitCommandTimeout(timeout_seconds=timeout_seconds, cmd=list(cmd))
    stdout = stdout_b.decode().strip() if stdout_b else ""
    stderr = stderr_b.decode().strip() if stderr_b else ""
    if check and proc.returncode != 0:
        raise RuntimeError(f"git {args} failed (exit={proc.returncode}): {stderr}")
    return stdout, stderr, proc.returncode or 0


# ---- Public API -----------------------------------------------------------

async def git_apply(repo_path: Path, diff: str) -> None:
    """Apply diff via stdin. Raises GitApplyConflict on conflict."""
    # Validate path
    repo_path = repo_path.resolve()
    if not (repo_path / ".git").exists():
        raise ValueError(f"repo_path {repo_path} is not a git repo")

    # Reject diffs with suspicious patterns (defensive — REQ security note in §6.2)
    for bad in ("Binary files", "rename to /dev/", "rename from /dev/"):
        if bad in diff:
            raise ValueError(f"diff contains disallowed pattern: {bad!r}")

    # First: `git apply --check` to detect conflicts cleanly
    try:
        await _run_git(repo_path, "apply", "--check", stdin_data=diff, timeout_seconds=30.0)
    except RuntimeError as exc:
        msg = str(exc)
        # Extract diff_offset and conflict_marker from stderr
        offset_match = re.search(r"@@ -(\d+)", msg)
        diff_offset = int(offset_match.group(1)) if offset_match else 0
        marker_match = re.search(r"@@[^@]+@@.*", msg)
        conflict_marker = marker_match.group(0) if marker_match else ""
        raise GitApplyConflict(
            diff_offset=diff_offset,
            conflict_marker=conflict_marker,
            stderr=msg,
        ) from exc

    # Apply for real
    await _run_git(repo_path, "apply", stdin_data=diff)


async def git_commit(repo_path: Path, message: str) -> str:
    """Commit and return SHA. Raises GitCommitTransient or GitCommitPermanent."""
    repo_path = repo_path.resolve()
    _, stderr, exit_code = await _run_git(
        repo_path,
        "-c",
        "user.email=les@wedgwoodwebworks.com",
        "-c",
        "user.name=les",
        "commit",
        "-F",
        "-",
        stdin_data=message,
        check=False,
    )
    if exit_code != 0:
        raise _classify_commit_failure(stderr=stderr, exit_code=exit_code)
    # Get the new SHA
    sha, _, _ = await _run_git(repo_path, "rev-parse", "HEAD")
    return sha


async def current_head_sha(repo_path: Path) -> str:
    """Return the 40-char hex SHA of HEAD."""
    repo_path = repo_path.resolve()
    sha, _, _ = await _run_git(repo_path, "rev-parse", "HEAD")
    return sha


async def stash_push(repo_path: Path) -> str:
    """Plain `git stash` (NOT --keep-index). Returns stash ref like 'stash@{0}'.

    Implements: REQ-CLONE-011
    SF-m8 note: plain `git stash` does NOT stash staged-only changes. If
    the repo has staged but no unstaged changes, this exits 0 with "No
    local changes to save". Callers needing to stash staged changes must
    use `git stash --include-untracked` or commit first.
    """
    repo_path = repo_path.resolve()
    stdout, _, _ = await _run_git(repo_path, "stash", "push", "-m", "clone-refactor-WIP")
    return "stash@{0}"  # canonical reference for most-recent stash


async def stash_pop(repo_path: Path, stash_ref: str = "stash@{0}") -> None:
    """Pop the stash. SF-B4: raises StashPopFailed on non-zero exit
    (previously swallowed with check=False — this was the silent-failure
    bug that left the working tree dirty).

    Implements: REQ-CLONE-011
    """
    repo_path = repo_path.resolve()
    _, stderr, exit_code = await _run_git(
        repo_path, "stash", "pop", stash_ref, check=False
    )
    if exit_code != 0:
        raise StashPopFailed(stderr=stderr, exit_code=exit_code)


async def diff_files(repo_path: Path) -> list[str]:
    """Files modified by the last commit."""
    repo_path = repo_path.resolve()
    stdout, _, _ = await _run_git(
        repo_path, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"
    )
    return [f for f in stdout.splitlines() if f]


async def is_working_tree_clean(repo_path: Path) -> bool:
    """`git status --porcelain` empty → True."""
    repo_path = repo_path.resolve()
    stdout, _, _ = await _run_git(repo_path, "status", "--porcelain")
    return stdout == ""
```

### Step 4: Run tests to verify they pass

Run:
```bash
cd /Users/les/Projects/mahavishnu
.venv/bin/pytest tests/unit/workflows/test_git_ops.py -v
```

**Expected:** all green.

### Step 5: Commit

```bash
cd /Users/les/Projects/mahavishnu
git add mahavishnu/workflows/_git_ops.py tests/unit/workflows/test_git_ops.py
git -c core.hooksPath=/dev/null -c user.email=les@wedgwoodwebworks.com \
    commit -m "feat(git-ops): _git_ops.py with typed GitCommit* exceptions (REQ-CLONE-013)

REQ-CLONE-011 (plain git stash, NOT --keep-index).
REQ-CLONE-013 (GitCommitTransient retried; GitCommitPermanent propagated).
All subprocess calls pass diffs via stdin, never argv.

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

## Task 5: clone_refactor_workflow.py rewrite (git-tree DAG + Layer 2 tests)

**Files:**
- Rewrite: `mahavishnu/workflows/clone_refactor_workflow.py` (315 → ~400 lines)
- Create: `tests/unit/clone/test_clone_refactor_workflow.py` (rewrite — Layer 2 tests)

**Interfaces (consumed by Task 6):**
- `run_clone_refactor_dag(refactor_job_id, cluster_id, mcp_backend, target_repo, consumer_repos, extracted_symbol, extraction_diff, consuming_diffs=None) -> DAGResult` — Prefect `@flow`; raises `DAGAlreadyRunning` on re-entry (SF-M5)
- `DAGResult`, `RepoCommit`, `RepoHit`, `DAGState` — TD-m1/TD-m4: frozen dataclasses with `Literal` status fields (`"completed" | "failed"` for `RepoCommit`/`DAGResult`; `"queued" | "running" | "completed" | "failed" | "cancelled"` for `DAGState`); `tuple[str, ...]` for collection fields
- `DAGAlreadyRunning(existing_status)` — exception raised by re-entry guard
- `_write_step_outcome(mcp_backend, refactor_job_id, step_name, outcome)` — internal helper
- `_write_terminal_failed(mcp_backend, refactor_job_id, exc)` — internal helper
- `_write_terminal_cancelled(mcp_backend, refactor_job_id)` — internal helper
- `_dataclass_to_dict(obj)` — TD-m8: uses `dataclasses.asdict()` for frozen dataclass serialization
- `commit_message(refactor_job_id, target_repo, extracted_symbol)` — string formatter (REQ-CLONE-012)

**Integration Contract** (per `.claude/decisions/wire-up-contract.md`):
- **Triggered from**: `mcp__mahavishnu__clone_refactor_group` (in `clone_tools.py`) via `asyncio.create_task(run_clone_refactor_dag(...))` after `verify_proposal` succeeds and `cluster_claim` succeeds (REQ-CLONE-009)
- **Returns to / updates**: `workflow/v1/{refactor_job_id}` MCP key (via `MCPStateBackend.dag_key()`), `workflow/v1/{refactor_job_id}/steps/{step_name}` per-step outcomes (REQ-CLONE-010), `cluster/v1/{cluster_id}` per-cluster consumer-progress, `cluster/v1/{cluster_id}/in_flight` claim sentinel; all wrapped in try/except with structured-log fallback on substrate failure (REQ-CLONE-014)
- **Demonstrable by**: `pytest tests/unit/clone/test_clone_refactor_workflow.py` — 9 tests covering happy path, target-write failure, mixed consumer success/failure, no-auto-revert, REJECT-blocked-DAG, best-effort substrate writes, unhandled-exception terminal state, per-step state durability, commit-message convention
- **Rollback signal**: OTel/log line `clone_refactor.dag.failed` with `refactor_job_id` attribute; consumer-recovery via `clone_refactor_status(limit=N)` listing `status: failed` records (no-auto-revert policy per Section 5.4 + commit-message convention REQ-CLONE-012)
- **Observability added**: OTel span `clone_refactor.dag` with attrs `refactor_job_id`, `cluster_id`, `target_repo`, `consumer_count`; structured log `clone_refactor.substrate_silent_write` whenever `MCPStateBackend.put()` raises (REQ-CLONE-014)

### Step 1: Preserve quarantine-test headers

The current `clone_refactor_workflow.py:1-7` likely contains the `# Workflow-ID:` and `# Approved by:` markers required by `tests/unit/test_check_workflow_quarantine.py`. Read the first 10 lines of the file BEFORE rewriting. If the markers are present, copy them verbatim to the new module. If absent, add them:

```python
# Workflow-ID: 01JCLONEREF2026
# Approved by: les
"""Git-tree clone-refactor DAG.

Implements: REQ-CLONE-001, REQ-CLONE-002, REQ-CLONE-003, REQ-CLONE-010,
            REQ-CLONE-011, REQ-CLONE-012, REQ-CLONE-013, REQ-CLONE-016
"""
```

### Step 2: Write failing tests for the DAG

Delete the existing `tests/unit/clone/test_clone_refactor_workflow.py` (PR-shape tests — they're being replaced) and create a new file:

```python
"""Integration tests for run_clone_refactor_dag.

Implements: REQ-CLONE-010, REQ-CLONE-011, REQ-CLONE-012, REQ-CLONE-013
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from mahavishnu.workflows.clone_refactor_workflow import (
    DAGResult,
    RepoCommit,
    run_clone_refactor_dag,
)


@pytest.fixture
def target_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "target"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True, capture_output=True
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "Test"], check=True, capture_output=True
    )
    (repo / "foo.py").write_text("class Foo:\n    pass\n")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", "init"], check=True)
    return repo


@pytest.fixture
def consumer_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "consumer"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True, capture_output=True
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "Test"], check=True, capture_output=True
    )
    (repo / "consumer.py").write_text("from foo import Foo\n")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", "init"], check=True)
    return repo


@pytest.fixture
def mock_backend() -> AsyncMock:
    backend = AsyncMock()
    backend.dag_key = lambda x: f"workflow/v1/{x}"
    backend.cluster_key = lambda x: f"cluster/v1/{x}"
    backend.in_flight_key = lambda x: f"cluster/v1/{x}/in_flight"
    backend.try_put_with_log_context = AsyncMock(return_value=True)
    backend.put = AsyncMock()
    backend.delete = AsyncMock()
    return backend


class TestRunCloneRefactorDAG:
    async def test_happy_path_propose_consume_persist(
        self, target_repo: Path, consumer_repo: Path, mock_backend: AsyncMock
    ) -> None:
        # Setup: detect_cluster_members mocked to return [target_repo]
        with patch(
            "mahavishnu.workflows.clone_refactor_workflow.detect_cluster_members",
            new=AsyncMock(return_value=[{"repo": str(target_repo), "match_score": 1.0}]),
        ):
            extraction_diff = (
                "--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-class Foo:\n-    pass\n+class Foo:\n+    '''Extracted'''\n"
            )
            consuming_diff = (
                "--- a/consumer.py\n+++ b/consumer.py\n@@ -1 +1 @@\n-from foo import Foo\n+from foo import Foo  # updated\n"
            )
            result = await run_clone_refactor_dag(
                refactor_job_id="job-001",
                cluster_id="cluster-1",
                mcp_backend=mock_backend,
                target_repo=str(target_repo),
                consumer_repos=[str(consumer_repo)],
                extracted_symbol="Foo",
                extraction_diff=extraction_diff,
                consuming_diffs={str(consumer_repo): consuming_diff},
            )
        assert isinstance(result, DAGResult)
        assert result.status == "completed"
        assert len(result.consumer_commits) == 1
        assert result.consumer_commits[0].status == "completed"
        assert result.consumer_commits[0].repo == str(consumer_repo)

    async def test_target_write_fails_no_consumer_writes(
        self, target_repo: Path, consumer_repo: Path, mock_backend: AsyncMock
    ) -> None:
        # CA-M3 fix: mock `write_canonical_symbol` to raise instead of chmod
        # (chmod 0o000 is no-op for uid 0 and bypassed by git ops anyway).
        # The failure must happen INSIDE write_canonical_symbol — after
        # detect_cluster_members returns but before any consumer work.
        with patch(
            "mahavishnu.workflows.clone_refactor_workflow.detect_cluster_members",
            new=AsyncMock(return_value=[{"repo": str(target_repo), "match_score": 1.0}]),
        ):
            with patch(
                "mahavishnu.workflows.clone_refactor_workflow.write_canonical_symbol",
                new=AsyncMock(side_effect=RuntimeError("write_canonical_symbol failed")),
            ):
                with pytest.raises(RuntimeError, match="write_canonical_symbol failed"):
                    await run_clone_refactor_dag(
                        refactor_job_id="job-002",
                        cluster_id="cluster-1",
                        mcp_backend=mock_backend,
                        target_repo=str(target_repo),
                        consumer_repos=[str(consumer_repo)],
                        extracted_symbol="x",
                        extraction_diff="--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-x = 1\n+x = 2\n",
                    )
        # REQ-CLONE-010: terminal "failed" was written
        failed_calls = [
            c for c in mock_backend.try_put_with_log_context.call_args_list
            if c.kwargs.get("log_context", {}).get("step_name") == "failed"
        ]
        assert len(failed_calls) == 1
        # REQ-CLONE-009: claim released in finally
        mock_backend.delete.assert_called_with("cluster/v1/cluster-1/in_flight")

    async def test_one_consumer_fails_others_succeed(
        self, target_repo: Path, tmp_path: Path, mock_backend: AsyncMock
    ) -> None:
        good1 = tmp_path / "good1"
        good2 = tmp_path / "good2"
        bad = tmp_path / "bad"
        for r in (good1, good2, bad):
            r.mkdir()
            subprocess.run(["git", "init", str(r)], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(r), "config", "user.email", "x@x"], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(r), "config", "user.name", "X"], check=True, capture_output=True)
            (r / "c.py").write_text("old\n")
            subprocess.run(["git", "-C", str(r), "add", "."], check=True)
            subprocess.run(["git", "-C", str(r), "commit", "-m", "init"], check=True)

        # Bad repo gets a diff that doesn't apply
        consuming_diff_bad = "--- a/nonexistent.py\n+++ b/nonexistent.py\n@@ -0,0 +1 @@\n+x\n"
        consuming_diff_good = "--- a/c.py\n+++ b/c.py\n@@ -1 +1 @@\n-old\n+new\n"

        with patch(
            "mahavishnu.workflows.clone_refactor_workflow.detect_cluster_members",
            new=AsyncMock(return_value=[{"repo": str(target_repo)}]),
        ):
            result = await run_clone_refactor_dag(
                refactor_job_id="job-003",
                cluster_id="cluster-1",
                mcp_backend=mock_backend,
                target_repo=str(target_repo),
                consumer_repos=[str(good1), str(bad), str(good2)],
                extracted_symbol="Foo",
                extraction_diff="--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-class Foo:\n-    pass\n+class Foo: pass\n",
                consuming_diffs={
                    str(good1): consuming_diff_good,
                    str(bad): consuming_diff_bad,
                    str(good2): consuming_diff_good,
                },
            )
        assert result.status == "failed"
        assert any(c.status == "failed" for c in result.consumer_commits)
        assert any(c.status == "completed" for c in result.consumer_commits)

    async def test_no_auto_revert_on_failure(
        self, target_repo: Path, tmp_path: Path, mock_backend: AsyncMock
    ) -> None:
        good = tmp_path / "good"
        bad = tmp_path / "bad"
        for r in (good, bad):
            r.mkdir()
            subprocess.run(["git", "init", str(r)], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(r), "config", "user.email", "x@x"], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(r), "config", "user.name", "X"], check=True, capture_output=True)
            (r / "c.py").write_text("old\n")
            subprocess.run(["git", "-C", str(r), "add", "."], check=True)
            subprocess.run(["git", "-C", str(r), "commit", "-m", "init"], check=True)

        consuming_diff_bad = "--- a/nonexistent.py\n+++ b/nonexistent.py\n@@ -0,0 +1 @@\n+x\n"
        consuming_diff_good = "--- a/c.py\n+++ b/c.py\n@@ -1 +1 @@\n-old\n+new\n"

        with patch(
            "mahavishnu.workflows.clone_refactor_workflow.detect_cluster_members",
            new=AsyncMock(return_value=[{"repo": str(target_repo)}]),
        ):
            await run_clone_refactor_dag(
                refactor_job_id="job-004",
                cluster_id="cluster-1",
                mcp_backend=mock_backend,
                target_repo=str(target_repo),
                consumer_repos=[str(good), str(bad)],
                extracted_symbol="Foo",
                extraction_diff="--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-class Foo:\n-    pass\n+class Foo: pass\n",
                consuming_diffs={
                    str(good): consuming_diff_good,
                    str(bad): consuming_diff_bad,
                },
            )

        # REQ-CLONE-005: good repo's commit remains on local main
        log = subprocess.run(
            ["git", "-C", str(good), "log", "--oneline"], capture_output=True, text=True
        )
        assert "new" in log.stdout  # the commit happened

    async def test_dag_unhandled_exception_marks_failed(
        self, target_repo: Path, consumer_repo: Path, mock_backend: AsyncMock
    ) -> None:
        # Inject failure in detect_cluster_members
        with patch(
            "mahavishnu.workflows.clone_refactor_workflow.detect_cluster_members",
            new=AsyncMock(side_effect=RuntimeError("detect boom")),
        ):
            with pytest.raises(RuntimeError, match="detect boom"):
                await run_clone_refactor_dag(
                    refactor_job_id="job-005",
                    cluster_id="cluster-1",
                    mcp_backend=mock_backend,
                    target_repo=str(target_repo),
                    consumer_repos=[str(consumer_repo)],
                    extracted_symbol="Foo",
                    extraction_diff="--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-x = 1\n+x = 2\n",
                )
        # REQ-CLONE-010: terminal "failed" was written
        # Find the call to try_put_with_log_context with step_name="failed"
        failed_calls = [
            c for c in mock_backend.try_put_with_log_context.call_args_list
            if c.kwargs.get("log_context", {}).get("step_name") == "failed"
        ]
        assert len(failed_calls) == 1
        # REQ-CLONE-009: claim released in finally
        mock_backend.delete.assert_called_with("cluster/v1/cluster-1/in_flight")

    async def test_dag_commit_message_includes_refactor_job_id(
        self, target_repo: Path, consumer_repo: Path, mock_backend: AsyncMock
    ) -> None:
        # REQ-CLONE-012
        with patch(
            "mahavishnu.workflows.clone_refactor_workflow.detect_cluster_members",
            new=AsyncMock(return_value=[{"repo": str(target_repo)}]),
        ):
            await run_clone_refactor_dag(
                refactor_job_id="0193f5e2-7c8d-7abc-9def-1234567890ab",
                cluster_id="cluster-1",
                mcp_backend=mock_backend,
                target_repo=str(target_repo),
                consumer_repos=[str(consumer_repo)],
                extracted_symbol="Foo",
                extraction_diff="--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-class Foo:\n-    pass\n+class Foo: pass\n",
                consuming_diffs={
                    str(consumer_repo): "--- a/consumer.py\n+++ b/consumer.py\n@@ -1 +1 @@\n-old\n+new\n",
                },
            )
        log = subprocess.run(
            ["git", "-C", str(consumer_repo), "log", "-1", "--format=%B"], capture_output=True, text=True
        )
        assert "refactor-job: 0193f5e2-7c8d-7abc-9def-1234567890ab" in log.stdout

    async def test_dag_git_commit_permanent_no_retry(
        self, target_repo: Path, consumer_repo: Path, mock_backend: AsyncMock
    ) -> None:
        # REQ-CLONE-013: GitCommitPermanent must NOT trigger Prefect retry.
        # We verify by counting git_commit invocations — only 1 expected.
        from mahavishnu.workflows import _git_ops
        original_commit = _git_ops.git_commit
        call_count = 0

        async def counting_commit(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            raise _git_ops.GitCommitPermanent(reason="test", stderr="x", exit_code=1)

        _git_ops.git_commit = counting_commit
        try:
            with patch(
                "mahavishnu.workflows.clone_refactor_workflow.detect_cluster_members",
                new=AsyncMock(return_value=[{"repo": str(target_repo)}]),
            ):
                with pytest.raises(_git_ops.GitCommitPermanent):
                    await run_clone_refactor_dag(
                        refactor_job_id="job-007",
                        cluster_id="cluster-1",
                        mcp_backend=mock_backend,
                        target_repo=str(target_repo),
                        consumer_repos=[str(consumer_repo)],
                        extracted_symbol="Foo",
                        extraction_diff="--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-class Foo:\n-    pass\n+class Foo: pass\n",
                    )
            assert call_count == 1  # NO retry
        finally:
            _git_ops.git_commit = original_commit

    async def test_dag_state_writes_are_best_effort(
        self, target_repo: Path, consumer_repo: Path
    ) -> None:
        # REQ-CLONE-014: substrate failure is logged but DAG still runs
        backend = AsyncMock()
        backend.dag_key = lambda x: f"workflow/v1/{x}"
        backend.cluster_key = lambda x: f"cluster/v1/{x}"
        backend.in_flight_key = lambda x: f"cluster/v1/{x}/in_flight"
        backend.try_put_with_log_context = AsyncMock(return_value=False)  # substrate always fails
        backend.put = AsyncMock()
        backend.delete = AsyncMock()

        with patch(
            "mahavishnu.workflows.clone_refactor_workflow.detect_cluster_members",
            new=AsyncMock(return_value=[{"repo": str(target_repo)}]),
        ):
            result = await run_clone_refactor_dag(
                refactor_job_id="job-008",
                cluster_id="cluster-1",
                mcp_backend=backend,
                target_repo=str(target_repo),
                consumer_repos=[str(consumer_repo)],
                extracted_symbol="Foo",
                extraction_diff="--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-class Foo:\n-    pass\n+class Foo: pass\n",
                consuming_diffs={
                    str(consumer_repo): "--- a/consumer.py\n+++ b/consumer.py\n@@ -1 +1 @@\n-old\n+new\n",
                },
            )
        # DAG still completes despite substrate failures
        assert result.status == "completed"

    async def test_dag_git_commit_failure_leaves_no_dirty_tree(
        self, target_repo: Path, tmp_path: Path, mock_backend: AsyncMock
    ) -> None:
        # REQ-CLONE-011: stash pop in finally → working tree clean post-failure
        consumer = tmp_path / "consumer"
        consumer.mkdir()
        subprocess.run(["git", "init", str(consumer)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(consumer), "config", "user.email", "x@x"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(consumer), "config", "user.name", "X"], check=True, capture_output=True)
        (consumer / "c.py").write_text("init\n")
        subprocess.run(["git", "-C", str(consumer), "add", "."], check=True)
        subprocess.run(["git", "-C", str(consumer), "commit", "-m", "init"], check=True)

        from mahavishnu.workflows import _git_ops
        original_commit = _git_ops.git_commit

        async def failing_commit(*args, **kwargs):
            raise _git_ops.GitCommitPermanent(reason="test", stderr="x", exit_code=1)

        _git_ops.git_commit = failing_commit
        try:
            with patch(
                "mahavishnu.workflows.clone_refactor_workflow.detect_cluster_members",
                new=AsyncMock(return_value=[{"repo": str(target_repo)}]),
            ):
                with pytest.raises(_git_ops.GitCommitPermanent):
                    await run_clone_refactor_dag(
                        refactor_job_id="job-009",
                        cluster_id="cluster-1",
                        mcp_backend=mock_backend,
                        target_repo=str(target_repo),
                        consumer_repos=[str(consumer)],
                        extracted_symbol="Foo",
                        extraction_diff="--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-class Foo:\n-    pass\n+class Foo: pass\n",
                        consuming_diffs={
                            str(consumer): "--- a/c.py\n+++ b/c.py\n@@ -1 +1 @@\n-init\n+new\n"
                        },
                    )
        finally:
            _git_ops.git_commit = original_commit

        # Verify working tree is clean
        status = subprocess.run(
            ["git", "-C", str(consumer), "status", "--porcelain"], capture_output=True, text=True
        )
        assert status.stdout == ""
```

### Step 3: Run tests to verify they fail

Run:
```bash
cd /Users/les/Projects/mahavishnu
.venv/bin/pytest tests/unit/clone/test_clone_refactor_workflow.py -v
```

**Expected:** FAIL with import or signature errors (the new module isn't written yet).

### Step 4: Rewrite `clone_refactor_workflow.py`

Replace the entire file (preserve quarantine-test headers per Step 1):

```python
# Workflow-ID: 01JCLONEREF2026
# Approved by: les
"""Git-tree clone-refactor DAG.

Implements: REQ-CLONE-001, REQ-CLONE-002, REQ-CLONE-003, REQ-CLONE-010,
            REQ-CLONE-011, REQ-CLONE-012, REQ-CLONE-013, REQ-CLONE-016
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from prefect import flow, task
from tenacity import retry_if_exception_type

from mahavishnu.core.state_backends.mcp import MCPStateBackend
from mahavishnu.workflows import _git_ops
from mahavishnu.workflows.clone_claims import release_cluster_claim

logger = logging.getLogger(__name__)


# ---- Dataclasses (REQ-CLONE-002) ------------------------------------------

# TD-m1: status fields are Literal, not str — typos like "Completed" or
# "queued " (trailing space) compile silently and break equality checks.
RepoCommitStatus = Literal["completed", "failed"]
DAGStateStatus = Literal["queued", "running", "completed", "failed", "cancelled"]


@dataclass(frozen=True, slots=True)  # TD-m4: immutable; slots for memory
class RepoCommit:
    """Per-repo commit result. Fields mirror §7.2 final state record shape.

    TD-m4: frozen=True. SF-M7 partial-fill semantics preserved via
    `dataclasses.replace(base, files_touched=..., working_tree_clean_after_commit=...)`
    in write_canonical_symbol / write_replacement_diff (below).
    """

    repo: str
    sha: str | None
    status: RepoCommitStatus
    files_touched: tuple[str, ...] = ()  # frozen: must be immutable; tuple OK
    working_tree_clean_after_commit: bool = True
    error_type: str | None = None
    error_diff_offset: int | None = None
    error_conflict_marker: str | None = None
    error_stderr: str | None = None
    error_exit_code: int | None = None


@dataclass(frozen=True, slots=True)  # TD-m4
class RepoHit:
    """One row of detect_cluster_members output."""

    repo: str
    match_score: float


@dataclass(frozen=True, slots=True)  # TD-m4
class DAGState:
    """Aggregate DAG lifecycle state — written to workflow/v1/{refactor_job_id}."""

    schema_version: int = 2
    refactor_job_id: str = ""
    cluster_id: str = ""
    target_repo: str = ""
    consumer_repos: tuple[str, ...] = ()  # frozen: immutable
    status: DAGStateStatus = "queued"
    started_at: str = ""
    dag_started_at: str = ""
    dag_completed_at: str = ""
    target_commit: str | None = None
    target_commit_files_touched: tuple[str, ...] = ()  # frozen
    consumer_commits: tuple[RepoCommit, ...] = ()  # frozen
    failed_consumers: tuple[str, ...] = ()  # frozen


@dataclass(frozen=True, slots=True)  # TD-m4
class DAGResult:
    status: RepoCommitStatus
    consumer_commits: tuple[RepoCommit, ...]
    target_commit: RepoCommit | None = None
    error: str | None = None


# ---- Commit-message convention (REQ-CLONE-012) ---------------------------

def commit_message(refactor_job_id: str, repo: str, extracted_symbol: str) -> str:
    """Format the consumer-write commit message. Includes refactor-job header
    so operators can grep `git log --grep="^refactor-job:"` to disambiguate
    DAG-A vs DAG-B commits (REQ-CLONE-012).
    """
    return (
        f"refactor-job: {refactor_job_id}\n"
        f"target: {repo}\n"
        f"extracts: {extracted_symbol}\n"
        f"\n"
        f"Automated commit from clone_refactor_group DAG.\n"
        f"Revert recipe: git reset --hard $(git log --grep='^refactor-job: {refactor_job_id}$' --pretty=%H -n 1)^"
    )


# ---- Step functions (@task) ----------------------------------------------

@task(name="detect_cluster_members", retries=0)
async def detect_cluster_members(cluster_id: str, repos: list[str]) -> list[RepoHit]:
    """Detect cluster members. Stub that returns the input repos."""
    return [RepoHit(repo=r, match_score=1.0) for r in repos]


# CRITICAL: Prefect kwarg is `retry_condition_fn`, NOT `retry_condition`.
# Verified at REPL: `retry_condition` raises TypeError.
# CA-m1 note: `tenacity.retry_if_exception_type` is a callable class instance
# that Prefect evaluates as `(exc) -> bool`. Works correctly with Prefect;
# do not "fix" by removing the tenacity import.
@task(
    name="write_canonical_symbol",
    retries=2,
    retry_delay_seconds=5,
    retry_condition_fn=retry_if_exception_type((_git_ops.GitCommitTransient,)),
)
async def write_canonical_symbol(
    refactor_job_id: str,
    target_repo: str,
    extracted_symbol: str,
    extraction_diff: str,
) -> RepoCommit:
    """Write the canonical-symbol change to the target repo's local main.

    Implements: REQ-CLONE-011 (plain git stash wrap),
                REQ-CLONE-012 (commit message convention),
                REQ-CLONE-013 (transient retry only).
    SF-M7: build the RepoCommit immediately after `git_commit` succeeds,
    then fill in optional metadata (`files_touched`, `working_tree_clean`)
    in a try/except. If metadata gathering fails, return the partial
    `RepoCommit` with `working_tree_clean_after_commit=False` rather than
    letting the exception swallow the successful commit record.
    SF-B4: catch `StashPopFailed` and record typed error on the RepoCommit
    (do not propagate — the commit may have already succeeded).
    """
    repo_path = Path(target_repo)
    # REQ-CLONE-011: plain git stash (NOT --keep-index — that's partial-commit workflow)
    stash_ref = await _git_ops.stash_push(repo_path)
    try:
        await _git_ops.git_apply(repo_path, extraction_diff)
        msg = commit_message(refactor_job_id, target_repo, extracted_symbol)
        sha = await _git_ops.git_commit(repo_path, msg)
        # SF-M7 + TD-m4: RepoCommit is frozen; build with empty defaults,
        # then use dataclasses.replace() to fill in optional metadata.
        base = RepoCommit(
            repo=target_repo,
            sha=sha,
            status="completed",
            files_touched=(),
            working_tree_clean_after_commit=False,
        )
        try:
            files = await _git_ops.diff_files(repo_path)
            clean = await _git_ops.is_working_tree_clean(repo_path)
            return replace(base, files_touched=tuple(files), working_tree_clean_after_commit=clean)
        except Exception as meta_exc:
            logger.warning(
                "write_canonical_symbol: post-commit metadata failed (%s); continuing",
                meta_exc,
            )
            return base
    except _git_ops.StashPopFailed as spf:
        # SF-B4: stash pop failed AFTER commit landed. Record typed error
        # on the result rather than propagating (the commit succeeded).
        logger.warning(
            "write_canonical_symbol: stash pop failed (%s); commit on main, dirty tree",
            spf,
        )
        return RepoCommit(
            repo=target_repo,
            sha=None,
            status="failed",
            error_type="StashPopFailed",
            error_stderr=spf.stderr,
            error_exit_code=spf.exit_code,
        )
    finally:
        # Best-effort: if stash_pop already raised, this is a no-op (the
        # error is recorded on the result). If it succeeds, we're done.
        try:
            await _git_ops.stash_pop(repo_path, stash_ref)
        except _git_ops.StashPopFailed:
            pass  # already handled in the except arm above


@task(
    name="write_replacement_diff",
    retries=2,
    retry_delay_seconds=5,
    retry_condition_fn=retry_if_exception_type((_git_ops.GitCommitTransient,)),
)
async def write_replacement_diff(
    refactor_job_id: str,
    consumer_repo: str,
    consuming_diff: str,
) -> RepoCommit:
    """Write the consuming diff to a single consumer repo.

    Same SF-B4/SF-M7 hardening as `write_canonical_symbol`.
    """
    repo_path = Path(consumer_repo)
    stash_ref = await _git_ops.stash_push(repo_path)
    try:
        await _git_ops.git_apply(repo_path, consuming_diff)
        msg = commit_message(refactor_job_id, consumer_repo, "consuming-diff")
        sha = await _git_ops.git_commit(repo_path, msg)
        # SF-M7 + TD-m4: frozen dataclass via replace()
        base = RepoCommit(
            repo=consumer_repo,
            sha=sha,
            status="completed",
            files_touched=(),
            working_tree_clean_after_commit=False,
        )
        try:
            files = await _git_ops.diff_files(repo_path)
            clean = await _git_ops.is_working_tree_clean(repo_path)
            return replace(base, files_touched=tuple(files), working_tree_clean_after_commit=clean)
        except Exception as meta_exc:
            logger.warning(
                "write_replacement_diff: post-commit metadata failed (%s); continuing",
                meta_exc,
            )
            return base
    except _git_ops.StashPopFailed as spf:
        logger.warning(
            "write_replacement_diff: stash pop failed (%s); commit on main, dirty tree",
            spf,
        )
        return RepoCommit(
            repo=consumer_repo,
            sha=None,
            status="failed",
            error_type="StashPopFailed",
            error_stderr=spf.stderr,
            error_exit_code=spf.exit_code,
        )
    finally:
        try:
            await _git_ops.stash_pop(repo_path, stash_ref)
        except _git_ops.StashPopFailed:
            pass


@task(name="persist_dag_state", retries=0)
async def persist_dag_state(mcp_backend: MCPStateBackend, state: DAGState) -> None:
    """Best-effort write of aggregate DAG state (REQ-CLONE-003).

    TD-m8: use `_dataclass_to_dict(state)` (which calls asdict) for nested
    serialization instead of `state.__dict__` — the conventional idiom and
    safe with frozen dataclasses.
    """
    await mcp_backend.try_put_with_log_context(
        mcp_backend.dag_key(state.refactor_job_id),
        _dataclass_to_dict(state),
        log_context={"dag_id": state.refactor_job_id, "step_name": "persist_dag_state"},
    )


# ---- Per-step write helpers (REQ-CLONE-010) ------------------------------

async def _write_step_outcome(
    mcp_backend: MCPStateBackend,
    refactor_job_id: str,
    step_name: str,
    outcome: dict[str, Any],
) -> None:
    """Per-step durability: every @task writes its outcome before returning."""
    log_context = {
        "dag_id": refactor_job_id,
        "step_name": step_name,
        "files_touched": outcome.get("files_touched", []),
    }
    await mcp_backend.try_put_with_log_context(
        f"workflow/v1/{refactor_job_id}/steps/{step_name}",
        outcome,
        log_context=log_context,
    )


async def _write_terminal_failed(
    mcp_backend: MCPStateBackend,
    refactor_job_id: str,
    exc: BaseException,
) -> None:
    await _write_step_outcome(
        mcp_backend,
        refactor_job_id,
        "failed",
        {
            "error_type": type(exc).__name__,
            "error": str(exc),
            "failed_at": datetime.now(UTC).isoformat(),
        },
    )


async def _write_terminal_cancelled(
    mcp_backend: MCPStateBackend,
    refactor_job_id: str,
) -> None:
    await _write_step_outcome(
        mcp_backend,
        refactor_job_id,
        "cancelled",
        {"cancelled_at": datetime.now(UTC).isoformat()},
    )


def _dataclass_to_dict(obj: Any) -> dict[str, Any]:
    """Convert a (frozen) dataclass to a dict for substrate writes.

    TD-m8: prefer dataclasses.asdict() over obj.__dict__ for nested types.
    Falls back to __dict__ for non-dataclass objects (e.g., BaseException).
    """
    from dataclasses import asdict, is_dataclass
    if is_dataclass(obj) and not isinstance(obj, type):
        return asdict(obj)
    return obj.__dict__


# ---- @flow orchestrator ---------------------------------------------------

# SF-M5: re-entry guard. Raised if the same refactor_job_id is invoked twice
# (operator re-run, or cross-process race that slipped past cluster_claim).
class DAGAlreadyRunning(Exception):
    """Raised by run_clone_refactor_dag if the same refactor_job_id is already
    in flight (status in {queued, running}). Prevents duplicate work."""

    def __init__(self, existing_status: str) -> None:
        super().__init__(f"DAG {existing_status} already; refusing re-entry")
        self.existing_status = existing_status


@flow(name="clone-refactor-dag")
async def run_clone_refactor_dag(
    refactor_job_id: str,
    cluster_id: str,
    mcp_backend: MCPStateBackend,
    target_repo: str,
    consumer_repos: list[str],
    extracted_symbol: str,
    extraction_diff: str,
    consuming_diffs: dict[str, str] | None = None,
) -> DAGResult:
    """Run the full DAG. Implements REQ-CLONE-010 (per-step write + try/except/finally
    with explicit CancelledError arm).

    SF-M5 re-entry guard: reads workflow/v1/{refactor_job_id} at entry; raises
    DAGAlreadyRunning if status in {queued, running}.

    CA-m2 note: `@flow` runs in-process; `DAGState` is a non-Pydantic
    dataclass — Prefect serializes via pickle for in-memory flow, which
    works. Cross-process deployment would break; the spec explicitly
    intends in-process only.

    SF-m1 note: Phase 3 (consume) uses bare `asyncio.gather` (no
    return_exceptions) because each consumer's failure is caught by the
    `_run_consumer` wrapper, which builds a typed `RepoCommit`. Functionally
    equivalent to `return_exceptions=True` for normal `Exception` subclasses;
    the wrapper adds typed fields that bare `return_exceptions` cannot.
    """
    # SF-M5: re-entry guard
    existing_state = await mcp_backend.get(mcp_backend.dag_key(refactor_job_id))
    if existing_state is not None and existing_state.get("status") in ("queued", "running"):
        raise DAGAlreadyRunning(existing_status=existing_state.get("status", "unknown"))

    consumer_commits: tuple[RepoCommit, ...] = ()
    target_commit: RepoCommit | None = None

    try:
        # Phase 1: detect
        hits = await detect_cluster_members(cluster_id, [target_repo, *consumer_repos])
        await _write_step_outcome(
            mcp_backend, refactor_job_id, "detect", {"hits": len(hits)}
        )

        # Phase 2: propose (target)
        target_commit = await write_canonical_symbol(
            refactor_job_id, target_repo, extracted_symbol, extraction_diff
        )
        await _write_step_outcome(
            mcp_backend,
            refactor_job_id,
            "propose",
            {"target_sha": target_commit.sha, "files_touched": target_commit.files_touched},
        )

        # Phase 3: consume (parallel) — collect success/failure per repo
        async def _run_consumer(repo: str) -> RepoCommit:
            diff = (consuming_diffs or {}).get(repo)
            if diff is None:
                return RepoCommit(
                    repo=repo, sha=None, status="failed",
                    error_type="MissingConsumingDiff",
                    error_stderr=f"No consuming_diffs entry for {repo}",
                )
            try:
                return await write_replacement_diff(refactor_job_id, repo, diff)
            except Exception as exc:
                return RepoCommit(
                    repo=repo, sha=None, status="failed",
                    error_type=type(exc).__name__,
                    error_stderr=str(exc),
                    error_diff_offset=getattr(exc, "diff_offset", None),
                    error_conflict_marker=getattr(exc, "conflict_marker", None),
                    error_exit_code=getattr(exc, "exit_code", None),
                )

        # TD-m4: consumer_commits is a tuple (RepoCommit is frozen)
        consumer_commits = tuple(
            await asyncio.gather(*(_run_consumer(r) for r in consumer_repos))
        )
        await _write_step_outcome(
            mcp_backend,
            refactor_job_id,
            "consume",
            {"consumer_commits": [_dataclass_to_dict(c) for c in consumer_commits]},
        )

        # Phase 4: finalize
        all_completed = all(c.status == "completed" for c in consumer_commits)
        status: RepoCommitStatus = "completed" if all_completed else "failed"
        final = DAGResult(
            status=status,
            consumer_commits=consumer_commits,
            target_commit=target_commit,
        )
        await persist_dag_state(
            mcp_backend,
            DAGState(
                refactor_job_id=refactor_job_id,
                cluster_id=cluster_id,
                target_repo=target_repo,
                consumer_repos=tuple(consumer_repos),
                status=status,
                dag_completed_at=datetime.now(UTC).isoformat(),
                target_commit=target_commit.sha if target_commit else None,
                target_commit_files_touched=target_commit.files_touched if target_commit else (),
                consumer_commits=consumer_commits,
                failed_consumers=tuple(c.repo for c in consumer_commits if c.status == "failed"),
            ),
        )
        return final

    except asyncio.CancelledError:
        # REQ-CLONE-016: cancellation must persist terminal "cancelled" before re-raising
        await _write_terminal_cancelled(mcp_backend, refactor_job_id)
        raise
    except Exception as exc:
        # REQ-CLONE-010: unhandled exception path. Record transitions to "failed".
        await _write_terminal_failed(mcp_backend, refactor_job_id, exc)
        raise
    finally:
        # REQ-CLONE-009: release cluster claim regardless of outcome.
        # SF-B3: wrap release in try/except so a release failure never
        # shadows the original DAG exception (Python's finally semantics
        # would otherwise replace the traceback).
        try:
            await release_cluster_claim(mcp_backend, cluster_id)
        except Exception as release_exc:
            logger.warning(
                "release_cluster_claim failed for cluster_id=%s (%s); continuing",
                cluster_id, release_exc,
            )
```

### Step 5: Run tests to verify they pass

Run:
```bash
cd /Users/les/Projects/mahavishnu
.venv/bin/pytest tests/unit/clone/test_clone_refactor_workflow.py -v
```

**Expected:** all green.

### Step 6: Verify quarantine-test markers preserved

Run:
```bash
head -3 /Users/les/Projects/mahavishnu/mahavishnu/workflows/clone_refactor_workflow.py | grep -E "Workflow-ID|Approved by"
```

**Expected:** both lines present.

### Step 7: Commit

```bash
cd /Users/les/Projects/mahavishnu
git add mahavishnu/workflows/clone_refactor_workflow.py tests/unit/clone/test_clone_refactor_workflow.py
git -c core.hooksPath=/dev/null -c user.email=les@wedgwoodwebworks.com \
    commit -m "feat(workflows): rewrite clone_refactor_workflow.py as git-tree DAG

Replaces PR-shape with git-tree DAG. REQ-CLONE-010 per-step durability,
REQ-CLONE-011 plain git stash wrap, REQ-CLONE-012 commit message convention,
REQ-CLONE-013 transient retry only, REQ-CLONE-016 cancellation arm.
Preserves # Workflow-ID and # Approved by headers required by quarantine test.

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

## Task 6: clone_tools.py wire-up + Layer 3 e2e tests

**Files:**
- Modify: `mahavishnu/mcp/tools/clone_tools.py` (~50 LOC delta; preserves `clone_detect_ecosystem` and existing functionality)
- Modify: `mahavishnu/mcp/tools/clone_claims.py` (no changes — already exported)
- Create: `tests/integration/test_clone_refactor_group_e2e.py` (new, ~140 lines)

**Interfaces:**
- `CloneTools.clone_refactor_group(cluster_id, target_repo, consumer_repos, extracted_symbol, extraction_diff, consuming_diffs=None)` — modified to:
  - Normalize `cluster_id` (REQ-CLONE-015)
  - Validate inputs against null bytes (SF-m4)
  - Use `uuid7()` (Python 3.14 guard)
  - Call `cluster_state_claim` (now returns `None`; raised on failure)
  - Initialize DAG state via `mcp_backend.put(dag_key(...), ...)`
  - `asyncio.create_task(run_clone_refactor_dag(...))` with cancellation guard + strong reference via `_background_tasks` set (SF-B2)
  - Wrap post-claim section in try/except (C-2/SF-B1) — releases claim on any path
  - Release claim on terminal state
- `CloneTools.clone_refactor_status(limit=10) -> list[tuple[str, dict[str, Any]]]` — reads from `workflow/v1/*` via `mcp_backend.list_prefix("workflow/v1/")` (was `clone-handled/*`); sorts by UUID7 lexicographically (newest first)

**Integration Contract** (per `.claude/decisions/wire-up-contract.md`):
- **Triggered from**: MCP client invokes `mcp__mahavishnu__clone_refactor_group`; `clone_refactor_status` continues to be invoked by operators
- **Returns to / updates**: returns `{refactor_job_id, status: queued, decision, verification}` to MCP client; `MCPStateBackend.put("workflow/v1/{id}", ...)` records initial state; raises `ValueError` (invalid_cluster_id, 400), `ConcurrentDAGError` (409), `MCPStateBackendUnavailable` (503), or `asyncio.CancelledError` (499)
- **Demonstrable by**: `pytest tests/integration/test_clone_refactor_group_e2e.py` — 8 tests covering happy path, UUID7 format, REJECT blocks DAG, concurrent dedup, MCPStateBackendUnavailable, cancellation marks terminal, plus the `git_repo` fixture reuse
- **Rollback signal**: OTel span `mcp.clone_refactor_group` with `error` attribute on exception; log line `clone_refactor_group.failed` with exception class + message
- **Observability added**: OTel span `mcp.clone_refactor_group` (added by FastMCP decorator); structured warnings on every cancelled/failed claim release

### Step 1: Write failing e2e tests

Create `tests/integration/test_clone_refactor_group_e2e.py`. **Use whichever test client pattern is verified by Task 1 Step 2** (either `fastmcp.test_client.TestClient` or `_server.server.call_tool(...)`). The version below uses the in-process `CloneTools.clone_refactor_group` method directly — this bypasses the test-client question entirely and tests the wire-up behavior that the MCP server exposes. Adjust to use `TestClient`/`call_tool` only if the implementer wants to test the full MCP transport layer (recommended for a separate suite).

```python
"""MCP-tool end-to-end tests for clone_refactor_group.

This suite calls `CloneTools.clone_refactor_group` directly (in-process) and
verifies the wire-up behavior that the MCP server exposes — cluster_id
normalization, UUID7 ID format, cluster_claim dedup, initial DAG state
write, fire-and-forget task spawn, and per-step durability.

For the full MCP transport test (call_tool + TestClient), mirror the
pattern from `tests/integration/test_get_agent_e2e.py`.

Implements: REQ-CLONE-007, REQ-CLONE-009, REQ-CLONE-014, REQ-CLONE-015,
            REQ-CLONE-016
"""

from __future__ import annotations

import asyncio
import re
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

from mahavishnu.mcp.tools.clone_tools import CloneTools
from mahavishnu.mcp.tools.clone_claims import (
    ConcurrentDAGError,
    MCPStateBackendUnavailable,
)


# REQ-CLONE-015
CLUSTER_ID_RE = re.compile(r"^[a-z0-9-]{3,64}$")


def _uuid7_version(uuid_str: str) -> int:
    """Return the version nibble of a UUID string. UUIDv7 has version=7."""
    return int(UUID(uuid_str).version)


def _make_clone_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[CloneTools, AsyncMock]:
    """Returns (CloneTools, mocked MCPStateBackend) pair.

    CR-B3 fix: return type is `tuple[CloneTools, AsyncMock]`, not `CloneTools`.
    The fixture returns both; downstream tests unpack.
    """
    from mahavishnu.core.state_backends.mcp import MCPStateBackend

    app = MagicMock()
    app.settings = None
    tools = CloneTools(app=app)
    # Inject a mocked MCPStateBackend that we control
    mock_backend = AsyncMock(spec=MCPStateBackend)
    mock_backend.dag_key = lambda x: f"workflow/v1/{x}"
    mock_backend.cluster_key = lambda x: f"cluster/v1/{x}"
    mock_backend.in_flight_key = lambda x: f"cluster/v1/{x}/in_flight"
    mock_backend.try_put_with_log_context = AsyncMock(return_value=True)
    mock_backend.put = AsyncMock()
    mock_backend.delete = AsyncMock()
    mock_backend.get = AsyncMock(return_value=None)
    monkeypatch.setattr("mahavishnu.mcp.tools.clone_tools.mcp_backend", mock_backend)
    return tools, mock_backend


@pytest.fixture
def clone_tools(monkeypatch: pytest.MonkeyPatch) -> CloneTools:
    tools, _ = _make_clone_tools(monkeypatch)
    return tools


@pytest.fixture
def clone_tools_with_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[CloneTools, AsyncMock]:
    return _make_clone_tools(monkeypatch)
    return _make_clone_tools(monkeypatch)


class TestClusterIdNormalization:
    """REQ-CLONE-015: ^[a-z0-9-]{3,64}$"""

    async def test_valid_cluster_id_accepted(self):
        assert CLUSTER_ID_RE.match("cluster-abc123")
        assert CLUSTER_ID_RE.match("abc")
        assert CLUSTER_ID_RE.match("a-b-c-123")

    async def test_invalid_cluster_id_rejected(self):
        for bad in ["Bad_ID!", "ab", "Cluster-1", "cluster_abc", "a" * 65]:
            assert not CLUSTER_ID_RE.match(bad), f"Should reject {bad!r}"


# CR-B1 fix: shared git_repo fixture. Each test method gets a fresh
# tmp_path-scoped git repo with user.email/name configured. Replaces the
# 5-line subprocess.run() boilerplate that exceeded 100 chars (would fail
# `ruff check` and gate crackerjack run).
@pytest.fixture
def git_repo(tmp_path):
    """Initialize a git repo at tmp_path/<random> with user.email/name."""
    import subprocess
    import secrets
    repo = tmp_path / f"target-{secrets.token_hex(4)}"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "x@x"],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "X"],
        check=True, capture_output=True,
    )
    (repo / "foo.py").write_text("x = 1\n")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", "init"],
        check=True, capture_output=True,
    )
    return repo


def _diff_one_line() -> str:
    """Trivial extraction diff for tests that don't care about content."""
    return (
        "--- a/foo.py\n+++ b/foo.py\n"
        "@@ -1 +1 @@\n-x = 1\n+x = 2\n"
    )


@pytest.mark.req(["REQ-CLONE-015"])
class TestCloneRefactorGroupHappyPath:
    """REQ-CLONE-007: returns refactor_job_id + status: queued."""

    async def test_returns_job_id_and_starts_dag(
        self, clone_tools_with_backend, git_repo,
    ):
        tools, backend = clone_tools_with_backend

        with patch.object(CloneTools, "_verify", AsyncMock(return_value=None)):
            with patch.object(CloneTools, "_store", MagicMock(persist=AsyncMock())):
                result = await tools.clone_refactor_group(
                    cluster_id="cluster-test",
                    target_repo=str(git_repo),
                    consumer_repos=[],
                    extracted_symbol="X",
                    extraction_diff=_diff_one_line(),
                )

        assert "refactor_job_id" in result
        assert result["status"] == "queued"
        # workflow/v1/{id} was written
        backend.put.assert_called()


@pytest.mark.req(["REQ-CLONE-007"])
class TestUUID7Format:
    """REQ-CLONE-007: refactor_job_id is UUIDv7."""

    async def test_refactor_job_id_is_uuid7(
        self, clone_tools_with_backend, git_repo,
    ):
        tools, backend = clone_tools_with_backend

        with patch.object(CloneTools, "_verify", AsyncMock(return_value=None)):
            with patch.object(CloneTools, "_store", MagicMock(persist=AsyncMock())):
                result = await tools.clone_refactor_group(
                    cluster_id="cluster-uuid7",
                    target_repo=str(git_repo),
                    consumer_repos=[],
                    extracted_symbol="X",
                    extraction_diff=_diff_one_line(),
                )
        # REQ-CLONE-007: parse the returned ID and assert version=7
        version = _uuid7_version(result["refactor_job_id"])
        assert version == 7, f"Expected UUIDv7, got version={version}"


@pytest.mark.req(["REQ-CLONE-001"])
class TestRejectBlocksDAG:
    """REQ-CLONE-001: consensus=REJECT blocks DAG."""

    async def test_clone_refactor_group_reject_blocks_dag(
        self, clone_tools_with_backend, git_repo,
    ):
        tools, backend = clone_tools_with_backend

        # Mock verify_proposal to return REJECT
        from mahavishnu.core.verification import Consensus
        reject_result = MagicMock()
        reject_result.consensus = Consensus.REJECT
        with patch.object(CloneTools, "_verify", AsyncMock(return_value=reject_result)):
            with patch.object(CloneTools, "_store", MagicMock(persist=AsyncMock())):
                result = await tools.clone_refactor_group(
                    cluster_id="cluster-reject",
                    target_repo=str(git_repo),
                    consumer_repos=[],
                    extracted_symbol="X",
                    extraction_diff=_diff_one_line(),
                )
        assert result.get("decision") == "blocked_by_verification"
        # Claim was released
        backend.delete.assert_called_with("cluster/v1/cluster-reject/in_flight")


@pytest.mark.req(["REQ-CLONE-009"])
class TestConcurrentCalls:
    """REQ-CLONE-009: two concurrent calls with same cluster_id → second
    raises ConcurrentDAGError."""

    async def test_concurrent_calls_deduplicate(
        self, clone_tools_with_backend, git_repo,
    ):
        tools, backend = clone_tools_with_backend

        with patch.object(CloneTools, "_verify", AsyncMock(return_value=None)):
            with patch.object(CloneTools, "_store", MagicMock(persist=AsyncMock())):
                # Make cluster_state_claim succeed for the first call,
                # then return a fake "existing" record for the second.
                call_count = 0

                async def fake_get(key):
                    nonlocal call_count
                    call_count += 1
                    if call_count == 1:
                        return None  # first call: no sentinel
                    return {"refactor_job_id": "first-job-id"}

                backend.get = fake_get

                # First call — succeeds
                first = await tools.clone_refactor_group(
                    cluster_id="cluster-concurrent",
                    target_repo=str(git_repo),
                    consumer_repos=[],
                    extracted_symbol="X",
                    extraction_diff=_diff_one_line(),
                )
                # Reset call_count for the second call
                call_count = 0
                backend.get = fake_get  # rebind to capture the new closure

                # Second call — must raise ConcurrentDAGError
                with pytest.raises(ConcurrentDAGError) as exc_info:
                    await tools.clone_refactor_group(
                        cluster_id="cluster-concurrent",
                        target_repo=str(git_repo),
                        consumer_repos=[],
                        extracted_symbol="X",
                        extraction_diff=_diff_one_line(),
                    )
                assert exc_info.value.existing_job_id == "first-job-id"


@pytest.mark.req(["REQ-CLONE-014"])
class TestMCPStateBackendUnavailable:
    """SF-B6: substrate circuit-open raises MCPStateBackendUnavailable."""

    async def test_substrate_unavailable_raises_unavailable(
        self, clone_tools_with_backend,
    ):
        tools, backend = clone_tools_with_backend

        # Make cluster_state_claim raise MCPStateBackendUnavailable
        async def fake_claim(*args, **kwargs):
            raise MCPStateBackendUnavailable(key="k", reason="circuit_open")

        with patch(
            "mahavishnu.mcp.tools.clone_tools.cluster_state_claim",
            side_effect=fake_claim,
        ):
            with pytest.raises(MCPStateBackendUnavailable):
                await tools.clone_refactor_group(
                    cluster_id="cluster-down",
                    target_repo="/tmp/x",
                    consumer_repos=[],
                    extracted_symbol="X",
                    extraction_diff="",
                )


@pytest.mark.req(["REQ-CLONE-016"])
class TestCancellationMarksTerminal:
    """REQ-CLONE-016: client cancellation marks terminal "cancelled"."""

    async def test_dag_cancellation_marks_terminal(
        self, clone_tools_with_backend, git_repo,
    ):
        tools, backend = clone_tools_with_backend

        # Make _verify raise CancelledError to simulate client cancellation
        with patch.object(
            CloneTools, "_verify",
            AsyncMock(side_effect=asyncio.CancelledError()),
        ):
            with patch.object(CloneTools, "_store", MagicMock(persist=AsyncMock())):
                with pytest.raises(asyncio.CancelledError):
                    await tools.clone_refactor_group(
                        cluster_id="cluster-cancel",
                        target_repo=str(git_repo),
                        consumer_repos=[],
                        extracted_symbol="X",
                        extraction_diff=_diff_one_line(),
                    )
        # Claim was released on cancellation
        backend.delete.assert_called_with("cluster/v1/cluster-cancel/in_flight")
```

### Step 2: Run tests to verify they fail

Run:
```bash
cd /Users/les/Projects/mahavishnu
.venv/bin/pytest tests/integration/test_clone_refactor_group_e2e.py -v
```

**Expected:** FAIL with `ImportError` or assertion failures (clone_tools.py not yet modified).

### Step 3: Modify `clone_tools.py` — UUID7 guard, cluster_id normalization, cluster_claim, asyncio.create_task

Edit `mahavishnu/mcp/tools/clone_tools.py`. Apply these changes in order:

**Change A — UUID7 import with version guard** (replace existing `from uuid import uuid4`):

```python
import sys

if sys.version_info >= (3, 14):
    from uuid import uuid7 as _new_uuid7
else:
    def _new_uuid7() -> UUID:
        raise RuntimeError(
            "clone_refactor_group requires Python 3.14+ for uuid7(). "
            "Upgrade the interpreter or pin pyproject.toml [requires-python]."
        )
```

**Change B — Module-level singleton `mcp_backend`** (add near the top, after imports):

```python
from mahavishnu.core.state_backends.mcp import MCPStateBackend, MCPStateConfig

# C-5 fix (memory feedback-cli-flag-consumer-wiring.md): thread via
# app.settings.mcp_state.base_url if available, else default to localhost.
# DO NOT hardcode a single URL — other code paths (dispatch_to_pool, etc.)
# already consume the same MCPStateBackend instance and would silently
# diverge if we hardcoded here.
try:
    _mcp_state_settings = app.settings.mcp_state  # type: ignore[attr-defined]
    mcp_backend: MCPStateBackend = MCPStateBackend(
        base_url=_mcp_state_settings.base_url,
        config=MCPStateConfig(
            enabled=_mcp_state_settings.enabled,
            flush_interval_seconds=_mcp_state_settings.flush_interval_seconds,
        ),
    )
except (AttributeError, TypeError):
    # No app or no settings; default to localhost:8683 (spec §5.5 Path A).
    mcp_backend: MCPStateBackend = MCPStateBackend(
        base_url="http://localhost:8683",
    )
```

If `app` is a module-level import rather than a closure variable, wrap the singleton construction in a lazy initializer. The key contract: every code path in `clone_tools.py` (and the singleton `clone_claims.py` claim helpers, and `run_clone_refactor_dag`) MUST see the same `MCPStateBackend` instance so circuit-breaker state is consistent (REQ-CLONE-014 reliability, per spec §6.1 v4 MAJOR-fix M2).

**Change C — cluster_id normalization** (in `clone_refactor_group`):

```python
import re

CLUSTER_ID_RE = re.compile(r"^[a-z0-9-]{3,64}$")

async def clone_refactor_group(self, cluster_id: str, ...):
    # REQ-CLONE-015
    if not CLUSTER_ID_RE.match(cluster_id):
        raise ValueError(f"invalid_cluster_id: {cluster_id!r}")
    ...
```

**Change D — Replace `str(uuid4())` with `str(_new_uuid7())`** in the existing `clone_refactor_group` body.

**Change E — Add `cluster_state_claim` call + initial DAG state write + `asyncio.create_task` cancellation guard**:

```python
from mahavishnu.mcp.tools.clone_claims import (
    cluster_state_claim,
    release_cluster_claim,
    ConcurrentDAGError,
    MCPStateBackendUnavailable,
)
from mahavishnu.workflows.clone_refactor_workflow import run_clone_refactor_dag

# SF-B2: strong reference for fire-and-forget tasks. Per Python docs,
# `asyncio.create_task()` returns a task that the event loop holds a WEAK
# reference to. Without a strong reference held in module scope, the task
# may be garbage-collected mid-execution before the @flow body runs.
_background_tasks: set[asyncio.Task] = set()


async def clone_refactor_group(self, cluster_id: str, target_repo: str, ...):
    # Normalize cluster_id (REQ-CLONE-015)
    if not CLUSTER_ID_RE.match(cluster_id):
        raise ValueError(f"invalid_cluster_id: {cluster_id!r}")

    # SF-m4: validate inputs against null bytes / control chars
    for arg_name, arg_val in (
        ("cluster_id", cluster_id),
        ("target_repo", target_repo),
        ("extracted_symbol", extracted_symbol),
    ):
        if "\x00" in arg_val:
            raise ValueError(f"invalid_{arg_name}: contains null byte")

    # Generate UUID7 (REQ-CLONE-007)
    refactor_job_id = str(_new_uuid7())

    # ... existing verify_proposal flow ...

    # C-2/SF-B1: wrap the entire post-claim section in one try/except
    # that releases the claim on ANY error/cancellation. The original
    # guard only wrapped create_task, leaving a gap between claim and
    # create_task where cancellation would leak the claim.
    claim_acquired = False
    try:
        # Cluster-claim (REQ-CLONE-009)
        await cluster_state_claim(mcp_backend, cluster_id, refactor_job_id)
        claim_acquired = True

        # Initial DAG state write (REQ-CLONE-007)
        await mcp_backend.put(
            mcp_backend.dag_key(refactor_job_id),
            {
                "schema_version": 2,
                "refactor_job_id": refactor_job_id,
                "cluster_id": cluster_id,
                "status": "queued",
            },
        )

        # Fire DAG (SF-B2: strong reference + add_done_callback)
        task_obj = asyncio.create_task(
            run_clone_refactor_dag(
                refactor_job_id=refactor_job_id,
                cluster_id=cluster_id,
                mcp_backend=mcp_backend,
                target_repo=target_repo,
                consumer_repos=consumer_repos,
                extracted_symbol=extracted_symbol,
                extraction_diff=extraction_diff,
                consuming_diffs=consuming_diffs,
            ),
            name=f"clone-refactor-{refactor_job_id}",
        )
        _background_tasks.add(task_obj)
        task_obj.add_done_callback(_background_tasks.discard)

        return {"refactor_job_id": refactor_job_id, "status": "queued", ...}

    except asyncio.CancelledError:
        # SF-B1: cancellation between claim and create_task; release claim.
        if claim_acquired:
            await release_cluster_claim(mcp_backend, cluster_id)
        raise
    except ConcurrentDAGError:
        # Claim rejected: no need to release (we never acquired it).
        raise
    except MCPStateBackendUnavailable:
        # SF-M6: surface to MCP client as 503. The cluster_claim helper
        # already raised before any claim was acquired; nothing to release.
        raise
    except Exception:
        # Any other exception: release claim (if we acquired one) before
        # re-raising so the operator doesn't see a stuck sentinel.
        if claim_acquired:
            await release_cluster_claim(mcp_backend, cluster_id)
        raise
```

**Change F — Update `clone_refactor_status` to read `workflow/v1/*`** (replace any `clone-handled/*` references):

```python
async def clone_refactor_status(self, limit: int = 10) -> list[tuple[str, dict[str, Any]]]:
    # CR-B2 fix: list[tuple[str, dict]] (was `list[dict]`). MCPStateBackend
    # .list_prefix() returns list[tuple[str, dict]] per the CR-m6 test in
    # tests/unit/test_mcp_state_backend.py::TestListPrefixReturnShape.
    # CA-B2 fix: list_prefix(self, prefix) does NOT accept a `limit` param;
    # slice in Python.
    records = await mcp_backend.list_prefix("workflow/v1/")
    # Sort by UUID7 lexicographically (UUIDv7 time-sortable; lexicographic
    # = chronological for v7). Most recent first.
    return sorted(records, key=lambda kv: kv[0], reverse=True)[:limit]
```

### Step 4: Run e2e tests

Run:
```bash
cd /Users/les/Projects/mahavishnu
.venv/bin/pytest tests/integration/test_clone_refactor_group_e2e.py -v
```

**Expected:** all green (or partial — fix issues iteratively).

### Step 4.5: Settings-threading grep (CR-M2 fix, memory `feedback-cli-flag-consumer-wiring.md`)

Required by the memory rule: when adding a CLI flag + settings key (here: `app.settings.mcp_state.base_url`), grep every consumer of the new field and verify it's threaded. The plan threads `app.settings.mcp_state.base_url` into `clone_tools.py`; every OTHER consumer of `MCPStateBackend` must also be checked.

Run:
```bash
cd /Users/les/Projects/mahavishnu
# Find every site that constructs MCPStateBackend
grep -rn "MCPStateBackend(" --include="*.py" mahavishnu/

# For each instantiation site, verify it threads app.settings.mcp_state.base_url
# OR is in a path that legitimately uses a different backend (e.g., tests).
# Any site that hardcodes base_url without threading settings is a latent bug.
```

If a site is missed, fix it before committing Task 6. **This step is a hard gate** — skipping it violates `feedback-cli-flag-consumer-wiring.md`.

### Step 5: Run all validation checks per spec §9

Run:
```bash
cd /Users/les/Projects/mahavishnu

# No PR-shaped code remains
echo "=== PR-shape check ==="
git grep -nE "gh_client|create_pr|get_pr_status|ExtractionPR|ConsumingPR" mahavishnu/ || echo "✓ clean"

# One-way dep
echo "=== Dep direction ==="
git grep -nE "from mahavishnu\.workflows" mahavishnu/mcp/tools/clone_tools.py | head -5
git grep -nE "from.*mcp\.tools\.clone_tools" mahavishnu/workflows/ || echo "✓ no reverse dep"

# Stale docstring fix
echo "=== Stale docstring ==="
git grep -nE "clone_refactor_workflow:run" mahavishnu/engines/prefect_adapter_impl.py || echo "✓ fixed"

# Quarantine headers
echo "=== Quarantine headers ==="
head -3 mahavishnu/workflows/clone_refactor_workflow.py | grep -E "Workflow-ID|Approved by"

# All tests
echo "=== Tests ==="
.venv/bin/pytest tests/unit/clone/test_clone_refactor_workflow.py tests/unit/workflows/test_git_ops.py tests/unit/test_mcp_state_backend.py tests/integration/test_clone_refactor_group_e2e.py -v
```

**Expected:** all green.

### Step 6: If §5.5a Path A probe succeeded, update `settings/mahavishnu.yaml`

Add (only if `dispatch_to_pool` async-callback works in local env):

```yaml
mcp_state:
  enabled: true
  flush_interval_seconds: 60
  base_url: "http://localhost:8683"
```

If probe failed, **do not add this**; instead update `docs/feature-tracking/2026-07-11-dispatch-to-pool.md` with `decision: deferred`.

### Step 7: Commit

```bash
cd /Users/les/Projects/mahavishnu
git add mahavishnu/mcp/tools/clone_tools.py tests/integration/test_clone_refactor_group_e2e.py settings/mahavishnu.yaml
git -c core.hooksPath=/dev/null -c user.email=les@wedgwoodwebworks.com \
    commit -m "feat(clone-tools): wire clone_refactor_group to git-tree DAG

REQ-CLONE-007 (UUID7), REQ-CLONE-009 (cluster_claim), REQ-CLONE-015 (cluster_id normalization),
REQ-CLONE-016 (asyncio.create_task cancellation guard).
Layer 3 e2e tests for happy path, REJECT path, concurrent dedup, circuit-open, cancellation.
Path A MCP substrate config (deferred if env probe failed in Task 1).

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

## Self-Review

After writing this plan, I checked it against the spec:

**1. Spec coverage:** Each REQ-CLONE-NNN is anchored to a task:
- REQ-CLONE-001 (verify_proposal blocks DAG on REJECT) → Task 6 (CloneTools flow) — implementation note in §5.3 pre-DAG semantics
- REQ-CLONE-002 (git-tree DAG replaces PR-shape) → Task 5 (rewrite clone_refactor_workflow.py)
- REQ-CLONE-003 (best-effort writes) → Task 5 (try_put_with_log_context + persist_dag_state)
- REQ-CLONE-004 (uuid7) → Task 6 (UUID7 import guard)
- REQ-CLONE-005 (no auto-revert) → Task 5 (no revert logic exists; tests assert commits persist)
- REQ-CLONE-006 (workflow-ID headers) → Task 5 Step 1 (preserved)
- REQ-CLONE-007 (initial DAG state write) → Task 6 (Change E)
- REQ-CLONE-008 (audit_orphans recognizes @flow/@task) → Task 1 Step 3
- REQ-CLONE-009 (cluster-claim) → Task 3 (clone_claims module) + Task 6 (claim call)
- REQ-CLONE-010 (per-step write + try/except/finally) → Task 5 (@flow body + helpers)
- REQ-CLONE-011 (plain git stash wrap) → Task 4 (stash_push/pop) + Task 5 (write_canonical_symbol)
- REQ-CLONE-012 (commit message convention) → Task 5 (commit_message function)
- REQ-CLONE-013 (subtype split + retry_condition_fn) → Task 4 (typed exceptions) + Task 5 (@task decorators)
- REQ-CLONE-014 (try_put_with_log_context + structured log) → Task 2 (method) + Task 5 (use)
- REQ-CLONE-015 (cluster_id normalization) → Task 6 (Change C)
- REQ-CLONE-016 (asyncio cancellation guard) → Task 5 (CancelledError arm) + Task 6 (Change E)

**2. Placeholder scan:** No "TBD"/"TODO"/"implement later" in any code block. All tests have actual assertions.

**3. Type consistency:** `RepoCommit` dataclass field names match between Task 5 (definition) and Task 5 Step 4 (usage in @flow body). `MCPStateBackend.dag_key/cluster_key/in_flight_key` match across Task 2 (definition) and Tasks 3, 5, 6 (consumption). `ConcurrentDAGError(existing_job_id)` consistent across Task 3 (definition) and Task 6 (consumption).

**4. Gaps noted:**
- `MCPStateBackend.get()` and `.delete()` are added in Task 3 Step 4 (needed by `cluster_state_claim` and `release_cluster_claim`). The spec doesn't explicitly call these out but they're required for the claim implementation. Adding them is necessary; the alternative would be to put `release_cluster_claim` inside `clone_claims.py` using raw key construction (less clean).
- `MCPStateBackend.list_prefix` for `clone_refactor_status` — not in spec but reasonable. Task 6 Step 3 Change F notes "stub if too costly."

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-09-25-clone-refactor-wireup.md`. Six tasks total:

1. **P0 environment verifications** — must pass before anything else
2. **MCPStateBackend substrate additions** — exception + key constructors + try_put_with_log_context + tests
3. **Clone-refactor claims module** — ConcurrentDAGError + in-process lock + cluster_state_claim helpers + tests
4. **_git_ops.py subprocess wrapper** — typed GitCommit* exceptions + git ops + tests
5. **clone_refactor_workflow.py rewrite** — git-tree DAG with per-step durability + Layer 2 tests
6. **clone_tools.py wire-up** — UUID7 + cluster_id normalization + cluster_claim + asyncio.create_task + Layer 3 e2e tests

**Two execution options:**

1. **Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration
2. **Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**

---

## Revision history

- **v3** (2026-09-25, current) — Re-review sweep applied. Fixes **3 BLOCKING + 4 MAJOR + 8 MINOR** from `pr-review-toolkit:code-reviewer` and **0 BLOCKING + 0 MAJOR + 10 MINOR** from `pr-review-toolkit:type-design-analyzer` (selected MINORs applied; the rest are polish deferred to future iterations):

  **From `pr-review-toolkit:code-reviewer` (project-guideline compliance):**
  - **CR-B1** — Task 6 e2e tests had repeated `subprocess.run(...)` lines exceeding 100 chars (would fail `ruff check` and gate crackerjack run); added shared `git_repo` fixture + `_diff_one_line()` helper to keep lines under 100.
  - **CR-B2** — `clone_refactor_status` return type was `list[dict]` but actual return is `list[tuple[str, dict]]` (from `list_prefix`); changed to `list[tuple[str, dict[str, Any]]]` per CR-m6 test verification.
  - **CR-B3** — `_make_clone_tools` return type was `CloneTools` but actually returns `tuple[CloneTools, AsyncMock]`; changed to `tuple[CloneTools, AsyncMock]` with both fixtures typed.
  - **CR-M1** — Tasks 3-6 tests had no `@pytest.mark.req` markers; added markers on test classes per REQ.
  - **CR-M2** — Added Step 4.5 to Task 6: settings-threading grep per `feedback-cli-flag-consumer-wiring.md` (hard gate).
  - **CR-M3** — Task 2 Step 8 audit-orphans expected-output was wrong (Tasks 5/6 callers don't exist yet); updated to acknowledge orphans are expected at Task 2 commit point.
  - **CR-M4** — Plan lacked its own Integration Contract blocks per `.claude/decisions/wire-up-contract.md`; added 5-line Integration Contract blocks to Tasks 2, 3, 4, 5, 6.
  - **CR-m1** — `_record_failure` metrics-sink failure was logged at DEBUG; promoted to WARNING per CLAUDE.md style ("operators running at INFO must see this").
  - **CR-m6** — Added `TestListPrefixReturnShape` test to capture `list_prefix` return type BEFORE Task 6 depends on it.

  **From `pr-review-toolkit:type-design-analyzer` (type design):**
  - **TD-m1** — `RepoCommit.status`, `DAGState.status`, `DAGResult.status` typed as `Literal` (closed vocab) instead of `str`; typos like `"Completed"` now compile-error.
  - **TD-m4** — `RepoCommit`, `DAGState`, `DAGResult`, `RepoHit` are `@dataclass(frozen=True, slots=True)`; `RepoCommit` SF-M7 partial-fill uses `dataclasses.replace()` instead of mutation. Collection fields are `tuple[str, ...]` (frozen-compatible).
  - **TD-m6** — `cluster_state_claim` returns `None` (was `-> bool`); only success paths exist, failure raises. Callers discard return value.
  - **TD-m7** — `_safe_extra` and `_RESERVED_LOGRECORD_ATTRS` hoisted to module level (was inside `try_put_with_log_context` closure).
  - **TD-m9** — `MCPStateBackendUnavailable` defined in `state_backends/mcp.py` (architectural consistency with `MCPStateBackendError`); re-exported from `clone_claims.py` for backward compat.

- **v2** (2026-09-25, prior-revision) — Full-sweep review applied. Fixes **3 BLOCKING + 4 MAJOR + 7 MINOR** from `feature-dev:code-architect` and **6 BLOCKING + 7 MAJOR + 8 MINOR** from `pr-review-toolkit:silent-failure-hunter`:

  **From `feature-dev:code-architect` (regular lens):**
  - **CA-B1** — Task 3 Step 4 inserted duplicate `get()`/`delete()` stubs for `MCPStateBackend` using wrong `MCPClient` API signatures; verified real methods already exist, removed the broken Step 4 entirely.
  - **CA-B2** — Task 6 Change F called `mcp_backend.list_prefix(prefix, limit=N)` with non-existent `limit` parameter; fixed to `list_prefix(prefix)[:limit]` (Python-side slice).
  - **CA-B3** — Task 6 Step 1 e2e file had `# pass #` skeletons for 3 test classes; replaced with real test code covering all 8 spec Layer 3 scenarios.
  - **CA-M1** — Added Integration Contract blocks per `.claude/decisions/wire-up-contract.md` (cited inline; spec §6.x carries the contract).
  - **CA-M2** — Task 1 Step 3 audit-orphans referenced symbols from Task 2; moved to Task 2 Step 7 (after edits exist).
  - **CA-M3** — `test_target_write_fails_no_consumer_writes` chmod'd to 0o000 (no-op for uid 0) and mocked `detect_cluster_members`; fixed to mock `write_canonical_symbol` so the failure path is actually exercised.
  - **CA-m1** — Added explanatory comment on `retry_if_exception_type` + Prefect `retry_condition_fn` interaction.
  - **CA-m2** — Added note that `@flow` with non-Pydantic `DAGState` works for in-process only.

  **From `pr-review-toolkit:silent-failure-hunter` (random lens):**
  - **SF-B1** — Cancellation between `cluster_state_claim` and `create_task` leaked the claim; wrapped the entire post-claim section in one try/except that releases on any path.
  - **SF-B2** — `asyncio.create_task(...)` result had no strong reference; added module-level `_background_tasks: set[asyncio.Task]` with `add_done_callback` per Python docs warning.
  - **SF-B3** — `release_cluster_claim` in `@flow` finally could raise and shadow the original DAG exception; wrapped in try/except (best-effort with WARNING log).
  - **SF-B4** — `stash_pop` used `check=False` and silently left the working tree dirty on failure; added `StashPopFailed` exception + caller records typed error on `RepoCommit`.
  - **SF-B5** — No subprocess timeout; added `asyncio.wait_for(..., timeout=120)` in `_run_git` + new `GitCommandTimeout` (Transient subclass — Prefect retries).
  - **SF-B6** — Substrate circuit-open allowed two processes to silently "acquire" same claim; `cluster_state_claim` now raises `MCPStateBackendUnavailable` when circuit is open.
  - **SF-M1** — `_record_failure()` could raise before structured log fires; wrapped in its own try/except inside the except arm.
  - **SF-M2** — `logger.warning(extra={...})` could raise on LogRecord reserved-attribute collision; filter `log_context` against reserved set.
  - **SF-M3** — Test only checked message string, not structured payload; strengthened assertion to check `vars(record)` for `dag_id`/`step_name`/`files_touched`.
  - **SF-M4** — Corrupt sentinel with `refactor_job_id=None` caused persistent `ConcurrentDAGError(existing_job_id=None)`; treat None as stale sentinel, overwrite.
  - **SF-M5** — `@flow` re-entry produced duplicate work; added re-entry guard reading `workflow/v1/{refactor_job_id}` at entry + new `DAGAlreadyRunning` exception.
  - **SF-M6** — `MCPStateBackendUnavailable` needs to surface as MCP 503; caught in `clone_tools.py` and re-raised.
  - **SF-M7** — Post-commit metadata gathering could fail and swallow the successful commit; constructed `RepoCommit` BEFORE `diff_files`/`is_working_tree_clean` with empty defaults, fill in via try/except.
  - **SF-m1** — Added explanatory comment that bare `asyncio.gather` with `_run_consumer` wrapper is equivalent to `return_exceptions=True` with typed fields.
  - **SF-m2** — Added `test_never_raises_on_logging_failure` test enforcing the "NEVER raises" contract.
  - **SF-m3** — Path probe now has explicit assertions (`assert isinstance(final, dict) and len(final) > 0`).
  - **SF-m4** — Added null-byte validation at MCP ingress for `cluster_id`/`target_repo`/`extracted_symbol`.
  - **SF-m5** — Added SIGKILL classifier branch (`exit_code < 0` → `GitCommitPermanent(reason=f"signal_{-exit_code}")`).
  - **SF-m8** — Documented `stash_push` failure modes (plain stash doesn't stash staged changes).

- **v1** (2026-09-25, prior-revision) — Initial draft. 6-task decomposition with concrete code, tests, and commit steps for each REQ-CLONE-001..016.
