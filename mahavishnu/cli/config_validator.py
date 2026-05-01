"""Configuration validation CLI commands for Mahavishnu."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import typer
import yaml

from ..core.config import MahavishnuSettings
from ..core.config_validator import ConfigValidationReport, ValidationResult, validate_config
from ..core.skill_mcp_validator import validate_agent_dir, validate_skill_dir
from ..core.health import HealthChecker
from ..core.health_schemas import HealthStatus


@dataclass(slots=True)
class RuntimeValidationCheck:
    """Structured result for a runtime validation check."""

    name: str
    valid: bool
    message: str
    path: str = ""
    target: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the runtime check."""
        return {
            "name": self.name,
            "valid": self.valid,
            "message": self.message,
            "path": self.path,
            "target": self.target,
            "details": self.details,
        }


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge two config dictionaries."""
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _load_yaml_mapping(path: Path) -> dict[str, Any]:
    """Load a YAML mapping if the file exists."""
    if not path.exists():
        return {}

    with path.open() as handle:
        data = yaml.safe_load(handle) or {}

    if not isinstance(data, dict):
        raise ValueError(f"Configuration file must contain a mapping: {path}")

    return data


def _load_settings_from_dir(config_dir: Path) -> MahavishnuSettings:
    """Load settings from an arbitrary configuration directory."""
    merged: dict[str, Any] = {}
    for filename in ("mahavishnu.yaml", "local.yaml"):
        merged = _deep_merge(merged, _load_yaml_mapping(config_dir / filename))

    if "repos_path" not in merged:
        merged["repos_path"] = str((config_dir / "repos.yaml").resolve())

    return MahavishnuSettings.model_validate(merged)


def _ensure_http_url(value: str, field_name: str) -> ValidationResult:
    """Validate that a string looks like an HTTP(S) URL."""
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ValidationResult(
            valid=False,
            message=f"Invalid {field_name}: expected http(s) URL, got {value!r}",
            path=field_name,
            suggestions=["Use a URL like http://localhost:4200 or https://example.com"],
        )

    return ValidationResult(
        valid=True,
        message=f"Validated {field_name}: {value}",
        path=field_name,
    )


def _validate_pool_config(settings: MahavishnuSettings) -> list[ValidationResult]:
    """Validate pool configuration invariants."""
    results: list[ValidationResult] = []
    pool = settings.pools

    if not pool.enabled:
        return results

    if pool.min_workers > pool.max_workers:
        results.append(
            ValidationResult(
                valid=False,
                message="Pool configuration invalid: min_workers cannot exceed max_workers",
                path="pools.min_workers",
                suggestions=["Decrease min_workers or increase max_workers"],
            )
        )

    valid_strategies = {"round_robin", "least_loaded", "random", "affinity"}
    if pool.routing_strategy not in valid_strategies:
        results.append(
            ValidationResult(
                valid=False,
                message=f"Invalid pool routing strategy: {pool.routing_strategy}",
                path="pools.routing_strategy",
                suggestions=[f"Use one of: {', '.join(sorted(valid_strategies))}"],
            )
        )

    return results


def _validate_adapter_config(settings: MahavishnuSettings) -> list[ValidationResult]:
    """Validate adapter-related configuration."""
    results: list[ValidationResult] = []

    if settings.adapters.prefect_enabled:
        results.append(_ensure_http_url(settings.prefect.api_url, "prefect.api_url"))

    if settings.adapters.agno_enabled:
        results.append(_ensure_http_url(settings.agno.tools.mcp_server_url, "agno.tools.mcp_server_url"))

    if settings.adapters.llamaindex_enabled:
        results.append(_ensure_http_url(settings.llm.ollama_base_url, "llm.ollama_base_url"))

    return results


def _validate_runtime_settings(settings: MahavishnuSettings) -> list[ValidationResult]:
    """Validate runtime-only configuration invariants."""
    results: list[ValidationResult] = []

    repos_path = Path(settings.repos_path).expanduser()
    if repos_path.exists():
        results.append(
            ValidationResult(
                valid=True,
                message=f"Validated repos path: {repos_path}",
                path="repos_path",
            )
        )
    else:
        results.append(
            ValidationResult(
                valid=False,
                message=f"Configured repos path does not exist: {repos_path}",
                path="repos_path",
                suggestions=["Update repos_path or create the referenced repo manifest"],
            )
        )

    results.extend(_validate_pool_config(settings))
    results.extend(_validate_adapter_config(settings))
    return results


def _dependency_health_url(name: str, dependency: Any) -> str:
    """Build a health URL for a configured dependency."""
    scheme = "https" if dependency.use_tls else "http"
    return f"{scheme}://{dependency.host}:{dependency.port}/health"


def _mcp_health_url(endpoint: str) -> str:
    """Convert an MCP URL to a health-check URL."""
    parsed = urlparse(endpoint)
    path = parsed.path.rstrip("/")
    if path.endswith("/mcp"):
        path = path[: -len("/mcp")] + "/health"
    elif not path or path == "/":
        path = "/health"
    else:
        path = f"{path}/health"

    return parsed._replace(path=path, params="", query="", fragment="").geturl()


async def _validate_runtime_connectivity(settings: MahavishnuSettings) -> list[RuntimeValidationCheck]:
    """Validate runtime connectivity for configured dependencies and MCP endpoints."""
    checks: list[RuntimeValidationCheck] = []
    checker = HealthChecker(config=settings.health)

    dependency_tasks: list[tuple[str, str, bool, asyncio.Task[Any]]] = []
    for name, dependency in settings.health.dependencies.items():
        url = _dependency_health_url(name, dependency)
        dependency_tasks.append(
            (
                name,
                url,
                dependency.required,
                asyncio.create_task(checker.check(url, timeout=dependency.timeout_seconds)),
            )
        )

    if settings.session_buddy_polling.enabled:
        url = _mcp_health_url(settings.session_buddy_polling.endpoint)
        dependency_tasks.append(
            (
                "session_buddy_polling",
                url,
                True,
                asyncio.create_task(
                    checker.check(url, timeout=settings.session_buddy_polling.timeout_seconds)
                ),
            )
        )

    if settings.agno.enabled and settings.agno.tools.mcp_server_url:
        url = _mcp_health_url(settings.agno.tools.mcp_server_url)
        dependency_tasks.append(
            (
                "agno_tools_mcp_server",
                url,
                True,
                asyncio.create_task(
                    checker.check(url, timeout=settings.agno.tools.tool_timeout_seconds)
                ),
            )
        )

    if not dependency_tasks:
        return checks

    gathered = await asyncio.gather(*(task for _, _, _, task in dependency_tasks), return_exceptions=True)
    for (name, url, required, _), result in zip(dependency_tasks, gathered, strict=True):
        if isinstance(result, Exception):
            checks.append(
                RuntimeValidationCheck(
                    name=name,
                    valid=not required,
                    message=f"Connectivity check failed: {result}",
                    path=name,
                    target=url,
                    details={"severity": "error" if required else "warning"},
                )
            )
            continue

        if result.status in {HealthStatus.OK, HealthStatus.DEGRADED}:
            checks.append(
                RuntimeValidationCheck(
                    name=name,
                    valid=True,
                    message=f"Connectivity OK: {url}",
                    path=name,
                    target=url,
                    details={
                        "status": result.status.value,
                        "latency_ms": result.latency_ms,
                    },
                )
            )
        else:
            checks.append(
                RuntimeValidationCheck(
                    name=name,
                    valid=not required,
                    message=f"Connectivity failed: {url}",
                    path=name,
                    target=url,
                    details={
                        "status": result.status.value,
                        "latency_ms": result.latency_ms,
                        "error": result.error,
                        "severity": "error" if required else "warning",
                    },
                )
            )

    return checks


async def run_validation(config_dir: str | Path = "settings", full: bool = False) -> dict[str, Any]:
    """Run static and optional runtime configuration validation."""
    config_dir = Path(config_dir)
    static_report: ConfigValidationReport = validate_config(config_dir)
    runtime_checks: list[RuntimeValidationCheck] = []
    runtime_validations: list[ValidationResult] = []
    runtime_settings_source = "default"

    if static_report.valid:
        try:
            if config_dir.resolve() == Path("settings").resolve():
                settings = MahavishnuSettings()
                runtime_settings_source = "settings"
            else:
                settings = _load_settings_from_dir(config_dir)
                runtime_settings_source = str(config_dir)
        except Exception as exc:  # pragma: no cover - defensive, exercised via CLI error paths
            runtime_validations.append(
                ValidationResult(
                    valid=False,
                    message=f"Failed to load runtime settings: {exc}",
                    path=str(config_dir),
                )
            )
        else:
            runtime_validations = _validate_runtime_settings(settings)
            # Drift check: find .claude/ in project dir first, fall back to global
            claude_dir = Path(__file__).parents[2] / ".claude"
            if not claude_dir.exists():
                claude_dir = Path.home() / ".claude"
            drift_report = check_skill_agent_drift(
                agents_dir=claude_dir / "agents",
                skills_dir=claude_dir / "skills",
            )
            drift_errors = [
                ValidationResult(valid=False, message=e, path="mcp_drift")
                for e in drift_report.errors
            ]
            drift_warnings = [
                ValidationResult(valid=True, message=w, path="mcp_drift")
                for w in drift_report.warnings
            ]
            runtime_validations.extend(drift_errors)
            runtime_validations.extend(drift_warnings)
            if full:
                runtime_checks = await _validate_runtime_connectivity(settings)

    runtime_errors = [check for check in runtime_checks if not check.valid]
    runtime_validation_errors = [result for result in runtime_validations if not result.valid]
    valid = static_report.valid and not runtime_errors and not runtime_validation_errors

    return {
        "valid": valid,
        "config_dir": str(config_dir),
        "full": full,
        "runtime_settings_source": runtime_settings_source,
        "static": static_report.to_dict(),
        "runtime_validations": [result.to_dict() for result in runtime_validations],
        "runtime_checks": [check.to_dict() for check in runtime_checks],
        "runtime_check_count": len(runtime_checks),
        "runtime_validation_count": len(runtime_validations),
        "summary": {
            "error_count": len(static_report.get_errors())
            + len(runtime_errors)
            + len(runtime_validation_errors),
            "warning_count": len(static_report.warnings)
            + sum(
                1
                for check in runtime_checks
                if check.valid and check.details.get("severity") == "warning"
            ),
            "runtime_check_count": len(runtime_checks),
            "runtime_validation_count": len(runtime_validations),
        },
    }


def _print_validation_report(report: dict[str, Any]) -> None:
    """Render a validation report to the terminal."""
    valid = report["valid"]
    static_report = report["static"]
    runtime_checks = report["runtime_checks"]
    runtime_validations = report["runtime_validations"]

    if valid:
        typer.echo("✅ Configuration validation passed")
    else:
        typer.echo("❌ Configuration validation failed", err=True)

    typer.echo(f"Config directory: {report['config_dir']}")

    if static_report["errors"]:
        typer.echo("\nStatic errors:", err=True)
        for error in static_report["errors"]:
            typer.echo(f"  - {error['path']}: {error['message']}", err=True)
            for suggestion in error.get("suggestions", []):
                typer.echo(f"    • {suggestion}", err=True)

    if static_report["warnings"]:
        typer.echo("\nStatic warnings:")
        for warning in static_report["warnings"]:
            typer.echo(f"  - {warning['path']}: {warning['message']}")

    if runtime_validations:
        typer.echo("\nRuntime validations:")
        for item in runtime_validations:
            status = "ok" if item["valid"] else "failed"
            typer.echo(f"  - [{status}] {item['path']}: {item['message']}")

    if runtime_checks:
        typer.echo("\nRuntime checks:")
        for check in runtime_checks:
            status = "ok" if check["valid"] else "failed"
            typer.echo(f"  - [{status}] {check['name']}: {check['message']}")

    summary = report["summary"]
    typer.echo(
        "\nSummary: "
        f"{summary['error_count']} error(s), "
        f"{summary['warning_count']} warning(s), "
        f"{summary['runtime_validation_count']} runtime validation(s), "
        f"{summary['runtime_check_count']} runtime check(s)"
    )


def add_config_validation_commands(app: typer.Typer) -> None:
    """Add configuration validation commands to a Typer app."""

    @app.command("validate")
    def validate_command(
        config_dir: Path = typer.Option(
            Path("settings"),
            "--config-dir",
            "-c",
            help="Configuration directory to validate",
            show_default=True,
        ),
        full: bool = typer.Option(
            False,
            "--full",
            help="Run full validation including runtime connectivity checks",
        ),
        json_output: bool = typer.Option(
            False,
            "--json",
            help="Emit structured JSON output",
        ),
    ) -> None:
        """Validate configuration files and runtime connectivity."""

        async def _validate() -> None:
            report = await run_validation(config_dir=config_dir, full=full)

            if json_output:
                typer.echo(json.dumps(report, indent=2, default=str))
            else:
                _print_validation_report(report)

            if not report["valid"]:
                raise typer.Exit(code=1)

        asyncio.run(_validate())


@dataclass(slots=True)
class DriftReport:
    """Aggregated skill/agent MCP drift report."""

    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def error_count(self) -> int:
        return len(self.errors)

    @property
    def valid(self) -> bool:
        return not self.errors


def check_skill_agent_drift(
    agents_dir: Path,
    skills_dir: Path,
) -> DriftReport:
    """Check agents and skills for stale MCP references and description violations."""
    report = DriftReport()

    if agents_dir.exists():
        for name, agent_report in validate_agent_dir(agents_dir).items():
            for ref in agent_report.stale_refs:
                report.errors.append(
                    f"Agent {name}: stale MCP ref {ref!r} not in KNOWN_TOOLS"
                )
            if agent_report.description_too_long:
                report.warnings.append(
                    f"Agent {name}: description exceeds 300 characters"
                )

    if skills_dir.exists():
        for rel_path, skill_report in validate_skill_dir(skills_dir).items():
            for ref in skill_report.stale_refs:
                report.errors.append(
                    f"Skill {rel_path}: stale MCP ref {ref!r} not in KNOWN_TOOLS"
                )
            for wrong in skill_report.wrong_ports:
                report.errors.append(f"Skill {rel_path}: wrong port — {wrong}")

    return report


_PROJECT_ROOT = Path(__file__).parents[2]


def _get_project_root() -> Path:
    """Return project root, overridable via MAHAVISHNU_PROJECT_ROOT for tests."""
    import os
    override = os.environ.get("MAHAVISHNU_PROJECT_ROOT")
    return Path(override) if override else _PROJECT_ROOT


def add_config_inventory_commands(app: typer.Typer) -> None:
    """Add config inventory commands (list-agents, list-skills, list-mcp-servers, sync-from-global, rollback)."""

    @app.command("list-agents")
    def list_agents(
        role: str | None = typer.Option(None, help="Filter by role tag in frontmatter"),
    ) -> None:
        """List all agents in .claude/agents/."""
        agents_dir = _get_project_root() / ".claude" / "agents"
        if not agents_dir.exists():
            typer.echo("No agents directory found. Run migration first.")
            raise typer.Exit(1)
        agents = sorted(agents_dir.glob("*.md"))
        typer.echo(f"{len(agents)} agents found:")
        for a in agents:
            typer.echo(f"  {a.stem}")

    @app.command("list-skills")
    def list_skills() -> None:
        """List all skills in .claude/skills/."""
        skills_dir = _get_project_root() / ".claude" / "skills"
        if not skills_dir.exists():
            typer.echo("No skills directory found. Run migration first.")
            raise typer.Exit(1)
        skills = [d for d in skills_dir.iterdir() if (d / "SKILL.md").exists()]
        typer.echo(f"{len(skills)} skills found:")
        for s in sorted(skills):
            typer.echo(f"  {s.name}")

    @app.command("list-mcp-servers")
    def list_mcp_servers() -> None:
        """List MCP servers from .mcp.json."""
        mcp_path = _get_project_root() / ".mcp.json"
        if not mcp_path.exists():
            typer.echo(".mcp.json not found. Run migration first.")
            raise typer.Exit(1)
        data = json.loads(mcp_path.read_text())
        servers = data.get("mcpServers", {})
        typer.echo(f"{len(servers)} MCP servers:")
        for name, cfg in sorted(servers.items()):
            url = cfg.get("url", cfg.get("command", "local"))
            typer.echo(f"  {name}: {url}")

    @app.command("sync-from-global")
    def sync_from_global(
        dry_run: bool = typer.Option(False, "--dry-run"),
    ) -> None:
        """Re-import agents/skills added to ~/.claude/ since last migration."""
        import sys
        sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))
        from migrate_config_to_project import MigrationRunner  # noqa: PLC0415
        home = Path.home()
        runner = MigrationRunner(
            source_claude=home / ".claude",
            source_claude_json=home / ".claude.json",
            dest_project=_get_project_root(),
            dry_run=dry_run,
            backup=False,
        )
        runner.run()

    @app.command("rollback")
    def rollback_cmd(
        timestamp: str = typer.Argument(help="Backup timestamp (YYYYMMDDTHHmmSS)"),
    ) -> None:
        """Restore ~/.claude.json, settings.local.json, and agents/skills from backup."""
        import sys
        sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))
        from migrate_config_to_project import rollback  # noqa: PLC0415
        rollback(_get_project_root(), timestamp)


__all__ = [
    "add_config_inventory_commands",
    "add_config_validation_commands",
    "check_skill_agent_drift",
    "DriftReport",
    "run_validation",
]
