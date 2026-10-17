---
name: runpod-flash-to-sdk-2
description: Replacement of `runpod-flash` with the merged `runpod` SDK 2.0; mahavishnu.pools.RunPodPool becomes a thin client to a pre-existing serverless endpoint id.
---

**Context (2026-10-17):** Upstream merged Flash into the main `runpod` Python package (SDK 2.0, released 2026-10-15). The `runpod-flash` PyPI package is deprecated on 2026-10-29. Per the deprecation warning we emit on every `mahavishnu pool spawn --type runpod`, `runpod_flash.Endpoint` is now `runpod.Endpoint(id)` — a client handle, not a worker-registration decorator.

**Decision:** Option A (thin client). `RunPodPool.__init__` requires `endpoint_id` in `config.extra_config`; `start()` constructs `runpod.Endpoint(endpoint_id)`; `execute_task` wraps `endpoint.run(payload)` + `.status()` + `.output()` in `asyncio.to_thread` (the SDK is sync). The legacy handler function (`_build_endpoint` decorator + `GpuType` lookup) is removed — worker logic now lives in the RunPod endpoint config (console or `runpod.serverless.start({...})` in a dedicated handler repo). `GpuHandlerPool` keeps category routing (`vision` / `ml_inference` / `embedding`); its `_build_endpoint` override is dropped.

**Why:** Demoing a deprecated path for 12 days would've been actively wrong signposting; Option A also decouples worker code from orchestrator code (cleaner substrate boundaries).

**Status:** merged; `runpod-flash>=1.20.1` removed from the `[gpu]` optional group, replaced with `runpod>=2.0,<3`.

Reference: https://docs.runpod.io/sdk/migrate-from-flash
