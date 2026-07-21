---
status: complete
role: historical
topic: convergence-control-plane
date: 2026-07-16
last_reviewed: 2026-07-16
superseded_by: null
blocks_on: []
---

# Pre-Implementation Checklist

## **Document Version:** 1.0 **Created:** 2026-04-02 **Related:** Legacy integration roadmap removed on 2026-04-04 (OpenCode/OMO/Sisyphus support abandoned)

## Purpose

This checklist contains all items that MUST be completed before starting the Integration Implementation Roadmap. These items were identified by the Pentaverate Review (4 specialized agents) as critical blockers or high-risk issues.

**⚠️ Do not start Phase 1 until all P0 items are complete.**

______________________________________________________________________

## Summary

| Priority | Count | Status |
|----------|-------|--------|
| **P0 - Blocking** | 5 | ✅ 5/5 Complete |
| **P1 - Required Before Phase 2** | 4 | ✅ 4/4 Complete |
| **P2 - Recommended** | 3 | ⬜ Not Started |

**P0 Progress:**

- ✅ P0-1: Routing Module Infrastructure (`mahavishnu/core/routing.py`)
- ✅ P0-2: Factory Functions for Singletons (`mahavishnu/factories.py`)
- ✅ P0-3: Pydantic Models for Webhook Validation (`mahavishnu/webhooks/models.py`)
- ✅ P0-4: Rate Limiting Infrastructure (`pyproject.toml` + `mahavishnu/webhooks/router.py`)
- ✅ P0-5: Auth Pattern Correction (`mahavishnu/webhooks/router.py`)

______________________________________________________________________

## P0 - Must Complete Before Starting

### 1. Routing Module Infrastructure ✅ COMPLETE

**Why:** Phase 2 code references `mahavishnu/core/routing.py` which does not exist. This blocks all OMO integration work.

**Files Created:**

- [x] `mahavishnu/core/routing.py` ✓ (2026-04-02)

**Components Implemented:**

- [x] `TaskRouter` class with `classify_intent()` method
- [x] `RoutingStrategy` enum (COST, LATENCY, SUCCESS_RATE, BALANCED)
- [x] Intent classification patterns for task types
- [x] `generate_fallback_chain()` method

**Validation:**

```python
# This must work after completion:
from mahavishnu.core.routing import TaskRouter, RoutingStrategy

router = TaskRouter()
task_type = router.classify_intent("sweep backend repos for security")
# Returns: TaskType.AI_TASK or similar

chain = router.generate_fallback_chain(TaskType.AI_TASK)
# Returns: [AdapterType.AGNO, AdapterType.LLAMAINDEX, AdapterType.PREFECT]
```

**Estimated Effort:** 6-8 hours

______________________________________________________________________

### 2. Factory Functions for Singletons ✅ COMPLETE

**Why:** Plan code creates new `MahavishnuApp()` and `PoolManager()` instances in every function call. This is expensive and causes resource exhaustion.

**Files Created:**

- [x] `mahavishnu/factories.py` ✓ (2026-04-02)

**Functions Implemented:**

- [x] `get_pool_manager() -> PoolManager`
- [x] `get_websocket_server() -> MahavishnuWebSocketServer`
- [x] `get_terminal_manager() -> TerminalManager`
- [x] `initialize_websocket_server(pool_manager)`
- [x] `reset_all_factories()` (for testing)

**Validation:**

```python
# This must work after completion:
from mahavishnu.factories import get_pool_manager, get_websocket_server

pool_mgr = get_pool_manager()  # Returns singleton
pool_mgr2 = get_pool_manager()  # Same instance
assert pool_mgr is pool_mgr2
```

**Estimated Effort:** 3-4 hours

______________________________________________________________________

### 3. Pydantic Models for Webhook Validation

**Why:** Current webhook code accepts raw string parameters without validation, creating injection vulnerability.

**Files Created:**

- [x] `mahavishnu/webhooks/models.py` ✓ (2026-04-02)

**Models Implemented:**

- [x] `OpenClawSweepRequest` with tag validation (regex: `^[a-zA-Z0-9_-]+$`)
- [x] `OpenClawWorkflowRequest` with repo list validation (path traversal prevention)
- [x] `WebhookResponse` with typed fields
- [x] `WebhookErrorResponse`

**Validation:**

```python
# This must work after completion:
from mahavishnu.webhooks.models import OpenClawSweepRequest

# Valid request
req = OpenClawSweepRequest(tag="backend", adapter="agno")
assert req.tag == "backend"

# Invalid request (should raise)
try:
    OpenClawSweepRequest(tag="../../../etc/passwd", adapter="agno")
    assert False, "Should have raised"
except ValueError:
    pass
```

**Estimated Effort:** 2-3 hours

______________________________________________________________________

### 4. Rate Limiting Infrastructure ✅ COMPLETE

**Why:** External platforms can DoS webhook endpoints with unlimited requests.

**Implementation Completed:**

- [x] Add `slowapi` dependency to `pyproject.toml` ✓ (2026-04-02)
- [x] Configure limiter in webhook router ✓ (`mahavishnu/webhooks/router.py`)
- [x] Add `@rate_limit("10/minute")` to sweep endpoint ✓
- [x] Add `@rate_limit("5/minute")` to workflow endpoint ✓
- [x] Fallback handling when slowapi not installed ✓

**Estimated Effort:** 2-3 hours (Actual: ~1 hour)

______________________________________________________________________

### 5. Auth Pattern Correction ✅ COMPLETE

**Why:** Plan code references non-existent `validate_jwt()` function. Actual implementation uses `MultiAuthHandler.authenticate_request()`.

**Files Updated:**

- [x] `mahavishnu/webhooks/router.py` - Uses correct auth pattern ✓ (2026-04-02)

**Correct Pattern (Documented in router.py):**

```python
# CORRECT:
from mahavishnu.core.subscription_auth import MultiAuthHandler, AuthenticationError

async def validate_auth(
    authorization: str = Header(..., alias="Authorization"),
) -> dict:
    auth = MultiAuthHandler()
    try:
        result = auth.authenticate_request(authorization)
        if not result.get("authenticated"):
            raise HTTPException(401, "Authentication failed")
        return result
    except AuthenticationError as e:
        raise HTTPException(401, str(e))

# INCORRECT (from original plan):
# from mahavishnu.core.auth import validate_jwt  # DOES NOT EXIST
# user = await validate_jwt(authorization)
```

**Estimated Effort:** 1-2 hours (Actual: ~30 min)

______________________________________________________________________

## P1 - Required Before Phase 2

### 6. MahavishnuApp Routing Methods ✅ COMPLETE

**Why:** Phase 2 calls methods that don't exist: `execute_workflow_with_fallback()`, `execute_workflow_with_routing()`.

**Methods Implemented:**

- [x] `execute_workflow_with_fallback(task, repos, adapter_preference, ...)` ✓ (2026-04-02)
- [x] `execute_workflow_with_routing(task, repos, routing_strategy, ...)` ✓ (2026-04-02)

**Files Modified:**

- [x] `mahavishnu/core/app.py` - Added routing methods with TaskRouter integration ✓

**Depends On:** Item #1 (Routing Module) - ✅ Complete

**Estimated Effort:** 4-6 hours (Actual: ~1 hour)

______________________________________________________________________

### 7. Method Signature Validation ✅ COMPLETE

**Why:** Plan code calls methods with incorrect parameters.

**Validation Results:**

- [x] `pool_mgr.route_task(task, pool_selector, pool_affinity)` - VERIFIED ✓
  - Parameters match: `task: dict`, `pool_selector: PoolSelector | None`, `pool_affinity: str | None`
- [x] `app.get_repos(tag, role, user_id)` - VERIFIED ✓
  - Return type: `list[str]` (list of repository paths)
- [x] `ws.broadcast_workflow_started(workflow_id, metadata)` - VERIFIED ✓
  - Method exists in `websocket/server.py:488`
  - Parameters: `workflow_id: str`, `metadata: dict`
- [x] `app.execute_workflow_parallel(task, adapter_name, repos, ...)` - VERIFIED ✓
  - Parameters match: `task: dict`, `adapter_name: str`, `repos: list | None`

**Action:** Cross-reference all plan code against actual implementations.

**Estimated Effort:** 2-3 hours (Actual: ~20 min)

______________________________________________________________________

### 8. Feature Flags for Integrations ✅ COMPLETE

**Why:** Need ability to disable integrations without code changes.

**Flags Implemented:**

- [x] `INTEGRATION_PYDANTIC_AI_ENABLED` → `integrations.pydantic_ai_enabled` ✓
- [x] `INTEGRATION_OPENCLAW_WEBHOOKS_ENABLED` → `integrations.openclaw_webhooks_enabled` ✓
- [x] `INTEGRATION_OMO_ENABLED` → `integrations.omo_enabled` ✓
- [x] `INTEGRATION_CROSS_PLATFORM_MEMORY_ENABLED` → `integrations.cross_platform_memory_enabled` ✓

**Files Modified:**

- [x] `mahavishnu/core/config.py` - Added `IntegrationConfig` class ✓ (2026-04-02)

**Estimated Effort:** 1-2 hours (Actual: ~30 min)

______________________________________________________________________

### 9. Circuit Breakers for External Services ✅ COMPLETE

**Why:** External service failures shouldn't cascade.

**Components Implemented:**

- [x] Circuit breaker for Session-Buddy calls ✓ (`mahavishnu/pools/memory_aggregator.py`)
- [x] Circuit breaker for Akosha calls ✓ (`mahavishnu/pools/memory_aggregator.py`)
- [x] Fallback to local storage when external services unavailable ✓ (bounded deque buffer)
- [x] `_CircuitBreaker` class with can_execute/record_success/record_failure API ✓
- [x] `_buffer_items()` for local fallback when circuit is open ✓
- [x] `flush_local_buffer()` for retry on next sync cycle ✓
- [x] `get_circuit_breaker_stats()` for monitoring ✓

**Files Modified:**

- [x] `mahavishnu/pools/memory_aggregator.py` - Full circuit breaker integration ✓ (2026-04-03)

**Architecture:**

```
Session-Buddy Sync → circuit breaker check
  ├─ CLOSED → normal batch insert
  ├─ OPEN → buffer items locally (deque, max 500)
  └─ HALF-OPEN → allow one probe request

Akosha Sync → circuit breaker check
  ├─ CLOSED → aggregate_metrics call
  ├─ OPEN → skip with debug log
  └─ HALF-OPEN → allow one probe request

Periodic Sync → flush_local_buffer() on each cycle
```

**Estimated Effort:** 3-4 hours (Actual: ~2 hours)

______________________________________________________________________

## P2 - Recommended Before Starting

### 10. Method Contracts Documentation

**Why:** Integration developers need clear method contracts.

**Documentation to Create:**

- [ ] `docs/integrations/method-contracts.md`
- [ ] Document all `MahavishnuApp` public methods
- [ ] Document all `PoolManager` public methods
- [ ] Document all `WebSocketServer` public methods

**Estimated Effort:** 3-4 hours

______________________________________________________________________

### 11. Integration Test Prerequisites

**Why:** Each phase should have explicit test prerequisites.

**Tests to Create:**

- [ ] `tests/integration/test_routing.py` (for Phase 1.5)
- [ ] `tests/integration/test_pydantic_ai.py` (for Phase 1)
- [ ] `tests/integration/test_openclaw_webhooks.py` (for Phase 1)

**Estimated Effort:** 4-6 hours

______________________________________________________________________

### 12. Secret Rotation Documentation

**Why:** Production deployments need rotation procedures.

**Documentation to Create:**

- [ ] JWT secret rotation procedure
- [ ] Webhook secret rotation procedure
- [ ] Cross-platform secret sync procedure

**Estimated Effort:** 1-2 hours

______________________________________________________________________

## Verification Checklist

After completing all P0 items, verify:

### Routing Module

- [x] `from mahavishnu.core.routing import TaskRouter, RoutingStrategy` works ✓
- [x] `TaskRouter().classify_intent("test")` returns valid TaskType ✓
- [x] `TaskRouter().generate_fallback_chain(TaskType.AI_TASK)` returns list ✓

### Factory Functions

- [x] `from mahavishnu.factories import get_pool_manager` works ✓
- [x] Multiple calls return same instance ✓
- [x] `reset_all_factories()` clears singletons ✓

### Pydantic Models

- [x] `from mahavishnu.webhooks.models import OpenClawSweepRequest` works ✓
- [x] Invalid input raises ValidationError ✓
- [x] Valid input creates model instance ✓

### Rate Limiting

- [x] `slowapi>=0.1.9` added to `pyproject.toml` ✓
- [x] `@rate_limit("10/minute")` decorator applied to sweep endpoint ✓
- [x] `@rate_limit("5/minute")` decorator applied to workflow endpoint ✓
- [x] Graceful fallback when slowapi not installed ✓

### Auth Pattern

- [x] `from mahavishnu.core.subscription_auth import MultiAuthHandler` works ✓
- [x] `MultiAuthHandler().authenticate_request()` pattern documented in router.py ✓
- [x] `validate_auth()` dependency implemented with correct error handling ✓

______________________________________________________________________

## ✅ All P0 Items Complete

**Date Completed:** 2026-04-02

All 5 P0 blocking items have been successfully implemented:

1. ✅ Routing Module Infrastructure (`mahavishnu/core/routing.py`)
1. ✅ Factory Functions for Singletons (`mahavishnu/factories.py`)
1. ✅ Pydantic Models for Webhook Validation (`mahavishnu/webhooks/models.py`)
1. ✅ Rate Limiting Infrastructure (`pyproject.toml` + `mahavishnu/webhooks/router.py`)
1. ✅ Auth Pattern Correction (`mahavishnu/webhooks/router.py`)

**Ready to proceed with Integration Implementation Roadmap Phase 1.**

______________________________________________________________________

## Timeline Impact

| Scenario | Phase 1 Start | Phase 2 Start | Total Duration |
|----------|---------------|----------------|----------------|
| All P0 complete | Day 1 | Week 3 | 9 weeks |
| P0 incomplete | **BLOCKED** | **BLOCKED** | **BLOCKED** |
| P1 incomplete | Day 1 | **BLOCKED** | Extended |

______________________________________________________________________

## Sign-Off

Before proceeding with implementation:

- [ ] All P0 items verified complete
- [ ] Pre-implementation review meeting held
- [ ] Timeline adjusted if needed
- [ ] Resources allocated

______________________________________________________________________

## Document History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-04-02 | Pentaverate Review | Initial checklist from 4-agent review |
