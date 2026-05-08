"""UnifiedConfig — cross-file schema validation for all Mahavishnu config files.

Covers five YAML files: mahavishnu.yaml, local.yaml, models.yaml, embeddings.yaml,
and repos.yaml / ecosystem.yaml. Extends the existing ConfigValidator with
Pydantic-level validation of MahavishnuSettings.

Design doc: docs/plans/2026-05-07-unified-config-design.md
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from .config_validator import ConfigValidationReport, ValidationResult, validate_config

logger = logging.getLogger(__name__)

_YAML_KEY_CHECKS: dict[str, list[str]] = {
    "models.yaml": [],
    "embeddings.yaml": [],
}


class ConfigValidationError(Exception):
    """Raised by UnifiedConfig.validate_strict() when any error is found."""

    def __init__(self, errors: list[str], file_path: str | None = None) -> None:
        self.errors = errors
        self.file_path = file_path
        summary = f"{len(errors)} config error(s)"
        if file_path:
            summary += f" in {file_path}"
        super().__init__(f"{summary}: {'; '.join(errors[:3])}")


class UnifiedConfig:
    """Cross-file schema validation for all Mahavishnu configuration files.

    Usage:
        report = UnifiedConfig.validate()
        if not report.valid:
            for err in report.get_errors():
                print(err.message)

        # Strict mode (raises on any error):
        UnifiedConfig.validate_strict()
    """

    @classmethod
    def validate(cls, settings_dir: Path = Path("settings")) -> ConfigValidationReport:
        """Run validation across all five config files.

        Returns a ConfigValidationReport. Errors are non-fatal — callers
        decide whether to raise or log.
        """
        # Start with the existing YAML-structure checks
        report = validate_config(config_dir=settings_dir)

        # Extend with Pydantic-level MahavishnuSettings validation
        cls._validate_pydantic_settings(report)

        # Check auxiliary YAML files for syntax and key presence
        for filename, required_keys in _YAML_KEY_CHECKS.items():
            path = settings_dir / filename
            if path.exists():
                cls._validate_yaml_file(path, required_keys, report)

        return report

    @classmethod
    def validate_strict(cls, settings_dir: Path = Path("settings")) -> None:
        """Run validation and raise ConfigValidationError if any error is found.

        This is the startup hook used when MAHAVISHNU_UNIFIED_VALIDATION_ENABLED=true.
        """
        report = cls.validate(settings_dir)
        errors = report.get_errors()
        if errors:
            messages = [f"{e.path}: {e.message}" if e.path else e.message for e in errors]
            first_path = errors[0].path or None
            raise ConfigValidationError(messages, file_path=first_path)

    @staticmethod
    def _validate_pydantic_settings(report: ConfigValidationReport) -> None:
        """Attempt to load MahavishnuSettings via Pydantic and capture any ValidationError."""
        try:
            from pydantic import ValidationError as PydanticValidationError

            from .config import MahavishnuSettings

            MahavishnuSettings()
        except ImportError:
            pass  # pydantic_settings not available — skip
        except Exception as exc:
            # PydanticValidationError or similar
            from pydantic import ValidationError as PydanticValidationError

            if isinstance(exc, PydanticValidationError):
                for error in exc.errors():
                    field_path = " → ".join(str(p) for p in error["loc"])
                    report.add_result(
                        ValidationResult(
                            valid=False,
                            message=f"{error['msg']} (type={error['type']})",
                            path=f"settings/mahavishnu.yaml#{field_path}",
                        )
                    )
            else:
                report.add_result(
                    ValidationResult(
                        valid=False,
                        message=f"Settings load failed: {exc}",
                        path="settings/mahavishnu.yaml",
                    )
                )

    @staticmethod
    def _validate_yaml_file(
        path: Path,
        required_keys: list[str],
        report: ConfigValidationReport,
    ) -> None:
        """Validate syntax and optional required top-level keys in a YAML file."""
        try:
            content: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            report.add_result(
                ValidationResult(
                    valid=False,
                    message=f"Invalid YAML syntax: {exc}",
                    path=str(path),
                )
            )
            return

        if content is not None and not isinstance(content, dict):
            report.add_result(
                ValidationResult(
                    valid=False,
                    message="Expected a YAML mapping (dict) at the top level",
                    path=str(path),
                )
            )
            return

        for key in required_keys:
            if content is None or key not in content:
                report.add_result(
                    ValidationResult(
                        valid=False,
                        message=f"Required key '{key}' missing",
                        path=str(path),
                        suggestions=[f"Add '{key}:' to {path.name}"],
                    )
                )
