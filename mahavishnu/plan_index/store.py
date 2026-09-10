"""Dhara-backed CRUD for plan metadata.

This is the only file that imports the Dhara client. PlanIndexRebuilder,
PlanIndexRenderer, PeriodicTaskRunner, and the MCP tools all consume
this module's interface — never Dhara directly.

Key conventions (mirror dhara-key-prefixes-2026-07-15.md):
  - plan_index/{plan_id}                  — primary, TTL 24h
  - plan_index/status/{status}/{date}/{plan_id}  — secondary index
  - plan_index/topic/{topic}/{date}/{plan_id}    — secondary index
  - plan_index/meta/{counter}             — counters (no TTL)
  - plan_index/meta/rebuild_lock/...      — TTL 60s
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
import json
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from mahavishnu.plan_index import PlanId
    from mahavishnu.plan_index.record import PlanRecord
    from mahavishnu.plan_index.types import (
        PlanRebuildStatusDict,
        PlanRecordDict,
        PlanVitalsDict,
        TripwireState,
    )


__all__ = ["PlanIndexStore"]


class _DharaClient(Protocol):
    """Subset of AsyncClient that PlanIndexStore uses. Exists for typing."""

    async def put(self, key: str, value: str, *, ttl: int | None = ...) -> None: ...
    async def get(self, key: str) -> str | None: ...
    async def list_prefix(self, prefix: str) -> list[tuple[str, str]]: ...
    async def delete(self, key: str) -> None: ...


class PlanIndexStore:
    """Dhara-backed CRUD. Constructor takes an optional Dhara client (DI)."""

    def __init__(self, dhara: _DharaClient) -> None:
        self._dhara = dhara

    @staticmethod
    def _primary_key(plan_id: str) -> str:
        return f"plan_index/{plan_id}"

    @staticmethod
    def _status_key(record: PlanRecordDict) -> str:
        return f"plan_index/status/{record['status']}/{record['date']}/{record['plan_id']}"

    @staticmethod
    def _topic_key(record: PlanRecordDict) -> str:
        return f"plan_index/topic/{record['topic']}/{record['date']}/{record['plan_id']}"

    @staticmethod
    def _to_dict(record: PlanRecord) -> PlanRecordDict:
        result: PlanRecordDict = {
            "plan_id": record.plan_id,
            "path": record.path,
            "title": record.title,
            "status": record.status,
            "role": record.role,
            "topic": record.topic,
            "date": record.date,
            "last_reviewed": record.last_reviewed,
            "blocks_on": list(record.blocks_on),
            "sha": record.sha,
            "repo": record.repo,
            "updated_at_ms": record.updated_at_ms,
        }
        if record.superseded_by is not None:
            result["superseded_by"] = record.superseded_by
        if record.lifecycle_state is not None:
            result["lifecycle_state"] = record.lifecycle_state
        return result

    async def upsert(self, record: PlanRecord) -> None:
        d = self._to_dict(record)
        await self._dhara.put(self._primary_key(d["plan_id"]), json.dumps(d), ttl=86400)
        await self._dhara.put(self._status_key(d), json.dumps(d))
        await self._dhara.put(self._topic_key(d), json.dumps(d))

    async def get(self, plan_id: PlanId) -> PlanRecordDict | None:
        raw = await self._dhara.get(self._primary_key(plan_id))
        if raw is None:
            return None
        result: PlanRecordDict = json.loads(raw)
        return result

    async def _list_by_prefix(self, prefix: str, *, limit: int) -> list[PlanRecordDict]:
        pairs = await self._dhara.list_prefix(prefix)
        records: list[PlanRecordDict] = []
        for _key, value in pairs[:limit]:
            rec: PlanRecordDict = json.loads(value)
            records.append(rec)
        return records

    async def list_by_status(self, status: str, *, limit: int = 50) -> list[PlanRecordDict]:
        return await self._list_by_prefix(f"plan_index/status/{status}/", limit=limit)

    async def list_by_topic(self, topic: str, *, limit: int = 50) -> list[PlanRecordDict]:
        return await self._list_by_prefix(f"plan_index/topic/{topic}/", limit=limit)

    async def list_by_date_range(self, date_from: str, date_to: str) -> list[PlanRecordDict]:
        all_records = await self._list_by_prefix("plan_index/status/", limit=1000)
        return [r for r in all_records if date_from <= r["date"] <= date_to]

    async def list_all(self, *, limit: int = 1000) -> list[PlanRecordDict]:
        # Primary keys are plan_index/{plan_id}, NOT plan_index/{anything-else}
        # We can scan the primary namespace but must exclude status/topic/meta
        # sub-prefixes. list_prefix returns sorted-by-key, so primary entries
        # appear before sub-prefixes when iterating from "plan_index/".
        # But because the prefix "plan_index/" matches everything (primary +
        # status/ + topic/ + meta/), we have to dedupe.
        seen: set[str] = set()
        out: list[PlanRecordDict] = []
        pairs = await self._dhara.list_prefix("plan_index/")
        for key, value in pairs:
            # Primary keys are exactly "plan_index/{32-hex}"
            suffix = key[len("plan_index/"):]
            if "/" in suffix:  # secondary index entry or meta — skip
                continue
            if suffix in seen:
                continue
            seen.add(suffix)
            rec: PlanRecordDict = json.loads(value)
            out.append(rec)
            if len(out) >= limit:
                break
        return out

    async def search(self, query: str, *, limit: int = 20) -> list[PlanRecordDict]:
        """Lexical match on title + topic. Full-table scan; O(N) at ~500 records."""
        all_records = await self.list_all(limit=1000)
        lowered = query.lower()
        matches = [
            r for r in all_records
            if lowered in r["title"].lower() or lowered in r["topic"].lower()
        ]
        return matches[:limit]

    async def vitals(self) -> PlanVitalsDict:
        all_records = await self.list_all(limit=10000)
        status_counts: Counter[str] = Counter(r["status"] for r in all_records)
        role_counts: Counter[str] = Counter(r["role"] for r in all_records)
        topic_counter: Counter[str] = Counter(r["topic"] for r in all_records)
        rebuild_raw = await self._dhara.get("plan_index/meta/last_rebuild_ms")
        last_rebuild_ms = int(rebuild_raw) if rebuild_raw else None
        success_raw = await self._dhara.get("plan_index/meta/last_success_ms")
        last_success_ms = int(success_raw) if success_raw else None
        cycles_raw = await self._dhara.get("plan_index/meta/cycles_total")
        cycles_total = int(cycles_raw) if cycles_raw else 0
        success_cycles_raw = await self._dhara.get("plan_index/meta/successful_cycles_total")
        successful_cycles_total = int(success_cycles_raw) if success_cycles_raw else 0
        errors_raw = await self._dhara.get("plan_index/meta/errors_total")
        errors_total = int(errors_raw) if errors_raw else 0
        # recent_errors — read from a JSON list (last 20)
        recent_errors_raw = await self._dhara.get("plan_index/meta/recent_errors")
        recent_errors: list[dict[str, Any]] = json.loads(recent_errors_raw) if recent_errors_raw else []
        tripwire = self._compute_tripwire(all_records, last_rebuild_ms)
        oldest_active_ms = self._oldest_active_ms(all_records)
        result: PlanVitalsDict = {
            "total": len(all_records),
            "by_status": dict(status_counts),
            "by_role": dict(role_counts),
            "by_topic_top10": topic_counter.most_common(10),
            "cycles_total": cycles_total,
            "successful_cycles_total": successful_cycles_total,
            "errors_total": errors_total,
            "recent_errors": recent_errors,  # type: ignore[typeddict-item]
            "tripwire": tripwire,
        }
        if last_rebuild_ms is not None:
            result["last_rebuild_ms"] = last_rebuild_ms
        if last_success_ms is not None:
            result["last_success_ms"] = last_success_ms
        if oldest_active_ms is not None:
            result["oldest_active_ms"] = oldest_active_ms
        return result

    @staticmethod
    def _compute_tripwire(
        all_records: list[PlanRecordDict], last_rebuild_ms: int | None
    ) -> TripwireState:
        # v1 is recorded-only. Placeholder: simple heuristic.
        if not all_records:
            return "ok"
        if last_rebuild_ms is None:
            return "no_recent_edits"
        return "ok"

    @staticmethod
    def _oldest_active_ms(all_records: list[PlanRecordDict]) -> int | None:
        active = [r for r in all_records if r["status"] == "active"]
        if not active:
            return None
        return min(int(r["updated_at_ms"]) for r in active)

    async def rebuild_status(self) -> PlanRebuildStatusDict:
        cycles_raw = await self._dhara.get("plan_index/meta/cycles_total")
        cycles_total = int(cycles_raw) if cycles_raw else 0
        success_cycles_raw = await self._dhara.get("plan_index/meta/successful_cycles_total")
        successful_cycles_total = int(success_cycles_raw) if success_cycles_raw else 0
        errors_raw = await self._dhara.get("plan_index/meta/errors_total")
        errors_total = int(errors_raw) if errors_raw else 0
        rebuild_raw = await self._dhara.get("plan_index/meta/last_rebuild_ms")
        last_rebuild_ms = int(rebuild_raw) if rebuild_raw else None
        success_raw = await self._dhara.get("plan_index/meta/last_success_ms")
        last_success_ms = int(success_raw) if success_raw else None
        recent_errors_raw = await self._dhara.get("plan_index/meta/recent_errors")
        recent_errors: list[dict[str, Any]] = json.loads(recent_errors_raw) if recent_errors_raw else []
        lock_raw = await self._dhara.get("plan_index/meta/rebuild_lock/holder")
        lock_held_by = lock_raw if lock_raw else None
        lock_age_ms = None
        if lock_held_by is not None:
            # 60s lock TTL means staleness is determined by last_rebuild_ms
            lock_age_ms = 0  # placeholder; real impl reads lock_acquired_at_ms
        stale = last_rebuild_ms is None or (
            int(datetime.now(tz=UTC).timestamp() * 1000) - last_rebuild_ms > 5 * 3600 * 1000
        )
        result: PlanRebuildStatusDict = {
            "cycles_total": cycles_total,
            "successful_cycles_total": successful_cycles_total,
            "errors_total": errors_total,
            "recent_errors": recent_errors,  # type: ignore[typeddict-item]
            "stale": stale,
        }
        if last_rebuild_ms is not None:
            result["last_rebuild_ms"] = last_rebuild_ms
        if last_success_ms is not None:
            result["last_success_ms"] = last_success_ms
        if lock_held_by is not None:
            result["lock_held_by"] = lock_held_by
        if lock_age_ms is not None:
            result["lock_age_ms"] = lock_age_ms
        return result
