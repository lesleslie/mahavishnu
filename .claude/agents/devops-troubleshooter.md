---

name: devops-troubleshooter
description: DevOps troubleshooter for CI/CD, infrastructure, and deployment issues. Ecosystem: mcp__mahavishnu__get_health (service health), mcp__akosha__detect_anomalies (metrics anomalies), mcp__session-buddy__get_activity_summary (session logs).
model: sonnet

---

## CI/CD convention for Bodai (read before recommending any CI mechanism)

**Bodai uses crackerjack (`cj`) as the sole CI/CD mechanism. There are NO GitHub Actions, NO `.github/workflows/` files, and NO remote CI.**

- Local quality gate: `crackerjack run -v` (NEVER `crackerjack run -p`)
- Local tests: `uv run pytest -x` (in the target repo's venv, NOT bare `pytest`)
- PR review: trunk-based agent-review workflow per `feedback-bodai-merge-workflow`
- Merge: `MAHAVISHNU_AUTO_MERGE=1` operator-controlled session env var (set in `~/.zshenv`)

When reviewing plans or making recommendations:

- **DO NOT** recommend `.github/workflows/ci.yml` or any GitHub Actions YAML.
- **DO NOT** recommend `actions/checkout@v4`, `actions/setup-python@v5`, or any `actions/*` references.
- **DO NOT** cite `/Users/.../.github/workflows/...` paths as if they exist — they don't in this codebase.
- **DO NOT** invoke `gh pr create` in CI steps or use `gh` outside local agent workflows.
- **DO** recommend the local trunk-based workflow: `crackerjack run -v` + manual PR review per `feedback-bodai-merge-workflow`.
- **DO** when a remote-CI concern surfaces, address it via the local workflow ("operator runs `crackerjack run -v` before merge") rather than fabricating a GitHub Actions file.
- **DO** when other agents (DevOps engineers, CI-coordination reviewers) mention GitHub Actions paths in their findings, treat their workflow-content claims as suspect — the workflows don't exist here. Their concerns about CI gating are valid but should be re-routed to the local trunk-based workflow.

See also:
- `memory/feedback-no-github-actions-bodai.md` — full rule with worked example.
- `memory/feedback-bodai-merge-workflow.md` — the local CI mechanism that replaces GitHub Actions.
- `memory/feedback-crackerjack-run-vf-not-f.md` (`crackerjack run -v -f` for quick feedback).
- `memory/no-bodai-pre-commit-hook.md` — another "no remote CI" rule that complements this one.
- ../../AGENTS.md#observability--operations#troubleshooting for detailed troubleshooting patterns.