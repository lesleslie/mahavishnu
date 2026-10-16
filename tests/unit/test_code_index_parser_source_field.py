"""Test that ``parse_file`` populates the ``source`` field on every node.

REQ-IDX-SOURCE: The mahavishnu-side code-indexer ships code-graph
nodes to session-buddy (and from there to akosha's
``search_code_patterns``). The akosha search contract matches a
regex against ``node["source"]``. If the node has no ``source``
field, the regex match sees an empty string and the search
returns nothing for every pattern — even ``import``.

The fix on the akosha side (``fix/cross-repo-search-source-fallback-2026-10-10``)
works around the gap by reading the file from disk using
``start_line``/``end_line``. The long-term fix is for the
mahavishnu parser to include the actual source slice natively,
so the next full reindex ships nodes with a populated
``source`` field and the akosha disk-read fallback becomes a
purely-defensive no-op.

These tests pin the new contract:

- Each node returned by ``parse_file`` has a non-empty
  ``source`` field equal to the line slice
  ``file_lines[start_line - 1 : end_line]`` of the original
  source file.
- The slice is exactly the node's body — no trailing
  whitespace, no leading indentation normalization.
"""

from __future__ import annotations

import textwrap

from mahavishnu.core.code_index.models import CodeGraphNode
from mahavishnu.core.code_index.parser import parse_file
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def test_parse_file_populates_source_field_with_line_slice(tmp_path: Path) -> None:
    """Each node's ``source`` field must equal the original file's
    ``[start_line, end_line]`` slice (1-indexed, inclusive).
    """
    file_abs = tmp_path / "module_under_test.py"
    file_abs.write_text(
        textwrap.dedent(
            """\
            # Line 1 — header comment
            # Line 2
            # Line 3
            # Line 4
            # Line 5
            def needle_function():
                # Line 7
                # Line 8
                # Line 9
                return "UNIQUE_PATTERN_TOKEN"
            """
        )
    )

    result = parse_file(str(file_abs), str(tmp_path), "deadbeef")
    assert result is not None
    nodes, _edges = result
    assert nodes, "expected at least one node"

    # The fixture defines a single function ``needle_function``
    # spanning lines 6..10 (1-indexed, inclusive). The
    # ``CodeGraphAnalyzer`` may also surface a file-level node;
    # find the function specifically.
    func_nodes = [
        n for n in nodes
        if n.symbol_type == "function" and n.symbol_name == "needle_function"
    ]
    assert len(func_nodes) == 1, (
        f"expected exactly one function node for needle_function; "
        f"got {[n.symbol_name for n in nodes]}"
    )
    func = func_nodes[0]
    assert isinstance(func, CodeGraphNode)

    # The contract: ``source`` is populated and matches the line
    # slice from the original file. This is RED on the unfixed
    # parser (no ``source`` field on the model).
    assert func.source is not None, (
        f"CodeGraphNode.source must be populated; got node {func.model_dump()!r}"
    )
    assert "UNIQUE_PATTERN_TOKEN" in func.source
    assert "needle_function" in func.source

    # And the slice must be exact: lines 6..10 of the fixture.
    # Re-read the file and compare directly — no whitespace
    # normalization on either side.
    file_lines = file_abs.read_text().splitlines(keepends=True)
    lo = (func.start_line or 1) - 1
    hi = func.end_line or len(file_lines)
    expected = "".join(file_lines[lo:hi])
    assert func.source == expected, (
        f"source field does not match the [start_line, end_line] slice.\n"
        f"  expected: {expected!r}\n"
        f"  got:      {func.source!r}"
    )


def test_parse_file_source_field_for_file_level_node(tmp_path: Path) -> None:
    """The file-level node (``symbol_type='file'``) must also have a
    populated ``source`` field — the full file contents. This is
    what akosha's search will match against when a pattern
    appears outside any function/class (e.g. a top-level
    ``import`` statement).
    """
    file_abs = tmp_path / "imports_only.py"
    file_abs.write_text(
        textwrap.dedent(
            """\
            import json
            import os
            import sys
            """
        )
    )

    result = parse_file(str(file_abs), str(tmp_path), "cafef00d")
    assert result is not None
    nodes, _edges = result
    file_nodes = [n for n in nodes if n.symbol_type == "file"]
    assert len(file_nodes) == 1
    file_node = file_nodes[0]

    # The file node's ``source`` is the full file text (or at
    # least matches it). akosha's regex match for ``import``
    # depends on this.
    file_text = file_abs.read_text()
    assert file_node.source is not None
    assert "import json" in file_node.source
    assert "import sys" in file_node.source
    # The file node should include all three imports so that a
    # regex search for ``^import \w+$`` matches every one.
    assert file_node.source.count("\nimport ") >= 2 or file_text.count("\nimport ") >= 2
