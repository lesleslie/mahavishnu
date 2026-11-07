"""Span-cardinality guard for the eval subsystem (REQ-EVAL-011).

The v7 substrate's ``spans_substrate`` storage has a cardinality alarm
(``docs/specs/2026-10-19-bodai-substrate-otel-v7.md`` §11.1.6) that
fires when a span carries unbounded attribute keys. The ``eval.*``
keyspace is **fixed and closed**: per-case data belongs in the run
store, not in span attributes.

This test is that alarm's pre-flight. It captures the real
``eval.run_suite`` span and asserts the attribute key set is *exactly*
:data:`mahavishnu.core.eval.engine.SPAN_ATTRIBUTE_KEYS` — no extra
keys, no missing keys — so a regression that adds ``eval.case_id`` or
``eval.case.*`` fails here instead of in production.

The tracer is patched for the test only: the engine's module-level
``_tracer`` is swapped for one bound to a local ``TracerProvider``
with an in-memory exporter. The global provider is left alone, so the
test is order-independent.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)
import pytest

from mahavishnu.core.eval import engine as engine_module
from mahavishnu.core.eval.engine import SPAN_ATTRIBUTE_KEYS
from mahavishnu.core.eval.model_backends.mock import MockModelBackend
from mahavishnu.core.eval.storage_backends.sqlite import SqliteEvalStorage

if TYPE_CHECKING:
    from pathlib import Path

    from mahavishnu.core.eval.dataset import Dataset

# req: REQ-EVAL-011


def _dataset() -> Dataset:
    """A two-case dataset."""
    from mahavishnu.core.eval.dataset import Dataset, DatasetCase

    return Dataset(
        name="golden",
        cases=[
            DatasetCase(id="c1", input="ping", expected="ping", metadata={}),
            DatasetCase(id="c2", input="pong", expected="pong", metadata={}),
        ],
        content_hash="hash-1",
        version="v0",
    )


@pytest.mark.integration
@pytest.mark.req(["REQ-EVAL-011"])
async def test_run_suite_span_carries_exactly_the_closed_keyspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The eval.run_suite span's eval.* keys are exactly the allowed set."""
    from mahavishnu.core.eval.engine import EvalEngine, EvalSuite, ModelConfig
    from mahavishnu.core.eval.scorers.exact_match import ExactMatchScorer

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(
        engine_module, "_tracer", provider.get_tracer("eval-cardinality-test")
    )

    storage = SqliteEvalStorage(tmp_path / "runs.sqlite")
    engine = EvalEngine(storage=storage, model_backend=MockModelBackend())
    suite = EvalSuite(
        name="golden",
        version="v0",
        dataset=_dataset(),
        scorers=[ExactMatchScorer()],
        model=ModelConfig(name="mahavishnu.mock"),
    )

    await engine.run_suite(suite)

    spans = exporter.get_finished_spans()
    eval_spans = [span for span in spans if span.name == "eval.run_suite"]
    assert len(eval_spans) == 1, (
        f"expected one eval.run_suite span, got {len(eval_spans)}"
    )

    attributes = eval_spans[0].attributes or {}
    eval_keys = {key for key in attributes if key.startswith("eval.")}

    assert eval_keys == set(SPAN_ATTRIBUTE_KEYS), (
        "the eval.* span keyspace is fixed and closed; "
        f"unexpected={sorted(eval_keys - set(SPAN_ATTRIBUTE_KEYS))} "
        f"missing={sorted(set(SPAN_ATTRIBUTE_KEYS) - eval_keys)}"
    )


@pytest.mark.integration
@pytest.mark.req(["REQ-EVAL-011"])
async def test_a_failed_run_marks_its_span_as_failed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed run's span says so, and stays inside the closed keyspace.

    The span is the run's rollback signal: the plan's contract says a
    failed run is visible as ``eval.outcome="failed"``. Without it, a
    failed run's span is indistinguishable from a span the process
    never got to instrument.
    """
    from mahavishnu.core.errors import EvalStorageError
    from mahavishnu.core.eval.engine import EvalEngine, EvalSuite, ModelConfig
    from mahavishnu.core.eval.scorers.exact_match import ExactMatchScorer

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(
        engine_module, "_tracer", provider.get_tracer("eval-cardinality-test")
    )

    class _FailingStorage(SqliteEvalStorage):
        """A store that fails on the first case result."""

        async def add_case_result(self, *args: object, **kwargs: object) -> None:
            raise EvalStorageError("simulated disk failure")

    storage = _FailingStorage(tmp_path / "runs.sqlite")
    engine = EvalEngine(storage=storage, model_backend=MockModelBackend())
    suite = EvalSuite(
        name="golden",
        version="v0",
        dataset=_dataset(),
        scorers=[ExactMatchScorer()],
        model=ModelConfig(name="mahavishnu.mock"),
    )

    with pytest.raises(Exception):
        await engine.run_suite(suite)

    span = next(
        span for span in exporter.get_finished_spans() if span.name == "eval.run_suite"
    )
    attributes = span.attributes or {}
    assert attributes.get("eval.outcome") == "failed"
    assert attributes.get("eval.case_count") == 0
    eval_keys = {key for key in attributes if key.startswith("eval.")}
    assert eval_keys <= set(SPAN_ATTRIBUTE_KEYS)


@pytest.mark.integration
@pytest.mark.req(["REQ-EVAL-011"])
async def test_run_suite_span_carries_no_per_case_keys(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No per-case attribute key is ever emitted on the span."""
    from mahavishnu.core.eval.engine import EvalEngine, EvalSuite, ModelConfig
    from mahavishnu.core.eval.scorers.exact_match import ExactMatchScorer

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(
        engine_module, "_tracer", provider.get_tracer("eval-cardinality-test")
    )

    storage = SqliteEvalStorage(tmp_path / "runs.sqlite")
    engine = EvalEngine(storage=storage, model_backend=MockModelBackend())
    suite = EvalSuite(
        name="golden",
        version="v0",
        dataset=_dataset(),
        scorers=[ExactMatchScorer()],
        model=ModelConfig(name="mahavishnu.mock"),
    )

    await engine.run_suite(suite)

    span = next(
        span for span in exporter.get_finished_spans() if span.name == "eval.run_suite"
    )
    keys = set(span.attributes or {})

    for forbidden in ("eval.case_id", "eval.prompt_hash", "eval.case", "eval.actual"):
        assert forbidden not in keys

    assert not any(key.startswith("eval.case.") for key in keys)


@pytest.mark.integration
@pytest.mark.req(["REQ-EVAL-011"])
def test_the_closed_keyspace_is_itself_fixed() -> None:
    """The allowed key set is exactly the eight documented keys."""
    expected = frozenset(
        {
            "eval.suite_name",
            "eval.model",
            "eval.case_count",
            "eval.cost_usd",
            "eval.duration_ms",
            "eval.outcome",
            "eval.total_input_tokens",
            "eval.total_output_tokens",
        }
    )
    assert set(SPAN_ATTRIBUTE_KEYS) == expected
