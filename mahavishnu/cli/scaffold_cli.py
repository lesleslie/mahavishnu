"""CLI commands for pattern management and project scaffolding."""

from __future__ import annotations

from pathlib import Path

import typer

from mahavishnu.scaffolding.engine import ScaffoldingEngine
from mahavishnu.scaffolding.library import PatternLibrary
from mahavishnu.scaffolding.validation import validate_pattern

app = typer.Typer(help="Pattern management and project scaffolding")


def _get_library() -> PatternLibrary:
    """Create a PatternLibrary and load all patterns from the default root."""
    lib = PatternLibrary()
    lib.load_all()
    return lib


@app.callback(invoke_without_command=True)
def callback():
    """Pattern management and scaffolding for Fastblocks projects."""


# -- Pattern commands --

patterns_app = typer.Typer(help="Pattern library management")
app.add_typer(patterns_app, name="patterns")


@patterns_app.command("list")
def patterns_list(
    category: str | None = typer.Option(None, "--category", "-c", help="Filter by category"),
):
    """List all patterns in the library."""
    lib = _get_library()
    categories = lib.list_all_categories()

    if category and category not in categories:
        typer.echo(f"Category '{category}' not found. Available: {', '.join(categories)}")
        return

    patterns = lib.list_category(category) if category else lib._cache.values()
    if not patterns:
        typer.echo("No patterns found.")
        return

    grouped: dict[str, list] = {}
    for p in sorted(patterns, key=lambda x: x.id):
        cat = p.id.split("/")[0]
        grouped.setdefault(cat, []).append(p)

    for cat in sorted(grouped):
        typer.echo(f"\n{cat}/")
        for p in grouped[cat]:
            dep_str = f" (depends: {len(p.depends)})" if p.depends else ""
            typer.echo(f"  {p.id} v{p.version}{dep_str} -- {p.description}")


@patterns_app.command("show")
def patterns_show(
    pattern_id: str = typer.Argument(..., help="Full pattern ID (e.g., components/nav)"),
):
    """Show pattern details."""
    lib = _get_library()
    p = lib.get(pattern_id)
    if p is None:
        typer.echo(f"Pattern '{pattern_id}' not found")
        raise typer.Exit(code=1)

    typer.echo(f"ID:          {p.id}")
    typer.echo(f"Name:        {p.name}")
    typer.echo(f"Version:     {p.version}")
    typer.echo(f"Description: {p.description}")
    typer.echo(f"Source repos: {', '.join(p.source_repos)}")
    typer.echo(f"Confidence:  {p.confidence}")
    typer.echo(f"Tags:        {', '.join(p.tags)}")

    if p.depends:
        typer.echo("Depends:")
        for d in p.depends:
            typer.echo(f"  - {d.id}" + (f" (version: {d.version})" if d.version else ""))

    dirs = p.get_dirs()
    files = p.get_files()
    slots = p.get_slots()
    templates = p.templates

    typer.echo(f"\nStructure:   {len(dirs)} dirs, {len(files)} files")
    typer.echo(f"Slots:       {len(slots)}")
    typer.echo(f"Templates:   {len(templates)}")

    if dirs:
        typer.echo("\nDirectories:")
        for d in dirs:
            req = " [required]" if d.required else ""
            typer.echo(f"  {d.path}{req}")

    if files:
        typer.echo("\nFiles:")
        for f in files:
            req = " [required]" if f.required else ""
            tmpl = f" (template: {f.template})" if f.template else ""
            typer.echo(f"  {f.path}{req}{tmpl}")

    if slots:
        typer.echo("\nSlots:")
        for name, slot in slots.items():
            req = " [required]" if slot.required else ""
            typer.echo(f"  {name}: {slot.path} ({slot.type}){req}")


@patterns_app.command("validate")
def patterns_validate():
    """Validate all patterns in the library."""
    lib = _get_library()
    total_issues = 0
    for p in lib._cache.values():
        issues = validate_pattern(p, lib)
        if issues:
            total_issues += len(issues)
            typer.echo(f"\n{p.id}:")
            for issue in issues:
                typer.echo(f"  - {issue}")
    if total_issues == 0:
        typer.echo("All patterns valid.")
    else:
        typer.echo(f"\n{total_issues} validation errors across {len(lib._cache)} patterns.", err=True)
        raise typer.Exit(code=1)


@patterns_app.command("search")
def patterns_search(
    query: str = typer.Argument(..., help="Search query"),
    source_repos: str | None = typer.Option(None, "--source-repos", "-s", help="Filter by source repos"),
):
    """Search patterns by keyword."""
    lib = _get_library()
    results = lib.search(query)
    if source_repos:
        results = [p for p in results if any(s in p.source_repos for s in source_repos.split(","))]

    if not results:
        typer.echo(f"No patterns matching '{query}'.")
        return

    typer.echo(f"Found {len(results)} pattern(s) matching '{query}':")
    for p in results:
        typer.echo(f"  {p.id} -- {p.name}")


# -- Scaffolding commands --


@app.command("scaffold")
def scaffold(
    project_name: str = typer.Argument(..., help="Project name (kebab-case)"),
    patterns: list[str] = typer.Option(..., "--patterns", "-p", help="Pattern IDs to compose"),
    title: str | None = typer.Option(None, "--title", "-t", help="Project title"),
    author: str | None = typer.Option(None, "--author", "-a", help="Author name"),
    version: str = typer.Option("0.1.0", "--version", "-v", help="Initial version"),
    output: Path | None = typer.Option(None, "--output", "-o", help="Output directory"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be scaffolded"),
):
    """Scaffold a new Fastblocks project from composed patterns."""
    lib = _get_library()

    if dry_run:
        resolved = []
        queue = list(patterns)
        seen: set[str] = set()
        while queue:
            pid = queue.pop(0)
            if pid in seen:
                continue
            p = lib.get(pid)
            if p is None:
                typer.echo(f"Pattern '{pid}' not found.", err=True)
                raise typer.Exit(code=1)
            resolved.append(p)
            seen.add(pid)
            for dep in p.get_dependency_ids():
                queue.append(dep)

        typer.echo(f"dry-run: Would scaffold '{project_name}' with {len(resolved)} patterns:")
        for p in resolved:
            typer.echo(f"  - {p.id} v{p.version}")
        return

    # Guard against path traversal
    if "/" in project_name or "\\" in project_name or ".." in project_name:
        typer.echo("Error: project_name must not contain '/', '\\', or '..'", err=True)
        raise typer.Exit(code=1)

    if output is None:
        output = Path.cwd() / project_name

    engine = ScaffoldingEngine(library=lib)
    try:
        result = engine.scaffold(
            project_name=project_name,
            patterns=patterns,
            output_dir=output,
            title=title,
            author=author,
            version=version,
        )
        typer.echo(f"Scaffolded '{project_name}' to {result}")
    except ValueError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1)


@app.command("scaffold-validate")
def scaffold_validate(
    project: Path = typer.Option(..., "--project", help="Path to scaffolded project"),
):
    """Validate a scaffolded project against its manifest."""
    lib = _get_library()
    engine = ScaffoldingEngine(library=lib)
    issues = engine.validate_project(project)
    if issues:
        typer.echo(f"Validation issues in {project}:")
        for i in issues:
            typer.echo(f"  - {i}")
        raise typer.Exit(code=1)
    typer.echo(f"{project} is valid.")
