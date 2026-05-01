"""Command-line interface for skill finder."""

import typer
from pathlib import Path
from rich.console import Console

from skill_finder import (
    SearchIndex,
    fuzzy_search,
    exact_search,
    search_by_system,
    search_by_keyword,
    format_system_summary,
    print_results,
    print_skills,
    print_skill_detail,
)
from skill_parser import parse_all_skills, build_reverse_references

app = typer.Typer()
console = Console()


def get_index(skills_dir: Path = None) -> SearchIndex:
    """
    Get or build search index.

    Args:
        skills_dir: Optional skills directory path

    Returns:
        SearchIndex object
    """
    from skill_finder import load_index

    return load_index()


@app.command()
def search(
    query: str = typer.Argument(..., help="Search query"),
    limit: int = typer.Option(5, "--limit", "-l", help="Maximum number of results"),
    skills_dir: Path = typer.Option(
        None,
        "--skills-dir",
        "-s",
        help="Path to skills directory"
    ),
):
    """
    Fuzzy search for skills by keyword, symptom, or description.

    Examples:
        skill-finder search "testing"
        skill-finder search "workflow" --limit 10
        skill-finder search "session management"
    """
    index = get_index(skills_dir)
    results = fuzzy_search(query, index, limit=limit)
    print_results(results, query)


@app.command()
def list(
    system: str = typer.Option(None, "--system", "-s", help="Filter by system"),
    keyword: str = typer.Option(None, "--keyword", "-k", help="Filter by keyword"),
    skills_dir: Path = typer.Option(
        None,
        "--skills-dir",
        help="Path to skills directory"
    ),
):
    """
    List all skills or filter by system/keyword.

    Examples:
        skill-finder list
        skill-finder list --system mahavishnu
        skill-finder list --keyword testing
    """
    index = get_index(skills_dir)

    # Filter skills
    if system:
        skill_names = search_by_system(system, index)
        skills = [index.skills[name] for name in skill_names]
        print_skills(skills, f"Skills in {system}")
    elif keyword:
        skill_names = search_by_keyword(keyword, index)
        skills = [index.skills[name] for name in skill_names]
        print_skills(skills, f"Skills with '{keyword}'")
    else:
        # Show system summary instead
        skills = list(index.skills.values())
        table = format_system_summary(skills)
        console.print(table)


@app.command()
def show(
    skill_name: str = typer.Argument(..., help="Exact skill name"),
    skills_dir: Path = typer.Option(
        None,
        "--skills-dir",
        help="Path to skills directory"
    ),
):
    """
    Show detailed information about a specific skill.

    Examples:
        skill-finder show testing-strategies
        skill-finder show orchestrate-workflow
    """
    index = get_index(skills_dir)

    # Try exact match first
    matches = exact_search(skill_name, index)

    if not matches:
        console.print(f"[red]Skill '{skill_name}' not found[/red]")
        console.print("\n[yellow]Try:[/yellow]")
        console.print("  • Use 'skill-finder search \"query\"' to search")
        console.print("  • Use 'skill-finder list' to see all skills")
        raise typer.Exit(1)

    skill = index.skills[matches[0]]
    print_skill_detail(skill)


@app.command()
def rebuild(
    skills_dir: Path = typer.Option(
        Path("/Users/les/.claude/skills"),
        "--skills-dir",
        "-s",
        help="Path to skills directory"
    ),
    output: Path = typer.Option(
        None,
        "--output",
        "-o",
        help="Output index file path"
    ),
):
    """
    Rebuild the search index from scratch.

    Examples:
        skill-finder rebuild
        skill-finder rebuild --skills-dir /path/to/skills
        skill-finder rebuild --output custom_index.json
    """
    from skill_finder import build_index, save_index

    console.print(f"[cyan]Parsing skills from {skills_dir}...[/cyan]")

    # Parse all skills
    skills = parse_all_skills(skills_dir)
    build_reverse_references(skills)

    console.print(f"[green]✓ Parsed {len(skills)} skills[/green]")

    # Build index
    index = build_index(skills_dir)

    # Save index
    if output is None:
        output = Path(__file__).parent.parent / "data" / "skill_index.json"

    save_index(index, output)
    console.print(f"[green]✓ Index saved to {output}[/green]")

    # Show summary
    table = format_system_summary(list(index.skills.values()))
    console.print(table)


@app.command()
def systems(
    skills_dir: Path = typer.Option(
        None,
        "--skills-dir",
        help="Path to skills directory"
    ),
):
    """
    Show system distribution summary.

    Examples:
        skill-finder systems
    """
    index = get_index(skills_dir)
    skills = list(index.skills.values())
    table = format_system_summary(skills)
    console.print(table)


if __name__ == "__main__":
    app()
