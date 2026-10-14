# Decision Adapter Category — Design Spec

**Status:** Draft. Phase 0 substrate PR targets Oneiric. Phase 1 Mahavishnu
consumption gated on the `task_router.py` migration landing first.

**Authoritative substrate contract:** `oneiric.adapters.protocol.OneiricAdapter`
(Protocol, structural) at `/Users/les/Projects/oneiric/oneiric/adapters/protocol.py:47-117`.
Every Oneiric adapter conforms to it via duck typing, not inheritance. Four
required members: `metadata: ClassVar[AdapterMetadata]`, `async init`,
`async health`, `async cleanup`. The `Resolver` and `AdapterBridge` enforce
the full contract at registration time and `use()` time.

## Goal

Add a `decision/` adapter category to the Oneiric substrate so the Mahavishnu
orchestrator can route through calibrated, typed decision classifiers
(TypeSafe Jev, vLLM Semantic Router Decision 3.0, and BGE Reranker v2-m3 via
HuggingFace TEI) without forking either the substrate or the orchestrator.
Land three concrete adapters in Phase 0.

## Architecture

```
oneiric/oneiric/adapters/decision/          ← substrate (Phase 0 PR to Oneiric)
├── __init__.py
├── types.py            # PointwiseRequest/Response, RankRequest/Response, Question/Answer
├── _base.py            # DecisionBaseSettings (Pydantic) + DecisionBase[SettingsT] (typed base)
├── jev.py              # JevAdapter(DecisionBase[JevSettings]) — closed hosted pointwise
├── decision_3.py       # Decision3Adapter(DecisionBase[Decision3Settings]) — open-source multimodal
└── bge_tei_rerank.py   # BgeTeiRerankAdapter(DecisionBase[BgeTeiSettings]) — relevance ranker

oneiric/oneiric/adapters/bootstrap.py      ← 6-line addition: 3 imports + 3 metadata entries

mahavishnu/decision/router.py              ← thin passthrough to AdapterBridge.use("decision", ...)
mahavishnu/cli/decision_cli.py             ← `mahavishnu decision decide` + `mahavishnu decision rank`
mahavishnu/mcp/tools/decision_tools.py     ← mcp__mahavishnu__decision_decide + _rank
mahavishnu/core/task_router.py             ← MIGRATION (Phase 0 prerequisite): 5 HybridAdapterRegistry refs
mahavishnu/core/adapter_discovery.py       ← MIGRATION cleanup (likely dead, verify)
mahavishnu/core/health_integration.py      ← MIGRATION: 2 docstring/comment refs
mahavishnu/adapters/pgvector_adapter.py    ← DELETION (Phase 0): route through AdapterBridge instead
```

`DecisionBase[SettingsT]` is the typed base for the category, mirroring
`VectorBase[T]`, `LLMBase`, `EmbeddingBase`. It carries the
substrate-conformant `__init__`, default `init`/`health`/`cleanup`, and
declares the two category-specific abstract methods. All three concrete
adapters subclass it.

## Tech stack

- **Oneiric substrate** (Python 3.14, Pydantic v2, pydantic_settings,
  `typing.Protocol`, `typing.ClassVar`, `typing.Generic`)
- **PEP 735 `[dependency-groups].typesafe`** for the Jev SDK (lazy import)
- **`httpx2`** for the BGE/TEI and Decision 3.0 adapters (already a Oneiric
  baseline)
- **vLLM Semantic Router** in Engine mode for Decision 3.0 serving
- **Mahavishnu** (Python 3.14, `typer` for CLI, `FastMCP` for tools)
- **No new transports, no new runtimes.** All three concrete adapters are
  HTTP-in.

## Substrate design

### `decision/types.py` — request/response Pydantic models

```python
"""Decision adapter category — Pydantic request/response models and per-adapter settings.

Defines the substrate's typed surface for the decision category:
- `NoulQuestion`/`ChoiceQuestion`/`ScoreQuestion` discriminated union (`Question`)
  covers the three pointwise primitives shared by Jev and vLLM Semantic Router Decision 3.0.
- `PointwiseRequest`/`PointwiseResponse` carry pointwise decisions; `PointwiseRequest.images`
  and `.videos` are the multimodal extension used only by Decision 3.0 (Jev silently ignores).
- `RankRequest`/`RankResponse` carry the relevance-ranking primitive used by BGE/TEI.
- `DecisionBaseSettings` is the substrate's typed settings base (Pydantic v2,
  `SettingsConfigDict(env_prefix="ONEIRIC_", extra="forbid")`); per-adapter settings
  (`JevSettings`, `BgeTeiSettings`, `Decision3Settings`) inherit from it.
"""

from __future__ import annotations

from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, Field, SecretStr, model_validator
from pydantic_settings import SettingsConfigDict


# ---- Pointwise (Jev / Decision 3.0 style) ----

class NoulQuestion(BaseModel):
    type: Literal["noul"] = "noul"
    name: str
    instructions: str


class ChoiceQuestion(BaseModel):
    type: Literal["choice"] = "choice"
    name: str
    instructions: str
    options: dict[str, str] = Field(..., description="option_name -> option description")


class ScoreQuestion(BaseModel):
    type: Literal["score"] = "score"
    name: str
    instructions: str
    levels: list[str] = Field(..., min_length=2, description="Ordered low-to-high levels.")


Question = Annotated[
    Union[NoulQuestion, ChoiceQuestion, ScoreQuestion],
    Field(discriminator="type"),
]


class PointwiseRequest(BaseModel):
    state: str = Field(..., description="The state/text being decided about.")
    questions: list[Question] = Field(..., min_length=1)
    images: list[str] = Field(
        default_factory=list,
        description="Decision 3.0 only. Multimodal context (data URLs, paths, or PIL). Ignored by Jev.",
    )
    videos: list[str] = Field(
        default_factory=list,
        description="Decision 3.0 only. Multimodal context (paths, URLs, or frame arrays). Ignored by Jev.",
    )


class Answer(BaseModel):
    name: str
    type: Literal["noul", "choice", "score"]
    value: float | str = Field(..., description="Typed value per question type.")
    probability: float | None = None
    confidence: float | None = None
    rationale: str | None = None


class PointwiseResponse(BaseModel):
    answers: list[Answer]
    model: str
    usage: dict | None = None


# ---- Rank (Cohere / Jina / BGE-TEI style) ----

class RankRequest(BaseModel):
    query: str
    documents: list[str] = Field(..., min_length=1)
    top_n: int | None = None
    return_documents: bool = False


class RankedDocument(BaseModel):
    index: int
    relevance_score: float
    document: str | None = None


class RankResponse(BaseModel):
    results: list[RankedDocument]
    model: str
    usage: dict | None = None


# ---- Settings base + per-adapter settings ----

class DecisionBaseSettings(BaseModel):
    model_config = SettingsConfigDict(env_prefix="ONEIRIC_", extra="forbid")
    base_url: str | None = Field(default=None, description="Override the adapter's default API URL.")
    model: str = Field(..., description="Concrete model id.")
    api_key_env: str | None = Field(
        default=None,
        description=(
            "Env-var name holding the secret. Set to None for self-hosted adapters with no auth "
            "(e.g. vllm-sr Engine mode local, TEI without --api-key). Never embed the secret "
            "value in this field — only the env-var name. The api_key property short-circuits "
            "on None so callers don't crash on missing env vars."
        ),
    )
    timeout_seconds: float = Field(default=30.0, gt=0)
    max_retries: int = Field(default=0, ge=0)
    limits: httpx.Limits | None = Field(
        default=None,
        description=(
            "Optional httpx connection-pool limits. Default None = httpx defaults "
            "(max_connections=100, max_keepalive_connections=20). Operators with bursty "
            "multimodal Decision 3.0 workloads (10-MB base64 images) should widen to "
            "e.g. max_connections=200, max_keepalive_connections=50."
        ),
    )
    health_probe: Literal["capability_probe", "head_get", "skip"] = Field(
        default="capability_probe",
        description=(
            "Strategy for the feed-state aggregator's `health()` call. "
            "`capability_probe` (default) calls decide()/rank() with a tiny request — "
            "correct but expensive (one full wire round-trip per provider per 60s tick). "
            "`head_get` issues `GET {base_url}/health` (TEI exposes /health; vllm-sr does too "
            "in Engine mode). `skip` returns False without any network call — for environments "
            "where health is asserted by other means (e.g. k8s liveness probe)."
        ),
    )
    # caller_namespace / cross_namespace_grant REMOVED. The PgvectorAdapter namespace ACL
    # (REQ-OSUB-B-004) does not apply to HTTP-in hosted models — there is no ACL surface
    # analogous to Pgvector collections. If a future adapter needs namespace ACL, encode it
    # in concrete-adapter logic, not in substrate-level settings.

    @property
    def api_key(self) -> SecretStr | None:
        import os
        if self.api_key_env is None:
            return None
        raw = os.environ.get(self.api_key_env)
        return SecretStr(raw) if raw else None

    @model_validator(mode="after")
    def _validate_base_url_https(self) -> "DecisionBaseSettings":
        """Reject plaintext-http URLs unless they target loopback.

        Per the api-security review of this spec: when api_key is non-None, an http://
        base_url exposes the Bearer credential on the network path. Allow http:// only
        for loopback addresses (localhost / 127.0.0.1 / ::1) where TLS is the operator's
        choice. Operators using a remote deployment MUST front the service with TLS or
        set base_url to https://.
        """
        from urllib.parse import urlparse
        if self.base_url is None:
            return self
        parsed = urlparse(self.base_url)
        if parsed.scheme == "https":
            return self
        if parsed.scheme == "http" and parsed.hostname in ("localhost", "127.0.0.1", "::1"):
            return self
        raise ValueError(
            f"base_url must use https:// for non-loopback hosts; got {self.base_url!r}. "
            "Loopback (localhost / 127.0.0.1) may use http:// at operator discretion."
        )


class JevSettings(DecisionBaseSettings):
    model: str = Field(default="jev-latest")
    api_key_env: str = Field(default="TYPESAFE_API_KEY")
    base_url: str | None = Field(default="https://api.typesafe.ai")


class BgeTeiSettings(DecisionBaseSettings):
    """HuggingFace Text Embeddings Inference (TEI) for BAAI/bge-reranker-v2-m3.

    IMPORTANT: the default `api_key_env` is `TEI_API_KEY`, NOT `HF_TOKEN`. TEI's auth model
    is a server-side `--api-key <shared-secret>` flag, not a HuggingFace Hub token. Operators
    who export `HF_TOKEN` (the conventional HuggingFace download token name) will silently emit
    the wrong credential: a TEI server started with `--api-key=foo` will 401; a TEI server
    started without `--api-key` will succeed while leaking the HF Hub token in every request
    header. Either export `TEI_API_KEY` matching the TEI server's `--api-key`, or set
    `api_key_env=None` for an unauthenticated local TEI.
    """
    model: str = Field(default="BAAI/bge-reranker-v2-m3")
    base_url: str | None = Field(default="http://localhost:8081")
    api_key_env: str = Field(default="TEI_API_KEY")


class Decision3Settings(DecisionBaseSettings):
    """vLLM Semantic Router Decision 3.0 — open-source multimodal pointwise decisions.

    Note on nomenclature: vLLM Semantic Router's "Decision 3.0" refers to the d3-* model
    family (d3-edge, d3-lite, d3-nano, d3-mini, d3-flash, d3). The earlier "Decision 1.0"
    (model Decision-1.0-Lux-9B, Sept 2026) is a separate lineage; not part of Phase 0.

    Substrate default is `vllm-sr/d3-mini` (4.54B params) per Apple Silicon
    hardware fit. Operators with M1/M2 Max+ or M3/M4 Pro can override
    `model` to `vllm-sr/d3-flash` (8.39B). For quantized variants, pin a HuggingFace
    repo suffix like `vllm-sr/d3-mini-AWQ` and set `quantization` accordingly.

    IMPORTANT on quantization: vllm-sr consumes `--quantization` at server startup,
    NOT per-request. The `quantization` field in this settings model is plumbed through
    to the wire body in `Decision3Adapter.decide()` for documentation purposes, but the
    running vllm-sr instance picks its quantization at launch. To change quantization,
    restart vllm-sr with the new flag. Operators who expect runtime quantization control
    will be surprised; this is documented here to set expectations.

    IMPORTANT on auth: vllm-sr local Engine mode is auth-less. `api_key_env` inherits
    the base default of `None`. If you operate a vllm-sr instance with auth, override
    `api_key_env` to point at the env var holding the secret.
    """
    model: str = Field(default="vllm-sr/d3-mini")
    base_url: str = Field(default="http://localhost:8899", description="vllm-sr Engine mode default endpoint.")
    quantization: str | None = Field(default=None, description="Optional. Maps to vllm-sr's --quantization flag. Common: 'awq', 'gptq', 'fp8'. Default None = let vllm-sr pick. NOTE: consumed at vllm-sr startup, not per-request.")


__all__ = [
    "Answer",
    "BgeTeiSettings",
    "ChoiceQuestion",
    "Decision3Settings",
    "DecisionBaseSettings",
    "JevSettings",
    "NoulQuestion",
    "PointwiseRequest",
    "PointwiseResponse",
    "Question",
    "RankRequest",
    "RankResponse",
    "RankedDocument",
    "ScoreQuestion",
]
```

The discriminated union on `Question.type` makes the substrate Pydantic-validate
the right shape per question at the adapter boundary. The `images`/`videos`
fields on `PointwiseRequest` are optional and ignored by Jev, so the
extension is one-way additive.

### `decision/_base.py` — typed settings + typed adapter base

```python
"""Decision adapter typed base — mirrors `VectorBase[T]` (PEP 695 bare generic, no parent).

`DecisionBase[SettingsT]` is the substrate's typed base for the decision category.
Concrete adapters subclass it and assign `metadata: ClassVar[AdapterMetadata] = AdapterMetadata(...)`
as a plain class attribute (same pattern as `PgvectorAdapter`).

The base deliberately does NOT use `@abstractmethod` — that would be a no-op without
`abc.ABC` inheritance. Concrete adapters that do not support a method raise
`UnsupportedCapabilityError(RuntimeError)`, which surfaces to callers as a typed
substrate error instead of Python's built-in `NotImplementedError`.

Health probing is capability-aware: pointwise adapters probe `decide()`, rank-only
adapters probe `rank()`. This avoids the silent failure mode where a blanket
`except Exception` in `health()` swallows `UnsupportedCapabilityError` and reports
the adapter as permanently unhealthy (e.g. `BgeTeiRerankAdapter` would otherwise be
`False` forever).
"""

from __future__ import annotations

from typing import Any, ClassVar, Generic, TypeVar

from oneiric.adapters.metadata import AdapterMetadata
from oneiric.core.errors import UnsupportedCapabilityError

from .types import (
    DecisionBaseSettings,
    NoulQuestion,
    PointwiseRequest,
    PointwiseResponse,
    RankRequest,
    RankResponse,
)

SettingsT = TypeVar("SettingsT", bound=DecisionBaseSettings)


# NOTE — DecisionBaseSettings is the canonical model defined in `decision/types.py`
# with model_config=SettingsConfigDict(env_prefix="ONEIRIC_", extra="forbid") and
# full per-field descriptions. Do NOT redefine here. Subclasses (JevSettings,
# BgeTeiSettings, Decision3Settings) live in `decision/types.py` and inherit
# from the canonical model. A regression test (test_decision_base.py::
# test_decision_base_does_not_redefine_settings) enforces this.


class DecisionBase[SettingsT: DecisionBaseSettings]:
    """Typed base for decision adapters. Mirrors `VectorBase[T]` (bare PEP 695 generic).

    Attributes:
        metadata: AdapterMetadata class attribute. Subclasses MUST override with a
            concrete AdapterMetadata entry including `category`, `provider`,
            `capabilities`, and `settings_model`. AdapterBridge discovery
            (oneiric/core/resolution.py:278) uses `priority` (higher wins) to
            disambiguate when multiple adapters match the requested capabilities.
    """

    metadata: ClassVar[AdapterMetadata]   # concrete subclasses override

    def __init__(self, settings: SettingsT) -> None:
        """Store settings; defer client construction to `init()` (subclass hook).

        Args:
            settings: the per-adapter settings instance (subclass of DecisionBaseSettings).
        """
        self._settings = settings
        self._client: Any | None = None
        self._cycles: int = 0

    async def decide(self, request: PointwiseRequest) -> PointwiseResponse:
        """Translate PointwiseRequest -> adapter wire format, parse PointwiseResponse.

        Subclasses override with concrete adapter logic.

        Raises:
            UnsupportedCapabilityError: if this adapter does not support decide()
                (rank-only adapters such as `BgeTeiRerankAdapter`).
        """
        raise UnsupportedCapabilityError(
            f"{type(self).__name__} has no decide primitive. "
            "Use an adapter with 'noul'/'choice'/'score' in metadata.capabilities."
        )

    async def rank(self, request: RankRequest) -> RankResponse:
        """Translate RankRequest -> adapter wire format, parse RankResponse.

        Subclasses override with concrete adapter logic.

        Raises:
            UnsupportedCapabilityError: if this adapter does not support rank()
                (pointwise adapters such as `JevAdapter`, `Decision3Adapter`).
        """
        raise UnsupportedCapabilityError(
            f"{type(self).__name__} has no rank primitive. "
            "Use BgeTeiRerankAdapter."
        )

    async def init(self) -> None:
        """Lifecycle hook — construct the adapter's HTTP client (subclass hook).

        Default implementation bumps `_cycles`. Concrete adapters override to build
        an `httpx.AsyncClient` and set `_client`. Idempotent: each call increments
        `_cycles`, so callers should invoke once per adapter lifetime.

        Subclasses MUST thread `self._settings.limits` into the `httpx.AsyncClient(...)`
        call so the operator's connection-pool tuning actually takes effect. The
        default httpx limits are `max_connections=100, max_keepalive_connections=20`,
        which is too tight for Decision 3.0 multimodal bursts with 10-MB base64
        images (per the `limits` field on `DecisionBaseSettings`).
        """
        self._cycles += 1

    async def cleanup(self) -> None:
        """Lifecycle hook — release the HTTP client (subclass hook).

        Default implementation nulls `_client`. Subclasses close any open
        `httpx.AsyncClient` here.
        """
        self._client = None

    async def health(self) -> bool:
        """Capability-aware health probe, dispatched on `settings.health_probe`.

        Returns:
            True if the underlying service responded per the configured strategy.

        Strategy (set via `DecisionBaseSettings.health_probe`):
            - `"capability_probe"` (default): pointwise adapters probe `decide()`,
              rank-only adapters probe `rank()`. Real wire round-trip.
            - `"head_get"`: issue `GET {base_url}/health` (TEI exposes `/health`;
              vllm-sr does too in Engine mode). Cheaper than capability_probe.
            - `"skip"`: return False without network. Use when health is asserted
              by other means (k8s liveness probe, sidecar).

        The `_probe_decision_state` aggregator probe reads `DecisionRouter.cycles_total`,
        NOT `adapter._cycles` — the per-handle counter is not the aggregate.
        """
        if self._client is None:
            return False
        probe_strategy = getattr(self._settings, "health_probe", "capability_probe")
        if probe_strategy == "skip":
            return False
        if probe_strategy == "head_get":
            return await self._head_get_health()
        # Default: capability_probe
        caps = set(self.metadata.capabilities)
        try:
            if {"noul", "choice", "score"} & caps:
                await self.decide(PointwiseRequest(
                    state="health probe",
                    questions=[NoulQuestion(name="ok", instructions="the service is reachable")]))
            elif "rank" in caps:
                await self.rank(RankRequest(query="probe", documents=["probe"]))
            else:
                return False
            return True
        except UnsupportedCapabilityError:
            return False
        except Exception:                                # noqa: BLE001
            return False

    async def _head_get_health(self) -> bool:
        """GET `{base_url}/health` probe for adapters that expose it."""
        if self._client is None or self._settings.base_url is None:
            return False
        try:
            resp = await self._client.get("/health")
            return resp.status_code < 500
        except Exception:                                # noqa: BLE001
            return False

    def has_capability(self, capability: str) -> bool:
        """Whether `capability` is in this adapter's `metadata.capabilities` list.

        Args:
            capability: e.g. "noul", "rank", "multimodal", "open_source".
        """
        return capability in self.metadata.capabilities


__all__ = ["DecisionBase", "SettingsT"]
```

### `oneiric.core.errors` additions

The decision category introduces two new typed errors to `oneiric/core/errors.py`:

```python
class UnsupportedCapabilityError(RuntimeError):
    """Raised when an adapter does not implement a substrate primitive (decide/rank).

    Distinct from Python's built-in `NotImplementedError`, which is reserved for the
    abstract-method contract. `UnsupportedCapabilityError` carries the concrete
    adapter class name and the missing capability in its message; callers can
    surface a typed, actionable error to end-users.
    """

class ShadowModeOnlyError(RuntimeError):
    """Raised when an adapter or selector is invoked while the decision category is
    in shadow-mode-only phase.

    Phase 1 of the decision category spec mandates a 7-day shadow-mode disagreement
    test before any selector flips to live routing in `pool_route_execute`. Until
    Task 5 (shadow harness) ships, `MAHAVISHNU_DECISION_LIVE_ROUTING` must be set to
    `true` for live routing; absent that, `DecisionRouter._assert_shadow_mode_unlocked`
    raises this error before any bridge dispatch.
    """

class DecisionToolsDisabledError(RuntimeError):
    """Raised when `MAHAVISHNU_DECISION_ENABLED=false` and a decision MCP tool is called.

    Per-tool kill switch — leaves the tool registered so clients see a typed error
    rather than a 404, and avoids the blunt `MAHAVISHNU_TOOL_PROFILE=minimal` (which
    flips off 33 other tools).
    """
```

### `decision/jev.py` — concrete adapter (closed hosted)

```python
"""TypeSafe Jev adapter — closed-hosted System One pointwise decisions (Noul/Choice/Score).

Subclasses `DecisionBase[JevSettings]`. Substrate default: `api_key_env="TYPESAFE_API_KEY"`,
`base_url="https://api.typesafe.ai"`, `model="jev-latest"`. Adapter is pointwise-only; `rank()`
raises `UnsupportedCapabilityError("JevAdapter has no rank primitive; use BgeTeiRerankAdapter")`.

The `init()` method lazy-imports `typesafe_sdk` (per `[dependency-groups].typesafe` in
`oneiric/pyproject.toml`); init raises a clear `RuntimeError` if `TYPESAFE_API_KEY` is unset.
"""

from __future__ import annotations

from oneiric.adapters.decision._base import DecisionBase
from oneiric.adapters.decision.types import JevSettings, PointwiseRequest, PointwiseResponse, RankRequest, RankResponse
from oneiric.core.errors import UnsupportedCapabilityError


class JevAdapter(DecisionBase[JevSettings]):
    """TypeSafe Jev System One — closed-hosted pointwise Noul/Choice/Score decisions.

    Capabilities: noul, choice, score, calibrated_probability, typed_decision.
    `requires_secrets=True` — `init()` fails fast if `TYPESAFE_API_KEY` is unset.
    """

    metadata: ClassVar[AdapterMetadata] = AdapterMetadata(
        category="decision",
        provider="typesafe_jev",
        factory="oneiric.adapters.decision.jev: JevAdapter",
        capabilities=["noul", "choice", "score", "calibrated_probability", "typed_decision"],
        stack_level=30, priority=400,
        source=CandidateSource.LOCAL_PKG,
        owner="Decision Substrate",
        requires_secrets=True,
        settings_model=JevSettings,
    )

    async def decide(self, request: PointwiseRequest) -> PointwiseResponse:
        """Translate PointwiseRequest -> Jev wire format, parse response."""
        # ... full implementation per Task 1.13 of the plan

    async def rank(self, request: RankRequest) -> RankResponse:
        """Jev has no rank primitive.

        Raises:
            UnsupportedCapabilityError: always — Jev is pointwise-only.
        """
        raise UnsupportedCapabilityError(
            "JevAdapter has no rank primitive; use BgeTeiRerankAdapter."
        )
```

### `decision/decision_3.py` — concrete adapter (open-source multimodal)

```python
"""vLLM Semantic Router Decision 3.0 — open-source multimodal pointwise decisions.

Subclasses `DecisionBase[Decision3Settings]`. Substrate default: `model="vllm-sr/d3-mini"`,
`base_url="http://localhost:8899"`. Multimodal (images/videos) inputs are passed through;
Jev silently ignores them. `rank()` raises `UnsupportedCapabilityError`.

The `quantization` setting is plumbed into the wire body for documentation, but the
running vllm-sr instance picks its quantization at startup via `--quantization`. To
change quantization, restart vllm-sr with the new flag.
"""

from __future__ import annotations

from oneiric.adapters.decision._base import DecisionBase
from oneiric.adapters.decision.types import Decision3Settings, PointwiseRequest, PointwiseResponse, RankRequest, RankResponse
from oneiric.core.errors import UnsupportedCapabilityError


class Decision3Adapter(DecisionBase[Decision3Settings]):
    """vLLM Semantic Router Decision 3.0 — open-source multimodal pointwise decisions.

    Capabilities: noul, choice, score, calibrated_probability, typed_decision, multimodal,
    self_hostable, open_source. `requires_secrets=False` (local Engine mode is auth-less).
    """

    metadata: ClassVar[AdapterMetadata] = AdapterMetadata(
        category="decision",
        provider="vllm_sr_d3",
        factory="oneiric.adapters.decision.decision_3: Decision3Adapter",
        capabilities=[
            "noul", "choice", "score",
            "calibrated_probability", "typed_decision",
            "multimodal", "self_hostable", "open_source",
        ],
        stack_level=30, priority=380,
        source=CandidateSource.LOCAL_PKG,
        owner="Decision Substrate",
        requires_secrets=False,
        settings_model=Decision3Settings,
    )

    async def decide(self, request: PointwiseRequest) -> PointwiseResponse:
        """Translate PointwiseRequest -> POST /v1/systemone with images/videos passthrough.

        Returns:
            PointwiseResponse: decisions parsed from server's `{answers: {name: {option: probability}}}` shape.

        Raises:
            RuntimeError: if called before `init()` (no client).
        """
        # ... full implementation per Task 1.18 of the plan

    async def rank(self, request: RankRequest) -> RankResponse:
        """Decision 3.0 is pointwise-only.

        Raises:
            UnsupportedCapabilityError: always.
        """
        raise UnsupportedCapabilityError(
            "Decision3Adapter has no rank primitive; use BgeTeiRerankAdapter."
        )
```

### `decision/bge_tei_rerank.py` — concrete adapter (open-source ranker)

```python
"""HuggingFace Text Embeddings Inference (TEI) for BAAI/bge-reranker-v2-m3.

Subclasses `DecisionBase[BgeTeiSettings]`. Substrate default: `model="BAAI/bge-reranker-v2-m3"`,
`base_url="http://localhost:8081"`, `api_key_env="TEI_API_KEY"` (NOT `HF_TOKEN` — TEI auth is
the server's `--api-key` shared secret, not a HuggingFace Hub token). `decide()` raises
`UnsupportedCapabilityError`.
"""

from __future__ import annotations

from oneiric.adapters.decision._base import DecisionBase
from oneiric.adapters.decision.types import BgeTeiSettings, PointwiseRequest, PointwiseResponse, RankRequest, RankResponse
from oneiric.core.errors import UnsupportedCapabilityError


class BgeTeiRerankAdapter(DecisionBase[BgeTeiSettings]):
    """BGE Reranker v2-m3 via HuggingFace TEI — relevance ranking.

    Capabilities: rank, relevance_score, self_hostable, open_source, multilingual.
    `requires_secrets=False` (TEI can run without `--api-key`; HF_TOKEN is a model-download
    token, NOT an API auth credential).
    """

    metadata: ClassVar[AdapterMetadata] = AdapterMetadata(
        category="decision",
        provider="bge_tei_rerank",
        factory="oneiric.adapters.decision.bge_tei_rerank: BgeTeiRerankAdapter",
        capabilities=["rank", "relevance_score", "self_hostable", "open_source", "multilingual"],
        stack_level=30, priority=370,
        source=CandidateSource.LOCAL_PKG,
        owner="Decision Substrate",
        requires_secrets=False,
        settings_model=BgeTeiSettings,
    )

    async def rank(self, request: RankRequest) -> RankResponse:
        """Translate RankRequest -> POST /rerank with TEI's `{query, texts, raw_scores: false}` body.

        Returns:
            RankResponse: parsed relevance scores, optionally with document text.

        Raises:
            RuntimeError: if called before `init()` (no client).
        """
        # ... full implementation per Task 1.23 of the plan

    async def decide(self, request: PointwiseRequest) -> PointwiseResponse:
        """BGE is rank-only.

        Raises:
            UnsupportedCapabilityError: always.
        """
        raise UnsupportedCapabilityError(
            "BgeTeiRerankAdapter has no decide primitive; use Jev or Decision3."
        )
```

### Bootstrap patch

```python
# oneiric/adapters/bootstrap.py — additions only
from .decision import BgeTeiRerankAdapter, Decision3Adapter, JevAdapter

def builtin_adapter_metadata() -> list[AdapterMetadata]:
    return [
        # ... existing 50+ entries unchanged ...
        BgeTeiRerankAdapter.metadata,
        Decision3Adapter.metadata,
        JevAdapter.metadata,
    ]
```

## Capability taxonomy

| Capability | Jev | Decision 3.0 | BGE/TEI |
|---|---|---|---|
| `noul` (pointwise yes/no) | ✓ | ✓ | — |
| `choice` (pointwise option) | ✓ | ✓ | — |
| `score` (pointwise graded) | ✓ | ✓ | — |
| `rank` (relevance) | — | — | ✓ |
| `multimodal` (images, videos) | — | ✓ | — |
| `calibrated_probability` | ✓ | ✓ | — |
| `multilingual` | ✓ | ✓ | ✓ (model-dependent) |
| `self_hostable` | — | ✓ | ✓ |
| `open_source` | — | ✓ | ✓ |

`AdapterBridge.use("decision", capabilities=["noul"])` → Jev. `AdapterBridge.use("decision", capabilities=["rank", "self_hostable"])` → BGE/TEI. `AdapterBridge.use("decision", capabilities=["noul", "multimodal"])` → Decision 3.0.

## Mahavishnu wire-up

### `mahavishnu/decision/router.py` — thin passthrough with handle cache

```python
"""DecisionRouter — Mahavishnu-side wrapper over the Oneiric decision adapter category.

Caches `AdapterHandle`s keyed by `frozenset(capabilities)` to avoid re-dispatching
`bridge.use()` on every MCP invocation (the substrate's `LifecycleManager` already
caches the adapter instance + `httpx.AsyncClient`, but the bridge dispatch path
itself is per-call — the VectorBase precedent caches handles at module-scope; we
mirror that with a most-recent-cache on `DecisionRouter`).

Single-source `cycles_total` counter (atomic, with a lightweight `asyncio.Lock`)
is incremented inside `decide()`/`rank()` after each successful adapter call and
read by the feed-state aggregator's `_probe_decision_state` AND the MCP tool
wrappers — never `adapter._cycles` directly (that field is per-handle, not
aggregate).

`ShadowModeOnlyError` is raised by `decide()`/`rank()` when
`MAHAVISHNU_DECISION_LIVE_ROUTING` is unset. Phase 1 shadow-mode harness is
out-of-scope for this plan (see Task 5 follow-up); until Task 5 lands, this is
the only machine-checkable gate preventing operators from flipping a selector to
live routing on day 1.
"""

from __future__ import annotations

import asyncio
import os
from typing import FrozenSet

from oneiric.core.errors import ShadowModeOnlyError
from oneiric.adapters.bridge import AdapterBridge, AdapterHandle
from oneiric.adapters.decision.types import (
    PointwiseRequest, PointwiseResponse,
    RankRequest, RankResponse,
)


class DecisionRouter:
    """Thin passthrough over `AdapterBridge.use("decision", ...)` with handle cache."""

    def __init__(self, bridge: AdapterBridge) -> None:
        self._bridge = bridge
        self._handle_cache: dict[FrozenSet[str], AdapterHandle] = {}
        self._cycles_total: int = 0
        self._cycles_lock = asyncio.Lock()

    @property
    def cycles_total(self) -> int:
        """Single source of truth for the decision feed's cycle count."""
        return self._cycles_total

    async def resolve_decision(
        self, *, capabilities: list[str],
    ) -> AdapterHandle:
        """Resolve adapter via the bridge, caching the handle by capability set.

        Returns:
            AdapterHandle: the cached or freshly-resolved handle.

        Side effects:
            On cache miss, calls `bridge.use("decision", ...)` which may instantiate
            a new adapter + open an `httpx.AsyncClient`. The substrate's
            `LifecycleManager.get_instance(...)` cache (oneiric/domains/base.py:74-116)
            ensures the adapter instance is constructed once per process; we only
            avoid the bridge dispatch + handle-construction overhead on cache hits.
        """
        key = frozenset(capabilities)
        cached = self._handle_cache.get(key)
        if cached is not None:
            return cached
        handle = await self._bridge.use(
            "decision", capabilities=list(capabilities), require_all=True,
        )
        self._handle_cache[key] = handle
        return handle

    async def decide(
        self, request: PointwiseRequest, *, capabilities: list[str],
    ) -> PointwiseResponse:
        """Dispatch pointwise decision via the resolved adapter.

        Raises:
            ShadowModeOnlyError: if `MAHAVISHNU_DECISION_LIVE_ROUTING` is not "true".
            UnsupportedCapabilityError: if the resolved adapter has no decide primitive.
            LifecycleError: if no candidate matches the requested capabilities.
        """
        self._assert_shadow_mode_unlocked()
        handle = await self.resolve_decision(capabilities=capabilities)
        result = await handle.instance.decide(request)
        await self._bump_cycle()
        return result

    async def rank(
        self, request: RankRequest, *, capabilities: list[str],
    ) -> RankResponse:
        """Dispatch rank via the resolved adapter. Same raise contract as `decide`."""
        self._assert_shadow_mode_unlocked()
        handle = await self.resolve_decision(capabilities=capabilities)
        result = await handle.instance.rank(request)
        await self._bump_cycle()
        return result

    @staticmethod
    def _assert_shadow_mode_unlocked() -> None:
        if os.environ.get("MAHAVISHNU_DECISION_LIVE_ROUTING", "").lower() != "true":
            raise ShadowModeOnlyError(
                "Decision adapters are in shadow-mode-only until Task 5 ships. "
                "Set MAHAVISHNU_DECISION_LIVE_ROUTING=true to enable live routing."
            )

    async def _bump_cycle(self) -> None:
        """Atomic cycle counter bump. Cheap; not held during the await."""
        async with self._cycles_lock:
            self._cycles_total += 1
```

### `mahavishnu/cli/decision_cli.py` — Pattern A

```python
"""Decision CLI sub-commands — `mahavishnu decision decide` + `mahavishnu decision rank`.

Mirrors `mahavishnu/cli/launchd_cli.py:45-58` Pattern A. Wire-up contract: 3 markers
move together (CLI docstring references `_main_cli.py:=== DECISION SUB-COMMANDS ===`
block, `_main_cli.py` registers the Typer group, `test_cli_wireup_invariants.py`
asserts registration).
"""

# @decision_app.command("decide") -- accepts a JSON PointwiseRequest on stdin, prints the
# PointwiseResponse as JSON on stdout. Takes --capabilities to override the default
# capability set (default: ["noul", "choice", "score"]).
#
# @decision_app.command("rank") -- accepts a JSON RankRequest on stdin, prints the
# RankResponse as JSON on stdout. Takes --capabilities to override the default
# capability set (default: ["rank", "self_hostable"]).
```

### `mahavishnu/mcp/tools/decision_tools.py`

```python
"""Decision MCP tools — `mcp__mahavishnu__decision_decide` + `mcp__mahavishnu__decision_rank`.

Profile-gated via `STANDARD_REGISTRATIONS` (NOT inline `_register_tools()` gating —
the 27 inline tools register regardless of profile per `profiles.py:8-11`).

Feed-state aggregator wiring: `_probe_decision_state` in
`mahavishnu/core/health_aggregator.py` reads `DecisionRouter.cycles_total` directly,
NOT `adapter._cycles` (per-handle, not aggregate). Cycle increments are atomic via
`asyncio.Lock`. Per-tool kill switch: `MAHAVISHNU_DECISION_ENABLED=false` raises
`DecisionToolsDisabledError` from each tool, leaving the tool registered (so
clients see a typed error rather than a 404).
"""
```

## Sequencing — soft rule

The substrate-side Oneiric PR (Task 1) and the `task_router.py` migration
(Task 2) can land in parallel — Task 1 is additive to the substrate, and
Task 2 is a comment/docstring cleanup of `HybridAdapterRegistry` references
whose class was already deleted at commit `db06fc87`. The 5 references at
`mahavishnu/core/task_router.py:394, 403, 430, 493, 591` are all in
docstrings or comments; no active code path depends on them.

Task 3 has **two internal dependencies on Task 2** that are not strictly
"must land first" but are cheap to keep together:

1. **Task 3 Step 18a** (new) extends `TaskRouter.__init__(adapter_bridge=...)`.
   This must land before Task 3 Step 16-19's selector tests can pass.
2. **Task 3 Step 15** (the MCP wire-up) does not depend on Task 2 at all —
   the MCP tools wrap `DecisionRouter`, which is independent.

The pgvector fork deletion is **pulled out of this plan** as a separate
drive-by — see the decision doc rule 6 update. The premise of deleting
the fork was wrong: `mahavishnu/ingesters/otel_ingester.py:619` actively
imports it, and Oneiric's `vector/pgvector.py:271-277` only emits IVFFlat
(no HNSW), so the fork's HNSW config is not duplicated upstream.

## Out of scope (Phase 2+)

- **Cohere Rerank v4** — closed hosted ranker. Will fit the same `rank()`
  shape as BGE/TEI. Future PR adds `oneiric/adapters/decision/cohere_rerank.py`
  and a fourth entry in `builtin_adapter_metadata()`.
- **OpenAI `omni-moderation-latest`** — categorical content classifier. Different
  question-type taxonomy (`category: str` instead of Noul/Choice/Score). Would
  warrant a `CategoricalQuestion` Pydantic variant.
- **Self-hosted Jina v3.5** — newer model from Jina. Same wire shape as
  Jina v2 / BGE / Cohere. Drop-in for BGE/TEI if operators want a different
  model with the same TEI-style API.
- **Qwen3 Reranker** — strong open-source ranker, but uses generative
  yes/no logit scoring (not sequence classification). Different wire shape
  than BGE/TEI. Needs a custom transport (vLLM with the Qwen3ForSequenceClassification
  override, or a sentence-transformers wrapper). Not in Phase 0; pick up as
  Phase 2 if/when the substrate gets a `rank_via_logits()` abstraction.

## Phase 1 gating (live routing in `mcp__mahavishnu__pool_route_execute`)

Per the user's prior direction ("approval gating first"), the first live
use of the decision category in Mahavishnu should be a **shadow-mode
disagreement test**, not a flipped selector. Specifically:

1. Shadow-mode Jev Noul decisions alongside `mcp__mahavishnu__request_approval`
   for 7 days. Log disagreements with the hand-coded approval gate.
1. Compare P-value distribution vs. baseline (alert on >2σ shift).
1. Compute precision vs. the hand-coded baseline over the 7-day window.
1. Promote to live routing only when precision holds AND P-value distribution
   is within 2σ. Per `feedback-no-backwards-compat-pre-1.0.md`, no
   deprecation windows — if Phase 1 fails, the adapter stays at Phase 0
   (shadow mode) or gets removed entirely.

The same gating applies to Decision 3.0 (in shadow mode alongside Jev) and
to BGE/TEI (in shadow mode alongside any existing relevance-based routing).

## Cross-component surface (Phase 0 only — Phase 2+ moved to a separate doc)

- **Oneiric**: substrate PR (this is the primary implementation)
- **Mahavishnu**: thin `decision/router.py` + CLI + MCP tool + `task_router.py`
  selector (Tasks 1, 2, 3)

**Phase 2+ consumers (Akosha, Session-Buddy, Crackerjack) are NOT in scope
for this spec.** They are roadmap-by-vibes until each has a use case brief,
design doc, and stakeholder sign-off. Move them to a separate
`docs/decisions/2026-XX-XX-decision-adapter-category-phase2-stakeholders.md`
once any Phase 2 consumer commits to adoption.

The "Other Bodai components inherit the convention without per-repo edits"
phrase was removed — each repo has its own `pyproject.toml`, dependency
group policy, and `MAHAVISHNU_AUTO_MERGE=1` default. Per-repo adoption
requires per-repo work.

## Risks

1. **TypeSafe AI commercial availability.** TypeSafe has no documented
   enterprise deployment option beyond the hosted API. If they disappear,
   the Jev adapter becomes a dead branch. Mitigation: the substrate's
   `AdapterBridge` is the abstraction layer; swapping the implementation
   under the `typesafe_jev` provider is a config change, not a code change.
   Decision 3.0 is the open-source fallback for the same primitives.
1. **vLLM Semantic Router is on the `--channel dev` channel** — not yet
   a stable release. Decision 3.0 production deployment is gated on
   vllm-sr's stable release. The substrate's `requires_secrets=False`
   stays correct regardless.
1. **vllm-metal on Apple Silicon is experimental.** Per the contracollective.com
   comparison, "MPS support is experimental" and "the CUDA dependency is
   deep." Operators on Apple Silicon may need to use MLX or wait for
   vllm-sr to ship an official Apple Silicon path. The substrate
   transport-agnostic posture means this doesn't change the decision
   adapter protocol — only the serving runtime.
1. **pgvector HNSW gap.** Mahavishnu's `pgvector_adapter.py` carries HNSW
   indexing that Oneiric's `PgvectorAdapter` does NOT have (verified —
   `oneiric/adapters/vector/pgvector.py:271-277` only emits IVFFlat). The
   decision plan pulls the pgvector fork deletion out of scope. Until either
   (a) HNSW is backported to Oneiric's `PgvectorAdapter`, or (b) the OTel
   ingester migrates to `AdapterBridge.use("vector", provider="pgvector")`
   and the HNSW requirement is verified dispensable, the Mahavishnu fork
   must remain. The "delete fork in same change window" framing in the
   original rule 6 was factually wrong on two counts (Oneiric has no HNSW;
   fork is actively imported by `otel_ingester.py:619`).
1. **Substrate-federation rot.** Per `feedback-substrate-compat-shim-rot.md`,
   direct substrate extension can rot when Oneiric's surface evolves. The
   `DecisionBase[SettingsT]` typed base is intentionally narrow (two
   abstract methods) to keep the surface stable.

## README outline (per decision rule 9)

Both `oneiric/adapters/decision/README.md` (substrate-side) and
`mahavishnu/decision/README.md` (consumer-side) are committed by decision rule 9.
The sections below are the canonical scaffold — a doc-only change to this outline
flows into both READMEs via the cross-reference pointers in plan Tasks 1 and 3.

### `oneiric/adapters/decision/README.md` — substrate category surface

1. **What is the decision category?** — pointwise System One + relevance ranking
   for adapters that satisfy `OneiricAdapter` Protocol.
2. **Capability taxonomy** — table from spec §"Capability taxonomy" with which
   adapter supports which capabilities.
3. **Capability-aware routing** — how `AdapterBridge.use("decision",
   capabilities=[...])` resolves by `(priority, capability, stack)` per
   `oneiric/core/resolution.py:278`.
4. **Concrete adapters** — Jev, Decision 3.0, BGE/TEI: brief per-adapter setup,
   model, default endpoint, env-var contract.
5. **Operator setup** — `decision/__init__.py` re-exports; bootstrap registration;
   how to add a new adapter (ClassVar metadata pattern).
6. **Per-adapter env-var contract** — `api_key_env` (SecretStr indirection);
   `base_url` validator (https:// or loopback only); `health_probe` strategy
   options; `limits: httpx.Limits | None`.
7. **Typed errors** — `UnsupportedCapabilityError(RuntimeError)` for adapter
   missing a primitive; `ShadowModeOnlyError(RuntimeError)` for Phase 1 gate.
8. **Hard constraints** — no backwards-compat windows (per
   `feedback-no-backwards-compat-pre-1.0.md`); Pydantic v2 only; Python 3.14.

### `mahavishnu/decision/README.md` — consumer wiring

1. **What is DecisionRouter?** — thin passthrough over
   `AdapterBridge.use("decision", ...)`, with handle cache keyed by
   `frozenset(capabilities)`, atomic `cycles_total` counter, and shadow-mode gate.
2. **Selectors** — `jev_classify`, `d3_classify`, `bge_rank`. How to add a new
   selector (extend `_DECISION_SELECTORS` in `mahavishnu/core/task_router.py`).
3. **MCP tools** — `mcp__mahavishnu__decision_decide`, `mcp__mahavishnu__decision_rank`.
   Profile-gating via `STANDARD_REGISTRATIONS`.
4. **CLI** — `mahavishnu decision decide` + `mahavishnu decision rank`. Pattern A
   wire-up contract.
5. **Kill switch** — `MAHAVISHNU_DECISION_ENABLED` (truthy: `true|1|yes|on`,
   case-insensitive); `MAHAVISHNU_DECISION_LIVE_ROUTING` (same truthy set); the
   shadow-mode gate (`ShadowModeOnlyError`) and disabled-tools gate
   (`DecisionToolsDisabledError`).
6. **Health / observability** — feed-state aggregator probe
   (`_probe_decision_state`); per-provider health / cycles / errors; how to read
   `/health` for the decision category.
7. **Migration / rollback posture** — Pre-Task 3 user action (oneiric pin bump);
   cross-repo rollback contract (decision rule 15); the
   `try/except ImportError` fallback in `mahavishnu/decision/__init__.py`
   (graceful degradation when the substrate revert is in flight).

## References

- `/Users/les/Projects/oneiric/oneiric/adapters/protocol.py:47-117` — `OneiricAdapter` Protocol
- `/Users/les/Projects/oneiric/oneiric/adapters/metadata.py:21-58` — `AdapterMetadata`
- `/Users/les/Projects/oneiric/oneiric/adapters/vector/pgvector.py:28, 65-66` — `VectorBaseSettings` + `VectorBase[T]` precedent
- `/Users/les/Projects/oneiric/oneiric/adapters/bootstrap.py:79, 124` — bootstrap pattern
- `git log db06fc87` — `feat(adapters): Phase 2 — drop HybridAdapterRegistry, route through Oneiric`
- `mahavishnu/core/task_router.py:394, 403, 430, 493, 591` — 5 live `HybridAdapterRegistry` references
- `mahavishnu/core/health_integration.py:13` — 1 docstring ref (line 261 does not exist; was overstated in original plan)
- `feedback-bodai-merge-workflow` (memory) — trunk-based review workflow
- `feedback-mcp-backend-wiring-discipline.md` (decision) — feed-state aggregator
- `feedback-wire-up-contract.md` (decision) — Integration Contract block requirement
- `feedback-no-backwards-compat-pre-1.0.md` (memory) — no deprecation windows
- `feedback-substrate-compat-shim-rot.md` (memory) — substrate extension rot pattern
- `feedback-mcp-test-must-assert-aggregator-verdict.md` (memory) — assert aggregator verdict, not slot population
- `feedback-keep-plan-files-tracked.md` (memory) — `git add docs/plans/*.md` first; **learned the hard way this session**
- [TypeSafe AI blog](https://typesafe.ai/blog/introducing-system-one-models-and-jev) — Jev API contract
- [TechCrunch — A new kind of AI model from a ChatGPT inventor is thrilling developers](https://techcrunch.com/2026/09/18/a-new-kind-of-ai-model-from-a-chatgpt-inventor-is-thrilling-developers) — TypeSafe founders, $40M seed
- [vllm-sr/d3-mini model card](https://huggingface.co/vllm-sr/d3-mini) — Decision 3.0 hardware numbers
- [vllm-sr/d3-flash model card](https://huggingface.co/vllm-sr/d3-flash) — Decision 3.0 flagship, multimodal
- [🔮Decision 3.0 collection](https://huggingface.co/collections/vllm-sr/decision-30) — full model family
- [vllm-project/vllm-metal](https://github.com/vllm-project/vllm-metal) — Apple Silicon serving plugin
- [HuggingFace — BAAI/bge-reranker-base](https://huggingface.co/BAAI/bge-reranker-base) — BGE model card
- [Spheron — TEI on GPU Cloud](https://www.spheron.network/blog/self-host-embedding-reranker-tei-gpu-cloud) — TEI deployment
- [contracollective.com — vLLM Semantic Router Decision 3.0 comparison](https://contracollective.com/vllm-sr-decision-3) — substrate comparison cited in Risks #2/#3
- [vLLM Semantic Router — Decision Models blog](https://vllm-sr.ai/blog/decision-models) — Decision 1.0 vs 3.0 nomenclature clarification
- [HuggingFace — BAAI/bge-reranker-v2-m3](https://huggingface.co/BAAI/bge-reranker-v2-m3) — the canonical self-hostable relevance ranker substrate default
- [OpenAI — omni-moderation-latest](https://platform.openai.com/docs/guides/moderation) — out-of-scope Phase 2 categorical classifier (different taxonomy)
