#!/bin/bash
# OTLP System Diagnostics Script
# Quick health check for all OTLP components

echo "======================================"
echo "  OTLP System Diagnostics"
echo "======================================"
echo ""

FAIL=0

# Check Docker
echo -n "1. Docker: "
if docker info > /dev/null 2>&1; then
    echo -e "\033[0;32m✅ Running\033[0m"
else
    echo -e "\033[0;31m❌ Not running\033[0m"
    FAIL=1
fi

# Check collector health
echo -n "2. Collector Health: "
if curl -s http://localhost:13133/healthy > /dev/null 2>&1; then
    echo -e "\033[0;32m✅ Healthy\033[0m"
else
    echo -e "\033[0;31m❌ Unhealthy\033[0m"
    FAIL=1
fi

# Check Jaeger
echo -n "3. Jaeger UI: "
if curl -s http://localhost:16686 > /dev/null 2>&1; then
    echo -e "\033[0;32m✅ Available\033[0m"
else
    echo -e "\033[0;31m❌ Not available\033[0m"
    FAIL=1
fi

# Check Prometheus
echo -n "4. Prometheus: "
if curl -s http://localhost:9090/-/healthy > /dev/null 2>&1; then
    echo -e "\033[0;32m✅ Healthy\033[0m"
else
    echo -e "\033[0;31m❌ Unhealthy\033[0m"
    FAIL=1
fi

# Check Grafana
echo -n "5. Grafana: "
if curl -s http://localhost:3000 > /dev/null 2>&1; then
    echo -e "\033[0;32m✅ Available\033[0m"
else
    echo -e "\033[0;31m❌ Not available\033[0m"
    FAIL=1
fi

# Check Elasticsearch
echo -n "6. Elasticsearch: "
if curl -s http://localhost:9200/_cluster/health > /dev/null 2>&1; then
    echo -e "\033[0;32m✅ Available\033[0m"
else
    echo -e "\033[0;31m❌ Not available\033[0m"
    FAIL=1
fi

# Check ports
echo ""
echo "7. OTLP Ports:"
for port in 4317 4318 4319 4320 4321 4322; do
    echo -n "   Port $port: "
    if nc -z localhost $port 2>/dev/null; then
        echo -e "\033[0;32m✅ Listening\033[0m"
    else
        echo -e "\033[0;31m❌ Not listening\033[0m"
        FAIL=1
    fi
done

echo ""
echo "======================================"
if [ $FAIL -eq 0 ]; then
    echo -e "\033[0;32m✅ All systems operational\033[0m"
    echo "======================================"
    echo ""
    echo "View telemetry:"
    echo "  • Jaeger:    http://localhost:16686"
    echo "  • Prometheus: http://localhost:9090"
    echo "  • Grafana:   http://localhost:3000"
    exit 0
else
    echo -e "\033[0;31m❌ Some systems failed\033[0m"
    echo "======================================"
    echo ""
    echo "Troubleshooting:"
    echo "  • Check logs: docker logs otel-collector"
    echo "  • Restart: docker-compose restart"
    echo "  • See: docs/OTLP_TROUBLESHOOTING.md"
    exit 1
fi
