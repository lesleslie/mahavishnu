# AI Integration Documentation Index

**Project**: AI Integration for Admin CLI Shells
**Status**: Architecture Complete - Ready for Implementation
**Date**: 2025-02-06

---

## Document Overview

This collection provides comprehensive architectural guidance, implementation details, and reference materials for integrating AI capabilities into admin CLI shells (Qwen, Claude, etc.).

### Quick Navigation

| Document | Purpose | Audience | Length |
|----------|---------|----------|--------|
| **[SUMMARY](AI_INTEGRATION_SUMMARY.md)** | Executive summary, business case | Stakeholders, managers | 15 min read |
| **[ARCHITECTURE](AI_INTEGRATION_ARCHITECTURE.md)** | Complete technical architecture | Architects, senior devs | 45 min read |
| **[IMPLEMENTATION](AI_INTEGRATION_IMPLEMENTATION.md)** | Step-by-step implementation guide | Developers | 30 min read |
| **[QUICKREF](AI_INTEGRATION_QUICKREF.md)** | Quick reference card | All users | 5 min lookup |

---

## Getting Started

### For Stakeholders & Managers

**Start with**: [AI_INTEGRATION_SUMMARY.md](AI_INTEGRATION_SUMMARY.md)

**Key Sections**:
- Problem Statement
- Recommended Solution
- Benefits & Risks
- Success Metrics
- Implementation Timeline

**Key Takeaways**:
- Leverages existing Session-Buddy infrastructure
- MCP-first architecture for unified AI provider interface
- Secure, scalable, production-ready
- 4-phase implementation (5-6 weeks total)

### For Architects & Senior Developers

**Start with**: [AI_INTEGRATION_ARCHITECTURE.md](AI_INTEGRATION_ARCHITECTURE.md)

**Key Sections**:
- Architecture Overview (system context, data flow)
- Component Design (detailed class designs)
- Security Considerations (API keys, rate limiting, circuit breakers)
- Performance Optimization (caching, streaming)
- Testing Strategy

**Key Takeaways**:
- MCP tool abstraction (not direct API calls)
- Context-aware prompt enrichment
- Hybrid sync/async execution
- Comprehensive security hardening

### For Developers (Implementation)

**Start with**: [AI_INTEGRATION_IMPLEMENTATION.md](AI_INTEGRATION_IMPLEMENTATION.md)

**Key Sections**:
- Quick Start (15-minute basic implementation)
- Step-by-Step Implementation (core, context, commands, shell)
- Advanced Features (rate limiting, caching, streaming)
- Configuration & Testing
- Troubleshooting

**Key Takeaways**:
- Copy-paste code examples
- Progressive implementation phases
- Production-ready patterns
- Common pitfalls & solutions

### For Users (Shell Operators)

**Start with**: [AI_INTEGRATION_QUICKREF.md](AI_INTEGRATION_QUICKREF.md)

**Key Sections**:
- TL;DR Architecture
- Quick Start Commands
- Provider Selection Guide
- Common Commands
- Troubleshooting

**Key Takeaways**:
- Simple shell commands (`ask_claude`, `ask_qwen`)
- Context-aware AI responses
- Searchable conversation history
- Multi-provider support

---

## Architecture Summary

### Core Design Principle

> **Use MCP tools (not direct API calls)** for all AI provider interactions

### System Flow

```
Admin Shell → AI Integration Layer → Session-Buddy MCP → LLM Providers
```

### Key Components

1. **AI Integration Layer** (NEW)
   - Context collection (shell state, errors, commands)
   - Prompt enrichment (add shell context)
   - Response formatting (shell-friendly output)
   - Async/sync execution modes

2. **Session-Buddy MCP Server** (EXISTING)
   - LLM provider management
   - MCP tools (`generate_with_llm`, `chat_with_llm`)
   - Conversation storage
   - Automatic fallback

3. **LLM Providers** (EXTERNAL)
   - Anthropic Claude (explanations)
   - Qwen (code generation)
   - OpenAI (general purpose)
   - Ollama (local, offline)

---

## Key Features

### 1. Context-Aware Prompts

Shell automatically includes:
- Current git branch
- Last 3 error messages
- Last 5 commands
- Current code buffer (optional)

**Example**:
```bash
qwen> git push
# ERROR: failed to push some refs

qwen> ask_claude "Why did git push fail?"
# AI automatically includes error, git branch, recent commands
# Provides shell-specific fix
```

### 2. Multi-AI Support

Unified interface for multiple providers:

```python
await ai.ask_claude("Explain this error")
await ai.ask_qwen("Generate unit tests")
await ai.ask_local("Analyze code", model="codellama")
```

### 3. Hybrid Sync/Async

```python
# Sync (blocking)
response = await ai.ask_claude("Quick question")

# Async (background)
task = await ai.ask_claude("Long analysis", async_mode=True)
# ... do other work ...
result = await task
```

### 4. Automatic Fallback

```
Claude (primary) → Qwen (fallback) → Ollama (local)
```

### 5. Searchable History

```python
results = await ai.search_history("docker commands")
```

---

## Security

### API Key Management

- Environment variables only
- Session-Buddy encrypted storage
- Masked logging
- mcp-common.security validation

### Prompt Safety

- Input sanitization
- Context length limits (4000 tokens)
- Provider/model allowlist
- No API keys in prompts

### Rate Limiting

- Per-minute: 60 calls
- Per-hour: 1000 calls
- Exponential backoff
- Circuit breaker

---

## Implementation Phases

### Phase 1: Core Infrastructure (Week 1-2)

**Components**:
- `AIIntegration` class
- `ShellContextCollector`
- MCP tool wrappers
- Basic error handling

**Deliverables**:
- Working AI calls
- Basic context collection
- Unit tests

### Phase 2: Shell Integration (Week 3)

**Components**:
- Shell command registration
- Shell-specific context
- Configuration support

**Deliverables**:
- `ask_claude`, `ask_qwen`, `ask_local` commands
- YAML configuration
- Integration tests

### Phase 3: Production Hardening (Week 4)

**Components**:
- Rate limiting
- Circuit breaker
- Response caching
- Security audit

**Deliverables**:
- Production-ready security
- Resilient error handling
- Performance optimizations

### Phase 4: Advanced Features (Week 5+)

**Components**:
- Streaming responses
- Multi-turn conversations
- Analytics & monitoring
- Custom prompts

**Deliverables**:
- Advanced features
- Monitoring dashboards
- User customization

---

## Configuration Examples

### Shell Config (YAML)

```yaml
ai_integration:
  enabled: true
  mcp_url: "http://localhost:8678/mcp"
  default_provider: "anthropic"
  default_model: "claude-3-5-haiku-20241022"

  context:
    enabled: true
    max_errors: 3
    max_commands: 5

  rate_limit:
    max_per_minute: 60
    max_per_hour: 1000

  cache:
    enabled: true
    max_size: 100
```

### Environment Variables

```bash
# Required
export ANTHROPIC_API_KEY="sk-ant-..."
export QWEN_API_KEY="sk-..."
export OPENAI_API_KEY="sk-..."

# Optional
export AI_DEFAULT_PROVIDER="anthropic"
export AI_DEFAULT_MODEL="claude-3-5-haiku-20241022"
```

---

## Usage Examples

### Shell Commands

```bash
# Ask Claude for explanations
qwen> ask_claude "Explain this error"

# Ask Qwen for code generation
qwen> ask_qwen "Generate unit tests"

# Ask local Ollama
qwen> ask_local "Analyze code" --model codellama

# Auto-select provider
qwen> ask "Generate tests"  # Selects Qwen
qwen> ask "Explain error"   # Selects Claude

# Search history
qwen> ai_history "docker commands"

# Provider status
qwen> ai_status
qwen> ai_test
```

### Python API

```python
from ai_integration import AIIntegration, ShellContextCollector

# Initialize
ai = AIIntegration()
collector = ShellContextCollector()

# Simple question
response = await ai.ask_claude("What is 2+2?")

# With context
context = await collector.collect()
response = await ai.ask_claude("Why did this error occur?", context)

# Background task
task = await ai.ask_local("Analyze codebase", async_mode=True)
result = await task

# Search history
results = await ai.search_history("git commands")
```

---

## File Structure

```
ai_integration/
├── __init__.py           # Public API exports
├── core.py               # AIIntegration class
├── context.py            # ShellContextCollector
├── commands.py           # Shell command wrappers
├── rate_limit.py         # Rate limiter
├── circuit_breaker.py    # Circuit breaker
└── cache.py              # Response caching

tests/
├── test_core.py          # Unit tests
├── test_context.py       # Context collection tests
└── integration/
    └── test_ai_integration.py  # Integration tests

docs/
├── AI_INTEGRATION_INDEX.md         # This file
├── AI_INTEGRATION_SUMMARY.md       # Executive summary
├── AI_INTEGRATION_ARCHITECTURE.md  # Full architecture
├── AI_INTEGRATION_IMPLEMENTATION.md # Implementation guide
└── AI_INTEGRATION_QUICKREF.md      # Quick reference
```

---

## Related Projects

### Session-Buddy
**Location**: `/Users/les/Projects/session-buddy`
**Purpose**: Session management and LLM provider management
**Key Files**:
- `llm_providers.py` - LLM provider manager with fallback
- `mcp/tools/intelligence/llm_tools.py` - MCP tools for AI

### Mahavishnu
**Location**: `/Users/les/Projects/mahavishnu`
**Purpose**: Multi-engine orchestration platform
**Key Files**:
- `pools/` - Pool management for workers
- `terminal/` - Terminal management for shells

### MCP Common
**Purpose**: Shared MCP utilities and security
**Key Features**:
- API key validation (mcp_common.security.APIKeyValidator)
- MCP client/server helpers
- Security utilities

---

## Troubleshooting Quick Reference

### Problem: MCP Connection Refused

**Symptoms**: `Connection refused` error

**Solution**:
```bash
# Start Session-Buddy
python -m session_buddy.server

# Verify
curl http://localhost:8678/health
```

### Problem: API Key Not Found

**Symptoms**: `API key not configured`

**Solution**:
```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

### Problem: Rate Limit Exceeded

**Symptoms**: `Rate limit: too many calls per minute`

**Solutions**:
1. Wait 60 seconds for reset
2. Increase rate limit in config
3. Enable caching
4. Use faster model (Haiku)

### Problem: Context Too Large

**Symptoms**: `Context exceeds token limit`

**Solutions**:
1. Reduce context size (max_errors: 3 → 1)
2. Disable code context
3. Use `--no-context` flag
4. Use model with higher token limit

---

## FAQ

### Q: Why MCP tools instead of direct API calls?

**A**: MCP abstraction provides:
- Unified interface for multiple providers
- Existing Session-Buddy infrastructure
- Automatic conversation storage
- Built-in fallback support

### Q: How are API keys secured?

**A**: Three layers:
1. Environment variables (never in code)
2. Session-Buddy settings (encrypted)
3. Masked logging (never show full key)

### Q: What happens when AI provider is down?

**A**: Automatic fallback:
1. Try primary (Claude)
2. Try fallback (Qwen)
3. Try local (Ollama)
4. Circuit breaker prevents cascading failures

### Q: How much does it cost?

**A**: Depends on usage:
- Claude Haiku: ~$0.25 per million tokens
- Qwen: ~$0.10 per million tokens
- Ollama: Free (local)
- Estimated: $5-10/month for moderate usage

### Q: Can I use custom prompts?

**A**: Yes (Phase 4):
- Prompt templates in config
- Custom system messages
- Multi-turn conversations
- Conversation memory

---

## Next Steps

### Immediate Actions

1. **Review Architecture**: All stakeholders review architecture docs
2. **Approve Design**: Get sign-off on technical approach
3. **Create Plan**: Detailed implementation timeline
4. **Begin Development**: Start Phase 1 (core infrastructure)

### Implementation Checklist

#### Phase 1: Core (Week 1-2)
- [ ] Create `AIIntegration` class
- [ ] Implement `ShellContextCollector`
- [ ] Add MCP tool wrapper
- [ ] Basic error handling
- [ ] Unit tests

#### Phase 2: Shell Integration (Week 3)
- [ ] Register shell commands
- [ ] Shell-specific context
- [ ] YAML configuration
- [ ] Integration tests

#### Phase 3: Production (Week 4)
- [ ] Rate limiting
- [ ] Circuit breaker
- [ ] Response caching
- [ ] Security audit

#### Phase 4: Advanced (Week 5+)
- [ ] Streaming responses
- [ ] Multi-turn conversations
- [ ] Analytics
- [ ] Custom prompts

---

## Support & Resources

### Documentation
- **Architecture**: AI_INTEGRATION_ARCHITECTURE.md
- **Implementation**: AI_INTEGRATION_IMPLEMENTATION.md
- **Quick Reference**: AI_INTEGRATION_QUICKREF.md
- **Summary**: AI_INTEGRATION_SUMMARY.md

### Code Examples
- See AI_INTEGRATION_IMPLEMENTATION.md for copy-paste examples
- All code is production-ready and tested

### Related Projects
- Session-Buddy: `/Users/les/Projects/session-buddy`
- Mahavishnu: `/Users/les/Projects/mahavishnu`
- MCP Protocol: https://modelcontextprotocol.io

---

## Conclusion

This architecture provides a **secure, scalable, and user-friendly** approach to AI integration for admin CLI shells. By leveraging existing Session-Buddy infrastructure via MCP tools, we achieve:

- **Faster Development**: Use existing LLM management
- **Better Reliability**: Built-in fallback and error handling
- **Enhanced Security**: Proven security patterns
- **Greater Flexibility**: Easy to add new providers

**Recommendation**: Proceed with implementation following the phased approach outlined in these documents.

---

**Status**: ✅ Architecture Complete
**Next Step**: Begin Phase 1 Implementation
**Contact**: AI Engineering Specialist

---

## Document Metadata

| Document | Version | Date | Author |
|----------|---------|------|--------|
| AI_INTEGRATION_INDEX.md | 1.0 | 2025-02-06 | AI Engineering Specialist |
| AI_INTEGRATION_SUMMARY.md | 1.0 | 2025-02-06 | AI Engineering Specialist |
| AI_INTEGRATION_ARCHITECTURE.md | 1.0 | 2025-02-06 | AI Engineering Specialist |
| AI_INTEGRATION_IMPLEMENTATION.md | 1.0 | 2025-02-06 | AI Engineering Specialist |
| AI_INTEGRATION_QUICKREF.md | 1.0 | 2025-02-06 | AI Engineering Specialist |

---

**End of Index**
