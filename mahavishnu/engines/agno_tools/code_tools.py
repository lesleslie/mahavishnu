"""Code analysis tools for Agno agents.

These tools provide code analysis capabilities including complexity analysis,
semantic code search, and function signature extraction.

All tools use Agno's native @tool decorator for seamless integration.
The actual implementations are separate functions for testing.
"""

from __future__ import annotations

import ast
import logging
from pathlib import Path
from typing import Any

from agno.tools import tool

from mahavishnu.core.errors import AgnoError, ErrorCode

logger = logging.getLogger(__name__)


def _get_python_files(repo_path: Path) -> list[Path]:
    """Get all Python files in a repository.

    Args:
        repo_path: Path to the repository

    Returns:
        List of Python file paths
    """
    python_files = []
    blocked = {".git", ".hg", ".svn", "__pycache__", "node_modules", ".venv", "venv", ".tox"}

    for path in repo_path.rglob("*.py"):
        if not any(blocked in str(path) for blocked in blocked):
            python_files.append(path)

    return python_files


def _analyze_python_file(file_path: Path) -> dict[str, Any]:
    """Analyze a single Python file.

    Args:
        file_path: Path to the Python file

    Returns:
        Analysis results dict
    """
    result: dict[str, Any] = {
        "file": str(file_path),
        "functions": [],
        "classes": [],
        "imports": [],
        "complexity": {
            "lines": 0,
            "loc": 0,  # Lines of code (excluding comments/blanks)
            "functions": 0,
            "classes": 0,
            "imports": 0,
        },
        "issues": [],
    }

    try:
        content = file_path.read_text(encoding="utf-8")
        lines = content.splitlines()
        result["complexity"]["lines"] = len(lines)

        # Count non-empty, non-comment lines
        loc = 0
        for line in lines:
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                loc += 1
        result["complexity"]["loc"] = loc

        # Parse AST
        tree = ast.parse(content)

        for node in ast.walk(tree):
            # Extract imports
            if isinstance(node, ast.Import | ast.ImportFrom):
                if isinstance(node, ast.ImportFrom) and node.module:
                    result["imports"].append(node.module)
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        result["imports"].append(alias.name)
                result["complexity"]["imports"] += 1

            # Extract functions
            elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                func_info = {
                    "name": node.name,
                    "line": node.lineno,
                    "args": [arg.arg for arg in node.args.args],
                    "decorators": [d.id if isinstance(d, ast.Name) else str(d) for d in node.decorator_list],
                    "is_async": isinstance(node, ast.AsyncFunctionDef),
                    "docstring": ast.get_docstring(node) or "",
                }

                # Calculate cyclomatic complexity
                complexity = 1
                for child in ast.walk(node):
                    if isinstance(child, ast.If | ast.For | ast.While | ast.ExceptHandler):
                        complexity += 1
                    elif isinstance(child, ast.BoolOp):
                        complexity += len(child.values) - 1
                    elif isinstance(child, ast.comprehension):
                        complexity += 1
                        if child.ifs:
                            complexity += len(child.ifs)

                func_info["complexity"] = complexity

                # Flag high complexity
                if complexity > 10:
                    result["issues"].append({
                        "type": "high_complexity",
                        "location": f"{node.name}:{node.lineno}",
                        "message": f"Function '{node.name}' has high cyclomatic complexity ({complexity})",
                        "severity": "warning",
                    })

                result["functions"].append(func_info)
                result["complexity"]["functions"] += 1

            # Extract classes
            elif isinstance(node, ast.ClassDef):
                class_info = {
                    "name": node.name,
                    "line": node.lineno,
                    "bases": [base.id if isinstance(base, ast.Name) else str(base) for base in node.bases],
                    "methods": [],
                    "docstring": ast.get_docstring(node) or "",
                }

                # Extract methods
                for item in node.body:
                    if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef):
                        class_info["methods"].append(item.name)

                result["classes"].append(class_info)
                result["complexity"]["classes"] += 1

        # Check for common issues
        if result["complexity"]["loc"] > 500:
            result["issues"].append({
                "type": "large_file",
                "location": str(file_path),
                "message": f"File is large ({result['complexity']['loc']} LOC)",
                "severity": "info",
            })

    except SyntaxError as e:
        result["issues"].append({
            "type": "syntax_error",
            "location": f"{file_path}:{e.lineno}",
            "message": str(e.msg),
            "severity": "error",
        })
    except Exception as e:
        result["issues"].append({
            "type": "parse_error",
            "location": str(file_path),
            "message": str(e),
            "severity": "error",
        })

    return result


# ============================================================================
# Implementation Functions (for direct testing)
# ============================================================================


def _analyze_code_impl(file_path: str) -> dict[str, Any]:
    """Analyze code file for complexity and issues - implementation.

    Args:
        file_path: Path to the code file to analyze

    Returns:
        Dict with analysis results including:
        - functions: List of function info
        - classes: List of class info
        - imports: List of imported modules
        - complexity: Metrics (lines, loc, functions, classes, imports)
        - issues: List of detected issues

    Raises:
        AgnoError: If analysis fails
    """
    path = Path(file_path).resolve()

    if not path.exists():
        raise AgnoError(
            f"File not found: {file_path}",
            error_code=ErrorCode.AGNO_TOOL_EXECUTION_ERROR,
            details={"file_path": file_path},
        )

    if not path.is_file():
        raise AgnoError(
            f"Not a file: {file_path}",
            error_code=ErrorCode.AGNO_TOOL_EXECUTION_ERROR,
            details={"file_path": file_path},
        )

    # Currently only support Python
    if path.suffix != ".py":
        raise AgnoError(
            f"Only Python files are supported for analysis: {file_path}",
            error_code=ErrorCode.AGNO_TOOL_EXECUTION_ERROR,
            details={"file_path": file_path, "extension": path.suffix},
        )

    result = _analyze_python_file(path)
    logger.debug(f"Analyzed code: {file_path}")
    return result


def _search_code_impl(query: str, repo_path: str) -> list[dict[str, Any]]:
    """Search for code patterns in a repository - implementation.

    Args:
        query: Search query (keyword or pattern)
        repo_path: Path to the repository root

    Returns:
        List of matches with file, line number, and context

    Raises:
        AgnoError: If search fails
    """
    path = Path(repo_path).resolve()

    if not path.exists():
        raise AgnoError(
            f"Repository not found: {repo_path}",
            error_code=ErrorCode.AGNO_TOOL_EXECUTION_ERROR,
            details={"repo_path": repo_path},
        )

    if not path.is_dir():
        raise AgnoError(
            f"Not a directory: {repo_path}",
            error_code=ErrorCode.AGNO_TOOL_EXECUTION_ERROR,
            details={"repo_path": repo_path},
        )

    results = []
    query_lower = query.lower()

    # Search Python files
    for py_file in _get_python_files(path):
        try:
            content = py_file.read_text(encoding="utf-8")
            lines = content.splitlines()

            for line_num, line in enumerate(lines, start=1):
                if query_lower in line.lower():
                    # Get context (surrounding lines)
                    context_start = max(0, line_num - 3)
                    context_end = min(len(lines), line_num + 2)
                    context = lines[context_start:context_end]

                    results.append({
                        "file": str(py_file.relative_to(path)),
                        "line": line_num,
                        "match": line.strip(),
                        "context": context,
                    })

        except Exception as e:
            logger.debug(f"Error reading {py_file}: {e}")
            continue

    # Sort by file path
    results.sort(key=lambda x: (x["file"], x["line"]))

    logger.debug(f"Found {len(results)} matches for '{query}' in {repo_path}")
    return results


def _get_function_signature_impl(file_path: str, function_name: str) -> dict[str, Any]:
    """Get function signature from a code file - implementation.

    Args:
        file_path: Path to the code file
        function_name: Name of the function to extract

    Returns:
        Dict with function signature info:
        - name: Function name
        - args: List of argument names
        - defaults: Dict of default values
        - return_annotation: Return type annotation
        - docstring: Function docstring
        - decorators: List of decorator names
        - is_async: Whether function is async

    Raises:
        AgnoError: If extraction fails or function not found
    """
    path = Path(file_path).resolve()

    if not path.exists():
        raise AgnoError(
            f"File not found: {file_path}",
            error_code=ErrorCode.AGNO_TOOL_EXECUTION_ERROR,
            details={"file_path": file_path},
        )

    if path.suffix != ".py":
        raise AgnoError(
            f"Only Python files are supported: {file_path}",
            error_code=ErrorCode.AGNO_TOOL_EXECUTION_ERROR,
            details={"file_path": file_path},
        )

    content = path.read_text(encoding="utf-8")
    tree = ast.parse(content)

    # Find the function
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == function_name:
            # Extract argument info
            args = []
            defaults = {}

            # Regular args
            for i, arg in enumerate(node.args.args):
                args.append(arg.arg)

                # Get default value if present
                default_offset = len(node.args.args) - len(node.args.defaults)
                if i >= default_offset:
                    default_idx = i - default_offset
                    default = node.args.defaults[default_idx]
                    defaults[arg.arg] = ast.unparse(default) if default else None

            # *args
            if node.args.vararg:
                args.append(f"*{node.args.vararg.arg}")

            # **kwargs
            if node.args.kwarg:
                args.append(f"**{node.args.kwarg.arg}")

            # Return annotation
            return_annotation = None
            if node.returns:
                return_annotation = ast.unparse(node.returns)

            # Decorators
            decorators = []
            for dec in node.decorator_list:
                if isinstance(dec, ast.Name):
                    decorators.append(dec.id)
                elif isinstance(dec, ast.Attribute):
                    decorators.append(ast.unparse(dec))
                else:
                    decorators.append(str(dec))

            result = {
                "name": node.name,
                "args": args,
                "defaults": defaults,
                "return_annotation": return_annotation,
                "docstring": ast.get_docstring(node) or "",
                "decorators": decorators,
                "is_async": isinstance(node, ast.AsyncFunctionDef),
                "line": node.lineno,
            }

            logger.debug(f"Extracted signature for {function_name} from {file_path}")
            return result

    # Function not found
    raise AgnoError(
        f"Function '{function_name}' not found in {file_path}",
        error_code=ErrorCode.AGNO_TOOL_EXECUTION_ERROR,
        details={"file_path": file_path, "function_name": function_name},
    )


# ============================================================================
# Agno Tool Definitions
# ============================================================================


@tool(
    name="analyze_code",
    description="Analyze code for complexity, structure, and potential issues",
    instructions="Use this tool to analyze Python code files. Returns complexity metrics, function/class info, and issues.",
)
def analyze_code(file_path: str) -> dict[str, Any]:
    """Analyze code file for complexity and issues.

    Args:
        file_path: Path to the code file to analyze

    Returns:
        Dict with analysis results
    """
    return _analyze_code_impl(file_path)


@tool(
    name="search_code",
    description="Search for code patterns in a repository",
    instructions="Use this tool to search for code by pattern or keyword. Returns matching files and line numbers.",
)
def search_code(query: str, repo_path: str) -> list[dict[str, Any]]:
    """Search for code patterns in a repository.

    Args:
        query: Search query (keyword or pattern)
        repo_path: Path to the repository root

    Returns:
        List of matches with file, line number, and context
    """
    return _search_code_impl(query, repo_path)


@tool(
    name="get_function_signature",
    description="Get the signature of a function in a code file",
    instructions="Use this tool to extract function signatures including parameters, return type, and docstring.",
)
def get_function_signature(file_path: str, function_name: str) -> dict[str, Any]:
    """Get function signature from a code file.

    Args:
        file_path: Path to the code file
        function_name: Name of the function to extract

    Returns:
        Dict with function signature info
    """
    return _get_function_signature_impl(file_path, function_name)


__all__ = [
    # Agno tools (for agent use)
    "analyze_code",
    "search_code",
    "get_function_signature",
    # Implementation functions (for testing)
    "_analyze_code_impl",
    "_search_code_impl",
    "_get_function_signature_impl",
]
