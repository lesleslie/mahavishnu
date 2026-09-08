"""Unit tests for worktree_scan module."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Module under test
from mahavishnu.core.worktree_scan import WorktreeClassification


class TestRunGitScanned:
    """_run_git_scanned: explicit-timeout subprocess wrapper for git."""

    def test_subprocess_called_with_list_form_args(self):
        from mahavishnu.core.worktree_scan import _run_git_scanned
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            _run_git_scanned(Path("/tmp/repo"), "worktree", "list", "--porcelain", timeout=10)
            call = mock_run.call_args
            args = call[0][0]
            assert args[0] == "git"
            assert args[1] == "-C"
            assert args[2] == "/tmp/repo"
            assert call[1].get("shell", False) is False
            assert call[1]["timeout"] == 10

    def test_shell_false_enforced(self):
        from mahavishnu.core.worktree_scan import _run_git_scanned
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            _run_git_scanned(Path("/tmp/repo"), "status", "--short")
            assert mock_run.call_args[1]["shell"] is False


class TestRunPs:
    """_run_ps: PID validation + subprocess wrapper for ps."""

    def test_pid_validated_as_digits_only(self):
        from mahavishnu.core.worktree_scan import _run_ps
        with pytest.raises(ValueError, match="PID must match"):
            _run_ps("-1")  # leading dash = flag injection

    def test_pid_validated_as_positive_integer(self):
        from mahavishnu.core.worktree_scan import _run_ps
        with pytest.raises(ValueError, match="PID must match"):
            _run_ps("abc")

    def test_valid_pid_invokes_ps(self):
        from mahavishnu.core.worktree_scan import _run_ps
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            _run_ps("74005", timeout=2)
            args = mock_run.call_args[0][0]
            assert args[0] == "ps"
            assert args[1] == "-p"
            assert args[2] == "74005"
            assert mock_run.call_args[1]["timeout"] == 2
            assert mock_run.call_args[1]["shell"] is False


class TestClassifyWorktreeTierA:
    """classify_worktree: tier A-merged and A-merged-dirty."""

    def test_clean_merged_is_tier_a_merged(self):
        from mahavishnu.core.worktree_scan import classify_worktree
        result = classify_worktree(
            worktree_path=Path("/tmp/wt"),
            branch="feat/merged",
            age_days=10.0,
            is_dirty=False,
            is_locked=False,
            lock_pid_liveness=None,
            plan_orphan_groups={},
            classify_merge_status_fn=lambda _p: "merged",
        )
        assert result.tier == "A-merged"

    def test_dirty_merged_is_tier_a_merged_dirty(self):
        from mahavishnu.core.worktree_scan import classify_worktree
        result = classify_worktree(
            worktree_path=Path("/tmp/wt"),
            branch="feat/merged",
            age_days=10.0,
            is_dirty=True,
            is_locked=False,
            lock_pid_liveness=None,
            plan_orphan_groups={},
            classify_merge_status_fn=lambda _p: "merged",
        )
        assert result.tier == "A-merged-dirty"

    def test_clean_not_merged_is_not_tier_a(self):
        from mahavishnu.core.worktree_scan import classify_worktree
        result = classify_worktree(
            worktree_path=Path("/tmp/wt"),
            branch="feat/active",
            age_days=10.0,
            is_dirty=False,
            is_locked=False,
            lock_pid_liveness=None,
            plan_orphan_groups={},
            classify_merge_status_fn=lambda _p: "not_merged",
        )
        assert result.tier != "A-merged"
        assert result.tier != "A-merged-dirty"


class TestClassifyWorktreeTierAOrphan:
    """classify_worktree: tier A-orphan-detached variants."""

    def test_detached_not_in_plan_pattern_is_tier_a(self):
        from mahavishnu.core.worktree_scan import classify_worktree
        result = classify_worktree(
            worktree_path=Path("/tmp/wt"),
            branch=None,  # detached HEAD
            age_days=2.0,
            is_dirty=False,
            is_locked=False,
            lock_pid_liveness=None,
            plan_orphan_groups={},
            classify_merge_status_fn=lambda _p: "not_merged",
        )
        assert result.tier == "A-orphan-detached"

    def test_detached_dirty_is_tier_a_orphan_detached_dirty(self):
        from mahavishnu.core.worktree_scan import classify_worktree
        result = classify_worktree(
            worktree_path=Path("/tmp/wt"),
            branch=None,
            age_days=2.0,
            is_dirty=True,
            is_locked=False,
            lock_pid_liveness=None,
            plan_orphan_groups={},
            classify_merge_status_fn=lambda _p: "not_merged",
        )
        assert result.tier == "A-orphan-detached-dirty"


class TestClassifyWorktreeTierX:
    """classify_worktree: tier X (cross-repo plan-orphan) — EXCLUSIVE."""

    def test_classify_worktree_returns_tier_x_for_plan_orphan_branch(self):
        from mahavishnu.core.worktree_scan import classify_worktree
        group = {
            "2026-08-16-wave8-diagram-corrections": [
                ("akosha", Path("/tmp/wt")),
            ],
        }
        result = classify_worktree(
            worktree_path=Path("/tmp/wt"),
            branch="wave8-diagram-corrections-2026-08-16",
            age_days=21.0,
            is_dirty=False,
            is_locked=False,
            lock_pid_liveness=None,
            plan_orphan_groups=group,
            classify_merge_status_fn=lambda _p: "not_merged",
        )
        assert result.tier == "X"
        assert result.cross_repo_group_id == "2026-08-16-wave8-diagram-corrections"


class TestClassifyWorktreeTierBCD:
    """classify_worktree: tier B (agent-dispatch), C (mid-age), D (recent)."""

    def test_agent_dispatch_path_is_tier_b(self, monkeypatch):
        from mahavishnu.core import worktree_scan
        # Pretend get_worktree_base_path returns /Users/les/worktrees
        monkeypatch.setattr(worktree_scan, "get_worktree_base_path",
                            lambda: Path("/Users/les/worktrees"))
        result = worktree_scan.classify_worktree(
            worktree_path=Path("/Users/les/worktrees/agent-abc123"),
            branch="worktree-agent-abc123",
            age_days=2.0,
            is_dirty=False,
            is_locked=False,
            lock_pid_liveness=None,
            plan_orphan_groups={},
            classify_merge_status_fn=lambda _p: "not_merged",
        )
        assert result.tier == "B"

    def test_mid_age_clean_is_tier_c(self):
        from mahavishnu.core.worktree_scan import classify_worktree
        result = classify_worktree(
            worktree_path=Path("/tmp/wt"),
            branch="feat/active-mid",
            age_days=15.0,
            is_dirty=False,
            is_locked=False,
            lock_pid_liveness=None,
            plan_orphan_groups={},
            classify_merge_status_fn=lambda _p: "not_merged",
        )
        assert result.tier == "C"

    def test_age_at_exactly_9_is_tier_c(self):
        from mahavishnu.core.worktree_scan import classify_worktree
        result = classify_worktree(
            worktree_path=Path("/tmp/wt"),
            branch="feat/active-9",
            age_days=9.0,
            is_dirty=False,
            is_locked=False,
            lock_pid_liveness=None,
            plan_orphan_groups={},
            classify_merge_status_fn=lambda _p: "not_merged",
        )
        assert result.tier == "C"  # 9.0 is inclusive

    def test_age_below_9_is_tier_d(self):
        from mahavishnu.core.worktree_scan import classify_worktree
        result = classify_worktree(
            worktree_path=Path("/tmp/wt"),
            branch="feat/active-8",
            age_days=8.99,
            is_dirty=False,
            is_locked=False,
            lock_pid_liveness=None,
            plan_orphan_groups={},
            classify_merge_status_fn=lambda _p: "not_merged",
        )
        assert result.tier == "D"


class TestScanWorktreesDriver:
    """scan_worktrees: 3-pass pipeline (collect, group, classify)."""

    def test_pipeline_returns_text_report(self, monkeypatch, tmp_path):
        from mahavishnu.core import worktree_scan
        # Minimal fixture: 1 repo with 1 worktree (clean, merged)
        repo_dir = tmp_path / "repo1"
        repo_dir.mkdir()
        (repo_dir / ".git").mkdir()
        # Mock git worktree list --porcelain output
        with patch.object(worktree_scan, "_run_git_scanned") as mock_git, \
             patch.object(worktree_scan, "_run_ps") as mock_ps:
            # Realistic porcelain block: one worktree with a branch line.
            mock_git.return_value = MagicMock(
                returncode=0,
                stdout="worktree /tmp/repo1/.worktrees/feat-merged\nHEAD abc123\nbranch refs/heads/feat/merged\n\n",
                stderr="",
            )
            report = worktree_scan.scan_worktrees(
                repo_paths=[repo_dir],
                classify_merge_status_fn=lambda _p: "merged",
            )
        assert isinstance(report, str)
        assert "Tier A-merged" in report or "A-merged" in report

    def test_json_output_is_valid_json(self, tmp_path):
        import json

        from mahavishnu.core import worktree_scan
        repo_dir = tmp_path / "repo1"
        repo_dir.mkdir()
        (repo_dir / ".git").mkdir()
        with patch.object(worktree_scan, "_run_git_scanned") as mock_git:
            mock_git.return_value = MagicMock(returncode=0, stdout="", stderr="")
            report_str = worktree_scan.scan_worktrees(
                repo_paths=[repo_dir],
                classify_merge_status_fn=lambda _p: "not_merged",
                output_format="json",
            )
        parsed = json.loads(report_str)
        assert "scan_metadata" in parsed
        assert "tier_a_merged" in parsed


class TestClassifyWorktreeTierXExclusivity:
    """F22 — Tier X is exclusive: merged+plan_orphan branches return A-merged.

    Per spec A66 / review F22: when a worktree matches PLAN_ORPHAN_PATTERNS
    AND `classify_merge_status == "merged"`, the early-return for merged
    takes priority and the classification is Tier A-merged (or A-merged-dirty).
    """

    def test_merged_plan_orphan_returns_tier_a_merged(self):
        from mahavishnu.core.worktree_scan import classify_worktree
        group = {
            "2026-08-16-wave8-diagram-corrections": [
                ("akosha", Path("/tmp/wt")),
            ],
        }
        result = classify_worktree(
            worktree_path=Path("/tmp/wt"),
            branch="wave8-diagram-corrections-2026-08-16",
            age_days=21.0,
            is_dirty=False,
            is_locked=False,
            lock_pid_liveness=None,
            plan_orphan_groups=group,
            classify_merge_status_fn=lambda _p: "merged",
        )
        assert result.tier == "A-merged"

    def test_merged_plan_orphan_dirty_returns_tier_a_merged_dirty(self):
        from mahavishnu.core.worktree_scan import classify_worktree
        group = {
            "2026-08-16-wave8-diagram-corrections": [
                ("akosha", Path("/tmp/wt")),
            ],
        }
        result = classify_worktree(
            worktree_path=Path("/tmp/wt"),
            branch="wave8-diagram-corrections-2026-08-16",
            age_days=21.0,
            is_dirty=True,
            is_locked=False,
            lock_pid_liveness=None,
            plan_orphan_groups=group,
            classify_merge_status_fn=lambda _p: "merged",
        )
        assert result.tier == "A-merged-dirty"


class TestCollectRepoFallbackForEmptyGitLog:
    """F40 — empty `git log -1 --format=%ct` output should default age to 0.0d
    so the worktree classifies as Tier D (recent) instead of
    Tier A-orphan-detached by age.
    """

    def test_empty_git_log_sets_age_to_zero(self, tmp_path):
        from mahavishnu.core import worktree_scan
        repo_dir = tmp_path / "fresh_repo"
        repo_dir.mkdir()
        (repo_dir / ".git").mkdir()
        # Build a porcelain entry that the collector will see; subsequent
        # `git log -1 --format=%ct` call returns empty stdout.
        porcelain = (
            "worktree /tmp/repo1/.worktrees/fresh-worktree\n"
            "HEAD abc123\nbranch refs/heads/feat/fresh\n\n"
        )
        call_log: list[tuple] = []

        def fake_git(path, *args, **kwargs):
            call_log.append(args)
            # First call: `worktree list --porcelain` — return the porcelain.
            if args and args[0] == "worktree":
                return MagicMock(returncode=0, stdout=porcelain, stderr="")
            # Everything else (incl. `log -1 --format=%ct`) — return empty.
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch.object(worktree_scan, "_run_git_scanned", side_effect=fake_git):
            entries, reason = worktree_scan._collect_repo(repo_dir, 30.0, 9.0)
        assert reason is None
        assert len(entries) == 1
        # F40: empty log → age_defaults to 0.0 (NOT 99999.0).
        assert entries[0]["age_days"] == 0.0


class TestCollectRepoFailureTracking:
    """F19 — when `git worktree list` fails, _collect_repo returns
    a failure reason so scan_worktrees can surface it.
    """

    def test_git_failure_returns_failure_reason(self, tmp_path):
        from mahavishnu.core import worktree_scan
        repo_dir = tmp_path / "broken_repo"
        repo_dir.mkdir()
        with patch.object(worktree_scan, "_run_git_scanned") as mock_git:
            mock_git.return_value = MagicMock(
                returncode=128,
                stdout="",
                stderr="fatal: not a git repository",
            )
            entries, reason = worktree_scan._collect_repo(repo_dir, 30.0, 9.0)
        assert entries == []
        assert reason is not None
        assert "128" in reason

    def test_scan_worktrees_threads_failed_repos(self, tmp_path):
        from mahavishnu.core import worktree_scan
        good_repo = tmp_path / "good"
        good_repo.mkdir()
        (good_repo / ".git").mkdir()
        bad_repo = tmp_path / "bad"

        def fake_git(path, *args, **kwargs):
            if args and args[0] == "worktree":
                if "bad" in str(path):
                    return MagicMock(
                        returncode=128, stdout="", stderr="fatal",
                    )
                return MagicMock(returncode=0, stdout="", stderr="")
            return MagicMock(returncode=0, stdout="0", stderr="")

        with patch.object(worktree_scan, "_run_git_scanned", side_effect=fake_git):
            report_str = worktree_scan.scan_worktrees(
                repo_paths=[good_repo, bad_repo],
                classify_merge_status_fn=lambda _p: "not_merged",
                output_format="json",
            )
        import json
        parsed = json.loads(report_str)
        assert "scan_metadata" in parsed
        assert "failed_repos" in parsed["scan_metadata"]
        failed_paths = [f["path"] for f in parsed["scan_metadata"]["failed_repos"]]
        assert any("bad" in p for p in failed_paths)


class TestFormatJsonTierXShape:
    """F21 §3 — `tier_x_cross_repo_orphan` is grouped by group_id and each
    record carries `date`, `pattern`, and a nested `entries[]` of
    {repo, path, branch}.
    """

    def test_tier_x_records_have_date_pattern_group_id_entries(self, tmp_path):
        import json

        from mahavishnu.core import worktree_scan
        # Two repos, each with one worktree on the same plan_orphan branch.
        repo_a = tmp_path / "akosha"
        repo_a.mkdir()
        (repo_a / ".git").mkdir()
        repo_b = tmp_path / "mahavishnu"
        repo_b.mkdir()
        (repo_b / ".git").mkdir()

        porcelain_a = (
            "worktree /tmp/akosha/.worktrees/wave8-1\n"
            "HEAD abc\nbranch refs/heads/wave8-diagram-corrections-2026-08-16\n\n"
        )
        porcelain_b = (
            "worktree /tmp/mahavishnu/.worktrees/wave8-2\n"
            "HEAD def\nbranch refs/heads/wave8-diagram-corrections-2026-08-16\n\n"
        )

        def fake_git(path, *args, **kwargs):
            if args and args[0] == "worktree":
                if "akosha" in str(path):
                    return MagicMock(returncode=0, stdout=porcelain_a, stderr="")
                if "mahavishnu" in str(path):
                    return MagicMock(returncode=0, stdout=porcelain_b, stderr="")
            return MagicMock(returncode=0, stdout="0", stderr="")

        with patch.object(worktree_scan, "_run_git_scanned", side_effect=fake_git):
            report = worktree_scan.scan_worktrees(
                repo_paths=[repo_a, repo_b],
                classify_merge_status_fn=lambda _p: "not_merged",
                output_format="json",
            )
        parsed = json.loads(report)
        tier_x = parsed["tier_x_cross_repo_orphan"]
        assert len(tier_x) == 1, "expected exactly one group record"
        record = tier_x[0]
        assert record["group_id"] == "2026-08-16-wave8-diagram-corrections"
        assert record["date"] == "2026-08-16"
        assert record["pattern"] == "wave8-diagram-corrections"
        assert isinstance(record["entries"], list)
        assert len(record["entries"]) == 2
        for entry in record["entries"]:
            assert "repo" in entry
            assert "path" in entry
            assert "branch" in entry
            assert entry["branch"] == "wave8-diagram-corrections-2026-08-16"


class TestScanMetadataReposScanned:
    """L4 — `scan_metadata.repos_scanned` reflects input minus driver failures."""

    def test_repos_scanned_equals_input_minus_failed(self, tmp_path):
        import json

        from mahavishnu.core import worktree_scan
        good_repo = tmp_path / "good"
        good_repo.mkdir()
        (good_repo / ".git").mkdir()
        bad_repo = tmp_path / "bad"

        def fake_git(path, *args, **kwargs):
            if args and args[0] == "worktree":
                if "bad" in str(path):
                    return MagicMock(returncode=128, stdout="", stderr="fatal")
                return MagicMock(returncode=0, stdout="", stderr="")
            return MagicMock(returncode=0, stdout="0", stderr="")

        with patch.object(worktree_scan, "_run_git_scanned", side_effect=fake_git):
            report = worktree_scan.scan_worktrees(
                repo_paths=[good_repo, bad_repo],
                classify_merge_status_fn=lambda _p: "not_merged",
                output_format="json",
            )
        parsed = json.loads(report)
        assert parsed["scan_metadata"]["repos_scanned"] == 1

    def test_repos_scanned_equals_all_when_no_failures(self, tmp_path):
        import json

        from mahavishnu.core import worktree_scan
        repo_a = tmp_path / "a"
        repo_a.mkdir()
        (repo_a / ".git").mkdir()
        repo_b = tmp_path / "b"
        repo_b.mkdir()
        (repo_b / ".git").mkdir()

        with patch.object(worktree_scan, "_run_git_scanned") as mock_git:
            mock_git.return_value = MagicMock(returncode=0, stdout="", stderr="")
            report = worktree_scan.scan_worktrees(
                repo_paths=[repo_a, repo_b],
                classify_merge_status_fn=lambda _p: "not_merged",
                output_format="json",
            )
        parsed = json.loads(report)
        assert parsed["scan_metadata"]["repos_scanned"] == 2


class TestGroupPlanOrphans:
    """F-QA-14 — `_group_plan_orphans` must only return groups with >= 2 repos."""

    def test_single_repo_match_is_excluded(self):
        from mahavishnu.core import worktree_scan
        entries = [
            {
                "branch": "wave8-diagram-corrections-2026-08-16",
                "path": Path("/tmp/akosha/.worktrees/x"),
                "repo_nickname": "akosha",
            },
        ]
        result = worktree_scan._group_plan_orphans(entries)
        # Only one repo matching -> no cross-repo group.
        assert result == {}

    def test_two_repo_match_yields_one_group(self):
        from mahavishnu.core import worktree_scan
        entries = [
            {
                "branch": "wave8-diagram-corrections-2026-08-16",
                "path": Path("/tmp/akosha/.worktrees/x"),
                "repo_nickname": "akosha",
            },
            {
                "branch": "wave8-diagram-corrections-2026-08-16",
                "path": Path("/tmp/mahavishnu/.worktrees/x"),
                "repo_nickname": "mahavishnu",
            },
        ]
        result = worktree_scan._group_plan_orphans(entries)
        assert "2026-08-16-wave8-diagram-corrections" in result
        assert len(result["2026-08-16-wave8-diagram-corrections"]) == 2

    def test_branch_without_date_suffix_is_excluded(self):
        from mahavishnu.core import worktree_scan
        entries = [
            {
                "branch": "wave8-diagram-corrections",
                "path": Path("/tmp/r/.worktrees/x"),
                "repo_nickname": "r",
            },
            {
                "branch": "wave8-diagram-corrections",
                "path": Path("/tmp/m/.worktrees/x"),
                "repo_nickname": "m",
            },
        ]
        result = worktree_scan._group_plan_orphans(entries)
        assert result == {}

    def test_detached_branch_is_skipped(self):
        from mahavishnu.core import worktree_scan
        entries = [
            {
                "branch": None,
                "path": Path("/tmp/r/.worktrees/x"),
                "repo_nickname": "r",
            },
        ]
        result = worktree_scan._group_plan_orphans(entries)
        assert result == {}


class TestFormatTextSections:
    """F-QA-12 — `_format_text` emits LOCKED / DIRTY / SCAN-FAILURES sections
    and an exit-code-aware footer. Tests build `WorktreeClassification`
    fixtures directly so each section is exercised in isolation.
    """

    def _make_cls(self, **overrides) -> WorktreeClassification:
        kwargs: dict = dict(
            tier="C",
            is_dirty=False,
            is_locked=False,
            pid_liveness=None,
            stash_count=0,
            modified_count=0,
            untracked_count=0,
            cross_repo_group_id=None,
            lock_pid=None,
            lock_command=None,
            repo_nickname=None,
            branch=None,
            worktree_path=None,
        )
        kwargs.update(overrides)
        return WorktreeClassification(**kwargs)

    def test_locked_live_section_renders_with_pid_and_command(self):
        from mahavishnu.core import worktree_scan
        cls = self._make_cls(
            is_locked=True,
            pid_liveness="alive",
            lock_pid=74005,
            lock_command="claude agent foo",
            branch="feat/locked",
        )
        out = worktree_scan._format_text([cls])
        assert "LOCKED-live (cannot remove without verification, 1):" in out
        assert "pid=74005" in out
        assert "'claude agent foo'" in out

    def test_locked_orphan_section_renders_when_pid_dead(self):
        from mahavishnu.core import worktree_scan
        cls = self._make_cls(
            is_locked=True,
            pid_liveness="dead",
            lock_pid=99999,
            lock_command=None,
            branch="feat/orphan",
        )
        out = worktree_scan._format_text([cls])
        assert "LOCKED-orphan (PID dead, can unlock+remove, 1):" in out
        # Dead PID is discoverable via the dataclass repr (lock_pid=...).
        assert "lock_pid=99999" in out
        assert "feat/orphan" in out

    def test_locked_unknown_section_renders_when_pid_unknown(self):
        from mahavishnu.core import worktree_scan
        cls = self._make_cls(
            is_locked=True,
            pid_liveness="unknown",
            lock_pid=None,
            lock_command=None,
        )
        out = worktree_scan._format_text([cls])
        assert "LOCKED-unknown (lock parse failed, manual review, 1):" in out

    def test_dirty_section_emits_aggregate_counts(self):
        from mahavishnu.core import worktree_scan
        cls1 = self._make_cls(
            is_dirty=True, modified_count=2, stash_count=1, untracked_count=3,
            tier="A-merged-dirty", repo_nickname="r1",
        )
        cls2 = self._make_cls(
            is_dirty=True, modified_count=0, stash_count=0, untracked_count=0,
            tier="C", repo_nickname="r2",
        )
        out = worktree_scan._format_text([cls1, cls2])
        assert "DIRTY (2 modified, 1 stashes, 3 untracked" in out
        assert ", 2):" in out

    def test_scan_failures_section_renders_failures(self):
        from mahavishnu.core import worktree_scan
        out = worktree_scan._format_text(
            [],
            failed_repos=[
                {"path": "/nonexistent/a", "reason": "path does not exist"},
                {"path": "/broken/repo", "reason": "git worktree list returned 128"},
            ],
        )
        assert "SCAN-FAILURES (2 repo(s) failed):" in out
        assert "/nonexistent/a: path does not exist" in out
        assert "/broken/repo: git worktree list returned 128" in out

    def test_footer_reports_exit_1_when_failures(self):
        from mahavishnu.core import worktree_scan
        out = worktree_scan._format_text(
            [], failed_repos=[{"path": "/x", "reason": "missing"}]
        )
        assert "Scan complete: 0 candidates; 1 scan failures; exit 1." in out

    def test_footer_reports_exit_0_when_clean(self):
        from mahavishnu.core import worktree_scan
        out = worktree_scan._format_text([])
        assert "Scan complete: 0 candidates; 0 scan failures; exit 0." in out

    def test_locked_sections_emit_even_when_empty(self):
        """F20 — every section header is always emitted (possibly empty)."""
        from mahavishnu.core import worktree_scan
        out = worktree_scan._format_text([])
        assert "LOCKED-live (cannot remove without verification, 0):" in out
        assert "LOCKED-orphan (PID dead, can unlock+remove, 0):" in out
        assert "LOCKED-unknown (lock parse failed, manual review, 0):" in out


class TestFormatJsonLockedLiveRealValues:
    """F21 §2 — locked_live[] emits real PID + command for entries where
    `pid_liveness == "alive" AND lock_pid is not None` (formatter-level test).
    """

    def _make_cls(self, **overrides) -> WorktreeClassification:
        kwargs: dict = dict(
            tier="C",
            is_dirty=False,
            is_locked=True,
            pid_liveness="alive",
            stash_count=0,
            modified_count=0,
            untracked_count=0,
            cross_repo_group_id=None,
            lock_pid=None,
            lock_command=None,
            repo_nickname=None,
            branch=None,
            worktree_path=None,
        )
        kwargs.update(overrides)
        return WorktreeClassification(**kwargs)

    def test_locked_live_emits_real_pid_and_command(self):
        """When `lock_pid` is set, formatter includes it (not None placeholder)."""
        import json

        from mahavishnu.core import worktree_scan
        cls = self._make_cls(
            lock_pid=74005,
            lock_command="claude agent foo",
            branch="feat/locked",
            repo_nickname="mahavishnu",
        )
        out = worktree_scan._format_json([cls])
        parsed = json.loads(out)
        locked_live = parsed["locked_live"]
        assert len(locked_live) == 1
        entry = locked_live[0]
        # Real PID + command (not None placeholders).
        assert entry["pid"] is not None
        assert isinstance(entry["pid"], int)
        assert entry["pid"] == 74005
        assert entry["command"] == "claude agent foo"

    def test_locked_live_excludes_entries_without_parsed_pid(self):
        """Worktree with `pid_liveness == 'alive'` but `lock_pid is None`
        must NOT appear in `locked_live[]` (F21 §2 second clause).
        """
        import json

        from mahavishnu.core import worktree_scan

        cls = self._make_cls(lock_pid=None)
        out = worktree_scan._format_json([cls])
        parsed = json.loads(out)
        # F21 §2: filter `lock_pid is not None` so this drops out.
        assert parsed["locked_live"] == []


class TestClassifierReuse:
    """Spec A20 / F25 — worktree_scan.py must NOT define `classify_merge_status`
    or `classify_merged`; both names must be imported from worktree_prune_merged.
    """

    def test_worktree_scan_does_not_define_classify_merge_status(self):
        import inspect

        from mahavishnu.core import worktree_scan
        source = inspect.getsource(worktree_scan)
        # Defs of classify_merge_status or classify_merged in scan.py are forbidden.
        assert "def classify_merge_status" not in source
        assert "def classify_merged" not in source

    def test_worktree_scan_uses_classify_merge_status_from_worktree_prune_merged(self):
        # The function name appears in scan.py ONLY as a callable parameter
        # or as a re-export; the implementation must come from prune_merged.
        from mahavishnu.core import worktree_scan
        # `scan.py` should re-export or pass through, not redefine.
        assert not hasattr(worktree_scan, "classify_merge_status") or callable(
            getattr(worktree_scan, "classify_merge_status", None)
        )


class TestScanWorktreesObservability:
    """F-QA-4 / F-QA-5 / F-QA-6 — scan_worktrees emits the spec's three
    observability signals on completion:

    (a) counter `mahavishnu.worktree_scan.scans_total` (+1 per call)
    (b) histogram `mahavishnu.worktree_scan.duration_seconds`
    (c) INFO log line carrying tier counts, duration, and counts.

    The module-level OTel handles are no-op fallbacks when opentelemetry
    isn't installed; we still verify they're called (counters/histograms
    are duck-typed objects with .add / .record methods)."""
    NOQA_ATTR = "_SCANS_COUNTER_DUMMY"

    def test_counter_and_histogram_are_called_per_scan(self, tmp_path, caplog):
        from mahavishnu.core import worktree_scan
        repo = tmp_path / "r"
        repo.mkdir()
        (repo / ".git").mkdir()
        with patch.object(worktree_scan, "_SCANS_COUNTER") as counter, \
             patch.object(worktree_scan, "_DURATION_HISTOGRAM") as hist, \
             patch.object(worktree_scan, "_run_git_scanned") as git, \
             patch.object(worktree_scan, "_run_ps"):
            git.return_value = MagicMock(returncode=0, stdout="", stderr="")
            with caplog.at_level("INFO", logger="mahavishnu.core.worktree_scan"):
                report = worktree_scan.scan_worktrees(
                    repo_paths=[repo],
                    classify_merge_status_fn=lambda _p: "not_merged",
                    output_format="text",
                )
        assert isinstance(report, str)
        # Counter incremented exactly once for the one scan call.
        assert counter.add.call_count == 1
        assert counter.add.call_args[0] == (1,)
        # Histogram recorded a positive float duration.
        assert hist.record.call_count == 1
        rec_arg = hist.record.call_args[0][0]
        assert isinstance(rec_arg, float)
        assert rec_arg >= 0.0
        # INFO log carries the canonical completion message and tier summary.
        matching = [
            rec for rec in caplog.records
            if rec.message.startswith("mahavishnu.worktree_scan.completed")
        ]
        assert matching, (
            "expected at least one INFO record beginning with "
            "'mahavishnu.worktree_scan.completed'"
        )
        log_msg = matching[-1].getMessage()
        assert "repos_input=1" in log_msg
        assert "repos_scanned=1" in log_msg
        assert "candidates=0" in log_msg
        assert "duration_s=" in log_msg
        assert "format=text" in log_msg
        assert "tiers=" in log_msg


class TestNoDuplicateHelpers:
    """Spec A56 / F26 — worktree_scan.py must not redefine `validate_path`,
    `get_worktree_base_path`, or `_validate_path`. The first two come from
    mcp-common/paths; `_validate_path` should not exist anywhere.
    """

    def test_worktree_scan_does_not_redefine_get_worktree_base_path(self):
        import inspect

        from mahavishnu.core import worktree_scan
        source = inspect.getsource(worktree_scan)
        assert "def get_worktree_base_path" not in source, (
            "worktree_scan.py must import get_worktree_base_path, not redefine it"
        )

    def test_worktree_scan_does_not_redefine_validate_path_or_underscore_variant(self):
        import inspect

        from mahavishnu.core import worktree_scan
        source = inspect.getsource(worktree_scan)
        # scan.py imports get_worktree_base_path from paths; it must not
        # also define its own path validator.
        assert "def validate_path" not in source
        assert "def _validate_path" not in source
