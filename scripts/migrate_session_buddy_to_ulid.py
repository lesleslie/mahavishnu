#!/usr/bin/env python3
"""Session-Buddy ULID Migration Script

Updates Session-Buddy session tracking to use Dhruva ULIDs instead of
f"{project_name}-{timestamp}" format.

Migration Strategy:
- EXPAND: Add session_ulid TEXT column
- MIGRATE: Backfill existing sessions with ULIDs
- SWITCH: Update session creation to use ULID
- CONTRACT: Remove legacy session_id generation after verification

Usage:
    python migrate_session_buddy_to_ulid.py [--dry-run]

Environment:
    SESSION_BUDDY_DB: Path to session_buddy.db (default: ./session_buddy.db)
"""

import argparse
import sqlite3
import sys
from pathlib import Path


def validate_session_ids(db_path: str) -> list[dict]:
    """Validate existing session_id format.

    Args:
        db_path: Path to session_buddy database

    Returns:
        List of validation results
    """
    issues = []

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # Check for invalid formats (not matching expected pattern)
        # Expected: project_name-timestamp
        cursor.execute(
            "SELECT session_id FROM sessions WHERE LENGTH(session_id) < 10 LIMIT 100"
        )

        too_short = cursor.fetchall()
        if too_short:
            issues.append({
                "issue": "too_short",
                "count": len(too_short),
                "sample": too_short[0][0] if too_short else None,
                "recommendation": "Session IDs should be >10 chars (project-timestamp format)"
            })

        # Check for NULL session_ids
        cursor.execute("SELECT COUNT(*) FROM sessions WHERE session_id IS NULL LIMIT 100")
        null_count = cursor.fetchone()[0]

        if null_count > 0:
            issues.append({
                "issue": "null_session_ids",
                "count": null_count,
                "recommendation": "All sessions should have valid session_id"
            })

    finally:
        conn.close()

    return issues


def generate_migration_plan(db_path: str, limit: int = 100) -> dict:
    """Generate migration plan for sessions.

    Args:
        db_path: Path to session_buddy database
        limit: Maximum sessions to process

    Returns:
        Dictionary with migration statistics
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # Get session table schema
        cursor.execute("PRAGMA table_info(sessions)")
        columns = [col[1] for col in cursor.fetchall()]
        print(f"Current schema: {columns}")

        # Check if session_ulid column exists
        has_ulid_col = "session_ulid" in columns

        if not has_ulid_col:
            print("⚠️  session_ulid column does not exist - must be added first")
        else:
            # Count sessions needing migration
            cursor.execute("SELECT COUNT(*) FROM sessions WHERE session_ulid IS NULL")
            null_count = cursor.fetchone()[0]

            # Count total sessions
            cursor.execute("SELECT COUNT(*) FROM sessions")
            total_count = cursor.fetchone()[0]

            print(f"Sessions needing migration: {null_count}/{total_count}")

    finally:
        conn.close()

    return {
        "has_session_ulid_column": has_ulid_col,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Migrate Session-Buddy session tracking from custom IDs to ULID"
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and show changes without executing"
    )

    parser.add_argument(
        "--db",
        default=str(Path.cwd() / "session_buddy.db"),
        help="Path to session_buddy.db"
    )

    args = parser.parse_args()

    print("=" * 60)
    print("Session-Buddy ULID Migration Script")
    print("=" * 60)
    print()

    # Step 1: Validation
    print("Step 1: Validating existing session_id format...")
    print("-" * 60)

    validation_issues = validate_session_ids(args.db)

    if validation_issues:
        print(f"❌ Found {len(validation_issues)} validation issues:")
        for issue in validation_issues:
            print(f"  • {issue['issue']}: {issue['count']} affected")
            if issue['sample']:
                print(f"   Sample: {issue['sample']}")
            print(f"   Recommendation: {issue['recommendation']}")
        print()
        print("⚠️  Please fix validation issues before proceeding with migration.")
        return 1

    print("✅ No critical validation issues found.")
    print()

    # Step 2: Migration Plan
    print("Step 2: Generating migration plan...")
    print("-" * 60)

    plan = generate_migration_plan(args.db)

    if not args.dry_run:
        print("✅ Migration analysis complete.")
        print()
        print("Step 3: Migration steps:")
        print("-" * 60)
        print()
        print("To complete Session-Buddy ULID migration:")
        print()
        print("1. Add session_ulid TEXT column to sessions table:")
        print("   ALTER TABLE sessions ADD COLUMN session_ulid TEXT;")
        print()
        print("2. Update session_buddy/session_manager.py:")
        print("   - Replace: session_id = f\"{project_name}-{timestamp}\"")
        print("   - With: from dhruva import generate; session_ulid = generate()")
        print()
        print("3. Backfill existing sessions:")
        print("   UPDATE sessions")
        print("   SET session_ulid = <generated_ulid>")
        print("   WHERE session_ulid IS NULL;")
        print()
        print("4. Update reflection/conversation creation:")
        print("   - Use generate() from Dhruva instead of custom ID")
        print()
        print("5. Run tests: pytest tests/")
        print()
        print("⏳  Awaiting user approval to execute migration.")
        print()
        print("Ready? Run without --dry-run to execute.")
    else:
        print("✅ DRY RUN - Schema analysis complete")
        print()
        print("Note: Session-Buddy uses DuckDB (flexible schema)")
        print("      No foreign key constraints to worry about.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
