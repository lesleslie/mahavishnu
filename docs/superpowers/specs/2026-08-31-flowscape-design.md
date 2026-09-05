# flowscape — Modern Network Visualization for macOS

**Status:** Revision 2 — incorporates Tier-1 fixes from 8-agent multi-agent review (2026-08-31)
**Date:** 2026-08-31
**Author:** Claude (brainstorming session)
**Scope:** v1 design — full repo, end-to-end architecture, IPC contract, distribution plan

______________________________________________________________________

## Context

Etherape (https://etherape.sourceforge.io/, GPLv2, unmaintained since 2015) is the canonical macOS/Linux network visualization tool: live packet capture, hosts as nodes, flows as edges, force-directed layout, color-by-protocol. Its visual model is iconic. Its implementation is stuck in GTK2-era C and Python2-era Python.

We want a modern Etherape-shaped tool, modernized where it makes sense, faithful where it doesn't.

**Three non-negotiables:**

1. **macOS-only, signed `.app` bundle.** Distribution target.
1. **3D rendering as a headline feature.** The "next-gen" angle.
1. **Structural no-payload guarantee.** The wire format cannot carry packet payload bytes. This is an architectural commitment, not a behavioral claim — see [Architectural invariants](#architectural-invariants) #4.

**macOS permission model is a real constraint.** `/dev/bpf*` access is not grantable through System Settings; the spec commits to a specific distribution strategy that works without Apple-granted entitlements — see [Distribution & packaging](#distribution--packaging).

**What we are NOT doing:** studying Etherape's source code. Its GPLv2 license makes any close re-implementation derivative work. We'll work from screenshots, documentation, and feature descriptions only. A formal clean-room protocol (see [Licensing](#licensing)) keeps the team honest about which contributors have prior knowledge of Etherape internals.

______________________________________________________________________

## Goals

1. **Modern Etherape replacement** — same core UX (live packet capture, host/flow graph, protocol coloring, pause/resume, pcap file replay) with a modern stack and prettier rendering.
1. **3D interactive scene** — orbit camera, click-a-host, hover-to-inspect, in-scene filtering. The headline differentiator.
1. **SwiftUI + Metal on macOS** — native, sandbox-friendly, fast. Swift 6 strict concurrency throughout.
1. **Python backend** — `dpkt` for parsing, `pcapy-ng` (with ctypes fallback) for live capture, numpy where helpful, Oneiric for config.
1. **Single source of truth for IPC** — `.proto` files generating both Python (betterproto2) and Swift (SwiftProtobuf) types via two `SOCK_SEQPACKET` Unix-domain sockets (one for data, one for control).
1. **Multi-channel distribution** — `pip install flowscape`, `uvx flowscape`, `brew install les/tap/flowscape`, signed `.app` bundle with launchd helper for `/dev/bpf*` ACL.
1. **Heuristics for live traffic patterns** — beaconing, port-scan, top-N churn. v1 versions are simple statistical detectors with realistic thresholds (see [Out of scope](#out-of-scope--future-work) for ML deferral).
1. **Structural no-payload guarantee** — packet bytes never leave the capture process. Wire format carries metadata + a 32-byte SHA-256 prefix per edge; no payload bytes, period.

## Non-Goals

- **Time scrubber / historical replay** — out of scope for v1. Buffered graph state is a v2 feature.
- **Drill-down side panels** (top talkers, conversation table) — out of scope for v1.
- **Cross-platform GUI** — Linux/Windows users use the Python backend headless or tcpdump. macOS-first.
- **ML-based anomaly detection** — only simple statistical heuristics in v1.
- **Cloud / SaaS integration** — NetFlow, sFlow, OpenTelemetry, VPC flow logs are v2+.
- **MCP server features** — `mcp-common` is included; activation is gated on legal review (see [Future scope](#future-scope)).
- **Etherape source study** — explicitly forbidden. Clean-room protocol documented in `CONTRIBUTING.md`.
- **TLS SNI extraction / QUIC ClientHello parsing** — would be a "modernized" differentiator but multi-week research; deferred to v2.
- **MAC/OUI bundling** — IEEE OUI file (5MB) deferred to v2; v1 shows raw MAC only.
- **Network Extensions entitlement** — Apple's NE PacketInspectorProvider path is not pursued in v1 (see [Distribution](#distribution--packaging) for the v1 strategy).

______________________________________________________________________

## Architecture

### High-level: two processes, one bundle

```
┌─────────────────────────────────────────────────────────────────┐
│  Flowscape.app (signed, notarized, ~30 MB)                       │
│                                                                 │
│  ┌──────────────────────┐    Two Unix-domain sockets    ┌──────┐ │
│  │  Swift Frontend      │◄──────────SOCK_SEQPACKET────►│ Py.  │ │
│  │  (SwiftUI + MTKView) │  data.sock (protobuf)        │Back. │ │
│  │                      │  control.sock (JSON-RPC)     │      │ │
│  │  • 3D scene          │                              │ • pc │ │
│  │  • sidebar / prefs   │                              │ • dp │ │
│  │  • IPC actors        │                              │ • ag │ │
│  │  • layout (Swift)    │                              │ • he │ │
│  └──────────────────────┘                              └──┬───┘ │
│         │                                                  │      │
│         ▼                                                  ▼      │
│      Metal GPU                                       libpcap       │
│      (MTKView)                                                   │
└─────────────────────────────────────────────────────────────────┘
```

The Swift app spawns the embedded Python at launch. **Two SOCK_SEQPACKET Unix-domain sockets** — one for the data plane (protobuf `GraphSnapshot` and `Alert`), one for the control plane (JSON-RPC 2.0). SOCK_SEQPACKET preserves message boundaries, so no in-stream framing or tag bytes are needed.

### Architectural invariants

1. **Two-process split is the default.** Swift owns GPU and UI loop; Python owns capture, decode, aggregation, heuristics. Crossing the process boundary lets each side use its strongest tooling without GIL contention. **Collapse only with measurement and a written justification.**

1. **`.proto` is the IPC contract's single source of truth.** Both Python (`betterproto2`) and Swift (`SwiftProtobuf`) generate types from `proto/flowscape.proto`. Drift is impossible. A CI check diffs regenerated files against committed copies.

1. **Layout lives in Swift.** Python publishes graph *state*; Swift decides *where they go*. Layout runs on a dedicated `DispatchQueue` (QoS `.userInteractive`) producing positions into a triple-buffer; the render thread picks up the newest at frame start. Decoupling IPC is the layout budget.

1. **Structural no-payload guarantee.** The wire format cannot carry packet payload bytes. `FlowEdge` exposes a `payload_sha256_prefix` (32 bytes) as the *only* payload-derived field allowed; this is computed by `decode.py` and the source buffer is zeroed immediately after hashing. CI lints for protobuf field names containing `payload`, `body`, `raw`, etc. (regex enforcement) and a runtime Oneiric log filter drops any record whose `extra` dict contains payload-shaped keys.

1. **Latest-wins backpressure on the data plane.** If Python's `socket.send` blocks for >50 ms (kernel buffer full), Python discards the *currently-prepared* `GraphSnapshot` and resumes on the next tick. Drop count is exposed via heartbeat. Control-plane alerts are exempt from the drop policy.

1. **Active consent gate.** On first launch (and on interface or SSID change, or after 30 days), the Swift app shows a blocking modal: "Confirm you own or are authorized to monitor this network. Unauthorized packet capture may violate federal law (18 U.S.C. §§ 2511, 1030) and state wiretap statutes." Acknowledge button disabled for 5 s to prevent misclick. Stored consent (`~/.flowscape/consent.json`) records timestamp + hashed network identifier.

1. **No GPL/LGPL in our dep tree.** All direct deps are permissively licensed (BSD, MIT, Apache-2.0). `dpkt` for parsing, `pcapy-ng` for live capture, `betterproto2` (MIT), `protobuf` (BSD-3), `libpcap` (BSD), `py2app` (MIT), `SwiftProtobuf` (Apache-2.0). Verified in CI via `pip-licenses --fail-on="GPL;LGPL;AGPL"`.

1. **Swift 6 strict concurrency from day one.** IPCSocket is an `actor`. Renderer is an `actor` (MTKView's delegate methods forward to it via `Task`). LayoutState is a `Sendable` struct with copy-on-write positions, triple-buffered across frames-in-flight. No `@unchecked Sendable` escapes.

### Repo placement

Fresh repo at `/Users/les/Projects/flowscape` (GitLab private; GitHub public option later). Bodai-maintained but not Bodai-core. Follows Bodai conventions (Oneiric config, crackerjack quality gates, PEP 735 optional dep groups).

______________________________________________________________________

## Subsystems

### Python backend (`src/flowscape/` package)

| Module | Purpose | LOC est. |
|---|---|---|
| `settings.py` | Oneiric settings model (Pydantic), `FlowscapeSettings(MCPServerSettings)`. Uses `oneiric.config.load_app_settings`. | 150 |
| `capture.py` | Owns the pcap source via `pcapy-ng` (with ctypes fallback if wheels unavailable). Dedicated `pcap_thread` runs `pcap_loop` synchronously, posts packets to the asyncio loop via `loop.call_soon_threadsafe`. Emits raw packets on an asyncio queue. Implements `CaptureSource` ABC; registered via local capture registry (not Oneiric adapters — see Oneiric section). | 350 |
| `decode.py` | Consumes raw packets via `dpkt`. Emits structured `FlowEvent`s with `tcp_flags`, `payload_sha256_prefix` (32 bytes; source buffer zeroed immediately). Zeroes buffer via context manager. | 350 |
| `aggregate.py` | Stateful: per-flow rolling counters + per-host byte totals over 60s sliding window. Two-tier window: fast (10Hz, 60s) for visualization, slow (every 30s, 10min sparse timestamps) for periodicity heuristics. | 500 |
| `graph.py` | Pure data: derives current `GraphState` from aggregator on tick. | 200 |
| `heuristics.py` | Reads aggregator stream, emits `Alert` events. Beaconing (jitter 20%, slow window), port-scan (SYN packets/sec, distinct dst ports, vertical/horizontal distinction), top-N churn (sustained 3+ ticks, scaled with active host count). | 350 |
| `publisher.py` | Encodes graph snapshots + alerts as protobuf on data.sock. Custom ring buffer (NOT `asyncio.Queue`) for drop-oldest semantics. | 200 |
| `ipc_server.py` | Reads JSON-RPC on control.sock. JSON Schema validation via `oneiric.actions.schema_validation`. | 250 |
| `app.py` | Oneiric-driven entrypoint; loads config, wires modules, handles signal/cleanup. | 150 |
| `cli.py` | `flowscape live`, `flowscape replay`, `flowscape doctor` (validates Oneiric config + BPF permission + libpcap version + BPF filter compiles + primary interface auto-detected), `flowscape interfaces`, `flowscape version`. | 100 |

**Total Python production:** ~2,600 LOC. **Plus tests:** ~5,000-6,500 total LOC (Python tests run 1.5-2.5× production LOC at 89% coverage).

### Swift frontend (`src/Flowscape/` Swift package)

| Module | Purpose | LOC est. |
|---|---|---|
| `App.swift` | SwiftUI `App` entrypoint; consent gate; window + menu commands. | 200 |
| `Sidebar.swift` | Capture source picker, filter controls, legend, alerts list, status indicator. | 400 |
| `SceneView.swift` | `NSViewRepresentable` wrapping `MTKView`; the GPU scene lives here. | 200 |
| `Renderer/` (actor) | Metal pipeline + custom shaders. **Edge rendering strategy: compute-pass writes line segments (cylinder quads) into a shared vertex buffer, instanced per-edge.** MTKView config pinned: `colorPixelFormat=.bgra10_xr_srgb`, `depthStencilPixelFormat=.depth32Float`, `sampleCount=4`, `enableSetNeedsDisplay=false`, `preferredFramesPerSecond` follows `RenderSettings.target_fps` (default 60, configurable up to 120 for ProMotion). MTLBuffer pools allocated once at startup with capacity = `max_nodes * node_size + max_edges * edge_size`, never reallocated during runtime. | 1,500-2,000 |
| `Layout/` | 3D force-directed (GPU compute kernel, not CPU on render thread). Triple-buffered positions. | 300 |
| `IPCSocket.swift` (actor) | Two `SOCK_SEQPACKET` Unix-socket clients. Partial-read state machine. JSON-RPC dispatcher on control.sock. Bidirectional heartbeat. | 600 |
| `AlertModel.swift` | Heuristic alerts surfaced in sidebar (dismissable, severity-aware, TTL-aware). | 150 |
| `HelperInstall/` | Launchd plist + helper binary source for the privileged ChmodBPF-style helper. | 300 |

**Total Swift hand-written:** ~3,650-4,150 LOC. **Plus generated:** ~500 LOC. Realistic v1 Swift is meaningfully larger than the original estimate; that's the cost of Swift 6 strict concurrency + the actor model.

### Generated files

| Source | Output | Invoked by |
|---|---|---|
| `proto/flowscape.proto` | `src/flowscape/_proto/*.py` (betterproto2) | `scripts/gen_proto.sh`, called from `uv sync` |
| `proto/flowscape.proto` | `src/Flowscape/Generated/*.swift` (swift-protobuf) | Xcode build phase |
| `proto/flowscape.proto` | `.metallib` shader bundle reference | Xcode build phase (proto used for `payload_sha256_prefix` zeroing on the GPU path) |

All generated outputs gitignored. The `.proto` file is committed.

### Public CLI surface

```
flowscape live [--interface en0] [--filter "tcp port 80"]   # primary command
flowscape replay capture.pcap [--speed 1x]                # offline replay
flowscape interfaces                                      # list libpcap-discoverable interfaces
flowscape doctor [--config] [--consent-check]            # config + permission validation
flowscape version
flowscape mcp                                              # v2: MCP server (gated on legal review)
```

______________________________________________________________________

## Data flow & cadence

### End-to-end packet journey

```
1. libpcap ring buffer (kernel)
 ↓ synchronous pcap_loop in pcap_thread (capture.py)
2. capture.py: posts raw packet to asyncio loop via call_soon_threadsafe
 ↓ asyncio.Queue (decode → aggregate: backpressure wanted)
3. decode.py — dpkt parses each packet into FlowEvent
       computes payload_sha256_prefix, zeroes buffer
 ↓ typed queue (aggregate tick)
4. aggregate.py — increments per-flow / per-host counters
 ↓ tick @ 10 Hz
5. graph.py — derives current GraphState snapshot
 ↓ encode as protobuf
6. publisher.py — encodes as protobuf and writes one message to data.sock (SOCK_SEQPACKET preserves message boundaries, so each `sendmsg` is one logical frame)
       drop-oldest ring buffer; if socket.send blocks >50ms, drop current snapshot
 ↓ kernel socket buffer
7. IPCSocket.swift (actor) — reads frame, decodes, hands to SnapshotBuffer
 ↓ triple-buffer handoff
8. Renderer (actor) — reads latest snapshot at frame start, updates MTLBuffer pools
 ↓ layout worker queue (separate DispatchQueue)
9. Layout — GPU compute kernel writes new positions to next slot in triple-buffer
 ↓ GPU upload
10. Renderer draws — Metal instanced spheres + line segments (cylinder quads)
```

### Tick rates

| Tier | Rate | Why |
|---|---|---|
| Packet ingest | As fast as libpcap hands us | Don't throttle the wire |
| Decode | Same as ingest | dpkt is fast enough at our target |
| Aggregation tick (fast) | **10 Hz** | Fast enough to feel live, slow enough to keep IPC bounded |
| Aggregation tick (slow) | **every 30 s** | Periodicity detection only; sparse timestamps |
| IPC publish | **10 Hz** | Same as fast aggregation |
| Layout (GPU compute) | **60 Hz** | Metal render thread pacing |
| Renderer | **`RenderSettings.target_fps`** (default 60, configurable up to 120 for ProMotion) | MTKView `preferredFramesPerSecond` reads from settings |

These are starting values exposed as settings. Tune empirically after we have a real network; wiring is the deliverable, not the numbers.

### Backpressure policy

Latest-wins on the data plane. The `publisher.py` keeps a **bounded ring buffer** (NOT `asyncio.Queue` — that gives backpressure-on-full, not drop-oldest). If `socket.send` blocks for >50 ms (kernel buffer full), Python:

1. Discards the currently-prepared `GraphSnapshot`.
1. Increments `dropped_snapshots` counter.
1. Resumes publishing on the next tick.

Control-plane alerts are **exempt** from this drop policy (alerts are rare and important).

### Cold-start sequence

```
T+0      User opens Flowscape.app
T+50ms   Swift App launches, opens window, "Starting…" placeholder
T+100ms  Consent gate: shows modal if no prior consent
T+200ms  (after consent ack) Swift spawns embedded Python (Process / NSTask)
         with PYTHONHOME/PYTHONPATH pointing at .app/Contents/Resources/python/
T+400ms  Python loads Oneiric config, binds data.sock and control.sock
T+500ms  Python sends handshake {app_version, schema_major, schema_minor} on control.sock
T+600ms  Swift responds with its version
         — version mismatch: Swift shows modal "incompatible backend", quits
T+700ms  Swift sends start_capture on control.sock
T+900ms  Python begins packet ingest
T+1000ms First snapshot arrives → first render frame
T+1100ms Animations begin (camera intro, node fade-in)
```

600-1000 ms to first snapshot is realistic (Python imports + Oneiric load + libpcap open are not free). The placeholder must be informative enough that users don't think the app is hung.

______________________________________________________________________

## IPC contract

### Wire format

**Two SOCK_SEQPACKET Unix-domain sockets.** Message boundaries are preserved by the kernel — no in-stream framing, no tag bytes, no length prefixes beyond what `protobuf` itself encodes.

```
┌─────────────────────────────────┐
│  data.sock    (protobuf frames)  │  SOCK_SEQPACKET
│  control.sock (JSON-RPC 2.0)     │  SOCK_SEQPACKET
└─────────────────────────────────┘
```

Why SOCK_SEQPACKET over SOCK_STREAM: avoids the partial-read state machine, eliminates the "what if my read returns half a frame" bug class, and removes the need for a tag-byte discriminator.

### Schema

`proto/flowscape.proto`:

```proto
syntax = "proto3";
package flowscape.v1;

// ---------- Data plane messages ----------

message GraphSnapshot {
  uint32 schema_major = 1;
  uint32 schema_minor = 2;
  uint64 tick_id = 3;            // monotonic; lets receivers detect drops
  uint64 timestamp_ns = 4;       // monotonic nanoseconds since Unix epoch
  repeated HostNode nodes = 5;
  repeated FlowEdge edges = 6;
  Bounds viewport_hint = 7;      // optional; helps Swift seed layout
}

message HostNode {
  // HostId is a string with a documented wire convention:
  //   - IPv4: dotted-quad, e.g. "192.168.1.5"
  //   - IPv6: compressed form per ipaddress.IPv6Address.compressed, e.g. "fe80::1"
  //   - MAC: lowercase colon-separated, e.g. "aa:bb:cc:dd:ee:ff"
  //   - FQDN: lowercase, FQDN form
  string id = 1;
  enum Kind { KIND_UNSPECIFIED = 0; IPV4 = 1; IPV6 = 2; MAC = 3; NAME = 4; }
  Kind kind = 2;
  uint64 bytes_in_window = 3;
  uint64 bytes_out_window = 4;
  uint32 flow_count = 5;
  repeated ProtocolCount protocol_breakdown = 6;   // ordered; not a map
  string asn = 7;        // empty if unknown
  string label = 8;      // resolved name or IP literal
}

message ProtocolCount {
  enum Protocol {
    PROTO_UNSPECIFIED = 0;
    TCP = 1; UDP = 2; ICMP = 3; ICMPv6 = 4; ARP = 5; IGMP = 6;
    SCTP = 7; ESP = 8; AH = 9; OTHER = 10;
  }
  Protocol protocol = 1;
  uint64 bytes = 2;
}

message FlowEdge {
  string id = 1;                  // canonical 5-tuple hash
  string src = 2;                  // HostNode.id
  string dst = 3;                  // HostNode.id
  uint64 bytes = 4;
  uint64 packets = 5;
  ProtocolCount.Protocol protocol = 6;
  uint32 port = 7;
  uint32 tcp_flags = 8;            // bitfield: SYN=0x02, ACK=0x10, FIN=0x01, RST=0x04
  uint64 first_seen_ns = 9;
  uint64 last_seen_ns = 10;
  // payload_sha256_prefix is the ONLY payload-derived field allowed.
  // 32-byte SHA-256 prefix of the first N payload bytes (per direction).
  // decode.py computes this and zeroes the source buffer immediately.
  bytes payload_sha256_prefix = 11;  // length 32 enforced by publisher assertion in decode.py and validated by Swift decoder
}

message Vec3 { double x = 1; double y = 2; double z = 3; }
message Bounds { Vec3 min = 1; Vec3 max = 2; }

message Alert {
  string alert_id = 1;             // stable ID for dedup
  enum Severity { SEVERITY_UNSPECIFIED = 0; INFO = 1; WARNING = 2; CRITICAL = 3; }
  Severity severity = 2;
  enum Kind { KIND_UNSPECIFIED = 0; BEACONING = 1; PORT_SCAN = 2; TOP_N_CHURN = 3; }
  Kind kind = 3;
  string host_id = 4;
  uint64 timestamp_ns = 5;
  uint32 ttl_seconds = 6;          // client drops after this expires
  oneof detail {
    BeaconingDetail beaconing = 10;
    PortScanDetail port_scan = 11;
    TopNChurnDetail top_n_churn = 12;
  }
}

message BeaconingDetail {
  string peer_id = 1;
  uint32 interval_seconds = 2;
  uint32 jitter_pct = 3;
  uint32 sample_count = 4;
}

message PortScanDetail {
  enum ScanType { SCAN_UNSPECIFIED = 0; VERTICAL = 1; HORIZONTAL = 2; }
  ScanType scan_type = 1;
  uint32 syn_packets_per_second = 2;
  uint32 distinct_dst_ports = 3;
  uint32 distinct_dst_ips = 4;
  uint32 window_seconds = 5;
}

message TopNChurnDetail {
  repeated string promoted_hosts = 1;   // HostNode.ids that entered top-N
  repeated string demoted_hosts = 2;
  uint32 sustained_ticks = 3;
  uint32 active_host_count = 4;
}

// ---------- Control plane messages (defined here as documentation;
// actual control plane uses JSON-RPC, see below) ----------
// All control-plane requests follow JSON-RPC 2.0:
// {"jsonrpc":"2.0","method":"start_capture","params":{"iface":"en0"},"id":N}
// {"jsonrpc":"2.0","result":{...},"id":N}
// {"jsonrpc":"2.0","error":{"code":N,"message":"..."},"id":N}
// {"jsonrpc":"2.0","method":"heartbeat","params":{"tick":N,"dropped_snapshots":M}}  // notification, no id
```

### Schema evolution

- **Adding fields**: append with a new field number. Old clients ignore unknown fields.
- **Removing fields**: mark `[deprecated = true]` first; remove only after one major version cycle.
- **Type changes or renumbering**: bump package `flowscape.v1` → `flowscape.v2`. v2 lives in a separate `src/flowscape/_proto_v2/` module; both link during the transition window; the publisher picks the schema based on the negotiated version. Removal of v1 after one full release cycle.

The publisher asserts `snapshot.schema_major == NEGOTIATED_SCHEMA_MAJOR` before sending; on mismatch, Python exits loudly with a structured error.

### Connection lifecycle

```
1. Python binds data.sock and control.sock (separate SOCK_SEQPACKET).
2. Swift opens both sockets.
3. Python sends handshake notification on control.sock:
   {"jsonrpc":"2.0","method":"handshake","params":{"app_version":"0.1.0","schema_major":1,"schema_minor":0}}
4. Swift responds with its version + capabilities.
   — version mismatch: Swift shows modal "incompatible backend", quits gracefully.
   — handshake timeout (5 s): Swift shows modal, quits.
5. Swift sends start_capture (or load_pcap).
6. Python begins emitting GraphSnapshot frames on data.sock at 10 Hz.
7. Python emits heartbeat notification every 1 s on control.sock:
   {"method":"heartbeat","params":{"tick":N,"dropped_snapshots":M,"ps_drop":N,"ps_ifdrop":N}}
8. Swift emits client_ping every 1 s on control.sock:
   {"method":"client_ping","params":{"ts":N}}
   Python considers Swift dead if 3 client_pings missed.
9. On Swift quit: Swift sends {"method":"quit"}; Python exits 0 within 2 s grace, else SIGTERM, else SIGKILL after 5 s.
10. On Python crash: Swift detects via missed heartbeats AND silent data-sock.
    v1 policy: **auto-respawn once after 2 s** (covers macOS TCC permission prompt window);
    on second failure, show "Backend disconnected. Restart?" modal.
11. On reconnect (transient socket drop): Swift sends last seen tick_id;
    Python either resumes from state or emits {"event":"resync_required","from_tick":N}
    and Swift clears its scene.
```

### Control-plane methods

**Swift → Python (JSON-RPC requests):**

- `start_capture(iface: str, promiscuous: bool = true, bpf_filter: str = "")`
- `stop_capture()`
- `set_filter(bpf: str)`
- `load_pcap(path: str)`
- `set_replay_speed(speed: float)`
- `pause_capture()` (libpcap keeps running; stop emitting snapshots — users can study the graph)
- `resume_capture()`
- `quit()`

**Python → Swift (JSON-RPC notifications, no id):**

- `handshake(app_version, schema_major, schema_minor)`
- `heartbeat(tick, dropped_snapshots, ps_drop, ps_ifdrop)`
- `client_ping` (request; Swift responds)
- `capture_error(message, hint)`
- `heuristic_alert` — **REMOVED.** Alerts go through the data plane as `IPCEnvelope.alert` (next bullet). Single channel.
- `resync_required(from_tick)`

**Python → Swift (data-plane messages):**

- `GraphSnapshot` (10 Hz)
- `Alert` (event-driven; exempt from latest-wins drop)

### Heartbeat details

Liveness uses **both** heartbeat AND data-plane activity:

- Python is "dead" only when (3 missed heartbeats) AND (no data.sock activity) for ≥5 s.
- Surface `ps_drop` (kernel buffer drops) and `ps_ifdrop` (NIC drops) separately in the heartbeat — different remediation for each.

______________________________________________________________________

## Configuration (Oneiric)

`FlowscapeSettings extends MCPServerSettings` — inherits `app_name`, `app_version`, `mcp.*` fields. We do **not** redeclare these.

Layered config lookup order (canonical Oneiric): `defaults → $PROJECT_ROOT/settings/flowscape.yaml → $XDG_CONFIG_HOME/flowscape/{flowscape,local}.yaml → $FLOWSCAPE_* env vars`. `project_root = Path(__file__).resolve().parent.parent` — never `path=` (that disables XDG lookup at `~/.config/flowscape/*.yaml`).

### Typed Pydantic schema

```python
# src/flowscape/settings.py (excerpt)
from __future__ import annotations
from enum import Enum
from pathlib import Path
from typing import Annotated
from pydantic import Field, PositiveInt, NonNegativeFloat, model_validator
from pydantic_extra_types.color import Color as PColor
from oneiric.settings import MCPServerSettings, PeriodicLoad

class CaptureKind(str, Enum):
    LIBPCAP_LIVE = "libpcap_live"
    PCAP_FILE = "pcap_file"

class Protocol(str, Enum):
    TCP = "tcp"; UDP = "udp"; ICMP = "icmp"; ICMPV6 = "icmpv6"
    ARP = "arp"; IGMP = "igmp"; SCTP = "sctp"; ESP = "esp"
    AH = "ah"; OTHER = "other"

class HeuristicName(str, Enum):
    BEACONING = "beaconing"
    PORT_SCAN = "port_scan"
    TOP_N_CHURN = "top_n_churn"

class CaptureSettings(MCPServerSettings.model_config_section("capture")):
    default_kind: CaptureKind = CaptureKind.LIBPCAP_LIVE
    default_interface: str = "en0"  # flowscape doctor --validate-config can override
    promiscuous: bool = True
    ring_buffer_size_mb: PositiveInt = 32  # ≤32MB avoids privilege issues on macOS 13+
    bpf_filter: str = ""

class AggregationSettings(MCPServerSettings.model_config_section("aggregation")):
    tick_interval: Annotated[PeriodicLoad, "ms"] = 100   # 10 Hz
    window: Annotated[PeriodicLoad, "s"] = 60          # fast window
    slow_window: Annotated[PeriodicLoad, "s"] = 600    # slow window for periodicity
    slow_tick_interval: Annotated[PeriodicLoad, "s"] = 30

class LayoutSettings(MCPServerSettings.model_config_section("layout")):
    force_constant_repulsion: NonNegativeFloat = 1.0
    force_constant_spring: NonNegativeFloat = 0.5
    damping: float = Field(0.85, gt=0.0, le=1.0)
    bounds_min: tuple[float, float, float] = (-50.0, -50.0, -50.0)
    bounds_max: tuple[float, float, float] = (50.0, 50.0, 50.0)
    @model_validator(mode="after")
    def _check_bounds(self) -> "LayoutSettings":
        for a, b in zip(self.bounds_min, self.bounds_max, strict=True):
            assert a < b, f"bounds_min must be < bounds_max per axis"
        return self

class RenderSettings(MCPServerSettings.model_config_section("renderer")):
    target_fps: PositiveInt = 60  # up to 120 supported for ProMotion
    background_color: PColor = PColor("#0a0e1a")
    protocol_colors: dict[Protocol, PColor] = Field(default_factory=lambda: {
        Protocol.TCP: PColor("#5ac8fa"), Protocol.UDP: PColor("#ffd60a"),
        Protocol.ICMP: PColor("#ff453a"), Protocol.ARP: PColor("#bf5af2"),
        Protocol.ICMPV6: PColor("#ff453a"),
    })
    edge_thickness_scale: PositiveInt = 1

class HeuristicSettings(MCPServerSettings.model_config_section("heuristics")):
    enabled: list[HeuristicName] = Field(default_factory=lambda: [
        HeuristicName.BEACONING, HeuristicName.PORT_SCAN, HeuristicName.TOP_N_CHURN,
    ])
    beaconing: "BeaconingSettings"
    port_scan: "PortScanSettings"
    top_n_churn: "TopNChurnSettings"

class BeaconingSettings:
    interval_min_seconds: PositiveInt = 30
    interval_max_seconds: PositiveInt = 1800
    jitter_tolerance_pct: float = Field(20.0, ge=0.0, le=100.0)

class PortScanSettings:
    syn_only_pps_threshold: PositiveInt = 100
    distinct_dst_ports_per_minute: PositiveInt = 50
    distinct_dst_ips_per_minute: PositiveInt = 30

class TopNChurnSettings:
    top_n: PositiveInt = 10
    sustained_ticks: PositiveInt = 3
    delta_threshold_pct: float = 50.0  # base; raised to 70% when active_host_count < min_active_hosts
    min_active_hosts: PositiveInt = 20

class LoggingSettings(MCPServerSettings.model_config_section("logging")):
    level: str = "INFO"  # DEBUG, INFO, WARNING, ERROR
    directory: str = "${platform_log_dir}"  # resolved by Oneiric at load
    rotation_max_bytes_mb: PositiveInt = 10
    rotation_backup_count: PositiveInt = 7
```

### YAML (validated against the Pydantic schema above)

```yaml
capture:
  default_kind: "libpcap_live"
  default_interface: "en0"
  promiscuous: true
  ring_buffer_size_mb: 32
  bpf_filter: ""

aggregation:
  tick_interval: "100ms"
  window: "60s"
  slow_window: "600s"
  slow_tick_interval: "30s"

layout:
  force_constant_repulsion: 1.0
  force_constant_spring: 0.5
  damping: 0.85
  bounds_min: [-50, -50, -50]
  bounds_max: [50, 50, 50]

renderer:
  target_fps: 60
  background_color: "#0a0e1a"
  protocol_colors:
    tcp: "#5ac8fa"
    udp: "#ffd60a"
    icmp: "#ff453a"
    arp: "#bf5af2"
  edge_thickness_scale: 1.0

heuristics:
  enabled: ["beaconing", "port_scan", "top_n_churn"]
  beaconing:
    interval_min_seconds: 30
    interval_max_seconds: 1800     # 30 min, not 10 min — covers slow beacons
    jitter_tolerance_pct: 20       # not 5% — real-world is 15-30%
  port_scan:
    syn_only_pps_threshold: 100
    distinct_dst_ports_per_minute: 50
    distinct_dst_ips_per_minute: 30
  top_n_churn:
    top_n: 10
    sustained_ticks: 3
    delta_threshold_pct: 50
    min_active_hosts: 20           # below this, raise threshold to 70%

logging:
  level: "INFO"
  # `${platform_log_dir}` is a Oneiric substitution that resolves to:
  #   - macOS .app: ~/Library/Logs/Flowscape
  #   - macOS wheel: ~/.flowscape/logs
  #   - Linux/future: ~/.local/state/flowscape/logs
  # The trailing /<appname> is appended by the loader, not in YAML.
  directory: "${platform_log_dir}"
  rotation:
    max_bytes_mb: 10
    backup_count: 7

# mcp section is inherited from MCPServerSettings; do not redeclare.
mcp:
  enabled: false                  # v1; activation gated on legal review
  port: 8700
```

### Settings validation (`flowscape doctor --config`)

1. Load YAML via Oneiric; fail loud with structured error on parse failure.
1. For each `Literal`/`Enum` field, assert value is in canonical set.
1. Validate BPF filter (if set) by asking libpcap to compile-no-link; raise on error.
1. Resolve `default_interface`; confirm it's present in libpcap's interface list; warn (not fail) if absent.
1. Confirm logging directory is writable.

### Oneiric action kits — in-scope inventory

| Action kit | In scope? | Where used |
|---|---|---|
| `oneiric.actions.retry` | yes | libpcap `ENODEV` reconnect, snapshot publisher backpressure probe |
| `oneiric.actions.serialization` | yes | protobuf serialization in `publisher.py`, JSON-RPC framing in `ipc_server.py` |
| `oneiric.actions.schema_validation` | yes | JSON-RPC inbound messages in `ipc_server.py` |
| `oneiric.actions.redaction` | yes | log lines scrub payload-derived fields (defense-in-depth alongside wire-format ban) |
| `oneiric.actions.hashing` | yes | host pseudo-IDs in logs (privacy); SHA-256 prefix in `FlowEdge.payload_sha256_prefix` |
| `oneiric.actions.compression` | no | frame sizes don't justify |
| `oneiric.actions.token_gen` / `HMAC` | no | Unix-socket ACL on `$TMPDIR` provides sufficient trust boundary |
| `oneiric.actions.http_probing` | no | no HTTP tier |
| `oneiric.actions.data_transforms` | yes | aggregation windowing, percentile rolling stats in `aggregate.py` |

### PEP 735 optional dependency groups

| Group | Deps | Justification |
|---|---|---|
| `dev` | `pytest`, `hypothesis`, `ruff`, `mypy`, `pyright`, `bandit`, `complexipy`, `commitizen`, `betterproto2[cli]`, `pip-licenses` | full local development |
| `macos` | `py2app`, `betterproto2[cli]`, `pcapy-ng` | macOS `.app` build only |
| `runtime` (default) | `dpkt`, `numpy`, `betterproto2`, `protobuf`, `orjson` | bundled into wheel and `.app` |

So `uv sync` for CLI usage is small; `uv sync --group macos` is required for `.app` packaging; CI's Linux job can skip the macos group entirely.

### Logging path resolution per install channel

| Channel | Path |
|---|---|
| macOS `.app` bundle (embedded Python) | `~/Library/Logs/Flowscape/` |
| macOS wheel install (`pip install flowscape`) | `~/.flowscape/logs/` |
| Linux / future | `~/.local/state/flowscape/logs/` (XDG_STATE_HOME) |

The `${platform_log_dir}` substitution is resolved at startup; Python and Swift end up writing to the same root.

______________________________________________________________________

## Distribution & packaging

### Channels

| Channel | Format | Audience |
|---|---|---|
| `pip install flowscape` | PyPI wheel (sdist + wheel) | Developers, CLI users |
| `uvx flowscape` | PyPI wheel, ephemeral env | One-off use without install |
| `brew install les/tap/flowscape` | Homebrew formula in `les/tap` | macOS command-line users |
| `Flowscape.app` | Signed + notarized `.app` bundle | End users; the headline distribution |

### macOS permission model — v1 strategy

**Decision: non-sandboxed app + ChmodBPF-style launchd helper.**

- The Network Extensions entitlement (`com.apple.developer.networking.networkextension`) is Apple-granted for content filters / VPN use cases, not general-purpose tools. Not pursued in v1.
- App Sandbox is incompatible with `/dev/bpf*` access at all.
- The standard pattern (Wireshark, others) is a **privileged launchd helper** that runs once at install, sets ACLs on `/dev/bpf*` so the logged-in console user can read without sudo.

**Helper bundle target:** `Flowscape Helper.app` (separate target within the same Xcode project), installed by `py2app` postinstall or Homebrew postinstall. Sets permissions on `/dev/bpf*`, exits.

### `.app` bundle structure

```
Flowscape.app/
  Contents/
    Info.plist                                # NSPrivacyNetworkUsageDescription set
    MacOS/
      Flowscape                               # signed (Developer ID)
    Resources/
      python/
        bin/python3                            # embedded interpreter
        lib/python3.14/...
        site-packages/...
      proto/flowscape.proto
      shaders.metallib                          # pre-compiled
      Flowscape Helper.app/                    # privileged helper, signed
        MacOS/Flowscape Helper
```

Python interpreter and `.metallib` must be signed with the same Developer ID for hardened runtime + library validation.

### Build steps

- **Python wheel:** `uv build` → PyPI publish via trusted publishing (OIDC) on tagged release.
- **Homebrew formula:** updated in `les/homebrew-tap` repo via PR from the release workflow.
- **.app bundle:** Xcode archive → `py2app` embeds Python + helper → `codesign --deep --options=runtime` → `xcrun notarytool submit --wait` → staple. Distribution via GitHub Releases.

### Phase 0 prerequisite (procurement)

Apple Developer ID + App Store Connect API key are required for codesign + notarize. If not already in hand, Apple takes 2-3 weeks to issue credentials. **Procure in Phase 0, not Phase 6.**

### Homebrew formula (sketch)

````ruby
class Flowscape < Formula
  desc "Modern network visualization tool"
  homepage "https://github.com/lesleslie/flowscape"
  url "https://files.pythonhosted.org/packages/source/f/flowscape/flowscape-0.1.0.tar.gz"
  sha256 "..."
  license "BSD-3-Clause"
  depends_on "python@3.14"
  depends_on "libpcap"

  def install
    virtualenv_install_with_resources
  end

  def post_install
    # Install the privileged helper to set /dev/bpf* ACLs
    system "#{bin}/flowscape", "doctor", "--install-helper"
  end

  test do
    system "#{bin}/flowscape", "version"
  end
end
```

### Privacy manifest (required for macOS App Store; good citizenship for direct distribution)

`Info.plist` includes `NSPrivacyNetworkUsageDescription` even though we don't request Network Extensions entitlement — it surfaces the system privacy prompt that captures the consent UX.

______________________________________________________________________

## Error handling & recovery

| # | Failure | Detection | Recovery | User-visible |
|---|---|---|---|---|
| 1 | No `/dev/bpf*` access | Python gets EPERM on libpcap open | Send `capture_error` with hint; offer `flowscape doctor --install-helper` | Red banner: "No capture permission. Run 'flowscape doctor --install-helper' or relaunch with sudo." |
| 2 | Helper not installed | libpcap open fails; ACL on `/dev/bpf*` not set | `flowscape doctor` provides install command | Banner: "Capture permission helper missing." |
| 3 | Interface disappears (Wi-Fi drops, USB unplug) | libpcap returns `ENODEV` mid-read | Pause capture; emit `capture_error`; retry every 5 s | Banner: "Capture paused — en0 not available. Retrying…" |
| 4 | Pcap file corrupt / truncated | dpkt throws on first bad packet | Stop decode; emit `capture_error` | Banner: "Pcap file is corrupt or truncated at offset 4.2 MB" |
| 5 | Python process crashes | Swift misses 3 heartbeats AND no data.sock activity ≥5 s | Auto-respawn once after 2 s (TCC permission window). On second failure, modal. | Status indicator; modal on persistent failure. |
| 6 | Python spawn failure (binary missing, dyld error) | Swift's `Process` fails | Modal "Backend failed to launch"; no zombie UI. | Modal immediately. |
| 7 | Unix socket bind failure (stale file, permissions) | `bind()` returns EADDRINUSE/EACCES | Unlink stale socket file; structured error → modal | Modal: "Stale socket at /tmp/... — quit any running Flowscape instances." |
| 8 | Multi-instance launch | Second `bind()` returns EADDRINUSE | Single-instance lockfile (`flock` on well-known path); modal | Modal: "Flowscape already running." |
| 9 | Swift app hangs / GPU device loss | Swift's MTKView crashes; user relaunches | macOS app lifecycle; on relaunch, fresh handshake | N/A (app restart) |
| 10 | Partial protobuf frame on recv | Should not occur with SOCK_SEQPACKET | Defense-in-depth: per-frame length validation; reject malformed | Logged; next valid frame recovers |
| 11 | Malformed protobuf frame | swift-protobuf throws decode error | Swift logs, drops frame, awaits next tick | Self-heals within 1 tick |
| 12 | Version mismatch on handshake | Schema major mismatch | Swift shows: "Backend version 2.0 incompatible with app 1.5. Reinstall." | Modal |
| 13 | Slow consumer (Swift UI hitching) | Python's `socket.send` blocks > 50 ms | Drop currently-prepared snapshot; counter via heartbeat | Status indicator if persistent |
| 14 | libpcap kernel buffer drops | `ps_drop` non-zero | Surface in sidebar; recommend larger ring buffer | "Kernel drops 1.2% of packets" |
| 15 | libpcap NIC drops | `ps_ifdrop` non-zero | Surface; document as not-fixable-by-buffer (NIC congestion) | "NIC drops 0.5% of packets — likely NIC congestion" |
| 16 | Heuristic false positives | User dismisses alerts (client-side state) | Alerts have TTL — auto-expire; persistent issues surfaced in settings | Dismissable alerts in sidebar |
| 17 | Oneiric config error | Oneiric fails to load | Python exits non-zero with structured error | Modal: "Backend config invalid: <line>. Edit settings/flowscape.yaml." |
| 18 | App quit while Python active | Swift sends `quit`; Python graceful shutdown within 2 s, else SIGTERM, else SIGKILL after 5 s | Clean shutdown of libpcap, socket close | macOS app lifecycle |
| 19 | Disk full writing log | `logging` raises | Logging must never block ingest — `QueueHandler` with drop + counter | Status indicator if log writes failing |
| 20 | Sleep/wake BPF re-bind | libpcap returns error after wake | Same as ENODEV (entry #3); auto-rebind | Banner |
| 21 | Graceful quit in middle of snapshot send | Python receives `quit`; flushes in-flight | Cancel pending send; close socket; exit | N/A (no UI during shutdown) |
| 22 | Bidirectional heartbeat detects Swift hung | Python misses 3 client_pings | Mark connection unhealthy; surface in heartbeat | (logged; user may see connection drop) |

### Logging

- **Python:** structured logs via `oneiric.logging` → `${platform_log_dir}/flowscape/python.log` (rotated, 7 backups).
- **Swift:** unified logging (`os_log`) → Console.app and `~/Library/Logs/Flowscape/swift.log`.
- **No PII in logs.** Defense-in-depth: wire format cannot carry payload (architectural); `redact()` helper scrubs known-sensitive fields; CI lints for log statements that include variable names matching `(ip|mac|host|endpoint|payload|packet_body)`.

______________________________________________________________________

## Testing strategy

### Python (pytest)

| Test type | Path | What | Target |
|---|---|---|---|
| Unit | `tests/python/unit/` | Pure functions of aggregate, graph, heuristics, decode, settings, publisher, ipc_server | **89% per module** (crackerjack threshold) |
| Property | `tests/python/property/` | Hypothesis invariants on graph snapshots, decode fuzz | byte counts non-decreasing, edge endpoints ⊆ node set, decode never crashes on arbitrary bytes |
| Integration | `tests/python/integration/` | Real pcap fixtures through full pipeline | handshake round-trip, version mismatch, backpressure drop counter monotonicity, schema evolution, CLI subprocess, crash recovery |

**Per-module coverage gates:**

| Module | Gate |
|---|---|
| `aggregate.py`, `graph.py`, `heuristics.py`, `decode.py`, `publisher.py`, `ipc_server.py`, `settings.py` | 90% |
| `capture.py` (libpcap I/O, hard to unit test) | 70% (with recording-replay wrapper for tests) |
| `cli.py`, `app.py` | 70% |

**Required integration tests** (currently missing in original spec):
- IPC handshake round-trip + version mismatch on both sides
- Heartbeat timeout detection (3 missed + data.sock silence)
- Backpressure drop counter (exactly one snapshot dropped, monotonic counter, oldest dropped)
- Force-directed layout convergence + energy-decreasing property
- Heuristic precision/recall on labeled pcap corpus (synthetic beacon stream with 20% jitter → fires; SYN-only burst → port-scan alert fires)
- `decode.py` fuzz harness (`hypothesis` strategy feeding random bytes)
- Round-trip protobuf encode/decode
- PII redaction in logs (regression test for hard invariant)
- Settings loader edge cases (missing `local.yaml`, malformed YAML, env-var override wins, extra unknown field tolerated)
- CLI subprocess integration (`flowscape version` exits 0)
- Schema v1 → v2 compat
- Crash recovery: kill Python mid-run, verify stale socket file cleanup, verify half-written frame handling

### Swift (XCTest)

| Test type | Path | What |
|---|---|---|
| Layout determinism + convergence | `tests/swift/layout/` | Same input graph → same final positions (`Double` epsilon `1e-9`); energy decreases |
| Renderer golden | `tests/swift/renderer/` | Render fixed snapshot, compare to reference image. **Tolerance: per-pixel L∞ ≤ 2/255 in linear RGB** (defined metric, not "0.5%"). Golden images pinned to macOS version + GPU model via `tests/swift/renderer/reference_manifest.json`. |
| IPC client | `tests/swift/ipc/` | Two `SOCK_SEQPACKET` clients, partial-read state machine, JSON-RPC dispatcher, handshake, heartbeat timeout |
| Actor isolation | `tests/swift/ipc/test_actor_isolation.swift` | Verify Sendable conformance, no `@unchecked Sendable` in production code |

**Swift coverage gate:** **70%** overall (Metal shaders excluded). Layout + IPC modules **90%**.

### End-to-end (manual + smoke)

- **`scripts/smoke_capture.sh`** — launches Swift app in test mode, captures from loopback pcap, asserts first frame within < 3 s.
- **`tests/e2e/test_app_launch.sh`** — `.app` bundle actually launches, window appears, IPC connects.

### CI matrix

| Stage | Runs |
|---|---|
| **PR** | `ruff check`, `mypy --strict`, `pyright`, `bandit`, `pytest --cov-fail-under=89 -m "not slow"`, `swift build`, `swift test --filter=LayoutDeterminism`, one renderer golden, `.proto` sync check, `pip-licenses --fail-on="GPL;LGPL;AGPL"`, `deptry`, `vulture` |
| **Nightly** | Full pytest (incl. `slow` and `property`), full Swift test suite, all renderer goldens on pinned macOS runner, `.app` bundle build + smoke launch |
| **Tagged release** | Full pipeline + notarization + codesign verification + PyPI publish via trusted publishing |

### Test fixtures

`tests/fixtures/*.pcap` — small files (each < 1 MB) covering: HTTP traffic, DNS bursts, IPv6, ARP-heavy LAN, port-scan pattern, beaconing pattern, malformed packets, **TCP/443 with TLS payloads present (but no SNI extraction — the fixture exercises the TCP/443 flow path and the `payload_sha256_prefix` field, not the deferred v2 SNI work)**.

**Fixture generation:** `scripts/gen_pcap_fixtures.py` (uses scapy as build-time dep, NOT runtime) emits deterministic pcaps from in-memory packet templates. CI check: fixtures match script output (catches binary corruption).

### Quality gates (Bodai crackerjack pattern)

| Gate | Tool | Threshold |
|---|---|---|
| Lint | Ruff | zero errors |
| Type check | mypy strict + pyright | zero errors |
| Tests | pytest | `--cov-fail-under=89` overall (crackerjack threshold), **per-module gates** in [Testing strategy](#testing-strategy): 90% on aggregate/graph/heuristics/decode/publisher/ipc_server/settings, 70% on capture/cli/app |
| Security | bandit | zero high/critical |
| License | pip-licenses | no GPL/LGPL/AGPL |
| Complexity | complexipy | per Bodai limits |
| Commit | commitizen | conventional commits |
| `.proto` sync | scripts/check_proto_sync.py | generated == committed |

Swift side: `swift build`, `swift test`, `swift-protobuf` codegen step. Golden tests fail build on regression.

______________________________________________________________________

## Naming & branding

| Field | Value |
|---|---|
| **Project name** | `flowscape` |
| **PyPI package** | `flowscape` |
| **CLI command** | `flowscape` |
| **Import name** | `flowscape` |
| **`.app` bundle** | `Flowscape.app` |
| **Main app bundle ID** | `com.lesleslie.flowscape` (subject to Apple Developer team match) |
| **Helper bundle ID** | `com.lesleslie.flowscape.helper` (same team; commit in Phase 0) |
| **Oneiric app name** | `flowscape` |
| **Homebrew formula** | `flowscape` (in `les/tap`) |
| **GitLab repo path** | `les/flowscape` (private) |
| **GitHub repo (later)** | `lesleslie/flowscape` |
| **Tagline** | "A 3D landscape of your network flows." |

**Why not Etherape / aether / etc.:** explicitly avoiding any name that suggests affiliation with the original project. We are inspired, not derived. Trademark clearance for "flowscape" in Class 9 (downloadable software) is on the lawyer's checklist before PyPI name reservation.

______________________________________________________________________

## Licensing

| Item | License |
|---|---|
| **flowscape (this project)** | **BSD-3-Clause** |
| `dpkt` | BSD-3-Clause |
| `betterproto2` | MIT |
| `protobuf` runtime | BSD-3-Clause |
| `pcapy-ng` | Apache-2.0 (with ctypes fallback to system libpcap) |
| `libpcap` | BSD |
| `py2app` | MIT |
| `SwiftProtobuf` | Apache-2.0 (with runtime exception) |
| Swift / SwiftUI / Metal | Apple-proprietary (standard Apple Developer terms) |
| Homebrew | BSD |

**No copyleft in the dependency tree.** CI enforces via `pip-licenses --fail-on="GPL;LGPL;AGPL"`.

**Etherape is GPLv2.** We do **not** study its source code. A formal clean-room protocol in `CONTRIBUTING.md`:

- Each contributor attests whether they have read Etherape source (ever, in any version).
- Contributors marked "yes" are excluded from writing code in subsystems that overlap Etherape features (capture, decode, protocol coloring, force-directed layout, BPF filtering). They contribute only via feature-spec declarations routed to non-contaminated implementers.
- Pre-commit CI check verifies no "yes"-marked contributor appears in git history on overlapping files.
- Clean-room attestation templates in `docs/clean-room-attestations/`.

**Disclaimer docs embedded in the build:**

- `LICENSE`: BSD-3 (unchanged).
- `SECURITY.md` / `LEGAL.md`: per-jurisdiction known restrictions (US ECPA / CFAA / state wiretap; EU GDPR + national implementations); explicit "consult counsel before using on third-party networks."
- README at top, before feature description: "For use on networks you own or have explicit written authorization to monitor. Misuse may violate criminal law."
- One-time in-app banner on every fresh build of the Swift frontend.

### GDPR posture (deliverable)

Even though the architecture is local-only, ship `docs/legal/gdpr-posture.md` documenting:

- Personal data processed: IPs, MACs, OUIs, host fingerprints (all derived from network observation).
- Lawful basis: Art. 6(1)(f) legitimate interests of the operator.
- Data minimization: window-only aggregation, no persistent store of subjects.
- Data subject rights narrative.
- No third-country transfers.

When MCP activates, write a DPIA (Art. 35) before flipping the switch.

______________________________________________________________________

## Out of scope / future work

| Feature | Why out | When |
|---|---|---|
| Time scrubber / historical replay | Buffered graph state | v2 |
| Drill-down side panels (top talkers, conversation table) | UI scope | v2 |
| sflow / NetFlow / OTel sources | Not Etherape-shaped | v2 |
| MCP server (full) | `mcp-common` ready; activation is a future spec gated on legal review | v2+ |
| scapy-mcp / unifi-mcp integration | Enrichment plugins for `heuristics.py` / `graph.py` | v2+ |
| TLS SNI extraction (TCP/443 + QUIC ClientHello) | "Modernized" differentiator; multi-week research | v2 |
| MAC/OUI bundling (5 MB IEEE OUI file) | LAN host identification UX win | v2 |
| mDNS / SSDP / WS-Discovery port classification | LAN-visibility (AirPlay, Chromecast, Sonos) | v2 |
| Linux / Windows GUI | macOS-first; not on the roadmap | maybe never |
| ML-based anomaly detection | Statistical heuristics in v1 | v3+ |
| Cloud / SaaS flow ingestion | Out of scope for a local tool | maybe never |
| Tauri / Electron port | Not aligned with the `.app` strategy | no |
| Network Extensions entitlement path | Apple-granted; not pursuing in v1 | maybe v3 |
| Sparkle / auto-update | Manual updates only | v2 |

______________________________________________________________________

## Open questions (must be resolved before Phase 6 distribution)

1. **App icon design.** Not in scope for this spec — design a separate branding spec when ready. (Placeholder concept: stylized "flow" mark in a 3D bezel.) Until then, ship with the default Xcode app icon.

## Assumptions (subject to verification)

- **Bundle identifier:** `com.lesleslie.flowscape` is the working assumption. If the signing Apple Developer team differs, this may need to change to match (`<team-id>.com.lesleslie.flowscape`).
- **GitHub public mirror:** GitLab private at launch; GitHub public mirror is planned for later once v1 stabilizes. Reverse order is also acceptable; defer the decision until we know which org publishes first.
- **Trademark clearance for "flowscape"** in Class 9 (downloadable software): pending lawyer review before PyPI name reservation.

## Future scope (NOT v1)

These are explicitly out of scope for v1; included here so future specs can pick them up cleanly.

- **sparkle / auto-update** — manual updates via `brew upgrade` / `pip install --upgrade` only.
- **Localization** — strings centralized in SwiftUI views and Python modules, but no l10n extraction. English-only v1.
- **Linux / Windows GUI** — macOS-first; not on the roadmap.
- **ML-based anomaly detection** — statistical heuristics only in v1.
- **Cloud / SaaS flow ingestion** (NetFlow, sFlow, OpenTelemetry, VPC flow logs) — local-pcap only in v1.
- **Tauri / Electron port** — not aligned with the `.app` strategy.

### MCP activation as regulatory event

`mcp.enabled` flips from `false` to `true` only after:

1. `docs/adr/0007-mcp-activation.md` is marked `decided` with sign-off date and rationale.
2. `docs/legal/gdpr-posture.md` is updated with MCP-specific DPIA (Art. 35).
3. `CONTRIBUTING.md` is updated with the MCP tool surface scope.

This is process discipline; without it, MCP activation could ship without the legal review that the rest of the spec mandates.

______________________________________________________________________

## Implementation clarifications

This section resolves ambiguities and prereqs from the final-pass review. **Read this before plan generation** — every item below has an explicit answer that the plan-writer should not need to re-derive.

### Ambiguity resolutions

| ID | Question | Resolution |
|---|---|---|
| A1 | How is `bpf_filter` validated in `flowscape doctor --config`? | Through `pcapy-ng`'s `compile()` API (returns 0 on success). ctypes fallback if `pcapy-ng` wheels are unavailable. |
| A2 | What resolves `${platform_log_dir}`? | Custom Oneiric substitution hook registered in `settings.py`. Resolves to `~/Library/Logs` for `.app`, `~/.flowscape` for wheel, `~/.local/state` for Linux (XDG_STATE_HOME). The trailing `/Flowscape` or `/flowscape` is appended by the loader, not in YAML. |
| A3 | SOCK_SEQPACKET connection pattern? | **Connection-oriented**: Python `bind()` + `listen()` + `accept()` on both sockets; Swift `connect()`. SOCK_SEQPACKET supports both styles; connection-oriented gives us a clear connection lifecycle. |
| A4 | Schema sync CI with gitignored generated files? | Generated files live at `src/flowscape/_proto/*.py` and `src/Flowscape/Generated/*.swift` — **gitignored** for the contents, but a `git-ls-files` check verifies the directory structure exists. CI regenerates from `.proto` and runs the binary (`flowscape` + a stub Swift receiver) to verify they produce equivalent output. The "diff against committed copy" was the wrong framing — there's no committed copy. |
| A5 | Where does `NEGOTIATED_SCHEMA_MAJOR` come from? | Generated at codegen time from `proto/flowscape.proto`'s `package flowscape.v1` literal. `betterproto2` codegen extracts it; Swift's protoc plugin does the same. Both sides compile-time-assert against it. |
| A6 | Heuristic scaling wording (`raise threshold to 70%`)? | When `active_host_count < min_active_hosts`, `delta_threshold_pct` is replaced with `delta_threshold_pct_high_density` (default 70%). Two separate fields, not computed at runtime. |
| A7 | Auto-respawn decision rule? | Auto-respawn fires only on **transient** failure (heartbeat lost + data-sock silent). Never on **permanent** failure (Python binary missing, dyld error, port already in use). Permanent failure surfaces modal immediately. |
| A8 | Single-instance lock primitive on macOS? | `flock(2)` on a well-known lockfile path (`~/Library/Application Support/Flowscape/.lock`). BSD file locks on macOS work for this use case (advisory, per-process). |
| A9 | MTLBuffer pool lifetime? | Allocated once at `Renderer` actor startup with capacity = `max_nodes * node_byte_size + max_edges * edge_byte_size`. Never reallocated during runtime. Capacities set from `RenderSettings` (default 10k nodes, 50k edges). |
| A10 | Layout initial positions in Phase 4a? | Deterministic random-on-sphere seeded by SHA-256 hash of `HostNode.id`. Reproducible; no flicker on identical graphs. |
| A11 | Helper XPC interface? | Single method: `install_helper()` (sets `/dev/bpf*` ACLs, exits). Helper does NOT stay resident. Subsequent runs of the app verify ACL state by attempting `pcap_open`; on EACCES, the app surfaces "Helper needs reinstall." |
| A12 | Heuristic labeled corpus source? | Start with `scripts/gen_pcap_fixtures.py` synthetic (deterministic, no real traffic). Expand with real captures only if synthetic isn't enough — and sanitize captures to remove any non-public IPs/hostnames before commit. |
| A13 | Golden-image baseline? | **macOS 14.6 on Apple M2**, pinned in `tests/swift/renderer/reference_manifest.json`. PR runs on GitHub Actions `macos-14` runner. Nightly re-bakes references when the manifest version bumps. |
| A14 | PII redaction CI tool? | Bespoke `scripts/check_log_pii.py`: regex over Python source for log statements containing variable names matching `(ip|mac|host|endpoint|payload|packet_body)` (case-insensitive). Build fails on hit. Plus a runtime `Oneiric.log.filter` that drops any record whose `extra` dict has keys starting with `payload`/`body`/`raw`. |
| A15 | Triple-buffer synchronization primitive? | `OSAllocatedUnfairLock<UInt32>` (macOS-native, lock-free reads in the common case). Three slots, atomic index swap. Producer writes to slot `(idx + 1) % 3`, consumer reads from slot `idx`. |
| A16 | CaptureSource registry vs Oneiric adapters? | Local module-level registry in `src/flowscape/capture_registry.py`. NOT Oneiric adapters (the registry framework is heavier than needed for 2 sources). `register_source(name: str, source: CaptureSource)` adds entries; `capture.py` looks up by name from settings. |
| A17 | Swift package layout for codegen? | Phase 0 scaffolds `Package.swift` with `swift-protobuf` SPM dep + a `Run Script` build phase that calls `scripts/gen_proto.sh`. Both Python (`uv sync`) and Xcode invoke the same script. |

### Prereq resolutions

| ID | Issue | Resolution |
|---|---|---|
| P1 | Phase 3 depends on Phase 2 IPC contract | Phase 2 ships the proto and a smoke test (Python emits, stub Swift receiver decodes). Phase 3 then writes `IPCSocket` against the same proto types. |
| P3 | No phase creates the Xcode project | **Phase 0 also scaffolds the Xcode project** (`Flowscape.xcodeproj`) and Swift package structure. Phase 6b only adds codesign + notarize. |
| P4 | Apple Developer ID blocks Phase 6 | Phase 0 starts procurement in week 1; Phase 6 is reached at week ~14 in worst case. Contingency: if Developer ID isn't ready, ship unsigned `.app` for local development and continue Homebrew/PyPI distribution for v1.0. |
| P5 | Heuristics config loaded in Phase 1 but unused until Phase 5 | **Phase 1 includes the Pydantic schema for heuristics** (added above). Loading + validation is Phase 1 work; using it is Phase 5. Tests for heuristics settings live with Phase 1. |
| P6 | PR CI assumes macOS runner | PR runs on GitHub Actions `macos-14`. GitLab private repo mirrors the same runner spec. Linux jobs run on Linux runners. |
| P8 | Helper bundle ID needs Phase 0 sign-off | **Helper bundle ID `com.lesleslie.flowscape.helper` is committed in Phase 0** (alongside main app bundle ID). See Naming & branding table. |
| P9 | Consent gate depends on privacy manifest | Phase 6b installs the privacy manifest in `Info.plist` (system-level prompt). Phase 3 implements the in-app consent gate (user-level prompt). Two separate prompts. |
| P10 | Embedded Python only available after Phase 6b | Phases 3-5 development uses `uv`-managed system Python (not embedded). Phase 6b switches to embedded Python. |

______________________________________________________________________

## Implementation phases (revised)

These map to spec phases; the `writing-plans` skill will produce a detailed plan from this design. **Realistic single-developer timeline: 14-20 weeks** (assumes prior Swift/Metal/libpcap/dpkt experience; otherwise 6 months).

1. **Phase 0 — Procurement + repo + tooling** (1 week)
   - Apple Developer ID + App Store Connect API key (parallel with everything else — slow external dependency)
   - **Commit main app + helper bundle IDs** (`com.lesleslie.flowscape`, `com.lesleslie.flowscape.helper`)
   - Fresh repo, pyproject.toml, ruff/mypy/pyright/pytest config, CI on GitHub Actions `macos-14`
   - **Xcode project scaffold** (`Flowscape.xcodeproj`) and Swift package structure (`Package.swift` with swift-protobuf dep + Run Script build phase)
   - Oneiric settings skeleton with typed Pydantic schema (incl. all classes from [Implementation clarifications](#implementation-clarifications))
   - `proto/flowscape.proto` initial schema (incl. all Tier-1 schema additions)
   - Codegen scripts + CI `.proto` sync check (binary equivalence test, not git diff — see A4)
   - `CONTRIBUTING.md` clean-room protocol skeleton
   - `scripts/check_log_pii.py` and CI enforcement (see A14)

2. **Phase 1 — Python backend (capture + decode + aggregate)** (3 weeks)
   - `capture.py` with `pcapy-ng` + `pcap_thread` + capture registry
   - `decode.py` with dpkt + `payload_sha256_prefix` + buffer zeroing
   - `aggregate.py` with two-tier windowing
   - Test fixtures generated via `scripts/gen_pcap_fixtures.py`

3. **Phase 2 — IPC contract end-to-end** (1.5 weeks)
   - `.proto` schema finalized with all Tier-1 fixes
   - Two `SOCK_SEQPACKET` sockets wired
   - betterproto2 + SwiftProtobuf codegen working
   - Smoke test: Python emits, Swift decodes
   - `CONTRIBUTING.md` clean-room attestations collected from team

4. **Phase 3 — Swift frontend basics** (3 weeks)
   - App skeleton, consent gate (`App.swift`)
   - Sidebar with controls
   - Swift 6 actor model: `IPCSocket` actor, `Renderer` actor, `LayoutState` Sendable struct
   - `MTKView` with simple wireframe render
   - IPCSocket partial-read state machine (SOCK_SEQPACKET makes this simpler, but partial-JSON-RPC parsing still needed)

5. **Phase 4a — 3D renderer with Metal compute layout** (3 weeks, parallel with Phase 3)
   - **Metal compute kernel** for force-directed layout (ships in this phase; not CPU)
   - **Initial positions seeded random-on-sphere** for Phase 4a (deterministic by host ID hash for reproducibility)
   - Instanced sphere rendering for nodes
   - Instanced line-segment rendering for edges (cylinder quads)
   - Camera controls (orbit, zoom)
   - SwiftUI ↔ MTKView bridging with actor model

6. **Phase 4b — Layout triple-buffer integration** (2 weeks)
   - **Layout compute kernel already ships in 4a.** 4b is the wiring: kernel output → `OSAllocatedUnfairLock<UInt32>` index swap → triple-buffer → renderer
   - Convergence tests + energy-decreasing property tests
   - Benchmarks (iterations-to-convergence on 1k-node graph)
   - Triple-buffer primitives: `[PositionBuffer]` ring of 3 with atomic write/read indices guarded by `OSAllocatedUnfairLock`

7. **Phase 5 — Interaction + heuristics** (2 weeks)
   - Click/hover for host inspection
   - In-scene filtering
   - Heuristics: beaconing (20% jitter, slow window), port-scan (SYN packets/sec), top-N churn (sustained, scaled)
   - Alerts list in sidebar with TTL awareness
   - Pause/resume control

8. **Phase 6a — Distribution: launchd helper** (1 week)
   - `Flowscape Helper.app` Xcode target (XPC-based privileged helper, modern macOS helper API — not SMJobBless, which is deprecated)
   - Helper sets `/dev/bpf*` ACLs on install, exits
   - `flowscape doctor --install-helper` CLI
   - Homebrew post-install hook

9. **Phase 6b — Distribution: signed .app** (2-3 weeks)
   - py2app build pipeline
   - codesign + notarize iteration loop (expect 2-3 retries)
   - `SECURITY.md` / `LEGAL.md` in the bundle
   - Privacy manifest in `Info.plist`

10. **Phase 7 — Polish + docs** (2 weeks)
    - Settings UI
    - Menu bar items
    - Error UX (the 22-row table)
    - Test coverage to 89%
    - `docs/legal/gdpr-posture.md`
    - README, USER_GUIDE

**v1 ships after Phase 7.** Realistic v1 timeline: 14-20 weeks for one experienced developer; 6 months for one without prior Swift/Metal/libpcap experience.

**Phase 6a and 6b start in parallel with Phase 5** — distribution has its own feedback loops (notarize iterations), better to learn them early.

______________________________________________________________________

## Decisions recorded

- **Approach: Lean Stack (A)** — dpkt + custom Python aggregator + custom Swift 3D force-directed layout (GPU compute) + SwiftProtobuf over two `SOCK_SEQPACKET` Unix sockets + MTKView. Rationale in this session's brainstorming.
- **Data plane: betterproto2 + SwiftProtobuf.** Control plane: JSON-RPC over separate socket.
- **Two SOCK_SEQPACKET sockets** (not one socket with tag-byte multiplexing). Message-boundary preservation eliminates the partial-read state machine.
- **License: BSD-3-Clause.**
- **Name: `flowscape`.** No Etherape-affiliation language.
- **Repo: fresh**, GitLab private (initially), GitHub public option later.
- **Distribution targets: PyPI + uvx + Homebrew + signed `.app` + launchd helper for BPF ACL.**
- **Oneiric for config + logging + action kits (selectively).** Capture-source adapter pattern adopted locally (NOT Oneiric adapters — only 2 sources, defer the registry framework).
- **`mcp-common` included now**, MCP server features gated on legal review ADR before activation.
- **Swift 6 strict concurrency from day one.** Actor model (IPCSocket, Renderer), Sendable LayoutState struct, triple-buffer handoff.
- **Structural no-payload guarantee.** Wire format cannot carry payload bytes. `payload_sha256_prefix` is the only allowed payload-derived field. CI lints for forbidden field names.
- **Active consent gate.** First-launch modal + on interface/SSID change + every 30 days. Stored in `~/.flowscape/consent.json`.
- **macOS permission model: non-sandboxed app + ChmodBPF-style launchd helper.** Network Extensions entitlement not pursued in v1.
- **Heuristic thresholds:** beaconing 20% jitter, port-scan SYN packets/sec, top-N churn sustained 3+ ticks.
- **Coverage: 89% Python (crackerjack threshold), 70% Swift (with per-module gates).**
- **Timeline: 14-20 weeks for one experienced developer.** Phase 4 split into 4a (renderer) + 4b (layout) for de-risking.

______________________________________________________________________

*Spec authored in a brainstorming session, revised after 8-agent multi-agent review. Next: user final review → `writing-plans`.*
````
