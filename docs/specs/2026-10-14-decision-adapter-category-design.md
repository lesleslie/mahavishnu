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
<<<<<<< Updated upstream
orchestrator can route through calibrated, typed decision classifiers
(TypeSafe Jev, vLLM Semantic Router Decision 3.0, and BGE Reranker v2-m3 via
HuggingFace TEI) without forking either the substrate or the orchestrator.
Land three concrete adapters in Phase 0.
=======
orchestrator can route through calibrated, typed decision classifiers (Jev
System One and BGE Reranker v2-m3 via HuggingFace TEI) without forking
either the substrate or the orchestrator. Land two concrete adapters in
Phase 0; add Cohere Rerank v4 in Phase 2 if needed.
>>>>>>> Stashed changes

## Architecture

```
oneiric/oneiric/adapters/decision/          ← substrate (Phase 0 PR to Oneiric)
├── __init__.py
├── types.py            # PointwiseRequest/Response, RankRequest/Response, Question/Answer
├── _base.py            # DecisionBaseSettings (Pydantic) + DecisionBase[SettingsT] (typed base)
<<<<<<< Updated upstream
├── jev.py              # JevAdapter(DecisionBase[JevSettings]) — closed hosted pointwise
├── decision_3.py       # Decision3Adapter(DecisionBase[Decision3Settings]) — open-source multimodal
└── bge_tei_rerank.py   # BgeTeiRerankAdapter(DecisionBase[BgeTeiSettings]) — relevance ranker

oneiric/oneiric/adapters/bootstrap.py      ← 6-line addition: 3 imports + 3 metadata entries
=======
├── jev.py              # JevAdapter(DecisionBase[JevSettings]) — pointwise Noul/Choice/Score
└── bge_tei_rerank.py   # BgeTeiRerankAdapter(DecisionBase[BgeTeiSettings]) — relevance ranker

oneiric/oneiric/adapters/bootstrap.py      ← 4-line addition: 2 imports + 2 metadata entries
>>>>>>> Stashed changes

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
<<<<<<< Updated upstream
declares the two category-specific abstract methods. All three concrete
adapters subclass it.
=======
declares the two category-specific abstract methods. Both concrete adapters
subclass it.
>>>>>>> Stashed changes

## Tech stack

- **Oneiric substrate** (Python 3.14, Pydantic v2, pydantic_settings,
  `typing.Protocol`, `typing.ClassVar`, `typing.Generic`)
- **PEP 735 `[dependency-groups].typesafe`** for the Jev SDK (lazy import)
<<<<<<< Updated upstream
- **`httpx2`** for the BGE/TEI and Decision 3.0 adapters (already a Oneiric
  baseline)
- **vLLM Semantic Router** in Engine mode for Decision 3.0 serving
- **Mahavishnu** (Python 3.14, `typer` for CLI, `FastMCP` for tools)
- **No new transports, no new runtimes.** All three concrete adapters are
  HTTP-in.
=======
- **`httpx2`** for the BGE/TEI adapter (already a Oneiric baseline)
- **Mahavishnu** (Python 3.14, `typer` for CLI, `FastMCP` for tools)
- **No new transports, no new runtimes.** The decision category is HTTP-in
  for all three concrete adapters.
>>>>>>> Stashed changes

## Substrate design

### `decision/types.py` — request/response Pydantic models

```python
from __future__ import annotations
<<<<<<< Updated upstream

from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, SecretStr
from pydantic_settings import SettingsConfigDict


# ---- Pointwise (Jev / Decision 3.0 style) ----
=======
from typing import Annotated, Literal, Union
from pydantic import BaseModel, Field

# ---- Pointwise (Jev-style) ----
>>>>>>> Stashed changes

class NoulQuestion(BaseModel):
    type: Literal["noul"] = "noul"
    name: str
    instructions: str

<<<<<<< Updated upstream

=======
>>>>>>> Stashed changes
class ChoiceQuestion(BaseModel):
    type: Literal["choice"] = "choice"
    name: str
    instructions: str
<<<<<<< Updated upstream
    options: dict[str, str] = Field(..., description="option_name -> option description")

=======
    options: dict[str, str]    # option_name -> option description
>>>>>>> Stashed changes

class ScoreQuestion(BaseModel):
    type: Literal["score"] = "score"
    name: str
    instructions: str
<<<<<<< Updated upstream
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
=======
    levels: list[str] = Field(..., min_length=2)

Question = Annotated[Union[NoulQuestion, ChoiceQuestion, ScoreQuestion], Field(discriminator="type")]


class PointwiseRequest(BaseModel):
    state: str
    questions: list[Question] = Field(..., min_length=1)
>>>>>>> Stashed changes


class Answer(BaseModel):
    name: str
    type: Literal["noul", "choice", "score"]
<<<<<<< Updated upstream
    value: float | str = Field(..., description="Typed value per question type.")
=======
    value: float | str
>>>>>>> Stashed changes
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
<<<<<<< Updated upstream


# ---- Settings base + per-adapter settings ----

class DecisionBaseSettings(BaseModel):
    model_config = SettingsConfigDict(env_prefix="ONEIRIC_", extra="forbid")
    base_url: str | None = Field(default=None, description="Override the adapter's default API URL.")
    model: str = Field(..., description="Concrete model id.")
    api_key_env: str = Field(..., description="Env-var name holding the secret. Never embed.")
    timeout_seconds: float = Field(default=30.0, gt=0)
    max_retries: int = Field(default=0, ge=0)
    caller_namespace: str = Field(default="public", description="Per REQ-OSUB-B-004.")
    cross_namespace_grant: bool = Field(default=False)

    @property
    def api_key(self) -> SecretStr | None:
        import os
        raw = os.environ.get(self.api_key_env)
        return SecretStr(raw) if raw else None


class JevSettings(DecisionBaseSettings):
    model: str = Field(default="jev-latest")
    api_key_env: str = Field(default="TYPESAFE_API_KEY")
    base_url: str | None = Field(default="https://api.typesafe.ai")


class BgeTeiSettings(DecisionBaseSettings):
    model: str = Field(default="BAAI/bge-reranker-v2-m3")
    base_url: str | None = Field(default="http://localhost:8081")
    api_key_env: str = Field(default="HF_TOKEN")


class Decision3Settings(DecisionBaseSettings):
    """vLLM Semantic Router Decision 3.0 — open-source multimodal pointwise decisions.

    Substrate default is `vllm-sr/d3-mini` (4.54B params) per Apple Silicon
    hardware fit. Operators with M1/M2 Max+ or M3/M4 Pro can override
    `model` to `vllm-sr/d3-flash` (8.39B). The full family:
    d3-edge (0.6B), d3-lite (0.9B), d3-nano (2B), d3-mini (4.54B),
    d3-flash (8.39B), d3 (27B). For quantized variants, pin a HuggingFace
    repo suffix like `vllm-sr/d3-mini-AWQ` and set `quantization` accordingly.
    """
    model: str = Field(default="vllm-sr/d3-mini")
    base_url: str = Field(default="http://localhost:8899", description="vllm-sr Engine mode default endpoint.")
    api_key_env: str | None = Field(default=None, description="vllm-sr local Engine mode is auth-less; kept for substrate parity but ignored when None.")
    quantization: str | None = Field(default=None, description="Optional. Maps to vllm-sr's --quantization flag. Common: 'awq', 'gptq', 'fp8'. Default None = let vllm-sr pick.")


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
=======
```

The discriminated union on `Question.type` makes the substrate Pydantic-validate
the right shape per question at the adapter boundary. No manual type-switching
inside the adapter.
>>>>>>> Stashed changes

### `decision/_base.py` — typed settings + typed adapter base

```python
from __future__ import annotations
<<<<<<< Updated upstream

=======
>>>>>>> Stashed changes
from abc import abstractmethod
from typing import Any, ClassVar, Generic, TypeVar

from pydantic import BaseModel, Field, SecretStr
from pydantic_settings import SettingsConfigDict

from oneiric.adapters.metadata import AdapterMetadata

from .types import NoulQuestion, PointwiseRequest, PointwiseResponse, RankRequest, RankResponse

SettingsT = TypeVar("SettingsT", bound="DecisionBaseSettings")


class DecisionBaseSettings(BaseModel):
    model_config = SettingsConfigDict(env_prefix="ONEIRIC_", extra="forbid")
    base_url: str | None = None
    model: str = Field(...)
    api_key_env: str = Field(...)
    timeout_seconds: float = Field(default=30.0, gt=0)
    max_retries: int = Field(default=0, ge=0)
<<<<<<< Updated upstream
    caller_namespace: str = Field(default="public")
=======
    caller_namespace: str = Field(default="public", description="Per REQ-OSUB-B-004.")
>>>>>>> Stashed changes
    cross_namespace_grant: bool = Field(default=False)

    @property
    def api_key(self) -> SecretStr | None:
        import os
        raw = os.environ.get(self.api_key_env)
        return SecretStr(raw) if raw else None


class DecisionBase(BaseModel, Generic[SettingsT]):
    """Typed base for decision adapters. Mirrors VectorBase[T] / LLMBase."""
<<<<<<< Updated upstream

    metadata: ClassVar[AdapterMetadata]   # concrete subclasses override
=======
    metadata: ClassVar[AdapterMetadata]    # concrete subclasses override
>>>>>>> Stashed changes

    def __init__(self, settings: SettingsT) -> None:
        self._settings = settings
        self._client: Any | None = None
        self._logger: Any = None
        self._cycles: int = 0

    @abstractmethod
    async def decide(self, request: PointwiseRequest) -> PointwiseResponse: ...
<<<<<<< Updated upstream

=======
>>>>>>> Stashed changes
    @abstractmethod
    async def rank(self, request: RankRequest) -> RankResponse: ...

    async def init(self) -> None:
        self._cycles += 1
<<<<<<< Updated upstream

    async def cleanup(self) -> None:
        self._client = None

=======
    async def cleanup(self) -> None:
        self._client = None
>>>>>>> Stashed changes
    async def health(self) -> bool:
        if self._client is None:
            return False
        try:
            await self.decide(PointwiseRequest(
                state="health probe",
                questions=[NoulQuestion(name="ok", instructions="the service is reachable")]))
            return True
<<<<<<< Updated upstream
        except Exception:                                # noqa: BLE001
            return False

    def has_capability(self, capability: str) -> bool:
        return capability in self.metadata.capabilities


__all__ = ["DecisionBase", "DecisionBaseSettings"]
```

### `decision/jev.py` — concrete adapter (closed hosted)

```python
=======
        except Exception:                            # noqa: BLE001 — health must never raise
            return False
    def has_capability(self, capability: str) -> bool:
        return capability in self.metadata.capabilities
```

### `decision/jev.py` — concrete adapter

```python
class JevSettings(DecisionBaseSettings):
    model_config = SettingsConfigDict(env_prefix="ONEIRIC_", extra="forbid")
    model: str = Field(default="jev-latest")
    api_key_env: str = Field(default="TYPESAFE_API_KEY")
    base_url: str = Field(default="https://api.typesafe.ai")


>>>>>>> Stashed changes
class JevAdapter(DecisionBase[JevSettings]):
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
<<<<<<< Updated upstream
    # decide() and rank() implementations — see plan for full TDD step-by-step
```

### `decision/decision_3.py` — concrete adapter (open-source multimodal)

```python
class Decision3Adapter(DecisionBase[Decision3Settings]):
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
    # decide() translates PointwiseRequest -> POST /v1/systemone -> PointwiseResponse
    # rank() raises NotImplementedError
```

### `decision/bge_tei_rerank.py` — concrete adapter (open-source ranker)

```python
=======

    async def decide(self, request: PointwiseRequest) -> PointwiseResponse: ...
    async def rank(self, request: RankRequest) -> RankResponse:
        raise NotImplementedError("Jev has no rank primitive. Use BgeTeiRerankAdapter.")

    async def init(self) -> None:
        from typesafe_sdk import AsyncTypeSafeClient
        api_key = self._settings.api_key
        if api_key is None:
            raise RuntimeError(f"{self._settings.api_key_env!r} not set in environment")
        self._client = AsyncTypeSafeClient(
            api_key=api_key.get_secret_value(),
            base_url=self._settings.base_url or "https://api.typesafe.ai",
        )
        await super().init()
```

### `decision/bge_tei_rerank.py` — concrete adapter

```python
class BgeTeiSettings(DecisionBaseSettings):
    model_config = SettingsConfigDict(env_prefix="ONEIRIC_", extra="forbid")
    model: str = Field(default="BAAI/bge-reranker-v2-m3")
    base_url: str = Field(default="http://localhost:8081")
    api_key_env: str = Field(default="HF_TOKEN")     # optional, for HF Inference Endpoints


>>>>>>> Stashed changes
class BgeTeiRerankAdapter(DecisionBase[BgeTeiSettings]):
    metadata: ClassVar[AdapterMetadata] = AdapterMetadata(
        category="decision",
        provider="bge_tei_rerank",
        factory="oneiric.adapters.decision.bge_tei_rerank: BgeTeiRerankAdapter",
        capabilities=["rank", "relevance_score", "self_hostable", "open_source", "multilingual"],
        stack_level=30, priority=370,
        source=CandidateSource.LOCAL_PKG,
        owner="Decision Substrate",
<<<<<<< Updated upstream
        requires_secrets=False,
        settings_model=BgeTeiSettings,
    )
    # rank() translates RankRequest -> POST /rerank -> RankResponse
    # decide() raises NotImplementedError
=======
        requires_secrets=False,                       # TEI is auth-less when self-hosted
        settings_model=BgeTeiSettings,
    )

    async def rank(self, request: RankRequest) -> RankResponse: ...
    async def decide(self, request: PointwiseRequest) -> PointwiseResponse:
        raise NotImplementedError("BGE Reranker is rank-only. Use JevAdapter.")

    async def init(self) -> None:
        headers = {}
        api_key = self._settings.api_key
        if api_key is not None:
            headers["Authorization"] = f"Bearer {api_key.get_secret_value()}"
        self._client = httpx.AsyncClient(
            base_url=self._settings.base_url,
            headers=headers,
            timeout=self._settings.timeout_seconds,
        )
        await super().init()
>>>>>>> Stashed changes
```

### Bootstrap patch

```python
# oneiric/adapters/bootstrap.py — additions only
<<<<<<< Updated upstream
from .decision import BgeTeiRerankAdapter, Decision3Adapter, JevAdapter
=======
from .decision import JevAdapter, BgeTeiRerankAdapter
>>>>>>> Stashed changes

def builtin_adapter_metadata() -> list[AdapterMetadata]:
    return [
        # ... existing 50+ entries unchanged ...
<<<<<<< Updated upstream
        BgeTeiRerankAdapter.metadata,
        Decision3Adapter.metadata,
        JevAdapter.metadata,
=======
        JevAdapter.metadata,
        BgeTeiRerankAdapter.metadata,
>>>>>>> Stashed changes
    ]
```

## Capability taxonomy

<<<<<<< Updated upstream
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
=======
| Capability | Jev | BGE/TEI |
|---|---|---|
| `noul` (pointwise yes/no) | ✓ | — |
| `choice` (pointwise option) | ✓ | — |
| `score` (pointwise graded) | ✓ | — |
| `rank` (relevance) | — | ✓ |
| `calibrated_probability` | ✓ | — |
| `multilingual` | ✓ | ✓ (model-dependent) |
| `self_hostable` | — | ✓ |
| `open_source` | — | ✓ |

`AdapterBridge.use("decision", capabilities=["noul"])` → Jev. `AdapterBridge.use("decision", capabilities=["rank", "self_hostable"])` → BGE/TEI. No ambiguity in the 2-adapter regime.
>>>>>>> Stashed changes

## Mahavishnu wire-up

### `mahavishnu/decision/router.py` — thin passthrough

```python
class DecisionRouter:
    def __init__(self, bridge: AdapterBridge) -> None:
        self._bridge = bridge

<<<<<<< Updated upstream
    async def resolve_decision(self, *, capabilities: list[str]) -> DecisionBase:
        handle = await self._bridge.use(
            "decision", capabilities=capabilities, require_all=True,
        )
        return handle.instance

    async def decide(self, request: PointwiseRequest, *, capabilities: list[str]) -> PointwiseResponse:
        adapter = await self.resolve_decision(capabilities=capabilities)
        return await adapter.decide(request)

    async def rank(self, request: RankRequest, *, capabilities: list[str]) -> RankResponse:
        adapter = await self.resolve_decision(capabilities=capabilities)
        return await adapter.rank(request)
=======
    async def resolve_decision(self, *, capabilities: list[str]) -> DecisionAdapter:
        handle = await self._bridge.use("decision", capabilities=capabilities, require_all=True)
        return handle.instance
>>>>>>> Stashed changes
```

### `mahavishnu/cli/decision_cli.py` — Pattern A

`@decision_app.command("decide")` and `@decision_app.command("rank")` mirroring
`mahavishnu/cli/launchd_cli.py:45-58` shape. Wire-up contract: 3 markers move
together (CLI docstring references `_main_cli.py:=== DECISION SUB-COMMANDS ===`
block, `_main_cli.py` registers the Typer group, `test_cli_wireup_invariants.py`
asserts registration).

### `mahavishnu/mcp/tools/decision_tools.py`

`mcp__mahavishnu__decision_decide` and `mcp__mahavishnu__decision_rank`. Profile-gated
per `mcp/server_core.py:_register_tools()` — `standard` and `full` profiles register,
`minimal` does not. Feed-state aggregator per
`docs/decisions/mcp-backend-wiring-discipline.md`: `feed.entities_count`,
`feed.last_updated_timestamp`, `feed.errors_total`, `cycles_total`. The
`cycles_total` is sourced from `adapter._cycles` populated by the
`DecisionBase.init()` default.

## Sequencing — hard rule

The `task_router.py` migration in
`mahavishnu/core/task_router.py:394, 403, 430, 493, 591` (5 live
`HybridAdapterRegistry` references) **must land before** the Mahavishnu
decision consumption work. The substrate-side Oneiric PR can land in
parallel — it's an additive change.

The pgvector fork deletion in
`mahavishnu/adapters/pgvector_adapter.py:126` is independent and can ship
alongside any of the above once `mahavishnu/adapters/pgvector_adapter.py`
is verified as unused by grep.

## Out of scope (Phase 2+)

- **Cohere Rerank v4** — closed hosted ranker. Will fit the same `rank()`
  shape as BGE/TEI. Future PR adds `oneiric/adapters/decision/cohere_rerank.py`
<<<<<<< Updated upstream
  and a fourth entry in `builtin_adapter_metadata()`.
=======
  and a third entry in `builtin_adapter_metadata()`.
>>>>>>> Stashed changes
- **OpenAI `omni-moderation-latest`** — categorical content classifier. Different
  question-type taxonomy (`category: str` instead of Noul/Choice/Score). Would
  warrant a `CategoricalQuestion` Pydantic variant.
- **Self-hosted Jina v3.5** — newer model from Jina. Same wire shape as
  Jina v2 / BGE / Cohere. Drop-in for BGE/TEI if operators want a different
  model with the same TEI-style API.
<<<<<<< Updated upstream
- **Qwen3 Reranker** — strong open-source ranker, but uses generative
  yes/no logit scoring (not sequence classification). Different wire shape
  than BGE/TEI. Needs a custom transport (vLLM with the Qwen3ForSequenceClassification
  override, or a sentence-transformers wrapper). Not in Phase 0; pick up as
  Phase 2 if/when the substrate gets a `rank_via_logits()` abstraction.
=======
>>>>>>> Stashed changes

## Phase 1 gating (live routing in `mcp__mahavishnu__pool_route_execute`)

Per the user's prior direction ("approval gating first"), the first live
use of the decision category in Mahavishnu should be a **shadow-mode
disagreement test**, not a flipped selector. Specifically:

1. Shadow-mode Jev Noul decisions alongside `mcp__mahavishnu__request_approval`
   for 7 days. Log disagreements with the hand-coded approval gate.
2. Compare P-value distribution vs. baseline (alert on >2σ shift).
3. Compute precision vs. the hand-coded baseline over the 7-day window.
4. Promote to live routing only when precision holds AND P-value distribution
   is within 2σ. Per `feedback-no-backwards-compat-pre-1.0.md`, no
   deprecation windows — if Phase 1 fails, the adapter stays at Phase 0
   (shadow mode) or gets removed entirely.

<<<<<<< Updated upstream
The same gating applies to Decision 3.0 (in shadow mode alongside Jev) and
to BGE/TEI (in shadow mode alongside any existing relevance-based routing).

## Cross-component surface

- **Oneiric**: substrate PR (this is the primary implementation)
=======
## Cross-component surface

- `Oneiric`: substrate PR (this is the primary implementation)
>>>>>>> Stashed changes
- **Mahavishnu**: thin `decision/router.py` + CLI + MCP tool + `task_router.py`
  selector
- **Akosha**: trace severity classification candidate (Phase 2, not Phase 0)
- **Session-Buddy**: content triage for `auto_compact` (Phase 2)
- **Crackerjack**: `crackerjack_hides_ty-output.md` failure-triage improvement
  candidate (Phase 2)

Other Bodai components inherit the convention without per-repo edits —
their workers run inside Mahavishnu's orchestration. They can consume
`AdapterBridge.use("decision", ...)` directly when they need it.

## Risks

1. **TypeSafe AI commercial availability.** TypeSafe has no documented
   enterprise deployment option beyond the hosted API. If they disappear,
   the Jev adapter becomes a dead branch. Mitigation: the substrate's
   `AdapterBridge` is the abstraction layer; swapping the implementation
   under the `typesafe_jev` provider is a config change, not a code change.
<<<<<<< Updated upstream
   Decision 3.0 is the open-source fallback for the same primitives.
2. **vLLM Semantic Router is on the `--channel dev` channel** — not yet
   a stable release. Decision 3.0 production deployment is gated on
   vllm-sr's stable release. The substrate's `requires_secrets=False`
   stays correct regardless.
3. **vllm-metal on Apple Silicon is experimental.** Per the contracollective.com
   comparison, "MPS support is experimental" and "the CUDA dependency is
   deep." Operators on Apple Silicon may need to use MLX or wait for
   vllm-sr to ship an official Apple Silicon path. The substrate
   transport-agnostic posture means this doesn't change the decision
   adapter protocol — only the serving runtime.
4. **HNSW extension migration.** Mahavishnu's `pgvector_adapter.py` carries
   HNSW indexing that Oneiric's `PgvectorAdapter` also has. The fork deletion
   is safe because Oneiric's class supports HNSW per the verified source.
5. **Substrate-federation rot.** Per `feedback-substrate-compat-shim-rot.md`,
=======
2. **HNSW extension migration.** Mahavishnu's `pgvector_adapter.py` carries
   HNSW indexing that Oneiric's `PgvectorAdapter` also has. The fork deletion
   is safe because Oneiric's class supports HNSW per the verified source.
3. **Substrate-federation rot.** Per `feedback-substrate-compat-shim-rot.md`,
>>>>>>> Stashed changes
   direct substrate extension can rot when Oneiric's surface evolves. The
   `DecisionBase[SettingsT]` typed base is intentionally narrow (two
   abstract methods) to keep the surface stable.

## References

- `/Users/les/Projects/oneiric/oneiric/adapters/protocol.py:47-117` — `OneiricAdapter` Protocol
- `/Users/les/Projects/oneiric/oneiric/adapters/metadata.py:21-58` — `AdapterMetadata`
- `/Users/les/Projects/oneiric/oneiric/adapters/vector/pgvector.py:28, 65-66` — `VectorBaseSettings` + `VectorBase[T]` precedent
- `/Users/les/Projects/oneiric/oneiric/adapters/bootstrap.py:79, 124` — bootstrap pattern
- `git log db06fc87` — `feat(adapters): Phase 2 — drop HybridAdapterRegistry, route through Oneiric`
- `mahavishnu/core/task_router.py:394, 403, 430, 493, 591` — 5 live `HybridAdapterRegistry` references
- `mahavishnu/core/health_integration.py:13, 261` — 2 docstring/comment refs
- `feedback-bodai-merge-workflow` (memory) — trunk-based review workflow
- `feedback-mcp-backend-wiring-discipline.md` (decision) — feed-state aggregator
- `feedback-wire-up-contract.md` (decision) — Integration Contract block requirement
- `feedback-no-backwards-compat-pre-1.0.md` (memory) — no deprecation windows
- `feedback-substrate-compat-shim-rot.md` (memory) — substrate extension rot pattern
- `feedback-mcp-test-must-assert-aggregator-verdict.md` (memory) — assert aggregator verdict, not slot population
<<<<<<< Updated upstream
- `feedback-keep-plan-files-tracked.md` (memory) — `git add docs/plans/*.md` first; **learned the hard way this session**
- [TypeSafe AI blog](https://typesafe.ai/blog/introducing-system-one-models-and-jev) — Jev API contract
- [TechCrunch — A new kind of AI model from a ChatGPT inventor is thrilling developers](https://techcrunch.com/2026/09/18/a-new-kind-of-ai-model-from-a-chatgpt-inventor-is-thrilling-developers) — TypeSafe founders, $40M seed
- [vllm-sr/d3-mini model card](https://huggingface.co/vllm-sr/d3-mini) — Decision 3.0 hardware numbers
- [vllm-sr/d3-flash model card](https://huggingface.co/vllm-sr/d3-flash) — Decision 3.0 flagship, multimodal
- [🔮Decision 3.0 collection](https://huggingface.co/collections/vllm-sr/decision-30) — full model family
- [vllm-project/vllm-metal](https://github.com/vllm-project/vllm-metal) — Apple Silicon serving plugin
=======
- [TypeSafe AI blog](https://typesafe.ai/blog/introducing-system-one-models-and-jev) — Jev API contract
- [TechCrunch — A new kind of AI model from a ChatGPT inventor is thrilling developers](https://techcrunch.com/2026/09/18/a-new-kind-of-ai-model-from-a-chatgpt-inventor-is-thrilling-developers) — TypeSafe founders, $40M seed
>>>>>>> Stashed changes
- [HuggingFace — BAAI/bge-reranker-base](https://huggingface.co/BAAI/bge-reranker-base) — BGE model card
- [Spheron — TEI on GPU Cloud](https://www.spheron.network/blog/self-host-embedding-reranker-tei-gpu-cloud) — TEI deployment
