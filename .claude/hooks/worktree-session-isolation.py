#!/usr/bin/env python3
"""SessionStart / SessionEnd hook for per-session worktree isolation.

When ``MAHAVISHNU_AUTO_WORKTREE=1`` is set in the environment, this
hook:

- **SessionStart**: auto-provisions a per-session git worktree at
  ``~/worktrees/agent-<hex8>``, branches from the main repo, and
  records the session_id → worktree_path mapping in the registry.
- **SessionEnd**: marks the worktree as ``abandoned`` in the registry
  (default policy; never auto-removes the git worktree).

When the env var is **unset** (the default), the hook returns 0 in
``<2s`` with the following possible side effect:

- **Discovery hint** (SessionStart only): when ``cwd`` is a git repo,
  is not already a worktree, and the configured worktree root
  (``MAHAVISHNU_AUTO_WORKTREE_ROOT``, default ``~/worktrees``) does
  not yet exist, prints a one-line stderr message pointing the user
  at the opt-in env var. No filesystem mutation, no mahavishnu
  import. Silenced by setting ``MAHAVISHNU_AUTO_WORKTREE`` to any
  value (truthy to enable, falsy to disable without seeing the hint).

This preserves the "default off, opt in" contract per the 4-lens
plan review, while addressing the discoverability gap noted after
the rollout.

Module load is stdlib-only. The ``mahavishnu.core.worktree_coordination``
import is gated behind the env-var check, so default-off sessions
incur no mahavishnu import cost.

Failure isolation: every code path returns 0. Errors are logged to
stderr (visible in Claude Code's hook output panel). Never raises.

Reference: plan ``/Users/les/.claude/plans/cheerful-marinating-fountain.md``
            and followup ``docs/followups/2026-07-16-session-worktree-isolation.md``.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess  # nosec B404 — argv-list only, no shell
import sys

# Shared helper lives in the same .claude/hooks directory.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _hook_io import read_session_payload  # noqa: E402

# Environment variable that gates the whole feature.
OPT_IN_ENV = "MAHAVISHNU_AUTO_WORKTREE"

# Optional overrides (all default to sane values via mahavishnu.core.paths).
ROOT_ENV = "MAHAVISHNU_AUTO_WORKTREE_ROOT"
BRANCH_BASE_ENV = "MAHAVISHNU_AUTO_WORKTREE_BRANCH_BASE"
CLEANUP_ENV = "MAHAVISHNU_AUTO_WORKTREE_CLEANUP"
DEBUG_ENV = "MAHAVISHNU_AUTO_WORKTREE_DEBUG"
TIMEOUT_ENV = "MAHAVISHNU_AUTO_WORKTREE_TIMEOUT"


def _log(msg: str) -> None:
    """Write a single line to stderr; Claude Code surfaces as Hook output."""
    sys.stderr.write(f"mahavishnu: {msg}\n")
    sys.stderr.flush()


def _is_truthy(value: str | None) -> bool:
    """True for ``1`` / ``true`` / ``yes`` / ``on`` (case-insensitive)."""
    if not value:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _cwd_is_inside_worktree(cwd: str) -> bool:
    """True when ``cwd`` is the working tree of a git worktree.

    Uses ``git rev-parse --git-dir`` which returns the worktree-specific
    git directory:

    - Main repo: ``.git`` (relative to the repo root)
    - Worktree: ``.git/worktrees/<wt-name>`` (relative to the worktree root)

    The prior implementation used ``--git-common-dir`` which returns
    the SHARED git dir (the main repo's ``.git``) regardless of whether
    we're in a worktree — so the helper was always returning False.
    Per multi-agent review Test #4 (2026-07-20): real worktrees were
    not detected.

    Returns False on any git failure — never blocks the hook.
    """
    if not cwd:
        return False
    try:
        result = subprocess.run(  # nosec B603 — cwd is a session-provided path; argv-list only
            ["git", "-C", cwd, "rev-parse", "--git-dir"],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        return False
    git_dir = result.stdout.strip()
    # For a main repo, ``--git-dir`` returns ``.git`` (no ``/worktrees/``);
    # for a worktree, it returns ``.git/worktrees/<name>``.
    return "/worktrees/" in git_dir


def _detect_repo_nickname(cwd: str) -> str | None:
    """Best-effort repo nickname from cwd.

    Walks up from ``cwd`` looking for ``.git``. Returns the basename of
    the directory containing ``.git``. Returns None on failure.
    """
    if not cwd:
        return None
    p = Path(cwd).resolve()
    for candidate in (p, *p.parents):
        if (candidate / ".git").exists() or (candidate / ".git").is_symlink():
            return candidate.name
    return None


def _ensure_mahavishnu_importable() -> None:
    """Inject the repo root into ``sys.path`` so ``mahavishnu.*`` resolves.

    The hook lives in ``.claude/hooks/`` (not inside the ``mahavishnu/``
    package). Adding the parent of ``.claude/`` to ``sys.path`` lets the
    hook ``import mahavishnu.core.worktree_coordination`` without
    requiring a packaged install.
    """
    if any("mahavishnu" in p for p in sys.path):
        return  # already importable
    # .claude/hooks/worktree-session-isolation.py → .claude/hooks/ → .claude/ → <repo>
    repo_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(repo_root))


def _git_worktree_add_argv(
    cwd: str,
    branch: str,
    target_path: str,
    branch_base: str,
) -> list[str]:
    """Build argv for ``git worktree add -B <branch> <path> <commit-ish>``.

    Includes ``--`` before the positional ``<path> <commit-ish>`` args
    to defend against ``branch_base`` (from the
    ``MAHAVISHNU_AUTO_WORKTREE_BRANCH_BASE`` env var) starting with
    ``-`` and being re-parsed by git as an option flag. Per the
    security audit (2026-07-20, finding #2): argv-list closes shell
    injection but not git's own option parser; ``--`` closes both.

    Returned argv is a plain list (never ``shell=True``) so the
    caller can pass it directly to ``subprocess.run``.
    """
    return [
        "git",
        "-C", cwd,
        "worktree",
        "add",
        "-B", branch,
        "--",
        target_path,
        branch_base,
    ]


def _git_current_branch(cwd: str) -> str | None:
    """Return the current branch name in ``cwd``, or None on failure.

    Used by ``_run_session_start`` to default ``MAHAVISHNU_AUTO_WORKTREE_BRANCH_BASE``
    to the current branch instead of hardcoded ``main`` (which fails
    on repos that default to ``master`` or any other name).
    """
    try:
        result = subprocess.run(  # nosec B603 — argv-list, no shell
            ["git", "-C", cwd, "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        return None
    branch = result.stdout.strip()
    if not branch or branch == "HEAD":
        return None  # detached HEAD
    return branch


def _log_debug(msg: str) -> None:
    """Conditional stderr write, gated by ``MAHAVISHNU_AUTO_WORKTREE_DEBUG``.

    No-op when the env var is unset. When set to truthy, prints
    one line per call (prefixed with ``[debug]``) so operators can
    introspect hook behavior without enabling the feature.
    """
    if _is_truthy(os.environ.get(DEBUG_ENV)):
        sys.stderr.write(f"[debug] {msg}\n")
        sys.stderr.flush()


def _run_session_start(session_id_full: str, cwd: str) -> int:
    """SessionStart: ensure the session has a worktree.

    Steps mirror the plan §Hook flow:
      1. Compute short session id (fail closed on malformed UUID).
      2. cwd-is-worktree → register existing, return 0.
      3. Registry hit + path still exists → refresh, log "reused", return 0.
      4. Stale entry → remove.
      5. Detect repo_nickname.
      6. git worktree add (via _git_worktree_add_argv).
      7. Path security check (must be under MAHAVISHNU_AUTO_WORKTREE_ROOT).
      8. Register in registry.
      9. Surface to user via stderr.
    """
    # Lazy import — only after env-var gate passes.
    _ensure_mahavishnu_importable()
    from mahavishnu.core.worktree_session_registry import (  # noqa: E402
        SessionWorktreeRegistry,
        short_session_id,
    )

    short = short_session_id(session_id_full)
    if not short:
        return 0  # bad UUID → silent skip

    registry = SessionWorktreeRegistry()

    # 2: cwd-is-worktree → register existing.
    if _cwd_is_inside_worktree(cwd):
        existing = registry.get(short)
        if existing is None:
            # Infer the worktree info from cwd + git.
            repo_path = str(Path(cwd).resolve())
            while repo_path != "/" and not (
                Path(repo_path) / ".git"
            ).exists():
                repo_path = str(Path(repo_path).parent)
            branch = f"worktree-agent-{short}"
            wt_path = str(Path(cwd).resolve())
            registry.register(
                session_id_short=short,
                worktree_path=wt_path,
                branch=branch,
                repo_path=repo_path,
                repo_nickname=_detect_repo_nickname(repo_path) or "",
                metadata={"source": "cwd-detected"},
            )
            _log(f"worktree registered (cwd-detected): {wt_path}")
        return 0

    # 3: registry hit + path still exists → refresh, log reused.
    existing = registry.get(short)
    if existing and Path(existing["worktree_path"]).exists():
        registry.register(  # refresh last_seen_at
            session_id_short=short,
            worktree_path=existing["worktree_path"],
            branch=existing["branch"],
            repo_path=existing["repo_path"],
            repo_nickname=existing["repo_nickname"],
            metadata=existing.get("metadata", {}),
        )
        _log(f"worktree reused: {existing['worktree_path']}")
        return 0

    # 4: stale entry → remove.
    if existing:
        registry.remove(short)
        _log(f"stale registry entry removed for session {short}")

    # 5: detect repo_nickname.
    repo_nickname = _detect_repo_nickname(cwd)
    if not repo_nickname:
        _log(f"could not detect repo_nickname from cwd={cwd!r}; skipping")
        return 0

    worktree_name = f"agent-{short}"
    branch = f"worktree-{worktree_name}"

    # 6: build argv + create worktree.
    # Direct ``git worktree add`` via subprocess. We deliberately bypass
    # ``MahavishnuApp.load()`` + ``WorktreeCoordinator`` to keep the
    # SessionStart cost <2s. The WorktreeCoordinator's safety features
    # (audit, path validation) are less critical here because:
    #   - cwd is known (user's session working directory)
    #   - branch name is derived from session_id (predictable)
    #   - no dependency chain involved
    # Path validation is re-applied below (relative_to root) for safety.
    root_env = os.environ.get(ROOT_ENV, "~/worktrees")
    root = Path(root_env).expanduser().resolve()
    target_path = (root / worktree_name).resolve()
    branch_base = os.environ.get(BRANCH_BASE_ENV)
    if not branch_base:
        # Default to the current branch in cwd so ``master``/other
        # default-branch repos aren't surprised by a hardcoded ``main``.
        # Falls back to ``main`` only when discovery fails.
        branch_base = _git_current_branch(cwd) or "main"

    # E5: configurable timeout (default 10s, capped at 60s).
    try:
        timeout = int(os.environ.get(TIMEOUT_ENV, "10"))
    except ValueError:
        timeout = 10
    timeout = max(1, min(timeout, 60))

    _log_debug(
        f"git worktree add: cwd={cwd!r} branch={branch!r} "
        f"target={target_path!r} branch_base={branch_base!r} timeout={timeout}"
    )

    # E2: GIT_TERMINAL_PROMPT=0 prevents the subprocess from blocking on
    # a credential prompt (e.g. when branch_base is a remote ref).
    subprocess_env = os.environ.copy()
    subprocess_env["GIT_TERMINAL_PROMPT"] = "0"

    try:
        # ``--`` ends option parsing before the positional
        # ``<path> <commit-ish>`` (defense against branch_base
        # starting with ``-``).
        result = subprocess.run(  # nosec B603 — argv-list, no shell
            _git_worktree_add_argv(cwd, branch, str(target_path), branch_base),
            capture_output=True,
            text=True,
            timeout=timeout,
            env=subprocess_env,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        _log(f"git worktree add failed: {exc}")
        return 0

    if result.returncode != 0:
        _log(f"git worktree add failed: {result.stderr.strip()}")
        return 0

    # 7: path security check — must be under the configured root.
    try:
        target_path.relative_to(root)
    except ValueError:
        _log(
            f"worktree_path {target_path} is not under root {root}; "
            f"SECURITY REJECTION"
        )
        # Best-effort cleanup: prune the worktree we just created.
        subprocess.run(  # nosec B603 — argv-list
            ["git", "-C", cwd, "worktree", "prune"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return 0

    # 8: register.
    registry.register(
        session_id_short=short,
        worktree_path=str(target_path),
        branch=branch,
        repo_path=cwd,
        repo_nickname=repo_nickname,
        metadata={
            "source": "auto",
            "claude_session_id_full": session_id_full,
        },
    )
    _log(f"worktree ready: {target_path}")
    return 0


def _run_session_end(session_id_full: str) -> int:
    """SessionEnd: mark the worktree abandoned (default policy)."""
    _ensure_mahavishnu_importable()
    from mahavishnu.core.worktree_session_registry import (  # noqa: E402
        SessionWorktreeRegistry,
        short_session_id,
    )

    short = short_session_id(session_id_full)
    if not short:
        return 0

    policy = os.environ.get(CLEANUP_ENV, "mark")
    if policy != "mark":
        return 0  # "keep" or anything else → no-op

    registry = SessionWorktreeRegistry()
    existing = registry.get(short)
    if existing is None:
        return 0
    if existing.get("state") == "abandoned":
        return 0  # idempotent — already marked

    registry.mark_abandoned(short)
    _log(
        f"worktree at {existing['worktree_path']} marked abandoned; "
        f"run `mahavishnu worktree prune-abandoned [--older-than-days N]` to "
        f"clean up the registry entry."
    )
    return 0


def _maybe_print_discovery_hint(cwd: str, mode: str) -> None:
    """One-line stderr hint when ``MAHAVISHNU_AUTO_WORKTREE`` is unset.

    Fires ONLY on SessionStart when ALL conditions are met:

    - ``MAHAVISHNU_AUTO_WORKTREE`` is unset (user has not touched the
      env var — they may not know the feature exists)
    - cwd is a git repo (not already a worktree)
    - ``MAHAVISHNU_AUTO_WORKTREE_ROOT`` doesn't exist yet (default
      ``~/worktrees``)

    The hint is purely informational: stderr write only, no filesystem
    mutation, no mahavishnu import. Silenced by setting
    ``MAHAVISHNU_AUTO_WORKTREE`` to any value (truthy to enable, falsy
    to disable without seeing the hint).

    Reference: ``.claude/decisions/session-worktree-defaults.md``.
    """
    if mode != "session-start":
        return
    if OPT_IN_ENV in os.environ:
        return  # user has touched the env var — they're informed
    if not cwd:
        return
    if _cwd_is_inside_worktree(cwd):
        return  # already in a worktree — they know
    if _detect_repo_nickname(cwd) is None:
        return  # not a git repo — feature not applicable
    root_env = os.environ.get(ROOT_ENV, "~/worktrees")
    root = Path(root_env).expanduser()
    if root.exists():
        return  # already configured — they've set something up
    _log(
        "MAHAVISHNU_AUTO_WORKTREE=1 enables per-session worktrees; "
        "see docs/CONFIGURATION.md"
    )


def main() -> int:
    """Dispatch on mode (positional argv[1] OR ``--mode`` flag).

    Accepts both forms because Claude Code's wire format passes
    positional ``session-start`` / ``session-end`` (per ``.claude/settings.json``),
    but downstream tooling may invoke with ``--mode``. Both are
    treated as authoritative.

    If neither form is provided, log a diagnostic and return 0 —
    fail-closed rather than inferring from the stdin payload shape
    (the prior cwd-based heuristic broke when SessionEnd payloads
    also carried a ``cwd`` field, per the multi-agent review).
    """
    args = sys.argv[1:]
    mode: str | None = None
    # Positional first (Claude Code's wire format).
    if args and not args[0].startswith("-"):
        mode = args[0]
    # --mode flag (back-compat + downstream tooling).
    elif "--mode" in args:
        i = args.index("--mode")
        if i + 1 < len(args):
            mode = args[i + 1]

    payload = read_session_payload()
    session_id_full = payload.session_id
    cwd = payload.cwd

    if mode is None:
        _log("no mode provided (neither positional argv[1] nor --mode); skipping")
        return 0

    if mode not in ("session-start", "session-end"):
        _log(f"unknown mode: {mode!r}")
        return 0

    # Default-off fast path: no env var → no mahavishnu import → return 0.
    # BUT: discovery hint may fire here if conditions are met.
    if not _is_truthy(os.environ.get(OPT_IN_ENV)):
        _maybe_print_discovery_hint(cwd, mode)
        return 0

    if mode == "session-start":
        return _run_session_start(session_id_full, cwd)
    return _run_session_end(session_id_full)


if __name__ == "__main__":
    sys.exit(main())
