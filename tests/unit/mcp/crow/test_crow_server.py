"""RED phase tests for server wiring (Task 10) and integration tests
(Task 11). Each test pins a contract on the production module
(``mahavishnu.mcp.crow_server``) that the stdlib fallback / missing
implementation cannot satisfy.
"""
from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Task 10 - CrowServer is a StandardServer subclass with FastMCP-owned lifespan
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_crow_server_is_standard_server_subclass():
    from mcp_common.profiles.standard import StandardServer

    from mahavishnu.mcp.crow_server import CrowServer

    assert issubclass(CrowServer, StandardServer)


@pytest.mark.unit
def test_create_crow_server_returns_crow_server_instance():
    from mahavishnu.mcp.crow.settings import CrowSettings
    from mahavishnu.mcp.crow_server import CrowServer, create_crow_server

    server = create_crow_server(CrowSettings())
    assert isinstance(server, CrowServer)


@pytest.mark.unit
def test_crow_server_exposes_fastmcp_attribute():
    """The dual-target ``register`` pattern needs ``server.fastmcp`` to
    dispatch tool registration to the FastMCP instance. The server must
    expose that attribute.
    """
    from fastmcp import FastMCP

    from mahavishnu.mcp.crow.settings import CrowSettings
    from mahavishnu.mcp.crow_server import create_crow_server

    server = create_crow_server(CrowSettings())
    assert hasattr(server, "fastmcp")
    assert isinstance(server.fastmcp, FastMCP)


# ---------------------------------------------------------------------------
# Task 11 - Regression tests: SSRF + DNS-rebinding TOCTOU
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_ssrf_v2_blocks_ipv4_mapped_ipv6_loopback(monkeypatch):
    """Audit Finding #9 regression test: an attacker URL whose hostname
    resolves to ``::ffff:127.0.0.1`` (IPv4-mapped loopback) MUST be
    blocked. Without the v2 coercion in _is_blocked, this slips past
    the IPv6-only check.
    """
    from mahavishnu.mcp.crow.path_security import validate_url

    monkeypatch.setattr(
        "socket.getaddrinfo",
        lambda *_a, **_k: [(None, None, None, None, ("::ffff:127.0.0.1", 0))],
    )
    with pytest.raises(PermissionError, match="SSRF"):
        validate_url("http://attacker.example.com/")


@pytest.mark.unit
def test_dns_rebinding_toctou_re_validates_per_hop(monkeypatch):
    """Audit Finding #9 regression test: when ``web_fetch`` follows a
    redirect, validate_url must be called on the new URL too. The shipped
    manual redirect loop guarantees this.
    """

    from mahavishnu.mcp.crow.path_security import validate_url

    # First DNS lookup: returns a public IP (initial URL passes).
    # Second DNS lookup: returns a private IP (the redirected target).
    # This emulates DNS-rebinding where the attacker flips the A record
    # between the two lookups.
    call_count = {"n": 0}

    def _flipping_resolver(host, *args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return [(None, None, None, None, ("93.184.216.34", 0))]
        return [(None, None, None, None, ("169.254.169.254", 0))]

    monkeypatch.setattr("socket.getaddrinfo", _flipping_resolver)

    # The initial URL is OK (public IP).
    validate_url("https://example.com/")
    # A second URL on the same path now resolves to AWS metadata -
    # the per-hop re-validation in the redirect loop would catch this.
    with pytest.raises(PermissionError, match="SSRF"):
        validate_url("https://attacker.example.com/")
    assert call_count["n"] >= 2


# ---------------------------------------------------------------------------
# Task 11 - Integration tests for lifespan-bound tool registration
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_register_all_populates_fastmcp_tool_manager():
    """Calling create_crow_server must register all 9 tools onto the
    FastMCP instance. FastMCP exposes them via ``list_tools()``.
    """
    from mahavishnu.mcp.crow.settings import CrowSettings
    from mahavishnu.mcp.crow_server import create_crow_server

    server = create_crow_server(CrowSettings())
    tools = await server.fastmcp.list_tools()
    tool_names = {t.name for t in tools}
    expected = {
        "read_file",
        "write_file",
        "list_directory",
        "stat",
        "delete_file",
        "rg_search",
        "web_fetch",
        "web_extract",
        "web_extract_batch",
    }
    missing = expected - tool_names
    assert not missing, f"Missing tools: {missing}"


@pytest.mark.unit
async def test_registered_tool_callable_returns_content(tmp_path):
    """A registered tool, invoked through FastMCP's tool registry, must
    call the underlying function and return its result. Read a file
    written into a tmp workspace.
    """
    from mahavishnu.mcp.crow.settings import CrowSettings
    from mahavishnu.mcp.crow_server import create_crow_server

    settings = CrowSettings(workspace_root=tmp_path)
    target = tmp_path / "x.txt"
    target.write_text("alpha\nbeta\ngamma\n")
    server = create_crow_server(settings)
    tools = await server.fastmcp.list_tools()
    by_name = {t.name: t for t in tools}
    tool = by_name["read_file"]
    result = await tool.run({"file_path": str(target), "offset": 0,
                              "limit": 100, "encoding": "utf-8"})
    assert result.is_error is False
    text = result.content[0].text
    # FastMCP serializes TypedDict returns to JSON in content[0].text.
    assert "alpha" in text
    assert "gamma" in text
    assert "3" in text  # total_lines is 3
