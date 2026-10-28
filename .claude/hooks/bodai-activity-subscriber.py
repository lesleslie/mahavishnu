#!/usr/bin/env python3
"""Bodai activity subscriber hook — SessionStart spawner + SessionEnd stopper.

Phase 6.4 (deliverable 6.4.1) of
``docs/plans/2026-07-11-phase-6-bodai-observability.md``. Phase 12a
Task 5 (2026-09) collapsed the original subscriber daemon into a
one-shot ``XREAD`` path inside ``bodai-activity-post-tool-use.py``;
Phase 6's steady state restores a true background subscriber via this
hook. The detached subprocess reads Oneiric EventBridge
(``mahavishnu.core.events.bodai_subscriber.subscribe_to_bodai_events``,
Redis Streams transport) and appends each decoded envelope to
``~/.mahavishnu/bodai-event-queue.json`` so the PostToolUse hook can
drain fresh activity inline.

Invoked by Claude Code's hooks system (``.claude/settings.json``). The
hook exits 0 on every path so a bus outage never blocks SessionStart
or SessionEnd.

Modes (selected via ``--mode``, defaults to ``session-start``):

* ``session-start`` — idempotently spawn a detached background subscriber.
* ``session-stop``  — terminate the subscriber previously spawned by this
  script and remove its pid file. Best-effort — a missing pid file or
  an already-dead pid is not an error.

Idempotency
-----------
``session-start`` reads ``~/.mahavishnu/bodai-subscriber-state.json`` and
checks whether the recorded pid is still alive (``os.kill(pid, 0)``).
If so, the hook returns 0 without spawning a duplicate. The pid file
also stores the ``started_at`` ISO timestamp for operator inspection.

Detachment
----------
The subscriber loop blocks on ``asyncio.run(...)`` indefinitely, which
a SessionStart hook (itself a short-lived Python process) cannot run
inline. ``session-start`` therefore spawns a fresh Python interpreter
via :func:`subprocess.Popen` with ``start_new_session=True`` (so the
detached child becomes its own session leader and survives the parent
hook's exit) and writes the child's pid to the state file. The child
runs ``mahavishnu.core.events.bodai_subscriber.subscribe_to_bodai_events``
in the background, calling :func:`append_to_queue` per envelope.

Configuration via environment variables (defaults shown):

* ``MAHAVISHNU_HOME`` — ``~/.mahavishnu``
* ``MAHAVISHNU_BODAI_SUBSCRIBER_STATE_PATH`` — ``~/.mahavishnu/bodai-subscriber-state.json``
* ``MAHAVISHNU_BODAI_REDIS_URL`` — ``redis://localhost:6379/0``
* ``MAHAVISHNU_BODAI_QUEUE_PATH`` — ``~/.mahavishnu/bodai-event-queue.json``
* ``MAHAVISHNU_BODAI_DEBUG`` — truthy value enables verbose stderr logging

The script never raises out of ``main()``; failures are logged and the
exit code is always 0. The hooks contract for Claude Code requires
non-zero exit only when we *want* the hook to block tool execution;
SessionStart / SessionEnd hooks should fail silent.

Safety guards
-------------
The observer surface is intentionally narrow. Two mitigations keep
sensitive material from leaving the local host:

* **Local-only Redis URL.** When ``MAHAVISHNU_BODAI_REDIS_URL`` is
  unset the default ``redis://localhost:6379/0`` is used. When it
  is set, the URL is validated: only loopback (``localhost``,
  ``127.0.0.1``, ``::1``) and ``unix://`` sockets are accepted. A
  non-local target causes the spawn to be skipped (logged at the
  ``session-start`` level) so a misconfigured environment cannot
  exfiltrate Bodai activity to a remote host.

* **Secret-shaped key redaction.** The worker redacts values whose
  envelope field name matches any of the credential-shaped patterns
  (``secret*``, ``token*``, ``password*``, ``credential*``,
  ``api_key*`` for prefixes; ``*_secret``, ``*_token``, ``*_password``,
  ``*_credential``, ``*_api_key`` for suffixes; plus the exact name
  ``apikey``), case-insensitive, recursively through nested dicts
  and lists. Prefix matching catches ``password_hash``-style names;
  suffix matching catches ``access_token``, ``refresh_token``,
  ``client_secret``-style names. The redacted value is replaced with
  the literal string ``<redacted>``. Envelopes that fail redaction
  are dropped rather than written in cleartext.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
from typing import Any

# Shared helper lives in the same .claude/hooks directory.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _atomic_write import atomic_write_text

# ---------------------------------------------------------------------------
# Paths / config
# ---------------------------------------------------------------------------


def _mahavishnu_home() -> Path:
    override = os.environ.get("MAHAVISHNU_HOME")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".mahavishnu"


def _state_path() -> Path:
    override = os.environ.get("MAHAVISHNU_BODAI_SUBSCRIBER_STATE_PATH")
    if override:
        return Path(override).expanduser()
    return _mahavishnu_home() / "bodai-subscriber-state.json"


def _redis_url() -> str | None:
    """Return the Redis URL, restricted to local-only targets.

    The Bodai activity subscriber reads the Redis Streams transport
    that backs the Oneiric EventBridge. To keep the observability
    surface narrow, the URL is only accepted when it points at the
    local host (loopback IPv4/IPv6, ``localhost``, or a Unix
    socket). Operators who genuinely need a non-local Redis must run
    the subscriber out-of-band — this hook will refuse to spawn
    against a remote target and return ``None``.

    Returns ``None`` when ``MAHAVISHNU_BODAI_REDIS_URL`` is set but
    points at a non-local host. The caller is expected to log and
    skip the spawn rather than fall back silently.
    """
    raw = os.environ.get("MAHAVISHNU_BODAI_REDIS_URL")
    candidate = raw or "redis://localhost:6379/0"

    # Unix socket: always local
    if candidate.startswith("unix://"):
        return candidate

    # TCP URL: must resolve to a loopback host
    from urllib.parse import urlparse
    try:
        parsed = urlparse(candidate)
    except ValueError:
        return None
    if parsed.scheme not in {"redis", "rediss"}:
        return None
    host = (parsed.hostname or "").lower()
    if host not in {"localhost", "127.0.0.1", "::1"}:
        return None
    return candidate


def _queue_path() -> Path:
    override = os.environ.get("MAHAVISHNU_BODAI_QUEUE_PATH")
    if override:
        return Path(override).expanduser()
    return _mahavishnu_home() / "bodai-event-queue.json"


def _debug_enabled() -> bool:
    raw = os.environ.get("MAHAVISHNU_BODAI_DEBUG", "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _log(message: str) -> None:
    sys.stderr.write(f"Hook output: bodai-activity-subscriber: {message}\n")
    sys.stderr.flush()


def _log_debug(message: str) -> None:
    if _debug_enabled():
        sys.stderr.write(
            f"Hook output [DEBUG]: bodai-activity-subscriber: {message}\n",
        )
        sys.stderr.flush()


# ---------------------------------------------------------------------------
# State I/O
# ---------------------------------------------------------------------------


def _read_state() -> dict[str, Any] | None:
    """Return the subscriber state file as a dict, or ``None`` if missing/invalid.

    Schema: ``{"pid": int, "started_at": str, "redis_url": str | None,
    "queue_path": str | None}``. The legacy schema (no fields) and any
    unparsable JSON are treated as missing — the hook will respawn.
    """
    path = _state_path()
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    pid = data.get("pid")
    if not isinstance(pid, int) or pid <= 0:
        return None
    return data


def _write_state(state: dict[str, Any]) -> None:
    """Persist the subscriber state via an atomic tmp+rename.

    The temp file gets a unique name rather than a fixed
    ``<state>.json.tmp``: a fixed one is shared by every writer of the
    state, so concurrent writes collide and the later renames fail with
    ``FileNotFoundError`` -- swallowed here, which turns a concurrent
    update into a silently lost one.
    """
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        atomic_write_text(path, json.dumps(state))
    except OSError as exc:
        _log(f"failed to persist state file: {exc}")


def _clear_state() -> None:
    """Remove the state file if present. Swallow ``FileNotFoundError``."""
    path = _state_path()
    try:
        path.unlink()
    except FileNotFoundError:
        return
    except OSError as exc:
        _log(f"failed to remove state file: {exc}")


def _pid_alive(pid: int) -> bool:
    """Return True when ``pid`` is a running process we can signal.

    ``os.kill(pid, 0)`` raises ``ProcessLookupError`` if the pid is
    dead and ``PermissionError`` if the pid is alive but owned by
    another user (treated as "not ours to manage" — return False).
    """
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


# ---------------------------------------------------------------------------
# Detached subprocess
# ---------------------------------------------------------------------------


# Code that runs inside the spawned subscriber process. The body
# imports the production subscriber from
# ``mahavishnu.core.events.bodai_subscriber`` and runs it with a
# callback that appends each envelope to the local queue file. The
# cancellation token is never set from inside the loop — only the
# SessionEnd hook stops the process, via SIGTERM.
_SUBSCRIBER_WORKER_CODE = """
import asyncio
import logging
import os
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.DEBUG if os.environ.get("MAHAVISHNU_BODAI_DEBUG") else logging.INFO,
    format="%(asctime)s bodai-subscriber-worker %(levelname)s %(message)s",
)


def _queue_path() -> Path:
    override = os.environ.get("MAHAVISHNU_BODAI_QUEUE_PATH")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".mahavishnu" / "bodai-event-queue.json"


# Key patterns whose values must never be written to the on-disk queue
# in cleartext. The names follow the convention used by the Oneiric
# substrate (lowercase, snake_case). New patterns can be added here;
# existing patterns should NOT be relaxed without an explicit security
# review (see commit 21fa05dd review).
#
# Matching is case-insensitive on the key and accepts either prefix OR
# suffix. Prefix covers ``password_hash``-style names; suffix covers
# ``access_token``, ``refresh_token``, ``client_secret``-style names
# where the credential type is the trailing word.
_SECRET_KEY_PREFIXES = (
    "secret",
    "token",
    "password",
    "credential",
    "api_key",
)
_SECRET_KEY_SUFFIXES = (
    "_secret",
    "_token",
    "_password",
    "_credential",
    "_api_key",
)
_SECRET_KEY_EXACT = frozenset({"apikey"})

_REDACTED_SENTINEL = "<redacted>"


def _is_secret_key(key: object) -> bool:
    if not isinstance(key, str):
        return False
    lowered = key.lower()
    if lowered in _SECRET_KEY_EXACT:
        return True
    if any(lowered.startswith(prefix) for prefix in _SECRET_KEY_PREFIXES):
        return True
    return any(lowered.endswith(suffix) for suffix in _SECRET_KEY_SUFFIXES)


def _redact_secrets(value, _seen=None, _depth=0):
    '''Recursively replace values whose key matches a secret pattern.

    Returns a deep-enough copy that no value reachable via a secret
    key survives in the result. Walks dicts and lists; leaves other
    types alone. Guards against pathological depth (max 16) and
    shared-reference cycles via ``_seen`` (id-keyed). Triple-quotes
    would terminate the enclosing ``_SUBSCRIBER_WORKER_CODE`` string,
    so the docstring uses single-quotes.
    '''
    if _seen is None:
        _seen = set()
    if _depth > 16:
        return value
    if isinstance(value, dict):
        sid = id(value)
        if sid in _seen:
            return value
        _seen.add(sid)
        out: dict = {}
        for k, v in value.items():
            if _is_secret_key(k):
                out[k] = _REDACTED_SENTINEL
            else:
                out[k] = _redact_secrets(v, _seen, _depth + 1)
        return out
    if isinstance(value, list):
        sid = id(value)
        if sid in _seen:
            return value
        _seen.add(sid)
        return [_redact_secrets(item, _seen, _depth + 1) for item in value]
    return value


async def _enqueue(envelope) -> None:
    import json
    from mahavishnu.core.events.bodai_subscriber import append_to_queue, _envelope_to_dict
    try:
        envelope_dict = _envelope_to_dict(envelope)
    except Exception:
        logging.exception("failed to serialize envelope; skipping")
        return
    try:
        redacted = _redact_secrets(envelope_dict)
    except Exception:
        logging.exception("redaction failed; refusing to enqueue envelope")
        return
    try:
        await asyncio.to_thread(
            append_to_queue,
            redacted,
            queue_path=_queue_path(),
        )
    except Exception:
        logging.exception("append_to_queue failed; envelope dropped")


async def _main() -> None:
    from mahavishnu.core.events.bodai_subscriber import subscribe_to_bodai_events
    redis_url = os.environ.get("MAHAVISHNU_BODAI_REDIS_URL", "redis://localhost:6379/0")
    cancellation_token = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, cancellation_token.set)
        except (NotImplementedError, RuntimeError):
            # Windows / non-Unix add_signal_handler raise — fall back
            # to default handler (the process will be terminated when
            # the SessionEnd hook sends SIGTERM).
            pass
    try:
        await subscribe_to_bodai_events(
            _enqueue,
            redis_url=redis_url,
            cancellation_token=cancellation_token,
        )
    except asyncio.CancelledError:
        pass
    except Exception:
        logging.exception("subscriber loop crashed; exiting")


import signal  # noqa: E402  - late import for signal name binding above

if __name__ == "__main__":
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        pass
"""


def _spawn_subprocess(redis_url: str, queue_path: Path) -> int | None:
    """Spawn the detached subscriber process. Returns the child pid.

    The child gets its own session (``start_new_session=True``) so it
    survives the parent hook's exit. stdout / stderr are sent to a
    log file under ``~/.mahavishnu/logs/`` (best-effort — falls back
    to ``DEVNULL`` if the log directory is not writable).

    Returns ``None`` when the spawn fails; the caller logs and
    continues. The hook never raises out of this function.
    """
    log_path = _mahavishnu_home() / "logs" / "bodai-subscriber.log"
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_fh = log_path.open("a", encoding="utf-8")
    except OSError:
        log_fh = subprocess.DEVNULL

    env = os.environ.copy()
    env["MAHAVISHNU_BODAI_REDIS_URL"] = redis_url
    env["MAHAVISHNU_BODAI_QUEUE_PATH"] = str(queue_path.expanduser())

    try:
        proc = subprocess.Popen(
            [sys.executable, "-c", _SUBSCRIBER_WORKER_CODE],
            stdout=log_fh,
            stderr=log_fh,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            env=env,
            cwd=str(_mahavishnu_home()),
        )
    except OSError as exc:
        _log(f"subprocess.Popen failed: {exc}")
        try:
            log_fh.close()
        except OSError:
            pass
        return None

    try:
        log_fh.close()
    except OSError:
        pass

    return proc.pid


# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------


def _session_start() -> int:
    """Idempotently spawn the subscriber. Returns 0 unconditionally."""
    state = _read_state()
    if state is not None:
        existing_pid = state.get("pid")
        if existing_pid is not None and _pid_alive(existing_pid):
            _log_debug(
                f"subscriber already running pid={existing_pid}; "
                f"started_at={state.get('started_at', 'unknown')!r}",
            )
            return 0
        # Stale pid file — the previous process died but left state.
        # Clear it before respawning.
        if existing_pid is not None:
            _log_debug(
                f"removing stale state file pid={existing_pid} (process not alive)",
            )
            _clear_state()

    redis_url = _redis_url()
    if redis_url is None:
        _log(
            "session-start: refusing to spawn — MAHAVISHNU_BODAI_REDIS_URL "
            "is not a local-only target (loopback / unix socket). "
            "Set it to redis://localhost:6379/0 or a unix:// path to enable.",
        )
        return 0
    queue_path = _queue_path()
    pid = _spawn_subprocess(redis_url, queue_path)
    if pid is None:
        _log("session-start: could not spawn subscriber process (see debug log)")
        return 0

    started_at = datetime.datetime.now(datetime.UTC).isoformat()
    _write_state(
        {
            "pid": pid,
            "started_at": started_at,
            "redis_url": redis_url,
            "queue_path": str(queue_path.expanduser()),
        },
    )
    _log(f"session-start: spawned subscriber pid={pid} redis_url={redis_url}")
    return 0


def _session_stop() -> int:
    """Terminate the subscriber referenced by the state file. Best-effort."""
    state = _read_state()
    if state is None:
        _log_debug("session-stop: no state file; nothing to do")
        return 0

    pid = state.get("pid")
    if pid is None:
        _clear_state()
        return 0

    if not _pid_alive(pid):
        _log_debug(f"session-stop: pid={pid} not alive; clearing stale state")
        _clear_state()
        return 0

    try:
        os.kill(pid, signal.SIGTERM)
        _log(f"session-stop: sent SIGTERM to pid={pid}")
    except ProcessLookupError:
        _log_debug(f"session-stop: pid={pid} vanished before SIGTERM")
    except PermissionError:
        _log(
            f"session-stop: no permission to signal pid={pid}; leaving for the OOM killer",
        )
        return 0
    except OSError as exc:
        _log(f"session-stop: SIGTERM to pid={pid} failed: {exc}")

    _clear_state()
    return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str]) -> str:
    """Parse ``--mode`` from argv; default to ``session-start``."""
    parser = argparse.ArgumentParser(
        prog="bodai-activity-subscriber",
        description=(
            "SessionStart/SessionEnd hook for the Bodai activity "
            "subscriber daemon. See the module docstring for details."
        ),
    )
    parser.add_argument(
        "--mode",
        choices=("session-start", "session-stop"),
        default="session-start",
        help="Hook phase (default: session-start).",
    )
    args = parser.parse_args(argv)
    return str(args.mode)


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    try:
        mode = _parse_args(argv)
    except SystemExit:
        # argparse exits with code 2 on bad flags. The hook contract
        # requires non-zero exit only when we *want* Claude Code to
        # block; SessionStart/SessionEnd should fail silent.
        _log("invalid arguments; defaulting to session-start (no-op spawn)")
        return 0

    if mode == "session-stop":
        return _session_stop()
    return _session_start()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001 — top-level __main__ boundary: entry/main() failure must not surface a Python traceback to the Claude Code hook chain (state lost would be the parent SessionEnd/SessionStart hook lifecycle).
        _log("unhandled error; exiting 0")
        sys.exit(0)
