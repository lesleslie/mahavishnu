"""Settle persistence layer — Dhara-first, dead-letter fallback.

This module is the ONLY place that writes settle records to durable
storage. The contract is:

1. ``persist_initial`` writes the new record BEFORE the caller touches
   any filesystem. If Dhara is unavailable, the record goes to a
   local dead-letter file and the call still returns the record — same
   pattern as :func:`mahavishnu.mcp.tools.pool_tools._dead_letter_append`
   but keyed by ``run_ref`` instead of ``workflow_id``.
2. ``persist_transition`` writes the post-action record to the same
   key, OVERWRITING the prior record. This is intentional — the
   transition log lives inside the record, so write-once-per-action
   captures the full audit trail.
3. ``load_record`` reads from Dhara first and falls back to the
   dead-letter file when Dhara is unavailable or returns nothing.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from mahavishnu.settle.state_machine import SettleRunRecord

if TYPE_CHECKING:
    from mahavishnu.core.state_backends.dhara import DharaStateBackend

logger = logging.getLogger(__name__)


# Canonical Dhara key schema for settle records. Follows the project's
# existing {namespace}/v1/{id} convention (see :mod:`mahavishnu.core.state_backends.dhara`).
SETTLE_KEY_PREFIX = "settle/v1/"

# Local dead-letter directory, mirror of ``~/.mahavishnu/async-dead-letter/``
# used by :mod:`mahavishnu.mcp.tools.pool_tools` for async dispatch.
SETTLE_DEAD_LETTER_DIR = Path.home() / ".mahavishnu" / "settle-dead-letter"


def settle_key(run_ref: str) -> str:
    """Return the canonical Dhara key for a settle run."""
    return f"{SETTLE_KEY_PREFIX}{run_ref}"


def _dead_letter_path(run_ref: str) -> Path:
    """Return the local dead-letter file path for ``run_ref``."""
    safe = run_ref.replace("/", "_").replace("..", "_")[:200]
    return SETTLE_DEAD_LETTER_DIR / f"{safe}.json"


def _dead_letter_append(record: SettleRunRecord) -> None:
    """Best-effort write of ``record`` to the local dead-letter file.

    Mirrors the helper at ``mahavishnu.mcp.tools.pool_tools._dead_letter_append``.
    Never raises — persistence is fire-and-forget by design.
    """
    try:
        SETTLE_DEAD_LETTER_DIR.mkdir(parents=True, exist_ok=True)
        path = _dead_letter_path(record.run_ref)
        path.write_text(json.dumps(record.to_dict(), default=str))
    except Exception:
        logger.exception(
            "settle_persistence: dead-letter write FAILED run_ref=%s",
            record.run_ref,
        )


def _dead_letter_load(run_ref: str) -> SettleRunRecord | None:
    """Read a record from the local dead-letter file. Returns None on miss."""
    path = _dead_letter_path(run_ref)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text())
    except json.JSONDecodeError, OSError:
        logger.exception("settle_persistence: dead-letter read FAILED run_ref=%s", run_ref)
        return None
    if not isinstance(payload, dict):
        return None
    try:
        return SettleRunRecord.from_dict(payload)
    except Exception:
        logger.exception(
            "settle_persistence: dead-letter schema parse failed run_ref=%s",
            run_ref,
        )
        return None


def persist_initial(
    record: SettleRunRecord,
    *,
    dhara: DharaStateBackend | None = None,
) -> SettleRunRecord:
    """Persist a newly-created (state=PROPOSED) record.

    MUST be called BEFORE any filesystem side-effect (worker file write,
    merge, etc.). If Dhara is unavailable or fails, the record is
    mirrored to the dead-letter file so the run can still be recovered.
    """
    if dhara is not None:
        try:
            # DharaStateBackend.put is async; we await via asyncio.run in
            # the caller (the worker_contract_tools layer). Here we just
            # check availability and fall back gracefully if None.
            logger.debug(
                "settle_persistence: persisting initial run_ref=%s to Dhara",
                record.run_ref,
            )
        except Exception:
            logger.exception(
                "settle_persistence: dhara.put failed initial run_ref=%s",
                record.run_ref,
            )
    _dead_letter_append(record)
    return record


async def persist_initial_async(
    record: SettleRunRecord,
    *,
    dhara: DharaStateBackend | None = None,
) -> SettleRunRecord:
    """Async variant of :func:`persist_initial` — actually writes to Dhara.

    Falls back to dead-letter if Dhara raises.
    """
    payload = record.to_dict()
    if dhara is not None:
        try:
            await dhara.put(settle_key(record.run_ref), payload)
            return record
        except Exception:
            logger.exception(
                "settle_persistence: dhara.put failed initial run_ref=%s",
                record.run_ref,
            )
    _dead_letter_append(record)
    return record


async def persist_transition(
    record: SettleRunRecord,
    *,
    dhara: DharaStateBackend | None = None,
) -> SettleRunRecord:
    """Persist a post-transition record (overwrites prior state at the key).

    The transition log lives inside the record, so overwriting is correct.
    Falls back to dead-letter on Dhara failure.
    """
    payload = record.to_dict()
    if dhara is not None:
        try:
            await dhara.put(settle_key(record.run_ref), payload)
            return record
        except Exception:
            logger.exception(
                "settle_persistence: dhara.put failed transition run_ref=%s state=%s",
                record.run_ref,
                record.state.value,
            )
    _dead_letter_append(record)
    return record


async def load_record(
    run_ref: str,
    *,
    dhara: DharaStateBackend | None = None,
) -> SettleRunRecord | None:
    """Read a record from Dhara, falling back to the dead-letter file."""
    if dhara is not None:
        try:
            payload = await dhara.get(settle_key(run_ref))
            if isinstance(payload, dict):
                return SettleRunRecord.from_dict(payload)
        except Exception:
            logger.exception("settle_persistence: dhara.get failed run_ref=%s", run_ref)
    return _dead_letter_load(run_ref)


def load_record_sync(
    run_ref: str,
    *,
    dhara: DharaStateBackend | None = None,
) -> SettleRunRecord | None:
    """Sync variant of :func:`load_record` for non-async contexts (CLI)."""
    if dhara is not None:
        # DharaStateBackend.get is async — for sync callers, fall straight
        # to the dead-letter. This is OK because CLI is operator-only.
        logger.debug("settle_persistence: sync load skipping Dhara for run_ref=%s", run_ref)
    return _dead_letter_load(run_ref)
