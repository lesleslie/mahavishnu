---
status: active
role: implementation
date: 2026-09-05
last_reviewed: 2026-09-05
topic: terminal-validate-command-safety
---

# `validate_command_safety` substring matches produce real false positives

## Status

🔴 **Open — behavioral decision required** — the current implementation is
deliberately strict (per the locked-in test suite at
`tests/unit/mcp/tools/test_terminal_tools.py:273-300`), but the strictness
blocks legitimate production-management commands. Choosing between strict
and permissive is a policy decision the maintainer should make explicitly,
not something to slip into a code change.

## Symptom

`mahavishnu/mcp/tools/terminal_tools.py:77-93` uses naive substring matching:

```python
command_lower = command.lower()
for pattern in DANGEROUS_COMMAND_PATTERNS:
    if pattern.lower() in command_lower:
        raise ValueError(...)
```

`DANGEROUS_COMMAND_PATTERNS` (lines 39-60) contains both genuinely dangerous
patterns and utility names that block normal command use:

| Pattern | False-positive trigger |
|---|---|
| `ncat` | matches `concat`, `concatenate`, file paths with `concat` in them |
| `pkill` | any production-management script that uses `pkill` (e.g., restarting workers) |
| `killall` | same — extremely common in service management |
| `kill -9` | killing a stuck process is normal ops |
| `&& rm` | benign `make clean && rm -f *.o` blocked |
| `; rm` | benign `python build.py; rm /tmp/scratch.txt` blocked |
| `| rm` | benign `echo done | rm /tmp/log.txt` blocked |
| `mkfs` | `mkfs.ext4` on a non-system drive is legitimate |
| `dd if=` | `diff` output containing `if=` lines; `dd` itself is a legitimate disk-cloning tool |
| `> /dev/sd` | redirecting to a normal file path containing `dev/sd` in the name |

## Reproduction

```python
from mahavishnu.mcp.tools.terminal_tools import validate_command_safety

# All of these are legitimate, common commands that currently raise ValueError:
validate_command_safety("pkill -f worker.py")        # kill stuck workers
validate_command_safety("kill -9 $STUCK_PID")         # recover from a hang
validate_command_safety("make clean && rm -f *.o")    # build cleanup
validate_command_safety("echo done; rm /tmp/scratch") # scratch file cleanup
validate_command_safety("dd if=boot.img of=/dev/sdb") # image an SD card
```

## Why it was filed rather than fixed

The locked-in test suite at
`tests/unit/mcp/tools/test_terminal_tools.py:273-300`
(`TestValidateCommandSafety::test_dangerous_patterns_rejected`) explicitly
parametrizes *all* of these as "must reject":

```python
("echo hi && rm -rf /tmp", "&& rm"),
("echo hi; rm -rf /tmp", "; rm"),
("ncat host 1234", "ncat"),
("pkill python", "pkill"),
("killall python", "killall"),
("kill -9 1234", "kill -9"),
("dd if=/dev/zero of=/dev/sda", "dd if="),
```

A correct fix would:

1. Split patterns into two categories — *strict* (always reject) and
   *permissive* (reject only when used in a dangerous context).
2. For permissive patterns, switch from substring to word-boundary or
   shell-token-aware matching.
3. Update the test parametrization to drop the cases that should be
   allowed (e.g., `pkill python` is not dangerous; only `pkill -9 init`
   would be).
4. Update the `test_safe_commands_pass_through` parametrize to include
   the new "previously rejected, now allowed" cases.

This is a behavioral change that the maintainer must sign off on — a
future session picking up this note should ask before changing the
patterns list, not slip the change in.

## Suggested fix (for the maintainer's review)

Reorganize patterns into three classes:

1. **Hard-block (always reject, no false-positive risk)**: `rm -rf /`,
   `mkfs` (only when followed by a block device, e.g. `/dev/`), `> /dev/sda*`.
2. **Shell-chain destructive (reject only when followed by a destructive
   verb)**: `&& rm`, `; rm`, `| rm` — keep, but require word-boundary
   on the next token.
3. **Utility-name overlap (decide policy)**: `pkill`, `killall`, `kill -9`,
   `ncat`, `mkfs`, `dd if=` — these block legitimate ops. Either drop
   them entirely or restrict to specific dangerous arg shapes
   (e.g., `ncat -e /bin/sh`, `pkill -9 init`).

A `pkill` of `worker.py` is not the same as a `pkill -9 1`. The current
code can't tell them apart.

## Related

- `mahavishnu/mcp/tools/terminal_tools.py:39-60` — pattern list
- `mahavishnu/mcp/tools/terminal_tools.py:77-93` — substring matcher
- `tests/unit/mcp/tools/test_terminal_tools.py:255-310` — locked-in tests
