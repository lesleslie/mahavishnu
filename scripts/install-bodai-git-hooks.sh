#!/bin/sh
# install-bodai-git-hooks.sh — Operator-install step (Phase 12a Task 4).
#
# Replaces the legacy per-clone ``.git/hooks/{pre-commit, post-commit,
# post-merge, post-rewrite}`` bash scripts with one-line wrappers that
# exec ``mahavishnu git-hook <event>`` via uv. The legacy wrappers (see
# ``git log -p .git/hooks/post-commit`` for the previous shape) called
# ``mahavishnu index repo --trigger git-event`` and did NOT publish to
# the bus; the new wrappers route through the bodai_hook_bridge (spec
# §4.13) so every git lifecycle event fans out to the Oneiric bus.
#
# Usage:
#   ./scripts/install-bodai-git-hooks.sh           # install (idempotent)
#   ./scripts/install-bodai-git-hooks.sh --force   # overwrite existing
#   ./scripts/install-bodai-git-hooks.sh --uninstall
#   ./scripts/install-bodai-git-hooks.sh --help
#
# Operator-side script — NOT invoked by ``uv run mahavishnu``. Run once
# per clone (or whenever the dispatcher signature changes).
#
# Per-clone git hooks live OUTSIDE version control, so this script is
# version-controlled but the resulting ``.git/hooks/*`` files are not.
# Re-run this script after ``git clone`` to wire up the dispatcher.

set -eu

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

force=0
uninstall=0
while [ $# -gt 0 ]; do
    case "$1" in
        --force)
            force=1
            shift
            ;;
        --uninstall)
            uninstall=1
            shift
            ;;
        --help|-h)
            sed -n '2,30p' "$0"
            exit 0
            ;;
        *)
            printf "install-bodai-git-hooks: unknown arg %s\n" "$1" >&2
            exit 2
            ;;
    esac
done

# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------

if [ -z "${GIT_DIR:-}" ] && ! git rev-parse --git-dir >/dev/null 2>&1; then
    echo "install-bodai-git-hooks: not inside a git working tree" >&2
    exit 1
fi

hooks_dir=$(git rev-parse --git-dir)/hooks
mkdir -p "$hooks_dir"

# ---------------------------------------------------------------------------
# Uninstall mode
# ---------------------------------------------------------------------------

if [ "$uninstall" -eq 1 ]; then
    for hook in pre-commit post-commit post-merge post-rewrite; do
        path="$hooks_dir/$hook"
        if [ -f "$path" ] && head -n 1 "$path" | grep -q "#!/bin/sh"; then
            # Only remove wrappers that we wrote (have our marker comment).
            if grep -q "install-bodai-git-hooks.sh" "$path" 2>/dev/null; then
                rm -f "$path"
                echo "removed $path"
            else
                echo "skipping $path (not our wrapper)" >&2
            fi
        fi
    done
    exit 0
fi

# ---------------------------------------------------------------------------
# Wrapper templates
# ---------------------------------------------------------------------------

# Standard wrapper — used for post-commit, post-merge, post-rewrite.
# The handler at mahavishnu/git_hook_handlers.py runs the legacy action
# (crackerjack / mahavishnu jot capture) AND publishes the bridge event.
# Using $0 as the event name means all 4 wrappers are identical 4-line
# scripts — the install script writes them from one template.
read -r -d '' standard_wrapper <<'WRAPPER' || true
#!/bin/sh
# Managed by scripts/install-bodai-git-hooks.sh (Phase 12a Task 4).
# Remove with: scripts/install-bodai-git-hooks.sh --uninstall
# Replaces the legacy "mahavishnu index repo --trigger git-event" wrapper.
# The bodai_hook_bridge (mahavishnu/bodai_hook_bridge.py, spec §4.13)
# publishes a fire-and-forget event envelope so subscribers can react.
exec uv run --project "$PWD" mahavishnu git-hook "$(basename "$0")" "$@"
WRAPPER

# Pre-commit wrapper — adds project-specific guards BEFORE the standard
# crackerjack dispatch. These guards (secrets audit, findings.md budget)
# are mahavishnu-repo-specific governance, NOT universal pre-commit
# concerns, so they belong in the wrapper (per-clone) rather than in
# mahavishnu/git_hook_handlers.handle_pre_commit (universal).
read -r -d '' precommit_wrapper <<'PRECOMMIT' || true
#!/bin/sh
# Managed by scripts/install-bodai-git-hooks.sh (Phase 12a Task 4).
# Remove with: scripts/install-bodai-git-hooks.sh --uninstall
# Pre-commit: project-specific guards (secrets audit + findings budget)
# THEN the standard crackerjack fast_hooks dispatch via the bridge.
if [ -f "scripts/audit_no_secrets_in_mcp.py" ]; then
    python3 scripts/audit_no_secrets_in_mcp.py || exit 1
fi
if [ -f "docs/audit-inventory/findings.md" ] && [ -f "scripts/validate_findings.py" ]; then
    test "$(wc -l < docs/audit-inventory/findings.md)" -le 250 || { echo "findings.md exceeds 250-line budget"; exit 1; }
    python3 scripts/validate_findings.py docs/audit-inventory/findings.md || exit 1
fi
exec uv run --project "$PWD" mahavishnu git-hook "$(basename "$0")" "$@"
PRECOMMIT

# ---------------------------------------------------------------------------
# Install loop
# ---------------------------------------------------------------------------

write_hook() {
    hook=$1
    content=$2
    path="$hooks_dir/$hook"
    if [ -f "$path" ] && [ "$force" -eq 0 ]; then
        echo "skipping $path (already exists; use --force to overwrite)"
        return 0
    fi
    printf "%s\n" "$content" > "$path"
    chmod +x "$path"
    echo "wrote $path"
}

write_hook pre-commit "$precommit_wrapper"
write_hook post-commit "$standard_wrapper"
write_hook post-merge "$standard_wrapper"
write_hook post-rewrite "$standard_wrapper"

echo
echo "Bodai git hooks installed. Verify with: ls -la $hooks_dir"
echo "Uninstall with: scripts/install-bodai-git-hooks.sh --uninstall"
