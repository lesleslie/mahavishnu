---
status: active
role: canonical
date: 2026-08-31
last_reviewed: 2026-08-31
superseded_by: null
topic: flowscape-v1-bootstrap
---

# Plan: `flowscape` v1 Bootstrap

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `flowscape` v1 — a modernized Etherape replacement for macOS — as a signed `.app` bundle plus PyPI/Homebrew distribution, with live packet capture, 3D interactive scene, statistical heuristics, and Etherape-shaped top-talkers + conversation tables.

**Architecture:** Two-process model: Swift frontend (SwiftUI + Metal) over two `SOCK_SEQPACKET` Unix-domain sockets to a Python backend (`dpkt` for parsing, `pcapy-ng` for live capture, Oneiric for config, `betterproto2` + `SwiftProtobuf` for typed IPC). `.proto` is the single source of truth. CPU layout (sufficient for ≤1000 nodes) on a `DispatchQueue`.

**Tech Stack:** Python 3.14 (dpkt, pcapy-ng, betterproto2, protobuf, numpy, orjson, oneiric), Swift 6 / SwiftUI / Metal (swift-protobuf), macOS-only. Distribution via PyPI (`uvx flowscape`), Homebrew (`les/tap`), signed `.app` + launchd helper.

**Spec:** [`docs/superpowers/specs/2026-08-31-flowscape-design.md`](../specs/2026-08-31-flowscape-design.md) — travels with this plan.

## Global Constraints

- **Python version:** 3.14 (`requires-python = ">=3.14"`).
- **macOS target:** 14+ (Sonoma); build host also 14+. CI runners: `macos-14` (primary; nightly matrix adds `macos-15` fallback), `ubuntu-latest` for Python-only jobs.
- **Swift version:** 6.0+ with strict concurrency enabled.
- **License:** BSD-3-Clause for all source; SPDX short-form headers.
- **No GPL/LGPL/AGPL** in any direct or transitive dep — `pip-licenses --fail-on="GPL;LGPL;AGPL"` is a CI gate.
- **No packet payload bytes on the wire** — `payload_sha256_prefix` is the only payload-derived field allowed in any `.proto`. CI lints for forbidden field names. Runtime Oneiric log filter as defense-in-depth.
- **Naming:** project name `flowscape`, package `flowscape`, CLI `flowscape`, main bundle ID `com.lesleslie.flowscape`, helper bundle ID `com.lesleslie.flowscape.helper`. Both committed in Phase 0a.
- **Commit style:** commitizen conventional commits.
- **Quality gates:** Ruff, mypy strict, pyright, bandit, complexipy, crackerjack. **Coverage:** overall `--cov-fail-under=89` (with `capture.py` excluded from the denominator via `[tool.coverage.run] omit`), per-module gates: **85%** on aggregate/graph/heuristics/decode/publisher/ipc_server/settings, **70%** on capture (separate per-file check). Swift: 70% overall with 90% on Layout and IPCSocket modules. (Replaces the previous 90% per-module gate — relaxed per product-manager feedback.)
- **No `assert` in production Python** — use `if not x: raise ValueError(...)` (per Bodai CLAUDE.md).
- **No `@unchecked Sendable` in production Swift** — CI lint enforces.
- **Swift 6 strict concurrency** from day one (`-strict-concurrency=complete`).
- **CI time budget:** PR Python target ≤3 min; PR Swift target ≤12 min. Tests over 5 s real time are `@pytest.mark.slow` (excluded from PR).

---

## Staffing & Parallelization

| Team size | Realistic timeline | Notes |
|---|---|---|
| **One experienced dev** (Swift + Metal + libpcap + dpkt) | **10-14 weeks** | Sequential phases. Conservative floor includes 3-week Apple ID wait in worst case. |
| **Two devs** | **8-10 weeks** | Dev A: Phase 3 → 5 → 7a/7b. Dev B: Phase 4 → 6a → 6b. Phase 0b scaffolding parallelizes. |
| **Three devs** | **6-8 weeks** | Add Dev C on Phase 6b-Notarized in parallel with 7a/7b. |

The 10-week floor requires: experienced solo dev + Apple ID in 2 weeks + notarization accepted first try. For one dev, 12-14 weeks is the honest range.

**Phase splits (0a+0b, 6a+6b-PyPI+6b-Notarized, 7a+7b) reflect distinct concerns, not parallelization claims.** They do NOT compress critical path for one dev. The plan's structure documents each as a separate phase because they have different Integration Contracts and demoable behavior, not because they can run in parallel.

---

## Apple Developer ID Contingency Tree

| Day | Status check | Action |
|---|---|---|
| Week 1 | Submit application; begin all other Phase 0 work in parallel. | If approved: continue. |
| Week 2 | Status check. | If approved: continue with Phase 6b-Notarized. If pending: ship PyPI + uvx + unsigned `.app` for entire v1. |
| Week 3 | Status check. | If still pending: **drop `.app` distribution from v1**; ship wheel-only via PyPI + Homebrew. Notarized `.app` becomes v1.0.1 hotfix. |
| Week 4+ | — | Re-evaluate `.app` for v1.0.1. |

The default fallback is "ship something useful earlier." `.app` distribution is a v1.x feature, not a v1.0 gate.

---

## 1. Outcome

`flowscape` v1.0.0 is published:
- `pip install flowscape` works; `uvx flowscape` runs without install.
- `brew install les/tap/flowscape` works on macOS.
- A signed and notarized `Flowscape.app` is distributed via GitHub Releases (if Apple Developer ID arrives in time; otherwise unsigned `.app` ships as a dev artifact and v1.0.1 has the signed one).
- `flowscape live --interface en0` renders a 3D interactive network graph with statistical heuristic alerts and a top-talkers sidebar in under 1.5 s from launch.

**Success metric:** a fresh macOS install can run `flowscape live` on a typical home network and see the iconic Etherape-style visualization with frame rate ≥ 30 FPS at ≤1 Gbps sustained capture, and answer "who is talking to whom right now" within 5 seconds.

## 2. Goals

1. Live packet capture + pcap file replay via `pcapy-ng` + `dpkt`.
2. 3D interactive scene with camera orbit, click-a-host, hover-to-inspect, in-scene filtering (no GPU compute — CPU force-directed layout for ≤1000 nodes).
3. **Etherape-shaped sidebar panels:** top talkers (top-10 hosts by bytes-in-window), conversation table (active flows).
4. SwiftUI + Metal frontend, Swift 6 strict concurrency throughout.
5. `.proto`-typed IPC (betterproto2 + SwiftProtobuf) over two `SOCK_SEQPACKET` Unix-domain sockets.
6. Typed Pydantic settings via Oneiric; crackerjack quality gates.
7. Two statistical heuristics (beaconing, port-scan) with realistic thresholds.
8. Active consent gate (first launch + interface/SSID change + every 30 days).
9. Structural no-payload guarantee enforced at the wire-format level + runtime redact filter.
10. Multi-channel distribution (PyPI + uvx + Homebrew + signed `.app`).
11. Launchd helper for `/dev/bpf*` ACL (no Network Extensions entitlement required).

## 3. Non-Goals (v1)

- GPU compute layout (deferred to v1.1; CPU is sufficient for ≤1000 nodes).
- Triple-buffer infrastructure (deferred to v1.1; atomic `MTLBuffer` swap is enough for CPU layout).
- Renderer golden-image suite (deferred to v1.1; v1 uses smoke + manual visual review).
- Time scrubber / historical replay (v2).
- Drill-down beyond top-talkers + conversation table (v2).
- sflow / NetFlow / OTel sources (v2).
- MCP server activation (gated on legal review ADR + DPIA before enabling).
- scapy-mcp / unifi-mcp integration (v2+).
- TLS SNI extraction (v2).
- MAC/OUI bundling (v2).
- Network Extensions entitlement path (maybe v3).
- ML-based anomaly detection (v3+).
- Top-N-churn heuristic (deferred to v1.1; bundled with future top-talkers enhancements).
- Cross-platform GUI (Linux/Windows).
- Sparkle / auto-update (v2).
- Localization (English-only v1).
- Full Settings UI for every Pydantic section (v1 ships 3-4 settings + raw YAML editing via `flowscape config`; full UI v1.1).

## 4. Current Findings

The spec at `docs/superpowers/specs/2026-08-31-flowscape-design.md` was authored in a brainstorming session and revised after:

- **8-agent parallel review.** All Tier-1 + Tier-2 wins incorporated into revision2.
- **Final-pass architect-reviewer.** 9 contradictions + 17 ambiguities + 10 prereqs resolved inline. "Implementation clarifications" section in spec.
- **7-agent plan review.** ~60 findings applied to revision3 of the plan.
- **3-agent final-pass plan review** (Plan, test-automator, product-manager). 12 critical fixes applied to this revision4.

## 5. Implementation Phases

### Phase 0a: Procurement + minimal repo + CI skeleton (1 week)

**Goal:** Apple ID submission in flight; `flowscape` Python package installable; Swift package builds; PR CI green on empty stubs. Two CIs (Python on Linux, Swift on macOS).

#### Task 0a.1: Apple Developer ID procurement + procurement log
**Files:**
- Create: `docs/procurement/apple-developer-id.md`

**Steps:**
- [ ] Submit Apple Developer ID application.
- [ ] Generate App Store Connect API key for notarization (smaller scope than App Store submission; this key is for `notarytool submit`, not App Store distribution); save to `~/.config/secrets/` (out-of-repo).
- [ ] Record Apple Team ID in `docs/procurement/apple-developer-id.md` once received.

#### Task 0a.2: Repo scaffold + Python tooling
**Files:**
- Create: `pyproject.toml`, `README.md`, `LICENSE`, `.gitignore`, `src/flowscape/__init__.py`, `tests/__init__.py`, `tests/python/__init__.py`, `tests/conftest.py`, `ruff.toml`, `mypy.ini`, `.crackerjack.yaml`

**Steps:**
- [ ] Write `pyproject.toml` with PEP 735 groups (`dev`, `macos`, `runtime`), Ruff config, mypy config, hatchling build target.
  - Add `[project.scripts]`: `flowscape = "flowscape.cli:main"`.
  - Configure coverage: `[tool.coverage.run] omit = ["src/flowscape/capture.py"]` (per test-automator finding); `fail_under = 89`.
- [ ] Initialize empty `src/flowscape/_proto/` and `src/Flowscape/Generated/` (gitignored).
- [ ] Write `src/flowscape/__init__.py` with `__version__ = "0.1.0.dev0"`.
- [ ] Write `tests/python/unit/test_smoke.py`:
  ```python
  def test_flowscape_imports():
      import flowscape
      assert flowscape.__version__ == "0.1.0.dev0"
  ```
- [ ] Write `pyproject.toml [tool.pytest.ini_options]`: `addopts = "-m 'not slow' --timeout=300"`.
- [ ] Run `uv sync --group dev`; run `pytest tests/python/unit/test_smoke.py -v` — expect PASS.
- [ ] Commit "feat: scaffold empty flowscape Python package".

#### Task 0a.3: Oneiric settings skeleton (typed Pydantic)
**Files:**
- Create: `src/flowscape/settings.py`, `tests/python/unit/test_settings.py`

**Steps:**
- [ ] Write failing tests covering: defaults, env-var precedence, XDG lookup (create a temp `XDG_CONFIG_HOME` with `local.yaml`, assert override wins), missing `local.yaml` tolerated, malformed YAML raises, unknown field tolerated, logging path substitution for all three install channels.
- [ ] Implement `src/flowscape/settings.py` per spec §Configuration (all six Pydantic classes: `CaptureSettings`, `AggregationSettings`, `LayoutSettings`, `RenderSettings`, `HeuristicSettings` with `delta_threshold_pct_high_density` per A6, `LoggingSettings`).
  - In `LayoutSettings._check_bounds`: use `if not a < b: raise ValueError(...)` (NOT `assert`).
- [ ] Use `oneiric.config.load_app_settings`; `PROJECT_ROOT = Path(__file__).resolve().parent.parent`.
- [ ] Implement `${platform_log_dir}` substitution hook resolving per install channel (`.app` → `~/Library/Logs/Flowscape`, wheel → `~/.flowscape/logs`, Linux → `~/.local/state/flowscape/logs`).
- [ ] Implement runtime Oneiric log filter that drops records with `extra` keys starting with `payload`/`body`/`raw`.
- [ ] Run `pytest tests/python/unit/test_settings.py -v` — expect PASS.
- [ ] Commit "feat(settings): typed Pydantic settings via Oneiric + runtime redact filter".

#### Task 0a.4: Swift package scaffold (SPM-only, no `.xcodeproj`)
**Files:**
- Create: `Package.swift`, `src/Flowscape/Empty.swift`, `Tests/FlowscapeTests/EmptyTests.swift`, `.github/workflows/build.yml`

**Steps:**
- [ ] Run `swift package init --type executable --name Flowscape`. (**Spec deviation:** no `.xcodeproj` is generated; SPM-only. See §6 Spec Reconciliation.)
- [ ] Add swift-protobuf SPM dep (`https://github.com/apple/swift-protobuf` from `1.27.0`).
- [ ] Add to `Package.swift`:
  ```swift
  .target(
      name: "Flowscape",
      dependencies: [
          .product(name: "SwiftProtobuf", package: "swift-protobuf"),
      ],
      resources: [.process("Resources")],
  )
  ```
- [ ] Write `src/Flowscape/Empty.swift` containing `import Foundation` (one-line file that compiles).
- [ ] Write `Tests/FlowscapeTests/EmptyTests.swift` with one passing XCTest.
- [ ] Add `.github/workflows/build.yml`:
  ```yaml
  name: build
  on: [push, pull_request]
  jobs:
    swift:
      runs-on: macos-14
      steps:
        - uses: actions/checkout@v4
        - run: swift build
        - run: swift test
  ```
- [ ] Run `swift build` and `swift test` locally; expect PASS.
- [ ] Commit "feat(swift): Swift package + swift-protobuf SPM dep + build workflow".

#### Task 0a.5: PR CI pipeline (Python + Swift + PII gates)
**Files:**
- Create: `.github/workflows/pr-python.yml`, `.github/workflows/pr-swift.yml`, `.github/workflows/pr-checks.yml`, `scripts/check_log_pii.py`, `scripts/check_no_unchecked_sendable.sh`, `scripts/check_proto_payload_ban.py`, tests for each script

**Steps:**
- [ ] Write failing tests for each script.
- [ ] Implement `scripts/check_log_pii.py`: regex over Python source for log statements with variable names matching `(ip|mac|host|endpoint|payload|packet_body)` (case-insensitive).
- [ ] Implement `scripts/check_no_unchecked_sendable.sh`: greps `src/Flowscape/**/*.swift` for `@unchecked Sendable` (excluding `Tests/`).
- [ ] Implement `scripts/check_proto_payload_ban.py`: scans `proto/flowscape.proto` for field names matching `(payload|body|raw|bytes_data)` excluding `payload_sha256_prefix`.
- [ ] Write `pr-python.yml`:
  ```yaml
  name: pr-python
  on: [pull_request]
  jobs:
    python:
      runs-on: ubuntu-latest
      steps:
        - uses: actions/checkout@v4
        - uses: actions/setup-python@v5
          with: { python-version: '3.14' }
        - uses: astral-sh/setup-uv@v4
        - run: uv sync --group dev
        - run: ruff check .
        - run: mypy --strict src/flowscape
        - run: pyright src/flowscape
        - run: pytest --cov-fail-under=89 -m "not slow"
        - run: pip-licenses --fail-on="GPL;LGPL;AGPL"
        - run: python scripts/check_log_pii.py
        - run: python scripts/check_proto_payload_ban.py
  ```
- [ ] Write `pr-swift.yml`:
  ```yaml
  name: pr-swift
  on: [pull_request]
  jobs:
    swift:
      runs-on: macos-14
      steps:
        - uses: actions/checkout@v4
        - run: swift build
        - run: swift test
        - run: bash scripts/check_no_unchecked_sendable.sh
  ```
- [ ] Write `pr-checks.yml` orchestrator using **reusable workflow `uses:` with `on: workflow_call:`**. Update `pr-python.yml` and `pr-swift.yml` to declare both `on: [pull_request]` AND `on: workflow_call:` triggers (reusable workflows ignore the called file's `on:` when invoked via `uses:`).
- [ ] Verify the workflows would run on a sample PR.
- [ ] Commit "feat(ci): PR pipelines for Python (Linux) + Swift (macOS) + PII/Sendable/proto-payload gates".

#### Integration Contract — Phase0a
- **Triggered from:** `git clone` of fresh repo; CI on every PR.
- **Returns to / updates:** Empty repo + scaffolding that `git status` shows clean; `uv sync --group dev` succeeds; `swift build` succeeds; PR CI green on empty stubs; Apple ID application submitted.
- **Demonstrable by:** `pip install -e .` works; `uvx --from . flowscape version` exits 0; `swift build && swift test` exits 0.
- **Rollback signal:** PR CI red on empty stubs implies Phase 0a bug.
- **Observability added:** CI badge in README; first PR Actions run visible.

---

### Phase 0b: Proto + codegen + clean-room + PII gate + fixtures (1 week)

#### Task 0b.1: Proto schema + codegen
**Files:**
- Create: `proto/flowscape.proto`, `scripts/gen_proto.sh`, `tests/python/integration/test_proto_roundtrip.py`

**Steps:**
- [ ] Write failing test:
  ```python
  def test_graph_snapshot_roundtrip():
      from flowscape._proto.flowscape_pb2 import GraphSnapshot, HostNode, FlowEdge
      snap = GraphSnapshot(
          schema_major=1, schema_minor=0, tick_id=42,
          timestamp_ns=1_700_000_000_000_000_000,
          nodes=[HostNode(id="192.168.1.5", bytes_in_window=1024)],
          edges=[FlowEdge(id="tcp:1->2:80", src="192.168.1.5", dst="10.0.0.1", bytes=1024)],
      )
      wire = snap.SerializeToString()
      snap2 = GraphSnapshot()
      snap2.ParseFromString(wire)
      assert snap2.nodes[0].id == "192.168.1.5"
  ```
- [ ] Author `proto/flowscape.proto` exactly as in spec §IPC contract.
- [ ] Write `scripts/gen_proto.sh`:
  ```bash
  #!/usr/bin/env bash
  set -euo pipefail
  REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  PYTHON_OUT="$REPO_ROOT/src/flowscape/_proto"
  SWIFT_OUT="$REPO_ROOT/src/Flowscape/Generated"
  mkdir -p "$PYTHON_OUT" "$SWIFT_OUT"
  protoc \
    --proto_path="$REPO_ROOT/proto" \
    --plugin=protoc-gen-better-python="$(which protoc-gen-betterproto2)" \
    --better-python_out="$PYTHON_OUT" \
    --plugin=protoc-gen-swift="$(which protoc-gen-swift)" \
    --swift_out="$SWIFT_OUT" \
    "$REPO_ROOT/proto/flowscape.proto"
  ```
- [ ] Wire `scripts/gen_proto.sh` into `pyproject.toml` so `uv sync` regenerates Python types.
- [ ] Add Run Script build phase in `Package.swift` calling `scripts/gen_proto.sh` for Swift codegen.
- [ ] Run `pytest tests/python/integration/test_proto_roundtrip.py -v` — expect PASS.
- [ ] Commit "feat(proto): flowscape.proto schema + betterproto2 + swift-protobuf codegen".

#### Task 0b.2: Phase 0 spike — Swift 6 actor + Metal placeholder
**Files:**
- Create: `src/Flowscape/ActorSpike.swift`, `Tests/FlowscapeTests/ActorSpikeTests.swift`

**Steps:**
- [ ] Write failing test:
  ```swift
  func test_actor_spike_actor_isolated() async throws {
      let actor = ActorSpike()
      let result = await actor.greet(name: "World")
      XCTAssertEqual(result, "Hello, World!")
  }
  ```
- [ ] Implement `ActorSpike`:
  ```swift
  actor ActorSpike {
      func greet(name: String) -> String { "Hello, \(name)!" }
  }
  ```
- [ ] Build with `swift build -Xswiftc -strict-concurrency=complete` — expect PASS.
- [ ] Run `swift test` — expect PASS.
- [ ] **Decision gate:** if Swift 6 actor pattern compiles + passes under strict concurrency, viable for Phase 3. If not, fall back to Swift 5 mode.
- [ ] Commit "feat(spike): Swift 6 actor placeholder to de-risk Phase 3".

#### Task 0b.3: CI proto sync gate (Python side)
**Files:**
- Create: `tests/integration/test_proto_sync.py`

**Steps:**
- [ ] Write failing test: regenerate proto types via `scripts/gen_proto.sh`, encode a known `GraphSnapshot`, decode, assert fields.
- [ ] Phase 0b can only test Python side (Swift receiver is Phase 2).
- [ ] Add to `.github/workflows/pr-python.yml`.
- [ ] Commit "feat(test): proto sync CI gate (Python side)".

#### Task 0b.4: Clean-room CONTRIBUTING.md
**Files:**
- Create: `CONTRIBUTING.md`, `docs/clean-room-attestations/template.md`

**Steps:**
- [ ] Author `CONTRIBUTING.md` with: clean-room attestation form, list of "overlapping subsystems", exclusion rule, pre-commit CI check.
- [ ] Author `docs/clean-room-attestations/template.md`.
- [ ] Add to `.github/workflows/pr-checks.yml`: step that checks no commit on overlapping files has an author with "yes" Etherape attestation.
- [ ] Commit "feat(docs): clean-room CONTRIBUTING.md + attestation template".

#### Task 0b.5: Synthetic pcap fixture generation
**Files:**
- Create: `scripts/gen_pcap_fixtures.py`, `tests/fixtures/` (scapy, build-time only)

**Steps:**
- [ ] Implement `scripts/gen_pcap_fixtures.py` using scapy — emits: HTTP traffic, DNS bursts, IPv6, ARP-heavy LAN, port-scan, beaconing (20% jitter), malformed packet, TCP/443 with TLS payloads.
- [ ] Use `Raw` layers and explicit pcap headers with fixed timestamps for determinism.
- [ ] Per-fixture provenance: each fixture ships with `tests/fixtures/<name>.provenance.json`.
- [ ] Run twice; verify byte-identical.
- [ ] Commit "feat(test): synthetic pcap fixture generation with provenance".

#### Integration Contract — Phase0b
- **Triggered from:** Phase 0a's empty stubs compile and PR CI green.
- **Returns to / updates:** `.proto` schema committed; codegen scripts produce Python + Swift types; actor spike proves Swift 6 pattern; clean-room protocol in repo; fixtures available.
- **Demonstrable by:** `bash scripts/gen_proto.sh` regenerates without errors; actor spike test passes.
- **Rollback signal:** Actor spike fails compile under strict concurrency → fall back to Swift 5 mode documented in ADR.
- **Observability added:** proto sync CI gate; clean-room author check; fixture provenance metadata.

---

### Phase 1: Python backend — capture, decode, aggregate (4 weeks)

**Goal:** Working `flowscape replay <pcap>` + `flowscape live --interface en0` CLIs.

#### Task 1.0: Recording-replay fixture for capture.py
**Files:**
- Create: `tests/python/unit/conftest.py`, `tests/python/unit/_recordings/*.pcap`

**Steps:**
- [ ] Create `tests/python/unit/conftest.py` exposing a `recording_source(name)` fixture.
- [ ] Implement `RecordingCapture` that replays recorded libpcap output bytes through the same code path as live capture.
- [ ] Record baseline fixtures by capturing 30 s of `lo0` traffic on macOS, saving as `tests/python/unit/_recordings/lo0_baseline.pcap`.
- [ ] Verify `recording_source('lo0_baseline')` round-trips through the same code path as `LibpcapLiveCapture`.
- [ ] Commit "feat(test): recording-replay fixture for capture.py unit tests".

#### Task 1.1: capture.py with `pcapy-ng` + `pcap_thread`
**Files:**
- Create: `src/flowscape/capture.py`, `src/flowscape/capture_registry.py`, `tests/python/unit/test_capture.py`

**Steps:**
- [ ] Write failing test: `test_capture.py::test_capture_source_registry` (verifies registry API).
- [ ] Implement `CaptureSource` ABC with `start()`, `stop()`, `pause()`, `resume()`, `is_paused()`, `health()`.
- [ ] Implement `capture_registry.py` with module-level `register_source(name, source)` and `get_source(name)`.
- [ ] Implement `LibpcapLiveCapture` (uses `pcapy-ng`).
- [ ] Implement `PcapFileCapture` (uses dpkt).
- [ ] Implement `pcap_thread` running `pcap_loop` synchronously; `loop.call_soon_threadsafe(queue.put_nowait, packet)` for asyncio hand-off.
- [ ] Implement real ctypes fallback: `LibpcapCtypesCapture` wraps `libpcap.dylib` directly.
- [ ] Use `recording_source` fixture from Task 1.0 for unit tests; achieve 70% coverage without real interfaces.
- [ ] Run `pytest tests/python/unit/test_capture.py -v` — expect PASS.
- [ ] Commit "feat(capture): libpcap capture source with pcap_thread + ctypes fallback + registry".

#### Task 1.2: decode.py with `payload_sha256_prefix` and buffer zeroing
**Files:**
- Create: `src/flowscape/decode.py`, `tests/python/unit/test_decode.py`, `tests/python/property/test_decode_fuzz.py`

**Steps:**
- [ ] Write failing unit tests for IP/TCP/UDP/ICMP/ARP/ICMPv6 decode.
- [ ] Implement `decode_packet(raw_packet: bytes) -> FlowEvent` using dpkt.
- [ ] Compute `payload_sha256_prefix = hashlib.sha256(payload).digest()[:32]`.
- [ ] Context manager that zeroes source buffer on exit.
- [ ] Hypothesis property test: `test_decode_fuzz.py::test_decode_never_crashes_on_random_bytes`. Bound to 65535 bytes (IP MTU limit). Mark `@pytest.mark.slow` if iteration count >10.
- [ ] Commit "feat(decode): dpkt-based decode with payload_sha256_prefix + buffer zeroing".

#### Task 1.3: aggregate.py with two-tier windowing
**Files:**
- Create: `src/flowscape/aggregate.py`, `tests/python/unit/test_aggregate.py`, `tests/python/property/test_aggregate_invariants.py`

**Steps:**
- [ ] Write failing unit tests for `update_flow(event)`, `current_snapshot()`, fast/slow window rollover.
- [ ] Implement `FlowAggregator`: fast window (60s sliding); slow window (600s sparse timestamps).
- [ ] Use `collections.deque(maxlen=N)`; `oneiric.actions.data_transforms` for percentile rolling stats.
- [ ] Hypothesis property tests: `byte counts non-decreasing over time`, `node set ⊇ edge endpoints`.
- [ ] Commit "feat(aggregate): sliding-window aggregator with fast + slow tiers".

#### Task 1.4: graph.py
**Files:**
- Create: `src/flowscape/graph.py`, `tests/python/unit/test_graph.py`

**Steps:**
- [ ] Write failing test: `derive_snapshot(aggregator) -> GraphSnapshot`.
- [ ] Implement pure transformation from `FlowAggregator` state to `GraphSnapshot`.
- [ ] Validate `payload_sha256_prefix` length == 32 before serializing.
- [ ] Commit "feat(graph): derive GraphSnapshot from aggregator".

#### Task 1.5a: CLI `flowscape replay`
**Files:**
- Create: `src/flowscape/cli.py` (skeleton), `tests/python/integration/test_pcap_to_snapshot.py`

**Steps:**
- [ ] Write failing integration test: replay `tests/fixtures/http-traffic.pcap` → assert `GraphSnapshot` has expected node count.
- [ ] Implement `flowscape replay <path>.pcap` CLI subcommand.
- [ ] Commit "feat(cli): flowscape replay command".

#### Task 1.5b: CLI `flowscape live`
**Files:**
- Modify: `src/flowscape/cli.py`, `src/flowscape/app.py` (minimal scaffold)

**Steps:**
- [ ] Write failing integration test: `flowscape live --interface lo0` prints snapshots within 1 s.
- [ ] Implement minimal `flowscape live` that prints snapshots to stdout.
- [ ] Implement `app.py` entrypoint loading Oneiric settings, wiring modules.
- [ ] Commit "feat(cli): flowscape live command + app.py entrypoint".

#### Task 1.6: Runtime redact helper
**Files:**
- Create: `src/flowscape/redact.py`, `tests/python/unit/test_redact.py`

**Steps:**
- [ ] Write failing test: `test_redact.py::test_strips_payload_keys_from_log_extra`.
- [ ] Implement `redact(extra: dict) -> dict`.
- [ ] Wire into Oneiric log filter (already set up in Task 0a.3).
- [ ] Add metric `flowscape.pii.redacted_total` counter.
- [ ] Commit "feat(redact): runtime PII redaction helper".

#### Task 1.7: Settings loader edge cases + runtime path resolution tests
**Files:**
- Create: `tests/python/integration/test_settings_loader_edge_cases.py`

**Steps:**
- [ ] Write failing tests: missing `local.yaml` tolerated, malformed YAML raises, env-var override wins over YAML, unknown field tolerated.
- [ ] Write parameterized test for `${platform_log_dir}` substitution: `.app`, wheel, Linux channels each resolve to expected path.
- [ ] Run — expect PASS.
- [ ] Commit "feat(test): settings loader edge case + platform_log_dir resolution tests".

#### Integration Contract — Phase1
- **Triggered from:** User runs `flowscape live` or `flowscape replay <pcap>` in a terminal.
- **Returns to / updates:** stdout receives `GraphSnapshot` JSON every 100 ms; capture errors via stderr.
- **Demonstrable by:** `flowscape replay tests/fixtures/http-traffic.pcap 2>&1 | jq '.nodes | length'` returns non-zero; `flowscape live --interface lo0` shows loopback traffic within 1 s.
- **Rollback signal:** Pipeline drops >50% of packets at <100 Mbps capture rate.
- **Observability added:** `flowscape.live.packets_per_sec`, `flowscape.live.dropped_packets_total`, `flowscape.pii.redacted_total`.

---

### Phase 2: IPC contract end-to-end + CI release workflow (1.5 weeks)

**Goal:** Python emits `GraphSnapshot` over data socket; stub Swift receiver decodes correctly. CI release workflow scaffolded.

#### Task 2.1: publisher.py with custom ring buffer
**Files:**
- Create: `src/flowscape/publisher.py`, `tests/python/unit/test_publisher.py`

**Steps:**
- [ ] Write failing tests: `test_drop_oldest_ring_buffer`; `test_alerts_bypass_ring_buffer`.
- [ ] Implement `SnapshotRingBuffer(maxsize=N)` (`collections.deque(maxlen=N)` + `threading.Lock`).
- [ ] Implement `Publisher`: reads from `SnapshotRingBuffer`, encodes as protobuf, sends over `data.sock` (SOCK_SEQPACKET).
- [ ] Implement 50 ms backpressure threshold via `asyncio.wait_for`.
- [ ] **Alerts bypass the ring buffer** — sent directly via `socket.send`.
- [ ] Wire `ps_drop` / `ps_ifdrop` into heartbeat.
- [ ] Use a `MockSocket` for unit tests that blocks `send()` deterministically; assert `dropped_snapshots >= 1` AND monotonic AND `surviving_snapshot.tick_id > dropped_snapshots[0].tick_id`.
- [ ] Commit "feat(publisher): data-plane publisher with drop-oldest ring buffer (alerts exempt)".

#### Task 2.2: ipc_server.py with JSON-RPC + SIGTERM escalation + Clock injection
**Files:**
- Create: `src/flowscape/ipc_server.py`, `src/flowscape/clock.py`, `tests/python/unit/test_ipc_server.py`, `tests/python/integration/test_handshake.py`, `tests/python/integration/test_heartbeat_liveness.py`

**Steps:**
- [ ] Write failing tests: handshake round-trip, version mismatch exits loudly, heartbeat emit-and-receive, SIGTERM/SIGKILL escalation ladder (2 s → SIGTERM → 5 s → SIGKILL), pause_capture / resume_capture methods.
- [ ] Implement `Clock` protocol (real + fake) for time injection. Tests advance the clock manually.
- [ ] Implement `IPCServer` on `control.sock` (SOCK_SEQPACKET): `bind()` + `listen()` + `accept()`. Stale socket cleanup before `bind()`.
- [ ] JSON-RPC 2.0 dispatcher with schema validation via `oneiric.actions.schema_validation`.
- [ ] Implement all methods listed in spec §"Control-plane methods" including `pause_capture` / `resume_capture`.
- [ ] Compile-time `NEGOTIATED_SCHEMA_MAJOR` extracted at codegen, asserted at module load.
- [ ] Implement heartbeat emission every 1 s + receive-and-track `client_ping`. Mark heartbeat compound test `@pytest.mark.slow` (uses Clock injection so PR CI doesn't hang).
- [ ] Implement bidirectional liveness detection (Python dead = 3 missed heartbeats AND no data.sock activity ≥5 s; Swift dead = 3 missed client_pings).
- [ ] Implement resync flow: emit `resync_required(from_tick)` on Swift request.
- [ ] Commit "feat(ipc): control-plane JSON-RPC server with handshake, heartbeat (Clock-injectable), resync, pause/resume".

#### Task 2.3: Swift stub receiver
**Files:**
- Create: `src/Flowscape/Stubs/StubReceiver.swift`, `Tests/FlowscapeTests/StubReceiverTests.swift`

**Steps:**
- [ ] Write failing test: `StubReceiverTests::test_decodes_written_snapshot`.
- [ ] Implement minimal `StubReceiver`: connects to `data.sock`, decodes one protobuf `GraphSnapshot`, asserts fields.
- [ ] Add Swift side of A4 binary equivalence check: Python emits + Swift decodes + assert byte equality.
- [ ] Commit "feat(swift): stub receiver for Python↔Swift smoke test".

#### Task 2.4: End-to-end smoke test + crash recovery + decoder rejects malformed
**Files:**
- Create: `scripts/smoke_capture.sh`, `tests/integration/test_smoke_capture.py`, `tests/integration/test_crash_recovery.py`

**Steps:**
- [ ] Write failing test: `test_smoke_capture.py::test_python_emits_swift_decodes`.
- [ ] Write failing test: `test_crash_recovery.py::test_kill_python_mid_run_assert_stale_socket_removed`. Mark `@pytest.mark.slow`.
- [ ] Write failing test: `test_decoder_rejects_malformed_protobuf_payload` (replaces the unreachable "half-written frame" test — SOCK_SEQPACKET preserves message boundaries, so defense-in-depth is the Swift decoder rejecting garbage).
- [ ] Implement `scripts/smoke_capture.sh`.
- [ ] Add to `.github/workflows/pr-checks.yml`.
- [ ] Commit "feat(test): end-to-end Python↔Swift smoke + crash recovery + malformed decoder test".

#### Task 2.6: CI release workflow (keychain + notarize + PyPI)
**Files:**
- Create: `.github/workflows/nightly.yml`, `.github/workflows/release.yml`

**Steps:**
- [ ] Write `nightly.yml`:
  ```yaml
  name: nightly
  on: { schedule: [{ cron: '0 4 * * *' }] }
  jobs:
    python:
      uses: ./.github/workflows/pr-python.yml
    swift:
      strategy:
        matrix: { runner: [macos-14, macos-15] }
        fail-fast: false
      runs-on: ${{ matrix.runner }}
      steps:
        - uses: actions/checkout@v4
        - run: swift test --sanitize=thread   # ThreadSanitizer catches TripleBuffer races
  ```
- [ ] Write `release.yml`:
  ```yaml
  name: release
  on:
    push: { tags: ['v*'] }
    workflow_dispatch:
      inputs: { tag: { description: 'Tag to publish', required: true } }
  permissions: read-all
  jobs:
    prepare-keychain:
      runs-on: macos-14
      outputs: { keychain-pass: ${{ steps.kc.outputs.pass }} }
      steps:
        - name: Create build keychain
          id: kc    # CRITICAL: this id is referenced by outputs.keychain-pass above
          env:
            KEYCHAIN_PASSWORD: ${{ secrets.KEYCHAIN_PASSWORD }}
            MACOS_CERT_P12: ${{ secrets.MACOS_CERT_P12 }}
            MACOS_CERT_P12_PASSWORD: ${{ secrets.MACOS_CERT_P12_PASSWORD }}
          run: |
            KEYCHAIN_PATH=$RUNNER_TEMP/build.keychain-db
            security create-keychain -p "$KEYCHAIN_PASSWORD" $KEYCHAIN_PATH
            security set-keychain-settings -lut 21600 $KEYCHAIN_PATH
            security unlock-keychain -p "$KEYCHAIN_PASSWORD" $KEYCHAIN_PATH
            echo "$MACOS_CERT_P12" | base64 --decode > $RUNNER_TEMP/cert.p12
            security import $RUNNER_TEMP/cert.p12 -P "$MACOS_CERT_P12_PASSWORD" \
              -A -t cert -f pkcs12 -k $KEYCHAIN_PATH
            security list-keychain -d user -s $KEYCHAIN_PATH
            security set-keychain-partition-list -S apple-tool:,apple: \
              -k "$KEYCHAIN_PASSWORD" $KEYCHAIN_PATH
            echo "pass=$KEYCHAIN_PASSWORD" >> $GITHUB_OUTPUT
      - name: Teardown
        if: always()
        run: security delete-keychain $RUNNER_TEMP/build.keychain-db || true
    build:
      needs: prepare-keychain
      runs-on: macos-14
      env: { KEYCHAIN_PASSWORD: ${{ needs.prepare-keychain.outputs.keychain-pass }} }
      steps:
        - uses: actions/checkout@v4
        - run: bash scripts/build_app.sh
        - run: codesign --force --options=runtime --sign "${{ secrets.DEVELOPER_ID_APPLICATION }}" Flowscape.app
        - run: codesign --verify --deep --strict --verbose=2 Flowscape.app
    notarize:
      needs: build
      runs-on: macos-14
      timeout-minutes: 90
      env: { KEYCHAIN_PASSWORD: ${{ needs.prepare-keychain.outputs.keychain-pass }} }
      steps:
        - uses: actions/download-artifact@v4
          with: { name: flowscape-app, path: dist/ }
        - name: Notarize
          env:
            APP_STORE_CONNECT_API_KEY_P8: ${{ secrets.APP_STORE_CONNECT_API_KEY_P8 }}
            APP_STORE_CONNECT_KEY_ID: ${{ secrets.APP_STORE_CONNECT_KEY_ID }}
            APP_STORE_CONNECT_ISSUER_ID: ${{ secrets.APP_STORE_CONNECT_ISSUER_ID }}
          run: xcrun notarytool submit dist/Flowscape.app --wait
        - name: Staple
          run: xcrun stapler staple dist/Flowscape.app && xcrun stapler validate dist/Flowscape.app
        - name: Inspect failures
          if: failure()
          run: |
            SUBMISSION_ID=$(xcrun notarytool history --output-format json | jq -r '.submissions[0].id')
            xcrun notarytool log "$SUBMISSION_ID"
    pypi:
      needs: notarize
      runs-on: ubuntu-latest
      environment: { name: pypi, url: https://pypi.org/p/flowscape }
      permissions: { id-token: write }
      steps:
        - uses: actions/download-artifact@v4
          with: { name: dist, path: dist/ }
        - uses: pypa/gh-action-pypi-publish@release/v1
          with: { packages-dir: dist/, skip-existing: true }
  ```
- [ ] Commit "feat(ci): nightly (with TSAN) + release workflows with keychain bootstrap, notarize timeout, PyPI OIDC".

#### Integration Contract — Phase2
- **Triggered from:** `scripts/smoke_capture.sh` invocation by CI or developer.
- **Returns to / updates:** Swift stub receives ≥10 `GraphSnapshot` frames within 3 s; release workflow ready.
- **Demonstrable by:** `bash scripts/smoke_capture.sh` exits 0.
- **Rollback signal:** Snapshot decode fails on Swift side, OR control-plane handshake times out 5 s.
- **Observability added:** `flowscape.ipc.bytes_sent_total`, `flowscape.ipc.dropped_snapshots_total`, `flowscape.ipc.handshake_duration_seconds`.

---

### Phase 3: Swift frontend basics + auto-respawn + single-instance (3 weeks)

#### Task 3.1: App.swift skeleton + consent gate
**Files:**
- Create: `src/Flowscape/App.swift`, `src/Flowscape/ConsentGate.swift`, `Tests/FlowscapeTests/ConsentGateTests.swift`

**Steps:**
- [ ] Write failing tests: `test_consent_required_on_first_launch`, `test_consent_button_disabled_for_5s`, `test_consent_persists_to_disk`, `test_consent_re_verified_on_interface_change`, `test_consent_re_verified_after_30_days`.
- [ ] Implement `ConsentGate` view: blocking modal with legal text.
- [ ] Store consent at `~/Library/Application Support/Flowscape/consent.json` (macOS convention; spec needs revision — see §6).
- [ ] Implement re-verification on interface change, SSID change, 30 days.
- [ ] Commit "feat(app): SwiftUI app shell with consent gate + re-verification".

#### Task 3.2: Sidebar.swift (with top-talkers + pause/resume buttons)
**Files:**
- Create: `src/Flowscape/Sidebar.swift`, `Tests/FlowscapeTests/SidebarTests.swift`

**Steps:**
- [ ] Write failing tests: `test_renders_capture_source_picker`, `test_renders_top_talkers`, `test_renders_alerts_list`, `test_pause_resume_button`.
- [ ] Implement `Sidebar` with capture controls, top-talkers list (top 10 hosts by bytes_in_window), pause/resume button, alerts list, status indicator.
- [ ] Use `@Observable` macro.
- [ ] Commit "feat(sidebar): capture controls + top-talkers + alerts + pause/resume".

#### Task 3.3a: IPCSocket actor (lifecycle + handshake)
**Files:**
- Create: `src/Flowscape/IPCSocket.swift` (actor skeleton), `Tests/FlowscapeTests/IPCSocketTests.swift`

**Steps:**
- [ ] Write failing tests: `test_actor_is_sendable`, `test_handshake_roundtrip`, `test_heartbeat_timeout_3_missed`, `test_data_sock_silence_5s_marks_python_dead`.
- [ ] Implement `IPCSocket` as `actor`; manages two `SOCK_SEQPACKET` Unix-domain sockets.
- [ ] Implement handshake protocol matching Python's `ipc_server.py`.
- [ ] Implement bidirectional heartbeat.
- [ ] Implement data-plane silence detection.
- [ ] Commit "feat(ipc): IPCSocket actor with handshake + bidirectional heartbeat".

#### Task 3.3b: IPCSocket JSON-RPC + partial-read state machine
**Files:**
- Modify: `src/Flowscape/IPCSocket.swift`
- Create: `Tests/FlowscapeTests/IPCSocketControlTests.swift`

**Steps:**
- [ ] Write failing test: `test_jsonrpc_request_notification_distinction`, `test_control_plane_partial_reads_reassembled`.
- [ ] Implement JSON-RPC 2.0 client (manual encoding/decoding, no third-party deps).
- [ ] Implement partial-read state machine for control plane (JSON-RPC; data plane is SOCK_SEQPACKET so message-boundary is preserved).
- [ ] Commit "feat(ipc): JSON-RPC types + partial-read state machine".

#### Task 3.4: SceneView.swift + MTKView + Renderer actor (CPU layout wired in Phase 4)
**Files:**
- Create: `src/Flowscape/SceneView.swift`, `src/Flowscape/Renderer/Renderer.swift`, `src/Flowscape/Renderer/PlaceholderRenderer.swift`, `Tests/FlowscapeTests/SceneViewTests.swift`, `Tests/FlowscapeTests/RendererActorTests.swift`

**Steps:**
- [ ] Write failing tests: `test_mtkview_creates_with_pinned_config`, `test_renderer_actor_is_sendable`.
- [ ] Define `NodeInstance` / `EdgeInstance` structs (concrete byte sizes for MTLBuffer allocation):
  ```swift
  struct NodeInstance {
      var position: SIMD3<Float>
      var color: SIMD4<Float>
      var scale: Float
      var _pad: SIMD4<Float>
  }
  // MemoryLayout<NodeInstance>.stride == 48 on Apple Silicon
  struct EdgeInstance {
      var src: SIMD3<Float>
      var dst: SIMD3<Float>
      var color: SIMD4<Float>
      var thickness: Float
  }
  ```
- [ ] Implement `Renderer` actor: owns the MTLBuffer pool (capacity = `max_nodes * 48 + max_edges * sizeof(EdgeInstance)`, allocated once at startup, never reallocated). MTKView delegate forwarding via `Task`.
- [ ] Implement `MTKView` configuration: `colorPixelFormat=.bgra10_xr_srgb`, `depthStencilPixelFormat=.depth32Float`, `sampleCount=4`, `enableSetNeedsDisplay=false`, `preferredFramesPerSecond` from settings.
- [ ] Implement `PlaceholderRenderer`: draws a wireframe triangle.
- [ ] Commit "feat(scene): MTKView with pinned config + Renderer actor + NodeInstance/EdgeInstance structs".

#### Task 3.5: JSON-RPC dispatcher + AlertModel
**Files:**
- Create: `src/Flowscape/JSONRPC.swift`, `src/Flowscape/AlertModel.swift`, `Tests/FlowscapeTests/JSONRPCTests.swift`

**Steps:**
- [ ] Write failing tests: `test_request_notification_distinction`, `test_alert_severity_levels`, `test_alert_ttl_expiration`.
- [ ] Implement `JSONRPC` types.
- [ ] Implement `AlertModel`: severity-aware, TTL-aware, dismissable.
- [ ] Commit "feat(ipc): JSON-RPC types + alert model".

#### Task 3.6: BackendLifecycle (auto-respawn)
**Files:**
- Create: `src/Flowscape/BackendLifecycle.swift`, `Tests/FlowscapeTests/BackendLifecycleTests.swift`

**Steps:**
- [ ] Write failing tests: `test_transient_failure_auto_respawns_once`, `test_transient_failure_second_time_shows_modal`, `test_permanent_failure_shows_modal_no_respawn`.
- [ ] Implement `BackendLifecycle`: distinguish transient (heartbeat lost + data.sock silent) from permanent (binary missing, dyld error, port in use). Auto-respawn once after 2 s on transient; show modal on second transient or any permanent.
- [ ] Commit "feat(app): BackendLifecycle with transient/permanent distinction + auto-respawn".

#### Task 3.7: Single-instance lockfile
**Files:**
- Create: `src/Flowscape/SingleInstance.swift`, `Tests/FlowscapeTests/SingleInstanceTests.swift`

**Steps:**
- [ ] Write failing test: `test_second_instance_exits_with_already_running`.
- [ ] Implement `SingleInstance`: `flock(LOCK_EX|LOCK_NB)` on `~/Library/Application Support/Flowscape/.lock`. On `EWOULDBLOCK`, exit with "Flowscape already running."
- [ ] Commit "feat(app): single-instance lockfile via flock".

#### Integration Contract — Phase3
- **Triggered from:** User opens `Flowscape.app` (consent modal first, then SwiftUI shell).
- **Returns to / updates:** UI shows consent gate → main window with sidebar (capture controls + top-talkers + pause/resume) + SceneView; second launch blocked by single-instance lock; backend lifecycle handles transient crashes.
- **Demonstrable by:** Open `.app`; consent modal blocks; ack shows SwiftUI shell with sidebar + triangle in SceneView; relaunch a second instance — exits "already running"; kill Python mid —Swift auto-respawns once; kill Python a second time — modal appears.
- **Rollback signal:** IPCSocket actor's handshake fails 3x consecutively (modal); SceneView crashes on Metal pipeline error (fallback to software renderer).
- **Observability added:** `flowscape.swift.handshake_duration_seconds`, `flowscape.swift.frame_render_duration_seconds`, `os_signpost` intervals.

---

### Phase 4: 3D renderer + CPU force-directed layout (5 weeks)

**Goal:** Real nodes and edges render with CPU force-directed layout. **Measurable DoD** (per spec Phase 4a): on `macos-14` M2 Pro, 1000 nodes + 5000 edges, `flowscape.render.frame_time_ms` **p99 ≤ 16 ms over 300 frames**. Capacity tests are `@pytest.mark.slow` and use p99 metric (not FPS), avoiding CI flake.

#### Task 4.1: CPU force-directed layout on DispatchQueue
**Files:**
- Create: `src/Flowscape/Layout/ForceDirectedLayout.swift`, `Tests/FlowscapeTests/LayoutTests.swift`, `Tests/FlowscapeTests/LayoutConvergenceTests.swift`

**Steps:**
- [ ] Write failing tests: `test_layout_runs_on_empty_graph`, `test_layout_converges_within_n_iterations`, `test_total_energy_decreases_monotonically`.
- [ ] Implement `ForceDirectedLayout` running on `DispatchQueue` at `.userInteractive` QoS.
- [ ] O(n²) repulsion + spring + damping per spec `LayoutSettings`.
- [ ] Initial positions seeded random-on-sphere, deterministic by SHA-256 of `HostNode.id`.
- [ ] Atomic swap of two `MTLBuffer` pointers for snapshot handoff to Renderer (no triple-buffer needed for CPU layout at ≤1000 nodes).
- [ ] Commit "feat(layout): CPU force-directed 3D layout with atomic MTLBuffer swap".

#### Task 4.2: NodeRenderer (instanced spheres, 10k-node capacity)
**Files:**
- Create: `src/Flowscape/Renderer/NodeRenderer.swift`, `Tests/FlowscapeTests/NodeRendererTests.swift`

**Steps:**
- [ ] Write failing test: `test_renders_10000_nodes_p99_under_16ms` (marked `@pytest.mark.slow`; excluded from PR).
- [ ] Implement `MTLRenderPipelineState` for instanced spheres.
- [ ] Node color from `RenderSettings.protocol_colors`.
- [ ] Commit "feat(renderer): instanced sphere rendering at 10k-node capacity".

#### Task 4.3: EdgeRenderer (instanced lines, 50k-edge capacity)
**Files:**
- Create: `src/Flowscape/Renderer/EdgeRenderer.swift`, `Tests/FlowscapeTests/EdgeRendererTests.swift`

**Steps:**
- [ ] Write failing test: `test_renders_50000_edges_p99_under_16ms` (marked `@pytest.mark.slow`).
- [ ] Implement instanced line-segment rendering for edges (cylinder quads).
- [ ] Edge thickness scales with `bytes` (clamped); color from sender's protocol.
- [ ] Commit "feat(renderer): instanced edge rendering at 50k-edge capacity".

#### Task 4.4: Camera controls + SceneFilter
**Files:**
- Create: `src/Flowscape/Renderer/CameraController.swift`, `src/Flowscape/Renderer/SceneFilter.swift`, `Tests/FlowscapeTests/CameraControllerTests.swift`

**Steps:**
- [ ] Write failing tests: `test_orbit_around_origin`, `test_zoom_clamped`, `test_protocol_filter_hides_nodes`.
- [ ] Implement orbit + zoom; `NSPanGestureRecognizer` and scroll wheel.
- [ ] Implement per-protocol visibility toggles.
- [ ] Commit "feat(renderer): orbit camera + zoom clamp + in-scene filtering".

#### Task 4.5: Picking (click/hover for host inspection)
**Files:**
- Create: `src/Flowscape/Renderer/Picking.swift`, `Tests/FlowscapeTests/PickingTests.swift`

**Steps:**
- [ ] Write failing tests: `test_click_returns_node_id`, `test_hover_highlights_node`.
- [ ] Implement GPU picking + CPU ray-against-bounding-sphere fallback.
- [ ] Commit "feat(renderer): click/hover picking".

#### Integration Contract — Phase4
- **Triggered from:** Phase 3's SceneView with `PlaceholderRenderer` is live; Python's `flowscape live` is emitting.
- **Returns to / updates:** SceneView shows real graph with CPU force-directed layout; frame time p99 ≤ 16 ms at 1000 nodes.
- **Demonstrable by:** `flowscape live --interface lo0` + open `.app`; see ≥50 nodes; capacity tests show p99 ≤ 16 ms at 10k nodes (nightly).
- **Rollback signal:** Frame time > 16 ms sustained for 10 s on 1000-node workload (user sees stutter).
- **Observability added:** `flowscape.render.frame_time_ms` histogram, `flowscape.layout.iterations_per_frame`, `OSSignposter` interval `flowscape.frame.draw`.

---

### Phase 5: Heuristics + interaction + Etherape-shaped panels (3 weeks)

**Goal:** Two statistical heuristics (beaconing, port-scan), top-talkers + conversation panels, click/hover picking + filtering.

#### Task 5.1: Heuristics implementation (2 detectors — port-scan + beaconing)
**Files:**
- Create: `src/flowscape/heuristics.py`, `tests/python/property/test_heuristics.py`, `tests/python/integration/test_heuristics_fixtures.py`

**Steps:**
- [ ] Write failing property tests: `test_beaconing_with_20pct_jitter_fires`, `test_port_scan_syn_burst_fires`.
- [ ] Implement `BeaconingDetector` (jitter 20% slow-window periodicity).
- [ ] Implement `PortScanDetector` (SYN packets/sec + distinct dst ports; vertical/horizontal distinction).
- [ ] Wire heuristic alerts to `publisher.py` data plane (single channel).
- [ ] **Top-N-churn deferred to v1.1** (was in earlier plan; removed per product-manager).
- [ ] Commit "feat(heuristics): beaconing + port-scan".

#### Task 5.2: Heuristic corpus + corpus-tuning test
**Files:**
- Modify: `scripts/gen_pcap_fixtures.py` (add port-scan, beaconing, benign ARP-heavy, benign mDNS, benign HTTP-only)
- Create: `tests/python/integration/test_heuristics_negative_corpus.py`

**Steps:**
- [ ] Add benign fixtures: ARP-heavy LAN, mDNS bursts, HTTP-only traffic, DNS bursts.
- [ ] Write failing test: `test_port_scan_pcap_yields_alert` AND `test_arp_heavy_pcap_yields_no_alert` **in the same pytest session** — if both fail together, it's a threshold-tuning problem.
- [ ] Use `time` injection in heuristics so window advancement can be tested without `asyncio.sleep`.
- [ ] Mark test `@pytest.mark.slow` (replays take time).
- [ ] Run — expect PASS.
- [ ] Commit "feat(heuristics): corpus-tuning test that runs positive + negative together".

#### Task 5.3: Top-talkers panel
**Files:**
- Create: `src/Flowscape/UI/TopTalkersPanel.swift`, `Tests/FlowscapeTests/TopTalkersPanelTests.swift`

**Steps:**
- [ ] Write failing tests: `test_renders_top_10_by_bytes_in_window`, `test_refreshes_on_snapshot`.
- [ ] Implement `TopTalkersPanel`: reads `GraphSnapshot.nodes`, sorts by `bytes_in_window` desc, renders sidebar list with host label + bytes.
- [ ] Refresh on each snapshot (max once per 100 ms).
- [ ] Commit "feat(ui): top-talkers panel (top 10 hosts by bytes-in-window)".

#### Task 5.4: Conversation table
**Files:**
- Create: `src/Flowscape/UI/ConversationTable.swift`, `Tests/FlowscapeTests/ConversationTableTests.swift`

**Steps:**
- [ ] Write failing tests: `test_renders_active_flows`, `test_click_row_filters_scene_to_that_flow`.
- [ ] Implement `ConversationTable`: reads `GraphSnapshot.edges`, renders sidebar table (src → dst, protocol, port, bytes, packets).
- [ ] Click row → `SceneFilter` highlights that flow.
- [ ] Commit "feat(ui): conversation table (sidebar, click-to-filter)".

#### Integration Contract — Phase5
- **Triggered from:** Phase 4's renderer is live; Python emitting snapshots.
- **Returns to / updates:** Alerts in sidebar; top-talkers + conversation panels populated; click a host → see its protocol breakdown; click a conversation → scene filters.
- **Demonstrable by:** Replay `tests/fixtures/port-scan.pcap` → see `PORT_SCAN` alert within 5 s; click a node → sidebar shows protocol breakdown; replay `tests/fixtures/arp-heavy.pcap` → zero alerts.
- **Rollback signal:** False-positive rate >10% on negative corpus OR recall <90% on positive corpus.
- **Observability added:** `flowscape.heuristic.alerts_total{kind=...}`, `flowscape.interaction.host_selections_total`, `flowscape.interaction.filter_applies_total`.

---

### Phase 6a: Distribution — launchd helper (1 week, after Phase 3)

**Goal:** `/dev/bpf*` accessible to console user via privileged XPC helper. Helper does **NOT stay resident**.

#### Task 6a.1: Helper Xcode target
**Files:**
- Create: `Helper/Package.swift`, `Helper/Sources/FlowscapeHelper/main.swift`, `Helper/Sources/FlowscapeHelper/Info.plist`

**Steps:**
- [ ] Create helper as a launchd-on-demand XPC service (modern helper API; NOT SMJobBless).
- [ ] Bundle ID: `com.lesleslie.flowscape.helper`.
- [ ] Implement single method `install_helper()`: sets `/dev/bpf*` ACLs.
- [ ] Helper exits after `install_helper()` returns. launchd re-launches on demand.
- [ ] Code-sign with same Apple Developer ID; `codesign -dvv` assert same TeamIdentifier.
- [ ] Commit "feat(helper): XPC launchd-on-demand helper for /dev/bpf* ACLs (not resident)".

#### Task 6a.2: CLI hook
**Files:**
- Create: `src/flowscape/helper_install.py`, `tests/python/unit/test_helper_install.py`

**Steps:**
- [ ] Write failing test: `test_helper_install.py::test_invokes_helper_with_right_bundle_id`.
- [ ] Implement `flowscape doctor --install-helper` that invokes the helper via XPC.
- [ ] Verify post-install by attempting `pcap_open`; on `EACCES`, surface "Helper needs reinstall."
- [ ] Commit "feat(cli): flowscape doctor --install-helper command".

#### Task 6a.3: Homebrew caveats + helper distribution decision
**Files:**
- Create (in `les/homebrew-tap`): `Formula/flowscape.rb`
- Create: `docs/distribution/helper-distribution.md`

**Steps:**
- [ ] Author formula using `virtualenv_install_with_resources`.
- [ ] Add `def caveats` block (NOT `post_install` — brew 4.0+ runs post_install as build user, not root):
  ```ruby
  def caveats
    <<~EOS
      Flowscape requires a one-time privileged helper installation
      to grant your user access to /dev/bpf* (packet capture devices).

      After install, run:
        sudo flowscape doctor --install-helper
    EOS
  end
  ```
- [ ] Run `brew audit --new flowscape` against the formula locally.
- [ ] Document: helper ships only inside `.app` (Phase 6b). Homebrew users run `sudo flowscape doctor --install-helper`. PyPI users get CLI without live capture.
- [ ] Commit "feat(brew): Homebrew formula with caveats + helper distribution decision".

#### Integration Contract — Phase6a
- **Triggered from:** `brew install les/tap/flowscape` (caveats) OR `flowscape doctor --install-helper` (manual).
- **Returns to / updates:** `/dev/bpf*` ACLs allow console user read; `pcap_open` succeeds.
- **Demonstrable by:** `brew install les/tap/flowscape && sudo flowscape doctor --install-helper && flowscape live --interface en0`.
- **Rollback signal:** Helper exits non-zero; `flowscape doctor` reports failure.
- **Observability added:** `flowscape.helper.install_duration_seconds`, `flowscape.helper.last_installed_at`.

---

### Phase 6b-PyPI: Distribution — PyPI + Homebrew tap + unsigned `.app` + bundle docs (1 week)

**Goal:** `pip install flowscape` works; `brew install les/tap/flowscape` works; unsigned `.app` available.

#### Task 6b-PyPI.1: py2app pipeline (with 3.14 fallback)
**Files:**
- Modify: `pyproject.toml` (add `[tool.py2app]` section)
- Create: `src/flowscape_launcher.py` (entry point for `.app`)

**Steps:**
- [ ] Verify py2app supports Python 3.14 (release notes). If not, use `briefcase` (BeeWare) as fallback.
- [ ] Implement `flowscape_launcher.py`: imports `flowscape.app`, calls main.
- [ ] Configure py2app: bundle ID, plist with `NSPrivacyNetworkUsageDescription`, includes for `dpkt`, `numpy`, `betterproto2`, `orjson`.
- [ ] Verify `python -m py2app` produces a runnable `Flowscape.app`.
- [ ] Commit "feat(dist): py2app pipeline + launcher module".

#### Task 6b-PyPI.2: Bundle LEGAL + SECURITY + GDPR posture (moved from Phase 7)
**Files:**
- Create: `SECURITY.md`, `LEGAL.md`, `docs/legal/gdpr-posture.md`

**Steps:**
- [ ] Author `SECURITY.md` with threat model + reporting.
- [ ] Author `LEGAL.md` with per-jurisdiction disclaimers.
- [ ] Author `docs/legal/gdpr-posture.md` per spec.
- [ ] Configure py2app to bundle them in `Flowscape.app/Contents/Resources/`.
- [ ] Commit "feat(dist): SECURITY.md + LEGAL.md + GDPR posture in bundle".

#### Task 6b-PyPI.3: PrivacyInfo.xcprivacy
**Files:**
- Create: `PrivacyInfo.xcprivacy`

**Steps:**
- [ ] Generate `PrivacyInfo.xcprivacy` declaring no tracking, no data collection.
- [ ] Configure py2app to include `NSPrivacyNetworkUsageDescription`.
- [ ] Commit "feat(dist): privacy manifest + Info.plist privacy strings".

#### Task 6b-PyPI.4: PyPI publish via trusted publishing + Homebrew PR
**Steps:**
- [ ] Verify PyPI project `flowscape` exists (trademark check done in Phase 0a).
- [ ] Verify trusted publisher config registered on PyPI.
- [ ] Push tag `v0.1.0`; release workflow fires.
- [ ] PyPI publish via OIDC (the `pypi` job).
- [ ] Homebrew tap PR (separate repo; uses `HOMEBREW_TAP_TOKEN` PAT).
- [ ] Commit (in homebrew-tap) "feat(brew): flowscape 0.1.0 formula".

#### Integration Contract — Phase6b-PyPI
- **Triggered from:** GitHub Actions release workflow on tagged commit.
- **Returns to / updates:** `pip install flowscape` works; `brew install les/tap/flowscape` works; unsigned `.app` available.
- **Demonstrable by:** Fresh venv: `pip install flowscape && flowscape live --interface lo0`; fresh macOS: `brew install les/tap/flowscape`.
- **Rollback signal:** PyPI publish fails — workflow refuses to publish; previous version remains on PyPI.
- **Observability added:** PyPI download stats via pypistats.org; Homebrew installs via `brew info`.

---

### Phase 6b-Notarized: Codesign + notarize (1-3 weeks, conditional on Apple ID)

**Goal:** Signed, notarized `Flowscape.app` is distributable.

#### Task 6b-Notarized.1: Codesign iteration (3 retries expected)
**Steps:**
- [ ] Run `codesign --force --options=runtime --sign "$DEVELOPER_ID_APPLICATION" Flowscape.app`.
- [ ] Verify: `codesign --verify --deep --strict --verbose=2 Flowscape.app`.
- [ ] If reject, fix root cause; retry up to 3 times.
- [ ] If all fail or Apple escalates to manual review, ship unsigned `.app` for v1.0.0-rc and codesigned v1.0.0 separately.
- [ ] Commit "feat(dist): codesign iteration with retry-class counters".

#### Task 6b-Notarized.2: Notarize + staple
**Steps:**
- [ ] Submit via `xcrun notarytool submit Flowscape.app --wait` (timeout: 90 min in workflow).
- [ ] Inspect failures via `xcrun notarytool log <id>`.
- [ ] Staple: `xcrun stapler staple Flowscape.app`; verify: `xcrun stapler validate Flowscape.app`.
- [ ] Commit "feat(dist): notarize + staple in release pipeline".

#### Integration Contract — Phase6b-Notarized
- **Triggered from:** Apple Developer ID arrived; Phase 6b-PyPI shipped v1.0.0.
- **Returns to / updates:** Signed, notarized `Flowscape.app` attached as v1.0.1.
- **Demonstrable by:** Download signed `.app`; open it; `spctl --assess` returns "accepted".
- **Rollback signal:** Notarization webhook returns Invalid 3 times → fall back to unsigned.
- **Observability added:** Notarization status in release workflow logs.

---

### Phase 7a: UX polish (0.5 week, parallel with 6b)

**Goal:** Minimal Settings UI + trimmed error UX (3 modals + 5 banners + generic widget).

#### Task 7a.1: Minimal Settings UI (3-4 settings + YAML editor)
**Files:**
- Create: `src/Flowscape/SettingsView.swift`, `Tests/FlowscapeTests/SettingsViewTests.swift`

**Steps:**
- [ ] Write failing test: `test_renders_interface_picker_bpf_filter_target_fps`.
- [ ] Implement minimal `SettingsView`: interface picker, BPF filter text field, target FPS, background color picker.
- [ ] For all other settings: `flowscape config` opens `settings/flowscape.yaml` in `$EDITOR`.
- [ ] Commit "feat(ui): minimal settings UI (3-4 settings) + raw YAML editor".

#### Task 7a.2: Menu bar items + error UX (trimmed)
**Files:**
- Modify: `src/Flowscape/Sidebar.swift`

**Steps:**
- [ ] Add menu items: Start/Stop Capture, Pause/Resume, Replay Pcap..., Doctor, About.
- [ ] Implement 3 modals: auto-respawn second failure (Error #5), Python spawn failure (Error #6), version mismatch (Error #12).
- [ ] Implement 5 most-visible banners: capture-permission (Error #1), interface disappeared (Error #3), pcap corrupt (Error #4), TCP failure (Error #13), heuristic false positives (Error #16).
- [ ] Implement generic `ErrorBanner(type, message)` widget for the remaining 14 error rows (per spec error-handling table).
- [ ] Commit "feat(ui): menu bar items + 3 modals + 5 banners + generic error widget".

#### Integration Contract — Phase7a
- **Triggered from:** Phase 6b-PyPI shipped; user is interacting with the app.
- **Returns to / updates:** Settings, menu, error UX live.
- **Demonstrable by:** Open Settings — see interface picker + BPF filter + target FPS; trigger capture failure — see appropriate modal/banner; run `flowscape config` — see YAML in editor.
- **Rollback signal:** User feedback indicates major UX gap.
- **Observability added:** Settings change events; error banner impression count.

---

### Phase 7b: README + MCP deferred decision (0.5 week, parallel with 6b)

**Goal:** README covers v1 walkthrough; MCP activation explicitly deferred.

#### Task 7b.1: README
**Files:** Modify: `README.md`

**Steps:**
- [ ] Author README with consent text at top (per spec §"Disclaimer docs").
- [ ] Cover: install, first-launch consent, `flowscape live`, `flowscape replay`, `flowscape doctor`, settings, FAQ.
- [ ] Ships at end of Phase 5b (handoff to other developers).
- [ ] Commit "feat(docs): README".

#### Task 7b.2: MCP deferred decision note
**Files:**
- Create: `.claude/decisions/mcp-activation-deferred.md`

**Steps:**
- [ ] Write 4-line "deferred decision" note: MCP activation requires ADR + DPIA + CONTRIBUTING update; `mcp.enabled` stays `false`; no UI affordance to flip it; revisit when legal review starts.
- [ ] Commit "feat(docs): MCP activation deferred decision note".

#### Integration Contract — Phase7b
- **Triggered from:** Phase 5b ships (README) and Phase 6b-PyPI ships (MCP note).
- **Returns to / updates:** Documentation complete; MCP gated.
- **Demonstrable by:** Fresh macOS user can install + launch + capture + configure + understand errors via README.
- **Rollback signal:** User feedback indicates major doc gap.
- **Observability added:** None (docs phase).

---

## 6. Spec Reconciliation Note

This plan revision4 incorporates findings from three review rounds. **Three items are spec-vs-plan inconsistencies that the user should know about:**

1. **Consent file path:** Plan stores at `~/Library/Application Support/Flowscape/consent.json` (macOS convention); spec stores at `~/.flowscape/consent.json` (XDG-style). **Recommendation:** use macOS convention; spec should be updated to match.

2. **`assert` in `_check_bounds`:** Spec example uses `assert a < b`; Bodai CLAUDE.md mandates `raise ValueError(...)`. Plan uses `ValueError`; spec example should be updated.

3. **`Flowscape.xcodeproj` per spec P3:** Spec says Phase 0 scaffolds `Flowscape.xcodeproj`. Plan uses SPM-only (no `.xcodeproj` separately). This is a deliberate deviation — SPM-only works for `swift build` + Xcode-as-editor; a separate `.xcodeproj` is unnecessary for v1.

## 7. Validation Matrix

| Stage | Tool / Command | Expected outcome | Evidence location |
|---|---|---|---|
| After Phase 0a | `uv sync --group dev` | succeeds | CI logs |
| After Phase 0a | `swift build && swift test` | succeeds | CI logs |
| After Phase 0a | `pip install -e .` in fresh venv | succeeds; `flowscape version` returns "0.1.0.dev0" | Local + CI |
| After Phase 0b | `bash scripts/gen_proto.sh` | succeeds; Python + Swift types generated | CI logs |
| After Phase 0b | actor spike test passes | Swift 6 actor pattern viable | CI logs |
| After Phase 1 | `pytest tests/python/ -v` | all pass at 89% coverage (capture.py excluded) | CI logs |
| After Phase 1 | `flowscape replay tests/fixtures/http-traffic.pcap` | JSON to stdout | Manual + smoke |
| After Phase 2 | `bash scripts/smoke_capture.sh` | exit 0; ≥10 snapshots received | CI logs |
| After Phase 2 | crash recovery test | passes | CI logs |
| After Phase 3 | `swift test` | all pass; Swift 6 strict concurrency | CI logs |
| After Phase 3 | second-launch blocked by single-instance lock | passes | Manual |
| After Phase 3 | kill-Python-twice modal | passes | Manual |
| After Phase 4 | frame time p99 ≤ 16 ms (1000 nodes, 5000 edges) | histogram in PR | CI artifacts |
| After Phase 4 | TSAN nightly (TripleBuffer races) | no races | Nightly logs |
| After Phase 5 | replay port-scan.pcap → PORT_SCAN alert | passes | CI logs |
| After Phase 5 | replay benign corpus → zero alerts | passes | CI logs |
| After Phase 5 | corpus-tuning test passes | passes | CI logs |
| After Phase 6a | `flowscape doctor --install-helper` works | ACL set | Manual |
| After Phase 6b-PyPI | `pip install flowscape` | works | pip install |
| After Phase 6b-PyPI | `brew install les/tap/flowscape` | works; caveats shown | Manual |
| After Phase 6b-Notarized | `spctl --assess --type install Flowscape.app` | "accepted" | Release workflow |
| After Phase 7a | `flowscape config` opens YAML in $EDITOR | works | Manual |
| After Phase 7b | README walkthrough end-to-end | works | Manual |

## 8. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Apple Developer ID procurement delays >3 weeks | High | Apple-ID contingency tree: ship wheel-only v1; notarized `.app` ships v1.0.1. |
| Notarization iteration (3+ rejections) | Medium | Pre-flight checks (`codesign --verify --deep --strict`); max 3 retries; fall back to unsigned. |
| `pcapy-ng` Python 3.14 wheels unavailable | Medium | Real ctypes fallback (`LibpcapCtypesCapture`) implemented, not just clear error. |
| Swift 6 strict concurrency reveals actor isolation issues | Medium | Phase 0b spike de-risks; fallback to Swift 5 mode documented. |
| CPU layout doesn't hit p99 ≤ 16 ms at 1000 nodes | Low-Medium | Mark `@pytest.mark.slow`; nightly capacity tests; degrade gracefully (lower node count → still useful). |
| Heuristic false positives on real traffic | Medium | Negative corpus required (Task 5.2); corpus-tuning test runs both directions together. |
| `py2app` Python 3.14 support | Low-Medium | Fallback to `briefcase` (BeeWare). |
| Coverage 89% overall fails despite per-module 70%/85% gates | Low | `capture.py` excluded from overall denominator; per-file gate enforced separately. |
| Single dev unavailable mid-project | Medium | README ships at end of Phase 5b; handoff protocol in `CONTRIBUTING.md`. |
| Helper distribution confusion | Medium | `docs/distribution/helper-distribution.md` documents the decision. |
| `--cov-fail-under=89` CI flakes in Phase 7 | Low | Capture.py excluded from denominator; per-file gates validated separately. |

## 9. Decision Rule

**This plan is "done enough" to ship v1 when:**
1. All phases complete with their Integration Contracts satisfied.
2. `bash scripts/smoke_capture.sh` passes on a fresh macos-14 runner.
3. `flowscape live --interface en0` works without sudo (after `sudo flowscape doctor --install-helper`).
4. `flowscape live --interface lo0` works after `brew install les/tap/flowscape` (or `pip install flowscape`).
5. Test coverage: 89% Python overall (capture.py excluded), 85% per-module on core modules, 70% Swift overall.
6. License audit (`pip-licenses --fail-on="GPL;LGPL;AGPL"`) passes.
7. No PII log statements (CI gates pass); runtime redact filter fires only when expected.
8. Documentation: README, SECURITY.md, LEGAL.md, GDPR posture document all present in bundle.

**When scope pressure forces a cut:**
1. Heuristic precision tuning (ship with v1 thresholds; improve in v1.x patches).
2. In-scene filter (ship only protocol hide; keep click-to-filter from conversation table).
3. macos-15 fallback runner matrix (single runner for v1).
4. The remaining 14 error rows beyond the 5 banners (rely on generic widget).

**The cut preserves:**
- Two `SOCK_SEQPACKET` sockets with `.proto` single source of truth.
- Swift 6 actor model + structural no-payload + active consent gate.
- Launchd helper for `/dev/bpf*` ACL (non-resident).
- Crackerjack quality gates at 89%.
- BSD-3 license + clean dep tree.
- LICENSE.md / SECURITY.md in bundle (regulatory requirement).
- Top-talkers + conversation panels (Etherape-shaped core UX).

**Apple ID contingency:** if Developer ID arrives by end of Phase 6b-PyPI, Phase 6b-Notarized ships notarized `.app` in v1.0.1. If not, PyPI + Homebrew ship v1.0.0; notarized `.app` ships v1.0.1 with no scope reduction elsewhere.