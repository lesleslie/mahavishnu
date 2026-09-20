"""Tests for ``mahavishnu.acp.auth`` — bearer auth gate, verify_token, redactor."""

from __future__ import annotations

import logging
import os
from pathlib import Path  # noqa: TC003 — Path is used at runtime (Path("..."), tmp_path / "name")

import pytest

from mahavishnu.acp.auth import (
    ENV_BEARER_TOKEN,
    ENV_BEARER_TOKEN_FILE,
    REDACTED_BEARER,
    BearerRedactionFilter,
    acquire_bearer,
    reset_cached_bearer_for_tests,
    validate_token_strength,
    verify_token,
)
from mahavishnu.acp.errors import AUTH_INVALID, ACPError

pytestmark = [pytest.mark.unit, pytest.mark.acp, pytest.mark.acp_stdio]


# ---------------------------------------------------------------------------
# verify_token — constant-time comparison
# ---------------------------------------------------------------------------

class TestVerifyToken:
    """``verify_token`` uses ``secrets.compare_digest``; plain ``==``/``!=`` forbidden."""

    def test_matching_tokens_verify(self) -> None:
        token = "a]super-secret-token-1234567890"
        assert verify_token(token, token) is True

    def test_different_tokens_do_not_verify(self) -> None:
        assert verify_token("token-aaaa-1234567890", "token-bbbb-1234567890") is False

    def test_different_lengths_do_not_verify(self) -> None:
        """Length-mismatch must not short-circuit to True."""
        assert verify_token("short", "a-much-longer-token-1234") is False

    def test_non_string_inputs_rejected(self) -> None:
        assert verify_token(None, "x") is False  # type: ignore[arg-type]
        assert verify_token(42, "x") is False  # type: ignore[arg-type]
        assert verify_token("x", None) is False  # type: ignore[arg-type]

    def test_empty_strings_do_not_verify(self) -> None:
        """Both-empty is False (no token provided) — fail-closed."""
        assert verify_token("", "") is False

    def test_one_empty_one_not_does_not_verify(self) -> None:
        assert verify_token("", "x") is False
        assert verify_token("x", "") is False

    def test_uses_compare_digest_not_equality(self) -> None:
        """Pin that ``verify_token`` uses ``secrets.compare_digest`` — not ``==``."""
        import inspect

        source = inspect.getsource(verify_token)
        assert "compare_digest" in source
        # Belt and suspenders: forbid the dangerous idioms in this function's
        # source. (Token comparison is timing-attack-vulnerable otherwise.)
        assert " == " not in source, "plain == comparison forbidden"
        assert " != " not in source, "plain != comparison forbidden"


# ---------------------------------------------------------------------------
# acquire_bearer — env-var + file modes, mutually exclusive, env-pop
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _isolate_bearer_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Wipe the bearer env vars before AND after each test in this class.

    The cached token (module-level state in ``auth.py``) is reset
    between tests so the env is read fresh each time.
    """
    monkeypatch.delenv(ENV_BEARER_TOKEN, raising=False)
    monkeypatch.delenv(ENV_BEARER_TOKEN_FILE, raising=False)
    reset_cached_bearer_for_tests()
    yield
    reset_cached_bearer_for_tests()


class TestAcquireBearerEnvVar:
    """``acquire_bearer`` reads the env var and pops it from the environment."""

    def test_returns_token_from_env_var(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        token = "x" * 40  # 40-byte bearer, meets minimum
        monkeypatch.setenv(ENV_BEARER_TOKEN, token)
        assert acquire_bearer() == token

    def test_pops_env_var_after_read(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The env var must be removed from ``os.environ`` after read so
        child processes don't inherit it (plan §Phase 2 Decision 5)."""
        token = "y" * 40
        monkeypatch.setenv(ENV_BEARER_TOKEN, token)
        acquire_bearer()
        assert ENV_BEARER_TOKEN not in os.environ

    def test_returns_none_when_neither_set(self) -> None:
        assert acquire_bearer() is None

    def test_cached_after_first_call(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Subsequent calls return the cached value without re-reading env."""
        token = "z" * 40
        monkeypatch.setenv(ENV_BEARER_TOKEN, token)
        first = acquire_bearer()
        # Now change the env — the cached value wins.
        monkeypatch.setenv(ENV_BEARER_TOKEN, "DIFFERENT" * 8)
        second = acquire_bearer()
        assert first == token
        assert second == token

    def test_reset_clears_cache(self, monkeypatch: pytest.MonkeyPatch) -> None:
        token = "a" * 40
        monkeypatch.setenv(ENV_BEARER_TOKEN, token)
        assert acquire_bearer() == token
        reset_cached_bearer_for_tests()
        monkeypatch.setenv(ENV_BEARER_TOKEN, "b" * 40)
        assert acquire_bearer() == "b" * 40


class TestAcquireBearerFile:
    """``acquire_bearer`` reads from a file when ``ENV_BEARER_TOKEN_FILE`` is set."""

    def test_reads_token_from_file(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        token = "f" * 40
        path = tmp_path / "bearer"
        path.write_text(token)
        path.chmod(0o600)
        monkeypatch.setenv(ENV_BEARER_TOKEN_FILE, str(path))
        assert acquire_bearer() == token

    def test_file_mode_0600_required(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """A file with permissive mode must be rejected."""
        path = tmp_path / "bearer-bad"
        path.write_text("x" * 40)
        path.chmod(0o644)  # group-readable; rejected
        monkeypatch.setenv(ENV_BEARER_TOKEN_FILE, str(path))
        with pytest.raises(ACPError) as excinfo:
            acquire_bearer()
        assert excinfo.value.code == AUTH_INVALID
        assert "permissive mode" in excinfo.value.message

    def test_file_strips_whitespace(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Trailing newline is stripped — the file's contents may end with one."""
        path = tmp_path / "bearer"
        path.write_text("f" * 40 + "\n")
        path.chmod(0o600)
        monkeypatch.setenv(ENV_BEARER_TOKEN_FILE, str(path))
        assert acquire_bearer() == "f" * 40

    def test_file_unreadable_raises(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """A nonexistent file must surface as ``ACPError(AUTH_INVALID)``."""
        monkeypatch.setenv(ENV_BEARER_TOKEN_FILE, str(tmp_path / "does-not-exist"))
        with pytest.raises(ACPError) as excinfo:
            acquire_bearer()
        assert excinfo.value.code == AUTH_INVALID


class TestAcquireBearerMutuallyExclusive:
    """Setting both env var and env-var-file is rejected."""

    def test_both_set_raises(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        path = tmp_path / "bearer"
        path.write_text("f" * 40)
        path.chmod(0o600)
        monkeypatch.setenv(ENV_BEARER_TOKEN, "x" * 40)
        monkeypatch.setenv(ENV_BEARER_TOKEN_FILE, str(path))
        with pytest.raises(ACPError) as excinfo:
            acquire_bearer()
        assert excinfo.value.code == AUTH_INVALID
        assert "mutually exclusive" in excinfo.value.message


# ---------------------------------------------------------------------------
# validate_token_strength
# ---------------------------------------------------------------------------

class TestValidateTokenStrength:
    """Tokens shorter than the minimum length are rejected."""

    def test_short_token_rejected(self) -> None:
        with pytest.raises(ACPError) as excinfo:
            validate_token_strength("x" * 8)
        assert excinfo.value.code == AUTH_INVALID
        assert "too short" in excinfo.value.message

    def test_minimum_length_accepted(self) -> None:
        validate_token_strength("x" * 16)  # exactly minimum — no raise

    def test_long_token_accepted(self) -> None:
        validate_token_strength("x" * 64)


# ---------------------------------------------------------------------------
# BearerRedactionFilter
# ---------------------------------------------------------------------------

class TestBearerRedactionFilter:
    """The redactor replaces bearer values in log records before the handler."""

    def test_bearer_value_replaced_in_message(self) -> None:
        token = "super-secret-1234567890"
        flt = BearerRedactionFilter(token)
        record = logging.LogRecord(
            name="mahavishnu.acp.test",
            level=logging.INFO,
            pathname=__file__,
            lineno=0,
            msg=f"connecting with bearer={token}",
            args=(),
            exc_info=None,
        )
        flt.filter(record)
        assert REDACTED_BEARER in record.getMessage()
        assert token not in record.getMessage()

    def test_unrelated_message_untouched(self) -> None:
        token = "super-secret-1234567890"
        flt = BearerRedactionFilter(token)
        record = logging.LogRecord(
            name="mahavishnu.acp.test",
            level=logging.INFO,
            pathname=__file__,
            lineno=0,
            msg="session started",
            args=(),
            exc_info=None,
        )
        flt.filter(record)
        assert record.getMessage() == "session started"

    def test_filter_returns_true(self) -> None:
        """The filter never suppresses a record (returns True unconditionally)."""
        flt = BearerRedactionFilter("x" * 40)
        record = logging.LogRecord(
            name="t",
            level=logging.INFO,
            pathname=__file__,
            lineno=0,
            msg="hello",
            args=(),
            exc_info=None,
        )
        assert flt.filter(record) is True

    def test_empty_bearer_is_noop(self) -> None:
        """An empty bearer string doesn't accidentally redact everything."""
        flt = BearerRedactionFilter("")
        record = logging.LogRecord(
            name="t",
            level=logging.INFO,
            pathname=__file__,
            lineno=0,
            msg="hello world",
            args=(),
            exc_info=None,
        )
        flt.filter(record)
        assert record.getMessage() == "hello world"

    def test_redacts_in_format_args(self) -> None:
        """When the bearer appears in ``record.args`` (structured logging),
        the redactor still catches it."""
        token = "token-abc-1234567890"
        flt = BearerRedactionFilter(token)
        record = logging.LogRecord(
            name="t",
            level=logging.INFO,
            pathname=__file__,
            lineno=0,
            msg="authorization=%s",
            args=(token,),
            exc_info=None,
        )
        flt.filter(record)
        assert REDACTED_BEARER in record.getMessage()
        assert token not in record.getMessage()
