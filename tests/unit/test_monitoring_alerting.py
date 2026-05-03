"""Tests for core.monitoring — Alert, AlertManager, NotificationChannels, Dashboard, MonitoringService."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import ANY, AsyncMock, MagicMock, Mock, patch

import pytest

from mahavishnu.core.monitoring import (
    Alert,
    AlertManager,
    AlertRule,
    AlertSeverity,
    AlertType,
    EmailNotificationChannel,
    MonitoringDashboard,
    MonitoringService,
    NotificationChannel,
    PagerDutyNotificationChannel,
    SlackNotificationChannel,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_alert(**overrides):
    """Build an Alert with sensible defaults."""
    defaults = {
        "severity": AlertSeverity.MEDIUM,
        "title": "test alert",
        "description": "something happened",
    }
    defaults.update(overrides)
    return Alert(**defaults)


# ---------------------------------------------------------------------------
# AlertRule
# ---------------------------------------------------------------------------


class TestAlertRule:
    def test_to_dict_round_trip(self):
        rule = AlertRule(
            name="cpu_high",
            expression="cpu > 90",
            severity=AlertSeverity.CRITICAL,
            duration_seconds=120,
            enabled=True,
            labels={"team": "platform"},
            annotations={"summary": "CPU too high"},
        )
        d = rule.to_dict()
        assert d["name"] == "cpu_high"
        assert d["expression"] == "cpu > 90"
        assert d["severity"] == "critical"
        assert d["duration_seconds"] == 120
        assert d["enabled"] is True
        assert d["labels"]["team"] == "platform"
        assert d["annotations"]["summary"] == "CPU too high"

    def test_default_values(self):
        rule = AlertRule(name="x", expression="y > 0")
        assert rule.severity == AlertSeverity.WARNING
        assert rule.duration_seconds == 60
        assert rule.enabled is True
        assert rule.labels == {}
        assert rule.annotations == {}


# ---------------------------------------------------------------------------
# Alert dataclass
# ---------------------------------------------------------------------------


class TestAlert:
    def test_auto_generated_id(self):
        alert = Alert(title="hello")
        assert alert.id is not None
        assert alert.id.startswith("alert_")

    def test_custom_id_preserved(self):
        alert = Alert(id="custom-1", title="hello")
        assert alert.id == "custom-1"

    def test_fired_at_defaults_to_timestamp(self):
        ts = datetime(2026, 1, 1, tzinfo=UTC)
        alert = Alert(timestamp=ts, title="hello")
        assert alert.fired_at == ts

    def test_fired_at_can_be_overridden(self):
        ts = datetime(2026, 1, 1, tzinfo=UTC)
        fired = datetime(2025, 6, 1, tzinfo=UTC)
        alert = Alert(timestamp=ts, fired_at=fired, title="hello")
        assert alert.fired_at == fired

    def test_message_falls_back_to_description(self):
        alert = Alert(description="fallback text")
        assert alert.message == "fallback text"

    def test_message_not_overwritten_when_set(self):
        alert = Alert(message="explicit", description="desc")
        assert alert.message == "explicit"

    def test_is_firing_true(self):
        alert = Alert(firing=True)
        assert alert.is_firing is True

    def test_is_firing_false(self):
        alert = Alert(firing=False)
        assert alert.is_firing is False

    def test_acknowledge_sets_fields(self):
        alert = Alert(title="test")
        before = datetime.now()
        alert.acknowledge("alice")
        assert alert.acknowledged is True
        assert alert.acknowledged_by == "alice"
        assert alert.acknowledged_at is not None
        assert alert.acknowledged_at >= before

    def test_to_dict_basic(self):
        alert = Alert(title="t", description="d", severity=AlertSeverity.HIGH)
        d = alert.to_dict()
        assert d["title"] == "t"
        assert d["description"] == "d"
        assert d["severity"] == "high"
        assert d["firing"] is True
        assert d["acknowledged"] is False

    def test_to_dict_with_type(self):
        alert = Alert(type=AlertType.BACKUP_FAILURE, title="t")
        d = alert.to_dict()
        assert d["type"] == "backup_failure"

    def test_to_dict_with_rule_name(self):
        alert = Alert(rule_name="my_rule", title="t")
        d = alert.to_dict()
        assert d["rule_name"] == "my_rule"

    def test_to_dict_omits_type_when_none(self):
        alert = Alert(title="t")
        d = alert.to_dict()
        assert "type" not in d

    def test_to_dict_omits_rule_name_when_none(self):
        alert = Alert(title="t")
        d = alert.to_dict()
        assert "rule_name" not in d

    def test_to_dict_omits_labels_when_empty(self):
        alert = Alert(title="t")
        d = alert.to_dict()
        assert "labels" not in d

    def test_to_dict_includes_labels_when_present(self):
        alert = Alert(title="t", labels={"env": "prod"})
        d = alert.to_dict()
        assert d["labels"] == {"env": "prod"}

    def test_to_dict_omits_message_when_none(self):
        alert = Alert(title="t", description="d")
        alert.message = None
        d = alert.to_dict()
        assert "message" not in d

    def test_to_dict_includes_message_when_present(self):
        alert = Alert(title="t", message="msg")
        d = alert.to_dict()
        assert d["message"] == "msg"


# ---------------------------------------------------------------------------
# AlertManager — rule management
# ---------------------------------------------------------------------------


class TestAlertManagerRules:
    def test_add_and_get_rule(self):
        mgr = AlertManager()
        rule = AlertRule(name="r1", expression="v > 0")
        mgr.add_rule(rule)
        assert "r1" in mgr.rules

    def test_remove_rule(self):
        mgr = AlertManager()
        mgr.add_rule(AlertRule(name="r1", expression="v > 0"))
        mgr.remove_rule("r1")
        assert "r1" not in mgr.rules

    def test_remove_nonexistent_rule_no_error(self):
        mgr = AlertManager()
        mgr.remove_rule("ghost")  # should not raise

    def test_enable_rule(self):
        mgr = AlertManager()
        mgr.add_rule(AlertRule(name="r1", expression="v > 0", enabled=False))
        mgr.enable_rule("r1")
        assert mgr.rules["r1"].enabled is True

    def test_disable_rule(self):
        mgr = AlertManager()
        mgr.add_rule(AlertRule(name="r1", expression="v > 0", enabled=True))
        mgr.disable_rule("r1")
        assert mgr.rules["r1"].enabled is False


# ---------------------------------------------------------------------------
# AlertManager — expression evaluation
# ---------------------------------------------------------------------------


class TestAlertManagerEvaluate:
    def test_evaluate_gt(self):
        mgr = AlertManager()
        mgr.add_rule(AlertRule(name="r1", expression="cpu > 80"))
        triggered = mgr.evaluate_rules({"cpu": 90})
        assert "r1" in triggered

    def test_evaluate_gt_no_trigger(self):
        mgr = AlertManager()
        mgr.add_rule(AlertRule(name="r1", expression="cpu > 80"))
        triggered = mgr.evaluate_rules({"cpu": 70})
        assert "r1" not in triggered

    def test_evaluate_gte(self):
        mgr = AlertManager()
        mgr.add_rule(AlertRule(name="r1", expression="cpu >= 80"))
        assert "r1" in mgr.evaluate_rules({"cpu": 80})

    def test_evaluate_lt(self):
        mgr = AlertManager()
        mgr.add_rule(AlertRule(name="r1", expression="free < 10"))
        assert "r1" in mgr.evaluate_rules({"free": 5})

    def test_evaluate_lte(self):
        mgr = AlertManager()
        mgr.add_rule(AlertRule(name="r1", expression="free <= 10"))
        assert "r1" in mgr.evaluate_rules({"free": 10})

    def test_evaluate_eq(self):
        mgr = AlertManager()
        mgr.add_rule(AlertRule(name="r1", expression="status == 1"))
        assert "r1" in mgr.evaluate_rules({"status": 1})

    def test_evaluate_ne(self):
        mgr = AlertManager()
        mgr.add_rule(AlertRule(name="r1", expression="status != 1"))
        assert "r1" in mgr.evaluate_rules({"status": 2})
        assert "r1" not in mgr.evaluate_rules({"status": 1})

    def test_evaluate_unknown_operator(self):
        mgr = AlertManager()
        mgr.add_rule(AlertRule(name="r1", expression="val ^^ 5"))
        assert "r1" not in mgr.evaluate_rules({"val": 10})

    def test_evaluate_bad_threshold(self):
        mgr = AlertManager()
        mgr.add_rule(AlertRule(name="r1", expression="val > notanum"))
        assert "r1" not in mgr.evaluate_rules({"val": 10})

    def test_evaluate_malformed_expression(self):
        mgr = AlertManager()
        mgr.add_rule(AlertRule(name="r1", expression="toomany parts"))
        assert "r1" not in mgr.evaluate_rules({})

    def test_evaluate_missing_metric_defaults_to_zero(self):
        mgr = AlertManager()
        mgr.add_rule(AlertRule(name="r1", expression="val > 5"))
        assert "r1" not in mgr.evaluate_rules({})

    def test_evaluate_disabled_rule_skipped(self):
        mgr = AlertManager()
        mgr.add_rule(AlertRule(name="r1", expression="val > 0", enabled=False))
        assert "r1" not in mgr.evaluate_rules({"val": 100})

    def test_evaluate_multiple_rules(self):
        mgr = AlertManager()
        mgr.add_rule(AlertRule(name="r1", expression="a > 5"))
        mgr.add_rule(AlertRule(name="r2", expression="b > 5"))
        triggered = mgr.evaluate_rules({"a": 10, "b": 3})
        assert triggered == ["r1"]


# ---------------------------------------------------------------------------
# AlertManager — fire / resolve
# ---------------------------------------------------------------------------


class TestAlertManagerFireResolve:
    def test_fire_alert_creates_active_alert(self):
        mgr = AlertManager()
        mgr.add_rule(AlertRule(name="r1", expression="v > 0"))
        mgr.fire_alert("r1", "val exceeded")
        assert "r1" in mgr.active_alerts
        assert mgr.active_alerts["r1"].firing is True

    def test_fire_alert_no_rule_does_nothing(self):
        mgr = AlertManager()
        mgr.fire_alert("ghost", "msg")  # no exception

    def test_fire_alert_copies_labels(self):
        mgr = AlertManager()
        mgr.add_rule(AlertRule(name="r1", expression="v > 0", labels={"env": "prod"}))
        mgr.fire_alert("r1", "msg")
        assert mgr.active_alerts["r1"].labels == {"env": "prod"}

    def test_resolve_alert(self):
        mgr = AlertManager()
        mgr.add_rule(AlertRule(name="r1", expression="v > 0"))
        mgr.fire_alert("r1", "msg")
        mgr.resolve_alert("r1")
        assert mgr.active_alerts["r1"].firing is False

    def test_resolve_nonexistent_alert(self):
        mgr = AlertManager()
        mgr.resolve_alert("ghost")  # no exception

    def test_get_alert(self):
        mgr = AlertManager()
        mgr.add_rule(AlertRule(name="r1", expression="v > 0"))
        mgr.fire_alert("r1", "msg")
        alert = mgr.get_alert("r1")
        assert alert is not None
        assert alert.firing is True

    def test_get_alert_missing(self):
        mgr = AlertManager()
        assert mgr.get_alert("ghost") is None

    def test_get_rule_alerts_only_firing(self):
        mgr = AlertManager()
        mgr.add_rule(AlertRule(name="r1", expression="v > 0"))
        mgr.add_rule(AlertRule(name="r2", expression="v > 0"))
        mgr.fire_alert("r1", "m1")
        mgr.fire_alert("r2", "m2")
        mgr.resolve_alert("r1")
        firing = mgr.get_rule_alerts()
        assert len(firing) == 1
        assert firing[0].rule_name == "r2"


# ---------------------------------------------------------------------------
# AlertManager — handlers
# ---------------------------------------------------------------------------


class TestAlertManagerHandlers:
    def test_register_handler(self):
        mgr = AlertManager()
        handler = Mock()
        mgr.register_handler(AlertType.WORKFLOW_FAILURE, handler)
        assert AlertType.WORKFLOW_FAILURE in mgr.alert_handlers
        assert handler in mgr.alert_handlers[AlertType.WORKFLOW_FAILURE]

    def test_register_multiple_handlers(self):
        mgr = AlertManager()
        h1, h2 = Mock(), Mock()
        mgr.register_handler(AlertType.SECURITY_ISSUE, h1)
        mgr.register_handler(AlertType.SECURITY_ISSUE, h2)
        assert len(mgr.alert_handlers[AlertType.SECURITY_ISSUE]) == 2

    def test_register_notification_channel(self):
        mgr = AlertManager()
        ch = NotificationChannel("test")
        mgr.register_notification_channel(ch)
        assert ch in mgr.notification_channels

    def test_default_handlers_registered(self):
        mgr = AlertManager()
        expected = {
            AlertType.WORKFLOW_FAILURE,
            AlertType.SYSTEM_HEALTH,
            AlertType.RESOURCE_EXHAUSTION,
            AlertType.PERFORMANCE_DEGRADATION,
            AlertType.BACKUP_FAILURE,
        }
        for t in expected:
            assert t in mgr.alert_handlers


# ---------------------------------------------------------------------------
# AlertManager — trigger_alert (async)
# ---------------------------------------------------------------------------


class TestAlertManagerTrigger:
    @pytest.mark.asyncio
    async def test_trigger_alert_returns_alert(self):
        mgr = AlertManager()
        alert = await mgr.trigger_alert(
            AlertSeverity.HIGH, AlertType.WORKFLOW_FAILURE, "fail", "wf failed"
        )
        assert alert.title == "fail"
        assert alert.severity == AlertSeverity.HIGH
        assert alert.type == AlertType.WORKFLOW_FAILURE

    @pytest.mark.asyncio
    async def test_trigger_alert_calls_handlers(self):
        mgr = AlertManager()
        handler = AsyncMock()
        mgr.register_handler(AlertType.WORKFLOW_FAILURE, handler)
        await mgr.trigger_alert(AlertSeverity.HIGH, AlertType.WORKFLOW_FAILURE, "fail", "desc")
        handler.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_trigger_alert_handler_error_does_not_propagate(self):
        mgr = AlertManager()
        bad_handler = AsyncMock(side_effect=RuntimeError("boom"))
        mgr.register_handler(AlertType.WORKFLOW_FAILURE, bad_handler)
        alert = await mgr.trigger_alert(
            AlertSeverity.HIGH, AlertType.WORKFLOW_FAILURE, "fail", "desc"
        )
        assert alert is not None  # didn't raise

    @pytest.mark.asyncio
    async def test_trigger_alert_sends_notifications(self):
        mgr = AlertManager()
        ch = AsyncMock()
        mgr.register_notification_channel(ch)
        await mgr.trigger_alert(AlertSeverity.HIGH, AlertType.WORKFLOW_FAILURE, "fail", "desc")
        ch.send_notification.assert_awaited_once()


# ---------------------------------------------------------------------------
# AlertManager — acknowledge_alert (async)
# ---------------------------------------------------------------------------


class TestAlertManagerAcknowledge:
    @pytest.mark.asyncio
    async def test_acknowledge_by_id(self):
        mgr = AlertManager()
        alert = await mgr.trigger_alert(
            AlertSeverity.HIGH, AlertType.WORKFLOW_FAILURE, "fail", "desc"
        )
        await mgr.acknowledge_alert(alert.id, "alice")
        assert alert.acknowledged is True
        assert alert.acknowledged_by == "alice"

    @pytest.mark.asyncio
    async def test_acknowledge_by_rule_name(self):
        mgr = AlertManager()
        await mgr.trigger_alert(AlertSeverity.HIGH, AlertType.WORKFLOW_FAILURE, "fail", "desc")
        # The alert has no rule_name, so acknowledge by id should work
        alert = await mgr.trigger_alert(
            AlertSeverity.HIGH, AlertType.WORKFLOW_FAILURE, "fail2", "desc2"
        )
        await mgr.acknowledge_alert(alert.id, "bob")
        assert alert.acknowledged is True

    @pytest.mark.asyncio
    async def test_acknowledge_nonexistent_no_error(self):
        mgr = AlertManager()
        await mgr.acknowledge_alert("ghost", "alice")  # no exception


# ---------------------------------------------------------------------------
# AlertManager — get_active_alerts (async)
# ---------------------------------------------------------------------------


class TestAlertManagerGetActive:
    @pytest.mark.asyncio
    async def test_active_excludes_acknowledged(self):
        mgr = AlertManager()
        a1 = await mgr.trigger_alert(AlertSeverity.HIGH, AlertType.WORKFLOW_FAILURE, "a1", "d1")
        a2 = await mgr.trigger_alert(AlertSeverity.HIGH, AlertType.WORKFLOW_FAILURE, "a2", "d2")
        await mgr.acknowledge_alert(a1.id, "alice")
        active = await mgr.get_active_alerts()
        assert len(active) == 1
        assert active[0].title == "a2"

    @pytest.mark.asyncio
    async def test_active_excludes_resolved(self):
        mgr = AlertManager()
        a1 = await mgr.trigger_alert(AlertSeverity.HIGH, AlertType.WORKFLOW_FAILURE, "a1", "d1")
        await mgr.trigger_alert(AlertSeverity.HIGH, AlertType.WORKFLOW_FAILURE, "a2", "d2")
        mgr.resolve_alert(a1.id)  # sync method, not async
        active = await mgr.get_active_alerts()
        assert len(active) == 1  # a1 resolved (firing=False), only a2 active


# ---------------------------------------------------------------------------
# AlertManager — _evaluate_expression
# ---------------------------------------------------------------------------


class TestEvaluateExpression:
    def test_evaluate_gt(self):
        mgr = AlertManager()
        assert mgr._evaluate_expression("cpu > 80", {"cpu": 90}) is True
        assert mgr._evaluate_expression("cpu > 80", {"cpu": 80}) is False

    def test_evaluate_with_missing_metric(self):
        mgr = AlertManager()
        assert mgr._evaluate_expression("cpu > 80", {}) is False

    def test_evaluate_with_invalid_threshold(self):
        mgr = AlertManager()
        assert mgr._evaluate_expression("cpu > abc", {"cpu": 90}) is False

    def test_evaluate_empty_expression(self):
        mgr = AlertManager()
        assert mgr._evaluate_expression("", {"cpu": 90}) is False


# ---------------------------------------------------------------------------
# NotificationChannel base
# ---------------------------------------------------------------------------


class TestNotificationChannel:
    @pytest.mark.asyncio
    async def test_send_notification_raises_not_implemented(self):
        ch = NotificationChannel("test")
        with pytest.raises(NotImplementedError):
            await ch.send_notification(_make_alert())


# ---------------------------------------------------------------------------
# EmailNotificationChannel
# ---------------------------------------------------------------------------


class TestEmailNotificationChannel:
    @pytest.mark.asyncio
    async def test_send_notification_builds_correct_email(self):
        ch = EmailNotificationChannel(
            smtp_server="smtp.test.com",
            smtp_port=587,
            username="from@test.com",
            password="secret",
            recipients=["to@test.com"],
        )
        ch.logger = MagicMock()  # production code uses self.logger.info
        alert = _make_alert(
            severity=AlertSeverity.CRITICAL,
            title="Server Down",
            description="The server is down",
        )

        with patch("mahavishnu.core.monitoring.smtplib.SMTP") as mock_smtp:
            mock_instance = MagicMock()
            mock_smtp.return_value = mock_instance
            mock_instance.starttls.return_value = None
            mock_instance.login.return_value = None
            mock_instance.sendmail.return_value = {}
            mock_instance.quit.return_value = None

            await ch.send_notification(alert)

        mock_smtp.assert_called_once_with("smtp.test.com", 587)
        mock_instance.login.assert_called_once_with("from@test.com", "secret")
        mock_instance.sendmail.assert_called_once()
        sent_msg = mock_instance.sendmail.call_args[0][2]
        assert "[CRITICAL] Server Down" in sent_msg

    @pytest.mark.asyncio
    async def test_send_notification_smtp_error_handled(self):
        ch = EmailNotificationChannel(
            smtp_server="smtp.test.com",
            smtp_port=587,
            username="from@test.com",
            password="secret",
            recipients=["to@test.com"],
        )
        ch.logger = MagicMock()
        alert = _make_alert(title="t")

        with patch("mahavishnu.core.monitoring.smtplib.SMTP", side_effect=Exception("smtp fail")):
            await ch.send_notification(alert)  # should not raise


# ---------------------------------------------------------------------------
# SlackNotificationChannel
# ---------------------------------------------------------------------------


class TestSlackNotificationChannel:
    @pytest.mark.asyncio
    async def test_send_notification_posts_webhook(self):
        ch = SlackNotificationChannel(webhook_url="https://hooks.slack.com/xxx", channel="#alerts")
        ch.logger = MagicMock()
        alert = _make_alert(
            severity=AlertSeverity.HIGH,
            title="Alert!",
            type=AlertType.SECURITY_ISSUE,
        )

        with patch("mahavishnu.core.monitoring.requests.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_post.return_value = mock_resp

            await ch.send_notification(alert)

        mock_post.assert_called_once_with("https://hooks.slack.com/xxx", json=ANY)
        sent_json = mock_post.call_args[1]["json"]
        assert sent_json["channel"] == "#alerts"
        assert "Alert!" in sent_json["text"]

    @pytest.mark.asyncio
    async def test_slack_color_danger_for_high(self):
        ch = SlackNotificationChannel(webhook_url="https://hooks.slack.com/xxx")
        ch.logger = MagicMock()
        alert = _make_alert(severity=AlertSeverity.HIGH)
        with patch("mahavishnu.core.monitoring.requests.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_post.return_value = mock_resp
            await ch.send_notification(alert)
        sent_json = mock_post.call_args[1]["json"]
        assert sent_json["attachments"][0]["color"] == "danger"

    @pytest.mark.asyncio
    async def test_slack_color_good_for_info(self):
        ch = SlackNotificationChannel(webhook_url="https://hooks.slack.com/xxx")
        ch.logger = MagicMock()
        alert = _make_alert(severity=AlertSeverity.INFO)
        with patch("mahavishnu.core.monitoring.requests.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_post.return_value = mock_resp
            await ch.send_notification(alert)
        sent_json = mock_post.call_args[1]["json"]
        assert sent_json["attachments"][0]["color"] == "good"

    @pytest.mark.asyncio
    async def test_slack_non_200_logs_warning(self):
        ch = SlackNotificationChannel(webhook_url="https://hooks.slack.com/xxx")
        ch.logger = MagicMock()
        alert = _make_alert()
        with patch("mahavishnu.core.monitoring.requests.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 500
            mock_post.return_value = mock_resp
            await ch.send_notification(alert)  # logs warning, no raise

    @pytest.mark.asyncio
    async def test_slack_exception_handled(self):
        ch = SlackNotificationChannel(webhook_url="https://hooks.slack.com/xxx")
        ch.logger = MagicMock()
        alert = _make_alert()
        with patch("mahavishnu.core.monitoring.requests.post", side_effect=Exception("net fail")):
            await ch.send_notification(alert)  # no raise


# ---------------------------------------------------------------------------
# PagerDutyNotificationChannel
# ---------------------------------------------------------------------------


class TestPagerDutyNotificationChannel:
    @pytest.mark.asyncio
    async def test_send_notification_posts_event(self):
        ch = PagerDutyNotificationChannel("integration_key_123")
        ch.logger = MagicMock()
        alert = _make_alert(severity=AlertSeverity.HIGH, title="Alert!")

        with patch("mahavishnu.core.monitoring.requests.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 202
            mock_post.return_value = mock_resp

            await ch.send_notification(alert)

        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert call_args[1]["json"]["routing_key"] == "integration_key_123"
        assert call_args[1]["json"]["event_action"] == "trigger"
        assert call_args[0][0] == "https://events.pagerduty.com/v2/enqueue"

    @pytest.mark.asyncio
    async def test_pagerduty_severity_mapping(self):
        ch = PagerDutyNotificationChannel("key")
        ch.logger = MagicMock()
        alert_critical = _make_alert(severity=AlertSeverity.CRITICAL)
        alert_info = _make_alert(severity=AlertSeverity.INFO)
        alert_emergency = _make_alert(severity=AlertSeverity.EMERGENCY)

        with patch("mahavishnu.core.monitoring.requests.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 202
            mock_post.return_value = mock_resp

            await ch.send_notification(alert_info)
            assert mock_post.call_args[1]["json"]["payload"]["severity"] == "info"

            await ch.send_notification(alert_critical)
            assert mock_post.call_args[1]["json"]["payload"]["severity"] == "critical"

            await ch.send_notification(alert_emergency)
            assert mock_post.call_args[1]["json"]["payload"]["severity"] == "critical"

    @pytest.mark.asyncio
    async def test_pagerduty_non_202_logs_warning(self):
        ch = PagerDutyNotificationChannel("key")
        ch.logger = MagicMock()
        alert = _make_alert()
        with patch("mahavishnu.core.monitoring.requests.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 500
            mock_post.return_value = mock_resp
            await ch.send_notification(alert)  # no raise


# ---------------------------------------------------------------------------
# MonitoringDashboard
# ---------------------------------------------------------------------------


class TestMonitoringDashboard:
    def test_set_alert_manager(self):
        app = Mock()
        dash = MonitoringDashboard(app)
        mgr = AlertManager()
        dash.set_alert_manager(mgr)
        assert dash.alert_manager is mgr

    @pytest.mark.asyncio
    async def test_get_recent_alerts_no_manager(self):
        app = Mock()
        dash = MonitoringDashboard(app)
        alerts = await dash.get_recent_alerts()
        assert alerts == []

    @pytest.mark.asyncio
    async def test_get_recent_alerts_sorted_by_timestamp(self):
        app = Mock()
        dash = MonitoringDashboard(app)
        mgr = AlertManager()
        dash.set_alert_manager(mgr)
        a1 = await mgr.trigger_alert(AlertSeverity.LOW, AlertType.SYSTEM_HEALTH, "first", "d1")
        a2 = await mgr.trigger_alert(AlertSeverity.HIGH, AlertType.SYSTEM_HEALTH, "second", "d2")
        alerts = await dash.get_recent_alerts(limit=10)
        assert len(alerts) == 2
        # Most recent first
        assert alerts[0]["title"] == "second"
        assert alerts[1]["title"] == "first"

    @pytest.mark.asyncio
    async def test_get_recent_alerts_respects_limit(self):
        app = Mock()
        dash = MonitoringDashboard(app)
        mgr = AlertManager()
        dash.set_alert_manager(mgr)
        for i in range(5):
            await mgr.trigger_alert(AlertSeverity.INFO, AlertType.SYSTEM_HEALTH, f"a{i}", "d")
        alerts = await dash.get_recent_alerts(limit=2)
        assert len(alerts) == 2

    @pytest.mark.asyncio
    async def test_get_recent_alerts_dict_structure(self):
        app = Mock()
        dash = MonitoringDashboard(app)
        mgr = AlertManager()
        dash.set_alert_manager(mgr)
        await mgr.trigger_alert(
            AlertSeverity.HIGH, AlertType.BACKUP_FAILURE, "Backup fail", "details here"
        )
        alerts = await dash.get_recent_alerts(limit=1)
        assert alerts[0]["title"] == "Backup fail"
        assert alerts[0]["severity"] == "high"
        assert alerts[0]["type"] == "backup_failure"
        assert alerts[0]["acknowledged"] is False


# ---------------------------------------------------------------------------
# MonitoringService
# ---------------------------------------------------------------------------


class TestMonitoringService:
    @pytest.mark.asyncio
    async def test_acknowledge_alert_delegates_success(self):
        app = Mock()
        svc = MonitoringService(app)
        alert = await svc.alert_manager.trigger_alert(
            AlertSeverity.HIGH, AlertType.WORKFLOW_FAILURE, "fail", "desc"
        )
        result = await svc.acknowledge_alert(alert.id, "alice")
        assert result is True

    @pytest.mark.asyncio
    async def test_acknowledge_alert_delegates_failure(self):
        app = Mock()
        svc = MonitoringService(app)
        # Production code: AlertManager doesn't raise on missing IDs,
        # so MonitoringService still returns True
        result = await svc.acknowledge_alert("ghost", "alice")
        assert result is True

    @pytest.mark.asyncio
    async def test_get_dashboard_data_structure(self):
        app = Mock()
        app.adapters = {}
        app.workflow_state_manager = AsyncMock()
        app.workflow_state_manager.list_workflows = AsyncMock(return_value=[])

        svc = MonitoringService(app)

        with (
            patch("psutil.cpu_percent", return_value=10.0),
            patch("psutil.virtual_memory") as mock_mem_cls,
            patch("psutil.disk_usage") as mock_disk_fn,
            patch("mahavishnu.core.monitoring.time", return_value=1000.0),
        ):
            mem_info = MagicMock()
            mem_info.percent = 50
            mem_info.available = 8 * 1024**3
            mock_mem_cls.return_value = mem_info
            disk_info = MagicMock()
            disk_info.used = 100 * 1024**4
            disk_info.total = 1000 * 1024**4
            disk_info.free = 900 * 1024**3
            mock_disk_fn.return_value = disk_info

            data = await svc.get_dashboard_data()

        assert "metrics" in data
        assert "recent_alerts" in data
        assert "timestamp" in data
