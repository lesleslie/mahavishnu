"""Models package for Mahavishnu.

Contains Pydantic data models for:
- Pattern detection and analysis
- Task data structures (future)
- Repository metadata (future)
"""

__all__ = [
    "BlockerPattern",
    "CompletionSequencePattern",
    "DetectedPattern",
    "PatternAnalysisResult",
    "PatternBase",
    "PatternFrequency",
    "PatternMatch",
    "PatternSeverity",
    "PatternType",
    "TaskDurationPattern",
]

# Mapping of export name -> (relative_module, attribute_name)
_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    "BlockerPattern": (".pattern", "BlockerPattern"),
    "CompletionSequencePattern": (".pattern", "CompletionSequencePattern"),
    "DetectedPattern": (".pattern", "DetectedPattern"),
    "PatternAnalysisResult": (".pattern", "PatternAnalysisResult"),
    "PatternBase": (".pattern", "PatternBase"),
    "PatternFrequency": (".pattern", "PatternFrequency"),
    "PatternMatch": (".pattern", "PatternMatch"),
    "PatternSeverity": (".pattern", "PatternSeverity"),
    "PatternType": (".pattern", "PatternType"),
    "TaskDurationPattern": (".pattern", "TaskDurationPattern"),
}


def __getattr__(name: str):
    """Lazy import to avoid heavy initialization on package import."""
    if entry := _LAZY_IMPORTS.get(name):
        from importlib import import_module

        module = import_module(entry[0], __name__)
        return getattr(module, entry[1])
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
