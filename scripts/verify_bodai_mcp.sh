#!/usr/bin/env bash
# verify_bodai_mcp.sh — Confirm Bodai MCP connectivity after session restart.
#
# Run this AFTER `! claude agents` (or any other action that restarts the
# Claude session supervisor). It does two things:
#
#   1. Probe each /health endpoint via direct HTTP. Confirms the launchd
#      wrappers and the underlying servers are healthy.
#
#   2. Probe each /mcp endpoint with a JSON-RPC initialize handshake.
#      Confirms the HTTP-transport MCP server is actually serving the
#      JSON-RPC protocol — which is what the Claude client uses to
#      register tools.
#
# If step 1 passes but step 2 fails on any server, that server's MCP
# route is broken. If step 2 passes but the in-session tool list still
# shows "No such tool available" for that server, the issue is the
# supervisor (bg worker wasn't established for that MCP server).
#
# Usage:  bash scripts/verify_bodai_mcp.sh
# Exit 0 = all servers healthy AND MCP-ready.
# Exit 1 = at least one server failed.

set -u

declare -a SERVERS=(
  "mahavishnu:8680"
  "akosha:8682"
  "dhara:8683"
  "session-buddy:8678"
  "crackerjack:8676"
)

step1_fail=0
step2_fail=0

echo "============================================================"
echo "Step 1 — HTTP /health probes"
echo "============================================================"
for entry in "${SERVERS[@]}"; do
  name="${entry%%:*}"
  port="${entry##*:}"
  body=$(curl -s -m 3 -w '\nHTTP_STATUS=%{http_code}' "http://127.0.0.1:${port}/health" 2>&1)
  status=$(echo "$body" | grep -o 'HTTP_STATUS=[0-9]*' | cut -d= -f2)
  payload=$(echo "$body" | grep -v 'HTTP_STATUS=' | head -c 120 | tr '\n' ' ')
  if [ "$status" = "200" ]; then
    printf "  %-15s port %s  ✅ 200  %s\n" "$name" "$port" "$payload"
  else
    printf "  %-15s port %s  ❌ %s  %s\n" "$name" "$port" "$status" "$payload"
    step1_fail=$((step1_fail + 1))
  fi
done

echo
echo "============================================================"
echo "Step 2 — MCP JSON-RPC initialize handshake (HTTP transport)"
echo "============================================================"
for entry in "${SERVERS[@]}"; do
  name="${entry%%:*}"
  port="${entry##*:}"
  # Minimal JSON-RPC 2.0 initialize message per MCP spec.
  req='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"verify-bodai-mcp","version":"1.0.0"}}}'
  body=$(curl -s -m 5 -w '\nHTTP_STATUS=%{http_code}' \
    -H 'Content-Type: application/json' \
    -H 'Accept: application/json, text/event-stream' \
    -X POST -d "$req" \
    "http://127.0.0.1:${port}/mcp" 2>&1)
  status=$(echo "$body" | grep -o 'HTTP_STATUS=[0-9]*' | cut -d= -f2)
  payload=$(echo "$body" | grep -v 'HTTP_STATUS=' | head -c 200 | tr '\n' ' ')
  if echo "$payload" | grep -q '"protocolVersion"'; then
    printf "  %-15s port %s  ✅ MCP handshake ok  %s\n" "$name" "$port" "$payload"
  else
    printf "  %-15s port %s  ❌ HTTP=%s  %s\n" "$name" "$port" "$status" "$payload"
    step2_fail=$((step2_fail + 1))
  fi
done

echo
echo "============================================================"
echo "Step 3 — Session-side tool registration check (manual)"
echo "============================================================"
cat <<'EOF'
The above probes confirm the SERVERS are healthy and serving MCP. To
verify the SESSION sees them, ask Claude (in this conversation):

    "Use mcp__mahavishnu__discover_tools and report how many tools
     each Bodai MCP server exposes."

If that prompt returns:
  - Tool counts for all 5 servers  → session registration is fine.
  - "No such tool available" for any → the supervisor's bg worker
    wasn't established for that server's MCP client connection.
    See CLAUDE.md "Degraded mode" guidance and the bodai-radar skill.
EOF

echo
echo "============================================================"
echo "Summary"
echo "============================================================"
if [ "$step1_fail" -eq 0 ] && [ "$step2_fail" -eq 0 ]; then
  echo "✅ All 5 Bodai MCP servers healthy AND MCP-ready."
  exit 0
else
  echo "❌ Failures: step1=${step1_fail}  step2=${step2_fail}"
  exit 1
fi
