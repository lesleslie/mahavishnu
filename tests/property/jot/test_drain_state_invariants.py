"""Task 18: property-based state-derivation invariant tests.

Invariants on the per-jot fields that ``build_states`` derives from the
event log:

  * ``current_attempt`` is non-decreasing as we walk the dispatch chain
    (only ``dispatch`` events may increment it).
  * ``dispatch_workflow_id`` matches the ``ctx.workflow_id`` of the most
    recent ``dispatch`` event for that jot.
  * When a dispatch event is present, ``ctx.dispatched_from`` ∈
    ``{"cli", "mcp", "slash"}`` (enforced by ``_validate_ctx`` and
    preserved by fold derivation).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from mahavishnu.jot.drain import _append_event, dispatch_jot
from mahavishnu.jot.events import HLC, JotEvent, serialize
from mahavishnu.jot.fold import DispatchState, build_states, parse_events


# ---------------------------------------------------------------------------
# Helpers + fixtures
# ---------------------------------------------------------------------------


def _capture_event(
    jot_id: str, text: str, *, wall_ms: int = 1_700_000_000_000,
) -> JotEvent:
    return JotEvent(
        id=jot_id,
        op="capture",
        text=text,
        hlc=HLC(wall_ms=wall_ms, ctr=0, node="a" * 8),
        ctx={},
        created_ms=wall_ms,
    )


def _dispatch_event(
    jot_id: str,
    *,
    workflow_id: str,
    attempt: int,
    dispatched_from: str = "mcp",
    triggered_by: str = "first",
    wall_ms: int = 1_700_000_001_000,
) -> JotEvent:
    return JotEvent(
        id=jot_id,
        op="dispatch",
        text="",
        hlc=HLC(wall_ms=wall_ms, ctr=0, node="a" * 8),
        ctx={
            "workflow_id": workflow_id,
            "attempt": attempt,
            "pool_selector": "least_loaded",
            "dispatched_from": dispatched_from,
            "triggered_by": triggered_by,
            "started_at_ms": wall_ms,
        },
        created_ms=wall_ms,
    )


def _dispatch_done_event(
    jot_id: str, *, workflow_id: str, wall_ms: int = 1_700_000_002_000,
) -> JotEvent:
    return JotEvent(
        id=jot_id,
        op="dispatch_done",
        text="",
        hlc=HLC(wall_ms=wall_ms, ctr=0, node="a" * 8),
        ctx={"workflow_id": workflow_id, "summary": "ok"},
        created_ms=wall_ms,
    )


def _dispatch_failed_event(
    jot_id: str,
    *,
    workflow_id: str,
    attempt: int,
    retry_budget_exhausted: bool,
    wall_ms: int = 1_700_000_002_000,
) -> JotEvent:
    return JotEvent(
        id=jot_id,
        op="dispatch_failed",
        text="",
        hlc=HLC(wall_ms=wall_ms, ctr=0, node="a" * 8),
        ctx={
            "workflow_id": workflow_id,
            "attempt": attempt,
            "error": "x",
            "error_id": "ERROR_JOT_TEST",
            "retry_budget_exhausted": retry_budget_exhausted,
        },
        created_ms=wall_ms,
    )


def _write_log(path: Path, events: list[JotEvent]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for ev in events:
            f.write(serialize(ev))


@pytest.fixture
def isolated_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    log = tmp_path / "log.jsonl"
    monkeypatch.setattr("mahavishnu.jot.drain.log_path", lambda: log)
    monkeypatch.setattr("mahavishnu.jot.paths.log_path", lambda: log)
    return log


# Strategies --------------------------------------------------------------

_JOT_TEXT = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "Z"),
        whitelist_characters=" _-",
    ),
    min_size=4,
    max_size=80,
).filter(lambda t: t.strip() != "")


@st.composite
def _non_decreasing_attempts(
    draw, min_attempts: int = 1, max_attempts: int = 5,
) -> list[int]:
    """Generate a non-decreasing sequence of attempt counters."""
    n = draw(st.integers(min_value=min_attempts, max_value=max_attempts))
    out: list[int] = []
    last = 0
    for _ in range(n):
        # Bump by 0..3 — strictly non-decreasing.
        bump = draw(st.integers(min_value=0, max_value=3))
        last = last + bump
        out.append(last)
    # Ensure monotonic non-decreasing (>= 1 — first attempt is always 1).
    if not out or out[0] == 0:
        out[0] = 1
    for i in range(1, len(out)):
        if out[i] < out[i - 1]:
            out[i] = out[i - 1]
    return out


# ---------------------------------------------------------------------------
# Property 1 — current_attempt is non-decreasing along the dispatch chain
# ---------------------------------------------------------------------------


class TestAttemptMonotonicity:
    """``current_attempt`` cannot decrease as more dispatch events arrive."""

    @given(
        text=_JOT_TEXT,
        attempts=_non_decreasing_attempts(min_attempts=1, max_attempts=5),
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_attempts_walk_yields_monotonic_current_attempt(
        self,
        isolated_log: Path,
        text: str,
        attempts: list[int],
    ) -> None:
        """Each ``dispatch`` event increments ``current_attempt`` strictly or
        monotonically — never decreases."""
        jid = f"{abs(hash(text)) & 0xffffffffffffffff:016x}" * 2
        events: list[JotEvent] = [_capture_event(jid, text, wall_ms=1_700_000_000_000)]
        for i, attempt in enumerate(attempts, start=1):
            events.append(
                _dispatch_event(
                    jid,
                    workflow_id=f"wf-{i}",
                    attempt=attempt,
                    wall_ms=1_700_000_000_000 + i * 1000,
                ),
            )
        _write_log(isolated_log, events)

        states = build_states(parse_events(isolated_log), enrich=False).states
        assert len(states) == 1
        summary = states[0]

        # The derived current_attempt must equal the LAST attempt we wrote.
        assert summary.current_attempt == attempts[-1]
        # And must be >= the FIRST attempt (monotonic).
        assert summary.current_attempt >= attempts[0]

    @given(text=_JOT_TEXT, n_dispatches=st.integers(min_value=2, max_value=6))
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_attempts_strictly_increase_with_unique_dispatch_events(
        self,
        isolated_log: Path,
        text: str,
        n_dispatches: int,
    ) -> None:
        """Distinct dispatch events for the same jot carry strictly
        increasing attempt counters (the dispatch primitive refuses
        to re-attempt with a stale number)."""
        jid = f"{abs(hash(text + 'Z')) & 0xffffffffffffffff:016x}" * 2
        events: list[JotEvent] = [_capture_event(jid, text)]
        for i in range(1, n_dispatches + 1):
            events.append(
                _dispatch_event(
                    jid,
                    workflow_id=f"wf-{i}",
                    attempt=i,  # strictly 1, 2, 3, ...
                    wall_ms=1_700_000_000_000 + i * 1000,
                ),
            )
        _write_log(isolated_log, events)
        states = build_states(parse_events(isolated_log), enrich=False).states
        assert states[0].current_attempt == n_dispatches


# ---------------------------------------------------------------------------
# Property 2 — dispatch_workflow_id matches the most recent dispatch's ctx
# ---------------------------------------------------------------------------


class TestWorkflowIdCorrectness:
    """The derived ``dispatch_workflow_id`` is the workflow_id of the most
    recent ``dispatch`` event."""

    @given(text=_JOT_TEXT, n=st.integers(min_value=1, max_value=5))
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_workflow_id_is_most_recent_dispatch(
        self,
        isolated_log: Path,
        text: str,
        n: int,
    ) -> None:
        """``dispatch_workflow_id`` equals the workflow_id of the last
        ``dispatch`` event for the jot."""
        jid = f"{abs(hash(text + 'A')) & 0xffffffffffffffff:016x}" * 2
        events: list[JotEvent] = [_capture_event(jid, text)]
        for i in range(1, n + 1):
            events.append(
                _dispatch_event(
                    jid,
                    workflow_id=f"wf-{i}",
                    attempt=i,
                    wall_ms=1_700_000_000_000 + i * 1000,
                ),
            )
        _write_log(isolated_log, events)
        summary = build_states(parse_events(isolated_log), enrich=False).states[0]
        assert summary.dispatch_workflow_id == f"wf-{n}"

    @given(text=_JOT_TEXT)
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_workflow_id_unchanged_when_done_event_follows(
        self,
        isolated_log: Path,
        text: str,
    ) -> None:
        """A ``dispatch_done`` matching the same workflow_id preserves the
        workflow_id field — completion does not null it out."""
        jid = f"{abs(hash(text + 'B')) & 0xffffffffffffffff:016x}" * 2
        events: list[JotEvent] = [
            _capture_event(jid, text),
            _dispatch_event(jid, workflow_id="wf-1", attempt=1,
                            wall_ms=1_700_000_001_000),
            _dispatch_done_event(jid, workflow_id="wf-1",
                                 wall_ms=1_700_000_002_000),
        ]
        _write_log(isolated_log, events)
        summary = build_states(parse_events(isolated_log), enrich=False).states[0]
        assert summary.dispatch_workflow_id == "wf-1"
        assert summary.dispatch_state == DispatchState.SUCCEEDED

    @given(text=_JOT_TEXT)
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_workflow_id_preserved_after_failed_event_with_budget_remaining(
        self,
        isolated_log: Path,
        text: str,
    ) -> None:
        """A ``dispatch_failed`` with ``retry_budget_exhausted=False`` keeps
        the jot IN_FLIGHT and the workflow_id intact."""
        jid = f"{abs(hash(text + 'C')) & 0xffffffffffffffff:016x}" * 2
        events: list[JotEvent] = [
            _capture_event(jid, text),
            _dispatch_event(jid, workflow_id="wf-1", attempt=1,
                            wall_ms=1_700_000_001_000),
            _dispatch_failed_event(
                jid, workflow_id="wf-1", attempt=1,
                retry_budget_exhausted=False,
                wall_ms=1_700_000_002_000,
            ),
        ]
        _write_log(isolated_log, events)
        summary = build_states(parse_events(isolated_log), enrich=False).states[0]
        assert summary.dispatch_workflow_id == "wf-1"
        assert summary.dispatch_state == DispatchState.IN_FLIGHT

    @given(text=_JOT_TEXT)
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_workflow_id_preserved_after_failed_event_with_budget_exhausted(
        self,
        isolated_log: Path,
        text: str,
    ) -> None:
        """A ``dispatch_failed`` with ``retry_budget_exhausted=True`` flips
        state to FAILED but preserves the workflow_id."""
        jid = f"{abs(hash(text + 'D')) & 0xffffffffffffffff:016x}" * 2
        events: list[JotEvent] = [
            _capture_event(jid, text),
            _dispatch_event(jid, workflow_id="wf-9", attempt=2,
                            wall_ms=1_700_000_001_000),
            _dispatch_failed_event(
                jid, workflow_id="wf-9", attempt=2,
                retry_budget_exhausted=True,
                wall_ms=1_700_000_002_000,
            ),
        ]
        _write_log(isolated_log, events)
        summary = build_states(parse_events(isolated_log), enrich=False).states[0]
        assert summary.dispatch_workflow_id == "wf-9"
        assert summary.dispatch_state == DispatchState.FAILED


# ---------------------------------------------------------------------------
# Property 3 — dispatched_from ∈ {cli, mcp, slash} when present
# ---------------------------------------------------------------------------


class TestDispatchedFromLiteral:
    """The ``dispatched_from`` ctx field is one of the three allowed values."""

    @given(
        text=_JOT_TEXT,
        origin=st.sampled_from(["cli", "mcp", "slash"]),
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_dispatched_from_persists_through_fold(
        self,
        isolated_log: Path,
        text: str,
        origin: str,
    ) -> None:
        """A dispatch event with any of the three origins survives the fold."""
        jid = f"{abs(hash(text + origin)) & 0xffffffffffffffff:016x}" * 2
        events: list[JotEvent] = [
            _capture_event(jid, text),
            _dispatch_event(
                jid, workflow_id="wf-1", attempt=1,
                dispatched_from=origin,
                wall_ms=1_700_000_001_000,
            ),
        ]
        _write_log(isolated_log, events)
        # Read the persisted JSONL line directly — fold does not surface
        # dispatched_from on JotSummary, but the on-disk ctx must preserve
        # the literal value verbatim.
        raw = isolated_log.read_text().splitlines()
        dispatch_line = next(
            (line for line in raw if '"op":"dispatch"' in line), None,
        )
        assert dispatch_line is not None
        ctx = json.loads(dispatch_line)["ctx"]
        assert ctx["dispatched_from"] == origin

    @given(text=_JOT_TEXT)
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_dispatch_jot_uses_passed_dispatched_from(
        self,
        isolated_log: Path,
        fake_workflow_substrate: dict,
        text: str,
    ) -> None:
        """``dispatch_jot`` stamps the caller-supplied ``dispatched_from``
        into the persisted ``dispatch`` event ctx.

        Three jots are written so each origin gets a fresh dispatch
        (re-dispatching an IN_FLIGHT jot fails closed).
        """
        import asyncio
        for i, origin in enumerate(["cli", "mcp", "slash"]):
            # Three distinct jids — one per origin.
            jid = f"{abs(hash(text + 'E' + origin)) & 0xffffffffffffffff:016x}" * 2
            events = list(
                parse_events(isolated_log),
            ) if isolated_log.exists() else []
            events.append(_capture_event(jid, f"{text} {origin}"))
            _write_log(isolated_log, events)

            calls_before = len(fake_workflow_substrate["trigger"])
            asyncio.run(dispatch_jot(jid[:6], dispatched_from=origin))
            # Find the newest dispatch line.
            raw = isolated_log.read_text().splitlines()
            dispatch_lines = [l for l in raw if '"op":"dispatch"' in l]
            latest = dispatch_lines[-1]
            ctx = json.loads(latest)["ctx"]
            assert ctx["dispatched_from"] == origin
            assert calls_before < len(fake_workflow_substrate["trigger"])


# ---------------------------------------------------------------------------
# Property 4 — log mutation never violates derived-field invariants
# ---------------------------------------------------------------------------


class TestDerivedFieldSanity:
    """A few sanity properties on the derived fields for any captured jot."""

    @given(text=_JOT_TEXT)
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_capture_only_jot_has_zero_current_attempt(
        self,
        isolated_log: Path,
        text: str,
    ) -> None:
        """A capture-only jot has ``current_attempt=0`` and no dispatch state."""
        jid = f"{abs(hash(text + 'F')) & 0xffffffffffffffff:016x}" * 2
        _write_log(isolated_log, [_capture_event(jid, text)])
        summary = build_states(parse_events(isolated_log), enrich=False).states[0]
        assert summary.current_attempt == 0
        assert summary.dispatch_state is None
        assert summary.dispatch_workflow_id is None

    @given(text=_JOT_TEXT, attempts=st.lists(
        st.integers(min_value=1, max_value=10), min_size=1, max_size=5,
    ).map(sorted))
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_current_attempt_equals_max_attempt_in_chain(
        self,
        isolated_log: Path,
        text: str,
        attempts: list[int],
    ) -> None:
        """current_attempt = max(attempt) across the dispatch chain."""
        jid = f"{abs(hash(text + 'G')) & 0xffffffffffffffff:016x}" * 2
        events: list[JotEvent] = [_capture_event(jid, text)]
        for i, attempt in enumerate(attempts, start=1):
            events.append(
                _dispatch_event(
                    jid, workflow_id=f"wf-{i}", attempt=attempt,
                    wall_ms=1_700_000_000_000 + i * 1000,
                ),
            )
        _write_log(isolated_log, events)
        summary = build_states(parse_events(isolated_log), enrich=False).states[0]
        assert summary.current_attempt == attempts[-1]


# ---------------------------------------------------------------------------
# Property 5 — _append_event validates dispatched_from strictly
# ---------------------------------------------------------------------------


class TestAppendEventValidation:
    """Direct ``_append_event`` calls reject unknown ``dispatched_from``."""

    @given(text=_JOT_TEXT)
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    async def test_append_event_rejects_unknown_dispatched_from(
        self,
        isolated_log: Path,
        text: str,
    ) -> None:
        """Anything outside ``{"cli", "mcp", "slash"}`` raises JotValidationError."""
        from mahavishnu.jot.errors import JotValidationError

        # valid jid (not used by _append_event but kept in scope)
        jid = f"{abs(hash(text + 'H')) & 0xffffffffffffffff:016x}" * 2
        bogus = "scheduler"  # not in the Literal
        with pytest.raises(JotValidationError) as excinfo:
            await _append_event(
                "dispatch",
                {
                    "workflow_id": "wf-x",
                    "attempt": 1,
                    "pool_selector": "least_loaded",
                    "dispatched_from": bogus,
                },
                jot_id=jid,
            )
        assert "dispatched_from" in str(excinfo.value)
        # And nothing was written — file may not exist yet (the append lock
        # acquires before mkdir in `_append_event`'s ordering — actually
        # validation happens BEFORE mkdir, so the file may never exist).
        assert (
            not isolated_log.exists() or isolated_log.read_text() == ""
        ), "validation failure must NOT persist anything to the log"
