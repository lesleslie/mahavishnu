#!/usr/bin/env bash
# minimax_health.sh - Probe the MiniMax API and related Bodai MCP wiring.
#
# Verifies (in order):
#   1. Env vars present in parent shell (MINIMAX_API_KEY required; warns if
#      MINIMAX_API_HOST missing — the minimax-coding-plan MCP server injects it
#      via .mcp.json, so absence in the shell is normal but worth flagging).
#   2. DNS resolves api.minimax.io.
#   3. TLS handshake to api.minimax.io:443 (skipped if openssl unavailable).
#   4. OpenAI-shaped GET /v1/models  (catalog + auth check).
#   5. Anthropic-shaped GET /anthropic/v1/models.
#   6. Tiny chat completion with max_tokens=1  (true ping, no reasoning drain).
#   7. 5x sustained /v1/models  (rules out intermittent flakiness).
#   8. Recent MiniMax errors in ~/.mahavishnu/logs/mcp.log (if present).
#   9. [optional] minimax-coding-plan uvx process is running.
#  10. [optional] Mahavishnu MCP /health endpoint on http://localhost:8680/health.
#
# Usage:
#   scripts/minimax_health.sh                  # full probe
#   scripts/minimax_health.sh --json          # machine-readable JSON output
#   scripts/minimax_health.sh --no-mcp        # skip MCP-process and Mahavishnu checks
#   scripts/minimax_health.sh --help
#
# Exit codes:
#   0  all critical probes passed
#   1  one or more critical probes failed (API/DNS/TLS/auth)
#   2  invalid arguments

set -uo pipefail  # not -e: per-probe failures must not abort the run

# ---- defaults & args ---------------------------------------------------------

API_HOST="${MINIMAX_API_HOST:-https://api.minimax.io}"
ANTHROPIC_PROXY_PATH="/anthropic"
LOG_DIR="${HOME}/.mahavishnu/logs"
MCP_LOG="${LOG_DIR}/mcp.log"
MAHAVISHNU_HEALTH_URL="http://localhost:8680/health"

JSON_MODE=0
SKIP_MCP=0
TIMEOUT_SECS=10
QUIET=0  # 1 = suppress human-readable output (used when JSON_MODE=1)

usage() {
  sed -n '2,22p' "$0" | sed 's/^# \{0,1\}//'
  exit 2
}

while [ $# -gt 0 ]; do
  case "$1" in
    --json) JSON_MODE=1; QUIET=1 ;;
    --no-mcp) SKIP_MCP=1 ;;
    --timeout) shift; TIMEOUT_SECS="${1:-10}" ;;
    --api-host) shift; API_HOST="${1:-https://api.minimax.io}" ;;
    -h|--help) usage ;;
    *) echo "unknown arg: $1" >&2; usage ;;
  esac
  shift
done

# ---- color helpers -----------------------------------------------------------

if [ -t 1 ] && [ "$QUIET" -eq 0 ]; then
  C_RED='\033[0;31m'; C_GRN='\033[0;32m'; C_YEL='\033[0;33m'
  C_DIM='\033[2m'; C_BOLD='\033[1m'; C_OFF='\033[0m'
else
  C_RED=''; C_GRN=''; C_YEL=''; C_DIM=''; C_BOLD=''; C_OFF=''
fi

# result tracking: PROBE_RESULTS is a newline-separated list of "name|status|detail"
PROBE_RESULTS=""

# _h <fmt> [args...]  — print only when human output is enabled
_h() { [ "$QUIET" -eq 0 ] && printf "$@"; }

record() {
  local name="$1" status="$2" detail="$3"
  PROBE_RESULTS="${PROBE_RESULTS}${name}|${status}|${detail}"$'\n'
}

pass() { _h '  %s✓%s %-40s %s\n' "$C_GRN" "$C_OFF" "$1" "$2"; record "$1" "pass" "$2"; }
warn() { _h '  %s!%s %-40s %s\n' "$C_YEL" "$C_OFF" "$1" "$2"; record "$1" "warn" "$2"; }
fail() { _h '  %s✗%s %-40s %s\n' "$C_RED" "$C_OFF" "$1" "$2"; record "$1" "fail" "$2"; }
skip() { _h '  %s-%s %-40s %s\n' "$C_DIM" "$C_OFF" "$1" "$2"; record "$1" "skip" "$2"; }

# tally counters + emit_json must exist before the env-var early-bail can call them
TOTAL=0; PASS=0; WARN=0; FAIL=0; SKIP=0

emit_json() {
  printf '{"api_host":"%s","total":%d,"pass":%d,"warn":%d,"fail":%d,"skip":%d,"probes":[' \
    "$API_HOST" "$TOTAL" "$PASS" "$WARN" "$FAIL" "$SKIP"
  local first=1
  while IFS='|' read -r name status detail; do
    [ -z "$name" ] && continue
    [ "$first" -eq 0 ] && printf ','
    first=0
    # escape backslashes and quotes in detail
    local d="${detail//\\/\\\\}"; d="${d//\"/\\\"}"
    printf '{"name":"%s","status":"%s","detail":"%s"}' "$name" "$status" "$d"
  done <<< "$PROBE_RESULTS"
  printf ']}\n'
}

# tiny http probe: prints "HTTP_CODE TIME_TOTAL" or "ERR:reason"
http_probe() {
  local url="$1"; shift
  local out
  out="$(curl -sS --max-time "$TIMEOUT_SECS" -o /dev/null \
    -w '%{http_code} %{time_total}' "$@" "$url" 2>&1)" || {
      echo "ERR:${out##*curl: }"
      return 0
    }
  echo "$out"
}

# ---- header ------------------------------------------------------------------

_h '%sMiniMax API health probe%s\n' "$C_BOLD" "$C_OFF"
_h '%sAPI host: %s    timeout: %ss    log: %s%s\n' \
  "$C_DIM" "$API_HOST" "$TIMEOUT_SECS" "$MCP_LOG" "$C_OFF"
_h '\n'

# ---- 1. env vars -------------------------------------------------------------

if [ -n "${MINIMAX_API_KEY:-}" ]; then
  pass "env.MINIMAX_API_KEY" "set (length=${#MINIMAX_API_KEY})"
else
  fail "env.MINIMAX_API_KEY" "UNSET — export it before running"
fi

if [ -n "${MINIMAX_API_HOST:-}" ]; then
  pass "env.MINIMAX_API_HOST" "set to $MINIMAX_API_HOST"
else
  warn "env.MINIMAX_API_HOST" "unset in parent shell (minimax-coding-plan MCP injects via .mcp.json — not fatal here)"
fi

# If no key, every later probe is doomed; bail with a clean summary.
if [ -z "${MINIMAX_API_KEY:-}" ]; then
  _h '\n%sMINIMAX_API_KEY is unset — skipping all network probes.%s\n' "$C_YEL" "$C_OFF"
  if [ "$JSON_MODE" -eq 1 ]; then emit_json; fi
  exit 1
fi

_h '\n'

# ---- 2. DNS ------------------------------------------------------------------

DNS_OUT="$(getent hosts api.minimax.io 2>/dev/null || nslookup api.minimax.io 2>/dev/null | awk '/^Address: / && !seen[$2]++ {print $2; exit}')"
if [ -n "$DNS_OUT" ]; then
  pass "dns.api.minimax.io" "resolves → $DNS_OUT"
else
  fail "dns.api.minimax.io" "no A record returned"
fi

# ---- 3. TLS handshake --------------------------------------------------------

if command -v openssl >/dev/null 2>&1; then
  TLS_OUT="$(echo | timeout "$TIMEOUT_SECS" openssl s_client -connect "api.minimax.io:443" -servername "api.minimax.io" 2>/dev/null | grep -E 'Verify return code|subject=' | head -2 | tr '\n' '|')"
  if echo "$TLS_OUT" | grep -q "Verify return code: 0"; then
    pass "tls.api.minimax.io:443" "ok"
  else
    fail "tls.api.minimax.io:443" "TLS verify failed (${TLS_OUT:-no output})"
  fi
else
  skip "tls.api.minimax.io:443" "openssl not installed"
fi

_h '\n%s--- API probes ---%s\n' "$C_BOLD" "$C_OFF"

# ---- 4. OpenAI /v1/models ----------------------------------------------------

RES="$(http_probe "$API_HOST/v1/models" -H "Authorization: Bearer $MINIMAX_API_KEY")"
CODE="${RES%% *}"; TIME="${RES##* }"
if [ "${CODE:-0}" = "200" ]; then
  COUNT="$(curl -sS --max-time "$TIMEOUT_SECS" -H "Authorization: Bearer $MINIMAX_API_KEY" "$API_HOST/v1/models" 2>/dev/null | grep -oE '"id":"[^"]+"' | wc -l | tr -d ' ')"
  pass "api.GET /v1/models" "HTTP $CODE in ${TIME}s ($COUNT models)"
else
  fail "api.GET /v1/models" "${RES:-no response}"
fi

# ---- 5. Anthropic /v1/models -------------------------------------------------

RES="$(http_probe "$API_HOST${ANTHROPIC_PROXY_PATH}/v1/models" -H "x-api-key: $MINIMAX_API_KEY" -H "anthropic-version: 2023-06-01")"
CODE="${RES%% *}"; TIME="${RES##* }"
if [ "${CODE:-0}" = "200" ]; then
  pass "api.GET /anthropic/v1/models" "HTTP $CODE in ${TIME}s"
else
  fail "api.GET /anthropic/v1/models" "${RES:-no response}"
fi

# ---- 6. chat completion (max_tokens=1) ---------------------------------------

CHAT_BODY='{"model":"MiniMax-M3","max_tokens":1,"messages":[{"role":"user","content":"."}]}'
RES="$(http_probe "$API_HOST/v1/chat/completions" -X POST \
  -H "Authorization: Bearer $MINIMAX_API_KEY" -H "Content-Type: application/json" \
  -d "$CHAT_BODY")"
CODE="${RES%% *}"; TIME="${RES##* }"
if [ "${CODE:-0}" = "200" ]; then
  pass "api.POST /v1/chat/completions" "HTTP $CODE in ${TIME}s (max_tokens=1)"
elif [ "${CODE:-0}" = "401" ] || [ "${CODE:-0}" = "403" ]; then
  fail "api.POST /v1/chat/completions" "auth rejected (HTTP $CODE) — check MINIMAX_API_KEY"
else
  fail "api.POST /v1/chat/completions" "${RES:-no response}"
fi

# ---- 7. sustained latency (5x /v1/models) ------------------------------------

_h '\n%s--- Sustained latency (5x /v1/models) ---%s\n' "$C_BOLD" "$C_OFF"
SLOW=0
SAMPLES=""
for i in 1 2 3 4 5; do
  RES="$(http_probe "$API_HOST/v1/models" -H "Authorization: Bearer $MINIMAX_API_KEY")"
  CODE="${RES%% *}"; TIME="${RES##* }"
  _h '  attempt %d: HTTP %s in %ss\n' "$i" "${CODE:-ERR}" "${TIME:-?}"
  SAMPLES="${SAMPLES}${TIME:-?} "
  if [ "${CODE:-0}" != "200" ]; then SLOW=$((SLOW + 1)); fi
  # numeric compare via awk — pass TIME as a variable, not via string interpolation
  if [ -n "${TIME:-}" ] && awk -v t="$TIME" 'BEGIN{exit !(t+0 > 1.0)}' 2>/dev/null; then
    SLOW=$((SLOW + 1))
  fi
done
if [ "$SLOW" -eq 0 ]; then
  pass "sustained.5x" "all under 1.0s (samples: $SAMPLES)"
else
  warn "sustained.5x" "$SLOW of 5 samples were slow or non-200 (samples: $SAMPLES)"
fi

# ---- 8. recent MiniMax errors in mcp.log -------------------------------------

_h '\n%s--- Logs ---%s\n' "$C_BOLD" "$C_OFF"
if [ -r "$MCP_LOG" ]; then
  ERRORS="$(tail -500 "$MCP_LOG" 2>/dev/null | grep -iE 'minimax' | grep -iE 'error|timeout|failed' | tail -5)"
  if [ -n "$ERRORS" ]; then
    warn "log.recent errors" "$(echo "$ERRORS" | wc -l | tr -d ' ') minimax-related (last 500 log lines):"
    [ "$QUIET" -eq 0 ] && echo "$ERRORS" | sed 's/^/      /'
  else
    pass "log.recent errors" "no minimax errors in last 500 lines of $MCP_LOG"
  fi
else
  skip "log.recent errors" "$MCP_LOG not readable"
fi

# ---- 9-10. MCP & Mahavishnu (skippable) --------------------------------------

if [ "$SKIP_MCP" -eq 0 ]; then
  _h '\n%s--- MCP wiring ---%s\n' "$C_BOLD" "$C_OFF"

  # 9. minimax-coding-plan uvx process
  if ps -axo command= 2>/dev/null | grep -q '[m]inimax-coding-plan'; then
    PID="$(ps -axo pid,command= 2>/dev/null | grep '[m]inimax-coding-plan' | awk '{print $1}' | head -1)"
    pass "mcp.minimax-coding-plan" "running (pid $PID)"
  else
    warn "mcp.minimax-coding-plan" "no uvx process found (server may not be started in this shell)"
  fi

  # 10. Mahavishnu /health
  RES="$(http_probe "$MAHAVISHNU_HEALTH_URL")"
  CODE="${RES%% *}"; TIME="${RES##* }"
  if [ "${CODE:-0}" = "200" ]; then
    pass "mcp.mahavishnu /health" "HTTP $CODE in ${TIME}s"
  elif [ "${CODE:-0}" = "000" ] || [ -z "${CODE:-}" ]; then
    skip "mcp.mahavishnu /health" "not reachable (server not started?)"
  else
    fail "mcp.mahavishnu /health" "HTTP $CODE in ${TIME}s"
  fi
fi

# ---- summary -----------------------------------------------------------------

_h '\n%s--- Summary ---%s\n' "$C_BOLD" "$C_OFF"
# tally counters were initialized before emit_json; just sum them here
while IFS='|' read -r name status detail; do
  [ -z "$name" ] && continue
  TOTAL=$((TOTAL + 1))
  case "$status" in
    pass) PASS=$((PASS+1)) ;;
    warn) WARN=$((WARN+1)) ;;
    fail) FAIL=$((FAIL+1)) ;;
    skip) SKIP=$((SKIP+1)) ;;
  esac
done <<< "$PROBE_RESULTS"

if [ "$FAIL" -eq 0 ]; then
  _h '%s✓ all critical probes passed%s  (%d pass, %d warn, %d skip, %d fail)\n' \
    "$C_GRN" "$C_OFF" "$PASS" "$WARN" "$SKIP" "$FAIL"
else
  _h '%s✗ %d critical probe(s) failed%s  (%d pass, %d warn, %d skip, %d fail)\n' \
    "$C_RED" "$FAIL" "$C_OFF" "$PASS" "$WARN" "$SKIP" "$FAIL"
fi

if [ "$JSON_MODE" -eq 1 ]; then
  emit_json
fi

# exit code: fail if any critical probe failed
[ "$FAIL" -eq 0 ]
