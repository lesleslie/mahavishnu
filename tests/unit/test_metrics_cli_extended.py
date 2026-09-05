from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import typer

import mahavishnu.metrics_cli as m


def test_postgres_loader_maps_rows_and_closes() -> None:
    conn = AsyncMock()
    conn.fetch.side_effect = [
        [{"adapter": "new", "selected_count": 3}],
        [{"adapter": "new", "execution_count": 5, "success_count": 4, "failure_count": 1}],
    ]
    fake = SimpleNamespace(connect=AsyncMock(return_value=conn))
    with patch.dict("sys.modules", {"asyncpg": fake}):
        result = asyncio.run(m._load_engine_metrics_from_postgres("dsn", 2))
    assert result["new"] == {"selected": 3, "executions": 5, "success": 4, "failure": 1}
    conn.close.assert_awaited_once()


def test_postgres_loader_without_asyncpg() -> None:
    with patch.dict("sys.modules", {"asyncpg": None}), pytest.raises(RuntimeError, match="asyncpg"):
        asyncio.run(m._load_engine_metrics_from_postgres("dsn", None))


def test_prometheus_malformed_lines_and_labels() -> None:
    metrics = {"prefect": {"selected": 0, "executions": 0, "success": 0, "failure": 0}}
    for line in ("garbage", "# comment", "", 'x{adapter="prefect"} nope', 'x{foo="bar"} 2'):
        m._process_prometheus_line(line, metrics)
    assert metrics["prefect"]["executions"] == 0
    assert m._parse_labels('a="1", malformed,b = "2"') == {"a": "1", "b": "2"}


def test_collect_command_success_and_error(monkeypatch: pytest.MonkeyPatch) -> None:
    import scripts.collect_metrics as script
    monkeypatch.setattr(script, "main", lambda: 0, raising=False)
    with pytest.raises(SystemExit) as exc:
        m.collect_metrics(True, 75.0, True, "json")
    assert exc.value.code == 0
    assert "--create-issues" in m.sys.argv and "--store-metrics" in m.sys.argv
    monkeypatch.setattr(script, "main", lambda: (_ for _ in ()).throw(RuntimeError("bad")))
    with pytest.raises(SystemExit) as exc:
        m.collect_metrics()
    assert exc.value.code == 1


def test_report_success_and_error(monkeypatch: pytest.MonkeyPatch) -> None:
    import scripts.collect_metrics as script
    monkeypatch.setattr(script, "main", lambda: 0, raising=False)
    with pytest.raises(SystemExit) as exc:
        m.generate_report("markdown", Path("out.md"))
    assert exc.value.code == 0
    monkeypatch.setattr(script, "main", lambda: (_ for _ in ()).throw(RuntimeError("bad")))
    with pytest.raises(SystemExit) as exc:
        m.generate_report()
    assert exc.value.code == 1




def test_history_missing_empty_and_snapshots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Path, "cwd", classmethod(lambda cls: tmp_path))
    m.show_history()
    d = tmp_path / "data" / "metrics"; d.mkdir(parents=True)
    (d / "metrics_1.json").write_text(json.dumps({"timestamp":"2025-01-01T00:00:00Z","summary":{"avg_coverage":70,"repos_count":2,"total_files_tested":4}}))
    (d / "metrics_2.json").write_text(json.dumps({"timestamp":"2025-01-02T00:00:00Z","summary":{"avg_coverage":75,"repos_count":2,"total_files_tested":5}}))
    (d / "metrics_bad.json").write_text("not json")
    m.show_history(10)


def test_dashboard_and_verify_endpoints(monkeypatch: pytest.MonkeyPatch) -> None:
    import scripts.generate_metrics_dashboard as dashboard
    monkeypatch.setattr(dashboard, "main", lambda: 0, raising=False)
    with patch("webbrowser.open") as browser, pytest.raises(SystemExit) as exc:
        m.generate_dashboard("x.html", True)
    assert exc.value.code == 0; browser.assert_called_once()
    monkeypatch.setattr(dashboard, "main", lambda: (_ for _ in ()).throw(RuntimeError("bad")))
    with pytest.raises(SystemExit) as exc:
        m.generate_dashboard()
    assert exc.value.code == 1
    with patch("scripts.verify_ecosystem_metrics.main", return_value=0), pytest.raises(typer.Exit) as exc:
        m.verify_endpoints(Path("i.yml"), Path("v.yml"), "json", 1.0, ["a", "b"])
    assert exc.value.exit_code == 0


def test_engine_helpers_and_paths() -> None:
    rows = m._build_engine_rows({"x": {"selected": 1, "executions": 2, "success": 1, "failure": 1}})
    assert rows[0]["success_rate_pct"] == 50.0
    with patch("mahavishnu.metrics_cli.console.print_json") as out:
        m._render_engine_output(rows, "json", "prometheus", "url", None, ["warn"]); out.assert_called_once()
    m._render_engine_output(rows, "table", "prometheus", "url", None, [])
    with pytest.raises(typer.Exit): m._render_engine_output(rows, "bad", "x", "url", None, [])
    with patch.object(m, "_load_engine_metrics_from_prometheus", return_value={"prefect": {"executions": 1, "success": 1}}):
        got = m._fetch_engine_metrics("prometheus", None, "url", None)
    assert got[1] == "prometheus"
    with patch.object(m, "_resolve_postgres_dsn", return_value=None), pytest.raises(typer.Exit):
        m.engine_metrics("invalid")
    with pytest.raises(typer.Exit): m._fetch_engine_metrics("postgres", None, "url", None)


def test_bodai_helpers_and_loaders(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    assert m._load_bodai_queue(missing) == [] and m._load_bodai_state(missing) is None
    q = tmp_path / "q"; q.write_text("{}")
    s = tmp_path / "s"; s.write_text("[]")
    assert m._load_bodai_queue(q) == [] and m._load_bodai_state(s) is None
    assert m._parse_bodai_timestamp(0) is not None
    assert m._parse_bodai_timestamp("bad") is None
    ev = [{"headers":{"source":"akosha","timestamp":datetime.now(UTC).isoformat()},"payload":{"workflow_id":"w"},"topic":"t"}]
    assert m._component_counts(ev)["akosha"] == 1
    assert m._component_last_seen(ev)["akosha"] is not None
    m._render_recent_event(ev); m._render_recent_event([{"topic":"x","payload":{}}])
    m._render_filter_note(1, "akosha")


def test_dhara_helpers_and_renderers() -> None:
    assert m._resolve_dhara_url("http://x/") == "http://x"
    with patch.dict("os.environ", {"MAHAVISHNU_DHARA_URL":"http://env/"}): assert m._resolve_dhara_url(None) == "http://env"
    assert m._parse_since("all") is None and m._parse_since("30m") is not None
    with pytest.raises(typer.Exit): m._parse_since("bad")
    entries = [{"key":"verification/a","value":{"consensus":"reject","persisted":False,"timestamp":datetime.now(UTC).isoformat()}}, {"key":"verification/b","value":{}}]
    with patch.object(m.console, "print_json") as out:
        m._render_verification_output(entries, cutoff=None, output_format="json", dhara_url="u"); out.assert_called_once()
    m._render_verification_output(entries, cutoff=None, output_format="table", dhara_url="u")
    with pytest.raises(typer.Exit): m._render_verification_output([], cutoff=None, output_format="x", dhara_url="u")
    with patch.object(m.console, "print_json") as out:
        m._render_dispatch_output([{"key":"routing/a","value":{"caller_kind":"cli","async_callback":True}}], cutoff=None, output_format="json", dhara_url="u"); out.assert_called_once()
    m._render_dispatch_output([], cutoff=None, output_format="table", dhara_url="u")
    with pytest.raises(typer.Exit): m._render_dispatch_output([], cutoff=None, output_format="x", dhara_url="u")


def test_fetch_dhara_entries_and_commands() -> None:
    client = AsyncMock()
    client.call_tool.return_value = [{"key":"a","value":{"x":1}}, {"bad":1}, "x"]
    fake = SimpleNamespace(DharaClient=MagicMock(return_value=client))
    with patch.dict("sys.modules", {"mahavishnu.core.dhara_adapter": fake}):
        assert asyncio.run(m._fetch_dhara_entries("u", "p")) == [{"key":"a","value":{"x":1}}]
    with patch.object(m, "_fetch_dhara_entries", new=AsyncMock(return_value=[])), patch.object(m, "_resolve_dhara_url", return_value="u"):
        m.verification_metrics("all", None, "table"); m.dispatch_metrics("all", None, "table")
