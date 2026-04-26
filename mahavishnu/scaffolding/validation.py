"""Pattern validation against schema, slots, dependencies, and Jinja2 syntax."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from jinja2 import Environment, TemplateSyntaxError

if TYPE_CHECKING:
    from mahavishnu.scaffolding.library import PatternLibrary
    from mahavishnu.scaffolding.models import Pattern


def validate_pattern(pattern: Pattern, library: PatternLibrary) -> list[str]:
    """Validate a pattern and return a list of issue descriptions."""
    issues: list[str] = []

    # ID matches file directory
    fp = getattr(pattern, "_file_path", None)
    if fp and isinstance(fp, Path):
        expected_dir = fp.parent.name
        if not pattern.id.startswith(expected_dir + "/") and pattern.id.split("/")[0] != expected_dir:
            issues.append(
                f"Pattern ID '{pattern.id}' doesn't match directory '{expected_dir}/'"
            )

    # Required files have templates
    for f in pattern.get_files():
        if f.required and f.template and f.template not in pattern.templates:
            issues.append(f"Required file '{f.path}' references missing template '{f.template}'")

    # Slot paths within declared dirs
    all_dir_paths = {d.path.rstrip("/") for d in pattern.get_dirs()}
    for slot_name, slot in pattern.get_slots().items():
        slot_parent = _find_parent_dir(slot.path.rstrip("/"), all_dir_paths)
        if all_dir_paths and slot_parent is None:
            issues.append(f"Slot '{slot_name}' path '{slot.path}' is outside all pattern dirs")

    # Jinja2 syntax validation
    env = Environment()
    for name, template_str in pattern.templates.items():
        try:
            env.parse(template_str)
        except TemplateSyntaxError as e:
            issues.append(f"Template '{name}' has Jinja2 syntax error: {e}")

    # Cross-pattern dependency checks
    for dep in pattern.depends:
        if not library.has(dep.id):
            issues.append(f"Dependency '{dep.id}' not found in library")

    # Circular dependency detection
    _check_cycles(pattern.id, pattern.get_dependency_ids(), library, issues)

    # Duplicate ID: library tracks None in _file_paths when duplicates exist
    file_paths = getattr(library, "_file_paths", {})
    if pattern.id in file_paths and file_paths[pattern.id] is None:
        issues.append(f"Duplicate pattern ID '{pattern.id}'")

    return issues


def _find_parent_dir(slot_path: str, dir_paths: set[str]) -> str | None:
    """Find the nearest parent directory from dir_paths for the given slot_path."""
    if not dir_paths:
        return None
    while "/" in slot_path:
        slot_path = slot_path.rsplit("/", 1)[0]
        if slot_path in dir_paths:
            return slot_path
    if slot_path in dir_paths:
        return slot_path
    return None


def _check_cycles(
    pattern_id: str,
    dep_ids: list[str],
    library: PatternLibrary,
    issues: list[str],
    visited: set[str] | None = None,
    path: list[str] | None = None,
) -> None:
    """Detect circular dependencies by DFS traversal."""
    visited = visited or set()
    path = path or []
    if pattern_id in visited:
        cycle = path[path.index(pattern_id) :] + [pattern_id]
        issues.append(f"Circular dependency: {' -> '.join(cycle)}")
        return
    visited.add(pattern_id)
    path = path + [pattern_id]
    for dep_id in dep_ids:
        dep = library.get(dep_id)
        if dep:
            _check_cycles(dep_id, dep.get_dependency_ids(), library, issues, visited, path)
