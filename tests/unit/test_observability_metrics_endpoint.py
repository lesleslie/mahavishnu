"""Where the OTLP exporters send their signals, and over what transport.

``observability.otlp_metrics_endpoint`` was removed once akosha's :4317
receiver implemented MetricsService beside TraceService, so metrics and
traces could share one endpoint. That was true for the **gRPC** transport
only.

The gRPC transport is what had to go: mahavishnu forks constantly, and
grpcio's background threads make every fork produce a child that dies with
SIGILL on macOS ("BUG IN CLIENT OF LIBDISPATCH: trying to lock
recursively"). See ``docs/decisions/2026-11-16-no-grpc-in-forking-processes.md``.

Over OTLP/HTTP the two signals MUST diverge, because the substrate's HTTP
listener serves ``/v1/traces`` only. So the split comes back -- with the
destinations the canonical port-ownership decision already names: traces to
the substrate (:4318), metrics to Alloy (:14318) and on to Grafana.

These tests pin the split, the transport, and the fact that the field is a
real, honored knob rather than a decoration.
"""

from __future__ import annotations

import importlib
from typing import Any

from pydantic import ValidationError
import pytest

from mahavishnu.core.config import (
    MahavishnuSettings,
    ObservabilityConfig,
    _filter_subconfig_keys,
)

# A deliberately unresolvable host: the exporters are lazy about connecting,
# but a real endpoint here would let a test pass by reaching a live server.
_FAKE_TRACES = "http://substrate.invalid:4318"
_FAKE_METRICS = "http://alloy.invalid:14318"


@pytest.fixture
def mod() -> Any:
    """A freshly-reloaded observability module.

    Reloading per-test keeps these tests hermetic against whatever ran
    before them: ``_init_otel_components`` catches every exception and
    falls back to mocks, so a module left in a stubbed state makes the
    REAL path unreachable -- correct behaviour, but for the wrong reason,
    which makes any assertion about that path meaningless.
    """
    return importlib.reload(importlib.import_module("mahavishnu.core.observability"))


class _StubExporter:
    """A stand-in for the OTel exporters, carrying the SDK's private hints.

    The real exporters start a retrying export thread against whatever host
    they are given, and that thread outlives the assertion -- a test that
    points at ``substrate.invalid`` produces DNS-failure noise long after
    the test has finished.

    The SDK reads two PRIVATE attributes off a metric exporter
    (``_preferred_temporality`` and ``_preferred_aggregation``) and both
    are per-instrument-type dicts that differ across SDK versions, so they
    are copied off a real exporter rather than hand-written.
    """

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self._preferred_temporality: Any = None
        self._preferred_aggregation: Any = None

    def export(self, *args: Any, **kwargs: Any) -> None:
        return None

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True

    def shutdown(self, *args: Any, **kwargs: Any) -> None:
        # The SDK calls ``shutdown(timeout=...)``; the stub must accept it
        # or the atexit hook raises and buries the real test output.
        return None


def _config(*, metrics: bool = True) -> Any:
    class _Cfg:
        observability = ObservabilityConfig(
            metrics_enabled=metrics,
            tracing_enabled=True,
            otlp_endpoint=_FAKE_TRACES,
            otlp_metrics_endpoint=_FAKE_METRICS,
        )
        # The top-level switch is an OR with the nested one. It is off here
        # so the nested flag alone decides, which is the only way to
        # exercise "metrics disabled" at all -- on the deployed host the
        # top-level flag is ON, so the nested flag alone cannot turn export
        # off.
        otel_metrics_enabled = False
        log_level = "INFO"

    return _Cfg()


def _capture_endpoints(
    mod: Any, monkeypatch: pytest.MonkeyPatch
) -> dict[str, list[str]]:
    """Record the endpoint every exporter was built with.

    The exporters are imported lazily inside the builders, so the seam is
    the exporter MODULE -- patching a name on the observability module would
    be patching nothing.
    """
    from opentelemetry.exporter.otlp.proto.http import metric_exporter as http_metric
    from opentelemetry.exporter.otlp.proto.http import trace_exporter as http_trace

    captured: dict[str, list[str]] = {"metric": [], "span": []}
    real_metric = http_metric.OTLPMetricExporter

    def _metric_spy(**kwargs: Any) -> Any:
        captured["metric"].append(str(kwargs.get("endpoint")))
        stub = _StubExporter(**kwargs)
        reference = real_metric(**kwargs)
        stub._preferred_temporality = reference._preferred_temporality
        stub._preferred_aggregation = reference._preferred_aggregation
        return stub

    def _span_spy(**kwargs: Any) -> Any:
        captured["span"].append(str(kwargs.get("endpoint")))
        return _StubExporter(**kwargs)

    monkeypatch.setattr(http_metric, "OTLPMetricExporter", _metric_spy)
    monkeypatch.setattr(http_trace, "OTLPSpanExporter", _span_spy)
    return captured


def test_the_metrics_field_is_declared_and_honored() -> None:
    """The field must be a real knob, not a decoration.

    An operator who points metrics at a different receiver needs the field
    to exist; a field that is ignored would send the series somewhere the
    operator did not choose and report success.
    """
    assert "otlp_metrics_endpoint" in ObservabilityConfig.model_fields
    config = ObservabilityConfig()
    assert config.otlp_metrics_endpoint
    assert config.otlp_endpoint != config.otlp_metrics_endpoint, (
        "traces and metrics must not default to the same receiver: the "
        "substrate's OTLP/HTTP listener serves /v1/traces only"
    )


def test_the_metrics_env_var_is_accepted() -> None:
    """``MAHAVISHNU_OBSERVABILITY__OTLP_METRICS_ENDPOINT`` is honored.

    Exercised through the settings model rather than through
    ``ObservabilityConfig`` directly, because only the settings model reads
    env vars: the property under test is about the ENV VAR.
    """
    import os

    os.environ["MAHAVISHNU_OBSERVABILITY__OTLP_METRICS_ENDPOINT"] = _FAKE_METRICS
    try:
        settings = MahavishnuSettings()
    finally:
        del os.environ["MAHAVISHNU_OBSERVABILITY__OTLP_METRICS_ENDPOINT"]
    assert settings.observability.otlp_metrics_endpoint == _FAKE_METRICS


def test_a_yaml_key_for_a_field_that_does_not_exist_is_dropped() -> None:
    """The operator's ``local.yaml`` is not allowed to break the CLI.

    ``_filter_subconfig_keys`` strips keys the sub-config does not declare
    BEFORE ``MahavishnuSettings(**merged)`` runs, so a leftover key under
    ``observability:`` is ignored rather than fatal.
    """
    annotation = MahavishnuSettings.model_fields["observability"].annotation
    filtered = _filter_subconfig_keys(
        {
            "metrics_enabled": True,
            "otlp_metrics_endpoint": _FAKE_METRICS,
        },
        annotation,
    )
    assert filtered == {
        "metrics_enabled": True,
        "otlp_metrics_endpoint": _FAKE_METRICS,
    }


def test_an_undeclared_key_is_still_rejected_by_the_model() -> None:
    """The nested model rejects a key it does not declare.

    This is the ``extra="forbid"`` half of the behaviour.
    """
    with pytest.raises(ValidationError):
        ObservabilityConfig.model_validate({"otlp_metrics_endpiont": "typo"})


def test_the_two_signals_target_different_receivers(
    mod: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Traces go to the substrate; metrics go to Alloy.

    The fallback assertion is load-bearing. ``_init_otel_components`` catches
    every exception and falls back to mocks, and the exporters are built
    BEFORE the fallible work that follows them. A test that only checks
    which endpoint the exporter was built with therefore stays green while
    the manager silently exports NOTHING -- the exact failure this whole
    change exists to prevent.
    """
    captured = _capture_endpoints(mod, monkeypatch)

    manager = mod.ObservabilityManager(_config(metrics=True))

    assert captured["span"] == [f"{_FAKE_TRACES}/v1/traces"]
    assert captured["metric"] == [f"{_FAKE_METRICS}/v1/metrics"]
    assert not isinstance(manager.meter, mod.MockMeter), (
        "the manager fell back to mocks: OTel init raised after the "
        "exporters were built, so the endpoints look right while nothing "
        "is exported at all"
    )
    assert not isinstance(manager.tracer, mod.MockTracer)


def test_disabling_metrics_still_builds_no_metric_exporter(
    mod: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The flag still gates export; only the endpoint changed.

    Without this, "the exporter targets otlp_metrics_endpoint" could be
    satisfied by an exporter that is always built -- which would export the
    series whether or not the operator asked for it.

    The assertion is about the exporter being CONSTRUCTED, not about the
    manager's meter: OTel's global meter provider is set once per process,
    so a meter handed out after an earlier test can still belong to an
    exporting provider. That is a constraint of the SDK, not of this
    change, and it is why the assertion is scoped to construction.
    """
    captured = _capture_endpoints(mod, monkeypatch)

    manager = mod.ObservabilityManager(_config(metrics=False))

    assert captured["metric"] == []
    assert captured["span"] == [f"{_FAKE_TRACES}/v1/traces"]
    assert not isinstance(manager.tracer, mod.MockTracer), (
        "tracing must still be real when metrics are off -- that "
        "independence is the property the gating tests exist for"
    )
