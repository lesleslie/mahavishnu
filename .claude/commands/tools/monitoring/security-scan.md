______________________________________________________________________

title: Security Scan
owner: Platform Reliability Guild
last_reviewed: 2025-02-06
supported_platforms:

- macOS
- Linux
  required_scripts: []
  risk: medium
  status: active
  id: 01K6EEXCV4ZRSDTB7BSM54R7X8
  category: monitoring

______________________________________________________________________

## Security Scan

Use this tool to find security issues quickly, then expand only the areas that need remediation.

## What to run

- Python: `bandit`, `pip-audit`, `safety`
- JavaScript/TypeScript: `npm audit`, `eslint` security plugins
- Containers: `trivy`, `grype`
- IaC: `checkov`, `tfsec`, `kube-score`
- Secrets: `gitleaks`, `trufflehog`, `detect-secrets`

## Workflow

1. Detect the stack from repo files.
1. Run the smallest scanner set that covers the stack.
1. Save machine-readable output for follow-up.
1. Summarize findings by severity, exploitability, and fix cost.
1. Prefer actionable remediation over long theory.

## Output

- Findings with file, line, severity, and fix guidance
- False positives called out separately
- A short remediation order: secrets, critical vulns, dependency issues, then hardening

## Common defaults

- Do not scan generated caches, backups, or archives.
- Keep shell commands explicit and stack-specific.
- Avoid broad recursive scans unless the user asks for a full audit.

## Requirements

$ARGUMENTS
