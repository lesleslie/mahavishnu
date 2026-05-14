"""Unit tests for core.ecosystem."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

import pytest
import yaml

import mahavishnu.core.ecosystem as ecosystem_module
from mahavishnu.core.ecosystem import (
    EcosystemLoader,
    MCPServerConfig,
    RepositoryConfig,
    get_ecosystem_loader,
)
from mahavishnu.core.errors import ConfigurationError


def _base_ecosystem_dict() -> dict:
    return {
        "version": "1.0",
        "last_updated": "2026-04-08",
        "maintainer": "les",
        "description": "test ecosystem",
        "portmap": [],
        "mcp_servers": [],
        "lsp_servers": [],
        "repos": [],
        "claude_agents": {},
        "workflows": {},
        "skills": {},
        "tools": {},
        "roles": [],
        "backup": {},
        "maintenance": {},
        "claude_settings": {},
    }


def _write_config(path: Path, data: dict) -> None:
    with path.open("w") as f:
        yaml.safe_dump(data, f)


def test_repository_config_normalizes_nicknames() -> None:
    repo = RepositoryConfig(
        name="mahavishnu",
        path="/tmp/repo",
        nickname=None,
        nicknames=["vishnu", "vishnu", " mv "],
        role="orchestrator",
        description="repo",
    )
    assert repo.nicknames == ["vishnu", "mv"]
    assert repo.nickname == "vishnu"


def test_mcp_server_config_validations() -> None:
    with pytest.raises(ValueError, match="must include"):
        MCPServerConfig(
            name="s3",
            type="http",
            port=1234,
            category="core",
            function="serve",
            description="d",
            command="python -m srv",
        )

    http_server = MCPServerConfig(
        name="s4",
        type="http",
        port=1234,
        category="core",
        function="serve",
        description="d",
        command="python -m srv --port {port}",
    )
    assert http_server.get_rendered_command() == "python -m srv --port 1234"


def test_loader_load_missing_file_raises(tmp_path: Path) -> None:
    loader = EcosystemLoader(tmp_path / "missing.yaml")
    with pytest.raises(ConfigurationError, match="not found"):
        loader.load()


def test_loader_load_invalid_yaml_raises(tmp_path: Path) -> None:
    path = tmp_path / "ecosystem.yaml"
    path.write_text(":\n- [")
    loader = EcosystemLoader(path)
    with pytest.raises(ConfigurationError, match="Failed to load ecosystem configuration"):
        loader.load()


def test_loader_load_validation_error_raises(tmp_path: Path) -> None:
    path = tmp_path / "ecosystem.yaml"
    _write_config(path, {"version": "1.0"})  # missing required fields
    loader = EcosystemLoader(path)
    with pytest.raises(ConfigurationError, match="Failed to validate ecosystem configuration"):
        loader.load()


def test_config_property_requires_load(tmp_path: Path) -> None:
    loader = EcosystemLoader(tmp_path / "ecosystem.yaml")
    with pytest.raises(ConfigurationError, match="not loaded"):
        _ = loader.config


def test_get_enabled_mcp_servers_dependency_order_and_circular(tmp_path: Path) -> None:
    data = _base_ecosystem_dict()
    data["mcp_servers"] = [
        {
            "name": "a",
            "type": "http",
            "port": 9001,
            "category": "core",
            "function": "serve",
            "command": "run-a --port {port}",
            "description": "A",
            "dependencies": ["b"],
            "status": "enabled",
        },
        {
            "name": "b",
            "type": "http",
            "port": 9002,
            "category": "core",
            "function": "serve",
            "command": "run-b --port {port}",
            "description": "B",
            "dependencies": [],
            "status": "enabled",
        },
        {
            "name": "c1",
            "type": "http",
            "port": 9003,
            "category": "core",
            "function": "serve",
            "command": "run-c1 --port {port}",
            "description": "C1",
            "dependencies": ["c2"],
            "status": "enabled",
        },
        {
            "name": "c2",
            "type": "http",
            "port": 9004,
            "category": "core",
            "function": "serve",
            "command": "run-c2 --port {port}",
            "description": "C2",
            "dependencies": ["c1"],
            "status": "enabled",
        },
        {
            "name": "disabled",
            "type": "http",
            "port": 9005,
            "category": "core",
            "function": "serve",
            "command": "run-x --port {port}",
            "description": "X",
            "status": "disabled",
        },
    ]
    path = tmp_path / "ecosystem.yaml"
    _write_config(path, data)

    ordered = EcosystemLoader(path).load()
    loader = EcosystemLoader(path)
    loader._config = ordered
    names = [s.name for s in loader.get_enabled_mcp_servers()]
    assert "disabled" not in names
    assert names.index("b") < names.index("a")
    assert "c1" in names and "c2" in names


def test_generate_claude_mcp_config_and_startup_commands(tmp_path: Path) -> None:
    data = _base_ecosystem_dict()
    data["mcp_servers"] = [
        {
            "name": "ide-http",
            "type": "http",
            "port": 9101,
            "category": "core",
            "function": "serve",
            "description": "IDE",
            "command": None,
            "status": "enabled",
        },
        {
            "name": "managed-http",
            "type": "http",
            "port": 9102,
            "category": "core",
            "function": "serve",
            "description": "Managed",
            "command": "run-managed --port {port}",
            "status": "enabled",
        },
        {
            "name": "stdio-srv",
            "type": "stdio",
            "category": "core",
            "function": "serve",
            "description": "STDIO",
            "command": "python -m stdio_srv",
            "status": "enabled",
        },
    ]
    path = tmp_path / "ecosystem.yaml"
    _write_config(path, data)
    loader = EcosystemLoader(path)
    loader.load()

    cfg = loader.generate_claude_mcp_config()
    assert cfg["ide-http"]["url"].endswith("/stream")
    assert cfg["managed-http"]["url"].endswith("/mcp")
    assert cfg["stdio-srv"]["type"] == "stdio"

    startup = loader.get_startup_commands()
    assert ("managed-http", "9102", "run-managed --port 9102") in startup
    assert not any(name == "ide-http" for name, _, _ in startup)


def test_validate_catalog_references_reports_invalid_role(tmp_path: Path) -> None:
    data = _base_ecosystem_dict()
    data["roles"] = [{"name": "orchestrator"}]
    data["repos"] = [
        {
            "name": "repo-a",
            "path": "/tmp/repo-a",
            "role": "unknown-role",
            "description": "Repo A",
            "status": "active",
        }
    ]
    path = tmp_path / "ecosystem.yaml"
    _write_config(path, data)
    loader = EcosystemLoader(path)
    loader.load()

    result = loader.validate_catalog_references()

    assert result["errors"] == ["repo-a: role 'unknown-role' is not defined in roles catalog"]
    assert result["warnings"] == []


def test_validate_catalog_metadata_reports_stale_catalog_and_missing_health_check(
    tmp_path: Path,
) -> None:
    data = _base_ecosystem_dict()
    data["last_updated"] = "2026-01-01"
    data["mcp_servers"] = [
        {
            "name": "catalog-http",
            "type": "http",
            "port": 9300,
            "category": "core",
            "function": "serve",
            "command": "run-catalog --port {port}",
            "description": "Catalog server",
            "status": "enabled",
        }
    ]
    path = tmp_path / "ecosystem.yaml"
    _write_config(path, data)
    loader = EcosystemLoader(path)
    loader.load()

    result = loader.validate_catalog_metadata()

    assert any("last_updated is" in warning for warning in result["warnings"])
    assert any("missing health_check metadata" in warning for warning in result["warnings"])
    assert result["errors"] == []


def test_validate_mcp_servers_reports_errors_and_warnings(tmp_path: Path) -> None:
    existing_dir = tmp_path / "existing"
    existing_dir.mkdir()

    data = _base_ecosystem_dict()
    data["mcp_servers"] = [
        {
            "name": "one",
            "type": "http",
            "port": 9200,
            "path": str(tmp_path / "missing-path"),
            "category": "core",
            "function": "serve",
            "command": "run-one --port {port}",
            "description": "One",
            "dependencies": ["missing-dep"],
            "status": "enabled",
        },
        {
            "name": "two",
            "type": "http",
            "port": 9200,
            "path": str(existing_dir),
            "package": "definitely_not_a_real_package_123456",
            "category": "core",
            "function": "serve",
            "command": "run-two --port {port}",
            "description": "Two",
            "status": "enabled",
        },
        {
            "name": "three",
            "type": "http",
            "port": 9201,
            "category": "core",
            "function": "serve",
            "command": "run-three --port {port}",
            "description": "Three",
            "dependencies": ["disabled-dep"],
            "status": "enabled",
        },
        {
            "name": "disabled-dep",
            "type": "http",
            "port": 9202,
            "category": "core",
            "function": "serve",
            "command": "run-disabled --port {port}",
            "description": "Disabled dep",
            "status": "disabled",
        },
    ]

    path = tmp_path / "ecosystem.yaml"
    _write_config(path, data)
    loader = EcosystemLoader(path)
    loader.load()
    result = loader.validate_mcp_servers()

    assert any("Path does not exist" in e for e in result["errors"])
    assert any("not installed or not importable" in e for e in result["errors"])
    assert any("Port 9200 conflicts" in e for e in result["errors"])
    assert any("Dependency 'missing-dep' not found" in e for e in result["errors"])
    assert any("Dependency 'disabled-dep' is disabled" in w for w in result["warnings"])


def test_update_audit_timestamp_and_save(tmp_path: Path) -> None:
    data = _base_ecosystem_dict()
    data["mcp_servers"] = [
        {
            "name": "audit-me",
            "type": "http",
            "port": 9300,
            "category": "core",
            "function": "serve",
            "command": "run-audit --port {port}",
            "description": "Audit",
            "status": "enabled",
            "audit": {},
        }
    ]
    path = tmp_path / "ecosystem.yaml"
    _write_config(path, data)
    loader = EcosystemLoader(path)
    loader.load()

    loader.update_audit_timestamp("audit-me", "last_validated", "2026-04-08T00:00:00Z", "ok")
    assert loader.config.mcp_servers[0].audit["last_validated"] == "2026-04-08T00:00:00Z"
    assert loader.config.mcp_servers[0].audit["notes"] == "ok"

    loader.save()
    reloaded = yaml.safe_load(path.read_text())
    assert reloaded["mcp_servers"][0]["audit"]["last_validated"] == "2026-04-08T00:00:00Z"

    with pytest.raises(ConfigurationError, match="MCP server not found"):
        loader.update_audit_timestamp("missing", "field", "value")


def test_get_ecosystem_loader_singleton_behavior(tmp_path: Path) -> None:
    ecosystem_module._loader = None
    path = tmp_path / "ecosystem.yaml"
    _write_config(path, _base_ecosystem_dict())

    a = get_ecosystem_loader(path)
    b = get_ecosystem_loader(path)
    assert a is b
