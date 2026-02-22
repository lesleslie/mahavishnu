# Goal-Driven Teams Operations Runbook

**Version:** 1.0
**Last Updated:** 2026-02-21
**Owner:** Mahavishnu Platform Team
**Severity:** P2 (High Priority)

---

## Table of Contents

1. [Overview](#1-overview)
2. [Monitoring & Observability](#2-monitoring--observability)
3. [Common Operations](#3-common-operations)
4. [Troubleshooting](#4-troubleshooting)
5. [Incident Response](#5-incident-response)
6. [Configuration Reference](#6-configuration-reference)
7. [Health Checks](#7-health-checks)
8. [Appendices](#8-appendices)

---

## 1. Overview

### 1.1 What are Goal-Driven Teams

Goal-Driven Teams is a Mahavishnu feature that converts natural language goals into fully-configured multi-agent teams. Instead of manually defining agents, roles, and collaboration modes, users describe what they want to accomplish, and Mahavishnu automatically generates the optimal team configuration.

**Key Capabilities:**
- Natural language goal parsing
- Automatic skill detection from goal content
- Intelligent collaboration mode selection
- Zero configuration team creation
- LLM fallback for complex goals

**Components:**
| Component | Description | Port |
|-----------|-------------|------|
| GoalDrivenTeamFactory | Parses goals and creates team configs | N/A (internal) |
| Goal Team MCP Tools | 3 tools for goal parsing and team creation | 8680 |
| Goal Team CLI | Command-line interface for team management | N/A |
| Prometheus Metrics | Team creation and execution metrics | 9092 |
| WebSocket Server | Real-time team event broadcasts | 8690 |

### 1.2 Architecture Diagram

```
                                    Goal-Driven Teams Architecture
                                    ================================

  +------------------+          +------------------------------------------+
  |   User Input     |          |         GoalDrivenTeamFactory            |
  |  (Natural Lang)  |--------->|  +------------------------------------+  |
  +------------------+          |  |     Phase 1: Pattern Matching     |  |
                                |  |  - Intent Detection (regex)       |  |
                                |  |  - Skill Extraction (keywords)    |  |
                                |  |  - Domain Classification          |  |
                                |  |  - Confidence Calculation         |  |
                                |  +------------------+---------------+  |
                                |                     |                  |
                                |          Confidence >= 0.7?            |
                                |                     |                  |
                                |         +----------+-----------+        |
                                |         | Yes                  | No     |
                                |         v                      v        |
                                |  +-------------+      +----------------+ |
                                |  | Return      |      | Phase 2: LLM  | |
                                |  | ParsedGoal  |      | Fallback      | |
                                |  +-------------+      | (if enabled)  | |
                                |                       +-------+--------+ |
                                +-------------------------------+----------+
                                                                |
                                                                v
                                +------------------------------------------+
                                |             TeamConfig                    |
                                |  - name: "security_review_team"          |
                                |  - mode: coordinate/route/broadcast      |
                                |  - leader: coordinator agent             |
                                |  - members: [security, quality, ...]     |
                                +------------------------------------------+
                                                |
                    +---------------------------+---------------------------+
                    |                           |                           |
                    v                           v                           v
          +-----------------+         +-----------------+         +-----------------+
          |  MCP Tools      |         |  CLI Commands   |         |  WebSocket      |
          |  (Port 8680)    |         |  (team *)       |         |  (Port 8690)    |
          |                 |         |                 |         |                 |
          |  team_from_goal |         |  team create    |         |  team_created   |
          |  parse_goal     |         |  team parse     |         |  team_execution |
          |  list_team_skills|        |  team skills    |         |  team_error     |
          +-----------------+         +-----------------+         +-----------------+
                    |                           |                           |
                    +---------------------------+---------------------------+
                                                |
                                                v
                                +------------------------------------------+
                                |           Prometheus Metrics              |
                                |              (Port 9092)                  |
                                |                                           |
                                |  - teams_created_total                   |
                                |  - goals_parsed_total                    |
                                |  - skill_usage_total                     |
                                |  - team_errors_total                     |
                                |  - team_creation_duration_seconds        |
                                +------------------------------------------+
```

### 1.3 Key Components and Ports

| Service | Port | Protocol | Purpose |
|---------|------|----------|---------|
| Mahavishnu MCP Server | 8680 | HTTP/SSE | MCP tools for goal teams |
| Prometheus Metrics | 9092 | HTTP | Goal team metrics endpoint |
| WebSocket Server | 8690 | WebSocket | Real-time team event broadcasts |
| Grafana Dashboard | 3000 | HTTP | Visualization (import dashboard) |

---

## 2. Monitoring & Observability

### 2.1 Prometheus Metrics (Port 9092)

The Goal Team Metrics server runs on port **9092** (distinct from routing metrics on 9091).

#### Counter Metrics

| Metric Name | Type | Labels | What It Measures | Alert Threshold |
|-------------|------|--------|------------------|-----------------|
| `mahavishnu_goal_teams_created_total` | Counter | server, mode, skill_count | Total teams created | > 100/min = spike |
| `mahavishnu_goal_teams_parsed_total` | Counter | server, intent, domain, method | Goals parsed by type | N/A (info) |
| `mahavishnu_goal_teams_skill_usage_total` | Counter | server, skill_name | Skill usage frequency | N/A (info) |
| `mahavishnu_goal_teams_errors_total` | Counter | server, error_code | Errors by type | > 10/min = warning |

#### Gauge Metrics

| Metric Name | Type | Labels | What It Measures | Alert Threshold |
|-------------|------|--------|------------------|-----------------|
| `mahavishnu_goal_teams_active` | Gauge | server | Current active teams | > 50 = capacity warning |

#### Histogram Metrics

| Metric Name | Type | Labels | Buckets | What It Measures | Alert Threshold |
|-------------|------|--------|---------|------------------|-----------------|
| `mahavishnu_goal_team_creation_duration_seconds` | Histogram | server, mode | 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0 | Team creation latency | p99 > 5s = warning |
| `mahavishnu_goal_teams_parsing_confidence` | Histogram | server, method | 0.1-1.0 | Parsing confidence scores | median < 0.7 = investigate |

#### Info Metrics

| Metric Name | Type | Labels | What It Measures |
|-------------|------|--------|------------------|
| `mahavishnu_goal_team` | Info | server, team_id, mode | Team metadata (intent, domain, skills) |

#### Accessing Metrics

```bash
# Direct Prometheus endpoint
curl http://localhost:9092/metrics | grep mahavishnu_goal

# Filter by metric type
curl http://localhost:9092/metrics | grep -E "teams_created|teams_parsed|errors_total"
```

### 2.2 WebSocket Events

WebSocket server runs on port **8690**. Subscribe to team events for real-time monitoring.

#### Event Types and Payloads

**Team Parsed Event** (`team_parsed`)
```json
{
  "event": "team_parsed",
  "goal": "Review code for security vulnerabilities",
  "intent": "review",
  "skills": ["security", "quality"],
  "confidence": 0.85,
  "user_id": "user_123",
  "timestamp": "2026-02-21T10:30:00Z"
}
```

**Team Created Event** (`team_created`)
```json
{
  "event": "team_created",
  "team_id": "team_abc123",
  "team_name": "security_review_team",
  "goal": "Review code for security vulnerabilities",
  "mode": "coordinate",
  "user_id": "user_123",
  "timestamp": "2026-02-21T10:30:05Z"
}
```

**Team Execution Started** (`team_execution_started`)
```json
{
  "event": "team_execution_started",
  "team_id": "team_abc123",
  "task": "Analyze the authentication module",
  "user_id": "user_123",
  "timestamp": "2026-02-21T10:30:10Z"
}
```

**Team Execution Completed** (`team_execution_completed`)
```json
{
  "event": "team_execution_completed",
  "team_id": "team_abc123",
  "success": true,
  "duration_ms": 5678.9,
  "user_id": "user_123",
  "timestamp": "2026-02-21T10:31:00Z"
}
```

**Team Error Event** (`team_error`)
```json
{
  "event": "team_error",
  "team_id": "team_abc123",
  "error_code": "MHV-465",
  "message": "Goal parsing failed: insufficient context",
  "user_id": "user_123",
  "timestamp": "2026-02-21T10:30:02Z"
}
```

#### Subscribing to WebSocket Channels

```python
# Python example using websockets library
import asyncio
import json
import websockets

async def monitor_team_events():
    uri = "ws://localhost:8690"
    async with websockets.connect(uri) as ws:
        # Subscribe to all team events
        await ws.send(json.dumps({
            "action": "subscribe",
            "channel": "team_events"
        }))

        async for message in ws:
            event = json.loads(message)
            print(f"Event: {event['event']}")
            print(f"Data: {json.dumps(event, indent=2)}")

asyncio.run(monitor_team_events())
```

```bash
# CLI tools
wscat -c ws://localhost:8690
# Send: {"action": "subscribe", "channel": "team_events"}
```

#### Debug WebSocket Connections

```bash
# Check WebSocket server is running
netstat -an | grep 8690

# Test connection with curl (upgrade to WebSocket)
curl -i -N -H "Connection: Upgrade" -H "Upgrade: websocket" \
  -H "Sec-WebSocket-Key: test" -H "Sec-WebSocket-Version: 13" \
  http://localhost:8690

# Monitor with wscat
npm install -g wscat
wscat -c ws://localhost:8690 -x '{"action":"subscribe","channel":"team_events"}'
```

### 2.3 Grafana Dashboard

#### Dashboard Panels

1. **Teams Created Over Time** - Time series of team creation rate
2. **Team Creation by Mode** - Pie chart (coordinate, route, broadcast, collaborate)
3. **Goal Parsing Confidence** - Histogram with p50, p90, p99
4. **Skill Usage Distribution** - Bar chart of skill popularity
5. **Error Rate by Code** - Time series of errors by MHV-XXX code
6. **Active Teams Gauge** - Current active team count
7. **Team Creation Latency** - Duration histogram
8. **Parsing Method Distribution** - Pattern vs LLM fallback
9. **Intent Distribution** - Goals by intent type
10. **Domain Distribution** - Goals by domain

#### Key Visualizations to Set Up

**PromQL Queries for Custom Panels:**

```promql
# Teams created per minute
rate(mahavishnu_goal_teams_created_total[1m]) * 60

# Error rate
rate(mahavishnu_goal_teams_errors_total[5m])

# P99 team creation latency
histogram_quantile(0.99,
  rate(mahavishnu_goal_team_creation_duration_seconds_bucket[5m])
)

# Low confidence parsing rate (< 0.7)
sum(rate(mahavishnu_goal_teams_parsing_confidence_bucket{le="0.7"}[5m]))
/ sum(rate(mahavishnu_goal_teams_parsing_confidence_count[5m]))

# Most used skills
topk(5, sum by (skill_name) (
  mahavishnu_goal_teams_skill_usage_total
))
```

---

## 3. Common Operations

### 3.1 Enable/Disable Feature Flags

#### Check Current Flags

```bash
# View all feature flags
mahavishnu team flags

# Output:
# +--------------------------------+----------+----------------------------------------+
# | Flag                           | Status   | Description                            |
# +--------------------------------+----------+----------------------------------------+
# | enabled                        | enabled  | Master switch for Goal-Driven Teams    |
# | mcp_tools_enabled              | enabled  | Enable MCP tools for team creation     |
# | cli_commands_enabled           | enabled  | Enable CLI commands                    |
# | llm_fallback_enabled           | enabled  | Enable LLM fallback for goal parsing   |
# | websocket_broadcasts_enabled   | enabled  | Enable WebSocket broadcasts            |
# | prometheus_metrics_enabled     | enabled  | Enable Prometheus metrics              |
# | learning_system_enabled        | disabled | Enable learning system (Phase 3)       |
# | auto_mode_selection_enabled    | enabled  | Enable automatic mode selection        |
# | custom_skills_enabled          | disabled | Enable custom skills                   |
# +--------------------------------+----------+----------------------------------------+
```

#### Enable/Disable via Config File

Edit `settings/mahavishnu.yaml`:

```yaml
goal_teams:
  enabled: true  # Master switch
  feature_flags:
    mcp_tools_enabled: true
    cli_commands_enabled: true
    llm_fallback_enabled: true
    websocket_broadcasts_enabled: true
    prometheus_metrics_enabled: true
    learning_system_enabled: false  # Phase 3 feature
    auto_mode_selection_enabled: true
    custom_skills_enabled: false
```

#### Enable via Environment Variables

```bash
# Master switch
export MAHAVISHNU_GOAL_TEAMS__ENABLED=true

# Individual flags (note double underscore)
export MAHAVISHNU_GOAL_TEAMS__FEATURE_FLAGS__MCP_TOOLS_ENABLED=true
export MAHAVISHNU_GOAL_TEAMS__FEATURE_FLAGS__LLM_FALLBACK_ENABLED=true
export MAHAVISHNU_GOAL_TEAMS__FEATURE_FLAGS__PROMETHEUS_METRICS_ENABLED=true
```

### 3.2 Create a Team

#### Dry Run (Preview Configuration)

```bash
# Preview what team would be created
mahavishnu team create --goal "Review code for security vulnerabilities" --dry-run

# Output shows YAML configuration and member details without creating
```

#### Create Team

```bash
# Basic creation
mahavishnu team create --goal "Review code for security vulnerabilities"

# With custom name and mode
mahavishnu team create -g "Analyze performance" -n perf_team --mode coordinate

# Create and run immediately
mahavishnu team create -g "Debug this issue" --run --task "Fix the login bug"

# Verbose output
mahavishnu team create -g "Write tests" --verbose
```

#### MCP Tool (Programmatic)

```python
# Via MCP tool
result = await mcp.call_tool("team_from_goal", {
    "goal": "Review code for security vulnerabilities",
    "name": "security_review",
    "mode": "coordinate",
    "auto_run": False
})

print(f"Team ID: {result['team_id']}")
print(f"Members: {[m['name'] for m in result['config']['members']]}")
```

### 3.3 Parse a Goal (Debug)

```bash
# Basic parse
mahavishnu team parse "Review code for security issues"

# Verbose - shows what team would be created
mahavishnu team parse "Build a REST API with authentication" --verbose

# Output:
# +------------------+------------------------------------------+
# | Intent           | review                                   |
# | Domain           | security                                 |
# | Skills           | security, quality                        |
# | Confidence       | 85%                                      |
# | Method           | pattern                                  |
# +------------------+------------------------------------------+
```

### 3.4 List Available Skills

```bash
# Basic list
mahavishnu team skills

# Verbose - full skill details including instructions
mahavishnu team skills --verbose

# Output:
# +-------------+----------------------------------------+--------+-------------------------+
# | Skill       | Role                                   | Model  | Tools                   |
# +-------------+----------------------------------------+--------+-------------------------+
# | security    | Security vulnerability specialist      | sonnet | search_code, read_file  |
# | quality     | Code quality engineer                  | sonnet | search_code, run_linter |
# | performance | Performance optimization specialist    | sonnet | search_code, profile    |
# | testing     | Test engineer                          | sonnet | search_code, run_tests  |
# | debugging   | Debugging specialist                   | sonnet | search_code, debugger   |
# | documentation| Technical writer                      | sonnet | search_code, write_file |
# | refactoring | Refactoring specialist                 | sonnet | search_code, write_file |
# +-------------+----------------------------------------+--------+-------------------------+
```

### 3.5 List Active Teams

```bash
# List teams in current session
mahavishnu team list

# Verbose - full team details
mahavishnu team list --verbose
```

---

## 4. Troubleshooting

### 4.1 Error Codes Reference

| Code | Name | Cause | Resolution |
|------|------|-------|------------|
| **MHV-460** | GOAL_TEAM_CREATION_FAILED | Team configuration could not be created | Check goal is well-formed; verify skill names in config |
| **MHV-461** | GOAL_TEAM_NOT_FOUND | Referenced team ID does not exist | Verify team ID; check if team expired (TTL) |
| **MHV-462** | GOAL_TEAM_EXECUTION_ERROR | Team execution failed during run | Check agent logs; verify LLM provider is accessible |
| **MHV-463** | GOAL_TEAM_TIMEOUT | Team execution exceeded time limit | Increase timeout in config; simplify the goal |
| **MHV-464** | GOAL_TEAM_LIMIT_EXCEEDED | Maximum teams per user reached | Delete unused teams; wait for TTL expiration |
| **MHV-465** | GOAL_PARSING_FAILED | Goal could not be parsed meaningfully | Use more specific language; add domain keywords |
| **MHV-466** | GOAL_TOO_SHORT | Goal is below minimum length | Provide at least 10 characters of context |
| **MHV-467** | GOAL_TOO_LONG | Goal exceeds maximum length | Limit goal to 2000 characters |
| **MHV-468** | FEATURE_DISABLED | Feature flag is not enabled | Enable the feature in configuration |

### 4.2 Common Issues

#### "Goal parsing failed" (MHV-465)

**Symptoms:**
- Error message: "Goal parsing failed: insufficient context"
- Confidence score below 0.3
- Team created with wrong skills

**Root Causes:**
1. Goal is too vague ("Make this better")
2. No recognizable intent keywords
3. Domain keywords not matched
4. LLM fallback not available or disabled

**Resolution:**
```bash
# Step 1: Test goal parsing
mahavishnu team parse "your goal here" --verbose

# Step 2: Check if LLM fallback is enabled
mahavishnu team flags | grep llm_fallback

# Step 3: If disabled and needed, enable it
# Edit settings/mahavishnu.yaml:
# goal_teams:
#   feature_flags:
#     llm_fallback_enabled: true

# Step 4: Rewrite goal with specific keywords
# Bad: "Fix issues"
# Good: "Fix the authentication timeout error in the login module"
```

**Good Goal Examples:**
```bash
# Specific and actionable
"Review the authentication module for SQL injection vulnerabilities"
"Optimize database query performance in the user service"
"Write unit tests for the payment processing module"
"Document the REST API endpoints in the docs folder"
```

#### "Feature disabled" (MHV-468)

**Symptoms:**
- Error message: "Feature 'X' is disabled"
- MCP tools return error with code MHV-468
- CLI commands exit with code 1

**Root Causes:**
1. Master switch `goal_teams.enabled` is false
2. Specific feature flag is disabled
3. Config not loaded correctly

**Resolution:**
```bash
# Step 1: Check all feature flags
mahavishnu team flags

# Step 2: Check master switch
grep -A5 "goal_teams:" settings/mahavishnu.yaml

# Step 3: Enable master switch
# settings/mahavishnu.yaml:
# goal_teams:
#   enabled: true

# Step 4: Or enable via environment
export MAHAVISHNU_GOAL_TEAMS__ENABLED=true

# Step 5: Restart Mahavishnu if needed
mahavishnu mcp restart
```

#### "Context not initialized" (MHV-011)

**Symptoms:**
- Error message: "Application context not initialized"
- LLM fallback fails even when enabled
- Tools fail to access Agno adapter

**Root Causes:**
1. MahavishnuApp not created before tool call
2. `set_app_context()` not called during init
3. Context variable cleared unexpectedly

**Resolution:**
```bash
# Step 1: Verify Mahavishnu MCP server is running
mahavishnu mcp status

# Step 2: Check server health
mahavishnu mcp health

# Step 3: Restart MCP server
mahavishnu mcp stop
mahavishnu mcp start

# Step 4: Verify Agno adapter is enabled
grep -A5 "agno:" settings/mahavishnu.yaml
# Should show: enabled: true

# Step 5: Check logs for initialization errors
tail -f logs/mahavishnu.log | grep -i "context\|adapter\|init"
```

#### Low Confidence Parsing

**Symptoms:**
- Confidence score < 0.7
- LLM fallback triggered frequently
- Wrong skills selected for team

**When It Happens:**
- Ambiguous goals with no clear intent
- Goals with mixed domains
- New domain keywords not in patterns
- Very long or complex goals

**How LLM Fallback Works:**
1. Pattern matching attempts first (fast, free)
2. If confidence < 0.7 and LLM fallback enabled
3. Goal sent to configured LLM (Ollama/OpenAI/Anthropic)
4. LLM extracts intent, domain, skills
5. LLM result used if higher confidence

**When to Investigate:**
- Confidence median drops below 0.7 (check Grafana)
- LLM fallback rate exceeds 30% of goals
- User complaints about wrong team composition

**Resolution:**
```bash
# Step 1: Check parsing confidence metrics
curl -s http://localhost:9092/metrics | grep parsing_confidence

# Step 2: Test specific goal
mahavishnu team parse "your problematic goal" --verbose

# Step 3: Review parsing method distribution in Grafana
# Panel: "Parsing Method Distribution"

# Step 4: If LLM fallback not working, check LLM config
grep -A10 "agno:" settings/mahavishnu.yaml | grep -A5 "llm:"

# Step 5: Verify LLM provider is accessible
curl http://localhost:11434/api/tags  # For Ollama
```

### 4.3 Debugging Steps

#### Step 1: Check Feature Flags

```bash
mahavishnu team flags
# Verify all needed flags are enabled
```

#### Step 2: Verify Context Initialization

```bash
mahavishnu mcp status
mahavishnu mcp health
# Should show "healthy" and "initialized"
```

#### Step 3: Check Metrics for Anomalies

```bash
# Error rate
curl -s http://localhost:9092/metrics | grep "errors_total" | grep -v "#"

# Active teams (should be reasonable)
curl -s http://localhost:9092/metrics | grep "goal_teams_active"

# Team creation latency
curl -s http://localhost:9092/metrics | grep "creation_duration"
```

#### Step 4: Review WebSocket Events

```bash
# Connect and subscribe
wscat -c ws://localhost:8690
> {"action": "subscribe", "channel": "team_events"}

# Look for error events in real-time
```

#### Step 5: Check Logs

```bash
# Application logs
tail -f logs/mahavishnu.log | grep -i "goal\|team\|parse"

# Error logs specifically
tail -f logs/mahavishnu.log | grep -i "error\|exception\|failed"

# Verbose logging
MAHAVISHNU_LOG_LEVEL=DEBUG mahavishnu mcp start
```

---

## 5. Incident Response

### 5.1 Team Creation Failures

**Severity:** P2
**Detection:** Error rate spike on `mahavishnu_goal_teams_errors_total{error_code="MHV-460"}`

**Runbook Steps:**

1. **Assess Impact**
   ```bash
   # Check error rate
   curl -s http://localhost:9092/metrics | grep "errors_total.*MHV-460"

   # Check recent errors in logs
   grep "MHV-460" logs/mahavishnu.log | tail -20
   ```

2. **Identify Root Cause**
   ```bash
   # Check feature flags
   mahavishnu team flags

   # Check Agno adapter status
   mahavishnu mcp health

   # Test simple goal parsing
   mahavishnu team parse "Review code for bugs"
   ```

3. **Common Fixes**
   - If feature disabled: Enable `goal_teams.enabled`
   - If context not initialized: Restart MCP server
   - If Agno adapter down: Check Agno configuration

4. **Verify Resolution**
   ```bash
   # Test team creation
   mahavishnu team create -g "Test goal" --dry-run

   # Monitor error rate
   watch 'curl -s http://localhost:9092/metrics | grep errors_total'
   ```

5. **Escalation Path**
   - If unresolved in 15 min: Escalate to Platform Team
   - If Agno-related: Include Agno adapter logs
   - Provide: Error rate, sample goals failing, config dump

### 5.2 High Error Rate

**Severity:** P2
**Detection:** `rate(mahavishnu_goal_teams_errors_total[5m]) > 10`

**Investigation Steps:**

1. **Identify Error Type**
   ```bash
   # Breakdown by error code
   curl -s http://localhost:9092/metrics | grep "errors_total" | grep -v "#"

   # Most common error
   # Group by error_code in Grafana
   ```

2. **Check Dependencies**
   ```bash
   # LLM provider (Ollama)
   curl http://localhost:11434/api/tags

   # Agno adapter
   grep "agno" logs/mahavishnu.log | tail -20

   # Database (if using persistent storage)
   grep -i "database\|sqlite\|postgres" logs/mahavishnu.log
   ```

3. **Check Resource Constraints**
   ```bash
   # Memory usage
   ps aux | grep mahavishnu

   # CPU usage
   top -p $(pgrep -f mahavishnu)

   # Disk space (for SQLite)
   df -h data/
   ```

4. **Mitigation**
   - If LLM down: Switch to pattern-only parsing (disable LLM fallback)
   - If resource exhaustion: Scale horizontally or reduce limits
   - If config error: Revert to last known good config

### 5.3 Performance Issues

**Severity:** P3
**Detection:** `histogram_quantile(0.99, rate(mahavishnu_goal_team_creation_duration_seconds_bucket[5m])) > 5`

**Metrics to Check:**

```promql
# P99 latency
histogram_quantile(0.99, rate(mahavishnu_goal_team_creation_duration_seconds_bucket[5m]))

# P50 latency
histogram_quantile(0.50, rate(mahavishnu_goal_team_creation_duration_seconds_bucket[5m]))

# Throughput
rate(mahavishnu_goal_teams_created_total[1m])
```

**Common Bottlenecks:**

1. **LLM Fallback Latency**
   - LLM calls add 1-5 seconds
   - Mitigation: Increase pattern matching coverage

2. **Agno Adapter Initialization**
   - First team creation slower due to lazy init
   - Mitigation: Warmup during startup

3. **WebSocket Broadcast Overhead**
   - Many clients = slower broadcasts
   - Mitigation: Batch events or disable broadcasts

**Mitigation Steps:**

```bash
# Step 1: Check if LLM fallback is the cause
# Compare pattern vs LLM parsing times in Grafana

# Step 2: Temporarily disable LLM fallback for faster creation
# settings/mahavishnu.yaml:
# goal_teams:
#   feature_flags:
#     llm_fallback_enabled: false

# Step 3: Disable WebSocket broadcasts if not needed
# goal_teams:
#   feature_flags:
#     websocket_broadcasts_enabled: false

# Step 4: Reduce concurrent execution limit if overloaded
# goal_teams:
#   limits:
#     max_concurrent_executions: 3
```

---

## 6. Configuration Reference

### 6.1 settings/mahavishnu.yaml

```yaml
# Goal-Driven Teams Configuration
# =================================

goal_teams:
  # Master switch - must be true for any goal teams functionality
  enabled: true

  # Goal parsing settings
  goal_parsing:
    # Minimum goal length in characters (default: 10)
    min_length: 10

    # Maximum goal length in characters (default: 2000)
    max_length: 2000

    # Fallback strategy when parsing fails:
    # - simple: Use basic keyword extraction
    # - reject: Return error to user
    # - default_team: Use a default team configuration
    fallback_strategy: simple

  # Limits and quotas
  limits:
    # Maximum active teams per user (default: 10)
    max_teams_per_user: 10

    # Team time-to-live in hours, 0 for no expiry (default: 24, max: 168)
    team_ttl_hours: 24

    # Maximum concurrent team executions (default: 5, max: 50)
    max_concurrent_executions: 5

  # Feature flags for granular control
  feature_flags:
    # Enable MCP tools (team_from_goal, parse_goal, list_team_skills)
    mcp_tools_enabled: true

    # Enable CLI commands (mahavishnu team *)
    cli_commands_enabled: true

    # Enable LLM fallback when pattern matching confidence < 0.7
    llm_fallback_enabled: true

    # Enable WebSocket broadcasts for team events
    websocket_broadcasts_enabled: true

    # Enable Prometheus metrics on port 9092
    prometheus_metrics_enabled: true

    # Enable learning system (Phase 3 - experimental)
    learning_system_enabled: false

    # Enable automatic mode selection based on goal analysis
    auto_mode_selection_enabled: true

    # Enable custom skills (requires skill configuration)
    custom_skills_enabled: false

# Agno adapter configuration (required for team execution)
agno:
  enabled: true
  llm:
    provider: ollama
    model_id: qwen2.5:7b
    base_url: http://localhost:11434
    temperature: 0.7
  memory:
    enabled: true
    backend: sqlite
    db_path: data/agno.db
  tools:
    mcp_server_url: http://localhost:8680/mcp
```

### 6.2 Feature Flags

| Flag | Description | Default | Environment Variable |
|------|-------------|---------|---------------------|
| `enabled` | Master switch for Goal-Driven Teams | `false` | `MAHAVISHNU_GOAL_TEAMS__ENABLED` |
| `mcp_tools_enabled` | Enable MCP tools | `true` | `MAHAVISHNU_GOAL_TEAMS__FEATURE_FLAGS__MCP_TOOLS_ENABLED` |
| `cli_commands_enabled` | Enable CLI commands | `true` | `MAHAVISHNU_GOAL_TEAMS__FEATURE_FLAGS__CLI_COMMANDS_ENABLED` |
| `llm_fallback_enabled` | Enable LLM fallback for parsing | `true` | `MAHAVISHNU_GOAL_TEAMS__FEATURE_FLAGS__LLM_FALLBACK_ENABLED` |
| `websocket_broadcasts_enabled` | Enable WebSocket broadcasts | `true` | `MAHAVISHNU_GOAL_TEAMS__FEATURE_FLAGS__WEBSOCKET_BROADCASTS_ENABLED` |
| `prometheus_metrics_enabled` | Enable Prometheus metrics | `true` | `MAHAVISHNU_GOAL_TEAMS__FEATURE_FLAGS__PROMETHEUS_METRICS_ENABLED` |
| `learning_system_enabled` | Enable learning system (Phase 3) | `false` | `MAHAVISHNU_GOAL_TEAMS__FEATURE_FLAGS__LEARNING_SYSTEM_ENABLED` |
| `auto_mode_selection_enabled` | Enable automatic mode selection | `true` | `MAHAVISHNU_GOAL_TEAMS__FEATURE_FLAGS__AUTO_MODE_SELECTION_ENABLED` |
| `custom_skills_enabled` | Enable custom skills | `false` | `MAHAVISHNU_GOAL_TEAMS__FEATURE_FLAGS__CUSTOM_SKILLS_ENABLED` |

### 6.3 Environment Variables

All Goal Teams environment variables use the `MAHAVISHNU_GOAL_TEAMS__` prefix with double underscore separators:

```bash
# Master switch
export MAHAVISHNU_GOAL_TEAMS__ENABLED=true

# Goal parsing
export MAHAVISHNU_GOAL_TEAMS__GOAL_PARSING__MIN_LENGTH=20
export MAHAVISHNU_GOAL_TEAMS__GOAL_PARSING__MAX_LENGTH=5000
export MAHAVISHNU_GOAL_TEAMS__GOAL_PARSING__FALLBACK_STRATEGY=simple

# Limits
export MAHAVISHNU_GOAL_TEAMS__LIMITS__MAX_TEAMS_PER_USER=20
export MAHAVISHNU_GOAL_TEAMS__LIMITS__TEAM_TTL_HOURS=48
export MAHAVISHNU_GOAL_TEAMS__LIMITS__MAX_CONCURRENT_EXECUTIONS=10

# Feature flags
export MAHAVISHNU_GOAL_TEAMS__FEATURE_FLAGS__MCP_TOOLS_ENABLED=true
export MAHAVISHNU_GOAL_TEAMS__FEATURE_FLAGS__CLI_COMMANDS_ENABLED=true
export MAHAVISHNU_GOAL_TEAMS__FEATURE_FLAGS__LLM_FALLBACK_ENABLED=true
export MAHAVISHNU_GOAL_TEAMS__FEATURE_FLAGS__WEBSOCKET_BROADCASTS_ENABLED=true
export MAHAVISHNU_GOAL_TEAMS__FEATURE_FLAGS__PROMETHEUS_METRICS_ENABLED=true
```

---

## 7. Health Checks

### 7.1 Manual Health Check

Run these CLI commands to verify system health:

```bash
#!/bin/bash
# Goal-Driven Teams Health Check Script

echo "=== Goal-Driven Teams Health Check ==="
echo ""

# 1. Check feature flags
echo "1. Feature Flags:"
mahavishnu team flags 2>&1 | head -15
echo ""

# 2. Check MCP server status
echo "2. MCP Server Status:"
mahavishnu mcp status 2>&1
echo ""

# 3. Check Prometheus metrics endpoint
echo "3. Prometheus Metrics (Port 9092):"
curl -s http://localhost:9092/metrics | grep -c "mahavishnu_goal" && echo "Metrics OK" || echo "Metrics FAILED"
echo ""

# 4. Check WebSocket server
echo "4. WebSocket Server (Port 8690):"
nc -z localhost 8690 && echo "WebSocket port open" || echo "WebSocket port CLOSED"
echo ""

# 5. Test goal parsing
echo "5. Test Goal Parsing:"
mahavishnu team parse "Review code for security issues" 2>&1 | head -10
echo ""

# 6. Test skill listing
echo "6. Available Skills:"
mahavishnu team skills 2>&1 | head -15
echo ""

# 7. Check error rate
echo "7. Recent Error Rate:"
curl -s http://localhost:9092/metrics | grep "goal_teams_errors_total" | grep -v "#"
echo ""

echo "=== Health Check Complete ==="
```

### 7.2 Automated Health Check

For monitoring systems (Prometheus, Nagios, etc.):

```yaml
# Prometheus alerting rules
groups:
  - name: goal_teams.rules
    rules:
      - alert: GoalTeamsHighErrorRate
        expr: rate(mahavishnu_goal_teams_errors_total[5m]) > 10
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "High error rate in Goal-Driven Teams"
          description: "{{ $labels.error_code }}: {{ $value }} errors/min"

      - alert: GoalTeamsDisabled
        expr: mahavishnu_goal_teams_active == 0 and on() mahavishnu_goal_teams_parsed_total offset 5m > 0
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Goal-Driven Teams appears disabled"
          description: "No active teams but recent parsing activity detected"

      - alert: GoalTeamsSlowCreation
        expr: histogram_quantile(0.99, rate(mahavishnu_goal_team_creation_duration_seconds_bucket[5m])) > 5
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Slow team creation latency"
          description: "P99 latency is {{ $value }}s"

      - alert: GoalTeamsLowConfidence
        expr: |
          sum(rate(mahavishnu_goal_teams_parsing_confidence_bucket{le="0.7"}[10m]))
          / sum(rate(mahavishnu_goal_teams_parsing_confidence_count[10m])) > 0.3
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Low confidence parsing rate high"
          description: "{{ $value | humanizePercentage }} of goals have confidence < 0.7"
```

---

## 8. Appendices

### Appendix A: Metric Definitions

Complete Prometheus metric documentation:

```
# TYPE mahavishnu_goal_teams_created_total counter
# HELP mahavishnu_goal_teams_created_total Total goal-driven teams created
mahavishnu_goal_teams_created_total{server="mahavishnu",mode="coordinate",skill_count="3"} 42

# TYPE mahavishnu_goal_teams_parsed_total counter
# HELP mahavishnu_goal_teams_parsed_total Total goals parsed by intent, domain, and method
mahavishnu_goal_teams_parsed_total{server="mahavishnu",intent="review",domain="security",method="pattern"} 100

# TYPE mahavishnu_goal_teams_skill_usage_total counter
# HELP mahavishnu_goal_teams_skill_usage_total Total skill usage in goal-driven teams
mahavishnu_goal_teams_skill_usage_total{server="mahavishnu",skill_name="security"} 45

# TYPE mahavishnu_goal_teams_errors_total counter
# HELP mahavishnu_goal_teams_errors_total Total goal-driven team errors by error code
mahavishnu_goal_teams_errors_total{server="mahavishnu",error_code="MHV-465"} 3

# TYPE mahavishnu_goal_teams_active gauge
# HELP mahavishnu_goal_teams_active Current number of active goal-driven teams
mahavishnu_goal_teams_active{server="mahavishnu"} 5

# TYPE mahavishnu_goal_team_creation_duration_seconds histogram
# HELP mahavishnu_goal_team_creation_duration_seconds Time taken to create goal-driven teams
mahavishnu_goal_team_creation_duration_seconds_bucket{server="mahavishnu",mode="coordinate",le="0.01"} 10
mahavishnu_goal_team_creation_duration_seconds_bucket{server="mahavishnu",mode="coordinate",le="0.025"} 25
mahavishnu_goal_team_creation_duration_seconds_bucket{server="mahavishnu",mode="coordinate",le="0.05"} 40
mahavishnu_goal_team_creation_duration_seconds_bucket{server="mahavishnu",mode="coordinate",le="0.1"} 55
mahavishnu_goal_team_creation_duration_seconds_bucket{server="mahavishnu",mode="coordinate",le="0.25"} 70
mahavishnu_goal_team_creation_duration_seconds_bucket{server="mahavishnu",mode="coordinate",le="0.5"} 80
mahavishnu_goal_team_creation_duration_seconds_bucket{server="mahavishnu",mode="coordinate",le="1.0"} 90
mahavishnu_goal_team_creation_duration_seconds_bucket{server="mahavishnu",mode="coordinate",le="2.5"} 95
mahavishnu_goal_team_creation_duration_seconds_bucket{server="mahavishnu",mode="coordinate",le="5.0"} 98
mahavishnu_goal_team_creation_duration_seconds_bucket{server="mahavishnu",mode="coordinate",le="10.0"} 99
mahavishnu_goal_team_creation_duration_seconds_bucket{server="mahavishnu",mode="coordinate",le="30.0"} 100
mahavishnu_goal_team_creation_duration_seconds_bucket{server="mahavishnu",mode="coordinate",le="+Inf"} 100

# TYPE mahavishnu_goal_teams_parsing_confidence histogram
# HELP mahavishnu_goal_teams_parsing_confidence Distribution of goal parsing confidence scores
mahavishnu_goal_teams_parsing_confidence_bucket{server="mahavishnu",method="pattern",le="0.1"} 2
mahavishnu_goal_teams_parsing_confidence_bucket{server="mahavishnu",method="pattern",le="0.2"} 3
mahavishnu_goal_teams_parsing_confidence_bucket{server="mahavishnu",method="pattern",le="0.3"} 5
mahavishnu_goal_teams_parsing_confidence_bucket{server="mahavishnu",method="pattern",le="0.4"} 8
mahavishnu_goal_teams_parsing_confidence_bucket{server="mahavishnu",method="pattern",le="0.5"} 12
mahavishnu_goal_teams_parsing_confidence_bucket{server="mahavishnu",method="pattern",le="0.6"} 18
mahavishnu_goal_teams_parsing_confidence_bucket{server="mahavishnu",method="pattern",le="0.7"} 25
mahavishnu_goal_teams_parsing_confidence_bucket{server="mahavishnu",method="pattern",le="0.8"} 45
mahavishnu_goal_teams_parsing_confidence_bucket{server="mahavishnu",method="pattern",le="0.9"} 75
mahavishnu_goal_teams_parsing_confidence_bucket{server="mahavishnu",method="pattern",le="0.95"} 85
mahavishnu_goal_teams_parsing_confidence_bucket{server="mahavishnu",method="pattern",le="0.99"} 95
mahavishnu_goal_teams_parsing_confidence_bucket{server="mahavishnu",method="pattern",le="1.0"} 100
mahavishnu_goal_teams_parsing_confidence_bucket{server="mahavishnu",method="pattern",le="+Inf"} 100

# TYPE mahavishnu_goal_team info
# HELP mahavishnu_goal_team Information about a goal-driven team
mahavishnu_goal_team_info{server="mahavishnu",team_id="team_abc123",mode="coordinate",intent="review",domain="security",skill_count="3",confidence="0.85"} 1
```

### Appendix B: WebSocket Event Schemas

JSON schemas for all WebSocket events:

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "definitions": {
    "TeamParsedEvent": {
      "type": "object",
      "required": ["event", "goal", "intent", "skills", "confidence"],
      "properties": {
        "event": { "const": "team_parsed" },
        "goal": { "type": "string", "minLength": 10 },
        "intent": { "type": "string", "enum": ["review", "build", "test", "fix", "refactor", "document", "analyze"] },
        "domain": { "type": "string" },
        "skills": { "type": "array", "items": { "type": "string" } },
        "confidence": { "type": "number", "minimum": 0, "maximum": 1 },
        "user_id": { "type": "string" },
        "timestamp": { "type": "string", "format": "date-time" }
      }
    },
    "TeamCreatedEvent": {
      "type": "object",
      "required": ["event", "team_id", "team_name", "goal", "mode"],
      "properties": {
        "event": { "const": "team_created" },
        "team_id": { "type": "string", "pattern": "^team_[a-z0-9]+" },
        "team_name": { "type": "string" },
        "goal": { "type": "string" },
        "mode": { "type": "string", "enum": ["coordinate", "route", "broadcast", "collaborate"] },
        "user_id": { "type": "string" },
        "timestamp": { "type": "string", "format": "date-time" }
      }
    },
    "TeamExecutionStartedEvent": {
      "type": "object",
      "required": ["event", "team_id", "task"],
      "properties": {
        "event": { "const": "team_execution_started" },
        "team_id": { "type": "string" },
        "task": { "type": "string" },
        "user_id": { "type": "string" },
        "timestamp": { "type": "string", "format": "date-time" }
      }
    },
    "TeamExecutionCompletedEvent": {
      "type": "object",
      "required": ["event", "team_id", "success", "duration_ms"],
      "properties": {
        "event": { "const": "team_execution_completed" },
        "team_id": { "type": "string" },
        "success": { "type": "boolean" },
        "duration_ms": { "type": "number" },
        "user_id": { "type": "string" },
        "timestamp": { "type": "string", "format": "date-time" }
      }
    },
    "TeamErrorEvent": {
      "type": "object",
      "required": ["event", "error_code", "message"],
      "properties": {
        "event": { "const": "team_error" },
        "team_id": { "type": "string" },
        "error_code": { "type": "string", "pattern": "^MHV-[0-9]{3}$" },
        "message": { "type": "string" },
        "user_id": { "type": "string" },
        "timestamp": { "type": "string", "format": "date-time" }
      }
    }
  }
}
```

### Appendix C: Error Code Quick Reference

Printable quick reference card:

```
+================================================================================+
|                    GOAL-DRIVEN TEAMS ERROR CODES                               |
+================================================================================+
| CODE | NAME                      | QUICK FIX                                    |
+=================================================================================
| MHV-460 | GOAL_TEAM_CREATION_FAILED | Check goal format; verify skills exist     |
| MHV-461 | GOAL_TEAM_NOT_FOUND       | Verify team ID; check TTL expiration       |
| MHV-462 | GOAL_TEAM_EXECUTION_ERROR | Check agent logs; verify LLM accessible    |
| MHV-463 | GOAL_TEAM_TIMEOUT         | Increase timeout; simplify goal            |
| MHV-464 | GOAL_TEAM_LIMIT_EXCEEDED  | Delete unused teams; wait for TTL          |
| MHV-465 | GOAL_PARSING_FAILED       | Use specific language; add domain keywords |
| MHV-466 | GOAL_TOO_SHORT            | Provide >= 10 characters                   |
| MHV-467 | GOAL_TOO_LONG             | Limit to <= 2000 characters                |
| MHV-468 | FEATURE_DISABLED          | Enable feature in settings/mahavishnu.yaml |
+================================================================================+
| SYSTEM ERRORS (May also occur)                                                 |
+================================================================================+
| MHV-011 | CONTEXT_NOT_INITIALIZED   | Restart MCP server; check initialization   |
| MHV-007 | INTERNAL_ERROR            | Check logs; restart server                 |
+================================================================================+

QUICK COMMANDS:
  mahavishnu team flags              - Check feature flags
  mahavishnu team parse "goal"       - Debug goal parsing
  mahavishnu team skills             - List available skills
  mahavishnu mcp health              - Check server health
  curl http://localhost:9092/metrics - View Prometheus metrics

CONFIG FILE: settings/mahavishnu.yaml
LOGS: logs/mahavishnu.log
METRICS: http://localhost:9092/metrics
WEBSOCKET: ws://localhost:8690
```

---

## Document History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-02-21 | Platform Team | Initial runbook creation |

---

## Related Documentation

- [Goal-Driven Teams User Guide](/docs/GOAL_DRIVEN_TEAMS.md)
- [Agno Adapter Documentation](/docs/AGNO_ADAPTER.md)
- [MCP Tools Specification](/docs/MCP_TOOLS_SPECIFICATION.md)
- [Architecture Overview](/ARCHITECTURE.md)
- [Security Checklist](/SECURITY_CHECKLIST.md)
