# Rate Limiting Integration (Integration #23)

## Overview

The Rate Limiting integration provides comprehensive, distributed rate limiting for the Mahavishnu ecosystem with multiple algorithms, strategies, admin override capabilities, and real-time monitoring.

## Features

### 4 Rate Limiting Algorithms

1. **Token Bucket** - Allows bursts up to burst size, then refills at steady rate
   - Best for: APIs with bursty traffic patterns
   - Allows short bursts while maintaining overall rate limit

2. **Leaky Bucket** - Processes requests at steady rate with no bursts
   - Best for: Consistent traffic shaping
   - Smooths out traffic spikes

3. **Fixed Window** - Simple reset-based limiting
   - Best for: Simple rate limiting requirements
   - Easy to understand and implement

4. **Sliding Window** - Accurate limiting with memory efficiency
   - Best for: High-accuracy requirements
   - More accurate than fixed window

### 5 Limiting Strategies

1. **Hard Limit** - Reject immediately when limit exceeded
2. **Queue Strategy** - Queue requests for later processing
3. **Retry-After** - Return 429 with retry-after header (recommended)
4. **Graceful Degradation** - Degrade service quality instead of hard rejection
5. **Throttling** - Slow down requests instead of rejecting

### Admin Override System

- **Admin Whitelist** - Bypass rate limiting for admins
- **Emergency Access** - Unlimited access during incidents
- **Temporary Override Grants** - Time-limited access grants
- **Override Audit Logging** - Track all override actions

### Real-time Monitoring

- **Hit Rate Tracking** - What % of requests are limited
- **Violation Tracking** - By user, IP, and endpoint
- **Rejection Rate** - Track overall rejection patterns
- **Alert Integration** - Alert on unusual patterns
- **Grafana Dashboards** - Export metrics for visualization

## Installation

```bash
# Rate limiting is included with mahavishnu
pip install mahavishnu
```

## Quick Start

### Basic Usage

```python
from mahavishnu.integrations.rate_limiting import (
    create_rate_limiter,
    RateLimitRule,
    LimitScope,
    LimitStrategy,
    RateLimitAlgorithm,
)

# Create rate limiter
limiter = create_rate_limiter(
    redis_url="redis://localhost:6379",  # Optional, uses in-memory if not provided
    default_algorithm=RateLimitAlgorithm.TOKEN_BUCKET,
    default_strategy=LimitStrategy.RETRY_AFTER,
)

# Add a rule
await limiter.add_rule(
    RateLimitRule(
        name="api_default",
        scope=LimitScope.PER_USER,
        rate=100,  # 100 requests per window
        burst=10,  # Allow burst of 10
        window_seconds=60,  # 60 second window
    )
)

# Check rate limit
decision = await limiter.check_limit(
    identifier="user_123",
    rule_name="api_default",
)

if decision.allowed:
    # Process request
    pass
else:
    # Handle rate limit
    return Response(
        status_code=429,
        headers={"Retry-After": str(decision.retry_after)},
    )
```

### Using Default Rules

```python
from mahavishnu.integrations.rate_limiting import (
    create_rate_limiter,
    create_default_rules,
)

# Create limiter with default rules
limiter = create_rate_limiter()

# Add default rules
rules = create_default_rules()
for rule in rules:
    await limiter.add_rule(rule)

# Default rules include:
# - api_global: 1000 req/min (global)
# - api_per_user: 100 req/min (per user)
# - api_per_ip: 50 req/min (per IP)
# - expensive_operations: 10 req/min (specific endpoints)
```

## Configuration

### Rule Configuration

```python
from mahavishnu.integrations.rate_limiting import RateLimitRule

rule = RateLimitRule(
    name="api_limit",
    scope=LimitScope.PER_USER,  # GLOBAL, PER_USER, PER_IP, PER_ENDPOINT
    rate=100,  # Sustained rate (requests per window)
    burst=10,  # Burst size (max 2x rate)
    window_seconds=60,  # Time window in seconds
    algorithm=RateLimitAlgorithm.TOKEN_BUCKET,  # Algorithm
    strategy=LimitStrategy.RETRY_AFTER,  # Strategy
    endpoints=["/api/search", "/api/export"],  # Specific endpoints
    user_ids=["premium_user"],  # Specific users
    ip_addresses=["192.168.1.0/24"],  # Specific IPs
    priority=100,  # Rule priority (higher = more important)
    enabled=True,  # Enable/disable rule
)
```

### Scope Types

- **GLOBAL** - System-wide limits
- **PER_USER** - Per-user limits
- **PER_IP** - Per-IP limits
- **PER_ENDPOINT** - Per-endpoint limits

### Algorithm Selection

| Algorithm | Use Case | Burst Support | Accuracy |
|-----------|----------|---------------|----------|
| Token Bucket | APIs with bursty traffic | Yes | High |
| Leaky Bucket | Consistent traffic shaping | No | High |
| Fixed Window | Simple requirements | No | Medium |
| Sliding Window | High accuracy needed | Limited | Very High |

### Strategy Selection

| Strategy | Use Case | Response |
|----------|----------|----------|
| HARD | Immediate rejection needed | 429 |
| QUEUE | Process requests later | 202 Accepted |
| RETRY_AFTER | Standard API behavior | 429 + Retry-After |
| GRACEFUL | Degrade instead of reject | 200 + degraded content |
| THROTTLE | Slow down requests | 200 + delayed |

## FastAPI Integration

### Middleware Setup

```python
from fastapi import FastAPI, Request
from mahavishnu.integrations.rate_limiting import (
    RateLimitMiddleware,
    create_rate_limiter,
    create_default_rules,
)

app = FastAPI()

# Create limiter
limiter = create_rate_limiter()

# Add default rules
rules = create_default_rules()
for rule in rules:
    await limiter.add_rule(rule)

# Add middleware
app.add_middleware(
    RateLimitMiddleware,
    engine=limiter,
    default_rule="api_per_user",
)
```

### Custom Identifier Extraction

```python
def extract_user_id(request: Request) -> str:
    """Extract user ID from JWT token."""
    token = request.headers.get("Authorization")
    if token:
        payload = decode_jwt(token)
        return f"user:{payload['user_id']}"
    return f"ip:{request.client.host}"

app.add_middleware(
    RateLimitMiddleware,
    engine=limiter,
    default_rule="api_per_user",
    extract_identifier=extract_user_id,
)
```

## Admin Override

### Create Override

```python
from mahavishnu.integrations.rate_limiting import OverrideRequest, OverrideReason

# Create override for emergency access
override_req = OverrideRequest(
    admin_id="admin_123",
    target_user_id="user_456",
    reason=OverrideReason.EMERGENCY_ACCESS,
    duration_minutes=60,
    unlimited=True,  # Unlimited access
)

record = await limiter.add_override(override_req)
print(f"Override ID: {record.override_id}")
print(f"Expires: {record.expires_at}")
```

### Remove Override

```python
await limiter.remove_override(override_id)
```

### Check Override

```python
override = await limiter.check_override(
    user_id="user_456",
    ip_address="192.168.1.1",
)

if override:
    print(f"Override active: {override.override_id}")
    print(f"Reason: {override.request.reason}")
```

## Monitoring

### Get Metrics

```python
# Get metrics for a specific rule
metrics = await limiter.get_metrics("api_per_user")

print(f"Total requests: {metrics.total_requests}")
print(f"Allowed: {metrics.allowed_requests}")
print(f"Denied: {metrics.denied_requests}")
print(f"Hit rate: {metrics.calculate_hit_rate():.1%}")
print(f"Avg tokens remaining: {metrics.avg_tokens_remaining:.1f}")

# Violations by user
for user, count in metrics.violations_by_user.items():
    print(f"  {user}: {count} violations")

# Violations by endpoint
for endpoint, count in metrics.violations_by_endpoint.items():
    print(f"  {endpoint}: {count} violations")
```

### Get All Metrics

```python
all_metrics = await limiter.get_all_metrics()

for rule_name, metrics in all_metrics.items():
    print(f"{rule_name}:")
    print(f"  Total: {metrics.total_requests}")
    print(f"  Hit rate: {metrics.calculate_hit_rate():.1%}")
```

### Reset Metrics

```python
await limiter.reset_metrics("api_per_user")
```

## CLI Commands

### List Rules

```bash
mahavishnu rate-limit-list
```

### Add Rule

```bash
mahavishnu rate-limit-add \
    --name api_limit \
    --scope per_user \
    --rate 100 \
    --burst 10 \
    --window 60 \
    --algorithm token_bucket \
    --strategy retry_after
```

### Remove Rule

```bash
mahavishnu rate-limit-remove --name api_limit
```

### Admin Override

```bash
mahavishnu rate-limit-override \
    --admin admin_123 \
    --user user_456 \
    --reason emergency_access \
    --duration 60 \
    --unlimited
```

### Show Metrics

```bash
# All metrics
mahavishnu rate-limit-metrics

# Specific rule
mahavishnu rate-limit-metrics --rule api_per_user
```

### Reset Metrics

```bash
mahavishnu rate-limit-reset --rule api_per_user
```

## Redis Configuration

### Standalone Redis

```python
limiter = create_rate_limiter(
    redis_url="redis://localhost:6379/0",
)
```

### Redis Sentinel

```python
limiter = create_rate_limiter(
    redis_url="sentinel://localhost:26379/0",
)
```

### Redis Cluster

```python
limiter = create_rate_limiter(
    redis_url="redis-cluster://localhost:7000/0",
)
```

### Redis with Authentication

```python
limiter = create_rate_limiter(
    redis_url="redis://:password@localhost:6379/0",
)
```

## Advanced Usage

### Multiple Rules Per Endpoint

```python
# Global limit
await limiter.add_rule(
    RateLimitRule(
        name="global_limit",
        scope=LimitScope.GLOBAL,
        rate=1000,
        burst=100,
        window_seconds=60,
    )
)

# Per-user limit (more restrictive)
await limiter.add_rule(
    RateLimitRule(
        name="user_limit",
        scope=LimitScope.PER_USER,
        rate=100,
        burst=10,
        window_seconds=60,
        priority=200,  # Higher priority
    )
)

# Check both limits
global_decision = await limiter.check_limit("user_123", "global_limit")
user_decision = await limiter.check_limit("user_123", "user_limit")

if global_decision.allowed and user_decision.allowed:
    # Process request
    pass
```

### Custom Algorithm

```python
from mahavishnu.integrations.rate_limiting import RateLimitAlgorithm

class CustomAlgorithm:
    def __init__(self, rate, burst, window_seconds):
        self.rate = rate
        self.burst = burst
        self.window_seconds = window_seconds

    async def check(self, state, current_time):
        # Your custom logic here
        allowed = True  # Your logic
        updated_state = state  # Your logic
        return allowed, updated_state

    def get_retry_after(self, state):
        # Calculate retry time
        return 60.0
```

### Custom Strategy

```python
from mahavishnu.integrations.rate_limiting import RateLimitStrategyHandler

class CustomStrategyHandler(RateLimitStrategyHandler):
    async def apply_strategy(self, decision, identifier):
        if not decision.allowed:
            # Custom strategy logic
            decision.allowed = True
            decision.tokens_remaining = 0.1
        return decision

# Use custom handler
handler = CustomStrategyHandler(engine)
```

## Best Practices

### 1. Rule Design

- Start with per-user limits for most APIs
- Use global limits to protect overall system
- Add per-IP limits to prevent abuse
- Use more restrictive limits for expensive operations

### 2. Algorithm Selection

- **Token Bucket** - Default choice for most APIs
- **Leaky Bucket** - Use for consistent traffic shaping
- **Fixed Window** - Use for simple, predictable limits
- **Sliding Window** - Use when accuracy is critical

### 3. Strategy Selection

- **RETRY_AFTER** - Recommended for most APIs
- **GRACEFUL** - Use for non-critical features
- **QUEUE** - Use for async processing
- **HARD** - Use for critical resources
- **THROTTLE** - Use for degradation scenarios

### 4. Monitoring

- Monitor hit rates regularly
- Alert on unusual patterns
- Track violations by user/IP
- Adjust limits based on metrics

### 5. Admin Override

- Document all override actions
- Set reasonable expiration times
- Review overrides periodically
- Use only for legitimate reasons

## Performance Considerations

### In-Memory vs Redis

| Aspect | In-Memory | Redis |
|--------|-----------|-------|
| Performance | Very Fast | Fast |
| Scalability | Single instance | Distributed |
| Persistence | No | Yes |
| Use Case | Development, single-instance | Production, distributed |

### Optimization Tips

1. **Use Redis for distributed systems** - Ensures consistency across instances
2. **Tune Redis connection pool** - Adjust based on load
3. **Use appropriate algorithms** - Simpler algorithms are faster
4. **Monitor metrics** - Identify performance bottlenecks
5. **Cache rule lookups** - Rules change infrequently

## Troubleshooting

### High Hit Rate

**Problem**: Many requests are being rate limited

**Solutions**:
- Increase rate limits
- Check for legitimate traffic spikes
- Identify abusive users/IPs
- Consider graceful degradation

### Redis Connection Issues

**Problem**: Redis connection failures

**Solutions**:
- Check Redis is running
- Verify connection string
- Check network connectivity
- Review Redis logs

### Uneven Distribution

**Problem**: Some users hit limits more than others

**Solutions**:
- Review rate limit configuration
- Check for power user patterns
- Consider tiered limits
- Add per-endpoint limits

## Testing

### Unit Tests

```python
import pytest
from mahavishnu.integrations.rate_limiting import (
    create_rate_limiter,
    RateLimitRule,
    LimitScope,
)

@pytest.mark.asyncio
async def test_rate_limit():
    limiter = create_rate_limiter()

    await limiter.add_rule(
        RateLimitRule(
            name="test",
            scope=LimitScope.PER_USER,
            rate=10,
            burst=10,
            window_seconds=60,
        )
    )

    # Make requests up to limit
    for i in range(10):
        decision = await limiter.check_limit("user_1", "test")
        assert decision.allowed is True

    # Next request should be denied
    decision = await limiter.check_limit("user_1", "test")
    assert decision.allowed is False
```

### Integration Tests

```python
from fastapi.testclient import TestClient
from mahavishnu.integrations.rate_limiting import RateLimitMiddleware

def test_rate_limit_middleware():
    client = TestClient(app)

    # Make requests up to limit
    for i in range(10):
        response = client.get("/api/test")
        assert response.status_code == 200

    # Next request should be rate limited
    response = client.get("/api/test")
    assert response.status_code == 429
    assert "Retry-After" in response.headers
```

## References

### File Locations

- **Main module**: `/Users/les/Projects/mahavishnu/mahavishnu/integrations/rate_limiting.py`
- **Tests**: `/Users/les/Projects/mahavishnu/tests/unit/test_integrations/test_rate_limiting.py`
- **Documentation**: `/Users/les/Projects/mahavishnu/docs/RATE_LIMITING_INTEGRATION.md`

### API Reference

See the module docstring in `rate_limiting.py` for complete API documentation.

### Related Integrations

- **FastAPI** - Web framework integration
- **Redis** - Distributed state storage
- **Prometheus** - Metrics export
- **Grafana** - Dashboard visualization

## Support

For issues, questions, or contributions, please refer to the main Mahavishnu documentation.
