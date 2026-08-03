"""Worker type registry with command templates and configurations.

This module defines all available worker types and their configurations,
making it easy to add new worker types without modifying core code.
"""

from dataclasses import dataclass, field
from enum import Enum


class AuthKind(Enum):
    """Authentication mechanism required by a worker."""

    NONE = "none"
    API_KEY = "api_key"
    CLI_SUBSCRIPTION = "cli_subscription"
    MCP_CREDENTIAL = "mcp_credential"
    BEARER_TOKEN = "bearer_token"
    OAUTH = "oauth"


class RuntimeKind(Enum):
    """Runtime that hosts a worker process."""

    NONE = "none"
    SHELL = "shell"
    APPLE_CONTAINER = "apple-container"
    E2B = "e2b"


class WorkerCategory(Enum):
    """Categories of workers for organization."""

    AI_ASSISTANT = "ai_assistant"  # AI coding assistants
    SHELL = "shell"  # Shell/REPL environments
    CONTAINER = "container"  # Container-based execution
    REMOTE = "remote"  # Remote execution (SSH)
    APPLICATION = "application"  # Desktop applications via MCP
    GATEWAY = "gateway"  # Remote gateway workers (HTTP/RPC)


@dataclass
class WorkerConfig:
    """Configuration for a worker type.

    Attributes:
        name: Human-readable name
        worker_type: Unique identifier (e.g., "terminal-shell")
        command: Command template to start the worker
        category: Worker category for grouping
        description: What this worker does
        completion_markers: Strings that indicate task completion
        error_markers: Strings that indicate errors
        stream_format: Output format ("json", "text", "line-delimited")
        supports_interactive: Whether worker supports interactive mode
        default_timeout: Default timeout in seconds
        env_vars: Environment variables to set
        requires_tool: External tool that must be installed
        mcp_server: Optional MCP server name for application workers
        complete_on_valid_json: Stop when the stream yields valid JSON
        required_env: Environment variable names the worker depends on
        required_settings: Mahavishnu settings keys the worker depends on
        auth_kind: Authentication mechanism required to use this worker
        runtime_kind: Runtime that hosts the worker process
        one_shot: Whether the worker runs a single task and exits
        endpoint: Static base URL if the worker is a remote HTTP/RPC service
    """

    name: str
    worker_type: str
    command: str
    category: WorkerCategory
    description: str = ""
    completion_markers: list[str] = field(default_factory=list)
    error_markers: list[str] = field(
        default_factory=lambda: ["error:", "Error:", "ERROR:", "Exception:"]
    )
    stream_format: str = "text"
    supports_interactive: bool = True
    default_timeout: int = 300
    env_vars: dict[str, str] = field(default_factory=dict)
    requires_tool: str | None = None
    mcp_server: str | None = None
    complete_on_valid_json: bool = False
    required_env: list[str] = field(default_factory=list)
    required_settings: list[str] = field(default_factory=list)
    auth_kind: AuthKind = AuthKind.NONE
    runtime_kind: RuntimeKind = RuntimeKind.NONE
    one_shot: bool = False
    endpoint: str | None = None


# Worker type registry - all available workers
WORKER_REGISTRY: dict[str, WorkerConfig] = {
    # AI Assistants
    "terminal-qwen": WorkerConfig(
        name="Qwen AI",
        worker_type="terminal-qwen",
        command="sh -lc 'qwen -o stream-json --approval-mode yolo'",
        category=WorkerCategory.AI_ASSISTANT,
        description="Fast local AI coding assistant with Qwen model",
        completion_markers=["finish_reason", '"done"', '"type": "done"'],
        stream_format="json",
        requires_tool="qwen",
        required_env=[],
        auth_kind=AuthKind.CLI_SUBSCRIPTION,
        runtime_kind=RuntimeKind.SHELL,
        one_shot=False,
        endpoint=None,
    ),
    "terminal-claude": WorkerConfig(
        name="Claude Code",
        worker_type="terminal-claude",
        command="sh -lc 'claude --output-format stream-json --permission-mode acceptEdits'",
        category=WorkerCategory.AI_ASSISTANT,
        description="Claude Code CLI for complex reasoning and coding",
        completion_markers=["finish_reason", '"done"', '"type": "done"'],
        stream_format="json",
        requires_tool="claude",
        required_env=[],
        auth_kind=AuthKind.CLI_SUBSCRIPTION,
        runtime_kind=RuntimeKind.SHELL,
        one_shot=False,
        endpoint=None,
    ),
    "terminal-codex": WorkerConfig(
        name="Codex CLI",
        worker_type="terminal-codex",
        command=(
            'sh -lc \'codex exec --json "$1"; printf "\\n__MAHAVISHNU_DONE__\\n"\' _ {prompt}'
        ),
        category=WorkerCategory.AI_ASSISTANT,
        description="Codex CLI one-shot execution with marker-based completion",
        completion_markers=["__MAHAVISHNU_DONE__"],
        stream_format="text",
        requires_tool="codex",
        required_env=[],
        auth_kind=AuthKind.CLI_SUBSCRIPTION,
        runtime_kind=RuntimeKind.SHELL,
        one_shot=True,
        endpoint=None,
    ),
    "terminal-deepagents": WorkerConfig(
        name="DeepAgents CLI",
        worker_type="terminal-deepagents",
        command=(
            'sh -lc \'deepagents-cli --non-interactive "$1" --quiet --no-stream; '
            'printf "\\n__MAHAVISHNU_DONE__\\n"\' _ {prompt}'
        ),
        category=WorkerCategory.AI_ASSISTANT,
        description="DeepAgents CLI one-shot execution with marker-based completion",
        completion_markers=["__MAHAVISHNU_DONE__"],
        stream_format="text",
        requires_tool="deepagents-cli",
        required_env=[],
        auth_kind=AuthKind.CLI_SUBSCRIPTION,
        runtime_kind=RuntimeKind.SHELL,
        one_shot=True,
        endpoint=None,
    ),
    "terminal-clai": WorkerConfig(
        name="CLAI",
        worker_type="terminal-clai",
        command=('sh -lc \'clai --no-stream "$1"; printf "\\n__MAHAVISHNU_DONE__\\n"\' _ {prompt}'),
        category=WorkerCategory.AI_ASSISTANT,
        description="CLAI one-shot execution with marker-based completion",
        completion_markers=["__MAHAVISHNU_DONE__"],
        stream_format="text",
        requires_tool="clai",
        required_env=[],
        auth_kind=AuthKind.CLI_SUBSCRIPTION,
        runtime_kind=RuntimeKind.SHELL,
        one_shot=True,
        endpoint=None,
    ),
    "terminal-crow": WorkerConfig(
        name="crow-cli ACP",
        worker_type="terminal-crow",
        command="",  # HTTP-ACP worker — no shell command
        category=WorkerCategory.AI_ASSISTANT,
        description=(
            "crow-cli ACP agent — autonomous multi-step reasoning. "
            "For PTY pass-through use GenericShellWorker with CrowTerminalAdapter."
        ),
        completion_markers=[],
        complete_on_valid_json=True,  # ACP protocol returns structured JSON responses
        default_timeout=300,
        requires_tool="crow",
        required_env=[],
        auth_kind=AuthKind.MCP_CREDENTIAL,
        runtime_kind=RuntimeKind.NONE,
        one_shot=False,
        endpoint=None,
    ),
    "terminal-aider": WorkerConfig(
        name="Aider",
        worker_type="terminal-aider",
        command="sh -lc 'aider --no-auto-commit'",
        category=WorkerCategory.AI_ASSISTANT,
        description="Aider AI pair-programming assistant",
        completion_markers=[">"],
        default_timeout=300,
        requires_tool="aider",
        required_env=[],
        auth_kind=AuthKind.CLI_SUBSCRIPTION,
        runtime_kind=RuntimeKind.SHELL,
        one_shot=False,
        endpoint=None,
    ),
    "terminal-goose": WorkerConfig(
        name="Block Goose",
        worker_type="terminal-goose",
        command="sh -lc 'goose'",
        category=WorkerCategory.AI_ASSISTANT,
        description="Block Goose autonomous agent",
        completion_markers=["Goose: "],
        default_timeout=300,
        requires_tool="goose",
        required_env=[],
        auth_kind=AuthKind.CLI_SUBSCRIPTION,
        runtime_kind=RuntimeKind.SHELL,
        one_shot=False,
        endpoint=None,
    ),
    "terminal-gemini": WorkerConfig(
        name="Gemini CLI",
        worker_type="terminal-gemini",
        command="sh -lc 'gemini'",
        category=WorkerCategory.AI_ASSISTANT,
        description="Gemini CLI AI assistant",
        completion_markers=["> "],
        default_timeout=300,
        requires_tool="gemini",
        required_env=[],
        auth_kind=AuthKind.CLI_SUBSCRIPTION,
        runtime_kind=RuntimeKind.SHELL,
        one_shot=False,
        endpoint=None,
    ),
    "terminal-amp": WorkerConfig(
        name="Amp",
        worker_type="terminal-amp",
        command="sh -lc 'amp'",
        category=WorkerCategory.AI_ASSISTANT,
        description="Amp AI coding assistant",
        completion_markers=["> "],
        default_timeout=300,
        requires_tool="amp",
        required_env=[],
        auth_kind=AuthKind.CLI_SUBSCRIPTION,
        runtime_kind=RuntimeKind.SHELL,
        one_shot=False,
        endpoint=None,
    ),
    "gateway-openclaw": WorkerConfig(
        name="OpenClaw Gateway",
        worker_type="gateway-openclaw",
        command="",  # Handled by OpenClawGatewayWorker
        category=WorkerCategory.GATEWAY,
        description="OpenClaw gateway worker via HTTP JSON-RPC",
        supports_interactive=False,
        default_timeout=300,
        required_env=["OPENCLAW_GATEWAY_URL"],
        auth_kind=AuthKind.BEARER_TOKEN,
        runtime_kind=RuntimeKind.NONE,
        one_shot=True,
        endpoint=None,  # read from env (OPENCLAW_GATEWAY_URL) at runtime
    ),
    # terminal-ollama intentionally absent: Ollama uses HTTP API, not a CLI
    # session.  Use OllamaWorker directly instead of routing through
    # GenericShellWorker with an empty command.
    # Shell/REPL Environments
    "terminal-shell": WorkerConfig(
        name="Bash Shell",
        worker_type="terminal-shell",
        command="bash --noediting",
        category=WorkerCategory.SHELL,
        description="Basic bash shell for general command execution",
        completion_markers=["$"],  # Prompt indicates ready
        stream_format="text",
        default_timeout=60,
        required_env=[],
        auth_kind=AuthKind.NONE,
        runtime_kind=RuntimeKind.SHELL,
        one_shot=False,
        endpoint=None,
    ),
    "terminal-python": WorkerConfig(
        name="Python REPL",
        worker_type="terminal-python",
        command="python3 -iq",
        category=WorkerCategory.SHELL,
        description="Python REPL for data processing and scripting",
        completion_markers=[">>>", "..."],
        stream_format="text",
        requires_tool="python3",
        required_env=[],
        auth_kind=AuthKind.NONE,
        runtime_kind=RuntimeKind.SHELL,
        one_shot=False,
        endpoint=None,
    ),
    "terminal-ipython": WorkerConfig(
        name="IPython",
        worker_type="terminal-ipython",
        command="ipython --no-banner",
        category=WorkerCategory.SHELL,
        description="Enhanced Python REPL with rich features",
        completion_markers=["In [", "Out ["],
        stream_format="text",
        requires_tool="ipython",
        required_env=[],
        auth_kind=AuthKind.NONE,
        runtime_kind=RuntimeKind.SHELL,
        one_shot=False,
        endpoint=None,
    ),
    "terminal-node": WorkerConfig(
        name="Node.js REPL",
        worker_type="terminal-node",
        command="node -i",
        category=WorkerCategory.SHELL,
        description="Node.js REPL for JavaScript/TypeScript tasks",
        completion_markers=[">"],
        stream_format="text",
        requires_tool="node",
        required_env=[],
        auth_kind=AuthKind.NONE,
        runtime_kind=RuntimeKind.SHELL,
        one_shot=False,
        endpoint=None,
    ),
    # Remote Execution
    "terminal-ssh": WorkerConfig(
        name="SSH Remote",
        worker_type="terminal-ssh",
        command="ssh {host}",  # Requires host parameter
        category=WorkerCategory.REMOTE,
        description="SSH connection for remote command execution",
        completion_markers=["$", "#", "%"],
        stream_format="text",
        requires_tool="ssh",
        default_timeout=600,
        required_env=[],
        required_settings=["workers.remote.hosts"],
        auth_kind=AuthKind.BEARER_TOKEN,
        runtime_kind=RuntimeKind.SHELL,
        one_shot=False,
        endpoint=None,
    ),
    # Database Workers
    "terminal-mysql": WorkerConfig(
        name="MySQL CLI",
        worker_type="terminal-mysql",
        command="mysql -u {user} -p{password} -h {host} {database}",
        category=WorkerCategory.SHELL,
        description="MySQL database CLI for SQL operations",
        completion_markers=["mysql>", "->"],
        stream_format="text",
        requires_tool="mysql",
        default_timeout=300,
        required_env=["MYSQL_PASSWORD"],
        auth_kind=AuthKind.BEARER_TOKEN,
        runtime_kind=RuntimeKind.SHELL,
        one_shot=False,
        endpoint=None,
    ),
    "terminal-psql": WorkerConfig(
        name="PostgreSQL CLI",
        worker_type="terminal-psql",
        command="psql -U {user} -h {host} -d {database}",
        category=WorkerCategory.SHELL,
        description="PostgreSQL database CLI for SQL operations",
        completion_markers=["=>", "->"],
        stream_format="text",
        requires_tool="psql",
        default_timeout=300,
        required_env=["PGPASSWORD"],
        auth_kind=AuthKind.BEARER_TOKEN,
        runtime_kind=RuntimeKind.SHELL,
        one_shot=False,
        endpoint=None,
    ),
    "terminal-turso": WorkerConfig(
        name="Turso CLI",
        worker_type="terminal-turso",
        command="turso db shell {database}",
        category=WorkerCategory.SHELL,
        description="Turso/libSQL database CLI for edge database operations",
        completion_markers=["turso> ", "...>"],
        stream_format="text",
        requires_tool="turso",
        default_timeout=300,
        required_env=["TURSO_AUTH_TOKEN"],
        auth_kind=AuthKind.BEARER_TOKEN,
        runtime_kind=RuntimeKind.SHELL,
        one_shot=False,
        endpoint=None,
    ),
    "terminal-redis": WorkerConfig(
        name="Redis CLI",
        worker_type="terminal-redis",
        command="redis-cli -h {host} -p {port}",
        category=WorkerCategory.SHELL,
        description="Redis CLI for cache and data structure operations",
        completion_markers=[">"],
        stream_format="text",
        requires_tool="redis-cli",
        default_timeout=120,
        required_env=[],
        auth_kind=AuthKind.BEARER_TOKEN,
        runtime_kind=RuntimeKind.SHELL,
        one_shot=False,
        endpoint=None,
    ),
    # WebAssembly Workers
    "terminal-wasmtime": WorkerConfig(
        name="Wasmtime Runtime",
        worker_type="terminal-wasmtime",
        command="wasmtime",
        category=WorkerCategory.SHELL,
        description="WebAssembly runtime using Wasmtime",
        completion_markers=[">", "$"],
        stream_format="text",
        requires_tool="wasmtime",
        required_env=[],
        auth_kind=AuthKind.NONE,
        runtime_kind=RuntimeKind.SHELL,
        one_shot=False,
        endpoint=None,
    ),
    "terminal-wasmer": WorkerConfig(
        name="Wasmer Runtime",
        worker_type="terminal-wasmer",
        command="wasmer",
        category=WorkerCategory.SHELL,
        description="WebAssembly runtime using Wasmer",
        completion_markers=[">", "$"],
        stream_format="text",
        requires_tool="wasmer",
        required_env=[],
        auth_kind=AuthKind.NONE,
        runtime_kind=RuntimeKind.SHELL,
        one_shot=False,
        endpoint=None,
    ),
    # Isolated execution (auto-tiered microVMs; Docker/Podman removed 2026-07)
    "container": WorkerConfig(
        name="Isolated Executor (legacy alias)",
        worker_type="container",
        command="",  # Handled by WorkerManager._create_isolated_worker
        category=WorkerCategory.CONTAINER,
        description="Legacy alias for container-executor (auto-tiered microVM isolation)",
        supports_interactive=False,
        required_env=[],
        auth_kind=AuthKind.NONE,
        runtime_kind=RuntimeKind.NONE,
        one_shot=True,
        endpoint=None,
    ),
    "container-executor": WorkerConfig(
        name="Isolated Executor (auto-tier)",
        worker_type="container-executor",
        command="",  # Handled by WorkerManager._create_isolated_worker
        category=WorkerCategory.CONTAINER,
        description="Auto-tiered microVM isolation: Apple container locally, E2B sandbox fallback",
        supports_interactive=False,
        required_env=[],
        auth_kind=AuthKind.NONE,
        # Tier resolved at worker creation time, not statically known here
        runtime_kind=RuntimeKind.NONE,
        one_shot=True,
        endpoint=None,
    ),
    "apple-container": WorkerConfig(
        name="Apple Container (microVM)",
        worker_type="apple-container",
        command="",  # Handled by AppleContainerWorker
        category=WorkerCategory.CONTAINER,
        description="Apple `container` microVM per task (Apple silicon; E2B fallback otherwise)",
        supports_interactive=False,
        requires_tool="container",
        required_env=[],
        auth_kind=AuthKind.NONE,
        runtime_kind=RuntimeKind.APPLE_CONTAINER,
        one_shot=True,
        endpoint=None,
    ),
    "e2b-sandbox": WorkerConfig(
        name="E2B Cloud Sandbox",
        worker_type="e2b-sandbox",
        command="",  # Handled by E2BSandboxWorker
        category=WorkerCategory.CONTAINER,
        description="E2B Firecracker cloud sandbox for isolated execution",
        supports_interactive=False,
        required_env=["E2B_API_KEY"],
        auth_kind=AuthKind.NONE,
        runtime_kind=RuntimeKind.E2B,
        one_shot=True,
        endpoint=None,
    ),
    # Application Workers (via MCP)
    "application-gimp": WorkerConfig(
        name="GIMP Image Editor",
        worker_type="application-gimp",
        command="",  # Handled via MCP
        category=WorkerCategory.APPLICATION,
        description="GIMP image editing via MCP server",
        mcp_server="gimp-mcp",
        supports_interactive=False,
        required_env=[],
        auth_kind=AuthKind.MCP_CREDENTIAL,
        runtime_kind=RuntimeKind.NONE,
        one_shot=False,
        endpoint=None,
    ),
    "application-inkscape": WorkerConfig(
        name="Inkscape Vector Graphics",
        worker_type="application-inkscape",
        command="inkscape --shell",  # Interactive shell mode
        category=WorkerCategory.APPLICATION,
        description="Inkscape SVG editor with shell mode for automation",
        completion_markers=[">"],
        stream_format="text",
        requires_tool="inkscape",
        required_env=[],
        auth_kind=AuthKind.NONE,
        runtime_kind=RuntimeKind.SHELL,
        one_shot=False,
        endpoint=None,
    ),
    "application-blender": WorkerConfig(
        name="Blender 3D",
        worker_type="application-blender",
        command="",  # Handled via MCP
        category=WorkerCategory.APPLICATION,
        description="Blender 3D modeling and rendering via MCP server",
        mcp_server="blender-mcp",
        supports_interactive=False,
        required_env=[],
        auth_kind=AuthKind.MCP_CREDENTIAL,
        runtime_kind=RuntimeKind.NONE,
        one_shot=False,
        endpoint=None,
    ),
    "application-mdinject": WorkerConfig(
        name="MDInject",
        worker_type="application-mdinject",
        command="",  # Handled via MCP
        category=WorkerCategory.APPLICATION,
        description="Markdown prompt injection and management via MCP server",
        mcp_server="mdinject",
        supports_interactive=False,
        required_env=[],
        auth_kind=AuthKind.MCP_CREDENTIAL,
        runtime_kind=RuntimeKind.NONE,
        one_shot=False,
        endpoint=None,
    ),
    "application-vscode": WorkerConfig(
        name="VS Code",
        worker_type="application-vscode",
        command="",  # Handled via MCP
        category=WorkerCategory.APPLICATION,
        description="VS Code IDE automation via MCP server",
        mcp_server="vscode-mcp",
        supports_interactive=False,
        required_env=[],
        auth_kind=AuthKind.MCP_CREDENTIAL,
        runtime_kind=RuntimeKind.NONE,
        one_shot=False,
        endpoint=None,
    ),
    "application-penpot": WorkerConfig(
        name="Penpot Design",
        worker_type="application-penpot",
        command="",  # Handled via MCP
        category=WorkerCategory.APPLICATION,
        description="Penpot design and prototyping via MCP server",
        mcp_server="penpot",
        supports_interactive=False,
        required_env=[],
        auth_kind=AuthKind.MCP_CREDENTIAL,
        runtime_kind=RuntimeKind.NONE,
        one_shot=False,
        endpoint=None,
    ),
    "application-grafana": WorkerConfig(
        name="Grafana",
        worker_type="application-grafana",
        command="",  # Handled via MCP
        category=WorkerCategory.APPLICATION,
        description="Grafana dashboards and monitoring via MCP server",
        mcp_server="grafana",
        supports_interactive=False,
        required_env=[],
        auth_kind=AuthKind.MCP_CREDENTIAL,
        runtime_kind=RuntimeKind.NONE,
        one_shot=False,
        endpoint=None,
    ),
    # New MCP Server Workers
    "application-porkbun-dns": WorkerConfig(
        name="Porkbun DNS",
        worker_type="application-porkbun-dns",
        command="",  # Handled via MCP
        category=WorkerCategory.APPLICATION,
        description="Porkbun DNS record management via MCP server",
        mcp_server="porkbun-dns-mcp",
        supports_interactive=False,
        required_env=[],
        auth_kind=AuthKind.MCP_CREDENTIAL,
        runtime_kind=RuntimeKind.NONE,
        one_shot=False,
        endpoint=None,
    ),
    "application-porkbun-domain": WorkerConfig(
        name="Porkbun Domain",
        worker_type="application-porkbun-domain",
        command="",  # Handled via MCP
        category=WorkerCategory.APPLICATION,
        description="Porkbun domain management via MCP server",
        mcp_server="porkbun-domain-mcp",
        supports_interactive=False,
        required_env=[],
        auth_kind=AuthKind.MCP_CREDENTIAL,
        runtime_kind=RuntimeKind.NONE,
        one_shot=False,
        endpoint=None,
    ),
    "application-synxis-crs": WorkerConfig(
        name="SynXis CRS",
        worker_type="application-synxis-crs",
        command="",  # Handled via MCP
        category=WorkerCategory.APPLICATION,
        description="SynXis Central Reservation System via MCP server",
        mcp_server="synxis-crs-mcp",
        supports_interactive=False,
        required_env=[],
        auth_kind=AuthKind.MCP_CREDENTIAL,
        runtime_kind=RuntimeKind.NONE,
        one_shot=False,
        endpoint=None,
    ),
    "application-synxis-pms": WorkerConfig(
        name="SynXis PMS",
        worker_type="application-synxis-pms",
        command="",  # Handled via MCP
        category=WorkerCategory.APPLICATION,
        description="SynXis Property Management System via MCP server",
        mcp_server="synxis-pms-mcp",
        supports_interactive=False,
        required_env=[],
        auth_kind=AuthKind.MCP_CREDENTIAL,
        runtime_kind=RuntimeKind.NONE,
        one_shot=False,
        endpoint=None,
    ),
    "application-graphics": WorkerConfig(
        name="Graphics",
        worker_type="application-graphics",
        command="",  # Handled via MCP
        category=WorkerCategory.APPLICATION,
        description="Image manipulation via Pillow/pilkit MCP server",
        mcp_server="graphics-mcp",
        supports_interactive=False,
        required_env=[],
        auth_kind=AuthKind.MCP_CREDENTIAL,
        runtime_kind=RuntimeKind.NONE,
        one_shot=False,
        endpoint=None,
    ),
    "application-neo4j": WorkerConfig(
        name="Neo4j Graph",
        worker_type="application-neo4j",
        command="",  # Handled via MCP
        category=WorkerCategory.APPLICATION,
        description="Neo4j graph database via MCP server",
        mcp_server="neo4j-mcp",
        supports_interactive=False,
        required_env=[],
        auth_kind=AuthKind.MCP_CREDENTIAL,
        runtime_kind=RuntimeKind.NONE,
        one_shot=False,
        endpoint=None,
    ),
    # IDE Workers (via MCP)
    "application-pycharm": WorkerConfig(
        name="PyCharm IDE",
        worker_type="application-pycharm",
        command="",  # Handled via MCP
        category=WorkerCategory.APPLICATION,
        description="PyCharm IDE automation via JetBrains MCP server",
        mcp_server="jetbrains",
        supports_interactive=False,
        default_timeout=60,
        required_env=[],
        auth_kind=AuthKind.MCP_CREDENTIAL,
        runtime_kind=RuntimeKind.NONE,
        one_shot=False,
        endpoint=None,
    ),
    # DevOps/Infrastructure Workers
    "terminal-sqlite": WorkerConfig(
        name="SQLite CLI",
        worker_type="terminal-sqlite",
        command="sqlite3 {database}",
        category=WorkerCategory.SHELL,
        description="SQLite database CLI for local database operations",
        completion_markers=["sqlite>", "...>"],
        stream_format="text",
        requires_tool="sqlite3",
        default_timeout=120,
        required_env=[],
        auth_kind=AuthKind.NONE,
        runtime_kind=RuntimeKind.SHELL,
        one_shot=False,
        endpoint=None,
    ),
    "terminal-mongo": WorkerConfig(
        name="MongoDB Shell",
        worker_type="terminal-mongo",
        command="mongosh --quiet",
        category=WorkerCategory.SHELL,
        description="MongoDB shell for document database operations",
        completion_markers=[">", "test>"],
        stream_format="text",
        requires_tool="mongosh",
        default_timeout=300,
        required_env=[],
        auth_kind=AuthKind.BEARER_TOKEN,
        runtime_kind=RuntimeKind.SHELL,
        one_shot=False,
        endpoint=None,
    ),
    "terminal-kubectl": WorkerConfig(
        name="Kubernetes CLI",
        worker_type="terminal-kubectl",
        command="kubectl",
        category=WorkerCategory.SHELL,
        description="Kubernetes CLI for cluster management",
        completion_markers=["$"],
        stream_format="text",
        requires_tool="kubectl",
        default_timeout=300,
        required_env=[],
        auth_kind=AuthKind.CLI_SUBSCRIPTION,
        runtime_kind=RuntimeKind.SHELL,
        one_shot=False,
        endpoint=None,
    ),
    "terminal-terraform": WorkerConfig(
        name="Terraform CLI",
        worker_type="terminal-terraform",
        command="terraform",
        category=WorkerCategory.SHELL,
        description="Terraform CLI for infrastructure as code",
        completion_markers=["$"],
        stream_format="text",
        requires_tool="terraform",
        default_timeout=600,
        required_env=[],
        auth_kind=AuthKind.CLI_SUBSCRIPTION,
        runtime_kind=RuntimeKind.SHELL,
        one_shot=False,
        endpoint=None,
    ),
    "openhands": WorkerConfig(
        name="OpenHands",
        worker_type="openhands",
        command="",  # GATEWAY worker — HTTP API, no shell command
        category=WorkerCategory.GATEWAY,
        description="OpenHands autonomous dev agent v1.7.0 — REST+WebSocket API",
        completion_markers=[],
        default_timeout=600,
        requires_tool="openhands",
        required_env=["OPENHANDS_API_KEY"],
        auth_kind=AuthKind.API_KEY,
        runtime_kind=RuntimeKind.NONE,
        one_shot=True,
        endpoint=None,  # resolved from settings at runtime
    ),
    "a2a": WorkerConfig(
        name="A2A Gateway",
        worker_type="a2a",
        command="",  # GATEWAY worker — HTTP/SSE API, no shell command
        category=WorkerCategory.GATEWAY,
        description=(
            "Google A2A protocol — routes tasks to external agents by name. "
            "Agent URLs resolved from settings only (SSRF-safe)."
        ),
        requires_tool=None,
        required_env=[],
        auth_kind=AuthKind.API_KEY,
        runtime_kind=RuntimeKind.NONE,
        one_shot=True,
        endpoint=None,  # credential resolved from a2a.agents[*].api_key settings
    ),
}


def get_worker_config(worker_type: str) -> WorkerConfig | None:
    """Get configuration for a worker type.

    Args:
        worker_type: Worker type identifier

    Returns:
        WorkerConfig or None if not found
    """
    return WORKER_REGISTRY.get(worker_type)


def resolve_worker_type(
    worker_type: str,
    task_type: str | None = None,
    prompt: str = "",
) -> str:
    """Pure intent-routing helper.

    Returns the worker type unchanged. Historical env-var inference that
    swapped terminal-* workers into gateway-openclaw is removed; callers
    pick the gateway explicitly when they want it.
    """
    return worker_type


def list_worker_types(category: WorkerCategory | None = None) -> list[str]:
    """List available worker types, optionally filtered by category.

    Args:
        category: Optional category filter

    Returns:
        List of worker type identifiers
    """
    if category is None:
        return list(WORKER_REGISTRY.keys())
    return [wt for wt, cfg in WORKER_REGISTRY.items() if cfg.category == category]


def get_workers_by_category() -> dict[WorkerCategory, list[WorkerConfig]]:
    """Get all workers grouped by category.

    Returns:
        Dictionary mapping categories to worker configs
    """
    result: dict[WorkerCategory, list[WorkerConfig]] = {cat: [] for cat in WorkerCategory}
    for cfg in WORKER_REGISTRY.values():
        result[cfg.category].append(cfg)
    return result


def validate_worker_dependencies() -> dict[str, bool]:
    """Check if required tools for workers are installed.

    Returns:
        Dictionary mapping worker types to availability status
    """
    import shutil

    results = {}
    for worker_type, config in WORKER_REGISTRY.items():
        if config.requires_tool:
            results[worker_type] = shutil.which(config.requires_tool) is not None
        else:
            results[worker_type] = True  # No external dependency
    return results


__all__ = [
    "WORKER_REGISTRY",
    "AuthKind",
    "RuntimeKind",
    "WorkerCategory",
    "WorkerConfig",
    "get_worker_config",
    "get_workers_by_category",
    "list_worker_types",
    "validate_worker_dependencies",
]
