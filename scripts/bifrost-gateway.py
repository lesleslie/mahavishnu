from __future__ import annotations

"""Bifrost gateway launcher.

Resolves required secrets through Oneiric's ``SecretsHook`` (which reads
``secrets.inline`` from ``~/.config/oneiric/local.yaml`` and may fall back to a
configured adapter), exports them into the Bifrost process environment, then
launches the ``@maximhq/bifrost`` Node binary and supervises its lifecycle.

This replaces the previous shell wrapper ``scripts/bifrost-gateway.zsh`` so
Bifrost consumes secrets via Oneiric's canonical mechanism instead of a flat
``source`` of ``shell-secrets.zsh``. Bifrost itself only ever sees plain
``process.env`` entries; it does not read any application-specific secrets file.
"""

import asyncio
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

from oneiric.core.config import SecretsHook, load_settings
from oneiric.core.lifecycle import LifecycleManager
from oneiric.core.resolution import Resolver, ResolverSettings

# Defaults match the values set in config/launchd/ai.bifrost.gateway.plist.
HOST: str = os.environ.get("BIFROST_HOST", "127.0.0.1")
PORT: int = int(os.environ.get("BIFROST_PORT", "8471"))
LOG_LEVEL: str = os.environ.get("BIFROST_LOG_LEVEL", "info")
LOG_STYLE: str = os.environ.get("BIFROST_LOG_STYLE", "json")
APP_DIR: Path = Path(os.environ.get("BIFROST_APP_DIR", f"{Path.home()}/.config/bifrost"))
READY_FILE: Path = Path(
    os.environ.get("BIFROST_READY_FILE", f"{Path.home()}/.local/state/mcp/ready/bifrost.ready")
)
LOG_DIR: Path = Path.home() / ".local/state/mcp/logs"

# Bifrost config template (relative to repo root, beside this script).
REPO_ROOT: Path = Path(__file__).resolve().parent.parent
TEMPLATE_CONFIG: Path = REPO_ROOT / "config/bifrost/config.template.json"
TARGET_CONFIG: Path = APP_DIR / "config.json"

# Secret IDs the gateway requires at startup. Resolution goes through Oneiric.
NEEDED_KEYS: tuple[str, ...] = ("MINIMAX_API_KEY", "OPENAI_API_KEY")

# Readiness probe budget. Matches the original shell wrapper.
READY_TIMEOUT_SECONDS: int = 60


async def resolve_secrets() -> None:
    """Resolve required Bifrost secrets via Oneiric's ``SecretsHook``.

    ``SecretsHook.get`` checks ``config.inline`` first; if absent and a provider
    is configured, it falls back to the adapter chain. ``inline`` is sufficient
    for the Bifrost activation; future migration to AWS / GCP / Keyring is a
    one-line config change in ``~/.config/oneiric/local.yaml``.
    """
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

    Mirrors the original shell wrapper's preference: ``npx`` writes the package
    under ``~/.npm/_npx/<hash>/node_modules/@maximhq/bifrost/bin.js`` on first
    use. Reusing the cached binary avoids the npx install round-trip on
    subsequent launches.
    """
    npm_npx_root = Path.home() / ".npm" / "_npx"
    if not npm_npx_root.exists():
        return None
    matches = sorted(npm_npx_root.glob("*/node_modules/@maximhq/bifrost/bin.js"))
    return matches[-1] if matches else None


def launch_bifrost() -> subprocess.Popen[bytes]:
    """Spawn the Bifrost Node binary as a supervised subprocess."""
    APP_DIR.mkdir(parents=True, exist_ok=True)
    READY_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    # First-run seed of the gateway config from the repo template. After the
    # initial bootstrap, Bifrost's own ``config_store`` (SQLite) is authoritative
    # and the template is no longer consulted unless ``rebootstrap`` is invoked.
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

    # File handles stay open for the lifetime of the subprocess. The kernel
    # dup's the FD into the child at exec time, so closing the Python handles
    # is safe — but keeping them open is harmless and makes tail/lsof trivial.
    stdout_log = open(LOG_DIR / "bifrost.log", "ab")  # noqa: SIM115
    stderr_log = open(LOG_DIR / "bifrost.err", "ab")  # noqa: SIM115
    return subprocess.Popen(cmd, cwd=APP_DIR, stdout=stdout_log, stderr=stderr_log)


def _port_is_listening(port: int = PORT) -> bool:
    """Return ``True`` iff something is bound to ``127.0.0.1:port`` in LISTEN."""
    try:
        for line in os.popen(f"lsof -nP -iTCP:{port} -sTCP:LISTEN -t 2>/dev/null"):
            if line.strip():
                return True
    except OSError:
        return False
    return False


def wait_for_ready(proc: subprocess.Popen[bytes], timeout: int = READY_TIMEOUT_SECONDS) -> bool:
    """Wait until the gateway binds the configured port, then write the ready file.

    Mirrors the original shell wrapper: it polls ``lsof`` for the listener, and
    writes the ready file itself — Bifrost does not write it. If the child exits
    before binding, propagate its return code instead of timing out.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return False
        if _port_is_listening():
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


def main() -> int:
    asyncio.run(resolve_secrets())
    proc = launch_bifrost()
    try:
        if not wait_for_ready(proc):
            return_code = proc.returncode if proc.poll() is not None else 1
            print(
                f"bifrost did not bind port {PORT} within "
                f"{READY_TIMEOUT_SECONDS}s; see {LOG_DIR}/bifrost.log and bifrost.err",
                file=sys.stderr,
            )
            return return_code
        # Bifrost is up. Supervise it: stay alive as long as the child runs so
        # launchd's KeepAlive sees a healthy long-running process. Drop the
        # ready file and terminate the child on exit.
        return proc.wait() or 0
    finally:
        cleanup(proc)


if __name__ == "__main__":
    sys.exit(main())
