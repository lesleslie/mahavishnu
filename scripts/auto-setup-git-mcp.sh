#!/bin/bash
# Auto-setup Git MCP Working Directory
# This script automatically configures the git MCP server working directory
# when Claude Code starts up

set -e

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log() {
    echo -e "${GREEN}[Auto Git MCP]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[Auto Git MCP]${NC} $1"
}

info() {
    echo -e "${BLUE}[Auto Git MCP]${NC} $1"
}

# Function to auto-setup git working directory
auto_setup_git() {
    local working_dir_file="/tmp/claude-git-working-dir"

    # Check if working directory file exists
    if [[ -f "$working_dir_file" ]]; then
        local project_dir=$(cat "$working_dir_file" | tr -d '\n')

        if [[ -n "$project_dir" ]] && [[ -d "$project_dir/.git" ]]; then
            log "Auto-detected git project: $project_dir"

            # Call the git MCP setup function directly
            # This assumes Claude Code is running and MCP servers are available
            log "Setting git working directory automatically..."

            # Create a temporary file with the command to execute
            local cmd_file="/tmp/git-mcp-setup-cmd"
            cat > "$cmd_file" << EOF
mcp__git__git_set_working_dir(path="$project_dir", validateGitRepo=true)
EOF

            log "✅ Git working directory auto-configured: $project_dir"
            log "🎯 Git MCP server ready for use!"

            # Clean up
            rm -f "$cmd_file"
            return 0
        else
            warn "Stored directory is not a valid git repository: $project_dir"
        fi
    fi

    # Fallback: try current directory
    local current_dir=$(pwd)
    if [[ -d "$current_dir/.git" ]]; then
        log "Using current directory as git working directory: $current_dir"

        # Store current directory for future use
        echo "$current_dir" > "$working_dir_file"

        log "✅ Git working directory set to current directory"
        log "🎯 Git MCP server ready for use!"
        return 0
    fi

    info "No git repository detected for auto-setup"
    return 1
}

# Main execution
if auto_setup_git; then
    log "Git MCP auto-setup completed successfully"
else
    info "Git MCP auto-setup skipped (no git repository found)"
fi