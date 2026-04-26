"""Tests for Mahavishnu WebSocket TLS configuration."""

from __future__ import annotations

import os
import ssl
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mahavishnu.websocket.tls_config import (
    get_tls_cli_options,
    get_websocket_tls_config,
    load_ssl_context,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _set_env(key: str, value: str) -> None:
    """Set an environment variable for testing."""
    os.environ[key] = value


def _del_env(*keys: str) -> None:
    """Remove environment variables, ignoring missing ones."""
    for key in keys:
        os.environ.pop(key, None)


TLS_ENV_KEYS = [
    "MAHAVISHNU_WS_TLS_ENABLED",
    "MAHAVISHNU_WS_CERT_FILE",
    "MAHAVISHNU_WS_KEY_FILE",
    "MAHAVISHNU_WS_CA_FILE",
    "MAHAVISHNU_WS_VERIFY_CLIENT",
]


# ---------------------------------------------------------------------------
# get_websocket_tls_config
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestGetWebsocketTlsConfig:
    """Tests for get_websocket_tls_config."""

    def test_returns_disabled_by_default(self) -> None:
        """TLS should be disabled when no env vars are set."""
        _del_env(*TLS_ENV_KEYS)

        config = get_websocket_tls_config()

        assert config["tls_enabled"] is False
        assert config["cert_file"] is None
        assert config["key_file"] is None
        assert config["ca_file"] is None
        assert config["verify_client"] is False

    def test_tls_enabled_when_true(self) -> None:
        """TLS enabled flag should be True when env var is 'true'."""
        _del_env(*TLS_ENV_KEYS)
        _set_env("MAHAVISHNU_WS_TLS_ENABLED", "true")

        config = get_websocket_tls_config()

        assert config["tls_enabled"] is True

    def test_tls_enabled_case_insensitive(self) -> None:
        """TLS enabled flag should handle mixed case."""
        _del_env(*TLS_ENV_KEYS)
        _set_env("MAHAVISHNU_WS_TLS_ENABLED", "TrUe")

        config = get_websocket_tls_config()

        assert config["tls_enabled"] is True

    def test_tls_disabled_when_false(self) -> None:
        """TLS enabled flag should be False when env var is 'false'."""
        _del_env(*TLS_ENV_KEYS)
        _set_env("MAHAVISHNU_WS_TLS_ENABLED", "false")

        config = get_websocket_tls_config()

        assert config["tls_enabled"] is False

    def test_tls_disabled_for_arbitrary_value(self) -> None:
        """TLS enabled flag should be False for non-'true' values."""
        _del_env(*TLS_ENV_KEYS)
        _set_env("MAHAVISHNU_WS_TLS_ENABLED", "yes")

        config = get_websocket_tls_config()

        assert config["tls_enabled"] is False

    def test_cert_file_from_env(self) -> None:
        """Certificate file path should be read from env var."""
        _del_env(*TLS_ENV_KEYS)
        _set_env("MAHAVISHNU_WS_CERT_FILE", "/tmp/cert.pem")

        config = get_websocket_tls_config()

        assert config["cert_file"] == "/tmp/cert.pem"

    def test_key_file_from_env(self) -> None:
        """Key file path should be read from env var."""
        _del_env(*TLS_ENV_KEYS)
        _set_env("MAHAVISHNU_WS_KEY_FILE", "/tmp/key.pem")

        config = get_websocket_tls_config()

        assert config["key_file"] == "/tmp/key.pem"

    def test_ca_file_from_env(self) -> None:
        """CA file path should be read from env var."""
        _del_env(*TLS_ENV_KEYS)
        _set_env("MAHAVISHNU_WS_CA_FILE", "/tmp/ca.pem")

        config = get_websocket_tls_config()

        assert config["ca_file"] == "/tmp/ca.pem"

    def test_verify_client_true(self) -> None:
        """Client verification should be True when env var is 'true'."""
        _del_env(*TLS_ENV_KEYS)
        _set_env("MAHAVISHNU_WS_VERIFY_CLIENT", "true")

        config = get_websocket_tls_config()

        assert config["verify_client"] is True

    def test_verify_client_false_by_default(self) -> None:
        """Client verification should default to False."""
        _del_env(*TLS_ENV_KEYS)

        config = get_websocket_tls_config()

        assert config["verify_client"] is False

    def test_full_config(self) -> None:
        """All config values should be populated from env vars."""
        _del_env(*TLS_ENV_KEYS)
        _set_env("MAHAVISHNU_WS_TLS_ENABLED", "true")
        _set_env("MAHAVISHNU_WS_CERT_FILE", "/certs/server.pem")
        _set_env("MAHAVISHNU_WS_KEY_FILE", "/certs/server-key.pem")
        _set_env("MAHAVISHNU_WS_CA_FILE", "/certs/ca.pem")
        _set_env("MAHAVISHNU_WS_VERIFY_CLIENT", "true")

        config = get_websocket_tls_config()

        assert config["tls_enabled"] is True
        assert config["cert_file"] == "/certs/server.pem"
        assert config["key_file"] == "/certs/server-key.pem"
        assert config["ca_file"] == "/certs/ca.pem"
        assert config["verify_client"] is True

    def test_uses_correct_prefix(self) -> None:
        """Verify the function delegates with the correct prefix."""
        _del_env(*TLS_ENV_KEYS)

        with patch(
            "mahavishnu.websocket.tls_config.get_tls_config_from_env"
        ) as mock_from_env:
            mock_from_env.return_value = {"tls_enabled": False}
            get_websocket_tls_config()

        mock_from_env.assert_called_once_with("MAHAVISHNU_WS")


# ---------------------------------------------------------------------------
# load_ssl_context
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestLoadSslContext:
    """Tests for load_ssl_context."""

    def test_returns_none_ssl_context_when_no_args_and_tls_disabled(
        self,
    ) -> None:
        """Should return None ssl_context when no files given and TLS disabled."""
        _del_env(*TLS_ENV_KEYS)

        result = load_ssl_context()

        assert result["ssl_context"] is None
        assert result["cert_file"] is None
        assert result["key_file"] is None
        assert result["ca_file"] is None
        assert result["verify_client"] is False

    def test_returns_ssl_context_from_explicit_args(self) -> None:
        """Should create SSL context from explicitly provided cert/key files."""
        _del_env(*TLS_ENV_KEYS)

        mock_ctx = MagicMock(spec=ssl.SSLContext)

        with patch(
            "mahavishnu.websocket.tls_config.create_ssl_context",
            return_value=mock_ctx,
        ):
            result = load_ssl_context(
                cert_file="/certs/cert.pem",
                key_file="/certs/key.pem",
            )

        assert result["ssl_context"] is mock_ctx
        assert result["cert_file"] == "/certs/cert.pem"
        assert result["key_file"] == "/certs/key.pem"
        assert result["ca_file"] is None
        assert result["verify_client"] is False

    def test_falls_back_to_env_when_no_args_and_tls_enabled(self) -> None:
        """Should read from env vars when no explicit args and TLS is enabled."""
        _del_env(*TLS_ENV_KEYS)
        _set_env("MAHAVISHNU_WS_TLS_ENABLED", "true")
        _set_env("MAHAVISHNU_WS_CERT_FILE", "/env/cert.pem")
        _set_env("MAHAVISHNU_WS_KEY_FILE", "/env/key.pem")
        _set_env("MAHAVISHNU_WS_CA_FILE", "/env/ca.pem")
        _set_env("MAHAVISHNU_WS_VERIFY_CLIENT", "true")

        mock_ctx = MagicMock(spec=ssl.SSLContext)

        with patch(
            "mahavishnu.websocket.tls_config.create_ssl_context",
            return_value=mock_ctx,
        ):
            result = load_ssl_context()

        assert result["ssl_context"] is mock_ctx
        assert result["cert_file"] == "/env/cert.pem"
        assert result["key_file"] == "/env/key.pem"
        assert result["ca_file"] == "/env/ca.pem"
        assert result["verify_client"] is True

    def test_explicit_args_take_precedence_over_env(self) -> None:
        """Explicit cert/key should override env vars."""
        _del_env(*TLS_ENV_KEYS)
        _set_env("MAHAVISHNU_WS_TLS_ENABLED", "true")
        _set_env("MAHAVISHNU_WS_CERT_FILE", "/env/cert.pem")
        _set_env("MAHAVISHNU_WS_KEY_FILE", "/env/key.pem")

        mock_ctx = MagicMock(spec=ssl.SSLContext)

        with patch(
            "mahavishnu.websocket.tls_config.create_ssl_context",
            return_value=mock_ctx,
        ):
            result = load_ssl_context(
                cert_file="/explicit/cert.pem",
                key_file="/explicit/key.pem",
            )

        assert result["ssl_context"] is mock_ctx
        assert result["cert_file"] == "/explicit/cert.pem"
        assert result["key_file"] == "/explicit/key.pem"

    def test_raises_on_create_ssl_context_failure(self) -> None:
        """Should re-raise exceptions from create_ssl_context."""
        _del_env(*TLS_ENV_KEYS)

        with patch(
            "mahavishnu.websocket.tls_config.create_ssl_context",
            side_effect=FileNotFoundError("cert not found"),
        ), pytest.raises(FileNotFoundError, match="cert not found"):
            load_ssl_context(
                cert_file="/missing/cert.pem",
                key_file="/missing/key.pem",
            )

    def test_raises_ssl_error_from_create_ssl_context(self) -> None:
        """Should re-raise SSLError from create_ssl_context."""
        _del_env(*TLS_ENV_KEYS)

        with patch(
            "mahavishnu.websocket.tls_config.create_ssl_context",
            side_effect=ssl.SSLError("bad cipher"),
        ), pytest.raises(ssl.SSLError, match="bad cipher"):
            load_ssl_context(
                cert_file="/bad/cert.pem",
                key_file="/bad/key.pem",
            )

    def test_does_not_call_create_ssl_context_when_tls_disabled_in_env(
        self,
    ) -> None:
        """When TLS is disabled in env and no explicit args, skip context creation."""
        _del_env(*TLS_ENV_KEYS)
        _set_env("MAHAVISHNU_WS_TLS_ENABLED", "false")

        with patch(
            "mahavishnu.websocket.tls_config.create_ssl_context"
        ) as mock_create:
            result = load_ssl_context()

        mock_create.assert_not_called()
        assert result["ssl_context"] is None

    def test_verify_client_passed_through(self) -> None:
        """verify_client flag should be forwarded to create_ssl_context."""
        _del_env(*TLS_ENV_KEYS)

        mock_ctx = MagicMock(spec=ssl.SSLContext)

        with patch(
            "mahavishnu.websocket.tls_config.create_ssl_context",
            return_value=mock_ctx,
        ) as mock_create:
            load_ssl_context(
                cert_file="/c.pem",
                key_file="/k.pem",
                ca_file="/ca.pem",
                verify_client=True,
            )

        mock_create.assert_called_once_with(
            cert_file="/c.pem",
            key_file="/k.pem",
            ca_file="/ca.pem",
            verify_client=True,
        )

    def test_returns_ca_file_when_provided(self) -> None:
        """CA file should be included in the result dict."""
        _del_env(*TLS_ENV_KEYS)

        mock_ctx = MagicMock(spec=ssl.SSLContext)

        with patch(
            "mahavishnu.websocket.tls_config.create_ssl_context",
            return_value=mock_ctx,
        ):
            result = load_ssl_context(
                cert_file="/c.pem",
                key_file="/k.pem",
                ca_file="/ca.pem",
            )

        assert result["ca_file"] == "/ca.pem"

    def test_env_fallback_keeps_none_ssl_context_when_tls_enabled_but_no_certs(
        self,
    ) -> None:
        """When TLS enabled in env but cert/key are None, ssl_context stays None."""
        _del_env(*TLS_ENV_KEYS)
        _set_env("MAHAVISHNU_WS_TLS_ENABLED", "true")
        # cert and key files are not set, so they will be None

        with patch(
            "mahavishnu.websocket.tls_config.create_ssl_context"
        ) as mock_create:
            result = load_ssl_context()

        # create_ssl_context should not be called because cert_file and key_file
        # are both None after reading from env
        mock_create.assert_not_called()
        assert result["ssl_context"] is None

    def test_only_cert_file_without_key_skips_ssl_context(self) -> None:
        """Providing only cert_file (no key_file) should skip SSL context creation."""
        _del_env(*TLS_ENV_KEYS)

        with patch(
            "mahavishnu.websocket.tls_config.create_ssl_context"
        ) as mock_create:
            result = load_ssl_context(cert_file="/c.pem")

        mock_create.assert_not_called()
        assert result["ssl_context"] is None
        assert result["cert_file"] == "/c.pem"

    def test_only_key_file_without_cert_skips_ssl_context(self) -> None:
        """Providing only key_file (no cert_file) should skip SSL context creation."""
        _del_env(*TLS_ENV_KEYS)

        with patch(
            "mahavishnu.websocket.tls_config.create_ssl_context"
        ) as mock_create:
            result = load_ssl_context(key_file="/k.pem")

        mock_create.assert_not_called()
        assert result["ssl_context"] is None
        assert result["key_file"] == "/k.pem"

    def test_result_dict_keys(self) -> None:
        """Result dict should contain exactly the expected keys."""
        _del_env(*TLS_ENV_KEYS)

        result = load_ssl_context()

        expected_keys = {
            "ssl_context",
            "cert_file",
            "key_file",
            "ca_file",
            "verify_client",
        }
        assert set(result.keys()) == expected_keys

    def test_env_verify_client_defaults_to_false(self) -> None:
        """When TLS enabled via env but VERIFY_CLIENT is not set, defaults to False."""
        _del_env(*TLS_ENV_KEYS)
        _set_env("MAHAVISHNU_WS_TLS_ENABLED", "true")
        _set_env("MAHAVISHNU_WS_CERT_FILE", "/c.pem")
        _set_env("MAHAVISHNU_WS_KEY_FILE", "/k.pem")

        mock_ctx = MagicMock(spec=ssl.SSLContext)

        with patch(
            "mahavishnu.websocket.tls_config.create_ssl_context",
            return_value=mock_ctx,
        ) as mock_create:
            result = load_ssl_context()

        # verify_client should default to False from env
        mock_create.assert_called_once_with(
            cert_file="/c.pem",
            key_file="/k.pem",
            ca_file=None,
            verify_client=False,
        )
        assert result["verify_client"] is False

    def test_logs_error_on_ssl_context_failure(self) -> None:
        """Should log an error message when SSL context creation fails."""
        _del_env(*TLS_ENV_KEYS)

        with patch(
            "mahavishnu.websocket.tls_config.create_ssl_context",
            side_effect=OSError("disk error"),
        ), patch("mahavishnu.websocket.tls_config.logger") as mock_logger:
            with pytest.raises(OSError, match="disk error"):
                load_ssl_context(
                    cert_file="/c.pem",
                    key_file="/k.pem",
                )

        mock_logger.error.assert_called_once()
        assert "Failed to load SSL context" in mock_logger.error.call_args[0][0]

    def test_logs_info_on_successful_ssl_load(self) -> None:
        """Should log info when SSL context is loaded successfully."""
        _del_env(*TLS_ENV_KEYS)

        mock_ctx = MagicMock(spec=ssl.SSLContext)

        with patch(
            "mahavishnu.websocket.tls_config.create_ssl_context",
            return_value=mock_ctx,
        ), patch("mahavishnu.websocket.tls_config.logger") as mock_logger:
            load_ssl_context(
                cert_file="/c.pem",
                key_file="/k.pem",
            )

        mock_logger.info.assert_called_once()
        assert "Loaded TLS certificate" in mock_logger.info.call_args[0][0]


# ---------------------------------------------------------------------------
# get_tls_cli_options
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestGetTlsCliOptions:
    """Tests for get_tls_cli_options."""

    def test_returns_all_expected_keys(self) -> None:
        """Should return dict with all expected keys."""
        _del_env(*TLS_ENV_KEYS)

        result = get_tls_cli_options()

        expected_keys = {
            "tls_enabled",
            "cert_file",
            "key_file",
            "ca_file",
            "verify_client",
        }
        assert set(result.keys()) == expected_keys

    def test_defaults_to_tls_disabled(self) -> None:
        """All options should reflect disabled TLS when env vars are unset."""
        _del_env(*TLS_ENV_KEYS)

        result = get_tls_cli_options()

        assert result["tls_enabled"] is False
        assert result["cert_file"] is None
        assert result["key_file"] is None
        assert result["ca_file"] is None
        assert result["verify_client"] is False

    def test_reads_tls_enabled_from_env(self) -> None:
        """tls_enabled option should reflect env var."""
        _del_env(*TLS_ENV_KEYS)
        _set_env("MAHAVISHNU_WS_TLS_ENABLED", "true")

        result = get_tls_cli_options()

        assert result["tls_enabled"] is True

    def test_reads_cert_file_from_env(self) -> None:
        """cert_file option should reflect env var."""
        _del_env(*TLS_ENV_KEYS)
        _set_env("MAHAVISHNU_WS_CERT_FILE", "/opt/certs/cert.pem")

        result = get_tls_cli_options()

        assert result["cert_file"] == "/opt/certs/cert.pem"

    def test_reads_key_file_from_env(self) -> None:
        """key_file option should reflect env var."""
        _del_env(*TLS_ENV_KEYS)
        _set_env("MAHAVISHNU_WS_KEY_FILE", "/opt/certs/key.pem")

        result = get_tls_cli_options()

        assert result["key_file"] == "/opt/certs/key.pem"

    def test_reads_ca_file_from_env(self) -> None:
        """ca_file option should reflect env var."""
        _del_env(*TLS_ENV_KEYS)
        _set_env("MAHAVISHNU_WS_CA_FILE", "/opt/certs/ca.pem")

        result = get_tls_cli_options()

        assert result["ca_file"] == "/opt/certs/ca.pem"

    def test_reads_verify_client_from_env(self) -> None:
        """verify_client option should reflect env var."""
        _del_env(*TLS_ENV_KEYS)
        _set_env("MAHAVISHNU_WS_VERIFY_CLIENT", "true")

        result = get_tls_cli_options()

        assert result["verify_client"] is True

    def test_delegates_to_get_websocket_tls_config(self) -> None:
        """Should delegate to get_websocket_tls_config."""
        _del_env(*TLS_ENV_KEYS)

        with patch(
            "mahavishnu.websocket.tls_config.get_websocket_tls_config"
        ) as mock_config:
            mock_config.return_value = {
                "tls_enabled": True,
                "cert_file": "/c.pem",
                "key_file": "/k.pem",
                "ca_file": "/ca.pem",
                "verify_client": True,
            }
            result = get_tls_cli_options()

        assert result["tls_enabled"] is True
        assert result["cert_file"] == "/c.pem"
        assert result["key_file"] == "/k.pem"
        assert result["ca_file"] == "/ca.pem"
        assert result["verify_client"] is True
