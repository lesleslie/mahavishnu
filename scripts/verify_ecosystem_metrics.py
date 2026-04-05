#!/usr/bin/env python3
"""Verify Bodai ecosystem Prometheus metrics endpoints."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import yaml

PROMETHEUS_CONTENT_TYPES = ("text/plain", "application/openmetrics-text")
PROMETHEUS_MARKERS = ("# HELP", "# TYPE")


def load_inventory(path: Path) -> list[dict[str, Any]]:
    """Load service inventory from YAML."""
    with path.open() as f:
        data = yaml.safe_load(f) or {}
    services = data.get("services", [])
    if not isinstance(services, list):
        raise ValueError(f"Invalid inventory format in {path}")
    return services


def is_prometheus_text(content_type: str, body: str) -> bool:
    """Check whether a response looks like Prometheus exposition text."""
    normalized = (content_type or "").split(";", 1)[0].strip().lower()
    if normalized and normalized not in PROMETHEUS_CONTENT_TYPES:
        return False
    return any(marker in body for marker in PROMETHEUS_MARKERS)


def probe_service(service: dict[str, Any], timeout: float) -> dict[str, Any]:
    """Probe a single service metrics endpoint."""
    probe_urls = service.get("probe_urls")
    if not probe_urls:
        probe_url = service.get("probe_url")
        probe_urls = [probe_url] if probe_url else []
    if not probe_urls:
        raise ValueError(f"Service {service['name']} is missing probe_urls")

    result = {
        "name": service["name"],
        "repo": service.get("repo", service["name"]),
        "role": service.get("role", "unknown"),
        "verification_status": service.get("verification_status", "candidate"),
        "required": bool(service.get("required", False)),
        "scrape_target": service.get("scrape_target"),
        "probe_url": None,
        "probe_urls": probe_urls,
        "metrics_path": service.get("metrics_path", "/metrics"),
        "ok": False,
        "status_code": None,
        "content_type": None,
        "reason": "",
    }

    failure_reasons: list[str] = []

    for probe_url in probe_urls:
        result["probe_url"] = probe_url
        request = Request(
            probe_url,
            headers={"Accept": "text/plain, application/openmetrics-text;q=0.9, */*;q=0.1"},
        )
        try:
            with urlopen(request, timeout=timeout) as response:
                body = response.read().decode("utf-8", errors="replace")
                content_type = response.headers.get("Content-Type", "")
                result["status_code"] = response.status
                result["content_type"] = content_type
                if response.status != 200:
                    failure_reasons.append(f"{probe_url} -> unexpected HTTP status {response.status}")
                    continue
                if not is_prometheus_text(content_type, body):
                    failure_reasons.append(
                        f"{probe_url} -> endpoint did not return recognizable Prometheus text"
                    )
                    continue

                result["ok"] = True
                result["reason"] = "prometheus_text"
                if not result["scrape_target"]:
                    parsed = urlparse(probe_url)
                    if parsed.hostname and parsed.port:
                        host = (
                            "host.docker.internal"
                            if parsed.hostname in {"127.0.0.1", "localhost"}
                            else parsed.hostname
                        )
                        result["scrape_target"] = f"{host}:{parsed.port}"
                return result
        except HTTPError as exc:
            failure_reasons.append(f"{probe_url} -> http_error: {exc.code}")
        except URLError as exc:
            failure_reasons.append(f"{probe_url} -> url_error: {exc.reason}")
        except Exception as exc:  # pragma: no cover - defensive guard
            failure_reasons.append(f"{probe_url} -> error: {exc}")

    result["reason"] = "; ".join(failure_reasons) if failure_reasons else "no probe attempts executed"

    return result


def build_verified_target_groups(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert successful probes into Prometheus file_sd target groups."""
    groups: list[dict[str, Any]] = []
    for result in results:
        if not result["ok"]:
            continue
        groups.append(
            {
                "targets": [result["scrape_target"]],
                "labels": {
                    "service": result["name"],
                    "repo": result["repo"],
                    "role": result["role"],
                    "verification_status": "verified",
                    "metrics_contract": "prometheus_text",
                },
            }
        )
    return groups


def write_verified_targets(results: list[dict[str, Any]], output_path: Path) -> None:
    """Write successful targets in Prometheus file_sd format."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    target_groups = build_verified_target_groups(results)
    with output_path.open("w") as f:
        yaml.safe_dump(target_groups, f, sort_keys=False)


def render_text_report(results: list[dict[str, Any]]) -> str:
    """Render a human-readable verification report."""
    lines = []
    for result in results:
        status = "PASS" if result["ok"] else "FAIL"
        lines.append(
            f"{status:4} {result['name']:14} {result['probe_url']} "
            f"[{result['verification_status']}] {result['reason']}"
        )
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    """Parse command-line options."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--inventory",
        type=Path,
        default=Path("monitoring/ecosystem_metrics_inventory.yml"),
        help="Path to ecosystem metrics inventory YAML.",
    )
    parser.add_argument(
        "--write-verified-file",
        type=Path,
        default=None,
        help="Write successful probes to a Prometheus file_sd YAML file.",
    )
    parser.add_argument(
        "--output",
        choices=("text", "json"),
        default="text",
        help="Output report format.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=2.0,
        help="Per-endpoint probe timeout in seconds.",
    )
    parser.add_argument(
        "--service",
        action="append",
        default=[],
        help="Probe only the named service. Repeatable.",
    )
    return parser.parse_args()


def main() -> int:
    """Run verification and optionally update the verified target file."""
    args = parse_args()
    services = load_inventory(args.inventory)
    selected = set(args.service)
    if selected:
        services = [service for service in services if service["name"] in selected]

    results = [probe_service(service, args.timeout) for service in services]

    if args.write_verified_file:
        write_verified_targets(results, args.write_verified_file)

    if args.output == "json":
        print(json.dumps(results, indent=2))
    else:
        print(render_text_report(results))

    failures = [
        result
        for result in results
        if not result["ok"] and (result["required"] or result["verification_status"] == "verified")
    ]
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
