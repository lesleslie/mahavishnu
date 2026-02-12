#!/usr/bin/env python3
"""Akosha ULID Migration Script

Updates Akosha knowledge graph entities to use Dhruva ULIDs instead of
custom string IDs (f"system:{id}", f"user:{id}").

Migration Strategy:
- IN-MEMORY: No database migration (entities stored in-memory)
- CODE UPDATE: Update GraphEntity class to use Dhruva generate()
- BACKFILL: Regenerate entity IDs for in-memory entities (on restart)

Usage:
    python migrate_akosha_to_ulid.py [--dry-run]

Environment:
    AKOSHA_PATH: Path to akosha codebase
"""

import argparse
import sys
from pathlib import Path


def analyze_entity_id_usage(akosha_path: str) -> dict:
    """Analyze current entity ID generation patterns.

    Args:
        akosha_path: Path to akosha project root

    Returns:
        Dictionary with analysis results
    """
    results = {
        "files_checked": 0,
        "custom_id_patterns": [],
        "uses_dhruva": False,
        "recommendations": []
    }

    # Check key files for entity ID generation
    files_to_check = [
        "akosha/processing/knowledge_graph.py",
        "akosha/mcp/tools/akosha_tools.py",
    ]

    for file_path in files_to_check:
        full_path = akosha_path / file_path

        if not full_path.exists():
            continue

        results["files_checked"] += 1
        content = full_path.read_text()

        # Check for custom ID patterns
        if 'f"system:{' in content or 'f"user:{' in content:
            results["custom_id_patterns"].append({
                "file": file_path,
                "pattern": "f\"system:{id}\" or f\"user:{id}\""
            })
            results["recommendations"].append({
                "file": file_path,
                "change": f"Replace custom ID generation with: from dhruva import generate; entity_id = generate()"
            })

        # Check if already using Dhruva
        if "from dhruva import" in content or "import dhruva" in content:
            results["uses_dhruva"] = True

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Migrate Akosha knowledge graph from custom IDs to ULID"
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and show changes without executing"
    )

    parser.add_argument(
        "--akosha-path",
        default=str(Path(__file__).parent.parent / "akosha"),
        help="Path to akosha project"
    )

    args = parser.parse_args()

    print("=" * 60)
    print("Akosha ULID Migration Script")
    print("=" * 60)
    print()

    # Step 1: Analysis
    print("Step 1: Analyzing entity ID generation patterns...")
    print("-" * 60)

    analysis = analyze_entity_id_usage(args.akosha_path)

    print(f"Files checked: {analysis['files_checked']}")
    print()

    if analysis["custom_id_patterns"]:
        print(f"❌ Found {len(analysis['custom_id_patterns'])} files using custom ID patterns:")
        for finding in analysis["custom_id_patterns"]:
            print(f"  • {finding['file']}: {finding['pattern']}")
        print()
    else:
        print("✅ No custom ID patterns found.")
        print()

    if not analysis["uses_dhruva"]:
        print("⚠️  Akosha is not using Dhruva for ID generation.")
        print()
    else:
        print("✅ Akosha already using Dhruva.")
        print()

    # Step 2: Migration Plan
    print("Step 2: Generating migration plan...")
    print("-" * 60)

    if not args.dry_run:
        print("Step 3: Migration steps:")
        print("-" * 60)
        print()
        print("To complete Akosha ULID migration:")
        print()
        print("1. Update akosha/processing/knowledge_graph.py:")
        print("   - Replace: entity_id = f\"system:{system_id}\"")
        print("   - With: from dhruva import generate; entity_id = generate()")
        print()
        print("2. Update akosha/mcp/tools/akosha_tools.py:")
        print("   - Replace any entity ID generation with: from dhruva import generate")
        print()
        print("3. Update imports in affected files:")
        print("   - Add: from dhruva import generate, ULID")
        print()
        print("4. Run tests: pytest tests/")
        print()
        print("⏳  Awaiting user approval to execute migration.")
        print()
        print("Ready? Run without --dry-run to make code changes.")
    else:
        print("✅ DRY RUN - Analysis complete")
        print()
        print("Note: Akosha uses in-memory storage (no database migration needed)")
        print("      Just update code to use Dhruva generate().")

    return 0


if __name__ == "__main__":
    sys.exit(main())
