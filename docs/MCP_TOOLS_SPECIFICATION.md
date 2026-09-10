# MCP Server Tool Specification

## Overview

Mahavishnu's MCP server exposes **197 tools** split across two layers:

- **27 inline core tools** registered in `mahavishnu/mcp/server_core.py` (always loaded)
- **170 decorated/profile-gated tools** registered across 26 modules under `mahavishnu/mcp/tools/` (loaded per the active profile — `minimal`, `standard`, or `full`)

This document is **generated from source**. The inventory script extracts `@mcp.tool`, `@server.tool`, `@app.tool`, and `mcp.tool()(name)` registrations; see `mahavishnu/mcp/tools/__init__.py` for the module list.

## Tool Profile Gating

Tools are gated by the `MAHAVISHNU_TOOL_PROFILE` environment variable:

- `full` (default): all 197 tools loaded
- `standard`: core 11 groups (terminal, pool, worker, messaging, git, session-buddy, coordination, ecosystem, health, capability, ...)
- `minimal`: health probes only

Profile configuration: `mahavishnu/mcp/tools/profiles.py`. A `discover_tools(query)` meta-tool is always registered so Claude can find unloaded tools.

## Tool Categories

### 1. Repository & Catalog

_7 tool(s)_

#### `list_repos`

**Signature:** `async def list_repos(tag: str | None, limit: int | None, offset: int | None, user_id: str | None)`

**Source:** `mahavishnu/mcp/server_core.py:241`

**Description:** List repositories with optional filtering and pagination.

#### `get_git_velocity_dashboard`

**Signature:** `async def get_git_velocity_dashboard(repo_paths: list[str], days_back: int, user_id: str | None)`

**Source:** `mahavishnu/mcp/tools/git_analytics.py:42`

**Description:** Get git velocity dashboard across multiple repositories.

#### `get_repository_health`

**Signature:** `async def get_repository_health(repo_path: str, user_id: str | None)`

**Source:** `mahavishnu/mcp/tools/git_analytics.py:119`

**Description:** Get repository health metrics including PRs and branches.

#### `get_cross_project_patterns`

**Signature:** `async def get_cross_project_patterns(days_back: int, min_occurrences: int, detect_until_dry: bool, k_empty_rounds: int, max_iterations: int, user_id: str | None)`

**Source:** `mahavishnu/mcp/tools/git_analytics.py:181`

**Description:** Detect patterns across all repositories in the ecosystem.

#### `ecosystem_status`

**Signature:** `async def ecosystem_status(sections: list[str] | None, include_details: bool, timeout_per_section_ms: int)`

**Source:** `mahavishnu/mcp/tools/ecosystem_tools.py:30`

**Description:** Get canonical ecosystem health status across all services and adapters.

#### `ecosystem_capabilities`

**Signature:** `async def ecosystem_capabilities(capability: str | None)`

**Source:** `mahavishnu/mcp/tools/ecosystem_tools.py:76`

**Description:** Query ecosystem capabilities by name or list all.

#### `ecosystem_routing_readiness`

**Signature:** `async def ecosystem_routing_readiness(task_class: str)`

**Source:** `mahavishnu/mcp/tools/ecosystem_tools.py:101`

**Description:** Check routing readiness for a given task class.


### 2. Workflow & Execution

_6 tool(s)_

#### `trigger_workflow`

**Signature:** `async def trigger_workflow(adapter: str, task_type: str, params: dict[str, Any] | None, tag: str | None, repos: list[str] | None, timeout: int | None, user_id: str | None)`

**Source:** `mahavishnu/mcp/server_core.py:273`

**Description:** Trigger a durable workflow execution through a named adapter

#### `get_workflow_status`

**Signature:** `async def get_workflow_status(workflow_id: str, user_id: str | None)`

**Source:** `mahavishnu/mcp/server_core.py:432`

**Description:** Get status of a workflow execution.

#### `list_workflows`

**Signature:** `async def list_workflows(status: str | None, limit: int, offset: int, user_id: str | None)`

**Source:** `mahavishnu/mcp/server_core.py:483`

**Description:** List workflows with optional filtering.

#### `cancel_workflow`

**Signature:** `async def cancel_workflow(workflow_id: str, user_id: str | None)`

**Source:** `mahavishnu/mcp/server_core.py:547`

**Description:** Cancel a running workflow.

#### `get_workflow_statistics`

**Signature:** `async def get_workflow_statistics()`

**Source:** `mahavishnu/mcp/server_core.py:762`

**Description:** Get workflow statistics and analytics.

#### `workflow_get_outcome_tool`

**Signature:** `async def workflow_get_outcome_tool(workflow_id: str, user_id: str | None)`

**Source:** `mahavishnu/mcp/tools/workflow_tools.py:84`

**Description:** Read back the persisted WorkflowOutcome for ``workflow_id``.


### 3. Pool Management

_8 tool(s)_

#### `pool_list`

**Signature:** `async def pool_list()`

**Source:** `mahavishnu/mcp/tools/pool_tools.py:55`

**Description:** List all active pools.

#### `pool_monitor`

**Signature:** `async def pool_monitor(pool_ids: list[str] | None)`

**Source:** `mahavishnu/mcp/tools/pool_tools.py:64`

**Description:** Monitor pool status and metrics.

#### `pool_scale`

**Signature:** `async def pool_scale(pool_id: str, target_workers: int)`

**Source:** `mahavishnu/mcp/tools/pool_tools.py:75`

**Description:** Scale pool to target worker count.

#### `pool_close`

**Signature:** `async def pool_close(pool_id: str)`

**Source:** `mahavishnu/mcp/tools/pool_tools.py:112`

**Description:** Close a specific pool.

#### `pool_close_all`

**Signature:** `async def pool_close_all()`

**Source:** `mahavishnu/mcp/tools/pool_tools.py:132`

**Description:** Close all active pools.

#### `pool_health`

**Signature:** `async def pool_health()`

**Source:** `mahavishnu/mcp/tools/pool_tools.py:153`

**Description:** Get health status of all pools.

#### `pool_search_memory`

**Signature:** `async def pool_search_memory(query: str, limit: int)`

**Source:** `mahavishnu/mcp/tools/pool_tools.py:165`

**Description:** Search memory across all pools.

#### `budget_enforce`

**Signature:** `async def budget_enforce(workflow_id: str, budget_tokens: int | None, budget_turns: int | None, budget_wallclock_seconds: float | None, declared_by: str | None)`

**Source:** `mahavishnu/mcp/tools/pool_tools.py:188`

**Description:** Declare a per-workflow budget; the watchdog enforces it.


### 4. Worker Management

_9 tool(s)_

#### `worker_spawn`

**Signature:** `async def worker_spawn()`

**Source:** `mahavishnu/mcp/tools/worker_tools.py:392`

**Description:** (no docstring)

#### `worker_execute`

**Signature:** `async def worker_execute()`

**Source:** `mahavishnu/mcp/tools/worker_tools.py:398`

**Description:** (no docstring)

#### `worker_execute_batch`

**Signature:** `async def worker_execute_batch()`

**Source:** `mahavishnu/mcp/tools/worker_tools.py:399`

**Description:** (no docstring)

#### `worker_list`

**Signature:** `async def worker_list()`

**Source:** `mahavishnu/mcp/tools/worker_tools.py:400`

**Description:** (no docstring)

#### `worker_monitor`

**Signature:** `async def worker_monitor()`

**Source:** `mahavishnu/mcp/tools/worker_tools.py:393`

**Description:** (no docstring)

#### `worker_collect_results`

**Signature:** `async def worker_collect_results()`

**Source:** `mahavishnu/mcp/tools/worker_tools.py:394`

**Description:** (no docstring)

#### `worker_close`

**Signature:** `async def worker_close()`

**Source:** `mahavishnu/mcp/tools/worker_tools.py:395`

**Description:** (no docstring)

#### `worker_close_all`

**Signature:** `async def worker_close_all()`

**Source:** `mahavishnu/mcp/tools/worker_tools.py:396`

**Description:** (no docstring)

#### `worker_health`

**Signature:** `async def worker_health()`

**Source:** `mahavishnu/mcp/tools/worker_tools.py:397`

**Description:** (no docstring)


### 5. Worker Contract (durable)

_9 tool(s)_

#### `launch_worker`

**Signature:** `async def launch_worker()`

**Source:** `mahavishnu/mcp/tools/worker_contract_tools.py:377`

**Description:** (no docstring)

#### `send_input`

**Signature:** `async def send_input()`

**Source:** `mahavishnu/mcp/tools/worker_contract_tools.py:378`

**Description:** (no docstring)

#### `capture_output`

**Signature:** `async def capture_output()`

**Source:** `mahavishnu/mcp/tools/worker_contract_tools.py:379`

**Description:** (no docstring)

#### `worker_status`

**Signature:** `async def worker_status()`

**Source:** `mahavishnu/mcp/tools/worker_contract_tools.py:380`

**Description:** (no docstring)

#### `wait_for_state`

**Signature:** `async def wait_for_state()`

**Source:** `mahavishnu/mcp/tools/worker_contract_tools.py:381`

**Description:** (no docstring)

#### `cancel_worker`

**Signature:** `async def cancel_worker()`

**Source:** `mahavishnu/mcp/tools/worker_contract_tools.py:382`

**Description:** (no docstring)

#### `worker_revoke`

**Signature:** `async def worker_revoke()`

**Source:** `mahavishnu/mcp/tools/worker_contract_tools.py:383`

**Description:** (no docstring)

#### `worker_run_with_settle`

**Signature:** `async def worker_run_with_settle()`

**Source:** `mahavishnu/mcp/tools/worker_contract_tools.py:384`

**Description:** (no docstring)

#### `worker_settle`

**Signature:** `async def worker_settle()`

**Source:** `mahavishnu/mcp/tools/worker_contract_tools.py:385`

**Description:** (no docstring)


### 6. Terminal

_10 tool(s)_

#### `terminal_launch`

**Signature:** `async def terminal_launch(command: Command, count: int, columns: int, rows: int)`

**Source:** `mahavishnu/mcp/tools/terminal_tools.py:116`

**Description:** Launch terminal sessions running a command.

#### `terminal_send`

**Signature:** `async def terminal_send(session_id: SessionID, command: Command)`

**Source:** `mahavishnu/mcp/tools/terminal_tools.py:136`

**Description:** Send command to a terminal session.

#### `terminal_capture`

**Signature:** `async def terminal_capture(session_id: str, lines: int | None)`

**Source:** `mahavishnu/mcp/tools/terminal_tools.py:149`

**Description:** Capture output from terminal session.

#### `terminal_capture_all`

**Signature:** `async def terminal_capture_all(session_ids: list[str], lines: int | None)`

**Source:** `mahavishnu/mcp/tools/terminal_tools.py:157`

**Description:** Capture output from multiple terminal sessions concurrently.

#### `terminal_list`

**Signature:** `async def terminal_list()`

**Source:** `mahavishnu/mcp/tools/terminal_tools.py:165`

**Description:** List all active terminal sessions.

#### `terminal_close`

**Signature:** `async def terminal_close(session_id: str)`

**Source:** `mahavishnu/mcp/tools/terminal_tools.py:170`

**Description:** Close a terminal session.

#### `terminal_close_all`

**Signature:** `async def terminal_close_all()`

**Source:** `mahavishnu/mcp/tools/terminal_tools.py:175`

**Description:** Close all terminal sessions.

#### `terminal_switch_adapter`

**Signature:** `async def terminal_switch_adapter(adapter_name: str, migrate_sessions: bool)`

**Source:** `mahavishnu/mcp/tools/terminal_tools.py:191`

**Description:** Hot-switch to a different terminal adapter without restart.

#### `terminal_current_adapter`

**Signature:** `async def terminal_current_adapter()`

**Source:** `mahavishnu/mcp/tools/terminal_tools.py:267`

**Description:** Get information about the current terminal adapter.

#### `terminal_list_adapters`

**Signature:** `async def terminal_list_adapters()`

**Source:** `mahavishnu/mcp/tools/terminal_tools.py:275`

**Description:** List all available terminal adapters.


### 7. Worktree

_1 tool(s)_

#### `worktree_manage`

**Signature:** `async def worktree_manage()`

**Source:** `mahavishnu/mcp/tools/worktree_tools.py:155`

**Description:** (no docstring)


### 8. Code Analysis (Tree-sitter)

_7 tool(s)_

#### `treesitter_parse`

**Signature:** `async def treesitter_parse(file_path: str, language: str | None)`

**Source:** `mahavishnu/mcp/tools/treesitter_tools.py:65`

**Description:** Parse a source code file with caching.

#### `treesitter_extract_symbols`

**Signature:** `async def treesitter_extract_symbols(file_path: str, symbol_kinds: list[str] | None)`

**Source:** `mahavishnu/mcp/tools/treesitter_tools.py:114`

**Description:** Extract symbols from a parsed file.

#### `treesitter_find_usages`

**Signature:** `async def treesitter_find_usages(file_path: str, symbol_name: str, search_directory: str | None)`

**Source:** `mahavishnu/mcp/tools/treesitter_tools.py:178`

**Description:** Find usages of a symbol across files.

#### `treesitter_query`

**Signature:** `async def treesitter_query(file_path: str, query: str)`

**Source:** `mahavishnu/mcp/tools/treesitter_tools.py:272`

**Description:** Run a custom tree-sitter query (S-expression format).

#### `treesitter_batch_analyze`

**Signature:** `async def treesitter_batch_analyze(directory: str, file_pattern: str, max_files: int)`

**Source:** `mahavishnu/mcp/tools/treesitter_tools.py:321`

**Description:** Batch analyze multiple files in a directory.

#### `treesitter_cache_stats`

**Signature:** `async def treesitter_cache_stats()`

**Source:** `mahavishnu/mcp/tools/treesitter_tools.py:403`

**Description:** Get cache statistics for the tree-sitter parser.

#### `treesitter_clear_cache`

**Signature:** `async def treesitter_clear_cache()`

**Source:** `mahavishnu/mcp/tools/treesitter_tools.py:419`

**Description:** Clear the tree-sitter parse cache.


### 9. Session-Buddy

_9 tool(s)_

#### `index_code_graph`

**Signature:** `async def index_code_graph(project_path: str, include_docs: bool, user_id: str | None)`

**Source:** `mahavishnu/mcp/tools/session_buddy_tools.py:61`

**Description:** Index codebase structure for better context in Session Buddy.

#### `get_function_context`

**Signature:** `async def get_function_context(project_path: str, function_name: str, user_id: str | None)`

**Source:** `mahavishnu/mcp/tools/session_buddy_tools.py:88`

**Description:** Get caller/callee context for a function for Session Buddy.

#### `find_related_code`

**Signature:** `async def find_related_code(project_path: str, file_path: str, user_id: str | None)`

**Source:** `mahavishnu/mcp/tools/session_buddy_tools.py:112`

**Description:** Find code related by imports/calls for Session Buddy.

#### `index_documentation`

**Signature:** `async def index_documentation(project_path: str, user_id: str | None)`

**Source:** `mahavishnu/mcp/tools/session_buddy_tools.py:137`

**Description:** Extract docstrings and index for semantic search in Session Buddy.

#### `search_documentation`

**Signature:** `async def search_documentation(query: str, user_id: str | None)`

**Source:** `mahavishnu/mcp/tools/session_buddy_tools.py:156`

**Description:** Search through indexed documentation in Session Buddy.

#### `send_project_message`

**Signature:** `async def send_project_message(from_project: str, to_project: str, subject: str, message: str, priority: str, user_id: str | None)`

**Source:** `mahavishnu/mcp/tools/session_buddy_tools.py:175`

**Description:** Send message between projects for Session Buddy.

#### `list_project_messages`

**Signature:** `async def list_project_messages(project: str, user_id: str | None)`

**Source:** `mahavishnu/mcp/tools/session_buddy_tools.py:211`

**Description:** List messages for a project in Session Buddy.

#### `track_channel_session`

**Signature:** `async def track_channel_session(event_type: str, channel_type: str, channel_id: str, sender_id: str, session_scope: str, thread_id: str | None, component_name: str, workspace: str | None, platform: str | None, message_preview: str | None, message_count: int, metadata: dict[str, Any] | None, user_id: str | None)`

**Source:** `mahavishnu/mcp/tools/session_buddy_tools.py:229`

**Description:** Track a channel session event (start / end / heartbeat) in Session-Buddy.

#### `get_channel_sessions`

**Signature:** `async def get_channel_sessions(channel_type: str | None, channel_id: str | None, sender_id: str | None, session_scope: str | None, limit: int, user_id: str | None)`

**Source:** `mahavishnu/mcp/tools/session_buddy_tools.py:294`

**Description:** Query active or recent channel sessions tracked in Session-Buddy.


### 10. OpenTelemetry Trace

_5 tool(s)_

#### `ingest_otel_traces`

**Signature:** `async def ingest_otel_traces(log_files: list[str] | None, trace_data: list[dict] | None, system_id: str)`

**Source:** `mahavishnu/mcp/tools/otel_tools.py:44`

**Description:** Ingest OpenTelemetry traces from log files or direct trace data.

#### `search_otel_traces`

**Signature:** `async def search_otel_traces(query: str, system_id: str | None, limit: int, threshold: float | None)`

**Source:** `mahavishnu/mcp/tools/otel_tools.py:170`

**Description:** Semantic search over OTel traces using vector embeddings.

#### `get_otel_trace`

**Signature:** `async def get_otel_trace(trace_id: str)`

**Source:** `mahavishnu/mcp/tools/otel_tools.py:216`

**Description:** Retrieve a specific OTel trace by ID.

#### `query_local_traces`

**Signature:** `async def query_local_traces(task_class: str, time_range_minutes: int, system_id: str | None, limit: int)`

**Source:** `mahavishnu/mcp/tools/otel_tools.py:251`

**Description:** Query OTel traces by task_class and time range.

#### `otel_ingester_stats`

**Signature:** `async def otel_ingester_stats()`

**Source:** `mahavishnu/mcp/tools/otel_tools.py:356`

**Description:** Get statistics about the OTel trace ingester.


### 11. Coordination (Issues, Todos, Plans)

_15 tool(s)_

#### `coord_list_issues`

**Signature:** `async def coord_list_issues(status: str | None, priority: str | None, repo: str | None, assignee: str | None)`

**Source:** `mahavishnu/mcp/tools/coordination_tools.py:30`

**Description:** List cross-repository issues with optional filtering.

#### `coord_get_issue`

**Signature:** `async def coord_get_issue(issue_id: str)`

**Source:** `mahavishnu/mcp/tools/coordination_tools.py:54`

**Description:** Get detailed information about a specific issue.

#### `coord_create_issue`

**Signature:** `async def coord_create_issue(title: str, description: str, repos: list[str], priority: str, severity: str, assignee: str | None, target: str | None, labels: list[str] | None)`

**Source:** `mahavishnu/mcp/tools/coordination_tools.py:66`

**Description:** Create a new cross-repository issue.

#### `coord_update_issue`

**Signature:** `async def coord_update_issue(issue_id: str, status: str | None, priority: str | None)`

**Source:** `mahavishnu/mcp/tools/coordination_tools.py:119`

**Description:** Update an existing issue.

#### `coord_close_issue`

**Signature:** `async def coord_close_issue(issue_id: str)`

**Source:** `mahavishnu/mcp/tools/coordination_tools.py:153`

**Description:** Close an issue.

#### `coord_list_todos`

**Signature:** `async def coord_list_todos(status: str | None, repo: str | None, assignee: str | None)`

**Source:** `mahavishnu/mcp/tools/coordination_tools.py:164`

**Description:** List todo items with optional filtering.

#### `coord_get_todo`

**Signature:** `async def coord_get_todo(todo_id: str)`

**Source:** `mahavishnu/mcp/tools/coordination_tools.py:187`

**Description:** Get detailed information about a specific todo.

#### `coord_create_todo`

**Signature:** `async def coord_create_todo(task: str, description: str, repo: str, estimate_hours: float, priority: str, assignee: str | None, blocked_by: list[str] | None, labels: list[str] | None, acceptance_criteria: list[str] | None)`

**Source:** `mahavishnu/mcp/tools/coordination_tools.py:199`

**Description:** Create a new todo item.

#### `coord_complete_todo`

**Signature:** `async def coord_complete_todo(todo_id: str)`

**Source:** `mahavishnu/mcp/tools/coordination_tools.py:254`

**Description:** Mark a todo as completed.

#### `coord_get_blocking_issues`

**Signature:** `async def coord_get_blocking_issues(repo: str)`

**Source:** `mahavishnu/mcp/tools/coordination_tools.py:272`

**Description:** Get all issues blocking a specific repository.

#### `coord_check_dependencies`

**Signature:** `async def coord_check_dependencies(consumer: str | None)`

**Source:** `mahavishnu/mcp/tools/coordination_tools.py:280`

**Description:** Validate inter-repository dependencies.

#### `coord_get_repo_status`

**Signature:** `async def coord_get_repo_status(repo: str)`

**Source:** `mahavishnu/mcp/tools/coordination_tools.py:290`

**Description:** Get comprehensive coordination status for a repository.

#### `coord_list_plans`

**Signature:** `async def coord_list_plans(status: str | None, repo: str | None)`

**Source:** `mahavishnu/mcp/tools/coordination_tools.py:311`

**Description:** List cross-repository plans with optional filtering.

#### `coord_list_dependencies`

**Signature:** `async def coord_list_dependencies(consumer: str | None, provider: str | None, dependency_type: str | None)`

**Source:** `mahavishnu/mcp/tools/coordination_tools.py:322`

**Description:** List inter-repository dependencies with optional filtering.

#### `coord_get_ecosystem_status`

**Signature:** `async def coord_get_ecosystem_status()`

**Source:** `mahavishnu/mcp/tools/coordination_tools.py:336`

**Description:** Get unified ecosystem coordination status.


### 12. Repository Messaging

_7 tool(s)_

#### `send_repository_message`

**Signature:** `async def send_repository_message(sender_repo: str, receiver_repo: str, message_type: str, content: dict[str, Any], priority: str)`

**Source:** `mahavishnu/mcp/tools/repository_messaging_tools.py:35`

**Description:** Send a message from one repository to another.

#### `broadcast_repository_message`

**Signature:** `async def broadcast_repository_message(sender_repo: str, message_type: str, content: dict[str, Any], target_repos: list[str] | None, priority: str)`

**Source:** `mahavishnu/mcp/tools/repository_messaging_tools.py:81`

**Description:** Broadcast a message to multiple repositories.

#### `get_repository_messages`

**Signature:** `async def get_repository_messages(receiver_repo: str, message_type: str | None, limit: int, since: str | None)`

**Source:** `mahavishnu/mcp/tools/repository_messaging_tools.py:127`

**Description:** Get messages for a specific repository.

#### `acknowledge_repository_message`

**Signature:** `async def acknowledge_repository_message(message_id: str, receiver_repo: str)`

**Source:** `mahavishnu/mcp/tools/repository_messaging_tools.py:183`

**Description:** Acknowledge receipt of a message.

#### `notify_repository_changes`

**Signature:** `async def notify_repository_changes(repo_path: str, changes: list[dict[str, Any]])`

**Source:** `mahavishnu/mcp/tools/repository_messaging_tools.py:203`

**Description:** Notify other repositories about changes in a repository.

#### `notify_workflow_status`

**Signature:** `async def notify_workflow_status(workflow_id: str, status: str, repo_path: str, target_repos: list[str] | None)`

**Source:** `mahavishnu/mcp/tools/repository_messaging_tools.py:219`

**Description:** Notify other repositories about workflow status changes.

#### `send_quality_alert`

**Signature:** `async def send_quality_alert(repo_path: str, alert_type: str, description: str, severity: str)`

**Source:** `mahavishnu/mcp/tools/repository_messaging_tools.py:237`

**Description:** Send a quality alert to other repositories.


### 13. Hybrid Search

_5 tool(s)_

#### `hybrid_search`

**Signature:** `async def hybrid_search(query: str, repository: str | None, limit: int, semantic_weight: float, lexical_weight: float, min_score: float)`

**Source:** `mahavishnu/mcp/tools/search_tools.py:63`

**Description:** Search across documents using hybrid semantic + lexical search.

#### `index_document`

**Signature:** `async def index_document(doc_id: str, title: str, content: str, repository: str | None, source_type: str, metadata: dict[str, Any] | None)`

**Source:** `mahavishnu/mcp/tools/search_tools.py:107`

**Description:** Index a document for hybrid search.

#### `delete_document`

**Signature:** `async def delete_document(doc_id: str)`

**Source:** `mahavishnu/mcp/tools/search_tools.py:157`

**Description:** Delete a document from the search index.

#### `search_by_repository`

**Signature:** `async def search_by_repository(repository: str, query: str, limit: int)`

**Source:** `mahavishnu/mcp/tools/search_tools.py:190`

**Description:** Search documents within a specific repository.

#### `cross_repo_search`

**Signature:** `async def cross_repo_search(query: str, scope: str, repo_filter: str | None, limit: int, stream_channel: bool)`

**Source:** `mahavishnu/mcp/tools/search_tools.py:222`

**Description:** Fan-out search across Akosha + Session-Buddy and aggregate results.


### 14. Capability Resolution

_5 tool(s)_

#### `list_capabilities`

**Signature:** `async def list_capabilities()`

**Source:** `mahavishnu/mcp/tools/capability_tools.py:210`

**Description:** Ungated introspection tool: enumerate every engine + worker registration.

#### `resolve_capabilities`

**Signature:** `async def resolve_capabilities(requires: list[str], prompt: str, selector: str, user_id: str | None)`

**Source:** `mahavishnu/mcp/tools/capability_tools.py:234`

**Description:** Resolve which engines/workers can satisfy each required capability.

#### `plan_capability`

**Signature:** `async def plan_capability(requires: list[str], prompt: str, selector: str, trace_id: str | None, user_id: str | None)`

**Source:** `mahavishnu/mcp/tools/capability_tools.py:286`

**Description:** Plan the DAG; returns the ExecutionDAG JSON (no engine dispatch).

#### `execute_capability`

**Signature:** `async def execute_capability(requires: list[str], prompt: str, selector: str, trace_id: str | None, user_id: str | None)`

**Source:** `mahavishnu/mcp/tools/capability_tools.py:349`

**Description:** Plan the DAG and return a CapabilityExecutionResult.

#### `get_capability_result`

**Signature:** `async def get_capability_result(trace_id: TraceId)`

**Source:** `mahavishnu/mcp/tools/get_capability_result_tool.py:28`

**Description:** Read back persisted envelopes for a trace_id from Dhara.


### 15. Clone Detection & Refactor

_4 tool(s)_

#### `clone_detect_ecosystem`

**Signature:** `async def clone_detect_ecosystem(repos: list[str] | None, min_similarity: float, detect_until_dry: bool, k_empty_rounds: int, max_iterations: int)`

**Source:** `mahavishnu/mcp/tools/clone_tools.py:318`

**Description:** Fan out clone detection across the ecosystem; returns job-id immediately.

#### `clone_refactor_group`

**Signature:** `async def clone_refactor_group(cluster_id: str, extraction_target: str | None)`

**Source:** `mahavishnu/mcp/tools/clone_tools.py:342`

**Description:** Trigger cross-repo clone refactor DAG; returns job-id immediately.

#### `clone_refactor_status`

**Signature:** `async def clone_refactor_status(limit: int)`

**Source:** `mahavishnu/mcp/tools/clone_tools.py:359`

**Description:** List open clone clusters with confidence tier and PR status.

#### `get_verification_result`

**Signature:** `async def get_verification_result(proposal_id: str)`

**Source:** `mahavishnu/mcp/tools/clone_tools.py:366`

**Description:** Return the stored ``VerificationResult`` for a given ``proposal_id``.


### 16. Learning Pipeline

_5 tool(s)_

#### `get_pipeline_status`

**Signature:** `async def get_pipeline_status()`

**Source:** `mahavishnu/mcp/tools/learning_pipeline_tools.py:53`

**Description:** Get current learning pipeline status including running state, cycle count, and last result.

#### `list_evidence`

**Signature:** `async def list_evidence(query: str, limit: int)`

**Source:** `mahavishnu/mcp/tools/learning_pipeline_tools.py:58`

**Description:** List stored learning evidence, optionally filtered by a search query.

#### `trigger_synthesis`

**Signature:** `async def trigger_synthesis()`

**Source:** `mahavishnu/mcp/tools/learning_pipeline_tools.py:74`

**Description:** Trigger a single learning pipeline cycle manually. Returns cycle result.

#### `list_pending_drafts`

**Signature:** `async def list_pending_drafts()`

**Source:** `mahavishnu/mcp/tools/learning_pipeline_tools.py:89`

**Description:** List all active skill drafts in the registry.

#### `get_promotion_history`

**Signature:** `async def get_promotion_history(skill_id: str)`

**Source:** `mahavishnu/mcp/tools/learning_pipeline_tools.py:113`

**Description:** Get version and promotion history for a specific skill.


### 17. Self-Improvement & Approvals

_7 tool(s)_

#### `review_and_fix`

**Signature:** `async def review_and_fix(scope: str, auto_fix: bool, dry_run: bool)`

**Source:** `mahavishnu/mcp/tools/self_improvement_tools.py:718`

**Description:** Run comprehensive review and optionally fix issues.

#### `request_approval`

**Signature:** `async def request_approval(approval_type: str, context: dict[str, Any])`

**Source:** `mahavishnu/mcp/tools/self_improvement_tools.py:732`

**Description:** Request manual approval for version bump or publish.

#### `respond_to_approval`

**Signature:** `async def respond_to_approval(approval_id: str, approved: bool, selected_option: int | None, rejection_reason: str | None)`

**Source:** `mahavishnu/mcp/tools/self_improvement_tools.py:743`

**Description:** Respond to a pending approval request.

#### `get_pending_approvals`

**Signature:** `async def get_pending_approvals()`

**Source:** `mahavishnu/mcp/tools/self_improvement_tools.py:758`

**Description:** Get all pending approval requests.

#### `self_improvement_analyze_failures`

**Signature:** `async def self_improvement_analyze_failures(repo: str | None, hook: str | None, time_window_days: int)`

**Source:** `mahavishnu/mcp/tools/self_improvement_tools.py:763`

**Description:** Query Dhara for accumulated fix-failure records and surface patterns.

#### `self_improvement_generate`

**Signature:** `async def self_improvement_generate(fingerprint: str, pattern_description: str)`

**Source:** `mahavishnu/mcp/tools/self_improvement_tools.py:776`

**Description:** Trigger improvement generation for a failure pattern (returns job-id immediately).

#### `self_improvement_status`

**Signature:** `async def self_improvement_status(limit: int)`

**Source:** `mahavishnu/mcp/tools/self_improvement_tools.py:787`

**Description:** List recent self-improvement records with before/after failure rates.


### 18. Goal Team

_3 tool(s)_

#### `team_from_goal`

**Signature:** `async def team_from_goal(goal: str, name: str | None, mode: str | None, auto_run: bool, task: str | None, user_id: str | None)`

**Source:** `mahavishnu/mcp/tools/goal_team_tools.py:52`

**Description:** Create an agent team from a natural language goal.

#### `parse_goal`

**Signature:** `async def parse_goal(goal: str, user_id: str | None)`

**Source:** `mahavishnu/mcp/tools/goal_team_tools.py:441`

**Description:** Parse a goal to see what team would be created.

#### `list_team_skills`

**Signature:** `async def list_team_skills()`

**Source:** `mahavishnu/mcp/tools/goal_team_tools.py:632`

**Description:** List all available skills for goal-driven team creation.


### 19. OpenHands

_4 tool(s)_

#### `openhands_run`

**Signature:** `async def openhands_run(prompt: str, timeout: int, run_quality_check: bool)`

**Source:** `mahavishnu/mcp/tools/openhands_tools.py:86`

**Description:** Submit an autonomous development task to OpenHands.

#### `openhands_status`

**Signature:** `async def openhands_status(conv_id: str)`

**Source:** `mahavishnu/mcp/tools/openhands_tools.py:103`

**Description:** Get the status of a running OpenHands conversation.

#### `openhands_cancel`

**Signature:** `async def openhands_cancel(conv_id: str)`

**Source:** `mahavishnu/mcp/tools/openhands_tools.py:115`

**Description:** Cancel a running OpenHands conversation.

#### `openhands_health`

**Signature:** `async def openhands_health()`

**Source:** `mahavishnu/mcp/tools/openhands_tools.py:127`

**Description:** Check whether the OpenHands service is reachable.


### 20. PyCharm Integration

_8 tool(s)_

#### `pycharm_health`

**Signature:** `async def pycharm_health()`

**Source:** `mahavishnu/mcp/tools/pycharm_tools.py:106`

**Description:** Check PyCharm MCP connectivity and health status.

#### `pycharm_run_diagnostics`

**Signature:** `async def pycharm_run_diagnostics(file_path: str, errors_only: bool)`

**Source:** `mahavishnu/mcp/tools/pycharm_tools.py:151`

**Description:** Run diagnostics on a file using PyCharm's code inspection.

#### `pycharm_open_file`

**Signature:** `async def pycharm_open_file(file_path: str, line: int | None)`

**Source:** `mahavishnu/mcp/tools/pycharm_tools.py:189`

**Description:** Open a file in PyCharm editor, optionally at a specific line.

#### `pycharm_search_in_project`

**Signature:** `async def pycharm_search_in_project(pattern: str, file_pattern: str | None)`

**Source:** `mahavishnu/mcp/tools/pycharm_tools.py:219`

**Description:** Search files in project using PyCharm's search index.

#### `pycharm_replace_in_file`

**Signature:** `async def pycharm_replace_in_file(file_path: str, search_text: str, replace_text: str)`

**Source:** `mahavishnu/mcp/tools/pycharm_tools.py:247`

**Description:** Find and replace text in a file via PyCharm.

#### `pycharm_reformat_file`

**Signature:** `async def pycharm_reformat_file(file_path: str)`

**Source:** `mahavishnu/mcp/tools/pycharm_tools.py:285`

**Description:** Reformat a file using PyCharm's code formatter.

#### `pycharm_refactor_symbol`

**Signature:** `async def pycharm_refactor_symbol(symbol_name: str, new_name: str, scope: str)`

**Source:** `mahavishnu/mcp/tools/pycharm_tools.py:312`

**Description:** Rename/refactor a symbol across project files via PyCharm.

#### `pycharm_list_problems`

**Signature:** `async def pycharm_list_problems(file_path: str, severity: str | None)`

**Source:** `mahavishnu/mcp/tools/pycharm_tools.py:353`

**Description:** List code inspections and problems for a file via PyCharm.


### 21. Desktop Automation

_23 tool(s)_

#### `automation_check_permissions`

**Signature:** `async def automation_check_permissions()`

**Source:** `mahavishnu/mcp/tools/desktop_automation_tools.py:67`

**Description:** Check automation permissions (accessibility, screen recording).

#### `automation_status`

**Signature:** `async def automation_status()`

**Source:** `mahavishnu/mcp/tools/desktop_automation_tools.py:76`

**Description:** Get automation manager status and statistics.

#### `automation_launch_app`

**Signature:** `async def automation_launch_app(bundle_id: Annotated[str, Field(description='Application bundle identifier')], dry_run: Annotated[bool, Field(description='Simulate without executing')])`

**Source:** `mahavishnu/mcp/tools/desktop_automation_tools.py:94`

**Description:** Launch an application by bundle identifier.

#### `automation_quit_app`

**Signature:** `async def automation_quit_app(bundle_id: Annotated[str, Field(description='Application bundle identifier')], force: Annotated[bool, Field(description='Force quit')])`

**Source:** `mahavishnu/mcp/tools/desktop_automation_tools.py:106`

**Description:** Quit an application.

#### `automation_activate_app`

**Signature:** `async def automation_activate_app(bundle_id: Annotated[str, Field(description='Application bundle identifier')])`

**Source:** `mahavishnu/mcp/tools/desktop_automation_tools.py:118`

**Description:** Activate (bring to front) an application.

#### `automation_list_apps`

**Signature:** `async def automation_list_apps()`

**Source:** `mahavishnu/mcp/tools/desktop_automation_tools.py:129`

**Description:** List all running applications.

#### `automation_get_active_app`

**Signature:** `async def automation_get_active_app()`

**Source:** `mahavishnu/mcp/tools/desktop_automation_tools.py:138`

**Description:** Get the currently active (frontmost) application.

#### `automation_list_windows`

**Signature:** `async def automation_list_windows(bundle_id: Annotated[str, Field(description='Application bundle identifier')])`

**Source:** `mahavishnu/mcp/tools/desktop_automation_tools.py:151`

**Description:** List all windows for an application.

#### `automation_resize_window`

**Signature:** `async def automation_resize_window(window_id: Annotated[str, Field(description='Window identifier')], width: Annotated[int, Field(description='New width in pixels')], height: Annotated[int, Field(description='New height in pixels')])`

**Source:** `mahavishnu/mcp/tools/desktop_automation_tools.py:162`

**Description:** Resize a window.

#### `automation_move_window`

**Signature:** `async def automation_move_window(window_id: Annotated[str, Field(description='Window identifier')], x: Annotated[int, Field(description='New X position')], y: Annotated[int, Field(description='New Y position')])`

**Source:** `mahavishnu/mcp/tools/desktop_automation_tools.py:175`

**Description:** Move a window to a new position.

#### `automation_close_window`

**Signature:** `async def automation_close_window(window_id: Annotated[str, Field(description='Window identifier')])`

**Source:** `mahavishnu/mcp/tools/desktop_automation_tools.py:188`

**Description:** Close a window.

#### `automation_click_menu`

**Signature:** `async def automation_click_menu(bundle_id: Annotated[str, Field(description='Application bundle identifier')], menu_path: Annotated[list[str], Field(description="Menu path (e.g., ['File', 'Save'])")])`

**Source:** `mahavishnu/mcp/tools/desktop_automation_tools.py:203`

**Description:** Navigate menu and click an item.

#### `automation_list_menus`

**Signature:** `async def automation_list_menus(bundle_id: Annotated[str, Field(description='Application bundle identifier')])`

**Source:** `mahavishnu/mcp/tools/desktop_automation_tools.py:215`

**Description:** List all menus for an application.

#### `automation_type_text`

**Signature:** `async def automation_type_text(text: Annotated[str, Field(description='Text to type')], interval: Annotated[float, Field(description='Delay between keystrokes')], dry_run: Annotated[bool, Field(description='Simulate')])`

**Source:** `mahavishnu/mcp/tools/desktop_automation_tools.py:230`

**Description:** Type text at current cursor position.

#### `automation_press_key`

**Signature:** `async def automation_press_key(key: Annotated[str, Field(description='Key to press')], modifiers: Annotated[list[str] | None, Field(description="Modifiers (e.g., ['cmd', 'shift'])")])`

**Source:** `mahavishnu/mcp/tools/desktop_automation_tools.py:243`

**Description:** Press a key with optional modifiers.

#### `automation_click`

**Signature:** `async def automation_click(x: Annotated[int, Field(description='X coordinate')], y: Annotated[int, Field(description='Y coordinate')], button: Annotated[str, Field(description='Mouse button (left/right/middle)')], clicks: Annotated[int, Field(description='Number of clicks')])`

**Source:** `mahavishnu/mcp/tools/desktop_automation_tools.py:257`

**Description:** Click at coordinates.

#### `automation_drag`

**Signature:** `async def automation_drag(start_x: Annotated[int, Field(description='Starting X coordinate')], start_y: Annotated[int, Field(description='Starting Y coordinate')], end_x: Annotated[int, Field(description='Ending X coordinate')], end_y: Annotated[int, Field(description='Ending Y coordinate')], duration: Annotated[float, Field(description='Duration in seconds')])`

**Source:** `mahavishnu/mcp/tools/desktop_automation_tools.py:271`

**Description:** Drag from one point to another.

#### `automation_scroll`

**Signature:** `async def automation_scroll(x: Annotated[int, Field(description='X coordinate')], y: Annotated[int, Field(description='Y coordinate')], dx: Annotated[int, Field(description='Horizontal scroll amount')], dy: Annotated[int, Field(description='Vertical scroll amount')])`

**Source:** `mahavishnu/mcp/tools/desktop_automation_tools.py:286`

**Description:** Scroll at coordinates.

#### `automation_screenshot`

**Signature:** `async def automation_screenshot(region: Annotated[list[int] | None, Field(description='Region [x, y, width, height] or None for full screen')])`

**Source:** `mahavishnu/mcp/tools/desktop_automation_tools.py:304`

**Description:** Capture a screenshot.

#### `automation_list_screens`

**Signature:** `async def automation_list_screens()`

**Source:** `mahavishnu/mcp/tools/desktop_automation_tools.py:336`

**Description:** List all connected displays.

#### `automation_get_ui_elements`

**Signature:** `async def automation_get_ui_elements(bundle_id: Annotated[str, Field(description='Application bundle identifier')], window_id: Annotated[str | None, Field(description='Window identifier or None for all')])`

**Source:** `mahavishnu/mcp/tools/desktop_automation_tools.py:349`

**Description:** Get UI elements for an application.

#### `automation_get_security_config`

**Signature:** `async def automation_get_security_config()`

**Source:** `mahavishnu/mcp/tools/desktop_automation_tools.py:367`

**Description:** Get security configuration (blocklist, allowlist, etc.).

#### `automation_close`

**Signature:** `async def automation_close()`

**Source:** `mahavishnu/mcp/tools/desktop_automation_tools.py:375`

**Description:** Close the automation manager and release resources.


### 22. Adapter Management

_8 tool(s)_

#### `adapter_list`

**Signature:** `async def adapter_list(domain: str | None, capabilities: list[str] | None, healthy_only: bool)`

**Source:** `mahavishnu/mcp/tools/adapter_registry_tools.py:38`

**Description:** List all registered adapters with optional filters.

#### `adapter_resolve`

**Signature:** `async def adapter_resolve(task_type: str, required_capabilities: list[str], domain: str)`

**Source:** `mahavishnu/mcp/tools/adapter_registry_tools.py:83`

**Description:** Resolve the best adapter for task requirements.

#### `adapter_health`

**Signature:** `async def adapter_health(adapter_name: str | None)`

**Source:** `mahavishnu/mcp/tools/adapter_registry_tools.py:129`

**Description:** Check health of adapters.

#### `adapter_enable`

**Signature:** `async def adapter_enable(adapter_name: str, enabled: bool, reason: str | None)`

**Source:** `mahavishnu/mcp/tools/adapter_registry_tools.py:178`

**Description:** Enable or disable an adapter.

#### `adapter_metadata`

**Signature:** `async def adapter_metadata(adapter_name: str)`

**Source:** `mahavishnu/mcp/tools/adapter_registry_tools.py:220`

**Description:** Get metadata for a specific adapter.

#### `adapter_cache_invalidate`

**Signature:** `async def adapter_cache_invalidate(source: str | None)`

**Source:** `mahavishnu/mcp/tools/adapter_registry_tools.py:255`

**Description:** Invalidate adapter registry caches.

#### `adapter_discover`

**Signature:** `async def adapter_discover(force_refresh: bool)`

**Source:** `mahavishnu/mcp/tools/adapter_registry_tools.py:294`

**Description:** Discover adapters from all sources.

#### `list_adapters`

**Signature:** `async def list_adapters()`

**Source:** `mahavishnu/mcp/server_core.py:1023`

**Description:** List available adapters.


### 23. Health & Liveness

_10 tool(s)_

#### `get_health`

**Signature:** `async def get_health()`

**Source:** `mahavishnu/mcp/server_core.py:1073`

**Description:** Get overall health status of the system.

#### `get_liveness`

**Signature:** `async def get_liveness()`

**Source:** `mahavishnu/mcp/tools/health_tools.py:393`

**Description:** Get liveness status for this service.

#### `get_readiness`

**Signature:** `async def get_readiness()`

**Source:** `mahavishnu/mcp/tools/health_tools.py:413`

**Description:** Get readiness status for this service.

#### `health_check_service`

**Signature:** `async def health_check_service(service_name: str, host: str, port: int, timeout: int, use_tls: bool)`

**Source:** `mahavishnu/mcp/tools/health_tools.py:120`

**Description:** Check health of a specific service.

#### `health_check_all`

**Signature:** `async def health_check_all()`

**Source:** `mahavishnu/mcp/tools/health_tools.py:241`

**Description:** Check health of all configured services.

#### `wait_for_dependency`

**Signature:** `async def wait_for_dependency(service_name: str, host: str, port: int, timeout: int, required: bool, use_tls: bool)`

**Source:** `mahavishnu/mcp/tools/health_tools.py:297`

**Description:** Wait for a specific dependency to become healthy.

#### `wait_for_all_dependencies`

**Signature:** `async def wait_for_all_dependencies()`

**Source:** `mahavishnu/mcp/tools/health_tools.py:346`

**Description:** Wait for all configured dependencies to become healthy.

#### `mcp_list_tools`

**Signature:** `async def mcp_list_tools()`

**Source:** `mahavishnu/mcp/tools/health_tools.py:155`

**Description:** List all registered MCP tools with their metadata.

#### `mcp_test_connection`

**Signature:** `async def mcp_test_connection(service_name: str, host: str, port: int, timeout: int, use_tls: bool, health_path: str)`

**Source:** `mahavishnu/mcp/tools/health_tools.py:176`

**Description:** Ping a specific server to verify MCP connectivity.

#### `mcp_get_metrics`

**Signature:** `async def mcp_get_metrics()`

**Source:** `mahavishnu/mcp/tools/health_tools.py:212`

**Description:** Return a metrics snapshot for the running MCP server.


### 24. Observability & Backup

_15 tool(s)_

#### `get_observability_metrics`

**Signature:** `async def get_observability_metrics()`

**Source:** `mahavishnu/mcp/server_core.py:649`

**Description:** Get current observability metrics from the system.

#### `search_logs`

**Signature:** `async def search_logs(query: str | None, level: str | None, workflow_id: str | None, repo_path: str | None, start_time: str | None, end_time: str | None, size: int)`

**Source:** `mahavishnu/mcp/server_core.py:680`

**Description:** Search logs with various filters.

#### `search_workflows`

**Signature:** `async def search_workflows(workflow_id: str | None, adapter: str | None, task_type: str | None, status: str | None, start_time: str | None, end_time: str | None, size: int)`

**Source:** `mahavishnu/mcp/server_core.py:719`

**Description:** Search workflows with various filters.

#### `get_log_statistics`

**Signature:** `async def get_log_statistics()`

**Source:** `mahavishnu/mcp/server_core.py:776`

**Description:** Get log statistics and analytics.

#### `get_recovery_metrics`

**Signature:** `async def get_recovery_metrics()`

**Source:** `mahavishnu/mcp/server_core.py:790`

**Description:** Get metrics about error recovery and resilience operations.

#### `flush_metrics`

**Signature:** `async def flush_metrics()`

**Source:** `mahavishnu/mcp/server_core.py:1007`

**Description:** Force flush all pending metrics to exporters.

#### `get_active_alerts`

**Signature:** `async def get_active_alerts()`

**Source:** `mahavishnu/mcp/server_core.py:925`

**Description:** Get all active (non-acknowledged) alerts.

#### `acknowledge_alert`

**Signature:** `async def acknowledge_alert(alert_id: str, user: str)`

**Source:** `mahavishnu/mcp/server_core.py:953`

**Description:** Acknowledge an alert.

#### `trigger_test_alert`

**Signature:** `async def trigger_test_alert(severity: str, title: str, description: str)`

**Source:** `mahavishnu/mcp/server_core.py:969`

**Description:** Trigger a test alert for testing purposes.

#### `get_monitoring_dashboard`

**Signature:** `async def get_monitoring_dashboard()`

**Source:** `mahavishnu/mcp/server_core.py:903`

**Description:** Get comprehensive monitoring dashboard data.

#### `run_disaster_recovery_check`

**Signature:** `async def run_disaster_recovery_check()`

**Source:** `mahavishnu/mcp/server_core.py:876`

**Description:** Run a disaster recovery check.

#### `heal_workflows`

**Signature:** `async def heal_workflows()`

**Source:** `mahavishnu/mcp/server_core.py:893`

**Description:** Manually trigger healing of failed workflows.

#### `create_backup`

**Signature:** `async def create_backup(backup_type: str, backup_id: str | None)`

**Source:** `mahavishnu/mcp/server_core.py:804`

**Description:** Create a backup of the system.

#### `list_backups`

**Signature:** `async def list_backups()`

**Source:** `mahavishnu/mcp/server_core.py:827`

**Description:** List all available backups.

#### `restore_backup`

**Signature:** `async def restore_backup(backup_id: str)`

**Source:** `mahavishnu/mcp/server_core.py:858`

**Description:** Restore from a backup.


### 25. User & Auth

_2 tool(s)_

#### `create_user`

**Signature:** `async def create_user(user_id: str, roles: list[str], allowed_repos: list[str] | None, user_id_caller: str | None)`

**Source:** `mahavishnu/mcp/server_core.py:582`

**Description:** Create a new user with specified roles.

#### `check_permission`

**Signature:** `async def check_permission(user_id: str, repo: str, permission: str)`

**Source:** `mahavishnu/mcp/server_core.py:617`

**Description:** Check if a user has a specific permission for a repository.


### 26. Tool Discovery

_4 tool(s)_

#### `discover_tools`

**Signature:** `async def discover_tools(query: str | None, capability: str | None)`

**Source:** `mahavishnu/mcp/server_core.py:1185`

**Description:** Search for available MCP tools by name or capability.

#### `get_tool_versions`

**Signature:** `async def get_tool_versions(tool_name: str | None)`

**Source:** `mahavishnu/mcp/server_core.py:1157`

**Description:** Get version metadata for MCP tools.

#### `list_primitives_tool`

**Signature:** `async def list_primitives_tool(category: str | None)`

**Source:** `mahavishnu/mcp/tools/primitive_tools.py:166`

**Description:** List primitives (MCP tools) registered on this server.

#### `show_primitive_tool`

**Signature:** `async def show_primitive_tool(name: str)`

**Source:** `mahavishnu/mcp/tools/primitive_tools.py:183`

**Description:** Show full detail (docstring + input schema) for one primitive.


### 27. Webhook

_1 tool(s)_

#### `webhook_replay_tool`

**Signature:** `async def webhook_replay_tool(webhook_id: str, user_id: str | None, token: str | None)`

**Source:** `mahavishnu/mcp/tools/webhook_tools.py:49`

**Description:** Read back a stored ``WebhookIngress`` for ``webhook_id``.

