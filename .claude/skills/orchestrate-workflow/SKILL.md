______________________________________________________________________

## name: orchestrate-workflow description: Use when coordinating workflows across multiple repositories.

# Orchestrate Workflow

## Overview

Use this skill when you need to run or route a workflow across multiple repositories.

## When to Use

- The user asks to orchestrate or sweep repositories
- The user wants to choose an adapter for a workflow
- The user needs coordinated execution across repos

## Core Rule

- Validate adapter availability and target repos before execution.

## Adapter Notes

- `llamaindex`: production-ready for RAG/document workflows
- `prefect`: workflow orchestration, stubbed
- `agno`: agent workflows, stubbed

## Quick Reference

- Check health: `mahavishnu mcp status`
- Find repos: `mahavishnu list-repos`
- Trigger workflow: `mcp__mahavishnu__trigger_workflow`

## Notes

- Use role/tag filters to avoid broad sweeps.
- Prefer the simplest adapter that fits the task.
