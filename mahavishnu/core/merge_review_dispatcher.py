"""Real stage-2 review dispatcher for the trunk-based agent-review workflow.

``mahavishnu.core.merge_to_main`` used to ship a stub dispatcher that
returned a hardcoded ``<verdict>decision: pass</verdict>`` for every
reviewer, so the 3-agent ensemble review gated nothing. This module is the
real implementation: it dispatches each review to the Mahavishnu worker
pool over the server's MCP surface and returns the reviewer's reply text.

Design notes
------------

- The pool route is reached over MCP (``mahavishnu_pool_route_execute``) rather than
  by constructing a :class:`~mahavishnu.pools.manager.PoolManager` here.
  The pool manager is a dependency-injected, lifecycle-managed object on
  the server; the MCP surface is the supported programmatic entry point
  (per the repo's tool-preference policy) and keeps this module free of
  pool-spawning side effects.
- The async core is :func:`dispatch_review_async`; the synchronous
  :func:`dispatch_review` is a thin wrapper so the existing synchronous
  pipeline (``run_pipeline`` → ``run_review`` → dispatcher) does not have
  to become async. The async form is the reusable one.
- Dispatch failures are **fail-loud**: they return a reply that carries no
  parseable verdict, which ``merge_to_main.parse_verdict`` maps to
  ``decision="block"``. A merge whose reviewers could not be reached is
  aborted, not waved through.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
import json
import logging
import os
import re
import subprocess
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

#: Default MCP endpoint of the Mahavishnu server (mirrors the hook
#: default in ``.claude/hooks/mahavishnu-pool-bootstrap.py`` and the
#: CLI default in ``mahavishnu/_main_cli.py``).
DEFAULT_MCP_URL: str = "http://localhost:8680/mcp"

#: Wall-clock budget for a single review dispatch, in seconds. The pool
#: route itself gets a slightly smaller budget so the MCP call has time
#: to report a timeout rather than being cut off mid-flight.
#:
#: A review of a multi-commit diff takes minutes, not seconds: the
#: reviewer reads the diff, reads the files it touches, and only then
#: answers. At 300 s the worker was cut off mid-review, the pool
#: reported a timeout carrying a partial pane, and the reply had no
#: verdict in it -- so every merge blocked on a "malformed verdict"
#: that was really a reviewer that never finished. At 900 s the reviewer
#: was still working through the changed files, and at 1800 s the
#: domain specialist was still working through them: it made eighty
#: tool calls at about twenty seconds each.
#:
#: This is the **server-side** budget: how long the pool will let the
#: worker run. It is not how long the caller waits. The MCP client's
#: read timeout bounds the call itself -- a response stream that has
#: gone quiet is cut -- so the budget the reviewer actually has is
#: minutes, not an hour, and the review is lost rather than reported
#: as a timeout when the transport wins the race. The prompt states
#: the budget that is real (see ``build_review_prompt``), and this
#: constant stays the ceiling the server enforces under it.
REVIEW_DISPATCH_TIMEOUT: float = 3600.0

#: Bound on the diff context embedded in the review prompt. A repo-wide
#: format pass touches >1000 files; pasting the whole diff would blow
#: past the worker's context window and cost more than it buys.
MAX_DIFFSTAT_LINES: int = 60
MAX_DIFF_FILES: int = 120


def resolve_mcp_url() -> str:
    """Return the Mahavishnu MCP endpoint, honoring the env override.

    ``MAHAVISHNU_MCP_URL`` is the established override across the repo
    (``mahavishnu/_main_cli.py``, the SessionStart hooks, and the
    integration tests all use it).
    """
    return os.environ.get("MAHAVISHNU_MCP_URL", DEFAULT_MCP_URL)


def _git_output(args: list[str], cwd: Path) -> str:
    """Run a read-only git command, returning "" on any failure."""
    try:
        result = subprocess.run(  # nosec B603 — argv-list, no shell
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except OSError, subprocess.SubprocessError:
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout


def collect_diff_context(branch: str, base: str, worktree_root: Path) -> str:
    """Summarize ``base..branch`` for the review prompt.

    Returns a bounded, human-readable summary: the diffstat plus the list
    of changed files. Both are truncated — a review prompt has to fit in
    a worker's context, and the worker can always read the full diff from
    the worktree path that the prompt also carries.

    Returns an empty string when the diff cannot be computed (for example
    when the branch is not reachable from ``worktree_root``); the prompt
    then falls back to instructing the reviewer to inspect the worktree.
    """
    diffstat = _git_output(["diff", "--stat", f"{base}...{branch}"], worktree_root)
    names = _git_output(["diff", "--name-only", f"{base}...{branch}"], worktree_root)

    sections: list[str] = []
    if diffstat.strip():
        lines = diffstat.rstrip().splitlines()
        if len(lines) > MAX_DIFFSTAT_LINES:
            kept = lines[: MAX_DIFFSTAT_LINES - 1]
            kept.append(f"... ({len(lines) - MAX_DIFFSTAT_LINES + 1} more lines)")
            lines = kept
        sections.append("Diffstat:\n" + "\n".join(lines))
    if names.strip():
        file_lines = names.rstrip().splitlines()
        total = len(file_lines)
        if total > MAX_DIFF_FILES:
            file_lines = file_lines[:MAX_DIFF_FILES]
            file_lines.append(f"... ({total - MAX_DIFF_FILES} more files)")
        sections.append("Changed files:\n" + "\n".join(file_lines))
    return "\n\n".join(sections)


def build_review_prompt(
    branch: str,
    base: str,
    worktree_root: Path,
    repo_path: Path | None = None,
) -> str:
    """Build the review prompt shared by the reviewers.

    The prompt carries the exact diff context and the worktree path so a
    reviewer can read the full diff itself. Without the diff context the
    reviewer has nothing to judge, which is what made the previous
    one-line prompt useless.

    It also carries the **repository**: the pool forks the reviewer's
    isolated worktree from the repository the branch belongs to, and it
    resolves that from the prompt. Without the repository named, the
    pool falls back to its own working directory — right for the
    server's own repository, wrong for every other one, so a merge
    reviewing a branch in another repository asked for a worktree of a
    branch that does not exist there.

    The prompt is reviewer-agnostic: ``run_review`` hands the same prompt
    to each of the three reviewers, and the per-reviewer role is added by
    the dispatcher (which knows which agent it is routing to).
    """
    diff_context = collect_diff_context(branch, base, worktree_root)
    parts = [
        f"Review the diff on branch {branch!r} relative to {base!r}.",
        f"Worktree: {worktree_root}",
    ]
    if repo_path is not None:
        # The ``.git`` suffix is the token the pool reads to resolve
        # the repository; the path itself is the repository's root.
        parts.append(f"Repository: {repo_path}/.git")
    if diff_context:
        parts.append(diff_context)
        parts.append("Read the diff from the worktree path above before judging it.")
    else:
        parts.append(
            "The diff could not be summarized automatically; read it from "
            "the worktree path above."
        )
    parts.append(
        "You have about three minutes of wall clock. The dispatch that runs "
        "you is cut off after that -- not by a timeout you can see, but by "
        "the transport the reply travels over -- and a reviewer that is cut "
        "off has no verdict at all, so its review counts for nothing. Work "
        "from the summary above and read only the files you need to judge, "
        "not every changed file."
    )
    parts.append(
        "You are reviewing, not implementing: do not modify any file in "
        "the worktree. Do not run pytest, crackerjack, tox, nox, or any "
        "other test runner -- not even a single test file. The merge "
        "pipeline runs the quality gate after this review, and a suite "
        "run spends the budget the read needed. If a claim needs "
        "confirming, read the code that shows it."
    )
    parts.append(
        "Your shell starts in an isolated checkout of the branch under "
        "review -- a different directory holding the same commit, so the "
        "code you are looking at is the code under review. Read files by "
        "the absolute path under the worktree path above; a relative path "
        "reads whatever your shell happens to be in."
    )
    parts.append(
        "Reply with the verdict block and nothing outside it: "
        "<verdict>decision: pass|needs_adjustment|block note: ...</verdict>, "
        "with the note under 600 characters and the findings that justify "
        "it inside the note.\n\n"
        "Your whole reply has a budget of about 1,500 characters: the pool "
        "captures the last screenful of your terminal and drops everything "
        "before it. So the block must be the LAST thing you write -- put "
        "any analysis before it, never after it -- and the reply as a "
        "whole must fit. A reply that runs past the screen arrives with "
        "its beginning cut off, and a verdict that arrives truncated "
        "cannot be read, so the review would be lost rather than counted."
    )
    return "\n\n".join(parts)


def _extract_reply_text(payload: Any) -> str:
    """Pull the reviewer's reply text out of the pool route response.

    ``CommonMCPClient.call_tool`` returns the raw MCP ``CallToolResult``,
    whose text lives in ``content[0].text``; that text is itself the JSON
    envelope of the ``mahavishnu_pool_route_execute`` result dict, which carries the
    worker's output under ``result``. Every layer is optional, so this
    walks the known shapes and falls back to the stringified payload.
    """
    if isinstance(payload, str):
        return payload

    content = getattr(payload, "content", None)
    if content:
        first = content[0]
        text = getattr(first, "text", None)
        if isinstance(text, str):
            return _extract_reply_text(text)

    if isinstance(payload, Mapping):
        for key in ("result", "output", "text", "content"):
            if key in payload:
                nested = payload[key]
                if isinstance(nested, str):
                    return nested
                return _extract_reply_text(nested)
        return json.dumps(payload, default=str)

    return str(payload)


#: The pool the review pipeline provisions. The name is the spawn
#: tool's idempotency key, so a second merge reuses the pool instead of
#: accumulating one pool per merge.
REVIEW_POOL_NAME = "merge-review"

#: The worker type that can start a session in a named directory. Only
#: a one-shot SHELL worker can: its session begins when the task
#: arrives, so the task's ``cwd`` can point at the worktree. A
#: pre-spawned worker is already running, in the directory it was
#: launched in.
REVIEW_POOL_WORKER_TYPE = "terminal-claude"


def _pools_from_listing(payload: Any) -> list[dict[str, Any]]:
    """Read the pool list out of a ``mahavishnu_pool_list`` result."""
    text = _extract_reply_text(payload)
    try:
        parsed = json.loads(text)
    except TypeError, ValueError:
        return []
    if isinstance(parsed, Mapping):
        for key in ("result", "pools", "output"):
            nested = parsed.get(key)
            if isinstance(nested, list):
                return [p for p in nested if isinstance(p, Mapping)]
        return []
    if isinstance(parsed, list):
        return [p for p in parsed if isinstance(p, Mapping)]
    return []


def _spawn_outcome(payload: Any) -> tuple[str, str]:
    """Read the ``(status, error)`` a pool spawn reported.

    The spawn tool never raises: it returns ``{"status": "failed",
    "error": "..."}`` so a failure reaches the caller as data. A
    provisioning step that ignored that data would report success for
    a pool that was never created.
    """
    text = _extract_reply_text(payload)
    try:
        parsed = json.loads(text)
    except TypeError, ValueError:
        return "unknown", text
    if not isinstance(parsed, Mapping):
        return "unknown", text
    status = parsed.get("status")
    error = parsed.get("error")
    return (
        status if isinstance(status, str) else "unknown",
        error if isinstance(error, str) else "",
    )


async def _review_pool_registered(client: Any) -> bool:
    """Whether the pool the reviews run in is registered.

    The check is by name, not by capability: the capability belongs to
    the server, which is where the routing happens, and a client that
    had to read the server's capability field would break against a
    server that does not carry it. The server refuses a task it cannot
    honour, and its refusal names the pool — so the operator learns
    that the pool of that name is the wrong kind from the error that
    actually stopped the dispatch.
    """
    listed = await client.call_tool("mahavishnu_pool_list", {})
    return any(
        pool.get("name") == REVIEW_POOL_NAME for pool in _pools_from_listing(listed)
    )


async def ensure_review_pool_async(
    mcp_url: str | None = None,
    timeout: float = 60.0,
) -> bool:
    """Make sure a pool that can isolate a review exists.

    Worktree isolation needs a pool whose worker session *starts* in
    the worktree, and only a one-shot SHELL worker does that. The
    auto-spawned pool is a pre-spawned shepherd pool, which cannot —
    so a merge that asked for isolation found no pool able to honour
    it, and every merge stopped at stage 2 with a message telling the
    operator to spawn one by hand. The capability constraint was
    enforced; nothing supplied the capability it required.

    This supplies it: the review pool is created once, keyed by name,
    and reused by every later merge.

    Returns ``True`` when the review pool is registered — and it says
    so only after *looking*, because the spawn tool reports failure as
    a ``status`` rather than by raising. A spawn that failed leaves
    the merge without the pool it needs, and saying "provisioned" then
    would replace the real reason with a misleading one.

    A failure here is logged rather than raised: the dispatch that
    follows produces the real error, and a provisioning failure that
    masked it would replace the reason with a misleading one.
    """
    url = mcp_url or resolve_mcp_url()
    from mcp_common.clients.common_mcp_client import CommonMCPClient

    try:
        async with CommonMCPClient(base_url=url, timeout=timeout) as client:
            if await _review_pool_registered(client):
                return True
            spawned = await client.call_tool(
                "mahavishnu_pool_spawn",
                {
                    "name": REVIEW_POOL_NAME,
                    "pool_type": "mahavishnu",
                    "worker_type": REVIEW_POOL_WORKER_TYPE,
                    "min_workers": 1,
                    "max_workers": 10,
                },
            )
            status, error = _spawn_outcome(spawned)
            if status not in {"spawned", "exists"}:
                logger.warning(
                    "the %r pool could not be provisioned (status=%r): %s",
                    REVIEW_POOL_NAME,
                    status,
                    error,
                )
                return False
            logger.info(
                "provisioned the %r pool for worktree-isolated reviews",
                REVIEW_POOL_NAME,
            )
            return True
    except (Exception, asyncio.CancelledError) as exc:  # noqa: BLE001
        logger.warning("could not provision a worktree-capable review pool: %r", exc)
        return False


def ensure_review_pool(
    mcp_url: str | None = None,
    timeout: float = 60.0,
) -> bool:
    """Synchronous wrapper around :func:`ensure_review_pool_async`.

    The merge pipeline is synchronous end to end, so the async core is
    bridged here the same way :func:`dispatch_review` bridges its own.
    """
    try:
        return asyncio.run(ensure_review_pool_async(mcp_url=mcp_url, timeout=timeout))
    except (Exception, asyncio.CancelledError) as exc:  # noqa: BLE001
        logger.warning("could not provision a worktree-capable review pool: %r", exc)
        return False


#: A worker runs Claude Code with ``--output-format stream-json``, so
#: what the pool captures is a JSON fragment of that stream rather than
#: prose. The agent's reply lives in the stream's ``"result"`` field,
#: JSON-escaped. The pool captures a window of the stream, so the
#: fragment's head may be cut -- the ``"result"`` field is what carries
#: the answer.
_SDK_RESULT_RE = re.compile(r'"result"\s*:\s*"((?:[^"\\]|\\.)*)"')


def _extract_agent_text(worker_output: str) -> str:
    """The agent's reply text from a worker's captured output.

    Without this step the verdict block reaches the parser
    JSON-escaped: the parser's pattern wants whitespace between
    ``<verdict>`` and ``decision:``, and the escaped form has a literal
    backslash-n. Every review then parsed as malformed -- and a
    malformed verdict is a fail-loud ``block``, so a reviewer that
    returned ``decision: pass`` gated the merge as a block.
    """
    match = _SDK_RESULT_RE.search(worker_output)
    if match is None:
        return worker_output
    try:
        decoded = json.loads(f'"{match.group(1)}"')
    except TypeError, ValueError:
        return worker_output
    if not isinstance(decoded, str) or not decoded.strip():
        return worker_output
    return decoded


def _parse_pool_result(text: str) -> str:
    """Extract the worker's reply from the pool result JSON, if present."""
    stripped = text.strip()
    if not stripped.startswith("{"):
        return text
    try:
        parsed = json.loads(stripped)
    except TypeError, ValueError:
        return text
    if isinstance(parsed, Mapping):
        for key in ("result", "output", "text"):
            value = parsed.get(key)
            if isinstance(value, str) and value.strip():
                return value
    return text


#: The pool's default worker substrate is ``shepherd`` (the default since
#: the 2026-09-24 legacy-worker deprecation). Per
#: ``mahavishnu/workers/registry.py``, shepherd-backed workers "do not
#: consume a prompt at all -- they take a command or a task ref", while
#: ``mahavishnu_pool_route_execute`` sends ``{"prompt": ...}``. A pool whose worker
#: cannot take a prompt answers with this error.
POOL_TASK_SHAPE_ERROR: str = "Task must specify 'task_ref' or 'command'"

#: The one pool status that means the worker finished. Every other
#: status -- ``failed``, ``timeout``, ``cancelled`` -- means the run
#: did not produce a review, and a run without a review has no verdict.
POOL_COMPLETED_STATUS: str = "completed"

_TASK_SHAPE_REMEDY: str = (
    "the pool's worker substrate does not accept a 'prompt' task; "
    "shepherd-backed workers require 'command' or 'task_ref' "
    "(see mahavishnu/workers/registry.py)"
)


def _pool_envelope(payload: Any) -> tuple[str, str] | None:
    """The ``(status, error)`` pair from a pool response envelope.

    The envelope is the pool's answer -- ``{"status": ..., "output":
    ..., "error": ...}`` -- or an MCP wrapper nesting it under
    ``"result"``. Returns ``None`` when the payload carries no status,
    which means it is not an envelope at all.
    """
    if isinstance(payload, str):
        stripped = payload.strip()
        if not stripped.startswith("{"):
            return None
        try:
            payload = json.loads(stripped)
        except TypeError, ValueError:
            return None
    if not isinstance(payload, Mapping):
        return None
    status = payload.get("status")
    if not isinstance(status, str):
        nested = payload.get("result")
        if isinstance(nested, Mapping):
            return _pool_envelope(nested)
        return None
    error = payload.get("error")
    return status, error.strip() if isinstance(error, str) else ""


def _pool_failure_message(payload: Any) -> str | None:
    """Return an actionable message when the pool reported a failure.

    The pool answers with ``{"status": "completed", ...}`` when the
    worker finished, and with the worker's own status otherwise --
    ``failed``, ``timeout``, ``cancelled`` -- plus an ``error``. A run
    that did not complete carries no verdict, so it has to read as an
    explicit failure: the difference between an operator who knows the
    reviewer timed out and one who thinks the reviewer crashed.

    The status has to be read from the *envelope*. The worker's output
    is a separate field of that envelope, and reducing the envelope to
    that output first -- which is what the verdict path does -- throws
    the status away.
    """
    envelope = _pool_envelope(payload)
    if envelope is None:
        return None
    status, error = envelope
    if status == POOL_COMPLETED_STATUS:
        return None
    message = error
    if not message:
        if status == "timeout":
            message = "the reviewer did not finish within the dispatch timeout"
        else:
            message = f"the pool reported status {status!r}"
    if POOL_TASK_SHAPE_ERROR in message:
        return f"{message} — {_TASK_SHAPE_REMEDY}"
    return message


def _worktree_context(payload: Any) -> dict[str, Any] | None:
    """The worktree context the pool attached to a dispatch result.

    ``mahavishnu_pool_route_execute`` adds a ``worktree`` key to its
    result when isolation engaged, carrying the checkout the worker
    ran in. Returns ``None`` when the key is absent — which means the
    dispatch did **not** run in an isolated checkout.

    The context is **server-attested**, not agent-controlled. It is a
    sibling key of the envelope, set by the pool tool's own code path
    after ``create_worktree`` succeeds; the reviewer's reply travels
    in the separate ``output`` field, where a string cannot forge a
    sibling key of the envelope it sits in. The signal is that the key
    exists and is non-empty.
    """
    if isinstance(payload, str):
        stripped = payload.strip()
        if not stripped.startswith("{"):
            return None
        try:
            payload = json.loads(stripped)
        except TypeError, ValueError:
            return None
    if not isinstance(payload, Mapping):
        return None
    context = payload.get("worktree")
    if isinstance(context, Mapping):
        return dict(context)
    nested = payload.get("result")
    if isinstance(nested, Mapping):
        inner = nested.get("worktree")
        if isinstance(inner, Mapping):
            return dict(inner)
    return None


#: A reply carrying this prefix is not a reviewer's answer: the
#: dispatch itself failed, so there is no verdict to read. It is
#: retried exactly like an unreadable verdict — a server that could
#: not be reached is worth one more try — and the reason travels with
#: it so the operator is told what actually happened.
DISPATCH_FAILED_PREFIX = "the dispatch failed: "


def _isolation_failure(agent: str) -> str:
    """The fail-loud reply for a dispatch that did not isolate.

    Isolation was requested and the pool did not provide it: either
    the worktree could not be created, or the pool type cannot honour
    a working directory. Both leave the reviewer in the shared
    checkout — the exact situation where a reviewer ran ``git stash``
    in another session's work on 2026-11-06. The review is abandoned
    rather than run unsafely.
    """
    return (
        f"<verdict>decision: block note: worktree isolation was "
        f"requested for {agent!r} but the dispatch ran without an "
        f"isolated checkout, so the reviewer would have shared the "
        f"repository's main checkout with every other session. The "
        f"review is not safe to run in that state.</verdict>"
    )


async def dispatch_review_async(
    agent: str,
    prompt: str,
    *,
    mcp_url: str | None = None,
    timeout: float = REVIEW_DISPATCH_TIMEOUT,
    worktree: dict[str, Any] | None = None,
) -> str:
    """Dispatch one review to the pool and return the reviewer's reply.

    ``worktree`` is passed straight through to
    ``mahavishnu_pool_route_execute``. The merge pipeline sets it to
    ``{"isolation": "worktree", "on_completion": "discard"}`` because the
    three reviewers now run **concurrently**: the repo's rule for
    parallel agents on one repo is worktree isolation, and a reviewer
    that ran ``git stash`` in a shared checkout on 2026-11-06 disturbed
    another reviewer's work. With isolation, each reviewer gets its own
    checkout and its edits are discarded.

    When isolation is requested it is **verified**, not assumed: the
    pool skips the worktree silently when it cannot resolve the
    repository, and a pool type that cannot honour a working directory
    refuses the task outright. A dispatch that came back without an
    isolated checkout returns an explicit block verdict rather than a
    review that ran in the shared checkout.

    Fail-loud: any transport, protocol, or server error returns a reply
    that carries no parseable verdict, which the caller's verdict parser
    turns into ``decision="block"``.
    """
    from mcp_common.clients.common_mcp_client import CommonMCPClient

    url = mcp_url or resolve_mcp_url()
    routed_prompt = (
        f"You are acting as the {agent!r} specialist reviewer.\n\n"
        f"{prompt}\n\n"
        "You are one of several independent reviewers; return only your "
        "verdict block."
    )
    try:
        async with CommonMCPClient(base_url=url, timeout=timeout) as client:
            tool_args: dict[str, Any] = {
                "prompt": routed_prompt,
                "pool_selector": "least_loaded",
                "timeout": timeout,
            }
            if worktree is not None:
                tool_args["worktree"] = worktree
            call_result = await client.call_tool(
                "mahavishnu_pool_route_execute",
                tool_args,
            )
    except (Exception, asyncio.CancelledError) as exc:  # noqa: BLE001
        # Fail-loud: a blocked merge, not a crash. ``CancelledError`` is
        # a ``BaseException``, so it has to be named explicitly — the
        # MCP client's anyio task group raises it while unwinding a
        # failed connection, and an unhandled one would take the whole
        # merge pipeline down instead of failing the review.
        logger.warning("review dispatch failed for agent %r: %r", agent, exc)
        return (
            f"review dispatch to the Mahavishnu pool failed for agent "
            f"{agent!r}: {exc!r}"
        )

    reply = _extract_reply_text(call_result)

    # A reply that carries no pool envelope is not a result at all: the
    # server raised, and the error text came back instead of the
    # dispatch's answer. That happens when the dispatch could not be
    # made at all — no pool can honour the directory the task named, or
    # the repository to isolate could not be resolved. Reporting that
    # as an isolation failure would replace the real reason with a
    # misleading one, so it is reported as what it is.
    if _pool_envelope(reply) is None:
        detail = reply.strip() or "the dispatch returned no pool envelope"
        return (
            f"<verdict>decision: block note: {DISPATCH_FAILED_PREFIX}{detail}</verdict>"
        )

    failure = _pool_failure_message(reply)
    if failure is not None:
        # The pool reached a worker but the run did not finish. Turn it
        # into an explicit block verdict carrying the reason, so the
        # operator sees *why* the review failed rather than a generic
        # "malformed verdict" note. The check reads the envelope, not the
        # worker's output: the status lives in the envelope, and the
        # output -- which is where a cut-off review ends up -- has no
        # status at all.
        return f"<verdict>decision: block note: {failure}</verdict>"

    # Isolation was requested. Confirm it engaged rather than assuming
    # it: the pool skips the worktree silently when it cannot resolve
    # the repository, and a pool type that cannot honour a working
    # directory refuses the task outright. Either way the reviewer
    # would be sharing the main checkout with every other session,
    # which is the situation the isolation exists to prevent.
    #
    # The signal is the ``worktree`` key the pool sets after it
    # created a worktree. It is server-attested — a sibling key of the
    # envelope, not part of the reviewer's reply — and it is absent
    # exactly when no worktree was created. The check is fail-closed:
    # a missing key *and* an empty context both mean the isolation
    # cannot be shown to have happened, and the review is abandoned.
    #
    # The path is logged when the pool reports it. A server that
    # predates that field still verifies on the key's presence, which
    # is what keeps this working across a rolling upgrade.
    if worktree is not None:
        context = _worktree_context(reply)
        if not context:
            logger.warning(
                "review dispatch for agent %r ran without an isolated "
                "worktree; the review is abandoned",
                agent,
            )
            return _isolation_failure(agent)
        logger.info(
            "review dispatch for agent %r ran in isolated worktree %s "
            "(branch %s, based on %s)",
            agent,
            context.get("path"),
            context.get("branch"),
            context.get("base_branch"),
        )

    return _extract_agent_text(_parse_pool_result(reply))


def dispatch_review(
    agent: str,
    prompt: str,
    *,
    mcp_url: str | None = None,
    timeout: float = REVIEW_DISPATCH_TIMEOUT,
    worktree: dict[str, Any] | None = None,
) -> str:
    """Synchronous wrapper around :func:`dispatch_review_async`.

    The merge pipeline is synchronous end to end (the SessionEnd hook and
    the CLI both call it directly), so the async core is bridged here
    rather than by making the whole pipeline async.

    Fail-loud, same as the async core: the MCP client's anyio task group
    can raise while the event loop is shutting down — after the
    coroutine's own ``try`` has already unwound — so the wrapper catches
    that too and converts it into the fail-loud reply.
    """
    try:
        return asyncio.run(
            dispatch_review_async(
                agent,
                prompt,
                mcp_url=mcp_url,
                timeout=timeout,
                worktree=worktree,
            )
        )
    except (Exception, asyncio.CancelledError) as exc:  # noqa: BLE001
        logger.warning("review dispatch failed for agent %r: %r", agent, exc)
        return (
            f"review dispatch to the Mahavishnu pool failed for agent "
            f"{agent!r}: {exc!r}"
        )
