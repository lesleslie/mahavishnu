---
status: draft
role: implementation
kind: plan
date: 2026-11-02
last_reviewed: 2026-11-02
superseded_by: null
topic: worker-output-compaction
title: "Worker tool-output compaction — RTK-style savings without a second gateway"
requirements:
  - id: REQ-COMP-01
    title: "A worker dispatch's context composition is measurable from data the control plane already captures"
    description: "Per dispatch, the control plane can report total bytes by event kind, tool-result bytes by tool name, and the estimated input tokens, with the estimation method stated. The measurement runs over already-captured worker output and requires no new runtime instrumentation of the agent."
  - id: REQ-COMP-02
    title: "Compaction changes only what the model reads, never what the worker does"
    description: "The compaction mechanism must not alter the command a tool executes, must not alter the exit status, and must not alter the tool's effect on the filesystem. A filter that drops a signal the model needed is a defect, not a saving."
  - id: REQ-COMP-03
    title: "The compaction is fail-open"
    description: "If the filter, the hook handler, or the configuration is missing, disabled, or raises, the original tool result reaches the model unchanged. Compaction is never allowed to turn a successful worker dispatch into a failed one."
  - id: REQ-COMP-04
    title: "The compaction is opt-in and reversible without a code change"
    description: "A deployment setting disables it. The default is disabled, so shipping the code changes no behavior until an operator turns it on."
  - id: REQ-COMP-05
    title: "Savings are measured, not asserted"
    description: "Any savings claim states the task corpus, the baseline, the token estimator, and the task-success delta. A byte reduction reported without a task-success delta is not a savings claim."
  - id: REQ-COMP-06
    title: "The compaction adds no gateway, no second failure-management stack, and no second envelope"
    description: "The mechanism introduces no new network hop, no retry or circuit-breaker logic, no new result envelope, and no new state machine. It is a local transform inside the worker session."
---

# Worker tool-output compaction — RTK-style savings without a second gateway

> **Status: draft.** This plan is measurement-first. Nothing ships until
> Phase 1 establishes how much of a worker's billed context is tool
> output, because the fleet has no worker traffic data yet and a
> compaction layer that saves 3% is worse than no compaction layer.
>
> **Origin:** the OmniRoute survey (2026-11-02). OmniRoute's one
> capability Bifrost lacks is tool-output compression — but it vendors
> two standalone projects to get it (`rtk-ai/rtk`, `juliusbrussee/caveman`),
> and the transferable part is the *idea*, not the gateway.

## 1. Outcome

**A worker's billed context shrinks by a measured, reproducible fraction,
without the worker doing less work.**

The success signal is a single report:

```text
$ mahavishnu workers compaction-report --corpus tasks/worker-bench-v1
worker_type            dispatches   input_tok_before   input_tok_after   saved   task_success_delta
terminal-claude                  24          3,918,442          2,744,910   30.0%   +0.0 pp
```

Three properties make it trustworthy, and each is a requirement, not a
nice-to-have:

1. **The saving is measured**, with the estimator stated and the task
   corpus fixed.
2. **Task success does not regress.** A byte reduction without a
   success-rate delta is not a saving; it is a defect with a good
   slide.
3. **The mechanism is local.** No new gateway, no new hop, no new
   failure-management stack.

## 2. Goals

1. **Establish the ceiling before building anything.** Answer, with
   measurement, what fraction of a worker's billed input tokens comes
   from tool output — and how much that fraction compounds across the
   turns of a single one-shot session.
2. **Compact tool results inside the agent's own tool loop**, so the
   smaller bytes are what the model reads *and* what enters the cached
   request prefix.
3. **Keep the worker's behavior byte-identical.** The same command
   runs, the same exit status comes back, the same files change. Only
   the model's *view* of the output shrinks.
4. **Fail open, always.** A compaction bug costs a few tokens. A
   compaction bug that breaks a dispatch costs the whole task.
5. **Ship disabled.** The mechanism lands inert; an operator turns it
   on per worker type after seeing the numbers.
6. **Stay inside the fleet's existing architecture**: one gateway
   (Bifrost), one envelope, one worker registry, no second control
   plane.

## 3. Non-Goals

1. **Not** a second gateway, a proxy, or a sidecar in the request path.
   A gateway fronting a gateway compounds retry and circuit-breaker
   logic — the reasoning already recorded in
   `mahavishnu/terminal/manager.py:28-31`.
2. **Not** prompt-side compaction of the task brief. It is a different
   lever (§4.5, L2), it has a worse signal-loss profile, and it would
   collide with the control-plane plan's prompt-digest contract
   (REQ-C10). Deferred, not rejected.
3. **Not** cost accounting. The control-plane consolidation plan
   explicitly defers it (its non-goal 8) because a worker leg's real
   cost is wall-clock, not tokens. This plan produces *local
   measurements*, not a fleet-wide cost model.
4. **Not** learning per-repo output policies from task feedback. That
   is a training-time system (Hermit's shape) needing a labeled task
   suite and a scoring callback we do not have.
5. **Not** a retrieval layer. LEANN's lane — "avoid injecting context
   you never needed" — is orthogonal and is a separate plan.
6. **Not** pruning the worker's tool definitions or injecting learned
   repo facts. Those are TokenEconomizer's mechanisms; they are real
   levers but they mutate the request prefix, which carries a
   prompt-cache cost this plan does not take on (§4.7).
7. **Not** vendoring RTK. RTK's default edition is Apache-2.0 +
   BUSL-1.1; only `rtk-oss` is Apache-2.0 alone, and a Rust binary
   would have to be installed on every local, delegated, and cloud
   worker host. The mechanism is ours; RTK is the reference (§4.6).

## 4. Current Findings

### 4.1 The waste is real in principle, and unmeasured in fact

RTK's own documentation is careful about this, and the caution
transfers:

> *"RTK reduces the **bash output** your agent reads. That is what RTK
> measures, and it is not the same as cutting your bill by the same
> amount. Bash output is **one contributor to input tokens**, alongside
> your prompt, the system prompt and conversation history."*

A competitor's estimate (`alexgreensh/token-optimizer`, itself
unverified) puts command output at **15–25% of context**. That is a
prior to test against our own telemetry, not a number to plan
against.

### 4.2 The compaction has to happen inside the agent's tool loop

This is the constraint that shapes the whole plan.

Mahavishnu dispatches a prompt to a one-shot CLI worker and captures
the pane (`mahavishnu/workers/shell_backend.py:346-410`). The tool
output that dominates the worker's context is generated and consumed
**inside the agent's own tool loop**, between our dispatch and our
capture. By the time we see it, the tokens are billed.

Therefore:

| Seam | What it compacts | Billed saving |
|---|---|---|
| `WorkerResult.output` after capture | our stored copy | **none** — the tokens were already spent |
| The prompt we assemble (L2) | the task brief | once per dispatch |
| **Inside the agent's tool loop** | **tool results, on every turn** | **compounds across turns** |

Only the third row is this plan. The first row is a storage
optimization wearing a cost-optimization costume, and it is the
mistake this plan exists to prevent.

The compounding matters more than it first appears. A one-shot worker
session with *N* turns resends the whole history each turn, so
removing *X* bytes from one tool result saves *X* bytes on that turn
**and on every subsequent turn of the same session**. The billed
saving is therefore roughly *N×* the naive per-turn ratio. The
measurement in Phase 1 must compute the compounded figure, not the
last-turn ratio, or it will understate the lever by an order of
magnitude.

### 4.3 The hook surface exists, and there are two rewriting events

Claude Code v2.1.316 (the version this fleet runs) exposes:

- **`--settings`** — "pass a key as JSON, inline or as a path to a
  file. Claude Code applies it above your user, project, and local
  files and below managed settings. It can set any key your user
  settings file can set." This is decisive: we can carry a `hooks`
  block **without** writing to the user's `~/.claude/settings.json`
  (which would also affect their interactive sessions) and **without**
  writing into a target repository's `.claude/settings.json` (which
  would be invasive in other people's repos).
- **Environment variables are not a settings level.** "Environment
  variables aren't a level in this stack." So there is no env-var
  seam for settings; `--settings` is the seam.
- **`PreToolUse`** → `hookSpecificOutput.updatedInput` "replaces a
  tool's arguments before it runs." This is RTK's mechanism: rewrite
  `pytest` into `rtk pytest`.
- **`PostToolUse`** → `updatedToolOutput` "replaces the tool's
  result." **This is the better seam.**
- **`--bare`** skips hooks "those defined in settings and by installed
  plugins" — hooks are a first-class, skippable mechanism, not a
  backdoor.
- Hooks fire "on every tool call inside the agentic loop."

`PostToolUse` wins on blast radius. `PreToolUse` rewrites the
*command*, so a bad rewrite changes what the worker does — violating
REQ-COMP-02 at the mechanism level. `PostToolUse` leaves the command
alone and replaces only the *result*, so the worker's behavior is
byte-identical by construction. Same token saving, strictly smaller
failure surface.

#### 4.3.1 The seam rides an environment variable, not a placeholder

The `--settings` path has to reach the CLI, and there are two ways to do
that. **Only one of them is safe here**, and the reason is worth
recording because the other one looks perfectly reasonable.

`render_command` (`mahavishnu/workers/shell_backend.py:136-185`) has a
**hardcoded two-placeholder contract**: it substitutes `{permission_mode}`,
and it *raises* on `{prompt}`. There is no general placeholder
mechanism. A `{settings}` placeholder in a registry command template
would therefore need `render_command` to learn a third placeholder — and
`render_command` is exactly the function the consolidation plan's Phase 7
rewrites. Worse, the failure mode is **silent**: only `{prompt}` raises,
so an unrecognized `{settings}` would fall through *unsubstituted* and
reach the CLI as literal text. A third placeholder is a collision with
Phase 7 *and* a silent-failure hazard.

The prompt already solved this. The prompt does not ride as a
placeholder — it rides as an environment variable, and the command
references `"$MAHAVISHNU_PROMPT"`. The settings path should ride the
same way:

```text
command='sh -lc \'claude -p --verbose --output-format stream-json \
  --permission-mode {permission_mode} --settings "$MAHAVISHNU_SETTINGS" \
  "$MAHAVISHNU_PROMPT" ...\''
```

That needs **no `render_command` change at all**, and the injection
rides `env_overrides` at `shell_backend.py:373-403` — the same mechanism
the prompt file path already uses. The path is short, so it rides
directly in the environment; it does not need the prompt's two-step
file-plus-prologue dance, which exists only because tmux caps its argv.

**One wrinkle, and its resolution.** If `MAHAVISHNU_SETTINGS` is unset
(`mode=off`), `"$MAHAVISHNU_SETTINGS"` expands to empty and
`claude --settings ""` is a bad flag. Making the flag conditional needs
a conditional template — which needs `render_command` to change, which
is the collision. The resolution is to make the template
**unconditional** and always create a settings file: an empty-hooks one
in `mode=off`, the hook-bearing one in `measure`/`apply`. The template
stays static, `render_command` stays untouched, and the only
`shell_backend.py` touch is one env var and one temp file.

The cost of that bargain, stated plainly: **every dispatch of an
affected worker type now carries one more flag and one more temp file,
even with the compaction disabled.** That is a small, permanent change
to the dispatch path, bought with the removal of a coordination
dependency. Phase 2 measures it; if it is not small, the conditional
template is reconsidered — but only *after* consolidation Phase 7, and
with agreement that `render_command` grows a third placeholder then,
not before.

### 4.4 The PATH route is closed, and the reason is macOS-specific

The obvious agent-agnostic mechanism is a shim directory on `PATH`
that intercepts `pytest`, `git`, `ruff` and friends. It does not work
as inherited, and the reason is worth recording because it will
otherwise be re-litigated.

Measured on this host:

```
$ PATH="$SHIM:$PATH" sh -lc 'command -v pytest'
/usr/local/bin/pytest              # the real one — the shim lost

$ PATH="$SHIM:$PATH" sh -lc 'export PATH="$SHIM:$PATH"; command -v pytest'
/var/folders/.../pytest            # the shim wins
```

`/etc/profile:3-4` runs `eval \`/usr/libexec/path_helper -s\``, which
**rebuilds** `PATH` and demotes anything inherited below the system
directories. Every command we would want to intercept (`pytest`,
`ruff`, `git`, `ls`) has a system copy that wins the lookup. The
inherited `PATH` from `tmux new-session -e` therefore cannot deliver a
shim.

The inner `export` does work — but it lives inside the `sh -lc`
payload, which is the registry's command template
(`mahavishnu/workers/registry.py:222-227`). So the PATH route needs
the same registry edit that the hook route needs, while being
agent-*specific* in what it intercepts. **The hook route dominates it.**
The PATH finding is retained here as a closed question, not a
fallback.

### 4.5 Two levers, measured separately

| | **L1 — tool-result compaction** | **L2 — prompt-assembly compaction** |
|---|---|---|
| Where | inside the agent's tool loop | mahavishnu's prompt builder |
| What shrinks | tool results, every turn | the task brief, once |
| Billed saving | compounds across turns | once per dispatch |
| Seam | `--settings` + a hook handler | none — already ours |
| Signal-loss risk | moderate (a dropped failure detail) | **higher** (a dropped requirement) |
| Collision risk | registry command template | prompt-digest contract (REQ-C10) |
| Verdict | **this plan** | deferred (§3 non-goal 2) |

L2 is deferred rather than rejected on one specific ground: the
control-plane consolidation plan's REQ-C10 verifies "the prompt the CLI
read" against a digest the worker wrote. Any prompt-side transform
must be sequenced *after* that plan's Phase 7, or the digest is
computed over bytes the CLI never read. L1 does not touch prompt bytes
at all, so L1 and REQ-C10 do not interact.

### 4.6 Prior art: what to steal, what to refuse

| Project | License | Adopt? | Why |
|---|---|---|---|
| `rtk-ai/rtk` (85,266★, Rust) | Apache-2.0 **+ BUSL-1.1**; `rtk-oss` edition is Apache-2.0 alone; `rtk-proxy` is BUSL-1.1 | **Reference only** | The filter catalogue (pytest → failures only, traceback trimmed; `git diff` → reduced context, headers stripped; `git log` → hash/author/subject; `ruff` → grouped by rule and file) and the `bytes/4` token estimator are worth copying. The binary is not: a Rust install on every local, delegated, and cloud worker host, under a source-available license, for a mechanism we can own in Python. |
| `juliusbrussee/caveman` (116,794★, Go) | Apache-2.0 | **No** | Prose degradation ("talk like a caveman"). Our workers emit code patches and JSON envelopes; degrading prose there loses signal. Its structural half (dedup, line caps, ANSI stripping) is already in RTK's catalogue. |
| `microsoft/TokenEconomizer` (4,241★) | Apache-2.0 | **No — but steal one rule** | It has **no output compaction at all**; its three mechanisms (micro-skills, tool pruning, loop guard) reduce *repeated* context. But it encodes the one hard constraint we must respect (§4.7). Also: one release (v0.1.0), created 2026-10-13, pins Claude Code 2.1.300–2.1.310 — we run 2.1.316, already outside its window. |
| `StarTrail-org/LEANN` (13,750★, MLSys 2026 Best Paper) | MIT | **No — orthogonal** | Selective recomputation over a pruned graph; never stores embeddings. Its MCP `search` tool beats `grep` on relevance, so the worker gets the right 8 KB instead of the wrong 50 KB. Complementary to compression, and its dependency floor (torch, sentence-transformers, llama-index) makes it sidecar-only, never in the worker path. **But steal its benchmark harness** (§4.8). |
| `Infini-AI-Lab/hermit` (443★) | Apache-2.0 | **No** | A harness-adapter evolution / continual-learning framework — a *training-time* system for a *runtime* problem. It needs a labeled task suite and a scoring callback we do not have, and costs several model calls per training step. Its one transferable idea — learn a per-repo output policy from evidence — needs exactly the task suite we lack. |
| `alexgreensh/token-optimizer` (2,843★) | **PolyForm Noncommercial** | **No** | Not OSI-licensed; noncommercial terms are wrong for an internal control plane. Use as a design reference only. |

Two corrections worth recording, since both were wrong in the original
briefing: **`microsoft/TokenOptimizer` does not exist** (the project
is `microsoft/TokenEconomizer`), and **`Infini-AI-Lab/hermit` is not an
inference-cost project at all**.

### 4.7 The cache-safety constraint

Anthropic-style prompt caching is a **prefix match**. Anything that
rewrites bytes already in the request prefix invalidates everything
after it.

TokenEconomizer encodes the rule precisely, and it is worth quoting
because it is the kind of thing that costs real money:

> *"A conversation resumed after its tools change must write its whole
> history to the prompt cache again instead of reading it, and after an
> idle hour that cache has expired anyway."*

Its conclusion: **never mutate the request prefix mid-session; only
mutate at a cold-start boundary.**

This plan's mechanism happens to be *cache-positive*, and the reason
is worth stating because it is the opposite of what a proxy-mode
rewrite would do:

- **In-agent compaction (our design):** the compacted bytes are what
  the model sees *and* what enters the cached prefix. The prefix is
  smaller and stable across turns. Cache hit ratio goes **up**.
- **Proxy-mode rewriting (RTK's `proxy.request.tool_result`):** the
  request is built with the original bytes and rewritten in flight.
  The prefix changes every turn. Cache hit ratio goes **down**.

That asymmetry is a second, independent reason to prefer the hook
seam over a proxy — and a third reason to prefer it over RTK's
proxy edition.

### 4.8 Measure before building, and borrow the harness

The measurement template is LEANN's ContextBench runner: Claude CLI +
mitmproxy trace recorder + `ccusage`, with model, agent, tools, and
budget held fixed and **one variable changed**. Its reported result —
2.1× relevant-code recall vs BM25 and 8.4% fewer tokens over 30
SWE-Bench Pro tasks — is small and carefully caveated ("Better context
access does not guarantee issue resolution"), which is what a
retrieval-budget-capped comparison deserves.

TokenEconomizer's cost accounting is the other template: **cache
pricing, and the plugin's own overhead counted against it.** A saving
that excludes the cost of the mechanism producing the saving is not a
saving.

And its results show why the success-rate column is not optional: the
Opus 4.8 cell was **−30.9% cost for −1.0 Pass@1**. Cost bought with
quality is a trade, not a win, and only the success-rate delta
distinguishes them.

### 4.9 Dead configuration in the worker path

Two `WorkerConfig` fields are declared and read by nobody:

- **`stream_format`** — set on every registry entry ("json", "text"),
  consumed nowhere. It is the natural signal that a worker produces
  machine-readable output.
- **`env_vars`** — a per-worker env-var map with no consumer. Its one
  plausible historical consumer was the Kubernetes manifest generator
  (`mahavishnu/core/k8s_manifests.py`, removed 2026-11-02 — see §4.12).

Neither is built on by this plan. `env_vars` in particular must **not**
be revived: the control-plane consolidation plan's Phase 3 owns the
worker-registry schema, and reviving a dead field there collides with
its likely removal. The compaction's configuration is a settings key
plus an env var set at dispatch time, not a registry field.

The *positive* use of `stream_format` is as the analyzer's input
contract — Phase 1's parser should honor it, which turns a dead field
into a consumed one without changing the registry schema.

### 4.10 What we already capture, and what we do not

The pane output of a `terminal-claude` dispatch contains Claude Code's
`--output-format stream-json` stream, which carries the `tool_use`
inputs and the `tool_result` contents. **The bash-output byte share is
therefore measurable from what we already capture** — no new
instrumentation inside the agent, and no new data path.

What does not exist today:

- **Zero token-usage parsing** in `mahavishnu/workers/` or
  `mahavishnu/pools/`. `grep -rn "input_tokens\|output_tokens"` over
  both directories returns nothing. We cannot currently state a
  worker's billed token count from mahavishnu's side.
- **No retained corpus.** `WorkerResult.output` holds the captured
  pane in memory for the life of the result; there is no archive to
  analyze offline.

Phase 1 therefore has two jobs: build the analyzer, and stand up a
small retained corpus of captured worker outputs to run it over.

### 4.11 Cross-plan integration

Seventeen other plans are live. Two collide; the rest do not.

#### 4.11.1 `2026-11-01-control-plane-consolidation.md` — hard sequencing

The concurrent session's plan (draft, canonical). The revision this
plan is written against is **committed** — `e29b966f` (round-2 review
findings) + `38f757e5` (the policy section), **3,131 lines**, tree
clean. An earlier draft of this section quoted an in-flight
working-tree snapshot; the numbers below are the committed revision.

Its Phase 7 was materially revised in ways that matter here, and this
plan has been **re-read against the revision** rather than patched
against the old text:

- **Phase 7 task 3 replaces the launch protocol with a generated
  launcher.** The string handed to `terminal_manager.launch_sessions`
  becomes `sh <launcher>`, where the launcher reads the prompt file into
  `MAHAVISHNU_PROMPT`, exports it, emits `__MAHAVISHNU_READY__` with
  the prompt's byte count, and then `exec`s the registry command. Our
  `--settings "$MAHAVISHNU_SETTINGS"` reference lives in the **registry
  command**, which the launcher `exec`s — so it survives the rewrite —
  but it depends on that launcher **preserving the session
  environment**. If the launcher scrubs or allowlists the environment,
  our variable must be added to its allowlist. That is a named
  dependency, not a hope.
- **The envelope split (`routing_type` vs `operation`)**, the store
  findings, and Phase 5's per-key record option do not reach this plan:
  it touches no envelope, writes no workflow record, and reads no store.
- **The plan is forward-only.** It carries a top-level
  `## Policy: No backwards compatibility / legacy support` section: no
  deprecation windows, no aliases, no re-export shims, no migration of
  old data. **This plan therefore assumes no compatibility surface from
  it.** The compaction ships as a new setting with a kill switch, and
  nothing here depends on an alias or a transition period existing.

| Consolidation phase | Owns | Consequence for this plan |
|---|---|---|
| Phase 3 — worker-registry schema | `mahavishnu/workers/registry.py` | Its touch is one line (`_legacy_config_to_entry`'s `command_argv` shape). It **keeps** `env_vars` and `stream_format`, so our refusal to build on `env_vars` and our use of `stream_format` as the analyzer's input contract both survive. Our registry edit lands after it. |
| Phase 4 — one execution envelope, owned spans | `mahavishnu/core/observability.py` | We add **no span**. Our signal is a structured log (§4.11.3). |
| Phase 5 — pool lane joins the workflow lane | `mahavishnu/pools/manager.py` | We touch no pool file. |
| Phase 6 — composition | `mahavishnu/core/conductor.py` | No interaction — the compaction is inside the worker session, upstream of the conductor. |
| Phase 7 — dispatch trustworthiness | `mahavishnu/workers/shell_backend.py` | A real restructure, not a one-liner: the launch protocol moves into a generated launcher. **Our dispatch-time wiring lands as one change with Phase 7, not as a later separate change** — the settings file is part of that path's blast radius. REQ-C10's prompt digest is unaffected (L1 does not touch prompt bytes). |

Six rules this plan takes on, from its §4.13, §2.1, and Phase 7:

1. **One transition, one owner.** The compaction does not settle,
   report, or transition anything. It transforms a tool result inside
   the worker's own loop. It is not a participant in the state machine.
2. **No new envelope.** The compaction does not add a field, a
   wrapper, or a status. It changes bytes the model reads.
3. **The dispatch-latency budget does not grow.** The consolidation
   plan holds the pool lane's documented ~200–500 ms routing overhead
   as a ceiling. The compaction adds work *inside* the agent's loop
   (per tool call), not on the dispatch path — but a hook handler that
   hangs would blow the worker's wall-clock, which that plan explicitly
   cares about. The handler must be bounded and fail-open (REQ-COMP-03).
4. **Cost accounting is not duplicated.** The consolidation plan
   defers cost accounting (non-goal 8); we produce local measurements,
   not a fleet cost model, and we do not touch `ADAPTER_COSTS`.
5. **Temp-file hygiene.** Our settings file is held to the same
   standard the launcher is: `tempfile.mkstemp` (**O_EXCL**, mode
   **0600**), the same private directory as the prompt file, removed
   with it at teardown. A fixed pathname in a shared directory is a
   symlink target, and the default umask would make it world-readable.
6. **`render_command` does not grow a placeholder.** Our seam is an
   environment variable (§4.3.1). If anyone later "fixes" the
   `--settings` reference into a `{settings}` placeholder, they
   re-introduce the collision with Phase 7 *and* the silent
   pass-through hazard. Both plans should record that the reference is
   an env var, so the next reader does not "tidy" it.

#### 4.11.2 `2026-10-29-bifrost-bodai-cache-wiring.md` — ordering

Active, canonical. Its Phase 5 touches `mahavishnu/workers/registry.py`
and `mahavishnu/pools/manager.py` — the same registry file as our
Phase 3. **It lands first.**

#### 4.11.3 The rest — no collision, two notes

| Plan | Status | Relationship |
|---|---|---|
| `2026-10-27-otel-metrics-service.md` | draft | Owns `core/observability.py` and `core/config.py`. Our compaction metric would collide there. **Disposition: emit a structured oneiric log in Phase 3; defer any OTel instrument to a follow-up after that plan lands.** Our `core/config.py` change is a new settings field — different symbol, no conflict. |
| `2026-10-27-bodai-producer-span-reporting.md` | active | Owns producer spans. **We add no span and re-home none.** |
| `2026-10-19-bifrost-mcp-skills-aggregation.md` | active | Bifrost MCP + skills distribution. **Opportunity, not collision:** a compaction *skill* could ship through an existing distribution path rather than a second one. Check before building a second distribution mechanism. |
| `2026-10-03-eval-adapter-phase1.md` | active | `core/config.py`, `pools/manager.py`. Different fields; no conflict. |
| `2026-10-29-agno-failover-and-gateway-repairs.md` | active | `core/config.py`. Different fields; no conflict. |
| `2026-10-14-decision-adapter-category.md` | active | Owns `core/task_router.py`. No overlap. |
| `2026-10-30-task-workflow-backlink.md` | active | Binds tasks to workflows. No overlap; our measurement is offline. |
| `2026-10-31-mcp-substrate-rewire.md`, `2026-10-31-substrate-calltime-rewire.md` | active (shipped — status drift) | No overlap. |
| `2026-11-01-bifrost-cache-eviction-and-threshold.md` | active | No overlap. Shares the method: measure before you tune. |
| `2026-10-15-ble001-triage-and-refactor.md`, `2026-10-12-ruff-cleanup-post-regrowth.md`, `2026-10-21-bifrost-cli-consolidation.md`, `2026-10-29-oneiric-resolver-plans.md`, `2026-10-12-mcp-common-test-backfill.md`, `2026-08-31-zsh-modernization.md` | various | No overlap with the surfaces this plan touches. |

### 4.12 A dead Kubernetes module, and what it teaches this plan

`mahavishnu/core/k8s_manifests.py` (665 lines) plus its test file
(543 lines) are dead. Kubernetes support was dropped in `c95fade6`
("refactor(pools): remove KubernetesPool"); the manifest generator was
left behind, and the only thing referencing it is its own test.

Two things about that are worth carrying into this plan:

- **`scripts/audit_orphans.py` cannot catch it.** The audit only
  considers symbols modified within a lookback window, so a module
  nobody has touched in months is invisible to it. "The orphan audit
  is clean" is not the same as "there are no orphans."
- **The doc line that kept it alive named a consumer that did not
  exist.** `docs/pools/POOL_ARCHITECTURE.md` said the manifests
  "remain in `mahavishnu/core/k8s_manifests.py` for deployment
  documentation only" — but no script called the generator, and no
  generated manifest was committed anywhere.

The lesson for this plan: **a compaction layer justified by a
rationale rather than a caller is the same failure.** Phase 1's
deliverable is therefore not a plan to compress — it is a number. If
the number does not justify the mechanism, the mechanism does not get
built, and that is a successful outcome of this plan, not a failure.

### 4.13 Requirements index

| ID | Requirement | Phase |
|---|---|---|
| REQ-COMP-01 | Context composition is measurable from already-captured output | Phase 1 |
| REQ-COMP-02 | Compaction changes what the model reads, never what the worker does | Phase 2, Phase 3 |
| REQ-COMP-03 | The compaction is fail-open | Phase 2, Phase 3 |
| REQ-COMP-04 | The compaction is opt-in and reversible without a code change | Phase 3 |
| REQ-COMP-05 | Savings are measured, not asserted | Phase 1, Phase 4 |
| REQ-COMP-06 | No gateway, no second failure-management stack, no second envelope | Phase 2, Phase 3 |

## 5. Implementation Phases

### Phase 1: Measure the ceiling

**Goal:** answer "what fraction of a worker's billed input tokens is
tool output, and how much does that compound across turns?" — with
the estimator stated, from data we already capture.

**Tasks:**

1. Build a stream-json analyzer that reads a captured
   `terminal-claude` output and reports, per dispatch: total bytes by
   event kind; `tool_use` input bytes by tool name; `tool_result`
   content bytes by tool name; and estimated input tokens.
2. **Honor `WorkerConfig.stream_format`** as the analyzer's input
   contract (§4.9) — a dead field becomes a consumed one, with no
   registry-schema change.
3. Use RTK's estimator — `bytes / 4` — and say so in the output.
   Percentages are reliable; absolute token counts are approximate.
4. Compute the **compounded** figure: for a session of *N* turns,
   bytes removed from a tool result at turn *k* are re-sent on turns
   *k+1…N*. Report the naive per-turn ratio *and* the compounded one.
5. Stand up a small retained corpus of captured worker outputs to
   analyze offline (e.g. `tasks/worker-bench-v1/`), with the dispatch
   conditions recorded per sample.

**Exit criteria:** a report giving the tool-output share of billed
input tokens, per worker type, with a confidence statement and the
compounded figure.

**Integration Contract**

- **Triggered from:** `mahavishnu workers analyze-context --input <path>`
  (or `scripts/analyze_worker_context.py` if the CLI surface is
  heavier than the analysis warrants). An offline entry point — it
  reads files, it does not dispatch.
- **Returns to / updates:** a JSON report written under
  `~/.local/state/mahavishnu/worker-context/`, and the measurement
  tables recorded in this plan's §4.1 as evidence.
- **Demonstrable by:** `mahavishnu workers analyze-context --input <sample>`
  prints the per-tool byte breakdown and the compounded saving
  estimate for one dispatch.
- **Rollback signal:** none — this phase is read-only and ships no
  runtime behavior.
- **Observability added:** none by design; this phase is a diagnostic.
  It is explicitly labeled as such.

### Phase 2: Spike the mechanism

**Goal:** prove the hook seam reaches the agent's tool loop, and prove
the fail-open path, before writing production code.

**Tasks:**

1. **Spike the `--settings` hook.** A minimal settings JSON carrying a
   `PostToolUse` hook on the `Bash` matcher, whose handler reads the
   JSON on stdin and returns `updatedToolOutput`. Verify with a real
   `terminal-claude` dispatch that the handler fires, that the
   replacement reaches the model, and that the command and its exit
   status are untouched (REQ-COMP-02).
2. **Prove fail-open (REQ-COMP-03).** Break the handler three ways —
   missing binary, non-zero exit, malformed JSON on stdin — and
   confirm the original tool result reaches the model in each case.
3. **Prove `--settings` does not suppress the user's own settings.**
   This is the risk the flag carries and it is not obvious from the
   docs. `--settings` "applies it above your user, project, and local
   files" — that reads as a *merge*, but a fleet worker runs the same
   `claude` binary as the user's interactive sessions, so if the flag
   *replaced* the settings stack, every dispatch would silently lose
   the user's MCP servers, permissions, and hooks. The spike must
   dispatch with `--settings` pointing at a settings file that defines
   only a hook, and confirm that (a) the user's
   `~/.claude/settings.json` still applies — a marker permission or an
   MCP server the user configured is still visible to the worker — and
   (b) the hook in the `--settings` file still fires. **If the stack is
   replaced rather than merged, this plan has no seam** and stops.
4. **Bound the handler.** The consolidation plan holds the worker
   wall-clock in view (§4.11.1 rule 3). Give the handler a hard
   timeout and measure its overhead per tool call against RTK's
   "<10 ms" claim, which is the number to beat or match.
5. **Decide the filter set** from Phase 1's per-tool byte table —
   only the tools that actually carry bytes earn a filter. Start with
   the catalogue in §4.6 (pytest, git diff/status/log, ruff, ls/tree,
   grep/rg).
6. **Decide the deployment shape.** The handler runs *inside the
   worker session*, on the worker's host. Options: a per-dispatch
   temp file in the existing `mkstemp` pattern
   (`shell_backend.py:_write_prompt_file`), or a stable installed
   script. The temp-file pattern matches the existing prompt-file and
   stderr-file handling and needs no install on delegated or cloud
   hosts; the trade-off is a per-dispatch Python start-up. The settings
   file follows the same pattern and the same hygiene rules as the
   prompt file (§4.11.1 rule 5).
7. **Confirm the `sh -lc` interaction.** The handler runs under the
   worker's shell; a handler written in Python must not depend on the
   demoted `PATH` (§4.4).
8. **Confirm the launcher preserves the environment.** After the
   consolidation plan's Phase 7, the session command is `sh <launcher>`
   and the registry command is `exec`'d from it. The settings path
   rides in the session environment as `MAHAVISHNU_SETTINGS`, so the
   launcher must preserve it. If the launcher scrubs or allowlists the
   environment, our variable must be added to its allowlist — a
   one-line coordination item, not a redesign (§4.11.1).

**Exit criteria:** a decision record naming the chosen mechanism, the
filter set, the deployment shape, and the measured per-call overhead —
with a fail-open demonstration attached.

**Integration Contract**

- **Triggered from:** a spike script under `scripts/` plus a real
  `terminal-claude` dispatch with the spike settings injected. This
  phase touches production code paths only under the spike's own
  explicit opt-in flag.
- **Returns to / updates:** a decision record at
  `docs/decisions/2026-11-02-worker-output-compaction-mechanism.md`,
  and the spike's evidence (handler output, fail-open transcripts)
  committed as fixtures under `tests/fixtures/compaction/`.
- **Demonstrable by:** the spike script printing, for one dispatch,
  the original tool-result byte count, the compacted byte count, and
  three fail-open transcripts showing the uncompacted result surviving.
- **Rollback signal:** the spike is disabled by default and gated on an
  explicit environment variable; removing that variable restores
  baseline behavior with no code change.
- **Observability added:** none. A spike is a diagnostic; the
  production signal is Phase 3's.

### Phase 3: Implement behind a kill switch

**Goal:** ship the mechanism inert, with an operator-facing switch.

**Tasks:**

1. **The filter module** — `mahavishnu/workers/output_compaction/`:
   one filter per tool, each a pure function from raw bytes to
   compacted bytes, each carrying a docstring stating *what it drops
   and why the model does not need it*. A filter that cannot justify
   its drops does not ship (REQ-COMP-02).
2. **The handler** — reads the hook JSON on stdin, applies the filter
   for the tool that produced the result, returns `updatedToolOutput`.
   Any failure returns exit 0 with no output, which Claude Code treats
   as "no decision" (REQ-COMP-03).
3. **The wiring** — the registry command template for the affected
   worker types gains `--settings "$MAHAVISHNU_SETTINGS"`, a literal
   environment-variable reference in the same shape as the existing
   `"$MAHAVISHNU_PROMPT"` (§4.3.1). **`render_command` is not
   modified**, and the settings file is **always** created — an
   empty-hooks one in `mode=off`, the hook-bearing one in
   `measure`/`apply` — so the template stays static and no flag is
   ever conditional. The path rides in `env_overrides`, beside
   `MAHAVISHNU_PROMPT_FILE` and `MAHAVISHNU_STDERR_PATH`.
   **Lands as one change with the control-plane consolidation plan's
   Phase 7**, not as a later separate change (§4.11.1), and after
   `2026-10-29-bifrost-bodai-cache-wiring`'s Phase 5.
4. **The switch** — `workers.output_compaction.enabled` (default
   `false`), `workers.output_compaction.mode`
   (`off` | `measure` | `apply`), and
   `workers.output_compaction.filters` (a per-tool allowlist).
   `measure` mode records what *would* have been saved without
   changing anything — so an operator can preview the saving before
   accepting the risk (REQ-COMP-04, REQ-COMP-05).
5. **The signal** — one structured log line per compacted tool
   result: `worker.output_compaction` with `worker_type`, `tool`,
   `bytes_before`, `bytes_after`, `filter`, `duration_ms`. A
   oneiric structured log, **not an OTel span** (§4.11.3).
6. **The kill switch** — `mode=off` restores baseline behavior with no
   code change and no redeploy of anything else. Note the residual
   cost recorded in §4.3.1: an affected worker type still carries one
   more flag and one more temp file per dispatch, because the template
   is unconditional.

**Exit criteria:** the mechanism ships disabled; `mode=measure`
produces a per-dispatch report; `mode=apply` produces the same report
plus compacted results; the fail-open path is covered by tests.

**Integration Contract**

- **Triggered from:** `ShellWorker.start()`
  (`mahavishnu/workers/shell_backend.py:346`) — the dispatch path that
  already assembles `env_overrides` and calls `render_command`. The
  settings file is created there and removed with the prompt and
  stderr files at teardown.
- **Returns to / updates:** the rendered worker command (now carrying
  `--settings <path>`) and the worker's session environment. The
  compaction's own state is the per-dispatch temp file, removed at
  teardown; there is no persistent store, because there is nothing to
  remember between dispatches.
- **Demonstrable by:** a `terminal-claude` dispatch with
  `mode=measure` whose log carries a `worker.output_compaction` line
  for each Bash tool result, and a dispatch with `mode=apply` whose
  captured output shows the compacted summary.
- **Rollback signal:** `mode=off` in settings, or the
  `worker.output_compaction.filter_error` counter exceeding 1% of
  compacted tool results, or any worker-dispatch failure rate increase
  attributable to the mechanism. The handler's own failure is already
  fail-open, so this signal covers the wiring, not the filter.
- **Observability added:** structured log
  `worker.output_compaction` (oneiric), carrying `worker_type`,
  `tool`, `bytes_before`, `bytes_after`, `filter`, `duration_ms`.
  No OTel span — the `2026-10-27-otel-metrics-service` plan owns that
  surface (§4.11.3).

### Phase 4: Prove the saving, or withdraw the mechanism

**Goal:** produce the §1 report, or withdraw.

**Tasks:**

1. Run the fixed task corpus with `mode=off` and with `mode=apply`.
   Hold the model, the agent, the tools, and the permission mode fixed;
   change exactly one variable — the compaction. (LEANN's ContextBench
   discipline.)
2. Report **three** numbers, not one: input tokens saved, **task
   success-rate delta**, and cache-hit-rate delta. The third is
   non-optional — §4.7 explains why, and TokenEconomizer's Opus 4.8
   cell (−30.9% cost, −1.0 Pass@1) is the concrete shape of the
   failure this catches.
3. Count the mechanism's own overhead in the saving, on RTK's and
   TokenEconomizer's accounting (the filter's cost, the handler's
   start-up, the extra bytes the compaction itself adds).
4. If the task-success delta is negative, **withdraw** the mechanism
   and record why. §4.12 applies: a rationale is not a consumer.

**Exit criteria:** the §1 report, with all three numbers and the
estimator stated — or a withdrawn mechanism with the reason recorded.

**Integration Contract**

- **Triggered from:** `mahavishnu workers compaction-report --corpus
  tasks/worker-bench-v1`, run twice against a fixed corpus.
- **Returns to / updates:** the report artifact under
  `~/.local/state/mahavishnu/worker-context/`, and the result
  recorded in this plan's §4.1 evidence tables.
- **Demonstrable by:** the report showing input tokens before and
  after, the task-success delta, and the cache-hit-rate delta for the
  same corpus.
- **Rollback signal:** a negative task-success delta, or a saving that
  does not survive the mechanism's own overhead being counted.
- **Observability added:** none new — the report aggregates Phase 3's
  structured log.

## 6. Required Code Changes

```text
mahavishnu/workers/output_compaction/
    __init__.py              # public surface: filter registry, apply()
    filters.py               # one pure filter per tool (pytest, git, ruff, ...)
    handler.py               # the hook handler: stdin JSON -> updatedToolOutput
    measure.py               # measure-mode accounting
mahavishnu/workers/shell_backend.py   # MODIFY: dispatch-time settings injection (env var + temp file)
mahavishnu/workers/registry.py        # MODIFY: --settings "$MAHAVISHNU_SETTINGS" in the command template (an env reference, NOT a placeholder)
mahavishnu/core/config.py              # MODIFY: workers.output_compaction settings model
settings/mahavishnu.yaml               # MODIFY: workers.output_compaction block (disabled)
settings/local.yaml                    # MODIFY: operator overrides
mahavishnu/cli/                        # MODIFY: analyze-context + compaction-report commands
scripts/analyze_worker_context.py      # NEW (Phase 1): offline analyzer
tests/unit/workers/test_output_compaction.py       # NEW
tests/integration/test_worker_compaction_e2e.py     # NEW
docs/decisions/2026-11-02-worker-output-compaction-mechanism.md  # NEW (Phase 2)
```

Deliberately **not** touched: `mahavishnu/core/observability.py` (the
otel-metrics plan owns it), `mahavishnu/core/conductor.py`,
`mahavishnu/pools/manager.py`, `mahavishnu/bifrost/`,
`WorkerConfig.env_vars` (§4.9), and — importantly —
**`render_command` in `mahavishnu/workers/shell_backend.py`**, which
must not grow a third placeholder (§4.3.1).

## 7. Validation Matrix

| Tool / command | Expected outcome | Evidence location |
|---|---|---|
| `mahavishnu workers analyze-context --input <sample>` | per-tool byte breakdown + compounded token estimate | stdout; report under `~/.local/state/mahavishnu/worker-context/` |
| `scripts/analyze_worker_context.py --corpus tasks/worker-bench-v1` | tool-output share of billed input tokens | Phase 1 report |
| Spike: `terminal-claude` dispatch with the `--settings` hook | handler fires; command and exit status unchanged | `tests/fixtures/compaction/` |
| Spike: dispatch with `--settings` while the user has `~/.claude/settings.json` | the user's MCP servers, permissions, and hooks still apply — the settings stack is **merged**, not replaced | `tests/fixtures/compaction/` |
| Spike: handler missing / non-zero exit / malformed stdin | original tool result reaches the model, in all three cases | `tests/fixtures/compaction/` |
| `mahavishnu workers compaction-report --corpus tasks/worker-bench-v1` | before/after input tokens, task-success delta, cache-hit-rate delta | Phase 4 report |
| `pytest tests/unit/workers/test_output_compaction.py` | filters preserve every signal they claim to preserve | test run |
| `pytest tests/integration/test_worker_compaction_e2e.py` | a real dispatch with `mode=apply` produces compacted output and a `worker.output_compaction` log line | test run |
| `mahavishnu workers compaction-report` with `mode=off` | byte-for-byte identical to a pre-change baseline | Phase 4 report |
| `crackerjack run -v -f` | 18/18 hooks pass, 0 issues | gate output |

## 8. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| The tool-output share is small, so the mechanism is not worth its complexity | **medium** | Phase 1 exists to find out. A small number is a *successful* outcome of this plan: the mechanism does not get built (§4.12). |
| A filter drops a signal the model needed, and the task fails quietly | medium | Every filter ships with a test asserting it preserves the failure detail it claims to preserve; Phase 4's task-success delta is the backstop; `mode=measure` lets an operator preview before applying. |
| The hook breaks the dispatch | low | Fail-open at three levels (REQ-COMP-03); the handler returns exit 0 on any failure; the kill switch needs no redeploy. |
| The mechanism collides with the concurrent consolidation plan | **medium** | §4.11.1 sequences us after its Phases 3 and 7, and our wiring lands as one change with Phase 7 rather than a second change to the same path. We touch only the command template and the dispatch-time env; we add no envelope, no span, no state transition, and `render_command` gains no placeholder. |
| `--settings` replaces rather than merges the settings stack, so every dispatch silently loses the user's MCP servers, permissions, and hooks | **low, but high blast radius** | Phase 2 task 3 proves it empirically before anything ships: dispatch with `--settings` and confirm the user's own `~/.claude/settings.json` still applies. If the stack is replaced, this plan has no seam and stops. |
| The post-Phase-7 launcher scrubs the session environment, so `$MAHAVISHNU_SETTINGS` never expands | low | Phase 2 task 8 verifies it against the real launcher. If the launcher allowlists the environment, our variable is one line on that allowlist (§4.11.1). |
| An unknown `{settings}` placeholder is silently passed through to the CLI | **low** | We never introduce one: the seam is an env var, and §4.11.1 rule 6 records why, so a later "tidying" does not reintroduce it. |
| Cache hit ratio drops because the compaction changes the prefix | **low** | §4.7: the compacted bytes are what enter the prefix, so the prefix is smaller and stable. Phase 4 measures it anyway, because "low likelihood" is not "verified." |
| A Rust binary (RTK) becomes a per-host deployment dependency | medium | We do not vendor RTK. The mechanism is ours, in Python, in the worker path. |
| The filter catalogue drifts from what our workers actually run | medium | Phase 1's per-tool byte table decides the filter set; filters for tools with no bytes are not built. |
| Compaction makes the model *less* able to verify the work | medium | REQ-COMP-02 and the per-filter preservation tests; Phase 4's success delta is the gate. |

## 9. Decision Rule

This plan is done when **one** of these is true:

1. **The mechanism ships**, `mode=apply` is the default for one worker
   type, and Phase 4's report shows a saving that survives its own
   overhead with a non-negative task-success delta; or
2. **The mechanism is withdrawn**, and the plan records which of the
   three things was true: the tool-output share was too small, the
   task-success delta was negative, or the seam could not be made
   fail-open. Either outcome is a *successful* plan — the deliverable
   is the decision plus its evidence, not the code.

**Cut order**, if scope must be reduced: drop the per-tool filter
catalogue to the top two tools by measured bytes → drop `mode=apply`
and ship `mode=measure` only → drop the compound-turn accounting (but
keep the naive ratio, and say so).

**Do not cut**: the fail-open guarantee (REQ-COMP-03), the
task-success delta (REQ-COMP-05), the Phase 1 measurement, or the
sequencing behind the consolidation plan.

## References

- `docs/plans/2026-11-01-control-plane-consolidation.md` — the
  concurrent plan this one sequences behind (§4.11.1)
- `docs/plans/2026-10-29-bifrost-bodai-cache-wiring.md` — registry
  ordering (§4.11.2)
- `docs/plans/TEMPLATE.md` — the Integration-Contract requirement
  this plan implements
- `docs/decisions/wire-up-contract.md` — the wiring policy
- `docs/plans/2026-11-01-bifrost-cache-eviction-and-threshold.md` —
  the sibling plan that established the measure-before-you-tune method
- `mahavishnu/workers/registry.py` — the worker command templates and
  the `PROMPT_ENV_VAR` / `PROMPT_FILE_ENV_VAR` delivery contract
- `mahavishnu/workers/shell_backend.py` — `render_command`,
  `ShellWorker.start`, `_write_prompt_file`
- `mahavishnu/terminal/manager.py` — `_resolve_worker_env`, the env
  injection path
- `rtk-ai/rtk` — the filter catalogue and the `bytes/4` estimator
  (reference only; not vendored)
- `microsoft/TokenEconomizer` — the cold-start-only prefix-mutation
  rule and the cache-priced cost accounting (§4.7, §4.8)
- `StarTrail-org/LEANN` — the ContextBench harness discipline (§4.8)
- Claude Code docs, "Hooks" and "Settings" — `--settings` precedence
  and the `PostToolUse.updatedToolOutput` contract (§4.3)
