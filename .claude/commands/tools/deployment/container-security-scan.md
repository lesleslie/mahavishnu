______________________________________________________________________

title: Container Security Scan
owner: Delivery Operations
last_reviewed: 2025-02-06
supported_platforms:

- macOS
- Linux
  required_scripts: []
  risk: medium
  status: active
  id: 01K6EEXBKG02QVEGX82SFYMDED
  category: deployment

______________________________________________________________________

## Container Security Scanning

Use this tool to review container images and runtime settings for security issues.

## Focus areas

- Dockerfile and base-image hardening
- Vulnerability and CIS benchmark scanning
- Runtime configuration review
- Layer and package hygiene

## Workflow

1. Inspect the Dockerfile and image build strategy.
1. Scan the image for vulnerabilities and misconfiguration.
1. Review runtime settings, ports, and user context.
1. Prioritize fixes by risk and exploitability.
1. Keep recommendations practical and reproducible.

## Output

- Security findings and risk ranking
- Hardening recommendations
- Scan and verification checklist

## Requirements

$ARGUMENTS
