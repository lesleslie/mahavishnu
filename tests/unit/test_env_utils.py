"""Unit tests for ``mahavishnu.core.env_utils.is_truthy_env``.

Extracted from ``mahavishnu.core.events.bodai_subscriber._accept_legacy_wire``
and ``.claude.hooks.bodai-activity-post-tool-use._debug_enabled``.
Pins the truthy-string contract so all callers stay consistent.
"""
from __future__ import annotations

import pytest

from mahavishnu.core.env_utils import is_truthy_env


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure the env var under test starts unset for each test."""
    monkeypatch.delenv("MAHAVISHNU_TEST_TRUTHY", raising=False)


def test_returns_default_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unset env var returns the supplied default (False by default)."""
    monkeypatch.delenv("MAHAVISHNU_TEST_TRUTHY", raising=False)
    assert is_truthy_env("MAHAVISHNU_TEST_TRUTHY") is False
    assert is_truthy_env("MAHAVISHNU_TEST_TRUTHY", default=True) is True


def test_truthy_strings_recognized(monkeypatch: pytest.MonkeyPatch) -> None:
    """The four documented truthy strings are all treated as True."""
    for value in ("1", "true", "yes", "on", "TRUE", "Yes", "  on  "):
        monkeypatch.setenv("MAHAVISHNU_TEST_TRUTHY", value)
        assert is_truthy_env("MAHAVISHNU_TEST_TRUTHY") is True, value


def test_falsy_and_garbage_strings_are_false(monkeypatch: pytest.MonkeyPatch) -> None:
    """Anything outside the four truthy strings is False, including empty string."""
    for value in ("0", "false", "no", "off", "", "  ", "maybe", "2"):
        monkeypatch.setenv("MAHAVISHNU_TEST_TRUTHY", value)
        assert is_truthy_env("MAHAVISHNU_TEST_TRUTHY") is False, value
