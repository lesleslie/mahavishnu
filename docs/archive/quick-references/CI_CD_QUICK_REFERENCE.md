# CI/CD Quick Reference

Fast reference for CI/CD workflows and common tasks.

## Workflows at a Glance

| Workflow | What It Does | When It Runs | Duration |
|----------|--------------|--------------|----------|
| **Phase 6 Tests** | Unit, integration, adapter, CLI, E2E tests | Push, PR, manual | 5-10 min |
| **Build Documentation** | Validate and build docs, examples | Push to main, PR, manual | 3-5 min |
| **Security Scan** | Vulnerability scan, code quality, type check | Push, PR, daily (2 AM UTC) | 7-10 min |
| **Performance Benchmark** | Benchmarks, load tests, health checks | Push, PR, weekly (Sun 3 AM UTC) | 15-20 min |

## Quick Start

### 1. Update Badges in README

Replace `yourusername` with your actual GitHub username:

```bash
sed -i '' 's/yourusername/YOUR_USERNAME/g' README.md
```

### 2. Commit and Push

```bash
git add .github/workflows/ docs/CI_CD*.md README.md
git commit -m "feat: Add CI/CD workflows for Phase 6"
git push origin main
```

### 3. Monitor First Run

Go to **Actions** tab in GitHub and monitor workflow execution.

## Status Badges

Add these to your README:

```markdown
[![Phase 6 Tests](https://github.com/YOUR_USERNAME/mahavishnu/actions/workflows/test-phase6.yml/badge.svg)](https://github.com/YOUR_USERNAME/mahavishnu/actions/workflows/test-phase6.yml)
[![Build Documentation](https://github.com/YOUR_USERNAME/mahavishnu/actions/workflows/build-docs.yml/badge.svg)](https://github.com/YOUR_USERNAME/mahavishnu/actions/workflows/build-docs.yml)
[![Security Scan](https://github.com/YOUR_USERNAME/mahavishnu/actions/workflows/security-scan.yml/badge.svg)](https://github.com/YOUR_USERNAME/mahavishnu/actions/workflows/security-scan.yml)
[![Performance Benchmark](https://github.com/YOUR_USERNAME/mahavishnu/actions/workflows/benchmark.yml/badge.svg)](https://github.com/YOUR_USERNAME/mahavishnu/actions/workflows/benchmark.yml)
```

## Common Commands

### Running Tests Locally

```bash
# Unit tests
pytest tests/unit/ -m "unit" --cov=mahavishnu

# Integration tests
pytest tests/integration/ -m "integration"

# E2E tests
pytest tests/integration/ -m "e2e" --timeout=600

# All tests
pytest
```

### Security Scanning

```bash
# Dependency vulnerabilities
safety check

# Code security
bandit -r mahavishnu/ --exclude tests/

# Linting
ruff check mahavishnu/

# Formatting
ruff format --check mahavishnu/

# Type checking
mypy mahavishnu/
```

### Performance Testing

```bash
# Benchmarks
pytest tests/unit/test_adapters/ -k "benchmark" --benchmark-only

# Load test
python -c "
import asyncio
import time
from mahavishnu.core.app import MahavishnuApp

async def load_test():
    app = MahavishnuApp()
    await app.initialize()

    start = time.time()
    tasks = [app.list_repos() for _ in range(100)]
    await asyncio.gather(*tasks)
    duration = time.time() - start

    print(f'100 concurrent operations: {duration:.2f}s')
    print(f'Operations per second: {100/duration:.2f}')

asyncio.run(load_test())
"
```

## Workflow Triggers

### Automatic

- **Push to main/develop**: All workflows run
- **Pull Request**: All workflows run for validation
- **Daily at 2 AM UTC**: Security scan
- **Weekly Sunday 3 AM UTC**: Performance benchmarks

### Manual

1. Go to **Actions** tab
2. Select workflow
3. Click **Run workflow**
4. Select branch and parameters
5. Click **Run workflow**

### Commit Message Triggers

- **E2E Tests**: Add `[e2e]` to commit message

## Quality Gates

| Gate | Tool | Threshold |
|------|------|-----------|
| Test Coverage | pytest-cov | 80% minimum |
| Code Quality | Ruff | 0 errors |
| Type Checking | mypy | Strict mode |
| Complexity | Complexipy | Max 15 |
| Security | Safety/Bandit | 0 critical |

## Secrets (Optional)

Configure in **Settings** → **Secrets and variables** → **Actions**:

| Secret | Description | Required |
|--------|-------------|----------|
| `CODECOV_TOKEN` | Codecov upload token | Optional |
| `SLACK_WEBHOOK` | Slack webhook for notifications | Optional |

## Troubleshooting

### Tests Fail in CI but Pass Locally

```bash
# Check Python version
python --version  # Should be 3.13

# Run with same configuration
pytest tests/unit/ -m "unit" --cov=mahavishnu --cov-report=xml
```

### Security Scan Failures

```bash
# Run locally
bandit -r mahavishnu/ --exclude tests/

# Fix issues
ruff check mahavishnu/ --fix
```

### Performance Regression

```bash
# Run benchmarks
pytest tests/unit/test_adapters/ -k "benchmark" --benchmark-only

# Compare with baseline
pytest tests/unit/test_adapters/ -k "benchmark" --benchmark-only --benchmark-autosave
```

## Artifacts

Download workflow artifacts from Actions tab:

| Artifact | Retention | Location |
|----------|-----------|----------|
| Coverage reports | 7 days | Workflow run → Artifacts |
| Benchmark results | 30 days | Workflow run → Artifacts |
| Security reports | 30 days | Workflow run → Artifacts |
| Code quality reports | 7 days | Workflow run → Artifacts |

## Local Testing with Act

Test workflows locally before pushing:

```bash
# Install act
brew install act

# List jobs
act -l

# Run push event jobs
act push

# Run specific workflow
act -W .github/workflows/test-phase6.yml push
```

## Branch Protection

Configure in **Settings** → **Branches**:

1. Add rule for `main` branch
2. Enable:
   - ✅ Require status checks to pass
   - ✅ Require branches to be up to date
   - ✅ Require PR reviews
3. Add required status checks:
   - Phase 6 Tests (unit-tests)
   - Security Scan
   - Build Documentation

## Notification Setup

### Email

1. Go to **Settings** → **Notifications**
2. Enable:
   - ✅ Send email notifications for workflow runs
   - ✅ Notify me on failures

### Slack (Optional)

Create `.github/workflows/notify.yml`:

```yaml
name: Notify Slack

on:
  workflow_run:
    workflows: ["Phase 6 Tests", "Security Scan"]
    types: [completed]
    statuses: [failure]

jobs:
  notify:
    runs-on: ubuntu-latest
    if: ${{ github.event.workflow_run.conclusion == 'failure' }}
    steps:
      - name: Send Slack notification
        uses: 8398a7/action-slack@v3
        with:
          status: ${{ job.status }}
          text: 'Workflow failed!'
          webhook_url: ${{ secrets.SLACK_WEBHOOK }}
```

## Documentation

- [CI/CD Guide](CI_CD_GUIDE.md) - Comprehensive usage guide
- [CI/CD Setup](CI_CD_SETUP.md) - Step-by-step setup instructions
- [CI/CD Summary](CI_CD_SUMMARY.md) - Implementation summary

## Support

For issues:
1. Check workflow logs in Actions tab
2. Review troubleshooting section
3. Open an issue with `ci/cd` label
4. Include workflow run link and error logs

______________________________________________________________________

**Last Updated**: 2026-02-05
**Maintained By**: Mahavishnu DevOps Team
