"""Unit tests for ``mahavishnu/cli/demo_cli.py``.

Covers the 5+5 test shape from the precedent at commit ``55630b45``
(for tmux) plus a parallel 5 for the prefect demo, and a stub-meta test.
The tests run fast under ``@pytest.mark.unit`` — no Prefect server, no
actual workers spawned. Implementation details are stubbed via the
precondition probe's injectable hooks (the same shape the 55630b45
precedent established).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx2 as httpx
from typer.testing import CliRunner

from mahavishnu.cli import demo_cli
from mahavishnu.cli.demo_cli import demo_app

runner = CliRunner()


# ============================================================================
# tmux sub-command (5 tests mirror the 55630b45 shape)
# ============================================================================


def test_tmux_subcommand_present() -> None:
    result = runner.invoke(demo_app, ["tmux", "--help"])
    assert result.exit_code == 0
    assert "tmux" in result.stdout.lower()


def test_tmux_precondition_failure_lists_each(monkeypatch) -> None:
    """Missing tmux binary → nonzero exit, names the binary, prints
    ``Precondition failure`` header."""
    # Stub shutil.which to return None for "tmux" but a path for "claude".
    def fake_which(name: str) -> str | None:
        return None if name == "tmux" else "/usr/bin/claude"

    monkeypatch.setattr(demo_cli.shutil, "which", fake_which)
    # Don't actually build a terminal manager.
    monkeypatch.setattr(demo_cli, "_build_terminal_manager", lambda: MagicMock())
    # Don't actually run the demo.
    monkeypatch.setattr(demo_cli, "_run_tmux_demo", AsyncMock())

    result = runner.invoke(demo_app, ["tmux"])
    assert result.exit_code == 1
    assert "Precondition failure" in result.stderr or "Precondition failure" in result.output
    assert "tmux" in result.output


def test_tmux_spawns_three_workers_by_default(monkeypatch, tmp_path) -> None:
    """Default ``workers=3`` is passed through."""
    monkeypatch.setattr(demo_cli.shutil, "which", lambda n: "/usr/bin/x" if n in ("tmux", "claude") else None)
    tm = MagicMock()
    monkeypatch.setattr(demo_cli, "_build_terminal_manager", lambda: tm)
    # Inject tmp_path as the socket dir — see test_custom_workers for rationale.
    real_check = demo_cli._check_tmux_preconditions
    def patched_preconditions(**kwargs: object) -> list[str]:
        kwargs.pop("socket_dir", None)
        return real_check(socket_dir=tmp_path, **kwargs)
    monkeypatch.setattr(demo_cli, "_check_tmux_preconditions", patched_preconditions)
    called_kwargs: dict = {}

    async def capture(**kwargs: object) -> None:
        called_kwargs.update(kwargs)

    monkeypatch.setattr(demo_cli, "_run_tmux_demo", capture)

    # Skip probe failure for claude requires-claude branch — both binaries present.
    result = runner.invoke(demo_app, ["tmux"])
    assert result.exit_code == 0, result.output + result.stderr
    assert called_kwargs["workers"] == 3
    assert called_kwargs["command"].startswith("bash -c")
    assert called_kwargs["keep"] is False


def test_tmux_keep_skips_reap_branch(monkeypatch) -> None:
    """``--keep`` propagates as True."""
    monkeypatch.setattr(demo_cli.shutil, "which", lambda n: "/usr/bin/x")
    monkeypatch.setattr(demo_cli, "_build_terminal_manager", lambda: MagicMock())
    captured: dict = {}
    # Use AsyncMock with side_effect to capture kwargs synchronously when awaited.
    # The Typer callback wraps the call in ``asyncio.run``; side_effect preserves
    # the args when the coroutine resumes.
    mock_run = AsyncMock(side_effect=lambda **kw: captured.update(kw))
    monkeypatch.setattr(demo_cli, "_run_tmux_demo", mock_run)

    result = runner.invoke(demo_app, ["tmux", "--keep"])
    assert result.exit_code == 0, result.output
    assert captured.get("keep") is True


def test_tmux_custom_workers_and_cmd_propagate(monkeypatch, tmp_path) -> None:
    """``--workers`` and ``--cmd`` arguments are forwarded verbatim.

    Inject ``tmp_path`` as the socket dir so the test doesn't touch
    ``~/.mahavishnu/tmux`` (which may be un-writable in CI or shared with
    parallel test workers).
    """
    monkeypatch.setattr(demo_cli.shutil, "which", lambda n: "/usr/bin/x")
    monkeypatch.setattr(demo_cli, "_build_terminal_manager", lambda: MagicMock())
    real_check = demo_cli._check_tmux_preconditions

    def patched_socket_check(**kw: object) -> list[str]:
        kwargs = {k: v for k, v in kw.items() if k != "socket_dir"}
        return real_check(socket_dir=tmp_path, **kwargs)

    monkeypatch.setattr(demo_cli, "_check_tmux_preconditions", patched_socket_check)
    captured: dict = {}
    mock_run = AsyncMock(side_effect=lambda **kw: captured.update(kw))
    monkeypatch.setattr(demo_cli, "_run_tmux_demo", mock_run)

    result = runner.invoke(demo_app, ["tmux", "--workers", "5", "--cmd", "echo hi"])
    assert result.exit_code == 0, result.output
    assert captured["workers"] == 5
    assert captured["command"] == "echo hi"


# ============================================================================
# prefect sub-command (5 tests mirror the tmux shape)
# ============================================================================


def test_prefect_subcommand_present() -> None:
    result = runner.invoke(demo_app, ["prefect", "--help"])
    assert result.exit_code == 0
    assert "prefect" in result.stdout.lower()


def test_prefect_precondition_failure_when_server_unreachable(monkeypatch) -> None:
    """No prefect binary + httpx error → two precondition lines, exit 1."""
    monkeypatch.setattr(demo_cli.shutil, "which", lambda n: None)
    settings_mock = MagicMock()
    settings_mock.prefect.api_url = "http://localhost:4200"
    settings_mock.prefect.work_pool = "default"
    settings_mock.prefect.timeout_seconds = 60
    monkeypatch.setattr(demo_cli, "_default_settings_getter", lambda: settings_mock)

    def http_probe(url, timeout):
        raise httpx.ConnectError("no server")

    monkeypatch.setattr(demo_cli.httpx, "get", http_probe)

    result = runner.invoke(demo_app, ["prefect"])
    assert result.exit_code == 1
    assert "Precondition" in (result.output + result.stderr)


def test_prefect_runs_with_default_flow_when_server_up(monkeypatch) -> None:
    """With all preconditions green, the demo invokes the helper exactly once
    with the default flow path and the operator's resolved repo."""
    monkeypatch.setattr(demo_cli.shutil, "which", lambda n: "/usr/bin/x")
    settings_mock = MagicMock()
    settings_mock.prefect.api_url = "http://localhost:4200"
    settings_mock.prefect.work_pool = "mahavishnu"
    settings_mock.prefect.timeout_seconds = 60
    monkeypatch.setattr(demo_cli, "_default_settings_getter", lambda: settings_mock)
    monkeypatch.setattr(demo_cli.httpx, "get", lambda url, timeout: MagicMock(status_code=200))

    captured: dict = {}

    async def fake_run(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {
            "flow_run_id": "fr-1",
            "flow_run_url": "http://localhost:4200/flows/flow-run/fr-1",
            "state": "COMPLETED",
            "state_name": "Completed",
            "repos_processed": 1,
            "results_count": 1,
        }

    monkeypatch.setattr(demo_cli, "_run_prefect_demo", fake_run)

    result = runner.invoke(demo_app, ["prefect", "--repos", "/tmp/x"])
    assert result.exit_code == 0, result.output + result.stderr
    assert captured["flow_dotted"] == "mahavishnu.engines.prefect_adapter_impl:process_repositories_flow"
    assert list(captured["repos"]) == ["/tmp/x"]
    assert captured["keep"] is False


def test_prefect_keep_flag_propagates(monkeypatch) -> None:
    monkeypatch.setattr(demo_cli.shutil, "which", lambda n: "/usr/bin/x")
    settings_mock = MagicMock()
    settings_mock.prefect.api_url = "http://localhost:4200"
    settings_mock.prefect.work_pool = "default"
    settings_mock.prefect.timeout_seconds = 60
    monkeypatch.setattr(demo_cli, "_default_settings_getter", lambda: settings_mock)
    monkeypatch.setattr(demo_cli.httpx, "get", lambda url, timeout: MagicMock(status_code=200))
    captured: dict = {}
    async def fake_run(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {"flow_run_id": "fr-1", "flow_run_url": "x", "state": "COMPLETED", "state_name": "Completed", "repos_processed": 0, "results_count": 0}
    monkeypatch.setattr(demo_cli, "_run_prefect_demo", fake_run)
    result = runner.invoke(demo_app, ["prefect", "--keep"])
    assert result.exit_code == 0
    assert captured["keep"] is True


def test_prefect_custom_flow_override(monkeypatch) -> None:
    """``--flow`` is forwarded to the helper verbatim (no transformation)."""
    monkeypatch.setattr(demo_cli.shutil, "which", lambda n: "/usr/bin/x")
    settings_mock = MagicMock()
    settings_mock.prefect.api_url = "http://localhost:4200"
    settings_mock.prefect.work_pool = "default"
    settings_mock.prefect.timeout_seconds = 60
    monkeypatch.setattr(demo_cli, "_default_settings_getter", lambda: settings_mock)
    monkeypatch.setattr(demo_cli.httpx, "get", lambda url, timeout: MagicMock(status_code=200))
    captured: dict = {}
    async def fake_run(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {"flow_run_id": "x", "flow_run_url": "x", "state": "COMPLETED", "state_name": "Completed", "repos_processed": 0, "results_count": 0}
    monkeypatch.setattr(demo_cli, "_run_prefect_demo", fake_run)
    result = runner.invoke(
        demo_app,
        ["prefect", "--flow", "pkg.mod:my_flow"],
    )
    assert result.exit_code == 0
    assert captured["flow_dotted"] == "pkg.mod:my_flow"


# ============================================================================
# Stub sub-commands (1 meta-test for the stable surface)
# ============================================================================


def test_stub_subcommands_print_not_implemented_and_exit_zero() -> None:
    """The 1 remaining stub sub-command prints the discovery message
    and exits 0 — operators running ``mahavishnu demo mock`` get a clear
    indicator that this is a deferred-work surface, not a bug.

    History of stub → live promotions and removals:

    - 2026-10-15: agno promoted to live (``AgnoAdapter.execute``).
    - 2026-10-16: llamaindex promoted to live (``LlamaIndexAdapter.execute``).
    - 2026-10-16: crow promoted to live (commit b892ab46 — drives
      ``CrowTerminalAdapter`` end-to-end against the bundled crow-mcp).
    - 2026-10-16: pydantic_ai promoted to live (commit 01bb28e8 — drives
      ``PydanticAIAdapter.execute`` end-to-end).
    - 2026-10-17: goose adapter removed (Block never shipped the matching
      ``goose serve`` server the design assumed).
    - 2026-10-17: hatchet promoted to live (``HatchetAdapterImpl.execute``
      end-to-end against the Hatchet server). The stub list is now
      one name: mock.
    """
    for stub in ["mock"]:
        result = runner.invoke(demo_app, [stub])
        assert result.exit_code == 0, f"{stub}: unexpected exit {result.exit_code}"
        assert "not implemented" in result.output, f"{stub}: missing not-implemented text"


def test_stub_subcommands_why_stub_flag_prints_implementation_cost() -> None:
    """``--why-stub`` reveals the implementation cost without a real impl."""
    for stub in ["mock"]:
        result = runner.invoke(demo_app, [stub, "--why-stub"])
        assert result.exit_code == 0, f"{stub}: unexpected exit {result.exit_code}"
        assert "implementation cost" in result.output, f"{stub}: missing cost info"
        # A path to the plan is included so operators can find the followup work.
        assert "plan" in result.output.lower(), f"{stub}: missing plan pointer"


def test_demo_agno_is_no_longer_a_stub() -> None:
    """2026-10-15 wire-up fix: ``mahavishnu demo agno`` is a live command.

    The stub path prints "not implemented" and exits 0; the live path
    hits the precondition gate (or actually executes). Either way it
    must NOT contain the stub message. We don't assert on precondition
    success here — that's tested in test_cli_wireup_invariants.
    """
    result = runner.invoke(demo_app, ["agno"])
    assert "not implemented" not in result.output, result.output


# ============================================================================
# Wire-up
# ============================================================================


def test_demo_app_exposes_expected_commands() -> None:
    """Sanity: the module exposes ``demo_app`` and it has 8 registered commands
    (tmux, prefect, 6 live). Test pin for accidental stub deletion."""
    cmd_names = {cmd.name for cmd in demo_app.registered_commands}
    assert cmd_names == {"tmux", "prefect", "agno", "llamaindex", "hatchet", "pydantic_ai", "crow", "mock"}
