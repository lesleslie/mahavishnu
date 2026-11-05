---
status: active
role: canonical
kind: decision
date: 2026-11-05
last_reviewed: 2026-11-05
superseded_by: null
topic: terminal-codex-worker
---

# The terminal-codex worker stays, and codex joins the Bifrost gateway

## Context

The question was: *since Claude Code and Qwen are the most supported
harnesses right now, does it make sense to have a terminal-codex worker
at all — and should it route through the Bifrost gateway like the other
two?*

**The premise needs one correction: the worker already exists.** This
is not "should we add one"; it is "should we use the one we have, and
should its traffic be governed".

### What is true today (verified 2026-11-05)

**The worker is registered.** `mahavishnu/workers/registry.py:240-258`:

```python
"terminal-codex": WorkerConfig(
    command=("sh -lc 'codex exec --json --sandbox {permission_mode} "
             '"$MAHAVISHNU_PROMPT" 2>>"${MAHAVISHNU_STDERR_PATH:-/dev/null}"; ...'),
    completion_markers=["__MAHAVISHNU_DONE__"],
    stream_format="text",
    requires_tool="codex",
    auth_kind=AuthKind.CLI_SUBSCRIPTION,
    one_shot=True,
    permission_mode="workspace-write",
)
```

`codex-cli 0.164.0` is installed on this host, so `requires_tool="codex"`
is satisfiable. The worker is exercised by the registry and
shell-command-safety tests.

**Claude and Qwen route through Bifrost; codex does not.** Three
verified facts:

- The live environment carries `ONEIRIC_BIFROST_ROUTES=claude_route,qwen_route`.
- `RouteKind` — in **oneiric**, `oneiric/adapters/llm/bifrost.py:179-188` —
  has **exactly two** members, `CLAUDE_ROUTE` and `QWEN_ROUTE`. There is
  no `CODEX_ROUTE` to switch on; adding one is a oneiric change.
- `mahavishnu/terminal/manager.py:66-93` branches only for
  `terminal-claude` (injects `ANTHROPIC_BASE_URL` pointing at the
  gateway's Anthropic-compatible endpoint) and `terminal-qwen` (injects
  `OPENAI_BASE_URL`). `terminal-codex` **falls through and receives no
  env override at all**, so it calls its own provider —
  `~/.codex/config.toml` carries `model = "gpt-5.6-terra"`.

**The gateway can carry codex.** The obstacle is not the protocol.
Bifrost serves the OpenAI **Responses** API that codex speaks:

```
POST http://127.0.0.1:8471/v1/responses
  {"is_bifrost_error": false, "error": {"message": "input is required for responses"},
   "routing_info": {}, "original_model_requested": "gpt-4o-mini", "request_type": "responses"}
```

The route exists, it validates Responses-shaped `input`, and it reports
`"request_type": "responses"`. (`/v1/chat/completions` and
`/anthropic/v1/messages` are served too; `/v1/models` answers 405 to a
POST, as expected for a GET-only route.)

**But the worker is registered and still broken.** The now-superseded
plan `docs/plans/2026-11-01-terminal-cli-harness-demos-and-dispatch-trust.md`
§4.2 smoke-tested the codex invocation and found two defects, **both of
which are still absent from `registry.py:243-246`**:

1. `codex exec` **reads additional input from stdin**. In a tmux pane
   stdin is the terminal, so the CLI *blocks* waiting for input that
   never arrives. The command must close stdin.
1. Outside a trusted directory it refuses with *"Not inside a trusted
   directory and --skip-git-repo-check was not specified"* and exits
   non-zero. It needs `--skip-git-repo-check`.

Neither fix is codex-specific in spirit — but the git-trust gate and the
stdin read are **codex's** behaviour; claude and qwen need neither.

With both fixed, codex ran and exited **rc=1** with
`{"type":"error","message":"You've hit your usage limit..."}` — the
account was **usage-limited until 2026-11-19**.

**What codex offers that the other two harnesses do not** (read from
`codex exec --help`, codex 0.164.0):

| capability | note |
|---|---|
| `codex exec resume` | resume by session id, or `--last` for the most recent — **session continuity**, which nothing else in the registry has |
| `codex exec review` | a purpose-built repository review mode |
| `--worktree` | run the session in a new *managed* git worktree |
| `-c key=value`, `-p --profile` | layered config overrides; `-p` layers `$CODEX_HOME/<name>.config.toml` |
| `--oss`, `--local-provider` | `lmstudio` / `ollama` — a local-model path that bypasses any gateway |
| `--output-schema` | JSON Schema for the final response shape |
| `--ephemeral` | do not persist session files to disk |
| `--sandbox` | `read-only` / `workspace-write` / `danger-full-access` |

**Its sandbox boundary is stricter and better pinned than Claude Code's.**
Codex's `--sandbox` vocabulary is `read-only|workspace-write|danger-full-access`,
and the registry allowlist is `{"read-only", "workspace-write"}` — with
`danger-full-access` **deliberately excluded** and pinned by a fail-closed
test (`tests/unit/workers/test_shell_command_safety.py` asserts
`"danger-full-access" not in PERMISSION_MODES["codex"]` and that
requesting it raises). Claude's `bypassPermissions` is excluded the same
way. `workspace-write` — write the working tree, not outside it — is the
right default for an agent fleet that runs across repositories.

**Why a third harness is worth having at all.** The fleet's review
contract is 2 specialists + 1 random generalist
(`docs/specs/2026-10-03-agent-reviewed-trunk-based-dev.md` §4.4). The
value of the third agent is **independence** — a different model family
catches what the first two share. Claude and Qwen are both already in
the fleet.

**One fleet-wide defect stands in the way, and it is not codex's.**
`stream_format` is a **dead field**: declared on `WorkerConfig`
(`registry.py:74`, `:101`), set to `"json"` for claude and qwen and
`"text"` for codex, and read by **nothing** in `mahavishnu/` — only
asserted in tests. And the worker layer does **no JSON parsing**:
`grep json.loads` across `mahavishnu/workers/` has exactly one hit, in
`openhands.py`, which is not the shell backend. So
`claude --output-format stream-json`, `qwen -o stream-json` and
`codex exec --json` all emit structured output that the backend collects
as opaque text. Codex's `--json` flag is therefore currently inert, and
so are the other two harnesses' structured-output flags.

## Decision

**1. The terminal-codex worker stays and becomes a first-class third
harness** — registered, tested, exercised by a demo, and usable as an
ensemble-review agent.

**2. Codex's traffic goes through the Bifrost gateway, with a gateway
virtual key** — not with codex's own ChatGPT subscription.

- `RouteKind.CODEX_ROUTE` is added in **oneiric** (the enum lives
  there), and `mahavishnu/terminal/manager.py` gains a `terminal-codex`
  branch that injects the gateway's OpenAI-compatible base URL, exactly
  as the `terminal-qwen` branch does today.
- The credential is the **Bifrost virtual key** (`BIFROST_VIRTUAL_KEY`).
  The gateway authenticates with the gateway virtual key and rejects a
  provider's own key with `401 virtual_key_required`; codex supports
  API-key authentication (`codex login --with-api-key`, documented as
  *"Read the API key from stdin"*), so the credential model is
  compatible.
- **The mechanism is an implementation detail, and this record does not
  pretend otherwise.** Two candidates: an environment variable
  (`OPENAI_BASE_URL` + `OPENAI_API_KEY`) or a `model_providers` block in
  codex's `config.toml`. The probe that settles it is
  `codex exec --strict-config -c 'model_providers.bifrost.base_url="…"' — `--strict-config`errors on an unrecognised key, and it is supported only for`codex exec\`, which could not be run from the review
  environment (the sandbox classifier blocks executing the external
  codex agent). **This must be verified before implementation.**

**3. The model and provider are pinned in mahavishnu's configuration,
not in `~/.codex/config.toml`.** A fleet worker whose model depends on
each operator's personal config is not reproducible, and the fleet's
three harnesses must be comparable. codex's `-c`, `-p` and
`--ignore-user-config` provide the mechanism; the chosen model id lives
in mahavishnu's settings, alongside the other harnesses'.

**4. The prerequisites are ordered, and the first one is trivial while
the second is the highest-value item on the list.**

1. **Fix the two invocation defects** in `registry.py` — close stdin and
   add `--skip-git-repo-check`. Two tokens of command string. Without
   this, a codex dispatch blocks or refuses, and nothing else matters.
1. **Make the worker layer actually parse the structured output it
   already collects**, and stop `stream_format` being a dead field.
   This is **fleet-wide, not codex-specific**: it is worth more than
   adding a worker, because it unblocks codex, unblocks the
   worker-tool-output measurement work, and fixes claude and qwen at the
   same time.
1. **Pin the model and provider** in mahavishnu's configuration.
1. **Then add the gateway route** (oneiric's `RouteKind` plus the
   manager branch), and only then the demo.

**5. Two questions this record explicitly does not settle.**

- The **toolchain** a dispatch runs (the login-shell `PATH` question) is
  already §9 deferral 4 of `docs/plans/2026-11-01-control-plane-consolidation.md`
  and is owned with Phase 7's launch protocol, not here.
- Whether codex's `--worktree` is compatible with this repo's worktree
  convention (`~/.local/state/mahavishnu/worktrees/<repo>/`) is **not**
  settled by this record. Codex would create *its own* managed worktree
  location, which would bypass the convention. That needs its own
  decision before any codex dispatch runs in a worktree.

## Why

**The gateway exists so every harness's traffic is visible, controllable
and swappable in one place.** A worker that bypasses it is a hole
*beside* the governed lane, not a neutral alternative. Today codex's
dispatches are invisible to all four gateway series —
`mahavishnu_bifrost_dispatch_total{outcome, provider, route_class}`,
`mahavishnu_bifrost_dispatch_latency_seconds{provider, route_class}`,
`mahavishnu_bifrost_dispatch_failures_total{provider, reason}` and
`mahavishnu_bifrost_local_dispatch_total{outcome, provider, route_class}`
— and to every place an operator can change which model a fleet uses.

**The alternative was considered and rejected.** Keeping codex on its own
ChatGPT subscription preserves that plan's billing and gives codex its
own auth path. But it leaves codex's traffic outside the gateway's
metrics, outside its caching (`ONEIRIC_BIFROST_CACHE_MODE=semantic`
today), outside its rate limiting, and outside the single place where a
model is swapped. On the fleet's primary dispatch path, a billing
convenience does not outweigh a governance hole.

**Independence is the reason to want codex specifically.** Not "one more
harness" — a different model family in the ensemble.

**Why the ordering puts the fleet-wide fix second.** Making the worker
layer parse the JSON it already collects is worth more than adding a
worker: it fixes claude and qwen, it is a precondition for codex, and
it is what the output-measurement work needs. The codex work is
therefore sequenced *behind* it rather than instead of it.

**Why the account limit is not an argument against.** The documented
limit (until 2026-11-19) means the codex demo reports `status: skipped`
— a supported outcome with a stated reason, not a failure. A demo that
fails because the operator's account is exhausted is noise; a demo that
skips with a reason is signal.

## Status

Proposed; **not yet implemented**. The gateway-route half is a
**cross-repo** change — oneiric owns `RouteKind`, this repo owns the
manager branch and the registry.

Verified 2026-11-05 against live code: the registry entry, the installed
CLI version, the live `ONEIRIC_BIFROST_ROUTES`, the two-member
`RouteKind`, the absence of a `terminal-codex` branch in the manager,
Bifrost's `/v1/responses` route, the two missing invocation fixes, the
`codex login --with-api-key` surface, and the permission-mode
allowlists.

**Not verified:** that codex 0.164.0 accepts a `model_providers` config
block (the probe is `codex exec --strict-config`, which the review
environment's sandbox classifier blocks); whether the account limit has
lifted since 2026-11-05; and codex's behaviour under the two fixes,
since a codex invocation could not be run from the review environment.

## Reference

- `docs/plans/2026-11-01-control-plane-consolidation.md` — Phase 7 (the
  launch protocol and readiness handshake), Phase 3 task 6 (the durable
  substrate and the store's write cost), §9 deferral 4 (the toolchain).
- `docs/plans/2026-11-01-terminal-cli-harness-demos-and-dispatch-trust.md`
  — **superseded** by the consolidation plan; its Phase 1 becomes that
  plan's Phase 7, and its §4.2 smoke test is the source of the two
  invocation defects above.
- `mahavishnu/workers/registry.py:240-258` — the worker entry.
- `mahavishnu/terminal/manager.py:66-93` — the Bifrost env injection,
  and the branch codex does not have.
