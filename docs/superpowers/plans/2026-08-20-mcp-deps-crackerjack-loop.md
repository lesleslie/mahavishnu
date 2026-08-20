# `*-mcp` Dep Refresh + Crackerjack Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refresh `oneiric` + `mcp-common` in all 15 `*-mcp` repos and publish a new version of each to PyPI via `crackerjack run -p minor`, with annotated git tags pushed to origin.

**Architecture:** Three sequential layers: (0) pre-flight gate across all 15 repos to verify clean state, (1) one-line patch + own publish of `crackerjack` itself so per-repo runs resolve to the patched PyPI version, (2) sequential per-repo loop: pre-flight → `uv add --upgrade-package oneiric --upgrade-package mcp-common --upgrade-package crackerjack` → `crackerjack run -v -p minor` → tag fix-up → next.

**Tech Stack:** Python 3.13, uv (with `--upgrade` semantics per memory `uv-sync-upgrade-minimizes-version.md`), crackerjack (PyPI published workflow), PyPI via `UV_PUBLISH_TOKEN`, git annotated tags.

## Global Constraints

- Working directory: `/Users/les/Projects/<repo>` (each `*-mcp` repo lives in `/Users/les/Projects/`).
- For all `uv` invocations in `*-mcp` repos: strip `VIRTUAL_ENV`, `UV_ACTIVE`, `UV_PROJECT_ENVIRONMENT` per memory `uv-active-and-virtual-env-cross-repo`. Use `env -u VAR1 -u VAR2 ... uv ...`.
- For all `git commit` invocations across all repos: use `-c user.email=les@wedgwoodwebworks.com -c user.name=les` per memory `git-author-email-correct-domain`.
- Use `uv add --upgrade-package oneiric --upgrade-package mcp-common --upgrade-package crackerjack` (NOT broad `--upgrade --all-groups`). This is critical: `--upgrade` downgrades to MINIMUM-version-satisfying-constraints per memory `uv-sync-upgrade-minimizes-version.md`, which would resolve `crackerjack>=0.54.3` to 0.54.3 instead of the new patched version. `--upgrade-package <name>` minimizes nothing and forces the new crackerjack to land.
- Pre-flight is a HARD GATE: `git status --porcelain` MUST be empty. Abort if not.
- PyPI publish uses `UV_PUBLISH_TOKEN` (NOT OIDC) per spec Risk #2.
- PyPI version divergence from local `pyproject.toml` is also a HARD ABORT.
- Sequential per repo; do not parallelize (PyPI rate limits + audit trail).
- Repo order: alphabetical: css-mcp, excalidraw-mcp, graphics-mcp, langsmith-mcp, mailgun-mcp, neo4j-mcp, opera-cloud-mcp, penpot-api-mcp, porkbun-dns-mcp, porkbun-domain-mcp, raindropio-mcp, spline-mcp, synxis-crs-mcp, synxis-pms-mcp, unifi-mcp.

---

## Task 1: Pre-flight gate across all 15 repos

**Files:** None modified. Output: baseline snapshots in `/tmp/`.

**Interfaces:**
- Produces: `/tmp/baseline-<repo>.txt` per repo (PyPI version, local commit SHA, dirty-state check)
- Produces: aggregate report at end

- [ ] **Step 1: Create the pre-flight script**

```bash
cat > /tmp/preflight.sh <<'EOF'
#!/bin/bash
# Pre-flight: verify clean state + record baseline for all 15 *-mcp repos
set -uo pipefail

REPOS=(
    css-mcp excalidraw-mcp graphics-mcp langsmith-mcp mailgun-mcp
    neo4j-mcp opera-cloud-mcp penpot-api-mcp porkbun-dns-mcp porkbun-domain-mcp
    raindropio-mcp spline-mcp synxis-crs-mcp synxis-pms-mcp unifi-mcp
)

FAILED=0
for repo in "${REPOS[@]}"; do
    cd "/Users/les/Projects/$repo" || { echo "MISSING: $repo"; FAILED=1; continue; }

    outfile="/tmp/baseline-$repo.txt"
    {
        echo "=== $repo ==="
        echo "date: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
        echo "commit: $(git log --oneline -1)"
        echo "pyproject_version: $(python3 -c "import tomllib; print(tomllib.loads(open('pyproject.toml').read())['project']['version'])")"
        # PyPI package name = directory name with -mcp preserved (e.g. css-mcp → css-mcp on PyPI)
        # Most use the same name; if pip index fails, the script records "unknown"
        pypi_ver=$(pip index versions "$repo" 2>/dev/null | head -1)
        echo "pypi_version: ${pypi_ver:-unknown}"
        echo "dirty: $(git status --porcelain | head -5)"
        echo "dirty_count: $(git status --porcelain | wc -l | tr -d ' ')"
    } > "$outfile"

    if [ -n "$(git status --porcelain)" ]; then
        echo "� DIRTY: $repo (see $outfile)"
        FAILED=1
    else
        echo "✓ clean: $repo"
    fi
done

if [ "$FAILED" -ne 0 ]; then
    echo "PRE-FLIGHT FAILED. Abort and surface dirty repos to user."
    exit 1
fi
echo "PRE-FLIGHT PASSED for all 15 repos."
EOF
chmod +x /tmp/preflight.sh
```

- [ ] **Step 2: Run the pre-flight script**

```bash
/tmp/preflight.sh
```

Expected: All 15 repos show `✓ clean`. If any show `✗ DIRTY`, STOP — surface to user per spec.

- [ ] **Step 3: Verify baseline files exist**

```bash
ls -la /tmp/baseline-*.txt | wc -l
```
Expected: 15

- [ ] **Step 4: Spot-check one baseline file**

```bash
cat /tmp/baseline-css-mcp.txt
```
Expected: contains date, commit, pyproject_version, pypi_version, dirty (empty), dirty_count (0).

- [ ] **Step 5: Commit (no code changes; this task produces snapshots only)**

No commit needed for this task.

---

## Task 2: Patch crackerjack — one-line fix to `publish_manager.py:676`

**Files:**
- Modify: `/Users/les/Projects/crackerjack/crackerjack/managers/publish_manager.py:676`

**Interfaces:**
- Produces: patched function `create_git_tag_local(self, version: str) -> bool` that creates **annotated** tags via `git tag -a v{version} -m "Release v{version}"` instead of lightweight.

- [ ] **Step 1: Verify pre-flight on crackerjack repo**

```bash
cd /Users/les/Projects/crackerjack
test -z "$(git status --porcelain)" && echo "clean" || { echo "DIRTY"; exit 1; }
```
Expected: `clean`. If DIRTY, abort and surface to user.

- [ ] **Step 2: Read the current line**

```bash
sed -n '676p' /Users/les/Projects/crackerjack/crackerjack/managers/publish_manager.py
```
Expected output:
```
        result = self._run_command(["git", "tag", f"v{version}"])
```

- [ ] **Step 3: Apply the one-line patch**

```bash
cd /Users/les/Projects/crackerjack
# Use Edit tool to replace the line
# old_string:         result = self._run_command(["git", "tag", f"v{version}"])
# new_string:         result = self._run_command(["git", "tag", "-a", f"v{version}", "-m", f"Release v{version}"])
```

Use the Edit tool to make the exact replacement shown. Do NOT modify any other line in the file.

- [ ] **Step 4: Verify the patch**

```bash
sed -n '676p' /Users/les/Projects/crackerjack/crackerjack/managers/publish_manager.py
```
Expected output:
```
        result = self._run_command(["git", "tag", "-a", f"v{version}", "-m", f"Release v{version}"])
```

- [ ] **Step 5: Run crackerjack's own unit tests for publish_manager**

```bash
cd /Users/les/Projects/crackerjack
unset VIRTUAL_ENV UV_ACTIVE UV_PROJECT_ENVIRONMENT
env -u VIRTUAL_ENV -u UV_ACTIVE -u UV_PROJECT_ENVIRONMENT \
    uv run pytest tests/ -k "publish_manager or tag" -v
```

Expected: PASS. If any test fails, abort and surface.

- [ ] **Step 6: Commit the patch in crackerjack repo**

```bash
cd /Users/les/Projects/crackerjack
git -c user.email=les@wedgwoodwebworks.com -c user.name=les \
    add crackerjack/managers/publish_manager.py
git -c user.email=les@wedgwoodwebworks.com -c user.name=les \
    commit -m "fix(crackerjack): create annotated git tag in create_git_tag_local

publish_manager.py:676 was running 'git tag v{version}' which creates
a lightweight tag. The subsequent 'git push --follow-tags' only pushes
annotated tags, so the tag never reached origin. Switching to
'git tag -a v{version} -m \"Release v{version}\"' creates an annotated
tag that --follow-tags will propagate.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 3: Publish patched crackerjack to PyPI

**Files:** None modified locally (crackerjack's own loop handles it).

**Interfaces:**
- Produces: New `crackerjack>=X.Y.Z` on PyPI (where X.Y.Z is the version in `/Users/les/Projects/crackerjack/pyproject.toml` after the patch's auto-bump). Local consumers will resolve to this on next `uv sync`.

- [ ] **Step 1: Confirm crackerjack env has UV_PUBLISH_TOKEN**

```bash
echo "${UV_PUBLISH_TOKEN:0:4}"
```
Expected: `pypi-` (PyPI token prefix). If empty/wrong, surface to user; PyPI publish will fail.

- [ ] **Step 2: Run crackerjack's own `-p minor` loop**

```bash
cd /Users/les/Projects/crackerjack
unset VIRTUAL_ENV UV_ACTIVE UV_PROJECT_ENVIRONMENT
env -u VIRTUAL_ENV -u UV_ACTIVE -u UV_PROJECT_ENVIRONMENT \
    uv run crackerjack run -v -p minor
```

Expected: All phases pass; PyPI publish succeeds; commit pushed; tag created. If any phase fails, fix inline and re-run.

- [ ] **Step 3: Verify the new crackerjack is on PyPI**

```bash
pip index versions crackerjack | head -3
```
Expected: New version at top (higher than 0.73.5 — confirm by eye).

- [ ] **Step 4: Verify the tag is annotated AND on origin**

```bash
cd /Users/les/Projects/crackerjack
git fetch origin
echo "=== local tag type ==="
git for-each-ref refs/tags/v\* --format='%(objecttype) %(refname:short)' | tail -1
echo "=== remote tag ==="
git ls-remote origin 'refs/tags/v*' | tail -1
```
Expected:
- `local tag type`: `tag vX.Y.Z` (annotated)
- `remote tag`: shows the new tag SHA

- [ ] **Step 5: No commit needed (crackerjack's own loop committed already)**

Verify final state of `/Users/les/Projects/crackerjack`:
```bash
cd /Users/les/Projects/crackerjack
git log --oneline -3
git status --porcelain
```
Expected: clean working tree, recent commits show "chore: bump version" + the patch.

---

## Task 4: Per-repo loop — first repo (css-mcp)

**Files:** Inside `/Users/les/Projects/css-mcp/`:
- Modify: `pyproject.toml` (crackerjack auto-edits)
- Modify: `uv.lock` (uv sync)
- Optional: `src/<pkg>/__init__.py`, `CHANGELOG.md`

**Interfaces:**
- Consumes: Layer 0 baseline at `/tmp/baseline-css-mcp.txt`
- Consumes: Layer 1 published crackerjack (Task 3)
- Produces: New PyPI release of `css-mcp` with annotated tag `vX.Y.Z` on origin

- [ ] **Step 1: Pre-flight gate**

```bash
cd /Users/les/Projects/css-mcp
# Dirty tree check
test -z "$(git status --porcelain)" || { echo "DIRTY: css-mcp"; git status --porcelain; exit 1; }
# PyPI version match check
pypi_ver=$(pip index versions css-mcp 2>/dev/null | head -1)
local_ver=$(python3 -c "import tomllib; print(tomllib.loads(open('pyproject.toml').read())['project']['version'])")
test "$pypi_ver" = "$local_ver" || { echo "PYPI_DIVERGED: css-mcp (pypi=$pypi_ver local=$local_ver)"; exit 1; }
echo "✓ pre-flight passed for css-mcp"
```

Expected: `✓ pre-flight passed for css-mcp`. If either check fails, abort and surface.

- [ ] **Step 2: Refresh deps**

```bash
cd /Users/les/Projects/css-mcp
unset VIRTUAL_ENV UV_ACTIVE UV_PROJECT_ENVIRONMENT
env -u VIRTUAL_ENV -u UV_ACTIVE -u UV_PROJECT_ENVIRONMENT \
    uv add --upgrade-package oneiric --upgrade-package mcp-common --upgrade-package crackerjack
```

Expected: pyproject.toml constraint pins get bumped (or stay the same if already satisfied), uv.lock resolves to latest of each. Critical: `--upgrade-package` (NOT `--upgrade`) is used because `--upgrade` downgrades to MINIMUM-version-satisfying-constraints per memory `uv-sync-upgrade-minimizes-version.md`. With `--upgrade --all-groups`, `crackerjack>=0.54.3` would resolve to 0.54.3, not the new patched version. `--upgrade-package crackerjack` forces the new release.

Quick sanity check:
```bash
grep -E "^(name|version):" /Users/les/Projects/css-mcp/uv.lock | grep -E "(oneiric|mcp-common|crackerjack)"
```
Expected: versions for oneiric, mcp-common, AND crackerjack should be ≥ the previous baseline. The crackerjack version MUST be the new patched one (Layer 1); if it shows an older version, `--upgrade-package` didn't fire and the loop will use unpatched crackerjack.

- [ ] **Step 3: Commit the lockfile change (separate from bump commit)**

```bash
cd /Users/les/Projects/css-mcp
# If pyproject.toml changed (e.g., constraint bumps), commit it together
git -c user.email=les@wedgwoodwebworks.com -c user.name=les add -A
git -c user.email=les@wedgwoodwebworks.com -c user.name=les \
    diff --cached --quiet || git -c user.email=les@wedgwoodwebworks.com -c user.name=les \
    commit -m "chore(css-mcp): refresh oneiric + mcp-common deps"
```

Note: This step is for separation of concerns. If `crackerjack`'s bump commit ends up containing only `pyproject.toml` + `uv.lock`, drift detection in Step 6 is unambiguous.

- [ ] **Step 4: Run crackerjack**

```bash
cd /Users/les/Projects/css-mcp
unset VIRTUAL_ENV UV_ACTIVE UV_PROJECT_ENVIRONMENT
env -u VIRTUAL_ENV -u UV_ACTIVE -u UV_PROJECT_ENVIRONMENT \
    uv run crackerjack run -v -p minor
```

Expected: all phases pass; bump committed; PyPI published; lightweight tag created; tag push no-ops (the bug). If any phase fails, fix inline, re-run without `-p` until clean, then with `-p`.

- [ ] **Step 5: Tag fix-up (always)**

```bash
cd /Users/les/Projects/css-mcp
new_ver=$(python3 -c "import tomllib; print(tomllib.loads(open('pyproject.toml').read())['project']['version'])")
git tag -fa "v$new_ver" HEAD -m "Release v$new_ver ($(date -u +%Y-%m-%d))"
git push origin "v$new_ver" --force
echo "✓ tagged v$new_ver"
```

Expected: `✓ tagged v$new_ver`. If `git push` fails with auth error, surface.

- [ ] **Step 6: Drift check on the bump commit**

```bash
cd /Users/les/Projects/css-mcp
bump_sha=$(git log --oneline --grep="^chore: bump version" -1 --format=%H)
if [ -n "$bump_sha" ]; then
    echo "=== bump commit $bump_sha files ==="
    git show --stat "$bump_sha" --format= | tail -n +2
    # Drift detection: bump should only contain pyproject.toml + uv.lock (+ maybe __init__.py, CHANGELOG.md)
    unrelated=$(git show --name-only --format= "$bump_sha" | grep -vE "^(pyproject\.toml|uv\.lock|.*__init__\.py|CHANGELOG\.md)$" | grep -v "^$" | wc -l | tr -d ' ')
    if [ "$unrelated" -gt 0 ]; then
        echo "⚠ DRIFT_BUNDLED: $unrelated unrelated files in bump commit"
        # Recovery: surgical reset + targeted re-add
        git reset --soft HEAD~1
        git reset HEAD
        git add pyproject.toml uv.lock
        git -c user.email=les@wedgwoodwebworks.com -c user.name=les \
            commit -m "chore(css-mcp): bump version to $new_ver (drift recovered)"
        git push origin HEAD
    fi
fi
```

Expected: either no drift (no message) or "DRIFT_RECOVERED" message. If unrelated files remain after recovery, abort and surface.

- [ ] **Step 7: Verify final state**

```bash
cd /Users/les/Projects/css-mcp
echo "=== final state ==="
git log --oneline -5
git status --porcelain
echo "=== PyPI ==="
pip index versions css-mcp | head -1
echo "=== local tag type ==="
git for-each-ref refs/tags/v\* --format='%(objecttype) %(refname:short)' | tail -1
echo "=== remote tag ==="
git ls-remote origin 'refs/tags/v*' | tail -1
```

Expected:
- Last commit: `chore(css-mcp): bump version to X.Y.Z` (or "drift recovered" variant)
- Clean working tree
- PyPI version = local version
- `tag vX.Y.Z` (annotated)
- Tag SHA present in `git ls-remote`

- [ ] **Step 8: Move to next repo**

Continue to Task 5. Repeat Task 4 with `excalidraw-mcp` substituted for `css-mcp` everywhere. Each of Tasks 5-18 mirrors Task 4 for one repo.

---

## Tasks 5-18: Per-repo loop — remaining 14 repos

**Files:** Same per-repo pattern as Task 4.

**For each repo in**: `excalidraw-mcp graphics-mcp langsmith-mcp mailgun-mcp neo4j-mcp opera-cloud-mcp penpot-api-mcp porkbun-dns-mcp porkbun-domain-mcp raindropio-mcp spline-mcp synxis-crs-mcp synxis-pms-mcp unifi-mcp`

**Each task is a verbatim copy of Task 4 with these substitutions:**
- `css-mcp` → target repo name in all paths
- PyPI package name = directory name (e.g., `excalidraw-mcp`)

**Per-task acceptance:**
- All 8 steps of Task 4 pass for the target repo
- Final state shows new PyPI version + annotated tag on origin + clean tree

**Tasks:**

| Task | Repo |
|---|---|
| 5 | excalidraw-mcp |
| 6 | graphics-mcp |
| 7 | langsmith-mcp |
| 8 | mailgun-mcp |
| 9 | neo4j-mcp |
| 10 | opera-cloud-mcp |
| 11 | penpot-api-mcp |
| 12 | porkbun-dns-mcp |
| 13 | porkbun-domain-mcp |
| 14 | raindropio-mcp |
| 15 | spline-mcp |
| 16 | synxis-crs-mcp |
| 17 | synxis-pms-mcp |
| 18 | unifi-mcp |

---

## Task 19: Final verification across all 15 repos

**Files:** None modified. Produces a final report.

- [ ] **Step 1: Verify all 15 repos have new PyPI version**

```bash
for repo in css-mcp excalidraw-mcp graphics-mcp langsmith-mcp mailgun-mcp \
            neo4j-mcp opera-cloud-mcp penpot-api-mcp porkbun-dns-mcp porkbun-domain-mcp \
            raindropio-mcp spline-mcp synxis-crs-mcp synxis-pms-mcp unifi-mcp; do
    pypi=$(pip index versions "$repo" 2>/dev/null | head -1)
    local=$(python3 -c "import tomllib; print(tomllib.loads(open('/Users/les/Projects/$repo/pyproject.toml').read())['project']['version'])" 2>/dev/null)
    if [ "$pypi" = "$local" ] && [ -n "$pypi" ]; then
        echo "✓ $repo: $pypi"
    else
        echo "✗ $repo: pypi=$pypi local=$local"
    fi
done
```
Expected: 15 `✓` lines.

- [ ] **Step 2: Verify all 15 repos have annotated tag on origin**

```bash
for repo in css-mcp excalidraw-mcp graphics-mcp langsmith-mcp mailgun-mcp \
            neo4j-mcp opera-cloud-mcp penpot-api-mcp porkbun-dns-mcp porkbun-domain-mcp \
            raindropio-mcp spline-mcp synxis-crs-mcp synxis-pms-mcp unifi-mcp; do
    cd "/Users/les/Projects/$repo"
    tag_type=$(git for-each-ref refs/tags/v\* --format='%(objecttype)' | tail -1)
    remote_sha=$(git ls-remote origin 'refs/tags/v*' 2>/dev/null | tail -1 | awk '{print $1}')
    if [ "$tag_type" = "tag" ] && [ -n "$remote_sha" ]; then
        echo "✓ $repo: annotated tag on origin"
    else
        echo "✗ $repo: tag_type=$tag_type remote_sha=$remote_sha"
    fi
done
```
Expected: 15 `✓` lines.

- [ ] **Step 3: Verify all 15 repos have clean working trees**

```bash
for repo in css-mcp excalidraw-mcp graphics-mcp langsmith-mcp mailgun-mcp \
            neo4j-mcp opera-cloud-mcp penpot-api-mcp porkbun-dns-mcp porkbun-domain-mcp \
            raindropio-mcp spline-mcp synxis-crs-mcp synxis-pms-mcp unifi-mcp; do
    cd "/Users/les/Projects/$repo"
    if [ -z "$(git status --porcelain)" ]; then
        echo "✓ $repo: clean"
    else
        echo "� $repo: dirty"
        git status --porcelain | head -3
    fi
done
```
Expected: 15 `✓` lines.

- [ ] **Step 4: Verify crackerjack passes clean on each main (no `-p`)**

```bash
for repo in css-mcp excalidraw-mcp graphics-mcp langsmith-mcp mailgun-mcp \
            neo4j-mcp opera-cloud-mcp penpot-api-mcp porkbun-dns-mcp porkbun-domain-mcp \
            raindropio-mcp spline-mcp synxis-crs-mcp synxis-pms-mcp unifi-mcp; do
    cd "/Users/les/Projects/$repo"
    unset VIRTUAL_ENV UV_ACTIVE UV_PROJECT_ENVIRONMENT
    env -u VIRTUAL_ENV -u UV_ACTIVE -u UV_PROJECT_ENVIRONMENT \
        uv run crackerjack run > /tmp/cj-final-$repo.log 2>&1
    if [ $? -eq 0 ]; then
        echo "✓ $repo: crackerjack clean"
    else
        echo "✗ $repo: crackerjack FAILED"
        tail -20 /tmp/cj-final-$repo.log
    fi
done
```
Expected: 15 `✓` lines. If any `�`, fix inline (the crackerjack run without `-p` should not trigger publish; if hooks fail, fix and re-run).

- [ ] **Step 5: Generate final report**

```bash
echo "=== crackerjack-deps-loop final report ==="
echo "date: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo ""
echo "crackerjack version (Layer 1):"
pip index versions crackerjack | head -1
echo ""
echo "Per-repo results:"
for repo in css-mcp excalidraw-mcp graphics-mcp langsmith-mcp mailgun-mcp \
            neo4j-mcp opera-cloud-mcp penpot-api-mcp porkbun-dns-mcp porkbun-domain-mcp \
            raindropio-mcp spline-mcp synxis-crs-mcp synxis-pms-mcp unifi-mcp; do
    pypi=$(pip index versions "$repo" 2>/dev/null | head -1)
    local=$(python3 -c "import tomllib; print(tomllib.loads(open('/Users/les/Projects/$repo/pyproject.toml').read())['project']['version'])" 2>/dev/null)
    baseline=$(grep "pypi_version:" "/tmp/baseline-$repo.txt" 2>/dev/null | awk '{print $2}')
    echo "  $repo: $baseline → $pypi (local=$local)"
done
```

Expected: report shows baseline → final version for each of 15 repos.
