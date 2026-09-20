"""Tests for ``mahavishnu health --section <key>`` (Phase 4 M11).

Round-4 review M11: the ``mahavishnu health`` subcommand now accepts a
``--section`` flag that prints only the named section. Combine with
``--json`` for machine-readable output. Supported keys are surfaced via
the helper in the CLI dispatch (``status``, ``liveness``, ``readiness``,
``dependencies``, ``merge_driver``).
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from typer.testing import CliRunner

import mahavishnu._main_cli as cli_module
from mahavishnu.core.health import HealthStatus

runner = CliRunner()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_liveness_mock() -> MagicMock:
    """Return a ``HealthResponse``-shaped MagicMock for the liveness probe."""
    liveness = MagicMock()
    liveness.status = HealthStatus.OK
    liveness.service = "mahavishnu"
    liveness.version = "0.3.2"
    liveness.uptime_seconds = 123.4
    liveness.model_dump.return_value = {
        "status": "ok",
        "service": "mahavishnu",
        "version": "0.3.2",
        "uptime_seconds": 123.4,
        "timestamp": "2026-09-10T00:00:00Z",
    }
    return liveness


def _make_readiness_mock(ready: bool = True, deps: dict | None = None) -> MagicMock:
    """Return a ``ReadyResponse``-shaped MagicMock for the readiness probe."""
    deps = deps or {}
    readiness = MagicMock()
    readiness.service = "mahavishnu"
    readiness.ready = ready
    readiness.dependencies = deps
    readiness.model_dump.return_value = {
        "ready": ready,
        "service": "mahavishnu",
        "dependencies": {},
        "checks": {"server": "ok"},
        "merge_driver": None,
    }
    return readiness


@pytest.fixture
def _mock_health_endpoint(monkeypatch: pytest.MonkeyPatch) -> dict[str, MagicMock]:
    """Wire a stub ``MahavishnuApp.health_endpoint`` and helpers for tests."""
    dep_mock = MagicMock()
    dep_mock.status = HealthStatus.OK
    dep_mock.latency_ms = 12.3
    dep_mock.error = None
    dep_mock.last_check = None
    deps = {"session_buddy": dep_mock}

    liveness = _make_liveness_mock()
    readiness = _make_readiness_mock(ready=True, deps=deps)

    endpoint = MagicMock()
    endpoint.liveness = AsyncMock(return_value=liveness)
    endpoint.readiness = AsyncMock(return_value=readiness)

    maha_app = MagicMock()
    maha_app.health_endpoint = endpoint
    fake_merge_driver = {"available": True, "binary": "/usr/local/bin/mergiraf", "version": "0.19.1", "grammars": [], "degraded_since": None}

    monkeypatch.setattr(cli_module, "MahavishnuApp", lambda: maha_app)
    monkeypatch.setattr(
        cli_module, "merge_driver_health", lambda: fake_merge_driver, raising=False
    )

    # ``merge_driver_health`` is imported lazily inside the command body;
    # monkey-patch the canonical module path so the import resolves.
    from mahavishnu.core import health as core_health_module

    monkeypatch.setattr(core_health_module, "merge_driver_health", lambda: fake_merge_driver)

    return {
        "liveness": liveness,
        "readiness": readiness,
        "endpoint": endpoint,
        "merge_driver": fake_merge_driver,
        "dep": dep_mock,
    }


# ---------------------------------------------------------------------------
# --section flag — focused output
# ---------------------------------------------------------------------------


class TestHealthSectionFlag:
    """Round-4 review M11: ``--section <key>`` prints a single section."""

    def test_section_merge_driver_outputs_only_that_payload(
        self, _mock_health_endpoint: dict[str, MagicMock]
    ) -> None:
        result = runner.invoke(cli_module.app, ["health", "--section", "merge_driver"])
        assert result.exit_code == 0, result.output
        body = json.loads(result.output)
        # The output must match the merge_driver shape only — no envelope.
        assert body == _mock_health_endpoint["merge_driver"]
        # Sibling sections MUST NOT appear in the output.
        assert "liveness" not in body
        assert "readiness" not in body
        assert "dependencies" not in body

    def test_section_liveness_outputs_only_liveness(
        self, _mock_health_endpoint: dict[str, MagicMock]
    ) -> None:
        result = runner.invoke(cli_module.app, ["health", "--section", "liveness"])
        assert result.exit_code == 0, result.output
        body = json.loads(result.output)
        assert body["service"] == "mahavishnu"
        assert body["status"] == "ok"
        assert body["uptime_seconds"] == 123.4

    def test_section_status_outputs_envelope_summary(
        self, _mock_health_endpoint: dict[str, MagicMock]
    ) -> None:
        result = runner.invoke(cli_module.app, ["health", "--section", "status"])
        assert result.exit_code == 0, result.output
        body = json.loads(result.output)
        assert body == {
            "service": "mahavishnu",
            "version": "0.3.2",
            "status": "ok",
        }

    def test_section_combined_with_json_works(
        self, _mock_health_endpoint: dict[str, MagicMock]
    ) -> None:
        result = runner.invoke(
            cli_module.app, ["health", "--json", "--section", "dependencies"]
        )
        assert result.exit_code == 0, result.output
        body = json.loads(result.output)
        assert "session_buddy" in body
        assert body["session_buddy"]["status"] == "ok"

    def test_unknown_section_exits_with_error(
        self, _mock_health_endpoint: dict[str, MagicMock]
    ) -> None:
        result = runner.invoke(cli_module.app, ["health", "--section", "no_such_key"])
        assert result.exit_code != 0
        # Standard Typer error path writes to stderr (we don't assert the
        # exact channel because CliRunner combines output by default).
        assert "no_such_key" in (result.output + (result.stderr or ""))

    def test_section_lists_supported_keys_in_error(
        self, _mock_health_endpoint: dict[str, MagicMock]
    ) -> None:
        result = runner.invoke(cli_module.app, ["health", "--section", "nope"])
        assert result.exit_code != 0
        # The error message should guide the user to the supported list.
        combined = result.output + (result.stderr or "")
        for key in ("liveness", "readiness", "dependencies", "merge_driver", "status"):
            assert key in combined, f"missing supported key '{key}' in error: {combined}"

    def test_section_when_health_disabled_surfaces_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When ``health_endpoint`` is ``None``, only ``--section status`` works.

        Other sections need the endpoint — a request for, say, ``--section
        liveness`` should fail loudly with a non-zero exit so CI scripts
        notice the misconfiguration rather than receiving a placeholder
        success.
        """
        maha_app = MagicMock()
        maha_app.health_endpoint = None
        monkeypatch.setattr(cli_module, "MahavishnuApp", lambda: maha_app)

        result = runner.invoke(cli_module.app, ["health", "--section", "liveness"])
        assert result.exit_code != 0
        assert "disabled" in (result.output + (result.stderr or ""))

    def test_full_command_still_works_without_section(
        self, _mock_health_endpoint: dict[str, MagicMock]
    ) -> None:
        """Regression guard: omitting ``--section`` keeps the legacy shape."""
        result = runner.invoke(cli_module.app, ["health", "--json"])
        assert result.exit_code == 0, result.output
        body = json.loads(result.output)
        assert body["service"] == "mahavishnu"
        # The full payload now exposes every section by name (Round-4 M11).
        for key in ("liveness", "readiness", "dependencies", "merge_driver", "status"):
            assert key in body, f"expected full payload to include '{key}' after M11"
