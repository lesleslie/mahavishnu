"""Native Agno tools for Mahavishnu orchestration.

This module provides custom tools that can be used by Agno agents
for file operations, code analysis, and repository management.

Available Tool Modules:
- file_tools: File and directory operations (read, write, list, search)
- code_tools: Code analysis and semantic search tools

Usage with Agno agents:
    from mahavishnu.engines.agno_tools import FILE_TOOLS, CODE_TOOLS

    agent = Agent(
        name="code_agent",
        tools=[*FILE_TOOLS, *CODE_TOOLS],
    )
"""

from __future__ import annotations

from mahavishnu.engines.agno_tools.code_tools import (
    analyze_code,
    get_function_signature,
    search_code,
)
from mahavishnu.engines.agno_tools.file_tools import (
    list_directory,
    read_file,
    search_files,
    write_file,
)

# Tool collections for easy import
FILE_TOOLS: list = [
    read_file,
    write_file,
    list_directory,
    search_files,
]

CODE_TOOLS: list = [
    analyze_code,
    search_code,
    get_function_signature,
]

ALL_TOOLS: list = [*FILE_TOOLS, *CODE_TOOLS]

__all__ = [
    # File tools
    "read_file",
    "write_file",
    "list_directory",
    "search_files",
    # Code tools
    "analyze_code",
    "search_code",
    "get_function_signature",
    # Tool collections
    "FILE_TOOLS",
    "CODE_TOOLS",
    "ALL_TOOLS",
]
