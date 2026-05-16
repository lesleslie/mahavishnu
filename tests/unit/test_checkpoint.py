"""Tests for session/checkpoint.py — SessionBuddy write-forward sink."""

from unittest.mock import MagicMock

import httpx
import respx

from mahavishnu.session.checkpoint import SessionBuddy


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

    @respx.mock
    async def test_enabled_returns_uuid(self):
        respx.post(_TOOLS_URL).mock(return_value=httpx.Response(200, json=_SUCCESS_RESPONSE))
        sb = SessionBuddy(_mock_config())
        checkpoint_id = await sb.create_checkpoint("sess-1", {})
        # UUID format: 8-4-4-4-12
        assert len(checkpoint_id) == 36
        assert checkpoint_id.count("-") == 4

    @respx.mock
    async def test_calls_store_conversation_checkpoint(self):
        route = respx.post(_TOOLS_URL).mock(
            return_value=httpx.Response(200, json=_SUCCESS_RESPONSE)
        )
        sb = SessionBuddy(_mock_config())
        await sb.create_checkpoint("sess-1", {})
        assert route.called
        body = route.calls[0].request.content
        import json

        payload = json.loads(body)
        assert payload["name"] == "store_conversation_checkpoint"

    @respx.mock
    async def test_degraded_on_http_error_still_returns_uuid(self):
        respx.post(_TOOLS_URL).mock(return_value=httpx.Response(500))
        sb = SessionBuddy(_mock_config())
        checkpoint_id = await sb.create_checkpoint("sess-1", {})
        assert len(checkpoint_id) == 36

    @respx.mock
    async def test_degraded_on_connect_error_still_returns_uuid(self):
        respx.post(_TOOLS_URL).mock(side_effect=httpx.ConnectError("refused"))
        sb = SessionBuddy(_mock_config())
        checkpoint_id = await sb.create_checkpoint("sess-1", {})
        assert len(checkpoint_id) == 36

    @respx.mock
    async def test_passes_quality_score_when_present(self):
        route = respx.post(_TOOLS_URL).mock(
            return_value=httpx.Response(200, json=_SUCCESS_RESPONSE)
        )
        sb = SessionBuddy(_mock_config())
        await sb.create_checkpoint("sess-1", {"quality_score": 85})
        import json

        payload = json.loads(route.calls[0].request.content)
        assert payload["arguments"]["quality_score"] == 85


class TestUpdateCheckpoint:
    async def test_disabled_returns_true(self):
        sb = SessionBuddy(_mock_config(enabled=False))
        assert await sb.update_checkpoint("ckpt-1", "running") is True

    @respx.mock
    async def test_non_terminal_does_not_call_service(self):
        route = respx.post(_TOOLS_URL).mock(
            return_value=httpx.Response(200, json=_SUCCESS_RESPONSE)
        )
        sb = SessionBuddy(_mock_config())
        result = await sb.update_checkpoint("ckpt-1", "running")
        assert result is True
        assert not route.called

    @respx.mock
    async def test_terminal_completed_calls_service(self):
        route = respx.post(_TOOLS_URL).mock(
            return_value=httpx.Response(200, json=_SUCCESS_RESPONSE)
        )
        sb = SessionBuddy(_mock_config())
        result = await sb.update_checkpoint("ckpt-1", "completed")
        assert result is True
        assert route.called

    @respx.mock
    async def test_terminal_failed_calls_service(self):
        route = respx.post(_TOOLS_URL).mock(
            return_value=httpx.Response(200, json=_SUCCESS_RESPONSE)
        )
        sb = SessionBuddy(_mock_config())
        result = await sb.update_checkpoint("ckpt-1", "failed")
        assert result is True
        assert route.called

    @respx.mock
    async def test_degraded_returns_false(self):
        respx.post(_TOOLS_URL).mock(side_effect=httpx.ConnectError("refused"))
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
    @respx.mock
    async def test_healthy_when_200(self):
        respx.get(_HEALTH_URL).mock(return_value=httpx.Response(200))
        sb = SessionBuddy(_mock_config())
        assert await sb.is_healthy() is True

    @respx.mock
    async def test_unhealthy_when_500(self):
        respx.get(_HEALTH_URL).mock(return_value=httpx.Response(500))
        sb = SessionBuddy(_mock_config())
        assert await sb.is_healthy() is False

    @respx.mock
    async def test_unhealthy_on_connect_error(self):
        respx.get(_HEALTH_URL).mock(side_effect=httpx.ConnectError("refused"))
        sb = SessionBuddy(_mock_config())
        assert await sb.is_healthy() is False
