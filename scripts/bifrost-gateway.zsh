#!/bin/zsh

set -euo pipefail

export PATH="/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"

SCRIPT_DIR=${0:A:h}
PROJECT_ROOT=${SCRIPT_DIR:h}

: "${BIFROST_HOST:=127.0.0.1}"
: "${BIFROST_PORT:=8471}"
: "${BIFROST_LOG_LEVEL:=info}"
: "${BIFROST_LOG_STYLE:=json}"
: "${BIFROST_NODE_BIN:=node}"
: "${BIFROST_APP_DIR:=${HOME}/.config/bifrost}"
: "${BIFROST_CONFIG_PATH:=${BIFROST_APP_DIR}/config.json}"
: "${BIFROST_READY_FILE:=${HOME}/.local/state/mcp/ready/bifrost.ready}"
: "${BIFROST_SECRETS_FILE:=${HOME}/.config/opencode/shell-secrets.zsh}"
: "${BIFROST_TEMPLATE_CONFIG:=${PROJECT_ROOT}/config/bifrost/config.template.json}"

mkdir -p "${BIFROST_APP_DIR}"
mkdir -p "${BIFROST_READY_FILE:h}"
mkdir -p "${HOME}/.local/state/mcp/logs"

# Keep Bifrost's relative SQLite artifacts inside the app dir, not the repo root.
cd "${BIFROST_APP_DIR}"

if [[ -f "${BIFROST_SECRETS_FILE}" ]]; then
    source "${BIFROST_SECRETS_FILE}"
fi

# Normalize the z.ai key so existing tools can use either name.
if [[ -n "${Z_AI_API_KEY:-}" && -z "${ZAI_API_KEY:-}" ]]; then
    export ZAI_API_KEY="${Z_AI_API_KEY}"
fi
if [[ -n "${ZAI_API_KEY:-}" && -z "${Z_AI_API_KEY:-}" ]]; then
    export Z_AI_API_KEY="${ZAI_API_KEY}"
fi

if [[ -z "${ZAI_API_KEY:-}" ]]; then
    print -u2 "bifrost-gateway: ZAI_API_KEY or Z_AI_API_KEY must be set before launch"
    exit 64
fi

if [[ ! -f "${BIFROST_CONFIG_PATH}" && -f "${BIFROST_TEMPLATE_CONFIG}" ]]; then
    cp "${BIFROST_TEMPLATE_CONFIG}" "${BIFROST_CONFIG_PATH}"
fi

rm -f "${BIFROST_READY_FILE}"

child_pid=""

cleanup() {
    rm -f "${BIFROST_READY_FILE}"
    if [[ -n "${child_pid}" ]]; then
        kill "${child_pid}" >/dev/null 2>&1 || true
    fi
}

trap cleanup EXIT INT TERM

find_cached_bifrost_bin() {
    local npm_npx_root="${HOME}/.npm/_npx"
    if [[ ! -d "${npm_npx_root}" ]]; then
        return 1
    fi
    find "${npm_npx_root}" -path '*/node_modules/@maximhq/bifrost/bin.js' -print 2>/dev/null \
        | sort \
        | tail -n 1
}

bifrost_cmd=()
cached_bifrost_bin=$(find_cached_bifrost_bin || true)
if [[ -n "${cached_bifrost_bin}" ]]; then
    bifrost_cmd=("${BIFROST_NODE_BIN}" "${cached_bifrost_bin}")
else
    bifrost_cmd=(npx -y "@maximhq/bifrost")
fi

"${bifrost_cmd[@]}" \
    -host "${BIFROST_HOST}" \
    -port "${BIFROST_PORT}" \
    -log-level "${BIFROST_LOG_LEVEL}" \
    -log-style "${BIFROST_LOG_STYLE}" \
    -app-dir "${BIFROST_APP_DIR}" &
child_pid=$!

for _ in {1..60}; do
    if ! kill -0 "${child_pid}" >/dev/null 2>&1; then
        wait "${child_pid}"
        exit $?
    fi
    if lsof -nP -iTCP:"${BIFROST_PORT}" -sTCP:LISTEN >/dev/null 2>&1; then
        touch "${BIFROST_READY_FILE}"
        break
    fi
    sleep 1
done

wait "${child_pid}"
