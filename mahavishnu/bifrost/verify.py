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

#: The model the Qwen route serves. ``config.json`` declares exactly one model
#: for the ``llama-server`` provider, so a row carrying it can only have come
#: from the Qwen route.
#:
#: This is a *semantic* discriminator and replaces the old syntactic
#: ``http.target == "/v1/chat/completions"`` check. Claude Code only ever
#: requests ``MiniMax-M3*``, so no amount of concurrent CC traffic can collide
#: with it -- and unlike a path comparison it has no normalisation or
#: traversal surface to get wrong.
QWEN_ROUTE_MODEL = "qwen3-8b-q4_k_m"

DISPATCH_PROMPT = "Reply with a single word: bifrost-routed"

EXIT_PASS = 0
EXIT_FAIL = 1
EXIT_PRECONDITION = 2
EXIT_NO_LOG = 3

#: Operator-friendly headroom for slow Qwen CLI first-token latency.
WAIT_SECONDS = 30


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


def is_qwen_route(request: RoutedRequest) -> bool:
    """True only for a row served by the Qwen route's provider."""
    return request.model == QWEN_ROUTE_MODEL


def find_qwen_row(
    baseline: int, virtual_key_name: str = VIRTUAL_KEY_NAME
) -> RoutedRequest | None:
    """Return the first post-baseline row proving the Qwen dispatch routed."""
    for request in find_routed_rows(baseline, virtual_key_name):
        if is_qwen_route(request):
            return request
    return None


def wait_for_qwen_row(baseline: int, timeout: int = WAIT_SECONDS) -> RoutedRequest | None:
    """Poll the log store for a Qwen-route row recorded after ``baseline``."""
    deadline = time.monotonic() + timeout
    while True:
        hit = find_qwen_row(baseline)
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
    """Drive one Qwen worker so Bifrost records a row.

    ``mahavishnu workers execute`` is the executor; ``mahavishnu pool route``
    is only a planner -- it emits a capability DAG and has no ``--worker-type``
    option at all. Passing the latter here made every gate run fail with a
    Typer usage error (exit 2) before dispatching anything.

    Returns the subprocess exit status. A non-zero status must fail the gate --
    otherwise the gate would go on to poll for a row that can never arrive,
    which is indistinguishable from the routing being broken.
    """
    result = _run(
        [
            "mahavishnu",
            "workers",
            "execute",
            "--prompt",
            DISPATCH_PROMPT,
            "--type",
            "terminal-qwen",
            "--count",
            "1",
            "--timeout",
            "60",
        ],
        timeout=120,
    )
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
    typer.echo(f"INFO: dispatching one Qwen worker via pool route: {DISPATCH_PROMPT!r}")

    if dispatch() != 0:
        return EXIT_FAIL

    if not LOGS_DB.exists():
        typer.echo(f"FAIL: {LOGS_DB} is missing -- no Bifrost activity at all", err=True)
        return EXIT_NO_LOG

    typer.echo(
        f"INFO: waiting up to {timeout}s for a {QWEN_ROUTE_MODEL} row "
        f"on virtual key {VIRTUAL_KEY_NAME!r}"
    )
    hit = wait_for_qwen_row(baseline, timeout)
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
    "find_qwen_row",
    "find_routed_rows",
    "is_qwen_route",
    "log_baseline",
    "run_gate",
    "wait_for_qwen_row",
]