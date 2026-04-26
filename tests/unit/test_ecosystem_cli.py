"""Unit tests for mahavishnu.ecosystem_cli."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import typer
from typer.testing import CliRunner

from mahavishnu.core.errors import ConfigurationError
from mahavishnu.ecosystem_cli import add_ecosystem_commands

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_mcp_server(
    name: str = "session-buddy",
    category: str = "core",
    status: str = "enabled",
    port: int | None = 8680,
    function: str = "Session management",
    type: str = "http",
    maintainer: str = "les",
    command: str = "mahavishnu mcp start",
    audit: dict | None = None,
    repo_url: str | None = "https://github.com/lesleslie/session-buddy",
    homepage_url: str | None = "https://session-buddy.dev",
    docs_url: str | None = "https://docs.session-buddy.dev",
    urls: dict | None = None,
) -> MagicMock:
    server = MagicMock()
    server.name = name
    server.category = category
    server.status = status
    server.port = port
    server.function = function
    server.type = type
    server.maintainer = maintainer
    server.command = command
    server.audit = audit or {}
    server.repo_url = repo_url
    server.homepage_url = homepage_url
    server.docs_url = docs_url
    server.urls = urls or {}
    return server


def _make_mock_repo(
    name: str = "session-buddy",
    repo_url: str | None = "https://github.com/lesleslie/session-buddy",
    homepage_url: str | None = "https://session-buddy.dev",
    docs_url: str | None = "https://docs.session-buddy.dev",
    urls: dict | None = None,
) -> MagicMock:
    repo = MagicMock()
    repo.name = name
    repo.repo_url = repo_url
    repo.homepage_url = homepage_url
    repo.docs_url = docs_url
    repo.urls = urls or {}
    return repo


def _make_mock_lsp_server(
    name: str = "pylsp",
    language: str = "python",
    type: str = "stdio",
    enabled: bool = True,
    description: str = "Python language server",
    command: str = "pylsp",
    args: list | None = None,
    config_file: str | None = "/path/to/config",
    config_section: str | None = "pylsp",
    repo_url: str | None = "https://github.com/python-lsp/python-lsp-server",
    docs_url: str | None = "https://pylsp.readthedocs.io",
    urls: dict | None = None,
    audit: dict | None = None,
) -> dict:
    return {
        "name": name,
        "language": language,
        "type": type,
        "enabled": enabled,
        "description": description,
        "command": command,
        "args": args or [],
        "config_file": config_file,
        "config_section": config_section,
        "repo_url": repo_url,
        "docs_url": docs_url,
        "urls": urls or {},
        "audit": audit or {},
    }


def _make_mock_portmap_entry(
    port: int = 8680,
    service: str = "mahavishnu",
    type: str = "MCP",
    category: str = "orchestration",
    protocol: str = "HTTP",
    status: str = "enabled",
    description: str = "Orchestration server",
) -> dict:
    return {
        "port": port,
        "service": service,
        "type": type,
        "category": category,
        "protocol": protocol,
        "status": status,
        "description": description,
    }


def _build_mock_loader(
    mcp_servers: list | None = None,
    repos: list | None = None,
    lsp_servers: list | None = None,
    portmap: list | None = None,
) -> MagicMock:
    loader = MagicMock()
    loader.config = MagicMock()
    loader.config.mcp_servers = mcp_servers or []
    loader.config.repos = repos or []
    loader.config.lsp_servers = lsp_servers or []
    loader.config.portmap = portmap or []
    return loader


def _make_app() -> typer.Typer:
    app = typer.Typer()
    add_ecosystem_commands(app)
    return app


# ---------------------------------------------------------------------------
# add_ecosystem_commands — registration tests
# ---------------------------------------------------------------------------


class TestAddEcosystemCommands:
    def test_registers_ecosystem_sub_app(self) -> None:
        parent = typer.Typer()
        sub_app = typer.Typer()
        parent.add_typer(sub_app, name="ecosystem")
        add_ecosystem_commands(sub_app)

        result = runner.invoke(parent, ["ecosystem", "--help"])
        assert result.exit_code == 0

    def test_registers_validate_command(self) -> None:
        app = _make_app()
        result = runner.invoke(app, ["validate", "--help"])
        assert result.exit_code == 0
        assert "validate" in result.output.lower()

    def test_registers_list_command(self) -> None:
        app = _make_app()
        result = runner.invoke(app, ["list", "--help"])
        assert result.exit_code == 0

    def test_registers_audit_command(self) -> None:
        app = _make_app()
        result = runner.invoke(app, ["audit", "--help"])
        assert result.exit_code == 0

    def test_registers_urls_command(self) -> None:
        app = _make_app()
        result = runner.invoke(app, ["urls", "--help"])
        assert result.exit_code == 0

    def test_registers_repo_urls_command(self) -> None:
        app = _make_app()
        result = runner.invoke(app, ["repo-urls", "--help"])
        assert result.exit_code == 0

    def test_registers_list_lsp_command(self) -> None:
        app = _make_app()
        result = runner.invoke(app, ["list-lsp", "--help"])
        assert result.exit_code == 0

    def test_registers_lsp_info_command(self) -> None:
        app = _make_app()
        result = runner.invoke(app, ["lsp-info", "--help"])
        assert result.exit_code == 0

    def test_registers_ports_command(self) -> None:
        app = _make_app()
        result = runner.invoke(app, ["ports", "--help"])
        assert result.exit_code == 0

    def test_registers_update_audit_command(self) -> None:
        app = _make_app()
        result = runner.invoke(app, ["update-audit", "--help"])
        assert result.exit_code == 0

    def test_registers_generate_claude_config_command(self) -> None:
        app = _make_app()
        result = runner.invoke(app, ["generate-claude-config", "--help"])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# validate command
# ---------------------------------------------------------------------------


class TestValidateCommand:
    @patch("mahavishnu.ecosystem_cli.get_ecosystem_loader")
    def test_valid_config_no_errors(self, mock_get_loader: MagicMock) -> None:
        loader = _build_mock_loader()
        loader.validate_mcp_servers.return_value = {"errors": [], "warnings": []}
        mock_get_loader.return_value = loader

        app = _make_app()
        result = runner.invoke(app, ["validate"])
        assert result.exit_code == 0
        assert "valid" in result.output.lower()

    @patch("mahavishnu.ecosystem_cli.get_ecosystem_loader")
    def test_valid_config_with_warnings(self, mock_get_loader: MagicMock) -> None:
        loader = _build_mock_loader()
        loader.validate_mcp_servers.return_value = {
            "errors": [],
            "warnings": ["Server 'x' has no health check"],
        }
        mock_get_loader.return_value = loader

        app = _make_app()
        result = runner.invoke(app, ["validate"])
        assert result.exit_code == 0
        assert "warnings" in result.output.lower()
        assert "no health check" in result.output.lower()

    @patch("mahavishnu.ecosystem_cli.get_ecosystem_loader")
    def test_invalid_config_with_errors(self, mock_get_loader: MagicMock) -> None:
        loader = _build_mock_loader()
        loader.validate_mcp_servers.return_value = {
            "errors": ["Missing required field 'port' for server 'x'"],
            "warnings": [],
        }
        mock_get_loader.return_value = loader

        app = _make_app()
        result = runner.invoke(app, ["validate"])
        assert result.exit_code == 1
        assert "missing required field" in result.output.lower()

    @patch("mahavishnu.ecosystem_cli.get_ecosystem_loader")
    def test_invalid_config_with_errors_and_warnings(
        self, mock_get_loader: MagicMock
    ) -> None:
        loader = _build_mock_loader()
        loader.validate_mcp_servers.return_value = {
            "errors": ["Bad config"],
            "warnings": ["Deprecation notice"],
        }
        mock_get_loader.return_value = loader

        app = _make_app()
        result = runner.invoke(app, ["validate"])
        assert result.exit_code == 1
        assert "bad config" in result.output.lower()
        assert "deprecation notice" in result.output.lower()

    @patch("mahavishnu.ecosystem_cli.get_ecosystem_loader")
    def test_configuration_error(self, mock_get_loader: MagicMock) -> None:
        mock_get_loader.side_effect = ConfigurationError("config file missing")

        app = _make_app()
        result = runner.invoke(app, ["validate"])
        assert result.exit_code == 1
        assert "configuration error" in result.output.lower()
        assert "config file missing" in result.output.lower()


# ---------------------------------------------------------------------------
# list command
# ---------------------------------------------------------------------------


class TestListCommand:
    @patch("mahavishnu.ecosystem_cli.get_ecosystem_loader")
    def test_list_all_servers(self, mock_get_loader: MagicMock) -> None:
        servers = [
            _make_mock_mcp_server(name="alpha", category="core"),
            _make_mock_mcp_server(name="beta", category="tool"),
        ]
        mock_get_loader.return_value = _build_mock_loader(mcp_servers=servers)

        app = _make_app()
        result = runner.invoke(app, ["list"])
        assert result.exit_code == 0
        assert "alpha" in result.output
        assert "beta" in result.output

    @patch("mahavishnu.ecosystem_cli.get_ecosystem_loader")
    def test_list_with_category_filter(self, mock_get_loader: MagicMock) -> None:
        servers = [
            _make_mock_mcp_server(name="alpha", category="core"),
            _make_mock_mcp_server(name="beta", category="tool"),
        ]
        mock_get_loader.return_value = _build_mock_loader(mcp_servers=servers)

        app = _make_app()
        result = runner.invoke(app, ["list", "--category", "core"])
        assert result.exit_code == 0
        assert "alpha" in result.output
        assert "beta" not in result.output

    @patch("mahavishnu.ecosystem_cli.get_ecosystem_loader")
    def test_list_with_status_filter(self, mock_get_loader: MagicMock) -> None:
        servers = [
            _make_mock_mcp_server(name="alpha", status="enabled"),
            _make_mock_mcp_server(name="beta", status="disabled"),
        ]
        mock_get_loader.return_value = _build_mock_loader(mcp_servers=servers)

        app = _make_app()
        result = runner.invoke(app, ["list", "--status", "enabled"])
        assert result.exit_code == 0
        assert "alpha" in result.output
        assert "beta" not in result.output

    @patch("mahavishnu.ecosystem_cli.get_ecosystem_loader")
    def test_list_groups_by_category(self, mock_get_loader: MagicMock) -> None:
        servers = [
            _make_mock_mcp_server(name="a-server", category="core"),
            _make_mock_mcp_server(name="b-server", category="core"),
            _make_mock_mcp_server(name="c-server", category="tool"),
        ]
        mock_get_loader.return_value = _build_mock_loader(mcp_servers=servers)

        app = _make_app()
        result = runner.invoke(app, ["list"])
        assert result.exit_code == 0
        assert "CORE" in result.output
        assert "TOOL" in result.output
        # Category header should show count
        assert "2 servers" in result.output

    @patch("mahavishnu.ecosystem_cli.get_ecosystem_loader")
    def test_list_shows_port_or_stdio(self, mock_get_loader: MagicMock) -> None:
        servers = [
            _make_mock_mcp_server(name="with-port", port=8680),
            _make_mock_mcp_server(name="no-port", port=None),
        ]
        mock_get_loader.return_value = _build_mock_loader(mcp_servers=servers)

        app = _make_app()
        result = runner.invoke(app, ["list"])
        assert result.exit_code == 0
        assert ":8680" in result.output
        assert "stdio" in result.output

    @patch("mahavishnu.ecosystem_cli.get_ecosystem_loader")
    def test_list_configuration_error(self, mock_get_loader: MagicMock) -> None:
        mock_get_loader.side_effect = ConfigurationError("bad config")

        app = _make_app()
        result = runner.invoke(app, ["list"])
        assert result.exit_code == 1
        assert "configuration error" in result.output.lower()

    @patch("mahavishnu.ecosystem_cli.get_ecosystem_loader")
    def test_list_short_category_flag(self, mock_get_loader: MagicMock) -> None:
        servers = [
            _make_mock_mcp_server(name="alpha", category="core"),
            _make_mock_mcp_server(name="beta", category="tool"),
        ]
        mock_get_loader.return_value = _build_mock_loader(mcp_servers=servers)

        app = _make_app()
        result = runner.invoke(app, ["list", "-c", "tool"])
        assert result.exit_code == 0
        assert "beta" in result.output
        assert "alpha" not in result.output

    @patch("mahavishnu.ecosystem_cli.get_ecosystem_loader")
    def test_list_short_status_flag(self, mock_get_loader: MagicMock) -> None:
        servers = [
            _make_mock_mcp_server(name="alpha", status="enabled"),
            _make_mock_mcp_server(name="beta", status="disabled"),
        ]
        mock_get_loader.return_value = _build_mock_loader(mcp_servers=servers)

        app = _make_app()
        result = runner.invoke(app, ["list", "-s", "disabled"])
        assert result.exit_code == 0
        assert "beta" in result.output
        assert "alpha" not in result.output


# ---------------------------------------------------------------------------
# audit command
# ---------------------------------------------------------------------------


class TestAuditCommand:
    @patch("mahavishnu.ecosystem_cli.get_ecosystem_loader")
    def test_audit_specific_server(self, mock_get_loader: MagicMock) -> None:
        audit_data = {"last_validated": "2026-04-01", "last_tested": "2026-04-15"}
        servers = [
            _make_mock_mcp_server(
                name="session-buddy",
                audit=audit_data,
            ),
        ]
        mock_get_loader.return_value = _build_mock_loader(mcp_servers=servers)

        app = _make_app()
        result = runner.invoke(app, ["audit", "session-buddy"])
        assert result.exit_code == 0
        assert "session-buddy" in result.output
        assert "last_validated" in result.output
        assert "2026-04-01" in result.output

    @patch("mahavishnu.ecosystem_cli.get_ecosystem_loader")
    def test_audit_all_servers(self, mock_get_loader: MagicMock) -> None:
        servers = [
            _make_mock_mcp_server(name="server-a"),
            _make_mock_mcp_server(name="server-b"),
        ]
        mock_get_loader.return_value = _build_mock_loader(mcp_servers=servers)

        app = _make_app()
        result = runner.invoke(app, ["audit"])
        assert result.exit_code == 0
        assert "server-a" in result.output
        assert "server-b" in result.output

    @patch("mahavishnu.ecosystem_cli.get_ecosystem_loader")
    def test_audit_server_not_found(self, mock_get_loader: MagicMock) -> None:
        servers = [
            _make_mock_mcp_server(name="exists"),
        ]
        mock_get_loader.return_value = _build_mock_loader(mcp_servers=servers)

        app = _make_app()
        result = runner.invoke(app, ["audit", "nonexistent"])
        assert result.exit_code == 1
        assert "server not found" in result.output.lower()
        assert "nonexistent" in result.output

    @patch("mahavishnu.ecosystem_cli.get_ecosystem_loader")
    def test_audit_shows_port_when_present(self, mock_get_loader: MagicMock) -> None:
        servers = [
            _make_mock_mcp_server(name="with-port", port=8680),
        ]
        mock_get_loader.return_value = _build_mock_loader(mcp_servers=servers)

        app = _make_app()
        result = runner.invoke(app, ["audit", "with-port"])
        assert result.exit_code == 0
        assert "Port:" in result.output
        assert "8680" in result.output

    @patch("mahavishnu.ecosystem_cli.get_ecosystem_loader")
    def test_audit_omits_port_when_none(self, mock_get_loader: MagicMock) -> None:
        servers = [
            _make_mock_mcp_server(name="no-port", port=None),
        ]
        mock_get_loader.return_value = _build_mock_loader(mcp_servers=servers)

        app = _make_app()
        result = runner.invoke(app, ["audit", "no-port"])
        assert result.exit_code == 0
        assert "Port:" not in result.output

    @patch("mahavishnu.ecosystem_cli.get_ecosystem_loader")
    def test_audit_configuration_error(self, mock_get_loader: MagicMock) -> None:
        mock_get_loader.side_effect = ConfigurationError("load failure")

        app = _make_app()
        result = runner.invoke(app, ["audit", "any"])
        assert result.exit_code == 1
        assert "configuration error" in result.output.lower()


# ---------------------------------------------------------------------------
# urls command
# ---------------------------------------------------------------------------


class TestUrlsCommand:
    @patch("mahavishnu.ecosystem_cli.get_ecosystem_loader")
    def test_urls_server_with_all_fields(self, mock_get_loader: MagicMock) -> None:
        extra_urls = {"issues": "https://github.com/foo/issues", "wiki": "https://wiki.foo"}
        servers = [
            _make_mock_mcp_server(
                name="my-server",
                repo_url="https://github.com/foo/bar",
                homepage_url="https://foo.dev",
                docs_url="https://docs.foo.dev",
                urls=extra_urls,
            ),
        ]
        mock_get_loader.return_value = _build_mock_loader(mcp_servers=servers)

        app = _make_app()
        result = runner.invoke(app, ["urls", "my-server"])
        assert result.exit_code == 0
        assert "Repository:" in result.output
        assert "https://github.com/foo/bar" in result.output
        assert "Homepage:" in result.output
        assert "Documentation:" in result.output
        assert "issues" in result.output
        assert "wiki" in result.output

    @patch("mahavishnu.ecosystem_cli.get_ecosystem_loader")
    def test_urls_server_not_found(self, mock_get_loader: MagicMock) -> None:
        mock_get_loader.return_value = _build_mock_loader(mcp_servers=[])

        app = _make_app()
        result = runner.invoke(app, ["urls", "nonexistent"])
        assert result.exit_code == 1
        assert "server not found" in result.output.lower()

    @patch("mahavishnu.ecosystem_cli.get_ecosystem_loader")
    def test_urls_server_no_urls_configured(self, mock_get_loader: MagicMock) -> None:
        servers = [
            _make_mock_mcp_server(
                name="empty",
                repo_url=None,
                homepage_url=None,
                docs_url=None,
                urls={},
            ),
        ]
        mock_get_loader.return_value = _build_mock_loader(mcp_servers=servers)

        app = _make_app()
        result = runner.invoke(app, ["urls", "empty"])
        assert result.exit_code == 0
        assert "no urls configured" in result.output.lower()

    @patch("mahavishnu.ecosystem_cli.get_ecosystem_loader")
    def test_urls_configuration_error(self, mock_get_loader: MagicMock) -> None:
        mock_get_loader.side_effect = ConfigurationError("bad config")

        app = _make_app()
        result = runner.invoke(app, ["urls", "any"])
        assert result.exit_code == 1
        assert "configuration error" in result.output.lower()


# ---------------------------------------------------------------------------
# repo-urls command
# ---------------------------------------------------------------------------


class TestRepoUrlsCommand:
    @patch("mahavishnu.ecosystem_cli.get_ecosystem_loader")
    def test_repo_urls_found(self, mock_get_loader: MagicMock) -> None:
        extra_urls = {"releases": "https://github.com/foo/releases"}
        repos = [
            _make_mock_repo(
                name="my-repo",
                repo_url="https://github.com/foo/my-repo",
                homepage_url="https://my-repo.dev",
                docs_url="https://docs.my-repo.dev",
                urls=extra_urls,
            ),
        ]
        mock_get_loader.return_value = _build_mock_loader(repos=repos)

        app = _make_app()
        result = runner.invoke(app, ["repo-urls", "my-repo"])
        assert result.exit_code == 0
        assert "Repository:" in result.output
        assert "https://github.com/foo/my-repo" in result.output
        assert "Homepage:" in result.output
        assert "Documentation:" in result.output
        assert "releases" in result.output

    @patch("mahavishnu.ecosystem_cli.get_ecosystem_loader")
    def test_repo_urls_not_found(self, mock_get_loader: MagicMock) -> None:
        mock_get_loader.return_value = _build_mock_loader(repos=[])

        app = _make_app()
        result = runner.invoke(app, ["repo-urls", "nonexistent"])
        assert result.exit_code == 1
        assert "repository not found" in result.output.lower()

    @patch("mahavishnu.ecosystem_cli.get_ecosystem_loader")
    def test_repo_urls_no_urls_configured(self, mock_get_loader: MagicMock) -> None:
        repos = [
            _make_mock_repo(
                name="empty-repo",
                repo_url=None,
                homepage_url=None,
                docs_url=None,
                urls={},
            ),
        ]
        mock_get_loader.return_value = _build_mock_loader(repos=repos)

        app = _make_app()
        result = runner.invoke(app, ["repo-urls", "empty-repo"])
        assert result.exit_code == 0
        assert "no urls configured" in result.output.lower()

    @patch("mahavishnu.ecosystem_cli.get_ecosystem_loader")
    def test_repo_urls_configuration_error(self, mock_get_loader: MagicMock) -> None:
        mock_get_loader.side_effect = ConfigurationError("load failure")

        app = _make_app()
        result = runner.invoke(app, ["repo-urls", "any"])
        assert result.exit_code == 1
        assert "configuration error" in result.output.lower()


# ---------------------------------------------------------------------------
# list-lsp command
# ---------------------------------------------------------------------------


class TestListLspCommand:
    @patch("mahavishnu.ecosystem_cli.get_ecosystem_loader")
    def test_list_all_lsp_servers(self, mock_get_loader: MagicMock) -> None:
        lsp_servers = [
            _make_mock_lsp_server(name="pylsp", language="python"),
            _make_mock_lsp_server(name="typescript-language-server", language="typescript"),
        ]
        mock_get_loader.return_value = _build_mock_loader(lsp_servers=lsp_servers)

        app = _make_app()
        result = runner.invoke(app, ["list-lsp"])
        assert result.exit_code == 0
        assert "pylsp" in result.output
        assert "typescript-language-server" in result.output

    @patch("mahavishnu.ecosystem_cli.get_ecosystem_loader")
    def test_list_lsp_with_language_filter(self, mock_get_loader: MagicMock) -> None:
        lsp_servers = [
            _make_mock_lsp_server(name="pylsp", language="python"),
            _make_mock_lsp_server(name="gopls", language="go"),
        ]
        mock_get_loader.return_value = _build_mock_loader(lsp_servers=lsp_servers)

        app = _make_app()
        result = runner.invoke(app, ["list-lsp", "--language", "python"])
        assert result.exit_code == 0
        assert "pylsp" in result.output
        assert "gopls" not in result.output

    @patch("mahavishnu.ecosystem_cli.get_ecosystem_loader")
    def test_list_lsp_with_enabled_filter(self, mock_get_loader: MagicMock) -> None:
        lsp_servers = [
            _make_mock_lsp_server(name="pylsp", enabled=True),
            _make_mock_lsp_server(name="old-lsp", enabled=False),
        ]
        mock_get_loader.return_value = _build_mock_loader(lsp_servers=lsp_servers)

        app = _make_app()
        result = runner.invoke(app, ["list-lsp", "--enabled", "true"])
        assert result.exit_code == 0
        assert "pylsp" in result.output
        assert "old-lsp" not in result.output

    @patch("mahavishnu.ecosystem_cli.get_ecosystem_loader")
    def test_list_lsp_with_disabled_filter(self, mock_get_loader: MagicMock) -> None:
        lsp_servers = [
            _make_mock_lsp_server(name="pylsp", enabled=True),
            _make_mock_lsp_server(name="old-lsp", enabled=False),
        ]
        mock_get_loader.return_value = _build_mock_loader(lsp_servers=lsp_servers)

        app = _make_app()
        result = runner.invoke(app, ["list-lsp", "--enabled", "false"])
        assert result.exit_code == 0
        assert "old-lsp" in result.output
        assert "pylsp" not in result.output

    @patch("mahavishnu.ecosystem_cli.get_ecosystem_loader")
    def test_list_lsp_groups_by_language(self, mock_get_loader: MagicMock) -> None:
        lsp_servers = [
            _make_mock_lsp_server(name="pylsp", language="python"),
            _make_mock_lsp_server(name="ruff-lsp", language="python"),
            _make_mock_lsp_server(name="gopls", language="go"),
        ]
        mock_get_loader.return_value = _build_mock_loader(lsp_servers=lsp_servers)

        app = _make_app()
        result = runner.invoke(app, ["list-lsp"])
        assert result.exit_code == 0
        assert "PYTHON" in result.output
        assert "GO" in result.output
        assert "2 servers" in result.output

    @patch("mahavishnu.ecosystem_cli.get_ecosystem_loader")
    def test_list_lsp_short_language_flag(self, mock_get_loader: MagicMock) -> None:
        lsp_servers = [
            _make_mock_lsp_server(name="pylsp", language="python"),
            _make_mock_lsp_server(name="gopls", language="go"),
        ]
        mock_get_loader.return_value = _build_mock_loader(lsp_servers=lsp_servers)

        app = _make_app()
        result = runner.invoke(app, ["list-lsp", "-l", "go"])
        assert result.exit_code == 0
        assert "gopls" in result.output
        assert "pylsp" not in result.output

    @patch("mahavishnu.ecosystem_cli.get_ecosystem_loader")
    def test_list_lsp_configuration_error(self, mock_get_loader: MagicMock) -> None:
        mock_get_loader.side_effect = ConfigurationError("bad config")

        app = _make_app()
        result = runner.invoke(app, ["list-lsp"])
        assert result.exit_code == 1
        assert "configuration error" in result.output.lower()


# ---------------------------------------------------------------------------
# lsp-info command
# ---------------------------------------------------------------------------


class TestLspInfoCommand:
    @patch("mahavishnu.ecosystem_cli.get_ecosystem_loader")
    def test_lsp_info_specific_server(self, mock_get_loader: MagicMock) -> None:
        lsp_servers = [
            _make_mock_lsp_server(
                name="pylsp",
                language="python",
                repo_url="https://github.com/python-lsp/python-lsp-server",
                docs_url="https://pylsp.readthedocs.io",
            ),
        ]
        mock_get_loader.return_value = _build_mock_loader(lsp_servers=lsp_servers)

        app = _make_app()
        result = runner.invoke(app, ["lsp-info", "pylsp"])
        assert result.exit_code == 0
        assert "pylsp" in result.output
        assert "python" in result.output.lower()
        assert "Repository:" in result.output
        assert "Documentation:" in result.output

    @patch("mahavishnu.ecosystem_cli.get_ecosystem_loader")
    def test_lsp_info_all_servers(self, mock_get_loader: MagicMock) -> None:
        lsp_servers = [
            _make_mock_lsp_server(name="pylsp", language="python"),
            _make_mock_lsp_server(name="gopls", language="go"),
        ]
        mock_get_loader.return_value = _build_mock_loader(lsp_servers=lsp_servers)

        app = _make_app()
        result = runner.invoke(app, ["lsp-info"])
        assert result.exit_code == 0
        assert "pylsp" in result.output
        assert "gopls" in result.output

    @patch("mahavishnu.ecosystem_cli.get_ecosystem_loader")
    def test_lsp_info_not_found(self, mock_get_loader: MagicMock) -> None:
        lsp_servers = [
            _make_mock_lsp_server(name="pylsp"),
        ]
        mock_get_loader.return_value = _build_mock_loader(lsp_servers=lsp_servers)

        app = _make_app()
        result = runner.invoke(app, ["lsp-info", "nonexistent"])
        assert result.exit_code == 1
        assert "lsp server not found" in result.output.lower()

    @patch("mahavishnu.ecosystem_cli.get_ecosystem_loader")
    def test_lsp_info_shows_status(self, mock_get_loader: MagicMock) -> None:
        lsp_servers = [
            _make_mock_lsp_server(name="enabled-lsp", enabled=True),
            _make_mock_lsp_server(name="disabled-lsp", enabled=False),
        ]
        mock_get_loader.return_value = _build_mock_loader(lsp_servers=lsp_servers)

        app = _make_app()
        result = runner.invoke(app, ["lsp-info"])
        assert result.exit_code == 0
        assert "enabled" in result.output
        assert "disabled" in result.output

    @patch("mahavishnu.ecosystem_cli.get_ecosystem_loader")
    def test_lsp_info_with_additional_urls(self, mock_get_loader: MagicMock) -> None:
        extra_urls = {"changelog": "https://github.com/foo/changelog"}
        lsp_servers = [
            _make_mock_lsp_server(name="pylsp", urls=extra_urls),
        ]
        mock_get_loader.return_value = _build_mock_loader(lsp_servers=lsp_servers)

        app = _make_app()
        result = runner.invoke(app, ["lsp-info", "pylsp"])
        assert result.exit_code == 0
        assert "Additional URLs:" in result.output
        assert "changelog" in result.output

    @patch("mahavishnu.ecosystem_cli.get_ecosystem_loader")
    def test_lsp_info_with_audit(self, mock_get_loader: MagicMock) -> None:
        audit_data = {"last_validated": "2026-04-01"}
        lsp_servers = [
            _make_mock_lsp_server(name="pylsp", audit=audit_data),
        ]
        mock_get_loader.return_value = _build_mock_loader(lsp_servers=lsp_servers)

        app = _make_app()
        result = runner.invoke(app, ["lsp-info", "pylsp"])
        assert result.exit_code == 0
        assert "Audit History:" in result.output
        assert "last_validated" in result.output

    @patch("mahavishnu.ecosystem_cli.get_ecosystem_loader")
    def test_lsp_info_config_defaults(self, mock_get_loader: MagicMock) -> None:
        lsp_servers = [
            _make_mock_lsp_server(
                name="minimal-lsp",
                config_file=None,
                config_section=None,
            ),
        ]
        mock_get_loader.return_value = _build_mock_loader(lsp_servers=lsp_servers)

        app = _make_app()
        result = runner.invoke(app, ["lsp-info", "minimal-lsp"])
        assert result.exit_code == 0
        assert "N/A" in result.output

    @patch("mahavishnu.ecosystem_cli.get_ecosystem_loader")
    def test_lsp_info_configuration_error(self, mock_get_loader: MagicMock) -> None:
        mock_get_loader.side_effect = ConfigurationError("bad config")

        app = _make_app()
        result = runner.invoke(app, ["lsp-info", "any"])
        assert result.exit_code == 1
        assert "configuration error" in result.output.lower()


# ---------------------------------------------------------------------------
# ports command
# ---------------------------------------------------------------------------


class TestPortsCommand:
    @patch("mahavishnu.ecosystem_cli.get_ecosystem_loader")
    def test_ports_lists_all(self, mock_get_loader: MagicMock) -> None:
        portmap = [
            _make_mock_portmap_entry(port=8680, service="mahavishnu"),
            _make_mock_portmap_entry(port=3032, service="excalidraw", type="WebSocket"),
        ]
        mock_get_loader.return_value = _build_mock_loader(portmap=portmap)

        app = _make_app()
        result = runner.invoke(app, ["ports"])
        assert result.exit_code == 0
        assert "8680" in result.output
        assert "3032" in result.output
        assert "mahavishnu" in result.output
        assert "excalidraw" in result.output

    @patch("mahavishnu.ecosystem_cli.get_ecosystem_loader")
    def test_ports_with_type_filter(self, mock_get_loader: MagicMock) -> None:
        portmap = [
            _make_mock_portmap_entry(port=8680, type="MCP"),
            _make_mock_portmap_entry(port=3032, type="WebSocket"),
        ]
        mock_get_loader.return_value = _build_mock_loader(portmap=portmap)

        app = _make_app()
        result = runner.invoke(app, ["ports", "--type", "MCP"])
        assert result.exit_code == 0
        assert "8680" in result.output
        assert "3032" not in result.output

    @patch("mahavishnu.ecosystem_cli.get_ecosystem_loader")
    def test_ports_with_status_filter(self, mock_get_loader: MagicMock) -> None:
        portmap = [
            _make_mock_portmap_entry(port=8680, status="enabled"),
            _make_mock_portmap_entry(port=9999, status="disabled"),
        ]
        mock_get_loader.return_value = _build_mock_loader(portmap=portmap)

        app = _make_app()
        result = runner.invoke(app, ["ports", "--status", "enabled"])
        assert result.exit_code == 0
        assert "8680" in result.output
        assert "mahavishnu" in result.output
        assert "Total: 1 ports" in result.output

    @patch("mahavishnu.ecosystem_cli.get_ecosystem_loader")
    def test_ports_empty_results(self, mock_get_loader: MagicMock) -> None:
        mock_get_loader.return_value = _build_mock_loader(portmap=[])

        app = _make_app()
        result = runner.invoke(app, ["ports"])
        assert result.exit_code == 0
        assert "no port mappings found" in result.output.lower()

    @patch("mahavishnu.ecosystem_cli.get_ecosystem_loader")
    def test_ports_filter_yields_empty(self, mock_get_loader: MagicMock) -> None:
        portmap = [
            _make_mock_portmap_entry(port=8680, type="MCP"),
        ]
        mock_get_loader.return_value = _build_mock_loader(portmap=portmap)

        app = _make_app()
        result = runner.invoke(app, ["ports", "--type", "LSP"])
        assert result.exit_code == 0
        assert "no port mappings found" in result.output.lower()

    @patch("mahavishnu.ecosystem_cli.get_ecosystem_loader")
    def test_ports_shows_summary(self, mock_get_loader: MagicMock) -> None:
        portmap = [
            _make_mock_portmap_entry(port=8680, status="enabled"),
            _make_mock_portmap_entry(port=8678, status="enabled"),
            _make_mock_portmap_entry(port=9999, status="disabled"),
        ]
        mock_get_loader.return_value = _build_mock_loader(portmap=portmap)

        app = _make_app()
        result = runner.invoke(app, ["ports"])
        assert result.exit_code == 0
        assert "Total: 3 ports" in result.output
        assert "Enabled: 2" in result.output
        assert "Disabled: 1" in result.output

    @patch("mahavishnu.ecosystem_cli.get_ecosystem_loader")
    def test_ports_infrastructure_grouping(self, mock_get_loader: MagicMock) -> None:
        portmap = [
            _make_mock_portmap_entry(port=8680, service="mahavishnu"),
            _make_mock_portmap_entry(port=3032, service="excalidraw"),
        ]
        mock_get_loader.return_value = _build_mock_loader(portmap=portmap)

        app = _make_app()
        result = runner.invoke(app, ["ports"])
        assert result.exit_code == 0
        assert "INFRASTRUCTURE" in result.output
        assert "TOOLS" in result.output

    @patch("mahavishnu.ecosystem_cli.get_ecosystem_loader")
    def test_ports_short_type_flag(self, mock_get_loader: MagicMock) -> None:
        portmap = [
            _make_mock_portmap_entry(port=8680, type="MCP"),
            _make_mock_portmap_entry(port=3032, type="WebSocket"),
        ]
        mock_get_loader.return_value = _build_mock_loader(portmap=portmap)

        app = _make_app()
        result = runner.invoke(app, ["ports", "-t", "WebSocket"])
        assert result.exit_code == 0
        assert "3032" in result.output
        assert "8680" not in result.output

    @patch("mahavishnu.ecosystem_cli.get_ecosystem_loader")
    def test_ports_short_status_flag(self, mock_get_loader: MagicMock) -> None:
        portmap = [
            _make_mock_portmap_entry(port=8680, status="enabled"),
            _make_mock_portmap_entry(port=9999, status="disabled"),
        ]
        mock_get_loader.return_value = _build_mock_loader(portmap=portmap)

        app = _make_app()
        result = runner.invoke(app, ["ports", "-s", "disabled"])
        assert result.exit_code == 0
        assert "9999" in result.output
        assert "8680" not in result.output

    @patch("mahavishnu.ecosystem_cli.get_ecosystem_loader")
    def test_ports_configuration_error(self, mock_get_loader: MagicMock) -> None:
        mock_get_loader.side_effect = ConfigurationError("bad config")

        app = _make_app()
        result = runner.invoke(app, ["ports"])
        assert result.exit_code == 1
        assert "configuration error" in result.output.lower()


# ---------------------------------------------------------------------------
# update-audit command
# ---------------------------------------------------------------------------


class TestUpdateAuditCommand:
    @patch("mahavishnu.ecosystem_cli.get_ecosystem_loader")
    def test_successful_update(self, mock_get_loader: MagicMock) -> None:
        loader = _build_mock_loader()
        mock_get_loader.return_value = loader

        app = _make_app()
        result = runner.invoke(
            app,
            ["update-audit", "session-buddy", "last_validated", "2026-04-24"],
        )
        assert result.exit_code == 0
        assert "updated audit info" in result.output.lower()
        assert "session-buddy" in result.output
        assert "last_validated" in result.output
        assert "2026-04-24" in result.output
        loader.update_audit_timestamp.assert_called_once_with(
            "session-buddy", "last_validated", "2026-04-24", None
        )
        loader.save.assert_called_once()

    @patch("mahavishnu.ecosystem_cli.get_ecosystem_loader")
    def test_successful_update_with_notes(self, mock_get_loader: MagicMock) -> None:
        loader = _build_mock_loader()
        mock_get_loader.return_value = loader

        app = _make_app()
        result = runner.invoke(
            app,
            [
                "update-audit",
                "session-buddy",
                "last_tested",
                "2026-04-24",
                "--notes",
                "All checks passed",
            ],
        )
        assert result.exit_code == 0
        assert "notes:" in result.output.lower()
        assert "all checks passed" in result.output.lower()
        loader.update_audit_timestamp.assert_called_once_with(
            "session-buddy", "last_tested", "2026-04-24", "All checks passed"
        )

    @patch("mahavishnu.ecosystem_cli.get_ecosystem_loader")
    def test_successful_update_short_notes_flag(
        self, mock_get_loader: MagicMock
    ) -> None:
        loader = _build_mock_loader()
        mock_get_loader.return_value = loader

        app = _make_app()
        result = runner.invoke(
            app,
            [
                "update-audit",
                "session-buddy",
                "last_tested",
                "2026-04-24",
                "-n",
                "Quick note",
            ],
        )
        assert result.exit_code == 0
        loader.update_audit_timestamp.assert_called_once_with(
            "session-buddy", "last_tested", "2026-04-24", "Quick note"
        )

    @patch("mahavishnu.ecosystem_cli.get_ecosystem_loader")
    def test_configuration_error(self, mock_get_loader: MagicMock) -> None:
        mock_get_loader.side_effect = ConfigurationError("config error")

        app = _make_app()
        result = runner.invoke(
            app,
            ["update-audit", "session-buddy", "last_validated", "2026-04-24"],
        )
        assert result.exit_code == 1
        assert "error:" in result.output.lower()
        assert "config error" in result.output.lower()


# ---------------------------------------------------------------------------
# generate-claude-config command
# ---------------------------------------------------------------------------


class TestGenerateClaudeConfigCommand:
    @patch("mahavishnu.ecosystem_cli.get_ecosystem_loader")
    def test_dry_run(self, mock_get_loader: MagicMock) -> None:
        loader = _build_mock_loader()
        loader.generate_claude_mcp_config.return_value = {
            "session-buddy": {"command": "uvx", "args": ["session-buddy"]},
            "crackerjack": {"command": "uvx", "args": ["crackerjack"]},
        }
        mock_get_loader.return_value = loader

        app = _make_app()
        result = runner.invoke(app, ["generate-claude-config", "--dry-run"])
        assert result.exit_code == 0
        assert "dry run" in result.output.lower()
        assert "session-buddy" in result.output
        assert "crackerjack" in result.output

    @patch("mahavishnu.ecosystem_cli.get_ecosystem_loader")
    def test_dry_run_short_flag(self, mock_get_loader: MagicMock) -> None:
        loader = _build_mock_loader()
        loader.generate_claude_mcp_config.return_value = {}
        mock_get_loader.return_value = loader

        app = _make_app()
        result = runner.invoke(app, ["generate-claude-config", "--dry-run"])
        assert result.exit_code == 0
        assert "dry run" in result.output.lower()

    @patch("mahavishnu.ecosystem_cli.get_ecosystem_loader")
    def test_configuration_error(self, mock_get_loader: MagicMock) -> None:
        mock_get_loader.side_effect = ConfigurationError("config load error")

        app = _make_app()
        result = runner.invoke(app, ["generate-claude-config", "--dry-run"])
        assert result.exit_code == 1
        assert "configuration error" in result.output.lower()

    @patch("mahavishnu.ecosystem_cli.get_ecosystem_loader")
    def test_writes_to_file(self, mock_get_loader: MagicMock, tmp_path) -> None:
        loader = _build_mock_loader()
        loader.generate_claude_mcp_config.return_value = {
            "test-server": {"command": "test"},
        }
        mock_get_loader.return_value = loader

        output_file = tmp_path / "claude_test.json"

        app = _make_app()
        result = runner.invoke(
            app, ["generate-claude-config", "--output", str(output_file)]
        )
        assert result.exit_code == 0
        assert "generated mcp configuration" in result.output.lower()
        assert str(output_file) in result.output

        import json

        with open(output_file) as f:
            written = json.load(f)
        assert "mcpServers" in written
        assert "test-server" in written["mcpServers"]

    @patch("mahavishnu.ecosystem_cli.get_ecosystem_loader")
    def test_creates_new_file_if_missing(self, mock_get_loader: MagicMock, tmp_path) -> None:
        loader = _build_mock_loader()
        loader.generate_claude_mcp_config.return_value = {
            "new-server": {"command": "new"},
        }
        mock_get_loader.return_value = loader

        output_file = tmp_path / "claude.json"

        app = _make_app()
        result = runner.invoke(
            app, ["generate-claude-config", "--output", str(output_file)]
        )
        assert result.exit_code == 0
        assert "creating new config file" in result.output.lower()
