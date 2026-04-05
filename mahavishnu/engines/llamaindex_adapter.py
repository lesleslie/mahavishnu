"""Compatibility wrapper for the LlamaIndex adapter implementation."""

from . import llamaindex_adapter_impl as _impl
from .llamaindex_adapter_impl import *  # noqa: F401,F403

globals().update({name: value for name, value in vars(_impl).items() if not name.startswith("_")})
__all__ = getattr(_impl, "__all__", [name for name in globals() if not name.startswith("_")])
