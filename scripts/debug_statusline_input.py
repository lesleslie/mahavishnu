#!/usr/bin/env python3
"""
Debug script to capture what Claude Code sends to statusline script
"""
import sys
import json
from datetime import datetime

# Read stdin
input_data = sys.stdin.read()

# Write to debug log
debug_log = '/tmp/statusline_debug.log'
with open(debug_log, 'w') as f:
    f.write(f"=== StatusLine Input Debug - {datetime.now()} ===\n\n")
    f.write("RAW INPUT:\n")
    f.write(input_data)
    f.write("\n\n")

    try:
        data = json.loads(input_data)
        f.write("PARSED JSON:\n")
        f.write(json.dumps(data, indent=2, default=str))
        f.write("\n\n")

        f.write("KEY FIELDS:\n")
        f.write(f"- cost: {data.get('cost')}\n")
        f.write(f"- exceeds_200k_tokens: {data.get('exceeds_200k_tokens')}\n")
        f.write(f"- session_id: {data.get('session_id')}\n")
        f.write(f"- project_path: {data.get('project_path')}\n")
        f.write(f"- transcript_path: {data.get('transcript_path')}\n")
        f.write(f"- session_start: {data.get('session_start')}\n")
        f.write(f"- global_session_start: {data.get('global_session_start')}\n")
        f.write("\n\n")

        f.write("ALL KEYS:\n")
        for key in sorted(data.keys()):
            f.write(f"- {key}\n")
    except json.JSONDecodeError as e:
        f.write(f"JSON PARSE ERROR: {e}\n")

# Output something to statusline (so Claude Code doesn't error)
print("Debugging - check /tmp/statusline_debug.log")
