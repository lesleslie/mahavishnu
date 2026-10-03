#!/usr/bin/env bash
# Migrate one Bodai core repo's plans/specs to docs/{plans,specs}/ canonical paths.
#
# Pattern (mirrors mahavishnu's 8207138a → 71014fca → 815e9e07 → 3ad383d5 → 2ce3d897):
#   1. .gitignore: blanket .superpowers/ + add archive exceptions
#   2. Move plans/specs/ to docs/{plans,specs}/ (handle existing docs/plans/)
#   3. Delete old docs/superpowers/{plans,specs}/ paths
#   4. Untrack archived files at old .archive/ paths (gitignored -> git add -u misses them)
#   5. Rewrite in-repo references
#
# Run from the target repo's working tree as main checkout.
# Usage: scripts/migrate_plans_specs_to_canonical_paths.sh [--dry-run] [REPO_DIR]

set -euo pipefail

DRY_RUN=0
if [ "${1:-}" = "--dry-run" ]; then
  DRY_RUN=1
  shift
fi

REPO_DIR="${1:-$(pwd)}"
cd "$REPO_DIR"

if [ ! -d .git ]; then
  echo "FATAL: $REPO_DIR is not a git repository" >&2
  exit 1
fi

if [ -n "$(git status --porcelain)" ]; then
  echo "FATAL: working tree has uncommitted changes; commit or stash first" >&2
  exit 1
fi

if [ ! -d docs/superpowers/plans ] && [ ! -d docs/superpowers/specs ]; then
  echo "FATAL: no docs/superpowers/{plans,specs}/ to migrate (already clean)" >&2
  exit 1
fi

echo "==> Repo: $REPO_DIR"
echo "    plans to migrate: $(git ls-files docs/superpowers/plans/ | wc -l | tr -d ' ')"
echo "    specs to migrate: $(git ls-files docs/superpowers/specs/ | wc -l | tr -d ' ')"

# ============================================================
# 1. .gitignore: blanket .superpowers/ + archive exceptions
# ============================================================
echo ""
echo "==> Step 1: update .gitignore"

if grep -q "^\.superpowers/$" .gitignore; then
  echo "    .superpowers/ already blanket-gitignored; skipping .gitignore write"
else
  # Replace the existing 3-line partial rule with a blanket + archive exceptions
  if grep -q "^\.superpowers/sdd/" .gitignore; then
    cat > /tmp/gitignore_superpowers_block <<'EOF'
# Superpowers Skill Artifacts (local-only, per-project runtime)
# ============================================================================
# All `.superpowers/` content is scratch: SDD controller workspace
# (briefs, reports, ledger, review packages) keyed by plan-basename, and
# the brainstorm visual-companion's mockup HTML + server-state JSON.
# Plans and specs live at `docs/plans/` and `docs/specs/` instead — they
# are committed under their canonical paths, never under `.superpowers/`.
.superpowers/
EOF
    # Add the archive exceptions (only if not already present)
    if ! grep -q "^\!docs/plans/\.archive/\*\*$" .gitignore; then
      cat >> /tmp/gitignore_superpowers_block <<'EOF'
!docs/plans/.archive/
!docs/plans/.archive/**
!docs/specs/.archive/
!docs/specs/.archive/**
EOF
    fi
    # Use Python to do the in-place edit safely (avoids sed escaping nightmares)
    python3 - <<PYEOF
from pathlib import Path
import re

p = Path(".gitignore")
text = p.read_text()

# Replace the old 3-line rule block with the new one
new_block = Path("/tmp/gitignore_superpowers_block").read_text()
pattern = re.compile(
    r"# Superpowers Skill Artifacts.*?(?=\n# ====|\n# [A-Z])",
    re.DOTALL,
)
if pattern.search(text):
    text = pattern.sub(new_block + "\n", text, count=1)
    p.write_text(text)
    print("    rewrote superpowers gitignore block + added archive exceptions")
else:
    print("    WARN: could not find existing superpowers rule block; append only")
    with p.open("a") as f:
        f.write("\n" + new_block)
PYEOF
  else
    # No existing rule — append blanket + exceptions
    python3 - <<'PYEOF'
from pathlib import Path
p = Path(".gitignore")
extra = """
# Superpowers Skill Artifacts (local-only, per-project runtime)
# ============================================================================
# All `.superpowers/` content is scratch: SDD controller workspace
# (briefs, reports, ledger, review packages) keyed by plan-basename, and
# the brainstorm visual-companion's mockup HTML + server-state JSON.
# Plans and specs live at `docs/plans/` and `docs/specs/` instead — they
# are committed under their canonical paths, never under `.superpowers/`.
.superpowers/
"""
if "!docs/plans/.archive/" not in p.read_text():
    extra += """
!docs/plans/.archive/
!docs/plans/.archive/**
!docs/specs/.archive/
!docs/specs/.archive/**
"""
with p.open("a") as f:
    f.write(extra)
print("    appended .superpowers/ blanket + archive exceptions")
PYEOF
  fi
fi

# ============================================================
# 2. Move plans and specs to docs/{plans,specs}/
# ============================================================
echo ""
echo "==> Step 2: move plans/specs"

mkdir -p docs/plans docs/specs

# Plans: detect collision. If docs/plans/ already exists with content,
# merge: add only NEW files (no overlap), skipping ones that already exist.
if [ -d docs/superpowers/plans ]; then
  existing_count=$(git ls-files docs/plans/ 2>/dev/null | wc -l | tr -d ' ')
  if [ "$existing_count" -gt 0 ]; then
    echo "    docs/plans/ already exists with $existing_count files; merging (skip overlaps)"
    # Detect any filename overlap (shouldn't happen, but safety check)
    overlap=$(comm -12 <(git ls-files docs/superpowers/plans/ 2>/dev/null | xargs -n1 basename | sort -u) \
                       <(git ls-files docs/plans/ 2>/dev/null | xargs -n1 basename | sort -u))
    if [ -n "$overlap" ]; then
      echo "    FATAL: filename overlap detected:"
      echo "$overlap"
      exit 2
    fi
  fi
  # Use git mv to rename the source directory; if dst exists, git mv nests under it.
  # Workaround: rename source first, then merge contents.
  if [ -d docs/superpowers/plans/.archive ]; then
    mkdir -p docs/plans/.archive
    for f in docs/superpowers/plans/.archive/*.md; do
      [ -f "$f" ] || continue
      base=$(basename "$f")
      if [ ! -f "docs/plans/.archive/$base" ]; then
        git mv "$f" "docs/plans/.archive/$base"
      else
        echo "    SKIP overlap: docs/plans/.archive/$base"
      fi
    done
  fi
  for f in docs/superpowers/plans/*.md; do
    [ -f "$f" ] || continue
    base=$(basename "$f")
    if [ ! -f "docs/plans/$base" ]; then
      git mv "$f" "docs/plans/$base"
    else
      echo "    SKIP overlap: docs/plans/$base"
    fi
  done
fi

# Specs: fresh directory, no collision risk in 4/5 (oneiracak = 0 docs/specs/)
if [ -d docs/superpowers/specs ]; then
  if [ -d docs/superpowers/specs/.archive ]; then
    mkdir -p docs/specs/.archive
    for f in docs/superpowers/specs/.archive/*.md; do
      [ -f "$f" ] || continue
      base=$(basename "$f")
      if [ ! -f "docs/specs/.archive/$base" ]; then
        git mv "$f" "docs/specs/.archive/$base"
      fi
    done
  fi
  for f in docs/superpowers/specs/*.md; do
    [ -f "$f" ] || continue
    base=$(basename "$f")
    if [ ! -f "docs/specs/$base" ]; then
      git mv "$f" "docs/specs/$base"
    fi
  done
fi

# ============================================================
# 3. Delete old top-level paths from index (git add -u)
# ============================================================
echo ""
echo "==> Step 3: delete old paths from index"
# If renames already cleared the source path (as with git mv), git add -u
# has nothing to add. Treat that as success.
if git ls-files docs/superpowers/plans/ docs/superpowers/specs/ 2>/dev/null | grep -q .; then
  git add -u docs/superpowers/ 2>&1 | tail -3 || true
else
  echo "    no tracked paths remain at docs/superpowers/{plans,specs}/ (renames cleared them)"
fi

# ============================================================
# 4. Untrack archived files at OLD .archive/ paths
#    (gitignored -> git add -u misses them; explicit --cached)
# ============================================================
echo ""
echo "==> Step 4: untrack old archive paths"
for f in $(git ls-files docs/superpowers/plans/.archive/ docs/superpowers/specs/.archive/ 2>/dev/null); do
  git rm --cached "$f" >/dev/null
done

# ============================================================
# 5. Rewrite in-repo references (sed)
# ============================================================
echo ""
echo "==> Step 5: rewrite in-repo references"
files=$(git grep -l "docs/superpowers/plans\|docs/superpowers/specs" -- ':!docs/superpowers' ':!CHANGELOG.md' 2>/dev/null)
if [ -n "$files" ]; then
  echo "$files" | xargs sed -i '' 's|docs/superpowers/plans|docs/plans|g; s|docs/superpowers/specs|docs/specs|g'
  echo "    rewrote $(echo "$files" | wc -l | tr -d ' ') files"
else
  echo "    no in-repo references to rewrite"
fi

echo ""
echo "==> Migration dry-run complete."
echo "    Run 'git status' to inspect the changes, then commit per the 5-commit pattern."