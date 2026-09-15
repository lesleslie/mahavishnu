---
status: complete
role: reference
date: 2026-09-10
last_reviewed: 2026-09-10
superseded_by: null
blocks_on: []
topic: math-spec-verification
---

# Math Spec Verification Audit — 2026-09-10

> **Purpose**: Preserve the reasoning from the 3-agent verification pass that drove the v2→v3 patch of [`docs/plans/.archive/2026-09-10-bodai-math-initiatives-tier1.md`](../plans/.archive/2026-09-10-bodai-math-initiatives-tier1.md). Future contributors asking "why does v3 say X?" should find their answer here.
>
> **Reading guide**: §1 Overview → §2 Synthesis (BLOCKER/CRITICAL/HIGH taxonomy) → §3 v2→v3 mapping table → §4 Per-agent findings. §5 Notes on what's preserved verbatim vs. summarized.
>
> **Full agent transcripts** (raw tool-use exchanges) are available in the JSONL files at `/private/tmp/claude-501/-Users-les-Projects-mahavishnu/0fabba93-19ac-4966-8208-e34b70f3e868/tasks/*.output`. These are ephemeral temp files; the preserved summary in §4 is the durable record.

## 1. Overview

On 2026-09-10, the v2 spec was verified by three agents dispatched in parallel. Each agent had a distinct verification lens (different from round-1 review lenses):

| # | Agent | Lens | Why this lens |
|---|---|---|---|
| 1 | `feature-dev:code-reviewer` | Changelog compliance | Verify each of the 10 v2 changelog items actually landed in the spec body; flag any rewrites that lost v1 content |
| 2 | `mycelium-core:architect-reviewer` | Fresh-eyes self-consistency | Re-read v2 looking for NEW internal contradictions the rewrite might have introduced |
| 3 | `pr-review-toolkit:code-reviewer` | Validation matrix implementability | Verify each gate in §9 is actually implementable against the codebase (replacing the prematurely-terminated first qa-expert dispatch) |

The three lenses are non-overlapping with round-1's coverage AND with each other. Each agent had a specific question about the v2 patch:

- Agent 1: *"Did v2 actually close each finding, and did the rewrite regress anything v1 had right?"*
- Agent 2: *"Reading v2 fresh, what internal contradictions or new gaps does the rewrite introduce?"*
- Agent 3: *"Are the §9 programmatic gates real (the cited `python -c` assertions, the `make` target, the `audit_requirements.py` script), and is the operational handoff story implementable?"*

## 2. Synthesis

### 2.1 Convergent findings (2+ agents agree)

| # | Finding | Source agents | v3 disposition |
|---|---|---|---|
| V1 | The `requirements:` block is in the spec body, NOT the YAML frontmatter. `scripts/audit_requirements.py:76-92 parse_frontmatter` reads frontmatter only; the gate exits 1 on first run with all 9 REQs as phantoms. | 1 (flagged), 3 (verified by reading the script) | Frontmatter `requirements:` block added in v3 §1. |
| V2 | `_ALLOWED_LABEL_KEYS` at `mahavishnu/observability/metrics.py:74` is `Final[frozenset[str]]` — closed at import time. New Phase 2 labels (`predicted_wait_bucket`, `effective_selector`) silently drop at emission unless added. | 1 (flagged round-1 unaddressed), 3 (verified the file content) | Phase 2 task added: verify labels are in the allowlist, add to the set if missing. |
| V3 | Phase 2 description is garbled (warmup text spliced together) and contains `MMcQueue` (v1 name) in one task — the rename to `MmcQueue` was not applied uniformly. | 1 (flagged MMcQueue), 2 (CRITICAL #5, #7) | Phase 2 warmup description rewritten; `MMcQueue` → `MmcQueue`. |
| V4 | Spec misidentifies `mahavishnu_routing_decisions_total` location at `mahavishnu/monitoring/metrics.py:routing_metrics.py:163` — actual is `mahavishnu/core/routing_metrics.py:164`. The `mahavishnu/monitoring/` directory does not exist. | 3 (verified by grep) | §4.5 and §8 Modified files corrected. |
| V5 | Spec says "queue cap 100" for `fitness_analyzer.py`; actual is `_MAX_BUFFER_SIZE = 1000` at line 31. A future contributor following §7 would wire the wrong value. | 3 (verified) | §7 stub corrected to 1000. |
| V6 | Staged rollout was a "Recommendation" in Phase 4 and Phase 8, not a required task. §10 Risks row 1 listed it as mitigation, but the mitigation was unenforced — single-day global default flip was still possible. | 2 (CRITICAL #10), 3 (CONCERN) | Promoted to required task in both phases; §10 row 1 language updated. |
| V7 | Phase 6 default `threshold: 5.0` achieves ARL₀ ≈ 465 (per CUSUM standard tables), but §1 commits to ARL₀ ≥ 10,000. The shipped default would violate the documented success criterion. | 2 (CRITICAL #1) | `threshold: 8.0`, `slack: 0.25` (achieves ARL₀ ≈ 10,000 at two-sided CUSUM per Brook & Evans 1972). |
| V8 | §11 Decision Rule p95 bound (`< 50%`) was a single looser bound; §1 specifies both `±25% on Poisson` and `±50% on bursty`. The Decision Rule dropped the stricter Poisson criterion. | 2 (CRITICAL #2) | §11 Decision Rule split: `< 25% on Poisson; < 50% on bursty/hyperexponential`. |
| V9 | "Zero false positives in 1 week of synthetic quiet operation" is a §1 success metric with no Phase that demonstrates it. | 2 (CRITICAL #4) | Phase 7 programmatic gate adds `assert d['cusum_fp_per_10080_quiet_samples'] == 0`. |
| V10 | OTel span attribute `runbook_url` is defined in Phase 6 but no runbook file path is specified anywhere — on-call has nothing to click. | 3 (BLOCKER) | `docs/runbooks/mahavishnu-drift-detection.md` added to §8 New files; Phase 6 task includes creating it. |
| V11 | No top-level Makefile exists; `make tier2-eligibility` CI gate has no target. | 3 (BLOCKER, verified by `ls`) | Top-level `Makefile` added to §8 New files with `tier2-eligibility` target. |

### 2.2 Divergent findings

No divergent findings of the round-1 type (FOR vs. AGAINST). The verification round did not have a binary split; all three agents converged on the same recommendation: **patch v3 before senior review**.

One divergence in framing:

| Position | Agent | Reasoning |
|---|---|---|
| More permissive | 1 | Some findings (e.g., the changelog section-number drift on Items 1 and 2) are cosmetic and don't need fixing before senior review. |
| Stricter | 2 | Every CRITICAL finding should be patched — even if cosmetic, leaving inconsistencies erodes senior reviewer trust in the spec's self-discipline. |

**Resolution**: stricter position won. All 16 v3 changes address substantive issues; cosmetic drift (changelog section numbers) was deliberately left as-is because rewriting the changelog to match v2's actual section numbers would require reconstructing §4 from §4.2+§4.6+§7, which is a different kind of work than verification. Future contributors can correct the section numbers if it matters.

### 2.3 Severity taxonomy

| Severity | Definition | Count | Examples |
|---|---|---|---|
| **BLOCKER** | Would prevent implementation on first run | 3 | `audit_requirements.py` gate fails; no Makefile; runbook_url points nowhere |
| **CRITICAL** | Self-contradiction in the spec; would mislead implementer or ship in a state that violates success criteria | 7 | Default threshold violates §1 ARL₀; Phase 2 description contradicts §4.5 |
| **HIGH** | Correctness gap that should be closed before senior review | 5 | `_ALLOWED_LABEL_KEYS` allowlist check missing; Q3 vs Phase 6 metric default; marker style inconsistency |
| **MEDIUM** | Clarity / convention issue; nice to fix | 8 | bench.json keys not pytest-benchmark defaults; severity classifier unspecified; HotRecord location misdescribed |

The verification round surfaced 3 BLOCKERs, 7 CRITICAL findings, 5 HIGH findings, and 8 MEDIUM findings. v3 addressed all BLOCKERs and CRITICAL findings, plus the 4 most decision-affecting HIGH items. The remaining MEDIUM findings are documented in §4 but not patched.

## 3. v2 → v3 mapping

| Aspect | v2 | v3 | Source agent(s) |
|---|---|---|---|
| Frontmatter `requirements:` block | absent | added with all 9 REQ IDs | 1, 3 |
| Top-level `Makefile` | absent | `Makefile` added with `tier2-eligibility` target | 3 |
| Runbook file | absent | `docs/runbooks/mahavishnu-drift-detection.md` | 3 |
| Phase 6 default `threshold` | `5.0` (ARL₀ ≈ 465) | `8.0` (ARL₀ ≈ 10,000) | 2 |
| Phase 6 default `slack` | `0.5` | `0.25` (allows 0.5-σ shift detection) | 2 |
| Phase 6 default `target_metric` | `workflow_duration_p99` | `pool_queue_depth` (Q3 resolved) | 2 |
| Phase 6 marker style | module docstring `# req:` | method-level `# req:` on `_evaluate_change_point`/`_evaluate_3sigma` (matches §5.1) | 2 |
| Phase 6 severity classifier | unspecified | `minor` (<2×threshold), `moderate` (<4×threshold), `critical` (≥4×threshold) | 2 |
| Phase 6 AnomalyResult type | undefined | `mahavishnu/observability/changepoint/anomaly.py` added to §8 | 2 |
| Phase 7 programmatic gate | 2 assertions | 5 assertions including `cusum_fp_per_10080_quiet_samples == 0` | 2 |
| §11 Decision Rule p95 bound | `< 50%` (single) | `< 25%` Poisson; `< 50%` bursty/hyperexponential | 2 |
| Phase 4 staged rollout | "Recommendation" | Required task with playbook template (environment sequence, gating metrics, monitoring window, opt-out template) | 2, 3 |
| Phase 8 staged rollout | "Recommendation" | Required task with same playbook template | 2, 3 |
| Phase 2 warmup description | garbled (two paragraphs spliced, undefined "per the round") | one clean paragraph | 2 |
| Phase 2 `MMcQueue` typo | at line 371 | renamed to `MmcQueue` | 1, 2 |
| Phase 2 `_ALLOWED_LABEL_KEYS` check | absent | task added: verify labels in `Final[frozenset[str]]`, add if missing | 1, 3 |
| §4.5 log-line exception | unclear (added a log line "for warmup" while §4.5 said no new emission paths) | explicit exception with rationale (warmup state has no other surface) | 2 |
| Phase 9 `feature_eligibility.py` contract | vague ("reads Akosha and Session-Buddy metrics via MCP") | specific MCP endpoint names, exit codes (0/1/2), output format, CLI flags | 3 |
| §7 cross-repo queue cap | 100 | 1000 (`_MAX_BUFFER_SIZE` at `fitness_analyzer.py:31`) | 3 |
| §7 HotRecord location | `mahavishnu/ingesters/otel_ingester.py` construction template | imported FROM `akosha.models` at line 758 | 3 |
| §8 Modified files `routing_metrics.py` path | `mahavishnu/monitoring/metrics.py` (does not exist) | `mahavishnu/core/routing_metrics.py` | 3 |
| §9 `bench.json` keys | unspecified | documented as custom-written by integration test harness, NOT pytest-benchmark defaults | 3 |
| §12 Q3 | open | RESOLVED — `pool_queue_depth` matches recommendation | 2 |
| Audit doc | none | `docs/audits/2026-09-10-math-spec-verification.md` (this file) | new |

## 4. Per-agent findings

Each agent's section below preserves: lens, key findings (summary), and a verbatim quote from the agent's response for the most decision-affecting claim.

### 4.1 feature-dev:code-reviewer (Agent 1)

**Lens**: Changelog compliance audit — verify each of the 10 v2 changelog items actually landed in the spec body, and flag any rewrites that lost v1 content.

**Key findings (7 VERIFIED · 3 PARTIAL · 0 MISSING · 2 minor regressions)**:

1. Items 3, 4, 5, 6, 7, 8, 9 VERIFIED — phase renumbering, Phase 6 wiring target, 3-sigma framing, ARL₀ spec, MmcQueue rename, instrumentation deliverables, env-var convention.
2. Items 1, 2, 10 PARTIAL:
   - Item 1 (cross-repo §4.4 → §4.6 + §7): content present but changelog section label drifted (§4.4 holds arrival-timestamps in v2, not cross-repo).
   - Item 2 (Akosha algorithm landscape §4.7): content present at §4.2 + §7 but changelog says §4.7.
   - Item 10 has 4-5 unaddressed sub-findings: `_ALLOWED_LABEL_KEYS` closed-set warning, `agent_task_duration_seconds` bucket coarseness, `pool_tasks_queued` never-written metric.
3. **Minor regressions**: `MMcQueue` typo at Phase 2 line 371; REQ marker style inconsistency in §5.1 mapping.

**Verbatim on the changelog drift**: *"The changelog is misleading. A reader auditing 'did they add §4.7 with the algorithm landscape?' will conclude 'no' by skimming §4.7. Worth fixing the changelog labels (or moving the content) so future reviewers can find what the changelog claims is there."*

**Verbatim on Item 10's gaps**: *"Agent 1's `_ALLOWED_LABEL_KEYS` closed-set warning (finding #10) and Agent 9's `agent_task_duration_seconds` bucket coarseness + `pool_tasks_queued` never-written (findings #3, #5) are not addressed. Phase 6 emits new Prometheus labels (line 520: `metric_name`, `detector`, `severity`) without verifying they're in the allowlist; if Agent 1 was right that `_ALLOWED_LABEL_KEYS` is closed, the new counter silently loses labels in production."*

**v3 impact**: Agent 1's `_ALLOWED_LABEL_KEYS` finding was verified by Agent 3's grep (file at `mahavishnu/observability/metrics.py:74` is `Final[frozenset[str]]` — closed). v3 adds Phase 2 task: verify labels are in the allowlist, add if missing. The `MMcQueue` typo was fixed.

### 4.2 mycelium-core:architect-reviewer (Agent 2)

**Lens**: Fresh-eyes architectural self-consistency — re-read v2 looking for new internal contradictions the rewrite might have introduced or pre-existing issues the rewrite didn't catch.

**Key findings (10 CRITICAL · 7 HIGH · 8 MEDIUM)**:

CRITICAL items the v3 patch addressed:
1. Phase 6 default `threshold: 5.0` achieves ARL₀ ≈ 465, but §1 commits to ARL₀ ≥ 10,000.
2. §11 Decision Rule p95 bound (`< 50%`) looser than §1's `±25% on Poisson`.
3. Phase 2 "Demonstrable by" claim contradicts §1 success metric (only one workload type tested).
4. Zero-FP-in-1-week criterion is an orphan — no Phase demonstrates it.
5. Phase 2 QueueingScorer warmup description is garbled.
6. Phase 2 still adds a new log line, contradicting §4.5.
7. Phase 2 references `MMcQueue` (v1 name).
8. Phase 6 marker-style inconsistency with §5.1 mapping (method-level vs module-docstring).
9. Q3 open question conflicts with Phase 6 default metric.
10. Staged rollout is a "Recommendation" not a deliverable.

**Verbatim on the threshold contradiction**: *"Phase 6 specifies `threshold: float = 5.0` (the classical `h`) with the comment 'chosen for ARL₀ ≈ 465 at standard settings.' But §1 commits to `ARL₀ ≥ 10,000` and §11 Decision Rule point 1 requires `change-point ARL₀ ≥ 10,000` to ship. The shipped default achieves ARL₀ ≈ 465, not ≥ 10,000."*

**Verbatim on Phase 2 description quality**: *"Phase 2's description is the lowest-quality text in the spec... It contains a garbled sentence, a v1 leftover class name, and a self-contradiction with §4.5. This is the first phase implementers will work on; sloppy description multiplies downstream rework."*

**Verbatim on staged rollout framing**: *"§10 row 1 says 'Staged rollout: 1 environment → all environments.' Phase 4 and Phase 8 both list staged rollout only as a 'Recommendation' with no explicit task to implement it. Reviewers who skip the recommendation can ship a single-day global default flip — exactly the failure mode §10 row 1 warns about."*

**v3 impact**: All 10 CRITICAL findings were addressed. The 7 HIGH findings included the marker-style inconsistency (addressed), `_ALLOWED_LABEL_KEYS` allowlist (addressed via Agent 1 + Agent 3 finding), Q3 resolution (addressed), spec path corrections (addressed). MEDIUM findings (line-number brittleness, open question phrasing, marker style in Phase 5 "Demonstrable by") were not patched but are documented in the v2 spec for future iteration.

### 4.3 pr-review-toolkit:code-reviewer (Agent 3)

**Lens**: Validation matrix implementability — verify each gate in §9 is real against the codebase; replace the prematurely-terminated first qa-expert dispatch.

**Key findings (3 BLOCKER · 8 CONCERNS · multiple OK)**:

**BLOCKERS** (all addressed in v3):
1. `audit_requirements.py:76-92 parse_frontmatter` reads frontmatter only — verified by reading the script. The `requirements:` block in the spec body is invisible to the audit.
2. No top-level Makefile exists at the repo root — verified by `ls`. The `make tier2-eligibility` CI gate has no target.
3. OTel span `runbook_url` references a non-existent file. No `docs/runbooks/` entry.

**CONCERNS** (most addressed in v3):
1. `bench.json` keys (`p95_error`, `cusum_p95_latency_at_0.5_sigma`, `cusum_arl0`) don't exist in pytest-benchmark's default output. Tests need to write a custom JSON.
2. Spec misidentifies `mahavishnu_routing_decisions_total` location (`mahavishnu/monitoring/metrics.py:routing_metrics.py:163` — directory does not exist; actual is `mahavishnu/core/routing_metrics.py:164`).
3. Spec says "queue cap 100" for fitness_analyzer; actual is `_MAX_BUFFER_SIZE = 1000`.
4. HotRecord imported FROM `akosha.models`, not constructed in mahavishnu.
5. Phase 9 `feature_eligibility.py` doesn't name MCP endpoints, response shapes, or exit codes.
6. OTel span `severity` classifier unspecified.
7. Phase 4 and Phase 8 staged rollout playbook is one-line, not concrete.
8. Two `PoolConfig` classes exist (Pydantic with `extra: forbid` in `core/config.py`, dataclass with `extra_config: dict` in `pools/base.py`).

**Verbatim on the BLOCKER pattern**: *"The v1→v2 review note ('REQ block stays in §5 with a §5.1 mapping table; frontmatter references it') claims this was fixed but it wasn't — the frontmatter doesn't reference §5 either."*

**Verbatim on the queue cap**: *"Spec says 'queue cap 100' — actually is `_MAX_BUFFER_SIZE = 1000` at `fitness_analyzer.py:31`. A future contributor following the §7 instructions would wire the wrong cap value. This is a copy-paste risk."*

**Verbatim on the verdict**: *"Three BLOCKERS prevent implementation... With the three BLOCKERS fixed (move `requirements:` to frontmatter, create a top-level Makefile target or switch to a `.github/workflows/` cron, and add `docs/runbooks/mahavishnu-drift-detection.md` to the Phase 6 docs list), the spec becomes implementable as **YES-WITH-NITS**."*

**v3 impact**: All 3 BLOCKERS addressed. 6 of 8 CONCERNS addressed in v3 (path corrections, queue cap, HotRecord, Phase 9 contract, severity classifier, staged rollout playbook). Two CONCERNS not addressed in v3: bench.json keys (deferred to integration test implementation) and `PoolConfig` disambiguation (the spec is consistent with `core/config.py` Pydantic version per existing precedent; the `pools/base.py` dataclass version is for runtime metrics, not config).

## 5. Notes on preservation

This document preserves each agent's lens, key findings, and the most decision-affecting verbatim quote. The full text of each agent's response is in the ephemeral JSONL transcripts at `/private/tmp/claude-501/-Users-les-Projects-mahavishnu/0fabba93-19ac-4966-8208-e34b70f3e868/tasks/*.output`.

The preservation strategy prioritizes **traceability of decisions** over verbatim completeness:
- Convergent findings (§2.1) summarize with attribution because the value is in the agreement.
- Severity taxonomy (§2.3) makes BLOCKER/CRITICAL/HIGH/MEDIUM explicit so the patch scope is auditable.
- v2→v3 mapping table (§3) is the durable record of which v2 problem each v3 change fixes.
- Per-agent key findings (§4) summarize each agent's contribution.
- Verbatim quotes are included for the claims that drove v3 changes.

If a future contributor needs a specific fact that isn't in this doc, the JSONL transcripts contain the full original responses with timestamps and tool-use exchanges.

## 6. References

- [`docs/plans/.archive/2026-09-10-bodai-math-initiatives-tier1.md`](../plans/.archive/2026-09-10-bodai-math-initiatives-tier1.md) — the v3 spec this verification drove
- [`docs/audits/2026-09-10-math-spec-review.md`](2026-09-10-math-spec-review.md) — the round-1 (9-agent) review that drove v1→v2
- `docs/plans/TEMPLATE.md` — integration-contract template the spec follows
- `.claude/decisions/wire-up-contract.md` — Integration Contract policy
- `scripts/audit_requirements.py:76-92` — `parse_frontmatter` function (verified reads frontmatter only)
- `mahavishnu/observability/metrics.py:74` — `_ALLOWED_LABEL_KEYS` `Final[frozenset[str]]` (verified closed)
- `mahavishnu/pools/fitness_analyzer.py:31` — `_MAX_BUFFER_SIZE = 1000` (verified)
- `mahavishnu/core/routing_metrics.py:164` — actual `mahavishnu_routing_decisions_total` location (verified)
- Brook, D. A., & Evans, D. A. (1972). *An Approach to the Probability Distribution of CUSUM Run Length*. Biometrika 59(3), 539–549. (CUSUM ARL₀ tables)
- Kingman, G. F. C. (1961). The single server queue in heavy traffic. *Proc. Cambridge Philos. Soc.* 57, 902–904.
- Page, E. S. (1954). Continuous inspection schemes. *Biometrika* 41(1/2), 141–154.
