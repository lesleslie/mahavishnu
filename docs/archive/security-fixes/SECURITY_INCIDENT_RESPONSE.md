# Security Incident Response Runbooks

**Version**: 1.0.0
**Last Updated**: 2026-02-05
**Status**: Production Ready

---

## Table of Contents

1. [Incident Response Overview](#incident-response-overview)
2. [Incident Classification](#incident-classification)
3. [Incident Response Procedures](#incident-response-procedures)
4. [Specific Incident Runbooks](#specific-incident-runbooks)
5. [Communication Procedures](#communication-procedures)
6. [Post-Incident Activities](#post-incident-activities)
7. [Automation & Tooling](#automation--tooling)

---

## Incident Response Overview

### Incident Response Lifecycle

```
┌─────────────────────────────────────────────────────────────────┐
│                     Incident Response Lifecycle                   │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  1. PREPARATION          2. DETECTION & ANALYSIS                │
│  ├─ IR team setup       ├─ Monitor alerts                       │
│  ├─ Tool deployment     ├─ Triage incidents                     │
│  ├─ Training            ├─ Investigate                           │
│  └─ Runbook creation    └─ Determine scope                      │
│                                                                  │
│  3. CONTAINMENT         4. ERADICATION                          │
│  ├─ Isolate systems     ├─ Remove malware                       │
│  ├─ Block IPs           ├─ Patch vulnerabilities                 │
│  ├─ Disable accounts    ├─ Change credentials                   │
│  └─ Disconnect networks └─ Fix misconfigurations                 │
│                                                                  │
│  5. RECOVERY            6. LESSONS LEARNED                       │
│  ├─ Restore systems     ├─ Post-incident review                 │
│  ├─ Verify integrity    ├─ Document findings                    │
│  ├─ Monitor for回流     ├─ Update runbooks                      │
│  └─ Normal operations   └─ Improve processes                     │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Incident Response Team Roles

| Role | Responsibilities | Contact |
|------|------------------|---------|
| **Incident Response Lead** | Overall coordination, decision making | on-call-ir@company.com |
| **Security Analyst** | Technical investigation, evidence collection | security@company.com |
| **DevOps Engineer** | System containment, recovery operations | devops@company.com |
| **Communications Lead** | Internal/external communications | comms@company.com |
| **Legal Counsel** | Legal guidance, regulatory compliance | legal@company.com |
| **Executive Sponsor** | Business impact assessment, escalation | exec@company.com |

---

## Incident Classification

### Severity Levels

| Severity | Description | Response Time | Example |
|----------|-------------|---------------|---------|
| **P0 - Critical** | System compromise, data breach, active attack | 15 minutes | Active ransomware, data exfiltration |
| **P1 - High** | Significant security control failure | 1 hour | Authentication bypass, SQL injection |
| **P2 - Medium** | Security incident with limited impact | 4 hours | Failed authentication spike, malware detected |
| **P3 - Low** | Minor security issue, policy violation | 24 hours | Weak password policy, missing patch |
| **P4 - Info** | Informational, no immediate action needed | 7 days | Security best practice recommendation |

### Incident Types

**Category 1: Malicious Code**
- Ransomware
- Malware infection
- Virus/Trojan
- Crypto miner

**Category 2: Unauthorized Access**
- Brute force attack
- Authentication bypass
- Privilege escalation
- Session hijacking

**Category 3: Data Breach**
- Data exfiltration
- Sensitive data exposure
- Database compromise
- Insider threat

**Category 4: Denial of Service**
- DDoS attack
- Resource exhaustion
- Application DoS
- Network flooding

**Category 5: Web Application Attack**
- SQL injection
- XSS
- CSRF
- SSRF
- API abuse

**Category 6: Misconfiguration**
- Unsecured S3 bucket
- Exposed database
- Default credentials
- Open port

**Category 7: Social Engineering**
- Phishing
- Business email compromise
- Pretexting
- Vishing

---

## Incident Response Procedures

### Standard Operating Procedure (SOP)

#### Phase 1: Detection and Analysis (T+0 to T+1 hour)

**Step 1: Initial Detection**

```python
# mahavishnu/security/incident_detection.py

from datetime import datetime, timedelta
from typing import List, Dict
import structlog

logger = structlog.get_logger(__name__)

class IncidentDetector:
    """Detect security incidents from monitoring data."""

    def __init__(self):
        self.alert_rules = self._load_alert_rules()

    def detect_incidents(self) -> List[Dict]:
        """Detect incidents from various sources."""
        incidents = []

        # Check Falco alerts
        incidents.extend(self._check_falco_alerts())

        # Check authentication logs
        incidents.extend(self._check_auth_logs())

        # Check SIEM alerts
        incidents.extend(self._check_siem_alerts())

        # Check anomaly detection
        incidents.extend(self._check_anomalies())

        return incidents

    def _check_falco_alerts(self) -> List[Dict]:
        """Check Falco runtime security alerts."""
        # Query Falco for recent alerts
        # Filter by severity and type
        pass

    def _check_auth_logs(self) -> List[Dict]:
        """Check authentication logs for suspicious patterns."""
        # Look for:
        # - Brute force patterns (>10 failed attempts from same IP)
        # - Impossible travel (login from 2 continents in <1 hour)
        # - Unusual time (logins at 3 AM)
        # - New device/user agent
        pass

    def _check_siem_alerts(self) -> List[Dict]:
        """Check SIEM for security alerts."""
        # Query Splunk/ELK for security alerts
        # Filter by severity and correlation rules
        pass

    def _check_anomalies(self) -> List[Dict]:
        """Check for anomalous behavior."""
        # Query ML-based anomaly detection
        # Look for deviations from baseline
        pass
```

**Step 2: Initial Triage**

```python
# mahavishnu/security/incident_triage.py

class IncidentTriage:
    """Initial incident triage and classification."""

    def triage_incident(self, incident: Dict) -> Dict:
        """Triage and classify incident."""
        triage_result = {
            "incident_id": self._generate_incident_id(),
            "severity": self._assess_severity(incident),
            "category": self._classify_category(incident),
            "affected_assets": self._identify_assets(incident),
            "indicators": self._extract_indicators(incident),
            "recommendations": self._get_recommendations(incident),
        }

        return triage_result

    def _assess_severity(self, incident: Dict) -> str:
        """Assess incident severity."""
        # Rules-based severity assessment
        severity_score = 0

        # Factor 1: Data sensitivity
        if incident.get("data_exfiltration"):
            severity_score += 40

        # Factor 2: System criticality
        if incident.get("affected_system") == "production":
            severity_score += 30

        # Factor 3: Active exploitation
        if incident.get("active_exploitation"):
            severity_score += 20

        # Factor 4: Public impact
        if incident.get("public_facing"):
            severity_score += 10

        # Map score to severity
        if severity_score >= 80:
            return "P0 - Critical"
        elif severity_score >= 60:
            return "P1 - High"
        elif severity_score >= 40:
            return "P2 - Medium"
        elif severity_score >= 20:
            return "P3 - Low"
        else:
            return "P4 - Info"
```

**Step 3: Investigation**

```python
# mahavishnu/security/incident_investigation.py

class IncidentInvestigator:
    """Detailed incident investigation."""

    def investigate(self, incident_id: str) -> Dict:
        """Conduct detailed investigation."""
        investigation = {
            "incident_id": incident_id,
            "timeline": self._build_timeline(incident_id),
            "root_cause": self._determine_root_cause(incident_id),
            "attack_vector": self._identify_attack_vector(incident_id),
            "scope": self._assess_scope(incident_id),
            "impact": self._assess_impact(incident_id),
            "evidence": self._collect_evidence(incident_id),
        }

        return investigation

    def _build_timeline(self, incident_id: str) -> List[Dict]:
        """Build incident timeline."""
        # Query logs and build chronological timeline
        # Include: initial access, lateral movement, data exfiltration, etc.
        pass

    def _determine_root_cause(self, incident_id: str) -> str:
        """Determine root cause of incident."""
        # Analyze logs and evidence
        # Identify: vulnerability, misconfiguration, human error, etc.
        pass
```

#### Phase 2: Containment (T+1 to T+4 hours)

**Immediate Containment Actions**

```bash
#!/bin/bash
# scripts/incident_containment.sh

# Immediate containment script for security incidents

INCIDENT_ID=$1
SEVERITY=$2

echo "Executing containment for incident: $INCIDENT_ID"
echo "Severity: $SEVERITY"

# 1. Block malicious IPs
block_ip() {
    IP_ADDRESS=$1

    # Block at firewall
    iptables -A INPUT -s $IP_ADDRESS -j DROP

    # Block at application level
    echo "deny $IP_ADDRESS;" >> /etc/nginx/conf.d/blocklist.conf
    nginx -s reload

    echo "Blocked IP: $IP_ADDRESS"
}

# 2. Disable compromised accounts
disable_account() {
    USER_ID=$1

    # Disable in auth system
    mahavishnu auth disable $USER_ID

    # Revoke all sessions
    mahavishnu auth revoke-sessions $USER_ID

    echo "Disabled account: $USER_ID"
}

# 3. Isolate compromised systems
isolate_system() {
    HOSTNAME=$1

    # Disconnect from network
    # (implementation depends on infrastructure)

    echo "Isolated system: $HOSTNAME"
}

# 4. Rotate secrets
rotate_secrets() {
    echo "Rotating all secrets..."

    # Rotate JWT secrets
    mahavishnu secrets rotate jwt

    # Rotate API keys
    mahavishnu secrets rotate api-keys

    # Rotate database credentials
    mahavishnu secrets rotate database

    echo "Secrets rotated"
}

# 5. Enable enhanced monitoring
enable_monitoring() {
    echo "Enabling enhanced monitoring..."

    # Enable verbose logging
    mahavishnu config set log_level DEBUG

    # Enable packet capture
    tcpdump -i any -w /var/log/capture.pcap &

    echo "Enhanced monitoring enabled"
}

# Execute based on severity
case $SEVERITY in
    "P0"|"P1")
        # Critical/High: Execute all containment
        rotate_secrets
        enable_monitoring
        ;;
    "P2"|"P3")
        # Medium/Low: Selective containment
        enable_monitoring
        ;;
esac

echo "Containment complete"
```

**Automated Containment**

```python
# mahavishnu/security/automated_containment.py

class AutomatedContainment:
    """Automated containment based on incident severity."""

    def __init__(self):
        self.containment_strategies = {
            "P0": ["rotate_secrets", "isolate_systems", "enable_monitoring"],
            "P1": ["block_ips", "disable_accounts", "enable_monitoring"],
            "P2": ["block_ips", "enable_monitoring"],
            "P3": ["enable_monitoring"],
        }

    def execute_containment(self, incident: Dict):
        """Execute automated containment based on severity."""
        severity = incident.get("severity", "P4")
        actions = self.containment_strategies.get(severity, [])

        for action in actions:
            if action == "rotate_secrets":
                self._rotate_secrets()
            elif action == "isolate_systems":
                self._isolate_systems(incident.get("affected_assets", []))
            elif action == "block_ips":
                self._block_ips(incident.get("indicators", []))
            elif action == "disable_accounts":
                self._disable_accounts(incident.get("affected_users", []))
            elif action == "enable_monitoring":
                self._enable_monitoring()

    def _rotate_secrets(self):
        """Rotate all secrets."""
        logger.info("Rotating all secrets")
        # Implementation depends on secrets backend
        # HashiCorp Vault, AWS Secrets Manager, etc.
```

#### Phase 3: Eradication (T+4 to T+24 hours)

**Eradication Checklist**

- [ ] Identify and remove malware
- [ ] Patch vulnerabilities
- [ ] Close open ports
- [ ] Fix misconfigurations
- [ ] Remove unauthorized access
- [ ] Sanitize compromised data
- [ ] Verify no backdoors remain

#### Phase 4: Recovery (T+24 to T+72 hours)

**Recovery Procedures**

```python
# mahavishnu/security/incident_recovery.py

class IncidentRecovery:
    """Recovery procedures after incident eradication."""

    def restore_systems(self, incident_id: str):
        """Restore systems to normal operation."""
        # 1. Verify systems are clean
        if not self._verify_clean():
            raise Exception("Systems not clean, cannot proceed with recovery")

        # 2. Restore from clean backups
        self._restore_backups()

        # 3. Change all credentials
        self._change_credentials()

        # 4. Remove containment measures
        self._remove_containment()

        # 5. Monitor for回流
        self._monitor_recovery()

    def _verify_clean(self) -> bool:
        """Verify systems are clean of threats."""
        # Run full security scan
        # Verify no indicators of compromise remain
        pass

    def _restore_backups(self):
        """Restore systems from clean backups."""
        # Restore from verified clean backups
        # Verify data integrity
        pass
```

#### Phase 5: Post-Incident Activities (T+72 hours onwards)

**Lessons Learned Process**

```python
# mahavishnu/security/post_incident.py

class PostIncidentReview:
    """Post-incident review and lessons learned."""

    def conduct_review(self, incident_id: str) -> Dict:
        """Conduct post-incident review."""
        review = {
            "incident_id": incident_id,
            "timeline": self._create_detailed_timeline(incident_id),
            "root_cause_analysis": self._perform_rca(incident_id),
            "impact_assessment": self._assess_impact(incident_id),
            "response_effectiveness": self._evaluate_response(incident_id),
            "lessons_learned": self._extract_lessons(incident_id),
            "recommendations": self._generate_recommendations(incident_id),
            "action_items": self._create_action_items(incident_id),
        }

        return review

    def _perform_rca(self, incident_id: str) -> Dict:
        """Perform root cause analysis using 5 Whys."""
        # Ask "why" 5 times to get to root cause
        pass

    def _evaluate_response(self, incident_id: str) -> Dict:
        """Evaluate incident response effectiveness."""
        # Metrics:
        # - Time to detect
        # - Time to contain
        # - Time to eradicate
        # - Time to recover
        # - Total incident duration
        pass
```

---

## Specific Incident Runbooks

### Runbook 1: Ransomware Attack

**Detection Signs**
- Files encrypted with unusual extensions
- Ransom note displayed
- High CPU/disk activity
- System slowdown

**Immediate Actions**
```bash
#!/bin/bash
# scripts/ransomware_response.sh

echo "Executing ransomware response..."

# 1. ISOLATE AFFECTED SYSTEMS
echo "Isolating affected systems..."
# Disconnect from network
# Power off if necessary

# 2. IDENTIFY ATTACK VECTOR
echo "Identifying attack vector..."
# Check email logs for phishing
# Check RDP logs
# Check VPN logs

# 3. ASSESS IMPACT
echo "Assessing impact..."
# Identify affected systems
# Identify encrypted files
# Identify data exfiltrated

# 4. CONTAINMENT
echo "Containing..."
# Isolate from network
# Disable shared drives
# Revoke credentials

# 5. ERADICATION
echo "Eradicating..."
# Rebuild clean systems
# Restore from backups
# Patch vulnerabilities

# 6. RECOVERY
echo "Recovering..."
# Restore from clean backups
# Verify data integrity
# Monitor for回流

echo "Ransomware response complete"
```

**Recovery Steps**
1. Do not pay ransom
2. Restore from clean backups
3. Verify backup integrity
4. Rebuild systems from scratch
5. Patch vulnerability used by attacker
6. Implement additional monitoring

### Runbook 2: SQL Injection Attack

**Detection Signs**
- Suspicious SQL queries in logs
- Database errors
- Unusual data retrieval
- Authentication bypass

**Immediate Actions**
```python
# mahavishnu/security/runbooks/sqli_response.py

class SQLInjectionResponse:
    """SQL injection incident response."""

    def respond(self, incident: Dict):
        """Respond to SQL injection attack."""
        # 1. Block malicious IPs
        malicious_ips = incident.get("indicators", [])
        for ip in malicious_ips:
            self._block_ip(ip)

        # 2. Review database logs
        self._review_database_logs()

        # 3. Identify compromised accounts
        compromised_accounts = self._identify_compromised_accounts()
        for account in compromised_accounts:
            self._disable_account(account)

        # 4. Assess data exposure
        exposed_data = self._assess_data_exposure()

        # 5. Patch vulnerable code
        self._patch_vulnerabilities()

        # 6. Reset all credentials
        self._reset_credentials()

    def _block_ip(self, ip: str):
        """Block malicious IP at firewall and application level."""
        pass

    def _review_database_logs(self):
        """Review database logs for unauthorized queries."""
        pass

    def _identify_compromised_accounts(self) -> List[str]:
        """Identify accounts that may have been compromised."""
        pass

    def _assess_data_exposure(self) -> Dict:
        """Assess what data was exposed."""
        pass
```

### Runbook 3: Data Breach

**Detection Signs**
- Large data transfer
- Unusual database queries
- Access to sensitive data
- Data found on dark web

**Immediate Actions**
```bash
#!/bin/bash
# scripts/data_breach_response.sh

echo "Executing data breach response..."

# 1. IDENTIFY SCOPE
echo "Identifying breach scope..."
# What data was accessed?
# How many records affected?
# Which users impacted?

# 2. CONTAIN BREACH
echo "Containing breach..."
# Block malicious IPs
# Disable compromised accounts
# Revoke credentials

# 3. ASSESS IMPACT
echo "Assessing impact..."
# Classify data sensitivity
# Determine regulatory requirements
# Assess legal liability

# 4. NOTIFICATION
echo "Preparing notifications..."
# Prepare breach notification
# Identify regulatory reporting requirements
# Prepare customer notifications

# 5. REMEDIATION
echo "Remediating..."
# Patch vulnerability
# Enhance monitoring
# Implement additional controls

echo "Data breach response complete"
```

**Notification Requirements**

| Jurisdiction | Deadline | Contact |
|--------------|----------|---------|
| GDPR (EU) | 72 hours | gdpr@company.com |
| CCPA (CA) | No specific deadline | privacy@company.com |
| HIPAA (US) | 60 days | compliance@company.com |

### Runbook 4: DDoS Attack

**Detection Signs**
- Traffic spike
- Service unavailability
- High network utilization
- Many requests from same IPs

**Immediate Actions**
```bash
#!/bin/bash
# scripts/ddos_response.sh

echo "Executing DDoS response..."

# 1. IDENTIFY ATTACK TYPE
echo "Identifying attack type..."
# Volumetric (SYN flood, UDP flood)
# Application layer (HTTP flood)
# Protocol attack

# 2. MITIGATION
echo "Mitigating attack..."
# Enable rate limiting
# Block attacking IPs
# Enable DDoS protection service
# Scale infrastructure

# 3. MONITORING
echo "Monitoring..."
# Monitor traffic patterns
# Adjust rate limits
# Whitelist legitimate traffic

echo "DDoS response complete"
```

### Runbook 5: Authentication Bypass

**Detection Signs**
- Successful authentication without credentials
- JWT algorithm confusion
- Session fixation
- Missing authentication checks

**Immediate Actions**
```python
# mahavishnu/security/runbooks/auth_bypass.py

class AuthenticationBypassResponse:
    """Authentication bypass incident response."""

    def respond(self, incident: Dict):
        """Respond to authentication bypass."""
        # 1. Emergency patch
        self._deploy_emergency_fix()

        # 2. Rotate all secrets
        self._rotate_secrets()

        # 3. Invalidate all sessions
        self._invalidate_all_sessions()

        # 4. Enable enhanced monitoring
        self._enable_enhanced_monitoring()

        # 5. Identify compromised accounts
        self._identify_compromised_accounts()

        # 6. Force password reset
        self._force_password_reset()

    def _rotate_secrets(self):
        """Rotate JWT secrets and other authentication secrets."""
        # Rotate JWT secret
        # Rotate API keys
        # Rotate database credentials
        pass

    def _invalidate_all_sessions(self):
        """Invalidate all active sessions."""
        # Clear session store
        # Force re-authentication
        pass
```

### Runbook 6: Malware Infection

**Detection Signs**
- Antivirus alerts
- Unusual process activity
- Suspicious network connections
- System modifications

**Immediate Actions**
```bash
#!/bin/bash
# scripts/malware_response.sh

echo "Executing malware response..."

# 1. ISOLATE INFECTED SYSTEMS
echo "Isolating infected systems..."
# Disconnect from network
# Quarantine system

# 2. IDENTIFY MALWARE
echo "Identifying malware..."
# Run antivirus scan
# Analyze malware sample
# Identify malware family

# 3. ERADICATION
echo "Eradicating malware..."
# Remove malware
# Rebuild system if necessary
# Scan connected systems

# 4. RECOVERY
echo "Recovering..."
# Restore from clean backups
# Verify system integrity
# Monitor for recurrence

echo "Malware response complete"
```

---

## Communication Procedures

### Internal Communication

**Severity-Based Escalation**

| Severity | Notify Within | Escalation Path |
|----------|---------------|-----------------|
| P0 - Critical | Immediate | IR Lead → Security Director → CISO → CEO |
| P1 - High | 15 minutes | IR Lead → Security Director → CISO |
| P2 - Medium | 1 hour | IR Lead → Security Director |
| P3 - Low | 4 hours | IR Lead |
| P4 - Info | Next business day | IR Lead |

**Communication Templates**

**Initial Incident Notification**
```
SUBJECT: [SECURITY] P0 - Critical Security Incident - {Incident ID}

SEVERITY: {Severity}
INCIDENT ID: {Incident ID}
DETECTED: {Timestamp}

SUMMARY:
{Brief description of incident}

AFFECTED ASSETS:
{List of affected systems and data}

CURRENT STATUS:
{Detection, Analysis, Containment, etc.}

NEXT STEPS:
{Immediate action items}

INCIDENT COMMAND:
Incident Lead: {Name} ({Contact})
Security Analyst: {Name} ({Contact})
DevOps Engineer: {Name} ({Contact})

UPDATES:
{Slack channel: #security-incident-{incident_id}}
{Status page: {URL}}
```

**Status Update (Every 2 Hours for P0/P1)**
```
SUBJECT: [SECURITY UPDATE] {Incident ID} - Status Update

INCIDENT ID: {Incident ID}
STATUS: {Detection/Analysis/Containment/Eradication/Recovery}
UPDATED: {Timestamp}

PROGRESS:
{What has been done since last update}

CHALLENGES:
{Any blockers or challenges}

NEXT MILESTONES:
{Expected timeline for next phase}

METRICS:
- Time to Detect: {X minutes}
- Time to Contain: {X minutes}
- Systems Affected: {N}
- Users Affected: {N}
```

### External Communication

**Customer Notification Template**
```
SUBJECT: Important Security Notice - {Company Name}

Dear {Customer Name},

We are writing to inform you of a security incident that may have affected your {data/service}.

WHAT HAPPENED:
{Description of incident}

WHAT INFORMATION WAS AFFECTED:
{List of affected data}

WHAT WE ARE DOING:
{Remediation steps}

WHAT YOU SHOULD DO:
{Recommended customer actions}

FOR MORE INFORMATION:
{Contact information}
{FAQ link}

We sincerely apologize for any inconvenience this may cause.

{Company Name} Security Team
```

**Public Statement Template**
```
FOR IMMEDIATE RELEASE

{Company Name} Investigating Security Incident

{City, State} - {Date} - {Company Name} is investigating a security incident involving {description}.

The company discovered the incident on {date} and immediately launched an investigation. {Company Name} is working with {law enforcement/security firm} to investigate the matter.

{Company Name} has {containment steps} and is notifying {affected parties}.

The company is committed to protecting the {data/privacy} of its {customers/users} and will provide updates as more information becomes available.

Media Contact:
{Name}
{Title}
{Email}
{Phone}

###
```

---

## Post-Incident Activities

### Root Cause Analysis (5 Whys)

```
Incident: {Description}

WHY 1: Why did the incident occur?
{Answer}

WHY 2: Why did {answer from Why 1} occur?
{Answer}

WHY 3: Why did {answer from Why 2} occur?
{Answer}

WHY 4: Why did {answer from Why 3} occur?
{Answer}

WHY 5: Why did {answer from Why 4} occur?
{Root Cause}

Corrective Actions:
1. {Action item}
2. {Action item}
3. {Action item}
```

### Metrics and KPIs

**Incident Response Metrics**

| Metric | Target | Actual | Status |
|--------|--------|--------|--------|
| Mean Time to Detect (MTTD) | <15 minutes | TBD | - |
| Mean Time to Contain (MTTC) | <1 hour | TBD | - |
| Mean Time to Recover (MTTR) | <24 hours | TBD | - |
| False Positive Rate | <10% | TBD | - |
| Incident Recurrence Rate | 0% | TBD | - |

### Continuous Improvement

**Process Improvements**
1. Update runbooks based on lessons learned
2. Enhance monitoring and detection rules
3. Improve tooling and automation
4. Conduct tabletop exercises
5. Regular training and awareness

**Technology Improvements**
1. Deploy additional security tools
2. Enhance logging and monitoring
3. Implement automated response
4. Improve threat intelligence
5. Strengthen security controls

---

## Automation & Tooling

### Incident Response Slack Bot

```python
# mahavishnu/security/ir_slack_bot.py

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

class IncidentResponseBot:
    """Slack bot for incident response communication."""

    def __init__(self, token: str):
        self.client = WebClient(token=token)

    def create_incident_channel(self, incident_id: str, severity: str) -> str:
        """Create dedicated Slack channel for incident."""
        channel_name = f"security-incident-{incident_id}"

        try:
            response = self.client.conversations_create(
                name=channel_name,
                is_private=True  # Private channel for security incidents
            )

            channel_id = response["channel"]["id"]

            # Invite incident response team
            self._invite_team(channel_id, severity)

            # Post incident details
            self._post_incident_details(channel_id, incident_id, severity)

            return channel_id

        except SlackApiError as e:
            logger.error(f"Error creating channel: {e}")
            raise

    def notify_incident(self, channel_id: str, message: str):
        """Post incident notification to channel."""
        try:
            self.client.chat_postMessage(
                channel=channel_id,
                text=message,
            )
        except SlackApiError as e:
            logger.error(f"Error posting message: {e}")

    def update_status(self, channel_id: str, status: str):
        """Update incident status in channel topic."""
        try:
            self.client.conversations_setTopic(
                channel=channel_id,
                topic=f"Status: {status}"
            )
        except SlackApiError as e:
            logger.error(f"Error setting topic: {e}")
```

### Automated Evidence Collection

```python
# mahavishnu/security/evidence_collection.py

class AutomatedEvidenceCollection:
    """Automated evidence collection for forensic analysis."""

    def collect_all_evidence(self, incident_id: str):
        """Collect all relevant evidence."""
        evidence_dir = f"evidence/{incident_id}"
        os.makedirs(evidence_dir, exist_ok=True)

        # Collect system state
        self._collect_system_state(evidence_dir)

        # Collect logs
        self._collect_logs(evidence_dir)

        # Collect network traffic
        self._collect_network_traffic(evidence_dir)

        # Collect process information
        self._collect_process_info(evidence_dir)

        # Collect memory dumps
        self._collect_memory_dumps(evidence_dir)

        # Generate chain of custody
        self._generate_chain_of_custody(evidence_dir)

    def _collect_system_state(self, evidence_dir: str):
        """Collect current system state."""
        # Running processes
        subprocess.run(
            ["ps", "aux"],
            stdout=open(f"{evidence_dir}/processes.txt", "w")
        )

        # Network connections
        subprocess.run(
            ["netstat", "-an"],
            stdout=open(f"{evidence_dir}/network_connections.txt", "w")
        )

        # Open files
        subprocess.run(
            ["lsof"],
            stdout=open(f"{evidence_dir}/open_files.txt", "w")
        )
```

---

## Appendix

### Incident Response Contacts

| Role | Name | Email | Phone | On-Call |
|------|------|-------|-------|---------|
| Incident Response Lead | TBD | on-call-ir@company.com | TBD | Yes |
| Security Director | TBD | security@company.com | TBD | Yes |
| CISO | TBD | ciso@company.com | TBD | Yes |
| Legal Counsel | TBD | legal@company.com | TBD | Yes |
| PR/Comms | TBD | comms@company.com | TBD | Yes |

### Useful Commands

```bash
# Block IP at firewall
iptables -A INPUT -s <IP> -j DROP

# Kill all processes for user
pkill -u <username>

# Disable user account
usermod -L <username>

# View recent auth failures
grep "Failed password" /var/log/auth.log | tail -100

# Capture network traffic
tcpdump -i any -w capture.pcap

# Scan for open ports
nmap -sV localhost

# View active connections
ss -tunap

# View recent system logs
journalctl -xe

# Search for suspicious processes
ps aux | grep -E "(nc|ncat|bash|sh|python)"
```

### Additional Resources

- **SANS Incident Response**: https://www.sans.org/white-papers/incident-handling/
- **NIST SP 800-61**: Computer Security Incident Handling Guide
- **OWASP Incident Response Guide**: https://owasp.org/www-community/Incident_Response
- **FIRST Forum of Incident Response**: https://www.first.org/

---

**Document Version**: 1.0.0
**Last Updated**: 2026-02-05
**Next Review**: 2026-05-05
**Maintained By**: Security Team
