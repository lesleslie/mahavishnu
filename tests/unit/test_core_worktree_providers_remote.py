"""Tests for ``mahavishnu.core.worktree_providers.remote.RemoteWorktreeProvider``.

Phase 3 (Task C.7) streaming tar.zst coverage — mirrors
``test_core_worktree_providers_local.py`` (Task C.6) but exercises the
cloud-backed path (S3 / GCS / Azure) where ``save_stream`` is async and
``load_stream`` returns a zero-arg callable yielding ``Iterator[bytes]``.

Uses in-memory storage / cache / Dhara fakes so no real cloud or Redis
connections are required.

Test infra note: ``remote.py`` captures ``get_worktree_path`` /
``get_worktree_base_path`` at module-import time (``from
mahavishnu.core.paths import ...``), so monkeypatching only the source
location doesn't affect the captured reference. The fixtures here
patch the SOURCE module *and* re-patch the captured reference on
``remote`` so the worktree paths land under ``tmp_path``. The same
trick is used for ``serialize_worktree_tar`` in the size-cap test.
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TYPE_CHECKING

import pytest

from mahavishnu.auth import Principal
from mahavishnu.core.worktree_providers import remote as remote_mod
from mahavishnu.core.worktree_providers.remote import (
    MAX_CONCURRENT_WORKTREE_STREAMS,
    HealthReport,
    RemoteWorktreeProvider,
    supports_streaming,
)
from mahavishnu.core.worktree_providers.types import (
    RemoteWorktreeRef,
    WorktreeHandle,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.unit

try:
    import zstandard  # noqa: F401
except ImportError:
    pytest.skip(
        "zstandard required; uv sync --group compression-zstd",
        allow_module_level=True,
    )


# ---------------------------------------------------------------------------
# Fakes — recording doubles for cloud storage / cache / Dhara
# ---------------------------------------------------------------------------


@dataclass
class _AdapterMetadata:
    capabilities: list[str] = field(default_factory=list)


class _FakeCloudStorage:
    """In-memory S3/GCS/Azure-shaped fake with async save_stream + sync load_stream.

    Mirrors the oneiric PR-A storage adapter contract:

    - ``save_stream`` is ASYNC (cloud adapter awaits multipart calls).
    - ``load_stream`` is SYNC and returns a zero-arg callable that
      yields the byte chunks in 8-byte increments. Calling the
      callable twice returns two fresh iterators (the storage_io
      retry-invocation contract).
    - ``delete`` is async.
    - ``exists`` is async; ``health`` is async.
    """

    def __init__(
        self,
        *,
        backend: str = "s3",
        capabilities: list[str] | None = None,
        raise_on_load_stream: Exception | None = None,
        stream_payload: bytes | None = None,
        health_return: bool = True,
    ) -> None:
        self.backend = backend
        self.metadata = _AdapterMetadata(
            capabilities=capabilities if capabilities is not None else ["stream"]
        )
        self._blobs: dict[str, bytes] = {}
        self._raise_on_load_stream = raise_on_load_stream
        self._stream_payload = stream_payload if stream_payload is not None else b""
        self._health_return = health_return
        self.save_stream_calls: list[tuple[str, dict, int]] = []
        self.load_stream_calls: list[str] = []
        self.delete_calls: list[str] = []
        self.exists_calls: list[str] = []
        self.health_calls = 0

    async def save_stream(
        self,
        key: str,
        chunk_reader,
        *,
        metadata: dict[str, str] | None = None,
    ) -> int:
        data = b"".join(chunk_reader())
        self.save_stream_calls.append((key, metadata or {}, len(data)))
        self._blobs[key] = data
        return len(data)

    def load_stream(self, key: str) -> Any:
        self.load_stream_calls.append(key)
        if self._raise_on_load_stream is not None:
            raise self._raise_on_load_stream
        payload = self._blobs.get(key, self._stream_payload)

        def _iter_bytes() -> Iterator[bytes]:
            for i in range(0, len(payload), 8):
                yield payload[i : i + 8]

        return _iter_bytes

    async def delete(self, key: str) -> None:
        self.delete_calls.append(key)
        self._blobs.pop(key, None)

    async def exists(self, key: str) -> bool:
        self.exists_calls.append(key)
        return key in self._blobs

    async def health(self) -> bool:
        self.health_calls += 1
        return self._health_return


class _FakeCache:
    """WorktreeCache-shaped in-memory fake."""

    PREFIX = "mahavishnu:worktree-cache:"

    def __init__(self) -> None:
        self._store: dict[str, Any] = {}
        self.invalidate_calls: list[str] = []
        self.set_calls: list[tuple[str, Any]] = []
        self.get_calls: list[str] = []

    @property
    def key_prefix(self) -> str:
        return self.PREFIX

    def _full(self, key: str) -> str:
        return key if key.startswith(self.PREFIX) else f"{self.PREFIX}{key}"

    async def get(self, key: str) -> Any:
        self.get_calls.append(key)
        return self._store.get(self._full(key))

    async def set(self, key: str, value: Any, *, ttl: int | None = None) -> None:
        self.set_calls.append((key, value))
        self._store[self._full(key)] = value

    async def delete(self, key: str) -> None:
        self._store.pop(self._full(key), None)

    async def invalidate_handle(self, handle_id: str) -> int:
        self.invalidate_calls.append(handle_id)
        prefix = f"{self.PREFIX}{handle_id}:"
        victims = [k for k in self._store if k.startswith(prefix)]
        for k in victims:
            self._store.pop(k, None)
        return len(victims)

    async def health(self) -> bool:
        return True


class FakeDharaClient:
    """In-memory Dhara thin client fake (mirrors ``test_dhara_registry``)."""

    def __init__(self) -> None:
        self._registry: dict[str, dict[str, Any]] = {}
        self._idx_principal: dict[str, set[str]] = {}
        self._idx_repo: dict[str, set[str]] = {}
        self._sql_log: list[tuple[str, dict[str, Any]]] = []
        self._schema_ready = False

    async def execute(self, sql: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._sql_log.append((sql, params or {}))
        s = " ".join(sql.split()).lower()
        if s.startswith("create table"):
            self._schema_ready = True
            return {"rowcount": 0, "status": "ok"}
        if s.startswith("insert or replace into mahavishnu_worktree_registry_idx_principal"):
            p = params or {}
            self._idx_principal.setdefault(p["principal"], set()).add(p["handle_id"])
            return {"rowcount": 1, "status": "ok"}
        if s.startswith("insert or replace into mahavishnu_worktree_registry_idx_repo"):
            p = params or {}
            self._idx_repo.setdefault(p["repo"], set()).add(p["handle_id"])
            return {"rowcount": 1, "status": "ok"}
        if s.startswith("insert or replace into mahavishnu_worktree_registry"):
            p = params or {}
            self._registry[p["handle_id"]] = dict(p)
            return {"rowcount": 1, "status": "ok"}
        if s.startswith("delete from mahavishnu_worktree_registry"):
            p = params or {}
            removed = self._registry.pop(p["handle_id"], None)
            return {"rowcount": 1 if removed else 0, "status": "ok"}
        if s.startswith("delete from mahavishnu_worktree_registry_idx_principal"):
            p = params or {}
            for s_set in self._idx_principal.values():
                s_set.discard(p["handle_id"])
            return {"rowcount": 1, "status": "ok"}
        if s.startswith("delete from mahavishnu_worktree_registry_idx_repo"):
            p = params or {}
            for s_set in self._idx_repo.values():
                s_set.discard(p["handle_id"])
            return {"rowcount": 1, "status": "ok"}
        raise ValueError(f"Unhandled SQL in fake: {sql[:80]}")

    async def query(self, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        s = " ".join(sql.split()).lower()
        if s.startswith("select * from mahavishnu_worktree_registry") and params and "handle_id" in params:
            row = self._registry.get(params["handle_id"])
            return [row] if row else []
        if s.startswith("select * from mahavishnu_worktree_registry"):
            return list(self._registry.values())
        if s.startswith("select principal") and params and "handle_id" in params:
            row = self._registry.get(params["handle_id"])
            return [row] if row else []
        if "idx_principal" in s and params and "principal" in params:
            ids = self._idx_principal.get(params["principal"], set())
            return [self._registry[i] for i in ids if i in self._registry]
        if "idx_repo" in s and params and "repo" in params:
            ids = self._idx_repo.get(params["repo"], set())
            return [self._registry[i] for i in ids if i in self._registry]
        raise ValueError(f"Unhandled SELECT in fake: {sql[:80]}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _principal(
    *,
    uid: int = 1000,
    name: str = "uid:1000",
    scopes: tuple[str, ...] = ("worktree:register",),
) -> Principal:
    return Principal(uid=uid, name=name, scopes=frozenset(scopes))


def _handle(
    *,
    handle_id: str = "h-abc",
    repo: str = "mahavishnu",
    branch: str = "feature/auth",
    sha: str = "",
    size: int = 0,
    principal: Principal | None = None,
    backend_kind: str = "s3",
    bucket: str = "b",
    key: str | None = None,
) -> WorktreeHandle:
    """Build a WorktreeHandle wired to a RemoteWorktreeRef."""
    p = principal or _principal()
    return WorktreeHandle(
        handle_id=handle_id,
        principal=p,
        repo=repo,
        branch=branch,
        base_ref="main",
        created_at=datetime.now(UTC),
        storage_ref=RemoteWorktreeRef(
            bucket=bucket,
            key=key or f"worktrees/{repo}/{branch}/{handle_id}.tar.zst",
            worktree_id=handle_id,
            backend_kind=backend_kind,  # type: ignore[arg-type]
        ),
        sha256=sha,
        bytes_size=size,
        cleanup_policy=None,
        provenance="v4",
    )


@pytest.fixture
def tmp_git_repo(tmp_path: Path, monkeypatch) -> Path:
    """Create a real git repo + redirect worktree paths into tmp_path.

    The ``get_worktree_path`` monkeypatch receives the repo path as
    its first arg. If that arg is absolute (``/private/var/folders/...``)
    pathlib's ``joinpath`` discards the prefix and we end up right
    back at the absolute path. We normalise via ``Path(*parts)``
    which preserves the absolute-prefix *only* when the FIRST part
    is absolute — giving us a stable shim that works for both the
    ``get_worktree_path(repo, branch)`` call shape AND absolute repo
    paths.
    """
    import subprocess

    wt_base = tmp_path / "wtbase"
    wt_base.mkdir()
    base_target = wt_base

    def _base() -> Path:
        return base_target

    def _path(*parts: str) -> Path:
        # Construct via Path() of each part so the absolute-arg rule
        # of joinpath doesn't bite when ``repo`` is already absolute.
        out = base_target
        for part in parts:
            # If the part is absolute, treat it as a *suffix* under
            # the test's wtbase (preserve the leaf components so the
            # unique-per-test isolation stays intact).
            p = Path(part)
            if p.is_absolute():
                # Use only the leaf components (drop the absolute
                # root) so two test runs don't collide.
                out = out.joinpath(*p.parts[1:])
            else:
                out = out.joinpath(part)
        return out

    monkeypatch.setattr(
        "mahavishnu.core.paths.get_worktree_base_path", _base
    )
    monkeypatch.setattr("mahavishnu.core.paths.get_worktree_path", _path)
    monkeypatch.setattr(remote_mod, "get_worktree_base_path", _base)
    monkeypatch.setattr(remote_mod, "get_worktree_path", _path)

    repo = tmp_path / "repo"
    repo.mkdir()
    try:
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=repo,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=repo,
            check=True,
            capture_output=True,
        )
        (repo / "README.md").write_text("hello\n")
        subprocess.run(["git", "add", "README.md"], cwd=repo, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-q", "-m", "init"], cwd=repo, check=True, capture_output=True
        )
    except Exception:
        pytest.skip("git unavailable or repo init failed")
    return repo


@pytest.fixture
def tmp_materialized_base(tmp_path: Path, monkeypatch) -> Path:
    """Pin get_worktree_base_path() (source + remote) to tmp_path/materialized."""
    target_base = tmp_path / "materialized"
    monkeypatch.setattr(
        "mahavishnu.core.paths.get_worktree_base_path",
        lambda: target_base,
    )
    monkeypatch.setattr(remote_mod, "get_worktree_base_path", lambda: target_base)
    return target_base


def _fake_create_wt_factory(worktree_dir: Path):
    """Return a stub ``_create_worktree_via_git`` that writes a sentinel file."""

    async def _fake_create_wt(*_a, **_kw):
        worktree_dir.mkdir(parents=True, exist_ok=True)
        (worktree_dir / "x.txt").write_text("y")
        return {"success": True}

    return _fake_create_wt


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


class TestSupportsStreaming:
    """``supports_streaming`` requires BOTH capability AND method presence (B-DI-04)."""

    def test_returns_true_when_capability_and_methods_present(self) -> None:
        storage = _FakeCloudStorage(capabilities=["blob", "stream", "delete"])
        assert supports_streaming(storage) is True

    def test_returns_false_when_capability_missing(self) -> None:
        storage = _FakeCloudStorage(capabilities=["blob", "delete"])
        assert supports_streaming(storage) is False

    def test_returns_false_when_methods_missing(self) -> None:
        class _NoStreaming:
            metadata = _AdapterMetadata(capabilities=["stream"])

        assert supports_streaming(_NoStreaming()) is False  # type: ignore[arg-type]

    def test_returns_false_for_none_storage(self) -> None:
        assert supports_streaming(None) is False


class TestMaxConcurrentWorktreeStreams:
    def test_constant_is_eight(self) -> None:
        assert MAX_CONCURRENT_WORKTREE_STREAMS == 8


# ---------------------------------------------------------------------------
# create_worktree_handle — streaming tests
# ---------------------------------------------------------------------------


class TestCreateWorktreeHandleStreaming:
    """``create_worktree_handle`` must stream via storage.save_stream (Phase 3)."""

    async def test_create_worktree_handle_streams_via_save_stream(
        self, tmp_git_repo, monkeypatch
    ):
        """save_stream invoked once with the right key + sha256/size/principal metadata."""
        wt_dir = remote_mod.get_worktree_path("mahavishnu", "feat-stream")
        monkeypatch.setattr(
            remote_mod, "_create_worktree_via_git", _fake_create_wt_factory(wt_dir)
        )

        storage = _FakeCloudStorage(backend="s3")
        dhara = FakeDharaClient()
        provider = RemoteWorktreeProvider(
            storage=storage,
            cache=_FakeCache(),
            dhara_client=dhara,
            backend="s3",
        )
        principal = _principal()

        handle = await provider.create_worktree_handle(
            repo="mahavishnu",
            branch="feat-stream",
            base_ref="HEAD",
            principal=principal,
        )

        # save_stream was called once with the right key shape.
        assert len(storage.save_stream_calls) == 1, (
            f"expected one save_stream call, got {storage.save_stream_calls}"
        )
        key, metadata, byte_count = storage.save_stream_calls[0]
        assert key.startswith("worktrees/mahavishnu/feat-stream/")
        assert key.endswith(".tar.zst")
        # Metadata: sha256 + size + principal
        assert metadata["sha256"] == handle.sha256
        assert int(metadata["size"]) == handle.bytes_size
        assert metadata["principal"] == principal.name
        assert byte_count == handle.bytes_size
        # Handle carries a RemoteWorktreeRef + the right backend label.
        assert handle.bytes_size > 0
        assert handle.sha256
        # Dhara registration was attempted by the production code.
        rows = await dhara.query(
            "SELECT * FROM mahavishnu_worktree_registry WHERE handle_id = :h",
            {"h": handle.handle_id},
        )
        assert len(rows) == 1

    async def test_create_worktree_handle_emits_serialize_metric_with_backend_label(
        self, tmp_git_repo, monkeypatch
    ):
        """``record_streaming_op`` receives the SERIALIZE op + backend label."""
        from mahavishnu.observability import metrics as metrics_mod
        from mahavishnu.observability.metrics import StreamingOp

        wt_dir = remote_mod.get_worktree_path("mahavishnu", "feat")
        monkeypatch.setattr(
            remote_mod, "_create_worktree_via_git", _fake_create_wt_factory(wt_dir)
        )

        captured: list[tuple] = []

        def _capture(op, backend, duration_ms, bytes_processed, *, success):
            captured.append((op, backend, duration_ms, bytes_processed, success))

        # Patch at the source module — create_worktree_handle imports
        # ``record_streaming_op`` from ``mahavishnu.observability.metrics``
        # *inside* the function body, so each call re-imports and the
        # monkeypatch on the source module attribute is observed by
        # the in-function ``from ... import`` lookup.
        monkeypatch.setattr(metrics_mod, "record_streaming_op", _capture)

        storage = _FakeCloudStorage(backend="gcs", capabilities=["stream"])
        provider = RemoteWorktreeProvider(
            storage=storage, cache=_FakeCache(), backend="gcs"
        )

        try:
            handle = await provider.create_worktree_handle(
                repo="mahavishnu",
                branch="feat",
                base_ref="HEAD",
                principal=_principal(),
            )
        except Exception as exc:  # noqa: BLE001 — diagnostic
            pytest.fail(f"create_worktree_handle raised: {type(exc).__name__}: {exc}")

        # Wait briefly for the producer-thread-state in case metrics are
        # emitted after the function returns (defensive — current code
        # emits synchronously).
        assert handle.bytes_size > 0, f"handle has zero bytes (handle={handle})"
        assert len(captured) == 1, (
            f"expected one metric; got captured={captured}; "
            f"handle.handle_id={handle.handle_id}, "
            f"handle.bytes_size={handle.bytes_size}"
        )
        op, backend, _duration_ms, bytes_processed, success = captured[0]
        assert op == StreamingOp.SERIALIZE
        assert backend == "gcs"
        assert bytes_processed > 0
        assert success is True

    async def test_create_worktree_handle_validates_key_length_mhv220(
        self, tmp_git_repo, monkeypatch
    ):
        """Repo name longer than 256 bytes → MHV-220 WorktreeError BEFORE upload."""
        from mahavishnu.core.errors import ErrorCode, WorktreeError

        # 240-char repo pushes the storage key past the 256-byte cap.
        # The key-length check fires BEFORE any git worktree IO so we
        # don't depend on git/paths being writable for pathological
        # inputs.
        storage = _FakeCloudStorage()
        provider = RemoteWorktreeProvider(
            storage=storage, cache=_FakeCache(), backend="s3"
        )

        long_repo = "r" * 240
        with pytest.raises(WorktreeError) as exc_info:
            await provider.create_worktree_handle(
                repo=long_repo,
                branch="b",
                base_ref="HEAD",
                principal=_principal(),
            )
        assert exc_info.value.error_code == ErrorCode.WORKTREE_BUNDLE_STORAGE_KEY_TOO_LONG
        # No save_stream call happened (validation aborted before upload).
        assert storage.save_stream_calls == []

    async def test_create_worktree_handle_enforces_size_cap_mhv221(
        self, tmp_git_repo, monkeypatch
    ):
        """Bundle size > MAX_BUNDLE_BYTES_STOPGAP → MHV-221 WorktreeError."""
        from mahavishnu.core.errors import ErrorCode, WorktreeError

        wt_dir = remote_mod.get_worktree_path(str(tmp_git_repo), "b")
        monkeypatch.setattr(
            remote_mod, "_create_worktree_via_git", _fake_create_wt_factory(wt_dir)
        )

        storage = _FakeCloudStorage()
        provider = RemoteWorktreeProvider(
            storage=storage, cache=_FakeCache(), backend="s3"
        )

        oversized = remote_mod.MAX_BUNDLE_BYTES_STOPGAP + 1

        @contextmanager
        def _fake_serialize(_source, *, compression_level=3):
            tmp = tmp_git_repo.parent / "fake.tar.zst"
            tmp.write_bytes(b"x")
            yield tmp, oversized, "0" * 64

        # Patch on the captured reference in remote_mod so the size
        # guard trips before save_stream is called.
        monkeypatch.setattr(remote_mod, "serialize_worktree_tar", _fake_serialize)

        with pytest.raises(WorktreeError) as exc_info:
            await provider.create_worktree_handle(
                repo=str(tmp_git_repo),
                branch="b",
                base_ref="HEAD",
                principal=_principal(),
            )
        assert exc_info.value.error_code == ErrorCode.WORKTREE_BUNDLE_STOPGAP_TOO_LARGE


# ---------------------------------------------------------------------------
# fetch — streaming tests (Task C.7 — bounded queue ACTIVE)
# ---------------------------------------------------------------------------


class TestFetchStreaming:
    """``fetch`` drains storage.load_stream through a bounded queue (B-DI-10)."""

    async def test_fetch_uses_load_stream(self, tmp_materialized_base):
        """fetch() invokes storage.load_stream — not download."""
        from mahavishnu.core.worktree_providers import storage_io

        wt = tmp_materialized_base.parent / "src"
        wt.mkdir()
        (wt / "README.md").write_text("hello\n")
        (wt / "src").mkdir(exist_ok=True)
        (wt / "src" / "main.py").write_text("print('hi')\n")

        with storage_io.serialize_worktree_tar(wt) as (temp_path, _size, sha):
            payload = temp_path.read_bytes()

        storage = _FakeCloudStorage(
            backend="azure", stream_payload=payload
        )
        cache = _FakeCache()
        provider = RemoteWorktreeProvider(
            storage=storage, cache=cache, backend="azure"
        )
        handle = _handle(handle_id="h-stream-1", sha=sha, size=len(payload))

        ref = await provider.fetch(handle)

        # load_stream was called with the right key
        assert len(storage.load_stream_calls) == 1
        assert storage.load_stream_calls[0].endswith("/h-stream-1.tar.zst")
        # materialised with file contents
        assert Path(ref.path).exists()
        assert (Path(ref.path) / "README.md").read_text() == "hello\n"
        # Cache was set after success with the R2-20 unified key shape
        assert cache.set_calls and cache.set_calls[0][0].startswith("materialized:")

    async def test_fetch_uses_bounded_queue_producer_consumer(
        self, tmp_materialized_base
    ):
        """Verify queue.Queue(maxsize=4) is the active handoff (B-DI-10)."""
        import queue as queue_mod

        captured_q: dict[str, Any] = {}

        def _recording_target(stream_iter, q):
            captured_q["maxsize"] = q.maxsize
            try:
                for chunk in stream_iter:
                    q.put(chunk)
            finally:
                q.put(remote_mod._STREAM_SENTINEL)

        q = queue_mod.Queue(maxsize=4)
        recorder_iter = iter([b"chunk1", b"chunk2"])
        _recording_target(recorder_iter, q)
        assert captured_q["maxsize"] == 4
        assert q.get_nowait() == b"chunk1"
        assert q.get_nowait() == b"chunk2"
        assert q.get_nowait() is remote_mod._STREAM_SENTINEL

    async def test_fetch_emits_deserialize_metric_with_backend_label(
        self, tmp_materialized_base, monkeypatch
    ):
        """``record_streaming_op`` receives DESERIALIZE + the backend label."""
        from mahavishnu.core.worktree_providers import storage_io
        from mahavishnu.observability import metrics as metrics_mod
        from mahavishnu.observability.metrics import StreamingOp

        wt = tmp_materialized_base.parent / "src"
        wt.mkdir()
        (wt / "x.txt").write_text("y")
        with storage_io.serialize_worktree_tar(wt) as (temp_path, _size, sha):
            payload = temp_path.read_bytes()

        storage = _FakeCloudStorage(stream_payload=payload)
        captured: list[tuple] = []

        def _capture(op, backend, duration_ms, bytes_processed, *, success):
            captured.append((op, backend, duration_ms, bytes_processed, success))

        monkeypatch.setattr(metrics_mod, "record_streaming_op", _capture)

        provider = RemoteWorktreeProvider(
            storage=storage, cache=_FakeCache(), backend="s3"
        )
        handle = _handle(sha=sha, size=len(payload))
        await provider.fetch(handle)

        assert len(captured) == 1, f"expected one metric, got {captured}"
        op, backend, _duration_ms, bytes_processed, success = captured[0]
        assert op == StreamingOp.DESERIALIZE
        assert backend == "s3"
        assert bytes_processed == len(payload)
        assert success is True

    async def test_fetch_raises_on_legacy_gzip_magic_mhv213(self, tmp_materialized_base):
        """First chunk starts with \\x1f\\x8b → MHV-213."""
        from mahavishnu.core.errors import ErrorCode, WorktreeError

        storage = _FakeCloudStorage(
            stream_payload=b"\x1f\x8b\x08\x00rest-of-gzip"
        )
        provider = RemoteWorktreeProvider(storage=storage, cache=_FakeCache())

        handle = _handle()
        with pytest.raises(WorktreeError) as exc_info:
            await provider.fetch(handle)
        assert exc_info.value.error_code == ErrorCode.WORKTREE_BUNDLE_LEGACY_PHASE2

    async def test_fetch_raises_on_codec_unavailable_mhv223(
        self, tmp_materialized_base, monkeypatch
    ):
        """Forced zstandard ImportError → MHV-223 WorktreeError."""
        from mahavishnu.core.errors import ErrorCode, WorktreeError

        import builtins

        real_import = builtins.__import__

        def _fake_import(name, *args, **kwargs):
            if name == "zstandard" or name.startswith("zstandard."):
                raise ImportError("simulated missing zstandard")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _fake_import)

        storage = _FakeCloudStorage(stream_payload=b"\x00" * 64)
        provider = RemoteWorktreeProvider(storage=storage, cache=_FakeCache())

        with pytest.raises(WorktreeError) as exc_info:
            await provider.fetch(_handle())
        assert exc_info.value.error_code == ErrorCode.WORKTREE_BUNDLE_CODEC_UNAVAILABLE

    async def test_fetch_raises_not_found_mhv222(self, tmp_materialized_base):
        """storage.load_stream raises FileNotFoundError → MHV-222."""
        from mahavishnu.core.errors import ErrorCode, WorktreeError

        storage = _FakeCloudStorage(
            raise_on_load_stream=FileNotFoundError("no such key")
        )
        provider = RemoteWorktreeProvider(storage=storage, cache=_FakeCache())

        with pytest.raises(WorktreeError) as exc_info:
            await provider.fetch(_handle())
        assert exc_info.value.error_code == ErrorCode.WORKTREE_BUNDLE_NOT_FOUND

    async def test_fetch_cache_hit_skips_streaming(self, tmp_materialized_base):
        """Positive cache entry short-circuits load_stream entirely."""
        cache = _FakeCache()
        cached_dir = tmp_materialized_base / "cached"
        cached_dir.mkdir(parents=True, exist_ok=True)
        (cached_dir / "a.txt").write_text("hit")
        handle = _handle(handle_id="h-hit")
        await cache.set(f"materialized:{handle.handle_id}", str(cached_dir))

        storage = _FakeCloudStorage()
        provider = RemoteWorktreeProvider(storage=storage, cache=cache)

        ref = await provider.fetch(handle)
        assert ref.path == cached_dir
        assert storage.load_stream_calls == []


# ---------------------------------------------------------------------------
# remove_handle — covers storage.delete + cache invalidate + Dhara remove
# ---------------------------------------------------------------------------


class TestRemoveHandle:
    """``remove_handle`` calls storage.delete, invalidates cache, removes from Dhara."""

    async def test_remove_handle_calls_storage_delete_and_dhara_remove(self) -> None:
        storage = _FakeCloudStorage()
        cache = _FakeCache()
        dhara = FakeDharaClient()
        provider = RemoteWorktreeProvider(
            storage=storage,
            cache=cache,
            dhara_client=dhara,
            backend="s3",
        )
        from mahavishnu.core.worktree_providers.dhara_registry import (
            register_handles as dhara_register,
        )

        principal_full = _principal(
            scopes=("worktree:register", "worktree:remove"),
        )
        handle = _handle(
            handle_id="h-rem",
            sha="a" * 64,
            size=42,
            principal=principal_full,
        )
        # Seed storage with a fake blob so delete() can find the key.
        storage._blobs[handle.storage_ref.key] = b"x"
        await dhara_register(dhara, [handle], caller=principal_full)

        removed = await provider.remove_handle(handle, caller=principal_full)
        assert removed is True
        # Storage delete called with the right key
        assert handle.storage_ref.key in storage.delete_calls
        assert handle.storage_ref.key not in storage._blobs
        # Cache invalidate called
        assert cache.invalidate_calls == [handle.handle_id]
        # Dhara primary row removed
        rows = await dhara.query(
            "SELECT * FROM mahavishnu_worktree_registry WHERE handle_id = :h",
            {"h": handle.handle_id},
        )
        assert rows == []


# ---------------------------------------------------------------------------
# health — HealthReport shape + streaming-capability warning
# ---------------------------------------------------------------------------


class TestHealthStreamingProbe:
    """``health()`` returns a HealthReport with the streaming-capability warning."""

    async def test_health_reports_streaming_capability_present(self) -> None:
        storage = _FakeCloudStorage(capabilities=["stream"])
        provider = RemoteWorktreeProvider(storage=storage, cache=_FakeCache())

        report = await provider.health()
        assert isinstance(report, HealthReport)
        assert bool(report) is True
        # No streaming-capability warning when adapter advertises it
        assert all(w["kind"] != "streaming_capability_missing" for w in report.warnings)

    async def test_health_reports_streaming_capability_missing(self) -> None:
        storage = _FakeCloudStorage(capabilities=["blob", "delete"])
        provider = RemoteWorktreeProvider(storage=storage, cache=_FakeCache())

        report = await provider.health()
        kinds = [w["kind"] for w in report.warnings]
        assert "streaming_capability_missing" in kinds
        assert bool(report) is False

    async def test_health_marks_unhealthy_when_storage_health_fails(self) -> None:
        storage = _FakeCloudStorage(health_return=False)
        provider = RemoteWorktreeProvider(storage=storage, cache=_FakeCache())

        report = await provider.health()
        assert report.healthy is False
        assert storage.health_calls == 1


# ---------------------------------------------------------------------------
# list_handles / lock — kept from v1 surface
# ---------------------------------------------------------------------------


class TestListHandles:
    async def test_list_handles_requires_caller(self) -> None:
        provider = RemoteWorktreeProvider(
            storage=_FakeCloudStorage(), cache=_FakeCache()
        )
        with pytest.raises(PermissionError):
            await provider.list_handles()


class TestLockDelegation:
    async def test_lock_raises_when_no_local_provider(self) -> None:
        provider = RemoteWorktreeProvider(
            storage=_FakeCloudStorage(), cache=_FakeCache()
        )
        with pytest.raises(NotImplementedError):
            await provider.lock("mahavishnu", "feature/x")
