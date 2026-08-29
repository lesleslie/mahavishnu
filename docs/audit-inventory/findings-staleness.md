# Staleness findings

Generated 0 findings from Phase 3 / Task 3.4.1 staleness sweep.

| Repo | Command | Verdict | Reason | Short help |
|---|---|---|---|---|
| (none) | — | — | — | No stale or deprecated commands detected in the current Core 7 inventory. |

## Notes

- Source: `docs/audit-inventory/<repo>-cli-inventory.json` snapshots from the 2026-08-25 CLI audit.
- Verdict logic (from `scripts/audit_cli_inventory.py::_staleness_verdict`):
  - `deprecated` — command marked deprecated in code.
  - `stale` — experimental stub, ≥3 TODO markers, or ≥365d idle with ≥1 TODO.
- Re-run cadence: see `.claude/decisions/bodai-cli-staleness-cadence.md` (Plan Task 7.3).
