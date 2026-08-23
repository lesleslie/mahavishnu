______________________________________________________________________

## name: oneiric-action-kit-awareness description: "Auto-trigger skill that surfaces the matching oneiric.actions.X kit when the user is about to write HMAC signing, token generation, schema validation, retries with backoff, span/log redaction, config serialization, HTTP fetch/probe, compression, hashing, data transforms, debug consoles, automation triggers, or workflow orchestration. Prompts 'Use the kit?' before implementation."

# Oneiric Action-Kit Awareness (auto-trigger)

When user is about to write code that maps to a known kit, surface the
kit before they reinvent.

## When this fires
- Trigger automation (cron-to-event glue) → AutomationTriggerAction (`automation.trigger`)
- Compression / encoding (gzip, base64, etc.) → CompressionAction (`compression.encode`)
- Hashing (md5, sha*, blake2b) → HashAction (`compression.hash`)
- PII / secret redaction in logs, spans, traces → DataSanitizeAction (`data.sanitize`)
- Generic data transforms (rename keys, coerce types) → DataTransformAction (`data.transform`)
- Debug / console output (formatted traces) → DebugConsoleAction (`debug.console`)
- Event dispatch / pub-sub → EventDispatchAction (`event.dispatch`)
- HTTP fetch / probe with retries → HttpFetchAction (`http.fetch`)
- Token / secret / random string generation → SecuritySecureAction (`security.secure`)
- HMAC, signing, signature verification → SecuritySignatureAction (`security.signature`)
- JSON / YAML serialize / deserialize → SerializationAction (`serialization.encode`)
- Cron / interval / scheduled task → TaskScheduleAction (`task.schedule`)
- JSON Schema validation → ValidationSchemaAction (`validation.schema`)
- Audit log / event emission → WorkflowAuditAction (`workflow.audit`)
- Webhook / workflow notification → WorkflowNotifyAction (`workflow.notify`)
- Multi-step workflow orchestration → WorkflowOrchestratorAction (`workflow.orchestrate`)
- Retry with backoff, jitter → WorkflowRetryAction (`workflow.retry`)

## What to do
1. Locate the catalog at `oneiric/docs/action-kits.md` in the oneiric
   project on the developer's filesystem (path varies by setup; if not
   findable, surface "couldn't find the oneiric catalog; please paste
   the kit name from §When this fires above" and continue).
2. Surface to the user: "This looks like `<kit>` (`<metadata.key>`);
   canonical pattern is in the oneiric catalog. Use it?"
3. If yes, write the wrapper. If no (latency, fit), document why in a
   code comment linking back to the catalog entry.

Note: kit invocations go through `oneiric.actions.ActionBridge` (in
`bridge.py`); not all kits require it directly, but the bridge is the
canonical runtime surface for cross-process kit calls.
