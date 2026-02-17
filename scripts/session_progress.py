#!/usr/bin/env python3
"""
Claude Code Session Progress StatusLine
Shows a progress bar for the 5-hour session limit using alive-progress
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path
import json

# Session limit constants
SESSION_HOURS = 5
SESSION_SECONDS = SESSION_HOURS * 3600

def get_session_start_time():
    """Get session start time from Claude Code's session file"""
    # Claude Code typically stores session info in ~/.claude/
    session_file = Path.home() / ".claude" / "session_start.json"

    if session_file.exists():
        try:
            with open(session_file) as f:
                data = json.load(f)
                return datetime.fromisoformat(data.get("start_time"))
        except (json.JSONDecodeError, KeyError, ValueError):
            pass

    # Fallback: create new session file
    start_time = datetime.now()
    session_file.parent.mkdir(parents=True, exist_ok=True)
    with open(session_file, "w") as f:
        json.dump({"start_time": start_time.isoformat()}, f)

    return start_time

def create_progress_bar(percentage: float, width: int = 30) -> str:
    """Create a simple ASCII progress bar"""
    filled = int(width * percentage / 100)
    bar = "█" * filled + "░" * (width - filled)
    return bar

def format_time_remaining(seconds: int) -> str:
    """Format remaining time as HH:MM"""
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    return f"{hours}h {minutes:02d}m"

def main():
    try:
        start_time = get_session_start_time()
        now = datetime.now()
        elapsed = (now - start_time).total_seconds()

        # Calculate progress
        percentage = min((elapsed / SESSION_SECONDS) * 100, 100)
        remaining_seconds = max(SESSION_SECONDS - int(elapsed), 0)

        # Create progress bar
        bar = create_progress_bar(percentage, width=25)
        time_left = format_time_remaining(remaining_seconds)

        # Status indicators
        if percentage >= 100:
            status = "🔴 SESSION EXPIRED"
        elif percentage >= 90:
            status = "⚠️  SESSION ENDING"
        elif percentage >= 75:
            status = "🟡 TIME LOW"
        else:
            status = "🟢 ACTIVE"

        # Output formatted statusLine
        output = f"{status} │ {bar} {percentage:.1f}% │ {time_left} left"
        print(output)

    except Exception as e:
        # Fallback output on error
        print(f"⚠️  Session tracking error: {str(e)}", file=sys.stderr)
        print("🟢 Claude Code Active")

if __name__ == "__main__":
    main()
