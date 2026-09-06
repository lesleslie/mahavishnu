---
status: draft
role: canonical
date: 2026-09-06
last_reviewed: 2026-09-06
superseded_by: null
blocks_on: []
decision_date: null
topic: gdpr-posture
related:
  - "../adr/0016-scapy-mcp-integration.md"
  - "../adr/0016-multi-agent-review.md"
  - "../feature-tracking/scapy-mcp-enrichment.md"
---

# GDPR Posture — Flowscape scapy-mcp Enrichment Integration

> **Status: draft.** This document captures the GDPR posture for Flowscape's v1 client-mode scapy-mcp enrichment integration. It was authored in response to the L4 BLOCKERs in the 6-agent multi-agent review of ADR 0016 (see `../adr/0016-multi-agent-review.md`). It is a working draft; a formal DPIA is the v1.x-public-release prerequisite, not pre-1.0 internal use.

## 1. Scope and Trigger

This document applies to **Flowscape v1's scapy-mcp client-mode enrichment integration** as specified in `../adr/0016-scapy-mcp-integration.md`.

**Pre-1.0 internal-use scope (current):** Recent project memory `feedback-bodai-pre-1.0-merge-policy: all Bodai components merge directly to main pre-1.0; no PRs` means Flowscape v1 has **no public release**. Article 3(1) GDPR territorial scope ("in the context of the activities of an establishment") and Article 3(2) (offering goods/services to data subjects in the Union) **are not currently triggered** for pre-1.0 internal use within the Bodai development environment. This document therefore captures the posture for the moment the project crosses into v1.x-public-release territory.

**v1.x trigger (when this becomes load-bearing):** Flowscape ships a v1.0 public release via PyPI + Homebrew + signed `.app` distribution (per the Flowscape plan §"Distribution & packaging"). At that moment:
- A formal Article 35 DPIA MUST be completed before the release goes live (see §7 below).
- This posture document MUST be re-reviewed against the then-current v1.0 scope and any updated scapy-mcp behaviors.
- ADR 0016 MUST be flipped to v3 (or higher) with the controller/processor reframing + Article 35 commitment.

## 2. Subject Matter and Nature of Processing

Flowscape is a macOS 3D network visualization tool. It captures live network packets from a user-monitored interface (subject to an active consent gate), aggregates them into per-flow counters, derives a graph-state snapshot, and presents it in a 3D scene. The **scapy-mcp enrichment integration** (v1, opt-in via `enrichment.scapy_mcp_enabled`) calls scapy-mcp as an MCP server to annotate the per-tick graph edge batch with: `top_n_rank`, `threat_score`, `confidence_boost` (per ADR 0016 v2 §"EnrichmentMetadata shape").

The **enrichment hook receives `(FlowEdge, HeuristicEvent)` metadata, never packet bytes** (per the wire-format no-payload guarantee in the spec §"Disclaimer docs" line 29). The hook input surface is structurally metadata-only.

## 3. Categories of Personal Data

The L4 GDPR review (`0016-multi-agent-review.md` B3) identified that **heuristic event metadata IS personal data** under GDPR Article 4(1), per Recital 30 and CJEU *Breyer* (C-582/14). The metadata includes:

| Field | Personal data? | Reasoning |
|---|---|---|
| `HostNode.id` (src, dst in `GraphEdge`) | **YES** | Pseudonymous identifier per Recital 26 ("any information ... which can be used to identify a natural person"). When combined with network-position context, re-identification is feasible. |
| `BeaconingDetail.peer_id` | **YES** | Same as above. |
| `BeaconingDetail.{interval_seconds, jitter_pct, sample_count}` | **YES** | Behavioral correlation data tied to identifiable peer: "user X's device contacted domain Y every 60 seconds with 20% jitter for 3 hours" — Article 4(1) per *Breyer*. |
| `PortScanDetail.{syn_packets_per_second, distinct_dst_ports, distinct_dst_ips, window_seconds}` | **YES** | Same; describes activity patterns of identifiable endpoints. |
| `TopNChurnDetail` | **YES** | Sustained activity patterns of identifiable hosts. |
| `payload_sha256_prefix` (32 bytes) | **NO** (one-way hash) | SHA-256 is cryptographically one-way; cannot reconstruct packet content from the prefix. |
| `bytes` / `packets` (uint64 counters) | **NO** | Length-only metadata, not content-derived. |
| `port`, `tcp_flags`, `protocol` | **NO** | Header fields; not specific to a data subject. |
| `top_n_rank`, `threat_score`, `confidence_boost` (enrichment metadata) | **NO** | Aggregated annotations; not subject-specific. |

**Categories of data subjects** affected: every individual on the network monitored by the Flowscape user's installation (likely the user's household/LAN members, devices, guests). Not the Flowscape user themselves in most cases.

**Categories of data NOT collected:** name, email, account credentials, payment info, biometric data, special categories (Article 9).

## 4. Controller / Processor Relationship

Per the L4 BLOCKER B1 (see `0016-multi-agent-review.md`), the v1 ADR's "exposure vs. dependency" framing is **the wrong GDPR axis**. The correct axis is **controller vs. processor** (GDPR Articles 4(7) and 4(8)).

**Position:** **Flowscape is the controller.** scapy-mcp (when invoked as an enrichment provider) is a **processor** on Flowscape's behalf. The processor agreement is the open-source `CONTRIBUTING.md` (Article 28(1) requires a "contract or other legal act" — for an open-source processor maintained by the same developer, `CONTRIBUTING.md` is the only available equivalent).

| Scenario | Flowscape role | scapy-mcp role | Article 28 contract needed? |
|---|---|---|---|
| Pre-1.0 internal use (single dev, same machine) | n/a (no Article 3 scope) | n/a | No |
| v1.x public release, same-host deployment | Controller | Processor (same legal entity if same dev maintains both) | Probably not (Article 28(2) exception: own processing activities) |
| v1.x public release, remote scapy-mcp | Controller | Processor (separate entity) | **YES** — Article 28(3) written contract required, including data categories, duration, security measures, sub-processor authorization |
| v1.x public release, third-party hosted scapy-mcp | Controller | Processor (third party) | **YES** — full Article 28(3) contract + Article 28(2) sufficiency demonstration |

The L4 BLOCKER B4 finding (premise that "same machine = same controller") is rejected: same-machine arguments are *security* arguments (no privilege escalation), not *privacy* arguments (Article 4(7) follows control of purpose-and-means, not locality).

## 5. Lawful Basis (Article 6)

The lawful basis for processing is determined by the deployment context:

### 5.1 Pre-1.0 internal use
No Article 6 basis required (no Article 3 scope). Internal-use documentation suffices.

### 5.2 v1.x public release — Legitimate Interests (Article 6(1)(f))

Flowscape's enrichment purpose is **enhanced threat detection to assist the Flowscape operator in understanding network activity on their own network**. This is a legitimate interest of the operator (Recital 47 — "the reasonable expectations of the data subject").

**Critical caveat from L4 BLOCKER B3**: Recital 49 limits legitimate-interests processing to data subjects with "reasonable expectations" of that processing. **A person on the user's Wi-Fi network who is being subjected to port-scan detection has no reasonable expectation that their SYN packets will be annotated by a separately-controlled enrichment tool.** Therefore:

- For **same-machine / same-entity** deployments: legitimate interests is viable IF the Flowscape user has clearly informed household members that packet capture + enrichment is active (the spec's active consent gate covers this for *capture*; the v3 ADR work adds an explicit consent-prompt for *enrichment activation*).
- For **remote / third-party hosted scapy-mcp**: legitimate interests is **NOT viable** without explicit consent per Article 6(1)(a). The remote-host processing is not within data subjects' reasonable expectations. **A fresh consent gate MUST be presented the first time the user flips `scapy_mcp_enabled = true`** (analogous to the existing consent gate for packet capture).

### 5.3 Consent gate design (v1.x public release)

When the user first flips `scapy_mcp_enabled = true`, the consent modal must include per Article 7(2) and Recital 32:

- **Specific**: names scapy-mcp as the enrichment provider; names the data categories shared (heuristic event metadata: behavioral correlation per Article 4(1)).
- **Informed**: explains the controller/processor relationship; explains that without consent, enrichment is unavailable but capture alone continues.
- **Unambiguous**: requires an explicit opt-in click; default-off preserved.
- **Withdrawable**: user can flip `scapy_mcp_enabled` back to `false` without re-installing or losing the consent gate's protection.

The implementation lives in the Flowscape consent modal at first-launch + interface/SSID change + every 30 days (spec line 92). The v3 ADR work extends this modal to include an enrichment-activation sub-prompt.

## 6. Data Subject Rights (Articles 12-22)

The Flowscape operator (the data controller) is the one who can exercise data subject rights on behalf of subjects, because Flowscape is local-only:

- **Right of access (Article 15)**: the Flowscape operator can read the live capture + enrichment state via `flowscape doctor` and similar commands. A subject requesting access through the operator can be accommodated without involving scapy-mcp.
- **Right to erasure (Article 17)**: deleting `~/.flowscape/` (per spec §"Logging path resolution") clears all local data. The enrichment provider (scapy-mcp) is told to forget via its own session-reset endpoint (to be designed in v1.x).
- **Right to data portability (Article 20)**: not applicable — Flowscape does not process structured personal data subjects would want to export.
- **Right to object (Article 21)**: subject objects through the Flowscape operator, who can disable capture + enrichment.
- **Rights related to automated decision-making (Article 22)**: Flowscape enrichment does NOT make automated decisions affecting subjects; heuristic alerts surface to the operator only.

## 7. DPIA Scope (Article 35)

Article 35(1) requires DPIA where processing is "likely to result in a high risk to the rights and freedoms of natural persons". Article 35(3)(c) names "systematic monitoring of a publicly accessible area on a large scale" as one trigger. The L4 BLOCKER (B3) applies:

- **Network activity monitoring on a private LAN**: EDPB Guidelines 4/2019 ¶21+ list systematic network monitoring as a DPIA trigger regardless of "public accessibility" — the EDPB considers indirect data subjects (those on the LAN) within scope.
- **Scale**: every FlowEdge, every HeuristicEvent, every 10Hz tick, every host on the LAN — this is "systematic" and "large scale" in the colloquial sense even though it operates on a private LAN.

**Conclusion:** Flowscape v1.x-public-release requires a formal Article 35 DPIA BEFORE shipping. The DPIA must cover:

- The lawful basis (Article 6(1)(f) vs 6(1)(a) — see §5.2 above).
- The data minimization analysis (Article 5(1)(c)) — does the enrichment plugin return only fields strictly necessary for the stated purpose? Per L4 BLOCKER B2, the default-off posture does NOT satisfy data minimization on its own; the metadata scope must be explicitly bounded.
- The accuracy and storage limitation analysis (Articles 5(1)(d), 5(1)(e)).
- The integrity and confidentiality analysis (Article 5(1)(f)) — including the wire-format no-payload guarantee and runtime Oneiric log filter.
- The accountability measures (Article 5(2)) — including this posture document, ADR 0016 v3, the spec, the runtime feed-state observability metrics.

The DPIA MUST be completed before Flowscape v1.x public release. The current `feedback-bodai-pre-1.0-merge-policy` makes this a v1.0-public-release prerequisite, not a v1.0-internal-use prerequisite.

## 8. International Transfers (Articles 44-50)

Pre-1.0 internal use: no transfers.

v1.x public release: **flowscape is local-only; scapy-mcp is the same-machine service by default (`scapy_mcp_host = localhost`).** Default-deployment has no international transfer.

For the remote-host scapy-mcp case (covered in ADR 0016 v2 §"Open Questions" #1): if the remote scapy-mcp is hosted outside the EEA, the controller (Flowscape operator) is responsible for ensuring Article 46 safeguards (Standard Contractual Clauses, adequacy decision, or binding corporate rules). This is a v1.x-post-release work item — defer until the remote-host architecture is concretely designed.

## 9. Security of Processing (Article 32)

The no-payload guarantee (spec §"Disclaimer docs") + runtime Oneiric log filter (spec line 88) + scapy-mcp's own safety controls (master kill-switch, L3 CIDR allowlist, L2 allow flag, broadcast opt-in per scapy-mcp plan §"Transmit safety model") form the Article 32 security baseline. The v1.x enrichment integration inherits this baseline; the v1.x-public-release work adds:

- **Wire-format regression detection** (L5 BLOCKER B-Op6): runtime regex-based field-name filter over `enrich_batch()` return values; emits WARN + increments `flowscape.enrichment.wire_format_violation_total` on hit. Closes the "silent regression" failure mode where a future maintainer adds a payload-shaped field to the merged proto.
- **mcp-common authentication primitives** (when designed, per ADR 0016 v2 §"Open Questions" #1): when scapy-mcp supports authenticated connections, the remote-host deployment gains transport security + principal-bound audit trail.

## 10. Connection to mcp-common Authentication Primitives

The v1.x posture assumes scapy-mcp authentication is unavailable (ADR 0016 v2 §"Open Questions" #1 explicitly defers this). When mcp-common ships authentication primitives, this document's remote-host analysis (§4 §8) updates to assume authenticated transport. Until then, same-host (localhost) deployment is the only posture this document endorses.

## 11. Cross-References

- **ADR 0016** (`../adr/0016-scapy-mcp-integration.md`) — the decision being posture-analyzed
- **ADR 0016 multi-agent review** (`../adr/0016-multi-agent-review.md`) — L4 lens BLOCKERs CB-1 through CB-5, of which CB-3 is closed by this document's existence
- **Feature-tracking built-not-wired** (`../feature-tracking/scapy-mcp-enrichment.md`) — tracks state transitions for v2/v3 wiring work
- **Flowscape spec §"MCP activation as regulatory event"** (lines 951-959 in v3) — softened by ADR 0016 v2 to clarify server-mode scope; this posture document covers the GDPR substrate that activation would invoke
- **Spec §"Consent gate"** — packet-capture consent; v3 work extends it for enrichment activation

## 12. Changelog

- 2026-09-06 — Drafted by Claude (v1) in response to L4 BLOCKERs in `0016-multi-agent-review.md`. Captures pre-1.0 internal-use scope (no current GDPR trigger) and v1.x-public-release obligations (DPIA, consent gate, controller/processor contract).
- TBD — Formal review by Bodai legal advisor before v1.x public release (and before any DPA contact).
- TBD — Re-review whenever scapy-mcp authentication primitives land (per §10).
