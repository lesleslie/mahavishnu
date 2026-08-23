---
status: proposed
role: canonical
date: 2026-08-23
last_reviewed: 2026-08-23
supersedes: "015-worktree-and-cache-storage", "015-worktree-and-cache-storage-v2"
blocks_on: []
decision_date: null
topic: storage-abstraction
related:
  - "015-multi-agent-review"
  - "015-worktree-and-cache-storage"
  - "015-worktree-and-cache-storage-v2"
  - "006-simplify-storage-architecture"
  - "013-mahavishnu-dhara-adapter-tool-boundary"
  - "001-use-oneiric"
---

# ADR 015: Worktree and Cache Storage Architecture (Revised v3)

## Status

**Proposed v3** — supersedes v1 (`015-worktree-and-cache-storage`) and v2 (`015-worktree-and-cache-storage-v2`). v3 incorporates the round-2 multi-agent review (6 new lenses, ~20 new BLOCKERs). v1 was rejected by the round-1 review; v2 resolved round-1's BLOCKERs but introduced new issues that round 2 caught. v3 addresses both rounds' findings.

**Date:** 2026-08-23

## What changed from v2

| Change | v2 → v3 | Source |
|---|---|---|
| **WorktreeProvider sketch** | v2's `Protocol` sketch → concrete classes inheriting existing `WorktreeProvider(ABC)` at `mahavishnu/core/worktree_providers/base.py:8` | code-architect (B-code-1) |
| **`StorageSettings` location** | Stays nested in `MahavishnuSettings` → moved to `oneiric.config` with re-export shim | platform-engineer (B-platform-2) |
| **`WorktreeRef` type** | `@runtime_checkable Protocol` with `backend_kind: str` → `ABC` with abstract `backend_kind` property | platform-engineer (B-platform-3) |
| **Pre-v2 migration story** | Missing → explicit pre-migration step: `git worktree list --porcelain` + handle synthesis for 210 existing worktrees | code-architect (B-code-2) |
| **Bundle integrity for pre-v2 worktrees** | Unspecified → explicit fallback: lazy-compute SHA-256 on first `fetch()`, fail-closed on bundle creation | code-architect (B-code-3) |
| **`DharaCacheAdapter` mention** | Preserved in Consequences line 460 → removed; ADR-013 boundary holds | historical (B-historical-1) |
| **`MAHAVISHNU_AUTO_WORKTREE_CLEANUP` policy** | Dropped → default `mark` preserved; per-principal and per-worktree override added | fastblocks (B-fastblocks-3) |
| **Cache key namespacing** | Missing → `redis_key_prefix: str = "mahavishnu:"` in `StorageSettings`; Oneiric adapter constructor accepts prefix | code-architect (B-code-4) |
| **S3 credentials resolution** | Hand-waved → explicit chain: env vars → IMDS → IRSA → OIDC → IAM role | devops (B-devops-2) |
| **Cache invalidation on worktree removal** | Unstated → cache entries tagged with `worktree_handle_id`; remove via Oneiric's `MultiTierCacheAdapter.delete(prefix)` | database (I-3) |
| **Phase 4 advisory lock** | Missing → per-`(main_repo, branch)` advisory lock during migration; SessionStart hook checks lock before creating new worktree at old path | code-architect (I-code-architect-5) |
| **Phase 4 `.git` file parsing** | Missing → migration script reads each worktree's `.git` pointer to discover main repo | code-architect (I-1) |
| **`lock()` semantics** | Skeleton → lease TTL 30s, fencing token via monotonic counter, Redis SETNX with EX | database (B-database-3) |
| **Deprecation window for `worktree_manage` v2.0.0** | Unspecified → v1 callable for 2 minor releases (0.15, 0.16); hard-remove in 0.17; translation shim included | platform + fastblocks |
| **`worktree_manage` discovery** | Standard → `discover_tools()` returns `deprecated: true` + `sunset_version` for v1 | platform + mcp |
| **Worktree registry schema** | Value-only → key naming + secondary indexes + retention policy | database (B-database-1) |
| **DR story for Dhara worktree state** | Missing → RPO/RTO per backend + S3 reconstruction path + nightly consistency check | database (B-database-2) |
| **`BundleTransport` decorator** | Stays in v2 → removed from v3; defer to follow-up ADR after `WorktreeProvider` extension lands | historical (B-historical-2) |
| **`git bundle` chunking for large repos** | Unspecified → `S3WorktreeProvider` restricted to repos under 50k commits; larger repos use shallow clone | code-architect (I-2) |
| **Redis sizing** | Asserted 2GB → "measure in Phase 2; size based on measured working-set × 1.5" | database (I-5) |
| **StorageSettings nested per adapter** | Flat fields (`s3_bucket`, `s3_region`, `redis_url`) → nested per Oneiric pattern (`s3: S3StorageSettings | None = None`) | platform (I-2) |
| **8-11 day estimate** | Stays → re-confirmed by round-2 reviewers as realistic-but-tight | historical (I-2) |
| **Phase 0 force-push / revert** | Uses `git revert` (v2) → unchanged | — |
| **Process improvement** | None → codified in CLAUDE.md: ADRs require ≥2 rounds of multi-agent review | reflection from rounds 1+2 |

## Context

A 2026-08-23 ecosystem audit surfaced three related problems:

**Worktrees** — 210 total, 83 misplaced. The misplacement stems from three bugs:
1. `MAHAVISHNU_AUTO_WORKTREE_ROOT` defaults to `~/worktrees` (literal hardcoded string), but actual code path produces `~/worktrees/agent-<hex8>/` (wrong sub-shape).
2. Auto-worktree tool computes `parent/<repo>.worktrees/<branch>/` (sibling of repo).
3. Result: 65 mahavishnu `agent-*` worktrees in `~/worktrees/`, 16 fastblocks siblings at `~/Projects/{fb-*,fastblocks-task*}`, 1 neo4j sibling at `~/Projects/neo4j-mcp.worktrees/`, 1 fastblocks `phase-5-v4` at `~/.claude/worktrees/`.

**Caches** — 22+ GB scattered across the filesystem. 24 per-MCP `.venv/` (~18 GB), 29 per-repo `.crackerjack/` (3 GB), per-repo tooling caches (~3.4 GB), stray `~/.cache/*` dirs.

**Deployment model** — serverless deploys make the package directory read-only and `/tmp` ephemeral. Whatever default path mahavishnu writes to **must** work for serverless. Three commits on `origin/main` (`eb247784`, `2f3649f9`, `c0b09a06`) hardcoded `~/Projects/worktrees` and are known wrong pending this ADR.

### What already exists (don't rebuild)

- **`mahavishnu/core/worktree_providers/base.py:8`** — `WorktreeProvider` ABC with `create_worktree(repository_path, branch, worktree_path, create_branch) -> dict[str, Any]`, `remove_worktree`, `list_worktrees`, `health_check`. Three concrete providers: `direct_git.py`, `session_buddy.py`, `mock.py`.
- **`mahavishnu/core/worktree_providers/registry.py:42`** — `WorktreeProviderRegistry.get_available_provider()` with fallback chain.
- **`mahavishnu/core/worktree_coordination.py:47`** — `WorktreeCoordinator` is the production call path (CLI + MCP both call `app.worktree_coordinator`).
- **`oneiric/oneiric/adapters/storage/`** — `LocalStorageAdapter`, `S3StorageAdapter`, `GCSStorageAdapter`, `AzureBlobStorageAdapter`.
- **`oneiric/oneiric/adapters/cache/`** — `RedisCacheAdapter`, `MemoryCacheAdapter`, `MultiTierCacheAdapter` (L1+L2 with metrics).
- **`oneiric/oneiric/core/resolution.py:60`** — `ResolverSettings.selections` for capability-based backend selection.
- **`mahavishnu/mahavishnu/core/paths.py`** — XDG-correct path helpers via `platformdirs`.
- **`mahavishnu/mahavishnu/core/config.py`** — `MahavishnuSettings(BaseSettings)` with nested `BaseModel` sections.
- **Dhara** (`dhara/dhara/mcp/kv_timeseries.py:60`) — `AsyncKVTimeSeriesStore`; ADR-013 routes durable state through it.
- **Redis** — local instance available.

## Decision

### 1. Storage: use Oneiric's existing storage adapters directly

The four Oneiric storage adapters provide what we need. **Do not introduce a new `WorktreeStorage` Protocol.** Instead, add a new `LocalWorktreeProvider` to `mahavishnu/core/worktree_providers/local.py` that wraps the existing pattern. The new provider extends the **existing `WorktreeProvider` ABC** (not a new `Protocol`), reusing the signatures already used by `direct_git.py`, `session_buddy.py`, and `mock.py`.

The 5-default drift in `MAHAVISHNU_AUTO_WORKTREE_ROOT` is fixed by funneling all reads through `get_worktree_base_path()` in `paths.py` (rather than five independent env-var reads). Phase 0 includes a CI guard test pinning "every reference to worktree base path must resolve through `paths.py::get_worktree_base_path()`."

The existing `direct_git.py` is renamed to `local.py` and the new `LocalWorktreeProvider` (with `LocalStorageAdapter` integration) takes its place. `DirectGitProvider` becomes a 1-release deprecated alias. The v3 path replaces the v1 path with a single compatible shim, not a parallel abstraction.

### 2. `StorageSettings` lives in Oneiric, not in `MahavishnuSettings`

The platform-engineer reviewer flagged that nesting `StorageSettings` in `MahavishnuSettings` makes the storage config mahavishnu-specific by construction — a new Bodai component would have to depend on `mahavishnu.core.config` to get storage settings. v3 relocates:

```python
# In oneiric/oneiric/config.py (new module)
from oneiric.adapters.storage.local import LocalStorageSettings
from oneiric.adapters.storage.s3 import S3StorageSettings
from oneiric.adapters.cache.redis import RedisCacheSettings
# ... other adapter settings

class StorageSettings(BaseModel):
    """Storage backend selection (Bodai ecosystem standard)."""

    worktree_provider_selection: str = "default"
    cache_provider_selection: str = "default"
    worktree_base_path: Path | None = None
    cache_ttl_seconds: int = Field(default=3600, gt=0)
    bundle_integrity_required: bool = True
    cleanup_policy_default: Literal["mark", "keep", "remove"] = "mark"

    # Per-adapter nested settings (Oneiric pattern, not flat)
    s3: S3StorageSettings | None = None
    gcs: GCSStorageSettings | None = None
    azure: AzureBlobStorageSettings | None = None
    redis: RedisCacheSettings | None = None
    redis_key_prefix: str = "mahavishnu:"
    local: LocalStorageSettings | None = None
    dhara: DharaDurableSettings | None = None

# In mahavishnu/mahavishnu/core/config.py (re-export for backward compat)
from oneiric.config import StorageSettings  # re-export
```

`MahavishnuSettings` either (a) composes the relocated `StorageSettings` (no longer nested), or (b) becomes a thin profile that subclasses the Oneiric settings and adds only mahavishnu-specific keys. (b) is preferred.

### 3. Cache: use Oneiric's `MultiTierCacheAdapter` directly

Oneiric's `MultiTierCacheAdapter` (L1+L2 with metrics) does what the cache tier needs. v3 uses it directly. **No new `CacheBackend` Protocol.** Naming collision with `mahavishnu/core/cache_manager.py:41-46` `CacheBackend` StrEnum is avoided.

**Cache key namespacing** is mandatory in shared Redis. v3 specifies `StorageSettings.redis_key_prefix: str = "mahavishnu:"` (default). Oneiric's `RedisCacheAdapter` constructor accepts a `key_prefix` argument; the value is applied to all `get`/`set`/`delete`/`scan` operations.

**Cache invalidation on worktree removal** uses Oneiric's existing `MultiTierCacheAdapter.delete(prefix)`. Each cache entry written by `LocalWorktreeProvider` is tagged with `worktree_handle_id` in the key: `mahavishnu:worktree-cache:<handle_id>:<suffix>`. On `WorktreeProvider.remove(handle)`, the adapter calls `delete(prefix="mahavishnu:worktree-cache:<handle_id>:")` to clear dependent entries.

**Per-cache-class registration** uses Oneiric's `ResolverSettings.selections`. Per-cache backend choice is operator-tunable at deployment time.

### 4. Backend selection: Oneiric's `ResolverSettings.selections`

The capability-based resolver (already implemented in Oneiric) handles selection. CLI/agent code calls `resolver.resolve("worktree-provider", "default")` instead of branching on an env var. This preserves Oneiric's `DecisionEvent` audit trail.

### 5. Multi-tenancy from day one

Every operation takes a `principal: Principal` parameter. The Local backend refuses to cross user boundaries (`os.getuid()` check on long-running hosts). The S3 backend uses principal-prefixed keys (`s3://<bucket>/worktrees/<principal>/<repo>/<branch>/`). The `Principal` type is the same one already used by `mahavishnu/mcp/auth.py` for the existing MCP auth boundary.

**Existing-worktree migration:** The 65 mahavishnu `agent-*` worktrees and 16 fastblocks siblings were created without a `principal` recorded. Phase 4 includes an explicit pre-migration step (see §12) that synthesizes handles with `principal = Principal.from_uid(os.getuid())` for local-host worktrees and `principal = Principal.anonymous()` for serverless-style worktrees (where uid derivation is meaningless). The synthesized handle is registered in Dhara with `provenance: "pre-v2-migration"` metadata.

### 6. Bundle integrity (SHA-256 + optional signature)

Every bundle is hashed at creation time; the SHA-256 is stored in S3 object metadata (`x-amz-meta-sha256`). At fetch time, the hash is verified before extraction. Mismatch → `WorktreeIntegrityError` + audit log entry.

**Pre-v2 worktree fetch behavior:** For worktrees created before v3 (no SHA-256 recorded), the first `fetch()` triggers a lazy `git bundle create` + `sha256sum` to compute the hash. The bundle is written to S3 (canonical storage) and the hash is cached in the synthesized `WorktreeHandle`. Subsequent fetches use the cached hash. **`git bundle create` failure during lazy hash computation fails closed** (no worktree materialization) to prevent data loss.

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

The `os.access(W_OK)` check belongs in Oneiric's `LocalStorageAdapter.init()`, not in every mahavishnu backend. The local worktree provider propagates the `LifecycleError("local-storage-readonly-filesystem")` from Oneiric. This requires a small enhancement to Oneiric; tracked as a prerequisite (Phase 0 sub-task: file a Oneiric PR for the `LifecycleError` enhancement).

**Lambda-specific behavior:** On Lambda, `Path.home()` may resolve to a writable area (`/tmp` for many runtimes) or to a read-only package dir depending on the base image. v3 documents explicitly that `MAHAVISHNU_CACHE_BASE_PATH` and `MAHAVISHNU_WORKTREE_BASE_PATH` MUST be set explicitly in Lambda deployments:

```bash
# Lambda deployment
MAHAVISHNU_CACHE_BASE_PATH=/tmp/mahavishnu
MAHAVISHNU_WORKTREE_BASE_PATH=/tmp/mahavishnu/worktrees
# OR
MAHAVISHNU_WORKTREE_PROVIDER_SELECTION=s3-primary
```

### 8. Update `.claude/hooks/worktree-session-isolation.py`

The hook reads `MAHAVISHNU_AUTO_WORKTREE_ROOT` (line 53) and validates worktree paths fall under it. v3 unifies all reads through `paths.py::get_worktree_base_path()` (no direct env-var reads). `MAHAVISHNU_AUTO_WORKTREE_ROOT` is kept as a 1-release alias for `MAHAVISHNU_WORKTREE_BASE_PATH`, then deprecated.

### 9. Path resolution uses `paths.py`

New code calls `get_worktree_base_path()` (new helper in `paths.py`) for the worktree root and `get_data_path("worktrees", repo, branch)` for per-worktree subdirs. No hand-rolled `Path.home() / ".local" / ...` paths.

### 10. `MAHAVISHNU_AUTO_WORKTREE_CLEANUP` policy: default `mark`, explicit override

The existing hook default `policy="mark"` is preserved. v3 specifies the policy semantics:

| Policy | Behavior |
|---|---|
| `mark` (default) | Mark worktree as abandoned in registry; never auto-remove |
| `keep` | Same as `mark` but also leave a record of uncommitted work |
| `remove` | Auto-remove worktree on SessionEnd (loses uncommitted work; not default) |

The policy is set globally via `StorageSettings.cleanup_policy_default`. Per-worktree override: a `cleanup_policy: Literal["mark", "keep", "remove"] | None` field on `WorktreeHandle` (set at creation time). Per-principal override: `Principal.cleanup_policy_override`.

### 11. Worktree registry schema (Dhara)

```text
mahavishnu:worktree-registry:&lt;handle_id&gt;            -&gt; JSON(WorktreeHandle)  [no TTL]
mahavishnu:worktree-registry:idx:principal:&lt;p&gt;      -&gt; SET&lt;handle_id&gt;        [no TTL]
mahavishnu:worktree-registry:idx:repo:&lt;r&gt;           -&gt; SET&lt;handle_id&gt;        [no TTL]
mahavishnu:worktree-registry:lock:&lt;p&gt;:&lt;r&gt;:&lt;b&gt;       -&gt; lease_token           [TTL = lease_ttl]
mahavishnu:audit-log:&lt;YYYY-MM-DD&gt;:&lt;handle_id&gt;:&lt;seq&gt; -&gt; JSON(AuditEvent)      [no TTL; archived quarterly]
mahavishnu:audit-log-idx:handle:&lt;handle_id&gt;         -&gt; SET&lt;event_id&gt;         [no TTL]
mahavishnu:audit-log-idx:date:&lt;YYYY-MM-DD&gt;           -&gt; SET&lt;event_id&gt;         [no TTL]
mahavishnu:worktree-cache:&lt;handle_id&gt;:&lt;suffix&gt;     -&gt; bytes                  [TTL = cache_ttl_seconds]
```

`SET NX` enforces uniqueness on secondary indexes; create transaction rolls back on collision. Audit log is append-only with quarterly archive to S3 Glacier (`s3://bucket/audit-archive/YYYY-Q*/`).

### 12. Pre-v2 migration story (Phase 4 prerequisite)

For the 210 pre-existing worktrees (none have a `WorktreeHandle` record), Phase 4 includes an explicit pre-migration step:

```python
# Phase 4 pre-migration (run before any worktree moves)
async def pre_migration_discover(main_repo: Path) -&gt; list[WorktreeHandle]:
    """Discover all worktrees for main_repo and synthesize WorktreeHandles."""
    raw_worktrees = await asyncio.create_subprocess_exec(
        "git", "-C", str(main_repo), "worktree", "list", "--porcelain",
        stdout=asyncio.subprocess.PIPE,
    )
    stdout, _ = await raw_worktrees.communicate()
    handles = []
    for entry in parse_porcelain(stdout.decode()):
        # entry has: worktree, HEAD, branch (optional), gitdir
        # worktree.path = entry["worktree"]
        # The .git file inside entry["worktree"] contains "gitdir: /abs/path"
        # which gives the main repo path. For most worktrees, this is
        # the main_repo we're querying; for misplaced worktrees, this
        # can also be derived from entry["gitdir"].
        principal = Principal.from_uid(os.getuid())
        handle = WorktreeHandle(
            handle_id=synthesize_uuid(),
            principal=principal,
            repo=infer_repo(entry["worktree"]),
            branch=entry.get("branch", "detached-HEAD").removeprefix("refs/heads/"),
            base_ref=entry.get("HEAD"),
            created_at=entry.get("created_at", datetime.now(UTC)),
            storage_ref=LocalWorktreeRef(path=Path(entry["worktree"]), ...),
            sha256="",  # computed lazily on first fetch
            bytes_size=0,  # computed lazily
        )
        handles.append(handle)
    return handles
```

After discovery, each handle is registered in Dhara with `provenance: "pre-v2-migration"`.

### 13. Concrete type definitions

```python
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import TracebackType
from typing import IO, Literal, Protocol, Self, runtime_checkable

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
    sha256: str  # empty for pre-v2 worktrees; lazily computed
    bytes_size: int  # 0 for pre-v2; lazily computed
    cleanup_policy: Literal["mark", "keep", "remove"] | None = None
    provenance: str = "v3"  # or "pre-v2-migration"


class WorktreeRef(ABC):
    """Backend-typed reference. Subclasses MUST override backend_kind."""

    @property
    @abstractmethod
    def backend_kind(self) -&gt; str: ...


@dataclass(frozen=True, slots=True)
class LocalWorktreeRef(WorktreeRef):
    path: Path
    worktree_id: str

    @property
    def backend_kind(self) -&gt; str:
        return "local"


@dataclass(frozen=True, slots=True)
class S3WorktreeRef(WorktreeRef):
    bucket: str
    key: str

    @property
    def backend_kind(self) -&gt; str:
        return "s3"


@dataclass(frozen=True, slots=True)
class BundleRef:
    bundle_key: str
    sha256: str
    signature: str | None
    created_at: datetime
    bytes_size: int


@dataclass(frozen=True, slots=True)
class WorktreeLock:
    acquire_at: datetime
    expires_at: datetime
    owner_principal: Principal
    fencing_token: int


class WorktreeLocked(Exception):
    pass


class WorktreeIntegrityError(Exception):
    pass


class WorktreeProvider(Protocol):
    """Extends the existing mahavishnu/core/worktree_providers/base.py ABC.

    Note: this is a Protocol for documentation. The real implementation
    extends the existing ABC, not this Protocol.
    """

    async def __aenter__(self) -&gt; Self: ...
    async def __aexit__(self, *exc_info: object) -&gt; None: ...
    async def health(self) -&gt; bool: ...
    async def create_worktree(self, repo: str, branch: str, base_ref: str, principal: Principal) -&gt; WorktreeHandle: ...
    async def fetch(self, handle: WorktreeHandle) -&gt; WorktreeRef: ...
    async def list(self, principal: Principal, repo: str | None = None) -&gt; list[WorktreeHandle]: ...
    async def exists(self, handle: WorktreeHandle) -&gt; bool: ...
    async def remove(self, handle: WorktreeHandle) -&gt; None: ...
    def lock(self, repo: str, branch: str, *, acquire_timeout: float = 10.0, lease_ttl: float = 30.0) -&gt; WorktreeLock: ...
```

### 14. `lock()` semantics: Redis SETNX with fencing token

```python
def lock(self, repo, branch, *, acquire_timeout=10.0, lease_ttl=30.0) -&gt; WorktreeLock:
    """Distributed lock via Redis SETNX with EX + fencing token.

    Returns a WorktreeLock with the fencing_token. Pass the fencing_token
    to all subsequent writes; writes reject tokens older than the
    highest-seen token. Lock auto-releases after lease_ttl seconds.
    """
    # Acquire via SET key token NX EX lease_ttl
    # If NX fails (someone else holds), wait acquire_timeout for release
    # Increment fencing token via INCR on per-(repo, branch) counter
    # Return WorktreeLock
```

- Lease TTL: 30s default (configurable)
- Acquire timeout: 10s default (caller-configurable)
- Fencing token: monotonic counter (Redis `INCR` on `mahavishnu:worktree-fence:<repo>:<branch>`)
- WorktreeLocked raised on acquire failure or lease expiry

### 15. S3 / GCS credentials (delegated to Oneiric)

S3 and GCS credentials are managed by Oneiric's `S3StorageSettings` (`oneiric/oneiric/adapters/storage/s3.py`) and `GCSStorageSettings` (`oneiric/oneiric/adapters/storage/gcs.py`) and resolved by the underlying cloud SDKs under the hood. mahavishnu's `StorageSettings` exposes these as nested `s3: S3StorageSettings | None` and `gcs: GCSStorageSettings | None` fields; **no custom credential chain needed in mahavishnu.**

**S3 credential resolution (delegated to aioboto3):**

- **EXPLICIT credentials** (from `S3StorageSettings`):
  - `access_key_id` + `secret_access_key` (settings or env vars)
  - `profile_name` (AWS profile)
  - `session_token` (for STS)
- **IMPLICIT credentials** (resolved by aioboto3's default provider chain when no explicit credentials are set):
  1. Environment variables (`AWS_ACCESS_KEY_ID`, etc.)
  2. AWS Web Identity / IRSA — `AWS_WEB_IDENTITY_TOKEN_FILE` + `AWS_ROLE_ARN`
  3. EC2/ECS task role via IMDSv2
  4. Lambda execution role (automatic in Lambda runtime)

**GCS credential resolution (delegated to google-cloud-storage):**

- Service account JSON path via `GCSStorageSettings.credentials_path`
- Application Default Credentials (ADC) otherwise: `GOOGLE_APPLICATION_CREDENTIALS` env var → metadata server → etc.

**Redis credentials:** `StorageSettings.redis_url: str` (with `rediss://` TLS by default). On connection failure, log + decrement health-check counter.

### 15.1. GCS mock for tests and localhost

A GCS mock (homebrew package) is available for testing and localhost development. Configure `GCSStorageSettings.endpoint_url` to point at the mock's local endpoint:

```python
# settings/local.yaml
storage:
  gcs:
    bucket: "test-bucket"
    project: "test-project"
    endpoint_url: "http://localhost:4443"  # GCS mock local endpoint
    credentials_path: null  # mock accepts unauthenticated requests
```

This avoids hitting real GCS during tests and enables fully-local development without cloud credentials. **Recommended for CI:** include the mock install in test runners and use it as the default GCS endpoint in `settings/test.yaml`.

### 16. SLOs (concrete)

| Backend | Operation | p50 | p95 | p99 | Availability |
|---|---|---|---|---|---|
| Local | create_worktree | <50ms | <200ms | <500ms | 99.9% |
| Local | fetch | <20ms | <100ms | <300ms | 99.9% |
| S3 | create_worktree | <500ms | <2s | <5s | 99.5% (depends on AWS S3 SLA) |
| S3 | fetch (bundle <50MB) | <300ms | <1.5s | <4s | 99.5% |
| Redis (L1 miss → L2) | cache.get | <5ms | <20ms | <50ms | 99.9% |
| Dhara | state.set | <20ms | <100ms | <300ms | 99.5% |

Error budget: 99.9% success over 30 days. Multi-window burn-rate alerts per Google SRE workbook.

**S3 bundle size constraint:** `S3WorktreeProvider` is restricted to repos under 50k commits OR repos where the bundle is <100MB. Larger repos use shallow clone (one-time setup) for serverless deployments. The 200-500ms p99 SLO applies only to small bundles.

### 17. Observability metrics

```
worktree_create_duration_seconds{backend,status,principal}
worktree_fetch_duration_seconds{backend,status,principal}
worktree_lock_wait_seconds{repo,branch,acquired}
worktree_lock_held_seconds{repo,branch,principal}
worktree_cache_invalidation_total{backend,reason}
cache_get_duration_seconds{backend,hit}
cache_set_duration_seconds{backend}
cache_fallback_total{from,to}
backend_health_check_failed_total{backend}
bundle_bytes{repo}
bundle_integrity_failure_total{backend,principal}
worktree_registry_drift_total{missing_in_s3,missing_in_dhara}
```

### 18. Migration plan (revised, realistic estimates)

**Phase 0: Revert + bootstrap (1-2 days)**

- Use `git revert -n eb247784 2f3649f9 c0b09a06` (preserves history)
- Add `LifecycleError("local-storage-readonly-filesystem")` to Oneiric's `LocalStorageAdapter.init()` (cross-repo PR)
- Unify the 5 default values for `MAHAVISHNU_AUTO_WORKTREE_ROOT` to `get_worktree_base_path()` across all 5 files
- Add CI guard test pinning "every reference to worktree base path must resolve through `paths.py::get_worktree_base_path()`"
- Rename `direct_git.py` → `local.py`; add `DirectGitProvider` as 1-release alias

**Phase 1: Provider subclasses + pre-v2 migration (2-3 days)**

- Add `LocalWorktreeProvider` extending the existing `WorktreeProvider` ABC
- Add `S3WorktreeProvider` extending the existing `WorktreeProvider` ABC
- Add concrete types: `WorktreeHandle` (dataclass), `WorktreeRef` (ABC), `LocalWorktreeRef`, `S3WorktreeRef`, `BundleRef`, `WorktreeIntegrityError`, `WorktreeLocked`, `WorktreeLock`
- Run `pre_migration_discover()` for all 210 existing worktrees; register synthesized handles in Dhara with `provenance: "pre-v2-migration"`
- Update `WorktreeCoordinator` to dispatch via the new providers
- Update `.claude/hooks/worktree-session-isolation.py` to read from `paths.py::get_worktree_base_path()`
- Implement `lock()` with Redis SETNX + fencing token

**Phase 2: Cache + observability (2-3 days, parallel with Phase 1)**

- Use Oneiric's `MultiTierCacheAdapter` directly (no new Protocol)
- Configure Redis: `maxmemory` sized after Phase 2 measurement, `allkeys-lfu`, `appendonly no`
- Wire cache invalidation: `WorktreeProvider.remove()` → `cache.delete(prefix="mahavishnu:worktree-cache:<handle_id>:")`
- Add per-cache-class registration via `ResolverSettings.selections`
- Export the SLO + observability metrics above

**Phase 3: 24 per-MCP `.venv/` deduplication (1 day, parallel)**

- Use `UV_PROJECT_ENVIRONMENT` env var
- Replace per-repo `.venv/` symlinks with a registry file at `~/.local/share/mahavishnu/venvs/registry.json` (no symlinks → no TOCTOU CVE surface)
- Atomic venv recreation: build at `new`, registry entry rewrite on success, `.old` retained for 7 days as rollback

**Phase 4: Migration of 210 worktrees (2-3 days)**

- For each of the 83 misplaced worktrees: read current handle (synthesized in Phase 1), invoke `git worktree move` (or `WorktreeProvider.materialize` for active S3 backend), verify SHA-256 lazily, register in Dhara
- Per-worktree safety check: skip if `git status` shows uncommitted changes; surface to operator for resolution
- Advisory lock per `(main_repo, branch)` during migration; SessionStart hook checks lock before creating new worktree at old path
- Concurrent-move safety: atomic `git worktree move` + Dhara register (transactional best-effort)

**Phase 5: Documentation + deprecation (1 day)**

- Update `CLAUDE.md`, `docs/CONFIGURATION.md`, runbooks
- Bump `worktree_manage` MCP tool to 2.0.0 (breaking payload change)
- Add `DEPRECATED_TOOLS` entry for `worktree_manage` v1 behavior; v1 callable for 2 minor releases
- Add translation shim for v1 payloads
- Update `discover_tools()` to return `deprecated: true` + `sunset_version` for v1 tools
- Update `MAHAVISHNU_AUTO_WORKTREE_ROOT` → `MAHAVISHNU_WORKTREE_BASE_PATH` (1-release alias)

**Total: 8-12 working days** (realistic per all reviewers; v1 said 4-5, v2 said 8-11, v3 is similar with a few extra items).

### 19. Rollback strategy per phase

| Phase | Rollback trigger | Procedure |
|---|---|---|
| Phase 0 | Approval blocked by maintainer | N/A — abort |
| Phase 1 | SLO breach > 2x baseline for 24h | `git revert <phase-1-sha>`, redeploy, flush Dhara worktree registry |
| Phase 2 | Redis or Dhara health check fails for 1h+ | Switch `cache_provider_selection=memory-only`, redeploy |
| Phase 3 | Venv regression in any repo | Restore from `registry.json.backup`, redeploy |
| Phase 4 | Worktree migration corrupts state | Per-worktree rollback via `git reflog` + `WorktreeProvider.remove(handle) + recreate` |
| Phase 5 | Doc-only, low risk | N/A |

**DR story per backend:**

| Backend | RPO | RTO | Recovery |
|---|---|---|---|
| Local worktree (filesystem) | 0 (single host) | manual recreation | operator intervention |
| S3 | 0 (S3 11 9s durable) | DNS/IAM replay | automatic |
| Dhara | depends on substrate | depends on substrate | reconstruction from S3 inventory |
| Redis | acceptable loss on restart | warm from cold | L1 cache hits degraded |

**Reconstruction path for Dhara loss:**
1. List `s3://bucket/worktrees/` keys
2. For each key, derive `(principal, repo, branch)` from path
3. Read `x-amz-meta-sha256` and other metadata
4. Rebuild `WorktreeHandle` records in Dhara from S3 inventory
5. Mark reconstruction with `reconstructed_at` field; require operator confirmation before writes resume

**S3 ↔ Dhara consistency check** (nightly cron):
- Enumerate S3 keys, enumerate Dhara handles, diff
- Alert on orphans (S3 has, Dhara doesn't) and ghosts (Dhara has, S3 doesn't)
- Ghosts are more dangerous — flag for manual review, never auto-delete

### 20. Runbooks (with owners)

| Runbook | Owner | Page-when |
|---|---|---|
| `runbooks/storage-backend-failure.md` | Mahavishnu core team | S3/Dhara/Redis health-check failure |
| `runbooks/worktree-migration-failure.md` | Migration team | Phase 4 corruption |
| `runbooks/shared-venv-corruption.md` | MCP infrastructure | Per-MCP venv breakage |
| `runbooks/bundle-integrity-failure.md` | Mahavishnu core team | SHA-256 mismatch alert |
| `runbooks/redis-down.md` | SRE | Redis connection failure |
| `runbooks/s3-throttled.md` | SRE | S3 503 SlowDown alert |
| `runbooks/dhara-unreachable.md` | SRE | Dhara health check failure |
| `runbooks/lambda-cold-start-slow.md` | DevOps | p99 cold start > 500ms |

## Consequences

### Positive

- **Distributable.** Defaults work in any deployment via Oneiric's capability-based resolver.
- **Serverless-safe.** `LocalStorageAdapter.init()` raises clear error on read-only filesystem; S3 backend is one env-var away.
- **Disk reclaim.** ~20-25 GB across the ecosystem migrates to backend-appropriate storage.
- **Observable.** SLOs + metrics + dashboards + runbooks are part of ratification, not a follow-up.
- **Multi-tenant from day one.** Pre-v2 worktrees are migrated to the new principal model.
- **No data loss.** Bundle integrity (SHA-256) verified at fetch time; pre-v2 worktrees compute lazily.
- **No parallel abstraction layers.** Extending the existing `WorktreeProvider` ABC, not creating a peer.
- **Cache invalidation tied to worktree lifecycle.** Removing a worktree clears its dependent cache entries.

### Negative

- **Migration effort.** Realistic 8-12 days of focused work.
- **New failure modes.** All are observable; each has a runbook with an owner.
- **Cold start latency.** Serverless: bundle download + clone = 200-500ms p99 for small bundles; large-repo tier uses shallow clone.
- **Breaking change.** `worktree_manage` MCP tool v2.0.0 with 2-minor-release deprecation window.
- **StorageSettings relocation touches mahavishnu, oneiric, and Dhara.** Cross-repo coordination required.

### Neutral

- v1 and v2 are now superseded. The 3 stale commits on `origin/main` are reverted via `git revert` (Phase 0), not force-push.
- The `WorktreeProvider` hierarchy is extended, not replaced. `direct_git.py` is renamed to `local.py` with a 1-release alias.
- Oneiric gains no new cache adapters (DharaCacheAdapter was an error in v2; ADR-013 boundary holds).
- `StorageSettings` lives in Oneiric for cross-component reuse.

## Open Questions

1. **Phase 0 Oneiric enhancement:** Adding `LifecycleError("local-storage-readonly-filesystem")` to `LocalStorageAdapter.init()` is a oneiric-side change. Confirm the Oneiric maintainer will accept this enhancement as part of this ADR, or split it into a separate Oneiric PR. Affects Phase 0 sequencing.
2. **Per-cache TTL defaults:** The 3600s default for `StorageSettings.cache_ttl_seconds` is a guess. Real values depend on workload. Set after Phase 2 instrumentation. The 5-default-drift CI guard test in Phase 0 should also pin per-cache TTL defaults to a known value (e.g., 0 for crackerjack so it always re-checks).
3. **Bundle transport for local:** Should `LocalWorktreeProvider` produce a bundle by default (for portability), or only on explicit request? The cost is double-disk (bundle + checkout); the benefit is "any local worktree can be promoted to S3 in one call." Affects Phase 1 design.
4. **Worktree handle cleanup on rollback:** If Phase 4 rolls back per-worktree (per §19), the synthesized `WorktreeHandle` for that worktree is orphaned in Dhara. Should the rollback also clean up the registry entry, or leave it for an explicit GC?
5. **Pre-v2 fastblocks path-shape bug fix:** Out of scope for v3 (which is the receiving-end fix). Should the consumer-side fix be a sibling ADR?

## Related Decisions

- **ADR-001: Use Oneiric for Configuration and Logging** — v3 extends Oneiric's resolver and (per §2) relocates `StorageSettings` to Oneiric. Consistent.
- **ADR-004: Adapter Architecture** — v3 follows the ABC + extensions pattern; new `LocalWorktreeProvider`/`S3WorktreeProvider` extend the existing ABC.
- **ADR-006: Simplify Storage Architecture** — v3 keeps PostgreSQL as the primary app-data store (via Dhara) and adds Redis as the L2 cache tier. v3 does NOT introduce `DharaCacheAdapter` (which would violate the 2-system spirit). Redis reintroduction is justified by serverless-distributable deployment model (different scale than v1 of ADR-006 considered).
- **ADR-009: Hybrid Adapter Registry** — v3 uses capability-based routing via `find_by_capabilities`.
- **ADR-013: Adapter Tool Boundary Between Mahavishnu and Dhara** — v3 strictly preserves the boundary. `DharaCacheAdapter` removed; durable state routes through `dhara_adapter.py`.
- **015-multi-agent-review** — the round-1 and round-2 review documents that drove v2 and v3.

## References

- Oneiric storage adapters: `oneiric/oneiric/adapters/storage/{local,s3,gcs,azure}.py`
- Oneiric cache adapters: `oneiric/oneiric/adapters/cache/{redis,memory,multitier}.py`
- Oneiric resolver: `oneiric/oneiric/core/resolution.py`
- Mahavishnu `paths.py`: `mahavishnu/mahavishnu/core/paths.py`
- Existing `WorktreeProvider` ABC: `mahavishnu/mahavishnu/core/worktree_providers/base.py:8`
- Existing `WorktreeCoordinator`: `mahavishnu/mahavishnu/core/worktree_coordination.py:47`
- Existing `WorktreeProviderRegistry`: `mahavishnu/mahavishnu/core/worktree_providers/registry.py:42`
- Hook: `mahavishnu/.claude/hooks/worktree-session-isolation.py:53`
- Dhara cache substrate: `dhara/dhara/mcp/kv_timeseries.py:60`
- `MAHAVISHNU_TOOL_PROFILE`, `DEPRECATED_TOOLS`: `mahavishnu/mahavishnu/mcp/tool_versions.py:293-304`
- Round-1 multi-agent review: `docs/adr/015-multi-agent-review.md`
- Round-2 multi-agent review (synthesis in commit message): see commit history of `015-multi-agent-review-round-2.md`

---

**END OF ADR-015 v3**