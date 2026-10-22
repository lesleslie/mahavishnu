"""Gateway bind-address and credential reporting.

Port of ``scripts/bifrost-auth-policy``. Originally a fail-closed guard keyed
on "permissive auth only on loopback". That rule was dropped once it was
established that Claude Code *can* present a virtual key
(``ANTHROPIC_CUSTOM_HEADERS``, >= 2.1.227) and Qwen Code can too
(``customHeaders``) -- so a routable bind is no longer a protocol violation.

What remains useful is *reporting*: a routable bind plus a missing virtual key
is still a genuine exposure, so this surfaces it as a risk rather than an
error. No credential store is read; the verdict comes from the live bind
addresses plus what the harness currently has configured.
"""

from __future__ import annotations

from dataclasses import dataclass
import subprocess

from .paths import DEFAULT_BIFROST_HOST, DEFAULT_BIFROST_PORT


@dataclass(frozen=True)
class PolicyReport:
    """Bind-address posture of the running gateway."""

    binds: tuple[str, ...]
    routable: tuple[str, ...]
    credential_configured: bool

    @property
    def reachable_off_host(self) -> bool:
        """True when at least one bind address is not loopback."""
        return bool(self.routable)

    @property
    def risk(self) -> str:
        """One-line risk assessment."""
        if not self.binds:
            return "gateway not running"
        if self.reachable_off_host and not self.credential_configured:
            return "routable bind AND no virtual key configured -- unauthenticated spend"
        if self.reachable_off_host:
            return "routable bind; virtual key configured -- acceptable"
        return "loopback bind -- local only"


def gateway_binds(host: str, port: int) -> tuple[str, ...]:
    """Return every address the gateway is listening on.

    Uses ``lsof`` because it reports the bind address directly rather than
    inferring reachability from a connect result.
    """
    try:
        out = subprocess.run(
            ["lsof", "-nP", "-iTCP:" + str(port), "-sTCP:LISTEN"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except OSError, subprocess.SubprocessError:
        return ()

    found: set[str] = set()
    for line in out.stdout.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 9:
            continue
        address = parts[8].rsplit(":", 1)[0].strip("[]")
        if address:
            found.add(address)
    return tuple(sorted(found))


def is_loopback(address: str) -> bool:
    """True for 127.0.0.0/8 and ::1."""
    return address.startswith("127.") or address == "::1"


def build_report(
    port: int = DEFAULT_BIFROST_PORT,
    host: str = DEFAULT_BIFROST_HOST,
    credential_configured: bool = False,
) -> PolicyReport:
    """Assemble the current posture report."""
    binds = gateway_binds(host, port)
    routable = tuple(a for a in binds if not is_loopback(a))
    return PolicyReport(
        binds=binds,
        routable=routable,
        credential_configured=credential_configured,
    )
