#!/usr/bin/env bash
# Build script for Mahavishnu using buildpacks
# Usage: ./scripts/build.sh [registry]

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
IMAGE_NAME="${REGISTRY:-mahavishnu}"
VERSION="${VERSION:-latest}"
BUILDER="${BUILDER:-heroku/builder:24}"

echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}  Mahavishnu Build Script with Buildpacks${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

# Check if pack is installed
if ! command -v pack &> /dev/null; then
    echo -e "${RED}✗ Error: pack CLI not installed${NC}"
    echo -e "${YELLOW}Install it from: https://buildpacks.io/docs/install-pack/${NC}"
    exit 1
fi

echo -e "${GREEN}✓ pack CLI found${NC}"

# Change to project root
cd "$PROJECT_ROOT"

# Build with pack
echo -e "${BLUE}🏗️  Building ${IMAGE_NAME}:${VERSION}...${NC}"
echo ""

pack build "${IMAGE_NAME}:${VERSION}" \
  --builder "${BUILDER}" \
  --buildpack heroku/python \
  --buildpack heroku/procfile-explorer \
  --env BP_PYTHON_VERSION="3.13" \
  --env BP_OTEL_VERSION="latest" \
  --env OTEL_SERVICE_NAME="mahavishnu" \
  --env OTEL_EXPORTER_OTLP_ENDPOINT="http://otel-collector:4317" \
  --env BP_LAUNCH_DEBUG="true" \
  --trust-builder \
  --publish

echo ""
echo -e "${GREEN}✓ Build complete: ${IMAGE_NAME}:${VERSION}${NC}"

# Show image size
echo -e "${BLUE}📏 Image size:${NC}"
docker images "${IMAGE_NAME}:${VERSION}" --format "table {{.Repository}}\t{{.Tag}}\t{{.Size}}"

echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}✓ Success! Image ready for deployment${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "${YELLOW}Next steps:${NC}"
echo -e "  1. Run locally: ${GREEN}docker compose -f docker-compose.buildpacks.yml up -d${NC}"
echo -e "  2. View logs:   ${GREEN}docker compose -f docker-compose.buildpacks.yml logs -f${NC}"
echo -e "  3. Open Jaeger: ${GREEN}http://localhost:16686${NC}"
echo -e "  4. Open Grafana:${GREEN}http://localhost:3000${NC}"
echo ""
