# 🤖 AI Voice Agent - PoC

**Real-time voice conversations between traditional telephony (SIP/PSTN) and AI Agent using RTP/G.711 A-law**

[![Docker](https://img.shields.io/badge/Docker-Ready-blue)](https://www.docker.com/)
[![Python](https://img.shields.io/badge/Python-3.11+-green)](https://www.python.org/)
[![Asterisk](https://img.shields.io/badge/Asterisk-VoIP-orange)](https://www.asterisk.org/)

---

## 📋 Overview

This Proof of Concept (PoC) demonstrates how to integrate traditional telephone systems with an AI-powered conversational agent. Users can call a phone number and have natural voice conversations with an AI in real-time.

### Architecture

```
📞 Phone (SIP/PSTN) → Asterisk (PABX) → ARI ExternalMedia → AI Agent
                                        RTP/G.711 A-law     ├─ ASR (Whisper)
                                                            ├─ LLM (Phi-3)
                                                            └─ TTS (Piper)
```

**Key Innovation**: Using Asterisk ARI (REST Interface) + ExternalMedia to route RTP audio directly to Python application.

### Key Features

- ✅ **Real-time voice processing** (< 3s latency goal)
- ✅ **Full-duplex communication** (talk and listen simultaneously)
- ✅ **Barge-in support** (interrupt AI while speaking)
- ✅ **On-premise deployment** (no cloud dependencies)
- ✅ **CPU-only inference** (no GPU required)
- ✅ **Docker-based** (setup in < 15 minutes)

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

## 📱 Configure SIP Softphone

To test the PoC, configure a SIP softphone (like Zoiper or Linphone):

### Settings

- **SIP Server**: `<YOUR_MACHINE_IP>:5060`
- **Username**: `1000`
- **Password**: `1000`
- **Protocol**: UDP

### Test Extensions

- **9999**: AI Voice Agent (routes to Stasis app via ARI)
- **100**: Echo test (for audio validation)

---

## 🧪 Testing

### 1. Make a Test Call

1. Open your configured softphone
2. Dial `100` → Should hear your own voice (echo test)
3. Dial `9999` → Should connect to AI Agent

### 2. Expected Behavior

- ✅ Call connects automatically
- ✅ You hear silence (AI waiting for you to speak)
- ✅ Speak in Portuguese
- ✅ AI responds after 2-3 seconds

### 3. Check Logs

```bash
./scripts/logs.sh

# Expected output:
# ai-agent    | 📡 RTP receive loop started
# ai-agent    | 🎤 First RTP packet received from...
# ai-agent    | RTP stats: 50 packets, 8.1KB received
```

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

- [x] **Phase 0**: Docker Infrastructure (COMPLETE)
- [x] **Phase 1**: Asterisk + ARI Configuration (COMPLETE)
- [ ] **Phase 2**: RTP Endpoint + G.711 Codec (IN PROGRESS)
- [ ] **Phase 3**: AI Pipeline (ASR + LLM + TTS)
- [ ] **Phase 4**: Full-Duplex + Barge-in
- [ ] **Phase 5**: Testing & Validation
- [ ] **Phase 6**: Documentation

See [ROADMAP](../ROADMAP_POC_TELEFONIA_AI.md) for detailed implementation plan.

---

## 🐛 Troubleshooting

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

### No audio / RTP not working

```bash
# Check if RTP port is listening
docker exec -it ai-agent netstat -ulnp | grep 5080

# Capture RTP packets
docker exec -it ai-agent tcpdump -i eth0 udp port 5080 -vv
```

### High latency

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
- [Whisper.cpp](https://github.com/ggerganov/whisper.cpp) - Efficient ASR
- [llama.cpp](https://github.com/ggerganov/llama.cpp) - CPU-optimized LLM inference
- [Piper TTS](https://github.com/rhasspy/piper) - Fast neural TTS

---

## 📞 Support

- Issues: [GitHub Issues](https://github.com/your-repo/issues)
- Documentation: [Index](../INDEX_ROADMAP_POC.md)

---

**Built with ❤️ for real-time AI voice interactions**
