---
status: active
role: canonical
date: 2026-07-16
last_reviewed: 2026-07-16
topic: wire-up-contract
---

# Wire-up contract

## Context

Mahavishnu has shipped features whose code merged but whose entry points
were never registered: no CLI command, no MCP tool, no workflow handler,
no FastAPI route. The implementation was correct and tested, but no
production path called it — a "built but not wired" failure mode.

The gap was structural: existing plan templates (`docs/plans/`) do not
require an integration section, the feature delivery workflow
(`.claude/commands/workflows/feature/feature-delivery-lifecycle.md`) had
no Wiring phase, and CLAUDE.md contained no rule tying plan completion
to wiring evidence.

## Decision rule

1. **Every plan uses `docs/plans/TEMPLATE.md`.** No plan is "done" if
   any phase deliverable lacks an Integration Contract block.
1. **Every Integration Contract specifies**:
   - **Triggered from** — the exact entry point (CLI command path, MCP
     tool name, HTTP route, scheduler, or upstream caller).
   - **Returns to / updates** — the destination state, store, or
     downstream artifact that the wired code mutates.
   - **Demonstrable by** — one concrete check (CLI command, HTTP
     request, log line, or test name) that proves the wiring works
     end-to-end. If you cannot name the check, the wiring does not
     exist.
   - **Rollback signal** — a log line, metric threshold, or alert that
     tells the operator to revert.
   - **Observability added** — the OTel span, metric, or log line that
     makes this wiring visible in production.
1. **Run `python scripts/audit_orphans.py` before declaring a feature
   complete.** Treat zero-caller symbols reported within the lookback
   window as either (a) wires that need connecting, or (b) code that
   should be removed. Both are acceptable; silent orphans are not.
1. **Track `{built, wired, adopted}` state** for every feature in
   `docs/feature-tracking/<slug>.md` (template at
   `docs/feature-tracking/TEMPLATE.md`). Persist a one-line state
   summary to Session-Buddy via `mcp__session-buddy__store_reflection`
   with tags `["feature-tracking", "<slug>", "wire-up-state"]`.
1. **Follow the `feature-delivery-lifecycle` workflow** which now
   includes a Wiring phase between Design and Validate.

## Examples

**Bad** (built but not wired):

```python
# mahavishnu/cli/experiments_cli.py
def run_experiment(config: ExperimentConfig) -> Result:
    """Execute an A/B experiment configuration."""
    ...
```

- No `@app.command(...)` registration → not exposed via the CLI.
- No call site in `mahavishnu/_main_cli.py` or any workflow orchestrator.
- `scripts/audit_orphans.py` reports `run_experiment` as a recent
  zero-caller symbol.

**Good** (built AND wired):

```python
# mahavishnu/cli/experiments_cli.py
@app.command("run")
def run_experiment(config_path: Path) -> None:
    """Execute an A/B experiment configuration."""
    config = ExperimentConfig.load(config_path)
    result = asyncio.run(experiment_runtime.run(config))
    typer.echo(result.summary())
```

- Registered as `mahavishnu experiment run <config>` (Triggered from).
- Result lands in `mahavishnu/state/experiments.db` (Returns to).
- Demonstrable by: `mahavishnu experiment run configs/demo.yaml`
  (Demonstrable by).
- Rollback signal: `experiments.run.duration.p99 > 30s` alert
  (Rollback signal).
- Observability added: OTel span `experiment.run` with attribute
  `experiment.id` (Observability added).

## References

- `docs/plans/TEMPLATE.md` — required template
- `docs/feature-tracking/TEMPLATE.md` — feature-state template
- `scripts/audit_orphans.py` — orphan-detection script
- `.claude/commands/workflows/feature/feature-delivery-lifecycle.md` —
  workflow with Wiring phase
- `CLAUDE.md` § Process Discipline — user-facing summary

## Status <!-- legacy status: Active — see YAML frontmatter -->

Established 2026-07-07. Supersedes the absence of any prior rule on
this topic.
