---
status: active
role: canonical
topic: followups-index
date: 2026-07-16
last_reviewed: 2026-07-16
superseded_by: null
blocks_on: []
---

# `docs/followups/` index

One-line summary: dated follow-up notes — each pairs a bug/task with its
investigation and (when closed) its resolution. This file is the index and
the single source of truth for each note's state; update it whenever a note
is added, resolved, or archived.

## Active follow-ups

Sorted newest-first. **Verified state** is the state confirmed against the
*current code* by the 2026-07-16 audit — which may differ from a note's own
`**Status:**` line (see [Lifecycle](#lifecycle)).

| File | Topic | Verified state (2026-07-16) |
|------|-------|------------------------------|
| `2026-07-27-acp-v15-followups.md` | 7 v1.5 items deferred from the ACP server build plan: session persistence (`session/load`), MCP-over-ACP tunnel, Remote ACP (Streamable HTTP), UUID v7 session IDs, additional session methods (`list`/`resume`/`set_mode`/`close`/`delete`/`logout`), license declaration reconciliation, Toad-integration smoke. | 🔴 **Open** — all 7 awaiting triggers; v1.5.6 (license reconciliation) can ship independently now (one-line fix; tracked in a separate GitHub issue). Other 6 ship in two contexts: persistence bundle (v1.5.1 + v1.5.4 + v1.5.5) when v1.0 is `adopted`; reactive (v1.5.2 MCP-over-ACP, v1.5.3 Remote ACP) when their respective upstream specs stabilize. |
| `2026-07-15-sb-checkpoint-stash-clobber.md` | Recurring: auto-checkpoint hook re-applies a `git stash` over in-flight subagent edits. | 🔴 **Open** — second observation; fix only *proposed* (Options A/B/C). Culprit lives in external `session-buddy` repo. |
| `2026-09-05-backup-cli-broad-typer-exit.md` | `_do_backup_restore`/`_do_backup_create` broad `except Exception` catches the `typer.Exit` raised on the False path → user sees both "Restore failed" and "Restore error:" on a benign failure. | ✅ **Resolved** — production fix at `mahavishnu/backup_cli.py:20-31,67-78`; regression test `test_backup_cli_extended.py::test_restore_command_handles_false_result` now asserts `"Restore error:" not in result.output`. |
| `2026-09-05-agno-memory-field-validator-silent-skip.md` | `AgnoMemoryConfig.validate_connection_string` is a `@field_validator` that does NOT run when `connection_string` is omitted → postgres backend silently accepted without connection string. | ✅ **Resolved** — production fix at `mahavishnu/core/config.py:131-149` (model_validator); regression tests `test_mahavishnu_config.py::test_connection_string_required_for_postgres` (tightened) + `test_config_extended.py::TestAgnoMemoryConnectionString::test_postgres_backend_with_explicit_none_raises` (already pinned). |
| `2026-09-05-metrics-schema-p50-formula.md` | `calculate_percentiles` p50 branch returns lower-of-two-middles instead of textbook median (`index = (len-1)//2 - 1` vs `len//2`). | ✅ **Resolved** — production fix at `mahavishnu/core/metrics_schema.py:320` (`index = len // 2`); 9 test assertions updated across `test_metrics_schema.py` and `test_metrics_schema_extended.py`. |
| `2026-09-05-metrics-schema-no-input-validation.md` | `calculate_percentiles` silently accepts negative or >100 percentile values. | ✅ **Resolved** — production fix at `mahavishnu/core/metrics_schema.py:316-317` (`ValueError` if outside `[0, 100]`); regression tests `test_metrics_schema_extended.py::test_negative_percentile_raises_value_error` + `::test_percentile_over_100_raises_value_error`. |
| `2026-09-05-metrics-schema-confidence-dead-parameter.md` | `calculate_confidence_interval` declares `confidence: float = 0.95` parameter but always uses hardcoded `z = 1.96`; threshold `< 10` is a magic literal. | ✅ **Resolved** — production fix at `mahavishnu/core/metrics_schema.py:329-342` (new `_Z_SCORES` lookup) + line 330-331 (`_MIN_SAMPLE_SIZE_FOR_CI` constant); regression tests `test_metrics_schema_extended.py::test_higher_confidence_yields_wider_interval` + `::test_unknown_confidence_falls_back_to_1_96`. |
| `2026-09-05-permissions-dead-cache-fields.md` | `PermissionChecker._cached_accessibility` and `_cached_screen_recording` are set in `__init__` but never read or written anywhere else. | ✅ **Resolved** — production fix at `mahavishnu/automation/permissions.py:69-71` (fields deleted); regression test `test_permissions_extended.py::test_init_records_platform_flag` asserts `not hasattr(checker, "_cached_accessibility")`. |
| `2026-09-05-permissions-accessibility-prompt.md` | `request_accessibility` hard-codes `{"kAXTrustedCheckOptionPrompt": True}`; no way for CI caller to suppress the system permission dialog. | ✅ **Resolved** — production fix at `mahavishnu/automation/permissions.py:190-217` (new `prompt: bool = True` parameter); regression tests `test_permissions_extended.py::test_macos_options_contain_prompt_flag` + `::test_macos_prompt_false_skips_dialog`. |
| `2026-09-05-permissions-mutable-dataclass.md` | `PermissionInfo` dataclass is mutable; `recovery_hint` can be clobbered by another caller sharing the instance. | ✅ **Resolved** — production fix at `mahavishnu/automation/permissions.py:26` (`@dataclass(frozen=True)`); regression test `test_permissions_extended.py::test_permission_info_is_frozen`. |
| `2026-09-05-beartype-pytest-cov-py314.md` | `pytest --cov` triggers a `beartype.claw._clawstate` partial-initialization `ImportError` on every run after the first, due to a meta-path import-hook re-entrance race under Python 3.14. | ✅ **Resolved** — operational fix at `tests/unit/conftest.py:7-18` (`os.environ.setdefault("BEARTYPE_DISABLE_CLI_HOOKS", "1")`); canonical coverage gate now runs cleanly. The originally-proposed `beartype>=0.23` pin was *not* viable — `0.22.9` is still the latest PyPI release as of 2026-09-05. |
| `2026-09-05-worker-status-isoformat-crash.md` | `worker_status` `try/except` guards the timestamp subtraction but not the subsequent `.isoformat()` call → corrupted records with non-datetime `last_seen_at` crash the call. | ✅ **Resolved** — production fix at `mahavishnu/mcp/tools/worker_contract_tools.py:217-230` (isoformat call moved into the same try block); regression test `test_worker_contract_tools.py::test_workflow_status_handles_malformed_non_datetime`. |
| `2026-09-05-terminal-send-regex-mismatch.md` | `SessionID` Annotated regex `[a-zA-Z0-9_-]` rejects legitimate adapter IDs (e.g. macOS Terminal dots). | ✅ **Resolved** — production fix at `mahavishnu/mcp/tools/terminal_tools.py:20-26` (regex widened to `[a-zA-Z0-9._-]`); regression test `test_terminal_tools.py::TestTerminalSend::test_session_id_with_dots_accepted`. |
| `2026-09-05-terminal-close-all-empty-id-roundtrip.md` | `terminal_close_all` coerces missing IDs to `""` and round-trips them to `manager.close_all`. | ✅ **Resolved** — production fix at `mahavishnu/mcp/tools/terminal_tools.py:168-180` (filter added); regression tests `test_terminal_tools.py::TestTerminalCloseAll::test_close_all_handles_missing_ids` (updated) + `::test_close_all_skips_all_empty_ids` (new). |
| `2026-09-05-websocket-broadcaster-default.md` | `getattr(settings, "websocket_enabled", True)` silently defaults to ON for malformed settings; `WebSocketBroadcaster.__init__` requires `server` positionally. | ✅ **Resolved** — production fixes at `mahavishnu/websocket/integration.py:66` (default flipped to `False`, fail-closed) and `:303` (`server: ... \| None = None`); regression tests `test_websocket_module_integration.py::TestStartWebSocketServerDisabled::test_default_websocket_enabled_setting_is_false` (renamed from `_is_true`) + `::TestWebSocketBroadcasterHelper::test_init_no_args`. |
| `2026-06-29-crow-mcp-client-wiring.md` | `mahavishnu mcp start` crash — crow adapter constructed with `mcp_client=None`. | ✅ **Addressed** for stated scope (helper + 3 call sites + tests). Adjacent gaps: no end-to-end env-precedence test; `core/adapters/worker.py:72-75` non-CLI caller still passes `None`. |
| `2026-06-29-dlq-silent-fallback.md` | DLQ silently falls back to a per-process in-memory deque when OpenSearch is down (data loss). | *archived* — see `.archive/` row. |
| `2026-06-29-opensearch-diverged-flags.md` | Duplicate `OPENSEARCH_AVAILABLE` flags can diverge and silently swallow tasks. | ✅ **Resolved for live paths** — `opensearch_integration.py` + `dead_letter_queue.py` share `opensearch_constants.py` (guard test enforces it). Residual: the **deprecated, test-only** `workflow_state.py:17-23` keeps its own flag, but its OpenSearch path is retired — no live divergence risk. |
| `2026-09-05-terminal-validate-command-safety.md` | `validate_command_safety` substring matching blocks legitimate ops (`pkill`, `killall`, `kill -9`, `&& rm`, `ncat` matching `concat`, etc.). | 🔴 **Open — behavioral decision required** — locked-in test suite at `tests/unit/mcp/tools/test_terminal_tools.py:273-300` enforces strict mode; changing it requires maintainer sign-off and an updated test parametrization. Note filed 2026-09-05; remediation deferred to a dedicated brief. |
| `2026-09-05-mahavishnu-pool-error-code-attribute.md` | `MahavishnuPool.start()` referenced nonexistent `MahavishnuError.code` attribute (ty error). | ✅ **Resolved** — production fix at `mahavishnu/pools/mahavishnu_pool.py:113` (`exc.code` → `exc.error_code`); regression tests `test_mahavishnu_pool.py::test_start_swallows_resource_not_found_for_unknown_worker_type` + `::test_start_reraises_non_resource_not_found_errors` (both pass). |
| `2026-09-05-ai-dep-group-transitive-bloat.md` | `pydantic-ai-slim[mcp,openai,anthropic,google,groq]` pulls 5 LLM SDKs plus 10+ `google-cloud-*` packages (incl. secret-manager, storage) and 3 overlapping MCP packages. | 🟡 **Documented; deferred** — `ai` is already opt-in. Bloat is cosmetic unless install footprint matters. Suggested remediation: split into per-provider sub-groups. |
| `2026-09-05-integration-test-environmental-blockers.md` | 9 canonical-gate failures all environmental: `duckdb` not declared in deps (4), `session_buddy` cross-repo (5), `hatchet-sdk` opt-group (1), xdist state contamination in `test_worktree_mcp_tools` (4 — passes 9/9 in isolation). | 🟡 **Documented; not blocking** — confirmed each is environmental by running in isolation. Quick wins: add `pytest.importorskip("duckdb")` (4 fixes), `pytest.importorskip("hatchet_sdk")` (1 fix), `skipif` on session_buddy tests (5 fixes). |

## Archived (`.archive/`)

Resolved notes, kept for the record. These are **git-tracked and never
deleted** — `.gitignore` re-includes `docs/followups/.archive/` despite the
repo-wide `.archive/` ignore.

| File | Topic | Why archived |
|------|-------|--------------|
| `.archive/2026-07-15-comprehensive-hooks-cleanup-checkpoint.md` | Session checkpoint: 3-wave comprehensive-hooks cleanup (complexity refactor, ty/DRY fix, PEP 735 manifest reshuffle). | ✅ All described changes present in `HEAD` (audit-verified). |
| `.archive/2026-07-15-bodai-hooks-sb-debug.md` | Pickup prompt: debug Session-Buddy MCP transport drops (`-32000`) + audit Bodai Claude Code hook firing. | ✅ **Resolved** — root cause is `.claude/settings.json` flat-layout (silently ignored) + multi-session MCP contention, not a server bug. Failing test pinned at `tests/unit/test_claude_settings_hooks_format.py`; fix documented in paired `.archive/2026-07-15-bodai-hooks-sb-debug-resolution.md` (not auto-applied per multi-session safety policy). |
| `.archive/2026-07-15-bodai-hooks-sb-debug-resolution.md` | Paired resolution doc: root-cause + failing test + proposed fix for the flat-layout bug. | ✅ Resolution written and archived together with its pickup note (per lifecycle rule's "2026-07-15 style"). Open follow-up: multi-session MCP contention architectural fix tracked under new followup entry. |
| `.archive/2026-06-29-agno-adapter-config-field-path.md` | Agno adapter rejected user config via duplicated config classes and silently fell back to Ollama. | ✅ Canonical shared classes + 3 regression tests verified in current code. |
| `.archive/2026-06-29-pydantic-settings-source-resolution.md` | pydantic-settings merge order let YAML mask env/`local.yaml` overrides for nested settings. | ✅ Source-order fix + 36-test regression suite + original reproduction all pass. |
| `.archive/2026-07-16-session-worktree-isolation.md` | Per-session git worktree isolation (Phase 1-6 + Phase 8 commit `206f23d`). | ✅ All commits referenced are in `HEAD`; frontmatter `status: complete`. Archived 2026-09-05 via `git mv`. |
| `.archive/2026-07-16-dlq-fail-closed-session-checkpoint.md` | Historical checkpoint from 2026-07-16 session: DLQ fail-closed wiring (Phases 1-3) + followups lifecycle policy. | ✅ Describes completed work, all referenced files in `HEAD`. Archived 2026-09-05 via `git mv`. |
| `.archive/2026-07-16-multi-session-mcp-contention.md` | Multi-Claude-session MCP contention: 4 concurrent Stop hooks fire `sb_checkpoint.py` simultaneously; `session-buddy` singleton `threading.Lock` blocks uvicorn event loop → `-32000 transport dropped`. | ✅ **Resolved** — single-flight coalescing + `asyncio.to_thread` wrappers landed in session-buddy commits `b86fbcbf`/`3c83f33d`/`d67a531c`/`4e661221`/`8b168816`/`1043ffec`. Integration test `tests/integration/test_concurrent_checkpoint_load.py` flips RED → GREEN (~41s for 6 parallel calls, within 1.5× single-call budget). Plan: `docs/plans/2026-07-16-checkpoint-async-refactor.md`. |

## Lifecycle

How a note moves open → resolved → archived, and how you know which state
it's in.

### Status convention

- Every note carries a `**Status:**` line near the top. Values in use:
  `open` / `Recurring defect` / `Partially resolved` / `Resolved`.
- A `Resolved` claim **should cite the fix location and a named regression
  test** so it can be re-verified. Treat an *uncited* `Resolved` as a claim,
  not a guarantee.

### Closing and archiving

- When a note is genuinely resolved (fix **and** test present), `git mv` it
  into `docs/followups/.archive/`. **Never delete it** — the record must
  survive a clean checkout.
- Move the note's row from the **Active** table to the **Archived** table in
  this index at the same time.
- 2026-07-15 style: some threads instead close by writing a paired
  `-resolution.md` note; when that lands, archive the pickup prompt and its
  companion notes together.

### How you know a follow-up is addressed

- **This index's "Verified state" column is the source of truth** — not the
  note's own `**Status:**` line.
- The 2026-07-16 audit found two notes (`dlq-silent-fallback`,
  `opensearch-diverged-flags`) that self-declare `Resolved` while the current
  code is only partially fixed. That gap is exactly why the verified-state
  column exists and why `Resolved` claims should cite a runnable test.

### Relationship to `.claude/decisions/`

This directory follows the same conventions as `.claude/decisions/`
(a README index plus archive-on-completion into `.archive/`, never delete).
The policy is recorded at `.claude/decisions/followups-lifecycle.md`.
