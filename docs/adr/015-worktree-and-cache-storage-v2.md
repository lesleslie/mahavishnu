---
status: proposed
role: canonical
date: 2026-08-23
last_reviewed: 2026-08-23
supersedes: "015-worktree-and-cache-storage"
blocks_on: []
decision_date: null
topic: storage-abstraction
related:
  - "015-multi-agent-review"
  - "006-simplify-storage-architecture"
  - "013-mahavishnu-dhara-adapter-tool-boundary"
  - "001-use-oneiric"
---

# ADR 015: Worktree and Cache Storage Architecture (Revised)

## Status

**Proposed v2** — supersedes the v1 proposal of the same name (see `015-multi-agent-review.md` for the 9-agent review that drove these revisions). v1 was not ratifiable per the reviewers' consensus; v2 restructures around extending existing abstractions rather than building parallel layers.

**Date:** 2026-08-23

## What changed from v1

v1 proposed two new top-level protocols (`WorktreeStorage`, `CacheBackend`). The multi-agent review (9 reviewers) identified 12 BLOCKERs and ~30 IMPORTANT issues. The dominant theme: **v1 duplicated work that already exists.**

v2 restructures as **extend, not build**:

| v1 (proposed, rejected) | v2 (proposed) |
|---|---|
| New `WorktreeStorage` Protocol parallel to existing `WorktreeProvider` | Extend existing `WorktreeProvider` ABC with new subclasses (`LocalWorktreeProvider`, `S3WorktreeProvider`) |
| New `CacheBackend` Protocol parallel to Oneiric's `MultiTierCacheAdapter` | Use Oneiric's existing `MultiTierCacheAdapter` (Redis L1 + Memory L2 already done) |
| New `GitBundleWorktreeBackend` as a peer of Local/S3 | `BundleTransport` as a decorator over any backend (transport, not storage) |
| `MAHAVISHNU_WORKTREE_BACKEND=local\|s3\|gcs\|azure\|bundle` env var | Oneiric's `ResolverSettings.selections` with capability-based resolution |
| `MAHAVISHNU_CACHE_BACKEND` env var | Same: Oneiric resolver picks cache adapter |
| New env vars bypassing `MahavishnuSettings` | New `StorageSettings(BaseModel)` nested in existing `MahavishnuSettings` (Pydantic-validated) |
| `LocalWorktreeBackend` using `git bundle create` + `git clone --reference` (defeats worktree performance) | `LocalWorktreeProvider` using `git worktree add` directly (preserves object-DB sharing) |
| `WorktreeHandle` = "UUID + metadata" (hand-waved) | `@dataclass(frozen=True, slots=True)` with full field definitions |
| `WorktreeRef` types mentioned but undefined | Sealed-class pattern with `runtime_checkable` discriminator |
| `DharaCacheBackend` (cache substrate, ADR-013 violation) | Dropped; persistent state already routed through Dhara via ADR-013 |
| No `health()` method | `health()` and `__aenter__`/`__aexit__` on Protocols |
| No concurrency / locking | Explicit `lock()` method on storage protocols |
| No SLOs | SLOs with concrete numbers per backend |
| No observability | Metric names + dashboards + runbooks |
| No multi-tenancy | `principal: Principal` parameter on all operations |
| No bundle integrity | SHA-256 stored alongside each bundle, verified at fetch time |
| Phase 0 force-push on `origin/main` | Phase 0 uses `git revert` (preserves history) |
| Phase 0 + 1 + 2 + 3 + 4 (4-5 days estimated) | Realistic 7-10 days, restructured to extend-don't-build |

## Context

A 2026-08-23 ecosystem audit surfaced three related problems:

**Worktrees** — 210 total, 83 misplaced. The misplacement stems from three bugs:
1. `MAHAVISHNU_AUTO_WORKTREE_ROOT` defaults to `~/worktrees` (literal hardcoded string), but actual code path produces `~/worktrees/agent-<hex8>/` (wrong sub-shape).
2. Auto-worktree tool computes `parent/<repo>.worktrees/<branch>/` (sibling of repo).
3. Result: 65 mahavishnu `agent-*` worktrees in `~/worktrees/`, 16 fastblocks siblings at `~/Projects/{fb-*,fastblocks-task*}`, 1 neo4j sibling at `~/Projects/neo4j-mcp.worktrees/`, 1 fastblocks `phase-5-v4` at `~/.claude/worktrees/`.

**Caches** — 22+ GB scattered across the filesystem. 24 per-MCP `.venv/` (~18 GB), 29 per-repo `.crackerjack/` (3 GB), per-repo tooling caches (~3.4 GB), stray `~/.cache/*` dirs.

**Deployment model** — serverless deploys make the package directory read-only and `/tmp` ephemeral. Whatever default path mahavishnu writes to **must** work for serverless. Three commits on `origin/main` (`eb247784`, `2f3649f9`, `c0b09a06`) hardcoded `~/Projects/worktrees` and are known wrong pending this ADR.

### What already exists (don't rebuild)

- **`mahavishnu/core/worktree_providers/`** — `WorktreeProvider` ABC with `create_worktree`/`remove_worktree`/`list_worktrees`/`health_check`, `WorktreeProviderRegistry` with fallback, three concrete providers (`direct_git.py`, `session_buddy.py`, `mock.py`).
- **`mahavishnu/core/worktree_coordination.py`** — `WorktreeCoordinator` is on the production call path (CLI + MCP both call `app.worktree_coordinator`). `WorktreeManager` is **not** on the production call path; v1 wired into the wrong class.
- **`oneiric/oneiric/adapters/storage/`** — `LocalStorageAdapter`, `S3StorageAdapter`, `GCSStorageAdapter`, `AzureBlobStorageAdapter` with consistent blob API (`init`/`health`/`cleanup`/`save`/`read`/`delete`/`list`/`exists`).
- **`oneiric/oneiric/adapters/cache/`** — `RedisCacheAdapter`, `MemoryCacheAdapter`, `MultiTierCacheAdapter` (L1+L2 with metrics, write-through, L2-hit write-back).
- **`oneiric/oneiric/core/resolution.py`** — `ResolverSettings.selections` for capability-based backend selection with DecisionEvent audit trail.
- **`mahavishnu/mahavishnu/core/paths.py`** — XDG-correct path helpers via `platformdirs`. `DATA_DIR = Path(_dirs.user_data_dir)` resolves to the right OS-specific location.
- **`mahavishnu/mahavishnu/core/config.py`** — `MahavishnuSettings(BaseSettings)` with nested `BaseModel` sections (`A2ASettings`, `ContainerSettings`). All `MAHAVISHNU_*` env vars flow through Pydantic here.
- **Dhara** (`dhara/dhara/mcp/kv_timeseries.py`) — put/get/TTL substrate; ADR-013 already routes durable state through it.
- **Redis** — local instance available; `maxmemory 2gb` + `maxmemory-policy allkeys-lfu` is the recommended default.
- **`mahavishnu/.claude/hooks/worktree-session-isolation.py`** — the SessionStart hook that calls `git worktree add` directly. Reads `MAHAVISHNU_AUTO_WORKTREE_ROOT` independently of `WorktreeManager`.

## Decision Drivers

- **Distributable.** Whatever default we pick must work in any deployment, not just one developer's local checkout.
- **Serverless-safe.** A misconfigured default must error clearly, not silently lose data.
- **Extend, don't build.** Oneiric's storage adapters, Oneiric's cache adapters, and mahavishnu's `WorktreeProvider` already exist. The work is to wire them up and add what's missing (a worktree-VCS wrapper, not a new abstraction layer).
- **Hot/persistent/regenerable have different homes.** Hot cache (Redis) ≠ persistent state (Dhara) ≠ regenerable cold cache (XDG disk). Conflating them is what produced the mess.
- **No data loss during migration.** The 83 misplaced worktrees, 24 per-MCP `.venv/` dirs, and 29 `.crackerjack/` dirs all contain potentially-active work or recoverable state.
- **Operational maturity.** SLOs, observability, rollback, runbooks — these are required before ratification, not after.

## Decision

### 1. Storage: use Oneiric's existing storage adapters directly

**No new `WorktreeStorage` Protocol.** The four Oneiric storage adapters (`LocalStorageAdapter`, `S3StorageAdapter`, `GCSStorageAdapter`, `AzureBlobStorageAdapter`) already provide what we need. Wire them through the existing `WorktreeProvider` hierarchy by adding new subclasses:

```python
# mahavishnu/core/worktree_providers/local.py (extends existing)
class LocalWorktreeProvider(WorktreeProvider):
    """Uses git worktree add + LocalStorageAdapter for bundle metadata."""
    def __init__(self, settings: StorageSettings, registry: WorktreeProviderRegistry):
        self._settings = settings
        self._storage = LocalStorageAdapter(LocalStorageSettings(
            base_path=get_data_path("worktrees"),
        ))
        self._registry = registry
        self._logger = get_logger("adapter.worktree.local").bind(...)

    async def create_worktree(
        self, repo: str, branch: str, base_ref: str,
        principal: Principal, *,
    ) -> WorktreeHandle:
        # Uses git worktree add directly (preserves .git/objects/ sharing)
        # Bundle is OPTIONAL via BundleTransport decorator
        ...
```

```python
# mahavishnu/core/worktree_providers/s3.py (new)
class S3WorktreeProvider(WorktreeProvider):
    """Uses git bundle + S3StorageAdapter for serverless-friendly storage."""
    def __init__(self, settings: StorageSettings, registry: WorktreeProviderRegistry):
        self._storage = S3StorageAdapter(S3StorageSettings(
            bucket=settings.s3_bucket,
            region=settings.s3_region,
        ))
        ...
```

The `WorktreeProviderRegistry.get_available_provider()` (already implemented in `worktree_providers/registry.py`) handles the fallback chain. The new providers register as `category="worktree-storage"` via Oneiric's adapter registry and are selected by capability.

**### 3. Cache: use Oneiric's existing cache adapters directly

**No new `CacheBackend` Protocol.** Oneiric's `MultiTierCacheAdapter` already does L1 (memory) + L2 (Redis) with metrics, write-through, and L2-hit write-back. Use it.

For warm/cold caches (regenerable, large, low-frequency), use Oneiric's `LocalStorageAdapter` via a thin wrapper. For persistent state (worktree registry, session metadata, audit log), use Dhara via the existing `dhara_adapter.py` — not a new cache layer.

The `CacheBackend` name collision (existing `StrEnum` at `mahavishnu/core/cache_manager.py:41-46`) is avoided because we're not adding a new Protocol with that name. The existing `CacheBackend` StrEnum stays as-is; new code uses the Oneiric adapters directly.

### 4. Backend selection: Oneiric's `ResolverSettings.selections`

Replace the env-var switcher (`MAHAVISHNU_WORKTREE_BACKEND=local|s3|...`) with Oneiric's capability-based resolver:

```yaml
# settings/mahavishnu.yaml
storage:
  worktree_provider_selection: "default"  # ResolverSettings.selections key
  cache_provider_selection: "default"
  s3_bucket: "mahavishnu-worktrees-prod"
  s3_region: "us-east-1"
  cache:
    redis_url: "redis://localhost:6379/0"
    maxmemory_policy: "allkeys-lfu"
    ttl_seconds: 3600
```

```python
# Code
worktree_provider = await resolver.resolve(
    domain="worktree-provider",
    selection=settings.storage.worktree_provider_selection,
)
cache_adapter = await resolver.resolve(
    domain="cache",
    selection=settings.storage.cache_provider_selection,
)
```

This preserves Oneiric's `DecisionEvent` audit trail (per ADR-001) and means CLI/agent code calls `resolver.resolve(...)` instead of branching on an env var.

### 5. Multi-tenancy from day one

Every operation takes a `principal: Principal` parameter. The Local backend refuses to cross user boundaries (`os.getuid()` check on long-running hosts). The S3 backend uses principal-prefixed keys (`s3://<bucket>/worktrees/<principal>/<repo>/<branch>/`). The `Principal` type is the same one already used by `mahavishnu/mcp/auth.py` for the existing MCP auth boundary.

```python
@dataclass(frozen=True, slots=True)
class WorktreeHandle:
    handle_id: str  # UUID4 hex
    principal: Principal
    repo: str
    branch: str
    base_ref: str
    created_at: datetime
    storage_ref: WorktreeRef  # discriminated union, see below
```

### 6. Bundle integrity (SHA-256 + optional signature)

Every bundle is hashed at creation time; the SHA-256 is stored alongside (or in Dhara). At fetch time, the hash is verified before extraction. Mismatch → `WorktreeIntegrityError` + audit log entry.

```python
@dataclass(frozen=True, slots=True)
class BundleRef:
    bundle_key: str
    sha256: str  # hex-encoded
    signature: str | None  # optional detached GPG/sigstore signature
    created_at: datetime
    bytes_size: int
```

### 7. Serverless safety in Oneiric's `LocalStorageAdapter`

The `os.access(W_OK)` check belongs in Oneiric's `LocalStorageAdapter.init()`, not in every mahavishnu backend. The local backend should not duplicate this check. If `LocalStorageAdapter.init()` raises `LifecycleError("local-storage-readonly-filesystem")` (an enhancement to Oneiric), the local worktree provider propagates that error and the operator sees the same clear message.

This requires a small enhancement to Oneiric (file: `oneiric/oneiric/adapters/storage/local.py`). Tracked as a sub-task of this ADR's Phase 0.

### 8. Update `.claude/hooks/worktree-session-isolation.py`

The hook reads `MAHAVISHNU_AUTO_WORKTREE_ROOT` (line 53) and validates worktree paths fall under it. With the new design, the hook must:

1. Read the configured `StorageSettings.worktree_base_path` (via `get_data_path("worktrees")` from `paths.py`).
2. Update `WorktreePathValidator.allowed_roots` to include the new path.
3. Keep `MAHAVISHNU_AUTO_WORKTREE_ROOT` as a per-deployment override (deprecated in favor of `StorageSettings.worktree_base_path`).

### 9. Path resolution uses `paths.py`

The new code calls `get_data_path("worktrees", repo, branch) / ".bundle"` — using the existing platformdirs-correct helper from `mahavishnu/mahavishnu/core/paths.py`. No hand-rolled `Path.home() / ".local" / ...` paths.

### 10. Settings via Pydantic, not env vars

New `StorageSettings(BaseModel)` nested in `MahavishnuSettings`:

```python
class StorageSettings(BaseModel):
    """Storage backend selection (ADR 015)."""

    worktree_provider_selection: Literal["default", "local-only", "s3-primary"] = "default"
    cache_provider_selection: Literal["default", "memory-only", "redis-primary"] = "default"
    worktree_base_path: Path | None = None  # defaults to get_data_path("worktrees")
    cache_ttl_seconds: int = Field(default=3600, gt=0)
    bundle_integrity_required: bool = True

    # Cloud-specific fields (only loaded when the matching provider is selected)
    s3_bucket: str | None = None
    s3_region: str = "us-east-1"
    s3_endpoint_url: str | None = None
    s3_kms_key_id: str | None = None

    redis_url: str = "redis://localhost:6379/0"
    redis_tls: bool = True  # refuse plaintext unless explicitly disabled
    redis_password: SecretStr | None = None

    dhara_endpoint: str | None = None
    dhara_auth_token: SecretStr | None = None
```

`MahavishnuSettings(BaseSettings)` loads this from YAML or env vars via Pydantic's standard machinery. No parallel config surface.

### 11. Concrete type definitions

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import IO, Protocol, Self, runtime_checkable

from mahavishnu.auth import Principal

@dataclass(frozen=True, slots=True)
class WorktreeHandle:
    handle_id: str
    principal: Principal
    repo: str
    branch: str
    base_ref: str
    created_at: datetime
    storage_ref: WorktreeRef
    sha256: str  # bundle integrity
    bytes_size: int


@runtime_checkable
class WorktreeRef(Protocol):
    """Backend-typed reference. Use isinstance() to discriminate."""
    backend_kind: str  # "local" | "s3" | "gcs" | "azure"


@dataclass(frozen=True, slots=True)
class LocalWorktreeRef:
    path: Path
    worktree_id: str
    backend_kind: Literal["local"] = "local"


@dataclass(frozen=True, slots=True)
class S3WorktreeRef:
    bucket: str
    key: str
    backend_kind: Literal["s3"] = "s3"


class WorktreeIntegrityError(Exception):
    """Bundle hash mismatch at fetch time."""
    pass


class WorktreeLocked(Exception):
    """Another process holds the lock for this (repo, branch)."""
    pass


class WorktreeProvider(Protocol):
    """Extends the existing mahavishnu/core/worktree_providers/base.py ABC."""

    async def __aenter__(self) -> Self: ...
    async def __aexit__(self, *exc_info: object) -> None: ...

    async def health(self) -> bool: ...

    async def create_worktree(
        self,
        repo: str,
        branch: str,
        base_ref: str,
        principal: Principal,
    ) -> WorktreeHandle: ...

    async def fetch(
        self,
        handle: WorktreeHandle,
    ) -> WorktreeRef:
        """Materializes the worktree. Verifies SHA-256. Raises WorktreeIntegrityError on mismatch."""
        ...

    async def list(
        self,
        principal: Principal | None = None,
        repo: str | None = None,
    ) -> list[WorktreeHandle]: ...

    async def exists(self, handle: WorktreeHandle) -> bool: ...

    async def remove(self, handle: WorktreeHandle) -> None: ...

    async def lock(
        self,
        repo: str,
        branch: str,
        timeout: float = 10.0,
    ) -> AsyncContextManager[None]:
        """Distributed lock via Oneiric or Dhara. Raises WorktreeLocked if held by another process."""
        ...
```

### 12. SLOs (concrete)

| Backend | Operation | p50 | p95 | p99 | Availability |
|---|---|---|---|---|---|
| Local | create_worktree | <50ms | <200ms | <500ms | 99.9% |
| Local | fetch | <20ms | <100ms | <300ms | 99.9% |
| S3 | create_worktree | <500ms | <2s | <5s | 99.5% (depends on AWS S3 SLA) |
| S3 | fetch | <300ms | <1.5s | <4s | 99.5% |
| Redis (L1 miss → L2) | cache.get | <5ms | <20ms | <50ms | 99.9% |
| Dhara | state.set | <20ms | <100ms | <300ms | 99.5% |

Error budget: 99.9% success over 30 days. Multi-window burn-rate alerts per Google SRE workbook.

### 13. Observability metrics

Per-backend metrics, exported via Oneiric's `LifecycleManager` and Mahavishnu's OTel collector:

```
worktree_create_duration_seconds{backend,status,principal}
worktree_fetch_duration_seconds{backend,status,principal}
cache_get_duration_seconds{backend,hit}
cache_set_duration_seconds{backend}
backend_health_check_failed_total{backend}
bundle_bytes{repo}
bundle_integrity_failure_total{backend,principal}
cache_fallback_total{from,to}
cache_evicted_total{backend,reason}
```

Trace spans: `worktree.create`, `worktree.fetch`, `cache.get`, `cache.set` with structured logs (`backend`, `operation`, `duration_ms`, `error_class`, `request_id`).

### 14. Migration plan (revised, realistic estimates)

**Phase 0: Revert + bootstrap (1 day, BLOCKED on this ADR ratification)**

- Use `git revert -n eb247784 2f3649f9 c0b09a06` (preserves history) — NOT force-push.
- Add `LifecycleError("local-storage-readonly-filesystem")` to Oneiric's `LocalStorageAdapter.init()` (file: `oneiric/oneiric/adapters/storage/local.py`). Tracked as a sub-task.
- Unify the 5 default values for `MAHAVISHNU_AUTO_WORKTREE_ROOT` to `get_data_path("worktrees")` across all 5 files.
- Add `StorageSettings` to `MahavishnuSettings`.

**Phase 1: Provider subclasses (2-3 days)**

- Add `LocalWorktreeProvider` to `mahavishnu/core/worktree_providers/local.py` (extends existing `WorktreeProvider`).
- Add `S3WorktreeProvider` to `mahavishnu/core/worktree_providers/s3.py`.
- Update `WorktreeCoordinator` to use the new providers via the registry (already wired).
- Update `.claude/hooks/worktree-session-isolation.py` to read from `StorageSettings.worktree_base_path`.
- Add concrete types: `WorktreeHandle`, `WorktreeRef`, `LocalWorktreeRef`, `S3WorktreeRef`, `WorktreeIntegrityError`, `WorktreeLocked`.

**Phase 2: Cache + observability (2-3 days, parallel with Phase 1)**

- Use Oneiric's `MultiTierCacheAdapter` directly (no new Protocol).
- Configure Redis: `maxmemory 2gb`, `maxmemory-policy allkeys-lfu`, `appendonly no`.
- Add per-cache-type classification (regenerable hot → Redis L1+L2, regenerable warm/cold → Oneiric Local, persistent → Dhara).
- Export the SLO + observability metrics above.
- Add `lock()` method using Oneiric's existing distributed lock or Dhara advisory locks.

**Phase 3: 24 per-MCP `.venv/` deduplication (1 day, parallel)**

- Use `UV_PROJECT_ENVIRONMENT` env var (already documented in CLAUDE.md).
- Replace per-repo `.venv/` symlinks with a registry file at `~/.local/share/mahavishnu/venvs/registry.json` mapping `<repo> → <shared-venv-path>` (no symlinks → no TOCTOU CVE surface).
- Atomic venv recreation: build at `new`, symlink swap on success, `.old` retained for 7 days as rollback.

**Phase 4: Migration of 83 misplaced worktrees (2-3 days)**

- Use the new `WorktreeProviderRegistry.get_available_provider()` (already implemented) — no new code path.
- For each misplaced worktree: read current handle, materialize via new provider, verify SHA-256, register in Dhara.
- Per-worktree safety check: skip if `git status` shows uncommitted changes; surface to operator for resolution.

**Phase 5: Documentation (1 day)**

- Update `CLAUDE.md`, `docs/CONFIGURATION.md`, runbooks.
- Bump `worktree_manage` MCP tool to 2.0.0 (breaking payload change).
- Add `DEPRECATED_TOOLS` entry for `worktree_manage` v1 behavior pointing at the new shape.
- Add MCP tools: `storage_backend_health`, `cache_invalidate_namespace`, `worktree_migrate` (optional).

**Total: 8-11 working days** (matches reviewer estimates; v1 said 4-5, which was unrealistic).

### 15. Rollback strategy per phase

| Phase | Rollback trigger | Procedure |
|---|---|---|
| Phase 0 | Approval blocked by maintainer | N/A — abort |
| Phase 1 | SLO breach > 2x baseline for 24h | `git revert <phase-1-sha>`, redeploy, flush Dhara worktree registry |
| Phase 2 | Redis or Dhara health check fails for 1h+ | Switch `cache_provider_selection=memory-only`, redeploy |
| Phase 3 | Venv regression in any repo | Restore symlink from `registry.json.backup`, redeploy |
| Phase 4 | Worktree migration corrupts state | Per-worktree rollback via `git reflog` + `WorktreeProvider.remove(handle) + recreate` |

### 16. Runbooks

- `runbooks/storage-backend-failure.md` — Redis down, S3 throttled, Dhara unreachable (one section each)
- `runbooks/worktree-migration-failure.md` — per-phase rollback procedures
- `runbooks/shared-venv-corruption.md` — atomic venv recreation rollback
- `runbooks/bundle-integrity-failure.md` — SHA-256 mismatch response

## Consequences

### Positive

- **Distributable.** Defaults work in any deployment via Oneiric's capability-based resolver.
- **Serverless-safe.** `LocalStorageAdapter.init()` raises clear error on read-only filesystem.
- **Disk reclaim.** ~20-25 GB across the ecosystem migrates to backend-appropriate storage.
- **Observable.** SLOs + metrics + dashboards + runbooks are part of ratification, not a follow-up.
- **Multi-tenant from day one.** No retrofit risk.
- **No data loss.** Bundle integrity (SHA-256) verified at fetch time.
- **Smaller blast radius.** Extending existing abstractions means we don't introduce a parallel API surface.

### Negative

- **Migration effort.** Realistic 8-11 days of focused work (matches reviewer estimates).
- **New failure modes.** All are observable; each has a runbook.
- **Cold start latency.** Serverless: bundle download + clone = 200-500ms p99 (must measure in Phase 1).
- **Breaking change.** `worktree_manage` MCP tool v2.0.0; consumers on v1 need to migrate.

### Neutral

- v1 is now superseded. The 3 stale commits on `origin/main` are reverted via `git revert` (Phase 0), not force-push.
- The `WorktreeProvider` hierarchy is extended, not replaced. Existing providers (`direct_git`, `session_buddy`, `mock`) continue to work.
- Oneiric gains one new cache adapter (`DharaCacheAdapter`, the durable-state complement to Redis/Memory).

## Open Questions

Fewer than v1 — most resolved during the multi-agent review.

1. **Local backend defaults:** `WorktreeProvider.create_worktree` for the local backend uses `git worktree add` directly. Bundle is optional via `BundleTransport` decorator. Confirm this is the right call (vs always-bundle for portability). Affects Phase 1 design.
2. **Phase 0 Oneiric enhancement:** Adding `LifecycleError("local-storage-readonly-filesystem")` to `LocalStorageAdapter.init()` is a oneiric-side change. Confirm the Oneiric maintainer will accept this enhancement as part of this ADR, or split it into a separate Oneiric PR. Affects Phase 0 sequencing.
3. **Per-cache TTL defaults:** The 3600s default for the new `StorageSettings.cache_ttl_seconds` is a guess. Real values depend on workload. Set after Phase 2 instrumentation.
4. **Bundle transport for local:** Should `LocalWorktreeProvider` produce a bundle by default (for portability), or only on explicit request (`BundleTransport.create_bundle(handle)`)? The cost is double-disk (bundle + checkout); the benefit is "any local worktree can be promoted to S3 in one call." Affects Phase 1 design.
5. **`MAHAVISHNU_AUTO_WORKTREE_ROOT` deprecation timeline:** Keep as alias for 1 release (per reviewer suggestion), or remove immediately? Affects Phase 0 timing.

## Related Decisions

- **ADR-001: Use Oneiric for Configuration and Logging** — v2 extends Oneiric's resolver instead of bypassing it. Consistent.
- **ADR-006: Simplify Storage Architecture** — v2 honors the 2-system storage story (PostgreSQL via Dhara for app data) and adds storage adapters for state-adjacent data (worktrees, caches). No conflict; additive.
- **ADR-013: Adapter Tool Boundary Between Mahavishnu and Dhara** — v2 keeps durable state in Dhara; cache backends route through Oneiric, not Dhara. Boundary preserved.
- **015-multi-agent-review** — the 9-agent review that drove these revisions.

## References

- Oneiric storage adapters: `oneiric/oneiric/adapters/storage/{local,s3,gcs,azure}.py`
- Oneiric cache adapters: `oneiric/oneiric/adapters/cache/{redis,memory,multitier}.py`
- Oneiric resolver: `oneiric/oneiric/core/resolution.py`
- Mahavishnu `paths.py`: `mahavishnu/mahavishnu/core/paths.py`
- Mahavishnu `config.py`: `mahavishnu/mahavishnu/core/config.py` (`MahavishnuSettings` at line 1921)
- Existing `WorktreeProvider` hierarchy: `mahavishnu/mahavishnu/core/worktree_providers/`
- Existing `WorktreeCoordinator`: `mahavishnu/mahavishnu/core/worktree_coordination.py`
- Hook: `mahavishnu/.claude/hooks/worktree-session-isolation.py`
- Dhara cache substrate: `dhara/dhara/mcp/kv_timeseries.py`

---

**END OF ADR-015 v2**