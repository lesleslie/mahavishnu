---
status: active
role: canonical
date: 2026-07-17
last_reviewed: 2026-07-17
superseded_by: null
topic: session-worktree-defaults
---

# Per-session worktree isolation — defaults & safety

## Context

The per-session worktree isolation feature
(`docs/followups/2026-07-16-session-worktree-isolation.md`) is **opt-in**
via `MAHAVISHNU_AUTO_WORKTREE=1`. This decision records why the default
is off, the security rationale, and the threat model the feature is
designed against.

The pickup context was the closed followup
`docs/followups/.archive/2026-07-16-multi-session-mcp-contention.md` —
multiple concurrent Claude Code sessions in the same working directory
causing file stomping, branch conflicts, and dirty-tree merge problems.

## Decision rule

1. **Default-off, opt-in.** The SessionStart hook is wired in
   `.claude/settings.json`. When `MAHAVISHNU_AUTO_WORKTREE` is unset,
   the hook returns 0 in `<2s` after optionally printing a one-line
   stderr discovery hint (see rule 6). Users MUST set the env var
   explicitly to enable; setting it to any value (including `0`)
   silences the hint.

1. **Never auto-removes worktrees.** SessionEnd marks the entry
   `abandoned` in the registry but does NOT delete the git worktree.
   The `mahavishnu worktree prune-abandoned` CLI removes registry
   entries; the user MUST run `mahavishnu worktree remove <repo> <path>` to actually delete the on-disk worktree.

1. **Session_id is validated.** Hook calls `uuid.UUID(session_id)`
   up front and fails closed on malformed input. First-segment 8 hex
   chars are the registry key (uniform distribution, no UUIDv4 time-low
   collision risk).

1. **State file is hardened.** `chmod 0o600` on the file, `chmod 0o700`
   on the parent dir. Open with `O_NOFOLLOW` to refuse pre-planted
   symlinks (CWE-59). Schema-version-gated: refuses to overwrite
   files declaring a future `schema_version`.

1. **POSIX-only.** Uses `fcntl.flock` which is local-FS only (NFS
   semantics differ). mahavishnu is Unix-targeted by posture; this is
   not portable to Windows.

1. **Discovery hint is the only default-off side effect** (Phase 4,
   2026-07-17). When `MAHAVISHNU_AUTO_WORKTREE` is unset AND
   `mode == "session-start"` AND `cwd` is non-empty AND `cwd` is a
   git repo (not already a worktree) AND `MAHAVISHNU_AUTO_WORKTREE_ROOT`
   does not yet exist, the hook prints one line to stderr:

   ```
   mahavishnu: MAHAVISHNU_AUTO_WORKTREE=1 enables per-session worktrees; see docs/CONFIGURATION.md
   ```

   No filesystem mutation, no registry write, no mahavishnu import.
   Silenced by setting `MAHAVISHNU_AUTO_WORKTREE` to any value
   (truthy to enable, falsy to disable without seeing the hint).

## Threat model

| Threat | Mitigation |
|--------|-----------|
| Local attacker replaces the registry file with a symlink | `O_NOFOLLOW` on open (CWE-59) |
| Local attacker reads the registry (chmod 644) | `chmod 0o600` + parent `chmod 0o700` at first write |
| Concurrent Claude sessions clobber each other's writes | `fcntl.flock(LOCK_EX)` over read-modify-write |
| `git worktree add` runs in the wrong directory | Path validation: `target_path.relative_to(root_env)` |
| Future-format registry file silently overwritten | Schema-version check: refuse to write if on-disk version > supported |
| Untrusted branch name with shell metacharacters | `git worktree add` uses argv-list (no shell=True); branch name is `worktree-agent-<hex8>` derived from validated UUID |
| Worktree fills disk over time | Manual cleanup via `mahavishnu worktree prune-abandoned` — never automatic |
| Session_id injection | `uuid.UUID()` strict validation; registry key is hex-only |
| Default-off sessions pollute stderr with hint spam | Hint only fires when conditions met (SessionStart + git repo + non-worktree + missing root); silenced by any value of `MAHAVISHNU_AUTO_WORKTREE` |
| Discovery hint bypasses the user's no-stderr-noise preference | Single line of stderr; gated by `MAHAVISHNU_AUTO_WORKTREE` being unset (any value silences) |

## Out of scope

- **Cross-host registry coordination**: assumes local FS. If mahavishnu
  ever runs across multiple machines sharing the same registry, the
  state file would diverge.
- **Windows support**: flock is POSIX-only.
- **Per-user ACLs**: assumes single-user dev box. If mahavishnu ever
  runs as a multi-user service, the registry path needs additional
  hardening (user-prefixed subdirs).
- **Suppressing the hint while keeping the feature opt-out clean**:
  today, `MAHAVISHNU_AUTO_WORKTREE=0` silences the hint AND turns the
  feature off. If users complain about that conflation, split into
  `MAHAVISHNU_AUTO_WORKTREE_HINT=0` (deferred until signal).

## Why opt-in (not default-on)

Three reasons, in order of weight:

1. **User agency.** A Claude session that auto-creates a worktree on
   its own changes the user's filesystem without explicit consent. The
   user may be running Claude in an environment where worktrees are
   unexpected (CI, container, ephemeral sandbox).
1. **Optics.** The first time a user sees `~/worktrees/agent-a0c5d2a0`
   appear unbidden, they may not realize what created it. Default-off
   means the user MUST see the env-var doc and decide.
1. **Escape hatch.** Default-on with a kill-switch (`unset MAHAVISHNU_AUTO_WORKTREE`) is more error-prone than default-off with
   an opt-in. The latter forces a deliberate choice.

### Phase 4 addition (2026-07-17): discovery hint

The discoverability gap noted after the Phase 1-3 rollout was real:
multi-session power users — the target audience — were never opting
in because they didn't know the feature existed. To address this
without flipping the default, Phase 4 added a one-line stderr hint
that fires when conditions suggest the feature would be useful
(SessionStart, git repo, non-worktree, missing root dir). The hint
preserves the consent contract (no filesystem mutation) while
improving findability.

If the opt-in rate is still low after a quarter of hint exposure,
revisit flipping the default. Until then, this middle ground is the
recommended posture.

## Cross-references

- Pickup followup: `docs/followups/2026-07-16-session-worktree-isolation.md`
- 4-lens plan: `/Users/les/.claude/plans/cheerful-marinating-fountain.md`
- Phase 1 commit: `5a7e001c` (registry + CLI)
- Phase 2 commit: `ccec4357` (hook + settings wiring)
- Phase 4 commit: `5bc29b3e` (discovery hint + docs)
- Phase 5a commit: `e8ea440` (lost-update race + write-path TOCTOU)
- Phase 5b commit: `054df70` (hook dispatch + payload + option-injection)
- Phase 5c commit: `1a0d39a` (real-git worktree detection)
- Phase 5d commit: `3ee593d` (CLI tests)
- Phase 5e commit: `ffe4397` (registry edge cases + corrupt-shape fix)
- Phase 6 commit: `2a6082f` (json_state_store SoT consolidation)
- Plan-template lifecycle: `.claude/decisions/wire-up-contract.md`
