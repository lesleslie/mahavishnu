#!/usr/bin/env python3
"""Bifrost vs direct-upstream perf A/B comparison.

Designed for ad-hoc perf comparisons before/after a cutover. NOT a load
test — low concurrency (1), small fixed prompt, structured JSON output.

Workflow::

    # 1. Capture baseline against direct upstream (CC pointing at MiniMax).
    #    Note: --allow-remote-base is required because api.minimax.io is
    #    not loopback and the script ships the API key there.
    python scripts/bifrost_perf_compare.py \\
        --label-a direct \\
        --base-a https://api.minimax.io/v1 \\
        --allow-remote-base \\
        --model MiniMax-M3 \\
        --runs 5 \\
        > perf-baseline.json

    # 2. Flip CC onto Bifrost (per spec §5), wait a few minutes, then:
    python scripts/bifrost_perf_compare.py \\
        --label-a bifrost \\
        --base-a http://127.0.0.1:8471/v1 \\
        --model MiniMax-M3 \\
        --runs 5 \\
        > perf-bifrost.json

    # 3. Diff the two:
    diff perf-baseline.json perf-bifrost.json

**Credential-safety default**: by default, only loopback bases
(``127.0.0.1``, ``localhost``) are accepted. To compare against a remote
endpoint (e.g. ``api.minimax.io``), pass ``--allow-remote-base`` so the
script emits a clear warning to stderr before sending the API key.
This guards against accidental credential exfiltration when the
operator mistypes the base URL.

Reports per-endpoint:

- ``ttfb_ms`` — time-to-first-byte (proxy for TTFT in streaming mode)
- ``total_ms`` — wall-clock end-to-end
- ``completion_tokens`` — tokens in the response (rough: ~4 chars/token)
- ``tokens_per_sec`` — completion tokens / generation duration
- ``http_status`` — the upstream response code

Aggregate stats: median across runs. Single-prompt A/B; for richer sweeps
extend with multiple ``--prompt`` invocations of this script.
"""

import argparse
import json
import os
import statistics
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass


DEFAULT_MODEL: str = "MiniMax-M3"
DEFAULT_PROMPT: str = "Reply with a single word: hi"
DEFAULT_RUNS: int = 5
DEFAULT_TIMEOUT: float = 30.0

LOOPBACK_HOSTS: frozenset[str] = frozenset({"127.0.0.1", "localhost", "::1"})

# Cloud-metadata endpoints that must NEVER receive credentials, even with
# --allow-remote-base. Mirrors the v1.5 spec's BifrostLLMSettings IMDS blocklist.
IMDS_BLOCKLIST: frozenset[str] = frozenset(
    {
        "169.254.169.254",
        "169.254.169.253",
        "100.100.100.200",
        "metadata.google.internal",
        "metadata.azure.com",
    }
)


def is_loopback(url: str) -> bool:
    """Return True iff the URL's host is loopback. SSRF-style guard for the API-key path."""
    from urllib.parse import urlparse

    host = (urlparse(url).hostname or "").lower()
    return host in LOOPBACK_HOSTS


def remote_base_url_safety(url: str) -> tuple[bool, str]:
    """For a non-loopback URL, return (ok, reason).

    Non-loopback bases must use https and must not resolve to a cloud-metadata
    endpoint on the IMDS_BLOCKLIST. The IMDS check is hostname-string-based
    (no DNS resolution) so an attacker cannot bypass it via /etc/hosts.
    """
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if parsed.scheme != "https":
        return False, f"non-loopback base requires https (got {parsed.scheme!r})"
    host = (parsed.hostname or "").lower()
    if host in IMDS_BLOCKLIST:
        return False, f"host is on the IMDS / metadata blocklist: {host}"
    return True, "ok"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse 3xx redirects when an Authorization header is set.

    An open redirect on the operator's intended base URL could otherwise
    silently bounce the request to an attacker-controlled host while
    the ``Authorization: Bearer <api_key>`` header stays attached —
    leaking the credential. Refusing to follow redirects is the
    defense-in-depth complement to the URL-string checks above; it does
    not replace them.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Returning None from redirect_request suppresses redirect-following.
        return None


NO_REDIRECT_OPENER = urllib.request.build_opener(_NoRedirect())


@dataclass
class RunMetrics:
    ttfb_ms: float
    total_ms: float
    completion_tokens: int
    tokens_per_sec: float
    http_status: int
    error: str | None = None


def measure(base_url: str, api_key: str, model: str, prompt: str, timeout: float) -> RunMetrics:
    """Issue one streaming chat completion; capture timing + token estimate.

    Returns RunMetrics with ``error`` set on transport failure. Token
    count is a heuristic (~4 chars/token) — for precise counts the
    upstream's ``usage.completion_tokens`` field would be authoritative,
    but that field isn't reliably emitted mid-stream by every provider.
    """
    url = f"{base_url.rstrip('/')}/chat/completions"
    body = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 64,
            "stream": True,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    started = time.monotonic()
    try:
        with NO_REDIRECT_OPENER.open(req, timeout=timeout) as resp:
            http_status = resp.status
            first_byte_at: float | None = None
            buf: list[str] = []
            while True:
                chunk = resp.read(2048)
                if not chunk:
                    break
                if first_byte_at is None:
                    first_byte_at = time.monotonic()
                buf.append(chunk.decode("utf-8", errors="replace"))
            ended = time.monotonic()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
        return RunMetrics(
            ttfb_ms=0.0,
            total_ms=(time.monotonic() - started) * 1000,
            completion_tokens=0,
            tokens_per_sec=0.0,
            http_status=getattr(exc, "code", 0),
            error=f"{type(exc).__name__}: {exc}",
        )
    ttfb_ms = (first_byte_at - started) * 1000 if first_byte_at else 0.0
    total_ms = (ended - started) * 1000
    completion_tokens = max(1, len("".join(buf)) // 4)
    generation_ms = max(1.0, total_ms - ttfb_ms)
    return RunMetrics(
        ttfb_ms=ttfb_ms,
        total_ms=total_ms,
        completion_tokens=completion_tokens,
        tokens_per_sec=completion_tokens / generation_ms * 1000,
        http_status=http_status,
    )


def aggregate(runs: list[RunMetrics]) -> dict:
    """Median across runs (errors excluded). Per-run dict is preserved."""
    ok = [r for r in runs if r.error is None]
    if not ok:
        return {"n": len(runs), "errors": len(runs)}
    return {
        "n": len(runs),
        "errors": len(runs) - len(ok),
        "ttfb_ms_median": statistics.median(r.ttfb_ms for r in ok),
        "total_ms_median": statistics.median(r.total_ms for r in ok),
        "tokens_per_sec_median": statistics.median(r.tokens_per_sec for r in ok),
        "completion_tokens_median": statistics.median(r.completion_tokens for r in ok),
    }


def run_endpoint(
    label: str,
    base_url: str,
    api_key: str,
    model: str,
    prompt: str,
    runs: int,
    timeout: float,
) -> dict:
    samples = [measure(base_url, api_key, model, prompt, timeout) for _ in range(runs)]
    return {
        "label": label,
        "base_url": base_url,
        "runs": [asdict(r) for r in samples],
        "aggregate": aggregate(samples),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="A/B perf comparison across two upstream bases (Bifrost vs direct).",
    )
    parser.add_argument("--label-a", default="a", help="Label for endpoint A (e.g. 'direct')")
    parser.add_argument("--base-a", required=True, help="Base URL for endpoint A")
    parser.add_argument("--label-b", default="b", help="Label for endpoint B (e.g. 'bifrost')")
    parser.add_argument("--base-b", help="Base URL for endpoint B (omit for single-endpoint mode)")
    parser.add_argument(
        "--api-key",
        default=os.environ.get("MINIMAX_API_KEY"),
        help="API key (default: $MINIMAX_API_KEY)",
    )
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--runs", type=int, default=DEFAULT_RUNS)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    parser.add_argument(
        "--allow-remote-base",
        action="store_true",
        help="Allow non-loopback base URLs (e.g. api.minimax.io). Required for "
        "before/after comparison against a remote upstream; the script emits a "
        "warning to stderr when this is set.",
    )
    args = parser.parse_args()

    if not args.api_key:
        print("error: --api-key or $MINIMAX_API_KEY required", file=sys.stderr)
        return 2
    if not args.base_b:
        print("hint: pass --base-b for an A/B run; single-endpoint mode otherwise", file=sys.stderr)

    bases: list[tuple[str, str]] = [(args.label_a, args.base_a)]
    if args.base_b:
        bases.append((args.label_b, args.base_b))
    remote_bases = [(label, url) for label, url in bases if not is_loopback(url)]
    if remote_bases and not args.allow_remote_base:
        joined = ", ".join(f"{label}={url}" for label, url in remote_bases)
        print(
            f"refusing to send API key to non-loopback base(s): {joined}. "
            "Re-run with --allow-remote-base if the endpoint is trusted.",
            file=sys.stderr,
        )
        return 2
    if remote_bases:
        for label, url in remote_bases:
            ok, reason = remote_base_url_safety(url)
            if not ok:
                print(
                    f"refusing remote base {label}={url}: {reason}",
                    file=sys.stderr,
                )
                return 2
        joined = ", ".join(f"{label}={url}" for label, url in remote_bases)
        print(
            f"WARNING: sending API key to non-loopback endpoint(s): {joined}. "
            "Verify the URL is trusted.",
            file=sys.stderr,
        )

    out: dict = {
        "prompt": args.prompt,
        "model": args.model,
        "runs_per_endpoint": args.runs,
        "endpoints": [
            run_endpoint(
                args.label_a,
                args.base_a,
                args.api_key,
                args.model,
                args.prompt,
                args.runs,
                args.timeout,
            )
        ],
    }
    if args.base_b:
        out["endpoints"].append(
            run_endpoint(
                args.label_b,
                args.base_b,
                args.api_key,
                args.model,
                args.prompt,
                args.runs,
                args.timeout,
            )
        )
    print(json.dumps(out, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
