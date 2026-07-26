---
date: 2026-07-25
last_reviewed: 2026-07-25
superseded_by: null
topic: mcp-common-http-health-route-helper
status: draft
role: implementation
---

# mcp-common `register_http_health_route` Helper — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Goal:** Add a single, standardized HTTP `/health` route helper to `mcp-common` and migrate all 16 Bodai `*-mcp` repos from their ad-hoc `@mcp.custom_route("/health")` implementations to the new helper. Unblocks the launchd `launch_with_healthcheck.sh` wrapper, fixes the spline-mcp zero-`/health` gap, and brings consistency to the existing fragmented responses across the other repos.
>
> **Architecture:** New function `register_http_health_route(mcp, *, service_name, version, extra_components=None)` in `mcp-common/mcp_common/health.py` registers a `@mcp.custom_route("/health", methods=["GET"])` whose handler returns a Starlette `JSONResponse` of shape `{status, service, version, components}`. Repos call it once during server bootstrap in place of their hand-rolled route. Helper coexists with the existing `register_health_tools` (MCP-protocol tools) and the two have non-overlapping responsibilities.
>
> **Tech Stack:** Python 3.13, FastMCP (Starlette underneath), mcp-common, Pydantic v2, pytest.

## Context

The Bodai ecosystem runs 16 `*-mcp` servers (css-mcp, graphics-mcp, splashstand, langsmith-mcp, etc.) under `launchd` supervision. The wrapper script `~/.local/state/mcp/scripts/launch_with_healthcheck.sh` polls an HTTP `GET /health` to confirm the server is ready before it exits; if the server never answers 200 within the timeout, launchd will retry, thrash the plist, and leave the ecosystem in a known-bad state. Each `*-mcp` server must therefore expose a stable, machine-parseable `/health` route.

Today, every repo rolls its own. css-mcp just landed its `/health` route in commit `cc016ec` (2026-07-25) for the launchd wrapper — that commit is the canonical shape we want to generalize: `{"status": "ok", "service": "...", "version": "..."}`. But 13 other repos implement the same idea with diverging JSON keys, missing version strings, or duplicate `/healthz` aliases, and `spline-mcp` has no `/health` route at all.

The shared `mcp-common` library already exposes `register_health_tools(mcp, ...)` for the MCP-protocol health endpoint (a tool registered with the JSON-RPC stream), but it intentionally does **not** register an HTTP route. The HTTP layer is a separate concern — and that's the gap this plan closes.

This plan is one of two follow-ups filed alongside the re-anchored 2026-07-13 MCPBase migration plan. It is narrowly scoped to HTTP `/health` standardization only.

## Current state (audit snapshot, 2026-07-25)

| Repo | HTTP `/health` | Shape | Notes |
|---|---|---|---|
| css-mcp | yes (commit `cc016ec`) | `{status, service, version}` | canonical pattern |
| graphics-mcp | yes | ad-hoc | keys drift from css-mcp |
| splashstand | yes | ad-hoc | missing `version` field |
| langsmith-mcp | yes | ad-hoc | ad-hoc JSON, inconsistent keys |
| mailgun-mcp | yes (verify) | ad-hoc | MCPBaseSettings already migrated; verify `@mcp.custom_route("/health")` still present |
| porkbun-domain-mcp | yes | ad-hoc | keys drift |
| porkbun-dns-mcp | yes | ad-hoc | keys drift |
| opera-cloud-mcp | yes | ad-hoc | ad-hoc JSON |
| neo4j-mcp | yes | ad-hoc | ad-hoc JSON |
| synxis-crs-mcp | yes | ad-hoc | ad-hoc JSON |
| synxis-pms-mcp | yes | ad-hoc | ad-hoc JSON |
| unifi-mcp | yes | ad-hoc | ad-hoc JSON |
| penpot-api-mcp | yes | ad-hoc | ad-hoc JSON |
| raindropio-mcp | yes | ad-hoc | ad-hoc JSON |
| excalidraw-mcp | yes + `/healthz` | ad-hoc | extra alias needs reconciling |
| spline-mcp | **none** | n/a | no `/health` endpoint — gap |

**Totals:** 14 of 16 repos have ad-hoc `@mcp.custom_route("/health")` calls; 1 has zero; 1 has a duplicate `/healthz` alias that should be left alone or consolidated under the helper.

The `launchd` wrapper does not care which repo it's polling — it only cares that `GET /health` returns HTTP 200 with parseable JSON. We standardize on the css-mcp shape so launchd, dashboards, and ad-hoc `curl` checks all converge.

## Proposed helper

Add the following to `mcp-common/mcp_common/health.py` (sitting alongside the existing `register_health_tools`):

```python
def register_http_health_route(
    mcp: "FastMCP",
    *,
    service_name: str,
    version: str,
    extra_components: list[dict[str, Any]] | None = None,
) -> None:
    """Register an HTTP /health route on the FastMCP server.

    Returns a JSON response: {status: "ok", service: <service_name>, version: <version>, components: [...]}

    This is the HTTP counterpart to register_health_tools. Use this for
    launchd wrappers and orchestrators that need a plain HTTP GET to
    confirm server readiness. Use register_health_tools for MCP-protocol
    health endpoints.

    Args:
        mcp: The FastMCP server instance to register the route on.
        service_name: Short identifier for the service (e.g. "css-mcp").
        version: Version string for the service (semver, commit sha, or "unknown").
        extra_components: Optional list of component health dicts to merge
            into the response. Each dict is passed through verbatim.
    """
    @mcp.custom_route("/health", methods=["GET"])
    async def http_health(request: Any) -> Any:
        from starlette.responses import JSONResponse

        return JSONResponse({
            "status": "ok",
            "service": service_name,
            "version": version,
            "components": extra_components or [],
        })
```

### Design notes

- **`Any` is avoided** in the public surface except where Starlette's own typing forces it. `request: Any` and the handler return type are constrained by `mcp.custom_route`'s decorator, which is upstream FastMCP — that matches the existing style in `mcp-common/mcp_common/health.py`.
- **`@mcp.custom_route("/health", methods=["GET"])`** matches the css-mcp pattern (commit `cc016ec`) and the convention used by every other repo's ad-hoc implementation. No routing changes are needed.
- **`extra_components`** lets a repo add per-component health (e.g. `[{"name": "db", "status": "ok"}, {"name": "redis", "status": "ok"}]`) without breaking the helper's shape. Repos that don't need it pass nothing (default `None`).
- **No state checks in v1.** The helper always returns `status: "ok"`. Live-dependency health (db, redis, s3) is per-repo concern and arrives later as `extra_components` populated by a probe. If a repo needs `status: "degraded"` today, it can override the route after registration.
- **Starlette `JSONResponse` is imported lazily** inside the handler so mcp-common's import surface stays small. (mcp-common already depends on FastMCP; Starlette is a transitive dep.)
- **`register_health_tools` is untouched.** The new helper sits next to it. MCP-protocol vs HTTP are different concerns; one does not deprecate the other.

### Per-repo integration

In every `*-mcp` server's bootstrap (typically `server.py` or `<service>/__main__.py`), replace:

```python
@mcp.custom_route("/health", methods=["GET"])
async def health(request):
    from starlette.responses import JSONResponse
    return JSONResponse({"status": "ok", "service": "<name>", "version": "<v>"})
```

with:

```python
from mcp_common.health import register_http_health_route

register_http_health_route(
    mcp,
    service_name="<name>",
    version="<v>",
    extra_components=[],  # or per-component probes
)
```

For `excalidraw-mcp`, drop the `/healthz` alias (it was ad-hoc; nothing depends on it). For `spline-mcp`, this PR is what gives it a `/health` route for the first time.

## Acceptance criteria

The plan is **done** when:

- [ ] `register_http_health_route` is added to `mcp-common/mcp_common/health.py` with the signature above and a docstring that names `register_health_tools` as the MCP-protocol counterpart.
- [ ] `mcp-common` version bumped per Oneiric convention (whatever bump level the maintainer chooses — usually patch or minor).
- [ ] Tests added in `mcp-common/tests/test_http_health_route.py` covering:
  - [ ] Route registration: `GET /health` returns 200 on a FastMCP instance.
  - [ ] JSON shape: response body parses as JSON with keys `status`, `service`, `version`, `components`.
  - [ ] `status` is `"ok"`, `service` echoes `service_name`, `version` echoes `version`.
  - [ ] `components` defaults to `[]` when `extra_components=None`.
  - [ ] `components` round-trips `extra_components` when provided (verify by `[{...}, {...}]`).
  - [ ] Response content type is `application/json`.
- [ ] All 14 repos with ad-hoc `@mcp.custom_route("/health")` (graphics-mcp, splashstand, langsmith-mcp, porkbun-domain-mcp, porkbun-dns-mcp, opera-cloud-mcp, neo4j-mcp, synxis-crs-mcp, synxis-pms-mcp, unifi-mcp, penpot-api-mcp, raindropio-mcp, excalidraw-mcp, css-mcp) replace the ad-hoc call with `register_http_health_route(...)`.
- [ ] `spline-mcp` gains a `/health` endpoint via `register_http_health_route(...)`.
- [ ] `excalidraw-mcp` loses the duplicate `/healthz` alias.
- [ ] `~/.local/state/mcp/scripts/launch_with_healthcheck.sh` continues to work against every repo's `/health` without modification.
- [ ] Per-repo validation: `curl -fsS http://127.0.0.1:<port>/health` returns the canonical JSON for each `*-mcp` server.
- [ ] All 16 repos' CI passes (ruff, mypy strict, pytest with 80% coverage).

## Out of scope

The following are **explicitly not** part of this plan:

- **MCP-protocol health endpoints** (governed by `register_health_tools`). The existing helper remains the source of truth for MCP-protocol health; standardizing the JSON shape of those tool responses is a separate plan (and not yet drafted).
- **Per-repo FastMCP pin bumps** and **MCPBaseSettings → OneiricMCPConfig migrations**. These are in [2026-07-13-mcp-server-family-mcpbase-migration.md](./2026-07-13-mcp-server-family-mcpbase-migration.md) — separate plan, separate dispatch, separate PRs.
- **Live dependency probes** (db ping, redis ping, s3 ping) wired into `components`. Repos can pass static lists or call a probe helper, but a unified probe layer is a follow-up.
- **Removing the helper's ability to coexist with `register_health_tools`.** Both stay; they answer different audiences.
- **`/healthz` alias consolidation** beyond the `excalidraw-mcp` removal called out above. Other repos don't have one.

## Sequencing

This plan ships in three waves to keep reviewable diff sizes small:

### Wave 1 — mcp-common (1 PR, ~1 hour)

1. Add `register_http_health_route` to `mcp-common/mcp_common/health.py`.
2. Add `mcp-common/tests/test_http_health_route.py` with the six test cases from the acceptance criteria.
3. Run `crackerjack run` on mcp-common until green.
4. Bump mcp-common version per Oneiric convention; tag and publish.
5. Open PR titled `feat(mcp-common): register_http_health_route helper`.

**Integration Contract (Wave 1):**
- **Triggered from:** the launchd wrapper's `launch_with_healthcheck.sh` failing to find a canonical `/health` shape across 14+ ad-hoc implementations.
- **Returns to / updates:** `mcp-common/mcp_common/health.py` gains the new helper; published mcp-common version exposes the helper to consumer repos.
- **Demonstrable by:** `python -c "from mcp_common.health import register_http_health_route; print(register_http_health_route)"` prints the function; the six test cases in `tests/test_http_health_route.py` pass.
- **Rollback signal:** any of the six test cases fail, or `crackerjack run` reports a regression; revert the Wave 1 PR.
- **Observability added:** `git log --oneline mcp-common/` shows the new helper commit; CI runs the new test file on every PR.

### Wave 2 — Per-repo replacements (16 repos, ~5 min each)

For each of the 16 `*-mcp` repos:

1. Open a worktree.
2. Bump the mcp-common pin to the new version.
3. Replace the ad-hoc `@mcp.custom_route("/health")` with `register_http_health_route(...)`.
4. For `excalidraw-mcp`, also drop the `/healthz` alias.
5. Run `crackerjack run` until green.
6. Smoke-test: `mahavishnu mcp start --service <repo>` then `curl -fsS http://127.0.0.1:<port>/health`.
7. Squash-merge to main per the pre-1.0 Bodai merge policy.

Repos that don't pin mcp-common today must add the pin. Repos that don't use mcp-common yet (rare) must adopt it as part of this PR.

**Integration Contract (Wave 2):**
- **Triggered from:** Wave 1's mcp-common release landing.
- **Returns to / updates:** each `*-mcp` repo's server bootstrap file (replacing the ad-hoc route), each repo's `pyproject.toml` (mcp-common pin bump), and `excalidraw-mcp`'s dropped `/healthz` alias.
- **Demonstrable by:** `curl -fsS http://127.0.0.1:<port>/health` returns the canonical JSON shape `{status, service, version, components}` for every repo.
- **Rollback signal:** any repo's `/health` returns non-200 or its JSON shape drifts from the canonical form; revert the per-repo PR.
- **Observability added:** `git log --oneline <repo>/` shows the per-repo migration commit; per-repo CI runs `crackerjack run` on every PR.

### Wave 3 — Validation (1 hour)

1. From a clean launchd state (`launchctl unload` every plist, then reload), confirm every `*-mcp` server passes `launch_with_healthcheck.sh` within 30 s.
2. Run a one-shot `for port in $(seq 8676 8700); do curl -fsS http://127.0.0.1:$port/health || echo "FAIL: $port"; done` against every known port and confirm no `FAIL`.
3. Update `docs/OPERATIONS.md` (or the equivalent ecosystem health doc) to note that `/health` is the canonical readiness probe.

**Integration Contract (Wave 3):**
- **Triggered from:** completion of all 16 per-repo migrations (Wave 2).
- **Returns to / updates:** `docs/OPERATIONS.md` (or equivalent) gains the canonical-readiness-probe note; the launchd wrapper script is verified working against every repo.
- **Demonstrable by:** the `for port in $(seq 8676 8700); do curl -fsS http://127.0.0.1:$port/health || echo "FAIL: $port"; done` loop produces no `FAIL` lines; every `launch_with_healthcheck.sh` invocation exits 0 within 30 s.
- **Rollback signal:** any `FAIL` line in the port sweep, or any `launch_with_healthcheck.sh` timeout; identify the offending repo and revert its Wave 2 PR.
- **Observability added:** launchd plist logs already capture `/health` probe outcomes; no new telemetry needed in v1.

## Estimate

| Wave | Time | Notes |
|---|---|---|
| 1 — mcp-common helper + tests | 1 hour | Includes PR review + version bump |
| 2 — 16 per-repo replacements | 5 min × 16 ≈ 1.5 hours | Each PR is a one-liner + pin bump |
| 3 — Validation + docs | 1 hour | Includes launchd end-to-end check |
| **Total** | **~3.5 hours** | Roughly 2 hours of focused work + 1.5 hours of PR review / CI waits |

The task statement's "~2 hours total" estimate is achievable if Wave 2 is dispatched in parallel (each repo PR is independent and trivially small).

## Risks & mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| A repo's existing `/health` carries business logic (component probes) that the helper doesn't replicate | Medium | Pass that logic through `extra_components`; if richer behavior is needed, file a follow-up plan to extend the helper |
| `mcp.custom_route` decorator typing breaks under mypy strict | Low | Match the existing `register_health_tools` typing patterns; use `Any` only where Starlette forces it |
| Per-repo PRs collide with the parallel MCPBase migration PRs | Medium | Sequence Wave 2 to start after Wave 1 lands; do not run both PRs in the same repo concurrently |
| Launchd wrapper breaks on a repo that doesn't pin mcp-common | Low | Wave 2 includes the pin bump; document the new requirement in the PR description |
| Starlette `JSONResponse` import surface changes | Very low | Lazy-import inside the handler; helper still works if Starlette is removed upstream |

## Integration contract (per project convention)

Every phase deliverable must answer:

- **Triggered from**: server bootstrap (`server.py` / `<service>/__main__.py`).
- **Returns to / updates**: the FastMCP server's HTTP router (adds `/health`); callers receive no return value.
- **Demonstrable by**: `curl -fsS http://127.0.0.1:<port>/health` returns `{"status": "ok", ...}` with HTTP 200; `launch_with_healthcheck.sh` exits 0 within its timeout.
- **Rollback signal**: any repo's `/health` returns non-200, or its JSON shape drifts from the canonical form; in either case revert the per-repo PR.
- **Observability added**: existing launchd plist logs already capture `/health` probe outcomes — no new telemetry needed in v1.

## Reference patterns

- **Canonical shape**: css-mcp commit `cc016ec` (2026-07-25).
- **MCP-protocol counterpart**: `mcp-common/mcp_common/health.py::register_health_tools`.
- **Launchd wrapper**: `~/.local/state/mcp/scripts/launch_with_healthcheck.sh`.
- **Sibling plan (out of scope here)**: [2026-07-13-mcp-server-family-mcpbase-migration.md](./2026-07-13-mcp-server-family-mcpbase-migration.md).

## Cross-Plan Sequencing — mcp-common release window

This plan's Wave 2 per-repo bumps depend on Wave 1's mcp-common release landing first; consumer repos pin to a baseline that doesn't yet have `register_http_health_route` if Wave 1 is skipped. The pre-1.0 Bodai merge policy (squash-merge to main) keeps this sequencing observable in the repo log. Wave 2 PRs run after Wave 1's mcp-common release tag, in parallel with the per-repo migrations from [2026-07-13-mcp-server-family-mcpbase-migration.md](./2026-07-13-mcp-server-family-mcpbase-migration.md) — bundle the helper adoption + MCPBaseSettings migration when they touch the same repo.

## Files touched

- **mcp-common**: `mcp_common/health.py` (add helper), `tests/test_http_health_route.py` (new).
- **Per-repo**: each `*-mcp` repo's server bootstrap file plus its `pyproject.toml` (pin bump).
- **Docs**: `docs/OPERATIONS.md` or equivalent (Wave 3) — single line noting canonical readiness probe.
