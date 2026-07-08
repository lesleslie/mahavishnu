#!/usr/bin/env python3
"""audit_orphans.py — find recently-added code with no callers.

Detects "built but not wired" by combining git recency with AST call-graph
analysis. A symbol is flagged if it was added or modified within the
lookback window AND has zero references anywhere in the scanned tree.

Usage:
    python scripts/audit_orphans.py
    python scripts/audit_orphans.py --days 14 --root mahavishnu --json
    python scripts/audit_orphans.py --out reports/orphans.md
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

SHORT_NAME_MAX = 3

# Decorator patterns that mark a symbol as a registered entry point
# (Typer CLI command, FastMCP tool, generic tool registration).
# Best-effort: catches app.command, cli.command, mcp.tool, tool,
# register_tool, and similar shapes.
#
# The trailing (?:\([^)]*\))? accepts decorators with arguments —
# app.command("health"), mcp.tool(name="foo"), etc. — which Typer
# and FastMCP commonly use. Without this, decorated functions whose
# command name is given as an argument are incorrectly flagged as
# orphans.
#
# NOTE: `ast.unparse(decorator)` returns the expression WITHOUT the
# leading `@` (the `@` is Python syntax, not part of the AST node's
# value), so the pattern is anchored on the function-call form
# (`app.command(...)`) rather than `@app.command(...)`.
DECORATOR_REGISTRATION_PATTERN = re.compile(
    r"^(?P<target>(?:[\w]+\.)*(?:tool|command|register_tool|app\.command|cli\.command))(?:\([^)]*\))?$"
)

# Framework decorator *names* that mark a symbol as wired. These are matched
# against the final segment of the decorator expression (the function name
# for ``@thing``, or the last attribute for ``@thing.foo``). The pattern
# is anchored at the end of the unparsed expression so it accepts both
# bare forms (``@field_validator``) and qualified/parameterised forms
# (``@pydantic.field_validator("foo")``, ``@app.on("Button.Pressed")``).
#
# Decorators covered:
#   Pydantic v2: field_validator, model_validator, computed_field
#   Pydantic v1: validator, root_validator
#   Textual:     on, on_mount, on_unmount, watch, work, compose
#   Builtins:    property, cached_property
#
# ``property`` and ``cached_property`` are technically readable via
# ``instance.attr``, which the audit's reference scan would not see; we
# treat them as wired by default to avoid flooding the orphan list with
# every getter in the codebase. Callers can still see them by enabling
# ``--include-stub-check`` (best-effort) if they want tighter analysis.
FRAMEWORK_DECORATORS: frozenset[str] = frozenset(
    {
        "field_validator",
        "model_validator",
        "computed_field",
        "validator",
        "root_validator",
        "on",
        "on_mount",
        "on_unmount",
        "watch",
        "work",
        "compose",
        "property",
        "cached_property",
    }
)

# Pattern that pulls the trailing decorator name from an unparsed expression.
# ``ast.unparse(app.on("Button.Pressed"))`` -> ``'app.on("Button.Pressed")'``;
# we want the ``on`` segment, not the call arg.
_FRAMEWORK_DECORATOR_TAIL = re.compile(r"(?:^|\.)([A-Za-z_]\w*)\s*(?:\(.*\))?$")

# Textual lifecycle / event / action methods are discovered by *name*, not
# decorator. Exact names (``compose``, ``on_mount``) plus a few prefix-based
# conventions (``on_<Event>``, ``watch_<reactive>``, ``action_<verb>``).
# These methods are framework entry points even when no caller references
# them, so excluding them from the orphan list keeps the report actionable.
TEXTUAL_LIFECYCLE_NAMES: frozenset[str] = frozenset({"compose"})
_TEXTUAL_PREFIX_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^on_mount$"),
    re.compile(r"^on_unmount$"),
    re.compile(r"^on_[A-Z]\w*$"),       # on_<Event>: on_button_pressed
    re.compile(r"^watch_[A-Za-z_]\w*$"),  # watch_<reactive>: watch__status
    re.compile(r"^action_[A-Za-z_]\w*$"),  # action_<verb>: action_switch_tab
)


def _is_textual_lifecycle(name: str) -> bool:
    """Return True if ``name`` is a Textual framework hook by convention."""
    if name in TEXTUAL_LIFECYCLE_NAMES:
        return True
    return any(pat.match(name) for pat in _TEXTUAL_PREFIX_PATTERNS)


@dataclass(frozen=True)
class Symbol:
    """A top-level public function, class, or public method."""

    name: str
    kind: str  # "function" | "class" | "method"
    file: Path
    line: int
    qualified: str = ""


@dataclass
class CandidateInfo:
    """A recently-modified candidate symbol plus its orphan verdict."""

    symbol: Symbol
    last_modified: datetime | None = None
    is_registered: bool = False
    references: list[str] = field(default_factory=list)


@dataclass
class FileResult:
    """Audit outcome for one recently-changed file."""

    path: Path
    orphans: list[CandidateInfo] = field(default_factory=list)
    has_no_public_surface: bool = False


def parse_args() -> argparse.Namespace:
    """Parse CLI flags per the deliverable spec."""
    parser = argparse.ArgumentParser(
        prog="audit_orphans",
        description=(
            "Find recently-added Python symbols with zero callers "
            "(\"built but not wired\"). Combines git recency with "
            "AST call-graph analysis."
        ),
    )
    parser.add_argument(
        "--root",
        default=".",
        type=Path,
        help="Directory to scan (default: current directory).",
    )
    parser.add_argument(
        "--days",
        default=30,
        type=int,
        help="Lookback window in days (default: 30).",
    )
    parser.add_argument(
        "--out",
        default=None,
        type=Path,
        help="Optional output file path (default: stdout).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON instead of Markdown.",
    )
    parser.add_argument(
        "--include-tests",
        action="store_true",
        help="Include symbols defined in tests/ (off by default).",
    )
    parser.add_argument(
        "--include-stub-check",
        action="store_true",
        help=(
            "Best-effort: exclude classes that appear as a Literal member "
            "or Field(discriminator=...) reference (Pydantic discriminated "
            "union stubs). Off by default."
        ),
    )
    parser.add_argument(
        "--exclude",
        nargs="*",
        default=[
            "__pycache__",
            ".venv",
            "build",
            "dist",
            ".git",
            ".tox",
            ".mypy_cache",
            ".ruff_cache",
            ".pytest_cache",
            "node_modules",
            ".eggs",
            "*.egg-info",
        ],
        help="Directory or path-component patterns to skip during walk.",
    )
    return parser.parse_args()


def _has_excluded_component(rel_parts: tuple[str, ...], excludes: list[str]) -> bool:
    """True if any path component matches one of the exclude patterns."""
    for part in rel_parts:
        for exclude in excludes:
            if part == exclude or part.endswith(exclude):
                return True
    return False


def should_skip(path: Path, root: Path, excludes: list[str]) -> bool:
    """Return True when path lives under an excluded directory."""
    try:
        rel = path.relative_to(root)
    except ValueError:
        return True
    return _has_excluded_component(rel.parts, excludes)


def run_git_log(
    root: Path, days: int
) -> tuple[set[Path], dict[Path, datetime]]:
    """Collect recently-changed Python files plus their last-modified time.

    Uses ``git log --since=<N> days ago`` when available. Falls back to
    an mtime-based scan when no git history exists (e.g. unpacked tarball).
    """
    files: set[Path] = set()
    last_modified: dict[Path, datetime] = {}
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    git_available = True
    try:
        result = subprocess.run(
            [
                "git",
                "log",
                f"--since={days} days ago",
                "--name-only",
                "--pretty=format:",
            ],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        git_available = False
        result = None  # type: ignore[assignment]

    if git_available and result is not None:
        for raw in result.stdout.splitlines():
            line = raw.strip()
            if not line.endswith(".py"):
                continue
            candidate = root / line
            if candidate.exists():
                files.add(candidate)
    else:
        print(
            f"warning: git log unavailable; using mtime fallback (last {days} days)",
            file=sys.stderr,
        )
        for path in root.rglob("*.py"):
            try:
                mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            except OSError:
                continue
            if mtime >= cutoff:
                files.add(path)

    # Per-file last-modified time
    for path in list(files):
        stamp: str | None = None
        if git_available:
            try:
                result = subprocess.run(
                    [
                        "git",
                        "log",
                        "-1",
                        "--format=%cI",
                        "--",
                        str(path.relative_to(root)),
                    ],
                    cwd=root,
                    check=True,
                    capture_output=True,
                    text=True,
                )
                stamp = result.stdout.strip()
            except (subprocess.CalledProcessError, FileNotFoundError, ValueError):
                stamp = None
        if stamp:
            try:
                last_modified[path] = datetime.fromisoformat(stamp)
                continue
            except ValueError:
                pass
        try:
            last_modified[path] = datetime.fromtimestamp(
                path.stat().st_mtime, tz=timezone.utc
            )
        except OSError:
            pass

    return files, last_modified


def _parse_file(path: Path) -> ast.Module | None:
    """Return the parsed AST for a Python source file, or None on failure."""
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    try:
        return ast.parse(source, filename=str(path))
    except SyntaxError:
        return None


def extract_symbols(path: Path) -> list[Symbol]:
    """Return top-level public functions, classes, and public methods.

    Public = name does not start with ``_`` and has more than
    ``SHORT_NAME_MAX`` characters (so we skip noisy names like ``run``).
    """
    tree = _parse_file(path)
    if tree is None:
        return []

    symbols: list[Symbol] = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            if not node.name.startswith("_") and len(node.name) > SHORT_NAME_MAX:
                symbols.append(
                    Symbol(
                        name=node.name,
                        kind="function",
                        file=path,
                        line=node.lineno,
                    )
                )
        elif isinstance(node, ast.ClassDef):
            if not node.name.startswith("_") and len(node.name) > SHORT_NAME_MAX:
                symbols.append(
                    Symbol(
                        name=node.name,
                        kind="class",
                        file=path,
                        line=node.lineno,
                    )
                )
                for child in node.body:
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        if (
                            not child.name.startswith("_")
                            and len(child.name) > SHORT_NAME_MAX
                        ):
                            symbols.append(
                                Symbol(
                                    name=child.name,
                                    kind="method",
                                    file=path,
                                    line=child.lineno,
                                    qualified=f"{node.name}.{child.name}",
                                )
                            )
    return symbols


def find_registrations(path: Path) -> set[str]:
    """Find symbol names whose definitions use a known registration decorator.

    The check is a best-effort source-text scan: any node whose decorator
    chain matches ``@tool``/``@mcp.tool``/``@app.command(...)``/etc. is
    considered wired (entry point exists) and excluded from the orphan
    list.

    Also recognises:
    - Framework decorators (Pydantic validators, Textual ``@on(...)``
      message handlers, ``@property``) that the static analyzer can't
      trace to a call site. See ``FRAMEWORK_DECORATORS``.
    - Textual lifecycle methods discovered by name (``compose``,
      ``on_mount``, ``watch_*``, ``action_*``, ``on_<Event>``). See
      ``_is_textual_lifecycle``.
    """
    tree = _parse_file(path)
    if tree is None:
        return set()

    registered: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        ):
            continue
        # Textual lifecycle methods are name-based (no decorator required).
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and _is_textual_lifecycle(node.name)
        ):
            registered.add(node.name)
            continue
        for decorator in node.decorator_list:
            decorator_text = ast.unparse(decorator)
            if DECORATOR_REGISTRATION_PATTERN.match(decorator_text):
                registered.add(node.name)
                break
            tail_match = _FRAMEWORK_DECORATOR_TAIL.search(decorator_text)
            if tail_match and tail_match.group(1) in FRAMEWORK_DECORATORS:
                registered.add(node.name)
                break
    return registered


def _class_names_from_literal(node: ast.AST) -> set[str]:
    """Return class names referenced inside a ``Literal[...]`` annotation."""
    names: set[str] = set()
    if not isinstance(node, (ast.Subscript, ast.Attribute)):
        return names
    # Subscript form: Literal[A, B] or Union[Literal[A], B]
    if isinstance(node, ast.Subscript):
        slc = node.slice
        if isinstance(slc, ast.Tuple):
            for elt in slc.elts:
                if isinstance(elt, ast.Name):
                    names.add(elt.id)
                elif isinstance(elt, ast.Attribute):
                    names.add(elt.attr)
        elif isinstance(slc, ast.Name):
            names.add(slc.id)
        elif isinstance(slc, ast.Attribute):
            names.add(slc.attr)
    return names


def _collect_discriminated_union_members(
    root: Path, excludes: list[str], include_tests: bool
) -> set[str]:
    """Return class names that participate in a Pydantic discriminated union.

    Best-effort: scans every ``.py`` file under ``root`` for two patterns:

    1. ``Literal[X, Y, ...]`` annotations (Pydantic v2 discriminated unions
       where each member sets a literal ``operation_type`` field).
    2. ``Field(discriminator="kind")`` references.
    3. Same-file inheritance: a class whose base is another class defined
       in the same file AND the base class declares an Enum-typed
       discriminator field. This catches the Pydantic v2 polymorphic
       pattern used in ``mahavishnu/automation/models.py`` (sibling
       classes overriding a shared ``operation_type: SomeEnum`` field).

    Returns a set of class names that look like polymorphic stubs and
    should be excluded from the orphan list.
    """
    members: set[str] = set()
    for path in root.rglob("*.py"):
        if should_skip(path, root, excludes):
            continue
        if not include_tests and "tests" in path.relative_to(root).parts:
            continue
        tree = _parse_file(path)
        if tree is None:
            continue

        # Pass 1: collect top-level class names defined in this file so
        # we can recognise ``same-file inheritance`` later.
        file_class_names: set[str] = set()
        file_classes: dict[str, ast.ClassDef] = {}
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                file_class_names.add(node.name)
                file_classes[node.name] = node

        # Pass 1b: for each top-level class, record whether it declares an
        # Enum-typed attribute (used as a discriminator signal).
        class_has_enum_field: dict[str, set[str]] = {}
        for class_name, class_node in file_classes.items():
            enum_attrs: set[str] = set()
            for child in class_node.body:
                if isinstance(child, ast.AnnAssign) and isinstance(
                    child.target, ast.Name
                ):
                    ann = child.annotation
                    if isinstance(ann, ast.Name) and ann.id.endswith(
                        ("Type", "Enum", "Status", "Kind", "Mode")
                    ):
                        enum_attrs.add(child.target.id)
            class_has_enum_field[class_name] = enum_attrs

        for node in ast.walk(tree):
            # Pattern: Literal[Foo, Bar, Baz]
            if isinstance(node, ast.Subscript):
                value = node.value
                is_literal = (
                    (isinstance(value, ast.Name) and value.id == "Literal")
                    or (
                        isinstance(value, ast.Attribute)
                        and value.attr == "Literal"
                    )
                )
                if is_literal:
                    members.update(_class_names_from_literal(node))
                continue

            # Pattern: Field(discriminator="kind"). The discriminator name
            # is a kwarg on a Call; we don't resolve which class is the
            # stub from this alone, but we can pick up class names that
            # appear as Name nodes inside the same Call argument list.
            if isinstance(node, ast.Call):
                has_discriminator = False
                for kw in node.keywords:
                    if kw.arg == "discriminator":
                        has_discriminator = True
                        break
                if has_discriminator:
                    for arg in node.args:
                        if isinstance(arg, ast.Name):
                            members.add(arg.id)

            # Pattern: same-file inheritance with Enum discriminator on
            # the parent. Catches the models.py polymorphic operation
            # classes. We look for ClassDef nodes whose base is another
            # top-level class declared in the same file, where that
            # parent declares an Enum-typed attribute.
            if isinstance(node, ast.ClassDef):
                for base in node.bases:
                    base_name: str | None = None
                    if isinstance(base, ast.Name):
                        base_name = base.id
                    elif isinstance(base, ast.Attribute):
                        base_name = base.attr
                    if (
                        base_name is not None
                        and base_name in file_class_names
                        and class_has_enum_field.get(base_name)
                    ):
                        members.add(node.name)
                        break

    return members


def collect_references(
    root: Path, excludes: list[str], include_tests: bool
) -> dict[str, set[Path]]:
    """Build a mapping of ``identifier name -> files that reference it``.

    Walks every ``.py`` file under ``root`` (minus excluded dirs and
    ``tests/`` unless ``include_tests`` is set) and records every
    ``Name``, ``Attribute``, and ``arg`` occurrence.

    This catches both bare ``func()`` and qualified ``module.func``
    references, plus function parameters that look like the symbol name.
    Re-exports such as ``from .x import Y as Z`` surface ``Z`` as a name
    wherever it is consumed, satisfying the "record Z as a reference"
    edge case in the spec.
    """
    refs: dict[str, set[Path]] = defaultdict(set)
    for path in root.rglob("*.py"):
        if should_skip(path, root, excludes):
            continue
        if not include_tests and "tests" in path.relative_to(root).parts:
            continue
        tree = _parse_file(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                refs[node.id].add(path)
            elif isinstance(node, ast.Attribute):
                refs[node.attr].add(path)
            elif isinstance(node, ast.arg):
                refs[node.arg].add(path)
    return refs


def classify_orphans(
    recent_files: set[Path],
    last_modified: dict[Path, datetime],
    root: Path,
    excludes: list[str],
    include_tests: bool,
    include_stub_check: bool = False,
) -> list[FileResult]:
    """For each recently-changed file, decide which candidates are orphans."""
    references = collect_references(root, excludes, include_tests)
    stub_members: set[str] = set()
    if include_stub_check:
        stub_members = _collect_discriminated_union_members(
            root, excludes, include_tests
        )

    results: list[FileResult] = []
    for path in sorted(recent_files):
        if should_skip(path, root, excludes):
            continue
        if not include_tests and "tests" in path.relative_to(root).parts:
            continue
        if not path.exists():
            continue

        symbols = extract_symbols(path)
        if not symbols:
            results.append(
                FileResult(path=path, orphans=[], has_no_public_surface=True)
            )
            continue

        registered = find_registrations(path)
        last_mod = last_modified.get(path)
        orphans: list[CandidateInfo] = []

        for sym in symbols:
            if sym.name in registered:
                continue
            if include_stub_check and sym.kind == "class" and sym.name in stub_members:
                continue
            ref_files = references.get(sym.name, set())
            other_files = {f for f in ref_files if f != path}
            if not other_files:
                orphans.append(
                    CandidateInfo(
                        symbol=sym,
                        last_modified=last_mod,
                        is_registered=False,
                        references=[],
                    )
                )

        results.append(
            FileResult(path=path, orphans=orphans, has_no_public_surface=False)
        )
    return results


def render_markdown(results: list[FileResult], root: Path) -> str:
    """Render the audit as a Markdown report grouped by file."""
    lines: list[str] = []
    lines.append("# Orphan Audit Report")
    lines.append("")
    lines.append(
        "Generated by `scripts/audit_orphans.py`. Each symbol below was "
        "modified within the lookback window and has zero callers in the "
        "scanned tree. Either wire it up or remove it."
    )
    lines.append("")

    total_orphans = sum(len(r.orphans) for r in results)
    if total_orphans == 0 and not any(r.has_no_public_surface for r in results):
        lines.append("**No orphans found.**")
        lines.append("")
        return "\n".join(lines)

    for result in results:
        rel = result.path.relative_to(root).as_posix()
        if result.has_no_public_surface:
            lines.append(f"## `{rel}`")
            lines.append("")
            lines.append("_No public surface (no top-level public functions or classes)._")
            lines.append("")
            continue
        if not result.orphans:
            # File had public symbols but all of them had callers or were registered.
            lines.append(f"## `{rel}`")
            lines.append("")
            lines.append("_No orphans (all public symbols are wired)._")
            lines.append("")
            continue
        lines.append(f"## `{rel}`")
        lines.append("")
        lines.append("| Symbol | Kind | Added/Modified | Last Ref | Risk Note |")
        lines.append("| --- | --- | --- | --- | --- |")
        for cand in result.orphans:
            sym = cand.symbol
            last = cand.last_modified.date().isoformat() if cand.last_modified else "unknown"
            lines.append(
                f"| `{sym.name}` | {sym.kind} | {last} | none in scan | "
                f"Add public entry-point in `__main__`/CLI/MCP server, or remove. |"
            )
        lines.append("")
    return "\n".join(lines)


def render_json(results: list[FileResult], root: Path) -> str:
    """Render the audit as a JSON document."""
    payload: list[dict[str, object]] = []
    for result in results:
        rel = result.path.relative_to(root).as_posix()
        if not result.orphans:
            continue
        payload.append(
            {
                "file": rel,
                "orphans": [
                    {
                        "symbol": c.symbol.name,
                        "kind": c.symbol.kind,
                        "line": c.symbol.line,
                        "added_or_modified": c.last_modified.isoformat()
                        if c.last_modified
                        else None,
                        "risk_note": (
                            "Add public entry-point in __main__/CLI/MCP server, or remove."
                        ),
                    }
                    for c in result.orphans
                ],
            }
        )
    return json.dumps({"orphans": payload}, indent=2)


def main() -> int:
    """Run the orphan audit end-to-end and return a shell exit code."""
    args = parse_args()
    root: Path = args.root.resolve()
    if not root.exists():
        print(f"error: root directory not found: {root}", file=sys.stderr)
        return 2

    recent_files, last_modified = run_git_log(root, args.days)
    results = classify_orphans(
        recent_files,
        last_modified,
        root,
        args.exclude,
        args.include_tests,
        include_stub_check=args.include_stub_check,
    )

    if args.json:
        body = render_json(results, root)
    else:
        body = render_markdown(results, root)

    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(body, encoding="utf-8")
    else:
        print(body)

    has_orphans = any(bool(r.orphans) for r in results)
    return 1 if has_orphans else 0


if __name__ == "__main__":
    sys.exit(main())