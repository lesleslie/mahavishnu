______________________________________________________________________

## name: testing-strategies description: Use when designing test suites, choosing testing approaches, or setting quality gates.

# Testing Strategies

## Overview

Use layered testing to build confidence: unit, integration, property-based, and end-to-end.

## When to Use

- Designing a new test suite or testing architecture
- Choosing between unit, integration, property, and E2E tests
- Establishing quality gates, coverage targets, and CI checks
- Testing cross-system interactions or orchestration flows

## Testing Layers

- `unit`: single function or class, fast, isolated, heavily mocked
- `integration`: multiple components or services, medium speed, real dependencies
- `property`: generated input/output invariants, good for contracts and round trips
- `e2e`: full workflow, slowest, best for release confidence

## Practical Guidance

- Keep tests in `tests/unit/`, `tests/integration/`, `tests/property/`, and `tests/e2e/`.
- Use pytest markers to distinguish fast, slow, and network-free tests.
- Prefer reusable fixtures and deterministic inputs.
- Add property-based tests when invariants matter more than one-off examples.

## Commands

- `pytest -m unit -n auto`
- `pytest -m integration`
- `pytest -m property`
- `pytest -m e2e -v`
- `pytest -m "not slow"`
- `pytest -m airgapped`

## Notes

- Use this skill for test strategy and organization, not for writing a single test case.
- Pair it with the repo-specific validation commands in `AGENTS.md` and `CLAUDE.md`.

## Related Skills

- `run-quality-checks`
- `manage-coverage`
- `error-handling`
- `observability`

## Related Documentation

- [pytest Documentation](https://docs.pytest.org/)
- [Hypothesis Docs](https://hypothesis.readthedocs.io/)
- [Crackerjack README](https://github.com/lesleslie/crackerjack)
