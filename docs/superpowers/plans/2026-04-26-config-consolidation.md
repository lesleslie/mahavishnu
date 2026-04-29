# Config Consolidation: Mahavishnu as Self-Contained Dev Environment — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move all Claude Code configuration (agents, skills, commands, workflows, hooks, MCP server definitions) from global `~/.claude/` into the Mahavishnu project directory, making it version-controlled, portable, and readable by both Claude Code and the Mahavishnu CLI.

**Architecture:** Native project config — Claude Code's `.claude/` and `.mcp.json` conventions used directly. A migration script handles the one-time copy, secret-stripping, and `~/.claude.json` cleanup. Existing `config_validator.py` gains drift-detection checks. No symlinks or sync mechanisms.

**Tech Stack:** Python stdlib (`pathlib`, `json`, `shutil`, `yaml`), Typer (existing in Mahavishnu CLI), pytest.

---

## File Structure

| File | Change |
|------|--------|
| `scripts/migrate_config_to_project.py` | **Create** — one-time migration script with `--dry-run`, `--backup`, `--rollback` |
| `mahavishnu/.claude/agents/` | **Populated** by migration script (102 `.md` files from `~/.claude/agents/`) |
| `mahavishnu/.claude/skills/` | **Populated** by migration script (22 native + 5 symlink-resolved skill dirs) |
| `mahavishnu/.claude/commands/` | **Populated** by migration script (10 commands + tools/ + workflows/) |
| `mahavishnu/.claude/hooks/mcp-hooks.json` | **Populated** by migration script |
| `mahavishnu/.claude/CLAUDE.md` | **Populated** by migration script (full 260-line ecosystem manifest) |
| `mahavishnu/.mcp.json` | **Create** by migration script (33 MCP servers, env blocks stripped) |
| `mahavishnu/.claude/settings.local.json` | **Modify** — remove `~/.claude` from `additionalDirectories` |
| `mahavishnu/.gitignore` | **Modify** — add rules for `.claude/hooks/scripts/`, `.claude/skills/*/.archive/` |
| `mahavishnu/cli/config_validator.py` | **Modify** — add CLI subcommands: `list-agents`, `list-skills`, `list-mcp-servers`, `sync-from-global`, `rollback` |
| `mahavishnu/core/config_validator.py` | **Modify** — add `check_skill_mcp_drift()` anti-drift function (wired into `validate_config()`) |
| `mahavishnu/tests/unit/test_migration_script.py` | **Create** — unit tests for migration logic |

---

## Task 1: Write the migration script

**Files:**
- Create: `scripts/migrate_config_to_project.py`
- Test: `tests/unit/test_migration_script.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_migration_script.py
import json
import shutil
from pathlib import Path

import pytest


@pytest.fixture
def fake_home(tmp_path):
    """Create a minimal fake ~/.claude structure for testing."""
    claude = tmp_path / ".claude"
    agents = claude / "agents"
    agents.mkdir(parents=True)
    (agents / "python-pro.md").write_text("---\nname: python-pro\n---\n")
    (agents / "code-reviewer.md").write_text("---\nname: code-reviewer\n---\n")

    skills = claude / "skills"
    skill_dir = skills / "manage-pools"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("# Manage Pools\n")

    commands = claude / "commands"
    commands.mkdir(parents=True)
    (commands / "start.md").write_text("# Start\n")

    hooks = claude / "hooks"
    hooks.mkdir(parents=True)
    (hooks / "mcp-hooks.json").write_text('{"hooks": []}')

    (claude / "CLAUDE.md").write_text("# Ecosystem manifest\n")

    # Fake ~/.claude.json with mcpServers + env blocks
    claude_json = tmp_path / ".claude.json"
    claude_json.write_text(json.dumps({
        "mcpServers": {
            "crackerjack": {
                "command": "uvx",
                "args": ["crackerjack-mcp"],
                "env": {"API_KEY": "secret-value"},
            },
            "akosha": {
                "url": "http://localhost:8682",
            },
        },
        "otherAppState": "preserved",
    }))

    return tmp_path


def test_dry_run_makes_no_changes(fake_home, tmp_path):
    """--dry-run should print operations but not touch any files."""
    dest = tmp_path / "mahavishnu"
    dest.mkdir()

    from scripts.migrate_config_to_project import MigrationRunner
    runner = MigrationRunner(
        source_claude=fake_home / ".claude",
        source_claude_json=fake_home / ".claude.json",
        dest_project=dest,
        dry_run=True,
    )
    runner.run()

    # Nothing should be created in dest
    assert not (dest / ".claude" / "agents").exists()
    assert not (dest / ".mcp.json").exists()


def test_full_migration_copies_agents(fake_home, tmp_path):
    dest = tmp_path / "mahavishnu"
    dest.mkdir()
    dest_claude = dest / ".claude"
    dest_claude.mkdir()
    (dest_claude / "settings.local.json").write_text(
        json.dumps({"additionalDirectories": [str(fake_home / ".claude"), "/other/path"]})
    )

    from scripts.migrate_config_to_project import MigrationRunner
    runner = MigrationRunner(
        source_claude=fake_home / ".claude",
        source_claude_json=fake_home / ".claude.json",
        dest_project=dest,
        dry_run=False,
        backup=False,
    )
    runner.run()

    assert (dest / ".claude" / "agents" / "python-pro.md").exists()
    assert (dest / ".claude" / "agents" / "code-reviewer.md").exists()


def test_env_blocks_stripped_from_mcp_json(fake_home, tmp_path):
    dest = tmp_path / "mahavishnu"
    dest.mkdir()
    (dest / ".claude").mkdir()
    (dest / ".claude" / "settings.local.json").write_text(
        json.dumps({"additionalDirectories": []})
    )

    from scripts.migrate_config_to_project import MigrationRunner
    runner = MigrationRunner(
        source_claude=fake_home / ".claude",
        source_claude_json=fake_home / ".claude.json",
        dest_project=dest,
        dry_run=False,
        backup=False,
    )
    runner.run()

    mcp_json = json.loads((dest / ".mcp.json").read_text())
    assert "env" not in mcp_json["mcpServers"]["crackerjack"]
    assert mcp_json["mcpServers"]["crackerjack"]["command"] == "uvx"


def test_other_app_state_preserved_in_claude_json(fake_home, tmp_path):
    dest = tmp_path / "mahavishnu"
    dest.mkdir()
    (dest / ".claude").mkdir()
    (dest / ".claude" / "settings.local.json").write_text(json.dumps({"additionalDirectories": []}))

    from scripts.migrate_config_to_project import MigrationRunner
    runner = MigrationRunner(
        source_claude=fake_home / ".claude",
        source_claude_json=fake_home / ".claude.json",
        dest_project=dest,
        dry_run=False,
        backup=False,
    )
    runner.run()

    remaining = json.loads((fake_home / ".claude.json").read_text())
    assert "mcpServers" not in remaining
    assert remaining["otherAppState"] == "preserved"


def test_additional_directories_updated(fake_home, tmp_path):
    dest = tmp_path / "mahavishnu"
    dest.mkdir()
    (dest / ".claude").mkdir()
    (dest / ".claude" / "settings.local.json").write_text(
        json.dumps({"additionalDirectories": [str(fake_home / ".claude"), "/keep/me"]})
    )

    from scripts.migrate_config_to_project import MigrationRunner
    runner = MigrationRunner(
        source_claude=fake_home / ".claude",
        source_claude_json=fake_home / ".claude.json",
        dest_project=dest,
        dry_run=False,
        backup=False,
    )
    runner.run()

    updated = json.loads((dest / ".claude" / "settings.local.json").read_text())
    dirs = updated["additionalDirectories"]
    assert str(fake_home / ".claude") not in dirs
    assert "/keep/me" in dirs
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/les/Projects/mahavishnu
pytest tests/unit/test_migration_script.py -v
```

Expected: `ModuleNotFoundError: No module named 'scripts.migrate_config_to_project'`

- [ ] **Step 3: Create the migration script**

```python
# scripts/migrate_config_to_project.py
"""
Migrate Claude Code configuration from ~/.claude/ to mahavishnu/.claude/.

Usage:
    python scripts/migrate_config_to_project.py --dry-run
    python scripts/migrate_config_to_project.py --backup
    python scripts/migrate_config_to_project.py --rollback
    python scripts/migrate_config_to_project.py  # full migration
"""
from __future__ import annotations

import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path


class MigrationRunner:
    def __init__(
        self,
        *,
        source_claude: Path,
        source_claude_json: Path,
        dest_project: Path,
        dry_run: bool = False,
        backup: bool = True,
    ) -> None:
        self.source_claude = source_claude
        self.source_claude_json = source_claude_json
        self.dest_project = dest_project
        self.dest_claude = dest_project / ".claude"
        self.dry_run = dry_run
        self.backup = backup
        self.backup_dir = dest_project / ".claude" / "backups" / datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
        self._ops: list[str] = []

    def _log(self, msg: str) -> None:
        prefix = "[DRY RUN] " if self.dry_run else ""
        print(f"{prefix}{msg}")

    def _copy_dir(self, src: Path, dst: Path) -> None:
        if src.is_symlink():
            resolved = src.resolve()
            self._copy_dir(resolved, dst)
            return
        for item in src.iterdir():
            target = dst / item.name
            if item.is_symlink():
                resolved = item.resolve()
                self._copy_item(resolved, target)
            elif item.is_dir():
                if not self.dry_run:
                    target.mkdir(parents=True, exist_ok=True)
                self._copy_dir(item, target)
            else:
                self._copy_item(item, target)

    def _copy_item(self, src: Path, dst: Path) -> None:
        self._log(f"  copy {src} → {dst}")
        if not self.dry_run:
            dst.parent.mkdir(parents=True, exist_ok=True)
            if not dst.exists():
                shutil.copy2(src, dst)

    def _backup_file(self, path: Path) -> None:
        if not self.backup or not path.exists():
            return
        target = self.backup_dir / path.name
        self._log(f"  backup {path} → {target}")
        if not self.dry_run:
            self.backup_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)

    # --- Phase 1: Copy files ---

    def _phase1_copy_files(self) -> None:
        self._log("Phase 1: Copying configuration files")

        for subdir in ("agents", "commands"):
            src = self.source_claude / subdir
            dst = self.dest_claude / subdir
            if src.exists():
                self._log(f"  Copying {subdir}/")
                if not self.dry_run:
                    dst.mkdir(parents=True, exist_ok=True)
                self._copy_dir(src, dst)

        skills_src = self.source_claude / "skills"
        skills_dst = self.dest_claude / "skills"
        if skills_src.exists():
            self._log("  Copying skills/ (resolving symlinks)")
            if not self.dry_run:
                skills_dst.mkdir(parents=True, exist_ok=True)
            for skill in skills_src.iterdir():
                skill_dst = skills_dst / skill.name
                if skill_dst.exists():
                    self._log(f"    skip (already exists): {skill.name}")
                    continue
                if skill.is_dir() or skill.is_symlink():
                    if not self.dry_run:
                        skill_dst.mkdir(parents=True, exist_ok=True)
                    self._copy_dir(skill, skill_dst)

        hooks_src = self.source_claude / "hooks" / "mcp-hooks.json"
        if hooks_src.exists():
            self._backup_file(hooks_src)
            self._copy_item(hooks_src, self.dest_claude / "hooks" / "mcp-hooks.json")

        claude_md_src = self.source_claude / "CLAUDE.md"
        if claude_md_src.exists():
            self._backup_file(claude_md_src)
            self._copy_item(claude_md_src, self.dest_claude / "CLAUDE.md")

    # --- Phase 2: Extract MCP servers ---

    def _phase2_extract_mcp(self) -> None:
        self._log("Phase 2: Extracting MCP servers from ~/.claude.json")
        if not self.source_claude_json.exists():
            self._log("  ~/.claude.json not found, skipping")
            return

        self._backup_file(self.source_claude_json)
        claude_data = json.loads(self.source_claude_json.read_text())
        mcp_servers = claude_data.pop("mcpServers", {})

        # Strip env blocks — secrets stay in ~/.claude/settings.json
        clean_servers: dict = {}
        for name, config in mcp_servers.items():
            clean = {k: v for k, v in config.items() if k != "env"}
            clean_servers[name] = clean

        mcp_json_path = self.dest_project / ".mcp.json"
        self._log(f"  Writing {mcp_json_path} ({len(clean_servers)} servers, env blocks stripped)")
        if not self.dry_run:
            mcp_json_path.write_text(json.dumps({"mcpServers": clean_servers}, indent=2))
            self.source_claude_json.write_text(json.dumps(claude_data, indent=2))

    # --- Phase 3: Update project config ---

    def _phase3_update_project_config(self) -> None:
        self._log("Phase 3: Updating project config")
        settings_path = self.dest_claude / "settings.local.json"
        if settings_path.exists():
            self._backup_file(settings_path)
            settings = json.loads(settings_path.read_text())
            dirs = settings.get("additionalDirectories", [])
            dirs = [d for d in dirs if str(self.source_claude) not in d and d != str(self.source_claude)]
            settings["additionalDirectories"] = dirs
            self._log(f"  Updated additionalDirectories: {dirs}")
            if not self.dry_run:
                settings_path.write_text(json.dumps(settings, indent=2))

        stub = "# Global Claude Code Configuration\n# Primary configuration lives in the Mahavishnu project.\n# See: /Users/les/Projects/mahavishnu/.claude/CLAUDE.md\n"
        stub_path = self.source_claude / "CLAUDE.md"
        self._log(f"  Writing thin stub to {stub_path}")
        if not self.dry_run:
            stub_path.write_text(stub)

    def run(self) -> None:
        if self.dry_run:
            print("=== DRY RUN — no files will be changed ===")
        self._phase1_copy_files()
        self._phase2_extract_mcp()
        self._phase3_update_project_config()
        print("Migration complete." if not self.dry_run else "Dry run complete.")


def rollback(dest_project: Path, backup_timestamp: str) -> None:
    """Restore ~/.claude.json, settings.local.json, CLAUDE.md, agents, skills, and commands from backup."""
    backup_dir = dest_project / ".claude" / "backups" / backup_timestamp
    if not backup_dir.exists():
        print(f"Backup not found: {backup_dir}")
        sys.exit(1)

    home = Path.home()

    # Restore ~/.claude.json (with mcpServers re-added)
    claude_json = home / ".claude.json"
    if (backup_dir / ".claude.json").exists():
        shutil.copy2(backup_dir / ".claude.json", claude_json)
        print(f"Restored {claude_json}")

    # Restore settings.local.json (with additionalDirectories reverted)
    settings_src = backup_dir / "settings.local.json"
    settings_dst = dest_project / ".claude" / "settings.local.json"
    if settings_src.exists():
        shutil.copy2(settings_src, settings_dst)
        print(f"Restored {settings_dst}")

    # Restore ~/.claude/CLAUDE.md (full manifest, not stub)
    claude_md_src = backup_dir / "CLAUDE.md"
    claude_md_dst = home / ".claude" / "CLAUDE.md"
    if claude_md_src.exists():
        shutil.copy2(claude_md_src, claude_md_dst)
        print(f"Restored {claude_md_dst}")

    # Restore agents, skills, and commands back to ~/.claude/ from the project directory
    for subdir in ("agents", "commands"):
        src = dest_project / ".claude" / subdir
        dst = home / ".claude" / subdir
        if src.exists():
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
            print(f"Restored {dst} from project directory")

    skills_src = dest_project / ".claude" / "skills"
    skills_dst = home / ".claude" / "skills"
    if skills_src.exists():
        if skills_dst.exists():
            shutil.rmtree(skills_dst)
        shutil.copytree(skills_src, skills_dst)
        print(f"Restored {skills_dst} from project directory")

    print("Rollback complete.")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Migrate Claude Code config to Mahavishnu project")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--backup", action="store_true", default=True)
    parser.add_argument("--rollback", metavar="TIMESTAMP", help="Rollback using backup timestamp (YYYYMMDDTHHmmSS)")
    args = parser.parse_args()

    home = Path.home()
    project = Path("/Users/les/Projects/mahavishnu")

    if args.rollback:
        rollback(project, args.rollback)
    else:
        runner = MigrationRunner(
            source_claude=home / ".claude",
            source_claude_json=home / ".claude.json",
            dest_project=project,
            dry_run=args.dry_run,
            backup=args.backup,
        )
        runner.run()
```

- [ ] **Step 4: Add `scripts/` to Python path for tests**

Add to `pyproject.toml` under `[tool.pytest.ini_options]`:
```toml
[tool.pytest.ini_options]
pythonpath = [".", "scripts"]
```

Or create `conftest.py` in `tests/`:
```python
# tests/conftest.py  (add to existing if it exists)
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/unit/test_migration_script.py -v
```

Expected: All PASS.

- [ ] **Step 6: Commit the script before running it**

```bash
git add scripts/migrate_config_to_project.py tests/unit/test_migration_script.py
git commit -m "feat(config): add migration script to consolidate ~/.claude into project directory"
```

---

## Task 2: Run migration dry-run + verify

- [ ] **Step 1: Run dry-run**

```bash
python scripts/migrate_config_to_project.py --dry-run
```

Review output — should list all copy operations, env-stripping, and settings.local.json changes without touching anything.

- [ ] **Step 2: Verify source counts match expectations**

```bash
ls ~/.claude/agents/ | wc -l         # Expect ~102
ls -d ~/.claude/skills/*/SKILL.md | wc -l  # Expect ~22 native + 5 symlinks
python3 -c "import json, pathlib; d=json.load(open(pathlib.Path.home()/'.claude.json')); print(len(d.get('mcpServers', {})))"
# Expect ~33
```

- [ ] **Step 3: Confirm no `.mcp.json` exists yet**

```bash
test ! -f /Users/les/Projects/mahavishnu/.mcp.json && echo "OK — not yet created"
```

Expected: `OK — not yet created`

---

## Task 3: Run full migration

- [ ] **Step 1: Run full migration with backup**

```bash
python scripts/migrate_config_to_project.py --backup
```

- [ ] **Step 2: Verify agent count**

```bash
ls /Users/les/Projects/mahavishnu/.claude/agents/ | wc -l
# Expect ~102
```

- [ ] **Step 3: Verify skill count**

```bash
ls -d /Users/les/Projects/mahavishnu/.claude/skills/*/SKILL.md | wc -l
# Expect ~27
```

- [ ] **Step 4: Verify MCP servers extracted**

```bash
python3 -c "
import json
d = json.load(open('/Users/les/Projects/mahavishnu/.mcp.json'))
servers = d['mcpServers']
print(f'{len(servers)} servers')
# Check no env blocks
for name, cfg in servers.items():
    assert 'env' not in cfg, f'{name} still has env block!'
print('No env blocks — OK')
"
```

Expected: `33 servers` (or actual count) + `No env blocks — OK`

- [ ] **Step 5: Verify ~/.claude.json no longer has mcpServers**

```bash
python3 -c "
import json, pathlib
d = json.load(open(pathlib.Path.home() / '.claude.json'))
assert 'mcpServers' not in d, 'mcpServers still present!'
print('mcpServers removed — OK')
"
```

- [ ] **Step 6: Verify additionalDirectories updated**

```bash
python3 -c "
import json
s = json.load(open('/Users/les/Projects/mahavishnu/.claude/settings.local.json'))
dirs = s.get('additionalDirectories', [])
print('additionalDirectories:', dirs)
assert not any('.claude' in d for d in dirs if 'Projects' not in d), 'global ~/.claude still in list'
print('OK')
"
```

- [ ] **Step 7: Verify ~/.claude/CLAUDE.md is now a stub**

```bash
wc -l ~/.claude/CLAUDE.md   # Expect 3 lines
head -1 ~/.claude/CLAUDE.md  # Expect: # Global Claude Code Configuration
```

- [ ] **Step 8: Start Claude Code and verify discovery**

```bash
claude  # Open a session from mahavishnu directory
# In the session, ask: "What agents are available?" and "What skills are available?"
# Should see all 102 agents and all 27 skills
```

> **Note:** The migrated files are untracked at this point. They will be staged and committed in Task 5 after `.gitignore` is updated. Do not commit them here.

---

## Task 4: Add `mahavishnu config` CLI commands

**Files:**
- Modify: `mahavishnu/cli/config_validator.py` (add new subcommands)

- [ ] **Step 1: Write the tests**

```python
# tests/unit/test_config_cli.py
from typer.testing import CliRunner
from mahavishnu.cli.config_validator import app  # or wherever the config app lives

runner = CliRunner()


def test_list_agents_shows_count(tmp_path, monkeypatch):
    agents_dir = tmp_path / ".claude" / "agents"
    agents_dir.mkdir(parents=True)
    (agents_dir / "python-pro.md").write_text("---\nname: python-pro\n---\n")
    (agents_dir / "code-reviewer.md").write_text("---\nname: code-reviewer\n---\n")
    monkeypatch.setenv("MAHAVISHNU_PROJECT_ROOT", str(tmp_path))

    result = runner.invoke(app, ["list-agents"])
    assert result.exit_code == 0
    assert "python-pro" in result.output


def test_list_mcp_servers_shows_servers(tmp_path, monkeypatch):
    mcp_json = tmp_path / ".mcp.json"
    import json
    mcp_json.write_text(json.dumps({"mcpServers": {"crackerjack": {"url": "http://localhost:8676"}}}))
    monkeypatch.setenv("MAHAVISHNU_PROJECT_ROOT", str(tmp_path))

    result = runner.invoke(app, ["list-mcp-servers"])
    assert result.exit_code == 0
    assert "crackerjack" in result.output
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/unit/test_config_cli.py -v
```

Expected: `ImportError` or `AttributeError` — `list-agents` and `list-mcp-servers` commands don't exist yet.

- [ ] **Step 3: Add CLI commands to `config_validator.py`**

Locate the Typer `app` instance in `mahavishnu/cli/config_validator.py` and add these commands:

```python
# In mahavishnu/cli/config_validator.py — append to existing commands

PROJECT_ROOT = Path(__file__).parent.parent.parent  # mahavishnu/


@app.command("list-agents")
def list_agents(
    role: str | None = typer.Option(None, help="Filter by role tag in frontmatter"),
) -> None:
    """List all agents in .claude/agents/."""
    import re
    agents_dir = PROJECT_ROOT / ".claude" / "agents"
    if not agents_dir.exists():
        typer.echo("No agents directory found. Run migration first.")
        raise typer.Exit(1)
    agents = sorted(agents_dir.glob("*.md"))
    typer.echo(f"{len(agents)} agents found:")
    for a in agents:
        typer.echo(f"  {a.stem}")


@app.command("list-skills")
def list_skills() -> None:
    """List all skills in .claude/skills/."""
    skills_dir = PROJECT_ROOT / ".claude" / "skills"
    if not skills_dir.exists():
        typer.echo("No skills directory found. Run migration first.")
        raise typer.Exit(1)
    skills = [d for d in skills_dir.iterdir() if (d / "SKILL.md").exists()]
    typer.echo(f"{len(skills)} skills found:")
    for s in sorted(skills):
        typer.echo(f"  {s.name}")


@app.command("list-mcp-servers")
def list_mcp_servers() -> None:
    """List MCP servers from .mcp.json."""
    mcp_path = PROJECT_ROOT / ".mcp.json"
    if not mcp_path.exists():
        typer.echo(".mcp.json not found. Run migration first.")
        raise typer.Exit(1)
    data = json.loads(mcp_path.read_text())
    servers = data.get("mcpServers", {})
    typer.echo(f"{len(servers)} MCP servers:")
    for name, cfg in sorted(servers.items()):
        url = cfg.get("url", cfg.get("command", "local"))
        typer.echo(f"  {name}: {url}")


@app.command("sync-from-global")
def sync_from_global(
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Re-import agents/skills added to ~/.claude/ since last migration."""
    home = Path.home()
    runner = MigrationRunner(
        source_claude=home / ".claude",
        source_claude_json=home / ".claude.json",
        dest_project=PROJECT_ROOT,
        dry_run=dry_run,
        backup=False,
    )
    runner.run()


@app.command("rollback")
def rollback_cmd(
    timestamp: str = typer.Argument(help="Backup timestamp (YYYYMMDDTHHmmSS)"),
) -> None:
    """Restore ~/.claude.json, settings.local.json, and agents/skills from backup."""
    import sys
    from migrate_config_to_project import rollback
    rollback(PROJECT_ROOT, timestamp)
```

Import `MigrationRunner` and `rollback` at the top of the file:

```python
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
from migrate_config_to_project import MigrationRunner, rollback
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/unit/test_config_cli.py -v
```

Expected: All PASS.

- [ ] **Step 5: Smoke test commands**

```bash
python -m mahavishnu config list-agents | head -5
python -m mahavishnu config list-skills | head -5
python -m mahavishnu config list-mcp-servers | head -5
```

- [ ] **Step 6: Commit**

```bash
git add mahavishnu/cli/config_validator.py tests/unit/test_config_cli.py
git commit -m "feat(config): add list-agents, list-skills, list-mcp-servers, sync-from-global, rollback CLI commands"
```

---

## Task 5: Update `.gitignore`

- [ ] **Step 1: Add rules**

Open `/Users/les/Projects/mahavishnu/.gitignore` and add:

```gitignore
# Claude Code project config — keep canonical files, ignore runtime-only
.claude/hooks/scripts/
.claude/skills/*/.archive/
.claude/backups/
```

- [ ] **Step 2: Verify agents and skills are tracked**

```bash
git status .claude/agents/ | head -10    # Should show files as untracked/new
git status .mcp.json                      # Should show as untracked/new
```

- [ ] **Step 3: Stage the canonical config files**

```bash
git add .claude/agents/ .claude/skills/ .claude/commands/ .claude/hooks/mcp-hooks.json
git add .claude/CLAUDE.md .claude/settings.local.json .mcp.json .gitignore
git status | grep "\.claude\|\.mcp" | head -20
```

- [ ] **Step 4: Verify no secrets staged**

```bash
# Should show no API keys or tokens
git diff --cached | grep -i "key\|token\|secret\|password" | grep "^+" | grep -v "secret_env_var\|secret_path\|jwt_secret" | head -20
```

If any matches found, un-stage and check: these should only be variable names, never values.

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(config): commit canonical Claude Code configuration into project (agents, skills, commands, MCP servers)"
```

---

## Task 6: Add anti-drift validation

**Files:**
- Modify: `mahavishnu/core/config_validator.py` — add `check_skill_mcp_drift()` function and wire into `validate_config()`. Note: this is the **core** validator (business logic), distinct from `mahavishnu/cli/config_validator.py` (CLI commands) modified in Task 4.
- Test: `tests/unit/test_config_drift.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_config_drift.py
import json
from pathlib import Path
import pytest


@pytest.fixture
def project_layout(tmp_path):
    """Fake project with .mcp.json and one skill with a port reference."""
    mcp = tmp_path / ".mcp.json"
    mcp.write_text(json.dumps({
        "mcpServers": {
            "crackerjack": {"url": "http://localhost:8676"},
            "akosha": {"url": "http://localhost:8682"},
        }
    }))
    skills_dir = tmp_path / ".claude" / "skills" / "my-skill"
    skills_dir.mkdir(parents=True)
    (skills_dir / "SKILL.md").write_text(
        "## Available MCP Servers\n| crackerjack | 9999 | ... |\n"
    )
    return tmp_path


def test_detects_port_drift(project_layout):
    from mahavishnu.core.config_validator import check_skill_mcp_drift
    issues = check_skill_mcp_drift(project_layout)
    assert len(issues) == 1
    assert "9999" in issues[0]
    assert "8676" in issues[0]  # actual port from .mcp.json


def test_no_drift_when_ports_match(tmp_path):
    mcp = tmp_path / ".mcp.json"
    mcp.write_text(json.dumps({"mcpServers": {"crackerjack": {"url": "http://localhost:8676"}}}))
    skills_dir = tmp_path / ".claude" / "skills" / "my-skill"
    skills_dir.mkdir(parents=True)
    (skills_dir / "SKILL.md").write_text("| crackerjack | 8676 | ... |")

    from mahavishnu.core.config_validator import check_skill_mcp_drift
    issues = check_skill_mcp_drift(tmp_path)
    assert issues == []
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/test_config_drift.py -v
```

Expected: `ImportError` for `check_skill_mcp_drift`.

- [ ] **Step 3: Add drift check to core config validator**

Find `mahavishnu/core/config_validator.py` and add:

```python
# mahavishnu/core/config_validator.py — add these functions

import re


def _extract_mcp_ports_from_json(project_root: Path) -> dict[str, int]:
    """Extract server_name → port from .mcp.json."""
    mcp_path = project_root / ".mcp.json"
    if not mcp_path.exists():
        return {}
    data = json.loads(mcp_path.read_text())
    ports = {}
    for name, cfg in data.get("mcpServers", {}).items():
        url = cfg.get("url", "")
        match = re.search(r":(\d+)", url)
        if match:
            ports[name] = int(match.group(1))
    return ports


def check_skill_mcp_drift(project_root: Path) -> list[str]:
    """Report port drift between .mcp.json and skill MCP reference tables."""
    issues: list[str] = []
    known_ports = _extract_mcp_ports_from_json(project_root)
    if not known_ports:
        return issues

    skills_dir = project_root / ".claude" / "skills"
    if not skills_dir.exists():
        return issues

    for skill_file in skills_dir.rglob("SKILL.md"):
        content = skill_file.read_text()
        for server_name, actual_port in known_ports.items():
            # Look for table rows: | server_name | NNNN |
            pattern = rf"\|\s*{re.escape(server_name)}\s*\|\s*(\d+)"
            for match in re.finditer(pattern, content):
                doc_port = int(match.group(1))
                if doc_port != actual_port:
                    issues.append(
                        f"Port drift in {skill_file.relative_to(project_root)}: "
                        f"{server_name} documented as :{doc_port}, "
                        f"but .mcp.json says :{actual_port}"
                    )
    return issues
```

Also wire it into the existing `validate_config()` function. The function accumulates warnings as a `list[str]` — extend it with drift results:

```python
# In validate_config() or equivalent top-level function — add:
drift_issues = check_skill_mcp_drift(project_root)
warnings.extend(drift_issues)
# Then at the end of validate_config(), warnings is returned or printed.
# If your existing function uses a different accumulator name, replace `warnings`
# with whatever list variable holds validation warnings in that function.
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/unit/test_config_drift.py -v
```

Expected: All PASS.

- [ ] **Step 5: Run full validation to confirm no drift in migrated files**

```bash
mahavishnu config validate
```

Expected: passes (or shows only known acceptable issues).

- [ ] **Step 6: Commit**

```bash
git add mahavishnu/core/config_validator.py tests/unit/test_config_drift.py
git commit -m "feat(config): add MCP port drift detection to config validate"
```

---

## Task 7: Final verification

- [ ] **Step 1: Run all tests**

```bash
pytest -x -q
```

Expected: All PASS.

- [ ] **Step 2: Run acceptance criteria check**

```bash
# AC1: 101+ agents present
ls /Users/les/Projects/mahavishnu/.claude/agents/ | wc -l

# AC9: No symlinks remain in .claude/skills/ (all resolved to real files)
find /Users/les/Projects/mahavishnu/.claude/skills -type l
# Expected: empty output — no symlinks should exist after migration


# AC2: 27 skills present
ls -d /Users/les/Projects/mahavishnu/.claude/skills/*/SKILL.md | wc -l

# AC3: 33 MCP servers in .mcp.json
python3 -c "import json; d=json.load(open('/Users/les/Projects/mahavishnu/.mcp.json')); print(len(d['mcpServers']), 'servers')"

# AC4: CLAUDE.md present
wc -l /Users/les/Projects/mahavishnu/.claude/CLAUDE.md

# AC5: ~/.claude/CLAUDE.md is thin stub
wc -l ~/.claude/CLAUDE.md   # Should be 3

# AC6: mcpServers gone from ~/.claude.json
python3 -c "import json, pathlib; d=json.load(open(pathlib.Path.home()/'.claude.json')); print('mcpServers' in d)"
# Should print: False

# AC7: ~/.claude not in additionalDirectories
python3 -c "import json; s=json.load(open('/Users/les/Projects/mahavishnu/.claude/settings.local.json')); print(s['additionalDirectories'])"

# AC13: No secrets in staged files
git diff HEAD .claude/ .mcp.json | grep "^+" | grep -iE "(api_key|token|password|secret)\s*=" | head
# Should be empty
```

- [ ] **Step 3: Final commit**

```bash
git add -A
git commit -m "chore(config): complete config consolidation — verify all acceptance criteria"
```
