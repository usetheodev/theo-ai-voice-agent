#!/bin/bash
# ============================================
# Phase 2.1 Test Script
# ============================================
# Tests Turn Detection + Smart Barge-in
# Run: ./scripts/test_phase2_1.sh

set -e  # Exit on error

echo "🧪 Phase 2.1 Test Suite - Conversational Intelligence"
echo "======================================================"
echo ""

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if pytest is available
if ! command -v pytest &> /dev/null; then
    echo -e "${RED}❌ pytest not found. Install with: pip install pytest pytest-asyncio${NC}"
    exit 1
fi

echo -e "${YELLOW}Step 1: Checking Phase 2.1 component imports...${NC}"
echo ""

# Test Turn Detection imports
python3 -c "
try:
    from audio.turn import BaseTurnAnalyzer, SimpleTurnAnalyzer, EndOfTurnState
    print('✅ Turn Detection imports OK')
except ImportError as e:
    print(f'❌ Turn Detection import failed: {e}')
    exit(1)
" || exit 1

# Test Smart Barge-in imports
python3 -c "
try:
    from audio.interruptions import BaseInterruptionStrategy, MinDurationInterruptionStrategy
    print('✅ Smart Barge-in imports OK')
except ImportError as e:
    print(f'❌ Smart Barge-in import failed: {e}')
    exit(1)
" || exit 1

echo ""
echo -e "${YELLOW}Step 2: Running SimpleTurnAnalyzer unit tests...${NC}"
echo ""

pytest tests/audio/test_phase2_1_components.py::TestSimpleTurnAnalyzer -v || {
    echo -e "${RED}❌ SimpleTurnAnalyzer tests failed${NC}"
    exit 1
}

echo ""
echo -e "${YELLOW}Step 3: Running MinDurationInterruptionStrategy unit tests...${NC}"
echo ""

pytest tests/audio/test_phase2_1_components.py::TestMinDurationInterruptionStrategy -v || {
    echo -e "${RED}❌ MinDurationInterruptionStrategy tests failed${NC}"
    exit 1
}

echo ""
echo -e "${YELLOW}Step 4: Running integration tests...${NC}"
echo ""

pytest tests/audio/test_phase2_1_components.py::TestPhase21Integration -v || {
    echo -e "${RED}❌ Integration tests failed${NC}"
    exit 1
}

echo ""
echo -e "${YELLOW}Step 5: Running all Phase 2.1 tests...${NC}"
echo ""

pytest tests/audio/test_phase2_1_components.py -v --tb=short || {
    echo -e "${RED}❌ Some tests failed${NC}"
    exit 1
}

echo ""
echo "======================================================"
echo -e "${GREEN}✅ All Phase 2.1 tests passed!${NC}"
echo ""
echo "Summary:"
echo "  ✅ Turn Detection: Working"
echo "  ✅ Smart Barge-in: Working"
echo "  ✅ Integration: Working"
echo ""
echo "Next steps:"
echo "  1. Review test results above"
echo "  2. Check configuration in .env"
echo "  3. Deploy: docker-compose build ai-agent && docker-compose up -d"
echo "  4. Monitor: docker-compose logs -f ai-agent | grep 'Phase 2.1'"
echo ""
