"""Tests for scripts/check_step8_ready.py — the step-8 date/status gate."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import pytest

from scripts.check_step8_ready import compute_blockers, main, parse_date, parse_frontmatter

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit


def _tracking(tmp_path: Path, status: str) -> Path:
    path = tmp_path / "plan-index-dhara.md"
    path.write_text(
        "---\n"
        "name: plan-index-dhara\n"
        f"status: {status}\n"
        "date: 2026-09-10\n"
        "role: canonical\n"
        "---\n\n# Feature\n"
    )
    return path


def test_parse_date_accepts_iso() -> None:
    assert parse_date("2026-09-10") == date(2026, 9, 10)


@pytest.mark.parametrize("value", ["", None, "not-a-date", "10/09/2026"])
def test_parse_date_rejects_invalid(value: str | None) -> None:
    assert parse_date(value) is None


def test_parse_frontmatter_reads_status(tmp_path: Path) -> None:
    front = parse_frontmatter(_tracking(tmp_path, "adopted"))
    assert front is not None
    assert front["status"] == "adopted"


def test_parse_frontmatter_returns_none_without_fence(tmp_path: Path) -> None:
    path = tmp_path / "plain.md"
    path.write_text("# No frontmatter\n")
    assert parse_frontmatter(path) is None


def test_parse_frontmatter_returns_none_for_missing_file(tmp_path: Path) -> None:
    assert parse_frontmatter(tmp_path / "absent.md") is None


def test_parse_frontmatter_returns_none_for_unterminated_fence(tmp_path: Path) -> None:
    path = tmp_path / "broken.md"
    path.write_text("---\nstatus: adopted\n")
    assert parse_frontmatter(path) is None


def test_ready_when_grace_elapsed_and_adopted(tmp_path: Path) -> None:
    blockers = compute_blockers(
        today=date(2026, 10, 1),
        cutover_date="2026-09-10",
        jot_drain_ship_date="2026-09-01",
        feature_tracking=_tracking(tmp_path, "adopted"),
    )
    assert blockers == []


def test_blocked_when_cutover_grace_not_reached(tmp_path: Path) -> None:
    blockers = compute_blockers(
        today=date(2026, 9, 15),
        cutover_date="2026-09-10",
        jot_drain_ship_date=None,
        feature_tracking=_tracking(tmp_path, "adopted"),
    )
    assert any("cutover+14d" in b for b in blockers)


def test_blocked_when_jot_drain_grace_not_reached(tmp_path: Path) -> None:
    blockers = compute_blockers(
        today=date(2026, 10, 1),
        cutover_date="2026-09-10",
        jot_drain_ship_date="2026-09-25",
        feature_tracking=_tracking(tmp_path, "adopted"),
    )
    assert any("jot-drain+14d" in b for b in blockers)


def test_missing_jot_date_reduces_to_cutover_only(tmp_path: Path) -> None:
    blockers = compute_blockers(
        today=date(2026, 10, 1),
        cutover_date="2026-09-10",
        jot_drain_ship_date=None,
        feature_tracking=_tracking(tmp_path, "adopted"),
    )
    assert blockers == []


def test_blocked_when_cutover_unknown(tmp_path: Path) -> None:
    blockers = compute_blockers(
        today=date(2026, 10, 1),
        cutover_date=None,
        jot_drain_ship_date=None,
        feature_tracking=_tracking(tmp_path, "adopted"),
    )
    assert any("cutover date unknown" in b for b in blockers)


def test_blocked_when_status_not_adopted(tmp_path: Path) -> None:
    blockers = compute_blockers(
        today=date(2026, 10, 1),
        cutover_date="2026-09-10",
        jot_drain_ship_date=None,
        feature_tracking=_tracking(tmp_path, "built"),
    )
    assert any("status != adopted" in b for b in blockers)


def test_main_exits_one_when_blocked(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = main(
        [
            "--cutover-date",
            "2999-01-01",
            "--feature-tracking",
            str(_tracking(tmp_path, "built")),
        ]
    )
    assert code == 1
    assert "ready: no" in capsys.readouterr().out


def test_main_exits_zero_when_ready(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = main(
        [
            "--cutover-date",
            "2000-01-01",
            "--feature-tracking",
            str(_tracking(tmp_path, "adopted")),
        ]
    )
    assert code == 0
    assert "ready: yes" in capsys.readouterr().out
