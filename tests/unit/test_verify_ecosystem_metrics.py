"""Tests for ecosystem metrics verification helpers."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

_MODULE_PATH = Path("scripts/verify_ecosystem_metrics.py")
_SPEC = spec_from_file_location("verify_ecosystem_metrics", _MODULE_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)

build_verified_target_groups = _MODULE.build_verified_target_groups
is_prometheus_text = _MODULE.is_prometheus_text
load_inventory = _MODULE.load_inventory
probe_service = _MODULE.probe_service


def test_is_prometheus_text_accepts_openmetrics_content():
    """Prometheus exposition markers should be accepted for valid content types."""
    assert is_prometheus_text("text/plain; version=0.0.4", "# HELP foo\n# TYPE foo counter\n")
    assert is_prometheus_text(
        "application/openmetrics-text; version=1.0.0",
        "# HELP foo\n# TYPE foo counter\n",
    )


def test_is_prometheus_text_rejects_non_prometheus_payload():
    """JSON or marker-free responses should not be treated as Prometheus exposition."""
    assert not is_prometheus_text("application/json", '{"status":"ok"}')
    assert not is_prometheus_text("text/plain", "plain text without markers")


def test_load_inventory_reads_services():
    """Inventory loader should return the configured service list."""
    services = load_inventory(Path("monitoring/ecosystem_metrics_inventory.yml"))

    assert services
    assert any(service["name"] == "mahavishnu" for service in services)


def test_build_verified_target_groups_filters_failures():
    """Only successful probes should be promoted into file_sd target groups."""
    results = [
        {
            "name": "mahavishnu",
            "repo": "mahavishnu",
            "role": "orchestrator",
            "scrape_target": "host.docker.internal:8680",
            "ok": True,
        },
        {
            "name": "session-buddy",
            "repo": "session-buddy",
            "role": "manager",
            "scrape_target": "host.docker.internal:8678",
            "ok": False,
        },
    ]

    groups = build_verified_target_groups(results)

    assert groups == [
        {
            "targets": ["host.docker.internal:8680"],
            "labels": {
                "service": "mahavishnu",
                "repo": "mahavishnu",
                "role": "orchestrator",
                "verification_status": "verified",
                "metrics_contract": "prometheus_text",
            },
        }
    ]


def test_probe_service_derives_scrape_target_from_successful_probe(monkeypatch):
    """Successful probe URLs should become scrape targets when not specified."""

    class DummyHeaders(dict):
        def get(self, key, default=None):
            return super().get(key, default)

    class DummyResponse:
        def __init__(self):
            self.status = 200
            self.headers = DummyHeaders({"Content-Type": "text/plain; version=0.0.4"})

        def read(self):
            return b"# HELP foo test\n# TYPE foo counter\nfoo_total 1\n"

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(_MODULE, "urlopen", lambda request, timeout=0: DummyResponse())

    result = probe_service(
        {
            "name": "session-buddy",
            "repo": "session-buddy",
            "role": "manager",
            "probe_urls": ["http://localhost:9090/metrics"],
        },
        timeout=1.0,
    )

    assert result["ok"] is True
    assert result["probe_url"] == "http://localhost:9090/metrics"
    assert result["scrape_target"] == "host.docker.internal:9090"
