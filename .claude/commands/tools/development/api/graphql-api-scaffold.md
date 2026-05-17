______________________________________________________________________

title: GraphQL API Scaffold
owner: Developer Enablement Guild
last_reviewed: 2025-10-01
supported_platforms:

- macOS
- Linux
  required_scripts: []
  risk: medium
  status: active
  id: 01K6H9DJ3RDGFNDADS8GNG9522
  category: development/api
  agents:
- graphql-architect
- architecture-council
- qa-strategist
  tags:
- graphql
- api
- schema
- apollo

______________________________________________________________________

## GraphQL API Scaffold Generator

Use this tool to design a GraphQL API with schema, resolvers, subscriptions, and security.

## Focus areas

- Schema design and documentation
- Resolver structure and N+1 avoidance
- Query complexity and depth limits
- Auth, authorization, and rate limiting
- Subscriptions and real-time transport
- Testing and federation only when needed

## Workflow

1. Define the schema and domain boundaries.
1. Pick the resolver and data-loading strategy.
1. Add security controls and observability.
1. Include tests for schema, resolvers, and subscriptions.
1. Add federation only if the architecture actually needs it.

## Output

- GraphQL project skeleton
- Schema and resolver outline
- Validation and test checklist

## Requirements for: $ARGUMENTS
