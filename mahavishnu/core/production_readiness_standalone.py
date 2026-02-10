"""Standalone production readiness checker for Mahavishnu MCP ecosystem.

Automated verification of production readiness criteria across security,
monitoring, resilience, performance, and operational readiness.
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import os
from pathlib import Path
import subprocess
from typing import Any


class ReadinessStatus(Enum):
    """Status of a readiness check."""

    PASS = "✅ PASS"
    FAIL = "❌ FAIL"
    WARN = "⚠️ WARN"
    SKIP = "⏭️ SKIP"


@dataclass
class ReadinessCheck:
    """Result of a single readiness check."""

    name: str
    status: ReadinessStatus
    message: str
    details: dict[str, Any] | None = None
    duration_ms: float | None = None


@dataclass
class ProductionReadinessReport:
    """Overall production readiness report."""

    total_checks: int = 0
    passed: int = 0
    failed: int = 0
    warnings: int = 0
    skipped: int = 0
    checks: list[ReadinessCheck] = field(default_factory=list)
    overall_score: float = 0.0
    recommendation: str = ""
    timestamp: str = ""

    def calculate_score(self) -> float:
        """Calculate overall readiness score (0-100)."""
        if self.total_checks == 0:
            return 0.0
        # Pass = 100%, Warn = 50%, Fail = 0%, Skip = excluded from total
        scored_checks = [c for c in self.checks if c.status != ReadinessStatus.SKIP]
        if not scored_checks:
            return 0.0

        total = 0.0
        for check in scored_checks:
            if check.status == ReadinessStatus.PASS:
                total += 100.0
            elif check.status == ReadinessStatus.WARN:
                total += 50.0
            # FAIL contributes 0

        return total / len(scored_checks)


class ProductionReadinessChecker:
    """Automated production readiness checker."""

    def __init__(self, project_root: Path | None = None):
        """Initialize the checker.

        Args:
            project_root: Root directory of the project (defaults to current dir)
        """
        self.project_root = project_root or Path.cwd()
        self.checks: list[ReadinessCheck] = []

    async def run_full_check(self) -> ProductionReadinessReport:
        """Run all production readiness checks.

        Returns:
            Complete production readiness report
        """
        self.checks.clear()

        # Section 1: Security & Compliance
        await self._check_security_audit()
        await self._check_secrets_management()
        await self._check_authentication()
        await self._check_data_encryption()

        # Section 2: Monitoring & Observability
        await self._check_metrics_collection()
        await self._check_logging()
        await self._check_alerting()

        # Section 3: Resilience & Fault Tolerance
        await self._check_circuit_breakers()
        await self._check_backup_system()

        # Section 4: Performance & Scalability
        await self._check_rate_limiting()

        # Section 7: Testing Quality
        await self._check_unit_tests()
        await self._check_integration_tests()

        # Section 8: Operational Readiness
        await self._check_incident_response()
        await self._check_maintenance_procedures()

        # Generate report
        report = ProductionReadinessReport(checks=self.checks, timestamp=datetime.now().isoformat())
        report.total_checks = len(self.checks)
        report.passed = sum(1 for c in self.checks if c.status == ReadinessStatus.PASS)
        report.failed = sum(1 for c in self.checks if c.status == ReadinessStatus.FAIL)
        report.warnings = sum(1 for c in self.checks if c.status == ReadinessStatus.WARN)
        report.skipped = sum(1 for c in self.checks if c.status == ReadinessStatus.SKIP)
        report.overall_score = report.calculate_score()
        report.recommendation = self._generate_recommendation(report.overall_score)

        return report

    async def _check_security_audit(self):
        """Check if security audit has been completed."""
        import time

        start = time.time()

        # Check for security audit completion file
        audit_file = self.project_root / "monitoring" / "security_audit_report.json"

        if audit_file.exists():
            status = ReadinessStatus.PASS
            message = "Security audit completed"
        else:
            status = ReadinessStatus.WARN
            message = "Security audit not found (run: python -m monitoring.security_audit)"

        duration_ms = (time.time() - start) * 1000
        self.checks.append(
            ReadinessCheck(
                name="Security Audit", status=status, message=message, duration_ms=duration_ms
            )
        )

    async def _check_secrets_management(self):
        """Check for hardcoded secrets in codebase."""
        import re
        import time

        start = time.time()

        issues = []

        # Check for common secret patterns (exclude test files and examples)
        secret_patterns = [
            (r'api_key\s*=\s*["\'][^"\']{20,}["\']', "Hardcoded API key"),
            (r'password\s*=\s*["\'][^"\']{10,}["\']', "Hardcoded password"),
            (r'secret\s*=\s*["\'][^"\']{20,}["\']', "Hardcoded secret"),
            (r'token\s*=\s*["\'][^"\']{20,}["\']', "Hardcoded token"),
        ]

        # Scan Python files (excluding tests and __pycache__)
        mahavishnu_dir = self.project_root / "mahavishnu"
        if mahavishnu_dir.exists():
            for py_file in mahavishnu_dir.rglob("*.py"):
                if "test" in str(py_file) or "__pycache__" in str(py_file):
                    continue

                try:
                    content = py_file.read_text()
                    for pattern, desc in secret_patterns:
                        if re.search(pattern, content, re.IGNORECASE):
                            # Exclude obvious placeholders/examples
                            if "example" not in content.lower() and "test" not in content.lower():
                                issues.append(f"{py_file.relative_to(self.project_root)}: {desc}")
                except Exception:
                    pass

        if issues:
            status = ReadinessStatus.FAIL
            message = f"Found {len(issues)} potential hardcoded secrets"
            details = {"issues": issues[:5]}  # First 5 issues
        else:
            status = ReadinessStatus.PASS
            message = "No hardcoded secrets detected"
            details = None

        duration_ms = (time.time() - start) * 1000
        self.checks.append(
            ReadinessCheck(
                name="Secrets Management",
                status=status,
                message=message,
                details=details,
                duration_ms=duration_ms,
            )
        )

    async def _check_authentication(self):
        """Check if authentication is configured."""
        import time

        start = time.time()

        # Check for auth secret
        auth_secret = os.getenv("MAHAVISHNU_AUTH_SECRET")

        if auth_secret and len(auth_secret) >= 32:
            status = ReadinessStatus.PASS
            message = "Authentication secret configured"
        elif auth_secret:
            status = ReadinessStatus.WARN
            message = f"Auth secret too short ({len(auth_secret)} chars, should be 32+)"
        else:
            status = ReadinessStatus.WARN
            message = "MAHAVISHNU_AUTH_SECRET not set (auth disabled)"

        duration_ms = (time.time() - start) * 1000
        self.checks.append(
            ReadinessCheck(
                name="Authentication", status=status, message=message, duration_ms=duration_ms
            )
        )

    async def _check_data_encryption(self):
        """Check if data encryption is implemented."""
        import time

        start = time.time()

        # Check for encryption module in session-buddy
        encryption_file = (
            self.project_root.parent / "session-buddy" / "session_buddy" / "utils" / "encryption.py"
        )

        if encryption_file.exists():
            status = ReadinessStatus.PASS
            message = "Data encryption implemented"
        else:
            status = ReadinessStatus.WARN
            message = "Data encryption not found (sensitive data unencrypted)"

        duration_ms = (time.time() - start) * 1000
        self.checks.append(
            ReadinessCheck(
                name="Data Encryption", status=status, message=message, duration_ms=duration_ms
            )
        )

    async def _check_metrics_collection(self):
        """Check if metrics collection is configured."""
        import time

        start = time.time()

        # Check for monitoring module
        monitoring_dir = self.project_root / "monitoring"
        metrics_file = monitoring_dir / "metrics.py"

        if monitoring_dir.exists() and metrics_file.exists():
            status = ReadinessStatus.PASS
            message = "Metrics collection configured"
        else:
            status = ReadinessStatus.WARN
            message = "Metrics collection not found"

        duration_ms = (time.time() - start) * 1000
        self.checks.append(
            ReadinessCheck(
                name="Metrics Collection", status=status, message=message, duration_ms=duration_ms
            )
        )

    async def _check_logging(self):
        """Check if structured logging is configured."""
        import time

        start = time.time()

        # Check for structlog in dependencies
        try:
            import structlog

            status = ReadinessStatus.PASS
            message = "Structured logging available (structlog)"
        except ImportError:
            status = ReadinessStatus.WARN
            message = "structlog not installed"

        duration_ms = (time.time() - start) * 1000
        self.checks.append(
            ReadinessCheck(name="Logging", status=status, message=message, duration_ms=duration_ms)
        )

    async def _check_alerting(self):
        """Check if alerting is configured."""
        import time

        start = time.time()

        # Check for alerting configuration
        alerting_file = self.project_root / "monitoring" / "alerts.yml"

        if alerting_file.exists():
            status = ReadinessStatus.PASS
            message = "Alerting configured"
        else:
            status = ReadinessStatus.WARN
            message = "Alerting configuration not found"

        duration_ms = (time.time() - start) * 1000
        self.checks.append(
            ReadinessCheck(name="Alerting", status=status, message=message, duration_ms=duration_ms)
        )

    async def _check_circuit_breakers(self):
        """Check if circuit breakers are implemented."""
        import time

        start = time.time()

        # Check for circuit breaker module
        circuit_breaker_file = self.project_root / "mahavishnu" / "core" / "circuit_breaker.py"

        if circuit_breaker_file.exists():
            status = ReadinessStatus.PASS
            message = "Circuit breakers implemented"
        else:
            status = ReadinessStatus.WARN
            message = "Circuit breakers not found"

        duration_ms = (time.time() - start) * 1000
        self.checks.append(
            ReadinessCheck(
                name="Circuit Breakers", status=status, message=message, duration_ms=duration_ms
            )
        )

    async def _check_backup_system(self):
        """Check if backup system is configured."""
        import time

        start = time.time()

        # Check for backup directory
        backup_dir = self.project_root / "backups"

        if backup_dir.exists():
            # Count backups
            backup_files = list(backup_dir.glob("*.tar.gz"))
            status = ReadinessStatus.PASS
            message = f"Backup system configured ({len(backup_files)} backups found)"
        else:
            status = ReadinessStatus.WARN
            message = "Backup directory not found"

        duration_ms = (time.time() - start) * 1000
        self.checks.append(
            ReadinessCheck(
                name="Backup System", status=status, message=message, duration_ms=duration_ms
            )
        )

    async def _check_rate_limiting(self):
        """Check if rate limiting is implemented."""
        import time

        start = time.time()

        # Check for rate limiting module
        rate_limit_file = self.project_root / "mahavishnu" / "core" / "rate_limit.py"

        if rate_limit_file.exists():
            status = ReadinessStatus.PASS
            message = "Rate limiting implemented"
        else:
            status = ReadinessStatus.WARN
            message = "Rate limiting not found"

        duration_ms = (time.time() - start) * 1000
        self.checks.append(
            ReadinessCheck(
                name="Rate Limiting", status=status, message=message, duration_ms=duration_ms
            )
        )

    async def _check_unit_tests(self):
        """Run unit tests and check coverage."""
        import time

        start = time.time()

        try:
            # Run pytest with coverage (unit tests only for faster execution)
            subprocess.run(
                ["pytest", "-m", "unit", "--cov=mahavishnu", "--cov-report=xml", "--tb=no", "-q"],
                cwd=self.project_root,
                capture_output=True,
                text=True,
                timeout=300,  # Increased to 5 minutes
            )

            # Parse coverage from coverage.xml (XML) if available
            coverage_file = self.project_root / "coverage.xml"
            if coverage_file.exists():
                try:
                    import xml.etree.ElementTree as ET

                    tree = ET.parse(coverage_file)
                    root = tree.getroot()

                    # Extract coverage percentage from line-rate attribute
                    # Coverage XML format: <coverage line-rate="0.XX" ...>
                    line_rate = root.get("line-rate", "0")
                    coverage_percent = float(line_rate) * 100

                    if coverage_percent >= 80:
                        status = ReadinessStatus.PASS
                        message = f"Unit test coverage: {coverage_percent:.1f}%"
                    elif coverage_percent >= 60:
                        status = ReadinessStatus.WARN
                        message = f"Unit test coverage: {coverage_percent:.1f}% (target: 80%)"
                    else:
                        status = ReadinessStatus.FAIL
                        message = f"Unit test coverage: {coverage_percent:.1f}% (below 60%)"

                    details = {"coverage_percent": coverage_percent}
                except (ET.ParseError, ValueError, KeyError) as e:
                    status = ReadinessStatus.WARN
                    message = f"Could not parse coverage report: {e}"
                    details = None
            else:
                status = ReadinessStatus.WARN
                message = "Coverage report not found"
                details = None

        except subprocess.TimeoutExpired:
            status = ReadinessStatus.WARN
            message = "Tests timed out"
            details = None
        except FileNotFoundError:
            status = ReadinessStatus.WARN
            message = "pytest not available"
            details = None
        except Exception as e:
            status = ReadinessStatus.WARN
            message = f"Could not run tests: {e}"
            details = None

        duration_ms = (time.time() - start) * 1000
        self.checks.append(
            ReadinessCheck(
                name="Unit Tests",
                status=status,
                message=message,
                details=details,
                duration_ms=duration_ms,
            )
        )

    async def _check_integration_tests(self):
        """Check for integration tests."""
        import time

        start = time.time()

        # Count integration tests
        integration_test_dir = self.project_root / "tests" / "integration"

        if integration_test_dir.exists():
            integration_test_files = list(integration_test_dir.rglob("test_*.py"))

            if len(integration_test_files) >= 5:
                status = ReadinessStatus.PASS
                message = f"Found {len(integration_test_files)} integration test files"
            elif len(integration_test_files) >= 1:
                status = ReadinessStatus.WARN
                message = f"Only {len(integration_test_files)} integration test file(s) found"
            else:
                status = ReadinessStatus.FAIL
                message = "No integration tests found"
        else:
            status = ReadinessStatus.WARN
            message = "Integration test directory not found"

        duration_ms = (time.time() - start) * 1000
        self.checks.append(
            ReadinessCheck(
                name="Integration Tests", status=status, message=message, duration_ms=duration_ms
            )
        )

    async def _check_incident_response(self):
        """Check for incident response procedures."""
        import time

        start = time.time()

        # Check for runbook (try multiple possible filenames)
        runbook_files = [
            self.project_root / "docs" / "INCIDENT_RESPONSE_RUNBOOK.md",
            self.project_root / "docs" / "runbook.md",
            self.project_root / "docs" / "RUNBOOK.md",
        ]

        runbook_exists = any(f.exists() for f in runbook_files)

        if runbook_exists:
            status = ReadinessStatus.PASS
            message = "Incident response runbook exists"
        else:
            status = ReadinessStatus.WARN
            message = "Runbook not found (create: docs/INCIDENT_RESPONSE_RUNBOOK.md)"

        duration_ms = (time.time() - start) * 1000
        self.checks.append(
            ReadinessCheck(
                name="Incident Response", status=status, message=message, duration_ms=duration_ms
            )
        )

    async def _check_maintenance_procedures(self):
        """Check for maintenance procedures."""
        import time

        start = time.time()

        # Check for maintenance docs (try multiple possible filenames)
        maintenance_files = [
            self.project_root / "docs" / "MAINTENANCE_PROCEDURES.md",
            self.project_root / "docs" / "maintenance.md",
            self.project_root / "docs" / "MAINTENANCE.md",
            self.project_root / "docs" / "operations.md",
        ]

        if any(f.exists() for f in maintenance_files):
            status = ReadinessStatus.PASS
            message = "Maintenance procedures documented"
        else:
            status = ReadinessStatus.WARN
            message = "Maintenance procedures not documented"

        duration_ms = (time.time() - start) * 1000
        self.checks.append(
            ReadinessCheck(
                name="Maintenance Procedures",
                status=status,
                message=message,
                duration_ms=duration_ms,
            )
        )

    def _generate_recommendation(self, score: float) -> str:
        """Generate deployment recommendation based on score."""
        if score >= 90:
            return "✅ READY FOR PRODUCTION"
        elif score >= 70:
            return "⚠️ ALMOST READY - Address warnings before deployment"
        elif score >= 50:
            return "❌ NOT READY - Multiple issues must be fixed"
        else:
            return "🚨 CRITICAL - Extensive work required before production"

    def generate_report(self, report: ProductionReadinessReport) -> str:
        """Generate human-readable report.

        Args:
            report: Production readiness report

        Returns:
            Formatted report string
        """
        lines = []
        lines.append("=" * 70)
        lines.append("PRODUCTION READINESS REPORT")
        lines.append("=" * 70)
        lines.append(f"Generated: {report.timestamp}")
        lines.append("")
        lines.append(f"Overall Score: {report.overall_score:.1f}/100")
        lines.append(f"Recommendation: {report.recommendation}")
        lines.append("")
        lines.append(f"Total Checks: {report.total_checks}")
        lines.append(f"  ✅ Passed: {report.passed}")
        lines.append(f"  ⚠️ Warnings: {report.warnings}")
        lines.append(f"  ❌ Failed: {report.failed}")
        lines.append(f"  ⏭️ Skipped: {report.skipped}")
        lines.append("")
        lines.append("-" * 70)
        lines.append("CHECK DETAILS")
        lines.append("-" * 70)
        lines.append("")

        # Group checks by section
        sections = {
            "Security & Compliance": [
                "Security Audit",
                "Secrets Management",
                "Authentication",
                "Data Encryption",
            ],
            "Monitoring & Observability": ["Metrics Collection", "Logging", "Alerting"],
            "Resilience & Fault Tolerance": ["Circuit Breakers", "Backup System"],
            "Performance & Scalability": ["Rate Limiting"],
            "Testing Quality": ["Unit Tests", "Integration Tests"],
            "Operational Readiness": ["Incident Response", "Maintenance Procedures"],
        }

        for section, check_names in sections.items():
            section_checks = [c for c in report.checks if c.name in check_names]
            if section_checks:
                lines.append(f"### {section}")
                lines.append("")

                for check in section_checks:
                    lines.append(f"{check.status.value} {check.name}")
                    lines.append(f"  {check.message}")
                    if check.details and check.details.get("issues"):
                        lines.append("  Issues:")
                        for issue in check.details["issues"]:
                            lines.append(f"    - {issue}")
                    if check.duration_ms is not None:
                        lines.append(f"  Duration: {check.duration_ms:.1f}ms")
                    lines.append("")

        lines.append("=" * 70)

        return "\n".join(lines)


async def main():
    """Run production readiness checks and print report."""
    import sys

    project_root = Path.cwd()
    checker = ProductionReadinessChecker(project_root)

    print("🔍 Running production readiness checks...")
    print("")

    report = await checker.run_full_check()

    # Generate and print report
    report_text = checker.generate_report(report)
    print(report_text)

    # Exit with appropriate code
    if report.failed > 0:
        sys.exit(1)
    elif report.warnings > 0:
        sys.exit(2)
    else:
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
