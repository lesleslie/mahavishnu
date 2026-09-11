"""Snapshot test against the golden render file.

Per spec §Read paths and the round-2 golden workflow, the new renderer's
output must match the existing PLAN_INDEX.md structure. The first run
(test_golden_first_run.py) creates the golden; subsequent runs diff.
"""

# REQ-PLAN-019: render output matches the legacy scanner

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from mahavishnu.plan_index.render import render

if TYPE_CHECKING:
    from mahavishnu.plan_index.types import PlanRecordDict


class TestRenderMatchesOldScanner:
    def test_render_matches_golden(self) -> None:
        golden_path = (
            Path(__file__).parent / "fixtures" / "PLAN_INDEX.golden.md"
        )
        if not golden_path.exists():
            pytest.skip(
                "Golden file not yet created; "
                "run test_golden_first_run.py first"
            )
        golden = golden_path.read_text()

        rec: PlanRecordDict = {
            "plan_id": "0" * 32,
            "path": "docs/plans/sample-plan.md",
            "title": "Sample Plan",
            "status": "active",
            "role": "implementation",
            "topic": "sample-topic",
            "date": "2026-09-15",
            "last_reviewed": "2026-09-15",
            "superseded_by": None,
            "blocks_on": [],
            "sha": "0" * 40,
            "repo": "github.com/example/repo",
            "updated_at_ms": 1700000000000,
        }
        rendered = render([rec])

        # Round-3 fix: normalize the regenerated-timestamp via regex (same
        # scheme as test_golden_first_run.py) so the diff is independent
        # of which line index the label lands at.
        import re

        def _normalize(ts_text: str) -> str:
            text = re.sub(
                r"\*\*Last regenerated:\*\* .* UTC",
                "**Last regenerated:** <STABLE> UTC",
                ts_text,
            )
            text = re.sub(
                r"(<!-- Last regenerated: )[^<]+( UTC .* -->)",
                r"\1<STABLE>\2",
                text,
            )
            return text

        assert _normalize(rendered) == _normalize(golden)
