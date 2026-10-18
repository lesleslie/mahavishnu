---
status: complete
role: implementation
date: 2026-09-05
last_reviewed: 2026-10-18
superseded_by: null
blocks_on: []
topic: terminal
resolved_at: 2026-10-18
resolved_by:
  - "Section 1 (close_all empty id roundtrip): commit at 2026-09-05"
  - "Section 2 (terminal_send regex mismatch): commit at 2026-09-05"
  - "Section 3 (validate_command_safety Shape B): commit 13e7bf95"
---

# Terminal Fixes Batch (consolidated)

This followup consolidates three former followups that each tracked a
terminal subsystem defect. All three sections are now resolved
(2026-10-18). Status: complete.

Each section preserves the original content verbatim.

---

## 1. `close_all` empty id roundtrip (formerly `2026-09-05-terminal-close-all-empty-id-roundtrip.md`)

# `terminal_close_all` round-trips empty-string IDs to `manager.close_all`

## Status

**Resolved (2026-09-05)** — production fix at `mahavishnu/mcp/tools/terminal_tools.py:168-180`
(filter added: `session_ids = [sid for sid in ... if sid]` skips empty/missing IDs
instead of coercing them to `""` and round-tripping to the manager); regression tests
at `tests/unit/mcp/tools/test_terminal_tools.py::TestTerminalCloseAll` —
`test_close_all_handles_missing_ids` (updated to assert `closed_count == 1` and
`close_all.assert_awaited_once_with(["sess-1"])`) and the new
`test_close_all_skips_all_empty_ids` (asserts `closed_count == 0` and
`close_all.assert_not_awaited()`).

## Trigger

Coverage fanout 2026-09-05 (Brief 2: `terminal_tools.py`) — subagent flagged that
`terminal_close_all` line 172 (`[s.get("id", s.get("terminal_id", "")) for s in sessions]`)
coerced missing IDs to `""` and passed the empty string to `manager.close_all`,
forcing the manager to handle an invalid session ID on every call.

## Action

1. File `Open` followup note (this file).
2. Filter empty IDs out of the list before passing to `manager.close_all`.
3. Update `test_close_all_handles_missing_ids` to lock the new (correct) behavior.
4. Add `test_close_all_skips_all_empty_ids` for the all-missing-IDs edge case.
5. Mark Resolved citing fix location + regression test names.

---

## 2. `terminal_send` regex mismatch (formerly `2026-09-05-terminal-send-regex-mismatch.md`)

# `SessionID` regex rejects legitimate adapter IDs (e.g. macOS Terminal dots)

## Status

**Resolved (2026-09-05)** — production fix at `mahavishnu/mcp/tools/terminal_tools.py:20-26`
(`SessionID` regex widened from `r"^[a-zA-Z0-9_-]+$"` to `r"^[a-zA-Z0-9._-]+$"` to accept
`.` in IDs); regression test at
`tests/unit/mcp/tools/test_terminal_tools.py::TestTerminalSend::test_session_id_with_dots_accepted`
(parametrized over `"session.with.dot"`, `"sess.1.2.3"`, `"a.b.c.d.e"` — all now pass
through to `manager.send_command`).

## Trigger

Coverage fanout 2026-09-05 (Brief 2: `terminal_tools.py`) — subagent flagged the
`SessionID = Annotated[str, StringConstraints(pattern=r"^[a-zA-Z0-9_-]+$")]`
constraint as potentially over-restrictive. macOS Terminal sessions backed by
`com.apple.Terminal` emit IDs containing dots; the previous regex rejected
those IDs at the MCP boundary even though the underlying adapter accepted them.

(Note: the subagent's original framing described a "regex vs Annotated
mismatch" — but `terminal_send` has only one validator, the Annotated constraint.
There was no internal duplicate regex check. The actual fix is to widen the
single Annotated constraint, not reconcile two validators.)

## Action

1. File `Open` followup note (this file).
2. Widen the regex pattern to include `.`.
3. Update `test_invalid_session_id_rejected` parametrize list to remove the
   `session.with.dot` case (now valid).
4. Add positive `test_session_id_with_dots_accepted` parametrized test.
5. Mark Resolved citing fix location + regression test name.

---

## 3. `validate_command_safety` substring false positives (formerly `2026-09-05-terminal-validate-command-safety.md`)

# `validate_command_safety` substring matches produce real false positives

## Status

✅ **Resolved 2026-10-17 (commit `13e7bf95`)** — operator signoff on
**Shape B (shell-chain with word-boundary)** landed. The 7 utility-name
overlap patterns that caused false positives (`mkfs`, `dd if=`, `> /dev/sd`,
`ncat`, `kill -9`, `pkill`, `killall`) were dropped from
`DANGEROUS_COMMAND_PATTERNS`. The shell-chain destructive patterns
(`&& rm`, `; rm`, `| rm`) were tightened via a new word-boundary regex
(`_SHELL_CHAIN_DESTRUCTIVE_RE = re.compile(r"(?:&&|;|\|)[ \t]+rm(?=$|[;|&]|[ \t]+[;|&])")`).
The 10 hard-block patterns (rm -rf /, chmod 000, chown root:, curl | sh,
wget | sh, nc -e, /dev/tcp, /dev/udp, bind shell, reverse shell) remain
as substring-match rejects.

Test parametrize updates: `test_safe_commands_pass_through` grew by 7
cases (the formerly-blocked legit commands — `make clean && rm -f *.o`,
`pkill -f worker.py`, `kill -9 $STUCK_PID`, `dd if=boot.img of=/dev/sdb`,
`mkfs.ext4 /dev/sdb1`, etc.); `test_dangerous_patterns_rejected` shrank
by 10 cases and grew by 5 (the shell-chain edge cases: `cmd && rm`,
`cmd1 && rm; cmd2`, `cmd1; rm; ls`, `cmd1 | rm | head`). The
`test_dangerous_command_rejected_before_send` test switched from
`pkill python` to `rm -rf /` (still rejected under Shape B).
All 84 tests in `tests/unit/mcp/tools/test_terminal_tools.py` pass;
`crackerjack run -v -f` 18/18 fast hooks passed.

Re-introducing any of the dropped patterns requires a fresh policy call.

---

🔴 **Open — behavioral decision required** (historical; resolved above) —
the current implementation is
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
