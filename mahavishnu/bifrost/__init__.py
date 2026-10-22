"""Bifrost LLM gateway control surface.

Consolidates the former ``scripts/bifrost*`` tooling into one wired CLI
(``mahavishnu bifrost ...``). See
``docs/plans/2026-10-21-bifrost-cli-consolidation.md``.
"""

from __future__ import annotations

from .models import HARNESSES, HarnessDescriptor, resolve_harness

__all__ = ["HARNESSES", "HarnessDescriptor", "resolve_harness"]
