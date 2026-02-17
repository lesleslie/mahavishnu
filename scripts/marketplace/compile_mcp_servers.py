#!/usr/bin/env python3
"""
Compile unique MCP servers from all active project .mcp.json files.
Deduplicates and selects latest versions.
"""

import json
import re
from pathlib import Path
from typing import Any

# Active projects with .mcp.json files
ACTIVE_PROJECTS = [
    "acb",
    "crackerjack",
    "fastblocks",
    "splashstand",
]

PROJECTS_DIR = Path.home() / "Projects"


def parse_version(version_str: str | None) -> tuple[int, ...]:
    """Parse version string into tuple of integers for comparison."""
    if not version_str or version_str == "latest":
        # Latest always wins
        return (999999,)

    # Extract version numbers (handles @1.0.20, 0.6.0, 2025.9.25, etc.)
    match = re.search(r'(\d+(?:\.\d+)*)', version_str)
    if match:
        return tuple(int(x) for x in match.group(1).split('.'))
    return (0,)


def extract_package_info(server_config: dict[str, Any]) -> dict[str, Any]:
    """Extract package name and version from server configuration."""
    server_type = server_config.get("type", "unknown")

    if server_type == "stdio":
        command = server_config.get("command", "")
        args = server_config.get("args", [])
        env = server_config.get("env", {})

        # Find package specifier in args
        package = None
        for arg in args:
            if arg.startswith("-"):
                continue
            if "@" in arg or "/" in arg or arg.endswith("-mcp"):
                package = arg
                break

        if not package and args:
            # Use last non-flag arg
            package = [a for a in args if not a.startswith("-")][-1] if args else None

        # Extract version from package string
        version = None
        if package and "@" in package:
            parts = package.split("@")
            if len(parts) >= 2:
                version = parts[-1]  # Last part after @

        return {
            "type": "stdio",
            "command": command,
            "args": args,
            "package": package,
            "version": version,
            "env": env if env else None,
        }

    elif server_type == "http":
        url = server_config.get("url", "")
        return {
            "type": "http",
            "url": url,
            "version": None,  # HTTP servers don't have versions
        }

    return {"type": "unknown"}


def compile_mcp_servers() -> dict[str, dict[str, Any]]:
    """Compile all unique MCP servers with latest versions."""
    servers_map: dict[str, list[tuple[dict[str, Any], str]]] = {}

    # Read all .mcp.json files
    for project in ACTIVE_PROJECTS:
        mcp_file = PROJECTS_DIR / project / ".mcp.json"
        if not mcp_file.exists():
            print(f"⚠️  {project}/.mcp.json not found")
            continue

        print(f"📖 Reading {project}/.mcp.json")
        with open(mcp_file) as f:
            config = json.load(f)

        servers = config.get("mcpServers", {})
        for server_name, server_config in servers.items():
            info = extract_package_info(server_config)

            if server_name not in servers_map:
                servers_map[server_name] = []

            servers_map[server_name].append((info, project))

    # Deduplicate and select latest versions
    unique_servers = {}

    for server_name, variants in servers_map.items():
        if len(variants) == 1:
            # Only one version, use it
            unique_servers[server_name] = variants[0][0]
            print(f"✓ {server_name}: unique (from {variants[0][1]})")
        else:
            # Multiple versions, pick latest
            latest = max(
                variants,
                key=lambda x: parse_version(x[0].get("version"))
            )
            unique_servers[server_name] = latest[0]

            # Show comparison
            version_info = ", ".join([
                f"{proj}: {v.get('version') or 'no-version'}"
                for v, proj in variants
            ])
            print(f"✓ {server_name}: selected from {latest[1]} ({version_info})")

    return unique_servers


def categorize_servers(servers: dict[str, dict[str, Any]]) -> dict[str, list[str]]:
    """Categorize MCP servers by function."""
    categories = {
        "development": [],
        "git": [],
        "cloud": [],
        "database": [],
        "monitoring": [],
        "design": [],
        "testing": [],
        "ai": [],
        "automation": [],
        "custom": [],
    }

    for name, info in servers.items():
        # Categorize based on name
        if name in ["github", "gitlab"]:
            categories["git"].append(name)
        elif name in ["memory", "sequential-thinking", "context7"]:
            categories["ai"].append(name)
        elif name in ["cloud-run", "turso-cloud", "upstash"]:
            categories["cloud"].append(name)
        elif name in ["sentry", "logfire"]:
            categories["monitoring"].append(name)
        elif name in ["excalidraw", "penpot", "mermaid"]:
            categories["design"].append(name)
        elif name in ["playwright"]:
            categories["testing"].append(name)
        elif name in ["macos_automator", "peekaboo"]:
            categories["automation"].append(name)
        elif name in ["rust-filesystem"]:
            categories["development"].append(name)
        else:
            categories["custom"].append(name)

    # Remove empty categories
    return {k: v for k, v in categories.items() if v}


if __name__ == "__main__":
    print("🔍 Compiling MCP servers from active projects...\n")

    servers = compile_mcp_servers()

    print(f"\n📊 Total unique servers: {len(servers)}")

    categories = categorize_servers(servers)
    print(f"📊 Categories: {len(categories)}")

    for category, server_list in categories.items():
        print(f"  - {category}: {len(server_list)} servers")

    # Write output
    output = {
        "servers": servers,
        "categories": categories,
        "total_servers": len(servers),
    }

    output_file = Path.home() / ".claude" / "scripts" / "marketplace" / "compiled_mcp_servers.json"
    with open(output_file, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\n✅ Compiled servers saved to {output_file}")
