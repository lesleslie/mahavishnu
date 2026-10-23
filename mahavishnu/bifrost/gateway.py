"""Bifrost gateway process supervision.

Port of ``scripts/bifrost-gateway.py``. Behaviour is preserved verbatim --
readiness polling, ready-file handling, stdbuf wrapping, cached-binary
preference, and the Oneiric secret resolution -- so the LaunchAgent's view of
the process does not change when Phase 4 repoints the plist here.

Two subtleties carried over deliberately:

- Bifrost does **not** write the ready file; this module touches it once the
  port is actually bound. That file is the contract ``lifecycle`` gates on.
- Readiness budget is 180s, not the original shell wrapper's 60s. Bifrost
  >= 2.3.0 syncs the MCP library catalog at startup and cold cache takes
  60-180s.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

from .paths import LOG_DIR, LOG_ERR, LOG_OUT, READY_FILE

HOST: str = os.environ.get("BIFROST_HOST", "127.0.0.1")
PORT: int = int(os.environ.get("BIFROST_PORT", "8471"))
LOG_LEVEL: str = os.environ.get("BIFROST_LOG_LEVEL", "info")
LOG_STYLE: str = os.environ.get("BIFROST_LOG_STYLE", "json")
APP_DIR: Path = Path(os.environ.get("BIFROST_APP_DIR", f"{Path.home()}/.config/bifrost"))

#: Repo root, resolved from this file rather than ``__file__`` of a script in
#: ``scripts/`` -- the module now lives in the package.
REPO_ROOT: Path = Path(__file__).resolve().parent.parent.parent
TEMPLATE_CONFIG: Path = REPO_ROOT / "config" / "bifrost" / "config.template.json"
TARGET_CONFIG: Path = APP_DIR / "config.json"

#: Secret IDs the gateway requires at startup. Resolved through Oneiric.
NEEDED_KEYS: tuple[str, ...] = ("MINIMAX_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY")

#: ``~/.config/secrets.env`` -- the operator's credential store. Read directly
#: because launchd spawns this process without a shell, so it inherits none of
#: the interactive environment. Oneiric's ``SecretsHook`` is not a substitute
#: here: it reads ``~/.config/oneiric/local.yaml``, not this file.
SECRETS_ENV: Path = Path.home() / ".config" / "secrets.env"

#: Credentials read from ``secrets.env`` rather than Oneiric. The dashboard
#: setup token belongs here: it is a local admin credential for the loopback
#: gateway, not an upstream provider key, and losing it locks the operator out
#: of the UI with "Dashboard auth is not configured and no setup token is set".
SECRETS_ENV_KEYS: tuple[str, ...] = ("BIFROST_SETUP_TOKEN", "BIFROST_VIRTUAL_KEY")

_ASSIGNMENT = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$")

READY_TIMEOUT_SECONDS: int = 180


def load_secrets_env(keys: tuple[str, ...] = SECRETS_ENV_KEYS) -> dict[str, str]:
    """Read selected assignments from ``~/.config/secrets.env``.

    Values are unquoted in place -- the operator's convention is that shell
    rc files source this file, so quotes are shell syntax, not part of the
    value. Toggling the switch on an existing session cannot retroactively
    change what a launchd child inherited, so both quoted and bare forms are
    accepted and normalised here.
    """
    found: dict[str, str] = {}
    if not SECRETS_ENV.exists():
        return found
    for raw in SECRETS_ENV.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = _ASSIGNMENT.match(line)
        if match is None:
            continue
        name, value = match.group(1), match.group(2)
        if name in keys:
            unquoted = value.strip()
            if len(unquoted) >= 2 and unquoted[0] == unquoted[-1] and unquoted[0] in "\"'":
                unquoted = unquoted[1:-1]
            if unquoted:
                found[name] = unquoted
    return found


async def resolve_secrets() -> None:
    """Resolve required Bifrost secrets via Oneiric's ``SecretsHook``.

    ``SecretsHook.get`` checks ``config.inline`` first; if absent and a
    provider is configured, it falls back to the adapter chain.
    """
    from oneiric.core.config import SecretsHook, load_settings
    from oneiric.core.lifecycle import LifecycleManager
    from oneiric.core.resolution import Resolver, ResolverSettings

    settings = load_settings(project_name="oneiric")
    resolver = Resolver(ResolverSettings())
    lifecycle = LifecycleManager(resolver)
    hook = SecretsHook(lifecycle, settings.secrets)
    for key in NEEDED_KEYS:
        value = await hook.get(key)
        if value is not None:
            os.environ[key] = value


def find_cached_bifrost_bin() -> Path | None:
    """Prefer a previously-npx-cached ``@maximhq/bifrost`` install.

    Reusing the cached binary avoids the npx install round-trip on every
    launch.
    """
    npm_npx_root = Path.home() / ".npm" / "_npx"
    if not npm_npx_root.exists():
        return None
    matches = sorted(npm_npx_root.glob("*/node_modules/@maximhq/bifrost/bin.js"))
    return matches[-1] if matches else None


def wrap_with_line_buffering(cmd: list[str]) -> list[str]:
    """Wrap ``cmd`` with ``stdbuf -oL -eL`` if stdbuf is on PATH.

    Node block-buffers stdout when the stream is not a TTY, which delays
    ``bifrost.log`` emission by seconds and breaks near-real-time log
    assertions downstream. Falls back to the bare command plus a warning when
    stdbuf is unavailable (macOS without coreutils).
    """
    if shutil.which("stdbuf") is None:
        print(
            "bifrost-gateway: stdbuf not on PATH; Node block-buffering may delay "
            "bifrost.log emission. Install coreutils (macOS: 'brew install coreutils') "
            "for line-buffered output.",
            file=sys.stderr,
        )
        return cmd
    return ["stdbuf", "-oL", "-eL", *cmd]


def port_is_listening(port: int | None = None) -> bool:
    """Return ``True`` iff something is bound to the configured port."""
    target = port if port is not None else PORT
    try:
        result = subprocess.run(
            ["lsof", "-nP", "-iTCP:" + str(target), "-sTCP:LISTEN", "-t"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except OSError, subprocess.SubprocessError:
        return False
    return bool(result.stdout.strip())


def launch_bifrost() -> subprocess.Popen[bytes]:
    """Spawn the Bifrost binary as a supervised subprocess."""
    APP_DIR.mkdir(parents=True, exist_ok=True)
    READY_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    # First-run seed from the repo template. After bootstrap Bifrost's own
    # ``config_store`` (SQLite) is authoritative; the template is only
    # consulted again by ``bifrost rebootstrap``.
    if not TARGET_CONFIG.exists() and TEMPLATE_CONFIG.exists():
        shutil.copy(TEMPLATE_CONFIG, TARGET_CONFIG)

    READY_FILE.unlink(missing_ok=True)

    bifrost_args: list[str] = [
        "-host",
        HOST,
        "-port",
        str(PORT),
        "-log-level",
        LOG_LEVEL,
        "-log-style",
        LOG_STYLE,
        "-app-dir",
        str(APP_DIR),
    ]

    cached = find_cached_bifrost_bin()
    if cached is not None:
        cmd: list[str] = ["node", str(cached), *bifrost_args]
    else:
        cmd = ["npx", "-y", "@maximhq/bifrost", *bifrost_args]

    cmd = wrap_with_line_buffering(cmd)

    with open(LOG_OUT, "ab") as stdout_log, open(LOG_ERR, "ab") as stderr_log:
        return subprocess.Popen(cmd, cwd=APP_DIR, stdout=stdout_log, stderr=stderr_log)


def wait_for_ready(proc: subprocess.Popen[bytes], timeout: int = READY_TIMEOUT_SECONDS) -> bool:
    """Poll until the gateway binds its port, then write the ready file.

    Propagates failure if the child exits before binding rather than timing
    out, so a genuine boot error surfaces immediately.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return False
        if port_is_listening():
            READY_FILE.touch()
            return True
        time.sleep(1)
    return False


def cleanup(proc: subprocess.Popen[bytes]) -> None:
    """Best-effort termination: drop the ready file, then stop the child."""
    READY_FILE.unlink(missing_ok=True)
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


def serve() -> int:
    """Run the gateway in the foreground until the child exits.

    This is what the LaunchAgent execs. Staying alive as the supervisor keeps
    launchd's KeepAlive seeing a healthy long-running process.
    """
    asyncio.run(resolve_secrets())
    # Copy BIFROST_SETUP_TOKEN and BIFROST_VIRTUAL_KEY from the operator's
    # credential store into this process environment so the spawned gateway
    # inherits them. Without BIFROST_SETUP_TOKEN the dashboard refuses to
    # start ("Dashboard auth is not configured and no setup token is set");
    # setdefault leaves an already-exported value alone.
    for key, value in load_secrets_env().items():
        os.environ.setdefault(key, value)
    proc = launch_bifrost()
    try:
        if not wait_for_ready(proc):
            return_code = proc.returncode if proc.poll() is not None else 1
            print(
                f"bifrost did not bind port {PORT} within {READY_TIMEOUT_SECONDS}s; "
                f"see {LOG_OUT} and {LOG_ERR}",
                file=sys.stderr,
            )
            return return_code
        return proc.wait() or 0
    finally:
        cleanup(proc)
