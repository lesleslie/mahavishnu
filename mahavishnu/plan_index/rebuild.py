"""PlanIndexRebuilder — pure function from PlanRecord list to upserts.

Almost-pure: the only I/O boundary is the injected sha_provider (called once
per record during upsert to fetch the git blob SHA). Tests inject a fake.

REQ-PLAN-011: normalize_repo_url runs BEFORE plan_id derivation.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
import hashlib
from pathlib import Path
from typing import TYPE_CHECKING, Final

from mahavishnu.plan_index import PlanId
from mahavishnu.plan_index.url import RepoUrlRejectedError, normalize_repo_url

if TYPE_CHECKING:
    from mahavishnu.plan_index.record import PlanRecord
    from mahavishnu.plan_index.store import PlanIndexStore
    from mahavishnu.plan_index.types import RebuildErrorCtx

__all__ = ["PlanIndexRebuilder"]

ShaProvider = Callable[[Path], str]
PLAN_ID_LEN: Final[int] = 32
DEFAULT_SHA: Final[str] = "0" * 40
PATH_HASH_LEN: Final[int] = 12


class PlanIndexRebuilder:
    """Pure function: list[PlanRecord] → upserts via store."""

    def __init__(self, *, sha_provider: ShaProvider | None = None) -> None:
        self._sha_provider: ShaProvider = sha_provider or (lambda _p: DEFAULT_SHA)

    def derive_plan_id(self, repo: str, path: str) -> PlanId:
        """Derive plan_id from NORMALIZED repo + path.

        Normalizes the repo internally (REQ-PLAN-011). Raises if the
        raw repo URL is rejected by normalize_repo_url — better to fail
        fast at the boundary than to silently let an unnormalized URL
        pollute the id space.

        The repo parameter is documented as already-normalized for
        callers that have pre-normalized (e.g., from `upsert_all`);
        for callers that have not, the function transparently
        normalizes.
        """
        normalized = normalize_repo_url(repo)
        if normalized is None:
            raise ValueError(f"cannot normalize repo for plan_id: {repo!r}")
        composite = f"{normalized}:{path}"
        h = hashlib.sha256(composite.encode()).hexdigest()[:PLAN_ID_LEN]
        return PlanId(h)

    async def upsert_all(
        self,
        records: list[PlanRecord],
        store: PlanIndexStore,
    ) -> tuple[int, int, list[RebuildErrorCtx]]:
        """Upsert all records. Returns (success_count, error_count, errors).

        Errors are accumulated in `errors` with path_hash only (never raw
        path). Failures are non-fatal — the rebuilder continues with the
        remaining records.
        """
        success = 0
        error_count = 0
        errors: list[RebuildErrorCtx] = []
        for record in records:
            path_hash = hashlib.sha256(record.path.encode()).hexdigest()[:PATH_HASH_LEN]
            try:
                try:
                    normalized = normalize_repo_url(record.repo, raise_on_reject=True)
                except RepoUrlRejectedError:
                    # normalize_repo_url with raise_on_reject=True signals rejection
                    # via this exception; the static type signature still says
                    # str | None, so defensively check for None before use.
                    errors.append({
                        "path_hash": path_hash,
                        "op": "normalize",
                        "plan_id": record.plan_id,
                    })
                    error_count += 1
                    continue
                if normalized is None:
                    errors.append({
                        "path_hash": path_hash,
                        "op": "normalize",
                        "plan_id": record.plan_id,
                    })
                    error_count += 1
                    continue
                normalized_record = replace(record, repo=normalized)
                await store.upsert(normalized_record)
                success += 1
            except Exception:  # noqa: BLE001 — fail-soft per spec §Error handling
                errors.append({
                    "path_hash": path_hash,
                    "plan_id": record.plan_id,
                    "op": "upsert",
                })
                error_count += 1
        return success, error_count, errors
