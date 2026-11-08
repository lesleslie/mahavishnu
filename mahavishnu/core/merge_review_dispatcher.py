"""Real stage-2 review dispatcher for the trunk-based agent-review workflow.

``mahavishnu.core.merge_to_main`` used to ship a stub dispatcher that
returned a hardcoded ``<verdict>decision: pass</verdict>`` for every
reviewer, so the 3-agent ensemble review gated nothing. This module is the
real implementation: it dispatches each review to the Mahavishnu worker
pool over the server's MCP surface and returns the reviewer's reply text.

Design notes
------------

- The pool route is reached over MCP (``pool_route_execute``) rather than
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
#: was still working through the changed files.
REVIEW_DISPATCH_TIMEOUT: float = 1800.0

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


def build_review_prompt(branch: str, base: str, worktree_root: Path) -> str:
    """Build the review prompt shared by the reviewers.

    The prompt carries the exact diff context and the worktree path so a
    reviewer can read the full diff itself. Without the diff context the
    reviewer has nothing to judge, which is what made the previous
    one-line prompt useless.

    The prompt is reviewer-agnostic: ``run_review`` hands the same prompt
    to each of the three reviewers, and the per-reviewer role is added by
    the dispatcher (which knows which agent it is routing to).
    """
    diff_context = collect_diff_context(branch, base, worktree_root)
    parts = [
        f"Review the diff on branch {branch!r} relative to {base!r}.",
        f"Worktree: {worktree_root}",
    ]
    if diff_context:
        parts.append(diff_context)
        parts.append(
            "Read the full diff from the worktree path above before judging it."
        )
    else:
        parts.append(
            "The diff could not be summarized automatically; read it from "
            "the worktree path above."
        )
    parts.append(
        "You are reviewing, not implementing: do not modify any file in "
        "the worktree, and do not run the test suite -- the merge pipeline "
        "runs the quality gate after this review. If a claim needs "
        "confirming, run only the narrowest test that shows it."
    )
    parts.append(
        "Reply with the verdict block and nothing outside it: "
        "<verdict>decision: pass|needs_adjustment|block note: ...</verdict>, "
        "with the note under 600 characters and the findings that justify "
        "it inside the note. The pool captures the last screenful of your "
        "reply, so prose in front of the block arrives with the block's "
        "opening tag cut off -- and a verdict that arrives truncated "
        "cannot be read."
    )
    return "\n\n".join(parts)


def _extract_reply_text(payload: Any) -> str:
    """Pull the reviewer's reply text out of the pool route response.

    ``CommonMCPClient.call_tool`` returns the raw MCP ``CallToolResult``,
    whose text lives in ``content[0].text``; that text is itself the JSON
    envelope of the ``pool_route_execute`` result dict, which carries the
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
#: ``pool_route_execute`` sends ``{"prompt": ...}``. A pool whose worker
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


async def dispatch_review_async(
    agent: str,
    prompt: str,
    *,
    mcp_url: str | None = None,
    timeout: float = REVIEW_DISPATCH_TIMEOUT,
) -> str:
    """Dispatch one review to the pool and return the reviewer's reply.

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
            call_result = await client.call_tool(
                "pool_route_execute",
                {
                    "prompt": routed_prompt,
                    "pool_selector": "least_loaded",
                    "timeout": timeout,
                },
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
    return _extract_agent_text(_parse_pool_result(reply))


def dispatch_review(
    agent: str,
    prompt: str,
    *,
    mcp_url: str | None = None,
    timeout: float = REVIEW_DISPATCH_TIMEOUT,
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
            dispatch_review_async(agent, prompt, mcp_url=mcp_url, timeout=timeout)
        )
    except (Exception, asyncio.CancelledError) as exc:  # noqa: BLE001
        logger.warning("review dispatch failed for agent %r: %r", agent, exc)
        return (
            f"review dispatch to the Mahavishnu pool failed for agent "
            f"{agent!r}: {exc!r}"
        )
