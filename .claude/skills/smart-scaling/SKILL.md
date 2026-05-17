______________________________________________________________________

## name: smart-scaling description: Use when repeated worker calls should become a pool-based batch.

# Smart Scaling

## Overview

Use this skill when repeated worker or pool calls should be consolidated into a pool-based approach.

## When to Use

- 3+ sequential worker calls without a pool
- Manual pool selection across several tasks
- Repeated individual executions that could be batched

## Core Rule

- If you are running 3+ workers, use a pool.

## Quick Reference

- Spawn pool: `mcp__mahavishnu__pool_spawn`
- Route tasks: `mcp__mahavishnu__pool_route_execute`
- Check health: `mcp__mahavishnu__pool_health`
- Scale pool: `mcp__mahavishnu__pool_scale`
- Close pool: `mcp__mahavishnu__pool_close`

## Notes

- Recommend pool routing when the pattern repeats.
- Prefer `least_loaded` for general task distribution.
