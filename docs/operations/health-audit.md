---
status: active
role: runbook
kind: operations-doc
date: 2026-10-09
last_reviewed: 2026-10-09
topic: mcp-design
---

# Fleet-Wide /health Audit — Operator Runbook

> Phase 2 of `docs/plans/2026-10-09-mcp-health-check-enrichment.md`
> (REQ-HC-004). Surface the silent-degraded case fleet-wide: a
> server returns HTTP 200 while its body claims
> `status: degraded | failed`. That is the bug
> `mcp-backend-wiring-discipline.md` calls out under "Audit
> cadence" — the load balancer thinks everything is fine, but
> the feeds are broken.

## TL;DR

```bash
# Run the monthly audit; non-zero exit code means a silent-degraded server.
mahavishnu mcp audit-health --all-repos

# Or invoke the MCP tool directly (any MCP client):
mcp__mahavishnu__audit_health(all_repos=True)
```

Exit code `0` = no silent-degraded servers, `2` = at least one
silent-degraded server (cron / monitoring can page on the exit
code alone, without parsing the body).

## What it audits

The 5 Bodai core MCP servers, per the canonical port table in
`CLAUDE.md` § Ecosystem Context:

| Repo | Port | Notes |
|------|------|-------|
| `mahavishnu` | 8680 | |
| `akosha` | 8682 | |
| `crackerjack` | 8676 | |
| `session-buddy` | 8678 | |
| `oneiric` | n/a | Foundation library — no MCP server, audit reports `skipped: true` |

`--repos` overrides the subset (e.g. `--repos mahavishnu,akosha`
for a spot check). `--all-repos` audits every entry in the
5-core list regardless of `settings/ecosystem.yaml`.

When neither flag is supplied, the audit intersects the
5-core list with `settings/ecosystem.yaml` so a missing
manifest entry is silently skipped. The monthly operator
cadence **must** pass `--all-repos` so the audit cannot
silently skip a repo just because it is not in the local
manifest.

## What it reports

For each repo:

```json
{
  "repo": "akosha",
  "host": "127.0.0.1",
  "port": 8682,
  "url": "http://127.0.0.1:8682/health",
  "http_code": 200,
  "body_status": "degraded",
  "latency_ms": 12.4,
  "silent_degraded": true
}
```

Plus aggregate counters at the top level:

```json
{
  "results": [ ... ],
  "total": 5,
  "silent_degraded_count": 1,
  "skipped_count": 1,
  "healthy_count": 3,
  "degraded_count": 1
}
```

## What `silent_degraded` means (M6 contract)

> `silent_degraded` = `http_code == 200 AND body.status in {"degraded", "failed"}`

This is the only condition that flips the flag. Honest 503s
(`http_code == 503` + degraded body) are **not** flagged — the
server told the truth, the load balancer can act. The bug the
audit exists to surface is the dishonest 200.

`warming_up` is **not** in the degraded set — a fresh server
returning 200 + `warming_up` is serving traffic and should not
page anyone. See `docs/plans/2026-10-09-mcp-health-check-enrichment.md`
§1 Outcome for the warming-up contract.

## Cadence

**Monthly** is the documented operator cadence (per
`mcp-backend-wiring-discipline.md` "Audit cadence" and the
parent plan §1 Outcome). Register the cron with the
deployment manifest (the `mahavishnu cron` CLI does not
exist; the cron is configured at the deployment level):

```cron
# /etc/cron.d/mahavishnu-health-audit — runs at 00:00 UTC on day 1 of every month
0 0 1 * * www-data /usr/local/bin/mahavishnu mcp audit-health --all-repos
```

Pager on non-zero exit (cron mail, Prometheus pushgateway, or
your equivalent).

## False-positive triage

1. **Read the report** — the `results` array tells you which
   repo is silent-degraded.
2. **Check the per-repo feed state** — `mcp__<server>__get_health()`
   on the affected repo returns the same envelope
   (`canonical_status`, `canonical_checks`,
   `canonical_reason_codes` per Phase 1.1) and identifies the
   broken feed.
3. **Check the per-feed halflife** — a feed is flagged degraded
   only after `HEALTH_FEED_HALFLIFE_SECONDS` (60s per
   Phase 1.1 override) of broken-before-first-success. If the
   flag flipped within the first 60s of a cold start, treat it
   as warm-up and re-run the audit after the next minute.
4. **If the flag persists** — file an issue against the
   offending repo's Phase 1.x health-enrichment work. The
   /health route is supposed to return 503 in that case (per
   REQ-HC-002), so a 200 + degraded body is a regression.

## Related

- Plan: `docs/plans/2026-10-09-mcp-health-check-enrichment.md`
- Spec (canonical aggregator): `mcp-common/mcp_common/health/aggregator.py:33-46`
- Discipline: `.claude/decisions/mcp-backend-wiring-discipline.md`
- Akosha pilot (precedent): commit `cd4733b` on akosha
