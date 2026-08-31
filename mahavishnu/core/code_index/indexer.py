"""Orchestrates code graph indexing: detect changes, parse, upsert to Session-Buddy."""

from __future__ import annotations

from datetime import UTC, datetime
import json
import logging
from pathlib import Path
import subprocess

from mahavishnu.core.code_index.lock import RepoIndexLock
from mahavishnu.core.code_index.models import IndexWorkItem
from mahavishnu.core.code_index.parser import filter_changed_files, parse_file

logger = logging.getLogger(__name__)

QUEUE_DIR = Path.home() / ".claude" / "data" / "mahavishnu-index-queue"


def get_last_indexed_commit(repo_path: str) -> str | None:
    """Get the last commit hash that was indexed for a repo."""
    state_file = Path(repo_path) / ".git" / "mahavishnu-last-index"
    if not state_file.exists():
        return None
    return state_file.read_text().strip()


def set_last_indexed_commit(repo_path: str, commit_hash: str) -> None:
    """Persist the last indexed commit hash."""
    state_file = Path(repo_path) / ".git" / "mahavishnu-last-index"
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(commit_hash)


def get_current_commit(repo_path: str) -> str:
    """Get the current HEAD commit hash."""
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_path,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip()


def index_repo(
    repo_path: str,
    trigger: str = "manual",
    full: bool = False,
) -> IndexWorkItem:
    """Index a single repository.

    Detects changed files, parses them, and upserts to Session-Buddy.
    Falls back to filesystem queue if Session-Buddy MCP is unavailable.
    """
    lock = RepoIndexLock(repo_path)
    if not lock.acquire():
        logger.info("Indexing already in progress for %s, skipping", repo_path)
        return IndexWorkItem(
            repo_path=repo_path,
            trigger=trigger,  # ty: ignore[invalid-argument-type]
            files_changed=[],
            status="failed",
        )

    try:
        work_item = IndexWorkItem(
            repo_path=repo_path,
            trigger=trigger,  # ty: ignore[invalid-argument-type]
            files_changed=[],
            status="parsing",
            started_at=datetime.now(UTC),
        )

        last_commit = None if full else get_last_indexed_commit(repo_path)

        current_commit = get_current_commit(repo_path)
        changed_files = filter_changed_files(repo_path, last_commit)

        work_item.files_changed = changed_files

        if not changed_files:
            work_item.status = "complete"
            work_item.completed_at = datetime.now(UTC)
            logger.info("No changes detected for %s", repo_path)
            return work_item

        all_nodes = []
        all_edges = []
        parse_failures = 0

        for file_path in changed_files:
            try:
                result = parse_file(file_path, repo_path, current_commit)
                if result is not None:
                    nodes, edges = result
                    all_nodes.extend(nodes)
                    all_edges.extend(edges)
            except (OSError, SyntaxError, ValueError, RuntimeError) as e:
                parse_failures += 1
                logger.warning("Failed to parse %s: %s", file_path, e)

        work_item.parse_failures = parse_failures

        if (
            parse_failures > 0
            and len(changed_files) > 0
            and parse_failures / len(changed_files) > 0.25
        ):
            logger.warning(
                "High parse failure rate for %s: %d/%d files failed",
                repo_path,
                parse_failures,
                len(changed_files),
            )

        work_item.status = "upserting"
        success = _upsert_to_session_buddy(repo_path, all_nodes, all_edges)

        if not success:
            _queue_locally(repo_path, current_commit, all_nodes, all_edges)

        work_item.status = "complete"
        work_item.completed_at = datetime.now(UTC)

        set_last_indexed_commit(repo_path, current_commit)

        logger.info(
            "Indexed %s: %d files, %d nodes, %d edges, %d failures",
            repo_path,
            len(changed_files),
            len(all_nodes),
            len(all_edges),
            parse_failures,
        )

        return work_item

    finally:
        lock.release()


def _upsert_to_session_buddy(
    repo_path: str,
    nodes: list,
    edges: list,
) -> bool:
    """Try to upsert to Session-Buddy via MCP. Returns True on success."""
    try:
        import httpx2 as httpx

        session_url = "http://localhost:8678/mcp"
        streamable_headers = {"Accept": "application/json, text/event-stream"}
        # FastMCP streamable-http requires an ``initialize`` handshake
        # before ``tools/call``; the server returns a ``mcp-session-id``
        # header on that first response which must be sent on every
        # subsequent call. Without this, the server returns 400 with
        # ``Missing session ID``.
        init_resp = httpx.post(
            session_url,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "mahavishnu", "version": "0"},
                },
            },
            headers=streamable_headers,
            timeout=30.0,
        )
        session_id = init_resp.headers.get("mcp-session-id", "")
        if not session_id:
            return False

        call_headers = {**streamable_headers, "mcp-session-id": session_id}
        resp = httpx.post(
            session_url,
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "store_code_graph_from_mahavishnu",
                    "arguments": {
                        "repo_path": repo_path,
                        "commit_hash": get_current_commit(repo_path),
                        "indexed_at": datetime.now(UTC).isoformat(),
                        "nodes_count": len(nodes),
                        "graph_data": {
                            "nodes": [n.model_dump(mode="json") for n in nodes],
                            "edges": [e.model_dump(mode="json") for e in edges],
                        },
                    },
                },
            },
            headers=call_headers,
            timeout=30.0,
        )
        return resp.status_code == 200
    except (httpx.HTTPError, OSError, TimeoutError) as e:
        logger.warning("Session-Buddy MCP unavailable: %s", e)
        return False


def _queue_locally(
    repo_path: str,
    commit_hash: str,
    nodes: list,
    edges: list,
) -> None:
    """Fallback: write parsed data to local filesystem queue."""
    QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    repo_name = Path(repo_path).name
    queue_file = QUEUE_DIR / f"{repo_name}_{timestamp}.json"
    queue_file.write_text(
        json.dumps(
            {
                "repo_path": repo_path,
                "commit_hash": commit_hash,
                "nodes": [n.model_dump(mode="json") for n in nodes],
                "edges": [e.model_dump(mode="json") for e in edges],
            },
            default=str,
        )
    )
    logger.info("Queued %d nodes to %s", len(nodes), queue_file)
