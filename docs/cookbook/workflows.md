# Workflow Cookbook

Practical recipes for combining Mahavishnu substrates (pools, workers,
terminal adapters, workflow engines) into end-to-end workflows. Each
recipe is a runnable demo command with the prerequisites, expected
output, and troubleshooting notes needed to actually execute it in a
fresh dev shell.

> **Companion docs**: `docs/CLI_REFERENCE.md` is the canonical command
> reference. `docs/cookbook/workflows.md` (this file) is the
> worked-example layer on top — it shows how to chain commands, not
> what each flag does in isolation.

## Recipe index

| # | Recipe | Substrates exercised | Flavor |
|---|---|---|---|
| 1 | [PiPool → MahavishnuPool handoff](#recipe-1-pipool--mahavishnupool-handoff) | PiPool + MahavishnuPool (worker + tmux terminal adapter) | Doc reference |
| 2 | [PiPool 2-turn cascade](#recipe-2-pipool-2-turn-cascade) | PiPool only | CI smoke |

> New recipes land at the bottom of the index. To propose one, add it
> alongside its `mahavishnu demo <name>` command in `demo_cli.py` and
> a precondition test in `test_demo_workflow_preconditions.py`.

---

## Recipe 1: PiPool → MahavishnuPool handoff

**Goal**: Use PiPool (model-agnostic, single subprocess, npx-based) to
**generate** something — code, text, a plan — then hand the result
to a Shepherd-backed MahavishnuPool to **execute** or test it. Each
pool plays to its strength: PiPool is a chat-shaped substrate with
multi-turn support; MahavishnuPool is the local execution substrate
with full worker + terminal-adapter wiring.

**Substrates exercised**:

- PiPool (model-agnostic agent; per-task spawner against
  `npx @earendil-works/pi-coding-agent@1.3.0`)
- MahavishnuPool (in-process `WorkerManager` + tmux terminal adapter)
- Shep­herd backend for the MahavishnuPool (post-2026-09-24 default worker substrate)

**Prerequisites**:

1. `npx` on PATH — PiPool spawns one `npx @earendil-works/pi-coding-agent`
   subprocess per task. Node.js 18+ ships `npx`; verify with
   `which npx`.
2. A Shepherd workspace initialized for the local pool. The pool's
   default writable root resolves to
   `~/.local/state/mahavishnu/worktrees/demo-pi-then-local-local/workspace`.
   Initialize it once per dev shell:
   ```bash
   sp init ~/.local/state/mahavishnu/worktrees/demo-pi-then-local-local
   ```
3. tmux binary on PATH (MahavishnuPool's default terminal adapter).

**The command**:

```bash
mahavishnu demo workflow-pi-then-local \
    --pi-prompt "write a hello-world function in Python" \
    --local-prompt "test it and report the result" \
    --timeout 90
```

**What you'll see**:

```
Workflow: pi pool -> local pool handoff
Pi prompt:    write a hello-world function in Python
Local prompt: test it and report the result
  ✓ pi pool started: pi_<id>
  ✓ pi task complete: status=completed
  → starting local pool with pi output as context
  ✓ local task complete: status=completed
  ✓ both pools stopped

Workflow result:
{
  "workflow": "pi-then-local",
  "pi": {
    "pool_type": "pi",
    "pool_id": "pi_<id>",
    "status": "completed",
    "duration": 4.21,
    "output_preview": "def hello_world():\n    print('Hello, World!')"
  },
  "local": {
    "pool_type": "mahavishnu",
    "pool_id": "pool_<id>",
    "status": "completed",
    "duration": 8.93,
    "output_preview": "<test execution result>"
  }
}
```

**Troubleshooting**:

| Symptom | Cause | Fix |
|---|---|---|
| `npx binary not on PATH` | Node.js 18+ not installed | Install Node.js and verify `which npx` |
| `Shepherd workspace not initialized at …/demo-pi-then-local-local/workspace` | `sp init` not run for that path | `sp init <path>` (see Prerequisite 2) |
| `[MHV-312] Shepherd workspace open failed: not a Shepherd workspace. Run \`sp init\` first.` | Same as above — but precondition was bypassed or the pool name changed | Run `sp init` for the workspace path shown in the error |
| PiPool subprocess times out | Bifrost routing config unreachable or model backend down | Verify `settings/mahavishnu.yaml` has a working `bifrost.route_*` block; check `mahavishnu pool health` for the pi pool |
| Local task returns `status=failed` | tmux session couldn't start (e.g. `$TMUX_TMPDIR` not writable) | Verify `tmux -V` works in your shell; check `~/.mahavishnu/tmux` is writable |

**Notes**:

- The PiPool's output is **automatically folded** into the local
  pool's prompt — you don't need to wire the handoff yourself. Look
  for the `received from pi pool: …` prefix in the local pool's
  prompt in `~/.mahavishnu/logs/mcp.log` to see the injection.
- Pass `--keep` to leave both pools running after the demo for
  follow-up `mahavishnu pool execute` calls.
- For the underlying implementation, see
  `_check_workflow_pi_then_local_preconditions` and
  `_run_workflow_pi_then_local_demo` in `mahavishnu/cli/demo_cli.py`.

---

## Recipe 2: PiPool 2-turn cascade

**Goal**: Run a single PiPool through a 2-turn cascade — turn 1
dispatches the operator's prompt, turn 2 dispatches a follow-up that
**inherits turn 1's output as context**. This showcases PiPool's
multi-turn agent capability (its real-world use case; the other
pools are single-dispatch).

**Substrates exercised**:

- PiPool only (single subprocess, `max_workers=1` enforced by the
  pool — two turns reuse the same subprocess)

**Prerequisites**:

- `npx` on PATH (same as Recipe 1, Prerequisite 1).
- **No Shepherd workspace needed** — PiPool doesn't use the Shepherd
  backend, so this recipe is runnable in any dev shell with `npx`
  installed (no `sp init` required).

**The command**:

```bash
mahavishnu demo workflow-pi-cascade \
    --prompt "what is 2+2?" \
    --followup "explain the previous answer in one sentence."
```

**What you'll see**:

```
Workflow: pi cascade (2 turns on the same pool)
Turn 1:  what is 2+2?
Turn 2:  explain the previous answer in one sentence.
  ✓ pi pool started: pi_<id>
  ✓ turn 1 complete: status=completed
  ✓ turn 2 complete: status=completed
  ✓ pi pool stopped

Workflow result:
{
  "workflow": "pi-cascade",
  "pool_id": "pi_<id>",
  "pool_type": "pi",
  "turns": [
    {
      "prompt": "what is 2+2?",
      "status": "completed",
      "duration": 3.12,
      "output_preview": "4"
    },
    {
      "prompt": "received from previous turn: 4\n\nexplain the previous answer in one sentence.",
      "status": "completed",
      "duration": 2.87,
      "output_preview": "The expression 2+2 evaluates to 4 because addition is the operation of combining two quantities."
    }
  ]
}
```

**Troubleshooting**:

| Symptom | Cause | Fix |
|---|---|---|
| `npx binary not on PATH` | Node.js 18+ not installed | Install Node.js |
| `PiPool scale(n>1) raises NotImplementedError` | Trying to scale up (cascade is sequential, not parallel) | Don't pass `--max` or similar; PiPool is fixed at 1 subprocess by design |
| Turn 1 fails but turn 2 runs | Subprocess crashed mid-stream | The pool should auto-recover; if not, `mahavishnu pool list` and inspect the failed `pi_<id>` |

**Notes**:

- The cascade is **sequential**, not parallel — PiPool reuses the
  same long-lived `npx` subprocess for both turns.
- For a true multi-pool handoff (source → target), use
  `workflow-multi-pool-handoff` instead. This recipe isolates
  PiPool's multi-turn behavior.
- For the underlying implementation, see
  `_check_workflow_pi_cascade_preconditions` and
  `_run_workflow_pi_cascade_demo` in `mahavishnu/cli/demo_cli.py`.

---

## How to add a new recipe

1. **Build the demo command** in `mahavishnu/cli/demo_cli.py`:
   - Add `_check_workflow_<name>_preconditions` (probe-injectable,
     returns `list[str]` of failures).
   - Add `async _run_workflow_<name>_demo` (constructs `PoolConfig`
     and the substrate, dispatches, returns structured result dict).
   - Add `@demo_app.command("workflow-<name>")` callback (Typer
     options + precondition gate + `asyncio.run(asyncio.wait_for(...))`).
2. **Wire it up**:
   - Update the `=== DEMO SUB-COMMANDS ===` comment in
     `mahavishnu/_main_cli.py` to reflect the new count.
   - Update the stub-section comment in `demo_cli.py` to mention
     the new demo in the "promoted to live" tally.
3. **Add tests**:
   - 2 wireup invariant tests in
     `tests/unit/cli/test_cli_wireup_invariants.py`
     (one asserting a unique `--flag` in `--help`, one asserting the
     name is NOT in `demo_cli._STUB_COSTS`).
   - 2-3 precondition tests in
     `tests/unit/cli/test_demo_workflow_preconditions.py`
     (cover each branch: pass-with-probes, fail-without-probes,
     edge cases).
4. **Add a recipe** to this file following the structure above
   (Goal, Substrates exercised, Prerequisites, The command, What
   you'll see, Troubleshooting, Notes). Add a row to the index.
5. **Reference it** in `docs/CLI_REFERENCE.md` under the
   `### Workflow demos` block.
6. **Run the merge gate**: `crackerjack run -v -f` from the worktree
   before squash-merging to main. Squash-merge only your staged
   paths (don't sweep in the user's unrelated dirty files).
