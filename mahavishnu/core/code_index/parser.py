"""Parse Python source files into code graph nodes and edges using mcp-common."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
import logging
from pathlib import Path
import subprocess
from typing import TYPE_CHECKING

from mahavishnu.core.code_index.models import CodeGraphEdge, CodeGraphNode
from mahavishnu.core.code_index.signature_redaction import redact_signature

if TYPE_CHECKING:  # pragma: no cover
    from typing import Any

logger = logging.getLogger(__name__)

PARSABLE_EXTENSIONS = {".py"}
SKIP_DIRS = {
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    "node_modules",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "htmlcov",
    "dist",
    "build",
    ".eggs",
    ".tox",
}

# Symbol types recognised by CodeGraphNode.symbol_type.
_ALLOWED_NODE_TYPES = {"function", "class", "module", "file", "variable"}


def _resolve_node_source(
    node_type: str,
    start_line: int | None,
    end_line: int | None,
    file_lines: list[str] | None,
) -> str | None:
    """Resolve the verbatim ``source`` slice for a single node.

    Returns ``None`` when the slice can't be reconstructed (missing
    file, missing line numbers, etc.); the caller leaves the
    field empty and the akosha search has a disk-read fallback
    for those.
    """
    if node_type == "file":
        # File-level nodes have no ``start_line``/``end_line``;
        # the full file is the searchable source.
        if file_lines is not None:
            return "".join(file_lines)
        return None

    if file_lines is None or not start_line or not end_line:
        return None

    # ``start_line``/``end_line`` are 1-indexed inclusive; convert
    # to slice indices. Clamp ``end_line`` to the file length so a
    # stale ``end_line`` from the parser can't ``IndexError``.
    lo = max(0, int(start_line) - 1)
    hi = min(len(file_lines), int(end_line))
    return "".join(file_lines[lo:hi])


def _extract_node_metadata(
    node: Any,
) -> tuple[str | None, int | None, int | None, int | None]:
    """Return ``(signature, complexity, start_line, end_line)`` for
    a parsed node based on its ``symbol_type``. Returns ``None`` for
    every field that doesn't apply to the node type.
    """
    if node.node_type == "function":
        return (
            redact_signature(getattr(node, "docstring", None)),
            getattr(node, "complexity", 1),
            getattr(node, "start_line", None),
            getattr(node, "end_line", None),
        )
    if node.node_type == "class":
        return (None, None, getattr(node, "start_line", None), getattr(node, "end_line", None))
    return (None, None, None, None)


def parse_file(
    file_path: str,
    repo_path: str,
    commit_hash: str,
) -> tuple[list[CodeGraphNode], list[CodeGraphEdge]] | None:
    """Parse a single file into graph nodes and edges.

    Returns None if the file is not parseable (wrong extension, skip dir, etc.).
    Raises on actual parse failures (caller handles).
    """
    path = Path(file_path)

    if path.suffix not in PARSABLE_EXTENSIONS:
        return None

    if any(skip_dir in path.parts for skip_dir in SKIP_DIRS):
        return None

    try:
        import asyncio

        from mcp_common.code_graph.analyzer import CodeGraphAnalyzer

        analyzer = CodeGraphAnalyzer(Path(repo_path))
        # _analyze_python_file populates analyzer.nodes but returns None
        asyncio.run(analyzer._analyze_python_file(path))
        result_nodes = list(analyzer.nodes.values())
    except Exception as e:
        logger.warning(f"Parse failure for {file_path}: {e}")
        raise

    # Read the file once so each node's ``source`` field can be
    # populated with the verbatim line slice. A missing/unreadable
    # file leaves ``source=None`` on every node; the akosha search
    # has a disk-read fallback that reconstructs from
    # ``start_line``/``end_line`` in that case.
    try:
        with path.open(encoding="utf-8") as _src_fh:
            file_lines: list[str] | None = _src_fh.readlines()
    except OSError as _e:
        logger.debug(f"Could not read {path} for source slice: {_e}")
        file_lines = None

    nodes: list[CodeGraphNode] = []
    edges: list[CodeGraphEdge] = []

    now = datetime.now(UTC)

    for node in result_nodes:
        if node.node_type not in _ALLOWED_NODE_TYPES:
            continue

        symbol_id = f"{repo_path}|||{file_path}|||{node.node_type}|||{node.name}"
        signature, complexity, start_line, end_line = _extract_node_metadata(node)
        source = _resolve_node_source(node.node_type, start_line, end_line, file_lines)

        graph_node = CodeGraphNode(
            symbol_id=symbol_id,
            symbol_name=node.name,
            symbol_type=node.node_type,  # type: ignore
            file_path=str(path.relative_to(repo_path)),
            repo_path=repo_path,
            start_line=start_line,
            end_line=end_line,
            language="python",
            signature=signature,
            complexity=complexity,
            last_indexed_at=now,
            commit_hash=commit_hash,
            source=source,
        )
        nodes.append(graph_node)

    # Build call edges
    for node in result_nodes:
        if node.node_type == "function" and hasattr(node, "calls"):
            source_id = f"{repo_path}|||{file_path}|||function|||{node.name}"
            calls_obj = getattr(node, "calls", ())
            calls_iterable: Iterable[str] = calls_obj if isinstance(calls_obj, Iterable) else ()
            for callee in calls_iterable:
                target_id = f"{repo_path}|||{file_path}|||function|||{callee}"
                edge = CodeGraphEdge(
                    source=source_id,
                    target=target_id,
                    edge_type="calls",
                    source_file=str(path.relative_to(repo_path)),
                    target_file=str(path.relative_to(repo_path)),
                    repo_path=repo_path,
                    created_at=now,
                )
                edges.append(edge)

    # Build import edges
    for node in result_nodes:
        if node.node_type == "import" and hasattr(node, "module"):
            source_id = f"{repo_path}|||{file_path}|||file|||{path.name}"
            target_id = f"{repo_path}|||{file_path}|||import|||{node.module}"
            edge = CodeGraphEdge(
                source=source_id,
                target=target_id,
                edge_type="imports",
                source_file=str(path.relative_to(repo_path)),
                target_file=str(path.relative_to(repo_path)),
                repo_path=repo_path,
                created_at=now,
            )
            edges.append(edge)

    return nodes, edges


def filter_changed_files(
    repo_path: str,
    commit_hash: str | None = None,
) -> list[str]:
    """Return list of changed Python files since the last indexed commit.

    If *commit_hash* is ``None`` (full re-index), returns all parseable files
    found under *repo_path*, respecting .gitignore patterns.
    """
    repo = Path(repo_path)

    if commit_hash is None:
        # Use git ls-files for full re-index to respect .gitignore
        result = subprocess.run(
            ["git", "-C", repo_path, "ls-files", "--cached"],
            capture_output=True,
            text=True,
            check=False,
        )
        all_files = result.stdout.strip().split("\n") if result.stdout.strip() else []
        py_files = [str(repo / f) for f in all_files if Path(f).suffix == ".py"]
        return sorted(py_files)

    result = subprocess.run(
        ["git", "diff", commit_hash, "--name-only", "--diff-filter=ACMR"],
        cwd=repo_path,
        capture_output=True,
        text=True,
        check=False,
    )
    changed = result.stdout.strip().split("\n") if result.stdout.strip() else []
    return sorted(str(repo / f) for f in changed if Path(f).suffix in PARSABLE_EXTENSIONS)
