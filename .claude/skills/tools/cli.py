"""CLI for skill parser tool."""

from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from skill_parser import build_reverse_references, parse_all_skills
import typer

console = Console()

app = typer.Typer(help="Skill Parser - Extract metadata from ecosystem skills")


@app.command()
def parse(
    skills_dir: Path = typer.Option(
        Path("/Users/les/.claude/skills"),
        "--skills-dir",
        "-s",
        help="Directory containing skill files",
        exists=True,
        dir_okay=True,
    ),
    output: Path | None = typer.Option(
        None, "--output", "-o", help="Output JSON file for parsed metadata"
    ),
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Show detailed parsing information"
    ),
):
    """Parse all skills and display summary statistics."""
    if verbose:
        console.print(f"[cyan]Parsing skills from:[/] {skills_dir}")

    skills = parse_all_skills(skills_dir)

    if not skills:
        console.print("[red]No skills found!")
        raise typer.Exit(1)

    # Build reverse references
    build_reverse_references(skills)

    # Display summary statistics
    console.print(f"\n✅ Successfully parsed [green]{len(skills)}[/] skills\n")

    # Summary table
    table = Table(title="Skill Summary")
    table.add_column("Skill Name", style="cyan")
    table.add_column("System", style="magenta")
    table.add_column("Related", style="green")
    table.add_column("Referenced By", style="blue")
    table.add_column("Words", style="yellow")

    for skill in skills:
        table.add_row(
            skill.name,
            skill.system,
            str(len(skill.related_skills)),
            str(len(skill.referenced_by)),
            str(skill.word_count),
        )

    console.print(table)

    # System breakdown
    console.print("\n[bold]Skills by System:[/]")
    system_counts: dict[str, int] = {}
    for skill in skills:
        system_counts[skill.system] = system_counts.get(skill.system, 0) + 1

    system_table = Table()
    system_table.add_column("System", style="magenta")
    system_table.add_column("Count", justify="right")
    for system, count in sorted(system_counts.items(), key=lambda x: x[1], reverse=True):
        system_table.add_row(system, str(count))
    console.print(system_table)

    # Export to JSON if requested
    if output:
        import json

        data = [s.to_dict() for s in skills]
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(data, indent=2))
        console.print(f"\n✅ Exported to [green]{output}[/]")


@app.command()
def show(
    skill_name: str = typer.Argument(..., help="Name of skill to show"),
    skills_dir: Path = typer.Option(
        Path("/Users/les/.claude/skills"),
        "--skills-dir",
        "-s",
        help="Directory containing skill files",
        exists=True,
        dir_okay=True,
    ),
):
    """Show detailed information about a specific skill."""
    skills = parse_all_skills(skills_dir)
    build_reverse_references(skills)

    # Find the skill
    skill = next((s for s in skills if s.name == skill_name), None)

    if not skill:
        console.print(f"[red]Skill '{skill_name}' not found![/]")
        console.print("\n[dim]Available skills:[/]")
        for s in skills:
            console.print(f"  - {s.name}")
        raise typer.Exit(1)

    # Display skill details
    console.print(
        Panel(
            f"[bold cyan]{skill.name}[/]\n\n[dim]{skill.description}[/]",
            title="Skill Details",
            border_style="blue",
        )
    )

    # Metadata
    console.print(f"\n[bold]File:[/] {skill.file_path}")
    console.print(f"[bold]System:[/] {skill.system}")

    # Keywords
    if skill.keywords:
        console.print(f"\n[bold]Keywords:[/] {', '.join(skill.keywords)}")

    # Related skills
    if skill.related_skills:
        console.print("\n[bold]Related Skills:[/]")
        for related in skill.related_skills:
            console.print(f"  - {related.name} ({related.relationship_type})")

    # Referenced by
    if skill.referenced_by:
        console.print("\n[bold]Referenced By:[/]")
        for ref in skill.referenced_by:
            console.print(f"  - {ref}")

    # Statistics
    console.print("\n[bold]Statistics:[/]")
    console.print(f"  Words: {skill.word_count}")
    console.print(f"  Lines: {skill.line_count}")
    console.print(f"  Has Examples: {'Yes' if skill.has_examples else 'No'}")
    console.print(f"  Has Flowchart: {'Yes' if skill.has_flowchart else 'No'}")


@app.command()
def validate(
    skills_dir: Path = typer.Option(
        Path("/Users/les/.claude/skills"),
        "--skills-dir",
        "-s",
        help="Directory containing skill files",
        exists=True,
        dir_okay=True,
    ),
):
    """Validate all skills and report issues."""
    skills = parse_all_skills(skills_dir)

    issues_found = False

    # Check for orphaned skills (no references)
    orphans = [
        s
        for s in skills
        if not s.referenced_by
        and s.name
        not in {
            "error-handling",  # Core skills may not be referenced
            "mcp-integration",
            "observability",
            "testing-strategies",
        }
    ]

    if orphans:
        issues_found = True
        console.print("[yellow]Potentially orphaned skills (not referenced):[/]")
        for skill in orphans:
            console.print(f"  - {skill.name} ({skill.system})")

    # Check for broken references
    skill_names = {s.name for s in skills}
    broken_refs = []
    for skill in skills:
        for related in skill.related_skills:
            if related.name not in skill_names:
                broken_refs.append((skill.name, related.name))

    if broken_refs:
        issues_found = True
        console.print("\n[red]Broken references:[/]")
        for source, target in broken_refs:
            console.print(f"  - {source} → {target}")

    if not issues_found:
        console.print("[green]✅ All skills validated successfully![/]")
    else:
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
