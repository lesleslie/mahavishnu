## /run

**Smart Crackerjack Execution with Intelligent Fallback**

Executes Crackerjack AI auto-fix with enhanced session management and automatic fallback strategy.

## Usage

```
/run [--debug]
```

### Arguments

- `--debug`: Run in foreground with debug output visible (for troubleshooting)

## Description

Run the Crackerjack auto-fix workflow with tests enabled and the best available execution path.

## Execution Strategy

1. Try the session-buddy path first for analytics and continuity.
1. Fall back to the direct Crackerjack command if MCP routing fails.
1. Use the bash fallback only when the other paths are unavailable.

## What It Does

- Runs formatters, tests, and quality checks.
- Applies AI-assisted fixes for the detected issues.
- Repeats until the run is clean or the iteration limit is reached.

## Notes

- Keep this command predictable and reliable.
- Prefer the shortest viable path that still validates the repo.
