"""Unit tests for mahavishnu.core.verification — Phase 1 Task 1.6 exit criteria.

Covers the failure-mode contract spelled out in the module docstring and
the Phase 1 Exit Criteria in
``docs/plans/2026-07-11-ultracode-integration-wiring.md`` §5:

- three diverse refuters disagreeing on a bad proposal
- unanimous APPROVE → consensus APPROVE
- all refuters failing → consensus UNAVAILABLE (NOT SPLIT)
- error ↔ ABSTAIN biconditional on ``RefuterVerdict``
- Dhara write failure → ``persisted=False`` and dead-letter file present
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from pydantic import ValidationError
import pytest

from mahavishnu.core.verification import (
    Consensus,
    Proposal,
    RefuterErrorKind,
    RefuterStrategy,
    RefuterVerdict,
    RefuterVerdictValue,
    VerificationResult,
    VerificationStore,
    verify_proposal,
)

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_strategy(
    name: str,
    raw_response: str | None,
    raise_exc: BaseException | None = None,
    timeout: float = 30.0,
) -> RefuterStrategy:
    """Build a strategy that, when patched into ``_invoke_llm``, emits ``raw_response``.

    The patched ``_invoke_llm`` reads ``raw_response`` from a closure-captured
    map keyed by strategy name; this helper produces the strategy, and the
    test supplies the matching LLM seam via ``monkeypatch.setattr``.
    """
    return RefuterStrategy(
        name=name,
        prompt_template=f"{name}: {{proposal}}",
        temperature=0.5,
        timeout_seconds=timeout,
    )


def _patch_llm_responses(
    monkeypatch: pytest.MonkeyPatch,
    responses: dict[str, str],
    raisers: dict[str, BaseException] | None = None,
) -> None:
    """Patch ``mahavishnu.core.verification._invoke_llm`` with a stub.

    The stub returns ``responses[strategy.name]`` for normal strategies
    and raises the exception in ``raisers[strategy.name]`` for failing ones.
    """

    async def fake_invoke(strategy: RefuterStrategy, proposal: Proposal) -> str:
        if raisers and strategy.name in raisers:
            raise raisers[strategy.name]
        return responses.get(strategy.name, "")

    monkeypatch.setattr(
        "mahavishnu.core.verification._invoke_llm",
        fake_invoke,
    )


def _approve_response(rationale: str = "ok", concerns: list[str] | None = None) -> str:
    return json.dumps(
        {
            "verdict": RefuterVerdictValue.APPROVE.value,
            "rationale": rationale,
            "concerns": concerns or [],
        }
    )


def _reject_response(rationale: str = "bad", concerns: list[str] | None = None) -> str:
    return json.dumps(
        {
            "verdict": RefuterVerdictValue.REJECT.value,
            "rationale": rationale,
            "concerns": concerns or [],
        }
    )


def _proposal(
    proposal_id: str = "p1",
    subject: str = "subject text",
    details: dict | None = None,
) -> Proposal:
    return Proposal(
        proposal_id=proposal_id,
        proposal_type="clone_refactor",
        subject=subject,
        details=details or {"k": "v"},
    )


# ---------------------------------------------------------------------------
# Task 1.6 exit criteria — multi-refuter consensus
# ---------------------------------------------------------------------------


async def test_three_refuters_disagree_on_bad_proposal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """At least one refuter returns ABSTAIN-or-REJECT when fed a bad proposal.

    Two refuters ABSTAIN (one malformed, one LLM error) and one REJECTs;
    the resulting consensus must surface the disagreement — at minimum one
    of the non-empty verdicts is REJECT or ABSTAIN.
    """
    strategies = (
        _build_strategy("a", _reject_response("dangerous", ["blast radius"])),
        _build_strategy("b", "{not json"),
        _build_strategy("c", _approve_response("looks fine")),
    )
    _patch_llm_responses(
        monkeypatch,
        responses={
            "a": _reject_response("dangerous", ["blast radius"]),
            "b": "{not json",
            "c": _approve_response("looks fine"),
        },
        raisers={"c": RuntimeError("provider 500")},
    )

    result = await verify_proposal(_proposal(), strategies=list(strategies))

    # Two verdicts (the third raised and got encoded as LLM_ERROR/ABSTAIN).
    assert len(result.verdicts) == 3

    verdict_kinds = {v.verdict for v in result.verdicts}
    # At least one ABSTAIN or REJECT must be present.
    assert (RefuterVerdictValue.REJECT in verdict_kinds) or (
        RefuterVerdictValue.ABSTAIN in verdict_kinds
    )

    # The malformed-response refuter surfaces as ABSTAIN/MALFORMED.
    malformed = next(v for v in result.verdicts if v.strategy_name == "b")
    assert malformed.verdict == RefuterVerdictValue.ABSTAIN
    assert malformed.error == RefuterErrorKind.MALFORMED_RESPONSE

    # Concerns from the REJECT refuter survive into the aggregated set.
    assert "blast radius" in result.concerns_aggregated


async def test_consensus_approve_when_all_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """All APPROVE → consensus APPROVE."""
    strategies = (
        _build_strategy("a", _approve_response()),
        _build_strategy("b", _approve_response()),
        _build_strategy("c", _approve_response()),
    )
    _patch_llm_responses(
        monkeypatch,
        responses={
            "a": _approve_response(),
            "b": _approve_response(),
            "c": _approve_response(),
        },
    )

    result = await verify_proposal(_proposal(), strategies=list(strategies))

    assert result.consensus == Consensus.APPROVE
    assert all(v.verdict == RefuterVerdictValue.APPROVE for v in result.verdicts)
    assert result.concerns_aggregated == []


async def test_consensus_unavailable_when_all_refuters_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """All refuters raise → consensus UNAVAILABLE (NOT SPLIT)."""
    strategies = (
        _build_strategy("a", None, raise_exc=RuntimeError("outage")),
        _build_strategy("b", None, raise_exc=RuntimeError("outage")),
        _build_strategy("c", None, raise_exc=RuntimeError("outage")),
    )
    _patch_llm_responses(
        monkeypatch,
        responses={},
        raisers={
            "a": RuntimeError("outage"),
            "b": RuntimeError("outage"),
            "c": RuntimeError("outage"),
        },
    )

    result = await verify_proposal(_proposal(), strategies=list(strategies))

    assert result.consensus == Consensus.UNAVAILABLE
    assert result.consensus != Consensus.SPLIT
    assert all(v.verdict == RefuterVerdictValue.ABSTAIN for v in result.verdicts)
    assert all(v.error is not None for v in result.verdicts)


# ---------------------------------------------------------------------------
# Task 1.6 exit criteria — model validator
# ---------------------------------------------------------------------------


def test_model_validator_enforces_error_abstain_biconditional() -> None:
    """APPROVE + error=TIMEOUT is rejected; ABSTAIN + error=None is rejected."""
    # error set but verdict != ABSTAIN → invalid.
    with pytest.raises(ValidationError):
        RefuterVerdict(
            strategy_name="x",
            verdict=RefuterVerdictValue.APPROVE,
            rationale="ok",
            concerns=[],
            latency_seconds=0.1,
            error=RefuterErrorKind.TIMEOUT,
        )

    # error None but verdict == ABSTAIN → invalid.
    with pytest.raises(ValidationError):
        RefuterVerdict(
            strategy_name="x",
            verdict=RefuterVerdictValue.ABSTAIN,
            rationale="ok",
            concerns=[],
            latency_seconds=0.1,
            error=None,
        )

    # APPROVE without error and ABSTAIN with error are both valid.
    valid_approve = RefuterVerdict(
        strategy_name="x",
        verdict=RefuterVerdictValue.APPROVE,
        rationale="ok",
        concerns=[],
        latency_seconds=0.1,
    )
    assert valid_approve.error is None

    valid_abstain = RefuterVerdict(
        strategy_name="x",
        verdict=RefuterVerdictValue.ABSTAIN,
        rationale="bad",
        concerns=[],
        latency_seconds=0.1,
        error=RefuterErrorKind.LLM_ERROR,
    )
    assert valid_abstain.error == RefuterErrorKind.LLM_ERROR


# ---------------------------------------------------------------------------
# Task 1.6 exit criteria — Dhara persistence failure
# ---------------------------------------------------------------------------


async def test_persisted_false_on_dhara_write_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Dhara raises on put() → result.persisted=False and a dead-letter file is written.

    Redirects ``VerificationStore.DEAD_LETTER_DIR`` to ``tmp_path`` so the
    dead-letter file lands somewhere pytest cleans up.
    """
    monkeypatch.setattr(VerificationStore, "DEAD_LETTER_DIR", tmp_path)

    class _BrokenDhara:
        async def put(self, key: str, payload: dict) -> None:
            raise ConnectionError("dhara unreachable")

    store = VerificationStore(dhara=_BrokenDhara())  # type: ignore[arg-type]

    result = VerificationResult(
        proposal_id="pid-deadletter",
        verdicts=[
            RefuterVerdict(
                strategy_name="a",
                verdict=RefuterVerdictValue.APPROVE,
                rationale="ok",
                concerns=[],
                latency_seconds=0.1,
            ),
        ],
        consensus=Consensus.APPROVE,
        concerns_aggregated=[],
    )

    persisted = await store.persist(result)

    assert persisted.persisted is False
    assert persisted.persist_error is not None
    assert "ConnectionError" in persisted.persist_error

    dead_letter = tmp_path / "pid-deadletter.json"
    assert dead_letter.exists(), "dead-letter file must be written on Dhara failure"
    payload = json.loads(dead_letter.read_text())
    assert payload["proposal_id"] == "pid-deadletter"
    assert payload["consensus"] == Consensus.APPROVE.value


# ---------------------------------------------------------------------------
# Bonus: ensures the LLM-error LLM-seam path doesn't slip into the SPLIT bucket
# when only one refuter succeeds (mixed-availability scenario).
# ---------------------------------------------------------------------------


async def test_mixed_availability_consensus_uses_non_error_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One LLM failure + two APPROVE → APPROVE (failure excluded from voting)."""
    strategies = (
        _build_strategy("ok1", _approve_response()),
        _build_strategy("ok2", _approve_response()),
        _build_strategy("flaky", None, raise_exc=RuntimeError("timeout")),
    )
    _patch_llm_responses(
        monkeypatch,
        responses={"ok1": _approve_response(), "ok2": _approve_response()},
        raisers={"flaky": RuntimeError("timeout")},
    )

    result = await verify_proposal(_proposal(), strategies=list(strategies))

    assert result.consensus == Consensus.APPROVE
    assert any(
        v.strategy_name == "flaky" and v.error == RefuterErrorKind.LLM_ERROR
        for v in result.verdicts
    )


# ---------------------------------------------------------------------------
# Empty-proposal short-circuit (documented behaviour, worth pinning)
# ---------------------------------------------------------------------------


async def test_empty_proposal_short_circuits_to_approve() -> None:
    """An empty proposal short-circuits to APPROVE without invoking any refuter."""
    proposal = Proposal(
        proposal_id="empty-1",
        proposal_type="clone_refactor",
        subject="",
        details={},
    )

    result = await verify_proposal(proposal)

    assert result.consensus == Consensus.APPROVE
    assert result.verdicts == []
    assert "empty proposal" in result.concerns_aggregated[0]
