"""The typed task envelope — where caller input becomes control input.

Phase 1 of the control-plane consolidation (plan §4.11). The envelope is
the trust boundary between a caller's free-form bag and the control plane's
substrate selection: which registered worker runs, how many of them run,
and for how long.

Three rules give the boundary its shape.

**Separated namespaces.** ``params`` holds caller-supplied values;
``control`` holds server-owned values. A caller cannot shadow a control
field, because the control namespace has no member the caller can write.

**Two timeout semantics, two fields.** ``deadline_seconds`` bounds the
whole execution (``None`` = unbounded, today's ``trigger_workflow``
behaviour, whose workflows "span repos or need durable state across hours
or days"). It is finite and positive -- ``inf`` is a bound's absence
spelled as a number -- but it is not capped above, because the public
``timeout`` parameter it carries had no bound before the envelope existed.
``leg_timeout_seconds`` bounds one leg (300 s, today's
``core/adapters/worker.py`` default) and is capped at
:data:`MAX_TIMEOUT`. One field cannot carry both, and a single
``timeout: float = 300`` would cap unbounded workflows *and* leave
``trigger_workflow``'s public parameter without a home.

**The projection is the only door to an adapter.** ``for_adapter`` returns
the plain dict an adapter reads, applying an explicit allowlist of the
parameters adapters actually use and an explicit deny-list of the keys
that select adapter behaviour. The deny-list is not cosmetic:
``TaskParams`` preserves unknown keys, so without it a caller would reach
``workflow_name`` (the dispatch target), ``tools`` (the agent's MCP
servers), ``system_prompt`` (the instruction override) and ``output_type``
(the output schema).
"""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any, Final

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from mahavishnu.core.metrics_schema import TaskType

# req: REQ-C02
# The envelope is this requirement's implementation. The entry points that
# build it carry the same marker (plan §4.10 lists ``core/workflow_execution.py``,
# ``mcp/server_core.py`` and ``_main_cli.py``): the requirement is "one
# envelope reaches every adapter", and it is not met until every builder
# constructs one.

#: The cap on a single leg's budget. 3600.0 s — one hour. It must exceed
#: the model's own default (:data:`LEG_TIMEOUT_SECONDS` = 300) or the
#: default would be invalid.
MAX_TIMEOUT: Final[float] = 3600.0

#: Per-leg (per-worker, per-adapter-attempt) budget. Today's value is
#: ``core/adapters/worker.py:209`` (``task.get("timeout", 300)``).
LEG_TIMEOUT_SECONDS: Final[float] = 300.0

#: The cap on a single prompt, taken from the pydantic-ai precedent
#: (``adapters/ai/pydantic_ai_adapter.py:55``) rather than invented.
MAX_PROMPT_LENGTH: Final[int] = 100000

#: The cap on the operation string — free-form, but not unbounded.
MAX_OPERATION_LENGTH: Final[int] = 100

#: The cap on the worker count, matching the repo's own precedent at
#: ``mcp/tools/worker_tools.py:67``. This is also the bound on the repo
#: scope's *worker* fan-out: a scope may name more repos than this, but
#: a single dispatch never mints more than this many workers -- the
#: worker adapter clamps the count it spawns to it
#: (``core/adapters/worker.py``), and the projection bounds the explicit
#: count it supplies.
MAX_COUNT: Final[int] = 50

#: The adapter that reads the worker controls. ``AdapterType.WORKER``'s
#: value, named here so this module does not import the adapters package.
WORKER_ADAPTER: Final[str] = "worker"

#: The worker type used when the envelope selects none. The adapter's own
#: default (``core/adapters/worker.py:206``); a bare ``None`` reaches
#: ``resolve_worker_type`` and dies on it.
DEFAULT_WORKER_TYPE: Final[str] = "terminal-claude"

#: Worker types a caller may select: one-shot agent CLIs only. Everything
#: else — interactive shells, database clients with credential-shaped
#: command templates — stays unreachable from a caller-supplied envelope.
WORKER_TYPE_ALLOWLIST: Final[frozenset[str]] = frozenset(
    {"terminal-claude", "terminal-qwen", "terminal-codex"}
)

#: Adapter-control keys. ``TaskParams`` preserves unknown keys, so these
#: must be dropped explicitly or a caller reaches the substrate's
#: dispatch target, the agent's MCP servers, its instruction override, or
#: its output schema.
CONTROL_DENY_LIST: Final[frozenset[str]] = frozenset(
    {"output_type", "system_prompt", "tools", "workflow_name"}
)

#: The parameters adapters read today: llamaindex's ``query``,
#: ``index_id``, ``top_k``, ``file_types``, ``exclude_patterns`` and
#: ``id``; agno's ``focus``, ``standards`` and ``target``; plus ``scope``
#: (the MCP tool's own docstring) and ``param1`` (the repo's own test).
PARAM_ALLOWLIST: Final[frozenset[str]] = frozenset(
    {
        "query",
        "index_id",
        "top_k",
        "file_types",
        "exclude_patterns",
        "id",
        "focus",
        "standards",
        "target",
        "scope",
        "param1",
    }
)

#: The server-derived permission mode per allowlisted worker type. The
#: registry default for ``terminal-qwen`` is ``yolo`` — auto-approve — so
#: it is overridden here; the other two match their registry defaults.
DEFAULT_PERMISSION_MODES: Final[dict[str, str]] = {
    "terminal-claude": "acceptEdits",
    "terminal-qwen": "plan",
    "terminal-codex": "workspace-write",
}

#: Server-derived adapter controls: the dispatch target a substrate reads
#: from the top level of the task dict. The adapter's own default supplies
#: it today; naming it here keeps it out of the caller's reach.
ADAPTER_WORKFLOW_NAMES: Final[dict[str, str]] = {
    "hatchet": "agent-loop",
}

#: The dispatch vocabulary of the adapters whose vocabulary is *closed* --
#: the ones that cannot run a task they do not name.
#:
#: The operation is free-form and it lands in ``task["type"]``, which is
#: the key an adapter branches on. An adapter with a default branch
#: (prefect's and agno's) dispatches anything, so its vocabulary is not
#: worth declaring; llamaindex's is closed, and an operation it does not
#: own is a request for behaviour that does not exist.
#:
#: This table is a copy of the engine's branch names -- the engines
#: import core, so core cannot import them. A source-level guard in
#: ``tests/unit/core/test_task_envelope.py`` asserts the copy still
#: matches ``engines/llamaindex_adapter_impl.py``.
ADAPTER_TASK_TYPES: Final[dict[str, frozenset[str]]] = {
    "llamaindex": frozenset({"ingest", "query", "ingest_and_query"}),
}

#: The type an adapter falls back to when the operation is not in its
#: vocabulary -- the type it runs when the key is absent. llamaindex's
#: own default is "ingest"
#: (``engines/llamaindex_adapter_impl.py`` reads ``task.get("type", "ingest")``).
ADAPTER_DEFAULT_TASK_TYPE: Final[dict[str, str]] = {
    "llamaindex": "ingest",
}

#: The id pattern. The same one the read path already enforces
#: (``mahavishnu/mcp/tools/_workflow_id_guard.py``), so the write and the
#: read accept the same ids by construction.
WORKFLOW_ID_PATTERN: re.Pattern[str] = re.compile(r"^[A-Za-z0-9._-]{1,128}$")

#: Path-traversal segments. The character class above admits "." and ".."
#: — both match it — but an id is spliced into a substrate key path, where
#: a dot-segment would traverse out of it. Rejected separately, exactly as
#: the read path does.
FORBIDDEN_ID_SEGMENTS: Final[frozenset[str]] = frozenset({".", ".."})


def _permission_modes_for(worker_type: str) -> frozenset[str]:
    """The permission modes the worker type's CLI accepts.

    Imported lazily: ``mahavishnu.workers`` imports back into
    ``mahavishnu.core``, so a module-level import here would close the
    cycle.
    """
    from mahavishnu.workers.registry import PERMISSION_MODES, get_worker_config

    config = get_worker_config(worker_type)
    tool = config.requires_tool if config is not None else ""
    return PERMISSION_MODES.get(tool, frozenset())


class TaskControlParams(BaseModel):
    """Server-side control fields. NEVER sourced from the caller's bag.

    ``extra="forbid"`` is the point: a control namespace that accepts
    unknown keys is a namespace a caller can write.
    """

    model_config = ConfigDict(extra="forbid")

    count: int | None = Field(default=None, ge=1, le=MAX_COUNT)
    # The whole-execution bound. It is finite and positive, but it is
    # NOT capped: the public ``trigger_workflow(timeout=...)`` parameter
    # had no bound before the envelope existed, and a workflow that
    # "spans repos or needs durable state across hours or days" needs a
    # deadline longer than one hour. The leg timeout is the bounded one.
    deadline_seconds: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    leg_timeout_seconds: float = Field(
        default=LEG_TIMEOUT_SECONDS, gt=0, le=MAX_TIMEOUT
    )
    worker_type: str | None = None
    preference_order: list[str] | None = None
    permission_mode: str | None = None
    #: The repo scope. Server-owned: the server computes it from the
    #: validated repo list, and it decides which paths the agent may
    #: read, how many workers run, and what lands in the durable
    #: workflow record. A caller's own list never reaches it.
    repos: list[str] = Field(default_factory=list)

    @field_validator("worker_type")
    @classmethod
    def _check_worker_type(cls, value: str | None) -> str | None:
        if value is not None and value not in WORKER_TYPE_ALLOWLIST:
            raise ValueError(
                f"worker_type {value!r} is not an allowlisted one-shot agent CLI; "
                f"expected one of {sorted(WORKER_TYPE_ALLOWLIST)}"
            )
        return value

    @model_validator(mode="after")
    def _check_permission_mode(self) -> TaskControlParams:
        """The mode must be one the selected CLI accepts.

        The mode is substituted into a command line, so an unchecked value
        could smuggle a flag into the agent's argv. Claude's
        ``bypassPermissions`` and Codex's ``danger-full-access`` are absent
        from the CLI allowlists and therefore rejected here too.
        """
        if self.permission_mode is None:
            return self
        if self.worker_type is not None:
            allowed = _permission_modes_for(self.worker_type)
            if self.permission_mode not in allowed:
                raise ValueError(
                    f"permission_mode {self.permission_mode!r} is not valid for "
                    f"{self.worker_type!r}; expected one of {sorted(allowed)}"
                )
            return self
        for worker_type in sorted(WORKER_TYPE_ALLOWLIST):
            if self.permission_mode in _permission_modes_for(worker_type):
                return self
        raise ValueError(
            f"permission_mode {self.permission_mode!r} is not valid for any "
            f"allowlisted worker type"
        )


class TaskParams(BaseModel):
    """Caller-supplied parameters. Control fields are NOT members.

    Unknown keys are PRESERVED (``extra="allow"``) because adapters read
    them by name — llamaindex's query path dies without ``query`` — and the
    projection decides which of them reach an adapter. The preservation is
    the mechanism; the allowlist is the rule.

    The repo scope is NOT a member: it is a control
    (:class:`TaskControlParams.repos`). A caller that could name the
    scope would name paths the server never validated.
    """

    model_config = ConfigDict(extra="allow")

    prompt: str = Field(default="", max_length=MAX_PROMPT_LENGTH)
    operation: str = Field(default="general", max_length=MAX_OPERATION_LENGTH)

    @model_validator(mode="after")
    def _check_target(self) -> TaskParams:
        """A ``target`` names a path inside a repo, so it cannot be absolute.

        agno joins a relative ``target`` to the repo but uses an absolute
        one verbatim, skipping containment — and an absolute path in the
        agent's instruction reaches any file the host can read.

        The containment check itself needs the repo scope, so it lives on
        the envelope: this model cannot see the control namespace.
        """
        extras = self.model_extra or {}
        target = extras.get("target")
        if target is None:
            return self
        raw = str(target).strip()
        if not raw:
            return self
        path = Path(raw)
        if path.is_absolute():
            raise ValueError(
                f"target {raw!r} must be repo-relative; an absolute path "
                "reaches outside the validated repo"
            )
        if ".." in path.parts:
            raise ValueError(
                f"target {raw!r} must not contain a '..' segment; it would "
                "traverse out of the validated repo"
            )
        return self


class TaskEnvelope(BaseModel):
    """The typed envelope every entry point builds.

    ``routing_type`` and ``id`` are server-derived: the routing
    classification is enum-constrained and bounded (it is the router's
    key, the workflow-id suffix and the metric label), and the id is
    pattern-constrained because it is spliced into substrate key paths.
    """

    model_config = ConfigDict(extra="forbid")

    routing_type: TaskType
    id: str = Field(pattern=r"^[A-Za-z0-9._-]{1,128}$")
    params: TaskParams = Field(default_factory=TaskParams)
    control: TaskControlParams = Field(default_factory=TaskControlParams)

    @field_validator("id")
    @classmethod
    def _check_id(cls, value: str) -> str:
        """Reject the dot segments the read path rejects.

        ``fullmatch`` rather than the pattern's ``$``: Python's ``$``
        also matches immediately before a trailing newline, and that
        value is spliced into a key path.
        """
        if value in FORBIDDEN_ID_SEGMENTS or not WORKFLOW_ID_PATTERN.fullmatch(value):
            raise ValueError(f"id {value!r} is not a safe key fragment")
        return value

    @model_validator(mode="after")
    def _check_target_containment(self) -> TaskEnvelope:
        """A ``target`` must resolve inside the scope, not just be relative.

        ``TaskParams`` rejects an absolute path and a ``..`` segment. A
        symlink inside the repo survives both, so the containment check
        belongs here — where the server's scope is visible.

        An empty scope skips the check: a relative target with no ``..``
        segment can only resolve inside whatever repo it is later joined
        to.
        """
        extras = self.params.model_extra or {}
        target = extras.get("target")
        if target is None:
            return self
        raw = str(target).strip()
        if not raw:
            return self
        path = Path(raw)
        for repo in self.control.repos:
            root = Path(repo).resolve()
            if not (root / path).resolve().is_relative_to(root):
                raise ValueError(
                    f"target {raw!r} resolves outside the validated repo {repo!r}"
                )
        return self

    def _projected_params(self) -> dict[str, Any]:
        """The caller's parameters an adapter is allowed to read."""
        extras = self.params.model_extra or {}
        projected = {
            key: value
            for key, value in extras.items()
            if key in PARAM_ALLOWLIST and key not in CONTROL_DENY_LIST
        }
        if self.params.prompt:
            # The prompt is a declared caller field rather than an extra,
            # but agno builds its brief from the params bag ("Parameters:
            # {params}") and never reads the top level — so the prompt
            # has to be in there or the adapter loses the task text.
            projected["prompt"] = self.params.prompt
        return projected

    def _effective_count(self) -> int | None:
        """The worker count to project, or ``None`` to omit the key.

        ``None`` means the adapter's own default applies: the adapter reads
        ``task.get("count", len(repos))``, and a projected ``count: None``
        would reach ``if count < 1`` and raise ``TypeError``.

        The projection cannot supply that default itself, because the
        adapter is called with a different repo list than the scope: the
        workflow lane dispatches once per repo
        (``core/workflow_execution.py:212`` passes ``[repo_path]``), while
        the router lane passes the whole scope
        (``core/task_router.py:924``). A count derived from the scope
        would mint one fleet per repo in the first lane. The adapter's own
        repo list is the right unit, and the adapter caps what it mints
        (``core/adapters/worker.py`` clamps to :data:`MAX_COUNT`).
        """
        repos = len(self.control.repos)
        if repos == 0:
            # One prompt -> one worker. The adapter's own default would be
            # ``len([]) == 0``, which it rejects.
            return 1
        if self.control.count is None:
            # Unset: the adapter's own default applies. See the docstring.
            return None
        return min(self.control.count, repos, MAX_COUNT)

    def _worker_projection(self) -> dict[str, Any]:
        """The controls the worker adapter reads from the top level.

        The worker adapter reads five top-level keys: ``worker_type``,
        ``count``, ``prompt``, ``timeout`` and ``task_type``. The
        projection supplies all five, so the adapter keeps no second
        source of truth.
        """
        worker_type = self.control.worker_type or DEFAULT_WORKER_TYPE
        projected: dict[str, Any] = {
            "worker_type": worker_type,
            "timeout": self.control.leg_timeout_seconds,
            "task_type": self.params.operation,
            "permission_mode": self.control.permission_mode
            or DEFAULT_PERMISSION_MODES.get(
                worker_type, DEFAULT_PERMISSION_MODES[DEFAULT_WORKER_TYPE]
            ),
        }
        count = self._effective_count()
        if count is not None:
            projected["count"] = count
        return projected

    def _adapter_task_type(self, adapter_type: str) -> str:
        """The dispatch selector this adapter reads.

        The operation is free-form, and it lands in ``task["type"]`` --
        the key an adapter branches on. An adapter with a default branch
        dispatches anything. An adapter with a *closed* vocabulary does
        not, and an operation it does not own names behaviour that does
        not exist: handed one, llamaindex answered "Unknown task type"
        for every repo. Such an operation becomes the adapter's own
        default, which is what the adapter runs when the key is absent.
        """
        vocabulary = ADAPTER_TASK_TYPES.get(adapter_type)
        if vocabulary is None or self.params.operation in vocabulary:
            return self.params.operation
        return ADAPTER_DEFAULT_TASK_TYPE[adapter_type]

    def for_adapter(self, adapter_type: str) -> dict[str, Any]:
        """Project the envelope into the shape ``adapter_type`` reads.

        A plain ``dict``, not the model: agno and llamaindex call
        ``.get()`` on what they receive, and a Pydantic instance has no
        ``.get()``.
        """
        projected: dict[str, Any] = {
            "id": self.id,
            "type": self._adapter_task_type(adapter_type),
            "routing_type": self.routing_type.value,
            "prompt": self.params.prompt,
            "repos": list(self.control.repos),
            "params": self._projected_params(),
        }
        workflow_name = ADAPTER_WORKFLOW_NAMES.get(adapter_type)
        if workflow_name is not None:
            projected["workflow_name"] = workflow_name
        if adapter_type == WORKER_ADAPTER:
            projected.update(self._worker_projection())
        return projected


def bounded_routing_type(task: dict[str, Any]) -> TaskType:
    """The bounded routing classification for ``task``.

    The metric label and the workflow-id suffix carry this, never the
    caller's free-form operation: an unbounded label creates a permanent
    metric series per distinct caller string.

    The envelope's ``routing_type`` wins when the task carries one. The
    task's ``type`` is the *operation* — what the adapter does — and its
    vocabulary has zero overlap with the routing one, so an operation
    with no routing classification (``code_sweep``, ``quality_check``,
    ``focused_review``, ``ingest``, ``query``) falls back to ``AI_TASK``.
    Coercing the operation is the bug this replaces.
    """
    raw = task.get("routing_type", task.get("type"))
    try:
        return TaskType(raw)
    except ValueError:
        return TaskType.AI_TASK
