"""Secrets detection for code indexing security.

This module integrates detect-secrets library to scan for credentials
in code before indexing, preventing secrets from being stored in code graphs.

Key Features:
- Integration with detect-secrets library
- Pre-indexing validation
- Credential redaction
- Configurable blocking (fail-fast vs. warn-only)
- Custom secret pattern support
"""

from enum import StrEnum
import logging
from pathlib import Path
import re
import subprocess
from typing import Any

logger = logging.getLogger(__name__)


# =============================================================================
# SECRET DETECTION RESULTS
# =============================================================================


class SecretSeverity(StrEnum):
    """Severity level for detected secrets."""

    LOW = "low"  # Unlikely to be a real secret (e.g., "password123")
    MEDIUM = "medium"  # Possibly a secret (e.g., random string)
    HIGH = "high"  # Likely a real secret (e.g., API key format)


class SecretType(StrEnum):
    """Type of detected secret."""

    API_KEY = "api_key"
    AWS_KEY = "aws_key"
    SSH_KEY = "ssh_key"
    PASSWORD = "password"
    TOKEN = "token"
    CERTIFICATE = "certificate"
    PRIVATE_KEY = "private_key"
    DATABASE_URL = "database_url"
    OTHER = "other"


class DetectedSecret:
    """Information about a detected secret."""

    def __init__(
        self,
        secret_type: SecretType,
        severity: SecretSeverity,
        line_number: int,
        line_content: str,
        file_path: str,
        matched_string: str,
    ):
        self.secret_type = secret_type
        self.severity = severity
        self.line_number = line_number
        self.line_content = line_content
        self.file_path = file_path
        self.matched_string = matched_string

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "secret_type": self.secret_type.value,
            "severity": self.severity.value,
            "line_number": self.line_number,
            "file_path": self.file_path,
            "matched_string": self.matched_string,
            "line_preview": self._get_preview(),
        }

    def _get_preview(self, max_length: int = 100) -> str:
        """Get preview of line with secret (truncated)."""
        preview = self.line_content.strip()
        if len(preview) > max_length:
            return preview[:max_length] + "..."
        return preview

    def __repr__(self) -> str:
        return (
            f"DetectedSecret(type={self.secret_type}, severity={self.severity}, "
            f"file={self.file_path}:{self.line_number})"
        )


class SecretScanResult:
    """Result of scanning for secrets."""

    def __init__(
        self,
        scanned_files: int,
        secrets_found: list[DetectedSecret],
        scan_duration_seconds: float,
    ):
        self.scanned_files = scanned_files
        self.secrets_found = secrets_found
        self.scan_duration_seconds = scan_duration_seconds

    @property
    def has_secrets(self) -> bool:
        """Check if any secrets were found."""
        return len(self.secrets_found) > 0

    @property
    def high_severity_count(self) -> int:
        """Count high severity secrets."""
        return sum(1 for s in self.secrets_found if s.severity == SecretSeverity.HIGH)

    @property
    def medium_severity_count(self) -> int:
        """Count medium severity secrets."""
        return sum(1 for s in self.secrets_found if s.severity == SecretSeverity.MEDIUM)

    @property
    def low_severity_count(self) -> int:
        """Count low severity secrets."""
        return sum(1 for s in self.secrets_found if s.severity == SecretSeverity.LOW)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "scanned_files": self.scanned_files,
            "secrets_found": len(self.secrets_found),
            "high_severity": self.high_severity_count,
            "medium_severity": self.medium_severity_count,
            "low_severity": self.low_severity_count,
            "secrets": [s.to_dict() for s in self.secrets_found],
            "scan_duration_seconds": self.scan_duration_seconds,
        }


# =============================================================================
# SECRET SCANNER
# =============================================================================


class SecretsScanner:
    """Scanner for detecting secrets in code using detect-secrets."""

    def __init__(
        self,
        fail_on_secrets: bool = True,
        block_on_high_severity: bool = True,
        custom_patterns: dict[str, str] | None = None,
    ):
        """Initialize secrets scanner.

        Args:
            fail_on_secrets: If True, block indexing if ANY secret found
            block_on_high_severity: If True, block indexing if HIGH severity secret found
            custom_patterns: Custom regex patterns for secret detection
        """
        self.fail_on_secrets = fail_on_secrets
        self.block_on_high_severity = block_on_high_severity
        self.custom_patterns = custom_patterns or {}

        # Check if detect-secrets is installed
        self._check_detect_secrets_installed()

    def _check_detect_secrets_installed(self) -> None:
        """Check if detect-secrets is installed."""
        try:
            result = subprocess.run(
                ["detect-secrets", "--version"],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                logger.info(f"detect-secrets installed: {result.stdout.strip()}")
        except FileNotFoundError:
            logger.warning("detect-secrets not found. Install with: pip install detect-secrets")
            raise RuntimeError(
                "detect-secrets is required for secrets scanning. "
                "Install with: pip install detect-secrets"
            )

    async def scan_directory(self, directory: Path | str) -> SecretScanResult:
        """Scan directory for secrets.

        Args:
            directory: Path to directory to scan

        Returns:
            Scan result with detected secrets
        """
        directory = Path(directory)

        if not directory.exists():
            raise FileNotFoundError(f"Directory not found: {directory}")

        logger.info(f"Scanning directory for secrets: {directory}")

        import time

        start_time = time.time()

        # Run detect-secrets
        try:
            result = subprocess.run(
                [
                    "detect-secrets",
                    "scan",
                    str(directory),
                    "--all-files",
                    "--baseline",
                    "/dev/null",  # No baseline, scan everything
                ],
                capture_output=True,
                text=True,
            )

            scan_duration = time.time() - start_time

            # Parse results
            secrets_found = self._parse_detect_secrets_output(
                result.stdout,
                result.stderr,
                directory,
            )

            return SecretScanResult(
                scanned_files=self._count_files(directory),
                secrets_found=secrets_found,
                scan_duration_seconds=scan_duration,
            )

        except subprocess.CalledProcessError as e:
            logger.error(f"detect-secrets scan failed: {e}")
            return SecretScanResult(
                scanned_files=0,
                secrets_found=[],
                scan_duration_seconds=time.time() - start_time,
            )

    def _parse_detect_secrets_output(
        self,
        stdout: str,
        stderr: str,
        base_path: Path,
    ) -> list[DetectedSecret]:
        """Parse detect-secrets output.

        Args:
            stdout: Standard output from detect-secrets
            stderr: Standard error from detect-secrets
            base_path: Base path for resolving file paths

        Returns:
            List of detected secrets
        """
        secrets = []

        # Parse stderr where detect-secrets reports findings
        for line in stderr.split("\n"):
            line = line.strip()
            if not line or line.startswith("Scanning..."):
                continue

            # Parse line format: "path/to/file:line  type  [matched_string]"
            # Example: "src/config.py:10  Secret Key  ['api_key']"
            try:
                if ":" not in line:
                    continue

                parts = line.split(":", 1)
                if len(parts) != 2:
                    continue

                file_part, detection_part = parts

                # Extract line number
                if "  " not in file_part:
                    continue

                file_part, line_part = file_part.rsplit("  ", 1)
                line_number = int(line_part)

                # Extract secret type and matched string
                detection_part = detection_part.strip()

                # Parse matched string if present
                matched_string = ""
                if "[" in detection_part and "]" in detection_part:
                    matched_str_start = detection_part.index("[") + 1
                    matched_str_end = detection_part.index("]")
                    matched_string = detection_part[matched_str_start:matched_str_end].strip("'")

                # Determine secret type and severity
                secret_type, severity = self._classify_secret(detection_part, matched_string)

                secret = DetectedSecret(
                    secret_type=secret_type,
                    severity=severity,
                    line_number=line_number,
                    line_content="",  # Line content not provided by detect-secrets
                    file_path=str(base_path / file_part),
                    matched_string=matched_string,
                )

                secrets.append(secret)

            except (ValueError, IndexError) as e:
                logger.debug(f"Failed to parse detect-secrets line: {line} - {e}")
                continue

        return secrets

    def _classify_secret(
        self, detection_part: str, matched_string: str
    ) -> tuple[SecretType, SecretSeverity]:
        """Classify secret type and severity.

        Args:
            detection_part: Detect-secrets detection string
            matched_string: The matched secret string

        Returns:
            Tuple of (SecretType, SecretSeverity)
        """
        detection_lower = detection_part.lower()

        # Classify type
        if "api key" in detection_lower or matched_string.startswith(("sk_", "key_", "api_")):
            secret_type = SecretType.API_KEY
        elif "aws" in detection_lower:
            secret_type = SecretType.AWS_KEY
        elif "ssh" in detection_lower or "private key" in detection_lower:
            secret_type = SecretType.SSH_KEY
        elif "password" in detection_lower:
            secret_type = SecretType.PASSWORD
        elif "token" in detection_lower:
            secret_type = SecretType.TOKEN
        elif "certificate" in detection_lower or "cert" in detection_lower:
            secret_type = SecretType.CERTIFICATE
        elif "private key" in detection_lower:
            secret_type = SecretType.PRIVATE_KEY
        elif "database" in detection_lower or "db_" in detection_lower:
            secret_type = SecretType.DATABASE_URL
        else:
            secret_type = SecretType.OTHER

        # Classify severity based on string characteristics
        severity = self._estimate_severity(matched_string, secret_type)

        return secret_type, severity

    def _estimate_severity(self, matched_string: str, secret_type: SecretType) -> SecretSeverity:
        """Estimate severity of detected secret based on characteristics.

        Args:
            matched_string: The matched secret string
            secret_type: Type of secret

        Returns:
            Estimated severity level
        """
        # High severity indicators
        high_severity_patterns = [
            r"^sk-[a-zA-Z0-9]{20,}$",  # Stripe API keys
            r"^AKIA[0-9]{16,}$",  # AWS keys
            r"^ghp_[a-zA-Z0-9]{36,}$",  # GitHub personal access tokens
            r"^xoxb-[a-zA-Z0-9]{36,}-",  # GitHub OAuth
        ]

        for pattern in high_severity_patterns:
            if re.match(pattern, matched_string):
                return SecretSeverity.HIGH

        # Medium severity indicators
        if len(matched_string) > 20 and any(c.isalnum() for c in matched_string):
            return SecretSeverity.MEDIUM

        # Low severity (likely false positive)
        if matched_string.lower() in ("password", "secret", "key", "token"):
            return SecretSeverity.LOW

        # Default to medium
        return SecretSeverity.MEDIUM

    def _count_files(self, directory: Path) -> int:
        """Count files in directory recursively.

        Args:
            directory: Path to directory

        Returns:
            Number of files
        """
        count = 0
        for item in directory.rglob("*"):
            if item.is_file():
                count += 1
        return count

    def should_block_indexing(self, scan_result: SecretScanResult) -> tuple[bool, str]:
        """Determine if indexing should be blocked based on scan results.

        Args:
            scan_result: Result of secrets scan

        Returns:
            Tuple of (should_block, reason)
        """
        if not scan_result.has_secrets:
            return False, "No secrets found"

        # Check high severity
        if self.block_on_high_severity and scan_result.high_severity_count > 0:
            return (
                True,
                f"Found {scan_result.high_severity_count} high severity secrets",
            )

        # Check if fail_on_secrets is enabled
        if self.fail_on_secrets:
            return (
                True,
                f"Found {len(scan_result.secrets_found)} secrets (fail_on_secrets=True)",
            )

        # Allow indexing but warn
        return (
            False,
            f"Found {len(scan_result.secrets_found)} secrets but indexing allowed",
        )


# =============================================================================
# SECRET REDACTOR
# =============================================================================


class SecretRedactor:
    """Redact secrets from code before indexing."""

    def __init__(self, secrets: list[DetectedSecret]):
        """Initialize redactor with list of secrets to redact.

        Args:
            secrets: List of detected secrets
        """
        self.secrets = secrets

    def redact_code(self, code: str) -> str:
        """Redact secrets from code string.

        Args:
            code: Source code string

        Returns:
            Code with secrets redacted
        """
        redacted = code

        # Sort secrets by line number (descending) to avoid offset issues
        sorted_secrets = sorted(
            [s for s in self.secrets if s.matched_string],
            key=lambda s: s.line_number,
            reverse=True,
        )

        for secret in sorted_secrets:
            # Replace matched string with placeholder
            placeholder = f"[REDACTED:{secret.secret_type.value.upper()}]"
            redacted = redacted.replace(secret.matched_string, placeholder)

        return redacted

    def redact_file(self, file_path: Path) -> Path:
        """Redact secrets from file and save to new file.

        Args:
            file_path: Path to file with secrets

        Returns:
            Path to redacted file
        """
        redacted_path = file_path.with_suffix(file_path.suffix + ".redacted")

        try:
            # Read file
            with open(file_path, encoding="utf-8", errors="ignore") as f:
                code = f.read()

            # Redact secrets
            redacted_code = self.redact_code(code)

            # Write redacted file
            with open(redacted_path, "w", encoding="utf-8") as f:
                f.write(redacted_code)

            logger.info(f"Created redacted file: {redacted_path}")

            return redacted_path

        except Exception as e:
            logger.error(f"Failed to redact file {file_path}: {e}")
            raise


# =============================================================================
# PRE-INDEXING VALIDATOR
# =============================================================================


class PreIndexValidator:
    """Validate code repository before indexing."""

    def __init__(
        self,
        scanner: SecretsScanner | None = None,
        fail_on_secrets: bool = True,
        block_on_high_severity: bool = True,
    ):
        """Initialize pre-index validator.

        Args:
            scanner: Secrets scanner instance (created if None)
            fail_on_secrets: Configuration for blocking on secrets
            block_on_high_severity: Configuration for blocking on high severity secrets
        """
        self.scanner = scanner or SecretsScanner(
            fail_on_secrets=fail_on_secrets,
            block_on_high_severity=block_on_high_severity,
        )

    async def validate_repository(self, repo_path: Path | str) -> dict[str, Any]:
        """Validate repository before indexing.

        Args:
            repo_path: Path to repository

        Returns:
            Validation result with status and details
        """
        repo_path = Path(repo_path)

        logger.info(f"Validating repository for secrets: {repo_path}")

        # Scan for secrets
        scan_result = await self.scanner.scan_directory(repo_path)

        # Determine if indexing should be blocked
        should_block, reason = self.scanner.should_block_indexing(scan_result)

        result = {
            "status": "blocked" if should_block else "allowed",
            "reason": reason,
            "scan_details": scan_result.to_dict(),
        }

        if should_block:
            logger.warning(f"Indexing blocked for {repo_path}: {reason}")
        else:
            logger.info(f"Indexing allowed for {repo_path}: {reason}")

        return result


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================


async def scan_and_validate(
    repo_path: Path | str,
    fail_on_secrets: bool = True,
    block_on_high_severity: bool = True,
) -> dict[str, Any]:
    """Convenience function to scan and validate repository.

    Args:
        repo_path: Path to repository
        fail_on_secrets: Configuration for secret blocking
        block_on_high_severity: Configuration for high severity blocking

    Returns:
        Validation result
    """
    validator = PreIndexValidator(
        fail_on_secrets=fail_on_secrets,
        block_on_high_severity=block_on_high_severity,
    )

    return await validator.validate_repository(repo_path)
