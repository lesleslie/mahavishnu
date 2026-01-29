# Mahavishnu v1.0.0 Release Notes

Release Date: January 23, 2026

## Overview

Mahavishnu v1.0.0 is the first production-ready release of the global orchestrator package for development workflows. This release includes security hardening, performance optimizations, and integration with multiple orchestration engines.

## Major Features

### Security Enhancements

- JWT authentication for CLI and API access
- Path validation to prevent directory traversal attacks
- Secure configuration management with environment variable support
- Secrets validation with minimum entropy requirements

### Orchestration Engine Support

Orchestration Adapters:

- **LlamaIndex**: Fully implemented for RAG pipelines with Ollama embeddings (production ready)
- **Prefect**: Stub implementation (framework skeleton, not yet functional)
- **Agno**: Stub implementation (framework skeleton, not yet functional)

Deprecated (removed 2025-01-23):

- ~~Airflow~~: Replaced by Prefect
- ~~CrewAI~~: Replaced by Agno
- ~~LangGraph~~: Replaced by Agno

### Performance & Reliability

- Concurrent workflow execution with configurable limits
- Circuit breaker pattern for resilience
- Retry mechanisms with exponential backoff
- Parallel repository processing

### Developer Experience

- MCP (Machine Learning Communication Protocol) server
- Quality control integration with Crackerjack
- Session management with checkpointing via Session-Buddy
- Comprehensive observability with OpenTelemetry

## Breaking Changes

- Configuration now requires environment variables for secrets
- API has been updated to use async/await patterns consistently
- CLI commands have been updated for better UX

## Known Issues

- Performance with extremely large repositories (>10k files) may be impacted
- Some LLM providers may require additional configuration

## Upgrade Instructions

1. Update your configuration to use environment variables for secrets
1. Review the new CLI command syntax
1. Update any custom adapters to use the async interface

## Dependencies

- Python 3.13+
- LangGraph 0.2.x
- Prefect 3.4.x
- FastMCP 0.1.x
- OpenTelemetry SDK 1.38.x

## Support

For support, please open an issue on GitHub or consult the documentation.
