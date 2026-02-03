"""
Claude-Qwen Sync CLI for Mahavishnu

Provides bidirectional synchronization between Claude Code and Qwen Code configurations:
- MCP servers (JSON dict merge)
- Extensions/plugins (JSON dict merge)
- File-based resources (agents, commands, skills)

Usage:
    mahavishnu sync --daemon      # Run as background daemon
    mahavishnu sync --once        # Run once and exit
    mahavishnu sync --status      # Show sync status
"""

import hashlib
import json
from pathlib import Path
import time
from typing import Any

import structlog
import typer
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

# Create sync CLI app
sync_app = typer.Typer(
    name="sync",
    help="Claude-Qwen configuration synchronization",
    add_completion=False,
)

logger = structlog.get_logger()


def add_sync_commands(main_app: typer.Typer) -> None:
    """Add sync commands to main CLI app.

    Args:
        main_app: Main Typer application to add commands to
    """
    main_app.add_typer(sync_app)


# Configuration paths
CLAUDE_CONFIG = Path.home() / ".claude.json"
QWEN_CONFIG = Path.home() / ".qwen" / "settings.json"
CLAUDE_SETTINGS = Path.home() / ".claude" / "settings.json"
QWEN_DIR = Path.home() / ".qwen"
CLAUDE_COMMANDS_DIR = Path.home() / ".claude" / "commands"
QWEN_COMMANDS_DIR = Path.home() / ".qwen" / "commands"
CLAUDE_AGENTS_DIR = Path.home() / ".claude" / "agents"
CLAUDE_PLUGINS_FILE = Path.home() / ".claude" / "plugins" / "installed_plugins.json"

# MCP servers to skip during sync (servers that should not be synced to Qwen)
DEFAULT_SKIP_SERVERS = ["homebrew", "pycharm"]

# Sync types
SYNC_TYPE_MCP = "mcp_servers"
SYNC_TYPE_EXTENSIONS = "extensions"
SYNC_TYPE_COMMANDS = "commands"
SYNC_TYPE_AGENTS = "agents"


class SyncConflictError(Exception):
    """Raised when sync conflict cannot be auto-resolved."""

    def __init__(self, message: str, claude_value: Any, qwen_value: Any):
        self.message = message
        self.claude_value = claude_value
        self.qwen_value = qwen_value
        super().__init__(message)


def file_hash(path: Path) -> str:
    """Calculate SHA-256 hash of file for change detection.

    Args:
        path: File path to hash

    Returns:
        Hexadecimal SHA-256 hash
    """
    if not path.exists():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json_safely(path: Path) -> dict[str, Any]:
    """Load JSON file safely, returning empty dict if not exists.

    Args:
        path: Path to JSON file

    Returns:
        Parsed JSON dict or empty dict
    """
    try:
        if path.exists():
            return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        logger.error(f"Failed to load {path}: {e}")
    return {}


def save_json_atomically(path: Path, data: dict[str, Any]) -> None:
    """Save JSON file atomically to prevent corruption.

    Args:
        path: Target file path
        data: Data to save
    """
    # Write to temp file first
    temp_path = path.with_suffix(".tmp")
    temp_path.write_text(json.dumps(data, indent=2))
    # Atomic rename
    temp_path.replace(path)
    logger.debug(f"Saved {path} atomically")


def merge_mcp_servers(
    claude: dict[str, Any],
    qwen: dict[str, Any],
    skip_servers: list[str] | None = None,
) -> dict[str, Any]:
    """Merge MCP servers from both configs.

    Strategy:
    - Servers unique to one side: add to other
    - Servers on both sides: Claude takes precedence (last-write-wins)
    - Preserve server metadata (type, url, command, args)
    - Skip servers in skip_servers list (won't be synced)

    Args:
        claude: Claude config dict
        qwen: Qwen config dict
        skip_servers: List of server names to skip syncing (default: DEFAULT_SKIP_SERVERS)

    Returns:
        Merged mcpServers dict
    """
    if skip_servers is None:
        skip_servers = DEFAULT_SKIP_SERVERS

    claude_mcp = claude.get("mcpServers", {})
    qwen_mcp = qwen.get("mcpServers", {})

    # Filter out skipped servers from Claude's config
    filtered_claude_mcp = {
        name: config for name, config in claude_mcp.items() if name not in skip_servers
    }

    # Start with Qwen's servers
    merged = {**qwen_mcp}
    # Overwrite/add Claude's servers (Claude takes precedence)
    merged.update(filtered_claude_mcp)

    skipped_count = len(claude_mcp) - len(filtered_claude_mcp)
    logger.debug(
        f"Merged {len(filtered_claude_mcp)} Claude + {len(qwen_mcp)} Qwen MCP servers "
        f"(skipped {skipped_count}: {', '.join(skip_servers)})"
    )
    return merged


def sync_extensions_claude_to_qwen() -> dict[str, Any]:
    """Sync Claude plugins → Qwen extensions.

    Note: Qwen extensions must be installed via `qwen extensions install`.
    This sync only tracks which extensions should be installed.

    Returns:
        Sync result with stats
    """
    logger.info("Syncing Claude plugins → Qwen extensions")

    claude_settings = load_json_safely(CLAUDE_SETTINGS)
    plugins_manifest = load_json_safely(CLAUDE_PLUGINS_FILE)

    stats = {"plugins_found": 0, "errors": []}

    try:
        enabled_plugins = claude_settings.get("enabledPlugins", {})
        stats["plugins_found"] = len(enabled_plugins)

        # Extract plugin names (remove marketplace suffix)
        plugin_names = []
        for plugin_id in enabled_plugins.keys():
            # Format: "plugin-name@marketplace" → "plugin-name"
            name = plugin_id.split("@")[0]
            plugin_names.append(name)

        logger.info(f"Found {len(plugin_names)} Claude plugins to potentially sync")
        logger.debug(
            f"Plugins: {', '.join(plugin_names[:5])}{'...' if len(plugin_names) > 5 else ''}"
        )

        # Note: Actual extension installation requires:
        # qwen extensions install <marketplace-url>:<plugin-name>
        # This is just tracking - user must manually install

    except Exception as e:
        error_msg = f"Failed to sync extensions: {e}"
        logger.error(error_msg)
        stats["errors"].append(error_msg)

    return stats


def markdown_to_qwen_markdown(md_content: str, command_name: str) -> str:
    """Convert Claude command markdown to Qwen markdown format.

    Qwen commands use .md files with YAML frontmatter:
    ---
    description: Command description
    ---

    Prompt content here

    Args:
        md_content: Markdown content from Claude command
        command_name: Name of the command

    Returns:
        Qwen-formatted markdown string
    """
    import re

    # Extract description from Claude format
    # Claude format: "## description: <text>" or first heading
    lines = md_content.strip().split("\n")

    description = command_name  # Default
    prompt_start = 0

    # Look for description line
    for i, line in enumerate(lines):
        # Claude format: ## description: ...
        if "description:" in line.lower():
            match = re.search(r"description:\s*(.+?)(?:\s+id:)?$", line, re.IGNORECASE)
            if match:
                description = match.group(1).strip()
                prompt_start = i + 1
                break
        # First heading as description
        elif line.strip().startswith("#"):
            description = line.strip("#").strip()
            prompt_start = i + 1
            break

    # Extract the main prompt content
    prompt_lines = []
    in_code_block = False

    for line in lines[prompt_start:]:
        # Track code blocks
        if "```" in line:
            in_code_block = not in_code_block
            prompt_lines.append(line)
            continue

        # Add all content (including markdown)
        prompt_lines.append(line)

    prompt_content = "\n".join(prompt_lines).strip()

    # Format as Qwen markdown with YAML frontmatter
    qwen_md = f"""---
description: {description}
---

# Command synced from Claude Code
# Original location: ~/.claude/commands/{command_name}.md

{prompt_content}
"""

    return qwen_md


def sync_commands_claude_to_qwen() -> dict[str, Any]:
    """Sync Claude commands (.md) → Qwen commands (.md).

    Converts Claude command markdown to Qwen markdown format with YAML frontmatter.

    Returns:
        Sync result with stats
    """
    logger.info("Syncing Claude commands → Qwen commands")

    stats = {"commands_synced": 0, "commands_skipped": 0, "errors": []}

    try:
        # Create Qwen commands directory if it doesn't exist
        QWEN_COMMANDS_DIR.mkdir(parents=True, exist_ok=True)

        # Find all markdown command files in Claude
        md_files = list(CLAUDE_COMMANDS_DIR.glob("**/*.md"))
        logger.debug(f"Found {len(md_files)} command files in Claude")

        for md_file in md_files:
            try:
                # Get relative path from commands directory
                rel_path = md_file.relative_to(CLAUDE_COMMANDS_DIR)
                # Keep .md extension (both use .md now)
                md_name = rel_path.with_suffix(".md")

                # Create subdirectories if needed
                qwen_md_file = QWEN_COMMANDS_DIR / md_name
                qwen_md_file.parent.mkdir(parents=True, exist_ok=True)

                # Convert Claude markdown to Qwen markdown format
                claude_md = md_file.read_text()
                qwen_md = markdown_to_qwen_markdown(claude_md, md_file.stem)

                # Write markdown file
                qwen_md_file.write_text(qwen_md)
                stats["commands_synced"] += 1

                logger.debug(f"Converted: {rel_path} → {md_name}")

            except Exception as e:
                error_msg = f"Failed to convert {md_file}: {e}"
                logger.warning(error_msg)
                stats["errors"].append(error_msg)
                stats["commands_skipped"] += 1

        logger.info(f"✅ Synced {stats['commands_synced']} commands to Qwen")

    except Exception as e:
        error_msg = f"Failed to sync commands: {e}"
        logger.error(error_msg)
        stats["errors"].append(error_msg)

    return stats


def sync_claude_to_qwen(
    sync_types: list[str] | None = None,
    skip_servers: list[str] | None = None,
) -> dict[str, Any]:
    """Sync Claude config → Qwen config.

    Args:
        sync_types: List of sync types to perform (default: all)
        skip_servers: List of server names to skip syncing (default: DEFAULT_SKIP_SERVERS)

    Returns:
        Sync result with stats
    """
    if sync_types is None:
        sync_types = [SYNC_TYPE_MCP, SYNC_TYPE_EXTENSIONS, SYNC_TYPE_COMMANDS]

    if skip_servers is None:
        skip_servers = DEFAULT_SKIP_SERVERS

    logger.info("Syncing Claude → Qwen")

    claude = load_json_safely(CLAUDE_CONFIG)
    qwen = load_json_safely(QWEN_CONFIG)

    stats = {
        "mcp_servers": 0,
        "mcp_servers_skipped": 0,
        "plugins_found": 0,
        "commands_synced": 0,
        "errors": [],
    }

    # Sync MCP servers
    if SYNC_TYPE_MCP in sync_types:
        try:
            if "mcpServers" in claude:
                claude_mcp_count = len(claude["mcpServers"])
                qwen["mcpServers"] = merge_mcp_servers(claude, qwen, skip_servers)
                stats["mcp_servers"] = claude_mcp_count
                stats["mcp_servers_skipped"] = len(
                    [s for s in claude["mcpServers"] if s in skip_servers]
                )
                save_json_atomically(QWEN_CONFIG, qwen)
                logger.info(
                    f"✅ Synced {stats['mcp_servers']} MCP servers to Qwen "
                    f"(skipped {stats['mcp_servers_skipped']}: {', '.join(skip_servers)})"
                )
        except Exception as e:
            error_msg = f"Failed to sync MCP servers: {e}"
            logger.error(error_msg)
            stats["errors"].append(error_msg)

    # Sync extensions/plugins
    if SYNC_TYPE_EXTENSIONS in sync_types:
        ext_stats = sync_extensions_claude_to_qwen()
        stats["plugins_found"] = ext_stats["plugins_found"]
        stats["errors"].extend(ext_stats["errors"])

    # Sync commands
    if SYNC_TYPE_COMMANDS in sync_types:
        cmd_stats = sync_commands_claude_to_qwen()
        stats["commands_synced"] = cmd_stats["commands_synced"]
        stats["errors"].extend(cmd_stats["errors"])

    return stats


def sync_qwen_to_claude() -> dict[str, Any]:
    """Sync Qwen config → Claude config.

    Returns:
        Sync result with stats
    """
    logger.info("Syncing Qwen → Claude")

    qwen = load_json_safely(QWEN_CONFIG)
    claude = load_json_safely(CLAUDE_CONFIG)

    stats = {"mcp_servers": 0, "errors": []}

    try:
        # Merge MCP servers
        if "mcpServers" in qwen:
            claude["mcpServers"] = merge_mcp_servers(qwen, claude)
            stats["mcp_servers"] = len(qwen["mcpServers"])
            save_json_atomically(CLAUDE_CONFIG, claude)
            logger.info(f"✅ Synced {stats['mcp_servers']} MCP servers to Claude")
    except Exception as e:
        error_msg = f"Failed to sync MCP servers: {e}"
        logger.error(error_msg)
        stats["errors"].append(error_msg)

    return stats


class ConfigSyncHandler(FileSystemEventHandler):
    """Watchdog event handler for config file changes.

    Monitors ~/.claude.json and ~/.qwen/settings.json for modifications
    and triggers bidirectional sync automatically.
    """

    def __init__(self, dry_run: bool = False, skip_servers: list[str] | None = None):
        """Initialize sync handler.

        Args:
            dry_run: If True, log but don't perform sync
            skip_servers: List of server names to skip syncing
        """
        super().__init__()
        self.dry_run = dry_run
        self.skip_servers = skip_servers if skip_servers is not None else DEFAULT_SKIP_SERVERS
        self.last_hash = {
            "claude": file_hash(CLAUDE_CONFIG),
            "qwen": file_hash(QWEN_CONFIG),
        }
        self.sync_count = {"claude_to_qwen": 0, "qwen_to_claude": 0}

    def on_modified(self, event) -> None:
        """Handle file modification events.

        Args:
            event: Watchdog file system event
        """
        if event.is_directory:
            return

        path = Path(event.src_path)

        # Sync Claude → Qwen
        if path == CLAUDE_CONFIG:
            current_hash = file_hash(path)
            if current_hash != self.last_hash["claude"]:
                logger.info("🔄 Claude config changed, syncing to Qwen...")
                if not self.dry_run:
                    sync_claude_to_qwen(skip_servers=self.skip_servers)
                self.last_hash["claude"] = current_hash
                self.sync_count["claude_to_qwen"] += 1

        # Sync Qwen → Claude
        elif path == QWEN_CONFIG:
            current_hash = file_hash(path)
            if current_hash != self.last_hash["qwen"]:
                logger.info("🔄 Qwen config changed, syncing to Claude...")
                if not self.dry_run:
                    sync_qwen_to_claude()
                self.last_hash["qwen"] = current_hash
                self.sync_count["qwen_to_claude"] += 1


@sync_app.command()
def once(
    direction: str = typer.Option(
        "both",
        "--direction",
        "-d",
        help="Sync direction: 'claude-to-qwen', 'qwen-to-claude', or 'both'",
    ),
    sync_type: list[str] = typer.Option(
        None,
        "--type",
        "-t",
        help="Sync types to include (mcp, extensions, commands). Can be specified multiple times.",
    ),
    skip: list[str] = typer.Option(
        None,
        "--skip",
        "-s",
        help="MCP servers to skip syncing (default: homebrew, pycharm). Can be specified multiple times.",
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
) -> None:
    """Run sync once and exit.

    Performs bidirectional synchronization between Claude and Qwen configurations.

    Sync types:
    - mcp: MCP servers (default)
    - extensions: Plugins/extensions tracking
    - commands: Convert Claude .md commands to Qwen .toml

    Skip list:
    - By default, skips: homebrew, pycharm
    - Use --skip to customize which servers to skip
    - Use --skip-empty to skip nothing (sync all servers)

    Examples:
        mahavishnu sync once                           # Sync all types (skip homebrew, pycharm)
        mahavishnu sync once --skip homebrew pycharm   # Custom skip list
        mahavishnu sync once --type mcp --type commands  # Sync only MCP + commands
        mahavishnu sync once --direction claude-to-qwen  # One-way sync
    """
    if verbose:
        import structlog

        structlog.configure(logger_factory=structlog.PrintLoggerFactory())

    # Convert sync type options
    sync_types = []
    if sync_type:
        type_mapping = {
            "mcp": SYNC_TYPE_MCP,
            "extensions": SYNC_TYPE_EXTENSIONS,
            "commands": SYNC_TYPE_COMMANDS,
        }
        for st in sync_type:
            if st in type_mapping:
                sync_types.append(type_mapping[st])
    else:
        # Default: sync all types
        sync_types = None

    # Set skip servers
    skip_servers = skip if skip else None

    logger.info("Starting one-time sync...")
    if skip_servers:
        logger.info(f"Skipping MCP servers: {', '.join(skip_servers)}")

    stats = []

    if direction in ("both", "claude-to-qwen"):
        result = sync_claude_to_qwen(sync_types, skip_servers)
        stats.append(("Claude → Qwen", result))

    if direction in ("both", "qwen-to-claude"):
        result = sync_qwen_to_claude()
        stats.append(("Qwen → Claude", result))

    # Print summary
    typer.echo("\n📊 Sync Summary:")
    for direction_name, result in stats:
        typer.echo(f"  {direction_name}:")
        typer.echo(f"    MCP servers: {result.get('mcp_servers', 0)}")
        if result.get("mcp_servers_skipped", 0) > 0:
            typer.echo(f"    MCP servers skipped: {result['mcp_servers_skipped']}")
        if "plugins_found" in result:
            typer.echo(f"    Plugins found: {result['plugins_found']}")
        if "commands_synced" in result:
            typer.echo(f"    Commands synced: {result['commands_synced']}")
        if result.get("errors"):
            typer.echo(f"    Errors: {len(result['errors'])}")
            for error in result["errors"]:
                typer.echo(f"      - {error}")

    logger.info("One-time sync complete")


@sync_app.command()
def daemon(
    dry_run: bool = typer.Option(False, "--dry-run", help="Log changes without syncing"),
    skip: list[str] = typer.Option(
        None,
        "--skip",
        "-s",
        help="MCP servers to skip syncing (default: homebrew, pycharm). Can be specified multiple times.",
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
) -> None:
    """Run sync daemon (monitors for file changes).

    Starts a background process that watches ~/.claude.json and ~/.qwen/settings.json
    and automatically syncs changes between them.

    Skip list:
    - By default, skips: homebrew, pycharm
    - Use --skip to customize which servers to skip

    Examples:
        mahavishnu sync daemon                          # Skip homebrew, pycharm
        mahavishnu sync daemon --skip homebrew neo4j    # Custom skip list
    """
    if verbose:
        import structlog

        structlog.configure(logger_factory=structlog.PrintLoggerFactory())

    # Set skip servers
    skip_servers = skip if skip else DEFAULT_SKIP_SERVERS

    logger.info("Starting Claude-Qwen sync daemon...")
    if skip_servers:
        logger.info(f"Skipping MCP servers: {', '.join(skip_servers)}")

    handler = ConfigSyncHandler(dry_run=dry_run, skip_servers=skip_servers)
    observer = Observer()

    # Watch Claude config
    if CLAUDE_CONFIG.exists():
        observer.schedule(handler, path=str(CLAUDE_CONFIG.parent), recursive=False)
        logger.info(f"   Watching: {CLAUDE_CONFIG}")
    else:
        logger.warning(f"   Claude config not found: {CLAUDE_CONFIG}")

    # Watch Qwen config
    if QWEN_CONFIG.exists():
        observer.schedule(handler, path=str(QWEN_CONFIG.parent), recursive=False)
        logger.info(f"   Watching: {QWEN_CONFIG}")
    else:
        logger.warning(f"   Qwen config not found: {QWEN_CONFIG}")

    if not observer.emitters:
        logger.error("No config files to watch!")
        raise typer.Exit(1)

    observer.start()

    typer.echo("\n🚀 Claude-Qwen sync daemon started")
    typer.echo(f"   Claude config: {CLAUDE_CONFIG}")
    typer.echo(f"   Qwen config: {QWEN_CONFIG}")
    typer.echo("\nPress Ctrl+C to stop...\n")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
        typer.echo("\n\n🛑 Sync daemon stopped")

        # Print stats
        typer.echo("\n📊 Session Statistics:")
        typer.echo(f"  Claude → Qwen: {handler.sync_count['claude_to_qwen']} syncs")
        typer.echo(f"  Qwen → Claude: {handler.sync_count['qwen_to_claude']} syncs")

    observer.join()


@sync_app.command()
def status() -> None:
    """Show current sync status."""
    typer.echo("\n📊 Claude-Qwen Sync Status\n")
    typer.echo("=" * 50)

    # Claude config
    typer.echo("\n🤖 Claude Code:")
    if CLAUDE_CONFIG.exists():
        claude = load_json_safely(CLAUDE_CONFIG)
        mcp_count = len(claude.get("mcpServers", {}))
        typer.echo(f"  Config: {CLAUDE_CONFIG}")
        typer.echo(f"  MCP servers: {mcp_count}")
        typer.echo(f"  Last modified: {time.ctime(CLAUDE_CONFIG.stat().st_mtime)}")
    else:
        typer.echo(f"  ❌ Config not found: {CLAUDE_CONFIG}")

    # Qwen config
    typer.echo("\n🦙 Qwen Code:")
    if QWEN_CONFIG.exists():
        qwen = load_json_safely(QWEN_CONFIG)
        mcp_count = len(qwen.get("mcpServers", {}))
        typer.echo(f"  Config: {QWEN_CONFIG}")
        typer.echo(f"  MCP servers: {mcp_count}")
        typer.echo(f"  Last modified: {time.ctime(QWEN_CONFIG.stat().st_mtime)}")
    else:
        typer.echo(f"  ❌ Config not found: {QWEN_CONFIG}")

    typer.echo("\n" + "=" * 50)


@sync_app.command()
def install_service() -> None:
    """Install sync daemon as system service (launchd/systemd)."""

    import platform
    import subprocess

    system = platform.system()
    mahavishnu_bin = Path.home() / ".local" / "bin" / "mahavishnu"

    typer.echo(f"\n🔧 Installing sync daemon service on {system}...")

    if system == "Darwin":
        # macOS launchd service
        plist_path = Path.home() / "Library" / "LaunchAgents" / "com.mahavishnu.sync.plist"

        plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.mahavishnu.sync</string>
    <key>ProgramArguments</key>
    <array>
        <string>{mahavishnu_bin}</string>
        <string>sync</string>
        <string>daemon</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/mahavishnu-sync.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/mahavishnu-sync.err</string>
</dict>
</plist>
"""
        plist_path.write_text(plist_content)
        typer.echo(f"✅ Created launchd plist: {plist_path}")

        # Load the service
        subprocess.run(["launchctl", "load", str(plist_path)], check=True)
        typer.echo("✅ Service started with launchctl")

    elif system == "Linux":
        # systemd service
        service_path = Path.home() / ".config" / "systemd" / "user" / "mahavishnu-sync.service"

        service_content = f"""[Unit]
Description=Mahavishnu Claude-Qwen Sync Daemon
After=network.target

[Service]
Type=simple
ExecStart={mahavishnu_bin} sync daemon
Restart=always
RestartSec=10

[Install]
WantedBy=default.target
"""
        service_path.parent.mkdir(parents=True, exist_ok=True)
        service_path.write_text(service_content)
        typer.echo(f"✅ Created systemd service: {service_path}")

        # Enable and start the service
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
        subprocess.run(["systemctl", "--user", "enable", "mahavishnu-sync.service"], check=True)
        subprocess.run(["systemctl", "--user", "start", "mahavishnu-sync.service"], check=True)
        typer.echo("✅ Service enabled and started")

    else:
        typer.echo(f"❌ Unsupported platform: {system}")
        raise typer.Exit(1)

    typer.echo("\n✅ Sync daemon installed and running!")
    typer.echo("\nManage service:")
    if system == "Darwin":
        typer.echo(f"  Stop:  launchctl unload {plist_path}")
        typer.echo(f"  Start: launchctl load {plist_path}")
    elif system == "Linux":
        typer.echo("  Stop:  systemctl --user stop mahavishnu-sync.service")
        typer.echo("  Start: systemctl --user start mahavishnu-sync.service")
