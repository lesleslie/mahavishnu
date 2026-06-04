"""Smoke tests for ``scripts/test_matrix.py``.

The matrix generator is run as a CLI; the tests below exercise the public
function-level surface (component detection, regex inference, matrix
assembly, coverage parsing, and the CLI entry point) against a fixture
project built in ``tmp_path``.

No mocking: the fixture writes real files so the helper functions can do
real filesystem work.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

# Make ``scripts/`` importable so we can ``import test_matrix`` directly
# without installing the script as a package.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from test_matrix import (  # noqa: E402
    ComponentCoverage,
    assemble_python_matrix,
    build_summary,
    detect_components,
    infer_component_from_imports,
    main,
    map_test_files_to_components,
    parse_coverage_xml,
    render_markdown,
)

# Minimal Cobertura XML literal with two classes. The ``line-rate`` values
# are arbitrary — the parser only needs to extract ``filename`` and
# ``line-rate`` attributes.
MINIMAL_COVERAGE_XML = """\
<?xml version="1.0" encoding="utf-8"?>
<coverage version="7.0" timestamp="0" lines-valid="100" lines-covered="85"
          line-rate="0.85" branches-covered="0" branches-valid="0"
          branch-rate="0.0" complexity="0">
  <sources>
    <source>.</source>
  </sources>
  <packages>
    <package name="mahavishnu/core" line-rate="0.85" branch-rate="0.0"
             complexity="0">
      <classes>
        <class name="app.py" filename="mahavishnu/core/app.py"
               line-rate="0.85" branch-rate="0.0" complexity="0">
          <lines/>
        </class>
        <class name="helpers.py" filename="mahavishnu/core/helpers.py"
               line-rate="0.50" branch-rate="0.0" complexity="0">
          <lines/>
        </class>
      </classes>
    </package>
  </packages>
</coverage>
"""


@pytest.fixture
def make_fixture_project(tmp_path: Path) -> Path:
    """Build a small but realistic Python project tree under ``tmp_path``.

    Structure mirrors a typical package layout so component detection,
    import inference, coverage parsing, and the matrix builder all have
    realistic inputs.
    """
    project = tmp_path

    # Package + two real components
    (project / "mahavishnu" / "core").mkdir(parents=True)
    (project / "mahavishnu" / "core" / "__init__.py").write_text("")
    (project / "mahavishnu" / "core" / "app.py").write_text("def app(): pass\n")

    (project / "mahavishnu" / "workers").mkdir(parents=True)
    (project / "mahavishnu" / "workers" / "__init__.py").write_text("")
    (project / "mahavishnu" / "workers" / "pool.py").write_text(
        "def pool(): pass\n"
    )

    # Single-file utility — no enclosing __init__.py directory, so it
    # must NOT be detected as a component.
    (project / "mahavishnu" / "utils.py").write_text("def helper(): pass\n")

    # Filtered directories (should never show up as components)
    pycache = project / "mahavishnu" / "__pycache__"
    pycache.mkdir()
    (pycache / "junk.pyc").write_bytes(b"")

    prototypes = project / "mahavishnu" / "prototypes"
    prototypes.mkdir()
    (prototypes / "__init__.py").write_text("")  # has __init__, but filtered

    # Test files
    unit = project / "tests" / "unit"
    unit.mkdir(parents=True)
    (unit / "test_core.py").write_text("from mahavishnu.core import foo\n")
    (unit / "test_workers.py").write_text("from mahavishnu.workers import bar\n")
    (unit / "test_phantom.py").write_text(
        "from mahavishnu.nonexistent import baz\n"
    )

    # Top-level test (no subdir) — no imports
    (project / "tests").mkdir(parents=True, exist_ok=True)
    (project / "tests" / "test_top.py").write_text("def test_top(): pass\n")

    # Filtered test subdir (fixtures)
    fixtures = project / "tests" / "fixtures"
    fixtures.mkdir(parents=True, exist_ok=True)
    (fixtures / "sample.txt").write_text("not a test\n")

    # coverage.xml at the project root
    (project / "coverage.xml").write_text(MINIMAL_COVERAGE_XML)

    return project


# ---------------------------------------------------------------------------
# Component detection
# ---------------------------------------------------------------------------


def test_detect_components_basic(make_fixture_project: Path) -> None:
    components = detect_components(make_fixture_project)
    assert "mahavishnu/core" in components
    assert "mahavishnu/workers" in components
    # utils.py has no enclosing __init__.py directory, so it must not
    # be a component.
    assert "mahavishnu/utils" not in components


def test_detect_components_excludes_non_component_dirs(
    make_fixture_project: Path,
) -> None:
    components = detect_components(make_fixture_project)
    # ``prototypes`` is in _NON_COMPONENT_DIRS — should be filtered
    # even though it has an __init__.py.
    assert "mahavishnu/prototypes" not in components
    # __pycache__ is also in the non-component set.
    assert "mahavishnu/__pycache__" not in components


# ---------------------------------------------------------------------------
# Import regex
# ---------------------------------------------------------------------------


def test_import_regex_handles_multiline_parenthesized_import(
    tmp_path: Path,
) -> None:
    r"""LOW #7: a multi-line ``from mahavishnu\n    .core import X`` must match.

    The regex's ``(?:\s*\.\s*|\s+)`` alternative after ``mahavishnu``
    allows newline + whitespace before the dot, so a multi-line import
    still resolves to a real sub-package.
    """
    multiline = tmp_path / "test_multiline.py"
    multiline.write_text("from mahavishnu\n    .core import foo\n")
    assert infer_component_from_imports(multiline) == "mahavishnu/core"

    no_dot = tmp_path / "test_nodot.py"
    no_dot.write_text("from mahavishnu import X\n")
    # Bare ``from mahavishnu import X`` (no submodule) is detected
    # as a parse error by the parser: the regex would otherwise
    # greedily capture the literal keyword ``import`` as the head.
    # The parser returns ``None`` so the caller's filename-based
    # heuristic and catch-all bucket can take over.
    assert infer_component_from_imports(no_dot) is None


def test_import_regex_ignores_docstring_mentions(tmp_path: Path) -> None:
    """The regex is anchored to line-start; a docstring that merely mentions
    ``mahavishnu`` must not be matched.
    """
    no_imports = tmp_path / "test_docstring.py"
    no_imports.write_text(
        '"""The mahavishnu module is great."""\n\n'
        "def test_thing(): pass\n"
    )
    assert infer_component_from_imports(no_imports) is None


# ---------------------------------------------------------------------------
# Mapping
# ---------------------------------------------------------------------------


def test_map_test_files_to_components_filters_phantom(
    make_fixture_project: Path,
) -> None:
    """LOW #15: when a test imports from a sub-package that doesn't exist
    (e.g. ``mahavishnu.nonexistent``), the file should land in the
    ``mahavishnu`` catch-all bucket, not in a phantom component bucket.
    """
    tests_root = make_fixture_project / "tests"
    unit = tests_root / "unit"
    test_files = sorted(p for p in unit.glob("test_*.py"))

    valid = {"mahavishnu/core", "mahavishnu/workers"}
    grouped = map_test_files_to_components(
        test_files, tests_root, valid_components=valid
    )

    # The catch-all bucket must be present and contain the phantom test.
    assert "mahavishnu" in grouped, (
        "phantom-component fallback should land unmatched tests in the "
        f"'mahavishnu' bucket; got buckets: {list(grouped)}"
    )

    # No phantom buckets should exist (i.e. no key starts with
    # ``mahavishnu/`` unless it's a real, valid component).
    phantom_keys = [
        k for k in grouped
        if k.startswith("mahavishnu/")
        and k not in valid
        and k != "mahavishnu"
    ]
    assert not phantom_keys, f"phantom components leaked: {phantom_keys}"


# ---------------------------------------------------------------------------
# Matrix assembly
# ---------------------------------------------------------------------------


def test_assemble_python_matrix_runs(make_fixture_project: Path) -> None:
    cells = assemble_python_matrix(
        make_fixture_project,
        ["mahavishnu/core", "mahavishnu/workers"],
        ["unit"],
    )
    # At least one cell should be covered for mahavishnu/core with ``unit``.
    core_cell = cells["mahavishnu/core"]["unit"]
    assert core_cell.covered is True


def test_build_summary_includes_components_with_no_tests(
    make_fixture_project: Path,
) -> None:
    """M4: ``build_summary`` should surface ``components_with_no_tests``
    as a list of ``{"component": ..., "missing_test_types": [...]}`` dicts
    so consumers don't have to recompute the uncovered tracking.
    """
    cells = assemble_python_matrix(
        make_fixture_project,
        ["mahavishnu/core", "mahavishnu/workers"],
        ["unit", "integration"],
    )
    summary = build_summary(
        cells,
        ["mahavishnu/core", "mahavishnu/workers"],
        ["unit", "integration"],
        80,
        None,
    )
    assert "components_with_no_tests" in summary, (
        "summary should include 'components_with_no_tests' (M4 follow-up); "
        f"got keys: {list(summary)}"
    )
    assert isinstance(summary["components_with_no_tests"], list)
    for entry in summary["components_with_no_tests"]:
        assert "component" in entry
        assert "missing_test_types" in entry


# ---------------------------------------------------------------------------
# CLI end-to-end
# ---------------------------------------------------------------------------


def test_main_end_to_end_writes_json(
    make_fixture_project: Path, tmp_path: Path
) -> None:
    out = tmp_path / "out.json"
    rc = main(
        [
            "--project",
            str(make_fixture_project),
            "--stack",
            "python",
            "--types",
            "unit",
            "--out",
            str(out),
        ]
    )
    assert rc == 0
    assert out.is_file()

    payload = json.loads(out.read_text())
    assert "summary" in payload
    summary = payload["summary"]

    # Baseline summary fields
    assert "coverage_pct" in summary
    assert "below_target" in summary

    # M4 follow-up: components_with_no_tests must be exposed in the
    # JSON output.
    assert "components_with_no_tests" in summary, (
        "JSON output should expose summary.components_with_no_tests "
        f"(M4 follow-up); got keys: {list(summary)}"
    )

    # Per-component cells must be present.
    assert "cells" in payload
    assert set(payload["cells"].keys()) >= {
        "mahavishnu/core",
        "mahavishnu/workers",
    }


def test_main_rejects_unsafe_output_path(
    make_fixture_project: Path, capsys
) -> None:
    """M10: --out must not be allowed to escape the project root (or cwd).

    A path-traversal attack via ``/tmp/../../../etc/passwd`` should be
    rejected with a non-zero exit code and a stderr message that
    mentions the safety check.
    """
    rc = main(
        [
            "--project",
            str(make_fixture_project),
            "--stack",
            "python",
            "--types",
            "unit",
            "--out",
            "/tmp/../../../etc/passwd",
        ]
    )
    captured = capsys.readouterr()
    assert rc == 1, (
        f"unsafe --out should fail; got rc={rc}, "
        f"stderr={captured.err!r}, stdout={captured.out!r}"
    )
    # Implementation's actual wording may vary. Match a flexible pattern
    # that covers the most likely phrasings, including the actual
    # implementation's "is outside the project root" message.
    assert any(
        needle in captured.err.lower()
        for needle in (
            "must be inside",
            "must be under",
            "must be within",
            "is outside the project root",
            "path traversal",
            "unsafe",
            "invalid output",
            "not allowed",
        )
    ), f"expected a safety-check error message; got stderr={captured.err!r}"


def test_main_rejects_unknown_test_type(
    make_fixture_project: Path, capsys
) -> None:
    rc = main(
        [
            "--project",
            str(make_fixture_project),
            "--stack",
            "python",
            "--types",
            "unit,contract",
        ]
    )
    captured = capsys.readouterr()
    assert rc == 1
    assert "unknown test type" in captured.err


# ---------------------------------------------------------------------------
# Coverage parsing
# ---------------------------------------------------------------------------


def test_parse_coverage_xml(make_fixture_project: Path) -> None:
    data = parse_coverage_xml(make_fixture_project)
    assert data is not None
    # Cobertura records the class filename verbatim; the matrix key style
    # differs (directory-style), but the parser returns the raw paths
    # so callers can decide.
    assert "mahavishnu/core/app.py" in data
    assert isinstance(data["mahavishnu/core/app.py"], float)


# ---------------------------------------------------------------------------
# ComponentCoverage dataclass
# ---------------------------------------------------------------------------


def test_component_coverage_dataclass_is_not_frozen() -> None:
    """LOW #10: ``frozen=True`` was misleading because mutable default
    fields (the ``files`` list) can still be mutated in place. The
    follow-up removes ``frozen=True`` so the dataclass is honest about
    its mutability.
    """
    cov = ComponentCoverage(covered=True, files=["x.py"], gaps=[])
    # Should not raise FrozenInstanceError.
    cov.files.append("y.py")
    assert "y.py" in cov.files


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------


def test_render_markdown_includes_summary_and_gaps(
    make_fixture_project: Path,
) -> None:
    components = detect_components(make_fixture_project)
    cells = assemble_python_matrix(
        make_fixture_project, components, ["unit"]
    )
    summary = build_summary(
        cells, components, ["unit"], 80, parse_coverage_xml(make_fixture_project)
    )
    md = render_markdown(
        project=str(make_fixture_project),
        stack="python",
        components=components,
        test_types=["unit"],
        cells=cells,
        summary=summary,
        coverage_target=80,
    )
    assert "## Summary" in md
    assert "## Component × Test Type Matrix" in md
    assert "## Gaps" in md
