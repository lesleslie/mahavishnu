#!/usr/bin/env python3
"""Test runner for backup recovery tests."""

import sys
import subprocess

if __name__ == "__main__":
    # Run the specific test file
    result = subprocess.run([
        sys.executable, "-m", "pytest",
        "tests/unit/test_core/test_backup_recovery_comprehensive.py",
        "-v",
        "--tb=short"
    ])

    print(f"Exit code: {result.returncode}")
    sys.exit(result.returncode)