---
status: complete
role: decision
date: 2026-09-06
last_reviewed: 2026-09-06
superseded_by: null
blocks_on: ["docs/superpowers/specs/2026-08-31-flowscape-design.md"]
decision_date: 2026-09-06
topic: mcp-enrichment-posture
related:
  - "docs/superpowers/plans/2026-08-31-flowscape.md"
  - "docs/superpowers/specs/2026-08-31-flowscape-design.md"
  - "docs/superpowers/plans/2026-09-06-scapy-mcp.md"
  - "docs/adr/0016-multi-agent-review.md"
  - "docs/feature-tracking/scapy-mcp-enrichment.md"
---

# ADR 0016 scapy-mcp Client-Mode Enrichment Integration

## Context

Flowscape v1 (`docs/superpowers/plans/2026-08-31-flowscape.md`) is a macOS 3D network visualization tool that ships with statistical heuristics (beaconing, port-scan) and Etherape-shaped top-talkers + conversation panels. The original plan deferred scapy-mcp integration to v2+, treating it as an "enrichment plugin for `heuristics.py` / `graph.py`".

Three forces converged in 2026-09-06 to make v1 integration the right move:

1. **Substrate readiness**: `mcp-common` ships `bootstrap_baseline_tools`, `seed_liveness_context`, `register_http_health_route` for server-side baseline. Current published version is **0.24.4** (6 minor releases headroom; no API in flight). Client-side primitives used here: `fastmcp.Client` against a streamable-HTTP endpoint (`http://scapy_mcp_host:scapy_mcp_port/mcp`), `mcp_common.testing.baseline_surface.assert_baseline_surface(url)` as a preflight assertion, and `BASELINE_TOOL_NAMES` from `mcp_common.baseline_tools` (note: `EXPECTED_BASELINE` does NOT exist as an mcp-common symbol — sibling stub-activation plans have hit the same gap; we define it locally). scapy-mcp itself is an active implementation plan (`docs/superpowers/plans/2026-09-06-scapy-mcp.md`) with port **3056** allocated by the `2026-09-06-port-bodai-reconciliation.md` plan.

2. **Build-time scapy already exists**: `scripts/gen_pcap_fixtures.py` uses scapy as a build-time dep to generate deterministic test pcaps. Switching from static fixtures to runtime scapy-mcp enrichment is a feature gain, not just a refactor — Flowscape gets *fresh* PCAP analysis (top-N ranking, threat score enrichment) instead of only the static fixture corpus.

3. **Regulatory posture clarification**: Flowscape's spec already gated `mcp.enabled = true` (server-mode: Flowscape *serving* an MCP surface) behind ADR 0007 + DPIA + `CONTRIBUTING.md` updates. The client-mode counterpart (Flowscape *calling* scapy-mcp) is a different posture: it's a dependency, not an exposure. The wire-format no-payload guarantee and consent gate are unchanged because the enrichment hook receives `(FlowEdge | HeuristicEvent)` metadata, never packet bytes.

This ADR records the decision to integrate scapy-mcp as a *client-mode* enrichment provider in Flowscape v1, decoupled from the server-mode regulatory gate.

## Decision

**Flowscape v1 ships a scapy-mcp-backed `EnrichmentHook` as a client-side MCP caller.** Server-mode (`flowscape mcp` exposing tools) remains v1.x-gated.

### Posture table

| Surface | Direction | Regulatory posture | v1 status |
|---|---|---|---|
| **Flowscape serving an MCP surface** (`flowscape mcp` exposing tools) | Inbound: client → Flowscape | Regulated *exposure* event. Requires ADR 0007 + DPIA (Art. 35) + `CONTRIBUTING.md` update before `mcp.enabled = true`. | **v1.x gated** (still off; deferred to Phase 7b.2 of the Flowscape plan). |
| **Flowscape calling scapy-mcp** (enrichment provider) | Outbound: Flowscape → scapy-mcp | Treated as a *dependency*, not an exposure. The legal exposure surface is unchanged from a non-MCP `pip install scapy`; Flowscape never exposes packet data to a third party. | **v1 in scope**, opt-in via `enrichment.scapy_mcp_enabled = false` default. |

### Why this distinction is principled

- **Exposure vs. dependency**: Flowscape serving an MCP surface changes the *trust boundary* — anyone with MCP credentials can drive Flowscape. Flowscape calling scapy-mcp does not; the trust boundary is the local Unix socket or localhost TCP connection to scapy-mcp running on the same machine, under the same user.
- **No third-party data egress**: the enrichment hook receives `(FlowEdge, HeuristicEvent)` metadata. The wire-format no-payload guarantee (`payload_sha256_prefix` is the only payload-derived field allowed; CI lint + runtime Oneiric log filter) is unchanged. scapy-mcp itself must respect its own safety controls (master kill-switch `transmit_enabled = False`, L3 CIDR allowlist, L2 allow flag, broadcast opt-in per the scapy-mcp plan §"Transmit safety model") — but those are inbound to scapy-mcp from Flowscape, not outbound from Flowscape to a third party.
- **Default-off preserves the regulatory lever**: shipping the plumbing behind `enrichment.scapy_mcp_enabled = false` default means the user affirmatively chooses to enrich. A Flowscape v1 install that never flips the flag has zero MCP code paths active. This is a meaningful posture distinction that survives any future auditor's scrutiny.

### Architecture (concrete, code-shaped)

```
src/flowscape/
├── enrichment.py            (NEW) — EnrichmentRegistry, EnrichmentHook ABC (mirrors CaptureSource)
├── enrichment_registry.py   (NEW) — module-level register_provider(name, hook) + get_provider(name); settings-driven lookup, no default() classmethod
├── graph.py                 (MODIFIED) — calls EnrichmentRegistry.get_provider(name).enrich_edge() per edge, name from EnrichmentSettings
├── heuristics.py            (MODIFIED) — detectors accept EnrichmentHook via DI for confidence boost
└── settings.py              (MODIFIED) — EnrichmentSettings nested in FlowscapeSettings (BaseModel subclass; addresses spec's BeaconingSettings BaseModel gap as a side-effect of this work)
```

The `EnrichmentHook` is an **`ABC`**, mirroring the existing `CaptureSource` ABC pattern (Flowscape plan Phase 1 line 384-396; spec A16 — `register_source(name: str, source: CaptureSource)`, lookup is `name`-driven via `CaptureSettings.default_kind`). Module-level `register_provider(name, hook)` parallels `register_source(name, source)`. **Lookup is name-driven, not singleton-driven**: `EnrichmentSettings.default_provider: str = "noop"` drives `get_provider(name)`, and the no-op default is registered automatically at module import if no other provider claims the name. **Deliberately no `EnrichmentRegistry.default()` classmethod** — that pattern silently masks wiring bugs by returning a no-op when nothing is registered; we want lookup to surface the misconfiguration loudly.

The **sole scapy-mcp entry point** for the enrichment hook is `dissect_bytes` (per the scapy-mcp plan §"Tools" — `dissect_bytes(bytes_b64) → {summary, layers, layer_count}`). The hook does **NOT** call `craft_packet`, `capture_read`, or `transmit_packet` — those are out of scope for v1 enrichment, and routing them through the hook would either (a) require payload-source code paths in scapy-mcp, or (b) trigger scapy-mcp's `full`-profile-only `transmit` surface unnecessarily. Constraining the entry point at the architecture diagram level is a structural guard against future maintainer drift.

### Settings surface (new `enrichment` block in `settings.yaml`)

```yaml
mcp:
  enabled: false                  # SERVER-MODE only (Flowscape serving an MCP surface). Gated on ADR 0007 + DPIA.
  port: 8700
enrichment:                       # CLIENT-MODE scapy-mcp enrichment. See ADR 0016. Different posture from mcp.enabled.
  scapy_mcp_enabled: false        # off by default; user opts in via `flowscape config`
  scapy_mcp_host: localhost
  scapy_mcp_port: 3056            # aligns with plans/2026-09-06-port-bodai-reconciliation.md
  default_provider: noop          # settings-driven lookup; matches CaptureSettings.default_kind pattern (spec A16)
  enrichment:
    timeout_ms: 100               # PER-TICK budget (NOT per-edge) — see Architecture note below
    retry:                        # composes with oneiric.actions.workflow.WorkflowRetryAction (not a fresh primitive)
      max_attempts: 2
      base_delay_ms: 10
      multiplier: 2.0
      max_delay_ms: 80
```

**Architecture note on the timeout budget** (closes L5 BLOCKER U-Op2 / CB-2): the v1 spec said the hook calls `enrich_edge(edge)` per `FlowEdge`, but Phase 4 capacity targets up to **5000 edges per tick**. Naive per-edge invocation with a 100ms timeout gives `5000 × 100ms = 500 seconds` of work per 100ms tick — a 5000× deficit that would block the publisher indefinitely. **The hook call is per-TICK, batched:** `EnrichmentRegistry.get_provider(name).enrich_batch(edges: list[FlowEdge]) → list[EnrichmentResult | None]` returns one batched response covering all edges in the current snapshot. The 100ms budget is the **per-tick batch budget**, which fits cleanly under the 100ms publish cadence (worst case: 100ms scapy-mcp call + 0ms overhead = 100ms tick). On timeout, the publisher drops the entire snapshot (existing 50ms backpressure threshold drops in 50ms increments; see spec §"Backpressure policy"). The per-edge interface is preserved as a thin synchronous shim for unit tests; the production call site uses the batched interface.

### Dependency group (PEP 735, optional)

A new `mcp-enrichment` group is added to `pyproject.toml`:

| Group | Deps | Justification |
|---|---|---|
| `mcp-enrichment` (optional) | `scapy-mcp`, `mcp` (Python SDK) | Enables `EnrichmentRegistry` to call scapy-mcp via MCP client. **Off by default** — user opts in via `flowscape config`. |

This keeps `pip install flowscape` lean: the scapy-mcp dependency is not pulled in unless the user explicitly enables it.

## Operational SLOs and Feed Observability

Closes L1 BLOCKER B1 (no feed-state observability) and L5 BLOCKERs B-Op1 through B-Op6. The enrichment surface is a feed per the `.claude/decisions/mcp-backend-wiring-discipline.md` policy §3 (extended to consumer-side aggregation in a v2 policy amendment — see `0016-multi-agent-review.md` CB-1 amendment request).

### Required feed observability metrics (per wiring discipline §3)

Every `EnrichmentRegistry` instance must expose:

| Metric | Type | Semantics |
|---|---|---|
| `flowscape.enrichment.entities_count` | gauge | edges (or batched-tick responses) enriched since start |
| `flowscape.enrichment.last_updated_timestamp` | gauge | wall-clock seconds of the most recent successful enrichment; alert when older than 5× polling interval |
| `flowscape.enrichment.errors_total` | counter | cumulative failures, labeled by cause: `connect`, `timeout`, `schema`, `cancel` |
| `flowscape.enrichment.cycles_total` | counter | incremented each polling cycle (per-tick batch call) |
| `flowscape.enrichment.timeout_total` | counter | subset of `errors_total{cause="timeout"}`; surfaced separately for alerting |

The no-op default provider (when `scapy_mcp_enabled = false` or no provider is registered) **emits these metrics as `0`/`now()`/`0`/`0`** — not "absent" — so the wiring-discipline audit cannot confuse "registered but disabled" with "registered and broken" (closes L1 I.B3).

### SLO targets

| SLO | Target | Measurement |
|---|---|---|
| Latency p99 of `enrich_batch(...)` | ≤ 100 ms | 1-minute rolling window |
| Error rate (non-timeout) | ≤ 1% | per 1000 batched calls |
| Availability: feed state `healthy` | ≥ 99% | per 1-minute window |
| Timeout-budget consumption | ≤ 0.5 per cycle | 5-minute rolling |

Violation of any SLO emits a `flowscape.enrichment.slo_violated` event with the relevant SLO name; `flowscape doctor --enrichment` (below) reports degraded status.

### `flowscape doctor --enrichment` output envelope (closes L1 B2 + L5 B-Op4)

```yaml
# `flowscape doctor --enrichment` — exit codes: 0=healthy, 1=degraded, 2=dead, 3=not_registered
provider: scapy-mcp                        # resolved from EnrichmentSettings.default_provider
endpoint: http://localhost:3056/mcp        # composed from scapy_mcp_host + scapy_mcp_port
reachable: true                           # TCP connect succeeded
mcp_handshake_ok: true                     # assert_baseline_surface() returned all 4 baseline tools
tools_discovered: [discover_tools, get_liveness, get_readiness, health_check_all]
latency_ms: 47                            # measured MCP roundtrip
feed_state: healthy                       # healthy | degraded | dead | not_registered
last_success_timestamp: 2026-09-06T21:48:11Z
last_error: null                          # or {cause, message, timestamp}
errors_total{connect: 0, timeout: 2, schema: 0, cancel: 1}
timeout_total: 2
uptime_seconds: 7234
enrichment_calls_total: 17301
```

The `feed_state` value flows into the `/health` aggregator (when Flowscape ships server-mode in Phase 7b.2). While `mcp.enabled = false`, the UI surfaces feed state directly via the `flowscape doctor --enrichment` invocation or the `enrichment_state` indicator on the top-talkers panel.

### Rollback thresholds (data-driven, not operator judgment)

Closes L5 BLOCKER B-Op2. The "false-positive rate on heuristic alerts jumps >5% AND no clear contributing cause" line in v1 is operator-subjective. v2 specifies:

| Trigger | Threshold | Auto-action |
|---|---|---|
| `flowscape.enrichment.timeout_total / flowscape.enrichment.cycles_total` > 0.5 sustained over 5 minutes | scapy-mcp is too slow to keep up | flip `scapy_mcp_enabled` to `false` in settings; emit alert |
| `flowscape.heuristic.false_positive_rate` > 5% over 15-minute window AND `flowscape.enrichment.errors_total` increased > 50% in same window | heuristic regression correlated with enrichment rollout | revert the enrichment plumbing (`enrichment.py` + `enrichment_registry.py` modules) — `graph.py` and `heuristics.py` retain v0.x behavior because hook defaults to no-op |
| `mahavishnu /health` enrichment feed = `dead` sustained > 10 minutes | enrichment is broken, not just slow | page on-call; require human review before re-enabling |

The "no clear contributing cause" clause is **removed** in v2 — every rollback trigger now has an automatic signal, not operator judgment.

### Cancellation semantics

Timeout enforcement uses `asyncio.wait_for(...)` with `cancel=True` (default). On client-side timeout, the underlying MCP request is cancelled; the underlying scapy-mcp task does not continue processing. Counter `flowscape.enrichment.in_flight_cancelled_total` tracks the rate of cancellations.

## Consequences

### Positive

- **Feature gain**: Flowscape v1 gets fresh PCAP analysis (top-N ranking, threat scores, beaconing confidence boosts from scapy-mcp's deterministic dissectors) instead of relying solely on the static fixture corpus.
- **Pattern lock-in**: the `EnrichmentHook` registry mirrors the proven `CaptureSource` ABC pattern. Future enrichment providers (unifi-mcp, custom in-house detectors) plug in via the same idiom.
- **De-risked MCP substrate**: shipping scapy-mcp enrichment exercises the `mcp-common` baseline tools contract (`discover_tools`, `get_liveness`, `get_readiness`, `health_check_all`), the `full` tool profile gating, and the registry/port plumbing — all of which other 2026-09-06 sibling plans (archive-org-mcp, medium-mcp) inherit.
- **Parallel implementability**: scapy-mcp's server work and Flowscape's client work proceed on independent timelines, joined only by the registry + port allocation plans.
- **Cleaner v2 hand-off**: when Flowscape eventually wires unifi-mcp into `heuristics.py` enrichment plugins (currently v2+), having a stable `EnrichmentHook` contract in place makes the integration story obvious instead of speculative.

### Negative

- **Two posture classes to explain**: server-mode and client-mode MCP both touch the codebase, but require different regulatory handling. Documentation must clearly distinguish them (this ADR is the source of truth). Note: the L4 GDPR review (see `0016-multi-agent-review.md`) flagged that this ADR's "exposure vs. dependency" framing is the wrong axis for GDPR — the correct framing is "controller vs. processor". The v2 revision adds a "Scope" section below that scopes the ADR to pre-1.0 internal use only and explicitly defers EU regulatory coverage to v1.x. Full reframe to controller/processor language, plus the `docs/legal/gdpr-posture.md` document, is deferred to a v3 revision.
- **Failure surface expansion**: scapy-mcp being unreachable (port 3056 closed, package not installed, version mismatch) means enrichment fails the per-tick batch call. Per v2 design, timeout drops the entire snapshot via the publisher's existing 50ms backpressure policy — the user sees "enrichment unavailable" in the UI and the feed-state metrics surface in `flowscape doctor --enrichment`. UX must surface the state.
- **Latency budget**: `enrichment.timeout_ms = 100` is a per-tick batch budget (NOT per-edge; the v1 framing was wrong — see L5 BLOCKER U-Op2 in `0016-multi-agent-review.md`). The hook calls `enrich_batch(edges)` once per publish tick; 100ms is comfortably below the 100ms tick interval. Worst case at Phase 4 capacity (5000 edges): one batched MCP call, ≤ 100ms, fits within the tick.
- **Test surface grows**: enrichment introduces a new dependency boundary in unit tests. Mocking scapy-mcp via FastMCP in-memory test server is required for hermetic test runs. The contract assertion (`assert_baseline_surface(url)`) is the canonical preflight test fixture.

### Scope (closes L4 BLOCKERs in part — full reframe deferred to v3)

This ADR captures the **pre-1.0 internal-use integration** of scapy-mcp enrichment in Flowscape. EU regulatory coverage (GDPR Articles 4-35, controller/processor reframing, DPIA scoping) is **explicitly out of scope** for v1 and v1.x — it is deferred to a v3 revision. Rationale: recent project memory `feedback-bodai-pre-1.0-merge-policy: all Bodai components merge directly to main pre-1.0; no PRs` means Flowscape v1 has no public release; the GDPR controller/processor question applies to public releases, not to internal Bodai infrastructure. When Flowscape ships a v1.0 public release, v3 of this ADR must (a) create `docs/legal/gdpar-posture.md`, (b) reframe posture as controller/processor relationship, (c) commit to Article 35 DPIA coverage, (d) commit to a fresh consent gate when the user first flips `scapy_mcp_enabled = true`.

### Neutral

- **No change to the wire-format no-payload guarantee**: the enrichment hook only receives `(FlowEdge, HeuristicEvent)` metadata. Packet bytes never reach the hook.
- **No change to the consent gate**: scapy-mcp enrichment does not change what data is captured or how; it changes how captured data is *annotated*.
- **No change to the launchd helper scope**: `/dev/bpf*` ACL setup is unchanged.

## Alternatives Considered

### Alternative A: Keep scapy-mcp as v2+ (the original decision)

**Rejected.** Two costs became evident in 2026-09-06:

1. Substrate readiness is no longer a blocker — `mcp-common` is stable and 6 minor releases ahead of the requirement, scapy-mcp is an active implementation plan with port allocation ready.
2. Build-time scapy for fixture generation is already in the codebase. The marginal cost of going from "static fixtures via scapy" to "runtime enrichment via scapy-mcp" is lower than the cost of two separate code paths (build-time scapy for fixtures, then re-implementing the same logic via scapy-mcp in v2).

### Alternative B: Make scapy-mcp enrichment server-mode too

**Rejected.** Server-mode (Flowscape *serving* an MCP surface) is the posture that requires ADR 0007 + DPIA + `CONTRIBUTING.md` updates. Doing both client-mode and server-mode in v1 conflates two regulatory postures and triggers a full DPIA review for v1, which the user explicitly wants to avoid.

### Alternative C: Embed scapy directly (skip MCP)

**Rejected.** Embedding scapy directly would:
- Bypass the `mcp-common` baseline tools contract for the v1 dependency surface.
- Bypass scapy-mcp's safety controls (master kill-switch, L3 CIDR allowlist, L2 allow flag, broadcast opt-in).
- Couple Flowscape's build deps to scapy-as-library instead of scapy-mcp-as-service.
- Lose the future plug-in surface (unifi-mcp-in-v2 won't have a registry to plug into).

The wire-format no-payload guarantee would still hold, but the regulatory and operational posture would be *worse* than client-mode MCP — directly embedding a library is less auditable than calling a service with documented safety controls.

### Alternative D: Defer to v1.1

**Considered.** v1.1 already has a backlog (GPU compute layout, triple-buffer infrastructure, top-N-churn heuristic). Adding scapy-mcp integration to that pile mixes two concerns: (a) the architecture for enrichment hooks, and (b) the substrate readiness. Doing the architecture now (v1) lets v1.1 ship the scapy-mcp *integration* (not the architecture) as a smaller, more focused increment.

## Rollback Signal

Data-driven thresholds (closes L5 BLOCKER B-Op2; supersedes the v1 operator-judgment clause). See **§Operational SLOs and Feed Observability → Rollback thresholds** for the full table. Summary:

| Trigger | Threshold | Auto-action |
|---|---|---|
| Slow provider | `timeout_total / cycles_total` > 0.5 over 5 min | flip `scapy_mcp_enabled = false`; alert |
| Heuristic regression | `false_positive_rate` > 5% AND `errors_total` increased > 50% in 15-min window | revert `enrichment.py` + `enrichment_registry.py` |
| Broken feed | `feed_state = dead` sustained > 10 min | page on-call; require human review |

**GDPR-specific rollback** (if a regulator or auditor reads the default-off posture as deceptive even under pre-1.0 scope):

1. Add explicit `flowscape doctor --enrichment` output to the first-launch consent modal.
2. Update README to call out the default-off posture and the pre-1.0 internal-use scope.
3. Defer EU coverage by removing the feature entirely until the v3 GDPR reframe lands — this is a stronger rollback than flipping the default.

## Open Questions

1. **Multi-host scapy-mcp**: what happens when scapy-mcp is on a remote host? Currently `scapy_mcp_host = localhost` is the default. Remote requires explicit user opt-in AND mcp-common's authentication primitives (not yet designed). Closely tied to v3 GDPR reframe (remote hosting changes the controller/processor analysis).
2. **Bidirectional enrichment**: should Flowscape expose its own heuristics back to scapy-mcp as MCP tools (server-mode for THIS specific surface)? Out of scope for this ADR; revisit if unifi-mcp or similar wants Flowscape's heuristic events.
3. **Wire-format regression detection** (L5 BLOCKER B-Op6, partial close): the runtime wire-format guard is specified (regex-based field-name filter over `enrich_batch()` return values; emit WARN + increment `flowscape.enrichment.wire_format_violation_total` on hit) but the implementation is deferred to v3 alongside the proto type definitions (`GraphEdge`, `HeuristicEvent`). Without those types, the merge step itself is a phantom — see §Deferred to v3 below.

### `EnrichmentMetadata` shape (resolves v1 Open Question 1 in part)

Closes L2 BLOCKER B1's input-side concern by pinning the contract for what the hook returns. `EnrichmentMetadata` is a Pydantic model with `model_config = ConfigDict(extra="forbid")` and an explicit allow-list of fields:

```python
from pydantic import BaseModel, ConfigDict

class EnrichmentMetadata(BaseModel):
    """Returned by EnrichmentHook.enrich_batch(). Forbid extras so a future
    scapy-mcp schema addition cannot silently widen the wire-format surface.
    """
    model_config = ConfigDict(extra="forbid")
    top_n_rank: int | None = None      # edge's rank in the top-N hosts by bytes_in_window
    threat_score: float | None = None  # 0.0-1.0 scapy-mcp threat heuristic
    confidence_boost: float | None = None  # -1.0 to +1.0; heuristic detector applies this
```

The `extra="forbid"` setting is a structural guard against the wire-format regression class (CB-5 / L5 U-Op3): if scapy-mcp adds a new field to its response, Pydantic raises a validation error rather than silently merging it into `FlowEdge`. The runtime guard (regex-based field-name filter, deferred to v3) provides a second layer.

## Deferred to v3

The following items require work that exceeds this ADR's scope. They are tracked in `docs/feature-tracking/scapy-mcp-enrichment.md` and the companion review file:

- **CB-3** (full GDPR reframe): see §Scope above. Creates `docs/legal/gdpr-posture.md`, reframes posture as controller/processor, commits to Article 35 DPIA scoping. Deferred to v3 because pre-1.0 internal use is not GDPR-triggered.
- **CB-4** (phantom APIs in spec): spec lines 110 + 503 reference `oneiric.config.load_app_settings` and `MCPServerSettings.model_config_section()`, neither of which exists. Spec edits replace with `from oneiric.core.config import load_settings` and explicit `BaseModel` subclassing. Spec is a sibling repo to this ADR — edits live in `docs/superpowers/specs/2026-08-31-flowscape-design.md`.
- **CB-5** (phantom proto types): `GraphEdge` and `HeuristicEvent` are referenced by plan §"MCP integration scope" but don't exist in `proto/flowscape.proto` (which itself doesn't exist yet — Phase 0b of the Flowscape plan). Deferred until Phase 0b lands.
- **L5 B-Op6 wire-format guard**: the regex-based field-name filter over hook return values is specified here but the implementation requires the proto types from CB-5.

## Cross-References

- **Flowscape plan** (`docs/superpowers/plans/2026-08-31-flowscape.md`) — revision 5 (2026-09-06) added §"MCP integration scope" section referencing this ADR
- **Flowscape spec** (`docs/superpowers/specs/2026-08-31-flowscape-design.md`) — revision 3 (2026-09-06) updated subsystems table, PEP 735 dep groups, out-of-scope table, and MCP activation regulatory event
- **scapy-mcp plan** (`docs/superpowers/plans/2026-09-06-scapy-mcp.md`) — the dependent server; ships port 3056 + `scapy_mcp_enabled` consumer semantics
- **Port allocation** (`docs/superpowers/plans/2026-09-06-port-bodai-reconciliation.md`) — port 3056 is allocated to scapy-mcp via this plan
- **Registry** (`docs/superpowers/plans/2026-09-06-registry-manifest-migration.md`) — registers scapy-mcp in `settings/ecosystem.yaml`
- **Server-mode MCP gate** (ADR 0007) — separate posture, not superseded by this ADR

## Review History

- 2026-09-06 — Drafted by Claude (v1, proposed).
- 2026-09-06 — **6-agent multi-agent review complete** (2 rounds, non-overlapping lenses per `docs/adr/015-multi-agent-review.md` precedent). See companion file `docs/adr/0016-multi-agent-review.md`.
  - **Verdict:** not ratifiable as-is. 25 BLOCKERs across 6 lenses (L1 wiring discipline, L2 wire-format, L3 Oneiric integration, L4 GDPR, L5 operational readiness, L6 cross-ADR).
  - **Status:** flipped to `complete` with **structural revisions deferred to v2** per the "deliberate exception" pattern documented in the review companion. The decision the ADR captures (client-mode enrichment posture, default-off, `mcp-enrichment` PEP 735 dep group, no-payload guarantee preservation) is sound; the implementation refinements (observability metrics, SLOs, timeout batching, Oneiric primitives, spec/proto fixes, GDPR posture document) are tracked in `docs/feature-tracking/scapy-mcp-enrichment.md` (`state: built-not-wired`) for v2.
  - **Two BLOCKERs closed at this revision**: CB-1 (built-not-wired declaration via feature-tracking file) and CB-6 (`blocks_on` typo + saga-coordinator misreference — fixed to point at the Flowscape spec).
  - **Four BLOCKERs deferred to v2**: CB-2 (100ms timeout × 5000 edges/tick math), CB-3 (GDPR reframe + `docs/legal/gdpr-posture.md`), CB-4 (phantom APIs in spec), CB-5 (phantom proto types).
- 2026-09-06 — **v2 revision**. Closes the v2-deferred BLOCKERs that fit within this ADR's scope:
  - **CB-2 (timeout math)**: replaced per-edge `enrich_edge(edge)` with per-tick batched `enrich_batch(edges)`. Per-tick budget fits the 100ms publish cadence at Phase 4 capacity (5000 edges). On timeout, publisher drops the entire snapshot via the existing 50ms backpressure policy.
  - **CB-3 (GDPR partial close)**: added §Scope framing the ADR as pre-1.0 internal-use only; deferred EU regulatory coverage (controller/processor reframing, `docs/legal/gdpr-posture.md`, Article 35 DPIA scoping) to v3. Project memory `feedback-bodai-pre-1.0-merge-policy` makes pre-1.0 internal use not GDPR-triggered; full reframe becomes load-bearing when Flowscape ships a v1.0 public release.
  - **L1 B1 + L5 B-Op3 (feed observability)**: added 4 mandatory metrics + `flowscape.enrichment.timeout_total`. Specified that the no-op default emits `0`/`now()`/`0`/`0` to surface wiring-discipline "registered but disabled" cleanly.
  - **L5 B-Op1 + B-Op2 (SLOs + data-driven rollback)**: added §Operational SLOs and Feed Observability with explicit latency p99, error rate, availability, timeout-budget targets. Replaced the v1 operator-judgment clause with three data-driven rollback triggers (slow provider, heuristic regression, broken feed) each with concrete thresholds and auto-actions.
  - **L1 B2 + L5 B-Op4 (doctor envelope)**: added explicit `flowscape doctor --enrichment` output schema with exit codes, fields, and feed_state aggregation into `/health`.
  - **L3 B1 + B2 (registry pattern)**: replaced the divergent `EnrichmentRegistry.default()` classmethod with name-driven `get_provider(name)` lookup mirroring `CaptureSource`'s `CaptureSettings.default_kind` pattern. Declared `EnrichmentHook` as ABC (not Protocol) per the L3 contradiction.
  - **L3 B3 (Oneiric primitives)**: replaced the bare `enrichment_timeout_ms: int` with `enrichment.retry: {max_attempts, base_delay_ms, multiplier, max_delay_ms}` composing with `oneiric.actions.workflow.WorkflowRetryAction`.
  - **L2 B2 (entry-point constraint)**: architecture diagram now names `dissect_bytes` as the **sole** scapy-mcp entry point, with a justification that `craft_packet`, `capture_read`, and `transmit_packet` are deliberately excluded.
  - **L2 I-3.5 (enrichment payload shape)**: pinned `EnrichmentMetadata` Pydantic model with `extra="forbid"` and an allow-list of `{top_n_rank, threat_score, confidence_boost}`.
  - **L1 I.A2 (client-side primitive)**: replaced `apply_tool_profile` reference with `fastmcp.Client` against the streamable-HTTP endpoint.
  - **L1 I.A3 (`EXPECTED_BASELINE` gap)**: cited `BASELINE_TOOL_NAMES` from `mcp_common.baseline_tools`; flagged that `EXPECTED_BASELINE` does not exist as an mcp-common symbol and is a recurring import failure mode across the stub-activation sibling plans.
  - **Three BLOCKERs remain deferred to v3** because they require work outside this ADR: **CB-4** (phantom APIs in spec — spec lives in `docs/superpowers/specs/`), **CB-5** (phantom proto types — proto lives in `proto/flowscape.proto` which doesn't exist yet), and the full **CB-3 GDPR reframe + `docs/legal/gdpr-posture.md`** (pre-1.0 scope currently makes it a v1.0-public-release prerequisite).

---

**END OF ADR 0016**
