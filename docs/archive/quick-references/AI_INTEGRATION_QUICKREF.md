# AI Integration for Admin CLI Shells - Quick Reference

**Architecture**: MCP-first AI integration via Session-Buddy
**Status**: Ready for Implementation
**Last Updated**: 2025-02-06

---

## TL;DR Architecture

```
Shell → AI Integration Layer → Session-Buddy MCP → LLM Providers (Claude/Qwen/Ollama)
```

**Key Decision**: Use MCP tools (not direct API calls) for:
- Unified provider interface
- Existing Session-Buddy infrastructure
- Automatic conversation storage
- Built-in fallback support

---

## Quick Start Commands

### Shell Integration

```python
# 1. Initialize AI integration
from ai_integration import AIIntegration, ShellContextCollector

ai = AIIntegration(mcp_url="http://localhost:8678/mcp")
collector = ShellContextCollector(shell_type="qwen")

# 2. Register shell commands
@shell_command("ask_claude")
async def ask_claude(prompt: str, include_context: bool = True):
    context = await collector.collect() if include_context else None
    return await ai.ask_claude(prompt, context)

# 3. Use in shell
qwen> ask_claude "Explain this error"
qwen> ask_qwen "Generate tests for this function"
qwen> ask_local "How do I fix docker?" --model codellama
```

### Basic Usage

```python
# Simple question
response = await ai.ask_claude("What is 2+2?")

# With context (errors, commands, git branch)
context = await collector.collect()
response = await ai.ask_claude("Why did the test fail?", context)

# Async background mode
task = await ai.ask_local("Analyze codebase", async_mode=True)
# ... do other work ...
result = await task

# Specific provider/model
await ai.ask_qwen("Generate Python code", context, model="qwen-coder-plus")
```

---

## Architecture Patterns

### Pattern 1: MCP Abstraction

**Why**: Unified interface for multiple AI providers

**Implementation**:
```python
# Shell calls AI integration
response = await ai.ask_claude("Hello")

# AI integration calls MCP tool
result = await mcp.call_tool(
    "generate_with_llm",
    {"prompt": prompt, "provider": "anthropic"}
)

# MCP tool routes to LLM manager
# LLM manager calls provider API (Anthropic, Qwen, Ollama)
```

**Benefits**:
- Single interface for all providers
- Automatic fallback (Claude → Qwen → Ollama)
- Provider-specific configuration in one place
- Easy to add new providers

### Pattern 2: Context Injection

**Why**: AI needs shell state to give relevant answers

**Context Collected**:
- Current directory
- Git branch
- Last 3 errors
- Last 5 commands
- Current code buffer (optional)

**Implementation**:
```python
@dataclass
class ShellContext:
    current_directory: str
    git_branch: str | None
    last_errors: list[str]
    last_commands: list[str]
    environment: dict[str, str]
    code_context: str | None

# Enrich prompt with context
enriched = f"""
Context:
- Git branch: {context.git_branch}
- Last errors: {context.last_errors}
- Recent commands: {context.last_commands}

Question: {prompt}
"""
```

**Benefits**:
- AI gives shell-specific answers
- Automatic error context inclusion
- Relevant git/state information
- Better, more actionable responses

### Pattern 3: Hybrid Sync/Async

**Why**: Some commands need instant response, others can be background

**Sync (Blocking)**:
```python
response = await ai.ask_claude("Quick question")  # Wait for response
print(response)
```

**Async (Background)**:
```python
task = await ai.ask_claude("Long analysis", async_mode=True)
# ... do other work ...
response = await task  # Get result when ready
```

**Benefits**:
- Flexibility for different use cases
- Background work doesn't block shell
- User can choose execution mode

---

## Provider Selection Guide

| Provider | Best For | Model | Speed | Quality | Cost |
|----------|----------|-------|-------|---------|------|
| **Claude (Anthropic)** | Explanations, analysis | claude-3-5-haiku-20241022 | Fast | High | Medium |
| **Qwen** | Code generation, tests | qwen-coder-plus | Fast | High | Low |
| **OpenAI** | General purpose | gpt-4 | Medium | High | High |
| **Ollama (Local)** | Privacy, offline | llama2, codellama | Variable | Medium | Free |

**Auto-Selection Logic**:
```python
if "code" in prompt or "test" in prompt:
    provider = "qwen"  # Best for code
elif "explain" in prompt or "analyze" in prompt:
    provider = "claude"  # Best for explanations
else:
    provider = "anthropic"  # Default
```

---

## Security Checklist

### API Keys
- ✅ Stored in environment variables
- ✅ Loaded via Session-Buddy settings
- ✅ Masked in logs (never show full key)
- ✅ Validation via mcp-common.security

### Prompt Safety
- ✅ Sanitize user input (escape special chars)
- ✅ Limit context length (max 4000 tokens)
- ✅ Validate provider/model names (allowlist)
- ✅ Never include API keys in prompts

### Rate Limiting
- ✅ Per-minute limit (default: 60)
- ✅ Per-hour limit (default: 1000)
- ✅ Exponential backoff on errors
- ✅ Circuit breaker for failing providers

---

## Error Handling

### Transient Errors (Retry)
- Rate limit (429)
- Network timeout
- Provider unavailable (503)

**Strategy**: Exponential backoff (1s, 2s, 4s, max 3 retries)

### Permanent Errors (Fail Immediately)
- Invalid API key (401)
- Invalid request (400)
- Model not found (404)

**Strategy**: Show user error, don't retry

### Context Errors (Skip Context)
- Context too large
- Invalid context format

**Strategy**: Retry without context

---

## Configuration Files

### Shell Config
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
export SESSION_BUDDY_MCP_URL="http://localhost:8678/mcp"
```

---

## Common Commands

### Shell Commands
```bash
# Ask Claude (Anthropic)
ask_claude "Explain this error"

# Ask Qwen (Alibaba)
ask_qwen "Generate unit tests"

# Ask local Ollama
ask_local "Analyze this code" --model codellama

# Auto-select provider
ask "Generate tests"  # Selects Qwen automatically
ask "Explain error"   # Selects Claude automatically

# Search history
ai_history "docker commands"

# Provider status
ai_status
ai_test
```

### Python API
```python
# Initialize
from ai_integration import AIIntegration
ai = AIIntegration()

# Ask questions
await ai.ask_claude("Hello")
await ai.ask_qwen("Generate code")
await ai.ask_local("Analyze")

# With context
from ai_integration import ShellContextCollector
collector = ShellContextCollector()
context = await collector.collect()
await ai.ask_claude("Help with error", context)

# Search history
await ai.search_history("git commands")

# Provider status
await ai.mcp.call_tool("list_llm_providers", {})
await ai.mcp.call_tool("test_llm_providers", {})
```

---

## Troubleshooting

### Problem: MCP Connection Refused

**Symptoms**: `Connection refused` error

**Solution**:
```bash
# Start Session-Buddy MCP server
python -m session_buddy.server

# Verify it's running
curl http://localhost:8678/health
```

### Problem: API Key Not Found

**Symptoms**: `API key not configured`

**Solution**:
```bash
# Set environment variable
export ANTHROPIC_API_KEY="sk-ant-..."

# Or configure in Session-Buddy settings
# settings/session-buddy.yaml
llm:
  anthropic_api_key: "${ANTHROPIC_API_KEY}"
```

### Problem: Rate Limit Exceeded

**Symptoms**: `Rate limit: too many calls per minute`

**Solutions**:
1. Wait 60 seconds for rate limit reset
2. Increase rate limit in config
3. Enable caching to reduce API calls
4. Use faster model (Haiku instead of Sonnet)

### Problem: Context Too Large

**Symptoms**: `Context exceeds token limit`

**Solutions**:
1. Reduce context size (max_errors: 3 → 1)
2. Disable code context
3. Ask without context (`--no-context` flag)
4. Use model with higher token limit

---

## Performance Optimization

### Reduce Latency
1. **Use Fast Models**: Haiku (Claude) or Qwen-Coder
2. **Enable Caching**: Cache common queries
3. **Limit Context**: Only include necessary context
4. **Async Mode**: Background for long tasks

### Reduce API Costs
1. **Smart Provider Selection**: Qwen for code (cheaper)
2. **Caching**: Avoid duplicate calls
3. **Context Limits**: Reduce token usage
4. **Fallback**: Local Ollama for simple queries

### Improve Reliability
1. **Fallback Chain**: Claude → Qwen → Ollama
2. **Circuit Breaker**: Stop calling failing provider
3. **Retry Logic**: Exponential backoff
4. **Rate Limiting**: Prevent throttling

---

## Testing

### Unit Test
```python
@pytest.mark.asyncio
async def test_ask_claude():
    mcp = AsyncMock()
    mcp.call_tool.return_value = {"text": "Response"}

    ai = AIIntegration()
    ai.mcp = mcp

    response = await ai.ask_claude("Hello")
    assert "Response" in response
```

### Integration Test
```python
@pytest.mark.integration
async def test_real_ai_call():
    ai = AIIntegration(mcp_url="http://localhost:8678/mcp")

    response = await ai.ask_claude("What is 2+2?")
    assert "4" in response.lower()
```

---

## Implementation Checklist

### Phase 1: Core (Week 1-2)
- [ ] Create `AIIntegration` class
- [ ] Implement `ShellContextCollector`
- [ ] Add MCP tool wrapper
- [ ] Basic error handling

### Phase 2: Shell Integration (Week 3)
- [ ] Register shell commands
- [ ] Test context collection
- [ ] Add configuration support

### Phase 3: Production (Week 4)
- [ ] Add rate limiting
- [ ] Add circuit breaker
- [ ] Implement caching
- [ ] Security audit

### Phase 4: Advanced (Week 5+)
- [ ] Streaming responses
- [ ] Multi-turn conversations
- [ ] Analytics & monitoring

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
├── AI_INTEGRATION_ARCHITECTURE.md    # Full architecture
├── AI_INTEGRATION_IMPLEMENTATION.md  # Implementation guide
└── AI_INTEGRATION_QUICKREF.md        # This file
```

---

## Key Files Reference

| File | Purpose |
|------|---------|
| `ai_integration/core.py` | Main AIIntegration class |
| `ai_integration/context.py` | Shell context collection |
| `ai_integration/commands.py` | Shell command wrappers |
| `/session-buddy/llm_providers.py` | LLM provider manager |
| `/session-buddy/mcp/tools/intelligence/llm_tools.py` | MCP tools for AI |

---

## Related Documentation

- **Architecture**: AI_INTEGRATION_ARCHITECTURE.md
- **Implementation**: AI_INTEGRATION_IMPLEMENTATION.md
- **Session-Buddy**: /Users/les/Projects/session-buddy/README.md
- **MCP Protocol**: https://modelcontextprotocol.io
- **Anthropic API**: https://docs.anthropic.com
- **Qwen API**: https://dashscope.aliyun.com/docs

---

## Support

**Issues**: GitHub Issues
**Questions**: Create discussion
**Contributing**: Pull requests welcome

---

**Status**: Ready for Implementation
**Next Step**: Review architecture, begin Phase 1 development
