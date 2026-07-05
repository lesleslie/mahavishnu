"""CrowSettings — Bodai crow HTTP MCP server configuration.

Layered on mcp_common.profiles.standard.StandardServerSettings, which
provides `server_name`, `description`, `log_level`, `enable_debug_mode`,
`enable_resources`. CrowSettings adds Crow-specific transport, workspace,
SSRF, and SearXNG knobs.
"""

from __future__ import annotations

from pathlib import Path
import shutil

from mcp_common.profiles.standard import StandardServerSettings
from pydantic import Field, model_validator


class CrowSettings(StandardServerSettings):
    """Settings for the Bodai crow HTTP MCP server."""

    # ---- transport ---------------------------------------------------------
    http_host: str = "127.0.0.1"
    http_port: int = 8675

    # ---- workspace containment --------------------------------------------
    workspace_root: Path = Field(default_factory=Path.cwd)

    # ---- web / SSRF --------------------------------------------------------
    user_agent: str = "BodaiCrow/0.1"
    max_redirect_hops: int = 5

    # ---- grep --------------------------------------------------------------
    max_grep_matches: int = 100
    rg_path: Path | None = None

    # ---- glob --------------------------------------------------------------
    max_glob_results: int = 1000

    # ---- web search --------------------------------------------------------
    searxng_url: str = "http://localhost:2946"

    # ---- web fetch batch ---------------------------------------------------
    max_batch_urls: int = 20
    max_concurrent_fetches: int = 5

    # ---- terminal proxy ----------------------------------------------------
    crow_mcp_command: str = "crow-mcp"

    @model_validator(mode="after")
    def _resolve_rg(self) -> CrowSettings:
        if self.rg_path is None:
            found = shutil.which("rg")
            self.rg_path = Path(found) if found else None
        return self
