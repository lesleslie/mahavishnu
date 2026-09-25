"""cron_core — pure planner for one rebuild cycle.

Separated from cron.py so it can be unit-tested without asyncio.
Exposes `discover_records()` so the CLI orchestrator (Task 15) can
reuse the same scan logic.

Round-3 BLOCKER fix: this cycle acquires a MCP-backed mutex before
touching any records and releases it after the cycle completes
(success or failure). Holder format is `<hostname_hash[:8]>/<pid>`;
lock TTL is REBUILD_LOCK_TTL_SECONDS = 60s; if the existing holder
is older than the TTL, this cycle takes over (stale-PID takeover).

DLQ semantics: transient MCP write failures append to
`plan_index/meta/recent_errors` (a bounded JSON list, max 20 entries,
30-day TTL). Failures are non-fatal — the rebuilder continues with the
remaining records.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import socket
import subprocess
import time
from typing import TYPE_CHECKING, Any, Protocol
import uuid

from mahavishnu.plan_index.errors import PlanRebuildLockedError
from mahavishnu.plan_index.paths import errors_log_path
from mahavishnu.plan_index.record import PlanRecord

if TYPE_CHECKING:
    from mahavishnu.plan_index.rebuild import PlanIndexRebuilder
    from mahavishnu.plan_index.store import PlanIndexStore

__all__ = [
    "RebuildOutcome",
    "discover_records",
    "run_rebuild_cycle",
]

RECENT_ERRORS_MAX = 20
RECENT_ERRORS_TTL_DAYS = 30
ENTITIES_COUNT_KEY = "plan_index/meta/entities_count"
CYCLES_TOTAL_KEY = "plan_index/meta/cycles_total"
SUCCESS_CYCLES_KEY = "plan_index/meta/successful_cycles_total"
ERRORS_TOTAL_KEY = "plan_index/meta/errors_total"
LAST_REBUILD_MS_KEY = "plan_index/meta/last_rebuild_ms"
LAST_SUCCESS_MS_KEY = "plan_index/meta/last_success_ms"
RECENT_ERRORS_KEY = "plan_index/meta/recent_errors"

# Round-3 addition: MCP-backed rebuild mutex.
# Holder format is `<hostname_hash[:8]>/<pid>`; tests assert this exact regex.
REBUILD_LOCK_HOLDER_KEY = "plan_index/meta/rebuild_lock/holder"
REBUILD_LOCK_ACQUIRED_KEY = "plan_index/meta/rebuild_lock/acquired_at_ms"
REBUILD_LOCK_TTL_SECONDS = 60
# Round-3 follow-up (Task 14.7): retain lock-history keys on stale takeover
# so observability can show "Cycle B took over from stale Cycle A at T".
REBUILD_LOCK_HISTORY_KEY_PREFIX = "plan_index/meta/rebuild_lock/history/"
REBUILD_LOCK_HISTORY_TTL_SECONDS = 7 * 86400
# Task 14.6: transient, per-attempt claim keys used to arbitrate concurrent
# acquisitions. Claim keys are unique (never overwritten) and are deleted as
# soon as arbitration resolves, so they never accumulate across cycles.
REBUILD_LOCK_CLAIM_KEY_PREFIX = "plan_index/meta/rebuild_lock/claim/"

_FRONTMATTER_RE = re.compile(r"\A---\s*\n(?P<fm>.*?)\n---\s*(?:\n|$)", re.DOTALL)
_EXCLUDED_DIR_NAMES: frozenset[str] = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "__pycache__",
        "node_modules",
        "htmlcov",
        "dist",
        ".pytest_cache",
        ".archive",
        "archive",
        "backups",
        "coverage_report",
        "assets",
    }
)
_EXCLUDED_FILE_NAMES: frozenset[str] = frozenset({"PLAN_INDEX.md"})

_logger = logging.getLogger(__name__)


def _hostname_hash() -> str:
    """Stable 8-hex-char identifier for this host (no PII leakage).

    Used to format the rebuild-lock holder key. Returns sha256(hostname)[:8].
    """
    return hashlib.sha256(socket.gethostname().encode("utf-8")).hexdigest()[:8]


def _lock_holder() -> str:
    """Return the canonical `hostname_hash[:8]/pid` lock-holder string."""
    return f"{_hostname_hash()}/{os.getpid()}"


class _LockStore(Protocol):
    """The MCP KV surface the rebuild lock needs. No compare-and-swap."""

    async def put(self, key: str, value: str, *, ttl: int | None = ...) -> None: ...
    async def get(self, key: str) -> str | None: ...
    async def list_prefix(self, prefix: str) -> list[tuple[str, str]]: ...
    async def delete(self, key: str) -> None: ...


def _new_claim_key() -> str:
    """Unique, time-ordered claim key for one acquisition attempt.

    The microsecond prefix makes claim keys sort in (approximate)
    acquisition order; the uuid4 suffix guarantees uniqueness so that two
    concurrent cycles can never overwrite each other's claim.
    """
    return f"{REBUILD_LOCK_CLAIM_KEY_PREFIX}{time.time_ns() // 1000:020d}-{uuid.uuid4().hex}"


def _claim_is_active(value: str, now_ms: int) -> bool:
    """True when a claim was written within the lock TTL window."""
    try:
        claimed_ms = int(value)
    except ValueError:
        return False
    return now_ms - claimed_ms < REBUILD_LOCK_TTL_SECONDS * 1000


async def _live_lock_holder(mcp: _LockStore, now_ms: int) -> tuple[str, int] | None:
    """Return `(holder, age_ms)` when a non-stale holder is published."""
    holder_raw = await mcp.get(REBUILD_LOCK_HOLDER_KEY)
    acquired_raw = await mcp.get(REBUILD_LOCK_ACQUIRED_KEY)
    if holder_raw is None or acquired_raw is None:
        return None
    try:
        acquired_ms = int(acquired_raw)
    except ValueError:
        return None
    age_ms = now_ms - acquired_ms
    if age_ms >= REBUILD_LOCK_TTL_SECONDS * 1000:
        return None
    return holder_raw, age_ms


async def _acquire_rebuild_lock(mcp: _LockStore, new_holder: str, now_ms: int) -> None:
    """Claim the rebuild lock, or raise `PlanRebuildLockedError`.

    A plain `get`-then-`put` on the holder key is a TOCTOU race: two
    concurrent cycles both read `holder is None`, both write their own
    holder, and neither sees the other. The MCP KV surface exposed to
    plan_index has no compare-and-swap, so acquisition is arbitrated with
    unique claim keys instead:

      1. Write a claim key that no other cycle can overwrite.
      2. List every claim; the lexicographically smallest *active* claim
         wins. Because claims are never overwritten, any cycle that lists
         after a rival's write is guaranteed to see that rival and defer.
      3. Re-read the holder key before publishing, to close the window
         where a rival won arbitration and published while we listed.
      4. Publish our holder, then drop our claim (in `finally`, on every
         path). From here on the holder key provides mutual exclusion, so
         claims never linger between cycles.
    """
    claim_key = _new_claim_key()
    await mcp.put(claim_key, str(now_ms), ttl=REBUILD_LOCK_TTL_SECONDS)
    try:
        pairs = await mcp.list_prefix(REBUILD_LOCK_CLAIM_KEY_PREFIX)
        active = sorted(k for k, v in pairs if _claim_is_active(v, now_ms))
        if active and active[0] != claim_key:
            raise PlanRebuildLockedError(active[0], 0)
        live = await _live_lock_holder(mcp, now_ms)
        if live is not None:
            raise PlanRebuildLockedError(*live)
        await mcp.put(REBUILD_LOCK_HOLDER_KEY, new_holder)
        await mcp.put(REBUILD_LOCK_ACQUIRED_KEY, str(now_ms))
    finally:
        await mcp.delete(claim_key)


@dataclass(frozen=True, slots=True)
class RebuildOutcome:
    success: int
    errors: int
    entities_count: int
    cycles_total: int
    successful_cycles_total: int
    errors_total: int
    last_rebuild_ms: int
    last_success_ms: int | None


def _parse_frontmatter(text: str) -> dict[str, Any]:
    """Parse a small `key: value` YAML subset. Avoids the PyYAML dep at scan time.

    Supports:
      - bare scalars: `key: value`
      - quoted scalars: `key: "value"` / `key: 'value'`
      - null scalars: `key: null` / `key: ~`
      - empty scalars: `key:` (treated as null)
      - block lists under a key: `key:` followed by indented `- item` lines
    """
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}
    lines = match.group("fm").splitlines()
    out: dict[str, Any] = {}
    i = 0
    while i < len(lines):
        raw_line = lines[i]
        line = raw_line.strip()
        if not line or line.startswith("#"):
            i += 1
            continue
        if ":" not in line:
            i += 1
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if value in {"", "null", "~"}:
            # Empty / null scalar OR start of a block list. Look ahead to
            # the next non-blank line to decide.
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            if j < len(lines):
                next_stripped = lines[j].strip()
                next_indented = lines[j].startswith((" ", "\t"))
                if next_indented and next_stripped.startswith("- "):
                    # Block list: collect items until the indentation level
                    # changes or the next top-level key.
                    items: list[str] = []
                    k = j
                    while k < len(lines):
                        candidate = lines[k]
                        cand_stripped = candidate.strip()
                        if not cand_stripped:
                            k += 1
                            continue
                        if not candidate.startswith((" ", "\t")):
                            break
                        if cand_stripped.startswith("- "):
                            items.append(cand_stripped[2:].strip().strip('"').strip("'"))
                            k += 1
                            continue
                        # Indented but not a list item — bail out.
                        break
                    out[key] = items
                    i = k
                    continue
            # No list follows — treat as null scalar.
            out[key] = None if value in {"null", "~"} else ""
            i += 1
            continue
        out[key] = value.strip('"').strip("'")
        i += 1
    return out


def _coerce_date(value: Any) -> str:
    """Coerce a YAML-parsed date (datetime.date or str) to YYYY-MM-DD.

    Returns "" if the value is missing, unparsable, or empty.
    """
    if value is None or value == "" or value == "null" or value == "~":
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat()
    import datetime as _dt

    if isinstance(value, _dt.date):
        return value.isoformat()
    if isinstance(value, str):
        return value
    return ""


def _coerce_str(value: Any) -> str:
    """Coerce a YAML scalar to a stripped string. Treats null/~ as ""."""
    if value is None or value == "" or value == "null" or value == "~":
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _coerce_blocks_on(value: Any) -> list[str]:
    """Coerce frontmatter `blocks_on` to a list of plan_id strings."""
    if value is None or value == "" or value == "null" or value == "~":
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        # Comma-separated fallback for hand-written frontmatter.
        items = [part.strip() for part in value.split(",")]
        return [item for item in items if item]
    return []


def _git_blob_sha(repo_root: Path, rel_path: str) -> str:
    """Return `git rev-parse HEAD:<rel_path>` if available, else empty string.

    Empty string (rather than a placeholder hash) signals "sha unknown" — the
    PlanRecord sha field is allowed to be any string, so consumers can detect
    missing SHAs by length.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", f"HEAD:{rel_path}"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except OSError, subprocess.TimeoutExpired:
        return ""
    if result.returncode != 0:
        return ""
    sha = result.stdout.strip()
    # Guard against pathological whitespace output.
    if not re.match(r"^[0-9a-f]{40}$", sha):
        return ""
    return sha


def _derive_plan_id(rel_path: str) -> str:
    """Derive `plan-<basename-without-.md>` from a relative path."""
    base = rel_path.removesuffix(".md")
    return f"plan-{base}"


def _normalize_repo_url(repo: str) -> str:
    """Normalize a repo URL (strip trailing .git, lowercase host)."""
    if not repo:
        return repo
    url = repo.strip()
    url = url.removesuffix(".git")
    return url


def _is_store_directory(directory: Path) -> bool:
    """A directory is a 'store' if it has >= 2 .md files with valid frontmatter."""
    count = 0
    try:
        for md in directory.rglob("*.md"):
            if md.name in _EXCLUDED_FILE_NAMES:
                continue
            try:
                fm = _parse_frontmatter(md.read_text(errors="replace"))
            except OSError:
                continue
            if "status" in fm and "title" in fm:
                count += 1
                if count >= 2:
                    return True
    except OSError:
        return False
    return False


def discover_records(repo_root: Path) -> list[PlanRecord]:
    """Walk `repo_root`, auto-discover stores, parse frontmatter, return records.

    Importable so the CLI orchestrator (Task 15) can reuse this.
    Mirrors `scripts/regenerate_plan_index.py` Phase A — auto-discover
    stores (skipping system dirs), parse each .md file's frontmatter,
    return a `PlanRecord` per file with ALL 14 fields populated.

    Defaults for fields missing from frontmatter:
      - role: "implementation" (most plans are implementation specs)
      - topic: "" (no vocabulary)
      - date: falls back to last_reviewed, then ""
      - last_reviewed: falls back to date, then ""
      - superseded_by: None (the literal string "null" or "~" is treated as None)
      - blocks_on: [] (empty list)
      - sha: `git rev-parse HEAD:<rel>` if available, else "" (signals "unknown")
      - lifecycle_state: None (no frontmatter source; status is the surface)
      - updated_at_ms: int(datetime.now(tz=UTC).timestamp() * 1000)

    A file whose status is not in PlanRecord's accepted vocabulary is skipped
    (the frozen dataclass's __post_init__ would otherwise raise ValueError).
    """
    repo_root = Path(repo_root).resolve()
    records: list[PlanRecord] = []
    if not repo_root.is_dir():
        return records

    accepted_statuses = frozenset({"draft", "active", "partial", "shipped", "complete"})

    for directory in sorted(repo_root.rglob("*")):
        if not directory.is_dir():
            continue
        if any(part in _EXCLUDED_DIR_NAMES for part in directory.parts):
            continue
        if not _is_store_directory(directory):
            continue
        for md in sorted(directory.rglob("*.md")):
            if md.name in _EXCLUDED_FILE_NAMES:
                continue
            try:
                rel = md.relative_to(repo_root).as_posix()
            except ValueError:
                continue
            try:
                text = md.read_text(errors="replace")
            except OSError:
                continue
            fm = _parse_frontmatter(text)
            status = _coerce_str(fm.get("status"))
            title = _coerce_str(fm.get("title"))
            if not status or not title or status not in accepted_statuses:
                continue
            repo = _normalize_repo_url(_coerce_str(fm.get("repo")))
            plan_id = _derive_plan_id(rel)

            role = _coerce_str(fm.get("role")) or "implementation"
            topic = _coerce_str(fm.get("topic"))

            date = _coerce_date(fm.get("date"))
            last_reviewed = _coerce_date(fm.get("last_reviewed"))
            # Cross-fallback: prefer last_reviewed if date is empty, and vice-versa.
            if not date and last_reviewed:
                date = last_reviewed
            if not last_reviewed and date:
                last_reviewed = date

            superseded_by_raw = _coerce_str(fm.get("superseded_by"))
            superseded_by: str | None = (
                superseded_by_raw
                if superseded_by_raw and superseded_by_raw not in {"null", "~"}
                else None
            )

            blocks_on = _coerce_blocks_on(fm.get("blocks_on"))
            sha = _git_blob_sha(repo_root, rel)
            updated_at_ms = int(datetime.now(tz=UTC).timestamp() * 1000)

            records.append(
                PlanRecord(
                    plan_id=plan_id,  # ty: ignore[invalid-argument-type]
                    path=rel,
                    title=title,
                    status=status,  # ty: ignore[invalid-argument-type]
                    role=role,  # ty: ignore[invalid-argument-type]
                    topic=topic,
                    date=date,
                    last_reviewed=last_reviewed,
                    superseded_by=superseded_by,
                    blocks_on=blocks_on,  # ty: ignore[invalid-argument-type]
                    sha=sha,
                    repo=repo,
                    lifecycle_state=None,
                    updated_at_ms=updated_at_ms,
                )
            )
    return records


def _write_error_log(errors: list[Any]) -> None:
    """Append structured error lines to `errors.log`. Never raises."""
    if not errors:
        return
    try:
        path = errors_log_path()
        with path.open("a", encoding="utf-8") as fh:
            fh.writelines(
                json.dumps(
                    {
                        "ts_ms": int(datetime.now(tz=UTC).timestamp() * 1000),
                        "err": err,
                    }
                )
                + "\n"
                for err in errors
            )
    except OSError as exc:
        _logger.warning("could not write errors.log: %s", exc)


async def run_rebuild_cycle(
    store: PlanIndexStore,
    rebuilder: PlanIndexRebuilder,
    *,
    repo_root: Path | None = None,
) -> RebuildOutcome:
    """Run one rebuild cycle: scan, normalize, upsert, update counters.

    Steps:
      0. Acquire lock at plan_index/meta/rebuild_lock/{holder,acquired_at_ms}.
         Raise PlanRebuildLockedError if a non-stale holder is held.
      1. Call `discover_records(repo_root)` to get the list of records.
      2. For each record: normalize the repo URL, derive the plan_id,
         upsert to MCP via `rebuilder.upsert_all`.
      3. On failure, append to `recent_errors` (bounded at 20) and write
         a structured line to `errors.log`.
      4. Update all six meta keys including the explicit `entities_count`.
      5. Truncate `recent_errors` to 20 entries.
      6. Release lock by deleting the holder key (always, in `finally`).
    """
    mcp = store._mcp  # type: ignore[attr-defined]

    # --- Lock acquisition (round-3 addition) ------------------------------
    holder_raw = await mcp.get(REBUILD_LOCK_HOLDER_KEY)
    acquired_raw = await mcp.get(REBUILD_LOCK_ACQUIRED_KEY)
    now_ms_for_lock = int(datetime.now(tz=UTC).timestamp() * 1000)
    new_holder = _lock_holder()

    if holder_raw is not None and acquired_raw is not None:
        acquired_ms = int(acquired_raw)
        age_ms = now_ms_for_lock - acquired_ms
        if age_ms < REBUILD_LOCK_TTL_SECONDS * 1000:
            # Lock is live — surface the conflict to the caller.
            raise PlanRebuildLockedError(holder_raw, age_ms)
        # Stale lock: log and take over (fall through to write our own).
        _logger.warning(
            "rebuild lock holder=%s is stale (age_ms=%d > ttl=%d); taking over",
            holder_raw,
            age_ms,
            REBUILD_LOCK_TTL_SECONDS * 1000,
        )
        # Retain provenance: write a history key with takeover context.
        # The finally block must NOT delete these history keys (only the
        # active holder), so observability can later surface who took over
        # from whom at what timestamp.
        history_key = f"{REBUILD_LOCK_HISTORY_KEY_PREFIX}{uuid.uuid4().hex}"
        await mcp.put(
            history_key,
            json.dumps(
                {
                    "previous_holder": holder_raw,
                    "took_over_at_ms": now_ms_for_lock,
                    "took_over_by": new_holder,
                }
            ),
            ttl=REBUILD_LOCK_HISTORY_TTL_SECONDS,
        )

    # Atomically claim the lock (Task 14.6). Replaces the previous
    # unconditional `put`, which let concurrent cycles clobber each other.
    await _acquire_rebuild_lock(mcp, new_holder, now_ms_for_lock)

    try:
        records: list[PlanRecord] = discover_records(repo_root) if repo_root is not None else []

        success, error_count, errors = await rebuilder.upsert_all(records, store)

        now_ms = int(datetime.now(tz=UTC).timestamp() * 1000)

        cycles_raw = await mcp.get(CYCLES_TOTAL_KEY)
        cycles_total = int(cycles_raw) + 1 if cycles_raw else 1
        await mcp.put(CYCLES_TOTAL_KEY, str(cycles_total))

        await mcp.put(ENTITIES_COUNT_KEY, str(success))

        if error_count == 0:
            success_raw = await mcp.get(SUCCESS_CYCLES_KEY)
            successful = int(success_raw) + 1 if success_raw else 1
            await mcp.put(SUCCESS_CYCLES_KEY, str(successful))
            await mcp.put(LAST_SUCCESS_MS_KEY, str(now_ms))
            last_success_ms: int | None = now_ms
        else:
            last_success_ms = None

        errors_total = error_count
        if error_count > 0:
            errors_raw = await mcp.get(ERRORS_TOTAL_KEY)
            errors_total = (int(errors_raw) if errors_raw else 0) + error_count
            await mcp.put(ERRORS_TOTAL_KEY, str(errors_total))

            recent_raw = await mcp.get(RECENT_ERRORS_KEY)
            recent: list[dict[str, Any]] = json.loads(recent_raw) if recent_raw else []
            for err in errors:
                recent.append({"ts_ms": now_ms, "op": "upsert", "err": "see ctx", "ctx": err})
            recent = recent[-RECENT_ERRORS_MAX:]
            await mcp.put(
                RECENT_ERRORS_KEY,
                json.dumps(recent),
                ttl=RECENT_ERRORS_TTL_DAYS * 86400,
            )

            _write_error_log(errors)

        await mcp.put(LAST_REBUILD_MS_KEY, str(now_ms))

        from mahavishnu.plan_index.health import (
            PlanIndexFeedState,
            set_plan_index_feed_state,
        )

        feed = PlanIndexFeedState(
            entities_count=success,
            last_updated_timestamp=now_ms,
            errors_total=errors_total,
            cycles_total=cycles_total,
        )
        set_plan_index_feed_state(feed)

        return RebuildOutcome(
            success=success,
            errors=error_count,
            entities_count=success,
            cycles_total=cycles_total,
            successful_cycles_total=int(await mcp.get(SUCCESS_CYCLES_KEY) or "0"),
            errors_total=errors_total,
            last_rebuild_ms=now_ms,
            last_success_ms=last_success_ms,
        )
    finally:
        # Always release the lock, even on partial failure.
        try:
            await mcp.delete(REBUILD_LOCK_HOLDER_KEY)
        except Exception as release_exc:  # noqa: BLE001
            _logger.warning("could not release rebuild lock: %s", release_exc)
