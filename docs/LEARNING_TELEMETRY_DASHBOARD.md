# Learning Telemetry Dashboard Setup Guide

**Version:** 1.0.0
**Last Updated:** 2026-02-09
**Status:** Production Ready

## Overview

The Learning Telemetry Dashboard provides comprehensive monitoring and analytics for the ORB Learning Feedback Loops system. It visualizes execution telemetry, model tier performance, pool utilization, and quality metrics from the DuckDB learning database.

## Quick Start

### Prerequisites

1. **Grafana Installation:**
   ```bash
   # macOS
   brew install grafana

   # Linux
   sudo apt-get install grafana

   # Docker
   docker run -d -p 3000:3000 --name grafana grafana/grafana
   ```

2. **DuckDB Plugin for Grafana:**
   ```bash
   grafana-cli plugins install duckdb-datasource

   # Restart Grafana after plugin installation
   brew services restart grafana  # macOS
   systemctl restart grafana-server  # Linux
   docker restart grafana  # Docker
   ```

3. **Learning Database:**
   ```bash
   # Initialize the learning database
   python scripts/migrate_learning_db.py
   ```

### Automated Setup

```bash
# Run complete setup
./scripts/setup_learning_dashboard.sh setup

# Or setup individual components
./scripts/setup_learning_dashboard.sh datasource  # Setup datasource only
./scripts/setup_learning_dashboard.sh dashboard   # Deploy dashboard only
./scripts/setup_learning_dashboard.sh test        # Test queries
```

### Manual Setup

#### 1. Configure DuckDB Datasource

In Grafana UI:
1. Go to **Configuration → Data Sources**
2. Click **Add data source**
3. Select **DuckDB**
4. Configure:
   - **Name:** `DuckDB Learning`
   - **Path:** `/path/to/mahavishnu/data/learning.db`
   - **UID:** `duckdb-learning`
5. Click **Save & Test**

#### 2. Import Dashboard

1. Go to **Dashboards → Import**
2. Click **Upload JSON file**
3. Select `grafana/dashboards/learning-telemetry.json`
4. Select **DuckDB Learning** as datasource
5. Click **Import**

## Dashboard Panels

### Summary Statistics (Top Row)

1. **Execution Count (Last 24 Hours)**
   - Total number of task executions
   - Thresholds: 0 (blue), 100 (green), 1000 (yellow)

2. **Success Rate (Last 24 Hours)**
   - Percentage of successful executions
   - Thresholds: 0% (red), 90% (yellow), 95% (green)

3. **Average Quality Score (Last 24 Hours)**
   - Mean quality score (0-100)
   - Thresholds: 0 (red), 60 (yellow), 75 (green), 90 (blue)

4. **Total Cost (Last 24 Hours)**
   - Sum of actual costs in USD
   - Thresholds: $0 (green), $1 (yellow), $5 (red)

### Time Series Panels

1. **Executions Over Time (Last 7 Days)**
   - Hourly execution counts
   - Identifies traffic patterns and trends

2. **Success Rate Over Time (Last 7 Days)**
   - Daily success rate percentages
   - Shows reliability trends

### Performance Analysis

1. **Success Rate by Model Tier**
   - Horizontal bar gauge comparing model tiers
   - Helps identify best/worst performing tiers

2. **Average Duration by Model Tier**
   - Execution time comparison across tiers
   - Identifies performance bottlenecks

3. **Cost by Model Tier (Last 7 Days)**
   - Donut chart showing cost distribution
   - Tracks spending across model tiers

### Pool Comparison

1. **Pool Performance Comparison (Last 7 Days)**
   - Table with metrics for each pool type:
     - Execution count
     - Success rate
     - Average duration
     - Average cost

### Repository Analysis

1. **Top Repositories by Execution Count (Last 30 Days)**
   - Top 10 repositories by usage
   - Shows quality, duration, and cost metrics

### Quality & Error Analysis

1. **Duration Percentiles (Last 7 Days)**
   - P50, P95, P99 duration values
   - Identifies outliers and tail latency

2. **Quality Score Distribution (Last 30 Days)**
   - Pie chart of quality tiers (excellent/good/fair/poor)

3. **Task Type Distribution (Last 30 Days)**
   - Top 15 task types by execution count
   - Shows duration and quality metrics

4. **Top Error Types (Last 7 Days)**
   - Most frequent error types
   - Shows count and last occurrence time

### Database Health

1. **Database Size Growth (Last 30 Days)**
   - Total number of execution records
   - Tracks database growth

2. **Average Routing Confidence (Last 7 Days)**
   - Mean routing confidence percentage
   - Indicates routing accuracy

## Queries Used

All dashboard queries are optimized for DuckDB and located in `scripts/dashboard_queries.sql`. Key query patterns:

### Time Series Aggregation

```sql
SELECT
    DATE_TRUNC('hour', timestamp) as time,
    COUNT(*) as executions
FROM executions
WHERE timestamp >= NOW() - INTERVAL '7 days'
GROUP BY time
ORDER BY time;
```

### Success Rate Calculation

```sql
SELECT
    model_tier,
    (SUM(CASE WHEN success = TRUE THEN 1 ELSE 0 END) * 100.0 / COUNT(*)) as success_rate
FROM executions
WHERE timestamp >= NOW() - INTERVAL '7 days'
GROUP BY model_tier;
```

### Percentile Calculation

```sql
SELECT
    PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY duration_seconds) as p50,
    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY duration_seconds) as p95,
    PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY duration_seconds) as p99
FROM executions
WHERE timestamp >= NOW() - INTERVAL '7 days';
```

## Configuration

### Environment Variables

The setup script supports the following environment variables:

```bash
# Grafana Configuration
export GRAFANA_URL="http://localhost:3000"
export GRAFANA_USER="admin"
export GRAFANA_PASSWORD="admin"

# Database Configuration
export LEARNING_DB_PATH="/path/to/mahavishnu/data/learning.db"
```

### Dashboard Refresh Intervals

Default refresh: `1 minute`

Recommended intervals by panel type:
- Summary stats: 30s - 1m
- Time series (7 days): 5m
- Time series (24 hours): 1m
- Tables (historical): 10m
- Database size: 1h

### Time Range

Default: `Last 24 hours`

Recommended time ranges for analysis:
- Real-time monitoring: Last 1 hour
- Daily operations: Last 24 hours
- Weekly trends: Last 7 days
- Monthly analysis: Last 30 days

## Troubleshooting

### Dashboard Shows No Data

**Problem:** All panels show "No Data"

**Solutions:**
1. Verify learning database has records:
   ```bash
   python -c "import duckdb; con = duckdb.connect('data/learning.db'); print(con.execute('SELECT COUNT(*) FROM executions').fetchone()[0])"
   ```

2. Check datasource connection:
   - Go to Configuration → Data Sources
   - Click "Test" button
   - Verify no connection errors

3. Verify DuckDB plugin is installed:
   ```bash
   grafana-cli plugins ls | grep duckdb
   ```

### Datasource Connection Failed

**Problem:** "Failed to connect to datasource"

**Solutions:**
1. Verify database path is correct and accessible
2. Check Grafana has file system permissions
3. Ensure database file is not corrupted:
   ```bash
   python -c "import duckdb; con = duckdb.connect('data/learning.db'); con.execute('SELECT 1').fetchall()"
   ```

### DuckDB Plugin Not Found

**Problem:** DuckDB datasource type not available

**Solutions:**
1. Install the plugin:
   ```bash
   grafana-cli plugins install duckdb-datasource
   ```

2. Restart Grafana after installation

3. Verify installation:
   ```bash
   grafana-cli plugins ls | grep duckdb
   ```

### Queries Are Slow

**Problem:** Dashboard panels take long to load

**Solutions:**
1. Create materialized views for frequently queried data:
   ```sql
   CREATE MATERIALIZED VIEW tier_performance_mv AS
   SELECT
       model_tier,
       COUNT(*) as executions,
       AVG(duration_seconds) as avg_duration,
       (SUM(CASE WHEN success = TRUE THEN 1 ELSE 0 END) * 100.0 / COUNT(*)) as success_rate
   FROM executions
   WHERE timestamp >= NOW() - INTERVAL '7 days'
   GROUP BY model_tier;
   ```

2. Add indexes on frequently queried columns:
   ```sql
   CREATE INDEX idx_executions_timestamp ON executions(timestamp);
   CREATE INDEX idx_executions_model_tier ON executions(model_tier);
   ```

3. Reduce time range for time series queries
4. Increase refresh interval

### Permission Denied Errors

**Problem:** Setup script fails with permission errors

**Solutions:**
1. Ensure script is executable:
   ```bash
   chmod +x scripts/setup_learning_dashboard.sh
   ```

2. Check Grafana API credentials are correct

3. Verify user has datasource creation permissions

## Alerting Setup

### Example Alerts

1. **Low Success Rate Alert:**
   - Condition: Success rate < 90% for 5 minutes
   - Severity: Warning
   - Notification: Email/Slack

2. **High Cost Alert:**
   - Condition: Hourly cost > $10
   - Severity: Warning
   - Notification: Email

3. **Database Size Alert:**
   - Condition: Database > 1GB
   - Severity: Info
   - Notification: Email

### Setting Up Alerts

1. Click alert icon on any panel
2. Set alert conditions
3. Configure notification channels
4. Test alert

## Advanced Configuration

### Custom Queries

To add custom queries to the dashboard:

1. Edit panel in Grafana UI
2. Modify SQL query
3. Test query
4. Save dashboard
5. Export updated JSON:
   ```bash
   curl -u admin:admin http://localhost:3000/api/dashboards/db/learning-telemetry > learning-telemetry-updated.json
   ```

### Multiple Environments

For development, staging, and production:

1. Create separate datasources for each environment
2. Duplicate dashboard for each environment
3. Update datasource references
4. Set environment-specific time ranges

### Export Dashboard

```bash
# Export via API
curl -u admin:admin \
  http://localhost:3000/api/dashboards/db/learning-telemetry \
  | jq '.dashboard' > learning-telemetry-export.json

# Export via UI
# Dashboards → learning-telemetry → Settings → JSON Model → Copy to File
```

## Performance Optimization

### Database Optimization

```sql
-- Enable query optimization
PRAGMA enable_optimizer=true;

-- Set memory limit (adjust based on available RAM)
PRAGMA memory_limit='2GB';

-- Enable parallel processing
PRAGMA threads=4;

-- Create indexes for common queries
CREATE INDEX idx_executions_timestamp_tier ON executions(timestamp, model_tier);
CREATE INDEX idx_executions_success ON executions(success) WHERE success = FALSE;
```

### Dashboard Optimization

1. **Reduce query frequency:**
   - Set longer refresh intervals for historical data
   - Use 5-10 minute refresh for 30-day queries

2. **Optimize query time ranges:**
   - Use shorter time ranges for real-time monitoring
   - Create separate dashboards for different time scales

3. **Cache results:**
   - Enable query caching in Grafana
   - Set cache TTL to match refresh interval

## Maintenance

### Backup Dashboard

```bash
# Automatic backup (created by setup script)
cp grafana/dashboards/learning-telemetry.json \
   grafana/dashboards/backups/learning-telemetry-$(date +%Y%m%d).json
```

### Update Dashboard

```bash
# Pull latest changes
git pull

# Redeploy dashboard
./scripts/setup_learning_dashboard.sh dashboard
```

### Database Maintenance

```sql
-- Vacuum and reclaim space
VACUUM;

-- Analyze table statistics
ANALYZE executions;

-- Check integrity
PRAGMA integrity_check;

-- Export database statistics
SELECT
    COUNT(*) as total_rows,
    MIN(timestamp) as first_record,
    MAX(timestamp) as last_record,
    (SUM(CASE WHEN success = TRUE THEN 1 ELSE 0 END) * 100.0 / COUNT(*)) as success_rate
FROM executions;
```

## Related Documentation

- **ADR-006:** DuckDB Learning Database Architecture
  - Location: `/Users/les/Projects/mahavishnu/docs/adr/006-duckdb-learning-database.md`
- **Query Reference:** Dashboard SQL Queries
  - Location: `/Users/les/Projects/mahavishnu/scripts/dashboard_queries.sql`
- **Database Migration:** Learning Database Setup
  - Location: `/Users/les/Projects/mahavishnu/scripts/migrate_learning_db.py`
- **Monitoring:** Database Monitoring Guide
  - Location: `/Users/les/Projects/mahavishnu/docs/DATABASE_MONITORING_GRAFANA.md`

## Support

For issues or questions:

1. Check this guide's troubleshooting section
2. Review Grafana logs: `/var/log/grafana/` or Docker logs
3. Review setup script log: `scripts/setup_learning_dashboard.log`
4. Check DuckDB documentation: https://duckdb.org/docs/
5. Check Grafana documentation: https://grafana.com/docs/

## Changelog

### v1.0.0 (2026-02-09)
- Initial release
- 17 panels covering key telemetry metrics
- Automated setup script
- DuckDB datasource integration
- Comprehensive documentation
