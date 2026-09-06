---
status: draft
role: implementation
date: 2026-09-06
last_reviewed: 2026-09-06
superseded_by: null
topic: mcp-stub-activation
---

# MCP Stub Activation — archive-org-mcp, medium-mcp, scapy-mcp

**Scope:** Turn three PyPI name-reservation scaffolds into working MCP servers, and
repair the repository and port registries that make "registered" mean something.

**Revision 2** — incorporates a four-lens multi-agent review (2026-09-06: factual
verification, adversarial red-team, Bodai conformance, plan-readiness). Revision 1
described `mcp-common`, `raindropio-mcp`, and the Mahavishnu CLI from inference; every
internal API in this revision was read from source. See §12 for the review log.

**Path convention:** repo-relative paths are written from the repository root. Because
the Mahavishnu repo and its package share a name, `settings/ecosystem.yaml` means
`/Users/les/Projects/mahavishnu/settings/ecosystem.yaml`, never
`mahavishnu/mahavishnu/settings/`.

______________________________________________________________________

## 1. Context

Three directories in `~/Projects` are name-reservation scaffolds created 2026-08-31.
Each contains `.gitignore`, `LICENSE`, `pyproject.toml`, `README.md`, a built `dist/`,
and three stub files under `src/`. All three status tables read
`Spec / plan: not written` and `Implementation: not started`.

| Repo | Package | Purpose |
|---|---|---|
| `archive-org-mcp` | `archive_org_mcp` | Internet Archive — Wayback snapshots, catalog search |
| `medium-mcp` | `medium_mcp` | Medium — posts, users, publications, tags |
| `scapy-mcp` | `scapy_mcp` | Scapy — packet crafting, dissection, capture, PCAP I/O |

**None of the three is a git repository.** No `.git` directory exists in any of them
(finding 4.7). This is a prerequisite, not a detail.

All three declare an identical stack: `fastmcp>=2.12.0`, `httpx2>=0.28.1`,
`mcp-common>=0.18.0`, `oneiric>=0.16.0`, `pydantic>=2.5.0`,
`pydantic-settings>=2.1.0`, `requires-python >=3.14`, BSD-3-Clause. `scapy-mcp` adds
`scapy>=2.5.0`.

### Why a shared spec

The three servers share their bootstrap, config, profile-dispatch, health, and client
skeleton. Writing that three times guarantees drift. This spec owns the shared
architecture and the concrete contracts; each plan owns execution.

______________________________________________________________________

## 2. Goals

1. Each repo exposes MCP tools that return real upstream data, verified by integration
   tests asserting non-empty results.
1. `settings/ecosystem.yaml` becomes the true single source of truth for the repository
   manifest, with all 35 repositories registered (the 32 in `repos.yaml`, which already
   subsume the canonical 8, plus the 3 new servers).
1. `bodai/config/portmap.yaml` is reconciled with the ports repos actually bind.
1. Registry and port drift fail CI instead of going silent.
1. `medium-mcp`'s README is corrected to name its real upstream API.
1. `scapy-mcp` cannot emit a frame onto a network without passing layer-appropriate
   controls.
1. All three repos are git repositories that build wheels containing their package.

## 3. Non-Goals

1. **Save Page Now / Internet Archive uploads.** Read-only v1 for `archive-org-mcp`.
1. **Medium write operations.** Official API retired; no legacy token exists.
1. **flowscape integration.** Listed there as v2+; not delivered here.
1. **TLS SNI extraction, MAC/OUI bundling, protocol heuristics.** flowscape's scope.
1. **Retiring `bodai/config/ecosystem.yaml`.** Different schema, different consumers.
1. **Deleting `settings/repos.yaml`.** An active consumer exists (finding 4.6).
1. **Adding a 503 path to `mcp_common.health`.** Out of scope; see §5.5 for the
   in-repo pattern instead.
1. **Registering non-project directories.** `ARCHIVED/`, `BACKUP/`, `SCRATCH/`,
   `sites/`.

______________________________________________________________________

## 4. Verified Findings

Every claim below was established by running a command or reading source.

### 4.1 Medium's official API is retired and unusable

Medium's Help Center: *"Medium will not be issuing any new integration tokens for our
API and will not allow any new integrations. All existing tokens will continue to
work."* The integration-token setting was removed around February 2025. n8n's
documentation (June 2026) confirms new integrations cannot be configured.
mediumapi.com corroborates: the official API was *"archived 2 March 2023"* and *"you
cannot extract anything using it."*

No `MEDIUM_*` credential exists in the environment, the shell rc files, or
`.mcp.json`. The grandfathered path is unavailable.

The complete official surface was seven endpoints — `GET /v1/me`,
`GET /v1/users/{userId}/publications`,
`GET /v1/publications/{publicationId}/contributors`,
`POST /v1/users/{authorId}/posts`, `POST /v1/publications/{publicationId}/posts`,
`POST /v1/images`, `POST /v1/tokens` — with **no read or search capability**.

### 4.2 The medium2 unofficial API provides the needed surface

[mediumapi.com](https://mediumapi.com/) ("medium2"), wrapped by the `medium-api` PyPI
package, covers all four capability groups the README promises. Access is via RapidAPI:
base `https://medium2.p.rapidapi.com`, header `X-RapidAPI-Key`.

| Tier | Cost | Calls/month | Overage |
|---|---|---|---|
| Basic | $0 | **150** | hard limit |
| Pro | $10/mo | 2,500 | $0.004/call |
| Ultra | $30/mo | 25,000 | $0.004/call |
| Mega | $150/mo | 1,000,000 | $0.04/call |

Per-second limits are undocumented. Content restriction: *"We strictly prohibit our
users from fetching copyrighted content from Medium without the explicit permission
from the author."*

### 4.3 A cautionary precedent: `Dishant27/medium-mcp-server`

Non-functional. `src/auth.ts` returns a fabricated token —
`` return `medium_token_${Date.now()}`; `` — with comments conceding *"This is a
placeholder for actual Medium OAuth flow"* and zero network calls. `src/client.ts`
targets the right base but five of six endpoints do not exist (`POST /publications`,
`GET /publications` without the required path param, `GET /articles`, `GET /drafts`,
`POST /drafts`); only `GET /me` is real.

It registers six tools, exposes a schema, and would pass any test that mocks HTTP —
while being incapable of returning one real row. **This is why every plan opens with a
Phase 0 that makes one real upstream call and asserts non-empty data before any tool is
registered.**

*Verification note:* read from the GitHub repo, not from a local clone. Treated as
motivating precedent, not as a load-bearing dependency.

### 4.4 archive.org is fully available for reads

CDX Server API (`http://web.archive.org/cdx/search/cdx`), Availability API
(`https://archive.org/wayback/available`), Advanced Search
(`https://archive.org/advancedsearch.php`), Metadata API
(`https://archive.org/metadata/{identifier}`) — live, documented, no auth for reads.

Internet Archive: *"Please be respectful and use this free public resource. While we do
not have hard rate limits..."* Politeness is our responsibility, not an enforced limit.

### 4.5 The repository registry has a four-month silent drift

| File | Read by | Entries | Status |
|---|---|---|---|
| `settings/ecosystem.yaml` | `load_repos()` at `mahavishnu/core/bootstrap.py:187`, path from `repos_path` (`settings/mahavishnu.yaml:18`; field default `mahavishnu/core/config.py:2181`) | **8 repos** + 15 roles | **canonical** |
| `settings/repos.yaml` | `_resolve_repos_path()` fallback at `mahavishnu/core/bootstrap.py:130`, and directly by `mahavishnu/repo_cli.py:16` | **32 repos** | legacy, but live |
| `bodai/config/ecosystem.yaml` | `bodai/core/config.py:15` | 23 components | separate schema |
| `bodai/config/portmap.yaml` | `bodai/core/config.py:23` | port allocations | separate |

Counts by YAML parse. `ecosystem.yaml` uses `- name:` for both repos and roles, so a
line count reports 23 and overstates the repo count.

`mahavishnu/core/config_validator.py:9`: *"Note: repos.yaml is legacy. Use
ecosystem.yaml as the single source of truth."*

Canonical `ecosystem.yaml` holds 8 repos — `mahavishnu`, `crackerjack`,
`session-buddy`, `oneiric`, `mcp-common`, `mdinject`, `akosha`, `dhara` — and is
stamped `last_updated: '2026-05-11'`.

**24 repositories are invisible to Mahavishnu at runtime:** `raindropio-mcp`,
`unifi-mcp`, `mailgun-mcp`, `graphics-mcp`, `css-mcp`, `langsmith-mcp`, `neo4j-mcp`,
`spline-mcp`, `penpot-api-mcp`, `opera-cloud-mcp`, `excalidraw-mcp`,
`porkbun-dns-mcp`, `porkbun-domain-mcp`, `synxis-crs-mcp`, `synxis-pms-mcp`,
`www-mcp-servers`, `fastblocks`, `fastblocks-ui`, `splashstand`,
`jinja2-async-environment`, `jinja2-custom-delimiters`, `jinja2-inflection`,
`starlette-async-jinja`, and `bodai` itself. Set difference verified — no omissions, no
extras.

The fallback never fires, because `ecosystem.yaml` exists. Nothing breaks loudly.

Dangling entries — exactly two, both in `bodai/config/ecosystem.yaml`: `druva`
(`~/Projects/druva` absent; renamed `dhara`) and `n8n-mcp` (`~/Projects/n8n-mcp`
absent). Both Mahavishnu manifests have zero dangling paths.

Never registered in any manifest: `flowscape`, `bodai-plugins`, `peanutbutterpub`,
`mdinject-pypi-placeholder`.

### 4.6 `repo_cli.py` is a live consumer of the legacy manifest

`mahavishnu/repo_cli.py:16` hard-codes `REPOS_CATALOG_PATH = Path("settings/repos.yaml")`
and loads it at `:23`. So `repos.yaml` cannot simply be marked deprecated — a working
command reads it.

Separately, the CLI surface is not what a naive reading suggests. `list_repos` is a
**top-level** command (`mahavishnu/_main_cli.py:886` → `mahavishnu list-repos`). The
`repo` sub-typer (`_main_cli.py:1282`) exposes only `diff` and `pr-create`. **There is
no `mahavishnu repo list`.** Every exit criterion must use `mahavishnu list-repos`.

### 4.7 The three scaffolds are not git repositories

`ls -a` shows `.gitignore` but no `.git` in any of the three. They were never
`git init`'d: no commits, no remote, no GitHub repository. `crackerjack run` performs
git operations, so this blocks every plan's exit criteria until resolved.

Scaffold contents are stubs: `__init__.py` 7 lines (docstring + `__version__`),
`__main__.py` 20 lines (`main()` prints a "not yet implemented" line), `server.py` 13
lines (`mcp = FastMCP("<pkg>")` and a comment; **no tools registered**).

### 4.8 All three build empty wheels — but the sdists are fine

Each `pyproject.toml` declares:

```toml
[tool.hatch.build.targets.wheel]
packages = ["medium_mcp"]          # and archive_org_mcp, scapy_mcp
```

Code lives at `src/<package>/`, not `./<package>/`. Hatchling resolves against the
project root, finds nothing, and **does not error** — it emits a metadata-only wheel.
Verified: all three `dist/*.whl` contain exactly five files, all under `dist-info/`,
zero Python modules.

**The sdists are unaffected** — `dist/*.tar.gz` contains `src/<pkg>/__init__.py`,
`__main__.py`, and `server.py` for all three. The defect is wheel-only, so
`pip install` from wheel fails while an sdist build would work.

Consequence if published: `pip install medium-mcp` succeeds, installs the console
script, then dies on `ModuleNotFoundError: No module named 'medium_mcp'`. All three
READMEs list reservation as `pending`, so this is caught pre-publication.

Resolution: **move to the flat layout** (`<package>/` at repo root), matching
`raindropio-mcp`, `css-mcp`, and `langsmith-mcp` — all three of which use flat layout,
not `src/`. This removes the failure mode rather than correcting one instance, and it is
required for the `project_root` anchor in §5.3 to resolve correctly.

### 4.9 `portmap.yaml` is wrong about six allocations

Audited every `<repo>/settings/*.yaml` for port declarations and compared to
`bodai/config/portmap.yaml`:

| Port | `portmap.yaml` says | Repo settings actually declare |
|---|---|---|
| 3049 | `css-mcp` | *(nothing — actually free)* |
| 3050 | reserved; `spline-mcp` per ecosystem.yaml | **`css-mcp`** |
| 3051 | *(absent)* | **`penpot-api-mcp`** |
| 3052 | *(absent)* | **`spline-mcp`** |
| 8679 | *(absent)* | **`mdinject`** |
| 8684 | `fastblocks` | **`crackerjack`** `dashboard_port` |
| 8685 | `mdinject` | **`crackerjack`** `zuban_port` |
| 3002 | *(absent)* | **`akosha`** `mcp_port` |

`portmap.yaml` also reserves `3050-3059: future expansion` while `ecosystem.yaml`
assigns `spline-mcp` to 3050 — and spline actually binds 3052.

Genuinely unclaimed in the integration range: **3032, 3041, 3044, 3049, 3053, 3054+**.

*Verification limit:* this audit covers `settings/*.yaml`, `portmap.yaml`, and
`bodai/config/ecosystem.yaml`. Repos that declare ports in code defaults, `.env`, or
`pyproject.toml` were not scanned. "Free" is confirmed against three sources, not
exhaustively. Plan 0b widens the audit before allocating.

### 4.10 The internal APIs this spec builds on — read from source

| Symbol | Location | Contract |
|---|---|---|
| `bootstrap_baseline_tools(server) -> list[str]` | `mcp_common/bootstrap.py` | Registers **four** tools: `discover_tools`, `get_liveness`, `get_readiness`, `health_check_all`. Idempotent. Does **not** seed `LivenessContext`. |
| `seed_liveness_context(*, service_name, version, start_time=None)` | `mcp_common/baseline_tools.py:140` | Must be called from lifespan startup, or `get_liveness()` returns a bare envelope. |
| `_apply_tool_profile(...)` (async) / `apply_tool_profile(...)` (sync) | `mcp_common/tools/dispatch.py:253` | Kwargs: `profile_env_var`, `registrations: dict[ToolProfile, list \| ALL_TOOLS]`, `registration_map: dict[str, Callable]`, `register_all_fn`, `mandatory_groups`, `essential_tool_names`, `discovery_fn`, `yaml_loader`. Sync form wraps the async in `asyncio.run()`. |
| `register_http_health_route(mcp, *, service_name, version, extra_components=None)` | `mcp_common/health.py:810` | **"The handler always returns HTTP 200"** — verbatim from its docstring. Body: `{status, service, version, components}`. There is no 503 path. |
| `APIKeyValidator` | `mcp_common.security` | Imported under `suppress(ImportError)` with a `SECURITY_AVAILABLE` flag in `raindropio_mcp/config/settings.py:23-27`. |
| `workflow.retry` action | `oneiric/oneiric/actions/workflow.py:521+` | `side_effect_free=True`. Returns **guidance**: `{attempt, max_attempts, status, next_attempt, delay_seconds}`. Computes a delay; does **not** perform the retry. Jitter is deterministic (`0.25 if attempt % 2 == 0 else 0.15`), **not** stochastic. |

`raindropio-mcp/raindropio_mcp/server.py` is the worked precedent: it calls
`register_http_health_route(app, service_name=..., version=...)` for `/health` **and
separately** defines `@app.custom_route("/healthz")` for a richer check. That is the
sanctioned way to get a non-200 status without modifying the shared helper.

It also documents a sync-async bridge (`_run_async_safely`) because profile dispatch is
async while CLI startup is sync: `asyncio.run` when no loop is running, a private
single-worker `ThreadPoolExecutor` when one is.

______________________________________________________________________

## 5. Architecture

### 5.1 Delivery order

Plan 0 splits, and the gate softens. Each server plan needs exactly one thing from the
registry work — its own entry in `settings/ecosystem.yaml` — which is a one-line edit,
not a 32-entry migration.

```
Plan 0a: manifest migration      ─┐  (32 entries + 3 new + repo_cli repoint + guard)
Plan 0b: port + bodai reconcile  ─┤  (portmap truth-up, druva→dhara, n8n removal)
                                  │
Server plans require ONLY their own ecosystem.yaml entry (Phase 0 task),
so Plan 1/2/3 start immediately and 0a/0b proceed in parallel.
                                  │
        ├─> Plan 1: archive-org-mcp   (no auth — proves the skeleton)
        ├─> Plan 2: medium-mcp        (needs RapidAPI key, see §11)
        └─> Plan 3: scapy-mcp         (most constrained)
```

Server order is deliberate: `archive-org-mcp` needs no authentication, so it validates
the shared skeleton with zero setup friction.

### 5.2 Package layout — flat, not `src/`

Matching `raindropio-mcp`, `css-mcp`, and `langsmith-mcp` (finding 4.8). Phase 0 of each
server plan moves `src/<package>/` to `<package>/` and fixes the hatch target.

```
<package>/
  __init__.py            __main__.py           server.py
  config/settings.py     # oneiric layered settings
  clients/base_client.py # httpx2 async: retry loop, backoff, budget accounting
  clients/<svc>_client.py
  models/                # pydantic; no Any in tool inputs
  tools/<domain>.py
  tools/profiles.py      # PROFILE_REGISTRATIONS + _build_registration_map
  utils/exceptions.py
settings/<name>.yaml
tests/unit/  tests/integration/  tests/fixtures/
```

`tools/profiles.py` mirrors `raindropio_mcp/tools/profiles.py`, which is where
`PROFILE_REGISTRATIONS` and `_build_registration_map` live in the precedent.

### 5.3 Configuration

Oneiric layered precedence: `defaults → settings/<name>.yaml → settings/local.yaml
(gitignored) → env vars`. Prefixes `ARCHIVE_ORG_MCP_*`, `MEDIUM_MCP_*`, `SCAPY_MCP_*`.
Secrets from environment only.

`project_root=Path(__file__).resolve().parent.parent` from `<package>/config/settings.py`
resolves to the repo root **under the flat layout only** — this is a second reason §5.2
is not optional.

`MEDIUM_MCP_RAPIDAPI_KEY` is validated with `mcp_common.security.APIKeyValidator`,
imported under `suppress(ImportError)` with a `SECURITY_AVAILABLE` flag, per
`raindropio_mcp/config/settings.py:23-27`.

### 5.4 Phase 0 — split into hermetic and networked halves

Bundling a deterministic check with a network-dependent one means a network blip blocks
the packaging fix. Two sub-phases, both required to exit:

**Phase 0a — hermetic, runs in PR CI:**

1. `git init`, initial commit, remote configured (finding 4.7).
1. Flat-layout move; `uv build` produces a wheel whose `unzip -l` contains
   `<package>/__init__.py` (finding 4.8).
1. `[tool.pytest.ini_options]` with `--cov-fail-under` and `[tool.coverage.run] omit`
   added to `pyproject.toml` — the crackerjack gate is **opt-in** and currently
   unconfigured in all three repos (§8).
1. The repo's entry added to `settings/ecosystem.yaml`; `mahavishnu list-repos | grep
   <name>` returns it.

**Phase 0b — networked, marked `requires_network`, excluded from PR CI, run nightly:**

| Server | Proof |
|---|---|
| `archive-org-mcp` | One live CDX query for a known-archived URL returns ≥1 snapshot row |
| `medium-mcp` | One live medium2 call returns a populated user object; **response recorded as a cassette**, so the test replays hermetically thereafter |
| `scapy-mcp` | One committed pcap fixture read, known packet dissected to expected layers *(hermetic — belongs in 0a)* |

`medium-mcp`'s live call runs **once, recorded, then replayed**. A live call per CI run
would consume 30-60 of 150 monthly calls before any user request.

Phase 0b proves one endpoint, not the whole surface. Each tool's own
`test_<tool>_e2e.py` (§8) is what covers the rest; a green Phase 0b is necessary, not
sufficient.

### 5.5 Health — two routes, because the shared helper cannot return 503

`.claude/decisions/mcp-backend-wiring-discipline.md` requires `/health` to return 503
when degraded. `register_http_health_route` **always returns 200** (finding 4.10). These
conflict, and modifying the shared helper is a non-goal.

Following the `raindropio-mcp` precedent:

- **`/health`** — `register_http_health_route(app, service_name=..., version=...,
  extra_components=[...])`. Always 200. Feed state passed via `extra_components`.
  Satisfies orchestrator and `curl` probes.
- **`/readyz`** — an in-repo `@app.custom_route("/readyz", methods=["GET"])` returning
  **503 when any required feed is degraded**, 200 otherwise. This is the route the
  wiring-discipline gate checks.

**Required vs. optional feeds.** A feed unavailable *by environment* is not a fault. Each
server declares which feeds are required:

| Server | Required feeds | Optional feeds |
|---|---|---|
| `archive-org-mcp` | `cdx`, `catalog` | — |
| `medium-mcp` | `medium2` | — |
| `scapy-mcp` | `pcap`, `craft`, `dissect` | `capture` (needs BPF), `transmit` (opt-in) |

So a stock Mac without ChmodBPF reports `capability_unavailable` on `capture` and still
returns **200** on `/readyz` — four of five domains work. Only a required-feed failure
yields 503. Revision 1 conflated these and would have returned 503 on every developer
machine.

Every tool exposes `feed.entities_count`, `feed.last_updated_timestamp`,
`feed.errors_total`, `cycles_total`.

### 5.6 Baseline tools and profile dispatch — reuse, do not reinvent

**Baseline is four tools, not one.** `bootstrap_baseline_tools(server)` registers
`discover_tools`, `get_liveness`, `get_readiness`, `health_check_all`. Lifespan startup
must additionally call `seed_liveness_context(service_name=..., version=...)` or
`get_liveness()` returns a bare envelope.

**Profile dispatch uses `mcp_common.tools.dispatch`,** not a hand-rolled map. Per
`raindropio_mcp/server.py`:

```python
await _apply_tool_profile(
    server,
    profile_env_var="<NAME>_TOOL_PROFILE",
    registrations=PROFILE_REGISTRATIONS,
    registration_map=_build_registration_map(client),
    register_all_fn=lambda srv: register_all_tool_groups(srv, client),
    mandatory_groups={"health_tools"},
    essential_tool_names={"health_check"},
)
```

Because dispatch is async and CLI startup is sync, each server needs the
`_run_async_safely` bridge documented in `raindropio_mcp/server.py`.

**Profile placement of gated tools.** `scapy-mcp`'s `transmit` domain is registered only
at `full`; `standard` and `minimal` omit it. The three transmit controls (§6.3) and the
profile gate compose as four independent barriers, and the profile is the outermost.

### 5.7 Async discipline

All I/O async. No blocking call inside an async function. `scapy` is synchronous, so
capture offloads via `run_in_executor` with a **dedicated, sized executor** — not the
default — so a long pcap write cannot starve a sniffer. `internetarchive` is dropped
entirely (§6.1), removing one sync bridge.

### 5.8 Retry and backoff — compose with oneiric

`oneiric.actions` `workflow.retry` is `side_effect_free=True` and returns
`{attempt, max_attempts, status, next_attempt, delay_seconds}` — it computes a delay,
it does not retry. Reuse it as the delay calculator inside our retry loop, per CLAUDE.md's
`oneiric.actions`-first rule.

Its jitter is **deterministic** (`0.25 if attempt % 2 == 0 else 0.15`), not stochastic.
Where genuine randomised jitter is wanted — thundering-herd avoidance against
archive.org — the retry loop adds its own random component on top and documents that it
does so.

______________________________________________________________________

## 6. Per-Server Design and Contracts

### 6.1 archive-org-mcp — port 3054

**Client: `httpx2` only.** `internetarchive` is dropped. Its distinctive value is
uploads, downloads, and collection management — all non-goals (§3.1) — so it would buy
nothing while costing a sync-to-async bridge. `httpx2` covers CDX, availability,
advancedsearch, and metadata, and honours §5.7 with no bridge.

**Tools:**

| Tool | Inputs | Returns |
|---|---|---|
| `wayback_snapshots` | `url: str`, `match_type: Literal["exact","prefix","host","domain"] = "exact"`, `from_ts: str \| None` (14-digit), `to_ts: str \| None`, `collapse: Literal["urlkey","digest","timestamp"] \| None`, `limit: int = 50` | `list[Snapshot]` — `{timestamp, original, mimetype, statuscode, digest, length}` |
| `wayback_closest` | `url: str`, `timestamp: str` (14-digit) | `Snapshot \| None` |
| `catalog_search` | `query: str`, `fields: list[str] = ["identifier","title","mediatype","date"]`, `rows: int = 25`, `page: int = 1` | `list[CatalogItem]` |
| `catalog_metadata` | `identifier: str` | `ItemMetadata` |
| `retrieve_snapshot` | `url: str`, `timestamp: str`, `max_bytes: int \| None = None` | `{content, truncated: bool, fetched_bytes}` |

CDX calls use `output=json`; the first row is the header and is consumed, not returned.
`from_ts`/`to_ts` are 14-digit `YYYYMMDDhhmmss`, zero-padded from shorter input.
Multi-value CDX fields are returned as lists, never joined strings.

**Politeness settings** (IA enforces nothing, §4.4):

| Key | Default |
|---|---|
| `concurrency_limit` | `2` |
| `max_response_bytes` | `5_242_880` (5 MiB) |
| `retry_max_attempts` | `4` |
| `backoff_base_seconds` | `1.0` |
| `backoff_multiplier` | `2.0` |
| `backoff_max_seconds` | `30.0` |
| `http_timeout_seconds` | `30.0` |
| `user_agent` | `archive-org-mcp/{version} (+https://github.com/lesleslie/archive-org-mcp)` |
| `cache_ttl_seconds` | `3600` |

Backoff on 429/503 via §5.8. `retrieve_snapshot` streams and truncates at
`max_response_bytes`, setting `truncated: true` rather than buffering unbounded.

### 6.2 medium-mcp — port 3055

**Client: `httpx2` direct** to `https://medium2.p.rapidapi.com`, header
`X-RapidAPI-Key`, typed pydantic models. `medium-api` is rejected: it fetches lazily
behind attribute access, and implicit I/O is a liability when calls are metered.

**Cache is the load-bearing component**, not an optimization — 150 calls/month.

**Cache contract:**

- Key: `medium2:v1:<endpoint>:<sorted-query-hash>` — `endpoint` is the medium2 path,
  `sorted-query-hash` is a SHA-256 of canonically-sorted params. Coalescing uses the
  same key.
- Dhara namespace: `medium_mcp` (per `dhara-key-prefixes`, an isolated top-level
  prefix).
- Value: pydantic model `model_dump_json()`, with a `schema_version` field so a model
  change invalidates rather than mis-parses.
- TTL: `user_info` 86400s · `user_articles` 3600s · `article_metadata` 604800s ·
  `article_content` 2592000s (30d — immutable once published) · `search_*` 1800s ·
  `tag_*` 21600s.
- Eviction: LRU with `cache_max_entries` default `10_000`; `article_content` entries are
  additionally bounded by `cache_max_content_bytes` default `52_428_800` (50 MiB).
- **Dhara unavailable at startup:** the server starts, logs at warning, reports the
  `medium2` feed `degraded` (→ 503 on `/readyz`, §5.5), and **refuses all metered
  calls**. It does not fall back to an in-memory counter — that risks silent overspend.

**Budget guard:**

- Counter key `medium2:v1:budget:<YYYY-MM>` in the same Dhara namespace, with **no
  TTL** — it must not evict. Distinct from the cache keyspace so cache eviction cannot
  reset it.
- Mutation is a **single atomic compare-and-increment**, not read-then-write. A
  concurrent pair at 149 must not both pass; the loser gets `BudgetExhaustedError`.
- **Failed calls count.** Any request that reaches RapidAPI is assumed metered
  regardless of status, because RapidAPI's metering behaviour on 4xx/5xx is
  undocumented. Retries therefore consume budget, so `medium-mcp` sets
  `retry_max_attempts: 1` — no retry on metered calls. This deliberately differs from
  archive-org-mcp.
- `budget_remaining` is a **local read** (Dhara only, zero upstream calls) and is free.

**Call cost is measured, not declared.** Revision 1 assumed static per-tool cost;
medium2 paginates, so `article_responses` fans out by response count. Instead:

- Every tool declares `min_cost` (calls needed for the first page) and
  `max_pages` (default `1`). Cost is bounded as `min_cost × max_pages`, and the guard
  reserves the **upper bound** before starting, releasing unused reservation on
  completion.
- Pagination never auto-follows. A tool returns one page plus a `next_cursor`; the agent
  spends another call deliberately.

| Tool | `min_cost` | Notes |
|---|---|---|
| `user_info`, `article_metadata`, `tag_info`, `budget_remaining` | 1 / 1 / 1 / **0** | single fetch; budget read is local |
| `user_articles`, `publication_articles`, `tag_latest`, `search_*` | 1 | one page; `next_cursor` returned |
| `article_content` | 1 | requires `include_full_text=True` |
| `article_responses` | 1 | one page only |

**Budget error payload** — `BudgetExhaustedError`, surfaced as an MCP error with
structured content:

```json
{
  "error": "budget_exhausted",
  "remaining_calls": 0,
  "requested_calls": 2,
  "period": "2026-09",
  "resets_at": "2026-10-01T00:00:00Z",
  "retryable": false,
  "cached_alternatives": ["user_info", "article_metadata"]
}
```

`cached_alternatives` lists tool names that can serve this request from cache at zero
cost. `retryable: false` — a caller must not retry into a hard cap.

**Content policy — corrected.** Revision 1 said full text is "never auto-persisted to
Dhara" while also mandating a Dhara-backed persistent cache. Those are the same storage;
the policy was incoherent. The rule now distinguishes fetch, cache, and return:

1. `include_full_text` defaults to **`False`**. Explicitly stated, because an unstated
   default is no control.
2. Full text is cached under a **separate key prefix**
   `medium2:v1:content:<article_id>` with its own TTL and byte cap.
3. **Return is gated independently of cache state.** A call without
   `include_full_text=True` never receives full text, cache hit or not. This is what
   revision 1 got wrong — the flag gated the fetch but not the return path, so one
   opt-in opened the gate permanently for that article.
4. `excerpt_max_chars` default **`500`**, hard-capped at `2000`. An unbounded "excerpt"
   is the article.
5. Akosha embedding and Dhara long-term persistence beyond the content cache require
   `allow_content_export=True` in settings, default `False`, independent of the per-call
   flag.
6. Recorded as `.claude/decisions/medium-content-policy.md`, structured as: context (the
   mediumapi.com restriction verbatim), the five rules above, and the enforcement point
   for each.

**README correction is a deliverable.** The four capability bullets stay — they are
achievable (§4.2) — but the README must state that the source is the unofficial medium2
API via RapidAPI, that the official API is retired, that a RapidAPI key is required, and
what the tier limits are.

### 6.3 scapy-mcp — port 3056

**Capture: live in v1, degrading to `capability_unavailable`.** `AsyncSniffer` on a
dedicated sized executor (§5.7). Startup probes `/dev/bpf*`; if unreachable, logs at
warning and marks the `capture` feed unavailable — an **optional** feed, so `/readyz`
stays 200 (§5.5). Sessions are bounded by `capture_packet_cap` (default `10_000`) and
`capture_duration_cap_seconds` (default `60`).

**Emission controls, rebuilt for the right layer.** Revision 1 specified a destination
CIDR allowlist, which cannot see an ARP frame — it has no IP layer. ARP spoofing and
IPv6 ND poisoning, the canonical scapy attacks, routed straight around it. Controls are
now layer-appropriate:

| Control | Default | Scope |
|---|---|---|
| `transmit_enabled` | `False` | master switch; `full` profile only (§5.6) |
| `transmit_allow_l3_cidrs` | `[]` | IPv4 **and** IPv6 CIDRs, parsed via `ipaddress.ip_network`. A packet whose destination family has no allowlist entry is **denied**, never skipped. |
| `transmit_allow_l2` | `False` | separate switch for any frame with no IP layer — ARP, ND, raw Ethernet, 802.11 |
| `transmit_allow_broadcast` | `False` | broadcast/multicast L2 and L3 destinations, independent of CIDR match |
| `transmit_max_pps` | `10` | rate cap |
| `transmit_max_per_session` | `100` | absolute cap |
| `transmit_max_probe_targets` | `16` | bounds `sr1`/`srp` fan-out |

`send`/`sendp`/`sr1`/`srp` are **not** one class. `sendp` is L2 and needs
`transmit_allow_l2`. `sr1`/`srp` are bidirectional probes where "packets per second" is
the wrong unit — one `srp` can scan 65535 ports — so they are additionally bounded by
`transmit_max_probe_targets`.

**`wrpcap` is a staging primitive, not a safe one.** Revision 1 classified pcap write as
"no privileges → safe." But craft + `write_pcap` produces a complete attack artifact
that `tcpreplay` emits in one command; only the final wire step was gated. Therefore:

- `write_pcap` refuses paths outside `pcap_write_dir` (default a temp dir under the
  server's runtime path), preventing writes to shared or auto-replayed locations.
- Writing a packet that `transmit` would refuse emits a structured warning naming the
  refusing control, so staging an otherwise-blocked frame is visible in logs.
- The security model is documented as *"emission is gated; authoring is observable"* —
  an honest boundary rather than a false one.

**Tools:**

| Tool | Inputs | Feed | Privileges |
|---|---|---|---|
| `craft_packet` | `layers: list[LayerSpec]` | `craft` | none |
| `dissect_bytes` | `data: str` (base64), `link_type: str = "EN10MB"` | `dissect` | none |
| `read_pcap` | `path: str`, `limit: int = 100`, `offset: int = 0` | `pcap` | none |
| `write_pcap` | `filename: str`, `packets: list[PacketSpec]` | `pcap` | none |
| `capture_start` / `capture_stop` / `capture_read` | `iface`, `bpf_filter`, `packet_cap`, `duration_cap` | `capture` | `/dev/bpf*` |
| `transmit_packet` | `packet: PacketSpec`, `iface: str`, `count: int = 1` | `transmit` | all controls above |

`LayerSpec` is a discriminated pydantic union over supported layers (`Ether`, `ARP`,
`IP`, `IPv6`, `TCP`, `UDP`, `ICMP`, `DNS`, `Raw`) — not a free-form dict, so no `Any`
enters a tool input.

**Fixtures**, enumerated so they need not be invented. Each ≤ 64 KiB, in
`tests/fixtures/`, with a sibling `<name>.provenance.json`:

| Fixture | Contents |
|---|---|
| `http_get.pcap` | TCP/80 three-way handshake + GET + 200 |
| `dns_query.pcap` | UDP/53 query + response |
| `arp_request.pcap` | ARP who-has + is-at |
| `icmp_echo.pcap` | ICMP echo request + reply |
| `ipv6_tcp.pcap` | IPv6 + TCP/443 |
| `malformed.pcap` | truncated IP header — dissection must fail gracefully |

Generated by `scripts/gen_pcap_fixtures.py` **committed to this repo** (not borrowed
from flowscape, which would create a cross-repo dependency). Determinism: all packet and
file-header timestamps set to the fixed epoch `1700000000.000000`; no `time.time()`, no
unseeded RNG. CI regenerates and asserts byte-identity.

**e2e tests for privileged and gated tools.** `mcp-backend-wiring-discipline.md`
requires a per-tool e2e test, and `capture`/`transmit` have no upstream:

- `test_capture_e2e.py` — asserts non-empty when BPF is available; asserts a
  well-formed `capability_unavailable` response when not. Both are passes.
- `test_transmit_e2e.py` — asserts a **refusal**: with default settings, a transmit
  attempt returns a typed error naming the refusing control. The observable success is
  the denial.

______________________________________________________________________

## 7. Registry and Port Consolidation

### 7.1 Plan 0a — manifest migration

Merge all 32 `repos.yaml` entries into `settings/ecosystem.yaml`, preserving that file's
schema and its `roles:` / `coordination:` sections.

Reconciliation rules, so nothing is invented:

- `repos.yaml` carries `mcp:` (`native` / `3rd-party`); `ecosystem.yaml` gains it.
  Entries lacking it default to **`3rd-party`** for `*-mcp` repos and **omitted** for
  libraries. "Preserve verbatim" therefore means "preserve all existing fields and add
  `mcp:`" — revision 1's wording contradicted itself here.
- Where an entry exists in both files with differing `role`, `tags`, or `description`,
  **`repos.yaml` wins** — it is 4 months newer. Each override is listed in the plan.
- Entries are sorted by `name` after merge. Duplicate names are a hard error.
- **`repo_cli.py:16` is repointed** to `settings/ecosystem.yaml` (finding 4.6).
  Deprecating `repos.yaml` while a command reads it would break `mahavishnu repo diff`.
- Add the three new servers to `settings/ecosystem.yaml` **only** — not to `repos.yaml`,
  which is being deprecated in the same plan.
- `repos.yaml` gains a deprecation header; it is not deleted (§3.6).

**Exit criteria:** all four guard assertions (§7.3) pass; `mahavishnu list-repos`
returns 35 entries; `mahavishnu repo diff <path>` still works against the new path.

### 7.2 Plan 0b — port and bodai reconciliation

1. Widen the port audit beyond `settings/*.yaml` to code defaults, `.env*`, and
   `pyproject.toml`, closing the §4.9 verification limit.
1. Truth-up `portmap.yaml` against the audit: `css-mcp` 3049→3050, `spline-mcp`
   3050→3052, add `penpot-api-mcp` 3051, `mdinject` 8679, correct 8684/8685 to
   `crackerjack`, add `akosha` 3002.
1. Allocate `3054: archive-org-mcp`, `3055: medium-mcp`, `3056: scapy-mcp`; narrow the
   reserved range to `3057-3059`.
1. `bodai/config/ecosystem.yaml`: rename `druva` → `dhara` (key, `repo`,
   `start_command`).
1. **`n8n-mcp`: comment out, do not delete**, with a dated note. The directory is absent,
   but no consumer check was performed — a launchd plist or start script may reference
   it. Deletion follows a consumer audit in the same plan.
1. Add the three new components to `bodai/config/ecosystem.yaml`.
1. Decide `flowscape`, `bodai-plugins`, `peanutbutterpub`,
   `mdinject-pypi-placeholder` — register or explicitly exclude, with a reason recorded.

### 7.3 Guard test

In the style of `tests/unit/test_task_router.py::TestYAMLRoutingSync`:

1. Every `path` in `settings/ecosystem.yaml` exists on disk.
1. Every `role` value is a member of the canonical `roles:` taxonomy — revision 1's
   guard omitted this, so a typo'd role would pass silently and then match no routing
   filter.
1. No port collides across `bodai/config/portmap.yaml`, `bodai/config/ecosystem.yaml`,
   **and every `<repo>/settings/*.yaml`**. The third source is what revision 1 missed,
   and it is exactly how the 3051/3052 collision escaped review.
1. `settings/ecosystem.yaml` is a superset of `settings/repos.yaml` by `name`, **and**
   `repos.yaml`'s entry count never decreases without a matching `ecosystem.yaml`
   change — the one-directional assertion in revision 1 would not have caught a deletion
   from the legacy file.

______________________________________________________________________

## 8. Testing Strategy

| Layer | Scope | Marker |
|---|---|---|
| Unit | Models, settings precedence, request construction, budget arithmetic, allowlist logic per layer | `unit` |
| Integration | One `test_<tool>_e2e.py` per registered tool, asserting non-empty (or well-formed unavailable / refusal, §6.3) | `integration` |
| Phase 0a | Wheel contents, flat layout, registry entry | `unit` |
| Phase 0b | Live upstream proof; cassette-recorded on first run | `integration`, `requires_network` |
| Registry guard | §7.3's four assertions | `unit` |
| Refusal | Budget exhaustion; transmit denial per control | `unit` |

Project markers only. `asyncio_mode = "auto"`. Anything over 10s marked `slow`.

**The coverage gate is opt-in and currently unconfigured.** `crackerjack run`'s
`coverage_goal` defaults to `None`, and none of the three `pyproject.toml` files sets a
coverage section. Phase 0a adds it. A new repo cannot start at 89%, so each plan sets a
starting floor and ratchets — following the flowscape precedent of per-module gates
rather than one blanket number. `scapy-mcp`'s `capture` module is listed in
`[tool.coverage.run] omit` with a comment naming the privilege reason.

`medium-mcp` tests replay cassettes by default; live calls require an explicit opt-in
flag so a full-suite run cannot consume the monthly budget.

**Untrusted content.** Medium article bodies and archived Wayback pages are attacker-
controllable and flow toward an LLM. Every tool returning third-party content wraps it in
an explicit data envelope with a delimiter, marks it `untrusted: true`, and strips no
content (stripping creates false confidence). The threat is documented in
`.claude/decisions/medium-content-policy.md`: retrieved content is data, never
instructions. This is defence-in-depth, not a solved problem — which is a further reason
`transmit_enabled` defaults to `False` and sits behind the `full` profile.

______________________________________________________________________

## 9. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| medium2 is unofficial and may change without notice | medium | One client module; typed models fail loudly; cassettes detect drift on refresh |
| 150-call budget exhausted in development | high | Cache-first; cassette replay; atomic guard refuses; no retry on metered calls |
| Copyright restriction violated | medium | Return gated independently of cache; separate content keyspace; `allow_content_export` default off; decision record |
| Prompt injection via archived or Medium content | medium | Untrusted-data envelopes; transmit off by default and `full`-profile-only; documented as unsolved |
| `scapy-mcp` emits an unintended frame | low-medium | Layer-appropriate controls; L2 and broadcast switches separate; probe fan-out bounded; refusal tests |
| Attack pcap staged then replayed externally | medium | `pcap_write_dir` confinement; warning when staging a would-be-refused packet; honest boundary documented |
| Live capture unavailable | high | Optional feed → `capability_unavailable`, `/readyz` stays 200 |
| IA throttles on impolite use | medium | Concurrency cap 2, backoff, identifying User-Agent, response ceiling |
| Registry migration breaks the working 8 | medium | Guard test pre-merge; `repos.yaml` wins on conflict, overrides listed; `repo_cli` repointed |
| Removing `n8n-mcp` breaks an unknown consumer | medium | Comment out, do not delete, pending a consumer audit |
| Empty wheel published, burning 0.1.0 | medium | Phase 0a asserts wheel contents; flat layout removes the mode |

______________________________________________________________________

## 10. Decision Rule

Under scope pressure, cut in this order:

1. `scapy-mcp` `transmit` domain — **and its controls with it.** They are one unit: with
   no emission path there is nothing to gate. Revision 1 listed transmit as first-to-cut
   while also declaring its allowlist never-cut, which was incoherent.
1. `medium-mcp` `search` domain — the most call-expensive surface.
1. `archive-org-mcp` `catalog` domain — Wayback is the primary draw.

**`scapy-mcp` live capture is deliberately not on this list.** Revision 1 both shipped it
in v1 and made it cut #2, which meant paying its implementation cost to maybe throw it
away. It ships in v1 because the BPF probe and optional-feed handling are ~30 lines given
§5.5, and because offline-only duplicates what `dissect`/`pcap` already cover.

**Never cut:** Phase 0a hermetic proof, Phase 0b upstream proof, the `/readyz`
feed-state route, the registry guard test, the budget guard's atomicity.

A server is done when: Phase 0a and 0b are green; every registered tool has a passing
non-empty / unavailable / refusal e2e test; `/readyz` returns 503 on required-feed
failure and 200 otherwise; `mahavishnu list-repos | grep <name>` returns it; and
`crackerjack run` passes with the repo's configured coverage floor.

______________________________________________________________________

## 11. Open Items

1. **`medium-mcp` needs a human prerequisite before Phase 0b:** a RapidAPI account, a
   medium2 subscription (free tier suffices), and `MEDIUM_MCP_RAPIDAPI_KEY` exported.
   Plan 2's Phase 0a can complete without it; 0b blocks. If it stays unmet, Plan 2 halts
   at 0a rather than shipping unproven — Phase 0b is never waived.
1. **`scapy-mcp` live capture needs `/dev/bpf*` access** — root or a ChmodBPF-style
   helper. Not required for Phase 0a or for four of five domains.
1. **`crackerjack/settings/repos.yaml` and `mcp-common/settings/repos.yaml` exist.**
   Plan 0a's scope is **investigate and document only** — determine whether they are
   independent manifests or stale copies, and record it. Any migration is a follow-up
   plan, so Plan 0a's scope stays bounded.
1. **`.crackerjack.yaml` provenance.** Whether the three new repos need one, and its
   initial contents, is unverified. Plan 0a resolves by copying `raindropio-mcp`'s or
   documenting that none is needed.
1. **CI runner matrix.** `scapy-mcp` live capture is macOS-only; unit tests are
   portable. Whether CI is Linux-only with a macOS exemption for `capture.py`, or a
   matrix, is undecided.

______________________________________________________________________

## 12. Review Log

Revision 2 incorporates a four-lens multi-agent review on 2026-09-06. Findings
**accepted** (~40) are folded in above. Findings **rejected**, recorded so they are not
re-litigated:

| Finding | Why rejected |
|---|---|
| The `internetarchive` executor bridge can starve `AsyncSniffer` of executor slots | Different servers, different processes, different repos. The reviewer collapsed three servers into one runtime. |
| Adding `mcp:` to `ecosystem.yaml` may break consumers with `extra="forbid"` | No such consumer identified. Plan 0a's guard test covers the schema regardless. |
| Other code may assume `3050-3059` is unallocated | No such consumer identified. Speculative. |
| `mahavishnu/settings/ecosystem.yaml` "does not exist" | The path is correct; the notation was ambiguous because repo and package share a name. Fixed by the convention note at the top, not by changing the path. |
| Single-path registration doesn't guarantee tools call upstream | True but not a contradiction — the two policies were cited for different purposes, and feed-state verification covers the second. |

Findings **refined** rather than accepted verbatim:

| Finding | Refinement |
|---|---|
| "oneiric already provides retry/backoff — you're reinventing it" | `workflow.retry` is `side_effect_free=True` and returns a delay, not a retry. Correct reuse is composition inside our loop (§5.8), and its jitter is deterministic, not stochastic. |
| "`/health` must return 503 on degraded" vs "the helper always returns 200" | Resolved via the `raindropio-mcp` precedent: helper for `/health`, a second in-repo route for `/readyz` (§5.5). Modifying the shared helper stays a non-goal. |

______________________________________________________________________

## 13. Settings Appendix — every key, every default

Enumerated so no implementer invents a key name or a default. Env var is the key
uppercased with the server prefix (`ARCHIVE_ORG_MCP_`, `MEDIUM_MCP_`, `SCAPY_MCP_`).

### 13.1 Shared by all three

| Key | Type | Default |
|---|---|---|
| `tool_profile` | `Literal["full","standard","minimal"]` | `"full"` |
| `log_level` | `str` | `"INFO"` |
| `http_port` | `int \| None` | `3054` / `3055` / `3056` respectively |

### 13.2 archive-org-mcp

| Key | Type | Default |
|---|---|---|
| `cdx_base_url` | `HttpUrl` | `http://web.archive.org/cdx/search/cdx` |
| `availability_base_url` | `HttpUrl` | `https://archive.org/wayback/available` |
| `search_base_url` | `HttpUrl` | `https://archive.org/advancedsearch.php` |
| `metadata_base_url` | `HttpUrl` | `https://archive.org/metadata` |
| `concurrency_limit` | `int` (1-10) | `2` |
| `max_response_bytes` | `int` | `5_242_880` |
| `retry_max_attempts` | `int` (0-10) | `4` |
| `backoff_base_seconds` | `float` | `1.0` |
| `backoff_multiplier` | `float` (≥1) | `2.0` |
| `backoff_max_seconds` | `float` | `30.0` |
| `backoff_random_jitter` | `bool` | `True` |
| `http_timeout_seconds` | `float` | `30.0` |
| `cache_ttl_seconds` | `int` | `3600` |
| `user_agent` | `str` | `archive-org-mcp/{version} (+<repo url>)` |

### 13.3 medium-mcp

| Key | Type | Default |
|---|---|---|
| `rapidapi_base_url` | `HttpUrl` | `https://medium2.p.rapidapi.com` |
| `rapidapi_key` | `SecretStr` | *(required; env only)* |
| `monthly_budget` | `int` | `150` |
| `budget_reserve_headroom` | `int` | `5` |
| `retry_max_attempts` | `int` | `1` *(no retry — metered)* |
| `http_timeout_seconds` | `float` | `30.0` |
| `dhara_namespace` | `str` | `"medium_mcp"` |
| `dhara_required` | `bool` | `True` *(refuse metered calls if unreachable)* |
| `cache_max_entries` | `int` | `10_000` |
| `cache_max_content_bytes` | `int` | `52_428_800` |
| `cache_ttl_user_info` | `int` | `86_400` |
| `cache_ttl_user_articles` | `int` | `3_600` |
| `cache_ttl_article_metadata` | `int` | `604_800` |
| `cache_ttl_article_content` | `int` | `2_592_000` |
| `cache_ttl_search` | `int` | `1_800` |
| `cache_ttl_tag` | `int` | `21_600` |
| `coalesce_window_seconds` | `float` | `5.0` |
| `excerpt_max_chars` | `int` (≤2000) | `500` |
| `allow_content_export` | `bool` | `False` |

### 13.4 scapy-mcp

| Key | Type | Default |
|---|---|---|
| `default_iface` | `str \| None` | `None` *(scapy default)* |
| `capture_packet_cap` | `int` | `10_000` |
| `capture_duration_cap_seconds` | `int` | `60` |
| `capture_default_bpf_filter` | `str \| None` | `None` |
| `capture_executor_workers` | `int` | `2` |
| `pcap_write_dir` | `Path` | `<runtime_dir>/pcap-staging` |
| `pcap_read_max_bytes` | `int` | `52_428_800` |
| `transmit_enabled` | `bool` | `False` |
| `transmit_allow_l3_cidrs` | `list[str]` | `[]` |
| `transmit_allow_l2` | `bool` | `False` |
| `transmit_allow_broadcast` | `bool` | `False` |
| `transmit_max_pps` | `int` | `10` |
| `transmit_max_per_session` | `int` | `100` |
| `transmit_max_probe_targets` | `int` | `16` |

Every `transmit_*` default is the closed position. A fresh install cannot emit a frame.

______________________________________________________________________

## References

- `docs/plans/TEMPLATE.md` — Integration Contract structure
- `.claude/decisions/wire-up-contract.md` — plan-time integration policy
- `.claude/decisions/mcp-backend-wiring-discipline.md` — runtime feed-state policy
- `docs/superpowers/specs/2026-08-31-flowscape-design.md` — per-module coverage gates,
  BPF privilege constraint
- `raindropio-mcp/raindropio_mcp/server.py` — profile dispatch, health routes,
  sync-async bridge precedent
- `mcp_common/{bootstrap,baseline_tools,health,security}.py`,
  `mcp_common/tools/dispatch.py` — the APIs in finding 4.10
- `oneiric/oneiric/actions/workflow.py` — `workflow.retry`
- [Medium Help Center — API/Importing](https://help.medium.com/hc/en-us/articles/213480228-API-Importing)
- [mediumapi.com](https://mediumapi.com/) / [docs.mediumapi.com](https://docs.mediumapi.com/)
- [Internet Archive APIs](https://archive.org/developers/apis)
- [Wayback CDX Server API](https://archive.org/developers/wayback-cdx-server-api)
