# Workflow Improvements for Session Optimization

## Quick Actions Added

### 1. Pre-commit Hook Template
```yaml
# .pre-commit-config.yaml
repos:
  - repo: local
    hooks:
      - id: ruff
        name: Run Ruff linter
        entry: ruff check --force-exclude
        language: system
  - repo: local
    hooks:
      - id: ruff-format
        name: Run Ruff formatter
        entry: ruff format --force-exclude
        language: system
  - repo: local
    hooks:
      - id: pytest-quick
        name: Quick smoke tests
        entry: pytest tests/unit/ -x -v
        language: system
```

### 2. Test Runner Script
```bash
#!/bin/bash
# quick-test.sh
echo "Running quick test suite..."
pytest tests/unit/ -x --tb=short -q "$@"
```

### 3. Commit Template
```bash
#!/bin/bash
# smart-commit.sh
echo "📝 Smart Commit Helper"
echo "Current changes:"
git status --short
echo ""
echo "Commit type (feat/fix/test/docs/chore/refactor):"
read -r commit_type
echo "Short description:"
read -r description
git add -A
git commit -m "$commit_type: $description

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

## MCP Tool Optimization

### Current Tool Usage
- Mahavishnu MCP: 🟢 Active (localhost:8680)
- Session-Buddy: 🟢 Active (localhost:8678)
- Crackerjack: 🟢 Active (localhost:8676)
- Akosha: 🟢 Active (localhost:8682)

### Optimization Recommendations
1. Reduce MCP server startup time
2. Cache frequently-accessed tools
3. Batch similar operations
4. Use async tool calls where possible

## Context Management

### Compaction Triggers
- After 80K tokens used
- After large file operations
- Before major code reviews

### Checkpoint Intervals
- After completing features
- After fixing tests
- Every 10 file modifications

### Cleanup Automation
- Auto-remove temporary files
- Clean cache on checkpoint
- Archive old session logs

## Workflow Shortcuts

### Common Operations
```bash
# Quick test run
pytest tests/unit/ -x -q

# Format code
ruff format .

# Lint code  
ruff check .

# Type check
mypy mahavishnu/

# Run specific test
pytest tests/unit/test_file.py::test_func -v

# Check coverage
pytest --cov=mahavishnu --cov-report=html
```

### Git Hygiene
```bash
# Interactive staging
git add -i

# Atomic commits
git commit -m "type: scope: message"

# Clean branches
git branch -d $(git branch --merged | grep -v main)

# Prune remote
git remote prune origin
```

