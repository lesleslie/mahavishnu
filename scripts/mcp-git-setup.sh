#!/bin/bash
# MCP Git Auto-Setup Helper
# This script reads the stored git working directory and provides setup instructions

set -e

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log() {
    echo -e "${GREEN}[MCP Git Setup]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[MCP Git Setup]${NC} $1"
}

info() {
    echo -e "${BLUE}[MCP Git Setup]${NC} $1"
}

# Check if working directory file exists
WORKING_DIR_FILE="/tmp/claude-git-working-dir"

if [[ -f "$WORKING_DIR_FILE" ]]; then
    PROJECT_DIR=$(cat "$WORKING_DIR_FILE")
    log "Auto-detected git project: $PROJECT_DIR"

    # Validate it's still a git repo
    if [[ -d "$PROJECT_DIR/.git" ]]; then
        info "✅ Git repository confirmed at: $PROJECT_DIR"
        info "🔧 To configure git MCP server, run this in Claude Code:"
        echo
        echo "mcp__git__git_set_working_dir(path=\"$PROJECT_DIR\", validateGitRepo=true)"
        echo
        info "Or copy this path: $PROJECT_DIR"
    else
        warn "⚠️ Directory is no longer a git repository: $PROJECT_DIR"
    fi
else
    warn "No auto-detected git directory found"
    info "💡 Either:"
    info "   1. Run your auto-start script first: ~/.claude/scripts/auto-start-mcp-servers.sh"
    info "   2. Manually set working directory in Claude Code:"
    echo
    echo "mcp__git__git_set_working_dir(path=\"$(pwd)\", validateGitRepo=true)"
    echo
fi

# Show current directory for reference
info "Current directory: $(pwd)"

# Check if current directory is a git repo
if [[ -d "$(pwd)/.git" ]]; then
    info "✅ Current directory is a git repository"
    info "🔧 To use current directory with git MCP server:"
    echo
    echo "mcp__git__git_set_working_dir(path=\"$(pwd)\", validateGitRepo=true)"
    echo
else
    info "ℹ️ Current directory is not a git repository"
fi