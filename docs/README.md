# Mahavishnu Docs

This directory contains current documentation, active plans, historical reviews, and archived implementation material for Mahavishnu.

Start here when reviewing or implementing work. Do not assume a root-level document is current just because it is easy to find; this repository has older phase reports and completion summaries that are being progressively archived.

## Current Entry Points

### Plans And Specs

- [Plan Index](./plans/PLAN_INDEX.md) - canonical map for active, historical, and superseded plans
- [Plans README](./plans/README.md) - plan directory orientation
- [Bodai Agent Platform Master Spec](./plans/2026-04-16-bodai-agent-platform-master-spec.md) - current Agno/Textual TUI and platform boundary spec
- [Bodai Master Implementation Plan](./plans/2026-04-16-bodai-master-implementation-plan.md) - current Agno/Textual/platform implementation plan
- [Ecosystem Control Plane Update Plan](./plans/2026-04-25-mahavishnu-ecosystem-control-plane-update-plan.md) - current ecosystem health/status/capability plan
- [Ecosystem Docs Canonicalization Plan](./plans/2026-04-25-ecosystem-docs-canonicalization-plan.md) - current cross-repo docs cleanup plan

### Architecture And Decisions

- [Architecture](./architecture/ARCHITECTURE.md)
- [Deployment Architecture](./deployment-architecture.md)
- [MCP Server Architecture](./MCP_SERVER_ARCHITECTURE.md)
- [ADR Directory](./adr/)
- [Specs](./specs/)

### Operator Docs

- [Getting Started](./GETTING_STARTED.md)
- [Quick Start](./QUICK_START.md)
- [MCP Tools Reference](./MCP_TOOLS_REFERENCE.md)
- [MCP Quick Reference](./MCP_QUICKREF.md)
- [Production Readiness](./PRODUCTION_READINESS.md)
- [Runbooks](./runbooks/)
- [Incident Response](./incident-response/INCIDENT_RESPONSE_RUNBOOK.md)
- [Disaster Recovery](./incident-response/DISASTER_RECOVERY_RUNBOOK.md)

### Development And Integration

- [Worktree Management](./WORKTREE_MANAGEMENT.md)
- [Terminal Management](./TERMINAL_MANAGEMENT.md)
- [Content Ingestion Guide](./CONTENT_INGESTION_GUIDE.md)
- [Integration Guide](./integration/INTEGRATION_GUIDE.md)
- [Integrations](./integrations/)
- [Testing Strategy](./testing-strategy.md)
- [Testing Docs](./testing/)

### Observability

- [Telemetry](./telemetry.md)
- [OTLP Architecture](./OTLP_ARCHITECTURE.md)
- [OTLP Troubleshooting](./OTLP_TROUBLESHOOTING.md)
- [Native OTEL Architecture](./NATIVE_OTEL_ARCHITECTURE.md)
- [Grafana Docs](./grafana/)
- [SRE Docs](./sre/)

## Historical And Non-Authoritative Material

- [Archive](./archive/) - historical plans, completion reports, old analyses, and superseded guides
- [Reviews](./reviews/) - review inputs and audits; useful evidence, not automatically current authority
- [Analysis](./analysis/) - investigation and analysis docs; verify against current plans/code before implementing
- [Reports](./reports/) - generated or curated reports used for planning and review

Archive material can be useful for provenance, but current implementation work should start from [Plan Index](./plans/PLAN_INDEX.md).

## Cleanup Status

Current docs cleanup is tracked in:

- [Ecosystem Docs Canonicalization Plan](./plans/2026-04-25-ecosystem-docs-canonicalization-plan.md)
- [Ecosystem Docs Inventory](./reports/ecosystem-docs-inventory.md)
- [Ecosystem Docs Audit](./reports/ecosystem-docs-audit.md)
- [Ecosystem Docs Cleanup Candidates](./reports/ecosystem-docs-cleanup-candidates.md)
- [Mahavishnu Root Docs Cleanup Candidates](./reports/mahavishnu-root-docs-cleanup-candidates.md)

Run the read-only audits with:

```bash
python scripts/audit_ecosystem_docs.py --output text
python scripts/audit_ecosystem_docs.py --output markdown --include-files --write docs/reports/ecosystem-docs-cleanup-candidates.md
python scripts/standardize_ecosystem_docs_structure.py
```

Current cleanup state:

- `docs/archive/backups/` contains historical markdown moved out of the active `docs/backups/` path.
- Mahavishnu root-level stale reports and old implementation plans have been moved under `docs/archive/`.
- All active ecosystem repos currently report no immediate structural recommendations in [Ecosystem Docs Audit](./reports/ecosystem-docs-audit.md).

## Maintenance Rules

- Add new active plans to [plans/PLAN_INDEX.md](./plans/PLAN_INDEX.md).
- Add new stable specs to `docs/specs/`.
- Add operational procedures to `docs/runbooks/` or `docs/incident-response/`.
- Add durable design decisions to `docs/adr/`.
- Move completion reports and superseded implementation plans to `docs/archive/`.
- Do not commit backup tarballs, coverage artifacts, or temporary generated files under `docs/`.
- If a doc is superseded, leave a pointer to the canonical replacement.
