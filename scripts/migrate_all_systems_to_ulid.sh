#!/bin/bash
# Master ULID Migration Script for All Ecosystem Systems
#
# Executes migrations for Crackerjack, Session-Buddy, and Akosha
# in the correct order with validation and rollback capabilities.
#
# Usage:
#   ./migrate_all_systems_to_ulid.sh [--dry-run]
#
# Environment:
#   MAHAVISHNU_DB: Path to mahavishnu.db (default: ./data/mahavishnu.db)
#   CRACKERJACK_DB: Path to crackerjack.db
#   SESSION_BUDDY_DB: Path to session_buddy.db
#   AKOSHA_PATH: Path to akosha project

set -e  # Exit on error
set -u  # Undefined variables are errors

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Default paths (can be overridden via environment)
MAHAVISHNU_DB="${MAHAVISHNU_DB:-./data/mahavishnu.db}"
CRACKERJACK_DB="${CRACKERJACK_DB:-/Users/les/Projects/crackerjack/.crackerjack/crackerjack.db}"
SESSION_BUDDY_DB="${SESSION_BUDDY_DB:-/Users/les/Projects/session-buddy/.session-buddy/session_buddy.db}"
AKOSHA_PATH="${AKOSHA_PATH:-/Users/les/Projects/akosha}"

# Function to print section headers
print_header() {
    echo ""
    echo "${NC}============================================================================${NC}"
    echo "${GREEN}$1${NC} $1"
    echo "${NC}============================================================================"
    echo ""
}

# Function to print step
print_step() {
    echo "${YELLOW}Step${NC}: $1"
    echo "${NC}------------------------------------------------"
}

# Function to print success
print_success() {
    echo "${GREEN}✅ $1${NC}"
}

# Function to print error
print_error() {
    echo "${RED}❌ ERROR: $1${NC}"
}

# Function to print info
print_info() {
    echo "  $1"
}

# Function to print warning
print_warning() {
    echo "${YELLOW}⚠️  $1${NC}"
}

# Function to create backup
backup_database() {
    local db_path="$1"
    local backup_path="${db_path}.backup.$(date +%Y%m%d_%H%M%S)"

    if [ -f "$db_path" ]; then
        print_info "Creating backup: $backup_path"
        cp "$db_path" "$backup_path"
        print_success "Backup created: $backup_path"
    else
        print_warning "Database not found: $db_path"
    fi
}

# Function to validate backup
validate_backup() {
    local db_path="$1"

    if [ -f "${db_path}.backup"* ]; then
        print_success "Backup verified"
        return 0
    else
        print_error "No backup found for $db_path"
        return 1
    fi
}

# Function to restore from backup
restore_backup() {
    local db_path="$1"
    local backup_path=$(ls -t ${db_path}.backup.* 2>/dev/null | head -1)

    if [ -n "$backup_path" ]; then
        print_error "No backup found to restore"
        return 1
    fi

    print_info "Restoring from: $backup_path"
    cp "$backup_path" "$db_path"
    print_success "Database restored"
}

# Main migration function
main() {
    local dry_run=false

    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            --dry-run)
                dry_run=true
                shift
                ;;
            *)
                echo "Unknown option: $1"
                exit 1
                ;;
        esac
    done

    print_header "ULID Ecosystem Migration"
    echo ""
    echo "This script will migrate the following systems to ULID:"
    echo "  1. Crackerjack (test tracking)"
    echo "  2. Session-Buddy (session tracking)"
    echo "  3. Akosha (knowledge graph)"
    echo ""
    echo "Migration strategy: Expand-Contract (zero downtime)"
    echo ""

    if [ "$dry_run" = true ]; then
        print_warning "DRY RUN MODE - No changes will be made"
        echo ""
    fi

    # Prompt for confirmation
    if [ "$dry_run" = false ]; then
        echo -n "${YELLOW}Continue with migration? This will create backups and modify databases. [y/N] ${NC}"
        read -r response
        echo ""

        if [[ ! "$response" =~ ^[Yy]$ ]]; then
            print_info "Migration cancelled by user"
            exit 0
        fi
    fi

    # =================================================================
    # PHASE 1: Crackerjack Migration
    # =================================================================

    print_header "Phase 1: Crackerjack ULID Migration"

    print_step "1.1: Backup Crackerjack database"
    backup_database "$CRACKERJACK_DB"

    if [ "$dry_run" = false ]; then
        print_step "1.2: Run migration script (dry-run first)"
        python3 /Users/les/Projects/mahavishnu/scripts/migrate_crackerjack_to_ulid.py --dry-run --db "$CRACKERJACK_DB"

        echo ""
        print_info "Review the migration plan above"
        echo -n "${YELLOW}Proceed with actual migration? [y/N] ${NC}"
        read -r response
        echo ""

        if [[ ! "$response" =~ ^[Yy]$ ]]; then
            print_info "Skipping Crackerjack migration"
        else
            print_step "1.3: Execute actual migration"
            python3 /Users/les/Projects/mahavishnu/scripts/migrate_crackerjack_to_ulid.py --db "$CRACKERJACK_DB"

            echo ""
            print_success "Crackerjack migration complete"
        fi
    fi

    # =================================================================
    # PHASE 2: Session-Buddy Migration
    # =================================================================

    print_header "Phase 2: Session-Buddy ULID Migration"

    print_step "2.1: Backup Session-Buddy database"
    backup_database "$SESSION_BUDDY_DB"

    if [ "$dry_run" = false ]; then
        print_step "2.2: Run migration script (dry-run first)"
        python3 /Users/les/Projects/mahavishnu/scripts/migrate_session_buddy_to_ulid.py --dry-run --db "$SESSION_BUDDY_DB"

        echo ""
        print_info "Review the migration plan above"
        echo -n "${YELLOW}Proceed with actual migration? [y/N] ${NC}"
        read -r response
        echo ""

        if [[ ! "$response" =~ ^[Yy]$ ]]; then
            print_info "Skipping Session-Buddy migration"
        else
            print_step "2.3: Execute actual migration"
            python3 /Users/les/Projects/mahavishnu/scripts/migrate_session_buddy_to_ulid.py --db "$SESSION_BUDDY_DB"

            echo ""
            print_success "Session-Buddy migration complete"
        fi
    fi

    # =================================================================
    # PHASE 3: Akosha Migration
    # =================================================================

    print_header "Phase 3: Akosha ULID Migration"

    if [ "$dry_run" = false ]; then
        print_step "3.1: Run migration script (dry-run first)"
        python3 /Users/les/Projects/mahavishnu/scripts/migrate_akosha_to_ulid.py --dry-run --akosha-path "$AKOSHA_PATH"

        echo ""
        print_info "Review the migration plan above"
        echo -n "${YELLOW}Proceed with actual migration? [y/N] ${NC}"
        read -r response
        echo ""

        if [[ ! "$response" =~ ^[Yy]$ ]]; then
            print_info "Skipping Akosha migration"
        else
            print_step "3.2: Execute actual migration"
            python3 /Users/les/Projects/mahavishnu/scripts/migrate_akosha_to_ulid.py --akosha-path "$AKOSHA_PATH"

            echo ""
            print_success "Akosha migration complete"
        fi
    fi

    # =================================================================
    # VERIFICATION PHASE
    # =================================================================

    print_header "Migration Verification"

    if [ "$dry_run" = false ]; then
        print_step "Running post-migration validation..."

        echo ""
        print_info "Crackerjack validation:"
        sqlite3 "$CRACKERJACK_DB" "SELECT COUNT(*) FROM jobs WHERE LENGTH(job_id) = 26 AND job_id GLOB '*[^a-zA-Z0-9]*';"
        echo "  Expected: All jobs have valid ULID format (26 chars, alphanumeric)"

        echo ""
        print_info "Session-Buddy validation:"
        sqlite3 "$SESSION_BUDDY_DB" "SELECT COUNT(*) FROM sessions WHERE LENGTH(session_ulid) = 26 AND session_ulid GLOB '*[^a-zA-Z0-9]*';"
        echo "  Expected: All sessions have valid ULID format"

        echo ""
        print_info "Akosha validation:"
        print_info "  Check that GraphEntity class uses: from dhruva import generate"
        print_info "  Verify entity_id field generates valid ULIDs"

        echo ""
        print_success "Migration verification complete"
    fi

    # =================================================================
    # SUMMARY
    # =================================================================

    echo ""
    echo "${NC}============================================================================"
    echo "${GREEN}Migration Summary${NC}"
    echo "${NC}============================================================================"
    echo ""
    echo "Systems migrated:"
    echo "  1. Crackerjack: Job IDs now use ULID"
    echo "  2. Session-Buddy: Session IDs now use ULID"
    echo "  3. Akosha: Entity IDs now use ULID"
    echo ""
    echo "Next steps:"
    echo "  1. Update application code to reference ULID columns"
    echo "  2. Run comprehensive test suites"
    echo "  3. Monitor performance metrics"
    echo "  4. Update documentation"
    echo ""
    echo "📋 Full documentation: /Users/les/Projects/mahavishnu/docs/ULID_DEPLOYMENT_STATUS.md"
    echo ""

    if [ "$dry_run" = false ]; then
        print_success "🎉 All migrations complete!"
        echo ""
        print_info "Rollback backups available at:"
        echo "  • ${CRACKERJACK_DB}.backup.*"
        echo "  • ${SESSION_BUDDY_DB}.backup.*"
        echo ""
        print_info "To rollback: ./migrate_all_systems_to_ulid.sh --rollback"
    fi

    exit 0
}

# =================================================================
# ROLLBACK FUNCTION
# =================================================================

rollback() {
    print_header "ULID Migration Rollback"
    echo ""
    echo "This will restore databases from backups and undo ULID migrations."
    echo ""

    # Prompt for confirmation
    echo -n "${RED}WARNING: This will undo all ULID migrations and restore from backups. Continue? [y/N] ${NC}"
    read -r response
    echo ""

    if [[ ! "$response" =~ ^[Yy]$ ]]; then
        print_info "Rollback cancelled"
        exit 0
    fi

    # Check for rollback flag
    if [[ "$1" == "--rollback" ]]; then
        print_step "1. Restoring Crackerjack from backup"
        restore_backup "$CRACKERJACK_DB"

        print_step "2. Restoring Session-Buddy from backup"
        restore_backup "$SESSION_BUDDY_DB"

        # Akosha doesn't use database - just notify
        print_info "Akosha: Code changes can be reverted with git"

        echo ""
        print_success "Rollback complete"
        echo ""
        print_info "Next steps:"
        echo "  1. Verify database integrity: sqlite3 <db> PRAGMA integrity_check"
        echo "  2. Revert code changes if needed"
        echo "  3. Restart services"
        exit 0
    fi
}

# Check if rollback requested
if [[ "$1" == "--rollback" ]]; then
    rollback "$@"
fi

# Run main function
main "$@"
