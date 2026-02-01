# Makefile for OTLP Client Testing
# Convenience commands for testing OTLP ingestion

.PHONY: help start test test-claude test-qwen stop clean health logs install

# Default target
help:
	@echo "OTLP Client Testing Commands"
	@echo ""
	@echo "Stack Management:"
	@echo "  make start      - Start OTLP test stack"
	@echo "  make stop       - Stop OTLP test stack"
	@echo "  make clean      - Stop stack and remove volumes"
	@echo "  make health     - Check collector health"
	@echo "  make logs       - View collector logs"
	@echo ""
	@echo "Testing:"
	@echo "  make test       - Run all tests (primary, claude, qwen)"
	@echo "  make test-primary - Send test telemetry to primary collector"
	@echo "  make test-claude  - Send Claude-specific test telemetry"
	@echo "  make test-qwen    - Send Qwen-specific test telemetry"
	@echo ""
	@echo "Setup:"
	@echo "  make install    - Install Python dependencies"
	@echo ""

# Stack management
start:
	@echo "Starting OTLP test stack..."
	docker-compose -f docker-compose.otlp.yml up -d
	@echo "Waiting for services to be healthy..."
	@sleep 10
	@curl -s http://localhost:13133/healthy && echo "✅ Collector is healthy" || echo "❌ Collector not ready"
	@echo ""
	@echo "Services available at:"
	@echo "  • Collector: http://localhost:13133/healthy"
	@echo "  • Jaeger:    http://localhost:16686"
	@echo "  • Prometheus: http://localhost:9090"
	@echo "  • Grafana:   http://localhost:3000 (admin/admin)"

stop:
	@echo "Stopping OTLP test stack..."
	docker-compose -f docker-compose.otlp.yml down

clean:
	@echo "Stopping OTLP test stack and removing volumes..."
	docker-compose -f docker-compose.otlp.yml down -v

# Health and monitoring
health:
	@echo "Checking collector health..."
	@curl -s http://localhost:13133/healthy && echo "" || echo "❌ Collector not healthy"

logs:
	docker-compose -f docker-compose.otlp.yml logs -f otel-collector

# Installation
install:
	@echo "Installing OpenTelemetry Python dependencies..."
	pip3 install opentelemetry-api opentelemetry-sdk opentelemetry-exporter-otlp-proto-grpc

# Testing
test: test-primary test-claude test-qwen
	@echo ""
	@echo "✅ All tests complete!"
	@echo "View traces at: http://localhost:16686"
	@echo "View metrics at: http://localhost:9090"

test-primary:
	@echo "Sending test telemetry to primary collector..."
	python3 python-otlp-client.py \
		--endpoint http://localhost:4317 \
		--service test-app \
		--count 5

test-claude:
	@echo "Sending Claude-specific test telemetry..."
	python3 python-otlp-client.py \
		--endpoint http://localhost:4319 \
		--service claude-integration \
		--source claude \
		--ai-workflow

test-qwen:
	@echo "Sending Qwen-specific test telemetry..."
	python3 python-otlp-client.py \
		--endpoint http://localhost:4321 \
		--service qwen-integration \
		--source qwen \
		--ai-workflow
