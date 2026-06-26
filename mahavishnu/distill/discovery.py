"""Workflow discovery with quarantine invariant (Plan 5 Phase A.0).

The quarantine invariant is the load-bearing security claim for distilled
workflows: files under ``mahavishnu/workflows/distilled/`` are NOT
discoverable by runtime workflow discovery. They become discoverable only
via ``mahavishnu workflow publish`` (Phase C.2), which atomically moves the
file from ``distilled/`` to ``workflows/`` AND records the approval.

This module is the runtime half of the invariant. The filesystem half lives
in ``scripts/ci/check_workflow_quarantine.py`` and rejects at commit time
any non-quarantined file that lacks the required headers (or any file
named ``distilled_*.py`` directly under ``workflows/``).

If a future refactor of the glob breaks the invariant, the regression tests
in ``tests/unit/test_workflow_discovery.py`` will fail loudly.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Discovery configuration — central path constants
# ---------------------------------------------------------------------------

# Path relative to the repo root where workflows live.
# Top-level glob: ``*.py`` (NOT ``**/*.py``).
DISCOVERY_ROOT = Path("mahavishnu") / "workflows"
DISCOVERY_PATTERN = "*.py"

# Quarantine directory name. Files under ``mahavishnu/workflows/distilled/``
# MUST NOT be discoverable. Defense-in-depth: the glob already excludes
# this, but we ALSO skip explicitly in case of pattern drift.
QUARANTINE_DIR_NAME = "distilled"

# Subdirectories to skip unconditionally.
EXCLUDED_DIR_NAMES = frozenset({"__pycache__", "__init__.py"})

# Module attribute name set by @mahavishnu_workflow(...).
SPEC_ATTR = "__mahavishnu_workflow_spec__"


# ---------------------------------------------------------------------------
# iter_workflow_modules — the glob + quarantine filter
# ---------------------------------------------------------------------------


def iter_workflow_modules(repo_root: Path) -> list[Path]:
    """Yield path to each top-level workflow module under DISCOVERY_ROOT.

    Quarantine guarantee: NEVER yields any file under
    ``DISCOVERY_ROOT / QUARANTINE_DIR_NAME /``. The pattern is ``*.py``
    (not ``**/*.py``) — top-level only — and we explicitly skip
    ``QUARANTINE_DIR_NAME`` and ``__pycache__`` as defense-in-depth.

    Returns a list (not a generator) so callers can iterate multiple times
    and so the test assertion failures can show what leaked.

    Args:
        repo_root: Repository root directory (absolute path).

    Returns:
        List of absolute paths to ``*.py`` files directly under
        ``<repo_root>/mahavishnu/workflows/``.
    """
    workflows_dir = repo_root / DISCOVERY_ROOT
    if not workflows_dir.is_dir():
        return []

    results: list[Path] = []
    # Top-level glob ONLY. ``rglob`` would break the quarantine invariant.
    for path in workflows_dir.glob(DISCOVERY_PATTERN):
        # Defense-in-depth: skip if any parent segment is the quarantine dir.
        if QUARANTINE_DIR_NAME in path.relative_to(workflows_dir).parts:
            continue
        # Skip __pycache__ and any other excluded subdir (defense-in-depth).
        if any(part in EXCLUDED_DIR_NAMES for part in path.relative_to(workflows_dir).parts):
            continue
        # Skip __init__.py — not a workflow module.
        if path.stem == "__init__":
            continue
        results.append(path)

    return results


# ---------------------------------------------------------------------------
# discover_workflows — load + introspect decorated functions
# ---------------------------------------------------------------------------


def discover_workflows(repo_root: Path) -> list[dict[str, Any]]:
    """Discover all ``@mahavishnu_workflow``-decorated functions under
    ``<repo_root>/mahavishnu/workflows/`` (top-level only — quarantined
    files are excluded by ``iter_workflow_modules``).

    Returns a list of dicts with shape::

        {
            "workflow_id":  "<module-stem>",   # for non-dotted lookup
            "source_path":  "<absolute path>",
            "intent":       "<spec.intent>",
            "tags":         list[str],          # from spec.tags
            "work_pool":    "<spec.work_pool>",
            "schedule":     "<spec.schedule or None>",
            "description":  "<spec.description>",
            "module_name":  "<unique synthetic name for importlib>",
        }

    Modules that fail to import (syntax errors, missing dependencies) are
    skipped silently; the publish-time lint/QC step is the canonical
    surface for surfacing those errors.
    """
    results: list[dict[str, Any]] = []

    for module_path in iter_workflow_modules(repo_root):
        # Synthetic module name — must be unique per import. Use a stable
        # prefix + the absolute path so re-runs of discovery don't collide.
        module_name = f"_mahavishnu_wf_discovery_{abs(hash(str(module_path)))}"

        spec = importlib.util.spec_from_file_location(module_name, module_path)
        if spec is None or spec.loader is None:
            continue
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except Exception:
            # Module failed to import. Skip silently — publish-time QC will
            # surface this. We deliberately do not raise: discovery is
            # best-effort enumeration, not a gate.
            continue

        for attr_name in dir(module):
            attr = getattr(module, attr_name, None)
            if attr is None:
                continue
            wfspec = getattr(attr, SPEC_ATTR, None)
            if wfspec is None:
                continue

            results.append(
                {
                    "workflow_id": module_path.stem,
                    "source_path": str(module_path),
                    "intent": getattr(wfspec, "intent", ""),
                    "tags": list(getattr(wfspec, "tags", ())),
                    "work_pool": getattr(wfspec, "work_pool", "default"),
                    "schedule": getattr(wfspec, "schedule", None),
                    "description": getattr(wfspec, "description", ""),
                    "module_name": module_name,
                }
            )

    return results