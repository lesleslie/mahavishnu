______________________________________________________________________

## name: ecosystem-awareness description: Use when discovering available repositories, roles, and capabilities.

# Ecosystem Awareness

## Overview

Use this skill to discover the current repository ecosystem and cache the result for later reuse.

## When to Use

- Starting a new session
- First Mahavishnu MCP call in a session
- The user asks what repos or capabilities are available

## Core Rule

- Discover once, cache the map, then validate incrementally.

## Quick Reference

- List repos: `mcp__mahavishnu__list_repos`
- Check health: `mcp__mahavishnu__get_health`

## Notes

- Cache role, tag, and repo indexes in memory or local notes.
- Rebuild the cache when repo counts or names change.
