"""Tenant context packs: per-tenant context bundles, versioned (Spec #9).

Tenant-scoped context packs allow multi-tenant MCP deployments where each
tenant (operator/customer) gets its own context bundle that is loaded
per-request and injected into agent prompts.

This module ships:

- ``TenantContextPack`` frozen dataclass (versioned, append-only by design)
- ``TenantContextPublisher`` protocol (interface)
- ``InMemoryTenantContextPublisher`` implementation for tests + dev
- ``DharaTenantContextPublisher`` stub that raises ``NotImplementedError``
- ``get_default_tenant_id`` resolver (env: ``MAHAVISHNU_DEFAULT_TENANT``)

The Dhara-backed implementation is a follow-up that lands with Workstream C
(substrate: HTTP CRUD endpoint ``/tenants/<id>/context-versions`` is blocked).
The stub keeps the Dhara dependency documented and exercises the call site
at import time.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable


DEFAULT_TENANT_ENV_VAR = "MAHAVISHNU_DEFAULT_TENANT"
DEFAULT_TENANT_ID = "default"


@dataclass(frozen=True)
class TenantContextPack:
    """A single versioned context pack for a tenant.

    Frozen + append-only by design (Spec #9 G3: history is preserved,
    no edits, no deletes). ``content_hash`` is the SHA-256 of the body
    at the moment of publication.

    Mirrors the Dhara ``tenant_context_versions`` table schema (Spec #9).
    """

    tenant_id: str
    version: int
    content_hash: str
    body: str
    published_at: datetime
    published_by: str


def compute_content_hash(body: str) -> str:
    """Compute the SHA-256 content hash for a tenant context body.

    Stable across processes and platforms so callers can detect body
    changes deterministically.
    """
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


@runtime_checkable
class TenantContextPublisher(Protocol):
    """Interface for publishing tenant context packs.

    The Dhara implementation will satisfy this protocol by inserting rows
    into ``tenant_context_versions`` via the HTTP CRUD endpoint
    ``/tenants/<tenant_id>/context-versions``. Until then,
    ``InMemoryTenantContextPublisher`` is the production reference
    implementation for tests and local dev.
    """

    def publish(
        self,
        tenant_id: str,
        body: str,
        published_by: str,
    ) -> TenantContextPack:
        """Publish a new context pack version for a tenant.

        Returns the published :class:`TenantContextPack` with the
        incremented version number, deterministic content hash, and
        UTC ``published_at`` timestamp.
        """
        ...


class InMemoryTenantContextPublisher:
    """In-memory implementation of :class:`TenantContextPublisher`.

    Suitable for unit tests, local development, and the dhara-still-pending
    Workstream C. Per-tenant version counters are tracked in a dict so
    version sequencing is preserved within a single process instance.
    """

    def __init__(self) -> None:
        self._version_counters: dict[str, int] = {}

    def publish(
        self,
        tenant_id: str,
        body: str,
        published_by: str,
    ) -> TenantContextPack:
        next_version = self._version_counters.get(tenant_id, 0) + 1
        self._version_counters[tenant_id] = next_version
        return TenantContextPack(
            tenant_id=tenant_id,
            version=next_version,
            content_hash=compute_content_hash(body),
            body=body,
            published_at=datetime.now(UTC),
            published_by=published_by,
        )


class DharaTenantContextPublisher:
    """Stub for the Dhara-backed implementation.

    The Dhara HTTP CRUD endpoint ``/tenants/<tenant_id>/context-versions``
    is the durable backing store for tenant context packs. Until the
    Dhara substrate lands (Workstream C), this stub raises
    ``NotImplementedError`` so the call site is documented and import-time
    visible, but no Dhara write occurs.

    TODO(Workstream C - substrate): replace ``publish`` with a Dhara HTTP
    POST to ``/tenants/<tenant_id>/context-versions`` using the payload:

        {
            "version": <int>,
            "content_hash": <sha256>,
            "body": <str>,
            "published_by": <str>,
            "published_at": <iso8601>
        }

    The follow-up must also keep the append-only invariant by routing any
    DELETE / UPDATE through the migration runner's deny list.
    """

    def publish(
        self,
        tenant_id: str,
        body: str,
        published_by: str,
    ) -> TenantContextPack:
        raise NotImplementedError(
            "DharaTenantContextPublisher is a stub. The Dhara-backed "
            "/tenants/<id>/context-versions endpoint is blocked on "
            "Workstream C (substrate). Use InMemoryTenantContextPublisher "
            "until then. "
            "TODO(Workstream C): wire HTTP POST to "
            "/tenants/<id>/context-versions."
        )


def get_default_tenant_id() -> str:
    """Resolve the default tenant id from ``MAHAVISHNU_DEFAULT_TENANT``.

    Falls back to ``"default"`` when the env var is unset or empty. The
    default tenant lets deployments run a single-tenant configuration
    without forcing every caller to set ``X-Tenant-Id``.
    """
    value = os.environ.get(DEFAULT_TENANT_ENV_VAR, "").strip()
    if not value:
        return DEFAULT_TENANT_ID
    return value


# ---------------------------------------------------------------------------
# HTTP CRUD call stub (TODO Workstream C)
# ---------------------------------------------------------------------------
#
# The HTTP CRUD entry point is intentionally a stub function (not a method
# on a class) so that downstream code can call a single entry point without
# committing to a specific publisher implementation. When the substrate
# lands, the body becomes a POST to ``/tenants/<tenant_id>/context-versions``
# via ``httpx.AsyncClient``:
#
#     import httpx
#     async with httpx.AsyncClient(
#         base_url=os.environ.get("MAHAVISHNU_DHARA_URL", "http://localhost:8683"),
#         timeout=httpx.Timeout(5.0),
#     ) as client:
#         resp = await client.post(
#             f"/tenants/{tenant_id}/context-versions",
#             json={
#                 "version": pack.version,
#                 "content_hash": pack.content_hash,
#                 "body": pack.body,
#                 "published_by": pack.published_by,
#                 "published_at": pack.published_at.isoformat(),
#             },
#         )
#         resp.raise_for_status()
#
# Until then, this call site is a TODO marker that imports cleanly and
# fails loudly if anything routes through it accidentally.


def publish_via_http(
    tenant_id: str,
    pack: TenantContextPack,
) -> None:
    """HTTP CRUD stub for ``/tenants/<tenant_id>/context-versions``.

    TODO(Workstream C - substrate): replace with a real httpx POST to
    ``/tenants/<tenant_id>/context-versions`` once the Dhara HTTP CRUD
    endpoint ships. For now, raise so accidental wiring is caught at
    runtime.
    """
    raise NotImplementedError(
        "publish_via_http() is a stub. TODO(Workstream C - substrate): "
        "wire the HTTP POST to /tenants/<id>/context-versions. "
        f"Would have published: tenant_id={tenant_id!r}, pack={pack}"
    )


__all__ = [
    "DEFAULT_TENANT_ENV_VAR",
    "DEFAULT_TENANT_ID",
    "DharaTenantContextPublisher",
    "InMemoryTenantContextPublisher",
    "TenantContextPack",
    "TenantContextPublisher",
    "compute_content_hash",
    "get_default_tenant_id",
    "publish_via_http",
]