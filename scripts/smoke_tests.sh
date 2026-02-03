#!/bin/bash
# Smoke tests for Mahavishnu MCP production deployment
# Usage: ./smoke_tests.sh [MAHAVISHNU_URL]
# Example: ./smoke_tests.sh https://mahavishnu-mcp-xxxxx.a.run.app

set -e

# Configuration
MAHAVISHNU_URL="${1:-http://localhost:8680}"
TIMEOUT=30
VERBOSE=0

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Parse arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    -v|--verbose)
      VERBOSE=1
      shift
      ;;
    *)
      MAHAVISHNU_URL="$1"
      shift
      ;;
  esac
done

echo "🔍 Running smoke tests against: $MAHAVISHNU_URL"
echo ""

# Test counter
TESTS_PASSED=0
TESTS_FAILED=0

# Test helper function
run_test() {
  local test_name="$1"
  local test_command="$2"

  echo -n "Testing: $test_name... "

  if [ $VERBOSE -eq 1 ]; then
    echo ""
    echo "Command: $test_command"
  fi

  # Run test with timeout
  if eval "$test_command" > /tmp/smoke_test_output.txt 2>&1; then
    echo -e "${GREEN}✅ PASS${NC}"
    TESTS_PASSED=$((TESTS_PASSED + 1))

    if [ $VERBOSE -eq 1 ]; then
      cat /tmp/smoke_test_output.txt
      echo ""
    fi
  else
    echo -e "${RED}❌ FAIL${NC}"
    TESTS_FAILED=$((TESTS_FAILED + 1))
    echo "Output:"
    cat /tmp/smoke_test_output.txt
    echo ""
  fi
}

# Test 1: Health endpoint
run_test "Health endpoint" \
  "curl -f -s --max-time $TIMEOUT '$MAHAVISHNU_URL/health' | grep -q 'healthy'"

# Test 2: MCP server initialization
run_test "MCP initialization" \
  "curl -f -s --max-time $TIMEOUT '$MAHAVISHNU_URL/mcp' -H 'Content-Type: application/json' -d '{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"initialize\",\"params\":{}}' | grep -q 'result'"

# Test 3: List available tools
run_test "List MCP tools" \
  "curl -f -s --max-time $TIMEOUT '$MAHAVISHNU_URL/mcp' -H 'Content-Type: application/json' -d '{\"jsonrpc\":\"2.0\",\"id\":2,\"method\":\"tools/list\"}' | grep -q 'list_repos'"

# Test 4: List repositories tool
run_test "List repositories tool" \
  "curl -f -s --max-time $TIMEOUT '$MAHAVISHNU_URL/mcp' -H 'Content-Type: application/json' -d '{\"jsonrpc\":\"2.0\",\"id\":3,\"method\":\"tools/call\",\"params\":{\"name\":\"list_repos\",\"arguments\":{}}}' | grep -q 'result'"

# Test 5: Get repository paths
run_test "Get repository paths" \
  "curl -f -s --max-time $TIMEOUT '$MAHAVISHNU_URL/mcp' -H 'Content-Type: application/json' -d '{\"jsonrpc\":\"2.0\",\"id\":4,\"method\":\"tools/call\",\"params\":{\"name\":\"get_all_repo_paths\",\"arguments\":{}}}' | grep -q 'result'"

# Test 6: Rate limiting (make 5 rapid requests)
echo -n "Testing: Rate limiting... "
RATE_LIMIT_PASSED=1
for i in {1..5}; do
  if ! curl -f -s --max-time $TIMEOUT "$MAHAVISHNU_URL/mcp" -H "Content-Type: application/json" -d "{\"jsonrpc\":\"2.0\",\"id\":$i,\"method\":\"tools/list\"}" > /dev/null 2>&1; then
    RATE_LIMIT_PASSED=0
    break
  fi
done

if [ $RATE_LIMIT_PASSED -eq 1 ]; then
  echo -e "${GREEN}✅ PASS${NC}"
  TESTS_PASSED=$((TESTS_PASSED + 1))
else
  echo -e "${RED}❌ FAIL${NC}"
  TESTS_FAILED=$((TESTS_FAILED + 1))
fi

# Test 7: Check response time (should be < 2s)
echo -n "Testing: Response time... "
START_TIME=$(date +%s%N)
curl -f -s --max-time $TIMEOUT "$MAHAVISHNU_URL/health" > /dev/null 2>&1
END_TIME=$(date +%s%N)
RESPONSE_TIME=$(( (END_TIME - START_TIME) / 1000000 )) # Convert to milliseconds

if [ $RESPONSE_TIME -lt 2000 ]; then
  echo -e "${GREEN}✅ PASS${NC} (${RESPONSE_TIME}ms)"
  TESTS_PASSED=$((TESTS_PASSED + 1))
else
  echo -e "${YELLOW}⚠️ SLOW${NC} (${RESPONSE_TIME}ms, expected < 2000ms)"
  TESTS_FAILED=$((TESTS_FAILED + 1))
fi

# Test 8: Check JSON-RPC error handling
run_test "Invalid method error handling" \
  "curl -f -s --max-time $TIMEOUT '$MAHAVISHNU_URL/mcp' -H 'Content-Type: application/json' -d '{\"jsonrpc\":\"2.0\",\"id\":5,\"method\":\"invalid_method\",\"params\":{}}' | grep -q 'error'"

# Summary
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Smoke Test Results"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Total Tests: $((TESTS_PASSED + TESTS_FAILED))"
echo -e "${GREEN}Passed: $TESTS_PASSED${NC}"
echo -e "${RED}Failed: $TESTS_FAILED${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Exit with appropriate code
if [ $TESTS_FAILED -gt 0 ]; then
  echo -e "${RED}❌ Smoke tests FAILED${NC}"
  exit 1
else
  echo -e "${GREEN}🎉 All smoke tests PASSED${NC}"
  exit 0
fi
