# CLAUDE.md

This file gives high-level guidance for Claude Code in this workspace.
For repo-local editing rules, layout, and validation entry points, see AGENTS.md.

## What Matters

- The repo is organized around `agents/`, `commands/tools/`, and `commands/workflows/`.
- Prefer the workflow catalog when you need help choosing a multi-step process.
- Use specialized agents and tools only when they materially reduce risk or coordination cost.
- Keep changes aligned with the repo-local guidance in `AGENTS.md`.

## Session Notes

- Session startup and status are managed by repo scripts and centralized MCP configuration.
- Settings are intended to stay local and configuration-driven, not hard-coded.
- Runtime verbosity and debug controls are available through dedicated commands.

## Validation

- `python scripts/agent_metadata_audit.py`
- `python scripts/tool_frontmatter_validator.py`

## Decisions

Repo-local decisions and policy live in `.claude/decisions/`. Use this
directory when a non-trivial choice needs to be recorded for future
contributors — typically a policy that future code, frontmatter, or
docs must respect.

**When to add a file here:**

- A change introduces a recurring rule (e.g. "no speculative
  `required_scripts:` entries") that future contributors will need
  to know.
- A reviewer repeatedly has to explain the same tradeoff — write it
  down so the next reviewer doesn't have to.
- A script or frontmatter reference points at something that
  intentionally does not exist, and the reason for the absence
  should not be lost.

**When to use `docs/adr/` instead:** `docs/adr/` is for
architectural decisions — choices that affect the structure or
long-term direction of the system (e.g. "MCP-first design",
"oneiric for config"). Use ADRs when the decision is about *what
to build*; use this directory when the decision is about *how to
operate within the current build*.

**File shape:** one file per topic. A short header (`## Context`,
`## Decision rule`, `## Status`) is enough; full ADR-style structure
is not required. See `removed-scripts.md` for an example.

**Index:** `.claude/decisions/README.md` lists the current files.

## Principles

1. Keep instructions short and specific.
1. Favor reusable files over duplicated guidance.
1. Treat archived or backup content as non-primary context.
1. Preserve the MCP-first structure of the repo.

- **Database Excellence**: Complete coverage (PostgreSQL, MySQL, SQLite, Redis, Vector DBs)
- **Modern Protocols**: WebSocket for real-time + gRPC for high-performance communication
- **AI Integration**: Cutting-edge Gemini AI and vector database specialists
- **Test Optimization**: Advanced test consolidation and refactoring capabilities
- **Enhanced Code Examples**: C, C++, and data engineering agents include production-ready patterns
- **Simplified Structure**: Removed marketplace dependency, cleaned documentation

## Working Style

- **Primary language**: Python
- **Implementation work** (algorithms, data structures, refactoring): Show reasoning through code — sketches, examples, tests — then summarize.
- **Architecture work** (design, trade-offs, requirements): Lead with written analysis before proposing code.

## Usage Guidelines

- **Take the time to do things right the first time**: Quality > speed. Proper implementation prevents technical debt and future refactoring cycles.
- **Check yourself before you wreck yourself**: Always validate your work before considering it complete. Run quality checks, verify dependencies, and ensure architectural compliance. Don't wait for quality gates to catch mistakes you could have prevented.
- Always use the appropriate agents/tools/workflows for the job at hand
- Always be honest with answers - do not embellish on progress
- Always clean up after yourself
- Always use IDE diagnostics to validate code after implementation if available
- Query and use custom agents on a regular basis when appropriate
- Make as few edits as possible by batching related changes together
- Always put implementation plans in a markdown document for review and reference
- Think when you need to think, think harder when you need to think harder

## Summary

This repository represents a comprehensive AI-assisted development environment with:

- **98 total agents** (100% active, zero deprecated; 3 retired agents live in `.claude/agents/.archive/`)
- **49 active development tools** (100% active, zero deprecated)
- **18 production-ready workflows** (100% active, zero deprecated)
- **15 MCP servers** providing enhanced capabilities
- **92/100 quality score** (industry-leading)

The ecosystem covers every aspect of modern software development from simple scripts to enterprise-scale systems, with zero critical gaps and world-class specialist coverage.

**Key Advantage**: Your entire agent ecosystem (98 specialists + 67 tools/workflows) is just **3.2MB** of plain text files that work perfectly without any marketplace or plugin dependencies!
