______________________________________________________________________

title: gRPC Service Implementation
owner: Developer Enablement Guild
last_reviewed: 2025-10-01
supported_platforms:

- macOS
- Linux
  required_scripts: []
  risk: medium
  status: active
  id: 01K6H9DJ3RDGFNDADS8GNG9523
  category: development/api
  agents:
- grpc-specialist
- architecture-council
- observability-incident-lead
  tags:
- grpc
- protobuf
- microservices
- rpc

______________________________________________________________________

## gRPC Service Implementation

Use this tool to scaffold a type-safe gRPC service with streaming, auth, and observability.

## Focus areas

- Proto definitions and field design
- Unary, server-streaming, client-streaming, and bidi handlers
- Client generation and deadline handling
- TLS, auth, and interceptor patterns
- Metrics, logging, health checks, and tracing

## Workflow

1. Define the protobuf contract first.
1. Choose service methods and streaming shapes deliberately.
1. Add auth, validation, and error handling.
1. Wire in retries, deadlines, and load balancing where needed.
1. Validate with focused server and client tests.

## Output

- Proto/service outline
- Server and client implementation plan
- Testing and deployment checklist

## Requirements for: $ARGUMENTS
