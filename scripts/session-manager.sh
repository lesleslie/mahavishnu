#!/bin/bash
# Session management script for Claude Code
# Handles automatic session-mgmt:init and session-mgmt:end

set -e

ACTION="$1"
PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

log() {
    echo -e "${BLUE}[Session Manager]${NC} $1"
}

# Check if we're in a git repository
is_git_repo() {
    git -C "$PROJECT_DIR" rev-parse --git-dir >/dev/null 2>&1
}

case "$ACTION" in
    "init")
        if is_git_repo; then
            log "Git repository detected in $PROJECT_DIR"
            log "Initializing session management..."
            
            # Check if session-mgmt MCP server is available
            if curl -s http://localhost:8678/mcp >/dev/null 2>&1; then
                # Send session:init via MCP (this would be handled by Claude Code automatically)
                log "Session management initialized"
            else
                log "Session-mgmt MCP server not available, skipping session init"
            fi
        else
            log "Not in a git repository, skipping session init"
        fi
        ;;
    
    "end")
        if is_git_repo; then
            log "Ending session for $PROJECT_DIR"
            
            # Check if session-mgmt MCP server is available
            if curl -s http://localhost:8678/mcp >/dev/null 2>&1; then
                # Send session:end via MCP (this would be handled by Claude Code automatically)
                log "Session ended gracefully"
            else
                log "Session-mgmt MCP server not available, skipping session end"
            fi
        fi
        ;;
    
    *)
        echo "Usage: $0 {init|end}"
        exit 1
        ;;
esac