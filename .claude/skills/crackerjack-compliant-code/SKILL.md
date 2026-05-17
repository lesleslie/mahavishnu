______________________________________________________________________

## name: crackerjack-compliant-code description: Use when writing Python code that should pass quality gates on the first run.

# Crackerjack-Compliant Code

## Overview

Use these rules before writing or modifying Python code so it passes the main quality gates without a fix loop.

## Core Rules

- Add `from __future__ import annotations` as the first non-comment line.
- Keep imports ordered: stdlib, third-party, first-party.
- Use full type annotations on all functions.
- Prefer modern Python syntax like `X | None`, `list[str]`, and `pathlib.Path`.
- Avoid `assert` in production code.
- Keep functions small and refactor when complexity rises.

## Quality Limits

- Line length: 100 chars
- Function complexity: 15
- Parameters: 10
- Return points: 6
- Statements: 55

## Quick Checks

- Run `crackerjack run`
- Fix lint, type, security, and complexity issues before committing

## Notes

- Prefer explicit errors over assertions.
- Remove unused imports and dead code immediately.
