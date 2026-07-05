"""Regression test: Agno config classes must be the SAME class in both modules.

Background
----------
The Agno config schema (LLMProvider, MemoryBackend, AgnoLLMConfig,
AgnoMemoryConfig, AgnoToolsConfig, AgnoAdapterConfig) lived as duplicates
in `mahavishnu.core.config` AND `mahavishnu.engines.agno_adapter_impl`.
Python sees duplicate class definitions as distinct objects, so
`isinstance(config.agno, AgnoAdapterConfig)` always failed when the
engine's local AgnoAdapterConfig was on the right-hand side. That caused
`AgnoAdapter._get_agno_config` to silently fall through to the engine's
default `AgnoAdapterConfig()` (provider=ollama) instead of the user's
configured values (provider=minimax).

See docs/followups/2026-06-29-agno-adapter-config-field-path.md for full context.

This test fails fast if anyone re-introduces a duplicate.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
ENGINE_FILE = REPO_ROOT / "mahavishnu" / "engines" / "agno_adapter_impl.py"
CONFIG_FILE = REPO_ROOT / "mahavishnu" / "core" / "config.py"

CANONICAL_CLASSES = (
    "LLMProvider",
    "MemoryBackend",
    "AgnoLLMConfig",
    "AgnoMemoryConfig",
    "AgnoToolsConfig",
    "AgnoAdapterConfig",
)


def _class_names_defined_in(path: Path) -> set[str]:
    """Return names of top-level classes defined in a Python file."""
    tree = ast.parse(path.read_text())
    return {node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)}


def test_engine_does_not_duplicate_canonical_agno_classes() -> None:
    """No canonical Agno config class should be re-defined in the engine module.

    The engine should import these from `mahavishnu.core.config`. Re-defining
    them creates a duplicate class object that breaks isinstance checks.
    """
    engine_classes = _class_names_defined_in(ENGINE_FILE)
    duplicates = sorted(set(CANONICAL_CLASSES) & engine_classes)
    assert not duplicates, (
        f"Engine defines duplicate(s) of canonical Agno config class(es): "
        f"{duplicates}. These should be imported from "
        f"`mahavishnu.core.config`, not re-defined. See "
        f"docs/followups/2026-06-29-agno-adapter-config-field-path.md."
    )


@pytest.mark.parametrize("cls_name", CANONICAL_CLASSES)
def test_canonical_class_is_identity_equal_across_modules(cls_name: str) -> None:
    """The class object loaded from each module must be the SAME object.

    This catches the bug at the type-system level: if anyone re-introduces
    the duplicate, `isinstance(config.agno, AgnoAdapterConfig)` will return
    False even when `config.agno` looks like an AgnoAdapterConfig.
    """
    from mahavishnu.core import config as config_module
    from mahavishnu.engines import agno_adapter_impl as engine_module

    config_cls = getattr(config_module, cls_name, None)
    engine_cls = getattr(engine_module, cls_name, None)

    assert config_cls is not None, f"{cls_name} not found in mahavishnu.core.config"
    assert engine_cls is not None, (
        f"{cls_name} not importable from mahavishnu.engines.agno_adapter_impl. "
        f"Did the import statement get removed?"
    )
    assert config_cls is engine_cls, (
        f"{cls_name} is a DIFFERENT class in the two modules "
        f"(id {id(config_cls)} vs {id(engine_cls)}). The engine must import "
        f"from mahavishnu.core.config, not re-define."
    )


def test_agno_adapter_sees_user_configured_provider() -> None:
    """End-to-end: AgnoAdapter built from MahavishnuSettings picks up local.yaml.

    This is the user-facing behavior the duplicate-class bug broke:
    setting `agno.llm.provider: minimax` in local.yaml should propagate to
    `adapter.agno_config.llm.provider`.
    """
    from mahavishnu.core.config import MahavishnuSettings
    from mahavishnu.engines.agno_adapter_impl import AgnoAdapter

    settings = MahavishnuSettings()
    adapter = AgnoAdapter(config=settings)

    assert adapter.agno_config is settings.agno, (
        "_get_agno_config must return the user-configured AgnoAdapterConfig "
        "from MahavishnuSettings.agno, not construct a default."
    )
    # local.yaml at /Users/les/Projects/mahavishnu/settings/local.yaml sets
    # `agno.llm.provider: minimax`. With the fix, this propagates; before the
    # fix, this would be LLMProvider.OLLAMA.
    assert adapter.agno_config.llm.provider.value == "minimax", (
        f"Expected provider=minimax from local.yaml, got "
        f"{adapter.agno_config.llm.provider.value}. The duplicate-class bug "
        f"is back — _get_agno_config is returning the engine's default instead "
        f"of the user-configured value."
    )
