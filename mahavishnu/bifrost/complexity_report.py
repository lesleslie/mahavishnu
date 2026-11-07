"""Cost and hazard accounting for Bifrost's complexity router.

Why this file exists
--------------------
The complexity router classifies every request as ``SIMPLE``, ``MEDIUM``, or
``COMPLEX`` and publishes the tier to the CEL engine, where a routing rule
can act on it. Two consequences follow, and neither is visible from the
gateway's own health output:

1. **It costs tokens.** A classification that cannot be served from the
   session tier store is a decision-model call, and the decision model's
   input scales with the turn being classified -- roughly 3,500 input
   tokens per call on the Claude Code path, measured 2026-11-07.

2. **Acting on the tier is not guaranteed.** Bifrost runs a second routing
   engine, ``session-affinity``, *after* the routing rules. It binds
   ``(session id, requested model)`` to the provider and model the session
   was first served, and it wins over a rule's proposed model. So a
   ``SIMPLE`` tier can be paid for and not acted on, and a ``MEDIUM`` or
   ``COMPLEX`` tier can be served by the cheaper model.

The module measures both from the gateway's own request log, so the
decision to keep the router ("keep it, price it as observability, watch
the escalation hazard") is watched rather than hoped for.

How the outcomes are told apart
-------------------------------
Bifrost's ``session-affinity`` engine writes one line per request that
carries the requested model, the session's bound model, and what the
routing rules proposed::

    [session-affinity] Session stays on minimax-anthropic/MiniMax-M3.1-Flash
        for MiniMax-M3; routing proposed minimax-anthropic/MiniMax-M3

Comparing that line against the tier and the model that actually served
the request gives one of three outcomes per request:

``downgraded``
    The tier was ``SIMPLE``, the rules proposed the cheap model, and the
    cheap model served it. **The rule's intent was carried out.**

``tier_overridden``
    The tier was ``MEDIUM`` or ``COMPLEX`` -- the router's instruction is
    to keep the caller's model -- and the cheap model served it anyway.
    **The tier's instruction was overruled.** This is the risk.

``lost_saving``
    The tier was ``SIMPLE``, the rules proposed the cheap model, and the
    session's bound model served it instead. **The classification was paid
    for and nothing was bought.** This is the normal state for a session
    that was bound before the router went live.

The per-request saving is *not* measured. It would need the counterfactual
(M3's output on a request M3.1-Flash actually served), and the gateway
does not record one. What the report gives is the volume that moved, which
is the traffic the saving accrues over.

Why the two cheap-model outcomes are the same thing
---------------------------------------------------
The affinity binding is ``(session id, requested model)`` and it persists
for the session. So a single ``SIMPLE`` turn does not discount one turn --
it **rebinds the whole session's model class** to the cheap model, and
every later request in that class is served by it, whatever the tier says.
Measured on 2026-11-07: one session's first ``SIMPLE`` turn was followed
by 266 ``MEDIUM`` requests that asked for the caller's model and were
served the cheap one. The rule's per-tier policy is therefore not what
decides the model; the session's first binding is.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import re
import sqlite3
from typing import TYPE_CHECKING

from oneiric.core.logging import get_logger

from .paths import LOGS_DB

if TYPE_CHECKING:
    from pathlib import Path

logger = get_logger(__name__)

# Implements: REQ-BIFROST-046, REQ-BIFROST-047

#: The model the ``SIMPLE`` tier routes to.
CHEAP_MODEL = "MiniMax-M3.1-Flash"

#: Tiers whose instruction is "keep the caller's model".
HEAVY_TIERS = ("MEDIUM", "COMPLEX")

#: The ``session-affinity`` engine's log line, in the three shapes it takes.
#:
#: The engine reports the session's bound model, the model the request
#: asked for, and -- when the rules proposed something different -- what
#: they proposed. The third variant says "which routing also proposed"
#: instead of naming a proposal.
_AFFINITY_RE = re.compile(
    r"Session stays on (?P<bound>\S+) for (?P<requested>[^;,]+)"
    r"(?:[;,]\s*(?:routing proposed (?P<proposed>\S+)"
    r"|which routing also proposed))?"
)

#: The tier rows, with everything the classification needs.
_ROWS_SQL = """
    SELECT timestamp, session_id, model, complexity_tier, complexity_mechanism,
           routing_rule_id, routing_engine_logs, total_tokens, completion_tokens
      FROM logs
     WHERE timestamp >= datetime('now', ?)
       AND complexity_tier IS NOT NULL
       AND complexity_tier != ''
"""

#: The decision-model calls, summed over every call in the row's metadata.
#:
#: ``json_each`` walks the ``calls`` array so a request that made more
#: than one provider call is counted once per call rather than once per
#: row. The ``json_valid`` guard is not decoration: some rows carry a
#: ``routing_metadata`` that is not well-formed JSON, and ``json_each``
#: raises on those rather than skipping them.
_COST_SQL = """
    SELECT count(*),
           coalesce(sum(json_extract(value, '$.input_tokens')), 0),
           coalesce(sum(json_extract(value, '$.output_tokens')), 0)
      FROM (SELECT routing_metadata
              FROM logs
             WHERE timestamp >= datetime('now', ?)
               AND routing_metadata IS NOT NULL
               AND json_valid(routing_metadata)) AS valid,
           json_each(valid.routing_metadata, '$.calls')
     WHERE json_extract(value, '$.request_type') = 'decisions'
"""


@dataclass(frozen=True)
class ComplexityReport:
    """One window of complexity-router activity, priced.

    Every counter is a count of *requests* unless its name says otherwise.
    """

    #: The window the report covers, in hours back from now.
    window_hours: float

    #: Requests that carried a tier.
    tiered_requests: int = 0

    #: Tier -> number of requests.
    tiers: dict[str, int] = field(default_factory=dict)

    #: Classification mechanism -> number of requests.
    mechanisms: dict[str, int] = field(default_factory=dict)

    #: Decision-model calls made in the window.
    decision_calls: int = 0

    #: Input tokens spent on decision-model calls.
    classifier_input_tokens: int = 0

    #: Output tokens spent on decision-model calls.
    classifier_output_tokens: int = 0

    #: ``SIMPLE`` tiers the cheap model actually served -- saving realised.
    downgraded: int = 0

    #: ``SIMPLE`` tiers the rules proposed but affinity overruled.
    lost_savings: int = 0

    #: ``MEDIUM``/``COMPLEX`` tiers the cheap model served anyway -- the
    #: tier's instruction overruled.
    tier_overridden: int = 0

    #: Requests served by the cheap model, in total.
    cheap_model_requests: int = 0

    #: Total tokens on the requests served by the cheap model.
    cheap_model_total_tokens: int = 0

    #: Output tokens on the requests served by the cheap model -- where a
    #: cheaper model actually saves.
    cheap_model_completion_tokens: int = 0

    #: Tiered requests whose affinity line could not be read.
    unclassified: int = 0

    #: Distinct sessions seen in the window.
    sessions: int = 0


@dataclass(frozen=True)
class _Row:
    """One tiered request, reduced to what the classification needs."""

    model: str
    tier: str
    mechanism: str
    rule: str
    requested_model: str | None
    proposed_model: str | None


def _model_of(provider_model: str) -> str:
    """Return the model part of a ``provider/model`` pair."""
    return provider_model.rsplit("/", 1)[-1].strip()


def _parse_affinity(engine_logs: str | None) -> tuple[str | None, str | None]:
    """Return ``(requested_model, proposed_model)`` from an affinity line.

    Both are ``None`` when the line is absent or unparsable -- which is a
    real state, because the engine only logs when it ran. The caller
    counts those rows as unclassified rather than guessing.
    """
    if not engine_logs:
        return None, None
    match = _AFFINITY_RE.search(engine_logs)
    if match is None:
        return None, None
    proposed = match.group("proposed")
    return (
        _model_of(match.group("requested")),
        _model_of(proposed) if proposed else None,
    )


def _classify(row: _Row) -> str:
    """Return the outcome name for one tiered request.

    One of ``downgraded``, ``lost_saving``, ``tier_overridden``, or
    ``normal``.
    """
    if row.requested_model is None:
        return "unclassified"
    if row.tier == "SIMPLE":
        if row.model == CHEAP_MODEL and row.requested_model != CHEAP_MODEL:
            return "downgraded"
        if row.proposed_model == CHEAP_MODEL and row.model != CHEAP_MODEL:
            return "lost_saving"
        return "normal"
    if (
        row.tier in HEAVY_TIERS
        and row.model == CHEAP_MODEL
        and row.requested_model != CHEAP_MODEL
    ):
        return "tier_overridden"
    return "normal"


def _connect(db_path: Path) -> sqlite3.Connection:
    """Open the log store read-only.

    The gateway holds it open in WAL mode, and the report must never
    write to it.
    """
    return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=10)


def collect_report(
    window_hours: float = 24.0, *, db_path: Path | None = None
) -> ComplexityReport:
    """Price the complexity router over a window.

    Args:
        window_hours: How far back to look. Defaults to 24 hours.
        db_path: The log store to read. Defaults to the gateway's own
            ``logs.db``, resolved at call time so a redirect is honoured.

    Returns:
        The report. Every counter is zero when the window has no traffic.

    Raises:
        FileNotFoundError: The log store does not exist.
    """
    # req: REQ-BIFROST-046
    target = db_path if db_path is not None else LOGS_DB
    if not target.exists():
        raise FileNotFoundError(f"Bifrost log store missing: {target}")

    modifier = f"-{window_hours} hours"
    connection = _connect(target)
    try:
        # The cost query runs first: it is the one that can raise on a
        # malformed row, and it must not do so with a thousand rows held
        # in scope.
        cost = connection.execute(_COST_SQL, (modifier,)).fetchone()
        rows = connection.execute(_ROWS_SQL, (modifier,)).fetchall()
    except sqlite3.Error:
        logger.exception("complexity report query failed", db_path=str(target))
        raise
    finally:
        connection.close()

    tiers: dict[str, int] = {}
    mechanisms: dict[str, int] = {}
    sessions: set[str] = set()
    outcomes = {"downgraded": 0, "lost_saving": 0, "tier_overridden": 0}
    unclassified = 0
    cheap_requests = 0
    cheap_total_tokens = 0
    cheap_completion_tokens = 0

    for (
        _timestamp,
        session_id,
        model,
        tier,
        mechanism,
        rule,
        engine_logs,
        total_tokens,
        completion_tokens,
    ) in rows:
        tiers[tier] = tiers.get(tier, 0) + 1
        mechanisms[mechanism or "(none)"] = mechanisms.get(mechanism or "(none)", 0) + 1
        if session_id:
            sessions.add(session_id)
        requested, proposed = _parse_affinity(engine_logs)
        outcome = _classify(
            _Row(
                model=model or "",
                tier=tier,
                mechanism=mechanism or "",
                rule=rule or "",
                requested_model=requested,
                proposed_model=proposed,
            )
        )
        if outcome in outcomes:
            outcomes[outcome] += 1
        elif outcome == "unclassified":
            unclassified += 1
        if outcome in ("downgraded", "tier_overridden"):
            cheap_requests += 1
            cheap_total_tokens += int(total_tokens or 0)
            cheap_completion_tokens += int(completion_tokens or 0)

    decision_calls = int(cost[0]) if cost else 0
    input_tokens = int(cost[1]) if cost else 0
    output_tokens = int(cost[2]) if cost else 0

    return ComplexityReport(
        window_hours=window_hours,
        tiered_requests=len(rows),
        tiers=dict(sorted(tiers.items())),
        mechanisms=dict(sorted(mechanisms.items())),
        decision_calls=decision_calls,
        classifier_input_tokens=input_tokens,
        classifier_output_tokens=output_tokens,
        downgraded=outcomes["downgraded"],
        lost_savings=outcomes["lost_saving"],
        tier_overridden=outcomes["tier_overridden"],
        cheap_model_requests=cheap_requests,
        cheap_model_total_tokens=cheap_total_tokens,
        cheap_model_completion_tokens=cheap_completion_tokens,
        unclassified=unclassified,
        sessions=len(sessions),
    )


def report_as_dict(report: ComplexityReport) -> dict[str, object]:
    """Return the report as a plain JSON-serialisable mapping."""
    return {
        "window_hours": report.window_hours,
        "tiered_requests": report.tiered_requests,
        "tiers": report.tiers,
        "mechanisms": report.mechanisms,
        "decision_calls": report.decision_calls,
        "classifier_input_tokens": report.classifier_input_tokens,
        "classifier_output_tokens": report.classifier_output_tokens,
        "downgraded": report.downgraded,
        "lost_savings": report.lost_savings,
        "tier_overridden": report.tier_overridden,
        "cheap_model_requests": report.cheap_model_requests,
        "cheap_model_total_tokens": report.cheap_model_total_tokens,
        "cheap_model_completion_tokens": report.cheap_model_completion_tokens,
        "unclassified": report.unclassified,
        "sessions": report.sessions,
    }


def render_report(report: ComplexityReport) -> str:
    """Render the report as the operator-facing text block."""
    total_tokens = report.classifier_input_tokens + report.classifier_output_tokens
    reuse = ""
    if report.tiered_requests:
        reused = report.mechanisms.get("session", 0)
        share = 100.0 * reused / report.tiered_requests
        reuse = f"{reused} reused a stored tier ({share:.1f}%)"

    classifier_line = (
        f"  classifier tokens : {report.classifier_input_tokens} in + "
        f"{report.classifier_output_tokens} out = {total_tokens}"
    )
    cheap_line = (
        f"  cheap model       : {report.cheap_model_requests} requests, "
        f"{report.cheap_model_total_tokens} total tokens, "
        f"{report.cheap_model_completion_tokens} output tokens"
    )
    overridden_line = (
        f"    tier said {'/'.join(HEAVY_TIERS):<13}: {report.tier_overridden}   "
        f"(the tier's instruction was overruled)"
    )
    lost_line = (
        f"  lost savings      : {report.lost_savings}   "
        f"(SIMPLE tier paid for, the session's binding won)"
    )
    ledger = (
        f"  ledger            : classifier spent {total_tokens} tokens; the "
        f"cheap model served {report.cheap_model_completion_tokens} output tokens."
    )

    lines = [
        f"complexity router -- last {report.window_hours:g}h",
        "",
        f"  tiered requests   : {report.tiered_requests} over {report.sessions} sessions",
        f"  tiers             : {report.tiers or '{}'}",
        f"  classification    : {reuse or report.mechanisms}",
        "",
        f"  decision calls    : {report.decision_calls}",
        classifier_line,
        "",
        cheap_line,
        f"    tier said SIMPLE        : {report.downgraded}   (the rule's intent)",
        overridden_line,
        lost_line,
        "",
        ledger,
        "                      Context tokens do not change with the model, so",
        "                      the token-side lever is output length alone --",
        "                      and the per-request saving is not attributable",
        "                      from what the gateway records.",
    ]
    if report.unclassified:
        lines.append(
            f"  unclassified      : {report.unclassified}   (no session-affinity line to read)"
        )
    return "\n".join(lines)


def main(window_hours: float = 24.0, *, db_path: Path | None = None) -> int:
    """Print the report. Returns a process exit code."""
    # req: REQ-BIFROST-048
    try:
        report = collect_report(window_hours, db_path=db_path)
    except FileNotFoundError as exc:
        print(str(exc))
        return 1
    print(render_report(report))
    if report.tier_overridden:
        print(
            "\n  the session binding overrode the tier: those turns asked for "
            "the caller's model and were served the cheaper one."
        )
    return 0


def report_json(window_hours: float = 24.0, *, db_path: Path | None = None) -> str:
    """Return the report as a JSON string."""
    report = collect_report(window_hours, db_path=db_path)
    return json.dumps(report_as_dict(report), indent=2, sort_keys=True)


__all__ = [
    "CHEAP_MODEL",
    "HEAVY_TIERS",
    "ComplexityReport",
    "collect_report",
    "main",
    "render_report",
    "report_as_dict",
    "report_json",
]
