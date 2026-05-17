______________________________________________________________________

## name: learn-from-errors description: Use when a bug or test failure should be recorded for future reuse.

# Learn From Errors

## Overview

Use this skill after fixing an error so the solution can be found again later.

## When to Use

- After fixing a failing test
- After resolving a runtime or build error
- After applying a quality-tool fix

## Core Rule

- Query similar errors first, then record the fix.

## Quick Reference

- Search: `mcp__session-buddy__query_similar_errors`
- Store fix: `mcp__session-buddy__record_fix_success`
- Add knowledge: `mcp__session-buddy__create_entity`
- Link error to fix: `mcp__session-buddy__create_relation`

## Notes

- Skip trivial fixes and flaky reruns.
- Record only non-trivial errors that are worth finding later.
