"""CLI commands for code graph indexing."""

from __future__ import annotations

import typer

from mahavishnu.core.code_index.path_validation import validate_repo_path

index_app = typer.Typer(help="Code graph indexing commands")


@index_app.command("repo")
def index_single_repo(
    repo: str = typer.Argument(help="Path to the repository"),
    full: bool = typer.Option(False, "--full", help="Full re-index (ignore last indexed commit)"),
    trigger: str = typer.Option("manual", "--trigger", help="Trigger type for logging"),
):
    """Index a single repository's code graph."""
    from mahavishnu.core.code_index.indexer import index_repo

    validated_path = validate_repo_path(repo)
    typer.echo(f"Indexing {validated_path}...")
    result = index_repo(validated_path, trigger=trigger, full=full)
    typer.echo(
        f"Status: {result.status} | "
        f"Files: {len(result.files_changed)} | "
        f"Failures: {result.parse_failures}"
    )
    if result.status == "failed":
        raise typer.Exit(code=1)


@index_app.command("status")
def index_status():
    """Show indexing status for all registered repos."""
    from mahavishnu.core.code_index.indexer import get_last_indexed_commit
    from mahavishnu.core.code_index.path_validation import get_registered_repos

    repos = get_registered_repos()
    if not repos:
        typer.echo("No repositories registered in repos.yaml")
        return

    typer.echo(f"Registered repos: {len(repos)}")
    for repo in sorted(repos):
        last = get_last_indexed_commit(repo)
        status = f"last indexed: {last[:8]}" if last else "not indexed"
        typer.echo(f"  {repo}: {status}")


@index_app.command("install-hooks")
def install_repo_hooks(
    repo: str = typer.Argument(help="Path to the repository"),
    force: bool = typer.Option(False, "--force", help="Overwrite existing hooks"),
):
    """Install git hooks for automatic code graph indexing."""
    from mahavishnu.core.code_index.git_hooks import install_hooks

    validated_path = validate_repo_path(repo)
    installed = install_hooks(validated_path, force=force)
    typer.echo(f"Installed hooks: {', '.join(installed)}")


@index_app.command("uninstall-hooks")
def uninstall_repo_hooks(
    repo: str = typer.Argument(help="Path to the repository"),
):
    """Remove mahavishnu-managed git hooks."""
    from mahavishnu.core.code_index.git_hooks import uninstall_hooks

    validated_path = validate_repo_path(repo)
    removed = uninstall_hooks(validated_path)
    typer.echo(f"Removed hooks: {', '.join(removed) or 'none'}")


def add_index_commands(app: typer.Typer) -> None:
    """Register index commands with the main CLI app."""
    app.add_typer(index_app, name="index")
