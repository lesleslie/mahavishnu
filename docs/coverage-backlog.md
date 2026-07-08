# Coverage Backlog

> **Generated from `coverage.xml`** — the canonical coverage report for `mahavishnu/`.
> **Overall rate: 4.25%** | Gate: `--cov-fail-under=80` (FAILING)
> 409 files measured, 49,058 total lines, 2,083 covered.

## Tier definitions

| Tier | Coverage | Action |
|---|---|---|
| `untested` | 0% | Write at least smoke tests; this is the highest-priority backlog |
| `low` | 1-49% | Add tests for uncovered paths; aim for `partial` then `good` |
| `partial` | 50-79% | Targeted gap-fill tests on missing lines |
| `good` | 80%+ | Maintain; only re-test on behavioral changes |

## Per-directory backlog (largest first)

### `core/` — 26,167 lines, 5.3% covered

**160 untested file(s)** (highest priority):

- `core/monitoring.py` — 536 lines, 0% covered
- `core/embeddings.py` — 422 lines, 0% covered
- `core/task_router.py` — 420 lines, 0% covered
- `core/ecosystem_status.py` — 358 lines, 0% covered
- `core/production_readiness.py` — 357 lines, 0% covered
- `core/production_readiness_standalone.py` — 350 lines, 0% covered
- `core/task_ordering.py` — 336 lines, 0% covered
- `core/output_formatter.py` — 323 lines, 0% covered
- `core/task_store.py` — 321 lines, 0% covered
- `core/cost_optimizer.py` — 302 lines, 0% covered
- `core/coordination/manager.py` — 298 lines, 0% covered
- `core/backup_recovery.py` — 285 lines, 0% covered
- `core/dependency_graph.py` — 284 lines, 0% covered
- `core/dead_letter_queue.py` — 275 lines, 0% covered
- `core/embedding_cache.py` — 274 lines, 0% covered
- `core/health_integration.py` — 270 lines, 0% covered
- `core/goal_team_metrics.py` — 259 lines, 0% covered
- `core/statistical_router.py` — 253 lines, 0% covered
- `core/resilient_embeddings.py` — 244 lines, 0% covered
- `core/nlp_parser.py` — 241 lines, 0% covered
- `core/adapter_persistence.py` — 236 lines, 0% covered
- `core/vector_search.py` — 235 lines, 0% covered
- `core/migrator.py` — 233 lines, 0% covered
- `core/repositories/tasks.py` — 229 lines, 0% covered
- `core/progress_tracker.py` — 228 lines, 0% covered
- `core/adapter_registry.py` — 226 lines, 0% covered
- `core/cache_manager.py` — 224 lines, 0% covered
- `core/load_testing.py` — 223 lines, 0% covered
- `core/pattern_detection.py` — 223 lines, 0% covered
- `core/health.py` — 222 lines, 0% covered
- `core/routing_metrics.py` — 222 lines, 0% covered
- `core/fix_orchestrator.py` — 218 lines, 0% covered
- `core/predictions.py` — 218 lines, 0% covered
- `core/ecosystem.py` — 214 lines, 0% covered
- `core/dependency_visualization.py` — 210 lines, 0% covered
- `core/opensearch_integration.py` — 208 lines, 0% covered
- `core/query_optimizer.py` — 208 lines, 0% covered
- `core/cross_repo_filter.py` — 204 lines, 0% covered
- `core/repo_dashboard.py` — 203 lines, 0% covered
- `core/worktree_coordination.py` — 200 lines, 0% covered
- `core/secrets_scanner.py` — 198 lines, 0% covered
- `core/routing_metrics_persistence.py` — 197 lines, 0% covered
- `core/task_dashboard.py` — 197 lines, 0% covered
- `core/event_store.py` — 195 lines, 0% covered
- `core/cross_repo_aggregator.py` — 193 lines, 0% covered
- `core/metrics_collector.py` — 193 lines, 0% covered
- `core/coordination/memory.py` — 191 lines, 0% covered
- `core/team_learning.py` — 190 lines, 0% covered
- `core/dependency_manager.py` — 189 lines, 0% covered
- `core/repositories/runs.py` — 187 lines, 0% covered
- `core/observability.py` — 182 lines, 0% covered
- `core/webhook_handler.py` — 182 lines, 0% covered
- `core/config_validator.py` — 181 lines, 0% covered
- `core/cross_repo_dependency.py` — 181 lines, 0% covered
- `core/task_models.py` — 181 lines, 0% covered
- `core/events/transport.py` — 179 lines, 0% covered
- `core/cross_repo_search.py` — 178 lines, 0% covered
- `core/multi_repo_coordinator.py` — 177 lines, 0% covered
- `core/blocker_detection.py` — 176 lines, 0% covered
- `core/db_migrations.py` — 173 lines, 0% covered
- `core/k8s_manifests.py` — 173 lines, 0% covered
- `core/sync_coordinator.py` — 173 lines, 0% covered
- `core/search/hybrid_search.py` — 173 lines, 0% covered
- `core/worktree_manager.py` — 169 lines, 0% covered
- `core/rate_limit.py` — 166 lines, 0% covered
- `core/routing_alerts.py` — 165 lines, 0% covered
- `core/quality_gate_manager.py` — 164 lines, 0% covered
- `core/deployment_manager.py` — 163 lines, 0% covered
- `core/cross_repo_blocker.py` — 158 lines, 0% covered
- `core/database.py` — 156 lines, 0% covered
- `core/precommitment.py` — 156 lines, 0% covered
- `core/validators.py` — 156 lines, 0% covered
- `core/task_audit.py` — 149 lines, 0% covered
- `core/secure_logging.py` — 146 lines, 0% covered
- `core/json_rpc_ipc.py` — 144 lines, 0% covered
- `core/slo.py` — 143 lines, 0% covered
- `core/external_issue_importer.py` — 141 lines, 0% covered
- `core/thompson_router.py` — 141 lines, 0% covered
- `core/state_backends/dhara.py` — 137 lines, 0% covered
- `core/adaptive_rag.py` — 135 lines, 0% covered
- `core/task_notifications.py` — 135 lines, 0% covered
- `core/repositories/documents.py` — 133 lines, 0% covered
- `core/onboarding.py` — 132 lines, 0% covered
- `core/coordination/executor.py` — 132 lines, 0% covered
- `core/learning_pipeline.py` — 131 lines, 0% covered
- `core/skill_governance.py` — 123 lines, 0% covered
- `core/evidence_retriever.py` — 122 lines, 0% covered
- `core/worktree_backup.py` — 122 lines, 0% covered
- `core/coordination/models.py` — 120 lines, 0% covered
- `core/task_metrics.py` — 112 lines, 0% covered
- `core/command_api.py` — 111 lines, 0% covered
- `core/repo_manager.py` — 110 lines, 0% covered
- `core/dlq_integration.py` — 107 lines, 0% covered
- `core/async_patterns.py` — 105 lines, 0% covered
- `core/subscription_auth.py` — 104 lines, 0% covered
- `core/worktree_validation.py` — 102 lines, 0% covered
- `core/embeddings_oneiric.py` — 97 lines, 0% covered
- `core/task_requirements.py` — 97 lines, 0% covered
- `core/approval_manager.py` — 96 lines, 0% covered
- `core/code_index/models.py` — 95 lines, 0% covered
- `core/context.py` — 94 lines, 0% covered
- `core/review_gate.py` — 92 lines, 0% covered
- `core/worktree_providers/session_buddy.py` — 90 lines, 0% covered
- `core/workflow_models.py` — 84 lines, 0% covered
- `core/repositories/embeddings.py` — 83 lines, 0% covered
- `core/repositories/events.py` — 82 lines, 0% covered
- `core/process_pool_executor.py` — 81 lines, 0% covered
- `core/events/envelope.py` — 81 lines, 0% covered
- `core/code_index/indexer.py` — 80 lines, 0% covered
- `core/repo_models.py` — 77 lines, 0% covered
- `core/feature_flags.py` — 76 lines, 0% covered
- `core/skill_synthesizer.py` — 74 lines, 0% covered
- `core/worktree_providers/direct_git.py` — 73 lines, 0% covered
- `core/code_index/parser.py` — 72 lines, 0% covered
- `core/events/schema_registry.py` — 72 lines, 0% covered
- `core/evidence_store.py` — 71 lines, 0% covered
- `core/webhook_auth.py` — 70 lines, 0% covered
- `core/dhara_client.py` — 69 lines, 0% covered
- `core/skill_registry.py` — 69 lines, 0% covered
- `core/unified_orchestrator.py` — 66 lines, 0% covered
- `core/self_heal/l3_rule_store.py` — 65 lines, 0% covered
- `core/unified_config.py` — 62 lines, 0% covered
- `core/rate_limit_tools.py` — 61 lines, 0% covered
- `core/worktree_audit.py` — 60 lines, 0% covered
- `core/skill_mcp_validator.py` — 59 lines, 0% covered
- `core/worktree_providers/registry.py` — 59 lines, 0% covered
- `core/code_index/lock.py` — 57 lines, 0% covered
- `core/dhara_adapter.py` — 56 lines, 0% covered
- `core/rate_limiting.py` — 54 lines, 0% covered
- `core/events/confidence_ceiling.py` — 53 lines, 0% covered
- `core/events/contract.py` — 52 lines, 0% covered
- `core/auth.py` — 51 lines, 0% covered
- `core/repositories/base.py` — 48 lines, 0% covered
- `core/paths.py` — 44 lines, 0% covered
- `core/evidence_collector.py` — 43 lines, 0% covered
- `core/worktree_providers/mock.py` — 40 lines, 0% covered
- `core/events/compatibility.py` — 39 lines, 0% covered
- `core/skill_security.py` — 36 lines, 0% covered
- `core/style_sop.py` — 34 lines, 0% covered
- `core/events/migration.py` — 32 lines, 0% covered
- `core/code_index/git_hooks.py` — 31 lines, 0% covered
- `core/completion_persister.py` — 28 lines, 0% covered
- `core/completion_report.py` — 28 lines, 0% covered
- `core/self_heal/l1_retry.py` — 28 lines, 0% covered
- `core/code_index/signature_redaction.py` — 20 lines, 0% covered
- `core/code_index/path_validation.py` — 19 lines, 0% covered
- `core/style_sop_validator.py` — 18 lines, 0% covered
- `core/events/__init__.py` — 18 lines, 0% covered
- `core/worktree_providers/errors.py` — 17 lines, 0% covered
- `core/self_heal/l2_noop.py` — 8 lines, 0% covered
- `core/worktree_providers/__init__.py` — 8 lines, 0% covered
- `core/repositories/__init__.py` — 7 lines, 0% covered
- `core/opensearch_constants.py` — 6 lines, 0% covered
- `core/coordination/__init__.py` — 5 lines, 0% covered
- `core/self_heal/__init__.py` — 5 lines, 0% covered
- `core/worktree_providers/base.py` — 4 lines, 0% covered
- `core/config_dlq.py` — 3 lines, 0% covered
- `core/code_index/__init__.py` — 2 lines, 0% covered
- `core/search/__init__.py` — 2 lines, 0% covered
- `core/state_backends/__init__.py` — 2 lines, 0% covered

**15 low-coverage file(s)** (1-49%):

- `core/dependency_waiter.py` — 3/38 lines (7.9%)
- `core/bootstrap.py` — 37/346 lines (10.7%)
- `core/workflow_execution.py` — 27/190 lines (14.2%)
- `core/repo_nicknames.py` — 4/23 lines (17.4%)
- `core/adapter_discovery.py` — 40/214 lines (18.7%)
- `core/adapters/worker.py` — 22/103 lines (21.4%)
- `core/repository_surface.py` — 26/119 lines (21.8%)
- `core/control_surface.py` — 13/56 lines (23.2%)
- `core/workflow_state.py` — 20/82 lines (24.4%)
- `core/resilience.py` — 102/406 lines (25.1%)
- `core/routing.py` — 26/100 lines (26.0%)
- `core/compatibility.py` — 32/123 lines (26.0%)
- `core/lifecycle.py` — 9/32 lines (28.1%)
- `core/oneiric_client.py` — 58/203 lines (28.6%)
- `core/permissions.py` — 44/131 lines (33.6%)

**5 partial file(s)** (50-79%):

- `core/errors.py` — 166/280 lines (59.3%)
- `core/app.py` — 140/235 lines (59.6%)
- `core/adapters/base.py` — 17/26 lines (65.4%)
- `core/__init__.py` — 11/16 lines (68.8%)
- `core/metrics_schema.py` — 91/128 lines (71.1%)

**4 good file(s)** (80%+):

- `core/circuit_breaker.py` — 3/3 lines (100.0%)
- `core/status.py` — 115/115 lines (100.0%)
- `core/adapters/__init__.py` — 2/2 lines (100.0%)
- `core/config.py` — 383/470 lines (81.5%)

### `mcp/` — 4,192 lines, 0.0% covered

**44 untested file(s)** (highest priority):

- `mcp/server_core.py` — 502 lines, 0% covered
- `mcp/bootstrap.py` — 215 lines, 0% covered
- `mcp/tools/goal_team_tools.py` — 187 lines, 0% covered
- `mcp/tools/self_improvement_tools.py` — 185 lines, 0% covered
- `mcp/tools/health_tools.py` — 165 lines, 0% covered
- `mcp/tools/desktop_automation_tools.py` — 163 lines, 0% covered
- `mcp/tools/pycharm_tools.py` — 163 lines, 0% covered
- `mcp/tools/otel_tools.py` — 160 lines, 0% covered
- `mcp/tools/session_buddy_tools.py` — 159 lines, 0% covered
- `mcp/tools/treesitter_tools.py` — 149 lines, 0% covered
- `mcp/crow/tools/web_extract.py` — 146 lines, 0% covered
- `mcp/tools/coordination_tools.py` — 146 lines, 0% covered
- `mcp/crow/tools/file_tools.py` — 144 lines, 0% covered
- `mcp/tools/git_analytics.py` — 133 lines, 0% covered
- `mcp/tools/pool_tools.py` — 113 lines, 0% covered
- `mcp/crow/tools/web_tools.py` — 112 lines, 0% covered
- `mcp/tools/adapter_registry_tools.py` — 111 lines, 0% covered
- `mcp/protocols/message_bus.py` — 107 lines, 0% covered
- `mcp/tools/terminal_tools.py` — 94 lines, 0% covered
- `mcp/crow/tools/rg_search.py` — 90 lines, 0% covered
- `mcp/tools/repository_messaging_tools.py` — 87 lines, 0% covered
- `mcp/bodai_component_client.py` — 72 lines, 0% covered
- `mcp/tools/openhands_tools.py` — 70 lines, 0% covered
- `mcp/auth.py` — 69 lines, 0% covered
- `mcp/websocket_tools.py` — 69 lines, 0% covered
- `mcp/tools/search_tools.py` — 64 lines, 0% covered
- `mcp/tools/worker_tools.py` — 53 lines, 0% covered
- `mcp/tools/learning_pipeline_tools.py` — 52 lines, 0% covered
- `mcp/tools/primitive_tools.py` — 50 lines, 0% covered
- `mcp/tools/worktree_tools.py` — 46 lines, 0% covered
- `mcp/tools/ecosystem_tools.py` — 45 lines, 0% covered
- `mcp/crow_server.py` — 43 lines, 0% covered
- `mcp/tools/clone_tools.py` — 40 lines, 0% covered
- `mcp/crow/terminal_proxy.py` — 37 lines, 0% covered
- `mcp/crow/path_security.py` — 34 lines, 0% covered
- `mcp/lifecycle.py` — 28 lines, 0% covered
- `mcp/crow/settings.py` — 24 lines, 0% covered
- `mcp/crow/client.py` — 14 lines, 0% covered
- `mcp/error_envelope.py` — 12 lines, 0% covered
- `mcp/tool_versions.py` — 12 lines, 0% covered
- `mcp/crow/tools/__init__.py` — 11 lines, 0% covered
- `mcp/tools/profiles.py` — 8 lines, 0% covered
- `mcp/tools/__init__.py` — 6 lines, 0% covered
- `mcp/protocols/__init__.py` — 2 lines, 0% covered

### `(root)/` — 2,659 lines, 0.0% covered

**16 untested file(s)** (highest priority):

- `_main_cli.py` — 803 lines, 0% covered
- `ecosystem_cli.py` — 355 lines, 0% covered
- `coordination_cli.py` — 353 lines, 0% covered
- `metrics_cli.py` — 350 lines, 0% covered
- `task_cli.py` — 196 lines, 0% covered
- `worktree_cli.py` — 123 lines, 0% covered
- `backup_cli.py` — 116 lines, 0% covered
- `ingestion_cli.py` — 114 lines, 0% covered
- `health.py` — 56 lines, 0% covered
- `factories.py` — 50 lines, 0% covered
- `production_cli.py` — 49 lines, 0% covered
- `repo_cli.py` — 37 lines, 0% covered
- `quality_cli.py` — 33 lines, 0% covered
- `routing_cli.py` — 19 lines, 0% covered
- `monitoring_cli.py` — 3 lines, 0% covered
- `__main__.py` — 1 lines, 0% covered

**1 good file(s)** (80%+):

- `__init__.py` — 1/1 lines (100.0%)

### `engines/` — 2,467 lines, 7.9% covered

**11 untested file(s)** (highest priority):

- `engines/agno_teams/manager.py` — 196 lines, 0% covered
- `engines/agno_tools/code_tools.py` — 169 lines, 0% covered
- `engines/agno_tools/file_tools.py` — 166 lines, 0% covered
- `engines/goal_team_factory.py` — 139 lines, 0% covered
- `engines/prefect_schedules.py` — 104 lines, 0% covered
- `engines/hatchet_adapter_impl.py` — 78 lines, 0% covered
- `engines/prefect_registry.py` — 63 lines, 0% covered
- `engines/agno_teams/config.py` — 59 lines, 0% covered
- `engines/prefect_models.py` — 56 lines, 0% covered
- `engines/agno_tools/__init__.py` — 7 lines, 0% covered
- `engines/agno_teams/__init__.py` — 3 lines, 0% covered

**4 low-coverage file(s)** (1-49%):

- `engines/prefect_adapter_impl.py` — 14/554 lines (2.5%)
- `engines/llamaindex_adapter_impl.py` — 76/398 lines (19.1%)
- `engines/agno_adapter_impl.py` — 101/459 lines (22.0%)
- `engines/__init__.py` — 4/16 lines (25.0%)

### `automation/` — 1,702 lines, 0.0% covered

**13 untested file(s)** (highest priority):

- `automation/cli.py` — 315 lines, 0% covered
- `automation/backends/native_macos.py` — 256 lines, 0% covered
- `automation/backends/pyautogui.py` — 238 lines, 0% covered
- `automation/models.py` — 184 lines, 0% covered
- `automation/manager.py` — 180 lines, 0% covered
- `automation/capabilities.py` — 128 lines, 0% covered
- `automation/security.py` — 111 lines, 0% covered
- `automation/base.py` — 89 lines, 0% covered
- `automation/permissions.py` — 86 lines, 0% covered
- `automation/errors.py` — 77 lines, 0% covered
- `automation/backends/base.py` — 26 lines, 0% covered
- `automation/__init__.py` — 8 lines, 0% covered
- `automation/backends/__init__.py` — 4 lines, 0% covered

### `workers/` — 1,691 lines, 21.2% covered

**3 untested file(s)** (highest priority):

- `workers/cloud_worker.py` — 138 lines, 0% covered
- `workers/a2a.py` — 94 lines, 0% covered
- `workers/task_router.py` — 93 lines, 0% covered

**9 low-coverage file(s)** (1-49%):

- `workers/container.py` — 15/120 lines (12.5%)
- `workers/manager.py` — 24/180 lines (13.3%)
- `workers/generic_shell.py` — 27/194 lines (13.9%)
- `workers/application.py` — 20/101 lines (19.8%)
- `workers/debug_monitor.py` — 25/114 lines (21.9%)
- `workers/ollama.py` — 59/238 lines (24.8%)
- `workers/crow.py` — 17/57 lines (29.8%)
- `workers/openhands.py` — 33/101 lines (32.7%)
- `workers/openclaw_gateway.py` — 45/116 lines (38.8%)

**3 partial file(s)** (50-79%):

- `workers/base.py` — 27/48 lines (56.2%)
- `workers/registry.py` — 33/56 lines (58.9%)
- `workers/protocol.py` — 21/28 lines (75.0%)

**1 good file(s)** (80%+):

- `workers/__init__.py` — 13/13 lines (100.0%)

### `pools/` — 1,359 lines, 0.0% covered

**13 untested file(s)** (highest priority):

- `pools/manager.py` — 307 lines, 0% covered
- `pools/memory_aggregator.py` — 246 lines, 0% covered
- `pools/fitness_analyzer.py` — 163 lines, 0% covered
- `pools/websocket/broadcaster.py` — 128 lines, 0% covered
- `pools/session_buddy_pool.py` — 117 lines, 0% covered
- `pools/mahavishnu_pool.py` — 98 lines, 0% covered
- `pools/runpod_pool.py` — 92 lines, 0% covered
- `pools/routing_fitness.py` — 53 lines, 0% covered
- `pools/__init__.py` — 41 lines, 0% covered
- `pools/peer_routing.py` — 41 lines, 0% covered
- `pools/gpu_handler_pool.py` — 37 lines, 0% covered
- `pools/base.py` — 34 lines, 0% covered
- `pools/websocket/__init__.py` — 2 lines, 0% covered

### `cli/` — 1,243 lines, 0.0% covered

**12 untested file(s)** (highest priority):

- `cli/team_cli.py` — 318 lines, 0% covered
- `cli/config_validator.py` — 283 lines, 0% covered
- `cli/scaffold_cli.py` — 149 lines, 0% covered
- `cli/help_cli.py` — 116 lines, 0% covered
- `cli/monitoring_cli.py` — 114 lines, 0% covered
- `cli/sop_cli.py` — 69 lines, 0% covered
- `cli/events.py` — 59 lines, 0% covered
- `cli/index_cli.py` — 40 lines, 0% covered
- `cli/docs_cli.py` — 33 lines, 0% covered
- `cli/precommit_cli.py` — 27 lines, 0% covered
- `cli/rollback_cli.py` — 18 lines, 0% covered
- `cli/__init__.py` — 17 lines, 0% covered

### `ingesters/` — 1,165 lines, 0.0% covered

**4 untested file(s)** (highest priority):

- `ingesters/otel_ingester.py` — 503 lines, 0% covered
- `ingesters/content_ingester.py` — 355 lines, 0% covered
- `ingesters/quality_scorer.py` — 244 lines, 0% covered
- `ingesters/turboquant_compressor.py` — 63 lines, 0% covered

### `tui/` — 1,021 lines, 0.0% covered

**5 untested file(s)** (highest priority):

- `tui/app.py` — 717 lines, 0% covered
- `tui/command_palette.py` — 200 lines, 0% covered
- `tui/monitor_app.py` — 49 lines, 0% covered
- `tui/__init__.py` — 32 lines, 0% covered
- `tui/widgets.py` — 23 lines, 0% covered

### `terminal/` — 1,016 lines, 13.5% covered

**7 untested file(s)** (highest priority):

- `terminal/pool.py` — 172 lines, 0% covered
- `terminal/grid/manager.py` — 143 lines, 0% covered
- `terminal/mcp_client.py` — 113 lines, 0% covered
- `terminal/grid/models.py` — 40 lines, 0% covered
- `terminal/session.py` — 24 lines, 0% covered
- `terminal/grid/exceptions.py` — 19 lines, 0% covered
- `terminal/grid/__init__.py` — 4 lines, 0% covered

**7 low-coverage file(s)** (1-49%):

- `terminal/manager.py` — 27/151 lines (17.9%)
- `terminal/adapters/iterm2.py` — 22/113 lines (19.5%)
- `terminal/adapters/mock.py` — 16/58 lines (27.6%)
- `terminal/adapters/mcpretentious.py` — 18/58 lines (31.0%)
- `terminal/adapters/__init__.py` — 12/38 lines (31.6%)
- `terminal/adapters/crow.py` — 17/53 lines (32.1%)
- `terminal/__init__.py` — 3/8 lines (37.5%)

**2 good file(s)** (80%+):

- `terminal/config.py` — 19/19 lines (100.0%)
- `terminal/adapters/base.py` — 3/3 lines (100.0%)

### `websocket/` — 701 lines, 0.0% covered

**7 untested file(s)** (highest priority):

- `websocket/server.py` — 238 lines, 0% covered
- `websocket/metrics.py` — 193 lines, 0% covered
- `websocket/rate_limiter.py` — 110 lines, 0% covered
- `websocket/integration.py` — 99 lines, 0% covered
- `websocket/auth.py` — 30 lines, 0% covered
- `websocket/tls_config.py` — 27 lines, 0% covered
- `websocket/__init__.py` — 4 lines, 0% covered

### `distill/` — 583 lines, 0.0% covered

**13 untested file(s)** (highest priority):

- `distill/llm_usage.py` — 124 lines, 0% covered
- `distill/distiller.py` — 76 lines, 0% covered
- `distill/reviewer.py` — 70 lines, 0% covered
- `distill/provenance.py` — 49 lines, 0% covered
- `distill/synthesizer.py` — 49 lines, 0% covered
- `distill/skill_pipeline.py` — 47 lines, 0% covered
- `distill/discovery.py` — 44 lines, 0% covered
- `distill/health.py` — 41 lines, 0% covered
- `distill/reporter.py` — 38 lines, 0% covered
- `distill/decorator.py` — 22 lines, 0% covered
- `distill/schema.py` — 12 lines, 0% covered
- `distill/__init__.py` — 6 lines, 0% covered
- `distill/consumer.py` — 5 lines, 0% covered

### `scaffolding/` — 583 lines, 0.0% covered

**8 untested file(s)** (highest priority):

- `scaffolding/engine.py` — 211 lines, 0% covered
- `scaffolding/extractor.py` — 97 lines, 0% covered
- `scaffolding/models.py` — 91 lines, 0% covered
- `scaffolding/library.py` — 64 lines, 0% covered
- `scaffolding/validation.py` — 56 lines, 0% covered
- `scaffolding/dependency_graph.py` — 46 lines, 0% covered
- `scaffolding/jinjava_env.py` — 14 lines, 0% covered
- `scaffolding/__init__.py` — 4 lines, 0% covered

### `testing/` — 412 lines, 0.0% covered

**3 untested file(s)** (highest priority):

- `testing/load_test.py` — 244 lines, 0% covered
- `testing/incident_simulation.py` — 166 lines, 0% covered
- `testing/__init__.py` — 2 lines, 0% covered

### `adapters/` — 254 lines, 0.0% covered

**2 untested file(s)** (highest priority):

- `adapters/pgvector_adapter.py` — 252 lines, 0% covered
- `adapters/__init__.py` — 2 lines, 0% covered

### `integrations/` — 241 lines, 0.0% covered

**2 untested file(s)** (highest priority):

- `integrations/session_buddy_poller.py` — 239 lines, 0% covered
- `integrations/__init__.py` — 2 lines, 0% covered

### `shell/` — 236 lines, 0.0% covered

**5 untested file(s)** (highest priority):

- `shell/formatters.py` — 123 lines, 0% covered
- `shell/magics.py` — 43 lines, 0% covered
- `shell/shell_commands.py` — 36 lines, 0% covered
- `shell/adapter.py` — 26 lines, 0% covered
- `shell/__init__.py` — 8 lines, 0% covered

### `messaging/` — 219 lines, 0.0% covered

**4 untested file(s)** (highest priority):

- `messaging/repository_messenger.py` — 170 lines, 0% covered
- `messaging/messaging/types.py` — 39 lines, 0% covered
- `messaging/__init__.py` — 8 lines, 0% covered
- `messaging/messaging/__init__.py` — 2 lines, 0% covered

### `workflows/` — 194 lines, 0.0% covered

**4 untested file(s)** (highest priority):

- `workflows/clone_refactor_workflow.py` — 96 lines, 0% covered
- `workflows/progress.py` — 59 lines, 0% covered
- `workflows/cli_watch.py` — 38 lines, 0% covered
- `workflows/__init__.py` — 1 lines, 0% covered

### `llm_gateway/` — 156 lines, 0.0% covered

**3 untested file(s)** (highest priority):

- `llm_gateway/contract.py` — 97 lines, 0% covered
- `llm_gateway/client.py` — 56 lines, 0% covered
- `llm_gateway/__init__.py` — 3 lines, 0% covered

### `webhooks/` — 129 lines, 0.0% covered

**3 untested file(s)** (highest priority):

- `webhooks/models.py` — 73 lines, 0% covered
- `webhooks/router.py` — 53 lines, 0% covered
- `webhooks/__init__.py` — 3 lines, 0% covered

### `a2a/` — 125 lines, 0.0% covered

**3 untested file(s)** (highest priority):

- `a2a/server.py` — 104 lines, 0% covered
- `a2a/card.py` — 19 lines, 0% covered
- `a2a/__init__.py` — 2 lines, 0% covered

### `agents/` — 121 lines, 0.0% covered

**2 untested file(s)** (highest priority):

- `agents/mahavishnu_agent.py` — 119 lines, 0% covered
- `agents/__init__.py` — 2 lines, 0% covered

### `sop/` — 118 lines, 0.0% covered

**4 untested file(s)** (highest priority):

- `sop/persisters.py` — 57 lines, 0% covered
- `sop/models.py` — 29 lines, 0% covered
- `sop/evolution.py` — 27 lines, 0% covered
- `sop/__init__.py` — 5 lines, 0% covered

### `models/` — 96 lines, 0.0% covered

**2 untested file(s)** (highest priority):

- `models/pattern.py` — 88 lines, 0% covered
- `models/__init__.py` — 8 lines, 0% covered

### `qc/` — 80 lines, 0.0% covered

**1 untested file(s)** (highest priority):

- `qc/checker.py` — 80 lines, 0% covered

### `session/` — 67 lines, 0.0% covered

**1 untested file(s)** (highest priority):

- `session/checkpoint.py` — 67 lines, 0% covered

### `observability/` — 52 lines, 0.0% covered

**1 untested file(s)** (highest priority):

- `observability/adapter_runtime.py` — 52 lines, 0% covered

### `quality/` — 9 lines, 0.0% covered

**2 untested file(s)** (highest priority):

- `quality/anti_ai_flavor_check.py` — 8 lines, 0% covered
- `quality/__init__.py` — 1 lines, 0% covered

---

## How to use this backlog

1. Pick one `untested` file from a high-priority directory (`core/`, `mcp/`, `pools/`).
2. Write tests targeting its public functions/classes.
3. Re-run `pytest --cov=mahavishnu --cov-report=xml`.
4. Verify the file's tier moved from `untested` → at least `partial`.
5. Commit and repeat.

Use `--cov-report=term-missing:skip-covered` to see *which* lines are uncovered without drowning in the 80%+ files.
