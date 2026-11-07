"""Subprocess smoke test for the eval MCP tools (REQ-EVAL-005).

The in-process e2e test (``test_eval_tools_e2e.py``) proves the tools
work when they are registered directly. This test proves they work
through the **real server**: it spawns ``mahavishnu mcp start`` as a
subprocess, waits for the port to accept connections, and calls each
eval tool over the MCP protocol.

Two things make that worth the cost:

1. The registration path a real server uses is the profile machinery
   (``_apply_tool_profile``), not a direct ``register_eval_tools``
   call. The in-process test cannot catch a group that is registered in
   the profile table but never dispatched.
2. The tool schemas are built by FastMCP at registration time against
   the real server's type resolution. A schema that only works in a
   test harness fails here.

The test is slow (a real server start) and needs a free port, so it is
marked ``slow`` and skipped by ``-m "not slow"``. It also picks an
ephemeral port rather than the default 8680 so it never collides with
a live Mahavishnu on the operator's machine.

The server is started in a **self-contained runtime directory**, not in
the repository: ``settings/repos.yaml`` and ``settings/ecosystem.yaml``
are gitignored operator files, so a fresh checkout (or a git worktree)
has no ecosystem manifest and the server refuses to boot. The test
writes a minimal manifest into a temporary directory, runs the server
there with ``PYTHONPATH`` pointing at the code under test, and therefore
depends on nothing outside the repository it is testing.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from pathlib import Path
import socket
import sys
import time

from fastmcp import Client
import pytest

# req: REQ-EVAL-005

#: How long to wait for the server to accept connections.
WARMUP_SECONDS = 120.0

#: The eval tools the smoke test calls.
EVAL_TOOL_NAMES = ("eval_register_dataset", "eval_run_suite", "eval_get_run")

#: A minimal ecosystem manifest. The server refuses to boot without one;
#: the eval subsystem needs no repositories.
_MINIMAL_ECOSYSTEM_YAML = """\
version: '1.0'
maintainer: eval-smoke
description: Minimal ecosystem manifest for the eval smoke test.

repos: []
"""


def _repo_root() -> Path:
    """Return the root of the checkout the code under test lives in.

    ``mahavishnu/__init__.py`` -> parents[0] is the package directory,
    parents[1] is the repository root.
    """
    import mahavishnu

    return Path(mahavishnu.__file__).resolve().parents[1]


def _free_port() -> int:
    """Return a port that is free right now.

    The socket is bound to find the port and released immediately
    before the subprocess starts. There is an unavoidable race with
    other processes, but it is far smaller than pinning 8680 and
    colliding with a live server.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


async def _wait_for_port(
    port: int,
    process: asyncio.subprocess.Process,
    timeout: float,
) -> bool:
    """Wait until the port accepts connections, or the process dies.

    Args:
        port: The port to probe.
        process: The server subprocess; if it exits, stop waiting.
        timeout: How long to wait, in seconds.

    Returns:
        True if the port became reachable.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.returncode is not None:
            return False
        with contextlib.suppress(OSError):
            with socket.create_connection(("127.0.0.1", port), timeout=1.0):
                return True
        await asyncio.sleep(0.5)
    return False


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.timeout(180)
@pytest.mark.req(["REQ-EVAL-005"])
async def test_eval_tools_are_callable_through_a_real_server(
    tmp_path: Path,
) -> None:
    """A real server registers the eval tools and answers calls."""
    port = _free_port()
    dataset = tmp_path / "cases.jsonl"
    dataset.write_text(
        '{"id": "c1", "input": "ping", "expected": "ping"}\n',
        encoding="utf-8",
    )

    runtime = tmp_path / "runtime"
    (runtime / "settings").mkdir(parents=True, exist_ok=True)
    (runtime / "settings" / "ecosystem.yaml").write_text(
        _MINIMAL_ECOSYSTEM_YAML, encoding="utf-8"
    )

    env = dict(os.environ)
    env.update(
        {
            "MAHAVISHNU_EVAL__ENABLED": "true",
            "MAHAVISHNU_EVAL__DB_PATH": str(tmp_path / "runs.sqlite"),
            "MAHAVISHNU_EVAL__DATASET_ROOT": str(tmp_path),
            "MAHAVISHNU_TOOL_PROFILE": "standard",
            # The OTLP exporters block on a collector that is not running
            # in a test environment: each export attempt stalls the
            # server's startup for 20-60s. Neither trace nor metric
            # export is what this test is about.
            "MAHAVISHNU_OBSERVABILITY__TRACING_ENABLED": "false",
            "MAHAVISHNU_OBSERVABILITY__METRICS_ENABLED": "false",
            "PYTHONPATH": os.pathsep.join(
                filter(None, [str(_repo_root()), env.get("PYTHONPATH", "")])
            ),
        }
    )

    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "mahavishnu",
        "mcp",
        "start",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        cwd=str(runtime),
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        reachable = await _wait_for_port(port, process, WARMUP_SECONDS)
        if not reachable:
            # The server is still alive: stop it so its output can be
            # read, then report what it printed. The diagnostics are
            # what makes the failure actionable instead of mysterious.
            #
            # This **fails** rather than skips. A skip here would be
            # invisible in CI, and a registration or schema regression
            # that stops the server booting is exactly the failure
            # this test exists to catch -- the repo's wiring decision
            # (docs/decisions/mcp-backend-wiring-discipline.md) asks
            # for a real-server smoke test that asserts non-empty
            # responses, and a skip asserts nothing.
            with contextlib.suppress(ProcessLookupError):
                process.terminate()
            output = ""
            if process.stdout is not None:
                with contextlib.suppress(asyncio.TimeoutError):
                    output = (await asyncio.wait_for(process.stdout.read(), 10))[-4000:]
            pytest.fail(
                "the Mahavishnu MCP server did not come up within "
                f"{WARMUP_SECONDS:.0f}s on port {port}; "
                f"exit={process.returncode} output={output[-1500:]!r}"
            )

        async with Client(f"http://127.0.0.1:{port}/mcp") as client:
            tools = await client.list_tools()
            tool_names = {tool.name for tool in tools}
            missing = set(EVAL_TOOL_NAMES) - tool_names
            assert not missing, f"the server did not register {sorted(missing)}"

            registered = await client.call_tool(
                "eval_register_dataset", {"path": str(dataset)}
            )
            assert registered.structured_content is not None
            assert registered.structured_content["cases"] == 1

            ran = await client.call_tool(
                "eval_run_suite",
                {"suite": str(dataset), "model": "mahavishnu.mock"},
            )
            assert ran.structured_content is not None
            assert ran.structured_content["status"] == "completed"

            fetched = await client.call_tool(
                "eval_get_run", {"run_id": ran.structured_content["run_id"]}
            )
            assert fetched.structured_content is not None
            assert len(fetched.structured_content["case_results"]) == 1
    finally:
        with contextlib.suppress(ProcessLookupError):
            process.terminate()
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(process.wait(), timeout=15)
        if process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                process.kill()
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(process.wait(), timeout=10)
