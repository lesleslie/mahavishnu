"""Messaging module for Mahavishnu - inter-repository communication."""

__all__ = [
    "MessageType",
    "MessagePriority",
    "RepositoryMessage",
    "RepositoryMessenger",
    "RepositoryMessengerManager",
]

# Mapping of export name -> (relative_module, attribute_name)
_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    "MessagePriority": (".repository_messenger", "MessagePriority"),
    "MessageType": (".repository_messenger", "MessageType"),
    "RepositoryMessage": (".repository_messenger", "RepositoryMessage"),
    "RepositoryMessenger": (".repository_messenger", "RepositoryMessenger"),
    "RepositoryMessengerManager": (".repository_messenger", "RepositoryMessengerManager"),
}


def __getattr__(name: str):
    """Lazy import to avoid heavy initialization on package import."""
    if entry := _LAZY_IMPORTS.get(name):
        from importlib import import_module

        module = import_module(entry[0], __name__)
        return getattr(module, entry[1])
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
