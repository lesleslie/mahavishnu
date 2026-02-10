# httpx Dependency Conflict - Workaround and Resolution Plan

**Status**: Active Workaround
**Created**: 2025-02-05
**Updated**: 2025-02-05
**Severity**: High (blocks LlamaIndex adapter usage)
**Related Issues**: ACT-001, ACT-007

---

## Executive Summary

A version conflict exists between `fastmcp` and `llama-index-embeddings-ollama` regarding their httpx dependency requirements. This document outlines the current workaround, monitoring strategy, and resolution timeline.

---

## Conflict Details

### Current State

**Package: fastmcp**
- Version: 2.14.5 (stable) - RECOMMENDED
- Version: 3.0.0b1 (beta) - CURRENT (not recommended for production)
- Requires: `httpx>=0.28.1`

**Package: llama-index-embeddings-ollama**
- Version: 0.8.6 (latest)
- Requires: `httpx<0.28.0` (implicitly via llama-index-core)

**Conflict**: Both packages cannot be installed simultaneously due to incompatible httpx version requirements.

### Impact Analysis

1. **FastMCP 3.0.0b1 (Beta)**: Currently installed, provides httpx 0.28.1+ support
   - Pros: Compatible with latest httpx
   - Cons: Beta version not recommended for production stability

2. **FastMCP 2.14.5 (Stable)**: Latest stable release
   - Pros: Production-ready, stable API
   - Cons: Also requires httpx>=0.28.1, same conflict with llamaindex

3. **LlamaIndex Ollama Adapter**: Currently **disabled** in `pyproject.toml` (lines 154-167)
   - RAG features unavailable until conflict resolved
   - Workaround: Use Ollama directly or use alternative embedding methods

---

## Current Workaround

### ACT-007: Stabilize FastMCP Dependency

**Status**: In Progress
**Action**: Pin FastMCP to stable release

**Change**:
```toml
# Before (line 27)
"fastmcp>=3.0.0b1",  # Compatible with crackerjack (pre-release for httpx compatibility)

# After
"fastmcp~=2.14.5",  # Stable release (compatible with crackerjack, httpx 0.28.1+)
```

**Rationale**:
- FastMCP 2.14.5 is the latest stable release (2026-02-03)
- Provides same httpx compatibility as 3.0.0b1
- Production-ready with stable API
- Compatible with Crackerjack 0.51.0+

### LlamaIndex Extras Disabled

**Location**: `pyproject.toml` lines 138-167

**Reason**: httpx version conflict cannot be resolved with current package versions

**Current State**:
```toml
# NOTE: llamaindex extras disabled due to httpx version conflict with fastmcp
# The llama-index-embeddings-ollama package requires httpx<0.28.0
# while fastmcp requires httpx>=0.28.1
# This needs to be resolved upstream before llamaindex can be re-enabled
# llamaindex = [
#     "llama-index-core>=0.12.0,<0.13.0",
#     "llama-index-embeddings-ollama>=0.4.0,<0.5.0",
#     "llama-index-llms-ollama>=0.4.0,<0.5.0",
# ]
```

### Alternative Embedding Options

While LlamaIndex adapter is disabled, the following alternatives are available:

1. **Ollama Direct Integration** (recommended for development)
   - Install: `uv pip install -e ".[ollama]"`
   - Use Ollama embeddings directly without LlamaIndex wrapper
   - Works on all platforms (including x86_64 macOS)

2. **FastEmbed** (production on ARM64)
   - Install: `uv pip install -e ".[fastembed]"`
   - ONNX-based embeddings, no external dependencies
   - Platform-specific: ARM64 Mac and Linux only

3. **Session-Buddy Memory** (ARM64 only)
   - Already installed as optional dependency
   - ONNX embeddings via onnxruntime
   - Local-first privacy, no external APIs

---

## Monitoring Strategy

### Weekly Checks

Every Monday, run the following to check for upstream updates:

```bash
# Check latest llama-index-embeddings-ollama requirements
pip download --no-deps llama-index-embeddings-ollama --dest /tmp && \
  unzip -q -c /tmp/llama_index*.whl */METADATA | grep -E "httpx"

# Check latest fastmcp requirements
pip download --no-deps fastmcp --dest /tmp && \
  unzip -q -c /tmp/fastmcp*.whl */METADATA | grep -E "httpx"

# Check fastmcp for new stable releases
pip index versions fastmcp | head -5
```

### Automated Monitoring (Recommended)

Create a GitHub Dependabot or Renovate rule to monitor:
- `llama-index-embeddings-ollama`
- `fastmcp`
- `httpx`

### Resolution Criteria

The conflict is resolved when **either** condition is met:

1. **llama-index-embeddings-ollama** updates to support `httpx>=0.28.1`
2. **fastmcp** downgrades to support `httpx<0.28.0` (unlikely)
3. **llama-index-core** removes upper bound on httpx (most likely)

---

## Resolution Timeline

### Phase 1: Workaround (Current)
- **Status**: Active
- **Action**: Pin FastMCP to stable 2.14.5, disable LlamaIndex
- **ETA**: Completed 2025-02-05

### Phase 2: Monitor (Ongoing)
- **Status**: Pending
- **Action**: Weekly checks for upstream updates
- **ETA**: Ongoing until resolved

### Phase 3: Resolution (Future)
- **Status**: Blocked on upstream
- **Action**: Re-enable LlamaIndex extras when compatible
- **ETA**: Unknown (depends on llama-index updates)

### Expected Resolution Timeline

Based on typical release cycles:
- **LlamaIndex releases**: Monthly (next release ~March 2025)
- **FastMCP releases**: Weekly (current stable is 2026-02-03)
- **Estimated resolution**: 2-8 weeks

---

## Testing After Resolution

Once the conflict is resolved, follow these steps:

### 1. Verify Compatibility
```bash
# Create test environment
python -m venv .venv-test
source .venv-test/bin/activate

# Install with both packages
uv pip install "fastmcp~=2.14.5" "llama-index-embeddings-ollama"

# Verify no conflicts
uv pip check

# Test httpx version
python -c "import httpx; print(f'httpx: {httpx.__version__}')"
```

### 2. Update pyproject.toml
```toml
# Remove the workaround comment
# Uncomment the llamaindex extras
llamaindex = [
    "llama-index-core>=0.12.0,<0.13.0",
    "llama-index-embeddings-ollama>=0.4.0,<0.5.0",
    "llama-index-llms-ollama>=0.4.0,<0.5.0",
]
```

### 3. Test Integration
```bash
# Install with llamaindex extras
uv pip install -e ".[llamaindex]"

# Run tests
pytest tests/unit/adapters/test_llamaindex_adapter.py

# Test RAG pipeline
mahavishnu sweep --tag python --adapter llamaindex
```

### 4. Update Documentation
- Update this document with resolution date
- Remove workaround comments from pyproject.toml
- Announce in CHANGELOG.md

---

## Upstream Links

### LlamaIndex
- **GitHub**: https://github.com/run-llama/llama_index
- **Issue Tracker**: https://github.com/run-llama/llama_index/issues
- **Releases**: https://github.com/run-llama/llama_index/releases

### FastMCP
- **GitHub**: https://github.com/jlowin/fastmcp
- **PyPI**: https://pypi.org/project/fastmcp/
- **Releases**: https://github.com/jlowin/fastmcp/releases

### httpx
- **GitHub**: https://github.com/encode/httpx
- **PyPI**: https://pypi.org/project/httpx/
- **Changelog**: https://github.com/encode/httpx/blob/master/CHANGELOG.md

---

## Recommendations

### For Development (Current)

1. **Use FastMCP 2.14.5** (stable) instead of 3.0.0b1
2. **Use Ollama directly** for embeddings (`uv pip install -e ".[ollama]"`)
3. **Use FastEmbed** for production on ARM64 (`uv pip install -e ".[fastembed]"`)
4. **Use Session-Buddy** for memory on ARM64 (`uv pip install -e ".[dev]"`)

### For Production (Post-Resolution)

1. **Monitor upstream** for llama-index updates
2. **Test thoroughly** in dev environment first
3. **Enable LlamaIndex** extras only after verification
4. **Update documentation** with resolution steps

### For Long-Term Stability

1. **Set up automated monitoring** (Dependabot, Renovate)
2. **Pin critical dependencies** with `~=` (compatible release clause)
3. **Avoid beta versions** in production dependencies
4. **Test dependency updates** in isolated environments
5. **Document workarounds** with clear resolution criteria

---

## FAQ

### Q: Why not downgrade httpx to <0.28.0?
**A**: FastMCP 2.14.5 and 3.0.0b1 both require httpx>=0.28.1. Downgrading httpx would break FastMCP, which is a core dependency for MCP server functionality.

### Q: Why not upgrade llama-index to latest?
**A**: The latest llama-index-embeddings-ollama (0.8.6) still has the httpx<0.28.0 constraint via llama-index-core. This is an upstream issue that needs to be fixed in llama-index.

### Q: Can I use both packages with different httpx versions?
**A**: No, Python's dependency resolver doesn't allow multiple versions of the same package in one environment. You would need to use virtual environments or separate containers.

### Q: What about using httpx 0.28.0 exactly?
**A**: FastMCP requires >=0.28.1, so 0.28.0 doesn't meet the minimum version. Even if it did, it's unlikely to satisfy both constraints long-term.

### Q: When will this be fixed?
**A**: This depends on the llama-index team removing the httpx upper bound. Based on their release cadence, this could be 2-8 weeks. Monitoring their GitHub issues and releases is recommended.

---

## Change Log

| Date | Change | Author |
|------|--------|--------|
| 2025-02-05 | Initial documentation of httpx conflict workaround | dependency-manager |
| 2025-02-05 | Document ACT-007 FastMCP stabilization | dependency-manager |

---

**Next Review**: 2025-02-12 (1 week)
**Document Owner**: dependency-manager
**Status**: Active Workaround
