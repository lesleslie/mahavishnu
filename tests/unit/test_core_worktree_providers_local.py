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
from unittest.mock import AsyncMock, patch

import pytest

from mahavishnu.auth import Principal
from mahavishnu.core.worktree_providers.base import WorktreeProvider
from mahavishnu.core.worktree_providers.errors import (
    WorktreeCreationError,
    WorktreeOperationError,
)
from mahavishnu.core.worktree_providers.local import (
    MAX_CONCURRENT_WORKTREE_STREAMS,
    DirectGitWorktreeProvider,
    HealthReport,
    LocalWorktreeProvider,
    _parse_worktree_porcelain,
    supports_streaming,
)
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

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
        # Instance method (matches WorktreeProvider abstract signature)
        assert (
            DirectGitWorktreeProvider().provider_name() == "DirectGitWorktreeProvider"
        )

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
            await p.create_worktree(
                Path("/r"), "newbranch", Path("/wt"), create_branch=True
            )

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
            await p.create_worktree(
                Path("/r"), "main", Path("/wt"), create_branch=False
            )

        cmd = mock_exec.call_args[0]
        assert "-B" in cmd

    async def test_success_returns_metadata(self):
        p = DirectGitWorktreeProvider()
        process = _fake_process()
        with patch(
            "asyncio.create_subprocess_exec",
            AsyncMock(return_value=process),
        ):
            result = await p.create_worktree(
                Path("/r"), "br", Path("/wt"), create_branch=True
            )

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
        """Parse the format git ACTUALLY emits.

        ``git worktree list --porcelain`` emits one BLOCK per worktree,
        not one line per worktree::

            worktree /repo/main
            HEAD abc123
            branch refs/heads/main

        The fixture this test used to carry was a four-field line
        (``/repo/main main abc123 ok``) -- a format git does not
        produce. The parser it matched never saw a real line, and the
        provider reported zero worktrees for every repository. The
        fixture is the format, not the implementation's assumption.
        """
        p = DirectGitWorktreeProvider()
        output = (
            b"worktree /repo/main\n"
            b"HEAD abc123\n"
            b"branch refs/heads/main\n"
            b"\n"
            b"worktree /repo/feat\n"
            b"HEAD def456\n"
            b"branch refs/heads/feature\n"
        )
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
        assert result["worktrees"][1]["branch"] == "feature"

    async def test_reports_a_locked_worktree_as_locked(self):
        """A ``locked`` line is the fleet's "do not touch this" marker."""
        p = DirectGitWorktreeProvider()
        output = (
            b"worktree /repo/live\n"
            b"HEAD abc123\n"
            b"branch refs/heads/live\n"
            b"locked initializing\n"
        )
        process = _fake_process(stdout=output)
        with patch(
            "asyncio.create_subprocess_exec",
            AsyncMock(return_value=process),
        ):
            result = await p.list_worktrees(Path("/repo"))

        assert len(result["worktrees"]) == 1
        assert result["worktrees"][0]["status"] == "locked"

    async def test_reports_a_detached_worktree(self):
        """A detached worktree reports NO branch -- not a fake one.

        The coordinator's ``prune_worktrees`` asks
        ``git branch --list <branch>`` whether the branch still
        exists. A name that resolves to nothing reads as "the branch
        was deleted", which force-removes the worktree and discards
        whatever uncommitted work it holds. A detached worktree has no
        branch to have been deleted, so it must report ``None`` --
        the convention ``worktree_scan`` already uses.
        """
        p = DirectGitWorktreeProvider()
        output = b"worktree /repo/det\nHEAD abc123\ndetached\n"
        process = _fake_process(stdout=output)
        with patch(
            "asyncio.create_subprocess_exec",
            AsyncMock(return_value=process),
        ):
            result = await p.list_worktrees(Path("/repo"))

        assert result["worktrees"][0]["branch"] is None

    async def test_skips_blank_lines(self):
        p = DirectGitWorktreeProvider()
        # blank line should be skipped
        output = (
            b"worktree /r/a\nHEAD commit1\nbranch refs/heads/branch1\n"
            b"\n"
            b"worktree /r/b\nHEAD commit2\nbranch refs/heads/branch2\n"
        )
        process = _fake_process(stdout=output)
        with patch(
            "asyncio.create_subprocess_exec",
            AsyncMock(return_value=process),
        ):
            result = await p.list_worktrees(Path("/r"))
        assert len(result["worktrees"]) == 2

    async def test_ignores_fields_before_any_worktree_line(self):
        p = DirectGitWorktreeProvider()
        # A field with no worktree to attribute it to carries nothing.
        output = b"HEAD stray\n\nworktree /r/full\nHEAD commit\nbranch refs/heads/b\n"
        process = _fake_process(stdout=output)
        with patch(
            "asyncio.create_subprocess_exec",
            AsyncMock(return_value=process),
        ):
            result = await p.list_worktrees(Path("/r"))
        assert len(result["worktrees"]) == 1
        assert result["worktrees"][0]["path"] == "/r/full"

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
    import zstandard
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


class _FakeMCPClient:
    """Stand-in for the MCP thin client. Just records execute() calls."""

    def __init__(self) -> None:
        self.executes: list[tuple[str, dict | None]] = []

    async def execute(self, sql: str, params: dict | None = None) -> None:
        # ``params`` is optional because schema-setup calls pass only
        # the SQL string (no bound parameters) per mcp_registry.
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
    """Build a WorktreeHandle for fetch tests without MCP round-trip."""
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
        # the same temp dir so the MCP path-validation allowlist
        # accepts the storage path. (MCP rejects paths outside the
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

        monkeypatch.setattr(local_mod, "_create_worktree_via_git", _fake_create_wt)

        storage = _FakeStorage(capabilities=["stream"])
        provider = LocalWorktreeProvider(storage=storage, cache=_FakeCache())
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
        # MCP registration was removed when MCP itself was retired
        # from the Bodai core components; no INSERT assertions remain.

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

        monkeypatch.setattr(local_mod, "_create_worktree_via_git", _fake_create_wt)

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

        monkeypatch.setattr(local_mod, "_create_worktree_via_git", _fake_create_wt)

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
        assert (
            exc_info.value.error_code == ErrorCode.WORKTREE_BUNDLE_STORAGE_KEY_TOO_LONG
        )

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

        monkeypatch.setattr(local_mod, "_create_worktree_via_git", _fake_create_wt)

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
        monkeypatch.setattr(storage_io, "serialize_worktree_tar", _fake_serialize)

        storage = _FakeStorage(capabilities=["stream"])
        provider = LocalWorktreeProvider(storage=storage)
        principal = _make_principal()

        with pytest.raises(WorktreeError) as exc_info:
            await provider.create_worktree_handle(
                repo="r", branch="b", base_ref="main", principal=principal
            )
        assert exc_info.value.error_code == ErrorCode.WORKTREE_BUNDLE_STOPGAP_TOO_LARGE


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
        storage = _FakeStorage(capabilities=["stream"], stream_payload=payload)

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

        storage = _FakeStorage(capabilities=["stream"], stream_payload=payload)
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
        storage = _FakeStorage(capabilities=["stream"], stream_payload=gzip_magic)
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
        # Force the zstandard import in fetch() to fail
        import builtins

        from mahavishnu.core.errors import ErrorCode, WorktreeError
        from mahavishnu.core.worktree_providers import local as local_mod

        real_import = builtins.__import__

        def _fake_import(name, *args, **kwargs):
            if name == "zstandard" or name.startswith("zstandard."):
                raise ImportError("simulated missing zstandard")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _fake_import)

        storage = _FakeStorage(capabilities=["stream"], stream_payload=b"\x00" * 64)
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

    async def test_fetch_raises_not_found_mhv222(self, tmp_path, monkeypatch):
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

    async def test_health_reports_streaming_capability_present(
        self, tmp_path, monkeypatch
    ):
        storage = _FakeStorage(capabilities=["stream"])
        provider = LocalWorktreeProvider(storage=storage)
        monkeypatch.setattr("shutil.which", lambda _name: "/usr/bin/git")

        report = await provider.health()
        assert isinstance(report, HealthReport)
        assert bool(report) is True
        # No warning when streaming capability is present
        assert all(w["kind"] != "streaming_capability_missing" for w in report.warnings)

    async def test_health_reports_streaming_capability_missing(
        self, tmp_path, monkeypatch
    ):
        # Adapter advertises no stream capability → warning expected
        storage = _FakeStorage(capabilities=["blob", "delete"])
        provider = LocalWorktreeProvider(storage=storage)
        monkeypatch.setattr("shutil.which", lambda _name: "/usr/bin/git")

        report = await provider.health()
        kinds = [w["kind"] for w in report.warnings]
        assert "streaming_capability_missing" in kinds
        # Bool of the report is False when warnings are present
        assert bool(report) is False

    async def test_health_warns_when_no_storage(self, monkeypatch):
        # No storage at all → warning is added
        provider = LocalWorktreeProvider()
        monkeypatch.setattr("shutil.which", lambda _name: "/usr/bin/git")

        report = await provider.health()
        assert isinstance(report, HealthReport)
        assert any(w["kind"] == "streaming_capability_missing" for w in report.warnings)


# ---------------------------------------------------------------------------
# Module-level constant
# ---------------------------------------------------------------------------


class TestMaxConcurrentWorktreeStreams:
    def test_constant_is_eight(self):
        assert MAX_CONCURRENT_WORKTREE_STREAMS == 8


# ---------------------------------------------------------------------------
# The porcelain parser against REAL git output
# ---------------------------------------------------------------------------


class TestPorcelainParserAgainstRealGit:
    """The parser, exercised against git's own output.

    Every other test in this file feeds the parser a fixture. A
    fixture can only prove the parser agrees with the fixture -- and
    the fixture that shipped here was a format git does not produce,
    which is how a parser that matched nothing stayed green.

    This class runs the REAL command against the REAL repository, so
    a change to git's output format shows up as a failure here
    instead of as a silently empty listing in production.
    """

    def _repo_root(self) -> Path:
        return Path(__file__).resolve().parents[2]

    @pytest.mark.req(["REQ-PRUNE-004"])
    def test_the_real_command_output_is_parsed(self):
        """``git worktree list --porcelain`` yields real worktrees.

        Before the parser was fixed this was ZERO for every
        repository: the old predicate kept a line only when it had
        four or more space-separated fields, and every line of the
        real output has exactly two.
        """
        import subprocess

        root = self._repo_root()
        result = subprocess.run(
            ["git", "-C", str(root), "worktree", "list", "--porcelain"],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        parsed = _parse_worktree_porcelain(result.stdout)

        assert parsed, "the parser returned nothing for real git output"
        paths = [entry["path"] for entry in parsed]
        assert str(root) in paths
        # The entry for THIS checkout must agree with git about which
        # branch it is on -- the worktree list is asked of the worktree
        # itself, so the entry carries the worktree's branch, not
        # ``main``.
        #
        # ``git branch --show-current`` prints NOTHING for a detached
        # checkout, and the parser reports no branch for one, so the
        # two agree on both cases. (``rev-parse --abbrev-ref HEAD``
        # would print the literal "HEAD" instead.)
        expected = subprocess.run(
            ["git", "-C", str(root), "branch", "--show-current"],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        ).stdout.strip()
        here = next(e for e in parsed if e["path"] == str(root))
        assert here["branch"] == (expected or None)
        assert here["commit"]
        assert here["status"] in {"ok", "locked"}

    def test_every_parsed_entry_has_the_same_shape(self):
        """Every entry has the same shape, whatever the repository holds.

        The assertions are about the PARSER, not about this machine: how
        many worktrees a checkout has, and whether any of them is
        detached, are properties of the environment. A test that
        required more than one worktree would fail on a fresh clone.
        """
        import subprocess

        result = subprocess.run(
            ["git", "-C", str(self._repo_root()), "worktree", "list", "--porcelain"],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        parsed = _parse_worktree_porcelain(result.stdout)

        assert parsed
        for entry in parsed:
            assert set(entry) == {"path", "branch", "commit", "status"}
            assert entry["path"].startswith("/")
            # A DETACHED worktree reports no branch -- that is the
            # point of the None, and it is why the coordinator must
            # read the detached state from git rather than trusting a
            # branch name.
            assert entry["branch"] is None or entry["branch"]
            assert entry["commit"]
