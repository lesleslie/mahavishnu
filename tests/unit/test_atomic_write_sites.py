"""Every writer in the Bodai activity path publishes atomically.

Each of these writers used a *fixed-name* temp file
(``path.with_suffix(path.suffix + ".tmp")``) and then renamed it over
the destination. That pattern shares one temp file between every writer
of the same destination, so the first writer to rename moves the file
out from under the others and their rename fails with
``FileNotFoundError`` -- which two of these three writers swallow, so
the update is silently lost. It also reuses whatever a crashed earlier
write left behind, and follows a symlink planted at the predictable
temp path.

The assertions below are about the *published* file and the *surrounding
directory*: the destination must be owner-only, must hold complete
content, and must leave no temp file behind.
"""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
import threading
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from types import ModuleType

from mahavishnu.core.events.bodai_subscriber import _write_queue_atomic

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOK_DIR = REPO_ROOT / ".claude" / "hooks"

WRITERS = 8
WRITES_EACH = 25


def _load_hook(name: str) -> ModuleType:
    """Load a Claude Code hook script as an importable module.

    The hook scripts import their shared helpers from the hooks
    directory, so that directory has to be importable the same way it
    is when the script runs as ``__main__``.
    """
    spec = importlib.util.spec_from_file_location(name, HOOK_DIR / f"{name}.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    hooks_dir = str(HOOK_DIR)
    sys.path.insert(0, hooks_dir)
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(hooks_dir)
    return module


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def _assert_published_cleanly(dest: Path) -> None:
    """The destination is owner-only and no temp file was left behind."""
    assert _mode(dest) == 0o600
    leftovers = [
        p.name
        for p in dest.parent.iterdir()
        if p != dest and (p.name.endswith(".tmp") or p.name.startswith(f".{dest.name}."))
    ]
    assert not leftovers, f"the writer left temp files behind: {leftovers}"


class _ReplaceCounter:
    """Counts the renames that actually succeeded.

    Two of these three writers swallow ``OSError``, so a lost update is
    invisible from the outside -- the only way to see it is to watch the
    renames.
    """

    def __init__(self) -> None:
        self.succeeded: list[Path] = []
        self._real_replace = os.replace

    def __call__(self, src: str, dst: str) -> None:
        self._real_replace(src, dst)
        self.succeeded.append(Path(dst))


@pytest.fixture
def replace_counter(monkeypatch: pytest.MonkeyPatch) -> _ReplaceCounter:
    counter = _ReplaceCounter()
    monkeypatch.setattr(os, "replace", counter)
    return counter


class TestEventQueue:
    """``mahavishnu.core.events.bodai_subscriber._write_queue_atomic``."""

    def test_the_queue_is_published_owner_only(self, tmp_path: Path) -> None:
        dest = tmp_path / "queue.json"

        _write_queue_atomic(dest, [{"headers": {"source": "mahavishnu"}}])

        assert json.loads(dest.read_text())
        _assert_published_cleanly(dest)

    def test_a_symlinked_temp_path_is_not_written_through(self, tmp_path: Path) -> None:
        """The old temp name was ``queue.json.tmp``; it must not be reused."""
        dest = tmp_path / "queue.json"
        victim = tmp_path / "victim.txt"
        victim.write_text("precious")
        (tmp_path / "queue.json.tmp").symlink_to(victim)

        _write_queue_atomic(dest, [{"headers": {"source": "mahavishnu"}}])

        assert victim.read_text() == "precious"

    def test_concurrent_writers_all_publish(
        self, tmp_path: Path, replace_counter: _ReplaceCounter
    ) -> None:
        dest = tmp_path / "queue.json"
        errors: list[BaseException] = []
        barrier = threading.Barrier(WRITERS)

        def writer(index: int) -> None:
            try:
                barrier.wait()
                for _ in range(WRITES_EACH):
                    _write_queue_atomic(dest, [{"writer": index}])
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(WRITERS)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert not errors, f"concurrent writers raised: {errors[:3]}"
        assert len(replace_counter.succeeded) == WRITERS * WRITES_EACH, (
            "every rename must succeed -- a shared temp file makes the "
            "later renames fail with FileNotFoundError"
        )
        assert json.loads(dest.read_text())


class TestPostToolUseHook:
    """``bodai-activity-post-tool-use.py::_write_state``."""

    @pytest.fixture
    def hook(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ModuleType:
        monkeypatch.setenv(
            "MAHAVISHNU_BODAI_POST_TOOL_USE_STATE_PATH",
            str(tmp_path / "state.json"),
        )
        return _load_hook("bodai-activity-post-tool-use")

    def test_the_state_is_published_owner_only(self, hook: ModuleType, tmp_path: Path) -> None:
        hook._write_state({"last_message_id": "1-0"})

        dest = tmp_path / "state.json"
        assert json.loads(dest.read_text()) == {"last_message_id": "1-0"}
        _assert_published_cleanly(dest)

    def test_a_symlinked_temp_path_is_not_written_through(
        self, hook: ModuleType, tmp_path: Path
    ) -> None:
        """The old temp name was ``state.json.tmp``; it must not be reused."""
        victim = tmp_path / "victim.txt"
        victim.write_text("precious")
        (tmp_path / "state.json.tmp").symlink_to(victim)

        hook._write_state({"last_message_id": "1-0"})

        assert victim.read_text() == "precious"

    def test_concurrent_writers_all_publish(
        self,
        hook: ModuleType,
        tmp_path: Path,
        replace_counter: _ReplaceCounter,
    ) -> None:
        errors: list[BaseException] = []
        barrier = threading.Barrier(WRITERS)

        def writer(index: int) -> None:
            try:
                barrier.wait()
                for _ in range(WRITES_EACH):
                    hook._write_state({"writer": index})
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(WRITERS)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert not errors, f"concurrent writers raised: {errors[:3]}"
        assert len(replace_counter.succeeded) == WRITERS * WRITES_EACH, (
            "every rename must succeed -- the hook swallows OSError, so a "
            "lost update is otherwise invisible"
        )


class TestSubscriberHook:
    """``bodai-activity-subscriber.py::_write_state``."""

    @pytest.fixture
    def hook(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ModuleType:
        monkeypatch.setenv(
            "MAHAVISHNU_BODAI_SUBSCRIBER_STATE_PATH",
            str(tmp_path / "state.json"),
        )
        return _load_hook("bodai-activity-subscriber")

    def test_the_state_is_published_owner_only(self, hook: ModuleType, tmp_path: Path) -> None:
        hook._write_state({"pid": 1234})

        dest = tmp_path / "state.json"
        assert json.loads(dest.read_text()) == {"pid": 1234}
        _assert_published_cleanly(dest)

    def test_concurrent_writers_all_publish(
        self,
        hook: ModuleType,
        tmp_path: Path,
        replace_counter: _ReplaceCounter,
    ) -> None:
        errors: list[BaseException] = []
        barrier = threading.Barrier(WRITERS)

        def writer(index: int) -> None:
            try:
                barrier.wait()
                for _ in range(WRITES_EACH):
                    hook._write_state({"writer": index})
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(WRITERS)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert not errors, f"concurrent writers raised: {errors[:3]}"
        assert len(replace_counter.succeeded) == WRITERS * WRITES_EACH, (
            "every rename must succeed -- the hook swallows OSError, so a "
            "lost update is otherwise invisible"
        )
