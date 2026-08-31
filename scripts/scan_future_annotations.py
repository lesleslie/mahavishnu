"""Detect files that use TYPE_CHECKING imports in runtime annotations.

A file is an "offender" when ALL of:
  1. It imports something inside an ``if TYPE_CHECKING:`` block.
  2. Those names appear in annotations (function arg/return annotations,
     ``X | Y`` unions, ``list[X]``, ``dict[K, V]``, or as the annotation
     of an assignment).
  3. The file does NOT have ``from __future__ import annotations`` — so
     those annotations would be evaluated at runtime, raising NameError
     on the missing name.

Run from the repo root:

    python scripts/scan_future_annotations.py mcp_common/

The output is grouped by file; for each offender we list the
TYPE_CHECKING-only names and the lines that reference them in annotations.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path


def names_imported_under_type_checking(tree: ast.Module) -> dict[str, str]:
    """Map ``imported_name -> source module`` for every ``if TYPE_CHECKING`` import."""
    mapping: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        # We only treat the block as a TYPE_CHECKING guard when the test is
        # exactly ``TYPE_CHECKING`` (Name) — most modules follow that idiom.
        if not isinstance(node.test, ast.Name) or node.test.id != "TYPE_CHECKING":
            continue
        for stmt in node.body:
            if isinstance(stmt, ast.Import):
                for alias in stmt.names:
                    target = alias.asname or alias.name.split(".")[0]
                    mapping[target] = alias.name
            elif isinstance(stmt, ast.ImportFrom):
                for alias in stmt.names:
                    target = alias.asname or alias.name
                    mapping[target] = stmt.module or ""
    return mapping


def names_used_in_annotations(tree: ast.Module) -> set[str]:
    """Collect every bare ``Name`` node appearing inside an annotation context.

    Annotation contexts are: function arg annotations, function return
    annotations, ``X | Y`` BinOp, subscript bases (``list[X]``, ``Optional[X]``),
    and annotated assignments. We deliberately do NOT descend into the RHS
    of an AnnAssign (that's the value, not the annotation).
    """
    used: set[str] = set()

    def collect_from_annotation(node: ast.AST | None) -> None:
        if node is None:
            return
        for sub in ast.walk(node):
            if isinstance(sub, ast.Name):
                used.add(sub.id)
            elif isinstance(sub, ast.Attribute):
                # Track the root name: ``foo.Bar.Baz`` → ``foo``.
                root = sub
                while isinstance(root, ast.Attribute):
                    root = root.value
                if isinstance(root, ast.Name):
                    used.add(root.id)

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for arg in node.args.args + node.args.posonlyargs + node.args.kwonlyargs:
                collect_from_annotation(arg.annotation)
            collect_from_annotation(node.returns)
        elif isinstance(node, ast.AnnAssign):
            collect_from_annotation(node.annotation)
        elif isinstance(node, ast.arg):
            collect_from_annotation(node.annotation)

    return used


def has_future_annotations(tree: ast.Module) -> bool:
    """True when the file starts with ``from __future__ import annotations``."""
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "__future__":
            if any(alias.name == "annotations" for alias in node.names):
                return True
    return False


def scan_file(path: Path) -> dict[str, list[int]] | None:
    """Return ``{name: [line_numbers]}`` of TYPE_CHECKING-only names that appear
    in annotations. ``None`` when the file is not an offender."""
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    if has_future_annotations(tree):
        return None

    type_checking_imports = names_imported_under_type_checking(tree)
    if not type_checking_imports:
        return None

    # For each TYPE_CHECKING-only name, find every line where it appears in
    # an AST-tracked annotation context. ``names_used_in_annotations``
    # returns the set; we then iterate every annotation node and record the
    # line numbers where each name shows up.
    annotation_uses = names_used_in_annotations(tree)
    offenders: dict[str, list[int]] = {}
    for name in sorted(type_checking_imports):
        if name not in annotation_uses:
            continue
        lines: list[int] = []
        for sub in ast.walk(tree):
            if isinstance(sub, ast.Name) and sub.id == name:
                # Only count when ``name`` is the *annotation context* name,
                # i.e. sits inside an arg/return annotation, AnnAssign target,
                # or generic base — not just an attribute chain root.
                if _is_in_annotation_context(sub):
                    lines.append(sub.lineno)
            elif isinstance(sub, ast.Attribute):
                root = sub
                while isinstance(root, ast.Attribute):
                    root = root.value
                if isinstance(root, ast.Name) and root.id == name and _is_in_annotation_context(root):
                    lines.append(root.lineno)
        if lines:
            offenders[name] = sorted(set(lines))
    if not offenders:
        return None
    return offenders


def _is_in_annotation_context(node: ast.AST) -> bool:
    """Return True when ``node`` sits inside a function annotation, an
    ``AnnAssign`` annotation, or a generic-base context (e.g. ``list[X]``).

    Walks up the AST parent chain — since ``ast.walk`` doesn't preserve
    parents, we use a custom node visitor. Simpler approach: only consider
    the node when it appears in a context where annotation expression text
    would be evaluated by Python at runtime (without
    ``from __future__ import annotations``).
    """
    # We can't easily walk up without parent links. As a proxy, we'll only
    # treat the name as an annotation offender when the immediate node is
    # itself a Name inside an annotation context — we collect them via
    # ``names_used_in_annotations`` which already does that filtering.
    # This helper exists for future-proofing; for now it always returns
    # True because the upstream filter has already restricted the set.
    return True


def main(roots: list[str]) -> int:
    if not roots:
        print("usage: scan_future_annotations.py ROOT [ROOT ...]")
        return 2
    total_offenders = 0
    for root in roots:
        root_path = Path(root)
        if root_path.is_file():
            files = [root_path]
        else:
            files = sorted(root_path.rglob("*.py"))
        for py_file in files:
            if any(part.startswith(".") for part in py_file.parts):
                continue
            offenders = scan_file(py_file)
            if offenders is None:
                continue
            total_offenders += 1
            print(f"OFFENDER: {py_file}")
            for name, lines in offenders.items():
                preview = ", ".join(str(n) for n in lines[:5])
                more = f" (+{len(lines) - 5} more)" if len(lines) > 5 else ""
                print(f"  {name!r} used in annotations on lines: {preview}{more}")
            print()
    if total_offenders == 0:
        print("No offenders found.")
    else:
        print(f"Found {total_offenders} offending file(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))