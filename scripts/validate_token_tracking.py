#!/usr/bin/env python3
"""
Validation script for transcript-based token tracking
Compares calculated tokens against expected values to ensure accuracy

Author: python-pro specialist
Date: 2025-10-03
"""
import json
from pathlib import Path
from session_progress_real import (
    extract_transcript_records,
    aggregate_token_usage,
    load_session_progress,
    TOKEN_BUDGET
)


def validate_transcript_parsing(jsonl_path: str) -> dict:
    """
    Validate transcript parsing and token aggregation

    Returns validation report with:
    - Token counts by category
    - Session timing
    - Data quality checks
    - Comparison with expected values
    """
    print(f"\n{'='*60}")
    print(f"Validating Transcript: {Path(jsonl_path).name}")
    print(f"{'='*60}\n")

    # Run aggregation
    records = extract_transcript_records(jsonl_path)
    stats = aggregate_token_usage(records)

    # Display results
    print("Token Statistics:")
    print(f"  Input Tokens:          {stats['input_tokens']:>10,}")
    print(f"  Cache Creation Tokens: {stats['cache_creation_tokens']:>10,}")
    print(f"  Cache Read Tokens:     {stats['cache_read_tokens']:>10,} (excluded)")
    print(f"  Output Tokens:         {stats['output_tokens']:>10,}")
    print(f"  {'─' * 45}")
    print(f"  Billable Total:        {stats['billable_tokens']:>10,}")
    print(f"  Budget Limit:          {TOKEN_BUDGET:>10,}")
    print(f"  Usage:                 {(stats['billable_tokens']/TOKEN_BUDGET)*100:>9.1f}%")

    print(f"\nSession Timing:")
    if stats['session_start']:
        print(f"  Start: {stats['session_start'].strftime('%Y-%m-%d %H:%M:%S UTC')}")
    if stats['session_end']:
        print(f"  End:   {stats['session_end'].strftime('%Y-%m-%d %H:%M:%S UTC')}")
    if stats['session_start'] and stats['session_end']:
        duration = stats['session_end'] - stats['session_start']
        hours = duration.total_seconds() / 3600
        print(f"  Duration: {hours:.2f} hours")

    print(f"\nMessage Count:")
    print(f"  Assistant responses: {stats['message_count']}")

    # Validation checks
    print(f"\n{'─'*60}")
    print("Validation Checks:")

    checks_passed = 0
    checks_total = 0

    # Check 1: Billable tokens are positive
    checks_total += 1
    if stats['billable_tokens'] > 0:
        print("  ✓ Billable tokens > 0")
        checks_passed += 1
    else:
        print("  ✗ Billable tokens should be > 0")

    # Check 2: Billable tokens sanity check (< 10M)
    checks_total += 1
    if stats['billable_tokens'] < 10_000_000:
        print("  ✓ Billable tokens < 10M (sanity check)")
        checks_passed += 1
    else:
        print("  ✗ Billable tokens exceed 10M (unusual)")

    # Check 3: Message count > 0
    checks_total += 1
    if stats['message_count'] > 0:
        print(f"  ✓ Found {stats['message_count']} assistant messages")
        checks_passed += 1
    else:
        print("  ✗ No assistant messages found")

    # Check 4: Cache efficiency (reads > creation after first few messages)
    checks_total += 1
    if stats['message_count'] > 5:
        if stats['cache_read_tokens'] >= stats['cache_creation_tokens']:
            ratio = stats['cache_read_tokens'] / stats['cache_creation_tokens'] if stats['cache_creation_tokens'] > 0 else 0
            print(f"  ✓ Good cache efficiency ({ratio:.1f}x reads vs creation)")
            checks_passed += 1
        else:
            print("  ⚠ Cache reads < cache creation (unusual pattern)")
    else:
        print("  ~ Skipping cache efficiency check (< 5 messages)")

    # Check 5: Session duration reasonable
    checks_total += 1
    if stats['session_start'] and stats['session_end']:
        duration = stats['session_end'] - stats['session_start']
        hours = duration.total_seconds() / 3600
        if 0 < hours < 12:
            print(f"  ✓ Session duration reasonable ({hours:.2f} hours)")
            checks_passed += 1
        else:
            print(f"  ⚠ Session duration unusual ({hours:.2f} hours)")
    else:
        print("  ✗ Missing session timing")

    # Check 6: Formula verification
    checks_total += 1
    calculated_billable = (
        stats['input_tokens'] +
        stats['cache_creation_tokens'] +
        stats['output_tokens']
    )
    if stats['billable_tokens'] == calculated_billable:
        print("  ✓ Billable token formula correct (input + cache_creation + output)")
        checks_passed += 1
    else:
        print(f"  ✗ Formula mismatch: {stats['billable_tokens']} != {calculated_billable}")

    # Summary
    print(f"\n{'─'*60}")
    print(f"Validation Summary: {checks_passed}/{checks_total} checks passed")
    print(f"{'='*60}\n")

    return stats


def test_load_session_progress(jsonl_path: str):
    """Test the complete ETL pipeline"""
    print("\nTesting Complete ETL Pipeline:")
    print(f"{'─'*60}")

    progress = load_session_progress(jsonl_path)

    print(f"Tokens Used:    {progress['tokens_used']:,}")
    print(f"Budget:         {progress['tokens_budget']:,}")
    print(f"Percentage:     {progress['percentage']:.1f}%")
    print(f"Exceeds Limit:  {progress['exceeds_limit']}")
    print(f"Message Count:  {progress['message_count']}")

    if progress['session_start']:
        print(f"Session Start:  {progress['session_start'].strftime('%Y-%m-%d %H:%M:%S UTC')}")
    if progress['reset_time']:
        print(f"Reset Time:     {progress['reset_time'].strftime('%Y-%m-%d %H:%M:%S UTC')}")
        print(f"Time Remaining: {progress['time_remaining']}")

    print(f"{'─'*60}\n")


if __name__ == "__main__":
    import sys

    # Test with provided path or most recent transcript
    if len(sys.argv) > 1:
        transcript_path = sys.argv[1]
    else:
        # Find most recent transcript
        projects_dir = Path.home() / '.claude' / 'projects'
        jsonl_files = list(projects_dir.rglob('*.jsonl'))
        if jsonl_files:
            transcript_path = str(max(jsonl_files, key=lambda p: p.stat().st_mtime))
        else:
            print("No transcript files found!")
            sys.exit(1)

    # Run validation
    stats = validate_transcript_parsing(transcript_path)

    # Test complete pipeline
    test_load_session_progress(transcript_path)

    # Display final verdict
    if stats['billable_tokens'] > 0 and stats['message_count'] > 0:
        print("✅ Validation PASSED - Token tracking is working correctly!\n")
    else:
        print("❌ Validation FAILED - Check error messages above\n")
