"""CLI commands for repo diff and PR creation (Plan 3 Tier 1).

Provides two thin wrappers around the system ``git`` and ``gh`` CLIs, scoped
to paths registered in ``settings/repos.yaml``. The catalog is loaded once at
module import; paths not in the catalog raise ``ValueError``.
"""

from __future__ import annotations

from pathlib import Path
import subprocess

import typer
import yaml

REPOS_CATALOG_PATH = Path("settings/repos.yaml")

repo_app = typer.Typer(help="Repository diff and PR creation commands")


def _load_catalog() -> dict[str, str]:
    """Load the repos catalog and return a {nickname: absolute_path} map."""
    catalog_file = Path(__file__).resolve().parents[1] / REPOS_CATALOG_PATH
    if not catalog_file.exists():
        return {}
    with catalog_file.open() as fh:
        data = yaml.safe_load(fh) or {}
    repos = data.get("repos", []) or []
    return {str(r.get("path", "")): str(r.get("nickname") or r.get("name") or "") for r in repos}


_CATALOG: dict[str, str] = _load_catalog()


def _ensure_catalog(path: str) -> None:
    """Raise ValueError if ``path`` is not in the loaded catalog."""
    if path not in _CATALOG:
        raise ValueError(f"Repository path '{path}' not in repo catalog")


def diff_repo(
    path: str,
    ref1: str = "HEAD",
    ref2: str = "main",
) -> str:
    """Run ``git diff <ref1>..<ref2>`` inside the given repo path.

    Args:
        path: Absolute filesystem path of the repository. Must be in the
            loaded repos catalog.
        ref1: First ref (left side of ``..``). Defaults to ``HEAD``.
        ref2: Second ref (right side of ``..``). Defaults to ``main``.

    Returns:
        The diff text captured from git.

    Raises:
        ValueError: If ``path`` is not in the repos catalog.
        subprocess.CalledProcessError: If ``git diff`` exits non-zero.
    """
    _ensure_catalog(path)
    cmd = ["git", "diff", f"{ref1}..{ref2}"]
    result = subprocess.run(
        cmd,
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def create_pr(path: str) -> str:
    """Create a pull request via ``gh pr create`` in the given repo path.

    Args:
        path: Absolute filesystem path of the repository. Must be in the
            loaded repos catalog.

    Returns:
        The PR URL emitted by ``gh pr create`` (stripped).

    Raises:
        ValueError: If ``path`` is not in the repos catalog.
        subprocess.CalledProcessError: If ``gh pr create`` exits non-zero.
    """
    _ensure_catalog(path)
    cmd = ["gh", "pr", "create", "--fill"]
    result = subprocess.run(
        cmd,
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


@repo_app.command("diff")
def diff_command(
    path: str = typer.Option(..., "--path", "-p", help="Repository absolute path"),
    ref1: str = typer.Option("HEAD", "--ref1", help="Left ref"),
    ref2: str = typer.Option("main", "--ref2", help="Right ref"),
) -> None:
    """Show the diff between two refs in a registered repo."""
    output = diff_repo(path, ref1=ref1, ref2=ref2)
    typer.echo(output)


@repo_app.command("pr-create")
def pr_create_command(
    path: str = typer.Option(..., "--path", "-p", help="Repository absolute path"),
) -> None:
    """Create a PR via ``gh pr create`` for the given repo."""
    url = create_pr(path)
    typer.echo(url)