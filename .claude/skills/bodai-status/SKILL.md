______________________________________________________________________

## name: bodai-status title: Bodai Status id: 01KX9EG7N9EEBKW0NA8ZAAD8CH description: 'Auto-trigger skill that surfaces cross-component Bodai activity (Mahavishnu, Akosha, Crackerjack) when the user asks "what is Bodai doing?", "show me activity", or similar phrasings. Reads from ~/.mahavishnu/bodai-event-queue.json which Phase 6A populates from Oneiric EventBridge. Use this for the cross-component view; use /vishnu-status for Mahavishnu-only.' owner: mahavishnu-core status: active category: observability last_reviewed: 2026-07-11

# Bodai Status (auto-trigger)

Visibility surface for cross-component Bodai activity (Mahavishnu + Akosha +
Crackerjack). Fires when the user wants visibility across the ecosystem, rather
than dispatch or single-component status.

## When to use

This skill is **observation**, not **dispatch**. Trigger when the user wants
cross-component visibility, e.g.:

- "What is Bodai doing right now?"
- "Show me cross-component activity."
- "Are there any workflows / aggregations / test runs in progress?"
- "What has Akosha or Crackerjack surfaced recently?"

The skill is *not* for requests like "dispatch this to Mahavishnu" (use
`/vishnu`) or "what is the pool status" (use `/vishnu-status`).

## Behavior

When this skill fires, invoke the `/bodai-status` slash command. The slash
command reads `~/.mahavishnu/bodai-event-queue.json` (populated by the
Phase 6A Bodai subscriber consuming Oneiric EventBridge) and groups events
by source (Mahavishnu, Akosha, Crackerjack) in a markdown table per
component.

If the queue is empty (Phase 6A subscriber not yet wired OR no recent
activity), the slash command prints `no events yet` — not an error. The
skill is safe to fire at any time.

## Distinction from `/vishnu-status`

| Surface | Purpose | Effect |
|-------------------|------------------------------------------|---------------------------------------------------------------|
| `/vishnu-status` | Observe / *show state* of Mahavishnu only | Surfaces pool health, workflow metrics, dispatch status (Mahavishnu-only) |
| `/bodai-status` | Observe / *show state* across Bodai | Surfaces merged events from Mahavishnu + Akosha + Crackerjack via the unified EventBridge queue |

Use `/vishnu-status` for "is Mahavishnu healthy" or "what's running on
Mahavishnu" (Mahavishnu-only view). Use `/bodai-status` for "what has anyone
done recently" — the cross-component view that captures Akosha aggregations,
Crackerjack test runs, and Mahavishnu workflows in one timeline.

## Where to find more

- Slash command body: `.claude/commands/bodai-status.md` (Phase 6 Task 6B.3).
- Bodai event subscriber: `mahavishnu/core/events/bodai_subscriber.py`
  (Phase 6A) — consumes `bodai:events` from Oneiric EventBridge and persists
  to `~/.mahavishnu/bodai-event-queue.json`.
- Plan: `docs/plans/2026-07-11-phase-6-bodai-observability.md` §Phase 6.3.
