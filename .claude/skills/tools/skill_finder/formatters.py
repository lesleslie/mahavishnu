"""Output formatting for skill search results."""

from typing import List
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.markdown import Markdown
from rich.text import Text

from .search import SearchResult
from skill_parser import SkillMetadata


console = Console()


def format_results(results: List[SearchResult], query: str) -> Table:
    """
    Format search results as a Rich table.

    Args:
        results: List of SearchResult objects
        query: Original search query

    Returns:
        Rich Table object
    """
    table = Table(title=f"Search Results: '{query}'", show_header=True, header_style="bold magenta")
    table.add_column("Score", style="cyan", width=8)
    table.add_column("Skill", style="green", no_wrap=False)
    table.add_column("Match Type", style="yellow")
    table.add_column("Matched Terms", style="blue")

    for result in results:
        # Format score as percentage
        score_text = f"{result.score * 100:.0f}%"

        # Format matched terms
        terms = ", ".join(result.matched_terms[:3])  # Show max 3 terms
        if len(result.matched_terms) > 3:
            terms += f" (+{len(result.matched_terms) - 3})"

        table.add_row(score_text, result.skill_name, result.match_type, terms)

    return table


def format_skill_detail(skill: SkillMetadata) -> Panel:
    """
    Format detailed skill information as a Rich panel.

    Args:
        skill: SkillMetadata object

    Returns:
        Rich Panel object
    """
    # Build content
    content = f"""
[bold cyan]Name:[/bold cyan] {skill.name}
[bold cyan]System:[/bold cyan] {skill.system}

[bold yellow]Description:[/bold yellow]
{skill.description}

[bold yellow]Keywords:[/bold yellow] {', '.join(skill.keywords) if skill.keywords else 'None'}

[bold yellow]Symptoms:[/bold yellow] {', '.join(skill.symptoms) if skill.symptoms else 'None'}

[bold yellow]Use Cases:[/bold yellow] {', '.join(skill.use_cases) if skill.use_cases else 'None'}
"""

    # Related skills
    if skill.related_skills:
        content += "\n[bold yellow]Related Skills:[/bold yellow]\n"
        for related in skill.related_skills:
            content += f"  • {related.name} ({related.relationship_type})\n"

    # Referenced by
    if skill.referenced_by:
        content += f"\n[bold yellow]Referenced By:[/bold yellow] {', '.join(skill.referenced_by)}\n"

    # Statistics
    content += f"\n[bold dim]Statistics:[/bold dim]"
    content += f"\n  • Words: {skill.word_count:,}"
    content += f"\n  • Lines: {skill.line_count:,}"
    content += f"\n  • Examples: {'Yes' if skill.has_examples else 'No'}"
    content += f"\n  • Flowchart: {'Yes' if skill.has_flowchart else 'No'}"

    # File location
    content += f"\n\n[bold dim]Location:[/bold dim] {skill.file_path}"

    return Panel(content, title=f"Skill: {skill.name}", border_style="cyan")


def print_results(results: List[SearchResult], query: str) -> None:
    """
    Print search results to console.

    Args:
        results: List of SearchResult objects
        query: Original search query
    """
    if not results:
        console.print(f"[yellow]No results found for '{query}'[/yellow]")
        return

    table = format_results(results, query)
    console.print(table)


def print_skills(skills: List[SkillMetadata], title: str = "Skills") -> None:
    """
    Print a list of skills as a table.

    Args:
        skills: List of SkillMetadata objects
        title: Table title
    """
    if not skills:
        console.print("[yellow]No skills found[/yellow]")
        return

    table = Table(title=f"{title} ({len(skills)})", show_header=True, header_style="bold magenta")
    table.add_column("Name", style="green", no_wrap=False)
    table.add_column("System", style="cyan")
    table.add_column("Related", style="yellow")
    table.add_column("Words", style="blue")
    table.add_column("Examples", style="magenta")

    for skill in skills:
        table.add_row(
            skill.name,
            skill.system,
            str(len(skill.related_skills)),
            f"{skill.word_count:,}",
            "Yes" if skill.has_examples else "No"
        )

    console.print(table)


def print_skill_detail(skill: SkillMetadata) -> None:
    """
    Print detailed skill information.

    Args:
        skill: SkillMetadata object
    """
    panel = format_skill_detail(skill)
    console.print(panel)


def format_system_summary(skills: List[SkillMetadata]) -> Table:
    """
    Format system distribution summary as a table.

    Args:
        skills: List of all SkillMetadata objects

    Returns:
        Rich Table object
    """
    # Count skills per system
    system_counts = {}
    for skill in skills:
        system_counts[skill.system] = system_counts.get(skill.system, 0) + 1

    table = Table(title="System Distribution", show_header=True, header_style="bold magenta")
    table.add_column("System", style="cyan")
    table.add_column("Count", style="green")
    table.add_column("Percentage", style="yellow")

    total = len(skills)
    for system, count in sorted(system_counts.items(), key=lambda x: x[1], reverse=True):
        percentage = (count / total) * 100
        table.add_row(system, str(count), f"{percentage:.1f}%")

    return table
