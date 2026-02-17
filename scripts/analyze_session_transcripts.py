#!/usr/bin/env python3
"""Analyze session transcripts to understand token aggregation"""
import json
from pathlib import Path
from datetime import datetime

transcript_dir = Path.home() / ".claude/projects/-Users-les--claude"

transcripts = [
    "45398f7f-1e89-4d8a-8826-9d4424c61559.jsonl",
    "f0250a4c-fba2-46c0-80d8-5fcf15b6827c.jsonl",
    "de731dcd-af58-4098-bb3d-68d4a2e299de.jsonl",
    "4af7a4b7-23f9-4829-9996-084048327157.jsonl",
    "81dff4f8-0f8c-4d19-9bce-27971d9d4b40.jsonl",
    "8985a1bf-70b7-4cd9-a63a-24ca59c8d043.jsonl",
]

for filename in transcripts:
    path = transcript_dir / filename
    if not path.exists():
        print(f"{filename}: NOT FOUND")
        continue

    with open(path, 'r') as f:
        first_line = f.readline()
        try:
            first_entry = json.loads(first_line)
            timestamp = first_entry.get('timestamp', 'N/A')
            print(f"{filename}")
            print(f"  First: {timestamp}")

            # Count tokens
            f.seek(0)
            total_tokens = 0
            for line in f:
                entry = json.loads(line.strip())
                usage = entry.get('message', {}).get('usage', {})
                if usage:
                    total_tokens += usage.get('input_tokens', 0) + usage.get('output_tokens', 0)

            print(f"  Tokens: {total_tokens:,}")
            print()
        except Exception as e:
            print(f"{filename}: ERROR - {e}")
            print()
