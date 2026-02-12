"""CLI commands for content ingestion.

This module provides Typer commands for ingesting web content and documents
into the Mahavishnu knowledge ecosystem.

Example:
    $ mahavishnu ingest url https://blog.example.com/post
    $ mahavishnu ingest file document.pdf
    $ mahavishnu ingest batch urls.txt
"""

import asyncio
from pathlib import Path
from typing import NoReturn

import typer
import structlog

from .ingesters.content_ingester import ContentIngester, create_content_ingester
from .core.embeddings import EmbeddingProvider

logger = structlog.get_logger()
ingestion_app = typer.Typer(help="Content ingestion commands")


def _format_result(result: dict) -> None:
    """Format and display ingestion result.

    Args:
        result: Result dictionary from ingestion
    """
    if result["success"]:
        typer.echo(f"✅ Successfully ingested: {result['title'] or result['source']}", fg=typer.colors.GREEN)
        typer.echo(f"   Type: {result['content_type']}", fg=typer.colors.BLUE)
        typer.echo(f"   Chunks: {result['chunk_count']}", fg=typer.colors.BLUE)
        typer.echo(f"   Embedding dim: {result['embedding_dimension']}", fg=typer.colors.BLUE)
        typer.echo(
            f"   Akosha: {'✓' if result['stored_in_akosha'] else '✗'}",
            fg=typer.colors.GREEN if result['stored_in_akosha'] else typer.colors.RED,
        )
        typer.echo(
            f"   Crackerjack: {'✓' if result['indexed_in_crackerjack'] else '✗'}",
            fg=typer.colors.GREEN if result['indexed_in_crackerjack'] else typer.colors.RED,
        )
    else:
        typer.echo(f"❌ Failed to ingest: {result['source']}", fg=typer.colors.RED)
        typer.echo(f"   Error: {result['error']}", fg=typer.colors.RED)


@ingestion_app.command("url")
def ingest_url(
    url: str = typer.Argument(..., help="URL to ingest"),
    provider: str = typer.Option(None, "--provider", "-p", help="Embedding provider (fastembed, ollama, openai)"),
    chunk_size: int = typer.Option(1000, "--chunk-size", "-c", help="Maximum characters per chunk"),
    chunk_overlap: int = typer.Option(200, "--chunk-overlap", "-o", help="Character overlap between chunks"),
    output_dir: str = typer.Option("ingested", "--output", "-d", help="Output directory"),
):
    """Ingest content from a URL.

    Fetches content from the given URL and stores it in:
    - Akosha knowledge graph with embeddings
    - Crackerjack semantic file index
    - Session-Buddy tracking

    Example:
        $ mahavishnu ingest url https://blog.example.com/post
        $ mahavishnu ingest url https://example.com --provider ollama --chunk-size 500
    """
    async def _ingest():
        # Map provider string to enum
        embedding_provider = None
        if provider:
            provider_map = {
                "fastembed": EmbeddingProvider.FASTEMBED,
                "ollama": EmbeddingProvider.OLLAMA,
                "openai": EmbeddingProvider.OPENAI,
            }
            embedding_provider = provider_map.get(provider.lower())

        ingester = create_content_ingester(
            embedding_provider=embedding_provider,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            output_dir=output_dir,
        )

        async with ingester:
            result = await ingester.ingest_url(url)
            return result.to_dict()

    result = asyncio.run(_ingest())
    _format_result(result)

    # Exit with appropriate code
    raise typer.Exit(code=0 if result["success"] else 1)


@ingestion_app.command("file")
def ingest_file(
    file_path: str = typer.Argument(..., help="Path to file to ingest"),
    provider: str = typer.Option(None, "--provider", "-p", help="Embedding provider (fastembed, ollama, openai)"),
    chunk_size: int = typer.Option(1000, "--chunk-size", "-c", help="Maximum characters per chunk"),
    chunk_overlap: int = typer.Option(200, "--chunk-overlap", "-o", help="Character overlap between chunks"),
):
    """Ingest content from a local file.

    Supports PDF, EPUB, Markdown, and text files.

    Example:
        $ mahavishnu ingest file document.pdf
        $ mahavishnu ingest file book.epub --provider fastembed
    """
    # Validate file exists
    path = Path(file_path)
    if not path.exists():
        typer.echo(f"❌ File not found: {file_path}", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    async def _ingest():
        # Map provider string to enum
        embedding_provider = None
        if provider:
            provider_map = {
                "fastembed": EmbeddingProvider.FASTEMBED,
                "ollama": EmbeddingProvider.OLLAMA,
                "openai": EmbeddingProvider.OPENAI,
            }
            embedding_provider = provider_map.get(provider.lower())

        ingester = create_content_ingester(
            embedding_provider=embedding_provider,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )

        async with ingester:
            result = await ingester.ingest_file(file_path)
            return result.to_dict()

    result = asyncio.run(_ingest())
    _format_result(result)

    # Exit with appropriate code
    raise typer.Exit(code=0 if result["success"] else 1)


@ingestion_app.command("batch")
def ingest_batch(
    input_file: str = typer.Argument(..., help="File containing URLs (one per line)"),
    provider: str = typer.Option(None, "--provider", "-p", help="Embedding provider (fastembed, ollama, openai)"),
    parallel: int = typer.Option(5, "--parallel", "-n", help="Number of parallel ingestions"),
):
    """Ingest multiple URLs from a file.

    Reads URLs from a text file (one per line) and processes them
    in parallel for faster ingestion.

    Example:
        $ mahavishnu ingest batch urls.txt
        $ mahavishnu ingest batch blogs.txt --parallel 10 --provider ollama
    """
    # Validate file exists
    path = Path(input_file)
    if not path.exists():
        typer.echo(f"❌ File not found: {input_file}", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    # Read URLs
    urls = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    if not urls:
        typer.echo(f"❌ No URLs found in: {input_file}", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    typer.echo(f"📋 Found {len(urls)} URLs to ingest", fg=typer.colors.BLUE)

    async def _ingest():
        # Map provider string to enum
        embedding_provider = None
        if provider:
            provider_map = {
                "fastembed": EmbeddingProvider.FASTEMBED,
                "ollama": EmbeddingProvider.OLLAMA,
                "openai": EmbeddingProvider.OPENAI,
            }
            embedding_provider = provider_map.get(provider.lower())

        ingester = create_content_ingester(
            embedding_provider=embedding_provider,
        )

        async with ingester:
            # Process in batches
            results = []
            for i in range(0, len(urls), parallel):
                batch = urls[i:i + parallel]
                typer.echo(f"Processing batch {i // parallel + 1} ({len(batch)} URLs)...", fg=typer.colors.BLUE)
                batch_results = await ingester.batch_ingest_urls(batch)
                results.extend(batch_results)

            return results

    results = asyncio.run(_ingest())

    # Report summary
    success_count = sum(1 for r in results if r["success"])
    fail_count = len(results) - success_count

    typer.echo(f"\n📊 Batch ingestion complete:", fg=typer.colors.BLUE)
    typer.echo(f"   Total: {len(results)}", fg=typer.colors.BLUE)
    typer.echo(f"   Success: {success_count}", fg=typer.colors.GREEN)
    typer.echo(f"   Failed: {fail_count}", fg=typer.colors.RED if fail_count > 0 else typer.colors.GREEN)

    # Show failed items
    if fail_count > 0:
        typer.echo("\n❌ Failed URLs:", fg=typer.colors.RED)
        for result in results:
            if not result["success"]:
                typer.echo(f"   - {result['source']}: {result['error']}", fg=typer.colors.RED)

    raise typer.Exit(code=0 if fail_count == 0 else 1)


@ingestion_app.command("stats")
def ingestion_stats(
    provider: str = typer.Option(None, "--provider", "-p", help="Preferred embedding provider"),
):
    """Show content ingestion system status.

    Displays:
    - Available embedding providers
    - Output directory
    - Chunk configuration
    - System status

    Example:
        $ mahavishnu ingest stats
        $ mahavishnu ingest stats --provider fastembed
    """
    async def _stats():
        # Map provider string to enum
        embedding_provider = None
        if provider:
            provider_map = {
                "fastembed": EmbeddingProvider.FASTEMBED,
                "ollama": EmbeddingProvider.OLLAMA,
                "openai": EmbeddingProvider.OPENAI,
            }
            embedding_provider = provider_map.get(provider.lower())

        ingester = create_content_ingester(
            embedding_provider=embedding_provider,
        )

        await ingester.initialize()

        # Get stats via MCP tool
        from .mcp.tools.content_ingestion_tools import register_content_tools
        from fastmcp import FastMCP

        mcp = FastMCP("stats")
        register_content_tools(mcp)

        # Since we can't call tools directly, return ingester config
        return {
            "output_dir": str(ingester._output_dir),
            "chunk_size": ingester._chunk_size,
            "chunk_overlap": ingester._chunk_overlap,
            "embedding_provider": embedding_provider.value if embedding_provider else "auto",
        }

    stats = asyncio.run(_stats())

    typer.echo("📊 Content Ingestion Status:", fg=typer.colors.BLUE)
    typer.echo(f"   Output directory: {stats['output_dir']}", fg=typer.colors.BLUE)
    typer.echo(f"   Chunk size: {stats['chunk_size']}", fg=typer.colors.BLUE)
    typer.echo(f"   Chunk overlap: {stats['chunk_overlap']}", fg=typer.colors.BLUE)
    typer.echo(f"   Embedding provider: {stats['embedding_provider']}", fg=typer.colors.BLUE)

    # Check output directory exists
    output_path = Path(stats["output_dir"])
    if output_path.exists():
        file_count = len(list(output_path.glob("*")))
        typer.echo(f"   Ingested files: {file_count}", fg=typer.colors.GREEN)
    else:
        typer.echo(f"   Output directory: does not exist", fg=typer.colors.YELLOW)


def add_ingestion_commands() -> None:
    """Add content ingestion commands to main CLI.

    Call this from main cli.py to register ingestion commands.
    """
    # Import main app
    from .cli import app

    # Add ingestion app as sub-command
    app.add_typer(ingestion_app, name="ingest")
