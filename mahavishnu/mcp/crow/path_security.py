"""Workspace containment + SSRF mitigation for the Bodai crow HTTP server.

Two helpers:

- ``resolve_workspace_path(path, workspace_root)`` — confines filesystem
  access to ``workspace_root``. Follows symlinks before the containment
  check (so a symlink pointing outside is correctly rejected) and rejects
  null bytes early to avoid Path-construction bypasses.
- ``validate_url(url)`` — enforces ``http(s)`` only, resolves DNS, and
  blocks any address falling within the reserved private/loopback/link-local
  ranges enumerated in ``_PRIVATE_NETS``. Catches the IPv4-mapped IPv6
  bypass (``::ffff:127.0.0.1``) via ``_is_blocked`` coercion.

Used by every tool that touches the filesystem or the network.
"""
from __future__ import annotations

import ipaddress
import socket
from pathlib import Path
from urllib.parse import urlparse

# v2 expansion: CGNAT (RFC 6598), this-network, multicast, reserved,
# IPv6 unspecified, and IPv4-mapped IPv6. Each range was added because
# real-world SSRF attempts exploited the gap; the corresponding test in
# tests/unit/mcp/crow/test_path_security.py::test_validate_url_blocks_all_reserved_ranges
# pins coverage.
_PRIVATE_NETS = [
    # IPv4 RFC 1918 private
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    # IPv4 loopback
    ipaddress.ip_network("127.0.0.0/8"),
    # IPv4 link-local (cloud metadata: AWS 169.254.169.254 etc.)
    ipaddress.ip_network("169.254.0.0/16"),
    # CGNAT (RFC 6598)
    ipaddress.ip_network("100.64.0.0/10"),
    # this-network (RFC 1122)
    ipaddress.ip_network("0.0.0.0/8"),
    # IPv4 multicast
    ipaddress.ip_network("224.0.0.0/4"),
    # IPv4 reserved (future use)
    ipaddress.ip_network("240.0.0.0/4"),
    # IPv6 loopback, unspecified, link-local, unique-local
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("::/128"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("fc00::/7"),
    # IPv4-mapped IPv6 — must be checked AFTER .ipv4_mapped coercion below.
    # Without coercion, `::ffff:127.0.0.1` slips past 127.0.0.0/8.
    ipaddress.ip_network("::ffff:0:0/96"),
]


def resolve_workspace_path(path: str, workspace_root: Path) -> Path:
    """Resolve ``path`` and assert it stays inside ``workspace_root``.

    Raises:
        PermissionError: null byte in path, or resolved path is outside root.
    """
    if "\x00" in path:
        raise PermissionError("null byte in path")
    resolved = Path(path).expanduser().resolve()
    root = workspace_root.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise PermissionError(
            f"Path '{resolved}' is outside workspace root '{root}'"
        ) from exc
    return resolved


def _is_blocked(ip: ipaddress._BaseAddress) -> bool:
    """Coerce IPv4-mapped IPv6 to IPv4 then check against _PRIVATE_NETS.

    ``::ffff:127.0.0.1`` would otherwise slip past ``127.0.0.0/8``. Convert
    via ``.ipv4_mapped`` before containment check (RFC 4291 §2.5.5.2).
    """
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        return any(mapped in net for net in _PRIVATE_NETS)
    return any(ip in net for net in _PRIVATE_NETS)


def validate_url(url: str) -> None:
    """Validate that ``url`` is a public http/https endpoint.

    Raises:
        ValueError: non-http scheme, missing scheme, or DNS failure.
        PermissionError: any resolved address falls in _PRIVATE_NETS.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(
            f"Only http/https URLs are allowed, got: {parsed.scheme!r}"
        )
    hostname = parsed.hostname or ""
    try:
        addrs = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise ValueError(f"DNS resolution failed for {hostname!r}: {exc}") from exc
    for _, _, _, _, sockaddr in addrs:
        ip = ipaddress.ip_address(sockaddr[0])
        if _is_blocked(ip):
            raise PermissionError(
                f"URL resolves to private/reserved address {ip} — blocked (SSRF)"
            )