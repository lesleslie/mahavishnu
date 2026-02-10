# Multi-Region Orchestration

Production-ready multi-region deployment system for Mahavishnu with intelligent routing, data locality optimization, and automatic failover.

## Overview

Multi-region orchestration enables deploying Mahavishnu across multiple cloud regions for:

- **Low Latency**: Route users to nearest regions
- **High Availability**: Automatic failover during outages
- **Data Compliance**: GDPR, CCPA, HIPAA enforcement
- **Cost Optimization**: Route to cheapest regions when possible
- **Disaster Recovery**: Multi-region backup and recovery

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    RegionManager                             │
│  - Region registration and discovery                        │
│  - Health monitoring                                        │
│  - Capability tracking                                      │
└─────────────────────────────────────────────────────────────┘
                            │
                            ├──────────────────────────────────┐
                            │                                  │
        ┌───────────────────┴──────────────────┐  ┌───────────┴──────────┐
        │      DeploymentOrchestrator           │  │   RegionAwareRouter  │
        │  - Active-Active deployment           │  │  - Latency routing   │
        │  - Active-Passive deployment          │  │  - Capacity routing  │
        │  - Blue-Green deployments             │  │  - Compliance routing│
        └───────────────────────────────────────┘  └──────────────────────┘
                            │                                  │
                            └──────────────┬───────────────────┘
                                           │
                    ┌──────────────────────┴───────────────────┐
                    │         DataLocalityOptimizer            │
                    │  - Data locality enforcement            │
                    │  - Replication planning                 │
                    │  - Cross-region transfer tracking       │
                    └──────────────────────────────────────────┘
                                           │
                    ┌──────────────────────┴───────────────────┐
                    │           FailureHandler                 │
                    │  - Automatic failover (<1 second)        │
                    │  - Health monitoring                    │
                    │  - Region recovery                      │
                    └──────────────────────────────────────────┘
```

## Features

### 1. Region Management

**RegionManager** manages all cloud regions:

```python
from mahavishnu.integrations.multi_region import RegionManager, Region, CloudProvider

manager = RegionManager()
await manager.initialize()

# Register a region
region = Region(
    region_id="us-east-1",
    name="US East (N. Virginia)",
    provider=CloudProvider.AWS,
    location="Northern Virginia",
    latitude=37.4,
    longitude=-77.5,
    endpoint="https://us-east-1.api.example.com",
    health_score=95.0,
    current_capacity=30,
)
await manager.register_region(region)

# List regions
regions = manager.list_regions(healthy_only=True)

# Get region health
health = await manager.get_region_health("us-east-1")
```

### 2. Deployment Strategies

**DeploymentOrchestrator** supports 4 deployment strategies:

#### Active-Active (Recommended)

All regions serve traffic simultaneously:

```python
from mahavishnu.integrations.multi_region import DeploymentOrchestrator

orchestrator = DeploymentOrchestrator(region_manager=manager)

deployment = await orchestrator.deploy_active_active(
    regions=["us-east-1", "us-west-2", "eu-west-1"],
    replication_strategy="full",  # Full data replication
    failover_strategy="automatic",
)

# All regions are active
assert len(deployment.regions) == 3
```

**Use cases**:
- Global applications
- Read-heavy workloads
- Maximum availability

**Pros**:
- Maximum availability
- Best latency
- Load distribution

**Cons**:
- Higher cost
- Complex consistency

#### Active-Passive

Primary region serves traffic, backups on standby:

```python
deployment = await orchestrator.deploy_active_passive(
    primary="us-east-1",      # Primary serves all traffic
    backups=["us-west-2"],    # Backups on standby
    replication_strategy="partial",
    failover_strategy="graceful",
)
```

**Use cases**:
- Disaster recovery
- Cost optimization
- Simple consistency

**Pros**:
- Lower cost
- Simpler consistency
- Clear failover path

**Cons**:
- Backup regions idle
- Slower failover
- No load distribution

#### Leader Election

Elect one region as leader dynamically:

```python
# Elect leader from candidates
leader = await orchestrator.elect_leader(
    regions=["us-east-1", "us-west-2", "eu-west-1"],
)

# Leader is selected based on:
# 1. Health score (prefer healthier)
# 2. Capacity (prefer less utilized)
# 3. Random tiebreaker
print(f"Leader: {leader}")
```

**Use cases**:
- Coordination services
- Distributed locking
- Master-worker patterns

#### Blue-Green

Zero-downtime deployment with blue/green switch:

```python
deployment = await orchestrator.deploy_blue_green(
    blue_regions=["us-east-1"],      # Current production
    green_regions=["us-west-2"],     # New deployment
    switch_after=60,                 # Seconds before switch
)

# Traffic switches automatically after 60 seconds
```

**Use cases**:
- Production deployments
- A/B testing
- Canary releases

### 3. Data Locality Optimization

**DataLocalityOptimizer** enforces data placement policies:

#### GDPR Compliance

```python
from mahavishnu.integrations.multi_region import (
    DataLocalityOptimizer,
    DataPlacementPolicy,
    ComplianceFramework,
)

optimizer = DataLocalityOptimizer(region_manager=manager)

# Register GDPR policy
policy = DataPlacementPolicy(
    name="EU Data Policy",
    compliance_requirements=[ComplianceFramework.GDPR],
    allowed_regions=["eu-west-1", "eu-central-1"],
    locality_level="strict",
    cross_region_transfer=False,  # No data leaves EU
)
await optimizer.register_policy(policy)

# Find compliant region for EU user
region = await optimizer.find_optimal_region(
    data_type="user_data",
    compliance_requirements=[ComplianceFramework.GDPR],
    user_location={"latitude": 52.5, "longitude": 13.4},  # Berlin
)

print(f"Optimal region: {region}")  # "eu-west-1"
```

#### Data Classification

Classify data as hot or cold:

```python
# Classify based on access frequency
classification = await optimizer.classify_data(
    data_id="user_123_data",
    access_frequency=50.0,  # 50 accesses per day
)

# Hot data (>10 accesses/day) replicated everywhere
# Cold data (<10 accesses/day) stored in primary region only
print(f"Classification: {classification}")  # "hot"
```

#### Replication Planning

Plan data replication across regions:

```python
# Full replication: all data everywhere
targets = await optimizer.plan_replication(
    data_id="user_123_data",
    replication_strategy="full",
)
print(f"Replicate to: {targets}")  # ["us-east-1", "us-west-2", "eu-west-1"]

# Partial replication: hot data everywhere, cold in primary
targets = await optimizer.plan_replication(
    data_id="archive_data",
    replication_strategy="partial",
)
print(f"Replicate to: {targets}")  # ["us-east-1"] (primary only)

# Sharded: partition data across regions
targets = await optimizer.plan_replication(
    data_id="user_456_data",
    replication_strategy="sharded",
)
print(f"Replicate to: {targets}")  # ["us-west-2"] (hash-based)
```

### 4. Intelligent Routing

**RegionAwareRouter** routes requests to optimal regions using 7 strategies:

#### Latency-Based Routing

Route to nearest region:

```python
from mahavishnu.integrations.multi_region import RegionAwareRouter, RoutingStrategy

router = RegionAwareRouter(region_manager=manager)

decision = await router.route_request(
    request_context={
        "user_location": {
            "latitude": 52.5,   # Berlin
            "longitude": 13.4,
        },
    },
    strategy=RoutingStrategy.LATENCY_BASED,
)

print(f"Routed to: {decision.selected_region}")  # "eu-west-1"
print(f"Reasoning: {decision.reasoning}")
# "Selected eu-west-1 for lowest latency"
```

#### Capacity-Based Routing

Route to region with most capacity:

```python
decision = await router.route_request(
    request_context={},
    strategy=RoutingStrategy.CAPACITY_BASED,
)

# Selects region with lowest utilization
print(f"Routed to: {decision.selected_region}")
print(f"Utilization: {decision.reasoning}")
# "Selected us-west-2 with 20.0% utilization"
```

#### Compliance-Based Routing

Route based on data compliance:

```python
decision = await router.route_request(
    request_context={
        "compliance_requirements": [ComplianceFramework.GDPR],
    },
    strategy=RoutingStrategy.COMPLIANCE_BASED,
)

# Only routes to compliant regions
print(f"Routed to: {decision.selected_region}")  # "eu-west-1"
```

#### Cost-Based Routing

Route to cheapest region:

```python
decision = await router.route_request(
    request_context={},
    strategy=RoutingStrategy.COST_BASED,
)

# Selects region with lowest cost multiplier
print(f"Routed to: {decision.selected_region}")
print(f"Cost: {decision.reasoning}")
# "Selected us-west-2 with 0.9x cost multiplier"
```

#### Health-Based Routing

Route to healthiest region:

```python
decision = await router.route_request(
    request_context={},
    strategy=RoutingStrategy.HEALTH_BASED,
)

# Selects region with highest health score
print(f"Routed to: {decision.selected_region}")
print(f"Health: {decision.reasoning}")
# "Selected us-east-1 with 95.0 health score"
```

#### Round-Robin Routing

Distribute requests evenly:

```python
# First request
decision1 = await router.route_request(
    request_context={},
    strategy=RoutingStrategy.ROUND_ROBIN,
)

# Second request
decision2 = await router.route_request(
    request_context={},
    strategy=RoutingStrategy.ROUND_ROBIN,
)

# Distributes across regions
assert decision1.selected_region != decision2.selected_region
```

### 5. Automatic Failover

**FailureHandler** provides sub-second failover:

```python
from mahavishnu.integrations.multi_region import FailureHandler

handler = FailureHandler(
    region_manager=manager,
    router=router,
    data_optimizer=optimizer,
    failover_timeout=1.0,  # 1 second timeout
)
await handler.initialize()

# Automatic failover on region failure
event = await handler.handle_region_failure(
    failed_region="us-east-1",
    reason="Health check failed",
)

print(f"Failover: {event.from_region} -> {event.to_region}")
print(f"Duration: {event.duration_ms}ms")
# "Failover: us-east-1 -> us-west-2"
# "Duration: 150ms"

# Manual failover
event = await handler.failover_to(
    from_region="us-east-1",
    to_region="eu-west-1",
    strategy="immediate",  # or "graceful"
    reason="Planned maintenance",
)

# Recover failed region
manager.regions["us-east-1"].health_score = 95.0
await handler.recover_region("us-east-1")
```

## FastAPI Integration

Create HTTP endpoints for multi-region management:

```python
from fastapi import FastAPI
from mahavishnu.integrations.multi_region import MultiRegionAPI, create_multi_region_system

app = FastAPI()

# Initialize multi-region system
region_mgr, router, failure_handler = await create_multi_region_system()

# Register API routes
api = MultiRegionAPI(region_mgr, router, failure_handler)
api.register_routes(app)

# Available endpoints:
# GET    /regions                    - List all regions
# GET    /regions/{region_id}        - Get region details
# POST   /regions                    - Register new region
# GET    /regions/{region_id}/health - Get region health
# POST   /route                      - Route request to optimal region
# GET    /stats                      - Get multi-region statistics
```

### Example API Usage

```bash
# List regions
curl http://localhost:8000/regions?healthy_only=true

# Get region details
curl http://localhost:8000/regions/us-east-1

# Get region health
curl http://localhost:8000/regions/us-east-1/health

# Route request
curl -X POST http://localhost:8000/route \
  -H "Content-Type: application/json" \
  -d '{
    "request_context": {
      "user_location": {"latitude": 52.5, "longitude": 13.4}
    },
    "strategy": "latency_based"
  }'

# Get statistics
curl http://localhost:8000/stats
```

## Configuration

### Environment Variables

```bash
# Region monitoring
MAHAVISHNU_MULTI_REGION__HEALTH_CHECK_INTERVAL=30
MAHAVISHNU_MULTI_REGION__CIRCUIT_BREAKER_THRESHOLD=5

# Failover
MAHAVISHNU_MULTI_REGION__FAILOVER_TIMEOUT=1.0

# Data locality
MAHAVISHNU_MULTI_REGION__HOT_DATA_THRESHOLD=10.0
```

### Region Configuration

Define regions in code or configuration:

```python
regions = [
    Region(
        region_id="us-east-1",
        name="US East (N. Virginia)",
        provider=CloudProvider.AWS,
        location="Northern Virginia",
        latitude=37.4,
        longitude=-77.5,
        endpoint="https://us-east-1.api.example.com",
        capabilities=RegionCapabilities(
            compliance=[ComplianceFramework.SOC2],
            max_capacity=100,
        ),
        cost_multiplier=1.0,
    ),
    Region(
        region_id="eu-west-1",
        name="Europe (Ireland)",
        provider=CloudProvider.AWS,
        location="Ireland",
        latitude=53.3,
        longitude=-6.2,
        endpoint="https://eu-west-1.api.example.com",
        capabilities=RegionCapabilities(
            compliance=[ComplianceFramework.GDPR],
            max_capacity=100,
        ),
        cost_multiplier=1.1,
    ),
]
```

## Best Practices

### 1. Deployment Strategy Selection

| Use Case | Strategy | Reason |
|----------|----------|--------|
| Global web app | Active-Active | Low latency everywhere |
| Internal tool | Active-Passive | Cost savings |
| Coordination service | Leader Election | Single point of coordination |
| Production deployment | Blue-Green | Zero downtime |

### 2. Data Replication Selection

| Data Type | Replication | Reason |
|-----------|-------------|--------|
| User profiles | Full | Fast access everywhere |
| Session data | Partial | Hot data replicated |
| Analytics | Sharded | Distribute load |
| Archive | Local | Cost savings |

### 3. Routing Strategy Selection

| Requirement | Strategy | Reason |
|-------------|----------|--------|
| Global users | Latency-based | Best user experience |
| High load | Capacity-based | Avoid overload |
| Compliance | Compliance-based | Meet regulations |
| Cost-sensitive | Cost-based | Minimize costs |

### 4. Compliance Enforcement

Always define compliance policies:

```python
# GDPR: Keep EU data in EU
policy = DataPlacementPolicy(
    name="GDPR Policy",
    compliance_requirements=[ComplianceFramework.GDPR],
    allowed_regions=["eu-west-1", "eu-central-1"],
    locality_level="strict",
    cross_region_transfer=False,
)

# HIPAA: Keep health data in compliant regions
policy = DataPlacementPolicy(
    name="HIPAA Policy",
    compliance_requirements=[ComplianceFramework.HIPAA],
    allowed_regions=["us-east-1", "us-west-2"],
    locality_level="region",
    cross_region_transfer=True,
)
```

### 5. Monitoring

Monitor key metrics:

```python
# Region health
stats = region_manager.get_stats()
print(f"Healthy: {stats['healthy_regions']}/{stats['total_regions']}")

# Routing distribution
stats = router.get_routing_stats()
print(f"Decisions: {stats['decisions_by_region']}")

# Failover events
stats = failure_handler.get_failover_stats()
print(f"Failovers: {stats['total_failovers']}")
print(f"Avg duration: {stats['average_duration_ms']:.1f}ms")
```

## Performance

### Failover Performance

- **Automatic failover**: <1 second
- **Graceful failover**: ~2-3 seconds
- **Manual failover**: Instant

### Routing Performance

- **Latency calculation**: <1ms
- **Routing decision**: <5ms
- **Compliance check**: <1ms

### Scalability

- **Supported regions**: 10+
- **Requests per second**: 10,000+
- **Concurrent deployments**: 100+

## Troubleshooting

### Region Not Available

```python
# Check region health
health = await manager.get_region_health("us-east-1")
print(f"Status: {health.status}")
print(f"Error rate: {health.error_rate}")
print(f"Capacity: {health.capacity_utilization}%")
```

### Routing Fails

```python
# Check if any healthy regions exist
regions = manager.list_regions(healthy_only=True)
if not regions:
    print("No healthy regions available!")
```

### Compliance Violations

```python
# Check region compliance
region = manager.get_region("us-east-1")
print(f"Compliance: {[c.value for c in region.compliance_frameworks]}")

# Verify policy requirements
policy = optimizer.policies["policy_id"]
print(f"Required: {[c.value for c in policy.compliance_requirements]}")
print(f"Allowed: {policy.allowed_regions}")
```

## Testing

Run integration tests:

```bash
# Test multi-region orchestration
pytest tests/integration/test_multi_region.py -v

# Test specific component
pytest tests/integration/test_multi_region.py::TestRegionManager -v

# Test with coverage
pytest tests/integration/test_multi_region.py --cov=mahavishnu/integrations/multi_region
```

## API Reference

See [API Documentation](MULTI_REGION_API.md) for complete API reference.

## See Also

- [Pool Architecture](../POOL_ARCHITECTURE.md)
- [Distributed Task Execution](../DISTRIBUTED_POOL.md)
- [Health Checks](../PHASE4_HEALTH_CHECKS.md)
