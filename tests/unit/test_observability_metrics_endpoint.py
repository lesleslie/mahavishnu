"""The metric exporter's endpoint after the interim split was retired.

``observability.otlp_metrics_endpoint`` existed because akosha's :4317
receiver implemented TraceService only, so metrics had to go somewhere else
(Alloy's receiver on :14317). The receiver now implements MetricsService too,
so metrics and traces share one endpoint and the interim field is gone.

These tests pin the REMOVAL as well as the new behaviour. A field that
silently came back would re-split the two paths, and the symptom would be
metrics failing to export again -- with no config change to point at.
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
_FAKE_OTLP = "http://substrate.invalid:4317"


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

    def force_flush(self, *args: Any, **kwargs: Any) -> bool:
        return True

    def shutdown(self, *args: Any, **kwargs: Any) -> None:
        return None


def _config(*, metrics: bool = True) -> Any:
    class _Cfg:
        observability = ObservabilityConfig(
            metrics_enabled=metrics,
            tracing_enabled=True,
            otlp_endpoint=_FAKE_OTLP,
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
    """Record the endpoint every exporter was built with."""
    captured: dict[str, list[str]] = {"metric": [], "span": []}
    real_metric = mod.OTLPMetricExporter

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

    monkeypatch.setattr(mod, "OTLPMetricExporter", _metric_spy)
    monkeypatch.setattr(mod, "OTLPSpanExporter", _span_spy)
    return captured


def test_the_interim_field_is_gone() -> None:
    """The field must not linger as a no-op.

    A field that stayed would re-split the two paths the moment somebody set
    it, and nothing in the config would say why.
    """
    assert "otlp_metrics_endpoint" not in ObservabilityConfig.model_fields
    assert not hasattr(ObservabilityConfig(), "otlp_metrics_endpoint")


def test_setting_the_removed_field_is_an_error() -> None:
    """The nested model rejects a key it no longer declares.

    This is the ``extra="forbid"`` half of the behaviour; the env-var half,
    which is the one an operator actually hits, is tested below.
    """
    with pytest.raises(ValidationError):
        ObservabilityConfig.model_validate(
            {"otlp_metrics_endpoint": "http://127.0.0.1:14317"}
        )


def test_the_removed_env_var_is_fatal(monkeypatch: pytest.MonkeyPatch) -> None:
    """An operator who still exports the old variable gets a loud failure.

    The YAML path is filtered (see the fail-soft test below), but the
    ``MAHAVISHNU_OBSERVABILITY__*`` overlay merges AFTER that filter, so the
    env var reaches validation and is rejected -- the operator gets a startup
    error naming the removed key, instead of metrics quietly going to a dead
    path.

    Exercised through the settings model rather than through
    ``ObservabilityConfig`` directly, because only the settings model reads
    env vars: the property under test is about the ENV VAR.
    """
    monkeypatch.setenv(
        "MAHAVISHNU_OBSERVABILITY__OTLP_METRICS_ENDPOINT",
        "http://127.0.0.1:14317",
    )
    with pytest.raises(ValidationError):
        MahavishnuSettings()


def test_a_dead_yaml_key_is_dropped_rather_than_raising() -> None:
    """The operator's ``local.yaml`` is not allowed to break the CLI.

    ``_filter_subconfig_keys`` strips keys the sub-config does not declare
    BEFORE ``MahavishnuSettings(**merged)`` runs, so a leftover key under
    ``observability:`` is ignored rather than fatal. That is why removing
    the field did not require removing the key from ``local.yaml`` first --
    but the key is still removed, because a dead key that names a retired
    path reads as configuration.
    """
    annotation = MahavishnuSettings.model_fields["observability"].annotation
    filtered = _filter_subconfig_keys(
        {
            "metrics_enabled": True,
            "otlp_metrics_endpoint": "http://127.0.0.1:14317",
        },
        annotation,
    )
    assert filtered == {"metrics_enabled": True}


def test_the_metric_exporter_targets_the_shared_endpoint(
    mod: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Metrics and traces must go to the SAME receiver.

    The interim field let them diverge, and when they did the metric path
    failed every export while the trace path kept working -- a split that
    looked like a metrics problem and was really a config one.

    The fallback assertion is load-bearing. ``_init_otel_components`` catches
    every exception and falls back to mocks, and the exporters are built
    BEFORE the fallible work that follows them. A test that only checks
    which endpoint the exporter was built with therefore stays green while
    the manager silently exports NOTHING -- the exact failure this whole
    change exists to prevent.
    """
    captured = _capture_endpoints(mod, monkeypatch)

    manager = mod.ObservabilityManager(_config(metrics=True))

    assert captured["metric"] == [_FAKE_OTLP]
    assert captured["span"] == [_FAKE_OTLP]
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

    Without this, "the exporter targets otlp_endpoint" could be satisfied by
    an exporter that is always built -- which would export the series whether
    or not the operator asked for it.

    The assertion is about the exporter being CONSTRUCTED, not about the
    manager's meter: OTel's global meter provider is set once per process,
    so a meter handed out after an earlier test can still belong to an
    exporting provider. That is a constraint of the SDK, not of this
    change, and it is why the assertion is scoped to construction.
    """
    captured = _capture_endpoints(mod, monkeypatch)

    manager = mod.ObservabilityManager(_config(metrics=False))

    assert captured["metric"] == []
    assert captured["span"] == [_FAKE_OTLP]
    assert not isinstance(manager.tracer, mod.MockTracer), (
        "tracing must still be real when metrics are off -- that "
        "independence is the property the gating tests exist for"
    )
