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

#: Pinned Bifrost transport version -- the native ``bifrost-http`` binary.
#:
#: The npm package ``@maximhq/bifrost`` is only a launcher: it downloads the
#: transport from ``downloads.getmaxim.ai`` and resolves ``latest`` on every
#: boot. Unpinned, an upstream release silently replaces the binary on the
#: next restart, which is how a failed boot once took Claude Code down with
#: it. The launcher accepts ``--transport-version`` and strips the flag
#: before exec'ing the binary.
#:
#: Kept in sync with ``BIFROST_TRANSPORT_VERSION`` in
#: ``config/launchd/ai.bifrost.gateway.plist`` by a CI guard test
#: (``tests/unit/test_bifrost_transport_version.py``).
#:
#: To roll back, edit the value in the plist and restart the gateway:
#: launchd's ``EnvironmentVariables`` replace the inherited environment, so
#: an exported ``BIFROST_TRANSPORT_VERSION`` never reaches the launchd job,
#: and ``install_plist()`` re-copies the repo plist over the installed one.
BIFROST_TRANSPORT_VERSION = "v2.4.0"

#: Bifrost's structured request log. This -- not ``LOG_OUT`` -- is where the
#: per-request record with virtual-key attribution actually lives. The stdout
#: log carries only HTTP access lines (see :mod:`mahavishnu.bifrost.verify`).
LOGS_DB = BIFROST_CONFIG_DIR / "logs.db"

STATE_ROOT = Path.home() / ".local" / "state" / "mcp"
LOG_DIR = STATE_ROOT / "logs"
READY_DIR = STATE_ROOT / "ready"

LOG_OUT = LOG_DIR / "bifrost.log"
LOG_ERR = LOG_DIR / "bifrost.err"
READY_FILE = READY_DIR / "bifrost.ready"
