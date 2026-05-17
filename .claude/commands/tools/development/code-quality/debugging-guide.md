______________________________________________________________________

title: Comprehensive Debugging Guide
owner: Platform Reliability Guild
last_reviewed: 2025-10-01
supported_platforms:

- macOS
- Linux
- Windows
  agents:
- devops-troubleshooter
- python-pro
- javascript-pro
- golang-pro
- rust-pro
- observability-incident-lead
  required_scripts: []
  risk: low
  status: active
  id: 01K6H7DBKXPATNET8YV0JQGZX7
  category: development
  tags:
- debugging
- troubleshooting
- observability
- performance
- production

______________________________________________________________________

## Comprehensive Debugging Guide

Use this tool to debug issues systematically from local repro to production incidents.

## Focus areas

- Reproduce, isolate, and document the issue
- Form and test hypotheses one at a time
- Gather logs, metrics, traces, and state
- Validate fixes with targeted regression checks
- Capture prevention and follow-up notes

## Workflow

1. Observe the symptom and define the expected behavior.
1. Reproduce the issue in the smallest reliable setup.
1. Test one change at a time and collect evidence.
1. Fix the root cause, then verify the regression is gone.
1. Record the lesson in a runbook or troubleshooting note.

## Output

- Root cause summary
- Evidence-backed fix or mitigation
- Prevention recommendations

## Inputs

- `$ISSUE_DESCRIPTION`
- `$ENVIRONMENT`
- `$STACK`
- `$REPRODUCTION_STEPS`
