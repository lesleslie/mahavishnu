# ACP Server — Operator Usage

This document covers the operational side of the Mahavishnu ACP server:
how to launch it, how to configure authentication, and what to expect
when an ACP client (Toad, Zed, JetBrains, future tooling) connects.

## What ACP is

The [Agent Client Protocol](https://agentclientprotocol.com) is a
stdio JSON-RPC 2.0 protocol that lets an external client drive a
coding agent directly. Mahavishnu implements the **agent** side —
any ACP-compatible client can spawn `mahavishnu acp serve` as a
subprocess and drive Mahavishnu through JSON-RPC over stdin/stdout.

This is the same pattern that lets Zed and JetBrains integrate with
non-Claude agents via ACP. For Mahavishnu, the use case is primarily
[Toad](https://github.com/batrachianai/toad) — an AGPL-licensed
terminal client — and any custom MCP client that wants ACP support.

## Quick start

The server is launched as a long-running subprocess. The client owns
the lifecycle (start it, exchange JSON-RPC, close stdin, reap).

```bash
# 1. Generate a 32-byte bearer (secrets.token_urlsafe(32) is the standard idiom).
export MAHAVISHNU_ACP_BEARER_TOKEN=$(python -c 'import secrets; print(secrets.token_urlsafe(32))')

# 2. Launch the server. It reads from stdin, writes responses to stdout,
#    and logs structured events to stderr.
mahavishnu acp serve

# 3. The client writes JSON-RPC requests to stdin and reads responses
#    from stdout, one newline-delimited JSON object per line.
echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"0.0.1","clientInfo":{"name":"my-client","version":"1.0.0"}}}' | mahavishnu acp serve
```

The server refuses to start without a bearer (fail-closed). If neither
`MAHAVISHNU_ACP_BEARER_TOKEN` nor `MAHAVISHNU_ACP_BEARER_TOKEN_FILE` is
set, `mahavishnu acp serve` exits with code 1 and an error message.

## Bearer setup

The bearer is loaded **once at startup** and popped from the environment
immediately so child processes don't inherit it. Two modes are
supported (mutually exclusive):

| Mode | Env var | Notes |
|------|---------|-------|
| Inline | `MAHAVISHNU_ACP_BEARER_TOKEN` | Simplest; the variable is unset after the server reads it |
| File | `MAHAVISHNU_ACP_BEARER_TOKEN_FILE` | Path to a file (mode 0600 required) containing the token; the file is read once at startup |

Generate a bearer (32+ bytes recommended):

```bash
export MAHAVISHNU_ACP_BEARER_TOKEN=$(python -c 'import secrets; print(secrets.token_urlsafe(32))')
```

Or write to a file:

```bash
umask 077  # ensure default file mode is 0600
python -c 'import secrets; print(secrets.token_urlsafe(32))' > ~/.mahavishnu/acp-bearer
chmod 0600 ~/.mahavishnu/acp-bearer
export MAHAVISHNU_ACP_BEARER_TOKEN_FILE=~/.mahavishnu/acp-bearer
```

The server compares the bearer with `secrets.compare_digest` —
timing-attack-resistant. Tokens shorter than 16 bytes are rejected at
startup (sanity guard; 32+ recommended).

## Toad config example

[Toad](https://github.com/batrachianai/toad) is the canonical Toad-style
ACP client for terminal-based coding workflows. Configured via
`~/.config/toad/config.toml`:

```toml
# Toad config (version tested against: v0.4.x)
[agent.mahavishnu]
type = "acp"
command = "mahavishnu"
args = ["acp", "serve"]
env = { MAHAVISHNU_ACP_BEARER_TOKEN = "<your-32-byte-token>" }
```

Or, equivalently, point Toad at the bearer file:

```toml
[agent.mahavishnu]
type = "acp"
command = "mahavishnu"
args = ["acp", "serve"]
env = { MAHAVISHNU_ACP_BEARER_TOKEN_FILE = "/home/user/.mahavishnu/acp-bearer" }
```

Verify the install:

```bash
mahavishnu acp serve --help  # shows invocation options
```

## CLI options

```
$ mahavishnu acp serve --help

Start the ACP server on stdio (JSON-RPC 2.0).

Reads JSON-RPC requests from stdin, writes responses to stdout,
logs structured events to stderr. The server refuses to start
unless a bearer token is configured — see the auth module for the
env-var and file conventions.

Options:
  --bearer-token          Explicit bearer (overrides env). Default: read from
                          MAHAVISHNU_ACP_BEARER_TOKEN.
  --max-concurrent-sessions   Maximum concurrent sessions before -32004.
                              Default: 16.
  --session-timeout       execute_fn timeout in seconds. Default: 600.0.
  --help                  Show this message and exit.
```

## Custom JSON-RPC error codes

Mahavishnu defines four project-specific JSON-RPC error codes in the
`-32000` to `-32099` range (per plan §Phase 2 Decision 1):

| Code | Meaning | When |
|------|---------|------|
| `-32001` | Auth required | A method (other than `initialize`) was called before `authenticate` |
| `-32002` | Auth invalid | The bearer token did not match |
| `-32003` | Session persistence not implemented | `session/load` was called (returns this in v1; persistence ships in v1.5) |
| `-32004` | Too many concurrent sessions | `session/new` rate limit exceeded |

Standard JSON-RPC 2.0 codes (also returned by the dispatcher):

| Code | Meaning | When |
|------|---------|------|
| `-32700` | Parse error | stdin line not parseable JSON, or > 1 MB line |
| `-32600` | Invalid Request | Batch requests (array at top level) |
| `-32601` | Method not found | Unknown JSON-RPC method |
| `-32602` | Invalid params | Pydantic validation rejected the params |
| `-32603` | Internal error | Unhandled dispatcher exception |

Clients (Toad, Zed, etc.) can surface these codes to users as
typed errors instead of generic "request failed" messages.

## Known limitations (v1)

The v1 dispatcher ships the ACP protocol surface but defers several
features to follow-on versions:

| Limitation | Plan section | Workaround |
|------------|-------------|------------|
| `session/load` returns `-32003` | v1.5.1 persistence bundle | None in v1; clients should use `session/new` |
| Streaming `session/update` notifications not yet wired | Phase 4 e2e territory | Each `session/prompt` returns the final `stopReason` only |
| `logout` not implemented | Plan §Phase 2 Decision 1 (bullet "Additional ACP session methods deferred to v1.5") | Process exit is the logout |
| `tool_call` updates require EventBridge envelope consumer changes | Phase 1 Task 5 + Phase 4 follow-on | Apple container + E2B sandbox workers already emit; other workers emit only `worker.*` topics |
| Phase 1.5 `execute_fn_factory` not wired | Phase 1.5 follow-on | CLI uses a stub `execute_fn` that echoes the prompt |

The CLI prints a stub note in the response payload when the stub is in
use: `{"echo": "<prompt>", "stub": true, "note": "Phase 1.5 execute_fn
not yet wired; this is a stub."}`.

## Security

Per plan §Phase 2 Decision 5 (threat model):

- **The bearer is not the primary trust boundary.** ACP auth is
  defense-in-depth; the primary trust boundary is OS-level process
  co-residency. Anyone who can spawn `mahavishnu acp serve` is
  already trusted with the local user's permissions.
- **The bearer gates audit logging and prevents accidental exposure.**
  Wrong tokens return `-32002 Auth invalid` and the request is logged
  at WARNING level.
- **The bearer is popped from the environment immediately after read.**
  Child processes (pool workers, OTel exporter, git subprocesses)
  do not inherit `MAHAVISHNU_ACP_BEARER_TOKEN`. Verify with
  `cat /proc/<pid>/environ | tr '\0' '\n' | grep MAHAVISHNU` — the
  bearer should not appear in the subprocess environment.
- **The bearer may be logged by the ACP client.** Toad, Zed, and other
  ACP clients may write the bearer to their own log/config files
  when launching the subprocess. Check your client's documentation
  for where it stores the token (typically `~/.config/<client>/config.toml`).
- **Use a 32-byte (or longer) bearer.** `secrets.token_urlsafe(32)` is
  the recommended idiom. Tokens <16 bytes are rejected at startup.

## License

Mahavishnu's canonical license is BSD-3-Clause (see `LICENSE` at the
repo root). The `pyproject.toml` `license` field is reconciled with
`LICENSE` in Phase 3b of the build plan — operators should treat
`LICENSE` as authoritative until then.

**Connecting an AGPL client like Toad does not impose AGPL on
Mahavishnu.** The stdio JSON-RPC boundary preserves the no-source-linking
rule (per the License/Compliance review in plan §Phase 2 Decision 3).
Operators do not need a commercial Toad license to use Mahavishnu as
the agent; Toad is invoked as an unmodified external subprocess.

`THIRD_PARTY_NOTICES.md` (added in Phase 3b) records the Toad row and
its commercial-license path.

## Troubleshooting

### Server hangs on startup

If `mahavishnu acp serve` hangs without producing output:

1. Check that `MAHAVISHNU_ACP_BEARER_TOKEN` is set (or
   `MAHAVISHNU_ACP_BEARER_TOKEN_FILE`).
2. Check the file mode on `MAHAVISHNU_ACP_BEARER_TOKEN_FILE` — must be
   `0600` (group/world readable fails).
3. Try `MAHAVISHNU_ACP_BEARER_TOKEN=$(python -c 'import secrets;print(secrets.token_urlsafe(32))')`
   inline to rule out a stale env.

### Client reports "Parse error" / `-32700`

- The dispatcher caps stdin lines at **1 MB**. Larger lines are
  rejected with `-32700 Parse error` before `json.loads` is called.
  Reduce the prompt size or split across multiple `session/prompt`
  calls.
- Confirm newline framing: each JSON-RPC request is **one line**
  terminated by `\n`. Clients that send multi-line JSON or forget the
  trailing newline will hit `-32700`.

### Client reports `-32001 Auth required`

The client forgot to call `authenticate` before a non-`initialize`
method. Check the client's startup sequence:

1. `initialize`
2. `authenticate` (with bearer)
3. `session/new`
4. `session/prompt` / `session/cancel` / etc.

### Bearer visible in process environment

The server pops `MAHAVISHNU_ACP_BEARER_TOKEN` from `os.environ` after
read. If you see the bearer in `/proc/<pid>/environ` after startup,
that's a bug — file an issue with the reproduction.

### Bearer visible in log files

`BearerRedactionFilter` replaces the bearer value with `<redacted-bearer>`
in every log record before it reaches the handler. If you see the
bearer in a log file, that's a bug — file an issue with the
reproduction.

## See also

- Plan: `docs/plans/2026-07-26-mahavishnu-acp-server.md` (the v1.0 plan)
- Spec: `docs/superpowers/specs/2026-07-15-mahavishnu-acp-server-design.md`
- Followups: `docs/followups/2026-07-27-acp-v15-followups.md`
- Wire format: `mahavishnu/acp/protocol.py` (Pydantic models)
- Dispatcher: `mahavishnu/acp/server.py` (JSON-RPC loop)
- [ACP spec](https://agentclientprotocol.com) — protocol reference
