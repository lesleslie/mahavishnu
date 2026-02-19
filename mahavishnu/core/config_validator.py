"""Configuration Validator for Mahavishnu.

Validates configuration files on startup:
- repos.yaml structure
- Required fields
- Type validation
- Helpful error messages
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from mahavishnu.core.errors import ConfigurationError, ValidationError

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """Result of a validation check."""

    valid: bool
    message: str = ""
    path: str = ""
    suggestions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "valid": self.valid,
            "message": self.message,
            "path": self.path,
            "suggestions": self.suggestions,
        }


@dataclass
class ConfigValidationReport:
    """Complete validation report."""

    valid: bool
    results: list[ValidationResult] = field(default_factory=list)
    warnings: list[ValidationResult] = field(default_factory=list)

    def add_result(self, result: ValidationResult) -> None:
        """Add a validation result."""
        self.results.append(result)
        if not result.valid:
            self.valid = False

    def add_warning(self, warning: ValidationResult) -> None:
        """Add a warning (non-fatal issue)."""
        self.warnings.append(warning)

    def get_errors(self) -> list[ValidationResult]:
        """Get all error results."""
        return [r for r in self.results if not r.valid]

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "valid": self.valid,
            "errors": [r.to_dict() for r in self.get_errors()],
            "warnings": [w.to_dict() for w in self.warnings],
        }


class ConfigValidator:
    """Validates Mahavishnu configuration."""

    # Required fields in repos.yaml
    REQUIRED_REPO_FIELDS = ["name", "path"]

    # Optional fields with expected types
    OPTIONAL_REPO_FIELDS = {
        "package": str,
        "nickname": str,
        "role": str,
        "tags": list,
        "description": str,
        "mcp": str,
    }

    # Valid roles (from CLAUDE.md)
    VALID_ROLES = {
        "orchestrator",
        "resolver",
        "manager",
        "inspector",
        "builder",
        "soothsayer",
        "app",
        "asset",
        "foundation",
        "visualizer",
        "extension",
        "tool",
    }

    # Valid MCP types
    VALID_MCP_TYPES = {"native", "3rd-party"}

    def __init__(self) -> None:
        self.report = ConfigValidationReport(valid=True)

    def validate_repos_yaml(self, repos_path: str | Path) -> ConfigValidationReport:
        """Validate repos.yaml file.

        Args:
            repos_path: Path to repos.yaml

        Returns:
            Validation report
        """
        self.report = ConfigValidationReport(valid=True)
        path = Path(repos_path)

        # Check file exists
        if not path.exists():
            self.report.add_result(
                ValidationResult(
                    valid=False,
                    message=f"Configuration file not found: {path}",
                    path=str(path),
                    suggestions=[
                        "Create a repos.yaml file in your settings directory",
                        "Run 'mahavishnu init' to create a default configuration",
                    ],
                )
            )
            return self.report

        # Parse YAML
        try:
            with open(path) as f:
                config = yaml.safe_load(f)
        except yaml.YAMLError as e:
            self.report.add_result(
                ValidationResult(
                    valid=False,
                    message=f"Invalid YAML syntax: {e}",
                    path=str(path),
                    suggestions=[
                        "Check YAML syntax at yamlint.com",
                        "Ensure proper indentation (use spaces, not tabs)",
                    ],
                )
            )
            return self.report

        # Validate structure
        if not isinstance(config, dict):
            self.report.add_result(
                ValidationResult(
                    valid=False,
                    message="Configuration must be a dictionary",
                    path=str(path),
                )
            )
            return self.report

        # Get repos list
        repos = config.get("repos", [])
        if not isinstance(repos, list):
            self.report.add_result(
                ValidationResult(
                    valid=False,
                    message="'repos' must be a list",
                    path=f"{path}:repos",
                )
            )
            return self.report

        if not repos:
            self.report.add_warning(
                ValidationResult(
                    valid=True,
                    message="No repositories configured",
                    path=str(path),
                    suggestions=["Add at least one repository to repos.yaml"],
                )
            )
            return self.report

        # Validate each repo
        for i, repo in enumerate(repos):
            self._validate_repo(repo, f"{path}:repos[{i}]")

        return self.report

    def _validate_repo(self, repo: Any, path: str) -> None:
        """Validate a single repository entry.

        Args:
            repo: Repository configuration dict
            path: Path for error messages
        """
        if not isinstance(repo, dict):
            self.report.add_result(
                ValidationResult(
                    valid=False,
                    message="Repository entry must be a dictionary",
                    path=path,
                )
            )
            return

        # Check required fields
        for field in self.REQUIRED_REPO_FIELDS:
            if field not in repo or not repo[field]:
                self.report.add_result(
                    ValidationResult(
                        valid=False,
                        message=f"Missing required field: {field}",
                        path=path,
                        suggestions=[f"Add '{field}: <value>' to this repository entry"],
                    )
                )

        # Validate name format
        name = repo.get("name", "")
        if name and not self._is_valid_name(name):
            self.report.add_result(
                ValidationResult(
                    valid=False,
                    message=f"Invalid repository name: {name}",
                    path=f"{path}:name",
                    suggestions=[
                        "Use lowercase letters, numbers, and hyphens",
                        "Start with a letter",
                        "Example: my-awesome-repo",
                    ],
                )
            )

        # Validate path exists
        repo_path = repo.get("path", "")
        if repo_path and not Path(repo_path).exists():
            self.report.add_warning(
                ValidationResult(
                    valid=True,
                    message=f"Repository path does not exist: {repo_path}",
                    path=f"{path}:path",
                    suggestions=[
                        "Verify the path is correct",
                        "Create the directory if needed",
                    ],
                )
            )

        # Validate role
        role = repo.get("role")
        if role and role not in self.VALID_ROLES:
            self.report.add_warning(
                ValidationResult(
                    valid=True,
                    message=f"Unknown role: {role}",
                    path=f"{path}:role",
                    suggestions=[f"Valid roles: {', '.join(sorted(self.VALID_ROLES))}"],
                )
            )

        # Validate MCP type
        mcp = repo.get("mcp")
        if mcp and mcp not in self.VALID_MCP_TYPES:
            self.report.add_warning(
                ValidationResult(
                    valid=True,
                    message=f"Unknown MCP type: {mcp}",
                    path=f"{path}:mcp",
                    suggestions=[f"Valid types: {', '.join(self.VALID_MCP_TYPES)}"],
                )
            )

        # Validate tags
        tags = repo.get("tags", [])
        if tags is not None and not isinstance(tags, list):
            self.report.add_result(
                ValidationResult(
                    valid=False,
                    message="'tags' must be a list",
                    path=f"{path}:tags",
                )
            )

    def _is_valid_name(self, name: str) -> bool:
        """Check if a repository name is valid.

        Args:
            name: Repository name to validate

        Returns:
            True if valid, False otherwise
        """
        # Allow lowercase letters, numbers, and hyphens
        # Must start with a letter
        pattern = r"^[a-z][a-z0-9-]*$"
        return bool(re.match(pattern, name))

    def validate_settings_yaml(self, settings_path: str | Path) -> ConfigValidationReport:
        """Validate settings.yaml file.

        Args:
            settings_path: Path to settings.yaml

        Returns:
            Validation report
        """
        self.report = ConfigValidationReport(valid=True)
        path = Path(settings_path)

        if not path.exists():
            # Settings file is optional
            return self.report

        try:
            with open(path) as f:
                config = yaml.safe_load(f)
        except yaml.YAMLError as e:
            self.report.add_result(
                ValidationResult(
                    valid=False,
                    message=f"Invalid YAML syntax: {e}",
                    path=str(path),
                )
            )
            return self.report

        if config is None:
            return self.report

        if not isinstance(config, dict):
            self.report.add_result(
                ValidationResult(
                    valid=False,
                    message="Settings must be a dictionary",
                    path=str(path),
                )
            )

        return self.report


def validate_config(config_dir: str | Path | None = None) -> ConfigValidationReport:
    """Validate all configuration files.

    Args:
        config_dir: Configuration directory (default: settings/)

    Returns:
        Combined validation report
    """
    if config_dir is None:
        config_dir = Path("settings")
    else:
        config_dir = Path(config_dir)

    validator = ConfigValidator()
    combined_report = ConfigValidationReport(valid=True)

    # Validate repos.yaml
    repos_path = config_dir / "repos.yaml"
    if repos_path.exists():
        report = validator.validate_repos_yaml(repos_path)
        for result in report.results:
            combined_report.add_result(result)
        for warning in report.warnings:
            combined_report.add_warning(warning)

    # Validate settings
    for settings_file in ["mahavishnu.yaml", "local.yaml"]:
        settings_path = config_dir / settings_file
        if settings_path.exists():
            report = validator.validate_settings_yaml(settings_path)
            for result in report.results:
                combined_report.add_result(result)
            for warning in report.warnings:
                combined_report.add_warning(warning)

    return combined_report


class ConfigurationWizard:
    """Interactive configuration wizard."""

    def __init__(self, config_dir: str | Path = "settings") -> None:
        self.config_dir = Path(config_dir)
        self.repos: list[dict[str, Any]] = []

    def add_repository(
        self,
        name: str,
        path: str,
        role: str = "tool",
        tags: list[str] | None = None,
        description: str = "",
    ) -> None:
        """Add a repository to the configuration.

        Args:
            name: Repository name
            path: Repository path
            role: Repository role
            tags: Optional tags
            description: Optional description
        """
        repo = {
            "name": name,
            "path": path,
            "role": role,
        }
        if tags:
            repo["tags"] = tags
        if description:
            repo["description"] = description
        self.repos.append(repo)

    def save(self) -> Path:
        """Save configuration to repos.yaml.

        Returns:
            Path to saved file
        """
        self.config_dir.mkdir(parents=True, exist_ok=True)
        repos_path = self.config_dir / "repos.yaml"

        config = {"repos": self.repos}

        with open(repos_path, "w") as f:
            yaml.dump(config, f, default_flow_style=False, sort_keys=False)

        logger.info(f"Configuration saved to {repos_path}")
        return repos_path

    def create_default_config(self) -> Path:
        """Create a default configuration.

        Returns:
            Path to created file
        """
        self.repos = [
            {
                "name": "mahavishnu",
                "path": str(Path.cwd()),
                "role": "orchestrator",
                "tags": ["python", "orchestration", "core"],
                "description": "Mahavishnu orchestration platform",
                "mcp": "native",
            }
        ]
        return self.save()
