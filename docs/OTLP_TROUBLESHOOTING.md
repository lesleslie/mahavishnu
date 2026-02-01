# OTLP Troubleshooting Guide

Comprehensive troubleshooting guide for OTLP ingestion issues in Mahavishnu.

## Quick Diagnostics

Run this quick diagnostic to check system health:

```bash
#!/bin/bash
echo "=== OTLP System Diagnostics ==="
echo ""

echo "1. Checking Docker..."
docker info > /dev/null 2>&1 && echo "✅ Docker is running" || echo "❌ Docker is not running"

echo ""
echo "2. Checking collector health..."
curl -s http://localhost:13133/healthy && echo "✅ Collector is healthy" || echo "❌ Collector is not healthy"

echo ""
echo "3. Checking OTLP ports..."
netstat -tuln 2>/dev/null | grep -E "4317|4318|4319|4320|4321|4322" > /dev/null && echo "✅ OTLP ports are listening" || echo "❌ OTLP ports not listening"

echo ""
echo "4. Checking services..."
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" | grep -E "otel-collector|jaeger|prometheus|elasticsearch" || echo "❌ Services not running"

echo ""
echo "5. Checking collector logs..."
docker logs otel-collector 2>&1 | tail -5
```

Save as `diagnose.sh` and run with `bash diagnose.sh`.

---

## Common Issues

### Issue 1: No Traces Appearing in Jaeger

**Symptoms:**
- Jaeger UI shows no traces
- Client runs without errors
- No data in Jaeger search

**Diagnostic Steps:**

```bash
# 1. Verify Jaeger is running
curl http://localhost:16686
# Should return HTML

# 2. Check Jaeger received traces
docker logs jaeger 2>&1 | grep -i "trace"

# 3. Check collector is sending to Jaeger
docker logs otel-collector 2>&1 | grep -i "jaeger"

# 4. Verify Jaeger endpoint in collector config
docker exec otel-collector cat /etc/otel-collector-config.yaml | grep -A 3 "jaeger:"
```

**Solutions:**

1. **Restart Jaeger:**
   ```bash
   docker-compose restart jaeger
   ```

2. **Check Jaeger OTLP receiver:**
   ```bash
   curl -X POST http://localhost:4318/v1/traces -d '{}'
   ```

3. **Verify exporter configuration:**
   ```yaml
   exporters:
     jaeger:
       endpoint: jaeger:14250  # Must match service name
       tls:
         insecure: true
   ```

4. **Check network connectivity:**
   ```bash
   docker exec otel-collector nc -zv jaeger 14250
   ```

---

### Issue 2: Connection Refused Errors

**Symptoms:**
- `Error: 14 UNAVAILABLE: Connection refused`
- Client cannot connect to collector
- Telnet to port fails

**Diagnostic Steps:**

```bash
# 1. Check collector is running
docker ps | grep otel-collector

# 2. Check ports are exposed
docker port otel-collector

# 3. Test endpoint from host
curl http://localhost:4317
curl http://localhost:4318

# 4. Test from inside container
docker exec otel-collector wget -O- http://localhost:4317
```

**Solutions:**

1. **Use correct endpoint format:**
   ```python
   # Correct
   OTLPSpanExporter(endpoint="http://localhost:4317", insecure=True)

   # Wrong (will cause connection refused)
   OTLPSpanExporter(endpoint="localhost:4317")  # Missing http://
   OTLPSpanExporter(endpoint="https://localhost:4317")  # Should be http://
   ```

2. **Verify port mapping:**
   ```yaml
   services:
     otel-collector:
       ports:
         - "4317:4317"  # Must be mapped
   ```

3. **Check firewall:**
   ```bash
   # macOS
   sudo pfctl -s rules | grep 4317

   # Linux
   sudo iptables -L -n | grep 4317
   ```

4. **For Docker networking:**
   ```python
   # Use service name when both are in Docker
   endpoint="http://otel-collector:4317"

   # Use localhost when client is on host
   endpoint="http://localhost:4317"
   ```

---

### Issue 3: Metrics Not Appearing in Prometheus

**Symptoms:**
- Prometheus UI has no data
- Query returns "no results"
- Metrics exist in collector but not Prometheus

**Diagnostic Steps:**

```bash
# 1. Check Prometheus targets
curl http://localhost:9090/api/v1/targets | jq '.data.activeTargets[] | {job: .labels.job, health: .health}'

# 2. Check Prometheus received metrics
curl http://localhost:9090/api/v1/label/__name__/values | jq '.data[]' | grep -i operation

# 3. Check collector metrics endpoint
curl http://localhost:8888/metrics | grep operations_total

# 4. Check remote write is working
docker logs prometheus 2>&1 | grep -i "remote"
```

**Solutions:**

1. **Verify remote write configuration:**
   ```yaml
   exporters:
     prometheusremotewrite:
       endpoint: 'http://prometheus:9090/api/v1/write'  # Must be /api/v1/write
   ```

2. **Check Prometheus is configured to accept remote write:**
   ```yaml
   prometheus:
     command:
       - '--enable-feature=remote-write-receiver'
   ```

3. **Manually test metric ingestion:**
   ```bash
   cat <<EOF | curl -X POST http://localhost:9090/api/v1/write --data-binary @-
   # TYPE test_metric counter
   test_metric{label="value"} 42
   EOF
   ```

4. **Check for metric name conflicts:**
   ```bash
   # List all metrics
   curl http://localhost:8888/metrics | grep "^operations"
   ```

---

### Issue 4: Logs Not Appearing in Elasticsearch

**Symptoms:**
- Kibana shows no data
- Index not created
- No logs in Elasticsearch

**Diagnostic Steps:**

```bash
# 1. Check Elasticsearch health
curl http://localhost:9200/_cluster/health

# 2. List indices
curl http://localhost:9200/_cat/indices?v

# 3. Check for logs index
curl http://localhost:9200/mahavishnu-logs*/_search?pretty

# 4. Check Elasticsearch logs
docker logs elasticsearch 2>&1 | tail -50
```

**Solutions:**

1. **Create index pattern manually:**
   ```bash
   curl -X PUT http://localhost:9200/mahavishnu-logs-$(date +%Y.%m.%d)
   ```

2. **Check exporter configuration:**
   ```yaml
   exporters:
     elasticsearch:
       endpoints:
         - http://elasticsearch:9200
       index: 'mahavishnu-logs'  # Without date pattern
   ```

3. **Verify Elasticsearch has no security blocking:**
   ```yaml
   elasticsearch:
     environment:
       - xpack.security.enabled=false  # Must be disabled for dev
   ```

4. **Test index creation:**
   ```bash
   curl -X PUT http://localhost:9200/test-index
   curl -X POST http://localhost:9200/test-index/_doc -H 'Content-Type: application/json' -d '{"message": "test"}'
   ```

---

### Issue 5: File Log Receiver Not Working

**Symptoms:**
- Log files exist but not appearing
- No errors in collector logs
- File receiver not reading files

**Diagnostic Steps:**

```bash
# 1. Check file paths
ls -la /var/log/mahavishnu/sessions/

# 2. Check file permissions
stat /var/log/mahavishnu/sessions/claude/test.log

# 3. Verify volume mount
docker exec otel-collector ls -la /var/log/mahavishnu/sessions/

# 4. Check collector config for filelog receiver
docker exec otel-collector cat /etc/otel-collector-config.yaml | grep -A 10 "filelog:"
```

**Solutions:**

1. **Verify volume mount in docker-compose:**
   ```yaml
   services:
     otel-collector:
       volumes:
         - /var/log/mahavishnu/sessions:/var/log/mahavishnu/sessions:ro
   ```

2. **Check file format:**
   ```bash
   # Must be JSON for JSON parser
   cat /var/log/mahavishnu/sessions/claude/test.log
   # Expected: {"timestamp": "...", "message": "..."}
   ```

3. **Fix file permissions:**
   ```bash
   sudo chmod 644 /var/log/mahavishnu/sessions/*.log
   sudo chown $(whoami) /var/log/mahavishnu/sessions/*.log
   ```

4. **Use correct operators in config:**
   ```yaml
   operators:
     - type: json_parser  # For JSON logs
     - type: regex_parser  # For text logs
   ```

---

### Issue 6: High Memory Usage

**Symptoms:**
- Collector OOM killed
- `docker ps` shows collector restarting
- High memory consumption

**Diagnostic Steps:**

```bash
# 1. Check container stats
docker stats otel-collector

# 2. Check for OOM kills
docker inspect otel-collector | jq '.[0].State.OOMKilled'

# 3. Check collector logs for memory issues
docker logs otel-collector 2>&1 | grep -i "memory"

# 4. Check memory limiter stats
curl http://localhost:8888/metrics | grep memory_limiter
```

**Solutions:**

1. **Adjust batch settings:**
   ```yaml
   processors:
     batch:
       timeout: 10s  # Increase from 5s
       send_batch_size: 5000  # Decrease from 10000
   ```

2. **Tighten memory limiter:**
   ```yaml
   memory_limiter:
     check_interval: 1s
     limit_percentage: 70  # Decrease from 80
     spike_limit_percentage: 20  # Decrease from 25
   ```

3. **Increase container memory:**
   ```yaml
   services:
     otel-collector:
       deploy:
         resources:
           limits:
             memory: 1G  # Increase from default
   ```

4. **Enable sending queue:**
   ```yaml
   exporters:
     otlp:
       sending_queue:
         enabled: true
         queue_size: 10000
         num_consumers: 10
   ```

---

### Issue 7: Mixed Telemetry from Different Sources

**Symptoms:**
- Can't distinguish Claude vs Qwen traces
- All telemetry appears as one service
- Filters not working

**Diagnostic Steps:**

```bash
# 1. Check resource attributes in Jaeger
# Open Jaeger UI → Click on trace → Look at tags

# 2. Query Prometheus with filter
curl http://localhost:9090/api/v1/query?query=operations_total{telemetry_source="claude"}

# 3. Check exporter logs
docker logs otel-collector 2>&1 | grep -i "resource"
```

**Solutions:**

1. **Use separate endpoints:**
   ```python
   # Claude
   OTLPSpanExporter(endpoint="http://localhost:4319")

   # Qwen
   OTLPSpanExporter(endpoint="http://localhost:4321")
   ```

2. **Set resource attributes:**
   ```python
   resource = Resource.create({
       "service.name": "claude-integration",
       "telemetry.source": "claude",  # This is key
       "telemetry.source.type": "ai_assistant"
   })
   ```

3. **Use attributes processor:**
   ```yaml
   processors:
     attributes/claude:
       actions:
         - key: telemetry.source
           value: claude
           action: insert
   ```

---

### Issue 8: Batch Delays in Seeing Telemetry

**Symptoms:**
- Telemetry takes 10+ seconds to appear
- Metrics appear after delays
- Seems like data is lost

**Diagnostic Steps:**

```bash
# 1. Check batch timeout
docker exec otel-collector cat /etc/otel-collector-config.yaml | grep -A 3 "batch:"

# 2. Check exporter queue
curl http://localhost:8888/metrics | grep queue

# 3. Monitor real-time
watch -n 1 'curl -s http://localhost:8888/metrics | grep operations_total'
```

**Solutions:**

1. **Reduce batch timeout:**
   ```yaml
   processors:
     batch:
       timeout: 1s  # Decrease from 5s for faster export
   ```

2. **Decrease batch size:**
   ```yaml
   batch:
     send_batch_size: 1000  # Export more frequently
   ```

3. **Use debug logging to verify:**
   ```yaml
   exporters:
     logging:
       loglevel: debug  # See exports in real-time
   ```

---

## Debugging Tools

### Collector Zpages

Access internal collector debugging:

```bash
# Zpages UI
open http://localhost:55679/debug/tracez

# Pipeline status
curl http://localhost:55679/debug/pipelinez

# Receiver status
curl http://localhost:55679/debug/receiverz
```

### Prometheus Metrics on Collector

```bash
# All collector metrics
curl http://localhost:8888/metrics

# Specific metrics
curl http://localhost:8888/metrics | grep otelcol_exporter

# Check for errors
curl http://localhost:8888/metrics | grep error
```

### Jaeger Self-Tracing

The collector can trace itself:

```yaml
extensions:
  pprof:
    endpoint: 0.0.0.0:1777

service:
  extensions: [pprof]

# Access pprof
go tool pprof http://localhost:1777/debug/pprof/heap
```

---

## Performance Tuning

### High Throughput Scenarios

For 1000+ spans/second:

```yaml
processors:
  batch:
    timeout: 10s
    send_batch_size: 50000
    send_batch_max_size: 55000

exporters:
  jaeger:
    timeout: 30s
    sending_queue:
      enabled: true
      queue_size: 100000
      num_consumers: 20
```

### Low Latency Scenarios

For real-time monitoring:

```yaml
processors:
  batch:
    timeout: 100ms  # Very fast
    send_batch_size: 100

exporters:
  logging:
    loglevel: info  # Reduce overhead
```

### Memory-Constrained Environments

For < 1GB RAM:

```yaml
processors:
  memory_limiter:
    limit_percentage: 50  # Conservative
    spike_limit_percentage: 10

  batch:
    send_batch_size: 1000  # Small batches
```

---

## Health Checks

### Comprehensive Health Check Script

```bash
#!/bin/bash
# health-check.sh - Comprehensive OTLP system health check

FAIL=0

echo "=== OTLP System Health Check ==="
echo ""

# Collector health
echo -n "Collector: "
if curl -s http://localhost:13133/healthy > /dev/null; then
    echo "✅ OK"
else
    echo "❌ FAIL"
    FAIL=1
fi

# Jaeger health
echo -n "Jaeger: "
if curl -s http://localhost:16686 > /dev/null; then
    echo "✅ OK"
else
    echo "❌ FAIL"
    FAIL=1
fi

# Prometheus health
echo -n "Prometheus: "
if curl -s http://localhost:9090/-/healthy > /dev/null; then
    echo "✅ OK"
else
    echo "❌ FAIL"
    FAIL=1
fi

# Elasticsearch health
echo -n "Elasticsearch: "
if curl -s http://localhost:9200/_cluster/health | grep -q '"status":"green"\|"status":"yellow"'; then
    echo "✅ OK"
else
    echo "❌ FAIL"
    FAIL=1
fi

# OTLP endpoints
echo -n "OTLP gRPC (4317): "
if nc -z localhost 4317 2>/dev/null; then
    echo "✅ OK"
else
    echo "❌ FAIL"
    FAIL=1
fi

echo -n "OTLP HTTP (4318): "
if nc -z localhost 4318 2>/dev/null; then
    echo "✅ OK"
else
    echo "❌ FAIL"
    FAIL=1
fi

echo ""
if [ $FAIL -eq 0 ]; then
    echo "✅ All systems operational"
    exit 0
else
    echo "❌ Some systems failed"
    exit 1
fi
```

---

## Getting Help

If you're still stuck:

1. **Check logs:**
   ```bash
   docker-compose logs -f --tail=100 otel-collector
   ```

2. **Enable debug logging:**
   ```yaml
   exporters:
     logging:
       loglevel: debug
   ```

3. **Verify configuration:**
   ```bash
   docker run --rm -v $(pwd)/config:/config \
     otel/opentelemetry-collector-contrib:latest \
     --config=/config/otel-collector-config.yaml \
     --validate
   ```

4. **Check GitHub issues:**
   - [OpenTelemetry Collector](https://github.com/open-telemetry/opentelemetry-collector/issues)
   - [OpenTelemetry Python](https://github.com/open-telemetry/opentelemetry-python/issues)

5. **Community resources:**
   - [OpenTelemetry Slack](https://cloud-native.slack.com/archives/CJFCJHG4Q)
   - [CNCF Discourse](https://discuss.cncf.io/)
