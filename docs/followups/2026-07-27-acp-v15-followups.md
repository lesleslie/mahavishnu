---
status: active
role: canonical
date: 2026-07-27
last_reviewed: 2026-08-03
topic: acp-v15-followups
---

# 2026-07-27-acp-v15-followups — followup

## Status

**Open** — 8 items, all deferred from the v1.0 ACP server build plan
(`docs/plans/2026-07-26-mahavishnu-acp-server.md`, status `active`,
promoted 2026-07-27 after multi-lens adversarial review).

## Trigger

The v1.0 plan shipped with seven items explicitly scoped out to v1.5,
enumerated in the plan's §10 "v1.5 follow-ups" section. Tracking them
in one followup file so a single PR can close them together when v1.5
starts, and so the v1.0 plan's "Decision Rule" item 7 ("open a
follow-up for Toad-integration smoke") is not orphaned.

## Items

The items are listed in the order they appear in the plan's §10, not
in priority order. Each item has: scope, prerequisite, and shipping
context (standalone vs. bundled).

### v1.5.1 — ACP session persistence

- **Scope:** Add `session/load` support backed by
  `~/.mahavishnu/acp-sessions/<id>.jsonl`. Re-run the License /
  Compliance review per Decision 3 in the v1.0 plan. Flip
  `loadSession: true` in `InitializeResponse`.
- **Prerequisite:** v1.0 ships and reaches `adopted` (or at least
  ships — adoption gating is conservative; an early release can
  open v1.5 if there is real demand).
- **Shipping context:** bundle with v1.5.4 and v1.5.5 (the
  "persistence bundle").

### v1.5.2 — MCP-over-ACP

- **Scope:** When the upstream RFD stabilizes
  ([agentclientprotocol.com/rfds/mcp-over-acp](https://agentclientprotocol.com/rfds/mcp-over-acp)),
  flip `mcpCapabilities.acp: true` in `InitializeResponse` and
  tunnel the existing 174 Mahavishnu MCP tools through ACP sessions.
  Re-run the AGPL §13 analysis (License/Compliance review flagged
  this explicitly).
- **Prerequisite:** upstream RFD lands.
- **Shipping context:** reactive; ship a separate plan when the
  RFD stabilizes.

### v1.5.3 — Remote ACP (Streamable HTTP)

- **Scope:** Add `--transport=http` to `mahavishnu acp serve`.
  Auth posture shifts materially: bearer over HTTP needs additional
  hardening (TLS termination, per-IP rate limit, token rotation
  semantics).
- **Prerequisite:** upstream Streamable HTTP transport draft
  stabilizes.
- **Shipping context:** reactive; ship a separate plan when the
  upstream draft stabilizes.

### v1.5.4 — UUID v7 session IDs

- **Scope:** Replace RFC 4122 v4 with v7 (time-ordered) for better
  observability and DB indexing. One-line change in
  `mahavishnu/acp/server.py` plus a migration note in
  `docs/acp/USAGE.md`.
- **Prerequisite:** v1.5.1 (so persisted sessions are queryable
  by time order; otherwise the migration is gratuitous).
- **Shipping context:** bundle with the persistence bundle.

### v1.5.5 — Additional session methods

- **Scope:** `session/list`, `session/resume`, `session/set_mode`,
  `session/close`, `session/delete`, `logout`. Surface area
  expansion once v1.5.1's persistence is in (some of these are
  nonsensical without persistence — e.g., `session/resume`).
- **Prerequisite:** v1.5.1.
- **Shipping context:** bundle with the persistence bundle.

### v1.5.6 — License declaration reconciliation

- **Scope:** Reconcile `pyproject.toml:16` (declares
  `license = {text = "MIT"}`) with the canonical `LICENSE` file
  (BSD-3-Clause). One-line fix; non-blocking for the v1.0 plan.
- **Prerequisite:** none; can ship independently of v1.0.
- **Shipping context:** **standalone, independent ship**. Tracked
  in a separate GitHub issue (see "Action" below).
- **Origin:** License/Compliance review, 2026-07-27.

### v1.5.7 — Toad-integration smoke test

- **Scope:** Manual smoke that wires Toad → Mahavishnu end-to-end,
  captures a sample session, validates streaming and cancel
  behavior. Prerequisite for `docs/feature-tracking/tui.md`
  flipping to `adopted` (the TUI tracker's `adopted` state
  requires "at least one Toad / ACP client integration is
  documented as a follow-on to the ACP server build").
- **Prerequisite:** v1.0 ships and Toad is configured per
  `docs/acp/USAGE.md`.
- **Shipping context:** standalone; ships when Toad integration
  is in scope (a separate test plan, not a feature plan).

### v1.5.8 — A2UI as ACP sessionUpdate payload carrier

- **Scope:** Investigate carrying Google A2UI payloads (declarative
  JSON UI markup; `github.com/google/A2UI` v0.2 schema) inside ACP
  `sessionUpdate` messages. The ACP server would emit A2UI-formatted
  chunks for ACP clients that opt in (e.g., Toad, a web frontend),
  while preserving plain-text chunks for clients that don't.
  Layered, not competing: ACP owns session lifecycle; A2UI owns
  rendering. The Mahavishnu A2A server (`mahavishnu/a2a/server.py`)
  places us adjacent to Google's protocol ecosystem, but A2A work
  does not transfer to A2UI — treat as a new surface.
- **Prerequisite:** v1.0 ships; an ACP client (Toad, a web
  frontend, or another consumer) expresses demand for rich-UI
  rendering. The A2UI spec is public at v0.2, so there is no
  upstream-stabilization blocker.
- **Shipping context:** reactive; ship a separate plan when a
  client wants to consume A2UI. Bundling with v1.5.2 (MCP-over-ACP)
  is not assumed — independent trigger.
- **Origin:** TUI planning relevance check 2026-08-03 (companion
  note: `docs/feature-tracking/tui.md` — Toad decision gate).

## Action

1. **Independent ship (now, non-blocking):** v1.5.6 is a one-line
   fix. The GitHub issue is filed under the v1.5 followup
   umbrella; it resolves immediately when the issue closes.
2. **Bundle ship (when v1.0 is `adopted`):** v1.5.1, v1.5.4,
   v1.5.5 form a coherent "persistence bundle" — ship them
   together as v1.5.0. Each item gets its own v1.5 plan file
   that inherits the v1.0 plan's structure (Integration Contracts,
   Validation Matrix, Decision Rule).
3. **Reactive ship:** v1.5.2 (MCP-over-ACP), v1.5.3 (Remote
   ACP), and v1.5.8 (A2UI payload carrier) ship when their
   respective triggers fire — upstream-spec stabilization for
   v1.5.2 / v1.5.3, client demand for v1.5.8. Each gets its own
   plan file with a `blocks_on:` link to the trigger signal.
4. **Adoption-gated ship:** v1.5.7 is the gate for the TUI
   tracker's `adopted` state. It ships as a test plan, not a
   feature plan, and resolves the TUI's adoption criterion.

## Verification

A v1.5 release closes this followup by:

- Filing v1.5.0, v1.5.2, v1.5.3, v1.5.7, and v1.5.8 plan files
  (or equivalent) that each `blocks_on:` this followup
- Moving this file to `docs/followups/.archive/` per the
  followups lifecycle policy at
  `docs/followups/README.md` § "Closing and archiving" and
  `.claude/decisions/followups-lifecycle.md`
- Updating `docs/followups/README.md` to remove the row and
  add the archive entry

## Related

- Source plan: `docs/plans/2026-07-26-mahavishnu-acp-server.md`
  §10 (the v1.5 follow-ups enumeration this file mirrors)
- Source design: `docs/superpowers/specs/2026-07-15-mahavishnu-acp-server-design.md`
- TUI companion tracker: `docs/feature-tracking/tui.md` (the
  consumer of v1.5.7)
- License reconciliation issue: see "Action" item 1 above
- Followups lifecycle policy:
  `docs/followups/README.md` § "Lifecycle" and
  `.claude/decisions/followups-lifecycle.md`
