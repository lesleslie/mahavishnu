"""Deployment Manager - Blue-green deployment support.

Provides deployment management with:

- Blue-green deployment strategy
- Health checks and automatic rollback
- Version tracking and history
- Deployment status management

Usage:
    from mahavishnu.core.deployment_manager import DeploymentManager, DeploymentConfig

    config = DeploymentConfig(
        name="api",
        image="app:v1.0",
        replicas=3,
    )

    manager = DeploymentManager(config=config)
    result = await manager.deploy("v1.0.0", "app:v1.0.0")
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, UTC
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class DeploymentStatus(str, Enum):
    """Deployment status types."""

    PENDING = "pending"
    DEPLOYING = "deploying"
    ACTIVE = "active"
    INACTIVE = "inactive"
    FAILED = "failed"
    ROLLING_BACK = "rolling_back"


@dataclass
class DeploymentVersion:
    """A deployment version.

    Attributes:
        version: Version identifier
        image: Container image
        deployed_at: Deployment timestamp
        status: Deployment status
    """

    version: str
    image: str
    deployed_at: datetime
    status: DeploymentStatus = DeploymentStatus.ACTIVE

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "version": self.version,
            "image": self.image,
            "deployed_at": self.deployed_at.isoformat(),
            "status": self.status.value,
        }


@dataclass
class BlueGreenStrategy:
    """Blue-green deployment strategy.

    Attributes:
        active_color: Current active color (blue/green)
        inactive_color: Current inactive color
        health_check_retries: Number of health check retries
        health_check_interval: Seconds between health checks
        auto_rollback: Whether to auto-rollback on failure
    """

    active_color: str = "blue"
    inactive_color: str = "green"
    health_check_retries: int = 3
    health_check_interval: int = 10
    auto_rollback: bool = True

    def swap(self) -> None:
        """Swap active and inactive colors."""
        self.active_color, self.inactive_color = (
            self.inactive_color,
            self.active_color,
        )


@dataclass
class DeploymentConfig:
    """Deployment configuration.

    Attributes:
        name: Deployment name
        image: Container image
        replicas: Number of replicas
        namespace: Kubernetes namespace
        health_check_path: Health check endpoint path
        health_check_port: Health check port
        strategy: Blue-green deployment strategy
    """

    name: str
    image: str
    replicas: int = 1
    namespace: str = "default"
    health_check_path: str = "/health"
    health_check_port: int = 8080
    strategy: BlueGreenStrategy = field(default_factory=BlueGreenStrategy)


@dataclass
class HealthCheckResult:
    """Result of a health check.

    Attributes:
        healthy: Whether the service is healthy
        status_code: HTTP status code
        response_time_ms: Response time in milliseconds
        error: Error message if unhealthy
    """

    healthy: bool
    status_code: int | None = None
    response_time_ms: float | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "healthy": self.healthy,
            "status_code": self.status_code,
            "response_time_ms": self.response_time_ms,
            "error": self.error,
        }


@dataclass
class DeploymentResult:
    """Result of a deployment operation.

    Attributes:
        deployment_id: Unique deployment identifier
        status: Deployment status
        version: Deployed version
        active_color: Active deployment color
        error: Error message if failed
        deployed_at: Deployment timestamp
    """

    deployment_id: str
    status: DeploymentStatus
    version: str
    active_color: str
    error: str | None = None
    deployed_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def success(self) -> bool:
        """Check if deployment was successful."""
        return self.status == DeploymentStatus.ACTIVE

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "deployment_id": self.deployment_id,
            "status": self.status.value,
            "version": self.version,
            "active_color": self.active_color,
            "success": self.success,
            "error": self.error,
            "deployed_at": self.deployed_at.isoformat(),
        }


class DeploymentManager:
    """Manages deployments with blue-green strategy.

    Features:
    - Blue-green deployment with zero downtime
    - Health checks before traffic switch
    - Automatic rollback on failure
    - Version history tracking

    Example:
        manager = DeploymentManager(config=DeploymentConfig(...))
        result = await manager.deploy("v1.0.0", "app:v1.0.0")
        if result.success:
            print(f"Deployed {result.version}")
    """

    def __init__(self, config: DeploymentConfig | None = None) -> None:
        """Initialize deployment manager.

        Args:
            config: Optional deployment configuration
        """
        self.config = config
        self.strategy = BlueGreenStrategy()
        self.deployments: dict[str, DeploymentResult] = {}
        self.versions: list[DeploymentVersion] = []

    def get_current_version(self) -> DeploymentVersion | None:
        """Get current active version.

        Returns:
            Current active version or None
        """
        for version in reversed(self.versions):
            if version.status == DeploymentStatus.ACTIVE:
                return version
        return None

    def get_previous_version(self) -> DeploymentVersion | None:
        """Get previous (inactive) version.

        Returns:
            Previous version or None
        """
        inactive_versions = [
            v for v in self.versions
            if v.status == DeploymentStatus.INACTIVE
        ]
        if inactive_versions:
            return inactive_versions[-1]
        return None

    async def deploy(
        self,
        version: str,
        image: str,
    ) -> DeploymentResult:
        """Deploy a new version.

        Args:
            version: Version identifier
            image: Container image

        Returns:
            DeploymentResult
        """
        deployment_id = f"deploy-{uuid.uuid4().hex[:8]}"

        logger.info(f"Starting deployment {deployment_id} version {version}")

        try:
            # Deploy to inactive slot
            deploy_success = await self._deploy_to_inactive(image)
            if not deploy_success:
                return DeploymentResult(
                    deployment_id=deployment_id,
                    status=DeploymentStatus.FAILED,
                    version=version,
                    active_color=self.strategy.active_color,
                    error="Failed to deploy to inactive slot",
                )

            # Run health checks
            health_result = await self._run_health_checks()
            if not health_result.healthy:
                if self.strategy.auto_rollback:
                    await self._cleanup_inactive()
                return DeploymentResult(
                    deployment_id=deployment_id,
                    status=DeploymentStatus.FAILED,
                    version=version,
                    active_color=self.strategy.active_color,
                    error=f"Health check failed: {health_result.error}",
                )

            # Switch traffic
            switch_success = await self._switch_traffic()
            if not switch_success:
                return DeploymentResult(
                    deployment_id=deployment_id,
                    status=DeploymentStatus.FAILED,
                    version=version,
                    active_color=self.strategy.active_color,
                    error="Failed to switch traffic",
                )

            # Mark old version as inactive
            current = self.get_current_version()
            if current:
                current.status = DeploymentStatus.INACTIVE

            # Add new version
            new_version = DeploymentVersion(
                version=version,
                image=image,
                deployed_at=datetime.now(UTC),
                status=DeploymentStatus.ACTIVE,
            )
            self.versions.append(new_version)

            result = DeploymentResult(
                deployment_id=deployment_id,
                status=DeploymentStatus.ACTIVE,
                version=version,
                active_color=self.strategy.active_color,
            )

            self.deployments[deployment_id] = result
            logger.info(f"Deployment {deployment_id} successful")

            return result

        except Exception as e:
            logger.error(f"Deployment {deployment_id} failed: {e}")
            return DeploymentResult(
                deployment_id=deployment_id,
                status=DeploymentStatus.FAILED,
                version=version,
                active_color=self.strategy.active_color,
                error=str(e),
            )

    async def rollback(self) -> DeploymentResult:
        """Rollback to previous version.

        Returns:
            DeploymentResult
        """
        deployment_id = f"rollback-{uuid.uuid4().hex[:8]}"

        previous = self.get_previous_version()
        if not previous:
            return DeploymentResult(
                deployment_id=deployment_id,
                status=DeploymentStatus.FAILED,
                version="",
                active_color=self.strategy.active_color,
                error="No previous version to rollback to",
            )

        logger.info(f"Starting rollback to {previous.version}")

        try:
            # Switch traffic back
            switch_success = await self._switch_traffic()
            if not switch_success:
                return DeploymentResult(
                    deployment_id=deployment_id,
                    status=DeploymentStatus.FAILED,
                    version=previous.version,
                    active_color=self.strategy.active_color,
                    error="Failed to switch traffic during rollback",
                )

            # Update version statuses
            current = self.get_current_version()
            if current:
                current.status = DeploymentStatus.INACTIVE
            previous.status = DeploymentStatus.ACTIVE

            result = DeploymentResult(
                deployment_id=deployment_id,
                status=DeploymentStatus.ACTIVE,
                version=previous.version,
                active_color=self.strategy.active_color,
            )

            self.deployments[deployment_id] = result
            logger.info(f"Rollback to {previous.version} successful")

            return result

        except Exception as e:
            logger.error(f"Rollback failed: {e}")
            return DeploymentResult(
                deployment_id=deployment_id,
                status=DeploymentStatus.FAILED,
                version=previous.version,
                active_color=self.strategy.active_color,
                error=str(e),
            )

    async def health_check(self) -> HealthCheckResult:
        """Run health check on active deployment.

        Returns:
            HealthCheckResult
        """
        return await self._make_health_request()

    async def _deploy_to_inactive(self, image: str) -> bool:
        """Deploy to inactive slot.

        Args:
            image: Container image

        Returns:
            True if successful
        """
        # Placeholder for actual deployment logic
        logger.info(f"Deploying {image} to {self.strategy.inactive_color}")
        return True

    async def _run_health_checks(self) -> HealthCheckResult:
        """Run health checks on inactive deployment.

        Returns:
            HealthCheckResult
        """
        for attempt in range(self.strategy.health_check_retries):
            result = await self._make_health_request()
            if result.healthy:
                return result
            logger.warning(f"Health check attempt {attempt + 1} failed")

        return HealthCheckResult(
            healthy=False,
            error="Health check retries exhausted",
        )

    async def _make_health_request(self) -> HealthCheckResult:
        """Make HTTP health check request.

        Returns:
            HealthCheckResult
        """
        # Placeholder for actual HTTP request
        # In production, this would make a real HTTP request
        return HealthCheckResult(
            healthy=True,
            status_code=200,
            response_time_ms=50.0,
        )

    async def _switch_traffic(self) -> bool:
        """Switch traffic to inactive slot.

        Returns:
            True if successful
        """
        self.strategy.swap()
        logger.info(f"Switched traffic to {self.strategy.active_color}")
        return True

    async def _cleanup_inactive(self) -> None:
        """Cleanup failed inactive deployment."""
        logger.info("Cleaning up inactive deployment")

    async def scale(self, replicas: int) -> bool:
        """Scale deployment replicas.

        Args:
            replicas: Target replica count

        Returns:
            True if successful
        """
        return await self._scale_replicas(replicas)

    async def _scale_replicas(self, replicas: int) -> bool:
        """Scale replicas.

        Args:
            replicas: Target replica count

        Returns:
            True if successful
        """
        logger.info(f"Scaling to {replicas} replicas")
        return True

    async def promote(self, deployment_id: str) -> DeploymentResult | None:
        """Promote inactive deployment to active.

        Args:
            deployment_id: Deployment to promote

        Returns:
            DeploymentResult or None
        """
        deployment = self.deployments.get(deployment_id)
        if not deployment:
            return None

        # Run health checks
        health_result = await self._run_health_checks()
        if not health_result.healthy:
            return DeploymentResult(
                deployment_id=deployment_id,
                status=DeploymentStatus.FAILED,
                version=deployment.version,
                active_color=self.strategy.active_color,
                error=health_result.error,
            )

        # Switch traffic
        await self._switch_traffic()

        deployment.status = DeploymentStatus.ACTIVE
        return deployment

    def get_deployment_status(self, deployment_id: str) -> DeploymentResult | None:
        """Get deployment status.

        Args:
            deployment_id: Deployment ID

        Returns:
            DeploymentResult or None
        """
        return self.deployments.get(deployment_id)

    def list_deployments(self) -> list[DeploymentResult]:
        """List all deployments.

        Returns:
            List of DeploymentResult
        """
        return list(self.deployments.values())

    def get_active_color(self) -> str:
        """Get active deployment color.

        Returns:
            Active color (blue/green)
        """
        return self.strategy.active_color

    def get_version_history(self) -> list[DeploymentVersion]:
        """Get version history.

        Returns:
            List of DeploymentVersion
        """
        return self.versions.copy()


__all__ = [
    "DeploymentManager",
    "DeploymentConfig",
    "DeploymentStatus",
    "DeploymentResult",
    "DeploymentVersion",
    "HealthCheckResult",
    "BlueGreenStrategy",
]
