"""Unit tests for mahavishnu/core/worktree_providers/local.py.

Module renamed from ``direct_git.py`` to ``local.py`` in ADR 015 v4
Phase 0.5; the class ``DirectGitWorktreeProvider`` is preserved as a
1-release deprecated alias.

Mocks asyncio.create_subprocess_exec so no real git commands are run.

NOTE: There are existing complementary tests in tests/unit/test_worktree_providers.py
that cover the happy paths. These tests focus on additional behavior such as
provider identity, health checks, and edge cases in the porcelain parser.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterator
from unittest.mock import AsyncMock, patch

import pytest

from mahavishnu.auth import Principal
from mahavishnu.core.worktree_providers.base import WorktreeProvider
from mahavishnu.core.worktree_providers.local import (
    DirectGitWorktreeProvider,
    HealthReport,
    LocalWorktreeProvider,
    MAX_CONCURRENT_WORKTREE_STREAMS,
    supports_streaming,
)
from mahavishnu.core.worktree_providers.errors import (
    WorktreeCreationError,
    WorktreeOperationError,
)

pytestmark = pytest.mark.unit


# ============================== Helpers ==============================


def _fake_process(returncode: int = 0, stdout: bytes = b"", stderr: bytes = b""):
    """Build a fake subprocess return value."""
    p = AsyncMock()
    p.communicate = AsyncMock(return_value=(stdout, stderr))
    p.returncode = returncode
    return p


# ============================== Init / identity ==============================


class TestInitAndIdentity:
    """Sanity checks on construction and identity."""

    def test_construction_sets_git_executable(self):
        p = DirectGitWorktreeProvider()
        assert p._git_executable == "git"

    def test_provider_name(self):
        # Static method
        assert DirectGitWorktreeProvider.provider_name() == "DirectGitWorktreeProvider"
        # Also accessible from instance
        assert DirectGitWorktreeProvider().provider_name() == "DirectGitWorktreeProvider"

    def test_inherits_from_base(self):
        assert isinstance(DirectGitWorktreeProvider(), WorktreeProvider)


# ============================== health_check ==============================


class TestHealthCheck:
    """Tests for synchronous health_check."""

    def test_health_check_true_when_git_present(self):
        p = DirectGitWorktreeProvider()
        with patch("shutil.which", return_value="/usr/bin/git"):
            assert p.health_check() is True

    def test_health_check_false_when_git_missing(self):
        p = DirectGitWorktreeProvider()
        with patch("shutil.which", return_value=None):
            assert p.health_check() is False

    def test_health_check_swallows_exceptions(self):
        p = DirectGitWorktreeProvider()
        with patch("shutil.which", side_effect=RuntimeError("nope")):
            assert p.health_check() is False


# ============================== create_worktree ==============================


class TestCreateWorktree:
    """Tests for create_worktree."""

    async def test_command_includes_repository_path(self):
        p = DirectGitWorktreeProvider()
        process = _fake_process()
        with patch(
            "asyncio.create_subprocess_exec",
            AsyncMock(return_value=process),
        ) as mock_exec:
            await p.create_worktree(Path("/myrepo"), "feat", Path("/wt/feat"), True)

        cmd = mock_exec.call_args[0]
        assert "git" in cmd
        assert "-C" in cmd
        assert "/myrepo" in cmd
        assert "feat" in cmd

    async def test_create_branch_flag_b(self):
        p = DirectGitWorktreeProvider()
        process = _fake_process()
        with patch(
            "asyncio.create_subprocess_exec",
            AsyncMock(return_value=process),
        ) as mock_exec:
            await p.create_worktree(Path("/r"), "newbranch", Path("/wt"), create_branch=True)

        cmd = mock_exec.call_args[0]
        # -b should be present but -B (uppercase) should NOT be present
        assert "-b" in cmd
        assert "-B" not in cmd

    async def test_existing_branch_uses_capital_B(self):
        p = DirectGitWorktreeProvider()
        process = _fake_process()
        with patch(
            "asyncio.create_subprocess_exec",
            AsyncMock(return_value=process),
        ) as mock_exec:
            await p.create_worktree(Path("/r"), "main", Path("/wt"), create_branch=False)

        cmd = mock_exec.call_args[0]
        assert "-B" in cmd

    async def test_success_returns_metadata(self):
        p = DirectGitWorktreeProvider()
        process = _fake_process()
        with patch(
            "asyncio.create_subprocess_exec",
            AsyncMock(return_value=process),
        ):
            result = await p.create_worktree(Path("/r"), "br", Path("/wt"), create_branch=True)

        assert result["success"] is True
        assert result["branch"] == "br"
        assert result["worktree_path"] == "/wt"
        assert result["provider"] == "DirectGitWorktreeProvider"

    async def test_failure_raises_creation_error(self):
        p = DirectGitWorktreeProvider()
        process = _fake_process(returncode=1, stderr=b"already exists")
        with (
            patch(
                "asyncio.create_subprocess_exec",
                AsyncMock(return_value=process),
            ),
            pytest.raises(WorktreeCreationError, match="Failed to create worktree"),
        ):
            await p.create_worktree(Path("/r"), "b", Path("/wt"), True)

    async def test_failure_with_empty_stderr(self):
        """Empty stderr should still raise with a generic message."""
        p = DirectGitWorktreeProvider()
        process = _fake_process(returncode=1, stderr=b"")
        with (
            patch(
                "asyncio.create_subprocess_exec",
                AsyncMock(return_value=process),
            ),
            pytest.raises(WorktreeCreationError),
        ):
            await p.create_worktree(Path("/r"), "b", Path("/wt"), True)


# ============================== remove_worktree ==============================


class TestRemoveWorktree:
    """Tests for remove_worktree."""

    async def test_success_returns_metadata(self):
        p = DirectGitWorktreeProvider()
        process = _fake_process()
        with patch(
            "asyncio.create_subprocess_exec",
            AsyncMock(return_value=process),
        ):
            result = await p.remove_worktree(Path("/r"), Path("/wt"))

        assert result["success"] is True
        assert result["removed_path"] == "/wt"
        assert result["provider"] == "DirectGitWorktreeProvider"

    async def test_force_flag_added(self):
        p = DirectGitWorktreeProvider()
        process = _fake_process()
        with patch(
            "asyncio.create_subprocess_exec",
            AsyncMock(return_value=process),
        ) as mock_exec:
            await p.remove_worktree(Path("/r"), Path("/wt"), force=True)

        cmd = mock_exec.call_args[0]
        assert "--force" in cmd

    async def test_without_force_no_flag(self):
        p = DirectGitWorktreeProvider()
        process = _fake_process()
        with patch(
            "asyncio.create_subprocess_exec",
            AsyncMock(return_value=process),
        ) as mock_exec:
            await p.remove_worktree(Path("/r"), Path("/wt"), force=False)

        cmd = mock_exec.call_args[0]
        assert "--force" not in cmd

    async def test_failure_raises_operation_error(self):
        p = DirectGitWorktreeProvider()
        process = _fake_process(returncode=1, stderr=b"locked")
        with (
            patch(
                "asyncio.create_subprocess_exec",
                AsyncMock(return_value=process),
            ),
            pytest.raises(WorktreeOperationError, match="Failed to remove worktree"),
        ):
            await p.remove_worktree(Path("/r"), Path("/wt"))


# ============================== list_worktrees ==============================


class TestListWorktrees:
    """Tests for list_worktrees and porcelain parsing."""

    async def test_empty_output_returns_empty_list(self):
        p = DirectGitWorktreeProvider()
        process = _fake_process(stdout=b"")
        with patch(
            "asyncio.create_subprocess_exec",
            AsyncMock(return_value=process),
        ):
            result = await p.list_worktrees(Path("/r"))

        assert result["success"] is True
        assert result["worktrees"] == []

    async def test_parses_valid_porcelain_output(self):
        p = DirectGitWorktreeProvider()
        output = b"/repo/main main abc123 ok\n/repo/feat feature def456 dirty\n"
        process = _fake_process(stdout=output)
        with patch(
            "asyncio.create_subprocess_exec",
            AsyncMock(return_value=process),
        ):
            result = await p.list_worktrees(Path("/repo"))

        assert len(result["worktrees"]) == 2
        first = result["worktrees"][0]
        assert first["path"] == "/repo/main"
        assert first["branch"] == "main"
        assert first["commit"] == "abc123"
        assert first["status"] == "ok"

    async def test_skips_blank_lines(self):
        p = DirectGitWorktreeProvider()
        # blank line should be skipped
        output = b"/r/a branch1 commit1 ok\n\n/r/b branch2 commit2 ok\n"
        process = _fake_process(stdout=output)
        with patch(
            "asyncio.create_subprocess_exec",
            AsyncMock(return_value=process),
        ):
            result = await p.list_worktrees(Path("/r"))
        assert len(result["worktrees"]) == 2

    async def test_skips_lines_with_too_few_parts(self):
        p = DirectGitWorktreeProvider()
        # Lines with < 4 parts are silently ignored
        output = b"only_one\ntwo parts\nthree parts here\n/r/full path branch commit ok\n"
        process = _fake_process(stdout=output)
        with patch(
            "asyncio.create_subprocess_exec",
            AsyncMock(return_value=process),
        ):
            result = await p.list_worktrees(Path("/r"))
        # Only 1 valid worktree line (4 parts present)
        assert len(result["worktrees"]) == 1

    async def test_provider_name_in_result(self):
        p = DirectGitWorktreeProvider()
        process = _fake_process(stdout=b"")
        with patch(
            "asyncio.create_subprocess_exec",
            AsyncMock(return_value=process),
        ):
            result = await p.list_worktrees(Path("/r"))
        assert result["provider"] == "DirectGitWorktreeProvider"

    async def test_failure_raises_operation_error(self):
        p = DirectGitWorktreeProvider()
        process = _fake_process(returncode=1, stderr=b"not a git repo")
        with (
            patch(
                "asyncio.create_subprocess_exec",
                AsyncMock(return_value=process),
            ),
            pytest.raises(WorktreeOperationError, match="Failed to list worktrees"),
        ):
            await p.list_worktrees(Path("/r"))

    async def test_command_uses_porcelain_flag(self):
        p = DirectGitWorktreeProvider()
        process = _fake_process(stdout=b"")
        with patch(
            "asyncio.create_subprocess_exec",
            AsyncMock(return_value=process),
        ) as mock_exec:
            await p.list_worktrees(Path("/r"))

        cmd = mock_exec.call_args[0]
        assert "--porcelain" in cmd
        assert "worktree" in cmd
        assert "list" in cmd


# ===========================================================================
# Phase 3 (ADR 015 v4 Task C.6) — LocalWorktreeProvider streaming tests
# ===========================================================================

try:
    import zstandard  # noqa: F401
except ImportError:
    pytest.skip(
        "zstandard required; uv sync --group compression-zstd",
        allow_module_level=True,
    )


# ---------------------------------------------------------------------------
# Lightweight storage / cache / registry fakes (avoid oneiric dependency)
# ---------------------------------------------------------------------------


@dataclass
class _AdapterMetadata:
    capabilities: list[str] = field(default_factory=list)


class _FakeStorage:
    """Fake LocalStorageAdapter — captures save_stream / load_stream calls."""

    def __init__(
        self,
        *,
        capabilities: list[str] | None = None,
        raise_on_read: Exception | None = None,
        stream_payload: bytes | None = None,
    ) -> None:
        self.metadata = _AdapterMetadata(
            capabilities=capabilities if capabilities is not None else ["stream"]
        )
        self.save_stream_calls: list[tuple[str, dict, int]] = []
        self.load_stream_calls: list[str] = []
        self._raise_on_read = raise_on_read
        self._stream_payload = stream_payload if stream_payload is not None else b""

    def save_stream(
        self,
        key: str,
        chunk_reader,
        *,
        metadata: dict[str, str] | None = None,
    ) -> int:
        data = b"".join(chunk_reader())
        self.save_stream_calls.append((key, metadata or {}, len(data)))
        return len(data)

    def load_stream(self, key: str) -> Iterator[bytes]:
        # NOTE: must NOT be a generator function. If this body has
        # ``yield`` directly, calling ``load_stream(key)`` would
        # return a generator object without running the body — so
        # the raise-on-missing-key would only fire on first
        # ``next()``, past the ``stream_iter = ...`` assignment
        # in ``fetch`` (and past the try/except that maps the
        # not-found path to MHV-222). Splitting the chunker into a
        # separate helper keeps the call site eager-raising.
        self.load_stream_calls.append(key)
        if self._raise_on_read is not None:
            # Raise synchronously (matches oneiric's
            # LocalStorageAdapter.load_stream which raises on
            # call when the key does not exist).
            raise self._raise_on_read
        return self._stream_chunks(key)

    def _stream_chunks(self, _key: str) -> Iterator[bytes]:
        for i in range(0, len(self._stream_payload), 8):
            yield self._stream_payload[i : i + 8]

    async def health(self) -> bool:
        return True

    async def save(self, key: str, data: bytes) -> str:
        return key

    async def read(self, key: str) -> bytes | None:
        return self._stream_payload or None


class _FakeCache:
    def __init__(self) -> None:
        self._store: dict[str, str] = {}
        self.get_calls = 0
        self.set_calls = 0

    async def get(self, key: str) -> str | None:
        self.get_calls += 1
        return self._store.get(key)

    async def set(self, key: str, value: str) -> None:
        self.set_calls += 1
        self._store[key] = value

    async def invalidate_handle(self, handle_id: str) -> int:
        prefix = f"materialized:{handle_id}"
        keys = [k for k in self._store if k.startswith(prefix)]
        for k in keys:
            del self._store[k]
        return len(keys)

    async def health(self) -> bool:
        return True


class _FakeDharaClient:
    """Stand-in for the Dhara thin client. Just records execute() calls."""

    def __init__(self) -> None:
        self.executes: list[tuple[str, dict | None]] = []

    async def execute(self, sql: str, params: dict | None = None) -> None:
        # ``params`` is optional because schema-setup calls pass only
        # the SQL string (no bound parameters) per dhara_registry.
        self.executes.append((sql, params))

    async def query(self, sql: str, params: dict | None = None) -> list[dict]:
        return []


def _make_principal(name: str = "test-principal", uid: int = 1000) -> Principal:
    return Principal(
        uid=uid,
        name=name,
        scopes=frozenset({"worktree:register", "worktree:remove"}),
    )


def _make_handle(
    *,
    handle_id: str = "abcd1234",
    repo: str = "mahavishnu",
    branch: str = "feature-x",
    sha: str = "0" * 64,
    size: int = 1024,
    wt_path: Path | None = None,
    principal: Principal | None = None,
):
    """Build a WorktreeHandle for fetch tests without Dhara round-trip."""
    from mahavishnu.core.worktree_providers.types import (
        LocalWorktreeRef,
        WorktreeHandle,
    )

    if wt_path is None:
        wt_path = Path("/tmp/fake-wt")
    return WorktreeHandle(
        handle_id=handle_id,
        principal=principal or _make_principal(),
        repo=repo,
        branch=branch,
        base_ref="main",
        created_at=datetime.now(UTC),
        storage_ref=LocalWorktreeRef(path=wt_path, worktree_id=handle_id),
        sha256=sha,
        bytes_size=size,
        cleanup_policy=None,
        provenance="v4",
    )


def _make_local_worktree(tmp_path: Path) -> Path:
    """Materialize a tiny worktree on disk for serialize_worktree_tar."""
    wt = tmp_path / "worktree"
    wt.mkdir(parents=True, exist_ok=True)
    (wt / "README.md").write_text("hello\n")
    (wt / "src").mkdir(exist_ok=True)
    (wt / "src" / "main.py").write_text("print('hi')\n")
    return wt


class _NoopAsyncCtx:
    """Async context manager that does nothing on entry/exit.

    Placeholder kept for future producer-task wiring; not currently
    used in the local-provider tests (the bounded queue is a sync
    queue for the local adapter).
    """

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


# ---------------------------------------------------------------------------
# Module-level helper tests
# ---------------------------------------------------------------------------


class TestSupportsStreaming:
    """``supports_streaming`` requires BOTH capability AND method presence (B-DI-04)."""

    def test_returns_true_when_capability_and_methods_present(self):
        storage = _FakeStorage(capabilities=["blob", "stream", "delete"])
        assert supports_streaming(storage) is True

    def test_returns_false_when_capability_missing(self):
        storage = _FakeStorage(capabilities=["blob", "delete"])
        # Methods exist but capability missing — adapter advertised
        # no streaming support so the stopgap path is used.
        assert supports_streaming(storage) is False

    def test_returns_false_when_methods_missing(self):
        # Capability advertised but methods missing — adapter is
        # broken / partial. Reject so the stopgap path is used.
        class _BrokenStorage:
            metadata = _AdapterMetadata(capabilities=["stream"])
            # No save_stream / load_stream defined

        assert supports_streaming(_BrokenStorage()) is False

    def test_returns_false_for_none_storage(self):
        assert supports_streaming(None) is False

    def test_returns_false_for_object_without_metadata(self):
        bare = object()
        assert supports_streaming(bare) is False


# ---------------------------------------------------------------------------
# create_worktree_handle — streaming tests
# ---------------------------------------------------------------------------


class TestCreateWorktreeHandleStreaming:
    """``create_worktree_handle`` must stream via storage.save_stream (Phase 3)."""

    async def test_create_worktree_handle_streams_via_save_stream(
        self, tmp_path, monkeypatch
    ):
        from mahavishnu.core.worktree_providers import local as local_mod

        # Pin both the worktree base and the per-worktree path under
        # the same temp dir so the Dhara path-validation allowlist
        # accepts the storage path. (Dhara rejects paths outside the
        # configured worktree base; the test must keep them aligned.)
        wt_base = tmp_path / "wtbase"
        wt_base.mkdir()
        monkeypatch.setattr(
            "mahavishnu.core.paths.get_worktree_base_path",
            lambda: wt_base,
        )
        monkeypatch.setattr(
            "mahavishnu.core.paths.get_worktree_path",
            lambda *parts: wt_base.joinpath(*parts),
        )

        # Patch _create_worktree_via_git to a no-op that just
        # materialises a small file inside the worktree path.
        async def _fake_create_wt(*_a, **_kw):
            wt = wt_base / "mahavishnu" / "feat-stream"
            wt.mkdir(parents=True, exist_ok=True)
            (wt / "x.txt").write_text("y")
            return {"success": True}

        monkeypatch.setattr(
            local_mod, "_create_worktree_via_git", _fake_create_wt
        )

        storage = _FakeStorage(capabilities=["stream"])
        dhara = _FakeDharaClient()
        provider = LocalWorktreeProvider(
            storage=storage, dhara_client=dhara, cache=_FakeCache()
        )
        principal = _make_principal()

        handle = await provider.create_worktree_handle(
            repo="mahavishnu",
            branch="feat-stream",
            base_ref="main",
            principal=principal,
        )

        # save_stream was called once with the right key shape
        assert len(storage.save_stream_calls) == 1
        key, metadata, byte_count = storage.save_stream_calls[0]
        assert key.startswith("worktrees/mahavishnu/feat-stream/")
        assert key.endswith(".tar.zst")
        assert "sha256" in metadata
        assert "size" in metadata
        assert byte_count > 0
        # handle.sha256 matches the metadata sha256
        assert handle.sha256 == metadata["sha256"]
        # handle.bytes_size matches the metadata size
        assert handle.bytes_size == int(metadata["size"])
        # Dhara registration was attempted (3 INSERTs per handle
        # plus the 3 schema-setup statements from _ensure_schema_async).
        # Filter to only INSERT statements to be robust to ordering.
        inserts = [e for e in dhara.executes if "INSERT" in e[0]]
        assert len(inserts) == 3

    async def test_create_worktree_handle_emits_streaming_op_metric(
        self, tmp_path, monkeypatch
    ):
        from mahavishnu.core.worktree_providers import local as local_mod
        from mahavishnu.observability import metrics as metrics_mod

        fake_wt = tmp_path / "wt"
        fake_wt.mkdir()
        monkeypatch.setattr(
            "mahavishnu.core.paths.get_worktree_path",
            lambda *parts: fake_wt,
        )
        monkeypatch.setattr(
            "mahavishnu.core.paths.get_worktree_base_path",
            lambda: tmp_path / "base",
        )

        async def _fake_create_wt(*_a, **_kw):
            (fake_wt / "x.txt").write_text("y")
            return {"success": True}

        monkeypatch.setattr(
            local_mod, "_create_worktree_via_git", _fake_create_wt
        )

        captured: list[tuple] = []

        from mahavishnu.observability.metrics import StreamingOp

        def _capture(op, backend, duration_ms, bytes_processed, *, success):
            captured.append((op, backend, duration_ms, bytes_processed, success))

        # Patch at the source module — create_worktree_handle imports
        # record_streaming_op from mahavishnu.observability.metrics
        # inside the function, so monkeypatching local_mod.record_streaming_op
        # has no effect.
        monkeypatch.setattr(metrics_mod, "record_streaming_op", _capture)

        storage = _FakeStorage(capabilities=["stream"])
        provider = LocalWorktreeProvider(storage=storage)
        principal = _make_principal()

        await provider.create_worktree_handle(
            repo="r", branch="b", base_ref="main", principal=principal
        )

        assert len(captured) == 1
        op, backend, _duration_ms, bytes_processed, success = captured[0]
        assert op == StreamingOp.SERIALIZE
        assert backend == "local"
        assert bytes_processed > 0
        assert success is True

    async def test_create_worktree_handle_validates_key_length_mhv220(
        self, tmp_path, monkeypatch
    ):
        from mahavishnu.core.errors import ErrorCode, WorktreeError
        from mahavishnu.core.worktree_providers import local as local_mod

        fake_wt = tmp_path / "wt"
        fake_wt.mkdir()
        monkeypatch.setattr(
            "mahavishnu.core.paths.get_worktree_path",
            lambda *parts: fake_wt,
        )
        monkeypatch.setattr(
            "mahavishnu.core.paths.get_worktree_base_path",
            lambda: tmp_path / "base",
        )

        async def _fake_create_wt(*_a, **_kw):
            (fake_wt / "x.txt").write_text("y")
            return {"success": True}

        monkeypatch.setattr(
            local_mod, "_create_worktree_via_git", _fake_create_wt
        )

        storage = _FakeStorage(capabilities=["stream"])
        provider = LocalWorktreeProvider(storage=storage)
        principal = _make_principal()

        # Repo name padded to push key length > 256
        long_repo = "r" * 240
        with pytest.raises(WorktreeError) as exc_info:
            await provider.create_worktree_handle(
                repo=long_repo,
                branch="b",
                base_ref="main",
                principal=principal,
            )
        assert exc_info.value.error_code == ErrorCode.WORKTREE_BUNDLE_STORAGE_KEY_TOO_LONG

    async def test_create_worktree_handle_enforces_size_cap_mhv221(
        self, tmp_path, monkeypatch
    ):
        from contextlib import contextmanager

        from mahavishnu.core.errors import ErrorCode, WorktreeError
        from mahavishnu.core.worktree_providers import local as local_mod
        from mahavishnu.core.worktree_providers import storage_io

        fake_wt = tmp_path / "wt"
        fake_wt.mkdir()
        monkeypatch.setattr(
            "mahavishnu.core.paths.get_worktree_path",
            lambda *parts: fake_wt,
        )
        monkeypatch.setattr(
            "mahavishnu.core.paths.get_worktree_base_path",
            lambda: tmp_path / "base",
        )

        async def _fake_create_wt(*_a, **_kw):
            (fake_wt / "x.txt").write_text("y")
            return {"success": True}

        monkeypatch.setattr(
            local_mod, "_create_worktree_via_git", _fake_create_wt
        )

        # Force the size guard to trip by making the stub report
        # MAX_BUNDLE_BYTES_STOPGAP + 1
        oversized = storage_io.MAX_BUNDLE_BYTES_STOPGAP + 1

        @contextmanager
        def _fake_serialize(_source, *, compression_level=3):
            tmp = tmp_path / "fake.tar.zst"
            tmp.write_bytes(b"x")
            yield tmp, oversized, "0" * 64

        # Patch serialize_worktree_tar at the storage_io module —
        # create_worktree_handle imports it via
        # ``from .storage_io import ... serialize_worktree_tar`` inside
        # the function body, so the original namespace is the right
        # target.
        monkeypatch.setattr(
            storage_io, "serialize_worktree_tar", _fake_serialize
        )

        storage = _FakeStorage(capabilities=["stream"])
        provider = LocalWorktreeProvider(storage=storage)
        principal = _make_principal()

        with pytest.raises(WorktreeError) as exc_info:
            await provider.create_worktree_handle(
                repo="r", branch="b", base_ref="main", principal=principal
            )
        assert (
            exc_info.value.error_code == ErrorCode.WORKTREE_BUNDLE_STOPGAP_TOO_LARGE
        )


# ---------------------------------------------------------------------------
# fetch — streaming tests
# ---------------------------------------------------------------------------


class TestFetchStreaming:
    """``fetch`` must stream via storage.load_stream with bounded handoff (Phase 3)."""

    async def test_fetch_streams_via_load_stream(self, tmp_path, monkeypatch):
        from mahavishnu.core.worktree_providers import local as local_mod
        from mahavishnu.core.worktree_providers import storage_io

        # Make a real tar.zst in tmp_path so the deserialize step is real
        wt = _make_local_worktree(tmp_path / "src")
        with storage_io.serialize_worktree_tar(wt) as (temp_path, _size, sha):
            payload = temp_path.read_bytes()

        # Bypass the on-disk materialization — return our prepared payload
        storage = _FakeStorage(
            capabilities=["stream"], stream_payload=payload
        )

        # Override the worktree base to land inside tmp_path
        target_base = tmp_path / "materialized"
        monkeypatch.setattr(
            "mahavishnu.core.paths.get_worktree_base_path",
            lambda: target_base,
        )

        # Patch _create_worktree_via_git to a no-op (not used by fetch)
        async def _noop(*_a, **_kw):
            return {"success": True}

        monkeypatch.setattr(local_mod, "_create_worktree_via_git", _noop)

        # Provide a cache so the cache-hit path can be exercised
        cache = _FakeCache()
        provider = LocalWorktreeProvider(storage=storage, cache=cache)
        principal = _make_principal()

        handle = _make_handle(
            handle_id="h-stream-1",
            sha=sha,
            size=len(payload),
            principal=principal,
        )
        ref = await provider.fetch(handle)

        # load_stream was called with the right key
        assert len(storage.load_stream_calls) == 1
        key = storage.load_stream_calls[0]
        assert key.startswith("worktrees/mahavishnu/feature-x/")
        assert key.endswith(".tar.zst")
        # target was materialized with file contents
        assert Path(ref.path).exists()
        assert (Path(ref.path) / "README.md").read_text() == "hello\n"
        # Cache was set after success
        assert cache.set_calls == 1

    async def test_fetch_emits_deserialize_metric(self, tmp_path, monkeypatch):
        from mahavishnu.core.worktree_providers import local as local_mod
        from mahavishnu.core.worktree_providers import storage_io
        from mahavishnu.observability import metrics as metrics_mod

        wt = _make_local_worktree(tmp_path / "src")
        with storage_io.serialize_worktree_tar(wt) as (temp_path, _size, sha):
            payload = temp_path.read_bytes()

        storage = _FakeStorage(
            capabilities=["stream"], stream_payload=payload
        )
        monkeypatch.setattr(
            "mahavishnu.core.paths.get_worktree_base_path",
            lambda: tmp_path / "materialized",
        )
        captured: list[tuple] = []

        from mahavishnu.observability.metrics import StreamingOp

        def _capture(op, backend, duration_ms, bytes_processed, *, success):
            captured.append((op, backend, duration_ms, bytes_processed, success))

        # Patch at the source module — fetch imports record_streaming_op
        # from mahavishnu.observability.metrics inside the function.
        monkeypatch.setattr(metrics_mod, "record_streaming_op", _capture)

        async def _noop(*_a, **_kw):
            return {"success": True}

        monkeypatch.setattr(local_mod, "_create_worktree_via_git", _noop)

        provider = LocalWorktreeProvider(storage=storage)
        handle = _make_handle(sha=sha, size=len(payload))
        await provider.fetch(handle)

        assert len(captured) == 1
        op, backend, _duration_ms, bytes_processed, success = captured[0]
        assert op == StreamingOp.DESERIALIZE
        assert backend == "local"
        assert bytes_processed == len(payload)
        assert success is True

    async def test_fetch_raises_on_legacy_gzip_magic_mhv213(
        self, tmp_path, monkeypatch
    ):
        from mahavishnu.core.errors import ErrorCode, WorktreeError
        from mahavishnu.core.worktree_providers import local as local_mod

        # Gzip magic header: 1f 8b, then a small payload. The 2-byte
        # sniff must catch this BEFORE the stream is handed to
        # deserialize_worktree_tar.
        gzip_magic = b"\x1f\x8b\x08\x00rest-of-gzip"
        storage = _FakeStorage(
            capabilities=["stream"], stream_payload=gzip_magic
        )
        monkeypatch.setattr(
            "mahavishnu.core.paths.get_worktree_base_path",
            lambda: tmp_path / "materialized",
        )

        async def _noop(*_a, **_kw):
            return {"success": True}

        monkeypatch.setattr(local_mod, "_create_worktree_via_git", _noop)

        provider = LocalWorktreeProvider(storage=storage)
        handle = _make_handle()
        with pytest.raises(WorktreeError) as exc_info:
            await provider.fetch(handle)
        assert exc_info.value.error_code == ErrorCode.WORKTREE_BUNDLE_LEGACY_PHASE2

    async def test_fetch_raises_on_codec_unavailable_mhv223(
        self, tmp_path, monkeypatch
    ):
        from mahavishnu.core.errors import ErrorCode, WorktreeError
        from mahavishnu.core.worktree_providers import local as local_mod

        # Force the zstandard import in fetch() to fail
        import builtins

        real_import = builtins.__import__

        def _fake_import(name, *args, **kwargs):
            if name == "zstandard" or name.startswith("zstandard."):
                raise ImportError("simulated missing zstandard")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _fake_import)

        storage = _FakeStorage(
            capabilities=["stream"], stream_payload=b"\x00" * 64
        )
        monkeypatch.setattr(
            "mahavishnu.core.paths.get_worktree_base_path",
            lambda: tmp_path / "materialized",
        )

        async def _noop(*_a, **_kw):
            return {"success": True}

        monkeypatch.setattr(local_mod, "_create_worktree_via_git", _noop)

        provider = LocalWorktreeProvider(storage=storage)
        handle = _make_handle()
        with pytest.raises(WorktreeError) as exc_info:
            await provider.fetch(handle)
        assert exc_info.value.error_code == ErrorCode.WORKTREE_BUNDLE_CODEC_UNAVAILABLE

    async def test_fetch_raises_not_found_mhv222(
        self, tmp_path, monkeypatch
    ):
        from mahavishnu.core.errors import ErrorCode, WorktreeError
        from mahavishnu.core.worktree_providers import local as local_mod

        # Storage adapter that raises when load_stream is called —
        # mirrors the LifecycleError("local-storage-key-not-found")
        # path on the real adapter.
        storage = _FakeStorage(
            capabilities=["stream"],
            raise_on_read=FileNotFoundError("no such key"),
        )
        monkeypatch.setattr(
            "mahavishnu.core.paths.get_worktree_base_path",
            lambda: tmp_path / "materialized",
        )

        async def _noop(*_a, **_kw):
            return {"success": True}

        monkeypatch.setattr(local_mod, "_create_worktree_via_git", _noop)

        provider = LocalWorktreeProvider(storage=storage)
        handle = _make_handle()
        with pytest.raises(WorktreeError) as exc_info:
            await provider.fetch(handle)
        assert exc_info.value.error_code == ErrorCode.WORKTREE_BUNDLE_NOT_FOUND


# ---------------------------------------------------------------------------
# HealthReport — streaming-capability probe
# ---------------------------------------------------------------------------


class TestHealthStreamingProbe:
    """``health()`` must probe streaming capability and warn (B-DI-03)."""

    async def test_health_reports_streaming_capability_present(self, tmp_path, monkeypatch):
        storage = _FakeStorage(capabilities=["stream"])
        provider = LocalWorktreeProvider(storage=storage)
        monkeypatch.setattr(
            "shutil.which", lambda _name: "/usr/bin/git"
        )

        report = await provider.health()
        assert isinstance(report, HealthReport)
        assert bool(report) is True
        # No warning when streaming capability is present
        assert all(
            w["kind"] != "streaming_capability_missing" for w in report.warnings
        )

    async def test_health_reports_streaming_capability_missing(
        self, tmp_path, monkeypatch
    ):
        # Adapter advertises no stream capability → warning expected
        storage = _FakeStorage(capabilities=["blob", "delete"])
        provider = LocalWorktreeProvider(storage=storage)
        monkeypatch.setattr(
            "shutil.which", lambda _name: "/usr/bin/git"
        )

        report = await provider.health()
        kinds = [w["kind"] for w in report.warnings]
        assert "streaming_capability_missing" in kinds
        # Bool of the report is False when warnings are present
        assert bool(report) is False

    async def test_health_warns_when_no_storage(self, monkeypatch):
        # No storage at all → warning is added
        provider = LocalWorktreeProvider()
        monkeypatch.setattr(
            "shutil.which", lambda _name: "/usr/bin/git"
        )

        report = await provider.health()
        assert isinstance(report, HealthReport)
        assert any(
            w["kind"] == "streaming_capability_missing" for w in report.warnings
        )


# ---------------------------------------------------------------------------
# Module-level constant
# ---------------------------------------------------------------------------


class TestMaxConcurrentWorktreeStreams:
    def test_constant_is_eight(self):
        assert MAX_CONCURRENT_WORKTREE_STREAMS == 8
