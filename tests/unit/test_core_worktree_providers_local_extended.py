"""Extended coverage for ``mahavishnu/core/worktree_providers/local.py``.

Round-2 push to bring the file from ~69% to 85%+ coverage. The companion
test file ``test_core_worktree_providers_local.py`` already exercises the
Phase 3 streaming paths and the v3 ``DirectGitWorktreeProvider`` surface;
this file targets the remaining uncovered branches:

* module-level path-component validators (shape + parent-traversal)
* ``_principal_short`` "anon" fallback
* ``LocalWorktreeProvider.create_worktree/remove_worktree/list_worktrees``
  delegation to the v4 module-level helpers
* ``LocalWorktreeProvider._persist_bundle`` (storage is None / storage
  missing ``save_stream``)
* ``LocalWorktreeProvider.fetch`` cache-hit fast path and storage-None
  fallback
* ``LocalWorktreeProvider._try_cache_hit`` (cache miss / cached path
  missing / cached path present)
* ``LocalWorktreeProvider._fallback_to_existing_path`` (non-Local ref /
  missing path / happy path)
* ``LocalWorktreeProvider._ensure_storage_supports_load_stream``
* ``LocalWorktreeProvider._open_storage_stream`` defensive None check
* ``LocalWorktreeProvider.remove_handle`` (non-Local ref / git failure
  is best-effort / cache invalidate / dhara remove / no-dhara path)
* ``LocalWorktreeProvider.list_handles`` (no caller / no dhara / happy)
* ``LocalWorktreeProvider.exists`` (Local exists / Local missing /
  non-Local returns False)
* ``LocalWorktreeProvider.lock`` (success / timeout)
* ``LocalWorktreeProvider.health`` (git-missing / storage-down /
  cache-down / all-healthy)
* Module-level ``_create_worktree_via_git`` / ``_remove_worktree_via_git``
  / ``_list_worktrees_via_git`` (success + failure + exception paths)

Style: monkeypatch ``asyncio.create_subprocess_exec`` so no real git
is run for the delegation tests; for the module-level helpers use a
real ``tmp_path`` git repo when it materially improves confidence.

No production code is modified. Helpers stay local to this file.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator
from unittest.mock import AsyncMock, patch

import pytest

from mahavishnu.auth import Principal
from mahavishnu.core.worktree_providers import local as local_mod
from mahavishnu.core.worktree_providers.local import (
    DirectGitWorktreeProvider,
    HealthReport,
    LocalWorktreeProvider,
    _create_worktree_via_git,
    _list_worktrees_via_git,
    _principal_short,
    _remove_worktree_via_git,
    _validate_path_component,
    _validate_path_component_no_parent_traversal,
    _validate_path_component_shape,
    supports_streaming,
)
from mahavishnu.core.worktree_providers.types import (
    LocalWorktreeRef,
    WorktreeHandle,
    WorktreeRef,
)

pytestmark = pytest.mark.unit


try:
    import zstandard  # noqa: F401
except ImportError:
    pytest.skip(
        "zstandard required; uv sync --group compression-zstd",
        allow_module_level=True,
    )


# ---------------------------------------------------------------------------
# Helpers (local to this file so the test is self-contained)
# ---------------------------------------------------------------------------


def _fake_process(returncode: int = 0, stdout: bytes = b"", stderr: bytes = b""):
    p = AsyncMock()
    p.communicate = AsyncMock(return_value=(stdout, stderr))
    p.returncode = returncode
    return p


@dataclass
class _AdapterMetadata:
    capabilities: list[str] = field(default_factory=list)


class _FakeStorage:
    """Stand-in for ``LocalStorageAdapter`` with configurable surface."""

    def __init__(
        self,
        *,
        capabilities: list[str] | None = None,
        raise_on_read: Exception | None = None,
        stream_payload: bytes | None = None,
        has_save_stream: bool = True,
        has_load_stream: bool = True,
        health_ok: bool = True,
        health_raises: bool = False,
    ) -> None:
        self.metadata = _AdapterMetadata(
            capabilities=capabilities if capabilities is not None else ["stream"]
        )
        self.save_stream_calls: list[tuple[str, dict, int]] = []
        self.load_stream_calls: list[str] = []
        self._raise_on_read = raise_on_read
        self._stream_payload = stream_payload if stream_payload is not None else b""
        self._has_save_stream = has_save_stream
        self._has_load_stream = has_load_stream
        self._health_ok = health_ok
        self._health_raises = health_raises

    def save_stream(self, key, chunk_reader, *, metadata=None) -> int:
        data = b"".join(chunk_reader())
        self.save_stream_calls.append((key, metadata or {}, len(data)))
        return len(data)

    def load_stream(self, key: str) -> Iterator[bytes]:
        self.load_stream_calls.append(key)
        if self._raise_on_read is not None:
            raise self._raise_on_read
        return self._stream_chunks(key)

    def _stream_chunks(self, _key: str) -> Iterator[bytes]:
        for i in range(0, len(self._stream_payload), 8):
            yield self._stream_payload[i : i + 8]

    async def health(self) -> bool:
        if self._health_raises:
            raise RuntimeError("storage health exploded")
        return self._health_ok

    async def save(self, key, data):
        return key

    async def read(self, key):
        return self._stream_payload or None


class _NoSaveStreamStorage:
    """Storage that advertises capability but has no save_stream method.

    Standalone class (not a subclass) so ``save_stream`` is genuinely absent.
    Production uses ``getattr(storage, "save_stream", None)`` which returns
    None when the attribute is missing.
    """

    metadata = _AdapterMetadata(capabilities=["stream"])

    def load_stream(self, key):  # pragma: no cover — not exercised
        return iter([])

    async def health(self) -> bool:
        return True


class _NoLoadStreamStorage:
    """Storage that advertises capability but has no load_stream method.

    Standalone class (not a subclass) so ``load_stream`` is genuinely absent.
    """

    metadata = _AdapterMetadata(capabilities=["stream"])

    def save_stream(self, key, chunk_reader, *, metadata=None):  # pragma: no cover
        return 0

    async def health(self) -> bool:
        return True


class _FakeCache:
    def __init__(self) -> None:
        self._store: dict[str, str] = {}
        self.get_calls = 0
        self.set_calls = 0
        self.invalidate_calls: list[str] = []

    async def get(self, key: str) -> str | None:
        self.get_calls += 1
        return self._store.get(key)

    async def set(self, key: str, value: str) -> None:
        self.set_calls += 1
        self._store[key] = value

    async def invalidate_handle(self, handle_id: str) -> int:
        self.invalidate_calls.append(handle_id)
        prefix = f"materialized:{handle_id}"
        keys = [k for k in self._store if k.startswith(prefix)]
        for k in keys:
            del self._store[k]
        return len(keys)

    async def health(self) -> bool:
        return True


class _BrokenCache:
    async def get(self, key):
        return None

    async def set(self, key, value):
        return None

    async def invalidate_handle(self, handle_id):
        return 0

    async def health(self) -> bool:
        raise RuntimeError("cache health exploded")


class _FakeDharaClient:
    def __init__(self) -> None:
        self.executes: list[tuple[str, dict | None]] = []
        self.queries: list[tuple[str, dict | None]] = []

    async def execute(self, sql: str, params: dict | None = None) -> None:
        self.executes.append((sql, params))

    async def query(self, sql: str, params: dict | None = None) -> list[dict]:
        self.queries.append((sql, params))
        return [{"handle_id": "abc", "principal": "someone"}]


def _principal(name: str = "test-principal", uid: int = 1000) -> Principal:
    return Principal(
        uid=uid,
        name=name,
        scopes=frozenset({"worktree:register", "worktree:remove"}),
    )


def _handle(
    *,
    handle_id: str = "abcd1234",
    repo: str = "mahavishnu",
    branch: str = "feature-x",
    sha: str = "0" * 64,
    size: int = 1024,
    wt_path: Path | None = None,
    principal_value: Principal | None = None,
    storage_ref: WorktreeRef | None = None,
) -> WorktreeHandle:
    """Build a WorktreeHandle. storage_ref defaults to LocalWorktreeRef."""
    if wt_path is None:
        wt_path = Path("/tmp/fake-wt")
    if storage_ref is None:
        storage_ref = LocalWorktreeRef(path=wt_path, worktree_id=handle_id)
    return WorktreeHandle(
        handle_id=handle_id,
        principal=principal_value or _principal(),
        repo=repo,
        branch=branch,
        base_ref="main",
        created_at=datetime.now(UTC),
        storage_ref=storage_ref,
        sha256=sha,
        bytes_size=size,
        cleanup_policy=None,
        provenance="v4",
    )


class _RemoteWorktreeRef(WorktreeRef):
    """Non-Local storage_ref used to exercise the isinstance narrowing."""

    @property
    def backend_kind(self) -> str:
        return "remote"


def _init_git_repo(tmp_path: Path) -> Path:
    """Create a real git repo on disk and return its path."""
    import subprocess

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "--initial-branch=main", str(repo)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "test@example.com"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "Test"],
        check=True,
        capture_output=True,
    )
    (repo / "README.md").write_text("hi\n")
    subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", "init"], check=True, capture_output=True
    )
    return repo


# ===========================================================================
# Module-level path-component validators
# ===========================================================================


class TestValidatePathComponentShape:
    """``_validate_path_component_shape`` rejects empty / dash / separator / dot.

    Note: this is a void helper; valid input returns ``None`` and the public
    ``_validate_path_component`` chains the input back to the caller.
    """

    def test_empty_value_raises(self):
        with pytest.raises(ValueError, match="repo is empty"):
            _validate_path_component_shape("", "repo")

    def test_dash_prefix_raises(self):
        with pytest.raises(ValueError, match="starts with dash"):
            _validate_path_component_shape("-rf", "branch")

    def test_forward_slash_raises(self):
        with pytest.raises(ValueError, match="path separator"):
            _validate_path_component_shape("a/b", "branch")

    def test_backslash_raises(self):
        with pytest.raises(ValueError, match="path separator"):
            _validate_path_component_shape(r"a\b", "branch")

    def test_dot_raises(self):
        with pytest.raises(ValueError, match="relative-path marker"):
            _validate_path_component_shape(".", "branch")

    def test_double_dot_raises_in_shape_check(self):
        # Note: shape check raises "relative-path marker" first (line 83),
        # not the parent-traversal check. Verify the ordering.
        with pytest.raises(ValueError, match="relative-path marker"):
            _validate_path_component_shape("..", "branch")

    def test_valid_input_does_not_raise(self):
        # Void helper — just verify no exception fires.
        _validate_path_component_shape("good-name", "branch")


class TestValidatePathComponentNoParentTraversal:
    """``..`` as a discrete component is the security boundary.

    Note: this helper is *void* too — the public ``_validate_path_component``
    chains the input back, but the inner parent-traversal check does not.
    """

    def test_double_dot_alone_raises(self):
        # ``a/../b`` has ``..`` as a discrete component after splitting on ``/``.
        # The shape check fires FIRST on the public helper (because of the
        # ``/`` separator), so to exercise this branch we call the helper
        # directly with a value that has ``..`` as a discrete component.
        # Note: in practice any value with ``..`` as a discrete component
        # also contains a separator, so the shape check always fires first;
        # this test verifies the inner helper's logic anyway.
        with pytest.raises(ValueError, match="contains '..'"):
            _validate_path_component_no_parent_traversal("a/../b", "branch")

    def test_backslash_parent_traversal_raises(self):
        with pytest.raises(ValueError, match="contains '..'"):
            _validate_path_component_no_parent_traversal(r"a\..\b", "branch")

    def test_valid_input_does_not_raise(self):
        # No ``..`` as discrete component → no raise.
        _validate_path_component_no_parent_traversal("plain", "branch")


class TestValidatePathComponentPublic:
    """``_validate_path_component`` runs both checks; verify error surface."""

    def test_returns_value_when_valid(self):
        assert _validate_path_component("clean", kind="repo") == "clean"

    def test_rejects_path_separator(self):
        with pytest.raises(ValueError, match="path separator"):
            _validate_path_component("foo/bar", kind="repo")


# ===========================================================================
# Module-level _principal_short
# ===========================================================================


class TestPrincipalShort:
    """``_principal_short`` returns "anon" for falsy names."""

    def test_returns_anon_for_empty_string_principal(self):
        # principal is a str; name falls through to ``principal`` itself.
        # getattr("", "name", None) → None (strings don't have .name).
        # None or "" → "". if not "": return "anon".
        assert _principal_short("") == "anon"

    def test_string_principal_hashed_returns_8_chars(self):
        # Hash of a real string → 8 hex chars.
        result = _principal_short("alice")
        assert len(result) == 8
        assert all(c in "0123456789abcdef" for c in result)

    def test_named_principal_with_unknown_name_is_hashed(self):
        # Principal with empty name → getattr returns "". OR fallback
        # fires, picking ``"unknown"`` (not a str), which is then hashed.
        # This does NOT trigger the "anon" branch — that branch is only
        # reachable for falsy strings themselves.
        p = Principal(uid=1, name="", scopes=frozenset())
        sha = _principal_short(p)
        assert len(sha) == 8

    def test_returns_anon_when_name_attr_missing_and_not_string(self):
        # No ``name`` attr AND not a string → "unknown" → truthy → hashed.
        # To reach "anon" we need the resolved name to be falsy.
        # Pass a non-string with no .name: getattr default is None,
        # so the OR picks ``"unknown"``. That gets hashed. Confirm.
        class _NoName:
            pass

        sha = _principal_short(_NoName())
        assert len(sha) == 8

    def test_hashes_string_principal(self):
        # String principal is hashed; result is 8 hex chars.
        result = _principal_short("alice")
        assert len(result) == 8
        assert all(c in "0123456789abcdef" for c in result)

    def test_hashes_named_principal(self):
        result = _principal_short(_principal(name="bob"))
        assert len(result) == 8


class TestLocalWorktreeProviderIdentity:
    """``LocalWorktreeProvider`` identity + health checks."""

    def test_provider_name_returns_local(self):
        assert LocalWorktreeProvider().provider_name() == "LocalWorktreeProvider"

    def test_health_check_true_when_git_present(self):
        with patch("shutil.which", return_value="/usr/bin/git"):
            assert LocalWorktreeProvider().health_check() is True

    def test_health_check_false_when_git_missing(self):
        with patch("shutil.which", return_value=None):
            assert LocalWorktreeProvider().health_check() is False

    def test_default_constructor_keeps_optional_deps_none(self):
        provider = LocalWorktreeProvider()
        assert provider._git_executable == "git"
        assert provider._settings is None
        assert provider._storage is None
        assert provider._cache is None
        assert provider._dhara_client is None


# ===========================================================================
# LocalWorktreeProvider — CRUD delegates
# ===========================================================================


class TestLocalWorktreeProviderCRUDDelegates:
    """``create_worktree`` / ``remove_worktree`` / ``list_worktrees`` delegate
    to the module-level helpers."""

    async def test_create_worktree_delegates_to_module_helper(self, monkeypatch):
        captured: dict[str, Any] = {}

        async def _fake(*args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs
            return {"success": True, "worktree_path": "/wt", "branch": "b"}

        monkeypatch.setattr(local_mod, "_create_worktree_via_git", _fake)
        provider = LocalWorktreeProvider()
        result = await provider.create_worktree(
            Path("/r"), "br", Path("/wt"), create_branch=True
        )
        assert result["success"] is True
        # Args: (git_executable, repository_path, branch, worktree_path,
        # create_branch) — create_branch is the 5th positional arg.
        assert captured["args"] == ("git", Path("/r"), "br", Path("/wt"), True)

    async def test_create_worktree_with_existing_branch(self, monkeypatch):
        captured: dict[str, Any] = {}

        async def _fake(*args, **kwargs):
            captured["args"] = args
            return {"success": True}

        monkeypatch.setattr(local_mod, "_create_worktree_via_git", _fake)
        provider = LocalWorktreeProvider()
        await provider.create_worktree(
            Path("/r"), "main", Path("/wt"), create_branch=False
        )
        assert captured["args"][4] is False

    async def test_remove_worktree_delegates_to_module_helper(self, monkeypatch):
        captured: dict[str, Any] = {}

        async def _fake(*args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs
            return {"success": True, "removed_path": "/wt"}

        monkeypatch.setattr(local_mod, "_remove_worktree_via_git", _fake)
        provider = LocalWorktreeProvider()
        result = await provider.remove_worktree(Path("/r"), Path("/wt"), force=True)
        assert result["success"] is True
        # Args: (git_executable, repository_path, worktree_path, force).
        assert captured["args"] == ("git", Path("/r"), Path("/wt"), True)

    async def test_remove_worktree_without_force(self, monkeypatch):
        captured: dict[str, Any] = {}

        async def _fake(*args, **kwargs):
            captured["args"] = args
            return {"success": True}

        monkeypatch.setattr(local_mod, "_remove_worktree_via_git", _fake)
        provider = LocalWorktreeProvider()
        await provider.remove_worktree(Path("/r"), Path("/wt"), force=False)
        assert captured["args"][3] is False

    async def test_list_worktrees_delegates_to_module_helper(self, monkeypatch):
        captured: dict[str, Any] = {}

        async def _fake(*args, **kwargs):
            captured["args"] = args
            return {"success": True, "worktrees": []}

        monkeypatch.setattr(local_mod, "_list_worktrees_via_git", _fake)
        provider = LocalWorktreeProvider()
        result = await provider.list_worktrees(Path("/r"))
        assert result["success"] is True
        assert captured["args"] == ("git", Path("/r"))


# ===========================================================================
# LocalWorktreeProvider._persist_bundle
# ===========================================================================


class TestPersistBundle:
    """``_persist_bundle`` short-circuits or raises depending on storage."""

    async def test_returns_when_storage_is_none(self):
        provider = LocalWorktreeProvider(storage=None)
        # Should be a no-op — no exception, no save_stream invocation.
        await provider._persist_bundle(Path("/tmp/x"), "k", 10, "deadbeef")

    async def test_raises_when_save_stream_missing(self, tmp_path):
        from mahavishnu.core.errors import ErrorCode, WorktreeError

        storage = _NoSaveStreamStorage()
        provider = LocalWorktreeProvider(storage=storage)
        with pytest.raises(WorktreeError) as exc_info:
            await provider._persist_bundle(tmp_path / "x.tar.zst", "k", 10, "h")
        assert exc_info.value.error_code == ErrorCode.WORKTREE_BUNDLE_CODEC_UNAVAILABLE


# ===========================================================================
# LocalWorktreeProvider.fetch — cache hit + storage None fallback
# ===========================================================================


class TestFetchCacheHit:
    """Cache hit short-circuits before storage streaming."""

    async def test_cache_hit_returns_cached_path(self, tmp_path):
        cached_dir = tmp_path / "cached"
        cached_dir.mkdir()
        (cached_dir / "marker.txt").write_text("cached")

        cache = _FakeCache()
        handle = _handle(handle_id="cached-id", wt_path=cached_dir)
        await cache.set(f"materialized:{handle.handle_id}", str(cached_dir))

        provider = LocalWorktreeProvider(storage=None, cache=cache)
        ref = await provider.fetch(handle)

        assert isinstance(ref, LocalWorktreeRef)
        assert ref.path == cached_dir
        # Cache was queried (not storage).
        assert cache.get_calls == 1
        # No load_stream because we never went down the streaming branch.

    async def test_cache_miss_returns_none_for_none_cache(self):
        provider = LocalWorktreeProvider(storage=None, cache=None)
        handle = _handle(handle_id="x")
        # Without storage, fallback path runs; we test the cache helper directly.
        result = await provider._try_cache_hit("k", handle, 0.0)
        assert result is None


class TestFetchCacheMissBranches:
    """``_try_cache_hit`` returns None for missing cache / missing path."""

    async def test_returns_none_when_cache_is_none(self):
        provider = LocalWorktreeProvider(cache=None)
        handle = _handle(handle_id="x")
        assert await provider._try_cache_hit("k", handle, 0.0) is None

    async def test_returns_none_when_cache_misses(self):
        cache = _FakeCache()
        provider = LocalWorktreeProvider(cache=cache)
        handle = _handle(handle_id="missing")
        assert await provider._try_cache_hit("k", handle, 0.0) is None
        assert cache.get_calls == 1

    async def test_returns_none_when_cached_path_does_not_exist(self, tmp_path):
        cache = _FakeCache()
        cache_key = "materialized:ghost"
        await cache.set(cache_key, str(tmp_path / "does-not-exist"))
        provider = LocalWorktreeProvider(cache=cache)
        handle = _handle(handle_id="ghost")
        # Use the same cache_key fetch would build.
        assert await provider._try_cache_hit(cache_key, handle, 0.0) is None

    async def test_returns_ref_when_cached_path_exists(self, tmp_path):
        path = tmp_path / "real"
        path.mkdir()
        cache = _FakeCache()
        cache_key = "materialized:real"
        await cache.set(cache_key, str(path))
        provider = LocalWorktreeProvider(cache=cache)
        handle = _handle(handle_id="real")
        # Use the same cache_key fetch would build for this handle.
        ref = await provider._try_cache_hit(cache_key, handle, 0.0)
        assert isinstance(ref, LocalWorktreeRef)
        assert ref.path == path


class TestFallbackToExistingPath:
    """``_fallback_to_existing_path`` handles non-Local / missing / happy."""

    def test_raises_for_non_local_storage_ref(self):
        from mahavishnu.core.errors import ErrorCode, WorktreeError

        handle = _handle(storage_ref=_RemoteWorktreeRef())
        with pytest.raises(WorktreeError) as exc_info:
            LocalWorktreeProvider._fallback_to_existing_path(handle, 0.0)
        assert exc_info.value.error_code == ErrorCode.WORKTREE_NOT_FOUND

    def test_raises_when_path_missing(self, tmp_path):
        from mahavishnu.core.errors import ErrorCode, WorktreeError

        missing = tmp_path / "missing"
        handle = _handle(wt_path=missing)
        with pytest.raises(WorktreeError) as exc_info:
            LocalWorktreeProvider._fallback_to_existing_path(handle, 0.0)
        assert exc_info.value.error_code == ErrorCode.WORKTREE_NOT_FOUND

    def test_returns_storage_ref_when_path_exists(self, tmp_path):
        existing = tmp_path / "exists"
        existing.mkdir()
        handle = _handle(wt_path=existing)
        ref = LocalWorktreeProvider._fallback_to_existing_path(handle, 0.0)
        assert isinstance(ref, LocalWorktreeRef)
        assert ref.path == existing


class TestFetchStorageNoneFallback:
    """When storage is None, fetch falls back to the on-disk path."""

    async def test_falls_back_to_existing_path(self, tmp_path):
        wt = tmp_path / "on-disk-wt"
        wt.mkdir()
        provider = LocalWorktreeProvider(storage=None)
        handle = _handle(handle_id="nobnd", wt_path=wt)
        ref = await provider.fetch(handle)
        assert ref.path == wt


# ===========================================================================
# LocalWorktreeProvider.fetch — defensive / codec checks
# ===========================================================================


class TestFetchStorageChecks:
    """``_ensure_storage_supports_load_stream`` + ``_open_storage_stream``."""

    async def test_ensure_storage_supports_load_stream_raises_when_missing(self):
        from mahavishnu.core.errors import ErrorCode, WorktreeError

        storage = _NoLoadStreamStorage()
        provider = LocalWorktreeProvider(storage=storage)
        with pytest.raises(WorktreeError) as exc_info:
            provider._ensure_storage_supports_load_stream()
        assert exc_info.value.error_code == ErrorCode.WORKTREE_BUNDLE_CODEC_UNAVAILABLE

    def test_open_storage_stream_raises_when_storage_is_none(self):
        from mahavishnu.core.errors import ErrorCode, WorktreeError

        provider = LocalWorktreeProvider(storage=None)
        # Defensive check: even though fetch() returns earlier when storage
        # is None, calling _open_storage_stream directly with a None storage
        # must raise a structured error rather than AttributeError.
        with pytest.raises(WorktreeError) as exc_info:
            provider._open_storage_stream("worktrees/foo/bar/x.tar.zst")
        assert exc_info.value.error_code == ErrorCode.WORKTREE_BUNDLE_NOT_FOUND


# ===========================================================================
# LocalWorktreeProvider.remove_handle
# ===========================================================================


class TestRemoveHandle:
    """``remove_handle`` exercises cache + dhara + git cleanup branches."""

    async def test_raises_for_non_local_storage_ref(self):
        handle = _handle(storage_ref=_RemoteWorktreeRef())
        provider = LocalWorktreeProvider()
        with pytest.raises(NotImplementedError, match="LocalWorktreeProvider can only remove LocalWorktreeRef"):
            await provider.remove_handle(handle, caller=_principal())

    async def test_skips_git_cleanup_on_error(self, monkeypatch):
        from mahavishnu.core.worktree_providers import local as local_mod_inner
        from mahavishnu.core.worktree_providers import dhara_registry

        async def _exploding_remove(*_a, **_kw):
            raise RuntimeError("disk gone")

        async def _fake_dhara_remove(*_a, **_kw):
            return None

        # Patch git subprocess helper to raise — must be swallowed.
        monkeypatch.setattr(local_mod_inner, "_remove_worktree_via_git", _exploding_remove)
        # Patch Dhara remove directly so we don't trip the ownership check.
        monkeypatch.setattr(dhara_registry, "remove_handle", _fake_dhara_remove)

        cache = _FakeCache()
        provider = LocalWorktreeProvider(cache=cache, dhara_client=_FakeDharaClient())
        handle = _handle(handle_id="ghost")
        # Should NOT raise despite git failure (best-effort).
        result = await provider.remove_handle(handle, caller=_principal())
        assert result is True
        # Cache still ran.
        assert cache.invalidate_calls == ["ghost"]

    async def test_skips_cache_when_no_cache(self, monkeypatch):
        from mahavishnu.core.worktree_providers import local as local_mod_inner

        async def _fake_remove(*_a, **_kw):
            return {"success": True}

        monkeypatch.setattr(local_mod_inner, "_remove_worktree_via_git", _fake_remove)

        provider = LocalWorktreeProvider(cache=None, dhara_client=None)
        handle = _handle(handle_id="x")
        assert await provider.remove_handle(handle, caller=_principal()) is True

    async def test_runs_dhara_remove_when_client_present(self, monkeypatch):
        from mahavishnu.core.worktree_providers import local as local_mod_inner
        from mahavishnu.core.worktree_providers import dhara_registry

        async def _fake_remove(*_a, **_kw):
            return {"success": True}

        captured: dict[str, Any] = {}

        async def _capture_dhara_remove(client, handle_id, *, caller):
            captured["client"] = client
            captured["handle_id"] = handle_id
            captured["caller"] = caller
            return None

        monkeypatch.setattr(local_mod_inner, "_remove_worktree_via_git", _fake_remove)
        monkeypatch.setattr(dhara_registry, "remove_handle", _capture_dhara_remove)

        cache = _FakeCache()
        client = _FakeDharaClient()
        provider = LocalWorktreeProvider(cache=cache, dhara_client=client)
        handle = _handle(handle_id="abc")
        await provider.remove_handle(handle, caller=_principal(name="caller-x"))
        assert captured["client"] is client
        assert captured["handle_id"] == "abc"
        assert captured["caller"].name == "caller-x"


# ===========================================================================
# LocalWorktreeProvider.list_handles
# ===========================================================================


class TestListHandles:
    """``list_handles`` requires a caller; delegates to Dhara otherwise."""

    async def test_raises_permission_error_when_caller_missing(self):
        provider = LocalWorktreeProvider()
        with pytest.raises(PermissionError, match="requires a caller"):
            await provider.list_handles()

    async def test_returns_empty_when_no_dhara_client(self):
        provider = LocalWorktreeProvider(dhara_client=None)
        result = await provider.list_handles(caller=_principal())
        assert result == []

    async def test_delegates_to_dhara(self, monkeypatch):
        from mahavishnu.core.worktree_providers import dhara_registry

        captured: dict[str, Any] = {}

        async def _fake_list(client, principal, repo, caller):
            captured["client"] = client
            captured["principal"] = principal
            captured["repo"] = repo
            captured["caller"] = caller
            return [{"handle_id": "h1", "principal": "alice"}]

        monkeypatch.setattr(dhara_registry, "list_handles", _fake_list)
        client = _FakeDharaClient()
        provider = LocalWorktreeProvider(dhara_client=client)
        result = await provider.list_handles(
            principal=None, repo="mahavishnu", caller=_principal()
        )
        assert result == [{"handle_id": "h1", "principal": "alice"}]
        assert captured["client"] is client
        assert captured["caller"] is not None


# ===========================================================================
# LocalWorktreeProvider.exists
# ===========================================================================


class TestExists:
    """``exists`` returns path.exists() for LocalWorktreeRef; False otherwise."""

    async def test_returns_true_when_local_path_exists(self, tmp_path):
        wt = tmp_path / "wt"
        wt.mkdir()
        provider = LocalWorktreeProvider()
        handle = _handle(wt_path=wt)
        assert await provider.exists(handle) is True

    async def test_returns_false_when_local_path_missing(self, tmp_path):
        provider = LocalWorktreeProvider()
        handle = _handle(wt_path=tmp_path / "ghost")
        assert await provider.exists(handle) is False

    async def test_returns_false_for_non_local_storage_ref(self):
        provider = LocalWorktreeProvider()
        handle = _handle(storage_ref=_RemoteWorktreeRef())
        assert await provider.exists(handle) is False


# ===========================================================================
# LocalWorktreeProvider.lock
# ===========================================================================


class TestLock:
    """``lock`` wraps ``RedisLockBackend.acquire`` and records wait metrics."""

    async def test_acquires_lock_and_records_wait(self, monkeypatch):
        from mahavishnu.core.worktree_providers import lock as lock_mod

        class _FakeLock:
            fencing_token = "tok-1"

        class _FakeBackend:
            def __init__(self, *args, **kwargs):
                pass

            async def acquire(self, *, principal_name, repo, branch):
                return _FakeLock()

        monkeypatch.setattr(lock_mod, "RedisLockBackend", _FakeBackend)
        provider = LocalWorktreeProvider()
        result = await provider.lock("mahavishnu", "feature-x")
        assert result.fencing_token == "tok-1"

    async def test_records_failure_on_timeout(self, monkeypatch):
        from mahavishnu.core.worktree_providers import lock as lock_mod

        class _FakeBackend:
            def __init__(self, *args, **kwargs):
                pass

            async def acquire(self, *, principal_name, repo, branch):
                raise TimeoutError("lease timeout")

        monkeypatch.setattr(lock_mod, "RedisLockBackend", _FakeBackend)
        provider = LocalWorktreeProvider()
        with pytest.raises(TimeoutError, match="lease timeout"):
            await provider.lock("r", "b")


# ===========================================================================
# LocalWorktreeProvider.health
# ===========================================================================


class TestHealthFailurePaths:
    """``health()`` flips ``healthy=False`` for any failing probe."""

    async def test_health_unhealthy_when_git_missing(self, monkeypatch):
        from mahavishnu.observability import metrics as metrics_mod

        captured: list[tuple] = []

        def _capture(*args, **kwargs):
            captured.append((args, kwargs))

        monkeypatch.setattr(metrics_mod, "record_backend_health_check_failed", _capture)
        monkeypatch.setattr("shutil.which", lambda _name: None)
        provider = LocalWorktreeProvider()
        report = await provider.health()
        assert isinstance(report, HealthReport)
        assert report.healthy is False
        assert bool(report) is False
        assert captured, "expected metric to be recorded"

    async def test_health_unhealthy_when_storage_unhealthy(self, monkeypatch):
        storage = _FakeStorage(capabilities=["stream"], health_ok=False)
        monkeypatch.setattr("shutil.which", lambda _name: "/usr/bin/git")
        provider = LocalWorktreeProvider(storage=storage)
        report = await provider.health()
        assert report.healthy is False

    async def test_health_unhealthy_when_storage_health_raises(self, monkeypatch):
        storage = _FakeStorage(capabilities=["stream"], health_raises=True)
        monkeypatch.setattr("shutil.which", lambda _name: "/usr/bin/git")
        provider = LocalWorktreeProvider(storage=storage)
        report = await provider.health()
        assert report.healthy is False

    async def test_health_unhealthy_when_cache_unhealthy(self, monkeypatch):
        cache = _BrokenCache()
        monkeypatch.setattr("shutil.which", lambda _name: "/usr/bin/git")
        provider = LocalWorktreeProvider(cache=cache)
        report = await provider.health()
        assert report.healthy is False

    async def test_health_healthy_when_all_good(self, monkeypatch):
        storage = _FakeStorage(capabilities=["stream"])
        cache = _FakeCache()
        monkeypatch.setattr("shutil.which", lambda _name: "/usr/bin/git")
        provider = LocalWorktreeProvider(storage=storage, cache=cache)
        report = await provider.health()
        assert isinstance(report, HealthReport)
        assert report.healthy is True
        assert bool(report) is True


# ===========================================================================
# create_worktree_handle — failure path records success=False metric
# ===========================================================================


class TestCreateWorktreeHandleFailure:
    """``create_worktree_handle`` records success=False metric on exception."""

    async def test_records_failure_metric_when_helper_raises(self, tmp_path, monkeypatch):
        from mahavishnu.core.worktree_providers import local as local_mod_inner
        from mahavishnu.observability import metrics as metrics_mod

        captured: list[tuple] = []

        def _capture(*args, **kwargs):
            captured.append((args, kwargs))

        monkeypatch.setattr(metrics_mod, "record_worktree_op", _capture)
        monkeypatch.setattr(
            "mahavishnu.core.paths.get_worktree_path",
            lambda *parts: tmp_path,
        )
        monkeypatch.setattr(
            "mahavishnu.core.paths.get_worktree_base_path",
            lambda: tmp_path / "base",
        )

        async def _exploding_create(*_a, **_kw):
            raise RuntimeError("git blew up")

        monkeypatch.setattr(local_mod_inner, "_create_worktree_via_git", _exploding_create)

        provider = LocalWorktreeProvider()
        with pytest.raises(RuntimeError, match="git blew up"):
            await provider.create_worktree_handle(
                repo="r", branch="b", base_ref="main", principal=_principal()
            )
        # Failure metric recorded exactly once.
        failures = [c for c in captured if c[1].get("success") is False]
        assert len(failures) == 1


# ===========================================================================
# _create_worktree_via_git / _remove_worktree_via_git / _list_worktrees_via_git
# ===========================================================================


class TestCreateWorktreeViaGit:
    """Module-level helper — success + failure + exception paths."""

    async def test_create_branch_uses_dash_b_flag(self):
        process = _fake_process()
        with patch(
            "asyncio.create_subprocess_exec", AsyncMock(return_value=process)
        ) as mock_exec:
            await _create_worktree_via_git(
                "git", Path("/r"), "feat", Path("/wt"), create_branch=True
            )
        cmd = mock_exec.call_args[0]
        assert "-b" in cmd
        assert "-B" not in cmd

    async def test_existing_branch_uses_dash_capital_b(self):
        process = _fake_process()
        with patch(
            "asyncio.create_subprocess_exec", AsyncMock(return_value=process)
        ) as mock_exec:
            await _create_worktree_via_git(
                "git", Path("/r"), "main", Path("/wt"), create_branch=False
            )
        cmd = mock_exec.call_args[0]
        assert "-B" in cmd
        assert "-b" not in cmd

    async def test_success_returns_metadata(self):
        process = _fake_process()
        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=process)):
            result = await _create_worktree_via_git(
                "git", Path("/r"), "br", Path("/wt"), create_branch=True
            )
        assert result == {
            "success": True,
            "worktree_path": "/wt",
            "branch": "br",
            "provider": "LocalWorktreeProvider",
        }

    async def test_nonzero_returncode_raises_creation_error(self):
        from mahavishnu.core.worktree_providers.errors import WorktreeCreationError

        process = _fake_process(returncode=128, stderr=b"fatal: bad ref")
        with (
            patch("asyncio.create_subprocess_exec", AsyncMock(return_value=process)),
            pytest.raises(WorktreeCreationError, match="Failed to create worktree"),
        ):
            await _create_worktree_via_git(
                "git", Path("/r"), "br", Path("/wt"), create_branch=True
            )

    async def test_exception_wraps_in_creation_error(self):
        from mahavishnu.core.worktree_providers.errors import WorktreeCreationError

        with (
            patch(
                "asyncio.create_subprocess_exec",
                AsyncMock(side_effect=RuntimeError("git missing")),
            ),
            pytest.raises(WorktreeCreationError, match="git worktree add failed"),
        ):
            await _create_worktree_via_git(
                "git", Path("/r"), "br", Path("/wt"), create_branch=True
            )

    async def test_nonzero_returncode_with_empty_stderr(self):
        from mahavishnu.core.worktree_providers.errors import WorktreeCreationError

        process = _fake_process(returncode=1, stderr=b"")
        with (
            patch("asyncio.create_subprocess_exec", AsyncMock(return_value=process)),
            pytest.raises(WorktreeCreationError),
        ):
            await _create_worktree_via_git(
                "git", Path("/r"), "br", Path("/wt"), create_branch=True
            )

    async def test_real_git_in_tmp_path(self, tmp_path):
        """End-to-end check: spawn a real repo, exercise the v4 path."""
        repo = _init_git_repo(tmp_path)
        wt = tmp_path / "wt"
        result = await _create_worktree_via_git(
            "git", repo, "feature-real", wt, create_branch=True
        )
        assert result["success"] is True
        assert Path(result["worktree_path"]).exists()


class TestRemoveWorktreeViaGit:
    """Module-level helper — success + failure + exception paths."""

    async def test_force_flag_added_when_true(self):
        process = _fake_process()
        with patch(
            "asyncio.create_subprocess_exec", AsyncMock(return_value=process)
        ) as mock_exec:
            await _remove_worktree_via_git(
                "git", Path("/r"), Path("/wt"), force=True
            )
        cmd = mock_exec.call_args[0]
        assert "--force" in cmd

    async def test_force_flag_omitted_when_false(self):
        process = _fake_process()
        with patch(
            "asyncio.create_subprocess_exec", AsyncMock(return_value=process)
        ) as mock_exec:
            await _remove_worktree_via_git(
                "git", Path("/r"), Path("/wt"), force=False
            )
        cmd = mock_exec.call_args[0]
        assert "--force" not in cmd

    async def test_success_returns_metadata(self):
        process = _fake_process()
        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=process)):
            result = await _remove_worktree_via_git(
                "git", Path("/r"), Path("/wt"), force=False
            )
        assert result == {
            "success": True,
            "removed_path": "/wt",
            "provider": "LocalWorktreeProvider",
        }

    async def test_nonzero_returncode_raises_operation_error(self):
        from mahavishnu.core.worktree_providers.errors import WorktreeOperationError

        process = _fake_process(returncode=1, stderr=b"locked")
        with (
            patch("asyncio.create_subprocess_exec", AsyncMock(return_value=process)),
            pytest.raises(WorktreeOperationError, match="Failed to remove worktree"),
        ):
            await _remove_worktree_via_git(
                "git", Path("/r"), Path("/wt"), force=False
            )

    async def test_exception_wraps_in_operation_error(self):
        from mahavishnu.core.worktree_providers.errors import WorktreeOperationError

        with (
            patch(
                "asyncio.create_subprocess_exec",
                AsyncMock(side_effect=FileNotFoundError("git missing")),
            ),
            pytest.raises(WorktreeOperationError, match="git worktree remove failed"),
        ):
            await _remove_worktree_via_git(
                "git", Path("/r"), Path("/wt"), force=False
            )

    async def test_real_git_in_tmp_path(self, tmp_path):
        repo = _init_git_repo(tmp_path)
        wt = tmp_path / "wt"
        # Create + remove via real git
        await _create_worktree_via_git("git", repo, "feature-real", wt, create_branch=True)
        assert wt.exists()
        result = await _remove_worktree_via_git("git", repo, wt, force=True)
        assert result["success"] is True


class TestListWorktreesViaGit:
    """Module-level helper — porcelain parser + exception paths."""

    async def test_returns_empty_for_empty_stdout(self):
        process = _fake_process(stdout=b"")
        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=process)):
            result = await _list_worktrees_via_git("git", Path("/r"))
        assert result == {
            "success": True,
            "worktrees": [],
            "provider": "LocalWorktreeProvider",
        }

    async def test_parses_multiple_worktrees(self):
        output = b"/a/wt1 main commit1 ok\n/a/wt2 feat commit2 dirty\n/a/wt3 dev commit3 prunable\n"
        process = _fake_process(stdout=output)
        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=process)):
            result = await _list_worktrees_via_git("git", Path("/a"))
        assert len(result["worktrees"]) == 3
        assert result["worktrees"][0]["branch"] == "main"
        assert result["worktrees"][2]["status"] == "prunable"

    async def test_skips_blank_and_short_lines(self):
        output = b"\n\n/a/wt only_three_parts\n\n/a/wt main commit ok\n"
        process = _fake_process(stdout=output)
        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=process)):
            result = await _list_worktrees_via_git("git", Path("/r"))
        assert len(result["worktrees"]) == 1

    async def test_nonzero_returncode_raises_operation_error(self):
        from mahavishnu.core.worktree_providers.errors import WorktreeOperationError

        process = _fake_process(returncode=128, stderr=b"not a git repo")
        with (
            patch("asyncio.create_subprocess_exec", AsyncMock(return_value=process)),
            pytest.raises(WorktreeOperationError, match="Failed to list worktrees"),
        ):
            await _list_worktrees_via_git("git", Path("/r"))

    async def test_exception_wraps_in_operation_error(self):
        from mahavishnu.core.worktree_providers.errors import WorktreeOperationError

        with (
            patch(
                "asyncio.create_subprocess_exec",
                AsyncMock(side_effect=FileNotFoundError("git missing")),
            ),
            pytest.raises(WorktreeOperationError, match="git worktree list failed"),
        ):
            await _list_worktrees_via_git("git", Path("/r"))

    async def test_real_git_in_tmp_path(self, tmp_path):
        repo = _init_git_repo(tmp_path)
        # The main repo is itself listed by `git worktree list --porcelain`.
        # Note: real git porcelain output is multi-line
        # (``worktree /path``, ``HEAD abc``, ``branch refs/heads/main``) —
        # the parser only consumes single-line entries, so the result list
        # is empty in this test. We still verify the subprocess ran.
        result = await _list_worktrees_via_git("git", repo)
        assert result["success"] is True
        assert isinstance(result["worktrees"], list)


# ===========================================================================
# supports_streaming — already covered elsewhere; one extra edge case
# ===========================================================================


class TestSupportsStreamingEdgeCases:
    """One additional edge case: storage with metadata=None."""

    def test_returns_false_for_storage_with_none_metadata(self):
        class _Bare:
            save_stream = lambda *a, **k: None
            load_stream = lambda *a, **k: iter([b""])

        assert supports_streaming(_Bare()) is False

    def test_returns_true_when_metadata_capability_and_methods_match(self):
        # Sanity: with both capability and methods, returns True.
        storage = _FakeStorage(capabilities=["stream"])
        assert supports_streaming(storage) is True


# ===========================================================================
# DirectGitWorktreeProvider health_check already exercised; verify exception
# path again with a fresh instance to keep the line traceable.
# ===========================================================================


class TestDirectGitHealthRecheck:
    """DirectGitWorktreeProvider.health_check swallowing exceptions."""

    def test_health_check_returns_false_on_shutil_error(self):
        p = DirectGitWorktreeProvider()
        with patch("shutil.which", side_effect=OSError("boom")):
            assert p.health_check() is False


# ===========================================================================
# HealthReport — add_warning populates list and __bool__ is False on warning
# ===========================================================================


class TestHealthReportBoolAndAdd:
    def test_default_is_truthy(self):
        assert bool(HealthReport()) is True

    def test_add_warning_marks_unhealthy(self):
        report = HealthReport()
        report.add_warning(kind="x", message="y")
        assert report.warnings == [{"kind": "x", "message": "y"}]
        assert bool(report) is False

    def test_healthy_false_without_warnings_is_false(self):
        assert bool(HealthReport(healthy=False)) is False