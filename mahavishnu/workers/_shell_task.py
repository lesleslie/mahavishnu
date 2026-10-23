"""Module-level Shepherd task backing the ``command`` shortcut.

req: REQ-BIFROST-033 (worker substrate)

This module exists to be *registerable*, and that constraint dictates its
shape. Shepherd's ``TaskLibrary.register`` reads the source of the module
that defines a task and refuses two things:

- a body that is not introspectable (so no per-call closure);
- **any relative import anywhere in the defining module**.

``shepherd_backend.py`` is full of relative imports, so a task defined there
can never be registered::

    TaskRegistrationError: task source
    'mahavishnu.workers.shepherd_backend:_run_shell_command'
    uses relative import at line 55; register an explicit task bundle instead

The task body here needs nothing from the package -- it returns a staged
string -- so the module declares no imports whatsoever. That is the whole
reason it is separate, and it should stay that way: adding an import here
silently breaks command dispatch again.

The command is staged here rather than captured in a closure because the
task is registered once and reused. Shepherd keys a registered task by its
import path, so every dispatch must resolve to the same callable; only the
staged value varies.
"""

from __future__ import annotations

# Absolute import only. Shepherd rejects a defining module containing a
# *relative* import, and it resolves the annotation below through
# ``typing.get_type_hints``, which needs ``GitRepo`` in this module's globals --
# so it cannot move into a TYPE_CHECKING block despite being used only in an
# annotation.
from shepherd import GitRepo  # noqa: TC002, RUF100

#: Command staged for the next shell dispatch.
_PENDING_COMMAND: dict[str, str] = {"value": ""}


def set_command(value: str) -> None:
    """Stage the command the next :func:`run_shell_command` will return."""
    _PENDING_COMMAND["value"] = value


def run_shell_command(repo: GitRepo) -> str:
    """Return the staged command.

    ``repo`` is the workspace grant the substrate binds. It is declared purely
    for the confinement contract -- Shepherd refuses a run whose signature
    carries no ``GitRepo`` handle, and it is what compiles the set of
    resources this task is permitted to touch. The parameter is unused here
    because the task's body is a single staged string.

    The substrate consumes this string as the command to execute. Callers are
    responsible for validating it first -- ``_exec_guard`` runs at the
    ``execute`` boundary, before the command reaches here.
    """
    return _PENDING_COMMAND["value"]