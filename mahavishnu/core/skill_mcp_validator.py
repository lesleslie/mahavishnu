# mahavishnu/core/skill_mcp_validator.py
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml


# Canonical MCP tool registry: tool names must match exactly what the running MCP server exposes.
# Triple-underscore tools arise when FastMCP converts Python names from servers with hyphens.
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

_MCP_REF_RE = re.compile(r"mcp__[a-zA-Z\d](?:[a-zA-Z\d-]*[a-zA-Z\d])?___?[\w]+(?:__[\w]+)*")
_PORT_RE = re.compile(r"\b(crackerjack|session[_-]buddy|mahavishnu|akosha|dhara)\b[^.\n]*?\bport\s+(\d{4,5})", re.IGNORECASE)


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
