# Third-Party Notices

This file lists third-party projects adopted by Mahavishnu, with version, license, URL, copyright, integration posture, and AGPL/SSPL posture where applicable.

**Last updated:** 2026-06-23
**Maintained by:** Mahavishnu / Bodai ecosystem

## Conventions

- **Mode** indicates integration posture:
  - **Reimplement** — pattern borrowed, code built in-tree (no dep)
  - **Wrap as service** — external daemon/container, talk via stdio/HTTP/OTLP
  - **Run as CLI subprocess** — invoke on demand, no long-lived process
- **License** is the upstream project's published license.
- **AGPL posture** notes the legal/compliance status where the upstream is AGPL-3.0 or SSPL.

## Adopted third-party projects

### Tier 1 — Shipped (reimplement, no external dep)

| Project | License | URL | Copyright | Mode | AGPL posture |
|---|---|---|---|---|---|
| Keystone (pattern only) | Apache-2.0 | https://github.com/tacoda-lol/keystone | tacoda | Reimplement pattern only (`keystone_show` shape → `mcp__mahavishnu__show_primitive`); binary NOT adopted | N/A |

### Tier 2 — Spikes in progress

| Project | License | URL | Copyright | Mode | AGPL posture |
|---|---|---|---|---|---|
| OpenObserve | AGPL-3.0 | https://github.com/openobserve/openobserve | OpenObserve, Inc. | Wrap as service (Docker, port 127.0.0.1:5080) | Unmodified external subprocess; no source linking; no source distribution; Loki/Grafana precedent applies |
| Emdash | MIT | https://github.com/generalaction/emdash | General Action, Inc. | Run as CLI subprocess (stateless bridge, separate repo `mahavishnu-emdash-bridge`) | N/A |
| PageIndex | (TBD) | https://github.com/VectifyAI/PageIndex | Vectify AI | Wrap as service (HTTP MCP server) — pending spike | TBD |
| Graphify | (TBD) | https://github.com/yoheinakajima/graphify | Yohei Nakajima | Run as CLI subprocess (one-shot folder ingest, JSON output) | TBD |
| Maxun | AGPL-3.0 | https://github.com/getmaxun/maxun | Maxun | Wrap as service (4 robot types via SDK/CLI/HTTP) — pending pre-check | Unmodified external subprocess; no source linking; no source distribution; legal review recommended |

### Tier 4-6 — Declined (no work)

| Project | License | URL | Reason for decline |
|---|---|---|---|
| Crawl4AI | AGPL-3.0 | https://github.com/unclecode/crawl4ai | Re-deferred per `docs/specs/defer-crawl4ai.md` (Playwright dep + 0.x version) |
| Firecrawl | Commercial | https://firecrawl.dev | Commercial; out of strategy |
| AutoGen | MIT | https://github.com/microsoft/autogen | Already-decided per `docs/LIBRARY_EVALUATION_2025.md` |
| CrewAI | MIT | https://github.com/crewAIInc/crewAI | Already-decided per `docs/LIBRARY_EVALUATION_2025.md` |
| LangGraph | MIT | https://github.com/langchain-ai/langgraph | Already-decided per `docs/LIBRARY_EVALUATION_2025.md` |

## Legal posture summary

1. **No source linking**: Bodai code does NOT import AGPL libraries directly. All AGPL-touching integrations are via unmodified external subprocess / OTLP / HTTP.
1. **No source distribution**: Bodai repos do NOT bundle AGPL source. Distributed binaries contain only Bodai code.
1. **Attribution**: This file + `session-buddy/THIRD_PARTY_NOTICES.md` provide attribution per project.
1. **Loki/Grafana precedent**: Existing Grafana Loki integration (also AGPL-3.0) demonstrates the established Bodai posture — unmodified external subprocess pattern.
1. **Phase 3 promotion gate**: Before any Tier 2 AGPL project promotes to full implementation, formal legal sign-off recommended.

## How to update

When adopting a new third-party project:

1. Add a row to the appropriate table.
1. Document version, license, URL, copyright (look up upstream `LICENSE` file).
1. Specify integration mode.
1. If AGPL/SSPL: add legal posture note.
1. Commit with PR title `chore: add <project> to THIRD_PARTY_NOTICES.md`.
