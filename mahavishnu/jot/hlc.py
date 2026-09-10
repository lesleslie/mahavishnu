"""Hybrid Logical Clock generation, node init, tail-HLC read.

See spec §"HLC generation" and §"HLC continuity across captures".
"""
from __future__ import annotations

import hashlib
import os
import re
import secrets
import socket
import time
from typing import TYPE_CHECKING

from .events import HLC, deserialize

if TYPE_CHECKING:
    from pathlib import Path

# Size of the tail read when looking for the last HLC. See spec §"HLC continuity".
TAIL_SIZE = 65536

_NODE_ID_PATTERN = re.compile(r"^[0-9a-f]{8}$")


class NodePersistError(OSError):
    """Raised when node_init cannot persist the node ID to disk.

    The caller should catch this, log via errors.log, and proceed with the
    in-memory ID (which is still returned by node_init()).
    """


def hlc_now(node: str, last: HLC | None) -> HLC:
    """Generate the next HLC for a given node, monotonically advancing from `last`.

    If `last` is None, or current wall_ms has advanced past last.wall_ms, ctr resets to 0.
    Otherwise, ctr increments by 1 from last.ctr.

    Pure function: no I/O. Safe to call from the hook on every capture.
    """
    wall_ms = int(time.time() * 1000)
    if last is None or wall_ms > last.wall_ms:
        ctr = 0
    else:
        ctr = last.ctr + 1
    return HLC(wall_ms=wall_ms, ctr=ctr, node=node)


def _generate_node_id() -> str:
    """Generate a new 8-hex-char node identifier.

    Format: sha256(hostname)[:4] + 4 hex chars from secrets.
    Total always exactly 8 hex chars (B2 fix).

    Hashing the hostname guarantees the spec invariant (8 lowercase hex chars)
    regardless of hostname content. Raw hostname slicing could include letters
    like 'y', 's', 't' that aren't valid hex chars. The hash preserves
    per-hostname determinism (same hostname → same prefix) without leaking
    the actual hostname in plaintext.
    """
    hostname = socket.gethostname().lower()
    host_part = hashlib.sha256(hostname.encode("utf-8")).hexdigest()[:4]
    random_part = secrets.token_hex(2)  # 4 hex chars
    return f"{host_part}{random_part}"


# Module-level lazy-init cache for the node ID. Tests reset via conftest.py.
_node: str | None = None


def get_node(path: Path) -> str:
    """Return the cached node ID, initializing from disk on first call.

    Spec compliance (B3 fix): the node file is conceptually "read at module
    import" but the implementation defers to first use so tests can reset
    cleanly. The semantic invariant is: every capture in a single process
    uses the same node ID, and the value matches what node_init() reads/creates.

    On first call, invokes node_init(path) which reads or creates the file.
    """
    global _node
    if _node is None:
        _node = node_init(path)
    return _node


def node_init(path: Path) -> str:
    """Read or create the node identifier file.

    If the file exists with a valid 8-hex-char ID, return it.
    Otherwise, generate a new ID, write it (mode 0o600), and return it.

    On write failure (permissions, disk full), raises NodePersistError after
    generating the in-memory ID (B5 fix). The caller logs via errors.log and
    proceeds with the returned ID — capture still succeeds.

    Note: parent directory is created with mode 0o700 via jot_dir() or os.mkdir
    before this is called. node_init does NOT create the parent — that's the
    caller's responsibility.
    """
    if path.exists():
        contents = path.read_text().strip()
        if _NODE_ID_PATTERN.match(contents):
            return contents

    new_id = _generate_node_id()
    try:
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, (new_id + "\n").encode("utf-8"))
        finally:
            os.close(fd)
    except OSError as exc:
        # Raise typed exception so caller can log via _log_error("node_init", ...)
        # The in-memory ID is still usable for HLC; only persistence failed.
        raise NodePersistError(str(exc)) from exc
    return new_id


def read_tail_hlc(log_path: Path) -> HLC | None:
    """Read the last valid HLC from the log file's tail (last 64KB).

    B4 fix: scans ALL lines in the tail (not just the last non-empty line) and
    returns the HLC of the last successfully-parsed line. A truncated final
    line (from SIGKILL mid-write, ENOSPC, or crash) is skipped, preserving the
    HLC monotonicity invariant — the next capture reads the prior valid HLC
    and advances from it instead of resetting ctr to 0.

    Returns None if:
    - The log file doesn't exist or can't be opened
    - The log file is empty
    - No line in the tail is a valid JotEvent JSON
    """
    try:
        file_size = log_path.stat().st_size
    except (FileNotFoundError, OSError):
        return None

    if file_size == 0:
        return None

    try:
        fd = os.open(str(log_path), os.O_RDONLY)
    except (FileNotFoundError, OSError):
        return None

    try:
        seek_to = max(0, file_size - TAIL_SIZE)
        os.lseek(fd, seek_to, os.SEEK_SET)
        data = os.read(fd, file_size - seek_to)
    except OSError:
        return None
    finally:
        os.close(fd)

    text = data.decode("utf-8", errors="replace")
    lines = text.split("\n")

    # B4 fix: iterate in reverse, return HLC of last successfully-parsed line
    for line in reversed(lines):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            event = deserialize(stripped)
            return event.hlc
        except (ValueError, KeyError, TypeError):
            continue  # Skip malformed lines (truncated or corrupt)

    return None
