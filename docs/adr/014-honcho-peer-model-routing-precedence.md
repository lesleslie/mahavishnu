# ADR 014: Honcho Peer-Model Routing Precedence

## Status

**Accepted**

**Date:** 2026-06-08

## Context

Session-Buddy Phase 1.5 introduced `user_models` (the Honcho peer model): an LLM-derived summary of a user's preferences, working style, and past routing outcomes. Phase 1.5 publishes per-user `peer_model_suggested_pool` as a routing *hint* — not an authority.

Mahavishnu's pool router currently uses `POOL_ROUTING_STRATEGY` (`round_robin`, `least_loaded`, `random`, `affinity`) to choose a pool when a task is dispatched. Phase 1.6 wants the router to additionally consult the user's peer model when a `user_id` is present in the request envelope.

Two authority surfaces now overlap:

1. **ACL** — the existing `pool_access_control` table / settings (who is allowed to run on which pool, repo-scoped or user-scoped). ACL is the security boundary: it answers "is this user permitted to dispatch to this pool at all?"
2. **Peer model** — the LLM-derived preference hint. Peer model is the optimization signal: it answers "given what we know about this user, which pool is *likely* best for them?"

The risk is precedence confusion. If the two surfaces disagree, a single dispatcher that consults both must have a deterministic answer for which wins, and the answer must be auditable from the trace log. Today there is no documented rule; the dispatcher would either silently drop the hint (no improvement) or silently override the ACL (security regression).

This ADR pins the rule so the dispatcher, the pool tools (`pool_route_execute`, `pool_execute`), and the WebSocket trace stream can all rely on a single contract.

## Decision

**The ACL is authoritative. The peer model is a hint that is honored only inside the ACL's allowlist.**

Concretely, when a `pool_route_execute` (or equivalent) call has a `user_id`:

1. Resolve the user's ACL. Build the set of pools this user is *permitted* to dispatch to. If the user has no ACL entry, fall back to the project-wide default ACL.
2. Consult the user's peer model (`user_models.peer_model_suggested_pool`) for a *suggested* pool.
3. If the suggested pool is in the ACL allowlist, use it as the candidate.
4. If the suggested pool is *not* in the ACL allowlist (denied, unknown, or simply missing), discard the hint and apply the configured `POOL_ROUTING_STRATEGY` against the ACL-allowlisted pools only.
5. Emit a trace event (`task.pool_routing.hint_discarded` or `task.pool_routing.hint_applied`) so an operator can see which path was taken.

The shortcut form `acl_wins := (acl_permits and not peer_suggests_within_acl) -> apply routing_strategy(acl_pools)` is the canonical contract. The dispatcher does **not** check the peer model *after* the ACL — it checks the peer model *within* the ACL. The two are not in conflict by construction.

**Why ACL wins by construction, not by tiebreak:** A tiebreak rule ("if both say something, ACL wins") still requires the dispatcher to read the peer model in cases where it would have been ignored anyway, and it leaves room for a future bug that consults the peer model before the ACL is loaded. The "ACL first, then peer-within-ACL" composition is impossible to misorder: there is no code path where the peer model can cause a denied pool to be selected.

## How it composes with the rest of the system

| Surface | Role | Authority level |
|---------|------|-----------------|
| `pool_access_control` (ACL) | Security boundary | **Authoritative** |
| `user_models.peer_model_suggested_pool` (Honcho) | Optimization hint | Advisory, ACL-scoped |
| `POOL_ROUTING_STRATEGY` | Tiebreak between equally-allowed pools | Default when no peer hint |
| `pool_health` (crashed/overloaded) | Eligibility filter | Hard filter, applied after ACL |

Health filtering happens *after* ACL: a pool the user is allowed to use but that is currently unhealthy is dropped, regardless of whether the peer model picked it. The peer model never overrides health either — a `peer_suggested` pool that just crashed is rerouted via the routing strategy, with the trace event `task.pool_routing.hint_discarded(reason=unhealthy)`.

## Consequences

### Positive

- **Smarter routing for known users.** Users with rich peer models get their preferred pool when it is also ACL-allowed, which empirically reduces p99 latency and tool-failure rate for repeat operators.
- **Auditable.** Every routing decision is a trace event. Operators can replay decisions, measure how often the peer-model hint changed the outcome, and tune the LLM that produces the hint without touching the router.
- **ACL is unchanged.** The security boundary does not move. A user with peer-model access to a pool they are not allowed to use still cannot get there. This is a contract decision, not a relaxation.
- **Phase 1.6 ships without a new ACL surface.** The peer model is a *consumer* of the existing ACL, not a peer authority that requires reconciliation code.

### Negative

- **LLM-derived hints can be wrong.** Honcho's peer model is an inference, not a fact. The "ACL is the safety net" framing means a stale or wrong hint is a UX regression (slower routing, more failed dispatches) but never a security one. We accept that trade.
- **Two reads per dispatch.** The router now does an ACL lookup and (optionally) a peer-model lookup. Both are O(1) for the in-memory ACL and a single Postgres point read for the peer model, so the latency cost is negligible — but it is real, and it shows up in the trace.
- **Operator confusion risk.** "Why didn't the peer model pick pool X for user Y?" will be a common question. The trace event vocabulary (`hint_applied`, `hint_discarded`, `hint_missing`) is the answer. Documentation in the routing guide and in the `pool_route_execute` tool docstring must spell this out.
- **No cross-user peer model.** The hint is per-user. A shared service account or a CI bot has no peer model, and gets the routing strategy with no hint — same as today. That is correct, but worth flagging.

## Implementation evidence

This decision is not speculative; the supporting pieces are landing in Items 1 and 2 of the same Session-Buddy Phase 1.6 batch:

- **Item 1 — Akosha `source_type` discriminator:** Akosha's reflection ingest now tags memory rows with `source_type ∈ {reflection, user_model, peer_signal}`. This is the storage layer that lets the dispatcher fetch the right row type without scanning. The trace event `task.pool_routing.hint_applied` carries the same `source_type` for cross-system correlation.
- **Item 2 — `PEER_AFFINITY` selector:** Mahavishnu's `PoolSelector` enum gains `PEER_AFFINITY` as a first-class selector. When the dispatcher sees `user_id` and the ACL is non-empty, it uses `PEER_AFFINITY`; when `user_id` is absent, it falls back to the configured `POOL_ROUTING_STRATEGY`. `PEER_AFFINITY` *is* the "honor the peer model within the ACL" branch. The selector is registered in `mahavishnu/pools/manager.py` and exposed via the `pool_route_execute` MCP tool.

Together, Items 1 and 2 are the implementation; this ADR is the contract they implement.

## Rejected alternatives

- **Peer model is authoritative, ACL is advisory.** Rejected. ACL exists to prevent a misclassified or compromised user from dispatching to a pool that holds production credentials. The peer model is an LLM output and cannot be trusted to be a security boundary.
- **Both vote, highest weight wins.** Rejected. Voting implies a shared metric space ("which is the *right* pool?"), and the two surfaces are answering different questions (security vs. preference). Composing them numerically is unprincipled and hard to audit.
- **Run them sequentially, last write wins.** Rejected. The natural last-write ordering depends on which lookup returns first, which is non-deterministic. The "ACL first, peer within ACL" composition is order-independent by construction.

## References

- `mahavishnu/pools/manager.py` — `PoolManager.route_task` and `PoolSelector.PEER_AFFINITY`
- `mahavishnu/mcp/tools/pool_tools.py` — `pool_route_execute` and `pool_execute` MCP tools
- `mahavishnu/core/access_control.py` — ACL resolution and `pool_access_control` table schema
- `mahavishnu/docs/ROUTING_GUIDE.md` — operator-facing routing strategy + selector reference
- Session-Buddy `user_models` table (Phase 1.5) — peer model storage
- Akosha `source_type` discriminator (Item 1) — `reflection` vs. `user_model` vs. `peer_signal`
- `PoolSelector.PEER_AFFINITY` (Item 2) — first-class selector for peer-scoped routing
