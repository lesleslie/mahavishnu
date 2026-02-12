"""Example: Ingesting books with Mahavishnu.

This example shows how to ingest PDF and EPUB books
into the knowledge ecosystem.

Usage:
    python examples/book_ingestion_example.py
"""

import asyncio
from pathlib import Path

from mahavishnu.ingesters import ContentIngester, ContentType


async def main() -> None:
    """Run book ingestion example."""
    print("📚 Mahavishnu Book Ingestion Example\n")

    # Create ingester with smaller chunks for books
    ingester = ContentIngester(
        chunk_size=1500,  # Larger chunks for books
        chunk_overlap=300,  # More overlap for context
    )

    try:
        print("📡 Initializing content ingester...")
        await ingester.initialize()

        # Example files to ingest
        # Replace these with actual file paths
        example_files = [
            "documents/ebook.pdf",
            "documents/research-paper.epub",
        ]

        # Filter to only existing files
        files_to_process = [f for f in example_files if Path(f).exists()]

        if not files_to_process:
            print("\n⚠️  No example files found.")
            print("   To test ingestion:")
            print("   1. Create 'documents/' directory")
            print("   2. Add PDF or EPUB files")
            print("   3. Run this script again")
            return

        print(f"\n📚 Processing {len(files_to_process)} files...")
        print("-" * 60)

        for file_path in files_to_process:
            path = Path(file_path)
            print(f"\n📖 Reading: {path.name}")

            result = await ingester.ingest_file(file_path)

            if result.success:
                content_type_name = {
                    ContentType.PDF: "PDF",
                    ContentType.EPUB: "EPUB",
                    ContentType.MARKDOWN: "Markdown",
                    ContentType.TEXT: "Text",
                }.get(result.content_type, "Unknown")

                print(f"✅ Success: {result.title}")
                print(f"   - Type: {content_type_name}")
                print(f"   - Chunks: {result.chunk_count}")
                print(f"   - Words: {result.metadata.get('word_count', 0):,}")
                print(f"   - Stored in Akosha: {result.stored_in_akosha}")
                print(f"   - Indexed in Crackerjack: {result.indexed_in_crackerjack}")
            else:
                print(f"❌ Failed: {result.error}")

        print("\n" + "=" * 60)
        print("✨ Book ingestion complete! You can now:")
        print("   - Search semantically across all ingested books")
        print("   - Query Akosha knowledge graph")
        print("   - Use content in RAG pipelines")

    finally:
        await ingester.close()


if __name__ == "__main__":
    asyncio.run(main())
