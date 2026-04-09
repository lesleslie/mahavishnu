#!/bin/zsh

set -euo pipefail

export PATH="/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"

: "${REDIS_STACK_HOST:=127.0.0.1}"
: "${REDIS_STACK_PORT:=6380}"
: "${REDIS_STACK_STATE_DIR:=${HOME}/.local/state/redis-stack-bifrost}"
: "${REDIS_STACK_CONFIG_DIR:=${HOME}/.config/redis-stack-bifrost}"
: "${REDIS_STACK_READY_FILE:=${HOME}/.local/state/mcp/ready/redis-stack-bifrost.ready}"
: "${REDIS_STACK_BINARY:=/usr/local/bin/redis-stack-server}"

mkdir -p "${REDIS_STACK_STATE_DIR}"
mkdir -p "${REDIS_STACK_CONFIG_DIR}"
mkdir -p "${REDIS_STACK_READY_FILE:h}"
mkdir -p "${HOME}/.local/state/mcp/logs"

config_path="${REDIS_STACK_CONFIG_DIR}/redis-stack.conf"
pidfile="${REDIS_STACK_STATE_DIR}/redis-stack.pid"
logfile="${HOME}/.local/state/mcp/logs/redis-stack-bifrost.log"

cat >"${config_path}" <<EOF
bind ${REDIS_STACK_HOST}
port ${REDIS_STACK_PORT}
daemonize no
dir ${REDIS_STACK_STATE_DIR}
pidfile ${pidfile}
dbfilename dump.rdb
appenddirname appendonlydir
EOF

rm -f "${REDIS_STACK_READY_FILE}"

child_pid=""

cleanup() {
    rm -f "${REDIS_STACK_READY_FILE}"
    if [[ -n "${child_pid}" ]]; then
        kill "${child_pid}" >/dev/null 2>&1 || true
    fi
}

trap cleanup EXIT INT TERM

"${REDIS_STACK_BINARY}" "${config_path}" >>"${logfile}" 2>&1 &
child_pid=$!

for _ in {1..30}; do
    if ! kill -0 "${child_pid}" >/dev/null 2>&1; then
        wait "${child_pid}"
        exit $?
    fi
    if redis-cli -h "${REDIS_STACK_HOST}" -p "${REDIS_STACK_PORT}" PING >/dev/null 2>&1; then
        touch "${REDIS_STACK_READY_FILE}"
        break
    fi
    sleep 1
done

wait "${child_pid}"
