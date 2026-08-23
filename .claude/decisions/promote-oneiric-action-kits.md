---
status: active
role: canonical
date: 2026-08-23
last_reviewed: 2026-08-23
topic: oneiric-action-kit-promotion
---

# Promote Oneiric Action Kits Across Bodai

## Context

The Oneiric action-kit registry gives every Bodai component a shared
vocabulary for the small utilities that come up in every project:
HMAC signing, token generation, schema validation, retries, redaction,
HTTP probing, serialization, compression, hashing, data transforms,
automation triggers, and workflow orchestration. W3 promoted the
kits across five bodai repos with 207 tests passing — the kits now
share one canonical envelope for redaction, signing, retry, probing,
sanitize, secure-token, and serialization. The remaining ~10 bodai
repos have no promotion surface yet, so contributors keep reaching
for stdlib reinvented. This decision closes that gap by making kit
discovery part of how contributors think, not by adding an
enforcement gate.

## Discovery hint

When about to write HMAC signing, token generation, schema
validation, retries, redaction, HTTP probing, serialization,
compression, hashing, data transforms, automation triggers, or
workflow orchestration, **discover** whether a matching
`oneiric.actions.<kit>` exists before reaching for stdlib. The
catalog is the canonical reference at `docs/action-kits.md` in the
oneiric project. If the kit fits, use it (or wrap it). If it does
not fit (latency budget, API mismatch), document why in a code
comment linking back to the catalog entry.

This is a discovery surface, not an enforcement gate. The
`oneiric-action-kit-awareness` skill auto-fires when a task smells
like kit-shaped work and prompts the contributor to reach for the
kit. The skill is the active nudge; this doc is the durable "why."

## Status

Active. Adopted 2026-08-23 after W3 promotion across 5 bodai repos.

## Inventory of kits

The catalog is the source of truth; this doc links to it rather than
duplicating. See `docs/action-kits.md` in the oneiric project for
the 17 built-in kits (alphabetical by `metadata.key`).

## Exceptions

- Latency budget under 1ms where the kit's `lru_cache` lookup still
  costs more than the inline operation
- Kit API genuinely does not fit (wrapper would be dishonest) — wrap
  with a one-line comment linking back to the catalog entry

Discovery, not enforcement — bypass freely with a one-line note in
the code.
