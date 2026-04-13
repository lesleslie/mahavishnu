"""Compatibility wrapper for the LlamaIndex adapter implementation.

.. deprecated:: 0.4.0
    This module is a re-export wrapper. Import directly from
    ``mahavishnu.engines.llamaindex_adapter_impl`` instead.

    To migrate, change imports from::

        from mahavishnu.engines.llamaindex_adapter import LlamaIndexAdapter

    To::

        from mahavishnu.engines.llamaindex_adapter_impl import LlamaIndexAdapter

This module will be removed in a future release.
"""

import warnings

warnings.warn(
    "mahavishnu.engines.llamaindex_adapter is a compatibility wrapper. "
    "Import from mahavishnu.engines.llamaindex_adapter_impl instead. "
    "This wrapper will be removed in a future release.",
    DeprecationWarning,
    stacklevel=2,
)

from . import llamaindex_adapter_impl as _impl
from .llamaindex_adapter_impl import *  # noqa: F401,F403,E402

globals().update({name: value for name, value in vars(_impl).items() if not name.startswith("_")})
__all__ = getattr(_impl, "__all__", [name for name in globals() if not name.startswith("_")])
