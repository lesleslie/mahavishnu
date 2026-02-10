#!/usr/bin/env bash
# Grafana Learning Telemetry Dashboard Setup Script
# Version: 1.0.0
# Description: Automated setup of DuckDB datasource and learning telemetry dashboard

set -euo pipefail

# ============================================================================
# CONFIGURATION
# ============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
DASHBOARD_NAME="learning-telemetry"
DASHBOARD_FILE="${PROJECT_ROOT}/grafana/dashboards/learning-telemetry.json"
BACKUP_DIR="${SCRIPT_DIR}/../grafana/dashboards/backups"
LOG_FILE="${SCRIPT_DIR}/setup_learning_dashboard.log"

# Grafana configuration
GRAFANA_URL="${GRAFANA_URL:-http://localhost:3000}"
GRAFANA_API_URL="${GRAFANA_URL}/api"
GRAFANA_USER="${GRAFANA_USER:-admin}"
GRAFANA_PASSWORD="${GRAFANA_PASSWORD:-admin}"

# DuckDB configuration
LEARNING_DB_PATH="${LEARNING_DB_PATH:-${PROJECT_ROOT}/data/learning.db}"
DATASOURCE_NAME="DuckDB Learning"
DATASOURCE_UID="duckdb-learning"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# ============================================================================
# LOGGING FUNCTIONS
# ============================================================================

log() {
    local level="$1"
    shift
    local message="$*"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo "[${timestamp}] [${level}] ${message}" | tee -a "${LOG_FILE}"
}

log_info() {
    echo -e "${BLUE}[INFO]${NC} $*"
    log "INFO" "$*"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $*"
    log "SUCCESS" "$*"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $*"
    log "WARNING" "$*"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $*"
    log "ERROR" "$*"
}

# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

check_dependencies() {
    log_info "Checking dependencies..."

    local missing_deps=()

    command -v curl >/dev/null 2>&1 || missing_deps+=("curl")
    command -v jq >/dev/null 2>&1 || missing_deps+=("jq")

    if [[ ${#missing_deps[@]} -gt 0 ]]; then
        log_error "Missing required dependencies: ${missing_deps[*]}"
        log_info "Install with: brew install ${missing_deps[*]}"
        return 1
    fi

    # Check Python dependencies
    if ! python3 -c "import duckdb" >/dev/null 2>&1; then
        log_warning "DuckDB Python package not found"
        log_info "Install with: pip install duckdb"
    fi

    log_success "All dependencies satisfied"
    return 0
}

check_grafana_running() {
    log_info "Checking if Grafana is running..."

    if ! curl -sf "${GRAFANA_URL}/api/health" >/dev/null 2>&1; then
        log_error "Grafana is not running at ${GRAFANA_URL}"
        log_info "Start Grafana with:"
        log_info "  - macOS: brew services start grafana"
        log_info "  - Linux: systemctl start grafana-server"
        log_info "  - Docker: docker run -d -p 3000:3000 grafana/grafana"
        return 1
    fi

    log_success "Grafana is running at ${GRAFANA_URL}"
    return 0
}

check_learning_database() {
    log_info "Checking learning database..."

    if [[ ! -f "${LEARNING_DB_PATH}" ]]; then
        log_warning "Learning database not found at ${LEARNING_DB_PATH}"
        log_info "Initialize the database with:"
        log_info "  python scripts/migrate_learning_db.py"
        return 1
    fi

    # Verify database has data
    local row_count
    row_count=$(python3 -c "import duckdb; con = duckdb.connect('${LEARNING_DB_PATH}'); print(con.execute('SELECT COUNT(*) FROM executions').fetchone()[0])" 2>/dev/null || echo "0")

    if [[ "${row_count}" -eq 0 ]]; then
        log_warning "Learning database exists but has no data"
        log_info "The dashboard will be deployed but may show no data until executions are recorded"
    else
        log_success "Learning database found with ${row_count} execution records"
    fi

    return 0
}

grafana_api() {
    local endpoint="$1"
    local method="${2:-GET}"
    local data="${3:-}"

    local response
    response=$(curl -s -X "${method}" \
        -u "${GRAFANA_USER}:${GRAFANA_PASSWORD}" \
        -H "Content-Type: application/json" \
        ${data:+-d "${data}"} \
        "${GRAFANA_API_URL}${endpoint}" 2>&1)

    local exit_code=$?

    if [[ $exit_code -ne 0 ]]; then
        log_error "API call failed: ${response}"
        return 1
    fi

    echo "${response}"
}

create_backup_dir() {
    if [[ ! -d "${BACKUP_DIR}" ]]; then
        mkdir -p "${BACKUP_DIR}"
        log_info "Created backup directory: ${BACKUP_DIR}"
    fi
}

backup_dashboard() {
    log_info "Backing up existing dashboard..."

    create_backup_dir

    local backup_file="${BACKUP_DIR}/${DASHBOARD_NAME}-$(date +%Y%m%d-%H%M%S).json"

    # Get existing dashboard if it exists
    local existing_dashboard
    existing_dashboard=$(grafana_api "/dashboards/db/${DASHBOARD_NAME}")

    if [[ -n "${existing_dashboard}" ]] && echo "${existing_dashboard}" | jq -e '.id' >/dev/null 2>&1; then
        echo "${existing_dashboard}" | jq '.' > "${backup_file}"
        log_success "Backup saved to: ${backup_file}"
    else
        log_info "No existing dashboard found, skipping backup"
    fi
}

# ============================================================================
# DATASOURCE SETUP
# ============================================================================

check_datasource_exists() {
    log_info "Checking if DuckDB datasource exists..."

    local response
    response=$(grafana_api "/datasources/name/${DATASOURCE_NAME}")

    if echo "${response}" | jq -e '.id' >/dev/null 2>&1; then
        log_success "DuckDB datasource already exists"
        return 0
    else
        log_info "DuckDB datasource not found"
        return 1
    fi
}

install_duckdb_plugin() {
    log_info "Checking for DuckDB plugin..."

    # Check if plugin is already installed
    local response
    response=$(grafana_api "/plugins/duckdb-datasource")

    if echo "${response}" | jq -e '.installed == true' >/dev/null 2>&1; then
        log_success "DuckDB plugin is installed"
        return 0
    fi

    log_warning "DuckDB plugin not found. Please install it manually:"
    log_info "  grafana-cli plugins install duckdb-datasource"
    log_info "  Then restart Grafana"
    return 1
}

create_duckdb_datasource() {
    log_info "Creating DuckDB datasource..."

    if ! check_datasource_exists; then
        if ! install_duckdb_plugin; then
            log_error "Cannot create datasource without DuckDB plugin"
            return 1
        fi

        local datasource_data=$(cat <<EOF
{
  "name": "${DATASOURCE_NAME}",
  "type": "duckdb-datasource",
  "uid": "${DATASOURCE_UID}",
  "access": "proxy",
  "isDefault": false,
  "jsonData": {
    "path": "${LEARNING_DB_PATH}",
    "enableConnectionPooling": true
  },
  "editable": true
}
EOF
)

        local response
        response=$(grafana_api "/datasources" "POST" "${datasource_data}")

        if echo "${response}" | jq -e '.message == "Datasource added"' >/dev/null 2>&1; then
            log_success "DuckDB datasource created successfully"
        else
            log_error "Failed to create datasource: ${response}"
            return 1
        fi
    fi

    return 0
}

create_postgres_datasource() {
    log_info "Creating PostgreSQL datasource (alternative)..."

    # This is a fallback if DuckDB plugin is not available
    local datasource_data='{
      "name": "DuckDB Learning (PostgreSQL)",
      "type": "postgres",
      "uid": "duckdb-learning-postgres",
      "access": "proxy",
      "isDefault": false,
      "jsonData": {
        "connString": "host=localhost user=postgres dbname=learning sslmode=disable"
      },
      "editable": true
    }'

    local response
    response=$(grafana_api "/datasources" "POST" "${datasource_data}")

    if echo "${response}" | jq -e '.message == "Datasource added"' >/dev/null 2>&1; then
        log_success "PostgreSQL datasource created (use if DuckDB plugin unavailable)"
    else
        log_warning "Failed to create PostgreSQL datasource: ${response}"
    fi
}

# ============================================================================
# DASHBOARD DEPLOYMENT
# ============================================================================

deploy_dashboard() {
    log_info "Deploying learning telemetry dashboard..."

    if [[ ! -f "${DASHBOARD_FILE}" ]]; then
        log_error "Dashboard file not found: ${DASHBOARD_FILE}"
        return 1
    fi

    # Read and prepare dashboard
    local dashboard_data
    dashboard_data=$(jq -c \
        --arg title "Mahavishnu Learning Telemetry" \
        --arg id "null" \
        '{
            overwrite: true,
            dashboard: (.dashboard | del(.id) | .title = $title)
        }' "${DASHBOARD_FILE}")

    # Deploy dashboard
    local response
    response=$(grafana_api "/dashboards/db" "POST" "${dashboard_data}")

    if echo "${response}" | jq -e '.status == "success"' >/dev/null 2>&1; then
        local dashboard_uid=$(echo "${response}" | jq -r '.uid')
        local dashboard_url="${GRAFANA_URL}/d/${dashboard_uid}"
        log_success "Dashboard deployed successfully"
        log_info "Dashboard URL: ${dashboard_url}"
        return 0
    else
        log_error "Failed to deploy dashboard: ${response}"
        return 1
    fi
}

verify_dashboard() {
    log_info "Verifying dashboard deployment..."

    # Wait a moment for Grafana to process
    sleep 2

    local response
    response=$(grafana_api "/dashboards/db/${DASHBOARD_NAME}")

    if echo "${response}" | jq -e '.id' >/dev/null 2>&1; then
        log_success "Dashboard verification successful"
        return 0
    else
        log_error "Dashboard verification failed: ${response}"
        return 1
    fi
}

open_dashboard() {
    log_info "Opening dashboard in browser..."

    # Get dashboard UID
    local response
    response=$(grafana_api "/dashboards/db/${DASHBOARD_NAME}")
    local dashboard_uid=$(echo "${response}" | jq -r '.uid // empty')

    if [[ -n "${dashboard_uid}" ]]; then
        local dashboard_url="${GRAFANA_URL}/d/${dashboard_uid}"

        if command -v open >/dev/null 2>&1; then
            open "${dashboard_url}"
        elif command -v xdg-open >/dev/null 2>&1; then
            xdg-open "${dashboard_url}"
        else
            log_info "Open this URL in your browser: ${dashboard_url}"
        fi
    fi
}

# ============================================================================
# TESTING
# ============================================================================

test_queries() {
    log_info "Testing sample queries against learning database..."

    if [[ ! -f "${LEARNING_DB_PATH}" ]]; then
        log_warning "Skipping query tests - database not found"
        return 0
    fi

    # Test 1: Basic count
    local count
    count=$(python3 -c "import duckdb; con = duckdb.connect('${LEARNING_DB_PATH}'); print(con.execute('SELECT COUNT(*) FROM executions').fetchone()[0])" 2>/dev/null || echo "ERROR")

    if [[ "${count}" != "ERROR" ]]; then
        log_success "Query test 1 passed: COUNT(*) = ${count}"
    else
        log_warning "Query test 1 failed"
    fi

    # Test 2: Success rate calculation
    local success_rate
    success_rate=$(python3 -c "import duckdb; con = duckdb.connect('${LEARNING_DB_PATH}'); print(con.execute('SELECT (SUM(CASE WHEN success = TRUE THEN 1 ELSE 0 END) * 100.0 / COUNT(*)) FROM executions').fetchone()[0])" 2>/dev/null || echo "ERROR")

    if [[ "${success_rate}" != "ERROR" ]]; then
        log_success "Query test 2 passed: Success rate = ${success_rate}%"
    else
        log_warning "Query test 2 failed"
    fi

    # Test 3: Model tier aggregation
    local tier_count
    tier_count=$(python3 -c "import duckdb; con = duckdb.connect('${LEARNING_DB_PATH}'); print(len(con.execute('SELECT model_tier FROM executions GROUP BY model_tier').fetchall()))" 2>/dev/null || echo "ERROR")

    if [[ "${tier_count}" != "ERROR" ]]; then
        log_success "Query test 3 passed: ${tier_count} model tiers found"
    else
        log_warning "Query test 3 failed"
    fi
}

print_next_steps() {
    echo ""
    log_info "=========================================="
    log_info "Setup Complete!"
    log_info "=========================================="
    echo ""
    log_info "Dashboard Information:"
    log_info "  URL: ${GRAFANA_URL}/d/${DASHBOARD_NAME}"
    log_info "  Credentials: ${GRAFANA_USER} / ${GRAFANA_PASSWORD}"
    echo ""
    log_info "Database Information:"
    log_info "  Path: ${LEARNING_DB_PATH}"
    log_info "  Datasource: ${DATASOURCE_NAME}"
    echo ""
    log_info "Next Steps:"
    log_info "  1. Verify datasource connection in Grafana"
    log_info "  2. Check dashboard panels render correctly"
    log_info "  3. Set up alerts (optional)"
    log_info "  4. Configure refresh intervals"
    echo ""
    log_info "Troubleshooting:"
    log_info "  - If panels show no data: Verify database has records"
    log_info "  - If datasource fails: Check DuckDB plugin installation"
    log_info "  - For errors: Check ${LOG_FILE}"
    echo ""
    log_info "Documentation:"
    log_info "  - ADR-006: docs/adr/006-duckdb-learning-database.md"
    log_info "  - Queries: scripts/dashboard_queries.sql"
    echo ""
}

# ============================================================================
# MAIN FUNCTIONS
# ============================================================================

usage() {
    cat <<EOF
Usage: $0 [COMMAND]

Commands:
    setup         Run complete setup (default)
    datasource    Create/update datasource only
    dashboard     Deploy dashboard only
    verify        Verify deployment
    test          Test database queries
    open          Open dashboard in browser
    help          Show this help message

Environment Variables:
    GRAFANA_URL           Grafana URL (default: http://localhost:3000)
    GRAFANA_USER          Grafana username (default: admin)
    GRAFANA_PASSWORD      Grafana password (default: admin)
    LEARNING_DB_PATH      Path to learning.db (default: ./data/learning.db)

Examples:
    $0 setup                                    # Complete setup
    $0 datasource                               # Setup datasource only
    GRAFANA_URL=http://grafana:3000 $0 setup    # Setup remote Grafana

EOF
}

cmd_setup() {
    log_info "Starting learning telemetry dashboard setup..."

    check_dependencies || return 1
    check_grafana_running || return 1
    check_learning_database || log_warning "Continuing without database verification..."

    backup_dashboard
    create_duckdb_datasource || create_postgres_datasource
    deploy_dashboard

    if verify_dashboard; then
        test_queries
        print_next_steps

        read -p "Open dashboard in browser? (y/N) " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            open_dashboard
        fi

        log_success "Setup completed successfully!"
        return 0
    else
        log_error "Setup verification failed"
        return 1
    fi
}

cmd_datasource() {
    log_info "Setting up datasource..."

    check_dependencies || return 1
    check_grafana_running || return 1

    create_duckdb_datasource || create_postgres_datasource
    log_success "Datasource setup complete"
}

cmd_dashboard() {
    log_info "Deploying dashboard..."

    check_dependencies || return 1
    check_grafana_running || return 1

    backup_dashboard
    deploy_dashboard

    if verify_dashboard; then
        log_success "Dashboard deployed successfully"
        return 0
    else
        log_error "Dashboard deployment failed"
        return 1
    fi
}

cmd_verify() {
    check_dependencies || return 1
    check_grafana_running || return 1
    verify_dashboard
    test_queries
}

cmd_test() {
    log_info "Running query tests..."
    test_queries
}

cmd_open() {
    open_dashboard
}

# ============================================================================
# ENTRY POINT
# ============================================================================

main() {
    local command="${1:-setup}"

    case "${command}" in
        setup)
            cmd_setup
            ;;
        datasource)
            cmd_datasource
            ;;
        dashboard)
            cmd_dashboard
            ;;
        verify)
            cmd_verify
            ;;
        test)
            cmd_test
            ;;
        open)
            cmd_open
            ;;
        help|--help|-h)
            usage
            ;;
        *)
            log_error "Unknown command: ${command}"
            usage
            exit 1
            ;;
    esac
}

# Run main function
main "$@"
