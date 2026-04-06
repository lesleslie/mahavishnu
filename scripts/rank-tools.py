#!/usr/bin/env python3
"""Rank MCP tool modules by quality signals.

Scans all tool files in mahavishnu/mcp/tools/ and outputs a ranked
markdown table with quality scores. Used for I10 tool governance.

Usage:
    uv run python scripts/rank-tools.py
    uv run python scripts/rank-tools.py --min-score 0.7
"""

from __future__ import annotations

import argparse
import math
import os
import re
import sys

TOOL_DIR = os.path.join(os.path.dirname(__file__), "..", "mahavishnu", "mcp", "tools")

WEIGHTS = {
    "tools": 0.4,
    "docs": 0.2,
    "error_handling": 0.2,
    "type_safety": 0.2,
}

DEPRECATION_THRESHOLD = 0.642
LOW_SCORE_THRESHOLD = 0.700


def analyze_module(path: str) -> dict[str, float | int]:
    """Analyze a single tool module and return quality signals."""
    with open(path) as f:
        text = f.read()
    lines = len(text.splitlines())

    # Count tools — both decorator and programmatic registration patterns
    decorator_tools = text.count("@mcp.tool()")
    programmatic_tools = len(re.findall(r"async def \w+\(", text))
    # Only count programmatic if there's a register_* function
    has_register = bool(re.search(r"def register_\w+_tools\(", text))
    tools = decorator_tools if decorator_tools > 0 else (programmatic_tools if has_register else 0)

    docstrings = text.count('"""') // 2
    try_blocks = len(re.findall(r"^\s*try:", text, re.MULTILINE))
    typed_funcs = len(re.findall(r"def\s+\w+\s*\([^)]*\)\s*->", text))

    # Ratios
    doc_ratio = min(docstrings / max(tools, 1), 1.0)
    err_ratio = min(try_blocks / max(tools, 1), 1.0)
    type_ratio = min(typed_funcs / max(tools, 1), 1.0)

    # Tool count normalized (log scale)
    tool_score = min(math.log2(tools + 1) / math.log2(25), 1.0) if tools > 0 else 0

    quality = round(
        tool_score * WEIGHTS["tools"]
        + doc_ratio * WEIGHTS["docs"]
        + err_ratio * WEIGHTS["error_handling"]
        + type_ratio * WEIGHTS["type_safety"],
        3,
    )

    return {
        "tools": tools,
        "lines": lines,
        "docstrings": docstrings,
        "try_blocks": try_blocks,
        "typed_funcs": typed_funcs,
        "quality": quality,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Rank MCP tool modules by quality")
    parser.add_argument(
        "--min-score", type=float, default=0.0, help="Filter modules below this score"
    )
    parser.add_argument(
        "--deprecation-candidates", action="store_true", help="Show only bottom 20%%"
    )
    args = parser.parse_args()

    if not os.path.isdir(TOOL_DIR):
        print(f"Error: Tool directory not found: {TOOL_DIR}", file=sys.stderr)
        return 1

    results = []
    for fname in sorted(os.listdir(TOOL_DIR)):
        if not fname.endswith(".py") or fname == "__init__.py":
            continue
        path = os.path.join(TOOL_DIR, fname)
        stats = analyze_module(path)
        results.append((fname, stats))

    results.sort(key=lambda x: -x[1]["quality"])

    # Apply filters
    if args.deprecation_candidates:
        cutoff = len(results) * 0.2
        results = results[-max(1, int(cutoff)) :]
        results.sort(key=lambda x: -x[1]["quality"])
    elif args.min_score > 0:
        results = [(f, s) for f, s in results if s["quality"] >= args.min_score]

    # Print markdown table
    print("| Rank | Module | Tools | Lines | Docs | Err | Typed | Score |")
    print("|-----:|--------|------:|------:|-----:|----:|------:|------:|")
    for rank, (fname, stats) in enumerate(results, 1):
        flag = " ⚠️" if stats["quality"] < LOW_SCORE_THRESHOLD else ""
        deprecate = " 🔴" if stats["quality"] < DEPRECATION_THRESHOLD else ""
        print(
            f"| {rank} | {fname}{flag}{deprecate} "
            f"| {stats['tools']} | {stats['lines']} | {stats['docstrings']} "
            f"| {stats['try_blocks']} | {stats['typed_funcs']} "
            f"| **{stats['quality']:.3f}** |"
        )

    print(
        f"\nTotal: {len(results)} modules | "
        f"⚠️ = below {LOW_SCORE_THRESHOLD} | 🔴 = below {DEPRECATION_THRESHOLD} (deprecation zone)"
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
