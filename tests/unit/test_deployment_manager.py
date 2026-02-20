"""Tests for Deployment Manager - Blue-green deployment support."""

import pytest
from datetime import datetime, UTC
from unittest.mock import MagicMock, AsyncMock, patch
from typing import Any

from mahavishnu.core.deployment_manager import (
    DeploymentManager,
    DeploymentConfig,
    DeploymentStatus,
    DeploymentResult,
    HealthCheckResult,
    BlueGreenStrategy,
    DeploymentVersion,
)


@pytest.fixture
def sample_deployment_config() -> DeploymentConfig:
    """Create a sample deployment configuration."""
    return DeploymentConfig(
        name="mahavishnu-api",
        image="mahavishnu:v1.0.0",
        replicas=3,
        namespace="production",
        health_check_path="/health",
        health_check_port=8080,
    )


class TestDeploymentStatus:
    """Tests for DeploymentStatus enum."""

    def test_deployment_statuses(self) -> None:
        """Test available deployment statuses."""
        assert DeploymentStatus.PENDING.value == "pending"
        assert DeploymentStatus.DEPLOYING.value == "deploying"
        assert DeploymentStatus.ACTIVE.value == "active"
        assert DeploymentStatus.INACTIVE.value == "inactive"
        assert DeploymentStatus.FAILED.value == "failed"
        assert DeploymentStatus.ROLLING_BACK.value == "rolling_back"


class TestDeploymentVersion:
    """Tests for DeploymentVersion class."""

    def test_create_version(self) -> None:
        """Create a deployment version."""
        version = DeploymentVersion(
            version="v1.0.0",
            image="mahavishnu:v1.0.0",
            deployed_at=datetime.now(UTC),
        )

        assert version.version == "v1.0.0"
        assert version.image == "mahavishnu:v1.0.0"
        assert version.status == DeploymentStatus.ACTIVE

    def test_version_to_dict(self) -> None:
        """Convert version to dictionary."""
        version = DeploymentVersion(
            version="v1.0.0",
            image="mahavishnu:v1.0.0",
            deployed_at=datetime.now(UTC),
            status=DeploymentStatus.ACTIVE,
        )

        d = version.to_dict()

        assert d["version"] == "v1.0.0"
        assert d["image"] == "mahavishnu:v1.0.0"
        assert d["status"] == "active"


class TestDeploymentConfig:
    """Tests for DeploymentConfig class."""

    def test_create_config(self) -> None:
        """Create a deployment configuration."""
        config = DeploymentConfig(
            name="test-api",
            image="test:v1",
            replicas=3,
        )

        assert config.name == "test-api"
        assert config.image == "test:v1"
        assert config.replicas == 3

    def test_config_defaults(self) -> None:
        """Test configuration defaults."""
        config = DeploymentConfig(
            name="test",
            image="test:latest",
        )

        assert config.replicas == 1
        assert config.namespace == "default"
        assert config.health_check_path == "/health"
        assert config.health_check_port == 8080

    def test_config_with_strategy(self) -> None:
        """Create config with deployment strategy."""
        config = DeploymentConfig(
            name="test",
            image="test:latest",
            strategy=BlueGreenStrategy(
                active_color="blue",
                inactive_color="green",
            ),
        )

        assert config.strategy.active_color == "blue"
        assert config.strategy.inactive_color == "green"


class TestBlueGreenStrategy:
    """Tests for BlueGreenStrategy class."""

    def test_create_strategy(self) -> None:
        """Create a blue-green strategy."""
        strategy = BlueGreenStrategy(
            active_color="blue",
            inactive_color="green",
        )

        assert strategy.active_color == "blue"
        assert strategy.inactive_color == "green"

    def test_strategy_defaults(self) -> None:
        """Test strategy defaults."""
        strategy = BlueGreenStrategy()

        assert strategy.active_color == "blue"
        assert strategy.inactive_color == "green"
        assert strategy.health_check_retries == 3
        assert strategy.health_check_interval == 10

    def test_swap_colors(self) -> None:
        """Swap active and inactive colors."""
        strategy = BlueGreenStrategy(active_color="blue")

        strategy.swap()

        assert strategy.active_color == "green"
        assert strategy.inactive_color == "blue"


class TestHealthCheckResult:
    """Tests for HealthCheckResult class."""

    def test_healthy_result(self) -> None:
        """Create a healthy result."""
        result = HealthCheckResult(
            healthy=True,
            status_code=200,
            response_time_ms=50.0,
        )

        assert result.healthy is True
        assert result.status_code == 200

    def test_unhealthy_result(self) -> None:
        """Create an unhealthy result."""
        result = HealthCheckResult(
            healthy=False,
            error="Connection refused",
        )

        assert result.healthy is False
        assert result.error == "Connection refused"

    def test_result_to_dict(self) -> None:
        """Convert result to dictionary."""
        result = HealthCheckResult(
            healthy=True,
            status_code=200,
            response_time_ms=50.0,
        )

        d = result.to_dict()

        assert d["healthy"] is True
        assert d["status_code"] == 200
        assert d["response_time_ms"] == 50.0


class TestDeploymentResult:
    """Tests for DeploymentResult class."""

    def test_success_result(self) -> None:
        """Create a successful result."""
        result = DeploymentResult(
            deployment_id="deploy-123",
            status=DeploymentStatus.ACTIVE,
            version="v1.0.0",
            active_color="blue",
        )

        assert result.deployment_id == "deploy-123"
        assert result.status == DeploymentStatus.ACTIVE
        assert result.success is True

    def test_failed_result(self) -> None:
        """Create a failed result."""
        result = DeploymentResult(
            deployment_id="deploy-123",
            status=DeploymentStatus.FAILED,
            version="v1.0.0",
            active_color="blue",
            error="Health check failed",
        )

        assert result.status == DeploymentStatus.FAILED
        assert result.success is False
        assert result.error == "Health check failed"

    def test_result_to_dict(self) -> None:
        """Convert result to dictionary."""
        result = DeploymentResult(
            deployment_id="deploy-123",
            status=DeploymentStatus.ACTIVE,
            version="v1.0.0",
            active_color="blue",
        )

        d = result.to_dict()

        assert d["deployment_id"] == "deploy-123"
        assert d["status"] == "active"
        assert d["success"] is True


class TestDeploymentManager:
    """Tests for DeploymentManager class."""

    def test_create_manager(self) -> None:
        """Create a deployment manager."""
        manager = DeploymentManager()

        assert manager is not None
        assert len(manager.deployments) == 0

    def test_create_manager_with_config(
        self,
        sample_deployment_config: DeploymentConfig,
    ) -> None:
        """Create manager with configuration."""
        manager = DeploymentManager(config=sample_deployment_config)

        assert manager.config.name == "mahavishnu-api"

    def test_get_current_version(self) -> None:
        """Get current deployed version."""
        manager = DeploymentManager()

        # No versions yet
        assert manager.get_current_version() is None

        # Add a version
        manager.versions.append(DeploymentVersion(
            version="v1.0.0",
            image="test:v1",
            deployed_at=datetime.now(UTC),
            status=DeploymentStatus.ACTIVE,
        ))

        current = manager.get_current_version()
        assert current is not None
        assert current.version == "v1.0.0"

    def test_get_previous_version(self) -> None:
        """Get previous deployed version."""
        manager = DeploymentManager()

        # Add two versions
        manager.versions.append(DeploymentVersion(
            version="v1.0.0",
            image="test:v1",
            deployed_at=datetime.now(UTC),
            status=DeploymentStatus.INACTIVE,
        ))
        manager.versions.append(DeploymentVersion(
            version="v2.0.0",
            image="test:v2",
            deployed_at=datetime.now(UTC),
            status=DeploymentStatus.ACTIVE,
        ))

        prev = manager.get_previous_version()
        assert prev is not None
        assert prev.version == "v1.0.0"

    @pytest.mark.asyncio
    async def test_deploy(
        self,
        sample_deployment_config: DeploymentConfig,
    ) -> None:
        """Deploy a new version."""
        manager = DeploymentManager(config=sample_deployment_config)

        # Mock the deployment steps
        with patch.object(manager, '_deploy_to_inactive', new_callable=AsyncMock) as mock_deploy:
            with patch.object(manager, '_run_health_checks', new_callable=AsyncMock) as mock_health:
                with patch.object(manager, '_switch_traffic', new_callable=AsyncMock) as mock_switch:
                    mock_deploy.return_value = True
                    mock_health.return_value = HealthCheckResult(healthy=True)
                    mock_switch.return_value = True

                    result = await manager.deploy("v2.0.0", "mahavishnu:v2.0.0")

                    assert result.success is True
                    assert result.status == DeploymentStatus.ACTIVE

    @pytest.mark.asyncio
    async def test_deploy_with_failure(
        self,
        sample_deployment_config: DeploymentConfig,
    ) -> None:
        """Deploy with failure."""
        manager = DeploymentManager(config=sample_deployment_config)

        with patch.object(manager, '_deploy_to_inactive', new_callable=AsyncMock) as mock_deploy:
            mock_deploy.return_value = False

            result = await manager.deploy("v2.0.0", "mahavishnu:v2.0.0")

            assert result.success is False
            assert result.status == DeploymentStatus.FAILED

    @pytest.mark.asyncio
    async def test_rollback(self) -> None:
        """Rollback to previous version."""
        manager = DeploymentManager()

        # Add versions
        manager.versions.append(DeploymentVersion(
            version="v1.0.0",
            image="test:v1",
            deployed_at=datetime.now(UTC),
            status=DeploymentStatus.INACTIVE,
        ))
        manager.versions.append(DeploymentVersion(
            version="v2.0.0",
            image="test:v2",
            deployed_at=datetime.now(UTC),
            status=DeploymentStatus.ACTIVE,
        ))

        with patch.object(manager, '_switch_traffic', new_callable=AsyncMock) as mock_switch:
            mock_switch.return_value = True

            result = await manager.rollback()

            assert result.success is True
            assert result.version == "v1.0.0"

    @pytest.mark.asyncio
    async def test_rollback_no_previous(self) -> None:
        """Rollback with no previous version."""
        manager = DeploymentManager()

        # Only one version
        manager.versions.append(DeploymentVersion(
            version="v1.0.0",
            image="test:v1",
            deployed_at=datetime.now(UTC),
            status=DeploymentStatus.ACTIVE,
        ))

        result = await manager.rollback()

        assert result.success is False
        assert "no previous" in result.error.lower()

    @pytest.mark.asyncio
    async def test_health_check(
        self,
        sample_deployment_config: DeploymentConfig,
    ) -> None:
        """Run health check."""
        manager = DeploymentManager(config=sample_deployment_config)

        with patch.object(manager, '_make_health_request', new_callable=AsyncMock) as mock_req:
            mock_req.return_value = HealthCheckResult(
                healthy=True,
                status_code=200,
                response_time_ms=50.0,
            )

            result = await manager.health_check()

            assert result.healthy is True
            assert result.status_code == 200

    def test_get_deployment_status(self) -> None:
        """Get deployment status."""
        manager = DeploymentManager()

        manager.deployments["deploy-123"] = DeploymentResult(
            deployment_id="deploy-123",
            status=DeploymentStatus.ACTIVE,
            version="v1.0.0",
            active_color="blue",
        )

        status = manager.get_deployment_status("deploy-123")

        assert status is not None
        assert status.status == DeploymentStatus.ACTIVE

    def test_list_deployments(self) -> None:
        """List all deployments."""
        manager = DeploymentManager()

        manager.deployments["deploy-1"] = DeploymentResult(
            deployment_id="deploy-1",
            status=DeploymentStatus.ACTIVE,
            version="v1.0.0",
            active_color="blue",
        )
        manager.deployments["deploy-2"] = DeploymentResult(
            deployment_id="deploy-2",
            status=DeploymentStatus.INACTIVE,
            version="v0.9.0",
            active_color="green",
        )

        deployments = manager.list_deployments()

        assert len(deployments) == 2

    def test_get_active_color(self) -> None:
        """Get active deployment color."""
        manager = DeploymentManager()
        manager.strategy.active_color = "green"

        assert manager.get_active_color() == "green"

    def test_version_history(self) -> None:
        """Get version history."""
        manager = DeploymentManager()

        manager.versions.append(DeploymentVersion(
            version="v1.0.0",
            image="test:v1",
            deployed_at=datetime.now(UTC),
            status=DeploymentStatus.INACTIVE,
        ))
        manager.versions.append(DeploymentVersion(
            version="v2.0.0",
            image="test:v2",
            deployed_at=datetime.now(UTC),
            status=DeploymentStatus.ACTIVE,
        ))

        history = manager.get_version_history()

        assert len(history) == 2
        assert history[0].version == "v1.0.0"
        assert history[1].version == "v2.0.0"

    @pytest.mark.asyncio
    async def test_promote_deployment(
        self,
        sample_deployment_config: DeploymentConfig,
    ) -> None:
        """Promote inactive to active."""
        manager = DeploymentManager(config=sample_deployment_config)

        # Add a deployment to promote
        manager.deployments["deploy-123"] = DeploymentResult(
            deployment_id="deploy-123",
            status=DeploymentStatus.INACTIVE,
            version="v1.0.0",
            active_color="green",
        )

        with patch.object(manager, '_run_health_checks', new_callable=AsyncMock) as mock_health:
            with patch.object(manager, '_switch_traffic', new_callable=AsyncMock) as mock_switch:
                mock_health.return_value = HealthCheckResult(healthy=True)
                mock_switch.return_value = True

                result = await manager.promote("deploy-123")

                assert result is not None
                assert result.status == DeploymentStatus.ACTIVE

    @pytest.mark.asyncio
    async def test_scale_deployment(
        self,
        sample_deployment_config: DeploymentConfig,
    ) -> None:
        """Scale deployment replicas."""
        manager = DeploymentManager(config=sample_deployment_config)

        with patch.object(manager, '_scale_replicas', new_callable=AsyncMock) as mock_scale:
            mock_scale.return_value = True

            result = await manager.scale(replicas=5)

            assert result is True
            mock_scale.assert_called_once_with(5)
