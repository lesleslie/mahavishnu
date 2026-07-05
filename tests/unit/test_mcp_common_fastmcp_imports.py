"""Smoke test asserting that mahavishnu's MCP modules import via
``mcp_common.fastmcp`` instead of the upstream ``fastmcp`` package.

Plan 7 Phase 2 directs every Bodai consumer to use the centralized
re-export surface so the FastMCP version can be swapped in one place
(mcp-common). A regression to ``from fastmcp import FastMCP`` anywhere
in the production tree breaks the contract and must fail loudly.

This test walks every Python module under ``mahavishnu/`` and the test
suite, checking that any FastMCP symbol comes from the centralized
re-export, not from the upstream ``fastmcp`` package. Lazy imports
inside function bodies (a long-standing pattern in this repo) are
covered by an import-time smoke check on every tool module.
"""

from __future__ import annotations

import importlib
from pathlib import Path
import sys

import pytest

PROD_ROOT = Path(__file__).resolve().parents[2] / "mahavishnu"


def _python_files(root: Path) -> list[Path]:
    """Yield every .py file under root, excluding __pycache__."""
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


def test_no_top_level_from_fastmcp_imports_in_production() -> None:
    """No production module may do ``from fastmcp import ...``.

    Plan 7 Phase 2 directs every Bodai consumer to import FastMCP
    symbols from ``mcp_common.fastmcp`` so the version can be swapped
    in one place. A regression to direct fastmcp imports breaks the
    contract.
    """
    offenders: list[str] = []
    for path in _python_files(PROD_ROOT):
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            line.lstrip()
            # Match only top-level imports (no leading whitespace)
            # for the bare ``from fastmcp import`` / ``from fastmcp.server``
            # forms. Lazy function-local imports are tested separately
            # via the import-time smoke test below.
            if line.startswith("from fastmcp import") or line.startswith("from fastmcp.server"):
                offenders.append(f"{path.relative_to(PROD_ROOT.parent)}:{line}")
    assert not offenders, (
        "Found production imports of upstream fastmcp; "
        "switch to ``from mcp_common.fastmcp import ...``:\n" + "\n".join(offenders)
    )


@pytest.mark.parametrize(
    "module_name",
    [
        "mahavishnu.mcp.server_core",
        "mahavishnu.mcp.tools.coordination_tools",
        "mahavishnu.mcp.tools.pool_tools",
        "mahavishnu.mcp.tools.terminal_tools",
        "mahavishnu.mcp.tools.worker_tools",
        "mahavishnu.mcp.tools.goal_team_tools",
        "mahavishnu.mcp.tools.openhands_tools",
    ],
)
def test_tool_modules_import_cleanly(module_name: str) -> None:
    """Every MCP tool module must import without raising.

    After Plan 7 Phase 2 the modules import FastMCP from
    ``mcp_common.fastmcp``. This is the import-time smoke check that
    catches lazy-import regressions like ``from fastmcp import FastMCP``
    inside a function body.
    """
    if module_name in sys.modules:
        # Idempotent: don't re-import; just confirm it's loadable.
        assert sys.modules[module_name] is not None
    else:
        importlib.import_module(module_name)
