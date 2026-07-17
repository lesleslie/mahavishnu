---
status: active
role: implementation
date: 2026-07-16
last_reviewed: 2026-07-16
superseded_by: null
topic: mcp-design
---

# Bodai Plugin Standardization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert 5 Bodai MCP servers (`mahavishnu`, `session-buddy`, `crackerjack`, `akosha`, `dhara`) to Claude Code plugins, distributed via a new `bodai-plugins` marketplace repo. Replace existing slash commands with namespaced `<server>:<command>` form. Give workflows a documented lifecycle.

**Architecture:** Five self-contained plugins (one per MCP server) + `bodai-plugins` marketplace repo with a Typer CLI scaffold tool (`init`, `validate --fix`) + paired decision files in `.claude/decisions/workflows/` for lifecycle tracking. Two-phase migration per repo: **Phase A** adds plugin manifest + namespaced commands alongside old flat commands (safe, additive); **Phase B** deletes old commands + updates `.mcp.json` to point at plugin's MCP server entry (destructive).

**Tech Stack:** Python 3.13, Typer, Claude Code plugin format (`plugin.json` + `commands/`), Claude Code marketplace format (`marketplace.json`).

## Global Constraints

- **Plugin manifest `name`** must equal the MCP server key AND the slash command namespace prefix (three places, one string). Scaffold enforces; CI guard test pins.
- **Slash namespace prefix** = full server name (`mahavishnu:status`, `session-buddy:checkpoint`, `crackerjack:status`, `akosha:search`, `dhara:put`). Exception: cross-component commands keep the `bodai:` prefix (`bodai-status`, `bodai-status-event`).
- **MCP server entries** live in the plugin's `.mcp.json`, NOT the consuming repo's `.mcp.json`. Plugin consumer adds `<server>` to its plugin list and the marketplace resolves MCP wiring.
- **Plugin layout** (per server repo): `<repo>/.claude-plugin/plugin.json` + `<repo>/commands/<server>-<command>.md` + `<repo>/.mcp.json`.
- **Marketplace layout** (`bodai-plugins` repo): `bodai-plugins/.claude-plugin/marketplace.json` + `bodai-plugins/bodai_plugins/{cli.py,scripts/init_bodai_plugin.py,scripts/validate_bodai_plugin.py}` + `bodai-plugins/tests/` + `bodai-plugins/pyproject.toml`.
- **Workflow decision files** use `YYYY-MM-DD-<name>.md` pattern, paired with the `.js` workflow in `.claude/workflows/`. Status header is `## Status: Active | Superseded | Archived`.
- **Lifecycle rules**: Active workflows are kept in `.claude/workflows/`; Superseded/Archived workflows move to `.claude/workflows/.archive/` and get a paired decision file in `.claude/decisions/workflows/`.
- **Cross-repo merge policy** (per `bodai-pre-1.0-merge-policy.md`): branch + squash/ff-merge into `main` of each repo. No PR review gates.
- **TDD discipline**: each task writes the failing test first, then the minimal implementation, then commits.
- **Frequent commits**: one commit per task minimum, atomic diff per commit.
- **No `assert` in production code** (`bodai-plugins/**` is a published tool). Use explicit `raise` or `typer.Exit(code=...)`.

---

## Phase 1: Build bodai-plugins marketplace repo

### Task 1: Initialize bodai-plugins repo skeleton

**Files:**
- Create: `bodai-plugins/pyproject.toml`
- Create: `bodai-plugins/.gitignore`
- Create: `bodai-plugins/README.md`
- Create: `bodai-plugins/CHANGELOG.md`
- Create: `bodai-plugins/LICENSE` (MIT)

**Step 1: Create the repo locally**

```bash
mkdir -p /Users/les/Projects/bodai-plugins && cd /Users/les/Projects/bodai-plugins
git init -b main
git remote add origin git@github.com:lesleslie/bodai-plugins.git
```

**Step 2: Write `pyproject.toml`**

```toml
[project]
name = "bodai-plugins"
version = "0.1.0"
description = "Marketplace scaffolding for Bodai MCP-server Claude Code plugins"
requires-python = ">=3.13"
dependencies = [
    "typer>=0.15",
    "jsonschema>=4.23",
    "rich>=13.9",
]

[project.scripts]
bodai-plugins = "bodai_plugins.cli:app"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["bodai_plugins"]
```

**Step 3: Write `.gitignore`**

```
# Python
__pycache__/
*.py[cod]
*.egg-info/
.venv/
dist/
build/

# Test
.pytest_cache/
.coverage
htmlcov/

# Editor
.vscode/
.idea/
.DS_Store

# Plugin scaffolds (never commit generated plugins)
*.scaffold-tmp/
```

**Step 4: Write minimal `README.md`**

```markdown
# bodai-plugins

Marketplace scaffolding CLI for the [Bodai ecosystem](https://github.com/lesleslie/bodai) Claude Code plugins.

## Install

```bash
uv tool install bodai-plugins
```

## Use

```bash
# Scaffold a new plugin in the current repo
bodai-plugins init mahavishnu

# Validate the plugin structure
bodai-plugins validate --verbose

# Auto-fix issues
bodai-plugins validate --fix
```

## Add the marketplace to Claude Code

```bash
claude plugin marketplace add https://github.com/lesleslie/bodai-plugins
```

## Plugins distributed

See `.claude-plugin/marketplace.json` for the canonical list.
```

**Step 5: Initial commit**

```bash
git add pyproject.toml .gitignore README.md CHANGELOG.md LICENSE
git commit -m "chore: bootstrap bodai-plugins marketplace repo"
git push -u origin main
```

---

### Task 2: Implement Typer CLI skeleton

**Files:**
- Create: `bodai-plugins/bodai_plugins/__init__.py`
- Create: `bodai-plugins/bodai_plugins/cli.py`
- Create: `bodai-plugins/tests/__init__.py`
- Create: `bodai-plugins/tests/test_cli.py`

**Step 1: Write the failing test**

`bodai-plugins/tests/test_cli.py`:

```python
from __future__ import annotations

from typer.testing import CliRunner

from bodai_plugins.cli import app


def test_cli_help_lists_subcommands() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "init" in result.stdout
    assert "validate" in result.stdout


def test_init_command_exists() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["init", "--help"])
    assert result.exit_code == 0
    assert "PLUGIN_NAME" in result.stdout or "--plugin-name" in result.stdout


def test_validate_command_accepts_fix_flag() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["validate", "--help"])
    assert result.exit_code == 0
    assert "--fix" in result.stdout
```

**Step 2: Run the test to verify it fails**

```bash
cd /Users/les/Projects/bodai-plugins && uv venv && source .venv/bin/activate && uv pip install -e ".[dev]"
uv run pytest tests/test_cli.py -v
```

Expected: `ModuleNotFoundError: No module named 'bodai_plugins.cli'`.

**Step 3: Implement the CLI skeleton**

`bodai-plugins/bodai_plugins/__init__.py`:

```python
"""Bodai plugins marketplace scaffold CLI."""

from __future__ import annotations

__version__ = "0.1.0"
```

`bodai-plugins/bodai_plugins/cli.py`:

```python
"""Typer CLI entry point for `bodai-plugins`."""

from __future__ import annotations

from pathlib import Path

import typer

from bodai_plugins import __version__

app = typer.Typer(
    name="bodai-plugins",
    help="Marketplace scaffold CLI for Bodai MCP-server Claude Code plugins.",
    no_args_is_help=True,
)


def version_callback(value: bool) -> None:
    if value:
        typer.echo(f"bodai-plugins {__version__}")
        raise typer.Exit(code=0)


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        callback=version_callback,
        is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    """Bodai plugins marketplace scaffold CLI."""


@app.command()
def init(
    plugin_name: str = typer.Argument(..., help="Plugin namespace (e.g. 'mahavishnu')."),
    path: Path = typer.Option(
        Path.cwd(),
        "--path",
        "-p",
        help="Target directory for the scaffold.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Overwrite existing plugin files.",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Print each file as it is written.",
    ),
) -> None:
    """Scaffold a new plugin directory at PATH."""
    typer.echo(f"init: not yet implemented (would scaffold {plugin_name} at {path})")


@app.command()
def validate(
    path: Path = typer.Option(
        Path.cwd(),
        "--path",
        "-p",
        help="Plugin or marketplace directory to validate.",
    ),
    fix: bool = typer.Option(
        False,
        "--fix",
        help="Auto-fix issues where safe.",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Print per-file diagnostic detail.",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit machine-readable JSON.",
    ),
) -> None:
    """Validate a plugin or marketplace structure."""
    typer.echo(f"validate: not yet implemented (would validate {path})")


if __name__ == "__main__":
    app()
```

`bodai-plugins/tests/__init__.py`: empty file.

**Step 4: Run the tests**

```bash
cd /Users/les/Projects/bodai-plugins && uv run pytest tests/test_cli.py -v
```

Expected: 3 passed.

**Step 5: Commit**

```bash
git add bodai_plugins/ tests/
git commit -m "feat(cli): add typer skeleton with init and validate stubs"
```

---

### Task 3: Implement `init_bodai_plugin.py` scaffold writer

**Files:**
- Create: `bodai-plugins/bodai_plugins/scripts/__init__.py`
- Create: `bodai-plugins/bodai_plugins/scripts/init_bodai_plugin.py`
- Create: `bodai-plugins/tests/test_init_bodai_plugin.py`
- Modify: `bodai-plugins/bodai_plugins/cli.py` (wire `init` to the script)

**Step 1: Write the failing test**

`bodai-plugins/tests/test_init_bodai_plugin.py`:

```python
from __future__ import annotations

from pathlib import Path

from bodai_plugins.scripts.init_bodai_plugin import scaffold_plugin


def test_scaffold_creates_plugin_manifest(tmp_path: Path) -> None:
    plugin_dir = scaffold_plugin(name="mahavishnu", target=tmp_path)
    manifest = plugin_dir / ".claude-plugin" / "plugin.json"
    assert manifest.is_file()
    import json

    data = json.loads(manifest.read_text())
    assert data["name"] == "mahavishnu"
    assert data["version"] == "0.1.0"
    assert "mcpServers" in data


def test_scaffold_creates_commands_directory(tmp_path: Path) -> None:
    plugin_dir = scaffold_plugin(name="mahavishnu", target=tmp_path)
    assert (plugin_dir / "commands").is_dir()


def test_scaffold_creates_mcp_json(tmp_path: Path) -> None:
    plugin_dir = scaffold_plugin(name="mahavishnu", target=tmp_path)
    mcp_json = plugin_dir / ".mcp.json"
    assert mcp_json.is_file()


def test_scaffold_refuses_overwrite_without_force(tmp_path: Path) -> None:
    scaffold_plugin(name="mahavishnu", target=tmp_path)
    import pytest

    with pytest.raises(FileExistsError):
        scaffold_plugin(name="mahavishnu", target=tmp_path, force=False)


def test_scaffold_overwrites_with_force(tmp_path: Path) -> None:
    scaffold_plugin(name="mahavishnu", target=tmp_path)
    plugin_dir = scaffold_plugin(name="mahavishnu", target=tmp_path, force=True)
    assert plugin_dir.is_dir()
```

**Step 2: Run test to verify failure**

```bash
cd /Users/les/Projects/bodai-plugins && uv run pytest tests/test_init_bodai_plugin.py -v
```

Expected: `ModuleNotFoundError: No module named 'bodai_plugins.scripts.init_bodai_plugin'`.

**Step 3: Implement the scaffold**

`bodai-plugins/bodai_plugins/scripts/__init__.py`: empty.

`bodai-plugins/bodai_plugins/scripts/init_bodai_plugin.py`:

```python
"""Scaffold a Bodai MCP-server plugin directory."""

from __future__ import annotations

import json
from pathlib import Path

PLUGIN_MANIFEST_SCHEMA_VERSION = "1.0.0"
INITIAL_VERSION = "0.1.0"


def _render_plugin_json(name: str) -> str:
    """Render `.claude-plugin/plugin.json` for a Bodai MCP-server plugin."""
    payload = {
        "schema_version": PLUGIN_MANIFEST_SCHEMA_VERSION,
        "name": name,
        "version": INITIAL_VERSION,
        "description": f"Bodai plugin for the {name} MCP server.",
        "author": {"name": "Bodai"},
        "keywords": ["bodai", "mcp", name],
        "mcpServers": f".mcp.json",
    }
    return json.dumps(payload, indent=2) + "\n"


def _render_mcp_json(name: str) -> str:
    """Render `.mcp.json` that wires the plugin's MCP server entry."""
    payload = {
        name: {
            "type": "http",
            "url": f"http://localhost:8680/mcp",
            "description": f"{name} MCP server (update URL to match this server).",
        }
    }
    return json.dumps(payload, indent=2) + "\n"


def _render_readme(name: str) -> str:
    return (
        f"# {name} plugin\n\n"
        f"Bodai plugin for the `{name}` MCP server.\n\n"
        f"## Install\n\n"
        f"Add the `bodai-plugins` marketplace, then install this plugin:\n\n"
        f"```bash\n"
        f"claude plugin install {name}\n"
        f"```\n\n"
        f"## Commands\n\n"
        f"See `commands/`.\n"
    )


def scaffold_plugin(
    name: str,
    target: Path,
    *,
    force: bool = False,
    verbose: bool = False,
) -> Path:
    """Scaffold a plugin directory at ``target/<name>/``.

    Returns the plugin directory path.
    Raises FileExistsError if the directory exists and ``force`` is False.
    """
    plugin_dir = target / name
    if plugin_dir.exists() and not force:
        raise FileExistsError(f"{plugin_dir} already exists; pass force=True to overwrite")

    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "commands").mkdir(exist_ok=True)
    (plugin_dir / ".claude-plugin").mkdir(exist_ok=True)

    files = {
        plugin_dir / ".claude-plugin" / "plugin.json": _render_plugin_json(name),
        plugin_dir / ".mcp.json": _render_mcp_json(name),
        plugin_dir / "README.md": _render_readme(name),
    }
    for path, content in files.items():
        path.write_text(content)
        if verbose:
            print(f"wrote {path}")

    return plugin_dir
```

**Step 4: Wire the CLI to the script**

Edit `bodai-plugins/bodai_plugins/cli.py`, replace the `init` body:

```python
@app.command()
def init(
    plugin_name: str = typer.Argument(..., help="Plugin namespace (e.g. 'mahavishnu')."),
    path: Path = typer.Option(
        Path.cwd(),
        "--path",
        "-p",
        help="Target directory for the scaffold.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Overwrite existing plugin files.",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Print each file as it is written.",
    ),
) -> None:
    """Scaffold a new plugin directory at PATH."""
    from bodai_plugins.scripts.init_bodai_plugin import scaffold_plugin

    plugin_dir = scaffold_plugin(name=plugin_name, target=path, force=force, verbose=verbose)
    typer.echo(f"scaffolded plugin at {plugin_dir}")
```

**Step 5: Run the tests**

```bash
cd /Users/les/Projects/bodai-plugins && uv run pytest tests/ -v
```

Expected: all tests pass (cli + init).

**Step 6: Commit**

```bash
git add bodai_plugins/ tests/
git commit -m "feat(init): scaffold plugin manifest, mcp.json, commands dir"
```

---

### Task 4: Implement `validate_bodai_plugin.py`

**Files:**
- Create: `bodai-plugins/bodai_plugins/scripts/validate_bodai_plugin.py`
- Create: `bodai-plugins/tests/test_validate_bodai_plugin.py`
- Modify: `bodai-plugins/bodai_plugins/cli.py` (wire `validate` to the script)

**Step 1: Write the failing test**

`bodai-plugins/tests/test_validate_bodai_plugin.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

from bodai_plugins.scripts.validate_bodai_plugin import (
    ValidationIssue,
    validate_plugin,
)


def test_validate_passes_on_valid_plugin(tmp_path: Path) -> None:
    plugin = tmp_path / "mahavishnu"
    plugin.mkdir()
    (plugin / ".claude-plugin").mkdir()
    (plugin / "commands").mkdir()
    (plugin / ".claude-plugin" / "plugin.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "name": "mahavishnu",
                "version": "0.1.0",
                "mcpServers": ".mcp.json",
            }
        )
    )
    (plugin / ".mcp.json").write_text(json.dumps({"mahavishnu": {"type": "http", "url": "x"}}))

    issues = validate_plugin(plugin)
    assert issues == []


def test_validate_detects_missing_manifest(tmp_path: Path) -> None:
    plugin = tmp_path / "mahavishnu"
    plugin.mkdir()
    issues = validate_plugin(plugin)
    assert any(i.code == "MISSING_MANIFEST" for i in issues)


def test_validate_detects_name_mismatch(tmp_path: Path) -> None:
    plugin = tmp_path / "mahavishnu"
    plugin.mkdir()
    (plugin / ".claude-plugin").mkdir()
    (plugin / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": "vishnu", "version": "0.1.0", "mcpServers": ".mcp.json"})
    )
    issues = validate_plugin(plugin)
    assert any(i.code == "NAME_MISMATCH" for i in issues)


def test_validate_fix_writes_missing_manifest(tmp_path: Path) -> None:
    plugin = tmp_path / "mahavishnu"
    plugin.mkdir()
    fixed = validate_plugin(plugin, fix=True)
    assert (plugin / ".claude-plugin" / "plugin.json").is_file()
    assert fixed == []


def test_validation_issue_dataclass() -> None:
    issue = ValidationIssue(code="X", message="y", path=Path("/z"))
    assert issue.code == "X"
    assert issue.message == "y"
    assert issue.path == Path("/z")
```

**Step 2: Run test to verify failure**

```bash
cd /Users/les/Projects/bodai-plugins && uv run pytest tests/test_validate_bodai_plugin.py -v
```

Expected: `ModuleNotFoundError`.

**Step 3: Implement the validator**

`bodai-plugins/bodai_plugins/scripts/validate_bodai_plugin.py`:

```python
"""Validate a Bodai MCP-server plugin structure."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str
    path: Path


REQUIRED_MANIFEST_KEYS = {"schema_version", "name", "version", "mcpServers"}
MIN_PLUGIN_VERSION = "1.0.0"


def _read_json(path: Path) -> object | None:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _issue(code: str, message: str, path: Path) -> ValidationIssue:
    return ValidationIssue(code=code, message=message, path=path)


def validate_plugin(plugin_dir: Path, *, fix: bool = False) -> list[ValidationIssue]:
    """Validate the plugin at ``plugin_dir``.

    When ``fix`` is True, safe auto-fixes are applied (writes a missing
    manifest stub, creates the ``commands/`` directory).
    """
    issues: list[ValidationIssue] = []
    manifest_path = plugin_dir / ".claude-plugin" / "plugin.json"
    mcp_json_path = plugin_dir / ".mcp.json"
    commands_dir = plugin_dir / "commands"

    # 1. manifest must exist
    if not manifest_path.is_file():
        issues.append(_issue("MISSING_MANIFEST", "plugin.json is missing", manifest_path))
        if fix:
            (plugin_dir / ".claude-plugin").mkdir(parents=True, exist_ok=True)
            manifest_path.write_text(
                json.dumps(
                    {
                        "schema_version": MIN_PLUGIN_VERSION,
                        "name": plugin_dir.name,
                        "version": "0.1.0",
                        "mcpServers": ".mcp.json",
                    },
                    indent=2,
                )
                + "\n"
            )
            issues.clear()
            return validate_plugin(plugin_dir, fix=False)

    # 2. commands/ must exist
    if not commands_dir.is_dir():
        issues.append(_issue("MISSING_COMMANDS_DIR", "commands/ directory is missing", commands_dir))
        if fix:
            commands_dir.mkdir()

    # 3. mcp.json must exist
    if not mcp_json_path.is_file():
        issues.append(_issue("MISSING_MCP_JSON", ".mcp.json is missing", mcp_json_path))
        if fix:
            mcp_json_path.write_text(json.dumps({plugin_dir.name: {"type": "http", "url": "x"}}, indent=2) + "\n")

    data = _read_json(manifest_path)
    if isinstance(data, dict):
        # 4. required keys
        missing = REQUIRED_MANIFEST_KEYS - set(data.keys())
        if missing:
            issues.append(
                _issue(
                    "MISSING_MANIFEST_KEYS",
                    f"manifest missing keys: {sorted(missing)}",
                    manifest_path,
                )
            )

        # 5. name must equal directory basename
        declared_name = data.get("name")
        if declared_name and declared_name != plugin_dir.name:
            issues.append(
                _issue(
                    "NAME_MISMATCH",
                    f"manifest name {declared_name!r} != directory name {plugin_dir.name!r}",
                    manifest_path,
                )
            )

        # 6. mcpServers file path must exist
        mcp_servers = data.get("mcpServers")
        if isinstance(mcp_servers, str) and not (plugin_dir / mcp_servers).is_file():
            issues.append(
                _issue(
                    "MISSING_MCP_SERVERS_FILE",
                    f"mcpServers path {mcp_servers!r} does not exist",
                    plugin_dir / mcp_servers,
                )
            )

    return issues
```

**Step 4: Wire the CLI to the script**

Edit `bodai-plugins/bodai_plugins/cli.py`, replace the `validate` body:

```python
@app.command()
def validate(
    path: Path = typer.Option(
        Path.cwd(),
        "--path",
        "-p",
        help="Plugin or marketplace directory to validate.",
    ),
    fix: bool = typer.Option(
        False,
        "--fix",
        help="Auto-fix issues where safe.",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Print per-file diagnostic detail.",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit machine-readable JSON.",
    ),
) -> None:
    """Validate a plugin or marketplace structure."""
    import json

    from bodai_plugins.scripts.validate_bodai_plugin import validate_plugin

    plugin_dir = path if (path / ".claude-plugin").is_dir() else None
    if plugin_dir is None:
        typer.echo(f"no plugin manifest found at {path}; pass --path pointing at a plugin directory")
        raise typer.Exit(code=2)

    issues = validate_plugin(plugin_dir, fix=fix)
    payload = {
        "plugin": str(plugin_dir),
        "issue_count": len(issues),
        "issues": [{"code": i.code, "message": i.message, "path": str(i.path)} for i in issues],
    }
    if json_output:
        typer.echo(json.dumps(payload, indent=2))
    else:
        if not issues:
            typer.echo(f"OK: {plugin_dir}")
            return
        typer.echo(f"{len(issues)} issue(s) in {plugin_dir}:", err=True)
        for issue in issues:
            typer.echo(f"  {issue.code}: {issue.message} ({issue.path})", err=True)
            if verbose:
                typer.echo(f"    at: {issue.path}", err=True)
        raise typer.Exit(code=1)
```

**Step 5: Run tests**

```bash
cd /Users/les/Projects/bodai-plugins && uv run pytest tests/ -v
```

Expected: all tests pass.

**Step 6: Smoke test**

```bash
cd /Users/les/Projects/bodai-plugins
mkdir -p /tmp/test-plugin
uv run bodai-plugins init mahavishnu --path /tmp/test-plugin --verbose
uv run bodai-plugins validate --path /tmp/test-plugin/mahavishnu --verbose
```

Expected: scaffold writes 3 files; validate reports `OK`.

**Step 7: Commit**

```bash
git add bodai_plugins/ tests/
git commit -m "feat(validate): plugin structure validator with --fix support"
```

---

### Task 5: Marketplace manifest + extension command

**Files:**
- Create: `bodai-plugins/bodai_plugins/scripts/manage_marketplace.py`
- Create: `bodai-plugins/tests/test_manage_marketplace.py`
- Modify: `bodai-plugins/bodai_plugins/cli.py` (add `marketplace` subcommand group)

**Step 1: Write the failing test**

`bodai-plugins/tests/test_manage_marketplace.py`:

```python
from __future__ import annotations

import json
from pathlib import Path


from bodai_plugins.scripts.manage_marketplace import (
    add_plugin_entry,
    load_marketplace,
    render_marketplace,
)


def test_render_marketplace_returns_required_keys() -> None:
    payload = render_marketplace(name="bodai-plugins", owner="lesleslie", plugins=[])
    assert payload["name"] == "bodai-plugins"
    assert payload["owner"]["name"] == "lesleslie"
    assert payload["plugins"] == []
    assert "schema_version" in payload


def test_add_plugin_entry_appends(tmp_path: Path) -> None:
    manifest = tmp_path / "marketplace.json"
    manifest.write_text(json.dumps(render_marketplace(name="bodai-plugins", owner="lesleslie", plugins=[])))
    add_plugin_entry(
        manifest,
        name="mahavishnu",
        source="../mahavishnu",
        ref="main",
    )
    data = load_marketplace(manifest)
    assert len(data["plugins"]) == 1
    assert data["plugins"][0]["name"] == "mahavishnu"
    assert data["plugins"][0]["source"] == "../mahavishnu"


def test_add_plugin_entry_rejects_duplicate(tmp_path: Path) -> None:
    manifest = tmp_path / "marketplace.json"
    manifest.write_text(json.dumps(render_marketplace(name="bodai-plugins", owner="lesleslie", plugins=[])))
    add_plugin_entry(manifest, name="mahavishnu", source="../mahavishnu")
    import pytest

    with pytest.raises(ValueError):
        add_plugin_entry(manifest, name="mahavishnu", source="../elsewhere")
```

**Step 2: Run test to verify failure**

```bash
cd /Users/les/Projects/bodai-plugins && uv run pytest tests/test_manage_marketplace.py -v
```

Expected: ModuleNotFoundError.

**Step 3: Implement the marketplace helpers**

`bodai-plugins/bodai_plugins/scripts/manage_marketplace.py`:

```python
"""Read and write the bodai-plugins marketplace manifest."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

MARKETPLACE_SCHEMA_VERSION = "1.0.0"


@dataclass(frozen=True)
class PluginEntry:
    name: str
    source: str
    ref: str = "main"

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "source": self.source, "ref": self.ref}


def render_marketplace(*, name: str, owner: str, plugins: list[PluginEntry]) -> dict[str, object]:
    return {
        "schema_version": MARKETPLACE_SCHEMA_VERSION,
        "name": name,
        "owner": {"name": owner},
        "plugins": [p.to_dict() for p in plugins],
    }


def load_marketplace(path: Path) -> dict[str, object]:
    return json.loads(path.read_text())


def add_plugin_entry(
    manifest_path: Path,
    *,
    name: str,
    source: str,
    ref: str = "main",
) -> None:
    data = load_marketplace(manifest_path)
    plugins = list(data.get("plugins", []))
    if any(isinstance(p, dict) and p.get("name") == name for p in plugins):
        raise ValueError(f"plugin {name!r} already present in {manifest_path}")
    plugins.append(PluginEntry(name=name, source=source, ref=ref).to_dict())
    data["plugins"] = plugins
    manifest_path.write_text(json.dumps(data, indent=2) + "\n")
```

**Step 4: Wire a marketplace add command in CLI**

Edit `bodai-plugins/bodai_plugins/cli.py`. Add this command after `validate`:

```python
marketplace_app = typer.Typer(help="Manage the marketplace manifest.")
app.add_typer(marketplace_app, name="marketplace")


@marketplace_app.command("add")
def marketplace_add(
    name: str = typer.Option(..., "--name", help="Plugin name."),
    source: str = typer.Option(..., "--source", help="Path or URL to the plugin source."),
    ref: str = typer.Option("main", "--ref", help="Git ref to pin."),
    manifest: Path = typer.Option(
        Path(".claude-plugin/marketplace.json"),
        "--manifest",
        help="Path to the marketplace manifest.",
    ),
) -> None:
    """Register a plugin in the marketplace manifest."""
    from bodai_plugins.scripts.manage_marketplace import add_plugin_entry

    add_plugin_entry(manifest, name=name, source=source, ref=ref)
    typer.echo(f"added {name} -> {manifest}")
```

**Step 5: Run tests**

```bash
cd /Users/les/Projects/bodai-plugins && uv run pytest tests/ -v
```

Expected: all pass.

**Step 6: Commit**

```bash
git add bodai_plugins/ tests/
git commit -m "feat(marketplace): add plugin registry helpers and CLI"
```

---

### Task 6: Initialize the marketplace manifest with empty plugins array

**Files:**
- Create: `bodai-plugins/.claude-plugin/marketplace.json`

**Step 1: Write the initial manifest**

```json
{
  "schema_version": "1.0.0",
  "name": "bodai-plugins",
  "owner": {
    "name": "lesleslie"
  },
  "plugins": []
}
```

**Step 2: Commit**

```bash
git add .claude-plugin/marketplace.json
git commit -m "chore(marketplace): initialize empty plugin registry"
```

---

### Task 7: Add a CI guard test for the marketplace schema

**Files:**
- Create: `bodai-plugins/tests/test_marketplace_schema.py`

**Step 1: Write the test**

```python
from __future__ import annotations

import json
from pathlib import Path

import jsonschema

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = REPO_ROOT / ".claude-plugin" / "marketplace.json"

MARKETPLACE_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "bodai-plugins marketplace manifest",
    "type": "object",
    "required": ["schema_version", "name", "owner", "plugins"],
    "additionalProperties": True,
    "properties": {
        "schema_version": {"type": "string"},
        "name": {"type": "string", "pattern": r"^[a-z][a-z0-9-]*$"},
        "owner": {
            "type": "object",
            "required": ["name"],
            "properties": {"name": {"type": "string"}},
        },
        "plugins": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["name", "source"],
                "properties": {
                    "name": {"type": "string", "pattern": r"^[a-z][a-z0-9-]*$"},
                    "source": {"type": "string"},
                    "ref": {"type": "string"},
                },
            },
        },
    },
}


def test_marketplace_manifest_validates_against_schema() -> None:
    payload = json.loads(MANIFEST_PATH.read_text())
    jsonschema.validate(payload, MARKETPLACE_SCHEMA)


def test_marketplace_plugin_names_are_unique() -> None:
    payload = json.loads(MANIFEST_PATH.read_text())
    names = [p["name"] for p in payload["plugins"]]
    assert len(names) == len(set(names)), f"duplicate plugin names: {names}"
```

**Step 2: Run test**

```bash
cd /Users/les/Projects/bodai-plugins && uv run pytest tests/test_marketplace_schema.py -v
```

Expected: 2 passed.

**Step 3: Commit**

```bash
git add tests/test_marketplace_schema.py
git commit -m "test(marketplace): guard test for manifest schema and uniqueness"
```

---

## Phase 2: Pilot migrate mahavishnu to a plugin

### Task 8: Phase A — Add plugin manifest + namespaced commands (additive)

**Files:**
- Create: `/Users/les/Projects/mahavishnu/.claude-plugin/plugin.json`
- Create: `/Users/les/Projects/mahavishnu/.mcp.json` (new, plugin-local)
- Create: `/Users/les/Projects/mahavishnu/commands/mahavishnu-status.md`
- Create: `/Users/les/Projects/mahavishnu/commands/mahavishnu-checkpoint.md` (or repurpose existing)
- Modify: `/Users/les/Projects/mahavishnu/.mcp.json` (adds a temporary `mahavishnu-plugin` mirror entry)

**Step 1: Use the scaffold to generate the skeleton**

```bash
cd /Users/les/Projects/mahavishnu
mkdir -p /tmp/mahavishnu-scaffold
uv tool run --from bodai-plugins bodai-plugins init mahavishnu --path /tmp/mahavishnu-scaffold --verbose
cp -R /tmp/mahavishnu-scaffold/mahavishnu/.claude-plugin ./
cp -R /tmp/mahavishnu-scaffold/mahavishnu/.mcp.json ./.mcp.plugin.json
cp -R /tmp/mahavishnu-scaffold/mahavishnu/commands ./
```

**Step 2: Edit `.claude-plugin/plugin.json` to point at the real MCP server**

```json
{
  "schema_version": "1.0.0",
  "name": "mahavishnu",
  "version": "0.1.0",
  "description": "Bodai plugin for the Mahavishnu orchestrator MCP server.",
  "author": {"name": "Bodai"},
  "keywords": ["bodai", "mcp", "mahavishnu", "orchestrator"],
  "mcpServers": ".mcp.json"
}
```

**Step 3: Replace `.mcp.json` with the real entry**

Write `.mcp.json`:

```json
{
  "mahavishnu": {
    "type": "http",
    "url": "http://localhost:8680/mcp"
  }
}
```

**Step 4: Move `vishnu-status.md` to `commands/mahavishnu-status.md`**

```bash
mv /Users/les/Projects/mahavishnu/.claude/commands/vishnu-status.md \
   /Users/les/Projects/mahavishnu/commands/mahavishnu-status.md
sed -i '' 's|/vishnu:status|/mahavishnu:status|g' \
   /Users/les/Projects/mahavishnu/commands/mahavishnu-status.md
```

**Step 5: Verify with the scaffold validator**

```bash
cd /Users/les/Projects/mahavishnu
uv tool run --from bodai-plugins bodai-plugins validate --path . --verbose
```

Expected: `OK: /Users/les/Projects/mahavishnu` (treating `.` as a plugin dir via the embedded manifest).

If `validate` complains, use `--fix`:

```bash
uv tool run --from bodai-plugins bodai-plugins validate --path . --fix
```

**Step 6: Smoke test manually**

Layer 4 manual smoke (per design):
1. Open a fresh Claude Code session.
2. Confirm `/mahavishnu:status` is offered as a slash command.
3. Run `/mahavishnu:status` and verify output matches the old `/vishnu-status` output.

**Step 7: Commit (additive, safe)**

```bash
cd /Users/les/Projects/mahavishnu
git add .claude-plugin/ .mcp.json commands/
git commit -m "feat(plugin): add mahavishnu plugin manifest + namespaced commands (additive)"
git push origin main
```

---

### Task 9: Phase B — Remove old flat commands (destructive cutover)

**Files:**
- Delete: `/Users/les/Projects/mahavishnu/.claude/commands/vishnu-status.md`
- Delete: `/Users/les/Projects/mahavishnu/.claude/commands/checkpoint.md` (replaced by `mahavishnu:checkpoint` — but see note below)
- Modify: `/Users/les/Projects/mahavishnu/.mcp.json` (revert to the original 16-server config)

**Note**: `checkpoint.md` calls `mcp__session-buddy__checkpoint` — it's a session-buddy command, NOT a mahavishnu one. Move it to the session-buddy plugin in Phase 3 instead of deleting here.

**Step 1: Confirm Phase A is on main**

```bash
cd /Users/les/Projects/mahavishnu && git log --oneline -5
```

Expected: top commit is the Phase A plugin manifest commit.

**Step 2: Delete old flat slash command**

```bash
git rm .claude/commands/vishnu-status.md
```

**Step 3: Restore the original `.mcp.json`**

```bash
git checkout HEAD~1 -- .mcp.json  # the version before Phase A added a temp entry
```

Verify by running:

```bash
cat .mcp.json | python -c "import json,sys; data=json.load(sys.stdin); print(f'{len(data)} MCP servers configured')"
```

Expected: ~16 (the original count).

**Step 4: Run the validator**

```bash
cd /Users/les/Projects/mahavishnu
uv tool run --from bodai-plugins bodai-plugins validate --path . --verbose
```

Expected: `OK`.

**Step 5: Smoke test manually**

1. Restart Claude Code to drop any cached slash commands.
2. `/mahavishnu:status` should still work (Phase A command).
3. `/vishnu-status` should NOT appear (old command removed).

**Step 6: Commit (destructive cutover)**

```bash
cd /Users/les/Projects/mahavishnu
git add -A
git commit -m "feat(plugin): remove old flat slash commands; mahavishnu plugin is canonical"
git push origin main
```

---

### Task 10: Register mahavishnu plugin in bodai-plugins marketplace

**Files:**
- Modify: `/Users/les/Projects/bodai-plugins/.claude-plugin/marketplace.json`

**Step 1: Use the CLI to register**

```bash
cd /Users/les/Projects/bodai-plugins
uv run bodai-plugins marketplace add --name mahavishnu --source ../mahavishnu --ref main
```

**Step 2: Verify the manifest**

```bash
cat .claude-plugin/marketplace.json
```

Expected: `plugins` array has one entry with `"name": "mahavishnu", "source": "../mahavishnu", "ref": "main"`.

**Step 3: Run the guard test**

```bash
uv run pytest tests/test_marketplace_schema.py -v
```

Expected: 2 passed.

**Step 4: Smoke test the marketplace**

```bash
claude plugin marketplace add /Users/les/Projects/bodai-plugins
claude plugin install mahavishnu
```

Expected: mahavishnu plugin installed.

**Step 5: Commit**

```bash
cd /Users/les/Projects/bodai-plugins
git add .claude-plugin/marketplace.json
git commit -m "chore(marketplace): register mahavishnu plugin"
git push origin main
```

---

## Phase 3: Migrate the remaining four MCP servers

### Task 11: Migrate session-buddy (two-phase)

**Repeat the Phase 2 pattern (Tasks 8 → 9 → 10) for session-buddy.**

Concrete differences:

- Plugin directory: `/Users/les/Projects/session-buddy/.claude-plugin/plugin.json`
- Namespace prefix: `session-buddy:`
- MCP URL: `http://localhost:8678/mcp`
- Migrate these commands from `/Users/les/Projects/mahavishnu/.claude/commands/` to `/Users/les/Projects/session-buddy/commands/`:
  - `checkpoint.md` → `session-buddy-checkpoint.md`
  - `start.md` → `session-buddy-start.md`
  - `end.md` → `session-buddy-end.md`
- After Phase A lands, delete `checkpoint.md`, `start.md`, `end.md` from `/Users/les/Projects/mahavishnu/.claude/commands/` in Phase B.
- Register in marketplace: `bodai-plugins marketplace add --name session-buddy --source ../session-buddy --ref main`.

Reference commands:

```bash
# Phase A
cd /Users/les/Projects/session-buddy
mkdir -p /tmp/sb-scaffold
uv tool run --from bodai-plugins bodai-plugins init session-buddy --path /tmp/sb-scaffold
cp -R /tmp/sb-scaffold/session-buddy/.claude-plugin ./
cp -R /tmp/sb-scaffold/session-buddy/.mcp.json ./
mkdir -p commands
# Move the 3 commands listed above from mahavishnu/.claude/commands/ into session-buddy/commands/, rename to session-buddy-* prefix
# Smoke test
uv tool run --from bodai-plugins bodai-plugins validate --path . --verbose
git add -A && git commit -m "feat(plugin): add session-buddy plugin manifest + namespaced commands (additive)"

# Phase B
git rm /Users/les/Projects/mahavishnu/.claude/commands/checkpoint.md
git rm /Users/les/Projects/mahavishnu/.claude/commands/start.md
git rm /Users/les/Projects/mahavishnu/.claude/commands/end.md
# Commit per-repo: session-buddy removes nothing, the deletions happen in mahavishnu.
cd /Users/les/Projects/mahavishnu
git add -A && git commit -m "feat(plugin): remove old flat session-buddy commands (now session-buddy:<cmd>)"

cd /Users/les/Projects/session-buddy
git add -A && git commit -m "feat(plugin): remove old flat slash commands; session-buddy plugin is canonical"

cd /Users/les/Projects/bodai-plugins
uv run bodai-plugins marketplace add --name session-buddy --source ../session-buddy --ref main
git add -A && git commit -m "chore(marketplace): register session-buddy plugin"
```

---

### Task 12: Migrate crackerjack (two-phase)

Same pattern. Differences:

- Plugin directory: `/Users/les/Projects/crackerjack/.claude-plugin/plugin.json`
- Namespace prefix: `crackerjack:`
- MCP URL: `http://localhost:8676/mcp`
- Migrate `crackerjack/slash_commands/*.md` content into `/Users/les/Projects/crackerjack/commands/`, renaming to `crackerjack-<command>.md`.
- Phase B: delete `/Users/les/Projects/crackerjack/slash_commands/` (it's a documentation directory, not real plugin commands — confirm by reading `/Users/les/Projects/crackerjack/crackerjack/slash_commands/README.md`).
- Register in marketplace.

```bash
# Phase A
cd /Users/les/Projects/crackerjack
mkdir -p /tmp/cj-scaffold
uv tool run --from bodai-plugins bodai-plugins init crackerjack --path /tmp/cj-scaffold
cp -R /tmp/cj-scaffold/crackerjack/.claude-plugin ./
cp -R /tmp/cj-scaffold/crackerjack/.mcp.json ./
mkdir -p commands
# Move status.md, init.md, run.md from crackerjack/slash_commands/ into commands/, rename to crackerjack-*.md
uv tool run --from bodai-plugins bodai-plugins validate --path . --verbose
git add -A && git commit -m "feat(plugin): add crackerjack plugin manifest + namespaced commands (additive)"

# Phase B
git rm -r crackerjack/slash_commands/   # in the crackerjack repo
git add -A && git commit -m "feat(plugin): remove legacy slash_commands/; crackerjack plugin is canonical"

# Register
cd /Users/les/Projects/bodai-plugins
uv run bodai-plugins marketplace add --name crackerjack --source ../crackerjack --ref main
git add -A && git commit -m "chore(marketplace): register crackerjack plugin"
```

---

### Task 13: Migrate akosha (two-phase)

Same pattern. Differences:

- Plugin directory: `/Users/les/Projects/akosha/.claude-plugin/plugin.json`
- Namespace prefix: `akosha:`
- MCP URL: `http://localhost:8682/mcp`
- Akosha has NO existing slash commands (no migration of legacy files). Phase A only adds the manifest + a starter `commands/akosha-search.md` and `commands/akosha-analyze.md` that wrap the most-used MCP tools.
- Register in marketplace.

```bash
cd /Users/les/Projects/akosha
mkdir -p /tmp/ak-scaffold
uv tool run --from bodai-plugins bodai-plugins init akosha --path /tmp/ak-scaffold
cp -R /tmp/ak-scaffold/akosha/.claude-plugin ./
cp -R /tmp/ak-scaffold/akosha/.mcp.json ./
mkdir -p commands
# Author commands/akosha-search.md and commands/akosha-analyze.md from scratch, wrapping mcp__akosha__search_all_systems and mcp__akosha__analyze_imports respectively.
uv tool run --from bodai-plugins bodai-plugins validate --path . --verbose
git add -A && git commit -m "feat(plugin): initial akosha plugin manifest + starter commands"

# Register
cd /Users/les/Projects/bodai-plugins
uv run bodai-plugins marketplace add --name akosha --source ../akosha --ref main
git add -A && git commit -m "chore(marketplace): register akosha plugin"
```

---

### Task 14: Migrate dhara (two-phase)

Same pattern. Differences:

- Plugin directory: `/Users/les/Projects/dhara/.claude-plugin/plugin.json`
- Namespace prefix: `dhara:`
- MCP URL: `http://localhost:8683/mcp`
- Dhara has NO existing slash commands. Phase A only adds the manifest + a starter `commands/dhara-put.md` and `commands/dhara-get.md` wrapping the two primary state operations.
- Register in marketplace.

```bash
cd /Users/les/Projects/dhara
mkdir -p /tmp/dh-scaffold
uv tool run --from bodai-plugins bodai-plugins init dhara --path /tmp/dh-scaffold
cp -R /tmp/dh-scaffold/dhara/.claude-plugin ./
cp -R /tmp/dh-scaffold/dhara/.mcp.json ./
mkdir -p commands
# Author commands/dhara-put.md and commands/dhara-get.md wrapping mcp__dhara__put and mcp__dhara__get respectively.
uv tool run --from bodai-plugins bodai-plugins validate --path . --verbose
git add -A && git commit -m "feat(plugin): initial dhara plugin manifest + starter commands"

# Register
cd /Users/les/Projects/bodai-plugins
uv run bodai-plugins marketplace add --name dhara --source ../dhara --ref main
git add -A && git commit -m "chore(marketplace): register dhara plugin"
```

---

## Phase 4: Workflow lifecycle (decisions + archive)

### Task 15: Add workflow decision lifecycle template + README

**Files:**
- Create: `/Users/les/Projects/mahavishnu/.claude/decisions/workflows/README.md`
- Create: `/Users/les/Projects/mahavishnu/.claude/decisions/workflows/TEMPLATE.md`

**Step 1: Write the README**

```markdown
# Workflow decisions

Pair every workflow in `.claude/workflows/` with a decision file here.

Lifecycle:

- **Active** — current, run as needed. Workflow lives in `.claude/workflows/`.
- **Superseded** — replaced by a newer workflow. Move the .js to `.claude/workflows/.archive/` and update this file's Status.
- **Archived** — no longer relevant. Move to `.claude/workflows/.archive/` and update Status.

Files use `YYYY-MM-DD-<name>.md` pattern. Status header is `## Status: Active | Superseded | Archived`.

Index:

| Decision file | Workflow | Status | Notes |
|---|---|---|---|
| (none yet) | | | |
```

**Step 2: Write the TEMPLATE**

```markdown
# YYYY-MM-DD-<name> — workflow decision

## Status

Active

## Context

What problem this workflow solved and when it was created. Include a link to the workflow file.

## Decision rule

When to use this workflow. What triggers it. What it produces.

## Status history

- YYYY-MM-DD — Created.
```

**Step 3: Commit**

```bash
cd /Users/les/Projects/mahavishnu
git add .claude/decisions/workflows/
git commit -m "docs(decisions): add workflow decision README and template"
```

---

### Task 16: Pair existing wave workflows with decision files (Active)

**Files:** Create one decision file per existing wave workflow.

For each `.js` file in `/Users/les/Projects/mahavishnu/.claude/workflows/`:

1. Note the wave's purpose from the header comment.
2. Create `.claude/decisions/workflows/YYYY-MM-DD-<wave-name>.md` with `## Status: Active` and a 1-paragraph decision rule explaining when to re-run it.

Reference for the wave workflows to pair (created in earlier work):

| Workflow file | Decision filename |
|---|---|
| `crackerjack-coverage-fanout-wave4.js` | `2026-04-26-crackerjack-coverage-fanout-wave4.md` |
| `crackerjack-coverage-fanout-wave5.js` | `2026-04-30-crackerjack-coverage-fanout-wave5.md` |
| `crackerjack-coverage-fanout-wave6.js` | `2026-05-15-crackerjack-coverage-fanout-wave6.md` |
| `crackerjack-cleanup-wave7.js` | `2026-05-22-crackerjack-cleanup-wave7.md` |
| `mahavishnu-coverage-fanout-wave-2026-06-12.js` | `2026-06-12-mahavishnu-coverage-fanout.md` |
| `mahavishnu-coverage-fanout-wave-2026-06-12-part2.js` | `2026-06-12-mahavishnu-coverage-fanout-part2.md` |

For each, write a decision file like:

```markdown
# 2026-04-26-crackerjack-coverage-fanout-wave4 — workflow decision

## Status

Active

## Context

Wave-4 of the crackerjack coverage fan-out. Lifted the smallest remaining zero-coverage tier and added regression fixes.

## Decision rule

Re-run this workflow when crackerjack total coverage drops below 70% or when a new package reaches the smallest-zero-coverage tier. Expect ~30-min wall-clock; uses 12 parallel python-pro agents.

## Status history

- 2026-04-26 — Created.
```

Commit:

```bash
cd /Users/les/Projects/mahavishnu
git add .claude/decisions/workflows/
git commit -m "docs(workflows): pair existing wave workflows with decision files"
```

---

### Task 17: Move executed/replaced waves to `.archive/` + flip Status

For each wave that has been **executed and superseded** by a later wave:

1. Move the `.js` to `.claude/workflows/.archive/`.
2. Flip the matching decision file's Status to `Superseded`.
3. Add a `## Status history` entry with the supersession date and pointer to the replacement wave.

Determine "executed and superseded" from the wave numbers (4 → 5 → 6 → 7 → 2026-06-12). Each previous wave was a step toward the next, so waves 4-6 and the 2026-06-12 part1 are now `Superseded` by their successor. Wave 7 and 2026-06-12 part2 are `Active` unless an even newer wave exists.

Reference commands (one per wave):

```bash
cd /Users/les/Projects/mahavishnu

# Wave 4 → superseded by wave 5
git mv .claude/workflows/crackerjack-coverage-fanout-wave4.js .claude/workflows/.archive/
# Then edit its decision file: flip Status to Superseded, add history entry pointing to wave-5.

# Wave 5 → superseded by wave 6
git mv .claude/workflows/crackerjack-coverage-fanout-wave5.js .claude/workflows/.archive/
# Edit decision file.

# Wave 6 → superseded by wave 7
git mv .claude/workflows/crackerjack-coverage-fanout-wave6.js .claude/workflows/.archive/

# 2026-06-12 part1 → superseded by part2
git mv .claude/workflows/mahavishnu-coverage-fanout-wave-2026-06-12.js .claude/workflows/.archive/

git commit -am "docs(workflows): archive superseded waves and update their decision Status"
```

---

### Task 18: Add `scripts/audit_workflow_lifecycle.py`

**Files:**
- Create: `/Users/les/Projects/mahavishnu/scripts/audit_workflow_lifecycle.py`
- Create: `/Users/les/Projects/mahavishnu/tests/test_audit_workflow_lifecycle.py`

**Step 1: Write the failing test**

```python
from __future__ import annotations

from pathlib import Path

from scripts.audit_workflow_lifecycle import audit_workflows


def _make_repo(tmp_path: Path) -> Path:
    wf = tmp_path / ".claude" / "workflows"
    wf.mkdir(parents=True)
    (wf / "wave-x.js").write_text("// wave x\n")
    decisions = tmp_path / ".claude" / "decisions" / "workflows"
    decisions.mkdir(parents=True)
    (decisions / "2026-01-01-wave-x.md").write_text(
        "# 2026-01-01-wave-x\n\n## Status\n\nActive\n\n## Context\n\nfoo\n"
    )
    return tmp_path


def test_audit_passes_when_each_workflow_has_a_decision(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    issues = audit_workflows(repo)
    assert issues == []


def test_audit_flags_missing_decision(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    (repo / ".claude" / "workflows" / "wave-y.js").write_text("// wave y\n")
    issues = audit_workflows(repo)
    assert any("wave-y" in i for i in issues)


def test_audit_ignores_archive(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    archive = repo / ".claude" / "workflows" / ".archive"
    archive.mkdir()
    (archive / "wave-old.js").write_text("// old\n")
    issues = audit_workflows(repo)
    assert issues == []
```

**Step 2: Run test to verify failure**

```bash
cd /Users/les/Projects/mahavishnu && uv run pytest tests/test_audit_workflow_lifecycle.py -v
```

Expected: ModuleNotFoundError.

**Step 3: Implement the audit script**

`/Users/les/Projects/mahavishnu/scripts/audit_workflow_lifecycle.py`:

```python
"""Audit `.claude/workflows/` for missing or mismatched decision files."""

from __future__ import annotations

import re
from pathlib import Path

DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-([a-z0-9-]+)\.md$")


def audit_workflows(repo_root: Path) -> list[str]:
    """Return a list of human-readable issues; empty list means clean."""
    issues: list[str] = []
    wf_dir = repo_root / ".claude" / "workflows"
    dec_dir = repo_root / ".claude" / "decisions" / "workflows"

    if not wf_dir.is_dir():
        return issues

    active = sorted(p for p in wf_dir.glob("*.js") if p.is_file())
    decisions = {p.stem for p in dec_dir.glob("*.md")} if dec_dir.is_dir() else set()

    for wf in active:
        stem = wf.stem  # e.g. "crackerjack-coverage-fanout-wave4"
        # Look for any decision file whose date-name-slug matches the workflow slug.
        # Convention: decision file ends with "-<workflow-stem>.md"
        match = next((d for d in decisions if d.endswith(f"-{stem}")), None)
        if match is None:
            issues.append(f"{wf.name}: no paired decision file in {dec_dir}")

    return issues


if __name__ == "__main__":
    import sys

    repo = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
    issues = audit_workflows(repo)
    if issues:
        for line in issues:
            print(f"FAIL: {line}")
        sys.exit(1)
    print("OK")
```

**Step 4: Run tests**

```bash
cd /Users/les/Projects/mahavishnu && uv run pytest tests/test_audit_workflow_lifecycle.py -v
```

Expected: 3 passed.

**Step 5: Smoke test against the live repo**

```bash
cd /Users/les/Projects/mahavishnu
uv run python scripts/audit_workflow_lifecycle.py .
```

Expected: `OK` (after Tasks 16 + 17 land).

**Step 6: Commit**

```bash
git add scripts/audit_workflow_lifecycle.py tests/test_audit_workflow_lifecycle.py
git commit -m "feat(audit): workflow lifecycle audit script"
```

---

### Task 19: Add `followups/` lifecycle parity (parallel feature)

**Files:**
- Create: `/Users/les/Projects/mahavishnu/docs/followups/README.md`
- Create: `/Users/les/Projects/mahavishnu/docs/followups/TEMPLATE.md`

The user noted `docs/followups/` is being changed to follow the same lifecycle as `docs/decisions`. Apply the same shape used for workflow decisions.

**Step 1: Write the README**

```markdown
# Followups

Time-bounded follow-up items. Pair with `.claude/decisions/` lifecycle.

Status: **Open** | **Resolved** | **Archived**.

Files use `YYYY-MM-DD-<name>.md` pattern.
```

**Step 2: Write the TEMPLATE**

```markdown
# YYYY-MM-DD-<name> — followup

## Status

Open

## Trigger

What prompted this followup.

## Action

Concrete next step.
```

**Step 3: Commit**

```bash
cd /Users/les/Projects/mahavishnu
git add docs/followups/
git commit -m "docs(followups): add lifecycle README and template"
```

(Existing followup files keep their shape; only new files use the template.)

---

## Phase 5: Publish + announce

### Task 20: Tag bodai-plugins v1.0.0

**Files:** none new.

**Step 1: Final validation**

```bash
cd /Users/les/Projects/bodai-plugins
uv run pytest -v
uv run bodai-plugins validate --path . --verbose
```

Expected: all tests pass; `OK`.

**Step 2: Build the wheel**

```bash
cd /Users/les/Projects/bodai-plugins
uv build
```

Expected: `dist/bodai_plugins-1.0.0-py3-none-any.whl` and `.tar.gz`.

**Step 3: Tag + push**

```bash
cd /Users/les/Projects/bodai-plugins
git tag -a v1.0.0 -m "bodai-plugins v1.0.0 — initial 5-plugin marketplace"
git push origin main --tags
```

---

### Task 21: Document the marketplace in bodai umbrella README

**Files:**
- Modify: `/Users/les/Projects/bodai/README.md` (if it exists; otherwise create one)

**Step 1: Add a "Marketplace" section**

Append to `bodai/README.md`:

```markdown
## Claude Code marketplace

The five Bodai MCP-server plugins are distributed via the `bodai-plugins` marketplace:

```bash
claude plugin marketplace add https://github.com/lesleslie/bodai-plugins
claude plugin install mahavishnu
claude plugin install session-buddy
claude plugin install crackerjack
claude plugin install akosha
claude plugin install dhara
```

Each plugin ships its own slash commands under the `<server>:<command>` namespace (e.g. `/mahavishnu:status`, `/session-buddy:checkpoint`).
```

**Step 2: Commit**

```bash
cd /Users/les/Projects/bodai
git add README.md
git commit -m "docs: link bodai-plugins marketplace from umbrella README"
```

---

### Task 22: Final smoke test of the whole flow

This is the Layer 4 manual smoke test from the design (everything end-to-end).

**Step 1: Reset Claude Code's plugin cache**

```bash
rm -rf ~/.claude/plugins/cache/bodai-plugins
claude plugin marketplace add https://github.com/lesleslie/bodai-plugins
claude plugin install mahavishnu
claude plugin install session-buddy
claude plugin install crackerjack
claude plugin install akosha
claude plugin install dhara
```

**Step 2: Verify all slash namespaces resolve**

Open a fresh Claude Code session and confirm:

- `/mahavishnu:status` appears
- `/session-buddy:checkpoint` appears
- `/crackerjack:status` appears
- `/akosha:search` appears
- `/dhara:put` appears

**Step 3: Run each one and verify MCP wiring works**

Each command should resolve its MCP server entry (the URL defined in the plugin's `.mcp.json`) and return data.

**Step 4: Verify the audit is clean**

```bash
cd /Users/les/Projects/mahavishnu && uv run python scripts/audit_workflow_lifecycle.py .
```

Expected: `OK`.

**Step 5: Note completion in CHANGELOG**

Edit `/Users/les/Projects/bodai-plugins/CHANGELOG.md`:

```markdown
# Changelog

## 1.0.0 — 2026-07-16

Initial release. Distributes 5 Bodai MCP-server plugins via the `bodai-plugins` marketplace:

- mahavishnu (orchestrator)
- session-buddy (memory)
- crackerjack (quality)
- akosha (intelligence)
- dhara (state)

Scaffold CLI: `bodai-plugins init <name>` and `bodai-plugins validate --fix`.
```

**Step 6: Commit the changelog**

```bash
cd /Users/les/Projects/bodai-plugins
git add CHANGELOG.md
git commit -m "docs(changelog): v1.0.0 release notes"
git push origin main
```

---

## Self-review checklist (run before handoff)

- [ ] **Spec coverage**: design spec sections → tasks:
  - Approach C (5 plugins + marketplace + scaffold-first) → Tasks 1-7, 8-10, 11-14
  - Plugin manifest schema → Tasks 3, 7
  - Marketplace manifest schema → Tasks 5-7
  - Scaffold CLI (init + validate with --fix/--verbose/--json/--force) → Tasks 3, 4
  - Naming convention (full server name as prefix, bodai: exception) → Tasks 8, 11, 12, 13, 14
  - Workflow lifecycle (Active/Superseded/Archived + .archive/) → Tasks 15, 16, 17, 18
  - Two-phase migration → Tasks 8, 9, 11, 12, 13, 14
  - Publishing + announce → Tasks 20, 21, 22
- [ ] **Placeholder scan**: no TBD/TODO/"similar to Task N" — each step has concrete code or commands.
- [ ] **Type consistency**: `scaffold_plugin(name, target, *, force, verbose) -> Path` consistent across Tasks 3, 4, 5, 8; `validate_plugin(plugin_dir, *, fix) -> list[ValidationIssue]` consistent across Tasks 4, 7.
- [ ] **No regressions**: every deleted file (Tasks 9, 11, 12, 17) has a replacement in the new layout.
- [ ] **CI guard test**: `tests/test_marketplace_schema.py` (Task 7) and `scripts/audit_workflow_lifecycle.py` (Task 18) catch the regressions the design promises.

---

## Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-16-bodai-plugin-standardization.md`.

Two execution options:

1. **Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** — execute tasks in this session using executing-plans, batch execution with checkpoints.
