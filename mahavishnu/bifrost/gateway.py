"""Bifrost gateway process supervision.

Port of ``scripts/bifrost-gateway.py``. Behaviour is preserved verbatim --
readiness polling, ready-file handling, stdbuf wrapping, cached-binary
preference, and the Oneiric secret resolution -- so the LaunchAgent's view of
the process does not change when Phase 4 repoints the plist here.

Two subtleties carried over deliberately:

- Bifrost does **not** write the ready file; this module touches it once the
  port is actually bound. That file is the contract ``lifecycle`` gates on.
- Readiness budget is :data:`READY_TIMEOUT_SECONDS` (600s), not the
  original shell wrapper's 60s. Bifrost >= 2.3.0 syncs the MCP library
  catalog at startup and a cold cache takes minutes on a loaded host.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

from .paths import (
    BIFROST_TRANSPORT_VERSION,
    LOG_DIR,
    LOG_ERR,
    LOG_OUT,
    READY_FILE,
)

HOST: str = os.environ.get("BIFROST_HOST", "127.0.0.1")
PORT: int = int(os.environ.get("BIFROST_PORT", "8471"))
LOG_LEVEL: str = os.environ.get("BIFROST_LOG_LEVEL", "info")
LOG_STYLE: str = os.environ.get("BIFROST_LOG_STYLE", "json")
APP_DIR: Path = Path(
    os.environ.get("BIFROST_APP_DIR", f"{Path.home()}/.config/bifrost")
)

#: Transport version handed to the launcher. Pinned rather than tracking
#: ``latest`` so an upstream release cannot change the binary under a running
#: deployment; override to roll back to a known-good build.
TRANSPORT_VERSION: str = os.environ.get(
    "BIFROST_TRANSPORT_VERSION", BIFROST_TRANSPORT_VERSION
)

#: How many times the supervisor re-launches the gateway when the launcher
#: dies immediately.
#:
#: macOS evaluates an unsigned binary that carries ``com.apple.provenance``
#: the first time it is exec'd, and denies that exec with EACCES while the
#: assessment runs. The launcher's own exec test is what trips it, so the
#: launcher dies within a second and the gateway never comes up. The
#: assessment finishes on its own -- usually within a couple of minutes --
#: and the next attempt succeeds. Relying on launchd's 30-second
#: ``ThrottleInterval`` to retry turns a two-second problem into a
#: two-minute outage, and ``mahavishnu bifrost restart`` burns its whole
#: 660-second ready budget waiting on a file that waiting would never fix.
LAUNCH_ATTEMPTS: int = 6

#: A launcher that dies inside this many seconds failed to start; it did not
#: time out. The distinction decides whether a retry is worth making.
LAUNCH_FAILURE_SECONDS: float = 30.0

#: Seconds to wait between launch attempts.
LAUNCH_RETRY_BACKOFF_SECONDS: float = 5.0

#: Repo root, resolved from this file rather than ``__file__`` of a script in
#: ``scripts/`` -- the module now lives in the package.
REPO_ROOT: Path = Path(__file__).resolve().parent.parent.parent
TEMPLATE_CONFIG: Path = REPO_ROOT / "config" / "bifrost" / "config.template.json"
TARGET_CONFIG: Path = APP_DIR / "config.json"

#: Secret IDs the gateway requires at startup. Resolved through Oneiric.
#:
#: ``LLAMA_SERVER_API_KEY`` is here because the Bifrost config declares
#: the local provider's key as ``env.LLAMA_SERVER_API_KEY``. Without the
#: variable in the gateway's environment the key cannot resolve, Bifrost
#: drops it, and every request for the local model fails with
#: ``no_key_supports_model`` -- which silently pushed the
#: ``background`` / ``classify`` governance rules onto the cloud
#: provider. The value is a placeholder, not a secret: the local
#: llama-server does not verify it.
#:
#: ``TYPESAFE_API_KEY`` is here for the same reason. The Bifrost config
#: declares the ``typesafe`` provider's key as ``env.TYPESAFE_API_KEY``,
#: and the complexity analyzer's decision classifier resolves through that
#: provider. The key is not in the gateway's environment, Bifrost drops it
#: at startup, and every classification fails with
#: ``no_key_supports_model`` -- which surfaces as "the complexity router
#: never produces a tier" rather than as a credential error.
# req: REQ-BIFROST-036
NEEDED_KEYS: tuple[str, ...] = (
    "MINIMAX_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "LLAMA_SERVER_API_KEY",
    "TYPESAFE_API_KEY",
)

#: ``~/.config/secrets.env`` -- the operator's credential store. Read directly
#: because launchd spawns this process without a shell, so it inherits none of
#: the interactive environment. Oneiric's ``SecretsHook`` is not a substitute
#: here: it reads ``~/.config/oneiric/local.yaml``, not this file.
SECRETS_ENV: Path = Path.home() / ".config" / "secrets.env"

#: Credentials read from ``secrets.env`` rather than Oneiric.
#:
#: The two Bifrost-local credentials belong here: the dashboard setup token is
#: a local admin credential for the loopback gateway, not an upstream provider
#: key, and losing it locks the operator out of the UI with "Dashboard auth is
#: not configured and no setup token is set".
#:
#: The upstream provider keys are included deliberately even though
#: :func:`resolve_secrets` asks Oneiric for them first. This deployment has no
#: Oneiric secrets provider configured -- every boot logs
#: ``no-secrets-provider-configured`` -- so that resolution returns nothing and
#: these are the only thing that provisions them. The gateway process
#: demonstrably receives them today (upstream calls authenticate), but by a
#: path this module cannot see, so depending on it makes the guarantee
#: untestable. Reading them here makes it explicit and setdefault-safe.
SECRETS_ENV_KEYS: tuple[str, ...] = (
    "BIFROST_SETUP_TOKEN",
    "BIFROST_VIRTUAL_KEY",
    *NEEDED_KEYS,
)

_ASSIGNMENT = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$")

#: How long the supervisor waits for the transport binary to bind the port
#: before it gives up on the child and kills it.
#:
#: The window has to clear the **worst** observed cold start, not the typical
#: one. Measured on 2026-11-06: 5m29s (329s) from launchd spawn to the UI
#: accepting connections, on a host whose load average peaked at 131 while the
#: rest of the MCP fleet was starting. A warm boot is ~26s, but the boot that
#: matters is the one where the gateway is launched *alongside* the fleet --
#: exactly the conditions that produced the 5m29s figure.
#:
#: The previous 180s came from the upstream 60-180s guidance, which does not
#: hold on this host. A budget shorter than the real cold start makes the
#: supervisor kill a healthy gateway mid-boot, and the dashboard never comes
#: up at all.
# req: REQ-BIFROST-045
READY_TIMEOUT_SECONDS: int = 600


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
            if (
                len(unquoted) >= 2
                and unquoted[0] == unquoted[-1]
                and unquoted[0] in "\"'"
            ):
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


def _launcher_version(launcher: Path) -> tuple[int, ...]:
    """The cached launcher's package version, as a comparable tuple.

    npm's ``_npx`` cache directories are named by an opaque hash, so the
    directory name carries no version information at all. The version lives
    in the ``package.json`` next to the launcher.
    """
    try:
        data = json.loads(
            (launcher.parent / "package.json").read_text(encoding="utf-8")
        )
        version = str(data["version"])
    except OSError, ValueError, KeyError, TypeError:
        return ()
    parts: list[int] = []
    for chunk in version.split("."):
        digits = "".join(ch for ch in chunk if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def find_cached_bifrost_bin(npm_npx_root: Path | None = None) -> Path | None:
    """Prefer a previously-npx-cached ``@maximhq/bifrost`` install.

    Reusing the cached binary avoids the npx install round-trip on every
    launch.

    The candidates are ordered by the **package version**, not by path.
    npm's cache directories are named by a hash, so sorting by path picks
    whichever hash happens to sort last -- which on this host was the
    *older* launcher (1.6.2 instead of 1.6.3). That matters beyond
    tidiness: the newer launcher validates the arguments it forwards to the
    transport binary against a known-flag list, while the older one forwards
    them verbatim, and the binary refuses to boot on a flag it does not
    know.
    """
    root = npm_npx_root if npm_npx_root is not None else Path.home() / ".npm" / "_npx"
    if not root.exists():
        return None
    matches = sorted(root.glob("*/node_modules/@maximhq/bifrost/bin.js"))
    if not matches:
        return None
    return max(matches, key=lambda path: (_launcher_version(path), str(path)))


def launcher_supports_transport_version(launcher: Path) -> bool:
    """Whether a cached launcher understands ``--transport-version``.

    The launcher parses the flag out of its own argv and *removes* it before
    exec'ing the transport binary. A launcher too old to know the flag would
    forward it to the binary instead, and the binary rejects unknown flags
    and refuses to boot. A pinned version must therefore never be handed to a
    launcher that cannot parse it -- fall back to ``npx`` in that case.

    The check is deliberately conservative: it requires both the flag *and*
    the argument-removal idiom, because a launcher that merely mentions the
    flag (a comment, a help string) would forward it. It is a heuristic, not
    a proof -- the false-positive needs a launcher that mentions the flag
    and splices arguments for unrelated reasons -- but every uncertainty
    resolves to ``npx``, which always resolves a current launcher.
    """
    try:
        source = launcher.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return "--transport-version" in source and "splice" in source


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


#: Bytes of the gateway's stderr log read from the end when counting
#: config-store contention. The file grows without bound, and the failures
#: cluster in time, so the tail is what carries the signal.
CONTENTION_TAIL_BYTES = 4 * 1024 * 1024

#: The failure text Bifrost emits when a background job cannot take the
#: config store's write lock.
CONTENTION_MARKER = "database is locked"

_LOG_TIME_RE = re.compile(r'"time"\s*:\s*"([^"]+)"')


def config_store_contention(window_hours: int = 24) -> tuple[int, str | None]:
    """Count the config-store write failures the gateway logged recently.

    Returns ``(count, most_recent_timestamp)``.

    Bifrost's background jobs -- the expired-flow sweeps, the pricing and
    model-parameter syncs, the virtual-key cleanup -- write to the config
    store with no busy timeout, so a writer that cannot take the lock fails
    immediately instead of waiting for it. When another writer holds the
    lock, every one of those jobs fails on its next tick, and the failure
    is invisible from the gateway's own surface: ``/health`` reports
    ``db_pings: ok`` because a ping tests connectivity, not contention, and
    nothing in the request path reads the sweeps.

    The stderr log is the only place the failure is recorded, so that is
    where this reads. It is a log scan rather than a first-class signal
    because Bifrost exposes no such signal; the alternative is a condition
    that only a human reading the log ever discovers.

    # req: REQ-BIFROST-050
    """
    log = LOG_ERR
    if not log.exists():
        return 0, None

    try:
        with log.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - CONTENTION_TAIL_BYTES))
            chunk = handle.read()
    except OSError:
        return 0, None

    # The seek can land mid-line; the first fragment is not a record.
    text = chunk.decode("utf-8", errors="replace")
    lines = text.splitlines()[1:] if size > CONTENTION_TAIL_BYTES else text.splitlines()

    cutoff = time.time() - (window_hours * 3600)
    count = 0
    latest: str | None = None
    latest_epoch = 0.0
    for line in lines:
        if CONTENTION_MARKER not in line:
            continue
        match = _LOG_TIME_RE.search(line)
        if match is None:
            continue
        stamp = match.group(1)
        try:
            when = datetime.fromisoformat(stamp)
        except ValueError:
            continue
        epoch = when.timestamp()
        if epoch < cutoff:
            continue
        count += 1
        if epoch > latest_epoch:
            latest_epoch = epoch
            latest = stamp

    return count, latest


def transport_cache_dir() -> Path:
    """Where the npm launcher caches the transport binary for the pinned version.

    Mirrors the launcher's own ``cacheDir()`` so this looks where the
    launcher writes. The launcher names the file ``bifrost-http`` and then
    appends the fallback index, so the file on disk is ``bifrost-http-0``.
    """
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Caches"
    elif sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", "")) or (
            Path.home() / "AppData" / "Local"
        )
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", "")) or (Path.home() / ".cache")
    return base / "bifrost" / TRANSPORT_VERSION / "bin"


def cached_transport_binaries() -> list[Path]:
    """The transport binaries the launcher has cached for the pinned version."""
    directory = transport_cache_dir()
    if not directory.is_dir():
        return []
    return sorted(p for p in directory.glob("bifrost-http*") if p.is_file())


# req: REQ-BIFROST-049
def ensure_transport_executable() -> list[Path]:
    """Give the cached transport binaries their execute bit.

    The npm launcher chmods the binary inside ``downloadBinary``, and the
    download is skipped whenever the file already exists in the cache. A
    binary that landed without its execute bit is therefore exec'd exactly
    as it was found, on every boot, and fails with EACCES -- and because the
    download is what would have fixed it, nothing upstream repairs it:
    launchd retries the same unusable file every ``ThrottleInterval``.

    Repairing the mode is cheap, idempotent, and safe. The file is a cache
    entry the launcher re-downloads on demand, so touching its mode carries
    no risk.
    """
    repaired: list[Path] = []
    for binary in cached_transport_binaries():
        try:
            if binary.stat().st_mode & 0o111:
                continue
            binary.chmod(0o755)
        except OSError:
            continue
        repaired.append(binary)
    return repaired


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
        # Consumed by the launcher, not the transport binary.
        f"--transport-version={TRANSPORT_VERSION}",
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
    if cached is not None and launcher_supports_transport_version(cached):
        cmd: list[str] = ["node", str(cached), *bifrost_args]
    else:
        cmd = ["npx", "-y", "@maximhq/bifrost", *bifrost_args]

    # The launcher chmods the transport binary only on the download path, and
    # the download is skipped when the file is already cached -- so a cached
    # binary that landed without its execute bit is exec'd as it was found
    # and fails with EACCES on every boot. Repair the mode before spawning.
    repaired = ensure_transport_executable()
    if repaired:
        print(
            "bifrost-gateway: restored the execute bit on "
            + ", ".join(str(p) for p in repaired),
            file=sys.stderr,
        )

    cmd = wrap_with_line_buffering(cmd)

    with open(LOG_OUT, "ab") as stdout_log, open(LOG_ERR, "ab") as stderr_log:
        return subprocess.Popen(cmd, cwd=APP_DIR, stdout=stdout_log, stderr=stderr_log)


def wait_for_ready(
    proc: subprocess.Popen[bytes], timeout: int = READY_TIMEOUT_SECONDS
) -> bool:
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

    A launcher that dies before it binds is re-launched rather than left to
    launchd's ``ThrottleInterval``: the denied exec it hit on 2026-11-20 was
    transient, and waiting 30 seconds for launchd to retry turned a
    two-second problem into a two-minute outage.

    # req: REQ-BIFROST-049
    """
    asyncio.run(resolve_secrets())
    # Provision the gateway from the operator's credential store. Oneiric runs
    # first because it is the intended abstraction; setdefault means anything
    # it resolved stays authoritative. In this deployment Oneiric has no
    # secrets provider, so this loop is what actually provisions the
    # credentials -- including BIFROST_SETUP_TOKEN, without which the
    # dashboard refuses to start ("Dashboard auth is not configured and no
    # setup token is set").
    for key, value in load_secrets_env().items():
        os.environ.setdefault(key, value)
    # The clock starts *before* the spawn. ``launch_bifrost`` forks a large
    # interpreter and execs a launcher that can stall on its own network
    # fetch; none of that time counts if the deadline is anchored after it.
    deadline = time.monotonic() + READY_TIMEOUT_SECONDS
    for attempt in range(1, LAUNCH_ATTEMPTS + 1):
        spawned_at = time.monotonic()
        proc = launch_bifrost()
        try:
            if wait_for_ready(proc, timeout=max(1, int(deadline - time.monotonic()))):
                return proc.wait() or 0
            died_immediately = (
                proc.poll() is not None
                and (time.monotonic() - spawned_at) < LAUNCH_FAILURE_SECONDS
            )
            if died_immediately and attempt < LAUNCH_ATTEMPTS:
                # The launcher died before it could bind. That is the
                # signature of a denied exec rather than a slow boot, and
                # the next attempt is worth making: macOS's first-exec
                # assessment on a freshly downloaded binary is transient,
                # and the attempt after it succeeds.
                print(
                    f"bifrost launcher exited immediately "
                    f"(attempt {attempt} of {LAUNCH_ATTEMPTS}); retrying in "
                    f"{LAUNCH_RETRY_BACKOFF_SECONDS:.0f}s",
                    file=sys.stderr,
                )
                time.sleep(LAUNCH_RETRY_BACKOFF_SECONDS)
                continue
            if died_immediately:
                print(
                    f"bifrost launcher exited immediately "
                    f"({LAUNCH_ATTEMPTS} attempts); see {LOG_OUT} and {LOG_ERR}",
                    file=sys.stderr,
                )
                return proc.returncode or 1
            return_code = proc.returncode if proc.poll() is not None else 1
            print(
                f"bifrost did not bind port {PORT} within {READY_TIMEOUT_SECONDS}s; "
                f"see {LOG_OUT} and {LOG_ERR}",
                file=sys.stderr,
            )
            return return_code
        finally:
            cleanup(proc)
