______________________________________________________________________

## name: verbose-off description: Disable Claude CLI verbose/debug mode

Disable verbose mode:

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
    print("   Changes take effect on next command")
else:
    print("⚠️  No settings file found (verbose mode already off)")
```
