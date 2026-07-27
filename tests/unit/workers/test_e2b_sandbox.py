"""Unit tests for E2BSandboxWorker.

Mock-only: the e2b SDK is faked at the module attribute, so tests run
without the optional ``e2b`` dependency installed and without network.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from mahavishnu.core.status import WorkerStatus
from mahavishnu.workers import e2b_sandbox
from mahavishnu.workers.e2b_sandbox import E2BSandboxWorker

pytestmark = pytest.mark.unit


class FakeCommandResult:
    def __init__(self, exit_code: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr


class FakeCommandExit(Exception):
    """Mimics e2b CommandExitException: carries exit_code/stdout/stderr."""

    def __init__(self, exit_code: int, stdout: str = "", stderr: str = "") -> None:
        super().__init__(f"exit {exit_code}")
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr


class FakeCommands:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.responses: list[FakeCommandResult | Exception] = []

    async def run(self, command: str) -> FakeCommandResult:
        self.calls.append(command)
        if not self.responses:
            return FakeCommandResult()
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class FakeSandbox:
    def __init__(self) -> None:
        self.sandbox_id = "sbx_123"
        self.commands = FakeCommands()
        self.killed = False

    async def kill(self) -> None:
        self.killed = True

    async def is_running(self) -> bool:
        return not self.killed


class FakeAsyncSandbox:
    """Stands in for e2b.AsyncSandbox."""

    created_kwargs: dict[str, Any] = {}
    instance: FakeSandbox | None = None
    create_error: Exception | None = None

    @classmethod
    async def create(cls, **kwargs: Any) -> FakeSandbox:
        cls.created_kwargs = kwargs
        if cls.create_error is not None:
            raise cls.create_error
        cls.instance = FakeSandbox()
        return cls.instance


@pytest.fixture
def sdk(monkeypatch: pytest.MonkeyPatch) -> type[FakeAsyncSandbox]:
    FakeAsyncSandbox.created_kwargs = {}
    FakeAsyncSandbox.instance = None
    FakeAsyncSandbox.create_error = None
    monkeypatch.setattr(e2b_sandbox, "AsyncSandbox", FakeAsyncSandbox)
    return FakeAsyncSandbox


async def started_worker(**kwargs: Any) -> E2BSandboxWorker:
    worker = E2BSandboxWorker(**kwargs)
    await worker.start()
    return worker


class TestStart:
    async def test_start_creates_sandbox_with_template_and_timeout(
        self, sdk: type[FakeAsyncSandbox]
    ) -> None:
        worker = await started_worker(template="mahavishnu-base", timeout=120)

        assert worker.sandbox_id == "sbx_123"
        assert sdk.created_kwargs == {"template": "mahavishnu-base", "timeout": 120}
        assert await worker.status() is WorkerStatus.RUNNING

    async def test_start_passes_explicit_api_key(self, sdk: type[FakeAsyncSandbox]) -> None:
        await started_worker(api_key="e2b_test_key")

        assert sdk.created_kwargs["api_key"] == "e2b_test_key"

    async def test_start_without_sdk_raises_install_hint(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(e2b_sandbox, "AsyncSandbox", None)
        worker = E2BSandboxWorker()

        with pytest.raises(RuntimeError, match="uv sync --group sandbox"):
            await worker.start()

    async def test_start_wraps_sdk_failure(self, sdk: type[FakeAsyncSandbox]) -> None:
        sdk.create_error = ConnectionError("api unreachable")
        worker = E2BSandboxWorker()

        with pytest.raises(RuntimeError, match="failed to start"):
            await worker.start()

    def test_construction_without_sdk_is_cheap(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Tier fallback must be able to construct the worker even where
        # the SDK is not installed; only start() requires it.
        monkeypatch.setattr(e2b_sandbox, "AsyncSandbox", None)
        worker = E2BSandboxWorker()
        assert worker.worker_type == "e2b-sandbox"


class TestExecute:
    async def test_execute_returns_completed_result(
        self, sdk: type[FakeAsyncSandbox]
    ) -> None:
        worker = await started_worker()
        assert sdk.instance is not None
        sdk.instance.commands.responses.append(FakeCommandResult(0, "hello\n", ""))

        result = await worker.execute({"command": "echo hello"})

        assert result.status is WorkerStatus.COMPLETED
        assert result.output == "hello\n"
        assert result.exit_code == 0
        assert result.metadata["runtime"] == "e2b"
        assert sdk.instance.commands.calls[0].startswith("echo ")
        assert sdk.instance.commands.calls[0].endswith("| sh")

    async def test_execute_maps_command_exit_exception_to_failed(
        self, sdk: type[FakeAsyncSandbox]
    ) -> None:
        worker = await started_worker()
        assert sdk.instance is not None
        sdk.instance.commands.responses.append(FakeCommandExit(3, stdout="", stderr="boom"))

        result = await worker.execute({"command": "python broken.py"})

        assert result.status is WorkerStatus.FAILED
        assert result.exit_code == 3
        assert result.error == "boom"

    async def test_execute_maps_transport_error_to_failed(
        self, sdk: type[FakeAsyncSandbox]
    ) -> None:
        worker = await started_worker()
        assert sdk.instance is not None
        sdk.instance.commands.responses.append(ConnectionError("socket closed"))

        result = await worker.execute({"command": "echo hi"})

        assert result.status is WorkerStatus.FAILED
        assert result.exit_code == -1
        assert "socket closed" in (result.error or "")

    async def test_execute_rejects_disallowed_command(
        self, sdk: type[FakeAsyncSandbox]
    ) -> None:
        worker = await started_worker()

        with pytest.raises(ValueError, match="not in the allowed list"):
            await worker.execute({"command": "sudo reboot"})

    async def test_execute_requires_started_worker(self) -> None:
        worker = E2BSandboxWorker()

        with pytest.raises(RuntimeError, match="not started"):
            await worker.execute({"command": "echo hi"})

    async def test_execute_stores_result_in_session_buddy(
        self, sdk: type[FakeAsyncSandbox]
    ) -> None:
        class FakeSessionBuddy:
            def __init__(self) -> None:
                self.tool_calls: list[tuple[str, dict[str, Any]]] = []

            async def call_tool(self, name: str, arguments: dict[str, Any]) -> None:
                self.tool_calls.append((name, arguments))

        buddy = FakeSessionBuddy()
        worker = await started_worker(session_buddy_client=buddy)
        assert sdk.instance is not None
        sdk.instance.commands.responses.append(FakeCommandResult(0, "42\n", ""))

        await worker.execute({"command": "python -c 'print(42)'"})

        assert len(buddy.tool_calls) == 1
        name, arguments = buddy.tool_calls[0]
        assert name == "store_memory"
        assert json.loads(arguments["content"])["exit_code"] == 0
        assert arguments["metadata"]["runtime"] == "e2b"


class TestStopAndStatus:
    async def test_stop_kills_sandbox_and_clears_state(
        self, sdk: type[FakeAsyncSandbox]
    ) -> None:
        worker = await started_worker()
        sandbox = sdk.instance
        assert sandbox is not None

        await worker.stop()

        assert sandbox.killed is True
        assert worker.sandbox_id is None
        assert await worker.status() is WorkerStatus.PENDING

    async def test_status_completed_when_sandbox_not_running(
        self, sdk: type[FakeAsyncSandbox]
    ) -> None:
        worker = await started_worker()
        assert sdk.instance is not None
        sdk.instance.killed = True  # simulate timeout-kill server side

        assert await worker.status() is WorkerStatus.COMPLETED
