# Multi-Region Deployment Quick Start Guide

This guide will help you deploy Mahavishnu across multiple regions in approximately **2 hours**.

## Prerequisites

### Required Tools

```bash
# Verify you have the required tools installed
aws --version      # AWS CLI v2
kubectl version --client
terraform version  # v1.5+
kustomize version  # v4.0+
docker --version
```

### Required Access

- AWS account with admin access
- Ability to create VPCs, subnets, and networking resources
- Ability to create IAM roles and policies
- Ability to purchase reserved instances (optional)

### Initial Setup

```bash
# Clone repository
git clone https://github.com/yourorg/mahavishnu.git
cd mahavishnu

# Install Python dependencies
pip install -e ".[dev]"

# Configure AWS CLI
aws configure

# Set default region
export AWS_DEFAULT_REGION=us-east-1
```

## Phase 1: Infrastructure Setup (30 minutes)

### Step 1: Create Terraform State Backend (5 minutes)

```bash
# Create S3 bucket for Terraform state
aws s3api create-bucket \
  --bucket mahavishnu-terraform-state \
  --region us-east-1

# Enable versioning
aws s3api put-bucket-versioning \
  --bucket mahavishnu-terraform-state \
  --versioning-configuration Status=Enabled

# Create DynamoDB table for state locking
aws dynamodb create-table \
  --table-name mahavishnu-terraform-locks \
  --attribute-definitions AttributeName=LockID,AttributeType=S \
  --key-schema AttributeName=LockID,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST
```

### Step 2: Provision Infrastructure with Terraform (20 minutes)

```bash
cd terraform/multi-region

# Initialize Terraform
terraform init

# Review execution plan
terraform plan \
  -var="environment=production" \
  -var="regions=[\"us-east-1\",\"eu-west-1\",\"ap-southeast-1\"]" \
  -out=tfplan

# Apply infrastructure
terraform apply tfplan

# Wait for infrastructure to be ready (~15-20 minutes)
echo "Waiting for infrastructure..."
sleep 1200
```

### Step 3: Verify Infrastructure (5 minutes)

```bash
# Verify VPCs created
aws ec2 describe-vpcs \
  --filters Name=tag:Project,Values=mahavishnu \
  --query 'Vpcs[].VpcId' \
  --output table

# Verify EKS clusters
aws eks list-clusters \
  --query 'clusters[?contains(@, `mahavishnu`)]' \
  --output table

# Verify databases
aws rds describe-db-instances \
  --filters Name=db-instance-id,Values=mahavishnu-* \
  --query 'DBInstances[].DBInstanceIdentifier' \
  --output table

# Verify ElastiCache
aws elasticache describe-cache-clusters \
  --query 'CacheClusters[].CacheClusterId' \
  --output table
```

## Phase 2: Kubernetes Configuration (20 minutes)

### Step 1: Configure kubectl Contexts (5 minutes)

```bash
# Get EKS cluster credentials
for region in us-east-1 eu-west-1 ap-southeast-1; do
  aws eks update-kubeconfig \
    --name mahavishnu-${region} \
    --region ${region} \
    --alias mahavishnu-${region}
done

# Verify contexts
kubectl config get-contexts | grep mahavishnu
```

### Step 2: Create Namespace and Secrets (10 minutes)

```bash
# Create namespace
kubectl create namespace mahavishnu \
  --context mahavishnu-us-east-1

kubectl create namespace mahavishnu \
  --context mahavishnu-eu-west-1

kubectl create namespace mahavishnu \
  --context mahavishnu-ap-southeast-1

# Create secrets from environment variables
for region in us-east-1 eu-west-1 ap-southeast-1; do
  kubectl create secret generic mahavishnu-secrets \
    --from-literal=DATABASE_ENDPOINT=${DB_ENDPOINT} \
    --from-literal=DATABASE_USER=${DB_USER} \
    --from-literal=DATABASE_PASSWORD=${DB_PASSWORD} \
    --from-literal=REDIS_ENDPOINT=${REDIS_ENDPOINT} \
    --from-literal=REDIS_PASSWORD=${REDIS_PASSWORD} \
    --from-literal=OPENSEARCH_ENDPOINT=${OPENSEARCH_ENDPOINT} \
    --from-literal=OPENSEARCH_PASSWORD=${OPENSEARCH_PASSWORD} \
    --namespace mahavishnu \
    --context mahavishnu-${region}
done
```

### Step 3: Verify Cluster Access (5 minutes)

```bash
# Test cluster access
kubectl get nodes \
  --context mahavishnu-us-east-1 \
  --namespace mahavishnu

kubectl get nodes \
  --context mahavishnu-eu-west-1 \
  --namespace mahavishnu

kubectl get nodes \
  --context mahavishnu-ap-southeast-1 \
  --namespace mahavishnu
```

## Phase 3: Application Deployment (30 minutes)

### Step 1: Build and Push Docker Images (10 minutes)

```bash
# Build Docker image
docker build -t mahavishnu:v1.0.0 .

# Login to ECR
for region in us-east-1 eu-west-1 ap-southeast-1; do
  aws ecr get-login-password --region ${region} | \
    docker login --username AWS --password-stdin \
    $(aws sts get-caller-identity --query Account --output text).dkr.ecr.${region}.amazonaws.com

  # Tag image
  docker tag mahavishnu:v1.0.0 \
    $(aws sts get-caller-identity --query Account --output text).dkr.ecr.${region}.amazonaws.com/mahavishnu:v1.0.0

  # Push image
  docker push \
    $(aws sts get-caller-identity --query Account --output text).dkr.ecr.${region}.amazonaws.com/mahavishnu:v1.0.0
done
```

### Step 2: Deploy with Kustomize (15 minutes)

```bash
cd k8s/multi-region

# Deploy to us-east-1
kustomize build us-east-1 | kubectl apply --context mahavishnu-us-east-1 -f -

# Wait for rollout
kubectl rollout status deployment/mahavishnu \
  --context mahavishnu-us-east-1 \
  --namespace mahavishnu

# Deploy to eu-west-1
kustomize build eu-west-1 | kubectl apply --context mahavishnu-eu-west-1 -f -

# Wait for rollout
kubectl rollout status deployment/mahavishnu \
  --context mahavishnu-eu-west-1 \
  --namespace mahavishnu

# Deploy to ap-southeast-1
kustomize build ap-southeast-1 | kubectl apply --context mahavishnu-ap-southeast-1 -f -

# Wait for rollout
kubectl rollout status deployment/mahavishnu \
  --context mahavishnu-ap-southeast-1 \
  --namespace mahavishnu
```

### Step 3: Verify Deployment (5 minutes)

```bash
# Check pod status
for region in us-east-1 eu-west-1 ap-southeast-1; do
  echo "=== Region: ${region} ==="
  kubectl get pods \
    --context mahavishnu-${region} \
    --namespace mahavishnu

  kubectl get services \
    --context mahavishnu-${region} \
    --namespace mahavishnu
done

# Check logs
kubectl logs -f \
  --context mahavishnu-us-east-1 \
  --namespace mahavishnu \
  -l app=mahavishnu \
  --tail=50
```

## Phase 4: DNS Configuration (20 minutes)

### Step 1: Create Route53 Health Checks (5 minutes)

```bash
# Create health checks for each region
for region in us-east-1 eu-west-1 ap-southeast-1; do
  # Get load balancer endpoint
  endpoint=$(kubectl get service mahavishnu \
    --context mahavishnu-${region} \
    --namespace mahavishnu \
    -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')

  # Create health check
  aws route53 create-health-check \
    --caller-reference mahavishnu-${region}-$(date +%s) \
    --health-check-config \
      IPAddress=$(dig +short ${endpoint} | head -1) \
      FullyQualifiedDomainName=${endpoint} \
      Port=8080 \
      Type=HTTPS \
      ResourcePath=/health \
      RequestInterval=30 \
      FailureThreshold=3
done
```

### Step 2: Create Route53 Records (10 minutes)

```bash
# Get hosted zone ID
HOSTED_ZONE_ID=$(aws route53 list-hosted-zones \
  --query 'HostedZones[?Name==`example.com.`].Id' \
  --output text | head -1 | cut -d'/' -f3)

# Create latency-based records
cat > route53-records.json <<EOF
{
  "Comment": "Create latency records for Mahavishnu",
  "Changes": [
    {
      "Action": "CREATE",
      "ResourceRecordSet": {
        "Name": "api.example.com",
        "Type": "CNAME",
        "SetIdentifier": "us-east-1",
        "Region": "us-east-1",
        "AliasTarget": {
          "HostedZoneId": "$(aws elb describe-load-balancers \
            --query 'LoadBalancerDescriptions[?DNSName==`$(kubectl get service mahavishnu \
              --context mahavishnu-us-east-1 \
              --namespace mahavishnu \
              -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')`].CanonicalHostedZoneNameID' \
            --output text)",
          "DNSName": "$(kubectl get service mahavishnu \
            --context mahavishnu-us-east-1 \
            --namespace mahavishnu \
            -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')",
          "EvaluateTargetHealth": true
        }
      }
    },
    {
      "Action": "CREATE",
      "ResourceRecordSet": {
        "Name": "api.example.com",
        "Type": "CNAME",
        "SetIdentifier": "eu-west-1",
        "Region": "eu-west-1",
        "AliasTarget": {
          "HostedZoneId": "$(aws elb describe-load-balancers \
            --query 'LoadBalancerDescriptions[?DNSName==`$(kubectl get service mahavishnu \
              --context mahavishnu-eu-west-1 \
              --namespace mahavishnu \
              -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')`].CanonicalHostedZoneNameID' \
            --output text)",
          "DNSName": "$(kubectl get service mahavishnu \
            --context mahavishnu-eu-west-1 \
            --namespace mahavishnu \
            -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')",
          "EvaluateTargetHealth": true
        }
      }
    },
    {
      "Action": "CREATE",
      "ResourceRecordSet": {
        "Name": "api.example.com",
        "Type": "CNAME",
        "SetIdentifier": "ap-southeast-1",
        "Region": "ap-southeast-1",
        "AliasTarget": {
          "HostedZoneId": "$(aws elb describe-load-balancers \
            --query 'LoadBalancerDescriptions[?DNSName==`$(kubectl get service mahavishnu \
              --context mahavishnu-ap-southeast-1 \
              --namespace mahavishnu \
              -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')`].CanonicalHostedZoneNameID' \
            --output text)",
          "DNSName": "$(kubectl get service mahavishnu \
            --context mahavishnu-ap-southeast-1 \
            --namespace mahavishnu \
            -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')",
          "EvaluateTargetHealth": true
        }
      }
    }
  ]
}
EOF

aws route53 change-resource-record-sets \
  --hosted-zone-id ${HOSTED_ZONE_ID} \
  --change-batch file://route53-records.json
```

### Step 3: Verify DNS Resolution (5 minutes)

```bash
# Wait for DNS propagation
echo "Waiting for DNS propagation..."
sleep 60

# Test DNS resolution
dig api.example.com

# Test from different regions
for region in us-east-1 eu-west-1 ap-southeast-1; do
  echo "=== DNS from ${region} ==="
  nslookup api.example.com \
    $(aws ec2 describe-instances \
      --region ${region} \
      --filters Name=instance-type,Values=t2.micro \
      --query 'Reservations[0].Instances[0].PublicIpAddress' \
      --output text)
done
```

## Phase 5: Monitoring and Validation (20 minutes)

### Step 1: Set Up Monitoring (10 minutes)

```bash
# Install Prometheus Operator
helm repo add prometheus-community \
  https://prometheus-community.github.io/helm-charts

helm repo update

helm install prometheus prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --create-namespace \
  --context mahavishnu-us-east-1

# Create ServiceMonitors
kubectl apply -f k8s/multi-region/monitoring/ \
  --context mahavishnu-us-east-1 \
  --namespace monitoring
```

### Step 2: Run Smoke Tests (5 minutes)

```bash
# Get API endpoint
API_ENDPOINT=$(kubectl get service mahavishnu \
  --context mahavishnu-us-east-1 \
  --namespace mahavishnu \
  -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')

# Run smoke tests
./scripts/smoke_tests.sh https://${API_ENDPOINT}

# Test all regions
for region in us-east-1 eu-west-1 ap-southeast-1; do
  endpoint=$(kubectl get service mahavishnu \
    --context mahavishnu-${region} \
    --namespace mahavishnu \
    -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')

  echo "Testing ${region}..."
  curl -f https://${endpoint}/health || echo "FAILED: ${region}"
done
```

### Step 3: Verify Multi-Region Replication (5 minutes)

```bash
# Test database replication
psql -h ${DB_ENDPOINT_US_EAST_1} -U ${DB_USER} -d mahavishnu \
  -c "SELECT * FROM users LIMIT 1"

psql -h ${DB_ENDPOINT_EU_WEST_1} -U ${DB_USER} -d mahavishnu \
  -c "SELECT * FROM users LIMIT 1"

# Test cache replication
redis-cli -h ${REDIS_ENDPOINT_US_EAST_1} -p 6379 -a ${REDIS_PASSWORD} --tls \
  SET test-key "test-value-us-east-1"

redis-cli -h ${REDIS_ENDPOINT_EU_WEST_1} -p 6379 -a ${REDIS_PASSWORD} --tls \
  GET test-key
```

## Phase 6: Cost Optimization Setup (Optional, 10 minutes)

```bash
# Purchase reserved instances for production databases
aws rds purchase-reserved-db-instances-offering \
  --reserved-db-instances-offering-id $(aws rds describe-reserved-db-instances-offerings \
    --db-instance-class db.r5.xlarge \
    --multi-az \
    --duration 1 \
    --product-description postgres \
    --offering-type PartialUpfront \
    --query 'ReservedDBInstancesOfferings[0].ReservedDBInstancesOfferingId' \
    --output text) \
  --db-instance-count 3

# Enable S3 lifecycle policies
aws s3 put-bucket-lifecycle-configuration \
  --bucket mahavishnu-us-east-1 \
  --lifecycle-configuration file://k8s/multi-region/s3-lifecycle.json

# Set up cost alarms
aws cloudwatch put-metric-alarm \
  --alarm-name monthly-cost-spike \
  --alarm-description "Alert on monthly cost spike" \
  --metric-name EstimatedCharges \
  --namespace AWS/Billing \
  --statistic Maximum \
  --period 21600 \
  --threshold 5000 \
  --comparison-operator GreaterThanThreshold
```

## Verification Checklist

### Infrastructure
- [ ] VPCs created in all regions
- [ ] EKS clusters running in all regions
- [ ] RDS databases with replication
- [ ] ElastiCache clusters with cross-region replication
- [ ] OpenSearch clusters with CCR
- [ ] S3 buckets with CRR

### Application
- [ ] Pods running in all regions
- [ ] Services accessible via load balancers
- [ ] Ingress configured with TLS
- [ ] HPA configured for auto-scaling

### DNS
- [ ] Route53 latency-based routing configured
- [ ] Health checks passing
- [ ] DNS resolution working from all regions

### Monitoring
- [ ] Prometheus deployed
- [ ] Metrics collected
- [ ] Alerts configured
- [ ] Dashboards created

### Data
- [ ] Database replication working
- [ ] Cache replication working
- [ ] Search index replication working
- [ ] S3 replication working

## Post-Deployment

### 1. Test Failover (Optional, 10 minutes)

```bash
# Simulate region failure
kubectl scale deployment/mahavishnu \
  --replicas=0 \
  --context mahavishnu-us-east-1 \
  --namespace mahavishnu

# Verify traffic routes to other regions
for i in {1..10}; do
  curl -w "%{http_code}\n" -o /dev/null -s https://api.example.com/health
done

# Restore region
kubectl scale deployment/mahavishnu \
  --replicas=3 \
  --context mahavishnu-us-east-1 \
  --namespace mahavishnu
```

### 2. Set Up Automated Deployments (5 minutes)

```bash
# Create deployment pipeline
cat > .github/workflows/deploy.yml <<EOF
name: Deploy to Multi-Region

on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Configure AWS
        uses: aws-actions/configure-aws-credentials@v2
        with:
          aws-access-key-id: \${{ secrets.AWS_ACCESS_KEY_ID }}
          aws-secret-access-key: \${{ secrets.AWS_SECRET_ACCESS_KEY }}
          aws-region: us-east-1

      - name: Deploy to regions
        run: |
          python scripts/deploy_multi_region.py deploy \
            --regions us-east-1,eu-west-1,ap-southeast-1 \
            --image-tag \${{ github.sha }}
EOF

git add .github/workflows/deploy.yml
git commit -m "Add multi-region deployment pipeline"
git push
```

### 3. Create Runbooks (5 minutes)

```bash
# Review and customize runbooks
cp docs/MULTI_REGION_RUNBOOKS.md runbooks/

# Update emergency contacts
sed -i 's/your-email@example.com/your-actual-email@example.com/' runbooks/MULTI_REGION_RUNBOOKS.md

# Test runbook procedures
./scripts/deploy_multi_region.py health --regions all
```

## Troubleshooting

### Issue: EKS Cluster Creation Fails

```bash
# Check CloudFormation stack events
aws cloudformation describe-stack-events \
  --stack-name eksctl-mahavishnu-us-east-1-cluster \
  --query 'StackEvents[::-1]'

# Common fix: Ensure IAM role has sufficient permissions
aws iam attach-role-policy \
  --role-name mahavishnu-eks-role \
  --policy-arn arn:aws:iam::aws:policy/AmazonEKSClusterPolicy
```

### Issue: Pods Not Starting

```bash
# Check pod status
kubectl describe pods \
  --context mahavishnu-us-east-1 \
  --namespace mahavishnu

# Check logs
kubectl logs \
  --context mahavishnu-us-east-1 \
  --namespace mahavishnu \
  -l app=mahavishnu \
  --previous

# Common fix: Check if secrets are created
kubectl get secrets \
  --context mahavishnu-us-east-1 \
  --namespace mahavishnu
```

### Issue: Database Replication Lag

```bash
# Check replication status
aws rds describe-db-instances \
  --db-instance-identifier mahavishnu-eu-west-1 \
  --query 'DBInstances[0].ReadReplicaSourceDBInstanceIdentifier'

# Common fix: Ensure sufficient capacity
aws rds modify-db-instance \
  --db-instance-identifier mahavishnu-eu-west-1 \
  --db-instance-class db.r5.2xlarge \
  --apply-immediately
```

### Issue: DNS Not Resolving

```bash
# Check hosted zone
aws route53 get-hosted-zone --id ${HOSTED_ZONE_ID}

# Check health checks
aws route53 list-health-checks

# Common fix: Wait for DNS propagation
sleep 300  # 5 minutes
```

## Next Steps

1. **Review Documentation**
   - Read [Multi-Region Deployment Guide](/docs/MULTI_REGION_DEPLOYMENT.md)
   - Review [Runbooks](/docs/MULTI_REGION_RUNBOOKS.md)
   - Study [Cost Optimization](/docs/MULTI_REGION_COST_OPTIMIZATION.md)

2. **Set Up CI/CD**
   - Configure GitHub Actions workflow
   - Set up automated testing
   - Enable automated deployments

3. **Configure Monitoring**
   - Set up Grafana dashboards
   - Configure PagerDuty alerts
   - Create runbooks

4. **Optimize Costs**
   - Purchase reserved instances
   - Enable spot instances
   - Configure S3 lifecycle policies

5. **Test Failover**
   - Conduct regional failover drill
   - Test disaster recovery procedures
   - Document lessons learned

## Support

- **Documentation**: [docs/](/docs/)
- **Issues**: [GitHub Issues](https://github.com/yourorg/mahavishnu/issues)
- **Slack**: #mahavishnu-ops
- **Email**: mahavishnu-support@example.com

## Time Estimate Summary

| Phase | Duration |
|-------|----------|
| Infrastructure Setup | 30 min |
| Kubernetes Configuration | 20 min |
| Application Deployment | 30 min |
| DNS Configuration | 20 min |
| Monitoring and Validation | 20 min |
| **Total** | **2 hours** |

---

**Document Version:** 1.0
**Last Updated:** 2025-02-05
**Author:** Cloud Architecture Team
