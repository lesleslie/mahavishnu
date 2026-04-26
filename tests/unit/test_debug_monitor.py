"""Comprehensive tests for the DebugMonitorWorker class."""

import asyncio
import logging
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.core.status import WorkerStatus
from mahavishnu.workers.base import BaseWorker, WorkerResult
from mahavishnu.workers.debug_monitor import DebugMonitorWorker


@pytest.fixture
def log_path():
    return Path("/var/log/mahavishnu-debug.log")


@pytest.fixture
def terminal_manager():
    tm = AsyncMock()
    tm.current_adapter = MagicMock(return_value="mcpretentious")
    tm.launch_sessions.return_value = ["session_test_001"]
    tm.close_session.return_value = None
    tm.list_sessions.return_value = []
    return tm


@pytest.fixture
def iterm2_terminal_manager():
    tm = AsyncMock()
    tm.current_adapter = MagicMock(return_value="iterm2")
    tm.adapter = MagicMock()
    tm.adapter._connection = "fake_iterm2_connection"
    tm.launch_sessions.return_value = ["session_iterm2_001"]
    tm.close_session.return_value = None
    tm.list_sessions.return_value = []
    return tm


@pytest.fixture
def session_buddy_client():
    client = AsyncMock()
    client.call_tool.return_value = None
    return client


@pytest.fixture
def monitor(terminal_manager, log_path):
    return DebugMonitorWorker(
        log_path=log_path,
        terminal_manager=terminal_manager,
    )


@pytest.fixture
def monitor_with_sb(terminal_manager, log_path, session_buddy_client):
    return DebugMonitorWorker(
        log_path=log_path,
        terminal_manager=terminal_manager,
        session_buddy_client=session_buddy_client,
    )


class TestDebugMonitorInitialization:
    """Tests for DebugMonitorWorker constructor and initial state."""

    def test_inherits_from_base_worker(self, monitor):
        assert isinstance(monitor, BaseWorker)

    def test_worker_type_is_debug_monitor(self, monitor):
        assert monitor.worker_type == "debug-monitor"

    def test_initial_status_is_pending(self, monitor):
        assert monitor._status == WorkerStatus.PENDING

    def test_log_path_stored(self, monitor, log_path):
        assert monitor.log_path == log_path

    def test_terminal_manager_stored(self, monitor, terminal_manager):
        assert monitor.terminal_manager is terminal_manager

    def test_session_buddy_client_defaults_to_none(self, monitor):
        assert monitor.session_buddy_client is None

    def test_session_buddy_client_can_be_set(self, monitor_with_sb, session_buddy_client):
        assert monitor_with_sb.session_buddy_client is session_buddy_client

    def test_session_id_initially_none(self, monitor):
        assert monitor.session_id is None

    def test_iterm2_connection_initially_none(self, monitor):
        assert monitor._iterm2_connection is None

    def test_streaming_task_initially_none(self, monitor):
        assert monitor._streaming_task is None

    def test_running_initially_false(self, monitor):
        assert monitor._running is False


class TestDebugMonitorStart:
    """Tests for the start method and its routing logic."""

    @pytest.mark.asyncio
    async def test_start_with_non_iterm2_adapter(self, monitor, terminal_manager):
        session_id = await monitor.start()
        terminal_manager.launch_sessions.assert_called_once_with(
            command=f"tail -f {monitor.log_path}",
            count=1,
        )
        assert session_id == "session_test_001"
        assert monitor.session_id == "session_test_001"

    @pytest.mark.asyncio
    async def test_start_with_iterm2_adapter(self, log_path, iterm2_terminal_manager):
        monitor = DebugMonitorWorker(
            log_path=log_path,
            terminal_manager=iterm2_terminal_manager,
        )
        session_id = await monitor.start()
        iterm2_terminal_manager.launch_sessions.assert_called_once_with(
            command=f"tail -f {log_path}",
            count=1,
        )
        assert session_id == "session_iterm2_001"
        assert monitor.session_id == "session_iterm2_001"

    @pytest.mark.asyncio
    async def test_start_iterm2_captures_connection(self, log_path, iterm2_terminal_manager):
        monitor = DebugMonitorWorker(
            log_path=log_path,
            terminal_manager=iterm2_terminal_manager,
        )
        await monitor.start()
        assert monitor._iterm2_connection == "fake_iterm2_connection"

    @pytest.mark.asyncio
    async def test_start_iterm2_adapter_without_connection_attribute(self, log_path):
        tm = AsyncMock()
        tm.current_adapter.return_value = "iterm2"
        tm.adapter = MagicMock(spec=[])
        del tm.adapter._connection
        tm.launch_sessions.return_value = ["session_no_conn"]
        tm.list_sessions.return_value = []

        monitor = DebugMonitorWorker(log_path=log_path, terminal_manager=tm)
        await monitor.start()
        assert monitor._iterm2_connection is None

    @pytest.mark.asyncio
    async def test_start_iterm2_adapter_with_none_connection(self, log_path):
        tm = AsyncMock()
        tm.current_adapter.return_value = "iterm2"
        tm.adapter = MagicMock()
        tm.adapter._connection = None
        tm.launch_sessions.return_value = ["session_none_conn"]
        tm.list_sessions.return_value = []

        monitor = DebugMonitorWorker(log_path=log_path, terminal_manager=tm)
        await monitor.start()
        assert monitor._iterm2_connection is None

    @pytest.mark.asyncio
    async def test_start_with_session_buddy_creates_streaming_task(self, monitor_with_sb):
        await monitor_with_sb.start()
        assert monitor_with_sb._streaming_task is not None
        assert monitor_with_sb._running is True

    @pytest.mark.asyncio
    async def test_start_without_session_buddy_no_streaming_task(self, monitor):
        await monitor.start()
        assert monitor._streaming_task is None
        assert monitor._running is False

    @pytest.mark.asyncio
    async def test_start_session_buddy_iterm2_creates_streaming_task(
        self, log_path, iterm2_terminal_manager, session_buddy_client
    ):
        monitor = DebugMonitorWorker(
            log_path=log_path,
            terminal_manager=iterm2_terminal_manager,
            session_buddy_client=session_buddy_client,
        )
        await monitor.start()
        assert monitor._streaming_task is not None
        assert monitor._running is True


class TestDebugMonitorStop:
    """Tests for the stop method and cleanup logic."""

    @pytest.mark.asyncio
    async def test_stop_sets_running_false(self, monitor):
        monitor._running = True
        await monitor.stop()
        assert monitor._running is False

    @pytest.mark.asyncio
    async def test_stop_cancels_streaming_task(self, monitor_with_sb):
        await monitor_with_sb.start()
        task = monitor_with_sb._streaming_task
        assert task is not None
        await monitor_with_sb.stop()
        assert monitor_with_sb._streaming_task is None
        assert task.cancelled()

    @pytest.mark.asyncio
    async def test_stop_without_streaming_task(self, monitor):
        monitor._running = True
        await monitor.stop()
        assert monitor._streaming_task is None

    @pytest.mark.asyncio
    async def test_stop_closes_terminal_session(self, monitor):
        monitor.session_id = "session_to_close"
        await monitor.stop()
        monitor.terminal_manager.close_session.assert_called_once_with("session_to_close")
        assert monitor.session_id is None

    @pytest.mark.asyncio
    async def test_stop_without_session_id(self, monitor):
        monitor.session_id = None
        await monitor.stop()
        monitor.terminal_manager.close_session.assert_not_called()

    @pytest.mark.asyncio
    async def test_stop_handles_close_session_error(self, monitor):
        monitor.session_id = "session_fail_close"
        monitor.terminal_manager.close_session.side_effect = RuntimeError("close failed")
        await monitor.stop()
        assert monitor.session_id is None

    @pytest.mark.asyncio
    async def test_stop_sets_status_to_completed(self, monitor):
        monitor.session_id = "session_complete"
        await monitor.stop()
        assert monitor._status == WorkerStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_stop_with_cancelled_streaming_task(self, monitor_with_sb):
        await monitor_with_sb.start()
        monitor_with_sb._streaming_task.cancel()
        await monitor_with_sb.stop()
        assert monitor_with_sb._streaming_task is None


class TestDebugMonitorExecute:
    """Tests for the execute method which should always raise NotImplementedError."""

    @pytest.mark.asyncio
    async def test_execute_raises_not_implemented(self, monitor):
        with pytest.raises(NotImplementedError, match="passive and does not execute tasks"):
            await monitor.execute({"task": "something"})

    @pytest.mark.asyncio
    async def test_execute_error_message_content(self, monitor):
        with pytest.raises(NotImplementedError) as exc_info:
            await monitor.execute({})
        assert "Debug monitor is passive" in str(exc_info.value)
        assert "Session-Buddy" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_execute_with_various_task_dicts(self, monitor):
        for task in [{"cmd": "run"}, {"nested": {"key": "val"}}, {"prompt": "do work"}]:
            with pytest.raises(NotImplementedError):
                await monitor.execute(task)


class TestDebugMonitorStatus:
    """Tests for the status method and its state transitions."""

    @pytest.mark.asyncio
    async def test_status_pending_when_no_session(self, monitor):
        assert await monitor.status() == WorkerStatus.PENDING

    @pytest.mark.asyncio
    async def test_status_running_with_active_streaming_task(self, monitor_with_sb):
        monitor_with_sb.session_id = "active_session"
        mock_task = MagicMock()
        mock_task.done.return_value = False
        monitor_with_sb._streaming_task = mock_task
        assert await monitor_with_sb.status() == WorkerStatus.RUNNING

    @pytest.mark.asyncio
    async def test_status_running_when_session_found_in_list(self, monitor):
        monitor.session_id = "listed_session"
        monitor.terminal_manager.list_sessions.return_value = [
            {"id": "listed_session", "name": "debug"}
        ]
        assert await monitor.status() == WorkerStatus.RUNNING

    @pytest.mark.asyncio
    async def test_status_completed_when_session_not_found(self, monitor):
        monitor.session_id = "missing_session"
        monitor.terminal_manager.list_sessions.return_value = [
            {"id": "other_session", "name": "other"}
        ]
        assert await monitor.status() == WorkerStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_status_completed_when_session_list_empty(self, monitor):
        monitor.session_id = "orphan_session"
        monitor.terminal_manager.list_sessions.return_value = []
        assert await monitor.status() == WorkerStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_status_handles_list_sessions_exception(self, monitor):
        monitor.session_id = "error_session"
        monitor.terminal_manager.list_sessions.side_effect = RuntimeError("connection lost")
        assert await monitor.status() == WorkerStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_status_running_streaming_takes_priority(self, monitor_with_sb):
        monitor_with_sb.session_id = "priority_session"
        mock_task = MagicMock()
        mock_task.done.return_value = False
        monitor_with_sb._streaming_task = mock_task
        status = await monitor_with_sb.status()
        assert status == WorkerStatus.RUNNING


class TestDebugMonitorGetProgress:
    """Tests for the get_progress method."""

    @pytest.mark.asyncio
    async def test_get_progress_initial_state(self, monitor):
        progress = await monitor.get_progress()
        assert progress["status"] == WorkerStatus.PENDING
        assert progress["session_id"] is None
        assert progress["log_path"] == str(monitor.log_path)
        assert progress["streaming_active"] is False
        assert progress["iterm2_connected"] is False
        assert progress["running"] is False

    @pytest.mark.asyncio
    async def test_get_progress_after_start(self, monitor):
        await monitor.start()
        progress = await monitor.get_progress()
        assert progress["session_id"] == "session_test_001"
        assert progress["log_path"] == str(monitor.log_path)
        assert progress["streaming_active"] is False

    @pytest.mark.asyncio
    async def test_get_progress_with_streaming_active(self, monitor_with_sb):
        await monitor_with_sb.start()
        progress = await monitor_with_sb.get_progress()
        assert progress["streaming_active"] is True
        assert progress["running"] is True

    @pytest.mark.asyncio
    async def test_get_progress_with_iterm2_connection(self, log_path, iterm2_terminal_manager):
        monitor = DebugMonitorWorker(log_path=log_path, terminal_manager=iterm2_terminal_manager)
        await monitor.start()
        progress = await monitor.get_progress()
        assert progress["iterm2_connected"] is True

    @pytest.mark.asyncio
    async def test_get_progress_after_stop(self, monitor):
        monitor.session_id = "stopped_session"
        monitor._running = True
        await monitor.stop()
        progress = await monitor.get_progress()
        assert progress["running"] is False
        assert progress["session_id"] is None
        assert progress["streaming_active"] is False


class TestStreamToSessionBuddy:
    """Tests for the _stream_to_session_buddy background method."""

    @pytest.mark.asyncio
    async def test_stream_returns_early_without_client(self, monitor):
        await monitor._stream_to_session_buddy()

    @pytest.mark.asyncio
    async def test_stream_iterm2_full_cycle(self, monitor_with_sb):
        self._inject_mock_iterm2()
        try:
            mock_task = asyncio.create_task(monitor_with_sb._stream_to_session_buddy())
            await asyncio.sleep(0.05)
            monitor_with_sb._running = False
            try:
                await asyncio.wait_for(mock_task, timeout=2.0)
            except asyncio.TimeoutError:
                mock_task.cancel()
                try:
                    await mock_task
                except asyncio.CancelledError:
                    pass
        finally:
            self._eject_mock_iterm2()

    @pytest.mark.asyncio
    async def test_stream_handles_cancelled_error(self, monitor_with_sb):
        self._inject_mock_iterm2()
        try:
            mock_task = asyncio.create_task(monitor_with_sb._stream_to_session_buddy())
            await asyncio.sleep(0.02)
            mock_task.cancel()
            result = await mock_task
            assert result is None
        finally:
            self._eject_mock_iterm2()

    def _inject_mock_iterm2(self):
        mock_iterm2 = MagicMock()
        mock_iterm2.App.async_get_connection = AsyncMock()
        sys.modules["iterm2"] = mock_iterm2
        return mock_iterm2

    def _eject_mock_iterm2(self):
        sys.modules.pop("iterm2", None)

    @pytest.mark.asyncio
    async def test_stream_stores_non_empty_log_text(
        self, log_path, iterm2_terminal_manager, session_buddy_client
    ):
        mock_iterm2 = self._inject_mock_iterm2()
        try:
            monitor = DebugMonitorWorker(
                log_path=log_path,
                terminal_manager=iterm2_terminal_manager,
                session_buddy_client=session_buddy_client,
            )
            await monitor.start()

            mock_app = AsyncMock()
            mock_session = AsyncMock()
            mock_session.session_id = "session_iterm2_001"
            mock_line = MagicMock()
            mock_line.string = "2026-04-24 ERROR something went wrong"
            mock_session.async_get_contents.return_value = [mock_line]
            mock_app.async_get_sessions.return_value = [mock_session]
            mock_iterm2.App.async_get_connection.return_value = mock_app

            monitor._running = True
            mock_task = asyncio.create_task(monitor._stream_to_session_buddy())
            await asyncio.sleep(0.15)
            monitor._running = False
            try:
                await asyncio.wait_for(mock_task, timeout=2.0)
            except asyncio.TimeoutError:
                mock_task.cancel()
                try:
                    await mock_task
                except asyncio.CancelledError:
                    pass

            session_buddy_client.call_tool.assert_called()
            call_args = session_buddy_client.call_tool.call_args
            assert call_args[0][0] == "store_memory"
            assert call_args[1]["arguments"]["metadata"]["type"] == "debug_log"
            assert call_args[1]["arguments"]["metadata"]["source"] == "mahavishnu_debug_monitor"
        finally:
            self._eject_mock_iterm2()

    @pytest.mark.asyncio
    async def test_stream_skips_empty_log_text(
        self, log_path, iterm2_terminal_manager, session_buddy_client
    ):
        mock_iterm2 = self._inject_mock_iterm2()
        try:
            monitor = DebugMonitorWorker(
                log_path=log_path,
                terminal_manager=iterm2_terminal_manager,
                session_buddy_client=session_buddy_client,
            )
            await monitor.start()

            mock_app = AsyncMock()
            mock_session = AsyncMock()
            mock_session.session_id = "session_iterm2_001"
            empty_line = MagicMock()
            empty_line.string = ""
            mock_session.async_get_contents.return_value = [empty_line]
            mock_app.async_get_sessions.return_value = [mock_session]
            mock_iterm2.App.async_get_connection.return_value = mock_app

            monitor._running = True
            mock_task = asyncio.create_task(monitor._stream_to_session_buddy())
            await asyncio.sleep(0.15)
            monitor._running = False
            try:
                await asyncio.wait_for(mock_task, timeout=2.0)
            except asyncio.TimeoutError:
                mock_task.cancel()
                try:
                    await mock_task
                except asyncio.CancelledError:
                    pass

            session_buddy_client.call_tool.assert_not_called()
        finally:
            self._eject_mock_iterm2()

    @pytest.mark.asyncio
    async def test_stream_handles_screen_capture_failure(
        self, log_path, iterm2_terminal_manager, session_buddy_client
    ):
        mock_iterm2 = self._inject_mock_iterm2()
        try:
            monitor = DebugMonitorWorker(
                log_path=log_path,
                terminal_manager=iterm2_terminal_manager,
                session_buddy_client=session_buddy_client,
            )
            await monitor.start()

            mock_app = AsyncMock()
            mock_session = AsyncMock()
            mock_session.session_id = "session_iterm2_001"
            mock_session.async_get_contents.side_effect = RuntimeError("capture failed")
            mock_app.async_get_sessions.return_value = [mock_session]
            mock_iterm2.App.async_get_connection.return_value = mock_app

            monitor._running = True
            mock_task = asyncio.create_task(monitor._stream_to_session_buddy())
            await asyncio.sleep(0.1)
            monitor._running = False
            try:
                await asyncio.wait_for(mock_task, timeout=2.0)
            except asyncio.TimeoutError:
                mock_task.cancel()
                try:
                    await mock_task
                except asyncio.CancelledError:
                    pass

            session_buddy_client.call_tool.assert_not_called()
        finally:
            self._eject_mock_iterm2()

    @pytest.mark.asyncio
    async def test_stream_handles_lines_without_string_attribute(
        self, log_path, iterm2_terminal_manager, session_buddy_client
    ):
        mock_iterm2 = self._inject_mock_iterm2()
        try:
            monitor = DebugMonitorWorker(
                log_path=log_path,
                terminal_manager=iterm2_terminal_manager,
                session_buddy_client=session_buddy_client,
            )
            await monitor.start()

            mock_app = AsyncMock()
            mock_session = AsyncMock()
            mock_session.session_id = "session_iterm2_001"
            line_no_string = MagicMock(spec=[])
            mock_session.async_get_contents.return_value = [line_no_string]
            mock_app.async_get_sessions.return_value = [mock_session]
            mock_iterm2.App.async_get_connection.return_value = mock_app

            monitor._running = True
            mock_task = asyncio.create_task(monitor._stream_to_session_buddy())
            await asyncio.sleep(0.15)
            monitor._running = False
            try:
                await asyncio.wait_for(mock_task, timeout=2.0)
            except asyncio.TimeoutError:
                mock_task.cancel()
                try:
                    await mock_task
                except asyncio.CancelledError:
                    pass

            session_buddy_client.call_tool.assert_not_called()
        finally:
            self._eject_mock_iterm2()

    @pytest.mark.asyncio
    async def test_stream_skips_when_session_not_found(
        self, log_path, iterm2_terminal_manager, session_buddy_client
    ):
        mock_iterm2 = self._inject_mock_iterm2()
        try:
            monitor = DebugMonitorWorker(
                log_path=log_path,
                terminal_manager=iterm2_terminal_manager,
                session_buddy_client=session_buddy_client,
            )
            await monitor.start()

            mock_app = AsyncMock()
            other_session = AsyncMock()
            other_session.session_id = "different_session"
            mock_app.async_get_sessions.return_value = [other_session]
            mock_iterm2.App.async_get_connection.return_value = mock_app

            monitor._running = True
            mock_task = asyncio.create_task(monitor._stream_to_session_buddy())
            await asyncio.sleep(0.15)
            monitor._running = False
            try:
                await asyncio.wait_for(mock_task, timeout=2.0)
            except asyncio.TimeoutError:
                mock_task.cancel()
                try:
                    await mock_task
                except asyncio.CancelledError:
                    pass

            session_buddy_client.call_tool.assert_not_called()
        finally:
            self._eject_mock_iterm2()

    @pytest.mark.asyncio
    async def test_stream_with_fatal_error(self, monitor_with_sb):
        mock_iterm2 = self._inject_mock_iterm2()
        try:
            monitor_with_sb._iterm2_connection = "conn"
            mock_iterm2.App.async_get_connection.side_effect = RuntimeError("fatal error")
            monitor_with_sb._running = True
            mock_task = asyncio.create_task(monitor_with_sb._stream_to_session_buddy())
            await asyncio.sleep(0.1)
            monitor_with_sb._running = False
            try:
                await asyncio.wait_for(mock_task, timeout=2.0)
            except asyncio.TimeoutError:
                mock_task.cancel()
                try:
                    await mock_task
                except asyncio.CancelledError:
                    pass
        finally:
            self._eject_mock_iterm2()


class TestDebugMonitorHealthCheck:
    """Tests for the inherited health_check method."""

    @pytest.mark.asyncio
    async def test_health_check_pending_is_healthy(self, monitor):
        result = await monitor.health_check()
        assert result["healthy"] is True
        assert result["status"] == WorkerStatus.PENDING.value
        assert result["worker_type"] == "debug-monitor"

    @pytest.mark.asyncio
    async def test_health_check_running_is_healthy(self, monitor):
        monitor.session_id = "active"
        mock_task = MagicMock()
        mock_task.done.return_value = False
        monitor._streaming_task = mock_task
        result = await monitor.health_check()
        assert result["healthy"] is True
        assert result["status"] == WorkerStatus.RUNNING.value

    @pytest.mark.asyncio
    async def test_health_check_completed_is_not_healthy(self, monitor):
        monitor.session_id = "done"
        monitor.terminal_manager.list_sessions.return_value = []
        result = await monitor.health_check()
        assert result["healthy"] is False
        assert result["status"] == WorkerStatus.COMPLETED.value

    @pytest.mark.asyncio
    async def test_health_check_handles_exception(self, monitor):
        monitor.session_id = "boom"
        monitor.terminal_manager.list_sessions.side_effect = RuntimeError("network error")
        result = await monitor.health_check()
        assert result["healthy"] is False


class TestDebugMonitorEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_log_path_as_string(self, terminal_manager):
        monitor = DebugMonitorWorker(
            log_path="/tmp/test.log",
            terminal_manager=terminal_manager,
        )
        assert monitor.log_path == "/tmp/test.log"

    @pytest.mark.asyncio
    async def test_double_start_overwrites_session(self, monitor):
        monitor.terminal_manager.launch_sessions.side_effect = [
            ["session_first"],
            ["session_second"],
        ]
        await monitor.start()
        assert monitor.session_id == "session_first"
        await monitor.start()
        assert monitor.session_id == "session_second"

    @pytest.mark.asyncio
    async def test_stop_when_already_stopped(self, monitor):
        monitor._running = False
        monitor.session_id = None
        monitor._streaming_task = None
        await monitor.stop()
        assert monitor._status == WorkerStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_start_stop_start_cycle(self, monitor):
        first_id = await monitor.start()
        await monitor.stop()
        monitor.terminal_manager.launch_sessions.return_value = ["session_second"]
        second_id = await monitor.start()
        assert first_id == "session_test_001"
        assert second_id == "session_second"
        assert monitor.session_id == "session_second"
