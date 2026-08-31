"""Tests for session/checkpoint.py — SessionBuddy write-forward sink."""

import json
from unittest.mock import MagicMock

import httpx2 as httpx

from mahavishnu.session.checkpoint import SessionBuddy

from tests.unit._httpx_test_helpers import (
    make_recording_handler,
    make_response_handler,
    patch_async_client,
)


def _mock_config(enabled=True, session_buddy_url="http://localhost:8678/mcp"):
    config = MagicMock()
    config.session.enabled = enabled
    config.session.checkpoint_interval = 60
    config.pools.session_buddy_url = session_buddy_url
    return config


_TOOLS_URL = "http://localhost:8678/mcp/tools/call"
_HEALTH_URL = "http://localhost:8678/health"

_SUCCESS_RESPONSE = {
    "result": "✅ Conversation checkpoint stored successfully!\n📝 Conversation ID: abc-123"
}

_TARGET = "mahavishnu.session.checkpoint"


class TestSessionBuddyInit:
    def test_enabled_init(self):
        sb = SessionBuddy(_mock_config(enabled=True))
        assert sb.enabled is True
        assert sb.checkpoint_interval == 60

    def test_disabled_init(self):
        sb = SessionBuddy(_mock_config(enabled=False))
        assert sb.enabled is False


class TestCreateCheckpoint:
    async def test_disabled_returns_prefixed_id(self):
        sb = SessionBuddy(_mock_config(enabled=False))
        result = await sb.create_checkpoint("sess-1", {})
        assert result.startswith("checkpoint_disabled_sess-1")

    async def test_enabled_returns_uuid(self):
        handler = make_response_handler(httpx.Response(200, json=_SUCCESS_RESPONSE))
        with patch_async_client(handler, _TARGET):
            sb = SessionBuddy(_mock_config())
            checkpoint_id = await sb.create_checkpoint("sess-1", {})
        # UUID format: 8-4-4-4-12
        assert len(checkpoint_id) == 36
        assert checkpoint_id.count("-") == 4

    async def test_calls_store_conversation_checkpoint(self):
        captured, handler = make_recording_handler(
            httpx.Response(200, json=_SUCCESS_RESPONSE)
        )
        with patch_async_client(handler, _TARGET):
            sb = SessionBuddy(_mock_config())
            await sb.create_checkpoint("sess-1", {})
        assert len(captured) == 1
        payload = json.loads(captured[0].content)
        assert payload["name"] == "store_conversation_checkpoint"

    async def test_degraded_on_http_error_still_returns_uuid(self):
        handler = make_response_handler(httpx.Response(500))
        with patch_async_client(handler, _TARGET):
            sb = SessionBuddy(_mock_config())
            checkpoint_id = await sb.create_checkpoint("sess-1", {})
        assert len(checkpoint_id) == 36

    async def test_degraded_on_connect_error_still_returns_uuid(self):
        def fail_handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused")

        with patch_async_client(fail_handler, _TARGET):
            sb = SessionBuddy(_mock_config())
            checkpoint_id = await sb.create_checkpoint("sess-1", {})
        assert len(checkpoint_id) == 36

    async def test_passes_quality_score_when_present(self):
        captured, handler = make_recording_handler(
            httpx.Response(200, json=_SUCCESS_RESPONSE)
        )
        with patch_async_client(handler, _TARGET):
            sb = SessionBuddy(_mock_config())
            await sb.create_checkpoint("sess-1", {"quality_score": 85})
        payload = json.loads(captured[0].content)
        assert payload["arguments"]["quality_score"] == 85


class TestUpdateCheckpoint:
    async def test_disabled_returns_true(self):
        sb = SessionBuddy(_mock_config(enabled=False))
        assert await sb.update_checkpoint("ckpt-1", "running") is True

    async def test_non_terminal_does_not_call_service(self):
        captured, handler = make_recording_handler(
            httpx.Response(200, json=_SUCCESS_RESPONSE)
        )
        with patch_async_client(handler, _TARGET):
            sb = SessionBuddy(_mock_config())
            result = await sb.update_checkpoint("ckpt-1", "running")
        assert result is True
        assert len(captured) == 0

    async def test_terminal_completed_calls_service(self):
        captured, handler = make_recording_handler(
            httpx.Response(200, json=_SUCCESS_RESPONSE)
        )
        with patch_async_client(handler, _TARGET):
            sb = SessionBuddy(_mock_config())
            result = await sb.update_checkpoint("ckpt-1", "completed")
        assert result is True
        assert len(captured) == 1

    async def test_terminal_failed_calls_service(self):
        captured, handler = make_recording_handler(
            httpx.Response(200, json=_SUCCESS_RESPONSE)
        )
        with patch_async_client(handler, _TARGET):
            sb = SessionBuddy(_mock_config())
            result = await sb.update_checkpoint("ckpt-1", "failed")
        assert result is True
        assert len(captured) == 1

    async def test_degraded_returns_false(self):
        def fail_handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused")

        with patch_async_client(fail_handler, _TARGET):
            sb = SessionBuddy(_mock_config())
            result = await sb.update_checkpoint("ckpt-1", "completed")
        assert result is False


class TestGetCheckpoint:
    async def test_always_returns_none(self):
        sb = SessionBuddy(_mock_config())
        assert await sb.get_checkpoint("any-id") is None

    async def test_disabled_also_returns_none(self):
        sb = SessionBuddy(_mock_config(enabled=False))
        assert await sb.get_checkpoint("any-id") is None


class TestRestoreFromCheckpoint:
    async def test_always_returns_none(self):
        sb = SessionBuddy(_mock_config())
        assert await sb.restore_from_checkpoint("any-id") is None


class TestCleanupCheckpoint:
    async def test_always_returns_true(self):
        sb = SessionBuddy(_mock_config())
        assert await sb.cleanup_checkpoint("any-id") is True

    async def test_disabled_also_returns_true(self):
        sb = SessionBuddy(_mock_config(enabled=False))
        assert await sb.cleanup_checkpoint("any-id") is True


class TestIsHealthy:
    async def test_healthy_when_200(self):
        handler = make_response_handler(httpx.Response(200))
        with patch_async_client(handler, _TARGET):
            sb = SessionBuddy(_mock_config())
            assert await sb.is_healthy() is True

    async def test_unhealthy_when_500(self):
        handler = make_response_handler(httpx.Response(500))
        with patch_async_client(handler, _TARGET):
            sb = SessionBuddy(_mock_config())
            assert await sb.is_healthy() is False

    async def test_unhealthy_on_connect_error(self):
        def fail_handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused")

        with patch_async_client(fail_handler, _TARGET):
            sb = SessionBuddy(_mock_config())
            assert await sb.is_healthy() is False
