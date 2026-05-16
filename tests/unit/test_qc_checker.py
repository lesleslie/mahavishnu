"""Tests for qc/checker.py — QualityControl integration with Crackerjack."""

import json
from unittest.mock import MagicMock

import httpx
import respx

from mahavishnu.qc.checker import QualityControl


def _mock_config(enabled=True, min_score=80, crackerjack_url="http://localhost:8676/mcp"):
    config = MagicMock()
    config.qc.enabled = enabled
    config.qc.min_score = min_score
    config.qc.checks = ["linting", "type_checking"]
    config.qc.crackerjack_url = crackerjack_url
    # getattr fallback for qc_checks
    del config.qc_checks
    return config


_TOOLS_URL = "http://localhost:8676/mcp/tools/call"
_HEALTH_URL = "http://localhost:8676/health"

_SUCCESS_RESULT = json.dumps({"success": True, "errors": [], "warnings": [], "duration": 1.2})
_FAILURE_RESULT = json.dumps(
    {"success": False, "errors": ["lint error 1", "type error 2"], "warnings": [], "duration": 2.0}
)


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


class TestRunPreChecksDisabled:
    async def test_disabled_returns_pass(self):
        qc = QualityControl(_mock_config(enabled=False))
        result = await qc.run_pre_checks(["/tmp/repo"])
        assert result["enabled"] is False
        assert result["passed"] is True
        assert result["score"] == 100

    async def test_disabled_empty_checks(self):
        qc = QualityControl(_mock_config(enabled=False))
        result = await qc.run_pre_checks(["/tmp/repo"])
        assert result["checks"] == []


class TestRunPreChecksSuccess:
    @respx.mock
    async def test_single_repo_success(self):
        respx.post(_TOOLS_URL).mock(
            return_value=httpx.Response(200, json={"result": _SUCCESS_RESULT})
        )
        qc = QualityControl(_mock_config())
        result = await qc.run_pre_checks(["/tmp/repo"])
        assert result["enabled"] is True
        assert result["passed"] is True
        assert result["score"] == 100
        assert "/tmp/repo" in result["individual_results"]

    @respx.mock
    async def test_multiple_repos_uses_min_score(self):
        respx.post(_TOOLS_URL).mock(
            side_effect=[
                httpx.Response(200, json={"result": _SUCCESS_RESULT}),
                httpx.Response(200, json={"result": _FAILURE_RESULT}),
            ]
        )
        qc = QualityControl(_mock_config(min_score=90))  # worst repo score=80 < 90
        result = await qc.run_pre_checks(["/tmp/a", "/tmp/b"])
        assert result["score"] < 100
        assert result["passed"] is False

    @respx.mock
    async def test_per_check_results_populated(self):
        respx.post(_TOOLS_URL).mock(
            return_value=httpx.Response(200, json={"result": _SUCCESS_RESULT})
        )
        qc = QualityControl(_mock_config())
        result = await qc.run_pre_checks(["/tmp/r"])
        repo_checks = result["individual_results"]["/tmp/r"]
        assert "linting" in repo_checks
        assert "type_checking" in repo_checks
        assert repo_checks["linting"]["status"] == "passed"

    @respx.mock
    async def test_custom_checks_override(self):
        respx.post(_TOOLS_URL).mock(
            return_value=httpx.Response(200, json={"result": _SUCCESS_RESULT})
        )
        qc = QualityControl(_mock_config())
        result = await qc.run_pre_checks(["/tmp/r"], checks=["security_scan"])
        assert result["checks"] == ["security_scan"]
        assert "security_scan" in result["individual_results"]["/tmp/r"]

    async def test_empty_repos(self):
        qc = QualityControl(_mock_config())
        result = await qc.run_pre_checks([])
        assert result["individual_results"] == {}
        assert result["score"] == 100
        assert result["passed"] is True


class TestRunPreChecksFailure:
    @respx.mock
    async def test_failure_score_below_threshold(self):
        respx.post(_TOOLS_URL).mock(
            return_value=httpx.Response(200, json={"result": _FAILURE_RESULT})
        )
        qc = QualityControl(_mock_config(min_score=90))  # score=80 < 90
        result = await qc.run_pre_checks(["/tmp/r"])
        assert result["score"] == 80  # 100 - 2*10
        assert result["passed"] is False

    @respx.mock
    async def test_failure_check_status_failed(self):
        respx.post(_TOOLS_URL).mock(
            return_value=httpx.Response(200, json={"result": _FAILURE_RESULT})
        )
        qc = QualityControl(_mock_config())
        result = await qc.run_pre_checks(["/tmp/r"])
        repo_checks = result["individual_results"]["/tmp/r"]
        for check in ["linting", "type_checking"]:
            assert repo_checks[check]["status"] == "failed"
            assert repo_checks[check]["issues_found"] == 2


class TestRunPreChecksDegraded:
    @respx.mock
    async def test_http_error_returns_score_zero(self):
        respx.post(_TOOLS_URL).mock(return_value=httpx.Response(500))
        qc = QualityControl(_mock_config(min_score=80))
        result = await qc.run_pre_checks(["/tmp/r"])
        assert result["score"] == 0
        assert result["passed"] is False

    @respx.mock
    async def test_transport_error_returns_score_zero(self):
        respx.post(_TOOLS_URL).mock(side_effect=httpx.ConnectError("refused"))
        qc = QualityControl(_mock_config(min_score=80))
        result = await qc.run_pre_checks(["/tmp/r"])
        assert result["score"] == 0
        assert result["passed"] is False

    @respx.mock
    async def test_degraded_per_check_status_is_error(self):
        respx.post(_TOOLS_URL).mock(side_effect=httpx.ConnectError("refused"))
        qc = QualityControl(_mock_config())
        result = await qc.run_pre_checks(["/tmp/r"])
        for check in result["individual_results"]["/tmp/r"].values():
            assert check["status"] == "error"


class TestRunPostChecks:
    @respx.mock
    async def test_post_disabled_returns_pass(self):
        qc = QualityControl(_mock_config(enabled=False))
        result = await qc.run_post_checks(["/tmp/repo"])
        assert result["enabled"] is False
        assert result["passed"] is True

    @respx.mock
    async def test_post_success(self):
        respx.post(_TOOLS_URL).mock(
            return_value=httpx.Response(200, json={"result": _SUCCESS_RESULT})
        )
        qc = QualityControl(_mock_config())
        result = await qc.run_post_checks(["/tmp/r"])
        assert result["passed"] is True
        assert result["score"] == 100


class TestIsHealthy:
    @respx.mock
    async def test_healthy_when_200(self):
        respx.get(_HEALTH_URL).mock(return_value=httpx.Response(200))
        qc = QualityControl(_mock_config())
        assert await qc.is_healthy() is True

    @respx.mock
    async def test_unhealthy_when_500(self):
        respx.get(_HEALTH_URL).mock(return_value=httpx.Response(500))
        qc = QualityControl(_mock_config())
        assert await qc.is_healthy() is False

    @respx.mock
    async def test_unhealthy_on_connect_error(self):
        respx.get(_HEALTH_URL).mock(side_effect=httpx.ConnectError("refused"))
        qc = QualityControl(_mock_config())
        assert await qc.is_healthy() is False


class TestValidateExecution:
    async def test_validate_pre_disabled_always_passes(self):
        qc = QualityControl(_mock_config(enabled=False))
        assert await qc.validate_pre_execution(["/tmp/r"]) is True

    async def test_validate_post_disabled_always_passes(self):
        qc = QualityControl(_mock_config(enabled=False))
        assert await qc.validate_post_execution(["/tmp/r"]) is True

    @respx.mock
    async def test_validate_pre_passes_on_success(self):
        respx.post(_TOOLS_URL).mock(
            return_value=httpx.Response(200, json={"result": _SUCCESS_RESULT})
        )
        qc = QualityControl(_mock_config())
        assert await qc.validate_pre_execution(["/tmp/r"]) is True

    @respx.mock
    async def test_validate_pre_fails_on_errors(self):
        respx.post(_TOOLS_URL).mock(
            return_value=httpx.Response(200, json={"result": _FAILURE_RESULT})
        )
        qc = QualityControl(_mock_config(min_score=90))
        assert await qc.validate_pre_execution(["/tmp/r"]) is False
