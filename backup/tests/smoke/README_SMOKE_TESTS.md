# Smoke Tests - AI Voice Agent v2.0

**Purpose**: Validate the system works end-to-end with real Asterisk traffic.

**Target**: Real-world validation after unit & integration tests pass.

---

## 📋 **Test Checklist**

### ✅ **Pre-Test Requirements**

- [ ] Docker Compose running (`docker-compose up -d`)
- [ ] AI Agent container healthy (`docker logs ai-agent`)
- [ ] Asterisk container healthy (`docker logs asterisk`)
- [ ] WebRTC VAD initialized (check logs: "✅ WebRTC VAD initialized")
- [ ] No errors in startup logs

---

## 🧪 **Smoke Test Scenarios**

### **TEST 1: Single Call - Basic Flow**

**Objective**: Verify basic call flow works end-to-end.

**Steps**:
1. Initiate SIP call from Asterisk to AI Agent
2. Speak into microphone for 5 seconds
3. Wait for AI Agent response
4. Hang up

**Expected Results**:
- ✅ Call connects successfully
- ✅ RTP stream established (check logs: "New call from...")
- ✅ VAD detects speech (logs: "🎙️ Speech started")
- ✅ ASR transcribes correctly (logs: transcription output)
- ✅ LLM generates response (logs: LLM response)
- ✅ TTS plays back (RTP packets sent)
- ✅ Call ends gracefully
- ✅ Session cleaned up (check: `docker exec ai-agent python3 -c "...check sessions..."`)

**Log Validation**:
```bash
# Check call flow
docker logs ai-agent 2>&1 | grep -E "(New call|Speech started|Speech ended|Transcription)"

# Expected:
# New call from 172.20.0.10:5060 (SSRC: 0x12345678)
# 🎙️ Speech started (segment #1)
# 🤫 Speech ended (duration: 3.50s, 175 frames)
# Transcription: "hello can you hear me"
```

---

### **TEST 2: Two Simultaneous Calls**

**Objective**: Validate multi-call isolation (no interference).

**Steps**:
1. Initiate Call A from Endpoint 1
2. While Call A is active, initiate Call B from Endpoint 2
3. Speak on Call A
4. Speak on Call B
5. Verify both calls are independent

**Expected Results**:
- ✅ Both calls connect successfully
- ✅ Two distinct sessions in `server.sessions` dict
- ✅ Different call_ids (format: IP:PORT:SSRC)
- ✅ Speech on Call A doesn't affect Call B
- ✅ Separate audio buffers confirmed in logs
- ✅ Separate packet counters

**Log Validation**:
```bash
# Check multi-call
docker logs ai-agent 2>&1 | grep "New call"

# Expected (2 distinct calls):
# New call from 172.20.0.10:5060 (SSRC: 0x11111111) -> call_id: 172.20.0.10:5060:286331153
# New call from 172.20.0.10:5070 (SSRC: 0x22222222) -> call_id: 172.20.0.10:5070:572662306
```

**Validation Script**:
```python
# Check sessions exist
import sys
sys.path.insert(0, '/app/src')
from rtp.server import RTPServer

# This would need to be run inside the container
# docker exec -it ai-agent python3 <<EOF
# ... query server.sessions ...
# EOF
```

---

### **TEST 3: Echo Filtering Validation**

**Objective**: Verify agent's voice doesn't get re-processed (echo loop prevention).

**Setup**:
- Configure Asterisk to echo back RTP packets (simulate echo scenario)
- OR use network tap to inject echo packets

**Steps**:
1. Start call
2. Wait for agent to speak (TTS output)
3. Monitor logs for echo packet detection

**Expected Results**:
- ✅ Outbound SSRC generated (logs: "Generated outbound SSRC: 0xXXXXXXXX")
- ✅ Echo packets detected (logs: "Echo packet filtered")
- ✅ `echo_packets_filtered` counter increments
- ✅ No re-transcription of agent's own voice

**Log Validation**:
```bash
# Check echo filtering
docker logs ai-agent 2>&1 | grep -E "(outbound_ssrc|Echo packet)"

# Expected:
# Session 172.20.0.10:5060:305419896: inbound=0x12345678, outbound=0xedcba987
# Echo packet filtered (SSRC: 0xedcba987 == outbound)
```

---

### **TEST 4: Session Cleanup (Memory Leak)**

**Objective**: Verify idle sessions get cleaned up after 5 minutes.

**Steps**:
1. Start a call
2. Leave call idle (no packets) for 6 minutes
3. Check if session was removed

**Expected Results**:
- ✅ Session created (logs: "New call from...")
- ✅ After 5 minutes: cleanup triggered (logs: "Cleaning up idle session...")
- ✅ Session removed from `server.sessions`
- ✅ Memory freed (check Docker stats: `docker stats ai-agent`)

**Log Validation**:
```bash
# Check cleanup
docker logs ai-agent 2>&1 | grep "Cleaning up idle session"

# Expected (after 5+ min):
# Cleaning up idle session: 172.20.0.10:5060:305419896 (idle: 301.5s)
```

---

### **TEST 5: VAD Dual-Mode Validation**

**Objective**: Verify WebRTC VAD + Energy VAD are both working.

**Steps**:
1. Start call with WebRTC VAD enabled (check config: `webrtc_aggressiveness: 1`)
2. Speak into microphone
3. Check logs for dual-mode statistics

**Expected Results**:
- ✅ WebRTC VAD initialized (logs: "✅ WebRTC VAD initialized")
- ✅ Dual-mode active (logs: "mode: dual-mode")
- ✅ Agreement rate >80% (logs: "agreement_rate: 0.85")
- ✅ Both methods detect speech (logs: "webrtc_detections: X, energy_detections: Y")

**Log Validation**:
```bash
# Check VAD stats
docker logs ai-agent 2>&1 | grep -A 10 "VAD Stats"

# Expected:
# VAD Stats: {
#   'mode': 'dual-mode',
#   'webrtc_detections': 150,
#   'energy_detections': 160,
#   'agreement_count': 140,
#   'agreement_rate': 0.875
# }
```

---

### **TEST 6: Security - IP Whitelist**

**Objective**: Verify RTP packets from unauthorized IPs are rejected.

**Setup**:
- Configure `allowed_asterisk_ips` in config.yaml
- Attempt to send RTP from non-whitelisted IP

**Steps**:
1. Configure whitelist: `['172.20.0.10']`
2. Attempt RTP from `172.20.0.99` (not in whitelist)
3. Check if rejected

**Expected Results**:
- ✅ Whitelisted IP accepted (logs: "New call from 172.20.0.10")
- ✅ Non-whitelisted IP rejected (logs: "Rejected RTP from unauthorized IP: 172.20.0.99")
- ✅ No session created for unauthorized IP

**Log Validation**:
```bash
# Check security
docker logs ai-agent 2>&1 | grep "Rejected RTP"

# Expected:
# Rejected RTP from unauthorized IP: 172.20.0.99
```

---

## 🛠️ **Smoke Test Utilities**

### **Generate Mock RTP Traffic**

Use SIPp to generate controlled RTP traffic:

```bash
# Install SIPp (if not installed)
sudo apt-get install sipp

# Run SIPp scenario
sipp -sn uac -d 10000 -s 1000 172.20.0.10:5060
```

### **Monitor RTP Packets**

Use tcpdump to capture RTP traffic:

```bash
# Capture RTP on port 5080
sudo tcpdump -i any port 5080 -w smoke_test_rtp.pcap

# Analyze with Wireshark
wireshark smoke_test_rtp.pcap
```

### **Check Session State**

Query active sessions inside container:

```bash
# List active sessions
docker exec -it ai-agent python3 -c "
import sys
sys.path.insert(0, '/app/src')
from rtp.server import RTPServer

# This requires the server instance to be accessible
# Alternative: Parse logs for session info
"
```

---

## 📊 **Success Criteria**

| Test | Status | Critical? |
|------|--------|-----------|
| Single Call Flow | ⬜ | ✅ YES |
| Two Simultaneous Calls | ⬜ | ✅ YES |
| Echo Filtering | ⬜ | ✅ YES |
| Session Cleanup | ⬜ | ⚠️ IMPORTANT |
| VAD Dual-Mode | ⬜ | ⚠️ IMPORTANT |
| IP Whitelist | ⬜ | ℹ️ NICE-TO-HAVE |

**Definition of PASS**:
- All CRITICAL tests pass
- ≥80% IMPORTANT tests pass
- No crashes or memory leaks
- Logs show no unexpected errors

---

## 🚨 **Troubleshooting**

### **Problem**: No RTP packets received

**Possible Causes**:
- Firewall blocking UDP 5080
- Asterisk sending to wrong IP/port
- Docker network misconfiguration

**Debug Steps**:
```bash
# Check if port is listening
docker exec ai-agent netstat -ulnp | grep 5080

# Check Docker network
docker network inspect ai-voice-agent_default

# Check Asterisk config
docker exec asterisk cat /etc/asterisk/pjsip.conf
```

---

### **Problem**: WebRTC VAD not initializing

**Possible Causes**:
- `webrtcvad` not installed
- Unsupported sample rate (not 8k/16k/32k)

**Debug Steps**:
```bash
# Check if webrtcvad installed
docker exec ai-agent python3 -c "import webrtcvad; print(webrtcvad.__version__)"

# Check config sample rate
docker exec ai-agent cat /app/config.yaml | grep sample_rate

# Expected: sample_rate: 8000 (or 16000/32000)
```

---

### **Problem**: Sessions not cleaning up

**Possible Causes**:
- Cleanup task not running
- Activity timestamps updating incorrectly

**Debug Steps**:
```bash
# Check if cleanup task is running
docker logs ai-agent 2>&1 | grep "_session_cleanup_task"

# Manually trigger cleanup (requires code access)
# OR wait 6+ minutes and check logs
```

---

## 📝 **Test Execution Log Template**

```markdown
## Smoke Test Execution - [DATE]

**Environment**:
- Docker Compose version: X.X.X
- AI Agent version: 2.0.0
- Asterisk version: X.X

**Test Results**:

### TEST 1: Single Call
- Status: ✅ PASS / ❌ FAIL
- Duration: X seconds
- Notes: [any observations]

### TEST 2: Two Simultaneous Calls
- Status: ✅ PASS / ❌ FAIL
- Sessions created: X
- Notes: [any observations]

[... repeat for all tests ...]

**Overall Result**: ✅ PASS / ❌ FAIL

**Issues Found**:
1. [Issue description]
2. [Issue description]

**Action Items**:
- [ ] Fix issue #1
- [ ] Fix issue #2
```

---

## 🔗 **References**

- **CHANGELOG.md**: Breaking changes and migration guide
- **README_v2.md**: Usage instructions
- **Unit Tests**: `tests/test_rtp_session.py`, `tests/test_vad.py`
- **Integration Tests**: `tests/test_integration_sessions.py`

---

## ✅ **Sign-Off**

**Tested By**: [Name]
**Date**: [Date]
**Version**: v2.0.0
**Result**: ✅ PASS / ❌ FAIL

---

**Next Steps After Smoke Tests**:
1. If PASS → Deploy to staging
2. If FAIL → Review logs, fix issues, re-run unit/integration tests
3. Document any production-specific configurations needed
