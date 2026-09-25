"""Identity test for WorkerStatus canonicalization.

Plan v3 Phase 5b. Per Agent 3's audit finding, ``WorkerStatus``
already had a single canonical definition at ``mahavishnu/core/status.py:97``
and ``mahavishnu/workers/base.py`` was already doing
``from mahavishnu.core.status import WorkerStatus``.

This file locks the identity with a runtime check so a future
regression (e.g., someone adding a duplicate ``class WorkerStatus``
definition in ``workers/base.py``) gets caught at test time.

Phase 5b also closes the two remaining stragglers that imported
``WorkerStatus`` through ``mahavishnu.workers.base``:
- mahavishnu/core/execute_fn_factory.py:150 -- migrated to
  ``from mahavishnu.core.status import WorkerStatus``
- mahavishnu/workers/__init__.py -- the re-export of WorkerStatus
  via workers.base import is INTENTIONAL (it's part of the package's
  public surface); we KEEP this import since the canonical location
  remains core.status.
"""

from __future__ import annotations

from types import MappingProxyType

import pytest


class TestWorkerStatusIdentity:
    """The two import paths must resolve to the same enum class object."""

    def test_workers_base_and_core_status_are_identical(self) -> None:
        from mahavishnu.workers.base import WorkerStatus as A
        from mahavishnu.core.status import WorkerStatus as B

        # ``is`` identity (not just equality) — same class object.
        assert A is B
        # Members are enumerable on the shared enum.
        assert set(A.__members__.keys()) == set(B.__members__.keys())

    def test_workers_base_does_not_define_its_own_worker_status(self) -> None:
        """``workers/base.py`` must use the re-export, never define its own.

        A regression here would create two ``WorkerStatus`` enums (only
        one registered with the prompt-routing and quota systems)
        and break equality across modules.
        """
        import inspect

        from mahavishnu import workers

        source = inspect.getsource(workers.base)
        # Re-import pattern is allowed: ``from mahavishnu.core.status
        # import WorkerStatus`` directly, with no local override.
        # Reject any of: explicit ``class WorkerStatus``, ``WorkerStatus =``,
        # or stub ``WorkerStatus =``.
        forbidden_patterns = (
            "class WorkerStatus",  # class WorkerStatus(...)
            "WorkerStatus = ",       # alias = CoreStatus.WorkerStatus
            "WorkerStatus = ",       # stub assignment
        )
        for pattern in forbidden_patterns:
            assert pattern not in source, (
                f"workers/base.py must not redefine WorkerStatus; "
                f"found forbidden pattern {pattern!r}. Use "
                f"``from mahavishnu.core.status import WorkerStatus``."
            )

    def test_no_stragglers_import_workerstatus_through_workers_base(self) -> None:
        """No production code path imports WorkerStatus through workers.base.

        Per Plan v3 Phase 5b, the import path canonicalization is
        one-way: ``from mahavishnu.core.status import WorkerStatus``.
        ``from mahavishnu.workers.base import WorkerStatus`` is the legacy
        path and is being deprecated. ``workers/__init__.py`` is allowed
        to re-export it (it IS the package's public surface); no other
        module is.
        """
        import subprocess
        import re

        result = subprocess.run(
            ["git", "grep", "-nE", "from mahavishnu.workers.base import.+WorkerStatus"],
            capture_output=True,
            text=True,
            cwd="/Users/les/Projects/mahavishnu",
            check=False,
        )
        # ``subprocess.run`` with cwd above may fail with unicode errors on
        # git's stderr; only use stdout.
        matches = [
            line
            for line in (result.stdout or "").splitlines()
            if line.strip()
            and not line.startswith(("a2a.py", "apple_container.py"))  # excluded dead files
        ]

        # Phase 5b allows ONLY mahavishnu/workers/__init__.py as a re-export;
        # any other importer is a regression.
        offenders = [
            line for line in matches
            if not line.startswith("mahavishnu/workers/__init__.py:")
        ]
        assert not offenders, (
            f"WorkerStatus must be imported from mahavishnu.core.status, "
            f"not through mahavishnu.workers.base. Offending importers: "
            f"{offenders}"
        )

        # Sanity check: __init__.py retains the re-export per the package's
        # public surface decision.
        init_re_exports = [
            line for line in matches if line.startswith("mahavishnu/workers/__init__.py:")
        ]
        assert init_re_exports, (
            "workers/__init__.py must continue to re-export WorkerStatus"
        )

    def test_worker_status_is_strenum(self) -> None:
        """The canonical WorkerStatus is a StrEnum — used by log slicing
        and JSON serialization in the routing layer. A regression to a
        plain Enum breaks the ``WorkerStatus.value`` pattern used in
        dispatcher logs.
        """
        from enum import StrEnum

        from mahavishnu.core.status import WorkerStatus

        assert isinstance(WorkerStatus, type)
        assert issubclass(WorkerStatus, StrEnum)
        # Every member's ``.value`` must be a non-empty string.
        for member in WorkerStatus:
            assert isinstance(member.value, str)
            assert member.value  # non-empty
