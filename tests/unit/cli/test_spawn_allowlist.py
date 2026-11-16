"""Pin the ``mahavishnu pool spawn`` worker-type allowlist against drift.

The accepted set is derived from the worker registry
(``mahavishnu.workers.registry.pool_capable_worker_types``), so the CLI
and the MCP ``pool_spawn`` tool cannot drift apart: a worker type the
factory can construct is accepted by both, and one whose backend module
was deleted is accepted by neither.

Two earlier states are pinned here because both were operator-facing
failures:

- 2026-09-24: the CLI help advertised worker types the CLI then
  rejected (``docs/decisions/2026-09-24-legacy-worker-deprecation.md``).
- 2026-10-09: the allowlist was narrowed to ``{"shepherd",
  "gateway-openclaw"}`` on the premise that ``terminal-claude`` and its
  siblings were retired. They were not — the SHELL AI-CLI workers route
  to ``ShellWorker`` and had been running live pool tasks ever since. The
  CLI refused the working types while the MCP tool, validating against
  the raw registry, accepted the genuinely dead ones (``apple-container``,
  ``e2b-sandbox``).

See:
- ``docs/followups/2026-10-09-spawn-cli-stale-worker-allowlist.md``
- ``docs/plans/2026-11-16-pool-affinity-and-worker-type-allowlist.md``
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from typer.testing import CliRunner, Result

from mahavishnu._main_cli import (
    SPAWN_WORKER_TYPE_ALLOWLIST,
    SPAWN_WORKER_TYPE_ERROR_HINT,
    pool_app,
)
from mahavishnu.workers.registry import pool_capable_worker_types

#: The AI-CLI shells. These carry a prompt — the pool types it into a
#: live session — and are the substrates the merge pipeline runs on.
_AI_CLI_WORKER_TYPES = (
    "terminal-claude",
    "terminal-qwen",
    "terminal-codex",
)

#: The isolated backends retired by the 2026-09-24 decision. Their
#: modules are deleted; the worker factory cannot construct them.
_RETIRED_BACKENDS = (
    "apple-container",
    "e2b-sandbox",
    "container-executor",
)


@pytest.mark.unit
def test_shepherd_in_allowlist() -> None:
    """The surviving isolated worker stays in the allowlist."""
    assert "shepherd" in SPAWN_WORKER_TYPE_ALLOWLIST


@pytest.mark.unit
@pytest.mark.parametrize("worker_type", _AI_CLI_WORKER_TYPES)
def test_the_ai_cli_shells_are_in_allowlist(worker_type: str) -> None:
    """The prompt-carrying substrates must be spawnable.

    ``terminal-claude`` was refused here on the premise that it was
    retired. It was not: ``WorkerManager._create_worker`` routes every
    ``RuntimeKind.SHELL`` entry to ``ShellWorker``, and these pools have
    been running live tasks.
    """
    assert worker_type in SPAWN_WORKER_TYPE_ALLOWLIST


@pytest.mark.unit
@pytest.mark.parametrize("worker_type", _RETIRED_BACKENDS)
def test_the_retired_backends_are_not_in_allowlist(worker_type: str) -> None:
    """The deleted backends stay out — their modules are gone."""
    assert worker_type not in SPAWN_WORKER_TYPE_ALLOWLIST


@pytest.mark.unit
def test_the_allowlist_is_the_registry_derived_set() -> None:
    """The CLI's list IS the registry-derived set, not a copy of it.

    A copy is what drifted in the first place.
    """
    assert pool_capable_worker_types() == SPAWN_WORKER_TYPE_ALLOWLIST


@pytest.mark.unit
def test_error_message_points_at_decision_doc() -> None:
    """The error hint must surface the authoritative retirement decision."""
    assert "2026-09-24-legacy-worker-deprecation" in SPAWN_WORKER_TYPE_ERROR_HINT


@pytest.mark.unit
def test_error_message_lists_supported_types() -> None:
    """The error hint must enumerate the live allowlist so operators know the path forward."""
    for allowed_type in SPAWN_WORKER_TYPE_ALLOWLIST:
        assert allowed_type in SPAWN_WORKER_TYPE_ERROR_HINT, (
            f"error hint must mention live worker type {allowed_type!r}"
        )


def _invoke_spawn(worker_type: str) -> Result:
    """Run ``pool spawn --worker-type <worker_type>`` through the Typer CLI."""
    runner = CliRunner()

    fake_config = type(
        "_Cfg",
        (),
        {"pools_enabled": True},
    )()

    with (
        patch("mahavishnu._main_cli.MahavishnuApp", return_value=_FakeApp(fake_config)),
        patch(
            "mahavishnu.pools._registry.canonicalize_pool_type",
            side_effect=lambda x: x,
        ),
        patch(
            "mahavishnu.pools._registry.list_pool_types",
            return_value=["mahavishnu"],
        ),
        patch(
            "mahavishnu._main_cli._dispatch_pool_spawn_via_mcp",
            return_value={"status": "spawned", "pool_id": "mahavishnu_test"},
        ),
    ):
        return runner.invoke(
            pool_app,
            [
                "spawn",
                "--type",
                "mahavishnu",
                "--name",
                "verify-allowlist",
                "--min",
                "1",
                "--max",
                "3",
                "--worker-type",
                worker_type,
            ],
        )


@pytest.mark.unit
def test_spawn_accepts_terminal_claude_via_cli() -> None:
    """End-to-end: the AI-CLI substrate reaches the spawn, not a rejection.

    This is the inverse of the 2026-10-09 expectation, and the reason
    for it: the CLI refused the worker type the pool path actually runs.
    """
    result = _invoke_spawn("terminal-claude")

    assert result.exit_code == 0, (
        f"expected terminal-claude to be accepted, got {result.exit_code}\n"
        f"output={result.output!r}"
    )
    assert "terminal-claude" in (result.output or "")


@pytest.mark.unit
def test_spawn_rejects_unknown_worker_type_via_cli() -> None:
    """End-to-end: a worker type the factory cannot build is rejected."""
    result = _invoke_spawn("not-a-real-worker-type")

    assert result.exit_code != 0, (
        f"expected non-zero exit for an unknown worker type, got {result.exit_code}\n"
        f"output={result.output!r}"
    )
    combined_output = (result.output or "") + (getattr(result, "stderr", "") or "")
    assert "not-a-real-worker-type" in combined_output


class _FakeApp:
    """Minimal MahavishnuApp stand-in: only ``config`` is touched by the spawn path."""

    def __init__(self, config) -> None:
        self.config = config
