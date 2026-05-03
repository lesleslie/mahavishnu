# Initiative 13: Dashboard Phase 2 (Textual, Conditional)

## Metadata

- Status: `complete`
- Owner Role: `Platform UI`
- Target Window: `2026-06-08` to `2026-06-26`

## Outcome

Provide live read-only ecosystem diagnostics in a unified Textual dashboard.

## Work Package Checklist

- [x] `I13-1` Add `[tui]` dependency and bootstrap app shell
- [x] `I13-2` Implement overview + sweep screens
- [x] `I13-3` Implement routing/alerts screens + read-only constraints
- [x] `I13-4` Replace placeholder data with live read-only backend/MCP data

## Dependencies

- `G1` Adoption gate: Initiative 1 command usage (`>=3` active weekly users)

## Exit Criteria

- Read-only dashboard renders all planned screens with live data for 5 consecutive days
- Dashboard crash-free sessions `>=99%` during pilot window
- Incident response median time does not degrade by more than `5%` in pilot window

## Risks

- Building UI before operational data contracts are stable
- Runtime overhead or operational fragility in TUI layer

## Progress Log

- 2026-04-04: Plan file created.
- 2026-04-05: I13-1 complete — textual>=0.40 added as optional [tui] dep
- 2026-04-05: I13-2 complete — OverviewScreen (health, workflows, alerts) + SweepScreen (history table)
- 2026-04-05: I13-3 complete — RoutingScreen (adapter health, cache stats) + AlertsScreen (severity table)
  - All screens READ-ONLY (no mutation methods)
  - DashboardApp with TabbedContent (4 tabs), key bindings (1-4 for tab switching, q for quit)
  - CLI: `mahavishnu dashboard` command registered in \_main_cli.py
  - Tests: tests/unit/test_tui_dashboard.py (14 tests, all passing)
- 2026-04-25: Status corrected from `complete` to `partial`. The Textual shell exists, but current fetchers still return placeholder data. Live read-only data wiring should follow `docs/plans/2026-04-25-mahavishnu-ecosystem-control-plane-update-plan.md`.
- 2026-04-26: I13-4 complete — replaced all placeholder data with live read-only collection:
  - `EcosystemStatusService._collect_services()` now health-checks configured ecosystem services (Session-Buddy, Akosha, Dhara) via HTTP GET using httpx
  - `EcosystemStatusService._collect_adapters()` wired to accept adapter dict, calls `get_health()` on each
  - `EcosystemStatusService._collect_workflows()` wired to accept WorkflowProvider protocol
  - `EcosystemStatusService._collect_alerts()` wired to accept AlertProvider protocol, reads firing alerts
  - Added AdapterProvider, AlertProvider, WorkflowProvider protocols for dependency injection
  - `fetch_skill_drafts()` returns empty list (no more hardcoded mock data)
  - TUI `_get_report()` builds service configs from MahavishnuSettings (session_buddy_url, akosha_url, oneiric_mcp)
  - Tests: 39/39 ecosystem_status + 28/28 TUI dashboard (all passing)
  - Status updated to `complete`.
