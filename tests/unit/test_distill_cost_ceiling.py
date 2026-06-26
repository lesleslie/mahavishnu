"""Cost ceiling tests for the distilled workflow LLM synthesizer.

Plan 5 Phase A.1 Task 6.

The skill system documents a 100 calls/week ceiling but does NOT
enforce it (the constant lives in a docstring at
``session_buddy/mcp/tools/memory/search_tools.py:1523``). Plan 5
ADDS this as a real gate — not a mirror of the skill system.

Contract:

- ``MAHAVISHNU_DISTILL_LLM_WEEKLY_CAP`` defaults to 100/week.
- ``_LlmSynthesizer.ceiling`` reads the env var at construction.
- Calling ``synthesize`` past the cap raises ``CostCeilingExceeded``.
- The cap is per-process; each ``_LlmSynthesizer`` instance counts
  its own calls.

Phase A.1 stubs the LLM with a deterministic callable; the ceiling
is the gate, not the LLM.
"""

from __future__ import annotations

import pytest

from mahavishnu.distill.synthesizer import (
    DEFAULT_WEEKLY_CAP,
    CostCeilingExceeded,
    _LlmSynthesizer,
    _StubCandidate,
)


class _StubLlm:
    """Deterministic LLM stub: returns the same schema-valid payload
    for every call. Raises only when configured to."""

    def __init__(self, payload: dict | None = None, *, raise_on: int | None = None) -> None:
        self.payload = payload or {
            "intent": "stub workflow",
            "steps": [
                {"id": "s1", "tool": "noop", "args": {}, "description": "step 1"},
                {"id": "s2", "tool": "noop", "args": {}, "description": "step 2"},
            ],
            "conditionals": [],
            "parallel_groups": [],
            "params_template": {},
            "repo_filter": "*",
        }
        self.raise_on = raise_on
        self.call_count = 0

    def __call__(self, _prompt: str) -> dict:
        self.call_count += 1
        if self.raise_on is not None and self.call_count >= self.raise_on:
            raise RuntimeError("stub LLM failure")
        return self.payload


class TestCostCeilingDefaults:
    def test_default_cap_is_100(self) -> None:
        assert DEFAULT_WEEKLY_CAP == 100

    def test_cap_reads_from_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MAHAVISHNU_DISTILL_LLM_WEEKLY_CAP", "5")
        synth = _LlmSynthesizer(_StubLlm())
        assert synth.ceiling == 5

    def test_cap_falls_back_to_default_when_env_unset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("MAHAVISHNU_DISTILL_LLM_WEEKLY_CAP", raising=False)
        synth = _LlmSynthesizer(_StubLlm())
        assert synth.ceiling == DEFAULT_WEEKLY_CAP

    def test_explicit_cap_overrides_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MAHAVISHNU_DISTILL_LLM_WEEKLY_CAP", "200")
        synth = _LlmSynthesizer(_StubLlm(), cap=10)
        assert synth.ceiling == 10


class TestCostCeilingGate:
    def test_synthesize_within_cap_succeeds(self) -> None:
        llm = _StubLlm()
        synth = _LlmSynthesizer(llm, cap=3)
        for _ in range(3):
            cand = _StubCandidate(session_id="s1", evidence_count=5)
            payload = synth.synthesize(cand)
            assert payload["intent"] == "stub workflow"
        assert llm.call_count == 3

    def test_synthesize_at_cap_raises(self) -> None:
        llm = _StubLlm()
        synth = _LlmSynthesizer(llm, cap=2)
        cand = _StubCandidate(session_id="s1", evidence_count=5)
        synth.synthesize(cand)
        synth.synthesize(cand)
        # Third call exceeds the cap → CostCeilingExceeded.
        with pytest.raises(CostCeilingExceeded) as ei:
            synth.synthesize(cand)
        assert ei.value.calls_made == 2
        assert ei.value.ceiling == 2

    def test_synthesize_past_cap_raises_on_every_call(self) -> None:
        llm = _StubLlm()
        synth = _LlmSynthesizer(llm, cap=1)
        cand = _StubCandidate(session_id="s1", evidence_count=5)
        synth.synthesize(cand)
        for _ in range(3):
            with pytest.raises(CostCeilingExceeded):
                synth.synthesize(cand)


class TestCostCeilingMessage:
    def test_exception_message_includes_counter(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MAHAVISHNU_DISTILL_LLM_WEEKLY_CAP", "2")
        synth = _LlmSynthesizer(_StubLlm())
        cand = _StubCandidate(session_id="s1", evidence_count=5)
        synth.synthesize(cand)
        synth.synthesize(cand)
        with pytest.raises(CostCeilingExceeded) as ei:
            synth.synthesize(cand)
        msg = str(ei.value)
        assert "2" in msg  # cap
        assert "ceiling" in msg.lower() or "cap" in msg.lower()


class TestCostCeilingErrorClass:
    def test_cost_ceiling_exceeded_is_exception(self) -> None:
        # Catchable as Exception by callers in the distill loop.
        assert issubclass(CostCeilingExceeded, Exception)
