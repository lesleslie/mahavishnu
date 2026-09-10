from __future__ import annotations

from typing import TYPE_CHECKING

from mahavishnu.plan_index.render import render

if TYPE_CHECKING:
    from mahavishnu.plan_index.types import PlanRecordDict


def _sample(plan_id: str = "1" * 32) -> PlanRecordDict:
    return {
        "plan_id": plan_id,
        "path": f"docs/plans/{plan_id[:8]}.md",
        "title": f"Plan {plan_id[:4]}",
        "status": "active",
        "role": "implementation",
        "topic": "routing-composition",
        "date": "2026-09-15",
        "last_reviewed": "2026-09-15",
        "superseded_by": None,
        "blocks_on": [],
        "sha": "f" * 40,
        "repo": "github.com/example/repo",
        "updated_at_ms": 1700000000000,
    }


class TestRenderer:
    def test_empty_records(self) -> None:
        out = render([])
        assert "Plan Index" in out  # header present
        assert "No plans indexed." in out

    def test_single_record(self) -> None:
        out = render([_sample("a" * 32)])
        assert "Plan aaaa" in out
        assert "active" in out
        assert "implementation" in out

    def test_staleness_header_present(self) -> None:
        out = render([_sample("b" * 32)])
        # The staleness-header comment is emitted by the renderer
        assert "<!-- Last regenerated:" in out
        assert "mcp__mahavishnu__plan_rebuild_status" in out

    def test_groups_by_store(self) -> None:
        out = render([_sample("c" * 32), _sample("d" * 32)])
        # Each record produces a row under a section heading
        assert "## " in out  # markdown heading
        assert out.count("| ") >= 2  # table rows
