"""Pin the ``mahavishnu pool spawn`` worker-type allowlist against drift.

Regression guard for ``docs/followups/2026-10-09-spawn-cli-stale-worker-allowlist.md``.
The 2026-09-24 worker retirement decision
(``docs/decisions/2026-09-24-legacy-worker-deprecation.md``) narrowed the
supported isolated-worker surface to ``shepherd``; the CLI help text kept
advertising the old types and immediately rejected operators who followed it.
These tests pin the constants exported from ``mahavishnu._main_cli`` so the
drift cannot silently resurface, and exercise the live ``pool spawn`` command
via Typer's ``CliRunner`` to assert the end-to-end behaviour.

See:
- ``docs/decisions/2026-09-24-legacy-worker-deprecation.md``
- ``docs/followups/2026-10-09-spawn-cli-stale-worker-allowlist.md``
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from mahavishnu._main_cli import (
    SPAWN_WORKER_TYPE_ALLOWLIST,
    SPAWN_WORKER_TYPE_ERROR_HINT,
    pool_app,
)


_RETIRED_WORKER_TYPES = (
    "terminal-claude",
    "terminal-codex",
    "terminal-qwen",
    "container-executor",
)


@pytest.mark.unit
def test_shepherd_in_allowlist() -> None:
    """The smoking-gun assertion: ``shepherd`` is the post-2026-09-24 survivor.

    If this fails the allowlist has drifted again and operators following the
    decision doc will hit the same confusing failure as 2026-10-09.
    """
    assert "shepherd" in SPAWN_WORKER_TYPE_ALLOWLIST


@pytest.mark.unit
@pytest.mark.parametrize("retired_type", _RETIRED_WORKER_TYPES)
def test_retired_types_not_in_allowlist(retired_type: str) -> None:
    """All four worker types retired 2026-09-24 must stay out of the allowlist.

    The retirement decision retains no back-compat window for these — no
    deprecation aliases, no shim layer. Adding any of them back here would
    re-introduce the spawn-path failure that this follow-up tracks.
    """
    assert retired_type not in SPAWN_WORKER_TYPE_ALLOWLIST


@pytest.mark.unit
def test_error_message_points_at_decision_doc() -> None:
    """The error hint must surface the authoritative retirement decision.

    Operators who hit the rejection need a doc anchor; without it the error
    is a dead-end. The substring check keeps the anchor path stable even if
    wording around it changes.
    """
    assert "2026-09-24-legacy-worker-deprecation" in SPAWN_WORKER_TYPE_ERROR_HINT


@pytest.mark.unit
def test_error_message_points_at_followup() -> None:
    """The error hint must also reference the follow-up that tracked this drift.

    Future readers tracing why this regression guard exists land on the
    follow-up doc rather than spelunking through git history.
    """
    assert "2026-10-09-spawn-cli-stale-worker-allowlist" in SPAWN_WORKER_TYPE_ERROR_HINT


@pytest.mark.unit
def test_error_message_lists_supported_types() -> None:
    """The error hint must enumerate the live allowlist so operators know the path forward."""
    for allowed_type in SPAWN_WORKER_TYPE_ALLOWLIST:
        assert allowed_type in SPAWN_WORKER_TYPE_ERROR_HINT, (
            f"error hint must mention live worker type {allowed_type!r}"
        )


@pytest.mark.unit
def test_spawn_rejects_unknown_worker_type_via_cli() -> None:
    """End-to-end check: a retired worker type via the live ``pool spawn`` command exits non-zero.

    The unit assertions above pin the constants; this test walks the full
    Typer ``CliRunner`` path so the constants actually reach the operator
    when a bad worker type is supplied. We stub upstream I/O so the failure
    surfaces at the allowlist check instead of the MahavishnuApp bootstrap.
    Typer's ``CliRunner`` merges stdout+stderr into ``result.output``.
    """
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
    ):
        result = runner.invoke(
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
                "terminal-claude",
            ],
        )

    assert result.exit_code != 0, (
        f"expected non-zero exit when worker-type is retired, got {result.exit_code}\n"
        f"output={result.output!r}"
    )
    combined_output = (result.output or "") + (getattr(result, "stderr", "") or "")
    assert "terminal-claude" in combined_output
    assert "2026-09-24-legacy-worker-deprecation" in combined_output
    assert "2026-10-09-spawn-cli-stale-worker-allowlist" in combined_output


class _FakeApp:
    """Minimal MahavishnuApp stand-in: only ``config`` is touched by the spawn path."""

    def __init__(self, config) -> None:
        self.config = config
