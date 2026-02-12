"""Example: Ingesting web content with Mahavishnu.

This example shows how to use the content ingestion pipeline to:
1. Fetch blog posts and web pages
2. Generate embeddings
3. Store in knowledge graph
4. Index for semantic search

Usage:
    python examples/web_ingestion_example.py
"""

import asyncio
from mahavishnu.ingesters import ContentIngester


async def main() -> None:
    """Run web content ingestion example."""
    print("🌐 Mahavishnu Web Content Ingestion Example\n")

    # Create ingester with default settings
    ingester = ContentIngester()

    try:
        # Initialize and connect to MCP servers
        print("📡 Initializing content ingester...")
        await ingester.initialize()

        # Example URLs to ingest
        urls = [
            "https://blog.anthropic.com/introducing-claude-code",
            "https://docs.anthropic.com/en/docs/build-with-claude/prompt-engineering",
        ]

        print(f"\n📋 Ingesting {len(urls)} URLs...")
        print("-" * 60)

        for url in urls:
            print(f"\n🔗 Fetching: {url}")
            result = await ingester.ingest_url(url)

            if result.success:
                print(f"✅ Success: {result.title}")
                print(f"   - Chunks: {result.chunk_count}")
                print(f"   - Stored in Akosha: {result.stored_in_akosha}")
                print(f"   - Indexed in Crackerjack: {result.indexed_in_crackerjack}")
            else:
                print(f"❌ Failed: {result.error}")

        print("\n" + "=" * 60)
        print("✨ Ingestion complete! Content is now:")
        print("   - Searchable via Crackerjack semantic search")
        print("   - Stored in Akosha knowledge graph")
        print("   - Tracked in Session-Buddy")

    finally:
        await ingester.close()


if __name__ == "__main__":
    asyncio.run(main())
