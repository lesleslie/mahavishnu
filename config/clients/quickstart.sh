#!/bin/bash
#
# Quick start script for OTLP testing
# Launches standalone OTel stack and sends example telemetry
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}======================================${NC}"
echo -e "${BLUE}  Mahavishnu OTLP Quick Start${NC}"
echo -e "${BLUE}======================================${NC}"
echo ""

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo -e "${RED}❌ Docker is not running. Please start Docker and try again.${NC}"
    exit 1
fi

# Check if docker-compose is available
if ! command -v docker-compose &> /dev/null; then
    echo -e "${YELLOW}⚠️  docker-compose not found. Checking for docker compose plugin...${NC}"
    if ! docker compose version &> /dev/null; then
        echo -e "${RED}❌ Neither docker-compose nor docker compose plugin found.${NC}"
        exit 1
    fi
    DOCKER_COMPOSE="docker compose"
else
    DOCKER_COMPOSE="docker-compose"
fi

# Parse command line arguments
MODE="start"
STACK_UP=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --stack-only)
            MODE="stack-only"
            shift
            ;;
        --test-only)
            MODE="test-only"
            shift
            ;;
        --stop)
            MODE="stop"
            shift
            ;;
        --clean)
            MODE="clean"
            shift
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            echo "Usage: $0 [--stack-only] [--test-only] [--stop] [--clean]"
            echo ""
            echo "Options:"
            echo "  --stack-only    Only start the stack, don't send test data"
            echo "  --test-only     Only send test data (assumes stack is running)"
            echo "  --stop          Stop the stack"
            echo "  --clean         Stop the stack and remove volumes"
            exit 1
            ;;
    esac
done

# Stop mode
if [[ "$MODE" == "stop" ]]; then
    echo -e "${YELLOW}🛑 Stopping OTLP test stack...${NC}"
    $DOCKER_COMPOSE -f docker-compose.otlp.yml down
    echo -e "${GREEN}✅ Stack stopped${NC}"
    exit 0
fi

# Clean mode
if [[ "$MODE" == "clean" ]]; then
    echo -e "${YELLOW}🧹 Stopping OTLP test stack and removing volumes...${NC}"
    $DOCKER_COMPOSE -f docker-compose.otlp.yml down -v
    echo -e "${GREEN}✅ Stack stopped and volumes removed${NC}"
    exit 0
fi

# Test-only mode
if [[ "$MODE" == "test-only" ]]; then
    echo -e "${BLUE}📊 Sending test telemetry...${NC}"
    # Continue to test section below
else
    # Start mode (default) or stack-only
    echo -e "${BLUE}🚀 Starting OTLP test stack...${NC}"
    $DOCKER_COMPOSE -f docker-compose.otlp.yml up -d

    echo -e "${YELLOW}⏳ Waiting for services to be healthy...${NC}"
    sleep 10

    # Check health
    for i in {1..30}; do
        if curl -s http://localhost:13133/healthy > /dev/null 2>&1; then
            echo -e "${GREEN}✅ Collector is healthy${NC}"
            break
        fi
        if [[ $i -eq 30 ]]; then
            echo -e "${RED}❌ Collector failed to become healthy${NC}"
            echo -e "${YELLOW}Check logs with: $DOCKER_COMPOSE -f docker-compose.otlp.yml logs otel-collector${NC}"
            exit 1
        fi
        sleep 1
    done
fi

# Stack-only mode stops here
if [[ "$MODE" == "stack-only" ]]; then
    echo ""
    echo -e "${GREEN}======================================${NC}"
    echo -e "${GREEN}  Stack is ready!${NC}"
    echo -e "${GREEN}======================================${NC}"
    echo ""
    echo -e "📍 Available Services:"
    echo -e "  • Collector Health:  ${BLUE}http://localhost:13133/healthy${NC}"
    echo -e "  • Jaeger (Traces):   ${BLUE}http://localhost:16686${NC}"
    echo -e "  • Prometheus:        ${BLUE}http://localhost:9090${NC}"
    echo -e "  • Grafana:           ${BLUE}http://localhost:3000${NC} (admin/admin)"
    echo ""
    echo -e "🚀 Send test data with:"
    echo -e "  ${YELLOW}python python-otlp-client.py${NC}"
    echo -e "  ${YELLOW}python python-otlp-client.py --source claude --ai-workflow${NC}"
    echo -e "  ${YELLOW}python python-otlp-client.py --source qwen --ai-workflow${NC}"
    echo ""
    exit 0
fi

# Test section (runs for test-only or start modes)
echo ""
echo -e "${BLUE}======================================${NC}"
echo -e "${BLUE}  Sending Test Telemetry${NC}"
echo -e "${BLUE}======================================${NC}"
echo ""

# Check if Python is available
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}❌ Python 3 is not installed${NC}"
    exit 1
fi

# Check if opentelemetry packages are installed
if ! python3 -c "import opentelemetry" 2>/dev/null; then
    echo -e "${YELLOW}⚠️  OpenTelemetry packages not found${NC}"
    echo -e "${YELLOW}Installing...${NC}"
    pip3 install -q opentelemetry-api opentelemetry-sdk opentelemetry-exporter-otlp-proto-grpc
    echo -e "${GREEN}✅ Installed OpenTelemetry packages${NC}"
fi

# Test 1: Primary collector
echo -e "${BLUE}📤 Test 1: Sending telemetry to primary collector...${NC}"
python3 python-otlp-client.py \
    --endpoint http://localhost:4317 \
    --service test-app \
    --count 5

echo ""
sleep 2

# Test 2: Claude-specific
echo -e "${BLUE}📤 Test 2: Sending Claude-specific telemetry...${NC}"
python3 python-otlp-client.py \
    --endpoint http://localhost:4319 \
    --service claude-integration \
    --source claude \
    --ai-workflow

echo ""
sleep 2

# Test 3: Qwen-specific
echo -e "${BLUE}📤 Test 3: Sending Qwen-specific telemetry...${NC}"
python3 python-otlp-client.py \
    --endpoint http://localhost:4321 \
    --service qwen-integration \
    --source qwen \
    --ai-workflow

echo ""
echo -e "${GREEN}======================================${NC}"
echo -e "${GREEN}  Tests Complete!${NC}"
echo -e "${GREEN}======================================${NC}"
echo ""
echo -e "📍 View Your Telemetry:"
echo -e "  • Jaeger (Traces):   ${BLUE}http://localhost:16686${NC}"
echo -e "  • Prometheus:        ${BLUE}http://localhost:9090${NC}"
echo -e "  • Grafana:           ${BLUE}http://localhost:3000${NC} (admin/admin)"
echo ""
echo -e "🔍 In Jaeger:"
echo -e "  1. Click ${YELLOW}Search${NC}"
echo -e "  2. Select service: ${YELLOW}test-app${NC}, ${YELLOW}claude-integration${NC}, or ${YELLOW}qwen-integration${NC}"
echo -e "  3. Click ${YELLOW}Find Traces${NC}"
echo -e "  4. Click on a trace to see details"
echo ""
echo -e "🔍 In Prometheus:"
echo -e "  1. Query: ${YELLOW}operations_total${NC}"
echo -e "  2. Click ${YELLOW}Execute${NC}"
echo ""
echo -e "🔍 In Grafana:"
echo -e "  1. Click ${YELLOW}Explore${NC}"
echo -e "  2. Select ${YELLOW}Prometheus${NC} datasource"
echo -e "  3. Query: ${YELLOW}operations_total${NC}"
echo -e "  4. Click ${YELLOW}Run query${NC}"
echo ""
echo -e "🛑 Stop the stack when done:"
echo -e "  ${YELLOW}$0 --stop${NC}"
echo ""
echo -e "🧹 Remove everything when done:"
echo -e "  ${YELLOW}$0 --clean${NC}"
echo ""
