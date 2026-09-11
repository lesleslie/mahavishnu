"""First-run golden creation.

Distinct from test_render_matches_old_scanner: this test WRITES the
golden file (with a fixed timestamp placeholder) the first time it's
invoked. Subsequent runs diff the renderer's output against the
committed golden. CI guard: the golden file MUST be present before
the diff test can run.
"""

# REQ-PLAN-019: golden workflow supports first-run creation + diff

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from mahavishnu.plan_index.render import render

if TYPE_CHECKING:
    from mahavishnu.plan_index.types import PlanRecordDict


class TestGoldenFirstRun:
    def test_first_run_creates_golden(self) -> None:
        """First invocation creates the golden file; doesn't fail."""
        golden_path = (
            Path(__file__).parent / "fixtures" / "PLAN_INDEX.golden.md"
        )
        if golden_path.exists():
            pytest.skip("Golden already exists; nothing to do on first run")

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

        # Round-3 fix: target the `**Last regenerated:** ... UTC` line by
        # regex so the golden-normalization is independent of which line
        # index the label happens to land at in render()'s output. The
        # previous line-index write (lines[3] = ...) was wrong by two
        # lines and produced a corrupted golden that broke the diff test.
        import re  # local import keeps the top-of-file imports pristine

        content = rendered
        # (a) Replace the in-body `**Last regenerated:**` metadata line.
        content = re.sub(
            r"\*\*Last regenerated:\*\* .* UTC",
            "**Last regenerated:** <STABLE> UTC",
            content,
        )
        # (b) Replace the HTML-comment staleness-header timestamp variant
        # that render() emits at the very top of the document.
        content = re.sub(
            r"(<!-- Last regenerated: )[^<]+( UTC .* -->)",
            r"\1<STABLE>\2",
            content,
        )
        golden_path.parent.mkdir(parents=True, exist_ok=True)
        golden_path.write_text(content)
        assert golden_path.exists()
