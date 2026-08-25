---
status: complete
role: historical
date: 2026-08-23
last_reviewed: 2026-08-23
superseded_by: null
blocks_on: ["015-worktree-and-cache-storage-v2"]
decision_date: null
topic: storage-abstraction-review
related: ["015-worktree-and-cache-storage", "015-worktree-and-cache-storage-v2"]
---

# ADR 015 Multi-Agent Review — Findings

## Purpose

This document captures the findings of the 9-agent multi-agent review of `015-worktree-and-cache-storage.md` (v1). It is a reference for the maintainer's review and the input for the v2 revision (`015-worktree-and-cache-storage-v2.md`).

**Reviewers:** 7 task-appropriate + 2 random, dispatched in parallel on 2026-08-23.

| Lens | Reviewer | Primary findings |
|---|---|---|
| mahavishnu code integration | mahavishnu-specialist | Existing `WorktreeProvider` hierarchy ignored; 5-default drift; wrong wiring target |
| Oneiric adapter integration | oneiric-specialist | `CacheBackend` Protocol duplicates Oneiric's existing cache adapters; `MultiTierCacheAdapter` already does L1+L2 |
| Cross-ecosystem architecture | architecture-council | `CacheBackend` StrEnum collision; ADR-006 Redis contradiction; ADR-013 Dhara boundary violation |
| Design pattern validation | architect-reviewer | `LocalWorktreeBackend` defeats worktree performance; bundling is transport not backend; concurrency/health semantics missing |
| Cache architecture (Redis) | redis-specialist | Stampede prevention missing; `KEYS prefix*` footgun; eviction policy unspecified |
| Reliability & failure modes | sre-engineer | No SLOs, no rollback, no observability metrics; silent data loss risk for uncommitted changes |
| MCP tool surface impact | mcp-integration-expert | Existing `SessionBuddyWorktreeProvider` not enumerated; `worktree_manage` payload change is breaking |
| Security lens (random) | api-security-specialist | Bundle content integrity = supply-chain risk; multi-tenancy missing; symlink-based venv migration = CVE surface |
| Python implementation lens (random) | python-pro | `WorktreeHandle`/`WorktreeRef` types undefined; async/sync boundary unanalyzed; bytes vs `IO[bytes]` for large values |

---

## Verdict

**Not ratifiable as written.** All 9 reviewers converged: the strategic direction (storage adapters, hot/warm/persistent classification, serverless safety) is sound. The implementation proposes parallel abstraction layers that duplicate Oneiric's existing work and ignore mahavishnu's existing `WorktreeProvider` hierarchy. Twelve BLOCKER-level findings need resolution before ratification.

---

## Cross-Reviewer BLOCKERs (12 findings, high confidence)

### B1. Existing `WorktreeProvider` / `WorktreeProviderRegistry` hierarchy ignored
**Reviewers:** mahavishnu-specialist, mcp-integration-expert, oneiric-specialist

`mahavishnu/core/worktree_providers/` (`base.py:21`, `direct_git.py:44`, `session_buddy.py:112`, `mock.py`) already implements the provider abstraction. The proposed `WorktreeStorage` Protocol is a parallel layer with incompatible signatures.

### B2. `LocalWorktreeBackend` design defeats worktree performance
**Reviewer:** architect-reviewer

The whole point of `git worktree add` is sharing `.git/objects/` with the source repo for performance. Re-bundling + cloning costs a full object DB walk per worktree. Local should use `git worktree add` directly.

### B3. `CacheBackend` Protocol duplicates Oneiric's existing cache adapters
**Reviewer:** oneiric-specialist

`RedisCacheAdapter`, `MemoryCacheAdapter`, and `MultiTierCacheAdapter` (already does L1+L2 with metrics) ship in Oneiric today. The proposal reinvents them.

### B4. `WorktreeHandle` and `WorktreeRef` not defined
**Reviewers:** python-pro, architect-reviewer

Referenced in Protocol signatures but never specified. Phase 1 implementation will stall on day one without concrete types.

### B5. `CacheBackend` naming collision with existing `CacheBackend` StrEnum
**Reviewers:** architecture-council, mcp-integration-expert

`mahavishnu/core/cache_manager.py:41-46` already defines `class CacheBackend(StrEnum)`. The new Protocol shadows it.

### B6. Phase 1 wires into the wrong class
**Reviewer:** mahavishnu-specialist

`WorktreeManager` is NOT on the production call path. CLI and MCP both call `app.worktree_coordinator` → `WorktreeProviderRegistry` → `WorktreeProvider`. Wiring into `WorktreeManager` doesn't intercept any production call site.

### B7. `DharaCacheBackend` violates ADR-013 boundary
**Reviewers:** architecture-council, oneiric-specialist

Dhara is the durable state owner, not a cache. Calling Dhara a cache substrate is exactly what ADR-013 was written to prevent. Either rename to `DharaDurableBackend` and put it in Oneiric, or drop entirely.

### B8. Env vars bypass `MahavishnuSettings`
**Reviewers:** python-pro, oneiric-specialist

Adding 3 new `MAHAVISHNU_*` env vars that don't go through Pydantic creates two parallel config surfaces. CLAUDE.md explicitly calls this antipattern.

### B9. Bundle content integrity unaddressed
**Reviewer:** api-security-specialist

`git bundle` as portable format + S3 as default backend + `git clone` on extract = implicit code execution under mahavishnu's identity. Needs SHA-256 verification minimum.

### B10. 5 different `MAHAVISHNU_AUTO_WORKTREE_ROOT` defaults in 5 files
**Reviewer:** mahavishnu-specialist

The ADR claims "XDG `DATA_DIR` is the default" but that's not true anywhere in code yet. Defaults exist at:
- `worktree_manager.py:176` — `"~/Projects/worktrees"`
- `worktree_validation.py:303` — `Path.home() / "Projects" / "worktrees"`
- `worktree_coordination.py:132` — `Path.home() / "worktrees"`
- `worktree-session-isolation.py:290` — `"~/worktrees"`
- `docs/CONFIGURATION.md:70` — `"~/worktrees"`

### B11. No SLOs, no rollback strategy, no observability metrics
**Reviewers:** sre-engineer, architect-reviewer

"Storage health, latency, error rates become first-class" is asserted in Consequences but the Protocol has no `health()`, no metric names, no runbook, no SLO targets.

### B12. Multi-tenancy not addressed
**Reviewer:** api-security-specialist

`WorktreeStorage.create()` takes no principal. CWE-639 (authorization bypass via user-controlled key) waiting to happen. If multi-user service ever ships, retrofitting a principal is breaking.

---

## Cross-Reviewer IMPORTANT issues (grouped)

### Protocol design gaps (architect-reviewer, python-pro, redis-specialist)
- No concurrency/locking semantics — two `create()` calls for same `(repo, branch)` race
- No `health()` method on either Protocol
- Cache stampede prevention missing — `get_or_compute(key, compute_fn, ttl, lock_ttl)` should be first-class
- `list(prefix)` is wrong primitive — Redis `KEYS prefix*` blocks event loop; needs `scan(prefix, cursor, count)`
- `list` materializes everything (memory hazard)
- No async context manager (`__aenter__`/`__aexit__`)
- No cancellation/atomicity contract for `bundle create + git clone`
- Bytes boundary vs `IO[bytes]` for large values
- `prefix: str = ""` inconsistent with Oneiric's `prefix: str | None = None`
- `WorktreePathValidator` sync vs `WorktreeStorage` async — boundary not analyzed

### Cache architecture (redis-specialist, architect-reviewer, sre-engineer)
- `maxmemory` and eviction policy not recommended
- Cache classification conflates data type and backend placement
- TTL units unspecified (seconds vs ms)
- Redis value serialization undefined (msgpack vs pickle vs JSON)
- Connection pool story absent
- Health-check policy for "redis if available" unspecified
- Cache invalidation strategy unstated (pub/sub vs streams)
- Cold-start cache warming story absent

### Operational (sre-engineer, mahavishnu-specialist, api-security-specialist)
- 24 per-MCP `.venv/` shared venv is SPOF
- `/tmp` extraction target needs `0o700` per-task dirs on long-running hosts
- Per-MCP venv symlink step lacks TOCTOU guard
- `S3` eventual consistency not addressed
- `S3` credentials rotation / IAM lag not addressed
- Dhara schema migration / replica lag not addressed
- No cost model for S3 storage / egress
- No capacity planning (Redis memory, S3 request rates, Dhara write throughput)
- No testing strategy (chaos tests, load tests, conformance tests)
- Cold-start 200-500ms estimate unverified

### Path/traversal/security (api-security-specialist, mahavishnu-specialist)
- Path traversal must route through `WorktreePathValidator`
- Audit hook preservation not asserted
- Redis auth/network exposure undefined (no TLS, no AUTH by default)
- Dhara auth model not specified
- Bundle integrity verification needed

### Cross-component (architecture-council, mcp-integration-expert, oneiric-specialist, mahavishnu-specialist)
- `DharaCacheBackend` should live in Dhara (where `kv_timeseries.py` already provides substrate)
- Existing `SessionBuddyWorktreeProvider` not enumerated
- `worktree_manage` payload schema must change breaking way
- `quality_tools.py` doesn't exist in mahavishnu (lives in crackerjack)
- `paths.py` already implements XDG correctly; ADR's hand-rolled paths bypass it
- `.claude/hooks/worktree-session-isolation.py` reads `MAHAVISHNU_AUTO_WORKTREE_ROOT` independently
- `MAHAVISHNU_AUTO_WORKTREE_CLEANUP` policy semantics dropped

### Migration phase issues (sre-engineer, architect-reviewer, mahavishnu-specialist)
- Phase 0 force-push on `origin/main` unsafe as written
- Phase estimates too optimistic (4-5 days → realistically 7-10)
- Phase 3 ("migrate 83 misplaced worktrees") has no per-worktree safety check for active/uncommitted state
- Per-MCP `.venv/` deduplication should use `UV_PROJECT_ENVIRONMENT`
- `.venv/` dedup is orthogonal to CacheBackend abstraction

---

## Unique findings worth surfacing

| Reviewer | Finding |
|---|---|
| architect-reviewer | **Bundling is a transport, not a storage backend** — should be a `BundleTransport` decorator wrapping any backend |
| architect-reviewer | **Warm/Cold cache distinction is artificial** — both use Oneiric Local, only difference is arbitrary 100 MB threshold |
| redis-specialist | **Hot+non-regenerable category missing** — session metadata mid-transaction has no slot |
| sre-engineer | **Silent data loss risk for uncommitted changes** — `git bundle` doesn't capture dirty state (Failure Scenario F8) |
| sre-engineer | **Shared venv corruption = blast radius to all 24 MCP servers** (Failure Scenario F5) |
| sre-engineer | **`/tmp` filled on serverless** — 200-500ms estimate doesn't account for full tmp (F4) |
| api-security-specialist | **Bundle content integrity = implicit code execution** — most important finding the architecture reviewers missed |
| api-security-specialist | **Symlink-based venv migration = CVE surface** — recommend registry file over symlinks |
| python-pro | **`WorktreeHandle`/`WorktreeRef` polymorphism hand-waved** — implementer stalls on day 1 |
| python-pro | **Cancellation/atomicity contract missing** — bundle-then-clone has no rollback if cancelled |
| mahavishnu-specialist | **`worktree_backup.py`, `worktree_audit.py`, `worktree_session_registry.py` all have separate disk layouts not addressed** |
| mahavishnu-specialist | **`worktree_cli.py` and `worktree_tools.py` use `app.worktree_coordinator`, not `app.worktree_manager`** — Phase 1 wires into wrong class |
| oneiric-specialist | **Use `ResolverSettings.selections` instead of env vars** — Oneiric's resolver already does capability-based selection |
| oneiric-specialist | **`MultiTierCacheAdapter` already does L1+L2 with metrics** — headline benefit of §3 already exists |
| oneiric-specialist | **Serverless safety check should be in `LocalStorageAdapter.init()`**, not duplicated in every backend |
| mcp-integration-expert | **`worktree_manage` payload change is breaking** — needs v2.0.0 bump + deprecation entry in `DEPRECATED_TOOLS` |
| redis-specialist | **`KEYS prefix*` is a Redis footgun** — use `SCAN MATCH` with cursor |

---

## Recommended path forward

The ADR's strategic direction is sound. To get it ratifiable, three structural changes are needed:

**1. Restructure to extend, not duplicate.**
- Use Oneiric's existing cache adapters (`MultiTierCacheAdapter` covers L1+L2 already)
- Extend mahavishnu's existing `WorktreeProvider` ABC (add storage backends as new provider subclasses) rather than introducing parallel `WorktreeStorage` layer
- This eliminates Blockers 1, 3, 5, 6 and shrinks the scope considerably

**2. Add the concrete type definitions.**
- `WorktreeHandle`, `WorktreeRef`, `BundleTransport`, concrete backend classes
- `@runtime_checkable` Protocol + `@dataclass(frozen=True, slots=True)`
- Add `__aenter__`/`__aexit__`, `health()`, `exists()`, `lock()` to the Protocols
- Unblocks Phase 1 implementation

**3. Add the operational layer before ratification.**
- SLOs (latency percentiles per backend, error budget, availability targets)
- Observability metrics with names + dashboards
- Rollback strategy per phase
- Runbooks for each failure mode (Redis down, S3 throttled, Dhara unreachable)

The cache-classification table reshuffle, the bundling-as-transport-not-backend reframe, the path-traversal/audit-preservation assertions, the bundle-integrity SHA-256 verification, and the WorktreePathValidator allow-list update are all fixable in revision v2 without re-architecting.

---

## Per-reviewer detailed findings

The full per-reviewer reports are available as subagent JSONL transcripts (do not read inline — they overflow context). The structured findings above are the synthesis; per-agent detailed reports are preserved in the dispatch tool's task output paths for the maintainer's reference if a specific lens needs deeper drilling.

---

## Files

- ADR under review: `/Users/les/Projects/mahavishnu/.claude/worktrees/adr-015-worktree-and-cache-storage/docs/adr/015-worktree-and-cache-storage.md` (v1)
- This review: `/Users/les/Projects/mahavishnu/.claude/worktrees/adr-015-worktree-and-cache-storage/docs/adr/015-multi-agent-review.md`
- v2 (revision incorporating BLOCKER fixes): `/Users/les/Projects/mahavishnu/.claude/worktrees/adr-015-worktree-and-cache-storage/docs/adr/015-worktree-and-cache-storage-v2.md`

---

**END OF ADR 015 MULTI-AGENT REVIEW**
