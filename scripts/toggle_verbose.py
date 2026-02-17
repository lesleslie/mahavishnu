#!/usr/bin/env python3
"""Toggle Claude CLI verbose/debug mode programmatically."""

import json
import sys
from pathlib import Path
from typing import Literal


def get_settings_file() -> Path:
    """Get the local settings file path."""
    return Path.cwd() / ".claude" / "settings.local.json"


def read_settings() -> dict:
    """Read current settings."""
    settings_file = get_settings_file()
    if settings_file.exists():
        with open(settings_file) as f:
            return json.load(f)
    return {}


def write_settings(data: dict) -> None:
    """Write settings to file."""
    settings_file = get_settings_file()
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    with open(settings_file, "w") as f:
        json.dump(data, f, indent=2)


def toggle_verbose(mode: Literal["on", "off", "toggle", "status"] = "toggle") -> None:
    """Toggle verbose mode.

    Args:
        mode: "on", "off", "toggle", or "status"
    """
    data = read_settings()

    if mode == "status":
        verbose = data.get("verbose", False)
        debug = data.get("debug", False)
        print(f"Verbose: {verbose}")
        print(f"Debug: {debug}")
        return

    current_verbose = data.get("verbose", False)

    if mode == "toggle":
        new_state = not current_verbose
    elif mode == "on":
        new_state = True
    elif mode == "off":
        new_state = False
    else:
        print(f"❌ Invalid mode: {mode}")
        sys.exit(1)

    data["verbose"] = new_state
    data["debug"] = new_state

    write_settings(data)

    state_emoji = "✅" if new_state else "⚪"
    state_text = "ENABLED" if new_state else "DISABLED"
    print(f"{state_emoji} Verbose mode {state_text}")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "toggle"
    toggle_verbose(mode)  # type: ignore[arg-type]
