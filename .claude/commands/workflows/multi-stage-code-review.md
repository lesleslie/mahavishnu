---
title: Multi-Stage Code Review
owner: Developer Enablement Guild
last_reviewed: '2026-11-17'
risk: low
status: active
id: 01a1e928ac6a70c8800a16d56c734757
category: workflow
description: Use this workflow for deep review of security, performance, tests, and documentation.
---

______________________________________________________________________

## Multi-Stage Code Review Workflow

Use this workflow for deep review of security, performance, tests, and documentation.

## Focus areas

- Security
- Performance
- Test coverage
- Documentation

## Workflow

1. Run a security review first, applying the `security-finding-gate` skill so every finding carries its evidence and the phase reports true/false-positive counts.
1. Check performance and resource concerns.
1. Verify tests cover the changed behavior.
1. Review public docs and API clarity.
1. Aggregate findings into a single prioritized report.

## Output

- Combined review summary
- Severity-ranked findings
- True/false-positive counts from the security phase
- Recommended next steps
