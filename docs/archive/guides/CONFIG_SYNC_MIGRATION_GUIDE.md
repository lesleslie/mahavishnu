# Claude/Qwen Config Sync Migration Guide

**Date**: 2026-02-06
**Status**: ✅ Migration Complete
**Affected Feature**: Claude/Qwen configuration synchronization

---

## 📢 Migration Notice

The Claude/Qwen config sync functionality has been **migrated from Mahavishnu to Session-Buddy**.

**Why?**
- Better architectural alignment (Session-Buddy manages state across all systems)
- Resolves circular dependency with SessionBuddyPool
- Enables ubiquity (Session-Buddy runs everywhere, Mahavishnu is single-instance)

---

## 🎯 Quick Start

### Before (Mahavishnu v1.x)

```bash
# CLI command
mahavishnu sync once --direction claude-to-qwen

# Python code
from mahavishnu.sync_cli import sync_claude_to_qwen
result = sync_claude_to_qwen(sync_types=["mcp", "commands"])
```

### After (Session-Buddy MCP)

```python
# MCP tool call
result = await call_tool("sync_claude_qwen_config", {
    "source": "claude",
    "destination": "qwen",
    "sync_types": ["mcp", "commands"],
    "skip_servers": ["homebrew", "pycharm"]
})
```

---

## 📋 Migration Steps

### Step 1: Ensure Session-Buddy is Running

```bash
# Start Session-Buddy MCP server
cd /path/to/session-buddy
python -m session_buddy.mcp.server

# Or via systemd/service
systemctl start session-buddy
systemctl enable session-buddy  # Auto-start on boot
```

### Step 2: Update Your Code

**Option A: Python Scripts**

```python
# Old code
from mahavishnu.sync_cli import sync_claude_to_qwen

def sync_configs():
    result = sync_claude_to_qwen(
        sync_types=["mcp", "commands"],
        skip_servers=["homebrew", "pycharm"]
    )
    return result

# New code
import asyncio
from your_mcp_client import call_tool

async def sync_configs():
    result = await call_tool("sync_claude_qwen_config", {
        "source": "claude",
        "destination": "qwen",
        "sync_types": ["mcp", "commands"],
        "skip_servers": ["homebrew", "pycharm"]
    })
    return result

# Usage
asyncio.run(sync_configs())
```

**Option B: CLI Workflows**

```bash
# Old command (deprecated, will show warning)
mahavishnu sync once

# New approach: Use Session-Buddy MCP tool directly
# Option 1: Via MCP client
echo '{"source": "claude", "destination": "qwen"}' | \
  mcp-client call sync_claude_qwen_config

# Option 2: Via Python script
python sync_configs.py
```

**Option C: Automated Scripts**

```python
# Old: Cron job or scheduled task
# 0 */6 * * * cd /path/to/mahavishnu && mahavishnu sync once

# New: Python script with MCP client
#!/usr/bin/env python3
import asyncio
from mcp_client import MCPClient

async def main():
    client = MCPClient("session-buddy")
    result = await client.call_tool("sync_claude_qwen_config", {
        "source": "claude",
        "destination": "qwen",
        "sync_types": ["all"]
    })
    print(result)

asyncio.run(main())

# Update cron job
# 0 */6 * * * /path/to/sync_configs.py
```

### Step 3: Update Dependencies

**requirements.txt**:
```
# Old (no change needed, but sync will show deprecation warning)
mahavishnu>=1.0.0

# New (ensure Session-Buddy is available)
session-buddy>=1.0.0
mcp-common>=1.0.0
```

### Step 4: Verify Migration

```python
# Test script to verify sync works
import asyncio
from mcp_client import MCPClient

async def test_sync():
    client = MCPClient("session-buddy")

    # Test Claude → Qwen
    result = await client.call_tool("sync_claude_qwen_config", {
        "source": "claude",
        "destination": "qwen",
        "sync_types": ["mcp"]
    })

    print("Sync result:", result)

    # Check for errors
    if "errors" in result and result["errors"]:
        print("ERRORS:", result["errors"])
        return False

    print("✅ Sync successful!")
    return True

asyncio.run(test_sync())
```

---

## 🔧 MCP Tool Specification

### Tool: `sync_claude_qwen_config`

**Description**: Sync Claude and Qwen provider configurations with bidirectional support.

**Parameters**:

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `source` | string | No | "claude" | Source config ("claude" or "qwen") |
| `destination` | string | No | "qwen" | Destination config ("claude" or "qwen") |
| `sync_types` | list[string] | No | ["mcp", "extensions", "commands"] | Types to sync |
| `skip_servers` | list[string] | No | ["homebrew", "pycharm"] | MCP servers to skip |

**Sync Types**:
- `"mcp"`: MCP servers (JSON dict merge)
- `"commands"`: File-based commands (convert formats)
- `"extensions"`: Plugins/extensions (tracking only, manual install)
- `"all"`: Sync all types

**Returns**:
```json
{
  "mcp_servers": 10,
  "mcp_servers_skipped": 2,
  "commands_synced": 5,
  "plugins_found": 3,
  "errors": []
}
```

---

## 📊 Feature Comparison

| Feature | Mahavishnu (Old) | Session-Buddy (New) |
|---------|------------------|---------------------|
| MCP server sync | ✅ | ✅ |
| Command sync | ✅ | ✅ |
| Extension tracking | ✅ | ✅ |
| Bidirectional sync | ✅ | ✅ |
| Skip servers | ✅ | ✅ |
| Daemon mode | ✅ | ⚠️ (use external scheduler) |
| File watcher | ✅ | ⚠️ (use external scheduler) |
| Installation service | ✅ | ⚠️ (use systemd/launchd) |

**Notes**:
- ⚠️ Daemon mode: Use cron, systemd timer, or external scheduler
- ⚠️ File watcher: Use watchdog with cron or inotify
- ⚠️ Installation service: Use native service managers (systemd, launchd)

---

## 🔄 Scheduling Automated Syncs

### Option 1: Cron (Linux/macOS)

```cron
# Sync every 6 hours
0 */6 * * * /path/to/sync_configs.py >> /var/log/sync.log 2>&1
```

### Option 2: systemd Timer (Linux)

```ini
# /etc/systemd/system/sync-claude-qwen.service
[Unit]
Description=Sync Claude and Qwen configs
After=network.target

[Service]
Type=oneshot
ExecStart=/path/to/sync_configs.py
User=your-user

[Install]
WantedBy=multi-user.target
```

```ini
# /etc/systemd/system/sync-claude-qwen.timer
[Unit]
Description=Sync Claude and Qwen configs every 6 hours

[Timer]
OnCalendar=*:0/6
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
# Enable and start
systemctl enable sync-claude-qwen.timer
systemctl start sync-claude-qwen.timer
```

### Option 3: Launchd (macOS)

```xml
<!-- ~/Library/LaunchAgents/com.user.sync-claude-qwen.plist -->
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.user.sync-claude-qwen</string>
    <key>ProgramArguments</key>
    <array>
        <string>/path/to/sync_configs.py</string>
    </array>
    <key>StartInterval</key>
    <integer>21600</integer> <!-- 6 hours -->
    <key>RunAtLoad</key>
    <true/>
</dict>
</plist>
```

```bash
# Load the job
launchctl load ~/Library/LaunchAgents/com.user.sync-claude-qwen.plist
```

---

## ⚠️ Common Issues & Solutions

### Issue 1: Session-Buddy MCP Not Available

**Error**: `Session-Buddy MCP client not available`

**Solution**:
```bash
# Install dependencies
pip install session-buddy mcp-common

# Start Session-Buddy
python -m session_buddy.mcp.server
```

### Issue 2: Import Errors in Deprecated Wrapper

**Error**: `ImportError: cannot import name 'add_sync_commands'`

**Solution**: Update imports from `sync_cli` to `sync_deprecated`:
```python
# Old
from mahavishnu.sync_cli import add_sync_commands

# New
from mahavishnu.sync_deprecated import add_sync_commands
```

### Issue 3: Deprecation Warnings

**Warning**: `DeprecationWarning: Config sync is deprecated in Mahavishnu`

**Solution**: This is expected. Migrate to Session-Buddy MCP tool as shown above.

### Issue 4: Sync Skips All Servers

**Issue**: All MCP servers are being skipped

**Solution**: Check your `skip_servers` parameter:
```python
# Wrong - skips everything
result = await call_tool("sync_claude_qwen_config", {
    "skip_servers": ["*"]  # ❌ Don't use wildcards
})

# Correct - skip only specific servers
result = await call_tool("sync_claude_qwen_config", {
    "skip_servers": ["homebrew", "pycharm"]  # ✅ Specific servers
})

# Or skip nothing
result = await call_tool("sync_claude_qwen_config", {
    "skip_servers": []  # ✅ Empty list = sync all
})
```

---

## 📚 Additional Resources

- **Session-Buddy Documentation**: https://github.com/your-repo/session-buddy
- **MCP Protocol**: https://modelcontextprotocol.io
- **Migration Plan**: `/Users/les/Projects/mahavishnu/docs/CONFIG_SYNC_MIGRATION_PLAN.md`
- **Architecture Discussion**: See multi-agent review in migration plan

---

## 🤝 Support

If you encounter issues during migration:

1. Check Session-Buddy logs: `journalctl -u session-buddy -f`
2. Enable verbose logging: Set `RUST_LOG=debug` for MCP client
3. Test MCP connection: Use MCP Inspector to verify tools are registered
4. Open an issue: https://github.com/your-repo/mahavishnu/issues

---

## ⏰ Deprecation Timeline

| Version | Date | Status |
|---------|------|--------|
| v1.0.0 | 2026-02-06 | ✅ Migration complete |
| v1.1.x | 2026-03-01 | ⏳ Deprecation warnings active |
| v1.2.x | 2026-04-01 | ⏳ Soft removal (wrapper still available) |
| v2.0.0 | 2026-06-01 | 🔴 Hard removal (wrapper deleted) |

**Migration Deadline**: 2026-06-01 (v2.0.0 release)

---

## ✅ Migration Checklist

- [ ] Ensure Session-Buddy is installed and running
- [ ] Update Python scripts to use MCP tool
- [ ] Update CLI workflows to use MCP tool
- [ ] Update automated sync jobs (cron/systemd)
- [ ] Test sync in development environment
- [ ] Deploy to production
- [ ] Monitor logs for errors
- [ ] Remove old `mahavishnu sync` commands from scripts
- [ ] Update documentation for your team
- [ ] Plan for v2.0.0 removal

---

**Last Updated**: 2026-02-06
**Migration Status**: ✅ Complete
**Questions?**: Open an issue or consult Session-Buddy documentation
