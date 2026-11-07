"""Settings for the model-evaluation feature (REQ-EVAL-006).

``EvalSettings`` is a nested Pydantic model on ``MahavishnuSettings`` — not
a separate ``BaseSettings``. The parent carries ``env_prefix="MAHAVISHNU_"``
and ``env_nested_delimiter="__"``, so the field ``eval`` and its sub-field
``cost_budget_per_run`` resolve from ``MAHAVISHNU_EVAL__COST_BUDGET_PER_RUN``.

The delimiter placement matters. The working form is
``MAHAVISHNU_<GROUP>__<FIELD>``, matching the format documented in
``mahavishnu/core/config.py``. The ``MAHAVISHNU__<GROUP>__<FIELD>`` form
that appears in a few docstrings is silently ignored — verified 2026-11-06:
``MAHAVISHNU_OTEL_INGESTER__SIMILARITY_THRESHOLD=0.42`` resolves to 0.42,
while ``MAHAVISHNU__OTEL_INGESTER__SIMILARITY_THRESHOLD=0.42`` leaves the
0.7 default in place.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

# req: REQ-EVAL-006


class EvalSettings(BaseModel):
    """Configuration for the model-evaluation feature.

    The defaults are the Phase 1 dogfood profile: evaluation is off, the
    mock model backend is used, and the run store lives under the XDG state
    directory.

    Two of these fields are **guardrails**, not preferences:

    - ``dataset_root`` is the directory a dataset must live inside when it
      is named by a *server-reachable* caller (the MCP tools, the eval
      pool). The MCP surface is a trust boundary: without confinement, a
      client could name any file on disk and have the server read it.
    - ``max_tokens_per_call`` caps what a caller may ask a model for. A
      caller-supplied value is clamped to it, never replaces it.

    The operator's own shell (``mahavishnu eval run-suite``) is not a
    trust boundary and is not confined to ``dataset_root``: an operator
    who types a path means it.
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    default_storage: str = "mahavishnu.sqlite"
    default_dataset_loader: str = "mahavishnu.jsonl"
    default_scorers: list[str] = Field(default_factory=lambda: ["mahavishnu.contains"])
    default_model_backend: str = "mahavishnu.mock"
    cost_budget_per_run: float = 5.0
    db_path: str = "~/.local/state/mahavishnu/eval/runs.sqlite"
    dataset_root: str = "~/.local/state/mahavishnu/eval/datasets"
    max_tokens_per_call: int = 4096


def get_eval_settings() -> EvalSettings:
    """Return the evaluation settings from the process-wide settings cache.

    Mirrors ``get_settings()`` at ``mahavishnu/core/config.py``. The import
    is deferred so that ``mahavishnu.core.config`` can import ``EvalSettings``
    at module load time without a cycle.
    """
    from mahavishnu.core.config import get_settings

    return get_settings().eval
