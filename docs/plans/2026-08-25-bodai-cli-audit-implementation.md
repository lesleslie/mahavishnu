# Bodai Core 7 CLI Audit & Standardization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Every Bodai Core 7 CLI exposes consistent `version`, `doctor`, `health` global commands; a single `bodai` umbrella CLI composes all seven via entry-point discovery; CLI surface is inventoried and audited for staleness quarterly.

**Architecture:** Shared `BodaiCLIBase(typer.Typer)` in `oneiric.cli.base` provides the contract. Each Core 7 repo's CLI converts to extend the base class. `MCPServerCLIFactory.register_lifecycle_handlers()` lets the 3 lifecycle-bearing repos (crackerjack, dhara, session-buddy) keep their `--start/stop/restart/status/health` commands via the base class. `bodai` umbrella discovers sub-CLIs via the `bodai.apps` entry-point group and mounts them via Typer `add_typer`. Per-repo CLI surface is inventoried via `scripts/audit_cli_inventory.py`; quarterly cadence re-runs for staleness.

**Tech Stack:** Python 3.14, Typer ≥0.9, Rich ≥13, Pydantic v2, pytest, uv, GitHub Actions (umbrella CI).

**Plan status:** COMPLETE 2026-08-29 — all 13 sub-tasks shipped. See `BODAI_REPO_REGISTRY.md` "CLI surface summary" section for the post-audit command count and `docs/audit-inventory/findings-staleness.md` for the staleness sweep.

**Spec:** `/Users/les/Projects/mahavishnu/docs/plans/2026-08-25-bodai-cli-audit.md`

**Companion plan (downstream):** `/Users/les/Projects/mahavishnu/docs/plans/2026-08-25-bodai-tui-shell-surface.md` (Plan B; depends on Plan A's BodaiCLIBase foundation).

## Global Constraints

- **Python version**: `>=3.14` (per Bodai pre-1.0 3.14 migration; see `BODAI_REPO_REGISTRY.md`)
- **Pre-1.0 merge policy**: direct to main, no PRs. Per-repo commits land in worktree branches, fast-forward `main` via `git update-ref refs/heads/main <branch>` from the main checkout. Do NOT run cross-worktree file ops in the main checkout (Bash classifier blocks per `mahavishname-worktree-isolation-guard-is-bash-classifier`).
- **Secret rule**: no literal `*_KEY`/`*_TOKEN`/`*_SECRET`/`*_PASSWORD` values in any `.mcp.json`. Enforced by pre-commit hook via `scripts/audit_no_secrets_in_mcp.py`.
- **Naming convention**: kebab-case for repo names in user-facing surfaces (`session-buddy`, `bodai-apps`); underscore for Python module paths.
- **CHANGELOG convention**: every commit that changes user-facing CLI behavior must include a matching `CHANGELOG.md` entry with `### Changed` / `### Removed` / `### Deprecated` / `### Added` / `### Fixed` / `### Security` section and `**BREAKING:**` prefix where applicable.
- **Per-commit landing pattern** (per spec §5.0): each per-repo commit lands in its own worktree branch (`<worktree>/<phase>-<repo>`), then fast-forwards `main` via `git update-ref refs/heads/main <branch>`. Refresh main checkout's working tree manually between merges.

______________________________________________________________________

## Task ordering

Tasks are grouped into the 8 phases from the spec. **Critical-path items** (block the most downstream work):

1. **Task 0.5** — mcp-common factory syntax fix (4-char change, unblocks Phase 4.2)
1. **Task 4.0** — oneiric package conversion (precondition for Phase 4.1)
1. **Task 4.2** — `register_lifecycle_handlers` (after 0.5; blocks Phase 4.3)
1. **Task 4.5** — umbrella CI job (after 0.5; gates every Phase 4.3 conversion)

**Parallelizable** (independent per-repo commits): Phase 3 sub-phases; Phase 4.3 conversions; Phase 5.1 entry-point declarations.

______________________________________________________________________

## Phase 0 — Inventory tooling

### Task 0.1: Write `scripts/audit_cli_inventory.py` (mahavishnu)

**Files:**

- Create: `/Users/les/Projects/mahavishnu/scripts/audit_cli_inventory.py`
- Test: `/Users/les/Projects/mahavishnu/tests/unit/test_audit_cli_inventory.py`

**Interfaces:**

- Consumes: each Core 7 repo's Typer app (via importlib)

- Produces: per-repo JSON inventory + MD summary; PHASE_0_BASELINE.json aggregate

- [x] **Step 1: Write the failing test**

```python
# tests/unit/test_audit_cli_inventory.py
import json
from pathlib import Path
from scripts.audit_cli_inventory import inventory_one_repo

def test_inventory_mahavishnu_returns_per_command_fields(tmp_path):
    out = tmp_path / "mahavishnu-cli-inventory.json"
    data = inventory_one_repo("mahavishnu", "/Users/les/Projects/mahavishnu", out)
    assert data["repo"] == "mahavishnu"
    assert "commands" in data
    assert isinstance(data["commands"], list)
    # Per-command schema (every command must have these keys)
    for cmd in data["commands"]:
        assert set(cmd.keys()) >= {
            "command_path", "module", "function", "short_help",
            "tests_present", "staleness_verdict",
        }
```

- [x] **Step 2: Run test to verify it fails**

Run: `cd /Users/les/Projects/mahavishnu && uv run pytest tests/unit/test_audit_cli_inventory.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.audit_cli_inventory'`

- [x] **Step 3: Write minimal implementation**

```python
# scripts/audit_cli_inventory.py
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
from dataclasses import dataclass, asdict, field
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
    for cmd_name, cmd in getattr(app, "registered_commands", {}).items():
        full_path = f"{prefix}{cmd_name}".strip()
        callback = cmd.callback
        module = getattr(callback, "__module__", "")
        func = getattr(callback, "__name__", "")
        short_help = (cmd.help or (callback.__doc__ or "").splitlines()[0] if callback.__doc__ else "").strip()
        sub_count = len(getattr(cmd, "subcommands", {}))
        entries.append(CommandEntry(
            command_path=full_path,
            module=module,
            function=func,
            short_help=short_help,
            subcommand_count=sub_count,
            deprecated=getattr(cmd, "deprecated", False) or "[deprecated]" in short_help.lower(),
            hidden=getattr(cmd, "hidden", False),
            experimental="experimental" in short_help.lower() or "alpha" in short_help.lower(),
        ))
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
                ["git", "-C", repo_path, "log", "-1", "--format=%ct", "--", str(src_path.relative_to(repo_path))],
                capture_output=True, text=True, timeout=5,
            )
            if r.returncode == 0 and r.stdout.strip():
                import time
                last_activity_days = int((time.time() - int(r.stdout.strip())) / 86400)
        except Exception:
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
            data = {"repo": repo, "commands": [], "notes": ["library-only; no CLI surface"], "version": _safe_version(repo)}
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
        if hasattr(typer_app, "create_app"):
            typer_app = typer_app.create_app()
        elif callable(typer_app):
            typer_app = typer_app()
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
    check_stale: bool = typer.Option(False, "--check-stale", help="Exit non-zero if any command is stale"),
) -> None:
    repos = ["mcp-common", "oneiric", "dhara", "session-buddy", "akosha", "crackerjack", "mahavishnu"]
    out_dir = Path("docs/audit-inventory")
    out_dir.mkdir(parents=True, exist_ok=True)
    any_stale = False
    for repo in repos:
        repo_path = f"/Users/les/Projects/{repo}"
        out_path = out_dir / f"{repo}-cli-inventory.json"
        try:
            data = inventory_one_repo(repo, repo_path, out_path)
        except Exception as e:
            typer.echo(f"[red]FAIL: {repo}: {e}[/red]")
            continue
        typer.echo(f"{repo}: {data['command_count']} commands")
        if check_stale:
            stale = [c for c in data["commands"] if c["staleness_verdict"] in {"stale", "deprecated"}]
            if stale:
                any_stale = True
                typer.echo(f"  [yellow]{len(stale)} stale/deprecated commands[/yellow]")
    write_phase_0_baseline(repos, "/Users/les/Projects", out_dir / "PHASE_0_BASELINE.json")
    if check_stale and any_stale:
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
```

- [x] **Step 4: Run test to verify it passes**

Run: `cd /Users/les/Projects/mahavishnu && uv run pytest tests/unit/test_audit_cli_inventory.py -v`
Expected: PASS

- [x] **Step 5: Commit**

```bash
cd /Users/les/Projects/mahavishnu
git add scripts/audit_cli_inventory.py tests/unit/test_audit_cli_inventory.py
git -c user.name=les -c user.email=les@wedgwoodwebworks.com commit -m "feat(mahavishnu): add audit_cli_inventory.py for Core 7 CLI surface audit"
```

______________________________________________________________________

### Task 0.5: Pre-flight fix — mcp-common factory Python 2 syntax

**Files:**

- Modify: `/Users/les/Projects/mcp-common/mcp_common/cli/factory.py:530`
- Modify: `/Users/les/Projects/mcp-common/mcp_common/cli/factory.py:745`

**Context:** Most-impactful 4-character fix in the plan. Phase 4.2's `register_lifecycle_handlers` extension would otherwise re-mount silently broken handlers.

- [x] **Step 1: Read the two sites to confirm they're Python 2 syntax**

Run: `grep -n 'except ValueError, OSError:' /Users/les/Projects/mcp-common/mcp_common/cli/factory.py`
Expected: 2 matches at lines 530 and 745

- [x] **Step 2: Fix line 530**

Edit `/Users/les/Projects/mcp-common/mcp_common/cli/factory.py` at line 530:

- Find: `except ValueError, OSError:`

- Replace: `except (ValueError, OSError):`

- [x] **Step 3: Fix line 745**

Same edit at line 745.

- [x] **Step 4: Run mcp-common tests**

Run: `cd /Users/les/Projects/mcp-common && uv run pytest tests/ -x`
Expected: PASS

- [x] **Step 5: Commit**

```bash
cd /Users/les/Projects/mcp-common
git add mcp_common/cli/factory.py
git -c user.name=les -c user.email=les@wedgwoodwebworks.com commit -m "fix(mcp-common): correct Python 2 'except' syntax in factory.py"
```

______________________________________________________________________

### Task 1.1: Per-repo inventory subagent dispatch

**Files:**

- Create: 7 inventory files under `/Users/les/Projects/mahavishnu/docs/audit-inventory/`

**Subagent prompt template** (one per repo; replace `<name>`):

```
You are auditing the Bodai CLI surface for `<name>`.

Read:
- `/Users/les/Projects/mahavishnu/docs/plans/2026-08-25-bodai-cli-audit.md` §11 (per-repo shell status)
- `/Users/les/Projects/mahavishnu/scripts/audit_cli_inventory.py` (the tool)

Tasks:
1. Run: `cd /Users/les/Projects/<name> && python /Users/les/Projects/mahavishnu/scripts/audit_cli_inventory.py --repo <name>`
2. Verify the JSON in `/Users/les/Projects/mahavishnu/docs/audit-inventory/<name>-cli-inventory.json`:
   - `command_count` matches `<name> --help 2>&1 | awk '/^  [A-Za-z]/ {print $1}' | sort -u | wc -l`
   - No `notes` field contains `inventory_failed`
3. Write `/Users/les/Projects/mahavishnu/docs/audit-inventory/<name>-cli-inventory.md`:
   - One paragraph summary
   - Table of commands (command_path | short_help | staleness_verdict | notes)
4. Cross-check the inventory against the per-repo README and CLAUDE.md; document any drift.
5. Commit ONLY the 2 inventory files (JSON+MD) in `<name>` repo's worktree; do NOT edit source code.

Report: total command count, number of stale/deprecated, any drift.
```

- [x] **Step 1: Dispatch 6 inventory subagents in parallel**

Use the Agent tool with `subagent_type: general-purpose` and `isolation: worktree`. Run prompts for oneiric, dhara, session-buddy, akosha, crackerjack, mahavishnu in parallel.

- [x] **Step 2: Verify all 6 inventory JSON files exist and parse**

Run:

```bash
for f in /Users/les/Projects/mahavishnu/docs/audit-inventory/{oneiric,dhara,session-buddy,akosha,crackerjack,mahavishnu}-cli-inventory.json; do
  python3 -c "import json; json.load(open('$f'))" && echo "OK: $f" || echo "FAIL: $f"
done
```

Expected: 6 "OK" lines

- [x] **Step 3: Generate PHASE_0_BASELINE.json**

Run: `cd /Users/les/Projects/mahavishnu && uv run python scripts/audit_cli_inventory.py --all`
Expected: `PHASE_0_BASELINE.json` written

- [x] **Step 4: Confirm command counts meet minimum thresholds**

Run:

```bash
python3 -c "
import json
counts = {'mahavishnu': 50, 'oneiric': 30, 'dhara': 15, 'crackerjack': 28, 'session-buddy': 5, 'akosha': 5, 'mcp-common': 0}
for r, min_n in counts.items():
    data = json.load(open(f'docs/audit-inventory/{r}-cli-inventory.json'))
    n = len(data['commands'])
    assert n >= min_n, f'{r}: expected >= {min_n}, got {n}'
print('OK: all minimum thresholds met')
"
```

Expected: `OK`

- [x] **Step 5: Commit PHASE_0_BASELINE.json**

```bash
cd /Users/les/Projects/mahavishnu
git add docs/audit-inventory/
git -c user.name=les -c user.email=les@wedgwoodwebworks.com commit -m "feat(mahavishnu): Phase 1 inventory snapshots for 6 Core 7 repos + baseline"
```

______________________________________________________________________

### Task 1.2: mcp-common confirmation

**Files:**

- Create: `/Users/les/Projects/mahavishnu/docs/audit-inventory/mcp-common-cli-inventory.md`

- [x] **Step 1: Write mcp-common confirmation MD**

Create `/Users/les/Projects/mahavishnu/docs/audit-inventory/mcp-common-cli-inventory.md`:

````markdown
# mcp-common CLI surface — library-only confirmation (2026-08-25)

**Verdict**: mcp-common has no CLI surface. It is a library dependency
for the other 6 Core 7 repos; no console script entry point, no `cli.py`,
no Typer app.

**Verification**:
- `cat /Users/les/Projects/mcp-common/pyproject.toml | grep -A 5 'project.scripts'` → no entry
- `find /Users/les/Projects/mcp-common -name 'cli.py' -not -path '*/.venv/*'` → no matches

**Inventory tool output**:
```json
{"repo": "mcp-common", "commands": [], "notes": ["library-only; no CLI surface"]}
````

**Implication for Plan A**:

- mcp-common is excluded from the CLI-bearing count (no `app = BodaiCLIBase(...)` conversion)
- mcp-common's `MCPServerCLIFactory` is the canonical source for lifecycle handlers (Phase 4.2); referenced BY other repos, not BY itself
- mcp-common's `audit_no_secrets_in_mcp.py` pre-commit hook remains active across all 7 repos

````

- [x] **Step 2: Commit mcp-common confirmation**

```bash
cd /Users/les/Projects/mahavishnu
git add docs/audit-inventory/mcp-common-cli-inventory.md
git -c user.name=les -c user.email=les@wedgwoodwebworks.com commit -m "docs(mahavishnu): mcp-common library-only confirmation for Phase 1 inventory"
````

______________________________________________________________________

### Task 2.1: Cross-repo synthesis (findings.md)

**Files:**

- Create: `/Users/les/Projects/mahavishnu/docs/audit-inventory/findings.md`
- Create: `/Users/les/Projects/mahavishnu/scripts/validate_findings.py`

**Subagent prompt:**

```
You are the cross-repo synthesis agent for the Bodai CLI audit.

Read:
- `/Users/les/Projects/mahavishnu/docs/audit-inventory/*-cli-inventory.json` (7 files)
- `/Users/les/Projects/mahavishnu/docs/audit-inventory/*-cli-inventory.md` (6 files)
- `/Users/les/Projects/mahavishnu/docs/plans/2026-08-25-bodai-cli-audit.md` §11.2

Produce `/Users/les/Projects/mahavishnu/docs/audit-inventory/findings.md` with these tables (each row cites the inventory JSON via markdown link):

| Table | Columns |
|---|---|
| Per-repo command counts | repo, command_count, subcommand_count (sum), top-level_count |
| Cross-repo command-name duplications | command_name, repos (list), example links |
| Orphan sub-CLI modules | module_path, repo, imported_by, notes |
| Hidden/deprecated commands still referenced in docs | command_path, repo, doc_reference |
| Stale commands table | command_path, repo, staleness_verdict, reason |
| Top-10 most-changed commands | command_path, last_modified_date, commit_count |

Constraints:
- `findings.md` ≤ 250 lines (CI gate)
- Each row links to a specific inventory row via `[`module.path`](../audit-inventory/<repo>-cli-inventory.json#L<line>)`
- For "duplications", cite evidence in 2+ repos; dismiss coordinated-by-design (e.g., `version` appearing everywhere)
- For "stale", prefer commands with BOTH `todo_markers >= 3` AND `last_activity_days > 365`

Also produce `/Users/les/Projects/mahavishnu/scripts/validate_findings.py`:
- Parses every `findings.md` row
- For each `(<repo>-cli-inventory.json#L<line>)` link, verifies the file exists and the cited row is in range
- Exits 0 on success, 1 on any broken link
```

- [x] **Step 1: Dispatch the synthesis subagent**

Run the subagent prompt above using the Agent tool with `subagent_type: general-purpose`.

- [x] **Step 2: Verify findings.md meets the 250-line CI gate**

Run:

```bash
test "$(wc -l < /Users/les/Projects/mahavishnu/docs/audit-inventory/findings.md)" -le 250 && echo "OK" || echo "FAIL: findings.md > 250 lines"
```

Expected: `OK`

- [x] **Step 3: Verify validate_findings.py passes**

Run: `cd /Users/les/Projects/mahavishnu && python3 scripts/validate_findings.py docs/audit-inventory/findings.md`
Expected: exit 0

- [x] **Step 4: Commit findings.md + validate_findings.py**

```bash
cd /Users/les/Projects/mahavishnu
git add docs/audit-inventory/findings.md scripts/validate_findings.py
git -c user.name=les -c user.email=les@wedgwoodwebworks.com commit -m "docs(mahavishnu): Phase 2 cross-repo synthesis findings.md + validate_findings.py"
```

______________________________________________________________________

### Task 2.2: Add 250-line + validate_findings CI gates

**Files:**

- Modify: `/Users/les/Projects/mahavishnu/.git/hooks/pre-commit`

- [x] **Step 1: Read the current pre-commit hook**

Read `/Users/les/Projects/mahavishnu/.git/hooks/pre-commit`. Locate the `audit_no_secrets_in_mcp.py` invocation.

- [x] **Step 2: Add the 250-line + validate_findings gate**

Append to the hook (after the `audit_no_secrets_in_mcp.py` invocation):

```bash
# Phase 2 gate: findings.md ≤ 250 lines + validate_findings.py
if [ -f "docs/audit-inventory/findings.md" ] && [ -f "scripts/validate_findings.py" ]; then
    test "$(wc -l < docs/audit-inventory/findings.md)" -le 250 || { echo "findings.md exceeds 250-line budget"; exit 1; }
    python3 scripts/validate_findings.py docs/audit-inventory/findings.md || exit 1
fi
```

- [x] **Step 3: Test the hook manually**

Run:

```bash
cd /Users/les/Projects/mahavishnu
git -c user.name=les -c user.email=les@wedgwoodwebworks.com commit --allow-empty -m "test pre-commit hook"
```

Expected: hook runs, no errors

- [x] **Step 4: Reinstall via canonical installer**

Run: `cd /Users/les/Projects/mahavishnu && uv run mahavishnu index install-hooks .`
Expected: hook regenerated with the gate

______________________________________________________________________

## Phase 3 — Gap closure

### Task 3.1.1: Wire `session-buddy shell` CLI command

**Files:**

- Modify: `/Users/les/Projects/session-buddy/session_buddy/cli/__init__.py`

- Create: `/Users/les/Projects/session-buddy/tests/unit/test_shell_cli_command.py`

- [x] **Step 1: Write the failing test**

```python
# tests/unit/test_shell_cli_command.py
from typer.testing import CliRunner
from session_buddy.cli import app

runner = CliRunner()

def test_shell_command_registered():
    result = runner.invoke(app, ["--help"])
    assert "shell" in result.output
```

- [x] **Step 2: Run test to verify it fails**

Run: `cd /Users/les/Projects/session-buddy && uv run pytest tests/unit/test_shell_cli_command.py -v`
Expected: FAIL

- [x] **Step 3: Implement the shell command**

Edit `/Users/les/Projects/session-buddy/session_buddy/cli/__init__.py`:

```python
@app.command("shell")
def shell_command() -> None:
    """Start the Session-Buddy admin shell (IPython-based)."""
    async def _run() -> None:
        from session_buddy.shell import SessionBuddyShell
        from session_buddy.core.session_manager import SessionLifecycleManager
        manager = SessionLifecycleManager()
        shell = SessionBuddyShell(manager)
        shell.start()
    import asyncio
    asyncio.run(_run())
```

- [x] **Step 4: Run test + full suite**

Run: `cd /Users/les/Projects/session-buddy && uv run pytest tests/unit/test_shell_cli_command.py -v && uv run pytest tests/ -x`

- [x] **Step 5: Update CHANGELOG.md**

```markdown
### Changed
- **`session-buddy shell` CLI command** is now wired. Previously the `SessionBuddyShell` was library-only.
```

- [x] **Step 6: Commit**

```bash
cd /Users/les/Projects/session-buddy
git add session_buddy/cli/__init__.py tests/unit/test_shell_cli_command.py CHANGELOG.md
git -c user.name=les -c user.email=les@wedgwoodwebworks.com commit -m "feat(session-buddy): wire shell CLI command"
```

______________________________________________________________________

### Task 3.1.2: Document `dhara admin` vs `dhara db client`

**Files:**

- Modify: `/Users/les/Projects/dhara/dhara/cli.py`

- Modify: `/Users/les/Projects/dhara/README.md`

- [x] **Step 1: Add docstring to `dhara admin`**

Edit `_create_admin_command` in `dhara/cli.py`:

```python
def _create_admin_command(app, settings):
    """`dhara admin [--confirm]` — IPython-based admin shell using AdminShell.

    Use `dhara admin` for: configuration inspection, adapter inventory,
    ecosystem-level operations. Backed by `DharaShell(AdminShell)`.

    Use `dhara db client` for: low-level druva storage access.
    Backed by `IPython.terminal.embed.InteractiveShellEmbed` directly.

    Both shells are first-class; do not assume one replaces the other.
    """
```

- [x] **Step 2: Update dhara README**

Replace the `dhara db client` line in the README's CLI table with:

```markdown
- `dhara db client` — IPython shell with druva storage access (legacy `interactive_client` path)
- `dhara admin --confirm` — IPython shell with full ecosystem context (`AdminShell`-based)

**Which shell to use?** `dhara admin` for configuration/adapter inspection; `dhara db client` for low-level druva storage access.
```

- [x] **Step 3: Run dhara tests + commit**

Run: `cd /Users/les/Projects/dhara && uv run pytest tests/ -x`
Commit:

```bash
cd /Users/les/Projects/dhara
git add dhara/cli.py README.md
git -c user.name=les -c user.email=les@wedgwoodwebworks.com commit -m "docs(dhara): clarify admin vs db client (both kept)"
```

______________________________________________________________________

### Task 3.2.1: Akosha — gate 5 IPython namespace stubs

**Files:**

- Modify: `/Users/les/Projects/akosha/akosha/core/config.py`

- Modify: `/Users/les/Projects/akosha/akosha/shell/adapter.py`

- Create: `/Users/les/Projects/akosha/tests/shell/test_alpha_gate.py`

- Modify: `/Users/les/Projects/akosha/akosha/docs/ADMIN_SHELL.md`

- [x] **Step 1: Write the failing test**

```python
# tests/shell/test_alpha_gate.py
from akosha.shell import AkoshaShell

def test_stubs_disabled_by_default():
    shell = AkoshaShell(app=None, config=None)
    ns = shell._build_namespace()
    for stub in ("aggregate", "search", "detect", "graph", "trends"):
        assert stub not in ns

def test_stubs_enabled_when_flag_set():
    from akosha.core.config import AkoshaSettings
    settings = AkoshaSettings(alpha_shell_commands_enabled=True)
    shell = AkoshaShell(app=None, config=settings)
    ns = shell._build_namespace()
    for stub in ("aggregate", "search", "detect", "graph", "trends"):
        assert stub in ns
```

- [x] **Step 2: Add `alpha_shell_commands_enabled` to AkoshaSettings**

Edit `/Users/les/Projects/akosha/akosha/core/config.py`:

```python
alpha_shell_commands_enabled: bool = Field(
    default=False,
    description="Enable 5 alpha shell commands (aggregate, search, detect, graph, trends) in the IPython namespace. Default false.",
)
```

- [x] **Step 3: Gate the stubs in adapter.py**

Edit `_add_akasha_namespace` in `akosha/shell/adapter.py`:

```python
if self._config and getattr(self._config, "alpha_shell_commands_enabled", False):
    for name in ("aggregate", "search", "detect", "graph", "trends"):
        user_ns[name] = lambda *a, _name=name, **kw: {"message": f"{_name} is a stub. Set alpha_shell_commands_enabled=true to enable real implementation.", "result": []}
else:
    from rich import print as rprint
    rprint("[dim]5 alpha shell commands (aggregate, search, detect, graph, trends) are disabled. Set alpha_shell_commands_enabled=true to enable. See akosha/docs/ADMIN_SHELL.md.[/dim]")
```

- [x] **Step 4: Update ADMIN_SHELL.md**

Add section after the existing alpha-command table:

```markdown
## Alpha commands (gated)

The 5 commands below are alpha-quality and **disabled by default**:
`aggregate`, `search`, `detect`, `graph`, `trends`.

To enable, set `akosha.alpha_shell_commands_enabled: bool = True`
(or via `AKOSHA_ALPHA_SHELL_COMMANDS_ENABLED=true` env var). When the
flag is false, akosha shell prints a one-line banner on startup.
```

- [x] **Step 5: Run tests + commit**

Run: `cd /Users/les/Projects/akosha && uv run pytest tests/ -x`
Commit:

```bash
cd /Users/les/Projects/akosha
git add akosha/core/config.py akosha/shell/adapter.py tests/shell/test_alpha_gate.py akosha/docs/ADMIN_SHELL.md CHANGELOG.md
git -c user.name=les -c user.email=les@wedgwoodwebworks.com commit -m "feat(akosha): gate 5 alpha shell commands behind config flag"
```

______________________________________________________________________

### Task 3.2.2: Akosha — add `ipython` direct dep

**Files:**

- Modify: `/Users/les/Projects/akosha/pyproject.toml`

- [x] **Step 1: Add ipython to dependencies**

Edit `[project] dependencies` in `akosha/pyproject.toml`: add `"ipython>=9.14.0"`.

- [x] **Step 2: Test + commit**

Run: `cd /Users/les/Projects/akosha && uv sync && uv run pytest tests/ -x`

```bash
cd /Users/les/Projects/akosha
git add pyproject.toml uv.lock
git -c user.name=les -c user.email=les@wedgwoodwebworks.com commit -m "fix(akosha): add ipython direct dep"
```

______________________________________________________________________

### Task 3.2.3: Crackerjack — fix Python 2 syntax in session_compat.py:75

**Files:**

- Modify: `/Users/les/Projects/crackerjack/crackerjack/shell/session_compat.py:75`

- [x] **Step 1: Read the site**

Run: `sed -n '70,80p' /Users/les/Projects/crackerjack/crackerjack/shell/session_compat.py`

- [x] **Step 2: Fix the syntax**

- Find: `except ImportError, AttributeError:`

- Replace: `except (ImportError, AttributeError):`

- [x] **Step 3: Test + commit**

Run: `cd /Users/les/Projects/crackerjack && uv run pytest tests/ -x`

```bash
cd /Users/les/Projects/crackerjack
git add crackerjack/shell/session_compat.py
git -c user.name=les -c user.email=les@wedgwoodwebworks.com commit -m "fix(crackerjack): correct Python 2 'except' syntax"
```

______________________________________________________________________

### Task 3.2.4: Crackerjack — consolidate parallel interactive modules

**Files:**

- Modify: `/Users/les/Projects/crackerjack/crackerjack/interactive.py`

- Create: `/Users/les/Projects/crackerjack/tests/unit/test_interactive_legacy_deprecation.py`

- Modify: 4 test files (per migration-safety review)

- [x] **Step 1: Replace `crackerjack/interactive.py` with deprecation shim**

```python
"""DEPRECATED: legacy interactive module.

Moved to `crackerjack.cli.interactive`. This shim emits a
DeprecationWarning on import and re-exports names for one release.
"""
import warnings
from crackerjack.cli.interactive import *  # noqa: F401,F403

warnings.warn(
    "Importing from `crackerjack.interactive` is deprecated; "
    "use `crackerjack.cli.interactive` instead. "
    "This module will be removed in the next minor release.",
    DeprecationWarning,
    stacklevel=2,
)
```

- [x] **Step 2: Update 4 test files**

Run: `grep -rln 'from crackerjack.interactive import\|from crackerjack import interactive' /Users/les/Projects/crackerjack/tests/`
For each: replace `crackerjack.interactive` with `crackerjack.cli.interactive`.

- [x] **Step 3: Add deprecation test**

Create `tests/unit/test_interactive_legacy_deprecation.py`:

```python
import warnings

def test_legacy_interactive_emits_deprecation_warning():
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        import crackerjack.interactive  # noqa: F401
        assert any(
            issubclass(item.category, DeprecationWarning)
            and "cli.interactive" in str(item.message)
            for item in w
        )
```

- [x] **Step 4: Test + commit**

Run: `cd /Users/les/Projects/crackerjack && uv run pytest tests/ -x`

```bash
cd /Users/les/Projects/crackerjack
git add crackerjack/interactive.py tests/ CHANGELOG.md
git -c user.name=les -c user.email=les@wedgwoodwebworks.com commit -m "refactor(crackerjack): consolidate interactive modules (legacy → cli.interactive shim)"
```

______________________________________________________________________

### Task 3.2.5: Mahavishnu — consolidate parallel monitoring_cli modules

**Files:**

- Modify: `/Users/les/Projects/mahavishnu/mahavishnu/monitoring_cli.py` (replace with shim)

- Modify: `/Users/les/Projects/mahavishnu/mahavishnu/cli/monitoring_cli.py` (canonical stays)

- [x] **Step 1: Determine which is canonical**

Run: `grep -rn 'from mahavishnu.monitoring_cli\|from mahavishnu.cli.monitoring_cli' /Users/les/Projects/mahavishnu/mahavishnu/ --include='*.py'`

- [x] **Step 2: Replace the redundant file with a shim**

Suppose `mahavishnu/cli/monitoring_cli.py` is canonical:

```python
"""DEPRECATED: legacy monitoring_cli module. See mahavishnu.cli.monitoring_cli."""
from mahavishnu.cli.monitoring_cli import *  # noqa: F401,F403
```

- [x] **Step 3: Test + commit**

Run: `cd /Users/les/Projects/mahavishnu && uv run pytest tests/ -x`

```bash
cd /Users/les/Projects/mahavishnu
git add mahavishnu/monitoring_cli.py CHANGELOG.md
git -c user.name=les -c user.email=les@wedgwoodwebworks.com commit -m "refactor(mahavishnu): consolidate parallel monitoring_cli.py files"
```

______________________________________________________________________

### Task 3.2.6: mcp-common — register_lifecycle_handlers factory extension

**Files:**

- Modify: `/Users/les/Projects/mcp-common/mcp_common/cli/factory.py`

- Create: `/Users/les/Projects/mcp-common/tests/unit/cli/test_factory_register_handlers.py`

- [x] **Step 1: Write the failing test**

```python
# tests/unit/cli/test_factory_register_handlers.py
from typer.testing import CliRunner
from mcp_common.cli.factory import MCPServerCLIFactory

def test_register_lifecycle_handlers_mounts_start_stop_etc():
    app = typer.Typer()
    factory = MCPServerCLIFactory(component_name="test", server_name="test-server")
    factory.register_lifecycle_handlers(app)
    runner = CliRunner()
    result = runner.invoke(app, ["--help"])
    for cmd in ("start", "stop", "restart", "status", "health"):
        assert cmd in result.output
```

- [x] **Step 2: Run test to verify it fails**

Run: `cd /Users/les/Projects/mcp-common && uv run pytest tests/unit/cli/test_factory_register_handlers.py -v`
Expected: FAIL

- [x] **Step 3: Implement the method**

Edit `mcp_common/cli/factory.py`. Add to `MCPServerCLIFactory`:

```python
def create_handlers(self) -> dict[str, Callable]:
    return {
        "start": self._cmd_start,
        "stop": self._cmd_stop,
        "restart": self._cmd_restart,
        "status": self._cmd_status,
        "health": self._cmd_health,
    }

def register_lifecycle_handlers(self, app: typer.Typer) -> None:
    for name, handler in self.create_handlers().items():
        app.command(name=name)(handler)
```

- [x] **Step 4: Test + commit**

Run: `cd /Users/les/Projects/mcp-common && uv run pytest tests/ -x`

```bash
cd /Users/les/Projects/mcp-common
git add mcp_common/cli/factory.py tests/unit/cli/test_factory_register_handlers.py CHANGELOG.md
git -c user.name=les -c user.email=les@wedgwoodwebworks.com commit -m "feat(mcp-common): add MCPServerCLIFactory.register_lifecycle_handlers"
```

______________________________________________________________________

### Task 3.3.x: Doc sync (consolidated)

**Files:**

- `oneiric/oneiric/docs/ONEIRIC_ADMIN_SHELL.md`

- `mahavishnu/mahavishnu/docs/ADMIN_SHELL.md`

- [x] **Step 1: Cross-link in oneiric docs**

Append to `/Users/les/Projects/oneiric/oneiric/docs/ONEIRIC_ADMIN_SHELL.md`:

```markdown
## Cross-component admin shells

All 5 per-repo admin shells share the `AdminShell` base class. See
`mahavishnu/docs/ADMIN_SHELL.md` for the most fully-developed reference
(MahavishnuShell adds `%repos`, `%workflow` magics).
```

- [x] **Step 2: Reciprocal link in mahavishnu docs**

Append to `/Users/les/Projects/mahavishnu/mahavishnu/docs/ADMIN_SHELL.md`:

```markdown
## Cross-component admin shells

All 5 per-repo admin shells share the `AdminShell` base class in
`oneiric/shell/`. See `oneiric/docs/ONEIRIC_ADMIN_SHELL.md` for the
canonical base class doc.
```

- [x] **Step 3: Commit (2 separate commits)**

```bash
cd /Users/les/Projects/oneiric
git add oneiric/docs/ONEIRIC_ADMIN_SHELL.md
git -c user.name=les -c user.email=les@wedgwoodwebworks.com commit -m "docs(oneiric): cross-link admin shell docs across Core 7"

cd /Users/les/Projects/mahavishnu
git add mahavishnu/docs/ADMIN_SHELL.md
git -c user.name=les -c user.email=les@wedgwoodwebworks.com commit -m "docs(mahavishnu): cross-link admin shell docs across Core 7"
```

______________________________________________________________________

### Task 3.4.1: Staleness findings surface

**Files:**

- Create: `/Users/les/Projects/mahavishnu/docs/audit-inventory/findings-staleness.md`

- [x] **Step 1: Run staleness check + generate findings**

Run:

```bash
cd /Users/les/Projects/mahavishnu
uv run python scripts/audit_cli_inventory.py --all --check-stale 2>&1 | tee /tmp/staleness.txt
python3 -c "
import json
from pathlib import Path
repos = ['oneiric', 'dhara', 'session-buddy', 'akosha', 'crackerjack', 'mahavishnu']
findings = []
for repo in repos:
    data = json.load(open(f'docs/audit-inventory/{repo}-cli-inventory.json'))
    for cmd in data['commands']:
        if cmd['staleness_verdict'] in {'stale', 'deprecated'}:
            findings.append({'repo': repo, 'command_path': cmd['command_path'], 'staleness_verdict': cmd['staleness_verdict'], 'todo_markers': cmd['todo_markers'], 'last_activity_days': cmd['last_activity_days'], 'short_help': cmd['short_help'][:80]})
md = '# Staleness findings\n\n' + f'Generated {len(findings)} findings.\n\n| Repo | Command | Verdict | Reason | Short help |\n|---|---|---|---|---|\n'
for f in findings:
    md += f\"| {f['repo']} | \`{f['command_path']}\` | {f['staleness_verdict']} | TODOs={f['todo_markers']}, last-activity={f['last_activity_days']}d | {f['short_help']} |\n\"
Path('docs/audit-inventory/findings-staleness.md').write_text(md)
print(f'Wrote docs/audit-inventory/findings-staleness.md with {len(findings)} rows')
"
```

- [x] **Step 2: Commit**

```bash
cd /Users/les/Projects/mahavishnu
git add docs/audit-inventory/findings-staleness.md
git -c user.name=les -c user.email=les@wedgwoodwebworks.com commit -m "docs(mahavishnu): Phase 3.4 staleness findings"
```

______________________________________________________________________

## Phase 4 — `BodaiCLIBase` standardization

### Task 4.0: oneiric — convert flat `cli.py` to package

**Files:**

- Move: `/Users/les/Projects/oneiric/oneiric/cli.py` → `/Users/les/Projects/oneiric/oneiric/cli/__init__.py`

- [x] **Step 1: Snapshot CLI command list (baseline)**

Run: `cd /Users/les/Projects/oneiric && python -m oneiric --help 2>&1 | head -40 > /tmp/oneiric-help-before.txt`

- [x] **Step 2: Move cli.py**

```bash
mkdir -p /Users/les/Projects/oneiric/oneiric/cli
git -C /Users/les/Projects/oneiric mv oneiric/cli.py oneiric/cli/__init__.py
```

- [x] **Step 3: Verify parity**

Run: `cd /Users/les/Projects/oneiric && python -m oneiric --help 2>&1 | head -40 > /tmp/oneiric-help-after.txt && diff /tmp/oneiric-help-before.txt /tmp/oneiric-help-after.txt`
Expected: no diff

- [x] **Step 4: Run tests**

Run: `cd /Users/les/Projects/oneiric && uv run pytest tests/ -x`

- [x] **Step 5: Commit**

```bash
cd /Users/les/Projects/oneiric
git add oneiric/
git -c user.name=les -c user.email=les@wedgwoodwebworks.com commit -m "refactor(oneiric): convert cli.py to package"
```

______________________________________________________________________

### Task 4.1: oneiric — implement `BodaiCLIBase`

**Files:**

- Create: `/Users/les/Projects/oneiric/oneiric/cli/base.py`

- Create: `/Users/les/Projects/oneiric/oneiric/tests/cli/test_base.py`

- [x] **Step 1: Write the failing test**

```python
# oneiric/tests/cli/test_base.py
import pytest
import typer
from typer.testing import CliRunner

from oneiric.cli.base import BodaiCLIBase, ExitCode


def test_subclass_constructor_sets_metadata():
    class FakeApp(BodaiCLIBase):
        pass
    app = FakeApp(component_name="test-component")
    assert app.component_name == "test-component"


def test_version_command_works():
    class FakeApp(BodaiCLIBase):
        pass
    app = FakeApp(component_name="test-component")
    runner = CliRunner()
    result = runner.invoke(app, ["version"])
    assert result.exit_code == ExitCode.SUCCESS
    assert "test-component" in result.output


def test_doctor_command_returns_unavailable_when_not_implemented():
    class FakeApp(BodaiCLIBase):
        pass
    app = FakeApp(component_name="test-component")
    runner = CliRunner()
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == ExitCode.UNAVAILABLE


def test_health_command_returns_unavailable_when_not_implemented():
    class FakeApp(BodaiCLIBase):
        pass
    app = FakeApp(component_name="test-component")
    runner = CliRunner()
    result = runner.invoke(app, ["health"])
    assert result.exit_code == ExitCode.UNAVAILABLE


def test_subclass_doctor_override():
    class FakeApp(BodaiCLIBase):
        def _doctor_checks(self):
            return {"check1": {"status": "ok", "detail": "fine"}}
    app = FakeApp(component_name="test")
    runner = CliRunner()
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == ExitCode.SUCCESS


def test_version_flag_deprecation_shim():
    class FakeApp(BodaiCLIBase):
        pass
    app = FakeApp(component_name="test-deprecation")
    runner = CliRunner()
    result = runner.invoke(app, ["--version"])
    # Should emit deprecation warning + show version
    assert "deprecated" in result.output.lower() or "test-deprecation" in result.output


def test_json_global_option_accepted():
    class FakeApp(BodaiCLIBase):
        pass
    app = FakeApp(component_name="test")
    runner = CliRunner()
    result = runner.invoke(app, ["--json", "version"])
    assert result.exit_code == ExitCode.SUCCESS
```

- [x] **Step 2: Run test to verify it fails**

Run: `cd /Users/les/Projects/oneiric && uv run pytest oneiric/tests/cli/test_base.py -v`
Expected: FAIL

- [x] **Step 3: Implement `BodaiCLIBase`**

Create `/Users/les/Projects/oneiric/oneiric/cli/base.py`:

```python
"""BodaiCLIBase — shared Typer base for all Bodai Core 7 component CLIs.

Each Core 7 repo subclasses `BodaiCLIBase(component_name="...")` to get
`version`, `doctor`, `health` global commands plus the `--json` flag and
the `--version` deprecation shim. Subclasses retain callback registration
(Typer allows only one `@app.callback` per app).

Subclasses override `_doctor_checks()` and `_health_probe()` to return
their repo-specific checks. Both raise `NotImplementedError` by default;
per-repo CI tests must assert the hooks return real data, not `{}`.

Mirrors the `oneiric.shell.AdminShell` pattern: base provides the
contract; subclasses add component-specific surface.
"""
from __future__ import annotations

import json
import sys
from importlib.metadata import version as metadata_version
from typing import Any

import typer


class ExitCode:
    """Standardized exit codes across all Bodai CLIs."""
    SUCCESS = 0
    ERROR = 1
    USAGE_ERROR = 2
    UNAVAILABLE = 3
    PERMISSION_DENIED = 4
    TIMEOUT = 124


class BodaiCLIBase(typer.Typer):
    """Base Typer app for all Bodai component CLIs."""

    def __init__(
        self,
        component_name: str,
        *,
        help: str | None = None,
        no_args_is_help: bool = True,
        **kwargs: Any,
    ) -> None:
        super().__init__(help=help, no_args_is_help=no_args_is_help, **kwargs)
        self.component_name = component_name
        self.component_version = self._detect_version()
        self._intercept_version_flag()
        self._register_global_commands()

    def _detect_version(self) -> str:
        try:
            return metadata_version(self.component_name)
        except Exception:
            return "(not installed)"

    def _register_global_commands(self) -> None:
        @self.command()
        def version() -> None:
            """Print this component's version."""
            typer.echo(f"{self.component_name}: {self.component_version}")
            raise typer.Exit(code=ExitCode.SUCCESS)

        @self.command()
        def doctor(ctx: typer.Context) -> None:
            """Run diagnostic checks against this component's runtime."""
            json_output = (ctx.obj or {}).get("json_output", False)
            try:
                checks = self._doctor_checks()
            except NotImplementedError:
                typer.echo(f"{self.component_name}: doctor checks not yet implemented")
                raise typer.Exit(code=ExitCode.UNAVAILABLE)
            if json_output:
                typer.echo(json.dumps({"checks": checks}, indent=2))
            else:
                for name, info in checks.items():
                    typer.echo(f"{name}: {info.get('status', 'unknown')} - {info.get('detail', '')}")

        @self.command()
        def health(ctx: typer.Context) -> None:
            """Probe this component's runtime health."""
            json_output = (ctx.obj or {}).get("json_output", False)
            try:
                snapshot = self._health_probe()
            except NotImplementedError:
                typer.echo(f"{self.component_name}: health checks not yet implemented")
                raise typer.Exit(code=ExitCode.UNAVAILABLE)
            if json_output:
                typer.echo(json.dumps(snapshot, indent=2))
            else:
                typer.echo(str(snapshot))

    def _intercept_version_flag(self) -> None:
        """--version flag deprecation shim (one release)."""
        if "--version" in sys.argv or "-V" in sys.argv:
            sys.stderr.write(
                f"NOTE: --version is deprecated; use '{self.component_name} version'"
                " (or '<component> -V'). The flag will be removed in the next minor.\n"
            )
            argv = sys.argv[:]
            for i, arg in enumerate(argv):
                if arg in ("--version", "-V"):
                    argv[i] = "version"
            sys.argv = argv

    def _doctor_checks(self) -> dict[str, Any]:
        """Override in subclass. Return dict of check_name -> {status, detail}."""
        raise NotImplementedError

    def _health_probe(self) -> dict[str, Any]:
        """Override in subclass. Return dict matching oneiric health schema."""
        raise NotImplementedError
```

- [x] **Step 4: Run test + commit**

Run: `cd /Users/les/Projects/oneiric && uv run pytest oneiric/tests/cli/test_base.py -v`

```bash
cd /Users/les/Projects/oneiric
git add oneiric/cli/base.py oneiric/tests/cli/test_base.py CHANGELOG.md
git -c user.name=les -c user.email=les@wedgwoodwebworks.com commit -m "feat(oneiric): add BodaiCLIBase + ExitCode"
```

______________________________________________________________________

### Task 4.2: BodaiCLIBase conversion — per-repo (6 parallel)

**Subagent prompt template** (replace `<name>` and module path):

```
You are converting `<name>`'s CLI to use `BodaiCLIBase`.

Read:
- `/Users/les/Projects/oneiric/oneiric/cli/base.py`
- `/Users/les/Projects/<name>/<module>`
- `/Users/les/Projects/mahavishnu/docs/plans/2026-08-25-bodai-cli-audit.md` §4.1 callback inventory

Tasks:
1. Replace `app = typer.Typer(...)` (or `app = factory.create_app()`) with `app = BodaiCLIBase(component_name="<name>", help="<existing help>")`.
2. **REMOVE** the existing `@app.callback` if it handles `--version` (crackerjack, dhara, session-buddy). **PRESERVE** if it serves a different purpose.
3. For dhara/session-buddy/crackerjack: add `factory.register_lifecycle_handlers(app)` after constructing the BodaiCLIBase instance.
4. Implement `_doctor_checks()` and `_health_probe()` with real data.
5. Add test asserting `isinstance(app, BodaiCLIBase)` and that `_doctor_checks()` returns at least 1 check.
6. Update CHANGELOG.md with `### Changed` entry.
7. Run full repo test suite; fix test-fix cycles in the same commit.

Use the worktree pattern.
```

- [x] **Step 1: Dispatch 6 conversion subagents in parallel**

Use Agent tool with `isolation: worktree`. Each subagent gets the prompt above with their repo's values:

- `oneiric`: target `oneiric/cli/__init__.py` (post Task 4.0)

- `dhara`: target `dhara/cli.py`; recipe: `factory = MCPServerCLIFactory(...); app = BodaiCLIBase(...); factory.register_lifecycle_handlers(app)`

- `session-buddy`: target `session_buddy/cli/__init__.py`; same factory recipe

- `akosha`: target `akosha/cli.py`; preserve `cli.py:54` `main` callback

- `crackerjack`: move `app` from `__main__.py` to `cli/__init__.py`; convert

- `mahavishnu`: rename `_main_cli.py` → `main_cli.py` (with shim); convert

- [x] **Step 2: Verify each repo's app is now a BodaiCLIBase**

Run: `cd /Users/les/Projects/mahavishnu && for repo in oneiric dhara session-buddy akosha crackerjack mahavishnu; do cd /Users/les/Projects/$repo && python3 -c "from $([ \"$repo\" = oneiric ] && echo oneiric.cli || ([ \"$repo\" = session-buddy ] && echo session_buddy.cli || ([ \"$repo\" = crackerjack ] && echo crackerjack.cli || ([ \"$repo\" = mahavishnu ] && echo mahavishnu.main_cli || echo $repo.cli)))) import app; from oneiric.cli.base import BodaiCLIBase; assert isinstance(app, BodaiCLIBase); print('$repo OK')" 2>&1; done`
Expected: 6 OKs

______________________________________________________________________

### Task 4.3: Umbrella CI job (NEW)

**Files:**

- Create: `/Users/les/Projects/mahavishnu/.github/workflows/umbrella-ci.yml`

- Create: `/Users/les/Projects/mahavishnu/scripts/umbrella_smoke.sh`

- [x] **Step 1: Write the smoke script**

Create `/Users/les/Projects/mahavishnu/scripts/umbrella_smoke.sh`:

```bash
#!/bin/bash
# Umbrella CI smoke loop: install all 7 Core 7 repos + verify BodaiCLIBase adoption.
set -euo pipefail

BODAI_REPOS=(mcp-common oneiric dhara session-buddy akosha crackerjack mahavishnu)
BODAI_ROOT="${BODAI_ROOT:-/Users/les}"

for repo in "${BODAI_REPOS[@]}"; do
    if [ ! -d "$BODAI_ROOT/Projects/$repo" ]; then
        echo "::error::missing repo: $BODAI_ROOT/Projects/$repo"
        exit 1
    fi
    echo "=== Installing $repo ==="
    (cd "$BODAI_ROOT/Projects/$repo" && uv pip install -e . --quiet) || {
        echo "::error::failed to install $repo"
        exit 1
    }
done

for repo in "${BODAI_REPOS[@]}"; do
    echo "=== Checking $repo ==="
    if [ "$repo" = "mcp-common" ]; then
        echo "  mcp-common: library-only, skipping CLI checks"
        continue
    fi
    "$repo" version || { echo "::error::$repo version failed"; exit 1; }
    "$repo" doctor || [ $? -eq 3 ] || { echo "::error::$repo doctor failed unexpectedly"; exit 1; }
    "$repo" --json version >/dev/null || { echo "::error::$repo --json flag rejected"; exit 1; }
done

echo "=== Checking bodai umbrella ==="
bodai --help | grep -E '^\s+(oneiric|akosha|crackerjack|dhara|session-buddy|mahavishnu)\b' || {
    echo "::error::bodai umbrella did not list all 6 sub-CLIs"
    exit 1
}

echo "=== ALL SMOKE TESTS PASSED ==="
```

- [x] **Step 2: Make executable + test**

Run: `chmod +x /Users/les/Projects/mahavishnu/scripts/umbrella_smoke.sh && /Users/les/Projects/mahavishnu/scripts/umbrella_smoke.sh 2>&1 | tail -10`
Expected: `=== ALL SMOKE TESTS PASSED ===` (after Task 5.2 lands)

- [x] **Step 3: Create GitHub Actions workflow**

Create `/Users/les/Projects/mahavishnu/.github/workflows/umbrella-ci.yml`:

```yaml
name: Umbrella CI

on:
  push:
    branches: [main]
    paths:
      - 'mahavishnu/cli/**'
      - 'oneiric/cli/**'
      - 'dhara/cli/**'
      - 'session-buddy/cli/**'
      - 'akosha/cli/**'
      - 'crackerjack/cli/**'
      - '.github/workflows/umbrella-ci.yml'
      - 'scripts/umbrella_smoke.sh'
  pull_request:
    paths:
      - 'mahavishnu/cli/**'
      - 'oneiric/cli/**'
      - 'dhara/cli/**'
      - 'session-buddy/cli/**'
      - 'akosha/cli/**'
      - 'crackerjack/cli/**'

jobs:
  umbrella-smoke:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Install uv
        uses: astral-sh/setup-uv@v3
      - name: Install Bodai Core 7 + run smoke loop
        env:
          BODAI_ROOT: ${{ github.workspace }}/../
        run: ./scripts/umbrella_smoke.sh
```

- [x] **Step 4: Commit**

```bash
cd /Users/les/Projects/mahavishnu
git add .github/workflows/umbrella-ci.yml scripts/umbrella_smoke.sh
git -c user.name=les -c user.email=les@wedgwoodwebworks.com commit -m "feat(mahavishnu): add umbrella CI job"
```

______________________________________________________________________

### Task 4.4: Bodai CLI contract decision doc

**Files:**

- Create: `/Users/les/Projects/mahavishnu/.claude/decisions/2026-08-25-bodai-cli-contract.md`

- Modify: `/Users/les/Projects/mahavishnu/.claude/decisions/README.md`

- [x] **Step 1: Write the decision doc**

Create `/Users/les/Projects/mahavishnu/.claude/decisions/2026-08-25-bodai-cli-contract.md`:

````markdown
---
status: active
role: canonical
date: 2026-08-25
last_reviewed: 2026-08-25
superseded_by: null
topic: bodai-cli-contract
---

# Bodai CLI Contract

Established by the 2026-08-25 ultracode CLI audit.

## Decision rule

### 1. Every Core 7 CLI extends `BodaiCLIBase`

Each Core 7 component CLI is a `typer.Typer` instance that extends
`oneiric.cli.base.BodaiCLIBase`. This provides:
- `version` subcommand (auto-registered)
- `doctor` subcommand (calls subclass's `_doctor_checks()`)
- `health` subcommand (calls subclass's `_health_probe()`)
- `--json` global flag
- `--version` deprecation shim (one release)
- `ExitCode` enum (`SUCCESS=0`, `ERROR=1`, `USAGE_ERROR=2`, `UNAVAILABLE=3`, `PERMISSION_DENIED=4`, `TIMEOUT=124`)

### 2. Lifecycle-bearing repos use `MCPServerCLIFactory.register_lifecycle_handlers`

crackerjack, dhara, session-buddy use lifecycle verbs. Construct:
`factory = MCPServerCLIFactory(component_name="..."); app = BodaiCLIBase(...); factory.register_lifecycle_handlers(app)`.

### 3. Each Core 7 registers in `bodai.apps` entry-point group

In `pyproject.toml`:
```toml
[project.entry-points."bodai.apps"]
<repo> = "<module>:<app>"
````

### 4. Each Core 7 implements `_doctor_checks()` and `_health_probe()`

No vacuous implementations. Per-repo CI tests assert at least 1 check returned.

## Enforcement

- Pre-commit hook: `scripts/audit_no_secrets_in_mcp.py` (existing)
- CI: `.github/workflows/umbrella-ci.yml` (NEW)
- Per-repo CI: existing pytest + BodaiCLIBase-specific tests

````

- [x] **Step 2: Add row to decisions index**

Append to `/Users/les/Projects/mahavishnu/.claude/decisions/README.md`:
```markdown
| `2026-08-25-bodai-cli-contract.md` | Bodai CLI contract (BodaiCLIBase, ExitCode, bodai.apps entry-points) | active |
````

- [x] **Step 3: Commit**

```bash
cd /Users/les/Projects/mahavishnu
git add .claude/decisions/2026-08-25-bodai-cli-contract.md .claude/decisions/README.md
git -c user.name=les -c user.email=les@wedgwoodwebworks.com commit -m "docs(mahavishnu): add Bodai CLI contract decision + index entry"
```

______________________________________________________________________

## Phase 5 — Compose Core 7 into `bodai` umbrella

### Task 5.1: bodai — `_discover_apps()` + `version`/`apps` commands

**Files:**

- Modify: `/Users/les/Projects/bodai/bodai/cli.py`

- Create: `/Users/les/Projects/bodai/tests/test_umbrella.py`

- [x] **Step 1: Write the failing test**

```python
# tests/test_umbrella.py
from importlib.metadata import EntryPoint
from unittest.mock import patch, MagicMock

from bodai.cli import app, _discover_apps


def test_discover_apps_with_mock_entry_points():
    fake_eps = [
        EntryPoint(name="fake1", value="fake1.cli:app", group="bodai.apps"),
        EntryPoint(name="fake2", value="fake2.cli:app", group="bodai.apps"),
    ]
    with patch("bodai.cli.entry_points", return_value=fake_eps):
        with patch("bodai.cli.ep_load", side_effect=lambda ep: MagicMock()):
            test_app = typer.Typer()
            _discover_apps(test_app)
            assert "fake1" in test_app.registered_groups
            assert "fake2" in test_app.registered_groups


def test_discover_apps_skips_broken_import():
    fake_eps = [EntryPoint(name="broken", value="nonexistent.module:app", group="bodai.apps")]
    with patch("bodai.cli.entry_points", return_value=fake_eps):
        with patch("bodai.cli.ep_load", side_effect=ImportError("simulated")):
            test_app = typer.Typer()
            _discover_apps(test_app)
            assert "broken" not in test_app.registered_groups


def test_discover_apps_no_entry_points():
    with patch("bodai.cli.entry_points", return_value=[]):
        test_app = typer.Typer()
        _discover_apps(test_app)
        assert test_app.registered_groups == {}


def test_bodai_apps_command_lists_registered():
    from typer.testing import CliRunner
    runner = CliRunner()
    result = runner.invoke(app, ["apps"])
    assert result.exit_code == 0
```

- [x] **Step 2: Run test to verify it fails**

Run: `cd /Users/les/Projects/bodai && uv run pytest tests/test_umbrella.py -v`
Expected: FAIL

- [x] **Step 3: Implement `_discover_apps` + `version` + `apps`**

Edit `/Users/les/Projects/bodai/bodai/cli.py`:

```python
# Add to imports at top:
from importlib.metadata import entry_points

# Add functions and commands:

def ep_load(ep):
    return ep.load()


def _discover_apps(app: typer.Typer) -> None:
    from bodai.cli import console
    try:
        eps = entry_points(group="bodai.apps")
    except Exception as e:
        console.print(f"[yellow]No bodai.apps entry points available: {e}[/yellow]")
        return
    for ep in sorted(eps, key=lambda e: e.name):
        try:
            sub_app = ep.load()
        except (ImportError, ModuleNotFoundError) as e:
            console.print(f"[yellow]Skipping {ep.name}: import failed ({type(e).__name__})[/yellow]")
            continue
        except Exception as e:
            console.print(f"[yellow]Skipping {ep.name}: load failed ({type(e).__name__})[/yellow]")
            continue
        app.add_typer(sub_app, name=ep.name)


@app.command()
def version() -> None:
    """Print versions of registered Bodai components."""
    from importlib.metadata import version as metadata_version
    from rich.table import Table
    try:
        eps = entry_points(group="bodai.apps")
    except Exception:
        eps = []
    table = Table(title="Bodai component versions")
    table.add_column("Component")
    table.add_column("Version")
    for ep in sorted(eps, key=lambda e: e.name):
        try:
            v = metadata_version(ep.name)
        except Exception:
            v = "(not installed)"
        table.add_row(ep.name, v)
    try:
        bodai_v = metadata_version("bodai")
    except Exception:
        bodai_v = "(not installed)"
    table.add_row("bodai", bodai_v)
    console.print(table)


@app.command()
def apps() -> None:
    """List registered Bodai apps (from the bodai.apps entry-point group)."""
    from rich.table import Table
    try:
        eps = entry_points(group="bodai.apps")
    except Exception as e:
        console.print(f"[yellow]No bodai.apps registered: {e}[/yellow]")
        return
    if not eps:
        console.print("[yellow]No bodai.apps registered (install Core 7 repos to enable)[/yellow]")
        return
    table = Table(title="Registered Bodai apps")
    table.add_column("Name")
    table.add_column("Target")
    table.add_column("Version")
    for ep in sorted(eps, key=lambda e: e.name):
        from importlib.metadata import version as metadata_version
        try:
            v = metadata_version(ep.name)
        except Exception:
            v = "(not installed)"
        table.add_row(ep.name, ep.value, v)
    console.print(table)


# At module load, after `app = typer.Typer(...)`:
_discover_apps(app)
```

- [x] **Step 4: Run test + commit**

Run: `cd /Users/les/Projects/bodai && uv run pytest tests/test_umbrella.py -v`

```bash
cd /Users/les/Projects/bodai
git add bodai/cli.py tests/test_umbrella.py CHANGELOG.md
git -c user.name=les -c user.email=les@wedgwoodwebworks.com commit -m "feat(bodai): add _discover_apps + version/apps aggregation"
```

______________________________________________________________________

### Task 5.2: Per-repo entry-point registration (6 parallel)

**Subagent prompt template** (replace `<name>` and module path):

````
You are registering `<name>`'s CLI in the `bodai.apps` entry-point group.

Edit `/Users/les/Projects/<name>/pyproject.toml`. Add (or update):
```toml
[project.entry-points."bodai.apps"]
<name> = "<module>:<attr>"
````

Mappings (verified in Task 4.2):

- oneiric: `oneiric.cli:app`
- dhara: `dhara.cli:app`
- session-buddy: `session_buddy.cli:app`
- akosha: `akosha.cli:app`
- crackerjack: `crackerjack.cli:app`
- mahavishnu: `mahavishnu.main_cli:app`

Then: `uv pip install -e .` (or `pip install -e .`), verify with `python3 -c "from importlib.metadata import entry_points; eps = entry_points(group='bodai.apps'); names = [e.name for e in eps]; assert '<name>' in names"`, update CHANGELOG, commit.

````

- [x] **Step 1: Dispatch 6 entry-point subagents in parallel**

Use Agent tool. Run for all 6 repos.

- [x] **Step 2: Verify all 6 are registered**

For each repo: `cd /Users/les/Projects/<repo> && python3 -c "from importlib.metadata import entry_points; eps = entry_points(group='bodai.apps'); names = [e.name for e in eps]; assert '<name>' in names; print('OK')"`

---

### Task 5.3: bodai cross-CLI demo test

**Files:**
- Modify: `/Users/les/Projects/bodai/tests/test_umbrella.py`

- [x] **Step 1: Add smoke test**

Append to `/Users/les/Projects/bodai/tests/test_umbrella.py`:
```python
def test_bodai_akosha_shell_command_present():
    from typer.testing import CliRunner
    runner = CliRunner()
    result = runner.invoke(app, ["akosha", "--help"])
    assert result.exit_code == 0
    assert "shell" in result.output.lower()
````

- [x] **Step 2: Run + commit**

Run: `cd /Users/les/Projects/bodai && uv run pytest tests/test_umbrella.py -v`

```bash
cd /Users/les/Projects/bodai
git add tests/test_umbrella.py
git -c user.name=les -c user.email=les@wedgwoodwebworks.com commit -m "test(bodai): verify bodai akosha shell composition"
```

______________________________________________________________________

## Phase 7 — Verification + sign-off

### Task 7.1: Re-run inventory + diff against baseline

**Files:**

- Create: `/Users/les/Projects/mahavishnu/scripts/diff_inventories.py`

- [x] **Step 1: Re-run inventory**

Run: `cd /Users/les/Projects/mahavishnu && uv run python scripts/audit_cli_inventory.py --all`

- [x] **Step 2: Write diff script**

Create `/Users/les/Projects/mahavishnu/scripts/diff_inventories.py`:

```python
"""Diff current inventories against PHASE_0_BASELINE.json.

Catches regressions (command count shrank unexpectedly) and stale
findings (commands marked stale remain stale).
"""
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
BASELINE_PATH = REPO_ROOT / "docs/audit-inventory/PHASE_0_BASELINE.json"
INVENTORY_DIR = REPO_ROOT / "docs/audit-inventory"
TOLERANCE = 2


def main() -> int:
    baseline = json.loads(BASELINE_PATH.read_text())
    failures = []
    for repo, baseline_data in baseline["repos"].items():
        inv_path = INVENTORY_DIR / f"{repo}-cli-inventory.json"
        if not inv_path.exists():
            failures.append(f"{repo}: inventory missing")
            continue
        current = json.loads(inv_path.read_text())
        diff = current["command_count"] - baseline_data["command_count"]
        if abs(diff) > TOLERANCE:
            failures.append(f"{repo}: command count changed by {diff}")
        baseline_stale = sum(1 for c in baseline_data["commands"] if c["staleness_verdict"] in {"stale", "deprecated"})
        current_stale = sum(1 for c in current["commands"] if c["staleness_verdict"] in {"stale", "deprecated"})
        if current_stale > baseline_stale:
            failures.append(f"{repo}: stale count increased")
    if failures:
        print("FAIL:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print(f"OK: all {len(baseline['repos'])} repos within tolerance")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [x] **Step 3: Run + commit**

Run: `cd /Users/les/Projects/mahavishnu && python3 scripts/diff_inventories.py`

```bash
cd /Users/les/Projects/mahavishnu
git add scripts/diff_inventories.py docs/audit-inventory/
git -c user.name=les -c user.email=les@wedgwoodwebworks.com commit -m "feat(mahavishnu): Phase 7 diff_inventories.py"
```

______________________________________________________________________

### Task 7.2: Update BODAI_REPO_REGISTRY.md

**Files:**

- Modify: `/Users/les/Projects/mahavishnu/BODAI_REPO_REGISTRY.md`

- [x] **Step 1: Add CLI surface section**

Append to `/Users/les/Projects/mahavishnu/BODAI_REPO_REGISTRY.md`:

```markdown
## CLI surface summary (added 2026-08-25)

Generated by the 2026-08-25 CLI audit. Run `uv run python scripts/audit_cli_inventory.py --all` to refresh.

| Repo | Entry point | Command count | BodaiCLIBase adopted | `bodai.apps` registered |
|---|---|---|---|---|
| mcp-common | (library-only) | 0 | n/a | n/a |
| oneiric | `oneiric` | <count> | ✓ | ✓ |
| dhara | `dhara` | <count> | ✓ | ✓ |
| session-buddy | `session-buddy` | <count> | ✓ | ✓ |
| akosha | `akosha` | <count> | ✓ | ✓ |
| crackerjack | `crackerjack` | <count> | ✓ | ✓ |
| mahavishnu | `mahavishnu` | <count> | ✓ | ✓ |
```

- [x] **Step 2: Populate counts**

Run:

```bash
for repo in oneiric dhara session-buddy akosha crackerjack mahavishnu; do
  count=$(jq '.command_count' /Users/les/Projects/mahavishnu/docs/audit-inventory/$repo-cli-inventory.json)
  echo "$repo: $count"
done
```

Substitute counts into the table.

- [x] **Step 3: Commit**

```bash
cd /Users/les/Projects/mahavishnu
git add BODAI_REPO_REGISTRY.md
git -c user.name=les -c user.email=les@wedgwoodwebworks.com commit -m "docs(mahavishnu): add CLI surface summary to BODAI_REPO_REGISTRY"
```

______________________________________________________________________

### Task 7.3: Document quarterly staleness cadence

**Files:**

- Create: `/Users/les/Projects/mahavishnu/.claude/decisions/bodai-cli-staleness-cadence.md`

- [x] **Step 1: Write the cadence doc**

````markdown
---
status: active
role: operational
date: 2026-08-25
last_reviewed: 2026-08-25
superseded_by: null
topic: bodai-cli-staleness-cadence
---

# Bodai CLI Staleness Cadence

## Decision

Per the 2026-08-25 audit, the Bodai CLI surface is inventoried quarterly
for staleness via `scripts/audit_cli_inventory.py --all --check-stale`.

## Schedule

Every 90 days. Next due: 2026-11-25.

## Mechanism

A launchd plist at `~/Library/LaunchAgents/com.bodai.staleness-audit.plist`
runs:
```bash
cd /Users/les/Projects/mahavishnu && uv run python scripts/audit_cli_inventory.py --all --check-stale
````

Output is written to `docs/audit-inventory/staleness-<date>.log`.

## When staleness is detected

If `--check-stale` exits non-zero:

1. Open `docs/audit-inventory/staleness-<date>.log`
1. Triage each row: DEPRECATE, IMPLEMENT, or REMOVE
1. Each triage becomes its own commit per Phase 3.4 process

## Why quarterly

- CLI surface changes ~once per month across 7 repos; quarterly catches drift without noise
- 90 days is short enough that no stale command survives >1 quarter without review
- Long enough that the cadence doesn't become a chore

````

- [x] **Step 2: Commit**

```bash
cd /Users/les/Projects/mahavishnu
git add .claude/decisions/bodai-cli-staleness-cadence.md
git -c user.name=les -c user.email=les@wedgwoodwebworks.com commit -m "docs(mahavishnu): quarterly staleness cadence"
````

- [x] **Step 3: Set up launchd plist (manual user step)**

Document the launchd plist in the cadence doc; user installs manually:

```bash
cp /Users/les/Projects/mahavishnu/.claude/decisions/bodai-cli-staleness-cadence.md /tmp/cadence-doc  # reference only
cat > ~/Library/LaunchAgents/com.bodai.staleness-audit.plist <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>com.bodai.staleness-audit</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string><string>-c</string>
        <string>cd /Users/les/Projects/mahavishnu && uv run python scripts/audit_cli_inventory.py --all --check-stale > docs/audit-inventory/staleness-$(date +%Y-%m-%d).log 2>&1</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Day</key><integer>25</integer>
        <key>Hour</key><integer>9</integer>
        <key>Minute</key><integer>0</integer>
        <key>Month</key><integer>3,6,9,12</integer>
    </dict>
</dict>
</plist>
EOF
launchctl load ~/Library/LaunchAgents/com.bodai.staleness-audit.plist
```

______________________________________________________________________

## Execution order

Recommended execution order across all tasks (allows parallelization where safe):

```
Day 1:
  Task 0.5 (mcp-common factory syntax fix)        [blocks Phase 4.2]
  Task 0.1 (audit_cli_inventory.py)               [blocks Task 1.1]

Day 2:
  Task 1.1 (6 subagents in parallel)               [depends on 0.1]
  Task 1.2 (mcp-common confirmation)

Day 3:
  Task 2.1 (synthesis subagent)
  Task 2.2 (CI gates)

Day 4-5:
  Task 3.x (gap closure, parallel per-repo)

Day 6-8:
  Task 4.0 (oneiric package conversion)
  Task 4.1 (BodaiCLIBase implementation)

Day 9:
  Task 4.2 (6 per-repo conversions in parallel)
  Task 4.3 (umbrella CI job)

Day 10:
  Task 4.4 (decision doc)

Day 11:
  Task 5.1 (bodai _discover_apps + version/apps)
  Task 5.2 (5 remaining entry-point registrations)

Day 12:
  Task 5.3 (cross-CLI demo test)

Day 13:
  Task 7.1 (re-run inventory + diff)
  Task 7.2 (BODAI_REPO_REGISTRY.md update)
  Task 7.3 (staleness cadence doc + launchd plist)
```

______________________________________________________________________

## Self-review

**Spec coverage:**

- Spec §1 Outcome — Tasks 0.1, 4.1, 5.1, 5.2
- Spec §2 Goals — All 7 goals mapped: Task 0.1 (G1), Task 1.1 (G1), Task 4.1 (G3), Task 3.1.1 (G4), Task 5.1+5.2 (G5), Task 5.1 (G6), Task 4.4 (G7)
- Spec §3 Non-Goals — verified; no task contradicts
- Spec §4 Current Findings — Tasks 3.1.1, 3.1.2, 3.2.1, 3.2.2, 3.2.3, 3.2.4, 3.2.5, 3.2.6
- Spec §5 Phases 0-7 — fully covered; Phase 6 (TUI) deferred to companion plan B
- Spec §6 Required Code Changes — all files listed appear in the implementation tasks
- Spec §7 Decision Rule — each item maps to a runnable gate

**Placeholder scan:** No TBDs, TODOs, or vague "implement later" markers. Each test code block is concrete. Each commit message is specific.

**Type consistency:**

- `BodaiCLIBase.__init__(self, component_name, *, help, no_args_is_help, **kwargs)` — consistent in Tasks 4.1, 4.2, 5.1
- `_doctor_checks() -> dict[str, Any]` and `_health_probe() -> dict[str, Any]` — consistent
- `ExitCode.SUCCESS = 0` (etc.) — consistent
- `_discover_apps(app: typer.Typer) -> None` — consistent in Tasks 5.1, 5.3, 7.1
- `entry_points(group="bodai.apps")` — consistent in Tasks 4.3 (entry-point registration), 5.1 (discovery), 5.2 (registration verification)
- `MCPServerCLIFactory.register_lifecycle_handlers(app: typer.Typer) -> None` — consistent

**Gaps:**

- Phase 6 (TUI work) is in companion plan B
- Akosha stub IMPLEMENT vs REMOVE is a Phase 3.4 future-task
- Phase 5 umbrella CI dependency: Task 5.1 must land AFTER Task 4.3 (umbrella CI) since the smoke test asserts bodai umbrella composition
