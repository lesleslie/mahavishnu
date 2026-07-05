from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import logging
import os
from typing import Any, Protocol

logger = logging.getLogger(__name__)


DEFAULT_WEEKLY_CAP: int = 100


ENV_VAR: str = "MAHAVISHNU_DISTILL_LLM_WEEKLY_CAP"


class CostCeilingExceeded(Exception):  # noqa: N818 — plan-locked name
    def __init__(self, *, calls_made: int, ceiling: int) -> None:
        self.calls_made = int(calls_made)
        self.ceiling = int(ceiling)
        super().__init__(
            f"distill LLM weekly cap exceeded (calls_made={calls_made}, ceiling={ceiling})"
        )


@dataclass(frozen=True)
class _StubCandidate:
    session_id: str
    evidence_count: int = 0


class _LlmLike(Protocol):
    def __call__(self, prompt: str) -> dict[str, Any]: ...


@dataclass
class _LlmSynthesizer:
    llm: _LlmLike
    cap: int | None = None
    ceiling: int = DEFAULT_WEEKLY_CAP
    calls_made: int = 0
    last_reset: datetime = None  # type: ignore[assignment]

    def __post_init__(self) -> None:

        if self.cap is not None:
            self.ceiling = int(self.cap)
        else:
            env_val = os.environ.get(ENV_VAR)
            if env_val is not None and env_val.strip():
                try:
                    self.ceiling = int(env_val)
                except ValueError:
                    logger.warning(
                        "%s=%r is not an int; falling back to %s",
                        ENV_VAR,
                        env_val,
                        DEFAULT_WEEKLY_CAP,
                    )
                    self.ceiling = DEFAULT_WEEKLY_CAP
            else:
                self.ceiling = DEFAULT_WEEKLY_CAP
        self.last_reset = datetime.now(tz=UTC)

    def synthesize(self, candidate: _StubCandidate) -> dict[str, Any]:
        if self.calls_made >= self.ceiling:
            raise CostCeilingExceeded(
                calls_made=self.calls_made,
                ceiling=self.ceiling,
            )

        prompt = _build_stub_prompt(candidate)
        payload = self.llm(prompt)
        self.calls_made += 1
        return payload


def _build_stub_prompt(candidate: _StubCandidate) -> str:
    return (
        f"Distill a workflow from session {candidate.session_id} "
        f"with {candidate.evidence_count} prior workflow runs."
    )


__all__ = [
    "DEFAULT_WEEKLY_CAP",
    "ENV_VAR",
    "CostCeilingExceeded",
    "_LlmSynthesizer",
    "_StubCandidate",
]
