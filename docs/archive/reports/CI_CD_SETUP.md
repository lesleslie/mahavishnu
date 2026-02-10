# CI/CD Setup Instructions

This guide walks you through setting up CI/CD for the Mahavishnu project from scratch.

## Prerequisites

- GitHub repository with admin access
- GitHub Actions enabled for repository
- Python 3.11+ installed locally
- Basic understanding of Git and GitHub

## Step 1: Repository Setup

### 1.1 Create GitHub Repository

If you haven't already:

```bash
# Create repository on GitHub
# Then clone it locally
git clone https://github.com/yourusername/mahavishnu.git
cd mahavishnu
```

### 1.2 Enable GitHub Actions

1. Go to repository **Settings**
2. Click **Actions** → **General**
3. Under **Actions permissions**, select:
   - ✅ Allow all actions and reusable workflows
4. Click **Save**

### 1.3 Configure Branch Protection

1. Go to **Settings** → **Branches**
2. Click **Add branch protection rule**
3. Configure:
   - Branch name pattern: `main`
   - ✅ Require status checks to pass before merging
   - ✅ Require branches to be up to date before merging
   - Required status checks:
     - Phase 6 Tests (unit-tests)
     - Security Scan
     - Build Documentation
   - ✅ Require pull request reviews before merging
   - Required approving reviews: 1
4. Click **Create**

## Step 2: Add Workflow Files

### 2.1 Create Workflow Directory

```bash
mkdir -p .github/workflows
```

### 2.2 Copy Workflow Files

Copy these workflow files to `.github/workflows/`:
- `test-phase6.yml`
- `build-docs.yml`
- `security-scan.yml`
- `benchmark.yml`

```bash
# From this repository
cp .github/workflows/*.yml /path/to/your/repo/.github/workflows/
```

### 2.3 Validate Workflow Syntax

```bash
# Install act (local GitHub Actions runner)
brew install act  # macOS
# or
brew install act  # Linux

# Test workflows locally
act -l  # List jobs
act push  # Run push event jobs
```

## Step 3: Configure Secrets

### 3.1 Add Repository Secrets

1. Go to **Settings** → **Secrets and variables** → **Actions**
2. Click **New repository secret**
3. Add the following secrets:

#### Optional Secrets

| Secret | Description | Required |
|--------|-------------|----------|
| `CODECOV_TOKEN` | Codecov upload token | Optional |
| `SLACK_WEBHOOK` | Slack webhook for notifications | Optional |

#### Getting Codecov Token

1. Sign up at https://codecov.io
2. Add your repository
3. Get token from repository settings
4. Add to GitHub secrets

#### Getting Slack Webhook

1. Create Slack app at https://api.slack.com/apps
2. Enable Incoming Webhooks
3. Create webhook URL
4. Add to GitHub secrets

### 3.2 Configure Environment Variables

No environment variables required by default. Workflows use:
- `PYTHON_VERSION: '3.13'` - Can be changed in workflow files

## Step 4: Update README with Badges

### 4.1 Add Status Badges

Add these badges to the top of your `README.md`:

```markdown
[![Phase 6 Tests](https://github.com/yourusername/mahavishnu/actions/workflows/test-phase6.yml/badge.svg)](https://github.com/yourusername/mahavishnu/actions/workflows/test-phase6.yml)
[![Build Documentation](https://github.com/yourusername/mahavishnu/actions/workflows/build-docs.yml/badge.svg)](https://github.com/yourusername/mahavishnu/actions/workflows/build-docs.yml)
[![Security Scan](https://github.com/yourusername/mahavishnu/actions/workflows/security-scan.yml/badge.svg)](https://github.com/yourusername/mahavishnu/actions/workflows/security-scan.yml)
[![Performance Benchmark](https://github.com/yourusername/mahavishnu/actions/workflows/benchmark.yml/badge.svg)](https://github.com/yourusername/mahavishnu/actions/workflows/benchmark.yml)
```

### 4.2 Update Username

Replace `yourusername` with your actual GitHub username:

```bash
# Update badges in README
sed -i '' 's/yourusername/YOUR_USERNAME/g' README.md
```

## Step 5: Initial Workflow Run

### 5.1 Commit and Push

```bash
git add .github/workflows/
git commit -m "feat: Add CI/CD workflows for Phase 6

- Add Phase 6 test workflow
- Add documentation build workflow
- Add security scan workflow
- Add performance benchmark workflow
- Update README with status badges"

git push origin main
```

### 5.2 Monitor First Run

1. Go to **Actions** tab
2. Click on running workflows
3. Monitor logs for any errors

### 5.3 Fix Any Issues

Common issues and fixes:

**Issue: Python version not found**
```yaml
# Update PYTHON_VERSION in workflow files
env:
  PYTHON_VERSION: '3.12'  # Change to available version
```

**Issue: Dependency installation fails**
```bash
# Update dependencies locally
uv pip install -e ".[dev,prefect,agno]"

# Commit updated pyproject.toml
git add pyproject.toml
git commit -m "fix: Update dependencies for CI"
git push
```

**Issue: Tests fail**
```bash
# Run tests locally first
pytest tests/unit/ -m "unit"

# Fix failing tests, then push
git commit -am "fix: Fix failing tests"
git push
```

## Step 6: Configure Notifications

### 6.1 Email Notifications

1. Go to **Settings** → **Notifications**
2. Configure:
   - ✅ Send email notifications for workflow runs
   - ✅ Notify me on failures

### 6.2 Slack Notifications (Optional)

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

## Step 7: Configure Codecov (Optional)

### 7.1 Install Codecov CLI

```bash
# macOS
brew install codecov

# Linux
curl -Os https://cli.codecov.io/latest/linux/codecov
chmod +x codecov
sudo mv codecov /usr/local/bin
```

### 7.2 Upload Coverage

```bash
# Run tests with coverage
pytest --cov=mahavishnu --cov-report=xml

# Upload to Codecov
codecov
```

### 7.3 Add Codecov YAML

Create `codecov.yml`:

```yaml
coverage:
  status:
    project:
      default:
        target: 80%
        threshold: 1%
        base: auto
    patch:
      default:
        target: 75%
        threshold: 1%

comment:
  layout: "reach,diff,flags,files,footer"
  behavior: default
  require_changes: false
  require_base: false
  require_head: true
```

## Step 8: Configure Staging/Production Environments

### 8.1 Create Environments

1. Go to **Settings** → **Environments**
2. Click **New environment**
3. Create `staging` environment
4. Create `production` environment
5. Configure protection rules:
   - ✅ Required reviewers (for production)
   - ✅ Wait timer (optional)

### 8.2 Add Deployment Workflows

Create `.github/workflows/deploy-staging.yml`:

```yaml
name: Deploy to Staging

on:
  workflow_dispatch:
    inputs:
      ref:
        description: 'Branch/tag to deploy'
        required: true
        default: 'main'

environment:
  name: staging
  url: https://staging.mahavishnu.example.com

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          ref: ${{ inputs.ref }}

      - name: Deploy to staging
        run: |
          echo "Deploying ${{ inputs.ref }} to staging..."
          # Add deployment commands here
```

## Step 9: Test CI/CD Pipeline

### 9.1 Create Test PR

```bash
git checkout -b test/cicd
echo "# Test" >> TEST.md
git add TEST.md
git commit -m "test: CI/CD pipeline"
git push origin test/cicd
```

1. Open PR on GitHub
2. Check that all workflows run
3. Verify all status checks pass

### 9.2 Merge Test PR

1. After all checks pass, merge PR
2. Verify workflows run on main branch
3. Check documentation deployment

## Step 10: Configure Scheduled Runs

Workflows already include scheduled runs:
- **Security Scan**: Daily at 2 AM UTC
- **Performance Benchmark**: Weekly on Sunday at 3 AM UTC

To modify schedules, edit the `cron` expression in workflow files:

```yaml
on:
  schedule:
    - cron: '0 2 * * *'  # Daily at 2 AM UTC
```

### Cron Format

```
┌───────────── minute (0 - 59)
│ ┌───────────── hour (0 - 23)
│ │ ┌───────────── day of month (1 - 31)
│ │ │ ┌───────────── month (1 - 12)
│ │ │ │ ┌───────────── day of week (0 - 6) (Sunday to Saturday)
│ │ │ │ │
* * * * *
```

## Step 11: Monitor and Maintain

### 11.1 Regular Maintenance

**Weekly**:
- Review workflow failures
- Update dependencies
- Check performance benchmarks

**Monthly**:
- Review and optimize workflow run times
- Update Python version if needed
- Review and update secrets

**Quarterly**:
- Review and update workflow configurations
- Audit access and permissions
- Update documentation

### 11.2 Troubleshooting

**Workflow not triggering**:
- Check branch names in workflow files
- Verify workflow syntax: `act -l`
- Check Actions is enabled

**Tests failing intermittently**:
- Add retry logic
- Increase timeouts
- Use fixture isolation

**Slow workflows**:
- Enable caching
- Reduce matrix size
- Optimize test suite

## Step 12: Advanced Configuration

### 12.1 Self-Hosted Runners

For custom infrastructure:

1. Go to **Settings** → **Actions** → **Runners**
2. Click **New self-hosted runner**
3. Follow instructions for your OS
4. Update workflow to use self-hosted runner:

```yaml
jobs:
  test:
    runs-on: [self-hosted, linux]
```

### 12.2 Composite Actions

Create reusable actions in `.github/actions/`:

```yaml
# .github/actions/setup-env/action.yml
name: 'Setup Environment'
description: 'Setup Python and install dependencies'
runs:
  using: 'composite'
  steps:
    - name: Set up Python
      uses: actions/setup-python@v5
      with:
        python-version: '3.13'
    - name: Install uv
      shell: bash
      run: curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 12.3 Matrix Strategy Optimization

Use include/exclude for specific combinations:

```yaml
strategy:
  matrix:
    python: ['3.11', '3.12', '3.13']
    os: [ubuntu-latest, macos-latest, windows-latest]
    include:
      - python: '3.13'
        os: ubuntu-latest
        full-test: true
    exclude:
      - python: '3.11'
        os: windows-latest
```

## Verification Checklist

Use this checklist to verify your CI/CD setup:

- [ ] GitHub Actions enabled
- [ ] Workflow files in `.github/workflows/`
- [ ] Branch protection rules configured
- [ ] Secrets configured (if needed)
- [ ] README badges added and updated
- [ ] Initial workflow run successful
- [ ] Notifications configured
- [ ] Codecov configured (optional)
- [ ] Environments created (staging/production)
- [ ] Test PR created and merged successfully
- [ ] Scheduled runs verified
- [ ] Documentation updated

## Next Steps

- [ ] Review [CI/CD Guide](CI_CD_GUIDE.md) for detailed usage
- [ ] Configure custom deployment workflows
- [ ] Set up staging and production environments
- [ ] Integrate with external services (e.g., Sentry, Datadog)
- [ ] Configure advanced features (self-hosted runners, composite actions)

## Support

For setup issues:
1. Check workflow logs in Actions tab
2. Review this setup guide
3. Open an issue with `ci/cd` label
4. Include workflow run link and error logs

______________________________________________________________________

**Last Updated**: 2026-02-05
**Maintained By**: Mahavishnu DevOps Team
