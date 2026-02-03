#!/usr/bin/env python3
"""Quick start script for Oneiric MCP integration.

This script demonstrates the simplest way to get started with Oneiric MCP
integration in Mahavishnu.

Prerequisites:
1. Oneiric MCP server running on port 8679
   cd /Users/les/Projects/oneiric-mcp
   python -m oneiric_mcp --port 8679

2. Mahavishnu configured with oneiric_mcp.enabled=true

Usage:
    python examples/quickstart_oneiric.py
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from mahavishnu.core.oneiric_client import (
    OneiricMCPClient,
    OneiricMCPConfig,
)


async def main():
    """Quick start demonstration."""
    print("=" * 60)
    print("Oneiric MCP Integration - Quick Start")
    print("=" * 60)
    print()

    # Step 1: Configure client
    print("Step 1: Configuring Oneiric MCP client...")
    config = OneiricMCPConfig(
        enabled=True,
        grpc_host="localhost",
        grpc_port=8679,  # Insecure dev port
        use_tls=False,
        timeout_sec=10,
    )
    print("  ✓ Configuration created")
    print(f"    Host: {config.grpc_host}")
    print(f"    Port: {config.grpc_port}")
    print()

    # Step 2: Create client
    print("Step 2: Creating client...")
    client = OneiricMCPClient(config)
    print("  ✓ Client created")
    print()

    try:
        # Step 3: Check connection
        print("Step 3: Checking connection...")
        health = await client.health_check()

        if health['status'] != 'healthy':
            print(f"  ✗ Connection failed: {health.get('error', 'Unknown error')}")
            print()
            print("Troubleshooting:")
            print("  1. Ensure Oneiric MCP server is running:")
            print("     cd /Users/les/Projects/oneiric-mcp")
            print("     python -m oneiric_mcp --port 8679")
            print()
            print("  2. Check port is correct:")
            print("     - Development: 8679 (insecure)")
            print("     - Production: 8680 (TLS)")
            print()
            return 1

        print("  ✓ Connected successfully")
        print(f"    Status: {health['status']}")
        print(f"    Adapters available: {health['adapter_count']}")
        print()

        # Step 4: List adapters
        print("Step 4: Listing available adapters...")
        adapters = await client.list_adapters()

        print(f"  ✓ Found {len(adapters)} adapters")

        if adapters:
            print()
            print("  Sample adapters:")
            for adapter in adapters[:5]:  # Show first 5
                print(f"    - {adapter.adapter_id}")
                print(f"      Category: {adapter.category}, Provider: {adapter.provider}")
            if len(adapters) > 5:
                print(f"    ... and {len(adapters) - 5} more")
        else:
            print("  No adapters found (register some adapters first)")
        print()

        # Step 5: Filter by category
        if adapters:
            print("Step 5: Filtering adapters by category...")

            # Get unique categories
            categories = set(a.category for a in adapters)
            print(f"  Available categories: {', '.join(sorted(categories))}")
            print()

            # Example: List storage adapters
            storage_adapters = await client.list_adapters(category="storage")
            print(f"  ✓ Storage adapters: {len(storage_adapters)}")

            if storage_adapters:
                for adapter in storage_adapters[:3]:
                    print(f"    - {adapter.provider}: {adapter.adapter_id}")
            print()

        # Step 6: Health check example
        if adapters:
            print("Step 6: Checking adapter health...")

            # Check health of first adapter
            first_adapter = adapters[0]
            is_healthy = await client.check_adapter_health(first_adapter.adapter_id)

            status_icon = "✓" if is_healthy else "✗"
            print(f"  {status_icon} {first_adapter.adapter_id}: {'healthy' if is_healthy else 'unhealthy'}")
            print()

        # Step 7: Cache demonstration
        print("Step 7: Testing cache performance...")

        import time

        # First query (cache miss)
        start = time.time()
        await client.list_adapters()
        duration1 = time.time() - start

        # Second query (cache hit)
        start = time.time()
        await client.list_adapters()
        duration2 = time.time() - start

        print(f"  First query: {duration1*1000:.1f}ms (cache miss)")
        print(f"  Second query: {duration2*1000:.1f}ms (cache hit)")
        print(f"  Speedup: {duration1/duration2:.1f}x faster with cache")
        print()

        # Success!
        print("=" * 60)
        print("✓ Quick start completed successfully!")
        print("=" * 60)
        print()
        print("Next steps:")
        print("  1. Explore MCP tools:")
        print("     - oneiric_list_adapters")
        print("     - oneiric_resolve_adapter")
        print("     - oneiric_check_health")
        print()
        print("  2. Try workflow examples:")
        print("     python examples/oneiric_workflow_examples.py")
        print()
        print("  3. Read documentation:")
        print("     docs/ONEIRIC_MCP_INTEGRATION.md")
        print()

        return 0

    except Exception as e:
        print(f"  ✗ Error: {e}")
        print()
        print("Troubleshooting:")
        print("  1. Ensure Oneiric MCP server is running on port 8679")
        print("  2. Check network connectivity:")
        print("     telnet localhost 8679")
        print("  3. Verify configuration in settings/mahavishnu.yaml")
        print("  4. Check logs for detailed error messages")
        print()
        return 1

    finally:
        # Always cleanup
        await client.close()
        print("  ✓ Client closed")


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
