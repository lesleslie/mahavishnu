"""Operator verification gate for the Qwen-CLI Bifrost route.

req: REQ-BIFROST-034

Port of ``scripts/verify_qwen_bifrost_gate.sh``. Preserves the contract the
two tests in ``tests/unit/test_terminal_worker_settings.py`` pin:

Preconditions (any missing aborts with ``EXIT_PRECONDITION``):

1. Bifrost gateway running -- the ready file must exist.
2. A real ``qwen`` binary on PATH (probed with ``qwen --version``).
3. The mahavishnu pool router reachable (``mahavishnu pool health``).

Pass criterion: after the dispatch, ``bifrost.log`` contains a JSON line with
``"caller_id":"mahavishnu"``.

Exit codes (unchanged from the shell original, so operator runbooks and any
wrapper scripts keep working):

==== ==========================================
Code Meaning
==== ==========================================
0    gate passed -- caller_id line found
1    gate failed -- no caller_id line within 30s
2    a precondition was not met
3    ``bifrost.log`` missing entirely
==== ==========================================
"""

from __future__ import annotations

import json
import posixpath
import re
import shutil
import subprocess
import time
from urllib.parse import urlsplit

import typer

from .paths import LOG_OUT, READY_FILE

CALLER_ID = "mahavishnu"
CALLER_MARKER = f'"caller_id":"{CALLER_ID}"'
DISPATCH_PROMPT = "Reply with a single word: bifrost-routed"

#: Exact request paths identifying the OpenAI-compatible endpoints the Qwen
#: route uses (``qwen_env_var`` defaults to ``OPENAI_BASE_URL``). Anthropic-side
#: traffic -- Claude Code and the workers it spawns -- arrives on
#: ``/anthropic/v1/messages`` instead, so this discriminates the two flows.
#:
#: Matched by exact equality against the *normalized* path, never by
#: substring: an unanchored ``"/chat/completions" in target`` would also
#: accept ``/v1/chat/completions/../../admin`` or ``/not-really/chat/completions``.
QWEN_ENDPOINT_PATHS: frozenset[str] = frozenset({"/v1/chat/completions", "/v1/completions"})

_MULTI_SLASH = re.compile(r"/{2,}")

EXIT_PASS = 0
EXIT_FAIL = 1
EXIT_PRECONDITION = 2
EXIT_NO_LOG = 3

#: Operator-friendly headroom for slow Qwen CLI first-token latency. The
#: stdbuf line-buffered log normally resolves this in under a second.
WAIT_SECONDS = 30


def _run(cmd: list[str], timeout: int = 60) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    except OSError, subprocess.SubprocessError:
        return subprocess.CompletedProcess(cmd, 127, "", "")


def check_preconditions() -> str | None:
    """Return a human-readable failure reason, or ``None`` if all are met."""
    if not READY_FILE.exists():
        return f"Bifrost not ready: {READY_FILE} is missing"

    if shutil.which("qwen") is None:
        return "Qwen CLI not on PATH"

    probe = _run(["qwen", "--version"], timeout=15)
    if probe.returncode != 0:
        return f"'qwen --version' failed (exit {probe.returncode})"

    health = _run(["mahavishnu", "pool", "health"], timeout=30)
    if health.returncode != 0 or "mahavishnu pool health" not in (health.stdout + health.stderr):
        return "'mahavishnu pool health' did not return expected output"

    return None


def log_baseline() -> int:
    """Byte offset of the end of ``bifrost.log`` right now.

    Everything before this offset is pre-existing history and is NOT evidence
    that the gate's own dispatch worked. A long-lived gateway accumulates
    caller_id lines from ordinary Bodai worker traffic, so a gate that greps
    the whole file passes instantly without proving anything.
    """
    try:
        return LOG_OUT.stat().st_size
    except OSError:
        return 0


def dispatch() -> int:
    """Drive one Qwen worker through the pool so Bifrost logs a caller_id.

    Returns the subprocess exit status. A non-zero status means the dispatch
    itself failed, which must fail the gate -- otherwise the gate would go on
    to poll for a line that can never arrive, or worse, match stale history.
    """
    result = _run(
        [
            "mahavishnu",
            "pool",
            "route",
            "--prompt",
            DISPATCH_PROMPT,
            "--worker-type",
            "terminal-qwen",
            "--selector",
            "least_loaded",
            "--timeout",
            "60",
        ],
        timeout=90,
    )
    for line in (result.stdout or "").splitlines()[:5]:
        typer.echo(f"  {line}")
    if result.returncode != 0:
        typer.echo(f"FAIL: dispatch exited {result.returncode}", err=True)
        for line in (result.stderr or "").splitlines()[:5]:
            typer.echo(f"  {line}", err=True)
    return result.returncode


def _iter_appended_lines(offset: int) -> list[str]:
    """Return log lines written after ``offset``, newest last."""
    try:
        with LOG_OUT.open("r", encoding="utf-8", errors="replace") as handle:
            handle.seek(offset)
            return handle.read().splitlines()
    except OSError:
        return []


def _normalize_request_path(target: str) -> str:
    """Return the normalized path portion of an HTTP request target.

    Strips any absolute-form URL and the query/fragment, collapses repeated
    slashes, and resolves ``.`` / ``..`` segments so that traversal cannot
    disguise one endpoint as another.

    Only a target carrying an explicit scheme is treated as a URL. A bare
    ``//v1/chat/completions`` is HTTP *origin-form* (a path), but
    :func:`urlsplit` would read its leading ``//`` as a network location and
    silently drop the first segment.
    """
    path = target
    if "://" in target:
        path = urlsplit(target).path
    path = path.split("?", 1)[0].split("#", 1)[0]
    if not path.startswith("/"):
        path = "/" + path
    # Collapse repeated slashes ourselves: POSIX normpath preserves a leading
    # "//" verbatim (its meaning is implementation-defined), which would let
    # "//v1/chat/completions" evade the exact-path comparison.
    path = _MULTI_SLASH.sub("/", path)
    normalized = posixpath.normpath(path)
    # normpath drops a trailing slash; the router treats /a/ and /a alike,
    # so that collapse is intended here.
    return normalized or "/"


def is_qwen_endpoint(target: str) -> bool:
    """True only for an exact, normalized Qwen-route endpoint path."""
    try:
        return _normalize_request_path(str(target)) in QWEN_ENDPOINT_PATHS
    except TypeError, ValueError:
        return False


def find_caller_line(lines: list[str]) -> str | None:
    """Return the first line proving *this* dispatch routed through Bifrost.

    Matching requires three things, not just the first:

    - ``caller_id`` parses to exactly ``mahavishnu`` (so a payload that
      merely contains the text elsewhere cannot satisfy the gate);
    - the record was served on the **OpenAI-compatible endpoint**
      (``http.target`` under ``/v1/chat/completions``), which is what the
      Qwen route uses via ``qwen_env_var`` / ``OPENAI_BASE_URL``;
    - it is a completion record (``latency_seconds`` present), not merely an
      HTTP access line.

    The endpoint check is what makes the gate attributable. Every Bodai
    worker shares this log and writes ``caller_id: "mahavishnu"``, so
    matching on caller_id alone would accept *any* concurrent worker
    traffic that happened to land inside the dispatch window. Qwen traffic
    is the only flow that arrives on ``/v1/chat/completions``; Claude Code
    and the workers it dispatches arrive on ``/anthropic/v1/messages``.
    """
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("{"):
            continue
        try:
            record = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict):
            continue
        if record.get("caller_id") != CALLER_ID:
            continue
        if "latency_seconds" not in record:
            continue
        target = str(record.get("http.target", ""))
        if not is_qwen_endpoint(target):
            continue
        return stripped
    return None


def wait_for_caller_line(offset: int, timeout: int = WAIT_SECONDS) -> str | None:
    """Poll ``bifrost.log`` for a caller_id line appended after ``offset``.

    Only content written past the pre-dispatch offset counts. Returns the
    matching line, or ``None`` on timeout.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        hit = find_caller_line(_iter_appended_lines(offset))
        if hit is not None:
            return hit
        time.sleep(1)
    return None


def run_gate(timeout: int = WAIT_SECONDS) -> int:
    """Execute the gate. Returns the process exit code."""
    typer.echo("Preconditions:")
    typer.echo(f"  ready file : {READY_FILE}")

    failure = check_preconditions()
    if failure:
        typer.echo(f"  FAIL: {failure}", err=True)
        return EXIT_PRECONDITION

    typer.echo("  OK: preconditions met")

    # Baseline BEFORE dispatch: a long-lived gateway already holds caller_id
    # lines from ordinary worker traffic, so anything already in the file
    # cannot prove that THIS dispatch routed through Bifrost.
    baseline = log_baseline()
    typer.echo(f"INFO: log baseline at byte {baseline}")
    typer.echo(f"INFO: dispatching one Qwen worker via pool route: {DISPATCH_PROMPT!r}")

    if dispatch() != 0:
        return EXIT_FAIL

    if not LOG_OUT.exists():
        typer.echo(f"FAIL: {LOG_OUT} is missing -- no Bifrost activity at all", err=True)
        return EXIT_NO_LOG

    typer.echo(f"INFO: waiting up to {timeout}s for a new caller_id line in {LOG_OUT}")
    hit = wait_for_caller_line(baseline, timeout)
    if hit is None:
        typer.echo(f"FAIL: no caller_id line appended in {timeout}s", err=True)
        return EXIT_FAIL

    typer.echo("PASS: a new caller_id line was appended after dispatch")
    typer.echo(f"  {hit[:200]}")
    return EXIT_PASS


def log_has_caller_line() -> bool:
    """True when any caller_id line exists (diagnostic only, not a gate)."""
    if not LOG_OUT.exists():
        return False
    return find_caller_line(_iter_appended_lines(0)) is not None


__all__ = [
    "CALLER_MARKER",
    "DISPATCH_PROMPT",
    "EXIT_FAIL",
    "EXIT_NO_LOG",
    "EXIT_PASS",
    "EXIT_PRECONDITION",
    "check_preconditions",
    "run_gate",
]
