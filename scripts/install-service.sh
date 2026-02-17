#!/usr/bin/env bash
# Installation script for Mahavishnu auto-restart configuration
#
# Usage:
#   sudo ./scripts/install-service.sh [systemd|supervisord]
#
# This script installs Mahavishnu as a system service with auto-restart.

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
SERVICE_NAME="mahavishnu"
INSTALL_DIR="${INSTALL_DIR:-/opt/mahavishnu}"
USER="${USER:-mahavishnu}"
GROUP="${GROUP:-mahavishnu}"
MANAGER="${1:-systemd}"

# Functions
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

check_root() {
    if [[ $EUID -ne 0 ]]; then
        log_error "This script must be run as root (use sudo)"
        exit 1
    fi
}

create_user() {
    log_info "Creating user and group: $USER:$GROUP"

    if ! id "$USER" &>/dev/null; then
        useradd -r -s /bin/false -d "$INSTALL_DIR" "$USER"
        log_info "User $USER created"
    else
        log_info "User $USER already exists"
    fi
}

create_directories() {
    log_info "Creating directories"

    mkdir -p "$INSTALL_DIR"
    mkdir -p "/var/log/$SERVICE_NAME"
    mkdir -p "/var/run/$SERVICE_NAME"

    chown -R "$USER:$GROUP" "$INSTALL_DIR"
    chown -R "$USER:$GROUP" "/var/log/$SERVICE_NAME"
    chown -R "$USER:$GROUP" "/var/run/$SERVICE_NAME"
}

install_systemd() {
    log_info "Installing systemd service"

    # Copy service file
    cp "$INSTALL_DIR/$SERVICE_NAME.service" /etc/systemd/system/

    # Reload systemd
    systemctl daemon-reload

    # Enable service
    systemctl enable "$SERVICE_NAME"

    log_info "Systemd service installed"
    log_info "Commands:"
    log_info "  sudo systemctl start $SERVICE_NAME"
    log_info "  sudo systemctl stop $SERVICE_NAME"
    log_info "  sudo systemctl restart $SERVICE_NAME"
    log_info "  sudo systemctl status $SERVICE_NAME"
    log_info "  journalctl -u $SERVICE_NAME -f"
}

install_supervisord() {
    log_info "Installing supervisord configuration"

    # Copy config file
    cp "$INSTALL_DIR/$SERVICE_NAME.supervisord.conf" /etc/supervisor/conf.d/$SERVICE_NAME.conf

    # Reread and update supervisord
    supervisorctl reread
    supervisorctl update

    log_info "Supervisord service installed"
    log_info "Commands:"
    log_info "  sudo supervisorctl start $SERVICE_NAME"
    log_info "  sudo supervisorctl stop $SERVICE_NAME"
    log_info "  sudo supervisorctl restart $SERVICE_NAME"
    log_info "  sudo supervisorctl status $SERVICE_NAME"
    log_info "  sudo supervisorctl tail -f $SERVICE_NAME"
}

install_health_check() {
    log_info "Installing health check service"

    HEALTH_SERVICE="/etc/systemd/system/$SERVICE_NAME-health.service"

    cat > "$HEALTH_SERVICE" <<EOF
[Unit]
Description=Mahavishnu Health Check API
After=network.target

[Service]
Type=simple
User=$USER
Group=$GROUP
WorkingDirectory=$INSTALL_DIR
Environment="PATH=$INSTALL_DIR/.venv/bin"
Environment="PYTHONUNBUFFERED=1"
ExecStart=$INSTALL_DIR/.venv/bin/python -m mahavishnu.health
Restart=on-failure
RestartSec=10s

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    systemctl enable "$SERVICE_NAME-health"

    log_info "Health check service installed on port 8080"
    log_info "Endpoints:"
    log_info "  http://localhost:8080/health"
    log_info "  http://localhost:8080/ready"
    log_info "  http://localhost:8080/metrics"
}

# Main installation
main() {
    log_info "Installing $SERVICE_NAME service with $MANAGER"

    check_root
    create_user
    create_directories

    case "$MANAGER" in
        systemd)
            install_systemd
            ;;
        supervisord)
            install_supervisord
            ;;
        *)
            log_error "Unknown manager: $MANAGER (use systemd or supervisord)"
            exit 1
            ;;
    esac

    # Always install health check (systemd only for now)
    if [[ "$MANAGER" == "systemd" ]]; then
        install_health_check
    fi

    log_info "Installation complete!"
}

# Run main function
main "$@"
