# File Reference Guide

## Core Application

- `mahavishnu/core/app.py` — MahavishnuApp class
- `mahavishnu/core/config.py` — MahavishnuSettings (Oneiric-based)
- `mahavishnu/core/adapters/base.py` — OrchestratorAdapter interface
- `mahavishnu/core/errors.py` — Custom exception hierarchy
- `mahavishnu/core/repo_models.py` — Repository metadata structures

## MCP & WebSocket

- `mahavishnu/mcp/server.py` — FastMCP server
- `mahavishnu/websocket/server.py` — Real-time updates
- `mahavishnu/mcp/tools/` — Tool implementations
  - `pool_tools.py` — Pool management (10 tools)
  - `worker_tools.py` — Worker orchestration (8 tools)
  - `coordination_tools.py` — Issues, todos, dependencies (13 tools)
  - `repository_messaging_tools.py` — Inter-repo messaging (7 tools)
  - `otel_tools.py` — OpenTelemetry trace ingestion (4 tools)
  - `session_buddy_tools.py` — Session-Buddy integration (7 tools)

## Pool Management

- `mahavishnu/pools/manager.py` — Multi-pool orchestration
- `mahavishnu/pools/mahavishnu_pool.py` — Direct worker management
- `mahavishnu/pools/session_buddy_pool.py` — Delegated pool
- `mahavishnu/pools/runpod_pool.py` — GPU cloud pool
- `mahavishnu/pools/memory_aggregator.py` — Cross-pool memory sync
- `mahavishnu/pools/websocket/` — Real-time pool events

## Workers & Terminal

- `mahavishnu/workers/manager.py` — Worker lifecycle
- `mahavishnu/workers/base.py` — Abstract worker interface
- `mahavishnu/workers/apple_container.py` — Apple `container` microVM execution (Apple silicon)
- `mahavishnu/workers/e2b_sandbox.py` — E2B cloud sandbox execution (fallback tier)
- `mahavishnu/workers/cloud_worker.py` — OpenAI-compatible cloud worker (MiniMax defaults)
- `mahavishnu/workers/task_router.py` — Task classification + model selection
- `mahavishnu/terminal/manager.py` — Terminal session management
- `mahavishnu/terminal/adapters/` — Terminal adapter implementations (tmux, mock, crow, base)

## Data Ingestion

- `mahavishnu/ingesters/otel_ingester.py` — Trace ingestion with pgvector
- `mahavishnu/ingesters/content_ingester.py` — Web/book/blog ingestion
- `mahavishnu/ingesters/quality_scorer.py` — Content quality scoring

## CLI Sub-commands

- `mahavishnu/backup_cli.py` — Backup/recovery commands
- `mahavishnu/coordination_cli.py` — Issues/todos/dependencies
- `mahavishnu/ecosystem_cli.py` — Repository management
- `mahavishnu/ingestion_cli.py` — Content ingestion
- `mahavishnu/metrics_cli.py` — Observability metrics
- `mahavishnu/monitoring_cli.py` — Health monitoring
- `mahavishnu/production_cli.py` — Production readiness
- `mahavishnu/quality_cli.py` — Quality evaluation
- `mahavishnu/routing_cli.py` — Adaptive routing system

## Routing System

- `mahavishnu/core/routing_metrics.py` — Prometheus metrics collection
- `mahavishnu/core/routing_alerts.py` — Alert generation and handling
- `mahavishnu/core/routing_metrics.py` — RoutingMetrics singleton

## Configuration & Architecture

- `settings/repos.yaml` — Repository manifest
- `settings/mahavishnu.yaml` — Main configuration (committed)
- `settings/local.yaml` — Local overrides (gitignored)
- `settings/models.yaml` — LLM provider routing
- `docs/adr/` — Architecture Decision Records
- `docs/plans/` — Implementation plans

## Examples

All examples in `examples/` directory are runnable:

- `websocket_integration.py` — WebSocket server integration
- `pool_monitoring_demo.py` — Pool monitoring with WebSocket
- `web_ingestion_example.py` — Webpage ingestion
- `book_ingestion_example.py` — PDF/EPUB ingestion
- `otel_ingester_example.py` — OpenTelemetry trace ingestion
- `cli_ingestion_examples.sh` — CLI ingestion commands
