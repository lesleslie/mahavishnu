#!/bin/bash
# MCP Git Auto-Initialization
# This runs automatically to set git working directory

WORKING_DIR_FILE="/tmp/claude-git-working-dir"

# Function to set git working directory automatically
auto_init_git_mcp() {
    local target_dir=""

    # Priority 1: Use stored directory from auto-start script
    if [[ -f "$WORKING_DIR_FILE" ]]; then
        target_dir=$(cat "$WORKING_DIR_FILE" | tr -d '\n')
    fi

    # Priority 2: Use current directory if it's a git repo
    if [[ -z "$target_dir" ]] && [[ -d "$(pwd)/.git" ]]; then
        target_dir="$(pwd)"
        echo "$target_dir" > "$WORKING_DIR_FILE"
    fi

    # Priority 3: Search for git repos in common project locations
    if [[ -z "$target_dir" ]]; then
        for proj_dir in "/Users/les/Projects"/*; do
            if [[ -d "$proj_dir/.git" ]]; then
                target_dir="$proj_dir"
                echo "$target_dir" > "$WORKING_DIR_FILE"
                break
            fi
        done
    fi

    # If we found a git directory, return the setup command
    if [[ -n "$target_dir" ]] && [[ -d "$target_dir/.git" ]]; then
        echo "AUTO_SETUP_PATH:$target_dir"
        return 0
    fi

    return 1
}

# Execute and return result
auto_init_git_mcp
