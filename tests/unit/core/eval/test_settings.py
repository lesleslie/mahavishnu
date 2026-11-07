"""Contract tests for the eval settings (REQ-EVAL-006).

Validates:

- the Phase 1 dogfood defaults on a bare ``EvalSettings``;
- that unknown keys are refused (Pydantic v2 ``ConfigDict``, not v1
  ``class Config``);
- that the env var form ``MAHAVISHNU_EVAL__<FIELD>`` overrides the nested
  field through the parent's ``env_nested_delimiter``;
- that the committed YAML block declares exactly the model's fields.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError
import pytest
import yaml

from mahavishnu.core.config import MahavishnuSettings
from mahavishnu.core.eval.settings import EvalSettings, get_eval_settings

REPO_ROOT = Path(__file__).resolve().parents[4]


@pytest.mark.req(["REQ-EVAL-006"])
def test_defaults_match_the_phase1_dogfood_profile() -> None:
    """A bare EvalSettings carries the Phase 1 dogfood defaults."""
    settings = EvalSettings()
    assert settings.enabled is False
    assert settings.default_storage == "mahavishnu.sqlite"
    assert settings.default_dataset_loader == "mahavishnu.jsonl"
    assert settings.default_scorers == ["mahavishnu.contains"]
    assert settings.default_model_backend == "mahavishnu.mock"
    assert settings.cost_budget_per_run == 5.0
    assert settings.db_path.endswith("eval/runs.sqlite")


@pytest.mark.req(["REQ-EVAL-006"])
def test_unknown_keys_are_rejected() -> None:
    """Extra keys are refused (Pydantic v2 ConfigDict, not v1 class Config)."""
    with pytest.raises(ValidationError):
        # The unknown key is the point of the test: the model is
        # configured to forbid extra fields, and this call is what
        # proves it. The type checker cannot know that.
        EvalSettings(not_a_real_field=1)  # ty: ignore[unknown-argument]


@pytest.mark.req(["REQ-EVAL-006"])
def test_env_override_uses_the_nested_delimiter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MAHAVISHNU_EVAL__COST_BUDGET_PER_RUN overrides the nested field."""
    monkeypatch.setenv("MAHAVISHNU_EVAL__COST_BUDGET_PER_RUN", "42.0")
    settings = MahavishnuSettings()
    assert settings.eval.cost_budget_per_run == 42.0


@pytest.mark.req(["REQ-EVAL-006"])
def test_get_eval_settings_returns_the_nested_settings() -> None:
    """get_eval_settings() reads the eval field off the settings cache."""
    assert isinstance(get_eval_settings(), EvalSettings)


@pytest.mark.req(["REQ-EVAL-006"])
def test_yaml_block_declares_exactly_the_model_fields() -> None:
    """settings/mahavishnu.yaml's eval block matches the model's fields."""
    yaml_path = REPO_ROOT / "settings" / "mahavishnu.yaml"
    data = yaml.safe_load(yaml_path.read_text())
    assert set(data["eval"]) == set(EvalSettings.model_fields)


@pytest.mark.req(["REQ-EVAL-006"])
def test_yaml_values_agree_with_the_model_defaults() -> None:
    """The committed YAML block and the model defaults do not drift.

    The comparison is between the *file* and the model's defaults, not
    between the file and ``get_eval_settings()``. The latter is the
    process-wide **merged** settings -- YAML, then the gitignored
    ``settings/local.yaml``, then ``~/.config/mahavishnu/*``, then the
    environment. An operator who configures eval the way the feature
    is designed to be configured gets a merged value that differs from
    the committed default, and the test would fail on a change that has
    nothing to do with eval. The neighbouring test already does this
    drift check the right way, against the file.
    """
    yaml_path = REPO_ROOT / "settings" / "mahavishnu.yaml"
    data = yaml.safe_load(yaml_path.read_text())
    defaults = EvalSettings().model_dump()
    for key, value in data["eval"].items():
        assert value == defaults[key], f"settings/mahavishnu.yaml: eval.{key} drifted"
