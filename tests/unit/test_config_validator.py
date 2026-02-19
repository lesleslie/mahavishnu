"""Tests for Configuration Validator Module.

Tests cover:
- Validation results
- Repository validation
- Settings validation
- Configuration wizard
"""

from __future__ import annotations

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
import tempfile
import yaml

from mahavishnu.core.config_validator import (
    ConfigValidator,
    ConfigValidationReport,
    ValidationResult,
    ConfigurationWizard,
    validate_config,
)


class TestValidationResult:
    """Test ValidationResult dataclass."""

    def test_valid_result(self) -> None:
        """Test valid result."""
        result = ValidationResult(valid=True, message="OK")
        assert result.valid is True
        assert result.message == "OK"
        assert result.suggestions == []

    def test_invalid_result(self) -> None:
        """Test invalid result with suggestions."""
        result = ValidationResult(
            valid=False,
            message="Error",
            path="/path/to/file",
            suggestions=["Try this", "Or this"],
        )
        assert result.valid is False
        assert result.path == "/path/to/file"
        assert len(result.suggestions) == 2

    def test_to_dict(self) -> None:
        """Test to_dict conversion."""
        result = ValidationResult(
            valid=False,
            message="Error",
            path="/path",
            suggestions=["Fix it"],
        )
        d = result.to_dict()

        assert d["valid"] is False
        assert d["message"] == "Error"
        assert d["path"] == "/path"
        assert d["suggestions"] == ["Fix it"]


class TestConfigValidationReport:
    """Test ConfigValidationReport."""

    def test_empty_report(self) -> None:
        """Test empty report is valid."""
        report = ConfigValidationReport(valid=True)
        assert report.valid is True
        assert report.results == []
        assert report.warnings == []

    def test_add_result(self) -> None:
        """Test adding results."""
        report = ConfigValidationReport(valid=True)
        report.add_result(ValidationResult(valid=True, message="OK"))

        assert len(report.results) == 1
        assert report.valid is True

    def test_add_result_invalidates(self) -> None:
        """Test adding invalid result invalidates report."""
        report = ConfigValidationReport(valid=True)
        report.add_result(ValidationResult(valid=False, message="Error"))

        assert report.valid is False

    def test_add_warning(self) -> None:
        """Test adding warnings."""
        report = ConfigValidationReport(valid=True)
        report.add_warning(ValidationResult(valid=True, message="Warning"))

        assert len(report.warnings) == 1
        assert report.valid is True  # Warnings don't invalidate

    def test_get_errors(self) -> None:
        """Test getting errors."""
        report = ConfigValidationReport(valid=True)
        report.add_result(ValidationResult(valid=True, message="OK"))
        report.add_result(ValidationResult(valid=False, message="Error"))
        report.add_result(ValidationResult(valid=False, message="Another error"))

        errors = report.get_errors()
        assert len(errors) == 2

    def test_to_dict(self) -> None:
        """Test to_dict conversion."""
        report = ConfigValidationReport(valid=False)
        report.add_result(ValidationResult(valid=False, message="Error", path="/path"))
        report.add_warning(ValidationResult(valid=True, message="Warning"))

        d = report.to_dict()
        assert d["valid"] is False
        assert len(d["errors"]) == 1
        assert len(d["warnings"]) == 1


class TestConfigValidator:
    """Test ConfigValidator."""

    @pytest.fixture
    def validator(self) -> ConfigValidator:
        """Create validator."""
        return ConfigValidator()

    @pytest.fixture
    def temp_dir(self, tmp_path: Path) -> Path:
        """Create temp directory."""
        return tmp_path

    def test_validate_missing_file(self, validator: ConfigValidator, temp_dir: Path) -> None:
        """Test validating missing file."""
        report = validator.validate_repos_yaml(temp_dir / "missing.yaml")
        assert report.valid is False
        assert "not found" in report.results[0].message.lower()

    def test_validate_invalid_yaml(self, validator: ConfigValidator, temp_dir: Path) -> None:
        """Test validating invalid YAML."""
        yaml_path = temp_dir / "repos.yaml"
        yaml_path.write_text("invalid: yaml: content: [")

        report = validator.validate_repos_yaml(yaml_path)
        assert report.valid is False
        assert "yaml" in report.results[0].message.lower()

    def test_validate_non_dict_config(self, validator: ConfigValidator, temp_dir: Path) -> None:
        """Test validating non-dict config."""
        yaml_path = temp_dir / "repos.yaml"
        yaml_path.write_text("- item1\n- item2")

        report = validator.validate_repos_yaml(yaml_path)
        assert report.valid is False
        assert "dictionary" in report.results[0].message.lower()

    def test_validate_non_list_repos(self, validator: ConfigValidator, temp_dir: Path) -> None:
        """Test validating non-list repos."""
        yaml_path = temp_dir / "repos.yaml"
        yaml_path.write_text("repos:\n  not: a list")

        report = validator.validate_repos_yaml(yaml_path)
        assert report.valid is False
        assert "list" in report.results[0].message.lower()

    def test_validate_empty_repos(self, validator: ConfigValidator, temp_dir: Path) -> None:
        """Test validating empty repos list."""
        yaml_path = temp_dir / "repos.yaml"
        yaml_path.write_text("repos: []")

        report = validator.validate_repos_yaml(yaml_path)
        assert report.valid is True  # Empty is valid, just warning
        assert len(report.warnings) == 1

    def test_validate_valid_repo(self, validator: ConfigValidator, temp_dir: Path) -> None:
        """Test validating valid repository."""
        yaml_path = temp_dir / "repos.yaml"
        yaml_path.write_text("""
repos:
  - name: test-repo
    path: /tmp/test
    role: tool
    tags: [python]
""")

        report = validator.validate_repos_yaml(yaml_path)
        # Valid structure, though path may not exist (warning)
        assert report.valid is True

    def test_validate_missing_required_field(self, validator: ConfigValidator, temp_dir: Path) -> None:
        """Test validating missing required field."""
        yaml_path = temp_dir / "repos.yaml"
        yaml_path.write_text("""
repos:
  - name: test-repo
    # missing path
""")

        report = validator.validate_repos_yaml(yaml_path)
        assert report.valid is False
        assert any("path" in r.message.lower() for r in report.results)

    def test_validate_invalid_name(self, validator: ConfigValidator, temp_dir: Path) -> None:
        """Test validating invalid repository name."""
        yaml_path = temp_dir / "repos.yaml"
        yaml_path.write_text("""
repos:
  - name: Invalid_Name!
    path: /tmp/test
""")

        report = validator.validate_repos_yaml(yaml_path)
        assert report.valid is False
        assert any("name" in r.message.lower() for r in report.results)

    def test_validate_unknown_role(self, validator: ConfigValidator, temp_dir: Path) -> None:
        """Test validating unknown role."""
        yaml_path = temp_dir / "repos.yaml"
        yaml_path.write_text("""
repos:
  - name: test-repo
    path: /tmp/test
    role: unknown-role
""")

        report = validator.validate_repos_yaml(yaml_path)
        # Unknown role is a warning, not error
        assert report.valid is True
        assert any("role" in w.message.lower() for w in report.warnings)

    def test_validate_non_dict_repo(self, validator: ConfigValidator, temp_dir: Path) -> None:
        """Test validating non-dict repo entry."""
        yaml_path = temp_dir / "repos.yaml"
        yaml_path.write_text("""
repos:
  - "not a dict"
""")

        report = validator.validate_repos_yaml(yaml_path)
        assert report.valid is False
        assert "dictionary" in report.results[0].message.lower()

    def test_validate_settings_yaml(self, validator: ConfigValidator, temp_dir: Path) -> None:
        """Test validating settings.yaml."""
        settings_path = temp_dir / "settings.yaml"
        settings_path.write_text("server_name: test\nport: 8080")

        report = validator.validate_settings_yaml(settings_path)
        assert report.valid is True

    def test_validate_settings_missing(self, validator: ConfigValidator, temp_dir: Path) -> None:
        """Test validating missing settings file."""
        report = validator.validate_settings_yaml(temp_dir / "missing.yaml")
        assert report.valid is True  # Missing is OK (optional)


class TestConfigurationWizard:
    """Test ConfigurationWizard."""

    @pytest.fixture
    def temp_dir(self, tmp_path: Path) -> Path:
        """Create temp directory."""
        return tmp_path

    def test_add_repository(self, temp_dir: Path) -> None:
        """Test adding repository."""
        wizard = ConfigurationWizard(temp_dir)
        wizard.add_repository(
            name="test-repo",
            path="/tmp/test",
            role="tool",
            tags=["python"],
            description="Test repo",
        )

        assert len(wizard.repos) == 1
        assert wizard.repos[0]["name"] == "test-repo"

    def test_save(self, temp_dir: Path) -> None:
        """Test saving configuration."""
        wizard = ConfigurationWizard(temp_dir)
        wizard.add_repository(name="test", path="/tmp/test")
        saved_path = wizard.save()

        assert saved_path.exists()
        assert saved_path.name == "repos.yaml"

        # Verify content
        with open(saved_path) as f:
            config = yaml.safe_load(f)
        assert "repos" in config
        assert len(config["repos"]) == 1

    def test_create_default_config(self, temp_dir: Path) -> None:
        """Test creating default configuration."""
        wizard = ConfigurationWizard(temp_dir)
        saved_path = wizard.create_default_config()

        assert saved_path.exists()
        assert len(wizard.repos) == 1
        assert wizard.repos[0]["name"] == "mahavishnu"
        assert wizard.repos[0]["role"] == "orchestrator"


class TestValidateConfig:
    """Test validate_config function."""

    @pytest.fixture
    def temp_dir(self, tmp_path: Path) -> Path:
        """Create temp directory."""
        return tmp_path

    def test_validate_empty_dir(self, temp_dir: Path) -> None:
        """Test validating empty directory."""
        report = validate_config(temp_dir)
        assert report.valid is True  # No files to validate

    def test_validate_with_valid_files(self, temp_dir: Path) -> None:
        """Test validating with valid files."""
        repos_path = temp_dir / "repos.yaml"
        repos_path.write_text("""
repos:
  - name: test-repo
    path: /tmp/test
""")

        report = validate_config(temp_dir)
        assert report.valid is True
