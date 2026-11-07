"""Tests for the operator-backed model routing loader.

``settings/models.yaml`` is the operator's source of truth for
task-to-model routing; the in-code ``DEFAULT_*_ROUTING`` tables are the
built-in fallback. These tests pin the precedence rules and the
degradation behaviour when the operator config is absent or broken.

See ``docs/plans/2026-11-05-yaml-backed-model-routing.md``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pytest

from mahavishnu.core.model_routing import (
    DEFAULT_MINIMAX_ROUTING,
    MODELS_CONFIG_PATH_ENV,
    TaskCategory,
    _reset_routing_cache,
    resolve_minimax_routing,
)

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture(autouse=True)
def _clean_routing_cache():
    """Reset the parsed operator config around every test."""
    _reset_routing_cache()
    yield
    _reset_routing_cache()


@pytest.fixture
def operator_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Return a writer that points the loader at a temporary config."""
    path = tmp_path / "models.yaml"

    def _write(body: str) -> Path:
        path.write_text(body, encoding="utf-8")
        monkeypatch.setenv(MODELS_CONFIG_PATH_ENV, str(path))
        _reset_routing_cache()
        return path

    return _write


def _config_for(model: str, *, extra: str = "") -> str:
    """Build a one-provider operator config naming ``model`` for every category."""
    lines = ["minimax:", "  task_routing:"]
    lines.extend(f"    {category.name}: {model!r}" for category in TaskCategory)
    if extra:
        lines.append(extra)
    return "\n".join(lines) + "\n"


def test_operator_config_wins_over_builtin(operator_config):
    """An operator value replaces the built-in route."""
    operator_config(_config_for("operator-model"))

    routing = resolve_minimax_routing()

    assert routing[TaskCategory.CODE_GENERATION] == "operator-model"


def test_omitted_category_keeps_builtin_route(operator_config):
    """A category the operator omits keeps its built-in route."""
    operator_config(
        'minimax:\n  task_routing:\n    CODE_GENERATION: "operator-model"\n'
    )

    routing = resolve_minimax_routing()

    assert routing[TaskCategory.CODE_GENERATION] == "operator-model"
    assert (
        routing[TaskCategory.EMBEDDING]
        == DEFAULT_MINIMAX_ROUTING[TaskCategory.EMBEDDING]
    )


def test_absent_config_falls_back_to_builtin(monkeypatch, tmp_path):
    """No operator config means the built-in tables serve unchanged."""
    monkeypatch.setenv(MODELS_CONFIG_PATH_ENV, str(tmp_path / "absent.yaml"))
    _reset_routing_cache()

    assert resolve_minimax_routing() == DEFAULT_MINIMAX_ROUTING


def test_unreadable_override_falls_back_to_builtin(monkeypatch, tmp_path, caplog):
    """A bad override degrades to the built-in table and says so."""
    monkeypatch.setenv(MODELS_CONFIG_PATH_ENV, str(tmp_path / "absent.yaml"))
    _reset_routing_cache()

    with caplog.at_level(logging.WARNING):
        routing = resolve_minimax_routing()

    assert routing == DEFAULT_MINIMAX_ROUTING
    assert any(
        MODELS_CONFIG_PATH_ENV in record.getMessage() for record in caplog.records
    )


def test_malformed_config_falls_back_to_builtin(operator_config, caplog):
    """A malformed config degrades to the built-in table and says so."""
    operator_config("minimax: [this is not: a mapping\n")

    with caplog.at_level(logging.WARNING):
        routing = resolve_minimax_routing()

    assert routing == DEFAULT_MINIMAX_ROUTING
    assert any(
        "Could not read model routing config" in record.getMessage()
        for record in caplog.records
    )


def test_fallback_meta_keys_are_ignored(operator_config):
    """``FALLBACK`` names no category and must not become a route."""
    operator_config(
        _config_for("operator-model", extra='    FALLBACK: "stable-model"\n')
    )

    routing = resolve_minimax_routing()

    assert set(routing) == set(TaskCategory)
    assert "stable-model" not in routing.values()


def test_lowercase_keys_are_accepted(operator_config):
    """The enum's lowercase values are accepted as keys too."""
    operator_config(
        'minimax:\n  task_routing:\n    code_generation: "operator-model"\n'
    )

    assert resolve_minimax_routing()[TaskCategory.CODE_GENERATION] == "operator-model"


def test_empty_model_id_is_ignored(operator_config):
    """An empty model id is dropped, not routed to."""
    operator_config('minimax:\n  task_routing:\n    CODE_GENERATION: ""\n')

    routing = resolve_minimax_routing()

    assert (
        routing[TaskCategory.CODE_GENERATION]
        == DEFAULT_MINIMAX_ROUTING[TaskCategory.CODE_GENERATION]
    )


def test_config_edit_is_picked_up_without_a_restart(operator_config):
    """Editing the operator config takes effect on the next read.

    The loader re-parses when the file's change-detector moves, so an
    operator's edit lands without a process restart.
    """
    path = operator_config(_config_for("first-model"))
    assert resolve_minimax_routing()[TaskCategory.CODE_GENERATION] == "first-model"

    # Same path, different content of a different length, so the
    # change-detector (mtime, size) necessarily moves.
    path.write_text(_config_for("second-model-longer"), encoding="utf-8")
    assert (
        resolve_minimax_routing()[TaskCategory.CODE_GENERATION] == "second-model-longer"
    )
