---
role: spec
topic: jot-inbox
status: draft
last_reviewed: 2026-09-09
---

# Jot — zero-turn quick-capture inbox

A taskwarrior-shaped inbox for half-formed thoughts, captured from Claude Code
without spending a conversational turn, stored durably in Dhara, and recalled
by meaning through Session-Buddy.

**Revision note.** This spec was revised after a six-lens review (architecture,
security, Crackerjack compliance, MCP integration, test strategy, human
factors). Findings that changed the design are marked **[R]** inline.

## Problem

There is no place in the Bodai ecosystem to put an unprocessed thought.
`MEMORY.md` holds learnings already processed; Session-Buddy reflections are
memories, not stateful records. The gap is the middle: a thought you want out of
your head right now, with zero ceremony, that you trust will come back later.

**[R]** An earlier draft justified this partly by criticizing
`coord_create_todo`'s mandatory `estimate_hours`. That specific complaint is a
one-line fix, not a subsystem, and has been removed from the justification. The
design is defended on the remaining merits.

## Goals

1. **Capture costs nothing.** No conversational turn, no perceptible latency, no
   context-window consumption.
2. **Capture cannot fail.** No network dependency on the write path.
3. **No organization required at capture time.** Context is gathered ambiently.
4. **Globally readable — once the originating machine has drained. [R]**
   Weakened from "any machine, always." A jot captured on a laptop that is never
   reopened never reaches Dhara. This is now stated rather than implied.
5. **Recall by meaning**, not only exact text.

## Non-goals

- Due dates, priorities, projects, recurrence, dependencies, estimates
- Push notifications of any kind (see Decision 5)
- Autonomous workers acting on jots without review
- Editing jot text (`done` + re-add covers it)

## Decisions

| # | Decision | Status |
|---|---|---|
| 1 | Zero-turn capture via `UserPromptSubmit` exit 2 | **Spike required — see Open Question 1** |
| 2 | Global index with ambient context capture | Locked |
| 3 | Terminal state is `done` | Locked (reaffirmed post-review) |
| 4 | Local-first capture **and** Mahavishnu MCP tools, both in v1 | Locked |
| 5 | Pull-only review, **plus a capture-time echo [R]** | Amended |
| 6 | Session-Buddy semantic recall in v1 | Locked |
| 7 | Dispatch is manual handoff only | Locked |
| 8 | Dhara canonical; Session-Buddy derived **from Dhara [R]** | Amended |
| 9 | **`jot_add` fires only on explicit "jot that" [R]** | New |
| 10 | **Prefix is `,,` [R]** | New |

### Decision 5, amended — pull-only plus capture-time echo

Review evidence: this workflow has twice produced pull-only, zero-friction,
append-shaped stores that rotted — git stashes (four separate memory entries
about cleanup) and `~/.mahavishnu/fallback-queue/`. Write-only death was
assessed at 70–85% within 90 days.

Pull-only is retained. No push surface ships. But the confirmation echo — which
already exists and already reads the log — carries three extra signals:

```
,,pool affinity vs peer routing?

  jotted a3f2 · "pool affinity vs peer rou…" · 3rd time · 17 open · 6 here
```

This is not push. It rides on a capture the user initiated, and self-regulates:
heavy capture produces frequent reminders; no capture produces no inbox to
forget. Duplicate detection uses stdlib `difflib.SequenceMatcher` over the last
~200 local jot texts — under 20 ms, no network, no new dependency.

**The exit criterion is now observable. [R]** The original revisit condition
("if the capture habit forms and the review habit does not") could never fire,
because `jot_sync` reported only write-side metrics. Feed state now includes
`last_review_ts`, `reviews_30d`, and `capture_review_ratio`. Pre-committed
trip-wire: **if `capture_review_ratio` exceeds 10:1 for two consecutive weeks,
Decision 5 is unlocked.**

### Decision 9 — agent capture is explicit-only

`jot_add` fires only when the user says "jot that." It is never inferred from
asides like "we should check that sometime." Rationale: once the list stops
reliably representing the user's own intent, it becomes someone else's
suggestions and stops being read. Same discipline already applied to autonomous
dispatch.

## Architecture

```
  ,,pool affinity vs peer routing?
              │
              ▼
  ┌───────────────────────────────┐
  │  UserPromptSubmit hook        │  stdlib only · no network · no subprocess
  │  gate → context → one write   │  target < 100ms
  │  exit 2 + echo                │  prompt erased, no turn
  └──────────────┬────────────────┘
                 │
                 ▼
  ~/.mahavishnu/jot/log.jsonl          ◄── WRITE PATH ENDS HERE
    append-only · 0600 · never compacted   cannot fail
                 │
                 │  async drain — never on the capture path
                 ▼
            Dhara :8683                     CANONICAL STATE
                 │                          ACID, versioned
                 ▼
         Session-Buddy :8678                DERIVED INDEX  [R]
           indexes FROM Dhara               can only lag Dhara,
                 │                          never lead it
                 ▼
      Mahavishnu MCP tools ──► /jot · /jot relevant · /jot draft
```

### Topology change [R]

The original design fanned out from the log to Dhara **and** Session-Buddy in
parallel, with independent offsets. That allowed Session-Buddy to hold an ID
Dhara did not have — so `/jot search` could return a hit that `/jot show`
reported missing.

Session-Buddy now indexes **from Dhara**, making the pipeline linear. The index
can lag but can never lead, so search may miss something recent and can never
return a phantom. `sb.offset` is deleted entirely.

**Terminology [R]:** this is *not* "single master." The write path is
multi-master — every machine appends to its own log with no coordinator. Dhara
is the **single canonical store for reads**. Conflict resolution is specified
below and is a real concern, not a naming detail.

### Ownership

| Layer | Owns | May fail? |
|---|---|---|
| Local log | Durability of the write | **Never** |
| Dhara | Canonical state for reads | Yes — local buffers |
| Session-Buddy | Search index derived from Dhara | Yes — rebuildable |
| Drain | Replication only | Yes — retries from offset |

### Draining

Three triggers, no daemon: **`SessionStart`**, **`SessionEnd`**, and
**drain-before-read** on every MCP tool call.

**[R]** `SessionStart` was added because staleness was otherwise unbounded — a
machine that captured jots and was never reopened never replicated them.

**Budget chain [R]:** per-hook `timeout: 5` raises the `SessionEnd` budget from
its 1.5 s default to 5 s. The drain's internal hard limit is 2 s, leaving 3 s of
slack. If the internal limit fires, the offset does not advance and the drain
retries at next `SessionStart` or first MCP read. Note that a hook exceeding its
budget is cancelled with its output **discarded silently** — the offset file is
the only durable record of progress.

**Rejected:** spawning a detached drain from the capture hook.
`claude-code-bun-hardened-runtime-stop-hook-enoent` documents `posix_spawn` of
`/bin/sh` failing under Bun's hardened runtime.

**Concurrency [R]:** drains serialize via `drain.lock` with stale-PID detection.
Two triggers can otherwise overlap.

### Degradation ladder

| Down | Lost | Retained |
|---|---|---|
| Session-Buddy | Search by meaning | Everything; index rebuilds from Dhara |
| Dhara | Cross-machine reads; search index freshness | Capture; reads of this machine's log |
| Network entirely | All remote reads | **Capture, fully** |
| Mahavishnu MCP | Tool surface | Capture; local CLI reads |

**No failure prevents capturing a thought.**

## Data model

### Events

```jsonc
{"op":"add","id":"01JQ8F3K2M7XVQNRT9WZ4YB0CD",
 "hlc":{"wall":1757458264881,"ctr":3,"node":"les-mbp"},
 "text":"pool affinity vs peer routing?",
 "ctx":{"repo":"mahavishnu","branch":"feat/settle","sha":"999f69ec",
        "cwd":"…/.claude/worktrees/settle",
        "project_dir":"/Users/les/Projects/mahavishnu",
        "session_id":"4131a1a5…"}}

{"op":"done","id":"01JQ8F3K…","hlc":{…}}
```

Three ops: **`add`**, **`done`**, **`reopen`**. State is a fold; last op per ID
wins. No stored `status` field — a stored status can disagree with the log.

### Ordering: hybrid logical clock [R]

**This replaces wall-clock ordering, which was a correctness bug.** Ops
originate on machines with independent clocks. Under the original design, a
laptop waking with an unsynced clock could `reopen` a jot at an apparent
timestamp earlier than the `done` that preceded it, and the fold would silently
keep it `done`.

Each event carries `(wall, ctr, node)`. Each machine advances `ctr` past the
highest it has observed. Fold orders by `(wall, ctr, node)` lexicographically.
This is a standard HLC and removes the class.

### Two-pass fold [R]

Ops referencing unknown IDs are **parked and re-applied**, not silently dropped.
A `done` that reaches Dhara before its `add` (different machines, different
drain timing) previously vanished. Pass one applies `add`; pass two applies
mutations, including parked ones.

### Identity and handles [R]

The original design conflated *identity* with *handle*, then rejected the handle
on identity's grounds. Taskwarrior has both.

- **Identity:** UUIDv7 via `uuid.uuid7()` (Python 3.14 stdlib — confirm in
  spike). Fallback `time.time_ns()` + `secrets.token_hex()`.
- **Primary handle: display-time ordinals.** `/jot` numbers its output 1..N and
  caches the mapping per `session_id`. You type `/jot done 3`. Batch forms:
  `/jot done 1-4`, `/jot drop 2,5`.
- **Stable handle:** last **6** hex characters, for cross-session and scripted
  use. Any unambiguous substring resolves; ambiguity raises `AmbiguousJotId`.

**Correction:** the earlier draft said 6 characters but every example showed 4.
At 4 chars, lifetime collision probability is ~70% by 400 jots. The quoted
"0.003%" was a per-insertion figure, not the birthday figure a user experiences;
the honest number at 6 chars / 1,000 jots is ~3%.

### Ambient context

From the hook's stdin payload plus `CLAUDE_PROJECT_DIR`. `prompt_id` (≥ v2.1.196)
and `scratchpad_dir` (≥ v2.1.257) read with `.get()` defaults.

**Git metadata is read as files, never subprocesses. [R]** Walk up for `.git`,
read `.git/HEAD`, read the ref. **The `git` subprocess fallback is removed** —
it contradicted the failure matrix (which already said git failure → `null`) and
reintroduced subprocess surface, including `.git/config` `[include]` handling.
On any failure, record `null` and capture anyway.

**Validation [R]:** branch names are validated against a conservative subset of
git's ref rules (`[A-Za-z0-9._/-]+`, no `..` segments, ≤ 1024 bytes) before
storage; control characters are stripped. `cwd` and `project_dir` are
`realpath`-canonicalized and checked absolute.

### The worktree rule

Both `cwd` and `project_dir` are recorded, but `repo` resolves to the
**canonical repository**, not the worktree. Otherwise jots partition across
every worktree ever created.

## Components

| Component | Location | Depends on |
|---|---|---|
| Capture hook | `mahavishnu/hooks/jot_capture.py` **[R]** | **stdlib only** |
| Event codec | `mahavishnu/jot/events.py` | msgspec |
| Fold | `mahavishnu/jot/fold.py` | events |
| Handle resolution | `mahavishnu/jot/short_id.py` | — |
| Context types | `mahavishnu/jot/ctx.py` | msgspec |
| Drain core (pure) | `mahavishnu/jot/drain_core.py` | — |
| Drain sync | `mahavishnu/jot/drain_sync.py` | urllib |
| Drain async | `mahavishnu/jot/drain_async.py` | httpx2 |
| MCP tools | `mahavishnu/mcp/tools/jot_tools.py` | jot core |
| CLI | `mahavishnu jot …` | jot core |

### Hook location and distribution [R]

Three reviewers independently pushed the hook out of `~/.claude/hooks/`:
security (a writable file executing on every prompt), Crackerjack compliance
(invisible to ruff, mypy, pyright, bandit, complexipy, and coverage), and MCP
integration (no upgrade or idempotency story).

The hook lives at `mahavishnu/hooks/jot_capture.py` — inside the package, fully
gated, still stdlib-only — and ships via **Claude Code plugin distribution**
using `${CLAUDE_PLUGIN_ROOT}`, not by programmatically editing
`~/.claude/settings.json`. This matches the project posture that *"settings are
intended to stay local and configuration-driven, not hard-coded,"* and gives
upgrades and multi-machine parity for free.

**Hook conventions [R]:** no logger of any kind (the stdlib-only constraint
forbids `oneiric.logging`, and project convention forbids stdlib `logging` and
`print`). The fail-open contract *is* the error story — logging is itself a
failure mode on this path. No `assert` (bandit B101 applies once the file is in
the package). Documented in the module docstring.

### Drain decomposition [R]

`drain_core` is pure — it plans replication from `(events, offset)` with no I/O.
`drain_sync` (urllib, 2 s socket timeout) serves the `SessionStart`/`SessionEnd`
hooks. `drain_async` (httpx2) serves `jot_sync`. The 2 s budget belongs only to
the sync path; `jot_sync` takes its own timeout parameter, default 30 s.

### Capture surface

```
,,pool affinity vs peer routing?
    →  jotted a3f2 · "pool affinity vs peer rou…" · 3rd time · 17 open · 6 here
```

**Prefix `,,` [R].** Single-comma was rejected: copied JSON, YAML flow
sequences, and argument-list fragments routinely begin with one comma, which is
a normal consequence of selecting the middle of a structure — not an exotic
typo. Two commas eliminate essentially that entire collision class for one extra
keystroke with no shift and no chord.

**Prefix validation [R]:** configurable, but constrained to a non-empty,
non-alphanumeric symbol. An empty prefix would silently swallow every prompt.

### Review surface

```
/jot              5 most recent open jots + vitals line
/jot all          full list
/jot relevant     ranked against the current session's subject matter  [R]
/jot "routing"    semantic search via Session-Buddy
/jot show 3       full text + captured context
/jot done 1-4     terminal state, batch  [R]
/jot draft 3      compose a dispatch prompt for review
```

**Default listing is bounded to 5 [R]** with a vitals header
(`17 open · 6 here · oldest 41d · 3 seen twice`). An unbounded list is a
monument to things undone, and nobody scrolls it. The *log* remains
append-only; only the *view* is horizoned.

**`/jot relevant` replaces `/jot here` [R].** `here` was adverb-shaped in a
verb-shaped namespace, collided with `/jot "here"`, and would barely narrow —
most jots in this workflow will carry `repo: mahavishnu`. Ranking against
current subject matter using Session-Buddy embeddings is pull-shaped, so
Decision 5 is untouched.

### MCP tool group

`jot_add` · `jot_list` · `jot_search` · `jot_show` · `jot_done` · `jot_reopen` ·
`jot_draft` · `jot_sync`

Registered as function names (no `name=` override needed); the full MCP name is
`mcp__mahavishnu__jot_<verb>`, surfacing as `/mahavishnu:jot_<verb>`. This is the
same shape as existing `pool_*` tools and does not hit the Akosha/Dhara naming
gap.

**Registration requires four edits, not one [R].** `PROFILE_REGISTRATIONS` and
`REGISTRATION_MAP` in `profiles.py` are parallel structures; a group present in
the first but absent from the second raises `ValueError` and **crashes the
server at boot** (`mcp_common/tools/dispatch.py`). Required:

1. `profiles.py` — add `"_register_jot_tools"` to `STANDARD_REGISTRATIONS`
   (inherits into `FULL` via the existing `+=`)
2. `profiles.py` — import and add to `REGISTRATION_MAP`
3. `bootstrap.py` — define `_register_jot_tools(server)`
4. `jot_tools.py` — define `register_jot_tools(mcp, …)`

**CI guard:** a test asserting every `PROFILE_REGISTRATIONS` key has a
`REGISTRATION_MAP` entry, modeled on `TestYAMLRoutingSync`. This closes a
documented recurring failure class and is worth more than this feature.

### `jot_draft` — manual handoff

Composes a dispatch prompt and returns it **for review**; it does not route.

**Injection hardening [R]:** jot text is wrapped in an explicit
data-not-instruction block with provenance, and control characters are stripped
(U+0000–U+001F except `\n`, U+200E–U+200F, U+202A–U+202E, U+2066–U+2069) to
defeat bidi and zero-width attacks. Stored text composed into a worker prompt is
an injection sink whether the attacker is external or the user's own past self.

### Drain bookkeeping

```
~/.mahavishnu/jot/log.jsonl      append-only, 0600, never pruned
~/.mahavishnu/jot/dhara.offset   last byte replicated + log inode + log size
~/.mahavishnu/jot/drain.lock     stale-PID detection
```

**Integrity guard [R]:** the offset file records the log's inode and size. On
mismatch — home-directory sync (Dropbox/iCloud/Syncthing), backup restore, or
log rotation — offsets reset to zero and re-drain, which is safe precisely
because replication is idempotent. Without this, a synced log leaves every
stored byte offset pointing into the middle of a foreign line.

## Security

### Permissions [R]

`~/.mahavishnu/jot/` created `0o700`; `log.jsonl` opened with
`O_CREAT|O_WRONLY|O_APPEND, 0o600`. Set explicitly — never inherited from umask.
This is proposed as the canonical mode for any new `~/.mahavishnu/<component>/`
directory.

### Redaction [R]

Users will jot secrets — "check why `MINIMAX_API_KEY` rotation broke pool
routing" is exactly the shape of thought this tool exists to capture. Without
redaction that lands in plaintext on disk, in Dhara, and as a **vector embedding
in Session-Buddy**, where deletion is not reliably reversible.

`session-buddy/session_buddy/ingesters/redaction.py` already provides a
stdlib-only, ReDoS-guarded `redact()` (AKIA, `ghp_`, JWTs, `password=`,
`Authorization:`, RFC1918, `~/.ssh/`) plus an `ALLOWED_METADATA_KEYS` allowlist.
(An earlier draft of this spec wrongly attributed redaction to
`oneiric.actions`; that module is HMAC and signatures only.)

The hook cannot import session-buddy. Defense in depth:

- **Capture time:** a vendored high-confidence subset of the patterns, copied
  into the hook (stdlib-only, so copyable), protecting the local log.
- **Drain time:** the full `redact()` before anything reaches Dhara or
  Session-Buddy.

The echo reports what happened: `jotted a3f2 · redacted:1 (AKIA)`.

### Deletion [R]

Add a **`redact` op** that overwrites the original `add` line **in place, same
length** (space-padded). Byte offsets are preserved, so the append-only
invariant holds — that invariant is about offsets not shifting, not about bytes
being immutable. The drain issues a tombstone to Dhara and a delete-by-ID to
Session-Buddy. Surfaced as `jot_redact`.

## Error handling

### Governing rule

**Never erase text you failed to store.** Swallowing and persisting are one
transaction. If the append fails for any reason, exit `0` and the prompt passes
through untouched.

### The truncate-and-swallow contradiction [R]

The original failure matrix said *"text > 3 KB → truncate, note in
confirmation."* **Truncation is a partial failure to store followed by a full
erase** — a direct violation of the governing rule, and the sole data-loss path
in the design. Five technical reviewers missed it.

Replaced with a **shape gate**: if the text exceeds ~300 characters **or**
contains a newline, capture it *and* `exit 0`, so the prompt still runs. Nothing
is lost in either direction. Over the hard limit: `exit 0`, pass through, do not
capture. **Truncate-and-swallow never happens.**

### Atomicity, corrected [R]

The earlier draft claimed `PIPE_BUF` atomicity for the log. **`PIPE_BUF` is a
guarantee about pipes and FIFOs, not regular files.** What POSIX actually
guarantees for `O_APPEND` on a regular file is that seek-to-end and write occur
with no intervening modification — which prevents overwriting, but does not
promise `write()` will not return short.

Implementation: **one `os.write()` of the complete line including its newline; a
short return is a failure** → fail-open. Partial bytes are then skipped by the
read rule below.

### Partial-line reads [R]

The drain reads **only up to the last complete newline**. The original design
specified neither behavior, and both alternatives lose: advancing past a partial
line drops the event; not advancing blocks forward progress forever.

### Failure matrix

| Failure | Behavior |
|---|---|
| Disk full / log unwritable | `exit 0`, prompt passes through |
| Short `write()` return | Treated as failure → `exit 0` |
| Git detection fails | Capture proceeds, `ctx` fields `null` |
| Text > 300 chars or multi-line | Capture **and** `exit 0` — prompt still runs |
| Concurrent capture, N sessions | No interleaving within a single `write()` |
| Malformed / partial line | Read stops at last complete newline; fold skips, counts |
| Dhara 503 mid-drain | Offset advances only to last confirmed event |
| Dhara hangs | 2 s hard timeout; offset unchanged; retry next trigger |
| Session-Buddy down | Index lags Dhara; search degrades, never phantoms |
| `done` on two machines | Idempotent by construction |
| Orphan `done`/`reopen` | Parked, re-applied in fold pass two |
| Clock skew | **Resolved by HLC** |
| Log inode/size mismatch | Reset offsets, re-drain (idempotent) |
| Short-ID ambiguity | `AmbiguousJotId` listing candidates |

### Stated invariants

1. **Byte offsets must never shift.** Appends and same-length in-place redaction
   are permitted; compaction and rotation are forbidden.
2. **The capture path performs no network I/O and spawns no subprocess.**
3. **Session-Buddy holds no authoritative state.**
4. **One `serialize_event()` definition [R]** — the hook vendors a copy, with a
   test asserting byte-identical output against the package version.

## Health and observability

**[R] `jot_sync` returning feed state does not, by itself, satisfy
`mcp-backend-wiring-discipline.md`.** That policy requires `/health` to
aggregate per-feed state and return 503 when degraded.
`bootstrap.py` `health_check()` currently returns `{"status": "ok"}`
**unconditionally** — the exact `mcp-surface-health-illusion` pattern the policy
exists to prevent. A stalled drain would report healthy to K8s, Grafana, and the
monthly radar.

`jot_tools.py` installs a feed-state provider that `health_check()` aggregates:
`entities_count`, `last_updated_timestamp`, `errors_total`, `cycles_total`, plus
the Decision 5 read-side metrics (`last_review_ts`, `reviews_30d`,
`capture_review_ratio`).

**Scope note:** extending `/health` aggregation is arguably beyond "add a jot
inbox" and is tracked as a separable deliverable. If cut, the wiring-discipline
claim must be removed from this spec rather than left unbacked.

## Testing strategy

Markers: `unit`, `integration`, `property`, `slow`. Coverage gate 89%.

### Fail-open — one test per failure-matrix row

`tests/unit/jot/test_capture_failopen.py`, each asserting `exit 0`, no block
JSON on stdout, and the confirmation on stderr:

`unwritable_dir` · `disk_full_mid_write` (patch `os.write` → ENOSPC) ·
`missing_parent_dir` · `eintr_retried` · `eintr_exhausted` ·
`oversized_passes_through` · `multiline_passes_through` · `stdin_eof` ·
`stdin_closed_epipe` · `no_python3_on_path` · `polluted_pythonpath` ·
`embedded_newline_does_not_split_line`

Env-stripping pattern: `tests/unit/test_pi_pool_env_stripping.py:89`.

### Concurrency

`tests/integration/test_jot_concurrent_append.py` — 32 processes × 100 rounds,
gated by `multiprocessing.Barrier`. Your own
`test_worktree_session_registry_concurrent.py:54` documents that without the
barrier the race surfaces in only ~33% of runs.

**[R] Runs on macOS.** A reviewer proposed `skipif(darwin)` on APFS portability
grounds. Rejected: macOS is the primary development machine, and if concurrent
append misbehaves there, that is a **design finding requiring a lock**, not a
test-portability footnote. Marked `slow`, never `flaky`.

### Property tests

`test_fold_respects_causal_order_under_clock_skew` — **[R] this property was
inverted in review.** One reviewer proposed asserting wall-clock last-write-wins;
the architecture reviewer identified that behavior as the bug. Generate events
with deliberately skewed `wall` values and assert HLC ordering wins.

Also: `done` idempotent · `reopen` inverts `done` · orphan ops parked and
re-applied · malformed lines never reduce recovered valid jots ·
`offset_monotonic_never_decreases` · `drain_redelivery_idempotent` ·
short-ID resolution total.

xdist-safe async helper: `tests/property/test_properties.py:25`.

### Hook testing

`importlib.util.spec_from_file_location`, per
`tests/unit/test_worktree_session_isolation_hook.py:55`. Includes an AST walk
asserting the hook imports nothing outside the stdlib allowlist. Plugin
registration validated per `tests/unit/test_claude_settings_hooks_format.py:103`
— the test that catches "install ran but the hook never fires."

### Drain

Stub Dhara with the existing `MockDharaRegistry`
(`tests/fixtures/adapter_mocks.py:498`). **A `MockSessionBuddy` analog does not
exist and is part of this work** (~50 lines, same file).

`partial_batch_failure_advances_to_last_confirmed` ·
`hang_returns_within_2p5s` (`@pytest.mark.timeout(5)`) ·
`resume_from_corrupted_offset_advances_to_next_newline` ·
`concurrent_invocation_serializes_via_lock` ·
`inode_mismatch_resets_offsets`

### Integration (wiring discipline)

`tests/integration/test_jot_tools_e2e.py` — capture, drain, and assert every
registered `jot_*` tool returns non-empty results and `jot_sync` reports the
four required feed signals.

## Open questions — resolve before implementation

1. **Hook block contract.** Two independent agents returned incompatible
   answers. One: `permissionDecision: "deny"` + `permissionDecisionReason`.
   The other: those are `PreToolUse`-only, and `UserPromptSubmit` uses
   `decision: "block"`. `exit 2` blocks either way, so only the user-visible
   string is at risk. **Blocking spike:** register a throwaway `jq -c .` hook,
   run `claude --debug`, and settle it empirically. Also confirm the exact stdin
   payload and that `uuid.uuid7()` exists in the runtime Python.
2. **Dhara idempotency mechanism.** Replay safety is asserted but ungrounded.
   Determine whether Dhara upserts by ID or appends, and specify it.
3. **Drain p99 latency.** If it exceeds 2 s under healthy Dhara, split into two
   hooks with separate timeouts.
4. **`/health` aggregation scope.** In or out of this deliverable.

## Future work

- **Transcript context** — store `transcript_path` + `prompt_id` and render
  surrounding lines in `/jot show`. **[R] Reviewed as the cheapest high-value
  feature in the review** and deliberately deferred by the user; it is the first
  thing to reach for if "what did I mean?" becomes the dominant review failure.
- **`drop` verb and `cold` view** — considered and deferred; `done` remains the
  sole terminal state per Decision 3.
- **`/jot ask`** — inject a jot as a prompt in the current session.
- **Push surfaces** — unlocked automatically if `capture_review_ratio` exceeds
  10:1 for two consecutive weeks.
- **Autonomous dispatch** — revisit after ~50 real jots exist.
- **Cross-machine sync via a shared store** — the current design already
  achieves this through Dhara; this entry covers conflict-resolution hardening
  beyond HLC if genuine concurrent editing emerges.
