"""metrics_enabled and tracing_enabled gate two independent signals.

They were declared as independent ``ObservabilityConfig`` fields but wired to
one: ``__init__`` tested ``metrics_enabled`` alone before calling
``_init_otel_components``. Turning metrics off therefore also turned tracing
off and dropped the process to MockTracer/MockMeter.

That coupling is not cosmetic here. akosha's OTLP receiver implements
TraceService only, so metric exports to :4317 fail with UNIMPLEMENTED every
60 seconds — an operator who wants the spam gone must disable metrics, and the
old wiring then silently discards the spans the receiver actually wants.
"""

from __future__ import annotations

import importlib
from typing import Any

import pytest

from mahavishnu.core import observability as obs_mod


@pytest.fixture
def mod() -> Any:
    """A freshly-reloaded observability module.

    ``test_observability.py`` monkeypatches this module's OTel symbols and
    reloads it, and does not restore them. Left alone, a later test gets a
    stubbed ``Resource`` and ``_init_otel_components`` raises inside its own
    try/except and falls back to mocks -- correct behaviour, but for the wrong
    reason, which makes any assertion about the real path meaningless.

    Reloading per-test makes these tests hermetic against whatever ran before.
    """
    return importlib.reload(obs_mod)


@pytest.fixture
def obs(mod: Any) -> Any:
    if not mod.OTEL_AVAILABLE:
        pytest.skip("opentelemetry not installed")
    return mod


def _config(obs: Any, *, metrics: bool, tracing: bool) -> Any:
    from mahavishnu.core.config import ObservabilityConfig

    class _Cfg:
        observability = ObservabilityConfig(
            metrics_enabled=metrics, tracing_enabled=tracing
        )
        log_level = "INFO"

    return _Cfg()


@pytest.fixture
def count_metric_readers(obs: Any, monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Count OTLP metric readers constructed, without exporting anything."""
    built: list[int] = []
    real = obs.PeriodicExportingMetricReader

    def _spy(*a: Any, **k: Any) -> Any:
        built.append(1)
        return real(*a, **k)

    monkeypatch.setattr(obs, "PeriodicExportingMetricReader", _spy)
    return built


def test_metrics_off_tracing_on_keeps_real_tracing(
    obs: Any, count_metric_readers: list[int]
) -> None:
    """The case that motivated the change: kill the spam, keep the spans."""
    mgr = obs.ObservabilityManager(_config(obs, metrics=False, tracing=True))

    assert not isinstance(mgr.tracer, obs.MockTracer), (
        "disabling metrics must not drop tracing to the mock tracer -- akosha's "
        "receiver is consuming those spans"
    )
    assert not isinstance(mgr.meter, obs.MockMeter)
    assert count_metric_readers == [], (
        "no OTLP metric reader may be built when metrics_enabled is false; "
        ":4317 has no MetricsService and every export fails"
    )


def test_metrics_on_still_builds_the_reader(
    obs: Any, count_metric_readers: list[int]
) -> None:
    """The flag must actually do something when flipped the other way."""
    obs.ObservabilityManager(_config(obs, metrics=True, tracing=True))
    assert len(count_metric_readers) == 1


def test_both_off_falls_back_to_mocks(
    obs: Any, count_metric_readers: list[int]
) -> None:
    """Both signals off is the only case that legitimately wants mocks."""
    mgr = obs.ObservabilityManager(_config(obs, metrics=False, tracing=False))
    assert isinstance(mgr.tracer, obs.MockTracer)
    assert isinstance(mgr.meter, obs.MockMeter)
    assert count_metric_readers == []


def test_instruments_survive_with_metrics_disabled(obs: Any) -> None:
    """Every instrument built from self.meter must stay usable.

    Disabling export must not mean "self.meter is None". The recording call
    sites are scattered across the codebase; a missing instrument turns a
    metrics decision into an AttributeError three call frames away.
    """
    mgr = obs.ObservabilityManager(_config(obs, metrics=False, tracing=True))

    for name in (
        "workflow_counter",
        "repo_counter",
        "error_counter",
        "workflow_duration_histogram",
    ):
        instrument = getattr(mgr, name, None)
        assert instrument is not None, f"{name} missing when metrics are disabled"
        if hasattr(instrument, "add"):
            instrument.add(1)
        else:
            instrument.record(1.0)