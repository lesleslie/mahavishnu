#!/bin/bash
# Example CLI commands for content ingestion

echo "🌐 Mahavishnu Content Ingestion Examples"
echo ""

# Example 1: Ingest a single blog post
echo "Example 1: Ingest a blog post"
echo "Command: mahavishnu ingest url https://blog.example.com/post"
echo ""

# Example 2: Ingest with specific embedding provider
echo "Example 2: Ingest with Ollama (local embeddings)"
echo "Command: mahavishnu ingest url https://example.com --provider ollama"
echo ""

# Example 3: Ingest a PDF document
echo "Example 3: Ingest a PDF book"
echo "Command: mahavishnu ingest file documents/report.pdf"
echo ""

# Example 4: Batch ingest multiple URLs
echo "Example 4: Batch ingest from file"
echo "Create urls.txt with one URL per line:"
echo "  https://blog1.com/post1"
echo "  https://blog2.com/post2"
echo "  https://blog3.com/post3"
echo ""
echo "Then run:"
echo "Command: mahavishnu ingest batch urls.txt"
echo ""

# Example 5: Parallel batch ingestion
echo "Example 5: Batch with 10 parallel workers"
echo "Command: mahavishnu ingest batch urls.txt --parallel 10"
echo ""

# Example 6: Custom chunk size for long documents
echo "Example 6: Larger chunks for technical docs"
echo "Command: mahavishnu ingest url https://docs.example.com --chunk-size 2000 --chunk-overlap 400"
echo ""

# Example 7: Check ingestion stats
echo "Example 7: View ingestion system status"
echo "Command: mahavishnu ingest stats"
echo ""

echo "✨ For more information, run:"
echo "  mahavishnu ingest --help"
echo ""
