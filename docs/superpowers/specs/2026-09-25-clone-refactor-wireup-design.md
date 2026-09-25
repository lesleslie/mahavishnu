---
status: partial
role: canonical
kind: spec
date: 2026-09-25
last_reviewed: 2026-09-25
revision: v2
owner: platform-team
scope: clone-refactor-group wire-up + dispatch-to-pool env-failure
related: docs/feature-tracking/2026-09-25-pool-worker-mcp-audit.md; docs/decisions/2026-09-25-langgraph-as-engine-adapter.md; .claude/decisions/wire-up-contract.md; docs/plans/TEMPLATE.md
---

# Clone-Refactor Wire-Up + Dispatch-to-Pool Env-Failure — Design

> **About this design (2026-09-25)**: Two related tasks that came out of the LangGraph viability spike. The spike concluded that adding a LangGraph engine adapter for `clone_refactor_group` is **not currently justified** because the tool is a stub that never invokes any DAG — neither Prefect nor LangGraph drives it today. This design closes that wire-up gap by (a) replacing the aspirational PR-shaped DAG module with a git-tree-shaped DAG that matches the actual workflow surface, and (b) closing the `dispatch_to_pool` async-callback env-failure so any new engine inherits a working persistence substrate.

> **Headline change**: The `clone_refactor_workflow.py` module is rewritten from a PR-creation DAG to a git-tree DAG (local-main writes via `git apply` + `git commit`). State persists via `MCPStateBackend` (NOT Dhara — Dhara is no longer a Mahavishnu dependency). Wire-up delivers in-process Prefect `@flow` + `asyncio.create_task` for fire-and-forget semantics matching the existing pattern in `prefect_adapter_impl.py:242` and `conductor.py:199`.

## 1. Outcome

After this design ships:

- `clone_refactor_group` MCP tool actually invokes the cross-repo DAG (it doesn't today).
- The DAG performs git-tree operations on local main (NOT PR creation — PRs are not part of the workflow surface per user direction 2026-09-25).
- DAG state persists via `MCPStateBackend` (`workflow/v1/{refactor_job_id}` and `cluster/v1/{cluster_id}` keys).
- `clone_refactor_status` reads `workflow/v1/*` records (currently reads `clone-handled/*` — orphan prefix after this change).
- The aspirational PR-shaped code in `clone_refactor_workflow.py` is deleted; the git-tree DAG replaces it.
- `dispatch_to_pool` async-callback env-failure root cause is identified and either fixed or formally deferred with a `decision: deferred` doc.

**Proof it worked**:
- `git grep -n "gh_client\|create_pr\|get_pr_status" mahavishnu/` returns zero hits.
- `pytest tests/unit/clone/test_clone_refactor_workflow.py tests/unit/workflows/test_git_ops.py tests/integration/test_clone_refactor_group_e2e.py` — all green.
- `python scripts/audit_orphans.py` exits 0; no new symbols with zero callers.
- `clone_refactor_group` MCP tool returns a `refactor_job_id` that is parseable as a UUID7 (proves the new ID format).

## 2. Goals

1. Wire `clone_refactor_group` to invoke a real DAG via Prefect `@flow` + `asyncio.create_task`.
2. Replace the PR-shaped DAG with a git-tree DAG matching the actual workflow surface (local-main writes, no GitHub).
3. Persist DAG state via `MCPStateBackend` (the existing state substrate).
4. Make `clone_refactor_status` return real records from the new DAG's writes.
5. Close (or formally defer) the `dispatch_to_pool` async-callback env-failure so any future engine inherits a working persistence substrate.

## 3. Non-Goals

- Adding a LangGraph engine adapter (deferred per the LangGraph spike; revisit when ≥3 durable workflows need cycles + HITL + time-travel).
- Implementing real GitHub PR creation (PRs are not in the workflow surface per user direction).
- Replacing `MCPStateBackend` with a different substrate (out of scope).
- Adding automatic revert on consumer-write failure (policy: operator-driven cleanup; see Section 4).
- Implementing `verify_proposal` post-DAG verification (pre-DAG only per user direction).

## 4. Current Findings

### 4.1 `clone_tools.py:161-231` — current stub surface

The `clone_refactor_group` tool generates a UUID, runs `verify_proposal` synchronously, persists `VerificationResult`, returns the job-id. **Never calls `run_clone_refactor_dag`.** No DAG runs today.

### 4.2 `clone_refactor_workflow.py` — aspirational PR-shape

Module docstring describes PR creation as the DAG steps. `ExtractionPR` / `ConsumingPR` dataclasses with `pr_url` field. `create_extraction_pr` / `wait_for_merge` / `create_consuming_pr` all take `gh_client` parameter. **Zero git-tree operations exist.** Tests at `tests/unit/clone/test_clone_refactor_workflow.py` test the PR-shaped API.

### 4.3 `engines/prefect_adapter_impl.py:1061` — dead docstring reference

References `flow_path="mahavishnu.workflows.clone_refactor_workflow:run"` only as a docstring example. Nothing in the codebase actually triggers that deployment.

### 4.4 `state_backends/mcp.py` — active state substrate

`MCPStateBackend` writes to MCP keys like `workflow/v1/{execution_id}`. Already used by `clone_refactor_status` (line 282) for `clone-handled/*` prefix. **Dhara is no longer a Mahavishnu dependency** (per user direction 2026-09-25 and verified by `git grep -n dhara mahavishnu/` returning only a stale `skill_mcp_validator.py` allowlist).

### 4.5 `dispatch_to_pool` async-callback env-failure

Per memory `pool-dispatch-async-default.md`: `dispatch_to_pool(async_callback=True)` returns `workflow_id` immediately, but `workflow_result(workflow_id=...)` returns `not_found`. Root cause: **the MCP substrate for `workflow/v1/{workflow_id}` writes is unconfigured** (not Dhara). The `Phase 2m` `pool_route_execute` (sync alternative) was shipped as a workaround in commit `4090965b`.

### 4.5 Requirements (REQ-XXX traceability)

Per `docs/plans/TEMPLATE.md` §4.5, every requirement introduced by this design is traceable from spec → code → test:

```yaml
requirements:
  - id: REQ-CLONE-001
    title: "Pre-DAG verify_proposal blocks DAG start on consensus==REJECT"
  - id: REQ-CLONE-002
    title: "Git-tree DAG replaces PR-shape (no gh_client, no ExtractionPR/ConsumingPR)"
  - id: REQ-CLONE-003
    title: "MCPStateBackend persistence is best-effort (try/except per write)"
  - id: REQ-CLONE-004
    title: "refactor_job_id uses uuid.uuid7() (Python 3.14 stdlib, RFC 9562)"
  - id: REQ-CLONE-005
    title: "No automatic revert on partial consumer-write failure (operator-driven cleanup)"
  - id: REQ-CLONE-006
    title: "Workflow-ID/Approved-by header preservation on rewritten module"
  - id: REQ-CLONE-007
    title: "Pre-DAG MCPStateBackend.dag_key() initial state write before asyncio.create_task"
  - id: REQ-CLONE-008
    title: "audit_orphans.py recognizes @flow/@task decorators (P0 verification, see §6.10)"
```

Each REQ ID gets `# Implements: REQ-CLONE-NNN` markers in code/docstrings and `@pytest.mark.req(["REQ-CLONE-NNN"])` markers in tests. `audit_requirements.py` enforces traceability.

### 4.6 Project-state corrections (user direction 2026-09-25)

Three corrections shape this design:

1. **No Dhara** — Dhara is no longer a Mahavishnu dependency. State substrate is `MCPStateBackend`. Do not write "Dhara" in any plan, ADR, code comment, or design doc.
2. **No PRs in workflows** — PRs are not the delivery surface. Git operations are git-tree operations on local main.
3. **Merge to local main** — delivery model is commit/merge to local `main`, not via GitHub PR.

All three are now stored in Session-Buddy `project` memory to prevent reintroduction.

## 5. Architecture

### 5.1 New DAG shape (replacing PR-shape)

```
clone_refactor_group MCP tool (mahavishnu/mcp/tools/clone_tools.py)
   │
   │  1. generate refactor_job_id = str(uuid.uuid7())   ← UUID7 (Section 5.2)
   │  2. await verify_proposal(proposal)                ← existing async; signature at core/verification.py:473
   │  3. persist VerificationResult via VerificationStore ← existing
   │  4. if consensus==REJECT and verification_enabled → return blocked_by_verification
   │  5. write initial DAG state (workflow/v1/{id}, status: queued) ← new
   │  6. asyncio.create_task(run_clone_refactor_dag(...))            ← new wire-up
   │
   ▼
run_clone_refactor_dag (Prefect @flow, fires in background)
   │
   │  writes state via MCPStateBackend (best-effort, try/except)
   │    workflow/v1/{refactor_job_id}    DAG lifecycle
   │    cluster/v1/{cluster_id}         per-cluster consumer-progress
   │
   ├─ Step 1: detect_cluster_members (Prefect @task)
   │
   ├─ Step 2: write_canonical_symbol (target_repo, local main) (Prefect @task, retries=2)
   │
   ├─ Step 3: write_replacement_diff per consumer (parallel asyncio.gather) (Prefect @task, retries=2)
   │
   └─ Step 4: persist final DAG state to MCPStateBackend (status: completed | failed)
```

### 5.2 UUID7 for `refactor_job_id`

Use `uuid.uuid7()` (Python 3.14 stdlib; **RFC 9562** finalized 2024) instead of `uuid.uuid4()`. The project's `pyproject.toml` already pins `requires-python = ">=3.14"`, so the availability is verified. Same wire format (8-4-4-4-12 hex string), zero breaking change to callers, but provides:

- Time-sortable in B-tree indexes (string sort = chronological sort)
- Creation timestamp encoded in the 48-bit ms-precision prefix
- Natural ordering for `clone_refactor_status(limit=N)` queries

**Trade-off**: this is the first UUID7 use in the codebase. The rest of Mahavishnu uses UUID4 (websocket, pools, evidence, locks). If a project-wide "prefer UUID7 for new public IDs" convention is wanted, that's a separate decision and out of scope for this design. For this design, only `refactor_job_id` uses UUID7. **§6.3 retains a `sys.version_info >= (3, 14)` guard** for defensive correctness in case the pin is ever relaxed.

**Sort direction** (binding): UUID7 timestamp prefix is encoded as 48-bit big-endian Unix-ms in the most-significant bits. Lexicographic string sort = ascending chronological sort. `clone_refactor_status(limit=N)` returns records **descending** (newest-first) per the Layer 3 test name `test_clone_refactor_status_returns_recent_jobs_first`. The test asserts `records[0].started_at > records[1].started_at` explicitly — not just "sorted".

### 5.3 Failure semantics

**Pre-DAG** (in `clone_refactor_group`):
- `verify_proposal` raises → MCP 500
- `VerificationStore.persist` raises → log + continue, MCP 500
- `consensus == REJECT` → return `decision: blocked_by_verification`, no DAG starts

**DAG step failures**:
- `detect_cluster_members` raises → DAG `failed`, no consumers attempted
- `write_canonical_symbol` raises → DAG `failed`, no consumers attempted (sequential before fan-out)
- `write_replacement_diff` raises on consumer N → record failure in `consumer_commits`, other consumers proceed
- `persist_dag_state` raises → log + continue (state writes are best-effort)

### 5.4 No-auto-revert policy

**If consumers 1-3 succeed and consumer 4 fails**: DAG ends `status: failed`, repos 1-3 retain their commits on local main. **No automatic revert.** Operator reads `workflow/v1/{refactor_job_id}` and decides:
- Manual revert: `cd repo && git reset --hard HEAD~1`
- Or leave as-is and open a follow-up DAG

**Rationale**: local-main writes are immediately visible to other tooling (CI, pre-commit, other DAGs). Auto-revert races with in-flight work. The blast radius of "auto-revert deletes someone's WIP commit" exceeds "operator does manual cleanup." Matches M-NEW-7 spirit ("prevent half-migrated ecosystem state") with operator-driven cancellation.

**Operator access path**: failed consumer records are read via `clone_refactor_status` (lists recent DAGs with `status: failed`) or direct MCP key inspection (`workflow/v1/{refactor_job_id}`). The `consumer_commits[i].status = failed` and `consumer_commits[i].error` fields name the consumer repo and the failure reason.

### 5.5 MCP substrate configuration for `dispatch_to_pool` env-failure

`dispatch_to_pool` async-callback env-failure root cause: the MCP substrate for `workflow/v1/{workflow_id}` writes is not configured in the local dev environment.

**Path A (selected 2026-09-25 — committed)**: Configure MCP substrate. Add to `settings/mahavishnu.yaml`:
```yaml
mcp_state:
  enabled: true
  flush_interval_seconds: 60
  base_url: "http://localhost:8683"  # MCP substrate endpoint
```

This makes `MCPStateBackend` writes succeed for both `dispatch_to_pool` and the new clone-refactor DAG.

**§5.5a Path probe (run before kickoff)**: this design implements Path A only. If the env probe fails, do NOT silently switch to Path B; record a `decision: deferred` doc and stop.

```
# env probe — must succeed before §6.1 begins
mahavishnu mcp health
mcp__mahavishnu__dispatch_to_pool(async_callback=True, prompt="env probe")
# expect: workflow_id returned; workflow_result(workflow_id) returns non-empty within 30s
```

If the probe fails: write `docs/feature-tracking/2026-07-11-dispatch-to-pool.md` update with `decision: deferred`, halt implementation, surface to user.

## 6. Components (files + boundaries)

### 6.1 `mahavishnu/workflows/clone_refactor_workflow.py` (rewrite, ~280 lines)

Replaces the PR-shaped module. **Preserve `# Workflow-ID: 01JCLONEREF2026` and `# Approved by: les` headers at the top of the rewritten module** (required by `tests/unit/test_check_workflow_quarantine.py`).

Public API:

```python
@flow(name="clone-refactor-dag")
async def run_clone_refactor_dag(
    refactor_job_id: str,
    cluster_id: str,
    target_repo: str,
    consumer_repos: list[str],
    extracted_symbol: str,
    extraction_diff: str,
    consuming_diffs: dict[str, str] | None = None,
) -> DAGResult: ...
```

Step functions (all `@task`, with explicit `retry_condition`):
```python
# Prefect @task — retry only commit-infrastructure failures, NOT GitApplyConflict
# (deterministic content conflicts aren't transient and re-running wastes time).
from prefect import task
from tenacity import retry_if_exception_type

@task(retries=2, retry_delay_seconds=5, retry_condition=retry_if_exception_type((GitCommitFailed,)))
async def write_canonical_symbol(...) -> RepoCommit: ...

@task(retries=2, retry_delay_seconds=5, retry_condition=retry_if_exception_type((GitCommitFailed,)))
async def write_replacement_diff(...) -> RepoCommit: ...

@task(retries=0)
async def detect_cluster_members(cluster_id: str, repos: list[str]) -> list[RepoHit]: ...

@task(retries=0)
async def persist_dag_state(state: DAGState) -> None: ...
```

`detect_cluster_members` delegates to `mahavishnu.core.loop_helpers.detect_until_dry` (the symbol lives in `core/loop_helpers.py`, NOT `workflows/`; the spec's earlier `workflows._detect_until_dry` reference was wrong).

Dataclasses: `DAGResult`, `RepoCommit`, `RepoHit`, `DAGState`. **No** `ExtractionPR` / `ConsumingPR` / `gh_client` references.

Imports `_git_ops.py` (`mahavishnu/workflows/_git_ops.py`), `mahavishnu/core/state_backends/mcp.py`, `mahavishnu/core/loop_helpers.py` (`detect_until_dry`), `prefect`. Does **not** import from `mahavishnu/mcp/tools/clone_tools.py` (one-way dependency: tools call workflow).

**Integration Contract:**
- **Triggered from**: `mcp__mahavishnu__clone_refactor_group` (in `mahavishnu/mcp/tools/clone_tools.py`) via `asyncio.create_task(run_clone_refactor_dag(...))` after `verify_proposal` succeeds
- **Returns to / updates**: `workflow/v1/{refactor_job_id}` MCP key (via `MCPStateBackend.dag_key()`), and `cluster/v1/{cluster_id}` MCP key (via `MCPStateBackend.cluster_key()`) — both best-effort writes wrapped in try/except
- **Demonstrable by**: `pytest tests/integration/test_clone_refactor_group_e2e.py::test_clone_refactor_group_returns_job_id_and_starts_dag` passes and asserts `workflow/v1/{id}` exists post-DAG-start
- **Rollback signal**: OTel/log line `clone_refactor.dag.failed` with `refactor_job_id` attribute; consumer-recovery via `clone_refactor_status(limit=N)` listing `status: failed` records (no-auto-revert policy: operator does manual cleanup per Section 5.4)
- **Observability added**: OTel span `clone_refactor.dag` with attrs `refactor_job_id`, `cluster_id`, `target_repo`, `consumer_count`; counter `clone_refactor.dag.steps.failed_total{step=...}`; histogram `clone_refactor.dag.duration_seconds{status=...}`; log line `clone_refactor.step.completed` per step

### 6.2 `mahavishnu/workflows/_git_ops.py` (new, ~80 lines)

Thin async wrapper around `git apply` / `git commit` for DAG tasks. Uses `asyncio.create_subprocess_exec` (no `shell=True`). **Passes diffs via stdin, never argv** (avoids injection through malformed diff headers).

Raises typed exceptions:
```python
class GitApplyConflict(Exception):
    """Structured conflict from `git apply --check`."""
    def __init__(self, diff_offset: int, conflict_marker: str, stderr: str) -> None: ...

class GitCommitFailed(Exception):
    def __init__(self, stderr: str, exit_code: int) -> None: ...
```

Public API:
```python
async def git_apply(repo_path: Path, diff: str) -> None:
    # 1. validate path is inside repo_path (reject paths with '..' or absolute escapes)
    # 2. reject diffs containing "Binary files", "rename to /dev/", "rename from /dev/"
    # 3. pipe diff via stdin to `git apply --check`; raise GitApplyConflict on non-zero
    # 4. on success, pipe diff via stdin to `git apply`
    ...

async def git_commit(repo_path: Path, message: str) -> str:
    # `git -c user.email=les@wedgwoodwebworks.com -c user.name=les commit -F -`
    # pass message via stdin
    ...

async def current_head_sha(repo_path: Path) -> str: ...
```

**Integration Contract:**
- **Triggered from**: DAG step functions in `clone_refactor_workflow.py` (calls inside `@task` bodies)
- **Returns to / updates**: nothing (pure side-effect wrapper; `git_commit` returns the SHA via stdout)
- **Demonstrable by**: `pytest tests/unit/workflows/test_git_ops.py` (5 tests, see §8 Layer 1)
- **Rollback signal**: `git_commit` raises `GitCommitFailed` → caller (DAG step) records failure; no automatic rollback
- **Observability added**: structured log line per call with `repo_path`, `exit_code`, `commit_sha` fields

### 6.3 `mahavishnu/mcp/tools/clone_tools.py` (modify, ~30 line delta)

Five changes:
1. UUID7 import with **Python 3.14 guard** (per `bodai-pytest-binary-cwd.md` style):
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
2. Replace `job_id = str(uuid4())` with `job_id = str(_new_uuid7())`
3. Add `_record_dag_state` helper that writes initial `workflow/v1/{refactor_job_id}` record before `asyncio.create_task`
4. Add `asyncio.create_task(run_clone_refactor_dag(...))` call after `verify_proposal` succeeds
5. Update `clone_refactor_status` to read `workflow/v1/*` (was `clone-handled/*`)

**Import direction invariant** (one-way dependency): `clone_tools.py` may import from `workflows/`, but `workflows/clone_refactor_workflow.py` must NOT import from `mcp/tools/clone_tools.py`. Verified by the §9 grep `git grep -nE "from mahavishnu\.workflows" mahavishnu/mcp/tools/clone_tools.py` (the spec previously had the grep backwards; this is the correct direction).

**Integration Contract:**
- **Triggered from**: MCP client invokes `mcp__mahavishnu__clone_refactor_group`; existing `clone_refactor_status` MCP tool continues to be invoked by operators
- **Returns to / updates**: returns `{refactor_job_id, status: queued, decision, verification}` to MCP client; `MCPStateBackend.put("workflow/v1/{id}", {...})` records initial state
- **Demonstrable by**: `pytest tests/integration/test_clone_refactor_group_e2e.py` — all 4 Layer 3 tests pass
- **Rollback signal**: OTel span `mcp.clone_refactor_group` with `error` attribute on exception; log line `clone_refactor_group.failed` with exception class + message
- **Observability added**: OTel span `mcp.clone_refactor_group` (added by FastMCP decorator); counter `mcp.clone_refactor_group.calls_total{decision=...}`

### 6.4 `mahavishnu/core/state_backends/mcp.py` (add static methods)

**Do NOT redeclare `workflow_key(execution_id)` — it already exists at `state_backends/mcp.py:55-58` and is called by `dispatch_to_pool`, `clone_refactor_status` (line 282), and other consumers.** Adding `workflow_key(refactor_job_id)` as a second definition would silently shadow the first (Python keeps the later definition), breaking every existing caller.

Add instead:
- `dag_key(refactor_job_id: str) -> str` returning `f"workflow/v1/{refactor_job_id}"` — new key constructor for clone-refactor DAG records. Distinct name from `workflow_key` because it carries semantic intent ("DAG lifecycle" vs. "workflow execution"); avoids future collision when `execution_id` and `refactor_job_id` formats diverge.
- `cluster_key(cluster_id: str) -> str` returning `f"cluster/v1/{cluster_id}"` — new key for per-cluster consumer-progress records.

Existing `workflow_key(execution_id)` is **kept unchanged**.

**Integration Contract:**
- **Triggered from**: `clone_refactor_workflow.py` (writes via `dag_key()`, `cluster_key()`); `clone_refactor_status` reads via the same keys
- **Returns to / updates**: MCP key strings (no state mutation by the constructors themselves)
- **Demonstrable by**: `pytest tests/unit/test_mcp_state_backend.py` (the actual path; **not** `tests/unit/state_backends/...` which doesn't exist) — every existing test continues to pass; new tests assert `dag_key("abc") == "workflow/v1/abc"` and `cluster_key("cluster-1") == "cluster/v1/cluster-1"`
- **Rollback signal**: N/A (pure functions; no side effects)
- **Observability added**: N/A (pure functions)

### 6.5 `tests/unit/clone/test_clone_refactor_workflow.py` (rewrite, ~300 lines)

Replaces 200+ line PR-shape test file with git-tree-shape integration tests. Covers all 9 scenarios from Section 8 Layer 2.

### 6.6 `tests/unit/workflows/test_git_ops.py` (new, ~120 lines)

Unit tests for `_git_ops.py` against `tmp_path` + `git init`. Covers 5 scenarios from Section 8 Layer 1.

### 6.7 `tests/integration/test_clone_refactor_group_e2e.py` (new, ~80 lines)

End-to-end MCP tool tests against in-process FastMCP test client. Covers 4 scenarios from Section 8 Layer 3.

### 6.8 `settings/mahavishnu.yaml` (add MCP state config, Path A)

If taking Path A for the env-failure, add the `mcp_state` block. **Pre-flight probe (§5.5a) must succeed before this section executes.**

### 6.9 Dependency graph (post-change)

```
clone_tools.py (MCP tool)
   │
   ▼
clone_refactor_workflow.py (DAG, @flow)
   │
   ├─→ _git_ops.py (subprocess wrapper)
   ├─→ mahavishnu/core/state_backends/mcp.py (MCPStateBackend, writes)
   └─→ mahavishnu/core/loop_helpers.py (detect_until_dry)
```

No circular imports. No new external deps. Prefect `@flow`/`@task` already in `prefect` (existing dep).

### 6.10 `audit_orphans.py` scope verification (P0)

`scripts/audit_orphans.py:51-53` `DECORATOR_REGISTRATION_PATTERN` includes `tool` and `app.command`, but **NOT** Prefect `@flow`/`@task`. The new symbols (`run_clone_refactor_dag`, `detect_cluster_members`, `write_canonical_symbol`, `write_replacement_diff`, `persist_dag_state`, `git_apply`, `git_commit`, `current_head_sha`, `GitApplyConflict`, `GitCommitFailed`, `DAGResult`, `RepoCommit`, `RepoHit`, `DAGState`, `dag_key`, `cluster_key`, `_record_dag_state`) may be flagged as orphans unless `audit_orphans.py` recognizes them as having direct callers.

**Pre-flight verification (P0 before §8 begins)**:

```bash
python scripts/audit_orphans.py --dry-run 2>&1 | grep -E "clone_refactor|_git_ops|dag_key|cluster_key"
```

If any new symbol is flagged as orphan under `--dry-run`, run the audit with `--include-tests` flag (verify flag exists) or extend `DECORATOR_REGISTRATION_PATTERN` to include `@flow`/`@task`. **The §11 decision rule item 3 (`audit_orphans.py` exit 0) is gated on this verification passing.**

### 6.11 `fastmcp.test_client.TestClient` availability (P0)

Pyproject pins `fastmcp>=3.4.7,<5`, which does **not** guarantee the `fastmcp.test_client` submodule exists. The existing test pattern uses `_server.server.call_tool(...)` directly (verified at `tests/integration/test_get_agent_e2e.py:38-46`).

**Pre-flight verification (P0 before §8 Layer 3 begins)**:

```python
# Verify in the active venv
python -c "from fastmcp.test_client import TestClient; print('ok')"
```

- If import succeeds: use `TestClient` for Layer 3.
- If import fails: fall back to `_server.server.call_tool(...)` pattern, mirroring `tests/integration/test_get_agent_e2e.py`. Update §8 Layer 3 test snippets accordingly.

**The §11 decision rule (all 4 Layer 3 tests pass) is gated on this verification resolving one way or the other.**

## 7. Data flow

### 7.1 Sequence (5 phases)

**Phase 0 — synchronous pre-DAG** (in `clone_refactor_group`):

1. `refactor_job_id = str(uuid.uuid7())`
2. Build `Proposal(proposal_id=refactor_job_id, proposal_type="clone_refactor", ...)`
3. `verification_result = await verify_proposal(proposal)`
4. `await self._store.persist(verification_result)` (existing)
5. **Initial DAG state write** (new, best-effort): `workflow/v1/{refactor_job_id}` = `{status: "queued", cluster_id, target_repo, consumer_repos, decision, started_at: now}`
6. If `consensus == REJECT` and verification enabled → return `decision: "blocked_by_verification"`, skip step 7
7. `asyncio.create_task(run_clone_refactor_dag(...))` — fire-and-forget
8. Return `{refactor_job_id, status: "queued", ...}`

**Phase 1 — DAG start** (inside `run_clone_refactor_dag`):

9. Update `workflow/v1/{refactor_job_id}.status = "running", dag_started_at = now` (best-effort)
10. `detect_cluster_members(cluster_id, repos)` → list of `RepoHit`

**Phase 2 — propose**:

11. `write_canonical_symbol(target_repo, extracted_symbol, extraction_diff)` → `RepoCommit(target_repo, sha)`
12. Best-effort: `workflow/v1/{refactor_job_id}.target_commit = sha`

**Phase 3 — consume** (parallel):

13. `consuming_tasks = [write_replacement_diff(repo, ...) for repo in consumer_repos]`
14. `results = await asyncio.gather(*consuming_tasks, return_exceptions=True)`
15. Per consumer: success → record `RepoCommit(consumer_repo, sha)`; exception → record failure
16. Best-effort: `cluster/v1/{cluster_id}` = `{consumers: [...]}`

**Phase 4 — finish**:

17. All consumers succeeded → `workflow/v1/{refactor_job_id}.status = "completed"`
18. Any consumer failed → `workflow/v1/{refactor_job_id}.status = "failed"`
19. `workflow/v1/{refactor_job_id}.dag_completed_at = now`
20. Return `DAGResult(...)`

### 7.2 Final state record shape

```json
{
  "schema_version": 1,
  "refactor_job_id": "0193f5e2-7c8d-7abc-9def-1234567890ab",
  "cluster_id": "cluster-abc123",
  "target_repo": "oneiric",
  "consumer_repos": ["mahavishnu", "session-buddy"],
  "decision": "propose_approve",
  "verification": {...serialized VerificationResult...},
  "status": "completed",
  "started_at": "2026-09-25T...",
  "dag_started_at": "2026-09-25T...",
  "dag_completed_at": "2026-09-25T...",
  "target_commit": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0",
  "consumer_commits": [
    {"repo": "mahavishnu", "sha": "b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1", "status": "completed"},
    {"repo": "session-buddy", "sha": "c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2", "status": "completed"}
  ],
  "failed_consumers": []
}
```

### 7.3 Key schema

| Key | Owner | Schema |
|---|---|---|
| `workflow/v1/{refactor_job_id}` | clone_refactor DAG | full DAG lifecycle record above |
| `cluster/v1/{cluster_id}` | clone_refactor DAG | per-cluster consumer-progress record |
| `verification/{proposal_id}/result` | VerificationStore | unchanged (existing) |

### 7.4 Read paths

- `clone_refactor_status` (modified) — reads `workflow/v1/*` prefix; sorted by UUID7 (chronological).
- `get_verification_result` (unchanged) — reads `verification/{proposal_id}/result`.

## 8. Testing

### Layer 1 — unit tests for `_git_ops.py`

`tests/unit/workflows/test_git_ops.py` (new, ~120 lines):

| Test | Setup | Assertion |
|---|---|---|
| `test_git_apply_clean` | init repo, write file, apply diff | file content matches diff |
| `test_git_apply_conflict_raises_structured` | init repo, write conflicting file | raises `GitApplyConflict(diff_offset, conflict_marker)` |
| `test_git_commit_returns_sha` | init repo, apply, commit | returns 40-char hex SHA |
| `test_git_commit_with_precommit_fail` | init repo with failing pre-commit | raises `GitCommitFailed(stderr, exit_code)` |
| `test_current_head_sha` | init repo, commit twice | returns latest SHA, not first |

### Layer 2 — integration tests for `run_clone_refactor_dag`

`tests/unit/clone/test_clone_refactor_workflow.py` (rewrite, ~300 lines):

| Test | Scenario | Assertion |
|---|---|---|
| `test_detect_cluster_members` | mocked scan returns 3 hits | step returns expected list |
| `test_write_canonical_symbol_commits_to_local_main` | init target repo, run step | `git log -1` shows expected commit on `main` |
| `test_write_replacement_diff_removes_duplicate_adds_import` | init consumer with duplicate | duplicate removed, import added, committed |
| `test_dag_happy_path_propose_consume_persist` | full DAG with 3 consumers, all succeed | DAGResult has 3 commits, all `status: completed` |
| `test_dag_target_write_fails_no_consumer_writes` | target repo unwritable | DAG `failed`, `consumer_commits: []` |
| `test_dag_one_consumer_fails_others_succeed` | 4 consumers, consumer 3 raises `GitApplyConflict` | DAG `failed`, consumer 3 marked failed, others committed |
| `test_dag_no_auto_revert_on_failure` | failure scenario above | `git log` on consumers 1, 2, 4 still shows their commits |
| `test_pre_dag_verify_reject_blocks_dag` | inject VerificationResult with consensus=REJECT | DAG never starts, returns `blocked_by_verification` |
| `test_dag_state_writes_are_best_effort` | mock MCPStateBackend throws on write | DAG completes (or fails), exception logged WARNING |

### Layer 3 — MCP-tool end-to-end

`tests/integration/test_clone_refactor_group_e2e.py` (new, ~80 lines):

| Test | Scenario | Assertion |
|---|---|---|
| `test_clone_refactor_group_returns_job_id_and_starts_dag` | call MCP tool with valid cluster_id | response has `refactor_job_id`, `status: queued`, `decision: propose_approve`; `workflow/v1/{id}` exists |
| `test_clone_refactor_group_reject_blocks_dag` | mocked verify_proposal returns REJECT | `decision: blocked_by_verification`, no DAG started |
| `test_clone_refactor_group_uses_uuid7` | call MCP tool | `refactor_job_id` parses as UUID with version=7 |
| `test_clone_refactor_status_returns_recent_jobs_first` | write 3 records via DAG | `clone_refactor_status(limit=10)` returns 3 records, newest-first |

### Test parity

Per `.claude/decisions/mcp-backend-wiring-discipline.md`: "every tool registration requires `tests/integration/test_<tool>_e2e.py` asserting non-empty results."

This plan produces all three layers; `audit_orphans.py` should show zero new symbols with zero callers after the rewrite.

### Required test infrastructure (no new project deps)

- `tmp_path` pytest fixture (stdlib)
- `git` binary (already project dev dep)
- `monkeypatch` for mocking `MCPStateBackend` and `verify_proposal`
- `pytest-asyncio` (already project dep via `pytest` config)
- `from fastmcp.test_client import TestClient` — **P0 verification step before implementation**: confirm this import resolves in the project's current `fastmcp` version. If absent, use the existing MCP test client pattern from `tests/integration/` instead. Do not assume.

## 9. Validation

| Check | Command | Expected |
|---|---|---|
| No PR-shaped code remains | `git grep -nE "gh_client\|create_pr\|get_pr_status\|ExtractionPR\|ConsumingPR" mahavishnu/` | 0 hits |
| DAG unit tests pass | `pytest tests/unit/clone/test_clone_refactor_workflow.py` | All green |
| Git-ops unit tests pass | `pytest tests/unit/workflows/test_git_ops.py` | All green |
| MCP e2e tests pass | `pytest tests/integration/test_clone_refactor_group_e2e.py` | All green |
| One-way dep (tools → workflows) | `git grep -nE "from mahavishnu\.workflows" mahavishnu/mcp/tools/clone_tools.py` | ≥1 hit (intentional); `git grep -nE "from.*mcp\.tools\.clone_tools" mahavishnu/workflows/` | 0 hits |
| No new orphans | `python scripts/audit_orphans.py --include-tests` | Exit 0 (gated on §6.10 P0 verification) |
| State substrate wired | `pytest tests/unit/test_mcp_state_backend.py` (the actual path; **not** `tests/unit/state_backends/...`) | All green |
| Workflow-ID preserved | `head -2 mahavishnu/workflows/clone_refactor_workflow.py \| grep -E "Workflow-ID: 01JCLONEREF2026\|Approved by: les"` | 2 hits |
| Stale docstring fixed | `git grep -nE "clone_refactor_workflow:run" mahavishnu/engines/prefect_adapter_impl.py` | 0 hits after `run` → `run_clone_refactor_dag` rewrite (see M2 in §10) |
| Lint clean | `crackerjack run` | All hooks pass |
| Coverage gate | `pytest --cov=mahavishnu --cov-fail-under=89.01682905225863` | Passes; every §5.3 failure mode has a test |
| Crackerjack version unchanged | `git diff pyproject.toml \| grep version` | No version bump (memory `feedback-mcp-common-version-bump-is-user.md`) |
| No `git push` | (manual check; no CI gate) | Per memory `feedback-bodai-push-is-user-controlled.md` |
| `dispatch_to_pool` async-callback working | `mcp__mahavishnu__dispatch_to_pool(async_callback=True)` then `mcp__mahavishnu__workflow_result(workflow_id=...)` | Returns non-empty result, not `not_found` (Path A committed; if probe fails, halt per §5.5a) |

## 10. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Existing tests for PR-shape break | Certain | `tests/unit/clone/test_clone_refactor_workflow.py` is rewritten — tests are aspirational, no production callers depend on them |
| `clone_refactor_status` consumers depend on `clone-handled/*` key | Medium | Search for `clone-handled` usages; if any, add alias reads (return from both `clone-handled/*` and `workflow/v1/*` for one release) |
| MCP substrate not configured in dev env | High (per memory `pool-dispatch-async-default.md`) | Path A configures it; Path B formally defers |
| UUID7 wire-format breaks existing test fixtures | Low | UUID7 produces same string format as UUID4; fixtures use string format, not hex bytes |
| `_git_ops.py` subprocess security (user-controlled diff input) | Medium | Validate diff contains no `rm` / `sudo` / shell metacharacters before passing to `git apply`. Wrap with try/except for `GitApplyConflict`. |
| Prefect server unreachable breaks DAG | Low | In-process `@flow` doesn't require Prefect server; retries at `@task` level use Prefect's in-memory scheduler |
| Prefect retries cause consumer writes to run twice (e.g., commit succeeds but Prefect thinks it failed) | Low | Each step's `git commit` returns the SHA; Prefect retries get the same SHA on second run (idempotent on same diff) but produce a duplicate commit on second invocation. Acceptable; operator cleans up if needed. |
| MCP substrate is intentionally absent (not a config issue) | Low | Path B documents as deferred rather than forcing config |
| Existing `clone_refactor_workflow.py` callers beyond tests | None expected | Verified by `git grep -rn "create_extraction_pr\|wait_for_merge\|create_consuming_pr" --include="*.py"` returns only tests + the module itself |

## 11. Decision rule

This design is "done enough" when:

1. All 5 sections implemented per Section 6 (file changes).
2. All 9 Layer 1-3 tests pass.
3. `audit_orphans.py` exits 0.
4. `crackerjack run` passes.
5. `dispatch_to_pool` async-callback either works in local env (Path A) or is formally deferred with feature-tracking doc update (Path B).
6. No production caller regression (no caller of old PR-shape API other than the rewritten tests).
7. Pre-commit bypass via `git -c core.hooksPath=/dev/null commit`.
8. Author email `les@wedgwoodwebworks.com`.
9. No version bump (memory rule).
10. No `git push` (memory rule).

## 12. Universal invariants (apply to all phases)

1. No `git push` (memory `feedback-bodai-push-is-user-controlled.md`).
2. No version bump in `pyproject.toml` (memory `feedback-mcp-common-version-bump-is-user.md`).
3. Pre-commit bypass via `git -c core.hooksPath=/dev/null commit` (memory `mahavishnu-worktree-precommit-blocks-workers.md`).
4. Git author `les@wedgwoodwebworks.com` (memory `git-author-email-correct-domain.md`).
5. All Bodai components merge directly to `main` pre-1.0 (memory `bodai-pre-1.0-merge-policy.md`).
6. Never hardcode `/Users/les/.../python` in any test (memory `mahavishnu-launcher-venv-discovery.md`).
7. Project-state corrections: no Dhara references; no PR workflow assumptions; merge to local main.

## 13. Critical files

- `mahavishnu/workflows/clone_refactor_workflow.py` (rewrite, replaces PR-shape)
- `mahavishnu/workflows/_git_ops.py` (new)
- `mahavishnu/mcp/tools/clone_tools.py` (modify ~30 LOC)
- `mahavishnu/core/state_backends/mcp.py` (add 2 static methods)
- `tests/unit/clone/test_clone_refactor_workflow.py` (rewrite, ~300 lines)
- `tests/unit/workflows/test_git_ops.py` (new, ~120 lines)
- `tests/integration/test_clone_refactor_group_e2e.py` (new, ~80 lines)
- `settings/mahavishnu.yaml` (add `mcp_state` block if Path A)
- `docs/feature-tracking/2026-09-25-pool-worker-mcp-audit.md` (add `dispatch_to_pool` decision)
- `docs/feature-tracking/2026-07-11-dispatch-to-pool.md` (Path B: update with `decision: deferred`)

## 14. References

- `.claude/decisions/wire-up-contract.md` — integration contract requirement
- `.claude/decisions/mcp-backend-wiring-discipline.md` — e2e test requirement for new MCP surfaces
- `docs/plans/TEMPLATE.md` — plan template with Integration Contract blocks
- `docs/decisions/2026-09-25-langgraph-as-engine-adapter.md` — LangGraph spike verdict (deferred)
- `docs/feature-tracking/2026-09-25-pool-worker-mcp-audit.md` — §10 audit context
- `memory/pool-dispatch-async-default.md` — `dispatch_to_pool` env-failure
- `mahavishnu/engines/prefect_adapter_impl.py:132,242,2062-2073` — Prefect `@flow`/`@task` patterns
- `mahavishnu/core/conductor.py:193-199` — Prefect `@task_decorator`/`@flow_decorator` patterns
- `mahavishnu/core/state_backends/mcp.py` — `MCPStateBackend` (existing state substrate)
- `mahavishnu/mcp/tools/clone_tools.py:161-231` — current stub `clone_refactor_group`
- `mahavishnu/workflows/clone_refactor_workflow.py` — current aspirational PR-shape DAG
- Commit `4090965b` — Phase 2m `pool_route_execute` (sync alternative)
- `docs/superpowers/specs/2026-04-09-tui-design.md` et al. — prior spec file format precedent

## 15. Revision history

- **v1** (2026-09-25) — Initial design. Replaces aspirational PR-shape DAG with git-tree DAG. UUID7 for `refactor_job_id`. MCPStateBackend as state substrate (no Dhara). Pre-DAG verify. No-auto-revert policy.
- **v2** (2026-09-25, current) — Multi-reviewer feedback applied:
  - Added Integration Contract blocks per `wire-up-contract.md` (mcp-integration-expert B1 + doc-review B1)
  - Renamed `workflow_key(refactor_job_id)` → `dag_key(refactor_job_id)` to avoid shadowing existing `workflow_key(execution_id)` (test-parity B1 + doc-review M6)
  - Fixed `workflows._detect_until_dry` → `core.loop_helpers.detect_until_dry` import path (mcp-integration-expert B3.1 + test-parity M9)
  - Fixed `tests/unit/state_backends/test_mcp_state_backend.py` → `tests/unit/test_mcp_state_backend.py` (mcp-integration-expert B3.2 + doc-review M9)
  - Added `sys.version_info >= (3, 14)` UUID7 guard + `requires-python = ">=3.14"` already pinned (test-parity B2 + doc-review m1)
  - Resolved sync/await contradiction on `verify_proposal`; signature confirmed at `core/verification.py:473` (doc-review B3)
  - Added §6.10 P0 `audit_orphans.py` scope verification
  - Added §6.11 P0 `fastmcp.test_client` availability verification
  - Added §5.5a Path probe (mandatory before §6.1)
  - Added §4.5 REQ-XXX traceability block (doc-review m6)
  - Fixed validation grep direction (tools → workflows, not workflows → tools; doc-review M18)
  - Added `@task(retries=2, retry_condition=retry_if_exception_type((GitCommitFailed,)))` so deterministic `GitApplyConflict` is not retried (doc-review m3)
  - Pinned UUID7 sort direction as descending (newest-first) per Layer 3 test name (doc-review M7)
  - Preserved `# Workflow-ID: 01JCLONEREF2026` and `# Approved by: les` headers required by `tests/unit/test_check_workflow_quarantine.py` (mcp-integration-expert M4)
  - Added stale docstring fix (`prefect_adapter_impl.py:1061` → `run_clone_refactor_dag`) (mcp-integration-expert M2)
  - Frontmatter `status: draft` → `partial` (per `doc-frontmatter-cleanup-2026-09-07.md`); added `revision: v2`
  - SHA examples un-abbreviated to 40-char hex

Next revision (v3) triggers: any post-implementation correction, any new project-state correction, or any spec section that diverges from the actual implementation by >20 LOC.
