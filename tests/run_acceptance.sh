#!/usr/bin/env bash
# tests/run_acceptance.sh
# Run all 5 acceptance test sites against the running Fatal Flaw API.
# Usage:
#   ./tests/run_acceptance.sh [API_URL]
#   API_URL defaults to http://localhost:8000

set -euo pipefail

API_URL="${1:-http://localhost:8000}"
PASS=0
FAIL=0
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}   Fatal Flaw — Acceptance Test Suite${NC}"
echo -e "${BLUE}   API: ${API_URL}${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo ""

# ── Health check ─────────────────────────────────────────────────────────────
echo -e "${YELLOW}[HEALTH CHECK]${NC} Checking API availability…"
HEALTH=$(curl -sf "${API_URL}/health" 2>/dev/null || echo '{"status":"error"}')
STATUS=$(echo "$HEALTH" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status','error'))")
if [ "$STATUS" = "ok" ]; then
    echo -e "  ${GREEN}✓ API is healthy${NC}"
else
    echo -e "  ${RED}✗ API health check failed: $HEALTH${NC}"
    echo -e "  Ensure the stack is running: docker-compose up"
    exit 1
fi
echo ""

# ── Helper function ───────────────────────────────────────────────────────────
run_test() {
    local test_name="$1"
    local payload="$2"
    local check_fatal="$3"       # "true" | "false" | "any"
    local min_score="$4"          # minimum expected score (or "any")
    local max_score="$5"          # maximum expected score (or "any")

    echo -e "${YELLOW}[TEST]${NC} ${test_name}"

    # Time the request
    START=$(python3 -c "import time; print(int(time.time()*1000))")
    RESPONSE=$(curl -sf -X POST \
        -H "Content-Type: application/json" \
        -d "$payload" \
        "${API_URL}/api/v1/assess-site" 2>/dev/null)
    END=$(python3 -c "import time; print(int(time.time()*1000))")
    ELAPSED=$((END - START))

    if [ -z "$RESPONSE" ]; then
        echo -e "  ${RED}✗ FAIL — No response from API${NC}"
        FAIL=$((FAIL+1))
        return
    fi

    # Parse response fields
    SCORE=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('overall_risk_score',0))")
    FATAL=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(str(d.get('fatal_flag',False)).lower())")
    LAYERS=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('all_layer_results',[])))")
    PROC_MS=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('processing_time_ms',999999))")
    FATAL_LAYERS=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(','.join(d.get('fatal_layers',[])))")

    local test_passed=true
    local failures=()

    # Check fatal flag
    if [ "$check_fatal" != "any" ] && [ "$FATAL" != "$check_fatal" ]; then
        test_passed=false
        failures+=("Expected fatal_flag=$check_fatal, got $FATAL (fatal_layers: $FATAL_LAYERS)")
    fi

    # Check score range
    if [ "$min_score" != "any" ]; then
        SCORE_OK=$(python3 -c "print('yes' if ${SCORE} >= ${min_score} else 'no')")
        if [ "$SCORE_OK" = "no" ]; then
            test_passed=false
            failures+=("Score ${SCORE} < minimum ${min_score}")
        fi
    fi
    if [ "$max_score" != "any" ]; then
        SCORE_OK=$(python3 -c "print('yes' if ${SCORE} <= ${max_score} else 'no')")
        if [ "$SCORE_OK" = "no" ]; then
            test_passed=false
            failures+=("Score ${SCORE} > maximum ${max_score}")
        fi
    fi

    # Check layer count
    if [ "$LAYERS" -ne 15 ]; then
        test_passed=false
        failures+=("Expected 15 layer results, got $LAYERS")
    fi

    # Check SLA
    if [ "$PROC_MS" -ge 500 ]; then
        test_passed=false
        failures+=("Processing time ${PROC_MS}ms exceeds 500ms SLA")
    fi

    if [ "$test_passed" = true ]; then
        echo -e "  ${GREEN}✓ PASS${NC} | score=${SCORE} | fatal=${FATAL} | layers=${LAYERS} | ${PROC_MS}ms (wall: ${ELAPSED}ms)"
        PASS=$((PASS+1))
    else
        echo -e "  ${RED}✗ FAIL${NC} | score=${SCORE} | fatal=${FATAL} | layers=${LAYERS} | ${PROC_MS}ms"
        for failure in "${failures[@]}"; do
            echo -e "    ${RED}→ ${failure}${NC}"
        done
        FAIL=$((FAIL+1))
    fi
    echo ""
}

# ── Test Site A: National Park → fatal ───────────────────────────────────────
run_test \
    "Site A — National Park (Yellowstone area) → fatal_flag=true" \
    '{"type":"Feature","geometry":{"type":"Polygon","coordinates":[[[-110.70,44.45],[-110.50,44.45],[-110.50,44.60],[-110.70,44.60],[-110.70,44.45]]]},"properties":{"site_name":"Site A National Park","site_type":"solar"}}' \
    "true" \
    "75" \
    "any"

# ── Test Site B: Critical Habitat → fatal ────────────────────────────────────
run_test \
    "Site B — Critical Habitat (Sonoran AZ) → fatal_flag=true" \
    '{"type":"Feature","geometry":{"type":"Polygon","coordinates":[[[-113.20,32.40],[-113.00,32.40],[-113.00,32.55],[-113.20,32.55],[-113.20,32.40]]]},"properties":{"site_name":"Site B Critical Habitat","site_type":"solar"}}' \
    "true" \
    "75" \
    "any"

# ── Test Site C: Near transmission → high score, not fatal ───────────────────
run_test \
    "Site C — Near Transmission Line (OK) → fatal_flag=false, non-trivial score" \
    '{"type":"Feature","geometry":{"type":"Polygon","coordinates":[[[-95.40,35.45],[-95.38,35.45],[-95.38,35.47],[-95.40,35.47],[-95.40,35.45]]]},"properties":{"site_name":"Site C Transmission","site_type":"solar"}}' \
    "false" \
    "any" \
    "any"

# ── Test Site D: Agricultural preserve → moderate risk ───────────────────────
run_test \
    "Site D — Agricultural Preserve (Iowa) → fatal_flag=false, score 0–70" \
    '{"type":"Feature","geometry":{"type":"Polygon","coordinates":[[[-93.00,42.00],[-92.95,42.00],[-92.95,42.05],[-93.00,42.05],[-93.00,42.00]]]},"properties":{"site_name":"Site D Ag Preserve","site_type":"solar"}}' \
    "false" \
    "any" \
    "70"

# ── Test Site E: Open field → low risk ───────────────────────────────────────
run_test \
    "Site E — Open Field Nevada Desert → fatal_flag=false, score < 50" \
    '{"type":"Feature","geometry":{"type":"Polygon","coordinates":[[[-116.50,38.80],[-116.45,38.80],[-116.45,38.85],[-116.50,38.85],[-116.50,38.80]]]},"properties":{"site_name":"Site E Open Field","site_type":"solar"}}' \
    "false" \
    "any" \
    "50"

# ── Summary ───────────────────────────────────────────────────────────────────
TOTAL=$((PASS+FAIL))
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo -e "  Results: ${GREEN}${PASS} passed${NC} | ${RED}${FAIL} failed${NC} | ${TOTAL} total"
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"

if [ "$FAIL" -gt 0 ]; then
    echo -e "${RED}Acceptance tests FAILED. Check that all 15 constraint layers are loaded.${NC}"
    exit 1
else
    echo -e "${GREEN}All acceptance tests PASSED. Platform is ready for production use.${NC}"
    exit 0
fi
