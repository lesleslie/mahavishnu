______________________________________________________________________

## name: verbose-on description: Enable Claude CLI verbose/debug mode

Enable verbose mode by running the toggle script:

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
print("   Changes take effect on next command")
```
