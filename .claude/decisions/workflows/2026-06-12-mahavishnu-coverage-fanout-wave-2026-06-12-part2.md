# 2026-06-12-mahavishnu-coverage-fanout-part2 — workflow decision

## Status

Active

## Context

Wave-2 (2026-06-12 part 2) of the mahavishnu coverage fan-out. Picked the next 8 high-value targets (otel_ingester, websocket_server, and similar ingesters/runtime modules). Dropped the verifier phase to avoid the 429 rate-limit issue observed in wave-1; coverage is measured directly after the wave completes.

## Decision rule

Re-run this workflow as the second wave after 2026-06-12-mahavishnu-coverage-fanout completes, or stand it up as a standalone wave on the next 8 untested high-leverage modules. Expect ~40-min wall-clock; uses 8 parallel python-pro agents.

## Status history

- 2026-06-12 — Created.
