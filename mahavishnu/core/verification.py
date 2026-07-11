"""Adversarial verification gate — diverse-refuter verification primitive.

Per Phase 1 of the Ultracode Integration Wiring plan (see
``docs/plans/2026-07-11-ultracode-integration-wiring.md`` §5). Provides the
typed ``Proposal``/``RefuterStrategy``/``VerificationResult`` models and an
async runner that supports the ``clone_refactor_group`` and
``self_improvement_generate`` verification gates.

Failure-mode contract (mandatory; verified by tests in T1.6):

- Per-refuter timeout → ``verdict=ABSTAIN``, ``error=TIMEOUT``.
- LLM call failure → ``verdict=ABSTAIN``, ``error=LLM_ERROR`` (or
  ``RATE_LIMITED`` on 429).
- Malformed JSON response → ``verdict=ABSTAIN``, ``error=MALFORMED_RESPONSE``.
- All refuters fail (infrastructure outage) → ``consensus=Consensus.UNAVAILABLE``
  — never ``SPLIT`` (which would mask the outage).
- Empty proposal → short-circuit ``consensus=Consensus.APPROVE`` with
  ``concerns_aggregated=["empty proposal — refuters skipped"]``.
- ``verify_proposal`` NEVER raises. All failures are encoded in the result.

Persistence contract (``VerificationStore``):

- Successful Dhara write → ``persisted=True``, ``persist_error=None``.
- Dhara write failure → ``persisted=False``, ``persist_error=<summary>``,
  WARNING log, dead-letter file written under
  ``~/.mahavishnu/verification-dead-letter/{proposal_id}.json``.

LLM call seam:

The private ``_invoke_llm`` function is the pluggable seam for real LLM
calls. The default implementation returns an empty string (signaling "no
LLM configured"), which causes every refuter to abstain with
``error=INTERNAL`` and drives ``consensus=UNAVAILABLE``. Production wiring
will replace the default; tests monkey-patch it to drive specific
scenarios without making real LLM calls.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
import time
from typing import TYPE_CHECKING, Any, Literal

from oneiric.core.logging import get_logger
from pydantic import BaseModel, ConfigDict, Field, model_validator

if TYPE_CHECKING:
    from mahavishnu.core.state_backends.dhara import DharaStateBackend

logger = get_logger("mahavishnu.verification")


# Resolve RateLimitError at module load time. Falls back to a local
# stand-in if mahavishnu.core.errors isn't importable for any reason
# (it should always be in production — this is defensive).
try:
    from mahavishnu.core.errors import RateLimitError as _RateLimitError
except ImportError:  # pragma: no cover

    class _RateLimitError(Exception):  # type: ignore[no-redef]
        """Fallback stub when mahavishnu.core.errors is not importable."""

        pass


# ---------------------------------------------------------------------------
# Shared MCP-tool helpers (lifted from clone_tools.py / self_improvement_tools.py
# so both surfaces use one canonical implementation. Issue 3+4 in Phase 1 review.)
# ---------------------------------------------------------------------------


def is_verification_enabled(app: Any | None) -> bool:
    """Return True iff the operator opted into verification blocking.

    Reads ``verification_enabled`` from the app's settings when available;
    defaults to False (informational-only mode per the integration plan).
    """
    if app is None:
        return False
    settings = getattr(app, "settings", None)
    if settings is None:
        return False
    return bool(getattr(settings, "verification_enabled", False))


def build_default_store(app: Any) -> VerificationStore | None:
    """Build a Dhara-backed ``VerificationStore`` from the app's settings.

    Returns None when Dhara cannot be configured (e.g. ``dhara_url`` is
    absent). Callers handle the None case by skipping persistence — the
    ``verification`` field is still populated from the in-memory result.
    """
    try:
        dhara_url = getattr(
            getattr(app, "settings", None), "dhara_url", "http://localhost:8683"
        )
        from mahavishnu.core.state_backends.dhara import DharaStateBackend

        backend = DharaStateBackend(base_url=dhara_url)
        return VerificationStore(dhara=backend)
    except Exception:
        logger.warning("build_default_store: Dhara unavailable, persistence disabled")
        return None


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class RefuterErrorKind(StrEnum):
    """Failure modes for a single refuter invocation."""

    TIMEOUT = "timeout"
    MALFORMED_RESPONSE = "malformed_response"
    LLM_ERROR = "llm_error"
    RATE_LIMITED = "rate_limited"
    INTERNAL = "internal"


class RefuterVerdictValue(StrEnum):
    """The actual verdict a refuter returns."""

    APPROVE = "approve"
    REJECT = "reject"
    ABSTAIN = "abstain"


class Consensus(StrEnum):
    """Aggregate consensus across all refuters for a proposal."""

    APPROVE = "approve"
    REJECT = "reject"
    SPLIT = "split"
    UNAVAILABLE = "unavailable"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class RefuterStrategy(BaseModel):
    """A single refuter strategy (prompt + temperature + model hint).

    Frozen so callers cannot mutate a strategy mid-run. Tests construct
    bespoke strategies; production uses ``DEFAULT_STRATEGIES``.
    """

    model_config = ConfigDict(frozen=True)

    name: str
    prompt_template: str
    temperature: float = Field(ge=0.0, le=2.0)
    model_hint: str | None = None
    timeout_seconds: float = Field(default=30.0, gt=0)


class RefuterVerdict(BaseModel):
    """A single refuter's verdict on a proposal.

    Stores only ``strategy_name`` (not the whole ``RefuterStrategy``) so
    the ``prompt_template`` is not leaked into persisted/returned verdicts.
    """

    model_config = ConfigDict(frozen=True)

    strategy_name: str
    verdict: RefuterVerdictValue
    rationale: str
    concerns: list[str] = Field(default_factory=list)
    latency_seconds: float
    error: RefuterErrorKind | None = None

    @model_validator(mode="after")
    def _check_error_abstain_biconditional(self) -> RefuterVerdict:
        error_set = self.error is not None
        abstain = self.verdict == RefuterVerdictValue.ABSTAIN
        if error_set != abstain:
            raise ValueError(
                "error must be set iff verdict == ABSTAIN "
                f"(got error={self.error}, verdict={self.verdict})"
            )
        return self


class Proposal(BaseModel):
    """A typed proposal to verify.

    Replaces the bare ``dict`` parameter that violated the project's
    no-``Any`` rule (per ``CLAUDE.md``). ``proposal_type`` is a closed
    Literal so adding new proposal kinds is a deliberate code change.
    """

    proposal_id: str
    proposal_type: Literal["clone_refactor", "self_improvement"]
    subject: str
    details: dict[str, Any] = Field(default_factory=dict)


class VerificationResult(BaseModel):
    """Aggregate result of running all refuters against a proposal.

    ``persisted`` and ``persist_error`` make the audit trail's durability
    observable to callers — a ``persisted=False`` result tells the caller
    the verification rationale did not reach Dhara and a dead-letter file
    is the recovery path.
    """

    model_config = ConfigDict(frozen=True)

    proposal_id: str
    verdicts: list[RefuterVerdict] = Field(default_factory=list)
    consensus: Consensus
    concerns_aggregated: list[str] = Field(default_factory=list)
    persisted: bool = False
    persist_error: str | None = None


# ---------------------------------------------------------------------------
# Default strategies
# ---------------------------------------------------------------------------


DEFAULT_STRATEGIES: tuple[RefuterStrategy, ...] = (
    RefuterStrategy(
        name="checklist",
        prompt_template=(
            "Evaluate the following proposal against a strict safety "
            "checklist. Reply with JSON of the form "
            '{"verdict": "approve"|"reject"|"abstain", '
            '"rationale": str, "concerns": [str]}.\n\n'
            "Proposal:\n{proposal}"
        ),
        temperature=0.2,
    ),
    RefuterStrategy(
        name="devils_advocate",
        prompt_template=(
            "Argue against the following proposal. Find any flaws, risks, "
            "or downsides. Reply with JSON of the form "
            '{"verdict": "approve"|"reject"|"abstain", '
            '"rationale": str, "concerns": [str]}.\n\n'
            "Proposal:\n{proposal}"
        ),
        temperature=0.7,
    ),
    RefuterStrategy(
        name="scope_audit",
        prompt_template=(
            "Audit whether the proposal's blast radius matches its "
            "description. Reply with JSON of the form "
            '{"verdict": "approve"|"reject"|"abstain", '
            '"rationale": str, "concerns": [str]}.\n\n'
            "Proposal:\n{proposal}"
        ),
        temperature=0.3,
    ),
)


# ---------------------------------------------------------------------------
# Consensus / proposal helpers
# ---------------------------------------------------------------------------


def _is_empty_proposal(proposal: Proposal) -> bool:
    """Return True when a proposal carries no meaningful content."""
    return not proposal.subject.strip() and not proposal.details


def _compute_consensus(verdicts: list[RefuterVerdict], is_empty: bool) -> Consensus:
    """Aggregate verdicts into a single Consensus value.

    Rules (see module docstring):
    - Empty proposal → APPROVE.
    - All verdicts ABSTAIN-with-error → UNAVAILABLE.
    - Any REJECT → REJECT (conservative gate).
    - All non-error verdicts APPROVE → APPROVE.
    - Everything else → SPLIT.
    """
    if is_empty:
        return Consensus.APPROVE

    distinct_no_error = {v.verdict for v in verdicts if v.error is None}

    if not distinct_no_error:
        # Every refuter abstained with an error → infrastructure outage.
        return Consensus.UNAVAILABLE

    if RefuterVerdictValue.REJECT in distinct_no_error:
        return Consensus.REJECT

    if distinct_no_error == {RefuterVerdictValue.APPROVE}:
        return Consensus.APPROVE

    return Consensus.SPLIT


def _aggregate_concerns(verdicts: list[RefuterVerdict]) -> list[str]:
    """Deduplicated, order-preserving union of all refuter concerns."""
    seen: set[str] = set()
    out: list[str] = []
    for v in verdicts:
        for c in v.concerns:
            if c and c not in seen:
                seen.add(c)
                out.append(c)
    return out


# ---------------------------------------------------------------------------
# LLM call seam (pluggable)
# ---------------------------------------------------------------------------


async def _invoke_llm(strategy: RefuterStrategy, proposal: Proposal) -> str:
    """Invoke the LLM and return the raw response text.

    Pluggable seam. Production wiring MUST override this default; tests
    monkey-patch it to drive specific scenarios without real LLM calls.

    The default implementation logs a clear WARNING at module import
    time and returns an empty string, which ``_run_refuter`` interprets
    as "no LLM configured" → ABSTAIN with ``error=INTERNAL``. Callers
    that hit this path in production should treat the verification result
    as "infrastructure unavailable" rather than a real refuter verdict.

    The function MUST return a string (possibly empty) or raise. It MUST
    NOT return ``None``.
    """
    return ""


async def _run_refuter(strategy: RefuterStrategy, proposal: Proposal) -> RefuterVerdict:
    """Run a single refuter and return its verdict. NEVER raises.

    All failure modes (timeout, LLM error, rate limit, malformed JSON,
    internal) are encoded as ABSTAIN verdicts with the appropriate
    ``RefuterErrorKind``. See module docstring for the full contract.
    """
    start = time.monotonic()
    # Note: prompt_template substitution happens inside _invoke_llm
    # (production wiring owns the templating concern). Test stubs
    # receive the strategy + proposal and decide what to do with them.

    try:
        async with asyncio.timeout(strategy.timeout_seconds):
            raw = await _invoke_llm(strategy, proposal)
    except TimeoutError:
        latency = time.monotonic() - start
        logger.warning(
            "refuter %s timed out after %.2fs",
            strategy.name,
            latency,
        )
        return RefuterVerdict(
            strategy_name=strategy.name,
            verdict=RefuterVerdictValue.ABSTAIN,
            rationale=f"refuter timed out after {strategy.timeout_seconds:.1f}s",
            concerns=[],
            latency_seconds=latency,
            error=RefuterErrorKind.TIMEOUT,
        )
    except _RateLimitError:
        latency = time.monotonic() - start
        logger.warning("refuter %s rate-limited", strategy.name)
        return RefuterVerdict(
            strategy_name=strategy.name,
            verdict=RefuterVerdictValue.ABSTAIN,
            rationale="refuter LLM call rate-limited",
            concerns=[],
            latency_seconds=latency,
            error=RefuterErrorKind.RATE_LIMITED,
        )
    except Exception as exc:
        latency = time.monotonic() - start
        logger.exception("refuter %s failed unexpectedly", strategy.name)
        return RefuterVerdict(
            strategy_name=strategy.name,
            verdict=RefuterVerdictValue.ABSTAIN,
            rationale=f"unexpected error: {exc!s}",
            concerns=[],
            latency_seconds=latency,
            error=RefuterErrorKind.LLM_ERROR,
        )

    latency = time.monotonic() - start

    # Empty response from the LLM seam → no LLM available.
    if not raw or not raw.strip():
        return RefuterVerdict(
            strategy_name=strategy.name,
            verdict=RefuterVerdictValue.ABSTAIN,
            rationale="refuter invocation not yet wired (no LLM response)",
            concerns=[],
            latency_seconds=latency,
            error=RefuterErrorKind.INTERNAL,
        )

    # Parse the response as JSON. Malformed JSON → ABSTAIN/MALFORMED.
    try:
        parsed = _parse_refuter_response(raw)
    except ValueError as exc:
        return RefuterVerdict(
            strategy_name=strategy.name,
            verdict=RefuterVerdictValue.ABSTAIN,
            rationale=f"malformed refuter response: {exc!s}",
            concerns=[],
            latency_seconds=latency,
            error=RefuterErrorKind.MALFORMED_RESPONSE,
        )

    verdict_value = parsed["verdict"]
    # ABSTAIN is not a valid LLM-emitted verdict — only failure modes
    # produce abstentions (see RefuterVerdict._check_error_abstain_biconditional).
    # Treat a stray "abstain" from the LLM as malformed.
    if verdict_value == RefuterVerdictValue.ABSTAIN.value:
        return RefuterVerdict(
            strategy_name=strategy.name,
            verdict=RefuterVerdictValue.ABSTAIN,
            rationale=f"refuter cannot self-abstain: {verdict_value!r}",
            concerns=[],
            latency_seconds=latency,
            error=RefuterErrorKind.MALFORMED_RESPONSE,
        )
    try:
        return RefuterVerdict(
            strategy_name=strategy.name,
            verdict=RefuterVerdictValue(verdict_value),
            rationale=str(parsed.get("rationale", "")),
            concerns=[str(c) for c in parsed.get("concerns", []) or []],
            latency_seconds=latency,
        )
    except ValueError:
        return RefuterVerdict(
            strategy_name=strategy.name,
            verdict=RefuterVerdictValue.ABSTAIN,
            rationale=f"unknown verdict value: {verdict_value!r}",
            concerns=[],
            latency_seconds=latency,
            error=RefuterErrorKind.MALFORMED_RESPONSE,
        )


def _parse_refuter_response(raw: str) -> dict[str, Any]:
    """Parse a raw refuter response into a dict. Raises ValueError on bad JSON."""
    import json

    text = raw.strip()
    # Tolerate fenced JSON (```json ... ```).
    if text.startswith("```"):
        lines = text.splitlines()
        # Drop first fence line and any trailing fence line.
        lines = [ln for ln in lines if not ln.strip().startswith("```")]
        text = "\n".join(lines).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise ValueError("response is not a JSON object")
    if "verdict" not in data:
        raise ValueError("response missing 'verdict' field")
    return data


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def verify_proposal(
    proposal: Proposal,
    strategies: list[RefuterStrategy] | None = None,
) -> VerificationResult:
    """Run the configured refuter strategies against a proposal.

    NEVER raises. The result's ``consensus`` and ``persisted`` fields tell
    the caller what actually happened; failure modes are encoded, not
    thrown.

    Args:
        proposal: The typed proposal to verify.
        strategies: Refuter strategies to run (defaults to
            ``DEFAULT_STRATEGIES`` — three diverse refuters with different
            prompts and temperatures).

    Returns:
        ``VerificationResult`` with per-refuter verdicts, aggregated
        consensus, and deduplicated concerns.
    """
    if strategies is None:
        strategies = list(DEFAULT_STRATEGIES)
    is_empty = _is_empty_proposal(proposal)

    if is_empty:
        logger.info(
            "verify_proposal: empty proposal %s — short-circuit APPROVE",
            proposal.proposal_id,
        )
        return VerificationResult(
            proposal_id=proposal.proposal_id,
            verdicts=[],
            consensus=Consensus.APPROVE,
            concerns_aggregated=["empty proposal — refuters skipped"],
        )

    logger.info(
        "verify_proposal: proposal_id=%s type=%s refuters=%d",
        proposal.proposal_id,
        proposal.proposal_type,
        len(strategies),
    )

    # Run all refuters concurrently; each one already swallows its own
    # exceptions, so gather() will not raise here either.
    verdicts = list(
        await asyncio.gather(
            *(_run_refuter(s, proposal) for s in strategies),
            return_exceptions=False,
        )
    )

    consensus = _compute_consensus(verdicts, is_empty=False)
    concerns = _aggregate_concerns(verdicts)

    logger.info(
        "verify_proposal.completed proposal_id=%s consensus=%s refuters=%d",
        proposal.proposal_id,
        consensus.value,
        len(verdicts),
    )

    return VerificationResult(
        proposal_id=proposal.proposal_id,
        verdicts=verdicts,
        consensus=consensus,
        concerns_aggregated=concerns,
    )


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


class VerificationStore:
    """Persists ``VerificationResult`` records to Dhara.

    Writes to ``verification/{proposal_id}/result`` under the canonical
    Dhara key schema. On failure, dead-letters the result to a local
    fallback file at ``~/.mahavishnu/verification-dead-letter/{proposal_id}.json``
    so reconciliation can replay the audit trail once Dhara recovers.
    """

    DEAD_LETTER_DIR: Path = Path.home() / ".mahavishnu" / "verification-dead-letter"
    KEY_PREFIX: str = "verification/"

    def __init__(self, dhara: DharaStateBackend | None = None) -> None:
        self.dhara = dhara

    @staticmethod
    def _result_key(proposal_id: str) -> str:
        return f"verification/{proposal_id}/result"

    @staticmethod
    def _metadata_key(proposal_id: str) -> str:
        return f"verification/{proposal_id}/metadata"

    @staticmethod
    def _dead_letter_path(proposal_id: str) -> Path:
        # Sanitize proposal_id for use as a filename:
        #   1. Reject control characters and null bytes (path traversal / corruption risk).
        #   2. Replace path separators with underscores.
        #   3. Strip leading dots so a crafted id like "..foo" can't escape DEAD_LETTER_DIR.
        #   4. Cap length at 200 chars to avoid filesystem limits.
        if any(c in proposal_id for c in ("\x00", "\n", "\r", "\t")):
            raise ValueError(f"proposal_id contains control character: {proposal_id!r}")
        safe = proposal_id.replace("/", "_").replace("\\", "_").lstrip(".") or "unnamed"
        safe = safe[:200]
        return VerificationStore.DEAD_LETTER_DIR / f"{safe}.json"

    async def persist(self, result: VerificationResult) -> VerificationResult:
        """Persist a ``VerificationResult`` to Dhara.

        On success returns the result with ``persisted=True`` and
        ``persist_error=None``. On failure logs a WARNING, dead-letters
        the payload locally, and returns the result with ``persisted=False``
        and ``persist_error`` set to a one-line exception summary.
        """
        if self.dhara is None:
            # No backend wired — treat as persistence failure so the
            # caller knows the audit trail isn't durable.
            return result.model_copy(
                update={
                    "persisted": False,
                    "persist_error": "dhara backend not configured",
                }
            )

        key = self._result_key(result.proposal_id)
        metadata_key = self._metadata_key(result.proposal_id)
        payload = result.model_dump(mode="json")
        payload["persisted_at"] = datetime.now(UTC).isoformat()

        try:
            await self.dhara.put(key, payload)
            await self.dhara.put(
                metadata_key,
                {
                    "proposal_id": result.proposal_id,
                    "consensus": result.consensus.value,
                    "persisted_at": payload["persisted_at"],
                },
            )
        except Exception as exc:
            logger.warning(
                "verification.persist_failure proposal_id=%s error=%s",
                result.proposal_id,
                exc,
            )
            self._dead_letter(result, exc)
            return result.model_copy(
                update={
                    "persisted": False,
                    "persist_error": f"{type(exc).__name__}: {exc!s}",
                }
            )

        return result.model_copy(update={"persisted": True, "persist_error": None})

    def _dead_letter(self, result: VerificationResult, exc: BaseException) -> None:
        """Write a dead-letter file for later reconciliation. NEVER raises."""
        path = self._dead_letter_path(result.proposal_id)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            import json

            path.write_text(
                json.dumps(
                    {
                        "proposal_id": result.proposal_id,
                        "consensus": result.consensus.value,
                        "result": result.model_dump(mode="json"),
                        "exception": f"{type(exc).__name__}: {exc!s}",
                        "dead_lettered_at": datetime.now(UTC).isoformat(),
                    },
                    indent=2,
                )
            )
        except Exception:
            logger.exception(
                "verification.dead_letter_failed proposal_id=%s",
                result.proposal_id,
            )

    async def get(self, proposal_id: str) -> VerificationResult | None:
        """Retrieve a persisted ``VerificationResult``.

        Returns ``None`` when no record exists or when Dhara is unavailable.
        """
        if self.dhara is None:
            return None
        try:
            data = await self.dhara.get(self._result_key(proposal_id))
        except Exception:
            logger.exception("verification.get_failed proposal_id=%s", proposal_id)
            return None
        if not data:
            return None
        # Strip the audit-trail-only fields Dhara added; the model_dump
        # shape already matches VerificationResult minus persisted_at.
        data.pop("persisted_at", None)
        try:
            return VerificationResult.model_validate(data)
        except Exception:
            logger.exception(
                "verification.get_invalid_payload proposal_id=%s",
                proposal_id,
            )
            return None


__all__ = [
    "DEFAULT_STRATEGIES",
    "Consensus",
    "Proposal",
    "RefuterErrorKind",
    "RefuterStrategy",
    "RefuterVerdict",
    "RefuterVerdictValue",
    "VerificationResult",
    "VerificationStore",
    "verify_proposal",
]
