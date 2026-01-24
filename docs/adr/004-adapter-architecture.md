# ADR 004: Adapter Architecture and Engine Integration

## Status
**Accepted**

## Context
Mahavishnu needs to support multiple orchestration engines (Airflow, CrewAI, LangGraph, Agno) with a unified interface. Each engine has different capabilities, APIs, and operational models.

### Requirements
1. **Unified Interface:** Common API across all engines
2. **Engine-Specific Features:** Access to unique capabilities of each engine
3. **Type Safety:** Pydantic models for configuration and results
4. **Observability:** Metrics and tracing for all operations
5. **Error Handling:** Consistent error handling across adapters
6. **Extensibility:** Easy to add new engines

### Options Considered

#### Option 1: Direct Engine API
- **Pros:** Full access to engine features
- **Cons:** Inconsistent interfaces, high coupling, difficult to switch engines

#### Option 2: Wrapper Classes
- **Pros:** Simple abstraction layer
- **Cons:** Limited to lowest common denominator, loses engine-specific features

#### Option 3: Abstract Base with Engine Extensions (CHOSEN)
- **Pros:**
  - Common interface via `OrchestratorAdapter` base class
  - Engine-specific extensions available via type casting
  - Pydantic models for type safety
  - Built-in observability and error handling
  - Easy to add new engines
- **Cons:**
  - More upfront design work
  - Need to maintain base class interface

## Decision
Use abstract base class `OrchestratorAdapter` with engine-specific implementations and extensions.

### Architecture

```python
from abc import ABC, abstractmethod
from typing import Any
from dataclasses import dataclass
from pydantic import BaseModel, Field

@dataclass
class AdapterResult:
    """Standard result type for adapter execution."""
    status: str  # "success", "failure", "partial"
    repos_processed: int
    repos_failed: int
    execution_time_seconds: float
    metadata: dict[str, Any]
    errors: list[str] | None = None
    engine_specific: dict[str, Any] | None = None

class OrchestratorAdapter(ABC):
    """Abstract base class for orchestrator adapters.

    All adapters must implement:
    - execute(): Core workflow execution
    - validate(): Validate task and repository configuration
    - get_health(): Check adapter health status

    Adapters may optionally implement:
    - Engine-specific methods for unique capabilities
    - Pre/post-execution hooks
    - Custom metrics collection
    """

    def __init__(self, config: MahavishnuSettings):
        """Initialize adapter with configuration.

        Args:
            config: Mahavishnu configuration
        """
        self.config = config
        self.stats = {
            "executions": 0,
            "successes": 0,
            "failures": 0,
            "retries": 0,
        }

    @abstractmethod
    async def execute(
        self,
        task: dict[str, Any],
        repos: list[str],
    ) -> AdapterResult:
        """Execute a task using the orchestrator engine.

        Args:
            task: Task specification with 'id', 'type', 'params' keys
            repos: List of repository paths to operate on

        Returns:
            AdapterResult with execution details

        Raises:
            ValidationError: If task or repos are invalid
            ExecutionError: If execution fails
        """
        pass

    @abstractmethod
    async def validate(
        self,
        task: dict[str, Any],
        repos: list[str],
    ) -> bool:
        """Validate task and repository configuration.

        Args:
            task: Task specification
            repos: List of repository paths

        Returns:
            True if valid

        Raises:
            ValidationError: If invalid
        """
        pass

    @abstractmethod
    async def get_health(self) -> dict[str, Any]:
        """Get adapter health status.

        Returns:
            Health status dictionary with 'status', 'details' keys
        """
        pass

    async def pre_execute_hook(
        self,
        task: dict[str, Any],
        repos: list[str],
    ) -> None:
        """Optional pre-execution hook.

        Override in subclasses for custom pre-execution logic.
        """
        pass

    async def post_execute_hook(
        self,
        result: AdapterResult,
    ) -> None:
        """Optional post-execution hook.

        Override in subclasses for custom post-execution logic.
        """
        pass
```

### Example Adapter: CrewAI

```python
from crewai import Crew, Agent, Task
from typing import Any

class CrewAIAdapter(OrchestratorAdapter):
    """Adapter for CrewAI orchestration engine.

    CrewAI-specific features:
    - Dynamic agent creation
    - Collaborative task execution
    - Tool integration
    """

    def __init__(self, config: MahavishnuSettings):
        super().__init__(config)
        self.llm_provider = config.crewai_llm_provider
        self.max_agents = config.crewai_max_agents

    async def execute(
        self,
        task: dict[str, Any],
        repos: list[str],
    ) -> AdapterResult:
        """Execute task using CrewAI crew.

        Creates a dynamic crew based on task type and executes
        across all repositories.

        Args:
            task: Task specification
            repos: List of repository paths

        Returns:
            AdapterResult with crew execution details
        """
        import time
        from opentelemetry import trace

        start_time = time.time()
        tracer = trace.get_tracer(__name__)

        with tracer.start_as_current_span("CrewAIAdapter.execute") as span:
            span.set_attribute("task.id", task.get("id"))
            span.set_attribute("task.type", task.get("type"))
            span.set_attribute("repos.count", len(repos))

            # Pre-execution hook
            await self.pre_execute_hook(task, repos)

            # Validate
            await self.validate(task, repos)

            # Create crew
            crew = await self._create_crew(task, repos)

            # Execute
            try:
                result = await crew.kickoff()

                execution_time = time.time() - start_time

                adapter_result = AdapterResult(
                    status="success",
                    repos_processed=len(repos),
                    repos_failed=0,
                    execution_time_seconds=execution_time,
                    metadata={
                        "crew_id": crew.id,
                        "agent_count": len(crew.agents),
                    },
                    engine_specific={
                        "crew_result": str(result),
                        "agent_outputs": {
                            agent.role: agent.output for agent in crew.agents
                        },
                    },
                )

                self.stats["executions"] += 1
                self.stats["successes"] += 1

            except Exception as e:
                execution_time = time.time() - start_time

                adapter_result = AdapterResult(
                    status="failure",
                    repos_processed=0,
                    repos_failed=len(repos),
                    execution_time_seconds=execution_time,
                    metadata={},
                    errors=[str(e)],
                )

                self.stats["executions"] += 1
                self.stats["failures"] += 1

                raise

            finally:
                # Post-execution hook
                await self.post_execute_hook(adapter_result)

            return adapter_result

    async def validate(
        self,
        task: dict[str, Any],
        repos: list[str],
    ) -> bool:
        """Validate task and repository configuration.

        Args:
            task: Task specification
            repos: List of repository paths

        Returns:
            True if valid

        Raises:
            ValidationError: If invalid
        """
        from pydantic import ValidationError

        # Validate task structure
        if "id" not in task:
            raise ValidationError("Task must have 'id' field")

        if "type" not in task:
            raise ValidationError("Task must have 'type' field")

        # Validate repos exist
        for repo in repos:
            if not Path(repo).exists():
                raise ValidationError(f"Repository not found: {repo}")

            if not Path(repo / ".git").exists():
                raise ValidationError(f"Not a git repository: {repo}")

        return True

    async def get_health(self) -> dict[str, Any]:
        """Get CrewAI adapter health status.

        Returns:
            Health status dictionary
        """
        try:
            # Test LLM connection
            from crewai import LLM

            llm = LLM(provider=self.llm_provider)
            health_status = await llm.health_check()

            return {
                "status": "healthy" if health_status else "degraded",
                "details": {
                    "llm_provider": self.llm_provider,
                    "max_agents": self.max_agents,
                    "executions": self.stats["executions"],
                    "successes": self.stats["successes"],
                    "failures": self.stats["failures"],
                },
            }

        except Exception as e:
            return {
                "status": "unhealthy",
                "details": {
                    "error": str(e),
                },
            }

    async def _create_crew(
        self,
        task: dict[str, Any],
        repos: list[str],
    ) -> Crew:
        """Create CrewAI crew based on task type.

        Args:
            task: Task specification
            repos: List of repository paths

        Returns:
            Configured CrewAI crew
        """
        task_type = task.get("type")

        if task_type == "code_sweep":
            return await self._create_sweep_crew(repos)
        elif task_type == "dependency_audit":
            return await self._create_audit_crew(repos)
        else:
            raise ValueError(f"Unknown task type: {task_type}")

    async def _create_sweep_crew(self, repos: list[str]) -> Crew:
        """Create crew for code sweep task.

        Args:
            repos: List of repository paths

        Returns:
            Configured CrewAI crew
        """
        from crewai import Agent, Task as CrewTask

        # Create agents
        code_analyzer = Agent(
            role="Code Analyzer",
            goal="Analyze code quality and identify issues",
            backstory="Expert code reviewer with deep knowledge of best practices",
            llm=self.llm_provider,
        )

        security_specialist = Agent(
            role="Security Specialist",
            goal="Identify security vulnerabilities",
            backstory="Security expert with experience in threat modeling",
            llm=self.llm_provider,
        )

        # Create tasks
        tasks = []
        for repo in repos:
            task = CrewTask(
                description=f"Analyze code in {repo}",
                expected_output="Detailed analysis report",
                agent=code_analyzer,
            )
            tasks.append(task)

        # Create crew
        crew = Crew(
            agents=[code_analyzer, security_specialist],
            tasks=tasks,
            verbose=True,
        )

        return crew

    # CrewAI-specific methods
    async def get_agent_status(self, crew_id: str) -> dict[str, Any]:
        """Get status of agents in a crew.

        This is a CrewAI-specific extension not available in other adapters.
        """
        # CrewAI-specific implementation
        pass

    async def add_tool_to_crew(
        self,
        crew_id: str,
        tool: Any,
    ) -> None:
        """Add a tool to an existing crew.

        This is a CrewAI-specific extension not available in other adapters.
        """
        # CrewAI-specific implementation
        pass
```

### Example Adapter: LangGraph

```python
from langgraph.graph import StateGraph
from typing import TypedDict

class LangGraphAdapter(OrchestratorAdapter):
    """Adapter for LangGraph orchestration engine.

    LangGraph-specific features:
    - Stateful workflow execution
    - Conditional routing
    - Checkpoint-based persistence
    """

    def __init__(self, config: MahavishnuSettings):
        super().__init__(config)
        self.checkpoint_dir = Path(config.langgraph_checkpoint_dir)
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

    async def execute(
        self,
        task: dict[str, Any],
        repos: list[str],
    ) -> AdapterResult:
        """Execute task using LangGraph workflow.

        Args:
            task: Task specification
            repos: List of repository paths

        Returns:
            AdapterResult with workflow execution details
        """
        import time
        from opentelemetry import trace

        start_time = time.time()
        tracer = trace.get_tracer(__name__)

        with tracer.start_as_current_span("LangGraphAdapter.execute") as span:
            span.set_attribute("task.id", task.get("id"))
            span.set_attribute("repos.count", len(repos))

            # Pre-execution hook
            await self.pre_execute_hook(task, repos)

            # Validate
            await self.validate(task, repos)

            # Build graph
            graph = await self._build_graph(task, repos)

            # Execute with checkpointing
            workflow_id = task.get("id", f"workflow-{int(time.time())}")
            checkpoint_path = self.checkpoint_dir / f"{workflow_id}.json"

            try:
                result = await graph.ainvoke(
                    initial_state={"repos": repos, "results": []},
                    config={"configurable": {"checkpoint_path": str(checkpoint_path)}},
                )

                execution_time = time.time() - start_time

                adapter_result = AdapterResult(
                    status="success",
                    repos_processed=len(repos),
                    repos_failed=0,
                    execution_time_seconds=execution_time,
                    metadata={
                        "workflow_id": workflow_id,
                        "checkpoint_path": str(checkpoint_path),
                        "nodes_visited": len(result.get("history", [])),
                    },
                    engine_specific={
                        "final_state": result,
                        "graph_structure": graph.get_graph().print_ascii(),
                    },
                )

                self.stats["executions"] += 1
                self.stats["successes"] += 1

            except Exception as e:
                execution_time = time.time() - start_time

                adapter_result = AdapterResult(
                    status="failure",
                    repos_processed=0,
                    repos_failed=len(repos),
                    execution_time_seconds=execution_time,
                    metadata={},
                    errors=[str(e)],
                )

                self.stats["executions"] += 1
                self.stats["failures"] += 1

                raise

            finally:
                # Post-execution hook
                await self.post_execute_hook(adapter_result)

            return adapter_result

    async def validate(
        self,
        task: dict[str, Any],
        repos: list[str],
    ) -> bool:
        """Validate task and repository configuration.

        Args:
            task: Task specification
            repos: List of repository paths

        Returns:
            True if valid

        Raises:
            ValidationError: If invalid
        """
        from pydantic import ValidationError

        # Validate task structure
        if "id" not in task:
            raise ValidationError("Task must have 'id' field")

        if "type" not in task:
            raise ValidationError("Task must have 'type' field")

        # Validate repos exist
        for repo in repos:
            if not Path(repo).exists():
                raise ValidationError(f"Repository not found: {repo}")

        return True

    async def get_health(self) -> dict[str, Any]:
        """Get LangGraph adapter health status.

        Returns:
            Health status dictionary
        """
        return {
            "status": "healthy",
            "details": {
                "checkpoint_dir": str(self.checkpoint_dir),
                "executions": self.stats["executions"],
                "successes": self.stats["successes"],
                "failures": self.stats["failures"],
            },
        }

    async def _build_graph(
        self,
        task: dict[str, Any],
        repos: list[str],
    ) -> StateGraph:
        """Build LangGraph workflow based on task type.

        Args:
            task: Task specification
            repos: List of repository paths

        Returns:
            Compiled LangGraph
        """
        from langgraph.graph import StateGraph, END
        from typing import Annotated
        from operator import add

        # Define state
        class WorkflowState(TypedDict):
            repos: list[str]
            results: Annotated[list, add]
            current_index: int

        # Define nodes
        async def process_repo(state: WorkflowState) -> dict:
            """Process a single repository."""
            repo = state["repos"][state["current_index"]]
            result = await self._process_single_repo(repo, task)
            return {"results": [result], "current_index": state["current_index"] + 1}

        async def should_continue(state: WorkflowState) -> str:
            """Check if there are more repos to process."""
            if state["current_index"] < len(state["repos"]):
                return "process"
            else:
                return END

        # Build graph
        graph = StateGraph(WorkflowState)
        graph.add_node("process", process_repo)
        graph.add_conditional_edges("process", should_continue)
        graph.set_entry_point("process")

        return graph.compile()

    async def _process_single_repo(
        self,
        repo: str,
        task: dict[str, Any],
    ) -> dict[str, Any]:
        """Process a single repository.

        Args:
            repo: Repository path
            task: Task specification

        Returns:
            Processing result
        """
        # Implementation depends on task type
        pass

    # LangGraph-specific methods
    async def get_workflow_checkpoint(
        self,
        workflow_id: str,
    ) -> dict[str, Any] | None:
        """Get checkpoint for a workflow.

        This is a LangGraph-specific extension leveraging checkpointing.
        """
        checkpoint_path = self.checkpoint_dir / f"{workflow_id}.json"

        if not checkpoint_path.exists():
            return None

        with open(checkpoint_path, "r") as f:
            import json
            return json.load(f)

    async def resume_workflow(
        self,
        workflow_id: str,
    ) -> AdapterResult:
        """Resume a workflow from checkpoint.

        This is a LangGraph-specific extension leveraging checkpointing.
        """
        # Implementation
        pass
```

## Consequences

### Positive
- Unified interface across all engines
- Type-safe with Pydantic models
- Built-in observability and error handling
- Engine-specific features accessible via extensions
- Easy to add new engines

### Negative
- More upfront design work
- Need to maintain base class interface
- Engine-specific features require type casting

### Risks
- **Risk:** Base class interface becomes limiting
  **Mitigation:** Use engine_specific field for custom data, allow extension methods

- **Risk:** Adapters diverge in behavior
  **Mitigation:** Comprehensive integration tests, strict interface compliance

## Implementation

### Phase 1: Base Adapter (Week 1, Day 5)
- [ ] Define `OrchestratorAdapter` abstract base class
- [ ] Define `AdapterResult` dataclass
- [ ] Add base methods with default implementations
- [ ] Add observability (metrics, tracing)

### Phase 2: CrewAI Adapter (Week 2, Day 1-3)
- [ ] Implement `CrewAIAdapter`
- [ ] Add crew creation logic
- [ ] Add agent management
- [ ] Add unit tests

### Phase 3: LangGraph Adapter (Week 2, Day 4-6)
- [ ] Implement `LangGraphAdapter`
- [ ] Add graph building logic
- [ ] Add checkpoint management
- [ ] Add unit tests

### Phase 4: Airflow & Agno (Week 3)
- [ ] Implement `AirflowAdapter`
- [ ] Implement `AgnoAdapter`
- [ ] Add integration tests

## References
- [CrewAI Documentation](https://docs.crewai.com/)
- [LangGraph Documentation](https://langchain-ai.github.io/langgraph/)
- [Apache Airflow Documentation](https://airflow.apache.org/docs/)
