"""Orchestration of the trunk-based agent-review workflow.

Per spec §4 (Components). Stages 2-6: ensemble review, crackerjack gate,
squash-merge, auto-push, cleanup. Cross-session resume via
.review-state.json at the worktree root. Idempotent and re-entrant.

Implements: REQ-004, REQ-009, REQ-013, REQ-014
"""

from __future__ import annotations

import argparse
import fcntl
import json
from pathlib import Path
import random
import re
import subprocess
import sys
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

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
            f"[merge_to_main] corrupt .review-state.json: {exc!r}; falling back to stage 2.",
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
        results.append(
            {
                "agent": agent,
                "decision": verdict["decision"],
                "note": verdict["note"],
            }
        )
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
    """Run ``crackerjack run -v`` in ``worktree_root`` (REQ-013).

    Per spec REQ-013, the merge-gate invocation is ``crackerjack run -v``
    (NEVER ``-p``; the publish stage must never fire on the merge path).
    Any non-zero returncode blocks the merge — the call site maps that to
    ``EXIT_CRACKERJACK_FAILURE = 2``.

    Returns ``(returncode, stderr_text)`` verbatim from ``subprocess.run``;
    this wrapper does not re-interpret the result. The split form
    (shell=False) is used so the constant's content cannot trigger shell
    injection if it is ever extended.
    """
    full_cmd = CRACKERJACK_INVOCATION.strip().split()
    result = subprocess.run(
        full_cmd,
        cwd=worktree_root,
        capture_output=True,
        text=True,
        check=False,
    )
    return (result.returncode, result.stderr)


def run_squash_merge(
    worktree_root: Path,
    base: str,
    branch: str,
) -> tuple[int, str]:
    """Stage 4: rebase → re-verify base SHA → squash-merge → semantic commit.

    Per spec §4.5:

    1. ``git rebase <base>`` in ``worktree_root`` to replay the branch
       onto the latest base.
    2. Re-verify the base SHA has not moved (compare ``git rev-parse
       <base>`` against the ``pre_rebase_base_sha`` stored in
       ``.review-state.json``). If it moved, the squash result would
       not be a fast-forward of the new base — abort.
    3. ``git checkout <base>`` (switch the worktree onto the base
       branch in preparation for the squash).
    4. ``git merge --squash <branch>`` (stages changes, does NOT auto-commit).
    5. Semantic commit (``merge: <branch> → <base>``).

    Returns ``(returncode, stderr)`` verbatim. The call site maps any
    non-zero returncode to ``EXIT_REBASE_CONFLICT = 3``. The rebase
    step is the most likely failure point; the squash-merge step is
    a no-op after a clean rebase.

    Implementation note: the checkout happens in the worktree (not
    the main checkout) because the SessionEnd hook always supplies
    ``worktree_root`` as ``cwd``. The worktree is the only place
    where the ephemeral branch exists.
    """
    # Step 1: rebase the branch onto the latest base.
    rebase_result = subprocess.run(  # nosec B603 — argv-list, no shell
        ["git", "rebase", base],
        cwd=worktree_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if rebase_result.returncode != 0:
        return (EXIT_REBASE_CONFLICT, rebase_result.stderr)

    # Step 2: re-verify the base SHA against the pre-rebase snapshot.
    state = read_review_state(worktree_root) or {}
    pre_rebase_sha = state.get("pre_rebase_base_sha")
    if pre_rebase_sha:
        sha_result = subprocess.run(  # nosec B603 — argv-list, no shell
            ["git", "rev-parse", base],
            cwd=worktree_root,
            capture_output=True,
            text=True,
            check=False,
        )
        if sha_result.returncode != 0:
            return (EXIT_REBASE_CONFLICT, sha_result.stderr)
        current_sha = sha_result.stdout.strip()
        if current_sha != pre_rebase_sha:
            return (
                EXIT_REBASE_CONFLICT,
                (
                    f"base SHA moved during rebase: was {pre_rebase_sha}, "
                    f"now {current_sha}; aborting squash and starting over"
                ),
            )

    # Step 3: switch the worktree onto the base branch.
    checkout_result = subprocess.run(  # nosec B603 — argv-list, no shell
        ["git", "checkout", base],
        cwd=worktree_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if checkout_result.returncode != 0:
        return (EXIT_REBASE_CONFLICT, checkout_result.stderr)

    # Step 4: stage the squash-merge (does NOT auto-commit).
    squash_result = subprocess.run(  # nosec B603 — argv-list, no shell
        ["git", "merge", "--squash", branch],
        cwd=worktree_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if squash_result.returncode != 0:
        return (EXIT_REBASE_CONFLICT, squash_result.stderr)

    # Step 5: semantic commit (one line, references the branch + base).
    subject = f"merge: {branch} -> {base}"
    commit_result = subprocess.run(  # nosec B603 — argv-list, no shell
        ["git", "commit", "-m", subject],
        cwd=worktree_root,
        capture_output=True,
        text=True,
        check=False,
    )
    return (commit_result.returncode, commit_result.stderr)


def run_push(base_ref: str = "main") -> tuple[int, str]:
    """Stage 5: ``git push origin <base_ref>`` (the ONLY auto-push entry point).

    Per decision doc ``.claude/decisions/2026-10-03-mainautopush.md`` and
    spec §4.6: this helper is the only place in the repo where
    ``git push origin main`` is invoked without explicit user opt-in.
    The command is hard-coded with no flags — no force-push, no
    other remote, no other branch. Any future flag in this argv would
    fail the multi-agent review (the review specifically checks for
    ``--force`` / ``-f`` / ``--force-with-lease``).

    Returns ``(returncode, stderr)`` verbatim. Non-fast-forward errors
    surface as non-zero; the call site maps them to
    ``EXIT_PUSH_DIVERGENCE = 4``. Per the decision doc, the module
    does NOT retry, force-push, rebase, or merge on divergence — the
    operator resolves manually.

    No-remote case (e.g. fresh worktree without ``origin``): per
    decision rule 5, the push is a silent no-op success. This is the
    only silent-success path in the workflow.
    """
    # No-remote case: silent success (decision doc rule 5).
    remote_result = subprocess.run(  # nosec B603 — argv-list, no shell
        ["git", "remote", "get-url", "origin"],
        capture_output=True,
        text=True,
        check=False,
    )
    if remote_result.returncode != 0:
        return (0, "")

    # Push (hard-coded command, no flags).
    push_result = subprocess.run(  # nosec B603 — argv-list, no shell
        ["git", "push", "origin", base_ref],
        capture_output=True,
        text=True,
        check=False,
    )
    return (push_result.returncode, push_result.stderr)


def _default_dispatcher(agent: str, prompt: str) -> str:
    """Default stage-2 dispatcher.

    Routes the prompt to ``agent`` via the Mahavishnu pool. The
    real implementation will invoke
    ``mcp__mahavishnu__pool_route_execute``; this v1 stub returns a
    synthetic pass verdict so the merge cycle is exercisable end-to-end
    before the pool-wiring lands. Operators running stage 2 in
    production should replace this with a real dispatcher at the
    call site (per spec REQ-004 follow-up).
    """
    return (
        f"<verdict>\n"
        f"  decision: pass\n"
        f"  note: stubbed dispatcher for {agent!r}; replace with "
        f"mcp__mahavishnu__pool_route_execute per REQ-004 follow-up\n"
        f"</verdict>\n"
    )


def _run_cleanup(worktree_root: Path) -> tuple[int, str]:
    """Stage 6: route through the existing ``mahavishnu worktree prune-merged``.

    Per spec REQ-012, cleanup uses the existing tier-rubric classifier
    (NOT silent removal). The CLI emits JSON on success and refuses
    ``not_merged`` worktrees (which is the desired fail-loud behavior
    for the merge cycle). The call site maps any non-zero returncode
    to ``EXIT_CLEANUP_FAILURE = 5`` and writes a sticky marker via
    ``.review-state.json`` to prevent re-attempt per spec §4.2.

    Private helper (leading underscore) so the test suite can
    monkeypatch it without touching the public API.
    """
    cleanup_result = subprocess.run(  # nosec B603 — argv-list, no shell
        ["mahavishnu", "worktree", "prune-merged", "--json"],
        cwd=worktree_root,
        capture_output=True,
        text=True,
        check=False,
    )
    return (cleanup_result.returncode, cleanup_result.stderr)


def _resolve_base(base_override: str | None) -> str:
    """Resolve the merge base: explicit override, else ``origin/main``, else ``main``.

    Mirrors the spec §4.4 default: ``origin/main`` if the remote
    exists, else ``main`` (the local ref). Called once at the top of
    ``run_pipeline`` so the same value threads through stage 4
    (rebase target) without re-querying the remote.
    """
    if base_override is not None:
        return base_override
    remote_result = subprocess.run(  # nosec B603 — argv-list, no shell
        ["git", "remote", "get-url", "origin"],
        capture_output=True,
        text=True,
        check=False,
    )
    if remote_result.returncode == 0:
        return "origin/main"
    return "main"


def _resolve_branch(worktree_root: Path, branch_override: str | None) -> str:
    """Resolve the merge branch: explicit override, else current branch of ``worktree_root``.

    Mirrors the slash-command default: ``--branch`` is optional; the
    SessionEnd hook and the CLI both fall back to the current branch
    of the worktree.
    """
    if branch_override is not None:
        return branch_override
    branch_result = subprocess.run(  # nosec B603 — argv-list, no shell
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=worktree_root,
        capture_output=True,
        text=True,
        check=False,
    )
    return branch_result.stdout.strip() or "main"


def run_pipeline(
    worktree_root: Path,
    *,
    branch: str | None = None,
    review_mode: str = "default",
    no_push: bool = False,
    no_cleanup: bool = False,
    base: str | None = None,
) -> int:
    """End-to-end merge-to-main pipeline (spec §4.4 stages 2-6).

    Composes the existing ``run_review`` / ``aggregate_verdicts`` /
    ``run_crackerjack_gate`` helpers with the new
    ``run_squash_merge`` / ``run_push`` / ``_run_cleanup`` helpers.
    Returns one of the spec §4.1 ``EXIT_*`` codes:

    - ``EXIT_OK = 0`` — full success.
    - ``EXIT_REVIEW_FAILURE = 1`` — ensemble review returned
      ``iterate`` or ``block`` (no progress made).
    - ``EXIT_CRACKERJACK_FAILURE = 2`` — ``crackerjack run -v`` non-zero.
    - ``EXIT_REBASE_CONFLICT = 3`` — stage 4 rebase / squash failed.
    - ``EXIT_PUSH_DIVERGENCE = 4`` — ``git push origin main`` non-FF.
    - ``EXIT_CLEANUP_FAILURE = 5`` — ``prune-merged`` refused.

    ``review_mode`` selects the stage-2 behavior:

    - ``"default"`` (or any other value): invoke the 3-agent ensemble
      via ``run_review`` + ``aggregate_verdicts``.
    - ``"none"``: skip stage 2 entirely (user responsibility; explicit
      opt-in required per the slash-command contract).
    - ``"quick"``: treated as ``"default"`` in v1 — a future spec
      revision will distinguish (smaller pool, no code-quality
      specialist).
    """
    base = _resolve_base(base)
    branch = _resolve_branch(worktree_root, branch)

    # Stage 2 — ensemble review (REQ-004).
    if review_mode != "none":
        prompt = (
            f"Review the diff on branch {branch!r} relative to {base!r}. "
            f"Worktree: {worktree_root}. "
            f"Return <verdict>decision: pass|needs_adjustment|block note: ...</verdict>."
        )
        verdicts = run_review(
            domain_specialist="python-pro",
            generalist_pool=AGENT_POOL,
            prompt=prompt,
            dispatcher=_default_dispatcher,
        )
        verdict = aggregate_verdicts(verdicts)
        if verdict in {"iterate", "block"}:
            return EXIT_REVIEW_FAILURE

    # Stage 3 — crackerjack gate (REQ-013).
    gate_rc, _gate_stderr = run_crackerjack_gate(worktree_root)
    if gate_rc != 0:
        return EXIT_CRACKERJACK_FAILURE

    # Stage 4 — squash-merge (spec §4.5).
    squash_rc, _squash_stderr = run_squash_merge(worktree_root, base, branch)
    if squash_rc != 0:
        return squash_rc  # EXIT_REBASE_CONFLICT typically

    # Stage 5 — auto-push (skippable via --no-push; spec §4.6).
    if not no_push:
        push_rc, _push_stderr = run_push("main")
        if push_rc != 0:
            return EXIT_PUSH_DIVERGENCE

    # Stage 6 — cleanup (skippable via --no-cleanup; spec REQ-012).
    if not no_cleanup:
        cleanup_rc, _cleanup_stderr = _run_cleanup(worktree_root)
        if cleanup_rc != 0:
            return EXIT_CLEANUP_FAILURE

    return EXIT_OK


def _build_arg_parser() -> argparse.ArgumentParser:
    """Build the ``__main__`` argument parser.

    Args:

    - ``--branch <name>`` — ephemeral branch to merge (default: current branch).
    - ``--review <mode>`` — ``default`` (3-agent ensemble), ``quick``
      (alias for default in v1), ``none`` (skip review; user opt-in).
    - ``--no-push`` — skip stage 5.
    - ``--no-cleanup`` — skip stage 6.
    - ``--from <base>`` — override rebase base (default: ``origin/main``,
      else ``main``).
    """
    parser = argparse.ArgumentParser(
        prog="python -m mahavishnu.core.merge_to_main",
        description=(
            "End-to-end merge-to-main pipeline (stages 2-6 of the "
            "trunk-based agent-review workflow per spec §4.4)."
        ),
    )
    parser.add_argument(
        "--branch",
        default=None,
        help="ephemeral branch to merge (default: current branch of cwd)",
    )
    parser.add_argument(
        "--review",
        choices=("quick", "default", "none"),
        default="default",
        help="stage-2 review mode: default|quick|none (default: default)",
    )
    parser.add_argument(
        "--no-push",
        action="store_true",
        help="skip stage 5 (default: push to origin/main)",
    )
    parser.add_argument(
        "--no-cleanup",
        action="store_true",
        help="skip stage 6 (default: prune the merged worktree)",
    )
    parser.add_argument(
        "--from",
        dest="base",
        default=None,
        help=("rebase base override (default: origin/main if remote exists, else main)"),
    )
    return parser


def main() -> int:
    """``__main__`` entry point — argparse + ``run_pipeline`` invocation.

    Per spec §4.4 demonstrable check: ``python -m
    mahavishnu.core.merge_to_main --help`` (smoke) shows the arg
    parser; ``--branch <name>`` triggers the full pipeline against
    the worktree at ``Path.cwd()``. Exit code propagates verbatim
    from ``run_pipeline`` (spec §4.1 outputs).
    """
    parser = _build_arg_parser()
    args = parser.parse_args()
    return run_pipeline(
        Path.cwd(),
        branch=args.branch,
        review_mode=args.review,
        no_push=args.no_push,
        no_cleanup=args.no_cleanup,
        base=args.base,
    )


if __name__ == "__main__":
    sys.exit(main())
