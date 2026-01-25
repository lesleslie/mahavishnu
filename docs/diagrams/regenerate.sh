#!/bin/bash
# Quick script to regenerate system architecture diagram from ARCHITECTURE.md
# Usage: ./regenerate.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "🔍 Extracting Mermaid diagram from ARCHITECTURE.md..."
sed -n '/```mermaid/,/```/p' "$PROJECT_ROOT/ARCHITECTURE.md" | sed '1d;$d' > /tmp/mahavishnu_arch.mmd

echo "📊 Checking for mermaid-cli..."
if command -v mermaid-cli &> /dev/null; then
    echo "✅ Using mermaid-cli (fast)..."
    cd "$PROJECT_ROOT"
    mermaid-cli -i /tmp/mahavishnu_arch.mmd \
        -o docs/diagrams/system-architecture.png \
        -w 1600 -H 1200
    echo "✅ Diagram generated: docs/diagrams/system-architecture.png"
else
    echo "⚠️  mermaid-cli not found. Using web-based method..."
    echo ""
    echo "📋 Manual steps:"
    echo "1. Copy contents of /tmp/mahavishnu_arch.mmd:"
    cat /tmp/mahavishnu_arch.mmd
    echo ""
    echo "2. Go to: https://mermaid.live"
    echo "3. Paste the code above"
    echo "4. Download as PNG"
    echo "5. Save to: $PROJECT_ROOT/docs/diagrams/system-architecture.png"
    echo ""
    echo "💡 Alternative: Install mermaid-cli:"
    echo "   npm install -g @mermaid-cli/mermaid-cli"
fi

echo ""
echo "🎉 Regeneration complete!"
