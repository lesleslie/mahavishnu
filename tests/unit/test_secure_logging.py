"""Unit tests for secure logging with credential redaction."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from mahavishnu.core.secure_logging import (
    CredentialPatterns,
    CredentialRedactor,
    CredentialType,
    SecureLogger,
    get_secure_logger,
    redact_credentials,
    redact_dict,
)


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def redactor():
    """Create credential redactor for testing."""
    return CredentialRedactor(redaction_string="***REDACTED***")


@pytest.fixture
def secure_logger():
    """Create secure logger for testing."""
    return SecureLogger("test_logger", log_path=None)


# =============================================================================
# SSH KEY REDACTION TESTS
# =============================================================================


class TestSSHKeyRedaction:
    """Test SSH key redaction."""

    def test_redact_ssh_rsa_private_key(self, redactor):
        """Test redaction of RSA private key."""
        private_key = """-----BEGIN RSA PRIVATE KEY-----
MIIEpAIBAAKCAQEAyKf7KnNzRJEVmNFgN3fTY8N2Zv7dDx+vYKL8mWfwZ5J7hL
[... rest of key ...]
-----END RSA PRIVATE KEY-----"""

        redacted = redactor.redact_string(private_key)

        assert "-----BEGIN" not in redacted
        assert "PRIVATE KEY" not in redacted
        assert "***REDACTED***" in redacted
        assert "MIIEpAIBAAKCAQEA" not in redacted

    def test_redact_ssh_ed25519_private_key(self, redactor):
        """Test redaction of Ed25519 private key."""
        private_key = """-----BEGIN OPENSSH PRIVATE KEY-----
b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAABAAAAMwAAAAtzc
[... rest of key ...]
-----END OPENSSH PRIVATE KEY-----"""

        redacted = redactor.redact_string(private_key)

        assert "-----BEGIN" not in redacted
        assert "OPENSSH PRIVATE KEY" not in redacted
        assert "***REDACTED***" in redacted
        assert "b3BlbnNzaC1rZXktdjE" not in redacted

    def test_redact_ssh_public_key_rsa(self, redactor):
        """Test redaction of SSH public key (RSA)."""
        public_key = "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQC user@host"

        redacted = redactor.redact_string(public_key)

        assert "AAAAB3NzaC1yc2EAAAADAQABAAABAQC" not in redacted
        assert "[REDACTED:SSH_PUBLIC_KEY]" in redacted
        assert "user@host" not in redacted

    def test_redact_ssh_public_key_ed25519(self, redactor):
        """Test redaction of SSH public key (Ed25519)."""
        public_key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMQlk user@host"

        redacted = redactor.redact_string(public_key)

        assert "AAAAC3NzaC1lZDI1NTE5AAAAIOMQlk" not in redacted
        assert "[REDACTED:SSH_PUBLIC_KEY]" in redacted

    def test_preserve_safe_ssh_text(self, redactor):
        """Test that safe SSH-related text is preserved."""
        safe_text = "SSH connection established to host.example.com"

        redacted = redactor.redact_string(safe_text)

        assert redacted == safe_text


# =============================================================================
# API KEY REDACTION TESTS
# =============================================================================


class TestAPIKeyRedaction:
    """Test API key redaction."""

    def test_redact_stripe_api_key(self, redactor):
        """Test redaction of Stripe API key."""
        api_key = "sk_test_51TestingCredentialsOnly1234567"

        redacted = redactor.redact_string(api_key)

        assert "sk_test_51TestingCredentialsOnly1234567" not in redacted
        assert "[REDACTED:API_KEY]" in redacted or "***REDACTED***" in redacted

    def test_redact_aws_access_key(self, redactor):
        """Test redaction of AWS access key."""
        aws_key = "AKIAIOSFODNN7EXAMPLE"

        redacted = redactor.redact_string(aws_key)

        assert "AKIAIOSFODNN7EXAMPLE" not in redacted
        assert "[REDACTED:API_KEY]" in redacted or "***REDACTED***" in redacted

    def test_redact_github_token(self, redactor):
        """Test redaction of GitHub personal access token."""
        github_token = "ghp_1234567890abcdefghijklmnopqrstuvwxy"

        redacted = redactor.redact_string(github_token)

        assert "ghp_1234567890abcdefghijklmnopqrstuvwxy" not in redacted
        assert "[REDACTED:API_KEY]" in redacted or "***REDACTED***" in redacted

    def test_redact_api_key_in_dict(self, redactor):
        """Test redaction of API key in dictionary."""
        data = {
            "username": "testuser",
            "api_key": "sk_test_51TestingCredentialsOnly1234567",
            "endpoint": "https://api.example.com",
        }

        redacted = redactor.redact_dict(data)

        assert redacted["username"] == "testuser"
        assert redacted["endpoint"] == "https://api.example.com"
        assert "sk_test_51TestingCredentialsOnly1234567" not in str(redacted)
        assert "REDACTED" in str(redacted["api_key"])


# =============================================================================
# PASSWORD REDACTION TESTS
# =============================================================================


class TestPasswordRedaction:
    """Test password redaction."""

    def test_redact_password_in_dict(self, redactor):
        """Test redaction of password in dictionary."""
        data = {
            "username": "testuser",
            "password": "SuperSecret123!",
            "database": "mydb",
        }

        redacted = redactor.redact_dict(data)

        assert redacted["username"] == "testuser"
        assert redacted["database"] == "mydb"
        assert "SuperSecret123!" not in str(redacted)
        assert "***REDACTED***" in str(redacted["password"])

    def test_redact_multiple_password_fields(self, redactor):
        """Test redaction of multiple password-like fields."""
        data = {
            "password": "pass1",
            "passwd": "pass2",
            "pass": "pass3",
            "user_password": "pass4",
            "db_password": "pass5",
        }

        redacted = redactor.redact_dict(data)

        # All password fields should be redacted
        for key, value in redacted.items():
            assert value != f"pass{key[-1]}"  # Original password not present
            assert "REDACTED" in str(value)


# =============================================================================
# TOKEN REDACTION TESTS
# =============================================================================


class TestTokenRedaction:
    """Test token redaction."""

    def test_redact_bearer_token(self, redactor):
        """Test redaction of bearer token."""
        auth_header = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"

        redacted = redactor.redact_string(auth_header)

        assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in redacted
        assert "[REDACTED:BEARER_TOKEN]" in redacted or "***REDACTED***" in redacted

    def test_redact_session_token(self, redactor):
        """Test redaction of session token."""
        data = {
            "session_id": "abc123def456ghi789jkl012mno345pqr",
            "user": "testuser",
        }

        redacted = redactor.redact_dict(data)

        assert "abc123def456ghi789jkl012mno345pqr" not in str(redacted)
        assert "REDACTED" in str(redacted["session_id"])


# =============================================================================
# DATABASE URL REDACTION TESTS
# =============================================================================


class TestDatabaseURLRedaction:
    """Test database URL redaction."""

    def test_redact_postgresql_url(self, redactor):
        """Test redaction of PostgreSQL connection URL."""
        db_url = "postgresql://user:secretPassword@localhost:5432/mydb"

        redacted = redactor.redact_string(db_url)

        assert "secretPassword" not in redacted
        assert "[REDACTED:DATABASE_URL]" in redacted or "***REDACTED***" in redacted

    def test_redact_mysql_url(self, redactor):
        """Test redaction of MySQL connection URL."""
        db_url = "mysql://admin:P@ssw0rd!@db.example.com:3306/prod"

        redacted = redactor.redact_string(db_url)

        assert "P@ssw0rd!" not in redacted
        assert "[REDACTED:DATABASE_URL]" in redacted or "***REDACTED***" in redacted

    def test_redact_connection_string(self, redactor):
        """Test redaction of connection string."""
        conn_str = "Server=localhost;Database=mydb;User Id=admin;Password=secret123;"

        redacted = redactor.redact_string(conn_str)

        assert "secret123" not in redacted
        assert "[REDACTED:CONNECTION_STRING]" in redacted or "***REDACTED***" in redacted


# =============================================================================
# CERTIFICATE REDACTION TESTS
# =============================================================================


class TestCertificateRedaction:
    """Test certificate redaction."""

    def test_redact_x509_certificate(self, redactor):
        """Test redaction of X.509 certificate."""
        cert = """-----BEGIN CERTIFICATE-----
MIIDXTCCAkWgAwIBAgIJAKL0UG+mRKqzMA0GCSqGSIb3DQEBCwUAMEUxCzAJBgNV
[... rest of cert ...]
-----END CERTIFICATE-----"""

        redacted = redactor.redact_string(cert)

        assert "-----BEGIN" not in redacted
        assert "CERTIFICATE" not in redacted
        assert "***REDACTED***" in redacted
        assert "MIIDXTCCAkWgAwIBAgIJAKL0UG+mRKqzMA0GCSqGSIb3DQEBCwUAMEUxCzAJBgNV" not in redacted


# =============================================================================
# DICT RECURSION TESTS
# =============================================================================


class TestDictRecursion:
    """Test dictionary recursion and nested structures."""

    def test_redact_nested_dict(self, redactor):
        """Test redaction of nested dictionary."""
        data = {
            "level1": {
                "level2": {
                    "password": "secret123",
                    "api_key": "sk_test_key",
                }
            },
            "safe": "value",
        }

        redacted = redactor.redact_dict(data)

        assert redacted["safe"] == "value"
        assert "secret123" not in str(redacted)
        assert "sk_test_key" not in str(redacted)

    def test_redact_list_of_dicts(self, redactor):
        """Test redaction of list containing dictionaries."""
        data = {
            "users": [
                {"username": "user1", "password": "pass1"},
                {"username": "user2", "password": "pass2"},
            ]
        }

        redacted = redactor.redact_dict(data)

        assert "pass1" not in str(redacted)
        assert "pass2" not in str(redacted)
        assert "user1" in str(redacted)
        assert "user2" in str(redacted)


# =============================================================================
# SECURE LOGGER TESTS
# =============================================================================


class TestSecureLogger:
    """Test SecureLogger functionality."""

    def test_secure_logger_logs_to_file(self):
        """Test that secure logger writes to file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "test.log"
            logger = SecureLogger("test", log_path=log_path)

            logger.info("Test message", password="secret123", api_key="sk_test_key")

            # Close logger to flush buffers
            logger.close()

            # Read log file
            with open(log_path, "r") as f:
                log_content = f.read()

            assert "Test message" in log_content
            assert "secret123" not in log_content
            assert "sk_test_key" not in log_content
            assert "REDACTED" in log_content

    def test_secure_logger_preserves_safe_data(self):
        """Test that safe data is preserved in logs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "test.log"
            logger = SecureLogger("test", log_path=log_path)

            logger.info(
                "User logged in",
                username="testuser",
                action="login",
                ip_address="192.168.1.1",
            )

            # Close logger to flush buffers
            logger.close()

            # Read log file
            with open(log_path, "r") as f:
                log_content = f.read()

            assert "testuser" in log_content
            assert "login" in log_content
            assert "192.168.1.1" in log_content


# =============================================================================
# CONVENIENCE FUNCTIONS TESTS
# =============================================================================


class TestConvenienceFunctions:
    """Test convenience functions."""

    def test_redact_credentials_function(self):
        """Test redact_credentials convenience function."""
        text = "API key: sk_test_51TestingCredentialsOnly1234567"

        redacted = redact_credentials(text)

        assert "sk_test_51TestingCredentialsOnly1234567" not in redacted
        assert "REDACTED" in redacted

    def test_redact_dict_function(self):
        """Test redact_dict convenience function."""
        data = {"password": "secret123", "username": "testuser"}

        redacted = redact_dict(data)

        assert redacted["username"] == "testuser"
        assert "secret123" not in str(redacted)
        assert "REDACTED" in str(redacted["password"])

    def test_get_secure_logger_function(self):
        """Test get_secure_logger convenience function."""
        logger = get_secure_logger("test_logger")

        assert isinstance(logger, SecureLogger)
        assert logger.logger.name == "test_logger"
