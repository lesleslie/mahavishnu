"""cron_core — pure planner for one rebuild cycle.

Separated from cron.py so it can be unit-tested without asyncio.
Exposes `discover_records()` so the CLI orchestrator (Task 15) can
reuse the same scan logic.

Round-3 BLOCKER fix: this cycle acquires a Dhara-backed mutex before
touching any records and releases it after the cycle completes
(success or failure). Holder format is `<hostname_hash[:8]>/<pid>`;
lock TTL is REBUILD_LOCK_TTL_SECONDS = 60s; if the existing holder
is older than the TTL, this cycle takes over (stale-PID takeover).

DLQ semantics: transient Dhara write failures append to
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
from typing import TYPE_CHECKING, Any

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

# Round-3 addition: Dhara-backed rebuild mutex.
# Holder format is `<hostname_hash[:8]>/<pid>`; tests assert this exact regex.
REBUILD_LOCK_HOLDER_KEY = "plan_index/meta/rebuild_lock/holder"
REBUILD_LOCK_ACQUIRED_KEY = "plan_index/meta/rebuild_lock/acquired_at_ms"
REBUILD_LOCK_TTL_SECONDS = 60

_FRONTMATTER_RE = re.compile(
    r"\A---\s*\n(?P<fm>.*?)\n---\s*(?:\n|$)", re.DOTALL
)
_EXCLUDED_DIR_NAMES: frozenset[str] = frozenset(
    {
        ".git", ".venv", "venv", "__pycache__", "node_modules",
        "htmlcov", "dist", ".pytest_cache", ".archive", "archive",
        "backups", "coverage_report", "assets",
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


def _parse_frontmatter(text: str) -> dict[str, str]:
    """Parse a small `key: value` YAML subset. Avoids the PyYAML dep at scan time."""
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}
    out: dict[str, str] = {}
    for line in match.group("fm").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        out[key.strip()] = value.strip().strip('"').strip("'")
    return out


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
    return a `PlanRecord` per file.
    """
    repo_root = Path(repo_root).resolve()
    records: list[PlanRecord] = []
    if not repo_root.is_dir():
        return records

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
            if "status" not in fm or "title" not in fm:
                continue
            repo = _normalize_repo_url(fm.get("repo", ""))
            plan_id = _derive_plan_id(rel)
            records.append(
                PlanRecord(
                    plan_id=plan_id,
                    path=rel,
                    title=fm["title"],
                    status=fm["status"],
                    repo=repo,
                )
            )
    return records


def _write_error_log(errors: list[dict[str, Any]]) -> None:
    """Append structured error lines to `errors.log`. Never raises."""
    if not errors:
        return
    try:
        path = errors_log_path()
        with path.open("a", encoding="utf-8") as fh:
            for err in errors:
                fh.write(
                    json.dumps(
                        {
                            "ts_ms": int(datetime.now(tz=UTC).timestamp() * 1000),
                            "err": err,
                        }
                    )
                    + "\n"
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
         upsert to Dhara via `rebuilder.upsert_all`.
      3. On failure, append to `recent_errors` (bounded at 20) and write
         a structured line to `errors.log`.
      4. Update all six meta keys including the explicit `entities_count`.
      5. Truncate `recent_errors` to 20 entries.
      6. Release lock by deleting the holder key (always, in `finally`).
    """
    dhara = store._dhara  # type: ignore[attr-defined]

    # --- Lock acquisition (round-3 addition) ------------------------------
    holder_raw = await dhara.get(REBUILD_LOCK_HOLDER_KEY)
    acquired_raw = await dhara.get(REBUILD_LOCK_ACQUIRED_KEY)
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
            holder_raw, age_ms, REBUILD_LOCK_TTL_SECONDS * 1000,
        )

    # Write (or overwrite) our own holder entry.
    await dhara.put(REBUILD_LOCK_HOLDER_KEY, new_holder)
    await dhara.put(REBUILD_LOCK_ACQUIRED_KEY, str(now_ms_for_lock))

    try:
        records: list[PlanRecord] = (
            discover_records(repo_root) if repo_root is not None else []
        )

        success, error_count, errors = await rebuilder.upsert_all(records, store)

        now_ms = int(datetime.now(tz=UTC).timestamp() * 1000)

        cycles_raw = await dhara.get(CYCLES_TOTAL_KEY)
        cycles_total = int(cycles_raw) + 1 if cycles_raw else 1
        await dhara.put(CYCLES_TOTAL_KEY, str(cycles_total))

        await dhara.put(ENTITIES_COUNT_KEY, str(success))

        if error_count == 0:
            success_raw = await dhara.get(SUCCESS_CYCLES_KEY)
            successful = int(success_raw) + 1 if success_raw else 1
            await dhara.put(SUCCESS_CYCLES_KEY, str(successful))
            await dhara.put(LAST_SUCCESS_MS_KEY, str(now_ms))
            last_success_ms: int | None = now_ms
        else:
            last_success_ms = None

        errors_total = error_count
        if error_count > 0:
            errors_raw = await dhara.get(ERRORS_TOTAL_KEY)
            errors_total = (int(errors_raw) if errors_raw else 0) + error_count
            await dhara.put(ERRORS_TOTAL_KEY, str(errors_total))

            recent_raw = await dhara.get(RECENT_ERRORS_KEY)
            recent: list[dict[str, Any]] = json.loads(recent_raw) if recent_raw else []
            for err in errors:
                recent.append({"ts_ms": now_ms, "op": "upsert", "err": "see ctx", "ctx": err})
            recent = recent[-RECENT_ERRORS_MAX:]
            await dhara.put(
                RECENT_ERRORS_KEY, json.dumps(recent),
                ttl=RECENT_ERRORS_TTL_DAYS * 86400,
            )

            _write_error_log(errors)

        await dhara.put(LAST_REBUILD_MS_KEY, str(now_ms))

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
            successful_cycles_total=int(await dhara.get(SUCCESS_CYCLES_KEY) or "0"),
            errors_total=errors_total,
            last_rebuild_ms=now_ms,
            last_success_ms=last_success_ms,
        )
    finally:
        # Always release the lock, even on partial failure.
        try:
            await dhara.delete(REBUILD_LOCK_HOLDER_KEY)
        except Exception as release_exc:  # noqa: BLE001
            _logger.warning("could not release rebuild lock: %s", release_exc)
