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
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

# ``scripts/`` is added to ``sys.path`` by the root ``conftest.py`` so we
# can ``import test_matrix`` directly without installing it as a package.
from test_matrix import (  # noqa: E402
    ComponentCoverage,
    assemble_go_matrix,
    assemble_node_matrix,
    assemble_python_matrix,
    build_summary,
    detect_components,
    infer_component_from_filename,
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
    (project / "mahavishnu" / "workers" / "pool.py").write_text("def pool(): pass\n")

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
    (unit / "test_phantom.py").write_text("from mahavishnu.nonexistent import baz\n")

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
    no_imports.write_text('"""The mahavishnu module is great."""\n\ndef test_thing(): pass\n')
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
    grouped = map_test_files_to_components(test_files, tests_root, valid_components=valid)

    # The catch-all bucket must be present and contain the phantom test.
    assert "mahavishnu" in grouped, (
        "phantom-component fallback should land unmatched tests in the "
        f"'mahavishnu' bucket; got buckets: {list(grouped)}"
    )

    # No phantom buckets should exist (i.e. no key starts with
    # ``mahavishnu/`` unless it's a real, valid component).
    phantom_keys = [
        k for k in grouped if k.startswith("mahavishnu/") and k not in valid and k != "mahavishnu"
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


def test_main_end_to_end_writes_json(make_fixture_project: Path, tmp_path: Path) -> None:
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


def test_main_rejects_unsafe_output_path(make_fixture_project: Path, capsys) -> None:
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
        f"unsafe --out should fail; got rc={rc}, stderr={captured.err!r}, stdout={captured.out!r}"
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


def test_main_rejects_out_equal_to_project_root(make_fixture_project: Path, capsys) -> None:
    """T3.1: --out pointing at the project root itself (a
    confused-deputy case) must be rejected. The directory exists, the
    path is technically "under" the project, but writing the JSON
    matrix INTO the project directory would clobber unrelated state.
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
            str(make_fixture_project),
        ]
    )
    captured = capsys.readouterr()
    assert rc == 1, (
        f"--out == project root should fail; got rc={rc}, "
        f"stderr={captured.err!r}, stdout={captured.out!r}"
    )
    assert any(
        needle in captured.err.lower()
        for needle in (
            "project root itself",
            "refusing to overwrite the project directory",
        )
    ), f"expected a project-root-equals error; got stderr={captured.err!r}"


def test_main_rejects_unknown_test_type(make_fixture_project: Path, capsys) -> None:
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

    Two guards are needed: list-mutation passes regardless of
    ``frozen=True`` (Python's frozen-dataclass check only blocks
    attribute *assignment*, not in-place list mutation), so we also
    assert that assigning a new value to a field works.
    """
    cov = ComponentCoverage(covered=True, files=["x.py"], gaps=[])

    # Guard 1: in-place list mutation must not raise.
    cov.files.append("y.py")
    assert "y.py" in cov.files

    # Guard 2: attribute *assignment* must not raise FrozenInstanceError.
    # If the dataclass is still declared ``frozen=True``, this raises
    # ``dataclasses.FrozenInstanceError`` and the test fails — the
    # whole point of LOW #10 was to remove the misleading ``frozen=True``.
    try:
        cov.covered = False
    except AttributeError as exc:  # FrozenInstanceError subclasses AttributeError
        pytest.fail(f"ComponentCoverage should not be frozen; assignment raised: {exc!r}")
    assert cov.covered is False


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------


def test_render_markdown_includes_summary_and_gaps(
    make_fixture_project: Path,
) -> None:
    components = detect_components(make_fixture_project)
    cells = assemble_python_matrix(make_fixture_project, components, ["unit"])
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


# ---------------------------------------------------------------------------
# Node/Go matrix assembly (Tier 2 — was uncovered)
# ---------------------------------------------------------------------------


def test_assemble_node_matrix_runs(tmp_path: Path) -> None:
    """The Node assembler walks for ``*.test.ts`` / ``*.test.js`` /
    ``__tests__`` and groups them by component directory. Smoke test:
    build a fixture with a single Node test file and assert the cell is
    covered.
    """
    project = tmp_path
    (project / "package.json").write_text("{}")
    (project / "src" / "foo").mkdir(parents=True)
    (project / "src" / "foo" / "foo.test.ts").write_text("test('foo', () => {});\n")

    cells = assemble_node_matrix(project, components=["src/foo"], test_types=["unit"])
    assert "src/foo" in cells
    cell = cells["src/foo"]["unit"]
    assert cell.covered is True
    assert any("foo.test.ts" in f for f in cell.files)


def test_assemble_go_matrix_runs(tmp_path: Path) -> None:
    """The Go assembler walks for ``*_test.go`` and groups by package dir."""
    project = tmp_path
    (project / "go.mod").write_text("module example.com/foo\n")
    (project / "pkg" / "foo").mkdir(parents=True)
    (project / "pkg" / "foo" / "foo_test.go").write_text(
        "package foo\nfunc TestFoo(t *testing.T) {}\n"
    )

    cells = assemble_go_matrix(project, components=["pkg/foo"], test_types=["unit"])
    assert "pkg/foo" in cells
    cell = cells["pkg/foo"]["unit"]
    assert cell.covered is True
    assert any("foo_test.go" in f for f in cell.files)


def test_assemble_node_matrix_empty_test_types_handled(
    tmp_path: Path,
) -> None:
    """M2 follow-up: ``assemble_node_matrix`` falls back to ``"unit"``
    when ``test_types`` is empty (``test_types[0] if test_types else
    "unit"``), so the function does NOT raise ``IndexError``. Note:
    the inner cell loop is ``for t in test_types``, which is also
    empty, so each component's inner dict is empty. The CLI rejects
    empty ``--types`` upstream; this test pins the library-level
    behaviour to "no IndexError, return a matrix shell with empty
    inner dicts".
    """
    (tmp_path / "package.json").write_text("{}")
    (tmp_path / "src" / "foo").mkdir(parents=True)
    (tmp_path / "src" / "foo" / "foo.test.ts").write_text("test('foo', () => {});\n")
    # Should not raise IndexError on empty test_types.
    cells = assemble_node_matrix(tmp_path, components=["src/foo"], test_types=[])
    assert "src/foo" in cells
    # Inner dict is empty because the for-t-in-test_types loop never
    # executes. This is the current behaviour; if a future change makes
    # the function fall back to ``["unit"]`` for empty input, update
    # this assertion to expect ``cells["src/foo"]["unit"].covered``.
    assert cells["src/foo"] == {}


# ---------------------------------------------------------------------------
# Stack CLI gating (Tier 2 — was uncovered)
# ---------------------------------------------------------------------------


def test_main_mixed_stack(make_fixture_project: Path, tmp_path: Path) -> None:
    """M2 follow-up: ``--stack mixed`` should pick up BOTH the Python
    package components (via ``detect_components``) AND the Node
    components (via ``src/<dir>`` and ``packages*``), gating each
    non-Python detection on its project-root marker (``package.json``).
    """
    out = tmp_path / "out.json"
    rc = main(
        [
            "--project",
            str(make_fixture_project),
            "--stack",
            "mixed",
            "--types",
            "unit",
            "--out",
            str(out),
        ]
    )
    assert rc == 0
    payload = json.loads(out.read_text())
    components = payload["components"]
    # Python components from ``detect_components``.
    assert "mahavishnu/core" in components
    assert "mahavishnu/workers" in components
    # Node components gated on package.json — fixture has no
    # package.json so the Node branch is skipped, which is the safe
    # default. (See ``test_m2_stack_python_only`` for the negative case.)
    assert "src/foo" not in components


def test_m2_python_only_no_phantom_go_or_node(make_fixture_project: Path, tmp_path: Path) -> None:
    """M2 follow-up: a Python-only fixture (no ``go.mod``, no
    ``package.json``) running with ``--stack python`` must NOT report
    phantom Go/Node components like ``htmlcov/``, ``dist/``,
    ``backups/``, ``docs``, ``scripts``, etc.
    """
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
    payload = json.loads(out.read_text())
    components = set(payload["components"])
    # None of these are real Python components; the Python stack path
    # in ``main()`` must skip them entirely.
    for phantom in (
        "htmlcov",
        "dist",
        "backups",
        "docs",
        "scripts",
        "test",
        "tests",
        ".git",
        ".github",
    ):
        assert phantom not in components, (
            f"phantom {phantom!r} leaked into Python-stack components: {sorted(components)}"
        )


def test_m2_stack_go_without_gomod_returns_error(tmp_path: Path, capsys) -> None:
    """M2 follow-up: ``--stack go`` against a fixture WITHOUT
    ``go.mod`` should produce no components and exit non-zero.
    """
    out = tmp_path / "out.json"
    rc = main(
        [
            "--project",
            str(tmp_path),
            "--stack",
            "go",
            "--types",
            "unit",
            "--out",
            str(out),
        ]
    )
    captured = capsys.readouterr()
    assert rc == 1, (
        f"go stack with no go.mod should fail; got rc={rc}, "
        f"stderr={captured.err!r}, stdout={captured.out!r}"
    )
    assert "no components detected" in captured.err


def test_t32_force_stack_go_in_polyglot_monorepo(tmp_path: Path, capsys) -> None:
    """T3.2: A polyglot monorepo that has Go files in ``cmd/*.go`` but
    no top-level ``go.mod`` (or has a Node workspace without a
    ``package.json``) should still get its Go components when the
    caller passes ``--force-stack go`` — that's the whole point of
    the escape hatch introduced for the M2 marker gating.
    """
    # Build a fixture: no go.mod, no package.json, but Go files in cmd/.
    (tmp_path / "cmd" / "foo").mkdir(parents=True)
    (tmp_path / "cmd" / "foo" / "foo.go").write_text("package foo\n")
    (tmp_path / "cmd" / "foo" / "foo_test.go").write_text(
        "package foo\nfunc TestFoo(t *testing.T) {}\n"
    )

    out = tmp_path / "out.json"
    rc = main(
        [
            "--project",
            str(tmp_path),
            "--stack",
            "go",
            "--types",
            "unit",
            "--force-stack",
            "go",
            "--out",
            str(out),
        ]
    )
    captured = capsys.readouterr()
    assert rc == 0, (
        f"force-stack go with Go files present should succeed; "
        f"got rc={rc}, stderr={captured.err!r}, stdout={captured.out!r}"
    )
    payload = json.loads(out.read_text())
    # The non-meta top-level dirs (cmd) should appear as Go components.
    assert "cmd" in payload["components"], (
        f"force-stack should surface cmd/ as a Go component; got components={payload['components']}"
    )


def test_t32_force_stack_rejects_unknown_stack(tmp_path: Path, capsys) -> None:
    """T3.2: --force-stack with an unknown stack name must fail with
    a clear error, not silently accept the bad input.
    """
    out = tmp_path / "out.json"
    rc = main(
        [
            "--project",
            str(tmp_path),
            "--stack",
            "python",
            "--types",
            "unit",
            "--force-stack",
            "rust",
            "--out",
            str(out),
        ]
    )
    captured = capsys.readouterr()
    assert rc == 1
    assert "unknown stack" in captured.err.lower()
    assert "rust" in captured.err


def test_main_rejects_out_of_range_coverage_target(make_fixture_project: Path, capsys) -> None:
    """M2 follow-up: ``--coverage-target`` must be 0..100; values
    outside the range must produce a non-zero exit and a clear
    stderr message.
    """
    out = make_fixture_project / "out.json"
    rc = main(
        [
            "--project",
            str(make_fixture_project),
            "--stack",
            "python",
            "--types",
            "unit",
            "--coverage-target",
            "150",
            "--out",
            str(out),
        ]
    )
    captured = capsys.readouterr()
    assert rc == 1
    # The exact wording is implementation-defined, so match a few
    # reasonable phrasings.
    assert any(
        needle in captured.err.lower()
        for needle in (
            "between 0 and 100",
            "out of range",
            "invalid",
            "must be",
        )
    ), f"expected range error; got stderr={captured.err!r}"


# ---------------------------------------------------------------------------
# Filename-based component inference (Tier 2 — was uncovered)
# ---------------------------------------------------------------------------


def test_infer_component_from_filename_websocket(tmp_path: Path) -> None:
    """``tests/unit/test_websocket_integration.py`` should resolve to
    ``mahavishnu/websocket`` via the filename heuristic.
    """
    tests_root = tmp_path / "tests" / "unit"
    tests_root.mkdir(parents=True)
    test_file = tests_root / "test_websocket_integration.py"
    test_file.write_text("# no imports\n")
    assert infer_component_from_filename(test_file, tests_root) == ("mahavishnu/websocket")


def test_infer_component_from_filename_top_level_catchall(
    make_fixture_project: Path,
) -> None:
    """``tests/test_top.py`` (no ``unit/`` prefix, no imports) should
    fall back to the catch-all ``mahavishnu`` bucket through
    ``map_test_files_to_components``.
    """
    tests_root = make_fixture_project / "tests"
    test_files = [tests_root / "test_top.py"]
    valid = {"mahavishnu/core", "mahavishnu/workers"}
    grouped = map_test_files_to_components(test_files, tests_root, valid_components=valid)
    assert "mahavishnu" in grouped
    assert any("test_top.py" in f for f in grouped["mahavishnu"])


# ---------------------------------------------------------------------------
# Coverage XML error paths (Tier 2 — was uncovered)
# ---------------------------------------------------------------------------


def test_parse_coverage_xml_missing_file(tmp_path: Path) -> None:
    """No ``coverage.xml`` in the project → ``parse_coverage_xml`` must
    return ``None`` (not raise).
    """
    assert parse_coverage_xml(tmp_path) is None


def test_parse_coverage_xml_malformed_xml(tmp_path: Path) -> None:
    """Garbage in ``coverage.xml`` → ``parse_coverage_xml`` must return
    ``None`` without raising. ``defusedxml`` should be the reason no
    exception propagates: malformed XML raises ``ParseError`` which the
    parser swallows and returns ``None``.
    """
    (tmp_path / "coverage.xml").write_text("<<< not xml at all >>>")
    assert parse_coverage_xml(tmp_path) is None
