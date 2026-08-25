from __future__ import annotations

import json
import os
import pathlib
import tempfile
from typing import TYPE_CHECKING

from oneiric.core.logging import get_logger

from .record import DurableWorkerRecord
from .state import WorkerLifecycleState

if TYPE_CHECKING:
    from collections.abc import Iterator

logger = get_logger(__name__)


class WorkerRecordStore:
    """Atomic JSON I/O for durable worker records.

    Files live at ``<root>/<worker_id>.json``. Writes use ``os.replace`` for
    POSIX-atomic semantics. Indexing is by directory scan; for the expected
    record counts (tens to low hundreds) this is acceptable.
    """

    def __init__(self, root: pathlib.Path | str) -> None:
        self._root = pathlib.Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        os.chmod(self._root, 0o700)

    @property
    def root(self) -> pathlib.Path:
        return self._root

    def _path_for(self, worker_id: str) -> pathlib.Path:
        return self._root / f"{worker_id}.json"

    def get(self, worker_id: str) -> DurableWorkerRecord | None:
        path = self._path_for(worker_id)
        if not path.exists():
            return None
        try:
            with path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            return DurableWorkerRecord.from_dict(data)
        except json.JSONDecodeError, ValueError, OSError:
            logger.exception("failed to load durable worker record", path=str(path))
            return None

    def put(self, record: DurableWorkerRecord) -> None:
        path = self._path_for(record.worker_id)
        payload = json.dumps(record.to_dict(), indent=2, sort_keys=True)
        fd, tmp_name = tempfile.mkstemp(prefix=f".worker-{record.worker_id}-", dir=str(self._root))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(payload)
                fh.flush()
                os.fsync(fh.fileno())
            os.chmod(tmp_name, 0o600)
            os.replace(tmp_name, path)
        except BaseException:
            try:
                pathlib.Path(tmp_name).unlink()
            except FileNotFoundError:
                pass
            raise

    def delete(self, worker_id: str) -> None:
        path = self._path_for(worker_id)
        try:
            path.unlink()
        except FileNotFoundError:
            pass

    def list_active(self) -> Iterator[DurableWorkerRecord]:
        terminal_states = {
            WorkerLifecycleState.COMPLETED,
            WorkerLifecycleState.FAILED,
            WorkerLifecycleState.REAPED,
        }
        yield from (record for record in self.list_all() if record.state not in terminal_states)

    def list_all(self) -> Iterator[DurableWorkerRecord]:
        for path in sorted(self._root.glob("*.json")):
            if path.name.startswith("."):
                continue
            try:
                with path.open("r", encoding="utf-8") as fh:
                    data = json.load(fh)
                yield DurableWorkerRecord.from_dict(data)
            except json.JSONDecodeError, ValueError, OSError:
                logger.exception("failed to scan durable worker record", path=str(path))
                continue
