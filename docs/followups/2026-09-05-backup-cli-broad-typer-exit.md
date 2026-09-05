---
status: complete
role: historical
date: 2026-09-05
last_reviewed: 2026-09-05
topic: backup-cli-broad-typer-exit
---

# `backup_cli.py` broad `except Exception` catches `typer.Exit` — double-print bug

## Status

**Resolved (2026-09-05)** — production fix at `mahavishnu/backup_cli.py:20-31`
(`_do_backup_create` restructured: `raise typer.Exit(code=1)` moved out of the
try block) and `mahavishnu/backup_cli.py:67-78` (same restructure for
`_do_backup_restore`). Regression test at
`tests/unit/test_backup_cli_extended.py::test_restore_command_handles_false_result`
(now asserts `"Restore error:" not in result.output` to lock the no-double-print
behavior).

## Trigger

Coverage fanout 2026-09-05 (Brief 5) — subagent discovered that
`_do_backup_restore` in `mahavishnu/backup_cli.py:67-76` has:

```python
try:
    success = await backup_manager.restore_backup(backup_id)
    if success:
        typer.echo(f"✓ Restored backup: {backup_id}")
    else:
        typer.echo(f"✗ Restore failed: {backup_id}", err=True)
        raise typer.Exit(code=1)
except Exception as e:  # noqa: BLE001
    typer.echo(f"✗ Restore error: {e}", err=True)
    raise typer.Exit(code=1) from None
```

When `restore_backup` returns `False`, the `raise typer.Exit(code=1)` at line
73 is caught by the broad `except Exception` at line 74, which then prints
"Restore error:" with `e=None` (or the Exit object's empty str) AND raises
again. The user sees **both** error messages on a benign failure.

Same pattern in `_do_backup_create` at lines 11-30.

## Action

1. File `Open` followup note (this file).
2. Restructure both `_do_backup_restore` and `_do_backup_create` so the
   `typer.Exit(code=1)` is raised OUTSIDE the try block:
   ```python
   success = await backup_manager.restore_backup(backup_id)
   if success:
       typer.echo(f"✓ Restored backup: {backup_id}")
       return
   typer.echo(f"✗ Restore failed: {backup_id}", err=True)
   raise typer.Exit(code=1)
   ```
3. Remove the now-redundant `# noqa: BLE001` comments.
4. Tighten `tests/unit/test_backup_cli_extended.py:263-277` — assert only
   "Restore failed" appears on the False path, not "Restore error:".
5. Mark Resolved citing fix location + regression test name.
