# Multi-Region Runbooks

This document contains operational runbooks for managing Mahavishnu's multi-region deployment.

## Table of Contents

1. [Regional Failover](#1-regional-failover)
2. [Database Replication Lag](#2-database-replication-lag)
3. [Cache Invalidation](#3-cache-invalidation)
4. [DNS Failover](#4-dns-failover)
5. [Regional Deployment](#5-regional-deployment)
6. [Data Sovereignty Incident](#6-data-sovereignty-incident)
7. [Cost Optimization](#7-cost-optimization)
8. [Performance Degradation](#8-performance-degradation)

---

## 1. Regional Failover

### Severity: Critical

### Trigger
- Region health score < 0.5
- Complete AWS region outage
- Network connectivity loss to region
- Database cluster failure in region

### Runbook

#### Step 1: Verify Outage (2 minutes)

```bash
# Check region health
./scripts/deploy_multi_region.py health --regions us-east-1

# Check AWS health dashboard
https://health.aws.amazon.com/health/status

# Check database connectivity
psql -h $DB_ENDPOINT -U $DB_USER -d mahavishnu -c "SELECT 1"

# Check API health
curl -f https://us-east-1.api.example.com/health
```

#### Step 2: Declare Incident (1 minute)

```bash
# Alert on-call team
pagerduty-trigger --service mahavishnu --severity critical \
  --message "Region us-east-1 failure detected"

# Post to Slack
slack-post --channel #incidents \
  --message "🚨 Regional failover initiated for us-east-1"

# Update status page
statuspage-update --component mahavishnu-us-east-1 --status major_outage
```

#### Step 3: Execute Automatic Failover (5 minutes)

**If automatic failover is enabled:**

```bash
# The failover engine will automatically:
# 1. Stop routing traffic to failed region
# 2. Promote healthy region to primary
# 3. Update DNS to route to healthy region
# 4. Verify failover success

# Monitor failover progress
./scripts/deploy_multi_region.py status --regions all
```

**Manual failover (if automatic fails):**

```bash
# 1. Disable failed region in load balancer
aws elbv2 modify-listener \
  --listener-arn $LISTENER_ARN \
  --default-actions Type=fixed-response,FixedResponseBody='{"status":"maintenance"}',StatusCode=503

# 2. Promote healthy region database
aws rds promote-read-replica \
  --db-instance-identifier mahavishnu-eu-west-1-replica

# 3. Update Route53 health check
aws route53 update-health-check \
  --health-check-id $HEALTH_CHECK_ID \
  --disabled

# 4. Update DNS to point to healthy region
aws route53 change-resource-record-sets \
  --hosted-zone-id $HOSTED_ZONE_ID \
  --change-batch file://failover-change.json
```

#### Step 4: Verify Failover (5 minutes)

```bash
# Check health of new primary region
curl -f https://eu-west-1.api.example.com/health

# Run smoke tests
./scripts/smoke_tests.sh https://eu-west-1.api.example.com

# Verify data replication lag
aws rds describe-db-instances \
  --db-instance-identifier mahavishnu-eu-west-1 \
  --query 'DBInstances[0].ReadReplicaSourceDBInstanceIdentifier'

# Check application metrics
kubectl --context mahavishnu-eu-west-1 top pods
```

#### Step 5: Monitor for Stability (30 minutes)

```bash
# Monitor error rates
./scripts/monitor_metrics.sh --metric error_rate --region eu-west-1

# Monitor latency
./scripts/monitor_metrics.sh --metric latency_p95 --region eu-west-1

# Monitor throughput
./scripts/monitor_metrics.sh --metric request_rate --region eu-west-1

# Monitor database connections
aws rds describe-db-log-files \
  --db-instance-identifier mahavishnu-eu-west-1
```

#### Step 6: Restore Failed Region (After outage resolved)

```bash
# 1. Rebuild infrastructure in failed region
./scripts/deploy_multi_region.py deploy --regions us-east-1

# 2. Sync data from healthy region
aws rds create-db-instance-read-replica \
  --db-instance-identifier mahavishnu-us-east-1-replica \
  --source-db-instance-identifier mahavishnu-eu-west-1

# 3. Wait for replication lag < 1 second
aws rds describe-db-instances \
  --db-instance-identifier mahavishnu-us-east-1-replica \
  --query 'DBInstances[0].ReadReplicaSourceDBInstanceIdentifier'

# 4. Execute failback (if needed)
./scripts/deploy_multi_region.py deploy --regions us-east-1,eu-west-1

# 5. Update DNS to restore traffic distribution
aws route53 change-resource-record-sets \
  --hosted-zone-id $HOSTED_ZONE_ID \
  --change-batch file://restore-change.json
```

#### Step 7: Post-Mortem

```bash
# Create incident report
./scripts/create_incident_report.sh \
  --incident-id INC-1234 \
  --region us-east-1 \
  --duration 45m

# Schedule post-mortem meeting
# Participants: SRE, DevOps, Engineering Manager
# Agenda: Root cause, timeline, action items

# Document action items
# - Improve failover automation
# - Reduce failover time from 5m to 3m
# - Add more health checks
# - Improve monitoring and alerting
```

---

## 2. Database Replication Lag

### Severity: Warning

### Trigger
- Replication lag > 1 second
- Database CPU > 80%
- Database connections > 90% of max

### Runbook

#### Step 1: Diagnose (2 minutes)

```bash
# Check replication lag
aws rds describe-db-instances \
  --db-instance-identifier mahavishnu-us-east-1 \
  --query 'DBInstances[0].ReadReplicaSourceDBInstanceIdentifier'

# Check CloudWatch metrics
aws cloudwatch get-metric-statistics \
  --namespace AWS/RDS \
  --metric-name ReadLag \
  --dimensions Name=DBInstanceIdentifier,Value=mahavishnu-us-east-1 \
  --start-time $(date -u -d '5 minutes ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 60 --statistics Average

# Check database performance
aws rds describe-db-log-files \
  --db-instance-identifier mahavishnu-us-east-1 \
  --output text
```

#### Step 2: Throttle Write Traffic (If needed)

```bash
# Reduce max concurrent workflows
kubectl set env deployment/mahavishnu \
  MAX_CONCURRENT_WORKFLOWS=5 \
  --namespace mahavishnu \
  --context mahavishnu-us-east-1

# Enable connection pooling
kubectl set env deployment/mahavishnu \
  DB_POOL_SIZE=10 \
  DB_MAX_OVERFLOW=20 \
  --namespace mahavishnu \
  --context mahavishnu-us-east-1
```

#### Step 3: Scale Database (If needed)

```bash
# Modify instance class
aws rds modify-db-instance \
  --db-instance-identifier mahavishnu-us-east-1 \
  --db-instance-class db.r5.2xlarge \
  --apply-immediately

# Add read replicas
aws rds create-db-instance-read-replica \
  --db-instance-identifier mahavishnu-us-east-1-replica-2 \
  --source-db-instance-identifier mahavishnu-us-east-1 \
  --db-instance-class db.r5.xlarge

# Increase storage
aws rds modify-db-instance \
  --db-instance-identifier mahavishnu-us-east-1 \
  --allocated-storage 500 \
  --apply-immediately
```

#### Step 4: Monitor Recovery (15 minutes)

```bash
# Monitor replication lag
watch -n 5 'aws rds describe-db-instances \
  --db-instance-identifier mahavishnu-us-east-1 \
  --query "DBInstances[0].ReadReplicaSourceDBInstanceIdentifier"'

# Monitor CPU utilization
aws cloudwatch get-metric-statistics \
  --namespace AWS/RDS \
  --metric-name CPUUtilization \
  --dimensions Name=DBInstanceIdentifier,Value=mahavishnu-us-east-1 \
  --start-time $(date -u -d '15 minutes ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 60 --statistics Average

# Check connection count
aws rds describe-db-instances \
  --db-instance-identifier mahavishnu-us-east-1 \
  --query 'DBInstances[0].DBInstanceConnections'
```

#### Step 5: Restore Normal Operations

```bash
# Restore normal workflow concurrency
kubectl set env deployment/mahavishnu \
  MAX_CONCURRENT_WORKFLOWS=10 \
  --namespace mahavishnu \
  --context mahavishnu-us-east-1
```

---

## 3. Cache Invalidation

### Severity: Warning

### Trigger
- Stale data detected in cache
- Cache consistency issues
- Users seeing outdated data

### Runbook

#### Step 1: Identify Affected Cache Keys

```bash
# Connect to Redis
redis-cli -h $REDIS_ENDPOINT -p 6379 -a $REDIS_PASSWORD --tls

# Find keys matching pattern
KEYS "user:*"

# Check TTL for keys
TTL user:12345

# Monitor cache operations
MONITOR
```

#### Step 2: Invalidate Stale Cache

```bash
# Delete specific keys
redis-cli -h $REDIS_ENDPOINT -p 6379 -a $REDIS_PASSWORD --tls \
  DEL user:12345 session:67890

# Delete all keys matching pattern
redis-cli -h $REDIS_ENDPOINT -p 6379 -a $REDIS_PASSWORD --tls \
  --scan --pattern "user:*" | xargs redis-cli -h $REDIS_ENDPOINT -p 6379 -a $REDIS_PASSWORD --tls DEL

# Flush entire cache (extreme case)
redis-cli -h $REDIS_ENDPOINT -p 6379 -a $REDIS_PASSWORD --tls FLUSHDB
```

#### Step 3: Invalidate Cross-Region Cache

```bash
# Publish invalidation event to all regions
redis-cli -h $REDIS_ENDPOINT -p 6379 -a $REDIS_PASSWORD --tls \
  PUBLISH cache_invalidation '{"key":"user:12345","region":"us-east-1"}'

# Verify invalidation propagated
redis-cli -h $REDIS_EU_ENDPOINT -p 6379 -a $REDIS_PASSWORD --tls \
  GET user:12345

# Should return (nil)
```

#### Step 4: Prevent Future Stale Data

```bash
# Reduce TTL for volatile data
kubectl set env deployment/mahavishnu \
  CACHE_DEFAULT_TTL=300 \
  --namespace mahavishnu \
  --context mahavishnu-us-east-1

# Enable cache write-through
kubectl set env deployment/mahavishnu \
  CACHE_WRITE_THROUGH=true \
  --namespace mahavishnu \
  --context mahavishnu-us-east-1

# Enable cache invalidation on write
kubectl set env deployment/mahavishnu \
  CACHE_INVALIDATE_ON_WRITE=true \
  --namespace mahavishnu \
  --context mahavishnu-us-east-1
```

---

## 4. DNS Failover

### Severity: Critical

### Trigger
- DNS queries failing
- Route53 health checks failing
- Users unable to resolve API endpoints

### Runbook

#### Step 1: Verify DNS Health

```bash
# Check DNS resolution
dig api.example.com

# Check Route53 health checks
aws route53 list-health-checks

# Check specific health check
aws route53 get-health-check-status \
  --health-check-id $HEALTH_CHECK_ID

# Check DNS query logs
aws route53 get-query-logging-config \
  --hosted-zone-id $HOSTED_ZONE_ID
```

#### Step 2: Update Health Check Thresholds (If false positives)

```bash
# Update health check parameters
aws route53 update-health-check \
  --health-check-id $HEALTH_CHECK_ID \
  --failure-threshold 3 \
  --request-interval 30

# Add regions to health check
aws route53 update-health-check \
  --health-check-id $HEALTH_CHECK_ID \
  --regions us-east-1,eu-west-1,ap-southeast-1
```

#### Step 3: Manual DNS Failover (If needed)

```bash
# Create failover change
cat > failover.json <<EOF
{
  "Changes": [{
    "Action": "UPSERT",
    "ResourceRecordSet": {
      "Name": "api.example.com",
      "Type": "CNAME",
      "SetIdentifier": "eu-west-1-failover",
      "Region": "eu-west-1",
      "AliasTarget": {
        "HostedZoneId": "$ZONE_ID",
        "DNSName": "alb-eu-west-1.aws.example.com",
        "EvaluateTargetHealth": true
      }
    }
  }]
}
EOF

# Apply change
aws route53 change-resource-record-sets \
  --hosted-zone-id $HOSTED_ZONE_ID \
  --change-batch file://failover.json
```

#### Step 4: Verify DNS Propagation

```bash
# Check DNS from multiple locations
for region in us-east-1 eu-west-1 ap-southeast-1; do
  echo "Checking from $region:"
  dig @ns-$region.awsdns.com api.example.com
done

# Check TTL
dig +noall +answer api.example.com | grep -i ttl

# Verify service endpoint
curl -v https://api.example.com/health
```

---

## 5. Regional Deployment

### Severity: Normal

### Trigger
- New feature release
- Bug fix deployment
- Infrastructure update

### Runbook

#### Step 1: Pre-Deployment Checklist

```bash
# [ ] All tests passing
pytest tests/ -v

# [ ] Code review approved
gh pr view $PR_NUMBER --json reviews

# [ ] Production readiness check passed
python -m mahavishnu.core.production_readiness_standalone

# [ ] Backup created
./scripts/deploy_production.sh backup

# [ ] Rollback plan documented
```

#### Step 2: Build and Push Image

```bash
# Build Docker image
docker build -t mahavishnu:$VERSION .

# Tag for regions
for region in us-east-1 eu-west-1 ap-southeast-1; do
  docker tag mahavishnu:$VERSION \
    $ECR_REGISTRY/mahavishnu:$VERSION-$region
done

# Push to ECR
for region in us-east-1 eu-west-1 ap-southeast-1; do
  aws ecr get-login-password --region $region | \
    docker login --username AWS --password-stdin \
    $ECR_REGISTRY.$region.amazonaws.com
  docker push $ECR_REGISTRY/mahavishnu:$VERSION-$region
done
```

#### Step 3: Deploy to Staging

```bash
# Deploy to staging environment
./scripts/deploy_multi_region.py deploy \
  --regions us-east-1 \
  --image-tag $VERSION \
  --environment staging

# Run smoke tests
./scripts/smoke_tests.sh https://staging.api.example.com

# Run integration tests
pytest tests/integration/ --base-url https://staging.api.example.com
```

#### Step 4: Deploy to Production (Blue-Green)

```bash
# Deploy to us-east-1 first (10% traffic)
./scripts/deploy_multi_region.py deploy \
  --regions us-east-1 \
  --image-tag $VERSION

# Monitor for 10 minutes
./scripts/monitor_deployment.sh --region us-east-1 --duration 600

# Deploy to eu-west-1 (25% traffic)
./scripts/deploy_multi_region.py deploy \
  --regions eu-west-1 \
  --image-tag $VERSION

# Monitor for 10 minutes
./scripts/monitor_deployment.sh --region eu-west-1 --duration 600

# Deploy to ap-southeast-1 (remaining traffic)
./scripts/deploy_multi_region.py deploy \
  --regions ap-southeast-1 \
  --image-tag $VERSION

# Monitor for 10 minutes
./scripts/monitor_deployment.sh --region ap-southeast-1 --duration 600
```

#### Step 5: Verify Deployment

```bash
# Check all regions
./scripts/deploy_multi_region.py health --regions all

# Check metrics
./scripts/check_metrics.sh --threshold error_rate:0.01

# Check logs
./scripts/check_logs.sh --region us-east-1 --level ERROR

# Run smoke tests
./scripts/smoke_tests.sh https://api.example.com
```

#### Step 6: Rollback (If needed)

```bash
# Rollback failed region
./scripts/deploy_multi_region.py rollback \
  --region us-east-1

# Verify rollback
./scripts/deploy_multi_region.py health --regions us-east-1
```

---

## 6. Data Sovereignty Incident

### Severity: Critical

### Trigger
- GDPR data stored outside EU
- Data localization violation
- Cross-border transfer without consent

### Runbook

#### Step 1: Identify Violation (5 minutes)

```bash
# Query audit log for EU data access
python -m mahavishnu.core.compliance.audit_logger \
  --query "data_residency:eu AND region NOT IN (eu-west-1, europe-west1, westeurope)"

# Check database for EU data in non-EU regions
psql -h $US_DB_ENDPOINT -U $DB_USER -d mahavishnu \
  -c "SELECT COUNT(*) FROM users WHERE data_region = 'eu'"

# Check S3 for EU data in non-EU buckets
aws s3 ls s3://mahavishnu-us-east-1/ --recursive | grep eu-data
```

#### Step 2: Immediate Containment (10 minutes)

```bash
# Stop all writes to non-EU regions for EU data
kubectl set env deployment/mahavishnu \
  GDPR_ENFORCEMENT=true \
  EU_DATA_REGION=eu-west-1 \
  BLOCK_EU_DATA_EXPORT=true \
  --namespace mahavishnu \
  --context mahavishnu-us-east-1

# Enable database RLS for EU data
psql -h $US_DB_ENDPOINT -U $DB_USER -d mahavishnu \
  -c "ALTER TABLE users ENABLE ROW LEVEL SECURITY"

# Drop EU data from non-EU regions (after backup)
pg_dump -h $US_DB_ENDPOINT -U $DB_USER -d mahavishnu \
  --table=users > /backups/users_backup.sql

psql -h $US_DB_ENDPOINT -U $DB_USER -d mahavishnu \
  -c "DELETE FROM users WHERE data_region = 'eu'"
```

#### Step 3: Migration to EU Region (1 hour)

```bash
# Export EU data from non-EU region
pg_dump -h $US_DB_ENDPOINT -U $DB_USER -d mahavishnu \
  -t users --where="data_region='eu'" > eu_data.sql

# Import to EU region
psql -h $EU_DB_ENDPOINT -U $DB_USER -d mahavishnu < eu_data.sql

# Verify migration
psql -h $EU_DB_ENDPOINT -U $DB_USER -d mahavishnu \
  -c "SELECT COUNT(*) FROM users WHERE data_region = 'eu'"

# Delete EU data from non-EU region
psql -h $US_DB_ENDPOINT -U $DB_USER -d mahavishnu \
  -c "DELETE FROM users WHERE data_region = 'eu'"
```

#### Step 4: Compliance Review (1 day)

```bash
# Generate compliance report
python -m mahavishnu.core.compliance.gdpr_router \
  --report > /reports/gdpr_compliance_$(date +%Y%m%d).pdf

# Update DPO (Data Protection Officer)
email-send --to dpo@example.com \
  --subject "GDPR Data Sovereignty Incident Report" \
  --body /reports/gdpr_compliance_$(date +%Y%m%d).pdf

# Document incident and remediation
./scripts/create_incident_report.sh \
  --type gdpr_violation \
  --severity critical \
  --region us-east-1
```

#### Step 5: Prevent Future Violations

```bash
# Enable automatic data residency enforcement
kubectl set env deployment/mahavishnu \
  DATA_RESIDENCY_ENFORCEMENT=true \
  --namespace mahavishnu \
  --all-contexts

# Add compliance monitoring
kubectl apply -f k8s/compliance-monitor.yaml

# Set up alerts for GDPR violations
aws cloudwatch put-metric-alarm \
  --alarm-name gdpr-data-residency-violation \
  --alarm-description "Alert on GDPR data residency violations" \
  --metric-name GDPRViolations \
  --namespace Mahavishnu/Compliance \
  --statistic Sum \
  --period 300 \
  --threshold 1 \
  --comparison-operator GreaterThanThreshold \
  --evaluation-periods 1
```

---

## 7. Cost Optimization

### Severity: Low

### Trigger
- Monthly cost spike > 20%
- Budget alert triggered
- Underutilized resources detected

### Runbook

#### Step 1: Identify Cost Drivers

```bash
# Get cost breakdown
aws ce get-cost-and-usage \
  --time-period Start=$(date -d '30 days ago' +%Y-%m-%d),End=$(date +%Y-%m-%d) \
  --granularity MONTHLY \
  --metrics BlendedCost \
  --group-by Type=DIMENSION,Key=SERVICE

# Check reserved instance coverage
aws ce get-reservation-coverage \
  --time-period Start=$(date -d '30 days ago' +%Y-%m-%d),End=$(date +%Y-%m-%d) \
  --granularity MONTHLY

# Check EC2 right-sizing recommendations
aws compute-optimizer get-ec2-instance-recommendations \
  --account-ids $(aws sts get-caller-identity --query Account --output text)
```

#### Step 2: Implement Cost Reduction Measures

```bash
# Purchase reserved instances
aws rds purchase-reserved-db-instances-offering \
  --reserved-db-instances-offering-id $OFFERING_ID \
  --db-instance-count 3

# Enable spot instances for workers
kubectl set env deployment/mahavishnu-workers \
  SPOT_INSTANCE_ENABLED=true \
  SPOT_INSTANCE_MAX_PRICE=0.5 \
  --namespace mahavishnu

# Resize underutilized instances
aws rds modify-db-instance \
  --db-instance-identifier mahavishnu-us-east-1 \
  --db-instance-class db.r5.xlarge \
  --apply-immediately

# Enable lifecycle policies for S3
aws s3 put-bucket-lifecycle-configuration \
  --bucket mahavishnu-us-east-1 \
  --lifecycle-configuration file://lifecycle.json
```

#### Step 3: Monitor Cost Impact

```bash
# Set up cost alarms
aws cloudwatch put-metric-alarm \
  --alarm-name monthly-cost-spike \
  --alarm-description "Alert on monthly cost spike" \
  --metric-name EstimatedCharges \
  --namespace AWS/Billing \
  --statistic Maximum \
  --period 21600 \
  --threshold 1000 \
  --comparison-operator GreaterThanThreshold

# Create budget
aws budgets create-budget \
  --account-id $(aws sts get-caller-identity --query Account --output text) \
  --budget file://budget.json
```

---

## 8. Performance Degradation

### Severity: Warning

### Trigger
- P95 latency > 500ms
- Error rate > 1%
- Throughput drop > 20%

### Runbook

#### Step 1: Identify Bottleneck (5 minutes)

```bash
# Check application metrics
kubectl top pods --namespace mahavishnu --context mahavishnu-us-east-1

# Check database performance
aws rds describe-db-log-files \
  --db-instance-identifier mahavishnu-us-east-1 \
  --output text | tail -1 | \
  xargs -I {} aws rds download-db-log-file-portion \
  --db-instance-identifier mahavishnu-us-east-1 \
  --log-file-name {} --output text

# Check cache hit rate
redis-cli -h $REDIS_ENDPOINT -p 6379 -a $REDIS_PASSWORD --tls \
  INFO stats | grep keyspace_hits

# Check network latency
ping -c 10 $API_ENDPOINT
```

#### Step 2: Scale Resources (If needed)

```bash
# Scale up pods
kubectl scale deployment/mahavishnu \
  --replicas=10 \
  --namespace mahavishnu \
  --context mahavishnu-us-east-1

# Enable HPA
kubectl autoscale deployment/mahavishnu \
  --min=3 --max=20 \
  --cpu-percent=70 \
  --namespace mahavishnu \
  --context mahavishnu-us-east-1

# Scale database
aws rds modify-db-instance \
  --db-instance-identifier mahavishnu-us-east-1 \
  --db-instance-class db.r5.2xlarge \
  --apply-immediately

# Scale cache cluster
aws elasticache modify-replication-group \
  --replication-group-id mahavishnu-us-east-1 \
  --cache-node-type cache.r5.2xlarge \
  --apply-immediately
```

#### Step 3: Optimize Application (If needed)

```bash
# Tune connection pools
kubectl set env deployment/mahavishnu \
  DB_POOL_SIZE=20 \
  REDIS_POOL_SIZE=50 \
  --namespace mahavishnu \
  --context mahavishnu-us-east-1

# Enable caching
kubectl set env deployment/mahavishnu \
  CACHE_ENABLED=true \
  CACHE_DEFAULT_TTL=300 \
  --namespace mahavishnu \
  --context mahavishnu-us-east-1

# Enable compression
kubectl set env deployment/mahavishnu \
  API_COMPRESSION=true \
  --namespace mahavishnu \
  --context mahavishnu-us-east-1
```

#### Step 4: Monitor Recovery (15 minutes)

```bash
# Monitor latency
watch -n 5 './scripts/check_metrics.sh --metric latency_p95 --threshold 500'

# Monitor error rate
watch -n 5 './scripts/check_metrics.sh --metric error_rate --threshold 0.01'

# Monitor throughput
watch -n 5 './scripts/check_metrics.sh --metric throughput --threshold 1000'
```

---

## Emergency Contacts

| Role | Name | Email | Phone |
|------|------|-------|-------|
| On-Call SRE | - | oncall@example.com | +1-555-0001 |
| Engineering Manager | - | eng-mgr@example.com | +1-555-0002 |
| VP Engineering | - | vp-eng@example.com | +1-555-0003 |
| DPO (GDPR) | - | dpo@example.com | +1-555-0004 |

## Additional Resources

- [Architecture Documentation](/docs/MULTI_REGION_DEPLOYMENT.md)
- [Kubernetes Manifests](/k8s/multi-region/)
- [Terraform Modules](/terraform/multi-region/)
- [Monitoring Dashboards](https://grafana.example.com/d/mahavishnu)
- [Run Repository](https://gitlab.example.com/mahavishnu/runbooks)
