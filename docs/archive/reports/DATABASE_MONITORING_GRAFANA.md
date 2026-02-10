# Database Monitoring - Grafana Integration

This document describes how to integrate Mahavishnu's learning database monitoring with Grafana for real-time dashboards and alerts.

## Overview

The learning database (`data/learning.db`) is a DuckDB database that stores:
- Task execution records
- Performance metrics
- Quality scores
- Cost tracking
- Pool utilization data

## Grafana Setup

### 1. Install DuckDB Plugin

Grafana needs a DuckDB data source plugin. Install it:

```bash
# Using grafana-cli
grafana-cli plugins install grafana-sqlite-datasource

# Or download from: https://github.com/graphistry/grafana-sqlite-datasource
```

### 2. Configure DuckDB Data Source

1. Go to **Configuration** → **Data Sources**
2. Add new data source → Select **SQLite** (works with DuckDB)
3. Configure:
   - **Name**: Mahavishnu Learning DB
   - **Path**: `/Users/les/Projects/mahavishnu/data/learning.db`
   - **Mode**: Read-only

4. Click **Save & Test**

### 3. Import Dashboard Queries

Use the queries from `scripts/dashboard_queries.sql` to create panels.

## Dashboard Panels

### Executions Overview

**Panel Title**: Executions per Day
**Query**:
```sql
SELECT
    DATE_TRUNC('day', timestamp) as time,
    COUNT(*) as executions,
    SUM(CASE WHEN success = TRUE THEN 1 ELSE 0 END) as successful,
    AVG(duration_seconds) as avg_duration,
    AVG(quality_score) as avg_quality
FROM executions
WHERE timestamp >= NOW() - INTERVAL '30 days'
GROUP BY DATE_TRUNC('day', timestamp)
ORDER BY time DESC;
```

**Visualization**: Time series
**Field Options**:
- executions: Bar
- successful: Line
- avg_duration: Right Y-axis

### Success Rate Gauge

**Panel Title**: Daily Success Rate
**Query**:
```sql
SELECT
    (SUM(CASE WHEN success = TRUE THEN 1 ELSE 0 END) * 100.0 / COUNT(*)) as success_rate
FROM executions
WHERE timestamp >= NOW() - INTERVAL '24 hours';
```

**Visualization**: Stat / Gauge
**Min**: 0, **Max**: 100
**Thresholds**:
- Green: 80-100
- Yellow: 60-79
- Red: 0-59

### Model Tier Performance

**Panel Title**: Success Rate by Model Tier
**Query**:
```sql
SELECT
    model_tier as metric,
    (SUM(CASE WHEN success = TRUE THEN 1 ELSE 0 END) * 100.0 / COUNT(*)) as success_rate
FROM executions
WHERE timestamp >= NOW() - INTERVAL '7 days'
GROUP BY model_tier
ORDER BY success_rate DESC;
```

**Visualization**: Bar chart
**Orientation**: Horizontal

### Duration Percentiles

**Panel Title**: Task Duration Distribution
**Query**:
```sql
SELECT
    AVG(duration_seconds) as avg_duration,
    PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY duration_seconds) as p50_duration,
    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY duration_seconds) as p95_duration,
    PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY duration_seconds) as p99_duration
FROM executions
WHERE timestamp >= NOW() - INTERVAL '7 days';
```

**Visualization**: Stat
**Fields**:
- avg_duration: Value
- p50_duration: Stat field
- p95_duration: Stat field
- p99_duration: Stat field

### Cost Analysis

**Panel Title**: Cost Trends (Last 30 Days)
**Query**:
```sql
SELECT
    DATE_TRUNC('day', timestamp) as time,
    SUM(actual_cost) as total_cost,
    SUM(cost_estimate) as total_estimate,
    SUM(cost_estimate - actual_cost) as savings
FROM executions
WHERE timestamp >= NOW() - INTERVAL '30 days'
GROUP BY DATE_TRUNC('day', timestamp)
ORDER BY time DESC;
```

**Visualization**: Time series
**Field Options**:
- total_cost: Area
- total_estimate: Line (dashed)
- savings: Bar (right Y-axis)

### Pool Performance

**Panel Title**: Pool Utilization
**Query**:
```sql
SELECT
    pool_type,
    COUNT(*) as executions,
    AVG(duration_seconds) as avg_duration,
    (SUM(CASE WHEN success = TRUE THEN 1 ELSE 0 END) * 100.0 / COUNT(*)) as success_rate
FROM executions
WHERE pool_type IS NOT NULL
  AND timestamp >= NOW() - INTERVAL '7 days'
GROUP BY pool_type
ORDER BY executions DESC;
```

**Visualization**: Table
**Columns**:
- pool_type: String
- executions: Colored background
- avg_duration: Number (2 decimals)
- success_rate: Colorized (green >80%, yellow 60-80%, red <60%)

### Error Analysis

**Panel Title**: Top Error Types (Last 7 Days)
**Query**:
```sql
SELECT
    error_type,
    COUNT(*) as count,
    MAX(timestamp) as last_occurrence
FROM executions
WHERE error_type IS NOT NULL
  AND timestamp >= NOW() - INTERVAL '7 days'
GROUP BY error_type
ORDER BY count DESC
LIMIT 10;
```

**Visualization**: Table
**Sort by**: count (descending)

### Quality Score Distribution

**Panel Title**: Quality Distribution
**Query**:
```sql
SELECT
    CASE
        WHEN quality_score >= 90 THEN 'excellent'
        WHEN quality_score >= 75 THEN 'good'
        WHEN quality_score >= 60 THEN 'fair'
        ELSE 'poor'
    END as quality_tier,
    COUNT(*) as count
FROM executions
WHERE quality_score IS NOT NULL
GROUP BY quality_tier
ORDER BY
    CASE quality_tier
        WHEN 'excellent' THEN 1
        WHEN 'good' THEN 2
        WHEN 'fair' THEN 3
        ELSE 4
    END;
```

**Visualization**: Pie chart

## Alert Rules

### Low Success Rate Alert

**Condition**: Query
**Query**:
```sql
SELECT
    (SUM(CASE WHEN success = TRUE THEN 1 ELSE 0 END) * 100.0 / COUNT(*)) as success_rate
FROM executions
WHERE timestamp >= NOW() - INTERVAL '1 hour';
```

**Alert Criteria**:
- **Warning**: success_rate < 85%
- **Critical**: success_rate < 70%

**Evaluation**: Every 1 minute
**For**: 5 minutes

### No Recent Executions Alert

**Condition**: Query
**Query**:
```sql
SELECT COUNT(*) as count
FROM executions
WHERE timestamp >= NOW() - INTERVAL '1 hour';
```

**Alert Criteria**:
- **Warning**: count = 0 (and total executions > 0)

**Evaluation**: Every 5 minutes
**For**: 10 minutes

### High Error Rate Alert

**Condition**: Query
**Query**:
```sql
SELECT
    (SUM(CASE WHEN error_type IS NOT NULL THEN 1 ELSE 0 END) * 100.0 / COUNT(*)) as error_rate
FROM executions
WHERE timestamp >= NOW() - INTERVAL '1 hour';
```

**Alert Criteria**:
- **Warning**: error_rate > 10%
- **Critical**: error_rate > 25%

**Evaluation**: Every 1 minute
**For**: 5 minutes

### Database Size Alert

**Condition**: Query (via script)
**Script**: `python3 scripts/monitor_database.py --metric cost`

**Alert Criteria**:
- **Warning**: Database size > 500 MB
- **Critical**: Database size > 1 GB

**Evaluation**: Every 10 minutes

## Real-Time Monitoring

### Live Executions Panel

**Query**:
```sql
SELECT
    timestamp as time,
    task_type,
    model_tier,
    success,
    duration_seconds,
    quality_score
FROM executions
WHERE timestamp >= NOW() - INTERVAL '5 minutes'
ORDER BY timestamp DESC;
```

**Visualization**: Table
**Refresh**: Every 10 seconds

## Dashboard JSON Export

To export and share the dashboard:

1. Go to **Dashboard** → **Settings** → **JSON Model**
2. Copy the JSON
3. Save to `scripts/grafana_dashboard.json`

### Sample Dashboard JSON Structure

```json
{
  "dashboard": {
    "title": "Mahavishnu Learning Database",
    "tags": ["mahavishnu", "learning", "database"],
    "timezone": "browser",
    "panels": [
      {
        "title": "Executions per Day",
        "type": "timeseries",
        "targets": [
          {
            "datasource": "Mahavishnu Learning DB",
            "rawSql": "SELECT DATE_TRUNC('day', timestamp) as time, COUNT(*) as executions FROM executions WHERE timestamp >= NOW() - INTERVAL '30 days' GROUP BY DATE_TRUNC('day', timestamp) ORDER BY time DESC"
          }
        ]
      },
      {
        "title": "Success Rate",
        "type": "stat",
        "targets": [
          {
            "datasource": "Mahavishnu Learning DB",
            "rawSql": "SELECT (SUM(CASE WHEN success = TRUE THEN 1 ELSE 0 END) * 100.0 / COUNT(*)) as success_rate FROM executions WHERE timestamp >= NOW() - INTERVAL '24 hours'"
          }
        ],
        "options": {
          "graphMode": "area",
          "colorMode": "value"
        }
      }
    ]
  }
}
```

## MCP Tool Integration

You can also query the database via MCP tools:

### database_status

```bash
# Via MCP client
mcp call database_status

# Returns JSON with:
# - Overall status (OK, WARNING, ERROR)
# - Database metadata
# - Execution counts
# - Performance metrics
```

### execution_statistics

```bash
# Via MCP client
mcp call execution_statistics --time_range "7d"

# Returns:
# - Time series data
# - By model tier
# - By pool type
# - Top repositories
```

### performance_metrics

```bash
# Via MCP client
mcp call performance_metrics --time_range "7d"

# Returns:
# - Duration percentiles
# - Cost analysis
# - Resource utilization
```

## Automation

### Cron Jobs

Add to crontab for periodic checks:

```bash
# Check database health every 5 minutes
*/5 * * * * cd /Users/les/Projects/mahavishnu && python3 scripts/monitor_database.py

# Generate daily report at 9 AM
0 9 * * * cd /Users/les/Projects/mahavishnu && python3 scripts/monitor_database.py --stats > data/monitoring_$(date +\%Y\%m\%d).json

# Weekly performance summary on Sundays at 10 AM
0 10 * * 0 cd /Users/les/Projects/mahavishnu && python3 scripts/monitor_database.py --metric performance --time_range 7d
```

### Alert Notifications

Configure Grafana notifications to:
- Slack
- Email
- PagerDuty
- Webhook

Example webhook configuration:

```yaml
# Grafana alert webhook
url: "http://localhost:8678/alerts"
method: POST
headers:
  Content-Type: application/json
```

## Performance Optimization

### Query Optimization

1. **Use time bounds**: Always filter by `timestamp >= NOW() - INTERVAL 'X days'`
2. **Limit results**: Use `LIMIT` for top-N queries
3. **Create indexes**: See `scripts/migrate_learning_db.py` for index definitions

### Materialized Views

The database includes pre-computed views for fast queries:
- `tier_performance_mv`: Performance by model tier
- `pool_performance_mv`: Performance by pool type
- `solution_patterns_mv`: Common solution patterns

Use these instead of raw queries for better performance.

## Troubleshooting

### Database Locked Error

If you see "database is locked":
```bash
# Check for other processes
lsof data/learning.db

# Close existing connections
kill -9 <PID>

# Or use read-only mode in Grafana
```

### No Data in Dashboard

If panels show no data:
```bash
# Check database has data
python3 scripts/monitor_database.py

# Verify query syntax
sqlite3 data/learning.db "SELECT COUNT(*) FROM executions"
```

### Grafana Plugin Issues

If DuckDB/SQLite plugin fails:
1. Check Grafana logs: `journalctl -u grafana`
2. Reinstall plugin: `grafana-cli plugins uninstall grafana-sqlite-datasource`
3. Restart Grafana: `systemctl restart grafana`

## Next Steps

1. Set up Grafana with DuckDB data source
2. Import dashboard queries
3. Configure alert rules
4. Set up notification channels
5. Monitor dashboard and tune alert thresholds
6. Add custom panels as needed

## Resources

- Grafana Documentation: https://grafana.com/docs/
- DuckDB Documentation: https://duckdb.org/docs/
- Dashboard Queries: `/Users/les/Projects/mahavishnu/scripts/dashboard_queries.sql`
- Monitoring Script: `/Users/les/Projects/mahavishnu/scripts/monitor_database.py`
- MCP Tools: `/Users/les/Projects/mahavishnu/mahavishnu/mcp/tools/database_tools.py`
