"""Durable ecosystem state primitives for the Bodai control plane (Phase 3).

Phase 3 of the MCP MCP retirement
(``docs/plans/2026-09-16-mcp-mcp-retirement-plan.md``) ports the
ecosystem-service / event primitives from MCP's substrate into
Mahavishnu so sibling Bodai components can resolve services and read
events without depending on MCP's MCP surface.

Mirrors the contract of MCP's :class:`AsyncEcosystemStateStore`
(see ``mcp/mcp/ecosystem_state.py``) so call-site signatures stay
field-for-field identical. The persistence layer, however, is different:
MCP stores services and events inside a single MCP root dict via
``PersistentDict`` / ``PersistentList``; Mahavishnu persists each record
under its own substrate key so siblings can read it via the substrate
without owning a reference to the MCP root.

Persistence model
-----------------
* Service record: ``ecosystem-services/{service_id}/`` — the validated
  :class:`EcosystemService` Struct, serialized via ``msgspec.to_builtins``.
* Event record: ``ecosystem-events/{event_id}/`` — the validated
  :class:`EcosystemEvent` Struct.
* Service index: ``ecosystem-services-index/`` — JSON list of ``{"service_id",
  "updated_at", "status", "service_type", "capabilities"}`` entries. The
  index is the substrate-level mirror of MCP's ``ecosystem_services``
  ``PersistentDict``; it is rebuilt on every upsert.
* Event index: ``ecosystem-events-index/`` — JSON list of ``{"event_id",
  "timestamp", "event_type", "source_service", "related_service"}`` entries.

The substrate-compat gate (``mcp_calltime``) keeps the substrate an
optional runtime dep — when unbound, the leaf functions return
``None`` and the writers log a structured warning. The async store
itself does not raise on substrate unavailability; it follows the
existing ``webhook_replay`` / ``outcome_writer`` pattern.

Note: pruning is intentionally in-memory on the index only. The substrate
itself owns durability and TTL; expired records will eventually fall out
of the index on the next upsert/record cycle, but the actual deletion
of stale substrate keys is out of scope (mirrors MCP's
``_prune_events`` behavior, which only mutates the in-memory list).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
import uuid

import msgspec
from oneiric.core.logging import get_logger

from mahavishnu.core._mcp_substrate_compat import mcp_calltime
from mahavishnu.core.models.persistence import EcosystemEvent, EcosystemService

logger = get_logger(__name__)

# Service registry schema version — bumped alongside ``EcosystemService.schema_version``
# when the field set changes incompatibly.
REGISTRY_SCHEMA_VERSION = 1
EVENT_SCHEMA_VERSION = 1

# Substrate key prefixes. Per the persistence-model comment above, services
# and events each live at their own keyed path; indices sit alongside.
_SERVICES_PREFIX = "ecosystem-services/"
_EVENTS_PREFIX = "ecosystem-events/"
_SERVICES_INDEX_KEY = "ecosystem-services-index/"
_EVENTS_INDEX_KEY = "ecosystem-events-index/"


def _utcnow_iso() -> str:
    """Return the current UTC timestamp as an ISO-8601 string with ``+00:00`` offset."""
    return datetime.now(UTC).isoformat()


def _service_key(service_id: str) -> str:
    """Build the substrate key for a service record."""
    return f"{_SERVICES_PREFIX}{service_id}/"


def _event_key(event_id: str) -> str:
    """Build the substrate key for an event record."""
    return f"{_EVENTS_PREFIX}{event_id}/"


class EventRetention:
    """Retention window for ecosystem events (matches MCP's contract)."""

    def __init__(self, retention_days: int = 30) -> None:
        self.retention_days = retention_days

    def cutoff(self) -> datetime:
        return datetime.now(UTC) - timedelta(days=self.retention_days)


def _parse_iso(ts: str | None) -> datetime | None:
    """Parse an ISO-8601 timestamp into a tz-aware ``datetime``, or ``None``.

    Mirrors MCP's ``datetime.fromisoformat`` call inside ``_prune_events``
    — malformed or missing timestamps fall through as "do not prune".
    """
    if not isinstance(ts, str):
        return None
    try:
        parsed = datetime.fromisoformat(ts)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _load_index(raw: Any, key: str) -> list[dict[str, Any]]:
    """Normalize a substrate ``get`` result into a list-of-dicts index view.

    Returns ``[]`` when the result is ``None`` or malformed. The caller
    has already awaited the substrate ``get`` coroutine; this helper is
    intentionally sync so the async store methods can compose it with
    other awaits without nesting coroutines.
    """
    if raw is None:
        return []
    if not isinstance(raw, (list, tuple)):
        # Malformed index — log and start fresh rather than crashing the writer.
        logger.warning(
            "ecosystem_state_index_malformed",
            extra={"key": key, "type": type(raw).__name__},
        )
        return []
    return list(raw)


class AsyncEcosystemStateStore:
    """Async durable ecosystem state store backed by the Bodai substrate.

    Mirrors :class:`mcp.AsyncEcosystemStateStore` signatures so the
    Phase 3 tool surface stays field-for-field compatible with MCP's
    group_registers wrappers (``mcp_upsert_service``,
    ``mcp_get_service``, etc.).

    The substrate binding is resolved at call time via
    :func:`mahavishnu.core._mcp_substrate_compat.mcp_calltime`.
    When unbound (no host mcp install), all read paths return
    ``None`` / ``[]`` and write paths log a structured warning then
    return the validated payload anyway — callers can still construct
    in-memory views.
    """

    def __init__(self, retention: EventRetention | None = None) -> None:
        self.retention = retention or EventRetention()

    # ------------------------------------------------------------------
    # Service operations
    # ------------------------------------------------------------------

    async def upsert_service_async(
        self,
        service_id: str,
        service_type: str,
        capabilities: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        status: str = "unknown",
        lease_expires_at: str | None = None,
        heartbeat_at: str | None = None,
    ) -> dict[str, Any]:
        """Create or update a durable ecosystem service record.

        Args:
            service_id: Stable primary key for the service.
            service_type: Logical type (e.g. ``"mcp"``, ``"worker_pool"``).
            capabilities: Free-form capability tags. Defaults to ``[]``.
            metadata: Free-form caller metadata. Defaults to ``{}``.
            status: Lifecycle status; free-form string. Defaults to ``"unknown"``.
            lease_expires_at: Optional ISO-8601 lease expiry.
            heartbeat_at: Optional ISO-8601 last-heartbeat timestamp.

        Returns:
            The serialized service record as a dict (via
            :func:`msgspec.to_builtins`). Persists to the substrate when
            ``mcp.put`` is bound; otherwise returns the validated record
            with a structured warning log so the caller still gets a
            well-formed response.
        """
        now = _utcnow_iso()
        # Preserve original ``created_at`` when an upsert is over an existing record.
        get_fn = mcp_calltime("get")
        existing = await get_fn(_service_key(service_id)) if get_fn is not None else None
        created_at = existing.get("created_at") if existing else now

        record_dict: dict[str, Any] = {
            "schema_version": REGISTRY_SCHEMA_VERSION,
            "service_id": service_id,
            "service_type": service_type,
            "capabilities": list(capabilities or []),
            "metadata": dict(metadata or {}),
            "status": status,
            "lease_expires_at": lease_expires_at,
            "heartbeat_at": heartbeat_at or now,
            "created_at": created_at,
            "updated_at": now,
        }

        # Validate via msgspec so persisted payloads match the local schema.
        validated: EcosystemService = msgspec.convert(record_dict, EcosystemService)  # ty: ignore[invalid-assignment]
        builtins: dict[str, Any] = msgspec.to_builtins(validated)

        put = mcp_calltime("put")
        if put is not None:
            put(_service_key(service_id), builtins)
            existing_index = await get_fn(_SERVICES_INDEX_KEY) if get_fn is not None else None
            await self._replace_service_index_entry(
                current_index=_load_index(existing_index, _SERVICES_INDEX_KEY),
                service_id=service_id,
                service_type=service_type,
                capabilities=list(capabilities or []),
                status=status,
                updated_at=now,
            )
        else:
            logger.warning(
                "ecosystem_state_upsert_skipped",
                extra={
                    "reason": "mcp.put_unbound",
                    "service_id": service_id,
                },
            )
        return builtins

    async def _replace_service_index_entry(
        self,
        *,
        current_index: list[dict[str, Any]],
        service_id: str,
        service_type: str,
        capabilities: list[str],
        status: str,
        updated_at: str,
    ) -> None:
        """Replace or insert ``service_id`` in the services index.

        The index is a JSON list under ``ecosystem-services-index/``. Reads
        + writes are linear (substrate has no native list-prefix); the
        expected cardinality is small (one row per registered service).
        The caller awaits ``get_fn`` before invoking this helper so the
        index is already resolved (see ``upsert_service_async``).
        """
        put = mcp_calltime("put")
        if put is None:
            return
        new_entry = {
            "service_id": service_id,
            "service_type": service_type,
            "capabilities": list(capabilities),
            "status": status,
            "updated_at": updated_at,
        }
        # Replace existing entry by service_id, otherwise append.
        out: list[dict[str, Any]] = []
        replaced = False
        for entry in current_index:
            if entry.get("service_id") == service_id:
                out.append(new_entry)
                replaced = True
            else:
                out.append(entry)
        if not replaced:
            out.append(new_entry)
        out.sort(key=lambda e: e.get("service_id", ""))
        put(_SERVICES_INDEX_KEY, out)

    async def get_service_async(self, service_id: str) -> dict[str, Any] | None:
        """Fetch a durable ecosystem service record by ``service_id``.

        Returns ``None`` when the substrate is unbound OR when no record
        exists at the durability key. The returned dict is the raw
        substrate payload normalized via :class:`EcosystemService`.
        """
        get_fn = mcp_calltime("get")
        if get_fn is None:
            logger.warning(
                "ecosystem_state_get_skipped",
                extra={
                    "reason": "mcp.get_unbound",
                    "service_id": service_id,
                },
            )
            return None
        raw = await get_fn(_service_key(service_id))
        if raw is None:
            return None
        return msgspec.to_builtins(msgspec.convert(raw, EcosystemService))  # ty: ignore[invalid-return-type]

    async def list_services_async(
        self,
        service_type: str | None = None,
        capability: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """List durable ecosystem service records with optional filters.

        Filters match the MCP contract: exact ``service_type``,
        ``status``; ``capability`` is a single-tag ``in`` membership
        check (caller cannot OR multiple capabilities).
        """
        get_fn = mcp_calltime("get")
        if get_fn is None:
            logger.warning(
                "ecosystem_state_list_skipped",
                extra={
                    "reason": "mcp.get_unbound",
                    "kind": "services",
                },
            )
            return []

        # Iterate the index; for each match, hydrate the full record so the
        # caller gets the canonical payload, not just the index entry.
        index = _load_index(await get_fn(_SERVICES_INDEX_KEY), _SERVICES_INDEX_KEY)
        results: list[dict[str, Any]] = []
        for entry in index:
            if service_type and entry.get("service_type") != service_type:
                continue
            if status and entry.get("status") != status:
                continue
            if capability and capability not in (entry.get("capabilities") or []):
                continue
            full = await get_fn(_service_key(entry["service_id"]))
            if full is None:
                # Index references a missing record — skip silently rather than crashing.
                continue
            results.append(msgspec.to_builtins(msgspec.convert(full, EcosystemService)))
        results.sort(key=lambda r: r.get("service_id", ""))
        return results

    # ------------------------------------------------------------------
    # Event operations
    # ------------------------------------------------------------------

    async def record_event_async(
        self,
        event_type: str,
        source_service: str,
        payload: dict[str, Any] | None = None,
        related_service: str | None = None,
        timestamp: str | None = None,
    ) -> dict[str, Any]:
        """Append a durable ecosystem event.

        ``event_id`` is derived deterministically from the timestamp +
        source_service + a uuid hex suffix so concurrent writers do not
        collide but readers see a stable ordering by timestamp.
        """
        ts = timestamp or _utcnow_iso()
        event_id = f"{ts}-{source_service}-{uuid.uuid4().hex[:8]}"
        record_dict: dict[str, Any] = {
            "schema_version": EVENT_SCHEMA_VERSION,
            "event_id": event_id,
            "event_type": event_type,
            "source_service": source_service,
            "related_service": related_service,
            "payload": dict(payload or {}),
            "timestamp": ts,
        }
        validated: EcosystemEvent = msgspec.convert(record_dict, EcosystemEvent)  # ty: ignore[invalid-assignment]
        builtins: dict[str, Any] = msgspec.to_builtins(validated)

        put = mcp_calltime("put")
        get_fn = mcp_calltime("get")
        if put is not None and get_fn is not None:
            put(_event_key(event_id), builtins)
            existing_index = await get_fn(_EVENTS_INDEX_KEY)
            await self._append_event_index_entry(
                current_index=_load_index(existing_index, _EVENTS_INDEX_KEY),
                event_id=event_id,
                event_type=event_type,
                source_service=source_service,
                related_service=related_service,
                timestamp=ts,
            )
        else:
            logger.warning(
                "ecosystem_state_record_skipped",
                extra={
                    "reason": "mcp.put_or_get_unbound",
                    "event_type": event_type,
                    "source_service": source_service,
                },
            )
        return builtins

    async def _append_event_index_entry(
        self,
        *,
        current_index: list[dict[str, Any]],
        event_id: str,
        event_type: str,
        source_service: str,
        related_service: str | None,
        timestamp: str,
    ) -> None:
        """Append ``event_id`` to the events index with retention pruning.

        Mirrors MCP's ``_prune_events`` — old entries beyond the
        retention window are dropped from the index here (the substrate
        owns the actual deletion of stale event keys, but the index is
        the read path so it must stay lean). The caller awaits ``get_fn``
        before invoking this helper so the index is already resolved.
        """
        put = mcp_calltime("put")
        if put is None:
            return
        cutoff = self.retention.cutoff()
        pruned: list[dict[str, Any]] = []
        for entry in current_index:
            ts = _parse_iso(entry.get("timestamp"))
            if ts is not None and ts < cutoff:
                continue
            pruned.append(entry)
        pruned.append(
            {
                "event_id": event_id,
                "event_type": event_type,
                "source_service": source_service,
                "related_service": related_service,
                "timestamp": timestamp,
            }
        )
        pruned.sort(key=lambda e: e.get("timestamp", ""))
        put(_EVENTS_INDEX_KEY, pruned)

    async def list_events_async(
        self,
        event_type: str | None = None,
        source_service: str | None = None,
        related_service: str | None = None,
        limit: int | None = 100,
    ) -> list[dict[str, Any]]:
        """List durable ecosystem events with optional filters.

        Returns up to ``limit`` most-recent matching events (matches
        MCP's ``results[-int(limit):]`` slicing).
        """
        get_fn = mcp_calltime("get")
        if get_fn is None:
            logger.warning(
                "ecosystem_state_list_skipped",
                extra={
                    "reason": "mcp.get_unbound",
                    "kind": "events",
                },
            )
            return []

        index = _load_index(await get_fn(_EVENTS_INDEX_KEY), _EVENTS_INDEX_KEY)
        cutoff = self.retention.cutoff()
        results: list[dict[str, Any]] = []
        for entry in index:
            ts = _parse_iso(entry.get("timestamp"))
            if ts is not None and ts < cutoff:
                continue
            if event_type and entry.get("event_type") != event_type:
                continue
            if source_service and entry.get("source_service") != source_service:
                continue
            if related_service and entry.get("related_service") != related_service:
                continue
            full = await get_fn(_event_key(entry["event_id"]))
            if full is None:
                continue
            results.append(msgspec.to_builtins(msgspec.convert(full, EcosystemEvent)))
        if limit is not None:
            results = results[-int(limit) :]
        return results


__all__ = [
    "EVENT_SCHEMA_VERSION",
    "REGISTRY_SCHEMA_VERSION",
    "AsyncEcosystemStateStore",
    "EventRetention",
]
