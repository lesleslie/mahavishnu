"""Tests for mahavishnu.pools.runpod_public_pool — REST substrate.

Sister file to ``test_runpod_pool.py``. Sister pool class
:func:`RunPodPublicEndpointPool` exercises the
``POST /v2/{endpoint_id}/runsync`` REST surface against RunPod
Public Endpoints (``moonshot-kimi``, ``granite-4-0-h-small``, etc.),
distinct from :class:`RunPodPool` which uses the ``runpod`` SDK
against operator-deployed serverless endpoints.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from mahavishnu.pools.base import PoolConfig, PoolMetrics, PoolStatus
from mahavishnu.pools.runpod_public_pool import DEFAULT_RUNPOD_BASE_URL, RunPodPublicEndpointPool


def _make_pool_config(**overrides) -> PoolConfig:
    """Build a PoolConfig with a valid public ``endpoint_id``."""
    defaults: dict[str, object] = {
        "name": "test-runpod-public",
        "pool_type": "runpod_public",
        "min_workers": 1,
        "max_workers": 10,
        "extra_config": {"endpoint_id": "granite-4-0-h-small"},
    }
    defaults.update(overrides)
    return PoolConfig(**defaults)  # type: ignore[arg-type]


def _fake_response(
    status_code: int = 200,
    status_value: str = "COMPLETED",
    output_value: object = None,
    error_value: object = None,
) -> MagicMock:
    """Return a MagicMock shaped like a RunPod Public Endpoints response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = RuntimeError(f"HTTP {status_code}")
    resp.json.return_value = {
        "status": status_value,
        "output": output_value,
        "error": error_value,
    }
    return resp


# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------


class TestRunPodPublicEndpointPoolInit:
    def test_defaults(self):
        cfg = _make_pool_config()
        pool = RunPodPublicEndpointPool(config=cfg)
        assert pool.config.pool_type == "runpod_public"
        assert pool._client is None
        assert pool._tasks_completed == 0
        assert pool._tasks_failed == 0
        assert pool._task_durations == []
        assert pool._status == PoolStatus.PENDING
        assert pool._endpoint_id == "granite-4-0-h-small"

    def test_extra_config_parsed(self):
        cfg = PoolConfig(
            name="p",
            pool_type="runpod_public",
            extra_config={
                "endpoint_id": "moonshot-kimi",
                "api_key": "rp-secret",
                "endpoint_name": "my-moonshot",
                "num_workers": 7,
                "timeout_seconds": 60,
            },
        )
        pool = RunPodPublicEndpointPool(config=cfg)
        assert pool._endpoint_id == "moonshot-kimi"
        assert pool._api_key == "rp-secret"
        assert pool._endpoint_name == "my-moonshot"
        assert pool._num_workers == 7
        assert pool._timeout_seconds == 60

    def test_inherits_from_base(self):
        cfg = _make_pool_config()
        pool = RunPodPublicEndpointPool(config=cfg)
        assert pool.config is cfg
        assert "runpod_public" in pool.pool_id


# ---------------------------------------------------------------------------
# endpoint_id requirement
# ---------------------------------------------------------------------------


class TestRequiresEndpointId:
    def test_raises_when_endpoint_id_missing(self):
        cfg = PoolConfig(
            name="no-id",
            pool_type="runpod_public",
            extra_config={"endpoint_name": "test"},  # endpoint_id absent
        )
        with pytest.raises(ValueError, match="endpoint_id"):
            RunPodPublicEndpointPool(config=cfg)


# ---------------------------------------------------------------------------
# start()
# ---------------------------------------------------------------------------


class TestStart:
    @pytest.mark.asyncio
    async def test_start_builds_httpx_client(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("RUNPOD_API_KEY", "rp-test-key")
        cfg = _make_pool_config()
        pool = RunPodPublicEndpointPool(config=cfg)

        with patch("mahavishnu.pools.runpod_public_pool.httpx") as mock_httpx:
            fake_client = MagicMock(name="httpx-client")
            mock_httpx.Client.return_value = fake_client

            result = await pool.start()

        assert result == pool.pool_id
        assert pool._status == PoolStatus.RUNNING
        assert pool._client is fake_client
        # The bearer header carries the API key; base_url is the
        # RunPod REST root.
        mock_httpx.Client.assert_called_once()
        kwargs = mock_httpx.Client.call_args.kwargs
        assert kwargs["base_url"] == DEFAULT_RUNPOD_BASE_URL
        assert kwargs["headers"]["Authorization"] == "Bearer rp-test-key"

    @pytest.mark.asyncio
    async def test_start_sets_failed_on_exception(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("RUNPOD_API_KEY", "rp-test-key")
        cfg = _make_pool_config()
        pool = RunPodPublicEndpointPool(config=cfg)

        with patch(
            "mahavishnu.pools.runpod_public_pool.httpx",
            MagicMock(Client=MagicMock(side_effect=RuntimeError("auth failed"))),
        ):
            with pytest.raises(RuntimeError, match="auth failed"):
                await pool.start()
            assert pool._status == PoolStatus.FAILED

    @pytest.mark.asyncio
    async def test_start_raises_when_httpx_missing(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("RUNPOD_API_KEY", "rp-test-key")
        cfg = _make_pool_config()
        pool = RunPodPublicEndpointPool(config=cfg)

        # Force the ``httpx = None`` lazy-import failure path by
        # patching the module-level symbol after import.
        with patch("mahavishnu.pools.runpod_public_pool.httpx", None):
            with pytest.raises(RuntimeError, match="httpx2"):
                await pool.start()


# ---------------------------------------------------------------------------
# execute_task()
# ---------------------------------------------------------------------------


class TestExecuteTask:
    @pytest.mark.asyncio
    async def test_not_started_returns_failed(self):
        cfg = _make_pool_config()
        pool = RunPodPublicEndpointPool(config=cfg)
        pool._client = None
        pool._status = PoolStatus.PENDING

        result = await pool.execute_task({"prompt": "hello"})
        assert result["status"] == "failed"
        assert result["error"] == "Pool not started — call start() first"
        assert pool._tasks_failed == 0  # not counted as task failure

    @pytest.mark.asyncio
    async def test_success_tracks_completed(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("RUNPOD_API_KEY", "rp-test-key")
        cfg = _make_pool_config()
        pool = RunPodPublicEndpointPool(config=cfg)

        with patch("mahavishnu.pools.runpod_public_pool.httpx") as mock_httpx:
            fake_client = MagicMock(name="client")
            fake_client.post = MagicMock(
                return_value=_fake_response(
                    status_code=200,
                    status_value="COMPLETED",
                    output_value="hello world",
                )
            )
            mock_httpx.Client.return_value = fake_client
            await pool.start()

            result = await pool.execute_task({"prompt": "say hello"})

        assert result["status"] == "completed"
        assert result["output"] == "hello world"
        assert "granite-4-0-h-small" in result["worker_id"]
        # The POST goes to /v2/{endpoint_id}/runsync with the body
        # wrapped in ``{"input": payload}``.
        fake_client.post.assert_called_once_with(
            "/v2/granite-4-0-h-small/runsync",
            json={"input": {"prompt": "say hello"}},
        )
        assert pool._tasks_completed == 1
        assert pool._tasks_failed == 0

    @pytest.mark.asyncio
    async def test_http_error_maps_to_failed(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("RUNPOD_API_KEY", "rp-test-key")
        cfg = _make_pool_config()
        pool = RunPodPublicEndpointPool(config=cfg)

        with patch("mahavishnu.pools.runpod_public_pool.httpx") as mock_httpx:
            fake_client = MagicMock(name="client")
            # raise_for_status side effect to mimic a 4xx response
            resp = MagicMock()
            resp.status_code = 404
            resp.text = "not found"
            resp.raise_for_status.side_effect = RuntimeError("404")
            fake_client.post = MagicMock(return_value=resp)
            mock_httpx.Client.return_value = fake_client
            await pool.start()

            result = await pool.execute_task({"prompt": "x"})

        assert result["status"] == "failed"
        assert result["output"] is None
        assert "404" in (result["error"] or "")
        assert pool._tasks_failed == 1
        assert pool._tasks_completed == 0

    @pytest.mark.asyncio
    async def test_structured_error_in_response_maps_to_failed(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        # 200 OK with a non-empty ``error`` field is the public-endpoints
        # way of signalling "the run failed but came back". The pool
        # must surface this as a failure envelope.
        monkeypatch.setenv("RUNPOD_API_KEY", "rp-test-key")
        cfg = _make_pool_config()
        pool = RunPodPublicEndpointPool(config=cfg)

        with patch("mahavishnu.pools.runpod_public_pool.httpx") as mock_httpx:
            fake_client = MagicMock(name="client")
            fake_client.post = MagicMock(
                return_value=_fake_response(
                    status_code=200,
                    status_value="FAILED",
                    error_value="upstream blew up",
                )
            )
            mock_httpx.Client.return_value = fake_client
            await pool.start()

            result = await pool.execute_task({"prompt": "x"})

        assert result["status"] == "failed"
        assert "upstream blew up" in (result["error"] or "")

    @pytest.mark.asyncio
    async def test_non_completed_terminal_status_warns(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ):
        # Unknown terminal status (SDK drift defense): the pool
        # treats non-COMPLETED as failure but captures the output
        # if any.
        import logging

        monkeypatch.setenv("RUNPOD_API_KEY", "rp-test-key")
        cfg = _make_pool_config()
        pool = RunPodPublicEndpointPool(config=cfg)

        with patch("mahavishnu.pools.runpod_public_pool.httpx") as mock_httpx:
            fake_client = MagicMock(name="client")
            fake_client.post = MagicMock(
                return_value=_fake_response(
                    status_code=200,
                    status_value="CANCELLED",
                    output_value="partial",
                )
            )
            mock_httpx.Client.return_value = fake_client
            await pool.start()

            with caplog.at_level(logging.WARNING, logger="mahavishnu.pools.runpod_public_pool"):
                result = await pool.execute_task({"prompt": "x"})

        assert result["status"] == "cancelled"
        assert "non-COMPLETED" in (result["error"] or "")
        assert any("CANCELLED" in rec.message for rec in caplog.records)

    @pytest.mark.asyncio
    async def test_generic_exception_maps_to_failed(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("RUNPOD_API_KEY", "rp-test-key")
        cfg = _make_pool_config()
        pool = RunPodPublicEndpointPool(config=cfg)

        with patch("mahavishnu.pools.runpod_public_pool.httpx") as mock_httpx:
            fake_client = MagicMock(name="client")
            fake_client.post = MagicMock(side_effect=RuntimeError("network down"))
            mock_httpx.Client.return_value = fake_client
            await pool.start()

            result = await pool.execute_task({"prompt": "x"})

        assert result["status"] == "failed"
        assert "network down" in (result["error"] or "")
        assert pool._tasks_failed == 1


# ---------------------------------------------------------------------------
# Health + metrics + memory + stop
# ---------------------------------------------------------------------------


class TestHealthAndMetrics:
    @pytest.mark.asyncio
    async def test_unhealthy_when_not_started(self):
        cfg = _make_pool_config()
        pool = RunPodPublicEndpointPool(config=cfg)
        pool._client = None
        pool._status = PoolStatus.PENDING

        health = await pool.health_check()
        assert health["status"] == "unhealthy"
        assert health["endpoint_id"] == "granite-4-0-h-small"
        assert health["pool_type"] == "runpod_public"

    @pytest.mark.asyncio
    async def test_healthy_when_running(self):
        cfg = _make_pool_config()
        pool = RunPodPublicEndpointPool(config=cfg)
        pool._client = MagicMock()
        pool._status = PoolStatus.RUNNING
        pool._tasks_completed = 3
        pool._tasks_failed = 1

        health = await pool.health_check()
        assert health["status"] == "healthy"
        assert health["tasks_completed"] == 3
        assert health["tasks_failed"] == 1

    @pytest.mark.asyncio
    async def test_metrics_reflect_task_stats(self):
        cfg = _make_pool_config()
        pool = RunPodPublicEndpointPool(config=cfg)
        pool._status = PoolStatus.RUNNING
        pool._tasks_completed = 5
        pool._tasks_failed = 1
        pool._task_durations = [1.0, 2.0, 3.0, 4.0, 5.0]

        metrics = await pool.get_metrics()
        assert isinstance(metrics, PoolMetrics)
        assert metrics.tasks_completed == 5
        assert metrics.tasks_failed == 1
        assert metrics.avg_task_duration == pytest.approx(3.0)


class TestStop:
    @pytest.mark.asyncio
    async def test_stop_closes_client(self):
        cfg = _make_pool_config()
        pool = RunPodPublicEndpointPool(config=cfg)
        mock_client = MagicMock()
        pool._client = mock_client
        pool._status = PoolStatus.RUNNING
        pool._task_results.append(
            {"worker_id": "wp-1", "output": "x", "status": "completed", "timestamp": 1.0}
        )

        await pool.stop()
        mock_client.close.assert_called_once()
        assert pool._client is None
        assert pool._status == PoolStatus.STOPPED
        assert len(pool._task_results) == 0


# ---------------------------------------------------------------------------
# Registry integration
# ---------------------------------------------------------------------------


class TestRegistryIntegration:
    def test_pool_type_registered(self):
        from mahavishnu.pools._registry import _POOL_FACTORIES

        assert "runpod_public" in _POOL_FACTORIES
