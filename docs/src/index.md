# Mahavishnu Documentation

Welcome to the Mahavishnu documentation. Mahavishnu is a multi-engine orchestration platform that provides unified interfaces for managing workflows across multiple repositories.

**Current Status**: Phase 1 Complete (Foundation + Core Architecture)

**Completed**:
- Security hardening (JWT auth, Claude Code + Qwen support)
- Async base adapter architecture
- FastMCP-based MCP server with terminal management
- Configuration system using Oneiric patterns
- CLI with authentication framework
- Repository management (9 repos configured)
- Test infrastructure (11 test files)

**Partially Complete**:
- Adapter implementations (stubs/skeleton only - actual orchestration logic not implemented)
- MCP tools (terminal tools complete, core orchestration tools missing)

**Not Started**:
- Actual adapter logic (Prefect, LangGraph, Agno)
- LLM provider integrations
- Production error recovery patterns
- Full observability implementation

See [UNIFIED_IMPLEMENTATION_STATUS.md](../../UNIFIED_IMPLEMENTATION_STATUS.md) for detailed progress tracking.

## Table of Contents

- [Installation](installation.md)
- [Configuration](configuration.md)
- [Usage](usage.md)
- [Adapters](adapters/index.md)
  - [Prefect Adapter](adapters/prefect.md) - Stub implementation
  - [LlamaIndex Adapter](adapters/llamaindex.md) - Stub implementation
  - [Agno Adapter](adapters/agno.md) - Stub implementation
- [MCP Server](mcp-server.md)
- [Security](security.md)
- [Production Deployment](production.md)
- [API Reference](api-reference.md)
- [Troubleshooting](troubleshooting.md)

## Architecture

Mahavishnu provides a unified interface to multiple orchestration engines, allowing you to manage complex workflows across multiple repositories with AI-powered automation.

### Core Components

- **Adapter Architecture**: Async base adapter interface for orchestration engines
- **Configuration System**: Oneiric-based layered configuration (defaults -> YAML -> env vars)
- **Error Handling**: Custom exception hierarchy with circuit breaker patterns
- **Repository Management**: YAML-based repository manifest with tag filtering

### Platform Services

- **CLI**: Typer-based command-line interface with authentication
- **MCP Server**: FastMCP-based server for tool integration
- **Terminal Management**: Multi-terminal session management (10+ concurrent sessions)
- **Security**: JWT authentication with multiple providers (Claude Code, Qwen, custom)

### Adapters

Mahavishnu supports the following orchestration engines:

- **Prefect**: High-level workflow orchestration (modern replacement for Airflow)
- **LlamaIndex**: RAG pipelines for knowledge bases and semantic search
- **Agno**: Fast, scalable AI agents with memory and tools

**Note**: All adapter implementations are currently stub/skeleton code. Actual orchestration logic is not yet implemented.

## Quick Links

- [Implementation Status Report](../../UNIFIED_IMPLEMENTATION_STATUS.md) - Detailed progress tracking
- [MCP Tools Specification](../MCP_TOOLS_SPECIFICATION.md) - Complete tool API documentation
- [Architecture Decision Records](../adr/) - Technical decisions and rationale
- [Terminal Management Documentation](../TERMINAL_MANAGEMENT.md) - Terminal feature documentation

## Project Status

**Roadmap**:
- Phase 0: Security Hardening (Complete)
- Phase 1: Foundation Architecture (Complete)
- Phase 2: MCP Server (Partial - terminal tools complete, core tools missing)
- Phase 3: Adapter Implementation (Not Started - 6-9 weeks estimated)
- Phase 4: Production Features (Not Started)
- Phase 5: Testing & Documentation (Not Started)
- Phase 6: Production Readiness (Not Started)

**Estimated Time to Production**: 10 weeks from current state
