"""Orchestration of the trunk-based agent-review workflow.

Per spec §4 (Components). Stages 2-6: ensemble review, crackerjack gate,
squash-merge, auto-push, cleanup. Cross-session resume via
.review-state.json at the worktree root. Idempotent and re-entrant.

Implements: REQ-004, REQ-009, REQ-013, REQ-014
"""
from __future__ import annotations

from collections.abc import Callable
import fcntl
import json
from pathlib import Path
import random
import re
import subprocess
import sys
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

# Pinned crackerjack invocation for the merge gate (spec REQ-013).
# The trailing space separates the verb from any appended flags; the
# CI-guard test in tests/unit/core/test_merge_to_main.py asserts this
# starts with "crackerjack run -v " and never contains "-p". The
# publish stage (`-p`) must never fire on the merge path.
CRACKERJACK_INVOCATION: str = "crackerjack run -v "


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


def parse_verdict(agent_text: str) -> dict[str, str]:
    """Parse `<verdict>decision: ...</verdict>` block from agent output.

    Per spec §4.4: missing or malformed block returns decision='block'
    (fail-loud) so the merge gates on the parser. The 'note' field carries
    either the agent's explanation (on success) or a 'malformed: ...'
    string describing what was wrong (on failure).
    """
    match = VERDICT_RE.search(agent_text)
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


# In-repo generalist pool per spec §4.4 (verified 2026-10-03). The random
# generalist is drawn uniformly from this list; each invocation re-shuffles.
AGENT_POOL: list[str] = [
    "performance-review-specialist",
    "test-coverage-review-specialist",
    "critical-audit-specialist",
    "documentation-review-specialist",
    "qa-strategist",
    "observability-incident-lead",
    "architecture-council",
]

# Code-quality specialist per spec §4.4. The spec leaves room for a
# plugin-supplied pr-review-toolkit:code-reviewer fallback; for v1 the
# in-repo critical-audit-specialist is the only available code-reviewer.
_CODE_QUALITY_AGENT: str = "critical-audit-specialist"


def run_review(
    domain_specialist: str,
    generalist_pool: list[str],
    prompt: str,
    dispatcher: Callable[[str, str], str],
) -> list[dict[str, str]]:
    """Run a 3-agent ensemble review (REQ-004, spec §4.4).

    Dispatches the prompt to three reviewers in order:
      1. ``domain_specialist`` (worker-supplied; default ``python-pro`` upstream)
      2. ``_CODE_QUALITY_AGENT`` (constant)
      3. one random pick from ``generalist_pool`` (default ``AGENT_POOL``)

    Each agent's response is parsed via ``parse_verdict``; missing or
    malformed verdict blocks already fail-loud to ``decision='block'``.

    Returns a list of three ``{'agent', 'decision', 'note'}`` dicts in
    dispatch order. The caller is responsible for applying the verdict
    rule order (any block → block; ≥2 pass → proceed; else iterate).
    """
    generalist = random.choice(generalist_pool)
    selected = (domain_specialist, _CODE_QUALITY_AGENT, generalist)
    results: list[dict[str, str]] = []
    for agent in selected:
        response = dispatcher(agent, prompt)
        verdict = parse_verdict(response)
        results.append({
            "agent": agent,
            "decision": verdict["decision"],
            "note": verdict["note"],
        })
    return results


def aggregate_verdicts(verdicts: list[dict[str, str]]) -> str:
    """Apply the spec §4.4 verdict rule order (priority high to low).

    Returns one of: "proceed", "iterate", "block".
    """
    decisions = [v["decision"] for v in verdicts]
    # Rule 1: any block → block (highest priority)
    if "block" in decisions:
        return "block"
    # Rule 2: ≥2 pass → proceed
    pass_count = decisions.count("pass")
    if pass_count >= 2:
        return "proceed"
    # Rule 3: otherwise → iterate
    return "iterate"


def run_crackerjack_gate(worktree_root: Path) -> tuple[int, str]:
    """Run ``crackerjack run -v --exitcode 0`` in ``worktree_root`` (REQ-013).

    Per spec REQ-013, the merge-gate invocation is ``crackerjack run -v``
    (NEVER ``-p``; the publish stage must never fire on the merge path).
    Any non-zero returncode blocks the merge — the call site maps that to
    ``EXIT_CRACKERJACK_FAILURE = 2``.

    Returns ``(returncode, stderr_text)`` verbatim from ``subprocess.run``;
    this wrapper does not re-interpret the result. The split form
    (shell=False) is used so the constant's content cannot trigger shell
    injection if it is ever extended.
    """
    full_cmd = (CRACKERJACK_INVOCATION + "--exitcode 0").split()
    result = subprocess.run(
        full_cmd,
        cwd=worktree_root,
        capture_output=True,
        text=True,
        check=False,
    )
    return (result.returncode, result.stderr)
