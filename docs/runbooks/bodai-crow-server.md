# Bodai Crow HTTP MCP Server — SSRF & Operations Runbook

**Status:** Shipped in working tree (`eb47401` + `084c505`). Auditable per HANDOFF Audit Finding #7.

**Plan:** `/Users/les/Projects/mahavishnu/docs/superpowers/plans/2026-06-22-bodai-crow-http-server.md` (v2)
**Spec:** `/Users/les/Projects/mahavishnu/docs/superpowers/specs/2026-06-21-bodai-crow-server-design.md` (v7)

## 1. Overview

The Bodai crow HTTP MCP server exposes file, web, and terminal tools over HTTP at `http://localhost:8675/mcp`. It is consumed by:

| Consumer | Tool prefix | Notes |
|----------|-------------|-------|
| Mahavishnu pool workers | `mcp__bodai-crow__*` | GenericShellWorker dispatches prompts that may invoke crow tools |
| Bodai CLI / TUI | `mcp__bodai-crow__*` | Replaces ad-hoc stdio subprocess management |
| ACP agents over HTTP | `mcp__bodai-crow__*` | Non-Claude-Code Bodai consumers |
| `CrowTerminalAdapter` | `mcp__bodai-crow__terminal` | `mahavishnu/terminal/adapters/crow.py` proxies here |

The `terminal` tool is implemented by delegating to a persistent `crow-mcp` stdio subprocess (see `mahavishnu/mcp/crow/terminal_proxy.py`); all other tools are native.

## 2. SSRF Defenses

Source: `mahavishnu/mcp/crow/path_security.py`. `_PRIVATE_NETS` covers the following reserved/private ranges:

| Range | Purpose |
|-------|---------|
| `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16` | RFC 1918 private IPv4 |
| `127.0.0.0/8` | IPv4 loopback |
| `169.254.0.0/16` | link-local / cloud metadata (AWS `169.254.169.254`) |
| `100.64.0.0/10` | CGNAT (RFC 6598) |
| `0.0.0.0/8` | this-network (RFC 1122) |
| `224.0.0.0/4` | IPv4 multicast |
| `240.0.0.0/4` | IPv4 reserved (future use) |
| `::1/128`, `::/128` | IPv6 loopback, unspecified |
| `fe80::/10`, `fc00::/7` | IPv6 link-local, unique-local |
| `::ffff:0:0/96` | IPv4-mapped IPv6 |

`_is_blocked()` coerces edge cases:

```python
def _is_blocked(ip):
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        return any(mapped in net for net in _PRIVATE_NETS)
    return any(ip in net for net in _PRIVATE_NETS)
```

**Why IPv4-mapped IPv6 matters:** `::ffff:127.0.0.1` is a valid IPv6 literal that wraps an IPv4 loopback. Without coercion (`ipaddress.IPv6Address.ipv4_mapped`), containment checks against IPv6-only networks would miss it. See RFC 4291 §2.5.5.2. The dedicated regression test is `tests/unit/mcp/crow/test_path_security.py::test_validate_url_blocks_all_reserved_ranges` (parametrized over all ranges, including the IPv4-mapped case).

`validate_url()` rejects non-http(s) schemes (`file://`, `ftp://`, etc.) with `ValueError` and DNS failures with `ValueError`.

## 3. DNS-Rebinding Mitigation

A single DNS resolution at fetch-time creates a TOCTOU window: an attacker-controlled DNS can return a public IP for the validation lookup, then a private IP for the actual `connect()`. The shared `httpx2.AsyncClient` is configured with `follow_redirects=False`; `web_fetch` (in `mahavishnu/mcp/crow/tools/web_tools.py`) follows redirects manually and re-runs `validate_url()` on every hop:

```python
while True:
    resp = await client.get(current_url, headers={"Accept": "text/html,*/*"})
    if resp.status_code in _REDIRECT_STATUSES and hops < settings.max_redirect_hops:
        location = resp.headers.get("location", "")
        if not location:
            break
        current_url = urljoin(current_url, location)
        validate_url(current_url)  # CRITICAL: re-validate every hop
        hops += 1
        continue
    break
```

`max_redirect_hops` defaults to `5` (`CrowSettings.max_redirect_hops`). A chain exceeding the cap raises `RuntimeError`.

Regression coverage (in `tests/unit/mcp/crow/test_web_tools.py`):
- `test_web_fetch_validates_every_redirect_hop` — public→public→private chain blocks at the private hop.
- `test_web_fetch_redirect_to_suspicious_scheme_blocked` — redirect to `file://` blocked.
- `test_web_fetch_redirect_to_relative_url_resolves_against_current` — relative `Location` header resolved against the current URL.

> Note: The two test names cited in the original HANDOFF line 82 (`test_ssrf_v2_blocks_ipv4_mapped_ipv6_loopback`, `test_dns_rebinding_toctou_re_validates_per_hop`) do not exist as named; the equivalent coverage is the parametrized test above plus `test_web_fetch_validates_every_redirect_hop`. Use those as the regression references.

## 4. Path Traversal Prevention

`resolve_workspace_path(path, workspace_root)` (same file) enforces that every file operation stays inside `settings.workspace_root`:

```python
def resolve_workspace_path(path, workspace_root):
    if "\x00" in path:
        raise PermissionError("null byte in path")
    resolved = Path(path).expanduser().resolve()
    root = workspace_root.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise PermissionError(
            f"Path '{resolved}' is outside workspace root '{root}'"
        ) from exc
    return resolved
```

`resolve()` follows symlinks before the containment check, so a symlink pointing outside the workspace is correctly rejected. The null-byte check prevents `Path("/etc/passwd\x00.txt")`-style bypasses on older runtimes.

The default `workspace_root` is `Path.cwd()` (deliberately narrow — not `Path.home()`). Operators widen it explicitly in `settings/local.yaml`:

```yaml
crow:
  workspace_root: "/Users/les/Projects"
```

## 5. OWASP Memory Guard — Known Gaps

Per HANDOFF Audit Finding #10, the `web_extract` content filter (regex/keyword strippers in `mahavishnu/mcp/crow/tools/web_extract.py`) has known false-negative gaps around homoglyph attacks and base64-encoded payloads. **Future work.** Do not rely on these filters as a security boundary today; the SSRF defenses above are the actual safety layer. If you need prompt-injection defense in front of LLM consumers, plan for an allowlist-based `trafilatura`-backed extractor (Task 10 in the plan) and a dedicated OWASP guard module.

## 6. Operational Runbook

### Start the server

```bash
mahavishnu mcp start crow   # or: python -m mahavishnu.mcp.crow_server
```

The server binds to `127.0.0.1:8675` by default (`CrowSettings.http_host`, `http_port`). Override via `MAHAVISHNU_CROW_HTTP_HOST` / `MAHAVISHNU_CROW_HTTP_PORT` env vars.

### Health check

```bash
curl -fsS http://localhost:8675/health
```

A 200 response indicates the server is up and the lifespan (httpx2 client, crow-mcp stdio subprocess) is initialized.

### Rotate secrets

There are **no embedded secrets** in the crow server itself. If `crow_mcp_command` is replaced with a binary that takes a token, set it via `MAHAVISHNU_CROW_CROW_MCP_COMMAND` and restart. The companion SearXNG container has its own `secret_key` in `settings/searxng/settings.yml` (see `docs/superpowers/specs/2026-06-21-bodai-crow-server-design.md` §7).

### False-positive triage (`_PRIVATE_NETS` blocks a legitimate URL)

1. Confirm the block: tool raises `PermissionError` matching `SSRF`. The resolved address is in the message.
2. If the target genuinely resolves to a public IP that is misclassified (rare — `_PRIVATE_NETS` is conservative), check the hostname's DNS records with `dig +short <host>`.
3. **Do not** widen `_PRIVATE_NETS` to suppress a single host. The right path is to expose the host via a public proxy or update the URL.
4. If the consumer is internal-only and you accept the SSRF risk, set `workspace_root` and `crow:` configuration per-env in `settings/local.yaml` rather than relaxing network policy.

## 7. Failure Modes & Mitigations

| Failure | Symptom | Mitigation |
|---------|---------|------------|
| Upstream web fetch times out | `httpx.TimeoutException` (30s read / 10s connect) | Tool-level raise; `web_fetch_batch` captures per-URL `error`. Caller retries or skips. |
| DNS resolution fails | `ValueError: DNS resolution failed` from `validate_url()` | Caller receives the error before any HTTP request is issued. Retry transient failures; treat permanent NXDOMAIN as terminal. |
| Redirect chain exceeds `max_redirect_hops` | `RuntimeError: redirect chain exceeded max_redirect_hops=N` | Caller surfaces the error. Raise the cap in `settings/local.yaml` only after verifying the destination chain is trusted. |
| Malformed tool output (bad UTF-8, broken HTML) | `charset-normalizer` fallback in `read`; `_TextExtractor` falls back to stripped raw string | Degrade gracefully — text is returned, never raised. |
| `crow-mcp` stdio subprocess dies | `terminal` tool calls raise on `get_crow_session()` | Restart the server (`mahavishnu mcp restart crow`); the subprocess is respawned by the lifespan context. |

## 8. Testing the Defenses

| Concern | Regression test | File |
|---------|-----------------|------|
| All reserved ranges incl. IPv4-mapped IPv6 | `test_validate_url_blocks_all_reserved_ranges` (parametrized) | `tests/unit/mcp/crow/test_path_security.py` |
| Multi-A DNS — block if ANY is private | `test_validate_url_blocks_any_of_multiple_resolved_addrs` | same |
| DNS failure → ValueError | `test_validate_url_dns_failure_raises_value_error` | same |
| Non-http scheme → ValueError | `test_validate_url_rejects_file_scheme`, `test_validate_url_rejects_no_scheme` | same |
| Path traversal (`/etc/passwd`) | `test_resolve_rejects_traversal` | same |
| Symlink escape | `test_resolve_rejects_symlink_escaping_workspace` | same |
| Null-byte injection | `test_resolve_rejects_null_byte` | same |
| Redirect re-validation on every hop | `test_web_fetch_validates_every_redirect_hop` | `tests/unit/mcp/crow/test_web_tools.py` |
| Redirect to `file://` blocked | `test_web_fetch_redirect_to_suspicious_scheme_blocked` | same |
| Redirect chain within cap | `test_web_fetch_redirect_chain_within_max_hops` | same |
| Redirect chain exceeds cap | `test_web_fetch_redirect_chain_exceeds_max_hops` | same |
| Relative `Location` resolved | `test_web_fetch_redirect_to_relative_url_resolves_against_current` | same |
| Batch partial failure isolated | `test_web_fetch_batch_partial_failure` | same |

Run the suite:

```bash
pytest tests/unit/mcp/crow/ -v
```