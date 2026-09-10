# Worker Expansion Plan - Priority 1-3
**Date:** 2025-02-03
**Status:** Design Phase
**Effort Estimate:** 3-4 weeks

---

## Executive Summary

Expanding Mahavishnu's worker ecosystem with 6 high-value workers for remote orchestration, IoT communication, container management, and database operations. All workers integrate with Oneiric adapters for configuration, Session-Buddy for result storage, and expose MCP tools for orchestration.

**Priority 1 (2 weeks):**
1. **SSH Worker** - Remote command execution with interactive + non-interactive modes
2. **MQTT Worker** - IoT device communication and pub/sub messaging
3. **Enhanced Terminal Worker** - PTY-allocated interactive sessions

**Priority 2 (1 week):**
4. **Docker/Cloud Run Worker** - Buildpacks + serverless container orchestration
5. **Database Worker** - Migration and backup orchestration

**Priority 3 (3 days):**
6. **Backup Worker** - Cross-repo backup coordination

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│  MAHAVISHNU (Orchestrator)                                      │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │  WorkerManager                                             │ │
│  │  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐          │ │
│  │  │ SSH Worker  │ │ MQTT Worker │ │ Docker Worker│  ...    │ │
│  │  └──────┬──────┘ └──────┬──────┘ └──────┬──────┘          │ │
│  └─────────┼───────────────┼───────────────┼─────────────────┘ │
│            │               │               │                    │
│            ▼               ▼               ▼                    │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │  Oneiric Adapters (Configuration)                          │ │
│  │  SSHClientAdapter │ MQTTAdapter │ CloudRunAdapter         │ │
│  └────────────────────────────────────────────────────────────┘ │
│            │               │               │                    │
│            ▼               ▼               ▼                    │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │  Session-Buddy (Result Storage)                            │ │
│  │  Worker execution history, outputs, telemetry              │ │
│  └────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

**Design Principles:**
1. **BaseWorker inheritance** - All workers extend `mahavishnu.workers.base.BaseWorker`
2. **Oneiric integration** - Configuration via Oneiric adapters (layered loading)
3. **Session-Buddy storage** - All results stored for audit trail
4. **MCP tool exposure** - Orchestrate via MCP protocol
5. **ADR 003 compliance** - Retry, circuit breaker, DLQ integration
6. **Security first** - Input validation, secrets management, audit logging

---

## 1. SSH Worker (Priority 1)

### Purpose
Execute commands on remote servers via SSH with both interactive (PTY) and non-interactive modes. Supports SFTP file transfers and connection pooling.

### Use Cases
- Deploy to remote servers (VPS, bare metal, cloud VMs)
- Execute maintenance tasks across infrastructure
- Run CI/CD pipelines on remote build servers
- Manage edge devices (IoT gateways, kiosks)
- Interactive debugging sessions (`vim`, `top`, `apt-get`)

### Architecture

**Mahavishnu Component:**
```python
# mahavishnu/workers/ssh.py

class SSHWorker(BaseWorker):
    """Execute commands on remote servers via SSH.

    Features:
    - Non-interactive commands (stdout/stderr capture)
    - Interactive sessions with PTY allocation
    - SFTP file upload/download
    - Connection pooling (reuse SSH connections)
    - Key-based and password authentication

    Example:
        >>> worker = SSHWorker(
        ...     host="server.example.com",
        ...     username="admin",
        ...     key_path="~/.ssh/id_rsa"
        ... )
        >>> worker_id = await worker.start()
        >>> result = await worker.execute({
        ...     "command": "ls -la /var/log",
        ...     "mode": "non-interactive"
        ... })
    """

    async def execute_interactive(
        self,
        command: str,
        term_type: str = "xterm",
        rows: int = 24,
        cols: int = 80
    ) -> WorkerResult:
        """Execute command with PTY allocation (for vim, top, etc.)."""

    async def execute_non_interactive(
        self,
        command: str,
        timeout: int = 300
    ) -> WorkerResult:
        """Execute command with stdin/stdout/stderr capture."""

    async def sftp_upload(
        self,
        local_files: list[Path],
        remote_dir: str
    ) -> WorkerResult:
        """Upload files via SFTP."""

    async def sftp_download(
        self,
        remote_files: list[str],
        local_dir: Path
    ) -> WorkerResult:
        """Download files via SFTP."""
```

**Oneiric Adapter:**
```python
# oneiric/adapters/ssh/ssh_client.py

class SSHClientSettings(BaseModel):
    """SSH client configuration."""
    host: str
    username: str
    port: int = 22
    password: SecretStr | None = None
    private_key: str | None = None  # Path or PEM content
    private_key_password: SecretStr | None = None
    known_hosts: str | None = None
    connect_timeout: int = 30
    command_timeout: int = 300

class SSHClientAdapter:
    """Oneiric adapter for SSH client configuration.

    Enables layered configuration:
    1. Default values in Pydantic model
    2. settings/mahavishnu.yaml (committed)
    3. settings/local.yaml (gitignored, local dev)
    4. Environment variables MAHAVISHNU_SSH_*

    Example YAML:
        ssh:
          default_host: "server.example.com"
          default_username: "admin"
          default_private_key: "~/.ssh/id_rsa"
          connection_pool_size: 5
    """
    metadata = AdapterMetadata(
        category="ssh",
        provider="asyncssh",
        capabilities=["execute", "sftp", "interactive"],
        stack_level=20,
        priority=300,
        settings_model=SSHClientSettings,
    )
```

**MCP Tools:**
```python
# mahavishnu/mcp/tools/ssh_tools.py

@mcp.tool()
async def ssh_execute(
    host: str,
    command: str,
    mode: Literal["interactive", "non-interactive"] = "non-interactive",
    username: str | None = None
) -> dict:
    """Execute command on remote server via SSH.

    Args:
        host: Remote server hostname/IP
        command: Command to execute
        mode: Execution mode (interactive allocates PTY)
        username: Override default username

    Returns:
        WorkerResult with exit code, stdout, stderr
    """

@mcp.tool()
async def ssh_sftp_transfer(
    host: str,
    files: list[tuple[str, str]],  # [(local, remote), ...]
    direction: Literal["upload", "download"],
    username: str | None = None
) -> dict:
    """Transfer files via SFTP.

    Args:
        host: Remote server hostname/IP
        files: List of (source, destination) tuples
        direction: Upload or download
        username: Override default username

    Returns:
        Transfer results with file sizes and durations
    """
```

### Implementation Details

**Library:** `asyncssh` (async, Python 3.10+, well-maintained)

**Key Features:**
1. **Connection Pooling** - Reuse SSH connections for multiple commands
2. **PTY Allocation** - Use `SSHServerConnection.create_process()` with `term_type`
3. **Key Management** - Support `~/.ssh/id_rsa`, encrypted keys, agent forwarding
4. **Timeout Handling** - Connect timeout (30s) + command timeout (300s default)
5. **Error Recovery** - ADR 003 retry (network failures) + circuit breaker
6. **Security** - Host key verification, secrets via Oneiric, audit logging

**Session-Buddy Integration:**
```python
# Store execution results
await session_buddy.call_tool(
    "store_memory",
    arguments={
        "content": json.dumps({
            "host": host,
            "command": command,
            "output": result.output,
            "exit_code": result.exit_code,
            "duration_seconds": result.duration_seconds,
            "timestamp": result.timestamp,
        }),
        "metadata": {
            "type": "ssh_execution",
            "worker_id": worker_id,
            "host": host,
            "username": username,
        }
    }
)
```

### Testing Strategy

**Unit Tests:**
- Test connection pooling (reuse connections)
- Test timeout handling (connect + command timeout)
- Test error scenarios (host unreachable, auth failure)
- Test SFTP upload/download

**Integration Tests:**
- Spin up test container with SSH server
- Execute real commands (non-interactive + interactive)
- Test file transfers
- Verify Session-Buddy storage

**Security Tests:**
- Verify host key verification
- Test credential redaction in logs
- Test command injection prevention

### Effort Estimate
- **Core implementation:** 3-4 days
- **Oneiric adapter:** 1 day
- **MCP tools:** 1 day
- **Testing:** 2 days
- **Documentation:** 1 day
- **Total:** 8-9 days

---

## 2. MQTT Worker (Priority 1)

### Purpose
Communicate with IoT devices and edge gateways via MQTT pub/sub messaging. Support for telemetry collection, command broadcasting, and OTA update orchestration.

### Use Cases
- **IoT Telemetry** - Collect sensor data from ESP32, Arduino, Raspberry Pi
- **Device Control** - Send commands to edge devices
- **OTA Updates** - Trigger firmware updates for ESP32 devices
- **Edge Gateway** - Manage Raspberry Pi/Jetson gateways that aggregate sensor data
- **Smart Home** - Control MQTT-enabled devices (Home Assistant, Zigbee2MQTT)

### Architecture

**Mahavishnu Component:**
```python
# mahavishnu/workers/mqtt.py

class MQTTWorker(BaseWorker):
    """MQTT pub/sub worker for IoT communication.

    Features:
    - Publish messages to topics
    - Subscribe to topic patterns (wildcards)
    - QoS levels (0, 1, 2)
    - Retained messages
    - Last Will and Testament
    - TLS/SSL support

    Example:
        >>> worker = MQTTWorker(broker="mqtt.example.com")
        >>> await worker.publish("sensors/+/temperature", {"value": 22.5})
        >>> async for msg in worker.subscribe("sensors/#"):
        ...     print(msg.topic, msg.payload)
    """

    async def publish(
        self,
        topic: str,
        payload: dict | str | bytes,
        qos: int = 0,
        retain: bool = False
    ) -> WorkerResult:
        """Publish message to MQTT topic."""

    async def subscribe(
        self,
        topic_pattern: str,
        qos: int = 0,
        timeout: int | None = None
    ) -> AsyncIterator[MQTTMessage]:
        """Subscribe to topic pattern and yield messages."""

    async def publish_to_devices(
        self,
        device_ids: list[str],
        command: dict,
        topic_suffix: str = "command"
    ) -> WorkerResult:
        """Publish command to multiple devices."""

    async def trigger_ota_update(
        self,
        device_id: str,
        firmware_url: str,
        version: str
    ) -> WorkerResult:
        """Trigger OTA firmware update for device."""
```

**Oneiric Adapter:**
```python
# oneiric/adapters/mqtt/mqtt_client.py

class MQTTClientSettings(BaseModel):
    """MQTT client configuration."""
    broker_host: str
    broker_port: int = 1883
    username: str | None = None
    password: SecretStr | None = None
    client_id: str | None = Field(
        default=None,
        description="Default: mahavishnu-{hostname}-{pid}"
    )
    tls_enabled: bool = False
    tls_ca_cert: str | None = None
    qos: int = 0
    keepalive: int = 60
    will_topic: str | None = None
    will_message: str | None = None
    will_qos: int = 0
    will_retain: bool = False

class MQTTClientAdapter:
    """Oneiric adapter for MQTT client configuration.

    Example YAML:
        mqtt:
          default_broker: "mqtt.example.com"
          default_port: 8883  # TLS port
          tls_enabled: true
          qos: 1
          subscriptions:
            - pattern: "sensors/+/temperature"
              qos: 1
            - pattern: "gateways/+/status"
              qos: 2
    """
    metadata = AdapterMetadata(
        category="mqtt",
        provider="gmqtt",
        capabilities=["publish", "subscribe", "tls", "qos"],
        settings_model=MQTTClientSettings,
    )
```

**MCP Tools:**
```python
# mahavishnu/mcp/tools/mqtt_tools.py

@mcp.tool()
async def mqtt_publish(
    topic: str,
    payload: dict | str,
    qos: int = 0,
    retain: bool = False,
    broker: str | None = None
) -> dict:
    """Publish message to MQTT topic.

    Args:
        topic: MQTT topic (supports wildcards for subscribe)
        payload: Message payload (dict will be JSON-encoded)
        qos: Quality of Service level (0, 1, 2)
        retain: Retain message for new subscribers
        broker: Override default broker

    Returns:
        Publish confirmation with message ID
    """

@mcp.tool()
async def mqtt_subscribe(
    topic_pattern: str,
    timeout: int = 30,
    qos: int = 0,
    broker: str | None = None
) -> dict:
    """Subscribe to MQTT topic pattern.

    Args:
        topic_pattern: Topic pattern (supports + and # wildcards)
        timeout: Subscribe duration in seconds
        qos: Quality of Service level
        broker: Override default broker

    Returns:
        List of received messages with topics and payloads
    """

@mcp.tool()
async def mqtt_trigger_ota(
    device_id: str,
    firmware_url: str,
    version: str,
    broker: str | None = None
) -> dict:
    """Trigger OTA firmware update for device.

    Args:
        device_id: Target device ID
        firmware_url: URL to firmware binary
        version: Firmware version string
        broker: Override default broker

    Returns:
        OTA trigger confirmation
    """
```

### Implementation Details

**Library:** `gmqtt` (async MQTT 5.0 client, Python 3.8+)

**Key Features:**
1. **QoS Levels** - Support QoS 0 (fire and forget), QoS 1 (at least once), QoS 2 (exactly once)
2. **TLS/SSL** - Secure communication with certificate verification
3. **Wildcards** - Subscribe to patterns like `sensors/+/temperature`
4. **Connection Pooling** - Reuse MQTT connections
5. **Last Will** - Notify if Mahavishnu disconnects unexpectedly
6. **Retained Messages** - Device state persistence
7. **Batch Publishing** - Publish to multiple devices efficiently

**Topic Hierarchy Design:**
```
mahavishnu/
├── commands/{device_id}/       # Commands to devices
├── ota/{device_id}/            # OTA update triggers
├── config/{device_id}/         # Configuration updates
└── status/{device_id}/         # Device status (subscribe)

sensors/
├── {device_id}/temperature    # Temperature telemetry
├── {device_id}/humidity        # Humidity telemetry
└── {device_id}/pressure        # Pressure telemetry

gateways/
├── {gateway_id}/status         # Gateway status
├── {gateway_id}/devices        # Connected devices
└── {gateway_id}/telemetry      # Aggregated sensor data
```

### Testing Strategy

**Unit Tests:**
- Test publish/subscribe logic
- Test QoS levels
- Test wildcard subscriptions
- Test TLS configuration

**Integration Tests:**
- Spin up Mosquitto MQTT broker (Docker)
- Publish/subscribe real messages
- Test TLS connection
- Test OTA update flow

**Security Tests:**
- Verify TLS certificate validation
- Test authentication (username/password)
- Test ACL enforcement (if broker supports)

### Effort Estimate
- **Core implementation:** 3 days
- **Oneiric adapter:** 1 day
- **MCP tools:** 1 day
- **Testing:** 2 days
- **Documentation:** 1 day
- **Total:** 8 days

---

## 3. Interactive Terminal Worker (Priority 1)

### Purpose
Enhance existing `TerminalAIWorker` to support PTY-allocated interactive sessions for commands like `vim`, `top`, `htop`, `apt-get`, `ssh` (nested).

### Current Gap Analysis

**Current TerminalAIWorker:**
- ✅ Launches AI CLI (Qwen/Claude) with `stream-json` monitoring
- ❌ **No PTY allocation** - cannot run interactive commands
- ❌ **No keystroke injection** - cannot send input to running processes
- ❌ **No terminal resizing** - cannot adjust terminal dimensions

**Required Enhancements:**

```python
# mahavishnu/workers/terminal_enhanced.py

class InteractiveTerminalWorker(TerminalAIWorker):
    """Enhanced terminal worker with PTY support.

    Adds interactive capabilities on top of TerminalAIWorker:
    - PTY allocation for interactive commands
    - Keystroke injection for process input
    - Terminal resizing support
    - Signal handling (SIGINT, SIGTERM, etc.)

    Example:
        >>> worker = InteractiveTerminalWorker(
        ...     terminal_manager=tm,
        ...     ai_type="claude"
        ... )
        >>> await worker.start_interactive_session()
        >>> await worker.send_keystrokes("vim myfile.txt\r")
        >>> await worker.send_keystrokes(":q\r")
    """

    async def start_interactive_session(
        self,
        term_type: str = "xterm-256color",
        rows: int = 24,
        cols: int = 80
    ) -> str:
        """Start terminal with PTY allocation.

        Allocates pseudo-terminal for interactive commands.
        Returns session ID for subsequent operations.
        """

    async def send_keystrokes(
        self,
        keys: str,
        delay_ms: int = 10
    ) -> None:
        """Send keystrokes to interactive session.

        Args:
            keys: Keystrokes to send (supports escape sequences)
            delay_ms: Delay between keystrokes (default 10ms)

        Example:
            await worker.send_keystrokes("hello world\r")  # Enter key
            await worker.send_keystrokes("\x03")  # Ctrl+C
        """

    async def resize_terminal(
        self,
        rows: int,
        cols: int
    ) -> None:
        """Resize terminal dimensions.

        Useful for full-screen apps (vim, htop, etc.).
        """

    async def send_signal(
        self,
        signal: int
    ) -> None:
        """Send signal to foreground process.

        Signals:
            2 (SIGINT)  - Ctrl+C (interrupt)
            3 (SIGQUIT) - Ctrl+\ (quit)
            9 (SIGKILL) - Force kill
            15 (SIGTERM) - Terminate
            20 (SIGTSTP) - Ctrl+Z (suspend)
        """
```

**Integration with SSH Worker:**
```python
# Nested SSH example
>>> ssh_worker = SSHWorker(host="server.example.com")
>>> await ssh_worker.start()
>>>
>>> # Start interactive SSH session
>>> result = await ssh_worker.execute_interactive(
...     command="ssh user@remote-server",
...     term_type="xterm-256color"
... )
>>>
>>> # Send commands to nested SSH
>>> await ssh_worker.send_keystrokes("ls -la\r")
>>> await ssh_worker.send_keystrokes("exit\r")
```

### Implementation Details

**PTY Allocation:** Use `pty.spawn()` or `pexpect` library
**Keystroke Injection:** Write to PTY master file descriptor
**Terminal Resizing:** Use `TIOCSWINSZ` ioctl
**Signal Handling:** Use `os.kill()` with process group

### Effort Estimate
- **PTY allocation:** 1 day
- **Keystroke injection:** 1 day
- **Signal handling:** 0.5 days
- **Testing:** 1 day
- **Documentation:** 0.5 days
- **Total:** 4 days

---

## 4. Docker/Cloud Run Worker (Priority 2)

### Purpose
Orchestrate container deployments using buildpacks (not Dockerfiles) with preference for serverless Cloud Run over local Docker. OrbStack integration for macOS.

### Use Cases
- Deploy to Google Cloud Run (serverless)
- Build container images using buildpacks (`pack` CLI)
- Run containers locally via OrbStack (macOS)
- Container health checks and rollback

### Architecture

**Mahavishnu Component:**
```python
# mahavishnu/workers/cloud_run.py

class CloudRunWorker(BaseWorker):
    """Google Cloud Run orchestration worker.

    Features:
    - Build images using buildpacks (pack CLI)
    - Deploy to Cloud Run (serverless)
    - Local execution via OrbStack (macOS)
    - Health checks and rollback
    - Zero-downtime deployments

    Example:
        >>> worker = CloudRunWorker(region="us-central1")
        >>> result = await worker.deploy({
        ...     "source_path": "./myapp",
        ...     "service_name": "myapp",
        ...     "memory": "512Mi",
        ...     "cpu": "1"
        ... })
    """

    async def build_with_pack(
        self,
        source_path: Path,
        builder_image: str = "paketo-buildpacks/builder:base",
        cache: bool = True
    ) -> WorkerResult:
        """Build container image using buildpacks.

        Uses `pack` CLI instead of `docker build`.
        Automatically detects language (Python, Node.js, Go, etc.).
        """

    async def deploy_to_cloud_run(
        self,
        image_name: str,
        service_name: str,
        region: str = "us-central1",
        memory: str = "512Mi",
        cpu: str = "1",
        min_instances: int = 0,
        max_instances: int = 10,
        allow_unauthenticated: bool = False
    ) -> WorkerResult:
        """Deploy container to Cloud Run.

        Args:
            image_name: Container image (gcr.io/...)
            service_name: Cloud Run service name
            region: GCP region
            memory: Memory allocation (256Mi, 512Mi, etc.)
            cpu: CPU allocation (1, 2, 4)
            min_instances: Minimum instances (0 = scale to zero)
            max_instances: Maximum instances
            allow_unauthenticated: Allow public access

        Returns:
            Service URL and deployment metadata
        """

    async def run_local_orbstack(
        self,
        image_name: str,
        command: str | None = None,
        ports: dict[int, int] | None = None
    ) -> WorkerResult:
        """Run container locally via OrbStack.

        OrbStack is preferred over Docker Desktop on macOS.
        Falls back to Docker if OrbStack not available.
        """

    async def health_check(
        self,
        service_name: str,
        region: str = "us-central1"
    ) -> WorkerResult:
        """Check Cloud Run service health."""

    async def rollback(
        self,
        service_name: str,
        revision: str | None = None,
        region: str = "us-central1"
    ) -> WorkerResult:
        """Rollback to previous revision."""
```

**Oneiric Adapter:**
```python
# oneiric/adapters/cloud_run/cloud_run.py

class CloudRunSettings(BaseModel):
    """Google Cloud Run configuration."""
    project_id: str
    region: str = "us-central1"
    artifact_registry: str = "us-central1-docker.pkg.dev"
    memory: str = "512Mi"
    cpu: str = "1"
    min_instances: int = 0
    max_instances: int = 10
    timeout_seconds: int = 300
    concurrency: int = 80
    allow_unauthenticated: bool = False

class OrbStackSettings(BaseModel):
    """OrbStack configuration for local containers."""
    enabled: bool = True
    docker_host: str = "unix:///Users/les/.orbstack/docker/docker.sock"
    machine_memory: str = "4GiB"
    machine_cpus: int = 2

class CloudRunAdapter:
    """Oneiric adapter for Cloud Run configuration.

    Example YAML:
        cloud_run:
          default_project_id: "my-project"
          default_region: "us-central1"
          default_memory: "512Mi"
          artifact_registry: "us-central1-docker.pkg.dev"

        orbstack:
          enabled: true
          machine_memory: "4GiB"
    """
    metadata = AdapterMetadata(
        category="cloud_run",
        provider="gcp",
        capabilities=["build", "deploy", "health", "rollback"],
        settings_model=CloudRunSettings,
    )
```

**MCP Tools:**
```python
# mahavishnu/mcp/tools/cloud_run_tools.py

@mcp.tool()
async def cloud_run_deploy(
    source_path: str,
    service_name: str,
    region: str = "us-central1",
    memory: str = "512Mi",
    build_only: bool = False
) -> dict:
    """Build and deploy to Cloud Run using buildpacks.

    Args:
        source_path: Path to application source code
        service_name: Cloud Run service name
        region: GCP region
        memory: Memory allocation
        build_only: Build image without deploying

    Returns:
        Service URL and deployment metadata
    """

@mcp.tool()
async def cloud_run_list_services(
    region: str = "us-central1"
) -> dict:
    """List all Cloud Run services in region."""

@mcp.tool()
async def cloud_run_logs(
    service_name: str,
    region: str = "us-central1",
    tail: bool = False
) -> dict:
    """Get logs for Cloud Run service."""
```

### Implementation Details

**Buildpacks (Preferred over Dockerfiles):**
- Use `pack` CLI (Cloud Native Buildpacks)
- Automatic language detection
- Dependency caching
- Security scanning built-in

**OrbStack Integration (macOS):**
- OrbStack provides faster Docker daemon on macOS
- Socket: `unix:///Users/les/.orbstack/docker/docker.sock`
- Fallback to Docker Desktop if OrbStack not available

**Cloud Run Deployment:**
- Use `gcloud run deploy` or Google Cloud REST API
- Zero-downtime deployments (traffic shifting)
- Automatic rollback on failure

### Effort Estimate
- **Buildpacks integration:** 2 days
- **Cloud Run deployment:** 2 days
- **OrbStack integration:** 1 day
- **Health checks/rollback:** 1 day
- **Oneiric adapter:** 1 day
- **MCP tools:** 1 day
- **Testing:** 2 days
- **Documentation:** 1 day
- **Total:** 11 days

---

## 5. Database Worker (Priority 2)

### Purpose
Orchestrate database migrations, backups, and restores across multiple repositories. Support for PostgreSQL, MySQL, SQLite.

### Use Cases
- Run migrations (Alembic, Flyway, migrate)
- Backup databases before deployments
- Restore from backups
- Cross-repo database coordination

### Architecture

**Mahavishnu Component:**
```python
# mahavishnu/workers/database.py

class DatabaseWorker(BaseWorker):
    """Database orchestration worker.

    Features:
    - Run migrations (Alembic, migrate, etc.)
    - Backup databases (SQL dump, custom format)
    - Restore from backups
    - Seed databases
    - Cross-repo coordination

    Example:
        >>> worker = DatabaseWorker(db_type="postgresql")
        >>> await worker.run_migration(
        ...     db_url="postgresql://user:pass@host/db",
        ...     migration_dir="./migrations"
        ... )
    """

    async def run_migration(
        self,
        db_url: str,
        migration_dir: Path,
        tool: Literal["alembic", "flyway", "migrate", "psql"] = "alembic",
        to_version: str | None = None
    ) -> WorkerResult:
        """Run database migrations.

        Args:
            db_url: Database connection URL
            migration_dir: Path to migration files
            tool: Migration tool to use
            to_version: Target version (None = latest)

        Returns:
            Migration results with applied versions
        """

    async def backup_database(
        self,
        db_url: str,
        backup_path: Path,
        format: Literal["sql", "custom", "tar", "dir"] = "custom"
    ) -> WorkerResult:
        """Backup database.

        Supports:
        - PostgreSQL: pg_dump (SQL, custom, tar, directory)
        - MySQL: mysqldump
        - SQLite: .db file copy
        """

    async def restore_database(
        self,
        db_url: str,
        backup_path: Path
    ) -> WorkerResult:
        """Restore database from backup."""

    async def seed_database(
        self,
        db_url: str,
        seed_file: Path
    ) -> WorkerResult:
        """Seed database with initial data."""
```

**Oneiric Adapter:**
```python
# oneiric/adapters/database/database_client.py

class DatabaseSettings(BaseModel):
    """Database configuration."""
    db_type: Literal["postgresql", "mysql", "sqlite"]
    host: str | None = None
    port: int | None = None
    database: str
    username: str | None = None
    password: SecretStr | None = None
    ssl_mode: str = "prefer"

class DatabaseAdapter:
    """Oneiric adapter for database configuration.

    Example YAML:
        database:
          default_type: "postgresql"
          default_host: "localhost"
          default_port: 5432
          migrations_dir: "./migrations"
          backup_dir: "./backups"
    """
```

### Effort Estimate
- **Core implementation:** 2 days
- **Migration tool integration:** 1 day
- **Backup/restore:** 1 day
- **Oneiric adapter:** 1 day
- **Testing:** 1 day
- **Total:** 6 days

---

## 6. Backup Worker (Priority 3)

### Purpose
Coordinate cross-repo backups to S3/GCS/Azure with retention policies and encryption.

### Architecture

```python
# mahavishnu/workers/backup.py

class BackupWorker(BaseWorker):
    """Backup coordination worker.

    Features:
    - Backup to S3/GCS/Azure
    - Rotate old backups (retention policy)
    - Encrypt backups before upload
    - Backup multiple repos in parallel

    Example:
        >>> worker = BackupWorker(backend="s3")
        >>> await worker.backup_repos([
        ...     "/path/to/repo1",
        ...     "/path/to/repo2"
        ... ])
    """

    async def backup_to_s3(
        self,
        source_paths: list[Path],
        bucket: str,
        prefix: str = "backups",
        encryption: bool = True
    ) -> WorkerResult:
        """Backup directories to S3."""

    async def rotate_backups(
        self,
        backup_prefix: str,
        keep_n: int = 7
    ) -> WorkerResult:
        """Rotate backups, keep last N."""
```

### Effort Estimate
- **Core implementation:** 1 day
- **S3/GCS/Azure integration:** 1 day
- **Encryption:** 0.5 days
- **Testing:** 0.5 days
- **Total:** 3 days

---

## Oneiric Integration Strategy

All workers will integrate with Oneiric adapters for configuration:

```yaml
# settings/mahavishnu.yaml (Oneiric-compatible)

ssh:
  default_host: "server.example.com"
  default_username: "admin"
  private_key: "~/.ssh/id_rsa"
  connection_pool_size: 5

mqtt:
  default_broker: "mqtt.example.com"
  default_port: 8883
  tls_enabled: true
  qos: 1
  subscriptions:
    - pattern: "sensors/+/temperature"
      qos: 1

cloud_run:
  default_project_id: "my-project"
  default_region: "us-central1"
  default_memory: "512Mi"

orbstack:
  enabled: true
  machine_memory: "4GiB"
```

**Benefits:**
1. Layered configuration (defaults → YAML → env)
2. Remote manifest support (hydrate from CDN)
3. Runtime swapping (change config without restart)
4. Type validation (Pydantic models)

---

## Session-Buddy Integration Strategy

All workers store execution results in Session-Buddy:

```python
# Unified storage pattern
await session_buddy.call_tool(
    "store_memory",
    arguments={
        "content": json.dumps({
            "worker_type": worker_type,
            "task": task,
            "result": result.to_dict(),
        }),
        "metadata": {
            "type": "worker_execution",
            "worker_id": worker_id,
            "timestamp": datetime.now(tz=UTC).isoformat(),
            "repo": task.get("repo"),
            "duration_seconds": result.duration_seconds,
        }
    }
)
```

**Query Capabilities:**
- Find all SSH executions for a host
- Find all MQTT messages from a device
- Find all Cloud Run deployments for a service
- Audit trail for compliance

---

## MCP Tool Exposure Strategy

All workers expose MCP tools for orchestration:

```python
# Tool naming convention
{worker}_{action}

# Examples:
ssh_execute
ssh_sftp_transfer
mqtt_publish
mqtt_subscribe
cloud_run_deploy
cloud_run_logs
database_migrate
database_backup
backup_repos
```

**Tool Parameters:**
- All tools accept optional `broker`/`host`/`region` overrides
- All tools return `WorkerResult` with standardized fields
- All tools support timeout and error handling

---

## ADR 003 Integration Strategy

All workers integrate error resilience patterns:

```python
# Retry with circuit breaker
from mahavishnu.core.resilience import (
    retry_with_circuit_breaker,
    CircuitBreakerError
)

class SSHWorker(BaseWorker):
    async def execute_non_interactive(self, command: str) -> WorkerResult:
        try:
            result = await retry_with_circuit_breaker(
                self._execute_internal,
                command,
                recovery_key="ssh_execute",
                max_attempts=3,
                circuit_breaker_threshold=5
            )
            return result
        except PermanentFailure as e:
            # Send to DLQ
            await self.app.dlq.enqueue(
                task_id=f"ssh_{self.worker_id}",
                task={"command": command},
                error=str(e)
            )
            raise
```

**Resilience Features:**
1. **Retry** - 3 attempts with exponential backoff
2. **Circuit Breaker** - Open after 5 failures
3. **DLQ** - Permanent failures go to dead letter queue
4. **Timeout** - Configurable per operation

---

## Security Considerations

### SSH Worker
- **Host key verification** - Prevent MITM attacks
- **Key-based auth** - Prefer over passwords
- **Secrets via Oneiric** - No plaintext in config
- **Audit logging** - Log all commands (exclude sensitive data)

### MQTT Worker
- **TLS/SSL** - Encrypted broker communication
- **Authentication** - Username/password or client certificates
- **ACL enforcement** - Topic-based access control
- **Device authorization** - Verify device identity

### Docker/Cloud Run Worker
- **Minimum privileges** - Service account with limited permissions
- **Image scanning** - Buildpacks include security scans
- **Secret management** - Use Secret Manager or similar
- **Network policies** - Restrict egress/ingress

### Database Worker
- **Credential rotation** - Regular password/key changes
- **Backup encryption** - Encrypt backups at rest
- **Access logging** - Log all database operations
- **Least privilege** - App-specific database users

---

## Testing Strategy

### Unit Tests
- Test worker lifecycle (start, execute, stop)
- Test error handling (timeouts, failures)
- Test Session-Buddy storage
- Test Oneiric config loading

### Integration Tests
- **SSH:** Test container with SSH server
- **MQTT:** Test Mosquitto broker
- **Cloud Run:** Deploy test service to GCP project
- **Database:** Test PostgreSQL container

### Security Tests
- **SSH:** Verify host key checking, auth failure
- **MQTT:** Verify TLS, auth failure
- **Cloud Run:** Verify IAM permissions
- **Database:** Verify SQL injection prevention

### Performance Tests
- **SSH:** Connection pool efficiency
- **MQTT:** Publish/subscribe throughput
- **Cloud Run:** Deployment time
- **Database:** Migration speed

---

## Documentation Strategy

### User Documentation
1. **Quick Start Guide** - Get started in 5 minutes
2. **Worker Reference** - Complete API documentation
3. **Examples** - Common use cases with code
4. **Troubleshooting** - Common issues and solutions

### Developer Documentation
1. **Architecture Diagrams** - System design
2. **Oneiric Integration** - Configuration guide
3. **Session-Buddy Schema** - Data storage format
4. **MCP Tool Reference** - Orchestration tools

### Runbooks
1. **Deployment Runbook** - How to deploy workers
2. **Incident Response** - What to do when things break
3. **Maintenance Procedures** - Regular maintenance tasks

---

## Implementation Timeline

### Week 1: SSH + MQTT (Priority 1)
**Days 1-5:** SSH Worker
- SSHWorker core (interactive + non-interactive)
- SFTP integration
- Oneiric adapter
- MCP tools
- Unit tests

**Days 6-8:** MQTT Worker
- MQTTWorker core (publish + subscribe)
- QoS levels, TLS support
- Oneiric adapter
- MCP tools
- Unit tests

**Day 9:** Interactive Terminal
- PTY allocation
- Keystroke injection
- Signal handling

**Day 10:** Integration testing
- SSH + MQTT end-to-end
- Session-Buddy storage verification
- Security testing

### Week 2: Docker + Database (Priority 2)
**Days 1-4:** Cloud Run Worker
- Buildpacks integration (`pack` CLI)
- Cloud Run deployment
- OrbStack local execution
- Health checks + rollback
- Oneiric adapter
- MCP tools

**Days 5-7:** Database Worker
- Migration tool integration
- Backup/restore
- Oneiric adapter
- MCP tools

**Day 8:** Testing
- Cloud Run deployment test
- Database migration test
- Security testing

**Day 9-10:** Documentation + Hardening

### Week 3: Backup + Polish (Priority 3)
**Days 1-2:** Backup Worker
- S3/GCS/Azure integration
- Retention policies
- Encryption

**Days 3-5:** Comprehensive testing
- End-to-end workflows
- Performance testing
- Security testing

**Days 6-10:** Documentation + Deployment
- User guides
- Developer docs
- Runbooks
- Deployment to production

---

## Success Criteria

### Functional Requirements
- ✅ SSH worker executes commands (interactive + non-interactive)
- ✅ MQTT worker publishes/subscribes (QoS 0, 1, 2)
- ✅ Cloud Run worker builds + deploys (buildpacks)
- ✅ Database worker runs migrations + backups
- ✅ Backup worker coordinates cross-repo backups
- ✅ All workers integrate with Oneiric adapters
- ✅ All workers store results in Session-Buddy
- ✅ All workers expose MCP tools

### Non-Functional Requirements
- ✅ 80%+ test coverage
- ✅ <500ms p95 latency for worker operations
- ✅ 99.5% availability (ADR 003 resilience)
- ✅ Security audit passed (no critical vulnerabilities)
- ✅ Documentation complete (user + developer)

---

## Open Questions

1. **Cloud Run project** - Which GCP project to use for testing?
2. **MQTT broker** - Use self-hosted Mosquitto or CloudMQTT?
3. **SSH key management** - Store in Oneiric Secrets or separate SSH agent?
4. **Backup retention** - How long to keep backups (30 days, 90 days)?
5. **Database migration rollback** - Automatic or manual rollback on failure?

---

## Conclusion

This worker expansion will significantly enhance Mahavishnu's orchestration capabilities:

**Priority 1 (SSH + MQTT):** Remote orchestration + IoT communication
**Priority 2 (Cloud Run + Database):** Serverless deployments + database coordination
**Priority 3 (Backup):** Cross-repo backup automation

**Total Effort:** 3-4 weeks for complete implementation with testing and documentation.

**Next Steps:**
1. Review and approve architecture
2. Set up infrastructure (MQTT broker, GCP project)
3. Begin implementation with SSH worker (Priority 1)

---

**Document Status:** Ready for Review
**Last Updated:** 2025-02-03
**Author:** Claude (Sonnet 4.5)
