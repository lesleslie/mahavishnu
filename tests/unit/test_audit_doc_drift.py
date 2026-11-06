"""Unit tests for the audit_doc_drift.py script.

Covers the reference classifier, the symbol collector, the status-to-severity
ladder, and the end-to-end scan against a synthetic repository tree.

The end-to-end tests build a throwaway tree rather than asserting against the
live repository, so they stay stable when the real corpus changes.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from scripts.audit_doc_drift import (
    Baseline,
    classify_token,
    collect_symbols,
    looks_like_config_key,
    main,
    read_status,
    strip_fenced_code,
)

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def sample_repo(tmp_path: Path) -> Path:
    """Build a minimal repository tree with a package and a design document."""
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "mod.py").write_text(
        "def foo():\n    pass\n\n\n"
        "class Bar:\n    def baz(self):\n        pass\n\n\n"
        "alias = foo\n",
        encoding="utf-8",
    )

    specs = tmp_path / "docs" / "specs"
    specs.mkdir(parents=True)
    (specs / "design.md").write_text(
        "---\n"
        "status: shipped\n"
        "role: canonical\n"
        "date: 2026-01-01\n"
        "last_reviewed: 2026-01-01\n"
        "superseded_by: null\n"
        "topic: convergence-control-plane\n"
        "---\n"
        "\n"
        "# Design\n"
        "\n"
        "The entry point is `pkg/mod.py:foo`.\n"
        "The class is `pkg/mod.py::Bar`.\n"
        "The module is `pkg.mod`.\n"
        "The alias is `pkg/mod.py:alias`.\n"
        "\n"
        "```python\n"
        "# fenced code must not be scanned\n"
        "missing = `pkg/never_exists.py`\n"
        "```\n"
        "\n"
        "A missing file is `pkg/gone.py`.\n"
        "A missing symbol is `pkg/mod.py::Nope`.\n",
        encoding="utf-8",
    )
    return tmp_path


class TestStripFencedCode:
    def test_removes_fenced_blocks_but_keeps_line_count(self) -> None:
        text = "before\n```\ninside\n```\nafter\n"
        stripped = strip_fenced_code(text)
        assert "inside" not in stripped
        assert "before" in stripped
        assert "after" in stripped
        assert len(stripped.splitlines()) == len(text.splitlines())


class TestClassifyToken:
    def test_classifies_path(self, tmp_path: Path) -> None:
        assert classify_token("pkg/mod.py", tmp_path) == ("path", "pkg/mod.py", None, False)

    def test_classifies_path_with_symbol(self, tmp_path: Path) -> None:
        assert classify_token("pkg/mod.py::Bar", tmp_path) == ("path", "pkg/mod.py", "Bar", False)

    def test_classifies_bare_filename(self, tmp_path: Path) -> None:
        assert classify_token("README.md", tmp_path) == ("path", "README.md", None, True)

    def test_classifies_dotted_module_only_for_real_packages(self, tmp_path: Path) -> None:
        (tmp_path / "pkg").mkdir()
        assert classify_token("pkg.mod", tmp_path) == ("module", "pkg.mod", None, False)
        assert classify_token("nosuchpkg.mod", tmp_path) is None

    def test_rejects_placeholders_and_urls(self, tmp_path: Path) -> None:
        assert classify_token("2026-XX-XX-name.md", tmp_path) is None
        assert classify_token("pkg/...", tmp_path) is None
        assert classify_token("https://example.com/x.py", tmp_path) is None
        assert classify_token("pkg/<name>.py", tmp_path) is None

    def test_strips_trailing_call_and_colon(self, tmp_path: Path) -> None:
        assert classify_token("pkg/mod.py:foo()", tmp_path) == ("path", "pkg/mod.py", "foo", False)
        assert classify_token("settings/models.yaml:bifrost:", tmp_path) == (
            "path",
            "settings/models.yaml",
            "bifrost",
            False,
        )

    def test_line_numbers_are_not_symbols(self, tmp_path: Path) -> None:
        assert classify_token("pkg/mod.py:120", tmp_path) == ("path", "pkg/mod.py", None, False)
        assert classify_token("pkg/mod.py:20-30", tmp_path) == ("path", "pkg/mod.py", None, False)


class TestLooksLikeConfigKey:
    def test_lowercase_dotted_token_is_config_key(self) -> None:
        assert looks_like_config_key("settings.load") is True
        assert looks_like_config_key("mahavishnu.log") is True
        assert looks_like_config_key("settings.models.yaml") is True

    def test_class_named_token_is_not_config_key(self) -> None:
        assert looks_like_config_key("mahavishnu.core.config.Settings") is False


class TestCollectSymbols:
    def test_collects_functions_classes_methods_and_aliases(self, tmp_path: Path) -> None:
        target = tmp_path / "mod.py"
        target.write_text(
            "def foo():\n    pass\n\n\n"
            "class Bar:\n    def baz(self):\n        pass\n\n\n"
            "alias = foo\n",
            encoding="utf-8",
        )
        symbols = collect_symbols(target)
        assert symbols is not None
        assert {"foo", "Bar", "Bar.baz", "alias"} <= symbols

    def test_returns_none_for_unparsable_file(self, tmp_path: Path) -> None:
        broken = tmp_path / "broken.py"
        broken.write_text("def (((:\n", encoding="utf-8")
        assert collect_symbols(broken) is None

    def test_non_python_file_has_no_symbols(self, tmp_path: Path) -> None:
        config = tmp_path / "config.yaml"
        config.write_text("key: value\n", encoding="utf-8")
        assert collect_symbols(config) == set()


class TestReadStatus:
    def test_reads_frontmatter_status(self) -> None:
        text = "---\nstatus: shipped\nrole: canonical\n---\n\nbody\n"
        assert read_status(text) == "shipped"

    def test_missing_frontmatter_is_unknown(self) -> None:
        assert read_status("no frontmatter here\n") == "unknown"


class TestEndToEndScan:
    def test_detects_missing_path_and_symbol(self, sample_repo: Path, capsys) -> None:
        exit_code = main(
            [
                "--repo-root",
                str(sample_repo),
                "--docs",
                "docs/specs",
                "--json",
            ]
        )
        payload = json.loads(capsys.readouterr().out)
        references = {f["reference"] for f in payload["findings"]}
        assert "pkg/gone.py" in references
        assert "pkg/mod.py::Nope" in references
        assert exit_code == 1

    def test_ignores_fenced_code_references(self, sample_repo: Path, capsys) -> None:
        main(["--repo-root", str(sample_repo), "--docs", "docs/specs", "--json"])
        payload = json.loads(capsys.readouterr().out)
        references = {f["reference"] for f in payload["findings"]}
        assert "pkg/never_exists.py" not in references

    def test_resolves_live_references(self, sample_repo: Path, capsys) -> None:
        main(["--repo-root", str(sample_repo), "--docs", "docs/specs", "--json"])
        payload = json.loads(capsys.readouterr().out)
        references = {f["reference"] for f in payload["findings"]}
        assert "pkg/mod.py:foo" not in references
        assert "pkg/mod.py::Bar" not in references
        assert "pkg/mod.py:alias" not in references

    def test_draft_documents_do_not_fail_the_gate(self, tmp_path: Path, capsys) -> None:
        specs = tmp_path / "docs" / "specs"
        specs.mkdir(parents=True)
        (specs / "draft.md").write_text(
            "---\nstatus: draft\n---\n\nPlanned file `pkg/not_yet.py`.\n",
            encoding="utf-8",
        )
        exit_code = main(["--repo-root", str(tmp_path), "--docs", "docs/specs", "--json"])
        payload = json.loads(capsys.readouterr().out)
        assert payload["errors"] == 0
        assert exit_code == 0

    def test_semantic_claims_are_listed_for_review(self, sample_repo: Path, capsys) -> None:
        main(["--repo-root", str(sample_repo), "--docs", "docs/specs", "--json"])
        payload = json.loads(capsys.readouterr().out)
        assert "semantic_review_items" in payload


class TestBaselineRatchet:
    def test_baseline_absorbs_known_findings(self, sample_repo: Path, tmp_path: Path, capsys) -> None:
        baseline_path = tmp_path / "baseline.json"
        main(
            [
                "--repo-root",
                str(sample_repo),
                "--docs",
                "docs/specs",
                "--write-baseline",
                str(baseline_path),
            ]
        )
        capsys.readouterr()

        exit_code = main(
            [
                "--repo-root",
                str(sample_repo),
                "--docs",
                "docs/specs",
                "--baseline",
                str(baseline_path),
                "--json",
            ]
        )
        payload = json.loads(capsys.readouterr().out)
        assert payload["errors"] == 0
        assert payload["baseline_known"] > 0
        assert exit_code == 0

    def test_new_drift_still_fails_with_a_baseline(self, sample_repo: Path, tmp_path: Path, capsys) -> None:
        baseline_path = tmp_path / "baseline.json"
        main(
            [
                "--repo-root",
                str(sample_repo),
                "--docs",
                "docs/specs",
                "--write-baseline",
                str(baseline_path),
            ]
        )
        capsys.readouterr()

        # A new document introduces drift the baseline has never seen.
        specs = sample_repo / "docs" / "specs"
        (specs / "new.md").write_text(
            "---\nstatus: shipped\n---\n\nReferences `pkg/brand_new_missing.py`.\n",
            encoding="utf-8",
        )
        exit_code = main(
            [
                "--repo-root",
                str(sample_repo),
                "--docs",
                "docs/specs",
                "--baseline",
                str(baseline_path),
                "--json",
            ]
        )
        payload = json.loads(capsys.readouterr().out)
        assert payload["errors"] == 1
        assert exit_code == 1

    def test_baseline_round_trips(self, sample_repo: Path, tmp_path: Path, capsys) -> None:
        baseline_path = tmp_path / "baseline.json"
        main(
            [
                "--repo-root",
                str(sample_repo),
                "--docs",
                "docs/specs",
                "--write-baseline",
                str(baseline_path),
            ]
        )
        capsys.readouterr()
        baseline = Baseline.load(baseline_path)
        assert baseline.known
        assert all(len(entry) == 3 for entry in baseline.known)
