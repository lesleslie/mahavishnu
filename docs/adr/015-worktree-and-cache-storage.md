---
status: draft
role: canonical
date: 2026-08-23
last_reviewed: 2026-08-23
superseded_by: null
blocks_on: []
decision_date: null
topic: storage-abstraction
---

# ADR 015: Worktree and Cache Storage Architecture

## Status

**Proposed**

**Date:** 2026-08-23

## Context

A 2026-08-23 audit of worktree, branch, and config dirs across the Bodai ecosystem surfaced two related design problems that share a single root cause: **mahavishnu state is filesystem-coupled, and the filesystem defaults are wrong for both distribution and serverless**.

### The two problems (concrete data)

**Worktrees** — 210 total across the ecosystem, 83 misplaced. The misplacement stems from three bugs:

1. `MAHAVISHNU_AUTO_WORKTREE_ROOT` defaults to `~/worktrees` (literal hardcoded string), but the actual code path produces `~/worktrees/agent-<hex8>/` (wrong sub-shape, bypasses `WorktreePathValidator`). Result: 65 mahavishnu `agent-*` worktrees in `~/worktrees/agent-<hex8>/`.
2. The auto-worktree tool computes `parent/<repo>.worktrees/<branch>/` (sibling of repo, not under it). Result: 16 fastblocks siblings at `~/Projects/{fb-*,fastblocks-task*}/` + 1 neo4j sibling at `~/Projects/neo4j-mcp.worktrees/`.
3. The auto-worktree tool's path-shape bug is the same as (1). Result: 1 fastblocks `phase-5-v4` worktree at `~/.claude/worktrees/phase-5-v4/`.

Three commits landed on `origin/main` (eb247784, 2f3649f9, c0b09a06) updating the default to `~/Projects/worktrees`, but a user review revealed the deeper issue: **whatever literal path is hardcoded will be wrong for some deployment model**.

**Caches** — 22+ GB scattered across the filesystem:

| Cache | Where | Size | Why it's wrong |
|---|---|---:|---|
| 24 per-MCP-server `.venv/` | Inside each `<repo>/.venv/` | ~18 GB | Duplicated Python envs (uv cache is already at `~/.cache/uv`, 8.2 GB) |
| 29 per-repo `.crackerjack/` | Inside each `<repo>/.crackerjack/` | 3.0 GB | Tooling state; gitignored but still on disk |
| Per-repo `.mypy_cache`, `.ruff_cache`, `.pytest_cache`, `htmlcov` | Inside each `<repo>/` | ~3.4 GB | Regenerable build artifacts |
| Stray `~/.cache/{huggingface, pre-commit, puppeteer, chrome-devtools-mcp}` | Home root | ~2 GB | Should be in app-specific XDG subdirs |
| Per-tool `~/.cache/{crackerjack, akosha, session-buddy, oneiric, mahavishnu}` | Home root | ~10 GB total | Some in XDG (`~/.cache/<app>/`), some scattered |

A local Redis server is available. Dhara is the curator of persistent state in the Bodai ecosystem. The Bodai spec already says caches and registries should be in Redis (ephemeral) or Dhara (persistent), not on disk.

### The deployment-model problem

The user (2026-08-23): "mahavishnu can be deployed serverless and it's home/package dir may not be writable."

In serverless (AWS Lambda, Cloud Run, Vercel Functions):

- The package directory is read-only
- `/tmp` is the only writable location, and it's ephemeral (lost on cold start)
- Whatever default path mahavishnu writes to **must** be one of:
  - A mounted network filesystem (EFS, NFS) — only with explicit config
  - A storage service (S3, GCS, Azure Blob, Redis, Dhara) — adapter-based
  - `/tmp` for short-lived, regenerateable state only

This means **none of the filesystem defaults work for serverless**. The right answer is an adapter abstraction that defaults to filesystem when writable, errors clearly when filesystem is not writable, and supports cloud backends when configured.

### What already exists in the ecosystem

We don't have to build this from scratch:

- **Oneiric storage adapters** at `oneiric/adapters/storage/`: `LocalStorageAdapter` (filesystem, blob API), `S3StorageAdapter`, `GCSStorageAdapter`, `AzureBlobStorageAdapter`. Same interface: `init`, `health`, `cleanup`, `save/read/delete/list/exists` (local) or `upload/download/delete/list` (cloud). Bytes-in, bytes-out.
- **Oneiric adapter registry** resolves which adapter to use at runtime by capabilities/priority.
- **Redis** is available locally (per user, 2026-08-23).
- **Dhara** is the durable state store (`dhara/dhara/`); provides ACID transactions, key-value, time-series, audit, etc.
- **Mahavishnu `paths.py`** already implements XDG-correct dirs via `platformdirs`: `DATA_DIR = user_data_dir`, `CACHE_DIR = user_cache_dir`, `STATE_DIR = user_state_dir`. So the per-app state dirs are correctly placed; the *contents* of the scattered cache dirs just need to flow through these.

The right answer is to use what we have: wire mahavishnu's `WorktreeManager` and the scattered cache writers through Oneiric's adapter interface, with `LocalStorageAdapter` as the dev default and `S3StorageAdapter` (or GCS/Azure) for serverless. Hot caches go to Redis. Persistent state goes to Dhara.

## Decision Drivers

- **Distributable.** Whatever default we pick must work in any deployment, not just one developer's local checkout.
- **Serverless-safe.** A misconfigured default must error clearly, not silently lose data.
- **Single source of truth for storage.** No more "X writes to `.crackerjack/` and Y writes to `~/.cache/mahavishnu/crackerjack/`" — both go through the same backend.
- **Hot/persistent/regenerable have different homes.** Hot cache (Redis) ≠ persistent state (Dhara) ≠ regenerable cold cache (XDG disk). Conflating them is what produced the mess.
- **No data loss during migration.** The 83 misplaced worktrees, 24 per-MCP `.venv/` dirs, and 29 `.crackerjack/` dirs all contain potentially-active work or recoverable state. Migration is a one-way trip; the path must be planned.

## Decision (proposed)

### 1. Introduce `WorktreeStorage` protocol in `mahavishnu/core/storage/worktree_storage.py`

```python
class WorktreeStorage(Protocol):
    async def create(self, repo: str, branch: str, base_ref: str) -> WorktreeHandle: ...
    async def fetch(self, handle: WorktreeHandle) -> WorktreeRef: ...
    async def list(self, repo: str | None = None) -> list[WorktreeHandle]: ...
    async def remove(self, handle: WorktreeHandle) -> None: ...
```

`WorktreeHandle` is a backend-agnostic identifier (UUID + metadata). `WorktreeRef` is a backend-typed reference: `LocalWorktreeRef` carries a filesystem path, `S3WorktreeRef` carries an S3 URI, `BundleWorktreeRef` carries a git-bundle path or pointer.

### 2. Three backend implementations

- **`LocalWorktreeBackend`** — wraps `LocalStorageAdapter`. Writes worktree bundles to `~/.local/share/mahavishnu/worktrees/<repo>/<branch>/.bundle` (XDG `DATA_DIR`), then `git clone --reference` to a per-task scratch dir. The default for local dev.
- **`S3WorktreeBackend`** — wraps `S3StorageAdapter`. Uploads bundles to `s3://<bucket>/worktrees/<repo>/<branch>/.bundle`. The default for serverless. Cold start cost: one bundle download + one `git clone` per task.
- **`GitBundleWorktreeBackend`** — uses `git bundle create` for portability. Worktrees become portable bundles regardless of storage backend. Optional optimization layered over the local or S3 backend.

### 3. Introduce `CacheBackend` protocol in `mahavishnu/core/cache/cache_backend.py`

```python
class CacheBackend(Protocol):
    async def get(self, key: str) -> bytes | None: ...
    async def set(self, key: str, value: bytes, ttl: int | None = None) -> None: ...
    async def delete(self, key: str) -> None: ...
    async def list(self, prefix: str = "") -> list[str]: ...
```

Four backend implementations, selected per cache type:

| Cache | Backend | When |
|---|---|---|
| Hot, regenerable, < 1 MB | **Redis** with TTL | `.mypy_cache`, `.ruff_cache`, lookup results, hot config |
| Warm, regenerable, < 100 MB | **Oneiric Local (XDG)** with TTL | `.crackerjack/` state, `.pytest_cache` |
| Cold, regenerable, any size | **Oneiric Local (XDG)** | Long-tail build artifacts |
| Persistent, not regenerable | **Dhara** | Worktree registry, session metadata, audit log, stats |
| Ephemeral, request-scoped | **In-memory dict** (no backend) | Intermediate computation |

### 4. Default selection via env var

```bash
# Worktree backend (default: local)
MAHAVISHNU_WORKTREE_BACKEND=local|s3|gcs|azure|bundle

# Cache backend (default: redis if available, else oneric-local)
MAHAVISHNU_CACHE_BACKEND=redis|oneric-local|dhara|memory

# Override the oneric-local base path (default: ~/.local/share/mahavishnu/cache)
MAHAVISHNU_CACHE_BASE_PATH=...
```

### 5. Serverless safety

- `LocalWorktreeBackend.__init__` calls `os.access(base_path, os.W_OK)`. If the path is in a read-only filesystem (serverless `/var/task`, etc.), raise `LifecycleError("worktree-storage-readonly-filesystem")` with a clear hint: "Set MAHAVISHNU_WORKTREE_BACKEND=s3 for serverless."
- `LocalCacheBackend` does the same check.
- `MAHAVISHNU_AUTO_WORKTREE_ROOT` is retained as a per-deployment override for the local backend's base path. Default is the XDG `DATA_DIR`.

### 6. Migration plan

**Phase 0: Revert stale commits (immediate)**

- Force-push to drop `eb247784`, `2f3649f9`, `c0b09a06` from `origin/main` — they hardcode `~/Projects/worktrees` and are known wrong pending this ADR.
- The 83 worktree moves (audit follow-up) are blocked on this ADR.

**Phase 1: Storage abstraction (1-2 days)**

- `mahavishnu/core/storage/worktree_storage.py` with the protocol
- `LocalWorktreeBackend`, `S3WorktreeBackend` (full), `GitBundleWorktreeBackend` (stub)
- Wire into existing `WorktreeManager` (becomes a thin wrapper)
- Existing env var `MAHAVISHNU_AUTO_WORKTREE_ROOT` retained for local-backend path override

**Phase 2: Cache migration (2-3 days)**

- `mahavishnu/core/cache/cache_backend.py` with the protocol
- `RedisCacheBackend`, `OnericCacheBackend`, `DharaCacheBackend`, `InMemoryCacheBackend`
- Migrate scattered writers: `.crackerjack/`, per-MCP `.venv/`, per-repo `.mypy_cache/.ruff_cache/.pytest_cache`
- Per-MCP `.venv/` → shared `~/.local/share/mahavishnu/venvs/<app>/.venv/` (uv-managed, symlinked per-repo)

**Phase 3: Migration of 83 misplaced worktrees + 24 per-MCP venvs (1-2 days)**

- Use the new `WorktreeStorage` API: for each misplaced worktree, `local.fetch()` then `local.create(repo, branch, base_ref)` to land it in the canonical location, then `local.remove(old_handle)` to clean up.
- For 24 per-MCP `.venv/`: move to shared venv root, symlink from per-repo for compatibility, update `pyproject.toml` or use `UV_PROJECT_ENVIRONMENT` env var.

**Phase 4: Documentation (1 day)**

- Update `CLAUDE.md` to reflect: worktrees via `WorktreeStorage`, caches via `CacheBackend`
- Document env vars: `MAHAVISHNU_WORKTREE_BACKEND`, `MAHAVISHNU_CACHE_BACKEND`
- Update MCP tool docs (`mcp/tools/worktree_tools.py`, `mcp/tools/quality_tools.py`) to reflect new abstractions
- Add "Cache hygiene" runbook to `docs/runbooks/`

## Alternatives Considered

### Worktree storage

**A. Hardcode `~/Projects/worktrees` (REJECTED)** — what the 3 stale commits did. Not portable, not serverless-safe.

**B. Project-relative `<mahavishnu_repo>/.worktrees/` (REJECTED)** — works for source-tree dev installs, but `__file__`-based resolution breaks when mahavishnu is PyPI-installed into a venv. Doesn't solve serverless.

**C. XDG `~/.local/share/mahavishnu/worktrees/` (PARTIAL)** — correct for local dev, still doesn't work serverless. Useful as the local-backend default inside the adapter pattern (Option D).

**D. Storage adapter with XDG local default + S3/GCS/Azure cloud backends (PROPOSED)** — portable, serverless-safe, lets users pick deployment model. Slightly more code (the protocol + 3 backends) but uses existing Oneiric adapters.

**E. Per-repo `<repo>/.worktrees/` (REJECTED)** — what the audit found as one of the misplacement patterns. No single-pane view, no cross-repo coordination.

### Cache storage

**A. Keep on disk (REJECTED)** — current state. 22+ GB scattered, breaks serverless, no observability.

**B. Single backend (Redis OR Dhara OR disk) (REJECTED)** — wrong tool for the wrong job. Hot data shouldn't pay the cost of ACID transactions; persistent state shouldn't be dropped on TTL.

**C. Pluggable backends with hot/warm/cold/persistent classification (PROPOSED)** — different data has different requirements. Same protocol, four backends, classified by usage pattern.

## Consequences

### Positive

- **Distributable.** Defaults work in any deployment. The hardcoded-path audit miss (2026-08-23) becomes a class of bug that the abstraction makes impossible.
- **Serverless-safe.** Local backend raises a clear error if filesystem is read-only. Cloud backends are one env var away.
- **Disk reclaim.** ~20-25 GB of scattered cache dirs can be moved/removed. The 24 per-MCP `.venv/` deduplication saves ~15 GB.
- **Observable.** Storage health, latency, error rates become first-class via Oneiric's adapter health checks, Redis `MONITOR`, Dhara metrics.
- **Hot data fast.** Caches that don't need persistence (Redis TTL) are no longer paying the cost of writing to disk.

### Negative

- **Migration effort.** Existing `WorktreeManager` and scattered cache writers need to be refactored. Estimated 4-5 days of focused work (Phase 1+2 above).
- **New failure modes.** Redis can be down; S3 can be down; Dhara can be down. All are observable; each can fall back to a degraded mode. The current design has no failure modes in the same sense (it just loses data silently if the disk is full).
- **Cold start latency.** Serverless: each task pays one bundle download + one `git clone` to `/tmp/<task>`. Estimated 200-500 ms overhead per task. Mitigated by caching bundles in `/tmp/<bucket-key>/` for warm starts within a single instance lifetime.

### Neutral

- **3 stale commits must be reverted** before this design is implementable. The current `origin/main` carries a default that any reviewer of this ADR would reject.
- **The 83-worktree migration** (audit follow-up) becomes a `WorktreeStorage.fetch + create + remove` operation per worktree, instead of a `git worktree move`. Cleaner abstraction, more code, same end state.
- **CLAUDE.md** will need updates to reflect the new env vars and abstractions.

## Open Questions

1. **PyPI install.** If mahavishnu is installed via `pip install mahavishnu` into a site-packages location, `__file__`-based resolution no longer points at a project tree. The storage adapter pattern handles this (cloud backends), but the local-backend default becomes "wherever `~/.local/share/mahavishnu` is" rather than "next to the package." Is that the right call? Confirm before Phase 1.
2. **Per-MCP `.venv/` deduplication.** 24 dirs × 745 MB is real waste. uv's `UV_PROJECT_ENVIRONMENT` env var or a project-relative shared venv root are the two options. Which? (Affects Phase 2.)
3. **Worktree bundling for non-git work.** If a worktree is in detached-HEAD state or has uncommitted changes, `git bundle` doesn't capture them. What's the right `WorktreeRef` shape for those cases? Affects Phase 1 backend signatures.
4. **Redis as default cache.** Should Redis be required (fail if not running) or optional (fall back to oneric-local if Redis is down)? What's the health-check story? Affects Phase 2 backend selection.
5. **Bundle format vs filesystem snapshot for the local backend.** Two options: (a) `LocalWorktreeBackend` writes a `.bundle` file, then `git clone` to extract, (b) `LocalWorktreeBackend` uses `git worktree add` directly (current behavior, just at a different path). Option (a) is consistent with the S3 backend's bundle semantics; option (b) is faster and simpler. Affects Phase 1.
6. **Deprecation of `MAHAVISHNU_AUTO_WORKTREE_ROOT`.** Retain for local-backend path override, or remove in favor of a unified `MAHAVISHNU_WORKTREE_BACKEND` + `MAHAVISHNU_LOCAL_BACKEND_PATH`? Affects public API surface.

## Decision Review

**Status: Proposed, awaiting maintainer review.**

- **Reviewer:** the project maintainer(s) of Mahavishnu (per the Bodai pre-1.0 merge policy, this lands directly on `main` once ratified).
- **SLA:** maintainer follow-up within 14 days of the proposal date. If no objection, this ADR moves to **Accepted**; if objections, the proposal is revised or moved to **Rejected** with rationale recorded in the *Open Questions* section.
- **Action requested:** maintainer to (1) ratify or modify the proposed backend classification, (2) address the six *Open Questions*, (3) approve the Phase 0 revert of the 3 stale commits, (4) approve the migration phases.

## Related Decisions

- **ADR-006: Simplify Storage Architecture from 4-System to 2-System** — settled PostgreSQL + Session-Buddy as the v1.0 storage story. This ADR extends that thinking to worktree and cache storage specifically, but doesn't conflict: PostgreSQL is still the primary app data store; this ADR covers git state (worktree bundles) and ephemeral hot data (caches), neither of which belongs in the v1.0 PostgreSQL story.
- **ADR-013: Adapter Tool Boundary Between Mahavishnu and Dhara** — documents the boundary between Mahavishnu's in-process view and Dhara's durable state. The new `WorktreeStorage` and `CacheBackend` abstractions sit on the same pattern: in-process hot path uses live data, durable state goes through Dhara, with clear ownership boundaries.
- **ADR-001: Use Oneiric for Configuration and Logging** — Oneiric is already the foundation for adapter resolution. The new storage backends here use Oneiric's adapter registry, consistent with ADR-001.

## References

- Oneiric storage adapters: `oneiric/oneiric/adapters/storage/{local,s3,gcs,azure}.py`
- Oneiric storage `__init__.py`: `oneiric/oneiric/adapters/storage/__init__.py`
- Mahavishnu `paths.py` (XDG-correct today): `mahavishnu/mahavishnu/core/paths.py`
- Dhara (curator): `dhara/dhara/`
- Three stale commits to revert: `eb247784`, `2f3649f9`, `c0b09a06`
- Audit findings: 2026-08-23 ecosystem audit (4 parallel agents; worktree inventory, branch audit, cache inventory, conventions audit)
- Memory: `serverless-readonly-package-dir`, `redis-dhara-caches-not-disk`

---

**END OF ADR-015**
