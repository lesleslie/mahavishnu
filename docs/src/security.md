# Security

This guide covers security best practices for Mahavishnu.

## Authentication

### JWT Authentication

Enable JWT authentication in your configuration:

```yaml
auth:
  enabled: true
  algorithm: "HS256"
  expire_minutes: 60
  secret: "${MAHAVISHNU_AUTH_SECRET}"
```

Set the secret as an environment variable:

```bash
export MAHAVISHNU_AUTH_SECRET="your-very-long-secret-key-at-least-32-chars"
```

### API Keys

For LLM providers, use environment variables:

```bash
export MAHAVISHNU_LLM_API_KEY="your-llm-api-key"
```

## Configuration Security

### Secrets Management

Never commit secrets to version control. Use environment variables:

```yaml
# settings/mahavishnu.yaml (committed)
auth:
  enabled: true
  algorithm: "HS256"
  expire_minutes: 60
  # Secret comes from environment variable
```

### Path Validation

Mahavishnu validates all paths to prevent directory traversal attacks:

- All repository paths are validated
- Relative paths are resolved to absolute paths
- Directory traversal patterns are blocked

## Network Security

### MCP Server

When exposing the MCP server:

- Use HTTPS/TLS in production
- Restrict network access with firewalls
- Implement rate limiting
- Enable authentication

## Dependency Security

### Vulnerability Scanning

Regularly scan dependencies for vulnerabilities:

```bash
pip-audit
```

### Dependency Updates

Keep dependencies up to date:

```bash
uv pip sync requirements.txt  # If using uv
pip check
```

## Production Security

### Environment Variables

Store sensitive configuration in environment variables:

```bash
# Required in production
export MAHAVISHNU_AUTH_SECRET="your-secret-key"
export MAHAVISHNU_LLM_API_KEY="your-api-key"
export MAHAVISHNU_DB_PASSWORD="your-db-password"
```

### File Permissions

Ensure proper file permissions:

- Configuration files should not be world-readable
- Private keys should have restrictive permissions (600)
- Log files should not contain sensitive information

## Security Monitoring

### Audit Logging

Enable audit logging to track security-relevant events:

```yaml
logging:
  level: INFO
  audit_enabled: true
  sensitive_fields: ["auth_token", "api_key", "password"]
```

### Health Checks

Regularly check system health for security indicators:

```bash
mahavishnu health
``
```
