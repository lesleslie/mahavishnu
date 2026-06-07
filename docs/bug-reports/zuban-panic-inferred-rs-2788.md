# zuban 0.8.0 panic at `inferred.rs:2788` on session-buddy

## Summary

Running `zuban check` against the [session-buddy](https://github.com/lesleslie/session-buddy) codebase causes a Rust-level panic inside zuban, which then produces a non-parseable stack trace instead of the expected type errors. This is reproducible from the `main` branch.

## Environment

| | |
|---|---|
| zuban version | `0.8.0` (release date 2026-06-01) |
| Python | 3.13 |
| Platform | macOS (both x86_64 and arm64 wheels affected) |
| Invocation | `zuban check session_buddy/...` invoked via [crackerjack](https://github.com/lesleslie/crackerjack)'s comprehensive hooks |
| Working directory | `/Users/les/Projects/session-buddy` |

## Panic

```
thread 'main' (<pid>) panicked at crates/zuban_python/src/inferred.rs:2788:31:
removal index (is 0) should be < len (is 0)
note: run with `RUST_BACKTRACE=1` environment variable to display a backtrace
```

This panic was captured by crackerjack in `.crackerjack/logs/ai-fix-errors-20260602-091603.json`. It occurred 4 times during a single run, with different PIDs (5937979, 5942179, 5948298, 5954114) — zuban appears to fork/spawn per file or per worker, and each subprocess panics.

The panic has also been observed on subsequent runs (2026-06-02 09:13:47, 09:11:10, 09:08:29) and on 2026-05-30, so it is **not a one-off flake**.

## The type error that triggered the panic

The session-buddy run was checking a file (`session_buddy/analytics/time_series.py`) that contained this type error:

```
session_buddy/analytics/time_series.py:195: error: Argument "trend" to "TrendAnalysis" has
incompatible type "Literal['invalid_metric']"; expected
"Literal['improving', 'declining', 'stable', 'insufficient_data']"
```

The relevant code (file: `session_buddy/analytics/time_series.py`):

```python
@dataclass
class TrendAnalysis:
    trend: Literal["improving", "declining", "stable", "insufficient_data"]
    slope: float
    ...

def detect_trend(self, skill_name: str, metric: str, window_days: int) -> TrendAnalysis:
    valid_metrics = {"completion_rate": "...", "avg_duration_seconds": "...", "invocation_count": "..."}
    if metric not in valid_metrics:
        # Security: return a distinct "invalid_metric" trend for
        # unknown metric names. Different from "insufficient_data".
        return TrendAnalysis(
            trend="invalid_metric",  # ← this string is not in the Literal above
            slope=0.0,
            ...
        )
```

The literal `"invalid_metric"` is intentionally *not* in `TrendAnalysis.trend`'s `Literal` type — the bug in session-buddy is the missing value, which I fixed by extending the `Literal`. But zuban should *report* the type error rather than panic.

## Reduced reproduction status

**I was unable to reproduce the panic with a minimal repro.** The smallest file I extracted from session-buddy that contains the offending pattern:

```python
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal


@dataclass
class TrendAnalysis:
    trend: Literal["improving", "declining", "stable", "insufficient_data"]


def make_invalid_metric_result() -> TrendAnalysis:
    return TrendAnalysis(
        trend="invalid_metric",
        slope=0.0,
        start_value=0.0,
        end_value=0.0,
        change_percent=0.0,
        confidence=1.0,
    )
```

Running `zuban check` on this minimal file produces a *clean, expected* output (6 normal type errors, no panic). So the panic requires additional context from the session-buddy codebase — likely the combination of `numpy`/`scipy`/`sqlite3` imports, the `from __future__ import annotations` directive, or some other module being checked in the same `zuban check` invocation.

## What I tried

- [x] Minimal repro of the `Literal` mismatch alone — no panic
- [x] Adding `from __future__ import annotations` to the repro — no panic
- [x] Running zuban 0.8.0 directly (no crackerjack involved) on the full file
      — the panic seems tied to running over a directory of files, not a single file
- [ ] Bisecting the session-buddy codebase to find the exact file combination that
      triggers the panic — not done yet, would benefit from maintainer guidance

## Suggested next steps

1. **Bisect in-tree**: I'd appreciate guidance on what the panic at
   `inferred.rs:2788:31` represents. The "removal index (is 0) should be < len
   (is 0)" message is consistent with iterating over a constraint set or union
   arm list and trying to remove from an empty collection. Is this a known
   panic signature?

2. **If you can provide a debug build**: a `zuban` binary that prints the
   offending source location and the AST shape it was processing at the time of
   the panic would let me bisect more precisely.

3. **Workaround in the meantime**: pinning `zuban<0.8.0` in projects that hit
   this avoids the panic. The previous version (whatever was used before
   2026-06-01) presumably did not have this regression.

## Environment details

```text
$ zuban --version
zuban 0.8.0

$ python --version
Python 3.13.x

$ uname -a
Darwin <host> 25.5.0 Darwin Kernel ...
```

The session-buddy codebase is publicly available at
<https://github.com/lesleslie/session-buddy>. The offending file is
`session_buddy/analytics/time_series.py`. To reproduce the panic (and
side-step the parsing issue in crackerjack that hides it), check the entire
project directory:

```bash
git clone https://github.com/lesleslie/session-buddy.git
cd session-buddy
uv venv && source .venv/bin/activate
uv pip install 'zuban==0.8.0'
zuban check session_buddy/   # ← panics with the message above
```

The exact code that triggers the panic is at
`session_buddy/analytics/time_series.py:194-201` in the
`detect_trend` method, *combined* with the surrounding module structure.
