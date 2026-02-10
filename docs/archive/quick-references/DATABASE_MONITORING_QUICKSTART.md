# Database Monitoring Quick Reference

Quick commands for monitoring the Mahavishnu learning database.

## Quick Health Check

```bash
# Basic health status
python3 scripts/monitor_database.py
```

## Detailed Statistics

```bash
# All statistics
python3 scripts/monitor_database.py --stats

# Execution statistics only
python3 scripts/monitor_database.py --metric executions

# Performance metrics
python3 scripts/monitor_database.py --metric performance

# Quality metrics
python3 scripts/monitor_database.py --metric quality
```

## Continuous Monitoring

```bash
# Watch mode (refresh every 60 seconds)
python3 scripts/monitor_database.py --watch

# Custom interval
python3 scripts/monitor_database.py --watch --interval 30
```

## Time Range Queries

```bash
# Last hour
python3 scripts/monitor_database.py --metric executions --time-range 1h

# Last 24 hours
python3 scripts/monitor_database.py --metric executions --time-range 24h

# Last 7 days (default)
python3 scripts/monitor_database.py --metric executions --time-range 7d

# Last 30 days
python3 scripts/monitor_database.py --metric executions --time-range 30d
```

## MCP Tools

```bash
# Start MCP server
mahavishnu mcp start

# Call database status tool
mcp call database_status

# Call execution statistics tool
mcp call execution_statistics --time-range 7d

# Call performance metrics tool
mcp call performance_metrics --time-range 7d
```

## SQL Queries

```bash
# Direct database access with duckdb
duckdb data/learning.db

# Example queries
# Execute in SQL shell:
SELECT COUNT(*) FROM executions;
SELECT * FROM executions ORDER BY timestamp DESC LIMIT 10;
SELECT model_tier, COUNT(*) FROM executions GROUP BY model_tier;
```

## Grafana Queries

Use queries from `scripts/dashboard_queries.sql`:

```bash
# View queries
cat scripts/dashboard_queries.sql

# Copy to Grafana SQL editor
# - Go to Dashboard → Edit → Query
# - Paste query
# - Run query
```

## Common Queries

### Executions Today
```sql
SELECT COUNT(*) FROM executions
WHERE DATE(timestamp) = CURRENT_DATE;
```

### Success Rate (Last 24 Hours)
```sql
SELECT
    (SUM(CASE WHEN success = TRUE THEN 1 ELSE 0 END) * 100.0 / COUNT(*)) as success_rate
FROM executions
WHERE timestamp >= NOW() - INTERVAL '24 hours';
```

### Average Duration (Last 7 Days)
```sql
SELECT AVG(duration_seconds) as avg_duration
FROM executions
WHERE timestamp >= NOW() - INTERVAL '7 days';
```

### Top Repositories (Last 30 Days)
```sql
SELECT repo, COUNT(*) as executions, AVG(quality_score) as avg_quality
FROM executions
WHERE timestamp >= NOW() - INTERVAL '30 days'
GROUP BY repo
ORDER BY executions DESC
LIMIT 10;
```

### Errors by Type (Last 7 Days)
```sql
SELECT error_type, COUNT(*) as count, MAX(timestamp) as last_seen
FROM executions
WHERE error_type IS NOT NULL
  AND timestamp >= NOW() - INTERVAL '7 days'
GROUP BY error_type
ORDER BY count DESC;
```

## Status Codes

- **OK**: Database healthy, metrics within thresholds
- **WARNING**: Potential issues detected (e.g., no recent activity, low success rate)
- **ERROR**: Database connection failed or critical error
- **CRITICAL**: Severe issues requiring immediate attention

## Warning Messages

Common warnings and their meanings:

- "No execution records found": Database is empty (normal initially)
- "No recent activity (last hour)": No executions in last hour (check if system is running)
- "Low success rate: XX%": Success rate below 80% (investigate task failures)
- "Database size above threshold": Database growing large (consider archival)

## Automation

### Cron Jobs

```bash
# Edit crontab
crontab -e

# Add monitoring jobs
*/5 * * * * cd /Users/les/Projects/mahavishnu && python3 scripts/monitor_database.py
0 9 * * * cd /Users/les/Projects/mahavishnu && python3 scripts/monitor_database.py --stats > data/daily_report_$(date +\%Y\%m\%d).json
```

### Watch Mode with Logging

```bash
# Run in background with logging
nohup python3 scripts/monitor_database.py --watch --interval 300 > data/monitoring.log 2>&1 &

# Check log
tail -f data/monitoring.log
```

## Troubleshooting

### Database Locked
```bash
# Check for other processes
lsof data/learning.db

# Kill if needed
kill -9 <PID>
```

### No Data Showing
```bash
# Verify database has data
python3 scripts/monitor_database.py

# Check schema
duckdb data/learning.db "SELECT * FROM information_schema.tables"
```

### Permission Denied
```bash
# Make script executable
chmod +x scripts/monitor_database.py

# Check file permissions
ls -la data/learning.db
```

## File Locations

- **Monitoring Script**: `/Users/les/Projects/mahavishnu/scripts/monitor_database.py`
- **Dashboard Queries**: `/Users/les/Projects/mahavishnu/scripts/dashboard_queries.sql`
- **MCP Tools**: `/Users/les/Projects/mahavishnu/mahavishnu/mcp/tools/database_tools.py`
- **Database**: `/Users/les/Projects/mahavishnu/data/learning.db`
- **Documentation**: `/Users/les/Projects/mahavishnu/docs/DATABASE_MONITORING_*.md`

## Output Formats

### JSON Output
```bash
# Get JSON output (for parsing)
python3 scripts/monitor_database.py --stats 2>/dev/null | jq '.executions'
```

### Human Readable
```bash
# Default human-readable format
python3 scripts/monitor_database.py
```

### Save to File
```bash
# Save statistics
python3 scripts/monitor_database.py --stats > data/stats.json

# Append to log
python3 scripts/monitor_database.py >> data/monitoring.log
```

## Performance Tips

1. **Always use time ranges** in queries to limit data scanned
2. **Use materialized views** (`tier_performance_mv`, `pool_performance_mv`) for faster queries
3. **Set appropriate intervals** in watch mode (don't poll too frequently)
4. **Use indexes** - they're already created for common query patterns
5. **Archive old data** if database grows too large

## Getting Help

```bash
# Help for monitoring script
python3 scripts/monitor_database.py --help

# Check logs
tail -f data/monitoring.log

# Verbose mode
python3 scripts/monitor_database.py --verbose
```

## Quick Status Check

```bash
# One-liner to check if database is healthy
python3 scripts/monitor_database.py 2>&1 | grep "^Status:" | cut -d' ' -f2
```

## MCP Tool Examples

```json
// database_status tool call
{
  "tool": "database_status",
  "parameters": {}
}

// execution_statistics tool call
{
  "tool": "execution_statistics",
  "parameters": {
    "time_range": "7d"
  }
}

// performance_metrics tool call
{
  "tool": "performance_metrics",
  "parameters": {
    "time_range": "30d"
  }
}
```

## Dashboard URLs

If Grafana is running on localhost:3035:

- **Dashboard**: http://localhost:3035/d/mahavishnu-learning
- **Data Source**: http://localhost:3035/datasources/edit/mahavishnu-learning-db
- **Alerts**: http://localhost:3035/alerting

## Key Metrics to Watch

1. **Success Rate**: Should be > 80%
2. **Daily Executions**: Should be > 0 (when system is active)
3. **Average Duration**: Track for performance trends
4. **Database Size**: Monitor growth rate
5. **Error Types**: Track recurring errors

## Emergency Commands

```bash
# If database is corrupted, restore from backup
python3 scripts/migrate_learning_db.py reset

# Validate database schema
python3 scripts/migrate_learning_db.py validate

# Check database integrity
duckdb data/learning.db "PRAGMA database_size"
```

## Summary

The monitoring system provides:
- ✅ Real-time health checks
- ✅ Detailed execution statistics
- ✅ Performance metrics
- ✅ Quality indicators
- ✅ Cost tracking
- ✅ Error analysis
- ✅ MCP tools integration
- ✅ Grafana dashboards
- ✅ Automated alerts

**Current Status**: Database ready, awaiting execution data
**Next Step**: Run workflows to populate database with execution records
