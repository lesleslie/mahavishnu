# Demo surface sweep — 2026-10-29

Swept every `mahavishnu demo <name>` subcommand (18 of them) against
live substrates, fixed the defects that surfaced, and added
`mahavishnu demo all` to make the sweep repeatable.

## Prerequisites used

| Substrate | Where | Started how |
|---|---|---|
| Bifrost gateway | `:8471` | already running under launchd |
| Prefect API | `:4200` | `prefect server start` |
| Prefect work pool | `default` | `prefect work-pool create --type process default` |
| Prefect worker | `default` | `prefect worker start --pool default` |
| crow-mcp (HTTP) | `:8693` | `crow-mcp --transport streamable-http --host 127.0.0.1 --port 8693` |
| Session-Buddy | `:8678` | already running |
| llama-server | `:8081` | already running (CPU-only) |
| OpenSearch | `:9200` | already running |

Not available: a Hatchet server (the official `hatchet server start`
pulls Docker images, which this environment does not use).

## Defects found and fixed

### 1. Every engine demo resolved the wrong repo (`demo_cli.py`)

`Path(__file__).resolve().parents[3]` is the *projects* root, not the
repo root — `parents[2]` is the repo. All five engine demos
(`prefect`, `agno`, `llamaindex`, `pydantic_ai`, `hatchet`) therefore
operated on `/Users/les/Projects`. LlamaIndex surfaced it as
`MHV-009 No index found for repository: /Users/les/Projects` while
still reporting a top-level `status: "completed"` — a false success.
Replaced with a shared `_default_demo_repos()` helper.

### 2. Four workflow demos sent the wrong payload to the MahavishnuPool

`MahavishnuPool` runs the Shepherd backend, whose `execute()` accepts
exactly one of `task_ref` or `command`
(`mahavishnu/workers/shepherd_backend.py`). The demos dispatched
`{"prompt": ...}`, which raised
`ValueError: Task must specify 'task_ref' or 'command'` before the
task reached the substrate. Added `_task_payload(pool_type, command)`:
`command` for `mahavishnu`, `prompt` for the prompt-shaped pools
(`session-buddy`, `pi`).

Affected: `workflow-pool-worker-terminal`,
`workflow-multi-pool-handoff` (target pool),
`workflow-adapter-swap`, `workflow-pi-then-local` (local pool).

### 3. Prefect: the deployment entrypoint selected the wrong loader

`Flow.afrom_source` branches on the presence of a colon:

```python
if ":" in entrypoint:
    full_entrypoint = str(storage.destination / entrypoint)
```

Every dotted-module entrypoint contains the `module:func` colon, so
Prefect prepended the storage destination to the dotted module name and
the worker tried to import `<clone>/mahavishnu.engines.prefect_adapter_impl`
— `ModuleNotFoundError`. The colon also selects
`EntrypointType.FILE_PATH`, which loads the file *outside* its package
and breaks relative imports
(`attempted relative import beyond top-level package`).

Fixed by passing a colon-free module-path entrypoint
(`pkg.module.func`), which selects the package-import path end to end.

### 4. Prefect: the precondition and the client used different servers

The precondition probed `settings.prefect.api_url` (`:4200`) but
Prefect's client resolves its own `PREFECT_API_URL`; unset, it starts
an **ephemeral** server on a random port, where the run sat SCHEDULED
because no worker watches that instance's pool. Worse,
`PREFECT_API_URL` is a *cached* settings object, so setting the env var
after `prefect` is imported has no effect — `temporary_settings` is
required. Both sides now use `_effective_prefect_api_url()`.

### 5. Prefect: `state.result()` returns a coroutine in async context

`State.result` is `@async_dispatch(aresult)`, so the sync call left an
un-awaited coroutine and `len(results)` raised
`TypeError: object of type 'coroutine' has no len()`. Switched to
`await state.aresult(raise_on_failure=False)`.

### 6. Prefect: a missing worker produced a silent timeout

A work pool with no worker polling it accepts the deployment and never
picks the run up. Added a precondition that reads the pool's `status`
(`READY` only while a worker polls) and names the fix.

### 7. pydantic_ai: the provider and its endpoint disagreed

The demo detected `llama_server` and took the model id from that
server's `/v1/models`, but applied `OPENAI_BASE_URL` with
`setdefault` semantics — so a pre-existing value (here: the Bifrost
gateway) won. The gateway then received a llama_server model id and
answered `could not auto resolve a provider for the request`. The
demo now sets the endpoint it derived from the selected provider, and
leaves an operator-exported API key alone.

### 8. Hatchet adapter: `hatchet-sdk` 1.43 removed `Hatchet.run`/`close`

The adapter called `client.run(...)` and `client.close()`, both gone in
1.43 — `AttributeError: 'Hatchet' object has no attribute 'run'`. The
adapter now prefers `client.runs.aio_create(...)` (1.43+) and falls
back to `client.run(...)` for older SDKs, and only closes the client
when the installed SDK exposes a closer.

### 9. LlamaIndex: a standalone query could never find its index

The query path looked the index up in `self.indices`, a map populated
only by an ingest **in the same process**. A query against an index
built earlier failed with `MHV-009` even though the persisted vector
store was right there (the adapter had already read its embedding
dimension from it during `initialize()`). The adapter now reopens the
configured store when the in-memory lookup misses.

### 10. Agno `search_code` rejected a file path

An agent routinely hands the tool a file it just read instead of the
repository root; the call failed with
`MHV-453 Not a directory: ...`. The tool now searches that file.

### 11. The pi demos wrote into the operator's checkout

`pi-coding-agent` is a *coding* agent and inherits the parent's working
directory, so a demo spawned from the repo root let it drop files
straight into the checkout — this sweep left `examples/hello_world.py`
and `tests/unit/test_hello_world.py` behind. The pi demos now run the
agent in a scratch directory under
`~/.local/state/mahavishnu/worktrees/<pool>/pi-workspace`.

### 12. Timeouts that could not cover the work

| Demo | Was | Now | Why |
|---|---|---|---|
| `agno` | 120s | 420s | shorter than the adapter's own 300s budget, so the demo could never surface the adapter's `MHV-008` |
| `llamaindex` | 120s | 900s | a `query` embeds, retrieves, and *synthesizes* — minutes on a CPU-only host |
| `workflow-pi-then-local` | 90s | 240s | the pi task now gets 120s (`PiPool` defaults to 30s, too short for a code-writing prompt) |

## Still open

- **`hatchet`** — needs a Hatchet server. `hatchet server start` pulls
  Docker images; the `hatchet-sdk` embedded sidecar downloads a native
  binary, which is a separate approval. The adapter's API drift is
  fixed, but the demo cannot be exercised without a server.
- **`pool-runpod` / `pool-runpod-public`** — need a paid RunPod
  account and endpoint ids. Both fail cleanly at the precondition.
- **`agno`** — the adapter's 300s budget expires because the agent
  explores a large repo (including blocked directories, which the tool
  correctly refuses). The demo now reports the adapter's own
  `MHV-008` rather than a generic timeout. Converging the agent's
  exploration is an Agno-side concern.
- **`llamaindex`** — works, but on a CPU-only host the synthesis
  exceeds the demo's budget. Note that the demo's timeout uses
  `asyncio.wait_for`, which cannot interrupt the blocking
  `llama_server` call, so the run overruns its budget rather than
  being cut short.

## `mahavishnu demo all`

A new sweep command runs every demo in its own subprocess and reports a
verdict matrix, distinguishing *missing substrate* from *broken demo*:

| Verdict | Meaning |
|---|---|
| `PASS` | reached the success path |
| `STUB` | documented stub |
| `PRECONDITION` | substrate missing — start the server / enable the flag / export the credential |
| `TIMEOUT` | the demo's own budget expired |
| `ERROR` | the demo is broken (traceback, failed status, or all-repos-failed) |
| `PARTIAL` | some repos succeeded, some failed |

```
mahavishnu demo all
mahavishnu demo all --only prefect --only llamaindex --skip pool-runpod
mahavishnu demo all --timeout 300 --json
```

Two classification traps are handled explicitly, because both produced
false verdicts during this sweep:

- Rich's traceback renderer prints the **source** of the timeout
  branch (`typer.echo(f"Timed out after {timeout}s ...`) inside the
  panel, so a substring match for `Timed out after` labelled a crash as
  a timeout. The match is line-anchored.
- The engine adapters report a top-level `status: "completed"` even
  when every repo failed, and the workflow demos report per-stage
  statuses in nested dicts with no top-level status at all. The
  classifier walks nested statuses and reads the per-repo counters.

## Integration contract

- **Triggered from** — `mahavishnu demo all`, and the CLI reference.
- **Returns to** — the terminal: a verdict matrix, exit code `0` when
  every demo passed or was a stub, `1` otherwise.
- **Demonstrable by** — `mahavishnu demo all --json`, and
  `tests/unit/cli/test_demo_sweep.py`.
- **Rollback signal** — the sweep reports `ERROR` for a demo that
  previously passed.
- **Observability added** — per-demo logs under `--log-dir`, with the
  verdict recorded per demo.
