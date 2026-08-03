"""Mahavishnu WAL: writer.

Async DuckDB-backed writer for deferred memory writes. Owns the connection
lifecycle; opens on first use, closes on `close()`.

Spec: docs/superpowers/specs/2026-07-29-session-buddy-extension-design.md
(Q2: data-plane durability).
"""

from __future__ import annotations

import json
import pathlib
from typing import cast

import duckdb

from mahavishnu.core.errors import DatabaseError

from .table import MemoryOutboxRow, OutboxStatus

_SCHEMA_PATH = pathlib.Path(__file__).parent / "schema.sql"


class MemoryOutboxWriter:
    """Async-style wrapper around a DuckDB connection.

    All write methods are async to match the rest of the orchestrator's
    I/O surface, but DuckDB operations are synchronous; we keep the
    interface async to allow swapping the backend without touching call sites.
    """

    def __init__(self, db_path: pathlib.Path) -> None:
        self._db_path = db_path
        self._conn: duckdb.DuckDBPyConnection | None = None

    def _ensure_conn(self) -> duckdb.DuckDBPyConnection:
        if self._conn is None:
            self._conn = duckdb.connect(str(self._db_path))
            self._conn.execute(_SCHEMA_PATH.read_text())
        return self._conn

    async def enqueue(self, key: str, payload: dict[str, object]) -> int:
        conn = self._ensure_conn()
        result = conn.execute(
            "INSERT INTO memory_outbox (key, payload) VALUES (?, ?) RETURNING id",
            [key, json.dumps(payload)],
        ).fetchone()
        if result is None:
            raise DatabaseError(
                "memory_outbox INSERT...RETURNING returned no row (database integrity error)"
            )
        return int(result[0])

    async def pending_count(self) -> int:
        conn = self._ensure_conn()
        result = conn.execute(
            "SELECT COUNT(*) FROM memory_outbox WHERE status = 'pending'"
        ).fetchone()
        if result is None:
            raise DatabaseError(
                "memory_outbox SELECT COUNT(*) returned no row (database integrity error)"
            )
        return int(result[0])

    async def mark_drained(self, ids: list[int]) -> int:
        if not ids:
            return 0
        conn = self._ensure_conn()
        placeholders = ",".join(["?"] * len(ids))
        result = conn.execute(
            f"UPDATE memory_outbox SET status = 'drained' WHERE id IN ({placeholders}) "
            "AND status = 'pending'",
            ids,
        )
        row = result.fetchone()
        if row is None:
            return 0
        return int(row[0])

    async def mark_failed(self, ids: list[int], error: str) -> int:
        if not ids:
            return 0
        conn = self._ensure_conn()
        placeholders = ",".join(["?"] * len(ids))
        result = conn.execute(
            f"UPDATE memory_outbox SET status = 'failed', last_error = ?, "
            f"attempts = attempts + 1 WHERE id IN ({placeholders}) AND status = 'pending'",
            [error, *ids],
        )
        row = result.fetchone()
        if row is None:
            return 0
        return int(row[0])

    async def pending_batch(self, limit: int) -> list[MemoryOutboxRow]:
        conn = self._ensure_conn()
        rows = conn.execute(
            "SELECT id, key, payload, enqueued_at, attempts, last_error, status "
            "FROM memory_outbox WHERE status = 'pending' "
            "ORDER BY enqueued_at, id LIMIT ?",
            [limit],
        ).fetchall()
        return [
            MemoryOutboxRow(
                id=r[0],
                key=r[1],
                payload=json.loads(r[2]),
                enqueued_at=r[3],
                attempts=r[4],
                last_error=r[5],
                status=cast("OutboxStatus", r[6]),
            )
            for r in rows
        ]

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None
