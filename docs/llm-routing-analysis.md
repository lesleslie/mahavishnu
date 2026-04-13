# LLM Configuration and Routing Analysis for Bodai Ecosystem

**Date:** 2026-04-09  
**Scope:** Vishnu/Mahavishnu, Crackerjack, and Session-Buddy  
**Goal:** Understand current LLM setup, routing, and integration points for Bifrost gateway

## Executive Summary

The Bodai ecosystem uses a **unified OpenAI-compatible API approach** across all services. Each service has its own LLM configuration strategy with different default providers and fallback chains, but all ultimately interface through OpenAI-style APIs. This consistency makes it easier to integrate a universal LLM gateway like Bifrost.

## 1. Service LLM Configurations

### 1.1 Session-Buddy
**Primary file:** `session_buddy/llm_providers.py`

- **Default provider:** `"openai"`
- **Fallback chain:** `["anthropic", "gemini", "ollama"]`
- **Bifrost integration:** 
  - Detects `BIFROST_OPENAI_BASE_URL` and `BIFROST_ANTHROPIC_BASE_URL`
  - Uses Bifrost API keys when available
  - Models: `zai-openai/glm-5-turbo` (Bifrost) vs `gpt-4` (direct)

**Key characteristics:**
- Not local-Ollama-first - uses paid providers first
- Sophisticated provider management with config loading
- Direct OpenAI/Anthropic API paths when not using Bifrost
- MCP tools for operator-facing LLM management

### 1.2 Crackerjack
**Primary file:** `crackerjack/config/settings.py`

```python
class AISettings(Settings):
    ai_provider: t.Literal["claude", "qwen", "ollama"] = "claude"
    ai_providers: list[t.Literal["claude", "qwen", "ollama"]] = [
        "claude", "qwen", "ollama"
    ]
    ollama_base_url: str = "http://localhost: 11434"
    ollama_model: str = "qwen2.5-coder: 7b"
```

- **Default provider:** `"claude"`
- **Fallback chain:** `claude -> qwen -> ollama`
- **Execution:** External API calls (Anthropic/DashScope) + local Ollama for fixes

**Key characteristics:**
- Claude-first approach for quality
- Qwen via DashScope OpenAI-compatible API
- Ollama as local fallback for code fixes

### 1.3 Mahavishnu (Agno Adapter)
**Primary file:** `mahavishnu/engines/agno_adapter_impl.py`

```python
class AgnoLLMConfig(BaseModel):
    provider: LLMProvider = Field(
        default=LLMProvider.OLLAMA,
        description="LLM provider (anthropic, openai, ollama)",
    )
    model_id: str = Field(
        default="qwen2.5:7b",
        description="Model identifier",
    )
```

- **Default provider:** `LLMProvider.OLLAMA`
- **Default model:** `"qwen2.5:7b"`
- **Base URL:** `"http://localhost:11434"`
- **Multi-provider support:** Anthropic, OpenAI, Ollama

**Key characteristics:**
- Local-Ollama-first by default
- Multi-agent orchestration via Agno SDK
- Intelligent model routing based on task type

### 1.4 Mahavishnu (Ollama Worker)
**Primary file:** `mahavishnu/workers/ollama.py`

**Intelligent Model Routing:**
```python
DEFAULT_MODEL_ROUTING: dict[TaskCategory, str] = {
    TaskCategory.CODE_GENERATION: "qwen2.5-coder:7b",
    TaskCategory.CODE_REVIEW: "qwen2.5-coder:7b",
    TaskCategory.DEBUGGING: "qwen2.5-coder:7b",
    TaskCategory.REFACTORING: "qwen2.5-coder:7b",
    TaskCategory.TESTING: "qwen2.5-coder:7b",
    TaskCategory.REASONING: "llama3:8b",
    TaskCategory.CREATIVE: "llava:7b",
    TaskCategory.VISION: "llava:7b",
    TaskCategory.EMBEDDING: "nomic-embed-text",
    TaskCategory.GENERAL: "qwen2.5-coder:7b",
}
```

**Features:**
- Task classification based on prompt patterns
- Dynamic model selection based on availability
- Context-aware routing (image, embedding, etc.)

## 2. Bifrost Gateway Implementation

### 2.1 Current Status
- **Status:** Intentionally dormant (as of 2026-04-09)
- **Target port:** 8471
- **Client infrastructure:** Ready and implemented
- **LaunchAgents:** Removed from `~/Library/LaunchAgents`

### 2.2 Gateway Contract
**Files:** 
- `mahavishnu/llm_gateway/contract.py`
- `mahavishnu/llm_gateway/client.py`

**Key components:**
```python
class ProtocolFamily(StrEnum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"

class CacheMode(StrEnum):
    DIRECT = "direct"
    SEMANTIC = "semantic"
    OFF = "off"

class RouteClass(StrEnum):
    DEFAULT = "default"
    THINK = "think"
    BACKGROUND = "background"
    LONG_CONTEXT = "long_context"
    WEB_SEARCH = "web_search"
    IMAGE = "image"
    HIGH_THROUGHPUT = "high_throughput"
    CHEAP = "cheap"
```

### 2.3 Integration Points
**Gateway helpers:**
- `gateway_path()` - HTTP path for protocol family
- `gateway_api_base()` - Base URL for SDK clients
- `default_provider_for_protocol()` - Configured provider mapping
- `build_gateway_envelope()` - Complete request metadata

## 3. Embedded LLM Calls Analysis

### 3.1 Session-Buddy Embedded Calls
**Location:** `session_buddy/memory/entity_extractor.py`
```python
# Direct OpenAI path for structured memory extraction
direct AsyncOpenAI(...) path
# Cascade extraction engine
tries openai -> anthropic -> gemini -> pattern extraction
```

### 3.2 Crackerjack Embedded Calls
**Locations:**
- `crackerjack/adapters/ai/claude.py` - `anthropic.AsyncAnthropic(...)`
- `crackerjack/adapters/ai/qwen.py` - `openai.AsyncOpenAI(...)` against DashScope
- `crackerjack/services/doc_update_service.py` - `anthropic.Anthropic(...)`

### 3.3 Mahavishnu Embedded Calls
**Location:** `mahavishnu/engines/agno_adapter_impl.py`
```python
# Agno SDK integration
- OpenAIChat from agno.models.openai
- Claude from agno.models.anthropic  
- Ollama from agno.models.ollama
```

## 4. LLM Routing and Caching Setup

### 4.1 Current Routing Architecture
**All services use OpenAI-compatible APIs:**
- **Direct:** Native provider SDKs (Anthropic, OpenAI)
- **Via Ollama:** OpenAI-compatible endpoint at `http://localhost:11434/v1`
- **Via Bifrost:** Planned unified gateway

### 4.2 Task-Based Routing (Mahavishnu)
**Intelligent routing in `ollama.py`:**
1. Task classification using keyword patterns
2. Model selection based on category
3. Fallback matching by model family
4. Final fallback to config default

**Task categories:**
- CODE_GENERATION, CODE_REVIEW, DEBUGGING, REFACTORING
- DOCUMENTATION, TESTING, REASONING, CREATIVE, ANALYSIS
- VISION, EMBEDDING, GENERAL

### 4.3 Caching Strategy
**Bifrost cache modes:**
- **DIRECT:** Exact match caching
- **SEMANTIC:** Semantic similarity caching
- **OFF:** No caching

**Cache recommendations:**
- IMAGE tasks: Cache OFF
- WEB_SEARCH/THINK/LONG_CONTEXT: SEMANTIC if available
- Default: DIRECT

## 5. Integration Points for Bifrost Gateway

### 5.1 High-Priority Integration Points

#### Session-Buddy
**File:** `session_buddy/llm_providers.py`
- Already detects Bifrost URLs
- Needs configuration to prefer gateway
- Provider initialization logic needs gateway-aware routing

#### Crackerjack  
**File:** `crackerjack/config/settings.py`
- Add Bifrost provider option
- Update AI settings to support gateway
- Modify adapter calls to use gateway

#### Mahavishnu Agno Adapter
**File:** `mahavishnu/engines/agno_adapter_impl.py`
- Update LLM provider factory to use Bifrost client
- Integrate gateway contract for request building
- Update model selection logic

### 5.2 Medium-Priority Integration Points

#### Mahavishnu Ollama Worker
**File:** `mahavishnu/workers/ollama.py`
- Add Bifrost option for external models
- Keep local routing for pure Ollama scenarios
- Hybrid mode: local for supported models, gateway for others

#### Crackerjack Adapters
**Files:** `crackerjack/adapters/ai/*.py`
- Update each adapter to use gateway
- Maintain backward compatibility
- Add provider selection logic

### 5.3 Low-Priority Integration Points

#### OpenClaw Gateway
**File:** `mahavishnu/workers/openclaw_gateway.py`
- Bifrost integration for external model routing
- Keep local processing capability
- Gateway-aware health checks

## 6. GPT4All and llama.cpp Compatibility

### 6.1 Current Ollama Integration
All services already use Ollama's OpenAI-compatible API:
- Endpoint: `http://localhost:11434/v1`
- Standard OpenAI request/response format

### 6.2 GPT4All Integration Options
**Option 1: Via Ollama compatibility**
- GPT4All supports OpenAI-compatible API
- Configure base URL to GPT4All endpoint
- Minimal code changes required

**Option 2: Direct integration**
- Use GPT4All Python SDK directly
- More control over model selection
- Requires additional adapter logic

### 6.3 llama.cpp Integration
**Via Ollama-compatible server:**
- llama.cpp has OpenAI-compatible server mode
- Configure base URL to llama.cpp endpoint
- Same integration path as Ollama

**Direct integration:**
- Use llama.cpp Python bindings
- More performance control
- Additional complexity

## 7. Recommendations

### 7.1 Bifrost Gateway Integration
1. **Phase 1:** Enable gateway in Session-Buddy and Mahavishnu
2. **Phase 2:** Update Crackerjack adapters
3. **Phase 3:** Implement hybrid routing (local + gateway)

### 7.2 Model Configuration Recommendations
**Service-specific defaults:**
- **Session-Buddy:** Keep current, add Bifrost option
- **Crackerjack:** Consider local-first for CI/CD scenarios
- **Mahavishnu:** Keep local-first, add gateway for external models

### 7.3 GPT4All/llama.cpp Integration
1. Start with Ollama compatibility mode
2. Test performance with existing model routing
3. Consider direct integration for specialized use cases

### 7.4 Architecture Changes
**Unified gateway interface:**
```python
class LLMGateway:
    def create_request(self, task: dict) -> GatewayRequestEnvelope
    def execute(self, request: GatewayRequestEnvelope) -> Response
```

**Provider-agnostic routing:**
```python
@dataclass
class ProviderConfig:
    name: str
    type: str  # "local", "gateway", "direct"
    models: list[str]
    routing_rules: dict
```

## 8. Implementation Plan

### Phase 1: Gateway Activation (1-2 weeks)
1. Configure Bifrost LaunchAgent
2. Update Session-Buddy to use gateway by default
3. Update Mahavishnu Agno adapter
4. Test basic functionality

### Phase 2: Service Integration (2-3 weeks)
1. Update Crackerjack adapters
2. Implement hybrid routing
3. Add caching integration
4. Performance testing

### Phase 3: Advanced Features (1-2 weeks)
1. GPT4All/llama.cpp testing
2. Advanced routing rules
3. Monitoring and alerting
4. Documentation updates

## 9. Critical Success Factors

1. **Backward compatibility** - All existing functionality must continue working
2. **Performance** - Gateway should not introduce significant latency
3. **Reliability** - Fallback mechanisms for gateway failures
4. **Monitoring** - Clear visibility into gateway vs direct API usage
5. **Configuration** - Easy switching between gateway and direct modes