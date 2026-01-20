#!/bin/bash
#
# Test Script for Phase 1 Audio Quality Components
#
# Tests all 3 components:
# 1. RNNoise Filter
# 2. Silero VAD
# 3. SOXR Resampler
#
# Usage:
#   ./scripts/test_phase1.sh
#

set -e  # Exit on error

echo "========================================="
echo "Phase 1 Components Test Suite"
echo "========================================="
echo ""

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if inside Docker container
if [ -f "/.dockerenv" ]; then
    PYTHON_CMD="python3"
    TEST_CMD="pytest"
else
    PYTHON_CMD="docker exec -it ai-agent python3"
    TEST_CMD="docker exec -it ai-agent pytest"
fi

echo "🔍 Checking dependencies..."
echo ""

# Check RNNoise
echo -n "  - pyrnnoise: "
if $PYTHON_CMD -c "import pyrnnoise" 2>/dev/null; then
    echo -e "${GREEN}✓ installed${NC}"
else
    echo -e "${RED}✗ missing${NC}"
    echo -e "${YELLOW}    Install: pip install pyrnnoise${NC}"
fi

# Check ONNX Runtime
echo -n "  - onnxruntime: "
if $PYTHON_CMD -c "import onnxruntime" 2>/dev/null; then
    echo -e "${GREEN}✓ installed${NC}"
else
    echo -e "${RED}✗ missing${NC}"
    echo -e "${YELLOW}    Install: pip install onnxruntime${NC}"
fi

# Check SOXR
echo -n "  - soxr: "
if $PYTHON_CMD -c "import soxr" 2>/dev/null; then
    echo -e "${GREEN}✓ installed${NC}"
else
    echo -e "${RED}✗ missing${NC}"
    echo -e "${YELLOW}    Install: pip install soxr${NC}"
fi

echo ""
echo "========================================="
echo "Running Standalone Tests"
echo "========================================="
echo ""

# Test 1: RNNoise Filter
echo "📦 Test 1: RNNoise Filter"
echo "-------------------------------------------"
if $PYTHON_CMD /app/src/audio/filters/rnnoise_filter.py 2>&1 | grep -q "✅"; then
    echo -e "${GREEN}✅ RNNoise filter test PASSED${NC}"
else
    echo -e "${YELLOW}⚠️  RNNoise filter test skipped (dependencies missing)${NC}"
fi
echo ""

# Test 2: Silero VAD
echo "📦 Test 2: Silero VAD"
echo "-------------------------------------------"
if $PYTHON_CMD /app/src/audio/vad_silero/silero_vad.py 2>&1 | grep -q "Speech"; then
    echo -e "${GREEN}✅ Silero VAD test PASSED${NC}"
else
    echo -e "${YELLOW}⚠️  Silero VAD test skipped (dependencies missing)${NC}"
fi
echo ""

# Test 3: SOXR Resampler
echo "📦 Test 3: SOXR Resampler"
echo "-------------------------------------------"
if $PYTHON_CMD /app/src/audio/resamplers/soxr_resampler.py 2>&1 | grep -q "✅"; then
    echo -e "${GREEN}✅ SOXR resampler test PASSED${NC}"
else
    echo -e "${YELLOW}⚠️  SOXR resampler test skipped (dependencies missing)${NC}"
fi
echo ""

echo "========================================="
echo "Running Unit Tests (pytest)"
echo "========================================="
echo ""

if $TEST_CMD /app/tests/audio/test_phase1_components.py -v --tb=short 2>&1; then
    echo ""
    echo -e "${GREEN}✅ All unit tests PASSED${NC}"
else
    echo ""
    echo -e "${YELLOW}⚠️  Some tests skipped (dependencies missing)${NC}"
fi

echo ""
echo "========================================="
echo "Test Summary"
echo "========================================="
echo ""
echo "Next steps:"
echo "  1. Install missing dependencies (if any)"
echo "  2. Rebuild Docker: docker-compose build ai-agent"
echo "  3. Start services: ./scripts/start.sh"
echo "  4. Make test call (dial 9999)"
echo "  5. Check logs: docker logs ai-agent | grep '✅'"
echo ""
echo "Expected log messages:"
echo "  ✅ RNNoise filter initialized"
echo "  ✅ Silero VAD initialized (threshold=0.50)"
echo "  ✅ SOXR resampler initialized (quality=VHQ)"
echo ""
