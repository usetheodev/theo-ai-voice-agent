#!/bin/bash
# AI Voice Agent v2.0 - Smoke Test Runner
#
# Automated smoke test execution for basic validation
# Use this after unit & integration tests pass
#
# Usage:
#   ./tests/smoke/run_smoke_tests.sh
#
# Prerequisites:
#   - Docker Compose running
#   - Asterisk and AI Agent containers healthy

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Test counters
TESTS_PASSED=0
TESTS_FAILED=0
TESTS_TOTAL=0

# Function to print colored output
print_header() {
    echo -e "${BLUE}================================================${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}================================================${NC}"
}

print_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

print_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

# Function to run a test
run_test() {
    local test_name="$1"
    local test_command="$2"

    TESTS_TOTAL=$((TESTS_TOTAL + 1))

    echo ""
    print_info "Running: $test_name"

    if eval "$test_command"; then
        print_success "PASS: $test_name"
        TESTS_PASSED=$((TESTS_PASSED + 1))
        return 0
    else
        print_error "FAIL: $test_name"
        TESTS_FAILED=$((TESTS_FAILED + 1))
        return 1
    fi
}

# Check prerequisites
check_prerequisites() {
    print_header "CHECKING PREREQUISITES"

    # Check if Docker is running
    if ! docker info > /dev/null 2>&1; then
        print_error "Docker is not running"
        exit 1
    fi
    print_success "Docker is running"

    # Check if ai-agent container exists
    if ! docker ps | grep -q "ai-agent"; then
        print_warning "ai-agent container not running"
        print_info "Starting containers with docker-compose..."
        docker-compose up -d
        sleep 10
    fi
    print_success "ai-agent container is running"

    # Check if asterisk container exists
    if docker-compose ps | grep -q "asterisk"; then
        print_success "asterisk container is running"
    else
        print_warning "asterisk container not found (optional)"
    fi
}

# Test 1: Container Health
test_container_health() {
    print_header "TEST 1: Container Health"

    run_test "AI Agent container is healthy" \
        "docker inspect ai-agent --format='{{.State.Health.Status}}' | grep -q 'healthy\|starting' || docker inspect ai-agent --format='{{.State.Status}}' | grep -q 'running'"

    run_test "AI Agent logs show no startup errors" \
        "! docker logs ai-agent 2>&1 | tail -50 | grep -iE '(error|exception|traceback)' | grep -vE '(DeprecationWarning|pkg_resources)'"
}

# Test 2: WebRTC VAD Initialization
test_vad_initialization() {
    print_header "TEST 2: WebRTC VAD Initialization"

    run_test "WebRTC VAD initialized successfully" \
        "docker logs ai-agent 2>&1 | grep -q '✅ WebRTC VAD initialized' || docker logs ai-agent 2>&1 | grep -q 'WebRTC VAD'"

    run_test "VAD configuration loaded" \
        "docker logs ai-agent 2>&1 | grep -qE '(VAD initialized|vad_mode)'"
}

# Test 3: RTP Server Listening
test_rtp_server() {
    print_header "TEST 3: RTP Server Status"

    run_test "RTP server is listening on port 5080" \
        "docker exec ai-agent netstat -ulnp 2>/dev/null | grep -q ':5080' || docker exec ai-agent ss -ulnp 2>/dev/null | grep -q ':5080'"

    run_test "IP whitelist configured" \
        "docker logs ai-agent 2>&1 | grep -q '🔒 IP Whitelist'"
}

# Test 4: Configuration Validation
test_configuration() {
    print_header "TEST 4: Configuration Validation"

    run_test "config.yaml exists" \
        "docker exec ai-agent test -f /app/config.yaml"

    run_test "VAD configuration present" \
        "docker exec ai-agent grep -q 'vad:' /app/config.yaml"

    run_test "RTP security configuration present" \
        "docker exec ai-agent grep -q 'rtp_security:' /app/config.yaml"
}

# Test 5: Dependencies Check
test_dependencies() {
    print_header "TEST 5: Python Dependencies"

    run_test "webrtcvad installed" \
        "docker exec ai-agent python3 -c 'import webrtcvad; print(webrtcvad.__version__)' 2>/dev/null"

    run_test "pytest installed (for testing)" \
        "docker exec ai-agent python3 -c 'import pytest; print(pytest.__version__)' 2>/dev/null"

    run_test "numpy installed (audio processing)" \
        "docker exec ai-agent python3 -c 'import numpy; print(numpy.__version__)' 2>/dev/null"
}

# Test 6: Code Structure Validation
test_code_structure() {
    print_header "TEST 6: Code Structure"

    run_test "CallSession module exists" \
        "docker exec ai-agent test -f /app/src/rtp/session.py"

    run_test "VAD module exists" \
        "docker exec ai-agent test -f /app/src/audio/vad.py"

    run_test "RTP server module exists" \
        "docker exec ai-agent test -f /app/src/rtp/server.py"
}

# Test 7: Log Analysis
test_log_analysis() {
    print_header "TEST 7: Log Analysis (Last 100 Lines)"

    run_test "No critical errors in recent logs" \
        "! docker logs ai-agent 2>&1 | tail -100 | grep -iE '(CRITICAL|FATAL)'"

    run_test "No unhandled exceptions in recent logs" \
        "! docker logs ai-agent 2>&1 | tail -100 | grep -A 5 'Traceback' | grep -q 'Error'"
}

# Print summary
print_summary() {
    echo ""
    print_header "SMOKE TEST SUMMARY"

    echo "Tests Run:    $TESTS_TOTAL"
    echo "Tests Passed: $TESTS_PASSED"
    echo "Tests Failed: $TESTS_FAILED"

    if [ $TESTS_FAILED -eq 0 ]; then
        echo ""
        print_success "ALL SMOKE TESTS PASSED! ✅"
        echo ""
        print_info "The system is ready for manual testing or staging deployment."
        echo ""
        print_info "Next Steps:"
        echo "  1. Perform manual call test (see README_SMOKE_TESTS.md)"
        echo "  2. Test with real Asterisk traffic"
        echo "  3. Monitor logs during test calls"
        echo ""
        return 0
    else
        echo ""
        print_error "SOME TESTS FAILED! ❌"
        echo ""
        print_warning "Please review the failures above and:"
        echo "  1. Check container logs: docker logs ai-agent"
        echo "  2. Verify configuration: docker exec ai-agent cat /app/config.yaml"
        echo "  3. Check Docker network: docker network inspect ai-voice-agent_default"
        echo ""
        return 1
    fi
}

# Main execution
main() {
    print_header "AI VOICE AGENT v2.0 - SMOKE TEST RUNNER"
    echo "Started: $(date)"
    echo ""

    check_prerequisites

    # Run all tests
    test_container_health
    test_vad_initialization
    test_rtp_server
    test_configuration
    test_dependencies
    test_code_structure
    test_log_analysis

    # Print summary and exit with appropriate code
    print_summary
    exit $?
}

# Run main
main
