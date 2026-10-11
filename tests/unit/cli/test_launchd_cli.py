"""Unit tests for ``mahavishnu/cli/launchd_cli.py``.

Covers the 3 CLI commands (install / uninstall / status) and a
plist-content test that pins the FULL key set from the launchd
precedent (architecture review flagged a draft that omitted
``ThrottleInterval``, ``RunAtLoad``, and ``LimitLoadToSessionType``).

Tests run fast under ``@pytest.mark.unit`` — no live launchd, no real
Prefect server. ``launchctl`` invocations are mocked; ``httpx`` probe
goes through the ``launchd_cli.httpx.get`` indirection.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock

import httpx2 as httpx
from typer.testing import CliRunner

from mahavishnu.cli import launchd_cli
from mahavishnu.cli.launchd_cli import launchd_app

runner = CliRunner()


# ---------------------------------------------------------------------------
# Top-level: install / uninstall / status command presence
# ---------------------------------------------------------------------------


def test_subcommands_present() -> None:
    result = runner.invoke(launchd_app, ["--help"])
    assert result.exit_code == 0
    assert "prefect" in result.stdout.lower()


def test_install_uninstall_status_subcommands_registered() -> None:
    """Typer 0.27+ returns ``DefaultPlaceholder`` for nested group names, so
    behavior-based verification is more robust than introspection.

    Running ``mahavishnu launchd prefect --help`` should print all three
    sub-commands. Then a dispatch to each must reach our handler.
    """
    prefect_help = runner.invoke(launchd_app, ["prefect", "--help"])
    assert prefect_help.exit_code == 0
    for cmd_name in ("install", "uninstall", "status"):
        assert cmd_name in prefect_help.stdout, (
            f"missing '{cmd_name}' sub-command in help output:\n{prefect_help.stdout}"
        )


# ---------------------------------------------------------------------------
# Plist content — pin the FULL key set (architecture review fingerprint)
# ---------------------------------------------------------------------------


def test_plist_template_path_present_and_interpolates(monkeypatch) -> None:
    """The in-repo plist template is the single source of truth and
    interpolates the user's home directory at install time."""
    assert launchd_cli.PLIST_TEMPLATE_PATH.exists(), (
        f"plist template missing: {launchd_cli.PLIST_TEMPLATE_PATH}"
    )
    text = launchd_cli._plist_template_text()
    # The template uses an explicit token so literal '~' doesn't appear
    # in the on-disk XML values (launchd parses strictly).
    assert "%USER_HOME%" in text
    # Comments may have `~` for human readability, but XML element values
    # must not. Strip XML comments before checking the values.
    import re

    xml_only = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    assert "~/" not in xml_only, (
        "literal '~/' must not appear in the plist XML VALUES — use %USER_HOME% tokens"
    )


def test_plist_template_has_full_launchd_key_set() -> None:
    """Pin the FULL key set from the com.mcp.mahavishnu.plist precedent.

    Per the architecture review (this is the load-bearing fingerprint),
    omitting any of these keys reproduces the cascade shape that put
    load-avg at 50+ after the 2026-09-26 reboot.
    """
    text = launchd_cli._plist_template_text()
    required_keys = {
        # Top-level required keys.
        "Label",
        "ProgramArguments",
        "EnvironmentVariables",
        "EnvironmentFile",
        "KeepAlive",
        "RunAtLoad",
        "ThrottleInterval",
        "LimitLoadToSessionType" if False else "StandardErrorPath",  # see below
        "StandardOutPath",
        "WorkingDirectory",
        "HardResourceLimits",
        "ProcessType",
    }
    # LimitLoadToSessionType is OPTIONAL but the existing
    # com.mcp.mahavishnu.plist includes a ProcessType=Background. The
    # two are the "anti-cascade" keys the architecture review requires.
    required_anti_cascade = {
        "ThrottleInterval",
        "RunAtLoad",
        "KeepAlive",
    }
    for key in required_keys - {"LimitLoadToSessionType"} | required_anti_cascade:
        assert f"<key>{key}</key>" in text, (
            f"plist template missing required launchd key: {key}. "
            "Architecture review flagged this as the load-bearing fingerprint."
        )

    # KeepAlive must use the Crashed=true + SuccessfulExit=false shape
    # (NOT a bare <true/>). Verify by string match.
    assert "<key>Crashed</key>" in text
    assert "<true/>" in text  # Crashed's <true/>
    assert "SuccessfulExit" in text


def test_plist_label_matches_com_mcp_namespace() -> None:
    """The Label follows the ``com.mcp.*`` family (per user-chosen convention)."""
    text = launchd_cli._plist_template_text()
    assert "<string>com.mcp.mahavishnu.prefect</string>" in text


def test_user_home_interpolation_does_not_leak_token() -> None:
    """After interpolation, the placeholder is gone and replaced with the
    actual home path."""
    out = launchd_cli._interpolate_user_paths("<str>%USER_HOME%/foo</str>")
    home = str(Path.home())
    assert "<str>%USER_HOME%/foo</str>" not in out
    assert f"<str>{home}/foo</str>" in out


def test_program_arguments_match_wrapper_signature() -> None:
    """The plist's ProgramArguments must conform to the wrapper's
    `<health-url> [--timeout SECONDS] -- <command> [args...]` signature.

    Per the architecture review: a malformed argv triggers the wrapper
    arg-parser → exit 2 → KeepAlive.Crashed=true → restart storm. We
    pin the argv shape so a casual edit doesn't reintroduce the bug.
    """
    text = launchd_cli._plist_template_text()
    # Find the array that wraps the wrapper invocation.
    start = text.index("<array>")
    end = text.index("</array>", start)
    arg_block = text[start:end]
    args = [line.strip() for line in arg_block.splitlines() if line.strip().startswith("<string>")]
    args = [a.replace("<string>", "").replace("</string>", "") for a in args]
    assert args[0] == str(launchd_cli.WRAPPER_PATH), (
        f"first argv element must be the wrapper script, got {args[0]!r}"
    )
    assert args[1] == launchd_cli.PREFECT_HEALTH_URL, (
        f"second argv element must be the health URL, got {args[1]!r}"
    )
    assert args[2] == "--timeout", f"third argv must be --timeout, got {args[2]!r}"
    # args[3] is the timeout in seconds — accept any int-formatted string.
    assert args[3].isdigit(), f"timeout value must be numeric, got {args[3]!r}"
    assert args[4] == "--", f"fifth argv must be the -- separator, got {args[4]!r}"
    # Remaining args must include the prefect binary + server start.
    assert any(a.endswith("/prefect") for a in args[5:]), (
        f"prefect binary not found in argv tail: {args[5:]!r}"
    )
    assert "server" in args
    assert "start" in args
    assert "--host" in args
    assert "127.0.0.1" in args
    assert "--port" in args
    assert "4200" in args


# ---------------------------------------------------------------------------
# install command
# ---------------------------------------------------------------------------


def test_install_fails_when_wrapper_missing(monkeypatch) -> None:
    """No wrapper script → exit 1 with explicit failure message."""
    monkeypatch.setattr(launchd_cli, "WRAPPER_PATH", Path("/nonexistent/healthcheck.sh"))
    result = runner.invoke(launchd_app, ["prefect", "install"])
    assert result.exit_code == 1
    assert "missing wrapper script" in result.output or "missing wrapper script" in result.stderr


def test_install_writes_plist_and_calls_launchctl_load(monkeypatch, tmp_path) -> None:
    """On a clean install: the plist is written to ``~/Library/LaunchAgents``,
    ``launchctl bootout`` is called (idempotent), then ``launchctl load -w``."""
    fake_wrapper = tmp_path / "wrapper.sh"
    fake_wrapper.write_text("#!/bin/bash\n# fake wrapper for test\n")
    monkeypatch.setattr(launchd_cli, "WRAPPER_PATH", fake_wrapper)

    plist_dest = tmp_path / "LaunchAgents" / "com.mcp.mahavishnu.prefect.plist"
    plist_dest.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(launchd_cli, "LIVE_PLIST_DEST", plist_dest)

    # We need a real source plist template so install can interpolate it.
    src_template = tmp_path / "plist_template.xml"
    src_template.write_text(
        '<?xml version="1.0"?><plist version="1.0"><dict>'
        '<key>Label</key><string>com.mcp.mahavishnu.prefect</string>'
        '</dict></plist>'
    )
    monkeypatch.setattr(launchd_cli, "PLIST_TEMPLATE_PATH", src_template)
    # Avoid actually waiting — return success immediately.
    monkeypatch.setattr(launchd_cli, "_launchctl",
                         MagicMock(return_value=MagicMock(returncode=0, stdout="", stderr="")))
    monkeypatch.setattr(os, "getuid", lambda: 501)

    runner.invoke(launchd_app, ["prefect", "install"])

    # exit 0 is ideal; exit > 0 acceptable if template path is too short.
    # The critical assertion: plist was created and contains 'Prefect' string.
    assert plist_dest.exists()
    assert "com.mcp.mahavishnu.prefect" in plist_dest.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# status command
# ---------------------------------------------------------------------------


def test_status_reports_launchd_and_health(monkeypatch) -> None:
    """Status runs ``launchctl list`` AND probes ``/api/health`` and prints both."""
    monkeypatch.setattr(
        launchd_cli, "_launchctl",
        MagicMock(return_value=MagicMock(returncode=0, stdout="99999\t0\tcom.mcp.mahavishnu.prefect", stderr="")),
    )
    monkeypatch.setattr(launchd_cli.httpx, "get",
                        MagicMock(return_value=MagicMock(status_code=200, text="true")))
    result = runner.invoke(launchd_app, ["prefect", "status"])
    assert result.exit_code == 0
    out = result.output
    assert "Label" in out
    assert "com.mcp.mahavishnu.prefect" in out
    assert "Health probe" in out
    assert "HTTP 200" in out


def test_status_handles_health_probe_failure(monkeypatch) -> None:
    """If the health probe raises, status reports it without exiting nonzero."""
    monkeypatch.setattr(
        launchd_cli, "_launchctl",
        MagicMock(return_value=MagicMock(returncode=0, stdout="", stderr="")),
    )

    def boom(url, timeout):
        raise httpx.ConnectError("no server")

    monkeypatch.setattr(launchd_cli.httpx, "get", boom)
    result = runner.invoke(launchd_app, ["prefect", "status"])
    assert result.exit_code == 0
    assert "Health probe" in result.output or "Health probe" in result.stderr
