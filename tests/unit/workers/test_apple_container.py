"""Unit tests for AppleContainerWorker.

All tests are mock-only: the ``container`` CLI is faked at the
``_run_cli`` seam and the platform gate is monkeypatched, so the suite
runs on Intel Macs, Linux CI, and anywhere else without Apple silicon.
"""

from __future__ import annotations

import json
import platform
import shutil
import sys
from typing import Any

import pytest

from mahavishnu.core.errors import AppleContainerUnsupported, ContainerDaemonUnavailable
from mahavishnu.core.status import WorkerStatus
from mahavishnu.workers import apple_container
from mahavishnu.workers.apple_container import (
    AppleContainerWorker,
    _inspect_reports_running,
    is_apple_container_supported,
    unsupported_reason,
)

pytestmark = pytest.mark.unit


class FakeCLI:
    """Recording fake for the ``_run_cli`` seam."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.responses: list[tuple[int, str, str]] = []

    def queue(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.responses.append((returncode, stdout, stderr))

    async def __call__(
        self, *argv: str, timeout: float | None = None
    ) -> tuple[int, str, str]:
        self.calls.append(list(argv))
        if self.responses:
            return self.responses.pop(0)
        return (0, "", "")


@pytest.fixture
def supported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(apple_container, "is_apple_container_supported", lambda: True)


@pytest.fixture
def cli(monkeypatch: pytest.MonkeyPatch) -> FakeCLI:
    fake = FakeCLI()
    monkeypatch.setattr(apple_container, "_run_cli", fake)
    return fake


async def started_worker(cli: FakeCLI, **kwargs: Any) -> AppleContainerWorker:
    """Build and start a worker with probe + run responses queued."""
    worker = AppleContainerWorker(**kwargs)
    cli.queue(0, "services healthy", "")  # system status probe
    cli.queue(0, "abc123\n", "")  # container run -> id
    await worker.start()
    return worker


class TestSupportGate:
    def _patch_host(
        self,
        monkeypatch: pytest.MonkeyPatch,
        *,
        host: str,
        machine: str,
        binary: str | None,
    ) -> None:
        monkeypatch.setattr(sys, "platform", host)
        monkeypatch.setattr(platform, "machine", lambda: machine)
        monkeypatch.setattr(shutil, "which", lambda name: binary)

    def test_apple_silicon_with_binary_is_supported(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._patch_host(
            monkeypatch, host="darwin", machine="arm64", binary="/usr/local/bin/container"
        )
        assert is_apple_container_supported() is True

    def test_intel_mac_is_unsupported(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._patch_host(
            monkeypatch, host="darwin", machine="x86_64", binary="/usr/local/bin/container"
        )
        assert is_apple_container_supported() is False
        assert "x86_64" in unsupported_reason()

    def test_linux_host_is_unsupported(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._patch_host(monkeypatch, host="linux", machine="x86_64", binary=None)
        assert is_apple_container_supported() is False
        assert "macOS" in unsupported_reason()

    def test_missing_binary_is_unsupported(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._patch_host(monkeypatch, host="darwin", machine="arm64", binary=None)
        assert is_apple_container_supported() is False
        assert "PATH" in unsupported_reason()

    def test_init_raises_typed_error_for_tier_fallback(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(apple_container, "is_apple_container_supported", lambda: False)
        with pytest.raises(AppleContainerUnsupported):
            AppleContainerWorker()


class TestLifecycle:
    async def test_start_probes_then_launches_detached_microvm(
        self, supported: None, cli: FakeCLI
    ) -> None:
        worker = await started_worker(cli, image="python:3.13-slim")

        assert cli.calls[0] == ["system", "status"]
        assert cli.calls[1] == [
            "run",
            "--detach",
            "--rm",
            "python:3.13-slim",
            "sleep",
            "infinity",
        ]
        assert worker.container_id == "abc123"
        assert await worker.status() is not WorkerStatus.PENDING

    async def test_start_passes_cpu_and_memory_limits(
        self, supported: None, cli: FakeCLI
    ) -> None:
        await started_worker(cli, cpus=4, memory="8g")

        run_argv = cli.calls[1]
        assert run_argv[3:5] == ["--cpus", "4"]
        assert run_argv[5:7] == ["--memory", "8g"]

    async def test_start_raises_daemon_unavailable_when_probe_fails(
        self, supported: None, cli: FakeCLI
    ) -> None:
        worker = AppleContainerWorker()
        cli.queue(1, "", "XPC connection failure")

        with pytest.raises(ContainerDaemonUnavailable):
            await worker.start()

    async def test_start_raises_runtime_error_when_launch_fails(
        self, supported: None, cli: FakeCLI
    ) -> None:
        worker = AppleContainerWorker()
        cli.queue(0, "ok", "")
        cli.queue(1, "", "image not found")

        with pytest.raises(RuntimeError, match="image not found"):
            await worker.start()

    async def test_stop_invokes_cli_and_clears_state(
        self, supported: None, cli: FakeCLI
    ) -> None:
        worker = await started_worker(cli)
        cli.queue(0, "", "")

        await worker.stop()

        assert cli.calls[-1] == ["stop", "abc123"]
        assert worker.container_id is None
        assert await worker.status() is WorkerStatus.PENDING


class TestExecute:
    async def test_execute_returns_completed_result(
        self, supported: None, cli: FakeCLI
    ) -> None:
        worker = await started_worker(cli)
        cli.queue(0, "hello\n", "")

        result = await worker.execute({"command": "echo hello"})

        assert result.status is WorkerStatus.COMPLETED
        assert result.output == "hello\n"
        assert result.exit_code == 0
        assert result.metadata["runtime"] == "apple-container"
        exec_argv = cli.calls[-1]
        assert exec_argv[:2] == ["exec", "abc123"]
        assert exec_argv[2:4] == ["sh", "-c"]

    async def test_execute_maps_nonzero_exit_to_failed(
        self, supported: None, cli: FakeCLI
    ) -> None:
        worker = await started_worker(cli)
        cli.queue(2, "", "boom")

        result = await worker.execute({"command": "python broken.py"})

        assert result.status is WorkerStatus.FAILED
        assert result.exit_code == 2
        assert result.error == "boom"

    async def test_execute_rejects_disallowed_command(
        self, supported: None, cli: FakeCLI
    ) -> None:
        worker = await started_worker(cli)

        with pytest.raises(ValueError, match="not in the allowed list"):
            await worker.execute({"command": "sudo reboot"})

    async def test_execute_rejects_dangerous_pattern(
        self, supported: None, cli: FakeCLI
    ) -> None:
        worker = await started_worker(cli)

        with pytest.raises(ValueError, match="dangerous pattern"):
            await worker.execute({"command": "echo hi && rm -rf /"})

    async def test_execute_requires_started_worker(self, supported: None) -> None:
        worker = AppleContainerWorker()

        with pytest.raises(RuntimeError, match="not started"):
            await worker.execute({"command": "echo hi"})

    async def test_execute_stores_result_in_session_buddy(
        self, supported: None, cli: FakeCLI
    ) -> None:
        class FakeSessionBuddy:
            def __init__(self) -> None:
                self.tool_calls: list[tuple[str, dict[str, Any]]] = []

            async def call_tool(self, name: str, arguments: dict[str, Any]) -> None:
                self.tool_calls.append((name, arguments))

        buddy = FakeSessionBuddy()
        worker = await started_worker(cli, session_buddy_client=buddy)
        cli.queue(0, "42\n", "")

        await worker.execute({"command": "python -c 'print(42)'"})

        assert len(buddy.tool_calls) == 1
        name, arguments = buddy.tool_calls[0]
        assert name == "store_memory"
        stored = json.loads(arguments["content"])
        assert stored["exit_code"] == 0
        assert arguments["metadata"]["runtime"] == "apple-container"


class TestStatusInspection:
    async def test_status_running_when_inspect_reports_running(
        self, supported: None, cli: FakeCLI
    ) -> None:
        worker = await started_worker(cli)
        cli.queue(0, json.dumps([{"status": "running"}]), "")

        assert await worker.status() is WorkerStatus.RUNNING

    async def test_status_completed_when_inspect_reports_stopped(
        self, supported: None, cli: FakeCLI
    ) -> None:
        worker = await started_worker(cli)
        cli.queue(0, json.dumps([{"status": "stopped"}]), "")

        assert await worker.status() is WorkerStatus.COMPLETED

    @pytest.mark.parametrize(
        ("payload", "expected"),
        [
            (json.dumps([{"status": "running"}]), True),
            (json.dumps({"status": "Running"}), True),
            (json.dumps([{"state": {"status": "running"}}]), True),
            (json.dumps([{"status": "stopped"}]), False),
            (json.dumps([]), False),
            ("not json", False),
            (json.dumps("running"), False),
        ],
    )
    def test_inspect_parser_tolerates_schema_variants(
        self, payload: str, expected: bool
    ) -> None:
        assert _inspect_reports_running(payload) is expected
