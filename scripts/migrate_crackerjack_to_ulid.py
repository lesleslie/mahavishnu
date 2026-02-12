#!/usr/bin/env python3
"""Crackerjack ULID Migration Script

Updates Crackerjack test tracking to use Dhruva ULIDs instead of UUID v4.

Migration Strategy:
- EXPAND: job_id already exists as TEXT UNIQUE (schema compatible)
- MIGRATE: Backfill existing jobs with new ULID column
- SWITCH: Update application code to reference ULID
- CONTRACT: Remove uuid4() calls after verification

Usage:
    python migrate_crackerjack_to_ulid.py [--dry-run]

Environment:
    CRACKERJACK_DB: Path to crackerjack.db (default: ./crackerjack.db)
"""

import argparse
import sqlite3
import sys
from pathlib import Path


def generate_migration_map(db_path: str, limit: int = 1000) -> dict[str, str]:
    """Generate mapping from UUID job_ids to ULIDs.

    Args:
        db_path: Path to crackerjack database
        limit: Maximum jobs to process (for testing)

    Returns:
        Dictionary mapping {old_job_id: new_ulid}
    """
    migration_map = {}

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # Get existing jobs with UUID job_ids
        cursor.execute(
            "SELECT job_id, id FROM jobs WHERE job_id IS NOT NULL LIMIT ?",
            (limit,)
        )

        rows = cursor.fetchall()

        print(f"Found {len(rows)} jobs to migrate")

        for job_id, _ in rows:
            # For each existing job, we'd generate a new ULID
            # In production, this would use Dhruva's generate()
            # For this script, we'll just note it needs migration
            migration_map[job_id] = f"[NEEDS_ULID_GENERATION]"

    finally:
        conn.close()

    return migration_map


def validate_job_ids(db_path: str) -> list[dict]:
    """Validate existing job_id format.

    Args:
        db_path: Path to crackerjack database

    Returns:
        List of validation results for invalid job_ids
    """
    issues = []

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # Check for invalid formats (not 26 chars, not alphanumeric)
        cursor.execute(
            "SELECT job_id FROM jobs WHERE LENGTH(job_id) != 26 OR job_id GLOB '*[^a-zA-Z0-9]*' LIMIT 100"
        )

        invalid = cursor.fetchall()
        if invalid:
            issues.append({
                "issue": "invalid_format",
                "count": len(invalid),
                "sample": invalid[0] if invalid else None,
                "recommendation": "Job IDs should be 26-char alphanumeric (ULID format)"
            })

        # Check for NULL job_ids
        cursor.execute("SELECT COUNT(*) FROM jobs WHERE job_id IS NULL LIMIT 100")
        null_count = cursor.fetchone()[0]

        if null_count > 0:
            issues.append({
                "issue": "null_job_ids",
                "count": null_count,
                "recommendation": "All jobs should have valid job_id"
            })

    finally:
        conn.close()

    return issues


def main():
    parser = argparse.ArgumentParser(
        description="Migrate Crackerjack test tracking from UUID to ULID"
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and show changes without executing"
    )

    parser.add_argument(
        "--db",
        default=str(Path.cwd() / "crackerjack.db"),
        help="Path to crackerjack.db"
    )

    args = parser.parse_args()

    print("=" * 60)
    print("Crackerjack ULID Migration Script")
    print("=" * 60)
    print()

    # Step 1: Validation
    print("Step 1: Validating existing job_id format...")
    print("-" * 60)

    validation_issues = validate_job_ids(args.db)

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

    print("✅ No validation issues found.")
    print()

    # Step 2: Migration Plan
    print("Step 2: Generating migration plan...")
    print("-" * 60)

    migration_map = generate_migration_map(args.db, limit=100)

    if not args.dry_run:
        print(f"✅ Migration map generated for {len(migration_map)} jobs.")
        print()
        print("Step 3: Migration steps:")
        print("-" * 60)
        print()
        print("To complete Crackerjack ULID migration:")
        print()
        print("1. Update crackerjack/services/metrics.py:")
        print("   - Replace uuid.uuid4() with: from dhruva import generate")
        print("   - job_id = generate()")
        print()
        print("2. Update crackerjack/tests/ to use Dhruva ULID in test fixtures")
        print()
        print("3. Add migration backfill script for existing jobs:")
        print("   UPDATE jobs SET job_ulid = <generated_ulid>")
        print("   WHERE job_ulid IS NULL")
        print()
        print("4. Run validation: python -m pytest tests/")
        print()
        print("⏳  Awaiting user approval to execute migration.")
        print()
        print("Ready? Run without --dry-run to execute.")
    else:
        print(f"✅ DRY RUN - Would migrate {len(migration_map)} jobs.")
        print()
        for old_id, new_id in list(migration_map.items())[:10]:
            print(f"  {old_id[:30]}... → {new_id}")
        if len(migration_map) > 10:
            print(f"  ... and {len(migration_map) - 10} more")

    return 0


if __name__ == "__main__":
    sys.exit(main())
