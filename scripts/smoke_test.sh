#!/bin/bash
# smoke_test.sh — quick post-deploy sanity check
# Usage: ./scripts/smoke_test.sh http://1.2.3.4:3081
set -e

BASE_URL=${1:-"http://localhost:3081"}
PASS=0
FAIL=0

check() {
  local label=$1
  local url=$2
  local expected=$3   # space-separated list of acceptable codes

  STATUS=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "$url" || echo "000")
  for code in $expected; do
    if [ "$STATUS" = "$code" ]; then
      echo "✅ $label ($STATUS)"
      PASS=$((PASS + 1))
      return
    fi
  done
  echo "❌ $label — got $STATUS, expected one of: $expected"
  FAIL=$((FAIL + 1))
}

echo ""
echo "🔍 Smoke testing $BASE_URL"
echo "────────────────────────────────────"

check "/health"        "$BASE_URL/health"        "200"
check "/ready"         "$BASE_URL/ready"          "200 503"
check "/api/projects"  "$BASE_URL/api/projects"   "200"
check "/api/system"    "$BASE_URL/api/system"     "200"
check "/api/stats"     "$BASE_URL/api/stats"      "200"
check "/metrics"       "$BASE_URL/metrics"        "200"

echo "────────────────────────────────────"
echo "Results: $PASS passed, $FAIL failed"

if [ "$FAIL" -gt 0 ]; then
  echo "❌ Smoke tests FAILED"
  exit 1
fi

echo "✅ All smoke tests passed"
