"""Tests for Session-Buddy poller configuration and bridge metrics."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from mahavishnu.core.config import MahavishnuSettings
from mahavishnu.integrations.session_buddy_poller import SessionBuddyPoller
from monitoring.metrics import (
    bodai_bridge_metric_ingest_total,
    bodai_bridge_polls_total,
)


@pytest.fixture
def poller_config() -> MahavishnuSettings:
    """Configuration with Session-Buddy polling enabled."""
    return MahavishnuSettings(
        session_buddy_polling={
            "enabled": True,
            "endpoint": "http://localhost:8678/mcp/",
            "interval_seconds": 15,
            "timeout_seconds": 7,
            "max_retries": 2,
            "retry_delay_seconds": 3,
            "circuit_breaker_threshold": 4,
            "metrics_to_collect": ["get_activity_summary"],
        }
    )


class TestSessionBuddyPoller:
    """Test Session-Buddy poller behavior."""

    def test_uses_nested_polling_config(self, poller_config: MahavishnuSettings):
        """Poller should read the nested session_buddy_polling config model."""
        poller = SessionBuddyPoller(config=poller_config)

        assert poller.enabled is True
        assert poller.endpoint == "http://localhost:8678/mcp"
        assert poller.interval == 15
        assert poller.timeout == 7
        assert poller.max_retries == 2
        assert poller.retry_delay == 3
        assert poller.circuit_breaker_threshold == 4
        assert poller.metrics_to_collect == ["get_activity_summary"]

    @pytest.mark.asyncio
    async def test_poll_once_records_bridge_metrics(self, poller_config: MahavishnuSettings):
        """Successful polls should emit bridge metrics on the shared registry."""
        poller = SessionBuddyPoller(config=poller_config)
        poller._http_client = AsyncMock()

        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {"result": {"active_sessions": 2, "total_sessions": 5}}
        poller._http_client.post.return_value = mock_response

        result = await poller.poll_once()

        assert result["metrics_collected"] == ["get_activity_summary"]
        poll_value = bodai_bridge_polls_total.labels(
            source_service="session_buddy",
            status="success",
        )._value.get()
        ingest_value = bodai_bridge_metric_ingest_total.labels(
            source_service="session_buddy",
            source_tool="get_activity_summary",
        )._value.get()

        assert poll_value >= 1
        assert ingest_value >= 1
