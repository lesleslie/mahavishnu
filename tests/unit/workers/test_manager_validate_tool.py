"""Tests for WorkerManager._validate_required_tool error UX.

Pin the error reporting contract introduced when the bare "Worker X requires
tool Y which is not on PATH" message was enriched with PATH context and a
fix hint pointing at MAHAVISHNU_NO_EXTRA_PATH / scripts/launch_mcp.py.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock

import pytest

from mahavishnu.core.errors import ErrorCode, MahavishnuError
from mahavishnu.workers.manager import WorkerManager


@dataclass
class _FakeEntry:
    """Minimal stand-in for a registry worker entry."""

    requires_tool: str | None = None


@pytest.fixture
def manager() -> WorkerManager:
    """WorkerManager with a stubbed terminal_manager — unused by _validate_required_tool."""
    return WorkerManager(terminal_manager=MagicMock(), max_concurrent=1)


@pytest.fixture
def fake_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace get_worker_entry with a stub returning a fixed requires_tool."""

    def _stub(worker_type: str, *, settings: object = None) -> _FakeEntry:
        return _FakeEntry(requires_tool="claude")

    monkeypatch.setattr(
        "mahavishnu.workers.manager.get_worker_entry", _stub, raising=True
    )


class TestMissingToolErrorContext:
    """Pin the structured context attached to the MahavishnuError raise."""

    def test_missing_tool_includes_path_context(
        self,
        manager: WorkerManager,
        fake_registry: None,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Any,
    ) -> None:
        """details must carry truncated PATH and the fix hint pointing at
        launch_mcp.py / MAHAVISHNU_NO_EXTRA_PATH so the operator doesn't have
        to guess why the subprocess PATH differs from the parent shell."""
        # Pin PATH to a known, short value so we can assert it verbatim.
        known_path = "/known/test/path"
        monkeypatch.setenv("PATH", known_path)

        # Force shutil.which to treat the lookup as missing regardless of
        # what the real PATH contains.
        monkeypatch.setattr(
            shutil, "which", lambda name: None, raising=True
        )

        with pytest.raises(MahavishnuError) as exc_info:
            manager._validate_required_tool("claude")

        err = exc_info.value
        assert err.error_code is ErrorCode.VALIDATION_ERROR
        assert err.details["worker_type"] == "claude"
        assert err.details["missing_tool"] == "claude"
        # The PATH we set flows through verbatim (no truncation for short
        # values).
        assert err.details["current_path_truncated"] == known_path
        # Fix hint must point at both the opt-out env var and the new
        # launch_mcp.py PATH bootstrap.
        assert "MAHAVISHNU_NO_EXTRA_PATH" in err.details["fix_hint"]
        assert "launch_mcp.py" in err.details["fix_hint"]

    def test_missing_tool_message_mentions_claude(
        self,
        manager: WorkerManager,
        fake_registry: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Sanity: the human-readable message still names the missing tool so
        error-routing log lines remain greppable."""
        monkeypatch.setenv("PATH", "/usr/bin:/bin")
        monkeypatch.setattr(shutil, "which", lambda name: None, raising=True)

        with pytest.raises(MahavishnuError) as exc_info:
            manager._validate_required_tool("claude")

        msg = str(exc_info.value)
        assert "claude" in msg
        # The enriched message should still surface the truncated PATH.
        assert "Current PATH:" in msg
        # And the fix line.
        assert "Fix:" in msg

    def test_path_truncation_at_512(
        self,
        manager: WorkerManager,
        fake_registry: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """PATH > 512 chars is truncated to 512 with a trailing '...'."""
        # 600-char PATH — well above the 512 threshold.
        long_path = "/a" * 300  # = 600 chars
        assert len(long_path) == 600
        monkeypatch.setenv("PATH", long_path)
        monkeypatch.setattr(shutil, "which", lambda name: None, raising=True)

        with pytest.raises(MahavishnuError) as exc_info:
            manager._validate_required_tool("claude")

        err = exc_info.value
        truncated = err.details["current_path_truncated"]
        # Total length should be 512 (kept chars) + 3 ("..." appendage) = 515.
        assert len(truncated) == 515
        assert truncated.endswith("...")
        # The first 512 chars of the truncated value match the first 512 of
        # the original PATH (i.e. we sliced it, not mutated it).
        assert truncated[:512] == long_path[:512]
        # Message body shows the same truncated value.
        assert truncated in str(err)
