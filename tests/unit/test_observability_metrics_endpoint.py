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

    ``test_observability.py`` monkeypatches this module's OTel symbols and
    reloads it, and does not restore them. Left alone, a later test gets a
    stubbed ``Resource`` and ``_init_otel_components`` raises inside its own
    try/except and falls back to mocks -- correct behaviour, but for the wrong
    reason, which makes any assertion about the real path meaningless.
    """
    return importlib.reload(importlib.import_module("mahavishnu.core.observability"))


def _config(*, metrics: bool = True) -> Any:
    class _Cfg:
        observability = ObservabilityConfig(
            metrics_enabled=metrics,
            tracing_enabled=True,
            otlp_endpoint=_FAKE_OTLP,
        )
        log_level = "INFO"

    return _Cfg()


def _capture_endpoints(
    mod: Any, monkeypatch: pytest.MonkeyPatch
) -> dict[str, list[str]]:
    """Record the endpoint every exporter was built with."""
    captured: dict[str, list[str]] = {"metric": [], "span": []}
    real_metric = mod.OTLPMetricExporter
    real_span = mod.OTLPSpanExporter

    def _metric_spy(*a: Any, **k: Any) -> Any:
        captured["metric"].append(str(k.get("endpoint")))
        return real_metric(*a, **k)

    def _span_spy(*a: Any, **k: Any) -> Any:
        captured["span"].append(str(k.get("endpoint")))
        return real_span(*a, **k)

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
    """Fail loud where it is safe to, rather than silently exporting nowhere.

    The YAML path is filtered (see the fail-soft test below), but the
    ``MAHAVISHNU_OBSERVABILITY__*`` overlay merges AFTER that filter, so an
    operator who still exports the old variable gets a startup error naming
    the removed key -- instead of metrics quietly going to a dead path.
    """
    with pytest.raises(ValidationError):
        ObservabilityConfig.model_validate(
            {"otlp_metrics_endpoint": "http://127.0.0.1:14317"}
        )


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
    """
    captured = _capture_endpoints(mod, monkeypatch)

    mod.ObservabilityManager(_config(metrics=True))

    assert captured["metric"] == [_FAKE_OTLP]
    assert captured["span"] == [_FAKE_OTLP]


def test_disabling_metrics_still_builds_no_metric_exporter(
    mod: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The flag still gates export; only the endpoint changed.

    Without this, "the exporter targets otlp_endpoint" could be satisfied by
    an exporter that is always built -- which would export the series whether
    or not the operator asked for it.
    """
    captured = _capture_endpoints(mod, monkeypatch)

    mod.ObservabilityManager(_config(metrics=False))

    assert captured["metric"] == []
    assert captured["span"] == [_FAKE_OTLP]
