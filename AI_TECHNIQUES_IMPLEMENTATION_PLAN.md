# AI Techniques Implementation Plan

**Date**: 2025-01-24
**Status**: 📋 Planning
**Timeline**: 7-10 weeks
**Priority**: High

---

## Executive Summary

This plan integrates cutting-edge AI techniques into Mahavishnu to achieve:
- **80% faster** repository analysis through multi-layer caching
- **60% reduction** in LLM API costs via semantic caching
- **Intelligent reasoning** with ReAct, Reflexion, and Tree of Thoughts
- **Multi-agent orchestration** for complex problem-solving

**Key Benefits**:
- Leverages Oneiric's production-ready cache adapters (Redis + Memory)
- JSON serialization for security (no pickle vulnerabilities)
- Phased implementation with measurable milestones
- Minimal external dependencies (uses existing stack)

---

## Table of Contents

1. [Phase 1: Multi-Layer Caching](#phase-1-multi-layer-caching)
2. [Phase 2: Advanced Reasoning](#phase-2-advanced-reasoning)
3. [Phase 3: Multi-Agent Optimization](#phase-3-multi-agent-optimization)
4. [Security Considerations](#security-considerations)
5. [Configuration](#configuration)
6. [Testing Strategy](#testing-strategy)
7. [Success Metrics](#success-metrics)

---

## Phase 1: Multi-Layer Caching

**Timeline**: 2-3 weeks
**Dependencies**: Oneiric v0.3.12 (already installed)
**Impact**: 80% performance improvement for repeated operations

### Architecture

```
┌─────────────────────────────────────────────────────────┐
│                   CacheManager                          │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐ │
│  │  L1: Memory  │  │  L2: Redis   │  │  L3: Semantic│ │
│  │              │  │              │  │              │ │
│  │ • < 1ms      │  │ • < 10ms     │  │ • Similarity │ │
│  │ • 1000 items │  │ • 10K items  │  │ • Embeddings │ │
│  │ • LRU        │  │ • TTL        │  │ • 100K items │ │
│  └──────────────┘  └──────────────┘  └──────────────┘ │
│         │                  │                  │        │
│         └──────────────────┴──────────────────┘        │
│                            │                           │
│                    Promotion/Demotion                  │
└─────────────────────────────────────────────────────────┘
```

### Implementation

#### 1.1 Cache Manager

```python
# mahavishnu/cache/manager.py
from typing import Optional, TypeVar, Any
from oneiric.adapters.cache.redis import RedisCacheAdapter, RedisCacheSettings
from oneiric.adapters.cache.memory import MemoryCacheAdapter, MemoryCacheSettings
import json
import structlog

logger = structlog.get_logger(__name__)
T = TypeVar('T')

class CacheManager:
    """Multi-layer cache with L1 (memory) and L2 (Redis)."""

    def __init__(self, config: Any):
        self.config = config
        self.memory_adapter: Optional[MemoryCacheAdapter] = None
        self.redis_adapter: Optional[RedisCacheAdapter] = None
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize cache layers."""
        # L1: Memory cache (fastest)
        if self.config.cache.memory_enabled:
            memory_settings = MemoryCacheSettings(
                max_entries=1000,
                default_ttl=300  # 5 minutes
            )
            self.memory_adapter = MemoryCacheAdapter(memory_settings)
            await self.memory_adapter.init()
            logger.info("L1 memory cache initialized")

        # L2: Redis cache (persistent)
        if self.config.cache.redis_enabled:
            redis_settings = RedisCacheSettings(
                host=self.config.cache.redis_host,
                port=self.config.cache.redis_port,
                default_ttl=3600,  # 1 hour
                max_connections=20
            )
            self.redis_adapter = RedisCacheAdapter(redis_settings)
            await self.redis_adapter.init()
            logger.info("L2 Redis cache initialized")

        self._initialized = True

    async def get(self, key: str, layer: int = 1) -> Optional[T]:
        """Get value from cache (checks L1, then L2)."""
        if not self._initialized:
            await self.initialize()

        # Check L1 (memory)
        if layer <= 1 and self.memory_adapter:
            value = await self.memory_adapter.get(key)
            if value is not None:
                logger.debug("L1 cache hit", key=key)
                # Safe JSON deserialization
                if isinstance(value, str):
                    value = json.loads(value)
                return value

        # Check L2 (Redis)
        if layer <= 2 and self.redis_adapter:
            value = await self.redis_adapter.get(key)
            if value is not None:
                logger.debug("L2 cache hit", key=key)
                # Safe JSON deserialization
                if isinstance(value, (str, bytes)):
                    value = json.loads(value)
                # Promote to L1
                if self.memory_adapter:
                    await self.memory_adapter.set(key, json.dumps(value))
                return value

        logger.debug("Cache miss", key=key)
        return None

    async def set(
        self,
        key: str,
        value: Any,
        ttl: Optional[int] = None
    ) -> None:
        """Set value in all cache layers."""
        if not self._initialized:
            await self.initialize()

        # Safe JSON serialization
        serialized = json.dumps(value)

        # Set in L1
        if self.memory_adapter:
            await self.memory_adapter.set(key, serialized, ttl)

        # Set in L2
        if self.redis_adapter:
            await self.redis_adapter.set(key, serialized, ttl)

    async def delete(self, key: str) -> None:
        """Delete from all cache layers."""
        if self.memory_adapter:
            await self.memory_adapter.delete(key)
        if self.redis_adapter:
            await self.redis_adapter.delete(key)

    async def clear(self) -> None:
        """Clear all cache layers."""
        if self.memory_adapter:
            await self.memory_adapter.clear()
        if self.redis_adapter:
            await self.redis_adapter.clear()

    async def health(self) -> dict[str, Any]:
        """Health check for all cache layers."""
        health = {"status": "healthy", "layers": {}}

        if self.memory_adapter:
            health["layers"]["memory"] = await self.memory_adapter.health()

        if self.redis_adapter:
            health["layers"]["redis"] = await self.redis_adapter.health()

        return health

    async def cleanup(self) -> None:
        """Cleanup cache adapters."""
        if self.memory_adapter:
            await self.memory_adapter.cleanup()
        if self.redis_adapter:
            await self.redis_adapter.cleanup()
        self._initialized = False
```

#### 1.2 Semantic Cache

```python
# mahavishnu/cache/semantic.py
from typing import List, Dict, Any, Optional
from sentence_transformers import SentenceTransformer
import numpy as np
import structlog

logger = structlog.get_logger(__name__)

class SemanticCache:
    """Semantic cache using vector similarity."""

    def __init__(self, config: Any):
        self.config = config
        self.model = None  # Lazy load
        self.embeddings: List[np.ndarray] = []
        self.keys: List[str] = []
        self.values: List[Any] = []
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize sentence transformer model."""
        if self._initialized:
            return

        # Load model (all-MiniLM-L6-v2 is fast and accurate)
        self.model = SentenceTransformer('all-MiniLM-L6-v2')
        self._initialized = True
        logger.info("Semantic cache initialized")

    def _encode(self, text: str) -> np.ndarray:
        """Encode text to embedding."""
        if not self._initialized:
            raise RuntimeError("Semantic cache not initialized")
        return self.model.encode(text, convert_to_numpy=True)

    def _similarity(self, emb1: np.ndarray, emb2: np.ndarray) -> float:
        """Calculate cosine similarity."""
        return np.dot(emb1, emb2) / (
            np.linalg.norm(emb1) * np.linalg.norm(emb2)
        )

    async def get(self, query: str, threshold: float = 0.85) -> Optional[Any]:
        """Get semantically similar cached result."""
        if not self._initialized:
            await self.initialize()

        if not self.embeddings:
            return None

        query_emb = self._encode(query)

        # Find most similar
        similarities = [
            self._similarity(query_emb, cached_emb)
            for cached_emb in self.embeddings
        ]

        max_idx = int(np.argmax(similarities))
        max_sim = similarities[max_idx]

        if max_sim >= threshold:
            logger.debug(
                "Semantic cache hit",
                similarity=max_sim,
                key=self.keys[max_idx]
            )
            return self.values[max_idx]

        logger.debug("Semantic cache miss", max_similarity=max_sim)
        return None

    async def set(self, key: str, value: Any) -> None:
        """Store key-value pair with embedding."""
        if not self._initialized:
            await self.initialize()

        embedding = self._encode(key)
        self.embeddings.append(embedding)
        self.keys.append(key)
        self.values.append(value)

        # Limit to 100K entries
        if len(self.keys) > 100000:
            self.embeddings.pop(0)
            self.keys.pop(0)
            self.values.pop(0)

    async def clear(self) -> None:
        """Clear all semantic cache entries."""
        self.embeddings.clear()
        self.keys.clear()
        self.values.clear()
```

#### 1.3 Cache Decorators

```python
# mahavishnu/cache/decorators.py
from functools import wraps
from typing import Callable, Any
import hashlib
import json

def cached_llm(ttl: int = 3600):
    """Cache LLM responses (default: 1 hour)."""
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(self, *args, **kwargs):
            # Generate cache key
            key_data = f"{func.__name__}:{args}:{kwargs}"
            key = hashlib.sha256(key_data.encode()).hexdigest()

            # Check cache
            cached = await self.cache_manager.get(key)
            if cached is not None:
                return cached

            # Call function
            result = await func(self, *args, **kwargs)

            # Cache result
            await self.cache_manager.set(key, result, ttl)

            return result
        return wrapper
    return decorator

def cached_repo_analysis(ttl: int = 7200):
    """Cache repository analysis (default: 2 hours)."""
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(self, repo_path: str, *args, **kwargs):
            # Generate cache key based on repo path and commit hash
            import subprocess
            commit_hash = subprocess.check_output(
                ['git', 'rev-parse', 'HEAD'],
                cwd=repo_path
            ).decode().strip()

            key_data = f"{func.__name__}:{repo_path}:{commit_hash}"
            key = hashlib.sha256(key_data.encode()).hexdigest()

            # Check cache
            cached = await self.cache_manager.get(key)
            if cached is not None:
                logger.info("Repository analysis cache hit", repo=repo_path)
                return cached

            # Call function
            result = await func(self, repo_path, *args, **kwargs)

            # Cache result
            await self.cache_manager.set(key, result, ttl)

            return result
        return wrapper
    return decorator

def semantically_cached(threshold: float = 0.85):
    """Cache using semantic similarity."""
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(self, query: str, *args, **kwargs):
            # Check semantic cache
            cached = await self.semantic_cache.get(query, threshold)
            if cached is not None:
                return cached

            # Call function
            result = await func(self, query, *args, **kwargs)

            # Cache result
            await self.semantic_cache.set(query, result)

            return result
        return wrapper
    return decorator
```

### Configuration

```yaml
# settings/mahavishnu.yaml
cache:
  enabled: true

  # L1: Memory cache
  memory_enabled: true
  memory_max_entries: 1000
  memory_ttl: 300  # 5 minutes

  # L2: Redis cache
  redis_enabled: true
  redis_host: "localhost"
  redis_port: 6379
  redis_ttl: 3600  # 1 hour
  redis_max_connections: 20

  # L3: Semantic cache
  semantic_enabled: true
  semantic_threshold: 0.85  # Cosine similarity
  semantic_model: "all-MiniLM-L6-v2"
```

### Success Criteria

- [ ] CacheManager supports L1 (memory) and L2 (Redis)
- [ ] SemanticCache achieves >60% hit rate for similar queries
- [ ] Repository analysis 80% faster on second run
- [ ] LLM API calls reduced by 60% through caching
- [ ] All serialization uses JSON (no pickle)

---

## Phase 2: Advanced Reasoning

**Timeline**: 3-4 weeks
**Dependencies**: Agno (already installed)
**Impact**: Intelligent problem-solving with systematic reasoning

### Frameworks Implemented

#### 2.1 ReAct Agent (Reasoning + Acting)

```python
# mahavishnu/agents/react.py
from typing import List, Dict, Any, Callable
import structlog

logger = structlog.get_logger(__name__)

class ReActAgent:
    """Agent that reasons and acts iteratively."""

    def __init__(self, tools: Dict[str, Callable], llm):
        self.tools = tools
        self.llm = llm
        self.max_iterations = 10

    async def solve(self, problem: str) -> Dict[str, Any]:
        """Solve problem using ReAct loop."""
        thoughts = []
        observations = []

        for i in range(self.max_iterations):
            # REASON: Generate thought
            thought = await self._think(problem, thoughts, observations)
            thoughts.append(thought)
            logger.info(f"Thought {i+1}", thought=thought)

            # ACT: Choose action
            action = await self._act(thought, thoughts, observations)

            if action["type"] == "finish":
                logger.info("Solution found", answer=action["answer"])
                return {
                    "answer": action["answer"],
                    "reasoning": thoughts,
                    "iterations": i + 1
                }

            # EXECUTE: Perform action
            result = await self._execute(action)
            observations.append(result)
            logger.info(f"Observation {i+1}", action=action["tool"], result=result)

        return {"error": "Max iterations reached", "reasoning": thoughts}

    async def _think(
        self,
        problem: str,
        thoughts: List[str],
        observations: List[Any]
    ) -> str:
        """Generate next thought using LLM."""
        context = self._build_context(problem, thoughts, observations)
        prompt = f"""Problem: {problem}

{context}

Thought: """
        response = await self.llm.generate(prompt)
        return response.strip()

    async def _act(
        self,
        thought: str,
        thoughts: List[str],
        observations: List[Any]
    ) -> Dict[str, str]:
        """Decide next action based on thought."""
        context = self._build_context("", thoughts, observations)
        prompt = f"""{context}

Thought: {thought}

Action: """
        response = await self.llm.generate(prompt)
        return self._parse_action(response.strip())

    async def _execute(self, action: Dict[str, str]) -> Any:
        """Execute action using available tools."""
        tool_name = action["tool"]
        tool_input = action.get("input", "")

        if tool_name not in self.tools:
            return f"Error: Unknown tool '{tool_name}'"

        tool = self.tools[tool_name]
        return await tool(tool_input)

    def _build_context(
        self,
        problem: str,
        thoughts: List[str],
        observations: List[Any]
    ) -> str:
        """Build context from previous steps."""
        lines = []
        if problem:
            lines.append(f"Problem: {problem}")

        for i, (thought, obs) in enumerate(zip(thought, observations), 1):
            lines.append(f"Thought {i}: {thought}")
            lines.append(f"Observation {i}: {obs}")

        return "\n".join(lines)

    def _parse_action(self, response: str) -> Dict[str, str]:
        """Parse action from LLM response."""
        # Expected format: "tool_name[input]" or "finish[answer]"
        if response.startswith("finish["):
            answer = response[7:-1]
            return {"type": "finish", "answer": answer}

        if "[" in response:
            tool, input = response.split("[", 1)
            return {"type": "action", "tool": tool.strip(), "input": input[:-1]}

        return {"type": "action", "tool": response, "input": ""}
```

#### 2.2 Reflexive Agent (Iterative Improvement)

```python
# mahavishnu/agents/reflexion.py
from typing import List, Dict, Any

class ReflexiveAgent:
    """Agent that reflects on its own reasoning and improves."""

    def __init__(self, llm):
        self.llm = llm
        self.max_reflections = 3

    async def solve(self, problem: str) -> Dict[str, Any]:
        """Solve problem with iterative refinement."""
        history = []

        for reflection_round in range(self.max_reflections + 1):
            # Generate solution
            solution = await self._generate_solution(problem, history)

            # Critique the solution
            critique = await self._critique(problem, solution, history)
            history.append({
                "round": reflection_round,
                "solution": solution,
                "critique": critique
            })

            logger.info(
                f"Reflection round {reflection_round}",
                solution=solution,
                critique=critique
            )

            # Check if satisfied
            if self._is_satisfied(critique):
                logger.info("Solution accepted after reflections", round=reflection_round)
                return {
                    "solution": solution,
                    "reflections": reflection_round,
                    "history": history
                }

        return {
            "solution": solution,
            "reflections": self.max_reflections,
            "history": history
        }

    async def _generate_solution(
        self,
        problem: str,
        history: List[Dict[str, Any]]
    ) -> str:
        """Generate solution based on problem and history."""
        prompt = f"Problem: {problem}\n"
        if history:
            prompt += "\nPrevious attempts:\n"
            for h in history:
                prompt += f"- {h['solution']}\n"
                prompt += f"  Critique: {h['critique']}\n"
        prompt += "\nProvide an improved solution:"

        return await self.llm.generate(prompt)

    async def _critique(
        self,
        problem: str,
        solution: str,
        history: List[Dict[str, Any]]
    ) -> str:
        """Critique the proposed solution."""
        prompt = f"""Problem: {problem}

Proposed Solution: {solution}

Critique this solution. What's good? What needs improvement? Be specific.
"""
        return await self.llm.generate(prompt)

    def _is_satisfied(self, critique: str) -> bool:
        """Check if critique indicates satisfaction."""
        satisfied_keywords = ["good", "excellent", "satisfactory", "optimal"]
        unsatisfied_keywords = ["improve", "lacks", "missing", "unclear", "better"]

        critique_lower = critique.lower()
        has_satisfied = any(kw in critique_lower for kw in satisfied_keywords)
        has_unsatisfied = any(kw in critique_lower for kw in unsatisfied_keywords)

        return has_satisfied and not has_unsatisfied
```

#### 2.3 Tree of Thoughts Solver

```python
# mahavishnu/agents/tot.py
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
import heapq

@dataclass
class ThoughtNode:
    """Node in the reasoning tree."""
    thought: str
    value: float  # Evaluation score
    parent: Optional['ThoughtNode'] = None
    children: List['ThoughtNode'] = None

    def __post_init__(self):
        if self.children is None:
            self.children = []

class ToTSolver:
    """Tree of Thoughts solver for systematic reasoning."""

    def __init__(self, llm, max_width: int = 5, max_depth: int = 4):
        self.llm = llm
        self.max_width = max_width
        self.max_depth = max_depth

    async def solve(self, problem: str) -> Dict[str, Any]:
        """Solve problem using Tree of Thoughts."""
        root = await self._generate_initial_thoughts(problem, breadth=self.max_width)

        for depth in range(self.max_depth):
            logger.info(f"ToT depth {depth + 1}", nodes=len(self._get_all_nodes(root)))

            # Expand best nodes
            candidates = self._select_best_nodes(root, top_k=3)

            for node in candidates:
                children = await self._expand_node(node, problem, breadth=self.max_width)
                node.children.extend(children)

            # Evaluate all new nodes
            await self._evaluate_batch(root, problem)

        # Return best solution
        best_node = self._find_best_node(root)
        solution_path = self._trace_path(best_node)

        return {
            "solution": best_node.thought,
            "value": best_node.value,
            "path": solution_path,
            "nodes_explored": len(self._get_all_nodes(root))
        }

    async def _generate_initial_thoughts(
        self,
        problem: str,
        breadth: int
    ) -> ThoughtNode:
        """Generate initial thoughts as root."""
        prompt = f"""Problem: {problem}

Generate {breadth} different initial approaches to solve this problem.
List each approach on a new line.
"""
        response = await self.llm.generate(prompt)
        thoughts = [t.strip() for t in response.split("\n") if t.strip()]

        # Create root with best thought as primary
        root = ThoughtNode(
            thought=thoughts[0] if thoughts else "No thoughts generated",
            value=0.0
        )

        # Add other thoughts as children
        for thought in thoughts[1:]:
            child = ThoughtNode(thought=thought, value=0.0, parent=root)
            root.children.append(child)

        # Evaluate initial thoughts
        await self._evaluate_batch(root, problem)

        return root

    async def _expand_node(
        self,
        node: ThoughtNode,
        problem: str,
        breadth: int
    ) -> List[ThoughtNode]:
        """Expand node with new thoughts."""
        prompt = f"""Problem: {problem}

Current approach: {node.thought}

Generate {breadth} next steps or refinements to this approach.
List each on a new line.
"""
        response = await self.llm.generate(prompt)
        thoughts = [t.strip() for t in response.split("\n") if t.strip()]

        return [
            ThoughtNode(thought=t, value=0.0, parent=node)
            for t in thoughts
        ]

    async def _evaluate_batch(self, root: ThoughtNode, problem: str) -> None:
        """Evaluate all unevaluated nodes."""
        nodes = self._get_all_nodes(root)

        for node in nodes:
            if node.value == 0.0:  # Not yet evaluated
                prompt = f"""Problem: {problem}

Approach: {node.thought}

Rate this approach from 0.0 to 1.0 based on:
- Likelihood of solving the problem
- Clarity and feasibility
- Efficiency

Respond with just the number:
"""
                response = await self.llm.generate(prompt)
                try:
                    node.value = float(response.strip())
                except ValueError:
                    node.value = 0.5

    def _select_best_nodes(self, root: ThoughtNode, top_k: int) -> List[ThoughtNode]:
        """Select top K nodes by value."""
        nodes = self._get_all_nodes(root)
        return heapq.nlargest(top_k, nodes, key=lambda n: n.value)[:top_k]

    def _find_best_node(self, root: ThoughtNode) -> ThoughtNode:
        """Find node with highest value."""
        nodes = self._get_all_nodes(root)
        return max(nodes, key=lambda n: n.value)

    def _trace_path(self, node: ThoughtNode) -> List[str]:
        """Trace path from root to node."""
        path = []
        current = node
        while current:
            path.append(current.thought)
            current = current.parent
        return list(reversed(path))

    def _get_all_nodes(self, root: ThoughtNode) -> List[ThoughtNode]:
        """Get all nodes in tree."""
        nodes = [root]
        queue = [root]

        while queue:
            current = queue.pop(0)
            nodes.extend(current.children)
            queue.extend(current.children)

        return nodes
```

### Success Criteria

- [ ] ReAct agent solves medium-complexity problems in <30 seconds
- [ ] Reflexive agent improves solutions across iterations
- [ ] ToT solver explores systematic reasoning paths
- [ ] All reasoning frameworks integrate with Agno

---

## Phase 3: Multi-Agent Optimization

**Timeline**: 2-3 weeks
**Dependencies**: Agno (already installed)
**Impact**: Parallel problem-solving with specialized agents

### Architecture

```
┌──────────────────────────────────────────────────────┐
│              AgentOrchestrator                       │
├──────────────────────────────────────────────────────┤
│                                                      │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐   │
│  │  Planner   │  │  Research  │  │  Executor  │   │
│  │  Agent     │  │  Agent     │  │  Agent     │   │
│  │            │  │            │  │            │   │
│  │ • Strategy │  │ • Info     │  │ • Tasks    │   │
│  │ • Decompose│  │ • Search   │  │ • Code     │   │
│  └────────────┘  └────────────┘  └────────────┘   │
│         │               │               │          │
│         └───────────────┴───────────────┘          │
│                      │                              │
│              Coordination                          │
│        (Hierarchical / Flat)                       │
└──────────────────────────────────────────────────────┘
```

### Implementation

```python
# mahavishnu/agents/orchestrator.py
from typing import List, Dict, Any, Literal
from enum import Enum
import structlog

logger = structlog.get_logger(__name__)

class CoordinationMode(str, Enum):
    HIERARCHICAL = "hierarchical"  # Manager delegates to workers
    FLAT = "flat"  # All agents collaborate as peers

class AgentOrchestrator:
    """Orchestrate multiple specialized agents."""

    def __init__(
        self,
        agents: Dict[str, Any],
        mode: CoordinationMode = CoordinationMode.HIERARCHICAL
    ):
        self.agents = agents
        self.mode = mode
        self.task_queue = []

    async def solve(self, problem: str, mode: CoordinationMode = None) -> Dict[str, Any]:
        """Solve problem using appropriate coordination mode."""
        mode = mode or self.mode

        if mode == CoordinationMode.HIERARCHICAL:
            return await self._solve_hierarchical(problem)
        else:
            return await self._solve_flat(problem)

    async def _solve_hierarchical(self, problem: str) -> Dict[str, Any]:
        """Hierarchical coordination: planner delegates to specialists."""
        logger.info("Starting hierarchical coordination", problem=problem)

        # Phase 1: Planning
        plan = await self.agents["planner"].plan(problem)
        logger.info("Plan generated", steps=len(plan.get("steps", [])))

        # Phase 2: Execution by specialists
        results = []
        for step in plan.get("steps", []):
            agent_type = step.get("agent", "executor")
            agent = self.agents.get(agent_type)

            if not agent:
                logger.warning(f"Agent not found: {agent_type}")
                continue

            result = await agent.execute(step)
            results.append(result)
            logger.info(f"Step completed", agent=agent_type, result=result.get("status"))

        # Phase 3: Synthesis
        final_result = await self.agents["planner"].synthesize(plan, results)

        return {
            "result": final_result,
            "plan": plan,
            "steps_completed": len(results)
        }

    async def _solve_flat(self, problem: str) -> Dict[str, Any]:
        """Flat coordination: all agents collaborate."""
        logger.info("Starting flat coordination", problem=problem)

        # All agents contribute
        contributions = {}
        for agent_name, agent in self.agents.items():
            try:
                contribution = await agent.contribute(problem)
                contributions[agent_name] = contribution
                logger.info(f"Contribution received", agent=agent_name)
            except Exception as e:
                logger.error(f"Agent failed", agent=agent_name, error=str(e))

        # Synthesize all contributions
        synthesis = await self._synthesize_contributions(problem, contributions)

        return {
            "result": synthesis,
            "contributions": contributions,
            "agents_participated": len(contributions)
        }

    async def _synthesize_contributions(
        self,
        problem: str,
        contributions: Dict[str, Any]
    ) -> str:
        """Synthesize contributions from all agents."""
        # Simple concatenation for now
        # In production, use LLM to synthesize
        parts = []
        for agent_name, contribution in contributions.items():
            parts.append(f"### {agent_name.title()}\n{contribution}")

        return "\n\n".join(parts)

# Specialized Agent Registry
SPECIALIZED_AGENTS = {
    "planner": {
        "description": "Decompose problems into steps",
        "tools": ["plan", "decompose", "synthesize"]
    },
    "researcher": {
        "description": "Gather information and search",
        "tools": ["search", "analyze", "summarize"]
    },
    "coder": {
        "description": "Write and review code",
        "tools": ["generate_code", "review", "refactor"]
    },
    "tester": {
        "description": "Design and run tests",
        "tools": ["generate_tests", "execute", "coverage"]
    },
    "debugger": {
        "description": "Diagnose and fix issues",
        "tools": ["diagnose", "fix", "verify"]
    },
    "executor": {
        "description": "Execute tasks and workflows",
        "tools": ["run", "monitor", "report"]
    }
}
```

### Success Criteria

- [ ] AgentOrchestrator supports hierarchical and flat coordination
- [ ] At least 5 specialized agents implemented
- [ ] Multi-agent solutions better than single-agent (>20% improvement)
- [ ] Integration with Agno workflow system

---

## Security Considerations

### Serialization Safety

**CRITICAL**: All caching uses JSON serialization, NOT pickle.

```python
# ✅ SAFE: JSON serialization
serialized = json.dumps(value)
value = json.loads(cached)

# ❌ UNSAFE: Pickle serialization (arbitrary code execution)
# serialized = pickle.dumps(value)
# value = pickle.loads(cached)
```

### Cache Key Security

```python
import hashlib

def sanitize_cache_key(key: str) -> str:
    """Generate safe cache key."""
    # Hash to prevent injection attacks
    return hashlib.sha256(key.encode()).hexdigest()
```

### LLM Input Validation

```python
def validate_llm_input(text: str, max_length: int = 10000) -> str:
    """Validate LLM input."""
    if len(text) > max_length:
        raise ValueError(f"Input too long: {len(text)} > {max_length}")

    # Remove potential injection patterns
    dangerous_patterns = ["<script>", "javascript:", "data:"]
    for pattern in dangerous_patterns:
        if pattern.lower() in text.lower():
            raise ValueError(f" Dangerous pattern detected: {pattern}")

    return text
```

---

## Configuration

### Complete Cache Configuration

```yaml
# settings/mahavishnu.yaml
cache:
  enabled: true

  # L1: Memory cache
  memory_enabled: true
  memory_max_entries: 1000
  memory_ttl: 300  # 5 minutes

  # L2: Redis cache
  redis_enabled: true
  redis_host: "localhost"
  redis_port: 6379
  redis_db: 0
  redis_password: null  # Set in production
  redis_ttl: 3600  # 1 hour
  redis_max_connections: 20

  # L3: Semantic cache
  semantic_enabled: true
  semantic_threshold: 0.85  # Cosine similarity
  semantic_model: "all-MiniLM-L6-v2"
  semantic_max_entries: 100000
```

### Agent Configuration

```yaml
# settings/mahavishnu.yaml
agents:
  # ReAct configuration
  react:
    enabled: true
    max_iterations: 10
    tools: ["search", "code", "test", "deploy"]

  # Reflexion configuration
  reflexion:
    enabled: true
    max_reflections: 3

  # Tree of Thoughts configuration
  tot:
    enabled: true
    max_width: 5
    max_depth: 4

  # Multi-agent orchestration
  orchestration:
    enabled: true
    mode: "hierarchical"  # hierarchical | flat
    agents: ["planner", "researcher", "coder", "tester", "executor"]
```

---

## Testing Strategy

### Unit Tests

```python
# tests/unit/test_cache_manager.py
import pytest

@pytest.mark.asyncio
async def test_cache_manager_l1_hit():
    """Test L1 cache hit."""
    manager = CacheManager(config)
    await manager.initialize()

    await manager.set("key1", "value1")
    value = await manager.get("key1", layer=1)

    assert value == "value1"

@pytest.mark.asyncio
async def test_cache_manager_l2_promotion():
    """Test L2 to L1 promotion."""
    manager = CacheManager(config)
    await manager.initialize()

    # Clear L1
    await manager.memory_adapter.clear()

    # Set in L2
    await manager.redis_adapter.set("key2", json.dumps("value2"))

    # Get should promote to L1
    value = await manager.get("key2")

    assert value == "value2"
    assert await manager.memory_adapter.get("key2") is not None

@pytest.mark.asyncio
async def test_semantic_cache_similarity():
    """Test semantic cache similarity."""
    cache = SemanticCache(config)
    await cache.initialize()

    await cache.set("What is Python?", "Python is a programming language.")
    value = await cache.get("Tell me about Python", threshold=0.85)

    assert value is not None
```

### Integration Tests

```python
# tests/integration/test_agents_integration.py
import pytest

@pytest.mark.integration
@pytest.mark.slow
async def test_react_agent_solving():
    """Test ReAct agent solving a problem."""
    agent = ReActAgent(tools=tools, llm=llm)

    result = await agent.solve("How do I read a file in Python?")

    assert "answer" in result
    assert result["iterations"] > 0

@pytest.mark.integration
@pytest.mark.slow
async def test_multi_agent_orchestration():
    """Test multi-agent orchestration."""
    orchestrator = AgentOrchestrator(
        agents=SPECIALIZED_AGENTS,
        mode=CoordinationMode.HIERARCHICAL
    )

    result = await orchestrator.solve("Create a REST API with FastAPI")

    assert "result" in result
    assert result["steps_completed"] > 0
```

### Performance Tests

```python
# tests/performance/test_cache_performance.py
import pytest
import time

@pytest.mark.performance
async def test_cache_performance_improvement():
    """Test cache improves performance."""
    manager = CacheManager(config)
    await manager.initialize()

    # First run (no cache)
    start = time.time()
    result1 = await expensive_operation(manager)
    time1 = time.time() - start

    # Second run (cached)
    start = time.time()
    result2 = await expensive_operation(manager)
    time2 = time.time() - start

    # Cached should be 80% faster
    assert time2 < time1 * 0.2
```

---

## Success Metrics

### Phase 1: Caching
- Cache hit rate: >60% for similar operations
- Performance: 80% faster repository analysis on cache hit
- Cost: 60% reduction in LLM API calls
- Reliability: >99% uptime for Redis

### Phase 2: Reasoning
- ReAct: Solve medium problems in <30 seconds
- Reflexion: Improve solutions across 2-3 iterations
- ToT: Explore 20+ reasoning paths
- Quality: >80% user satisfaction

### Phase 3: Multi-Agent
- Coordination: Support hierarchical and flat modes
- Performance: >20% better than single-agent
- Scalability: 5+ agents working in parallel
- Integration: Seamless Agno workflow integration

---

## Implementation Checklist

### Phase 1: Caching (2-3 weeks)
- [ ] Create `mahavishnu/cache/` module
- [ ] Implement `CacheManager` with L1/L2 support
- [ ] Implement `SemanticCache` with sentence transformers
- [ ] Implement cache decorators (`@cached_llm`, `@cached_repo_analysis`)
- [ ] Add Redis configuration to `MahavishnuSettings`
- [ ] Write unit tests for cache layers
- [ ] Write integration tests for end-to-end caching
- [ ] Document cache configuration in README
- [ ] Benchmark cache performance

### Phase 2: Reasoning (3-4 weeks)
- [ ] Create `mahavishnu/agents/` module
- [ ] Implement `ReActAgent` with thought/action/observation loop
- [ ] Implement `ReflexiveAgent` with iterative refinement
- [ ] Implement `ToTSolver` with systematic exploration
- [ ] Integrate with Agno workflow system
- [ ] Write unit tests for each reasoning framework
- [ ] Write integration tests for problem-solving
- [ ] Document reasoning patterns and usage
- [ ] Benchmark reasoning performance

### Phase 3: Multi-Agent (2-3 weeks)
- [ ] Implement `AgentOrchestrator` with hierarchical/flat modes
- [ ] Create specialized agent registry (planner, researcher, coder, etc.)
- [ ] Integrate with Agno multi-agent patterns
- [ ] Write unit tests for orchestration
- [ ] Write integration tests for multi-agent workflows
- [ ] Document agent specialization patterns
- [ ] Benchmark multi-agent vs single-agent performance

---

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| **Redis downtime** | Cache unavailability | Fallback to L1 memory cache |
| **Semantic model size** | Slow startup | Lazy load model on first use |
| **Agent complexity** | Hard to debug | Extensive logging and tracing |
| **LLM API costs** | Budget overrun | Aggressive caching, rate limiting |
| **Serialization bugs** | Data corruption | Use JSON (not pickle), validate schemas |

---

## Next Steps

1. **Review and approve** this implementation plan
2. **Set up Redis** for L2 cache (or use existing instance)
3. **Install sentence-transformers** for semantic cache:
   ```bash
   uv pip install sentence-transformers
   ```
4. **Begin Phase 1 implementation** with CacheManager
5. **Establish baseline metrics** before caching
6. **Iterate** through phases based on feedback

---

**Document Version**: 1.0
**Date**: 2025-01-24
**Status**: Ready for Implementation
**Total Timeline**: 7-10 weeks
