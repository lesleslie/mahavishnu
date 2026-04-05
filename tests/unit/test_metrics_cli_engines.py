"""Tests for `mahavishnu metrics engines` helper logic."""

from __future__ import annotations

from urllib import request as urllib_request

from mahavishnu.metrics_cli import _load_engine_metrics_from_prometheus


class _FakeResponse:
    def __init__(self, payload: str):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return self._payload.encode("utf-8")


def test_load_engine_metrics_from_prometheus_aggregates_counts(monkeypatch):
    payload = """
# HELP mahavishnu_routing_decisions_total Total routing decisions
mahavishnu_routing_decisions_total{server="mahavishnu",adapter="prefect",task_type="workflow"} 2
mahavishnu_routing_decisions_total{server="mahavishnu",adapter="agno",task_type="ai_task"} 1
mahavishnu_adapter_executions_total{server="mahavishnu",adapter="prefect",status="success"} 3
mahavishnu_adapter_executions_total{server="mahavishnu",adapter="prefect",status="failure"} 1
mahavishnu_adapter_executions_total{server="mahavishnu",adapter="agno",status="timeout"} 2
"""

    def fake_urlopen(url: str, timeout: float = 2.0):  # pragma: no cover - signature shim
        return _FakeResponse(payload)

    monkeypatch.setattr(urllib_request, "urlopen", fake_urlopen)
    metrics = _load_engine_metrics_from_prometheus("http://127.0.0.1:8680/metrics")

    assert metrics["prefect"]["selected"] == 2
    assert metrics["prefect"]["executions"] == 4
    assert metrics["prefect"]["success"] == 3
    assert metrics["prefect"]["failure"] == 1

    assert metrics["agno"]["selected"] == 1
    assert metrics["agno"]["executions"] == 2
    assert metrics["agno"]["success"] == 0
    assert metrics["agno"]["failure"] == 2

    # Expected engines are always present
    assert "llamaindex" in metrics


def test_load_engine_metrics_from_prometheus_falls_back_to_workflow_counter(monkeypatch):
    payload = """
mahavishnu_workflows_total{adapter="llamaindex",task_type="rag_query",status="completed"} 5
mahavishnu_workflows_total{adapter="llamaindex",task_type="rag_query",status="failed"} 2
"""

    def fake_urlopen(url: str, timeout: float = 2.0):  # pragma: no cover - signature shim
        return _FakeResponse(payload)

    monkeypatch.setattr(urllib_request, "urlopen", fake_urlopen)
    metrics = _load_engine_metrics_from_prometheus("http://127.0.0.1:8680/metrics")

    assert metrics["llamaindex"]["executions"] == 7
    assert metrics["llamaindex"]["success"] == 5
    assert metrics["llamaindex"]["failure"] == 2
