______________________________________________________________________

## name: sweep-repositories description: Use when executing a workflow across multiple repositories.

# Sweep Repositories

## Overview

Use this skill to run a workflow across multiple repositories and aggregate the results.

## When to Use

- The user wants to sweep repos by role, tag, or capability
- Coordinated multi-repo execution is needed
- You need aggregated results from several repos

## Core Rule

- Target repositories precisely to minimize failures.

## Quick Reference

- Discover targets: `mahavishnu list-repos`
- Execute sweep: `mahavishnu sweep`
- Check status: `mahavishnu sweep-status`

## Notes

- Preview targets before sweeping.
- Use pools when concurrency or capacity becomes an issue.
