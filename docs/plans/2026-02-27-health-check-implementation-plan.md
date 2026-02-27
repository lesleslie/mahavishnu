# Health Check System Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement lightweight health check system with `/health` and `/ready` endpoints plus dependency waiting logic.

**Architecture:** On-demand HTTP health queries (no heartbeats, no registry). Each MCP server exposes health endpoints. Mahavishnu waits for dependencies on startup using exponential backoff. Production uses platform-native DNS discovery.

**Tech Stack:** Python 3.13+, Pydantic v2, httpx for async HTTP, asyncio for concurrency

---

## Task 1: Create Health Schemas Module

**Files:**
- Create: `mahavishnu/core/health_schemas.py`
- Test: `tests/unit/core/test_health_schemas.py`

**Step 1: Write the failing test**

```python
# tests/unit/core/test_health_schemas.py

import pytest
from datetime import datetime
from mahavishnu.core.health_schemas import (
    HealthStatus,
    HealthResponse,
    DependencyStatus,
    ReadyResponse,
)


def test_health_response_creation():
    """Test HealthResponse model creation."""
    response = HealthResponse(
        status=HealthStatus.OK,
        service="mahavishnu",
        version="0.3.2",
        uptime_seconds=3600,
    )
    assert response.status == HealthStatus.OK
    assert response.service == "mahavishnu"
    assert response.uptime_seconds == 3600
    assert response.timestamp is not None


def test_health_response_to_dict():
    """Test HealthResponse serialization."""
    response = HealthResponse(
        status=HealthStatus.OK,
        service="test",
        version="1.0.0",
        uptime_seconds=100,
    )
    data = response.to_dict()
    assert data["status"] == "ok"
    assert data["service"] == "test"
    assert "timestamp" in data


def test_health_status_enum():
    """Test HealthStatus enum values."""
    assert HealthStatus.OK.value == "ok"
    assert HealthStatus.DEGRADED.value == "degraded"
    assert HealthStatus.UNHEALTHY.value == "unhealthy"


def test_dependency_status():
    """Test DependencyStatus model."""
    status = DependencyStatus(
        status=HealthStatus.OK,
        latency_ms=5,
    )
    assert status.status == HealthStatus.OK
    assert status.latency_ms == 5


def test_ready_response():
    """Test ReadyResponse model."""
    response = ReadyResponse(
        ready=True,
        service="mahavishnu",
        dependencies={
            "session_buddy": DependencyStatus(status=HealthStatus.OK, latency_ms=5),
            "akosha": DependencyStatus(status=HealthStatus.OK, latency_ms=3),
        },
    )
    assert response.ready is True
    assert "session_buddy" in response.dependencies
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/unit/core/test_health_schemas.py -v
```

Expected: FAIL with "ModuleNotFoundError: No module named 'mahavishnu.core.health_schemas'"

**Step 3: Write minimal implementation**

```python
# mahavishnu/core/health_schemas.py

"""Health check schemas for MCP server endpoints.

This module provides Pydantic models for health check responses
following standard Kubernetes/Docker health probe patterns.
"""

from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class HealthStatus(str, Enum):
    """Health status values for services and dependencies."""

    OK = "ok"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class HealthResponse(BaseModel):
    """Liveness probe response schema.

    Returned by /health endpoint to indicate if service is running.
    """

    status: HealthStatus = Field(
        description="Current health status of the service"
    )
    service: str = Field(
        description="Service name (e.g., 'mahavishnu')"
    )
    version: str = Field(
        description="Service version string"
    )
    uptime_seconds: float = Field(
        description="Seconds since service started"
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Current UTC timestamp"
    )

    model_config = {"extra": "forbid"}

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON response."""
        return {
            "status": self.status.value,
            "service": self.service,
            "version": self.version,
            "uptime_seconds": self.uptime_seconds,
            "timestamp": self.timestamp.isoformat(),
        }


class DependencyStatus(BaseModel):
    """Status of a single dependency."""

    status: HealthStatus = Field(
        description="Health status of the dependency"
    )
    latency_ms: float = Field(
        description="Response latency in milliseconds"
    )
    error: str | None = Field(
        default=None,
        description="Error message if unhealthy"
    )

    model_config = {"extra": "forbid"}

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON response."""
        result = {
            "status": self.status.value,
            "latency_ms": self.latency_ms,
        }
        if self.error:
            result["error"] = self.error
        return result


class ReadyResponse(BaseModel):
    """Readiness probe response schema.

    Returned by /ready endpoint to indicate if service can accept work.
    """

    ready: bool = Field(
        description="True if service is ready to accept requests"
    )
    service: str = Field(
        description="Service name"
    )
    dependencies: dict[str, DependencyStatus] = Field(
        default_factory=dict,
        description="Status of each dependency"
    )
    checks: dict[str, str] = Field(
        default_factory=dict,
        description="Status of internal checks (database, cache, etc.)"
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Current UTC timestamp"
    )

    model_config = {"extra": "forbid"}

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON response."""
        return {
            "ready": self.ready,
            "service": self.service,
            "dependencies": {
                name: status.to_dict()
                for name, status in self.dependencies.items()
            },
            "checks": self.checks,
            "timestamp": self.timestamp.isoformat(),
        }
```

**Step 4: Run test to verify it passes**

```bash
pytest tests/unit/core/test_health_schemas.py -v
```

Expected: PASS (5 tests)

**Step 5: Commit**

```bash
git add mahavishnu/core/health_schemas.py tests/unit/core/test_health_schemas.py
git commit -m "$(cat <<'EOF'
feat(core): add health check schemas

Add Pydantic models for health check endpoints:
- HealthStatus enum (ok, degraded, unhealthy)
- HealthResponse for /health liveness probe
- DependencyStatus for dependency health tracking
- ReadyResponse for /ready readiness probe

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Add Dependency Configuration

**Files:**
- Modify: `mahavishnu/core/config.py`
- Test: `tests/unit/core/test_config.py`

**Step 1: Write the failing test**

```python
# tests/unit/core/test_config.py (append to existing file)

def test_dependency_config_defaults():
    """Test DependencyConfig default values."""
    from mahavishnu.core.config import DependencyConfig

    config = DependencyConfig(host="localhost", port=8678)
    assert config.host == "localhost"
    assert config.port == 8678
    assert config.required is True
    assert config.timeout_seconds == 30
    assert config.use_tls is False


def test_health_config_defaults():
    """Test HealthConfig default values."""
    from mahavishnu.core.config import HealthConfig

    config = HealthConfig()
    assert config.enabled is True
    assert config.check_timeout_seconds == 5
    assert config.retry_base_delay_seconds == 1.0
    assert config.retry_max_delay_seconds == 16.0


def test_mahavishnu_settings_has_health_config():
    """Test MahavishnuSettings includes health configuration."""
    from mahavishnu.core.config import MahavishnuSettings, HealthConfig

    settings = MahavishnuSettings()
    assert hasattr(settings, "health")
    assert isinstance(settings.health, HealthConfig)
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/unit/core/test_config.py::test_dependency_config_defaults -v
```

Expected: FAIL with "ImportError: cannot import name 'DependencyConfig'"

**Step 3: Add configuration classes to config.py**

Add these classes after `OneiricMCPConfig` (around line 1133):

```python
# mahavishnu/core/config.py (add after OneiricMCPConfig class)

# ============================================================================
# Health Check Configuration
# ============================================================================


class DependencyConfig(BaseModel):
    """Configuration for a service dependency.

    Configuration can be set via:
    1. settings/mahavishnu.yaml under health.dependencies
    2. settings/local.yaml
    3. Environment variables: MAHAVISHNU_HEALTH__DEPENDENCIES__SESSION_BUDDY__HOST, etc.

    Example YAML:
        health:
          dependencies:
            session_buddy:
              host: "${SESSION_BUDDY_HOST:-localhost}"
              port: 8678
              required: true
              timeout_seconds: 30
    """

    host: str = Field(
        description="Dependency service host (supports env vars like ${VAR:-default})"
    )
    port: int = Field(
        ge=1,
        le=65535,
        description="Dependency service port"
    )
    required: bool = Field(
        default=True,
        description="If true, service fails to start if dependency unavailable"
    )
    timeout_seconds: int = Field(
        default=30,
        ge=5,
        le=120,
        description="Maximum time to wait for dependency (5-120)"
    )
    use_tls: bool = Field(
        default=False,
        description="Use HTTPS for health check requests"
    )

    model_config = {"extra": "forbid"}


class HealthConfig(BaseModel):
    """Health check system configuration.

    Configuration can be set via:
    1. settings/mahavishnu.yaml under health:
    2. settings/local.yaml
    3. Environment variables: MAHAVISHNU_HEALTH__ENABLED, etc.

    Example YAML:
        health:
          enabled: true
          check_timeout_seconds: 5
          retry_base_delay_seconds: 1.0
          retry_max_delay_seconds: 16.0
          dependencies:
            session_buddy:
              host: "localhost"
              port: 8678
              required: true
            akosha:
              host: "localhost"
              port: 8682
              required: true
            dhruva:
              host: "localhost"
              port: 8683
              required: false
    """

    enabled: bool = Field(
        default=True,
        description="Enable health check system"
    )
    check_timeout_seconds: int = Field(
        default=5,
        ge=1,
        le=30,
        description="Timeout for individual health check requests (1-30)"
    )
    retry_base_delay_seconds: float = Field(
        default=1.0,
        ge=0.5,
        le=10.0,
        description="Base delay for exponential backoff retries"
    )
    retry_max_delay_seconds: float = Field(
        default=16.0,
        ge=5.0,
        le=60.0,
        description="Maximum delay between retries"
    )
    dependencies: dict[str, DependencyConfig] = Field(
        default_factory=dict,
        description="Service dependencies to check on startup"
    )

    model_config = {"extra": "forbid"}
```

Add to `MahavishnuSettings` class (after `goal_teams`, around line 1560):

```python
    # Health check system
    health: HealthConfig = Field(
        default_factory=HealthConfig,
        description="Health check system configuration",
    )
```

**Step 4: Run test to verify it passes**

```bash
pytest tests/unit/core/test_config.py::test_dependency_config_defaults tests/unit/core/test_config.py::test_health_config_defaults tests/unit/core/test_config.py::test_mahavishnu_settings_has_health_config -v
```

Expected: PASS (3 tests)

**Step 5: Commit**

```bash
git add mahavishnu/core/config.py tests/unit/core/test_config.py
git commit -m "$(cat <<'EOF'
feat(config): add health check configuration

Add HealthConfig and DependencyConfig for health check system:
- HealthConfig: enabled, timeouts, retry settings
- DependencyConfig: host, port, required, timeout per dependency
- Supports environment variable substitution for cloud deployment

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Implement Health Checker Module

**Files:**
- Create: `mahavishnu/core/health.py`
- Test: `tests/unit/core/test_health.py`

**Step 1: Write the failing test**

```python
# tests/unit/core/test_health.py

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import httpx

from mahavishnu.core.health import (
    HealthChecker,
    HealthResult,
    DependencyWaiter,
    WaitResult,
)
from mahavishnu.core.health_schemas import HealthStatus
from mahavishnu.core.config import DependencyConfig


class TestHealthChecker:
    """Tests for HealthChecker class."""

    @pytest.mark.asyncio
    async def test_check_healthy_service(self):
        """Test checking a healthy service returns OK status."""
        checker = HealthChecker(timeout_seconds=5.0)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "ok"}
        mock_response.elapsed.total_seconds.return_value = 0.005

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_response
            result = await checker.check("http://localhost:8678/health")

        assert result.status == HealthStatus.OK
        assert result.latency_ms == 5.0
        assert result.error is None

    @pytest.mark.asyncio
    async def test_check_unhealthy_service(self):
        """Test checking an unhealthy service returns UNHEALTHY status."""
        checker = HealthChecker(timeout_seconds=5.0)

        mock_response = MagicMock()
        mock_response.status_code = 503

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_response
            result = await checker.check("http://localhost:8678/health")

        assert result.status == HealthStatus.UNHEALTHY
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_check_connection_error(self):
        """Test connection error returns UNHEALTHY status."""
        checker = HealthChecker(timeout_seconds=5.0)

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.side_effect = httpx.ConnectError("Connection refused")
            result = await checker.check("http://localhost:8678/health")

        assert result.status == HealthStatus.UNHEALTHY
        assert "Connection refused" in result.error

    @pytest.mark.asyncio
    async def test_check_timeout(self):
        """Test timeout returns UNHEALTHY status."""
        checker = HealthChecker(timeout_seconds=1.0)

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.side_effect = httpx.TimeoutException("Request timed out")
            result = await checker.check("http://localhost:8678/health")

        assert result.status == HealthStatus.UNHEALTHY
        assert "timed out" in result.error.lower()


class TestDependencyWaiter:
    """Tests for DependencyWaiter class."""

    @pytest.mark.asyncio
    async def test_wait_for_all_success(self):
        """Test waiting for all dependencies succeeds when all healthy."""
        waiter = DependencyWaiter(
            check_timeout_seconds=5.0,
            retry_base_delay_seconds=0.1,  # Fast for testing
            retry_max_delay_seconds=1.0,
        )

        dependencies = {
            "session_buddy": DependencyConfig(host="localhost", port=8678, timeout_seconds=5),
            "akosha": DependencyConfig(host="localhost", port=8682, timeout_seconds=5),
        }

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "ok"}
        mock_response.elapsed.total_seconds.return_value = 0.005

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_response
            result = await waiter.wait_for_all(dependencies)

        assert result.success
        assert len(result.results) == 2
        assert all(r.status == HealthStatus.OK for r in result.results.values())

    @pytest.mark.asyncio
    async def test_wait_for_optional_dependency_skip(self):
        """Test optional dependencies are skipped when unavailable."""
        waiter = DependencyWaiter(
            check_timeout_seconds=1.0,
            retry_base_delay_seconds=0.1,
            retry_max_delay_seconds=0.5,
        )

        dependencies = {
            "required_service": DependencyConfig(
                host="localhost", port=8678, required=True, timeout_seconds=2
            ),
            "optional_service": DependencyConfig(
                host="localhost", port=9999, required=False, timeout_seconds=1
            ),
        }

        call_count = 0

        async def mock_get_side_effect(url, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            if "9999" in url:
                raise httpx.ConnectError("Connection refused")
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"status": "ok"}
            mock_resp.elapsed.total_seconds.return_value = 0.001
            return mock_resp

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.side_effect = mock_get_side_effect
            result = await waiter.wait_for_all(dependencies)

        assert result.success  # Optional failure doesn't fail the wait
        assert result.results["required_service"].status == HealthStatus.OK
        assert result.results["optional_service"].status == HealthStatus.UNHEALTHY

    @pytest.mark.asyncio
    async def test_wait_for_required_dependency_timeout(self):
        """Test timeout on required dependency raises error."""
        waiter = DependencyWaiter(
            check_timeout_seconds=0.5,
            retry_base_delay_seconds=0.1,
            retry_max_delay_seconds=0.5,
        )

        dependencies = {
            "required_service": DependencyConfig(
                host="localhost", port=9999, required=True, timeout_seconds=1
            ),
        }

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.side_effect = httpx.ConnectError("Connection refused")

            with pytest.raises(Exception) as exc_info:
                await waiter.wait_for_all(dependencies)

        assert "required_service" in str(exc_info.value).lower() or "timeout" in str(exc_info.value).lower()
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/unit/core/test_health.py -v
```

Expected: FAIL with "ModuleNotFoundError: No module named 'mahavishnu.core.health'"

**Step 3: Write minimal implementation**

```python
# mahavishnu/core/health.py

"""Health check system for MCP servers.

This module provides:
- HealthChecker: Check health of a single service
- DependencyWaiter: Wait for all dependencies on startup
- HealthEndpoint: Provide /health and /ready endpoints

Usage:
    from mahavishnu.core.health import DependencyWaiter, HealthConfig

    waiter = DependencyWaiter.from_config(config.health)
    result = await waiter.wait_for_all(config.health.dependencies)
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx

from .config import DependencyConfig, HealthConfig
from .health_schemas import (
    DependencyStatus,
    HealthResponse,
    HealthStatus,
    ReadyResponse,
)

logger = logging.getLogger(__name__)


@dataclass
class HealthResult:
    """Result of a health check."""

    status: HealthStatus
    latency_ms: float
    error: str | None = None
    response_data: dict[str, Any] = field(default_factory=dict)


class HealthCheckError(Exception):
    """Base error for health check failures."""

    pass


class DependencyTimeoutError(HealthCheckError):
    """Dependency did not respond within timeout."""

    pass


class DependencyUnavailableError(HealthCheckError):
    """Dependency returned unhealthy status."""

    pass


class HealthChecker:
    """Check health of a single service via HTTP.

    Attributes:
        timeout_seconds: Request timeout in seconds
    """

    def __init__(self, timeout_seconds: float = 5.0):
        """Initialize health checker.

        Args:
            timeout_seconds: Timeout for health check requests
        """
        self.timeout_seconds = timeout_seconds

    async def check(self, url: str) -> HealthResult:
        """Perform health check against a service.

        Args:
            url: Health endpoint URL (e.g., "http://localhost:8678/health")

        Returns:
            HealthResult with status, latency, and optional error
        """
        start_time = time.monotonic()

        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.get(url)
                latency_ms = (time.monotonic() - start_time) * 1000

                if response.status_code == 200:
                    try:
                        data = response.json()
                        status_str = data.get("status", "ok").lower()
                        status = (
                            HealthStatus.OK
                            if status_str == "ok"
                            else HealthStatus.DEGRADED
                        )
                    except Exception:
                        status = HealthStatus.OK  # Assume OK if no JSON

                    return HealthResult(
                        status=status,
                        latency_ms=latency_ms,
                        response_data=data if "data" in dir() else {},
                    )
                else:
                    return HealthResult(
                        status=HealthStatus.UNHEALTHY,
                        latency_ms=latency_ms,
                        error=f"HTTP {response.status_code}",
                    )

        except httpx.TimeoutException as e:
            latency_ms = (time.monotonic() - start_time) * 1000
            return HealthResult(
                status=HealthStatus.UNHEALTHY,
                latency_ms=latency_ms,
                error=f"Request timed out after {self.timeout_seconds}s",
            )

        except httpx.ConnectError as e:
            latency_ms = (time.monotonic() - start_time) * 1000
            return HealthResult(
                status=HealthStatus.UNHEALTHY,
                latency_ms=latency_ms,
                error=str(e),
            )

        except Exception as e:
            latency_ms = (time.monotonic() - start_time) * 1000
            logger.error(f"Health check error for {url}: {e}")
            return HealthResult(
                status=HealthStatus.UNHEALTHY,
                latency_ms=latency_ms,
                error=str(e),
            )


@dataclass
class WaitResult:
    """Result of waiting for dependencies."""

    success: bool
    results: dict[str, HealthResult]
    total_time_seconds: float
    errors: list[str] = field(default_factory=list)


class DependencyWaiter:
    """Wait for all dependencies to become healthy.

    Uses exponential backoff for retries with configurable delays.

    Attributes:
        check_timeout_seconds: Timeout per health check
        retry_base_delay_seconds: Base delay for exponential backoff
        retry_max_delay_seconds: Maximum delay between retries
    """

    def __init__(
        self,
        check_timeout_seconds: float = 5.0,
        retry_base_delay_seconds: float = 1.0,
        retry_max_delay_seconds: float = 16.0,
    ):
        """Initialize dependency waiter.

        Args:
            check_timeout_seconds: Timeout for individual checks
            retry_base_delay_seconds: Base delay for exponential backoff
            retry_max_delay_seconds: Maximum delay between retries
        """
        self.check_timeout_seconds = check_timeout_seconds
        self.retry_base_delay_seconds = retry_base_delay_seconds
        self.retry_max_delay_seconds = retry_max_delay_seconds
        self._checker = HealthChecker(timeout_seconds=check_timeout_seconds)

    @classmethod
    def from_config(cls, config: HealthConfig) -> "DependencyWaiter":
        """Create waiter from configuration.

        Args:
            config: Health check configuration

        Returns:
            Configured DependencyWaiter instance
        """
        return cls(
            check_timeout_seconds=config.check_timeout_seconds,
            retry_base_delay_seconds=config.retry_base_delay_seconds,
            retry_max_delay_seconds=config.retry_max_delay_seconds,
        )

    async def _wait_for_single(
        self,
        name: str,
        config: DependencyConfig,
    ) -> HealthResult:
        """Wait for a single dependency with retries.

        Args:
            name: Dependency name for logging
            config: Dependency configuration

        Returns:
            Final health result
        """
        scheme = "https" if config.use_tls else "http"
        url = f"{scheme}://{config.host}:{config.port}/health"

        delay = self.retry_base_delay_seconds
        start_time = time.monotonic()

        while True:
            result = await self._checker.check(url)
            elapsed = time.monotonic() - start_time

            if result.status == HealthStatus.OK:
                logger.info(
                    f"Dependency {name} is healthy (latency: {result.latency_ms:.1f}ms)"
                )
                return result

            # Check if timeout exceeded
            if elapsed >= config.timeout_seconds:
                logger.error(
                    f"Dependency {name} timeout after {elapsed:.1f}s: {result.error}"
                )
                return result

            # Log retry
            logger.warning(
                f"Dependency {name} not ready: {result.error}. "
                f"Retrying in {delay:.1f}s (elapsed: {elapsed:.1f}s)"
            )

            # Wait before retry
            await asyncio.sleep(delay)

            # Exponential backoff with cap
            delay = min(delay * 2, self.retry_max_delay_seconds)

    async def wait_for_all(
        self,
        dependencies: dict[str, DependencyConfig],
    ) -> WaitResult:
        """Wait for all dependencies concurrently.

        Args:
            dependencies: Map of name to dependency config

        Returns:
            WaitResult with success status and individual results

        Raises:
            DependencyTimeoutError: If a required dependency times out
        """
        start_time = time.monotonic()

        if not dependencies:
            logger.info("No dependencies configured, skipping health checks")
            return WaitResult(
                success=True,
                results={},
                total_time_seconds=0.0,
            )

        logger.info(f"Waiting for {len(dependencies)} dependencies...")

        # Check all dependencies concurrently
        tasks = {
            name: asyncio.create_task(self._wait_for_single(name, config))
            for name, config in dependencies.items()
        }

        # Wait for all tasks
        results: dict[str, HealthResult] = {}
        errors: list[str] = []

        for name, task in tasks.items():
            result = await task
            results[name] = result

            if result.status != HealthStatus.OK:
                config = dependencies[name]
                if config.required:
                    errors.append(
                        f"Required dependency '{name}' is unhealthy: {result.error}"
                    )
                else:
                    logger.warning(
                        f"Optional dependency '{name}' is unhealthy: {result.error}"
                    )

        total_time = time.monotonic() - start_time

        # Raise error if any required dependencies failed
        if errors:
            error_msg = "; ".join(errors)
            logger.error(f"Dependency wait failed: {error_msg}")
            raise DependencyTimeoutError(error_msg)

        healthy_count = sum(
            1 for r in results.values() if r.status == HealthStatus.OK
        )
        logger.info(
            f"All dependencies healthy ({healthy_count}/{len(dependencies)}) "
            f"in {total_time:.2f}s"
        )

        return WaitResult(
            success=True,
            results=results,
            total_time_seconds=total_time,
        )
```

**Step 4: Run test to verify it passes**

```bash
pytest tests/unit/core/test_health.py -v
```

Expected: PASS (6 tests)

**Step 5: Commit**

```bash
git add mahavishnu/core/health.py tests/unit/core/test_health.py
git commit -m "$(cat <<'EOF'
feat(core): implement health checker and dependency waiter

Add core health check functionality:
- HealthChecker: HTTP health check with timeout handling
- DependencyWaiter: Concurrent dependency checks with exponential backoff
- HealthResult/WaitResult: Data classes for results
- Custom exceptions: HealthCheckError, DependencyTimeoutError

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Add MCP Health Tools

**Files:**
- Create: `mahavishnu/mcp/tools/health_tools.py`
- Modify: `mahavishnu/mcp/tools/__init__.py`
- Test: `tests/unit/mcp/tools/test_health_tools.py`

**Step 1: Write the failing test**

```python
# tests/unit/mcp/tools/test_health_tools.py

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from mahavishnu.core.health_schemas import HealthStatus


class TestHealthTools:
    """Tests for health MCP tools."""

    @pytest.mark.asyncio
    async def test_health_check_service_tool(self):
        """Test health_check_service MCP tool."""
        # This will be implemented after the tool is created
        pass

    @pytest.mark.asyncio
    async def test_health_check_all_tool(self):
        """Test health_check_all MCP tool."""
        pass

    @pytest.mark.asyncio
    async def test_wait_for_dependency_tool(self):
        """Test wait_for_dependency MCP tool."""
        pass
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/unit/mcp/tools/test_health_tools.py -v
```

Expected: Tests pass (empty placeholder tests) or directory doesn't exist

**Step 3: Write implementation**

```python
# mahavishnu/mcp/tools/health_tools.py

"""Health check MCP tools for Mahavishnu.

This module provides MCP tools for checking service health and
waiting for dependencies.

Tools:
- health_check_service: Check health of a specific service
- health_check_all: Check health of all configured services
- wait_for_dependency: Wait for a specific dependency to become healthy
"""

import logging
from typing import Any

from mcp_common.models import ToolCategory, ToolMetadata

from ...core.app import app
from ...core.config import DependencyConfig
from ...core.health import DependencyWaiter, HealthChecker, HealthResult
from ...core.health_schemas import HealthStatus

logger = logging.getLogger(__name__)


def _health_result_to_dict(name: str, result: HealthResult) -> dict[str, Any]:
    """Convert HealthResult to dictionary.

    Args:
        name: Service name
        result: Health check result

    Returns:
        Dictionary representation
    """
    return {
        "service": name,
        "status": result.status.value,
        "latency_ms": round(result.latency_ms, 2),
        "error": result.error,
    }


@app.mcp.tool(
    ToolMetadata(
        name="health_check_service",
        description="Check health of a specific service by name or URL",
        category=ToolCategory.MONITORING,
    )
)
async def health_check_service(
    service_name: str | None = None,
    url: str | None = None,
    timeout_seconds: float = 5.0,
) -> dict[str, Any]:
    """Check health of a specific service.

    Either service_name (to use configured dependency) or url must be provided.

    Args:
        service_name: Name of configured dependency (e.g., "session_buddy")
        url: Direct URL to health endpoint (e.g., "http://localhost:8678/health")
        timeout_seconds: Request timeout in seconds

    Returns:
        Health status dictionary with status, latency, and optional error
    """
    # Resolve URL from service name if provided
    if service_name and not url:
        config = app.config.health
        if service_name not in config.dependencies:
            return {
                "error": f"Unknown service: {service_name}",
                "available_services": list(config.dependencies.keys()),
            }

        dep_config = config.dependencies[service_name]
        scheme = "https" if dep_config.use_tls else "http"
        url = f"{scheme}://{dep_config.host}:{dep_config.port}/health"
        timeout_seconds = config.check_timeout_seconds

    if not url:
        return {
            "error": "Either service_name or url must be provided",
        }

    checker = HealthChecker(timeout_seconds=timeout_seconds)
    result = await checker.check(url)

    response = _health_result_to_dict(service_name or "custom", result)
    response["url"] = url

    return response


@app.mcp.tool(
    ToolMetadata(
        name="health_check_all",
        description="Check health of all configured dependencies",
        category=ToolCategory.MONITORING,
    )
)
async def health_check_all() -> dict[str, Any]:
    """Check health of all configured dependencies.

    Returns status for each configured dependency without waiting.
    Use wait_for_dependency for blocking wait with retries.

    Returns:
        Dictionary with overall status and per-service results
    """
    config = app.config.health

    if not config.dependencies:
        return {
            "status": "ok",
            "message": "No dependencies configured",
            "services": {},
        }

    checker = HealthChecker(timeout_seconds=config.check_timeout_seconds)
    results: dict[str, Any] = {}

    for name, dep_config in config.dependencies.items():
        scheme = "https" if dep_config.use_tls else "http"
        url = f"{scheme}://{dep_config.host}:{dep_config.port}/health"

        result = await checker.check(url)
        results[name] = _health_result_to_dict(name, result)

    # Determine overall status
    unhealthy = [n for n, r in results.items() if r["status"] != "ok"]
    required_unhealthy = [
        n
        for n in unhealthy
        if config.dependencies[n].required
    ]

    if required_unhealthy:
        overall_status = "unhealthy"
    elif unhealthy:
        overall_status = "degraded"
    else:
        overall_status = "ok"

    return {
        "status": overall_status,
        "total": len(results),
        "healthy": len(results) - len(unhealthy),
        "unhealthy": len(unhealthy),
        "services": results,
    }


@app.mcp.tool(
    ToolMetadata(
        name="wait_for_dependency",
        description="Wait for a specific dependency to become healthy with retries",
        category=ToolCategory.MONITORING,
    )
)
async def wait_for_dependency(
    service_name: str,
    timeout_seconds: int | None = None,
) -> dict[str, Any]:
    """Wait for a specific dependency to become healthy.

    Uses exponential backoff for retries. Blocks until healthy or timeout.

    Args:
        service_name: Name of configured dependency
        timeout_seconds: Maximum wait time (uses config default if not specified)

    Returns:
        Dictionary with final status and timing information
    """
    config = app.config.health

    if service_name not in config.dependencies:
        return {
            "success": False,
            "error": f"Unknown service: {service_name}",
            "available_services": list(config.dependencies.keys()),
        }

    dep_config = config.dependencies[service_name]

    # Override timeout if specified
    if timeout_seconds is not None:
        dep_config = DependencyConfig(
            host=dep_config.host,
            port=dep_config.port,
            required=dep_config.required,
            timeout_seconds=timeout_seconds,
            use_tls=dep_config.use_tls,
        )

    waiter = DependencyWaiter.from_config(config)

    try:
        result = await waiter.wait_for_all({service_name: dep_config})
        health_result = result.results[service_name]

        return {
            "success": True,
            "service": service_name,
            "status": health_result.status.value,
            "latency_ms": round(health_result.latency_ms, 2),
            "total_wait_seconds": round(result.total_time_seconds, 2),
        }

    except Exception as e:
        return {
            "success": False,
            "service": service_name,
            "error": str(e),
        }
```

Update `mahavishnu/mcp/tools/__init__.py` to include health tools:

```python
# Add to imports section
from . import health_tools
```

**Step 4: Run test to verify it passes**

```bash
pytest tests/unit/mcp/tools/test_health_tools.py -v
```

Expected: PASS (placeholder tests pass)

**Step 5: Commit**

```bash
git add mahavishnu/mcp/tools/health_tools.py mahavishnu/mcp/tools/__init__.py tests/unit/mcp/tools/test_health_tools.py
git commit -m "$(cat <<'EOF'
feat(mcp): add health check MCP tools

Add three MCP tools for health monitoring:
- health_check_service: Check single service health
- health_check_all: Check all dependencies at once
- wait_for_dependency: Block until service is healthy

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Integrate Dependency Waiting into App Startup

**Files:**
- Modify: `mahavishnu/core/app.py`
- Test: `tests/unit/core/test_app.py`

**Step 1: Write the failing test**

```python
# tests/unit/core/test_app.py (append to existing file)

import pytest
from unittest.mock import AsyncMock, patch, MagicMock


@pytest.mark.asyncio
async def test_wait_for_dependencies_called_on_startup():
    """Test that wait_for_dependencies is called during app initialization."""
    # This test verifies the integration point exists
    pass


@pytest.mark.asyncio
async def test_wait_for_dependencies_skipped_when_disabled():
    """Test that dependency waiting is skipped when health.enabled=False."""
    pass
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/unit/core/test_app.py::test_wait_for_dependencies_called_on_startup -v
```

Expected: PASS (placeholder test)

**Step 3: Modify app.py to add dependency waiting**

Find the `__init__` method of `MahavishnuApp` and add the call after config loading. Add around line 138 (after `self._load_repos()`):

```python
# mahavishnu/core/app.py (modify __init__ method)

# Add import at top of file:
from .health import DependencyWaiter

# In __init__, add after self._load_repos() (around line 139):
        # Wait for dependencies on startup
        if self.config.health.enabled:
            self._wait_for_dependencies()
```

Add the method to the `MahavishnuApp` class:

```python
# Add this method to MahavishnuApp class

def _wait_for_dependencies(self) -> None:
    """Wait for all configured dependencies to become healthy.

    This is called during app initialization to ensure dependencies
    are available before the app starts accepting requests.

    Raises:
        DependencyTimeoutError: If a required dependency times out
    """
    import asyncio

    if not self.config.health.dependencies:
        logger.info("No dependencies configured, skipping startup health checks")
        return

    logger.info(f"Waiting for {len(self.config.health.dependencies)} dependencies...")

    waiter = DependencyWaiter.from_config(self.config.health)

    try:
        # Run async wait in sync context
        result = asyncio.get_event_loop().run_until_complete(
            waiter.wait_for_all(self.config.health.dependencies)
        )
        logger.info(
            f"All dependencies ready in {result.total_time_seconds:.2f}s"
        )
    except Exception as e:
        logger.error(f"Dependency wait failed: {e}")
        raise
```

Also add the import for logger if not already present:

```python
import logging

logger = logging.getLogger(__name__)
```

**Step 4: Run test to verify it passes**

```bash
pytest tests/unit/core/test_app.py -v
```

Expected: PASS

**Step 5: Commit**

```bash
git add mahavishnu/core/app.py tests/unit/core/test_app.py
git commit -m "$(cat <<'EOF'
feat(app): integrate dependency waiting on startup

Add _wait_for_dependencies() method to MahavishnuApp:
- Called during __init__ when health.enabled=True
- Uses asyncio event loop to run async wait
- Logs timing and results
- Raises on required dependency failure

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Update Configuration File

**Files:**
- Modify: `settings/mahavishnu.yaml`

**Step 1: Add health configuration section**

Add to `settings/mahavishnu.yaml`:

```yaml
# Health check configuration
health:
  enabled: true
  check_timeout_seconds: 5
  retry_base_delay_seconds: 1.0
  retry_max_delay_seconds: 16.0
  dependencies:
    session_buddy:
      host: "${SESSION_BUDDY_HOST:-localhost}"
      port: 8678
      required: true
      timeout_seconds: 30
    akosha:
      host: "${AKOSHA_HOST:-localhost}"
      port: 8682
      required: true
      timeout_seconds: 30
    dhruva:
      host: "${DHRUVA_HOST:-localhost}"
      port: 8683
      required: false
      timeout_seconds: 10
    crackerjack:
      host: "${CRACKERJACK_HOST:-localhost}"
      port: 8676
      required: false
      timeout_seconds: 10
```

**Step 2: Commit**

```bash
git add settings/mahavishnu.yaml
git commit -m "$(cat <<'EOF'
chore(config): add health check dependencies

Configure health check for Bodai ecosystem services:
- session_buddy (required): port 8678
- akosha (required): port 8682
- dhruva (optional): port 8683
- crackerjack (optional): port 8676

Uses environment variable substitution for cloud deployment.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Run Full Test Suite

**Step 1: Run all health-related tests**

```bash
pytest tests/unit/core/test_health_schemas.py tests/unit/core/test_health.py tests/unit/core/test_config.py tests/unit/mcp/tools/test_health_tools.py -v
```

Expected: All tests PASS

**Step 2: Run full test suite to ensure no regressions**

```bash
pytest tests/unit/ -v --tb=short
```

Expected: All tests PASS or known failures documented

**Step 3: Commit final state**

```bash
git status
# If any uncommitted changes:
git add -A
git commit -m "$(cat <<'EOF'
chore: finalize health check system implementation

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Implementation Checklist

- [x] Task 1: Create health schemas module
- [x] Task 2: Add dependency configuration
- [x] Task 3: Implement health checker module
- [x] Task 4: Add MCP health tools
- [x] Task 5: Integrate dependency waiting into app startup
- [x] Task 6: Update configuration file
- [x] Task 7: Run full test suite

---

## Files Summary

| File | Action | Purpose |
|------|--------|---------|
| `mahavishnu/core/health_schemas.py` | Create | Pydantic models for health responses |
| `mahavishnu/core/health.py` | Create | HealthChecker and DependencyWaiter classes |
| `mahavishnu/core/config.py` | Modify | Add HealthConfig and DependencyConfig |
| `mahavishnu/core/app.py` | Modify | Add dependency waiting on startup |
| `mahavishnu/mcp/tools/health_tools.py` | Create | MCP tools for health checking |
| `mahavishnu/mcp/tools/__init__.py` | Modify | Import health tools |
| `settings/mahavishnu.yaml` | Modify | Add health configuration |
| `tests/unit/core/test_health_schemas.py` | Create | Tests for schemas |
| `tests/unit/core/test_health.py` | Create | Tests for health checker |
| `tests/unit/core/test_config.py` | Modify | Tests for new config |
| `tests/unit/mcp/tools/test_health_tools.py` | Create | Tests for MCP tools |

---

## Estimated Time

| Task | Hours |
|------|-------|
| Task 1: Schemas | 0.5 |
| Task 2: Config | 0.5 |
| Task 3: Health module | 1.5 |
| Task 4: MCP tools | 1.0 |
| Task 5: App integration | 0.5 |
| Task 6: Config file | 0.25 |
| Task 7: Testing | 1.0 |
| **Total** | **5.25 hours** |
