# 🤖 AI Voice Agent - PoC

**Real-time voice conversations between traditional telephony (SIP/PSTN/WebRTC) and AI Agent using RTP/G.711 ulaw**

[![Docker](https://img.shields.io/badge/Docker-Ready-blue)](https://www.docker.com/)
[![Python](https://img.shields.io/badge/Python-3.11+-green)](https://www.python.org/)
[![Asterisk](https://img.shields.io/badge/Asterisk-16.28-orange)](https://www.asterisk.org/)
[![WebRTC](https://img.shields.io/badge/WebRTC-Enabled-brightgreen)](https://webrtc.org/)

---

## 📋 Overview

This Proof of Concept (PoC) demonstrates how to integrate traditional telephone systems **and modern WebRTC browsers** with an AI-powered conversational agent. Users can call from a SIP phone or connect via web browser and have natural voice conversations with an AI in real-time.

### Architecture

```
📞 SIP Phone ──────┐
                   │
🌐 WebRTC Browser ─┼──→ Asterisk (PABX) ──→ ARI ExternalMedia ──→ AI Agent
                   │      (Bridge)              RTP/G.711 ulaw     ├─ ASR (Whisper)
📱 PSTN Line ──────┘                                               ├─ LLM (Phi-3)
                                                                   └─ TTS (Piper)
```

**Key Innovation**: Using Asterisk ARI (REST Interface) + ExternalMedia to route RTP audio directly to Python application with asyncari library for modern async/await patterns.

### Key Features

- ✅ **WebRTC Support** - Call from any modern web browser (Chrome, Firefox, Safari)
- ✅ **SIP/PSTN Compatible** - Traditional phone systems supported
- ✅ **Real-time RTP Processing** - 50 packets/second at 8kHz
- ✅ **Modern Async Architecture** - Built with asyncari 0.20.6 and asyncio
- ✅ **Real-time Statistics** - Live monitoring of audio packets and throughput
- ✅ **On-premise Deployment** - No cloud dependencies
- ✅ **CPU-only Inference** - No GPU required
- ✅ **Docker-based** - Setup in < 15 minutes
- 🚧 **Full-duplex Communication** (In Progress - Phase 2)
- 🚧 **Barge-in Support** (Planned - Phase 4)

---

## 🚀 Quick Start

### Prerequisites

- Docker 20.10+ ([Install Docker](https://docs.docker.com/get-docker/))
- Docker Compose 1.29+ ([Install Compose](https://docs.docker.com/compose/install/))
- 8GB RAM minimum
- 4 CPU cores recommended

### Installation

```bash
# 1. Clone repository
git clone <your-repo-url>
cd ai-voice-agent

# 2. Setup (builds images, configures environment)
./scripts/setup.sh

# 3. Start the stack
./scripts/start.sh

# 4. View logs
./scripts/logs.sh
```

**That's it!** Your AI Voice Agent is now running. 🎉

---

## 📱 How to Connect

You have **3 options** to test the AI Voice Agent:

### Option 1: WebRTC Browser (Recommended ✨)

**No softphone needed!** Connect directly from your web browser:

1. Open your browser and go to: `https://<YOUR_MACHINE_IP>:8089`
2. **Accept the self-signed certificate warning** (click "Advanced" → "Proceed")
3. Configure Browser-Phone:
   - **Secure WebSocket Server (TLS):** `<YOUR_MACHINE_IP>`
   - **WebSocket Port:** `8089`
   - **WebSocket Path:** `ws`
   - **SIP Username:** `webrtc`
   - **SIP Password:** `1234`
4. Click "Register" ✅
5. Dial `9999` to reach the AI Agent

> **Note**: For localhost testing, use `https://localhost:8089` instead.

### Option 2: SIP Softphone

Configure any SIP softphone (Zoiper, Linphone, etc.):

- **SIP Server**: `<YOUR_MACHINE_IP>:5060`
- **Username**: `1000`
- **Password**: `1000`
- **Protocol**: UDP

### Option 3: Physical SIP Phone

Connect your IP phone using the same credentials as Option 2.

### Test Extensions

- **9999**: 🤖 AI Voice Agent (routes to Stasis app via ARI)
- **100**: 🔊 Echo test (validates audio path)

---

## 🧪 Testing

### 1. Make a Test Call

#### WebRTC Browser:
1. Access `https://<YOUR_MACHINE_IP>:8089`
2. Register with credentials (see above)
3. Dial `100` → Should hear your own voice (echo test) ✅
4. Dial `9999` → Connects to AI Agent (RTP flow validated)

#### SIP Softphone:
1. Register your softphone
2. Dial `100` → Echo test
3. Dial `9999` → AI Agent

### 2. Expected Behavior (Phase 2 - Audio Decoding)

- ✅ Call connects automatically
- ✅ Bridge stays connected (no codec errors)
- ✅ RTP packets flow at 50 pkt/s
- ✅ Audio decoded to PCM in real-time
- ✅ Zero packet loss
- 🚧 AI response (Phase 3 - pending)

### 3. Check Logs

```bash
./scripts/logs.sh

# Expected output during active call:
# ai-agent | 📞 New call received!
# ai-agent | ✅ Call bridged successfully!
# ai-agent | 🎤 First RTP packet received from ('172.20.0.10', 10082)
# ai-agent | 📊 RTP Stats: 101 packets (17.0KB) in 2.0s - 50 pkt/s
# ai-agent | 🎵 Audio: 101 frames decoded (31.6KB PCM) - Loss: 0.00%
# ai-agent | 📊 RTP Stats: 202 packets (33.9KB) in 4.0s - 50 pkt/s
# ai-agent | 🎵 Audio: 202 frames decoded (63.1KB PCM) - Loss: 0.00%
# ai-agent | 📊 RTP Stats: 303 packets (50.9KB) in 6.0s - 50 pkt/s
# ai-agent | 🎵 Audio: 303 frames decoded (94.7KB PCM) - Loss: 0.00%
```

**What this means:**
- ✅ 50 pkt/s = Perfect G.711 ulaw codec operation (20ms packetization)
- ✅ ~172 bytes/packet = Correct RTP header (12B) + payload (160B)
- ✅ Audio decoded to PCM = Ready for AI processing (Whisper ASR)
- ✅ 2x expansion ratio = 160B G.711 → 320B PCM (16-bit samples)
- ✅ 0.00% packet loss = Perfect network conditions
- ✅ No "path to translate" errors = Codec compatibility working

---

## 🏆 Technical Achievements

### Phase 1: Infrastructure (Complete ✅)

#### WebRTC Integration
- ✅ **Self-signed SSL certificates** with Subject Alternative Names (SAN)
- ✅ **Browser-Phone** accessible via HTTPS (port 8089)
- ✅ **WebSocket Secure (WSS)** for SIP over WebRTC
- ✅ **DTLS/SRTP** media encryption configured

#### Asterisk ARI
- ✅ **asyncari 0.20.6** - Latest async Python library
- ✅ **Event-driven architecture** with async/await patterns
- ✅ **ExternalMedia channels** routing RTP to AI Agent
- ✅ **Bridge management** without codec translation errors
- ✅ **Automatic cleanup** on call hangup

#### RTP Flow
- ✅ **Real-time packet reception** at 50 pkt/s
- ✅ **Live statistics** every 2 seconds
- ✅ **Non-blocking I/O** with asyncio
- ✅ **Large buffer size** (4MB) to prevent packet loss

#### Codec Compatibility
- ✅ **G.711 ulaw** working perfectly (8kHz, 20ms packetization)
- ✅ **No opus** (codec_opus.so not available - properly handled)
- ✅ **Stable bridges** - no "path to translate" errors
- ✅ **Validated metrics** - packet rate, size, and timing all correct

### Phase 2: Audio Processing (In Progress 🚧)

#### RTP Parser (RFC 3550)
- ✅ **Header parsing** - Version, payload type, sequence, timestamp, SSRC
- ✅ **CSRC handling** - Multiple contributing sources supported
- ✅ **Packet loss detection** - Sequence number tracking
- ✅ **Statistics** - Parse errors, loss rate calculation

#### G.711 Codec
- ✅ **μ-law decoder** - 8-bit companded → 16-bit linear PCM
- ✅ **Python audioop** - Native implementation (no external deps)
- ✅ **NumPy integration** - Convert to/from numpy arrays for DSP
- ✅ **Real-time decode** - 50 frames/second @ 20ms packetization
- ✅ **Compression metrics** - 2x expansion validated (160B → 320B)

#### Audio Quality
- ✅ **Zero packet loss** - 0.00% loss rate observed in testing
- ✅ **Perfect timing** - 50 pkt/s exactly as expected
- ✅ **PCM output** - 251.6KB decoded from 135.2KB G.711 (16s call)

### Lessons Learned

**Phase 1:**
1. **asyncari over custom WebSocket** - Community libraries save 80% development time
2. **Codec availability matters** - Missing codec_opus.so required fallback to ulaw/alaw
3. **SSL SAN for WebRTC** - IP addresses must be in certificate SAN, not just CN
4. **Browser-Phone path** - Asterisk expects static files in `/usr/share/asterisk/static-http/`
5. **Event filtering** - ExternalMedia channels trigger StasisStart, must filter to prevent loops

**Phase 2:**
1. **Python audioop is powerful** - Built-in G.711 codec eliminates external dependencies
2. **struct.unpack for RTP** - Standard library sufficient for binary protocol parsing
3. **Packet loss tracking** - Sequence number wrap-around (16-bit) must be handled
4. **Real-time decode works** - No buffering needed for G.711 (sample-by-sample)
5. **PCM ready for AI** - 16-bit signed little-endian format is numpy-compatible

---

## 🛠️ Development

### Project Structure

```
ai-voice-agent/
├── docker/
│   ├── asterisk/            # Asterisk PABX container
│   │   ├── Dockerfile
│   │   ├── configs/         # ARI, SIP, dialplan configs
│   │   └── entrypoint.sh
│   └── ai-agent/            # AI Agent container
│       ├── Dockerfile
│       ├── requirements.txt
│       └── entrypoint.sh
├── src/                     # Python source code
│   ├── ari/                 # ARI client (Asterisk integration)
│   ├── rtp/                 # RTP server
│   ├── codec/               # G.711 codec (TODO)
│   ├── asr/                 # Whisper integration (TODO)
│   ├── llm/                 # LLM integration (TODO)
│   ├── tts/                 # TTS integration (TODO)
│   └── utils/               # Utilities
├── scripts/                 # Automation scripts
├── tests/                   # Unit tests
├── docker-compose.yml       # Docker orchestration
└── README.md
```

### Scripts

- `./scripts/setup.sh` - Initial setup (run once)
- `./scripts/start.sh` - Start stack
- `./scripts/stop.sh` - Stop stack
- `./scripts/logs.sh` - View logs
- `./scripts/reset.sh` - Complete reset (removes volumes)

### Environment Variables

Edit `.env` file:

```bash
# Whisper ASR
WHISPER_MODEL=base  # tiny, base, small, medium

# LLM
LLM_MODEL=phi-3-mini

# TTS
TTS_VOICE=pt_BR-faber-medium

# Asterisk ARI
ASTERISK_ARI_PASSWORD=ChangeMe123!

# Logging
LOG_LEVEL=INFO
```

---

## 🏗️ Implementation Roadmap

This PoC follows a structured roadmap with 6 phases:

### Phase Status

- [x] **Phase 0**: Docker Infrastructure ✅ **COMPLETE**
  - [x] Asterisk container with WebRTC support
  - [x] AI Agent Python container
  - [x] Network bridge configuration
  - [x] SSL certificates with SAN for WebRTC

- [x] **Phase 1**: Asterisk + ARI + WebRTC ✅ **COMPLETE**
  - [x] ARI client with asyncari 0.20.6
  - [x] WebSocket connection handling
  - [x] StasisStart/StasisEnd events
  - [x] ExternalMedia channel creation
  - [x] Bridge management (no codec errors)
  - [x] WebRTC endpoint configuration (ulaw/alaw)
  - [x] Browser-Phone integration
  - [x] RTP flow validation (50 pkt/s)
  - [x] Real-time statistics logging

- [ ] **Phase 2**: RTP Parser + G.711 Codec 🚧 **IN PROGRESS**
  - [x] RTP header parser (sequence, timestamp, SSRC)
  - [x] G.711 ulaw decoder → PCM 16-bit
  - [x] Packet loss detection (0.00% observed)
  - [x] Real-time decode statistics
  - [ ] Audio buffer management
  - [ ] VAD (Voice Activity Detection)
  - [ ] PCM → G.711 ulaw encoder
  - [ ] RTP packet builder

- [ ] **Phase 3**: AI Pipeline (ASR + LLM + TTS)
  - [ ] Whisper.cpp integration (ASR)
  - [ ] Phi-3 via llama.cpp (LLM)
  - [ ] Piper TTS integration
  - [ ] Pipeline orchestration

- [ ] **Phase 4**: Full-Duplex + Barge-in
  - [ ] Simultaneous send/receive
  - [ ] DTMF detection for barge-in
  - [ ] TTS interruption handling

- [ ] **Phase 5**: Testing & Validation
  - [ ] Latency measurements
  - [ ] Call quality metrics
  - [ ] Load testing

- [ ] **Phase 6**: Documentation
  - [ ] API documentation
  - [ ] Architecture diagrams
  - [ ] Deployment guide

See [ROADMAP](../ROADMAP_POC_TELEFONIA_AI.md) for detailed implementation plan.

---

## 🐛 Troubleshooting

### WebRTC Browser Connection Issues

**Problem**: SSL certificate warning won't accept

**Solution**:
1. Open separate tab: `https://<YOUR_IP>:8089/ws`
2. Click "Advanced" → "Proceed to <IP> (unsafe)"
3. Return to Browser-Phone tab and retry registration

**Problem**: "No path to translate" error in Asterisk logs

**Solution**: This was fixed in Phase 1 by:
- Removing opus codec (codec_opus.so not available)
- Using only ulaw/alaw codecs
- Regenerating SSL certificate with proper SAN

### Container won't start

```bash
# Check logs
docker-compose logs asterisk
docker-compose logs ai-agent

# Rebuild images
docker-compose build --no-cache
```

### Softphone won't register

- Verify port 5060/UDP is not blocked by firewall
- Use your machine's actual IP (not localhost)
- Check password in `.env` matches softphone config
- For WebRTC: Accept SSL certificate first (see above)

### No audio / RTP not working

```bash
# Check if RTP port is listening
docker exec -it ai-agent netstat -ulnp | grep 5080

# Check RTP statistics in logs
docker logs ai-agent 2>&1 | grep "RTP Stats"

# Should show: 📊 RTP Stats: XXX packets (XX.XKB) in X.Xs - 50 pkt/s
```

**Expected RTP metrics:**
- Packet rate: 50 pkt/s (G.711 ulaw at 8kHz with 20ms packetization)
- Packet size: ~172 bytes (12B RTP header + 160B payload)
- Bitrate: ~68 Kbps

### Bridge immediately disconnects

**Problem**: Channels join bridge but immediately leave

**Root cause**: Codec translation failure (typically opus ↔ ulaw)

**Solution**: Verify WebRTC endpoint config in `docker/asterisk/configs/pjsip.conf`:
```ini
[webrtc]
disallow=all
allow=ulaw
allow=alaw
# opus removed - codec_opus.so not available
```

Then rebuild Asterisk:
```bash
docker-compose build asterisk && docker-compose up -d asterisk
```

### High latency (Phase 3+)

- Try smaller Whisper model: `WHISPER_MODEL=tiny`
- Ensure sufficient CPU resources
- Check `docker stats` for resource usage

---

## 📚 Documentation

- [Architecture Decision Record (ADR)](../po_c_telefonia_sip_pstn_ai_agent_rtp_pcma.md)
- [Complete Roadmap](../ROADMAP_POC_TELEFONIA_AI.md)
- [Docker Architecture](../DOCKER_ARCHITECTURE.md)
- [Quick Start Guide](../QUICKSTART_DOCKER.md)

---

## 🤝 Contributing

This is a PoC project. Contributions are welcome!

### Development Workflow

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test with `docker-compose up`
5. Submit a pull request

---

## 📄 License

[MIT License](LICENSE) (or your preferred license)

---

## 🙏 Acknowledgments

- [Asterisk](https://www.asterisk.org/) - Open-source telephony platform with ARI
- [asyncari](https://github.com/M-o-a-T/asyncari) - Modern async Python client for Asterisk ARI
- [Browser-Phone](https://github.com/InnovateAsterisk/Browser-Phone) - WebRTC SIP phone for browsers
- [Whisper.cpp](https://github.com/ggerganov/whisper.cpp) - Efficient ASR
- [llama.cpp](https://github.com/ggerganov/llama.cpp) - CPU-optimized LLM inference
- [Piper TTS](https://github.com/rhasspy/piper) - Fast neural TTS

---

## 📞 Support

- Issues: [GitHub Issues](https://github.com/your-repo/issues)
- Documentation: [Index](../INDEX_ROADMAP_POC.md)

---

**Built with ❤️ for real-time AI voice interactions**
