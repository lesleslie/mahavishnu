---
status: draft
role: implementation
kind: plan
date: 2026-09-27
last_reviewed: 2026-09-27
topic: shared-oneiric-substrate-phase-c
---

# Phase C: Cold Consolidation (Akosha + SB) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Consolidate both components' cold-tier storage on `oneiric.adapters.storage.{gcs,s3,azure}` with a shared R2 bucket and per-component prefix ACL.

**Architecture:** Add `oneiric.adapters.storage.acl.PrefixACL` (declarative allowlist of `component_name → allowed_prefixes[]`). Akosha's `ColdStore` (`akosha/storage/cold_store.py:29`) delegates to oneiric adapters directly (drops bespoke wrapper). SB deletes the legacy S3-only `session_buddy/storage/cloud_sync.py`; the newer `session_buddy/adapters/storage_oneiric.py` (already wired for GCS via `GCSStorageOneiric`, commit `ef09475b`) becomes the only cold adapter for SB.

**Tech Stack:** Python 3.14, `oneiric.adapters.storage.{gcs,s3,local,azure}`, fakeredis-compatible ACL testing, pytest.

**Spec:** `docs/superpowers/specs/2026-09-27-shared-bodai-substrate-design.md` §6.3, §6.7 (Phase C1+C2).

## Global Constraints

Verbatim from spec §12:

- **Pre-1.0 replace, not deprecate** — `session_buddy/storage/cloud_sync.py` deleted in same commit that adopts `GCSStorageOneiric` everywhere.
- **Direct merge to main, no PRs**.
- **No `git push`** for bodai without explicit approval.
- **No version bumps** in any Bodai `pyproject.toml` — user does.
- **No `Co-Authored-By` trailer**.
- **Wire-up contract** per `.claude/decisions/wire-up-contract.md`.

## 1. Outcome

- `class ColdStore` (Akosha, `akosha/storage/cold_store.py:29`) delegates to `oneiric.adapters.storage.{gcs,s3,azure}` directly. The bespoke wrapper is gone.
- `session_buddy/storage/cloud_sync.py` DELETED.
- `GCSStorageOneiric` (`session_buddy/adapters/storage_oneiric.py:338`) is the only cold adapter for SB; all `cloud_sync` callers migrated.
- `oneiric.adapters.storage.acl.PrefixACL` enforces per-component prefix isolation in dev/test; production R2/S3/GCS policy binding happens at deployment time.
- `grep -rn "class ColdStore\|class CloudSync" akosha/ session_buddy/` returns zero hits post-Phase-C.

## 2. Goals

1. `PrefixACL` denies cross-prefix reads/writes by default.
2. Akosha cold writes land in R2 prefix `akosha/`.
3. SB cold writes land in R2 prefix `sb/`.
4. Round-trip test: SB writes `sb/object.parquet`; Akosha reads when admin-granted; data identical.
5. ACL test: SB token denied for `akosha/*`; admin token can read all.
6. OTel spans `cold.adapter.{gcs,s3}.put/get` with `prefix`, `object_key`, `bytes`, `compression`.

## 3. Non-Goals

- No warm-tier change (Phase B).
- No embedding change (Phase D).
- No settings layer (Phase E1).
- No multi-bucket topology (one shared bucket per spec §5.2).
- No R2/S3/GCS production policy YAML (deployment-time concern; PrefixACL enforces at runtime only).

## 4. Current Findings

- **Akosha cold wrapper**: `akosha/storage/cold_store.py` line 29 defines `class ColdStore`. Single file; S3/GCS/Azure via oneiric adapters under the hood.
- **SB has two surfaces**:
  - `session_buddy/storage/cloud_sync.py` — S3-only, lazy-imports `S3StorageAdapter` from oneiric at line 54. **Note (v5 corrects v4 wording)**: the legacy class is `class CloudSyncMethod(SyncMethod)` at **line 66** of `cloud_sync.py` — not `class CloudSync`. The grep `class CloudSync` in v4 Validation Matrix returned zero hits today; use `class CloudSyncMethod` (or `class CloudSyncMethod\|class CloudSync` for breadth). Module docstring falsely claims "S3/R2/MinIO" — no GCS support.
  - `session_buddy/adapters/storage_oneiric.py` line 338 (`class GCSStorageOneiric`) — added separately per commit `ef09475b`. NOT in `cloud_sync.py`.
- **No `akosha/storage/cloud_sync.py`** — the v1/v2 spec claim is fabricated (audit finding from v3 review).
- **R2 bucket**: shared at `oneiric-substrate-shared` (per spec §5.3).

## 5. Requirements

```yaml
requirements:
  - id: REQ-OSUB-C-001
    title: "oneiric.adapters.storage.acl.PrefixACL denies cross-prefix ops by default"
    dep: "Akosha → oneiric (PrefixACL); SB → oneiric (PrefixACL)"
  - id: REQ-OSUB-C-002
    title: "Akosha ColdStore delegates to oneiric.adapters.storage.{gcs,s3,azure} directly"
    dep: "Akosha → oneiric (storage adapters); drops Akosha wrapper"
  - id: REQ-OSUB-C-003
    title: "SB deletes session_buddy/storage/cloud_sync.py (legacy class `CloudSyncMethod`, line 66)"
    dep: "SB → oneiric (GCSStorageAdapter, commit ef09475b)"
  - id: REQ-OSUB-C-004
    title: "Cold round-trip: SB writes sb/*, Akosha reads with admin grant"
    dep: "SB → oneiric (GCSStorageAdapter + PrefixACL); Akosha → oneiric (GCSStorageAdapter)"
  - id: REQ-OSUB-C-005
    title: "Per-component prefix ACL: SB denied for akosha/*; admin can read all"
    dep: "Akosha → oneiric (PrefixACL); SB → oneiric (PrefixACL)"
  - id: REQ-OSUB-C-006
    title: "OTel span cold.adapter.{gcs,s3}.put/get with prefix + object_key + bytes + compression"
    dep: "Akosha → oneiric (OTel); SB → oneiric (OTel)"
```

## 6. Implementation Tasks

### Task 1: `PrefixACL` module in oneiric

**Files:**
- Create: `oneiric/adapters/storage/acl.py`
- Test: `oneiric/tests/test_acl_enforced.py` (new)

#### Integration Contract ← REQUIRED

- **Triggered from**: First cold-tier read/write across any component after Phase C ships.
- **Returns to**: `PermissionError` raised when `caller_namespace` is not in `allowed_prefixes` for the target prefix.
- **Demonstrable by**: `pytest oneiric/tests/test_acl_enforced.py -v` PASS — Akosha token denied for `sb/*`; SB token denied for `akosha/*`; admin token can read all.
- **Rollback signal**: SB or Akosha `/health` returns 503 with `feeds.cold_health == degraded`; ACL raises false positives.
- **Observability added**: OTel span `cold.acl.assert` with attributes `caller_namespace`, `target_prefix`, `allowed`.

- [ ] **Step 1: Write failing tests**:

```python
# oneiric/tests/test_acl_enforced.py
import pytest
from oneiric.adapters.storage.acl import PrefixACL

def test_default_deny_cross_prefix():
    acl = PrefixACL(caller="sb", allowed=["sb/*"])
    with pytest.raises(PermissionError):
        acl.assert_write(target="akosha/object.parquet")

def test_admin_can_read_all():
    acl = PrefixACL(caller="admin", allowed=["*"])
    acl.assert_read(target="sb/anything.parquet")  # no exception

def test_self_prefix_allowed():
    acl = PrefixACL(caller="akosha", allowed=["akosha/*"])
    acl.assert_write(target="akosha/x.parquet")  # no exception
```

- [ ] **Step 2: Run, expect failure** — `PrefixACL` doesn't exist.

- [ ] **Step 3: Implement `PrefixACL`** — minimal `assert_read(target)` and `assert_write(target)` methods; glob-style allowlist matching; OTel span on every assert.

- [ ] **Step 4: Re-run tests, expect pass**.

- [ ] **Step 5: Add `PrefixACL` integration helper for storage adapters** — `oneiric.adapters.storage.{gcs,s3}.*` accept an optional `acl: PrefixACL` constructor arg; default is admin-caller with `allowed=["*"]`.

- [ ] **Step 6: Commit**:

```bash
cd /Users/les/Projects/oneiric
git add oneiric/adapters/storage/acl.py oneiric/tests/test_acl_enforced.py
git commit -m "feat(oneiric): add PrefixACL for cold-tier cross-prefix isolation"
```

### Task 2: Akosha ColdStore delegates to oneiric storage adapters

**Files:**
- Modify: `akosha/storage/cold_store.py`
- Test: `akosha/tests/cold/test_prefix_acl.py` (new)

#### Integration Contract

- **Triggered from**: `mcp__akosha__create_backup` first call after Akosha restart.
- **Returns to**: cold writes land in shared R2 bucket at prefix `akosha/`.
- **Demonstrable by**: `grep -rn "class ColdStore" akosha/` returns zero hits; `pytest akosha/tests/cold/test_prefix_acl.py -v` PASS.
- **Rollback signal**: R2 5xx rate > 0.5%; `cold.compression` mismatch on read.
- **Observability added**: OTel span `cold.adapter.{gcs,s3}.put/get` with `prefix`, `object_key`, `bytes`, `compression` (from oneiric adapter side; Akosha's wrapper emits caller's namespace attribute).

- [ ] **Step 1: Write failing tests**:

```python
# akosha/tests/cold/test_prefix_acl.py
def test_akosha_cold_store_writes_to_akosha_prefix(monkeypatch):
    # Patch `oneiric.adapters.storage.gcs.GCSStorageAdapter.put` to a fixture.
    # Call Akosha cold store .write(...).
    # Assert fixture saw object_key starting with "akosha/".

def test_akosha_token_denied_for_sb_prefix():
    from oneiric.adapters.storage.acl import PrefixACL
    acl = PrefixACL(caller="akosha", allowed=["akosha/*"])
    with pytest.raises(PermissionError):
        acl.assert_read(target="sb/reflections.parquet")
```

- [ ] **Step 2: Run, expect failure**.

- [ ] **Step 3: Rewrite `akosha/storage/cold_store.py`** — replace bespoke `class ColdStore` body with a thin wrapper that:
  - constructs `GCSStorageAdapter` (or `S3StorageAdapter` per `SubstrateSettings.cold__backend`) with `prefix="akosha/"` and `acl=PrefixACL(caller="akosha", allowed=["akosha/*"])`
  - delegates `write/read/list` to the oneiric adapter
  - emits OTel caller-namespace attribute

- [ ] **Step 4: Run tests, expect pass**.

- [ ] **Step 5: Commit**:

```bash
cd /Users/les/Projects/akosha
git add akosha/storage/cold_store.py akosha/tests/cold/test_prefix_acl.py
git commit -m "refactor(akosha): ColdStore delegates to oneiric storage adapters"
```

### Task 3: SB deletes `cloud_sync.py` and migrates callers

**Files:**
- Delete: `session_buddy/storage/cloud_sync.py`
- Modify: callers of `cloud_sync` (find via `grep -rn "from session_buddy.storage.cloud_sync" session_buddy/`)
- Test: `session_buddy/tests/cold/test_prefix_acl.py` (new)

#### Integration Contract

- **Triggered from**: `mcp__session-buddy__backup` first call after SB restart.
- **Returns to**: cold writes land in shared R2 bucket at prefix `sb/`.
- **Demonstrable by**: `grep -rn "class CloudSyncMethod\|cloud_sync" session_buddy/storage/` returns zero hits (or only migration-shim hits); `pytest session_buddy/tests/cold/test_prefix_acl.py -v` PASS.
- **Rollback signal**: SB backup errors > 1% over 5 minutes; cold reads return mismatched compression.
- **Observability added**: OTel span `cold.adapter.{gcs,s3}.put/get` with `prefix="sb/"`.

- [ ] **Step 1: Find all callers of `cloud_sync`** — `grep -rn "from session_buddy.storage.cloud_sync\|cloud_sync\." session_buddy/`.

- [ ] **Step 2: Write failing test**:

```python
def test_sb_token_denied_for_akosha_prefix():
    from oneiric.adapters.storage.acl import PrefixACL
    acl = PrefixACL(caller="sb", allowed=["sb/*"])
    with pytest.raises(PermissionError):
        acl.assert_read(target="akosha/embeddings.parquet")
```

- [ ] **Step 3: Run, expect failure** (caller still imports `cloud_sync`).

- [ ] **Step 4: Migrate every caller of `cloud_sync` to use `GCSStorageOneiric` directly** — the existing `session_buddy/adapters/storage_oneiric.py:GCSStorageOneiric` (line 338, commit `ef09475b`) is the replacement. Update import paths; preserve call-site signatures.

- [ ] **Step 5: Delete `session_buddy/storage/cloud_sync.py`**.

- [ ] **Step 6: Re-run tests, expect pass**.

- [ ] **Step 7: Commit**:

```bash
cd /Users/les/Projects/session-buddy
git add session_buddy/storage/cloud_sync.py session_buddy/ tests  # deletions + migration
git commit -m "refactor(session-buddy): remove S3-only cloud_sync; use GCSStorageOneiric"
```

### Task 4: Cross-component cold round-trip + ACL e2e

**Files:**
- Create: `tests/e2e/test_cold_tier_round_trip.py`
- Create: `tests/e2e/test_cold_acl_enforced.py`

#### Integration Contract ← REQUIRED (v5 addition; IC + Observability was missing on this task)

- **Triggered from**: CI e2e gate on every PR touching `oneiric/adapters/storage/{gcs,s3}.py` or component cold wrappers.
- **Returns to**: `tests/e2e/test_cold_tier_round_trip.py` proves SB-writes / Akosha-reads symmetry across shared R2 bucket (admin-granted); `tests/e2e/test_cold_acl_enforced.py` proves per-prefix isolation.
- **Demonstrable by**: `pytest tests/e2e/test_cold_tier_round_trip.py tests/e2e/test_cold_acl_enforced.py -v` PASS against local fake-S3 / fake-GCS endpoint.
- **Rollback signal**: false-positive ACL denial on a legitimate read (operator unbinds policy); `cold.compression` mismatch (operator confirms `SubstrateSettings.cold__compression`).
- **Observability added**: OTel spans `cold.adapter.{gcs,s3}.put` and `cold.adapter.{gcs,s3}.get` (already specced in Phase C Task 1 Observability row) plus `e2e.cold_round_trip.success`, `e2e.cold_acl.allow`, `e2e.cold_acl.deny` per `mcp-backend-wiring-discipline.md §3`.

- [ ] **Step 1: Write round-trip test**:

```python
def test_sb_writes_sb_prefix_akosha_reads_admin():
    # Setup: shared fake S3 endpoint.
    # SB writes object "sb/reflections.parquet".
    # Akosha, as admin, reads the same object.
    # Assert bytes identical.
```

- [ ] **Step 2: Write ACL test**:

```python
def test_per_component_prefix_enforced():
    # SB token attempts read on "akosha/embeddings.parquet" -> PermissionError.
    # Akosha token attempts read on "sb/reflections.parquet" -> PermissionError.
    # Admin reads both -> success.
```

- [ ] **Step 3: Run against local fake-S3** (Homebrew `fake-gcs-server` or LocalStack).

- [ ] **Step 4: Commit**:

```bash
cd /Users/les/Projects/mahavishnu
git add tests/e2e/test_cold_tier_round_trip.py tests/e2e/test_cold_acl_enforced.py
git commit -m "test: cold tier round-trip + ACL enforcement"
```

## 7. Required Code Changes

| File | Action | Phase task |
|---|---|---|
| `oneiric/adapters/storage/acl.py` | CREATE: PrefixACL | Task 1 |
| `oneiric/tests/test_acl_enforced.py` | CREATE | Task 1 |
| `akosha/storage/cold_store.py` | MODIFY: delegates to oneiric | Task 2 |
| `akosha/tests/cold/test_prefix_acl.py` | CREATE | Task 2 |
| `session_buddy/storage/cloud_sync.py` | DELETE (legacy class `CloudSyncMethod`, line 66) | Task 3 |
| `session_buddy/tests/cold/test_prefix_acl.py` | CREATE | Task 3 |
| `session_buddy/` (callers of `cloud_sync`) | MODIFY: import path updates | Task 3 |
| `tests/e2e/test_cold_tier_round_trip.py` | CREATE | Task 4 |
| `tests/e2e/test_cold_acl_enforced.py` | CREATE | Task 4 |

## 8. Validation Matrix

| Tool / Command | Expected outcome | Evidence |
|---|---|---|
| `grep -rn "class ColdStore\|class CloudSyncMethod" akosha/ session_buddy/` | zero hits | shell exit code 1 |
| `pytest oneiric/tests/test_acl_enforced.py akosha/tests/cold/test_prefix_acl.py session_buddy/tests/cold/test_prefix_acl.py -v` | all green | pytest exit 0 |
| `pytest tests/e2e/test_cold_tier_round_trip.py tests/e2e/test_cold_acl_enforced.py -v` | PASS | pytest exit 0 |
| `aws s3 ls s3://oneiric-substrate-shared/sb/ --profile sb-token` | lists SB archive files | shell output |
| `aws s3 ls s3://oneiric-substrate-shared/akosha/ --profile sb-token` | `AccessDenied` per ACL | shell exit code 1 |
| `crackerjack run -v` (oneiric + akosha + SB) | green | exit code 0 |

## 9. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| ACL false-positives block legitimate reads | Medium | Default-deny is correct per spec §5.2; admin grant covers cross-component reads; tests cover both directions |
| R2/S3/GCS policy binding out of sync with PrefixACL | Low | PrefixACL enforces at runtime (dev/test); production policy is deployment-time concern out of Phase C scope |
| SB callers exist that import `cloud_sync` symbols | Medium | Step 4 of Task 3 explicitly grep-and-migrate all callers before delete |
| OTel span cardinality from `cold.adapter.{gcs,s3}.{put/get}` | Low | Sample at low rate; per spec §10 ack |
| **(Meta, spec §10 #7) oneiric becomes a hard substrate dependency** | Medium | Phase C adds Akosha → oneiric (storage + PrefixACL); SB → oneiric (storage + PrefixACL). `oneiric>=<pinned>` to both `[project.dependencies]`; CI guard test. |
| **(Meta, spec §10 #8) Cross-component import direction violation** | Medium | Phase C adds Akosha→oneiric and SB→oneiric only. CI guard: `grep -rn "from mahavishnu\|import mahavishnu" akosha/ session_buddy/` returns zero hits. |
| **(Meta, spec §10 #9) Rollback complexity across 6 phases × 4 repos** | Low for Phase C | Phase C is pure-substitution + delete; rollback restores legacy Akosha wrapper and SB `cloud_sync.py`. |

## 10. Decision Rule

Phase C is complete when ALL of:

- All 4 tasks land as commits.
- `grep -rn "class ColdStore\|class CloudSync" akosha/ session_buddy/` returns zero hits.
- Round-trip and ACL e2e tests pass.
- Oneiric's `PrefixACL` shipped to PyPI (release-train gate per spec §6.7).
- `crackerjack run -v` green on oneiric + akosha + SB.

**Release-train gate**: oneiric `PrefixACL` published + Akosha green + SB green + ACL tests pass.

## References

- `docs/superpowers/specs/2026-09-27-shared-bodai-substrate-design.md` §6.3 — Phase C contract
- `oneiric/adapters/storage/{gcs,s3,local,azure}.py` — existing storage adapters
- `akosha/storage/cold_store.py:29` — `class ColdStore` (line targets for replacement)
- `session_buddy/storage/cloud_sync.py` — line-target for deletion
- `session_buddy/adapters/storage_oneiric.py:338` — `GCSStorageOneiric` (already shipped, commit `ef09475b`)
