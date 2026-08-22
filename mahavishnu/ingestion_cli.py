"""CLI commands for content ingestion.

This module provides Typer commands for ingesting web content and documents
into the Mahavishnu knowledge ecosystem.

Example:
    $ mahavishnu ingest url https://blog.example.com/post
    $ mahavishnu ingest file document.pdf
    $ mahavishnu ingest batch blogs.txt
"""

import asyncio
from pathlib import Path

import structlog
import typer

from .ingesters.content_ingester import create_content_ingester
from .ingesters.turboquant_compressor import TURBOQUANT_AVAILABLE

# Evaluated once at import time. Tests that need to override this must patch
# `mahavishnu.ingestion_cli._DEFAULT_TURBOQUANT_BITS` directly (not the source flag).
_DEFAULT_TURBOQUANT_BITS: int | None = 4 if TURBOQUANT_AVAILABLE else None

logger = structlog.get_logger()
ingestion_app = typer.Typer(help="Content ingestion commands")


def _format_result(result: dict) -> None:
    """Format and display ingestion result.

    Args:
        result: Result dictionary from ingestion
    """
    if result["success"]:
        typer.secho(
            f"✅ Successfully ingested: {result['title'] or result['source']}",
            fg=typer.colors.GREEN,
        )
        typer.secho(f"   Type: {result['content_type']}", fg=typer.colors.BLUE)
        typer.secho(f"   Chunks: {result['chunk_count']}", fg=typer.colors.BLUE)
        typer.secho(f"   Embedding dim: {result['embedding_dimension']}", fg=typer.colors.BLUE)
        typer.secho(
            f"   Akosha: {'✓' if result['stored_in_akosha'] else '✗'}",
            fg=typer.colors.GREEN if result["stored_in_akosha"] else typer.colors.RED,
        )
        typer.secho(
            f"   Crackerjack: {'✓' if result['indexed_in_crackerjack'] else '✗'}",
            fg=typer.colors.GREEN if result["indexed_in_crackerjack"] else typer.colors.RED,
        )
    else:
        typer.secho(f"❌ Failed to ingest: {result['source']}", fg=typer.colors.RED)
        typer.secho(f"   Error: {result['error']}", fg=typer.colors.RED)


@ingestion_app.command("url")
def ingest_url(
    url: str = typer.Argument(..., help="URL to ingest"),
    chunk_size: int = typer.Option(1000, "--chunk-size", "-c", help="Maximum characters per chunk"),
    chunk_overlap: int = typer.Option(
        200, "--chunk-overlap", "-o", help="Character overlap between chunks"
    ),
    output_dir: str = typer.Option("ingested", "--output", "-d", help="Output directory"),
):
    """Ingest content from a URL.

    Fetches content from the given URL and stores it in:
    - Akosha knowledge graph with embeddings
    - Crackerjack semantic file index
    - Session-Buddy tracking

    Embedding backend selection is automatic via the oneiric probe chain
    (llama_cpp -> ollama -> minimax -> model2vec -> mock). Configure which
    legs participate in ``EmbeddingSettings`` from
    ``oneiric.adapters.observability.embedding_settings``.

    Example:
        $ mahavishnu ingest url https://blog.example.com/post
        $ mahavishnu ingest url https://example.com --chunk-size 500
    """

    async def _ingest():
        ingester = create_content_ingester(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            output_dir=output_dir,
            turboquant_bits=_DEFAULT_TURBOQUANT_BITS,
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
    chunk_size: int = typer.Option(1000, "--chunk-size", "-c", help="Maximum characters per chunk"),
    chunk_overlap: int = typer.Option(
        200, "--chunk-overlap", "-o", help="Character overlap between chunks"
    ),
):
    """Ingest content from a local file.

    Supports PDF, EPUB, Markdown, and text files.

    Embedding backend selection is automatic via the oneiric probe chain.
    Configure which legs participate in ``EmbeddingSettings`` from
    ``oneiric.adapters.observability.embedding_settings``.

    Example:
        $ mahavishnu ingest file document.pdf
        $ mahavishnu ingest file book.epub
    """
    # Validate file exists
    path = Path(file_path)
    if not path.exists():
        typer.secho(f"❌ File not found: {file_path}", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    async def _ingest():
        ingester = create_content_ingester(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            turboquant_bits=_DEFAULT_TURBOQUANT_BITS,
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
    parallel: int = typer.Option(5, "--parallel", "-n", help="Number of parallel ingestions"),
):
    """Ingest multiple URLs from a file.

    Reads URLs from a text file (one per line) and processes them
    in parallel for faster ingestion.

    Embedding backend selection is automatic via the oneiric probe chain.

    Example:
        $ mahavishnu ingest batch urls.txt
        $ mahavishnu ingest batch blogs.txt --parallel 10
    """
    # Validate file exists
    path = Path(input_file)
    if not path.exists():
        typer.secho(f"❌ File not found: {input_file}", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    # Read URLs
    urls = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    if not urls:
        typer.secho(f"❌ No URLs found in: {input_file}", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    typer.secho(f"📋 Found {len(urls)} URLs to ingest", fg=typer.colors.BLUE)

    async def _ingest():
        ingester = create_content_ingester(
            turboquant_bits=_DEFAULT_TURBOQUANT_BITS,
        )

        async with ingester:
            # Process in batches
            results = []
            for i in range(0, len(urls), parallel):
                batch = urls[i : i + parallel]
                typer.secho(
                    f"Processing batch {i // parallel + 1} ({len(batch)} URLs)...",
                    fg=typer.colors.BLUE,
                )
                batch_results = await ingester.batch_ingest_urls(batch)
                results.extend(batch_results)

            return results

    results = asyncio.run(_ingest())

    # Report summary
    success_count = sum(1 for r in results if r["success"])
    fail_count = len(results) - success_count

    typer.secho("\n📊 Batch ingestion complete:", fg=typer.colors.BLUE)
    typer.secho(f"   Total: {len(results)}", fg=typer.colors.BLUE)
    typer.secho(f"   Success: {success_count}", fg=typer.colors.GREEN)
    typer.secho(
        f"   Failed: {fail_count}",
        fg=typer.colors.RED if fail_count > 0 else typer.colors.GREEN,
    )

    # Show failed items
    if fail_count > 0:
        typer.secho("\n❌ Failed URLs:", fg=typer.colors.RED)
        for result in results:
            if not result["success"]:
                typer.secho(f"   - {result['source']}: {result['error']}", fg=typer.colors.RED)

    raise typer.Exit(code=0 if fail_count == 0 else 1)


@ingestion_app.command("stats")
def ingestion_stats() -> None:
    """Show content ingestion system status.

    Displays:
    - Active embedding backend (selected by oneiric's probe chain)
    - Output directory
    - Chunk configuration
    - System status

    Embedding backend selection is automatic via the oneiric probe chain
    (llama_cpp -> ollama -> minimax -> model2vec -> mock). Configure which
    legs participate in ``EmbeddingSettings`` from
    ``oneiric.adapters.observability.embedding_settings``.

    Example:
        $ mahavishnu ingest stats
    """

    async def _stats():
        ingester = create_content_ingester(
            turboquant_bits=_DEFAULT_TURBOQUANT_BITS,
        )

        await ingester.initialize()

        # Get stats directly from ingester config
        return {
            "output_dir": str(ingester._output_dir),
            "chunk_size": ingester._chunk_size,
            "chunk_overlap": ingester._chunk_overlap,
            "embedding_provider": "auto (oneiric probe chain)",
        }

    stats = asyncio.run(_stats())

    typer.secho("📊 Content Ingestion Status:", fg=typer.colors.BLUE)
    typer.secho(f"   Output directory: {stats['output_dir']}", fg=typer.colors.BLUE)
    typer.secho(f"   Chunk size: {stats['chunk_size']}", fg=typer.colors.BLUE)
    typer.secho(f"   Chunk overlap: {stats['chunk_overlap']}", fg=typer.colors.BLUE)
    typer.secho(f"   Embedding provider: {stats['embedding_provider']}", fg=typer.colors.BLUE)

    # Check output directory exists
    output_path = Path(stats["output_dir"])
    if output_path.exists():
        file_count = len(list(output_path.glob("*")))
        typer.secho(f"   Ingested files: {file_count}", fg=typer.colors.GREEN)
    else:
        typer.secho("   Output directory: does not exist", fg=typer.colors.YELLOW)


def add_ingestion_commands() -> None:
    """Add content ingestion commands to main CLI.

    Call this from main cli.py to register ingestion commands.
    """
    # Import main app
    from ._main_cli import app

    # Add ingestion app as sub-command
    app.add_typer(ingestion_app, name="ingest")
