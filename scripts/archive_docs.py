#!/usr/bin/env python3
"""
Documentation Archival and Consolidation Script

Archives old documentation from root and docs/ directories to docs/archive/
Consolidates duplicate documentation files.

Target: Reduce from ~615 docs to ~400 docs by archiving ~215 files.
"""

import os
import shutil
import re
from pathlib import Path
from datetime import datetime
from collections import defaultdict

# Configuration
PROJECT_ROOT = Path("/Users/les/Projects/mahavishnu")
ARCHIVE_ROOT = PROJECT_ROOT / "docs" / "archive"
DRY_RUN = False  # Set to True for dry run

# File categorization patterns
CATEGORIES = {
    "completion-reports": [
        r".*_COMPLETE\.md$",
        r".*_COMPLETION.*\.md$",
        r".*_FINAL.*\.md$",
        r".*_DELIVERY.*\.md$",
        r"PHASE.*_COMPLETE\.md$",
    ],
    "implementation-plans": [
        r".*_PLAN\.md$",
        r".*_IMPLEMENTATION.*\.md$",
        r".*_STRATEGY\.md$",
    ],
    "analysis": [
        r".*_ANALYSIS\.md$",
        r".*_ASSESSMENT\.md$",
        r".*_REVIEW.*\.md$",
        r".*_AUDIT.*\.md$",
    ],
    "summaries": [
        r".*_SUMMARY\.md$",
        r".*_REPORT\.md$",
        r".*_STATUS\.md$",
    ],
    "checkpoints": [
        r"CHECKPOINT.*\.md$",
        r"SESSION.*\.md$",
        r".*_CHECKPOINT.*\.md$",
    ],
    "act-reports": [
        r"ACT-.*\.md$",
    ],
    "quick-references": [
        r".*_QUICK.*\.md$",
        r".*_QUICKSTART\.md$",
        r".*_QUICKREF\.md$",
    ],
    "research": [
        r".*_RESEARCH\.md$",
        r".*_INVESTIGATION.*\.md$",
        r".*_STUDY\.md$",
    ],
    "phase-reports": [
        r"PHASE.*\.md$",
        r"WEEK.*\.md$",
        r".*_PHASE.*\.md$",
    ],
    "test-reports": [
        r".*_TEST.*\.md$",
        r".*_COVERAGE.*\.md$",
        r"TEST_.*\.md$",
    ],
    "guides": [
        r".*_GUIDE\.md$",
        r".*_TUTORIAL\.md$",
    ],
    "migration": [
        r".*_MIGRATION.*\.md$",
        r".*_MIGRATE\.md$",
    ],
    "security-fixes": [
        r"SECURITY_.*\.md$",
        r".*_SECURITY.*\.md$",
        r".*_FIX_.*\.md$",
    ],
    "ecosystem": [
        r"ECOSYSTEM.*\.md$",
    ],
    "sessions": [
        r".*_SESSION.*\.md$",
    ],
    "status-reports": [
        r"PROGRESS.*\.md$",
        r".*_PROGRESS.*\.md$",
    ],
}

# Files to KEEP in root or docs/ (not archive)
KEEP_FILES = {
    # Root files
    "README.md",
    "QUICKSTART.md",
    "CHANGELOG.md",
    "RELEASE_NOTES.md",
    "CONTRIBUTING.md",
    "RULES.md",
    "CLAUDE.md",
    "ARCHITECTURE.md",
    "SECURITY_CHECKLIST.md",

    # Docs files (keep current/active)
    "ADVANCED_FEATURES.md",
    "API_REFERENCE.md",
    "GETTING_STARTED.md",
    "USER_GUIDE.md",
    "MCP_TOOLS_SPECIFICATION.md",
    "MCP_TOOLS_REFERENCE.md",
    "ECOSYSTEM_ARCHITECTURE.md",
    "ECOSYSTEM_QUICKSTART.md",
    "PROMPT_ADAPTER_ARCHITECTURE.md",
    "PROMPT_ADAPTER_QUICK_START.md",
    "PROMPT_BACKEND_RESEARCH.md",
    "TRACK4_LITE_MODE_PLAN.md",
}


def categorize_file(filename: str) -> str:
    """Categorize a file based on its name pattern."""
    for category, patterns in CATEGORIES.items():
        for pattern in patterns:
            if re.match(pattern, filename, re.IGNORECASE):
                return category
    return "reports"  # Default category


def should_keep_file(filepath: Path) -> bool:
    """Check if file should be kept (not archived)."""
    filename = filepath.name
    if filename in KEEP_FILES:
        return True

    # Keep recent checkpoint files (last 7 days)
    if "CHECKPOINT" in filename.upper():
        file_mtime = datetime.fromtimestamp(filepath.stat().st_mtime)
        if (datetime.now() - file_mtime).days < 7:
            return True

    return False


def find_duplicates():
    """Find potential duplicate documentation files."""
    # Group files by base name (remove suffixes like _COMPLETE, _SUMMARY, etc.)
    file_groups = defaultdict(list)

    # Scan root directory
    for md_file in PROJECT_ROOT.glob("*.md"):
        if not should_keep_file(md_file):
            # Extract base name
            base = md_file.stem
            for suffix in ["_COMPLETE", "_SUMMARY", "_FINAL", "_PLAN", "_REPORT", "_QUICKSTART", "_QUICKREF"]:
                base = base.replace(suffix, "")
            file_groups[base].append(md_file)

    # Scan docs directory
    for md_file in (PROJECT_ROOT / "docs").glob("*.md"):
        if not should_keep_file(md_file):
            base = md_file.stem
            for suffix in ["_COMPLETE", "_SUMMARY", "_FINAL", "_PLAN", "_REPORT", "_QUICKSTART", "_QUICKREF"]:
                base = base.replace(suffix, "")
            file_groups[base].append(md_file)

    # Find groups with multiple files
    duplicates = {k: v for k, v in file_groups.items() if len(v) > 1}
    return duplicates


def archive_file(filepath: Path, category: str) -> Path:
    """Archive a file to the appropriate category directory."""
    category_dir = ARCHIVE_ROOT / category
    category_dir.mkdir(parents=True, exist_ok=True)

    # Handle name conflicts
    dest = category_dir / filepath.name
    counter = 1
    while dest.exists():
        stem = filepath.stem
        suffix = filepath.suffix
        dest = category_dir / f"{stem}_{counter}{suffix}"
        counter += 1

    if not DRY_RUN:
        shutil.move(str(filepath), str(dest))
        print(f"Archived: {filepath.name} -> {category}/{dest.name}")
    else:
        print(f"[DRY RUN] Would archive: {filepath.name} -> {category}/{dest.name}")

    return dest


def main():
    """Main archival function."""
    print("=" * 80)
    print("DOCUMENTATION ARCHIVAL AND CONSOLIDATION")
    print("=" * 80)
    print(f"Project Root: {PROJECT_ROOT}")
    print(f"Archive Root: {ARCHIVE_ROOT}")
    print(f"Mode: {'DRY RUN' if DRY_RUN else 'LIVE'}")
    print("=" * 80)
    print()

    # Count files before
    root_files = list(PROJECT_ROOT.glob("*.md"))
    docs_files = list((PROJECT_ROOT / "docs").glob("*.md"))
    total_before = len(root_files) + len(docs_files)

    print(f"Files before archival: {total_before}")
    print(f"  - Root: {len(root_files)}")
    print(f"  - docs/: {len(docs_files)}")
    print()

    # Find duplicates BEFORE moving files
    print("Finding duplicate documentation files...")
    duplicates = find_duplicates()
    print(f"Found {len(duplicates)} potential duplicate groups:")
    for base, files in sorted(duplicates.items()):
        print(f"  - {base}: {len(files)} files")
    print()

    # Archive files
    archived_count = 0
    consolidated_count = 0

    # Process root directory files
    print("Processing root directory files...")
    for md_file in root_files:
        if not should_keep_file(md_file):
            category = categorize_file(md_file.name)
            archive_file(md_file, category)
            archived_count += 1

    # Process docs directory files
    print("\nProcessing docs/ directory files...")
    for md_file in docs_files:
        if not should_keep_file(md_file):
            category = categorize_file(md_file.name)
            archive_file(md_file, category)
            archived_count += 1

    # Handle duplicates (keep most recent)
    print("\nHandling duplicate files...")
    for base, files in sorted(duplicates.items()):
        if len(files) > 1:
            # Filter to only existing files and sort by modification time (newest first)
            existing_files = [f for f in files if f.exists()]
            if len(existing_files) <= 1:
                continue

            existing_files.sort(key=lambda f: f.stat().st_mtime, reverse=True)

            # Keep the newest, archive the rest
            keep = existing_files[0]
            for duplicate in existing_files[1:]:
                if duplicate.exists():
                    category = categorize_file(duplicate.name)
                    archive_file(duplicate, category)
                    consolidated_count += 1
                    print(f"  Consolidated: {duplicate.name} (kept {keep.name})")

    # Count files after
    root_files_after = list(PROJECT_ROOT.glob("*.md"))
    docs_files_after = list((PROJECT_ROOT / "docs").glob("*.md"))
    total_after = len(root_files_after) + len(docs_files_after)

    print()
    print("=" * 80)
    print("ARCHIVAL SUMMARY")
    print("=" * 80)
    print(f"Files before: {total_before}")
    print(f"Files after:  {total_after}")
    print(f"Archived:    {archived_count}")
    print(f"Consolidated: {consolidated_count}")
    print(f"Reduction:   {total_before - total_after} files")
    print(f"Target:      ~400 files (achieved: {total_after} files)")
    print()

    if DRY_RUN:
        print("[DRY RUN] No files were actually moved.")
        print("Set DRY_RUN = False to execute.")
    else:
        print("Archival complete!")
    print("=" * 80)


if __name__ == "__main__":
    main()
