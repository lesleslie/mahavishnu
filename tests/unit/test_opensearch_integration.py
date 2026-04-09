"""Unit tests for core.opensearch_integration."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import mahavishnu.core.opensearch_integration as osi


class _FakeIndices:
    def __init__(self, exists_map: dict[str, bool] | None = None) -> None:
        self.exists_map = exists_map or {}
        self.create_calls: list[tuple[str, dict]] = []
        self.exists_calls: list[str] = []

    async def exists(self, index: str) -> bool:
        self.exists_calls.append(index)
        return self.exists_map.get(index, False)

    async def create(self, index: str, body: dict) -> dict:
        self.create_calls.append((index, body))
        return {"acknowledged": True}


class _FakeClient:
    def __init__(self) -> None:
        self.indices = _FakeIndices()
        self.index_calls: list[tuple[str, dict]] = []
        self.search_calls: list[tuple[str, dict]] = []
        self.ping_value = True
        self.closed = False
        self.search_responses: list[dict] = []

    async def index(self, index: str, body: dict) -> dict:
        self.index_calls.append((index, body))
        return {"result": "created"}

    async def search(self, index: str, body: dict) -> dict:
        self.search_calls.append((index, body))
        if self.search_responses:
            return self.search_responses.pop(0)
        return {"hits": {"hits": []}}

    async def ping(self) -> bool:
        return self.ping_value

    async def close(self) -> None:
        self.closed = True


def _config() -> SimpleNamespace:
    return SimpleNamespace(
        opensearch=SimpleNamespace(
            endpoint="http://localhost:9200",
            use_ssl=False,
            verify_certs=False,
            ssl_assert_hostname=False,
            ssl_show_warn=False,
            ca_certs=None,
        ),
        opensearch_log_index="mahavishnu-logs",
        opensearch_workflow_index="mahavishnu-workflows",
    )


@pytest.fixture(autouse=True)
def _force_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(osi, "OPENSEARCH_AVAILABLE", False)


@pytest.mark.asyncio
async def test_mock_clients_exercise_fallback_methods() -> None:
    client = osi.MockAsyncOpenSearch()
    assert await client.ping() is True
    assert await client.index(index="x", body={"k": "v"}) == {"result": "created"}
    assert await client.search(index="x", body={}) == {"hits": {"hits": [], "total": {"value": 0}}}
    indices = await client.indices()
    assert await indices.exists(index="x") is False
    assert await indices.create(index="x", body={}) == {"acknowledged": True}


@pytest.mark.asyncio
async def test_init_uses_mock_client_and_initializes_indices() -> None:
    analytics = osi.OpenSearchLogAnalytics(_config())
    assert analytics.client is not None

    fake = _FakeClient()
    analytics.client = fake
    await analytics._ensure_indices()
    assert analytics._indices_initialized is True
    assert fake.indices.create_calls  # both log/workflow indices attempted


@pytest.mark.asyncio
async def test_create_indices_handles_exceptions(caplog: pytest.LogCaptureFixture) -> None:
    analytics = osi.OpenSearchLogAnalytics(_config())

    class _BadIndices(_FakeIndices):
        async def exists(self, index: str) -> bool:
            raise RuntimeError("exists failed")

    bad = _FakeClient()
    bad.indices = _BadIndices()
    analytics.client = bad

    await analytics._create_log_index()
    await analytics._create_workflow_index()
    assert "Failed to create log index" in caplog.text
    assert "Failed to create workflow index" in caplog.text


def test_init_with_opensearch_available_success_and_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(osi, "OPENSEARCH_AVAILABLE", True)

    class _CtorClient:
        def __init__(self, **kwargs) -> None:  # noqa: ANN003
            self.kwargs = kwargs

    monkeypatch.setattr(osi, "AsyncOpenSearch", _CtorClient)
    analytics = osi.OpenSearchLogAnalytics(_config())
    assert isinstance(analytics.client, _CtorClient)

    class _BoomClient:
        def __init__(self, **kwargs) -> None:  # noqa: ANN003
            raise RuntimeError("ctor failed")

    monkeypatch.setattr(osi, "AsyncOpenSearch", _BoomClient)
    analytics_fail = osi.OpenSearchLogAnalytics(_config())
    assert isinstance(analytics_fail.client, osi.MockAsyncOpenSearch)


def test_import_success_branch_uses_real_async_client_symbol(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib.util
    import sys
    from types import ModuleType

    fake_pkg = ModuleType("opensearchpy")

    class _CtorClient:
        def __init__(self, *args, **kwargs) -> None:  # noqa: ANN003
            self.args = args
            self.kwargs = kwargs

    fake_pkg.AsyncOpenSearch = _CtorClient
    monkeypatch.setitem(sys.modules, "opensearchpy", fake_pkg)

    spec = importlib.util.spec_from_file_location("opensearch_integration_success", osi.__file__)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    assert module.OPENSEARCH_AVAILABLE is True
    assert module.AsyncOpenSearch is _CtorClient
    sys.modules.pop(spec.name, None)


@pytest.mark.asyncio
async def test_log_event_and_workflow_event_index_docs() -> None:
    analytics = osi.OpenSearchLogAnalytics(_config())
    fake = _FakeClient()
    analytics.client = fake

    await analytics.log_event(
        level="INFO",
        message="hello",
        attributes={"k": "v"},
        trace_id="t1",
        workflow_id="w1",
        repo_path="/tmp/repo",
        adapter="agno",
    )
    await analytics.log_workflow_event(
        workflow_id="w1",
        adapter="agno",
        task_type="workflow",
        status="running",
        progress=10,
    )

    assert len(fake.index_calls) == 2
    assert fake.index_calls[0][0] == analytics.log_index
    assert fake.index_calls[1][0] == analytics.workflow_index


@pytest.mark.asyncio
async def test_log_event_returns_when_client_none() -> None:
    analytics = osi.OpenSearchLogAnalytics(_config())
    analytics.client = None
    await analytics.log_event(level="INFO", message="x")
    await analytics.log_workflow_event(
        workflow_id="w", adapter="a", task_type="t", status="s"
    )


@pytest.mark.asyncio
async def test_create_index_and_log_event_error_branches(caplog: pytest.LogCaptureFixture) -> None:
    analytics = osi.OpenSearchLogAnalytics(_config())
    analytics.client = None
    await analytics._create_log_index()
    await analytics._create_workflow_index()

    class _BoomClient(_FakeClient):
        async def index(self, index: str, body: dict) -> dict:
            raise RuntimeError("boom")

    analytics.client = _BoomClient()
    await analytics.log_event(level="INFO", message="hello")
    await analytics.log_workflow_event(workflow_id="w", adapter="a", task_type="t", status="s")
    assert "Failed to log event to OpenSearch" in caplog.text
    assert "Failed to log workflow event to OpenSearch" in caplog.text


@pytest.mark.asyncio
async def test_search_logs_builds_match_all_and_filters() -> None:
    analytics = osi.OpenSearchLogAnalytics(_config())
    fake = _FakeClient()
    fake.search_responses = [{"hits": {"hits": [{"_source": {"msg": "a"}}]}}]
    analytics.client = fake

    # no filters -> match_all
    out = await analytics.search_logs()
    assert out == [{"msg": "a"}]
    assert fake.search_calls[0][1]["query"] == {"match_all": {}}

    # filters -> bool must
    fake.search_responses = [{"hits": {"hits": [{"_source": {"msg": "b"}}]}}]
    out = await analytics.search_logs(
        query="error",
        level="ERROR",
        workflow_id="w1",
        repo_path="/r",
        start_time="2026-01-01T00:00:00Z",
        end_time="2026-01-02T00:00:00Z",
        size=50,
    )
    assert out == [{"msg": "b"}]
    body = fake.search_calls[1][1]
    assert body["size"] == 50
    must = body["query"]["bool"]["must"]
    assert any("simple_query_string" in x for x in must)
    assert any(x.get("term", {}).get("level") == "ERROR" for x in must)
    assert any(x.get("term", {}).get("workflow_id") == "w1" for x in must)
    assert any(x.get("term", {}).get("repo_path") == "/r" for x in must)
    assert any("range" in x for x in must)


@pytest.mark.asyncio
async def test_search_logs_handles_exceptions_and_none_client() -> None:
    analytics = osi.OpenSearchLogAnalytics(_config())
    analytics.client = None
    assert await analytics.search_logs() == []

    class _BadClient(_FakeClient):
        async def search(self, index: str, body: dict) -> dict:
            raise RuntimeError("boom")

    analytics.client = _BadClient()
    assert await analytics.search_logs(query="x") == []


@pytest.mark.asyncio
async def test_search_workflows_builds_filters_and_handles_error() -> None:
    analytics = osi.OpenSearchLogAnalytics(_config())
    analytics.client = None
    assert await analytics.search_workflows() == []

    analytics.client = _FakeClient()
    fake = _FakeClient()
    fake.search_responses = [{"hits": {"hits": [{"_source": {"id": "w1"}}]}}]
    analytics.client = fake

    out = await analytics.search_workflows(
        workflow_id="w1",
        adapter="agno",
        task_type="workflow",
        status="running",
        start_time="2026-01-01T00:00:00Z",
        end_time="2026-01-02T00:00:00Z",
        size=10,
    )
    assert out == [{"id": "w1"}]
    must = fake.search_calls[0][1]["query"]["bool"]["must"]
    assert any(x.get("term", {}).get("workflow_id") == "w1" for x in must)
    assert any(x.get("term", {}).get("adapter") == "agno" for x in must)
    assert any(x.get("term", {}).get("task_type") == "workflow" for x in must)
    assert any(x.get("term", {}).get("status") == "running" for x in must)

    class _BadClient(_FakeClient):
        async def search(self, index: str, body: dict) -> dict:
            raise RuntimeError("boom")

    analytics.client = _BadClient()
    assert await analytics.search_workflows() == []


@pytest.mark.asyncio
async def test_workflow_and_log_stats_happy_and_error_paths() -> None:
    analytics = osi.OpenSearchLogAnalytics(_config())
    analytics.client = None
    assert await analytics.get_workflow_stats() == {}
    assert await analytics.get_log_stats() == {}

    fake = _FakeClient()
    fake.search_responses = [
        {"hits": {"total": {"value": 5}}},
        {"aggregations": {"status_breakdown": {"buckets": [{"key": "completed", "doc_count": 3}]}}},
        {"aggregations": {"adapter_breakdown": {"buckets": [{"key": "agno", "doc_count": 2}]}}},
        {"hits": {"total": {"value": 12}}},
        {"aggregations": {"level_breakdown": {"buckets": [{"key": "ERROR", "doc_count": 4}]}}},
    ]
    analytics.client = fake

    wf_stats = await analytics.get_workflow_stats()
    assert wf_stats["total_workflows"] == 5
    assert wf_stats["status_breakdown"]["completed"] == 3
    assert wf_stats["adapter_breakdown"]["agno"] == 2

    log_stats = await analytics.get_log_stats()
    assert log_stats["total_logs"] == 12
    assert log_stats["level_breakdown"]["ERROR"] == 4

    class _BadClient(_FakeClient):
        async def search(self, index: str, body: dict) -> dict:
            raise RuntimeError("boom")

    analytics.client = _BadClient()
    assert await analytics.get_workflow_stats() == {}
    assert await analytics.get_log_stats() == {}


@pytest.mark.asyncio
async def test_health_check_and_close_paths() -> None:
    analytics = osi.OpenSearchLogAnalytics(_config())
    analytics.client = None
    result = await analytics.health_check()
    assert result["status"] == "unavailable"

    fake = _FakeClient()
    fake.indices.exists_map = {
        analytics.log_index: True,
        analytics.workflow_index: False,
    }
    analytics.client = fake
    healthy = await analytics.health_check()
    assert healthy["status"] == "healthy"
    assert healthy["indices"]["logs"] is True
    assert healthy["indices"]["workflows"] is False

    fake.ping_value = False
    unhealthy = await analytics.health_check()
    assert unhealthy["status"] == "unhealthy"

    class _ErrClient(_FakeClient):
        async def ping(self) -> bool:
            raise RuntimeError("network down")

    analytics.client = _ErrClient()
    bad = await analytics.health_check()
    assert bad["status"] == "unhealthy"
    assert "network down" in bad["error"]

    analytics.client = fake
    await analytics.close()
    assert fake.closed is True


@pytest.mark.asyncio
async def test_open_search_integration_wrapper_methods(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Analytics:
        def __init__(self, _cfg) -> None:
            self.calls: list[tuple[str, tuple, dict]] = []

        async def log_workflow_event(self, *args, **kwargs):
            self.calls.append(("log_workflow_event", args, kwargs))

        async def log_event(self, *args, **kwargs):
            self.calls.append(("log_event", args, kwargs))

        async def search_logs(self, **kwargs):
            return [{"k": "logs", **kwargs}]

        async def search_workflows(self, **kwargs):
            return [{"k": "wfs", **kwargs}]

        async def get_workflow_stats(self):
            return {"wf": 1}

        async def get_log_stats(self):
            return {"logs": 1}

        async def health_check(self):
            return {"status": "healthy"}

    monkeypatch.setattr(osi, "OpenSearchLogAnalytics", _Analytics)
    integration = osi.OpenSearchIntegration(_config())

    await integration.log_workflow_start("w1", "agno", "workflow", ["r1"])
    await integration.log_workflow_update("w1", "running", progress=20, adapter="agno")
    await integration.log_workflow_completion(
        "w1", "completed", execution_time=1.2, results_count=2, errors_count=0, adapter="agno"
    )
    await integration.log_error("w1", "boom", repo_path="/repo", adapter="agno")

    logs = await integration.search_logs(query="x")
    wfs = await integration.search_workflows(status="completed")
    wf_stats = await integration.get_workflow_stats()
    log_stats = await integration.get_log_stats()
    health = await integration.health_check()

    assert logs[0]["k"] == "logs"
    assert wfs[0]["k"] == "wfs"
    assert wf_stats == {"wf": 1}
    assert log_stats == {"logs": 1}
    assert health["status"] == "healthy"
    assert any(name == "log_workflow_event" for name, _, _ in integration.analytics.calls)
    assert any(name == "log_event" for name, _, _ in integration.analytics.calls)
