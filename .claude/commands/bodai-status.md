## name: bodai-status description: Check current Bodai-wide activity (Mahavishnu, Akosha, Crackerjack) — reads recent envelopes from the Oneiric bus (Redis Streams via mahavishnu.core.events.bodai_subscriber.read_bodai_events_since).

Check current Bodai-wide activity across Mahavishnu, Akosha, and Crackerjack.

This command reads recent envelopes from the Oneiric EventBridge
stream (Redis Streams transport) — the unified event spine from
Convergence Plan C1b. Phase 12a Task 5 retired the JSON-file queue
that previously held these envelopes; the bus is now the single
source of truth. Each entry is an EventEnvelope (oneiric.runtime.events)
with topic, payload, and headers.

Output format: a markdown table per component (Mahavishnu, Akosha,
Crackerjack), each row showing topic + key payload fields. If the
bus read fails (Redis unreachable, coredis missing) or no recent
envelopes are available, print a single 'no events yet' line — not
an error.

Phase 5's `/mahavishnu:status` shows only Mahavishnu activity; this
command shows the same plus Akosha and Crackerjack. Use
`/mahavishnu:status` when you want Mahavishnu-only; use `/bodai-status`
for the cross-component view.

Run the following Python via the Bash tool (tool ID `Bash`) to read
from the bus and group by source. The hook reads the most recent
100 envelopes from the stream (full history is bounded by Redis
Streams' MAXLEN policy); adjust `count` if you need more.

```python
import asyncio
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

async def _read_bus_envelopes() -> list:
    """One-shot read from the bus. Empty list on any failure (no errors propagated)."""
    repo_root = Path(os.environ.get('CLAUDE_PROJECT_DIR') or '/Users/les/Projects/mahavishnu')
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    try:
        from mahavishnu.core.events.bodai_subscriber import read_bodai_events_since
        redis_url = os.environ.get('MAHAVISHNU_BODAI_REDIS_URL', 'redis://localhost:6379/0')
        return await read_bodai_events_since(
            last_id=None,
            count=100,
            redis_url=redis_url,
        )
    except Exception:
        return []

def main() -> int:
    try:
        envelopes = asyncio.run(_read_bus_envelopes())
    except Exception:
        print('No Bodai events yet (bus read failed)')
        return 0

    if not envelopes:
        print('No Bodai events yet (bus is empty or unreachable)')
        return 0

    by_source: dict[str, list] = defaultdict(list)
    for _msg_id, envelope in envelopes:
        if not isinstance(envelope, dict):
            continue
        headers = envelope.get('headers') or {}
        source = headers.get('source', 'unknown')
        by_source[source].append(envelope)

    for source in sorted(by_source):
        print(f'## {source}')
        print('')
        print('| topic | payload summary | timestamp |')
        print('|-------|-----------------|-----------|')
        for e in by_source[source][-20:]:  # last 20 per source
            topic = e.get('topic', '?')
            ts = (e.get('headers') or {}).get('timestamp', '?')
            payload = e.get('payload') or {}
            # Render payload as 'k=v, k=v' (truncate at 80 chars)
            kv = ', '.join(f'{k}={v}' for k, v in list(payload.items())[:5])
            if len(kv) > 80:
                kv = kv[:77] + '...'
            print(f'| {topic} | {kv} | {ts} |')
        print('')
    return 0

sys.exit(main())
```

Notes:

- Mirror the mahavishnu-status.md format (underscore frontmatter delimiter, descriptive paragraph, fenced code block).
- The command MUST gracefully handle the empty-bus case ('No events yet' — not an error). Both "Redis unreachable" and "bus has no recent envelopes" produce a single friendly line and exit 0.
- The command is bus-read based, NOT CLI based. Do NOT invoke Mahavishnu / Akosha / Crackerjack CLIs here — those components do not yet expose CLI health surfaces for activity.
- The command does not modify any state; it is read-only and safe to invoke at any time.
- This command is not wired into `settings.json`. It is manual-invocation only (no auto-trigger).
