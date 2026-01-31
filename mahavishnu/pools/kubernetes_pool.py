"""Kubernetes-native worker pool.

Deploys workers as K8s Jobs/Pods.

NOTE: This pool type requires a Kubernetes cluster and is not currently tested
due to lack of available cluster infrastructure. The implementation follows the
specification but should be tested before production use.
"""

import asyncio
import logging
import time
from typing import Any

from .base import BasePool, PoolConfig, PoolStatus

logger = logging.getLogger(__name__)


class KubernetesPool(BasePool):
    """Kubernetes-native worker pool.

    Deploys workers as K8s Jobs for cloud-native execution.

    Use Cases:
    - Cloud deployments
    - Auto-scaling workloads
    - Multi-cluster execution
    - Resource quotas

    Architecture:
    ┌─────────────────────────────────────┐
    │      KubernetesPool                 │
    │  • Python k8s client                │
    │  • Job management                   │
    │  • Pod monitoring                   │
    └─────────────────────────────────────┘
            │ k8s API
            ↓
    ┌───────────────────────┐
    │  Kubernetes Cluster   │
    ├───────────────────────┤
    │  Namespace: mahavishnu│
    │  • Jobs               │
    │  • Pods               │
    └───────────────────────┘
    """

    def __init__(
        self,
        config: PoolConfig,
        namespace: str = "mahavishnu",
        kubeconfig_path: str | None = None,
        container_image: str = "python:3.13-slim",
    ):
        """Initialize KubernetesPool.

        Args:
            config: Pool configuration
            namespace: Kubernetes namespace
            kubeconfig_path: Path to kubeconfig file (None = in-cluster config)
            container_image: Container image for worker pods
        """
        super().__init__(config)
        self.namespace = namespace
        self.kubeconfig_path = kubeconfig_path
        self.container_image = container_image
        self._k8s_client = None
        self._active_jobs: dict[str, str] = {}  # task_id -> job_name

        # Track task statistics
        self._tasks_completed = 0
        self._tasks_failed = 0
        self._task_durations: list[float] = []

    async def _ensure_k8s_client(self) -> None:
        """Ensure Kubernetes client is initialized.

        Raises:
            ImportError: If kubernetes package is not installed
            Exception: If kubeconfig cannot be loaded
        """
        if self._k8s_client is not None:
            return

        try:
            from kubernetes import client, config as k8s_config

            # Load kubeconfig
            if self.kubeconfig_path:
                k8s_config.load_kube_config(config_file=self.kubeconfig_path)
            else:
                k8s_config.load_incluster_config()

            self._k8s_client = client
            logger.info("Kubernetes client initialized")

        except ImportError as e:
            logger.error("kubernetes package not installed")
            raise RuntimeError(
                "KubernetesPool requires 'kubernetes' package. "
                "Install it with: pip install kubernetes"
            ) from e
        except Exception as e:
            logger.error(f"Failed to initialize Kubernetes client: {e}")
            raise

    async def start(self) -> str:
        """Initialize K8s client and create namespace.

        Returns:
            pool_id: Unique pool identifier
        """
        self._status = PoolStatus.INITIALIZING

        try:
            await self._ensure_k8s_client()

            # Create namespace if it doesn't exist
            from kubernetes import client

            core_api = client.CoreV1Api()

            try:
                core_api.create_namespace(
                    body=client.V1Namespace(
                        metadata=client.V1ObjectMeta(name=self.namespace)
                    )
                )
                logger.info(f"Created namespace: {self.namespace}")
            except client.exceptions.ApiException as e:
                if e.status == 409:
                    # Namespace already exists
                    logger.info(f"Namespace {self.namespace} already exists")
                else:
                    raise

            self._status = PoolStatus.RUNNING
            logger.info(f"KubernetesPool {self.pool_id} started (namespace: {self.namespace})")

        except Exception as e:
            logger.error(f"Failed to start KubernetesPool: {e}")
            self._status = PoolStatus.FAILED
            raise

        return self.pool_id

    async def execute_task(self, task: dict[str, Any]) -> dict[str, Any]:
        """Execute task as K8s Job.

        Args:
            task: Task specification with 'command' or 'prompt' field

        Returns:
            Execution result
        """
        await self._ensure_k8s_client()

        from kubernetes import client

        # Create K8s Job
        job_name = f"mahavishnu-{self.pool_id[:8]}-{id(task)}"

        # Prepare command
        command = task.get("command")
        prompt = task.get("prompt", "")

        if not command:
            # Default command for AI task execution
            command = f'python -c "print(\'{prompt}\')"'

        job_spec = self._create_job_spec(command, job_name)

        start_time = time.time()
        try:
            batch_api = client.BatchV1Api()
            job = batch_api.create_namespaced_job(
                namespace=self.namespace,
                body=job_spec,
            )

            self._active_jobs[id(task)] = job_name
            logger.info(f"Created K8s Job: {job_name}")

            # Wait for completion
            timeout = task.get("timeout", 300)
            await self._wait_for_job(job_name, timeout=timeout)

            # Collect logs
            logs = self._get_job_logs(job_name)
            duration = time.time() - start_time

            self._tasks_completed += 1
            self._task_durations.append(duration)

            return {
                "pool_id": self.pool_id,
                "worker_id": job_name,
                "status": "completed",
                "output": logs,
                "error": None,
                "duration": duration,
            }

        except TimeoutError as e:
            logger.error(f"K8s Job {job_name} timed out: {e}")
            self._tasks_failed += 1
            return {
                "pool_id": self.pool_id,
                "worker_id": job_name,
                "status": "timeout",
                "output": None,
                "error": str(e),
                "duration": time.time() - start_time,
            }

        except Exception as e:
            logger.error(f"K8s Job {job_name} failed: {e}")
            self._tasks_failed += 1
            return {
                "pool_id": self.pool_id,
                "worker_id": job_name,
                "status": "failed",
                "output": None,
                "error": str(e),
                "duration": time.time() - start_time,
            }

    async def execute_batch(self, tasks: list[dict[str, Any]]) -> dict[str, Any]:
        """Execute multiple tasks as K8s Jobs.

        Args:
            tasks: List of task specifications

        Returns:
            Dictionary mapping task_id -> result
        """
        # Execute tasks concurrently
        coros = [self.execute_task(task) for task in tasks]
        results = await asyncio.gather(*coros)

        return {
            str(i): result
            for i, result in enumerate(results)
        }

    async def scale(self, target_worker_count: int) -> None:
        """Scale not applicable for K8s (job-based execution).

        KubernetesPool uses job-based execution rather than persistent workers,
        so scaling is handled automatically by K8s based on job submission rate.

        Args:
            target_worker_count: Desired worker count (ignored)

        Note:
            Consider using K8s HorizontalPodAutoscaler for auto-scaling
        """
        # K8s pools scale automatically based on job submission
        # Consider implementing HPA instead
        logger.info(
            f"KubernetesPool scales automatically based on job submission. "
            f"Target {target_worker_count} not applicable."
        )

    async def health_check(self) -> dict[str, Any]:
        """Check K8s cluster health.

        Returns:
            Health status dictionary
        """
        try:
            await self._ensure_k8s_client()
            from kubernetes import client

            core_api = client.CoreV1Api()

            # Check namespace exists
            try:
                core_api.read_namespace(self.namespace)
                ns_status = "healthy"
            except client.exceptions.ApiException:
                ns_status = "unhealthy"

            # Count active jobs
            batch_api = client.BatchV1Api()
            jobs = batch_api.list_namespaced_job(self.namespace)
            active_jobs = [j for j in jobs.items if j.status.active]

            pool_status = "healthy"
            if ns_status == "unhealthy":
                pool_status = "unhealthy"
            elif len(active_jobs) == 0:
                pool_status = "degraded"

            return {
                "pool_id": self.pool_id,
                "pool_type": "kubernetes",
                "status": pool_status,
                "namespace": self.namespace,
                "active_jobs": len(active_jobs),
                "total_jobs": len(self._active_jobs),
                "tasks_completed": self._tasks_completed,
                "tasks_failed": self._tasks_failed,
            }

        except Exception as e:
            logger.error(f"Failed health check for KubernetesPool: {e}")
            return {
                "pool_id": self.pool_id,
                "pool_type": "kubernetes",
                "status": "unhealthy",
                "error": str(e),
            }

    async def get_metrics(self) -> dict[str, Any]:
        """Get K8s pool metrics.

        Returns:
            PoolMetrics with current stats
        """
        from .base import PoolMetrics

        health = await self.health_check()

        # Calculate average task duration
        avg_duration = (
            sum(self._task_durations) / len(self._task_durations)
            if self._task_durations
            else 0.0
        )

        return PoolMetrics(
            pool_id=self.pool_id,
            status=self._status,
            active_workers=health.get("active_jobs", 0),
            total_workers=len(self._active_jobs),
            tasks_completed=self._tasks_completed,
            tasks_failed=self._tasks_failed,
            avg_task_duration=avg_duration,
            memory_usage_mb=0.0,
        )

    async def collect_memory(self) -> list[dict[str, Any]]:
        """Collect memory from completed K8s Jobs.

        Returns:
            List of memory dictionaries
        """
        # Query completed jobs and extract logs
        # Store in Session-Buddy via MCP
        memory_items = []

        for task_id, job_name in self._active_jobs.items():
            try:
                logs = self._get_job_logs(job_name)
                memory_items.append({
                    "content": logs or "",
                    "metadata": {
                        "type": "pool_worker_execution",
                        "pool_id": self.pool_id,
                        "pool_type": "kubernetes",
                        "worker_id": job_name,
                        "status": "completed",
                        "timestamp": time.time(),
                    },
                })
            except Exception as e:
                logger.warning(f"Failed to collect logs from {job_name}: {e}")

        logger.info(
            f"Collected {len(memory_items)} memory items from KubernetesPool {self.pool_id}"
        )

        return memory_items

    async def stop(self) -> None:
        """Cleanup K8s resources."""
        logger.info(f"Stopping KubernetesPool {self.pool_id}...")

        if self._k8s_client is None:
            self._status = PoolStatus.STOPPED
            return

        from kubernetes import client

        batch_api = client.BatchV1Api()

        # Delete all jobs created by this pool
        for job_name in self._active_jobs.values():
            try:
                batch_api.delete_namespaced_job(
                    name=job_name,
                    namespace=self.namespace,
                    body=client.V1DeleteOptions(),
                )
                logger.info(f"Deleted K8s Job: {job_name}")
            except Exception as e:
                logger.warning(f"Failed to delete job {job_name}: {e}")

        self._active_jobs.clear()
        self._status = PoolStatus.STOPPED
        logger.info(f"KubernetesPool {self.pool_id} stopped")

    def _create_job_spec(self, command: str, job_name: str) -> dict:
        """Create K8s Job manifest.

        Args:
            command: Command to execute
            job_name: Job name

        Returns:
            Job specification dictionary
        """
        from kubernetes import client

        return client.V1Job(
            api_version="batch/v1",
            kind="Job",
            metadata=client.V1ObjectMeta(
                name=job_name,
                labels={"app": "mahavishnu", "pool": self.pool_id},
            ),
            spec=client.V1JobSpec(
                backoff_limit=3,
                template=client.V1PodTemplateSpec(
                    metadata=client.V1ObjectMeta(
                        labels={"app": "mahavishnu", "pool": self.pool_id},
                    ),
                    spec=client.V1PodSpec(
                        restart_policy="Never",
                        containers=[
                            client.V1Container(
                                name="worker",
                                image=self.container_image,
                                command=["/bin/sh", "-c", command],
                            )
                        ],
                    ),
                ),
            ),
        )

    async def _wait_for_job(self, job_name: str, timeout: int = 300) -> None:
        """Wait for K8s Job completion.

        Args:
            job_name: Job name
            timeout: Timeout in seconds

        Raises:
            TimeoutError: If job times out
            RuntimeError: If job fails
        """
        await self._ensure_k8s_client()
        from kubernetes import client

        batch_api = client.BatchV1Api()

        start_time = asyncio.get_event_loop().time()

        while True:
            job = batch_api.read_namespaced_job(job_name, self.namespace)

            if job.status.succeeded:
                logger.info(f"Job {job_name} succeeded")
                return
            elif job.status.failed:
                raise RuntimeError(f"Job {job_name} failed")

            elapsed = asyncio.get_event_loop().time() - start_time
            if elapsed > timeout:
                raise TimeoutError(f"Job {job_name} timed out after {elapsed:.1f}s")

            await asyncio.sleep(5)

    def _get_job_logs(self, job_name: str) -> str:
        """Get logs from K8s Job pods.

        Args:
            job_name: Job name

        Returns:
            Pod logs as string
        """
        from kubernetes import client

        core_api = client.CoreV1Api()

        # Get pods for this job
        pods = core_api.list_namespaced_pod(
            namespace=self.namespace,
            label_selector=f"job-name={job_name}",
        )

        if not pods.items:
            logger.warning(f"No pods found for job {job_name}")
            return ""

        # Get logs from first pod
        pod_name = pods.items[0].metadata.name

        try:
            logs = core_api.read_namespaced_pod_log(
                name=pod_name,
                namespace=self.namespace,
            )
            return logs
        except Exception as e:
            logger.warning(f"Failed to get logs from {pod_name}: {e}")
            return ""
