"""Unit tests for UnifiedConfig and ConfigValidationError.

Tests cover: valid config passes, Pydantic error surfaces, strict mode raises,
and YAML syntax failure is caught.
"""

from unittest.mock import patch

import pytest

from mahavishnu.core.unified_config import ConfigValidationError, UnifiedConfig


def _make_report(valid: bool = True, errors: list | None = None):
    """Build a minimal ConfigValidationReport mock."""
    from mahavishnu.core.config_validator import ConfigValidationReport, ValidationResult

    report = ConfigValidationReport(valid=valid)
    for msg in (errors or []):
        report.add_result(ValidationResult(valid=False, message=msg, path="settings/test.yaml"))
    return report


class TestUnifiedConfigValidate:
    def test_returns_valid_report_when_all_ok(self, tmp_path):
        # Create minimal valid YAML files
        (tmp_path / "repos.yaml").write_text("repos: []\n")
        (tmp_path / "mahavishnu.yaml").write_text("")
        (tmp_path / "models.yaml").write_text("providers: {}\n")
        (tmp_path / "embeddings.yaml").write_text("models: {}\n")

        with (
            patch("mahavishnu.core.unified_config.validate_config") as mock_vc,
            patch.object(UnifiedConfig, "_validate_pydantic_settings"),
        ):
            mock_vc.return_value = _make_report(valid=True)
            report = UnifiedConfig.validate(settings_dir=tmp_path)

        assert report.valid

    def test_pydantic_error_adds_result(self, tmp_path):

        with (
            patch("mahavishnu.core.unified_config.validate_config") as mock_vc,
            patch("mahavishnu.core.unified_config.UnifiedConfig._validate_pydantic_settings") as mock_ps,
        ):
            valid_report = _make_report(valid=True)
            mock_vc.return_value = valid_report

            def _add_error(report):
                from mahavishnu.core.config_validator import ValidationResult
                report.add_result(ValidationResult(valid=False, message="Bad field", path="settings/mahavishnu.yaml"))

            mock_ps.side_effect = _add_error
            report = UnifiedConfig.validate(settings_dir=tmp_path)

        assert not report.valid
        assert any("Bad field" in e.message for e in report.get_errors())

    def test_yaml_syntax_error_in_aux_file_is_caught(self, tmp_path):
        (tmp_path / "models.yaml").write_text(": broken: yaml: {{")

        with patch("mahavishnu.core.unified_config.validate_config") as mock_vc:
            mock_vc.return_value = _make_report(valid=True)
            report = UnifiedConfig.validate(settings_dir=tmp_path)

        # models.yaml has no required keys in _YAML_KEY_CHECKS, so only syntax is checked
        errors = report.get_errors()
        assert any("syntax" in e.message.lower() for e in errors)


class TestUnifiedConfigValidateStrict:
    def test_raises_config_validation_error_on_failure(self, tmp_path):
        with patch.object(UnifiedConfig, "validate") as mock_v:
            mock_v.return_value = _make_report(valid=False, errors=["Bad field value"])

            with pytest.raises(ConfigValidationError) as exc_info:
                UnifiedConfig.validate_strict(settings_dir=tmp_path)

        assert "Bad field value" in str(exc_info.value)
        assert exc_info.value.errors

    def test_does_not_raise_when_valid(self, tmp_path):
        with patch.object(UnifiedConfig, "validate") as mock_v:
            mock_v.return_value = _make_report(valid=True)
            UnifiedConfig.validate_strict(settings_dir=tmp_path)  # should not raise


class TestConfigValidationError:
    def test_carries_errors_list(self):
        exc = ConfigValidationError(["err1", "err2"], file_path="settings/foo.yaml")
        assert exc.errors == ["err1", "err2"]
        assert exc.file_path == "settings/foo.yaml"
        assert "2 config error(s)" in str(exc)

    def test_no_file_path(self):
        exc = ConfigValidationError(["single error"])
        assert exc.file_path is None
        assert "single error" in str(exc)
