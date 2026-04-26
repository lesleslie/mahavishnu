"""Pattern learning and scaffolding for Fastblocks/Oneiric projects."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mahavishnu.scaffolding.models import Pattern
    from mahavishnu.scaffolding.library import PatternLibrary

    __all__ = [
        "Pattern",
        "PatternLibrary",
        # Future exports — added as modules are implemented:
        # "ScaffoldingEngine",
        # "PatternExtractor",
    ]
else:
    __all__: list[str] = []
