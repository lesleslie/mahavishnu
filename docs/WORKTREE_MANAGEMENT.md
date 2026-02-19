# Worktree Management Guide

Mahavishnu provides standardized, safe git worktree management across your entire repository ecosystem with comprehensive safety mechanisms to prevent data loss.

## Quick Start

### Basic Worktree Operations

```bash
# Create a worktree
mahavishnu worktree create mahavishnu feature-auth

# Create a worktree with a new branch
mahavishnu worktree create mahavishnu feature-api --create-branch

# Create a worktree with a custom name
mahavishnu worktree create mahavishnu main --name my-worktree

# List all worktrees across all repositories
mahavishnu worktree list

# List worktrees for a specific repository
mahavishnu worktree list --repo mahavishnu

# Check safety status before removal
mahavishnu worktree safety-status mahavishnu ~/worktrees/mahavishnu/feature-auth

# Remove a worktree (safe - checks for uncommitted changes)
mahavishnu worktree remove mahavishnu ~/worktrees/mahavishnu/feature-auth

# Force remove a worktree with uncommitted changes (requires reason)
mahavishnu worktree remove mahavishnu ~/worktrees/mahavishnu/feature \
  --force \
  --force-reason "Fixing critical security bug, backup created automatically"

# Prune stale worktree references
mahavishnu worktree prune mahavishnu

# Check provider health
mahavishnu worktree provider-health
```

## Architecture

### Multi-Layer Safety System

Mahavishnu worktree management implements **defense-in-depth** security across multiple layers:

```
┌─────────────────────────────────────────────────────────────┐
│  Layer 1: WorktreeCoordinator                             │
│  - Repository validation                                  │
│  - Dependency checking (ARCH-002 fix)                      │
│  - Cross-repo coordination                                │
│  - Comprehensive audit logging (SECURITY-003)             │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│  Layer 2: WorktreePathValidator                           │
│  - Null byte prevention (CWE-170)                          │
│  - Path traversal prevention (CWE-22)                      │
│  - Shell metacharacter detection (CWE-114)                 │
│  - Allowed root verification                              │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│  Layer 3: WorktreeProviderRegistry                        │
│  - SessionBuddyWorktreeProvider (primary, MCP-based)      │
│  - DirectGitWorktreeProvider (fallback, subprocess)        │
│  - Automatic health checking & fallback                    │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│  Layer 4: Backup Manager (SECURITY-001)                   │
│  - Automatic backup before force removal                   │
│  - Timestamped backup directories                          │
│  - XDG-compliant backup storage                           │
└─────────────────────────────────────────────────────────────┘
```

### Provider Abstraction

The worktree system uses a **provider pattern** for resilience:

1. **SessionBuddyWorktreeProvider** (Primary)
   - Uses Session-Buddy MCP integration
   - Session state preservation
   - Advanced worktree features

2. **DirectGitWorktreeProvider** (Fallback)
   - Uses subprocess git commands
   - Always available (no external dependencies)
   - Activates automatically if Session-Buddy unavailable

3. **MockWorktreeProvider** (Testing)
   - Safe testing without real git operations
   - Used in all automated tests

## Safety Features

### 1. Force Flag Safety (SECURITY-001)

**Problem**: Force flag bypassing ALL safety checks without reason or backup creates risk of accidental data loss.

**Solution**:
- `--force` flag with uncommitted changes **requires** `--force-reason`
- Automatic backup creation before any force removal
- Comprehensive audit logging of all force operations

**Example**:
```bash
# SAFE: Force removal with reason
mahavishnu worktree remove repo /worktrees/repo/feature \
  --force \
  --force-reason "Fixing critical bug in production"

# BLOCKED: Force removal without reason
mahavishnu worktree remove repo /worktrees/repo/feature --force
# Error: Worktree has uncommitted changes. --force requires --force-reason.
```

### 2. Path Validation (SECURITY-002)

**Problem**: Path traversal vulnerabilities if only provider validates paths.

**Solution**: **Defense-in-depth** - validate at Mahavishnu layer BEFORE provider calls

**Security Checks**:
- Null byte prevention (CWE-170)
- Path traversal prevention (CWE-22)
- Shell metacharacter detection (CWE-114)
- Allowed root verification

**Example**:
```bash
# BLOCKED: Path with null bytes
mahavishnu worktree create repo /worktrees/repo\x00feature
# Error: Invalid worktree path: Path contains null bytes (CWE-170)

# BLOCKED: Path traversal attempt
mahavishnu worktree create repo /worktrees/../../../etc/passwd
# Error: Invalid worktree path: Path contains dangerous component: .. (CWE-22)

# BLOCKED: Shell metacharacters
mahavishnu worktree create repo "/worktrees/repo;rm -rf /"
# Error: Invalid worktree path: Path contains shell metacharacters (CWE-114)
```

### 3. Audit Logging (SECURITY-003)

**Problem**: Missing audit logging violates SOC 2, ISO 27001, and PCI DSS compliance requirements.

**Solution**: Comprehensive audit logging for ALL operations with sensitive data redaction

**Logged Events**:
- `worktree_create_attempt` - Before creation
- `worktree_create_success` - After successful creation
- `worktree_create_failure` - After failed creation
- `worktree_remove_attempt` - Before removal
- `worktree_remove_success` - After successful removal
- `worktree_remove_forced` - Force removal with reason and backup
- `worktree_remove_failure` - After failed removal
- `worktree_prune` - Prune operations
- `worktree_list` - List operations
- `worktree_backup_created` - Backup creation
- `security_rejection` - Blocked malicious operations

**Audit Log Location**:
```
~/.local/state/mahavishnu/audit.log  # XDG-compliant
```

### 4. Automatic Backup Creation

**Feature**: Automatic backup creation before force removal with uncommitted changes

**Storage**:
```
~/.local/state/mahavishnu/worktree_backups/
├── mahavishnu_feature_20260218_120000/
│   ├── .backup_metadata.json
│   └── [all worktree files]
└── mahavishnu_main_20260218_130000/
    ├── .backup_metadata.json
    └── [all worktree files]
```

**Retention Policy**:
- Default: 30 days
- Configurable via WorktreeBackupManager(retention_days=N)

### 5. Dependency Tracking (ARCH-002 Fix)

**Problem**: Repo-level dependency tracking causes false positives.

**Solution**: Worktree-level dependency tracking with specific worktree paths

**Example**:
```bash
# Create worktree
mahavishnu worktree create backend-api feature-auth

# Another repo depends on this SPECIFIC worktree
# (Not just the backend-api repo in general)

# Try to remove (blocked)
mahavishnu worktree remove backend-api ~/worktrees/backend-api/feature-auth
# Error: Worktree is depended on by 1 other repositories
#        Dependents: ['frontend']
```

## Common Workflows

### Workflow 1: Safe Feature Development

```bash
# 1. Create worktree for feature
mahavishnu worktree create mahavishnu feature-user-auth

# 2. Work in the worktree
cd ~/worktrees/mahavishnu/feature-user-auth
# ... make changes ...

# 3. Check safety status before removal
mahavishnu worktree safety-status mahavishnu ~/worktrees/mahavishnu/feature-user-auth
# Output:
# 🔍 Safety Status for ~/worktrees/mahavishnu/feature-user-auth:
#    Uncommitted changes: ⚠️ Yes
#    Is valid worktree: ✅ Yes
#    Path is safe: ✅ Yes
#    ✅ No blocking dependencies

# 4. Commit changes
cd ~/worktrees/mahavishnu/feature-user-auth
git add .
git commit -m "Implement user authentication"

# 5. Remove worktree (safe - no uncommitted changes)
mahavishnu worktree remove mahavishnu ~/worktrees/mahavishnu/feature-user-auth
# ✅ Removed worktree: ~/worktrees/mahavishnu/feature-user-auth
```

### Workflow 2: Emergency Force Removal

```bash
# Scenario: Worktree has critical bug that must be removed immediately

# 1. Check safety status
mahavishnu worktree safety-status mahavishnu ~/worktrees/mahavishnu/broken-feature
# Shows uncommitted changes

# 2. Force remove with reason and backup
mahavishnu worktree remove mahavishnu ~/worktrees/mahavishnu/broken-feature \
  --force \
  --force-reason "Critical bug: breaking production, hotfix deployed"

# Output:
# ✅ Backup created: ~/.local/state/mahavishnu/worktree_backups/mahavishnu_broken-feature_20260218_143052
# ✅ Removed worktree: ~/worktrees/mahavishnu/broken-feature

# 3. If needed, restore from backup
mahavishnu worktree restore ~/.local/state/mahavishnu/worktree_backups/mahavishnu_broken-feature_20260218_143052 \
  ~/worktrees/mahavishnu/broken-feature-restored
```

### Workflow 3: Multi-Repo Coordination

```bash
# Scenario: API change in backend-api requires frontend update

# 1. Create worktrees for coordinated change
mahavishnu worktree create backend-api feature/auth-api
mahavishnu worktree create frontend feature-auth-ui

# 2. Make changes in both worktrees
# ... work in parallel ...

# 3. List all worktrees across ecosystem
mahavishnu worktree list
# Output:
# 📋 Worktrees (2 total):
#   ✅ ~/worktrees/backend-api/feature-auth-api (feature/auth-api)
#   ✅ ~/worktrees/frontend/feature-auth-ui (feature/auth-ui)

# 4. When ready, remove both worktrees
mahavishnu worktree remove backend-api ~/worktrees/backend-api/feature-auth-api
mahavishnu worktree remove frontend ~/worktrees/frontend/feature-auth-ui
```

### Workflow 4: Cleanup Stale Worktrees

```bash
# 1. List worktrees to see what exists
mahavishnu worktree list --repo mahavishnu

# 2. Prune stale worktree references
mahavishnu worktree prune mahavishnu
# Output: ✅ Pruned 3 stale worktrees

# Note: Prune only removes worktrees whose branches have been deleted
# It's safe to run anytime
```

## MCP Tool Usage

Mahavishnu exposes worktree management via MCP tools for AI agent integration:

### Available Tools

1. **create_ecosystem_worktree**
2. **remove_ecosystem_worktree**
3. **list_ecosystem_worktrees**
4. **prune_ecosystem_worktrees**
5. **get_worktree_safety_status**
6. **get_worktree_provider_health**

### Example MCP Client Usage

```python
from mcp_client import MCPClient

client = MCPClient("http://localhost:8680/mcp")

# Create worktree
result = await client.call_tool(
    "create_ecosystem_worktree",
    arguments={
        "user_id": "user-123",
        "repo_nickname": "mahavishnu",
        "branch": "feature-auth",
        "create_branch": True,
    }
)

# List worktrees
result = await client.call_tool(
    "list_ecosystem_worktrees",
    arguments={
        "user_id": "user-123",
        "repo_nickname": "mahavishnu",
    }
)

# Get safety status
result = await client.call_tool(
    "get_worktree_safety_status",
    arguments={
        "user_id": "user-123",
        "repo_nickname": "mahavishnu",
        "worktree_path": "~/worktrees/mahavishnu/feature-auth",
    }
)
```

## Configuration

### Worktree Settings

Configure in `settings/mahavishnu.yaml`:

```yaml
# Worktree coordination
worktree_coordination:
  enabled: true

  # Allowed root directories for worktrees
  allowed_roots:
    - ~/worktrees
    - /path/to/custom/worktrees

  # Provider selection (optional, auto-detected)
  providers:
    - session_buddy  # Primary
    - direct_git    # Fallback

  # Backup settings
  backup:
    enabled: true
    retention_days: 30
    location: ~/.local/state/mahavishnu/worktree_backups
```

### Repository Configuration

Worktree metadata in `settings/repos.yaml`:

```yaml
repos:
  - path: "/Users/les/Projects/mahavishnu"
    nickname: "mahavishnu"
    role: "orchestrator"
    # Worktree-specific settings can be added here
```

## Troubleshooting

### Issue: "Repository not found"

**Cause**: Repository nickname not found in `settings/repos.yaml`

**Solution**:
```bash
# List available repositories
mahavishnu list-repos

# Use correct nickname or package name
mahavishnu worktree create mahavishnu main  # Use nickname, not full name
```

### Issue: "Worktree has uncommitted changes"

**Cause**: Trying to remove worktree with uncommitted changes without `--force`

**Solution**:
```bash
# Option 1: Commit changes first
cd ~/worktrees/repo/branch
git add .
git commit -m "Save work"

# Option 2: Use force with reason
mahavishnu worktree remove repo ~/worktrees/repo/branch \
  --force \
  --force-reason "Reason for bypassing safety check"
```

### Issue: "Path outside allowed directories"

**Cause**: Worktree path not in allowed roots

**Solution**:
```bash
# Create in allowed location (default: ~/worktrees)
mahavishnu worktree create repo feature  # Goes to ~/worktrees/repo/feature

# Or configure custom allowed roots in settings/mahavishnu.yaml
```

### Issue: "Provider unavailable"

**Cause**: All worktree providers are unhealthy

**Solution**:
```bash
# Check provider health
mahavishnu worktree provider-health

# If Session-Buddy is down, system automatically falls back to DirectGit
# If both fail, check that git is available:
which git
git --version
```

### Issue: Backup creation failed

**Cause**: Insufficient permissions or disk space

**Solution**:
```bash
# Check backup directory permissions
ls -la ~/.local/state/mahavishnu/worktree_backups

# Check disk space
df -h ~/.local/state/mahavishnu

# Ensure write permissions
chmod 750 ~/.local/state/mahavishnu/worktree_backups
```

## Best Practices

### 1. Always Check Safety Status

Before removing a worktree, check safety status:

```bash
mahavishnu worktree safety-status repo ~/worktrees/repo/branch
```

### 2. Commit Before Removal

Avoid force removal when possible:

```bash
# BETTER: Commit first, then remove
cd ~/worktrees/repo/branch
git add .
git commit -m "Save work"
mahavishnu worktree remove repo ~/worktrees/repo/branch

# AVOID: Force removal (unless emergency)
mahavishnu worktree remove repo ~/worktrees/repo/branch --force --force-reason "..."
```

### 3. Use Descriptive Force Reasons

When using force removal, provide clear reasons:

```bash
# GOOD
mahavishnu worktree remove repo ~/worktrees/repo/broken \
  --force \
  --force-reason "Hotfix deployed, this worktree has breaking bug"

# BAD
mahavishnu worktree remove repo ~/worktrees/repo/broken \
  --force \
  --force-reason "oops"  # Not helpful for audit trail
```

### 4. Prune Regularly

Keep worktree references clean:

```bash
# Run weekly or as part of cleanup routine
mahavishnu worktree prune mahavishnu
```

### 5. Review Audit Logs

Regular review audit logs for security:

```bash
# View recent worktree operations
tail -100 ~/.local/state/mahavishnu/audit.log | grep worktree
```

## Migration from Direct Session-Buddy Usage

If you were previously using Session-Buddy directly:

### Before (Direct Session-Buddy)

```python
from session_buddy.worktree_manager import WorktreeManager

mgr = WorktreeManager()
mgr.create_worktree("/path/to/repo", "/path/to/worktree", "main")
```

### After (Mahavishnu Orchestration)

```bash
# CLI
mahavishnu worktree create repo main

# Or via MCP
from mcp_client import MCPClient
client = MCPClient("http://localhost:8680/mcp")
await client.call_tool(
    "create_ecosystem_worktree",
    arguments={"repo_nickname": "repo", "branch": "main"}
)
```

### Benefits

- ✅ **Safety**: Automatic backup creation before force removal
- ✅ **Validation**: Multi-layer security checks prevent data loss
- ✅ **Coordination**: Manage worktrees across entire ecosystem
- ✅ **Resilience**: Automatic provider fallback if Session-Buddy unavailable
- ✅ **Compliance**: Complete audit trail for SOC 2, ISO 27001, PCI DSS

## Security Considerations

### Authentication

All MCP tools require `WRITE_REPO` or `READ_REPO` permissions:

```python
from mahavishnu.mcp.auth import require_mcp_auth, Permission

@server.tool()
@require_mcp_auth(required_permission=Permission.WRITE_REPO)
async def create_ecosystem_worktree(...):
    ...
```

### Path Security

All paths validated before operations:
- Null bytes rejected (CWE-170)
- Path traversal blocked (CWE-22)
- Shell metacharacters blocked (CWE-114)
- Only allowed roots accepted

### Data Protection

- Sensitive data redacted in audit logs
- Automatic backups before destructive operations
- XDG-compliant paths for data storage
- No credentials in logs

## Compliance

Worktree management is compliant with:

- **SOC 2**: Complete audit trail with user tracking
- **ISO 27001**: Security controls and logging
- **PCI DSS**: Data protection and audit requirements

## Support

For issues or questions:

1. Check logs: `~/.local/state/mahavishnu/audit.log`
2. Check provider health: `mahavishnu worktree provider-health`
3. Review safety status: `mahavishnu worktree safety-status`
4. Report bugs with audit log excerpts

## References

- Git worktree documentation: https://git-scm.com/docs/git-worktree
- Session-Buddy integration: `session_buddy/worktree_manager.py`
- MCP tools specification: `docs/MCP_TOOLS_SPECIFICATION.md`
- Architecture decisions: `docs/adr/`
