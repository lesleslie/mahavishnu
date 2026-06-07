"""Unit tests for mahavishnu/websocket/tls_config.py.

Covers the three thin wrappers around mcp_common.websocket.tls:
get_websocket_tls_config, load_ssl_context, and get_tls_cli_options.
Environment variables are monkey-patched so tests stay hermetic and
mcp_common.websocket.tls is mocked to avoid touching the real SSL stack.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from mahavishnu.websocket import tls_config as tls_module
from mahavishnu.websocket.tls_config import (
    get_tls_cli_options,
    get_websocket_tls_config,
    load_ssl_context,
)

# =============================================================================
# get_websocket_tls_config Tests
# =============================================================================


class TestGetWebsocketTlsConfig:
    """Tests for get_websocket_tls_config()."""

    def test_delegates_to_mcp_common_with_mahavishnu_prefix(self):
        """The wrapper passes the MAHAVISHNU_WS_ prefix to mcp_common."""
        sentinel = {
            "tls_enabled": False,
            "cert_file": None,
            "key_file": None,
            "ca_file": None,
            "verify_client": False,
        }
        with patch.object(tls_module, "get_tls_config_from_env", return_value=sentinel) as get_cfg:
            result = get_websocket_tls_config()

        get_cfg.assert_called_once_with("MAHAVISHNU_WS")
        assert result is sentinel

    def test_returns_dict_from_env(self):
        """The returned value is whatever mcp_common reports."""
        expected = {
            "tls_enabled": True,
            "cert_file": "/etc/cert.pem",
            "key_file": "/etc/key.pem",
            "ca_file": None,
            "verify_client": True,
        }
        with patch.object(tls_module, "get_tls_config_from_env", return_value=expected):
            result = get_websocket_tls_config()

        assert result == expected


# =============================================================================
# load_ssl_context Tests
# =============================================================================


class TestLoadSslContext:
    """Tests for load_ssl_context()."""

    def test_no_files_consults_env(self):
        """With no cert/key files, env config is consulted."""
        env_config = {
            "tls_enabled": True,
            "cert_file": "/env/cert.pem",
            "key_file": "/env/key.pem",
            "ca_file": None,
            "verify_client": False,
        }
        fake_ssl = MagicMock(name="ssl_context")

        with (
            patch.object(tls_module, "get_tls_config_from_env", return_value=env_config) as get_env,
            patch.object(tls_module, "create_ssl_context", return_value=fake_ssl) as create,
        ):
            result = load_ssl_context()

        get_env.assert_called_once_with("MAHAVISHNU_WS")
        create.assert_called_once_with(
            cert_file="/env/cert.pem",
            key_file="/env/key.pem",
            ca_file=None,
            verify_client=False,
        )
        assert result["ssl_context"] is fake_ssl
        assert result["cert_file"] == "/env/cert.pem"
        assert result["key_file"] == "/env/key.pem"

    def test_no_files_and_tls_disabled_returns_none(self):
        """Env reports tls_enabled=False - no SSL context is created."""
        env_config = {
            "tls_enabled": False,
            "cert_file": None,
            "key_file": None,
            "ca_file": None,
            "verify_client": False,
        }
        with (
            patch.object(tls_module, "get_tls_config_from_env", return_value=env_config) as get_env,
            patch.object(tls_module, "create_ssl_context") as create,
        ):
            result = load_ssl_context()

        get_env.assert_called_once()
        create.assert_not_called()
        assert result["ssl_context"] is None

    def test_explicit_cert_and_key_creates_context(self):
        """Explicit cert/key file paths produce an SSL context."""
        fake_ssl = MagicMock(name="ssl_context")

        with patch.object(tls_module, "create_ssl_context", return_value=fake_ssl) as create:
            result = load_ssl_context(
                cert_file="/x/cert.pem",
                key_file="/x/key.pem",
                ca_file="/x/ca.pem",
                verify_client=True,
            )

        create.assert_called_once_with(
            cert_file="/x/cert.pem",
            key_file="/x/key.pem",
            ca_file="/x/ca.pem",
            verify_client=True,
        )
        assert result["ssl_context"] is fake_ssl
        assert result["cert_file"] == "/x/cert.pem"
        assert result["key_file"] == "/x/key.pem"
        assert result["ca_file"] == "/x/ca.pem"
        assert result["verify_client"] is True

    def test_only_cert_file_provided_skips_context_creation(self):
        """If only cert_file is given (no key_file) no SSL context is built."""
        with patch.object(tls_module, "create_ssl_context") as create:
            result = load_ssl_context(cert_file="/x/cert.pem")

        create.assert_not_called()
        assert result["ssl_context"] is None
        assert result["cert_file"] == "/x/cert.pem"
        assert result["key_file"] is None

    def test_only_key_file_provided_skips_context_creation(self):
        """If only key_file is given (no cert_file) no SSL context is built."""
        with patch.object(tls_module, "create_ssl_context") as create:
            result = load_ssl_context(key_file="/x/key.pem")

        create.assert_not_called()
        assert result["ssl_context"] is None

    def test_explicit_args_override_env(self):
        """If explicit cert/key are given, env config is ignored."""
        fake_ssl = MagicMock(name="ssl_context")

        with (
            patch.object(tls_module, "get_tls_config_from_env") as get_env,
            patch.object(tls_module, "create_ssl_context", return_value=fake_ssl),
        ):
            result = load_ssl_context(
                cert_file="/explicit/cert.pem",
                key_file="/explicit/key.pem",
            )

        get_env.assert_not_called()
        assert result["ssl_context"] is fake_ssl
        assert result["cert_file"] == "/explicit/cert.pem"
        assert result["key_file"] == "/explicit/key.pem"

    def test_create_ssl_context_failure_propagates(self):
        """Errors from create_ssl_context bubble up to the caller."""
        with (
            patch.object(
                tls_module,
                "create_ssl_context",
                side_effect=RuntimeError("bad cert"),
            ),
            pytest.raises(RuntimeError, match="bad cert"),
        ):
            load_ssl_context(
                cert_file="/x/cert.pem",
                key_file="/x/key.pem",
            )

    def test_returns_full_metadata_dict(self):
        """The returned dict always has the five documented keys."""
        fake_ssl = MagicMock(name="ssl_context")

        with patch.object(tls_module, "create_ssl_context", return_value=fake_ssl):
            result = load_ssl_context(
                cert_file="/x/cert.pem",
                key_file="/x/key.pem",
                ca_file=None,
                verify_client=False,
            )

        assert set(result.keys()) == {
            "ssl_context",
            "cert_file",
            "key_file",
            "ca_file",
            "verify_client",
        }

    def test_env_verify_client_default_is_false(self):
        """When env verify_client is absent, default is False."""
        env_config = {
            "tls_enabled": True,
            "cert_file": "/env/cert.pem",
            "key_file": "/env/key.pem",
            "ca_file": None,
            # no 'verify_client' key
        }
        fake_ssl = MagicMock(name="ssl_context")

        with (
            patch.object(tls_module, "get_tls_config_from_env", return_value=env_config),
            patch.object(tls_module, "create_ssl_context", return_value=fake_ssl) as create,
        ):
            load_ssl_context()

        # verify_client defaulted to False
        assert create.call_args.kwargs["verify_client"] is False


# =============================================================================
# get_tls_cli_options Tests
# =============================================================================


class TestGetTlsCliOptions:
    """Tests for get_tls_cli_options()."""

    def test_returns_dict_with_all_keys(self):
        """Returned dict has the five CLI option keys."""
        env_config = {
            "tls_enabled": True,
            "cert_file": "/x/cert.pem",
            "key_file": "/x/key.pem",
            "ca_file": "/x/ca.pem",
            "verify_client": True,
        }
        with patch.object(tls_module, "get_tls_config_from_env", return_value=env_config):
            options = get_tls_cli_options()

        assert set(options.keys()) == {
            "tls_enabled",
            "cert_file",
            "key_file",
            "ca_file",
            "verify_client",
        }

    def test_passes_env_values_through(self):
        """Each env value is mirrored into the CLI options dict."""
        env_config = {
            "tls_enabled": True,
            "cert_file": "/x/cert.pem",
            "key_file": "/x/key.pem",
            "ca_file": "/x/ca.pem",
            "verify_client": True,
        }
        with patch.object(tls_module, "get_tls_config_from_env", return_value=env_config):
            options = get_tls_cli_options()

        assert options["tls_enabled"] is True
        assert options["cert_file"] == "/x/cert.pem"
        assert options["key_file"] == "/x/key.pem"
        assert options["ca_file"] == "/x/ca.pem"
        assert options["verify_client"] is True

    def test_verify_client_defaults_to_false_when_missing(self):
        """If env config has no verify_client key, default to False."""
        env_config = {
            "tls_enabled": False,
            "cert_file": None,
            "key_file": None,
            "ca_file": None,
            # no verify_client
        }
        with patch.object(tls_module, "get_tls_config_from_env", return_value=env_config):
            options = get_tls_cli_options()

        assert options["verify_client"] is False

    def test_all_values_passed_through_unchanged(self):
        """Each value passes through verbatim - no normalization."""
        env_config = {
            "tls_enabled": False,
            "cert_file": None,
            "key_file": None,
            "ca_file": None,
            "verify_client": False,
        }
        with patch.object(tls_module, "get_tls_config_from_env", return_value=env_config):
            options = get_tls_cli_options()

        assert options == env_config


# =============================================================================
# Integration-style Smoke Test
# =============================================================================


class TestTlsConfigSmoke:
    """Cross-function smoke tests to ensure wrappers don't break each other."""

    def test_load_ssl_context_uses_get_websocket_tls_config(self):
        """When no explicit args are given, the public get_* helper is called."""
        env_config = {
            "tls_enabled": True,
            "cert_file": "/x/cert.pem",
            "key_file": "/x/key.pem",
            "ca_file": None,
            "verify_client": False,
        }
        fake_ssl = MagicMock(name="ssl_context")

        with (
            patch.object(tls_module, "get_tls_config_from_env", return_value=env_config) as get_env,
            patch.object(tls_module, "create_ssl_context", return_value=fake_ssl),
        ):
            load_ssl_context()

        # Same env-var prefix as the public helper
        get_env.assert_called_once_with("MAHAVISHNU_WS")

    @pytest.mark.parametrize("tls_enabled", [True, False])
    def test_cli_options_reflect_env_toggle(self, tls_enabled):
        """CLI options include the env-controlled tls_enabled flag."""
        env_config = {
            "tls_enabled": tls_enabled,
            "cert_file": None,
            "key_file": None,
            "ca_file": None,
            "verify_client": False,
        }
        with patch.object(tls_module, "get_tls_config_from_env", return_value=env_config):
            options = get_tls_cli_options()

        assert options["tls_enabled"] is tls_enabled
