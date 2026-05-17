______________________________________________________________________

title: Secrets Management
owner: Security Guild
last_reviewed: 2025-10-01
supported_platforms:

- macOS
- Linux
  required_scripts: []
  risk: high
  status: active
  id: 01K6HDST4YKZQV8PX3NMWJ7HG2
  category: deployment
  agents:
- security-auditor
- devops-troubleshooter
- architecture-council
- terraform-specialist
  tags:
- secrets
- vault
- aws-secrets-manager
- gcp-secret-manager
- azure-key-vault
- kubernetes
- security

______________________________________________________________________

## Secrets Management

Use this tool to design secure secret storage, access, and rotation patterns.

## Focus areas

- Centralized secret storage
- Encryption in transit and at rest
- Least-privilege access control
- Rotation and rollback
- Audit logging and compliance
- Cloud-native or Vault-based integration

## Workflow

1. Classify the secret types and where they are consumed.
1. Choose the right backend for the platform and operational model.
1. Define app, CI/CD, and Kubernetes access paths.
1. Add rotation and audit requirements.
1. Keep break-glass access explicit and rare.

## Output

- Recommended secret backend
- Access and rotation pattern
- Validation and compliance checklist

## Requirements for: $ARGUMENTS
