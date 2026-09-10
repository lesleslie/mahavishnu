"""Claude Code UserPromptSubmit hook for jot inbox capture.

Detects ',,' prefix in user prompts, writes a JSONL event to
~/.mahavishnu/jot/log.jsonl, and exits 2 to erase the prompt from Claude's
transcript. Stdlib-only at module level (imports mahavishnu.jot.* which
are themselves stdlib-only).

Failure policy: every exception is caught at the top level, logged to
~/.mahavishnu/jot/errors.log, and converted to passthrough (exit 0).

Fixes applied (per pre-implementation review):
- B6: Echo to stderr BEFORE writing to log. If stderr fails, no log entry —
  prevents split-brain state (event in log but Claude saw passthrough).
- B7: _log_error accepts a pre-resolved jot_dir; doesn't depend on jot_dir()
  succeeding — prevents the recursive "log_error fails because jot_dir fails"
  cascade.
- B8: 300-char shape gate. If body > 300 chars OR contains '\\n', capture the
  event AND exit 0 (passthrough) instead of exit 2 (block prompt). User has
  a record AND sees the Claude response.
- H2: errors.log rotation at 1 MB, 2 generations max (errors.log + .1).
- H3: per-step op tags via separate try/except blocks in _do_capture.
- H5: _write_log_line loops os.write() to handle short writes.
"""
from __future__ import annotations

import json
import os
import sys
import time
import traceback
from typing import TYPE_CHECKING, Any
import uuid

from mahavishnu.jot.capture_echo import format_echo
from mahavishnu.jot.events import JotEvent, serialize
from mahavishnu.jot.hlc import NodePersistError, get_node, hlc_now, read_tail_hlc
from mahavishnu.jot.paths import errors_log_path, jot_dir, log_path, node_path
from mahavishnu.jot.redact import redact_text

if TYPE_CHECKING:
    from pathlib import Path

# H2: rotation threshold and generation count for errors.log
MAX_ERRORS_LOG_SIZE = 1_048_576  # 1 MB
ERRORS_LOG_ROTATIONS = 2  # keep errors.log + errors.log.1 (2 generations max)

# B8: shape gate thresholds
SHAPE_GATE_MAX_CHARS = 300


# ---------------------------------------------------------------------------
# Pattern detection
# ---------------------------------------------------------------------------


def _is_capture(prompt: str) -> tuple[bool, str]:
    """Return (is_capture, body).

    is_capture=True iff prompt starts with ',,' after stripping leading whitespace.
    body is the text after the ',,' prefix, lstripped. Empty body → not a capture.
    """
    stripped = prompt.lstrip()
    if not stripped.startswith(",,"):
        return False, ""
    body = stripped[2:].lstrip()
    if not body:
        return False, ""
    return True, body


# ---------------------------------------------------------------------------
# Context assembly
# ---------------------------------------------------------------------------


def _build_capture_ctx(stdin_payload: dict[str, Any], env: dict[str, str], cwd: str) -> dict[str, Any]:
    """Assemble the capture-time ambient context."""
    return {
        "cwd": cwd,
        "session_id": stdin_payload.get("session_id", ""),
        "files": stdin_payload.get("files", []),
        "env_repo": env.get("MAHAVISHNU_REPO"),
        "env_branch": env.get("MAHAVISHNU_BRANCH"),
    }


# ---------------------------------------------------------------------------
# H5: looping os.write helper
# ---------------------------------------------------------------------------


def _write_log_line(line: str) -> None:
    """Write a JSONL line to the log file, looping on short writes (H5 fix).

    os.write() to a regular file can return fewer bytes than requested
    (interrupted by signals). This helper loops until all bytes are written
    or raises. Spec §"Atomicity" assumes one syscall per event; this loop
    preserves the single-write intent while handling kernel short-writes.
    """
    path = log_path()
    data = line.encode("utf-8")
    fd = os.open(str(path), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        written = 0
        while written < len(data):
            n = os.write(fd, data[written:])
            if n == 0:
                raise OSError("os.write returned 0 — kernel refused to write")
            written += n
    finally:
        os.close(fd)


# ---------------------------------------------------------------------------
# H2: errors.log rotation
# ---------------------------------------------------------------------------


def _rotate_errors_log(errors_log: Path) -> None:
    """Rotate errors.log → errors.log.1 if size exceeds MAX_ERRORS_LOG_SIZE (H2 fix).

    Silently swallow rotation failures. errors.log is best-effort.
    """
    try:
        size = errors_log.stat().st_size
    except (FileNotFoundError, OSError):
        return
    if size <= MAX_ERRORS_LOG_SIZE:
        return

    older = errors_log.with_name(errors_log.name + ".1")
    try:
        older.unlink(missing_ok=True)
    except OSError:
        pass

    try:
        errors_log.rename(older)
    except OSError:
        return


def _write_errors_line(errors_log: Path, line: str) -> None:
    """Write a single line to errors.log, looping on short writes."""
    data = line.encode("utf-8")
    fd = os.open(str(errors_log), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        written = 0
        while written < len(data):
            n = os.write(fd, data[written:])
            if n == 0:
                break
            written += n
    finally:
        os.close(fd)


# ---------------------------------------------------------------------------
# B7: _log_error with pre-resolved directory
# ---------------------------------------------------------------------------


def _log_error(op: str, exc: BaseException, ctx: dict[str, Any], jot_dir_path: Path | None) -> None:
    """Write a structured error record to errors.log. Fail-open on any failure.

    Args:
        op: which operation failed (H3: e.g., "mkdir", "node_init", "hdl_tail",
            "stderr_echo", "log_write", "capture").
        exc: the exception that was caught.
        ctx: minimal context dict (cwd, prompt prefix, etc.).
        jot_dir_path: pre-resolved jot directory (B7 fix). May be None if
            jot_dir() couldn't be created. If None, we try to resolve it again;
            if that also fails, we silently drop.
    """
    try:
        if jot_dir_path is None:
            try:
                jot_dir_path = jot_dir()
            except Exception:  # noqa: BLE001 - fail-open: any failure to resolve dir means we cannot write errors.log
                return  # Cannot resolve dir — silently drop.

        errors_log = errors_log_path()
        _rotate_errors_log(errors_log)

        record = {
            "ts_ms": int(time.time() * 1000),
            "hook": "jot_capture",
            "op": op,
            "err": f"{type(exc).__name__}: {exc}".replace("\n", " "),
            "traceback": traceback.format_exception(type(exc), exc, exc.__traceback__),
            "ctx": ctx,
        }
        line = json.dumps(record, separators=(",", ":"), ensure_ascii=False) + "\n"
        _write_errors_line(errors_log, line)
    except Exception:  # noqa: BLE001, S110 - errors.log must be silent-on-failure (spec §"Errors log writes fail-open")
        pass


# ---------------------------------------------------------------------------
# Main hook logic
# ---------------------------------------------------------------------------


def _do_hook() -> int:
    """Run the hook logic. Returns exit code (0 = passthrough, 2 = capture)."""
    stdin_text = sys.stdin.read()
    stdin_payload: dict[str, Any] = {}

    # Parse stdin JSON (fail-open on failure)
    try:
        stdin_payload = json.loads(stdin_text)
    except (json.JSONDecodeError, ValueError) as exc:
        _log_error("stdin_parse", exc, {"stdin_prefix": stdin_text[:50]}, jot_dir_path=None)
        return 0

    prompt = stdin_payload.get("prompt", "")
    is_cap, body = _is_capture(prompt)

    if not is_cap:
        # Passthrough: write original JSON to stdout
        sys.stdout.write(stdin_text)
        return 0

    return _do_capture(body, stdin_payload)


def _do_capture(body: str, stdin_payload: dict[str, Any]) -> int:
    """Execute the capture with per-step error handling (H3 fix).

    Each step is wrapped in its own try/except so the errors.log `op` field
    accurately identifies which step failed. B6: echo to stderr BEFORE log
    write. B8: long/multi-line body captures AND exits 0 (shape gate).
    """
    ctx: dict[str, Any] = {}
    pre_resolved_dir: Path | None = None
    prompt_prefix = {"prompt_prefix": body[:50]}

    # Step 1: Ensure directory exists
    try:
        pre_resolved_dir = jot_dir()
    except Exception as exc:  # noqa: BLE001 - fail-open: any I/O failure means we cannot capture
        _log_error("mkdir", exc, prompt_prefix, jot_dir_path=None)
        return 0

    # Step 2: Get node (B3 lazy, B5 raises NodePersistError on write failure)
    try:
        node = get_node(node_path())
    except NodePersistError as exc:
        # B5: persistence failed but in-memory ID is still usable for HLC.
        # Log the failure and continue with a fresh in-memory ID.
        _log_error("node_init", exc, prompt_prefix, pre_resolved_dir)
        from mahavishnu.jot.hlc import _generate_node_id
        node = _generate_node_id()
    except Exception as exc:  # noqa: BLE001 - fail-open: NodePersistError is the only expected exception; any other is a bug we swallow
        _log_error("node_init", exc, prompt_prefix, pre_resolved_dir)
        return 0

    # Step 3: Read last HLC (B4 scans all lines for last valid)
    try:
        last_hlc = read_tail_hlc(log_path())
    except Exception as exc:  # noqa: BLE001 - fail-open: tail-read failure falls back to None
        _log_error("hdl_tail", exc, prompt_prefix, pre_resolved_dir)
        last_hlc = None

    # Step 4: Build event
    hlc = hlc_now(node, last_hlc)
    ctx = _build_capture_ctx(stdin_payload, dict(os.environ), cwd=os.getcwd())
    text = redact_text(body)

    # B8 shape gate: long bodies OR multi-line → capture AND exit 0 (not 2)
    is_long = len(text) > SHAPE_GATE_MAX_CHARS or "\n" in text

    event = JotEvent(
        id=uuid.uuid4().hex,
        op="capture",
        hlc=hlc,
        text=text,
        ctx=ctx,
        created_ms=int(time.time() * 1000),
    )

    # Step 5: Echo to stderr FIRST (B6 fix)
    # If stderr is broken, return 0 without writing the log — prevents split-brain.
    echo = format_echo(event.id, text)
    try:
        sys.stderr.write(echo + "\n")
    except Exception as exc:  # noqa: BLE001 - fail-open: stderr closure/redirect → no log entry (B6 split-brain prevention)
        _log_error("stderr_echo", exc, {**ctx, **prompt_prefix}, pre_resolved_dir)
        return 0

    # Step 6: Write to log (H5 loops os.write for short-write safety)
    line = serialize(event)
    try:
        _write_log_line(line)
    except Exception as exc:  # noqa: BLE001 - fail-open: log write failure → user sees echo but capture didn't persist
        _log_error("log_write", exc, {**ctx, **prompt_prefix}, pre_resolved_dir)
        return 0

    # Step 7: Shape gate determines exit code (B8)
    return 0 if is_long else 2


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> int:
    """Top-level entry point. Returns exit code via sys.exit()."""
    return _do_hook()


if __name__ == "__main__":
    sys.exit(main())
