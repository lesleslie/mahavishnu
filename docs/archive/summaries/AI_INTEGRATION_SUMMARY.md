# AI Integration for Admin CLI Shells - Executive Summary

**Date**: 2025-02-06
**Status**: Architecture Complete - Ready for Implementation
**Related Systems**: Mahavishnu, Session-Buddy, MCP Protocol

---

## Problem Statement

Admin CLI shells (Qwen, Claude, etc.) need AI integration to provide intelligent assistance, but there's no standard architecture for:

1. **API Integration**: How to call multiple AI providers (Claude, Qwen, Ollama)
2. **Context Injection**: How to include shell state (errors, commands, git)
3. **Authentication**: How to manage API keys securely
4. **Response Handling**: How to handle sync vs async calls
5. **Error Handling**: How to handle rate limits, failures
6. **Persistence**: How to store/search AI conversations

---

## Recommended Solution

**Architecture**: MCP-first AI integration via Session-Buddy

### Core Design Decision

> **Use MCP tools (not direct API calls)** for all AI provider interactions

**Rationale**:
- Session-Buddy already has LLM provider infrastructure
- MCP provides unified interface for all providers
- Automatic conversation storage in Session-Buddy
- Built-in fallback support (Claude → Qwen → Ollama)
- Provider-specific configuration in one place

### Architecture Diagram

```
┌──────────────────────┐
│  Admin CLI Shell     │
│  (Qwen, Claude, etc) │
└──────────┬───────────┘
           │
           ▼
┌──────────────────────────────────┐
│  AI Integration Layer             │
│  (NEW: ai_integration package)    │
│                                  │
│  • Context collection            │
│  • Prompt enrichment             │
│  • Response formatting           │
│  • Async/sync execution          │
└──────────┬───────────────────────┘
           │
           ▼
┌──────────────────────────────────┐
│  Session-Buddy MCP Server         │
│                                  │
│  • generate_with_llm (MCP tool)  │
│  • LLM Provider Manager          │
│  • Conversation storage          │
└──────────┬───────────────────────┘
           │
           ▼
┌──────────────────────────────────┐
│  LLM Providers                   │
│  (Anthropic, Qwen, OpenAI,       │
│   Ollama local)                  │
└──────────────────────────────────┘
```

---

## Key Features

### 1. Context-Aware Prompts

Shell automatically includes relevant context:

- **Git branch**: Current branch name
- **Last errors**: Recent error messages
- **Last commands**: Recent shell commands
- **Code context**: Current function/file (optional)

**Example**:
```python
# User runs:
qwen> ask_claude "Why did git push fail?"

# AI automatically includes:
# - Last error: "failed to push some refs"
# - Git branch: "main"
# - Last commands: "git status", "git commit"

# AI gives shell-specific answer with fix
```

### 2. Multi-AI Support

Unified interface for multiple providers:

- **Claude (Anthropic)**: Explanations, analysis
- **Qwen (Alibaba)**: Code generation, tests
- **OpenAI**: General purpose
- **Ollama (Local)**: Privacy, offline

**Example**:
```python
# All use same interface
await ai.ask_claude("Explain this")
await ai.ask_qwen("Generate tests")
await ai.ask_local("Analyze code")
```

### 3. Hybrid Sync/Async

Flexible execution modes:

```python
# Sync (blocking) - wait for response
response = await ai.ask_claude("Quick question")

# Async (background) - don't wait
task = await ai.ask_claude("Long analysis", async_mode=True)
# ... do other work ...
result = await task
```

### 4. Automatic Fallback

If primary provider fails, automatically try fallbacks:

```
Claude (primary) → Qwen (fallback) → Ollama (last resort)
```

### 5. Searchable Conversations

All AI conversations stored in Session-Buddy:

```python
# Search past conversations
results = await ai.search_history("docker commands")
```

---

## Security

### API Key Management

- Stored in environment variables
- Loaded via Session-Buddy settings
- Masked in logs (never show full key)
- Validation via mcp-common.security

### Prompt Safety

- Sanitize user input
- Limit context length (max 4000 tokens)
- Validate provider/model names
- Never include API keys in prompts

### Rate Limiting

- Per-minute limit (default: 60)
- Per-hour limit (default: 1000)
- Exponential backoff on errors
- Circuit breaker for failing providers

---

## Implementation Approach

### Phase 1: Core Infrastructure (Week 1-2)

**Components**:
- `AIIntegration` class
- `ShellContextCollector`
- MCP tool wrapper functions
- Basic error handling

**Deliverables**:
- Working AI integration
- Can ask Claude/Qwen questions
- Basic context collection

### Phase 2: Shell Integration (Week 3)

**Components**:
- Shell command registration
- Context collection for specific shells
- Configuration support

**Deliverables**:
- `ask_claude`, `ask_qwen`, `ask_local` commands
- Context injection working
- Configuration via YAML

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
- Custom prompt templates

**Deliverables**:
- Advanced features
- Monitoring dashboards
- Custom prompts

---

## Configuration Example

### Shell Config (YAML)

```yaml
# ~/.qwen/settings.yaml
ai_integration:
  enabled: true
  mcp_url: "http://localhost:8678/mcp"
  default_provider: "anthropic"
  default_model: "claude-3-5-haiku-20241022"

  context:
    enabled: true
    max_errors: 3
    max_commands: 5
    include_git_branch: true

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
qwen> ask_qwen "Generate unit tests for this function"

# Ask local Ollama for privacy
qwen> ask_local "Analyze this code" --model codellama

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
task = await ai.ask_local("Analyze entire codebase", async_mode=True)
# ... do other work ...
result = await task

# Search history
results = await ai.search_history("git commands")
```

---

## Benefits

### For Users

1. **Intelligent Assistance**: AI knows shell context (errors, git, commands)
2. **Multi-AI Support**: Choose best AI for task (Claude for explanation, Qwen for code)
3. **Offline Option**: Use local Ollama for privacy
4. **Searchable History**: Find past AI conversations

### For Developers

1. **Simple API**: One interface for all AI providers
2. **MCP Abstraction**: No direct API integration needed
3. **Existing Infrastructure**: Leverage Session-Buddy LLM tools
4. **Secure**: Built-in security best practices

### For Operations

1. **Centralized Configuration**: All AI providers in one place
2. **Rate Limiting**: Prevent API abuse
3. **Circuit Breaker**: Prevent cascading failures
4. **Monitoring**: Track usage, errors, performance

---

## Risks & Mitigations

### Risk 1: API Key Exposure

**Mitigation**:
- Keys stored in environment variables only
- Masked in logs
- Validation via mcp-common.security

### Risk 2: Rate Limiting

**Mitigation**:
- Per-minute and per-hour limits
- Exponential backoff
- Circuit breaker for failing providers

### Risk 3: Cost Overruns

**Mitigation**:
- Smart provider selection (Qwen cheaper than Claude)
- Caching to reduce duplicate calls
- Context limits to reduce token usage

### Risk 4: Context Injection Attacks

**Mitigation**:
- Sanitize user input
- Limit context length
- Validate provider/model names
- Escape special characters

---

## Success Metrics

### Technical Metrics

- **Latency**: < 2s for simple queries (Haiku/Qwen)
- **Reliability**: 99% uptime (with fallback)
- **Cost**: < $10/month for moderate usage
- **Security**: Zero API key leaks

### User Metrics

- **Adoption**: 50% of users use AI commands
- **Satisfaction**: 4+ star rating
- **Retention**: 80% monthly active users
- **Usage**: 5+ AI calls per user per day

---

## Next Steps

### Immediate Actions

1. **Review Architecture**: Stakeholder approval
2. **Prioritize Features**: MVP vs advanced features
3. **Create Implementation Plan**: Detailed timeline
4. **Begin Development**: Phase 1 (core infrastructure)

### Long-Term Vision

1. **Multi-Shell Support**: Qwen, Claude, other shells
2. **Advanced Features**: Streaming, multi-turn conversations
3. **Analytics**: Usage tracking, popular queries
4. **Customization**: User-defined prompt templates

---

## Documentation

| Document | Purpose | Audience |
|----------|---------|----------|
| **AI_INTEGRATION_ARCHITECTURE.md** | Full architecture | Architects, senior developers |
| **AI_INTEGRATION_IMPLEMENTATION.md** | Implementation guide | Developers |
| **AI_INTEGRATION_QUICKREF.md** | Quick reference | All users |
| **AI_INTEGRATION_SUMMARY.md** | This document | Stakeholders, managers |

---

## Questions & Answers

### Q: Why MCP tools instead of direct API calls?

**A**: MCP abstraction provides:
- Unified interface for multiple providers
- Existing Session-Buddy infrastructure
- Automatic conversation storage
- Built-in fallback support

### Q: How are API keys secured?

**A**: Three layers:
1. Environment variables (never in code)
2. Session-Buddy settings (encrypted storage)
3. Masked logging (never show full key)

### Q: What happens when AI provider is down?

**A**: Automatic fallback:
1. Try primary provider (Claude)
2. If failed, try fallback (Qwen)
3. If failed, try local (Ollama)
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

## Conclusion

This architecture provides a **secure, scalable, and user-friendly** way to integrate AI capabilities into admin CLI shells. By leveraging existing Session-Buddy infrastructure via MCP tools, we can:

- **Reduce Development Time**: Use existing LLM management
- **Improve Reliability**: Built-in fallback and error handling
- **Enhance Security**: Proven security patterns
- **Enable Flexibility**: Easy to add new providers

**Recommendation**: Proceed with implementation following phased approach.

---

## Appendix: Related Projects

### Session-Buddy
**Location**: `/Users/les/Projects/session-buddy`
**Purpose**: Session management and LLM provider management
**Key Files**:
- `llm_providers.py` - LLM provider manager
- `mcp/tools/intelligence/llm_tools.py` - MCP tools for AI

### Mahavishnu
**Location**: `/Users/les/Projects/mahavishnu`
**Purpose**: Multi-engine orchestration platform
**Key Files**:
- `pools/` - Pool management for workers
- `terminal/` - Terminal management

### MCP Common
**Purpose**: Shared MCP utilities and security
**Key Features**:
- API key validation
- Security utilities
- MCP client/server helpers

---

**Status**: ✅ Architecture Complete
**Next Step**: Begin Phase 1 Implementation
**Contact**: AI Engineering Specialist
