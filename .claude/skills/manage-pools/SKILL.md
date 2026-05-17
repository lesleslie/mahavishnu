______________________________________________________________________

## name: manage-pools description: Use when spawning, scaling, routing, or closing Mahavishnu worker pools.

# Manage Pools

## Overview

Use this skill to select and manage worker pools for horizontal scaling.

## When to Use

- Spawning a pool
- Scaling an existing pool
- Routing tasks to a pool
- Checking pool health

## Core Rule

- Choose the pool type based on the deployment scenario, then scale for workload.

## Pool Types

- `MahavishnuPool`: local development and debugging
- `SessionBuddyPool`: distributed workloads
- `KubernetesPool`: production and auto-scaling

## Quick Reference

- Spawn: `mahavishnu pool spawn`
- List: `mahavishnu pool list`
- Route: `mahavishnu pool route`
- Scale: `mahavishnu pool scale`
- Health: `mahavishnu pool health`
- Close: `mahavishnu pool close`

## Notes

- Prefer auto-routing for general use.
- Use `manage-pools` instead of ad hoc worker calls when work can be batched.
