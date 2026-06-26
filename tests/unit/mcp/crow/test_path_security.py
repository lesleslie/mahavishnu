"""Tests for mahavishnu.mcp.crow.path_security — workspace containment + SSRF guard.

RED phase: these tests are written first. They will fail with ImportError
until path_security.py is implemented.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from mahavishnu.mcp.crow.path_security import resolve_workspace_path, validate_url


# ---- workspace containment ---------------------------------------------------


def test_resolve_accepts_path_inside_workspace(tmp_path):
    f = tmp_path / "a.py"
    f.touch()
    assert resolve_workspace_path(str(f), tmp_path) == f.resolve()


def test_resolve_rejects_traversal(tmp_path):
    with pytest.raises(PermissionError, match="outside workspace root"):
        resolve_workspace_path("/etc/passwd", tmp_path)


def test_resolve_rejects_null_byte(tmp_path):
    with pytest.raises(PermissionError, match="null byte"):
        resolve_workspace_path("/tmp/a\x00.py", tmp_path)


def test_resolve_rejects_symlink_escaping_workspace(tmp_path):
    """A symlink inside the workspace that points outside must be rejected."""
    link = tmp_path / "escape"
    os.symlink("/etc", link)
    with pytest.raises(PermissionError, match="outside workspace root"):
        resolve_workspace_path(str(link / "passwd"), tmp_path)


# ---- SSRF: scheme + DNS ----------------------------------------------------


def test_validate_url_accepts_https(monkeypatch):
    monkeypatch.setattr(
        "socket.getaddrinfo",
        lambda *_a, **_k: [(None, None, None, None, ("93.184.216.34", 0))],
    )
    validate_url("https://example.com/page")  # must not raise


def test_validate_url_rejects_file_scheme():
    with pytest.raises(ValueError, match="Only http"):
        validate_url("file:///etc/passwd")


def test_validate_url_rejects_no_scheme():
    with pytest.raises(ValueError, match="Only http"):
        validate_url("example.com/page")


def test_validate_url_blocks_private_ip(monkeypatch):
    monkeypatch.setattr(
        "socket.getaddrinfo",
        lambda *_a, **_k: [(None, None, None, None, ("192.168.1.1", 0))],
    )
    with pytest.raises(PermissionError, match="SSRF"):
        validate_url("http://internal.corp/secret")


def test_validate_url_blocks_loopback(monkeypatch):
    monkeypatch.setattr(
        "socket.getaddrinfo",
        lambda *_a, **_k: [(None, None, None, None, ("127.0.0.1", 0))],
    )
    with pytest.raises(PermissionError, match="SSRF"):
        validate_url("http://localhost/admin")


# ---- SSRF: every reserved range --------------------------------------------


@pytest.mark.parametrize(
    "blocked_ip",
    [
        "10.0.0.1",          # RFC 1918
        "172.16.0.1",        # RFC 1918
        "192.168.1.1",       # RFC 1918
        "127.0.0.1",         # loopback
        "169.254.169.254",   # AWS metadata
        "100.64.0.1",        # CGNAT (RFC 6598)
        "0.0.0.0",           # this-network
        "224.0.0.1",         # multicast
        "240.0.0.1",         # reserved
        "::1",               # IPv6 loopback
        "fe80::1",           # IPv6 link-local
        "fc00::1",           # IPv6 unique-local
        "::",                # IPv6 unspecified
        "::ffff:127.0.0.1",  # IPv4-mapped IPv6 — must NOT slip past
    ],
)
def test_validate_url_blocks_all_reserved_ranges(monkeypatch, blocked_ip):
    monkeypatch.setattr(
        "socket.getaddrinfo",
        lambda *_a, **_k: [(None, None, None, None, (blocked_ip, 0))],
    )
    with pytest.raises(PermissionError, match="SSRF"):
        validate_url("http://attacker.example.com/")


def test_validate_url_dns_failure_raises_value_error(monkeypatch):
    import socket as _socket

    def _raise(*_a, **_k):
        raise _socket.gaierror("Name or service not known")

    monkeypatch.setattr("socket.getaddrinfo", _raise)
    with pytest.raises(ValueError, match="DNS resolution failed"):
        validate_url("http://does-not-exist.invalid/")


def test_validate_url_blocks_any_of_multiple_resolved_addrs(monkeypatch):
    """If DNS returns multiple addresses and ANY is private, block."""
    monkeypatch.setattr(
        "socket.getaddrinfo",
        lambda *_a, **_k: [
            (None, None, None, None, ("8.8.8.8", 0)),
            (None, None, None, None, ("10.0.0.1", 0)),  # private — must block
        ],
    )
    with pytest.raises(PermissionError, match="SSRF"):
        validate_url("http://attacker.example.com/")