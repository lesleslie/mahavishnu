from __future__ import annotations

from dataclasses import dataclass
import datetime as dt
import pathlib
import secrets
import time
from typing import Any, Protocol

from . import tmux_adapter as tmux
from .record import DurableWorkerRecord, TmuxTarget
from .state import WorkerLifecycleState, can_transition
from .store import WorkerRecordStore  # noqa: TC001  (used as runtime value in __init__)
from .tmux_adapter import (
    TmuxAdapterError,
    capture_pane,
    create_session,
    kill_session,
    pane_alive,
    send_keys,
)


class EventPublisher(Protocol):
    def emit(self, payload: dict[str, Any], topic: str) -> None: ...


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _new_worker_id() -> str:
    return f"worker-{secrets.token_hex(4)}"


@dataclass(frozen=True)
class SpawnResult:
    worker_id: str
    record: DurableWorkerRecord
    pane: str


class DurableWorkerManager:
    """Owns durable worker records, tmux sessions, and canonical events."""

    def __init__(
        self,
        *,
        store: WorkerRecordStore,
        publisher: EventPublisher,
        socket_dir: pathlib.Path,
    ) -> None:
        self.store = store
        self.publisher = publisher
        self.socket_dir = pathlib.Path(socket_dir)
        self.socket_dir.mkdir(parents=True, exist_ok=True)
        # Spec §9: 0700 on the tmux socket directory.
        import os as _os

        _os.chmod(self.socket_dir, 0o700)
        # Spec §9: snapshot directory for pane-snapshot side files.
        self.snapshot_dir = self.socket_dir.parent / "pane-snapshots"
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        _os.chmod(self.snapshot_dir, 0o700)

    def _socket_for(self, worker_id: str) -> str:
        return str(self.socket_dir / f"{worker_id}.sock")

    def _snapshot_path(self, record: DurableWorkerRecord) -> pathlib.Path:
        return self.snapshot_dir / f"{record.worker_id}.txt"

    def _write_snapshot(self, record: DurableWorkerRecord) -> str | None:
        """Capture a fresh pane snapshot to disk; return the path or None."""
        if record.tmux is None:
            return None
        try:
            captured = capture_pane(
                record.tmux.socket,
                record.tmux.pane,
                since_offset=0,
                max_bytes=131_072,
            )
        except TmuxAdapterError:
            return None
        path = self._snapshot_path(record)
        try:
            path.write_text(captured.text, encoding="utf-8")
        except OSError:
            return None
        return str(path)

    def _publish(self, topic: str, record: DurableWorkerRecord, **extra: Any) -> None:
        # Spec §9: pane snapshots are NOT embedded in envelopes. The bridge
        # writes the snapshot to a side file and references it from the
        # envelope. We publish the reference; we do not embed the bytes.
        snapshot_path = self._write_snapshot(record)
        payload: dict[str, Any] = {
            "worker_id": record.worker_id,
            "worker_type": record.worker_type,
            "backend": record.backend,
            "state": record.state.value if hasattr(record.state, "value") else record.state,
            "tmux_session": record.tmux.session if record.tmux else None,
            "tmux_window": record.tmux.window if record.tmux else None,
            "tmux_pane": record.tmux.pane if record.tmux else None,
            "pane_snapshot_path": snapshot_path,
        }
        payload.update(extra)
        self.publisher.emit(payload, topic)

    def _transition(
        self, record: DurableWorkerRecord, target: WorkerLifecycleState
    ) -> DurableWorkerRecord:
        if record.state == target:
            return record
        if not can_transition(record.state, target):
            raise ValueError(
                f"invalid transition {record.state} -> {target} for {record.worker_id}"
            )
        updated = record.model_copy(
            update={"state": target, "last_seen_at": _utcnow()}
        )
        self.store.put(updated)
        self._publish("worker.status_changed", updated)
        return updated

    def spawn(
        self,
        *,
        worker_type: str,
        backend: str,
        command: list[str],
        worker_id: str | None = None,
        window_name: str = "main",
        max_wait_ms: int = 30_000,
    ) -> SpawnResult:
        # Spec §6: emit STARTING before tmux creation so launch_worker
        # can return the in-flight state. F11/F19.
        worker_id = worker_id or _new_worker_id()
        socket = self._socket_for(worker_id)
        session = worker_id
        now = _utcnow()
        starting = DurableWorkerRecord(
            worker_id=worker_id,
            worker_type=worker_type,
            backend=backend,
            tmux=None,
            state=WorkerLifecycleState.STARTING,
            created_at=now,
            last_seen_at=now,
        )
        self.store.put(starting)
        self._publish("worker.spawned", starting)
        self._publish("worker.status_changed", starting)
        # Bounded tmux creation + initial command launch.
        info = create_session(
            socket=socket,
            session=session,
            window_name=window_name,
            command=command,
        )
        target = TmuxTarget(
            socket=info.socket,
            session=info.session,
            window=info.window,
            pane=info.pane,
            attach_command=info.attach_command,
        )
        # F11: transition STARTING -> READY (or REAPED on early failure).
        ready = self._transition(
            starting.model_copy(update={"tmux": target}),
            WorkerLifecycleState.READY,
        )
        pane_id = ready.tmux.pane if ready.tmux else ""
        return SpawnResult(worker_id=worker_id, record=ready, pane=pane_id)

    def status(self, worker_id: str) -> DurableWorkerRecord | None:
        return self.store.get(worker_id)

    def capture_output(
        self, worker_id: str, *, since_offset: int, max_bytes: int = 65_536
    ) -> tmux.CapturedOutput:
        record = self.store.get(worker_id)
        if record is None or record.tmux is None:
            return tmux.CapturedOutput(
                text="", next_offset=since_offset, truncated=False, pane_alive=False
            )
        result = capture_pane(
            record.tmux.socket,
            record.tmux.pane,
            since_offset=since_offset,
            max_bytes=max_bytes,
        )
        # Persist new offset
        updated = record.model_copy(
            update={"last_output_offset": result.next_offset, "last_seen_at": _utcnow()}
        )
        self.store.put(updated)
        return result

    def send_input(self, worker_id: str, text: str, *, submit: bool = True) -> bool:
        record = self.store.get(worker_id)
        if record is None or record.tmux is None:
            return False
        if record.state not in {
            WorkerLifecycleState.READY,
            WorkerLifecycleState.RUNNING,
            WorkerLifecycleState.DETACHED,
        }:
            return False
        keys = [text]
        if submit and not text.endswith("\n"):
            keys = [text, "Enter"]
        send_keys(record.tmux.socket, record.tmux.pane, keys)
        record = record.model_copy(update={"last_seen_at": _utcnow()})
        self.store.put(record)
        return True

    def cancel(
        self, worker_id: str, *, signal: str = "soft", grace_ms: int = 5_000
    ) -> bool:
        record = self.store.get(worker_id)
        if record is None or record.tmux is None:
            return False
        if record.state == WorkerLifecycleState.REAPED:
            return False
        record = self._transition(record, WorkerLifecycleState.DRAINING)
        if signal == "soft":
            # The soft signal targets a live pane; if the socket is gone the
            # adapter raises and we simply fall through to the grace loop.
            try:
                send_keys(record.tmux.socket, record.tmux.pane, ["\x03"])
            except TmuxAdapterError:
                pass
        deadline = time.monotonic() + grace_ms / 1000.0
        while time.monotonic() < deadline:
            if not pane_alive(record.tmux.socket, record.tmux.pane):
                break
            time.sleep(0.1)
        if pane_alive(record.tmux.socket, record.tmux.pane):
            if signal == "SIGKILL":
                tmux._run(
                    record.tmux.socket, "kill-pane", "-t", record.tmux.pane
                )
            else:
                tmux._run(
                    record.tmux.socket,
                    "send-keys",
                    "-t",
                    record.tmux.pane,
                    "C-c",
                )
        try:
            kill_session(record.tmux.socket, record.tmux.session)
        except TmuxAdapterError:
            pass
        record = self._transition(record, WorkerLifecycleState.REAPED)
        self._publish("worker.reaped", record, reason="cancelled", signal=signal)
        return True

    def reap(self, worker_id: str) -> None:
        record = self.store.get(worker_id)
        if record is None:
            return
        if record.state == WorkerLifecycleState.REAPED:
            return
        record = self._transition(record, WorkerLifecycleState.REAPED)
        self._publish("worker.reaped", record, reason="explicit")

    def reconcile_all(self) -> list[DurableWorkerRecord]:
        reconciled: list[DurableWorkerRecord] = []
        for record in self.store.list_all():
            if record.tmux is None:
                continue
            alive = pane_alive(record.tmux.socket, record.tmux.pane)
            if not alive:
                # Pane is dead. v1: reap the record. Sibling-pane
                # recreation (spec §5 F3) is deferred to a follow-up
                # because it requires a non-trivial tmux window-layout
                # query; document the gap in the next-plan task.
                if record.state != WorkerLifecycleState.REAPED:
                    record = self._transition(record, WorkerLifecycleState.REAPED)
                    self._publish("worker.reaped", record, reason="pane_dead")
            elif record.state == WorkerLifecycleState.DETACHED:
                # F18: runtime disconnect -> reconnect emits DETACHED;
                # reconcile sees the pane is alive and restores READY.
                record = self._transition(record, WorkerLifecycleState.READY)
                self._publish("worker.attached", record)
            record = record.model_copy(update={"last_seen_at": _utcnow()})
            self.store.put(record)
            reconciled.append(record)
        return reconciled

    def mark_all_detached(self) -> int:
        """Spec §8.5: graceful shutdown. Marks in-flight workers as
        DETACHED, emits worker.status_changed for each, and does NOT
        kill the underlying panes (the operator may want to keep them).
        Returns the number of records transitioned.
        """
        transitioned = 0
        # Only include states whose ALLOWED_TRANSITIONS table permits
        # a transition to DETACHED. STARTING -> DETACHED is not allowed
        # (STARTING has only STARTING->READY/REAPED/FAILED/DEGRADED),
        # and DRAINING -> DETACHED is not allowed either. Including them
        # here would raise ValueError from _transition.
        in_flight = {
            WorkerLifecycleState.READY,
            WorkerLifecycleState.RUNNING,
        }
        for record in self.store.list_all():
            if record.state in in_flight:
                # F18: explicit runtime-disconnect path during shutdown.
                record = self._transition(record, WorkerLifecycleState.DETACHED)
                transitioned += 1
        return transitioned
