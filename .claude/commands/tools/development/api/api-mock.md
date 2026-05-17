______________________________________________________________________

title: Api Mock
owner: Developer Enablement Guild
last_reviewed: 2025-02-06
supported_platforms:

- macOS
- Linux
  required_scripts: []
  risk: medium
  status: active
  id: 01K6EEXBWVGNARGXR4N6YW90TW
  category: development/api

______________________________________________________________________

## API Mocking Framework

Use this tool to create realistic mock services for development, testing, and demos.

## Focus areas

- Route matching by method, path, query, headers, and body
- Scenario-based responses and latency simulation
- Stateful request tracking
- Error and edge-case simulation
- Easy reset between tests

## Workflow

1. Identify the API shape and common request patterns.
1. Define mocks for happy path, errors, and key edge cases.
1. Add state or scenario controls only when needed.
1. Keep the mock contract aligned with the real service.
1. Prefer simple fixtures over a full custom framework unless scale demands it.

## Output

- Mock route plan
- Example stub definitions
- Validation notes for request/response parity

## Requirements

$ARGUMENTS
