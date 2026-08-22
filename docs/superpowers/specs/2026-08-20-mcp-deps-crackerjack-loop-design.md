---
name: mcp-deps-crackerjack-loop
description: Refresh oneiric deps in 15 *-mcp repos via crackerjack -p minor, with a one-line crackerjack patch for annotated tags
status: active
role: canonical
date: 2026-08-20
last_reviewed: 2026-08-20
topic: mcp-deps-crackerjack-loop
title: mcp-deps-crackerjack-loop Design Spec (rev2)
---

# Design: `*-mcp` dep refresh + crackerjack loop (2026-08-20, rev2)

## Problem

The 15 `*-mcp` repos have stale dep pins for `oneiric` and `mcp-common`. We need
to refresh both, clear any quality hooks that surface, and publish a new version
of each.

Two upstream realities shape the design:

1. **`crackerjack run -p minor` creates lightweight tags.** `publish_manager.py:676`
   runs `git tag v{version}` with no `-a`. `--follow-tags` (used by the
   subsequent push) only pushes **annotated** tags, so the local `vX.Y.Z` tag
   never reaches origin. The one-line fix is `git tag -a v{version} -m "Release v{version}"`.

2. **`mcp-common` is a path-source editable in every `*-mcp` repo.**
   `[tool.uv.sources] mcp-common = { path = "../mcp-common", editable = true }`.
   `uv add --upgrade mcp-common` against a path source is fragile; `uv sync --upgrade`
   resolves to the local editable checkout.

## Goals

1. Refresh `oneiric` + `mcp-common` in all 15 `*-mcp` repos to latest.
2. Publish a new version of each repo to PyPI via `crackerjack run -p minor`.
3. Push an **annotated** git tag to origin for each repo.
4. Fix the crackerjack tag defect (one-line patch + publish new crackerjack).

## Non-goals

- No major refactors of `*-mcp` code.
- No new feature work.
- No changes to non-`*-mcp` Bodai components in this cycle.
- No bumping `crackerjack>=X.Y.Z` pins in any `*-mcp` repo (rely on PyPI
  resolution to find the new patched version automatically — most pins are
  wide like `>=0.50.1`).

## Architecture

```
Layer 0: Pre-flight gate (15 repos in parallel, fast)
        ↓
Layer 1: One-line crackerjack patch + own -p minor (publishes new crackerjack)
        ↓
Layer 2: Per-repo loop, sequential (15 repos, ~10 min each)
        ↓
        per repo: pre-flight → uv sync → crackerjack -p minor → tag fix-up → next repo
```

Three layers, sequential. Layer 0 establishes clean state for all 15 repos.
Layer 1 publishes the crackerjack fix to PyPI so Layer 2 can resolve to the
patched version (per the BLOCKING finding from the audit).

## Components

### Layer 0: Pre-flight gate (parallel, fast)

For each `*-mcp` repo, in parallel:

```bash
cd /Users/les/Projects/<repo>
git status --porcelain           # must be empty (exit non-zero otherwise)
pip index versions <pkg> | head -1   # record baseline PyPI version
git log --oneline -1             # record baseline commit
```

If `git status --porcelain` is non-empty: **ABORT** the loop. Surface the
uncommitted files to user. Do not proceed (drift bundling risk per memory).

If pre-flight passes: continue to Layer 1.

### Layer 1: One-line crackerjack patch + own publish

In `/Users/les/Projects/crackerjack`:

```bash
cd /Users/les/Projects/crackerjack
# Verify pre-flight passes
git status --porcelain

# Apply the one-line patch
edit crackerjack/managers/publish_manager.py:676
# FROM: result = self._run_command(["git", "tag", f"v{version}"])
#   TO: result = self._run_command(
#            ["git", "tag", "-a", f"v{version}", "-m", f"Release v{version}"]
#        )

# Run crackerjack's own loop (this publishes the fix)
unset VIRTUAL_ENV UV_ACTIVE UV_PROJECT_ENVIRONMENT
env -u VIRTUAL_ENV -u UV_ACTIVE -u UV_PROJECT_ENVIRONMENT \
    uv run crackerjack run -v -p minor
```

After Layer 1 succeeds: `crackerjack-X.Y.Z` is on PyPI. Each `*-mcp` repo with
`crackerjack>=X.Y.Z` (where X.Y.Z is some lower number) will resolve to the
new patched version automatically.

### Layer 2: Per-repo loop (sequential)

Per repo, in order:

```bash
cd /Users/les/Projects/<repo>

# Pre-flight (defense in depth)
test -z "$(git status --porcelain)" || { echo "DIRTY: <repo>"; exit 1; }

# Refuse to push if origin has a newer version we didn't publish
pypi_ver=$(pip index versions <pkg> 2>/dev/null | head -1)
local_ver=$(uv version --short 2>/dev/null || python -c "import tomllib; print(tomllib.loads(open('pyproject.toml').read())['project']['version'])")
test "$pypi_ver" != "$local_ver" && { echo "PYPI_DIVERGED: <repo>"; exit 1; }

# Refresh deps (broad --upgrade per user; --all-groups per memory)
unset VIRTUAL_ENV UV_ACTIVE UV_PROJECT_ENVIRONMENT
env -u VIRTUAL_ENV -u UV_ACTIVE -u UV_PROJECT_ENVIRONMENT \
    uv sync --upgrade --all-groups

# Run crackerjack (publishes bump + pushes commit + tag + PyPI)
env -u VIRTUAL_ENV -u UV_ACTIVE -u UV_PROJECT_ENVIRONMENT \
    uv run crackerjack run -v -p minor

# Always apply tag fix-up (idempotent; no-op if crackerjack already created annotated tag)
new_ver=$(python -c "import tomllib; print(tomllib.loads(open('pyproject.toml').read())['project']['version'])")
git tag -fa "v$new_ver" HEAD -m "Release v$new_ver ($(date -u +%Y-%m-%d))"
git push origin "v$new_ver" --force

# If drift got bundled into the bump commit (per memory: drift-bundling-recovery)
if ! git show HEAD --stat | grep -qE "pyproject\.toml|uv\.lock|CHANGELOG\.md"; then
    git reset --soft HEAD~1
    git reset HEAD
    git add pyproject.toml uv.lock CHANGELOG.md 2>/dev/null || git add pyproject.toml uv.lock
    git commit -m "chore(<repo>): bump version to $new_ver"
    git push origin HEAD:crackerjack/loop
fi

echo "✓ <repo> published $local_ver → $new_ver"
cd ..
# next repo
```

If `crackerjack run -v -p minor` exits non-zero (hooks fail): fix inline, re-run
without `-p` first to verify clean, then re-run with `-p`. If it can't be
fixed in <30 min: ABORT the loop, surface to user.

### Repo order

Sequential, alphabetical:
1. css-mcp
2. excalidraw-mcp
3. graphics-mcp
4. langsmith-mcp
5. mailgun-mcp
6. neo4j-mcp
7. opera-cloud-mcp
8. penpot-api-mcp
9. porkbun-dns-mcp
10. porkbun-domain-mcp
11. raindropio-mcp
12. spline-mcp
13. synxis-crs-mcp
14. synxis-pms-mcp
15. unifi-mcp

## Data flow

```
Layer 0 (parallel):
  for repo in *-mcp: git status check, record baseline
                ↓
Layer 1:
  patch crackerjack publish_manager.py:676 (one line)
                ↓
  crackerjack run -v -p minor (publishes new crackerjack to PyPI)
                ↓
Layer 2 (sequential):
  for repo in alphabetical:
    pre-flight (clean tree + PyPI version match)
                ↓
    uv sync --upgrade --all-groups (refreshes lockfile)
                ↓
    crackerjack run -v -p minor
      ├─ config
      ├─ fast_hooks (ruff autofix)
      ├─ snob_tests (pytest)
      ├─ comprehensive_hooks (ty, bandit, etc.)
      ├─ coverage_ratchet
      ├─ publishing
      │   ├─ bump pyproject.toml version
      │   ├─ git add (sweeps dirty tree — drift risk)
      │   ├─ git commit "chore: bump version to X.Y.Z"
      │   ├─ uv publish (PyPI OIDC OR UV_PUBLISH_TOKEN — see Risks)
      │   ├─ git tag vX.Y.Z (lightweight — bug)
      │   └─ git push --follow-tags (no-op for lightweight tag)
                ↓
    tag fix-up: git tag -fa vX.Y.Z -m "..." && git push origin --force
                ↓
    drift recovery: surgical reset if bump commit contains unrelated files
                ↓
    next repo
```

## Error handling

| Failure | Detection | Recovery |
|---|---|---|
| Pre-flight dirty tree | `git status --porcelain` non-empty | Abort loop; surface dirty files; do NOT proceed (drift bundling). |
| PyPI version diverged from local | `pip index versions != pyproject version` | Abort; someone else published this repo externally. Skip to next. |
| `uv sync --upgrade` fails | non-zero exit | Read output; usually network/transient. Retry once. If still fails: abort. |
| Crackerjack fast_hooks fail | non-zero exit | Fix inline; re-run `crackerjack run -v` (no `-p`) until clean; then `crackerjack run -v -p minor`. |
| Crackerjack comprehensive_hooks fail | non-zero exit | Fix inline source-level; same re-run pattern. |
| Crackerjack `snob_tests` fail | non-zero exit | Bisect via `uv pip install oneiric==OLD` where OLD is the version in `git show HEAD:uv.lock` immediately before the upgrade. |
| `uv publish` fails (auth) | `403 Invalid or non-existent authentication information` | Verify `UV_PUBLISH_TOKEN` env var is set in operator's shell. PyPI publishing uses `UV_PUBLISH_TOKEN`, NOT OIDC, for local runs. |
| PyPI version already exists | `400 File already exists` | The version was bumped twice. Reset the bump commit via `git reset --hard HEAD~1`, re-run. |
| Push fails | yellow warning (non-fatal) | Manual `git push` from inside the repo. |
| Drift bundled into bump commit | `git show HEAD --stat` shows unrelated files | Apply the drift-bundling-recovery pattern (surgical reset + targeted re-add). |
| Tag still lightweight after tag fix-up | `git for-each-ref refs/tags/v\* --format='%(objecttype)' \| grep '^commit'` | Re-run `git tag -fa vX.Y.Z HEAD -m "..."`. Investigate why annotated tag wasn't created. |

## Testing

### Layer 0 test
```bash
for repo in <list>; do
    cd /Users/les/Projects/$repo
    test -z "$(git status --porcelain)" || echo "DIRTY: $repo"
done
```

### Layer 1 test
After `crackerjack run -v -p minor` on /Users/les/Projects/crackerjack:
```bash
# Verify new crackerjack is on PyPI
pip index versions crackerjack | head -1

# Verify the tag is annotated on origin
git -C /Users/les/Projects/crackerjack ls-remote origin 'refs/tags/v*' | tail -1
git -C /Users/les/Projects/crackerjack for-each-ref refs/tags/v\* --format='%(objecttype) %(refname:short)' | tail -1
```

### Layer 2 test (per repo)
```bash
# After publish, verify
pip index versions <pkg> | head -1                                 # = pyproject version
git -C /Users/les/Projects/<repo> for-each-ref refs/tags/v\* --format='%(objecttype) %(refname:short)' | tail -1   # = "tag vX.Y.Z"
git -C /Users/les/Projects/<repo> ls-remote origin 'refs/tags/v*' | grep -q "vX.Y.Z"   # tag on origin
```

## Acceptance criteria

All four must pass:

1. **Layer 1 published**: `pip index versions crackerjack | head -1` ≥ the version
   we patched. New tag `vX.Y.Z` is annotated (`objecttype=tag`) AND on origin
   (`git ls-remote origin 'refs/tags/vX.Y.Z'`).

2. **All 15 `*-mcp` repos have new PyPI version**: for each repo,
   `pip index versions <pkg> | head -1` matches `pyproject.toml`'s `version` field.

3. **All 15 repos have annotated tag on origin**: for each repo,
   `git for-each-ref refs/tags/v\* --format='%(objecttype) %(refname:short)'` shows
   `tag vX.Y.Z` AND `git ls-remote origin 'refs/tags/vX.Y.Z'` returns a SHA.

4. **Crackerjack clean on each main**: for each repo, `uv run crackerjack run` (no
   `-p`) exits 0. (Re-running `crackerjack` on the bumped tree should not re-trigger
   publish.)

## Risks

1. **`--upgrade --all-groups` may downgrade packages.** Memory
   `uv-sync-upgrade-minimizes-version.md` documents that `uv sync --upgrade`
   re-resolves to MINIMUM version satisfying constraints (downgrade risk).
   `--upgrade-package <name>` would minimize nothing. User opted for broad
   `--upgrade` per explicit decision. If `uv.lock` shows downgrades after the
   sync, abort the run and re-pin manually.
2. **`UV_PUBLISH_TOKEN` may not be set in operator's shell.** Local publish via
   `uv publish` uses `UV_PUBLISH_TOKEN` env var, NOT OIDC (despite the spec's
   earlier assumption). If unset, publish fails with `403`. Verify before the
   loop starts: `echo $UV_PUBLISH_TOKEN | head -c 4` should show `pypi-`.
3. **PyPI version collision.** A repo's version may have been bumped externally
   since Layer 0's snapshot. Pre-flight detects this and aborts the affected repo.
4. **Crackerjack auto-rolls back via `git reset --hard` on PyPI failure.**
   `--hard` also nukes any inline source fixes. If rollback happens, the fixes
   are lost; re-apply them before re-running.
5. **`--follow-tags` only pushes annotated tags.** Layer 1's patch makes
   `create_git_tag_local` create annotated tags, so `push_with_tags` will
   propagate them. Layer 2's tag fix-up is a safety net (idempotent).
6. **Sequential ~2.5h wall-clock.** Per-repo runs are short, but the loop
   can't be parallelized safely (PyPI rate limits, OIDC token reuse).
7. **Layer 1 fails → Layer 2 must be skipped.** If crackerjack's own publish
   fails, the patched version never reaches PyPI, and Layer 2's `--upgrade --all-groups`
   won't pick up the fix. Abort Layer 2 entirely; fix Layer 1; restart from
   Layer 1.

## Rollback

- **Layer 1**: revert the commit in /Users/les/Projects/crackerjack, run
  crackerjack's own loop again (this will publish the reverted version).
- **Layer 2 per repo**: `git reset --hard <pre-loop-sha>` to undo bump + tag.
  PyPI cannot be un-published (only yanked via PyPI admin).
- **Whole loop**: revert commits in each repo, un-yank PyPI versions via admin.

## Observability

- Crackerjack prints structured phase output. Capture per-repo with
  `tee /tmp/crackerjack-<repo>-$(date -I).log`.
- Layer 0 baseline: capture in `/tmp/baseline-<repo>.txt` for diff at the end.
- PyPI publish confirmation: `✅ Successfully published` in crackerjack output.
- Tag-push confirmation: `git ls-remote origin 'refs/tags/vX.Y.Z'` returns SHA.
