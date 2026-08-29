"""Typer CLI surface inventory for Bodai Core 7.

Walks each Core 7 repo's Typer app recursively and captures per-command
schema for the audit. Used by Phase 1 inventory subagents and the
quarterly staleness re-audit cadence (Phase 7.5).

Usage:
    python scripts/audit_cli_inventory.py --repo mahavishnu
    python scripts/audit_cli_inventory.py --all
    python scripts/audit_cli_inventory.py --all --check-stale
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from importlib.metadata import version as metadata_version
from pathlib import Path
from typing import Any

import typer

app = typer.Typer(help="Bodai CLI surface inventory")


@dataclass
class CommandEntry:
    command_path: str
    module: str
    function: str
    short_help: str
    deprecated: bool = False
    hidden: bool = False
    experimental: bool = False
    first_added_sha: str = ""
    last_modified_sha: str = ""
    last_modified_date: str = ""
    tests_present: bool = False
    doc_referenced: list[str] = field(default_factory=list)
    subcommand_count: int = 0
    todo_markers: int = 0
    last_activity_days: int = -1
    short_help_vs_impl_drift: str = ""
    staleness_verdict: str = "unknown"
    notes: list[str] = field(default_factory=list)


TODO_PATTERN = re.compile(r"\b(TODO|FIXME|XXX|HACK)\b")


def _walk_typer(app: typer.Typer, prefix: str = "") -> list[CommandEntry]:
    """Recursively walk a Typer app's commands + sub-apps."""
    entries: list[CommandEntry] = []
    for sub_info in getattr(app, "registered_groups", []):
        sub_app = sub_info.typer_instance
        sub_name = sub_info.name or sub_app.info.name
        entries.extend(_walk_typer(sub_app, prefix=f"{prefix}{sub_name} "))
    registered_commands = getattr(app, "registered_commands", {})
    # Typer 0.9+: dict[cmd_name, CommandInfo]; older: list[CommandInfo]
    cmd_items = (
        registered_commands.items()
        if hasattr(registered_commands, "items")
        else ((getattr(cmd, "name", ""), cmd) for cmd in registered_commands)
    )
    for cmd_name, cmd in cmd_items:
        full_path = f"{prefix}{cmd_name}".strip()
        callback = cmd.callback
        module = getattr(callback, "__module__", "")
        func = getattr(callback, "__name__", "")
        doc_first = ""
        if callback:
            doc_text = callback.__doc__ or ""
            if doc_text:
                lines = doc_text.splitlines()
                doc_first = lines[0] if lines else ""
        short_help = (cmd.help or doc_first).strip()
        sub_count = len(getattr(cmd, "subcommands", {}))
        entries.append(
            CommandEntry(
                command_path=full_path,
                module=module,
                function=func,
                short_help=short_help,
                subcommand_count=sub_count,
                deprecated=getattr(cmd, "deprecated", False)
                or "[deprecated]" in short_help.lower(),
                hidden=getattr(cmd, "hidden", False),
                experimental="experimental" in short_help.lower()
                or "alpha" in short_help.lower(),
            )
        )
    return entries


def _staleness_signals(module: str, repo_path: str) -> dict[str, Any]:
    if not module:
        return {"todo_markers": 0, "last_activity_days": -1}
    module_file = module.replace(".", "/") + ".py"
    src_path = Path(repo_path) / module_file
    if not src_path.exists():
        candidates = list(Path(repo_path).rglob(Path(module_file).name))
        src_path = candidates[0] if candidates else src_path
    todo_count = 0
    last_activity_days = -1
    if src_path.exists():
        text = src_path.read_text(errors="ignore")
        todo_count = len(TODO_PATTERN.findall(text))
        try:
            r = subprocess.run(
                [
                    "git",
                    "-C",
                    repo_path,
                    "log",
                    "-1",
                    "--format=%ct",
                    "--",
                    str(src_path.relative_to(repo_path)),
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if r.returncode == 0 and r.stdout.strip():
                last_activity_days = int((time.time() - int(r.stdout.strip())) / 86400)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass
    return {"todo_markers": todo_count, "last_activity_days": last_activity_days}


def _staleness_verdict(cmd: CommandEntry) -> str:
    if cmd.deprecated:
        return "deprecated"
    if cmd.experimental and cmd.short_help_vs_impl_drift == "stub":
        return "stale"
    if cmd.todo_markers >= 3:
        return "stale"
    if cmd.last_activity_days > 365 and cmd.todo_markers >= 1:
        return "stale"
    return "current"


def inventory_one_repo(repo: str, repo_path: str, out_path: Path) -> dict[str, Any]:
    sys.path.insert(0, repo_path)
    try:
        if repo == "mcp-common":
            data = {
                "repo": repo,
                "command_count": 0,
                "commands": [],
                "notes": ["library-only; no CLI surface"],
                "version": _safe_version(repo),
            }
            out_path.write_text(json.dumps(data, indent=2))
            return data
        entry_points = {
            "oneiric": ("oneiric.cli", "app"),
            "dhara": ("dhara.cli", "create_cli"),
            "session-buddy": ("session_buddy.cli", "app"),
            "akosha": ("akosha.cli", "app"),
            "crackerjack": ("crackerjack.__main__", "app"),
            "mahavishnu": ("mahavishnu._main_cli", "app"),
        }
        mod_name, attr_name = entry_points[repo]
        mod = __import__(mod_name, fromlist=[attr_name])
        typer_app = getattr(mod, attr_name)
        # Typer instances: the imported object IS the app (it's already
        # instantiated; calling it would trigger CLI execution). Some
        # repos expose a `create_app()` factory returning a fresh app —
        # we honour that, but we never call a Typer instance as a
        # callable, since that exits with code 2 ("no command given").
        if hasattr(typer_app, "create_app") and not isinstance(typer_app, typer.Typer):
            typer_app = typer_app.create_app()
    finally:
        sys.path.pop(0)
    commands = _walk_typer(typer_app)
    for cmd in commands:
        signals = _staleness_signals(cmd.module, repo_path)
        cmd.todo_markers = signals["todo_markers"]
        cmd.last_activity_days = signals["last_activity_days"]
        cmd.staleness_verdict = _staleness_verdict(cmd)
    data = {
        "repo": repo,
        "version": _safe_version(repo),
        "command_count": len(commands),
        "commands": [asdict(c) for c in commands],
        "notes": [],
    }
    out_path.write_text(json.dumps(data, indent=2, default=str))
    return data


def _safe_version(repo: str) -> str:
    try:
        return metadata_version(repo)
    except Exception:
        return "(not installed)"


def write_phase_0_baseline(repos: list[str], repo_root: str, out_path: Path) -> None:
    baseline = {"phase": 0, "repos": {}}
    for repo in repos:
        json_path = out_path.parent / f"{repo}-cli-inventory.json"
        if json_path.exists():
            baseline["repos"][repo] = json.loads(json_path.read_text())
    out_path.write_text(json.dumps(baseline, indent=2, default=str))


@app.command()
def repo(
    repo_name: str = typer.Option(..., "--repo", help="Single repo to inventory"),
    check_stale: bool = typer.Option(False, "--check-stale"),
) -> None:
    repo_path = f"/Users/les/Projects/{repo_name}"
    out_dir = Path("docs/audit-inventory")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{repo_name}-cli-inventory.json"
    data = inventory_one_repo(repo_name, repo_path, out_path)
    typer.echo(f"Wrote {out_path} ({data['command_count']} commands)")


@app.command(name="all")
def all_repos(
    check_stale: bool = typer.Option(
        False, "--check-stale", help="Exit non-zero if any command is stale"
    ),
) -> None:
    repos = [
        "mcp-common",
        "oneiric",
        "dhara",
        "session-buddy",
        "akosha",
        "crackerjack",
        "mahavishnu",
    ]
    out_dir = Path("docs/audit-inventory")
    out_dir.mkdir(parents=True, exist_ok=True)
    any_stale = False
    for repo in repos:
        repo_path = f"/Users/les/Projects/{repo}"
        out_path = out_dir / f"{repo}-cli-inventory.json"
        try:
            data = inventory_one_repo(repo, repo_path, out_path)
        except (ImportError, AttributeError, OSError) as e:
            typer.echo(f"[red]FAIL: {repo}: {e}[/red]")
            continue
        typer.echo(f"{repo}: {data['command_count']} commands")
        if check_stale:
            stale = [
                c for c in data["commands"] if c["staleness_verdict"] in {"stale", "deprecated"}
            ]
            if stale:
                any_stale = True
                typer.echo(f"  [yellow]{len(stale)} stale/deprecated commands[/yellow]")
    write_phase_0_baseline(repos, "/Users/les/Projects", out_dir / "PHASE_0_BASELINE.json")
    if check_stale and any_stale:
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()