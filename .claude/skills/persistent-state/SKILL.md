______________________________________________________________________

## name: persistent-state description: Use when state must survive beyond the current session.

# Persistent State

## Overview

Use durable storage when state needs to outlive the current session.

## When to Use

- Persisting config or cached results
- Tracking metrics over time
- Looking up, validating, or registering adapters
- Recording service lifecycle events

## Core Rule

- If the state matters later, persist it.
- If it is only useful now, keep it in memory.

## Quick Reference

- Key-value: `mcp__dhara__put`, `mcp__dhara__get`
- Time-series: `mcp__dhara__record_time_series`, `mcp__dhara__query_time_series`, `mcp__dhara__aggregate_patterns`
- Adapter registry: `mcp__dhara__list_adapters`, `mcp__dhara__get_adapter`, `mcp__dhara__validate_adapter`, `mcp__dhara__get_adapter_health`
- Service lifecycle: `mcp__dhara__record_event`, `mcp__dhara__list_services`, `mcp__dhara__get_service`

## Notes

- Use a TTL for temporary state.
- Validate adapters before critical use.
- Prefer a concise key scheme like `{domain}:{entity}:{identifier}:{field}`.
