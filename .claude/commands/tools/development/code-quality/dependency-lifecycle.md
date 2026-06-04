______________________________________________________________________

title: Dependency Lifecycle Management
owner: Platform Engineering Guild
last_reviewed: 2025-10-01
supported_platforms:

- macOS
- Linux
  required_scripts:
- scripts/agent_metadata_audit.py
  risk: medium
  status: active
  id: 01K6EEP8QJFB1XTCXAWQ09YSAB
  category: development/code-quality
  agents:
- python-pro
- javascript-pro
- golang-pro
- security-auditor
  tags:
- dependencies
- security
- vulnerabilities
- automation
- supply-chain

______________________________________________________________________

## Dependency Lifecycle Management

Use this tool to audit, upgrade, and bootstrap dependencies across ecosystems.

## Focus areas

- Vulnerability and license auditing
- Safe upgrades and rollback
- Environment bootstrap and reproducibility
- Multi-ecosystem coverage

## Workflow

1. Detect the ecosystems in the repo.
1. Audit dependencies and flag high-risk findings.
1. Plan upgrades with test and rollback coverage.
1. Keep bootstrap steps reproducible.
1. Automate safe maintenance where it actually helps.

## Output

- Audit or upgrade plan
- Safe-fix and rollback checklist
- Bootstrap guidance

## Inputs

- `$PROJECT_PATH`
- `$MODE`
- `$SEVERITY_THRESHOLD`
- `$ECOSYSTEM`
- `$AUTO_FIX`
