# 2026-06-12-mahavishnu-coverage-fanout — workflow decision

## Status

Active

## Context

Wave-1 (2026-06-12) of the mahavishnu coverage fan-out. Fanned out one test-writing agent per high-leverage module in parallel using per-agent `.cov_<module>.qual` files to avoid parallel pytest race conditions. Covered 8 high-value modules totaling 7,302 source lines that had no test file or a very low test:source ratio. Average coverage of the targeted modules landed at ~94.7%.

## Decision rule

Re-run this workflow (or its part-2 sibling) when mahavishnu overall coverage drops below 80%, or when a new high-leverage module lands without a test file. Expect ~45-min wall-clock; uses 8 parallel python-pro agents, each writing tests for a single module.

## Status history

- 2026-06-12 — Created.
