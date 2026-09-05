"""Extended coverage tests for ``mahavishnu.tui.command_palette``.

Targets the ~30% gap in ``command_palette.py`` to push coverage to ~100%.

What is covered here:

* ``FuzzyMatcher.normalize`` — case-insensitive strip.
* ``FuzzyMatcher.score`` — exact, prefix, contains, word-start, fuzzy, no-match.
* ``FuzzyMatcher._fuzzy_score`` — bonus paths, missing-char penalty, 0.6 cap.
* ``Command.__hash__`` / ``__eq__`` — same-id equality, non-Command inequality.
* ``CommandPalette.register`` / ``unregister`` / ``get`` / ``list_all`` / ``list_by_category``.
* ``CommandPalette.search`` — every match_type branch, empty/whitespace, score sort,
  min_score filter, disabled command exclusion.
* ``CommandPalette.execute`` (async) — sync action, async action, missing command,
  missing action, history append, history 100-item cap.
* ``CommandPalette.get_history`` / ``clear_history``.
* ``create_default_palette`` — command count and named ids.
* ``MahavishnuCommandProvider.search`` (async) — yielded Hits and ``_run`` callback.
* ``get_command_palette`` singleton — same instance on repeat, fresh after reset.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from mahavishnu.tui import command_palette as cp_module
from mahavishnu.tui.command_palette import (
    Command,
    CommandCategory,
    CommandMatch,
    CommandPalette,
    FuzzyMatcher,
    MahavishnuCommandProvider,
    create_default_palette,
    get_command_palette,
)


# ============================================================
# Helpers
# ============================================================


def _cmd(
    cid: str,
    *,
    name: str = "Sample",
    category: CommandCategory = CommandCategory.SYSTEM,
    description: str = "",
    shortcut: str = "",
    keywords: list[str] | None = None,
    action: Any = None,
    enabled: bool = True,
    priority: int = 0,
) -> Command:
    return Command(
        id=cid,
        name=name,
        category=category,
        description=description,
        shortcut=shortcut,
        keywords=list(keywords or []),
        action=action,
        enabled=enabled,
        priority=priority,
    )


def _collect_hits(provider: MahavishnuCommandProvider, query: str) -> list[Any]:
    """Drain the async generator from ``MahavishnuCommandProvider.search``."""

    async def drain() -> list[Any]:
        hits: list[Any] = []
        async for hit in provider.search(query):
            hits.append(hit)
        return hits

    return asyncio.run(drain())


# ============================================================
# FuzzyMatcher.normalize
# ============================================================


@pytest.mark.unit
def test_fuzzy_matcher_normalize_lowercases_and_strips() -> None:
    assert FuzzyMatcher.normalize("  Hello WORLD  ") == "hello world"


@pytest.mark.unit
def test_fuzzy_matcher_normalize_handles_empty_string() -> None:
    assert FuzzyMatcher.normalize("") == ""
    assert FuzzyMatcher.normalize("   ") == ""


# ============================================================
# FuzzyMatcher.score
# ============================================================


@pytest.mark.unit
def test_fuzzy_matcher_score_exact_match_returns_one() -> None:
    assert FuzzyMatcher.score("create", "create") == 1.0


@pytest.mark.unit
def test_fuzzy_matcher_score_exact_match_is_case_insensitive() -> None:
    assert FuzzyMatcher.score("CREATE", "create") == 1.0
    assert FuzzyMatcher.score("Create", "CREATE") == 1.0


@pytest.mark.unit
def test_fuzzy_matcher_score_prefix_match_returns_zero_point_nine() -> None:
    assert FuzzyMatcher.score("cre", "create") == 0.9


@pytest.mark.unit
def test_fuzzy_matcher_score_contains_match_returns_zero_point_eight() -> None:
    # "ate" is not a prefix of "create", but it appears in it.
    assert FuzzyMatcher.score("ate", "create") == 0.8


@pytest.mark.unit
def test_fuzzy_matcher_score_contains_beats_word_start() -> None:
    # The word-start branch (0.7) is unreachable in practice: whenever a word
    # starts with the query, the query is also a substring of the target, so
    # the 'contains' tier (0.8) wins first. Lock in that precedence here.
    target = "create task"
    assert FuzzyMatcher.score("t", target) == 0.8  # 't' is contained
    assert FuzzyMatcher.score("tas", target) == 0.8  # 'tas' is contained
    assert FuzzyMatcher.score("task", target) == 0.8  # 'task' is contained


@pytest.mark.unit
def test_fuzzy_matcher_score_empty_query_returns_zero() -> None:
    assert FuzzyMatcher.score("", "anything") == 0.0
    assert FuzzyMatcher.score("   ", "anything") == 0.0


@pytest.mark.unit
def test_fuzzy_matcher_score_empty_target_returns_zero() -> None:
    assert FuzzyMatcher.score("query", "") == 0.0
    assert FuzzyMatcher.score("query", "   ") == 0.0


@pytest.mark.unit
def test_fuzzy_matcher_score_fuzzy_match_capped_at_zero_point_six() -> None:
    # "ct" — neither an exact/prefix/contains/word-start match for "create";
    # fuzzy branch should fire and the score must be <= 0.6.
    score = FuzzyMatcher.score("ct", "create")
    assert 0.0 < score <= 0.6


@pytest.mark.unit
def test_fuzzy_matcher_score_non_matching_query_returns_zero() -> None:
    # "xyz" — no characters from the query appear in "create" in order.
    assert FuzzyMatcher.score("xyz", "create") == 0.0


@pytest.mark.unit
def test_fuzzy_matcher_score_priority_of_match_types() -> None:
    # Exact > prefix > contains — exercise them all on a single target so we
    # lock in the scoring precedence. (Word-start 0.7 is unreachable: any
    # word-start query is also a substring of the target.)
    target = "create task"
    assert FuzzyMatcher.score("create task", target) == 1.0  # exact
    assert FuzzyMatcher.score("create", target) == 0.9  # prefix
    assert FuzzyMatcher.score("ate", target) == 0.8  # contains


# ============================================================
# FuzzyMatcher._fuzzy_score
# ============================================================


@pytest.mark.unit
def test_fuzzy_score_all_chars_in_order_returns_positive() -> None:
    score = FuzzyMatcher._fuzzy_score("ct", "create")
    assert score > 0.0


@pytest.mark.unit
def test_fuzzy_score_missing_chars_returns_zero() -> None:
    # "z" never appears in "create".
    assert FuzzyMatcher._fuzzy_score("z", "create") == 0.0


@pytest.mark.unit
def test_fuzzy_score_is_capped_at_zero_point_six() -> None:
    # Even with consecutive + word-start bonuses, the fuzzy score must clamp
    # at 0.6 so callers can distinguish it from the exact/prefix/contains tier.
    assert FuzzyMatcher._fuzzy_score("c", "create") <= 0.6
    # Confirming the cap explicitly when every char matches at word start.
    assert FuzzyMatcher._fuzzy_score("c t", "create task") <= 0.6


@pytest.mark.unit
def test_fuzzy_score_normalization_handles_underscores_and_dashes_as_word_separators() -> None:
    # "ct" against "create-task" — both 'c' and 't' land on word starts, so we
    # expect bonuses; result must still be <= 0.6 and > 0.
    score = FuzzyMatcher._fuzzy_score("ct", "create-task")
    assert 0.0 < score <= 0.6
    score_under = FuzzyMatcher._fuzzy_score("ct", "create_task")
    assert 0.0 < score_under <= 0.6


# ============================================================
# Command.__hash__ and __eq__
# ============================================================


@pytest.mark.unit
def test_command_equal_when_ids_match() -> None:
    a = _cmd("task.create", name="A")
    b = _cmd("task.create", name="B")
    assert a == b


@pytest.mark.unit
def test_command_not_equal_when_ids_differ() -> None:
    a = _cmd("task.create")
    b = _cmd("task.list")
    assert a != b


@pytest.mark.unit
def test_command_hash_is_consistent_with_equality() -> None:
    a = _cmd("task.create", name="Foo")
    b = _cmd("task.create", name="Bar")
    assert hash(a) == hash(b)
    # Hash must be derived from the id (not the name).
    assert hash(a) == hash("task.create")


@pytest.mark.unit
def test_command_not_equal_to_non_command_object() -> None:
    cmd = _cmd("task.create")
    assert (cmd == "task.create") is False
    assert (cmd == 42) is False
    assert (cmd == None) is False  # noqa: E711


@pytest.mark.unit
def test_command_usable_in_set_and_dict() -> None:
    a = _cmd("a")
    b = _cmd("b")
    s = {a, b, _cmd("a")}
    assert len(s) == 2
    lookup = {_cmd("a"): 1, _cmd("b"): 2}
    assert lookup[_cmd("a")] == 1


# ============================================================
# CommandPalette register / unregister / get / list_all / list_by_category
# ============================================================


@pytest.mark.unit
def test_palette_register_adds_command() -> None:
    palette = CommandPalette()
    cmd = _cmd("task.create")
    palette.register(cmd)
    assert palette.get("task.create") is cmd


@pytest.mark.unit
def test_palette_unregister_returns_true_when_present() -> None:
    palette = CommandPalette()
    palette.register(_cmd("task.create"))
    assert palette.unregister("task.create") is True
    assert palette.get("task.create") is None


@pytest.mark.unit
def test_palette_unregister_returns_false_when_absent() -> None:
    palette = CommandPalette()
    assert palette.unregister("does.not.exist") is False


@pytest.mark.unit
def test_palette_get_returns_none_for_missing_id() -> None:
    palette = CommandPalette()
    assert palette.get("missing") is None


@pytest.mark.unit
def test_palette_list_all_returns_every_registered_command() -> None:
    palette = CommandPalette()
    cmds = [_cmd(f"c{i}") for i in range(5)]
    for c in cmds:
        palette.register(c)
    listed = palette.list_all()
    assert sorted(c.id for c in listed) == [f"c{i}" for i in range(5)]


@pytest.mark.unit
def test_palette_list_by_category_filters_correctly() -> None:
    palette = CommandPalette()
    palette.register(_cmd("t1", category=CommandCategory.TASK))
    palette.register(_cmd("t2", category=CommandCategory.TASK))
    palette.register(_cmd("s1", category=CommandCategory.SYSTEM))
    palette.register(_cmd("h1", category=CommandCategory.HELP))
    task_cmds = palette.list_by_category(CommandCategory.TASK)
    assert sorted(c.id for c in task_cmds) == ["t1", "t2"]
    assert palette.list_by_category(CommandCategory.SEARCH) == []
    assert palette.list_by_category(CommandCategory.NAVIGATION) == []
    assert palette.list_by_category(CommandCategory.REPOSITORY) == []


# ============================================================
# CommandPalette.search
# ============================================================


@pytest.mark.unit
def test_palette_search_empty_query_returns_all_enabled_with_score_half() -> None:
    palette = CommandPalette()
    palette.register(_cmd("alpha", name="Alpha", priority=1))
    palette.register(_cmd("bravo", name="Bravo", priority=5))
    palette.register(_cmd("charlie", name="Charlie", enabled=False, priority=10))

    matches = palette.search("")
    assert len(matches) == 2  # disabled excluded
    assert all(m.score == 0.5 for m in matches)
    assert all(m.match_type == "none" for m in matches)
    # Sorted by (-priority, name): bravo(5), alpha(1).
    assert [m.command.id for m in matches] == ["bravo", "alpha"]


@pytest.mark.unit
def test_palette_search_whitespace_query_returns_all_enabled() -> None:
    palette = CommandPalette()
    palette.register(_cmd("alpha", name="Alpha"))
    palette.register(_cmd("bravo", name="Bravo", enabled=False))
    matches = palette.search("   ")
    assert [m.command.id for m in matches] == ["alpha"]


@pytest.mark.unit
def test_palette_search_excludes_disabled_commands() -> None:
    palette = CommandPalette()
    palette.register(_cmd("a", name="Alpha"))
    palette.register(_cmd("b", name="Beta", enabled=False))
    matches = palette.search("a")
    assert [m.command.id for m in matches] == ["a"]


@pytest.mark.unit
def test_palette_search_exact_name_match_uses_match_type_exact() -> None:
    palette = CommandPalette()
    palette.register(_cmd("a", name="Create Task"))
    matches = palette.search("Create Task")
    assert len(matches) == 1
    assert matches[0].match_type == "exact"
    assert matches[0].score == 1.0
    assert matches[0].matched_text == "Create Task"


@pytest.mark.unit
def test_palette_search_fuzzy_name_match_uses_match_type_fuzzy() -> None:
    palette = CommandPalette()
    palette.register(_cmd("a", name="Create"))
    matches = palette.search("ct")
    assert len(matches) == 1
    assert matches[0].match_type == "fuzzy"
    assert matches[0].matched_text == "Create"


@pytest.mark.unit
def test_palette_search_shortcut_match_uses_match_type_shortcut() -> None:
    palette = CommandPalette()
    palette.register(
        _cmd("a", name="Some Long Name", shortcut="tc"),
    )
    matches = palette.search("tc")
    assert len(matches) == 1
    assert matches[0].match_type == "shortcut"
    assert matches[0].matched_text == "tc"


@pytest.mark.unit
def test_palette_search_keyword_match_uses_match_type_keyword() -> None:
    palette = CommandPalette()
    palette.register(
        _cmd(
            "a",
            name="Random Name",
            description="nothing helpful",
            keywords=["alpha", "beta"],
        ),
    )
    matches = palette.search("alpha")
    assert len(matches) == 1
    assert matches[0].match_type == "keyword"
    assert matches[0].matched_text == "alpha"


@pytest.mark.unit
def test_palette_search_description_match_uses_match_type_description_with_multiplier() -> None:
    palette = CommandPalette()
    palette.register(
        _cmd("a", name="ZZZ", description="create task something"),
    )
    # Description exact match is 1.0 * 0.8 = 0.8 — strictly less than the
    # name-tier 0.9/1.0, but still well above default min_score 0.3.
    matches = palette.search("create task something")
    assert len(matches) == 1
    assert matches[0].match_type == "description"
    assert matches[0].score == pytest.approx(0.8)


@pytest.mark.unit
def test_palette_search_id_match_uses_match_type_id_with_multiplier() -> None:
    palette = CommandPalette()
    palette.register(_cmd("task.create", name="ZZZ"))
    matches = palette.search("task.create")
    assert len(matches) == 1
    assert matches[0].match_type == "id"
    assert matches[0].score == pytest.approx(0.7)


@pytest.mark.unit
def test_palette_search_picks_highest_score_across_fields() -> None:
    # "create" matches name (1.0) AND shortcut (1.0) AND id (1.0 * 0.7) AND
    # description (1.0 * 0.8). The name-tier wins, so match_type == "exact".
    palette = CommandPalette()
    palette.register(
        _cmd(
            "create",
            name="create",
            shortcut="create",
            description="create",
            keywords=["create"],
        ),
    )
    matches = palette.search("create")
    assert matches[0].match_type == "exact"
    assert matches[0].score == 1.0


@pytest.mark.unit
def test_palette_search_sorts_results_by_score_then_priority_then_name() -> None:
    palette = CommandPalette()
    # All three match "create" exactly (score 1.0); only the priority tier
    # breaks the tie. The 'low' command has the lowest priority, so it must
    # come after 'mid' and 'high'.
    palette.register(_cmd("low", name="Create", priority=0))
    palette.register(_cmd("mid", name="Create", priority=5))
    palette.register(_cmd("high", name="Create", priority=10))
    matches = palette.search("create")
    ids = [m.command.id for m in matches]
    assert ids.index("high") < ids.index("mid")
    assert ids.index("mid") < ids.index("low")


@pytest.mark.unit
def test_palette_search_sort_prefers_higher_score_over_priority() -> None:
    palette = CommandPalette()
    # 'high_prio' has higher priority but a lower score than 'high_score';
    # score trumps priority in the sort key.
    palette.register(_cmd("high_prio", name="Create Extra", priority=100))
    palette.register(_cmd("high_score", name="create", priority=0))
    matches = palette.search("create")
    ids = [m.command.id for m in matches]
    # high_score gets exact 1.0; high_prio gets 0.9 prefix — score wins.
    assert ids.index("high_score") < ids.index("high_prio")


@pytest.mark.unit
def test_palette_search_min_score_filter_drops_low_matches() -> None:
    palette = CommandPalette(min_score=0.7)
    palette.register(_cmd("a", name="Create Task"))
    # 'x' vs 'Create Task' is fuzzy ~0.x, well below 0.7 — should be filtered.
    matches = palette.search("x")
    assert matches == []


@pytest.mark.unit
def test_palette_search_min_score_admits_exact_matches() -> None:
    palette = CommandPalette(min_score=0.9)
    palette.register(_cmd("a", name="Create"))
    matches = palette.search("create")
    assert [m.command.id for m in matches] == ["a"]


@pytest.mark.unit
def test_palette_search_shortcut_branch_skipped_when_command_has_no_shortcut() -> None:
    # No shortcut — verify the `if cmd.shortcut` guard doesn't crash and that
    # the search still finds the name match.
    palette = CommandPalette()
    palette.register(_cmd("a", name="Create", shortcut=""))
    matches = palette.search("create")
    assert matches[0].match_type == "exact"


@pytest.mark.unit
def test_palette_search_description_branch_skipped_when_empty() -> None:
    palette = CommandPalette()
    palette.register(_cmd("a", name="Create", description=""))
    matches = palette.search("create")
    assert matches[0].match_type == "exact"


# ============================================================
# CommandPalette.execute
# ============================================================


@pytest.mark.unit
def test_palette_execute_sync_action_returns_value() -> None:
    palette = CommandPalette()

    def action() -> str:
        return "sync-result"

    palette.register(_cmd("a", action=action))
    assert asyncio.run(palette.execute("a")) == "sync-result"


@pytest.mark.unit
def test_palette_execute_async_action_awaits_coroutine() -> None:
    palette = CommandPalette()

    async def action() -> str:
        return "async-result"

    palette.register(_cmd("a", action=action))
    assert asyncio.run(palette.execute("a")) == "async-result"


@pytest.mark.unit
def test_palette_execute_missing_command_raises_value_error() -> None:
    palette = CommandPalette()
    with pytest.raises(ValueError, match="not found"):
        asyncio.run(palette.execute("missing"))


@pytest.mark.unit
def test_palette_execute_no_action_raises_value_error() -> None:
    palette = CommandPalette()
    palette.register(_cmd("a", action=None))
    with pytest.raises(ValueError, match="no action"):
        asyncio.run(palette.execute("a"))


@pytest.mark.unit
def test_palette_execute_appends_to_history() -> None:
    palette = CommandPalette()
    palette.register(_cmd("a", action=lambda: None))
    palette.register(_cmd("b", action=lambda: None))
    asyncio.run(palette.execute("a"))
    asyncio.run(palette.execute("b"))
    asyncio.run(palette.execute("a"))
    history = palette.get_history(limit=100)
    assert history == ["a", "b", "a"]


@pytest.mark.unit
def test_palette_execute_history_caps_at_one_hundred() -> None:
    palette = CommandPalette()
    cmds = [_cmd(f"c{i}", action=lambda: None) for i in range(101)]
    for c in cmds:
        palette.register(c)
    for i in range(101):
        asyncio.run(palette.execute(f"c{i}"))
    # Internal _history should be capped at 100.
    assert len(palette._history) == 100
    # Newest 10 reversed — last 10 ids (c91..c100) reversed.
    history = palette.get_history(limit=10)
    assert history == [f"c{i}" for i in range(100, 90, -1)]


# ============================================================
# CommandPalette.get_history / clear_history
# ============================================================


@pytest.mark.unit
def test_palette_get_history_empty_returns_empty_list() -> None:
    palette = CommandPalette()
    assert palette.get_history() == []
    assert palette.get_history(limit=5) == []


@pytest.mark.unit
def test_palette_get_history_returns_reversed_slice() -> None:
    palette = CommandPalette()
    palette.register(_cmd("a", action=lambda: None))
    palette.register(_cmd("b", action=lambda: None))
    palette.register(_cmd("c", action=lambda: None))
    for cid in ("a", "b", "c"):
        asyncio.run(palette.execute(cid))
    assert palette.get_history() == ["c", "b", "a"]
    assert palette.get_history(limit=2) == ["c", "b"]
    # Larger limit than history size just returns the full reversed slice.
    assert palette.get_history(limit=50) == ["c", "b", "a"]


@pytest.mark.unit
def test_palette_clear_history_empties_history() -> None:
    palette = CommandPalette()
    palette.register(_cmd("a", action=lambda: None))
    asyncio.run(palette.execute("a"))
    assert palette.get_history() == ["a"]
    palette.clear_history()
    assert palette.get_history() == []


# ============================================================
# create_default_palette
# ============================================================


@pytest.mark.unit
def test_create_default_palette_registers_thirteen_commands() -> None:
    # 5 task + 2 repo + 2 search + 2 system + 2 help = 13.
    palette = create_default_palette()
    assert len(palette.list_all()) == 13


@pytest.mark.unit
def test_create_default_palette_includes_expected_ids() -> None:
    palette = create_default_palette()
    expected_ids = {
        "task.create",
        "task.list",
        "task.update",
        "task.delete",
        "task.status",
        "repo.list",
        "repo.sweep",
        "search.tasks",
        "search.similar",
        "system.health",
        "system.config",
        "help.commands",
        "help.shortcuts",
    }
    actual_ids = {cmd.id for cmd in palette.list_all()}
    assert expected_ids == actual_ids


@pytest.mark.unit
def test_create_default_palette_categories_are_populated() -> None:
    palette = create_default_palette()
    assert palette.list_by_category(CommandCategory.TASK)
    assert palette.list_by_category(CommandCategory.REPOSITORY)
    assert palette.list_by_category(CommandCategory.SEARCH)
    assert palette.list_by_category(CommandCategory.SYSTEM)
    assert palette.list_by_category(CommandCategory.HELP)
    assert palette.list_by_category(CommandCategory.NAVIGATION) == []


# ============================================================
# MahavishnuCommandProvider.search (async)
# ============================================================


@pytest.mark.unit
def test_command_provider_yields_hit_per_match_for_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The provider uses the global singleton — reset it and seed with a
    # controlled palette so we can make exact assertions.
    monkeypatch.setattr(cp_module, "_default_palette", None)
    palette = get_command_palette()
    # Wipe the defaults so the default descriptions don't pollute the search.
    for cmd in list(palette.list_all()):
        palette.unregister(cmd.id)
    palette.register(
        _cmd(
            "task.create",
            name="Create Task",
            description="Create a new task",
            action=lambda: None,
        ),
    )
    palette.register(
        _cmd(
            "task.list",
            name="List Tasks",
            description="List all tasks",
            action=lambda: None,
        ),
    )

    provider = MahavishnuCommandProvider(None)  # screen arg unused
    hits = _collect_hits(provider, "create")
    assert len(hits) == 1
    hit = hits[0]
    assert hit.text == "Create Task"
    assert hit.help == "Create a new task"
    assert "[bold]Create Task[/]" in hit.match_display
    assert "[dim]Create a new task[/]" in hit.match_display
    # "create" prefixes "Create Task" → score 0.9.
    assert hit.score == pytest.approx(0.9)


@pytest.mark.unit
def test_command_provider_empty_query_yields_all_enabled_commands(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cp_module, "_default_palette", None)
    palette = get_command_palette()
    # Wipe the defaults so we have a deterministic enabled/disabled mix.
    for cmd in list(palette.list_all()):
        palette.unregister(cmd.id)
    palette.register(_cmd("a", name="Alpha", action=lambda: None))
    palette.register(_cmd("b", name="Bravo", enabled=False, action=lambda: None))
    palette.register(_cmd("c", name="Charlie", action=lambda: None))

    provider = MahavishnuCommandProvider(None)
    hits = _collect_hits(provider, "")
    names = sorted(h.text for h in hits)
    assert names == ["Alpha", "Charlie"]


@pytest.mark.unit
def test_command_provider_help_is_none_when_description_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cp_module, "_default_palette", None)
    palette = get_command_palette()
    for cmd in list(palette.list_all()):
        palette.unregister(cmd.id)
    palette.register(_cmd("a", name="Alpha", description="", action=lambda: None))

    provider = MahavishnuCommandProvider(None)
    hits = _collect_hits(provider, "alpha")
    assert hits[0].help is None


@pytest.mark.unit
def test_command_provider_run_callback_executes_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Hit's ``command`` callback should invoke ``palette.execute``."""
    monkeypatch.setattr(cp_module, "_default_palette", None)
    palette = get_command_palette()
    for cmd in list(palette.list_all()):
        palette.unregister(cmd.id)

    sentinel = {"called": False, "id": None}

    def action() -> None:
        sentinel["called"] = True
        sentinel["id"] = "executed.id"

    palette.register(_cmd("executed.id", name="Executed", action=action))

    provider = MahavishnuCommandProvider(None)
    hits = _collect_hits(provider, "executed")
    assert len(hits) == 1
    # ``command`` is an async closure returned by the provider.
    asyncio.run(hits[0].command())
    assert sentinel == {"called": True, "id": "executed.id"}


# ============================================================
# get_command_palette singleton
# ============================================================


@pytest.mark.unit
def test_get_command_palette_returns_same_instance(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cp_module, "_default_palette", None)
    first = get_command_palette()
    second = get_command_palette()
    assert first is second


@pytest.mark.unit
def test_get_command_palette_creates_default_palette_on_first_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cp_module, "_default_palette", None)
    palette = get_command_palette()
    assert isinstance(palette, CommandPalette)
    assert len(palette.list_all()) == 13


@pytest.mark.unit
def test_get_command_palette_resets_with_new_instance_after_reset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cp_module, "_default_palette", None)
    first = get_command_palette()
    first.register(_cmd("custom.command"))  # mutate to differentiate
    monkeypatch.setattr(cp_module, "_default_palette", None)
    second = get_command_palette()
    assert first is not second
    # Fresh instance — our custom command is gone.
    assert second.get("custom.command") is None
    assert len(second.list_all()) == 13


# ============================================================
# CommandMatch validation (smoke check that Pydantic rebuild works)
# ============================================================


@pytest.mark.unit
def test_command_match_rejects_out_of_range_score() -> None:
    palette = CommandPalette()
    palette.register(_cmd("a", action=lambda: None))
    cmd = palette.get("a")
    with pytest.raises(Exception):  # ValidationError from pydantic
        CommandMatch(command=cmd, score=1.5, match_type="exact", matched_text="x")
    with pytest.raises(Exception):
        CommandMatch(command=cmd, score=-0.1, match_type="exact", matched_text="x")


@pytest.mark.unit
def test_command_match_rejects_extra_fields() -> None:
    palette = CommandPalette()
    palette.register(_cmd("a", action=lambda: None))
    cmd = palette.get("a")
    with pytest.raises(Exception):  # extra="forbid"
        CommandMatch(
            command=cmd,
            score=0.5,
            match_type="exact",
            matched_text="x",
            unexpected_field="nope",
        )