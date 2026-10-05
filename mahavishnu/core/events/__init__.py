"""Typed event envelope and event-contract utilities.

Submodule re-exports whose underlying modules eagerly import `oneiric`
(directly, or transitively via `mahavishnu.core.events.canonical`) are
deferred via PEP 562 module-level `__getattr__`. `oneiric` is resolved
as a sibling peer directory in the user's workspace, not as an
installed wheel — when the `mahavishnu` CLI is invoked from a non-
mahavishnu CWD (e.g. via the post-commit git hook installed by
`mahavishnu index install-hooks` in crackerjack, session-buddy, etc.),
the peer-directory resolution fails and an eager `from .<submodule>
import ...` here crashes the CLI at startup before any subcommand can
run. See `tests/unit/core/events/test_package_init_lazy_canonical.py`
for the regression test that pins this contract.
"""

from __future__ import annotations

import importlib

from mahavishnu.core.errors import MahavishnuError as MahavishnuError
from mahavishnu.core.events.compatibility import (
    CompatibilityLevel as CompatibilityLevel,
)
from mahavishnu.core.events.compatibility import (
    CompatibilityPolicy as CompatibilityPolicy,
)
from mahavishnu.core.events.contract import (
    EventHandler as EventHandler,
)
from mahavishnu.core.events.contract import (
    EventPublisherProtocol as EventPublisherProtocol,
)
from mahavishnu.core.events.contract import (
    EventSubscription as EventSubscription,
)
from mahavishnu.core.events.contract import (
    InMemoryEventTransport as InMemoryEventTransport,
)
from mahavishnu.core.events.contract import (
    create_event_envelope as create_event_envelope,
)
from mahavishnu.core.events.envelope import EventEnvelope as EventEnvelope
from mahavishnu.core.events.envelope import EventVersion as EventVersion
from mahavishnu.core.events.migration import (
    migrate_legacy_event_bus_event as migrate_legacy_event_bus_event,
)
from mahavishnu.core.events.migration import (
    migrate_legacy_task_event as migrate_legacy_task_event,
)
from mahavishnu.core.events.migration import (
    migrate_legacy_webhook_event as migrate_legacy_webhook_event,
)
from mahavishnu.core.events.publisher import (
    get_publisher as get_publisher,
)
from mahavishnu.core.events.publisher import (
    safe_publish as safe_publish,
)
from mahavishnu.core.events.publisher import (
    set_publisher as set_publisher,
)
from mahavishnu.core.events.schema_registry import (
    EventSchema as EventSchema,
)
from mahavishnu.core.events.schema_registry import (
    EventSchemaRegistry as EventSchemaRegistry,
)


# Names whose definition lives in a submodule that eagerly imports
# `oneiric` (directly, or transitively via `mahavishnu.core.events.canonical`).
# Accessing any of them triggers a one-time `import <submodule>` on
# first use, which transitively loads `oneiric`. Keep this mapping
# in lockstep with the actual re-exports — the regression test
# `test_package_init_lazy_canonical.py` enforces the contract that
# `envelope`/`schema_registry`/`contract`/etc. imports do NOT load
# any of these names.
_LAZY_HEAVY_REEXPORTS: dict[str, str] = {
    # canonical: itself imports oneiric at module load.
    "OPTIONAL_EVENT_HEADERS": "canonical",
    "REQUIRED_EVENT_HEADERS": "canonical",
    "RESERVED_EVENT_HEADERS": "canonical",
    "OneiricEventPublisherProtocol": "canonical",
    "create_oneiric_envelope": "canonical",
    "decode_oneiric_envelope": "canonical",
    "encode_oneiric_envelope": "canonical",
    "to_mahavishnu_envelope": "canonical",
    "to_oneiric_envelope": "canonical",
    # transport: imports canonical at module load, which imports oneiric.
    "EventBusConsumer": "transport",
    "RedisEventTransport": "transport",
    "WebSocketEventHandler": "transport",
}


def __getattr__(name: str):
    # PEP 562 module-level __getattr__: defer loading any submodule
    # that pulls in `oneiric` (directly or transitively) until a
    # name that lives there is actually requested. This keeps
    # `mahavishnu index ...` and other subcommands runnable from any
    # CWD — including the background `mahavishnu index repo
    # --trigger git-event` process started by the post-commit hook in
    # every Bodai repo where `mahavishnu index install-hooks` has
    # been run.
    module_name = _LAZY_HEAVY_REEXPORTS.get(name)
    if module_name is not None:
        module = importlib.import_module(f".{module_name}", __name__)
        try:
            return getattr(module, name)
        except AttributeError:
            pass
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    # Surface the lazy names in `dir(mahavishnu.core.events)` so
    # tab-completion and IDE introspection see them.
    return sorted(set(globals().keys()) | _LAZY_HEAVY_REEXPORTS.keys())
