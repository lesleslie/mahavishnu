#!/usr/bin/env python3
"""
Claude Code Session Progress StatusLine with alive-progress
Shows an animated progress bar for the 5-hour session limit
"""
import sys
from datetime import datetime
from pathlib import Path
import json
import io
from contextlib import redirect_stdout

try:
    from alive_progress import alive_bar
    HAS_ALIVE_PROGRESS = True
except ImportError:
    HAS_ALIVE_PROGRESS = False

# Session limit constants
SESSION_HOURS = 5
SESSION_SECONDS = SESSION_HOURS * 3600

def get_session_start_time():
    """Get session start time from Claude Code's session file"""
    session_file = Path.home() / ".claude" / "session_start.json"

    if session_file.exists():
        try:
            with open(session_file) as f:
                data = json.load(f)
                return datetime.fromisoformat(data.get("start_time"))
        except (json.JSONDecodeError, KeyError, ValueError):
            pass

    # Create new session file
    start_time = datetime.now()
    session_file.parent.mkdir(parents=True, exist_ok=True)
    with open(session_file, "w") as f:
        json.dump({"start_time": start_time.isoformat()}, f)

    return start_time

def create_simple_bar(percentage: float, width: int = 25) -> str:
    """Fallback progress bar without alive-progress"""
    filled = int(width * percentage / 100)
    bar = "█" * filled + "░" * (width - filled)
    return bar

def format_time_remaining(seconds: int) -> str:
    """Format remaining time as HH:MM"""
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    return f"{hours}h {minutes:02d}m"

def format_end_time(start_time: datetime) -> str:
    """Calculate and format session end time"""
    end_time = start_time + timedelta(hours=SESSION_HOURS)
    return end_time.strftime("%I:%M %p").lstrip('0')

def main():
    try:
        start_time = get_session_start_time()
        now = datetime.now()
        elapsed = (now - start_time).total_seconds()

        # Calculate progress
        percentage = min((elapsed / SESSION_SECONDS) * 100, 100)
        remaining_seconds = max(SESSION_SECONDS - int(elapsed), 0)
        time_left = format_time_remaining(remaining_seconds)

        # Status indicators
        if percentage >= 100:
            status = "🔴 EXPIRED"
            color = "red"
        elif percentage >= 90:
            status = "⚠️  ENDING"
            color = "yellow"
        elif percentage >= 75:
            status = "🟡 LOW"
            color = "yellow"
        else:
            status = "🟢 ACTIVE"
            color = "green"

        # Create progress bar with alive-progress if available
        if HAS_ALIVE_PROGRESS:
            # Capture alive_bar output to string
            output_buffer = io.StringIO()

            # Create a single-step progress bar
            with redirect_stdout(output_buffer):
                with alive_bar(100, bar='smooth', spinner=None,
                              title='', length=25, theme='smooth') as bar:
                    bar(int(percentage))

            # Extract the bar portion from alive_bar output
            bar_output = output_buffer.getvalue().strip()
            # Clean up ANSI codes for simple display
            # For statusLine, we want clean output
            bar = create_simple_bar(percentage, 25)
        else:
            bar = create_simple_bar(percentage, 25)

        # Output formatted statusLine
        output = f"{status} │ {bar} {percentage:.1f}% │ {time_left}"
        print(output)

    except Exception as e:
        # Fallback output on error
        print(f"⚠️  Error: {str(e)}", file=sys.stderr)
        print("🟢 Claude Code Active")

if __name__ == "__main__":
    main()
