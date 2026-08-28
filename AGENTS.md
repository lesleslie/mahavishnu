# Repository Guidelines

## Project Structure & Module Organization

- `mahavishnu/` contains the application package: core orchestration logic in `core/`, MCP server code in `mcp/`, WebSocket support in `websocket/`, content ingestion in `ingestion/`, and CLI entrypoints in `cli.py`.
- MCP tools live under `mahavishnu/mcp/tools/`; keep tool modules narrowly scoped by domain and register new tools through the FastMCP server wiring in `mahavishnu/mcp/server_core.py`.
- Configuration lives in `settings/`, with committed defaults in `settings/mahavishnu.yaml` and developer overrides in `settings/local.yaml` when needed.
- Tests live in `tests/` and include unit, integration, and property coverage; mirror package paths when adding new tests and keep generated artifacts such as `htmlcov/`, `.coverage`, and local SQLite files out of review.

## Build, Test, and Development Commands

- `uv sync --group dev` installs runtime and development dependencies for local work.
- `uv run pytest` runs the full test suite; use `uv run pytest tests/unit/test_config.py` or `-k <pattern>` for targeted iteration.
- `uv run pytest --cov=mahavishnu --cov-report=html` generates a local coverage report in `htmlcov/`.
- `uv run ruff check mahavishnu tests` and `uv run ruff format mahavishnu tests` cover linting and formatting.
- `uv run mypy mahavishnu` or `uv run pyright mahavishnu` performs static type checks depending on the issue at hand.
- `uv run mahavishnu mcp start`, `uv run mahavishnu mcp status`, and `uv run mahavishnu mcp health` are the primary local MCP server smoke-test commands.

## CLI Installation

- `uv tool install --editable .` puts `mahavishnu` on `PATH` (symlinked into `~/.local/bin/`) so you can run it from any directory without `uv run`. This is what makes the auto-installed git hooks (see below) and shell commands like `mahavishnu start` work portably across machines.
- The optional TUI (`textual`) lives in the `tui` dependency group and is **not** required for the CLI to start — `mahavishnu/cli/monitoring_cli.py` already lazily imports the TUI under the `TUI_AVAILABLE` flag. Install only if you want the command-palette / monitor app: `uv tool install --editable --with "textual>=8.2.7" .`.
- Re-run `uv tool install --editable --reinstall .` after pulling new changes if the installed console script's import paths go stale.

## Coding Style & Naming Conventions

- Target modern Python with explicit type hints, small composable functions, and Pydantic models for configuration, request validation, and structured tool inputs.
- Follow the existing package split: orchestration concerns in `core/`, transport concerns in `mcp/` or `websocket/`, and cross-cutting helpers in focused support modules rather than monolith files.
- Keep module names snake_case, classes PascalCase, and CLI or MCP entrypoints explicit about side effects and async boundaries.
- Prefer extending existing adapter, settings, and exception patterns instead of introducing parallel abstractions.

## Testing Guidelines

- Add tests alongside every substantive change, mirroring package structure under `tests/unit/`, `tests/integration/`, or `tests/property/` as appropriate.
- For MCP features, cover both tool behavior and server registration paths when possible; integration tests should verify realistic inputs and error handling, not just happy paths.
- Reuse existing fixtures and factories before creating new ones, and prefer deterministic inputs for orchestration, routing, and workflow tests.
- Review `htmlcov/index.html` after larger changes to catch untested branches in orchestration code, MCP tools, and adapters.

## Commit & Pull Request Guidelines

- Use focused commits with conventional or clearly scoped subjects such as `feat(mcp): add workflow status tool` or `fix(routing): tighten fallback selection`.
- PRs should describe the user-visible behavior change, affected adapters or MCP tools, commands run for validation, and any follow-up work or known gaps.
- Include CLI transcripts, MCP examples, or screenshots when changing operator-facing output, dashboards, or live monitoring flows.

## MCP & Ecosystem Notes

- Mahavishnu is the orchestrator for the Bodai ecosystem and commonly integrates with Session-Buddy, Akosha, Crackerjack, Dhara, Oneiric, and related MCP services.
- Treat Mahavishnu as an ecosystem-internal control plane first. When editing docs, features, or examples, prefer language that reflects Bodai-owned repos and services as the primary operating scope unless the work is explicitly about external productization.
- This repository does not use GitHub Actions for active CI or quality gating. Use Crackerjack-based validation and repository-local test commands instead of adding or relying on `.github/workflows/*` for enforcement.
- Treat external service ports, URLs, and auth settings as configuration, not constants embedded in new code.
- New orchestration features should fit the existing adapter model and preserve the MCP-first design: expose reusable capabilities through tools or well-defined service layers rather than repo-local scripts only.
- When dispatching parallel-fanout workflows across repos, ensure the parent session is in a clean main checkout (not inside any Claude-Code worktree) and let each agent create its own worktree under `$XDG_RUNTIME_DIR/...` or `/tmp/<branch>` via raw `git worktree add`; subagents inherit the parent CWD and `EnterWorktree` will refuse. See `.claude/decisions/2026-08-28-cross-repo-fanout-cwd-isolation.md`.

## Git Hooks

- The `post-commit`, `post-merge`, and `post-rewrite` hooks generated by `mahavishnu index install-hooks <repo-path>` invoke `mahavishnu index repo --trigger git-event "$(pwd)" &` (background) to keep mahavishnu's repo index current. They assume `mahavishnu` is on `PATH` — see **CLI Installation** above. Without it, every commit logs `mahavishnu: command not found` (non-fatal, but noisy).
- Never edit `.git/hooks/*` by hand to hardcode paths; the install-hooks template already uses bare `mahavishnu` so the hook is portable across machines. Use `mahavishnu index uninstall-hooks <path>` to remove hooks from a repo, and `mahavishnu index install-hooks --force <path>` to regenerate them after a template change.

## Security & Configuration Tips

- Never hard-code secrets, bearer tokens, or local machine paths; load them from environment variables or layered settings.
- Preserve path validation and repository safety checks when touching worktree, filesystem, or cross-repo coordination features.
- When adding new MCP tools, validate inputs strictly and keep shell execution isolated from user-controlled strings.
