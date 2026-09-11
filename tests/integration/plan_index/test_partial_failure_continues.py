"""Inject a record whose normalize_repo_url rejects; the rebuilder
records the error (path_hash only) and continues with the next record.

Per spec §Error handling (REQ-PLAN-012), errors are non-fatal and the
errors list contains path_hash but NEVER the raw path or repo.
"""

# REQ-PLAN-012: errors.log contains only path_hash, never raw path/repo

from __future__ import annotations

import pytest

from mahavishnu.plan_index.rebuild import PlanIndexRebuilder
from mahavishnu.plan_index.record import PlanRecord
from mahavishnu.plan_index.store import PlanIndexStore
from mahavishnu.plan_index.testing import FakeDhara


def _bad_record() -> PlanRecord:
    return PlanRecord(
        plan_id="b" * 32,
        path="docs/plans/bad.md",
        title="Bad",
        status="active",
        role="implementation",
        topic="t",
        date="2026-09-15",
        last_reviewed="2026-09-15",
        superseded_by=None,
        blocks_on=[],
        sha="f" * 40,
        repo="not-a-url-at-all",  # normalize_repo_url returns None → rejected
        updated_at_ms=1700000000000,
    )


def _good_record() -> PlanRecord:
    return PlanRecord(
        plan_id="a" * 32,
        path="docs/plans/good.md",
        title="Good",
        status="active",
        role="implementation",
        topic="t",
        date="2026-09-15",
        last_reviewed="2026-09-15",
        superseded_by=None,
        blocks_on=[],
        sha="f" * 40,
        # Brief defect fix: the original brief specified
        # `repo="github.com/example/repo"` which is the NORMALIZED form
        # (host/path). normalize_repo_url requires canonical INPUT forms
        # (git@/https?/ssh:// prefix). Use the canonical form so the
        # good record actually passes through.
        repo="https://github.com/example/repo.git",
        updated_at_ms=1700000000000,
    )


class TestPartialFailureContinues:
    @pytest.mark.asyncio
    async def test_bad_record_logged_good_record_succeeds(self) -> None:
        store = PlanIndexStore(FakeDhara())  # type: ignore[arg-type]
        rb = PlanIndexRebuilder()
        success, errors_count, errors = await rb.upsert_all(
            [_bad_record(), _good_record()], store
        )
        assert success == 1
        assert errors_count == 1
        assert len(errors) == 1
        # Error has path_hash only, never raw path or repo
        err = errors[0]
        assert "path_hash" in err
        assert "path" not in err
        assert "repo" not in err
        assert "not-a-url-at-all" not in str(err)  # raw repo NOT leaked
