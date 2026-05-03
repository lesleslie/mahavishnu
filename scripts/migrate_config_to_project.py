"""
Migrate Claude Code configuration from ~/.claude/ to mahavishnu/.claude/.

Usage:
    python scripts/migrate_config_to_project.py --dry-run
    python scripts/migrate_config_to_project.py --backup
    python scripts/migrate_config_to_project.py --rollback <TIMESTAMP>
    python scripts/migrate_config_to_project.py  # full migration
"""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import shutil
import sys


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
        self.backup_dir = (
            dest_project / ".claude" / "backups" / datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
        )

    def _log(self, msg: str) -> None:
        prefix = "[DRY RUN] " if self.dry_run else ""
        print(f"{prefix}{msg}")

    def _copy_dir(self, src: Path, dst: Path) -> None:
        if src.is_symlink():
            self._copy_dir(src.resolve(), dst)
            return
        for item in src.iterdir():
            target = dst / item.name
            if item.is_symlink():
                self._copy_item(item.resolve(), target)
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

    def _phase2_extract_mcp(self) -> None:
        self._log("Phase 2: Extracting MCP servers from ~/.claude.json")
        if not self.source_claude_json.exists():
            self._log("  ~/.claude.json not found, skipping")
            return

        self._backup_file(self.source_claude_json)
        claude_data = json.loads(self.source_claude_json.read_text())
        mcp_servers = claude_data.pop("mcpServers", {})

        # Strip env blocks — secrets stay in the shell environment, never in VCS
        clean_servers: dict = {}
        for name, config in mcp_servers.items():
            clean = {k: v for k, v in config.items() if k != "env"}
            clean_servers[name] = clean

        mcp_json_path = self.dest_project / ".mcp.json"
        self._log(f"  Writing {mcp_json_path} ({len(clean_servers)} servers, env blocks stripped)")
        if not self.dry_run:
            mcp_json_path.write_text(json.dumps({"mcpServers": clean_servers}, indent=2))
            self.source_claude_json.write_text(json.dumps(claude_data, indent=2))

    def _phase3_update_project_config(self) -> None:
        self._log("Phase 3: Updating project config")
        settings_path = self.dest_claude / "settings.local.json"
        if settings_path.exists():
            self._backup_file(settings_path)
            settings = json.loads(settings_path.read_text())
            dirs = settings.get("additionalDirectories", [])
            dirs = [
                d for d in dirs if str(self.source_claude) not in d and d != str(self.source_claude)
            ]
            settings["additionalDirectories"] = dirs
            self._log(f"  Updated additionalDirectories: {dirs}")
            if not self.dry_run:
                settings_path.write_text(json.dumps(settings, indent=2))

        stub = (
            "# Global Claude Code Configuration\n"
            "# Primary configuration lives in the Mahavishnu project.\n"
            "# See: /Users/les/Projects/mahavishnu/.claude/CLAUDE.md\n"
        )
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
    """Restore ~/.claude.json, settings.local.json, CLAUDE.md, agents, skills from backup."""
    backup_dir = dest_project / ".claude" / "backups" / backup_timestamp
    if not backup_dir.exists():
        print(f"Backup not found: {backup_dir}")
        sys.exit(1)

    home = Path.home()

    claude_json = home / ".claude.json"
    if (backup_dir / ".claude.json").exists():
        shutil.copy2(backup_dir / ".claude.json", claude_json)
        print(f"Restored {claude_json}")

    settings_src = backup_dir / "settings.local.json"
    settings_dst = dest_project / ".claude" / "settings.local.json"
    if settings_src.exists():
        shutil.copy2(settings_src, settings_dst)
        print(f"Restored {settings_dst}")

    claude_md_src = backup_dir / "CLAUDE.md"
    claude_md_dst = home / ".claude" / "CLAUDE.md"
    if claude_md_src.exists():
        shutil.copy2(claude_md_src, claude_md_dst)
        print(f"Restored {claude_md_dst}")

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
    parser.add_argument(
        "--rollback",
        metavar="TIMESTAMP",
        help="Rollback using backup timestamp (YYYYMMDDTHHmmSS)",
    )
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
