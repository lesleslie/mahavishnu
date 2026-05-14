# C6a MdInject Audit

**Date:** 2026-05-11
**Scope:** `mdinject`
**Result:** audit-only, no direct deletion target identified

## Audit Commands

- `rg -n "event|session|memory|orchestration|storage|mcp|websocket|workspace|checkpoint|slack|discord" /Users/les/Projects/mdinject/mdinject /Users/les/Projects/mdinject/tests -g '!**/__pycache__/**'`

## Findings

- `mdinject/services/orchestrator.py` owns lifecycle wiring for prompt storage, terminal, export, format conversion, and licensing.
- `mdinject/mcp/server_core.py` wires the MCP lifespan around that orchestrator and uses `mdinject.storage.scope` to select the database path.
- `mdinject/storage.py` is the canonical prompt store implementation for the repo-local prompt database.
- The `event/session/memory/orchestration/storage` matches are overwhelmingly in tests, docs, or the existing service names rather than a separate live event spine.
- No direct Bodai event, recovery, or cross-repo memory/session dependency was found in the active runtime path.

## Disposition

- Keep `mdinject` as a client surface.
- Do not delete or rewrite runtime modules in this phase.
- Treat `C6a-MD1` as complete for audit purposes, with no code removal required.

## Follow-Up

- If future work introduces a direct Bodai dependency, re-open the row and separate the live dependency from docs/test-only references first.
