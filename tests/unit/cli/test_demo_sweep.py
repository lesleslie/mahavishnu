"""Unit tests for the ``mahavishnu demo all`` sweep and its helpers.

Covers the pieces that were *fixed* while the demo surface was
swept for real (2026-10-29):

- the verdict classifier, including the Rich-traceback false positive
  that made a crash look like a timeout;
- the repo-root resolution that every engine demo shares;
- the pool-type-aware task payload (Shepherd wants ``command``, the
  prompt-based pools want ``prompt``);
- the Prefect deployment entrypoint (colon-free => module path);
- the Prefect API URL resolution that the precondition and the client
  must agree on.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mahavishnu.cli import demo_cli
from mahavishnu.cli.demo_cli import (
    DEMO_SWEEP_SPECS,
    VERDICT_ERROR,
    VERDICT_PARTIAL,
    VERDICT_PASS,
    VERDICT_PRECONDITION,
    VERDICT_STUB,
    VERDICT_TIMEOUT,
    _classify_sweep_output,
    _check_hatchet_server_reachable,
    _default_demo_repos,
    _deployment_entrypoint,
    _effective_prefect_api_url,
    _extract_demo_payload,
    _extract_demo_status,
    _select_sweep_specs,
    _task_payload,
)

# ============================================================================
# Verdict classifier
# ============================================================================


def test_classify_precondition_failure() -> None:
    output = "Precondition failure(s):\n  - crow-mcp unreachable at http://x/mcp\n"
    assert _classify_sweep_output(output, 1) == VERDICT_PRECONDITION


def test_classify_real_timeout() -> None:
    assert _classify_sweep_output("Timed out after 120s waiting for the flow run\n", 2) == (
        VERDICT_TIMEOUT
    )


def test_classify_traceback_with_timeout_source_line_is_error() -> None:
    """A Rich traceback panel embeds the *source* of the timeout branch.

    Matching ``Timed out after`` as a substring fires on the source
    line ``typer.echo(f"Timed out after {timeout}s ...")`` and
    mislabels a crash as a timeout. The match must be line-anchored.
    """
    output = (
        "╭── Traceback (most recent call last) ───╮\n"
        '│   510 │   │   typer.echo(f"Timed out after {timeout}s '
        "waiting for the flow  │\n"
        "╰───────────────────────╯\n"
        "ModuleNotFoundError: No module named 'x'\n"
    )
    assert _classify_sweep_output(output, 1) == VERDICT_ERROR


def test_classify_stub() -> None:
    assert _classify_sweep_output("not implemented — see docs/plans/x.md\n", 0) == VERDICT_STUB


def test_classify_success_payload() -> None:
    output = 'Agno demo result:\n{\n  "status": "success"\n}\n'
    assert _classify_sweep_output(output, 0) == VERDICT_PASS


def test_classify_false_success_with_unhealthy_status() -> None:
    """The Hatchet adapter returns ``status: unhealthy`` on a connection error.

    The demo exits 0 anyway, so only the payload tells the truth.
    """
    output = 'Hatchet demo result:\n{\n  "status": "unhealthy"\n}\n'
    assert _classify_sweep_output(output, 0) == VERDICT_ERROR


def test_classify_all_repos_failed_is_error() -> None:
    """LlamaIndex reports ``status: completed`` even when every repo failed."""
    output = (
        "LlamaIndex demo result:\n"
        "{\n"
        '  "status": "completed",\n'
        '  "success_count": 0,\n'
        '  "failure_count": 1\n'
        "}\n"
    )
    assert _classify_sweep_output(output, 0) == VERDICT_ERROR


def test_classify_partial_success_is_partial() -> None:
    output = (
        "LlamaIndex demo result:\n"
        "{\n"
        '  "status": "completed",\n'
        '  "success_count": 2,\n'
        '  "failure_count": 1\n'
        "}\n"
    )
    assert _classify_sweep_output(output, 0) == VERDICT_PARTIAL


def test_classify_nested_stage_status_is_error() -> None:
    """Workflow demos report per-stage verdicts in nested dicts.

    ``workflow-pi-then-local`` has no top-level ``status`` at all --
    only ``pi.status`` and ``local.status``.
    """
    output = (
        "Workflow result:\n"
        "{\n"
        '  "workflow": "pi-then-local",\n'
        '  "pi": {"status": "timeout"},\n'
        '  "local": {"status": "completed"}\n'
        "}\n"
    )
    assert _classify_sweep_output(output, 0) == VERDICT_ERROR


def test_classify_prefect_state_completed_is_pass() -> None:
    output = 'Flow run result:\n{\n  "state": "COMPLETED"\n}\n'
    assert _classify_sweep_output(output, 0) == VERDICT_PASS


def test_classify_prefect_state_crashed_is_error() -> None:
    output = 'Flow run result:\n{\n  "state": "CRASHED"\n}\n'
    assert _classify_sweep_output(output, 0) == VERDICT_ERROR


# ============================================================================
# Payload extraction
# ============================================================================


def test_extract_status_from_multiline_json() -> None:
    output = 'Agno demo result:\n{\n  "status": "success",\n  "adapter": "agno"\n}\n'
    assert _extract_demo_status(output) == "success"


def test_extract_status_from_workflow_result_header() -> None:
    output = 'Workflow result:\n{\n  "status": "completed"\n}\n'
    assert _extract_demo_status(output) == "completed"


def test_extract_payload_returns_none_without_result_header() -> None:
    assert _extract_demo_payload("just some output\n") is None


# ============================================================================
# Sweep selection
# ============================================================================


def test_select_sweep_specs_defaults_to_all() -> None:
    assert _select_sweep_specs([], []) == list(DEMO_SWEEP_SPECS)


def test_select_sweep_specs_only_filters() -> None:
    selected = _select_sweep_specs(["tmux"], [])
    assert [spec.name for spec in selected] == ["tmux"]


def test_select_sweep_specs_skip_filters() -> None:
    selected = _select_sweep_specs([], ["tmux", "mock"])
    assert "tmux" not in {spec.name for spec in selected}
    assert "mock" not in {spec.name for spec in selected}
    assert len(selected) == len(DEMO_SWEEP_SPECS) - 2


def test_select_sweep_specs_rejects_unknown_name() -> None:
    with pytest.raises(Exception) as excinfo:
        _select_sweep_specs(["not-a-demo"], [])
    assert "not-a-demo" in str(excinfo.value)


def test_sweep_specs_cover_every_registered_demo() -> None:
    """Every demo subcommand must be reachable by the sweep."""
    registered = {cmd.name for cmd in demo_cli.demo_app.registered_commands}
    registered.discard("all")
    swept = {spec.name for spec in DEMO_SWEEP_SPECS}
    assert registered == swept


def test_sweep_specs_mark_demos_without_timeout_flag() -> None:
    """``tmux`` and ``mock`` have no ``--timeout`` of their own."""
    by_name = {spec.name: spec for spec in DEMO_SWEEP_SPECS}
    assert by_name["tmux"].takes_timeout is False
    assert by_name["mock"].takes_timeout is False
    assert by_name["prefect"].takes_timeout is True


# ============================================================================
# Repo-root resolution
# ============================================================================


def test_default_demo_repos_points_at_the_repo_not_the_projects_root() -> None:
    """``parents[3]`` was one level too high.

    It resolved to the *projects* root, so every engine demo operated
    on the wrong tree (LlamaIndex: ``MHV-009 No index found for
    repository: /Users/les/Projects``).
    """
    repos = _default_demo_repos()
    assert len(repos) == 1
    resolved = Path(repos[0]).resolve()
    assert resolved.name == "mahavishnu"
    assert (resolved / "mahavishnu" / "cli" / "demo_cli.py").is_file()


# ============================================================================
# Pool-type-aware task payload
# ============================================================================


def test_task_payload_mahavishnu_uses_command_key() -> None:
    """The Shepherd backend accepts ``task_ref`` XOR ``command``."""
    assert _task_payload("mahavishnu", "echo hi") == {"command": "echo hi"}


def test_task_payload_prompt_pools_use_prompt_key() -> None:
    assert _task_payload("session-buddy", "echo hi") == {"prompt": "echo hi"}
    assert _task_payload("pi", "echo hi") == {"prompt": "echo hi"}


# ============================================================================
# Prefect entrypoint + API URL
# ============================================================================


def test_deployment_entrypoint_is_colon_free() -> None:
    """A colon selects Prefect's FILE_PATH branch, which loads the file
    outside its package and breaks relative imports."""
    entrypoint = _deployment_entrypoint(
        "mahavishnu.engines.prefect_adapter_impl", "process_repositories_flow"
    )
    assert entrypoint == "mahavishnu.engines.prefect_adapter_impl.process_repositories_flow"
    assert ":" not in entrypoint


def test_effective_prefect_api_url_appends_api_suffix(monkeypatch) -> None:
    monkeypatch.delenv("PREFECT_API_URL", raising=False)
    url = _effective_prefect_api_url()
    assert url.endswith("/api")
    assert url.startswith("http")


def test_effective_prefect_api_url_env_wins(monkeypatch) -> None:
    monkeypatch.setenv("PREFECT_API_URL", "http://example.test:9999/api")
    assert _effective_prefect_api_url() == "http://example.test:9999/api"


def test_effective_prefect_api_url_does_not_double_suffix(monkeypatch) -> None:
    monkeypatch.setenv("PREFECT_API_URL", "http://example.test:9999/api")
    assert not _effective_prefect_api_url().endswith("/api/api")


# ============================================================================
# Hatchet server reachability
# ============================================================================


def test_hatchet_server_reachable_reports_unreachable_server() -> None:
    """A refused connection must be a precondition, not a demo defect.

    The Hatchet SDK connects lazily, so without this probe the demo
    reports a connection error that reads like an adapter bug.
    """
    failures = _check_hatchet_server_reachable("localhost:1", 0.5)
    assert failures
    assert "not reachable" in failures[0]
    assert "hatchet server start" in failures[0]


def test_hatchet_server_reachable_accepts_a_listening_port() -> None:
    import socket

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        # Keep it listening for the duration of the check.
        probe.listen(1)
        assert _check_hatchet_server_reachable(f"127.0.0.1:{port}", 2.0) == []


def test_hatchet_server_reachable_ignores_unparseable_url() -> None:
    """A URL shape the probe cannot interpret is left to the SDK."""
    assert _check_hatchet_server_reachable("not-a-host-port", 0.5) == []

