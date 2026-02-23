# ADR 010: Adapter Security Specification

## Status

**Accepted**

## Context

The Hybrid Adapter Registry (ADR 009) introduces dynamic adapter discovery via Python entry points. This creates security risks that must be addressed:

1. **Malicious Package Injection** - Third-party packages could register malicious adapters
2. **Code Execution** - Adapters execute with full application privileges
3. **Supply Chain Attacks** - Compromised dependencies could inject adapters
4. **Unauthorized Registration** - Unauthenticated adapter registration
5. **Data Exfiltration** - Malicious adapters could access sensitive data

## Decision

Implement a multi-layered security model with allowlists, optional signing, and sandboxed execution.

### Layer 1: Entry Point Allowlist

All adapter entry points must match allowlist patterns:

```python
class AdapterDiscoveryEngine:
    """Discover adapters with allowlist validation."""

    def __init__(self, config: AdapterRegistryConfig):
        self.allowlist_patterns = config.allowlist_patterns
        self.verify_signatures = config.verify_signatures
        self.reject_unsigned = config.reject_unsigned

    def _is_allowed(self, module_path: str) -> bool:
        """Check if module matches allowlist patterns."""
        import fnmatch
        for pattern in self.allowlist_patterns:
            if fnmatch.fnmatch(module_path, pattern):
                return True
        logger.warning(f"Adapter rejected (not in allowlist): {module_path}")
        return False

    async def discover_from_entry_points(self) -> list[AdapterMetadata]:
        """Load adapters from Python entry points with validation."""
        import importlib.metadata as metadata
        eps = metadata.entry_points(group="mahavishnu.adapters")

        for ep in eps:
            if not self._is_allowed(ep.value):
                continue
            if self.verify_signatures and not self._verify_signature(ep):
                if self.reject_unsigned:
                    continue
            yield AdapterMetadata.from_entry_point(ep)
```

Configuration in `settings/mahavishnu.yaml`:

```yaml
adapter_registry:
  enabled: true
  allowlist_patterns:
    - "mahavishnu.adapters.*"      # Core adapters
    - "mahavishnu.engines.*"       # Engine adapters
    - "trusted_org.third_party.*"  # Trusted third-party
  verify_signatures: false         # Enable in production
  reject_unsigned: false           # Dev mode flexibility
```

### Layer 2: Authorization Levels

Adapters operate under authorization levels:

| Level | Permissions | Use Case |
|-------|-------------|----------|
| **full** | All operations, file system, network | Core adapters (prefect, agno) |
| **read_only** | Read-only data access | Monitoring adapters |
| **sandboxed** | Isolated execution, no file/network | Untrusted third-party |

```python
class AuthorizationLevel(str, Enum):
    FULL = "full"
    READ_ONLY = "read_only"
    SANDBOXED = "sandboxed"

@dataclass
class AdapterMetadata:
    adapter_id: str
    authorization_level: AuthorizationLevel = AuthorizationLevel.FULL
    allowed_paths: list[str] = field(default_factory=list)
    allowed_networks: list[str] = field(default_factory=list)
```

### Layer 3: Secure gRPC Configuration

Oneiric MCP discovery requires TLS in production:

```yaml
oneiric_mcp:
  enabled: true
  grpc_host: "localhost"
  grpc_port: 8681
  use_tls: true                    # REQUIRED in production
  tls_cert_path: "/path/to/cert"   # TLS certificate
  tls_key_path: "/path/to/key"     # TLS private key
  ca_cert_path: "/path/to/ca"      # CA certificate for verification
```

```python
class OneiricMCPClient:
    """Secure gRPC client for Oneiric MCP."""

    def __init__(self, config: OneiricMCPConfig):
        self.channel = self._create_secure_channel(config)

    def _create_secure_channel(self, config: OneiricMCPConfig) -> grpc.Channel:
        if config.use_tls:
            credentials = grpc.ssl_channel_credentials(
                root_certificates=self._load_cert(config.ca_cert_path),
                private_key=self._load_cert(config.tls_key_path),
                certificate_chain=self._load_cert(config.tls_cert_path),
            )
            return grpc.secure_channel(
                f"{config.grpc_host}:{config.grpc_port}",
                credentials,
            )
        else:
            # Development only - warn in logs
            logger.warning("Using insecure gRPC channel - not recommended for production")
            return grpc.insecure_channel(
                f"{config.grpc_host}:{config.grpc_port}"
            )
```

### Layer 4: Audit Logging

All adapter operations are logged:

```python
class AdapterAuditLogger:
    """Audit logging for adapter operations."""

    def log_registration(self, metadata: AdapterMetadata, source: str):
        logger.info(
            "adapter_registered",
            extra={
                "adapter_id": metadata.adapter_id,
                "source": source,  # "entry_point", "oneiric_mcp", "dhruva"
                "capabilities": metadata.capabilities,
                "authorization_level": metadata.authorization_level.value,
            }
        )

    def log_resolution(self, task_type: str, adapter_id: str, capabilities: list[str]):
        logger.info(
            "adapter_resolved",
            extra={
                "task_type": task_type,
                "adapter_id": adapter_id,
                "matched_capabilities": capabilities,
            }
        )

    def log_rejection(self, module_path: str, reason: str):
        logger.warning(
            "adapter_rejected",
            extra={
                "module_path": module_path,
                "reason": reason,  # "not_in_allowlist", "invalid_signature"
            }
        )
```

### Layer 5: Prometheus Metrics

Security metrics exposed for monitoring:

```python
from prometheus_client import Counter, Gauge, Histogram

# Security metrics
adapter_rejections_total = Counter(
    "mahavishnu_adapter_rejections_total",
    "Adapter rejections by reason",
    ["reason", "module_path"]
)

adapter_registrations_total = Counter(
    "mahavishnu_adapter_registrations_total",
    "Adapter registrations by source",
    ["source", "authorization_level"]
)

unverified_adapters_gauge = Gauge(
    "mahavishnu_unverified_adapters",
    "Number of adapters loaded without signature verification"
)
```

### Layer 6: Grafana Alerts

Security alerts in Grafana dashboard:

| Alert | Condition | Severity |
|-------|-----------|----------|
| **Unsigned Adapter Loaded** | `unverified_adapters > 0` in production | Warning |
| **High Rejection Rate** | `rate(rejections[5m]) > 1` | Warning |
| **Unauthorized Registration Attempt** | Any rejection with reason="not_in_allowlist" | Critical |

## Threat Model

| Threat | Likelihood | Impact | Mitigation |
|--------|------------|--------|------------|
| Malicious package injection | Medium | Critical | Allowlist + signature verification |
| Supply chain attack | Low | Critical | Dependency scanning + signing |
| Unauthorized registration | Medium | High | Authorization levels |
| Data exfiltration | Low | High | Sandboxed execution |
| Code execution | Medium | Critical | Allowlist + code review |

## Security Best Practices

### Development

1. **Never disable allowlist** - Even in development, use patterns
2. **Log all rejections** - Monitor for suspicious patterns
3. **Review third-party adapters** - Code review before allowlisting

### Production

1. **Enable signature verification** - `verify_signatures: true`
2. **Reject unsigned adapters** - `reject_unsigned: true`
3. **Use TLS for gRPC** - `use_tls: true`
4. **Restrict allowlist** - Only trusted modules
5. **Monitor alerts** - Configure Grafana alerting

### Secrets Management

```bash
# Environment variables for secrets
export MAHAVISHNU_ADAPTER_SIGNING_KEY="/secure/path/to/signing.key"
export MAHAVISHNU_ONEIRIC_TLS_CERT="/secure/path/to/tls.crt"
export MAHAVISHNU_ONEIRIC_TLS_KEY="/secure/path/to/tls.key"
```

## Consequences

### Positive

- **Supply chain protection** - Allowlist prevents random package injection
- **Audit trail** - All operations logged for forensics
- **Production hardening** - TLS and signatures required
- **Defense in depth** - Multiple security layers
- **Monitoring** - Prometheus metrics and Grafana alerts

### Negative

- **Development friction** - Allowlist must be updated for new adapters
- **Operational overhead** - Certificate management for TLS
- **Performance** - Signature verification adds latency

### Risks

- **Risk:** Allowlist too permissive
  **Mitigation:** Regular audit of patterns, restrict to specific modules

- **Risk:** Signature key compromise
  **Mitigation:** Rotate keys, use HSM for production

- **Risk:** Development settings in production
  **Mitigation:** Configuration validation at startup

## Implementation Checklist

- [x] Allowlist pattern validation in discovery engine
- [x] Authorization levels in AdapterMetadata
- [x] Audit logging for registrations and rejections
- [x] Prometheus security metrics
- [x] Grafana security alerts
- [ ] Signature verification (optional, production-only)
- [ ] Sandboxed execution (future enhancement)
- [ ] TLS certificate automation (future enhancement)

## References

- ADR 009: Hybrid Adapter Registry with Dynamic Discovery
- [Python Entry Points Security](https://packaging.python.org/en/latest/specifications/entry-points/)
- [OWASP Supply Chain Security](https://owasp.org/www-project-software-supply-chain-security/)
- [gRPC Security Best Practices](https://grpc.io/docs/guides/auth/)
