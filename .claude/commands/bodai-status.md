______________________________________________________________________

## name: bodai-status description: Check current Bodai-wide activity (Mahavishnu, Akosha, Crackerjack) — reads from ~/.mahavishnu/bodai-event-queue.json which the Phase 6A Bodai subscriber populates from Oneiric EventBridge.

Check current Bodai-wide activity across Mahavishnu, Akosha, and Crackerjack.

This command reads from `~/.mahavishnu/bodai-event-queue.json` (a JSON file populated by the Phase 6A Bodai subscriber at `.claude/hooks/bodai-activity-subscriber.py`, which consumes from Oneiric EventBridge — the unified event spine from Convergence Plan C1b). Each entry is an EventEnvelope (oneiric.runtime.events) with topic, payload, and headers.

Output format: a markdown table per component (Mahavishnu, Akosha, Crackerjack), each row showing topic + key payload fields. If the queue file is empty or does not exist, print a single 'no events yet' line — not an error.

Phase 5's `/mahavishnu:status` shows only Mahavishnu activity; this command shows the same plus Akosha and Crackerjack. Use `/mahavishnu:status` when you want Mahavishnu-only; use `/bodai-status` for the cross-component view.

Run the following Python via the Bash tool (tool ID `Bash`) to read the queue and group by source:

```python
import json
from pathlib import Path
from collections import defaultdict

queue_path = Path.home() / '.mahavishnu' / 'bodai-event-queue.json'
if not queue_path.exists():
    print('No Bodai events yet (queue file does not exist - Phase 6A subscriber not running)')
    raise SystemExit(0)

events = json.loads(queue_path.read_text() or '[]')
if not events:
    print('No Bodai events in the queue yet.')
    raise SystemExit(0)

by_source = defaultdict(list)
for e in events:
    source = e.get('headers', {}).get('source', 'unknown')
    by_source[source].append(e)

for source in sorted(by_source):
    print(f'## {source}')
    print('')
    print('| topic | payload summary | timestamp |')
    print('|-------|-----------------|-----------|')
    for e in by_source[source][-20:]:  # last 20 per source
        topic = e.get('topic', '?')
        ts = e.get('headers', {}).get('timestamp', '?')
        payload = e.get('payload', {})
        # Render payload as 'k=v, k=v' (truncate at 80 chars)
        kv = ', '.join(f'{k}={v}' for k, v in list(payload.items())[:5])
        if len(kv) > 80:
            kv = kv[:77] + '...'
        print(f'| {topic} | {kv} | {ts} |')
    print('')
```

Notes:

- Mirror the mahavishnu-status.md format (underscore frontmatter delimiter, descriptive paragraph, fenced code block).
- The command MUST gracefully handle the empty-queue case ('No events yet' — not an error). Both "queue file does not exist" and "queue file exists but is empty" produce a single friendly line and exit 0.
- The command is queue-file based, NOT CLI based. Do NOT invoke Mahavishnu / Akosha / Crackerjack CLIs here — those components do not yet expose CLI health surfaces for activity.
- The command does not modify any state; it is read-only and safe to invoke at any time.
- This command is not wired into `settings.json`. It is manual-invocation only (no auto-trigger).
