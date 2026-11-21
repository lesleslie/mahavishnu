"""Orchestration of the trunk-based agent-review workflow.

Per spec §4 (Components). Stages 2-6: ensemble review, crackerjack gate,
squash-merge, auto-push, cleanup. Cross-session resume via
.review-state.json at the worktree root. Idempotent and re-entrant.

Implements: REQ-004, REQ-009, REQ-013, REQ-014
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
import fcntl
from functools import partial
import json
from pathlib import Path
import random
import re
import subprocess
import sys
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

from .paths import get_worktree_base_path

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

#: A note carrying this prefix is not a reviewer's answer: the
#: dispatch itself failed, so there is no verdict about the code to
#: read. It is retried exactly like an unreadable verdict — a server
#: that could not be reached is worth one more try — and the reason
#: travels with it so the operator is told what actually happened.
#:
#: It lives here because it is a PARSER contract, not a dispatcher's
#: one: it says how to tell a dispatch failure from a reviewer's
#: verdict. The dispatcher puts it on every verdict it synthesises, and
#: :func:`_is_retryable` reads it to decide whether the failure is
#: worth another attempt.
DISPATCH_FAILED_PREFIX: str = "the dispatch failed: "

#: The same contract, for a dispatch that failed for a reason that
#: does not change between attempts: the pool refused the task's
#: shape, or it cannot honour the isolation the review asked for. It
#: is still not a reviewer's answer — so :func:`parse_verdict` reads it
#: as a ``block`` whose note names the failure — but it is NOT retried,
#: because a second dispatch would spend a full review cycle to learn
#: the same thing. The word differs from
#: :data:`DISPATCH_FAILED_PREFIX` (``permanently`` against a colon), so
#: the two are distinguishable by prefix alone.
DISPATCH_FAILED_PERMANENT_PREFIX: str = "the dispatch failed permanently: "

#: A decision word carrying this separator is the PROMPT's contract — the
#: alternatives joined by a pipe — copied back by a reviewer that repeated
#: the instruction. A reviewer's own decision word is one word.
VERDICT_CONTRACT_SEPARATOR: str = "|"

#: A note that is nothing but template placeholders — ``{failure}`` — is a
#: quoted source line, not prose. A reviewer's note is prose.
PLACEHOLDER_NOTE_RE = re.compile(r"^(?:\{[^{}]*\}\s*)+$")

#: The phrase the parser puts in the note of an AMBIGUOUS reply -- one
#: carrying more than one candidate verdict block. The retry says what
#: to change, so it recognises the phrase.
_AMBIGUOUS_NOTE: str = "more than one verdict block"

#: The phrase the parser puts in the note of a reply whose decision
#: word is not one the pipeline knows.
_UNKNOWN_DECISION_NOTE: str = "unknown decision"

#: The phrase the parser puts in the note of a reply that carried only
#: a quotation of the verdict block and no verdict of the reviewer's
#: own.
_QUOTED_ONLY_NOTE: str = "only quoted verdict templates"

#: What to tell the reviewer on a retry, keyed by the phrase in the
#: note that says what went wrong. Without it the retry repeats the
#: same instruction, the reviewer makes the same mistake, and the
#: merge blocks for a reason nobody was told about.
_RETRY_HINTS: dict[str, str] = {
    _AMBIGUOUS_NOTE: (
        "\n\nYour previous reply carried more than one verdict block, so it "
        "could not be read: which one was yours could not be told. Reply "
        "with the verdict block ALONE -- no analysis, and no quotation of "
        "the block's shape anywhere in the reply."
    ),
    _UNKNOWN_DECISION_NOTE: (
        "\n\nYour previous reply named a decision the pipeline does not "
        "know, so it could not be read. Name one of: pass, "
        "needs_adjustment, block -- and name it as one word, with no "
        "other text in place of it."
    ),
    _QUOTED_ONLY_NOTE: (
        "\n\nYour previous reply carried only a quotation of the verdict "
        "block and no verdict of your own, so it could not be read. Reply "
        "with your own verdict block."
    ),
}

# Exit codes (spec §4.1 Outputs)
EXIT_OK = 0
EXIT_REVIEW_FAILURE = 1
EXIT_CRACKERJACK_FAILURE = 2
EXIT_REBASE_CONFLICT = 3
EXIT_PUSH_DIVERGENCE = 4
EXIT_CLEANUP_FAILURE = 5

#: The local branch stage 5 pushes. ``run_push`` hard-codes ``main``, so
#: the consolidation gate's eligibility range is anchored here rather
#: than to the pipeline's ``base``: the range must describe the commits
#: that are actually about to be pushed.
PUSHED_BRANCH: str = "main"

# Pinned crackerjack invocation for the merge gate (spec REQ-013).
# The trailing space separates the verb from any appended flags; the
# CI-guard test in tests/unit/core/test_merge_to_main.py asserts this
# starts with "crackerjack run -v -f " and never contains "-p". The
# publish stage (`-p`) must never fire on the merge path. The
# ``-f`` flag (fast hooks only) was added so the merge gate runs in
# seconds rather than the ~5 minutes the comprehensive suite takes;
# the comprehensive suite is still expected to pass via the
# SessionEnd hook's pre-merge check (or CI), not on the merge path
# itself.
CRACKERJACK_INVOCATION: str = "crackerjack run -v -f "


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


#: Control characters, including ESC (0x1b) which opens an ANSI escape.
#: Newlines are excluded here on purpose -- they are handled by the
#: whitespace collapse below, which turns them into a space rather than
#: deleting them (deleting would join two words into one).
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")

#: Credential-shaped substrings. A reviewer that copies a secret out of
#: the diff under review would otherwise land it in the operator's log --
#: a log the operator reads, greps and pastes from.
_CREDENTIAL_RE = re.compile(
    r"\b(?:sk|pk|ghp|gho|github_pat|xox[baprs])[-_][A-Za-z0-9_-]{12,}\b",
    re.IGNORECASE,
)

#: The longest reviewer note printed to the operator's stderr. A note is
#: model-authored free text, so its length is bounded: one reviewer must
#: not be able to flood the log.
#:
#: The bound has to leave the finding room to FIT. The note is where the
#: finding that justifies the verdict goes -- the prompt says so -- and
#: the reply budget the prompt declares
#: (``REVIEW_REPLY_BUDGET_CHARS``, 1,500) is the whole reply: the
#: verdict block, the note inside it, and whatever analysis precedes
#: it. A 500-character note was a third of that budget, so a reviewer
#: writing a fuller finding had it cut mid-sentence: a real
#: architectural finding arrived as its first half and a guess. The
#: note is now 1,200 -- most of the reply budget, leaving room for the
#: analysis and the block itself -- and the number the reviewer is
#: told is read from this constant, so the two cannot drift.
#:
#: What the cap does NOT do is sanitise: control characters are
#: stripped, credential-shaped substrings are masked and whitespace is
#: collapsed BEFORE the length is taken, so a longer note carries no
#: more injection or secret-leak risk than a short one. The cap's own
#: cost is the length of the stderr line it allows, and that is the
#: whole of it.
MAX_NOTE_LENGTH: int = 1_200


def sanitize_note(note: str, *, limit: int = MAX_NOTE_LENGTH) -> str:
    """Make a reviewer's free-form note safe to print.

    The note is the remainder of a reviewer's reply -- model-authored text
    we did not write -- and it reaches the operator's stderr verbatim (see
    ``_format_verdicts`` and the retry message in ``run_review``). So it
    is made safe before it is trusted:

    * control characters are stripped, so an ANSI escape cannot repaint
      the terminal;
    * credential-shaped substrings are masked, so a secret copied out of
      the diff under review does not reach a log;
    * whitespace is collapsed to one line, so a note carrying a newline
      cannot forge a second verdict's log line;
    * the length is capped, and a truncated note keeps a trailing ``...``
      so a cut note is not mistaken for a whole one.

    The note is *kept*, not dropped. It is what tells a reviewer that had
    no opinion apart from one that never finished; dropping it would
    regress the reason the note was surfaced in the first place.
    """
    cleaned = _CONTROL_CHAR_RE.sub(" ", note)
    cleaned = _CREDENTIAL_RE.sub("<redacted>", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if len(cleaned) > limit:
        cleaned = cleaned[:limit].rstrip() + "..."
    return cleaned


def parse_verdict(agent_text: str) -> dict[str, str]:
    """Parse `<verdict>decision: ...</verdict>` block from agent output.

    Per spec §4.4: missing or malformed block returns decision='block'
    (fail-loud) so the merge gates on the parser. The 'note' field carries
    either the agent's explanation (on success) or a 'malformed: ...'
    string describing what was wrong (on failure).

    The agent's explanation is model-authored free text, so it is
    sanitized on the way in -- this is the only point where a note
    enters the pipeline, so sanitizing here covers every consumer of a
    verdict (the retry message, the operator-facing summary, and the
    persisted review state).

    **One block, or none.** The reply is read only when exactly one
    block could be the reviewer's answer. The prompt asks the reviewer
    to put its verdict block last, with any analysis before it -- and an
    analysis that quotes a line of code can carry a literal
    ``<verdict>...</verdict>`` in it. A review of this branch quoted
    the integration test's own reply-builder line, and the parser took
    the quote as the verdict: the reviewer had said ``decision: pass``,
    and the merge read a note that was a fragment of Python. So a
    reply carrying two possible answers is refused rather than parsed,
    and the reviewer is asked again.

    **Two blocks, and the parser refuses.** A quoted block with a
    single-word decision and a prose note is indistinguishable from a
    verdict the reviewer wrote, and reviewers of this repo quote source
    lines verbatim. Picking one of two candidates could open the
    ensemble gate on a verdict nobody wrote -- two passes are enough to
    proceed -- so the parser refuses: more than one candidate is a
    fail-loud ``malformed`` note, and the retry path gives the
    reviewer another chance to answer unambiguously.

    There is no tie-break to fall back on, and that is deliberate. A
    block standing on its own line is usually the reviewer's, but a
    quotation of a verdict block also stands on its own line -- and the
    mirror of that mistake is the same mistake: a reviewer that wrote
    its verdict inside a sentence and quoted a block beneath it would
    have the QUOTE read as the answer. Position cannot separate those
    two replies, so the parser refuses both.

    The same reasoning rules out the OTHER way of telling them apart:
    by their surroundings. A block inside a quoted literal is usually
    a quotation, but a reviewer that wraps its own verdict in quote
    marks would be hidden by that rule -- and what a rule hides, a rule
    can promote to be the only candidate, which is how a quoted
    ``pass`` opens the gate.

    So the only shapes the parser acts on are the ones a genuine
    verdict **cannot** have: a note that is nothing but template
    placeholders (``{failure}``), and a decision word that is the
    prompt's alternatives joined by a pipe. A reviewer's note is prose
    and its decision word is one word. Everything else is either the
    answer or a reason to refuse.

    A block that names no known decision decides nothing on its own,
    and it does not poison the blocks around it: a reviewer whose last
    block is fine has answered, whatever it quoted earlier. But it is
    not skipped in favour of an earlier block either -- when the LAST
    block is one the pipeline cannot read, the parser reports it,
    because reporting an earlier quote as the verdict would hide the
    reviewer's own answer and let the review pass on the strength of a
    line of code.

    A note carrying ``DISPATCH_FAILED_PREFIX`` is the DISPATCHER's
    failure report rather than a reviewer's answer, and it is read as
    the block it is -- a ``block`` whose note names the failure. The
    prefix is what makes the difference visible to the operator and to
    :func:`_is_retryable`, which retries it: a dispatch that failed
    says nothing about the code. A dispatch that failed *permanently*
    carries the sibling prefix and is not retried.
    """
    matches = list(VERDICT_RE.finditer(agent_text))
    # req: REQ-MERGEREV-006
    blocks: list[tuple[str, str, bool]] = []
    for match in matches:
        decision_raw = match.group(1).strip().lower()
        note_raw = (match.group(2) or "").strip()
        if PLACEHOLDER_NOTE_RE.match(note_raw):
            # A quoted template: the note is a placeholder, not prose.
            # A reviewer's note is prose, so a genuine verdict cannot
            # have this shape -- skipping it cannot hide one.
            continue
        if VERDICT_CONTRACT_SEPARATOR in decision_raw:
            # The prompt's contract, quoted back. A genuine decision
            # word is one word, so this cannot hide one either.
            continue
        blocks.append((decision_raw, note_raw, decision_raw in VALID_DECISIONS))
    if not blocks:
        if matches:
            return {
                "decision": "block",
                "note": (
                    "malformed: the reply carried only quoted verdict templates, "
                    "no verdict of the reviewer's own"
                ),
            }
        return {
            "decision": "block",
            "note": "malformed: <verdict> block not found in agent response",
        }
    last_decision, _last_note, last_known = blocks[-1]
    if not last_known:
        # The LAST block the reviewer wrote names a decision the
        # pipeline does not know. Fail loud rather than read an earlier
        # block: reporting an earlier quote as the verdict would hide
        # the reviewer's own answer, and the review would pass on the
        # strength of a line of code.
        #
        # An unknown decision word EARLIER in the reply does not
        # poison it: a reviewer whose last block is fine has answered,
        # whatever it quoted earlier.
        return {
            "decision": "block",
            "note": f"malformed: unknown decision {last_decision!r}",
        }
    reviewer_verdicts: list[tuple[str, str]] = [
        (d, n) for d, n, known in blocks if known
    ]
    if len(reviewer_verdicts) > 1:
        # More than one block could be the reviewer's own verdict, so
        # which one it is cannot be told from the reply -- a quoted
        # line with a prose note looks exactly like a verdict, and
        # reviewers of this repo quote source lines verbatim. Fail loud
        # rather than pick one: a wrong pick can open the ensemble
        # gate on a verdict nobody wrote.
        #
        # There is no tie-break to fall back on. A block that stands
        # on its own line is usually the reviewer's, but a quotation
        # of a verdict block also stands on its own line -- and the
        # mirror of that mistake is the same mistake: a reviewer that
        # writes its verdict inside a sentence and quotes a block
        # beneath it would have the QUOTE read as the answer. Position
        # cannot separate the two, so the reply is refused and the
        # reviewer is asked again.
        return {
            "decision": "block",
            "note": (
                "malformed: the reply carried more than one verdict block, "
                "so the reviewer's own cannot be identified"
            ),
        }
    decision_raw, note_raw = reviewer_verdicts[0]
    return {"decision": decision_raw, "note": sanitize_note(note_raw)}


# In-repo generalist pool per spec §4.4 (verified 2026-10-03). The random
# generalist is drawn uniformly from this list; each invocation re-shuffles.
#: A review that produced no answer is worth one more try: the
#: reply could not be read, or the dispatch itself failed. Both mean
#: the review did not happen, which is not the same as a reviewer
#: that had no opinion.
_RETRYABLE_NOTE_PREFIXES: tuple[str, ...] = ("malformed",)


def _is_retryable(note: str) -> bool:
    """Whether a reply that produced this note should be retried.

    Two ways a review fails to arrive: the reply could not be read
    (``malformed: ...``), or the dispatch itself failed
    (``the dispatch failed: ...``). Both are retried once, because a
    server that could not be reached and a reviewer whose reply was
    cut off are both worth another try — and a second failure still
    blocks, so the gate is not weakened.

    A dispatch that failed **permanently** is not retried: the pool
    refused the task's shape, or it cannot honour the isolation the
    review asked for, and neither changes between attempts. The
    permanent prefix deliberately does not start with the transient one
    — ``permanently`` where the transient form has a colon — so this
    check does not match it.
    """
    return note.startswith(_RETRYABLE_NOTE_PREFIXES) or note.startswith(
        DISPATCH_FAILED_PREFIX
    )


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
    *,
    attempts: int = 2,
) -> list[dict[str, str]]:
    """Run a 3-agent ensemble review (REQ-004, spec §4.4).

    Dispatches the prompt to three reviewers:
      1. ``domain_specialist`` (worker-supplied; default ``python-pro`` upstream)
      2. ``_CODE_QUALITY_AGENT`` (constant)
      3. one random pick from ``generalist_pool`` (default ``AGENT_POOL``)

    The three run **concurrently**. Each dispatch is an I/O-bound MCP
    round trip to a Mahavishnu worker pool, so dispatching them one
    after another paid the slowest reviewer's latency three times over —
    a twenty-minute review that was really three concurrent reviews.
    Threading keeps the synchronous dispatcher signature and the
    per-agent retry loop exactly as they were, and each dispatch already
    owns its event loop (``asyncio.run`` per call), so the three do not
    share one.

    Each agent's response is parsed via ``parse_verdict``; missing or
    malformed verdict blocks already fail-loud to ``decision='block'``.

    A reviewer whose reply could not be *read* is retried once. A
    review that never arrived is not a review that had no opinion: the
    MCP server restarting mid-dispatch and the reviewer's CLI being
    interrupted both read exactly like a reviewer with no opinion, and
    both are worth one more attempt. A second failure still blocks, so
    the gate is not weakened -- it is just no longer decided by a
    dropped connection.

    Returns a list of three ``{'agent', 'decision', 'note'}`` dicts in
    dispatch order, each carrying the wall-clock seconds that reviewer's
    dispatch took. The caller is responsible for applying the verdict
    rule order (any block → block; ≥2 pass → proceed; else iterate).
    """
    generalist = random.choice(generalist_pool)
    selected = (domain_specialist, _CODE_QUALITY_AGENT, generalist)

    def _review_one(agent: str) -> dict[str, str]:
        verdict = parse_verdict("")
        started = time.monotonic()
        # Local to this reviewer: the prompt is shared by the three
        # concurrent dispatches, so it must not be rebound here.
        attempt_prompt = prompt
        for attempt in range(1, max(1, attempts) + 1):
            response = dispatcher(agent, attempt_prompt)
            verdict = parse_verdict(response)
            if not _is_retryable(verdict["note"]):
                break
            if attempt < attempts:
                print(
                    f"[merge_to_main] reviewer {agent!r} returned an unreadable "
                    f"verdict ({verdict['note']}); retrying",
                    file=sys.stderr,
                )
                attempt_prompt = prompt
                for marker, hint in _RETRY_HINTS.items():
                    if marker in verdict["note"]:
                        attempt_prompt = prompt + hint
                        break
        elapsed = time.monotonic() - started
        return {
            "agent": agent,
            "decision": verdict["decision"],
            "note": verdict["note"],
            "elapsed_s": f"{elapsed:.1f}",
        }

    with ThreadPoolExecutor(max_workers=len(selected)) as executor:
        futures = [executor.submit(_review_one, agent) for agent in selected]
        # Collected in submission order, so the verdict list is in
        # dispatch order however the reviews interleave.
        return [future.result() for future in futures]


def _format_verdicts(verdicts: list[dict[str, str]]) -> str:
    """The reviewer verdicts, one line each, for the operator's stderr.

    Spec §4.4 asks for a stderr message naming the reviewer that
    failed. Without it a blocked merge says only "review failure": the
    operator has to guess which reviewer was unhappy and why -- and a
    reviewer that timed out looks exactly like one that had no opinion.
    """
    lines = ["[merge_to_main] stage 2 ensemble review:"]
    for verdict in verdicts:
        elapsed = verdict.get("elapsed_s")
        suffix = f" ({elapsed}s)" if elapsed else ""
        lines.append(
            f"  {verdict['agent']}: {verdict['decision']} - {verdict['note']}{suffix}"
        )
    return "\n".join(lines)


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


def _find_main_checkout_path(worktree_root: Path) -> Path | None:
    """Locate the main checkout in the same git repo as ``worktree_root``.

    Uses ``git worktree list --porcelain`` to enumerate every worktree
    in the shared git repository. Returns the path of the worktree
    whose branch is ``refs/heads/main`` — i.e., where ``main`` is
    checked out as a real branch (not detached). Returns ``None`` if
    no worktree has ``main`` checked out (bare repo, detached main,
    or no main branch at all).

    The squash-merge commit must land in a real ``main`` checkout:
    a detached HEAD on ``origin/main`` would lose the commit on
    ``git gc`` (and the auto-cleanup prunes the worktree anyway).
    """
    list_result = subprocess.run(  # nosec B603 — argv-list, no shell
        ["git", "worktree", "list", "--porcelain"],
        cwd=worktree_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if list_result.returncode != 0:
        return None

    # Porcelain format: blocks separated by blank lines. Each block
    # starts with ``worktree <path>`` and may include ``branch <ref>``
    # (or ``detached``). The block whose branch is refs/heads/main is
    # the main checkout.
    candidate: Path | None = None
    for line in list_result.stdout.splitlines():
        if line.startswith("worktree "):
            candidate = Path(line.split(" ", 1)[1])
        elif line.startswith("branch refs/heads/main") and candidate is not None:
            return candidate
    return None


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
    3. ``git checkout <base>`` in the main checkout (NOT the worktree)
       so the commit lands on local ``main``. The worktree has the
       ephemeral branch; the main checkout has the real ``main``
       ref. This used to fail: ``git checkout origin/main`` in the
       worktree is a detached HEAD, so the squash commit was a
       floating ref GC'd on cleanup. The base is resolved to a local
       branch by ``_resolve_local_branch`` before it reaches this
       step, so the checkout always lands on a real branch — the same
       one the branch was replayed onto.
    4. ``git merge --squash <branch>`` in the main checkout (stages
       changes, does NOT auto-commit).
    5. Semantic commit (``merge: <branch> → <base>``) in the main
       checkout.

    Plus a pair of pre-/post- capture steps that protect the main
    checkout's index from pollution across sessions:

    - **Step 2.6** (before step 3): ``git status --porcelain`` in the
      main checkout. If dirty (staged, modified, or untracked files
      from prior sessions), ``git stash push --include-untracked``
      captures the state into a dated stash entry. Without this,
      step 4's ``git merge --squash`` adds the branch's files to
      the already-polluted index, and step 5's bare ``git commit``
      sweeps everything in (the
      ``feedback-squash-merge-pollutes-parent-index`` failure mode —
      observed 2026-10-16 in mcp-common: 24 unintended files,
      6,535 lines).
    - **Step 6** (after step 5): ``git stash pop`` restores the
      captured state. Only fires on commit success; if the commit
      fails, the stash is preserved so the user can inspect it via
      ``git stash list`` and recover manually.

    Returns ``(returncode, stderr)`` verbatim. The call site maps any
    non-zero returncode to ``EXIT_REBASE_CONFLICT = 3``. The rebase
    step is the most likely failure point; the squash-merge step is
    a no-op after a clean rebase.

    The pre-rebase work (steps 1-2) stays in the worktree because
    the ephemeral branch only exists there. Stages 2.6, 3-6
    relocate to the main checkout so the squash-merge lands on the
    real ``main`` branch and the user's prior dirty state is
    preserved across the merge.
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

    # Step 2.5: locate the main checkout so the squash-merge lands
    # on the real ``main`` branch (not a detached HEAD on
    # ``origin/main`` inside the worktree).
    main_checkout = _find_main_checkout_path(worktree_root)
    if main_checkout is None:
        return (
            EXIT_REBASE_CONFLICT,
            (
                "no worktree with branch refs/heads/main found; "
                "cannot land squash-merge on local main"
            ),
        )

    # Step 2.6: capture the main checkout's dirty tree state.
    # The main_checkout is shared across sessions and accumulates
    # staged-but-uncommitted files from prior work. Step 4's
    # ``git merge --squash`` adds my files to that index, and Step 5's
    # bare ``git commit`` would then sweep everything in (the
    # ``feedback-squash-merge-pollutes-parent-index`` failure mode).
    # Stash first, restore after the commit lands.
    #
    # The stash stack is shared by every worktree and every session in
    # the repo, so the entry this pipeline creates has to be restored by
    # identity, not by position. ``stash_ref`` holds the unique message
    # that identifies the entry.
    stash_ref: str | None = None
    status_result = subprocess.run(  # nosec B603 — argv-list, no shell
        ["git", "status", "--porcelain"],
        cwd=main_checkout,
        capture_output=True,
        text=True,
        check=False,
    )
    if status_result.stdout.strip():
        stash_message = f"merge-to-main auto-stash: {branch} -> {base} ({datetime.now(UTC).isoformat()})"
        stash_result = subprocess.run(  # nosec B603 — argv-list, no shell
            [
                "git",
                "stash",
                "push",
                "--include-untracked",
                "-m",
                stash_message,
            ],
            cwd=main_checkout,
            capture_output=True,
            text=True,
            check=False,
        )
        # ``git stash push`` exits 0 when it had nothing to save -- it
        # prints "No local changes to save" and creates no entry. A
        # dirty tree can still be unstaged away by the time the push
        # runs (another session committing under us), so the exit code
        # alone does not say an entry exists. Recording a stash that was
        # never created is what made the restore step pop whatever
        # happened to be on top of the shared stack.
        stash_created = "No local changes to save" not in stash_result.stdout
        if stash_result.returncode == 0 and stash_created:
            stash_ref = stash_message
            print(
                f"[merge_to_main] captured main_checkout dirty tree: {stash_message}",
                file=sys.stderr,
            )
        elif stash_result.returncode == 0:
            print(
                "[merge_to_main] main_checkout had no changes to stash "
                "after all; nothing captured",
                file=sys.stderr,
            )
        else:
            print(
                f"[merge_to_main] warning: git stash push failed in "
                f"main_checkout; proceeding without stash. stderr: "
                f"{stash_result.stderr!r}",
                file=sys.stderr,
            )

    # Step 3: switch the main checkout onto the base branch.
    checkout_result = subprocess.run(  # nosec B603 — argv-list, no shell
        ["git", "checkout", base],
        cwd=main_checkout,
        capture_output=True,
        text=True,
        check=False,
    )
    if checkout_result.returncode != 0:
        if stash_ref is not None:
            _pop_stash_safely(main_checkout, stash_ref)
        return (EXIT_REBASE_CONFLICT, checkout_result.stderr)

    # Step 4: stage the squash-merge (does NOT auto-commit).
    squash_result = subprocess.run(  # nosec B603 — argv-list, no shell
        ["git", "merge", "--squash", branch],
        cwd=main_checkout,
        capture_output=True,
        text=True,
        check=False,
    )
    if squash_result.returncode != 0:
        if stash_ref is not None:
            _pop_stash_safely(main_checkout, stash_ref)
        return (EXIT_REBASE_CONFLICT, squash_result.stderr)

    # Step 5: semantic commit (one line, references the branch + base).
    subject = f"merge: {branch} -> {base}"
    commit_result = subprocess.run(  # nosec B603 — argv-list, no shell
        ["git", "commit", "-m", subject],
        cwd=main_checkout,
        capture_output=True,
        text=True,
        check=False,
    )

    # Step 6: restore the captured dirty tree (only on commit success).
    # If the commit failed, leave the stash in place so the user can
    # inspect it via ``git stash list`` and recover manually.
    if commit_result.returncode == 0 and stash_ref is not None:
        _pop_stash_safely(main_checkout, stash_ref)
    elif commit_result.returncode != 0 and stash_ref is not None:
        print(
            "[merge_to_main] commit failed; auto-stash preserved in "
            "main_checkout. Run `git stash list` to inspect, "
            "`git stash pop` to restore.",
            file=sys.stderr,
        )

    return (commit_result.returncode, commit_result.stderr)


def _find_stash_entry(main_checkout: Path, message: str) -> tuple[str, str] | None:
    """Find the stash entry carrying ``message``.

    Returns ``(sha, ref)`` — the entry's commit SHA and its
    ``stash@{n}`` selector — or ``None`` when no entry matches.

    The stash stack is shared by every worktree and every session in
    the repo, so an entry is only addressable by identity. ``%gd``
    gives the positional selector git's ``drop`` wants, ``%H`` the
    SHA that ``apply`` accepts, and ``%gs`` the reflog subject the
    message is a substring of (``stash push -m`` prefixes the subject
    with ``On <branch>:``).
    """
    list_result = subprocess.run(  # nosec B603 — argv-list, no shell
        ["git", "stash", "list", "--format=%gd %H %gs"],
        cwd=main_checkout,
        capture_output=True,
        text=True,
        check=False,
    )
    if list_result.returncode != 0:
        return None
    for line in list_result.stdout.splitlines():
        parts = line.split(" ", 2)
        if len(parts) != 3:
            continue
        ref, sha, subject = parts
        if message in subject:
            return sha, ref
    return None


def _pop_stash_safely(main_checkout: Path, stash_ref: str) -> None:
    """Restore the stash entry this pipeline created, and drop it.

    ``stash_ref`` is the unique message the entry was created with.
    The entry is restored by **identity**, never by position: a bare
    ``git stash pop`` pops whatever is on top of the shared stack,
    which — if another session stashed in between — is not this
    pipeline's entry at all. Popping it would land another session's
    work in the main checkout and leave this pipeline's own entry
    buried. That is the failure the ``stash_ref`` parameter was
    always meant to prevent.

    So the entry is resolved to its SHA, applied by SHA (git accepts
    any stash commit here), and then dropped by a ``stash@{n}`` that
    is re-resolved and re-verified against the SHA immediately
    beforehand — ``drop`` takes no SHA, only a position.

    Stash pop conflicts are common when the user's prior dirty tree
    state overlapped with files modified by the squash-merge (e.g.
    the user had staged changes to the same files the branch was
    editing). Standard merge conflict markers surface; the user
    resolves them via normal git tooling. We never want to fail the
    entire merge pipeline just because the user's pre-existing
    work overlapped with the new commit — the commit has already
    landed on ``main`` and is the source of truth going forward.
    """
    entry = _find_stash_entry(main_checkout, stash_ref)
    if entry is None:
        print(
            f"[merge_to_main] warning: no stash entry matching "
            f"{stash_ref!r} was found; the main_checkout's pre-merge "
            f"state was not restored automatically. Inspect the stack "
            f"with `git stash list`.",
            file=sys.stderr,
        )
        return
    sha, _ref = entry

    apply_result = subprocess.run(  # nosec B603 — argv-list, no shell
        ["git", "stash", "apply", sha],
        cwd=main_checkout,
        capture_output=True,
        text=True,
        check=False,
    )
    if apply_result.returncode != 0:
        print(
            f"[merge_to_main] warning: restoring the main_checkout "
            f"dirty tree from stash {sha[:12]} failed. The user's "
            f"pre-existing dirty tree state is still in the stash; "
            f"manual resolution required. git stash apply stdout: "
            f"{apply_result.stdout!r}; stderr: {apply_result.stderr!r}",
            file=sys.stderr,
        )
        return

    # The apply succeeded. Drop the entry — but only the entry just
    # applied. ``drop`` accepts a positional ``stash@{n}``, so the
    # position is re-resolved from the message and re-checked against
    # the SHA before it is used. A push by another session appends and
    # leaves positions alone; only a concurrent pop could shift one,
    # and that is a single-command window rather than the whole merge.
    drop_target = _find_stash_entry(main_checkout, stash_ref)
    if drop_target is None:
        print(
            f"[merge_to_main] restored the main_checkout dirty tree, but "
            f"the stash entry {sha[:12]} could not be re-resolved for "
            f"removal; it is still in the stack. Drop it with "
            f"`git stash drop` once you have confirmed it is the right "
            f"entry.",
            file=sys.stderr,
        )
        return
    drop_sha, drop_ref = drop_target
    if drop_sha != sha:
        print(
            f"[merge_to_main] warning: the stash position {drop_ref!r} "
            f"holds {drop_sha[:12]} rather than the entry that was "
            f"applied ({sha[:12]}); leaving the stack untouched.",
            file=sys.stderr,
        )
        return
    drop_result = subprocess.run(  # nosec B603 — argv-list, no shell
        ["git", "stash", "drop", drop_ref],
        cwd=main_checkout,
        capture_output=True,
        text=True,
        check=False,
    )
    if drop_result.returncode != 0:
        print(
            f"[merge_to_main] restored the main_checkout dirty tree, but "
            f"dropping the stash entry {drop_ref} failed; it is still in "
            f"the stack. git stash drop stderr: {drop_result.stderr!r}",
            file=sys.stderr,
        )
        return
    print(
        "[merge_to_main] restored main_checkout dirty tree from stash",
        file=sys.stderr,
    )


def run_push(base_ref: str = "main") -> tuple[int, str]:
    """Stage 5: ``git push origin <base_ref>`` (the ONLY auto-push entry point).

    Per decision doc ``docs/decisions/2026-10-03-mainautopush.md`` and
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


def _list_repo_worktrees(worktree_root: Path) -> list[Path]:
    """List co-located worktrees for the current repo's worktree-base.

    Per `docs/decisions/2026-10-13-prepushconsolidationgate.md` and
    `~/.claude/CLAUDE.md` "Worktree location preference": Bodai repos
    place their worktrees at
    ``<worktree-base>/<basename-of-cwd>/<worktree-name>/``. So the
    *parent* of the worktree path is the repo dir under the worktree
    base; siblings of the current worktree live there. The cwd
    worktree itself is excluded from the returned list.

    Public for testability via monkeypatch.
    """
    base = get_worktree_base_path()
    repo_dir = worktree_root.parent
    # Verify the parent is directly under the configured worktree base.
    # If the worktree is elsewhere (e.g. fresh checkout), there are no
    # co-located siblings to check.
    if repo_dir.parent != base:
        return []
    try:
        worktree_root_resolved = worktree_root.resolve()
    except OSError, RuntimeError:
        worktree_root_resolved = worktree_root
    siblings: list[Path] = []
    for p in repo_dir.iterdir():
        if not p.is_dir():
            continue
        try:
            if p.resolve() == worktree_root_resolved:
                continue
        except OSError, RuntimeError:
            pass
        siblings.append(p)
    return sorted(siblings)


def _check_sibling_worktree_state(
    worktree_root: Path,
    sibling_path: Path,
    base: str,
    worktree_list_output: str,
) -> str | None:
    """Check if a sibling worktree is in one of the four acceptable states.

    Returns ``None`` if the sibling passes (merge / pruned / mid-review /
    abandoned); returns a reason string if the sibling holds back the push.

    The ``worktree_list_output`` parameter is the cached stdout of
    ``git worktree list --porcelain`` — passed in so the caller can share
    one subprocess invocation across all siblings.
    """
    try:
        if sibling_path.resolve() == worktree_root.resolve():
            return None  # self, skip
    except OSError, RuntimeError:
        pass

    # State (b): pruned — not in `git worktree list --porcelain` output.
    # The porcelain output lists paths; the sibling is "live" iff its
    # resolved path appears in the output.
    if str(sibling_path.resolve()) not in worktree_list_output:
        return None

    # State (c) / (d): `.review-state.json` mid-review or sticky-failed.
    state_path = sibling_path / ".review-state.json"
    if state_path.exists():
        try:
            data = json.loads(state_path.read_text())
        except json.JSONDecodeError, OSError:
            data = None
        if isinstance(data, dict):
            if data.get("stage_failed") is not None:
                return None  # (d) explicitly abandoned
            stages_completed = data.get("stages_completed") or []
            if stages_completed:
                return None  # (c) mid-review in progress

    # State (a): branch HEAD is "merged" into local main.
    # Two sub-checks:
    #   (a1) branch HEAD is an ancestor of local main HEAD (regular
    #        merge or fast-forward case)
    #   (a2) local main has a commit with subject "merge: <branch> -> <base>"
    #        (squash-merge case — the squash-merge creates a NEW commit,
    #        so the branch tip is NOT an ancestor of local main)
    branch_result = subprocess.run(  # nosec B603 — argv-list, no shell
        ["git", "-C", str(sibling_path), "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if branch_result.returncode != 0 or not branch_result.stdout.strip():
        return f"sibling {sibling_path.name}: cannot determine branch HEAD"
    branch = branch_result.stdout.strip()
    ancestor_result = subprocess.run(  # nosec B603 — argv-list, no shell
        ["git", "merge-base", "--is-ancestor", branch, base],
        capture_output=True,
        text=True,
        check=False,
    )
    if ancestor_result.returncode == 0:
        return None  # (a1) branch is ancestor of main

    # (a2) Look for a squash-merge commit on local main whose subject
    # matches the squash-merge template for this branch.
    squash_subject = f"merge: {branch} -> {base}"
    log_result = subprocess.run(  # nosec B603 — argv-list, no shell
        ["git", "log", "--format=%s", base],
        capture_output=True,
        text=True,
        check=False,
        cwd=sibling_path,
    )
    if log_result.returncode == 0 and squash_subject in log_result.stdout:
        return None  # (a2) squash-merge commit exists on local main

    return f"sibling {sibling_path.name}: branch {branch!r} has unmerged commits"


def _check_pending_commit_eligibility(
    branch: str = PUSHED_BRANCH,
    *,
    cwd: Path | None = None,
) -> list[str]:
    """Check the pending-commit eligibility per the gate's check (2).

    Per `docs/decisions/2026-10-13-prepushconsolidationgate.md` §2, the
    range is the set of commits stage 5 will actually push::

        git log origin/main..main

    — the commits on local ``main`` that the remote does not yet have.

    The range is deliberately NOT ``<base>..HEAD``. At stage 4.5 the
    worktree's HEAD is still the ephemeral branch: stage 4 lands the
    squash-merge in the *main checkout*, so the worktree never moves off
    the branch. ``<base>..HEAD`` therefore enumerates exactly the
    commits the squash-merge just consumed into ``main`` — the branch's
    own history. Every branch with an ordinary commit history produced
    at least one "ineligible" commit, and the gate held back every push.

    For v1: accepts commits whose subject matches the squash-merge
    template ``merge: <branch> -> <base>`` (eligibility check α).
    Checks (β) fast-forward replay and (γ) authorized version bump are
    documented in the decision doc but not enforced in v1 to keep the
    eligibility check simple — operators use `--no-consolidation-gate`
    for the rare non-squash case.

    Args:
        branch: The local branch whose unpushed commits are checked.
        cwd: The repository to inspect. Defaults to the process cwd.

    Returns the list of ineligible commit SHAs (empty list = all eligible).
    """
    remote_ref = f"origin/{branch}"
    log_result = subprocess.run(  # nosec B603 — argv-list, no shell
        ["git", "log", "--format=%H|%s", f"{remote_ref}..{branch}"],
        capture_output=True,
        text=True,
        check=False,
        cwd=cwd,
    )
    if log_result.returncode != 0:
        return []  # git failure — assume eligible (don't block on git error)
    ineligible: list[str] = []
    for line in log_result.stdout.splitlines():
        if "|" not in line:
            continue
        sha, subject = line.split("|", 1)
        if subject.startswith("merge: ") and " -> " in subject:
            continue  # (α) squash-merge commit
        ineligible.append(sha)
    return ineligible


def _run_consolidation_gate(
    worktree_root: Path,
    base: str,
) -> tuple[bool, list[str], list[str]]:
    """Pre-push consolidation gate.

    Per `docs/decisions/2026-10-13-prepushconsolidationgate.md`:
    checks (1) co-located worktrees for unmerged WIP and (2) pending
    commit eligibility. Returns ``(gate_clear, held_back_sibling_reasons,
    ineligible_commit_shas)``. ``gate_clear=True`` means push is
    authorized; ``gate_clear=False`` means the push is held back (the
    caller writes the held-back dev-log entry and sticky-failure marker).
    """
    held_back_siblings: list[str] = []

    # Cache `git worktree list --porcelain` output once per gate run.
    wt_list_result = subprocess.run(  # nosec B603 — argv-list, no shell
        ["git", "worktree", "list", "--porcelain"],
        capture_output=True,
        text=True,
        check=False,
        cwd=worktree_root,
    )
    worktree_list_output = (
        wt_list_result.stdout if wt_list_result.returncode == 0 else ""
    )

    for sibling in _list_repo_worktrees(worktree_root):
        reason = _check_sibling_worktree_state(
            worktree_root,
            sibling,
            base,
            worktree_list_output,
        )
        if reason is not None:
            held_back_siblings.append(reason)

    # The range is the commits stage 5 will push — anchored to the
    # pushed branch, not to ``base`` and not to the worktree's HEAD.
    ineligible = _check_pending_commit_eligibility(
        PUSHED_BRANCH,
        cwd=worktree_root,
    )

    return (
        not held_back_siblings and not ineligible,
        held_back_siblings,
        ineligible,
    )


def _write_held_back_log(
    worktree_root: Path,
    branch: str,
    base: str,
    held_back_siblings: list[str],
    ineligible_commits: list[str],
) -> None:
    """Write the dev-log entry for a held-back gate (best-effort).

    Per the new decision doc: ``push.result: "error:consolidation_gate_held_back"``
    reuses the parent's existing ``error:<message>`` enum value (no new
    enum value added). Local file is canonical; session-buddy mirror is
    best-effort (existing `dev_log.write_entry()` behavior).
    """
    try:
        from .dev_log import write_entry
    except ImportError:
        return  # dev_log not available; skip silently
    metadata: dict[str, Any] = {
        "date": datetime.now(tz=UTC).strftime("%Y-%m-%d"),
        "branch": branch,
        "push": {
            "result": "error:consolidation_gate_held_back",
            "remote": "origin",
            "branch": "main",
        },
        "base": base,
    }
    if held_back_siblings:
        metadata["held_back_sibling_worktrees"] = held_back_siblings
    if ineligible_commits:
        metadata["held_back_pending_commits"] = ineligible_commits
    body = (
        f"# merge-to-main held back by pre-push consolidation gate\n\n"
        f"Branch: {branch}\n"
        f"Base: {base}\n"
        f"Held-back sibling worktrees: {len(held_back_siblings)}\n"
        f"Ineligible pending commits: {len(ineligible_commits)}\n\n"
        f"Per `docs/decisions/2026-10-13-prepushconsolidationgate.md`. "
        f"Stage 6 cleanup was skipped; `.review-state.json` carries the "
        f"sticky-failure marker (`stage_failed: "
        f"'stage_5_push_held_back_by_consolidation_gate'`).\n"
    )
    write_entry(metadata, body, mirror_to_session_buddy=True)


def _origin_remote_exists() -> bool:
    """Return True when the repo has an ``origin`` remote configured.

    ``run_push`` treats a missing remote as a silent success (per
    decision rule 5), so the caller cannot tell "pushed" from "no remote"
    by its return code alone. The dev-log entry needs the distinction.
    """
    result = subprocess.run(  # nosec B603 — argv-list, no shell
        ["git", "remote", "get-url", "origin"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def _write_merge_log(
    worktree_root: Path,
    branch: str,
    base: str,
    *,
    push_result: str,
    cleanup_performed: bool,
    outcome: str,
) -> None:
    """Write the dev-log entry for a merge that ran to a terminal outcome.

    Mirrors :func:`_write_held_back_log`, which only covers the
    pre-push consolidation gate's hold-back path. Without this, the audit
    trail recorded merges that were *deferred* but none of the merges that
    actually landed.

    ``push.result`` uses the enum from
    `docs/decisions/2026-10-03-mainautopush.md`: ``ok``, ``diverged``,
    ``error:<message>``, ``no_remote`` — plus ``skipped`` for an
    operator-deferred push (``--no-push``).

    Local file is canonical; the session-buddy mirror is best-effort
    (existing ``dev_log.write_entry()`` behavior).
    """
    try:
        from .dev_log import write_entry
    except ImportError:
        return  # dev_log not available; skip silently
    metadata: dict[str, Any] = {
        "date": datetime.now(tz=UTC).strftime("%Y-%m-%d"),
        "branch": branch,
        "base": base,
        "outcome": outcome,
        "push": {
            "result": push_result,
            "remote": "origin",
            "branch": "main",
        },
        "cleanup_performed": cleanup_performed,
    }
    body = (
        f"# merge-to-main {outcome}\n\n"
        f"Branch: {branch}\n"
        f"Base: {base}\n"
        f"Push result: {push_result}\n"
        f"Cleanup performed: {cleanup_performed}\n"
    )
    write_entry(metadata, body, mirror_to_session_buddy=True)


def _write_sticky_failure_marker(
    worktree_root: Path,
    branch: str,
    held_back_siblings: list[str],
    ineligible_commits: list[str],
) -> None:
    """Write the sticky-failure marker for a held-back gate.

    Per the decision doc: the current worktree's `.review-state.json`
    gets ``stage_failed: "stage_5_push_held_back_by_consolidation_gate"``
    and ``stages_completed`` is appended with
    ``stage_5_consolidation_gate_held_back``. Subsequent
    `agent-merge-on-end.py` invocations see ``is_sticky_failed() == True``
    and skip the pipeline until the user resolves.

    Best-effort: if `.review-state.json` doesn't exist (fresh
    worktree, never reviewed), this is a no-op — the gate's held-back
    state is still recorded in the dev log.
    """
    state_path = worktree_root / ".review-state.json"
    if not state_path.exists():
        return
    try:
        state = json.loads(state_path.read_text())
    except json.JSONDecodeError, OSError:
        return
    if not isinstance(state, dict):
        return
    state["stage_failed"] = "stage_5_push_held_back_by_consolidation_gate"
    completed = state.get("stages_completed") or []
    if "stage_5_consolidation_gate_held_back" not in completed:
        completed.append("stage_5_consolidation_gate_held_back")
    state["stages_completed"] = completed
    state["held_back_sibling_worktrees"] = held_back_siblings
    state["held_back_pending_commits"] = ineligible_commits
    state["current_stage"] = "stage_5_push_held_back"
    try:
        state_path.write_text(json.dumps(state, indent=2, sort_keys=True))
    except OSError:
        pass  # best-effort; dev log still captures the state


def _default_dispatcher(
    agent: str,
    prompt: str,
    *,
    worktree: dict[str, Any] | None = None,
) -> str:
    """Default stage-2 dispatcher.

    Routes the prompt to ``agent`` via the Mahavishnu pool — the
    ``pool_route_execute`` MCP tool — and returns the reviewer's reply
    text. The routing itself lives in
    :mod:`mahavishnu.core.merge_review_dispatcher`.

    ``worktree`` is forwarded to the pool tool. The pipeline sets it
    because the three reviewers run concurrently: the repo's rule for
    parallel agents on one repo is worktree isolation, and a reviewer
    that ran ``git stash`` in the shared checkout on 2026-11-06
    disturbed another reviewer's work.

    Fail-loud: a dispatch failure returns a reply carrying no parseable
    verdict, which :func:`parse_verdict` maps to ``decision="block"``. A
    merge whose reviewers could not be reached is aborted, not waved
    through.
    """
    from .merge_review_dispatcher import dispatch_review

    return dispatch_review(agent, prompt, worktree=worktree)


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


def _resolve_local_branch(base: str) -> str:
    """Resolve a base ref to the local branch that will carry the squash.

    ``git checkout origin/main`` leaves a **detached HEAD**: the
    squash-merge then commits onto a floating ref that ``git gc``
    reclaims, so local ``main`` never moves. Stage 5 pushes ``main``,
    so the pipeline would report success while shipping nothing — and
    stage 6 would prune the branch that held the work.

    So a remote-tracking base resolves to its local counterpart when
    that branch exists. The resolved ref is used for *both* the rebase
    target and the landing branch, so the branch is replayed onto the
    same trunk the squash lands on. Rebasing onto a stale
    ``origin/main`` while landing on local ``main`` would sweep the
    trunk's unpushed commits into the squash.

    A base that is already a local branch is returned unchanged, and a
    remote-tracking ref with no local counterpart is returned unchanged
    (there is no local branch to land on).

    Args:
        base: The base ref to resolve.

    Returns:
        The local branch to use as the merge base, when one exists.
    """
    if not base.startswith("origin/"):
        return base
    local_name = base[len("origin/") :]
    show_ref_result = subprocess.run(  # nosec B603 — argv-list, no shell
        ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{local_name}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if show_ref_result.returncode == 0:
        return local_name
    return base


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
    no_consolidation_gate: bool = False,
    no_crackerjack: bool = False,
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
    # The base must name a real local branch: stage 4 checks it out in
    # the main checkout to land the squash-merge, and `git checkout
    # origin/main` would leave a detached HEAD — the commit would land
    # on a floating ref, `main` would never move, and stage 5 would
    # push a `main` that does not contain the work.
    base = _resolve_local_branch(base)
    branch = _resolve_branch(worktree_root, branch)

    # Stage 2 — ensemble review (REQ-004).
    if review_mode != "none":
        from .merge_review_dispatcher import build_review_prompt, ensure_review_pool

        # The repository the branch belongs to. The pool forks the
        # reviewer's isolated worktree from it, and it resolves that
        # from the prompt — without it the pool falls back to its own
        # working directory, so a merge reviewing a branch in another
        # repository asked for a worktree of a branch that does not
        # exist there. The main checkout is the right answer: it is
        # the same repository the branch belongs to, and it is inside
        # the operator's allowed repository roots (a worktree under
        # ``~/.local/state`` is not).
        repo_root = _find_main_checkout_path(worktree_root)
        if repo_root is None:
            print(
                "[merge_to_main] cannot locate the main checkout of "
                f"{worktree_root}; the review needs the repository the "
                "branch belongs to",
                file=sys.stderr,
            )
            # Stage 2 could not run, so this is a review failure. The
            # rebase-conflict code means "stage 4 could not land the
            # merge", and reporting that here sent the operator
            # looking for a conflict that does not exist.
            return EXIT_REVIEW_FAILURE

        prompt = build_review_prompt(branch, base, worktree_root, repo_root)
        # The three reviewers run concurrently, so each gets its own
        # checkout: the repo's rule for parallel agents on one repo is
        # worktree isolation, and a reviewer that ran ``git stash`` in
        # the shared checkout on 2026-11-06 disturbed another
        # reviewer's work. ``on_completion="discard"`` — a reviewer
        # must not merge anything back.
        #
        # ``base_branch`` is the branch **under review**, not the merge
        # base. The worktree is created from that ref, so a checkout of
        # the merge base would put the reviewer on the trunk's code and
        # not on the code it was asked to judge — the reviewer would
        # have to read the diff by absolute path to see the change at
        # all. The branch is created *from* the reviewed ref (the
        # worktree manager makes a new branch), so the reviewed branch
        # staying checked out elsewhere is not a conflict.
        worktree_options: dict[str, Any] = {
            "isolation": "worktree",
            "base_branch": branch,
            "on_completion": "discard",
        }
        # Isolation needs a pool whose worker session starts in the
        # worktree, and only a one-shot SHELL worker does that. The
        # auto-spawned pool is a pre-spawned shepherd pool, which
        # cannot, so without this the dispatch below finds no pool
        # able to honour the directory and every merge stops at stage
        # 2 with an instruction to spawn one by hand. The pipeline
        # knows it needs the capability, so the pipeline provides it.
        if not ensure_review_pool():
            # The dispatch would fail with the router's generic
            # message, and the remedy that message names is a no-op
            # when a pool of that name already exists in the wrong
            # form. Say what actually happened instead.
            print(
                "[merge_to_main] could not provision a pool that can "
                "isolate the review; the review was not dispatched",
                file=sys.stderr,
            )
            return EXIT_REVIEW_FAILURE
        verdicts = run_review(
            domain_specialist="python-pro",
            generalist_pool=AGENT_POOL,
            prompt=prompt,
            dispatcher=partial(_default_dispatcher, worktree=worktree_options),
        )
        verdict = aggregate_verdicts(verdicts)
        print(_format_verdicts(verdicts), file=sys.stderr)
        if verdict in {"iterate", "block"}:
            return EXIT_REVIEW_FAILURE

    # Stage 3 — crackerjack gate (REQ-013).
    if no_crackerjack:
        # Explicit operator opt-out (fail-loud bypass per
        # `feedback-bodai-push-is-user-controlled`). Logged here, not
        # silently — the dev-log entry captures the bypass.
        print(
            "[merge_to_main] --no-crackerjack set: skipping stage 3 "
            "crackerjack gate (operator-approved bypass; per "
            "docs/decisions/2026-10-14-fast-hooks-vs-comprehensive.md)",
            file=sys.stderr,
        )
    else:
        gate_rc, _gate_stderr = run_crackerjack_gate(worktree_root)
        if gate_rc != 0:
            return EXIT_CRACKERJACK_FAILURE

    # Stage 4 — squash-merge (spec §4.5).
    squash_rc, _squash_stderr = run_squash_merge(worktree_root, base, branch)
    if squash_rc != 0:
        return squash_rc  # EXIT_REBASE_CONFLICT typically

    # Stage 4.5 — pre-push consolidation gate (per new decision doc).
    # Held back = sticky-failure marker, stage 6 skipped, EXIT_OK.
    held_back = False
    if not no_consolidation_gate:
        gate_clear, held_back_siblings, ineligible_commits = _run_consolidation_gate(
            worktree_root,
            base,
        )
        if not gate_clear:
            held_back = True
            _write_held_back_log(
                worktree_root,
                branch,
                base,
                held_back_siblings,
                ineligible_commits,
            )
            _write_sticky_failure_marker(
                worktree_root,
                branch,
                held_back_siblings,
                ineligible_commits,
            )
            print(
                f"[merge_to_main] push held back: pre-push consolidation gate "
                f"(siblings={len(held_back_siblings)}, "
                f"ineligible={len(ineligible_commits)}); "
                f"see dev-log entry and .review-state.json for details",
                file=sys.stderr,
            )
            return EXIT_OK

    # Stage 5 — auto-push (skippable via --no-push; spec §4.6).
    push_result = "skipped"
    if not no_push:
        push_rc, _push_stderr = run_push("main")
        if push_rc != 0:
            _write_merge_log(
                worktree_root,
                branch,
                base,
                push_result="diverged",
                cleanup_performed=False,
                outcome="push_failed",
            )
            return EXIT_PUSH_DIVERGENCE
        push_result = "ok" if _origin_remote_exists() else "no_remote"

    # Stage 6 — cleanup (skippable via --no-cleanup; spec REQ-012).
    # ALSO skipped when the consolidation gate held back (stage 4.5):
    # the branch and worktree must remain until the push lands; otherwise
    # the squash-commit gets orphaned.
    cleanup_performed = False
    if not no_cleanup and not held_back:
        cleanup_rc, _cleanup_stderr = _run_cleanup(worktree_root)
        if cleanup_rc != 0:
            _write_merge_log(
                worktree_root,
                branch,
                base,
                push_result=push_result,
                cleanup_performed=False,
                outcome="cleanup_failed",
            )
            return EXIT_CLEANUP_FAILURE
        cleanup_performed = True

    _write_merge_log(
        worktree_root,
        branch,
        base,
        push_result=push_result,
        cleanup_performed=cleanup_performed,
        outcome="merged",
    )
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
        "--no-consolidation-gate",
        action="store_true",
        help=(
            "skip stage 4.5 pre-push consolidation gate (default: gate "
            "runs between squash-merge and push; held back writes a "
            "sticky-failure marker and skips stage 6)"
        ),
    )
    parser.add_argument(
        "--no-cleanup",
        action="store_true",
        help="skip stage 6 (default: prune the merged worktree)",
    )
    parser.add_argument(
        "--no-crackerjack",
        action="store_true",
        help=(
            "skip stage 3 crackerjack gate (operator-approved bypass; "
            "logged in dev-log per docs/decisions/2026-10-14-fast-hooks-vs-comprehensive.md)"
        ),
    )
    parser.add_argument(
        "--from",
        dest="base",
        default=None,
        help=(
            "rebase base override (default: origin/main if remote exists, else "
            "main; a remote-tracking ref resolves to its local branch so the "
            "squash-merge lands on a real branch)"
        ),
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
        no_consolidation_gate=args.no_consolidation_gate,
        no_crackerjack=args.no_crackerjack,
    )


if __name__ == "__main__":
    sys.exit(main())
