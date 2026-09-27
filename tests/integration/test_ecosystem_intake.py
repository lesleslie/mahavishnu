"""Integration tests for the ecosystem intake endpoint (C-10, REQ-016).

Per round-4 simplification: 4 happy/sad path tests + 1 unit test for
``DataSanitizeAction`` shape.
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest
from fastapi.testclient import TestClient

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture
def ecosystem_intake_test_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """Yield a FastAPI TestClient over the durable receiver app.

    The ecosystem_intake router is mounted inside the receiver's FastAPI
    app (see ``mahavishnu/webhooks/receiver.py``), so tests drive it via
    the receiver's app instance. The test enables the intake via the
    ``webhook_intake.enabled`` toggle and clears ``_capture_singleton``
    on each test to keep assertions isolated.
    """
    from mahavishnu.core.config import get_settings
    from mahavishnu.core.events import publisher as publisher_mod
    from mahavishnu.webhooks.receiver import app as receiver_app

    settings = get_settings()
    monkeypatch.setattr(settings.webhook_intake, "enabled", True)
    monkeypatch.setattr(
        settings.webhook_intake, "max_payload_size_bytes", 1_048_576
    )
    monkeypatch.setattr(settings.webhook_intake, "allowed_sources", frozenset())
    monkeypatch.setattr(publisher_mod, "_capture_singleton", [])

    with TestClient(receiver_app) as client:
        yield client


@pytest.fixture
def safe_publisher_monkeypatch(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force ``safe_publish`` to record into ``_capture_singleton``.

    Replaces ``mahavishnu.webhooks.ecosystem_intake.safe_publish`` with a
    stub that pushes the envelope into the publisher module's capture
    list and returns ``True``. ``TestClient`` runs the FastAPI app in a
    sync thread, so the stub uses a sync helper that appends to the list.
    """
    from mahavishnu.core.events import publisher as publisher_mod
    from mahavishnu.webhooks import ecosystem_intake

    captured: list[dict[str, Any]] = []
    monkeypatch.setattr(publisher_mod, "_capture_singleton", captured)

    async def _fake_publish(envelope: Any) -> bool:
        # EventEnvelope is a msgspec.Struct; project to dict for assertions.
        try:
            captured.append(envelope.to_dict())  # type: ignore[attr-defined]
        except AttributeError:
            captured.append({
                "event_type": getattr(envelope, "event_type", None),
                "source": getattr(envelope, "source", None),
                "payload": getattr(envelope, "payload", {}),
                "metadata": getattr(envelope, "metadata", {}),
            })
        return True

    monkeypatch.setattr(ecosystem_intake, "safe_publish", _fake_publish)
    # Also keep the publisher module-level reference in sync so the
    # stub is what the route handler actually calls.
    monkeypatch.setattr(publisher_mod, "safe_publish", _fake_publish)


@pytest.mark.req(["REQ-016"])
class TestAllowedSource202:
    async def test_post_returns_202_when_source_allowed(
        self,
        ecosystem_intake_test_client: TestClient,
        safe_publisher_monkeypatch: None,
    ) -> None:
        response = ecosystem_intake_test_client.post(
            "/webhooks/ecosystem/git-monitor",
            json={"key": "value", "Authorization": "Bearer leak"},
        )
        assert response.status_code == 202
        assert response.json()["status"] == "accepted"


@pytest.mark.req(["REQ-016"])
class TestDisallowedSource404:
    async def test_post_returns_404_when_source_not_in_allowlist(
        self, ecosystem_intake_test_client: TestClient
    ) -> None:
        response = ecosystem_intake_test_client.post(
            "/webhooks/ecosystem/external-attacker",
            json={"data": "x"},
        )
        assert response.status_code == 404
        assert response.json()["status"] == "not_found"


@pytest.mark.req(["REQ-016"])
class TestOversizedPayload413:
    async def test_post_returns_413_when_payload_too_large(
        self,
        ecosystem_intake_test_client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from mahavishnu.core.config import get_settings

        settings = get_settings()
        monkeypatch.setattr(
            settings.webhook_intake, "max_payload_size_bytes", 100
        )
        response = ecosystem_intake_test_client.post(
            "/webhooks/ecosystem/git-monitor",
            content=b"x" * 200,
            headers={"Content-Type": "application/octet-stream"},
        )
        assert response.status_code == 413
        assert response.json()["status"] == "too_large"


@pytest.mark.req(["REQ-016"])
class TestSanitizationStripsAuth:
    async def test_authorization_field_is_masked(
        self,
        ecosystem_intake_test_client: TestClient,
        safe_publisher_monkeypatch: None,
    ) -> None:
        from mahavishnu.core.events import publisher as publisher_mod

        response = ecosystem_intake_test_client.post(
            "/webhooks/ecosystem/git-monitor",
            json={"Authorization": "Bearer SECRET_TOKEN"},
        )
        assert response.status_code == 202
        assert len(publisher_mod._capture_singleton) == 1
        envelope = publisher_mod._capture_singleton[0]
        # Round-8 fix: payload.data is a dict (not a sanitized string),
        # so consumers can read payload["data"]["pr_url"] without
        # AttributeError. Verify the mask replaced the bearer token.
        sanitized_data = envelope["payload"]["data"]
        # Mask uses the action's default value ("***"); the bearer token
        # itself must NOT appear in the sanitized data.
        serialized = json.dumps(sanitized_data, default=str)
        assert "SECRET_TOKEN" not in serialized
        assert "***" in serialized


@pytest.mark.req(["REQ-016"])
class TestDisabledWhenConfigured:
    async def test_post_returns_503_when_intake_disabled(
        self,
        ecosystem_intake_test_client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from mahavishnu.core.config import get_settings

        settings = get_settings()
        monkeypatch.setattr(settings.webhook_intake, "enabled", False)
        response = ecosystem_intake_test_client.post(
            "/webhooks/ecosystem/git-monitor",
            json={"key": "value"},
        )
        assert response.status_code == 503
        assert response.json()["status"] == "disabled"


@pytest.mark.req(["REQ-016"])
class TestDataSanitizeActionUnit:
    async def test_action_payload_shape(self) -> None:
        """Verify the Oneiric action payload shape matches the C-10 contract.

        The endpoint passes a dict to ``data`` and a list to
        ``mask_fields``. ``DataSanitizeAction`` must accept the dict and
        return a dict with ``status="sanitized"`` and ``data`` set to the
        sanitized record.
        """
        from oneiric.actions.data import DataSanitizeAction

        result = await DataSanitizeAction().execute({
            "data": {
                "Authorization": "Bearer ABC",
                "key": "xyz",
                "harmless": "keep-me",
            },
            "mask_fields": ["Authorization", "key"],
        })
        assert result["status"] == "sanitized"
        assert "data" in result
        # Masked fields are replaced; the bearer token must not survive.
        assert result["data"]["Authorization"] != "Bearer ABC"
        assert result["data"]["key"] != "xyz"
        # Non-masked fields pass through.
        assert result["data"]["harmless"] == "keep-me"


@pytest.mark.req(["REQ-016"])
class TestRouteRegistration:
    def test_route_registered_on_receiver_app(self) -> None:
        """Sanity: ``/webhooks/ecosystem/{source_name}`` exists on the receiver.

        Inspects the OpenAPI schema rather than the raw routes list —
        Starlette's ``_IncludedRouter`` wrapper hides nested routes from
        ``app.routes`` (each is reported with ``path=None``). The OpenAPI
        schema is the canonical public surface for route registration.

        Guards against accidental router-removal during refactors.
        """
        from mahavishnu.webhooks.receiver import app as receiver_app

        schema = receiver_app.openapi()
        paths = schema.get("paths", {})
        assert "/webhooks/ecosystem/{source_name}" in paths
        methods = paths["/webhooks/ecosystem/{source_name}"]
        assert "post" in methods
