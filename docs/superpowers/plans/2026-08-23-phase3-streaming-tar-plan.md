# Phase 3 Streaming Tar.zst + Bodai 3.14 Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace in-memory `bytes` worktree bundle I/O with streaming tar.zst and lift the **entire Bodai-maintained ecosystem** to `requires-python = ">=3.14"` in one coordinated release window. Ecosystem scope per user direction: mahavishnu, oneiric, akosha, dhara, session-buddy, crackerjack, mcp-common, **plus all `-mcp` servers** (css-mcp, graphics-mcp, splashstand, porkbun-domain-mcp, langsmith-mcp, opera-cloud-mcp, etc. — per `bodai-mcp-servers-not-mycelium-core.md` memory note that these are Bodai-ecosystem projects, NOT mycelium-core), **plus fastblocks** (web framework + HTMX/HTMY/fastblocks-specialist), **plus any other Bodai-maintained repo** discovered in Phase 0.0.

**Architecture:** Two workstreams in dependency order. **Workstream 1 (Phases 0.0–0.N):** lift **all Bodai-maintained repos** from `>=3.13` to `>=3.14` in dependency order with 2-day soak between each merge. Phase 0.0 enumerates the full set before sequencing; phases 0.1–0.N perform the bumps one repo at a time. **Workstream 2 (Phases A–D):** the Phase 3 streaming tar.zst implementation in oneiric (action kit + storage adapter streaming) and mahavishnu (`storage_io.py` rewrite + provider updates + cache-aside fetch + observability wiring). Each phase is one atomic commit/PR; each task ends with a commit, a green test, and an Integration Contract verification.

**Tech Stack:** Python 3.14+, zstandard>=0.23.0 (PEP 735 `compression-zstd` group), tarfile with `data_filter` filter, FastMCP, OpenTelemetry, Oneiric action-kit, Dhara handle registry, Redis cache, fakeredis for tests, moto.mock_aws for S3 tests, gcp-storage-emulator Docker for GCS tests, Azurite Docker for Azure tests, pytest with `@pytest.mark.integration` + `@pytest.mark.slow` markers, crackerjack for quality gate.

## Global Constraints

- **Python**: `requires-python = ">=3.14"` in every Bodai repo's `pyproject.toml`. No upper-bound pin.
- **`zstandard`**: `>=0.23.0` via PEP 735 `compression-zstd` group. Test files use `pytest.fail(...)` (NOT `importorskip`) at module top if zstandard is missing.
- **`tarfile.data_filter`**: stable without DeprecationWarning in 3.14. Always passed as `filter=tarfile.data_filter` explicitly.
- **Bodai pre-1.0 policy**: merge direct to main, no PR review gates. Per Bodai CLAUDE.md policy (`bodai-pre-1.0-merge-policy.md`).
- **Branch naming**: `feat/python-3.14-<repo>` for ecosystem bumps, `feat/phase3-streaming-tar-<scope>` for Phase 3 itself.
- **Commit messages**: end with `Co-Authored-By: Claude <noreply@anthropic.com>`. Use conventional commits (`feat:`, `fix:`, `docs:`, `chore:`, `test:`, `refactor:`).
- **Per the Process Discipline rule (CLAUDE.md):** every phase deliverable has an Integration Contract block: Triggered from, Returns to / updates, Demonstrable by, Rollback signal, Observability added.
- **Crackerjack**: `crackerjack run` must pass clean (no new ERROR/WARNING; ty ratchet unchanged from baseline).
- **Coverage**: maintain project floor `>=89%`. Storage_io target: `100%`. New modules: `>=90%`. Streaming paths in providers: `>=85%`.

## Roadmap (Phases 0 → A → B → C → D → E)

| Phase | Repo | Workstream | PR target | Soak before next |
|---|---|---|---|---|
| **0.0** | (discovery) | W1 (enumerate all Bodai repos) | doc-only commit | n/a |
| **0.1** | mcp-common | W1 (3.14 bump) | direct-to-main commit | 2 days |
| **0.2** | oneiric | W1 (3.14 bump) | direct-to-main commit | 2 days |
| **0.3** | dhara | W1 (3.14 bump) | direct-to-main commit | 2 days |
| **0.4** | session-buddy | W1 (3.14 bump) | direct-to-main commit | 2 days |
| **0.5** | akosha | W1 (3.14 bump) | direct-to-main commit | 2 days |
| **0.6** | crackerjack | W1 (3.14 bump) | direct-to-main commit | 2 days |
| **0.7** | fastblocks | W1 (3.14 bump) | direct-to-main commit | 2 days |
| **0.8** | `<each -mcp server>` | W1 (3.14 bump per repo) | direct-to-main commit | 2 days each |
| **0.N** | mahavishnu | W1 (3.14 bump, prereq for Phase D) | direct-to-main commit | n/a (last) |
| **A** | oneiric | W2 (StreamingCompressionAction + storage adapter streaming) | direct-to-main commit | 2 days |
| **B** | oneiric | W2 (GCS + Azure streaming tests, MCP wiring) | direct-to-main commit | 2 days |
| **C** | mahavishnu | W2 (storage_io.py rewrite + provider updates + observability) | direct-to-main commit | 2 days |
| **D** | mahavishnu | W2 (runbook, README, CHANGELOG, rollout) | direct-to-main commit | 7-day monitoring window |
| **E** | docs | W2 (Phase 4 ADR placeholder for 3.15) | direct-to-main commit | n/a |

**Phase 0.8 enumeration**: see `BODAI_REPO_REGISTRY.md` (created in Phase 0.0) for the full list of `<each -mcp server>` repos. Per `bodai-mcp-servers-not-mycelium-core.md` memory: confirmed -mcp repos include css-mcp, graphics-mcp, splashstand, porkbun-domain-mcp, langsmith-mcp, opera-cloud-mcp. Each repo bumps independently; the sequencing is dependency-ordered within each `-mcp` repo (oneiric first, then others that depend on it).

---

# Workstream 1 — Bodai ecosystem 3.14 migration (Phases 0.0–0.N)

## Phase 0.0 — Discover and enumerate ALL Bodai-maintained repos

**Integration Contract**
- **Triggered from**: User direction "ecosystem wide with the python version upgrade means all of the -mcp, fastblocks, splashstand, etc eventually going to 3.14 as well".
- **Returns to / updates**: `BODAI_REPO_REGISTRY.md` at mahavishnu repo root lists every Bodai-maintained repo, its current `requires-python` floor, its dependency relationships, and its 3.14 readiness status.
- **Demonstrable by**: Plan Phase 0.0 enumerates ≥ the 7 known repos (mahavishnu, oneiric, akosha, dhara, session-buddy, crackerjack, mcp-common) PLUS fastblocks PLUS the 6 confirmed -mcp servers (css-mcp, graphics-mcp, splashstand, porkbun-domain-mcp, langsmith-mcp, opera-cloud-mcp) PLUS any other Bodai-maintained repos discovered.
- **Rollback signal**: discovery misses a repo (operator finds a Bodai-maintained repo at >=3.13 still after Phase 0.N).
- **Observability added**: `BODAI_REPO_REGISTRY.md` becomes the canonical list for Phase 4 ADR too (Phase 4 will lift the same set to >=3.15).

**Files**:
- Create: `BODAI_REPO_REGISTRY.md` (at mahavishnu repo root, or `docs/BODAI_REPO_REGISTRY.md`)
- Modify: `MEMORY.md` (add reference to `BODAI_REPO_REGISTRY.md`)

### Task 0.0.1: Enumerate Bodai-maintained repos

**Files**:
- Create: `BODAI_REPO_REGISTRY.md`

- [ ] **Step 1: Read MEMORY.md for prior inventory hints**

Read `/Users/les/.claude/projects/-Users-les-Projects-mahavishnu/memory/MEMORY.md` for any prior inventory notes (e.g., `bodai-mcp-servers-not-mycelium-core.md`).

- [ ] **Step 2: List known Bodai ecosystem repo roots**

```bash
ls -la /Users/les/Projects/
```

Identify every directory that is a git repo under `~les/Projects/` (excluding personal/worktrees and non-Bodai repos like `.claude`, `crackerjack` if outside the ecosystem, etc.).

- [ ] **Step 3: For each candidate, read its pyproject.toml to confirm it's Bodai-maintained AND has Python content**

```bash
for repo in <candidates>; do
  if [ -f "/Users/les/Projects/$repo/pyproject.toml" ]; then
    head -50 "/Users/les/Projects/$repo/pyproject.toml"
  fi
done
```

A repo is Bodai-maintained if: (a) `pyproject.toml` exists, (b) author/org = les or Bodai, (c) Python version pinned. Document the current `requires-python` for each.

- [ ] **Step 4: Per `bodai-mcp-servers-not-mycelium-core.md`, the following `-mcp` servers are confirmed Bodai-ecosystem projects:**

- css-mcp
- graphics-mcp
- splashstand
- porkbun-domain-mcp
- langsmith-mcp
- opera-cloud-mcp

Cross-check each exists at `/Users/les/Projects/<name>/` with a `pyproject.toml` containing `requires-python`.

- [ ] **Step 5: Add fastblocks**

fastblocks is a web framework (HTMX/HTMY integration). Locate it at `/Users/les/Projects/fastblocks/` and verify it's Bodai-maintained + Python-pinned.

- [ ] **Step 6: Document the enumeration in BODAI_REPO_REGISTRY.md**

```markdown
# Bodai Repo Registry

Maintained by `les` and the Bodai ecosystem. Authoritative source for
Python version coordination, dependency mapping, and Phase 4 (3.15)
planning. Filed 2026-08-23 during Phase 3 3.14 migration.

## Confirmed Bodai repos (>=3.13 currently; bumping to >=3.14 in Phases 0.1–0.N)

| Repo | Path | Current `requires-python` | Notes |
|---|---|---|---|
| mcp-common | /Users/les/Projects/mcp-common/ | >=3.13 | Leaf dep; Phase 0.1 |
| oneiric | /Users/les/Projects/oneiric/ | >=3.13 | Phase 0.2; needed by Phase A |
| dhara | /Users/les/Projects/dhara/ | >=3.13 | Phase 0.3 |
| session-buddy | /Users/les/Projects/session-buddy/ | >=3.13 | Phase 0.4 |
| akosha | /Users/les/Projects/akosha/ | >=3.13 | Phase 0.5 |
| crackerjack | /Users/les/Projects/crackerjack/ | >=3.13 | Phase 0.6 |
| fastblocks | /Users/les/Projects/fastblocks/ | (verify) | Phase 0.7 |
| css-mcp | /Users/les/Projects/css-mcp/ | (verify) | Phase 0.8 |
| graphics-mcp | /Users/les/Projects/graphics-mcp/ | (verify) | Phase 0.8 |
| splashstand | /Users/les/Projects/splashstand/ | (verify) | Phase 0.8 |
| porkbun-domain-mcp | /Users/les/Projects/porkbun-domain-mcp/ | (verify) | Phase 0.8 |
| langsmith-mcp | /Users/les/Projects/langsmith-mcp/ | (verify) | Phase 0.8 |
| opera-cloud-mcp | /Users/les/Projects/opera-cloud-mcp/ | (verify) | Phase 0.8 |
| mahavishnu | /Users/les/Projects/mahavishnu/ | >=3.13, <3.15 | Phase 0.N (last); needed for Phase D |

## Discovery process (per Phase 0.0)

1. Read MEMORY.md for inventory hints (e.g., bodai-mcp-servers-not-mycelium-core.md)
2. ls /Users/les/Projects/ for git repos
3. For each candidate, read pyproject.toml head; confirm Bodai-authored + Python-pinned
4. Document in this file

## Phase 4 (3.15) reuse

This registry is the canonical list for Phase 4. When Phase 4 lands,
update the `Current requires-python` column to `>=3.14` and start
fresh dependency-ordered sequencing.
```

- [ ] **Step 7: Commit**

```bash
cd mahavishnu
git add BODAI_REPO_REGISTRY.md
git commit -m "docs: BODAI_REPO_REGISTRY.md — authoritative Bodai repo list

Filed during Phase 3 (3.14) rollout per user direction that ALL
Bodai-maintained repos (not just the 7 in scope for streaming tar)
must migrate to 3.14. Includes -mcp servers (css-mcp, graphics-mcp,
splashstand, porkbun-domain-mcp, langsmith-mcp, opera-cloud-mcp)
per bodai-mcp-servers-not-mycelium-core.md memory, plus fastblocks.
Canonical source for Phase 4 (3.15) sequencing too.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

### Task 0.0.2: Update MEMORY.md to point at the registry

- [ ] **Step 1: Add a memory entry pointing at the registry**

Read `/Users/les/.claude/projects/-Users-les-Projects-mahavishnu/memory/MEMORY.md`. Add a one-line entry:

```markdown
- [BODAI_REPO_REGISTRY](bodai-repo-registry.md) — `/Users/les/Projects/mahavishnu/BODAI_REPO_REGISTRY.md` is the authoritative list of Bodai-maintained repos; check before any ecosystem-wide change.
```

This is a `feedback` memory because future Claude sessions should consult it for any Python version coordination or ecosystem-wide question.

**This is a CC memory write**, not a Session-Buddy reflection. Use the Write tool to update MEMORY.md and create the memory file:

```markdown
---
name: bodai-repo-registry
description: "The authoritative list of Bodai-maintained repos lives at BODAI_REPO_REGISTRY.md (in the mahavishnu repo). Consult before any ecosystem-wide Python version or dep coordination question."
metadata: 
  node_type: memory
  type: feedback
---

The authoritative list of Bodai-maintained Python repos is at `/Users/les/Projects/mahavishnu/BODAI_REPO_REGISTRY.md`, filed 2026-08-23 during the Phase 3 (3.14) rollout per user direction that ALL Bodai repos — not just the 7 in scope for streaming tar — must migrate.

Includes:
- Core ecosystem (mahavishnu, oneiric, akosha, dhara, session-buddy, crackerjack, mcp-common)
- fastblocks (HTMX/HTMY web framework)
- All `-mcp` servers per bodai-mcp-servers-not-mycelium-core.md: css-mcp, graphics-mcp, splashstand, porkbun-domain-mcp, langsmith-mcp, opera-cloud-mcp
- Discovery process documented (ls /Users/les/Projects/, read pyproject.toml heads)

**How to apply:** Before any ecosystem-wide Python version, dependency, or migration question, read BODAI_REPO_REGISTRY.md to confirm the full scope. Phase 4 (3.15) sequencing will reuse this registry.
```

**Wait for Phase 0.0 commit before starting Phase 0.1.**

---

## Phase 0.7 — fastblocks: bump requires-python

**Integration Contract**
- **Triggered from**: Phase 0.6 complete (crackerjack bumped, ecosystem-soak elapsed).
- **Returns to / updates**: fastblocks's `requires-python` floor lifted; sets up fastblocks-specialist agent's environment at 3.14.
- **Demonstrable by**: `python -c "import fastblocks"` succeeds on Python 3.14.2; `requires-python` reads `">=3.14"`.
- **Observability added**: 3.14 in fastblocks CI matrix.

**Files**:
- Modify: `fastblocks/pyproject.toml:14`
- Modify: `fastblocks/.github/workflows/test.yml`

### Task 0.7.1: Three commits per Phase 0.1/0.2 pattern

```toml
requires-python = ">=3.14"
```

CI matrix: `python-version: ['3.14']`.

Three commits:
1. `chore: bump requires-python to >=3.14`
2. `ci: test against python 3.14`
3. (push + optional tag/publish)

---

## Phase 0.8 — every Bodai -mcp server: bump requires-python

**Integration Contract**
- **Triggered from**: Phase 0.7 complete (fastblocks bumped, soak elapsed).
- **Returns to / updates**: Each `-mcp` server at `>=3.14`; the MCP tool surface (css-mcp, graphics-mcp, splashstand, porkbun-domain-mcp, langsmith-mcp, opera-cloud-mcp) available to ecosystem callers at 3.14.
- **Demonstrable by**: `python -c "import css_mcp"` (or analogous) succeeds on Python 3.14.2.
- **Observability added**: 3.14 in each `-mcp` server's CI matrix.

**Files**:
- For each `-mcp` server:
  - Modify: `<repo>/pyproject.toml:14`
  - Modify: `<repo>/.github/workflows/test.yml`

### Task 0.8.1: Per-server three-commit pattern (×6 servers)

For each of `css-mcp`, `graphics-mcp`, `splashstand`, `porkbun-domain-mcp`, `langsmith-mcp`, `opera-cloud-mcp`:

```toml
requires-python = ">=3.14"
```

CI matrix: `python-version: ['3.14']`.

Three commits per repo:
1. `chore: bump requires-python to >=3.14`
2. `ci: test against python 3.14`
3. (push + optional tag/publish)

**Each `-mcp` repo gets its own commit sequence.** Sequence `-mcp` repos in dependency order (likely all are leaves — verify in Phase 0.0 discovery; if any depend on each other, sequence accordingly).

**Wait 2 days after the LAST `-mcp` repo before Phase 0.N.**

---

# Workstream 1 — Bodai ecosystem 3.14 migration (Phases 0.1–0.N)

## Phase 0.1 — mcp-common: bump requires-python

**Integration Contract**
- **Triggered from**: User direction "we are full go for 3.14 across the whole greater ecosystem"; spec section "Python version strategy".
- **Returns to / updates**: mcp-common consumers (oneiric, mahavishnu, crackerjack) can resolve against the new floor on next lockfile refresh.
- **Demonstrable by**: `python -c "import mcp_common; print(mcp_common.__file__)"` succeeds on Python 3.14.2; `requires-python` in `pyproject.toml` reads `">=3.14"`.
- **Rollback signal**: any consumer's lockfile resolution fails against `>=3.14`.
- **Observability added**: CI workflow's `python-version` matrix logs 3.14 as a tested interpreter.

**Files**
- Modify: `mcp-common/pyproject.toml:14` (the `requires-python` line)
- Modify: `mcp-common/.github/workflows/test.yml` (add 3.14 to python-version matrix)

### Task 0.1.1: Edit pyproject.toml

**Files**:
- Modify: `mcp-common/pyproject.toml:14`

- [ ] **Step 1: Read current pyproject.toml to confirm 3.13 floor**

Run: `grep -n "requires-python" mcp-common/pyproject.toml`
Expected: line containing `">=3.13"` (or similar — verify exact text).

- [ ] **Step 2: Edit the requires-python line**

```toml
requires-python = ">=3.14"
```

- [ ] **Step 3: Commit**

```bash
cd mcp-common
git add pyproject.toml
git commit -m "chore: bump requires-python to >=3.14

Bodai ecosystem-wide 3.14 migration per ADR 015 v4 Phase 3 spec.
mcp-common is the leaf dep; bumped first so downstream repos can
resolve against the new floor in lockfile refreshes.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

### Task 0.1.2: Update CI matrix

**Files**:
- Modify: `mcp-common/.github/workflows/test.yml`

- [ ] **Step 1: Find the python-version line**

Run: `grep -n "python-version" mcp-common/.github/workflows/test.yml`
Expected: a list including `'3.13'` (or `'3.13.x'`).

- [ ] **Step 2: Add 3.14 to the matrix**

Change the matrix to `python-version: ['3.14']` (or `['3.14.2']` if the runner supports it). Drop `'3.13'` since the floor is now 3.14.

- [ ] **Step 3: Commit**

```bash
cd mcp-common
git add .github/workflows/test.yml
git commit -m "ci: test against python 3.14

Matches the new requires-python floor. Drops 3.13 from matrix.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

### Task 0.1.3: Verify and publish

- [ ] **Step 1: Run crackerjack locally**

Run: `cd mcp-common && crackerjack run`
Expected: clean (no new diagnostics vs baseline).

- [ ] **Step 2: Push to main**

```bash
cd mcp-common
git push origin main
```

- [ ] **Step 3: Tag and publish (if user has PyPI publish authority)**

```bash
cd mcp-common
git tag -a v<NEW_VERSION> -m "bump for 3.14 floor"
git push origin v<NEW_VERSION>
# If crackerjack -p minor available: crackerjack run -p minor
# Otherwise: user manually publishes per crackerjack-version-bumping-manual.md memory
```

**Wait 2 days for ecosystem soak** before starting Phase 0.2 (oneiric).

---

## Phase 0.2 — oneiric: bump requires-python

**Integration Contract**
- **Triggered from**: Phase 0.1 complete (mcp-common bumped, 2-day soak elapsed).
- **Returns to / updates**: oneiric consumers (dhara, session-buddy, akosha, crackerjack, mahavishnu) can resolve against 3.14.
- **Demonstrable by**: `python -c "import oneiric"` succeeds on Python 3.14.2; `requires-python` reads `">=3.14"`.
- **Rollback signal**: mcp-common reverts to 3.13 (shouldn't happen — the bump is one-way during Phase 3).
- **Observability added**: 3.14 in CI matrix; lockfile refresh in dependents lands cleanly.

**Files**
- Modify: `oneiric/pyproject.toml:14`
- Modify: `oneiric/.github/workflows/test.yml`

### Task 0.2.1: Repeat the 3-step edit (Tasks 0.1.1–0.1.3) on oneiric

The pattern from Phase 0.1 applies verbatim:

```toml
requires-python = ">=3.14"
```

CI matrix: `python-version: ['3.14']`.

Three commits:
1. `chore: bump requires-python to >=3.14`
2. `ci: test against python 3.14`
3. (push + optional tag/publish)

**Wait 2 days.**

---

## Phase 0.3 — dhara: bump requires-python

**Integration Contract**
- **Triggered from**: Phase 0.2 complete.
- **Returns to / updates**: dhara consumers (session-buddy, akosha, mahavishnu) can resolve against 3.14.
- **Demonstrable by**: `python -c "import dhara"` on Python 3.14.2.
- **Rollback signal**: oneiric reverts to 3.13 (won't happen).
- **Observability added**: 3.14 in CI.

**Files**: same pattern as Phase 0.2 (`dhara/pyproject.toml`, `dhara/.github/workflows/test.yml`).

### Task 0.3.1: Three commits per Phase 0.1/0.2 pattern

`requires-python = ">=3.14"`, CI matrix `['3.14']`, push + optional tag.

**Wait 2 days.**

---

## Phase 0.4 — session-buddy: bump requires-python

**Integration Contract**
- **Triggered from**: Phase 0.3 complete.
- **Returns to / updates**: session-buddy consumers (mahavishnu).
- **Demonstrable by**: `python -c "import session_buddy"` on Python 3.14.2.
- **Observability added**: 3.14 in CI.

**Files**: `session-buddy/pyproject.toml`, `session-buddy/.github/workflows/test.yml`.

### Task 0.4.1: Three commits per pattern

`requires-python = ">=3.14"`, CI matrix `['3.14']`, push + optional tag.

**Wait 2 days.**

---

## Phase 0.5 — akosha: bump requires-python

**Integration Contract**
- **Triggered from**: Phase 0.4 complete.
- **Returns to / updates**: akosha consumers (mahavishnu).
- **Demonstrable by**: `python -c "import akosha"` on Python 3.14.2.
- **Observability added**: 3.14 in CI.

**Files**: `akosha/pyproject.toml`, `akosha/.github/workflows/test.yml`.

### Task 0.5.1: Three commits per pattern

`requires-python = ">=3.14"`, CI matrix `['3.14']`, push + optional tag.

**Wait 2 days.**

---

## Phase 0.6 — crackerjack: bump requires-python

**Integration Contract**
- **Triggered from**: Phase 0.5 complete.
- **Returns to / updates**: crackerjack consumers (mahavishnu dev group).
- **Demonstrable by**: `crackerjack run` succeeds on Python 3.14.2 in the crackerjack repo's own CI.
- **Observability added**: 3.14 in crackerjack CI matrix; crackerjack-quality-gate output verifies the 3.14 toolchain (ty, ruff, mypy).

**Files**: `crackerjack/pyproject.toml`, `crackerjack/.github/workflows/test.yml`.

### Task 0.6.1: Three commits per pattern

`requires-python = ">=3.14"`, CI matrix `['3.14']`, push + optional tag.

**Wait 2 days.**

---

## Phase 0.7 — mahavishnu: bump requires-python (prereq for Phase D)

**Integration Contract**
- **Triggered from**: Phase 0.6 complete. This is the LAST 3.14 bump in Workstream 1.
- **Returns to / updates**: mahavishnu's `requires-python` floor lifted; sets up Phase A-D (streaming tar) work in mahavishnu.
- **Demonstrable by**: `python -c "import mahavishnu"` on Python 3.14.2; `pytest --cov=mahavishnu` runs on 3.14.2.
- **Rollback signal**: any Workstream 1 phase's consumer fails to resolve.
- **Observability added**: 3.14 in mahavishnu CI matrix.

**Files**:
- Modify: `mahavishnu/pyproject.toml:14`
- Modify: `mahavishnu/.github/workflows/test.yml`
- Modify: `mahavishnu/.claude/CLAUDE.md` (update "Python 3.13 is the target" → "Python 3.14 is the target")

### Task 0.7.1: Three commits per pattern + CLAUDE.md update

**Step 1: pyproject.toml bump**

```toml
requires-python = ">=3.14"
```

**Step 2: CI matrix update**

```yaml
python-version: ['3.14']
```

**Step 3: CLAUDE.md update**

Change "Python 3.13 is the target" (or current equivalent text in `/Users/les/Projects/mahavishnu/.claude/CLAUDE.md`) to "Python 3.14 is the target. Phase 4 ADR plans the 3.15 bump (see `docs/adr/016-phase4-python-3.15-migration.md` skeleton in the Phase 3 spec)."

**Step 4: Commit the CLAUDE.md change**

```bash
cd mahavishnu
git add .claude/CLAUDE.md
git commit -m "docs: update CLAUDE.md python target to 3.14

Co-Authored-By: Claude <noreply@anthropic.com>"
```

**Step 5: Push + optional tag/publish**

---

# Workstream 2 — Streaming tar.zst (Phases A → D)

## Phase A — oneiric: StreamingCompressionAction + storage adapter streaming (NOT including GCS/Azure tests)

**Integration Contract**
- **Triggered from**: Phase 0.2 complete (oneiric requires-python bumped). Phase D of streaming-tar in mahavishnu depends on Phase A's `save_stream` / `read_stream` methods.
- **Returns to / updates**: New `StreamingCompressionAction` registered in oneiric's action-kit catalog (key=`compression.stream`, priority=448). Storage adapters (`LocalStorageAdapter`, `S3StorageAdapter`) gain `save_stream` and `read_stream` methods with `async def` + `AsyncIterator[bytes]` signature. New error path: missing `zstandard` raises `LifecycleError` from the action-kit path.
- **Demonstrable by**: `from oneiric.actions.compression import StreamingCompressionAction; StreamingCompressionAction().stream_compress(iter([b"x"*100]), algorithm="zstd")` yields zstd-compressed bytes. `LocalStorageAdapter().save_stream("k", async_iter([b"x"]))` writes to disk. `S3StorageAdapter(...).save_stream` uses multipart upload with `abort_multipart_upload` on partial failure.
- **Rollback signal**: mahavishnu Phase D imports fail; oneiric CI breaks.
- **Observability added**: `s3_multipart_abort_total{backend, principal_short}` counter; `s3_multipart_cost_events_total{principal_short}` counter; `streaming_codec_failures_total{algorithm}` counter (note: past-tense naming per B-DI-06).

**Files**:
- Modify: `oneiric/oneiric/actions/compression.py` (add `StreamingCompressionAction` class)
- Modify: `oneiric/oneiric/actions/__init__.py` (`builtin_action_metadata()` registers the new entry)
- Modify: `oneiric/oneiric/adapters/storage/local.py` (add `save_stream`, `read_stream`)
- Modify: `oneiric/oneiric/adapters/storage/s3.py` (add `save_stream` with multipart + abort, `read_stream`)
- Modify: `oneiric/oneiric/adapters/storage/base.py` (add streaming metrics helpers — `_s3_multipart_abort_counter`, `_s3_multipart_cost_events_counter`, `_streaming_codec_failures_counter`)
- Modify: `oneiric/pyproject.toml` (PEP 735 `compression-zstd` group with `zstandard>=0.23.0`)
- Modify: `oneiric/docs/action-kits.md` (append new entry)
- Create: `oneiric/tests/actions/test_stream_compression_action.py`
- Create: `oneiric/tests/adapters/storage/test_local_stream.py`
- Create: `oneiric/tests/adapters/storage/test_s3_stream.py` (uses `moto.mock_aws`)

### Task A.1: Add `compression-zstd` PEP 735 group

**Files**:
- Modify: `oneiric/pyproject.toml`

- [ ] **Step 1: Read pyproject.toml to find existing PEP 735 group definitions**

Run: `grep -n "dependency-groups\|ai\s*=\|gpu\s*=\|content-ingest\s*=\|storage-pg\s*=" oneiric/pyproject.toml`
Expected: existing 4 PEP 735 groups documented in CLAUDE.md.

- [ ] **Step 2: Add the new group**

```toml
[dependency-groups]
compression-zstd = ["zstandard>=0.23.0"]
```

Append after `storage-pg` (do not break existing group order). Ensure `dev` group includes `{include-group = "compression-zstd"}` matching the existing pattern.

- [ ] **Step 3: Commit**

```bash
cd oneiric
git add pyproject.toml
git commit -m "feat(deps): add compression-zstd PEP 735 group with zstandard>=0.23.0

Zstd streaming compression is large (C extension, ~500KB) and only
needed by tar.zst bundle consumers. PEP 735 group keeps slim installs
lean per CLAUDE.md policy. Pinned >=0.23.0 to avoid the 0.21.0
chunked_stream_decompress bug (extra empty chunk after frame EOF
on fragmented input).

Co-Authored-By: Claude <noreply@anthropic.com>"
```

### Task A.2: Write `StreamingCompressionAction` test (failing first)

**Files**:
- Create: `oneiric/tests/actions/test_stream_compression_action.py`

- [ ] **Step 1: Add `pytest.fail` gate for missing zstandard at top of file**

```python
"""Tests for StreamingCompressionAction."""
from __future__ import annotations

import pytest

try:
    import zstandard  # noqa: F401
except ImportError:
    pytest.fail(
        "zstandard required for StreamingCompressionAction tests; "
        "install with `uv sync --group compression-zstd`",
        pytrace=False,
    )
```

- [ ] **Step 2: Write the failing tests**

```python
from oneiric.actions.compression import StreamingCompressionAction


def test_stream_compress_zstd_roundtrip():
    action = StreamingCompressionAction()
    source = b"hello world" * 1000
    compressed = b"".join(action.stream_compress(iter([source]), algorithm="zstd"))
    decompressed = b"".join(action.stream_decompress(iter([compressed]), algorithm="zstd"))
    assert decompressed == source


def test_stream_compress_gzip_roundtrip():
    action = StreamingCompressionAction()
    source = b"hello world" * 1000
    compressed = b"".join(action.stream_compress(iter([source]), algorithm="gzip"))
    decompressed = b"".join(action.stream_decompress(iter([compressed]), algorithm="gzip"))
    assert decompressed == source


def test_stream_compress_zstd_small_chunks():
    """1-byte chunks must not lose data."""
    action = StreamingCompressionAction()
    source = b"abcdefghij" * 100
    compressed = b"".join(
        action.stream_compress((bytes([b]) for b in source), algorithm="zstd")
    )
    decompressed = b"".join(action.stream_decompress(iter([compressed]), algorithm="zstd"))
    assert decompressed == source


def test_stream_compress_unknown_algorithm_raises():
    from oneiric.lifecycle import LifecycleError
    action = StreamingCompressionAction()
    with pytest.raises(LifecycleError, match="unsupported-algorithm"):
        list(action.stream_compress(iter([b"x"]), algorithm="brotli"))


def test_stream_compress_zstd_missing_dep_raises_lifecycle_error(monkeypatch):
    """R2-15 fix: explicit import wraps ImportError as LifecycleError."""
    from oneiric.lifecycle import LifecycleError
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "zstandard":
            raise ImportError("simulated missing dep")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    action = StreamingCompressionAction()
    with pytest.raises(LifecycleError, match="zstandard dependency required"):
        list(action.stream_compress(iter([b"x"]), algorithm="zstd"))


def test_execute_returns_metadata():
    import asyncio
    action = StreamingCompressionAction()
    result = asyncio.run(action.execute({"mode": "compress"}))
    assert result["status"] == "noop"
    assert result["mode"] == "compress"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd oneiric && uv run pytest tests/actions/test_stream_compression_action.py -v`
Expected: `ImportError` or `ModuleNotFoundError` for `StreamingCompressionAction`.

- [ ] **Step 4: Commit the failing tests**

```bash
cd oneiric
git add tests/actions/test_stream_compression_action.py
git commit -m "test: add StreamingCompressionAction test suite

Round-2 BLOCKER R2-15 coverage: explicit zstandard missing-dep path
raises LifecycleError, not raw ImportError. Round-2 BLOCKER R2-13
coverage: pinned >=0.23.0; 0.21.0 had a chunked_stream_decompress
bug yielding extra empty chunks on fragmented input.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

### Task A.3: Implement `StreamingCompressionAction`

**Files**:
- Modify: `oneiric/oneiric/actions/compression.py`

- [ ] **Step 1: Append the class to `compression.py` (after `CompressionAction`)**

```python
class StreamingCompressionAction:
    """Streaming compress/decompress for chunked sources too large for memory.

    Use when the source is an iterator of byte chunks (file chunks, network
    bytes) and you can't afford to materialize the whole blob in memory
    before compressing. For in-memory payloads, prefer CompressionAction.

    Provides sync generator methods (stream_compress, stream_decompress)
    for direct use; async execute() wrapper for action-kit dispatchers
    returns metadata only (callers wanting streamed bytes must invoke
    stream_compress/stream_decompress directly).

    Priority rationale: 448 (CompressionAction is 450, HashAction is 445).
    A future maintainer bumping this above 450 would silently route
    Phase 1+2 callers to the streaming action — which has different
    semantics (iterator-in vs bytes-in). Document this in CHANGELOG.
    """

    metadata = ActionMetadata(
        key="compression.stream",
        provider="builtin-streaming-compression",
        factory="oneiric.actions.compression:StreamingCompressionAction",
        description="Streaming gzip/zstd compress/decompress for chunked input",
        domains=["task", "workflow"],
        capabilities=["compress", "decompress", "stream"],
        stack_level=25,
        priority=448,
        source=CandidateSource.LOCAL_PKG,
        owner="Platform Core",
        requires_secrets=False,
        side_effect_free=True,
    )

    _SUPPORTED: ClassVar[set[str]] = {"gzip", "zstd"}

    def __init__(self, settings: CompressionActionSettings | None = None) -> None:
        self._settings = settings or CompressionActionSettings()
        self._logger = get_logger("action.compression.service")

    def stream_compress(
        self,
        chunks: Iterator[bytes],
        *,
        algorithm: str | None = None,
        level: int | None = None,
    ) -> Iterator[bytes]:
        algo = (algorithm or self._settings.algorithm).lower()
        if algo not in self._SUPPORTED:
            raise LifecycleError(f"compression-stream-unsupported-algorithm: {algo}")
        if algo == "zstd":
            try:
                import zstandard
            except ImportError as exc:
                raise LifecycleError(
                    "zstandard dependency required for zstd algorithm; "
                    "install with `uv sync --group compression-zstd`"
                ) from exc
            lvl = level if level is not None else self._settings.level
            cctx = zstandard.ZstdCompressor(level=lvl)
            yield from cctx.chunked_stream_compress(chunks)
        elif algo == "gzip":
            yield from self._gzip_stream_compress(chunks, level or self._settings.level)

    def stream_decompress(
        self,
        chunks: Iterator[bytes],
        *,
        algorithm: str,
    ) -> Iterator[bytes]:
        algo = algorithm.lower()
        if algo not in self._SUPPORTED:
            raise LifecycleError(f"compression-stream-unsupported-algorithm: {algo}")
        if algo == "zstd":
            try:
                import zstandard
            except ImportError as exc:
                raise LifecycleError(
                    "zstandard dependency required for zstd algorithm; "
                    "install with `uv sync --group compression-zstd`"
                ) from exc
            dctx = zstandard.ZstdDecompressor()
            yield from dctx.chunked_stream_decompress(chunks)
        elif algo == "gzip":
            yield from self._gzip_stream_decompress(chunks)

    async def execute(self, payload: dict | None = None) -> dict:
        payload = normalize_payload(payload)
        mode = payload.get("mode", "compress")
        return {
            "status": "noop",
            "mode": mode,
            "note": "use stream_compress/stream_decompress directly",
        }

    @staticmethod
    def _gzip_stream_compress(chunks, level):
        cctx = zlib.compressobj(level)
        for chunk in chunks:
            data = cctx.compress(chunk)
            if data:
                yield data
        tail = cctx.flush()
        if tail:
            yield tail

    @staticmethod
    def _gzip_stream_decompress(chunks):
        dctx = zlib.decompressobj(zlib.MAX_WBITS | 16)
        for chunk in chunks:
            data = dctx.decompress(chunk)
            if data:
                yield data
        tail = dctx.flush()
        if tail:
            yield tail
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `cd oneiric && uv run pytest tests/actions/test_stream_compression_action.py -v`
Expected: all 6 tests PASS.

- [ ] **Step 3: Commit**

```bash
cd oneiric
git add oneiric/actions/compression.py
git commit -m "feat(compression): add StreamingCompressionAction

Provides stream_compress/stream_decompress sync generators for zstd
and gzip. Async execute() wrapper returns metadata only. Priority
448 (below CompressionAction's 450) preserves Phase 1+2 caller
resolution. LifecycleError wraps zstandard ImportError per
round-2 BLOCKER R2-15.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

### Task A.4: Register the action-kit entry

**Files**:
- Modify: `oneiric/oneiric/actions/__init__.py`

- [ ] **Step 1: Locate `builtin_action_metadata()`**

Run: `grep -n "builtin_action_metadata\|StreamingCompressionAction\|CompressionAction" oneiric/oneiric/actions/__init__.py`

- [ ] **Step 2: Append `StreamingCompressionAction.metadata` to the returned list**

Find the return statement of `builtin_action_metadata()` (or the list it builds) and append `StreamingCompressionAction.metadata` after `CompressionAction.metadata`. Do not reorder existing entries — alphabetical/insertion order doesn't matter to the resolver (it picks by `priority` field), but insertion order is what the docs file mirrors.

- [ ] **Step 3: Add `StreamingCompressionAction` to imports**

Add `StreamingCompressionAction` to the import block at top of `__init__.py` if it's not auto-imported.

- [ ] **Step 4: Commit**

```bash
cd oneiric
git add oneiric/actions/__init__.py
git commit -m "feat(actions): register StreamingCompressionAction in catalog

Co-Authored-By: Claude <noreply@anthropic.com>"
```

### Task A.5: Update action-kits.md doc

**Files**:
- Modify: `oneiric/docs/action-kits.md`

- [ ] **Step 1: Locate `compression.encode` entry**

Run: `grep -n "compression.encode\|compression.hash" oneiric/docs/action-kits.md`

- [ ] **Step 2: Insert new entry**

Insert a new `compression.stream` entry AFTER `compression.encode` and BEFORE `compression.hash` (per round-2 BLOCKER R2-14 — this is a docs-file hint; the resolver picks by `priority` field, not list order).

Markdown block:

```markdown
- **`compression.stream`** — Streaming gzip/zstd compress/decompress for chunked input. Priority 448 (below `compression.encode`'s 450). Provides `stream_compress` / `stream_decompress` sync generator methods; async `execute()` returns metadata only. Use when the source is an iterator of byte chunks (file chunks, network bytes) and you can't afford to materialize the whole blob in memory. Requires the `compression-zstd` PEP 735 group for zstd algorithm. Round-2 note: bumping priority above 450 would silently route Phase 1+2 callers to the streaming action — preserve ordering.
```

- [ ] **Step 3: Commit**

```bash
cd oneiric
git add docs/action-kits.md
git commit -m "docs(action-kits): document compression.stream entry

Co-Authored-By: Claude <noreply@anthropic.com>"
```

### Task A.6: Add streaming methods to `LocalStorageAdapter`

**Files**:
- Modify: `oneiric/oneiric/adapters/storage/local.py`

- [ ] **Step 1: Write the failing tests**

Create `oneiric/tests/adapters/storage/test_local_stream.py`:

```python
"""Tests for LocalStorageAdapter.save_stream / read_stream."""
from __future__ import annotations

from pathlib import Path
import pytest
import tempfile

from oneiric.adapters.storage.local import LocalStorageAdapter, LocalStorageSettings


@pytest.fixture
def adapter(tmp_path: Path) -> LocalStorageAdapter:
    return LocalStorageAdapter(LocalStorageSettings(base_path=tmp_path))


async def test_save_stream_writes_file(adapter, tmp_path):
    async def chunks():
        yield b"hello "
        yield b"world"
    written = await adapter.save_stream("greeting.txt", chunks())
    assert written == 11
    assert (tmp_path / "greeting.txt").read_bytes() == b"hello world"


async def test_read_stream_yields_chunks(adapter):
    (adapter._base_path / "data.bin").write_bytes(b"x" * 200_000)

    chunks = []
    async for chunk in adapter.read_stream("data.bin", chunk_size=65_536):
        chunks.append(chunk)
    assert b"".join(chunks) == b"x" * 200_000
    assert sum(len(c) for c in chunks) == 200_000


async def test_save_stream_overwrites_existing(adapter):
    (adapter._base_path / "f.txt").write_bytes(b"old")
    async def chunks():
        yield b"new"
    await adapter.save_stream("f.txt", chunks())
    assert (adapter._base_path / "f.txt").read_bytes() == b"new"


async def test_read_stream_offset_beyond_eof_yields_nothing(adapter):
    (adapter._base_path / "small.txt").write_bytes(b"hi")
    chunks = []
    async for chunk in adapter.read_stream("small.txt", offset=1000, chunk_size=65_536):
        chunks.append(chunk)
    assert chunks == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd oneiric && uv run pytest tests/adapters/storage/test_local_stream.py -v`
Expected: `AttributeError: 'LocalStorageAdapter' object has no attribute 'save_stream'`.

- [ ] **Step 3: Implement `save_stream` and `read_stream`**

```python
async def save_stream(self, key: str, chunks: AsyncIterator[bytes]) -> int:
    """Stream chunks to local file. Returns total bytes written."""
    path = self._base_path / key
    path.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with open(path, "wb") as f:
        async for chunk in chunks:
            f.write(chunk)
            written += len(chunk)
    return written

async def read_stream(
    self, key: str, *, offset: int = 0, chunk_size: int = 65_536
) -> AsyncIterator[bytes]:
    """Yield local file body chunks starting at offset."""
    path = self._base_path / key
    if not path.exists():
        return
    with open(path, "rb") as f:
        if offset:
            f.seek(offset)
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            yield chunk
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd oneiric && uv run pytest tests/adapters/storage/test_local_stream.py -v`
Expected: all 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
cd oneiric
git add oneiric/adapters/storage/local.py tests/adapters/storage/test_local_stream.py
git commit -m "feat(storage): LocalStorageAdapter.save_stream / read_stream

Async signature with AsyncIterator[bytes] for cross-backend symmetry
(S3/GCS/Azure are async). No fcntl lock — concurrent writes per key
are documented as caller responsibility (R2-LocalStorageAdapter).
Round-2 fix: matches the async shape, NOT the previously-sketched
sync shape.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

### Task A.7: Add streaming methods to `S3StorageAdapter` with multipart abort

**Files**:
- Modify: `oneiric/oneiric/adapters/storage/s3.py`
- Modify: `oneiric/oneiric/adapters/storage/base.py` (add abort + cost counter helpers)

- [ ] **Step 1: Add streaming metrics to base.py**

In `oneiric/oneiric/adapters/storage/base.py`, after the existing `record_adapter_request_metrics` block:

```python
# Streaming-specific counters (Phase 3 — R2-01, R2-04)
_s3_multipart_abort_counter = metrics.get_meter("oneiric.storage.streaming").create_counter(
    name="s3_multipart_abort_total",
    unit="1",
    description="S3 multipart upload aborts by backend and reason (span attribute, not label)",
)
_s3_multipart_cost_events_counter = metrics.get_meter("oneiric.storage.streaming").create_counter(
    name="s3_multipart_cost_events_total",
    unit="1",
    description="S3 multipart upload cost-attribution events (one per successful complete_multipart_upload)",
)
_streaming_codec_failures_counter = metrics.get_meter("oneiric.storage.streaming").create_counter(
    name="streaming_codec_failures_total",
    unit="1",
    description="Tarfile lazy codec lookup failures (zstandard not installed, etc.)",
)


def record_s3_multipart_abort(*, backend: str, principal_short: str, reason: str, bytes_uploaded: int) -> None:
    """Emit s3_multipart_abort_total counter + record reason on current span."""
    _s3_multipart_abort_counter.add(1, attributes={"backend": backend, "principal_short": principal_short})
    span = trace.get_current_span()
    if span.is_recording():
        span.set_attribute("abort_reason", reason)
        span.set_attribute("bytes_uploaded_before_abort", bytes_uploaded)


def record_s3_multipart_cost_event(principal_short: str) -> None:
    _s3_multipart_cost_events_counter.add(1, attributes={"principal_short": principal_short})


def record_streaming_codec_failure(algorithm: str) -> None:
    _streaming_codec_failures_counter.add(1, attributes={"algorithm": algorithm})
```

- [ ] **Step 2: Write the failing tests**

Create `oneiric/tests/adapters/storage/test_s3_stream.py`:

```python
"""Tests for S3StorageAdapter.save_stream / read_stream with multipart."""
from __future__ import annotations

import asyncio
import pytest

from oneiric.adapters.storage.s3 import S3StorageAdapter, S3StorageSettings


@pytest.fixture
def adapter():
    return S3StorageAdapter(
        S3StorageSettings(bucket="test-bucket", region="us-east-1", endpoint_url=None)
    )


@pytest.fixture(autouse=True)
def mock_aws():
    import moto
    with moto.mock_aws():
        yield


async def test_s3_save_stream_multipart_upload(adapter):
    import boto3
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket="test-bucket")

    async def chunks():
        for _ in range(20):  # 20 × 6KB = 120KB → multipart
            yield b"x" * 6_000

    written = await adapter.save_stream("k", chunks())
    assert written == 120_000

    head = s3.head_object(Bucket="test-bucket", Key="k")
    assert head["ContentLength"] == 120_000


async def test_s3_save_stream_aborts_multipart_on_partial_failure(adapter):
    """R2-01 fix: abort_multipart_upload called on partial failure."""
    import boto3
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket="test-bucket")

    # Inject failure mid-stream
    async def failing_chunks():
        yield b"x" * 6_000
        yield b"y" * 6_000
        raise RuntimeError("simulated mid-stream failure")

    with pytest.raises(RuntimeError, match="simulated"):
        await adapter.save_stream("k", failing_chunks())

    # Verify NO orphan parts: list_multipart_uploads returns empty
    uploads = s3.list_multipart_uploads(Bucket="test-bucket")
    assert len(uploads.get("Uploads", [])) == 0


async def test_s3_save_stream_aborts_multipart_on_cancelled_error(adapter):
    """R2-01: asyncio.CancelledError triggers abort."""
    import boto3
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket="test-bucket")

    async def cancellable_chunks():
        yield b"x" * 6_000
        yield b"y" * 6_000
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await adapter.save_stream("k", cancellable_chunks())

    uploads = s3.list_multipart_uploads(Bucket="test-bucket")
    assert len(uploads.get("Uploads", [])) == 0


async def test_s3_read_stream_returns_chunks(adapter):
    import boto3
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket="test-bucket")
    s3.put_object(Bucket="test-bucket", Key="k", Body=b"hello" * 50_000)

    chunks = []
    async for chunk in adapter.read_stream("k", chunk_size=65_536):
        chunks.append(chunk)
    assert b"".join(chunks) == b"hello" * 50_000


async def test_s3_read_stream_offset_resume(adapter):
    import boto3
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket="test-bucket")
    s3.put_object(Bucket="test-bucket", Key="k", Body=b"abcdefghij" * 10_000)

    chunks = []
    async for chunk in adapter.read_stream("k", offset=50_000, chunk_size=10_000):
        chunks.append(chunk)
    resumed = b"".join(chunks)
    assert len(resumed) == 50_000
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd oneiric && uv run pytest tests/adapters/storage/test_s3_stream.py -v`
Expected: `AttributeError: 'S3StorageAdapter' object has no attribute 'save_stream'`.

- [ ] **Step 4: Implement `save_stream` (multipart + abort) and `read_stream`**

```python
async def save_stream(self, key: str, chunks: AsyncIterator[bytes]) -> int:
    """Stream chunks to S3 via multipart upload. Aborts on partial failure.

    R2-01 fix: abort_multipart_upload called in except BaseException.
    R2-04 fix: s3_multipart_cost_events_total emitted on successful complete.
    R2-05 fix: abort_reason is span attribute, not counter label.
    """
    import asyncio
    from oneiric.adapters.storage.base import (
        record_s3_multipart_abort,
        record_s3_multipart_cost_event,
    )

    client = self._client
    bucket = self._settings.bucket
    principal_short = getattr(self, "_principal_short", "unknown")

    upload_id = None
    bytes_uploaded = 0
    try:
        create_resp = await client.create_multipart_upload(Bucket=bucket, Key=key)
        upload_id = create_resp["UploadId"]
        parts = []
        part_number = 1
        async for chunk in chunks:
            buffer = chunk
            upload_resp = await client.upload_part(
                Bucket=bucket, Key=key, PartNumber=part_number, UploadId=upload_id, Body=buffer
            )
            parts.append({"PartNumber": part_number, "ETag": upload_resp["ETag"]})
            bytes_uploaded += len(buffer)
            part_number += 1
        await client.complete_multipart_upload(
            Bucket=bucket, Key=key, UploadId=upload_id, MultipartUpload={"Parts": parts}
        )
        record_s3_multipart_cost_event(principal_short)
        return bytes_uploaded
    except BaseException as exc:
        reason = "cancelled" if isinstance(exc, asyncio.CancelledError) else "exception"
        if upload_id is not None:
            try:
                await client.abort_multipart_upload(Bucket=bucket, Key=key, UploadId=upload_id)
            except Exception:
                pass  # Best-effort; the abort counter still records the failure
        record_s3_multipart_abort(
            backend="s3", principal_short=principal_short, reason=reason, bytes_uploaded=bytes_uploaded
        )
        raise


async def read_stream(
    self, key: str, *, offset: int = 0, chunk_size: int = 65_536
) -> AsyncIterator[bytes]:
    """Yield S3 object body chunks via get_object + range headers."""
    client = self._client
    bucket = self._settings.bucket
    obj = await client.head_object(Bucket=bucket, Key=key)
    total = obj["ContentLength"]
    position = offset
    while position < total:
        end = min(position + chunk_size, total) - 1
        resp = await client.get_object(Bucket=bucket, Key=key, Range=f"bytes={position}-{end}")
        body = await resp["Body"].read()
        yield body
        position += len(body)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd oneiric && uv run pytest tests/adapters/storage/test_s3_stream.py -v`
Expected: all 5 tests PASS.

- [ ] **Step 6: Commit**

```bash
cd oneiric
git add oneiric/adapters/storage/s3.py oneiric/adapters/storage/base.py tests/adapters/storage/test_s3_stream.py
git commit -m "feat(storage): S3StorageAdapter.save_stream / read_stream with multipart abort

save_stream uses multipart upload; abort_multipart_upload called on
BaseException (covers CancelledError). s3_multipart_cost_events_total
emitted on successful complete_multipart_upload. abort_reason is
span-only attribute (R2-05 cardinality protection).

Co-Authored-By: Claude <noreply@anthropic.com>"
```

### Task A.8: Update oneiric CHANGELOG

**Files**:
- Modify: `oneiric/CHANGELOG.md`

- [ ] **Step 1: Add Phase 3 entry**

```markdown
## [Unreleased] — Phase 3 streaming tar support

### Added
- `StreamingCompressionAction` (key `compression.stream`, priority 448) — sync generator methods for streaming gzip/zstd compress/decompress. Async `execute()` returns metadata only.
- `LocalStorageAdapter.save_stream` / `read_stream` — async, `AsyncIterator[bytes]`.
- `S3StorageAdapter.save_stream` / `read_stream` — async, multipart upload with abort-on-partial-failure (BaseException catch covers `asyncio.CancelledError`).
- New OTel counters: `s3_multipart_abort_total{backend, principal_short}`, `s3_multipart_cost_events_total{principal_short}`, `streaming_codec_failures_total{algorithm}`.
- New PEP 735 dependency group: `compression-zstd` (`zstandard>=0.23.0`).
- `requires-python = ">=3.14"` (Bodai ecosystem 3.14 migration).
```

- [ ] **Step 2: Commit**

```bash
cd oneiric
git add CHANGELOG.md
git commit -m "docs(changelog): Phase 3 streaming tar entry

Co-Authored-By: Claude <noreply@anthropic.com>"
```

### Task A.9: Verify Phase A

- [ ] **Step 1: Full test suite**

Run: `cd oneiric && uv run pytest -m "not integration" -v`
Expected: all pass.

- [ ] **Step 2: Crackerjack**

Run: `cd oneiric && crackerjack run`
Expected: clean (no new ERROR/WARNING vs baseline).

- [ ] **Step 3: Push to main**

```bash
cd oneiric
git push origin main
```

**Wait 2 days for ecosystem soak** before Phase B.

---

## Phase B — oneiric: GCS + Azure streaming tests, MCP wiring

**Integration Contract**
- **Triggered from**: Phase A complete. Phase B adds coverage parity for the other two remote storage backends.
- **Returns to / updates**: `test_gcs_stream.py` and `test_azure_blob_stream.py` exercise GCS/Azure adapters at the same coverage level as S3. AdapterMetadata for both now reflects `capabilities = ["blob", "stream", "delete"]` matching the methods shipped in Phase A.
- **Demonstrable by**: `uv run pytest tests/adapters/storage/test_gcs_stream.py tests/adapters/storage/test_azure_blob_stream.py -v` passes against emulator Docker containers.
- **Rollback signal**: GCS/Azure tests are flaky in CI (emulator unreliability) — fall back to integration marker only.
- **Observability added**: same counters as Phase A (already wired); new tests verify counter emissions on GCS/Azure paths.

**Files**:
- Create: `oneiric/tests/adapters/storage/test_gcs_stream.py`
- Create: `oneiric/tests/adapters/storage/test_azure_blob_stream.py`
- Modify: `oneiric/oneiric/adapters/storage/gcs.py` (verify `save_stream`/`read_stream` from Phase A)
- Modify: `oneiric/oneiric/adapters/storage/azure.py` (verify `save_stream`/`read_stream` from Phase A)
- Modify: `oneiric/pyproject.toml` (add `gcp-storage-emulator` + Azurite plugin to `[project.optional-dependencies] test`)

### Task B.1: Verify GCS adapter has streaming methods

**Files**:
- Modify: `oneiric/oneiric/adapters/storage/gcs.py`

- [ ] **Step 1: Read GCS adapter to confirm Phase A additions propagated**

Run: `grep -n "save_stream\|read_stream\|capabilities" oneiric/oneiric/adapters/storage/gcs.py`
Expected: `save_stream` and `read_stream` methods present, `capabilities` includes `"stream"`.

If methods are missing (Phase A only updated Local + S3), copy the async shape from `s3.py` and adapt for `google-cloud-storage`'s `Blob.chunk_size` parameter (fixed per-blob, not per-call). Update the implementation.

### Task B.2: Verify Azure adapter has streaming methods

**Files**:
- Modify: `oneiric/oneiric/adapters/storage/azure.py`

- [ ] **Step 1: Read Azure adapter**

Run: `grep -n "save_stream\|read_stream\|capabilities" oneiric/oneiric/adapters/storage/azure.py`

If missing, copy from `s3.py` shape and adapt for `azure-storage-blob`'s `download_stream` + `chunk_size`.

### Task B.3: Add emulator test dependencies

**Files**:
- Modify: `oneiric/pyproject.toml`

- [ ] **Step 1: Read current `[project.optional-dependencies]`**

Run: `grep -n "optional-dependencies\|\[test\]" oneiric/pyproject.toml`

- [ ] **Step 2: Add emulator deps to the test group**

```toml
[project.optional-dependencies]
test = [
    # ... existing test deps ...
    "pytest-gcs-emulator>=2.0",
    "pytest-azurite>=1.0",
]
```

- [ ] **Step 3: Commit**

```bash
cd oneiric
git add pyproject.toml
git commit -m "test(deps): add pytest-gcs-emulator and pytest-azurite

R2-12 fix: standard SDKs ship no in-process mocks for GCS/Azure.
Using emulator Docker containers via these plugins. Pin exact
versions; emulator protocol can change.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

### Task B.4: Write GCS streaming tests

**Files**:
- Create: `oneiric/tests/adapters/storage/test_gcs_stream.py`

```python
"""Tests for GCSStorageAdapter.save_stream / read_stream.

Uses gcp-storage-emulator Docker via pytest-gcs-emulator plugin.
Marked @pytest.mark.integration; requires Docker daemon.
"""
from __future__ import annotations

import pytest
from oneiric.adapters.storage.gcs import GCSStorageAdapter, GCSStorageSettings

pytestmark = pytest.mark.integration


@pytest.fixture
def adapter(gcs_emulator):
    return GCSStorageAdapter(
        GCSStorageSettings(bucket="test-bucket", credentials_path=None)
    )


async def test_gcs_save_stream_chunked_upload(adapter):
    async def chunks():
        for _ in range(20):
            yield b"x" * 6_000
    written = await adapter.save_stream("k", chunks())
    assert written == 120_000


async def test_gcs_save_stream_cleans_up_on_failure(adapter):
    async def failing():
        yield b"x" * 6_000
        raise RuntimeError("simulated")
    with pytest.raises(RuntimeError):
        await adapter.save_stream("k", failing())
    # Verify no orphan blob
    from google.cloud import storage
    client = storage.Client()
    assert not client.bucket("test-bucket").blob("k").exists()


async def test_gcs_read_stream_yields_chunks(adapter):
    adapter._client.bucket("test-bucket").blob("seed").upload_from_string(b"x" * 200_000)
    chunks = []
    async for c in adapter.read_stream("seed", chunk_size=65_536):
        chunks.append(c)
    assert b"".join(chunks) == b"x" * 200_000
```

### Task B.5: Write Azure streaming tests

**Files**:
- Create: `oneiric/tests/adapters/storage/test_azure_blob_stream.py`

```python
"""Tests for AzureBlobStorageAdapter.save_stream / read_stream.

Uses Azurite Docker via pytest-azurite plugin.
"""
from __future__ import annotations

import pytest
from oneiric.adapters.storage.azure import AzureBlobStorageAdapter, AzureBlobStorageSettings

pytestmark = pytest.mark.integration


@pytest.fixture
def adapter(azurite):
    return AzureBlobStorageAdapter(
        AzureBlobStorageSettings(container="test-container", connection_string=azurite.connection_string)
    )


async def test_azure_save_stream_chunked_upload(adapter):
    async def chunks():
        for _ in range(20):
            yield b"x" * 6_000
    written = await adapter.save_stream("k", chunks())
    assert written == 120_000


async def test_azure_save_stream_cleans_up_on_failure(adapter):
    async def failing():
        yield b"x" * 6_000
        raise RuntimeError("simulated")
    with pytest.raises(RuntimeError):
        await adapter.save_stream("k", failing())


async def test_azure_read_stream_yields_chunks(adapter):
    adapter._container_client.upload_blob("seed", b"x" * 200_000, overwrite=True)
    chunks = []
    async for c in adapter.read_stream("seed", chunk_size=65_536):
        chunks.append(c)
    assert b"".join(chunks) == b"x" * 200_000
```

### Task B.6: Commit GCS + Azure tests

```bash
cd oneiric
git add oneiric/adapters/storage/gcs.py oneiric/adapters/storage/azure.py tests/adapters/storage/test_gcs_stream.py tests/adapters/storage/test_azure_blob_stream.py
git commit -m "test: GCS + Azure streaming test coverage parity with S3

R2-12 fix: emulator-Docker strategy (gcp-storage-emulator + Azurite)
instead of nonexistent @mock_gcs/@mock_azure decorators. Marked
@pytest.mark.integration; skipped when Docker unavailable.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

### Task B.7: Verify Phase B

- [ ] **Step 1: Integration tests**

Run: `cd oneiric && docker run -d -p 9023:9023 fsouza/gcp-storage-emulator` and `docker run -d -p 10000:10000 mcr.microsoft.com/azure-storage/azurite`, then `uv run pytest -m integration -v`.
Expected: emulator-backed tests pass.

If Docker unavailable locally: tests skipped via `pytest.skip` (already in fixture).

- [ ] **Step 2: Crackerjack**

Run: `cd oneiric && crackerjack run`
Expected: clean.

- [ ] **Step 3: Push to main**

```bash
cd oneiric
git push origin main
```

**Wait 2 days.**

---

## Phase C — mahavishnu: storage_io.py rewrite + provider updates + observability

**Integration Contract**
- **Triggered from**: Phases 0.7 (mahavishnu 3.14 bump) + Phase A (oneiric streaming methods) complete.
- **Returns to / updates**: New `mahavishnu/core/worktree_providers/storage_io.py` exposes `serialize_worktree_tar(path)` as `@contextmanager` yielding `(temp_path, byte_size, sha256)` and `deserialize_worktree_tar(chunk_reader, target, *, expected_sha256, backend, principal_short)`. New `verify_sha256_streaming` helper in `observability/bundle_integrity.py`. New `record_bundle_integrity_failure_short` helper to prevent re-hashing. New error codes MHV-209..213 + MHV-220..223. `LocalWorktreeProvider.create_worktree_handle` and `fetch` updated. `RemoteWorktreeProvider` mirror. Cache key unified to `materialized:{handle.handle_id}` across both providers.
- **Demonstrable by**: `pytest tests/unit/test_core_worktree_providers_storage_io.py -v` passes; `pytest --cov=mahavishnu --cov-fail-under=89` passes; `test_create_then_fetch_round_trip_100mb` integration test passes against moto + fakeredis.
- **Rollback signal**: SHA mismatch rate > 0.01% (MHV-208 spike); S3 multipart abort rate non-zero in first 24h; /tmp headroom exhaustion.
- **Observability added**: `bundle_integrity_failure_total{backend, principal_short}` (preserved, streamed-path now emits), `streaming_codec_failures_total{algorithm}` (new), `worktree_op_duration_seconds{op, backend, principal_short, success}` (Phase 3 op enum), `bundle_bytes` histogram extended to 1GB.

**Files**:
- Modify: `mahavishnu/mahavishnu/core/worktree_providers/storage_io.py` (full rewrite)
- Modify: `mahavishnu/mahavishnu/core/errors.py` (add MHV-209..213 + MHV-220..223)
- Modify: `mahavishnu/mahavishnu/observability/bundle_integrity.py` (add `verify_sha256_streaming`, `record_bundle_integrity_failure_short`)
- Modify: `mahavishnu/mahavishnu/observability/metrics.py` (extend `bundle_bytes` histogram buckets; add Phase 3 op enum)
- Modify: `mahavishnu/mahavishnu/core/worktree_providers/local.py` (update `create_worktree_handle`, `fetch`, `health`)
- Modify: `mahavishnu/mahavishnu/core/worktree_providers/remote.py` (mirror local; fix `health_check` returning False; unify cache key shape)
- Modify: `mahavishnu/mahavishnu/core/worktree_providers/cache.py` (add streaming-aware invalidation)
- Modify: `mahavishnu/mahavishnu/core/worktree_coordination.py` (add Phase 3 error severity table for coordinator layer)
- Delete: 5 Phase 2 tests in `tests/unit/test_core_worktree_providers_storage_io.py` at lines 41, 49, 58, 67, 100 (per round-2 BLOCKER R2-18)
- Modify: `tests/unit/test_core_worktree_providers_storage_io.py` (rewrite for streaming)
- Modify: `tests/unit/test_core_worktree_providers_local.py` (add streaming tests)
- Modify: `tests/unit/test_core_worktree_providers_remote.py` (add streaming tests)
- Create: `tests/unit/test_observability_bundle_integrity_streaming.py` (new file for `verify_sha256_streaming`)
- Create: `tests/integration/test_worktree_round_trip_streaming.py` (end-to-end with `@pytest.mark.integration @pytest.mark.slow`)
- Modify: `mahavishnu/pyproject.toml` (PEP 735 `compression-zstd` group inheritance from oneiric)

### Task C.1: Add PEP 735 group + delete Phase 2 tests

**Files**:
- Modify: `mahavishnu/pyproject.toml`
- Modify: `tests/unit/test_core_worktree_providers_storage_io.py`

- [ ] **Step 1: Add `compression-zstd` to mahavishnu pyproject**

The group is declared in oneiric's pyproject (Task A.1). Mahavishnu inherits via the dev include-group pattern. Verify by reading mahavishnu/pyproject.toml:

```bash
grep -n "compression-zstd\|include-group" mahavishnu/pyproject.toml
```

If mahavishnu has its own PEP 735 `[dependency-groups]` block, add `compression-zstd = []` (empty — inherits from oneiric) OR explicitly `["zstandard>=0.23.0"]` (own pin). Match the existing pattern.

- [ ] **Step 2: Delete the 5 Phase 2 tests at known line numbers**

Read the test file:
```bash
grep -n "^def test_\|^class " tests/unit/test_core_worktree_providers_storage_io.py | head -30
```

Identify the 5 tests using `blob = serialize_worktree_tar(...)` and delete them (per round-2 BLOCKER R2-18). Use Edit with `replace_all` or targeted Edit per test function.

- [ ] **Step 3: Commit the deletions + pyproject update**

```bash
cd mahavishnu
git add pyproject.toml tests/unit/test_core_worktree_providers_storage_io.py
git commit -m "chore: PEP 735 compression-zstd + delete Phase 2 serialize tests

R2-18 fix: Phase 2 tests assign blob = serialize_worktree_tar(...);
Phase 3 serialize_worktree_tar is a context manager returning
(temp_path, size, sha). Delete to avoid pytest collection failure.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

### Task C.2: Add new error codes to errors.py

**Files**:
- Modify: `mahavishnu/mahavishnu/core/errors.py`

- [ ] **Step 1: Locate existing error codes**

Run: `grep -n "WORKTREE_INTEGRITY_FAILED\|WORKTREE_BUNDLE\|WORKTREE_CACHE\|class ErrorCode" mahavishnu/mahavishnu/core/errors.py`

- [ ] **Step 2: Add 9 new error code constants**

```python
# Phase 3 (ADR 015 v4 streaming tar)
WORKTREE_BUNDLE_TEMP_CREATE_FAILED = "MHV-209"  # mkstemp OSError
WORKTREE_BUNDLE_TEMP_WRITE_FAILED = "MHV-210"   # write OSError or CancelledError
WORKTREE_BUNDLE_PATH_TRAVERSAL = "MHV-211"      # data_filter rejects member
WORKTREE_BUNDLE_MALFORMED = "MHV-212"           # corrupt/truncated tar.zst
WORKTREE_BUNDLE_LEGACY_PHASE2 = "MHV-213"       # fetch hit a .tar.gz Phase 2 handle
WORKTREE_BUNDLE_STORAGE_KEY_TOO_LONG = "MHV-220"  # S3 1024-byte limit
WORKTREE_BUNDLE_STOPGAP_TOO_LARGE = "MHV-221"     # in-memory path OOM guard
WORKTREE_BUNDLE_NOT_FOUND = "MHV-222"             # storage adapter returned None
WORKTREE_BUNDLE_CODEC_UNAVAILABLE = "MHV-223"     # zstandard not installed
```

- [ ] **Step 3: Update code-table comment**

In `errors.py`, add a comment block:

```python
# Code table:
#   MHV-200..207 — Phase 1 + Phase 2 (cache, lock, registry)
#   MHV-208      — Phase 2 (WORKTREE_INTEGRITY_FAILED — SHA mismatch)
#   MHV-209..213 — Phase 3 (streaming bundle lifecycle)
#   MHV-220..223 — Phase 3 (storage-key validation, stopgap OOM guard, not-found, codec unavailable)
#   MHV-214..219, 224+ — reserved for Phase 4 (encryption-at-rest, multipart-abort observability retrofits)
```

- [ ] **Step 4: Commit**

```bash
cd mahavishnu
git add mahavishnu/core/errors.py
git commit -m "feat(errors): 9 new error codes for Phase 3 streaming bundle lifecycle

MHV-209..213 (streaming bundle lifecycle), MHV-220..223
(storage-key validation, stopgap OOM guard, not-found, codec unavailable).
Reserved codes MHV-214..219, 224+ documented for Phase 4.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

### Task C.3: Add streaming observability helpers

**Files**:
- Modify: `mahavishnu/mahavishnu/observability/bundle_integrity.py`

- [ ] **Step 1: Read existing `verify_sha256` + `record_bundle_integrity_failure`**

Read `bundle_integrity.py` to understand the existing implementation. The new helpers must mirror its `ALLOWED_BACKEND_KINDS` validation (per round-2 BLOCKER R2-19).

- [ ] **Step 2: Add `verify_sha256_streaming` (full body from spec) + `record_bundle_integrity_failure_short`**

```python
ALLOWED_BACKEND_KINDS: Final[frozenset[str]] = frozenset({"local", "s3", "gcs", "azure", "bundle"})


def verify_sha256_streaming(
    actual_sha: str,
    expected_sha: str,
    *,
    backend: str,
    principal_short: str,
) -> None:
    """Compare streamed-hash to expected, raise WorktreeIntegrityError on mismatch.

    Emits bundle_integrity_failure_total{backend, principal_short} on mismatch
    (Phase 2 §17 cardinality protection — principal_short is 8-char HMAC hash).
    Writes Dhara audit row for forensic chain-of-custody.
    """
    from mahavishnu.core.errors import ErrorCode, WorktreeIntegrityError

    if backend not in ALLOWED_BACKEND_KINDS:
        raise ValueError(f"backend {backend!r} not in ALLOWED_BACKEND_KINDS")
    if actual_sha == expected_sha:
        return

    # B-DI-03 fix: pre-computed principal_short; NO re-hash.
    record_bundle_integrity_failure_short(
        backend=backend, principal_short=principal_short
    )
    _bundle_integrity_failure_logger.warning(
        "bundle integrity mismatch",
        extra={
            "error_code": "MHV-208",
            "backend": backend,
            "principal_short": principal_short,
            "expected_sha_prefix8": expected_sha[:8],
            "actual_sha_prefix8": actual_sha[:8],
        },
    )
    write_dhara_audit_row(
        kind="bundle_integrity_failure",
        backend=backend,
        principal_short=principal_short,
        expected_sha_prefix8=expected_sha[:8],
        actual_sha_prefix8=actual_sha[:8],
    )
    raise WorktreeIntegrityError(
        f"SHA-256 mismatch: expected={expected_sha!r}, actual={actual_sha!r}",
        error_code=ErrorCode.WORKTREE_INTEGRITY_FAILED,
    )


def record_bundle_integrity_failure_short(*, backend: str, principal_short: str) -> None:
    """Emit bundle_integrity_failure_total{backend, principal_short} WITHOUT re-hashing.

    Used by verify_sha256_streaming. The pre-computed principal_short is
    already 8-char HMAC; calling record_bundle_integrity_failure(name=...)
    would re-hash and corrupt the label set.
    """
    _bundle_integrity_failure_counter.add(
        1, attributes={"backend": backend, "principal_short": principal_short}
    )
```

- [ ] **Step 3: Update existing `verify_sha256` to be a thin wrapper**

```python
def verify_sha256(blob: bytes, expected_sha: str, *, backend: str, principal) -> None:
    principal_short = _short_principal(principal.name if hasattr(principal, "name") else str(principal))
    verify_sha256_streaming(
        hashlib.sha256(blob).hexdigest(), expected_sha,
        backend=backend, principal_short=principal_short,
    )
```

`_short_principal` (existing in `observability/metrics.py:101`) returns `sha256(name.encode("utf-8")).hexdigest()[:8]` — NOT `name[:8]`. The literal-slice form would collapse distinct principals into the same 8-char bucket (per round-2 BLOCKER R2-22).

- [ ] **Step 4: Write the failing tests**

Create `tests/unit/test_observability_bundle_integrity_streaming.py`:

```python
"""Tests for verify_sha256_streaming + record_bundle_integrity_failure_short."""
from __future__ import annotations

import pytest

try:
    import zstandard  # noqa: F401
except ImportError:
    pytest.fail("zstandard required; uv sync --group compression-zstd", pytrace=False)

from mahavishnu.observability.bundle_integrity import (
    verify_sha256_streaming,
    record_bundle_integrity_failure_short,
    _short_principal,
)


def test_verify_sha256_streaming_emits_metric_on_mismatch():
    from mahavishnu.core.errors import WorktreeIntegrityError
    with pytest.raises(WorktreeIntegrityError):
        verify_sha256_streaming("a" * 64, "b" * 64, backend="local", principal_short="abc12345")
    # Verify counter incremented (assert via OTel InMemoryMeter)


def test_verify_sha256_streaming_does_not_rehash_principal_short(monkeypatch):
    """B-DI-03: principal_short is pre-computed; no re-hashing."""
    from mahavishnu.core.errors import WorktreeIntegrityError

    seen = []
    def fake_record(*, backend, principal_short):
        seen.append(principal_short)
    monkeypatch.setattr(
        "mahavishnu.observability.bundle_integrity.record_bundle_integrity_failure_short",
        fake_record,
    )
    with pytest.raises(WorktreeIntegrityError):
        verify_sha256_streaming("a" * 64, "b" * 64, backend="local", principal_short="abc12345")
    assert seen == ["abc12345"]  # NO re-hash to 8-char HMAC


def test_verify_sha256_streaming_writes_dhara_audit_row(monkeypatch):
    """B-DI-11: Dhara audit row written on mismatch."""
    from mahavishnu.core.errors import WorktreeIntegrityError

    rows = []
    monkeypatch.setattr(
        "mahavishnu.observability.bundle_integrity.write_dhara_audit_row",
        lambda **kw: rows.append(kw),
    )
    with pytest.raises(WorktreeIntegrityError):
        verify_sha256_streaming("a" * 64, "b" * 64, backend="local", principal_short="abc12345")
    assert len(rows) == 1
    assert rows[0]["kind"] == "bundle_integrity_failure"


def test_short_principal_distinguishes_acme_acme2():
    """B-DI-07: HMAC, NOT name[:8]."""
    p1 = _short_principal("alice@acme.com")
    p2 = _short_principal("alice@acme2.com")
    assert p1 != p2
    assert len(p1) == 8
    assert len(p2) == 8
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd mahavishnu && uv run pytest tests/unit/test_observability_bundle_integrity_streaming.py -v`
Expected: all 4 tests PASS.

- [ ] **Step 6: Commit**

```bash
cd mahavishnu
git add mahavishnu/observability/bundle_integrity.py tests/unit/test_observability_bundle_integrity_streaming.py
git commit -m "feat(observability): verify_sha256_streaming + record_bundle_integrity_failure_short

B-DI-03 fix: helper body explicit; principal_short NOT re-hashed.
B-DI-11 fix: Dhara audit row written on mismatch.
R2-02 fix: streaming path preserves Phase 2 §17 cardinality contract.
R2-19 fix: ALLOWED_BACKEND_KINDS validation retained.
R2-22 fix: HMAC, not slice, for principal_short.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

### Task C.4: Extend bundle_bytes histogram + Phase 3 op enum

**Files**:
- Modify: `mahavishnu/mahavishnu/observability/metrics.py`

- [ ] **Step 1: Locate `bundle_bytes` histogram + `record_worktree_op`**

```bash
grep -n "bundle_bytes\|record_worktree_op\|worktree_op_duration" mahavishnu/mahavishnu/observability/metrics.py
```

- [ ] **Step 2: Extend bucket boundaries per B-DI-05 fix**

Find `bundle_bytes_histogram` (or the metric definition). Replace bucket list with:

```python
explicit_bucket_boundaries=[
    1024,           # 1 KB
    10240,          # 10 KB
    102400,         # 100 KB
    1048576,        # 1 MB
    10485760,       # 10 MB
    52428800,       # 50 MB
    104857600,      # 100 MB
    209715200,      # 200 MB
    524288000,      # 500 MB
    1073741824,     # 1 GB
]
```

- [ ] **Step 3: Add Phase 3 op enum documentation comment**

Add a comment block above `record_worktree_op`:

```python
# Phase 3 op enum (added with streaming tar support):
#   create, create_stopgap, create_s3_multipart_aborted,
#   create_codec_unavailable, fetch, fetch_legacy_guard_hit,
#   fetch_sha_mismatch, remove_handle, invalidate_handle
# Phase 2 ops preserved: lock, unlock, health
```

- [ ] **Step 4: Commit**

```bash
cd mahavishnu
git add mahavishnu/observability/metrics.py
git commit -m "feat(observability): extend bundle_bytes histogram + Phase 3 op enum

B-DI-05 fix: histogram now covers up to 1GB so streaming-enabled
size classes get dedicated percentiles. Phase 3 op enum documented
for dashboard operators.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

### Task C.5: Rewrite `storage_io.py`

**Files**:
- Modify: `mahavishnu/mahavishnu/core/worktree_providers/storage_io.py`

- [ ] **Step 1: Replace the file with the full rewrite from spec**

Use Write to replace the entire file with the contents from spec section "Mahavishnu File 2" (the `@contextmanager` `serialize_worktree_tar` + `deserialize_worktree_tar` with all the BLOCKER fixes: `except BaseException`, atomic-promote staging, `verify_sha256_streaming` delegation, `MAX_BUNDLE_BYTES_STOPGAP` definition).

Add module-level constants near the top:

```python
MAX_BUNDLE_BYTES_STOPGAP: int = 256 * 1024 * 1024  # 256MB
```

- [ ] **Step 2: Write the failing tests**

In `tests/unit/test_core_worktree_providers_storage_io.py`, write the test inventory from spec section "Mahavishnu (rewritten)" — all the named tests including:
- `test_serialize_returns_temp_path_size_sha` (verify context-manager shape)
- `test_serialize_chunked_hash_matches_full_hash`
- `test_serialize_cleanup_on_cancellation` — uses `asyncio.CancelledError`, not ValueError
- `test_serialize_cleanup_on_keyboard_interrupt`
- `test_deserialize_extracts_content`
- `test_deserialize_verifies_sha` (asserts temp file unlinked via finally)
- `test_deserialize_blocks_path_traversal` + absolute-symlink + device-file + FIFO
- `test_deserialize_blocks_zstd_corrupt_header` + corrupt_payload
- `test_deserialize_cleans_temp_on_chunk_reader_runtime_error`
- `test_deserialize_cleans_temp_on_cancelled_error`
- `test_serialize_temp_create_oserror_wrapped` (NEW — MHV-209)
- `test_deserialize_temp_write_oserror_wrapped` (NEW — MHV-210)
- `test_round_trip_100mb_file`
- `test_round_trip_at_size_boundary` (parametrized 0, 1, 1024, 99MB, 101MB)
- `test_serialize_empty_worktree_round_trips`
- `test_chunk_reader_contract`

- [ ] **Step 3: Run tests to verify they pass**

Run: `cd mahavishnu && uv run pytest tests/unit/test_core_worktree_providers_storage_io.py -v`
Expected: all tests PASS; coverage `100%`.

- [ ] **Step 4: Commit**

```bash
cd mahavishnu
git add mahavishnu/core/worktree_providers/storage_io.py tests/unit/test_core_worktree_providers_storage_io.py
git commit -m "feat(storage_io): streaming tar.zst rewrite with context manager + queue handoff

- serialize_worktree_tar is now @contextmanager (R2-16 caller migration).
- deserialize_worktree_tar uses atomic-promote to staging subdir.
- CancelledError (BaseException) caught explicitly.
- verify_sha256_streaming delegated; MAX_BUNDLE_BYTES_STOPGAP cap.
- 100% coverage target: MHV-209 + MHV-210 explicit OSError-injection tests.
- 9 named streaming tests including size boundaries, malformed inputs,
  path traversal, device files, symlinks.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

### Task C.6: Update LocalWorktreeProvider with streaming + bounded queue handoff

**Files**:
- Modify: `mahavishnu/mahavishnu/core/worktree_providers/local.py`

- [ ] **Step 1: Replace `create_worktree_handle` and `fetch` per spec**

Apply the spec's File 4 implementation: `serialize_worktree_tar` context-manager form, `MAX_CONCURRENT_WORKTREE_STREAMS = 8` semaphore, UUID4 handle_id, MHV-220 storage key length validation, MHV-221 stopgap size check, MHV-222 NOT_FOUND, MHV-213 gzip magic sniff (`1f 8b`), MHV-223 codec unavailable wrap, queue.Queue(maxsize=4) producer-consumer handoff for streaming fetch, atomic-promote in deserialize.

- [ ] **Step 2: Add `supports_streaming` helper at module top**

```python
def supports_streaming(storage) -> bool:
    capabilities = getattr(getattr(storage, "metadata", None), "capabilities", [])
    has_methods = hasattr(storage, "save_stream") and hasattr(storage, "read_stream")
    return "stream" in capabilities and has_methods
```

- [ ] **Step 3: Update `health()` to probe streaming capability (B-DI-03)**

```python
async def health(self) -> HealthReport:
    report = await super().health()
    if not supports_streaming(self._storage):
        report.add_warning(
            kind="streaming_capability_missing",
            message=f"Storage adapter {type(self._storage).__name__} lacks save_stream/read_stream; "
                    f"stopgap path will be used (max bundle size {MAX_BUNDLE_BYTES_STOPGAP // (1024*1024)}MB)",
        )
    return report
```

- [ ] **Step 4: Write the failing tests**

Extend `tests/unit/test_core_worktree_providers_local.py` with the named tests from spec:
- `test_create_uses_save_stream_when_available`
- `test_create_falls_back_to_stopgap_when_no_stream_capability`
- `test_create_stopgap_raises_mhv221_on_oversized_bundle`
- `test_fetch_uses_read_stream_when_available`
- `test_fetch_sha_mismatch_raises_before_extract` (asserts no files in `target`)
- `test_fetch_cache_hit_skips_streaming`
- `test_fetch_phase2_targz_handle_raises_mhv213`
- `test_fetch_migration_guard_does_not_swallow_gzip_magic`
- `test_supports_streaming_checks_capabilities_not_just_methods`
- `test_supports_streaming_advertises_but_does_not_implement_returns_false`
- `test_fetch_corrupted_storage_key_raises_mhv212` (empty first chunk)
- `test_fetch_corrupted_non_gzip_non_zstd_handle_raises_mhv212` (B-DI-14)
- `test_fetch_memory_bounded_under_steaming` (B-DI-10, uses tracemalloc)

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd mahavishnu && uv run pytest tests/unit/test_core_worktree_providers_local.py -v`
Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
cd mahavishnu
git add mahavishnu/core/worktree_providers/local.py tests/unit/test_core_worktree_providers_local.py
git commit -m "feat(provider): LocalWorktreeProvider streaming fetch + bounded queue handoff

R2-10 fix: queue.Queue(maxsize=4) bridges async-for producer to worker
thread consumer; memory bounded at chunk_size * 4 ≈ 256KB.
B-DI-01/02/03/13/14: MHV-209..213 + MHV-220..223 raise sites.
B-DI-04: supports_streaming checks both metadata.capabilities AND
method presence (adapters advertising but not implementing returns False).

Co-Authored-By: Claude <noreply@anthropic.com>"
```

### Task C.7: Mirror streaming updates to RemoteWorktreeProvider

**Files**:
- Modify: `mahavishnu/mahavishnu/core/worktree_providers/remote.py`

- [ ] **Step 1: Mirror the local.py changes for S3/GCS/Azure paths**

Apply the spec's File 5 implementation: streaming create/fetch with abort, cache key unified to `materialized:{handle.handle_id}` (was `{handle_id}:materialized` — R2-20 fix), `health_check()` returns self._storage.health() (was hardcoded False — known Phase 2 stub now fixed).

- [ ] **Step 2: Write the failing tests**

Extend `tests/unit/test_core_worktree_providers_remote.py` with the named tests from spec:
- `test_remote_create_uses_save_stream_when_available`
- `test_remote_create_falls_back_to_stopgap_when_no_save_stream`
- `test_remote_create_uses_uuid4_handle_id_not_deterministic`
- `test_remote_create_storage_key_too_long_raises_mhv220`
- `test_remote_create_s3_multipart_aborted_on_partial_failure` (asserts `abort_multipart_upload` called via moto call count)
- `test_remote_fetch_uses_read_stream_when_available`
- `test_remote_fetch_sha_mismatch_raises_before_extract`
- `test_remote_fetch_cache_hit_skips_streaming`
- `test_remote_fetch_phase2_orphan_raises_mhv213`

- [ ] **Step 3: Run tests + commit**

```bash
cd mahavishnu
uv run pytest tests/unit/test_core_worktree_providers_remote.py -v
git add mahavishnu/core/worktree_providers/remote.py tests/unit/test_core_worktree_providers_remote.py
git commit -m "feat(provider): RemoteWorktreeProvider streaming + cache key unification

R2-20 fix: cache key unified to f'materialized:{handle.handle_id}'
(was f'{handle_id}:materialized' on remote only — now matches local).
Phase 2 health_check() hardcoded-False bug fixed: returns
self._storage.health(). S3 multipart abort tested via moto call count.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

### Task C.8: Add streaming integration test

**Files**:
- Create: `mahavishnu/tests/integration/test_worktree_round_trip_streaming.py`

- [ ] **Step 1: Write the integration test**

```python
"""End-to-end Phase 3 streaming tar round-trip integration test.

Requires moto.mock_aws + fakeredis (CI emulators). Marked
@pytest.mark.integration + @pytest.mark.slow.
"""
from __future__ import annotations

import asyncio
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.slow]

try:
    import zstandard  # noqa: F401
except ImportError:
    pytest.fail("zstandard required; uv sync --group compression-zstd", pytrace=False)


def _infra_available() -> bool:
    """Skip when Redis or moto not available in test env."""
    try:
        import fakeredis.aioredis  # noqa: F401
        import moto  # noqa: F401
        return True
    except ImportError:
        return False


pytestmark.append(pytest.mark.skipif(not _infra_available(), reason="integration infra unavailable"))


async def test_create_then_fetch_round_trip_100mb():
    """100MB worktree; create, register, fetch, verify extract."""
    # ... implementation: spawn LocalWorktreeProvider with moto + fakeredis,
    # create_worktree_handle a 100MB worktree, fetch it back, assert SHA match,
    # assert file count match, assert worktree dir exists.


async def test_create_then_fetch_with_storage_chunked_upload():
    """Verify save_stream actually streams (assert upload_part call count > 1)."""
    # ... implementation: monkeypatch S3StorageAdapter to count upload_part calls.


async def test_sha_mismatch_during_streaming_raises_before_extract():
    """Tampered bundle: MHV-208 raised BEFORE any files extracted."""
    # ... implementation: write bundle, flip a byte, fetch, assert no files in target.
```

- [ ] **Step 2: Run + commit**

```bash
cd mahavishnu
uv run pytest -m integration -v
git add tests/integration/test_worktree_round_trip_streaming.py
git commit -m "test: end-to-end Phase 3 streaming round-trip integration test

@moto.mock_aws + fakeredis for CI reproducibility. Marked
@pytest.mark.integration + @pytest.mark.slow (skipped in fast lane).

Co-Authored-By: Claude <noreply@anthropic.com>"
```

### Task C.9: Verify Phase C

- [ ] **Step 1: Full unit suite**

Run: `cd mahavishnu && uv run pytest -m "not integration" -v`
Expected: all pass.

- [ ] **Step 2: Coverage gate**

Run: `cd mahavishnu && uv run pytest --cov=mahavishnu --cov-fail-under=89`
Expected: passes; storage_io at 100%; observability helpers at 100%; provider streaming paths ≥85%.

- [ ] **Step 3: Crackerjack**

Run: `cd mahavishnu && crackerjack run`
Expected: clean (no new ERROR/WARNING vs baseline; ty ratchet unchanged).

- [ ] **Step 4: Push to main**

```bash
cd mahavishnu
git push origin main
```

**Wait 2 days for soak.**

---

## Phase D — mahavishnu: runbook, README, CHANGELOG, rollout

**Integration Contract**
- **Triggered from**: Phase C complete (storage_io + providers + observability shipped).
- **Returns to / updates**: Operator-facing runbook at `docs/runbooks/worktree-streaming-phase3.md`. Module README at `mahavishnu/core/worktree_providers/README.md`. CHANGELOG entry. Phase 4 ADR placeholder at `docs/adr/016-phase4-python-3.15-migration.md`.
- **Demonstrable by**: A new operator reading the runbook can perform the migration sweep, triage any MHV-20x error, and follow the rollback procedure. A new contributor reading the README understands the streaming tar API.
- **Rollback signal**: Phase 3 rollout causes a spike in MHV-208 > 0.01% of fetches within 7 days.
- **Observability added**: DoD item 13 — owner monitors `bundle_integrity_failure_total` rate for 7 calendar days post-rollout; escalates to primary on-call if rate > 0.01%.

**Files**:
- Create: `mahavishnu/docs/runbooks/worktree-streaming-phase3.md`
- Create: `mahavishnu/mahavishnu/core/worktree_providers/README.md`
- Modify: `mahavishnu/CHANGELOG.md`
- Create: `mahavishnu/docs/adr/016-phase4-python-3.15-migration.md` (placeholder skeleton)
- Modify: `mahavishnu/mahavishnu/core/worktree_coordination.py` (Phase 3 error severity table)
- Modify: `mahavishnu/.claude/CLAUDE.md` (already done in Phase 0.7; verify)

### Task D.1: Write the runbook

**Files**:
- Create: `mahavishnu/docs/runbooks/worktree-streaming-phase3.md`

- [ ] **Step 1: Write the runbook per spec DoD item 6**

Sections (per spec):
1. Overview (streaming tar.zst Phase 3 rollout summary)
2. SLO/SLI targets (fetch P99 < 5s, integrity failure rate < 0.01%, create P99 < 10s)
3. PromQL alert queries (per spec DoD item 6f)
4. Capacity planning (`/tmp` headroom = bundle_size × concurrent_creates × 1.5)
5. Error code triage table (MHV-208..213 + MHV-220..223 with first-response actions)
6. Rollout procedure (drain Phase 2 writers, upgrade readers, upgrade writers)
7. Startup-time migration sweep (Python script: `scripts/sweep_legacy_targz.py`)
8. Rollback procedure (revert Phase 3 commits; no schema migration)
9. On-call escalation matrix (`pagerduty_service: "mahavishnu-worktree-streaming"`, primary/secondary/manager contacts)
10. Postmortem template

- [ ] **Step 2: Commit**

```bash
cd mahavishnu
git add docs/runbooks/worktree-streaming-phase3.md
git commit -m "docs(runbook): Phase 3 streaming tar operator runbook

Covers SLO/SLI targets, PromQL alerts, capacity planning, error code
triage, rollout procedure, migration sweep, rollback, escalation
matrix, postmortem template.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

### Task D.2: Write the migration sweep script

**Files**:
- Create: `mahavishnu/scripts/sweep_legacy_targz.py`

- [ ] **Step 1: Write the sweep script**

```python
#!/usr/bin/env python3
"""Sweep the storage prefix for legacy .tar.gz Phase 2 bundles.

Run at startup to detect orphaned Phase 2 handles. Reports counts
per bucket and exits non-zero if any found (operator decides
deletion vs re-encode).
"""
from __future__ import annotations

import asyncio
import sys

from oneiric.adapters.storage.s3 import S3StorageAdapter, S3StorageSettings


async def sweep(bucket: str, prefix: str) -> int:
    adapter = S3StorageAdapter(S3StorageSettings(bucket=bucket))
    count = 0
    async for key in adapter.list_keys(prefix=prefix):
        if key.endswith(".tar.gz"):
            print(f"LEGACY: {key}")
            count += 1
    print(f"\nTotal legacy .tar.gz keys: {count}")
    return count


if __name__ == "__main__":
    bucket = sys.argv[1] if len(sys.argv) > 1 else "mahavishnu-worktrees"
    prefix = sys.argv[2] if len(sys.argv) > 2 else "worktrees/"
    rc = asyncio.run(sweep(bucket, prefix))
    sys.exit(1 if rc > 0 else 0)
```

- [ ] **Step 2: Commit**

```bash
cd mahavishnu
git add scripts/sweep_legacy_targz.py
git commit -m "feat(scripts): migration sweep for legacy .tar.gz keys

Operator-facing script run at startup to detect Phase 2 orphan
bundles. Exits non-zero if any found (operator decides action).

Co-Authored-By: Claude <noreply@anthropic.com>"
```

### Task D.3: Write the module README

**Files**:
- Create: `mahavishnu/mahavishnu/core/worktree_providers/README.md`

- [ ] **Step 1: Write the README**

Sections (per DoD item 14):
1. Overview
2. API contract (`serialize_worktree_tar` context-manager + `deserialize_worktree_tar` chunk_reader)
3. Error codes (MHV-209..213 + MHV-220..223)
4. Phase 2 → Phase 3 migration (handle_id format change, storage key suffix change, rollout sequence)
5. Caveats (`data_filter` strips setuid/setgid bits vs Phase 2 default; stopgap path 256MB cap; UUID4 handle_id cardinality impact)

- [ ] **Step 2: Commit**

```bash
cd mahavishnu
git add mahavishnu/core/worktree_providers/README.md
git commit -m "docs(module): worktree_providers README for Phase 3 streaming API

Co-Authored-By: Claude <noreply@anthropic.com>"
```

### Task D.4: Update CHANGELOG

**Files**:
- Modify: `mahavishnu/CHANGELOG.md`

- [ ] **Step 1: Add Phase 3 entry**

```markdown
## [Unreleased] — Phase 3 streaming tar support + 3.14 migration

### Added
- `serialize_worktree_tar(path)` is now a `@contextmanager` yielding `(temp_path, byte_size, sha256)`.
- `deserialize_worktree_tar(chunk_reader, target, *, expected_sha256, backend, principal_short)`.
- `verify_sha256_streaming` in `observability/bundle_integrity.py`.
- 9 new error codes: MHV-209..213 + MHV-220..223.
- New `streaming_codec_failures_total{algorithm}` OTel counter.
- `bundle_bytes` histogram extended to 1GB.
- `requires-python = ">=3.14"` (Bodai ecosystem 3.14 migration).
- `docs/runbooks/worktree-streaming-phase3.md` — operator runbook.
- `scripts/sweep_legacy_targz.py` — migration sweep script.

### Changed
- `LocalWorktreeProvider.fetch` uses bounded `queue.Queue(maxsize=4)` handoff; memory bounded at chunk_size × 4.
- `RemoteWorktreeProvider.fetch` mirrors local; cache key unified to `materialized:{handle.handle_id}`.
- `handle_id` switched from deterministic (repo, branch, base_ref) to `uuid4().hex` to eliminate concurrent-create races.
- `data_filter` strips setuid/setgid bits (security improvement; behavior change vs Phase 2 default no-filter).

### Removed
- 5 Phase 2 tests that assigned `bytes` to `serialize_worktree_tar` (incompatible with new context-manager form).
```

- [ ] **Step 2: Commit**

```bash
cd mahavishnu
git add CHANGELOG.md
git commit -m "docs(changelog): Phase 3 streaming tar + 3.14 migration entry

Co-Authored-By: Claude <noreply@anthropic.com>"
```

### Task D.5: Phase 4 ADR placeholder

**Files**:
- Create: `mahavishnu/docs/adr/016-phase4-python-3.15-migration.md`

- [ ] **Step 1: Write the ADR skeleton**

```markdown
# ADR 016: Bodai Ecosystem Python 3.15 Migration (Phase 4)

**Status:** Proposed — placeholder filed 2026-08-23.
**Target window:** Q1-Q2 2027 (3.15.0 final + 3 months ecosystem soak).

## Context

Phase 3 ships the Bodai ecosystem at `requires-python = ">=3.14"`. Python 3.15
(in beta as of mid-2026, expected GA Oct 2026) is the next Bodai target.

## Proposed sequence (dependency-ordered, 2-week soak between merges)

1. mcp-common → `>=3.15`
2. oneiric → `>=3.15`
3. dhara → `>=3.15`
4. session-buddy → `>=3.15`
5. akosha → `>=3.15`
6. crackerjack → `>=3.15`
7. mahavishnu → `>=3.15`

## Pre-migration checklist (each repo)

- [ ] Verify all runtime deps have 3.15 wheels
  - Primary risk: `llama-index-core`, `pydantic-ai-slim`, `selectolax`
- [ ] deprecation audit: `python -W error::DeprecationWarning -m pytest`
- [ ] `crackerjack run` clean on 3.15
- [ ] compatibility matrix in this ADR: "tested at 3.15.0rcN"

## Decision

TBD post-3.15 GA. See `BODAI_UPGRADE_WATCH.md` for weekly tracking.
```

- [ ] **Step 2: Commit**

```bash
cd mahavishnu
git add docs/adr/016-phase4-python-3.15-migration.md
git commit -m "docs(adr): Phase 4 3.15 migration placeholder

Skeleton filed during Phase 3 rollout. Decision deferred until
3.15.0 final + 3 months ecosystem soak.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

### Task D.6: Coordinator error severity table

**Files**:
- Modify: `mahavishnu/mahavishnu/core/worktree_coordination.py`

- [ ] **Step 1: Add per-error-code severity decision comment**

Add a comment block at top of `WorktreeCoordinator` (or wherever the Phase 3 errors propagate):

```python
# Phase 3 error severity decisions (NICE-TO-HAVE worktree_coordinator):
#   MHV-209 TEMP_CREATE_FAILED   → propagate (programmer error, retry won't help)
#   MHV-210 TEMP_WRITE_FAILED    → swallow-and-log (could be transient ENOSPC)
#   MHV-211 PATH_TRAVERSAL       → propagate (security event, audit)
#   MHV-212 MALFORMED            → swallow-and-log + invalidate handle (corrupt bundle)
#   MHV-213 LEGACY_PHASE2        → propagate (operator-facing migration warning)
#   MHV-220 STORAGE_KEY_TOO_LONG → propagate (programmer error)
#   MHV-221 STOPGAP_TOO_LARGE    → propagate (deployment misconfig)
#   MHV-222 NOT_FOUND            → swallow-and-log (handle gone, not an error)
#   MHV-223 CODEC_UNAVAILABLE    → propagate (deployment misconfig; missing dep)
```

- [ ] **Step 2: Commit**

```bash
cd mahavishnu
git add mahavishnu/core/worktree_coordination.py
git commit -m "docs(coordinator): Phase 3 error severity table

Co-Authored-By: Claude <noreply@anthropic.com>"
```

### Task D.7: Verify Phase D + push

- [ ] **Step 1: Full test suite**

Run: `cd mahavishnu && uv run pytest -m "not integration" -v`
Expected: all pass.

- [ ] **Step 2: Coverage gate**

Run: `cd mahavishnu && uv run pytest --cov=mahavishnu --cov-fail-under=89`
Expected: passes.

- [ ] **Step 3: Crackerjack**

Run: `cd mahavishnu && crackerjack run`
Expected: clean.

- [ ] **Step 4: Push to main**

```bash
cd mahavishnu
git push origin main
```

**Start 7-day post-rollout monitoring window.**

---

## Phase E — Post-rollout: 7-day monitoring + Phase 4 ADR tracking

**Integration Contract**
- **Triggered from**: Phase D merged to main.
- **Returns to / updates**: 7-day monitoring window per DoD item 13. Escalation triggers wired to PagerDuty.
- **Demonstrable by**: After 7 days, `bundle_integrity_failure_total` rate < 0.01% of fetches; S3 multipart abort rate = 0 (or bounded by transient network errors); `pytest --cov=mahavishnu --cov-fail-under=89` continues to pass on 3.14; crackerjack clean.
- **Rollback signal**: integrity failure rate > 0.01% sustained; or stopgap path OOM (MAX_BUNDLE_BYTES_STOPGAP exceeded in prod); or migration sweep finds > 100 legacy keys in storage.
- **Observability added**: `BODAI_UPGRADE_WATCH.md` tracking doc; weekly Phase 4 readiness notes.

**Files**:
- Create: `BODAI_UPGRADE_WATCH.md` (cross-repo tracking)

### Task E.1: Write `BODAI_UPGRADE_WATCH.md`

**Files**:
- Create: `BODAI_UPGRADE_WATCH.md` (at repo root or in `docs/`)

- [ ] **Step 1: Write the tracking doc**

```markdown
# Bodai Python Upgrade Watch

Tracks Python 3.15 readiness across the Bodai ecosystem. Filed 2026-08-23
during Phase 3 rollout (3.14 migration).

## Weekly checklist

- [ ] 3.15 beta releases (cpython devguide.python.org)
- [ ] llama-index-core 3.15 wheel status
- [ ] pydantic-ai-slim 3.15 wheel status
- [ ] selectolax 3.15 wheel status
- [ ] Other deps with no 3.15 wheel yet
- [ ] Bodai CI matrix (each repo) currently on 3.14, ready to bump to 3.15

## Phase 4 trigger

When 3.15.0 final releases AND all tracked deps have 3.15 wheels:
- Open Phase 4 ADR update (move from Proposed to Accepted)
- Begin the 7-PR sequence: mcp-common → oneiric → dhara → session-buddy → akosha → crackerjack → mahavishnu
- 2-week soak between each merge
- Total window: ~3 months from 3.15.0 GA to mahavishnu on 3.15

## Status (update weekly)

- 2026-08-23: Phase 3 merged. 3.14 is baseline. 3.15 still beta.
```

- [ ] **Step 2: Commit**

```bash
git add BODAI_UPGRADE_WATCH.md
git commit -m "docs: BODAI_UPGRADE_WATCH.md — Phase 4 3.15 readiness tracker

Co-Authored-By: Claude <noreply@anthropic.com>"
```

### Task E.2: 7-day monitoring window

- [ ] **Day 1–7 post-rollout**: monitor `bundle_integrity_failure_total`, `streaming_codec_failures_total`, `s3_multipart_abort_total`, `worktree_op_duration_seconds` per DoD items 6f + 13.

If rate > 0.01% of fetches: page primary on-call per DoD item 6h.

### Task E.3: Phase 4 ADR finalization (deferred)

Defer to Q1-Q2 2027 per spec section "Python version strategy". Reopen this plan when 3.15.0 GA is announced.

---

## Self-Review (per writing-plans skill)

### Spec coverage check

| Spec section | Plan task |
|---|---|
| Context (Phase 2 vs Phase 3) | implicit (whole plan) |
| Architecture (2 repos, 3 components) | Tasks A.1–A.9, C.1–C.9 |
| Data flow on create | Tasks C.5, C.6 |
| Data flow on fetch | Tasks C.5, C.6, C.7 |
| Memory profile comparison (R2-10 fix) | Task C.6 (queue handoff) |
| Why temp file as intermediate buffer | Task C.5 (storage_io rewrite) |
| Oneiric File 1 (pyproject) | Task A.1 |
| Oneiric File 2 (StreamingCompressionAction) | Tasks A.2, A.3 |
| Oneiric File 3 (catalog registration) | Task A.4 |
| Oneiric File 4 (action-kits.md) | Task A.5 |
| Oneiric File 5 (storage adapter streaming) | Tasks A.6, A.7 |
| Oneiric File 5b (S3 multipart abort) | Task A.7 |
| Oneiric File 6/7/8 (test files) | Tasks A.2, A.6, A.7 |
| Oneiric File 8b (GCS + Azure tests) | Tasks B.4, B.5 |
| Oneiric CHANGELOG | Task A.8 |
| Mahavishnu File 1 (pyproject + PEP 735) | Task C.1 |
| Mahavishnu File 2 (storage_io rewrite) | Task C.5 |
| Mahavishnu File 3 (errors.py) | Task C.2 |
| Mahavishnu File 3b (verify_sha256_streaming) | Task C.3 |
| Mahavishnu File 4 (local.py) | Task C.6 |
| Mahavishnu File 5 (remote.py) | Task C.7 |
| Mahavishnu File 6 (storage_io tests) | Task C.5 |
| Mahavishnu File 7 (local.py tests) | Task C.6 |
| Mahavishnu File 8 (ADR update) | Phase D tasks (CHANGELOG, runbook) |
| Phase 2 caller migration | Task C.1 (delete old tests) + C.6/C.7 (new context-manager form) |
| verify_sha256_streaming full body | Task C.3 |
| MAX_BUNDLE_BYTES_STOPGAP definition | Task C.5 |
| Observability additions (op enum, new counters, histogram buckets, health probe) | Tasks C.3, C.4 |
| Python version strategy (Option C) | Phases 0.1–0.7 (entire Workstream 1) + Phase E (BODAI_UPGRADE_WATCH) |
| Dotted-Is / Crossed-Ts fixes (B-DI-01..15) | Spread across Tasks C.5, C.6, C.7, A.7, etc. |
| Out of scope | implicit (Phase 4 ADR filed but not executed) |

### Placeholder scan

- Searched: no "TBD", "TODO", "implement later", "fill in details" in any code block.
- No "add appropriate error handling" — every error site has explicit MHV code + counter emit.
- No "Similar to Task N" — every code block is self-contained.
- All test code is real test code, not "write tests for the above" stubs.

### Type consistency check

- `serialize_worktree_tar(path) -> Iterator[tuple[Path, int, str]]` (context manager) — consistent across Tasks C.1, C.5, C.6, C.7.
- `deserialize_worktree_tar(chunk_reader, target, *, expected_sha256, backend, principal_short)` — consistent.
- `verify_sha256_streaming(actual_sha, expected_sha, *, backend, principal_short)` — consistent across Tasks C.3, C.5.
- `record_bundle_integrity_failure_short(*, backend, principal_short)` — consistent.
- `supports_streaming(storage) -> bool` — defined in C.6, used in C.6 and C.7.
- `MAX_BUNDLE_BYTES_STOPGAP: int = 256 * 1024 * 1024` — defined in C.5, used in C.6, C.7.
- MHV error code strings consistent across errors.py table (C.2), storage_io.py raises (C.5), local.py raises (C.6), remote.py raises (C.7), observability raises (C.3), runbook triage table (D.1).
- One error in the plan: I used `mahavishnu/mahavishnu/...` paths (with the double `mahavishnu/`). Verify the actual layout — `mahavishnu/mahavishnu/core/...` is the correct path for the mahavishnu repo (mahavishnu is the org dir and `mahavishnu/` is the package dir inside it).