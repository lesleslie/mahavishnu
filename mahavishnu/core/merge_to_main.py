"""Orchestration of the trunk-based agent-review workflow.

Per spec §4 (Components). Stages 2-6: ensemble review, crackerjack gate,
squash-merge, auto-push, cleanup. Cross-session resume via
.review-state.json at the worktree root. Idempotent and re-entrant.

Implements: REQ-004, REQ-009, REQ-013, REQ-014
"""
from __future__ import annotations

import fcntl
import json
import re
import sys
from pathlib import Path
from typing import Any

REVIEW_STATE_SCHEMA_VERSION: int = 1
REVIEW_STATE_FILENAME: str = ".review-state.json"

# Valid verdict decisions per spec §4.4. Anything else => block (fail-loud).
VALID_DECISIONS: frozenset[str] = frozenset({"pass", "needs_adjustment", "block"})

# Parses `<verdict>decision: <word> note: <text></verdict>`. The note group
# is optional; surrounding whitespace and case are tolerated so a slightly
# sloppy agent still gets a parse instead of a malformed block.
VERDICT_RE = re.compile(
    r"<verdict>\s*decision:\s*(\S+)(?:\s+note:\s*(.*?))?\s*</verdict>",
    re.IGNORECASE | re.DOTALL,
)

# Exit codes (spec §4.1 Outputs)
EXIT_OK = 0
EXIT_REVIEW_FAILURE = 1
EXIT_CRACKERJACK_FAILURE = 2
EXIT_REBASE_CONFLICT = 3
EXIT_PUSH_DIVERGENCE = 4
EXIT_CLEANUP_FAILURE = 5


def write_review_state(worktree_root: Path, state: dict[str, Any]) -> None:
    """Atomically write the review-state JSON for a worktree.

    Uses fcntl.flock for cross-process safety (in case two merge
    invocations run concurrently on the same worktree).
    """
    target = worktree_root / REVIEW_STATE_FILENAME
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(state, indent=2, sort_keys=True)
    lock_path = worktree_root / ".review-state.lock"
    lock_path.touch(exist_ok=True)
    with open(lock_path, "w") as lock_fd:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        try:
            tmp = target.with_suffix(".json.tmp")
            tmp.write_text(payload)
            tmp.rename(target)
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)


def read_review_state(worktree_root: Path) -> dict[str, Any] | None:
    """Read the review-state JSON. Returns None if missing or corrupt."""
    target = worktree_root / REVIEW_STATE_FILENAME
    if not target.exists():
        return None
    try:
        return json.loads(target.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        # Corrupt or unreadable; spec REQ-014 graceful fallback.
        print(
            f"[merge_to_main] corrupt .review-state.json: {exc!r}; "
            f"falling back to stage 2.",
            file=sys.stderr,
        )
        return None


def make_review_state(
    ephemeral_branch: str,
    base: str,
    pre_rebase_base_sha: str,
    stages_completed: list[str],
    current_stage: str,
    stage_failed: str | None,
    reviewers_invoked: list[dict[str, Any]],
    audit_log_path: str | None,
    session_buddy_reflection_id: str | None,
) -> dict[str, Any]:
    """Construct a fresh review-state dict per spec §4.4 schema."""
    return {
        "schema_version": REVIEW_STATE_SCHEMA_VERSION,
        "ephemeral_branch": ephemeral_branch,
        "base": base,
        "pre_rebase_base_sha": pre_rebase_base_sha,
        "stages_completed": stages_completed,
        "current_stage": current_stage,
        "stage_failed": stage_failed,
        "reviewers_invoked": reviewers_invoked,
        "audit_log_path": audit_log_path,
        "session_buddy_reflection_id": session_buddy_reflection_id,
    }


def parse_verdict(response: str) -> dict[str, str]:
    """Parse `<verdict>decision: ...</verdict>` block from agent output.

    Per spec §4.4: missing or malformed block returns decision='block'
    (fail-loud) so the merge gates on the parser. The 'note' field carries
    either the agent's explanation (on success) or a 'malformed: ...'
    string describing what was wrong (on failure).
    """
    match = VERDICT_RE.search(response)
    if match is None:
        return {
            "decision": "block",
            "note": "malformed: <verdict> block not found in agent response",
        }
    decision_raw = match.group(1).strip().lower()
    note = (match.group(2) or "").strip()
    if decision_raw not in VALID_DECISIONS:
        return {
            "decision": "block",
            "note": f"malformed: unknown decision {decision_raw!r}",
        }
    return {"decision": decision_raw, "note": note}
