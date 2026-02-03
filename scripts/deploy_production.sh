#!/bin/bash
# Production deployment script for Mahavishnu MCP
# Usage: ./deploy_production.sh [environment]
# Example: ./deploy_production.sh production

set -e

# Configuration
ENVIRONMENT="${1:-production}"
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="$PROJECT_ROOT/backups"
LOG_DIR="$PROJECT_ROOT/logs"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}Mahavishnu MCP Deployment${NC}"
echo -e "${BLUE}Environment: $ENVIRONMENT${NC}"
echo -e "${BLUE}Timestamp: $TIMESTAMP${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

# Create directories
mkdir -p "$BACKUP_DIR"
mkdir -p "$LOG_DIR"

# Step 1: Pre-deployment checks
echo -e "${BLUE}[1/8]${NC} Running pre-deployment checks..."

# Check if required tools are installed
for cmd in gcloud docker python uv; do
  if ! command -v $cmd &> /dev/null; then
    echo -e "${RED}❌ Required tool not found: $cmd${NC}"
    exit 1
  fi
done

# Run production readiness checker
echo "Running production readiness checker..."
if ! python -m mahavishnu.core.production_readiness_standalone > "$LOG_DIR/readiness_$TIMESTAMP.log" 2>&1; then
  echo -e "${YELLOW}⚠️ Production readiness check failed. Review logs at: $LOG_DIR/readiness_$TIMESTAMP.log${NC}"
  read -p "Continue anyway? (y/N): " -n 1 -r
  echo
  if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo -e "${RED}❌ Deployment aborted${NC}"
    exit 1
  fi
else
  echo -e "${GREEN}✅ Production readiness check passed${NC}"
fi

echo ""

# Step 2: Backup current state
echo -e "${BLUE}[2/8]${NC} Creating backups..."

# Backup configuration
echo "Backing up configuration..."
tar -czf "$BACKUP_DIR/config_$TIMESTAMP.tar.gz" settings/

# Backup data (if exists)
if [ -d "$PROJECT_ROOT/data" ]; then
  echo "Backing up data..."
  tar -czf "$BACKUP_DIR/data_$TIMESTAMP.tar.gz" data/
fi

# List recent backups
echo "Recent backups:"
ls -lht "$BACKUP_DIR"/*.tar.gz 2>/dev/null | head -5 || echo "No backups found"

echo -e "${GREEN}✅ Backups created${NC}"
echo ""

# Step 3: Build Docker images
echo -e "${BLUE}[3/8]${NC} Building Docker images..."

# Build Mahavishnu image
echo "Building Mahavishnu MCP image..."
docker build -t mahavishnu:$TIMESTAMP "$PROJECT_ROOT" > "$LOG_DIR/build_$TIMESTAMP.log" 2>&1

# Tag as latest
docker tag mahavishnu:$TIMESTAMP mahavishnu:latest

echo -e "${GREEN}✅ Docker images built${NC}"
echo ""

# Step 4: Run tests
echo -e "${BLUE}[4/8]${NC} Running test suite..."

echo "Running unit tests..."
if pytest tests/unit/ -q --tb=short > "$LOG_DIR/unit_tests_$TIMESTAMP.log" 2>&1; then
  echo -e "${GREEN}✅ Unit tests passed${NC}"
else
  echo -e "${YELLOW}⚠️ Unit tests failed. Review logs at: $LOG_DIR/unit_tests_$TIMESTAMP.log${NC}"
fi

echo "Running integration tests..."
if pytest tests/integration/ -q --tb=short > "$LOG_DIR/integration_tests_$TIMESTAMP.log" 2>&1; then
  echo -e "${GREEN}✅ Integration tests passed${NC}"
else
  echo -e "${YELLOW}⚠️ Integration tests failed. Review logs at: $LOG_DIR/integration_tests_$TIMESTAMP.log${NC}"
fi

echo ""

# Step 5: Deploy to production
echo -e "${BLUE}[5/8]${NC} Deploying to production..."

# Check deployment method
if [ "$ENVIRONMENT" = "cloud-run" ]; then
  echo "Deploying to Cloud Run..."

  # Deploy to Cloud Run
  gcloud run deploy mahavishnu-mcp \
    --source "$PROJECT_ROOT" \
    --platform managed \
    --region us-central1 \
    --no-traffic \
    --tag $TIMESTAMP \
    --memory 8Gi \
    --cpu 4 \
    --max-instances 10 \
    --min-instances 1 \
    --port 8680

  # Get service URL
  SERVICE_URL=$(gcloud run services describe mahavishnu-mcp \
    --platform managed \
    --region us-central1 \
    --format 'value(status.url)')

  echo -e "${GREEN}✅ Deployed to: $SERVICE_URL${NC}"

elif [ "$ENVIRONMENT" = "docker" ]; then
  echo "Deploying with Docker..."

  # Stop old container (if exists)
  if docker ps -a | grep -q mahavishnu-old; then
    docker stop mahavishnu-old
    docker rm mahavishnu-old
  fi

  # Stop current container
  if docker ps | grep -q mahavishnu; then
    docker stop mahavishnu
    docker rename mahavishnu mahavishnu-old
  fi

  # Start new container
  docker run -d \
    --name mahavishnu \
    --restart unless-stopped \
    --env-file "$PROJECT_ROOT/.env.production" \
    -p 8680:8680 \
    --log-driver json-file \
    --log-opt max-size=10m \
    --log-opt max-file=3 \
    mahavishnu:latest

  SERVICE_URL="http://localhost:8680"
  echo -e "${GREEN}✅ Deployed to: $SERVICE_URL${NC}"

else
  echo -e "${RED}❌ Unknown deployment method: $ENVIRONMENT${NC}"
  echo "Valid options: cloud-run, docker"
  exit 1
fi

echo ""

# Step 6: Smoke tests
echo -e "${BLUE}[6/8]${NC} Running smoke tests..."

# Wait for service to be ready
echo "Waiting for service to be ready..."
sleep 10

# Run smoke tests
if "$PROJECT_ROOT/scripts/smoke_tests.sh" "$SERVICE_URL"; then
  echo -e "${GREEN}✅ Smoke tests passed${NC}"
else
  echo -e "${RED}❌ Smoke tests failed${NC}"

  # Rollback
  echo "Initiating rollback..."
  if [ "$ENVIRONMENT" = "docker" ]; then
    docker stop mahavishnu
    docker rm mahavishnu
    docker start mahavishnu-old
    docker rename mahavishnu-old mahavishnu
  elif [ "$ENVIRONMENT" = "cloud-run" ]; then
    gcloud run services update-traffic mahavishnu-mcp \
      --to-revisions=REVISION_PREVIOUS \
      --region us-central1
  fi

  echo -e "${RED}❌ Deployment rolled back${NC}"
  exit 1
fi

echo ""

# Step 7: Enable production traffic
echo -e "${BLUE}[7/8]${NC} Enabling production traffic..."

if [ "$ENVIRONMENT" = "cloud-run" ]; then
  # Route 100% traffic to new version
  gcloud run services update-traffic mahavishnu-mcp \
    --to-revisions=mahavishnu-mcp-$TIMESTAMP=100 \
    --region us-central1

  echo -e "${GREEN}✅ Production traffic enabled${NC}"
else
  echo -e "${YELLOW}⚠️ Manual traffic enablement required${NC}"
fi

echo ""

# Step 8: Post-deployment validation
echo -e "${BLUE}[8/8]${NC} Post-deployment validation..."

# Monitor for 30 seconds
echo "Monitoring service health for 30 seconds..."
for i in {1..6}; do
  sleep 5
  if curl -f "$SERVICE_URL/health" > /dev/null 2>&1; then
    echo -e "${GREEN}✅ Health check passed ($i/6)${NC}"
  else
    echo -e "${RED}❌ Health check failed ($i/6)${NC}"
  fi
done

# Final check
echo "Running final health check..."
HEALTH_RESPONSE=$(curl -s "$SERVICE_URL/health")
if echo "$HEALTH_RESPONSE" | grep -q "healthy"; then
  echo -e "${GREEN}✅ Service is healthy${NC}"
else
  echo -e "${YELLOW}⚠️ Service health check returned unexpected response${NC}"
  echo "Response: $HEALTH_RESPONSE"
fi

echo ""

# Summary
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}Deployment Summary${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo "Environment: $ENVIRONMENT"
echo "Timestamp: $TIMESTAMP"
echo "Service URL: $SERVICE_URL"
echo "Backup location: $BACKUP_DIR"
echo "Log location: $LOG_DIR"
echo ""
echo -e "${GREEN}✅ Deployment completed successfully!${NC}"
echo ""
echo "Next steps:"
echo "1. Monitor service health for 24 hours"
echo "2. Review metrics in Grafana/Prometheus"
echo "3. Check logs for any errors"
echo "4. Verify all integrations are working"
echo ""
echo "Useful commands:"
echo "  View logs: docker logs -f mahavishnu"
echo "  Check health: curl $SERVICE_URL/health"
echo "  Run smoke tests: $PROJECT_ROOT/scripts/smoke_tests.sh $SERVICE_URL"
echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
