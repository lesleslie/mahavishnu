"""Tests for the model-id resolver in ``mahavishnu.core.model_routing``.

``resolve_model_id`` answers "which model id does the worker use for this
task category, and is that id one the operator actually configured?". The
drift check is a warning, never an exception: the routing decision still
stands when the configuration cannot be read.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from mahavishnu.core.model_routing import (
    DEFAULT_MINIMAX_ROUTING,
    MODELS_CONFIG_PATH,
    TaskCategory,
    resolve_model_id,
)

if TYPE_CHECKING:
    from pathlib import Path

#: A models.yaml whose only configured model is the flash model — the
#: stable "MiniMax-M3" is deliberately absent so the drift check fires.
_CONFIG_WITHOUT_STABLE_MODEL = """
default_provider: "minimax"
minimax:
  enabled: true
  task_routing:
    CODE_GENERATION: "MiniMax-M3.1-Flash"
    SWARM: "MiniMax-M3.1-Flash"
"""

#: A models.yaml that configures the stable model, as the shipped file does.
_CONFIG_WITH_STABLE_MODEL = """
default_provider: "minimax"
minimax:
  enabled: true
  task_routing:
    CODE_GENERATION: "MiniMax-M3"
llama_server:
  enabled: true
  task_routing:
    GENERAL: "qwen3.5"
"""


def _write_config(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "models.yaml"
    path.write_text(body, encoding="utf-8")
    return path


class TestResolveModelId:
    """The resolved id must match the worker's routing table."""

    def test_returns_model_from_routing_table(self):
        """A category with an entry resolves to that entry's model id."""
        assert resolve_model_id(TaskCategory.CODE_GENERATION) == "MiniMax-M3"

    def test_latency_categories_resolve_to_flash_model(self):
        """Latency-sensitive categories resolve to the flash model."""
        assert resolve_model_id(TaskCategory.SWARM) == "MiniMax-M3.1-Flash"
        assert resolve_model_id(TaskCategory.QUICK) == "MiniMax-M3.1-Flash"

    def test_every_category_resolves_to_a_model(self):
        """No category resolves to an empty model id."""
        for category in TaskCategory:
            assert resolve_model_id(category)

    def test_shipped_config_does_not_warn(self, caplog):
        """The repository's own models.yaml configures the resolved ids."""
        with caplog.at_level(logging.WARNING):
            resolve_model_id(TaskCategory.CODE_GENERATION, config_path=MODELS_CONFIG_PATH)
        assert caplog.records == []

    def test_configured_ids_come_from_every_provider(self, tmp_path, caplog):
        """Model ids configured by any provider count as configured."""
        config = _write_config(tmp_path, _CONFIG_WITH_STABLE_MODEL)
        with caplog.at_level(logging.WARNING):
            resolve_model_id(TaskCategory.CODE_GENERATION, config_path=config)
        assert caplog.records == []

    def test_model_absent_from_configured_routing_warns(self, tmp_path, caplog):
        """A model id no provider block names is reported as a warning."""
        config = _write_config(tmp_path, _CONFIG_WITHOUT_STABLE_MODEL)
        with caplog.at_level(logging.WARNING):
            model = resolve_model_id(TaskCategory.CODE_GENERATION, config_path=config)

        assert model == "MiniMax-M3"
        assert len(caplog.records) == 1
        record = caplog.records[0]
        assert record.levelno == logging.WARNING
        assert "MiniMax-M3" in record.getMessage()
        assert "code_generation" in record.getMessage()

    def test_flash_model_absent_from_configured_routing_warns(self, tmp_path, caplog):
        """The drift check covers every category, not just the first."""
        config = _write_config(tmp_path, _CONFIG_WITHOUT_STABLE_MODEL)
        with caplog.at_level(logging.WARNING):
            model = resolve_model_id(TaskCategory.SWARM, config_path=config)

        assert model == "MiniMax-M3.1-Flash"
        assert caplog.records == []

    def test_missing_config_file_returns_model_and_warns(self, tmp_path, caplog):
        """An unreadable configuration is reported, not raised."""
        missing = tmp_path / "absent.yaml"
        with caplog.at_level(logging.WARNING):
            model = resolve_model_id(TaskCategory.CODE_GENERATION, config_path=missing)

        assert model == "MiniMax-M3"
        assert len(caplog.records) == 1
        assert "Could not read model routing config" in caplog.records[0].getMessage()

    def test_unparseable_config_returns_model_and_warns(self, tmp_path, caplog):
        """A malformed configuration is reported, not raised."""
        config = _write_config(tmp_path, ": broken: yaml: {{")
        with caplog.at_level(logging.WARNING):
            model = resolve_model_id(TaskCategory.CODE_GENERATION, config_path=config)

        assert model == "MiniMax-M3"
        assert len(caplog.records) == 1
        assert "Could not read model routing config" in caplog.records[0].getMessage()

    def test_non_mapping_config_returns_model_and_warns(self, tmp_path, caplog):
        """A configuration that is not a mapping is reported, not raised."""
        config = _write_config(tmp_path, "- just\n- a\n- list\n")
        with caplog.at_level(logging.WARNING):
            model = resolve_model_id(TaskCategory.CODE_GENERATION, config_path=config)

        assert model == "MiniMax-M3"
        assert len(caplog.records) == 1
        assert "is not a mapping" in caplog.records[0].getMessage()

    def test_empty_config_reports_every_model_as_unconfigured(self, tmp_path, caplog):
        """An empty configuration has no routing, so every model drifts."""
        config = _write_config(tmp_path, "")
        with caplog.at_level(logging.WARNING):
            model = resolve_model_id(TaskCategory.CODE_GENERATION, config_path=config)

        assert model == "MiniMax-M3"
        assert len(caplog.records) == 1
        assert "is not present in the routing configured in" in caplog.records[0].getMessage()


class TestRoutingTableCoverage:
    """The resolver and the worker's table must not drift apart."""

    def test_resolver_matches_routing_table(self):
        """Every category resolves to its routing-table entry."""
        for category, expected in DEFAULT_MINIMAX_ROUTING.items():
            assert resolve_model_id(category) == expected
