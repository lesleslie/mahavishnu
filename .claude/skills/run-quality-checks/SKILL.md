---
name: run-quality-checks
description: Use when running Crackerjack quality gates or executing Python code quality checks. Use when user asks to check code quality, run tests, lint code, or validate Python projects. Use for AI-assisted issue fixing with Crackerjack agents.
---

# Run Quality Checks

## Overview

## Available MCP Servers

| Server | Port | Context Mode | Relevant Tools | Default Timeout |
|--------|------|-------------|---------------|----------------|
| crackerjack | 8676 | summary | mcp__crackerjack__crackerjack_run, mcp__crackerjack__get_comprehensive_status, mcp__crackerjack__smart_error_analysis | 120s |
| mahavishnu | 8680 | grep | mcp__mahavishnu__get_health | 60s |

Crackerjack provides unified quality enforcement through 11 concurrent adapters. This skill guides you through running quality gates, interpreting results, and leveraging AI-powered auto-fixing.

**Core principle:** Run quality checks early and often, using AI agents to fix issues automatically before they become technical debt.

## When to Use

**Use when:**
- User asks to "check code quality", "run quality gates", "validate code"
- Before committing code or creating pull requests
- After implementing features or bug fixes
- Setting up quality enforcement for new projects
- Fixing quality issues with AI assistance

**Don't use when:**
- Manual code formatting (use IDE or `ruff format` directly)
- Running specific test suites without quality gates
- Non-Python projects (Crackerjack is Python-specific)

## Crackerjack Architecture

**11 Concurrent Adapters (Parallel Execution):**

| Category | Adapters | Purpose |
|----------|----------|---------|
| **Format** | black, ruff format | Code formatting |
| **Import** | isort, ruff imports | Import sorting |
| **Lint** | flake8, ruff lint | Code quality |
| **Type** | mypy, pyright | Type checking |
| **Security** | bandit, safety | Security scanning |
| **Complexity** | complexipy, radon | Cyclomatic complexity |
| **Test** | pytest, pytest-cov | Test execution |
| **Docs** | pydocstyle | Documentation style |
| **Refactor** | refurb | Modern Python patterns |

**Key Advantage:** All adapters run concurrently (not sequentially), providing results in seconds rather than minutes.

## Quick Reference

```bash
# Run all quality checks
crackerjack run

# Run with AI auto-fix enabled
crackerjack run --ai-fix

# Run specific checks only
crackerjack run --check ruff
crackerjack run --check pytest
crackerjack run --check bandit

# Run with coverage
crackerjack run --run-tests --cov

# Check quality status
crackerjack status

# View execution history
crackerjack history
```

## Implementation

### Step 1: Run Quality Checks

**Basic execution:**
```bash
crackerjack run
```

**What happens:**
1. Discovers project configuration (pyproject.toml, setup.cfg, .crackerjack.toml)
2. Runs all 11 adapters concurrently
3. Collects and aggregates results
4. Displays summary with pass/fail status
5. Exits with non-zero if any checks fail

**Via MCP:**
```python
# Run quality checks via MCP server
result = await mcp.call_tool("mcp__crackerjack__execute_crackerjack", {})

# Result includes:
# - Overall status (pass/fail)
# - Per-adapter results
# - Issues found
# - Suggestions for fixes
```

### Step 2: Interpret Results

**Result format:**
```
✅ Format (black, ruff) - PASSED
✅ Import (isort, ruff) - PASSED
❌ Lint (flake8, ruff) - FAILED
   - module.py:42: E501 Line too long (85 > 79)
   - module.py:55: E203 Whitespace before ':'
✅ Type (mypy) - PASSED
⚠️  Security (bandit) - WARNINGS
   - module.py:100: assert_detected: Use of assert detected
✅ Test (pytest) - PASSED (32/32 tests)
   - Coverage: 87.3%
```

**Status meanings:**
- ✅ **PASSED** - All checks in category passed
- ❌ **FAILED** - Critical failures, must fix
- ⚠️ **WARNINGS** - Non-critical issues, should fix
- 🔒 **SKIPPED** - Adapter not configured for project

### Step 3: AI Auto-Fix (Recommended)

**Enable AI fixing:**
```bash
crackerjack run --ai-fix
```

**How it works:**
1. Run quality checks normally
2. Identify fixable issues
3. Dispatch to specialized AI agents:
   - **RefactoringAgent** - Code structure and modernization
   - **SecurityAgent** - Security vulnerabilities
   - **PerformanceAgent** - Performance optimization
   - **TestAgent** - Test generation and improvement
   - **DocumentationAgent** - Documentation enhancement
4. Apply fixes automatically
5. Re-run checks to verify

**AI Agent Capabilities:**

| Agent | Fixes | Example |
|-------|-------|---------|
| RefactoringAgent | Code structure, modernization | Convert to f-strings, use dataclasses |
| SecurityAgent | Security vulnerabilities | SQL injection, XSS, hardcoded secrets |
| PerformanceAgent | Performance issues | Inefficient loops, missing caching |
| TestAgent | Test coverage | Generate missing tests, improve assertions |
| DocumentationAgent | Documentation | Add docstrings, improve comments |

### Step 4: Specific Check Execution

**Run only specific adapters:**
```bash
# Linting only
crackerjack run --check ruff --check flake8

# Type checking only
crackerjack run --check mypy

# Security scanning only
crackerjack run --check bandit --check safety

# Testing only
crackerjack run --check pytest
```

**Via MCP:**
```python
# Get available skills for issue type
skills = await mcp.call_tool("mcp__crackerjack__get_skills_for_issue", {
    "issue_type": "complexity"
})

# Execute specific skill
result = await mcp.call_tool("mcp__crackerjack__execute_skill", {
    "skill_id": skills[0]["id"],
    "issue_type": "complexity",
    "issue_data": {
        "message": "Function has complexity 18 (max 15)",
        "file_path": "module.py"
    }
})
```

### Step 5: Coverage Management

**Run with coverage:**
```bash
crackerjack run --run-tests --cov
```

**Coverage ratchet:**
```toml
# pyproject.toml
[tool.crackerjack]
coverage_ratchet = true
min_coverage = 80  # Fail if coverage below 80%
```

**Result:**
```
✅ Test (pytest) - PASSED (32/32 tests)
   - Coverage: 87.3% (↑ from 85.1%)
   - Ratchet: ✅ Above minimum (80%)
```

## Quality Gates

**Pre-commit gate:**
```bash
# Runs fast checks only (no slow tests)
crackerjack run --fast
```

**CI/CD gate:**
```bash
# Full quality suite
crackerjack run --all
```

**Release gate:**
```bash
# Complete validation including packaging
crackerjack run --all patch
```

## Common Mistakes

| Mistake | Symptom | Fix |
|---------|---------|-----|
| **Running checks manually** | Slow, inconsistent execution | Use `crackerjack run` for unified execution |
| **Not using AI auto-fix** | Manual fixing takes hours | Enable `--ai-fix` for automatic fixes |
| **Ignoring coverage ratchet** | Coverage regresses over time | Enable `coverage_ratchet` in configuration |
| **Running adapters sequentially** | 5-10 minute execution time | Crackerjack runs adapters concurrently |
| **Fixing symptoms not root causes** | Same issues recur | Use AI agents to identify and fix root causes |

## Real-World Impact

**Before this skill:**
- Manual quality checks → 5-10 minutes execution
- No AI fixing → hours of manual work
- Inconsistent checks → quality gaps

**After this skill:**
- Unified execution → 30-60 seconds
- AI auto-fix → 80% reduction in manual work
- Consistent enforcement → zero quality gaps

## Example Workflows

**Before Commit:**
```bash
# 1. Run quality checks
crackerjack run

# 2. If failed, fix with AI
crackerjack run --ai-fix

# 3. Commit only when passing
git commit -m "feat: add feature"
```

**CI/CD Pipeline:**
```yaml
# .github/workflows/quality.yml
- name: Run Crackerjack
  run: crackerjack run --all

- name: AI Fix (if failed)
  if: failure()
  run: crackerjack run --ai-fix
```

**New Project Setup:**
```bash
# 1. Create project
crackerjack init myproject

# 2. Run quality checks
crackerjack run

# 3. Fix any issues with AI
crackerjack run --ai-fix
```

## Quality Metrics

**Crackerjack enforces these standards:**

| Metric | Threshold | Enforced By |
|--------|-----------|-------------|
| Test Coverage | ≥80% (configurable) | pytest-cov |
| Cyclomatic Complexity | ≤15 per function | complexipy, radon |
| Line Length | ≤88 characters (Black) | black, ruff |
| Type Safety | Strict mode | mypy |
| Security | Zero high-severity issues | bandit, safety |

## Related Skills

- **REQUIRED:** `superpowers:test-driven-development` - Write tests before code
- **REQUIRED:** `superpowers:verification-before-completion` - Validate before claiming work done
- `persistent-state` — Durable storage for quality metrics and adapter performance data (time-series tracking)
- `learn-from-errors` - Error learning after fixes (quality checks often surface errors that trigger this skill)

## Related Documentation

- [Crackerjack README](https://github.com/lesleslie/crackerjack) - Complete documentation
- [Adapter Architecture](docs/adapters/) - 11 concurrent adapters
- [AI Agents](docs/agents/) - Specialized agent capabilities
