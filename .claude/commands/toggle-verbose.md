______________________________________________________________________

## name: toggle-verbose description: Toggle Claude CLI verbose/debug mode on/off

# Toggle Verbose/Debug Mode

This command programmatically toggles Claude CLI's verbose/debug mode.

## Current State

Check current debug state:

```python
import json
from pathlib import Path

settings_file = Path.home() / '.claude' / 'settings.json'
local_settings = Path.cwd() / '.claude' / 'settings.local.json'

if local_settings.exists():
    with open(local_settings) as f:
        data = json.load(f)
        verbose = data.get('verbose', False)
        debug = data.get('debug', False)
        print(f"Verbose: {verbose}, Debug: {debug}")
```

## Toggle Commands

### Enable Verbose Mode

```python
import json
from pathlib import Path

settings_file = Path.cwd() / '.claude' / 'settings.local.json'
settings_file.parent.mkdir(parents=True, exist_ok=True)

# Read existing settings
if settings_file.exists():
    with open(settings_file) as f:
        data = json.load(f)
else:
    data = {}

# Enable verbose
data['verbose'] = True
data['debug'] = True

# Write back
with open(settings_file, 'w') as f:
    json.dump(data, f, indent=2)

print("✅ Verbose mode ENABLED")
```

### Disable Verbose Mode

```python
import json
from pathlib import Path

settings_file = Path.cwd() / '.claude' / 'settings.local.json'

if settings_file.exists():
    with open(settings_file) as f:
        data = json.load(f)

    data['verbose'] = False
    data['debug'] = False

    with open(settings_file, 'w') as f:
        json.dump(data, f, indent=2)

    print("✅ Verbose mode DISABLED")
else:
    print("⚠️  No settings file to modify")
```

## CLI Flag (Runtime Override)

You can also use CLI flags without modifying config:

```bash
# Enable for single command
claude --verbose chat "your message"
claude --debug api,hooks chat "your message"

# Enable debug for specific categories
claude --debug api chat "test"      # Only API debug
claude --debug "!statsig" chat "test"  # All except statsig
```

## Notes

- Settings take effect on next Claude CLI invocation
- Runtime flags (`--verbose`, `--debug`) override config settings
- Debug filtering uses comma-separated categories or `!category` to exclude
