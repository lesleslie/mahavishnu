"""Unit tests for core.production_readiness_standalone."""

from __future__ import annotations

from pathlib import Path
import types
import uuid

import pytest

import mahavishnu.core.production_readiness_standalone as prs
from mahavishnu.core.production_readiness_standalone import (
    ProductionReadinessChecker,
    ProductionReadinessReport,
    ReadinessCheck,
    ReadinessStatus,
)


def test_report_calculate_score_and_recommendation_thresholds() -> None:
    report = ProductionReadinessReport(
        checks=[
            ReadinessCheck("a", ReadinessStatus.PASS, "ok"),
            ReadinessCheck("b", ReadinessStatus.WARN, "warn"),
            ReadinessCheck("c", ReadinessStatus.FAIL, "fail"),
            ReadinessCheck("d", ReadinessStatus.SKIP, "skip"),
        ]
    )
    report.total_checks = len(report.checks)
    assert report.calculate_score() == 50.0

    checker = ProductionReadinessChecker(Path("."))
    assert checker._generate_recommendation(95) == "✅ READY FOR PRODUCTION"
    assert "ALMOST READY" in checker._generate_recommendation(75)
    assert "NOT READY" in checker._generate_recommendation(60)
    assert "CRITICAL" in checker._generate_recommendation(10)

    empty_report = ProductionReadinessReport()
    assert empty_report.calculate_score() == 0.0

    skip_only = ProductionReadinessReport(
        checks=[ReadinessCheck("skip", ReadinessStatus.SKIP, "skip")]
    )
    skip_only.total_checks = 1
    assert skip_only.calculate_score() == 0.0


def test_generate_report_formats_sections_and_details() -> None:
    checker = ProductionReadinessChecker(Path("."))
    report = ProductionReadinessReport(
        total_checks=3,
        passed=1,
        failed=1,
        warnings=1,
        skipped=0,
        overall_score=66.6,
        recommendation="x",
        timestamp="2026-04-08T00:00:00",
        checks=[
            ReadinessCheck("Security Audit", ReadinessStatus.PASS, "ok", duration_ms=1.2),
            ReadinessCheck(
                "Secrets Management",
                ReadinessStatus.FAIL,
                "bad",
                details={"issues": ["a", "b"]},
                duration_ms=2.3,
            ),
            ReadinessCheck("Unit Tests", ReadinessStatus.WARN, "meh"),
        ],
    )
    txt = checker.generate_report(report)
    assert "PRODUCTION READINESS REPORT" in txt
    assert "Security & Compliance" in txt
    assert "Testing Quality" in txt
    assert "Issues:" in txt
    assert "Duration:" in txt


@pytest.mark.asyncio
async def test_run_full_check_with_monkeypatched_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    checker = ProductionReadinessChecker(Path("."))

    async def _pass(self) -> None:  # noqa: ANN001
        self.checks.append(ReadinessCheck("x", ReadinessStatus.PASS, "ok"))

    async def _warn(self) -> None:  # noqa: ANN001
        self.checks.append(ReadinessCheck("y", ReadinessStatus.WARN, "warn"))

    async def _fail(self) -> None:  # noqa: ANN001
        self.checks.append(ReadinessCheck("z", ReadinessStatus.FAIL, "fail"))

    names = [
        "_check_security_audit",
        "_check_secrets_management",
        "_check_authentication",
        "_check_data_encryption",
        "_check_metrics_collection",
        "_check_logging",
        "_check_alerting",
        "_check_circuit_breakers",
        "_check_backup_system",
        "_check_rate_limiting",
        "_check_unit_tests",
        "_check_integration_tests",
        "_check_incident_response",
        "_check_maintenance_procedures",
    ]
    funcs = [_pass, _warn, _fail]
    for i, name in enumerate(names):
        monkeypatch.setattr(ProductionReadinessChecker, name, funcs[i % 3], raising=True)

    report = await checker.run_full_check()
    assert report.total_checks == 14
    assert report.passed > 0
    assert report.warnings > 0
    assert report.failed > 0
    assert report.timestamp
    assert report.recommendation


@pytest.mark.asyncio
async def test_filesystem_based_checks_cover_pass_and_warn(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    checker = ProductionReadinessChecker(tmp_path)

    # security audit warn -> pass
    await checker._check_security_audit()
    assert checker.checks[-1].status == ReadinessStatus.WARN
    (tmp_path / "monitoring").mkdir(parents=True, exist_ok=True)
    (tmp_path / "monitoring" / "security_audit_report.json").write_text("{}")
    await checker._check_security_audit()
    assert checker.checks[-1].status == ReadinessStatus.PASS

    # secrets management: use a path without "test" in full path so scan won't skip files
    alt_root = Path(f"/tmp/prs_cov_{uuid.uuid4().hex}")
    alt_root.mkdir(parents=True, exist_ok=True)
    checker_secrets = ProductionReadinessChecker(alt_root)
    src = alt_root / "mahavishnu" / "core"
    src.mkdir(parents=True, exist_ok=True)
    (src / "mod.py").write_text("x = 1\n")
    await checker_secrets._check_secrets_management()
    assert checker_secrets.checks[-1].status == ReadinessStatus.PASS
    (src / "secret.py").write_text("api_key='abcdefghijklmnopqrstuvwxyz123456'\n")
    await checker_secrets._check_secrets_management()
    assert checker_secrets.checks[-1].status == ReadinessStatus.FAIL

    # auth env branches
    monkeypatch.delenv("MAHAVISHNU_AUTH_SECRET", raising=False)
    await checker._check_authentication()
    assert checker.checks[-1].status == ReadinessStatus.WARN
    monkeypatch.setenv("MAHAVISHNU_AUTH_SECRET", "short")
    await checker._check_authentication()
    assert checker.checks[-1].status == ReadinessStatus.WARN
    monkeypatch.setenv("MAHAVISHNU_AUTH_SECRET", "x" * 40)
    await checker._check_authentication()
    assert checker.checks[-1].status == ReadinessStatus.PASS

    # other file presence checks
    await checker._check_data_encryption()
    assert checker.checks[-1].status == ReadinessStatus.WARN
    enc = tmp_path.parent / "session-buddy" / "session_buddy" / "utils"
    enc.mkdir(parents=True, exist_ok=True)
    (enc / "encryption.py").write_text("x=1\n")
    await checker._check_data_encryption()
    assert checker.checks[-1].status == ReadinessStatus.PASS

    (tmp_path / "monitoring" / "metrics.py").write_text("x=1\n")
    await checker._check_metrics_collection()
    assert checker.checks[-1].status == ReadinessStatus.PASS
    await checker._check_alerting()
    assert checker.checks[-1].status == ReadinessStatus.WARN
    (tmp_path / "monitoring" / "alerts.yml").write_text("groups: []\n")
    await checker._check_alerting()
    assert checker.checks[-1].status == ReadinessStatus.PASS

    (tmp_path / "mahavishnu" / "core").mkdir(parents=True, exist_ok=True)
    (tmp_path / "mahavishnu" / "core" / "circuit_breaker.py").write_text("x=1\n")
    (tmp_path / "mahavishnu" / "core" / "rate_limit.py").write_text("x=1\n")
    await checker._check_circuit_breakers()
    assert checker.checks[-1].status == ReadinessStatus.PASS
    await checker._check_rate_limiting()
    assert checker.checks[-1].status == ReadinessStatus.PASS

    await checker._check_backup_system()
    assert checker.checks[-1].status == ReadinessStatus.WARN
    (tmp_path / "backups").mkdir(parents=True, exist_ok=True)
    (tmp_path / "backups" / "a.tar.gz").write_text("x")
    await checker._check_backup_system()
    assert checker.checks[-1].status == ReadinessStatus.PASS

    await checker._check_integration_tests()
    assert checker.checks[-1].status == ReadinessStatus.WARN
    tdir = tmp_path / "tests" / "integration"
    tdir.mkdir(parents=True, exist_ok=True)
    (tdir / "test_a.py").write_text("def test_a(): pass\n")
    await checker._check_integration_tests()
    assert checker.checks[-1].status == ReadinessStatus.WARN
    for i in range(2, 6):
        (tdir / f"test_{i}.py").write_text("def test_x(): pass\n")
    await checker._check_integration_tests()
    assert checker.checks[-1].status == ReadinessStatus.PASS

    await checker._check_incident_response()
    assert checker.checks[-1].status == ReadinessStatus.WARN
    docs = tmp_path / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "RUNBOOK.md").write_text("# runbook\n")
    await checker._check_incident_response()
    assert checker.checks[-1].status == ReadinessStatus.PASS

    await checker._check_maintenance_procedures()
    assert checker.checks[-1].status == ReadinessStatus.WARN
    (docs / "MAINTENANCE.md").write_text("# maint\n")
    await checker._check_maintenance_procedures()
    assert checker.checks[-1].status == ReadinessStatus.PASS


@pytest.mark.asyncio
async def test_secrets_scan_ignores_read_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    alt_root = Path(f"/tmp/prs_cov_{uuid.uuid4().hex}")
    alt_root.mkdir(parents=True, exist_ok=True)
    checker = ProductionReadinessChecker(alt_root)
    src = alt_root / "mahavishnu" / "core"
    src.mkdir(parents=True, exist_ok=True)
    (src / "test_secret.py").write_text("api_key='abcdefghijklmnopqrstuvwxyz123456'\n")
    await checker._check_secrets_management()
    assert checker.checks[-1].status == ReadinessStatus.PASS

    (src / "bad.py").write_text("x = 1\n")

    original_read_text = Path.read_text

    def fake_read_text(self, *args, **kwargs):  # noqa: ANN001,ANN002,ANN003
        if self.name == "bad.py":
            raise OSError("boom")
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fake_read_text, raising=True)
    await checker._check_secrets_management()
    assert checker.checks[-1].status == ReadinessStatus.PASS


@pytest.mark.asyncio
async def test_logging_check_warn_and_pass(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    checker = ProductionReadinessChecker(tmp_path)

    real_import = __import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):  # noqa: ANN001,ANN002,ANN003
        if name == "structlog":
            raise ImportError("missing")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr("builtins.__import__", fake_import)
    await checker._check_logging()
    assert checker.checks[-1].status == ReadinessStatus.WARN

    monkeypatch.setattr("builtins.__import__", real_import)
    await checker._check_logging()
    assert checker.checks[-1].status in (ReadinessStatus.PASS, ReadinessStatus.WARN)


@pytest.mark.asyncio
async def test_unit_test_check_branches(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    checker = ProductionReadinessChecker(tmp_path)

    # coverage >= 80 => PASS
    def run_ok(*args, **kwargs):  # noqa: ANN002,ANN003
        (tmp_path / "coverage.xml").write_text('<coverage line-rate="0.90"></coverage>')
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(prs.subprocess, "run", run_ok)
    await checker._check_unit_tests()
    assert checker.checks[-1].status == ReadinessStatus.PASS

    # parse error => WARN
    def run_parse_err(*args, **kwargs):  # noqa: ANN002,ANN003
        (tmp_path / "coverage.xml").write_text("<coverage")
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(prs.subprocess, "run", run_parse_err)
    await checker._check_unit_tests()
    assert checker.checks[-1].status == ReadinessStatus.WARN

    # timeout => WARN
    def run_timeout(*args, **kwargs):  # noqa: ANN002,ANN003
        raise prs.subprocess.TimeoutExpired(cmd="pytest", timeout=1)

    monkeypatch.setattr(prs.subprocess, "run", run_timeout)
    await checker._check_unit_tests()
    assert checker.checks[-1].status == ReadinessStatus.WARN


@pytest.mark.asyncio
async def test_remaining_warn_fail_and_main_branches(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    checker = ProductionReadinessChecker(tmp_path)

    # Metrics collection warn branch
    (tmp_path / "monitoring").mkdir(parents=True, exist_ok=True)
    await checker._check_metrics_collection()
    assert checker.checks[-1].status == ReadinessStatus.WARN

    # Circuit breakers / rate limiting warn branches
    empty_root = Path(f"/tmp/prs_empty_{uuid.uuid4().hex}")
    empty_root.mkdir(parents=True, exist_ok=True)
    checker_empty = ProductionReadinessChecker(empty_root)
    await checker_empty._check_circuit_breakers()
    assert checker_empty.checks[-1].status == ReadinessStatus.WARN
    await checker_empty._check_rate_limiting()
    assert checker_empty.checks[-1].status == ReadinessStatus.WARN

    # Integration tests warn/fail branches
    await checker._check_integration_tests()
    assert checker.checks[-1].status == ReadinessStatus.WARN
    integration = tmp_path / "tests" / "integration"
    integration.mkdir(parents=True, exist_ok=True)
    await checker._check_integration_tests()
    assert checker.checks[-1].status == ReadinessStatus.FAIL

    # Unit tests: low coverage, no coverage file, missing pytest, generic exception
    def run_low_cov(*args, **kwargs):  # noqa: ANN002,ANN003
        (tmp_path / "coverage.xml").write_text('<coverage line-rate="0.55"></coverage>')
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(prs.subprocess, "run", run_low_cov)
    await checker._check_unit_tests()
    assert checker.checks[-1].status == ReadinessStatus.FAIL

    def run_mid_cov(*args, **kwargs):  # noqa: ANN002,ANN003
        (tmp_path / "coverage.xml").write_text('<coverage line-rate="0.70"></coverage>')
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(prs.subprocess, "run", run_mid_cov)
    await checker._check_unit_tests()
    assert checker.checks[-1].status == ReadinessStatus.WARN

    def run_no_cov(*args, **kwargs):  # noqa: ANN002,ANN003
        cov = tmp_path / "coverage.xml"
        if cov.exists():
            cov.unlink()
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(prs.subprocess, "run", run_no_cov)
    await checker._check_unit_tests()
    assert checker.checks[-1].status == ReadinessStatus.WARN

    def run_missing(*args, **kwargs):  # noqa: ANN002,ANN003
        raise FileNotFoundError("pytest")

    monkeypatch.setattr(prs.subprocess, "run", run_missing)
    await checker._check_unit_tests()
    assert checker.checks[-1].status == ReadinessStatus.WARN

    def run_generic(*args, **kwargs):  # noqa: ANN002,ANN003
        raise RuntimeError("boom")

    monkeypatch.setattr(prs.subprocess, "run", run_generic)
    await checker._check_unit_tests()
    assert checker.checks[-1].status == ReadinessStatus.WARN

    # main() exit branches
    report_fail = ProductionReadinessReport(total_checks=1, failed=1, timestamp="now")
    report_warn = ProductionReadinessReport(total_checks=1, warnings=1, timestamp="now")
    report_ok = ProductionReadinessReport(total_checks=1, timestamp="now")

    async def fake_fail(self):  # noqa: ANN001
        return report_fail

    async def fake_warn(self):  # noqa: ANN001
        return report_warn

    async def fake_ok(self):  # noqa: ANN001
        return report_ok

    monkeypatch.setattr(ProductionReadinessChecker, "generate_report", lambda self, report: "x", raising=True)

    monkeypatch.setattr(ProductionReadinessChecker, "run_full_check", fake_fail, raising=True)
    with pytest.raises(SystemExit) as exc:
        await prs.main()
    assert exc.value.code == 1

    monkeypatch.setattr(ProductionReadinessChecker, "run_full_check", fake_warn, raising=True)
    with pytest.raises(SystemExit) as exc:
        await prs.main()
    assert exc.value.code == 2

    monkeypatch.setattr(ProductionReadinessChecker, "run_full_check", fake_ok, raising=True)
    with pytest.raises(SystemExit) as exc:
        await prs.main()
    assert exc.value.code == 0
