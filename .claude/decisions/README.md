# `.claude/decisions/` index

One-line summary: the directory holds repo-local decisions and
follow-up trackers. This file is the index — update it when adding
a new file.

## Files

Sorted newest-first. The first column is the file, the second is
the topic, the third is the most recent state.

| File | Topic | Status |
|------|-------|--------|
| `README.md` | This file — index of repo-local decisions and follow-up trackers. | Active. |
| `agent-curation-strategy.md` | Rules for adding/archiving agents: mycelium-core deduplication, Bodai-stack relevance, 15k token limit. | Active. |
| `skill-vs-agent-strategy.md` | When to write a skill vs. an agent: trigger-driven procedures → skill, domain persona → agent. | Active. |
| `technical-debt-roadmap.md` | Side discoveries from the recent `.claude/agents/` and `scripts/test_matrix.py` cleanup work. 5 items, 3 size classes. | 4/5 RESOLVED (TD-1..TD-4 done; TD-5 open). |
| `test-matrix-review-followups.md` | Deferred MEDIUM/LOW items from the `scripts/test_matrix.py` review. | All 4 groups RESOLVED. |
| `removed-scripts.md` | Policy for `required_scripts:` references in tool command frontmatter. | Active. |
| `wire-up-contract.md` | Integration Contract template + orphan audit gate; prevents "built but not wired" deliveries. | Active. |
