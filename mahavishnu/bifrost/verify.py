"""Operator verification gate for the Qwen-CLI Bifrost route.

req: REQ-BIFROST-034

Reads Bifrost's **structured request log** (``~/.config/bifrost/logs.db``) to
prove that one dispatched Qwen worker actually routed through the gateway.

Preconditions (any missing aborts with ``EXIT_PRECONDITION``):

1. Bifrost gateway running -- the ready file must exist.
2. A real ``qwen`` binary on PATH (probed with ``qwen --version``).
3. The mahavishnu pool router reachable (``mahavishnu pool health``).

Pass criterion: a row appears in ``logs`` with ``virtual_key_name`` set to our
key, ``status = 'success'``, and a model served only by the Qwen route.

Exit codes (unchanged from the shell original, so operator runbooks and any
wrapper scripts keep working):

==== ==========================================
Code Meaning
==== ==========================================
0    gate passed -- a Qwen-route row was recorded after dispatch
1    gate failed -- no such row within 30s
2    a precondition was not met
3    the log store is missing
==== ==========================================

Why this reads SQLite rather than the stdout log
-------------------------------------------------

The previous implementation tail-grepped ``bifrost.log`` for a JSON line
carrying ``caller_id`` and ``latency_seconds``. **Neither field is ever
written there.** At ``info`` level the stdout log emits only HTTP access
lines::

    http.method http.target http.status_code http.request_duration_ms
    http.remote_addr http.user_agent request_id trace_id

so the gate could never pass regardless of routing health -- and because the
skip is silent, that failure looked identical to "traffic did not arrive".
Bifrost's own struct tag ``json:"caller_id,omitempty"`` is a *capability*,
not evidence: the ``metadata`` column that would carry it is empty in every
recorded row.

The structured store has the real equivalents, under different names:

===================  ==========================
stdout log (wrong)   ``logs`` table (right)
===================  ==========================
``caller_id``        ``virtual_key_name``
``latency_seconds``  ``latency`` (milliseconds)
``http.target``      ``model`` + ``provider``
===================  ==========================

``virtual_key_name`` identifies the caller exactly as ``caller_id`` was meant
to, and it is populated on every row.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import time

import typer

from .paths import LOGS_DB, READY_FILE

#: Operator-facing name of the virtual key the harnesses authenticate with.
#: Matches ``_BIFROST_VKEY_NAME`` in ``examples/_bifrost_setup.py``, which
#: resolves the same key by name.
VIRTUAL_KEY_NAME = "bodai-pi-pool"

#: Fallback expected model when Qwen Code's settings cannot be read.
#:
#: The gate used to hardcode ``qwen3-8b-q4_k_m``, the local llama-server
#: model. That is not what Qwen Code is actually configured to send: it
#: resolves ``model.name`` against ``modelProviders`` and reaches MiniMax
#: through the ``anthropic`` provider, so the rows it produces carry
#: ``MiniMax-M3``. Pinning a model nothing requests made the gate
#: unsatisfiable for the same reason the old ``http.target`` check was.
QWEN_ROUTE_MODEL = "MiniMax-M3"

#: Qwen Code's settings file -- the same one ``bifrost qwen-url`` rewrites.
QWEN_SETTINGS_PATH = Path.home() / ".qwen" / "settings.json"

DISPATCH_PROMPT = "Reply with a single word: bifrost-routed"

EXIT_PASS = 0
EXIT_FAIL = 1
EXIT_PRECONDITION = 2
EXIT_NO_LOG = 3

#: Operator-friendly headroom for slow Qwen CLI first-token latency.
WAIT_SECONDS = 30

#: The Qwen CLI pays MCP-server startup on every one-shot run; a bare prompt
#: takes ~10s but a cold MCP layer pushes well past that.
DISPATCH_TIMEOUT_SECONDS = 180


def expected_qwen_model() -> str:
    """Return the model Qwen Code will actually request.

    Read from ``~/.qwen/settings.json`` (``model.name``) rather than pinned,
    so the gate follows the harness when the operator repoints it. ``model.name``
    is the resolved selection -- Qwen matches it against ``modelProviders``
    before dispatch, which is why the value can name a cloud model rather than
    the local llama-server model the gate used to hardcode.
    """
    try:
        loaded = json.loads(QWEN_SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return QWEN_ROUTE_MODEL
    if not isinstance(loaded, dict):
        return QWEN_ROUTE_MODEL
    model = loaded.get("model")
    if not isinstance(model, dict):
        return QWEN_ROUTE_MODEL
    name = model.get("name")
    return name if isinstance(name, str) and name else QWEN_ROUTE_MODEL


@dataclass(frozen=True)
class RoutedRequest:
    """One row from Bifrost's ``logs`` table, narrowed to what the gate needs."""

    rowid: int
    timestamp: str
    provider: str
    model: str
    status: str
    latency: float | None
    user_agent: str

    def describe(self) -> str:
        """One-line human summary for the operator."""
        agent = self.user_agent or "(no user-agent)"
        return (
            f"{self.timestamp} provider={self.provider} model={self.model} "
            f"status={self.status} latency={self.latency}ms via {agent}"
        )


def _connect() -> sqlite3.Connection | None:
    """Open the log store read-only, or ``None`` if it isn't there.

    ``mode=ro`` matters: the gateway holds this database open in WAL mode and
    the gate must never take a write lock on it.
    """
    if not LOGS_DB.exists():
        return None
    return sqlite3.connect(f"file:{LOGS_DB}?mode=ro", uri=True, timeout=10)


def _query(sql: str, params: tuple[object, ...] = ()) -> list[tuple[object, ...]]:
    """Run a read-only query, treating any SQLite failure as "no rows"."""
    connection = _connect()
    if connection is None:
        return []
    try:
        return connection.execute(sql, params).fetchall()
    except sqlite3.Error:
        return []
    finally:
        connection.close()


def _as_int(value: object, default: int = 0) -> int:
    """Narrow a SQLite scalar to ``int``.

    SQLite is dynamically typed and hands back whatever storage class a column
    happened to use, so this narrows on the runtime type rather than asserting
    one. A ``rowid`` that is not an integer would mean a different table shape
    entirely, which is exactly when the gate should degrade to "no evidence"
    rather than raise.
    """
    if isinstance(value, bool):
        return default
    return value if isinstance(value, int) else default


def _as_float(value: object) -> float | None:
    """Narrow a SQLite scalar to ``float``, or ``None`` when it is NULL."""
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def log_baseline() -> int:
    """Highest ``rowid`` currently in the log store.

    Everything at or below this is pre-existing history and is **not**
    evidence that the gate's own dispatch worked. A long-lived gateway
    accumulates rows from ordinary Claude Code and worker traffic, so a gate
    that scans the whole table passes instantly without proving anything.

    ``rowid`` is used rather than ``inc_number``: ``inc_number`` exists as a
    column but is NULL on every recorded row (it is a ClickHouse-origin
    autoincrement that the SQLite writer never populates), so it cannot serve
    as a watermark. SQLite's implicit ``rowid`` is monotonic for appends,
    which is exactly the property a baseline needs.
    """
    rows = _query("SELECT coalesce(max(rowid), 0) FROM logs")
    if not rows:
        return 0
    return _as_int(rows[0][0])


def find_routed_rows(baseline: int, virtual_key_name: str = VIRTUAL_KEY_NAME) -> list[RoutedRequest]:
    """Successful requests attributed to ``virtual_key_name`` after ``baseline``.

    Ordered by ``rowid`` so the first match is the oldest qualifying request,
    which makes the gate's diagnostic stable rather than dependent on which
    poll iteration happened to win the race.
    """
    rows = _query(
        """
        SELECT rowid, timestamp, provider, model, status, latency, user_agent
          FROM logs
         WHERE rowid > ?
           AND virtual_key_name = ?
           AND status = 'success'
      ORDER BY rowid
        """,
        (baseline, virtual_key_name),
    )
    return [
        RoutedRequest(
            rowid=_as_int(rowid),
            timestamp=str(timestamp or ""),
            provider=str(provider or ""),
            model=str(model or ""),
            status=str(status or ""),
            latency=_as_float(latency),
            user_agent=str(user_agent or ""),
        )
        for rowid, timestamp, provider, model, status, latency, user_agent in rows
    ]


def expected_qwen_user_agent() -> str | None:
    """Return the Bifrost user-agent prefix identifying the Qwen CLI.

    Model alone does **not** identify the Qwen route. Claude Code requests the
    same ``MiniMax-M3`` on the same virtual key continuously, so a
    model-only match admits this operator's own CC traffic: the gate observed
    ``PASS: row 2577`` whose user agent was ``claude-cli/2.1.309 ... sdk-py``,
    not Qwen at all.

    The Qwen CLI stamps Bifrost's Anthropic-compatible user agent with its own
    version -- ``claude-cli/0.23.3 (external, cli)`` for ``qwen 0.23.3`` --
    while Claude Code stamps ``claude-cli/2.1.309``. So the version of the
    binary the gate just invoked is the discriminator, read live rather than
    pinned. Returns ``None`` when the version cannot be read, which makes
    matching fail closed.
    """
    probe = _run(["qwen", "--version"], timeout=30)
    if probe.returncode != 0:
        return None
    version = (probe.stdout or "").strip().splitlines()[:1]
    if not version or not version[0].strip():
        return None
    return f"claude-cli/{version[0].strip()}"


def is_qwen_route(
    request: RoutedRequest,
    model: str = QWEN_ROUTE_MODEL,
    user_agent: str | None = None,
) -> bool:
    """True only for a row this gate's own dispatch could have produced.

    ``model`` follows ``~/.qwen/settings.json`` (the module constant is the
    fallback), and ``user_agent`` must additionally match the Qwen CLI's
    stamped version. ``user_agent=None`` means "unresolved" and fails closed:
    guessing is what let the gate pass on Claude Code's traffic.
    """
    if request.model != model:
        return False
    if user_agent is None:
        return False
    return request.user_agent.startswith(user_agent)


def find_qwen_row(
    baseline: int,
    virtual_key_name: str = VIRTUAL_KEY_NAME,
    model: str = QWEN_ROUTE_MODEL,
    user_agent: str | None = None,
) -> RoutedRequest | None:
    """Return the first post-baseline row proving the Qwen dispatch routed."""
    for request in find_routed_rows(baseline, virtual_key_name):
        if is_qwen_route(request, model, user_agent):
            return request
    return None


def wait_for_qwen_row(
    baseline: int,
    timeout: int = WAIT_SECONDS,
    model: str = QWEN_ROUTE_MODEL,
    user_agent: str | None = None,
) -> RoutedRequest | None:
    """Poll the log store for a Qwen-route row recorded after ``baseline``."""
    deadline = time.monotonic() + timeout
    while True:
        hit = find_qwen_row(baseline, model=model, user_agent=user_agent)
        if hit is not None:
            return hit
        if time.monotonic() >= deadline:
            return None
        time.sleep(1)


def _run(cmd: list[str], timeout: int = 60) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError):
        return subprocess.CompletedProcess(cmd, 127, "", "")


def check_preconditions() -> str | None:
    """Return a human-readable failure reason, or ``None`` if all are met."""
    if not READY_FILE.exists():
        return f"Bifrost not ready: {READY_FILE} is missing"

    if not LOGS_DB.exists():
        return f"Bifrost log store missing: {LOGS_DB} does not exist"

    if shutil.which("qwen") is None:
        return "Qwen CLI not on PATH"

    probe = _run(["qwen", "--version"], timeout=15)
    if probe.returncode != 0:
        return f"'qwen --version' failed (exit {probe.returncode})"

    health = _run(["mahavishnu", "pool", "health"], timeout=60)
    if health.returncode != 0:
        # Exit status alone is the signal. The shell original additionally
        # grepped stdout for the literal string "mahavishnu pool health",
        # which that command never prints -- it emits "Pool Manager Health:
        # healthy". The check therefore failed against a perfectly healthy
        # router and blocked every gate run.
        return f"'mahavishnu pool health' exited {health.returncode}"

    return None


def dispatch() -> int:
    """Run the Qwen CLI once so Bifrost records a row.

    ``mahavishnu workers execute`` is **not** used here, deliberately.
    Two independent reasons, both verified rather than assumed:

    1. It only planned. The command resolved a capability DAG and returned
       with "Per-engine dispatch lands in Phase 4" -- no worker was spawned,
       so no Bifrost row could ever appear and the gate then polled out.
    2. Wiring the missing dispatch in did not help. ``WorkerOrchestratorAdapter``
       really does spawn workers, but they land on ``ShellWorker``, whose
       ``execute`` is a documented no-op returning ``COMPLETED``
       (``mahavishnu/workers/shell_backend.py``). The run went green in
       0.187s with empty output and logged nothing -- a false pass that looks
       exactly like success.

    ``shell_backend`` says the intended contract outright: *"the Bifrost Qwen
    gate's verification path runs the CLI directly rather than through this
    method."* That is what this does. The ``qwen`` CLI reads its endpoint and
    its ``x-bf-vk`` header from ``~/.qwen/settings.json``, which
    ``bifrost qwen-url`` maintains -- so invoking the CLI is itself the test of
    that toggle.

    Returns the subprocess exit status. A non-zero status must fail the gate --
    otherwise the gate would go on to poll for a row that can never arrive,
    which is indistinguishable from the routing being broken.
    """
    result = _run(["qwen", DISPATCH_PROMPT], timeout=DISPATCH_TIMEOUT_SECONDS)
    for line in (result.stdout or "").splitlines()[:5]:
        typer.echo(f"  {line}")
    if result.returncode != 0:
        typer.echo(f"FAIL: dispatch exited {result.returncode}", err=True)
        for line in (result.stderr or "").splitlines()[:5]:
            typer.echo(f"  {line}", err=True)
    return result.returncode


def run_gate(timeout: int = WAIT_SECONDS) -> int:
    """Execute the gate. Returns the process exit code."""
    typer.echo("Preconditions:")
    typer.echo(f"  ready file  : {READY_FILE}")
    typer.echo(f"  log store   : {LOGS_DB}")

    failure = check_preconditions()
    if failure:
        typer.echo(f"  FAIL: {failure}", err=True)
        return EXIT_PRECONDITION

    typer.echo("  OK: preconditions met")

    # Baseline BEFORE dispatch: a long-lived gateway already holds rows from
    # ordinary Claude Code and worker traffic, so anything already recorded
    # cannot prove that THIS dispatch routed through Bifrost.
    baseline = log_baseline()
    typer.echo(f"INFO: log baseline at rowid {baseline}")
    expected_model = expected_qwen_model()
    expected_agent = expected_qwen_user_agent()
    if expected_agent is None:
        typer.echo("FAIL: could not read 'qwen --version'; refusing to guess a user agent", err=True)
        return EXIT_PRECONDITION
    typer.echo(f"INFO: expecting rows from {expected_model!r} via {expected_agent!r}")

    if dispatch() != 0:
        return EXIT_FAIL

    if not LOGS_DB.exists():
        typer.echo(f"FAIL: {LOGS_DB} is missing -- no Bifrost activity at all", err=True)
        return EXIT_NO_LOG

    typer.echo(
        f"INFO: waiting up to {timeout}s for a {expected_model} row "
        f"on virtual key {VIRTUAL_KEY_NAME!r}"
    )
    hit = wait_for_qwen_row(baseline, timeout, model=expected_model, user_agent=expected_agent)
    if hit is None:
        typer.echo(f"FAIL: no Qwen-route row appeared within {timeout}s", err=True)
        return EXIT_FAIL

    typer.echo(f"PASS: row {hit.rowid} recorded after dispatch")
    typer.echo(f"  {hit.describe()}")
    return EXIT_PASS


__all__ = [
    "DISPATCH_PROMPT",
    "EXIT_FAIL",
    "EXIT_NO_LOG",
    "EXIT_PASS",
    "EXIT_PRECONDITION",
    "QWEN_ROUTE_MODEL",
    "VIRTUAL_KEY_NAME",
    "RoutedRequest",
    "check_preconditions",
    "expected_qwen_model",
    "expected_qwen_user_agent",
    "find_qwen_row",
    "find_routed_rows",
    "is_qwen_route",
    "log_baseline",
    "run_gate",
    "wait_for_qwen_row",
]