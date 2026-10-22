"""Filesystem locations and constants for the Bifrost control surface.

Split out from :mod:`mahavishnu.bifrost.models` so both the harness
descriptors and the lifecycle/toggle logic can import them without a cycle.
"""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_BIFROST_HOST = "127.0.0.1"
DEFAULT_BIFROST_PORT = 8471

LAUNCHD_LABEL = "ai.bifrost.gateway"
GUI_DOMAIN = f"gui/{os.getuid()}"

BIFROST_CONFIG_DIR = Path.home() / ".config" / "bifrost"
BIFROST_BACKUP_DIR = BIFROST_CONFIG_DIR

STATE_ROOT = Path.home() / ".local" / "state" / "mcp"
LOG_DIR = STATE_ROOT / "logs"
READY_DIR = STATE_ROOT / "ready"

LOG_OUT = LOG_DIR / "bifrost.log"
LOG_ERR = LOG_DIR / "bifrost.err"
READY_FILE = READY_DIR / "bifrost.ready"
