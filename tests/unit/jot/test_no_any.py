"""Static check: no Any in MCP tool I/O (TD-B1, CLAUDE.md hard limit)."""
from __future__ import annotations

import inspect
from pathlib import Path
import re

import pytest

from mahavishnu.mcp.tools import jot_tools

JOT_TOOLS = [
    jot_tools.jot_list,
    jot_tools.jot_show,
    jot_tools.jot_add,
    jot_tools.jot_edit,
    jot_tools.jot_done,
    jot_tools.jot_reopen,
    jot_tools.jot_vitals,
    jot_tools.jot_search,
]


@pytest.mark.parametrize("tool", JOT_TOOLS, ids=lambda t: t.name)
def test_tool_signature_has_no_any(tool) -> None:  # type: ignore[no-untyped-def]
    """No Any in params or return type."""
    # Use `.fn` to get the underlying callable (FunctionTool wraps it).
    sig = inspect.signature(tool.fn)
    for name, param in sig.parameters.items():
        if param.annotation is inspect.Parameter.empty:
            pytest.fail(f"{tool.name}: parameter {name!r} has no annotation")
        if "Any" in str(param.annotation):
            pytest.fail(f"{tool.name}: parameter {name!r} annotated with Any")
    if sig.return_annotation is inspect.Signature.empty:
        pytest.fail(f"{tool.name}: missing return annotation")
    if "Any" in str(sig.return_annotation):
        pytest.fail(f"{tool.name}: return type annotated with Any: {sig.return_annotation}")


def test_no_any_in_jot_tools_source() -> None:
    """Belt-and-braces: no `Any` literal in the jot_tools.py source."""
    src = Path(jot_tools.__file__).read_text(encoding="utf-8")
    # Strip comments + docstrings to avoid false positives on the word "any".
    cleaned = re.sub(r"#.*", "", src)
    cleaned = re.sub(r'"""[\s\S]*?"""', "", cleaned)
    cleaned = re.sub(r"'''[\s\S]*?'''", "", cleaned)
    assert "Any" not in cleaned, "jot_tools.py must not contain 'Any' in type annotations"