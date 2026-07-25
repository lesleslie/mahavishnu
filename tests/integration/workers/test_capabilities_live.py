from __future__ import annotations

from dataclasses import dataclass, field
import os

import pytest

from mahavishnu.workers.capabilities import (
    WorkerCapabilityState,
    evaluate_worker_capabilities,
)


@dataclass
class _ContainerSettings:
    runtime: str | None = "fake"
    socket_path: str | None = None


@dataclass
class _WorkersSettings:
    enabled: bool = True
    container: _ContainerSettings = field(default_factory=_ContainerSettings)


@dataclass
class _Settings:
    workers: _WorkersSettings = field(default_factory=_WorkersSettings)
    mcp_servers: dict[str, str] = field(
        default_factory=lambda: {"gimp-mcp": "http://mcp.test/gimp"}
    )


@pytest.mark.integration
@pytest.mark.requires_network
def test_live_probe_openclaw_unhealthy() -> None:
    os.environ["OPENCLAW_GATEWAY_URL"] = "http://127.0.0.1:1"
    report = evaluate_worker_capabilities(
        "gateway-openclaw", settings=_Settings(), force_live=True,
    )
    assert report.state is WorkerCapabilityState.READY
    assert any(c.kind == "openclaw_gateway" for c in report.checks)


@pytest.mark.integration
def test_live_probe_container_daemon() -> None:
    report = evaluate_worker_capabilities(
        "container-executor", settings=_Settings(), force_live=True,
    )
    assert report.state in {WorkerCapabilityState.READY, WorkerCapabilityState.AVAILABLE}
