# SONA Router Documentation

## Overview

The **Self-Opting Neural Architecture (SONA) Router** is an intelligent adapter routing system that learns from past executions to make optimal routing decisions. It uses a neural network to analyze task features and predict the best orchestration adapter for each task.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Task Input                               │
│  (description, files, tokens, scheduled, etc.)              │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│              Feature Extraction (9 dims)                     │
│  • num_files, total_tokens, has_rag                        │
│  • has_state_machine, has_human_loop, is_scheduled         │
│  • needs_deployment, complexity_keywords, urgency           │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│           Neural Network (Feedforward)                      │
│  Input(9) → Hidden(16) → Hidden(8) → Output(4)             │
│  ReLU + Dropout → Softmax                                   │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│         Adapter Selection (4 adapters)                      │
│  • llamaindex: RAG and knowledge bases                      │
│  • agno: Agent-based workflows                              │
│  • langgraph: State machine orchestration                   │
│  • prefect: Scheduled workflows                             │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│              RouteDecision                                  │
│  • adapter_id, confidence, reason                           │
│  • neural_score, expected_quality, learning_data            │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
              Task Execution
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│            Outcome Learning                                 │
│  • Compute loss based on actual quality                     │
│  • Update neural network weights                            │
│  • Compute Fisher Information Matrix (EWC++)                │
│  • Prevent catastrophic forgetting                          │
└─────────────────────────────────────────────────────────────┘
```

## Key Components

### 1. SimpleNeuralNetwork

A feedforward neural network with configurable architecture:

```python
network = SimpleNeuralNetwork(
    input_dim=9,           # Number of task features
    hidden_layers=[16, 8], # Hidden layer sizes
    output_dim=4,          # Number of adapters
    dropout=0.1            # Dropout rate
)
```

**Features:**
- Xavier initialization for stable training
- ReLU activation for hidden layers
- Softmax output for adapter probabilities
- Dropout for regularization

### 2. EWCPlus (Elastic Weight Consolidation)

Prevents catastrophic forgetting in continual learning:

```python
ewc = EWCPlus(
    network=network,
    lambda_=0.5  # Regularization strength
)
```

**Features:**
- Fisher Information Matrix tracks parameter importance
- Optimal parameters saved for each task
- Regularization penalty protects important weights
- Enables continual learning without forgetting

### 3. SONARouter

Main router class that orchestrates everything:

```python
router = SONARouter(config=SONAConfig())
decision = await router.route_task(task)
await router.learn_from_outcome(task_id, outcome)
```

**Features:**
- Task feature extraction
- Neural network routing
- Explainable decisions
- Continual learning
- Model persistence

## Configuration

### SONAConfig

```python
from mahavishnu.core.learning_router import (
    SONAConfig,
    NeuralNetworkConfig,
    EWCConfig
)

config = SONAConfig(
    neural_network=NeuralNetworkConfig(
        input_dim=9,
        hidden_layers=[16, 8],
        dropout=0.1,
        activation="relu"
    ),
    ewc=EWCConfig(
        lambda_=0.5,
        update_frequency=100
    ),
    session_buddy=SessionBuddyConfig(
        enabled=True,
        history_window=1000,
        track_outcomes=True
    ),
    learning_rate=0.001,
    update_frequency=100,
    history_window=1000
)
```

### Configuration via YAML

```yaml
# settings/mahavishnu.yaml
sona:
  enabled: true
  neural_network:
    input_dim: 9
    hidden_layers: [16, 8]
    dropout: 0.1
    activation: "relu"
  ewc:
    lambda_: 0.5
    update_frequency: 100
  session_buddy:
    enabled: true
    history_window: 1000
    track_outcomes: true
  learning_rate: 0.001
  update_frequency: 100
  history_window: 1000
```

## Usage

### Basic Routing

```python
from mahavishnu.core.learning_router import SONARouter

# Initialize router
router = SONARouter()

# Route a task
task = {
    "description": "Build RAG pipeline for document search",
    "files": ["rag.py", "embeddings.py"],
    "estimated_tokens": 5000,
    "scheduled": False
}

decision = await router.route_task(task)

print(f"Adapter: {decision.adapter_id.value}")
print(f"Confidence: {decision.confidence:.2%}")
print(f"Reason: {decision.reason}")
print(f"Expected Quality: {decision.expected_quality:.2%}")
```

### Learning from Outcomes

```python
# After task execution, learn from the outcome
await router.learn_from_outcome("task_1", {
    "quality": 0.9,
    "execution_time": 2.5,
    "success": True,
    "adapter_used": "llamaindex"
})
```

### Statistics

```python
stats = router.get_statistics()

print(f"Total routes: {stats['total_routes']}")
print(f"Average confidence: {stats['avg_confidence']:.2%}")
print(f"Adapter distribution:")
for adapter, count in stats['adapter_distribution'].items():
    print(f"  {adapter}: {count}")
```

### Model Persistence

```python
# Save model
await router.save_model("models/sona_router.json")

# Load model
new_router = SONARouter()
await new_router.load_model("models/sona_router.json")
```

## Task Features

The router extracts 9 features from each task:

1. **num_files**: Number of files affected
2. **total_tokens**: Estimated token count
3. **has_rag**: Whether task requires RAG (keyword: "rag")
4. **has_state_machine**: Whether task needs state management (keyword: "state")
5. **has_human_loop**: Whether task has human-in-the-loop (keyword: "human")
6. **is_scheduled**: Whether task is scheduled (boolean)
7. **needs_deployment**: Whether task needs deployment (keyword: "deploy")
8. **complexity_keywords**: Normalized complexity keyword count (0-1)
9. **urgency**: Whether task is urgent (keyword: "urgent")

### Complexity Keywords

The following keywords indicate complexity:
- "architecture"
- "design"
- "security"
- "performance"
- "migration"
- "optimization"
- "scalability"

## Routing Decision

The `RouteDecision` object contains:

```python
class RouteDecision(BaseModel):
    adapter_id: AdapterType        # Selected adapter
    confidence: float               # Confidence score (0-1)
    reason: str                     # Human-readable explanation
    neural_score: float             # Raw neural network output
    expected_quality: float         # Expected quality (0-1)
    learning_data: dict[str, Any]   # Data for learning
```

## Explainability

Each routing decision includes a human-readable explanation:

```
Selected llamaindex - task requires RAG, neural confidence: 0.85
Selected agno - task needs state management, task is scheduled, neural confidence: 0.72
Selected prefect - task is scheduled, neural confidence: 0.68
```

## Continual Learning

### EWC++ Algorithm

1. **Task Completion**: After each task, update optimal parameters
2. **Fisher Matrix**: Compute Fisher Information Matrix periodically
3. **Regularization**: Apply EWC penalty to protect important weights
4. **Prevent Forgetting**: Balance new learning with previous knowledge

### Learning Workflow

```python
# 1. Route task
decision = await router.route_task(task)

# 2. Execute task with selected adapter
result = await adapter.execute(task, repos)

# 3. Learn from outcome
await router.learn_from_outcome(task_id, {
    "quality": compute_quality(result),
    "execution_time": result["duration"],
    "success": result["success"]
})

# 4. Periodically update EWC
if task_count % update_frequency == 0:
    ewc.update_optimal_params()
```

## Performance

### Target Metrics

- **Routing Accuracy**: 89%
- **Average Confidence**: >70%
- **Expected Quality**: >80%
- **Continual Learning**: No catastrophic forgetting

### Optimization Techniques

1. **Batch Processing**: Route multiple tasks in parallel
2. **GPU Acceleration**: Use GPU for neural network inference
3. **Caching**: Cache routing decisions for similar tasks
4. **Model Compression**: Quantize model for faster inference

## Integration

### With MahavishnuApp

```python
from mahavishnu.core.app import MahavishnuApp
from mahavishnu.core.learning_router import SONARouter

app = MahavishnuApp()
app.sona_router = SONARouter()

# Use SONA for routing
async def execute_workflow(task, repos):
    decision = await app.sona_router.route_task(task)
    adapter = app.get_adapter(decision.adapter_id.value)
    result = await adapter.execute(task, repos)

    # Learn from outcome
    await app.sona_router.learn_from_outcome(task["id"], {
        "quality": result["quality"],
        "success": result["success"]
    })

    return result
```

### MCP Integration

```python
@mcp.tool()
async def route_task_with_sona(task: dict) -> dict:
    """Route task using SONA neural router."""
    router = app.sona_router
    decision = await router.route_task(task)

    return {
        "adapter": decision.adapter_id.value,
        "confidence": decision.confidence,
        "reason": decision.reason,
        "expected_quality": decision.expected_quality
    }
```

## Production Checklist

- [ ] Replace SimpleNeuralNetwork with TensorFlow/PyTorch
- [ ] Implement real backpropagation with autograd
- [ ] Compute actual Fisher Information Matrix
- [ ] Integrate with Session-Buddy for history
- [ ] Add OpenTelemetry tracing
- [ ] Monitor routing accuracy
- [ ] Set up alerts for low-confidence routes
- [ ] Implement A/B testing for routing decisions
- [ ] Add ensemble routing with multiple networks
- [ ] Deploy with GPU acceleration

## Troubleshooting

### Low Confidence Scores

If routing confidence is consistently low (<50%):

1. Check feature extraction - ensure task metadata is complete
2. Verify neural network architecture - try larger hidden layers
3. Increase training data - route more tasks
4. Adjust learning rate - try higher or lower values

### Catastrophic Forgetting

If router forgets previous tasks:

1. Increase EWC lambda_ (e.g., 0.5 → 0.8)
2. Decrease update frequency (e.g., 100 → 50)
3. Implement experience replay
4. Use ensemble of networks

### Poor Routing Accuracy

If accuracy is below target (<80%):

1. Add more task features
2. Improve feature extraction
3. Train neural network on historical data
4. Implement active learning for uncertain cases
5. Use ensemble routing

## References

- [Elastic Weight Consolidation Paper](https://arxiv.org/abs/1612.00796)
- [Continual Learning Survey](https://arxiv.org/abs/1910.01468)
- [Neural Architecture Search](https://arxiv.org/abs/1808.05377)

## License

Apache License 2.0 - See LICENSE file for details
