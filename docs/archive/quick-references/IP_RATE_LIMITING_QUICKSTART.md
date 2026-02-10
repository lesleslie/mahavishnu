# IP-Based Rate Limiting - Quick Start Guide

**5-minute setup guide for IP-based rate limiting**

---

## Step 1: Configure (2 minutes)

Edit `settings/mahavishnu.yaml`:

```yaml
rate_limit:
  enabled: true

  # User-level limits
  user_requests_per_minute: 60
  user_requests_per_hour: 1000

  # IP-level limits (stricter)
  ip_requests_per_minute: 30
  ip_requests_per_hour: 500

  # IP ban settings
  ip_ban_enabled: true
  ip_ban_threshold: 5  # Auto-ban after 5 violations
  ip_ban_duration: 300  # 5 minutes

  # Exemptions (recommended)
  exempt_ips:
    - "127.0.0.1"
    - "::1"
  exempt_networks:
    - "10.0.0.0/8"
    - "172.16.0.0/12"
    - "192.168.0.0/16"
```

## Step 2: Restart MCP Server (1 minute)

```bash
# Stop existing server
mahavishnu mcp stop

# Start with new config
mahavishnu mcp start

# Verify it's running
mahavishnu mcp status
```

## Step 3: Test (2 minutes)

Use MCP tools to test:

```python
# Check configuration
config = await rate_limit_get_config()
print(f"Rate limiting: {'enabled' if config['enabled'] else 'disabled'}")
print(f"IP ban: {'enabled' if config['ip_ban_enabled'] else 'disabled'}")

# Make a test request (will use your IP)
stats = await rate_limit_get_stats()
print(f"Active IPs: {stats['total_ips']}")

# Test IP ban (optional)
await ip_ban_add(
    ip_address="203.0.113.50",  # Test IP
    duration=60,
    reason="Test ban"
)

# Check it worked
check = await ip_ban_check(ip_address="203.0.113.50")
print(f"Banned: {check['banned']}")

# Clean up
await ip_ban_remove(ip_address="203.0.113.50")
```

---

## Common Configurations

### Development (Permissive)

```yaml
rate_limit:
  enabled: true
  user_requests_per_minute: 1000  # Very high
  ip_requests_per_minute: 500
  ip_ban_enabled: false  # Disable bans
```

### Production (Balanced)

```yaml
rate_limit:
  enabled: true
  user_requests_per_minute: 60
  ip_requests_per_minute: 30
  ip_ban_enabled: true
  ip_ban_threshold: 5
  ip_ban_duration: 300
```

### High Security (Strict)

```yaml
rate_limit:
  enabled: true
  user_requests_per_minute: 30  # Low
  ip_requests_per_minute: 10    # Very low
  ip_ban_enabled: true
  ip_ban_threshold: 3           # Quick ban
  ip_ban_duration: 3600         # 1 hour
```

### Corporate Network (Whitelist Office)

```yaml
rate_limit:
  enabled: true
  user_requests_per_minute: 60
  ip_requests_per_minute: 30

  # Whitelist office network
  exempt_networks:
    - "203.0.113.0/24"  # Office CIDR
```

---

## Environment Variables (Quick Override)

```bash
# Disable rate limiting temporarily
export MAHAVISHNU_RATE_LIMIT__ENABLED=false

# Increase limits for testing
export MAHAVISHNU_RATE_LIMIT__USER_REQUESTS_PER_MINUTE=1000

# Disable IP bans
export MAHAVISHNU_RATE_LIMIT__IP_BAN_ENABLED=false

# Change ban threshold
export MAHAVISHNU_RATE_LIMIT__IP_BAN_THRESHOLD=10
```

---

## MCP Tools Cheat Sheet

```python
# View config
await rate_limit_get_config()

# View stats
await rate_limit_get_stats()  # Global
await rate_limit_get_stats(key="user_123")  # Specific

# IP ban management
await ip_ban_check(ip_address="192.168.1.1")
await ip_ban_list()  # All bans
await ip_ban_add(ip_address="1.2.3.4", duration=3600, reason="Abuse")
await ip_ban_remove(ip_address="1.2.3.4")
await ip_ban_get_stats()

# Maintenance
await rate_limit_cleanup()
```

---

## Troubleshooting

**Legitimate users blocked?**
```yaml
# Whitelist the IP/network
exempt_networks:
  - "203.0.113.0/24"
```

**Too many bans?**
```yaml
# Increase threshold
ip_ban_threshold: 10  # From 5

# Or disable bans
ip_ban_enabled: false
```

**Need to bypass for testing?**
```bash
export MAHAVISHNU_RATE_LIMIT__ENABLED=false
mahavishnu mcp restart
```

---

## Next Steps

1. **Full Documentation**: `/docs/IP_RATE_LIMITING.md`
2. **Analysis**: `/ACT-014_RATE_LIMITING_ANALYSIS.md`
3. **Tests**: `/tests/unit/test_rate_limit_extended.py`
4. **Configuration**: `/settings/mahavishnu.yaml`
