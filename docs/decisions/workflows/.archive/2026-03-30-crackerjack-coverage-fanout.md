---
status: archived
role: canonical
date: 2026-07-21
last_reviewed: 2026-07-21
topic: workflows
---

# 2026-03-30-crackerjack-coverage-fanout — workflow decision

## Status

Archived

## Context

The original Crackerjack coverage fan-out was created to lift a 6% baseline by assigning parallel test writers to independent, high-leverage zero-coverage modules. The workflow is defined in [crackerjack-coverage-fanout.js](../../../../.claude/workflows/.archive/crackerjack-coverage-fanout.js).

## Decision rule

Use this workflow to establish a fresh coverage baseline and fan out test work across independent Crackerjack packages. It produces targeted tests and a measured post-wave coverage report.

## Status history

- 2026-10-11 — Archived as part of coverage-fanout lifecycle sweep; workflow moved to `.claude/workflows/.archive/`.
- 2026-07-17 — Decision record added for the existing active workflow.
