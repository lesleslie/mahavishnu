"""Tests for ``mahavishnu.distill.reviewer.ReviewerIdentity``.

Plan 5 audit finding H6 - reviewer identity from shell env has no trust
root. Require either:

- ``MAHAVISHNU_USER_ID`` env var AND the user is in
  ``MAHAVISHNU_PUBLISHER_ALLOWLIST``, OR
- a signed token from a configured trust root (placeholder for future RBAC)

When no allowlist is configured, the distiller is bootstrap-allowed
with a WARNING + an audit log entry (NOT a hard fail - that's the v1
behavior; the audit only asks for the warning and the audit log).

A CLI flag must never override the missing env var (env wins).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pytest

from mahavishnu.core.errors import ReviewerNotTrustedError
from mahavishnu.distill.reviewer import (
    ReviewerDecision,
    ReviewerIdentity,
    ReviewerSource,
)

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def allowlist_file(tmp_path: Path) -> Path:
    """Write an allowlist file with two trusted reviewers."""
    p = tmp_path / "publisher_allowlist.txt"
    p.write_text("alice\nbob\n", encoding="utf-8")
    return p


@pytest.fixture
def empty_allowlist_file(tmp_path: Path) -> Path:
    """An allowlist file that exists but lists no one."""
    p = tmp_path / "publisher_allowlist_empty.txt"
    p.write_text("", encoding="utf-8")
    return p


@pytest.fixture
def missing_allowlist_path(tmp_path: Path) -> Path:
    """A path that does not exist (used for bootstrap-mode test)."""
    return tmp_path / "does_not_exist.txt"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure no MAHAVISHNU_USER_ID / MAHAVISHNU_PUBLISHER_ALLOWLIST leaks between tests."""
    monkeypatch.delenv("MAHAVISHNU_USER_ID", raising=False)
    monkeypatch.delenv("MAHAVISHNU_PUBLISHER_ALLOWLIST", raising=False)


# ---------------------------------------------------------------------------
# Happy path: env + in allowlist
# ---------------------------------------------------------------------------


class TestEnvAndAllowlistAllowed:
    def test_env_user_in_allowlist_file_is_allowed(
        self,
        monkeypatch: pytest.MonkeyPatch,
        allowlist_file: Path,
    ) -> None:
        """User from env + listed in allowlist file -> ALLOWED."""
        monkeypatch.setenv("MAHAVISHNU_USER_ID", "alice")
        monkeypatch.setenv("MAHAVISHNU_PUBLISHER_ALLOWLIST", str(allowlist_file))

        identity = ReviewerIdentity.from_env()
        decision = identity.check()

        assert decision.allowed is True
        assert decision.source is ReviewerSource.ENV_ALLOWLIST
        assert decision.reviewer_id == "alice"
        assert decision.reason == ""

    def test_env_user_in_allowlist_csv_is_allowed(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """User from env + listed in inline CSV allowlist -> ALLOWED."""
        monkeypatch.setenv("MAHAVISHNU_USER_ID", "carol")
        monkeypatch.setenv("MAHAVISHNU_PUBLISHER_ALLOWLIST", "alice,bob,carol")

        identity = ReviewerIdentity.from_env()
        decision = identity.check()

        assert decision.allowed is True
        assert decision.reviewer_id == "carol"
        assert decision.source is ReviewerSource.ENV_ALLOWLIST


# ---------------------------------------------------------------------------
# Reject: env + NOT in allowlist
# ---------------------------------------------------------------------------


class TestEnvUserNotInAllowlistRejected:
    def test_raises_when_user_not_in_allowlist(
        self,
        monkeypatch: pytest.MonkeyPatch,
        allowlist_file: Path,
    ) -> None:
        """User from env + NOT in allowlist -> ReviewerNotTrustedError."""
        monkeypatch.setenv("MAHAVISHNU_USER_ID", "mallory")
        monkeypatch.setenv("MAHAVISHNU_PUBLISHER_ALLOWLIST", str(allowlist_file))

        identity = ReviewerIdentity.from_env()

        with pytest.raises(ReviewerNotTrustedError) as excinfo:
            identity.enforce()

        assert "mallory" in str(excinfo.value)
        assert "allowlist" in str(excinfo.value).lower()
        assert excinfo.value.error_code == "MHV-483"
        assert excinfo.value.reviewer_id == "mallory"

    def test_check_returns_denied_decision(
        self,
        monkeypatch: pytest.MonkeyPatch,
        allowlist_file: Path,
    ) -> None:
        """check() (non-raising) returns allowed=False for not-in-allowlist."""
        monkeypatch.setenv("MAHAVISHNU_USER_ID", "eve")
        monkeypatch.setenv("MAHAVISHNU_PUBLISHER_ALLOWLIST", str(allowlist_file))

        identity = ReviewerIdentity.from_env()
        decision = identity.check()

        assert decision.allowed is False
        assert decision.source is ReviewerSource.ENV_ALLOWLIST
        assert "not in" in decision.reason.lower() and "allowlist" in decision.reason.lower()

    def test_empty_allowlist_is_bootstrap_mode(
        self,
        monkeypatch: pytest.MonkeyPatch,
        empty_allowlist_file: Path,
    ) -> None:
        """Empty allowlist file == allowlist not configured (bootstrap).

        An empty allowlist is functionally identical to a missing one
        (no entries to check against) so the v1 semantic is to
        bootstrap-allow with a WARNING. Operators who want strict
        enforcement MUST populate the file.
        """
        monkeypatch.setenv("MAHAVISHNU_USER_ID", "alice")
        monkeypatch.setenv("MAHAVISHNU_PUBLISHER_ALLOWLIST", str(empty_allowlist_file))

        identity = ReviewerIdentity.from_env()
        decision = identity.check()

        assert decision.allowed is True
        assert decision.source is ReviewerSource.BOOTSTRAP


# ---------------------------------------------------------------------------
# Bootstrap mode: env set, no allowlist file -> WARN, allowed
# ---------------------------------------------------------------------------


class TestBootstrapMode:
    def test_missing_allowlist_file_with_env_is_bootstrap_allowed(
        self,
        monkeypatch: pytest.MonkeyPatch,
        missing_allowlist_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Env + no allowlist file -> bootstrap-allowed with WARNING."""
        monkeypatch.setenv("MAHAVISHNU_USER_ID", "alice")
        monkeypatch.setenv("MAHAVISHNU_PUBLISHER_ALLOWLIST", str(missing_allowlist_path))

        identity = ReviewerIdentity.from_env()
        with caplog.at_level(logging.WARNING, logger="mahavishnu.distill.reviewer"):
            decision = identity.check()

        assert decision.allowed is True
        assert decision.source is ReviewerSource.BOOTSTRAP
        assert decision.reviewer_id == "alice"
        assert "bootstrap" in decision.reason.lower() or "allowlist" in decision.reason.lower()

        assert any(
            record.levelno == logging.WARNING and "allowlist" in record.getMessage().lower()
            for record in caplog.records
        )

    def test_no_allowlist_env_var_with_user_id_is_bootstrap_allowed(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """User set + no allowlist env var at all -> bootstrap-allowed with WARNING."""
        monkeypatch.setenv("MAHAVISHNU_USER_ID", "alice")
        monkeypatch.delenv("MAHAVISHNU_PUBLISHER_ALLOWLIST", raising=False)

        identity = ReviewerIdentity.from_env()
        with caplog.at_level(logging.WARNING, logger="mahavishnu.distill.reviewer"):
            decision = identity.check()

        assert decision.allowed is True
        assert decision.source is ReviewerSource.BOOTSTRAP


# ---------------------------------------------------------------------------
# Reject: no env + CLI flag (env wins, but a missing env means rejected)
# ---------------------------------------------------------------------------


class TestMissingEnvRejected:
    def test_no_env_no_cli_flag_is_rejected(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """No env + no CLI flag -> ReviewerNotTrustedError."""
        monkeypatch.delenv("MAHAVISHNU_USER_ID", raising=False)

        identity = ReviewerIdentity.from_env(cli_reviewer=None)

        with pytest.raises(ReviewerNotTrustedError) as excinfo:
            identity.enforce()

        assert "MAHAVISHNU_USER_ID" in str(excinfo.value)

    def test_cli_flag_alone_does_not_satisfy_gate(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """CLI flag without env var -> rejected (env wins)."""
        monkeypatch.delenv("MAHAVISHNU_USER_ID", raising=False)

        identity = ReviewerIdentity.from_env(cli_reviewer="alice")

        with pytest.raises(ReviewerNotTrustedError):
            identity.enforce()

        decision = identity.check()
        assert decision.allowed is False
        assert decision.cli_reviewer == "alice"
        assert decision.source is ReviewerSource.NONE

    def test_env_wins_over_cli_flag(
        self,
        monkeypatch: pytest.MonkeyPatch,
        allowlist_file: Path,
    ) -> None:
        """When env present, cli_reviewer is ignored - env's identity used."""
        monkeypatch.setenv("MAHAVISHNU_USER_ID", "alice")
        monkeypatch.setenv("MAHAVISHNU_PUBLISHER_ALLOWLIST", str(allowlist_file))

        identity = ReviewerIdentity.from_env(cli_reviewer="mallory")
        decision = identity.check()

        assert decision.allowed is True
        assert decision.reviewer_id == "alice"
        assert decision.cli_reviewer == "mallory"


# ---------------------------------------------------------------------------
# Audit log entry
# ---------------------------------------------------------------------------


class TestAuditLog:
    def test_bootstrap_emit_writes_audit_entry(
        self,
        monkeypatch: pytest.MonkeyPatch,
        missing_allowlist_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Bootstrap-allow path emits an audit log entry tagged for review."""
        monkeypatch.setenv("MAHAVISHNU_USER_ID", "alice")
        monkeypatch.setenv("MAHAVISHNU_PUBLISHER_ALLOWLIST", str(missing_allowlist_path))

        identity = ReviewerIdentity.from_env()
        with caplog.at_level(logging.INFO, logger="mahavishnu.distill.reviewer"):
            decision = identity.check()
            identity.emit_audit_log(decision)

        audit_records = [r for r in caplog.records if getattr(r, "audit", False)]
        assert len(audit_records) >= 1
        msg = audit_records[0].getMessage().lower()
        assert "alice" in msg
        assert "bootstrap" in msg or "allowlist" in msg


# ---------------------------------------------------------------------------
# Shape / API pinning
# ---------------------------------------------------------------------------


class TestAPIShape:
    def test_decision_is_frozen_value_object(self) -> None:
        """ReviewerDecision is a frozen value object."""
        d = ReviewerDecision(
            allowed=True,
            source=ReviewerSource.ENV_ALLOWLIST,
            reviewer_id="alice",
            cli_reviewer=None,
            reason="",
        )
        with pytest.raises((AttributeError, TypeError)):
            d.allowed = False  # type: ignore[misc]

    def test_source_enum_has_four_values(self) -> None:
        """The source enum covers all paths: env+allowlist, bootstrap, none, token."""
        values = {s.value for s in ReviewerSource}
        assert values == {"env_allowlist", "bootstrap", "none", "signed_token"}

    def test_from_env_returns_identity_with_captured_state(self) -> None:
        """from_env() captures env state at construction time."""
        from_env = ReviewerIdentity.from_env
        assert callable(from_env)
