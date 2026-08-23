---
status: proposed
role: canonical
date: 2026-08-23
last_reviewed: 2026-08-23
supersedes: "015-worktree-and-cache-storage", "015-worktree-and-cache-storage-v2", "015-worktree-and-cache-storage-v3"
blocks_on: []
decision_date: null
topic: storage-abstraction
related:
  - "015-multi-agent-review"
  - "015-worktree-and-cache-storage"
  - "015-worktree-and-cache-storage-v2"
  - "015-worktree-and-cache-storage-v3"
  - "006-simplify-storage-architecture"
  - "013-mahavishnu-dhara-adapter-tool-boundary"
  - "001-use-oneiric"
---

# ADR 015: Worktree and Cache Storage Architecture (Revised v4)

## Status

**Proposed v4** — supersedes v1, v2, v3. v4 incorporates the final-pass review findings (2 fresh-lens reviewers) that exposed blockers rounds 1 and 2 missed. The strategic direction from v1 is preserved; the corrections are localized to type definitions, missing symbols, and Phase 4 risk.

**Date:** 2026-08-23

## What changed from v3

| Change | v3 → v4 | Source |
|---|---|---|
| **`Principal` class definition** | v3 referenced `from mahavishnu.auth import Principal` — symbol does not exist anywhere. v4 defines the class explicitly in `mahavishnu/auth.py`. | code-reviewer (top ambiguity #1) + general-purpose (concern #3) |
| **`WorktreeProvider(Protocol)` removed** | v3's §13 defined a Protocol with signatures incompatible with the existing `WorktreeProvider(ABC)`. v4 deletes the Protocol; concrete classes extend the existing ABC only. | code-reviewer (compatibility check) |
| **`BackendKind` literal type** | v3 used bare string literals (`"local"`, `"s3"`) for `backend_kind`. v4 uses `Literal` for type-safe discrimination. | code-reviewer (ambiguity #5) |
| **`LocalWorktreeRef` / `S3WorktreeRef` field shape** | v3's `LocalWorktreeRef` was missing `worktree_id: str` (the §12 example was non-compiling). v4 adds the field. | code-reviewer (ambiguity #6) |
| **`WorktreeLocked` / `WorktreeIntegrityError` exception base** | v3 had them extending bare `Exception` (violates CLAUDE.md's "use `mahavishnu/core/errors.py` hierarchy" rule). v4 has them extend the existing `WorktreeError(MahavishnuError)`. | code-reviewer (compilation check) |
| **Unused imports in §13** | v3 imported `IO`, `TracebackType`, `runtime_checkable` but didn't use them. v4 removes them. | code-reviewer (compilation check) |
| **§12 pre-v2 migration example** | v3's `pre_migration_discover()` snippet didn't supply `worktree_id` to `LocalWorktreeRef`. v4 fixes. | code-reviewer (ambiguity #6) |
| **Phase 4 pre-spike** | v3 went straight to Phase 4 implementation. v4 adds a 1-2 day spike on 3-5 actual misplaced worktrees before committing to the 83-worktree migration. | general-purpose (top concern #1) |
| **Oneiric `LifecycleError` sign-off** | v3 listed as Phase 0 sub-task with no explicit maintainer confirmation. v4 flags as a hard prerequisite — must get Oneiric maintainer sign-off before Phase 0. | general-purpose (top concern #2) |
| **Dhara worktree-registry schema sign-off** | v3 implied Dhara substrate readiness. v4 flags as a hard prerequisite — must get Dhara maintainer sign-off on the schema before Phase 1. | general-purpose (hidden deps) |
| **Open Question #3 (BundleTransport for local)** | v3 had the question open. v4 marks it resolved: BundleTransport is deferred to a follow-up ADR. | general-purpose (minor inconsistency) |
| **`WorktreeCoordinator` return type** | v3 ambiguous (returns `dict[str, Any]` currently, no spec for new shape). v4 specifies: returns `WorktreeHandle` from new providers, adapts to `WorktreeInfo` for old call sites. | code-reviewer (ambiguity #2) |

## Context

A 2026-08-23 ecosystem audit surfaced three related problems:

**Worktrees** — 210 total, 83 misplaced. The misplacement stems from three bugs:
1. `MAHAVISHNU_AUTO_WORKTREE_ROOT` defaults to `~/worktrees` (literal hardcoded string), but actual code path produces `~/worktrees/agent-<hex8>/` (wrong sub-shape).
2. Auto-worktree tool computes `parent/<repo>.worktrees/<branch>/` (sibling of repo).
3. Result: 65 mahavishnu `agent-*` worktrees in `~/worktrees/`, 16 fastblocks siblings at `~/Projects/{fb-*,fastblocks-task*}`, 1 neo4j sibling at `~/Projects/neo4j-mcp.worktrees/`, 1 fastblocks `phase-5-v4` at `~/.claude/worktrees/`.

**Caches** — 22+ GB scattered across the filesystem. 24 per-MCP `.venv/` (~18 GB), 29 per-repo `.crackerjack/` (3 GB), per-repo tooling caches (~3.4 GB), stray `~/.cache/*` dirs.

**Deployment model** — serverless deploys make the package directory read-only and `/tmp` ephemeral. Whatever default path mahavishnu writes to **must** work for serverless.

## Decision

### 1. Storage: use Oneiric's existing storage adapters directly

The four Oneiric storage adapters provide what we need. New `LocalWorktreeProvider` and `S3WorktreeProvider` extend the **existing `WorktreeProvider` ABC** at `mahavishnu/core/worktree_providers/base.py:8`. **No new Protocol.** No parallel abstraction.

The 5-default drift in `MAHAVISHNU_AUTO_WORKTREE_ROOT` is fixed by funneling all reads through `paths.py::get_worktree_base_path()`. Phase 0 includes a CI guard test pinning "every reference to worktree base path must resolve through `paths.py::get_worktree_base_path()`."

The existing `direct_git.py` is renamed to `local.py` and the new `LocalWorktreeProvider` takes its place. `DirectGitProvider` becomes a 1-release deprecated alias. The new path replaces the v1 path with a single compatible shim, not a parallel abstraction.

### 2. `StorageSettings` lives in Oneiric, not in `MahavishnuSettings`

`StorageSettings` is relocated to `oneiric/oneiric/config.py` (new module), re-exported by `mahavishnu/mahavishnu/core/config.py` for backward compat. Nested per-adapter fields (matching Oneiric's `LocalStorageSettings` / `S3StorageSettings` / `GCSStorageSettings` / `AzureBlobStorageSettings` / `RedisCacheSettings` / `DharaDurableSettings`).

### 3. Cache: use Oneiric's `MultiTierCacheAdapter` directly

`MultiTierCacheAdapter` (L1+L2 with metrics) does what the cache tier needs. **No new `CacheBackend` Protocol.**

**Cache key namespacing** is mandatory: `StorageSettings.redis_key_prefix: str = "mahavishnu:"` (default). Oneiric's `RedisCacheAdapter` constructor accepts a `key_prefix` argument.

### 4. Backend selection: Oneiric's `ResolverSettings.selections`

Capability-based selection. CLI/agent code calls `resolver.resolve("worktree-provider", "default")`. Preserves Oneiric's `DecisionEvent` audit trail.

### 5. Multi-tenancy from day one — `Principal` defined explicitly

`Principal` is **defined in this ADR** and lands in `mahavishnu/mahavishnu/auth.py` (a new module; today `mcp/auth.py` uses bare `user_id: str`). v3 referenced `Principal` in 4 sections without ever defining it. v4 fixes that:

```python
# mahavishnu/mahavishnu/auth.py (new module)

from __future__ import annotations
import os
from dataclasses import dataclass, field
from typing import Literal


CleanupPolicy = Literal["mark", "keep", "remove"]


@dataclass(frozen=True, slots=True)
class Principal:
    """Identity for storage operations. Multi-tenant boundary key.

    Constructed via Principal.from_uid() for local-host contexts
    (uid derivation from os.getuid()), Principal.anonymous() for
    serverless contexts, or Principal.current() for the current
    process's uid.
    """

    uid: int | None  # None = anonymous
    name: str
    scopes: frozenset[str] = field(default_factory=frozenset)
    cleanup_policy_override: CleanupPolicy | None = None

    @classmethod
    def from_uid(cls, uid: int) -> Principal:
        return cls(uid=uid, name=f"uid:{uid}")

    @classmethod
    def anonymous(cls) -> Principal:
        return cls(uid=None, name="anonymous")

    @classmethod
    def current(cls) -> Principal:
        """Returns Principal.from_uid(os.getuid()) for the current process."""
        return cls.from_uid(os.getuid())

    @property
    def is_anonymous(self) -> bool:
        return self.uid is None
```

**Existing-worktree migration:** the 65 mahavishnu `agent-*` worktrees and 16 fastblocks siblings were created without a `Principal` recorded. Phase 4 includes an explicit pre-migration step (see §12) that synthesizes handles with `Principal = Principal.current()` for local-host worktrees and `Principal = Principal.anonymous()` for serverless-style worktrees.

### 6. Bundle integrity (SHA-256 + optional signature)

Every bundle is hashed at creation time; SHA-256 stored in S3 object metadata (`x-amz-meta-sha256`). At fetch time, the hash is verified. Mismatch → `WorktreeIntegrityError` (subclass of `WorktreeError`) + audit log entry.

**Pre-v2 worktree fetch behavior:** lazy `git bundle create` + `sha256sum` on first `fetch()`. Bundle written to S3 (canonical storage) and hash cached in the synthesized `WorktreeHandle`. **`git bundle create` failure fails closed** (no worktree materialization).

### 7. Serverless safety in Oneiric's `LocalStorageAdapter`

`os.access(W_OK)` check belongs in Oneiric's `LocalStorageAdapter.init()`. Local worktree provider propagates `LifecycleError("local-storage-readonly-filesystem")` from Oneiric.

**Hard prerequisite for Phase 0:** explicit Oneiric maintainer sign-off on the `LifecycleError` enhancement. Without it, Phase 0 either stalls or has to drop serverless safety (a top-level decision driver from v1).

**Lambda-specific behavior:** `MAHAVISHNU_CACHE_BASE_PATH` and `MAHAVISHNU_WORKTREE_BASE_PATH` MUST be set explicitly in Lambda deployments (e.g., `/tmp/mahavishnu/...`), or `MAHAVISHNU_WORKTREE_PROVIDER_SELECTION=s3-primary`.

### 8. Update `.claude/hooks/worktree-session-isolation.py`

Hook reads `paths.py::get_worktree_base_path()` (no direct env-var reads). `MAHAVISHNU_AUTO_WORKTREE_ROOT` kept as 1-release alias, then deprecated.

### 9. Path resolution uses `paths.py`

`get_worktree_base_path()` (new helper in `paths.py`) for the worktree root. `get_data_path("worktrees", repo, branch)` for per-worktree subdirs. No hand-rolled paths.

### 10. `MAHAVISHNU_AUTO_WORKTREE_CLEANUP` policy: default `mark`, explicit override

| Policy | Behavior |
|---|---|
| `mark` (default) | Mark worktree as abandoned in registry; never auto-remove |
| `keep` | Same as `mark` but also leave a record of uncommitted work |
| `remove` | Auto-remove worktree on SessionEnd (loses uncommitted work; not default) |

Policy is set globally via `StorageSettings.cleanup_policy_default`. Per-worktree override: `cleanup_policy: CleanupPolicy | None` field on `WorktreeHandle`. Per-principal override: `Principal.cleanup_policy_override`.

### 11. Worktree registry schema (Dhara)

**Hard prerequisite for Phase 1:** explicit Dhara maintainer sign-off on the schema below. Without it, Phase 1 cannot begin.

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

### 12. Pre-v2 migration story (Phase 4 prerequisite)

```python
# Phase 4 pre-migration (run before any worktree moves)
import uuid

from mahavishnu.auth import Principal


def synthesize_uuid() -> str:
    return uuid.uuid4().hex


def parse_porcelain(output: str) -> list[dict[str, str]]:
    """Parse 'git worktree list --porcelain' output into list of dicts.

    Each block separated by blank line; key/value pairs separated by ' '.
    """
    blocks: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in output.splitlines():
        if not line:
            if current:
                blocks.append(current)
                current = {}
            continue
        key, _, value = line.partition(" ")
        current[key] = value
    if current:
        blocks.append(current)
    return blocks


def infer_repo(worktree_path: str) -> str:
    """Best-effort: parse repo name from worktree path."""
    return worktree_path.rstrip("/").split("/")[-1]


def pre_migration_discover(main_repo: str) -> list[WorktreeHandle]:
    """Discover all worktrees for main_repo and synthesize WorktreeHandles."""
    import subprocess
    result = subprocess.run(
        ["git", "-C", main_repo, "worktree", "list", "--porcelain"],
        capture_output=True, text=True, check=True,
    )
    raw = parse_porcelain(result.stdout)
    principal = Principal.current()
    handles = []
    for entry in raw:
        wt_path = entry["worktree"]
        # entry["HEAD"] is the commit; entry.get("branch") is the branch ref
        branch = entry.get("branch", "").removeprefix("refs/heads/") or "detached-HEAD"
        handle = WorktreeHandle(
            handle_id=synthesize_uuid(),
            principal=principal,
            repo=infer_repo(wt_path),
            branch=branch,
            base_ref=entry.get("HEAD", ""),
            created_at=datetime.now(UTC),
            storage_ref=LocalWorktreeRef(
                path=Path(wt_path),
                worktree_id=entry.get("worktree_id", synthesize_uuid()),
            ),
            sha256="",  # computed lazily on first fetch
            bytes_size=0,  # computed lazily
            cleanup_policy=None,
            provenance="pre-v2-migration",
        )
        handles.append(handle)
    return handles
```

Each synthesized handle is registered in Dhara with `provenance: "pre-v2-migration"`.

### 13. Concrete type definitions

```python
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal, Self

from mahavishnu.auth import CleanupPolicy, Principal
from mahavishnu.core.errors import MahavishnuError


# WorktreeRef backend discriminator (Literal, not StrEnum, for ABC subclass compat).
BackendKind = Literal["local", "s3", "gcs", "azure", "bundle"]


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
    cleanup_policy: CleanupPolicy | None = None
    provenance: str = "v3"


class WorktreeRef(ABC):
    """Backend-typed reference. Subclasses MUST override backend_kind."""

    @property
    @abstractmethod
    def backend_kind(self) -> str: ...


@dataclass(frozen=True, slots=True)
class LocalWorktreeRef(WorktreeRef):
    path: Path
    worktree_id: str

    @property
    def backend_kind(self) -> str:
        return "local"


@dataclass(frozen=True, slots=True)
class S3WorktreeRef(WorktreeRef):
    bucket: str
    key: str
    worktree_id: str

    @property
    def backend_kind(self) -> str:
        return "s3"


@dataclass(frozen=True, slots=True)
class BundleRef:
    bundle_key: str
    sha256: str
    signature: str | None
    created_at: datetime
    bytes_size: int


# Exceptions follow the mahavishnu/core/errors.py hierarchy (CLAUDE.md).
class WorktreeError(MahavishnuError):
    """Base class for all worktree operation errors."""
    pass


class WorktreeLocked(WorktreeError):
    """Distributed lock could not be acquired within the timeout."""
    pass


class WorktreeIntegrityError(WorktreeError):
    """Bundle hash mismatch at fetch time."""
    pass


@dataclass(frozen=True, slots=True)
class WorktreeLock:
    acquire_at: datetime
    expires_at: datetime
    owner_principal: Principal
    fencing_token: int
    repo: str
    branch: str


# No new WorktreeProvider Protocol. The existing WorktreeProvider(ABC)
# at mahavishnu/core/worktree_providers/base.py:8 is the production
# interface. New providers extend it; the adapter is at the
# WorktreeCoordinator level.
```

**`WorktreeCoordinator` return type contract:**

- `WorktreeCoordinator.create_worktree(...)` returns a new `WorktreeHandle` for new code paths.
- Existing call sites (CLI, MCP) that consume `dict[str, Any]` are adapted via a thin wrapper at the boundary (`_legacy_create_worktree_response(handle: WorktreeHandle) -> dict[str, Any]`).
- `WorktreeInfo` (at `worktree_manager.py:55`) is the per-task snapshot (with `task_id`, `state`, `metadata dict`). `WorktreeHandle` is the backend-neutral identifier. They are distinct types: `WorktreeHandle` is the durable registry record, `WorktreeInfo` is the per-task lifecycle record. A worktree may have a `WorktreeHandle` without being associated with a task (no `WorktreeInfo`); a task may reference a `WorktreeHandle` (carrying `WorktreeInfo` fields separately).

### 14. `lock()` semantics: Redis SETNX with fencing token

```python
async def lock(self, repo: str, branch: str, *, acquire_timeout: float = 10.0, lease_ttl: float = 30.0) -> WorktreeLock:
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
- `WorktreeLocked` raised on acquire failure or lease expiry

### 15. S3 / GCS credentials (delegated to Oneiric)

S3 and GCS credentials are managed by Oneiric's `S3StorageSettings` / `GCSStorageSettings` and resolved by the underlying cloud SDKs under the hood. No custom credential chain in mahavishnu.

**S3:** EXPLICIT credentials from `S3StorageSettings`; IMPLICIT chain (env vars → IRSA → OIDC → IMDS → IAM role) resolved by aioboto3.

**GCS:** service account JSON path via `GCSStorageSettings.credentials_path`; otherwise Application Default Credentials.

**GCS mock for tests/localhost** (§15.1): homebrew GCS mock package, configured via `GCSStorageSettings.endpoint_url: "http://localhost:4443"`. Recommended for CI test runners.

### 16. SLOs (concrete)

| Backend | Operation | p50 | p95 | p99 | Availability |
|---|---|---|---|---|---|
| Local | create_worktree | <50ms | <200ms | <500ms | 99.9% |
| Local | fetch | <20ms | <100ms | <300ms | 99.9% |
| S3 | create_worktree | <500ms | <2s | <5s | 99.5% |
| S3 | fetch (bundle <50MB) | <300ms | <1.5s | <4s | 99.5% |
| Redis (L1 miss → L2) | cache.get | <5ms | <20ms | <50ms | 99.9% |
| Dhara | state.set | <20ms | <100ms | <300ms | 99.5% |

`S3WorktreeProvider` restricted to repos under 50k commits OR repos where the bundle is <100MB. Larger repos use shallow clone. The 200-500ms p99 SLO applies only to small bundles.

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

**Prerequisites before Phase 0 starts:**
- [ ] Oneiric maintainer sign-off on `LifecycleError("local-storage-readonly-filesystem")` enhancement (cross-repo PR)
- [ ] Dhara maintainer sign-off on the worktree-registry schema in §11 (cross-repo PR)

**Phase 0 work:**
- Use `git revert -n eb247784 2f3649f9 c0b09a06` (preserves history)
- Add `LifecycleError("local-storage-readonly-filesystem")` to Oneiric's `LocalStorageAdapter.init()` (after PR merge)
- Unify the 5 default values for `MAHAVISHNU_AUTO_WORKTREE_ROOT` to `get_worktree_base_path()` across all 5 files
- Add CI guard test pinning "every reference to worktree base path must resolve through `paths.py::get_worktree_base_path()`"
- Rename `direct_git.py` → `local.py`; add `DirectGitProvider` as 1-release alias
- Create `mahavishnu/mahavishnu/auth.py` (new module) with `Principal` class

**Phase 1: Provider subclasses + pre-v2 migration (2-3 days)**

**Prerequisites before Phase 1 starts:**
- [ ] Dhara worktree-registry schema merged (from Phase 0 prerequisite)
- [ ] Phase 0 CI guard test passing on main

**Phase 1 work:**
- Add `LocalWorktreeProvider` extending the existing `WorktreeProvider` ABC
- Add `S3WorktreeProvider` extending the existing `WorktreeProvider` ABC
- Add concrete types: `WorktreeHandle`, `WorktreeRef` (ABC), `LocalWorktreeRef`, `S3WorktreeRef`, `BundleRef`, `WorktreeLock`, `WorktreeLocked`, `WorktreeIntegrityError` (all in `mahavishnu/core/worktree_providers/`)
- Run `pre_migration_discover()` for all 210 existing worktrees
- Register synthesized handles in Dhara with `provenance: "pre-v2-migration"`
- Update `WorktreeCoordinator` to dispatch via new providers
- Update `.claude/hooks/worktree-session-isolation.py` to read from `paths.py::get_worktree_base_path()`
- Implement `lock()` with Redis SETNX + fencing token

**Phase 1.5: Phase 4 pre-spike (1-2 days, BLOCKING before Phase 4)**

**This is new in v4.** Before committing to the 83-worktree migration, run a spike on 3-5 actual misplaced worktrees:
- Run `pre_migration_discover()` on a known-misplaced sample
- Verify the `.git` pointer files are parseable (the 83 worktrees are misplaced BECAUSE of path-computation bugs; their pointers may also be misconfigured)
- Verify the synthesized `WorktreeHandle` fields (principal, repo, branch) are correct
- If the spike fails: revise Phase 4 plan before committing

**Phase 2: Cache + observability (2-3 days, parallel with Phase 1)**

- Use Oneiric's `MultiTierCacheAdapter` directly (no new Protocol)
- Configure Redis: `maxmemory` sized after Phase 2 measurement, `allkeys-lfu`, `appendonly no`
- Wire cache invalidation: `WorktreeProvider.remove()` → `cache.delete(prefix="mahavishnu:worktree-cache:<handle_id>:")`
- Add per-cache-class registration via `ResolverSettings.selections`
- Export the SLO + observability metrics above

**Phase 3: 24 per-MCP `.venv/` deduplication (1 day, parallel)**

- Use `UV_PROJECT_ENVIRONMENT` env var
- Replace per-repo `.venv/` symlinks with a registry file at `~/.local/share/mahavishnu/venvs/registry.json`

**Phase 4: Migration of 83 misplaced worktrees (2-3 days, BLOCKED on Phase 1.5 spike)**

- For each misplaced worktree: read current handle, invoke `git worktree move` (or `WorktreeProvider.materialize` for S3 backend), verify SHA-256 lazily, register in Dhara
- Per-worktree safety check: skip if `git status` shows uncommitted changes
- Advisory lock per `(main_repo, branch)` during migration; SessionStart hook checks lock before creating new worktree at old path

**Phase 5: Documentation + deprecation (1 day)**

- Bump `worktree_manage` MCP tool to 2.0.0 (breaking payload change)
- Add `DEPRECATED_TOOLS` entry for `worktree_manage` v1; v1 callable for 2 minor releases
- Add translation shim for v1 payloads
- Update `discover_tools()` to return `deprecated: true` + `sunset_version` for v1 tools
- Update `MAHAVISHNU_AUTO_WORKTREE_ROOT` → `MAHAVISHNU_WORKTREE_BASE_PATH` (1-release alias)

**Total: 8-12 working days** (realistic per all reviewers; v1 said 4-5, v2 said 8-11, v3 said 8-12, v4 adds 1-2 days for the Phase 1.5 spike).

### 19. Rollback strategy per phase

| Phase | Rollback trigger | Procedure |
|---|---|---|
| Phase 0 | Approval blocked by maintainer | N/A — abort |
| Phase 1 | SLO breach > 2x baseline for 24h | `git revert <phase-1-sha>`, redeploy, flush Dhara worktree registry |
| Phase 1.5 | Spike fails on sample worktrees | Revise Phase 4 plan; do not proceed to Phase 4 |
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

**Reconstruction path for Dhara loss:** List `s3://bucket/worktrees/` keys, derive `(principal, repo, branch)` from path, read `x-amz-meta-sha256` and other metadata, rebuild `WorktreeHandle` records in Dhara from S3 inventory, mark `reconstructed_at` field, require operator confirmation before writes resume.

**S3 ↔ Dhara consistency check** (nightly cron): alert on orphans (S3 has, Dhara doesn't) and ghosts (Dhara has, S3 doesn't). Ghosts are more dangerous — flag for manual review, never auto-delete.

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
- **Serverless-safe.** `LocalStorageAdapter.init()` raises clear error on read-only filesystem.
- **Disk reclaim.** ~20-25 GB across the ecosystem migrates to backend-appropriate storage.
- **Observable.** SLOs + metrics + dashboards + runbooks are part of ratification.
- **Multi-tenant from day one.** `Principal` is now a real class (not a phantom reference).
- **No data loss.** Bundle integrity verified at fetch time; pre-v2 worktrees compute lazily.
- **No parallel abstraction layers.** New providers extend the existing `WorktreeProvider(ABC)`.
- **Cache invalidation tied to worktree lifecycle.**
- **Phase 4 spike validates the migration plan** before committing 8-12 days of work.

### Negative

- **Migration effort.** Realistic 8-12 days of focused work.
- **Phase 0 + 1 prerequisites block start.** Oneiric and Dhara maintainer sign-off required.
- **New failure modes.** All are observable; each has a runbook with an owner.
- **Cold start latency.** Serverless: bundle download + clone = 200-500ms p99 for small bundles.
- **Breaking change.** `worktree_manage` MCP tool v2.0.0 with 2-minor-release deprecation window.
- **StorageSettings relocation touches mahavishnu, oneiric, and Dhara.**

### Neutral

- v1, v2, v3 are now superseded. The 3 stale commits on `origin/main` are reverted via `git revert` (Phase 0), not force-push.
- The `WorktreeProvider` hierarchy is extended, not replaced. `direct_git.py` is renamed to `local.py` with a 1-release alias.
- Oneiric gains no new cache adapters (DharaCacheAdapter was an error in v2; ADR-013 boundary holds).
- `StorageSettings` lives in Oneiric for cross-component reuse.
- `Principal` lives in `mahavishnu/auth.py` (new module).
- `BundleTransport` decorator is deferred to a follow-up ADR.

## Open Questions

1. **Phase 0 Oneiric enhancement:** `LifecycleError("local-storage-readonly-filesystem")` requires a Oneiric PR. Confirm the Oneiric maintainer will accept this enhancement before starting Phase 0.
2. **Dhara worktree-registry schema:** confirm the Dhara maintainer accepts the schema in §11 before starting Phase 1.
3. **Per-cache TTL defaults:** the 3600s default for `StorageSettings.cache_ttl_seconds` is a guess. Real values depend on workload; set after Phase 2 instrumentation.
4. **Bundle transport for local:** Should `LocalWorktreeProvider` produce a bundle by default (for portability), or only on explicit request? **Deferred to a follow-up ADR** (was Open Question #3 in v3; resolved by deferral).
5. **Worktree handle cleanup on rollback:** If Phase 4 rolls back per-worktree, the synthesized `WorktreeHandle` for that worktree is orphaned in Dhara. Should the rollback also clean up the registry entry, or leave it for an explicit GC?

## Related Decisions

- **ADR-001: Use Oneiric for Configuration and Logging** — v4 extends Oneiric's resolver and (per §2) relocates `StorageSettings` to Oneiric.
- **ADR-004: Adapter Architecture** — v4 follows the ABC + extensions pattern; new `LocalWorktreeProvider`/`S3WorktreeProvider` extend the existing ABC.
- **ADR-006: Simplify Storage Architecture** — v4 keeps PostgreSQL as the primary app-data store (via Dhara) and adds Redis as the L2 cache tier.
- **ADR-009: Hybrid Adapter Registry** — v4 uses capability-based routing via `find_by_capabilities`.
- **ADR-013: Adapter Tool Boundary Between Mahavishnu and Dhara** — v4 strictly preserves the boundary. `DharaCacheAdapter` removed; durable state routes through `dhara_adapter.py`.
- **015-multi-agent-review** — the round-1, round-2, and final-pass reviews that drove v2, v3, and v4.

## References

- Oneiric storage adapters: `oneiric/oneiric/adapters/storage/{local,s3,gcs,azure}.py`
- Oneiric cache adapters: `oneiric/oneiric/adapters/cache/{redis,memory,multitier}.py`
- Oneiric resolver: `oneiric/oneiric/core/resolution.py`
- Mahavishnu `paths.py`: `mahavishnu/mahavishnu/core/paths.py`
- Existing `WorktreeProvider` ABC: `mahavishnu/mahavishnu/core/worktree_providers/base.py:8`
- Existing `WorktreeCoordinator`: `mahavishnu/mahavishnu/core/worktree_coordination.py:47`
- Existing `WorktreeProviderRegistry`: `mahavishnu/mahavishnu/core/worktree_providers/registry.py:42`
- Existing `WorktreeError(MahavishnuError)`: `mahavishnu/mahavishnu/core/worktree_manager.py:95`
- Hook: `mahavishnu/.claude/hooks/worktree-session-isolation.py:53`
- Dhara cache substrate: `dhara/dhara/mcp/kv_timeseries.py:60`
- `MAHAVISHNU_TOOL_PROFILE`, `DEPRECATED_TOOLS`: `mahavishnu/mahavishnu/mcp/tool_versions.py:293-304`
- Multi-agent review (round 1): `docs/adr/015-multi-agent-review.md`
- Multi-agent review (round 2): synthesis in commit history of `015-multi-agent-review-round-2.md`

---

**END OF ADR-015 v4**