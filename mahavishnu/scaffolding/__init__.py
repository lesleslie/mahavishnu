"""Pattern learning and scaffolding for Fastblocks/Oneiric projects."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mahavishnu.scaffolding.models import Pattern

    __all__ = [
        "Pattern",
        # Future exports — added as modules are implemented:
        # "PatternLibrary",
        # "ScaffoldingEngine",
        # "PatternExtractor",
    ]
else:
    __all__: list[str] = []
