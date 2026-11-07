"""Tests for mahavishnu/scaffolding/extractor.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from mahavishnu.scaffolding.extractor import (
    PatternDraft,
    PatternExtractor,
    _dir_in_repo,
    _find_common_files,
    _find_common_subtrees,
    _get_sorted_path_list,
    _infer_category,
)


class TestPatternDraft:
    def test_init_stores_attributes(self) -> None:
        draft = PatternDraft(
            category="adapters",
            name="my-pattern",
            dirs=[{"path": "src/", "required": True, "description": ""}],
            files=[{"path": "src/main.py", "required": False, "description": ""}],
            confidence=0.9,
            source_repos=["repo-a", "repo-b"],
        )
        assert draft.category == "adapters"
        assert draft.name == "my-pattern"
        assert draft.confidence == 0.9
        assert draft.source_repos == ["repo-a", "repo-b"]

    def test_to_pattern_dict_schema(self) -> None:
        draft = PatternDraft(
            category="scaffolding",
            name="base",
            dirs=[],
            files=[],
            confidence=0.75,
            source_repos=["repo-x"],
        )
        d = draft.to_pattern_dict()
        assert d["schema_version"] == 1
        assert d["id"] == "scaffolding/base"
        assert d["version"] == "0.1.0-draft"
        assert d["confidence"] == 0.75
        assert d["source_repos"] == ["repo-x"]
        assert d["depends"] == []
        assert d["tags"] == ["scaffolding", "auto-suggested"]
        assert "structure" in d
        assert d["structure"]["dirs"] == []
        assert d["structure"]["files"] == []

    def test_to_pattern_dict_confidence_rounded(self) -> None:
        draft = PatternDraft("x", "y", [], [], 0.7777777, ["r"])
        assert draft.to_pattern_dict()["confidence"] == 0.78

    def test_to_pattern_dict_description_includes_repos(self) -> None:
        draft = PatternDraft("x", "y", [], [], 1.0, ["repo-a", "repo-b"])
        d = draft.to_pattern_dict()
        assert "repo-a" in d["description"]
        assert "repo-b" in d["description"]


class TestPatternExtractor:
    def test_register_repo_accepts_str(self, tmp_path: Path) -> None:
        ex = PatternExtractor()
        ex.register_repo("my-repo", str(tmp_path))
        assert ex._repo_paths["my-repo"] == tmp_path

    def test_register_repo_accepts_path(self, tmp_path: Path) -> None:
        ex = PatternExtractor()
        ex.register_repo("r", tmp_path)
        assert ex._repo_paths["r"] == tmp_path

    def test_create_draft_unknown_repo_raises(self) -> None:
        ex = PatternExtractor()
        with pytest.raises(ValueError, match="Unknown repo"):
            ex.create_draft_from_project("no-such", "cat", "name")

    def test_create_draft_finds_py_files(self, tmp_path: Path) -> None:
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("x = 1")
        (tmp_path / "src" / "helper.yaml").write_text("key: val")
        (tmp_path / "__pycache__").mkdir()
        (tmp_path / "__pycache__" / "cache.pyc").write_text("")

        ex = PatternExtractor()
        ex.register_repo("r", tmp_path)
        draft = ex.create_draft_from_project("r", "scaffolding", "test-pattern")

        file_paths = [f["path"] for f in draft.files]
        assert any("main.py" in p for p in file_paths)
        assert any("helper.yaml" in p for p in file_paths)
        assert not any("pycache" in p for p in file_paths)

    def test_create_draft_with_custom_include_patterns(self, tmp_path: Path) -> None:
        (tmp_path / "keep.py").write_text("x")
        (tmp_path / "skip.py").write_text("y")

        ex = PatternExtractor()
        ex.register_repo("r", tmp_path)
        draft = ex.create_draft_from_project(
            "r", "cat", "nm", include_patterns=[r"keep"]
        )
        file_paths = [f["path"] for f in draft.files]
        assert any("keep.py" in p for p in file_paths)
        assert not any("skip.py" in p for p in file_paths)

    def test_create_draft_with_exclude_patterns(self, tmp_path: Path) -> None:
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "good.py").write_text("x")
        (tmp_path / "src" / "bad.yaml").write_text("k: v")

        ex = PatternExtractor()
        ex.register_repo("r", tmp_path)
        draft = ex.create_draft_from_project(
            "r", "cat", "nm", exclude_patterns=[r"bad"]
        )
        file_paths = [f["path"] for f in draft.files]
        assert not any("bad" in p for p in file_paths)

    def test_create_draft_dirs_collected(self, tmp_path: Path) -> None:
        subdir = tmp_path / "mydir"
        subdir.mkdir()
        (subdir / "init.py").write_text("")

        ex = PatternExtractor()
        ex.register_repo("r", tmp_path)
        draft = ex.create_draft_from_project("r", "cat", "nm")

        dir_paths = [d["path"] for d in draft.dirs]
        assert any("mydir" in p for p in dir_paths)

    def test_suggest_patterns_fewer_than_2_repos_returns_empty(self) -> None:
        ex = PatternExtractor()
        ex.register_repo("single", Path("/tmp"))
        assert ex.suggest_patterns() == []

    def test_suggest_patterns_finds_common_dirs(self, tmp_path: Path) -> None:
        repo_a = tmp_path / "repo_a"
        repo_b = tmp_path / "repo_b"
        for r in (repo_a, repo_b):
            (r / "core").mkdir(parents=True)
            (r / "core" / "utils.py").write_text("x")

        ex = PatternExtractor()
        ex.register_repo("a", repo_a)
        ex.register_repo("b", repo_b)
        drafts = ex.suggest_patterns(min_prevalence=0.5)
        names = [d.name for d in drafts]
        assert any("core" in n for n in names)

    def test_suggest_patterns_sorted_by_confidence_desc(self, tmp_path: Path) -> None:
        repo_a = tmp_path / "ra"
        repo_b = tmp_path / "rb"
        for r in (repo_a, repo_b):
            (r / "core").mkdir(parents=True)
            (r / "core" / "mod.py").write_text("")
        repo_a_extra = repo_a / "extras"
        repo_a_extra.mkdir()
        (repo_a_extra / "x.py").write_text("")

        ex = PatternExtractor()
        ex.register_repo("a", repo_a)
        ex.register_repo("b", repo_b)
        drafts = ex.suggest_patterns(min_prevalence=0.5)
        confidences = [d.confidence for d in drafts]
        assert confidences == sorted(confidences, reverse=True)


class TestHelperFunctions:
    def test_dir_in_repo_match(self) -> None:
        assert _dir_in_repo("core", ["core/utils.py", "core/models.py"])

    def test_dir_in_repo_no_match(self) -> None:
        assert not _dir_in_repo("core", ["score/main.py", "discord/app.py"])

    def test_dir_in_repo_no_partial_name_match(self) -> None:
        assert not _dir_in_repo("cor", ["core/utils.py"])

    def test_get_sorted_path_list(self, tmp_path: Path) -> None:
        (tmp_path / "b.py").write_text("")
        (tmp_path / "a.py").write_text("")
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "c.py").write_text("")
        paths = _get_sorted_path_list(tmp_path)
        assert "a.py" in paths
        assert "b.py" in paths
        assert "sub/c.py" in paths

    def test_find_common_subtrees_threshold(self) -> None:
        structures = {
            "r1": ["core/a.py", "core/b.py", "extras/x.py"],
            "r2": ["core/a.py", "other/z.py"],
        }
        result = _find_common_subtrees(structures, min_prevalence=1.0)
        assert "core" in result
        assert "extras" not in result

    def test_find_common_subtrees_root_files_skipped(self) -> None:
        structures = {"r1": ["readme.txt"], "r2": ["readme.txt"]}
        result = _find_common_subtrees(structures, min_prevalence=0.5)
        assert result == {}

    def test_find_common_files(self) -> None:
        structures = {
            "r1": ["core/utils.py", "core/models.py"],
            "r2": ["core/utils.py", "core/views.py"],
        }
        common = _find_common_files(structures, "core", min_prevalence=1.0)
        assert "utils.py" in common
        assert "models.py" not in common

    def test_infer_category_adapters(self) -> None:
        assert _infer_category("adapters/base") == "adapters"

    def test_infer_category_components(self) -> None:
        assert _infer_category("components/ui") == "components"
        assert _infer_category("templates/base") == "components"

    def test_infer_category_deployment(self) -> None:
        assert _infer_category("deploy") == "deployment"
        assert _infer_category("deployment") == "deployment"
        assert _infer_category("docker") == "deployment"

    def test_infer_category_settings(self) -> None:
        assert _infer_category("settings") == "scaffolding"
        assert _infer_category("config") == "scaffolding"

    def test_infer_category_default(self) -> None:
        assert _infer_category("random_dir") == "scaffolding"
