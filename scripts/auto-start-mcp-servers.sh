#!/bin/bash
# Auto-start MCP servers script for Claude Code
# This script reads the project's .mcp.json and starts local HTTP servers

set -e

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"
MCP_CONFIG="$PROJECT_DIR/.mcp.json"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log() {
    echo -e "${GREEN}[MCP Auto-Start]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[MCP Auto-Start]${NC} $1"
}

error() {
    echo -e "${RED}[MCP Auto-Start]${NC} $1"
}

# Check if .mcp.json exists
if [[ ! -f "$MCP_CONFIG" ]]; then
    warn "No .mcp.json found in $PROJECT_DIR"
    exit 0
fi

log "Starting local MCP servers for project: $PROJECT_DIR"

# Function to check if a port is in use
is_port_in_use() {
    local port=$1
    lsof -i :$port >/dev/null 2>&1
}

# Function to start server if not running
start_server_if_needed() {
    local server_name=$1
    local port=$2
    local start_command=$3
    
    if is_port_in_use $port; then
        log "$server_name already running on port $port"
    else
        log "Starting $server_name on port $port..."
        # Start in background and detach from terminal
        nohup bash -c "$start_command" > "/tmp/mcp-$server_name.log" 2>&1 &
        
        # Wait for FastMCP servers to fully initialize
        local max_wait=3
        local wait_time=0
        while [ $wait_time -lt $max_wait ]; do
            if is_port_in_use $port; then
                log "$server_name started successfully"
                return 0
            fi
            sleep 1
            wait_time=$((wait_time + 1))
        done
        
        # Check if server is actually running but startup script shows error
        if grep -q "Uvicorn running on" "/tmp/mcp-$server_name.log" 2>/dev/null; then
            log "$server_name started successfully (confirmed from logs)"
        else
            error "Failed to start $server_name (check /tmp/mcp-$server_name.log)"
        fi
    fi
}

# Ensure jq is available for parsing .mcp.json
if ! command -v jq >/dev/null 2>&1; then
    log "Installing jq for JSON parsing..."
    if command -v brew >/dev/null 2>&1; then
        brew install jq >/dev/null 2>&1
    elif command -v apt-get >/dev/null 2>&1; then
        sudo apt-get install -y jq >/dev/null 2>&1
    else
        warn "jq not found and cannot auto-install - some servers may not start"
    fi
fi

# Parse .mcp.json and start local HTTP servers
if command -v jq >/dev/null 2>&1; then
    # Extract localhost URLs and their ports
    jq -r '.mcpServers | to_entries[] | select(.value.url // "" | test("http://localhost")) | "\(.key)|\(.value.url)"' "$MCP_CONFIG" | while IFS='|' read -r server_name url; do
        port=$(echo "$url" | sed -n 's/.*localhost:\([0-9]*\).*/\1/p')
        
        case $server_name in
            "session-mgmt")
                start_server_if_needed "$server_name" "$port" "cd '$PROJECT_DIR/../session-mgmt-mcp' && .venv/bin/python -m session_mgmt_mcp.server"
                ;;
            "crackerjack")
                start_server_if_needed "$server_name" "$port" "cd '$PROJECT_DIR' && python -m crackerjack --start-mcp-server"
                ;;
            "mermaid")
                start_server_if_needed "$server_name" "$port" "npx -y mcp-mermaid -t streamable"
                ;;
            "excalidraw")
                start_server_if_needed "$server_name" "$port" "cd '$PROJECT_DIR/../excalidraw-mcp' && python -m excalidraw_mcp"
                ;;
            "raindropio")
                warn "raindropio server not implemented - please start manually"
                ;;
            "peekaboo")
                # This server is handled differently (stdio or external)
                ;;
            *)
                warn "Unknown local server: $server_name"
                ;;
        esac
    done
else
    error "jq not found - cannot parse .mcp.json automatically"
    warn "Please install jq: brew install jq"
fi

# MCP servers are now started directly via stdio (npx/uvx) by Claude Code
# or as local HTTP servers (see below). Proxy servers removed for simplicity.

log "MCP server auto-start complete"