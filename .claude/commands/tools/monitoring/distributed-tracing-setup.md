______________________________________________________________________

title: Distributed Tracing Setup
owner: Observability Guild
last_reviewed: 2025-10-01
supported_platforms:

- macOS
- Linux
  required_scripts: []
  risk: low
  status: active
  id: 01K6HDRW9VMXPQ3K7N8YJHZ2T6
  category: monitoring
  agents:
- observability-incident-lead
- architecture-council
  tags:
- tracing
- opentelemetry
- jaeger
- zipkin
- observability
- distributed-systems

______________________________________________________________________

## Distributed Tracing Setup

Use this tool to design end-to-end tracing with OpenTelemetry and a trace backend.

## Focus areas

- Automatic and manual instrumentation
- Context propagation and baggage
- Backend selection: Jaeger, Zipkin, Tempo, or cloud trace
- Sampling strategy and export overhead
- HTTP, gRPC, DB, and queue spans

## Workflow

1. Identify the services and request path to trace.
1. Choose the least intrusive instrumentation path first.
1. Add context propagation and useful attributes.
1. Configure sampling and asynchronous export.
1. Validate that the trace is readable end to end.

## Output

- Instrumentation plan
- Backend and exporter recommendation
- Minimal code snippets or config notes

## Requirements for: $ARGUMENTS
