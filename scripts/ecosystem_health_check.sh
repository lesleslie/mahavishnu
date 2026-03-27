#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="/Users/les/Projects/mahavishnu"
BODAI_DIR="/Users/les/Projects/bodai"

failures=0

run_check() {
  local name="$1"
  shift
  echo
  echo "==> ${name}"
  if "$@"; then
    echo "PASS: ${name}"
  else
    echo "FAIL: ${name}"
    failures=$((failures + 1))
  fi
}

run_check_output() {
  local name="$1"
  local fail_pattern="$2"
  shift 2

  echo
  echo "==> ${name}"

  local output
  if output="$("$@" 2>&1)"; then
    echo "${output}"
    if [[ -n "${fail_pattern}" ]] && echo "${output}" | grep -E -q "${fail_pattern}"; then
      echo "FAIL: ${name}"
      failures=$((failures + 1))
    else
      echo "PASS: ${name}"
    fi
  else
    echo "${output}"
    echo "FAIL: ${name}"
    failures=$((failures + 1))
  fi
}

run_check "Mahavishnu ecosystem validate" \
  /usr/local/bin/zsh -lc "cd '${ROOT_DIR}' && mahavishnu ecosystem validate"

run_check_output "Mahavishnu MCP health" "Not running|Could not connect" \
  /usr/local/bin/zsh -lc "cd '${ROOT_DIR}' && mahavishnu mcp health"

run_check "Mahavishnu worker types + dependency check" \
  /usr/local/bin/zsh -lc "cd '${ROOT_DIR}' && mahavishnu workers list-types"

if [[ -d "${BODAI_DIR}" ]]; then
  run_check "Bodai config validate" \
    /usr/local/bin/zsh -lc "cd '${BODAI_DIR}' && python -m bodai.cli config validate >/tmp/bodai_config_validate.out 2>&1; cat /tmp/bodai_config_validate.out; ! grep -q -- '- ecosystem.yaml:' /tmp/bodai_config_validate.out"

  run_check "Bodai health" \
    /usr/local/bin/zsh -lc "cd '${BODAI_DIR}' && python -m bodai.cli health"
else
  echo
  echo "WARN: Bodai directory not found at ${BODAI_DIR} (skipping Bodai checks)"
fi

echo
if [[ "${failures}" -eq 0 ]]; then
  echo "Ecosystem health check: PASS"
  exit 0
fi

echo "Ecosystem health check: FAIL (${failures} check(s) failed)"
exit 1
