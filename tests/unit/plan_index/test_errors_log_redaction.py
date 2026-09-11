"""Round-2 BLOCKER: errors.log MUST NOT contain raw paths, repos, or URLs.

REQ-PLAN-012: errors_log_path() lines must contain only path_hash (sha256[:12]),
never raw path or repo. The TypedDict schema for ctx forbids keys called
`path` or `repo`. Lines matching `/Users/`, `/docs/`, `github.com/`, or any
URL-shaped string are forbidden.

Round-3 fix: the test drives failure through cron_core.run_rebuild_cycle
rather than calling rebuilder.upsert_all directly, because the actual
errors.log writer lives inside run_rebuild_cycle (called only by the
cron loop in production). Calling upsert_all in isolation never appends
to errors.log, so the previous test trivially passed against an empty
file. This version mocks the inner rebuilder + discover_records so
run_rebuild_cycle emits a deliberate partial failure.
"""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any
from unittest.mock import AsyncMock

import pytest

from mahavishnu.plan_index import cron_core
from mahavishnu.plan_index.cron_core import run_rebuild_cycle
from mahavishnu.plan_index.paths import errors_log_path
from mahavishnu.plan_index.rebuild import PlanIndexRebuilder
from mahavishnu.plan_index.store import PlanIndexStore
from mahavishnu.plan_index.testing import FakeDhara


class TestErrorsLogRedaction:
    @pytest.mark.asyncio
    async def test_no_raw_paths_in_errors_log(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Drive a partial-failure cycle through cron_core and assert the
        resulting errors.log contains no /Users/, /docs/, github.com/, or
        http(s):// substrings. Forces failure via a mocked upsert_all return.
        """
        monkeypatch.setenv("HOME", str(tmp_path))

        store = PlanIndexStore(FakeDhara())  # type: ignore[arg-type]
        rebuilder = PlanIndexRebuilder()

        async def _fake_discover(repo_root: Path | None) -> list[Any]:
            return []

        monkeypatch.setattr(cron_core, "discover_records", _fake_discover)

        # Mock rebuilder.upsert_all to return a partial failure with a single
        # ctx dict carrying path_hash (12 hex chars) and NO raw path/repo keys.
        # If redaction regresses, this ctx WILL leak /Users/... into errors.log.
        rebuilder.upsert_all = AsyncMock(  # type: ignore[method-assign]
            return_value=(
                1,
                1,
                [{"path_hash": "abc123def456", "op": "normalize", "plan_id": "f" * 32}],
            )
        )

        # repo_root value is deliberately /Users/.../docs/... so any leak is visible.
        await run_rebuild_cycle(store, rebuilder, repo_root=Path("/Users/fake/docs/plan"))

        log = errors_log_path().read_text()
        forbidden_substrings = ("/Users/", "/docs/", "github.com/", "http://", "https://")
        for needle in forbidden_substrings:
            assert needle not in log, f"errors.log contains forbidden substring: {needle!r}"

    @pytest.mark.asyncio
    async def test_errors_log_lines_use_path_hash_only(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Every errors.log line must reference a path_hash (12 hex chars)
        and an `err` field, and must NOT carry a raw `path` or `repo` key.
        """
        monkeypatch.setenv("HOME", str(tmp_path))

        store = PlanIndexStore(FakeDhara())  # type: ignore[arg-type]
        rebuilder = PlanIndexRebuilder()

        async def _fake_discover(repo_root: Path | None) -> list[Any]:
            return []

        monkeypatch.setattr(cron_core, "discover_records", _fake_discover)

        rebuilder.upsert_all = AsyncMock(  # type: ignore[method-assign]
            return_value=(
                1,
                2,
                [
                    {
                        "path_hash": "deadbeef0001",
                        "op": "normalize",
                        "err": "control character in repo",
                        "plan_id": "a" * 32,
                    },
                    {
                        "path_hash": "deadbeef0002",
                        "op": "upsert",
                        "err": "dhara conflict",
                        "plan_id": "b" * 32,
                    },
                ],
            )
        )

        await run_rebuild_cycle(store, rebuilder, repo_root=Path("/Users/fake/docs/plan"))

        log = errors_log_path().read_text()
        # Pull out every "err": {...} payload dict and validate its schema.
        err_payloads = re.findall(r'"err": (\{[^{}]*\})', log)
        assert err_payloads, "errors.log must contain at least one err payload block"
        for payload in err_payloads:
            assert re.search(r'"path_hash": "[a-f0-9]{12}"', payload), (
                f"errors.log err payload missing 12-hex path_hash: {payload}"
            )
            assert re.search(r'"err": "[^"]+"', payload), (
                f"errors.log err payload missing err field: {payload}"
            )
            assert '"path":' not in payload, (
                f"errors.log err payload carries raw 'path' key: {payload}"
            )
            assert '"repo":' not in payload, (
                f"errors.log err payload carries raw 'repo' key: {payload}"
            )
