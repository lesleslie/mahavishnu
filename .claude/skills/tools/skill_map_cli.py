"""Command-line interface for skill map visualization."""

from pathlib import Path

from rich.console import Console
from rich.table import Table
from skill_map import (
    SkillGraph,
    analyze_centrality,
    build_graph,
    detect_clusters,
    export_graphviz,
    export_json,
    export_mermaid,
    export_system_matrix,
    find_all_paths,
    find_bridge_skills,
    find_central_topics,
    find_learning_path,
    find_orphan_skills,
    get_prerequisite_skills,
    get_statistics_summary,
)
from skill_parser import build_reverse_references, parse_all_skills
import typer

app = typer.Typer()
console = Console()


def get_graph(skills_dir: Path = None) -> SkillGraph:
    """Get or build skill graph."""
    if skills_dir is None:
        skills_dir = Path("/Users/les/.claude/skills")

    skills = parse_all_skills(skills_dir)
    build_reverse_references(skills)
    return build_graph(skills)


@app.command()
def graph(
    skills_dir: Path = typer.Option(None, "--skills-dir", "-s", help="Path to skills directory"),
    format: str = typer.Option(
        "mermaid", "--format", "-f", help="Export format (mermaid, graphviz, json)"
    ),
    output: Path = typer.Option(None, "--output", "-o", help="Output file path"),
):
    """
    Generate skill relationship graph.

    Examples:
        skill-map graph --format mermaid
        skill-map graph --format graphviz --output skills.dot
        skill-map graph --format json --output skills.json
    """
    graph = get_graph(skills_dir)

    if format == "mermaid":
        content = export_mermaid(graph)
        ext = ".mmd"
    elif format == "graphviz":
        content = export_graphviz(graph)
        ext = ".dot"
    elif format == "json":
        content = export_json(graph)
        ext = ".json"
    else:
        console.print(f"[red]Unknown format: {format}[/red]")
        raise typer.Exit(1)

    if output is None:
        output = Path(f"skill_graph{ext}")

    output.write_text(content)
    console.print(f"[green]✓ Graph exported to {output}[/green]")


@app.command()
def path(
    start: str = typer.Argument(..., help="Starting skill name"),
    end: str = typer.Argument(..., help="Target skill name"),
    skills_dir: Path = typer.Option(None, "--skills-dir", "-s", help="Path to skills directory"),
    all_paths: bool = typer.Option(False, "--all", "-a", help="Find all paths"),
):
    """
    Find learning path between two skills.

    Examples:
        skill-map path testing-strategies error-handling
        skill-map path orchestrate-workflow observability --all
    """
    graph = get_graph(skills_dir)

    if all_paths:
        paths = find_all_paths(graph, start, end, max_paths=10)
        if not paths:
            console.print(f"[yellow]No paths found from '{start}' to '{end}'[/yellow]")
            return

        table = Table(
            title=f"All Paths: {start} → {end}", show_header=True, header_style="bold magenta"
        )
        table.add_column("Path", style="cyan")
        table.add_column("Length", style="green")

        for i, path in enumerate(paths, 1):
            path_str = " → ".join(path)
            table.add_row(f"Path {i}", path_str)

        console.print(table)
    else:
        path = find_learning_path(graph, start, end)
        if not path:
            console.print(f"[yellow]No path found from '{start}' to '{end}'[/yellow]")
            return

        console.print(f"[cyan]Shortest Path:[/cyan] {' → '.join(path)}")


@app.command()
def clusters(
    skills_dir: Path = typer.Option(None, "--skills-dir", "-s", help="Path to skills directory"),
):
    """
    Show skill clusters by system.

    Examples:
        skill-map clusters
    """
    graph = get_graph(skills_dir)
    clusters = detect_clusters(graph)

    table = Table(title="Skill Clusters by System", show_header=True, header_style="bold magenta")
    table.add_column("System", style="cyan")
    table.add_column("Skills", style="green")
    table.add_column("Count", style="yellow")

    for system, skills in sorted(clusters.items()):
        skill_list = ", ".join(sorted(skills)[:5])
        if len(skills) > 5:
            skill_list += f" (+{len(skills) - 5} more)"
        table.add_row(system, skill_list, str(len(skills)))

    console.print(table)


@app.command()
def orphans(
    skills_dir: Path = typer.Option(None, "--skills-dir", "-s", help="Path to skills directory"),
):
    """
    Find orphaned skills with no relationships.

    Examples:
        skill-map orphans
    """
    graph = get_graph(skills_dir)
    orphans = find_orphan_skills(graph)

    if not orphans:
        console.print("[green]No orphan skills found[/green]")
        return

    table = Table(title="Orphan Skills", show_header=True, header_style="bold magenta")
    table.add_column("Skill", style="cyan")
    table.add_column("System", style="yellow")
    table.add_column("Description", style="green")

    for skill_name in orphans:
        skill = graph.skills[skill_name]
        desc = skill.description[:60] + "..." if len(skill.description) > 60 else skill.description
        table.add_row(skill_name, skill.system, desc)

    console.print(table)


@app.command()
def central(
    skills_dir: Path = typer.Option(None, "--skills-dir", "-s", help="Path to skills directory"),
    top_n: int = typer.Option(10, "--top", "-n", help="Number of top skills to show"),
):
    """
    Show most central skills (PageRank).

    Examples:
        skill-map central
        skill-map central --top 20
    """
    graph = get_graph(skills_dir)
    centrality = analyze_centrality(graph)

    table = Table(
        title=f"Top {top_n} Central Skills", show_header=True, header_style="bold magenta"
    )
    table.add_column("Rank", style="dim")
    table.add_column("Skill", style="cyan")
    table.add_column("System", style="yellow")
    table.add_column("PageRank", style="green")
    table.add_column("Description", style="blue")

    for i, (skill_name, score) in enumerate(centrality[:top_n], 1):
        skill = graph.skills[skill_name]
        desc = skill.description[:50] + "..." if len(skill.description) > 50 else skill.description
        table.add_row(str(i), skill_name, skill.system, f"{score:.4f}", desc)

    console.print(table)


@app.command()
def prerequisites(
    skill_name: str = typer.Argument(..., help="Skill name"),
    skills_dir: Path = typer.Option(None, "--skills-dir", "-s", help="Path to skills directory"),
):
    """
    Show prerequisites for a skill.

    Examples:
        skill-map prerequisites orchestrate-workflow
    """
    graph = get_graph(skills_dir)

    if skill_name not in graph.skills:
        console.print(f"[red]Skill '{skill_name}' not found[/red]")
        raise typer.Exit(1)

    prereqs = get_prerequisite_skills(graph, skill_name)

    console.print(f"[cyan]Prerequisites for: {skill_name}[/cyan]\n")

    if prereqs["direct"]:
        console.print("[bold yellow]Direct Prerequisites:[/bold yellow]")
        for skill in prereqs["direct"]:
            console.print(f"  • {skill}")

    if prereqs["transitive"]:
        console.print("\n[bold yellow]Transitive Prerequisites:[/bold yellow]")
        for skill in prereqs["transitive"]:
            console.print(f"  • {skill}")

    if not prereqs["direct"] and not prereqs["transitive"]:
        console.print("[dim]No prerequisites found[/dim]")


@app.command()
def stats(
    skills_dir: Path = typer.Option(None, "--skills-dir", "-s", help="Path to skills directory"),
):
    """
    Show comprehensive statistics about the skill graph.

    Examples:
        skill-map stats
    """
    graph = get_graph(skills_dir)
    summary = get_statistics_summary(graph)
    console.print(summary)


@app.command()
def bridges(
    skills_dir: Path = typer.Option(None, "--skills-dir", "-s", help="Path to skills directory"),
):
    """
    Find bridge skills (critical connections).

    Examples:
        skill-map bridges
    """
    graph = get_graph(skills_dir)
    bridges = find_bridge_skills(graph)

    if not bridges:
        console.print("[green]No bridge skills found[/green]")
        return

    table = Table(
        title="Bridge Skills (Critical Connections)", show_header=True, header_style="bold magenta"
    )
    table.add_column("Source", style="cyan")
    table.add_column("Target", style="green")

    for source, target in bridges:
        table.add_row(source, target)

    console.print(table)


@app.command()
def topics(
    skills_dir: Path = typer.Option(None, "--skills-dir", "-s", help="Path to skills directory"),
    top_n: int = typer.Option(10, "--top", "-n", help="Number of topics to show"),
):
    """
    Find central topics (betweenness centrality).

    Examples:
        skill-map topics
        skill-map topics --top 15
    """
    graph = get_graph(skills_dir)
    topics = find_central_topics(graph, top_n=top_n)

    table = Table(
        title=f"Top {top_n} Central Topics", show_header=True, header_style="bold magenta"
    )
    table.add_column("Rank", style="dim")
    table.add_column("Skill", style="cyan")
    table.add_column("Betweenness", style="green")

    for i, (skill_name, score) in enumerate(topics, 1):
        table.add_row(str(i), skill_name, f"{score:.4f}")

    console.print(table)


@app.command()
def matrix(
    skills_dir: Path = typer.Option(None, "--skills-dir", "-s", help="Path to skills directory"),
):
    """
    Show system connection matrix.

    Examples:
        skill-map matrix
    """
    graph = get_graph(skills_dir)
    matrix_str = export_system_matrix(graph)
    console.print(matrix_str)


if __name__ == "__main__":
    app()
