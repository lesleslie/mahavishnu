# Mahavishnu Self-Improvement System Design

**Date:** 2026-02-20
**Status:** Approved
**Author:** Claude + Les

---

## Overview

This design defines how Mahavishnu leverages its own capabilities to systematically improve code quality, track issues, and build a continuous self-improvement pipeline.

## Goals

1. **Phase 1:** Fix all P0/P1 issues from the Power Trios review using parallel agent pools
2. **Phase 2:** Establish dual-tracking system (ecosystem.yaml + Session-Buddy) for all findings
3. **Phase 3:** Build triggered workflow for continuous review-and-fix automation

---

## Architecture

```
+-------------------------------------------------------------------------+
|                    MAHAVISHNU SELF-IMPROVEMENT SYSTEM                    |
+-------------------------------------------------------------------------+
|                                                                          |
|  +-------------+    +-------------+    +-------------+                  |
|  |   PHASE 1   |    |   PHASE 2   |    |   PHASE 3   |                  |
|  |  Fix P0/P1  |--->|  Triage All |--->|  Automate   |                  |
|  |  Issues     |    |  Findings   |    |  Pipeline   |                  |
|  +-------------+    +-------------+    +-------------+                  |
|                                                                          |
+-------------------------------------------------------------------------+
```

---

## Phase 1: Fix P0/P1 Issues (Parallel Agents)

### Pool Architecture

```
+-------------------------------------------------------------------------+
|                         FIX POOL ORCHESTRATION                           |
+-------------------------------------------------------------------------+
|                                                                          |
|  +-----------------+  +-----------------+  +-----------------+          |
|  | Security Pool   |  | Perf Pool       |  | Python Pool     |          |
|  | (3 workers)     |  | (3 workers)     |  | (3 workers)     |          |
|  +--------+--------+  +--------+--------+  +--------+--------+          |
|           |                    |                    |                    |
|           v                    v                    v                    |
|  +-------------------------------------------------------------+        |
|  |                    QUALITY GATE CHECKPOINT                   |        |
|  |  +---------+   +---------+   +---------------+               |        |
|  |  | Fast    |-->| Tests   |-->| Comprehensive |               |        |
|  |  | Hooks   |   |         |   | Hooks         |               |        |
|  |  | (~5s)   |   |         |   | (~30s)        |               |        |
|  |  +---------+   +---------+   +---------------+               |        |
|  +-------------------------------------------------------------+        |
|           |                                                              |
|           v                                                              |
|  +-------------------------------------------------------------+        |
|  |                    MANUAL APPROVAL GATES                     |        |
|  |  +-----------------+         +-----------------+             |        |
|  |  | Version Bump?   |--> X -->| Publish?        |--> X --> Done        |
|  |  | (Auto-suggest)  |         | (PyPI/GitHub)   |             |        |
|  |  +-----------------+         +-----------------+             |        |
|  +-------------------------------------------------------------+        |
|                                                                          |
+-------------------------------------------------------------------------+
```

### Issue Assignment to Pools

| Issue ID | Issue | Pool | Agent Type | Priority |
|----------|-------|------|------------|----------|
| `MHV-001` | `asyncio.run()` in sync context | python | `python-pro` | P0 |
| `MHV-002` | Missing `logger` import | python | `python-pro` | P0 |
| `MHV-003` | No shutdown events (4 files) | perf | `performance-engineer` | P0 |
| `MHV-004` | N+1 HTTP batch insert | perf | `performance-engineer` | P1 |
| `MHV-005` | SSRF URL blocklist | security | `security-auditor` | P1 |
| `MHV-006` | Heap synchronization | perf | `performance-engineer` | P1 |
| `MHV-007` | `datetime.utcnow()` deprecation | python | `python-pro` | P2 |
| `MHV-008` | Status enum consolidation | python | `refactoring-specialist` | P2 |

### Quality Gate Flow Per Fix

```python
async def execute_fix_with_gates(
    pool_id: str,
    issue: CrossRepoIssue,
    fix_prompt: str,
) -> FixResult:
    """Execute a fix with full quality gate enforcement."""

    # 1. Execute fix in pool
    result = await pool_manager.execute_on_pool(pool_id, {
        "prompt": fix_prompt,
        "issue_id": issue.id,
        "files": issue.affected_files,
    })

    if not result.success:
        return FixResult(success=False, stage="execution", error=result.error)

    # 2. Run quality gates
    quality = await crackerjack.run_quality_checks(
        fast_only=False,
        autofix=True,
    )

    # 3. Gate enforcement
    gate_result = QualityGateResult(
        fast_hooks=quality.fast_hooks_passed,
        tests=quality.tests_passed,
        comprehensive=quality.comprehensive_hooks_passed,
        coverage=quality.coverage_percentage,
    )

    # Block on fast hooks and tests
    if not quality.fast_hooks_passed:
        return FixResult(success=False, stage="fast_hooks", gates=gate_result)

    if quality.test_failed_count > 0:
        return FixResult(success=False, stage="tests", gates=gate_result)

    # 4. Update issue status
    await coordination_manager.update_issue(
        issue.id,
        status=IssueStatus.RESOLVED,
        resolution={
            "fixed_by": result.worker_id,
            "quality_gates": gate_result.to_dict(),
            "timestamp": datetime.now(UTC).isoformat(),
        },
    )

    # 5. Request manual approval for version bump
    approval = await request_manual_approval(
        approval_type="version_bump",
        context={
            "issue_id": issue.id,
            "changes": result.changes,
            "quality_gates": gate_result.to_dict(),
        },
    )

    if approval.rejected:
        return FixResult(success=True, stage="version_rejected", gates=gate_result)

    # 6. Bump version (if approved)
    if approval.version_bump:
        await crackerjack.bump_version(approval.version_bump)

    # 7. Request manual approval for publish
    publish_approval = await request_manual_approval(
        approval_type="publish",
        context={
            "version": new_version,
            "changes_summary": result.changes_summary,
        },
    )

    if publish_approval.approved:
        await crackerjack.publish()

    return FixResult(success=True, stage="complete", gates=gate_result)
```

### Quality Gate Stages

**Stage 1: Fast Hooks (~5s)**
- Ruff format + lint
- Import sorting
- Trailing whitespace, EOF fixes
- Retry once on failure

**Stage 2: Tests**
- Parallel execution (pytest-xdist)
- Collect ALL failures (don't stop on first)
- Coverage reporting

**Stage 3: Comprehensive Hooks (~30s)**
- Type checking (Zuban/mypy via LSP)
- Security scanning (Bandit)
- Complexity analysis
- Dead code detection (Skylos)

---

## Phase 2: Triage & Track (Dual Tracking)

### ecosystem.yaml Structure

```yaml
coordination:
  issues:
    - id: MHV-001
      title: "asyncio.run() called in sync context"
      description: |
        app.py:707 calls asyncio.run() inside _check_user_repo_permission
        which will fail at runtime when called from async code.
      severity: critical
      priority: P0
      status: pending  # pending -> in_progress -> resolved
      pool: python
      affected_files:
        - mahavishnu/core/app.py
      created_at: 2026-02-20T11:30:00Z
      labels: [async, bug, runtime-error]

  plans:
    - id: PLAN-001
      title: "Phase 1 Critical Fixes"
      description: "Fix all P0 issues before any P1/P2 work"
      issue_ids: [MHV-001, MHV-002, MHV-003]
      status: in_progress

  todos:
    - id: TODO-001
      issue_id: MHV-003
      task: "Add shutdown events to resilience.py background loop"
      status: pending
```

### Session-Buddy Integration

Store reflections after each fix for learning:

```python
async def capture_fix_reflection(
    issue: CrossRepoIssue,
    fix_result: FixResult,
    quality_gates: QualityGateResult,
) -> None:
    """Store fix pattern in Session-Buddy for future learning."""

    reflection = f"""
    ## Fix Pattern: {issue.title}

    **Issue Type**: {issue.labels}
    **Root Cause**: {fix_result.root_cause}
    **Solution**: {fix_result.solution_summary}
    **Files Changed**: {issue.affected_files}
    **Quality Gates**: Fast={quality_gates.fast_hooks}, Tests={quality_gates.tests}, Coverage={quality_gates.coverage}%

    **Key Learnings**:
    {fix_result.learnings}

    **Similar Issues to Watch For**:
    {fix_result.similar_patterns}
    """

    await session_buddy.store_reflection(
        subcategory="code_fixes",
        content=reflection,
        metadata={
            "issue_id": issue.id,
            "pool": issue.pool,
            "priority": issue.priority,
        },
    )
```

---

## Phase 3: Continuous Pipeline (Triggered)

### New MCP Tool: `review_and_fix`

```python
@mcp.tool
async def review_and_fix(
    scope: Literal["critical", "security", "performance", "quality", "all"] = "critical",
    auto_fix: bool = False,
    dry_run: bool = False,
) -> dict:
    """
    Run comprehensive review and optionally fix issues.

    Args:
        scope: Review scope - "critical" (P0 only), "security", "performance",
               "quality" (code quality), or "all"
        auto_fix: If True, automatically spawn fix pools for found issues
        dry_run: If True, report findings without making changes

    Returns:
        {
            "findings": [...],
            "issues_created": [...],
            "fixes_applied": [...],
            "quality_gates": {...},
            "approval_requests": [...],
        }
    """
```

### Workflow Definition

```
+-------------------------------------------------------------------------+
|                    REVIEW AND FIX WORKFLOW                               |
+-------------------------------------------------------------------------+
|                                                                          |
|  User: /mahavishnu review-and-fix --scope critical                      |
|                                                                          |
|  STEP 1: SPAWN REVIEW AGENTS                                             |
|  +-----------+ +-----------+ +-----------+ +-----------+                |
|  |Architect  | |Security   | |Python Pro | |Perf Eng   |                |
|  |(Opus)     | |(Sonnet)   | |(Sonnet)   | |(Sonnet)   |                |
|  +-----------+ +-----------+ +-----------+ +-----------+                |
|                                                                          |
|  STEP 2: AGGREGATE FINDINGS                                              |
|  findings = merge_and_dedupe([architect, security, python, perf])       |
|                                                                          |
|  STEP 3: CREATE ISSUES IN ecosystem.yaml                                 |
|  for finding in findings:                                                |
|      coordination_manager.create_issue(CrossRepoIssue(...))             |
|                                                                          |
|  STEP 4: STORE REFLECTIONS IN SESSION-BUDDY                              |
|  session_buddy.store_reflection(subcategory="review_findings", ...)     |
|                                                                          |
|  STEP 5: PRESENT SUMMARY TO HUMAN                                        |
|  +-----------------------------------------------------------+          |
|  |  REVIEW COMPLETE                                           |          |
|  |  Findings: 17 issues (3 P0, 4 P1, 10 P2)                  |          |
|  |  Issues Created: MHV-001 through MHV-017                   |          |
|  |  [Fix P0 Issues Now?]  [View Details]  [Done]              |          |
|  +-----------------------------------------------------------+          |
|                                                                          |
|  if auto_fix:                                                            |
|      STEP 6: SPAWN FIX POOLS                                             |
|      pool_manager.spawn_pool("security", ...)                            |
|      pool_manager.spawn_pool("performance", ...)                         |
|      pool_manager.spawn_pool("python", ...)                              |
|                                                                          |
|      STEP 7: QUALITY GATES PER FIX                                       |
|      Fast Hooks -> Tests -> Comprehensive Hooks                          |
|                                                                          |
|      STEP 8: MANUAL APPROVAL GATES                                       |
|      +-----------------------------------------------------------+      |
|      |  FIXES COMPLETE - APPROVAL REQUIRED                      |      |
|      |  [Approve Version Bump] [Skip]                            |      |
|      |  [Publish to PyPI] [GitHub Release] [Skip]                |      |
|      +-----------------------------------------------------------+      |
|                                                                          |
+-------------------------------------------------------------------------+
```

---

## Manual Approval System

### Data Structures

```python
@dataclass
class ApprovalRequest:
    """Represents a pending approval request."""
    id: str
    approval_type: Literal["version_bump", "publish"]
    context: dict[str, Any]
    created_at: datetime
    expires_at: datetime
    options: list[ApprovalOption]

@dataclass
class ApprovalOption:
    """An option the user can select."""
    label: str
    description: str
    action: Callable[[], Awaitable[None]]
    is_recommended: bool = False
```

### Approval Flow

```python
async def request_manual_approval(
    approval_type: Literal["version_bump", "publish"],
    context: dict[str, Any],
) -> ApprovalResult:
    """Request manual approval via WebSocket broadcast and CLI prompt."""

    request = ApprovalRequest(
        id=str(uuid.uuid4()),
        approval_type=approval_type,
        context=context,
        created_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) + timedelta(minutes=30),
        options=_build_options(approval_type, context),
    )

    # Broadcast to WebSocket clients (dashboard)
    await websocket_server.broadcast(
        channel="approvals",
        event="approval_required",
        data=request.to_dict(),
    )

    # Also prompt via CLI if interactive
    if sys.stdin.isatty():
        result = await cli_prompt_approval(request)
    else:
        # Wait for WebSocket response
        result = await wait_for_approval_response(request.id, timeout=1800)

    return result
```

---

## WebSocket Events

```python
# Review progress events
"review:review_started"     -> {"scope": "critical"}
"review:agent_completed"    -> {"agent": "security", "findings": 3}
"review:review_completed"   -> {"total_findings": 17}

# Fix progress events
"fix:fix_started"           -> {"issue_id": "MHV-001", "pool": "python"}
"fix:quality_gate"          -> {"stage": "fast_hooks", "passed": True}
"fix:fix_completed"         -> {"issue_id": "MHV-001"}

# Approval events
"approvals:approval_required" -> {"type": "version_bump", "suggested": "0.24.3"}
"approvals:approval_granted"  -> {"type": "version_bump"}
```

---

## Files to Create/Modify

| File | Purpose |
|------|---------|
| `mahavishnu/mcp/tools/self_improvement_tools.py` | New MCP tools: `review_and_fix`, `request_approval` |
| `mahavishnu/core/approval_manager.py` | Manual approval workflow |
| `mahavishnu/core/fix_orchestrator.py` | Orchestrates fix pools with quality gates |
| `settings/ecosystem.yaml` | Issue/plan/todo tracking |

---

## Success Criteria

### Phase 1
- [ ] All P0 issues fixed and verified through quality gates
- [ ] All P1 issues fixed or triaged
- [ ] Zero regression in test coverage
- [ ] All changes pass fast hooks, tests, and comprehensive hooks

### Phase 2
- [ ] All 17 review findings tracked in ecosystem.yaml
- [ ] Reflections stored in Session-Buddy for each fix
- [ ] Dependency graph established between issues

### Phase 3
- [ ] `review_and_fix` MCP tool implemented
- [ ] Manual approval gates working for version bump and publish
- [ ] WebSocket broadcasting for real-time monitoring
- [ ] End-to-end workflow tested

---

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| Fix introduces regression | Quality gates block merge; tests must pass |
| Auto-fix breaks unrelated code | Scope fixes to specific files; review diffs |
| Approval timeout | Default 30min expiry; can extend |
| Pool worker failure | Retry logic; fallback to sequential execution |
| Session-Buddy unavailable | Continue without reflections; log warning |

---

## Future Enhancements

1. **Scheduled Reviews**: Automatic periodic reviews (daily/weekly)
2. **Git Hook Integration**: Pre-commit triggers review on critical paths
3. **Slack/Teams Notifications**: Approval requests via chat
4. **Metrics Dashboard**: Grafana dashboard for review/fix metrics
5. **Learning from Fixes**: Use Session-Buddy reflections to prevent similar issues
