#!/bin/bash
# Production deployment script for Mahavishnu WebSocket ecosystem
#
# This script deploys WebSocket servers for:
# - Mahavishnu (port 8690)
# - Dhruva (port 8693)
# - Akosha (port 8692)
# - Crackerjack (port 8686)
# - Excalidraw (port 3042)
# - Fastblocks (port 8684)
#
# Usage:
#   ./scripts/deploy_websocket_servers.sh [environment]
#
# Environments:
#   development - Local development with auto-generated certificates
#   staging - Staging environment with staging certificates
#   production - Production with valid certificates

set -euo  # Exit on error

# Configuration
PROJECT_ROOT="/Users/les/Projects/mahavishnu"
VENV_PATH="$PROJECT_ROOT/.venv/bin/activate"
LOG_DIR="$PROJECT_ROOT/logs"
PID_DIR="$PROJECT_ROOT/run"
METRICS_PORT=${WEBSOCKET_METRICS_PORT:-9090}

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m' # No Color

# Logging functions
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if virtual environment exists
check_venv() {
    if [ ! -d "$VENV_PATH" ]; then
        log_error "Virtual environment not found at $VENV_PATH"
        log_error "Run: uv venv"
        exit 1
    fi
}

# Create necessary directories
create_directories() {
    log_info "Creating directories..."
    mkdir -p "$LOG_DIR"
    mkdir -p "$PID_DIR"
    mkdir -p "$PROJECT_ROOT/settings"
}

# Kill existing WebSocket servers
kill_existing_servers() {
    log_info "Stopping existing WebSocket servers..."

    # Kill by PID files
    if [ -d "$PID_DIR" ]; then
        for pid_file in "$PID_DIR"/*.pid; do
            if [ -f "$pid_file" ]; then
                pid=$(cat "$pid_file")
                if kill -0 "$pid" 2>/dev/null; then
                    log_info "Killed server (PID: $pid)"
                fi
                rm -f "$pid_file"
            fi
        done
    fi

    # Kill by port
    for port in 8690 8691 8692 8686 3042 8684; do
        pid=$(lsof -ti:"$port" -sTCP:LISTENING 2>/dev/null || echo "")
        if [ -n "$pid" ]; then
            kill -9 "$pid" 2>/dev/null
            fi
    done
}

# Start WebSocket servers
start_servers() {
    local env=${1:-development}

    log_info "Starting WebSocket servers in $env environment..."

    # Source virtual environment
    # shellcheck disable=SC1094
    source "$VENV_PATH"

    # Start Mahavishnu WebSocket server (with metrics)
    log_info "Starting Mahavishnu WebSocket server (port 8690) with metrics on port $METRICS_PORT..."
    nohup python -m mahavishnu.websocket start_metrics_server \
        --host 127.0.0.1 \
        --port 8690 \
        --metrics-port $METRICS_PORT \
        >> "$LOG_DIR/mahavishnu_websocket.log" 2>&1 &
    echo $! > "$PID_DIR/mahavishnu_websocket.pid"

    # Start other WebSocket servers (if they exist as separate services)
    # Note: Dhruva, Akosha, Crackerjack would be started via their own MCP servers

    # Wait for servers to start
    sleep 3

    # Check if servers are running
    check_servers_health
}

# Check server health
check_servers_health() {
    log_info "Checking server health..."

    sleep 2

    # Check Mahavishnu WebSocket
    if lsof -i:8690 -sTCP:LISTENING > /dev/null 2>&1; then
        log_info "✓ Mahavishnu WebSocket server running on port 8690"
    else
        log_error "✗ Mahavishnu WebSocket server NOT running on port 8690"
    fi

    # Check Prometheus metrics
    if lsof -i:$METRICS_PORT -sTCP:LISTENING > /dev/null 2>&1; then
        log_info "✓ Prometheus metrics server running on port $METRICS_PORT"
    else
        log_warn "⚠ Prometheus metrics server NOT running on port $METRICS_PORT"
    fi

    # Check other services
    for service in "Dhruva:8693" "Akosha:8692" "Crackerjack:8686" "Excalidraw:3042" "Fastblocks:8684"; do
        IFS=':' read -r name port <<< "$service"
        if lsof -i:$port -sTCP:LISTENING > /dev/null 2>&1; then
            log_info "✓ $name WebSocket server running on port $port"
        else
            log_warn "⚠ $name WebSocket server not running (port $port)"
        fi
    done
    unset IFS
}

# Show status
show_status() {
    log_info "WebSocket Server Status:"
    echo ""

    # Mahavishnu
    if [ -f "$PID_DIR/mahavishnu_websocket.pid" ]; then
        pid=$(cat "$PID_DIR/mahavishnu_websocket.pid")
        if kill -0 "$pid" 2>/dev/null; then
            echo -e "  Mahavishnu: ${GREEN}RUNNING${NC} (PID: $pid)"
        else
            echo -e "  Mahavishnu: ${RED}STOPPED${NC}"
        fi
    else
        echo -e "  Mahavishnu: ${YELLOW}NOT STARTED${NC}"
    fi

    # Prometheus metrics
    if lsof -i:$METRICS_PORT -sTCP:LISTENING > /dev/null 2>&1; then
        echo -e "  Metrics Server: ${GREEN}RUNNING${NC} (port $METRICS_PORT)"
    else
        echo -e "  Metrics Server: ${YELLOW}NOT RUNNING${NC}"
    fi

    echo ""
}

# Stop servers
stop_servers() {
    log_info "Stopping WebSocket servers..."
    kill_existing_servers
    log_info "Servers stopped"
}

# Restart servers
restart_servers() {
    log_info "Restarting WebSocket servers..."
    kill_existing_servers
    sleep 2
    start_servers
}

# Show logs
show_logs() {
    local service=${1:-mahavishnu}
    local log_file="$LOG_DIR/${service}_websocket.log"

    if [ -f "$log_file" ]; then
        tail -f "$log_file"
    else
        log_warn "No log file found: $log_file"
    fi
}

# Usage
usage() {
    cat << EOF
Usage: $0 [command] [options]

Commands:
  start [env]     Start WebSocket servers (environment: development|staging|production)
  stop            Stop all WebSocket servers
  restart         Restart all WebSocket servers
  status          Show server status
  logs [service] Show logs for service (default: mahavishnu)
  health          Check server health

Options:
  --metrics-port   Port for Prometheus metrics (default: 9090)

Examples:
  $0 start development
  $0 start production
  $0 status
  $0 logs dhruva
  $0 health

EOF
    exit 1
}

# Main script logic
main() {
    local command=${1:-start}
    local environment=${2:-development}

    case "$command" in
        start)
            check_venv
            create_directories
            kill_existing_servers
            start_servers "$environment"
            ;;
        stop)
            stop_servers
            ;;
        restart)
            restart_servers
            ;;
        status)
            show_status
            ;;
        logs)
            show_logs "$2"
            ;;
        health)
            check_servers_health
            ;;
        *)
            usage
            ;;
    esac
}

# Run main
main "$@"
