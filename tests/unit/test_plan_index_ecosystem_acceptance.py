"""Tests for the generated ecosystem acceptance section."""

from __future__ import annotations

from scripts.regenerate_plan_index import Entry, _render_ecosystem_acceptance


def _entry(path: str, status: str) -> Entry:
    return Entry(
        rel=path,
        store="docs/plans/",
        date="2026-11-10",
        status=status,
        role="implementation",
        kind="plan",
        topic="ecosystem",
        title=path.rsplit("/", maxsplit=1)[-1],
    )


def test_acceptance_section_derives_owner_and_supporting_statuses() -> None:
    entries = {
        "docs/plans/2026-11-01-control-plane-consolidation.md": _entry(
            "docs/plans/2026-11-01-control-plane-consolidation.md", "partial"
        ),
        "docs/plans/2026-10-30-task-workflow-backlink.md": _entry(
            "docs/plans/2026-10-30-task-workflow-backlink.md", "partial"
        ),
        "docs/plans/2026-11-07-mcp-tool-disambiguation.md": _entry(
            "docs/plans/2026-11-07-mcp-tool-disambiguation.md", "active"
        ),
        "docs/plans/2026-11-05-config-that-nobody-reads.md": _entry(
            "docs/plans/2026-11-05-config-that-nobody-reads.md", "active"
        ),
        "docs/specs/2026-10-20-bodai-otel-substrate-read-path.md": _entry(
            "docs/specs/2026-10-20-bodai-otel-substrate-read-path.md", "active"
        ),
    }

    rendered = _render_ecosystem_acceptance(entries)
    rendered_again = _render_ecosystem_acceptance(dict(reversed(list(entries.items()))))

    assert "## Ecosystem Acceptance Status" in rendered
    assert "Golden workflow provenance" in rendered
    assert "`partial`" in rendered
    assert "2026-10-30-task-workflow-backlink.md" in rendered
    assert "../../docs/specs/2026-10-20-bodai-otel-substrate-read-path.md" in rendered
    assert "(missing)" in rendered
    assert "Required evidence" in rendered
    assert rendered == rendered_again
