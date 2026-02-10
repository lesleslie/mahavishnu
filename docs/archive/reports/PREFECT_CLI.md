# Prefect CLI Documentation

The Mahavishnu Prefect CLI provides comprehensive command-line tools for managing Prefect flows, deployments, schedules, and monitoring with rich console output and progress tracking.

## Installation

The Prefect CLI is included with Mahavishnu when the Prefect adapter is installed:

```bash
# Install with Prefect support
pip install -e ".[prefect]"

# Or install all adapters
pip install -e ".[all]"
```

## Quick Start

```bash
# Create a new flow
mahavishnu prefect flow create --name my-flow

# Execute a flow
mahavishnu prefect flow execute my-flow

# Deploy a flow
mahavishnu prefect deploy my-flow --name my-deployment --work-pool my-pool

# List flow runs
mahavishnu prefect flow-runs list

# Open Prefect dashboard
mahavishnu prefect dashboard --open
```

## Command Reference

### Flow Management

#### `mahavishnu prefect flow create`

Create a new Prefect flow.

**Usage:**
```bash
mahavishnu prefect flow create --name <name> [OPTIONS]
```

**Options:**
- `--name, -n`: Flow name (required)
- `--description, -d`: Flow description
- `--tags, -t`: Comma-separated tags for organization
- `--output, -o`: Output format (table, json) [default: table]

**Examples:**
```bash
# Create a basic flow
mahavishnu prefect flow create --name my-flow

# Create with description and tags
mahavishnu prefect flow create --name "Data Pipeline" \
  --description "Daily ETL pipeline" \
  --tags "etl,daily,production"

# Output as JSON
mahavishnu prefect flow create --name my-flow --output json
```

**Output (table format):**
```
┏━━━━━━━━━━━━━━━━━━━━┓
┃ ✓ Flow Created     ┃
┡━━━━━━━━━━━━━━━━━━━━┩
│ Name:              my-flow
│ ID:                abc123-def456...
│ Version:           1.0.0
│ Deployed:          No
└────────────────────┘
```

---

#### `mahavishnu prefect flow execute`

Execute a Prefect flow.

**Usage:**
```bash
mahavishnu prefect flow execute <flow_name> [OPTIONS]
```

**Options:**
- `flow_name`: Name of flow to execute (required)
- `--param, -p`: Flow parameters (key=value) can be specified multiple times
- `--deployment, -d`: Deployment name to use
- `--wait, -w`: Wait for completion before returning
- `--timeout, -T`: Timeout in seconds [default: 300]
- `--output, -o`: Output format (table, json) [default: table]

**Examples:**
```bash
# Execute a flow
mahavishnu prefect flow execute my-flow

# Execute with parameters
mahavishnu prefect flow execute my-flow \
  --param env=prod \
  --param retries=3 \
  --param batch_size=100

# Execute from deployment and wait
mahavishnu prefect flow execute my-flow \
  --deployment my-deployment \
  --wait
```

**Output:**
```
┏━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ ✓ Flow Execution Started ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ Flow:              my-flow
│ Run ID:            run-abc123...
│ Status:            running
│ Started:           2024-01-01 12:00:00
│
│ Parameters:
│   env:             prod
│   retries:         3
└────────────────────────────┘
```

---

#### `mahavishnu prefect flow list`

List all Prefect flows.

**Usage:**
```bash
mahavishnu prefect flow list [OPTIONS]
```

**Options:**
- `--limit, -l`: Maximum flows to show [default: 50]
- `--deployed, -d`: Show only deployed flows
- `--output, -o`: Output format (table, json) [default: table]

**Examples:**
```bash
# List all flows
mahavishnu prefect flow list

# List only deployed flows
mahavishnu prefect flow list --deployed

# Limit to 20 flows
mahavishnu prefect flow list --limit 20

# Output as JSON
mahavishnu prefect flow list --output json
```

**Output:**
```
                    Prefect Flows (15)
┏━━━━━━━━━┳━━━━━━━━┳━━━━━━━━┳━━━━━━━━┳━━━━━━━━┳━━━━━━┓
┃ Name    ┃ ID     ┃ Version┃Deployed┃Last Run┃Status┃
┡━━━━━━━━━╇━━━━━━━━╇━━━━━━━━╇━━━━━━━━╇━━━━━━━━╇━━━━━━┩
│ my-flow │abc123..│ 1.0.0  │   No   │ Never  │  -   │
│ etl-job │def456..│ 2.1.0  │  Yes   │2h ago  │✓     │
└─────────┴────────┴────────┴────────┴────────┴──────┘
```

---

#### `mahavishnu prefect flow validate`

Validate a flow definition file.

**Usage:**
```bash
mahavishnu prefect flow validate <flow_path> [OPTIONS]
```

**Options:**
- `flow_path`: Path to flow Python file (required)
- `--output, -o`: Output format (table, json) [default: table]

**Examples:**
```bash
# Validate a flow file
mahavishnu prefect flow validate my_flow.py

# Validate with JSON output
mahavishnu prefect flow validate flows/etl_pipeline.py --output json
```

**Output:**
```
┏━━━━━━━━━━━━━━━━━━┓
┃ ✓ Flow is Valid  ┃
┡━━━━━━━━━━━━━━━━━━┩
│
│ No errors found.
└──────────────────┘
```

---

### Deployment Management

#### `mahavishnu prefect deploy`

Deploy a flow to Prefect.

**Usage:**
```bash
mahavishnu prefect deploy <flow_name> --name <deployment_name> [OPTIONS]
```

**Options:**
- `flow_name`: Name of flow to deploy (required)
- `--name, -n`: Deployment name (required)
- `--work-pool, -w`: Work pool name for execution
- `--cron, -c`: Cron schedule expression
- `--param, -p`: Default parameters (key=value)
- `--output, -o`: Output format (table, json) [default: table]

**Examples:**
```bash
# Basic deployment
mahavishnu prefect deploy my-flow --name my-deployment

# Deploy with work pool
mahavishnu prefect deploy my-flow \
  --name prod-deployment \
  --work-pool my-pool

# Deploy with schedule
mahavishnu prefect deploy my-flow \
  --name scheduled-deployment \
  --cron "0 0 * * *"

# Deploy with default parameters
mahavishnu prefect deploy my-flow \
  --name my-deployment \
  --param env=prod \
  --param retries=3
```

**Output:**
```
┏━━━━━━━━━━━━━━━━━━┓
┃ ✓ Flow Deployed  ┃
┡━━━━━━━━━━━━━━━━━━┩
│ Deployment:       my-deployment
│ Flow:             my-flow
│ ID:               deploy-abc123...
│ Status:           deployed
│ Work Pool:        my-pool
│ Schedule:         0 0 * * *
│ Created:          2024-01-01 12:00:00
└───────────────────┘
```

---

#### `mahavishnu prefect undeploy`

Undeploy a flow deployment.

**Usage:**
```bash
mahavishnu prefect undeploy <deployment_name>
```

**Examples:**
```bash
mahavishnu prefect undeploy my-deployment
```

---

#### `mahavishnu prefect deployments list`

List all deployments.

**Usage:**
```bash
mahavishnu prefect deployments list [OPTIONS]
```

**Options:**
- `--flow, -f`: Filter by flow name
- `--limit, -l`: Maximum deployments to show [default: 50]
- `--output, -o`: Output format (table, json) [default: table]

**Examples:**
```bash
# List all deployments
mahavishnu prefect deployments list

# Filter by flow
mahavishnu prefect deployments list --flow my-flow

# Limit results
mahavishnu prefect deployments list --limit 20
```

**Output:**
```
                    Deployments (5)
┏━━━━━━━━━━━━━━┳━━━━━━━┳━━━━━━━━┳━━━━━━━━┳━━━━━━┓
┃ Name         ┃ Flow  ┃Work Pool┃ Status ┃Created┃
┡━━━━━━━━━━━━━━╇━━━━━━━╇━━━━━━━━╇━━━━━━━━╇━━━━━━┩
│ my-deploy    │my-flow│my-pool  │deployed│2d ago│
│ prod-deploy  │etl-job│prod-pool│deployed│1w ago│
└──────────────┴───────┴─────────┴────────┴───────┘
```

---

### Schedule Management

#### `mahavishnu prefect schedule create`

Create a schedule for a flow.

**Usage:**
```bash
mahavishnu prefect schedule create <flow_name> --type <type> [OPTIONS]
```

**Options:**
- `flow_name`: Flow name (required)
- `--type, -t`: Schedule type (cron, interval) [required]
- `--cron, -c`: Cron expression (required for cron type)
- `--interval, -i`: Interval in seconds (required for interval type)
- `--param, -p`: Default parameters (key=value)
- `--output, -o`: Output format (table, json) [default: table]

**Examples:**
```bash
# Create cron schedule (daily at midnight)
mahavishnu prefect schedule create my-flow \
  --type cron \
  --cron "0 0 * * *"

# Create interval schedule (every hour)
mahavishnu prefect schedule create my-flow \
  --type interval \
  --interval 3600

# Create with parameters
mahavishnu prefect schedule create my-flow \
  --type cron \
  --cron "*/5 * * * *" \
  --param env=prod
```

**Cron Expression Examples:**
```
0 0 * * *      # Daily at midnight
0 */6 * * *    # Every 6 hours
0 9 * * 1-5    # 9am on weekdays
*/30 * * * *   # Every 30 minutes
0 0 1 * *      # Monthly on the 1st
```

**Output:**
```
┏━━━━━━━━━━━━━━━━━━━━┓
┃ ✓ Schedule Created ┃
┡━━━━━━━━━━━━━━━━━━━━┩
│ Flow:              my-flow
│ Type:              cron
│ Cron:              0 0 * * *
│ Active:            Yes
│ Next Run:          2024-01-02 00:00:00
└────────────────────┘
```

---

#### `mahavishnu prefect schedule list`

List all schedules.

**Usage:**
```bash
mahavishnu prefect schedule list [OPTIONS]
```

**Options:**
- `--flow, -f`: Filter by flow name
- `--output, -o`: Output format (table, json) [default: table]

**Examples:**
```bash
# List all schedules
mahavishnu prefect schedule list

# Filter by flow
mahavishnu prefect schedule list --flow my-flow
```

**Output:**
```
                    Schedules (3)
┏━━━━━━━━┳━━━━━━┳━━━━━━━━━━┳━━━━━━┳━━━━━━━━━━━━━━━━┓
┃ Flow   ┃ Type ┃ Schedule  ┃Active┃ Next Run       ┃
┡━━━━━━━━╇━━━━━━╇━━━━━━━━━━╇━━━━━━╇━━━━━━━━━━━━━━━━┩
│my-flow │cron  │0 0 * * * │  Yes │2024-01-02 00:00│
│etl-job │inter │3600s     │  Yes │2024-01-01 13:00│
└────────┴──────┴──────────┴──────┴────────────────┘
```

---

#### `mahavishnu prefect schedule delete`

Delete a schedule.

**Usage:**
```bash
mahavishnu prefect schedule delete <schedule_id>
```

**Examples:**
```bash
mahavishnu prefect schedule delete abc123-def456
```

---

#### `mahavishnu prefect backfill`

Backfill missed flow runs.

**Usage:**
```bash
mahavishnu prefect backfill <deployment_name> --start <date> --end <date> [OPTIONS]
```

**Options:**
- `deployment_name`: Deployment name (required)
- `--start, -s`: Start date (YYYY-MM-DD) [required]
- `--end, -e`: End date (YYYY-MM-DD) [required]
- `--max-runs, -m`: Maximum runs to create [default: 100]
- `--output, -o`: Output format (table, json) [default: table]

**Examples:**
```bash
# Backfill for January
mahavishnu prefect backfill my-deployment \
  --start 2024-01-01 \
  --end 2024-01-31

# Limit backfill runs
mahavishnu prefect backfill my-deployment \
  --start 2024-01-01 \
  --end 2024-01-31 \
  --max-runs 50
```

**Output:**
```
┏━━━━━━━━━━━━━━━━━━━━┓
┃ ✓ Backfill Created ┃
┡━━━━━━━━━━━━━━━━━━━━┩
│ Deployment:        my-deployment
│ Runs Created:      31
│ Date Range:        2024-01-01 to 2024-01-31
│
│ Backfill Runs:
│ Run ID      Flow       Status    Start Time
│ run-001..   my-flow    running   2024-01-01 00:00
│ run-002..   my-flow    running   2024-01-02 00:00
│ ... and 29 more
└───────────────────────┘
```

---

### Monitoring

#### `mahavishnu prefect flow-runs list`

List flow runs.

**Usage:**
```bash
mahavishnu prefect flow-runs list [OPTIONS]
```

**Options:**
- `--limit, -l`: Maximum runs to show [default: 50]
- `--flow, -f`: Filter by flow name
- `--state, -s`: Filter by state
- `--output, -o`: Output format (table, json) [default: table]

**Examples:**
```bash
# List all runs
mahavishnu prefect flow-runs list

# Filter by flow
mahavishnu prefect flow-runs list --flow my-flow

# Filter by state
mahavishnu prefect flow-runs list --state failed

# Limit results
mahavishnu prefect flow-runs list --limit 20
```

**Output:**
```
                    Flow Runs (50)
┏━━━━━━━━┳━━━━━━━┳━━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━┓
┃ Run ID ┃ Flow  ┃ Status ┃ Start Time   ┃Duratn┃
┡━━━━━━━━╇━━━━━━━╇━━━━━━━━╇━━━━━━━━━━━━━━╇━━━━━━┩
│run-001.│my-flow│✓complete│2024-01-01 12:00│45.2s │
│run-002.│etl-job│✗failed │2024-01-01 11:00│12.1s │
│run-003.│my-flow│↻running│2024-01-01 13:00│  -   │
└────────┴───────┴────────┴──────────────┴──────┘
```

---

#### `mahavishnu prefect flow-runs get`

Get flow run details.

**Usage:**
```bash
mahavishnu prefect flow-runs get <run_id> [OPTIONS]
```

**Options:**
- `run_id`: Flow run ID (required)
- `--output, -o`: Output format (table, json) [default: table]

**Examples:**
```bash
# Get run details
mahavishnu prefect flow-runs get abc123-def456

# Output as JSON
mahavishnu prefect flow-runs get abc123 --output json
```

**Output:**
```
┏━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃  Flow Run Details       ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ Run ID:              abc123-def456
│ Flow:                my-flow
│ Status:              completed
│
│ Start Time:          2024-01-01 12:00:00
│ End Time:            2024-01-01 12:00:45
│ Duration:            45.23 seconds
│
│ Deployment:          my-deployment
│ Message:             Flow completed successfully
└──────────────────────┘
```

---

#### `mahavishnu prefect dashboard`

Open Prefect UI dashboard.

**Usage:**
```bash
mahavishnu prefect dashboard [OPTIONS]
```

**Options:**
- `--open, -o`: Open in browser

**Examples:**
```bash
# Show dashboard URL
mahavishnu prefect dashboard

# Open in browser
mahavishnu prefect dashboard --open
```

**Output:**
```
┏━━━━━━━━━━━━━━━━━━━━━━━┓
┃  Prefect Dashboard     ┃
┡━━━━━━━━━━━━━━━━━━━━━━━┩
│ URL:                 http://localhost:4200
│
│ Tip: Use --open flag to open in browser
└──────────────────────┘
```

---

#### `mahavishnu prefect visualize`

Visualize flow DAG.

**Usage:**
```bash
mahavishnu prefect visualize <flow_name> [OPTIONS]
```

**Options:**
- `flow_name`: Flow name (required)
- `--output, -o`: Output file path
- `--format, -f`: Visualization format (mermaid, dot) [default: mermaid]

**Examples:**
```bash
# Display visualization
mahavishnu prefect visualize my-flow

# Save to file
mahavishnu prefect visualize my-flow --output flow_dag.mmd

# Export as DOT format
mahavishnu prefect visualize my-flow --format dot --output flow_dag.dot
```

**Output:**
```
┏━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Flow Visualization: my-flow ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ ```mermaid
│ graph TD
│     Start([Start]) --> Task1[Task 1]
│     Task1 --> Task2[Task 2]
│     Task2 --> Task3[Task 3]
│     Task3 --> End([End])
│ ```
└───────────────────────────┘
```

---

## Configuration

### Prefect Settings

Configure Prefect in `settings/mahavishnu.yaml`:

```yaml
adapters:
  prefect: true

# Prefect-specific settings
prefect:
  api_url: "http://localhost:4200/api"
  cloud_url: "https://api.prefect.cloud/api"
  workspace: "my-workspace"

  # Default work pool
  default_work_pool: "my-pool"

  # Concurrency limits
  max_concurrent_flows: 10
  max_concurrent_deployments: 5
```

### Environment Variables

Override configuration with environment variables:

```bash
export PREFECT_API_URL="http://localhost:4200/api"
export PREFECT_CLOUD_URL="https://api.prefect.cloud/api"
export PREFECT_WORKSPACE="my-workspace"
```

---

## Workflows and Examples

### Complete Flow Lifecycle

```bash
# 1. Create a flow
mahavishnu prefect flow create \
  --name "data-pipeline" \
  --description "Daily ETL pipeline" \
  --tags "etl,daily,production"

# 2. Validate the flow
mahavishnu prefect flow validate flows/data_pipeline.py

# 3. Execute the flow manually
mahavishnu prefect flow execute data-pipeline \
  --param env=prod \
  --param batch_date=2024-01-01

# 4. Deploy the flow
mahavishnu prefect deploy data-pipeline \
  --name "prod-data-pipeline" \
  --work-pool "prod-pool" \
  --cron "0 2 * * *"

# 5. Monitor the deployment
mahavishnu prefect flow-runs list --flow data-pipeline

# 6. Check specific run
mahavishnu prefect flow-runs get run-abc123

# 7. Visualize the flow
mahavishnu prefect visualize data-pipeline --output pipeline_dag.mmd
```

### Troubleshooting Failed Runs

```bash
# List failed runs
mahavishnu prefect flow-runs list --state failed --limit 20

# Get details of failed run
mahavishnu prefect flow-runs get run-failed123

# Re-run with same parameters
mahavishnu prefect flow execute data-pipeline \
  --param env=prod \
  --param batch_date=2024-01-01
```

### Backfilling Historical Data

```bash
# Create backfill for missed runs
mahavishnu prefect backfill prod-data-pipeline \
  --start 2024-01-01 \
  --end 2024-01-31 \
  --max-runs 31

# Monitor backfill progress
watch -n 5 'mahavishnu prefect flow-runs list --flow data-pipeline | head -20'
```

### Schedule Management

```bash
# Create daily schedule
mahavishnu prefect schedule create data-pipeline \
  --type cron \
  --cron "0 2 * * *" \
  --param env=prod

# List all schedules
mahavishnu prefect schedule list

# Delete a schedule
mahavishnu prefect schedule delete schedule-abc123

# Create interval schedule (hourly)
mahavishnu prefect schedule create monitoring-job \
  --type interval \
  --interval 3600
```

---

## Integration with Mahavishnu

### Using with Multi-Repository Workflows

The Prefect CLI integrates seamlessly with Mahavishnu's multi-repository orchestration:

```bash
# Execute flow across repositories
mahavishnu sweep --tag backend --adapter prefect

# Combine with repository filtering
mahavishnu prefect flow execute repo-sweep \
  --param repos="repo1,repo2,repo3" \
  --param tag="backend"
```

### Configuration Integration

Prefect settings are managed through Mahavishnu's unified configuration system:

```yaml
# settings/mahavishnu.yaml
adapters:
  prefect:
    enabled: true
    api_url: "http://localhost:4200/api"
    default_work_pool: "mahavishnu-pool"

# Local overrides
# settings/local.yaml
prefect:
  api_url: "http://prefect-server:4200/api"
  debug: true
```

---

## Best Practices

### Flow Organization

1. **Use descriptive names**: `data-pipeline-etl-prod` instead of `flow1`
2. **Tag your flows**: Use tags for filtering and organization
3. **Version your flows**: Track flow versions in deployment names
4. **Document parameters**: Always include descriptions for parameters

### Deployment Strategies

1. **Use work pools**: Organize deployments by environment/tenant
2. **Set appropriate schedules**: Use cron for fixed times, interval for frequency
3. **Configure timeouts**: Set reasonable timeouts for different flow types
4. **Enable retries**: Configure retry logic for resilient flows

### Monitoring and Alerts

1. **Check flow runs regularly**: Use `flow-runs list` to monitor status
2. **Track failed runs**: Filter by `--state failed` to identify issues
3. **Use dashboard**: Open Prefect UI for visual monitoring
4. **Set up alerts**: Configure notifications for failed runs

### Performance Optimization

1. **Limit concurrency**: Use work pool limits to control resource usage
2. **Optimize schedules**: Stagger similar flows to avoid resource contention
3. **Monitor duration**: Track flow run times to identify bottlenecks
4. **Use backfill wisely**: Limit backfill runs to avoid overwhelming the system

---

## Troubleshooting

### Common Issues

**Flow not found:**
```bash
# Check flow exists
mahavishnu prefect flow list | grep my-flow

# Verify flow name spelling
mahavishnu prefect flow execute my-flow --help
```

**Deployment fails:**
```bash
# Check work pool exists
# (Use Prefect UI or API to verify)

# Validate flow first
mahavishnu prefect flow validate my_flow.py

# Check Prefect server connection
mahavishnu prefect dashboard
```

**Schedule not triggering:**
```bash
# Check schedule is active
mahavishnu prefect schedule list --flow my-flow

# Verify cron expression
# Use https://crontab.guru/ to validate

# Check deployment has schedule
mahavishnu prefect deployments list --flow my-flow
```

**Run hangs:**
```bash
# Check run status
mahavishnu prefect flow-runs get run-id

# Use timeout
mahavishnu prefect flow execute my-flow --timeout 600

# Force cancel via Prefect UI if needed
```

### Debug Mode

Enable debug logging:

```bash
# Set environment variable
export PREFECT_LOG_LEVEL=DEBUG

# Or via settings
# settings/mahavishnu.yaml
prefect:
  log_level: "DEBUG"
```

### Getting Help

```bash
# General help
mahavishnu prefect --help

# Command-specific help
mahavishnu prefect flow --help
mahavishnu prefect deploy --help

# Subcommand help
mahavishnu prefect flow create --help
mahavishnu prefect schedule create --help
```

---

## API Reference

### Exit Codes

- `0`: Success
- `1`: Error or validation failure

### Output Formats

**Table format**: Human-readable tables with Rich console formatting
**JSON format**: Machine-readable JSON for scripting and automation

### Color Output

The CLI uses color coding:
- Green: Success, completed, active
- Red: Failed, error, inactive
- Yellow: Running, pending, warning
- Blue: Informational
- Cyan: Identifiers, names
- Magenta: Metadata

---

## See Also

- [Prefect Documentation](https://docs.prefect.io/)
- [Mahavishnu Configuration](../settings/mahavishnu.yaml)
- [Prefect Adapter](../mahavishnu/engines/prefect_adapter.py)
- [Integration Tests](../../tests/integration/test_prefect_cli.py)
