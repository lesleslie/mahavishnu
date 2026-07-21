---
status: active
role: canonical
date: 2026-07-21
last_reviewed: 2026-07-21
topic: workflows
---

# 2026-04-12-crackerjack-coverage-fanout-wave2 — workflow decision

## Status

Active

## Context

Wave 2 followed the first Crackerjack coverage pass at roughly 67% coverage. It assigned parallel test writers to the next-highest-leverage packages and included a dedicated agent to repair regressions introduced by wave 1. The workflow is defined in [crackerjack-coverage-fanout-wave2.js](../../workflows/crackerjack-coverage-fanout-wave2.js).

## Decision rule

Use this workflow after the original coverage fan-out when the next package tier remains under-tested or wave-1 regressions need isolation. It produces targeted tests, regression repairs, and a verified coverage delta.

## Status history

- 2026-07-17 — Decision record added for the existing active workflow.
