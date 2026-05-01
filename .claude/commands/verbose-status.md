______________________________________________________________________

## name: verbose-status description: Check current Claude CLI verbose/debug mode status

Check current verbose mode status:

```python
import json
from pathlib import Path

settings_file = Path.cwd() / '.claude' / 'settings.local.json'

if settings_file.exists():
    with open(settings_file) as f:
        data = json.load(f)

    verbose = data.get('verbose', False)
    debug = data.get('debug', False)

    print("📊 Verbose Mode Status:")
    print(f"   Verbose: {'✅ ON' if verbose else '⚪ OFF'}")
    print(f"   Debug: {'✅ ON' if debug else '⚪ OFF'}")
else:
    print("📊 Verbose Mode Status:")
    print("   Verbose: ⚪ OFF (default)")
    print("   Debug: ⚪ OFF (default)")
```
