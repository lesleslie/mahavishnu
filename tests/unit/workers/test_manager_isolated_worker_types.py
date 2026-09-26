"""Tests for the narrowed _create_isolated_worker after Phase 4.

Plan v3 Phase 4 — only `shepherd` is supported as an isolated-worker
backend. Every other worker_type must raise ``ValueError`` with a
helpful message that points to the new ADR. The historical surface
``apple_container`` / ``e2b_sandbox`` was retired — see
``docs/decisions/2026-09-24-legacy-worker-deprecation.md``.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from mahavishnu.workers.manager import (
    WORKER_SUPPORTED_TYPES,
    WorkerManager,
    _create_isolated_worker,
)
from mahavishnu.workers.registry import RuntimeKind, WorkerCategory, WorkerConfig


class TestIsolatedWorkerFactoryHappyPath:
    """``worker_type="shepherd"`` constructs ShepherdBackendWorker."""

    def test_shepherd_with_writable_root_returns_backend(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``writable_root`` provided → ShepherdBackendWorker is constructed."""
        captured_kwargs: dict[str, object] = {}

        class _FakeShepherd:
            def __init__(self, **kw: object) -> None:
                captured_kwargs.update(kw)

        fake_module = MagicMock()
        fake_module.ShepherdBackendWorker = _FakeShepherd
        monkeypatch.setattr(
            "mahavishnu.workers.shepherd_backend.ShepherdBackendWorker",
            _FakeShepherd,
        )

        backend = _create_isolated_worker(
            worker_type="shepherd",
            session_buddy_client=None,
            kwargs={
                "writable_root": "/tmp/shepherd-root",
                "workspace_cwd": "/tmp",
                "placement": "auto",
                "timeout": 300,
            },
        )

        assert isinstance(backend, _FakeShepherd)
        assert captured_kwargs["writable_root"] == "/tmp/shepherd-root"
        assert captured_kwargs["workspace_cwd"] == "/tmp"
        assert captured_kwargs["placement"] == "auto"
        # ShepherdBackendWorker takes ``default_timeout`` (the per-call
        # timeout from kwargs is mapped through this name).
        assert captured_kwargs["default_timeout"] == 300
        assert captured_kwargs["session_buddy_client"] is None

    def test_shepherd_without_writable_root_raises_mahavishnu_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Missing ``writable_root`` → MahavishnuError (fail-closed by design)."""
        from mahavishnu.core.errors import (
            ErrorCode,
            MahavishnuError,
        )

        fake_module = MagicMock()
        monkeypatch.setattr(
            "mahavishnu.workers.shepherd_backend.ShepherdBackendWorker",
            lambda **kw: MagicMock(),
        )

        with pytest.raises(MahavishnuError) as exc_info:
            _create_isolated_worker(
                worker_type="shepherd",
                session_buddy_client=None,
                kwargs={},
            )

        assert exc_info.value.error_code is ErrorCode.WORKER_UNAVAILABLE
        assert exc_info.value.details.get("worker_type") == "shepherd"
        assert "writable_root" in str(exc_info.value)


class TestIsolatedWorkerFactoryUnsupportedTypes:
    """Every other worker_type raises ValueError per Plan v3 Phase 4."""

    @pytest.mark.parametrize(
        "unsupported_type",
        [
            # Historical Apple-container tier names.
            "apple-container",
            "apple_container",
            # Historical E2B-sandbox tier names.
            "e2b-sandbox",
            "e2b_sandbox",
            "e2b",
            # Other legacy names that the registry never registered but
            # callers might pass.
            "container",
            "sandbox",
            "vm",
        ],
    )
    def test_unsupported_worker_type_raises_value_error(
        self, unsupported_type: str
    ) -> None:
        """Each unsupported worker_type → ValueError pointing to the ADR."""
        with pytest.raises(ValueError) as exc_info:
            _create_isolated_worker(
                worker_type=unsupported_type,
                session_buddy_client=None,
                kwargs={},
            )

        message = str(exc_info.value)
        assert unsupported_type in message
        assert "2026-09-24-legacy-worker-deprecation.md" in message
        assert "shepherd" in message


class TestWorkerSupportedTypesMetadata:
    """The exposed SUPPORTED_TYPES set is the single source of truth."""

    def test_supported_types_is_exactly_shepherd(self) -> None:
        """Per Plan v3 Phase 4, only shepherd remains after the legacy purge."""
        assert set(WORKER_SUPPORTED_TYPES) == {"shepherd"}

    def test_supported_types_is_frozenset(self) -> None:
        """Avoids accidental mutation at runtime."""
        from collections.abc import Iterable

        assert isinstance(WORKER_SUPPORTED_TYPES, frozenset)
        # Sanity: container protocol so iteration is stable.
        assert list(WORKER_SUPPORTED_TYPES) == ["shepherd"]


# Worker types retired per docs/decisions/2026-09-24-legacy-worker-deprecation.md.
# Every entry MUST raise ValueError from WorkerManager._create_isolated_worker_from_config
# with a message naming the retirement, pointing to shepherd as the migration target,
# and citing the ADR filename.
_RETIRED_WORKER_TYPES: tuple[tuple[str, WorkerCategory], ...] = (
    ("e2b-sandbox", WorkerCategory.CONTAINER),
    ("apple-container", WorkerCategory.CONTAINER),
    ("terminal-crow", WorkerCategory.AI_ASSISTANT),
    ("a2a", WorkerCategory.GATEWAY),
    ("openclaw", WorkerCategory.GATEWAY),
    ("openhands", WorkerCategory.GATEWAY),
    ("generic-shell", WorkerCategory.SHELL),
    ("application", WorkerCategory.APPLICATION),
    ("gateway-openclaw", WorkerCategory.GATEWAY),
)


class TestCreateIsolatedWorkerFromConfigContract:
    """Pin the contract Task 1 introduced on WorkerManager._create_isolated_worker_from_config.

    Task 1 refactored WorkerManager so every retired worker_type raises a
    ValueError from a single dispatch surface. This pins the contract so
    future refactors that silently regress the message or skip a retired
    type fail CI rather than reaching production.
    """

    @pytest.fixture
    def manager(self) -> WorkerManager:
        """Build a WorkerManager with a mocked terminal_manager (unused here)."""
        return WorkerManager(terminal_manager=MagicMock(), max_concurrent=1)

    @pytest.mark.parametrize(
        ("retired_type", "category"),
        _RETIRED_WORKER_TYPES,
    )
    def test_retired_type_raises_value_error_with_advertised_message(
        self,
        manager: WorkerManager,
        retired_type: str,
        category: WorkerCategory,
    ) -> None:
        """ValueError must name (a) the retirement, (b) shepherd, (c) the ADR."""
        config = WorkerConfig(
            name=retired_type,
            worker_type=retired_type,
            command="",
            category=category,
            description=retired_type,
            required_env=[],
            runtime_kind=RuntimeKind.NONE,
        )
        with pytest.raises(ValueError) as exc_info:
            manager._create_isolated_worker_from_config(config, {})

        msg = str(exc_info.value)
        assert "legacy isolated-worker surface has been retired" in msg, msg
        assert "shepherd" in msg, msg
        assert "2026-09-24-legacy-worker-deprecation.md" in msg, msg

    def test_shepherd_happy_path_returns_shepherd_backend_worker(
        self,
        manager: WorkerManager,
        tmp_path,
    ) -> None:
        """Shepherd still constructs ShepherdBackendWorker (Task 1 preserved the happy path)."""
        config = WorkerConfig(
            name="shepherd",
            worker_type="shepherd",
            command="",
            category=WorkerCategory.CONTAINER,
            description="shepherd OS-level syscall jail",
            required_env=[],
            runtime_kind=RuntimeKind.NONE,
        )
        worker = manager._create_isolated_worker_from_config(
            config,
            {"writable_root": tmp_path},
        )
        assert worker is not None
        assert getattr(worker, "writable_root", None) == tmp_path
