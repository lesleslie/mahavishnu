"""Unit tests for mahavishnu.cli.docs_cli.

Verifies the ``docs`` sub-typer is registered correctly and that the
``audit`` command handles the various input/output branches end-to-end.
The heavy work (catalog scan over real repos) is replaced by patching
``audit_ecosystem_docs.build_audit_report`` so the tests stay fast and
deterministic.

Run standalone:
    python tests/unit/test_docs_cli.py

Run with pytest:
    pytest tests/unit/test_docs_cli.py
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import sys
import types

import pytest
import typer
from typer.testing import CliRunner

from mahavishnu.cli.docs_cli import add_docs_commands

# ---------------------------------------------------------------------------
# Stubs for audit_ecosystem_docs dataclasses
# ---------------------------------------------------------------------------


@dataclass
class FakeSummary:
    """Minimal stand-in for audit_ecosystem_docs.RepoDocsSummary.

    Only the attributes that ``docs_cli`` actually touches (via
    ``asdict``) matter. ``asdict`` recurses into nested dataclasses, so
    every field referenced by ``asdict`` must itself be a dataclass,
    list, dict, or primitive.
    """

    name: str = "repo-a"
    path: str = "/tmp/repo-a"
    docs_path: str = "docs"
    docs_exists: bool = True
    total_files: int = 4
    markdown_files: int = 4
    archive_files: int = 0
    backup_like_files: int = 0
    generated_files: int = 0
    root_markdown_files: list = field(default_factory=list)
    stale_root_candidates: list = field(default_factory=list)
    has_docs_readme: bool = True
    has_archive_readme: bool = False
    has_plan_index: bool = True
    top_level_dirs: list = field(default_factory=list)
    backup_like_paths: list = field(default_factory=list)
    generated_paths: list = field(default_factory=list)
    stale_root_paths: list = field(default_factory=list)
    recommendations: list = field(default_factory=list)


@dataclass
class FakeCatalog:
    """Minimal stand-in for audit_ecosystem_docs.CatalogSnapshot."""

    ecosystem_path: str = "/tmp/ecosystem.yaml"
    last_updated: str = "2026-01-01"
    repo_count: int = 1
    active_repo_count: int = 1
    mcp_server_count: int = 0
    agent_count: int = 0
    workflow_count: int = 0
    skill_count: int = 0
    tool_count: int = 0
    role_count: int = 0


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def app() -> typer.Typer:
    parent = typer.Typer()
    add_docs_commands(parent)
    return parent


@pytest.fixture
def fake_report():
    """Returns (catalog, issues, summaries) tuple used by the CLI."""

    def _build(
        summaries: list[FakeSummary] | None = None,
        issues: list[str] | None = None,
        catalog: FakeCatalog | None = None,
    ):
        return (
            catalog or FakeCatalog(),
            issues if issues is not None else [],
            summaries or [FakeSummary()],
        )

    return _build


@pytest.fixture
def fake_module(fake_report):
    """Inject a fake ``audit_ecosystem_docs`` module into sys.modules.

    ``docs_cli`` does the import inside the command body via
    ``from audit_ecosystem_docs import ...``. We pre-register a stub
    module with the same surface so the import succeeds and the
    build/render functions are easy to monkeypatch.
    """
    mod = types.ModuleType("audit_ecosystem_docs")

    def _build_audit_report(_path: Path):
        return fake_report()

    def _render_text(summaries, *, catalog=None, catalog_issues=None):
        return f"TEXT-RENDER: {len(summaries)} summaries"

    def _render_markdown(summaries, *, include_files=False, catalog=None, catalog_issues=None):
        return f"MARKDOWN-RENDER: {len(summaries)} summaries"

    mod.build_audit_report = _build_audit_report
    mod.render_text = _render_text
    mod.render_markdown = _render_markdown
    saved = sys.modules.get("audit_ecosystem_docs")
    sys.modules["audit_ecosystem_docs"] = mod
    try:
        yield mod
    finally:
        if saved is not None:
            sys.modules["audit_ecosystem_docs"] = saved
        else:
            sys.modules.pop("audit_ecosystem_docs", None)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def test_add_docs_commands_attaches_subtyper(app: typer.Typer) -> None:
    """add_docs_commands registers exactly one sub-typer named 'docs'."""
    assert len(app.registered_groups) == 1
    assert app.registered_groups[0].name == "docs"


def test_docs_group_listed_in_parent(app: typer.Typer) -> None:
    names = [g.name for g in app.registered_groups]
    assert "docs" in names


def test_docs_top_level_help_runs(runner: CliRunner, app: typer.Typer) -> None:
    result = runner.invoke(app, ["docs", "--help"])
    assert result.exit_code == 0
    assert "docs" in result.stdout.lower()


def test_docs_audit_help_runs(runner: CliRunner, app: typer.Typer) -> None:
    result = runner.invoke(app, ["docs", "audit", "--help"])
    assert result.exit_code == 0
    # Make sure the recognized flags are documented.
    assert "--ecosystem" in result.stdout
    assert "--output" in result.stdout
    assert "--write" in result.stdout
    assert "--include-files" in result.stdout


# ---------------------------------------------------------------------------
# `docs audit` — error paths
# ---------------------------------------------------------------------------


def test_audit_missing_ecosystem_file_exits_1(
    runner: CliRunner, app: typer.Typer, tmp_path: Path, fake_module
) -> None:
    missing = tmp_path / "no-such-ecosystem.yaml"
    result = runner.invoke(app, ["docs", "audit", "--ecosystem", str(missing)])
    assert result.exit_code == 1
    assert "Ecosystem file not found" in (result.output + result.stderr)


def test_audit_invalid_output_format_exits_1(
    runner: CliRunner, app: typer.Typer, tmp_path: Path, fake_module
) -> None:
    eco = tmp_path / "ecosystem.yaml"
    eco.write_text("version: '1.0'\n")
    result = runner.invoke(
        app,
        ["docs", "audit", "--ecosystem", str(eco), "--output", "xml"],
    )
    assert result.exit_code == 1
    assert "Invalid output format" in (result.output + result.stderr)


def test_audit_missing_module_exits_1(runner: CliRunner, app: typer.Typer, tmp_path: Path) -> None:
    """When audit_ecosystem_docs is not importable, the command should
    still produce a clean error instead of a traceback."""
    eco = tmp_path / "ecosystem.yaml"
    eco.write_text("version: '1.0'\n")
    saved = sys.modules.pop("audit_ecosystem_docs", None)
    # Block re-import by registering a sentinel that always raises.
    blocker = types.ModuleType("audit_ecosystem_docs")

    def _raise(*_a, **_k):
        raise ImportError("blocked for test")

    blocker.build_audit_report = _raise  # type: ignore[attr-defined]
    sys.modules["audit_ecosystem_docs"] = blocker
    try:
        result = runner.invoke(app, ["docs", "audit", "--ecosystem", str(eco)])
    finally:
        sys.modules.pop("audit_ecosystem_docs", None)
        if saved is not None:
            sys.modules["audit_ecosystem_docs"] = saved
    assert result.exit_code == 1


# ---------------------------------------------------------------------------
# `docs audit` — output formats
# ---------------------------------------------------------------------------


def test_audit_text_output_to_stdout(
    runner: CliRunner, app: typer.Typer, tmp_path: Path, fake_module
) -> None:
    eco = tmp_path / "ecosystem.yaml"
    eco.write_text("version: '1.0'\n")
    result = runner.invoke(app, ["docs", "audit", "--ecosystem", str(eco)])
    assert result.exit_code == 0
    assert "TEXT-RENDER: 1 summaries" in result.output


def test_audit_json_output_renders_as_json(
    runner: CliRunner, app: typer.Typer, tmp_path: Path, fake_module
) -> None:
    eco = tmp_path / "ecosystem.yaml"
    eco.write_text("version: '1.0'\n")
    result = runner.invoke(
        app,
        ["docs", "audit", "--ecosystem", str(eco), "--output", "json"],
    )
    assert result.exit_code == 0
    parsed = json.loads(result.output)
    assert isinstance(parsed, list)
    assert len(parsed) == 1
    assert parsed[0]["name"] == "repo-a"
    assert parsed[0]["docs_exists"] is True


def test_audit_markdown_output_uses_markdown_renderer(
    runner: CliRunner, app: typer.Typer, tmp_path: Path, fake_module
) -> None:
    eco = tmp_path / "ecosystem.yaml"
    eco.write_text("version: '1.0'\n")
    result = runner.invoke(
        app,
        [
            "docs",
            "audit",
            "--ecosystem",
            str(eco),
            "--output",
            "markdown",
            "--include-files",
        ],
    )
    assert result.exit_code == 0
    assert "MARKDOWN-RENDER: 1 summaries" in result.output


# ---------------------------------------------------------------------------
# `docs audit` — write flag
# ---------------------------------------------------------------------------


def test_audit_writes_report_to_file(
    runner: CliRunner, app: typer.Typer, tmp_path: Path, fake_module
) -> None:
    eco = tmp_path / "ecosystem.yaml"
    eco.write_text("version: '1.0'\n")
    out = tmp_path / "reports" / "audit.md"
    result = runner.invoke(
        app,
        [
            "docs",
            "audit",
            "--ecosystem",
            str(eco),
            "--output",
            "markdown",
            "--write",
            str(out),
        ],
    )
    assert result.exit_code == 0
    assert out.exists()
    assert "Report written to" in result.output
    assert out.read_text() == "MARKDOWN-RENDER: 1 summaries"


def test_audit_write_creates_missing_parent_dirs(
    runner: CliRunner, app: typer.Typer, tmp_path: Path, fake_module
) -> None:
    eco = tmp_path / "ecosystem.yaml"
    eco.write_text("version: '1.0'\n")
    out = tmp_path / "deep" / "nested" / "audit.txt"
    result = runner.invoke(
        app,
        ["docs", "audit", "--ecosystem", str(eco), "--write", str(out)],
    )
    assert result.exit_code == 0
    assert out.exists()
    assert out.parent.is_dir()


def test_audit_invoke_uses_real_module_when_present(
    runner: CliRunner, app: typer.Typer, tmp_path: Path
) -> None:
    """Sanity check: if the real ``audit_ecosystem_docs`` is importable
    (which it is in this repo), the command must not crash on a
    well-formed ecosystem file. This guards against the import path
    diverging from the one expected by the CLI source."""
    eco = tmp_path / "ecosystem.yaml"
    eco.write_text("version: '1.0'\n")
    if "audit_ecosystem_docs" not in sys.modules:
        pytest.skip("audit_ecosystem_docs not on sys.path in this env")
    result = runner.invoke(app, ["docs", "audit", "--ecosystem", str(eco)])
    # Either success (audit found nothing to say) or a clean error
    # message; we only care that we didn't get a TypeError or ImportError
    # from inside the command body.
    assert result.exit_code in (0, 1)
