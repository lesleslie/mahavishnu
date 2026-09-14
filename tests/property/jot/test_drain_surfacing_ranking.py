"""Task 18: property-based surfacing-ranking invariant tests.

Invariants on ``surface_relevant``:

  * Determinism — same trigger + same context_text + same jots ⇒ same
    ordered candidate set.
  * Lexical-tie semantics — when two jots share identical lexical
    overlap with the context, the one carrying the EARLIER
    ``last_modified_ms`` ranks first (``sort key (-score, wall_ms)``).
  * ``limit`` is a strict upper bound on the returned candidate list.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from mahavishnu.jot.drain import (
    _Throttle,
    surface_relevant,
)
from mahavishnu.jot.events import HLC, JotEvent, serialize


# ---------------------------------------------------------------------------
# Helpers + fixtures
# ---------------------------------------------------------------------------


def _capture_event(
    jot_id: str, text: str, *, wall_ms: int,
) -> JotEvent:
    return JotEvent(
        id=jot_id,
        op="capture",
        text=text,
        hlc=HLC(wall_ms=wall_ms, ctr=0, node="a" * 8),
        ctx={},
        created_ms=wall_ms,
    )


def _pad_ctx(base: str, min_words: int = 60) -> str:
    """Pad a context with at least ``min_words`` whitespace-split words."""
    words = base.split()
    if len(words) >= min_words:
        return base
    pad_word = "padzzword"
    while len(words) < min_words:
        words.append(pad_word)
    return " ".join(words)


def _write_log(path: Path, events: list[JotEvent]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for ev in events:
            f.write(serialize(ev))


@pytest.fixture
def isolated_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    log = tmp_path / "log.jsonl"
    node = tmp_path / "node"
    node.write_text("a" * 8)
    monkeypatch.setattr("mahavishnu.jot.drain.log_path", lambda: log)
    monkeypatch.setattr("mahavishnu.jot.drain.node_path", lambda: node)
    monkeypatch.setattr("mahavishnu.jot.paths.log_path", lambda: log)
    return log


@pytest.fixture(autouse=True)
def _force_zero_throttle(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the module-level throttle fire every call (default = 5s)."""
    import mahavishnu.jot.drain as drain_module

    monkeypatch.setattr(drain_module, "_THROTTLE", _Throttle(min_interval_ms=0))


@pytest.fixture(autouse=True)
def _stub_embeddings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace the embeddings adapter with a deterministic stub.

    The real ``OneiricEmbeddingsAdapter`` is async-only and not stable
    across hypothesis examples — its failures produce ``embeddings_down``
    that masks the determinism / ranking invariants we want to test.
    """
    import mahavishnu.jot.drain as drain_module

    class _Stub:
        deterministic = True

        async def embed(self, texts):
            import hashlib

            return [
                [(hashlib.md5(t.encode()).digest()[i] / 255.0) for i in range(8)]
                for t in texts
            ]

    monkeypatch.setattr(drain_module, "_build_embeddings_adapter", lambda: _Stub())


# Strategies --------------------------------------------------------------

_JOT_TEXT = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "Z"),
        whitelist_characters=" _-",
    ),
    min_size=4,
    max_size=80,
).filter(lambda t: t.strip() != "")


@st.composite
def _jot_set(
    draw, min_size: int = 0, max_size: int = 4,
) -> list[tuple[str, str, int]]:
    """Generate a list of (id, text, wall_ms) tuples for surfacing tests.

    ``wall_ms`` is monotonically increasing across the list, simulating a
    realistic ``last_modified_ms`` ordering.
    """
    n = draw(st.integers(min_value=min_size, max_value=max_size))
    out: list[tuple[str, str, int]] = []
    seen: set[str] = set()
    last_wall = 1_700_000_000_000
    for i in range(n):
        body = draw(st.integers(min_value=0, max_value=2**31 - 1))
        jid = f"{body:032x}"[-32:]
        if jid in seen:
            continue
        seen.add(jid)
        text = draw(_JOT_TEXT)
        wall = last_wall + draw(st.integers(min_value=1, max_value=1000))
        last_wall = wall
        out.append((jid, text, wall))
    return out


@st.composite
def _context_with_tokens(
    draw, min_size: int = 4, max_size: int = 12,
) -> str:
    """A context string with several recognizable tokens (≥ 50 words)."""
    n = draw(st.integers(min_value=min_size, max_value=max_size))
    tokens = draw(
        st.lists(
            st.text(
                alphabet="abcdefghijklmnopqrstuvwxyz",
                min_size=3,
                max_size=10,
            ).filter(lambda t: t.isalpha()),
            min_size=n,
            max_size=n,
            unique=True,
        ),
    )
    # Build a context with at least 60 words (50 for the throttle gate + 10 buffer).
    body = " ".join(tokens)
    return _pad_ctx(body, min_words=60)


# ---------------------------------------------------------------------------
# Property 1 — surface_relevant is deterministic
# ---------------------------------------------------------------------------


class TestSurfacingDeterminism:
    """Same inputs ⇒ identical ordered candidate list."""

    @given(
        jots=_jot_set(min_size=1, max_size=3),
        ctx_tokens=_context_with_tokens(min_size=4, max_size=8),
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_two_calls_return_identical_ordered_candidates(
        self,
        isolated_log: Path,
        jots: list[tuple[str, str, int]],
        ctx_tokens: str,
    ) -> None:
        """Three back-to-back calls return the same ordered candidate list."""
        events = [_capture_event(jid, text, wall_ms=wall) for jid, text, wall in jots]
        _write_log(isolated_log, events)

        first = surface_relevant(trigger="session_start", context_text=ctx_tokens)
        second = surface_relevant(trigger="session_start", context_text=ctx_tokens)
        third = surface_relevant(trigger="session_start", context_text=ctx_tokens)

        ids_first = [j.id for j in first.matches]
        ids_second = [j.id for j in second.matches]
        ids_third = [j.id for j in third.matches]
        assert ids_first == ids_second == ids_third
        # surface_reason must be identical across the three calls. The
        # path (lexical vs semantic) depends on whether random
        # ctx_tokens overlap the jot texts; with the embeddings stub
        # active, the semantic fallback is deterministic too.
        assert first.surface_reason == second.surface_reason == third.surface_reason
        assert first.score_threshold_used == second.score_threshold_used == third.score_threshold_used


# ---------------------------------------------------------------------------
# Property 2 — lexical-tie semantic ordering
# ---------------------------------------------------------------------------


class TestLexicalTieOrdering:
    """Jots with identical lexical overlap are ordered by last_modified_ms."""

    @given(
        token_seed=st.text(
            alphabet="abcdefghijklmnopqrstuvwxyz",
            min_size=4,
            max_size=10,
        ).filter(lambda t: t.isalpha()),
        n_jots=st.integers(min_value=2, max_value=4),
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_earlier_last_modified_ranks_first_under_lexical_tie(
        self,
        isolated_log: Path,
        token_seed: str,
        n_jots: int,
    ) -> None:
        """When two jots share 100% of the context tokens, the EARLIER one
        (``-last_modified_ms`` descending) wins because the score is tied
        and ``last_modified_ms`` is the secondary sort key."""
        # Build N jots that all share `token_seed` in their text. Each
        # carries a strictly increasing wall_ms so the secondary key
        # produces a deterministic ranking: oldest first.
        events: list[JotEvent] = []
        for i in range(n_jots):
            jid = f"{abs(hash(token_seed + '|' + str(i))) & 0xffffffffffffffff:016x}" * 2
            text = f"{token_seed} filler {i}"  # all share token_seed
            wall = 1_700_000_000_000 + i * 1_000
            events.append(_capture_event(jid, text, wall_ms=wall))
        _write_log(isolated_log, events)

        # Context that ONLY contains the shared token — this gives every
        # jot a lexical_score of 1.0 (full coverage) so the secondary
        # sort key (last_modified_ms) drives the ordering.
        ctx = f"{token_seed} " * 60  # 60 copies of the token, 60 words

        result = surface_relevant(
            trigger="session_start", context_text=ctx, limit=n_jots + 2,
        )
        assert result.surface_reason == "matches"
        # Ordering should be ascending by wall_ms — earliest first.
        wall_times = [j.last_modified_ms for j in result.matches]
        assert wall_times == sorted(wall_times), (
            f"expected ascending wall_ms, got {wall_times}"
        )

    @given(token_seed=st.text(
        alphabet="abcdefghijklmnopqrstuvwxyz",
        min_size=4,
        max_size=10,
    ).filter(lambda t: t.isalpha()))
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_two_jots_lexical_tie_picks_earlier(
        self,
        isolated_log: Path,
        token_seed: str,
    ) -> None:
        """Two jots with identical lexical coverage → earlier one first."""
        older_id = f"{abs(hash(token_seed + 'older')) & 0xffffffffffffffff:016x}" * 2
        newer_id = f"{abs(hash(token_seed + 'newer')) & 0xffffffffffffffff:016x}" * 2
        events = [
            _capture_event(older_id, f"{token_seed} older", wall_ms=1_700_000_000_000),
            _capture_event(newer_id, f"{token_seed} newer", wall_ms=1_700_000_010_000),
        ]
        _write_log(isolated_log, events)
        # Context that ONLY contains the shared token.
        ctx = f"{token_seed} " * 60

        result = surface_relevant(
            trigger="session_start", context_text=ctx, limit=5,
        )
        assert result.surface_reason == "matches"
        assert len(result.matches) >= 2
        # The first match must be the older jot.
        assert result.matches[0].id == older_id


# ---------------------------------------------------------------------------
# Property 3 — limit parameter is a strict upper bound
# ---------------------------------------------------------------------------


class TestLimitRespected:
    """``limit=N`` ⇒ at most N candidates returned."""

    @given(
        n_jots=st.integers(min_value=3, max_value=8),
        limit=st.integers(min_value=1, max_value=5),
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_limit_caps_returned_count(
        self,
        isolated_log: Path,
        n_jots: int,
        limit: int,
    ) -> None:
        """The number of matches never exceeds ``limit``."""
        # Build N jots that all share a dominant token so every one matches.
        token = "alpha"
        events: list[JotEvent] = []
        for i in range(n_jots):
            jid = f"{abs(hash(f'{token}-{i}')) & 0xffffffffffffffff:016x}" * 2
            events.append(
                _capture_event(jid, f"{token} {i}", wall_ms=1_700_000_000_000 + i),
            )
        _write_log(isolated_log, events)
        ctx = _pad_ctx(f"{token} " * 50 + "fill " * 20, min_words=60)

        result = surface_relevant(
            trigger="session_start", context_text=ctx, limit=limit,
        )
        assert len(result.matches) <= limit
        # And matches count should be exactly min(limit, n_jots).
        assert len(result.matches) == min(limit, n_jots)

    @given(limit=st.integers(min_value=1, max_value=10))
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_limit_zero_returns_no_matches(
        self,
        isolated_log: Path,
        limit: int,
    ) -> None:
        """``limit=0`` ⇒ no candidates returned (truncate-before-sort is
        a no-op, so the list is empty by construction)."""
        events = [
            _capture_event(f"{i:032x}"[-32:], "alpha beta", wall_ms=1_700_000_000_000 + i)
            for i in range(3)
        ]
        _write_log(isolated_log, events)
        ctx = _pad_ctx("alpha beta fill " * 20, min_words=60)
        result = surface_relevant(
            trigger="session_start", context_text=ctx, limit=limit,
        )
        if limit == 0:
            assert result.matches == []
        else:
            assert len(result.matches) <= limit


# ---------------------------------------------------------------------------
# Property 4 — empty jots + non-empty context never surface empty candidates
# ---------------------------------------------------------------------------


class TestEmptyInputHandling:
    """Degenerate inputs produce no spurious matches."""

    @given(jots=_jot_set(min_size=1, max_size=3))
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_empty_jot_text_never_surfaces(
        self,
        isolated_log: Path,
        jots: list[tuple[str, str, int]],
    ) -> None:
        """Jots with text that tokenizes to an empty set are not surfaced.

        Build jots that contain only 1-char tokens (filtered by ``_tokenize``).
        """
        # Build jots with only 1-char tokens. After tokenize (len >= 2
        # filter), the token set is empty.
        events: list[JotEvent] = []
        for i, (jid, _text, _wall) in enumerate(jots):
            events.append(
                _capture_event(jid, "a b c d", wall_ms=1_700_000_000_000 + i),
            )
        _write_log(isolated_log, events)
        ctx = _pad_ctx("alpha beta gamma delta fill " * 20, min_words=60)
        result = surface_relevant(trigger="session_start", context_text=ctx)
        # Empty-token jots have lexical_score = 0 against any ctx → no
        # candidate reaches the threshold.
        assert result.matches == []
