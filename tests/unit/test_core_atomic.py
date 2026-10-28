"""The contract every atomic-write helper in this repo must honour.

Two implementations exist: ``mahavishnu.core.atomic`` for the package,
and ``.claude/hooks/_atomic_write.py`` for the hook scripts, which stay
deliberately self-contained so a hook never fails because the package is
unavailable. They must behave identically.
"""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import stat
import tempfile
import threading
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from types import ModuleType

from mahavishnu.core import atomic as package_atomic

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOK_HELPER = REPO_ROOT / ".claude" / "hooks" / "_atomic_write.py"


def _load_hook_helper() -> ModuleType:
    spec = importlib.util.spec_from_file_location("_hook_atomic_write", HOOK_HELPER)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


HOOK_ATOMIC = _load_hook_helper()

HELPERS = [
    pytest.param(package_atomic, id="mahavishnu.core.atomic"),
    pytest.param(HOOK_ATOMIC, id="hooks/_atomic_write.py"),
]


@pytest.fixture(params=HELPERS)
def atomic(request: pytest.FixtureRequest) -> ModuleType:
    """Each helper implementation, one at a time."""
    return request.param


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_atomic_write_text_publishes_the_content(atomic: ModuleType, tmp_path: Path) -> None:
    dest = tmp_path / "snapshot.json"
    atomic.atomic_write_text(dest, "hello")
    assert dest.read_text() == "hello"


def test_atomic_write_bytes_publishes_binary_content(atomic: ModuleType, tmp_path: Path) -> None:
    dest = tmp_path / "blob.bin"
    atomic.atomic_write_bytes(dest, b"\x00\x01\x02")
    assert dest.read_bytes() == b"\x00\x01\x02"


def test_atomic_write_text_leaves_no_temp_file_behind(atomic: ModuleType, tmp_path: Path) -> None:
    dest = tmp_path / "snapshot.json"
    atomic.atomic_write_text(dest, "hello")
    assert [p.name for p in tmp_path.iterdir()] == ["snapshot.json"]


def test_atomic_write_text_publishes_owner_only_permissions(
    atomic: ModuleType, tmp_path: Path
) -> None:
    dest = tmp_path / "snapshot.json"
    atomic.atomic_write_text(dest, "hello")
    assert _mode(dest) == 0o600


def test_atomic_write_text_honours_an_explicit_mode(atomic: ModuleType, tmp_path: Path) -> None:
    dest = tmp_path / "snapshot.json"
    atomic.atomic_write_text(dest, "hello", mode=0o640)
    assert _mode(dest) == 0o640


def test_a_stale_temp_file_cannot_leak_its_permissions(atomic: ModuleType, tmp_path: Path) -> None:
    """A leftover temp file from a crashed write must not be reused.

    ``Path.write_text`` truncates an existing file *in place* and keeps
    its mode, so a stale temp left at 0644 publishes the destination at
    0644 no matter what the writer intended.
    """
    dest = tmp_path / "snapshot.json"
    stale = tmp_path / "snapshot.tmp"
    stale.write_text("poison")
    stale.chmod(0o644)

    atomic.atomic_write_text(dest, "fresh")

    assert dest.read_text() == "fresh"
    assert _mode(dest) == 0o600


def test_a_symlinked_temp_file_is_never_written_through(atomic: ModuleType, tmp_path: Path) -> None:
    """The writer must not follow a symlink planted at a predictable path.

    ``Path.write_bytes`` opens with ``O_CREAT | O_TRUNC``, which follows
    a symlink: whatever the temp path points at gets truncated and
    overwritten.
    """
    dest = tmp_path / "snapshot.json"
    victim = tmp_path / "victim.txt"
    victim.write_text("precious")
    (tmp_path / "snapshot.tmp").symlink_to(victim)

    atomic.atomic_write_text(dest, "fresh")

    assert victim.read_text() == "precious"
    assert dest.read_text() == "fresh"


def test_the_temp_file_is_owner_only_from_the_moment_it_exists(
    atomic: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The temp file must never be observable at a wider mode.

    A write-then-chmod pattern leaves the temp readable by everyone for
    as long as the write takes -- which is exactly the window a
    sensitive payload is exposed in.
    """
    real_mkstemp = tempfile.mkstemp
    observed: list[int] = []

    def spy(
        suffix: str | None = None,
        prefix: str | None = None,
        dir: str | os.PathLike[str] | None = None,
        text: bool = False,
    ) -> tuple[int, str]:
        fd, name = real_mkstemp(suffix=suffix, prefix=prefix, dir=dir, text=text)
        observed.append(stat.S_IMODE(os.fstat(fd).st_mode))
        return fd, name

    monkeypatch.setattr(tempfile, "mkstemp", spy)

    atomic.atomic_write_text(tmp_path / "snapshot.json", "hello")

    assert observed == [0o600], f"the temp file was created at {observed}"


def test_a_failed_rename_leaves_the_destination_untouched(
    atomic: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A crash between the write and the rename must not leak a temp file."""
    dest = tmp_path / "snapshot.json"
    dest.write_text("original")

    def boom(src: str, dst: str) -> None:
        raise OSError("rename failed")

    monkeypatch.setattr(os, "replace", boom)

    with pytest.raises(OSError, match="rename failed"):
        atomic.atomic_write_text(dest, "new")

    assert dest.read_text() == "original"
    assert [p.name for p in tmp_path.iterdir()] == ["snapshot.json"]


def test_concurrent_writers_all_succeed(atomic: ModuleType, tmp_path: Path) -> None:
    """Every writer of one destination must survive.

    With a fixed temp name the first writer to rename moves the file
    away from the others, whose rename then raises
    ``FileNotFoundError``.
    """
    dest = tmp_path / "snapshot.json"
    errors: list[BaseException] = []
    barrier = threading.Barrier(8)

    def writer(index: int) -> None:
        try:
            barrier.wait()
            for _ in range(25):
                atomic.atomic_write_text(dest, json.dumps({"writer": index}))
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors, f"concurrent writers raised: {errors[:3]}"
    assert json.loads(dest.read_text())["writer"] in range(8)


def test_the_published_file_is_never_a_mixture_of_two_writes(
    atomic: ModuleType, tmp_path: Path
) -> None:
    """A published file must be one writer's bytes, never a blend."""
    dest = tmp_path / "snapshot.json"
    errors: list[BaseException] = []
    barrier = threading.Barrier(8)

    def writer(index: int) -> None:
        try:
            barrier.wait()
            for _ in range(25):
                atomic.atomic_write_text(dest, json.dumps({"writer": index, "filler": "x" * 4000}))
                # A reader must never observe a half-written file.
                assert json.loads(dest.read_text())["filler"] == "x" * 4000
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors, f"concurrent writers raised: {errors[:3]}"
