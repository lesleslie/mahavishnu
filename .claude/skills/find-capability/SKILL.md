______________________________________________________________________

## name: find-capability description: Use when discovering which repository has the needed capability.

# Find Capability

## Overview

Use this skill to find the best repository for a task using role, tag, and capability metadata.

## When to Use

- The user asks which repo handles a feature
- The user needs a repo by capability or domain
- You do not yet know which repo should own the work

## Core Rule

- Query by role first, then narrow by tags and capabilities.

## Quick Reference

- List repos: `mahavishnu list-repos`
- List roles: `mahavishnu list-roles`
- Show role: `mahavishnu show-role`
- Search via MCP: `mcp__mahavishnu__list_repos`

## Notes

- If the repo is already known, use the relevant workflow instead.
- Prefer metadata queries over guesswork.
