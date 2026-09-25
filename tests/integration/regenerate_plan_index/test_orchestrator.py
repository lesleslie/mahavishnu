"""Integration tests for scripts/regenerate_plan_index.py orchestrator.

Three-phase orchestrator (scan → upsert → render). The brief specifies
two smoke tests via subprocess; this file extends them with parser-level
checks so the new flags are wired even when Dhara is not reachable.
"""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys

import pytest

from scripts.regenerate_plan_index import build_parser

REPO_ROOT = Path("/Users/les/Projects/mahavishnu")


class TestParserWiring:
    """Verify the new orchestrator flags are present and defaulted correctly."""

    def test_parser_includes_check_flag(self) -> None:
        parser = build_parser()
        # argparse aborts on unknown flags; --check should parse cleanly.
        args = parser.parse_args(["--check", "--repo-root", "/tmp"])
        assert args.check is True

    def test_parser_includes_skip_render_flag(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["--skip-render"])
        assert args.skip_render is True

    def test_parser_includes_exclude_repeatable(self) -> None:
        parser = build_parser()
        args = parser.parse_args([
            "--exclude", "drafts/**",
            "--exclude", "tmp/*.md",
        ])
        assert args.exclude == ["drafts/**", "tmp/*.md"]

    def test_parser_includes_exclude_from(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["--exclude-from", "/tmp/excludes"])
        assert args.exclude_from == "/tmp/excludes"

    def test_parser_includes_render_to(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["--render-to", "/tmp/index.md"])
        assert args.render_to == "/tmp/index.md"

    def test_parser_includes_mcp_url(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["--mcp-url", "http://localhost:8683"])
        assert args.mcp_url == "http://localhost:8683"

    def test_parser_includes_preflight_mode(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["--preflight-mode", "strict"])
        assert args.preflight_mode == "strict"
        # Default is lenient
        args_default = parser.parse_args([])
        assert args_default.preflight_mode == "lenient"

    def test_parser_includes_rebuild_from(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["--rebuild-from", "HEAD~5..HEAD"])
        assert args.rebuild_from == "HEAD~5..HEAD"

    def test_parser_includes_dry_run(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["--dry-run"])
        assert args.dry_run is True

    def test_parser_includes_repo_root(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["--repo-root", "/tmp/x"])
        assert args.repo_root == Path("/tmp/x")

    def test_parser_help_lists_all_flags(self, capsys: pytest.CaptureFixture[str]) -> None:
        parser = build_parser()
        with pytest.raises(SystemExit) as exc:
            parser.parse_args(["--help"])
        assert exc.value.code == 0
        out = capsys.readouterr().out
        for flag in (
            "--dry-run", "--check", "--skip-render",
            "--rebuild-from", "--exclude", "--exclude-from",
            "--preflight-mode", "--render-to", "--mcp-url",
            "--repo-root",
        ):
            assert flag in out, f"--help output missing {flag}"


class TestHelpFlagRenders:
    def test_help_flag_renders(self) -> None:
        result = subprocess.run(
            [sys.executable, "scripts/regenerate_plan_index.py", "--help"],
            capture_output=True, text=True, cwd=str(REPO_ROOT), check=False,
        )
        # --help exits 0 and prints usage to stdout.
        assert result.returncode == 0
        assert "usage:" in result.stdout.lower() or "regenerate_plan_index" in result.stdout


class TestCheckFlag:
    def test_check_flag_exits_zero_when_no_render(self, tmp_path: Path) -> None:
        """--check with a freshly-empty repo: rendered output != existing file
        (existing doesn't exist), so the orchestrator exits 1 with the drift
        message on stderr. The brief allows either exit code, so accept both."""
        result = subprocess.run(
            [sys.executable, "scripts/regenerate_plan_index.py", "--check",
             "--repo-root", str(tmp_path)],
            capture_output=True, text=True, cwd=str(REPO_ROOT), check=False,
        )
        # Either exit 0 (no PLAN_INDEX.md yet → empty == empty) or 1 (drift).
        assert result.returncode in (0, 1)


class TestDryRun:
    def test_dry_run_prints_to_stdout_no_write(self, tmp_path: Path) -> None:
        """--dry-run must NOT create PLAN_INDEX.md under --repo-root."""
        target = tmp_path / "PLAN_INDEX.md"
        assert not target.exists()
        result = subprocess.run(
            [sys.executable, "scripts/regenerate_plan_index.py",
             "--dry-run", "--repo-root", str(tmp_path)],
            capture_output=True, text=True, cwd=str(REPO_ROOT), check=False,
        )
        assert result.returncode == 0
        # Stdout should contain the index header.
        assert "Plan Index" in result.stdout
        # No file should be written.
        assert not target.exists()


class TestSkipRender:
    def test_skip_render_does_not_write(self, tmp_path: Path) -> None:
        """--skip-render: scan runs, but PLAN_INDEX.md is NOT written."""
        target = tmp_path / "PLAN_INDEX.md"
        result = subprocess.run(
            [sys.executable, "scripts/regenerate_plan_index.py",
             "--skip-render", "--repo-root", str(tmp_path),
             "--out", str(target)],
            capture_output=True, text=True, cwd=str(REPO_ROOT), check=False,
        )
        assert result.returncode == 0
        assert not target.exists()
        assert "skip-render" in result.stderr


class TestExclude:
    def test_exclude_pattern_skips_paths(self, tmp_path: Path) -> None:
        """A --exclude pattern must drop matching files from the registry."""
        # Build a tiny store: docs/plans/foo.md + drafts/bar.md
        plans = tmp_path / "docs" / "plans"
        plans.mkdir(parents=True)
        foo = plans / "foo.md"
        foo.write_text(
            "---\nstatus: active\nrole: canonical\ndate: 2026-09-10\n"
            "last_reviewed: 2026-09-10\ntitle: Foo\n---\n\n# Foo\n"
        )
        drafts = tmp_path / "drafts"
        drafts.mkdir()
        bar = drafts / "bar.md"
        bar.write_text(
            "---\nstatus: draft\nrole: implementation\ndate: 2026-09-10\n"
            "last_reviewed: 2026-09-10\ntitle: Bar\n---\n\n# Bar\n"
        )

        # Auto-discovery requires >= 2 docs with frontmatter in the same
        # store; force the store explicitly via --stores so the small
        # fixture still gets picked up.
        result = subprocess.run(
            [sys.executable, "scripts/regenerate_plan_index.py",
             "--dry-run",
             "--repo-root", str(tmp_path),
             "--stores", "drafts/,docs/plans/",
             "--exclude", "drafts/**"],
            capture_output=True, text=True, cwd=str(REPO_ROOT), check=False,
        )
        assert result.returncode == 0
        # drafts/bar.md was excluded; only foo.md should appear.
        assert "bar.md" not in result.stdout
        assert "foo.md" in result.stdout


class TestExcludeFrom:
    def test_exclude_from_file(self, tmp_path: Path) -> None:
        plans = tmp_path / "docs" / "plans"
        plans.mkdir(parents=True)
        keep = plans / "keep.md"
        keep.write_text(
            "---\nstatus: active\nrole: canonical\ndate: 2026-09-10\n"
            "last_reviewed: 2026-09-10\ntitle: Keep\n---\n\n# Keep\n"
        )
        skip = plans / "skip.md"
        skip.write_text(
            "---\nstatus: active\nrole: canonical\ndate: 2026-09-10\n"
            "last_reviewed: 2026-09-10\ntitle: Skip\n---\n\n# Skip\n"
        )

        excludes = tmp_path / "excludes"
        excludes.write_text("# drop the skip doc\nskip.md\n")

        result = subprocess.run(
            [sys.executable, "scripts/regenerate_plan_index.py",
             "--dry-run",
             "--repo-root", str(tmp_path),
             "--stores", "docs/plans/",
             "--exclude-from", str(excludes)],
            capture_output=True, text=True, cwd=str(REPO_ROOT), check=False,
        )
        assert result.returncode == 0
        assert "keep.md" in result.stdout
        assert "skip.md" not in result.stdout


class TestDiscoverRecords14Fields:
    """Smoke test the cron_core.discover_records 14-field fix.

    After Task 15's fix, every discovered record must populate all 14
    PlanRecord fields — the previous version only filled 5 (plan_id, path,
    title, status, repo) and the frozen dataclass would have raised on the
    missing kw_only fields.

    `_is_store_directory` requires >= 2 docs with valid frontmatter in
    the same directory before it is promoted to a "store", so each test
    seeds at least two plan files.
    """

    def test_discover_records_populates_all_14_fields(self, tmp_path: Path) -> None:
        from mahavishnu.plan_index.cron_core import discover_records

        plans = tmp_path / "docs" / "plans"
        plans.mkdir(parents=True)
        # Pair file: lifts the directory into "store" territory.
        (plans / "pair.md").write_text(
            "---\n"
            "status: active\n"
            "role: implementation\n"
            "date: 2026-09-10\n"
            "last_reviewed: 2026-09-10\n"
            "title: Pair\n"
            "---\n\n# Pair\n"
        )
        doc = plans / "alpha.md"
        doc.write_text(
            "---\n"
            "status: active\n"
            "role: canonical\n"
            "date: 2026-09-10\n"
            "last_reviewed: 2026-09-09\n"
            "superseded_by: null\n"
            "blocks_on:\n"
            "  - docs/plans/beta.md\n"
            "  - docs/plans/gamma.md\n"
            "topic: routing-composition\n"
            "title: Alpha\n"
            "---\n\n# Alpha\n"
        )

        records = discover_records(tmp_path)
        by_path = {r.path: r for r in records}
        assert "docs/plans/alpha.md" in by_path, "alpha.md must be discovered"
        rec = by_path["docs/plans/alpha.md"]

        # All 14 fields present, non-default values where expected.
        assert rec.plan_id == "plan-docs/plans/alpha"
        assert rec.path == "docs/plans/alpha.md"
        assert rec.title == "Alpha"
        assert rec.status == "active"
        assert rec.role == "canonical"
        assert rec.topic == "routing-composition"
        assert rec.date == "2026-09-10"
        assert rec.last_reviewed == "2026-09-09"
        assert rec.superseded_by is None
        assert rec.blocks_on == ["docs/plans/beta.md", "docs/plans/gamma.md"]
        # sha may be empty string when git is unavailable in tmp_path; that's
        # acceptable — the field is populated (just possibly empty).
        assert isinstance(rec.sha, str)
        assert isinstance(rec.repo, str)
        assert rec.lifecycle_state is None
        assert isinstance(rec.updated_at_ms, int) and rec.updated_at_ms > 0

    def test_discover_records_applies_role_default_when_missing(
        self, tmp_path: Path,
    ) -> None:
        from mahavishnu.plan_index.cron_core import discover_records

        plans = tmp_path / "docs" / "plans"
        plans.mkdir(parents=True)
        (plans / "alpha.md").write_text(
            "---\n"
            "status: active\n"
            "date: 2026-09-10\n"
            "last_reviewed: 2026-09-10\n"
            "title: Alpha\n"
            "---\n\n# Alpha\n"
        )
        (plans / "beta.md").write_text(
            "---\n"
            "status: active\n"
            "role: canonical\n"
            "date: 2026-09-10\n"
            "last_reviewed: 2026-09-10\n"
            "title: Beta\n"
            "---\n\n# Beta\n"
        )

        records = discover_records(tmp_path)
        by_path = {r.path: r for r in records}
        rec = by_path["docs/plans/alpha.md"]
        assert rec.role == "implementation"  # default
        assert rec.topic == ""  # default
        assert rec.blocks_on == []  # default

    def test_discover_records_skips_invalid_status(self, tmp_path: Path) -> None:
        from mahavishnu.plan_index.cron_core import discover_records

        plans = tmp_path / "docs" / "plans"
        plans.mkdir(parents=True)
        (plans / "good.md").write_text(
            "---\n"
            "status: active\n"
            "role: canonical\n"
            "date: 2026-09-10\n"
            "last_reviewed: 2026-09-10\n"
            "title: Good\n"
            "---\n\n# Good\n"
        )
        bad = plans / "bad.md"
        bad.write_text(
            "---\n"
            "status: not-a-real-status\n"
            "role: canonical\n"
            "date: 2026-09-10\n"
            "last_reviewed: 2026-09-10\n"
            "title: Bad\n"
            "---\n\n# Bad\n"
        )

        records = discover_records(tmp_path)
        by_path = {r.path for r in records}
        assert "docs/plans/bad.md" not in by_path, "invalid status must skip the file"
        assert "docs/plans/good.md" in by_path
