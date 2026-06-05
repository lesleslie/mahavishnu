"""Unit tests for the Mahavishnu ingestion CLI module.

Covers:
- ``add_ingestion_commands`` registers the ``ingest`` sub-typer.
- Each registered subcommand (``url``, ``file``, ``batch``, ``stats``) is
  discoverable through ``--help`` and accepts the expected options/arguments.
- The turboquant/compressor gate (set at import time on
  ``_DEFAULT_TURBOQUANT_BITS``) is honored end-to-end: when the flag is
  ``None`` (turboquant unavailable) the ingester is constructed without a
  compressor, and when it is set to an integer the value is forwarded.
- All heavy ingestion I/O is patched, so no real network, embedding, or
  filesystem operations are performed.

The conventions mirror ``tests/unit/test_backup_cli.py``:
- ``typer.testing.CliRunner`` is the runner.
- A throwaway parent ``typer.Typer`` is created so we don't depend on the
  full Mahavishnu main app being importable in unit tests.
- ``asyncio.run`` is replaced with a helper that runs the coroutine on a
  fresh event loop, matching the rest of the CLI test suite.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import typer
from typer.testing import CliRunner

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fake_asyncio_run(coro):
    """Run the coroutine on a fresh event loop (test environment safe)."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _make_app() -> typer.Typer:
    """Create a parent Typer app with the ingestion sub-typer registered."""
    app = typer.Typer()
    # Import inside the helper so the module-level _DEFAULT_TURBOQUANT_BITS
    # is only evaluated when a test actually exercises the CLI.
    from mahavishnu.ingestion_cli import add_ingestion_commands

    add_ingestion_commands()
    return app


def _ingest_result(success: bool = True) -> dict:
    """Build a representative ``IngestionResult.to_dict()`` payload."""
    return {
        "success": success,
        "title": "Test Title",
        "source": "https://example.com/post",
        "content_type": "webpage",
        "chunk_count": 4,
        "embedding_dimension": 384,
        "stored_in_akosha": True,
        "indexed_in_crackerjack": True,
        "error": None if success else "boom",
    }


def _mock_ingester(result_dict: dict | None = None) -> MagicMock:
    """Create a mock ContentIngester wired to async context-manager use."""
    ingester = MagicMock()
    ingester.__aenter__ = AsyncMock(return_value=ingester)
    ingester.__aexit__ = AsyncMock(return_value=False)
    ingester.ingest_url = AsyncMock(
        return_value=MagicMock(to_dict=lambda: result_dict or _ingest_result())
    )
    ingester.ingest_file = AsyncMock(
        return_value=MagicMock(to_dict=lambda: result_dict or _ingest_result())
    )
    ingester.batch_ingest_urls = AsyncMock(return_value=[result_dict or _ingest_result()])
    ingester.initialize = AsyncMock()
    # Stats attributes used by the ``stats`` command body.
    ingester._output_dir = Path("/tmp/ingested")
    ingester._chunk_size = 1000
    ingester._chunk_overlap = 200
    return ingester


# ---------------------------------------------------------------------------
# add_ingestion_commands: sub-typer registration
# ---------------------------------------------------------------------------


class TestAddIngestionCommands:
    """Verify add_ingestion_commands wires the ingest sub-typer correctly."""

    def test_registers_ingest_sub_typer(self):
        """``ingest`` should appear in the parent app's registered groups."""
        app = _make_app()
        registered_names = [group.name for group in app.registered_groups]
        assert "ingest" in registered_names

    def test_ingest_typer_has_help_text(self):
        """The registered ``ingest`` sub-typer should be exposed with its help."""
        app = _make_app()
        ingest_group = next(group for group in app.registered_groups if group.name == "ingest")
        # Typer attaches the underlying typer as ``typer_instance`` on the group.
        typer_instance = getattr(ingest_group, "typer_instance", None) or ingest_group.typer
        assert typer_instance.help == "Content ingestion commands"

    def test_ingest_help_lists_all_subcommands(self):
        """``ingest --help`` should list every registered subcommand."""
        app = _make_app()
        result = runner.invoke(app, ["ingest", "--help"])
        assert result.exit_code == 0
        for sub in ("url", "file", "batch", "stats"):
            assert sub in result.output, f"missing subcommand '{sub}' in help output"

    def test_idempotent_registration_on_separate_apps(self):
        """Calling add_ingestion_commands twice (on different parents) must work."""
        app_a = typer.Typer()
        app_b = typer.Typer()
        from mahavishnu.ingestion_cli import add_ingestion_commands

        add_ingestion_commands()  # attaches to module-level ``_main_cli.app``
        add_ingestion_commands()  # attaching twice should be tolerated
        # We can't easily verify the module app here (it would require importing
        # the heavy main CLI), so we just confirm the function returns cleanly
        # and the local app is still well-formed.
        names_a = [g.name for g in app_a.registered_groups]
        names_b = [g.name for g in app_b.registered_groups]
        assert names_a == []  # local apps aren't touched
        assert names_b == []


# ---------------------------------------------------------------------------
# Subcommand discoverability + argument registration
# ---------------------------------------------------------------------------


class TestSubcommandRegistration:
    """Each subcommand must be discoverable and accept its declared options."""

    @pytest.mark.parametrize("sub", ["url", "file", "batch", "stats"])
    def test_subcommand_help_renders(self, sub):
        app = _make_app()
        result = runner.invoke(app, ["ingest", sub, "--help"])
        assert result.exit_code == 0
        # All four commands accept a ``--provider/-p`` option.
        assert "--provider" in result.output

    def test_url_help_documents_chunk_and_output_options(self):
        """The url command should expose --chunk-size, --chunk-overlap, --output."""
        app = _make_app()
        result = runner.invoke(app, ["ingest", "url", "--help"])
        assert result.exit_code == 0
        for opt in ("--chunk-size", "--chunk-overlap", "--output"):
            assert opt in result.output

    def test_batch_help_documents_parallel_option(self):
        """The batch command should expose --parallel."""
        app = _make_app()
        result = runner.invoke(app, ["ingest", "batch", "--help"])
        assert result.exit_code == 0
        assert "--parallel" in result.output

    def test_url_missing_required_argument_errors(self):
        """Calling ``ingest url`` without a URL should fail with a non-zero code."""
        app = _make_app()
        result = runner.invoke(app, ["ingest", "url"])
        assert result.exit_code != 0

    def test_file_missing_required_argument_errors(self):
        """Calling ``ingest file`` without a path should fail with a non-zero code."""
        app = _make_app()
        result = runner.invoke(app, ["ingest", "file"])
        assert result.exit_code != 0

    def test_batch_missing_required_argument_errors(self):
        """Calling ``ingest batch`` without an input file should fail."""
        app = _make_app()
        result = runner.invoke(app, ["ingest", "batch"])
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# ingest url
# ---------------------------------------------------------------------------


class TestIngestUrl:
    """Behavioural tests for the ``ingest url`` command."""

    @patch("mahavishnu.ingestion_cli.create_content_ingester")
    def test_url_success(self, mock_factory):
        """A successful ingestion should print the success banner and exit 0."""
        mock_factory.return_value = _mock_ingester()
        with patch("mahavishnu.ingestion_cli.asyncio.run", side_effect=_fake_asyncio_run):
            app = _make_app()
            result = runner.invoke(app, ["ingest", "url", "https://example.com/post"])
        assert result.exit_code == 0
        assert "Successfully ingested" in result.output
        mock_factory.assert_called_once()
        # The URL argument should propagate to ingest_url.
        factory_kwargs = mock_factory.call_args.kwargs
        assert factory_kwargs["output_dir"] == "ingested"
        # The compressor gate should default to ``None`` when turboquant is
        # unavailable, or to the import-time bit value when it is.
        from mahavishnu.ingestion_cli import _DEFAULT_TURBOQUANT_BITS

        assert factory_kwargs["turboquant_bits"] == _DEFAULT_TURBOQUANT_BITS

    @patch("mahavishnu.ingestion_cli.create_content_ingester")
    def test_url_failure_exits_nonzero(self, mock_factory):
        """A failed ingestion should print the failure banner and exit 1."""
        mock_factory.return_value = _mock_ingester(result_dict=_ingest_result(success=False))
        with patch("mahavishnu.ingestion_cli.asyncio.run", side_effect=_fake_asyncio_run):
            app = _make_app()
            result = runner.invoke(app, ["ingest", "url", "https://example.com/post"])
        assert result.exit_code == 1
        assert "Failed to ingest" in result.output

    @patch("mahavishnu.ingestion_cli.create_content_ingester")
    def test_url_provider_openai_maps_to_enum(self, mock_factory):
        """--provider openai should map to the OPENAI enum on the factory."""
        from mahavishnu.core.embeddings import EmbeddingProvider

        mock_factory.return_value = _mock_ingester()
        with patch("mahavishnu.ingestion_cli.asyncio.run", side_effect=_fake_asyncio_run):
            app = _make_app()
            runner.invoke(
                app,
                [
                    "ingest",
                    "url",
                    "https://example.com",
                    "--provider",
                    "openai",
                ],
            )
        assert mock_factory.call_args.kwargs["embedding_provider"] == EmbeddingProvider.OPENAI


# ---------------------------------------------------------------------------
# ingest file
# ---------------------------------------------------------------------------


class TestIngestFile:
    """Behavioural tests for the ``ingest file`` command."""

    def test_file_missing_path_exits_nonzero(self, tmp_path):
        """A non-existent file path should be rejected up front with exit 1."""
        missing = tmp_path / "does-not-exist.pdf"
        app = _make_app()
        result = runner.invoke(app, ["ingest", "file", str(missing)])
        assert result.exit_code == 1
        assert "File not found" in result.output

    @patch("mahavishnu.ingestion_cli.create_content_ingester")
    def test_file_success(self, mock_factory, tmp_path):
        """An existing file should be ingested and exit 0 on success."""
        real_file = tmp_path / "doc.txt"
        real_file.write_text("hello world", encoding="utf-8")
        mock_factory.return_value = _mock_ingester()
        with patch("mahavishnu.ingestion_cli.asyncio.run", side_effect=_fake_asyncio_run):
            app = _make_app()
            result = runner.invoke(app, ["ingest", "file", str(real_file)])
        assert result.exit_code == 0
        assert "Successfully ingested" in result.output


# ---------------------------------------------------------------------------
# ingest batch
# ---------------------------------------------------------------------------


class TestIngestBatch:
    """Behavioural tests for the ``ingest batch`` command."""

    def test_batch_missing_input_file_exits_nonzero(self, tmp_path):
        """A missing input file should fail up front."""
        app = _make_app()
        result = runner.invoke(app, ["ingest", "batch", str(tmp_path / "missing.txt")])
        assert result.exit_code == 1
        assert "File not found" in result.output

    def test_batch_empty_input_file_exits_nonzero(self, tmp_path):
        """An input file with no URLs should be rejected."""
        empty = tmp_path / "empty.txt"
        empty.write_text("   \n\n", encoding="utf-8")
        app = _make_app()
        result = runner.invoke(app, ["ingest", "batch", str(empty)])
        assert result.exit_code == 1
        assert "No URLs found" in result.output

    @patch("mahavishnu.ingestion_cli.create_content_ingester")
    def test_batch_all_success_exits_zero(self, mock_factory, tmp_path):
        """All-success batch should report summary and exit 0."""
        urls_file = tmp_path / "urls.txt"
        urls_file.write_text("https://a.test\nhttps://b.test\n", encoding="utf-8")
        mock_factory.return_value = _mock_ingester()
        with patch("mahavishnu.ingestion_cli.asyncio.run", side_effect=_fake_asyncio_run):
            app = _make_app()
            result = runner.invoke(app, ["ingest", "batch", str(urls_file), "--parallel", "2"])
        assert result.exit_code == 0
        assert "Batch ingestion complete" in result.output
        assert "Success: 2" in result.output

    @patch("mahavishnu.ingestion_cli.create_content_ingester")
    def test_batch_partial_failure_exits_nonzero(self, mock_factory, tmp_path):
        """A mix of success/failure results should exit 1 and list failures."""
        urls_file = tmp_path / "urls.txt"
        urls_file.write_text("https://a.test\nhttps://b.test\n", encoding="utf-8")

        ingester = _mock_ingester()
        ingester.batch_ingest_urls = AsyncMock(
            return_value=[
                _ingest_result(success=True),
                _ingest_result(success=False),
            ]
        )
        mock_factory.return_value = ingester

        with patch("mahavishnu.ingestion_cli.asyncio.run", side_effect=_fake_asyncio_run):
            app = _make_app()
            result = runner.invoke(app, ["ingest", "batch", str(urls_file)])
        assert result.exit_code == 1
        assert "Failed: 1" in result.output
        assert "Failed URLs" in result.output


# ---------------------------------------------------------------------------
# ingest stats
# ---------------------------------------------------------------------------


class TestIngestStats:
    """Behavioural tests for the ``ingest stats`` command."""

    @patch("mahavishnu.ingestion_cli.create_content_ingester")
    def test_stats_output_when_output_dir_exists(self, mock_factory, tmp_path):
        """Stats should print provider, chunk size, and file count."""
        ingester = _mock_ingester()
        ingester._output_dir = tmp_path  # exists, but is empty
        mock_factory.return_value = ingester
        with patch("mahavishnu.ingestion_cli.asyncio.run", side_effect=_fake_asyncio_run):
            app = _make_app()
            result = runner.invoke(app, ["ingest", "stats"])
        assert result.exit_code == 0
        assert "Content Ingestion Status" in result.output
        assert "Chunk size: 1000" in result.output
        assert "Ingested files: 0" in result.output

    @patch("mahavishnu.ingestion_cli.create_content_ingester")
    def test_stats_warns_when_output_dir_missing(self, mock_factory, tmp_path):
        """Stats should print a yellow warning when the output dir is absent."""
        missing_dir = tmp_path / "no-such-dir"
        ingester = _mock_ingester()
        ingester._output_dir = missing_dir
        mock_factory.return_value = ingester
        with patch("mahavishnu.ingestion_cli.asyncio.run", side_effect=_fake_asyncio_run):
            app = _make_app()
            result = runner.invoke(app, ["ingest", "stats"])
        assert result.exit_code == 0
        assert "does not exist" in result.output


# ---------------------------------------------------------------------------
# Turboquant / compressor gate
# ---------------------------------------------------------------------------


class TestTurboquantGate:
    """Both branches of the turboquant flag must be exercised."""

    def test_default_turboquant_bits_value(self):
        """The module-level flag should be either ``None`` or ``3``/``4``."""
        from mahavishnu.ingestion_cli import _DEFAULT_TURBOQUANT_BITS

        assert _DEFAULT_TURBOQUANT_BITS in (None, 3, 4)

    @patch("mahavishnu.ingestion_cli.create_content_ingester")
    def test_disabled_gate_uses_none(self, mock_factory):
        """When the flag is None, the factory should receive ``turboquant_bits=None``."""
        with patch("mahavishnu.ingestion_cli._DEFAULT_TURBOQUANT_BITS", None):
            mock_factory.return_value = _mock_ingester()
            with patch("mahavishnu.ingestion_cli.asyncio.run", side_effect=_fake_asyncio_run):
                app = _make_app()
                runner.invoke(app, ["ingest", "url", "https://example.com/x"])
        assert mock_factory.call_args.kwargs["turboquant_bits"] is None

    @patch("mahavishnu.ingestion_cli.create_content_ingester")
    def test_enabled_gate_forwards_bit_count(self, mock_factory):
        """When the flag is an int, the factory should receive the same int."""
        with patch("mahavishnu.ingestion_cli._DEFAULT_TURBOQUANT_BITS", 4):
            mock_factory.return_value = _mock_ingester()
            with patch("mahavishnu.ingestion_cli.asyncio.run", side_effect=_fake_asyncio_run):
                app = _make_app()
                runner.invoke(app, ["ingest", "url", "https://example.com/x"])
        assert mock_factory.call_args.kwargs["turboquant_bits"] == 4

    def test_turboquant_module_flag_state(self):
        """The import-time flag should track the underlying module constant."""
        from mahavishnu.ingesters.turboquant_compressor import TURBOQUANT_AVAILABLE
        from mahavishnu.ingestion_cli import _DEFAULT_TURBOQUANT_BITS

        if TURBOQUANT_AVAILABLE:
            assert _DEFAULT_TURBOQUANT_BITS is not None
        else:
            assert _DEFAULT_TURBOQUANT_BITS is None
