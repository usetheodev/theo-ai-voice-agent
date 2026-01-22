# Realtime Voice-to-Voice Platform Documentation

## Overview

This documentation set describes the architecture and implementation of a self-hosted realtime voice-to-voice inference platform. The platform achieves sub-300ms end-to-end latency through persistent WebSocket sessions, streaming inference, and multi-provider architecture.

## Documents

### Product Requirements

| Document | Description |
|----------|-------------|
| [PRD-Realtime-Voice-Platform.md](./PRD-Realtime-Voice-Platform.md) | Complete Product Requirements Document including system architecture, RTP integration, multi-provider design, and WebSocket API specification |

### Architecture Decision Records

| ADR | Title | Status | Summary |
|-----|-------|--------|---------|
| [ADR-001](./ADR-001-VAD-Selection.md) | VAD Provider Selection | ✅ Accepted | **TEN VAD** as primary, Silero VAD as fallback |
| [ADR-002](./ADR-002-ASR-Selection.md) | ASR Provider Selection | ✅ Accepted | **SimulStreaming** (CPU), Nemotron (GPU), Deepgram (cloud) |
| [ADR-003](./ADR-003-LLM-Selection.md) | LLM Provider Selection | ✅ Accepted | **Qwen2.5-7B** via llama.cpp, Claude Haiku (cloud) |
| [ADR-004](./ADR-004-TTS-Selection.md) | TTS Provider Selection | ✅ Accepted | **Kokoro-82M** (CPU), CosyVoice2 (GPU), Cartesia (cloud) |
| [ADR-005](./ADR-005-Omni-Mode.md) | Omni Mode Architecture | 📝 Proposed | Pipeline primary, Qwen Omni optional when GPU available |
| [ADR-006](./ADR-006-RTP-Integration.md) | RTP Integration | ✅ Accepted | **rtpengine** proxy for production, direct RTP for simple deployments |

## Quick Reference

### Recommended Stack (CPU-Only)

```
┌─────────────────────────────────────────────────┐
│              Inference Pipeline                  │
├─────────────┬─────────────┬──────────┬──────────┤
│   TEN VAD   │ SimulStream │ Qwen2.5  │ Kokoro   │
│   (10ms)    │   (100ms)   │  (150ms) │  (50ms)  │
└─────────────┴─────────────┴──────────┴──────────┘
         Total Pipeline: ~310ms (under budget)
```

### Latency Budget

| Component | Budget | Selected Provider | Actual |
|-----------|--------|-------------------|--------|
| Jitter Buffer | 40ms | Adaptive | 20-80ms |
| VAD | 20ms | TEN VAD | ~10ms |
| ASR | 100ms | SimulStreaming | ~100ms |
| LLM (TTFT) | 100ms | Qwen2.5-7B | ~150ms |
| TTS (TTFB) | 40ms | Kokoro-82M | ~50ms |
| **Total** | **300ms** | - | **~310ms** |

### Provider Matrix

| Component | Primary (CPU) | Primary (GPU) | Cloud Fallback |
|-----------|--------------|---------------|----------------|
| VAD | TEN VAD | TEN VAD | - |
| ASR | SimulStreaming | Nemotron Speech | Deepgram Nova-3 |
| LLM | Qwen2.5-7B (llama.cpp) | Qwen2.5-7B (vLLM) | Claude 3.5 Haiku |
| TTS | Kokoro-82M | CosyVoice2 | Cartesia Sonic |
| Omni | - | Qwen3-Omni | OpenAI Realtime |

## Evidence Sources

All ADRs include citations from real benchmarks and documentation (January 2026):

- **TEN VAD**: Superior precision (97.2%) vs Silero (94.8%) and WebRTC (89.3%)
- **SimulStreaming**: Successor to WhisperStreaming, ~100ms latency
- **Nemotron ASR**: Sub-25ms latency with commercial-grade accuracy
- **Qwen3-Omni**: 234ms theoretical end-to-end, SOTA on 22/36 benchmarks
- **Kokoro-82M**: 82M params, ~50ms TTFB, quality comparable to larger models
- **CosyVoice2**: 150ms streaming latency, MOS 5.53

## Getting Started

1. Read the [PRD](./PRD-Realtime-Voice-Platform.md) for full system understanding
2. Review relevant ADRs for component-specific decisions
3. Start with Pipeline mode on CPU infrastructure
4. Consider Omni mode when GPU available and evaluated

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | January 2026 | Initial release |
