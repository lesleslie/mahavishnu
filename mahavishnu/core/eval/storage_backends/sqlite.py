"""SQLite run-store backend (REQ-EVAL-002).

The database is opened lazily on first use, in WAL mode so that a reader
is not blocked by a writer. Every statement runs under a lock and its own
transaction, and every ``sqlite3`` failure is translated into an
:class:`EvalStorageError` so callers never see a raw driver exception.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
import json
from pathlib import Path
import sqlite3
import threading
from typing import TYPE_CHECKING

from mahavishnu.core.errors import EvalStorageError
from mahavishnu.core.eval.storage import (
    CaseRecord,
    EvalStorage,
    EvalSummary,
    RunDetails,
    RunRecord,
    ScoreRecord,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from mahavishnu.core.eval.storage import RunStatus

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    suite_name TEXT NOT NULL,
    suite_version TEXT NOT NULL,
    suite_hash TEXT NOT NULL,
    model_configs TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS case_results (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    case_id TEXT NOT NULL,
    case_index INTEGER NOT NULL,
    actual TEXT NOT NULL,
    error TEXT,
    scored INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_case_results_run_id ON case_results(run_id);
CREATE TABLE IF NOT EXISTS scores (
    id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL REFERENCES case_results(id) ON DELETE CASCADE,
    scorer_name TEXT NOT NULL,
    value REAL NOT NULL,
    kind TEXT NOT NULL,
    reasoning TEXT
);
CREATE INDEX IF NOT EXISTS idx_scores_case_id ON scores(case_id);
"""


def _run_from_row(row: sqlite3.Row) -> RunRecord:
    """Build a RunRecord from a ``runs`` row."""
    summary = json.loads(row["summary"])
    return RunRecord(
        id=row["id"],
        suite_name=row["suite_name"],
        suite_version=row["suite_version"],
        suite_hash=row["suite_hash"],
        model_configs=json.loads(row["model_configs"]),
        started_at=datetime.fromisoformat(row["started_at"]),
        finished_at=(
            datetime.fromisoformat(row["finished_at"]) if row["finished_at"] else None
        ),
        status=row["status"],
        summary=summary
        or EvalSummary(
            total_cases=0,
            scored_cases=0,
            errors=0,
            duration_seconds=0.0,
            cost_usd=0.0,
            mean_score=0.0,
            min_score=0.0,
            max_score=0.0,
        ),
    )


def _case_from_row(row: sqlite3.Row) -> CaseRecord:
    """Build a CaseRecord from a ``case_results`` row."""
    return CaseRecord(
        id=row["id"],
        run_id=row["run_id"],
        case_id=row["case_id"],
        case_index=row["case_index"],
        actual=row["actual"],
        error=row["error"],
        scored=bool(row["scored"]),
    )


def _score_from_row(row: sqlite3.Row) -> ScoreRecord:
    """Build a ScoreRecord from a ``scores`` row."""
    return ScoreRecord(
        id=row["id"],
        case_id=row["case_id"],
        scorer_name=row["scorer_name"],
        value=row["value"],
        kind=row["kind"],
        reasoning=row["reasoning"],
    )


class SqliteEvalStorage(EvalStorage):
    """Stores eval runs in a SQLite database.

    Args:
        db_path: Path to the SQLite file. Its parent directory is created
            on first use.
    """

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path).expanduser()
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None

    def _connection(self) -> sqlite3.Connection:
        """Return the open connection, creating and initializing it once.

        Callers must hold ``self._lock``.
        """
        if self._conn is None:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                conn = sqlite3.connect(
                    self._db_path, timeout=30.0, check_same_thread=False
                )
                conn.row_factory = sqlite3.Row
                conn.executescript(_SCHEMA_SQL)
                conn.execute("PRAGMA journal_mode=WAL;")
                conn.execute("PRAGMA synchronous=NORMAL;")
                conn.commit()
            except sqlite3.Error as exc:
                raise EvalStorageError(
                    f"cannot open eval run store at {self._db_path}: {exc}",
                    details={"path": str(self._db_path)},
                ) from exc
            self._conn = conn
        return self._conn

    def _start_run(self, run: RunRecord) -> None:
        """Insert the run row. Caller holds the lock."""
        with self._lock:
            conn = self._connection()
            try:
                conn.execute(
                    "INSERT INTO runs (id, suite_name, suite_version, suite_hash, "
                    "model_configs, started_at, finished_at, status, summary) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        run.id,
                        run.suite_name,
                        run.suite_version,
                        run.suite_hash,
                        json.dumps(run.model_configs),
                        run.started_at.isoformat(),
                        run.finished_at.isoformat() if run.finished_at else None,
                        run.status,
                        json.dumps(run.summary),
                    ),
                )
                conn.commit()
            except sqlite3.Error as exc:
                conn.rollback()
                raise EvalStorageError(
                    f"cannot record eval run {run.id}: {exc}",
                    details={"path": str(self._db_path), "run_id": run.id},
                ) from exc

    def _add_case_result(
        self,
        case: CaseRecord,
        scores: Sequence[ScoreRecord],
    ) -> None:
        """Insert the case row and its scores in one transaction."""
        with self._lock:
            conn = self._connection()
            try:
                conn.execute(
                    "INSERT INTO case_results (id, run_id, case_id, case_index, "
                    "actual, error, scored) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        case.id,
                        case.run_id,
                        case.case_id,
                        case.case_index,
                        case.actual,
                        case.error,
                        int(case.scored),
                    ),
                )
                conn.executemany(
                    "INSERT INTO scores (id, case_id, scorer_name, value, kind, reasoning) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    [
                        (
                            score.id,
                            score.case_id,
                            score.scorer_name,
                            score.value,
                            score.kind,
                            score.reasoning,
                        )
                        for score in scores
                    ],
                )
                conn.commit()
            except sqlite3.Error as exc:
                conn.rollback()
                raise EvalStorageError(
                    f"cannot record case result {case.id}: {exc}",
                    details={"path": str(self._db_path), "case_id": case.id},
                ) from exc

    def _finish_run(
        self,
        run_id: str,
        status: RunStatus,
        finished_at: datetime,
        summary: EvalSummary,
    ) -> None:
        """Update the run row. Caller holds the lock."""
        with self._lock:
            conn = self._connection()
            try:
                cursor = conn.execute(
                    "UPDATE runs SET status = ?, finished_at = ?, summary = ? WHERE id = ?",
                    (status, finished_at.isoformat(), json.dumps(summary), run_id),
                )
                conn.commit()
            except sqlite3.Error as exc:
                conn.rollback()
                raise EvalStorageError(
                    f"cannot finish eval run {run_id}: {exc}",
                    details={"path": str(self._db_path), "run_id": run_id},
                ) from exc
            if cursor.rowcount == 0:
                raise EvalStorageError(
                    f"no such eval run: {run_id}",
                    details={"path": str(self._db_path), "run_id": run_id},
                )

    def _get_run(self, run_id: str) -> RunDetails | None:
        """Read a run with its case results and scores."""
        with self._lock:
            conn = self._connection()
            try:
                run_row = conn.execute(
                    "SELECT * FROM runs WHERE id = ?", (run_id,)
                ).fetchone()
                if run_row is None:
                    return None
                case_rows = conn.execute(
                    "SELECT * FROM case_results WHERE run_id = ? ORDER BY case_index",
                    (run_id,),
                ).fetchall()
                score_rows = conn.execute(
                    "SELECT s.* FROM scores s "
                    "JOIN case_results c ON c.id = s.case_id "
                    "WHERE c.run_id = ? ORDER BY c.case_index",
                    (run_id,),
                ).fetchall()
            except sqlite3.Error as exc:
                raise EvalStorageError(
                    f"cannot read eval run {run_id}: {exc}",
                    details={"path": str(self._db_path), "run_id": run_id},
                ) from exc
        return RunDetails(
            run=_run_from_row(run_row),
            case_results=[_case_from_row(row) for row in case_rows],
            scores=[_score_from_row(row) for row in score_rows],
        )

    def _list_runs(self, limit: int) -> list[RunRecord]:
        """Read the most recent runs, newest first."""
        with self._lock:
            conn = self._connection()
            try:
                rows = conn.execute(
                    "SELECT * FROM runs ORDER BY started_at DESC LIMIT ?", (limit,)
                ).fetchall()
            except sqlite3.Error as exc:
                raise EvalStorageError(
                    f"cannot list eval runs: {exc}",
                    details={"path": str(self._db_path)},
                ) from exc
        return [_run_from_row(row) for row in rows]

    async def start_run(self, run: RunRecord) -> str:
        """Record the start of a run and return its id."""
        await asyncio.to_thread(self._start_run, run)
        return run.id

    async def add_case_result(
        self,
        case: CaseRecord,
        scores: Sequence[ScoreRecord] = (),
    ) -> None:
        """Record one case result and its scores."""
        await asyncio.to_thread(self._add_case_result, case, tuple(scores))

    async def finish_run(
        self,
        run_id: str,
        status: RunStatus,
        finished_at: datetime,
        summary: EvalSummary,
    ) -> None:
        """Transition a run out of the ``running`` state."""
        await asyncio.to_thread(self._finish_run, run_id, status, finished_at, summary)

    async def get_run(self, run_id: str) -> RunDetails | None:
        """Return a run with its case results and scores."""
        return await asyncio.to_thread(self._get_run, run_id)

    async def list_runs(self, limit: int = 50) -> list[RunRecord]:
        """Return the most recent runs, newest first."""
        return await asyncio.to_thread(self._list_runs, limit)


__all__ = ["SqliteEvalStorage"]
