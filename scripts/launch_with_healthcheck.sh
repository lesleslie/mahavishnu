#!/bin/bash
# launch_with_healthcheck.sh
#
# Wraps an MCP server launch with a post-start /health smoke check.
#
# Behavior:
#   1. Parse args: <health-url> [--timeout SECONDS=30] -- <command> [args...]
#   2. Start <command> in the background; capture its PID.
#   3. Poll curl -fsS <health-url> every 0.5s up to --timeout seconds.
#   4. On success: wait for the command and propagate its exit code.
#   5. On timeout or curl error: kill the command, exit 1.
#      This way launchd's KeepAlive.Crashed=true will trigger a restart,
#      surfacing silent pre-bind crashes in `launchctl list` exit codes
#      instead of as log-only restart storms.
#
# Usage example (from a launchd plist):
#   <string>/Users/les/.local/state/mcp/scripts/launch_with_healthcheck.sh</string>
#   <string>http://127.0.0.1:8680/health</string>
#   <string>--</string>
#   <string>/Users/les/Projects/mahavishnu/scripts/launch_mcp_with_secrets.py</string>
#
# Exit codes:
#   0   command exited cleanly after /health became healthy
#   1   /health never responded within --timeout, or command died unexpectedly
#   2   argument parsing error

set -u

if [ $# -lt 3 ]; then
  echo "Usage: $0 <health-url> [--timeout SECONDS=30] -- <command> [args...]" >&2
  exit 2
fi

HEALTH_URL="$1"
shift

TIMEOUT=30
if [ "${1:-}" = "--timeout" ]; then
  TIMEOUT="$2"
  shift 2
fi

if [ "${1:-}" != "--" ]; then
  echo "Usage: $0 <health-url> [--timeout SECONDS=30] -- <command> [args...]" >&2
  exit 2
fi
shift

if [ $# -lt 1 ]; then
  echo "Error: no command provided after --" >&2
  exit 2
fi

CMD=("$@")

# Start the actual command in background. We do NOT put it in its own
# process group — we want to signal just this PID, not ourselves.
"${CMD[@]}" &
PID=$!

# Trap signals so we always clean up the child before exiting.
# IMPORTANT: cleanup returns 0 explicitly so it doesn't shadow the
# explicit `exit 1` we issue on timeout (otherwise the trap's last
# command's exit code can override the script's exit code).
cleanup() {
  if kill -0 "$PID" 2>/dev/null; then
    kill -TERM "$PID" 2>/dev/null || true
    for _ in 1 2 3 4 5; do
      kill -0 "$PID" 2>/dev/null || break
      sleep 1
    done
    kill -0 "$PID" 2>/dev/null && kill -KILL "$PID" 2>/dev/null || true
  fi
  wait "$PID" 2>/dev/null
  return 0
}
trap cleanup EXIT INT TERM

# Poll /health until it responds, or until timeout.
ATTEMPTS=$(( TIMEOUT * 2 ))  # 0.5s per attempt
SLEEP_INTERVAL=0.5
HEALTHY=0
for ((i=1; i<=ATTEMPTS; i++)); do
  # Check the command is still alive first.
  if ! kill -0 "$PID" 2>/dev/null; then
    echo "launch_with_healthcheck: command (PID $PID) died before becoming healthy" >&2
    exit 1
  fi
  if curl -fsS -o /dev/null --max-time 1 "$HEALTH_URL" 2>/dev/null; then
    HEALTHY=1
    break
  fi
  sleep "$SLEEP_INTERVAL"
done

if [ "$HEALTHY" -ne 1 ]; then
  echo "launch_with_healthcheck: $HEALTH_URL did not respond within ${TIMEOUT}s, killing PID $PID" >&2
  exit 1
fi

# Health endpoint is responding — wait for the command to exit naturally.
# launchd will see the exit code of the command.
wait "$PID"
EXIT_CODE=$?

# Disable the trap so cleanup doesn't run on the natural exit path.
trap - EXIT INT TERM
cleanup
exit "$EXIT_CODE"
