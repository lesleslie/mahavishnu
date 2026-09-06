---
status: draft
role: implementation
date: 2026-09-06
last_reviewed: 2026-09-06
superseded_by: null
blocks_on:
  - docs/plans/TEMPLATE.md
topic: mcp-stub-activation
---

# MCP Stub Activation — archive-org-mcp, medium-mcp, scapy-mcp

**Scope:** Turn three PyPI name-reservation scaffolds into working MCP servers, and
repair the repository registry that makes "registered" mean something.

______________________________________________________________________

## 1. Context

Three repositories in `~/Projects` are name-reservation scaffolds created 2026-08-31.
Each contains `.gitignore`, `LICENSE`, `pyproject.toml`, `README.md`, a built `dist/`,
and three near-empty files under `src/`. All three status tables read
`Spec / plan: not written` and `Implementation: not started`.

| Repo | Package | Purpose |
|---|---|---|
| `archive-org-mcp` | `archive_org_mcp` | Internet Archive — Wayback snapshots, catalog search |
| `medium-mcp` | `medium_mcp` | Medium publishing platform — posts, users, publications, tags |
| `scapy-mcp` | `scapy_mcp` | Scapy — packet crafting, dissection, capture, PCAP I/O |

All three `pyproject.toml` files already declare the intended stack: `fastmcp>=2.12.0`,
`httpx2>=0.28.1`, `mcp-common>=0.18.0`, `oneiric>=0.16.0`, `pydantic>=2.5.0`,
`pydantic-settings>=2.1.0`, Python `>=3.14`, BSD-3-Clause. Each README names
`raindropio-mcp` as the reference architecture.

### Why a shared spec

The three servers share roughly 70% of their architecture: oneiric layered config,
`mcp-common` bootstrap and health, tool-profile gating, an async HTTP client with
retry/backoff, pydantic models, and the crackerjack quality gates. Writing that three
times guarantees drift. This spec owns the shared architecture; each plan owns its
service-specific deltas.

______________________________________________________________________

## 2. Goals

1. Each of the three repos exposes working MCP tools that return real upstream data,
   verified by integration tests asserting non-empty results.
1. Canonical `mahavishnu/settings/ecosystem.yaml` becomes the true single source of
   truth for the repository manifest, with all 35 repositories registered (the 32
   currently in `repos.yaml`, which already subsume the canonical 8, plus the 3 new
   servers).
1. Registry drift fails CI instead of going silent.
1. `medium-mcp`'s README capability list is corrected to match a real upstream API.
1. `scapy-mcp` cannot transmit packets unless three independent controls are all
   satisfied.
1. All three repos build wheels that actually contain their package (finding 4.6).

## 3. Non-Goals

1. **Save Page Now / Internet Archive uploads.** Read-only v1 for `archive-org-mcp`.
1. **Medium write operations.** The official API is retired and no legacy integration
   token exists. No publish path in v1.
1. **flowscape integration.** The flowscape spec lists `scapy-mcp` enrichment as v2+;
   this spec does not deliver it.
1. **TLS SNI extraction, MAC/OUI bundling, protocol-classification heuristics.** Those
   belong to flowscape, not to `scapy-mcp`.
1. **Retiring `bodai/config/ecosystem.yaml`.** It has a different schema and different
   consumers. This spec fixes its bugs; it does not merge it with Mahavishnu's.
1. **Registering non-project directories.** `ARCHIVED/`, `BACKUP/`, `SCRATCH/`,
   `sites/` stay unregistered.

______________________________________________________________________

## 4. Verified Findings

These were established by direct verification during design, not inferred. They are
recorded here because two of them invalidate the scaffolds' stated assumptions.

### 4.1 Medium's official API is retired and unusable

Medium's Help Center: *"Medium will not be issuing any new integration tokens for our
API and will not allow any new integrations. All existing tokens will continue to
work."* The integration-token setting was removed from user settings around
February 2025. n8n's documentation (June 2026) confirms new integrations cannot be
configured. mediumapi.com independently corroborates: the official API was *"archived 2
March 2023"* and *"you cannot extract anything using it."*

No `MEDIUM_*` credential exists in the current environment, the shell rc files, or
`mahavishnu/.mcp.json`. The grandfathered path is therefore unavailable.

Even with a token, the complete official surface was seven endpoints — `GET /v1/me`,
`GET /v1/users/{userId}/publications`,
`GET /v1/publications/{publicationId}/contributors`,
`POST /v1/users/{authorId}/posts`, `POST /v1/publications/{publicationId}/posts`,
`POST /v1/images`, `POST /v1/tokens` — with **no read or search capability** for
arbitrary articles.

### 4.2 The medium2 unofficial API does provide the needed surface

[mediumapi.com](https://mediumapi.com/) ("medium2", author Nishu Jain), wrapped by the
`medium-api` PyPI package, covers all four capability groups the `medium-mcp` README
promises:

| README bullet | medium2 coverage |
|---|---|
| Posts — fetch, list, search author articles | `User.articles`, `Article.content/markdown/html`, `Search.articles` |
| Publications — query stories | `Publication.articles`, `.newsletter` |
| Users — profile, follower counts, metadata | `User.followers`, `.following`, `.info`, `.interests`, `.top_articles` |
| Tags — topic discovery | `related_tags`, `tag_info`, `root_tags`, `TopFeeds`, `LatestPosts` |

Access is via RapidAPI. Base URL `https://medium2.p.rapidapi.com`, auth header
`X-RapidAPI-Key`.

| Tier | Cost | Calls/month | Overage |
|---|---|---|---|
| Basic | $0 | **150** | hard limit |
| Pro | $10/mo | 2,500 | $0.004/call |
| Ultra | $30/mo | 25,000 | $0.004/call |
| Mega | $150/mo | 1,000,000 | $0.04/call |

Per-second rate limits are not documented; only monthly caps.

mediumapi.com imposes a content restriction: *"We strictly prohibit our users from
fetching copyrighted content from Medium without the explicit permission from the
author."*

### 4.3 A cautionary precedent: `Dishant27/medium-mcp-server`

This public MCP server is non-functional, and the failure mode is the one our wiring
discipline exists to catch.

`src/auth.ts` reads `MEDIUM_CLIENT_ID` / `MEDIUM_CLIENT_SECRET`, then returns a
fabricated token:

```ts
return `medium_token_${Date.now()}`;
```

Its own comments concede *"This is a placeholder for actual Medium OAuth flow."* The
file makes zero network calls and never contacts `/v1/tokens`.

`src/client.ts` targets the correct base (`https://api.medium.com/v1`) but five of six
endpoints do not exist: `POST /publications`, `GET /publications` (missing required
path parameter), `GET /articles`, `GET /drafts`, `POST /drafts`. Only `GET /me` is
real.

It registers six tools, exposes a schema, and would satisfy any test that mocks the
HTTP layer — while being incapable of returning a single real row. **This is why every
plan derived from this spec opens with a mandatory Phase 0 that makes one real upstream
call and asserts non-empty data before any tool is registered.**

### 4.4 archive.org is fully available for reads

The CDX Server API (`http://web.archive.org/cdx/search/cdx`), Availability API
(`https://archive.org/wayback/available`), Advanced Search
(`https://archive.org/advancedsearch.php`), and Metadata API
(`https://archive.org/metadata/{identifier}`) are live, documented, and require no
authentication for reads.

Internet Archive states: *"Please be respectful and use this free public resource.
While we do not have hard rate limits..."* Politeness is therefore a design
requirement rather than an enforced constraint — the server must self-limit.

### 4.5 The repository registry has a four-month silent drift

Four registry files exist. The one most obviously named is the one the runtime ignores.

| File | Read by | Entries | Status |
|---|---|---|---|
| `mahavishnu/settings/ecosystem.yaml` | `load_repos()` via `repos_path` (`settings/mahavishnu.yaml:18`, `core/config.py:2181`) | **8 repos** + 15 roles | **canonical** |
| `mahavishnu/settings/repos.yaml` | `_resolve_repos_path()` fallback, only when ecosystem.yaml is absent | **32 repos** | legacy |
| `bodai/config/ecosystem.yaml` | `bodai/core/config.py:15` | 23 components | separate schema |
| `bodai/config/portmap.yaml` | `bodai/core/config.py:28` | port allocations | separate |

Counts verified by YAML parse, not by grep — `ecosystem.yaml` uses `- name:` for both
repos and roles, so a naive line count reports 23 and overstates the repo count.

`mahavishnu/core/config_validator.py:9` states: *"Note: repos.yaml is legacy. Use
ecosystem.yaml as the single source of truth."*

Canonical `ecosystem.yaml` contains 8 repos: `mahavishnu`, `crackerjack`,
`session-buddy`, `oneiric`, `mcp-common`, `mdinject`, `akosha`, `dhara`. It is stamped
`last_updated: '2026-05-11'`.

**Consequence: 24 repositories are invisible to Mahavishnu at runtime** — every MCP
integration server (`raindropio`, `unifi`, `mailgun`, `graphics`, `css`, `langsmith`,
`neo4j`, `spline`, `penpot-api`, `opera-cloud`, `excalidraw`, `porkbun-dns`,
`porkbun-domain`, `synxis-crs`, `synxis-pms`, `www-mcp-servers`), plus `fastblocks`,
`fastblocks-ui`, `splashstand`, the four jinja2/starlette libraries, and `bodai`
itself. `list_repos`, role-based routing, `find-capability`, and tag sweeps all resolve
against 8 repos.

The fallback never fires, because `ecosystem.yaml` exists. Nothing is broken loudly.

Additional defects found:

- `bodai/config/ecosystem.yaml` declares `druva` at port 8683; `~/Projects/druva` does
  not exist (renamed to `dhara`).
- `bodai/config/ecosystem.yaml` declares `n8n-mcp` at port 3044; `~/Projects/n8n-mcp`
  does not exist.
- `spline-mcp` claims port 3050, but `portmap.yaml` reserves 3050-3059 as "future
  expansion" and never allocates 3050.
- Port 3044 appears in `ecosystem.yaml` but is absent from `portmap.yaml` allocations.
- Never registered in any manifest: `flowscape`, `bodai-plugins`, `peanutbutterpub`,
  `mdinject-pypi-placeholder`.

### 4.6 All three scaffolds build empty wheels

Each `pyproject.toml` declares:

```toml
[tool.hatch.build.targets.wheel]
packages = ["medium_mcp"]          # and archive_org_mcp, scapy_mcp
```

But the code lives at `src/<package>/`, not `./<package>/`. Hatchling resolves
`packages = ["medium_mcp"]` against the project root, finds nothing, and — critically —
**does not error**. It emits a metadata-only wheel.

Verified against the committed artifacts. All three `dist/*.whl` files contain five
files and zero Python modules:

```
medium_mcp-0.1.0.dist-info/METADATA
medium_mcp-0.1.0.dist-info/WHEEL
medium_mcp-0.1.0.dist-info/entry_points.txt
medium_mcp-0.1.0.dist-info/licenses/LICENSE
medium_mcp-0.1.0.dist-info/RECORD
```

Consequence if published as-is: `pip install medium-mcp` succeeds, installs the
`medium-mcp` console script from `entry_points.txt`, and then fails at first run with
`ModuleNotFoundError: No module named 'medium_mcp'`. The entry point references a module
the wheel does not ship.

All three READMEs list PyPI reservation as `pending (run uv publish)`, so this is
caught pre-publication. Fix is either `packages = ["src/medium_mcp"]` or a move to the
flat layout used by `raindropio-mcp` (`raindropio_mcp/` at the repository root). The
flat layout is preferred for consistency with the reference architecture, and because
it removes the failure mode rather than correcting one instance of it.

This is the packaging analogue of finding 4.3: a build that reports success while
producing nothing usable. It is included in each plan's Phase 0, where the exit
criterion is a wheel whose `unzip -l` output contains the package's `__init__.py`.

______________________________________________________________________

## 5. Architecture

### 5.1 Delivery order

Registry consolidation is **Plan 0 and a hard prerequisite**. Until canonical
`ecosystem.yaml` is the real manifest, a server plan's "registered and discoverable"
exit criterion has no checkable form — `mahavishnu repo list | grep medium-mcp` would
fail even after a correct edit to `repos.yaml`.

```
Plan 0: registry consolidation   ──blocks──┐
                                            ├─> Plan 1: archive-org-mcp
                                            ├─> Plan 2: medium-mcp
                                            └─> Plan 3: scapy-mcp
```

Server order is deliberate. `archive-org-mcp` requires no authentication, so it proves
the shared skeleton end-to-end with zero setup friction. `medium-mcp` and `scapy-mcp`
then inherit a validated pattern rather than debugging the skeleton and the service
simultaneously.

### 5.2 Shared package layout

Modeled on `raindropio-mcp`, which all three READMEs already name as the reference.

```
src/<package>/
  __init__.py
  __main__.py                 # main() entry point, matches [project.scripts]
  server.py                   # FastMCP server construction
  config/
    settings.py               # oneiric layered settings model
  clients/
    base_client.py            # httpx2 async client: retry, backoff, budget accounting
    <service>_client.py       # service-specific calls, typed returns
  models/                     # pydantic models; no Any in tool inputs
  tools/
    <domain>.py               # one module per tool domain
    tool_registry.py          # profile-gated registration
  utils/
    exceptions.py             # typed exception hierarchy
settings/
  <name>.yaml                 # committed defaults
tests/
  unit/
  integration/
    test_<tool>_e2e.py        # one per registered tool, asserts non-empty
```

### 5.3 Configuration

Oneiric layered precedence, consistent with the rest of the ecosystem:

```
defaults → settings/<name>.yaml → settings/local.yaml (gitignored) → env vars
```

Environment prefixes: `ARCHIVE_ORG_MCP_*`, `MEDIUM_MCP_*`, `SCAPY_MCP_*`. Secrets are
read from the environment only and never committed. Per
`oneiric-load-settings-no-project-root`, each settings module anchors with
`project_root=Path(__file__).resolve().parent.parent`.

### 5.4 Phase 0 — mandatory upstream proof

Every plan opens with a phase that makes one real upstream call and asserts non-empty
data **before any tool is registered**. Finding 4.3 is the justification: endpoint
existence is a falsifiable claim, and a server that registers tools against imagined
endpoints looks healthy by every surface signal.

| Server | Phase 0 proof |
|---|---|
| `archive-org-mcp` | One live CDX query for a known-archived URL returns ≥1 snapshot row |
| `medium-mcp` | One live `medium2` call returns a populated user object; the call is counted against budget |
| `scapy-mcp` | One committed pcap fixture is read and a known packet dissected to expected layers |
| all three | `uv build` produces a wheel whose `unzip -l` output contains the package `__init__.py` (finding 4.6) |

Phase 0 exits only when the proof is committed as a test. It is not a spike; the test
stays.

### 5.5 Health and feed state

Per `.claude/decisions/mcp-backend-wiring-discipline.md`:

- `/health` aggregates per-feed state and returns **503 on degraded**, not 200.
- Every registered tool exposes `feed.entities_count`,
  `feed.last_updated_timestamp`, `feed.errors_total`, `cycles_total`.
- Every registered tool has `tests/integration/test_<tool>_e2e.py` asserting
  **non-empty** results.
- CI spins up the server and asserts non-empty responses per tool.

A server with registered tools and no working feed reports `degraded`.

### 5.6 Tool profiles

Each server registers a `discover_tools(query)` meta-tool unconditionally, then gates
the rest behind `<NAME>_TOOL_PROFILE` with `full` / `standard` / `minimal`, following
`mcp-tool-profile-adoption`. Per
`2026-08-29-mcp-tool-registration-dual-track-drift-pattern`, registration flows through
a **single** path — one `REGISTRATION_MAP`, no parallel optional-block mechanism.

### 5.7 Async discipline

All I/O is async (`httpx2`, `aiofiles`). No blocking call inside an async function.
Where an upstream library is synchronous — the `internetarchive` package, all of
`scapy` — the bridge is explicit and confined to one adapter module, offloading through
`loop.run_in_executor` or `mahavishnu/core/process_pool_executor.py`.

______________________________________________________________________

## 6. Per-Server Design

### 6.1 archive-org-mcp — port 3051

**Client strategy: hybrid.** `httpx2` for the Wayback surface (CDX, availability,
archived-page retrieval), where fine-grained backoff control matters. The official
`internetarchive` library for catalog metadata and item downloads, where it carries
real value. The library is synchronous, so it is isolated behind a single adapter that
owns the executor bridge — its sync nature does not leak into tool handlers.

**Tool domains:**

| Domain | Capability |
|---|---|
| `wayback` | CDX snapshot queries: url, matchType, from/to, filter, collapse, limit |
| `availability` | Closest-snapshot lookup for url + timestamp |
| `catalog` | Advanced Search over IA metadata; Metadata API by identifier |
| `retrieval` | Fetch archived page content at a specific timestamp |

**Politeness, since IA enforces nothing (finding 4.4):** configurable concurrency cap
(default conservative), exponential backoff with jitter on 429/503, a per-response
size ceiling because archived pages can be very large, and a descriptive User-Agent
identifying the client. These are settings, not constants.

**Read-only.** Save Page Now and item upload are out of scope (non-goal 1) — writing
to a public shared archive on an LLM's initiative is an irreversibility risk not
justified by v1 value.

### 6.2 medium-mcp — port 3052

**Client strategy: `httpx2` direct to `https://medium2.p.rapidapi.com`** with
`X-RapidAPI-Key`, typed pydantic models per response. The `medium-api` wrapper is
rejected deliberately: it uses lazy attribute fetching, so `user.articles` followed by
per-article `.content` issues calls invisibly behind property access. When every call
is metered against a hard monthly cap, implicit I/O is a liability.

**The 150-call free tier is the binding architectural constraint.** A naive "fetch this
author's last 10 posts with content" is 12+ calls — roughly twelve such operations per
month before a hard wall. Caching is therefore load-bearing, not an optimization:

- **Dhara-backed persistent cache**, surviving process restarts. An in-memory cache
  would burn the monthly budget on every server start.
- **Request coalescing** so concurrent identical requests issue one upstream call.
- **Declared call cost per tool**, so the budget guard can evaluate a request before
  spending.
- **A budget guard that refuses.** On projected exhaustion the tool returns a typed
  error naming remaining budget and cache-hit alternatives. It does not silently
  proceed and it does not incur overage.

**Content policy (finding 4.2's restriction):** metadata, titles, links, and short
excerpts by default. Full article bodies require an explicit per-call opt-in flag, and
full text is **never** auto-persisted to Dhara or embedded into Akosha without that
flag. Recorded as a decision record in `.claude/decisions/`, following the precedent of
flowscape gating its MCP surface on legal review.

**README correction is a deliverable, not a side effect.** The four capability bullets
stay — finding 4.2 shows they are achievable — but the README must state that the
source is the unofficial medium2 API via RapidAPI, that the official API is retired,
that a RapidAPI key is required, and what the tier limits are. The current README
implies an official integration that does not exist.

**Tool domains:**

| Domain | Capability |
|---|---|
| `users` | Profile, followers, following, interests, top articles |
| `articles` | Metadata, excerpt, content (opt-in), responses, related |
| `publications` | Publication info, articles, newsletter |
| `tags` | Tag info, related tags, root tags, topfeeds, latest posts |
| `search` | Articles, users, publications, lists, tags |
| `budget` | Remaining call budget, cache statistics, hit rate |

The `budget` domain is a first-class tool, not diagnostics: an agent must be able to
ask what it can afford before spending.

### 6.3 scapy-mcp — port 3053

**Capture: live in v1, degrading gracefully.** Live sniffing uses scapy's
`AsyncSniffer`. On startup the server probes `/dev/bpf*` accessibility; if unreachable
it logs at warning level, reports `degraded` on the capture feed, and continues serving
offline tools rather than failing to start. The macOS privilege constraint — root or a
ChmodBPF-style helper — is the same one the flowscape spec documents, and the same
resolution is followed rather than reinvented.

**Blocking-call discipline.** Scapy is synchronous and `sniff()` blocks. Capture is
offloaded via `mahavishnu/core/process_pool_executor.py` or `run_in_executor`.
Sessions are bounded by explicit packet count and duration limits so a capture cannot
run unbounded.

**Transmit: disabled by default, gated on three independent controls.** Scapy can emit
arbitrary frames (`send`, `sendp`, `sr1`, `srp`), which makes ARP spoofing, SYN
flooding, and DNS poisoning reachable from a tool call. All three must be satisfied:

1. `transmit_enabled: false` in settings — must be explicitly turned on.
1. A destination CIDR allowlist — empty by default; a packet to a non-allowlisted
   destination is refused.
1. A rate cap — packets per second and total per session.

**Demonstrability inverts here.** For the other two servers, "wired" means a tool
returned real rows. For transmit, the Integration Contract's "Demonstrable by" proves a
**refusal**: a send to a non-allowlisted destination is rejected with a typed error,
and the rejection is observable. Safety features are verified by their denials.

**Tool domains:**

| Domain | Capability | Privileges |
|---|---|---|
| `craft` | Build L2/L3/L4 packets from layer specs | none |
| `dissect` | Decode packet bytes to structured summaries | none |
| `pcap` | Read/write `.pcap` / `.pcapng` | none |
| `capture` | Live sniff with optional BPF filter | `/dev/bpf*` |
| `transmit` | Send crafted packets | opt-in + allowlist + rate cap |

The first three need no privileges, so CI exercises them fully against committed
fixtures.

**Fixtures.** Committed pcap fixtures with deterministic timestamps, each shipping a
`.provenance.json`, generated by a committed script and verified byte-identical across
runs — reusing the pattern from the flowscape plan's `gen_pcap_fixtures.py` rather than
inventing a second convention.

**Relationship to flowscape.** flowscape lists `scapy-mcp` enrichment as v2+.
`scapy-mcp` is designed standalone; nothing in it presumes flowscape. Its tool surface
should be shaped so flowscape could later consume it, but no flowscape integration
ships here (non-goal 3).

______________________________________________________________________

## 7. Registry Consolidation (Plan 0)

### 7.1 Migration

Merge all 32 `repos.yaml` entries into canonical `mahavishnu/settings/ecosystem.yaml`,
preserving that file's schema (`name`, `package`, `path`, `nickname`, `nicknames`,
`role`, `tags`, `description`, `status`) and its `roles:` and `coordination:` sections.
Reconcile fields present in only one file — `repos.yaml` carries `mcp:`
(`native` / `3rd-party`), which `ecosystem.yaml` lacks and should gain.

Add the three new servers **to canonical `ecosystem.yaml` only**. They are deliberately
not added to `repos.yaml`: writing new entries into a file being deprecated in the same
plan would manufacture the drift the plan exists to remove.

Then mark `repos.yaml` deprecated with a header pointing at the canonical file; do not
delete it in this plan, since `bootstrap.py` still reads it as a fallback and
`crackerjack` and `mcp-common` have their own `settings/repos.yaml` files whose
relationship is unverified (open item 2).

### 7.2 bodai config repairs

- `druva` → `dhara`: rename the component key, fix `repo:`, fix `start_command:`.
- Remove `n8n-mcp` (repository does not exist).
- Allocate `3050: spline-mcp` in `portmap.yaml` and narrow the reserved range to
  3054-3059.
- Add `3051: archive-org-mcp`, `3052: medium-mcp`, `3053: scapy-mcp`.
- Add the three new components to `bodai/config/ecosystem.yaml`.

### 7.3 Guard test

A sync test in the style of `tests/unit/test_task_router.py::TestYAMLRoutingSync`,
asserting:

1. Every `path` in canonical `ecosystem.yaml` exists on disk.
1. No two components share a port across `bodai/config/ecosystem.yaml` and
   `portmap.yaml`.
1. Every port in `ecosystem.yaml` has a matching `portmap.yaml` allocation, and vice
   versa.
1. Canonical `ecosystem.yaml` is a **superset** of `repos.yaml` by `name`.

Assertion 4 is the one that would have caught this drift in May instead of September.

______________________________________________________________________

## 8. Testing Strategy

| Layer | Scope | Marker |
|---|---|---|
| Unit | Models, settings precedence, client request construction, budget arithmetic, allowlist logic | `unit` |
| Integration | One `test_<tool>_e2e.py` per registered tool, asserting non-empty | `integration` |
| Upstream proof | Phase 0 real-call test per server | `integration`, `requires_network` |
| Registry guard | Path existence, port uniqueness, manifest superset | `unit` |
| Refusal | Budget-exhaustion refusal; transmit allowlist rejection | `unit` |

Project markers only — no invented markers. `asyncio_mode = "auto"`, so async tests
need no decorator. Anything over 10s is marked `slow`.

Coverage target 89% per the crackerjack gate. `scapy-mcp`'s capture path cannot be
covered in CI without privileges; it gets an explicitly documented lower per-module
target, following the flowscape precedent of per-module gates rather than a blanket
number.

Network-dependent tests are marked `requires_network`. Metered `medium-mcp` calls are
additionally guarded so a full-suite run cannot silently consume the monthly budget —
cassette/fixture replay by default, live calls only under an explicit opt-in.

______________________________________________________________________

## 9. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| medium2 is unofficial and could vanish or change without notice | medium | Isolate behind one client module; typed models fail loudly on schema change; Phase 0 test detects breakage |
| 150-call budget exhausted during development | high | Cache-first design; fixture replay in tests; budget tool surfaces remaining calls |
| Copyright restriction violated by piping full text into Akosha/Dhara | medium | Opt-in-only full text; no auto-persist; decision record |
| `scapy-mcp` transmit reachable via prompt injection | low-medium | Three independent controls; disabled default; refusal tests |
| Live capture unavailable on target machine | high | Degrade to offline; report `degraded`; offline tools remain functional |
| IA throttles or blocks on impolite use | medium | Concurrency cap, backoff with jitter, identifying User-Agent |
| Registry migration breaks routing for the 8 currently-working repos | medium | Guard test runs before merge; migration preserves existing entries verbatim |
| `internetarchive` sync library blocks the event loop | medium | Confined to one adapter with an explicit executor bridge |
| Empty wheel published to PyPI, burning the 0.1.0 version | medium | Phase 0 asserts wheel contents; flat layout removes the failure mode |

______________________________________________________________________

## 10. Decision Rule

Under scope pressure, cut in this order:

1. `scapy-mcp` transmit domain — highest risk, lowest v1 value.
1. `scapy-mcp` live capture — offline tools are the useful core.
1. `medium-mcp` `search` domain — the most call-expensive surface.
1. `archive-org-mcp` `catalog` domain — Wayback is the primary draw.

**Never cut:** Phase 0 upstream proof, feed-state health, the registry guard test, or
the transmit allowlist. Those four are what separate this from finding 4.3.

A server is done when: Phase 0 proof is committed and green; every registered tool has
a passing non-empty e2e test; `/health` reports per-feed state and returns 503 when
degraded; the repo appears in `mahavishnu repo list`; and `crackerjack run` passes.

______________________________________________________________________

## 11. Open Items

1. **`medium-mcp` requires a RapidAPI subscription before Phase 0 can run.** Even the
   free tier needs an account, a subscription to medium2, and `MEDIUM_MCP_RAPIDAPI_KEY`
   exported. This is a human prerequisite, not an implementation task.
1. **`crackerjack/settings/repos.yaml` and `mcp-common/settings/repos.yaml`** also
   exist. Their relationship to Mahavishnu's manifest is unverified. Plan 0 should
   determine whether they are independent or stale copies.
1. **Whether the flat vs. `src/` layout decision affects `[project.scripts]`.** Moving
   to a flat layout changes nothing in the entry-point string
   (`medium_mcp.__main__:main`), but the `[tool.hatch.build.targets.sdist] exclude`
   list should be re-checked after the move.

______________________________________________________________________

## References

- `docs/plans/TEMPLATE.md` — Integration Contract structure
- `.claude/decisions/wire-up-contract.md` — plan-time integration policy
- `.claude/decisions/mcp-backend-wiring-discipline.md` — runtime feed-state policy
- `docs/superpowers/specs/2026-08-31-flowscape-design.md` — pcap fixtures, BPF
  privilege constraint, per-module coverage gates
- `raindropio-mcp` — reference package architecture
- [Medium Help Center — API/Importing](https://help.medium.com/hc/en-us/articles/213480228-API-Importing)
- [mediumapi.com](https://mediumapi.com/) / [docs.mediumapi.com](https://docs.mediumapi.com/)
- [Internet Archive APIs](https://archive.org/developers/apis)
- [Wayback CDX Server API](https://archive.org/developers/wayback-cdx-server-api)
