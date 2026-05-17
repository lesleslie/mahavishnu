______________________________________________________________________

## name: code-knowledge-builder description: Use when exploring code or making significant edits.

# Code Knowledge Builder

## Overview

Use this skill to keep the Session-Buddy knowledge graph current when you are exploring unfamiliar code or making substantial changes.

## When to Use

- Starting work in a new module or package area
- Making a significant refactor or new adapter
- Reasoning about an interface, protocol, or base class
- Answering "how does this code work?" for unfamiliar code

## Quick Reference

- Check project tracking: `code_list_projects()`
- Search symbols: `code_search_symbols(...)`
- Inspect relationships: `code_get_symbol_graph(...)`
- Re-ingest changed files: `code_ingest_file(...)`
- Capture decisions: `create_entity(...)` and `create_relation(...)`

## Rules

- Ingest only meaningful changes, not trivial formatting or config edits.
- Prefer symbol search before reading large files.
- Record design decisions when a tradeoff matters.
- Avoid duplicate knowledge entries when an existing one already covers the topic.
