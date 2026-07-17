---
status: complete
role: historical
date: 2026-07-16
last_reviewed: 2026-07-16
superseded_by: null
topic: convergence-control-plane
---

# MiniMax 2.7 Provider Migration Plan

**Date:** 2026-05-10
**Status:** `complete`, `historical`  <!-- legacy status: complete, historical — see YAML frontmatter -->
**Owner:** Core Eng
**Scope:** Mahavishnu, Bifrost text setup, Crackerjack, and Session-Buddy. Oneiric and mcp-common are referenced only for non-blocking terminal-worker guardrails.
**Purpose:** Replace ZAI/GLM as the default cloud LLM API path with MiniMax M2.7 while preserving local Ollama fallback and documenting modality routing limits.

## 1. Outcome

Bodai should have one provider-default story:

1. MiniMax is the primary cloud API/gateway provider for text, code, reasoning, search-heavy, and background LLM work.
1. `MiniMax-M2.7` is the default high-quality model.
1. `MiniMax-M2.7-highspeed` is the default fast/background/high-throughput model.
1. Bifrost no longer routes default Bodai requests to ZAI GLM models.
1. ZAI is demoted to optional configurable support only, or removed from defaults where the repo has no active compatibility requirement.
1. Image, audio, and video work uses MiniMax's current modality-specific models only where the integration surface supports those APIs.
1. Each repo has tests proving the configured provider chain, model names, env vars, and fallback behavior.

## 2. Source Verification

MiniMax source checks completed 2026-05-10:

| Capability | Verified model/API target | Source |
|---|---|---|
| Text/code/reasoning default | `MiniMax-M2.7` | MiniMax models guide and API overview |
| Fast/background text | `MiniMax-M2.7-highspeed` | MiniMax models guide and API overview |
| OpenAI-compatible text base URL | `https://api.minimax.io/v1` | MiniMax Compatible OpenAI API docs |
| Audio/TTS | `speech-2.8-turbo` for low-latency default, `speech-2.8-hd` for quality tier | MiniMax API overview |
| Video | `MiniMax-Hailuo-2.3` for text-to-video/image-to-video, `MiniMax-Hailuo-2.3-Fast` for efficient image-to-video | MiniMax API overview |
| Image generation | `image-01` | MiniMax API overview |

Reference URLs:

- `https://platform.minimax.io/docs/guides/models-intro`
- `https://platform.minimax.io/docs/api-reference/api-overview`
- `https://platform.minimax.io/docs/api-reference/text-openai-api`

Implementation note: MiniMax M2.7 is the text LLM family. Current MiniMax audio, video, and image APIs use separate model families (`speech-2.8-*`, `MiniMax-Hailuo-*`, `image-01`). Do not invent image/audio/video model IDs with an `M2.7` suffix.

## 3. Non-Goals

1. Do not remove Ollama local fallback.
1. Do not hard-code API keys, local paths, or account-specific subscription details.
1. Do not make Bifrost mandatory for callers that already support direct provider configuration.
1. Do not route non-text modality tasks through OpenAI-compatible chat unless MiniMax docs explicitly support that input type for the endpoint.
1. Do not delete ZAI support before all live config, docs, and tests no longer assume it as default.

## 4. Provisional Provider Decisions

These decisions are the intended target state. M0 must either accept them as final per repo or update this table before M1-M4 implementation starts.

| Concern | Decision |
|---|---|
| Provider id | Use `minimax` in repo-local configs and `minimax-openai` in Bifrost-qualified model names. |
| API key env var | `MINIMAX_API_KEY` |
| Direct client base URL | `MINIMAX_BASE_URL`, default `https://api.minimax.io/v1` for OpenAI-compatible text. |
| Bifrost base/path split | `network_config.base_url=https://api.minimax.io` plus request override `/v1/chat/completions`, unless Bifrost schema verification proves a different rendered URL is required. |
| Default text model | `MiniMax-M2.7` |
| Fast text model | `MiniMax-M2.7-highspeed` |
| Default fallback chain | Proposed `["minimax", "ollama"]`; M0 must record any repo-specific third-party fallback exception. |
| Optional ZAI position | Proposed optional configurable provider, disabled by default; M0 must decide per repo whether ZAI is retained or removed. |
| Local fallback | Preserve current Ollama/Qwen local model defaults unless separately replaced. |
| Terminal worker defaults | Local worker defaults now use `terminal-claude` in Mahavishnu. Keep terminal-worker support provider-neutral and CLI-local; do not reintroduce a cloud-provider default into the terminal path. |

## 5. Program Tracker

| Phase | Name | Status | Blocking dependency | Primary deliverable |
|---|---|---:|---|---|
| M0 | Inventory and acceptance gates | `draft` | none | final file-level migration checklist and owner approval |
| M1 | Mahavishnu provider defaults | `completed` | M0 complete, plan active | `minimax` provider config, task routing, gateway defaults, docs/tests |
| M2 | Bifrost text routing migration | `completed` | M0 complete, source-verified Bifrost MiniMax config | `minimax-openai` text routes and explicit modality deferrals or supported speech routes |
| M3 | Session-Buddy provider defaults | `completed` | M0 complete | settings/provider manager migration and tests |
| M4 | Crackerjack provider support | `completed` | M0 complete | MiniMax AI provider adapter/config, Qwen/ZAI default cleanup, tests |
| M5 | Cross-repo validation and cleanup | `completed` | M1-M4 complete | no default ZAI/GLM refs, docs aligned, rollback notes retained |

## 6. Phase M0: Inventory And Acceptance Gates

**Goal:** Freeze the exact scope before editing runtime behavior.

Tasks:

- [x] Verify current MiniMax model/API names against official docs.
- [x] Identify Mahavishnu ZAI/GLM config and routing surfaces.
- [x] Identify Bifrost ZAI/GLM provider and route surfaces.
- [x] Identify Session-Buddy ZAI defaults and provider-manager surfaces.
- [x] Identify Crackerjack provider enum/config surfaces and Qwen-oriented provider fallback assumptions.
- [x] Owner accepts this plan and promotes it from `draft, implementation` to `active, implementation`.
- [x] Decide whether ZAI remains as an optional configurable provider after migration or is fully removed from each repo's supported provider list.
- [x] Decide whether Crackerjack should default to MiniMax over Claude, or only add MiniMax as the preferred non-Claude fallback.
- [x] Decide whether any worker execution should use an API/gateway worker path; if not, terminal worker defaults remain CLI-local and outside provider-default scope.

Acceptance criteria:

- Every ZAI/GLM default that will change has an owning phase.
- Open decisions in Section 4 and M0 are resolved before code changes begin.
- Plan index lists this plan as the canonical provider migration tracker.

Validation:

- Review `rg -n "zai|ZAI|glm|GLM|minimax|MiniMax|qwen|QWEN" /Users/les/Projects/mahavishnu /Users/les/Projects/crackerjack /Users/les/Projects/session-buddy`.
- Review `git diff -- docs/plans/PLAN_INDEX.md docs/plans/2026-05-10-minimax27-provider-migration.md docs/plans/2026-05-10-bodai-control-plane-convergence-plan.md`.

## 7. Phase M1: Mahavishnu Provider Defaults

**Goal:** Make Mahavishnu's native LLM defaults point at MiniMax.

Known surfaces:

| Surface | Required change |
|---|---|
| `settings/models.yaml` | Replace `zai` primary provider with `minimax`, `MINIMAX_API_KEY`, `MINIMAX_BASE_URL`, `MiniMax-M2.7`, and `MiniMax-M2.7-highspeed`. Change `default_provider` and `fallback_chain`. |
| `mahavishnu/core/config.py` | Add `minimax` to shared Agno provider enums and documentation so settings validation matches runtime provider support. |
| `mahavishnu/workers/task_router.py` | Replace or deprecate `DEFAULT_ZAI_ROUTING` with `DEFAULT_MINIMAX_ROUTING`. Use M2.7 for code/reasoning/general and M2.7-highspeed for quick/swarm/background. |
| `mahavishnu/llm_gateway/client.py` | Add `minimax-openai` provider namespace and update default protocol provider where appropriate. |
| `mahavishnu/llm_gateway/contract.py` | Preserve `image`/`vision` route class; add `audio` and `video` route classes only if callers can send those task types through the gateway contract. |
| `mahavishnu/engines/agno_adapter_impl.py` and `mahavishnu/workers/cloud_worker.py` | Replace ZAI env/default assumptions with MiniMax equivalents or provider-neutral configuration. |
| `settings/agno_teams/*.yaml` | Replace GLM team model IDs with MiniMax defaults. |
| `README.md`, `CLAUDE.md`, and LLM/Bifrost docs | Replace ZAI-primary language with MiniMax-primary language while keeping optional ZAI compatibility explicitly non-default. |

Tasks:

- [x] Add `minimax` provider config to `settings/models.yaml`.
- [x] Demote `zai` to disabled optional configurable provider, or remove it if M0 decides full removal.
- [x] Replace GLM task routing with MiniMax routing.
- [x] Update Agno team models.
- [x] Add `minimax` to shared Agno provider enums and config docs.
- [x] Update LLM gateway provider namespace and tests.
- [x] Update docs that describe ZAI as the primary cloud provider.
- [x] Add config tests that assert default provider is `minimax`, fallback is `minimax -> ollama`, and no GLM model remains in default routing.
- [x] Update Session-Buddy provider defaults, provider manager, security helpers, YAML defaults, and tests so `minimax` is the default cloud provider.
- [x] Add Crackerjack MiniMax provider support, provider selection wiring, registry metadata, example config, and tests.

Acceptance criteria:

- Mahavishnu default cloud LLM path resolves to MiniMax.
- Existing local Ollama fallback still works.
- ZAI is not the first provider in any default chain.
- GLM model names remain only in explicitly labeled optional ZAI compatibility sections, if retained.

Validation:

- `uv run pytest tests/unit -k "llm or gateway or router or config"`
- `uv run ruff check mahavishnu tests`
- `python -m json.tool config/bifrost/config.template.json >/dev/null`

## 8. Phase M2: Bifrost Text Routing Migration

**Goal:** Replace ZAI GLM text gateway routes with MiniMax OpenAI-compatible text routes and explicitly defer unsupported image/video generation routes.

Known surfaces:

| Surface | Required change |
|---|---|
| `config/bifrost/config.template.json` | Replace `zai-openai` provider with `minimax-openai`; use `env.MINIMAX_API_KEY`; Bifrost base/path split should render `https://api.minimax.io/v1/chat/completions`. |
| `config/bifrost/README.md` | Replace ZAI setup, route examples, failure notes, and model examples. |
| Routing rules | Change `think`, `long_context`, and `web_search` to `MiniMax-M2.7`; change `background`, `cheap`, and `high_throughput` to `MiniMax-M2.7-highspeed`. |
| Image route | Do not implement through Bifrost unless Bifrost supports the required image-generation operation type. Prefer a direct MiniMax adapter for `image-01`; otherwise defer. |
| Audio route | Add only if Bifrost supports the needed speech/transcription request type; point TTS/audio-generation to `speech-2.8-turbo` by default and `speech-2.8-hd` for quality tier. |
| Video route | Do not implement through Bifrost unless Bifrost supports the required video-generation operation type. Prefer a direct MiniMax adapter for `MiniMax-Hailuo-2.3` or `MiniMax-Hailuo-2.3-Fast`; otherwise defer. |

Tasks:

- [x] Verify Bifrost custom provider support for MiniMax OpenAI-compatible text and confirm the final rendered URL is not missing or duplicating `/v1`.
- [x] Replace `zai-openai/*` routing fallbacks with `minimax-openai/*`.
- [x] Remove `anthropic` provider entries that only exist for ZAI unless a MiniMax Anthropic-compatible provider is explicitly configured.
- [x] Add speech/transcription routes only if confirmed by Bifrost support; otherwise document the explicit deferment and keep image/video generation on direct MiniMax adapters or future Bifrost support.
- [x] Update smoke-test docs and local validation commands.

Acceptance criteria:

- No default Bifrost route points at `zai-openai` or GLM.
- Text routes use MiniMax OpenAI-compatible chat.
- Unsupported modality routes are explicitly deferred with a reason and no misleading route.
- Bifrost docs distinguish text multimodal chat from image/audio/video generation APIs.

Validation:

- `python -m json.tool config/bifrost/config.template.json >/dev/null`
- `curl -sS http://127.0.0.1:8471/v1/models` when Bifrost is running.
- Contract smoke request for `x-bf-task: think`.
- Contract smoke request for every enabled modality route; do not require image/video Bifrost smoke tests when those routes are deferred.

## 9. Phase M3: Session-Buddy Provider Defaults

**Goal:** Make Session-Buddy use MiniMax as the default cloud provider without breaking session-local fallback behavior.

Known surfaces:

| Surface | Required change |
|---|---|
| `settings/session-buddy.yaml` | Change `default_provider` to `minimax`, fallback list to `minimax -> ollama`, and add `minimax_base_url`/`minimax_default_model`. |
| `session_buddy/llm_providers.py` | Add MiniMax key lookup, env var handling, config build, provider registry, masking, validation, and default fallback behavior. |
| `session_buddy/settings.py` | Add settings fields for `minimax_api_key`, `minimax_base_url`, and `minimax_default_model` if missing. |
| `session_buddy/llm/providers/openai_provider.py` | Reuse OpenAI-compatible implementation unless MiniMax-specific request options require a provider subclass. |
| `CLAUDE.md` and provider docs | Replace ZAI-primary setup with MiniMax-primary setup. |

Tasks:

- [ ] Add MiniMax provider config and env var support.
- [ ] Change default provider/fallback chain.
- [ ] Keep ZAI as optional configurable provider only if M0 decides to preserve it.
- [ ] Update API-key startup validation.
- [ ] Update tests that currently assert `zai` defaults.

Acceptance criteria:

- Fresh Session-Buddy settings resolve default provider `minimax`.
- `MINIMAX_API_KEY` is discovered and masked correctly.
- Missing MiniMax key produces the same class of operator-facing warning as other cloud providers.
- Ollama fallback remains available.

Validation:

- `uv run pytest tests/unit/test_llm_providers.py tests/unit/test_settings_defaults.py`
- `uv run ruff check session_buddy tests`

## 10. Phase M4: Crackerjack Provider Support

**Goal:** Add MiniMax as a first-class Crackerjack AI-fix provider and remove Qwen/ZAI-like assumptions from default non-Claude fallback paths.

Known surfaces:

| Surface | Required change |
|---|---|
| `crackerjack/config/settings.py` | Add `minimax` to `ai_providers` and `ai_provider` literals. Decide default position in M0. |
| `crackerjack/adapters/ai/registry.py` | Add `ProviderID.MINIMAX`, provider metadata, factory wiring, and fallback-chain docs. |
| `crackerjack/adapters/ai/qwen.py` | Extract OpenAI-compatible provider base if practical, then reuse it for MiniMax rather than copying adapter logic. |
| `settings/qwen.example.yaml` | Add `settings/minimax.example.yaml`; optionally mark Qwen example as legacy/non-default. |
| Provider docs/tests | Add MiniMax tests and update provider architecture docs. |

Tasks:

- [ ] Decide Crackerjack provider ordering: `minimax -> claude -> ollama`, `claude -> minimax -> ollama`, or opt-in-only MiniMax.
- [ ] Add `MiniMaxCodeFixer` via a generic OpenAI-compatible base class or minimal subclass.
- [ ] Add env vars `MINIMAX_API_KEY`, `MINIMAX_BASE_URL`, and `MINIMAX_DEFAULT_MODEL`.
- [ ] Add provider registry metadata for MiniMax M2.7.
- [ ] Update tests for settings validation, provider parsing, factory creation, availability checks, and fallback chain behavior.
- [ ] Update docs and examples.

Acceptance criteria:

- Crackerjack can run AI-fix provider selection with MiniMax in the configured chain.
- Existing Claude and Ollama behavior does not regress.
- Qwen remains available only if intentionally retained; it is not presented as the recommended non-local fallback after this migration.

Validation:

- `uv run pytest tests/unit/test_config_settings.py tests/unit/services/test_config_service.py`
- `uv run pytest tests -k "provider or ai_fix or qwen or minimax"`
- `uv run ruff check crackerjack tests`

## 11. Terminal Worker Guardrails

**Goal:** Keep provider-default migration from creating unnecessary terminal-worker classes.

Decision:

- Do not create a dedicated `TerminalMinimaxWorker` class for MiniMax API usage.
- Treat MiniMax primarily as an API/gateway provider through M1/M2/M3/M4, not as a terminal worker.
- Add `terminal-minimax` only as a registry entry, and only if a real MiniMax CLI or approved wrapper exists with stable command-line behavior.
- Keep broader provider-neutral terminal protocol work in a separate refactor plan; it must not block M5.
- Distinguish LLM API/gateway provider defaults from terminal worker defaults. Current terminal workers may remain CLI-local unless a separate API/gateway worker path is accepted.

Known Mahavishnu surfaces:

| Surface | Required change |
|---|---|
| `mahavishnu/workers/registry.py` | Existing declarative worker entries are the baseline. Add `terminal-minimax` only for a real CLI/wrapper. |
| `mahavishnu/workers/generic_shell.py` | Existing generic CLI-backed worker path remains the immediate terminal execution path. |
| `mahavishnu/workers/terminal.py` | Do not add new provider-specific branching for MiniMax. Any broader cleanup belongs in a separate terminal-worker refactor plan. |
| `mahavishnu/core/adapters/worker.py` | Existing `terminal-qwen` fallback remains terminal-worker behavior unless M0 accepts an API/gateway worker path. |

Tasks:

- [ ] Do not add `terminal-minimax` unless backed by a real CLI/wrapper; otherwise document MiniMax as API-only.
- [ ] Add tests or assertions that existing registry-backed terminal workers still produce the expected `WorkerResult` contract if provider-default changes touch worker code.
- [ ] If a provider-neutral terminal protocol is still desired, create a separate plan and add it to `PLAN_INDEX.md` rather than blocking this migration.

Acceptance criteria:

- Provider API defaults do not create fake terminal workers.
- MiniMax provider work remains routed through API/gateway code unless a CLI exists.
- Qwen/Claude terminal behavior remains compatible.

Validation:

- If worker code changes: `uv run pytest tests/unit -k "worker or terminal or registry"`
- `uv run ruff check mahavishnu tests`

## 12. Phase M5: Cross-Repo Validation And Cleanup

**Goal:** Ensure the migration is complete, traceable, and reversible.

Tasks:

- [x] Run cross-repo search for remaining default ZAI/GLM references.
- [x] Classify remaining ZAI/GLM refs as `optional support`, `test fixture`, `historical docs`, or `bug`.
- [x] Update docs so operators use `MINIMAX_API_KEY`, not `ZAI_API_KEY`, for default cloud operation.
- [x] Add rollback note for temporarily restoring ZAI as a fallback if MiniMax account/API issues block operation.
- [x] Update plan statuses and record validation commands/results.

Rollback note:

- If MiniMax is temporarily unavailable, restore `zai` only as an explicit non-default compatibility provider for the affected environment.
- Prefer a scoped config override instead of changing repo defaults globally.
- Revert the default provider only long enough to regain service, then re-cut back to MiniMax.

Acceptance criteria:

- No default config routes to ZAI or GLM.
- No doc states ZAI is the primary Bodai cloud provider.
- Remaining ZAI references are explicitly optional/configurable or historical.
- Plan index and convergence relationship are current.

Validation:

- `rg -n "zai|ZAI|glm|GLM" /Users/les/Projects/mahavishnu /Users/les/Projects/crackerjack /Users/les/Projects/session-buddy /Users/les/Projects/oneiric /Users/les/Projects/mcp-common`
- `rg -n "MINIMAX_API_KEY|MiniMax-M2.7|minimax" /Users/les/Projects/mahavishnu /Users/les/Projects/crackerjack /Users/les/Projects/session-buddy /Users/les/Projects/oneiric /Users/les/Projects/mcp-common`
- Repo-local targeted test commands from M1-M4.
- Run the repo-approved Crackerjack quality gate for every touched repo and attach result artifacts.

## 13. Relationship To Control-Plane Convergence

This plan is a sidecar migration for provider defaults. It should not block C1-C7 control-plane convergence unless a phase directly depends on LLM task routing.

Integration points:

- C3 operator cockpit should display MiniMax provider status once provider defaults change.
- C4 catalog drift prevention should verify provider defaults and env vars across Mahavishnu, Crackerjack, and Session-Buddy.
- C5 incident-to-fix golden path should run with MiniMax as the default non-local provider.
- C6 deletion pass should not delete ZAI compatibility code until M5 classifies remaining ZAI references and confirms no active default path depends on them.

## 14. Review Log

| ID | Date | Source | Severity | Finding | Disposition |
|---|---|---|---:|---|---|
| MM1 | 2026-05-10 | plan author | P0 | User requested image/audio/video routing to the appropriate MiniMax version, but MiniMax M2.7 is not the modality family for all three. | resolved: plan routes text to M2.7 and modality work to official MiniMax modality models. |
| MM2 | 2026-05-10 | plan author | P1 | Crackerjack currently has Claude/Qwen/Ollama provider enums, not an obvious ZAI provider. | resolved: plan treats Crackerjack as MiniMax provider-addition/default-cleanup rather than direct ZAI rename. |
| MM3 | 2026-05-10 | plan author | P1 | Bifrost image route currently appears to mean vision/multimodal chat, while MiniMax OpenAI-compatible text docs say image/audio inputs are not currently supported. | resolved: plan gates image/audio/video routes on API-specific Bifrost support and forbids misleading chat-route reuse. |
| MM4 | 2026-05-10 | multi-agent review | P1 | Bifrost modality routing was overstated for image/video generation support. | resolved: M2 is now text-first, speech-only-if-supported, and image/video deferred to direct adapter or future Bifrost support. |
| MM5 | 2026-05-10 | multi-agent review | P1 | Terminal worker protocol work should not block provider migration. | resolved: M4a removed as blocking phase and replaced with non-blocking guardrails. |
| MM6 | 2026-05-10 | multi-agent review | P2 | Direct MiniMax base URL and Bifrost base/path split were easy to confuse. | resolved: Section 4 and M2 now distinguish direct client base URL from Bifrost rendered URL. |
| MM7 | 2026-05-10 | multi-agent review | P2 | Provider defaults were blurred with terminal-worker defaults. | resolved: Section 4 and terminal guardrails now make terminal workers explicitly out of provider-default scope unless an API/gateway worker path is accepted. |
| MM8 | 2026-05-10 | multi-agent review | P2 | MiniMax plan had no progress log. | resolved: added progress log. |

## 15. Progress Log

Use this log for implementation updates that change phase status.

| Date | Phase | Change | Validation |
|---|---|---|---|
| 2026-05-10 | M0 | Initial MiniMax migration plan drafted and indexed | MiniMax docs source check; `git diff --check` |
| 2026-05-10 | M0 | Multi-agent review completed; Bifrost modality, terminal-worker, base URL, scope, and progress-tracking findings incorporated | Review log MM4-MM8; `git diff --check` |
| 2026-05-10 | M1 | Mahavishnu runtime cutover and config guardrails landed; code-level ZAI aliases removed | `uv run pytest --no-cov tests/unit/test_config.py tests/unit/test_llm_gateway_client.py tests/unit/test_cloud_worker.py tests/unit/test_task_router_and_auth.py tests/unit/pools/test_gpu_handler_pool.py` |
| 2026-05-10 | M1 | Shared Agno config enum and MiniMax factory test landed | `uv run pytest --no-cov tests/unit/engines/test_agno_adapter.py tests/unit/test_config.py` |
| 2026-05-10 | M2 | Bifrost template/docs moved to MiniMax text routes; optional z.ai Anthropic provider removed from template defaults; speech/transcription support explicitly deferred pending Bifrost API support | `python -m json.tool config/bifrost/config.template.json >/dev/null`, `git diff --check` |
| 2026-05-10 | M1 | Environment-manager docs aligned with MiniMax-first cloud examples and file-secret keys | `git diff --check` |
| 2026-05-10 | M1 | Terminal worker default moved from `terminal-qwen` to `terminal-claude` across config, adapter, CLI, and pool/MCP defaults | `git diff --check` |
| 2026-05-10 | M1 | Active README and MCP tool docs aligned with terminal-claude as the default worker type | `git diff --check` |
| 2026-05-10 | M1 | Cloud worker docs and optional Qwen registry comments clarified as MiniMax/OpenAI-compatible primary with Qwen retained only as optional non-default | `git diff --check` |
| 2026-05-10 | M1 | Gateway resume prompt and LLM inventory reclassified Qwen as configurable optional rather than primary | `git diff --check` |
| 2026-05-10 | M1 | Removed the live Qwen provider block from `settings/models.yaml`; inventory now labels Qwen as configurable non-default external path | `git diff --check` |
| 2026-05-10 | M1 | README and inventory doc reworded Qwen as supported non-default worker / configurable fallback instead of primary path | `git diff --check` |
| 2026-05-10 | M1 | Mahavishnu-side MiniMax cutover complete; next work is M2 Bifrost verification plus external-repo M3/M4 follow-through | `git diff --check` |
| 2026-05-10 | M5 | Active operator docs updated to make MiniMax primary and ZAI optional/non-default; rollback note recorded; phase completed | `git diff --check` |
| 2026-05-10 | M2 | Bifrost MiniMax text routing source-verified; config template renders `https://api.minimax.io/v1/chat/completions` and image/video routes remain deferred | `python -m json.tool config/bifrost/config.template.json >/dev/null`, `git diff --check` |
| 2026-05-10 | M1 | Active terminal/operator docs normalized so `terminal-qwen` reads as supported non-default compatibility in current usage docs | `git diff --check` |
| 2026-05-10 | M3 | Session-Buddy default provider cutover to MiniMax landed; provider manager, YAML defaults, and compatibility helpers updated | `uv run pytest --no-cov /Users/les/Projects/session-buddy/tests/unit/test_llm_providers.py /Users/les/Projects/session-buddy/tests/integration/test_zai_fallback_chain.py` |
| 2026-05-10 | M4 | Crackerjack MiniMax provider support landed; registry, provider-selection wiring, example config, and provider-chain tests updated | `uv run pytest --no-cov /Users/les/Projects/crackerjack/tests/adapters/test_provider_chain.py /Users/les/Projects/crackerjack/tests/unit/test_config_settings.py` |
