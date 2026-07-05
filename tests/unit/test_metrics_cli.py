"""Unit tests for mahavishnu.metrics_cli.

Covers:
    - _resolve_postgres_dsn()  — all precedence levels and edge cases
    - _load_engine_metrics_from_prometheus()  — Prometheus text parsing, URLError, label mapping
    - add_metrics_commands()  — Typer app registration
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest
import typer

from mahavishnu.metrics_cli import (
    _load_engine_metrics_from_prometheus,
    _resolve_postgres_dsn,
    add_metrics_commands,
    metrics_app,
)

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _prometheus_text(lines: list[str]) -> str:
    """Build a Prometheus exposition-format body from *lines*."""
    return "\n".join(lines)


def _mock_urlopen(body: str):
    """Return a mock context manager that yields a response with *body*."""
    response = MagicMock()
    response.read.return_value = body.encode("utf-8")
    response.__enter__ = MagicMock(return_value=response)
    response.__exit__ = MagicMock(return_value=False)
    return response


# ---------------------------------------------------------------------------
# _resolve_postgres_dsn
# ---------------------------------------------------------------------------


class TestResolvePostgresDsn:
    """Tests for the _resolve_postgres_dsn helper."""

    def test_explicit_dsn_takes_priority(self) -> None:
        """An explicitly provided DSN wins over every other source."""
        with patch.dict(
            os.environ,
            {
                "MAHAVISHNU_PERSISTENCE__POSTGRES_URL": "postgres://env:5432/x",
                "MAHAVISHNU_POSTGRES_DSN": "postgres://env2:5432/x",
            },
            clear=False,
        ):
            result = _resolve_postgres_dsn("postgres://explicit:5432/db")
        assert result == "postgres://explicit:5432/db"

    def test_env_var_persistence_postgres_url(self) -> None:
        """MAHAVISHNU_PERSISTENCE__POSTGRES_URL is preferred over MAHAVISHNU_POSTGRES_DSN."""
        with patch.dict(
            os.environ,
            {
                "MAHAVISHNU_PERSISTENCE__POSTGRES_URL": "postgres://persist:5432/db",
                "MAHAVISHNU_POSTGRES_DSN": "postgres://dsn:5432/db",
            },
            clear=False,
        ):
            result = _resolve_postgres_dsn(None)
        assert result == "postgres://persist:5432/db"

    def test_env_var_postgres_dsn_fallback(self) -> None:
        """MAHAVISHNU_POSTGRES_DSN is used when PERSISTENCE variant is absent."""
        with patch.dict(
            os.environ,
            {
                "MAHAVISHNU_POSTGRES_DSN": "postgres://dsn:5432/db",
            },
            clear=False,
        ):
            # Ensure the higher-priority var is NOT set
            os.environ.pop("MAHAVISHNU_PERSISTENCE__POSTGRES_URL", None)
            result = _resolve_postgres_dsn(None)
        assert result == "postgres://dsn:5432/db"

    def test_yaml_settings_fallback(self, tmp_path: Path) -> None:
        """When no env vars are set, persistence.postgres_url is read from YAML."""
        settings_dir = tmp_path / "settings"
        settings_dir.mkdir()
        settings_file = settings_dir / "mahavishnu.yaml"
        settings_file.write_text("persistence:\n  postgres_url: postgres://yaml:5432/mydb\n")

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MAHAVISHNU_PERSISTENCE__POSTGRES_URL", None)
            os.environ.pop("MAHAVISHNU_POSTGRES_DSN", None)
            with patch("mahavishnu.metrics_cli.Path") as mock_path_cls:
                # Make Path("settings/mahavishnu.yaml") resolve to our temp file
                mock_path_instance = MagicMock()
                mock_path_instance.exists.return_value = True
                mock_path_instance.open.return_value.__enter__ = MagicMock(
                    return_value=settings_file.open("r").__enter__()
                )
                mock_path_instance.open.return_value.__exit__ = MagicMock(return_value=False)
                mock_path_cls.return_value = mock_path_instance

                result = _resolve_postgres_dsn(None)

        assert result == "postgres://yaml:5432/mydb"

    def test_yaml_settings_strips_whitespace(self, tmp_path: Path) -> None:
        """Whitespace around the YAML value is stripped."""
        settings_dir = tmp_path / "settings"
        settings_dir.mkdir()
        settings_file = settings_dir / "mahavishnu.yaml"
        settings_file.write_text("persistence:\n  postgres_url: '  postgres://yaml:5432/db  '\n")

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MAHAVISHNU_PERSISTENCE__POSTGRES_URL", None)
            os.environ.pop("MAHAVISHNU_POSTGRES_DSN", None)
            with patch("mahavishnu.metrics_cli.Path") as mock_path_cls:
                mock_path_instance = MagicMock()
                mock_path_instance.exists.return_value = True
                mock_path_instance.open.return_value.__enter__ = MagicMock(
                    return_value=settings_file.open("r").__enter__()
                )
                mock_path_instance.open.return_value.__exit__ = MagicMock(return_value=False)
                mock_path_cls.return_value = mock_path_instance

                result = _resolve_postgres_dsn(None)

        assert result == "postgres://yaml:5432/db"

    def test_no_dsn_returns_none(self, tmp_path: Path) -> None:
        """Returns None when no DSN can be found anywhere."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MAHAVISHNU_PERSISTENCE__POSTGRES_URL", None)
            os.environ.pop("MAHAVISHNU_POSTGRES_DSN", None)
            with patch("mahavishnu.metrics_cli.Path") as mock_path_cls:
                mock_path_instance = MagicMock()
                mock_path_instance.exists.return_value = False
                mock_path_cls.return_value = mock_path_instance

                result = _resolve_postgres_dsn(None)

        assert result is None

    def test_malformed_yaml_returns_none(self, tmp_path: Path) -> None:
        """If YAML parsing fails, the function returns None."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MAHAVISHNU_PERSISTENCE__POSTGRES_URL", None)
            os.environ.pop("MAHAVISHNU_POSTGRES_DSN", None)
            with patch("mahavishnu.metrics_cli.Path") as mock_path_cls:
                mock_path_instance = MagicMock()
                mock_path_instance.exists.return_value = True
                # Simulate an exception when reading/parsing the file
                mock_path_instance.open.side_effect = OSError("permission denied")
                mock_path_cls.return_value = mock_path_instance

                result = _resolve_postgres_dsn(None)

        assert result is None

    def test_yaml_non_dict_top_level(self, tmp_path: Path) -> None:
        """If safe_load returns a non-dict (e.g., a string), returns None."""
        mock_yaml = MagicMock()
        mock_yaml.safe_load.return_value = "just a string"
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MAHAVISHNU_PERSISTENCE__POSTGRES_URL", None)
            os.environ.pop("MAHAVISHNU_POSTGRES_DSN", None)
            with patch("mahavishnu.metrics_cli.Path") as mock_path_cls:
                mock_path_instance = MagicMock()
                mock_path_instance.exists.return_value = True
                mock_path_instance.open.return_value.__enter__ = MagicMock(return_value=None)
                mock_path_instance.open.return_value.__exit__ = MagicMock(return_value=False)
                mock_path_cls.return_value = mock_path_instance

                with patch.dict("sys.modules", {"yaml": mock_yaml}):
                    result = _resolve_postgres_dsn(None)

        assert result is None

    def test_yaml_missing_persistence_key(self, tmp_path: Path) -> None:
        """If the YAML has no persistence key, returns None."""
        mock_yaml = MagicMock()
        mock_yaml.safe_load.return_value = {"other": 1}
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MAHAVISHNU_PERSISTENCE__POSTGRES_URL", None)
            os.environ.pop("MAHAVISHNU_POSTGRES_DSN", None)
            with patch("mahavishnu.metrics_cli.Path") as mock_path_cls:
                mock_path_instance = MagicMock()
                mock_path_instance.exists.return_value = True
                mock_path_instance.open.return_value.__enter__ = MagicMock(return_value=None)
                mock_path_instance.open.return_value.__exit__ = MagicMock(return_value=False)
                mock_path_cls.return_value = mock_path_instance

                with patch.dict("sys.modules", {"yaml": mock_yaml}):
                    result = _resolve_postgres_dsn(None)

        assert result is None

    def test_yaml_empty_postgres_url(self, tmp_path: Path) -> None:
        """An empty string for postgres_url is treated as absent."""
        mock_yaml = MagicMock()
        mock_yaml.safe_load.return_value = {"persistence": {"postgres_url": ""}}
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MAHAVISHNU_PERSISTENCE__POSTGRES_URL", None)
            os.environ.pop("MAHAVISHNU_POSTGRES_DSN", None)
            with patch("mahavishnu.metrics_cli.Path") as mock_path_cls:
                mock_path_instance = MagicMock()
                mock_path_instance.exists.return_value = True
                mock_path_instance.open.return_value.__enter__ = MagicMock(return_value=None)
                mock_path_instance.open.return_value.__exit__ = MagicMock(return_value=False)
                mock_path_cls.return_value = mock_path_instance

                with patch.dict("sys.modules", {"yaml": mock_yaml}):
                    result = _resolve_postgres_dsn(None)

        assert result is None


# ---------------------------------------------------------------------------
# _load_engine_metrics_from_prometheus
# ---------------------------------------------------------------------------


class TestLoadEngineMetricsFromPrometheus:
    """Tests for the _load_engine_metrics_from_prometheus helper."""

    def test_valid_routing_decisions_total(self) -> None:
        """Routing decision counters are mapped to 'selected'."""
        body = _prometheus_text(
            [
                'mahavishnu_routing_decisions_total{adapter="prefect"} 10',
                'mahavishnu_routing_decisions_total{adapter="agno"} 5',
            ]
        )
        mock = _mock_urlopen(body)

        with patch("mahavishnu.metrics_cli.urllib_request.urlopen", return_value=mock):
            result = _load_engine_metrics_from_prometheus("http://localhost:9091")

        assert result["prefect"]["selected"] == 10
        assert result["agno"]["selected"] == 5

    def test_valid_adapter_executions_total_success(self) -> None:
        """Adapter execution counters with status=success increment 'success'."""
        body = _prometheus_text(
            [
                'mahavishnu_adapter_executions_total{adapter="prefect",status="success"} 8',
                'mahavishnu_adapter_executions_total{adapter="agno",status="completed"} 4',
            ]
        )
        mock = _mock_urlopen(body)

        with patch("mahavishnu.metrics_cli.urllib_request.urlopen", return_value=mock):
            result = _load_engine_metrics_from_prometheus("http://localhost:9091")

        assert result["prefect"]["executions"] == 8
        assert result["prefect"]["success"] == 8
        assert result["prefect"]["failure"] == 0

        assert result["agno"]["executions"] == 4
        assert result["agno"]["success"] == 4

    def test_valid_adapter_executions_total_failure(self) -> None:
        """Adapter execution counters with failure/failed/timeout/cancelled map to 'failure'."""
        body = _prometheus_text(
            [
                'mahavishnu_adapter_executions_total{adapter="prefect",status="failure"} 3',
                'mahavishnu_adapter_executions_total{adapter="agno",status="failed"} 2',
                'mahavishnu_adapter_executions_total{adapter="llamaindex",status="timeout"} 1',
                'mahavishnu_adapter_executions_total{adapter="llamaindex",status="cancelled"} 1',
            ]
        )
        mock = _mock_urlopen(body)

        with patch("mahavishnu.metrics_cli.urllib_request.urlopen", return_value=mock):
            result = _load_engine_metrics_from_prometheus("http://localhost:9091")

        assert result["prefect"]["failure"] == 3
        assert result["prefect"]["executions"] == 3
        assert result["prefect"]["success"] == 0

        assert result["agno"]["failure"] == 2
        assert result["agno"]["executions"] == 2

        assert result["llamaindex"]["failure"] == 2
        assert result["llamaindex"]["executions"] == 2

    def test_valid_workflows_total_fallback(self) -> None:
        """mahavishnu_workflows_total acts as a fallback execution counter."""
        body = _prometheus_text(
            [
                'mahavishnu_workflows_total{adapter="prefect",status="success"} 7',
                'mahavishnu_workflows_total{adapter="prefect",status="failed"} 2',
            ]
        )
        mock = _mock_urlopen(body)

        with patch("mahavishnu.metrics_cli.urllib_request.urlopen", return_value=mock):
            result = _load_engine_metrics_from_prometheus("http://localhost:9091")

        assert result["prefect"]["executions"] == 9
        assert result["prefect"]["success"] == 7
        assert result["prefect"]["failure"] == 2

    def test_unknown_status_not_counted_as_success_or_failure(self) -> None:
        """An execution with an unknown status increments executions but not success/failure."""
        body = _prometheus_text(
            [
                'mahavishnu_adapter_executions_total{adapter="prefect",status="pending"} 6',
            ]
        )
        mock = _mock_urlopen(body)

        with patch("mahavishnu.metrics_cli.urllib_request.urlopen", return_value=mock):
            result = _load_engine_metrics_from_prometheus("http://localhost:9091")

        assert result["prefect"]["executions"] == 6
        assert result["prefect"]["success"] == 0
        assert result["prefect"]["failure"] == 0

    def test_empty_response(self) -> None:
        """An empty Prometheus body still returns default adapter entries."""
        mock = _mock_urlopen("")

        with patch("mahavishnu.metrics_cli.urllib_request.urlopen", return_value=mock):
            result = _load_engine_metrics_from_prometheus("http://localhost:9091")

        for adapter in ("prefect", "agno", "llamaindex"):
            assert adapter in result
            assert result[adapter] == {"selected": 0, "executions": 0, "success": 0, "failure": 0}

    def test_only_comments_and_blank_lines(self) -> None:
        """Comments and blank lines are skipped; defaults still present."""
        body = _prometheus_text(
            [
                "# HELP mahavishnu_routing_decisions_total Total routing decisions",
                "# TYPE mahavishnu_routing_decisions_total counter",
                "",
                "   ",
            ]
        )
        mock = _mock_urlopen(body)

        with patch("mahavishnu.metrics_cli.urllib_request.urlopen", return_value=mock):
            result = _load_engine_metrics_from_prometheus("http://localhost:9091")

        for adapter in ("prefect", "agno", "llamaindex"):
            assert adapter in result
            assert result[adapter] == {"selected": 0, "executions": 0, "success": 0, "failure": 0}

    def test_urlerror_raises_runtime_error(self) -> None:
        """A URLError from urlopen is wrapped in a RuntimeError."""
        from urllib import error as urllib_error

        with (
            patch(
                "mahavishnu.metrics_cli.urllib_request.urlopen",
                side_effect=urllib_error.URLError("connection refused"),
            ),
            pytest.raises(RuntimeError, match="failed to fetch Prometheus metrics"),
        ):
            _load_engine_metrics_from_prometheus("http://localhost:9091")

    def test_default_adapters_always_present(self) -> None:
        """prefect, agno, llamaindex are always in the result dict."""
        body = _prometheus_text(
            [
                'mahavishnu_routing_decisions_total{adapter="custom_engine"} 1',
            ]
        )
        mock = _mock_urlopen(body)

        with patch("mahavishnu.metrics_cli.urllib_request.urlopen", return_value=mock):
            result = _load_engine_metrics_from_prometheus("http://localhost:9091")

        # custom_engine should also be present
        assert "custom_engine" in result
        assert result["custom_engine"]["selected"] == 1

        # The three defaults must always be present
        for adapter in ("prefect", "agno", "llamaindex"):
            assert adapter in result
            assert result[adapter] == {"selected": 0, "executions": 0, "success": 0, "failure": 0}

    def test_metrics_without_adapter_label_skipped(self) -> None:
        """Lines with no 'adapter' label are ignored."""
        body = _prometheus_text(
            [
                'mahavishnu_routing_decisions_total{region="us"} 99',
                'mahavishnu_adapter_executions_total{status="success"} 42',
            ]
        )
        mock = _mock_urlopen(body)

        with patch("mahavishnu.metrics_cli.urllib_request.urlopen", return_value=mock):
            result = _load_engine_metrics_from_prometheus("http://localhost:9091")

        # No adapter-level data should be recorded beyond defaults
        total_selected = sum(m["selected"] for m in result.values())
        total_executions = sum(m["executions"] for m in result.values())
        assert total_selected == 0
        assert total_executions == 0

    def test_scientific_notation_value(self) -> None:
        """Values in scientific notation (e.g., 1e3) are parsed correctly."""
        body = _prometheus_text(
            [
                'mahavishnu_routing_decisions_total{adapter="prefect"} 1e3',
            ]
        )
        mock = _mock_urlopen(body)

        with patch("mahavishnu.metrics_cli.urllib_request.urlopen", return_value=mock):
            result = _load_engine_metrics_from_prometheus("http://localhost:9091")

        assert result["prefect"]["selected"] == 1000

    def test_negative_value_ignored(self) -> None:
        """Non-numeric Prometheus values (negative after int conversion edge) are skipped."""
        # float("-1") -> int -> -1.  Prometheus counters should never be negative,
        # but the code does `int(float(raw_value))` which succeeds for negative numbers.
        # This test verifies the behaviour is still consistent: the value is added.
        body = _prometheus_text(
            [
                'mahavishnu_routing_decisions_total{adapter="prefect"} -1',
            ]
        )
        mock = _mock_urlopen(body)

        with patch("mahavishnu.metrics_cli.urllib_request.urlopen", return_value=mock):
            result = _load_engine_metrics_from_prometheus("http://localhost:9091")

        assert result["prefect"]["selected"] == -1

    def test_non_numeric_value_skipped(self) -> None:
        """A value that cannot be converted to int(float(...)) is skipped."""
        body = _prometheus_text(
            [
                'mahavishnu_routing_decisions_total{adapter="prefect"} NaN',
            ]
        )
        mock = _mock_urlopen(body)

        with patch("mahavishnu.metrics_cli.urllib_request.urlopen", return_value=mock):
            result = _load_engine_metrics_from_prometheus("http://localhost:9091")

        assert result["prefect"]["selected"] == 0

    def test_multiple_lines_same_adapter_accumulate(self) -> None:
        """Multiple metric lines for the same adapter accumulate correctly."""
        body = _prometheus_text(
            [
                'mahavishnu_routing_decisions_total{adapter="prefect"} 5',
                'mahavishnu_routing_decisions_total{adapter="prefect"} 3',
                'mahavishnu_adapter_executions_total{adapter="prefect",status="success"} 4',
                'mahavishnu_adapter_executions_total{adapter="prefect",status="failure"} 2',
            ]
        )
        mock = _mock_urlopen(body)

        with patch("mahavishnu.metrics_cli.urllib_request.urlopen", return_value=mock):
            result = _load_engine_metrics_from_prometheus("http://localhost:9091")

        assert result["prefect"]["selected"] == 8
        assert result["prefect"]["executions"] == 6
        assert result["prefect"]["success"] == 4
        assert result["prefect"]["failure"] == 2

    def test_unknown_metric_name_ignored(self) -> None:
        """Metric names that are not one of the three expected ones are ignored."""
        body = _prometheus_text(
            [
                'mahavishnu_unknown_metric{adapter="prefect"} 100',
            ]
        )
        mock = _mock_urlopen(body)

        with patch("mahavishnu.metrics_cli.urllib_request.urlopen", return_value=mock):
            result = _load_engine_metrics_from_prometheus("http://localhost:9091")

        assert result["prefect"]["selected"] == 0
        assert result["prefect"]["executions"] == 0

    def test_return_value_is_plain_dict(self) -> None:
        """The return type is dict, not defaultdict."""
        mock = _mock_urlopen("")

        with patch("mahavishnu.metrics_cli.urllib_request.urlopen", return_value=mock):
            result = _load_engine_metrics_from_prometheus("http://localhost:9091")

        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# add_metrics_commands
# ---------------------------------------------------------------------------


class TestAddMetricsCommands:
    """Tests for the add_metrics_commands registration helper."""

    def test_adds_metrics_sub_app(self) -> None:
        """add_metrics_commands registers 'metrics' as a sub-Typer on the parent app."""
        parent = typer.Typer()
        add_metrics_commands(parent)

        # Typer stores registered sub-apps as groups in registered_groups
        group_names = [g.name for g in parent.registered_groups]
        assert "metrics" in group_names

    def test_metrics_app_has_expected_commands(self) -> None:
        """The metrics_app has all the expected command names registered."""
        # Extract registered command names from the Typer app
        command_names = list(metrics_app.registered_commands)
        name_set = {cmd.name or cmd.callback.__name__ for cmd in command_names}
        for expected in (
            "collect",
            "report",
            "status",
            "history",
            "dashboard",
            "verify-endpoints",
            "engines",
        ):
            assert expected in name_set, f"command '{expected}' not found in {name_set}"
