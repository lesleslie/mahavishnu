______________________________________________________________________

title: Comprehensive Test Harness & Advanced Testing Strategies
owner: Quality Engineering Guild
last_reviewed: 2025-10-01
supported_platforms:

- macOS
- Linux
- Windows
  agents:
- qa-strategist
- python-pro
- javascript-pro
- golang-pro
- observability-incident-lead
  required_scripts:
- scripts/test_matrix.py
  risk: medium
  status: active
  id: 01K6EEQRQ3BDHZ1H0CJT2XC8S7
  category: development/testing
  tags:
- testing
- qa
- automation
- chaos-engineering
- property-based-testing
- contract-testing

______________________________________________________________________

## Comprehensive Test Harness

Use this tool to design a test stack that matches the repo’s language, risk, and coverage needs.

## Focus areas

- Fixture and factory design
- Unit, integration, property-based, and E2E coverage
- Contract, chaos, and mutation testing when justified
- CI integration and coverage thresholds
- Deterministic test data and cleanup

## Workflow

1. Identify the stack and main test risks.
1. Choose the smallest useful mix of test layers.
1. Add shared fixtures and helpers before expanding suites.
1. Wire in coverage, reporting, and CI execution.
1. Document what should be mocked, real, or property-based.

## Output

- Test architecture recommendation
- Example fixture patterns
- CI and coverage checklist

## Requirements

- Testing framework for your stack
- CI/CD pipeline for automated execution
- Access to a test environment
- Basic testing familiarity

## Inputs

- `$PROJECT_PATH`
- `$STACK`
- `$TEST_TYPES`
- `$COVERAGE_TARGET`
