"""Tests for scripts/audit_plan_index.py — the three-way drift check."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

from scripts.audit_plan_index import (
    AuditReport,
    audit,
    collect_dhara_paths,
    dhara_paths_from_records,
    extract_index_paths,
    format_report,
    main,
    scan_disk_paths,
)

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit


RENDERED_INDEX = """\
# Plan Index

| Date | Path | Title | Status | Role | Topic | Plan ID |
|---|---|---|---|---|---|---|
| 2026-09-10 | docs/plans/alpha.md | Alpha | active | canonical | x | `abcd1234` |
| 2026-09-09 | docs/plans/beta.md | Beta | shipped | canonical | y | `beef5678` |
"""

LEGACY_INDEX = """\
# Plan Index

| Path | Date | Status | Role | Topic | Title |
|---|---|---|---|---|---|
| [`docs/plans/alpha.md`](alpha.md) | 2026-09-10 | `active` | `canonical` | `x` | Alpha |
| [`docs/plans/beta.md`](beta.md) | 2026-09-09 | `shipped` | `canonical` | `y` | Beta |
"""


def _plan_body(title: str, date: str = "2026-09-10") -> str:
    return (
        "---\n"
        "status: active\n"
        "role: canonical\n"
        f"date: {date}\n"
        f"last_reviewed: {date}\n"
        "superseded_by: null\n"
        "topic: audit-fixture\n"
        "---\n"
        "\n"
        f"# {title}\n"
    )


def _make_repo(tmp_path: Path, *, plans: dict[str, str], index_text: str) -> Path:
    plans_dir = tmp_path / "docs" / "plans"
    plans_dir.mkdir(parents=True)
    for name, title in plans.items():
        (plans_dir / name).write_text(_plan_body(title))
    (plans_dir / "PLAN_INDEX.md").write_text(index_text)
    return tmp_path


# --------------------------------------------------------------------------
# extract_index_paths
# --------------------------------------------------------------------------


def test_extract_index_paths_reads_rendered_rows() -> None:
    assert extract_index_paths(RENDERED_INDEX) == {
        "docs/plans/alpha.md",
        "docs/plans/beta.md",
    }


def test_extract_index_paths_reads_legacy_link_rows() -> None:
    assert extract_index_paths(LEGACY_INDEX) == {
        "docs/plans/alpha.md",
        "docs/plans/beta.md",
    }


def test_extract_index_paths_ignores_prose_and_separators() -> None:
    text = "# Heading\n\nSome prose about docs/plans/ghost.md\n\n|---|---|\n"
    assert extract_index_paths(text) == set()


# --------------------------------------------------------------------------
# audit (pure comparison)
# --------------------------------------------------------------------------


def test_audit_reports_ok_when_index_and_disk_agree() -> None:
    report = audit({"a.md"}, {"a.md"})
    assert report.ok
    assert report.failures == 0
    assert report.index_count == 1
    assert report.dhara_checked is False


def test_audit_flags_index_entry_missing_from_disk() -> None:
    report = audit({"a.md", "gone.md"}, {"a.md"})
    assert not report.ok
    assert report.in_index_only == frozenset({"gone.md"})


def test_audit_flags_disk_file_missing_from_index() -> None:
    report = audit({"a.md"}, {"a.md", "new.md"})
    assert not report.ok
    assert report.in_disk_only == frozenset({"new.md"})


def test_audit_flags_dhara_record_missing_from_index() -> None:
    report = audit({"a.md"}, {"a.md"}, {"a.md", "orphan.md"})
    assert not report.ok
    assert report.in_dhara_only == frozenset({"orphan.md"})
    assert report.dhara_checked is True


def test_audit_treats_index_without_dhara_record_as_warning_only() -> None:
    report = audit({"a.md", "b.md"}, {"a.md", "b.md"}, {"a.md"})
    assert report.ok
    assert report.missing_from_dhara == frozenset({"b.md"})


def test_audit_three_way_clean_marks_dhara_checked() -> None:
    report = audit({"a.md"}, {"a.md"}, {"a.md"})
    assert report.ok
    assert report.dhara_checked is True
    assert report.missing_from_dhara == frozenset()


# --------------------------------------------------------------------------
# format_report
# --------------------------------------------------------------------------


def test_format_report_notes_unchecked_dhara_leg() -> None:
    lines = format_report(audit({"a.md"}, {"a.md"}))
    assert any("Dhara leg not checked" in line for line in lines.out)
    assert lines.err == []


def test_format_report_omits_caveat_when_dhara_checked() -> None:
    lines = format_report(audit({"a.md"}, {"a.md"}, {"a.md"}))
    assert any(line.startswith("OK:") for line in lines.out)
    assert not any("not checked" in line for line in lines.out)


def test_format_report_truncates_long_failure_lists() -> None:
    many = {f"docs/plans/p{i}.md" for i in range(25)}
    lines = format_report(audit(many, set()))
    assert any("and 15 more" in line for line in lines.err)


def test_format_report_emits_warning_for_missing_dhara_records() -> None:
    lines = format_report(audit({"a.md"}, {"a.md"}, set()))
    assert any(line.startswith("WARN:") for line in lines.out)


# --------------------------------------------------------------------------
# Dhara adapters
# --------------------------------------------------------------------------


def test_dhara_paths_from_records_skips_malformed_entries() -> None:
    records: list[dict[str, Any]] = [
        {"path": "docs/plans/a.md"},
        {"path": ""},
        {"path": None},
        {"no_path": 1},
    ]
    assert dhara_paths_from_records(records) == {"docs/plans/a.md"}


async def test_collect_dhara_paths_uses_public_store_api() -> None:
    class _Store:
        def __init__(self) -> None:
            self.limit: int | None = None

        async def list_all(self, *, limit: int = 1000) -> list[dict[str, str]]:
            self.limit = limit
            return [{"path": "docs/plans/a.md"}, {"path": "docs/plans/b.md"}]

    store = _Store()
    assert await collect_dhara_paths(store, limit=7) == {
        "docs/plans/a.md",
        "docs/plans/b.md",
    }
    assert store.limit == 7


# --------------------------------------------------------------------------
# scan_disk_paths + main (end-to-end over a temp repo)
# --------------------------------------------------------------------------


def test_scan_disk_paths_finds_frontmattered_plans(tmp_path: Path) -> None:
    repo = _make_repo(
        tmp_path,
        plans={"alpha.md": "Alpha", "beta.md": "Beta", "gamma.md": "Gamma"},
        index_text=RENDERED_INDEX,
    )
    found = scan_disk_paths(repo)
    assert "docs/plans/alpha.md" in found
    assert "docs/plans/gamma.md" in found


def test_scan_disk_paths_includes_nested_store_files(tmp_path: Path) -> None:
    """A nested store owns its own files.

    Regression: skipping every *other* store (rather than only the ones
    nested under the current store) made a parent store's prefix swallow
    the nested store's files, so they silently vanished from the audit.
    """
    repo = _make_repo(
        tmp_path,
        plans={"alpha.md": "Alpha", "beta.md": "Beta"},
        index_text=RENDERED_INDEX,
    )
    nested = repo / "docs" / "plans" / "initiatives"
    nested.mkdir()
    (nested / "one.md").write_text(_plan_body("One"))
    (nested / "two.md").write_text(_plan_body("Two"))

    found = scan_disk_paths(repo)
    assert "docs/plans/alpha.md" in found
    assert "docs/plans/initiatives/one.md" in found
    assert "docs/plans/initiatives/two.md" in found


def test_main_returns_zero_when_consistent(tmp_path: Path) -> None:
    index = (
        RENDERED_INDEX
        + "| 2026-09-08 | docs/plans/gamma.md | G | active | canonical | z | `c0ffee00` |\n"
    )
    repo = _make_repo(
        tmp_path,
        plans={"alpha.md": "Alpha", "beta.md": "Beta", "gamma.md": "Gamma"},
        index_text=index,
    )
    assert main(["--repo-root", str(repo)]) == 0


def test_main_returns_one_when_disk_file_missing_from_index(tmp_path: Path) -> None:
    repo = _make_repo(
        tmp_path,
        plans={"alpha.md": "Alpha", "beta.md": "Beta", "gamma.md": "Gamma"},
        index_text=RENDERED_INDEX,
    )
    assert main(["--repo-root", str(repo)]) == 1


def test_main_returns_one_when_index_missing(tmp_path: Path) -> None:
    assert main(["--repo-root", str(tmp_path)]) == 1


def test_main_reads_dhara_records_from_json(tmp_path: Path) -> None:
    repo = _make_repo(
        tmp_path,
        plans={"alpha.md": "Alpha", "beta.md": "Beta", "gamma.md": "Gamma"},
        index_text=RENDERED_INDEX,
    )
    records = repo / "records.json"
    records.write_text(json.dumps({"records": [{"path": "docs/plans/orphan.md"}]}))
    assert main(["--repo-root", str(repo), "--dhara-records", str(records)]) == 1


def test_audit_report_defaults_are_empty() -> None:
    report = AuditReport()
    assert report.ok
    assert report.index_count == 0
