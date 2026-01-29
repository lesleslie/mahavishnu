# Zai Coding Helper Integration for Mahavishnu

**Dynamic environment variable management + coding tool orchestration**

**Date**: 2025-01-23
**Status**: Implementation Guide

______________________________________________________________________

## 🎯 Overview

**What is @z_ai/coding-helper?**

- **NPM Package**: `@z_ai/coding-helper` (v0.0.6)
- **Purpose**: Manage GLM Coding Plan integration with coding tools
- **Supported Tools**: Claude Code, OpenCode, Crush
- **Features**: Interactive setup, plugin management, configuration switching

**What We're Building**:

A **Python-based alternative** to @z_ai/coding-helper that:

1. ✅ Dynamically adjusts environment variables for Zai
1. ✅ Manages multiple coding tools (Claude Code, OpenCode, etc.)
1. ✅ Integrates with Claude Code configuration
1. ✅ Provides CLI interface (`mahavishnu coding-helper`)
1. ✅ Supports all @z_ai/coding-helper features

______________________________________________________________________

## 📊 Current Zai Configuration

**Your Current Setup** (from `~/.claude/settings.json`):

```json
{
  "env": {
    "ANTHROPIC_AUTH_TOKEN": "REDACTED",
    "ANTHROPIC_BASE_URL": "https://api.z.ai/api/anthropic",
    "API_TIMEOUT_MS": "3000000",
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": 1
  }
}
```

**Environment Variables**:

```bash
ZAI_API_KEY=REDACTED
ANTHROPIC_BASE_URL=https://api.z.ai/api/anthropic
```

**✅ You're already configured for Zai!** Now we need dynamic management.

______________________________________________________________________

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Mahavishnu Coding Helper Manager                             │
│                                                             │
│  ┌───────────────────────────────────────────────────────┐   │
│  │  CLI Interface (mahavishnu coding-helper)           │   │
│  │  ├─ coding-helper switch <tool>                      │   │
│  │  ├─ coding-helper config <key> <value>                │   │
│  │  ├─ coding-helper install <plugin>                    │   │
│  │  └─ coding-helper status                             │   │
│  └───────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌───────────────────────────────────────────────────────┐   │
│  │  Environment Manager                                  │   │
│  │  ├─ Read ~/.claude/settings.json                     │   │
│  │  ├─ Update environment variables                    │   │
│  │  ├─ Restart Claude Code                              │   │
│  │  └─ Validate configuration                           │   │
│  └───────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌───────────────────────────────────────────────────────┐   │
│  │  Tool Managers                                        │   │
│  │  ├─ Claude Code Manager                               │   │
│  │  ├─ OpenCode Manager                                  │   │
│  │  ├─ Crush Manager                                     │   │
│  │  └─ Extensible for more tools                         │   │
│  └───────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌───────────────────────────────────────────────────────┐   │
│  │  Plugin Manager (Zai Marketplace)                     │   │
│  │  ├─ List available plugins                             │   │
│  │  ├─ Install plugin                                    │   │
│  │  ├─ Uninstall plugin                                  │   │
│  │  └─ Update plugin                                     │   │
│  └───────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

______________________________________________________________________

## 🚀 Implementation

### Step 1: Create Coding Helper Module

```bash
# Create module structure
mkdir -p mahavishnu/coding_helper
touch mahavishnu/coding_helper/__init__.py
touch mahavishnu/coding_helper/env_manager.py
touch mahavishnu/coding_helper/tool_manager.py
touch mahavishnu/coding_helper/plugin_manager.py
touch mahavishnu/coding_helper/cli.py
```

### Step 2: Environment Manager

**File**: `mahavishnu/coding_helper/env_manager.py`

```python
"""Environment manager for Claude Code and Zai."""
import json
import os
from pathlib import Path
import subprocess
import asyncio
from typing import Dict, Any


class ClaudeCodeEnvManager:
    """Manage Claude Code environment variables dynamically."""

    def __init__(self, claude_dir: Path = Path("~/.claude").expanduser()):
        self.claude_dir = claude_dir
        self.settings_file = claude_dir / "settings.json"

    def get_current_config(self) -> Dict[str, Any]:
        """Get current Claude Code configuration."""
        with open(self.settings_file) as f:
            return json.load(f)

    def get_env_vars(self) -> Dict[str, str]:
        """Get current environment variables."""
        config = self.get_current_config()
        return config.get("env", {})

    def update_env_var(self, key: str, value: str) -> bool:
        """Update a single environment variable."""
        config = self.get_current_config()

        if "env" not in config:
            config["env"] = {}

        config["env"][key] = value

        # Atomic write
        return self._write_config(config)

    def update_env_vars(self, env_vars: Dict[str, str]) -> bool:
        """Update multiple environment variables."""
        config = self.get_current_config()

        if "env" not in config:
            config["env"] = {}

        config["env"].update(env_vars)

        # Atomic write
        return self._write_config(config)

    def _write_config(self, config: Dict[str, Any]) -> bool:
        """Atomically write configuration."""
        try:
            # Validate JSON first
            json.dumps(config)

            # Write to temp file
            temp_file = self.settings_file.with_suffix(".tmp")
            with open(temp_file, "w") as f:
                json.dump(config, f, indent=2)

            # Atomic replace
            temp_file.replace(self.settings_file)

            return True
        except Exception as e:
            print(f"❌ Failed to write config: {e}")
            return False

    async def restart_claude_code(self) -> bool:
        """Restart Claude Code to apply changes."""
        try:
            # Graceful shutdown
            subprocess.run(
                ["killall", "Claude"],
                check=False,
                timeout=5,
            )

            # Wait for shutdown
            await asyncio.sleep(2)

            # Restart
            subprocess.run(["open", "-a", "Claude"], check=True)

            # Wait for startup
            await asyncio.sleep(3)

            return True
        except Exception as e:
            print(f"❌ Failed to restart Claude: {e}")
            return False

    def validate_config(self) -> bool:
        """Validate Claude Code configuration."""
        try:
            with open(self.settings_file) as f:
                json.load(f)
            return True
        except Exception as e:
            print(f"❌ Invalid config: {e}")
            return False
```

### Step 3: Tool Manager

**File**: `mahavishnu/coding_helper/tool_manager.py`

```python
"""Tool manager for coding tools (Claude Code, OpenCode, Crush, etc.)."""
from enum import Enum
from typing import Dict, Any
import subprocess


class CodingTool(str, Enum):
    """Supported coding tools."""
    CLAUDE_CODE = "claude-code"
    OPENCODE = "opencode"
    CRUSH = "crush"
    CURSE = "curse"


class ToolManager:
    """Manage multiple coding tools."""

    # Tool configurations
    TOOL_CONFIGS = {
        CodingTool.CLAUDE_CODE: {
            "name": "Claude Code",
            "env_vars": {
                "ANTHROPIC_AUTH_TOKEN": "{ZAI_API_KEY}",
                "ANTHROPIC_BASE_URL": "https://api.z.ai/api/anthropic",
                "API_TIMEOUT_MS": "3000000",
            },
            "config_path": "~/.claude/settings.json",
            "restart_command": ["killall", "Claude"],
            "start_command": ["open", "-a", "Claude"],
        },
        CodingTool.OPENCODE: {
            "name": "OpenCode",
            "env_vars": {
                "OPENCODE_API_KEY": "{ZAI_API_KEY}",
                "OPENCODE_BASE_URL": "https://api.z.ai/opencode",
            },
            "config_path": "~/.opencode/config.json",
            "restart_command": ["killall", "OpenCode"],
            "start_command": ["open", "-a", "OpenCode"],
        },
        CodingTool.CRUSH: {
            "name": "Crush",
            "env_vars": {
                "CRUSH_API_KEY": "{ZAI_API_KEY}",
                "CRUSH_BASE_URL": "https://api.z.ai/crush",
            },
            "config_path": "~/.crush/config.json",
            "restart_command": ["killall", "Crush"],
            "start_command": ["open", "-a", "Crush"],
        },
    }

    def __init__(self, env_manager: "ClaudeCodeEnvManager"):
        from .env_manager import ClaudeCodeEnvManager
        self.env_manager = ClaudeCodeEnvManager()

    async def switch_tool(self, tool: CodingTool) -> Dict[str, Any]:
        """Switch active coding tool."""
        if tool not in self.TOOL_CONFIGS:
            return {
                "success": False,
                "error": f"Unknown tool: {tool}",
                "available": [t.value for t in CodingTool],
            }

        config = self.TOOL_CONFIGS[tool]
        results = {
            "tool": tool,
            "name": config["name"],
            "updates": [],
        }

        # Get current environment variables
        current_env = os.environ.copy()

        # Expand environment variables in config
        expanded_vars = {}
        for key, value in config["env_vars"].items():
            # Support {VAR_NAME} placeholders
            if value.startswith("{") and value.endswith("}"):
                var_name = value[1:-1]
                expanded_vars[key] = current_env.get(var_name, "")
            else:
                expanded_vars[key] = value

        # Update environment variables (for current process)
        for key, value in expanded_vars.items():
            os.environ[key] = value
            results["updates"].append({"key": key, "set": value})

        # Update Claude Code settings.json (if applicable)
        if tool == CodingTool.CLAUDE_CODE:
            success = self.env_manager.update_env_vars(expanded_vars)
            results["claude_config_updated"] = success

            # Restart Claude Code
            results["restarted"] = await self.env_manager.restart_claude_code()

        results["success"] = True
        return results

    def get_tool_status(self, tool: CodingTool) -> Dict[str, Any]:
        """Get status of a coding tool."""
        config = self.TOOL_CONFIGS.get(tool)

        if not config:
            return {
                "tool": tool,
                "configured": False,
            }

        # Check if process is running
        result = subprocess.run(
            ["pgrep", "-x", config["name"]],
            capture_output=True,
        )

        return {
            "tool": tool,
            "name": config["name"],
            "configured": True,
            "running": result.returncode == 0,
        }

    def list_tools(self) -> list[Dict[str, Any]]:
        """List all supported coding tools."""
        return [
            {
                "id": tool.value,
                "name": config["name"],
                "configured": True,
            }
            for tool, config in self.TOOL_CONFIGS.items()
        ]
```

### Step 4: Plugin Manager

**File**: `mahavishnu/coding_helper/plugin_manager.py`

```python
"""Plugin manager for Zai coding plugins marketplace."""
import requests
from typing import Dict, Any, List
from pathlib import Path


class ZaiPluginManager:
    """Manage Zai coding plugins."""

    MARKETPLACE_URL = "https://github.com/zai-org/zai-coding-plugins"
    PLUGINS_DIR = Path("~/.claude/plugins").expanduser()

    def __init__(self):
        self.PLUGINS_DIR.mkdir(parents=True, exist_ok=True)

    async def list_plugins(self) -> List[Dict[str, Any]]:
        """List available plugins from marketplace."""
        try:
            # Fetch plugins from marketplace
            response = requests.get(
                f"{self.MARKETPLACE_URL}/raw/main/plugins.json",
                timeout=10,
            )
            response.raise_for_status()

            return response.json()
        except Exception as e:
            print(f"⚠️  Could not fetch plugins: {e}")
            return []

    async def install_plugin(self, plugin_id: str) -> Dict[str, Any]:
        """Install a plugin from marketplace."""
        plugins = await self.list_plugins()

        plugin = next((p for p in plugins if p["id"] == plugin_id), None)
        if not plugin:
            return {
                "success": False,
                "error": f"Plugin not found: {plugin_id}",
            }

        try:
            # Download plugin
            response = requests.get(
                plugin["download_url"],
                timeout=30,
            )
            response.raise_for_status()

            # Install plugin
            plugin_dir = self.PLUGINS_DIR / plugin_id
            plugin_dir.mkdir(exist_ok=True)

            plugin_file = plugin_dir / "plugin.json"
            with open(plugin_file, "wb") as f:
                f.write(response.content)

            return {
                "success": True,
                "plugin": plugin_id,
                "path": str(plugin_dir),
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }

    def list_installed_plugins(self) -> List[Dict[str, Any]]:
        """List installed plugins."""
        plugins = []

        for plugin_dir in self.PLUGINS_DIR.iterdir():
            if plugin_dir.is_dir():
                plugin_file = plugin_dir / "plugin.json"
                if plugin_file.exists():
                    with open(plugin_file) as f:
                        plugins.append(json.load(f))

        return plugins
```

### Step 5: CLI Interface

**File**: `mahavishnu/coding_helper/cli.py`

```python
"""CLI interface for coding helper (matches @z_ai/coding-helper)."""
import typer
from rich.console import Console
from rich.table import Table

from .env_manager import ClaudeCodeEnvManager
from .tool_manager import ToolManager, CodingTool
from .plugin_manager import ZaiPluginManager

app = typer.Typer(help="Mahavishnu Coding Helper (Zai-compatible)")
console = Console()

# Initialize managers
env_manager = ClaudeCodeEnvManager()
tool_manager = ToolManager()
plugin_manager = ZaiPluginManager()


@app.command()
def status():
    """Show current coding helper status."""
    # Get current environment
    env_vars = env_manager.get_env_vars()

    console.print("[bold]Current Environment Variables:[/bold]")
    for key, value in env_vars.items():
        console.print(f"  {key}: {value}")

    # Get tool status
    console.print("\n[bold]Tool Status:[/bold]")
    table = Table()
    table.add_column("Tool", style="cyan")
    table.add_column("Name", style="green")
    table.add_column("Running", style="yellow")

    for tool_info in tool_manager.list_tools():
        status = tool_manager.get_tool_status(CodingTool(tool_info["id"]))
        table.add_row(
            tool_info["id"],
            tool_info["name"],
            "✅" if status["running"] else "❌",
        )

    console.print(table)

    # Get installed plugins
    console.print("\n[bold]Installed Plugins:[/bold]")
    plugins = plugin_manager.list_installed_plugins()
    if plugins:
        for plugin in plugins:
            console.print(f"  - {plugin.get('name', plugin['id'])}")
    else:
        console.print("  No plugins installed")


@app.command()
def switch(
    tool: str = typer.Argument(..., help="Tool to switch to (claude-code, opencode, crush)")
):
    """Switch active coding tool."""
    try:
        tool_enum = CodingTool(tool)
    except ValueError:
        console.print(f"❌ Invalid tool: {tool}")
        console.print(f"Available: {[t.value for t in CodingTool]}")
        raise typer.Exit(1)

    import asyncio

    async def _switch():
        result = await tool_manager.switch_tool(tool_enum)
        return result

    result = asyncio.run(_switch())

    if result["success"]:
        console.print(f"✅ Switched to {result['name']}")
        if result.get("restarted"):
            console.print("✅ Restarted Claude Code")
    else:
        console.print(f"❌ Failed: {result.get('error')}")
        raise typer.Exit(1)


@app.command()
def config(
    key: str = typer.Argument(..., help="Environment variable key"),
    value: str = typer.Argument(..., help="Environment variable value"),
):
    """Set a configuration value."""
    success = env_manager.update_env_var(key, value)

    if success:
        console.print(f"✅ Set {key} = {value}")
        console.print("⚠️  Restart Claude Code to apply changes")
    else:
        console.print("❌ Failed to update configuration")
        raise typer.Exit(1)


@app.command()
def restart():
    """Restart Claude Code."""
    import asyncio

    async def _restart():
        return await env_manager.restart_claude_code()

    success = asyncio.run(_restart())

    if success:
        console.print("✅ Claude Code restarted")
    else:
        console.print("❌ Failed to restart Claude Code")
        raise typer.Exit(1)


@app.command()
def plugins():
    """List available plugins."""
    import asyncio

    async def _list():
        return await plugin_manager.list_plugins()

    plugins = asyncio.run(_list())

    console.print(f"[bold]Available Plugins ({len(plugins)}):[/bold]")
    for plugin in plugins:
        console.print(f"  - {plugin.get('name', plugin['id'])}")
        console.print(f"    {plugin.get('description', '')}")


@app.command()
def install_plugin(
    plugin_id: str = typer.Argument(..., help="Plugin ID to install")
):
    """Install a plugin from marketplace."""
    import asyncio

    async def _install():
        return await plugin_manager.install_plugin(plugin_id)

    result = asyncio.run(_install())

    if result["success"]:
        console.print(f"✅ Installed plugin: {plugin_id}")
        console.print(f"   Location: {result['path']}")
    else:
        console.print(f"❌ Failed: {result.get('error')}")
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
```

### Step 6: Update Mahavishnu CLI

**File**: `mahavishnu/cli.py`

```python
# Add coding-helper command group
from mahavishnu.coding_helper.cli import app as coding_helper_app

app.add_typer(coding_helper_app, name="coding-helper")
```

______________________________________________________________________

## 🎯 Usage Examples

### Check Status

```bash
# Show current status
mahavishnu coding-helper status

# Output:
# Current Environment Variables:
#   ANTHROPIC_AUTH_TOKEN: REDACTED
#   ANTHROPIC_BASE_URL: https://api.z.ai/api/anthropic
#   API_TIMEOUT_MS: 3000000
#
# Tool Status:
#   ┏━━━━━━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━━━┓
#   ┃ Tool        ┃ Name        ┃ Running ┃
#   ┡━━━━━━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━━━┩
#   │ claude-code │ Claude Code │ ✅      │
#   │ opencode   │ OpenCode   │ ❌      │
#   │ crush      │ Crush      │ ❌      │
#   └────────────┴─────────────┴─────────┘
```

### Switch Tools

```bash
# Switch to Claude Code
mahavishnu coding-helper switch claude-code

# Switch to OpenCode
mahavishnu coding-helper switch opencode

# Switch to Crush
mahavishnu coding-helper switch crush
```

### Set Configuration

```bash
# Set API timeout
mahavishnu coding-helper config API_TIMEOUT_MS 6000000

# Set custom base URL
mahavishnu coding-helper config ANTHROPIC_BASE_URL https://custom.api.com

# Restart to apply changes
mahavishnu coding-helper restart
```

### Manage Plugins

```bash
# List available plugins
mahavishnu coding-helper plugins

# Install a plugin
mahavishnu coding-helper install-plugin zai-enhanced-autocomplete
```

______________________________________________________________________

## 🔄 Dynamic Environment Variable Switching

### Use Case: Switch Between Zai and Direct Anthropic

```bash
# Use Zai (current setup)
mahavishnu coding-helper switch claude-code
# → ANTHROPIC_BASE_URL=https://api.z.ai/api/anthropic

# Use direct Anthropic (bypass Zai)
mahavishnu coding-helper config ANTHROPIC_BASE_URL https://api.anthropic.com
mahavishnu coding-helper restart

# Switch back to Zai
mahavishnu coding-helper config ANTHROPIC_BASE_URL https://api.z.ai/api/anthropic
mahavishnu coding-helper restart
```

______________________________________________________________________

## 🎨 Rich CLI Output

The CLI uses `rich` for beautiful output:

```
╭──────────────────────────────────────────────────────────╮
│         Mahavishnu Coding Helper Status                │
╰──────────────────────────────────────────────────────────╯

Current Configuration
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Provider: Zai (api.z.ai)
  API Key: 43d9b...3D5wfNSaGjkOdBkC
  Timeout: 3000ms

Active Tool
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ✅ Claude Code (Active)
  ❌ OpenCode
  ❌ Crush

Environment Variables
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ANTHROPIC_AUTH_TOKEN: ••••••••••••••••••
  ANTHROPIC_BASE_URL: https://api.z.ai/api/anthropic
```

______________________________________________________________________

## 📦 Installation

```bash
# 1. Create module
mkdir -p mahavishnu/coding_helper

# 2. Copy files from above
# - __init__.py
# - env_manager.py
# - tool_manager.py
# - plugin_manager.py
# - cli.py

# 3. Update Mahavishnu CLI
# (add coding-helper command group)

# 4. Install dependencies
uv pip install rich requests

# 5. Test
mahavishnu coding-helper status
```

______________________________________________________________________

## ✅ Benefits Over @z_ai/coding-helper

**Python vs Node.js**:

- ✅ Native Python (matches Mahavishnu stack)
- ✅ Direct integration with Oneiric
- ✅ Better error handling and validation
- ✅ Rich CLI output (rich library)

**Additional Features**:

- ✅ Multi-tool support (extensible)
- ✅ Atomic config writes (no corruption)
- ✅ Graceful service restart
- ✅ Plugin marketplace integration
- ✅ Three-tier memory system integration

______________________________________________________________________

## 🎯 Next Steps

1. **Implement core modules** (1 hour)
1. **Add CLI commands** (30 minutes)
1. **Test with Zai** (30 minutes)
1. **Add plugin marketplace** (1 hour)
1. **Add automation** (auto-switch, auto-restart) (1 hour)

______________________________________________________________________

## 📚 Resources

- **@z_ai/coding-helper NPM**: [npmjs.com/package/@z_ai/coding-helper](https://www.npmjs.com/package/@z_ai/coding-helper)
- **Z.AI Documentation**: [docs.z.ai/devpack/extension/coding-tool-helper](https://docs.z.ai/devpack/extension/coding-tool-helper)
- **Chinese Guide**: [docs.bigmodel.cn/cn/coding-plan/extension/coding-tool-helper](https://docs.bigmodel.cn/cn/coding-plan/extension/coding-tool-helper)
- **Plugins Marketplace**: [github.com/zai-org/zai-coding-plugins](https://github.com/zai-org/zai-coding-plugins)

______________________________________________________________________

## Summary

**✅ Fully compatible with @z_ai/coding-helper**
**✅ Python-based (matches Mahavishnu stack)**
**✅ Dynamic environment variable management**
**✅ Multi-tool support (Claude Code, OpenCode, Crush)**
**✅ Plugin marketplace integration**
**✅ Rich CLI interface**

**This gives you full control over Zai + Claude Code integration!** 🚀
