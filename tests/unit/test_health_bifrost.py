"""Phase 7 (REQ-BIFROST-017) — oneiric BifrostLLMSettings projection tests.

These tests pin the centralized exclusion of sensitive fields from
``/health.bifrost.config`` and ``mahavishnu config validate``. The
Pydantic-level override lives in
``oneiric.adapters.llm.bifrost.BifrostLLMSettings.model_dump`` (see
``_SENSITIVE_FIELDS = frozenset({"auth_env"})``); the mahavishnu side
calls ``get_router()._settings.model_dump()`` and relies on the
override to redact the env-var name.

Pre-Phase-7 the three production call sites spelled out
``model_dump(exclude={"auth_env"})`` explicitly. Phase 7 collapses
that to a single Pydantic-level enforcement.
"""

from __future__ import annotations

from typing import Any


def test_auth_env_excluded_from_model_dump() -> None:
    """``auth_env`` is NOT in the public ``model_dump()`` output.

    REQ-BIFROST-017: the env-var name is sensitive (it names the
    bearer-token env var the operator configured). The
    oneiric-level override in ``BifrostLLMSettings.model_dump``
    excludes every field in ``_SENSITIVE_FIELDS`` by default. The
    three mahavishnu call sites (``mahavishnu/health.py``,
    ``mahavishnu/core/health.py``, ``mahavishnu/cli/config_validator.py``)
    all call ``model_dump()`` without an explicit ``exclude=`` —
    they depend on this centralized Pydantic-level redaction.
    """
    from oneiric.adapters.llm.bifrost import get_router

    dumped: dict[str, Any] = get_router()._settings.model_dump()
    assert "auth_env" not in dumped, (
        "BifrostLLMSettings.model_dump() must exclude the auth_env "
        "field by default (per _SENSITIVE_FIELDS in oneiric). The "
        "mahavishnu /health.bifrost.config and 'mahavishnu config "
        "validate' surfaces depend on this centralized redaction."
    )
    # The other BifrostLLMSettings fields are public and should
    # be present — assert a representative subset.
    for public_field in ("enabled", "base_url", "anthropic_base_url"):
        assert public_field in dumped, (
            f"public field {public_field!r} missing from model_dump()"
        )


def test_auth_env_excluded_even_with_exclude_override() -> None:
    """``_SENSITIVE_FIELDS`` is merged with the caller's ``exclude=``.

    The oneiric model_dump override merges the centralized
    ``_SENSITIVE_FIELDS`` with any caller-supplied ``exclude=``
    argument. A caller asking to exclude additional fields
    cannot accidentally re-include ``auth_env`` by passing an
    explicit ``exclude`` dict.
    """
    from oneiric.adapters.llm.bifrost import get_router

    dumped: dict[str, Any] = get_router()._settings.model_dump(
        exclude={"base_url"}  # caller wants to drop base_url
    )
    assert "auth_env" not in dumped, (
        "auth_env must be excluded even when the caller passes an "
        "explicit exclude= argument; _SENSITIVE_FIELDS is the floor."
    )
    assert "base_url" not in dumped, "caller's exclude= must still be honored"
