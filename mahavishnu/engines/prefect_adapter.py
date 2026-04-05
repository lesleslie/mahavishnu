"""Compatibility wrapper for the Prefect adapter implementation."""

from . import prefect_adapter_impl as _impl
from .prefect_adapter_impl import *  # noqa: F401,F403

globals().update({name: value for name, value in vars(_impl).items() if not name.startswith("_")})
__all__ = getattr(_impl, "__all__", [name for name in globals() if not name.startswith("_")])
