# Security Checklist for Mahavishnu

This checklist ensures security best practices are followed during development and deployment of Mahavishnu.

## Pre-Commit Security Checks

- [ ] All API keys and secrets are stored in environment variables, not in code/config files
- [ ] Sensitive configuration files (config.yaml, oneiric.yaml) are added to .gitignore
- [ ] Path validation is implemented to prevent directory traversal attacks
- [ ] Input validation is performed on all user inputs
- [ ] JWT authentication is properly implemented when enabled
- [ ] Secrets are validated for minimum entropy/length requirements

## Configuration Security

- [ ] JWT secrets are at least 32 characters long
- [ ] Authentication is configurable via environment variables
- [ ] Default configurations do not include sensitive information
- [ ] Configuration loading follows the principle of least privilege

## Runtime Security

- [ ] File operations validate paths to prevent directory traversal
- [ ] External resources are accessed securely (HTTPS/TLS where applicable)
- [ ] Error messages do not leak sensitive system information
- [ ] Proper isolation between different workflow executions

## Deployment Security

- [ ] Container images are scanned for vulnerabilities
- [ ] Dependencies are regularly updated and scanned for known vulnerabilities
- [ ] Network access is restricted to necessary ports/services only
- [ ] Secrets management is handled by the platform (Kubernetes secrets, AWS Secrets Manager, etc.)

## Monitoring and Logging

- [ ] Authentication failures are logged for security monitoring
- [ ] Access patterns are monitored for anomalies
- [ ] Audit logs are maintained for compliance purposes
- [ ] Sensitive information is not logged in plaintext

## Incident Response

- [ ] Procedures are defined for rotating compromised secrets
- [ ] Contact information is available for security incidents
- [ ] Rollback procedures are documented and tested
- [ ] Security patches are applied promptly
