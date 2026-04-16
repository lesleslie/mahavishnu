# Worker Classification Policy

**Purpose:** Decide whether a new integration should be a terminal worker, a gateway worker, or stay external.

## Rules

Use a **terminal worker** when the integration:

- can be launched as a CLI
- produces parseable stdout/stderr
- can be terminated cleanly by Mahavishnu
- is useful as an execution surface rather than a product runtime

Use a **gateway worker** when the integration:

- is primarily an HTTP/RPC service
- is already exposed through a long-running endpoint
- should not be spawned as a local terminal process

Keep an integration **external reference only** when the integration:

- is the user-facing assistant or runtime itself
- is a product boundary, not an execution backend
- would duplicate Mahavishnu's orchestration role if embedded directly

## Current Examples

### Terminal workers

- `terminal-qwen`
- `terminal-claude`
- `terminal-codex`
- `terminal-openclaw`
- `terminal-deepagents`
- `terminal-clai`

### Gateway workers

- `gateway-openclaw`

### External references

- Hermes

## Add New Integrations

Before adding a new worker type, check:

1. Is there a real CLI or service surface?
2. Does Mahavishnu need to own execution, or just coordinate it?
3. Would the integration become a duplicate assistant/runtime if embedded?
4. Can the worker complete deterministically enough for registry-driven orchestration?

If the answer to #3 is yes, keep it external.
