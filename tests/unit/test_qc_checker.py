"""Tests for qc/checker.py — QualityControl integration with Crackerjack."""

from unittest.mock import MagicMock

import pytest

from mahavishnu.qc.checker import QualityControl


def _mock_config(enabled=True, min_score=80, qc_checks=None):
    config = MagicMock()
    config.qc.enabled = enabled
    config.qc.min_score = min_score
    if qc_checks is not None:
        config.qc_checks = qc_checks
    else:
        # Default: getattr returns ["linting", "type_checking"] in the real code
        delattr(config, "qc_checks") if hasattr(config, "qc_checks") else None
    return config


class TestQualityControlInit:
    def test_enabled_init(self):
        qc = QualityControl(_mock_config(enabled=True, min_score=75))
        assert qc.enabled is True
        assert qc.min_score == 75

    def test_disabled_init(self):
        qc = QualityControl(_mock_config(enabled=False))
        assert qc.enabled is False

    def test_default_checks(self):
        qc = QualityControl(_mock_config())
        assert "linting" in qc.checks
        assert "type_checking" in qc.checks


class TestRunPreChecks:
    async def test_disabled_returns_pass(self):
        qc = QualityControl(_mock_config(enabled=False))
        result = await qc.run_pre_checks(["/tmp/repo"])
        assert result["enabled"] is False
        assert result["passed"] is True
        assert result["score"] == 100

    async def test_single_repo_default_checks(self):
        qc = QualityControl(_mock_config())
        result = await qc.run_pre_checks(["/tmp/repo"])
        assert result["enabled"] is True
        assert result["passed"] is True
        assert "/tmp/repo" in result["individual_results"]
        assert "linting" in result["individual_results"]["/tmp/repo"]
        assert "type_checking" in result["individual_results"]["/tmp/repo"]

    async def test_multiple_repos(self):
        qc = QualityControl(_mock_config())
        result = await qc.run_pre_checks(["/tmp/a", "/tmp/b"])
        assert len(result["individual_results"]) == 2

    async def test_custom_checks_override(self):
        qc = QualityControl(_mock_config())
        result = await qc.run_pre_checks(["/tmp/r"], checks=["security_scan", "complexity"])
        assert result["checks"] == ["security_scan", "complexity"]
        assert "security_scan" in result["individual_results"]["/tmp/r"]
        assert "complexity" in result["individual_results"]["/tmp/r"]

    async def test_linting_check_result(self):
        qc = QualityControl(_mock_config())
        result = await qc.run_pre_checks(["/tmp/r"], checks=["linting"])
        lint = result["individual_results"]["/tmp/r"]["linting"]
        assert lint["status"] == "passed"
        assert lint["issues_found"] == 0

    async def test_type_checking_check_result(self):
        qc = QualityControl(_mock_config())
        result = await qc.run_pre_checks(["/tmp/r"], checks=["type_checking"])
        tc = result["individual_results"]["/tmp/r"]["type_checking"]
        assert tc["status"] == "passed"

    async def test_security_scan_check_result(self):
        qc = QualityControl(_mock_config())
        result = await qc.run_pre_checks(["/tmp/r"], checks=["security_scan"])
        sec = result["individual_results"]["/tmp/r"]["security_scan"]
        assert sec["status"] == "passed"
        assert "/tmp/r" in sec["details"]

    async def test_complexity_check_result(self):
        qc = QualityControl(_mock_config())
        result = await qc.run_pre_checks(["/tmp/r"], checks=["complexity"])
        comp = result["individual_results"]["/tmp/r"]["complexity"]
        assert comp["status"] == "passed"

    async def test_unknown_check_skipped(self):
        qc = QualityControl(_mock_config())
        result = await qc.run_pre_checks(["/tmp/r"], checks=["unknown_check"])
        unk = result["individual_results"]["/tmp/r"]["unknown_check"]
        assert unk["status"] == "skipped"
        assert "Unknown check type" in unk["details"]

    async def test_score_equals_min_score(self):
        qc = QualityControl(_mock_config(min_score=60))
        result = await qc.run_pre_checks(["/tmp/r"])
        assert result["score"] == 60
        assert result["passed"] is True

    async def test_empty_repos(self):
        qc = QualityControl(_mock_config())
        result = await qc.run_pre_checks([])
        assert result["enabled"] is True
        assert result["individual_results"] == {}


class TestRunPostChecks:
    async def test_disabled_returns_pass(self):
        qc = QualityControl(_mock_config(enabled=False))
        result = await qc.run_post_checks(["/tmp/repo"])
        assert result["enabled"] is False
        assert result["passed"] is True

    async def test_post_check_includes_after_text(self):
        qc = QualityControl(_mock_config())
        result = await qc.run_post_checks(["/tmp/r"], checks=["linting"])
        lint = result["individual_results"]["/tmp/r"]["linting"]
        assert "after workflow" in lint["details"]

    async def test_post_score_higher_than_pre(self):
        qc = QualityControl(_mock_config(min_score=80))
        pre = await qc.run_pre_checks(["/tmp/r"])
        post = await qc.run_post_checks(["/tmp/r"])
        assert post["score"] > pre["score"]
        assert post["score"] == min(80 + 5, 100)

    async def test_post_score_capped_at_100(self):
        qc = QualityControl(_mock_config(min_score=98))
        post = await qc.run_post_checks(["/tmp/r"])
        assert post["score"] == 100

    async def test_post_custom_checks(self):
        qc = QualityControl(_mock_config())
        result = await qc.run_post_checks(["/tmp/r"], checks=["security_scan"])
        assert "security_scan" in result["individual_results"]["/tmp/r"]

    async def test_post_unknown_check_skipped(self):
        qc = QualityControl(_mock_config())
        result = await qc.run_post_checks(["/tmp/r"], checks=["bogus"])
        assert result["individual_results"]["/tmp/r"]["bogus"]["status"] == "skipped"


class TestValidatePreExecution:
    async def test_disabled_always_passes(self):
        qc = QualityControl(_mock_config(enabled=False))
        assert await qc.validate_pre_execution(["/tmp/r"]) is True

    async def test_enabled_passes(self):
        qc = QualityControl(_mock_config())
        assert await qc.validate_pre_execution(["/tmp/r"]) is True


class TestValidatePostExecution:
    async def test_disabled_always_passes(self):
        qc = QualityControl(_mock_config(enabled=False))
        assert await qc.validate_post_execution(["/tmp/r"]) is True

    async def test_enabled_passes(self):
        qc = QualityControl(_mock_config())
        assert await qc.validate_post_execution(["/tmp/r"]) is True
