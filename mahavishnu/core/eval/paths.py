"""Path confinement for evaluation datasets (REQ-EVAL-002).

The eval MCP tools and the eval pool are server-reachable: a client
names a dataset path and the server reads it. Without confinement, a
client could name any file the server can read.

This module resolves a dataset path and asserts it stays inside an
operator-configured root. It mirrors
:func:`mahavishnu.mcp.crow.path_security.resolve_workspace_path`, which
does the same job for the Crow terminal adapter; it is duplicated here
rather than imported because ``mahavishnu.mcp`` pulls in the MCP
server, and the eval core must stay importable without it.

The operator's own shell is **not** a trust boundary. ``mahavishnu eval
run-suite --suite <path>`` is a local command an operator typed, and it
is not confined: refusing a path the operator just named would be
useless friction, not safety.
"""

from __future__ import annotations

from pathlib import Path

from mahavishnu.core.errors import EvalDatasetLoadError

# req: REQ-EVAL-002


def resolve_dataset_path(path: str | Path, root: str | Path) -> Path:
    """Resolve a dataset path and assert it stays inside ``root``.

    The resolution is symlink-aware: ``root`` and the candidate are both
    fully resolved before the containment check, so a symlink inside the
    root cannot point out of it.

    Args:
        path: The dataset path the caller named.
        root: The directory the dataset must live inside.

    Returns:
        The resolved path.

    Raises:
        EvalDatasetLoadError: If the path is empty, contains a null byte,
            or resolves outside ``root``.
    """
    raw = str(path)
    if not raw.strip():
        raise EvalDatasetLoadError("the dataset path is empty")
    if "\x00" in raw:
        raise EvalDatasetLoadError("the dataset path contains a null byte")

    resolved_root = Path(root).expanduser().resolve()
    try:
        resolved = Path(raw).expanduser().resolve()
    except OSError as exc:
        raise EvalDatasetLoadError(
            f"cannot resolve the dataset path {raw!r}: {exc}",
            details={"path": raw},
        ) from exc

    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise EvalDatasetLoadError(
            f"the dataset path {resolved} is outside the eval dataset root "
            f"{resolved_root}",
            details={"path": str(resolved), "root": str(resolved_root)},
        ) from exc
    return resolved


__all__ = ["resolve_dataset_path"]
