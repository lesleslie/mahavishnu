# 2026-10-11 — Prefect adapter fixes + `mahavishnu demo|launchd` CLI framework

## Decision rule

Three recurring patterns from this PR that future work should respect:

1. **Use ``prefect.flow_runs.wait_for_flow_run`` (top-level import) — NOT
   ``client.wait_for_flow_run``.** The client method does NOT exist on
   ``PrefectClient`` in 3.x; the function moved to a module-level helper.
   Returns a ``FlowRun`` whose ``.state`` is the State to probe. Apply this
   on every 3.x touch — pin with a test that asserts the import path
   (memory: ``prefect-3-8-sdk-shape.md``).

2. **Bug C fixes stay scoped to ``_api_key_env`` — never ``__init__`` or
   ``shutdown``.** Reason: ``os.environ`` is process-global; mutation in
   ``__init__`` leaks across pytest-xdist workers. Keep the swap in the
   existing scoped contextmanager.

3. **Revert-resistant CLI wire-up requires three anti-revert markers,
   all must move together:** (a) the new CLI module's docstring
   references the wire-up, (b) ``_main_cli.py`` carries a
   ``=== <NAME> SUB-COMMANDS ===`` comment block, (c) a meta-test
   asserts the new Typer group is in
   ``mahavishnu._main_cli.app.registered_groups``. All three absent
   → silent revert is invisible to CI.

## Status

Shipped 2026-10-11 in 3 commits:

- ``03a7949c`` — fix(prefect): patch three adapter bugs surfaced by live 3.8.8 demo
- ``26ae40e5`` — feat(cli): ``mahavishnu demo <engine|adapter>`` framework — tmux + prefect + 7 stubs
- ``ab912667`` — feat(cli): ``mahavishnu launchd prefect`` opt-in plist management

## Staged rollout rationale

Phase A (bugs) is independently shippable — leaves the engine correct
even if B/C never happen. Phase B (demo CLI) builds on A. Phase C
(launchd) builds on A only — an operator can adopt A and skip C
without losing B's value. The ``xfail``-flips-to-pass trick on
``test_launchd_subcommands_wired_in_main_cli`` lets Phase B commit
without Phase C holding it up.

## Related

- Plan: ``docs/plans/2026-10-11-prefect-adapter-bug-fixes-demo-cli-launchd.md``
- Memory: ``prefect-3-8-sdk-shape.md`` (fix patterns)
- Memory: ``prefect-adapter-bugs-2026-10-11.md`` (original bug surfaces)
- Memory: ``feedback-line-number-pin-tests.md`` (test brittleness fix)
- Anti-pattern: ``feedback-macos-reboot-launchd-keepalive-cascade.md``
  → do NOT auto-install the plist; opt-in only.
