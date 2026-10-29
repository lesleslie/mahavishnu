---
status: shipped
role: implementation
date: 2026-10-29
last_reviewed: 2026-10-29
owner: les
topic: demo-surface
scope: mahavishnu-demo-cli
purpose: sweep every `mahavishnu demo <name>` subcommand against live substrates, fix the defects that surfaced, and add `mahavishnu demo all` so the sweep is repeatable
superseded_by: null
blocks_on: []
title: "Demo Surface Sweep"
---

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
answered `could not auto resolve a provider for the request`.

The deeper problem: `PydanticAIAdapter` builds its agent as
`Agent(model="openai:<name>")`, and pydantic-ai resolves the endpoint
and credential from the **environment** — the adapter's own
`ModelConfig.base_url` / `.api_key` are decorative. So the demo, not
the adapter, is the only place where the provider, its endpoint, and
its credential can be made to agree. The demo now sets both from the
provider it selected.

The provider order also changed to **cloud first, local last**
(`minimax → anthropic → openai → llama_server`), matching the
project's MiniMax-first posture and the Agno adapter's chain. The
local `llama_server` is a CPU-only 8B model here, so a paragraph of
prose from it takes *minutes* — long enough that the demo's own budget
expired first (900 s and still running). With MiniMax the same demo
answers in **3.8 s**.

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
| `workflow-pool-worker-terminal` | 60s | 180s | the worker leg runs a real command in the Shepherd jail |
| `workflow-multi-pool-handoff` | 30s | 180s | both legs *completed* inside 30 s and the demo still timed out before printing its result |
| `workflow-adapter-swap` | 90s | 240s | two pool start/stop cycles |
| `workflow-pi-cascade` | 60s | 180s | two full pi-coding-agent invocations |

### The Session-Buddy probe was intermittently failing

The reachability probe is a GET with `Accept: text/event-stream`. The
MCP handshake is not always fast: measured on this host, **3 of 4
probes exceeded the 5 s budget** while the server was plainly up, and
the fourth answered in 2.8 s. Both Session-Buddy demos therefore
reported "not reachable" *intermittently* — a flaky precondition that
looks exactly like a missing server. The probe also reused the
*RunPod* 5 s constant; it now has its own 15 s budget
(`DEFAULT_SESSION_BUDDY_PROBE_TIMEOUT_S`).

## Security hardening

The commit's automated security review flagged three issues in the
changes above. All three were real and are fixed.

### `search_code` could read arbitrary files

`_search_code_impl` had **no** path validation at all, so an agent
could name any directory on the host and read it. An intermediate
attempt to also accept a *file* path made that worse (it added
non-Python files to the reachable set) and broke the tool's pinned
contract — `tests/unit/engines/test_agno_tools.py::test_search_code_not_directory`
asserts that a file path raises `AgnoError`.

The resolution keeps the contract and closes the hole: the tool runs
the same `_validate_path` guard the file tools use (raw-traversal
detection, symlink-resolving normalization, an allowed-base-directory
check, the blocked sensitive-directory list), and still rejects a file
path — but the message now names the directory to use
(`Not a directory: …/health.py. Pass the containing directory (…) instead.`)
so an agent recovers on its next turn instead of aborting.

`/etc/passwd` is now refused with
`Access denied: path is outside allowed directories`.

### The persisted vector store is shared across repositories

The vector store is a *single* index — every repo ingested into it
lands in the same collection — so a similarity search returns the
globally closest chunks regardless of which repo was asked for. On the
sweep host the persisted index turned out to hold a different repo's
content outright (`www-mcp-servers`), so a query for mahavishnu would
have answered with another project's code.

Retrieval is now scoped to the requested repository by each chunk's
`file_path` metadata, applied as a **node postprocessor** — i.e.
between retrieval and the response synthesizer. That placement is the
point: filtering the synthesizer's *output* afterwards still lets the
other repository's content shape the answer text, because the
synthesizer had already read it.

Verified against the live store: raw retrieval returned 5 nodes, all
from `www-mcp-servers`, and the scope filter reduced them to 0.

LlamaIndex's metadata filters have no prefix operator and the chunks
record an absolute file path rather than a repo id, so the scope is
expressed as a postprocessor over `file_path`. The failure mode is the
safe one — too few results, never results from the wrong repo. This
also closes the same gap on the pre-existing ingest-then-query path.

The query engine is built directly (`index.as_retriever(...)` plus
`RetrieverQueryEngine.from_args(...)`) rather than through
`index.as_query_engine(...)`, because the latter forwards its kwargs
to the retriever as well, so a `node_postprocessors` argument never
reaches the engine. The postprocessor is deliberately duck-typed rather
than a `BaseNodePostprocessor` subclass: the engine only calls
`postprocess_nodes` on each entry, and a plain class keeps the module
free of an import that resolves to a mock under the test suite's
`sys.modules` patching.

### Sweep logs were written without permission or symlink protection

The sweep wrote logs into a shared temp directory with default
permissions, and a symlink pre-planted at the log path could redirect
the write. The default log directory is now created with
`tempfile.mkdtemp` (mode 0700).

Each log is written to a freshly created `O_EXCL` temp file in the
same directory (`mkstemp` creates with mode 0600, so it can never be
a pre-existing file or a symlink) and then moved onto the destination
with `os.replace`. Rename semantics *replace* a symlink at the
destination rather than following it, and the move is atomic, so no
reader ever sees a half-written log. Permissions are applied to the
open descriptor with `fchmod` rather than to the path afterwards — a
path-based `chmod` would follow a symlink and leaves a window between
the write and the permission change. Verified: a symlink at the log
path is replaced by a regular file, its target is left untouched, and
the resulting file is mode 0600.

## Still open

- **`hatchet`** — needs a Hatchet server. `hatchet server start` pulls
  Docker images; the `hatchet-sdk` embedded sidecar downloads a native
  binary, which is a separate approval. The adapter's API drift is
  fixed, and the demo now reports the missing server as a
  *precondition* (`Hatchet server is not reachable at localhost:7077
  (Connection refused). Start one with 'hatchet server start'.`)
  rather than a connection error that reads like an adapter defect.
- **`pool-runpod` / `pool-runpod-public`** — need a paid RunPod
  account and endpoint ids. Both fail cleanly at the precondition.
- **`agno`** — the adapter's 300s budget expires because the agent
  explores a large repo (including blocked directories, which the tool
  correctly refuses). The demo now reports the adapter's own
  `MHV-008` rather than a generic timeout. The knob is
  `agno.default_timeout_seconds` (`MAHAVISHNU_AGNO__DEFAULT_TIMEOUT_SECONDS`),
  but raising it only buys time — the agent's exploration is what does
  not converge, and that is an Agno-side concern (the adapter and its
  provider chain are under active development in a concurrent session).
- **`llamaindex`** — now passes. The query finds the persisted index
  (`index_id: mahavishnu_0`) and the repo scope correctly filters out
  the other repository's chunks, so the synthesizer has no context to
  work with: the demo completes in **50 s** (it used to overrun the
  1200 s ceiling) and reports `success_count: 1`, `answer: "Empty
  Response"`, `sources: []`. That is the honest answer — the persisted
  index on this host holds *another* repo's content, so there is
  nothing in it for mahavishnu. Build the right index with
  `--task-type ingest_and_query` (slow: the local CPU-only embedder
  takes minutes per batch). Note that the demo's timeout uses
  `asyncio.wait_for`, which cannot interrupt the blocking
  `llama_server` call, so an overrunning demo reports late rather than
  being cut short.

## Final verdict matrix

`mahavishnu demo all` over the 16 demos that do not need paid
credentials (the two RunPod demos are excluded — they need a billed
account and endpoint ids):

```
  tmux                           PASS          exit=0      13.8s
  mock                           STUB          exit=0       6.3s
  prefect                        PASS          exit=0      47.3s
  agno                           ERROR         exit=0     309.3s
  llamaindex                     PASS          exit=0      20.5s
  pydantic_ai                    PASS          exit=0       9.6s
  crow                           PASS          exit=0       7.0s
  hatchet                        PRECONDITION  exit=1       8.5s
  pool-mahavishnu                PASS          exit=0      22.0s
  pool-session-buddy             PASS          exit=0      12.7s
  pool-pi                        PASS          exit=0      16.7s
  workflow-pool-worker-terminal  PASS          exit=0      19.3s
  workflow-multi-pool-handoff    PASS          exit=0      20.0s
  workflow-adapter-swap          PASS          exit=0      26.4s
  workflow-pi-cascade            PASS          exit=0      34.3s
  workflow-pi-then-local         PASS          exit=0      33.3s
```

**14/16 passed.** The two that do not are the ones that *should* not:

- `hatchet` → `PRECONDITION` (no Hatchet server; no Docker images here).
- `agno` → `ERROR`, the adapter's own `MHV-008` at its 300 s budget.

Two rows are worth calling out because they got *faster* while getting
correct: `llamaindex` went from a 1200 s ceiling to **20.5 s** (the
repository scope removes the other repository's chunks, so the
synthesizer has no context to chew on), and `pool-pi` /
`workflow-pi-cascade` went from `ERROR` to **16.7 s / 34.3 s** once
their pi task got PiPool's 120 s budget instead of its 30 s default.

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
