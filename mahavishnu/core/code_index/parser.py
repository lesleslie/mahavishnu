"""Parse Python source files into code graph nodes and edges using mcp-common."""

from __future__ import annotations

from datetime import UTC, datetime
import logging
from pathlib import Path
import subprocess

from mahavishnu.core.code_index.models import CodeGraphEdge, CodeGraphNode
from mahavishnu.core.code_index.signature_redaction import redact_signature

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

    for skip_dir in SKIP_DIRS:
        if skip_dir in path.parts:
            return None

    try:
        from mcp_common.code_graph.analyzer import CodeGraphAnalyzer

        analyzer = CodeGraphAnalyzer(Path(repo_path))
        result = analyzer._analyze_python_file(path)
    except Exception as e:
        logger.warning(f"Parse failure for {file_path}: {e}")
        raise

    nodes: list[CodeGraphNode] = []
    edges: list[CodeGraphEdge] = []

    now = datetime.now(UTC)

    for node in result.nodes:
        if node.node_type not in _ALLOWED_NODE_TYPES:
            continue

        symbol_id = f"{repo_path}|||{file_path}|||{node.node_type}|||{node.name}"
        signature: str | None = None
        complexity: int | None = None
        start_line: int | None = None
        end_line: int | None = None

        if node.node_type == "function":
            signature = redact_signature(getattr(node, "docstring", None))
            complexity = getattr(node, "complexity", 1)
            start_line = getattr(node, "start_line", None)
            end_line = getattr(node, "end_line", None)
        elif node.node_type == "class":
            start_line = getattr(node, "start_line", None)
            end_line = getattr(node, "end_line", None)

        graph_node = CodeGraphNode(
            symbol_id=symbol_id,
            symbol_name=node.name,
            symbol_type=node.node_type,
            file_path=str(path.relative_to(repo_path)),
            repo_path=repo_path,
            start_line=start_line,
            end_line=end_line,
            language="python",
            signature=signature,
            complexity=complexity,
            last_indexed_at=now,
            commit_hash=commit_hash,
        )
        nodes.append(graph_node)

    # Build call edges
    for node in result.nodes:
        if node.node_type == "function" and hasattr(node, "calls"):
            source_id = f"{repo_path}|||{file_path}|||function|||{node.name}"
            for callee in node.calls:
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
    for node in result.nodes:
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
    found under *repo_path*.
    """
    repo = Path(repo_path)

    if commit_hash is None:
        files: list[str] = []
        for ext in PARSABLE_EXTENSIONS:
            files.extend(str(f) for f in repo.rglob(f"*{ext}"))
        return sorted(files)

    result = subprocess.run(
        ["git", "diff", commit_hash, "--name-only", "--diff-filter=ACMR"],
        cwd=repo_path,
        capture_output=True,
        text=True,
    )
    changed = result.stdout.strip().split("\n") if result.stdout.strip() else []
    return sorted(str(repo / f) for f in changed if Path(f).suffix in PARSABLE_EXTENSIONS)
