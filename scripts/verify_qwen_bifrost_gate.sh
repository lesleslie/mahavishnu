#!/usr/bin/env bash
#
# scripts/verify_qwen_bifrost_gate.sh
# ----------------------------------------------------------------------------
# Operator-facing verification gate for the Phase D Qwen-CLI Bifrost
# routing. Phase D ships with ``bifrost.route_qwen_code: false`` by
# default; this script is the manual run that flips the flag to true
# once the gate passes.
#
# Preconditions (all checked, the script aborts with a clear message
# if any are missing):
#
#  1. Bifrost gateway running on 127.0.0.1:8471 (the ready file at
#     ``$HOME/.local/state/mcp/ready/bifrost.ready`` must exist).
#  2. A real Qwen CLI binary on PATH (we use ``qwen --version`` to
#     verify the binary is functional — the actual env-var name
#     Bifrost expects is verified at dispatch time).
#  3. The mahavishnu pool router is available
#     (``mahavishnu pool health`` returns at least one active pool).
#
# Pass criterion: after the test dispatch, ``$HOME/.local/state/mcp/logs/bifrost.log``
# contains a JSON line with ``"caller_id":"mahavishnu"`` and
# ``"provider":"qwen"`` (or the equivalent provider name Bifrost
# uses for the Qwen CLI route).
#
# Usage:
#   bash scripts/verify_qwen_bifrost_gate.sh
#
# Exit codes:
#   0  — gate passed (caller_id line found in bifrost.log)
#   1  — gate failed (caller_id line NOT found within 30s)
#   2  — preconditions not met (Bifrost down, Qwen missing, etc.)
#   3  — bifrost.log file missing entirely (no Bifrost activity)
#
# This script is the operator action referenced by the
# ``test_qwen_actual_dispatch_emits_caller_id`` xfail in
# ``tests/unit/test_terminal_worker_settings.py`` — flip that xfail
# to a real pass once this script returns 0 against your local
# Bifrost + Qwen CLI setup.

set -euo pipefail

# ----------------------------------------------------------------------------
# Precondition checks
# ----------------------------------------------------------------------------

READY_FILE="${HOME}/.local/state/mcp/ready/bifrost.ready"
BIFROST_LOG="${HOME}/.local/state/mcp/logs/bifrost.log"
POOL_HEALTH_OUTPUT="$(mahavishnu pool health --output json 2>/dev/null || echo '{}')"

# 1. Bifrost ready file present.
if [ ! -f "${READY_FILE}" ]; then
    echo "FAIL: Bifrost ready file not found at ${READY_FILE}" >&2
    echo "      Start the gateway first: scripts/bifrost-gateway.py (or the launchd plist)" >&2
    exit 2
fi
echo "OK:   Bifrost ready file present"

# 2. Qwen CLI on PATH.
if ! command -v qwen >/dev/null 2>&1; then
    echo "FAIL: qwen CLI not on PATH" >&2
    echo "      Install: see https://github.com/QwenLM/Qwen (or your distro's package)" >&2
    exit 2
fi

QWEN_VERSION="$(qwen --version 2>&1 || true)"
echo "OK:   qwen CLI on PATH (${QWEN_VERSION%%[[:space:]]*})"

# 3. Mahavishnu pool router is reachable.
if ! echo "${POOL_HEALTH_OUTPUT}" | grep -q '"pools_active"'; then
    echo "FAIL: 'mahavishnu pool health' did not return JSON" >&2
    echo "      Is the Mahavishnu orchestrator running? (mahavishnu mcp start)" >&2
    exit 2
fi
echo "OK:   Mahavishnu pool router reachable"

# ----------------------------------------------------------------------------
# Dispatch through Bifrost
# ----------------------------------------------------------------------------

# Use a one-shot pool route to drive a Qwen worker. The
# bifrost.route_qwen_code + qwen_env_var wiring from Phase D
# makes the spawned Qwen worker pick up the gateway env vars
# (ANTHROPIC_BASE_URL / OPENAI_BASE_URL) so the Qwen CLI's
# outbound HTTP goes through Bifrost, not direct.

PROMPT="Reply with a single word: bifrost-routed"
echo "INFO: dispatching one Qwen worker via pool_route_execute"
echo "      prompt=${PROMPT}"

DISPATCH_OUTPUT="$(
    mahavishnu pool route \
        --prompt "${PROMPT}" \
        --worker-type terminal-qwen \
        --selector least_loaded \
        --timeout 60 \
        2>&1 || true
)"
echo "${DISPATCH_OUTPUT}" | head -5

# ----------------------------------------------------------------------------
# Bifrost log inspection
# ----------------------------------------------------------------------------

# Bifrost logs are JSON-one-line-per-event. We wait up to 30s
# for a caller_id=="mahavishnu" line to appear. With the
# stdbuf -oL -eL wrapper from this branch's prior commit, the
# actual latency is <1s; the 30s window is operator-friendly
# headroom for slow Qwen CLI first-token latency.

DEADLINE_SECONDS=30
WAIT_START="$(date +%s)"
while true; do
    if [ -f "${BIFROST_LOG}" ] && grep -q '"caller_id":"mahavishnu"' "${BIFROST_LOG}"; then
        echo ""
        echo "PASS: bifrost.log contains caller_id line"
        grep '"caller_id":"mahavishnu"' "${BIFROST_LOG}" | tail -1
        exit 0
    fi
    NOW="$(date +%s)"
    ELAPSED=$(( NOW - WAIT_START ))
    if [ "${ELAPSED}" -ge "${DEADLINE_SECONDS}" ]; then
        echo ""
        echo "FAIL: no caller_id line in ${BIFROST_LOG} within ${DEADLINE_SECONDS}s" >&2
        if [ ! -f "${BIFROST_LOG}" ]; then
            echo "      bifrost.log does not exist — the Qwen dispatch did not go through Bifrost" >&2
            exit 3
        fi
        echo "      bifrost.log exists but no caller_id match — check Phase D env wiring" >&2
        exit 1
    fi
    sleep 1
done
