#!/bin/bash
# Maintenance reminder for agent discovery setup

echo "======================================"
echo "  Agent Discovery Maintenance Check"
echo "======================================"
echo ""

# Check Claude Code version
echo "Claude Code Version:"
claude --version 2>/dev/null || echo "  ⚠️  Claude CLI not in PATH"
echo ""

# Check environment variable
echo "Environment Variable:"
if [ "$USE_BUILTIN_RIPGREP" = "0" ]; then
  echo "  ✅ USE_BUILTIN_RIPGREP=0 (correct)"
else
  echo "  ⚠️  USE_BUILTIN_RIPGREP not set correctly"
  echo "     Run: export USE_BUILTIN_RIPGREP=0"
fi
echo ""

# Check last sync time
SYNC_SCRIPT="$HOME/.claude/scripts/sync-agents-to-projects.sh"
if [ -f "$SYNC_SCRIPT" ]; then
  LAST_MODIFIED=$(stat -f "%Sm" -t "%Y-%m-%d %H:%M" "$SYNC_SCRIPT" 2>/dev/null || stat -c "%y" "$SYNC_SCRIPT" 2>/dev/null | cut -d' ' -f1-2)
  echo "Last Sync Script Modified: $LAST_MODIFIED"
else
  echo "  ⚠️  Sync script not found"
fi
echo ""

# Check project file counts
echo "Project Agent Counts:"
PROJECTS=("crackerjack" "acb" "session-mgmt-mcp" "fastblocks" "splashstand")
for project in "${PROJECTS[@]}"; do
  PROJECT_DIR="$HOME/Projects/$project"
  if [ -d "$PROJECT_DIR/.claude/agents" ]; then
    COUNT=$(ls -1 "$PROJECT_DIR/.claude/agents"/*.md 2>/dev/null | wc -l | tr -d ' ')
    if [ "$COUNT" = "83" ]; then
      echo "  ✅ $project: $COUNT agents"
    else
      echo "  ⚠️  $project: $COUNT agents (expected 83)"
    fi
  else
    echo "  ❌ $project: No agents directory"
  fi
done
echo ""

# Reminder
echo "======================================"
echo "Maintenance Reminders:"
echo "======================================"
echo "1. After updating global agents, run:"
echo "   bash ~/.claude/scripts/sync-agents-to-projects.sh"
echo ""
echo "2. Watch for Claude Code updates:"
echo "   https://github.com/anthropics/claude-code/releases"
echo ""
echo "3. Monitor bug fixes:"
echo "   Issue #4728, #5750, #764"
echo ""
