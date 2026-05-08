# P2 Addendum — DharaStateBackend Interface

**Created**: 2026-05-07
**Amends**: `docs/plans/2026-04-02-storage-consolidation-and-akosha-role.md`
**Status**: approved — written to unblock P2 implementation

---

## DharaStateBackend Interface

Location: `mahavishnu/core/state_backends/dhara.py`

```python
class DharaStateBackend:
    async def put(self, key: str, value: dict, ttl: int | None = None) -> None
    async def get(self, key: str) -> dict | None
    async def delete(self, key: str) -> None
    async def list_prefix(self, prefix: str) -> list[tuple[str, dict]]
    @property
    def available(self) -> bool        # False in degraded-boot mode
```

Backed by `DharaClient.put()` and `DharaClient.call_tool("get", ...)`. If Dhara is unreachable at construction time, `available` is `False` and all writes become no-ops (degraded-boot). Reads return `None`.

---

## Key Schema

| Object | Key pattern |
|--------|-------------|
| Workflow execution | `workflow/v1/{execution_id}` |
| Pool state | `pool/v1/{pool_id}` |
| Routing decision | `routing/v1/{decision_id}` |
| Pending approval | `approval/v1/{request_id}` |

Schema version (`v1`) is embedded in the key, not the value, so key-range queries stay simple.

---

## WorkflowEngine Hook Points

There is no `WorkflowEngine` class. The equivalent is `MahavishnuApp.execute_workflow_with_fallback()` and related methods. Hook points:

- **Start**: persist `WorkflowExecution` (status=`running`) at start of `execute_workflow_with_fallback`
- **Success**: update status → `completed`, set `end_time`
- **Failure**: update status → `failed`, set `end_time` + `error` field
- **Pool spawn/close**: persist `PoolExecution` at `PoolManager.spawn_pool()` and `close_pool()`

All writes are fire-and-forget (`asyncio.create_task`). If Dhara is unavailable, `DharaStateBackend.put()` is a no-op — the orchestrator never blocks on persistence.

---

## RoutingDecisionBuffer Batched-Write Strategy

`RoutingDecisionBuffer` holds a `deque` of `RoutingDecision` objects per task class. Rather than writing each decision individually, flush on:

1. `PoolManager.close_pool()` — flush all buffered decisions for the pool
2. A periodic background task (60 s interval) initiated in `MahavishnuApp.wait_for_dependencies()`

Each flush serializes the buffer to JSON and writes one key: `routing/v1/{task_class}/{timestamp}`.

---

## Degraded-Boot Mode

Dhara dependency is already `required: false` in `settings/mahavishnu.yaml`. The `DharaStateBackend` mirrors this:

- If Dhara health check fails at startup, `backend.available = False`
- All writes silently skip; reads return `None`
- A `WARN` log is emitted once: `"Dhara unavailable — state persistence disabled"`
- Recovery: if a subsequent write finds Dhara responding, `available` flips to `True`

---

## Circuit-Breaker Policy

Reuse the existing `CircuitBreaker` in `mahavishnu/core/circuit_breaker.py`. Configure:

- failure threshold: 3 consecutive errors → open
- recovery timeout: 30 s
- half-open probe: 1 request

When the circuit is open, `DharaStateBackend.put()` logs at DEBUG and returns immediately. No new errors are propagated to the caller.

---

## Config Stanza

New field on `MahavishnuSettings`:

```python
class DharaStateConfig(BaseModel):
    enabled: bool = True
    flush_interval_seconds: int = 60
    max_routing_buffer_age_seconds: int = 3600
```

Added under `MahavishnuSettings.dhara_state: DharaStateConfig`.

The Dhara URL is already resolved by `MahavishnuApp._resolve_dhara_url()` from `health.dependencies.dhara`.
