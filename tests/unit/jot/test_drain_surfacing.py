"""Task 8: surfacing scorers + _Throttle + surface_relevant."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from mahavishnu.jot.drain import (
    SurfacingResult,
    _Throttle,
    _cosine_similarity,
    _lexical_score,
    _semantic_score,
    _tokenize,
    surface_relevant,
)
from mahavishnu.jot.events import JotEvent, serialize
from mahavishnu.jot.hlc import HLC


# =============================================================================
# _tokenize
# =============================================================================


def test_tokenize_lowercases_words() -> None:
    """Mixed case input → all lowercase tokens."""
    tokens = _tokenize("Hello WORLD Foo")
    assert "hello" in tokens
    assert "world" in tokens
    assert "foo" in tokens


def test_tokenize_filters_short_tokens() -> None:
    """Tokens len < 2 are dropped."""
    tokens = _tokenize("a I go be it xx")
    # 'a' and 'I' are length 1; 'be' is length 2, 'it' is length 2
    assert "a" not in tokens
    assert "i" not in tokens
    assert "go" in tokens
    assert "be" in tokens
    assert "it" in tokens
    assert "xx" in tokens


def test_tokenize_unicode_aware_via_w() -> None:
    """\\w+ regex matches Unicode word characters (letters/digits/underscore)."""
    tokens = _tokenize("café résumé")
    assert "café" in tokens
    assert "résumé" in tokens


def test_tokenize_returns_set() -> None:
    """Duplicate tokens collapse to one."""
    tokens = _tokenize("foo bar foo baz bar")
    assert tokens == {"foo", "bar", "baz"}


def test_tokenize_empty_input() -> None:
    """Empty string → empty set."""
    assert _tokenize("") == set()


# =============================================================================
# _lexical_score
# =============================================================================


def test_lexical_score_zero_on_empty_jot() -> None:
    """Empty jot tokens → 0.0."""
    assert _lexical_score(set(), {"foo", "bar"}) == 0.0


def test_lexical_score_zero_on_empty_ctx() -> None:
    """Empty ctx tokens → 0.0."""
    assert _lexical_score({"foo"}, set()) == 0.0


def test_lexical_score_zero_on_no_overlap() -> None:
    """Disjoint token sets → 0.0."""
    assert _lexical_score({"alpha"}, {"beta", "gamma"}) == 0.0


def test_lexical_score_full_overlap() -> None:
    """All ctx tokens covered → 1.0."""
    assert _lexical_score({"foo", "bar"}, {"foo", "bar"}) == 1.0


def test_lexical_score_proportional() -> None:
    """Partial overlap → coverage ratio."""
    # ctx: {foo, bar, baz}; jot: {foo, bar} → 2/3
    assert _lexical_score({"foo", "bar"}, {"foo", "bar", "baz"}) == pytest.approx(2 / 3)


def test_lexical_score_extra_jot_tokens_dont_help() -> None:
    """Tokens in jot not in ctx don't bump score."""
    # ctx: {foo}; jot: {foo, bar, baz} → 1/1
    assert _lexical_score({"foo", "bar", "baz"}, {"foo"}) == 1.0


# =============================================================================
# _cosine_similarity
# =============================================================================


def test_cosine_similarity_identical_vectors() -> None:
    """Identical non-zero vectors → 1.0."""
    assert _cosine_similarity([1.0, 0.0, 0.0], [1.0, 0.0, 0.0]) == pytest.approx(1.0)


def test_cosine_similarity_orthogonal() -> None:
    """Orthogonal vectors → 0.0."""
    assert _cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_cosine_similarity_opposite() -> None:
    """Opposite vectors → -1.0."""
    assert _cosine_similarity([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)


def test_cosine_similarity_empty_a() -> None:
    """Empty a → 0.0."""
    assert _cosine_similarity([], [1.0]) == 0.0


def test_cosine_similarity_empty_b() -> None:
    """Empty b → 0.0."""
    assert _cosine_similarity([1.0], []) == 0.0


def test_cosine_similarity_mismatched_lengths() -> None:
    """Mismatched lengths → 0.0."""
    assert _cosine_similarity([1.0, 0.0], [1.0]) == 0.0


def test_cosine_similarity_zero_vector() -> None:
    """All-zero vector → 0.0 (not divide-by-zero)."""
    assert _cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0


# =============================================================================
# _Throttle
# =============================================================================


def test_throttle_skips_short_context() -> None:
    """context_tokens < 50 → skip with reason 'short_context'."""
    t = _Throttle()
    fire, reason = t.should_fire(now_ms=100_000, context_tokens=49)
    assert fire is False
    assert reason == "short_context"


def test_throttle_fires_first_time() -> None:
    """First fire on long context → True, no skip reason."""
    t = _Throttle()
    fire, reason = t.should_fire(now_ms=100_000, context_tokens=100)
    assert fire is True
    assert reason is None


def test_throttle_throttles_within_window() -> None:
    """Two fires within min_interval_ms → second is throttled."""
    t = _Throttle(min_interval_ms=5000)
    fire1, _ = t.should_fire(now_ms=100_000, context_tokens=100)
    assert fire1 is True
    fire2, reason = t.should_fire(now_ms=100_000 + 4999, context_tokens=100)
    assert fire2 is False
    assert reason == "throttled"


def test_throttle_fires_after_window() -> None:
    """Second fire past min_interval_ms → True."""
    t = _Throttle(min_interval_ms=5000)
    t.should_fire(now_ms=100_000, context_tokens=100)
    fire, reason = t.should_fire(now_ms=100_000 + 5001, context_tokens=100)
    assert fire is True
    assert reason is None


def test_throttle_zero_interval_always_fires() -> None:
    """min_interval_ms=0 → always fires (test convenience)."""
    t = _Throttle(min_interval_ms=0)
    for i in range(5):
        fire, reason = t.should_fire(now_ms=100_000 + i, context_tokens=100)
        assert fire is True
        assert reason is None


# =============================================================================
# _semantic_score error paths
# =============================================================================


class _RaisingEmbeddings:
    """Embeddings stub that raises when called."""

    def embed(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError("boom")


class _EmptyEmbeddings:
    """Embeddings stub that returns an empty list."""

    def embed(self, texts: list[str]) -> list[list[float]]:
        return []


class _ShortEmbeddings:
    """Embeddings stub that returns a too-short result."""

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.1, 0.2, 0.3]]


class _MismatchedEmbeddings:
    """Embeddings stub that returns vectors of different lengths."""

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.1, 0.2, 0.3], [0.4, 0.5]]


class _TimeoutEmbeddings:
    """Embeddings stub that raises asyncio.TimeoutError."""

    def embed(self, texts: list[str]) -> list[list[float]]:
        raise asyncio.TimeoutError()


class _EmptyVectorEmbeddings:
    """Embeddings stub that returns an empty inner vector."""

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[], [0.1, 0.2]]


def test_semantic_score_returns_zero_on_raises() -> None:
    """embed() raises → 0.0, surface_degraded=True."""
    # Reset the module-level flag for this test.
    import mahavishnu.jot.drain as drain_module

    drain_module._last_surface_degraded = False
    score = _semantic_score("hello", "world", _RaisingEmbeddings())
    assert score == 0.0
    assert drain_module._last_surface_degraded is True


def test_semantic_score_returns_zero_on_empty() -> None:
    """embed() returns [] → 0.0, surface_degraded=True."""
    import mahavishnu.jot.drain as drain_module

    drain_module._last_surface_degraded = False
    score = _semantic_score("hello", "world", _EmptyEmbeddings())
    assert score == 0.0
    assert drain_module._last_surface_degraded is True


def test_semantic_score_returns_zero_on_short_result() -> None:
    """embed() returns 1 vector instead of 2 → 0.0, surface_degraded=True."""
    import mahavishnu.jot.drain as drain_module

    drain_module._last_surface_degraded = False
    score = _semantic_score("hello", "world", _ShortEmbeddings())
    assert score == 0.0
    assert drain_module._last_surface_degraded is True


def test_semantic_score_returns_zero_on_mismatched_shapes() -> None:
    """embed() returns vectors of differing lengths → 0.0, surface_degraded=True."""
    import mahavishnu.jot.drain as drain_module

    drain_module._last_surface_degraded = False
    score = _semantic_score("hello", "world", _MismatchedEmbeddings())
    assert score == 0.0
    assert drain_module._last_surface_degraded is True


def test_semantic_score_returns_zero_on_timeout() -> None:
    """embed() raises asyncio.TimeoutError → 0.0, surface_degraded=True."""
    import mahavishnu.jot.drain as drain_module

    drain_module._last_surface_degraded = False
    score = _semantic_score("hello", "world", _TimeoutEmbeddings())
    assert score == 0.0
    assert drain_module._last_surface_degraded is True


def test_semantic_score_returns_zero_on_empty_inner_vector() -> None:
    """embed() returns one empty vector → 0.0, surface_degraded=True."""
    import mahavishnu.jot.drain as drain_module

    drain_module._last_surface_degraded = False
    score = _semantic_score("hello", "world", _EmptyVectorEmbeddings())
    assert score == 0.0
    assert drain_module._last_surface_degraded is True


class _GoodEmbeddings:
    """Embeddings stub that returns parallel vectors with high cosine."""

    def embed(self, texts: list[str]) -> list[list[float]]:
        # Parallel vectors → cosine = 1.0
        return [[0.6, 0.8, 0.0], [0.6, 0.8, 0.0]]


class _OrthogonalEmbeddings:
    """Embeddings stub that returns orthogonal vectors."""

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]


def test_semantic_score_returns_cosine_on_good_result() -> None:
    """Parallel vectors → 1.0, no degraded flag."""
    import mahavishnu.jot.drain as drain_module

    drain_module._last_surface_degraded = False
    score = _semantic_score("hello", "world", _GoodEmbeddings())
    assert score == pytest.approx(1.0)
    assert drain_module._last_surface_degraded is False


def test_semantic_score_orthogonal_returns_zero() -> None:
    """Orthogonal vectors → 0.0, no degraded flag."""
    import mahavishnu.jot.drain as drain_module

    drain_module._last_surface_degraded = False
    score = _semantic_score("hello", "world", _OrthogonalEmbeddings())
    assert score == pytest.approx(0.0)
    assert drain_module._last_surface_degraded is False


# =============================================================================
# surface_relevant — lexical path
# =============================================================================


def _capture_event(jot_id: str, text: str, wall_ms: int = 1000) -> JotEvent:
    return JotEvent(
        id=jot_id.ljust(32, "0"),
        op="capture",
        hlc=HLC(wall_ms=wall_ms, ctr=0, node="a" * 8),
        text=text,
        ctx={},
        created_ms=wall_ms,
    )


def _done_event(jot_id: str, wall_ms: int = 2000) -> JotEvent:
    return JotEvent(
        id=jot_id.ljust(32, "0"),
        op="done",
        hlc=HLC(wall_ms=wall_ms, ctr=0, node="a" * 8),
        text="",
        ctx={},
        created_ms=wall_ms,
    )


def _delete_event(jot_id: str, wall_ms: int = 2000) -> JotEvent:
    return JotEvent(
        id=jot_id.ljust(32, "0"),
        op="delete",
        hlc=HLC(wall_ms=wall_ms, ctr=0, node="a" * 8),
        text="",
        ctx={"reason": None},
        created_ms=wall_ms,
    )


def _write_log(path: Path, events: list[JotEvent]) -> None:
    """Write a JSONL log from a list of events."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for ev in events:
            f.write(serialize(ev))


def _pad_ctx(base: str, min_words: int = 60) -> str:
    """Pad a context to at least ``min_words`` words.

    The throttle's short-context gate requires ≥ 50 raw words; tests need
    contexts longer than that regardless of their lexical composition.

    The pad is a single repeated word so it adds ONE unique token after
    tokenization. Multi-word fillers would inflate ctx_total and shrink
    the lexical coverage ratio, defeating the test's intent.
    """
    words = base.split()
    if len(words) >= min_words:
        return base
    pad_word = "padzzword"
    while len(words) < min_words:
        words.append(pad_word)
    return " ".join(words)


@pytest.fixture
def isolated_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point drain module at a tmp_path log + node file."""
    log = tmp_path / "log.jsonl"
    node = tmp_path / "node"
    node.write_text("a" * 8)
    monkeypatch.setattr("mahavishnu.jot.drain.log_path", lambda: log)
    monkeypatch.setattr("mahavishnu.jot.drain.node_path", lambda: node)
    return log


def test_surface_relevant_lexical_hit_above_threshold(
    isolated_log: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Token overlap ≥ threshold → lexical match wins, surface_reason='matches'."""
    # Build a jot whose text shares ≥ 50% of ctx tokens.
    _write_log(
        isolated_log,
        [
            _capture_event(
                "jot_a",
                "fix the python linter regression in api module",
                wall_ms=1000,
            ),
        ],
    )
    # ≥50 words; the jot's tokens cover ≥ 50% of the ctx's tokenized tokens.
    ctx = _pad_ctx(
        "the python linter regression in api module documentation really matters "
        "to us because the team depends on accurate api module output across all "
        "production deployments and continuous integration pipelines that we run"
    )

    # Patch the throttle to use 0 interval so we always fire.
    import mahavishnu.jot.drain as drain_module

    monkeypatch.setattr(drain_module, "_THROTTLE", _Throttle(min_interval_ms=0))

    result = surface_relevant(trigger="session_start", context_text=ctx)
    assert isinstance(result, SurfacingResult)
    assert result.surface_reason == "matches"
    assert result.surface_degraded is False
    assert len(result.matches) >= 1
    assert result.matches[0].text.startswith("fix the python linter regression")


def test_surface_relevant_no_context_returns_short_context(
    isolated_log: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty context text → short_context skip → empty matches."""
    _write_log(
        isolated_log,
        [_capture_event("jot_a", "fix the python linter", wall_ms=1000)],
    )
    import mahavishnu.jot.drain as drain_module

    monkeypatch.setattr(drain_module, "_THROTTLE", _Throttle(min_interval_ms=0))
    result = surface_relevant(trigger="session_start", context_text="")
    assert result.matches == []
    assert result.surface_reason == "short_context"


def test_surface_relevant_short_context_below_threshold(
    isolated_log: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """<50 words → short_context skip (throttle gate)."""
    _write_log(
        isolated_log,
        [_capture_event("jot_a", "fix the python linter", wall_ms=1000)],
    )
    import mahavishnu.jot.drain as drain_module

    monkeypatch.setattr(drain_module, "_THROTTLE", _Throttle(min_interval_ms=0))
    short_ctx = "fix the python linter in api"  # 6 words, well below 50
    result = surface_relevant(trigger="session_start", context_text=short_ctx)
    assert result.matches == []
    assert result.surface_reason == "short_context"


def test_surface_relevant_skips_done_jots(
    isolated_log: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Done jots are not eligible → no_match when only done jots exist."""
    _write_log(
        isolated_log,
        [
            _capture_event("jot_a", "fix the python linter", wall_ms=1000),
            _done_event("jot_a", wall_ms=2000),
        ],
    )
    import mahavishnu.jot.drain as drain_module

    monkeypatch.setattr(drain_module, "_THROTTLE", _Throttle(min_interval_ms=0))
    long_ctx = _pad_ctx(
        "fix the python linter in some context here to provide enough words "
        "for the throttle to fire on this fifty-word context with the team "
        "depending on accurate output across the deployment pipeline"
    )
    result = surface_relevant(
        trigger="session_start",
        context_text=long_ctx,
    )
    assert result.matches == []
    assert result.surface_reason == "no_match"


def test_surface_relevant_skips_deleted_jots(
    isolated_log: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Deleted jots are not eligible."""
    _write_log(
        isolated_log,
        [
            _capture_event("jot_a", "fix the python linter", wall_ms=1000),
            _delete_event("jot_a", wall_ms=2000),
        ],
    )
    import mahavishnu.jot.drain as drain_module

    monkeypatch.setattr(drain_module, "_THROTTLE", _Throttle(min_interval_ms=0))
    long_ctx = _pad_ctx(
        "fix the python linter in some context here to provide enough words "
        "for the throttle to fire on this fifty-word context with the team "
        "depending on accurate output across the deployment pipeline"
    )
    result = surface_relevant(
        trigger="session_start",
        context_text=long_ctx,
    )
    assert result.matches == []


def test_surface_relevant_falls_back_to_semantic_on_zero_lexical(
    isolated_log: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No lexical hits → semantic path runs; mock returns good scores."""
    # Jot and ctx share no tokens → lexical = 0.
    _write_log(
        isolated_log,
        [_capture_event("jot_a", "alpha beta gamma", wall_ms=1000)],
    )
    import mahavishnu.jot.drain as drain_module

    monkeypatch.setattr(drain_module, "_THROTTLE", _Throttle(min_interval_ms=0))

    # Patch the _semantic_score entry point so we can track it was called.
    called = {"n": 0}

    def fake_semantic(jot_text: str, ctx_text: str, embeddings: Any) -> float:
        called["n"] += 1
        # Return cosine of 1.0 for "alpha beta gamma" + context.
        return 0.9

    monkeypatch.setattr(drain_module, "_semantic_score", fake_semantic)

    long_ctx = _pad_ctx(
        "xyzzy plover quux corge waldo fred plugh xyzzy thud waldo plover quux "
        "corge waldo fred plugh thud waldo plover quux corge waldo fred plugh "
        "thud waldo plover quux corge waldo fred plugh thud waldo"
    )
    result = surface_relevant(
        trigger="session_start",
        context_text=long_ctx,
    )
    assert called["n"] >= 1, "semantic fallback should be invoked"
    assert result.surface_reason == "matches"
    assert result.surface_degraded is False
    assert len(result.matches) == 1


def test_surface_relevant_semantic_not_invoked_when_lexical_hits(
    isolated_log: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Lexical hit above threshold → semantic path is NOT called."""
    _write_log(
        isolated_log,
        [_capture_event(
            "jot_a",
            "python linter regression api module documentation matters depend",
            wall_ms=1000,
        )],
    )
    import mahavishnu.jot.drain as drain_module

    monkeypatch.setattr(drain_module, "_THROTTLE", _Throttle(min_interval_ms=0))

    called = {"n": 0}

    def fake_semantic(jot_text: str, ctx_text: str, embeddings: Any) -> float:
        called["n"] += 1
        return 0.9

    monkeypatch.setattr(drain_module, "_semantic_score", fake_semantic)

    # Long ctx with many repeated shared tokens → lexical = 1.0.
    ctx = _pad_ctx(
        "python linter regression api module documentation matters depend "
        "on accurate python linter regression api module documentation matters "
        "depend output across all production deployments and CI pipelines"
    )
    result = surface_relevant(trigger="session_start", context_text=ctx)
    assert called["n"] == 0, "semantic should NOT be invoked on lexical hit"
    assert result.surface_reason == "matches"


def test_surface_relevant_semantic_degraded_when_embeddings_raise(
    isolated_log: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Embeddings raise → surface_degraded=True, reason='embeddings_down'."""
    _write_log(
        isolated_log,
        [_capture_event("jot_a", "alpha beta gamma", wall_ms=1000)],
    )
    import mahavishnu.jot.drain as drain_module

    monkeypatch.setattr(drain_module, "_THROTTLE", _Throttle(min_interval_ms=0))

    # Wire _semantic_score to set the module-level flag (mirrors the real
    # error path). Returns 0.0.
    def fake_semantic(jot_text: str, ctx_text: str, embeddings: Any) -> float:
        drain_module._last_surface_degraded = True
        return 0.0

    monkeypatch.setattr(drain_module, "_semantic_score", fake_semantic)

    # Pre-set the global so we can verify it's reset and re-set.
    drain_module._last_surface_degraded = False

    long_ctx = _pad_ctx(
        "xyzzy plover quux corge waldo fred plugh thud waldo plover quux "
        "corge waldo fred plugh thud waldo plover quux corge waldo fred plugh "
        "thud waldo plover quux corge waldo fred plugh thud waldo"
    )
    result = surface_relevant(
        trigger="session_start",
        context_text=long_ctx,
    )
    assert result.surface_degraded is True
    # Reason is "embeddings_down" when degraded.
    assert result.surface_reason == "embeddings_down"
    assert result.matches == []


def test_surface_relevant_returns_top_n_by_lexical_score(
    isolated_log: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Top N jots sorted by lexical score."""
    _write_log(
        isolated_log,
        [
            _capture_event(
                "jot_top",
                "python linter regression api module documentation matters",
                wall_ms=1000,
            ),
            _capture_event(
                "jot_mid",
                "python linter bug documentation matters",
                wall_ms=1001,
            ),
            _capture_event(
                "jot_low",
                "alpha beta",
                wall_ms=1002,
            ),
        ],
    )
    import mahavishnu.jot.drain as drain_module

    monkeypatch.setattr(drain_module, "_THROTTLE", _Throttle(min_interval_ms=0))

    ctx = _pad_ctx(
        "python linter regression api module documentation matters depend "
        "on accurate output across all production deployments for python linter"
    )
    result = surface_relevant(
        trigger="session_start",
        context_text=ctx,
        limit=2,
    )
    assert result.surface_reason == "matches"
    ids = {j.id for j in result.matches}
    # limit=2 → top 2 should be jot_top + jot_mid.
    assert "jot_top".ljust(32, "0") in ids
    assert len(result.matches) == 2


def test_surface_relevant_throttled_when_called_repeatedly(
    isolated_log: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two rapid surface_relevant calls within min_interval → second is throttled."""
    _write_log(
        isolated_log,
        [_capture_event(
            "jot_a",
            "python linter regression api module documentation matters depend",
            wall_ms=1000,
        )],
    )
    # Default throttle: min_interval_ms=5000.
    # Patch _now_ms to return a fixed value.
    import mahavishnu.jot.drain as drain_module

    monkeypatch.setattr(drain_module, "_now_ms", lambda: 100_000)

    long_ctx = _pad_ctx(
        "python linter regression api module documentation matters depend "
        "on accurate output across all production deployments and CI pipelines "
        "for python linter regression api module documentation matters depend"
    )

    # First call — fires.
    r1 = surface_relevant(
        trigger="session_start",
        context_text=long_ctx,
    )
    assert r1.surface_reason == "matches"

    # Second call within 5s window — throttled.
    monkeypatch.setattr(drain_module, "_now_ms", lambda: 100_001)
    r2 = surface_relevant(
        trigger="session_start",
        context_text=long_ctx,
    )
    assert r2.surface_reason == "throttled"
    assert r2.matches == []


def test_surface_relevant_resets_degraded_flag_at_entry(
    isolated_log: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The module-level _last_surface_degraded is reset to False on entry."""
    _write_log(
        isolated_log,
        [_capture_event(
            "jot_a",
            "python linter regression api module documentation matters depend",
            wall_ms=1000,
        )],
    )
    import mahavishnu.jot.drain as drain_module

    monkeypatch.setattr(drain_module, "_THROTTLE", _Throttle(min_interval_ms=0))

    # Pretend a prior call set the degraded flag.
    drain_module._last_surface_degraded = True

    # Patch _semantic_score to do nothing — no flag flip.
    monkeypatch.setattr(
        drain_module, "_semantic_score",
        lambda j, c, e: 0.0,
    )

    long_ctx = _pad_ctx(
        "python linter regression api module documentation matters depend "
        "on accurate output across all production deployments and CI pipelines"
    )

    # Lexical path with a high-overlap context → no semantic call.
    result = surface_relevant(
        trigger="session_start",
        context_text=long_ctx,
    )
    # Flag was reset by entry; lexical hit → degraded=False.
    assert result.surface_degraded is False


def test_surface_relevant_no_eligible_jots_returns_no_match(
    isolated_log: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty log → no eligible jots → 'no_match'."""
    _write_log(isolated_log, [])
    import mahavishnu.jot.drain as drain_module

    monkeypatch.setattr(drain_module, "_THROTTLE", _Throttle(min_interval_ms=0))
    long_ctx = _pad_ctx(
        "any sufficiently long context here that exceeds fifty tokens easily "
        "for the throttle to allow the surface relevant function to fire "
        "and return some result with no_match status when nothing eligible"
    )
    result = surface_relevant(
        trigger="session_start",
        context_text=long_ctx,
    )
    assert result.matches == []
    assert result.surface_reason == "no_match"


def test_surface_relevant_score_threshold_field_present(
    isolated_log: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SurfacingResult.score_threshold_used is a float."""
    _write_log(isolated_log, [])
    import mahavishnu.jot.drain as drain_module

    monkeypatch.setattr(drain_module, "_THROTTLE", _Throttle(min_interval_ms=0))
    long_ctx = _pad_ctx(
        "any sufficiently long context here that exceeds fifty tokens easily "
        "for the throttle to allow the surface relevant function to fire "
        "and return some result with no_match status when nothing eligible"
    )
    result = surface_relevant(
        trigger="session_start",
        context_text=long_ctx,
    )
    assert isinstance(result.score_threshold_used, float)
    assert 0.0 <= result.score_threshold_used <= 1.0
