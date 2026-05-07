"""Quality Control (QC) integration for Mahavishnu."""

import json
import logging
from typing import Any, cast

import httpx

from ..core.config import MahavishnuSettings
from ..core.errors import ExternalServiceError, TimeoutError

logger = logging.getLogger(__name__)

_TOOLS_CALL_PATH = "/tools/call"


def _score_from_result(result: dict[str, Any], min_score: int) -> int:
    """Map a Crackerjack QualityCheckResult to a numeric score."""
    if result.get("success"):
        return 100
    errors = result.get("errors") or []
    raw = 100 - len(errors) * 10
    return max(0, raw)


class QualityControl:
    """Quality control integration with Crackerjack."""

    def __init__(self, config: MahavishnuSettings):
        self.config = config
        self.enabled = config.qc.enabled
        self.min_score = config.qc.min_score
        self.checks = getattr(config, "qc_checks", None) or list(config.qc.checks)
        self._base_url = config.qc.crackerjack_url
        self._client = httpx.AsyncClient(timeout=120.0)

    async def _call_mcp(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            response = await self._client.post(
                f"{self._base_url}{_TOOLS_CALL_PATH}",
                json={"name": tool_name, "arguments": arguments},
            )
            response.raise_for_status()
            return cast("dict[str, Any]", response.json())
        except httpx.TimeoutException as exc:
            raise TimeoutError(
                f"crackerjack:{tool_name}",
                details={"tool": tool_name, "url": self._base_url},
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise ExternalServiceError(
                "crackerjack",
                f"Tool '{tool_name}' returned {exc.response.status_code}",
                details={"tool": tool_name, "status_code": exc.response.status_code},
            ) from exc
        except httpx.TransportError as exc:
            raise ExternalServiceError(
                "crackerjack",
                f"Unreachable: {exc}",
                details={"tool": tool_name, "url": self._base_url},
            ) from exc

    async def is_healthy(self) -> bool:
        health_url = self._base_url.replace("/mcp", "/health")
        try:
            r = await self._client.get(health_url, timeout=5.0)
            return r.status_code == 200
        except (httpx.HTTPError, httpx.TransportError):
            return False

    async def _run_checks_for_repo(
        self, repo: str, checks: list[str]
    ) -> tuple[dict[str, Any], int]:
        """Run crackerjack on one repo and return (per-check results, score)."""
        try:
            raw = await self._call_mcp(
                "execute_crackerjack",
                {
                    "args": "",
                    "kwargs": json.dumps({"target_dir": repo, "checks": checks}),
                },
            )
            # execute_crackerjack returns a JSON string under "result"
            result_str = raw.get("result", "{}")
            cj_result = json.loads(result_str) if isinstance(result_str, str) else result_str

            score = _score_from_result(cj_result, self.min_score)
            errors = cj_result.get("errors") or []
            success = cj_result.get("success", False)

            per_check: dict[str, Any] = {}
            for check in checks:
                per_check[check] = {
                    "status": "passed" if success else "failed",
                    "issues_found": len(errors),
                    "details": errors[0]
                    if errors
                    else (f"No issues in {repo}" if success else f"Issues found in {repo}"),
                }

            return per_check, score

        except (ExternalServiceError, TimeoutError) as exc:
            logger.warning("Crackerjack check degraded for %s: %s", repo, exc)
            per_check = {
                check: {
                    "status": "error",
                    "issues_found": 0,
                    "details": str(exc),
                    "error": str(exc),
                }
                for check in checks
            }
            return per_check, 0

    async def run_pre_checks(
        self, repos: list[str], checks: list[str] | None = None
    ) -> dict[str, Any]:
        if not self.enabled:
            return {"enabled": False, "score": 100, "checks": [], "passed": True}

        checks_to_run = checks if checks is not None else self.checks
        individual_results: dict[str, Any] = {}
        scores: list[int] = []

        for repo in repos:
            per_check, score = await self._run_checks_for_repo(repo, checks_to_run)
            individual_results[repo] = per_check
            scores.append(score)

        overall = min(scores) if scores else 100
        return {
            "enabled": True,
            "checks": checks_to_run,
            "repos_checked": repos,
            "individual_results": individual_results,
            "score": overall,
            "passed": overall >= self.min_score,
        }

    async def run_post_checks(
        self, repos: list[str], checks: list[str] | None = None
    ) -> dict[str, Any]:
        return await self.run_pre_checks(repos, checks)

    async def validate_pre_execution(self, repos: list[str]) -> bool:
        if not self.enabled:
            return True
        results = await self.run_pre_checks(repos)
        return bool(results["passed"])

    async def validate_post_execution(self, repos: list[str]) -> bool:
        if not self.enabled:
            return True
        results = await self.run_post_checks(repos)
        return bool(results["passed"])
