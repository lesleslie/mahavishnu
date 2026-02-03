# Mahavishnu Workflow Diagrams

**Common Workflows and Operational Procedures**

**Last Updated**: 2026-02-03

---

## Table of Contents

1. [Quick Start Workflow](#1-quick-start-workflow)
2. [Pool Spawn and Execute](#2-pool-spawn-and-execute)
3. [Repository Sweep](#3-repository-sweep)
4. [Memory Search](#4-memory-search)
5. [Quality Control Pipeline](#5-quality-control-pipeline)
6. [Error Recovery](#6-error-recovery)
7. [MCP Tool Execution](#7-mcp-tool-execution)

---

## 1. Quick Start Workflow

### First-Time Setup

```mermaid
flowchart TD
    Start([Clone Repository]) --> Install[Install Dependencies<br/>uv venv + pip install]
    Install --> Config[Configure Settings<br/>settings/mahavishnu.yaml]
    Config --> Env[Set Environment Variables<br/>MAHAVISHNU_AUTH_SECRET]
    Env --> Verify[Verify Installation<br/>mahavishnu health-check]
    Verify --> Healthy{Healthy?}
    Healthy -->|No| Troubleshoot[Troubleshoot<br/>Check logs]
    Troubleshoot --> Verify
    Healthy -->|Yes| Launch[Launch MCP Server<br/>mahavishnu mcp start]
    Launch --> Test[Test CLI<br/>mahavishnu list-repos]
    Test --> Success([Ready to Use!])

    style Start fill:#82E0AA,stroke:#27AE60
    style Success fill:#90EE90,stroke:#2E7D32
    style Troubleshoot fill:#FFB347,stroke:#FF8C00
```

### Configuration Priority

```mermaid
graph BT
    EnvVars["Environment Variables<br/>MAHAVISHNU_*<br/>Highest Priority"]
    LocalConfig["settings/local.yaml<br/>Gitignored<br/>Local Overrides"]
    CommittedConfig["settings/mahavishnu.yaml<br/>Committed<br/>Default Config"]
    Defaults["Pydantic Defaults<br/>Code Defaults<br/>Lowest Priority"]

    EnvVars --> LocalConfig
    LocalConfig --> CommittedConfig
    CommittedConfig --> Defaults

    style EnvVars fill:#FF6B6B,stroke:#8B0000
    style LocalConfig fill:#FFB347,stroke:#FF8C00
    style CommittedConfig fill:#87CEEB,stroke:#4682B4
    style Defaults fill:#90EE90,stroke:#2E7D32
```

---

## 2. Pool Spawn and Execute

### Pool Lifecycle

```mermaid
stateDiagram-v2
    [*] --> Configuring: pool spawn command
    Configuring --> Initializing: Settings loaded
    Initializing --> Running: Workers started
    Running --> Scaling: scale command
    Scaling --> Running: New workers ready
    Running --> Executing: Tasks submitted
    Executing --> Running: Task complete
    Running --> Stopping: pool close command
    Stopping --> [*]: Resources released

    note right of Configuring
        Validate configuration
        Check available resources
        Set worker limits
    end note

    note right of Running
        Accept tasks
        Route to workers
        Track performance
    end note
```

### Spawn and Execute Flow

```mermaid
sequenceDiagram
    participant User as User
    participant CLI as CLI
    participant PM as PoolManager
    participant Pool as Pool
    participant Workers as Workers

    User->>CLI: mahavishnu pool spawn --type mahavishnu --name local --min 2 --max 5
    CLI->>PM: spawn_pool("mahavishnu", config)
    PM->>Pool: Initialize with config
    Pool->>Workers: Launch 2 initial workers
    Workers-->>Pool: Workers ready
    Pool-->>PM: Pool created: pool_local_abc123
    PM-->>CLI: pool_id: pool_local_abc123
    CLI-->>User: Pool spawned successfully

    User->>CLI: mahavishnu pool execute pool_local_abc123 --prompt "Write tests"
    CLI->>PM: execute_on_pool("pool_local_abc123", task)
    PM->>Pool: Route task to available worker
    Pool->>Workers: Execute task
    Workers-->>Pool: Result
    Pool-->>PM: Execution result
    PM-->>CLI: Task output
    CLI-->>User: Task complete

    User->>CLI: mahavishnu pool scale pool_local_abc123 --target 10
    CLI->>PM: scale_pool("pool_local_abc123", 10)
    PM->>Pool: Scale to 10 workers
    Pool->>Workers: Launch 8 more workers
    Workers-->>Pool: All workers ready
    Pool-->>PM: Scaling complete
    PM-->>CLI: Pool scaled to 10 workers
    CLI-->>User: Scaling complete
```

### Auto-Routing Decision Tree

```mermaid
flowchart TD
    Start([Task Submitted]) --> Strategy{Routing Strategy?}

    Strategy -->|least_loaded| Load[Check Worker Counts<br/>All Pools]
    Strategy -->|round_robin| RR[Next Pool<br/>Cycle Through]
    Strategy -->|random| Rand[Random Pool<br/>Selection]
    Strategy -->|affinity| Aff[Check Task Tags<br/>Pool Affinity]

    Load --> Select1[Select Pool with<br/>Fewest Workers]
    RR --> Select2[Select Next Pool<br/>In Rotation]
    Rand --> Select3[Select Random Pool<br/>From Available]
    Aff --> Select4[Select Pool with<br/>Matching Tags]

    Select1 --> Available{Pool Available?}
    Select2 --> Available
    Select3 --> Available
    Select4 --> Available

    Available -->|Yes| Execute[Execute Task]
    Available -->|No| Fallback[Use Fallback Pool]

    Execute --> Complete([Task Complete])
    Fallback --> Complete

    style Start fill:#82E0AA,stroke:#27AE60
    style Complete fill:#90EE90,stroke:#2E7D32
    style Fallback fill:#FFB347,stroke:#FF8C00
```

---

## 3. Repository Sweep

### Cross-Repository Workflow Execution

```mermaid
sequenceDiagram
    participant User as User
    participant CLI as CLI
    participant App as MahavishnuApp
    participant Adapter as Adapter
    participant QC as QualityControl
    participant DLQ as DeadLetterQueue

    User->>CLI: mahavishnu sweep --tag python --adapter llamaindex
    CLI->>App: execute_workflow_sweep(task, tag, adapter)

    App->>App: Filter repos by tag: python
    App->>App: Get repos: [repo1, repo2, repo3]

    par Parallel Execution Across Repos
        App->>Adapter: execute(task, repo1)
        Adapter-->>App: result1
    and
        App->>Adapter: execute(task, repo2)
        Adapter-->>App: result2
    and
        App->>Adapter: execute(task, repo3)
        Adapter-->>App: result3
    end

    App->>QC: Run quality checks on all results
    QC-->>App: Quality report

    App->>App: Aggregate results
    alt All Passed
        App-->>CLI: Success: 3/3 repos processed
    else Some Failed
        App->>DLQ: Enqueue failed repos
        App-->>CLI: Partial: 2/3 passed, 1 in DLQ
    end

    CLI-->>User: Sweep complete
```

### Tag-Based Filtering

```mermaid
graph LR
    subgraph "Repository Database"
        AllRepos[All Repositories<br/>9 total]

        subgraph "By Tag"
            Python[python<br/>3 repos]
            Backend[backend<br/>4 repos]
            Frontend[frontend<br/>2 repos]
        end

        subgraph "By Role"
            Orch[orchestrator<br/>1 repo]
            Tool[tool<br/>5 repos]
            App[app<br/>2 repos]
        end
    end

    subgraph "Filter Examples"
        F1[mahavishnu list-repos<br/>--tag python]
        F2[mahavishnu list-repos<br/>--role tool]
        F3[mahavishnu list-repos<br/>--tag backend --role app]
    end

    AllRepos --> Python
    AllRepos --> Backend
    AllRepos --> Frontend
    AllRepos --> Orch
    AllRepos --> Tool
    AllRepos --> App

    F1 -->|Returns| Python
    F2 -->|Returns| Tool
    F3 -->|Returns| Intersection

    style AllRepos fill:#4A90E2,stroke:#1E3A5F,color:#fff
    style Python fill:#90EE90,stroke:#2E7D32
    style Backend fill:#87CEEB,stroke:#4682B4
    style Frontend fill:#DDA0DD,stroke:#9370DB
```

---

## 4. Memory Search

### Cross-Pool Search Flow

```mermaid
sequenceDiagram
    participant User as User
    participant MA as MemoryAggregator
    participant Cache as TTL Cache
    participant SB as Session-Buddy
    participant Pools as Pools

    User->>MA: cross_pool_search("API authentication", limit=50)

    MA->>Cache: Check cache for "API authentication:50"

    alt Cache Hit
        Cache-->>MA: Return cached results
        MA-->>User: 50 results (< 0.1s)
    else Cache Miss
        Cache-->>MA: Not found/expired
        MA->>SB: search_conversations("API authentication", 50)
        SB->>SB: Query all indexed memory
        SB-->>MA: 50 conversations found
        MA->>Cache: Store in cache with timestamp
        MA-->>User: 50 results (1-2s)
    end

    Note over MA,Cache: Cache TTL: 5 minutes<br/>Hit Rate: 60%+
```

### Cache Performance

```mermaid
graph LR
    subgraph "Search Request"
        Req[Search Query]
    end

    subgraph "Cache Layer"
        Check{Check Cache}
        Hit[Cache Hit<br/>&lt; 0.1s<br/>60%]
        Miss[Cache Miss<br/>1-2s<br/>40%]
    end

    subgraph "Storage"
        SB[Session-Buddy<br/>Query All Pools]
    end

    Req --> Check
    Check -->|Key Found & TTL Valid| Hit
    Check -->|Key Not Found or Expired| Miss
    Miss --> SB
    SB --> Update[Update Cache]
    Update --> Return([Return Results])
    Hit --> Return

    style Req fill:#4A90E2,stroke:#1E3A5F,color:#fff
    style Hit fill:#90EE90,stroke:#2E7D32
    style Miss fill:#FFB347,stroke:#FF8C00
    style Return fill:#87CEEB,stroke:#4682B4
```

---

## 5. Quality Control Pipeline

### QC Flow

```mermaid
flowchart TD
    Start([Code Change]) --> Trigger[QC Triggered<br/>Pre-commit/Manual]

    Trigger --> Lint[Ruff Linting<br/>Code Style]
    Lint --> LintPass{Pass?}
    LintPass -->|No| Fix1[Auto-fix or Manual Fix]
    Fix1 --> Lint

    LintPass -->|Yes| Type[Mypy Type Check<br/>Type Safety]
    Type --> TypePass{Pass?}
    TypePass -->|No| Fix2[Fix Type Hints]
    Fix2 --> Type

    TypePass -->|Yes| Security[Bandit Security Scan<br/>Vulnerability Check]
    Security --> SecPass{Pass?}
    SecPass -->|No| Fix3[Fix Security Issues]
    Fix3 --> Security

    SecPass -->|Yes| Tests[pytest Test Suite<br/>Unit + Integration]
    Tests --> TestsPass{Pass?}
    TestsPass -->|No| Fix4[Fix Tests]
    Fix4 --> Tests

    TestsPass -->|Yes| Coverage[Coverage Report<br/>Target: 80%]
    Coverage --> CovPass{>= 80%?}
    CovPass -->|No| Fix5[Add Tests]
    Fix5 --> Coverage

    CovPass -->|Yes| Score[Calculate QC Score<br/>All Checks Weighted]
    Score --> Threshold{Score >= 80?}
    Threshold -->|Yes| Success([QC Passed ✅<br/>Ready to Merge])
    Threshold -->|No| Fail([QC Failed ❌<br/>Fix Required])

    style Start fill:#82E0AA,stroke:#27AE60
    style Success fill:#90EE90,stroke:#2E7D32
    style Fail fill:#FF6B6B,stroke:#8B0000
    style Fix1 fill:#FFB347,stroke:#FF8C00
    style Fix2 fill:#FFB347,stroke:#FF8C00
    style Fix3 fill:#FFB347,stroke:#FF8C00
    style Fix4 fill:#FFB347,stroke:#FF8C00
    style Fix5 fill:#FFB347,stroke:#FF8C00
```

### QC Score Calculation

```mermaid
pie title "Quality Control Score Components (Target: 80+)"
    "Linting (20%)" : 20
    "Type Checking (20%)" : 20
    "Security (20%)" : 20
    "Tests (30%)" : 30
    "Coverage (10%)" : 10
```

---

## 6. Error Recovery

### Circuit Breaker Pattern

```mermaid
stateDiagram-v2
    [*] --> Closed: Initial State
    Closed --> Open: Failures >= Threshold
    Open --> HalfOpen: Timeout Expired
    HalfOpen --> Closed: Success
    HalfOpen --> Open: Failure
    Closed --> Closed: Success (Reset Count)

    note right of Closed
        Requests allowed
        Track failures
        Reset on success
    end note

    note right of Open
        Requests blocked
        Wait for timeout
        Prevent cascading
    end note

    note right of HalfOpen
        Allow one test request
        Verify recovery
        Transition based on result
    end note
```

### Error Handling Flow

```mermaid
flowchart TD
    Start([Execute Operation]) --> Try[Attempt Operation]

    Try --> Result{Result?}
    Result -->|Success| Success([Return Result])
    Result -->|Failure| Error{Error Type?}

    Error -->|Transient| Retry{Retry<br/>Available?}
    Error -->|Permanent| Fail[Permanent Failure]
    Error -->|Validation| ValidationError[Return 400]
    Error -->|Auth| AuthError[Return 401]
    Error -->|Permission| PermError[Return 403]

    Retry -->|Yes| Backoff[Exponential Backoff<br/>Wait: 2^n seconds]
    Backoff --> RetryCount{Retries < Max?}
    RetryCount -->|Yes| Try
    RetryCount -->|No| DLQ[Send to DLQ]

    Fail --> DLQ
    DLQ --> Store[Store with Retry Policy]
    Store --> Notify[Notify Monitoring]

    ValidationError --> End([Return Error])
    AuthError --> End
    PermError --> End
    Notify --> End

    style Start fill:#82E0AA,stroke:#27AE60
    style Success fill:#90EE90,stroke:#2E7D32
    style DLQ fill:#FFA07A,stroke:#CD5C5C
    style End fill:#FF6B6B,stroke:#8B0000
```

---

## 7. MCP Tool Execution

### MCP Tool Call Flow

```mermaid
sequenceDiagram
    participant Claude as Claude Desktop
    participant MCP as MCP Server
    participant Tool as Tool Handler
    participant Validator as Input Validator
    participant Executor as Executor
    participant Logger as Logger

    Claude->>MCP: tools/call

    MCP->>Tool: Route to tool handler

    Tool->>Validator: Validate inputs
    Validator->>Validator: Check Pydantic models
    Validator->>Validator: Check constraints
    Validator-->>Tool: Valid / Invalid

    alt Invalid
        Tool-->>MCP: Validation Error
        MCP-->>Claude: Error response
    else Valid
        Tool->>Executor: Execute with validated inputs
        Executor->>Logger: Log execution start
        Executor->>Executor: Perform operation
        Executor->>Logger: Log execution result
        Executor-->>Tool: Result
        Tool-->>MCP: Success response
        MCP-->>Claude: Result with data
    end
```

### Available MCP Tools

```mermaid
mindmap
    root((MCP Tools<br/>49 Total))
        Repository Management
            list_repos
            show_repo
            list_roles
            show_role
        Pool Operations
            pool_spawn
            pool_list
            pool_execute
            pool_route
            pool_scale
            pool_health
            pool_close
        Workflow Execution
            trigger_workflow
            get_workflow_status
            cancel_workflow
            execute_workflow_parallel
        Quality Control
            run_qc
            get_qc_thresholds
            set_qc_thresholds
        Terminal Management
            terminal_launch
            terminal_send
            terminal_capture
            terminal_list
            terminal_close
        Memory & Session
            list_checkpoints
            resume_workflow
            delete_checkpoint
            cross_pool_search
```

---

## Quick Reference

### Common Command Patterns

```mermaid
graph TB
    subgraph "Repository Operations"
        R1[mahavishnu list-repos]
        R2[mahavishnu list-repos --tag python]
        R3[mahavishnu list-repos --role tool]
    end

    subgraph "Pool Operations"
        P1[mahavishnu pool spawn --type mahavishnu]
        P2[mahavishnu pool list]
        P3[mahavishnu pool execute POOL_ID --prompt TASK]
        P4[mahavishnu pool close POOL_ID]
    end

    subgraph "Workflow Operations"
        W1[mahavishnu sweep --tag python]
        W2[mahavishnu trigger_workflow --adapter llamaindex]
    end

    subgraph "Quality Operations"
        Q1[crackerjack run all]
        Q2[pytest --cov=mahavishnu]
    end

    style R1 fill:#4A90E2,stroke:#1E3A5F,color:#fff
    style P1 fill:#7B68EE,stroke:#4B0082,color:#fff
    style W1 fill:#90EE90,stroke:#2E7D32
    style Q1 fill:#FF6B6B,stroke:#8B0000,color:#fff
```

---

## Summary

These workflow diagrams cover the most common operational procedures in Mahavishnu:

- **Quick Start**: Setup and configuration
- **Pool Management**: Spawn, execute, scale, and close pools
- **Repository Sweep**: Multi-repo workflow execution
- **Memory Search**: Cross-pool search with caching
- **Quality Control**: Automated quality pipeline
- **Error Recovery**: Circuit breaker and DLQ patterns
- **MCP Tools**: Tool execution flow

For more detailed architecture diagrams, see [VISUAL_GUIDE.md](VISUAL_GUIDE.md).

---

**Document Version**: 1.0
**Last Updated**: 2026-02-03
**Related Documentation**:
- [VISUAL_GUIDE.md](VISUAL_GUIDE.md) - Comprehensive architecture diagrams
- [GETTING_STARTED.md](GETTING_STARTED.md) - Setup and configuration
- [MCP_TOOLS_REFERENCE.md](MCP_TOOLS_REFERENCE.md) - Complete MCP tool documentation
