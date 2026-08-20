---
name: mcp-deps-crackerjack-loop
description: Dep-update + crackerjack -p minor loop across 15 *-mcp repos, with a crackerjack patch for annotated tag push
---

# Design: `*-mcp` dep-update + crackerjack loop (2026-08-20)

## Problem

The 15 `*-mcp` repos (`css-mcp`, `excalidraw-mcp`, `graphics-mcp`, `langsmith-mcp`,
`mailgun-mcp`, `neo4j-mcp`, `opera-cloud-mcp`, `penpot-api-mcp`, `porkbun-dns-mcp`,
`porkbun-domain-mcp`, `raindropio-mcp`, `spline-mcp`, `synxis-crs-mcp`,
`synxis-pms-mcp`, `unifi-mcp`) all depend on `oneiric` and `mcp-common` and have
sitting dep pins that lag the upstream ecosystem. We need to refresh those deps,
clear any quality hooks that surface, and publish a new version of each.

We also discovered that `crackerjack run -p minor` (the publish pathway) creates
**lightweight** tags via `git tag v{version}` with no `-a`, then calls
`push_with_tags` which uses `--follow-tags`. `--follow-tags` only pushes
**annotated** tags, so the local `vX.Y.Z` tag never reaches origin. This is a
crackerjack defect that affects every downstream repo, not just the 15 `*-mcp`
ones — so the patch is its own deliverable.

## Goals

1. Refresh `oneiric` + `mcp-common` in all 15 `*-mcp` repos to latest published.
2. Publish a new version of each repo to PyPI via `crackerjack run -p minor`.
3. Push an **annotated** git tag to origin for each repo (so consumers can `git
   checkout vX.Y.Z`).
4. Fix the crackerjack tag defect so future runs everywhere benefit.

## Non-goals

- No major refactors of `*-mcp` code.
- No new feature work; this is dep + quality gate refresh only.
- No changes to non-`*-mcp` Bodai components in this cycle.

## Architecture

```
crackerjack repo (one-shot patch)
        ↓
*-mcp repo loop (×15, sequential)
        ↓
per-repo worktree → dep bump → CVE pre-fix → crackerjack -p minor loop
                  → tag fix-up (if needed) → ff-merge worktree → next repo
```

Three layers, sequential. The crackerjack patch is its own deliverable because
every downstream run benefits from it.

## Components

### Layer 1: Crackerjack patch (deliverable #1)

**Files to change** in `/Users/les/Projects/crackerjack`:

- `crackerjack/managers/publish_manager.py:669-686` — `create_git_tag_local` →
  use `git tag -a v{version} -m "Release v{version}"` instead of `git tag
  v{version}`. Function name can stay (or rename for clarity).
- `crackerjack/managers/publish_manager.py:688-715` — `create_git_tag` already
  has a push step but still creates lightweight tag. Fix the tag command.
- `crackerjack/core/phase_coordinator.py:1640-1647` — `_finalize_publishing`
  currently calls `create_git_tag_local`. Switch to `create_git_tag` (the one
  with the push step) so the tag actually reaches origin.

**Tests**:

- Existing `pytest tests/` in crackerjack repo.
- Real end-to-end: `crackerjack run -b` (bump-only, no publish) on a scratch
  branch in mahavishnu; verify `git for-each-ref refs/tags/v* --format='%(objecttype) %(refname)'`
  shows `tag` not `commit`.

**Commit in crackerjack repo** with a focused message and Co-Authored-By.

### Layer 2: Per-repo worktree isolation

Per the worktree pattern from earlier sessions (memory: `session-buddy-bugs-fixed-2026-08-04`),
each `*-mcp` repo gets its own worktree:

```bash
cd /Users/les/Projects/<repo>
git worktree add ../<repo>-crackerjack-loop -b crackerjack/loop main
cd ../<repo>-crackerjack-loop
```

When done: `git worktree remove ../<repo>-crackerjack-loop` and ff-merge
`crackerjack/loop` back to `main`.

### Layer 3: Dep refresh + crackerjack loop (deliverable #2)

Per repo, inside the worktree:

1. **Bump deps** — `uv add --upgrade oneiric mcp-common` with `VIRTUAL_ENV`,
   `UV_ACTIVE`, `UV_PROJECT_ENVIRONMENT` stripped (memory:
   `uv-active-and-virtual-env-cross-repo`).
2. **Pre-emptive CVE upgrade** — `uv pip install --upgrade aiohttp>=3.14.3
   cryptography>=49.0.1` to skip one `pip-audit` failure cycle (memory:
   `crackerjack-pip-audit-aiohttp-cryptography-cve`).
3. **Run crackerjack** — `uv run crackerjack run -v -p minor`.
4. **If hooks fail** → fix inline (ruff/ty/pytest/C901/BLE001 etc.), re-run.
5. **If drift gets bundled into the bump commit** → surgical `git reset --soft
   HEAD~1 && git reset HEAD <unrelated> && git add <intended> && git commit`
   (memory: `drift-bundling-recovery`).
6. **Once hooks pass cleanly** → crackerjack publishes to PyPI, pushes commit
   + tag to origin, all in one shot. Verify on PyPI: `pip index versions <pkg>`.

### Tag fix-up (only if crackerjack patch didn't apply or test repo)

After each `crackerjack run -p minor`:

```bash
git tag -fa "v$X.Y.Z" HEAD -m "Release v$X.Y.Z ($(date -I))"
git push origin "v$X.Y.Z" --force
```

This is the fallback if the patch in Layer 1 didn't land in time or didn't take
effect. With the patch in place, this step is a no-op (tag already annotated +
pushed).

## Data flow

```
worktree/main (clean)
  ↓ uv add --upgrade oneiric mcp-common
worktree/main (dirty: pyproject.toml, uv.lock)
  ↓ uv pip install --upgrade aiohttp cryptography
worktree/main (dirty: same two + maybe more if pinned)
  ↓ uv run crackerjack run -v -p minor
    ↓ config phase
    ↓ fast_hooks (ruff --fix --unsafe-fixes auto-applies)
    ↓ snob_tests (pytest)
    ↓ comprehensive_hooks (ty, complexipy, bandit, skylos, refurb, vulture)
    ↓ coverage_ratchet
    ↓ publishing
      ↓ version bump in pyproject.toml
      ↓ git add (sweeps dirty tree)
      ↓ git commit "chore: bump version to X.Y.Z"
      ↓ uv publish (PyPI OIDC trusted publishing)
      ↓ git tag -a vX.Y.Z -m "..." (after patch)
      ↓ git push --follow-tags (after patch: tag actually goes)
  ↓ ff-merge crackerjack/loop into main
  ↓ git worktree remove
  ↓ next repo
```

## Error handling

| Failure mode | Response |
|---|---|
| Fast hooks fail (ruff auto-fix couldn't repair) | Inspect output, fix inline, re-run `crackerjack run -v` (no `-p` yet). |
| Comprehensive hooks fail (ty/bandit/C901) | Fix inline source-level, re-run. |
| `snob_tests` fail (pytest) | Likely a new-dep regression. Bisect with `uv pip install oneiric==OLD` to confirm. |
| PyPI publish fails | Crackerjack auto-rolls back via `git reset --hard`. Verify with `git log` + `git status`, re-run. |
| Push fails (yellow warning, non-fatal) | Manual `git push --follow-tags` from inside the worktree. |
| Drift bundling (unrelated dirty files in bump commit) | `git reset --soft HEAD~1 && git reset HEAD <unrelated> && git add <intended> && git commit`. Re-push if needed. |
| Tag still lightweight after crackerjack patch | Fallback `git tag -fa` step. Investigate why patch didn't apply. |
| OIDC token missing (PyPI rejected) | Verify `.github/workflows/publish.yml` (or equivalent) has correct `id-token: write` and trusted publisher config. |

## Testing

### Crackerjack patch tests

- `pytest tests/` in crackerjack repo — covers publish manager + phase coordinator.
- Manual: in mahavishnu, on a throwaway branch: `crackerjack run -b` (bump-only),
  verify `git for-each-ref refs/tags/v*` shows `tag` not `commit`, then reset.

### Per-repo loop tests

- `crackerjack run -v -p minor` IS the test for that repo. Each iteration surfaces
  remaining issues.
- After publish, smoke test: `uv pip install --force-reinstall <pkg> && <pkg> --version`
  matches PyPI version.
- After merge, run `crackerjack` (no `-p`) once more on main to verify clean tree.

## Acceptance criteria

- [ ] Crackerjack patch committed in `/Users/les/Projects/crackerjack`, with
      annotated tags now pushed.
- [ ] All 15 `*-mcp` repos have new PyPI version matching `pyproject.toml`.
- [ ] All 15 repos have annotated `vX.Y.Z` tag on origin.
- [ ] All 15 repos: crackerjack fast_hooks + comprehensive_hooks + snob_tests +
      coverage_ratchet pass clean on main.
- [ ] Zero manual version bumps in any `*-mcp` repo (all via `crackerjack -p minor`).
- [ ] No drift-commits in any of the 15 repos' main branches (bump commits only
      contain intended files).

## Rollback

- **Per repo**: `git reset --hard <pre-loop-sha>` to undo bump + tag. PyPI cannot
  be un-published (only yanked via admin).
- **Crackerjack patch**: revert commit + reinstall previous crackerjack. Backward-
  compatible (lightweight tag is still valid; just not on origin).

## Observability

- Crackerjack prints structured phase output to stdout. Capture per-repo with
  `tee /tmp/crackerjack-<repo>-<date>.log` for offline diff.
- PyPI upload confirmation in `crackerjack` output: `✅ Successfully published`.
- GitHub: tag push reflected on the repo's tags page.

## Open questions

None at design time. Resolved in conversation:
- Sequential per repo: yes
- `crackerjack -p minor` for bump+publish: yes
- Drift bundling: let it bundle, recover if needed
- Tag-push: patch crackerjack (don't manually tag per repo)
- Push policy: crackerjack handles (commits + tags to origin after patch)

## Risks

1. **PyPI already has a higher version than what we'd push** — unlikely but
   possible. Crackerjack's version-bump logic reads current PyPI version and
   bumps from there; check first if any `*-mcp` was published outside this loop.
2. **OIDC token expires mid-loop** — if a run takes >1 hour and tokens are
   short-lived, the publish step may fail. Mitigation: per-repo runs are short
   (≤10 min each); 15 × 10 = ~2.5 hours total, well within typical token windows.
3. **Sequential is slow** — 15 × ~10 min = ~2.5 hours wall-clock. Acceptable
   given lower blast radius and easier bisection. Parallel dispatch would risk
   drift bundling and concurrent PyPI uploads (also problematic for OIDC).
4. **Worktree-per-repo overhead** — disk + bookkeeping. Negligible at 15 worktrees.