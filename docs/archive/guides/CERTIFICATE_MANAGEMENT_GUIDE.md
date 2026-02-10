# Certificate Management Guide

**Mahavishnu Certificate Management System - Complete Operational Guide**

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Oneiric Integration](#oneiric-integration)
4. [Certificate Storage](#certificate-storage)
5. [Let's Encrypt Integration](#lets-encrypt-integration)
6. [Certificate Lifecycle Management](#certificate-lifecycle-management)
7. [Automation](#automation)
8. [Multi-Region Propagation](#multi-region-propagation)
9. [Monitoring and Alerting](#monitoring-and-alerting)
10. [Setup Guides](#setup-guides)
11. [Security Best Practices](#security-best-practices)
12. [Troubleshooting](#troubleshooting)
13. [API Reference](#api-reference)

---

## Overview

The Mahavishnu Certificate Management system provides comprehensive SSL/TLS certificate lifecycle management with automated provisioning, renewal, and multi-region propagation capabilities.

### Key Features

- **Automated Provisioning**: Let's Encrypt ACME integration with zero-touch certificate issuance
- **Intelligent Renewal**: Automatic renewal before expiration (configurable threshold)
- **Multi-Domain Support**: SAN certificates with up to 100 domains per certificate
- **Wildcard Certificates**: Support for wildcard domains (*.example.com)
- **Multi-Region Propagation**: Automatic certificate distribution across regions/providers
- **Storage Backends**: Encrypted local storage or cloud provider integration
- **Challenge Types**: HTTP-01 and DNS-01 validation methods
- **Monitoring**: Real-time certificate expiration tracking and health checks
- **Security**: AES-256-GCM encryption for private keys at rest

### Certificate Types Supported

| Type | Description | Use Case |
|------|-------------|----------|
| **Single Domain** | Standard certificate for one domain | Simple websites |
| **SAN Certificate** | Subject Alternative Names with multiple domains | Multi-domain applications |
| **Wildcard Certificate** | Wildcard for subdomain (*.example.com) | Subdomain-heavy applications |
| **EV Certificate** | Extended Validation (manual process) | Enterprise applications |

---

## Architecture

### System Components

```
┌─────────────────────────────────────────────────────────────┐
│                     Mahavishnu Application                  │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                  CertificateManager                         │
│  ┌──────────────┐  ┌───────────────┐  ┌─────────────────┐ │
│  │ Certificate  │  │   LetsEncrypt │  │   Certificate   │ │
│  │    Store     │  │  Integration  │  │   Automation    │ │
│  └──────────────┘  └───────────────┘  └─────────────────┘ │
└─────────────────────────────────────────────────────────────┘
                              │
          ┌───────────────────┼───────────────────┐
          ▼                   ▼                   ▼
┌──────────────────┐  ┌──────────────┐  ┌─────────────────┐
│  Local Storage   │  │   Let's      │  │  Cloud Providers│
│  (Encrypted)     │  │   Encrypt    │  │  (AWS/Azure)    │
└──────────────────┘  └──────────────┘  └─────────────────┘
```

### Component Responsibilities

**CertificateManager**
- Certificate issuance and renewal orchestration
- Challenge validation management
- Multi-region propagation coordination

**CertificateStore**
- Encrypted certificate storage (AES-256-GCM)
- Certificate metadata tracking
- Expiration monitoring

**LetsEncryptIntegration**
- ACME protocol implementation
- Challenge handling (HTTP-01, DNS-01)
- Certificate signing request (CSR) generation

**CertificateAutomation**
- Scheduled renewal jobs
- Health checks and monitoring
- Alert generation

**CertificateMonitoring**
- Expiration tracking
- Certificate validity verification
- Metrics collection (Prometheus)

---

## Oneiric Integration

The Certificate Management system uses Oneiric's layered configuration system for flexible, environment-aware certificate configuration.

### Extending Oneiric for Certificate Configuration

Mahavishnu extends Oneiric to provide certificate-specific configuration layers:

```python
# Oneiric configuration layers for certificate management
# Layer order (lower priority → higher priority):
# 1. Default values in Pydantic models
# 2. settings/mahavishnu.yaml (committed)
# 3. settings/local.yaml (gitignored)
# 4. Environment variables MAHAVISHNU_CERTIFICATE_*
```

### Configuration Schema

**`settings/mahavishnu.yaml`**

```yaml
# Certificate Management Configuration
certificate_management:
  enabled: true

  # Storage configuration
  storage:
    backend: local  # local, aws, azure
    encryption_key_path: /etc/mahavishnu/cert_key
    storage_path: /var/lib/mahavishnu/certificates

  # Let's Encrypt configuration
  lets_encrypt:
    enabled: true
    staging: false  # Use staging for development
    email: admin@example.com
    directory_url: https://acme-v02.api.letsencrypt.org/directory

  # Challenge configuration
  challenges:
    default_type: http-01  # http-01, dns-01
    http_port: 80
    dns_provider: cloudflare  # cloudflare, route53, azure

  # Automation configuration
  automation:
    auto_renew: true
    renewal_threshold_days: 30  # Renew 30 days before expiration
    check_interval_hours: 24
    retry_attempts: 3
    retry_delay_seconds: 300

  # Multi-region configuration
  multi_region:
    enabled: false
    regions:
      - name: us-east-1
        provider: aws
        acm_enabled: true
      - name: westeurope
        provider: azure
        key_vault: https://kv.vault.azure.net/

  # Monitoring configuration
  monitoring:
    enabled: true
    prometheus_port: 9091
    alert_threshold_days: 14
```

**`settings/local.yaml` (gitignored)**

```yaml
# Local development overrides
certificate_management:
  lets_encrypt:
    staging: true  # Use Let's Encrypt staging in development
  storage:
    storage_path: ./dev_certificates
```

### Environment Variables

```bash
# Override settings via environment variables
export MAHAVISHNU_CERTIFICATE_MANAGEMENT_ENABLED=true
export MAHAVISHNU_CERTIFICATE_LETS_ENCRYPT_STAGING=false
export MAHAVISHNU_CERTIFICATE_STORAGE_BACKEND=aws
export MAHAVISHNU_CERTIFICATE_AUTOMATION_RENEWAL_THRESHOLD_DAYS=30
```

### Accessing Configuration in Code

```python
from mahavishnu.integrations.certificate_management import CertificateManager
from mahavishnu.core.config import MahavishnuSettings

# Load configuration
settings = MahavishnuSettings()

# Initialize certificate manager
cert_manager = CertificateManager(
    storage_backend=settings.certificate_management.storage.backend,
    encryption_key_path=settings.certificate_management.storage.encryption_key_path,
    lets_encrypt_enabled=settings.certificate_management.lets_encrypt.enabled,
    staging=settings.certificate_management.lets_encrypt.staging,
)

# Access configuration
if settings.certificate_management.automation.auto_renew:
    await cert_manager.enable_auto_renewal(
        threshold_days=settings.certificate_management.automation.renewal_threshold_days
    )
```

### Dynamic Configuration Updates

```python
# Update configuration at runtime (requires restart for some settings)
from mahavishnu.core.config import update_config

await update_config({
    "certificate_management": {
        "automation": {
            "renewal_threshold_days": 45  # Increase threshold
        }
    }
})
```

---

## Certificate Storage

### Storage Backends

#### Local Storage (Encrypted)

Default backend for development and single-region deployments.

```python
from mahavishnu.integrations.certificate_management import CertificateStore

# Initialize local store
store = CertificateStore(
    backend="local",
    storage_path="/var/lib/mahavishnu/certificates",
    encryption_key_path="/etc/mahavishnu/cert_key"
)

# Store certificate
await store.store_certificate(
    certificate_id="cert_abc123",
    certificate_pem="-----BEGIN CERTIFICATE-----...",
    private_key_pem="-----BEGIN PRIVATE KEY-----...",
    domains=["example.com", "www.example.com"],
    expires_at=datetime(2025, 3, 5),
)

# Retrieve certificate
cert = await store.get_certificate("cert_abc123")
print(cert.certificate_pem)
print(cert.domains)  # ['example.com', 'www.example.com']
```

**Security**:
- Private keys encrypted with AES-256-GCM
- Encryption key derived from key file using PBKDF2
- File permissions: 0600 (owner read/write only)

#### AWS Certificate Manager (ACM)

Integration for AWS deployments.

```yaml
# settings/mahavishnu.yaml
certificate_management:
  storage:
    backend: aws
    aws_region: us-east-1
```

```python
from mahavishnu.integrations.certificate_management import CertificateStore

# Initialize AWS store
store = CertificateStore(
    backend="aws",
    aws_region="us-east-1"
)

# Certificate is automatically imported into ACM
await store.store_certificate(
    certificate_id="cert_abc123",
    certificate_pem="...",
    private_key_pem="...",
    domains=["example.com"],
    expires_at=datetime(2025, 3, 5),
)
```

#### Azure Key Vault

Integration for Azure deployments.

```yaml
# settings/mahavishnu.yaml
certificate_management:
  storage:
    backend: azure
    azure_key_vault_url: https://kv.vault.azure.net/
```

```python
# Initialize Azure store
store = CertificateStore(
    backend="azure",
    azure_key_vault_url="https://kv.vault.azure.net/"
)

# Certificate is automatically imported into Key Vault
await store.store_certificate(
    certificate_id="cert_abc123",
    certificate_pem="...",
    private_key_pem="...",
    domains=["example.com"],
    expires_at=datetime(2025, 3, 5),
)
```

### Certificate Metadata

```python
from mahavishnu.integrations.certificate_management import CertificateMetadata

metadata = CertificateMetadata(
    certificate_id="cert_abc123",
    domains=["example.com", "www.example.com"],
    issued_at=datetime.now(),
    expires_at=datetime(2025, 3, 5),
    auto_renew=True,
    challenge_type="http-01",
    key_size=2048,
    organization="Example Corp",
    country="US",
    state="California",
    locality="San Francisco",
)

# Access metadata
print(metadata.days_until_expiration)  # 30
print(metadata.is_expiring_soon(days=30))  # True
```

---

## Let's Encrypt Integration

### ACME Protocol

Mahavishnu implements the ACME (Automatic Certificate Management Environment) protocol for Let's Encrypt integration.

### Setup

**Production Environment**

```yaml
# settings/mahavishnu.yaml
certificate_management:
  lets_encrypt:
    enabled: true
    staging: false
    email: admin@example.com
    directory_url: https://acme-v02.api.letsencrypt.org/directory
    account_key_path: /etc/mahavishnu/acme_account_key.pem
```

**Staging Environment** (Recommended for development)

```yaml
# settings/local.yaml
certificate_management:
  lets_encrypt:
    staging: true
    directory_url: https://acme-staging-v02.api.letsencrypt.org/directory
```

### Challenge Types

#### HTTP-01 Challenge

Default challenge type. Requires port 80 access.

```python
from mahavishnu.integrations.certificate_management import CertificateManager

cert_manager = CertificateManager()

# Issue certificate with HTTP-01 challenge
certificate = await cert_manager.issue_certificate(
    domains=["example.com", "www.example.com"],
    email="admin@example.com",
    challenge_type="http-01",
)

# Mahavishnu automatically serves the challenge file at:
# http://example.com/.well-known/acme-challenge/<token>
```

**Requirements**:
- Port 80 must be accessible from the internet
- Web server must serve files from `/.well-known/acme-challenge/`

#### DNS-01 Challenge

Required for wildcard certificates.

```python
# Issue wildcard certificate with DNS-01 challenge
certificate = await cert_manager.issue_certificate(
    domains=["*.example.com", "example.com"],
    email="admin@example.com",
    challenge_type="dns-01",
    dns_provider="cloudflare",  # cloudflare, route53, azure
)

# Mahavishnu automatically creates the TXT record:
# _acme-challenge.example.com TXT <validation_token>
```

**DNS Provider Configuration**

**Cloudflare**

```yaml
# settings/mahavishnu.yaml
certificate_management:
  challenges:
    dns_provider: cloudflare
    cloudflare:
      api_token: CF_API_TOKEN  # From environment variable
```

**AWS Route 53**

```yaml
certificate_management:
  challenges:
    dns_provider: route53
    route53:
      access_key_id: AWS_ACCESS_KEY_ID
      secret_access_key: AWS_SECRET_ACCESS_KEY
      region: us-east-1
```

**Azure DNS**

```yaml
certificate_management:
  challenges:
    dns_provider: azure
    azure:
      subscription_id: AZURE_SUBSCRIPTION_ID
      resource_group: example-rg
      zone_name: example.com
```

### Certificate Issuance Workflow

```python
from mahavishnu.integrations.certificate_management import (
    CertificateManager,
    CertificateMetadata,
)

# Initialize manager
cert_manager = CertificateManager()

# Define certificate metadata
metadata = CertificateMetadata(
    domains=["example.com", "www.example.com"],
    organization="Example Corp",
    country="US",
    state="California",
    locality="San Francisco",
)

# Issue certificate
certificate = await cert_manager.issue_certificate(
    domains=metadata.domains,
    email="admin@example.com",
    organization=metadata.organization,
    country=metadata.country,
    state=metadata.state,
    locality=metadata.locality,
    key_size=2048,
    challenge_type="http-01",
    auto_renew=True,
)

# Certificate issued
print(f"Certificate ID: {certificate.id}")
print(f"Domains: {certificate.domains}")
print(f"Expires: {certificate.expires_at}")
print(f"Certificate PEM:\n{certificate.certificate_pem}")
```

---

## Certificate Lifecycle Management

### Certificate Lifecycle

```
┌──────────────┐
│  REQUESTED   │
└──────┬───────┘
       │
       ▼
┌──────────────┐
│   ISSUING    │ ← ACME Challenge Validation
└──────┬───────┘
       │
       ▼
┌──────────────┐
│   ISSUED     │ ← Certificate Stored
└──────┬───────┘
       │
       ▼
┌──────────────┐
│   ACTIVE     │ ← Certificate in Use
└──────┬───────┘
       │
       ▼
┌──────────────┐
│  RENEWING    │ ← Auto-renewal Triggered
└──────┬───────┘
       │
       ▼
┌──────────────┐
│   REVOKED    │ ← Certificate Revoked (Optional)
└──────────────┘
```

### Certificate States

| State | Description | Transitions |
|-------|-------------|-------------|
| **REQUESTED** | Certificate issuance initiated | → ISSUING |
| **ISSUING** | ACME challenge validation in progress | → ISSUED, FAILED |
| **ISSUED** | Certificate issued and stored | → ACTIVE |
| **ACTIVE** | Certificate currently in use | → RENEWING, REVOKED, EXPIRED |
| **RENEWING** | Certificate renewal in progress | → ACTIVE |
| **REVOKED** | Certificate revoked before expiration | → (end state) |
| **EXPIRED** | Certificate passed expiration date | → (end state) |
| **FAILED** | Certificate issuance failed | → REQUESTED (retry) |

### Certificate Renewal

**Automatic Renewal**

```yaml
# settings/mahavishnu.yaml
certificate_management:
  automation:
    auto_renew: true
    renewal_threshold_days: 30  # Renew 30 days before expiration
    check_interval_hours: 24
```

```python
# Automatic renewal is handled by CertificateAutomation
from mahavishnu.integrations.certificate_management import CertificateAutomation

automation = CertificateAutomation(cert_manager)

# Start automatic renewal job
await automation.start_renewal_job(
    check_interval_hours=24
)

# System automatically checks and renews certificates
# within 30 days of expiration
```

**Manual Renewal**

```python
# Manually renew a certificate
certificate = await cert_manager.renew_certificate(
    certificate_id="cert_abc123",
)

print(f"Renewed certificate: {certificate.id}")
print(f"New expiration: {certificate.expires_at}")
```

**Force Renewal** (regardless of expiration)

```python
# Force renewal (e.g., after key compromise)
certificate = await cert_manager.renew_certificate(
    certificate_id="cert_abc123",
    force=True,
)
```

### Certificate Revocation

```python
# Revoke a certificate (e.g., after key compromise)
await cert_manager.revoke_certificate(
    certificate_id="cert_abc123",
    reason="keyCompromise",  # keyCompromise, affiliationChanged, etc.
)

# Certificate is immediately revoked via Let's Encrypt ACME
```

### Certificate Expiration Monitoring

```python
from mahavishnu.integrations.certificate_management import CertificateMonitoring

monitoring = CertificateMonitoring(cert_manager)

# Check for expiring certificates
expiring_certs = await monitoring.get_expiring_certificates(
    within_days=30,
)

for cert in expiring_certs:
    print(f"ALERT: {cert.domains} expires in {cert.days_until_expiration} days")

# Get certificate health status
health = await monitoring.get_health_status()
print(f"Total certificates: {health['total']}")
print(f"Expiring soon: {health['expiring_soon']}")
print(f"Expired: {health['expired']}")
```

---

## Automation

### Scheduled Renewal Jobs

```python
from mahavishnu.integrations.certificate_management import CertificateAutomation
import asyncio

automation = CertificateAutomation(cert_manager)

# Start renewal job (runs every 24 hours)
async def renewal_task():
    while True:
        await automation.check_and_renew_all()
        await asyncio.sleep(24 * 3600)  # 24 hours

# Run in background
task = asyncio.create_task(renewal_task())
```

### Health Checks

```python
# Health check endpoint for Kubernetes/Monitoring
async def health_check():
    monitoring = CertificateMonitoring(cert_manager)
    health = await monitoring.get_health_status()

    if health["expired"] > 0:
        return {"status": "unhealthy", "expired": health["expired"]}

    if health["expiring_soon"] > 0:
        return {
            "status": "degraded",
            "expiring_soon": health["expiring_soon"]
        }

    return {"status": "healthy"}

# Kubernetes probe
@app.get("/health/certificates")
async def certificate_health():
    return await health_check()
```

### Metrics (Prometheus)

```yaml
# settings/mahavishnu.yaml
certificate_management:
  monitoring:
    enabled: true
    prometheus_port: 9091
```

```python
# Metrics exposed at :9091/metrics
# Example metrics:
# certificate_days_until_expiration{domain="example.com"} 30
# certificate_renewal_total{status="success"} 5
# certificate_validation_errors_total{type="http-01"} 0
```

**Grafana Dashboard**

```json
{
  "dashboard": {
    "title": "Certificate Monitoring",
    "panels": [
      {
        "title": "Days Until Expiration",
        "targets": [
          {
            "expr": "certificate_days_until_expiration"
          }
        ]
      },
      {
        "title": "Renewal Success Rate",
        "targets": [
          {
            "expr": "rate(certificate_renewal_total{status=\"success\"}[5m])"
          }
        ]
      }
    ]
  }
}
```

---

## Multi-Region Propagation

### Architecture

```
┌─────────────────────────────────────────────────────────┐
│              Mahavishnu Certificate Manager              │
└────────────────┬────────────────────────────────────────┘
                 │
                 │ Issue Certificate
                 ▼
        ┌────────────────┐
        │ Certificate    │
        │ Store          │
        └────────┬───────┘
                 │
                 │ Propagate
                 ▼
┌─────────────────────────────────────────────────────────┐
│                    Propagation Engine                    │
└─────────────────────────────────────────────────────────┘
         │                  │                  │
         ▼                  ▼                  ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│ AWS ACM         │  │ Azure Key Vault │  │ GCP Certificate │
│ (us-east-1)     │  │ (westeurope)    │  │ Manager         │
└─────────────────┘  └─────────────────┘  └─────────────────┘
```

### Configuration

```yaml
# settings/mahavishnu.yaml
certificate_management:
  multi_region:
    enabled: true
    propagation_strategy: sync  # sync, async
    regions:
      - name: us-east-1
        provider: aws
        acm_enabled: true
      - name: westeurope
        provider: azure
        key_vault_url: https://kv.vault.azure.net/
      - name: us-central1
        provider: gcp
        project_id: example-project
```

### Propagation Methods

**Synchronous Propagation** (Wait for all regions)

```python
# Propagate certificate to all regions (blocks until complete)
result = await cert_manager.propagate_certificate(
    certificate_id="cert_abc123",
    strategy="sync",  # Wait for all regions
)

print(f"Propagation status: {result.status}")
print(f"Regions: {result.regions}")
# {
#   "us-east-1": "success",
#   "westeurope": "success",
#   "us-central1": "success"
# }
```

**Asynchronous Propagation** (Fire and forget)

```python
# Propagate asynchronously (returns immediately)
result = await cert_manager.propagate_certificate(
    certificate_id="cert_abc123",
    strategy="async",  # Don't wait
)

print(f"Propagation initiated: {result.task_id}")
```

### Per-Region Configuration

**AWS ACM**

```python
from mahavishnu.integrations.certificate_management import AWSACMAdapter

acm_adapter = AWSACMAdapter(region="us-east-1")

# Import certificate into ACM
acm_arn = await acm_adapter.import_certificate(
    certificate_pem=certificate.certificate_pem,
    private_key_pem=certificate.private_key_pem,
    certificate_chain=certificate.chain_pem,
)

print(f"Imported into ACM: {acm_arn}")
```

**Azure Key Vault**

```python
from mahavishnu.integrations.certificate_management import AzureKeyVaultAdapter

kv_adapter = AzureKeyVaultAdapter(
    vault_url="https://kv.vault.azure.net/"
)

# Import certificate into Key Vault
kv_cert_id = await kv_adapter.import_certificate(
    certificate_pem=certificate.certificate_pem,
    private_key_pem=certificate.private_key_pem,
    name="example-com-cert",
)

print(f"Imported into Key Vault: {kv_cert_id}")
```

---

## Monitoring and Alerting

### Prometheus Metrics

| Metric | Type | Description |
|--------|------|-------------|
| `certificate_days_until_expiration` | Gauge | Days until certificate expiration |
| `certificate_renewal_total` | Counter | Total renewal attempts |
| `certificate_validation_errors_total` | Counter | Total ACME validation errors |
| `certificate_propagation_total` | Counter | Total propagation attempts |

### Alerting Rules (Prometheus)

```yaml
# alerting_rules.yml
groups:
  - name: certificate_alerts
    rules:
      # Critical: Certificate expired
      - alert: CertificateExpired
        expr: certificate_days_until_expiration < 0
        for: 0m
        labels:
          severity: critical
        annotations:
          summary: "Certificate has expired: {{ $labels.domain }}"
          description: "Certificate for {{ $labels.domain }} expired {{ $value }} days ago"

      # Warning: Certificate expiring soon
      - alert: CertificateExpiringSoon
        expr: certificate_days_until_expiration < 30
        for: 1h
        labels:
          severity: warning
        annotations:
          summary: "Certificate expiring soon: {{ $labels.domain }}"
          description: "Certificate for {{ $labels.domain }} expires in {{ $value }} days"

      # Critical: Certificate renewal failure
      - alert: CertificateRenewalFailure
        expr: rate(certificate_renewal_total{status="failure"}[5m]) > 0
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Certificate renewal failing"
          description: "Certificate renewal failure rate: {{ $value }}/sec"
```

### Grafana Dashboard

Import pre-built dashboard from `docs/grafana/CertificateMonitoring.json`.

**Key Panels**:
- Days until expiration (by domain)
- Renewal success/failure rate
- ACME validation errors
- Propagation status (by region)
- Certificate inventory

---

## Setup Guides

### Development Setup

**Prerequisites**:
- Python 3.10+
- Local development environment

**Installation**:

```bash
# Install dependencies
pip install -e ".[certificate]"

# Create local configuration
cat > settings/local.yaml << EOF
certificate_management:
  lets_encrypt:
    staging: true  # Use Let's Encrypt staging
  storage:
    storage_path: ./dev_certificates
EOF

# Initialize certificate manager
python -c "
from mahavishnu.integrations.certificate_management import CertificateManager

cert_manager = CertificateManager()
print('Certificate manager initialized')
"
```

**Usage**:

```python
# Issue a staging certificate
cert_manager = CertificateManager()

certificate = await cert_manager.issue_certificate(
    domains=["localhost.example.com"],  # Use a public domain
    email="admin@example.com",
    challenge_type="dns-01",
    staging=True,
)
```

### Production Setup

**Prerequisites**:
- Publicly accessible server
- Domain name configured
- Port 80 open (for HTTP-01 challenges)

**Installation**:

```bash
# Install dependencies
pip install -e ".[certificate]"

# Create production configuration
cat > settings/mahavishnu.yaml << EOF
certificate_management:
  enabled: true
  lets_encrypt:
    enabled: true
    staging: false
    email: letsencrypt@example.com
  automation:
    auto_renew: true
    renewal_threshold_days: 30
  monitoring:
    enabled: true
    prometheus_port: 9091
EOF

# Set environment variables
export MAHAVISHNU_CERTIFICATE_LETS_ENCRYPT_EMAIL="letsencrypt@example.com"

# Run certificate manager
python -m mahavishnu.integrations.certificate_management
```

**Systemd Service**:

```ini
# /etc/systemd/system/mahavishnu-certificates.service
[Unit]
Description=Mahavishnu Certificate Manager
After=network.target

[Service]
Type=simple
User=mahavishnu
Group=mahavishnu
WorkingDirectory=/opt/mahavishnu
Environment="PATH=/opt/mahavishnu/venv/bin"
ExecStart=/opt/mahavishnu/venv/bin/python -m mahavishnu.integrations.certificate_management
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
# Enable and start service
sudo systemctl enable mahavishnu-certificates
sudo systemctl start mahavishnu-certificates
sudo systemctl status mahavishnu-certificates
```

### AWS Setup

**Prerequisites**:
- AWS Account with ACM access
- IAM credentials with `acm:ImportCertificate` permission

**Configuration**:

```yaml
# settings/mahavishnu.yaml
certificate_management:
  storage:
    backend: aws
    aws_region: us-east-1
  multi_region:
    enabled: true
    regions:
      - name: us-east-1
        provider: aws
        acm_enabled: true
```

**IAM Policy**:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "acm:ImportCertificate",
        "acm:GetCertificate",
        "acm:ListCertificates",
        "acm:DeleteCertificate"
      ],
      "Resource": "arn:aws:acm:us-east-1:123456789012:certificate/*"
    }
  ]
}
```

### Azure Setup

**Prerequisites**:
- Azure subscription with Key Vault
- Service principal with Key Vault certificates access

**Configuration**:

```yaml
# settings/mahavishnu.yaml
certificate_management:
  storage:
    backend: azure
    azure_key_vault_url: https://kv-example.vault.azure.net/
  multi_region:
    enabled: true
    regions:
      - name: westeurope
        provider: azure
        key_vault_url: https://kv-example.vault.azure.net/
```

**Azure RBAC**:

```bash
# Grant Key Vault certificates access
az keyvault set-policy \
  --name kv-example \
  --certificate-permissions import get list delete \
  --spn $SERVICE_PRINCIPAL_ID
```

---

## Security Best Practices

### Private Key Protection

**Never expose private keys in logs**:

```python
import logging

# SAFE: Log certificate metadata only
logger.info(f"Certificate issued: {certificate.id} for {certificate.domains}")

# UNSAFE: Logs private key
logger.info(f"Private key: {certificate.private_key_pem}")  # NEVER DO THIS
```

**Encrypt private keys at rest**:

```yaml
# settings/mahavishnu.yaml
certificate_management:
  storage:
    encryption_key_path: /etc/mahavishnu/cert_key
```

```bash
# Set proper file permissions
sudo chmod 600 /etc/mahavishnu/cert_key
sudo chown mahavishnu:mahavishnu /etc/mahavishnu/cert_key
```

### ACME Account Security

**Protect ACME account key**:

```bash
# Generate strong account key
openssl genrsa 4096 > /etc/mahavishnu/acme_account_key.pem
chmod 600 /etc/mahavishnu/acme_account_key.pem
```

**Use production Let's Encrypt carefully**:

```yaml
# settings/local.yaml (development)
certificate_management:
  lets_encrypt:
    staging: true  # Always use staging in development

# settings/mahavishnu.yaml (production)
certificate_management:
  lets_encrypt:
    staging: false  # Only disable in production
```

### Certificate Revocation

**Revoke compromised certificates immediately**:

```python
# After key compromise
await cert_manager.revoke_certificate(
    certificate_id="cert_abc123",
    reason="keyCompromise",
)

# Issue new certificate with new key
new_cert = await cert_manager.issue_certificate(
    domains=["example.com"],
    email="admin@example.com",
    force_new_key=True,  # Generate new private key
)
```

### Rate Limiting

**Let's Encrypt has strict rate limits**:

- **Production**: 50 certificates per domain per week
- **Staging**: No limits (use staging for testing)

```python
# Always test in staging first
cert_manager = CertificateManager(staging=True)
# ... test issuance ...

# Only use production after successful staging test
cert_manager = CertificateManager(staging=False)
```

---

## Troubleshooting

### Common Issues

#### Issue: "Connection timeout during ACME challenge"

**Cause**: Port 80 not accessible from internet

**Solution**:

```bash
# Check port 80 is open
sudo netstat -tlnp | grep :80

# Check firewall rules
sudo ufw allow 80/tcp
# or
sudo iptables -A INPUT -p tcp --dport 80 -j ACCEPT

# Verify connectivity from internet
curl http://your-domain.com/.well-known/acme-challenge/test
```

#### Issue: "DNS-01 challenge failed"

**Cause**: DNS record not created or propagated

**Solution**:

```bash
# Wait for DNS propagation
dig _acme-challenge.example.com TXT

# Check DNS provider credentials
# For Cloudflare:
export CLOUDFLARE_API_TOKEN=your_token

# For Route 53:
export AWS_ACCESS_KEY_ID=your_key
export AWS_SECRET_ACCESS_KEY=your_secret
```

#### Issue: "Certificate import to ACM failed"

**Cause**: Insufficient IAM permissions

**Solution**:

```bash
# Check IAM permissions
aws iam get-user-policy --user-name mahavishnu --policy-name ACMImport

# Add required permissions:
# acm:ImportCertificate
# acm:GetCertificate
```

#### Issue: "Certificate expired despite auto-renewal"

**Cause**: Auto-renewal job not running

**Solution**:

```bash
# Check automation service status
sudo systemctl status mahavishnu-certificates

# Check logs
sudo journalctl -u mahavishnu-certificates -n 50

# Manually trigger renewal
await cert_manager.renew_certificate("cert_abc123")
```

### Debug Mode

Enable debug logging:

```yaml
# settings/local.yaml
logging:
  level: DEBUG
```

```python
import logging
logging.basicConfig(level=logging.DEBUG)

# Now all ACME operations will be logged
cert_manager = CertificateManager()
```

### Health Checks

```bash
# Check certificate manager health
curl http://localhost:9091/health

# Check Prometheus metrics
curl http://localhost:9091/metrics

# Check certificate status
python -c "
from mahavishnu.integrations.certificate_management import CertificateMonitoring

monitoring = CertificateMonitoring(cert_manager)
health = await monitoring.get_health_status()
print(health)
"
```

---

## API Reference

### CertificateManager

**`__init__(config: MahavishnuSettings)`**

Initialize certificate manager with configuration.

**`async issue_certificate(domains: list[str], email: str, **kwargs) -> Certificate`**

Issue a new certificate.

**Parameters**:
- `domains`: List of domains (required)
- `email`: Contact email (required)
- `organization`: Organization name
- `country`: Country code (2-letter)
- `state`: State/province
- `locality`: City
- `key_size`: RSA key size (default: 2048)
- `challenge_type`: Challenge type (http-01, dns-01)
- `auto_renew`: Enable auto-renewal (default: true)

**Returns**: Certificate object

**Example**:

```python
certificate = await cert_manager.issue_certificate(
    domains=["example.com", "www.example.com"],
    email="admin@example.com",
    organization="Example Corp",
    key_size=2048,
    challenge_type="http-01",
)
```

**`async renew_certificate(certificate_id: str, force: bool = False) -> Certificate`**

Renew an existing certificate.

**Parameters**:
- `certificate_id`: Certificate ID to renew
- `force`: Force renewal regardless of expiration

**Returns**: Renewed certificate object

**`async revoke_certificate(certificate_id: str, reason: str = "unspecified") -> None`**

Revoke a certificate.

**Parameters**:
- `certificate_id`: Certificate ID to revoke
- `reason`: Revocation reason (keyCompromise, affiliationChanged, etc.)

**`async propagate_certificate(certificate_id: str, strategy: str = "sync") -> PropagationResult`**

Propagate certificate to multi-region backends.

**Parameters**:
- `certificate_id`: Certificate ID to propagate
- `strategy`: Propagation strategy (sync, async)

**Returns**: PropagationResult object

### CertificateStore

**`async store_certificate(certificate_id: str, certificate_pem: str, private_key_pem: str, **kwargs) -> None`**

Store a certificate.

**`async get_certificate(certificate_id: str) -> Certificate`**

Retrieve a certificate by ID.

**`async list_certificates(filter: dict = None) -> list[Certificate]`**

List all certificates with optional filtering.

**`async delete_certificate(certificate_id: str) -> None`**

Delete a certificate.

### CertificateMonitoring

**`async get_expiring_certificates(within_days: int = 30) -> list[Certificate]`**

Get certificates expiring within specified days.

**`async get_health_status() -> dict`**

Get overall certificate health status.

**Returns**: Dictionary with total, expiring_soon, expired counts

### CertificateAutomation

**`async start_renewal_job(check_interval_hours: int = 24) -> None`**

Start automatic renewal background job.

**`async stop_renewal_job() -> None`**

Stop automatic renewal job.

**`async check_and_renew_all() -> dict`**

Check all certificates and renew if needed.

---

## Additional Resources

- [Let's Encrypt Documentation](https://letsencrypt.org/docs/)
- [ACME Protocol RFC](https://datatracker.ietf.org/doc/html/rfc8555)
- [AWS ACM Documentation](https://docs.aws.amazon.com/acm/)
- [Azure Key Vault Documentation](https://docs.microsoft.com/en-us/azure/key-vault/)
- [OpenTelemetry Documentation](https://opentelemetry.io/docs/)

---

**Last Updated**: 2025-02-05
**Version**: 1.0.0
**Maintainer**: Mahavishnu Team
