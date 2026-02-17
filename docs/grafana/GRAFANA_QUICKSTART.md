# Grafana Dashboard Quick Start

## Access Information

**Grafana URL:** http://localhost:3030
**Username:** admin
**Password:** admin

**Dashboard URL:** http://localhost:3030/d/e24a0cf5-28cf-4bc7-82bc-46e876c7e4d9

## Current Status

- ✅ Grafana running on port 3030
- ✅ Dashboard deployed with 17 panels
- ✅ SQLite datasource plugin installed
- ⚠️ DuckDB datasource requires bridge server

## Quick Start Steps

### Option 1: View Dashboard (No Data)

1. Open Grafana: http://localhost:3030
1. Login with admin/admin
1. Navigate to: http://localhost:3030/d/e24a0cf5-28cf-4bc7-82bc-46e876c7e4d9
1. Dashboard will load but panels may show no data until datasource is configured

### Option 2: Deploy Bridge Server (Recommended)

1. **Start the bridge server:**

   ```bash
   cd /Users/les/Projects/mahavishnu
   python scripts/duckdb_grafana_server.py --port 8080
   ```

1. **Verify bridge server is running:**

   ```bash
   curl http://localhost:8080/health
   ```

1. **Add JSON datasource in Grafana:**

   - Go to: http://localhost:3030/datasources
   - Click "Add data source"
   - Select "JSON" (or "Infinity" plugin)
   - URL: `http://localhost:8080`
   - Name: `DuckDB Learning`
   - Save & Test

1. **Update dashboard panels:**

   - Edit dashboard
   - Change datasource to JSON
   - Use query names from bridge server

## Available Queries

The bridge server provides 17 pre-configured queries:

- `execution_count_24h` - Total executions (24h)
- `success_rate_24h` - Success rate (24h)
- `avg_quality_24h` - Average quality (24h)
- `total_cost_24h` - Total cost (24h)
- `executions_over_time` - Timeline (7 days)
- `success_rate_over_time` - Success timeline (7 days)
- `success_by_model_tier` - By model tier
- `duration_by_model_tier` - Duration by tier
- `cost_by_model_tier` - Cost distribution
- `pool_performance` - Pool comparison
- `top_repos` - Top repositories
- `duration_percentiles` - p50/p95/p99
- `quality_distribution` - Quality tiers
- `task_type_distribution` - Task breakdown
- `top_errors` - Error frequency
- `database_growth` - Growth metrics
- `avg_routing_confidence` - Routing stats

## Troubleshooting

**Dashboard shows "Not found":**

- Use direct URL: http://localhost:3030/d/e24a0cf5-28cf-4bc7-82bc-46e876c7e4d9
- Or search for "learning" in Grafana

**Panels show no data:**

- Verify bridge server is running
- Check datasource connection
- Ensure database has records

**Database locked:**

- Wait for embedding generation to complete
- Check: `ps aux | grep generate_ollama_embeddings`

## Documentation

- Full deployment report: `/Users/les/Projects/mahavishnu/GRAFANA_DASHBOARD_DEPLOYMENT.md`
- Dashboard JSON: `/Users/les/Projects/mahavishnu/grafana/dashboards/learning-telemetry.json`
- Setup script: `/Users/les/Projects/mahavishnu/scripts/setup_learning_dashboard.sh`
- Bridge server: `/Users/les/Projects/mahavishnu/scripts/duckdb_grafana_server.py`
