---
status: shipped
role: implementation
date: 2026-07-16
last_reviewed: 2026-07-16
superseded_by: null
topic: agent-skill-modernization
---

# Agent & Skill Modernization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enrich 15 agent descriptions with ecosystem MCP tool references, add "Available MCP Servers" sections to all 22 native skills, and add automated stale-reference validation to `mahavishnu config validate`.

**Architecture:** TDD-first: write the validator (`mahavishnu/core/skill_mcp_validator.py`) and tests first, then edit agent/skill content files until all tests pass. Static content edits (agents, skills) are verified by running the validator, not by unit tests per file.

**Prerequisite:** Config Consolidation plan (`2026-04-26-config-consolidation.md`) must be complete. Agent files live at `mahavishnu/.claude/agents/`, skill files at `mahavishnu/.claude/skills/`. If consolidation hasn't run, substitute `~/.claude/agents/` and `~/.claude/skills/` accordingly.

**Tech Stack:** Python 3.13, `re` (stdlib), `pathlib`, `yaml` (PyYAML), `typer`, pytest, `mahavishnu/cli/config_validator.py` (existing).

______________________________________________________________________

### Task 1: Write the stale-reference validator

**Files:**

- Create: `mahavishnu/core/skill_mcp_validator.py`
- Create: `tests/unit/test_skill_mcp_validator.py`

The validator extracts `mcp__<server>__<tool>` patterns from files and checks them against a known registry. It also checks agent description lengths and port numbers.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_skill_mcp_validator.py
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from mahavishnu.core.skill_mcp_validator import (
    KNOWN_TOOLS,
    SkillValidationReport,
    extract_mcp_refs,
    validate_agent_file,
    validate_skill_file,
    validate_agent_dir,
    validate_skill_dir,
)


def test_extract_mcp_refs_none():
    assert extract_mcp_refs("No MCP references here.") == []


def test_extract_mcp_refs_single():
    content = "Use mcp__crackerjack__crackerjack_run for quality gates."
    assert extract_mcp_refs(content) == ["mcp__crackerjack__crackerjack_run"]


def test_extract_mcp_refs_multiple():
    content = "mcp__akosha__search_all_systems and mcp__session-buddy__checkpoint"
    refs = extract_mcp_refs(content)
    assert "mcp__akosha__search_all_systems" in refs
    assert "mcp__session-buddy__checkpoint" in refs


def test_extract_mcp_refs_triple_underscore():
    # FastMCP servers with hyphens use triple underscore
    content = "mcp__session-buddy___code_ingest_file_impl"
    assert extract_mcp_refs(content) == ["mcp__session-buddy___code_ingest_file_impl"]


def test_validate_agent_file_no_refs(tmp_path):
    agent = tmp_path / "test-agent.md"
    agent.write_text(textwrap.dedent("""\
        ---
        name: test-agent
        description: A short description with no ecosystem refs.
        model: sonnet
        ---
        """))
    report = validate_agent_file(agent)
    assert report.stale_refs == []
    assert not report.description_too_long
    assert not report.has_ecosystem_refs  # no refs is allowed (non-targeted agent)


def test_validate_agent_file_valid_ref(tmp_path):
    agent = tmp_path / "test-agent.md"
    agent.write_text(textwrap.dedent(f"""\
        ---
        name: test-agent
        description: >-
          Short description. Ecosystem: use {list(KNOWN_TOOLS)[0]} for quality.
        model: sonnet
        ---
        """))
    report = validate_agent_file(agent)
    assert report.stale_refs == []
    assert report.has_ecosystem_refs


def test_validate_agent_file_stale_ref(tmp_path):
    agent = tmp_path / "test-agent.md"
    agent.write_text(textwrap.dedent("""\
        ---
        name: test-agent
        description: Ecosystem: use mcp__crackerjack__nonexistent_tool.
        model: sonnet
        ---
        """))
    report = validate_agent_file(agent)
    assert "mcp__crackerjack__nonexistent_tool" in report.stale_refs


def test_validate_agent_file_description_too_long(tmp_path):
    agent = tmp_path / "test-agent.md"
    long_desc = "x" * 301
    agent.write_text(textwrap.dedent(f"""\
        ---
        name: test-agent
        description: {long_desc}
        model: sonnet
        ---
        """))
    report = validate_agent_file(agent)
    assert report.description_too_long


def test_validate_skill_file_no_mcp_section(tmp_path):
    skill = tmp_path / "SKILL.md"
    skill.write_text("# My Skill\n\n## Overview\n\nDoes something.\n")
    report = validate_skill_file(skill)
    assert not report.has_mcp_section
    assert report.stale_refs == []


def test_validate_skill_file_with_valid_mcp_section(tmp_path):
    skill = tmp_path / "SKILL.md"
    valid_tool = list(KNOWN_TOOLS)[0]
    skill.write_text(textwrap.dedent(f"""\
        # My Skill

        ## Available MCP Servers

        | Server | Port | Context Mode | Relevant Tools | Default Timeout |
        |--------|------|-------------|---------------|----------------|
        | crackerjack | 8676 | summary | {valid_tool} | 120s |

        ## Overview

        Does something.
        """))
    report = validate_skill_file(skill)
    assert report.has_mcp_section
    assert report.stale_refs == []


def test_validate_skill_file_stale_ref(tmp_path):
    skill = tmp_path / "SKILL.md"
    skill.write_text(textwrap.dedent("""\
        # My Skill

        ## Available MCP Servers

        Use mcp__crackerjack__old_tool_name for quality.

        ## Overview

        Does something.
        """))
    report = validate_skill_file(skill)
    assert "mcp__crackerjack__old_tool_name" in report.stale_refs


def test_validate_skill_file_wrong_port(tmp_path):
    skill = tmp_path / "SKILL.md"
    skill.write_text(textwrap.dedent("""\
        # My Skill

        ## Available MCP Servers

        session-buddy on port 8765.

        ## Overview
        """))
    report = validate_skill_file(skill)
    assert any("8765" in w for w in report.wrong_ports), f"expected port 8765 in wrong_ports, got {report.wrong_ports}"
    assert any("8678" in w for w in report.wrong_ports), f"expected correct port 8678 in wrong_ports, got {report.wrong_ports}"


def test_validate_agent_dir_empty(tmp_path):
    reports = validate_agent_dir(tmp_path)
    assert reports == {}


def test_validate_skill_dir_empty(tmp_path):
    reports = validate_skill_dir(tmp_path)
    assert reports == {}
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/unit/test_skill_mcp_validator.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'mahavishnu.core.skill_mcp_validator'`

- [ ] **Step 3: Write the validator implementation**

```python
# mahavishnu/core/skill_mcp_validator.py
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml


# Canonical MCP tool registry: server -> set of tool names
# Tool names must match exactly what the running MCP server exposes.
# Triple-underscore tools arise when FastMCP converts Python names from servers
# with hyphens (e.g. session-buddy -> session_buddy prefix with leading _).
KNOWN_TOOLS: frozenset[str] = frozenset({
    # crackerjack (port 8676)
    "mcp__crackerjack__crackerjack_run",
    "mcp__crackerjack__search_code",
    "mcp__crackerjack__smart_error_analysis",
    "mcp__crackerjack__get_skills_for_issue",
    "mcp__crackerjack__get_comprehensive_status",
    "mcp__crackerjack__execute_crackerjack",
    "mcp__crackerjack__get_stage_status",
    "mcp__crackerjack__analyze_crackerjack",
    # akosha (port 8682)
    "mcp__akosha__search_all_systems",
    "mcp__akosha__search_code_patterns",
    "mcp__akosha__find_function_usage",
    "mcp__akosha__find_path",
    "mcp__akosha__detect_anomalies",
    "mcp__akosha__correlate_systems",
    "mcp__akosha__analyze_trends",
    "mcp__akosha__store_memory",
    "mcp__akosha__query_knowledge_graph",
    "mcp__akosha__get_graph_statistics",
    # session-buddy (port 8678)
    "mcp__session-buddy__checkpoint",
    "mcp__session-buddy__search_conversations",
    "mcp__session-buddy__store_reflection",
    "mcp__session-buddy__search_entities",
    "mcp__session-buddy__get_activity_summary",
    "mcp__session-buddy__code_call_chain",
    "mcp__session-buddy__code_impact_analysis",
    "mcp__session-buddy___code_ingest_file_impl",
    "mcp__session-buddy___code_ingest_directory_impl",
    "mcp__session-buddy___code_search_symbols_impl",
    "mcp__session-buddy___code_get_symbol_graph_impl",
    "mcp__session-buddy___code_list_projects_impl",
    # mahavishnu (port 8680)
    "mcp__mahavishnu__pool_spawn",
    "mcp__mahavishnu__pool_route_execute",
    "mcp__mahavishnu__pool_health",
    "mcp__mahavishnu__trigger_workflow",
    "mcp__mahavishnu__get_health",
    "mcp__mahavishnu__list_repos",
    "mcp__mahavishnu__list_workflows",
    "mcp__mahavishnu__get_workflow_status",
    "mcp__mahavishnu__index_code_graph",
    "mcp__mahavishnu__search_documentation",
    # dhara (port 8683)
    "mcp__dhara__put",
    "mcp__dhara__get",
    "mcp__dhara__list_adapters",
    "mcp__dhara__upsert_service",
    "mcp__dhara__record_event",
    "mcp__dhara__get_adapter",
    "mcp__dhara__store_adapter",
    "mcp__dhara__aggregate_patterns",
    # context7 (plugin)
    "mcp__plugin_context7_context7__query-docs",
    "mcp__plugin_context7_context7__resolve-library-id",
})

# Canonical port map: server name (as it appears in skill docs) -> correct port
KNOWN_PORTS: dict[str, int] = {
    "crackerjack": 8676,
    "session-buddy": 8678,
    "session_buddy": 8678,
    "mahavishnu": 8680,
    "akosha": 8682,
    "dhara": 8683,
}

_MCP_REF_RE = re.compile(r"mcp__[\w-]+___?[\w]+(?:__[\w]+)*")
_PORT_RE = re.compile(r"\b(crackerjack|session[_-]buddy|mahavishnu|akosha|dhara)\b.*?(?:port\s+)?(\d{4,5})", re.IGNORECASE)


@dataclass
class AgentValidationReport:
    path: Path
    stale_refs: list[str] = field(default_factory=list)
    description_too_long: bool = False
    has_ecosystem_refs: bool = False


@dataclass
class SkillValidationReport:
    path: Path
    stale_refs: list[str] = field(default_factory=list)
    has_mcp_section: bool = False
    wrong_ports: list[str] = field(default_factory=list)


def extract_mcp_refs(content: str) -> list[str]:
    """Return all mcp__<server>__<tool> patterns found in content."""
    return _MCP_REF_RE.findall(content)


def validate_agent_file(path: Path) -> AgentValidationReport:
    """Validate a single agent .md file."""
    report = AgentValidationReport(path=path)
    content = path.read_text()

    # Parse frontmatter
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            try:
                frontmatter = yaml.safe_load(parts[1]) or {}
            except yaml.YAMLError:
                frontmatter = {}
            description = str(frontmatter.get("description", ""))
            if len(description) > 300:
                report.description_too_long = True

    refs = extract_mcp_refs(content)
    report.has_ecosystem_refs = bool(refs)
    report.stale_refs = [r for r in refs if r not in KNOWN_TOOLS]
    return report


def validate_skill_file(path: Path) -> SkillValidationReport:
    """Validate a single skill SKILL.md file."""
    report = SkillValidationReport(path=path)
    content = path.read_text()

    report.has_mcp_section = "## Available MCP Servers" in content

    refs = extract_mcp_refs(content)
    report.stale_refs = [r for r in refs if r not in KNOWN_TOOLS]

    for match in _PORT_RE.finditer(content):
        server_raw, port_str = match.group(1), match.group(2)
        server = server_raw.lower().replace("-", "_").replace(" ", "_")
        canonical_key = server_raw.lower()
        correct_port = KNOWN_PORTS.get(canonical_key) or KNOWN_PORTS.get(server)
        if correct_port and int(port_str) != correct_port:
            report.wrong_ports.append(
                f"{server_raw}: found port {port_str}, expected {correct_port}"
            )

    return report


def validate_agent_dir(directory: Path) -> dict[str, AgentValidationReport]:
    """Validate all *.md files in an agents directory."""
    return {
        path.name: validate_agent_file(path)
        for path in sorted(directory.glob("*.md"))
    }


def validate_skill_dir(directory: Path) -> dict[str, SkillValidationReport]:
    """Validate all SKILL.md files recursively under a skills directory."""
    return {
        str(path.relative_to(directory)): validate_skill_file(path)
        for path in sorted(directory.rglob("SKILL.md"))
    }


__all__ = [
    "KNOWN_TOOLS",
    "KNOWN_PORTS",
    "AgentValidationReport",
    "SkillValidationReport",
    "extract_mcp_refs",
    "validate_agent_file",
    "validate_skill_file",
    "validate_agent_dir",
    "validate_skill_dir",
]
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
pytest tests/unit/test_skill_mcp_validator.py -v
```

Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add mahavishnu/core/skill_mcp_validator.py tests/unit/test_skill_mcp_validator.py
git commit -m "feat(validator): add skill/agent MCP stale-reference validator"
```

______________________________________________________________________

### Task 2: Integrate validator into `mahavishnu config validate`

**Files:**

- Modify: `mahavishnu/cli/config_validator.py`

- Create: `tests/unit/test_config_validator_mcp.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_config_validator_mcp.py
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from mahavishnu.core.skill_mcp_validator import KNOWN_TOOLS
from mahavishnu.cli.config_validator import (
    check_skill_agent_drift,
    DriftReport,
)


@pytest.fixture()
def clean_agent(tmp_path):
    agents = tmp_path / "agents"
    agents.mkdir()
    valid_tool = list(KNOWN_TOOLS)[0]
    (agents / "good-agent.md").write_text(textwrap.dedent(f"""\
        ---
        name: good-agent
        description: Short desc. Ecosystem: use {valid_tool}.
        model: sonnet
        ---
        """))
    return agents


@pytest.fixture()
def stale_agent(tmp_path):
    agents = tmp_path / "agents"
    agents.mkdir()
    (agents / "bad-agent.md").write_text(textwrap.dedent("""\
        ---
        name: bad-agent
        description: Ecosystem: use mcp__crackerjack__gone_forever.
        model: sonnet
        ---
        """))
    return agents


@pytest.fixture()
def clean_skill(tmp_path):
    skills = tmp_path / "skills" / "my-skill"
    skills.mkdir(parents=True)
    valid_tool = list(KNOWN_TOOLS)[0]
    (skills / "SKILL.md").write_text(textwrap.dedent(f"""\
        # My Skill

        ## Available MCP Servers

        | Server | Port | Context Mode | Relevant Tools | Default Timeout |
        |--------|------|-------------|---------------|----------------|
        | crackerjack | 8676 | summary | {valid_tool} | 120s |
        """))
    return tmp_path / "skills"


def test_drift_report_no_errors(clean_agent, clean_skill):
    report = check_skill_agent_drift(
        agents_dir=clean_agent,
        skills_dir=clean_skill,
    )
    assert isinstance(report, DriftReport)
    assert report.error_count == 0
    assert report.valid


def test_drift_report_stale_agent(stale_agent, clean_skill):
    report = check_skill_agent_drift(
        agents_dir=stale_agent,
        skills_dir=clean_skill,
    )
    assert not report.valid
    assert report.error_count > 0
    assert any("mcp__crackerjack__gone_forever" in e for e in report.errors)


def test_drift_report_missing_dirs(tmp_path):
    report = check_skill_agent_drift(
        agents_dir=tmp_path / "missing_agents",
        skills_dir=tmp_path / "missing_skills",
    )
    # Missing dirs produce no errors (dirs not present = nothing to validate)
    assert report.valid
    assert report.error_count == 0
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/unit/test_config_validator_mcp.py -v 2>&1 | head -10
```

Expected: `ImportError: cannot import name 'check_skill_agent_drift'`

- [ ] **Step 3: Add `check_skill_agent_drift` and `DriftReport` to config_validator.py**

Add the import at the **top** of `mahavishnu/cli/config_validator.py`, with the other imports:

```python
from ..core.skill_mcp_validator import validate_agent_dir, validate_skill_dir
```

Then add the `DriftReport` class and `check_skill_agent_drift` function before `__all__`:

```python


@dataclass(slots=True)
class DriftReport:
    """Aggregated skill/agent MCP drift report."""

    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def error_count(self) -> int:
        return len(self.errors)

    @property
    def valid(self) -> bool:
        return not self.errors


def check_skill_agent_drift(
    agents_dir: Path,
    skills_dir: Path,
) -> DriftReport:
    """Check agents and skills for stale MCP references and description violations."""
    report = DriftReport()

    if agents_dir.exists():
        for name, agent_report in validate_agent_dir(agents_dir).items():
            for ref in agent_report.stale_refs:
                report.errors.append(
                    f"Agent {name}: stale MCP ref {ref!r} not in KNOWN_TOOLS"
                )
            if agent_report.description_too_long:
                report.warnings.append(
                    f"Agent {name}: description exceeds 300 characters"
                )

    if skills_dir.exists():
        for rel_path, skill_report in validate_skill_dir(skills_dir).items():
            for ref in skill_report.stale_refs:
                report.errors.append(
                    f"Skill {rel_path}: stale MCP ref {ref!r} not in KNOWN_TOOLS"
                )
            for wrong in skill_report.wrong_ports:
                report.errors.append(f"Skill {rel_path}: wrong port — {wrong}")

    return report
```

Also update `__all__` to include `"check_skill_agent_drift"` and `"DriftReport"`.

- [ ] **Step 4: Run tests to confirm they pass**

```bash
pytest tests/unit/test_config_validator_mcp.py -v
```

Expected: All tests PASS.

- [ ] **Step 5: Wire into `run_validation()` function**

In `run_validation()` in `config_validator.py`, after `runtime_validations = _validate_runtime_settings(settings)`, add the following. Note: `Path` is already imported at the top of this file — use it directly, do not re-import inline.

```python
# mahavishnu/cli/config_validator.py is at mahavishnu/cli/config_validator.py,
# so parents[2] = repo root. If config consolidation hasn't run, .claude/ won't
# exist here and the check skips gracefully (both dirs checked with .exists()).
claude_dir = Path(__file__).parents[2] / ".claude"
if not claude_dir.exists():
    # Pre-consolidation fallback: global config dir
    claude_dir = Path.home() / ".claude"
drift_report = check_skill_agent_drift(
    agents_dir=claude_dir / "agents",
    skills_dir=claude_dir / "skills",
)
drift_errors = [
    ValidationResult(valid=False, message=e, path="mcp_drift")
    for e in drift_report.errors
]
drift_warnings = [
    ValidationResult(valid=True, message=w, path="mcp_drift")
    for w in drift_report.warnings
]
runtime_validations.extend(drift_errors)
runtime_validations.extend(drift_warnings)
```

- [ ] **Step 6: Run existing validation tests to confirm no regressions**

```bash
pytest tests/unit/test_config_validator_mcp.py tests/unit/ -k "config" -v 2>&1 | tail -20
```

Expected: All config validator tests PASS.

- [ ] **Step 7: Commit**

```bash
git add mahavishnu/cli/config_validator.py tests/unit/test_config_validator_mcp.py
git commit -m "feat(validate): integrate MCP stale-reference drift check into config validate"
```

______________________________________________________________________

### Task 3: Enrich 5 ecosystem agent descriptions

**Files:**

- Modify: `mahavishnu/.claude/agents/mahavishnu-specialist.md`
- Modify: `mahavishnu/.claude/agents/akasha-specialist.md`
- Modify: `mahavishnu/.claude/agents/oneiric-specialist.md`
- Modify: `mahavishnu/.claude/agents/mcp-integration-expert.md`
- Modify: `mahavishnu/.claude/agents/refactoring-specialist.md`

> If config consolidation hasn't run yet, these files are at `~/.claude/agents/`.

- [ ] **Step 1: Update `mahavishnu-specialist.md`**

Replace the `description` field:

```yaml
description: >-
  Expert in Mahavishnu orchestration platform. Routes tasks, manages workflows and
  adapter configuration, diagnoses pool and routing issues.
  Ecosystem: mcp__mahavishnu__pool_route_execute (task routing),
  mcp__mahavishnu__get_health (health check),
  mcp__mahavishnu__trigger_workflow (workflow control).
```

- [ ] **Step 2: Update `akasha-specialist.md` (fix spelling Akasha → Akosha)**

Replace the `description` field:

```yaml
description: >-
  Expert in Akosha cross-system intelligence and vector embeddings. Runs semantic
  search, pattern detection, and cross-repo correlation queries.
  Ecosystem: mcp__akosha__search_all_systems (semantic search),
  mcp__akosha__search_code_patterns (code patterns),
  mcp__akosha__detect_anomalies (anomaly detection).
```

Also fix any remaining "Akasha" spellings in the body of the file to "Akosha".

- [ ] **Step 3: Update `oneiric-specialist.md`**

Replace the `description` field:

```yaml
description: >-
  Expert in Oneiric component resolution, adapter lifecycle, and runtime orchestration.
  Handles adapter registration, config loading, and dependency resolution.
  Ecosystem: mcp__dhara__list_adapters (adapter catalog),
  mcp__dhara__get_adapter (adapter lookup),
  mcp__mahavishnu__list_repos (repo catalog).
```

- [ ] **Step 4: Update `mcp-integration-expert.md`**

Replace the `description` field:

```yaml
description: >-
  Expert in Model Context Protocol integration, FastMCP server design, and MCP
  tool registration. Designs and debugs MCP server-client interactions.
  Ecosystem: mcp__mahavishnu__get_health (server health),
  mcp__crackerjack__crackerjack_run (quality gates),
  mcp__akosha__search_code_patterns (cross-repo search).
```

- [ ] **Step 5: Update `refactoring-specialist.md`**

Replace the `description` field:

```yaml
description: >-
  Expert refactoring specialist for safe code transformation, pattern application,
  and reducing complexity while preserving behavior.
  Ecosystem: mcp__crackerjack__crackerjack_run (quality gates post-refactor),
  mcp__akosha__search_code_patterns (find usage patterns before changing).
```

- [ ] **Step 6: Verify with validator — no stale refs, no description > 300 chars**

```bash
python -c "
from pathlib import Path
from mahavishnu.core.skill_mcp_validator import validate_agent_dir
d = Path('mahavishnu/.claude/agents')  # adjust if pre-consolidation
for name, r in validate_agent_dir(d).items():
    if r.stale_refs or r.description_too_long:
        print(f'FAIL {name}: stale={r.stale_refs} long={r.description_too_long}')
print('done')
"
```

Expected: Only "done" printed (no FAIL lines for these 5 files).

- [ ] **Step 7: Commit**

```bash
git add mahavishnu/.claude/agents/mahavishnu-specialist.md \
        mahavishnu/.claude/agents/akasha-specialist.md \
        mahavishnu/.claude/agents/oneiric-specialist.md \
        mahavishnu/.claude/agents/mcp-integration-expert.md \
        mahavishnu/.claude/agents/refactoring-specialist.md
git commit -m "feat(agents): enrich 5 ecosystem agent descriptions with MCP tool references"
```

______________________________________________________________________

### Task 4: Enrich 10 generic agent descriptions

**Files:**

- Modify: `mahavishnu/.claude/agents/code-reviewer.md`

- Modify: `mahavishnu/.claude/agents/security-auditor.md`

- Modify: `mahavishnu/.claude/agents/python-pro.md`

- Modify: `mahavishnu/.claude/agents/architecture-council.md`

- Modify: `mahavishnu/.claude/agents/devops-troubleshooter.md`

- Modify: `mahavishnu/.claude/agents/pytest-hypothesis-specialist.md`

- Modify: `mahavishnu/.claude/agents/database-operations-specialist.md`

- Modify: `mahavishnu/.claude/agents/frontend-developer.md`

- Modify: `mahavishnu/.claude/agents/documentation-specialist.md`

- Modify: `mahavishnu/.claude/agents/incident-responder.md`

- [ ] **Step 1: Add ecosystem line to each agent**

For each agent, append an "Ecosystem:" line to the `description` field. The existing description content must be preserved. Use `>-` block scalar to keep it under 300 chars total.

**`code-reviewer.md`** — append:

```
Ecosystem: mcp__crackerjack__crackerjack_run (quality gates),
mcp__akosha__search_code_patterns (cross-repo pattern context).
```

**`security-auditor.md`** — append:

```
Ecosystem: mcp__crackerjack__crackerjack_run (security scans),
mcp__session-buddy__search_conversations (error log context).
```

**`python-pro.md`** — append:

```
Ecosystem: mcp__crackerjack__crackerjack_run (pytest quality gates),
mcp__akosha__search_code_patterns (cross-repo Python patterns),
mcp__mahavishnu__pool_route_execute (distributed test execution).
```

**`architecture-council.md`** — append:

```
Ecosystem: mcp__akosha__search_code_patterns (cross-repo patterns),
mcp__dhara__aggregate_patterns (adapter pattern history).
```

**`devops-troubleshooter.md`** — append:

```
Ecosystem: mcp__mahavishnu__get_health (service health),
mcp__akosha__detect_anomalies (metrics anomalies),
mcp__session-buddy__get_activity_summary (session logs).
```

**`pytest-hypothesis-specialist.md`** — append:

```
Ecosystem: mcp__crackerjack__crackerjack_run (test execution),
mcp__akosha__search_code_patterns (error pattern discovery).
```

**`database-operations-specialist.md`** — append:

```
Ecosystem: mcp__dhara__put (persistence layer),
mcp__akosha__analyze_trends (query trend analysis).
```

**`frontend-developer.md`** — append:

```
Ecosystem: mcp__mahavishnu__trigger_workflow (pipeline trigger),
mcp__session-buddy___code_search_symbols_impl (component symbol search).
```

**`documentation-specialist.md`** — append:

```
Ecosystem: mcp__akosha__search_all_systems (semantic doc search),
mcp__session-buddy__search_conversations (conversation context).
```

**`incident-responder.md`** — append:

```
Ecosystem: mcp__akosha__detect_anomalies (anomaly detection),
mcp__mahavishnu__get_workflow_status (workflow status),
mcp__session-buddy__search_conversations (error logs).
```

- [ ] **Step 2: Verify all 10 with validator**

```bash
python -c "
from pathlib import Path
from mahavishnu.core.skill_mcp_validator import validate_agent_dir
targets = [
    'code-reviewer', 'security-auditor', 'python-pro', 'architecture-council',
    'devops-troubleshooter', 'pytest-hypothesis-specialist',
    'database-operations-specialist', 'frontend-developer',
    'documentation-specialist', 'incident-responder',
]
d = Path('mahavishnu/.claude/agents')
reports = validate_agent_dir(d)
for t in targets:
    r = reports.get(f'{t}.md')
    if r is None:
        print(f'MISSING {t}.md')
    elif r.stale_refs or r.description_too_long:
        print(f'FAIL {t}: stale={r.stale_refs} long={r.description_too_long}')
    else:
        print(f'OK {t}')
"
```

Expected: 10 lines of `OK <name>`.

- [ ] **Step 3: Commit**

```bash
git add mahavishnu/.claude/agents/code-reviewer.md \
        mahavishnu/.claude/agents/security-auditor.md \
        mahavishnu/.claude/agents/python-pro.md \
        mahavishnu/.claude/agents/architecture-council.md \
        mahavishnu/.claude/agents/devops-troubleshooter.md \
        mahavishnu/.claude/agents/pytest-hypothesis-specialist.md \
        mahavishnu/.claude/agents/database-operations-specialist.md \
        mahavishnu/.claude/agents/frontend-developer.md \
        mahavishnu/.claude/agents/documentation-specialist.md \
        mahavishnu/.claude/agents/incident-responder.md
git commit -m "feat(agents): add ecosystem MCP references to 10 generic agents"
```

______________________________________________________________________

### Task 5: Add MCP reference tables to 18 existing skills

**Files:**

- Modify: 18 `SKILL.md` files under `mahavishnu/.claude/skills/`

The "Available MCP Servers" section goes immediately after the `## Overview` section heading (before its body). Each table has columns: Server | Port | Context Mode | Relevant Tools | Default Timeout.

Context Mode values: `full` (complete file content), `summary` (summarized context), `grep` (matching lines only).

- [ ] **Step 1: Add the section to each skill**

Insert the following block into each skill file. **Do not change any other content.**

**`manage-pools/SKILL.md`** — after `## Overview`:

```markdown
## Available MCP Servers

| Server | Port | Context Mode | Relevant Tools | Default Timeout |
|--------|------|-------------|---------------|----------------|
| mahavishnu | 8680 | summary | mcp__mahavishnu__pool_spawn, mcp__mahavishnu__pool_route_execute, mcp__mahavishnu__pool_health | 60s |
| session-buddy | 8678 | grep | mcp__session-buddy__get_activity_summary | 30s |
```

**`code-archaeologist/SKILL.md`** — after `## Overview`:

```markdown
## Available MCP Servers

| Server | Port | Context Mode | Relevant Tools | Default Timeout |
|--------|------|-------------|---------------|----------------|
| akosha | 8682 | summary | mcp__akosha__search_all_systems, mcp__akosha__find_function_usage, mcp__akosha__search_code_patterns | 60s |
| session-buddy | 8678 | full | mcp__session-buddy__search_conversations, mcp__session-buddy___code_search_symbols_impl | 30s |
```

**`orchestrate-workflow/SKILL.md`** — after `## Overview`:

```markdown
## Available MCP Servers

| Server | Port | Context Mode | Relevant Tools | Default Timeout |
|--------|------|-------------|---------------|----------------|
| mahavishnu | 8680 | summary | mcp__mahavishnu__trigger_workflow, mcp__mahavishnu__get_workflow_status, mcp__mahavishnu__list_workflows | 60s |
| crackerjack | 8676 | grep | mcp__crackerjack__crackerjack_run | 120s |
```

**`run-quality-checks/SKILL.md`** — after `## Overview`:

```markdown
## Available MCP Servers

| Server | Port | Context Mode | Relevant Tools | Default Timeout |
|--------|------|-------------|---------------|----------------|
| crackerjack | 8676 | summary | mcp__crackerjack__crackerjack_run, mcp__crackerjack__get_comprehensive_status, mcp__crackerjack__smart_error_analysis | 120s |
| mahavishnu | 8680 | grep | mcp__mahavishnu__get_health | 60s |
```

**`search-insights/SKILL.md`** — after `## Overview`:

```markdown
## Available MCP Servers

| Server | Port | Context Mode | Relevant Tools | Default Timeout |
|--------|------|-------------|---------------|----------------|
| akosha | 8682 | summary | mcp__akosha__search_all_systems, mcp__akosha__correlate_systems, mcp__akosha__detect_anomalies | 60s |
| session-buddy | 8678 | grep | mcp__session-buddy__search_conversations, mcp__session-buddy__store_reflection | 30s |
```

**`persistent-state/SKILL.md`** — after `## Overview`:

```markdown
## Available MCP Servers

| Server | Port | Context Mode | Relevant Tools | Default Timeout |
|--------|------|-------------|---------------|----------------|
| dhara | 8683 | grep | mcp__dhara__put, mcp__dhara__get, mcp__dhara__record_event | 30s |
| session-buddy | 8678 | grep | mcp__session-buddy__store_reflection | 30s |
```

**`learn-from-errors/SKILL.md`** — after `## Overview`:

```markdown
## Available MCP Servers

| Server | Port | Context Mode | Relevant Tools | Default Timeout |
|--------|------|-------------|---------------|----------------|
| session-buddy | 8678 | full | mcp__session-buddy__search_conversations, mcp__session-buddy__store_reflection, mcp__session-buddy__search_entities | 30s |
| crackerjack | 8676 | grep | mcp__crackerjack__smart_error_analysis | 120s |
```

**`ecosystem-awareness/SKILL.md`** — after `## Overview`:

```markdown
## Available MCP Servers

| Server | Port | Context Mode | Relevant Tools | Default Timeout |
|--------|------|-------------|---------------|----------------|
| mahavishnu | 8680 | summary | mcp__mahavishnu__get_health, mcp__mahavishnu__list_repos, mcp__mahavishnu__list_workflows | 60s |
| akosha | 8682 | summary | mcp__akosha__search_all_systems, mcp__akosha__correlate_systems | 60s |
```

**`quality-pulse/SKILL.md`** — after `## Overview`:

```markdown
## Available MCP Servers

| Server | Port | Context Mode | Relevant Tools | Default Timeout |
|--------|------|-------------|---------------|----------------|
| akosha | 8682 | summary | mcp__akosha__analyze_trends, mcp__akosha__detect_anomalies | 60s |
| crackerjack | 8676 | summary | mcp__crackerjack__get_comprehensive_status, mcp__crackerjack__get_stage_status | 120s |
```

**`session-archaeologist/SKILL.md`** — after `## Overview`:

```markdown
## Available MCP Servers

| Server | Port | Context Mode | Relevant Tools | Default Timeout |
|--------|------|-------------|---------------|----------------|
| akosha | 8682 | summary | mcp__akosha__search_all_systems, mcp__akosha__find_function_usage | 60s |
| session-buddy | 8678 | full | mcp__session-buddy__search_conversations, mcp__session-buddy__search_entities | 30s |
```

**`bodai-radar/SKILL.md`** — after `## Overview`:

```markdown
## Available MCP Servers

| Server | Port | Context Mode | Relevant Tools | Default Timeout |
|--------|------|-------------|---------------|----------------|
| session-buddy | 8678 | grep | mcp__session-buddy__get_activity_summary, mcp__session-buddy__checkpoint | 30s |
| mahavishnu | 8680 | grep | mcp__mahavishnu__get_health, mcp__mahavishnu__pool_health | 60s |
| akosha | 8682 | summary | mcp__akosha__detect_anomalies, mcp__akosha__correlate_systems | 60s |
```

**`auto-coordinate/SKILL.md`** — after `## Overview`:

```markdown
## Available MCP Servers

| Server | Port | Context Mode | Relevant Tools | Default Timeout |
|--------|------|-------------|---------------|----------------|
| mahavishnu | 8680 | summary | mcp__mahavishnu__trigger_workflow, mcp__mahavishnu__pool_route_execute, mcp__mahavishnu__get_workflow_status | 60s |
| session-buddy | 8678 | grep | mcp__session-buddy__get_activity_summary | 30s |
```

**`smart-scaling/SKILL.md`** — after `## Overview`:

```markdown
## Available MCP Servers

Primary: **mahavishnu** (8680) — mcp__mahavishnu__pool_spawn, mcp__mahavishnu__pool_health (context mode: grep, timeout: 60s)
```

**`capture-insights/SKILL.md`** — after `## Overview`:

```markdown
## Available MCP Servers

| Server | Port | Context Mode | Relevant Tools | Default Timeout |
|--------|------|-------------|---------------|----------------|
| session-buddy | 8678 | full | mcp__session-buddy__store_reflection, mcp__session-buddy__search_conversations | 30s |
| akosha | 8682 | summary | mcp__akosha__store_memory, mcp__akosha__query_knowledge_graph | 60s |
```

**`search-sessions/SKILL.md`** — after `## Overview`:

```markdown
## Available MCP Servers

Primary: **session-buddy** (8678) — mcp__session-buddy__search_conversations, mcp__session-buddy__search_entities (context mode: full, timeout: 30s)
```

**`sweep-repositories/SKILL.md`** — after `## Overview`:

```markdown
## Available MCP Servers

Primary: **mahavishnu** (8680) — mcp__mahavishnu__list_repos, mcp__mahavishnu__trigger_workflow (context mode: summary, timeout: 60s)
```

**`resolve-components/SKILL.md`** — after `## Overview`:

```markdown
## Available MCP Servers

| Server | Port | Context Mode | Relevant Tools | Default Timeout |
|--------|------|-------------|---------------|----------------|
| dhara | 8683 | grep | mcp__dhara__get_adapter, mcp__dhara__list_adapters, mcp__dhara__store_adapter | 30s |
| mahavishnu | 8680 | grep | mcp__mahavishnu__list_repos | 60s |
```

**`configure-oneiric/SKILL.md`** — after `## Overview`:

```markdown
## Available MCP Servers

Primary: **dhara** (8683) — mcp__dhara__list_adapters, mcp__dhara__get_adapter, mcp__dhara__store_adapter (context mode: grep, timeout: 30s)
```

- [ ] **Step 2: Verify all 18 skills now have the MCP section**

```bash
python -c "
from pathlib import Path
from mahavishnu.core.skill_mcp_validator import validate_skill_dir
d = Path('mahavishnu/.claude/skills')
missing = [p for p, r in validate_skill_dir(d).items() if not r.has_mcp_section]
if missing:
    print('Missing MCP section:', missing)
else:
    print('All skills have MCP sections')
"
```

Expected: `All skills have MCP sections`

- [ ] **Step 3: Commit**

```bash
git add mahavishnu/.claude/skills/
git commit -m "feat(skills): add Available MCP Servers sections to 18 existing skills"
```

______________________________________________________________________

### Task 6: Add MCP reference tables to 2 missing skills

**Files:**

- Modify: `mahavishnu/.claude/skills/swiftui-ipc-client/SKILL.md`

- Modify: `mahavishnu/.claude/skills/testing-strategies/SKILL.md`

- [ ] **Step 1: Update `swiftui-ipc-client/SKILL.md`** — add after `## Overview`:

```markdown
## Available MCP Servers

| Server | Port | Context Mode | Relevant Tools | Default Timeout |
|--------|------|-------------|---------------|----------------|
| session-buddy | 8678 | grep | mcp__session-buddy__search_conversations, mcp__session-buddy___code_search_symbols_impl | 30s |
| mahavishnu | 8680 | grep | mcp__mahavishnu__get_health | 60s |
```

- [ ] **Step 2: Update `testing-strategies/SKILL.md`** — add after `## Overview`:

```markdown
## Available MCP Servers

| Server | Port | Context Mode | Relevant Tools | Default Timeout |
|--------|------|-------------|---------------|----------------|
| crackerjack | 8676 | summary | mcp__crackerjack__crackerjack_run, mcp__crackerjack__smart_error_analysis, mcp__crackerjack__get_stage_status | 120s |
| session-buddy | 8678 | full | mcp__session-buddy__search_conversations, mcp__session-buddy__store_reflection | 30s |
| akosha | 8682 | summary | mcp__akosha__search_code_patterns, mcp__akosha__detect_anomalies | 60s |
```

- [ ] **Step 3: Verify both skills now have the MCP section and no stale refs**

```bash
python -c "
from pathlib import Path
from mahavishnu.core.skill_mcp_validator import validate_skill_dir
d = Path('mahavishnu/.claude/skills')
for p, r in validate_skill_dir(d).items():
    if 'swiftui' in p or 'testing-strategies' in p:
        print(p, 'has_mcp:', r.has_mcp_section, 'stale:', r.stale_refs)
"
```

Expected: Both skills show `has_mcp: True` and `stale: []`.

- [ ] **Step 4: Commit**

```bash
git add mahavishnu/.claude/skills/swiftui-ipc-client/SKILL.md \
        mahavishnu/.claude/skills/testing-strategies/SKILL.md
git commit -m "feat(skills): add MCP reference tables to swiftui-ipc-client and testing-strategies skills"
```

______________________________________________________________________

### Task 7: Fix stale references and wrong ports across all skills

**Files:**

- Modify: whichever skill SKILL.md files the validator reports as having stale refs or wrong ports

- [ ] **Step 1: Run the full validator to find all issues**

```bash
python -c "
from pathlib import Path
from mahavishnu.core.skill_mcp_validator import validate_skill_dir, validate_agent_dir

print('=== SKILLS ===')
for p, r in validate_skill_dir(Path('mahavishnu/.claude/skills')).items():
    if r.stale_refs or r.wrong_ports:
        print(f'SKILL {p}: stale={r.stale_refs} wrong_ports={r.wrong_ports}')

print('=== AGENTS ===')
for p, r in validate_agent_dir(Path('mahavishnu/.claude/agents')).items():
    if r.stale_refs:
        print(f'AGENT {p}: stale={r.stale_refs}')
" 2>&1
```

- [ ] **Step 2: For each reported file, fix the stale reference**

For each file listed, make only the targeted substitution. Representative examples:

**Wrong triple-underscore (session-buddy FastMCP names):**

```
# Before:
mcp__session-buddy__code_ingest_file
# After:
mcp__session-buddy___code_ingest_file_impl

# Before:
mcp__session-buddy__code_search_symbols
# After:
mcp__session-buddy___code_search_symbols_impl
```

**Wrong port for session-buddy:**

```
# Before:  session-buddy on port 8765
# After:   session-buddy on port 8678
```

**Misspelling:**

```
# Before:  Akasha
# After:   Akosha
```

Use the `Edit` tool for each file. Do not add new content — only fix the stale patterns identified by the validator output from Step 1.

- [ ] **Step 3: Re-run validator until zero issues**

```bash
python -c "
from pathlib import Path
from mahavishnu.core.skill_mcp_validator import validate_skill_dir, validate_agent_dir

issues = []
for p, r in validate_skill_dir(Path('mahavishnu/.claude/skills')).items():
    issues.extend(r.stale_refs + r.wrong_ports)
for p, r in validate_agent_dir(Path('mahavishnu/.claude/agents')).items():
    issues.extend(r.stale_refs)

if issues:
    print('REMAINING ISSUES:', issues)
else:
    print('CLEAN — zero stale references')
"
```

Expected: `CLEAN — zero stale references`

- [ ] **Step 4: Commit**

```bash
git add mahavishnu/.claude/skills/ mahavishnu/.claude/agents/
git commit -m "fix(agents,skills): resolve all stale MCP references and wrong port numbers"
```

______________________________________________________________________

### Task 8: Add notes-as-memory format to checkpoint skill

**Files:**

- Modify: `mahavishnu/.claude/skills/session-buddy/checkpoint/SKILL.md` (or wherever the checkpoint skill lives)

This implements the Notes-as-Memory pattern from the spec (section 8.3) — replacing full conversation replay with 200-token structured notes.

- [ ] **Step 1: Locate the checkpoint skill file**

Expected path (post-consolidation): `mahavishnu/.claude/skills/session-buddy/checkpoint/SKILL.md`

If that path doesn't exist, discover it:

```bash
find mahavishnu/.claude/skills -name "SKILL.md" | xargs grep -l "checkpoint" 2>/dev/null
```

- [ ] **Step 2: Add the Notes-as-Memory section**

After the existing checkpoint summary template (or after the first `## Implementation` section), add:

````markdown
## Notes-as-Memory Format

When creating checkpoint summaries, use structured notes instead of full conversation replay. This reduces token usage by ~90% while preserving essential context:

```markdown
## Checkpoint Notes

- **Decision**: [What was decided and which option was chosen]
- **Reason**: [Why — the constraint, tradeoff, or requirement that drove the choice]
- **Files changed**: [exact/path/to/file.py (created|modified), ...]
- **Next step**: [The single next action after this checkpoint]
- **Blockers**: [None | description of what is blocking progress]
````

Do not replay the full conversation. Do not summarize what was discussed. Only record decisions, reasons, files, and next steps.

````

- [ ] **Step 3: Verify the skill file still has no stale refs**

```bash
python -c "
from pathlib import Path
from mahavishnu.core.skill_mcp_validator import validate_skill_file
import subprocess, sys

result = subprocess.run(
    ['find', 'mahavishnu/.claude/skills', '-name', 'SKILL.md'],
    capture_output=True, text=True
)
for path_str in result.stdout.strip().split():
    p = Path(path_str)
    r = validate_skill_file(p)
    if 'checkpoint' in str(p).lower() and r.stale_refs:
        print(f'FAIL {p}: {r.stale_refs}')
        sys.exit(1)
print('OK')
"
````

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add mahavishnu/.claude/skills/
git commit -m "docs(skills): add notes-as-memory format to checkpoint skill"
```

______________________________________________________________________

### Task 9: Final verification — run full validation suite

**Files:** None (verification only)

- [ ] **Step 1: Run the pytest suite**

```bash
pytest tests/unit/test_skill_mcp_validator.py tests/unit/test_config_validator_mcp.py -v
```

Expected: All tests PASS.

- [ ] **Step 2: Run `mahavishnu config validate` (if Mahavishnu MCP is running)**

```bash
mahavishnu config validate --json 2>&1 | python -c "
import json, sys
report = json.load(sys.stdin)
drift_issues = [
    v for v in report.get('runtime_validations', [])
    if v.get('path') == 'mcp_drift' and not v['valid']
]
if drift_issues:
    print('DRIFT ISSUES:')
    for d in drift_issues:
        print(' ', d['message'])
    sys.exit(1)
else:
    print('No drift issues')
"
```

Expected: `No drift issues`

- [ ] **Step 3: Verify acceptance criteria**

```bash
python -c "
from pathlib import Path
from mahavishnu.core.skill_mcp_validator import validate_skill_dir, validate_agent_dir

skills = validate_skill_dir(Path('mahavishnu/.claude/skills'))
agents = validate_agent_dir(Path('mahavishnu/.claude/agents'))

# AC1: 15 enriched agents have MCP refs
enriched_agents = [
    'mahavishnu-specialist', 'akasha-specialist', 'oneiric-specialist',
    'mcp-integration-expert', 'refactoring-specialist',
    'code-reviewer', 'security-auditor', 'python-pro', 'architecture-council',
    'devops-troubleshooter', 'pytest-hypothesis-specialist',
    'database-operations-specialist', 'frontend-developer',
    'documentation-specialist', 'incident-responder',
]
for name in enriched_agents:
    r = agents.get(f'{name}.md')
    if r is None or not r.has_ecosystem_refs:
        print(f'AC1 FAIL: {name} missing ecosystem refs')

# AC2: all 22 skills have MCP section
missing_mcp = [p for p, r in skills.items() if not r.has_mcp_section]
if missing_mcp:
    print(f'AC2 FAIL: skills without MCP section: {missing_mcp}')

# AC3: zero stale refs
all_stale = [(p, r.stale_refs) for p, r in skills.items() if r.stale_refs]
all_stale += [(p, r.stale_refs) for p, r in agents.items() if r.stale_refs]
if all_stale:
    print(f'AC3 FAIL: stale refs: {all_stale}')

# AC4: no description > 300 chars
long_descs = [(p, ) for p, r in agents.items() if r.description_too_long]
if long_descs:
    print(f'AC4 FAIL: descriptions too long: {long_descs}')

# AC7: no 'Akasha' misspelling
import subprocess
result = subprocess.run(
    ['grep', '-rl', 'Akasha', 'mahavishnu/.claude/'],
    capture_output=True, text=True
)
if result.stdout.strip():
    print(f'AC7 FAIL: Akasha misspelling in: {result.stdout.strip()}')

print('Acceptance criteria check complete')
"
```

Expected: Only `Acceptance criteria check complete` printed.

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "chore: agent & skill modernization complete — all acceptance criteria met"
```

______________________________________________________________________

## Self-Review

### Spec Coverage

| Spec section | Plan coverage |
|---|---|
| §5 Agent description enrichment (15 agents) | Tasks 3, 4 |
| §6 Skills MCP reference tables (22 skills) | Tasks 5, 6 |
| §7 Stale reference cleanup + validation | Tasks 1, 2, 7 |
| §8.3 Notes-as-memory for checkpoint | Task 8 |
| §8.7 Anti-drift validation in `config validate` | Task 2 |
| §10 Acceptance criteria verification | Task 9 |

Spec items intentionally deferred:

- `requires_mcp` frontmatter field (§8.1) — deferred to future phase (not a standard Claude Code field)
- §8.4 Adaptive Health Monitoring — adds stagger/idle timeout guidance to skills; deferred because it requires runtime metrics that don't yet exist in the ecosystem
- §8.6 Filesystem Coordination Fallback — adds MCP-unavailable degradation sections to skills; deferred because filesystem coordination infrastructure is not yet established
- Smart timeout and context mode columns are documented in Task 5/6 skill tables instead of the spec's "Use When" column — this is an intentional enhancement (Context Mode + Default Timeout are more actionable than "Use When")

### Type Consistency

- `AgentValidationReport` and `SkillValidationReport` dataclasses defined in Task 1, used in Task 2 — names match throughout.
- `DriftReport` defined in Task 2, used in Task 9 step 2.
- `validate_agent_dir` / `validate_skill_dir` return `dict[str, Report]` — used consistently in all verification steps.

### No Placeholders

All code blocks are complete and runnable. No "TBD" or "fill in later" items.
