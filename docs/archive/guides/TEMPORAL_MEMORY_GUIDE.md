# Temporal Memory Guide

Comprehensive guide to using Mahavishnu's temporal knowledge graph for time-travel queries and historical analysis.

## Table of Contents

1. [Introduction](#introduction)
2. [Core Concepts](#core-concepts)
3. [Time-Travel Queries](#time-travel-queries)
4. [Episodic Memory](#episodic-memory)
5. [Advanced Patterns](#advanced-patterns)
6. [Performance Optimization](#performance-optimization)
7. [Real-World Examples](#real-world-examples)

---

## Introduction

Temporal Memory (Graphiti-inspired) enables you to:

- **Track entities over time**: See how nodes and edges evolved
- **Time-travel queries**: Query graph state at any point in history
- **Change tracking**: See what changed between two timestamps
- **Episodic memory**: Group related events into coherent sequences

### When to Use Temporal Memory

✅ **Great for**:
- Knowledge bases with versioning needs
- Audit trails and compliance
- Historical analysis and trends
- "What did the system look like at time T?" queries
- Causal analysis of events

❌ **Not ideal for**:
- Simple current-state graphs (use regular graph DB)
- Real-time only data (no history needed)
- Static schemas (no temporal evolution)

---

## Core Concepts

### TimeRange

```python
from mahavishnu.temporal.graphiti import TimeRange
from datetime import UTC, datetime

# Valid from Jan 1 to Jun 30 (exclusive)
time_range = TimeRange(
    start_time=datetime(2024, 1, 1, tzinfo=UTC),
    end_time=datetime(2024, 6, 30, tzinfo=UTC)
)

# Check validity
is_valid = time_range.is_valid_at(datetime(2024, 3, 1, tzinfo=UTC))  # True
is_valid = time_range.is_valid_at(datetime(2024, 7, 1, tzinfo=UTC))  # False

# Check overlap
other = TimeRange(
    start_time=datetime(2024, 5, 1, tzinfo=UTC),
    end_time=datetime(2024, 7, 1, tzinfo=UTC)
)
overlaps = time_range.overlaps(other)  # True
```

### TemporalNode

```python
from mahavishnu.temporal.graphiti import TemporalNode, TimeRange

node = TemporalNode(
    node_id="user_123",
    labels=["User", "Premium"],
    properties={
        "name": "Alice",
        "plan": "gold",
        "tier": 1
    },
    time_range=TimeRange(start_time=datetime.now(UTC))
)
```

**Key attributes**:
- `node_id`: Unique identifier (all versions share this)
- `labels`: Tags/categories for filtering
- `properties`: Data that can change over time
- `time_range`: When this version is valid
- `created_at`: When first created

### TemporalEdge

```python
from mahavishnu.temporal.graphiti import TemporalEdge, TimeRange

edge = TemporalEdge(
    edge_id="follows_123_456",
    from_node="user_123",
    to_node="user_456",
    relationship_type="FOLLOWS",
    properties={
        "since": "2024-01-01",
        "strength": 0.8
    },
    time_range=TimeRange(start_time=datetime.now(UTC))
)
```

---

## Time-Travel Queries

### Query State at Specific Time

```python
from mahavishnu.temporal.graphiti import TemporalGraph
from datetime import UTC, datetime

graph = TemporalGraph()

# Get node version valid at specific time
node = await graph.get_node_at(
    node_id="user_123",
    timestamp=datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)
)

if node:
    print(f"User plan on June 1: {node.properties['plan']}")
```

### Get Graph Snapshot

```python
# Get complete graph state at time T
snapshot = await graph.get_snapshot_at(
    timestamp=datetime(2024, 1, 1, tzinfo=UTC)
)

print(f"Nodes at time T: {snapshot['node_count']}")
print(f"Edges at time T: {snapshot['edge_count']}")

# Access nodes and edges
for node in snapshot['nodes']:
    print(f"  {node.node_id}: {node.properties}")
```

### Track Changes Over Time

```python
# What changed between two timestamps?
changes = await graph.get_changes_between(
    from_time=datetime(2024, 1, 1, tzinfo=UTC),
    to_time=datetime(2024, 12, 31, tzinfo=UTC)
)

print(f"Nodes added: {len(changes['nodes_added'])}")
print(f"Nodes modified: {len(changes['nodes_modified'])}")
print(f"Edges added: {len(changes['edges_added'])}")
```

### Path Finding with Temporal Validity

```python
# Find path valid at specific time
path = await graph.find_path_at(
    from_node="user_123",
    to_node="user_789",
    timestamp=datetime(2024, 6, 1, tzinfo=UTC),
    max_depth=5,
    relationship_types=["FOLLOWS", "KNOWS"]
)

if path:
    print(f"Path found with {len(path)} hops:")
    for edge in path:
        print(f"  {edge.from_node} -> {edge.to_node} ({edge.relationship_type})")
```

---

## Episodic Memory

### Create Episodes

```python
from mahavishnu.temporal.episodic import EpisodicMemory, Episode, TemporalEvent

memory = EpisodicMemory()

# Create episode for a sequence of related events
episode = Episode(
    title="User Registration Flow",
    description="Complete signup process"
)
episode_id = await memory.create_episode(episode)
```

### Add Events to Episodes

```python
# Add events to episode
events = [
    TemporalEvent(event_type="PageView", data={"page": "/signup"}),
    TemporalEvent(event_type="FormSubmit", data={"form": "registration"}),
    TemporalEvent(event_type="EmailVerify", data={"email": "user@example.com"}),
]

for event in events:
    await memory.add_event(event, episode_id=episode_id)
```

### Query Episodes

```python
# Get all events in an episode (chronological)
events = await memory.get_episode_events(episode_id)

for event in events:
    print(f"{event.timestamp}: {event.event_type}")

# Find episodes in time range
episodes = await memory.get_episodes_in_range(
    from_time=datetime(2024, 1, 1, tzinfo=UTC),
    to_time=datetime(2024, 12, 31, tzinfo=UTC)
)

for episode in episodes:
    print(f"Episode: {episode.title}")
    print(f"  Duration: {episode.duration_seconds()}s")
```

### Merge Episodes

```python
# Merge two related episodes
merged = await memory.merge_episodes(
    target_id=episode_id_1,
    source_id=episode_id_2
)

print(f"Merged episode has {len(merged.event_ids)} events")
```

---

## Advanced Patterns

### Pattern 1: Automatic Versioning

```python
# Updating nodes creates new versions automatically
await graph.update_node(
    node_id="user_123",
    properties={"plan": "platinum"},  # Merge with existing
    timestamp=datetime.now(UTC)
)

# Old version is automatically invalidated
# New version has updated properties
```

### Pattern 2: Temporal Neighbors

```python
# Get neighbors with relationship type filtering
neighbors = await graph.get_neighbors_at(
    node_id="user_123",
    timestamp=datetime(2024, 6, 1, tzinfo=UTC),
    relationship_types=["FOLLOWS", "LIKES"],
    direction="out"  # or "in" or "both"
)

for edge, neighbor in neighbors:
    print(f"{neighbor.node_id}: {neighbor.properties['name']}")
```

### Pattern 3: Filtered Queries

```python
# Get nodes by labels at specific time
users = await graph.get_nodes_at(
    timestamp=datetime(2024, 6, 1, tzinfo=UTC),
    labels=["User", "Active"]
)

# Get edges by relationship type
follows = await graph.get_edges_at(
    timestamp=datetime(2024, 6, 1, tzinfo=UTC),
    relationship_types=["FOLLOWS"],
    from_node="user_123"
)
```

### Pattern 4: Retroactive Episode Creation

```python
# Create episode from existing events
event_ids = [evt1, evt2, evt3]

episode_id = await memory.create_episode_from_events(
    title="Retroactive Episode",
    event_ids=event_ids,
    description="Created after the fact"
)

# Events now reference this episode
```

---

## Performance Optimization

### Efficient Time-Range Queries

```python
# ✅ GOOD: Specific time range
changes = await graph.get_changes_between(
    from_time=datetime(2024, 1, 1, tzinfo=UTC),
    to_time=datetime(2024, 1, 31, tzinfo=UTC)
)

# ❌ BAD: Entire history
changes = await graph.get_changes_between(
    from_time=datetime(2020, 1, 1, tzinfo=UTC),  # Too broad
    to_time=datetime.now(UTC)
)
```

### Leverage Indexes

```python
# Labels are indexed for fast filtering
nodes = await graph.get_nodes_at(
    labels=["User"]  # Uses index
)

# Relationship types are indexed
edges = await graph.get_edges_at(
    relationship_types=["FOLLOWS"]  # Uses index
)
```

### Batch Operations

```python
# ✅ GOOD: Batch node creation
nodes = [TemporalNode(...) for _ in range(100)]
for node in nodes:
    await graph.add_node(node)

# ❌ BAD: Individual updates in loop
for node_id in node_ids:
    await graph.update_node(node_id, props)  # Slow
```

### Statistics Monitoring

```python
# Monitor graph growth
stats = await graph.get_statistics()
print(f"Total nodes: {stats['total_nodes']}")
print(f"Total versions: {stats['total_node_versions']}")
print(f"Versions per node: {stats['total_node_versions'] / stats['total_nodes']:.2f}")
```

---

## Real-World Examples

### Example 1: Knowledge Base Evolution

Track how a knowledge graph evolves over time:

```python
async def track_knowledge_evolution():
    graph = TemporalGraph()

    # Initial state: Article created
    article = TemporalNode(
        node_id="article_abc",
        labels=["Article", "Draft"],
        properties={"title": "ML Basics", "status": "draft"},
        time_range=TimeRange(start_time=datetime(2024, 1, 1, tzinfo=UTC))
    )
    await graph.add_node(article)

    # Update: Article published
    await graph.update_node(
        node_id="article_abc",
        properties={"status": "published", "views": 0},
        timestamp=datetime(2024, 1, 15, tzinfo=UTC)
    )

    # Update: Article went viral
    await graph.update_node(
        node_id="article_abc",
        properties={"views": 10000, "trending": True},
        timestamp=datetime(2024, 2, 1, tzinfo=UTC)
    )

    # Query: What did the article look like on Jan 20?
    article_on_jan_20 = await graph.get_node_at(
        node_id="article_abc",
        timestamp=datetime(2024, 1, 20, tzinfo=UTC)
    )
    print(f"Status on Jan 20: {article_on_jan_20.properties['status']}")
    # Output: Status on Jan 20: published
```

### Example 2: Social Network Analysis

Track relationship evolution:

```python
async def analyze_relationship_evolution():
    graph = TemporalGraph()

    # Initial: Alice follows Bob
    edge = TemporalEdge(
        edge_id="alice_follows_bob",
        from_node="alice",
        to_node="bob",
        relationship_type="FOLLOWS",
        properties={},
        time_range=TimeRange(start_time=datetime(2024, 1, 1, tzinfo=UTC))
    )
    await graph.add_edge(edge)

    # Update: Relationship strengthened
    await graph.update_edge(
        edge_id="alice_follows_bob",
        properties={"strength": 0.9},
        timestamp=datetime(2024, 3, 1, tzinfo=UTC)
    )

    # Query: How strong was the relationship on Feb 1?
    edge_on_feb_1 = await graph.get_edge_at(
        edge_id="alice_follows_bob",
        timestamp=datetime(2024, 2, 1, tzinfo=UTC)
    )
    print(f"Strength on Feb 1: {edge_on_feb_1.properties.get('strength', 'N/A')}")
```

### Example 3: Audit Trail

Create complete audit trail with episodic memory:

```python
async def create_audit_trail():
    memory = EpisodicMemory()

    # Episode: User settings change
    episode = Episode(title="Settings Update Episode")
    episode_id = await memory.create_episode(episode)

    # Track all changes in sequence
    events = [
        TemporalEvent(
            event_type="SettingsView",
            data={"user": "user_123"},
            timestamp=datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)
        ),
        TemporalEvent(
            event_type="SettingsChange",
            data={"field": "theme", "old": "light", "new": "dark"},
            timestamp=datetime(2024, 1, 1, 10, 5, 0, tzinfo=UTC)
        ),
        TemporalEvent(
            event_type="SettingsSave",
            data={"success": True},
            timestamp=datetime(2024, 1, 1, 10, 6, 0, tzinfo=UTC)
        ),
    ]

    for event in events:
        await memory.add_event(event, episode_id)

    # Query: What happened during the update?
    episode_events = await memory.get_episode_events(episode_id)
    for event in episode_events:
        print(f"{event.timestamp}: {event.event_type}")
```

### Example 4: Causal Analysis

Find related events using time windows:

```python
async def analyze_event_causality():
    memory = EpisodicMemory()

    # Critical event
    crash_event = TemporalEvent(
        event_type="SystemCrash",
        timestamp=datetime(2024, 6, 1, 14, 30, 0, tzinfo=UTC)
    )
    await memory.add_event(crash_event)

    # Find events in 5-minute window before crash
    from_time = datetime(2024, 6, 1, 14, 25, 0, tzinfo=UTC)
    to_time = datetime(2024, 6, 1, 14, 30, 0, tzinfo=UTC)

    events_before = await memory.get_events_in_range(from_time, to_time)

    print("Events before crash:")
    for event in events_before:
        print(f"  {event.timestamp}: {event.event_type}")
        if event.event_type in ["HighLoad", "ConfigChange"]:
            print("    → Possible cause!")
```

---

## Best Practices

### 1. Always Use UTC Timezones

```python
# ✅ GOOD
from datetime import UTC, datetime

timestamp = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)

# ❌ BAD
timestamp = datetime(2024, 1, 1, 12, 0, 0)  # Naive datetime
```

### 2. Use Specific Timestamps

```python
# ✅ GOOD
snapshot = await graph.get_snapshot_at(
    timestamp=datetime(2024, 6, 1, tzinfo=UTC)
)

# ❌ BAD
snapshot = await graph.get_snapshot_at()  # Current time only
```

### 3. Handle None Results

```python
# ✅ GOOD: Handle missing data
node = await graph.get_node_at("user_123", timestamp)
if node is None:
    print("Node doesn't exist at this time")
else:
    print(f"Node: {node.properties}")

# ❌ BAD: Assume exists
node = await graph.get_node_at("user_123", timestamp)
print(node.properties["name"])  # AttributeError if None
```

### 4. Check Versions Before Updates

```python
# ✅ GOOD: Verify current state first
current = await graph.get_node_at("user_123")
if current and current.properties["status"] == "active":
    await graph.update_node("user_123", {"status": "verified"})

# ❌ BAD: Update without checking
await graph.update_node("user_123", {"status": "verified"})
```

---

## Testing Temporal Memory

### Unit Tests

```python
import pytest
from datetime import UTC, datetime

@pytest.mark.asyncio
async def test_node_versioning():
    graph = TemporalGraph()

    # Add initial version
    t1 = datetime(2024, 1, 1, tzinfo=UTC)
    node_v1 = TemporalNode(
        node_id="test",
        labels=["Test"],
        properties={"version": 1},
        time_range=TimeRange(start_time=t1)
    )
    await graph.add_node(node_v1)

    # Add second version
    t2 = datetime(2024, 6, 1, tzinfo=UTC)
    node_v2 = await graph.update_node("test", {"version": 2}, t2)

    # Verify versions
    assert (await graph.get_node_at("test", t1)).properties["version"] == 1
    assert (await graph.get_node_at("test", t2)).properties["version"] == 2
```

### Integration Tests

```python
@pytest.mark.asyncio
async def test_episodic_integration():
    memory = EpisodicMemory()
    graph = TemporalGraph()

    # Create episode
    episode = Episode(title="Integration Test")
    episode_id = await memory.create_episode(episode)

    # Add node to graph
    node = TemporalNode(
        node_id="test_node",
        labels=["Test"],
        properties={},
        time_range=TimeRange(start_time=datetime.now(UTC))
    )
    await graph.add_node(node)

    # Record event
    event = TemporalEvent(
        event_type="NodeCreated",
        data={"node_id": "test_node"}
    )
    await memory.add_event(event, episode_id)

    # Verify integration
    events = await memory.get_episode_events(episode_id)
    assert len(events) == 1
    assert events[0].data["node_id"] == "test_node"
```

---

## Troubleshooting

### Issue: Query Returns None

**Symptom**: `get_node_at()` returns None

**Causes**:
1. Node doesn't exist at all
2. Node exists but not valid at queried timestamp
3. Wrong node_id

**Debug**:
```python
# Check node history
history = await graph.get_node_history("user_123")
print(f"Node has {len(history)} versions")

for i, version in enumerate(history):
    print(f"Version {i}: {version.time_range.start_time} - {version.time_range.end_time}")
```

### Issue: Unexpected Changes

**Symptom**: `get_changes_between()` returns wrong count

**Causes**:
1. Time range boundaries (inclusive vs exclusive)
2. Multiple versions in range
3. Concurrent updates

**Debug**:
```python
# Check all versions
for node_id, versions in graph._nodes.items():
    print(f"\n{node_id}:")
    for version in versions:
        print(f"  {version.time_range.start_time} - {version.time_range.end_time}")
```

---

## API Reference

See `mahavishnu/temporal/graphiti.py` and `mahavishnu/temporal/episodic.py` for complete API documentation.

**Key Classes**:
- `TemporalGraph` - Main graph interface
- `TemporalNode` - Entity with time range
- `TemporalEdge` - Relationship with time range
- `TimeRange` - Validity period
- `EpisodicMemory` - Event management
- `Episode` - Event grouping
- `TemporalEvent` - Time-stamped event
