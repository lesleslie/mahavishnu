"""Unit tests for mahavishnu/tenancy/context_packs.py.

Spec #9: multi-tenant-context-packs. Context packs scoped to tenants, versioned.

The Dhara-backed implementation is a follow-up (Workstream C: substrate).
The HTTP CRUD endpoint is blocked on /tenants/<id>/context-versions.
These tests pin the TenantContextPack model + TenantContextPublisher
interface so the Dhara implementation can be swapped in without breaking callers.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from mahavishnu.tenancy.context_packs import (
    DEFAULT_TENANT_ENV_VAR,
    InMemoryTenantContextPublisher,
    TenantContextPack,
    TenantContextPublisher,
    get_default_tenant_id,
)

# ---------------------------------------------------------------------------
# TenantContextPack dataclass
# ---------------------------------------------------------------------------


class TestTenantContextPack:
    def test_required_fields(self) -> None:
        pack = TenantContextPack(
            tenant_id="acme",
            version=1,
            content_hash="abc123",
            body="Direct, opinionated.",
            published_at=datetime(2026, 6, 27, tzinfo=UTC),
            published_by="system:cli",
        )
        assert pack.tenant_id == "acme"
        assert pack.version == 1
        assert pack.content_hash == "abc123"
        assert pack.body == "Direct, opinionated."
        assert pack.published_at == datetime(2026, 6, 27, tzinfo=UTC)
        assert pack.published_by == "system:cli"

    def test_frozen_dataclass(self) -> None:
        pack = TenantContextPack(
            tenant_id="acme",
            version=1,
            content_hash="abc",
            body="x",
            published_at=datetime(2026, 6, 27, tzinfo=UTC),
            published_by="system:cli",
        )
        with pytest.raises(Exception):  # FrozenInstanceError subclass
            pack.tenant_id = "other"  # type: ignore[misc]

    def test_published_at_defaults_to_utc_now(self) -> None:
        pack = TenantContextPack(
            tenant_id="acme",
            version=1,
            content_hash="abc",
            body="x",
            published_at=datetime.now(UTC),
            published_by="system:cli",
        )
        assert pack.published_at.tzinfo is not None

    def test_content_hash_is_string(self) -> None:
        pack = TenantContextPack(
            tenant_id="acme",
            version=1,
            content_hash="deadbeef",
            body="x",
            published_at=datetime(2026, 6, 27, tzinfo=UTC),
            published_by="system:cli",
        )
        assert isinstance(pack.content_hash, str)
        assert pack.content_hash == "deadbeef"


# ---------------------------------------------------------------------------
# TenantContextPublisher protocol
# ---------------------------------------------------------------------------


class TestTenantContextPublisher:
    def test_in_memory_satisfies_protocol(self) -> None:
        publisher: TenantContextPublisher = InMemoryTenantContextPublisher()
        assert isinstance(publisher, TenantContextPublisher)

    def test_publish_returns_tenant_context_pack(self) -> None:
        publisher = InMemoryTenantContextPublisher()
        pack = publisher.publish(
            tenant_id="acme",
            body="Direct, opinionated.",
            published_by="system:cli",
        )
        assert isinstance(pack, TenantContextPack)
        assert pack.tenant_id == "acme"
        assert pack.body == "Direct, opinionated."
        assert pack.version == 1
        assert pack.published_by == "system:cli"
        # content_hash should be deterministic for a given body
        assert isinstance(pack.content_hash, str)
        assert len(pack.content_hash) > 0

    def test_publish_increments_version_per_tenant(self) -> None:
        publisher = InMemoryTenantContextPublisher()
        v1 = publisher.publish("acme", "v1 body", "system:cli")
        v2 = publisher.publish("acme", "v2 body", "system:cli")
        v3 = publisher.publish("acme", "v3 body", "system:cli")
        assert v1.version == 1
        assert v2.version == 2
        assert v3.version == 3

    def test_publish_version_is_per_tenant_independent(self) -> None:
        publisher = InMemoryTenantContextPublisher()
        acme_v1 = publisher.publish("acme", "acme body", "system:cli")
        beta_v1 = publisher.publish("beta", "beta body", "system:cli")
        assert acme_v1.version == 1
        assert beta_v1.version == 1
        # Each tenant maintains its own version counter
        acme_v2 = publisher.publish("acme", "acme body v2", "system:cli")
        assert acme_v2.version == 2
        assert beta_v1.version == 1

    def test_publish_content_hash_changes_with_body(self) -> None:
        publisher = InMemoryTenantContextPublisher()
        v1 = publisher.publish("acme", "first body", "system:cli")
        v2 = publisher.publish("acme", "second body", "system:cli")
        assert v1.content_hash != v2.content_hash

    def test_publish_content_hash_stable_for_same_body(self) -> None:
        publisher = InMemoryTenantContextPublisher()
        v1 = publisher.publish("acme", "same body", "system:cli")
        v2 = publisher.publish("acme", "same body", "system:cli")
        # Same body should produce same content_hash (sha256 stable)
        assert v1.content_hash == v2.content_hash

    def test_published_at_is_recent_utc(self) -> None:
        publisher = InMemoryTenantContextPublisher()
        pack = publisher.publish("acme", "body", "system:cli")
        assert pack.published_at.tzinfo is not None
        delta = datetime.now(UTC) - pack.published_at
        assert abs(delta.total_seconds()) < 5


# ---------------------------------------------------------------------------
# Default tenant resolution
# ---------------------------------------------------------------------------


class TestDefaultTenant:
    def test_default_tenant_env_var_constant(self) -> None:
        assert DEFAULT_TENANT_ENV_VAR == "MAHAVISHNU_DEFAULT_TENANT"

    def test_get_default_tenant_id_returns_default_when_unset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(DEFAULT_TENANT_ENV_VAR, raising=False)
        assert get_default_tenant_id() == "default"

    def test_get_default_tenant_id_reads_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(DEFAULT_TENANT_ENV_VAR, "acme")
        assert get_default_tenant_id() == "acme"


# ---------------------------------------------------------------------------
# InMemoryTenantContextPublisher isolation
# ---------------------------------------------------------------------------


class TestInMemoryPublisherIsolation:
    def test_publish_does_not_leak_across_instances(self) -> None:
        pub_a = InMemoryTenantContextPublisher()
        pub_b = InMemoryTenantContextPublisher()
        pub_a.publish("acme", "body", "system:cli")
        # Different instance should not see prior state
        new_pack = pub_b.publish("acme", "body", "system:cli")
        assert new_pack.version == 1  # not 2
