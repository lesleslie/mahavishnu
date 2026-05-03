"""Tests for mahavishnu.pools.kubernetes_pool — KubernetesPool."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.pools.base import PoolConfig, PoolMetrics, PoolStatus
from mahavishnu.pools.kubernetes_pool import KubernetesPool


def _make_k8s_mock():
    """Create a mock kubernetes module."""
    mock_k8s = MagicMock()

    # config module
    mock_config = MagicMock()
    mock_k8s.config = mock_config

    # client submodule — source does `from kubernetes import client`
    mock_client = MagicMock()
    mock_k8s.client = mock_client

    # Client classes (on the client submodule)
    mock_core_api = MagicMock()
    mock_batch_api = MagicMock()
    mock_client.CoreV1Api = MagicMock(return_value=mock_core_api)
    mock_client.BatchV1Api = MagicMock(return_value=mock_batch_api)

    # Model objects (on the client submodule) — must be callable, not classes
    mock_client.V1Namespace = MagicMock()
    mock_client.V1ObjectMeta = MagicMock()
    mock_client.V1Job = MagicMock()
    mock_client.V1JobSpec = MagicMock()
    mock_client.V1PodTemplateSpec = MagicMock()
    mock_client.V1PodSpec = MagicMock()
    mock_client.V1Container = MagicMock()
    mock_client.V1DeleteOptions = MagicMock()

    # Exceptions (on the client submodule)
    mock_client.exceptions = MagicMock()
    mock_client.exceptions.ApiException = type("ApiException", (Exception,), {})

    return mock_k8s, mock_core_api, mock_batch_api


def _make_pool_config(**overrides):
    defaults = {"name": "test-k8s", "pool_type": "kubernetes"}
    defaults.update(overrides)
    return PoolConfig(**defaults)


class TestKubernetesPoolInit:
    """Test KubernetesPool initialization."""

    def test_defaults(self):
        cfg = _make_pool_config()
        pool = KubernetesPool(config=cfg)
        assert pool.namespace == "mahavishnu"
        assert pool.kubeconfig_path is None
        assert pool.container_image == "python:3.13-slim"
        assert pool._k8s_client is None
        assert pool._active_jobs == {}
        assert pool._tasks_completed == 0
        assert pool._tasks_failed == 0
        assert pool._task_durations == []

    def test_custom_params(self):
        cfg = _make_pool_config()
        pool = KubernetesPool(
            config=cfg,
            namespace="custom-ns",
            kubeconfig_path="/path/to/kubeconfig",
            container_image="myimage:latest",
        )
        assert pool.namespace == "custom-ns"
        assert pool.kubeconfig_path == "/path/to/kubeconfig"
        assert pool.container_image == "myimage:latest"

    def test_inherits_from_base(self):
        cfg = _make_pool_config()
        pool = KubernetesPool(config=cfg)
        assert pool.config is cfg
        assert pool._status.value == "pending"
        assert "kubernetes" in pool.pool_id


class TestEnsureK8sClient:
    """Test _ensure_k8s_client method."""

    @pytest.mark.asyncio
    async def test_import_error_raises_runtime_error(self):
        cfg = _make_pool_config()
        pool = KubernetesPool(config=cfg)

        with patch.dict("sys.modules", {"kubernetes": None}):
            # ImportError because kubernetes module is None
            with pytest.raises(RuntimeError, match="kubernetes.*package"):
                await pool._ensure_k8s_client()

    @pytest.mark.asyncio
    async def test_client_initialized_once(self):
        cfg = _make_pool_config()
        pool = KubernetesPool(config=cfg)

        mock_k8s, _, _ = _make_k8s_mock()
        with patch.dict("sys.modules", {"kubernetes": mock_k8s}):
            await pool._ensure_k8s_client()
            assert pool._k8s_client is not None
            first_client = pool._k8s_client

            # Second call should return same client
            await pool._ensure_k8s_client()
            assert pool._k8s_client is first_client

    @pytest.mark.asyncio
    async def test_kubeconfig_path_loads_config(self):
        cfg = _make_pool_config()
        pool = KubernetesPool(config=cfg, kubeconfig_path="/custom/config")

        mock_k8s, _, _ = _make_k8s_mock()
        with patch.dict("sys.modules", {"kubernetes": mock_k8s}):
            await pool._ensure_k8s_client()
            # Source uses: from kubernetes import config as k8s_config
            # So mock_k8s.config is the config module
            mock_k8s.config.load_kube_config.assert_called_once_with(config_file="/custom/config")

    @pytest.mark.asyncio
    async def test_no_kubeconfig_uses_incluster(self):
        cfg = _make_pool_config()
        pool = KubernetesPool(config=cfg, kubeconfig_path=None)

        mock_k8s, _, _ = _make_k8s_mock()
        with patch.dict("sys.modules", {"kubernetes": mock_k8s}):
            await pool._ensure_k8s_client()
            mock_k8s.config.load_incluster_config.assert_called_once()


class TestKubernetesPoolStart:
    """Test start method."""

    @pytest.mark.asyncio
    async def test_start_success(self):
        cfg = _make_pool_config()
        pool = KubernetesPool(config=cfg, namespace="test-ns")

        mock_k8s, mock_core_api, _ = _make_k8s_mock()
        with patch.dict("sys.modules", {"kubernetes": mock_k8s}):
            result = await pool.start()
            assert result == pool.pool_id
            assert pool._status.value == "running"
            mock_k8s.client.CoreV1Api.assert_called()
            mock_core_api.create_namespace.assert_called_once()

    @pytest.mark.asyncio
    async def test_namespace_already_exists(self):
        cfg = _make_pool_config()
        pool = KubernetesPool(config=cfg)

        mock_k8s, mock_core_api, _ = _make_k8s_mock()
        # 409 = Conflict (namespace exists)
        conflict_err = mock_k8s.client.exceptions.ApiException()
        conflict_err.status = 409
        mock_core_api.create_namespace.side_effect = conflict_err

        with patch.dict("sys.modules", {"kubernetes": mock_k8s}):
            result = await pool.start()
            assert result == pool.pool_id
            assert pool._status.value == "running"

    @pytest.mark.asyncio
    async def test_start_failure(self):
        cfg = _make_pool_config()
        pool = KubernetesPool(config=cfg)

        mock_k8s, _, _ = _make_k8s_mock()
        mock_k8s.client.CoreV1Api.side_effect = RuntimeError("cluster unreachable")

        with patch.dict("sys.modules", {"kubernetes": mock_k8s}):
            with pytest.raises(RuntimeError, match="cluster unreachable"):
                await pool.start()
            assert pool._status.value == "failed"


class TestKubernetesPoolStop:
    """Test stop method."""

    @pytest.mark.asyncio
    async def test_stop_without_client(self):
        cfg = _make_pool_config()
        pool = KubernetesPool(config=cfg)
        pool._status = PoolStatus.RUNNING

        mock_k8s, _, _ = _make_k8s_mock()
        with patch.dict("sys.modules", {"kubernetes": mock_k8s}):
            await pool.stop()
            assert pool._status.value == "stopped"

    @pytest.mark.asyncio
    async def test_stop_deletes_jobs(self):
        cfg = _make_pool_config()
        pool = KubernetesPool(config=cfg)
        pool._k8s_client = MagicMock()
        pool._active_jobs = {"task1": "job-1", "task2": "job-2"}

        mock_k8s, _, mock_batch = _make_k8s_mock()
        with patch.dict("sys.modules", {"kubernetes": mock_k8s}):
            await pool.stop()
            assert mock_batch.delete_namespaced_job.call_count == 2
            assert pool._active_jobs == {}


class TestKubernetesPoolScale:
    """Test scale method."""

    @pytest.mark.asyncio
    async def test_scale_is_noop(self):
        cfg = _make_pool_config()
        pool = KubernetesPool(config=cfg)
        # Should not raise — K8s pools scale automatically
        await pool.scale(target_worker_count=100)


class TestKubernetesPoolExecuteTask:
    """Test execute_task method."""

    @pytest.mark.asyncio
    async def test_execute_task_with_prompt(self):
        cfg = _make_pool_config()
        pool = KubernetesPool(config=cfg)

        mock_k8s, _, mock_batch = _make_k8s_mock()

        # Mock _wait_for_job and _get_job_logs
        pool._wait_for_job = AsyncMock()
        pool._get_job_logs = MagicMock(return_value="task output")

        with patch.dict("sys.modules", {"kubernetes": mock_k8s}):
            result = await pool.execute_task({"prompt": "hello world"})
            assert result["status"] == "completed"
            assert result["output"] == "task output"
            assert result["pool_id"] == pool.pool_id
            assert pool._tasks_completed == 1
            assert len(pool._task_durations) == 1
            assert "kubernet" in result["worker_id"]

    @pytest.mark.asyncio
    async def test_execute_task_with_command(self):
        cfg = _make_pool_config()
        pool = KubernetesPool(config=cfg)

        mock_k8s, _, _ = _make_k8s_mock()
        pool._wait_for_job = AsyncMock()
        pool._get_job_logs = MagicMock(return_value="cmd output")

        with patch.dict("sys.modules", {"kubernetes": mock_k8s}):
            result = await pool.execute_task({"command": "echo hello"})
            assert result["status"] == "completed"

    @pytest.mark.asyncio
    async def test_execute_task_timeout(self):
        cfg = _make_pool_config()
        pool = KubernetesPool(config=cfg)

        mock_k8s, _, _ = _make_k8s_mock()
        pool._wait_for_job = AsyncMock(side_effect=TimeoutError("timed out"))

        with patch.dict("sys.modules", {"kubernetes": mock_k8s}):
            result = await pool.execute_task({"prompt": "slow task"})
            assert result["status"] == "timeout"
            assert result["error"] == "timed out"
            assert pool._tasks_failed == 1

    @pytest.mark.asyncio
    async def test_execute_task_exception(self):
        cfg = _make_pool_config()
        pool = KubernetesPool(config=cfg)

        mock_k8s, _, mock_batch = _make_k8s_mock()
        pool._wait_for_job = AsyncMock()
        pool._get_job_logs = MagicMock(side_effect=RuntimeError("pod crash"))

        # Make batch_api raise
        mock_batch.create_namespaced_job.side_effect = RuntimeError("pod crash")

        with patch.dict("sys.modules", {"kubernetes": mock_k8s}):
            result = await pool.execute_task({"prompt": "bad task"})
            assert result["status"] == "failed"
            assert "pod crash" in result["error"]
            assert pool._tasks_failed == 1


class TestKubernetesPoolExecuteBatch:
    """Test execute_batch method."""

    @pytest.mark.asyncio
    async def test_execute_batch(self):
        cfg = _make_pool_config()
        pool = KubernetesPool(config=cfg)
        pool.execute_task = AsyncMock(
            side_effect=[
                {"status": "completed", "output": "r1"},
                {"status": "completed", "output": "r2"},
                {"status": "failed", "error": "err"},
            ]
        )

        results = await pool.execute_batch([{}, {}, {}])
        assert len(results) == 3
        assert results["0"]["output"] == "r1"
        assert results["2"]["error"] == "err"


class TestKubernetesPoolHealthCheck:
    """Test health_check method."""

    @pytest.mark.asyncio
    async def test_healthy_with_active_jobs(self):
        cfg = _make_pool_config()
        pool = KubernetesPool(config=cfg)
        pool._tasks_completed = 5

        mock_k8s, mock_core_api, mock_batch = _make_k8s_mock()

        # Namespace exists
        mock_core_api.read_namespace.return_value = MagicMock()

        # Active job
        active_job = MagicMock()
        active_job.status.active = 1
        mock_batch.list_namespaced_job.return_value = MagicMock(items=[active_job])

        with patch.dict("sys.modules", {"kubernetes": mock_k8s}):
            health = await pool.health_check()
            assert health["status"] == "healthy"
            assert health["active_jobs"] == 1
            assert health["tasks_completed"] == 5

    @pytest.mark.asyncio
    async def test_degraded_no_active_jobs(self):
        cfg = _make_pool_config()
        pool = KubernetesPool(config=cfg)

        mock_k8s, mock_core_api, mock_batch = _make_k8s_mock()
        mock_core_api.read_namespace.return_value = MagicMock()
        mock_batch.list_namespaced_job.return_value = MagicMock(items=[])

        with patch.dict("sys.modules", {"kubernetes": mock_k8s}):
            health = await pool.health_check()
            assert health["status"] == "degraded"

    @pytest.mark.asyncio
    async def test_unhealthy_namespace_missing(self):
        cfg = _make_pool_config()
        pool = KubernetesPool(config=cfg)

        mock_k8s, mock_core_api, _ = _make_k8s_mock()
        mock_core_api.read_namespace.side_effect = mock_k8s.client.exceptions.ApiException()

        with patch.dict("sys.modules", {"kubernetes": mock_k8s}):
            health = await pool.health_check()
            assert health["status"] == "unhealthy"

    @pytest.mark.asyncio
    async def test_health_check_exception(self):
        cfg = _make_pool_config()
        pool = KubernetesPool(config=cfg)

        mock_k8s, _, _ = _make_k8s_mock()
        mock_k8s.client.CoreV1Api.side_effect = RuntimeError("no cluster")

        with patch.dict("sys.modules", {"kubernetes": mock_k8s}):
            health = await pool.health_check()
            assert health["status"] == "unhealthy"
            assert "no cluster" in health["error"]


class TestKubernetesPoolGetMetrics:
    """Test get_metrics method."""

    @pytest.mark.asyncio
    async def test_get_metrics(self):
        cfg = _make_pool_config()
        pool = KubernetesPool(config=cfg)
        pool._tasks_completed = 10
        pool._tasks_failed = 2
        pool._task_durations = [1.0, 2.0, 3.0]

        mock_k8s, mock_core_api, _ = _make_k8s_mock()
        mock_core_api.read_namespace.return_value = MagicMock()
        mock_k8s.client.BatchV1Api.return_value.list_namespaced_job.return_value = MagicMock(
            items=[]
        )

        with patch.dict("sys.modules", {"kubernetes": mock_k8s}):
            metrics = await pool.get_metrics()
            assert isinstance(metrics, PoolMetrics)
            assert metrics.tasks_completed == 10
            assert metrics.tasks_failed == 2
            assert metrics.avg_task_duration == pytest.approx(2.0)

    @pytest.mark.asyncio
    async def test_get_metrics_empty_durations(self):
        cfg = _make_pool_config()
        pool = KubernetesPool(config=cfg)

        mock_k8s, mock_core_api, _ = _make_k8s_mock()
        mock_core_api.read_namespace.return_value = MagicMock()

        with patch.dict("sys.modules", {"kubernetes": mock_k8s}):
            metrics = await pool.get_metrics()
            assert metrics.avg_task_duration == 0.0


class TestKubernetesPoolCollectMemory:
    """Test collect_memory method."""

    @pytest.mark.asyncio
    async def test_collect_memory(self):
        cfg = _make_pool_config()
        pool = KubernetesPool(config=cfg)
        pool._active_jobs = {"t1": "job-a", "t2": "job-b"}
        pool._get_job_logs = MagicMock(return_value="log data")

        memories = await pool.collect_memory()
        assert len(memories) == 2
        assert all(m["metadata"]["pool_type"] == "kubernetes" for m in memories)
        assert all(m["metadata"]["pool_id"] == pool.pool_id for m in memories)

    @pytest.mark.asyncio
    async def test_collect_memory_with_log_failure(self):
        cfg = _make_pool_config()
        pool = KubernetesPool(config=cfg)
        pool._active_jobs = {"t1": "job-a"}
        pool._get_job_logs = MagicMock(side_effect=RuntimeError("pod gone"))

        memories = await pool.collect_memory()
        # Source catches exception and logs warning, skipping the item
        assert len(memories) == 0


class TestCreateJobSpec:
    """Test _create_job_spec method."""

    def test_create_job_spec_called(self):
        cfg = _make_pool_config()
        pool = KubernetesPool(config=cfg, container_image="custom:latest")

        mock_k8s, _, _ = _make_k8s_mock()
        with patch.dict("sys.modules", {"kubernetes": mock_k8s}):
            result = pool._create_job_spec("echo hello", "test-job")

            # V1Job was called — result is a MagicMock from V1Job()
            mock_k8s.client.V1Job.assert_called_once()
            assert result is not None

    def test_create_job_spec_uses_container_image(self):
        cfg = _make_pool_config()
        pool = KubernetesPool(config=cfg, container_image="myapp:v2")

        mock_k8s, _, _ = _make_k8s_mock()
        with patch.dict("sys.modules", {"kubernetes": mock_k8s}):
            pool._create_job_spec("echo test", "job-x")
            # V1Container was called — check container image in call args
            mock_k8s.client.V1Container.assert_called()
            call_args = mock_k8s.client.V1Container.call_args
            # image should be in the keyword args
            assert "image" in call_args.kwargs or any("myapp:v2" in str(v) for v in call_args.args)


class TestGetJobLogs:
    """Test _get_job_logs method."""

    def test_get_job_logs_success(self):
        cfg = _make_pool_config()
        pool = KubernetesPool(config=cfg, namespace="logs-ns")

        mock_k8s, mock_core_api, _ = _make_k8s_mock()
        mock_pod = MagicMock()
        mock_pod.metadata.name = "pod-abc"
        mock_core_api.list_namespaced_pod.return_value = MagicMock(items=[mock_pod])
        mock_core_api.read_namespaced_pod_log.return_value = "line1\nline2"

        with patch.dict("sys.modules", {"kubernetes": mock_k8s}):
            logs = pool._get_job_logs("my-job")
            assert logs == "line1\nline2"

    def test_get_job_logs_no_pods(self):
        cfg = _make_pool_config()
        pool = KubernetesPool(config=cfg, namespace="empty-ns")

        mock_k8s, mock_core_api, _ = _make_k8s_mock()
        mock_core_api.list_namespaced_pod.return_value = MagicMock(items=[])

        with patch.dict("sys.modules", {"kubernetes": mock_k8s}):
            logs = pool._get_job_logs("missing-job")
            assert logs == ""

    def test_get_job_logs_read_failure(self):
        cfg = _make_pool_config()
        pool = KubernetesPool(config=cfg, namespace="err-ns")

        mock_k8s, mock_core_api, _ = _make_k8s_mock()
        mock_pod = MagicMock()
        mock_pod.metadata.name = "pod-xyz"
        mock_core_api.list_namespaced_pod.return_value = MagicMock(items=[mock_pod])
        mock_core_api.read_namespaced_pod_log.side_effect = Exception("connection refused")

        with patch.dict("sys.modules", {"kubernetes": mock_k8s}):
            logs = pool._get_job_logs("broken-job")
            assert logs == ""
