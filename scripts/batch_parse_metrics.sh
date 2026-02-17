#!/bin/bash
# Batch parse all transcripts for agent metrics

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$HOME/.claude/projects/-Users-les--claude"

echo "Parsing all transcripts in $PROJECT_DIR"
echo "========================================"
echo

count=0
for transcript in "$PROJECT_DIR"/*.jsonl; do
    if [ -f "$transcript" ]; then
        echo "Processing: $(basename "$transcript")"
        python3 "$SCRIPT_DIR/auto_agent_metrics.py" parse "$transcript" 2>&1 | grep -E "Found|invocations"
        count=$((count + 1))
    fi
done

echo
echo "Processed $count transcript files"
echo
echo "Generating report..."
python3 "$SCRIPT_DIR/auto_agent_metrics.py" report --days 365
