"""Mahavishnu admin shell with workflow-specific formatters and helpers.

This module extends the Oneiric AdminShell with Mahavishnu-specific functionality
for workflow orchestration, repository management, and log viewing.

Example:
    >>> from mahavishnu.shell import MahavishnuShell
    >>> from mahavishnu.core.app import MahavishnuApp
    >>> app = MahavishnuApp()
    >>> shell = MahavishnuShell(app)
    >>> shell.start()
"""

__all__ = ["MahavishnuShell", "WorkflowFormatter", "LogFormatter", "RepoFormatter"]

# Mapping of export name -> (relative_module, attribute_name)
_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    "MahavishnuShell": (".adapter", "MahavishnuShell"),
    "WorkflowFormatter": (".formatters", "WorkflowFormatter"),
    "LogFormatter": (".formatters", "LogFormatter"),
    "RepoFormatter": (".formatters", "RepoFormatter"),
}


def __getattr__(name: str):
    """Lazy import to avoid heavy initialization on package import."""
    if entry := _LAZY_IMPORTS.get(name):
        from importlib import import_module

        module = import_module(entry[0], __name__)
        return getattr(module, entry[1])
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
