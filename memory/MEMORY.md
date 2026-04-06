# Long-term Memory

This file stores important information that should persist across sessions.

## User Information

- Username: les
- Projects home: /Users/les/Projects/
- Primary project: Mahavishnu (/Users/les/Projects/mahavishnu)
- Uses iTerm2 on macOS
- **Intel Mac** — Homebrew binaries at `/usr/local/opt/` (NOT `/opt/homebrew/`)
- **16 GB RAM**
- User has ADHD and sometimes misses information — be proactive with reminders and clear summaries
- Tool call iteration limit is a client-side nanobot runtime parameter — cannot be changed from within the session
- **Preference**: Always prefer simplest solutions over more complicated ones

## Local Infrastructure

### Currently Running Services (brew services)
- **started**: grafana, neo4j, opensearch, postgresql@18, redis
- **none**: arcadedb, bind, containerd, dbus, ironclaw, mysql, netdata, picoclaw, syncthing, unbound, zeptoclaw, zeroclaw
- **ollama**: shows `error 1` in brew services — **Ollama.app (GUI) is the actual manager**. Brew LaunchAgent conflicts with it. Fix: `brew services stop ollama` to stop the crash-looping LaunchAgent. Ollama.app handles the process.
  - Ollama models: qwen2.5-coder:7b, nomic-embed-text:latest, llava:7b
  - Port: 11434 (localhost)

### Postgres 18 (Homebrew) — **TUNED** [2026-04-06]
- Running as brew service: `homebrew.mxcl.postgresql@18.plist`
- Binary path: `/usr/local/opt/postgresql@18/bin/` (keg-only, not symlinked)
- Version: PostgreSQL 18.3 (Homebrew) on x86_64-apple-darwin23.6.0
- Connection: `localhost:5432`, user `les`, no password (trust auth)
- Data dir: `/usr/local/var/postgresql@18`
- Config: `/usr/local/var/postgresql@18/postgresql.conf`
- Log: `/usr/local/var/log/postgresql@18.log`

#### Databases
| Database | Owner | Extensions |
|---|---|---|
| mahavishnu | les | pg_trgm 1.6 |
| mahavishnu_test | les | — |
| postgres | les | pg_stat_statements 1.12 |
| tensorzero | les | pg_trgm 1.6, vector 0.8.2 |

#### Tuned Settings (as of 2026-04-06)
| Setting | Value | Notes |
|---|---|---|
| shared_buffers | 4GB | ~25% of 16GB RAM |
| work_mem | 64MB | Up from 4MB default |
| effective_cache_size | 12GB | ~75% of RAM |
| logging_collector | on | Rotating log files |
| wal_level | minimal | No replication overhead |
| max_wal_senders | 0 | Disabled (required for minimal wal_level) |
| shared_preload_libraries | pg_stat_statements | Query performance tracking |
| track_io_timing | on | I/O timing for pg_stat_statements |
| max_connections | 100 | Default |
| listen_addresses | localhost | Default |

#### Available extensions (not yet created in all DBs)
- `pg_trgm` 1.6
- `vector` 0.8.2
- `pg_stat_statements` 1.12
- `pg_cron` — NOT available via Homebrew

### Mahavishnu Persistence Config
- `settings/mahavishnu.yaml` has `persistence` section with dual write mode, legacy read source
- `postgres_url` empty — set via `MAHAVISHNU_PERSISTENCE__POSTGRES_URL` env var
- `otel_storage` disabled (Postgres + pgvector for trace storage)
- OpenSearch configured at `https://localhost:9200`

## TensorZero Gateway Plan (v3.0)
- Plan file: `/Users/les/Projects/mahavishnu/docs/plans/tensorzero-gateway-plan.md`
- Port: 8471, native binary (NOT Docker)
- **Auth enabled** — backed by Postgres (API keys stored in Postgres)
- **Observability enabled** — inference logs in Postgres
- z.ai as sole LLM provider (OpenAI + Anthropic format endpoints)
- Clients: CCR (Anthropic), Codex, Qwen, Nanobot, Vish Workers, OpenClaw (OpenAI)
- **Phase 0: COMPLETE** ✅ — `tensorzero` database created with pg_trgm + vector extensions
- **Phase 1: READY** — Install gateway venv, create tensorzero.toml, run migrations, smoke test. Needs ZAI_API_KEY from user.
- LaunchAgent: `~/Library/LaunchAgents/com.tensorzero.gateway.plist`
- Config: `~/.config/tensorzero/tensorzero.toml`
- Install: `~/.local/share/tensorzero/.venv/`
- Needs `TENSORZERO_POSTGRES_URL` and `ZAI_API_KEY` env vars
- `TENSORZERO_POSTGRES_URL = "postgres://les@localhost:5432/tensorzero"`
- All clients use `TENSORZERO_API_KEY` (gateway handles provider auth)
- Rate limiting: Postgres-backed (persistent across restarts)

## Oneiric Adapter Architecture
- `oneiric.adapters.database.postgres.PostgresDatabaseAdapter` — asyncpg-based
- `oneiric.adapters.identity.auth0.Auth0IdentityAdapter` — Auth0-based (not relevant for TensorZero auth)
- Installed in mahavishnu venv at `.venv/lib/python3.13/site-packages/oneiric/`
- Adapters: database (postgres, duckdb), identity (auth0), embedding (sentence_transformers), graph (arangodb, neo4j), storage (gcs), observability (otel)