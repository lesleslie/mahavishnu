"""The OTLP transport contract -- the regression guard for the fork crash.

mahavishnu forks constantly: git for the worktree diff, git for the
plan-index rebuild, tmux for the worker pane. On macOS CPython 3.14 those
forks are REAL forks (``os.POSIX_SPAWN_CLOSEFROM`` does not exist there, so
the ``posix_spawn`` path is unreachable with the default ``close_fds=True``),
and a fork taken while grpcio's background threads are live leaves the child
holding a libdispatch ``dispatch_once`` that the vanished thread owned. The
child then dies with SIGILL -- "BUG IN CLIENT OF LIBDISPATCH: trying to lock
recursively" -- and the fork's caller sees
``subprocess.CalledProcessError ... died with <Signals.SIGILL: 4>``.

The fix is not to avoid the fork (macOS gives us no fork-free spawn with
equivalent semantics). It is to keep grpcio OUT of a process that forks.

So the property to pin is narrow and checkable: **importing this module must
not import grpc.** Everything else here is the transport selection that
follows from it.
"""

from __future__ import annotations

import subprocess
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest

import mahavishnu.core.observability as obs


def _import_in_subprocess(stmt: str) -> str:
    """Run ``stmt`` in a clean interpreter and return its stdout.

    A subprocess is the only honest way to ask "does importing this pull in
    grpc?" -- in-process, the answer depends on what the rest of the test
    session already imported.
    """
    result = subprocess.run(
        [sys.executable, "-c", stmt],
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    )
    return result.stdout.strip()


def test_importing_observability_does_not_import_grpc() -> None:
    """The regression guard for the whole bug.

    Before the fix, ``core/observability.py`` imported the OTLP **gRPC**
    exporters at module scope, so ``cygrpc`` was mapped into the MCP server
    process -- and every child it forked could die with SIGILL.
    """
    out = _import_in_subprocess(
        "import sys; import mahavishnu.core.observability; print('grpc' in sys.modules)"
    )
    assert out == "False", (
        "importing core.observability loaded grpcio; a process that forks "
        "must not have grpcio's threads (see the decision doc)"
    )


def test_the_full_server_import_graph_does_not_import_grpc() -> None:
    """The same property for the MCP server's real import graph.

    ``mahavishnu.mcp.server_core`` pulls in far more than the observability
    module does, so it is the graph that matters in production.
    """
    out = _import_in_subprocess(
        "import sys; import mahavishnu.mcp.server_core; print('grpc' in sys.modules)"
    )
    assert out == "False"


def test_the_default_transport_is_http(monkeypatch: pytest.MonkeyPatch) -> None:
    """HTTP is the default, and it is the default for a reason."""
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_PROTOCOL", raising=False)
    assert obs._resolve_otlp_protocol() == "http/protobuf"


def test_the_transport_env_var_selects_grpc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An operator can still ask for gRPC.

    The escape hatch exists -- but it re-arms the fork hazard, which is why
    it is not the default.
    """
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_PROTOCOL", "grpc")
    assert obs._resolve_otlp_protocol() == "grpc"


def test_the_http_endpoint_gets_its_signal_path() -> None:
    """A base URL gets the signal path; one that has it is left alone.

    The HTTP exporter treats an explicit endpoint as the COMPLETE url, so
    ``http://127.0.0.1:4318`` posted to as-is would 404.
    """
    assert (
        obs._http_signal_endpoint("http://127.0.0.1:4318", obs._TRACES_PATH)
        == "http://127.0.0.1:4318/v1/traces"
    )
    assert (
        obs._http_signal_endpoint("http://127.0.0.1:4318/", obs._TRACES_PATH)
        == "http://127.0.0.1:4318/v1/traces"
    )
    assert (
        obs._http_signal_endpoint("http://127.0.0.1:4318/v1/traces", obs._TRACES_PATH)
        == "http://127.0.0.1:4318/v1/traces"
    )
    assert (
        obs._http_signal_endpoint("http://127.0.0.1:4318", obs._METRICS_PATH)
        == "http://127.0.0.1:4318/v1/metrics"
    )


def test_the_http_span_exporter_uses_the_http_transport() -> None:
    """The default build path never touches the gRPC exporter module."""
    exporter = obs._build_span_exporter("http://127.0.0.1:4318", "http/protobuf")
    assert type(exporter).__module__.startswith(
        "opentelemetry.exporter.otlp.proto.http"
    )


def test_the_grpc_span_exporter_keeps_the_endpoint_verbatim() -> None:
    """A gRPC endpoint is a host:port, not a url -- no path is appended."""
    exporter = obs._build_span_exporter("http://127.0.0.1:4317", "grpc")
    assert type(exporter).__module__.startswith(
        "opentelemetry.exporter.otlp.proto.grpc"
    )
    endpoint = getattr(exporter, "_endpoint", None)
    if endpoint is not None:
        assert not str(endpoint).endswith(obs._TRACES_PATH)


def test_no_grpc_channel_is_created_by_the_default_configuration() -> None:
    """The default configuration must not create a grpc channel.

    Creating a channel is what starts the c-ares resolver thread that
    arms the dispatch_once token -- importing the module is only half the
    hazard.
    """
    out = _import_in_subprocess(
        "import sys; import mahavishnu.core.observability as o; "
        "e = o._build_span_exporter('http://127.0.0.1:4318', o._resolve_otlp_protocol()); "
        "print(type(e).__module__)"
    )
    assert out.startswith("opentelemetry.exporter.otlp.proto.http")
