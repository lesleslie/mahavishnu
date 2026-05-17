# Toggle Verbose/Debug Mode

Toggle Claude CLI verbose/debug mode on or off for the current repo.

## Usage

- Read `.claude/settings.local.json` to see the current repo settings.
- Set `verbose` and `debug` to `true` to enable verbose mode.
- Set both values to `false` to disable verbose mode.
- Use CLI flags for one-off overrides when you do not want to edit config.

## Notes

- Settings take effect on the next Claude CLI invocation.
- Runtime flags override config settings.
