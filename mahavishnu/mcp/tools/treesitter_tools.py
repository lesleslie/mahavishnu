"""MCP tools for tree-sitter - real-time analysis focused.

These tools provide fast, cached code analysis for Mahavishnu's
orchestration workflows. Unlike Session-Buddy's storage-focused tools,
these focus on real-time parsing with content-hash caching.

Tools:
- treesitter_parse: Parse a file with caching
- treesitter_extract_symbols: Extract symbols from parsed file
- treesitter_find_usages: Find symbol usages (planned)
- treesitter_query: Custom tree-sitter queries (planned)
- treesitter_batch_analyze: Analyze multiple files
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

logger = logging.getLogger(__name__)

# Global parser instance (shared cache)
_parser: Any = None


def _get_parser():
    """Get or create the global parser instance."""
    global _parser
    if _parser is None:
        from mcp_common.parsing.tree_sitter import TreeSitterParser

        _parser = TreeSitterParser()
    return _parser


def _ensure_grammar_loaded(language: str) -> bool:
    """Ensure grammar is loaded for the given language."""
    from mcp_common.parsing.tree_sitter import SupportedLanguage, ensure_language_loaded

    try:
        lang = SupportedLanguage(language.lower())
        return ensure_language_loaded(lang)
    except ValueError:
        return False


def register_treesitter_tools(mcp: FastMCP) -> None:
    """Register 5 tree-sitter tools for Mahavishnu.

    Args:
        mcp: FastMCP server instance
    """

    @mcp.tool()
    async def treesitter_parse(
        file_path: str,
        language: str | None = None,
    ) -> dict[str, Any]:
        """Parse a source code file with caching.

        Uses content-hash caching to avoid redundant parsing.
        Returns parse status, symbol counts, and cache information.

        Args:
            file_path: Absolute path to source file
            language: Optional language override (auto-detected if not provided)

        Returns:
            Parse result with symbols, imports, and cache status
        """
        from mcp_common.parsing.tree_sitter import SupportedLanguage

        try:
            parser = _get_parser()
            path = Path(file_path)

            # Determine language
            if language:
                try:
                    lang = SupportedLanguage(language.lower())
                except ValueError:
                    lang = SupportedLanguage.UNKNOWN
            else:
                lang = parser.detect_language(path)

            # Load grammar if needed
            if lang != SupportedLanguage.UNKNOWN:
                _ensure_grammar_loaded(lang.value)

            # Parse the file
            result = await parser.parse_file(path, language=lang)

            return {
                "success": result.success,
                "file_path": result.file_path,
                "language": result.language.value,
                "symbols_count": len(result.symbols),
                "imports_count": len(result.imports),
                "relationships_count": len(result.relationships),
                "parse_time_ms": round(result.parse_time_ms, 2),
                "from_cache": result.from_cache,
                "error_node_count": result.error_node_count,
                "error": result.error,
            }

        except Exception as e:
            logger.error(f"Failed to parse file: {e}")
            return {
                "success": False,
                "file_path": file_path,
                "error": str(e),
            }

    @mcp.tool()
    async def treesitter_extract_symbols(
        file_path: str,
        symbol_kinds: list[str] | None = None,
    ) -> dict[str, Any]:
        """Extract symbols from a parsed file.

        Returns detailed symbol information including signatures,
        docstrings, and locations.

        Args:
            file_path: Absolute path to source file
            symbol_kinds: Optional filter (function, class, method, variable, import)

        Returns:
            List of extracted symbols with metadata
        """
        from mcp_common.parsing.tree_sitter import SupportedLanguage, SymbolKind

        try:
            parser = _get_parser()
            path = Path(file_path)
            lang = parser.detect_language(path)

            if lang != SupportedLanguage.UNKNOWN:
                _ensure_grammar_loaded(lang.value)

            result = await parser.parse_file(path)

            # Filter symbols
            symbols = result.symbols
            if symbol_kinds:
                symbols = [s for s in symbols if s.kind.value in symbol_kinds]

            return {
                "success": result.success,
                "file_path": file_path,
                "language": result.language.value,
                "total_symbols": len(result.symbols),
                "filtered_symbols": len(symbols),
                "symbols": [
                    {
                        "name": s.name,
                        "kind": s.kind.value,
                        "line_start": s.line_start,
                        "line_end": s.line_end,
                        "column_start": s.column_start,
                        "column_end": s.column_end,
                        "signature": s.signature,
                        "docstring": s.docstring[:100] + "..."
                        if s.docstring and len(s.docstring) > 100
                        else s.docstring,
                        "modifiers": list(s.modifiers),
                        "parameters": [
                            {"name": p.get("name", ""), "type": p.get("type", "")}
                            for p in s.parameters
                        ],
                        "return_type": s.return_type,
                        "parent": s.parent_context,
                    }
                    for s in symbols
                ],
                "from_cache": result.from_cache,
                "error": result.error,
            }

        except Exception as e:
            logger.error(f"Failed to extract symbols: {e}")
            return {
                "success": False,
                "file_path": file_path,
                "error": str(e),
                "symbols": [],
            }

    @mcp.tool()
    async def treesitter_find_usages(
        file_path: str,
        symbol_name: str,
        search_directory: str | None = None,
    ) -> dict[str, Any]:
        """Find usages of a symbol across files.

        Searches for references to a symbol in the specified directory.

        Args:
            file_path: File containing symbol definition
            symbol_name: Name of symbol to find
            search_directory: Directory to search (defaults to file's parent)

        Returns:
            List of usage locations
        """
        try:
            parser = _get_parser()
            path = Path(file_path)

            # Determine search directory
            if search_directory:
                search_dir = Path(search_directory)
            else:
                search_dir = path.parent

            # Parse the definition file first
            result = await parser.parse_file(path)
            if not result.success:
                return {
                    "success": False,
                    "error": f"Failed to parse definition file: {result.error}",
                    "symbol_name": symbol_name,
                }

            # Find the symbol in the definition
            symbol_found = any(s.name == symbol_name for s in result.symbols)
            if not symbol_found:
                return {
                    "success": True,
                    "symbol_name": symbol_name,
                    "definition": None,
                    "usages": [],
                    "message": f"Symbol '{symbol_name}' not found in {file_path}",
                }

            # Get symbol details
            symbol = next((s for s in result.symbols if s.name == symbol_name), None)

            # Search for usages (basic implementation - grep for symbol name)
            usages = []

            # Get files to search based on language
            lang = parser.detect_language(path)
            extensions = {
                "python": ".py",
                "go": ".go",
                "javascript": ".js",
                "typescript": ".ts",
            }
            ext = extensions.get(lang.value, ".py")

            for candidate in search_dir.glob(f"**/*{ext}"):
                if candidate == path:
                    continue
                try:
                    content = candidate.read_text()
                    if symbol_name in content:
                        # Find line numbers
                        for i, line in enumerate(content.split("\n"), 1):
                            if symbol_name in line:
                                usages.append(
                                    {
                                        "file": str(candidate),
                                        "line": i,
                                        "context": line.strip()[:80],
                                    }
                                )
                except Exception:
                    continue

            return {
                "success": True,
                "symbol_name": symbol_name,
                "definition": {
                    "file": str(path),
                    "line_start": symbol.line_start if symbol else None,
                    "line_end": symbol.line_end if symbol else None,
                    "kind": symbol.kind.value if symbol else None,
                }
                if symbol
                else None,
                "usages": usages[:50],  # Limit results
                "total_usages": len(usages),
            }

        except Exception as e:
            logger.error(f"Failed to find usages: {e}")
            return {
                "success": False,
                "symbol_name": symbol_name,
                "error": str(e),
                "usages": [],
            }

    @mcp.tool()
    async def treesitter_query(
        file_path: str,
        query: str,
    ) -> dict[str, Any]:
        """Run a custom tree-sitter query (S-expression format).

        Allows running custom tree-sitter queries for advanced
        pattern matching.

        Args:
            file_path: Absolute path to source file
            query: Tree-sitter query string (S-expression)

        Returns:
            List of matching nodes
        """
        try:
            parser = _get_parser()
            path = Path(file_path)
            lang = parser.detect_language(path)

            if lang.value == "unknown":
                return {
                    "success": False,
                    "error": "Unknown language",
                    "matches": [],
                }

            _ensure_grammar_loaded(lang.value)

            result = await parser.parse_file(path)
            if not result.success:
                return {
                    "success": False,
                    "error": result.error,
                    "matches": [],
                }

            # Basic query implementation
            # For now, return a message that custom queries need full implementation
            return {
                "success": True,
                "file_path": file_path,
                "query": query,
                "matches": [],
                "message": "Custom tree-sitter queries require direct tree-sitter API access",
                "tip": "Use treesitter_extract_symbols with symbol_kinds filter instead",
            }

        except Exception as e:
            logger.error(f"Failed to run query: {e}")
            return {
                "success": False,
                "file_path": file_path,
                "query": query,
                "error": str(e),
                "matches": [],
            }

    @mcp.tool()
    async def treesitter_batch_analyze(
        directory: str,
        file_pattern: str = "**/*.py",
        max_files: int = 100,
    ) -> dict[str, Any]:
        """Batch analyze multiple files in a directory.

        Analyzes all matching files and returns aggregated results
        with caching for efficiency.

        Args:
            directory: Directory to analyze
            file_pattern: Glob pattern (default: Python files)
            max_files: Maximum files (default 100)

        Returns:
            Aggregated analysis results
        """
        try:
            parser = _get_parser()
            dir_path = Path(directory)
            files = list(dir_path.glob(file_pattern))[:max_files]

            results = []
            total_symbols = 0
            total_imports = 0
            cache_hits = 0
            errors = []

            for file_path in files:
                if not file_path.is_file():
                    continue

                try:
                    result = await parser.parse_file(file_path)
                    total_symbols += len(result.symbols)
                    total_imports += len(result.imports)
                    if result.from_cache:
                        cache_hits += 1

                    results.append(
                        {
                            "file": str(file_path.relative_to(dir_path)),
                            "symbols": len(result.symbols),
                            "imports": len(result.imports),
                            "cached": result.from_cache,
                            "parse_time_ms": round(result.parse_time_ms, 2),
                            "error_nodes": result.error_node_count,
                        }
                    )

                    if not result.success:
                        errors.append(
                            {
                                "file": str(file_path.relative_to(dir_path)),
                                "error": result.error,
                            }
                        )

                except Exception as e:
                    errors.append(
                        {
                            "file": str(file_path.relative_to(dir_path)),
                            "error": str(e),
                        }
                    )

            # Get cache stats
            cache_stats = parser.get_cache_stats()

            return {
                "success": True,
                "directory": str(dir_path),
                "file_pattern": file_pattern,
                "files_analyzed": len(results),
                "total_symbols": total_symbols,
                "total_imports": total_imports,
                "cache_hit_rate": cache_stats.get("hit_rate", 0),
                "cache_hits": cache_hits,
                "results": results,
                "errors": errors[:10],  # Limit error list
                "error_count": len(errors),
            }

        except Exception as e:
            logger.error(f"Failed to batch analyze: {e}")
            return {
                "success": False,
                "directory": directory,
                "error": str(e),
                "results": [],
            }

    @mcp.tool()
    async def treesitter_cache_stats() -> dict[str, Any]:
        """Get cache statistics for the tree-sitter parser.

        Returns hit rate, size, and eviction statistics.

        Returns:
            Cache statistics
        """
        try:
            parser = _get_parser()
            stats = parser.get_cache_stats()
            return {
                "success": True,
                **stats,
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }

    @mcp.tool()
    async def treesitter_clear_cache() -> dict[str, Any]:
        """Clear the tree-sitter parse cache.

        Returns:
            Number of entries cleared
        """
        try:
            parser = _get_parser()
            count = parser.clear_cache()
            return {
                "success": True,
                "entries_cleared": count,
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }
