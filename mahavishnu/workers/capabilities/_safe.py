"""Safe-redaction helpers for capability reports, exceptions, and logs."""
from __future__ import annotations
import re
from typing import Any
_SECRET_PATTERN = re.compile(r"(?i)(?:sk-[a-z0-9]{8,}|ghp_[a-z0-9]{8,}|xox[ab]-[a-z0-9-]{8,}|ya29\.[a-z0-9_-]{8,}|bearer\s+[a-z0-9._-]{8,})")
def safe_error_for_user(message: str | None) -> str:
    return _SECRET_PATTERN.sub("***", message) if message else ""
def safe_dict(details: dict[str, Any] | None) -> dict[str, Any]:
    return {k: safe_error_for_user(v) if isinstance(v, str) else v for k,v in (details or {}).items()}
