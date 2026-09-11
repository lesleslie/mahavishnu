"""Task 18: property-based idempotency tests for ``mahavishnu.jot.drain``.

Invariants:
  * Re-running ``drain_plan`` against a frozen log returns an identical
    candidate set (modulo ordering on ties).
  * Two successive ``dispatch_jot`` calls on the same handle produce a
    deterministic workflow-id sequence — first call succeeds with ``wf-1``,
    second call either returns the next workflow-id (after a manual
    retry / reset) or fails closed because the jot is already IN_FLIGHT.

Fixtures used (``tests/conftest.py``):
  * ``fake_workflow_substrate`` — captures every workflow trigger call and
    monotonically assigns ``wf-N`` ids.
  * ``isolated_log`` (local) — points ``mahavishnu.jot.paths.log_path`` at
    a tmp_path file so the test never touches the real ``~/.mahavishnu/jot/``.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from mahavishnu.jot.drain import (
    DispatchResult,
    _mcp_trigger_workflow,
    dispatch_jot,
    drain_plan,
)
from mahavishnu.jot.errors import JotDispatchError
from mahavishnu.jot.events import HLC, JotEvent, serialize
from mahavishnu.jot.fold import build_states, parse_events


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _capture_event(jot_id: str, text: str, *, wall_ms: int = 1_700_000_000_000) -> JotEvent:
    return JotEvent(
        id=jot_id,
        op="capture",
        text=text,
        hlc=HLC(wall_ms=wall_ms, ctr=0, node="a" * 8),
        ctx={},
        created_ms=wall_ms,
    )


def _done_event(jot_id: str, *, wall_ms: int = 1_700_000_001_000) -> JotEvent:
    return JotEvent(
        id=jot_id,
        op="done",
        text="",
        hlc=HLC(wall_ms=wall_ms, ctr=0, node="a" * 8),
        ctx={},
        created_ms=wall_ms,
    )


def _delete_event(jot_id: str, *, wall_ms: int = 1_700_000_002_000) -> JotEvent:
    return JotEvent(
        id=jot_id,
        op="delete",
        text="",
        hlc=HLC(wall_ms=wall_ms, ctr=0, node="a" * 8),
        ctx={},
        created_ms=wall_ms,
    )


def _write_log(path: Path, events: list[JotEvent]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for ev in events:
            f.write(serialize(ev))


@pytest.fixture
def isolated_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point drain + paths modules at a tmp_path log."""
    log = tmp_path / "log.jsonl"
    monkeypatch.setattr("mahavishnu.jot.drain.log_path", lambda: log)
    monkeypatch.setattr("mahavishnu.jot.paths.log_path", lambda: log)
    return log


# Strategy: a small list of captures — used as the raw input for the
# idempotence properties. Each jot id is 32-hex (the full ULID-shaped id
# the rest of the codebase uses).
_JOT_TEXT = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "Z"),
        whitelist_characters=" _-",
    ),
    min_size=4,
    max_size=80,
).filter(lambda t: t.strip() != "")


@st.composite
def _jot_ids_and_texts(draw, min_size: int = 0, max_size: int = 5) -> list[tuple[str, str]]:
    n = draw(st.integers(min_value=min_size, max_value=max_size))
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for i in range(n):
        # Deterministic 32-hex id; uniqueness across the list.
        body = draw(st.integers(min_value=0, max_value=2**31 - 1))
        jid = f"{body:032x}"[-32:]  # always 32 chars
        if jid in seen:
            continue
        seen.add(jid)
        text = draw(_JOT_TEXT)
        out.append((jid, text))
    return out


# ---------------------------------------------------------------------------
# Property 1 — drain_plan is idempotent on a frozen log
# ---------------------------------------------------------------------------


class TestDrainPlanIdempotence:
    """``drain_plan`` should produce the same candidate set on repeated calls."""

    @given(jots=_jot_ids_and_texts(max_size=5))
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_candidate_set_stable_under_repeat_calls(
        self,
        isolated_log: Path,
        jots: list[tuple[str, str]],
    ) -> None:
        """Three back-to-back ``drain_plan`` calls produce identical candidates.

        The candidate set is sorted by ``(-last_modified_ms, id)`` — that
        sort is deterministic, so equality of the tuple list is the
        strongest possible idempotence claim.
        """
        events = [
            _capture_event(jid, text, wall_ms=1_700_000_000_000 + i)
            for i, (jid, text) in enumerate(jots)
        ]
        _write_log(isolated_log, events)

        snapshots = [drain_plan(query=None, limit=20) for _ in range(3)]
        ids0 = [c.id for c in snapshots[0].candidates]
        for i, snap in enumerate(snapshots[1:], start=1):
            assert [c.id for c in snap.candidates] == ids0, (
                f"call #{i + 1} candidate ids diverged from first call"
            )
            # Status and last_modified_ms must also match exactly.
            for a, b in zip(snapshots[0].candidates, snap.candidates):
                assert a.status == b.status
                assert a.last_modified_ms == b.last_modified_ms
                assert a.dispatch_state == b.dispatch_state

    @given(jots=_jot_ids_and_texts(max_size=5))
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_candidate_set_stable_after_done_event(
        self,
        isolated_log: Path,
        jots: list[tuple[str, str]],
    ) -> None:
        """Marking a jot done is the only log mutation between calls; the
        open-jot candidate set is monotonically shrinking (or stable)."""
        events: list[JotEvent] = []
        for i, (jid, text) in enumerate(jots):
            events.append(_capture_event(jid, text, wall_ms=1_700_000_000_000 + i))

        # Snapshot the open candidate set first.
        _write_log(isolated_log, events)
        first_call = drain_plan(query=None, limit=20)
        first_open_ids = [c.id for c in first_call.candidates]

        # Mark some jots done, snapshot again — done jots must drop out.
        if jots:
            done_ids = {jots[0][0]}
            events.append(_done_event(jots[0][0], wall_ms=1_700_000_002_000))
            _write_log(isolated_log, events)
            second_call = drain_plan(query=None, limit=20)
            second_open_ids = [c.id for c in second_call.candidates]
            # Done jot must be absent from the second snapshot.
            assert jots[0][0] not in second_open_ids
            # All other originally-open jots are still present.
            assert set(second_open_ids).issubset(set(first_open_ids))

    @given(jots=_jot_ids_and_texts(max_size=3))
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_candidate_set_stable_after_delete_event(
        self,
        isolated_log: Path,
        jots: list[tuple[str, str]],
    ) -> None:
        """Deleting a jot removes it from the candidate set on the next call.

        ``delete_jot`` is a soft delete; the ``deleted`` flag is read in
        ``_is_drain_eligible`` so a deleted jot disappears from the next
        ``drain_plan`` call.
        """
        if not jots:
            return
        events = [
            _capture_event(jid, text, wall_ms=1_700_000_000_000 + i)
            for i, (jid, text) in enumerate(jots)
        ]
        _write_log(isolated_log, events)
        before = [c.id for c in drain_plan(query=None, limit=20).candidates]
        # Soft-delete the first one.
        events.append(_delete_event(jots[0][0], wall_ms=1_700_000_002_000))
        _write_log(isolated_log, events)
        after = [c.id for c in drain_plan(query=None, limit=20).candidates]
        assert jots[0][0] not in after
        assert set(after).issubset(set(before))


# ---------------------------------------------------------------------------
# Property 2 — dispatch_jot determinism + closed-fail on re-entry
# ---------------------------------------------------------------------------


class TestDispatchDeterminism:
    """``dispatch_jot`` is deterministic given an isolated log."""

    @given(jot_text=_JOT_TEXT)
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_first_dispatch_returns_wf_1(
        self,
        isolated_log: Path,
        fake_workflow_substrate: dict,
        jot_text: str,
    ) -> None:
        """First dispatch on a fresh jot always yields ``wf-1``."""
        # Stable 32-hex id so handle resolution works on subsequent calls.
        jid = f"{abs(hash(jot_text)) & 0xffffffffffffffff:016x}" * 2
        _write_log(isolated_log, [_capture_event(jid, jot_text)])
        # Snapshot the substrate's call count BEFORE this example runs.
        # (fake_workflow_substrate persists across @given examples.)
        calls_before = len(fake_workflow_substrate["trigger"])
        result = asyncio.run(dispatch_jot(jid[:6], dispatched_from="mcp"))
        assert isinstance(result, DispatchResult)
        # Resulting workflow_id is always exactly the next-in-sequence.
        assert result.workflow_id == f"wf-{calls_before + 1}"
        assert result.status == "in_flight"
        # And the substrate recorded exactly one additional call.
        assert len(fake_workflow_substrate["trigger"]) == calls_before + 1

    @given(jot_text=_JOT_TEXT)
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_second_dispatch_fails_closed_when_in_flight(
        self,
        isolated_log: Path,
        fake_workflow_substrate: dict,
        jot_text: str,
    ) -> None:
        """A second dispatch_jot on the same IN_FLIGHT jot raises.

        This is the "fails closed if already in flight" branch.
        """
        jid = f"{abs(hash(jot_text + 'X')) & 0xffffffffffffffff:016x}" * 2
        _write_log(isolated_log, [_capture_event(jid, jot_text)])
        calls_before = len(fake_workflow_substrate["trigger"])
        first = asyncio.run(dispatch_jot(jid[:6], dispatched_from="mcp"))
        assert first.workflow_id == f"wf-{calls_before + 1}"

        # Second call — jot is now IN_FLIGHT.
        with pytest.raises(JotDispatchError) as excinfo:
            asyncio.run(dispatch_jot(jid[:6], dispatched_from="mcp"))
        assert "IN_FLIGHT" in str(excinfo.value)
        # No NEW substrate call from the failed dispatch (fail-closed).
        assert len(fake_workflow_substrate["trigger"]) == calls_before + 1

    @given(jot_text=_JOT_TEXT)
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_consecutive_dispatches_after_reset_assign_sequential_ids(
        self,
        isolated_log: Path,
        fake_workflow_substrate: dict,
        jot_text: str,
    ) -> None:
        """After the jot is marked done, a fresh dispatch yields ``wf-2``.

        This pins the determinism of the monotonic id generator: each
        substrate call advances the counter by exactly one, regardless of
        the dispatch_jot caller.
        """
        jid = f"{abs(hash(jot_text + 'Y')) & 0xffffffffffffffff:016x}" * 2
        _write_log(
            isolated_log,
            [
                _capture_event(jid, jot_text, wall_ms=1_700_000_000_000),
                _done_event(jid, wall_ms=1_700_000_001_000),
            ],
        )
        calls_before = len(fake_workflow_substrate["trigger"])
        # A done jot cannot be dispatched — it raises.
        with pytest.raises(JotDispatchError):
            asyncio.run(dispatch_jot(jid[:6], dispatched_from="mcp"))
        # No NEW trigger call (validation rejects before reaching substrate).
        assert len(fake_workflow_substrate["trigger"]) == calls_before


# ---------------------------------------------------------------------------
# Property 3 — log round-trip preserves the candidate set
# ---------------------------------------------------------------------------


class TestLogRoundTripIdempotence:
    """Re-reading the log via ``parse_events`` + ``build_states`` is stable."""

    @given(jots=_jot_ids_and_texts(max_size=4))
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_parse_build_repeatable(
        self,
        isolated_log: Path,
        jots: list[tuple[str, str]],
    ) -> None:
        """Two parse/build cycles produce the same JotSummary list."""
        events = [
            _capture_event(jid, text, wall_ms=1_700_000_000_000 + i)
            for i, (jid, text) in enumerate(jots)
        ]
        _write_log(isolated_log, events)

        first_states = build_states(parse_events(isolated_log), enrich=False).states
        second_states = build_states(parse_events(isolated_log), enrich=False).states

        assert len(first_states) == len(second_states)
        for a, b in zip(first_states, second_states):
            assert a.id == b.id
            assert a.short_id == b.short_id
            assert a.text == b.text
            assert a.status == b.status
            assert a.last_modified_ms == b.last_modified_ms
            assert a.dispatch_state == b.dispatch_state
            assert a.current_attempt == b.current_attempt
            assert a.dispatch_workflow_id == b.dispatch_workflow_id

    @given(jots=_jot_ids_and_texts(max_size=4))
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_raw_log_bytes_stable_under_repeat_writes(
        self,
        isolated_log: Path,
        jots: list[tuple[str, str]],
    ) -> None:
        """Writing the same events twice produces the same byte-for-byte log."""
        events = [
            _capture_event(jid, text, wall_ms=1_700_000_000_000 + i)
            for i, (jid, text) in enumerate(jots)
        ]
        _write_log(isolated_log, events)
        before = isolated_log.read_bytes()
        _write_log(isolated_log, events)
        after = isolated_log.read_bytes()
        assert before == after, "log byte-for-byte drift after re-write"

    @given(jots=_jot_ids_and_texts(max_size=4))
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_event_json_roundtrip_preserves_candidate_set(
        self,
        isolated_log: Path,
        jots: list[tuple[str, str]],
    ) -> None:
        """JSONL round-trip preserves every JotSummary field (id, status)."""
        events = [
            _capture_event(jid, text, wall_ms=1_700_000_000_000 + i)
            for i, (jid, text) in enumerate(jots)
        ]
        _write_log(isolated_log, events)
        # Round-trip through JSON.
        lines = isolated_log.read_text().splitlines()
        rewritten = [json.loads(line) for line in lines if line.strip()]
        isolated_log.write_text(
            "\n".join(json.dumps(rec, separators=(",", ":")) for rec in rewritten) + "\n"
        )
        states = build_states(parse_events(isolated_log), enrich=False).states
        ids = sorted(s.id for s in states)
        expected_ids = sorted(jid for jid, _ in jots)
        assert ids == expected_ids