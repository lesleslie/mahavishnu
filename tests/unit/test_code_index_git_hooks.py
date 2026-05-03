"""Tests for git hook installation."""

from __future__ import annotations

from pathlib import Path

import pytest

from mahavishnu.core.code_index.git_hooks import (
    _HOOK_NAMES,
    HOOK_CONTENT,
    MAHAVISHNU_HEADER,
    install_hooks,
    uninstall_hooks,
)


class TestInstallHooks:
    def test_creates_all_three_hooks(self, tmp_path: Path) -> None:
        installed = install_hooks(str(tmp_path))
        assert set(installed) == set(_HOOK_NAMES)

        for name in _HOOK_NAMES:
            hook = tmp_path / ".git" / "hooks" / name
            assert hook.exists()
            assert MAHAVISHNU_HEADER in hook.read_text()

    def test_makes_hooks_executable(self, tmp_path: Path) -> None:
        install_hooks(str(tmp_path))
        for name in _HOOK_NAMES:
            hook = tmp_path / ".git" / "hooks" / name
            assert hook.stat().st_mode & 0o111 != 0

    def test_refuses_unmanaged_hook(self, tmp_path: Path) -> None:
        """Raise FileExistsError when an existing hook lacks the mahavishnu header."""
        hook = tmp_path / ".git" / "hooks" / "post-commit"
        hook.parent.mkdir(parents=True, exist_ok=True)
        hook.write_text("#!/bin/sh\nsome other hook\n")

        with pytest.raises(FileExistsError, match="not managed"):
            install_hooks(str(tmp_path))

    def test_force_overwrites_unmanaged_hook(self, tmp_path: Path) -> None:
        hook = tmp_path / ".git" / "hooks" / "post-commit"
        hook.parent.mkdir(parents=True, exist_ok=True)
        hook.write_text("#!/bin/sh\nsome other hook\n")

        installed = install_hooks(str(tmp_path), force=True)
        assert "post-commit" in installed
        assert MAHAVISHNU_HEADER in hook.read_text()

    def test_idempotent_reinstall(self, tmp_path: Path) -> None:
        """Re-installing over a mahavishnu-managed hook succeeds without force."""
        first = install_hooks(str(tmp_path))
        second = install_hooks(str(tmp_path))
        assert first == second


class TestUninstallHooks:
    def test_removes_managed_hooks(self, tmp_path: Path) -> None:
        install_hooks(str(tmp_path))
        removed = uninstall_hooks(str(tmp_path))
        assert set(removed) == set(_HOOK_NAMES)

        for name in _HOOK_NAMES:
            hook = tmp_path / ".git" / "hooks" / name
            assert not hook.exists()

    def test_preserves_unmanaged_hooks(self, tmp_path: Path) -> None:
        """Unmanaged hooks must not be touched."""
        hooks_dir = tmp_path / ".git" / "hooks"
        hooks_dir.mkdir(parents=True)

        # Write an unmanaged hook
        unmanaged = hooks_dir / "post-commit"
        unmanaged.write_text("#!/bin/sh\nunmanaged hook\n")

        removed = uninstall_hooks(str(tmp_path))
        assert removed == []
        assert unmanaged.exists()

    def test_mixed_managed_and_unmanaged(self, tmp_path: Path) -> None:
        """Only mahavishnu-managed hooks are removed; unmanaged ones stay."""
        install_hooks(str(tmp_path))

        # Overwrite post-commit with unmanaged content
        hooks_dir = tmp_path / ".git" / "hooks"
        post_commit = hooks_dir / "post-commit"
        post_commit.write_text("#!/bin/sh\nunmanaged\n")

        removed = uninstall_hooks(str(tmp_path))
        # post-commit is no longer managed, so it should NOT be removed
        assert "post-commit" not in removed
        assert post_commit.exists()
        # post-merge and post-rewrite should still be removed
        assert "post-merge" in removed
        assert "post-rewrite" in removed
        assert not (hooks_dir / "post-merge").exists()
        assert not (hooks_dir / "post-rewrite").exists()

    def test_nonexistent_repo(self, tmp_path: Path) -> None:
        """No hooks dir means nothing to remove."""
        removed = uninstall_hooks(str(tmp_path))
        assert removed == []


class TestHookContent:
    def test_is_valid_shell_script(self) -> None:
        assert HOOK_CONTENT.startswith("#!/bin/sh")

    def test_contains_mahavishnu_header(self) -> None:
        assert MAHAVISHNU_HEADER in HOOK_CONTENT
