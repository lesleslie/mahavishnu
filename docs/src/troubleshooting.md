# Troubleshooting

This guide helps troubleshoot common issues with Mahavishnu.

## Common Issues

### Authentication Errors

#### Symptom

```
AuthenticationError: Could not validate credentials
```

#### Solution

1. Verify `MAHAVISHNU_AUTH_SECRET` is set with a value of at least 32 characters
1. Ensure authentication is properly configured in settings
1. Check that JWT tokens are not expired

```bash
# Verify the secret is set
echo $MAHAVISHNU_AUTH_SECRET

# Regenerate if needed
export MAHAVISHNU_AUTH_SECRET=$(openssl rand -hex 32)
```

### Configuration Loading Errors

#### Symptom

```
ConfigurationError: Failed to load configuration
```

#### Solution

1. Verify configuration files are valid YAML
1. Check that required environment variables are set
1. Ensure file paths exist and are accessible

```bash
# Validate YAML syntax
python -c "import yaml; print(yaml.safe_load(open('settings/mahavishnu.yaml')))"
```

### Adapter Initialization Failures

#### Symptom

```
ConfigurationError: Failed to initialize langgraph adapter
```

#### Solution

1. Check if required dependencies are installed
1. Verify adapter-specific configuration
1. Ensure LLM API keys are valid

```bash
# Install adapter-specific dependencies
pip install -e .[langgraph]
```

### Repository Path Validation Errors

#### Symptom

```
ValidationError: Invalid path contains directory traversal
```

#### Solution

1. Check repository paths in repos.yaml for `..` sequences
1. Ensure paths are absolute or properly relative
1. Verify paths exist and are accessible

### MCP Server Connection Issues

#### Symptom

```
ConnectionError: Unable to connect to MCP server
```

#### Solution

1. Verify the server is running
1. Check the configured port is available
1. Ensure firewall rules allow connections

```bash
# Check if server is running
netstat -an | grep 3000

# Test connection
curl http://localhost:3000/
```

## Performance Issues

### Slow Workflow Execution

#### Symptoms

- Workflows taking longer than expected
- High memory usage
- Timeout errors

#### Solutions

1. Reduce `max_concurrent_workflows` to decrease resource contention
1. Increase `timeout_per_repo` if processing large repositories
1. Monitor system resources (CPU, memory, disk I/O)

```bash
# Check current configuration
mahavishnu config show --field max_concurrent_workflows
```

### Circuit Breaker Tripped

#### Symptom

```
CircuitBreaker: Circuit is OPEN, request denied
```

#### Solution

1. Check underlying service health (LLM provider, database, etc.)
1. Wait for the circuit breaker timeout to reset
1. Adjust circuit breaker thresholds if needed

## Debugging Tips

### Enable Debug Logging

Set log level to DEBUG for detailed information:

```bash
export MAHAVISHNU_LOG_LEVEL=DEBUG
mahavishnu sweep --tag debug --adapter langgraph
```

### Check Health Status

Use the health command to diagnose issues:

```bash
mahavishnu health
```

### Inspect Configuration

View current configuration values:

```bash
mahavishnu config show
```

## Log Analysis

### Log Locations

- Default: Console output
- With logging configured: Specified in logging configuration
- Systemd service: `/var/log/journal/` or via `journalctl`

### Common Log Patterns

Look for these patterns in logs:

- `ERROR` - Critical issues requiring attention
- `WARNING` - Potential problems to investigate
- `CRITICAL` - System-threatening issues

## Reporting Issues

When reporting issues, include:

1. Mahavishnu version
1. Python version
1. Operating system
1. Relevant configuration
1. Steps to reproduce
1. Full error message and traceback
1. Log snippets showing the issue

```bash
# Collect system information
python --version
pip show mahavishnu
uname -a
``
```
