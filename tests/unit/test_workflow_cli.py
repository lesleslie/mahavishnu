#!/usr/bin/env python3
"""Smoke tests for I12-2 canonical workflow and adapter CLI commands.

Run standalone:  python tests/unit/test_workflow_cli.py
Does NOT use pytest to avoid MahavishnuApp init timeout (known I9 issue).

CLI help integration tests should be run manually:
  uv run mahavishnu workflow --help
  uv run mahavishnu adapter --help
"""

from __future__ import annotations

import ast
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent.parent


def get_source() -> str:
    return (ROOT / "mahavishnu" / "_main_cli.py").read_text()


def get_functions(source: str) -> list[str]:
    return [
        n.name
        for n in ast.walk(ast.parse(source))
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]


def get_async_functions(source: str) -> list[str]:
    return [n.name for n in ast.walk(ast.parse(source)) if isinstance(n, ast.AsyncFunctionDef)]


def check(condition: bool, msg: str) -> None:
    if not condition:
        print(f"  ❌ {msg}")
        sys.exit(1)
    print(f"  ✅ {msg}")


def main() -> None:
    source = get_source()
    funcs = get_functions(source)
    async_funcs = get_async_functions(source)
    failures = 0

    print("=== Workflow sub-app ===")
    for name in [
        "workflow_sweep",
        "workflow_quality_check",
        "workflow_heal",
        "workflow_fix",
        "workflow_review",
    ]:
        if name in funcs:
            print(f"  ✅ {name}")
        else:
            print(f"  ❌ {name} MISSING")
            failures += 1

    print("\n=== Adapter sub-app ===")
    for name in ["adapter_list_cmd", "adapter_resolve_cmd", "adapter_health_cmd"]:
        if name in funcs:
            print(f"  ✅ {name}")
        else:
            print(f"  ❌ {name} MISSING")
            failures += 1

    print("\n=== Async helpers ===")
    for name in [
        "_async_trigger_workflow",
        "_async_heal_workflows",
        "_async_fix_orchestrate",
        "_async_review_and_fix",
        "_async_adapter_list",
        "_async_adapter_resolve",
        "_async_adapter_health",
    ]:
        if name in async_funcs:
            print(f"  ✅ {name}")
        else:
            print(f"  ❌ {name} MISSING")
            failures += 1

    print("\n=== Sub-app registration ===")
    check("workflows_app" in source, "workflows_app defined")
    check('name="workflow"' in source, "workflow sub-app registered")
    check("adapter_app" in source, "adapter_app defined")
    check('name="adapter"' in source, "adapter sub-app registered")

    print("\n=== Correct imports ===")
    check("from .core.dead_letter_queue import DeadLetterQueue" in source, "DLQ import")
    check(
        "from .core.fix_orchestrator import FixOrchestrator, FixTask" in source,
        "FixOrchestrator import",
    )
    check("from .core.task_router import TaskRouter" in source, "TaskRouter import")
    check(
        "from .core.adapter_registry import HybridAdapterRegistry" in source,
        "HybridAdapterRegistry import",
    )
    check(
        "from .mcp.tools.self_improvement_tools import ReviewScope, SelfImprovementTools" in source,
        "SelfImprovementTools import",
    )

    print("\n=== Correct API usage ===")
    check("dlq.retry_task" in source, "Heal uses DLQ retry_task")
    check(
        "execute_fix(pool_id=pool_id, task=task)" in source, "FixOrchestrator call without timeout"
    )
    check("SelfImprovementTools(maha_app)" in source, "Review creates MahavishnuApp")
    check("TaskType(task_type)" in source, "Adapter resolve uses TaskType enum")
    check(
        "await registry.check_all_health()" in source, "Adapter health uses async check_all_health"
    )

    print("\n=== Legacy sweep backward compat ===")
    check("def sweep(" in source, "Legacy sweep still exists")
    check("workflow sweep" in source, "Legacy sweep mentions canonical path")

    if failures:
        print(f"\n❌ {failures} checks failed")
        sys.exit(1)
    else:
        print("\n✅ All checks passed")


if __name__ == "__main__":
    main()
