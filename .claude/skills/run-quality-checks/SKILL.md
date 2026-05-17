______________________________________________________________________

## name: run-quality-checks description: Use when running Crackerjack quality gates or Python quality checks.

# Run Quality Checks

## Overview

Use this skill to run quality gates, inspect results, and apply AI-assisted fixes when appropriate.

## When to Use

- Before committing code or opening a PR
- After a feature or bug fix
- When validating Python code quality
- When you need Crackerjack-based auto-fixing

## Core Checks

- Format
- Import sorting
- Linting
- Type checking
- Security scanning
- Complexity checks
- Tests and coverage

## Quick Reference

- Run all: `crackerjack run`
- Auto-fix: `crackerjack run --ai-fix`
- Status: `crackerjack status`
- History: `crackerjack history`

## Notes

- Prefer the shortest run that still validates the change.
- Use AI fix only after the failing checks are understood.
