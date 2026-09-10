# Diagram Regeneration Guide

**Date**: 2026-01-24
**Purpose**: Regenerate PNG diagrams to match corrected architecture

______________________________________________________________________

## Overview

The existing PNG diagrams in `docs/diagrams/` were generated from the old architecture showing 6 orchestration engines (Airflow, CrewAI, LangGraph, Agno, Prefect, LlamaIndex). These need to be regenerated to show the **correct 3-adapter architecture**.

______________________________________________________________________

## Current Diagram Status

> **Cleanup (2026-09-09):** All pre-rendered PNGs were removed from `docs/diagrams/`.
> They had no references from any active markdown documentation — only from this
> regen guide and the mermaid sources in `ARCHITECTURE.md`. PNGs can be
> regenerated on demand via the methods below; storing stale bitmaps is no
> longer useful.

| Diagram | Created | Status | Action Needed |
|---------|---------|--------|--------------|
| (no committed PNGs) | — | — | Regenerate from `ARCHITECTURE.md` mermaid sources when needed |

______________________________________________________________________

## Mermaid Source Location

The corrected Mermaid diagram is now in:

- **File**: `/Users/les/Projects/mahavishnu/ARCHITECTURE.md`
- **Lines**: 197-275 (approx)
- **Section**: "## Architecture Diagram"

______________________________________________________________________

## Method 1: Web-Based Mermaid Live Editor (Recommended)

### Steps:

1. **Extract Mermaid code**:

   ````bash
   sed -n '/```mermaid/,/```/p' /Users/les/Projects/mahavishnu/ARCHITECTURE.md | sed '1d;$d' > /tmp/arch_diagram.mmd
   ````

1. **Open Mermaid Live Editor**:

   - Go to: https://mermaid.live
   - Paste the contents of `/tmp/arch_diagram.mmd`

1. **Export as PNG**:

   - Click "Download PNG" or "Download SVG"
   - Save to `/Users/les/Projects/mahavishnu/docs/diagrams/system-architecture.png`

1. **Optional: Generate high-resolution SVG**:

   - Choose SVG for vector format (better for scaling)
   - Convert to PNG using: `svgexport -o system-architecture.png`

______________________________________________________________________

## Method 2: Python with kaleido (Developer Friendly)

### Prerequisites:

```bash
pip install kaleido
```

### Steps:

1. **Create Python script**:

   ```python
   # /tmp/generate_diagram.py
   import kaleido

   with open('/tmp/arch_diagram.mmd', 'r') as f:
       mermaid_code = f.read()

   kaleido.render(
       mermaid_code,
       output='png',
       output_file='docs/diagrams/system-architecture.png',
       width=1600,
       height=1200
   )
   ```

1. **Run generation**:

   ```bash
   cd /Users/les/Projects/mahavishnu
   python /tmp/generate_diagram.py
   ```

______________________________________________________________________

## Method 3: Docker with mermaid-cli (Isolated)

### Steps:

1. **Run mermaid-cli in Docker**:
   ````bash
   cd /Users/les/Projects/mahavishnu

   # Extract Mermaid code
   sed -n '/```mermaid/,/```/p' ARCHITECTURE.md | sed '1d;$d' > /tmp/arch_diagram.mmd

   # Generate PNG via Docker
   docker run -v /tmp:/data -w /data minlag/mermaid-cli -i arch_diagram.mmd -o system-architecture.png

   # Copy back
   docker cp <container_id>:/data/system-architecture.png docs/diagrams/
   ````

______________________________________________________________________

## Method 4: Online API (Automated)

### Using mermaid.ink API:

````bash
curl -X POST \
  -H 'Content-Type: text/plain' \
  -d "$(sed -n '/```mermaid/,/```/p' ARCHITECTURE.md | sed '1d;$d')" \
  https://mermaid.ink/png/system-architecture.png \
  -o docs/diagrams/system-architecture.png
````

______________________________________________________________________

## Recommended Quick Start (Fastest)

### For Mac/Linux (Command Line):

````bash
# 1. Install mermaid-cli
npm install -g @mermaid-cli/mermaid-cli

# 2. Extract and generate
cd /Users/les/Projects/mahavishnu
sed -n '/```mermaid/,/```/p' ARCHITECTURE.md | sed '1d;$d' > /tmp/arch.mmd
mermaid-cli -i /tmp/arch.mmd -o docs/diagrams/system-architecture.png -w 1600 -H 1200
````

### For Windows/Linux GUI (Easiest):

1. Extract Mermaid code from ARCHITECTUME.md (lines 199-270)
1. Go to https://mermaid.live
1. Paste code
1. Download PNG
1. Save to `docs/diagrams/system-architecture.png`

______________________________________________________________________

## Verification

After generating the new diagram, verify it shows:

**✅ Correct Adapters** (3 total):

- LlamaIndexAdapter (green/working)
- PrefectAdapter (yellow/stub)
- AgnoAdapter (yellow/stub)

**❌ NOT Present** (deprecated):

- Airflow
- CrewAI
- LangGraph

**✅ Other Components Present**:

- CLI, MCP Server, MahavishnuApp
- Config, Logging, Auth
- Terminal Management
- Repository Management
- Quality & Operations (QC, Session-Buddy, Metrics)

______________________________________________________________________

## Automated Regeneration Script

Create this script for easy regeneration:

````bash
#!/bin/bash
# /Users/les/Projects/mahahvishnu/docs/diagrams/regenerate.sh

set -e

echo "Extracting Mermaid diagram from ARCHITECTURE.md..."
sed -n '/```mermaid/,/```/p' ../../ARCHITECTURE.md | sed '1d;$d' > /tmp/arch_diagram.mmd

echo "Generating PNG diagram..."
cd /Users/les/Projects/mahavishnu

# Method 1: mermaid-cli (if installed)
if command -v mermaid-cli &> /dev/null; then
    echo "Using mermaid-cli..."
    mermaid-cli -i /tmp/arch_diagram.mmd \
        -o docs/diagrams/system-architecture.png \
        -w 1600 -H 1200
else
    echo "mermaid-cli not found. Using web-based method..."
    echo "1. Copy contents of /tmp/arch_diagram.mmd"
    echo "2. Go to https://mermaid.live"
    echo "3. Paste and download as PNG"
    echo "4. Save to: docs/diagrams/system-architecture.png"
fi

echo "Diagram regeneration complete!"
````

Make executable:

```bash
chmod +x /Users/les/Projects/mahavishnu/docs/diagrams/regenerate.sh
```

Run anytime:

```bash
/Users/les/Projects/mahavishnu/docs/diagrams/regenerate.sh
```

______________________________________________________________________

## Summary

**✅ Done** (2026-01-24):

- Added corrected Mermaid diagram to ARCHITECTURE.md
- Shows actual 3 adapters (not deprecated 6)
- Clear status indicators with color coding
- Single source of truth for architecture

**✅ Cleanup (2026-09-09)**:

- Removed 8 stale PNG bitmaps from `docs/diagrams/` (no active doc referenced them)
- Removed `git-branching-strategy.png` (never tracked in any regen manifest)
- Mermaid source remains in `ARCHITECTURE.md`; regenerate on demand via methods below

**📋 To Do**:

- If a PNG is needed for a doc/PR, regenerate it from the mermaid source in `ARCHITECTURE.md`
- Otherwise, leave only the mermaid sources in version control

**Note**: The old PNG diagrams have been replaced with the corrected architecture diagram showing the actual 3 adapters.

______________________________________________________________________

## Regeneration Method Used (2026-01-24)

**Tools (at the time)**:

- Mermaid MCP server (localhost:3033) — **since uninstalled 2026-09-09**
- rsvg-convert for SVG→PNG conversion

**Process (as run)**:

1. Extracted Mermaid code from ARCHITECTURE.md (lines 197-275)
1. Generated SVG via `mcp__mermaid__generate_mermaid_diagram` (outputType: svg)
1. Converted to PNG using `rsvg-convert -w 1600 -h 1200`

**Note**: With the MCP server removed, regenerate via Method 3 (mermaid-cli):

```bash
mermaid-cli -i /tmp/arch_diagram.mmd -o docs/diagrams/system-architecture.svg
rsvg-convert -w 1600 -h 1200 docs/diagrams/system-architecture.svg -o docs/diagrams/system-architecture.png
```

**Result**:

- ✅ SVG: 2856x684 viewBox, vector format
- ✅ PNG: 1600x1200, 8-bit RGBA, 61KB
- ✅ Correct 3 adapters shown with proper status indicators
