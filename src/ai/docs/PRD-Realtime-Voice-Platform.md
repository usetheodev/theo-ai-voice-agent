# Product Requirements Document: Realtime Voice-to-Voice Inference Platform

**Version:** 1.0  
**Date:** January 2026  
**Status:** Draft  
**Author:** Platform Architecture Team

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Problem Statement](#2-problem-statement)
3. [Solution Overview](#3-solution-overview)
4. [System Architecture](#4-system-architecture)
5. [RTP Integration Specification](#5-rtp-integration-specification)
6. [Multi-Provider Architecture](#6-multi-provider-architecture)
7. [WebSocket API Specification](#7-websocket-api-specification)
8. [Session Management](#8-session-management)
9. [Latency Budget](#9-latency-budget)
10. [Non-Functional Requirements](#10-non-functional-requirements)
11. [Deployment Architecture](#11-deployment-architecture)
12. [ADR References](#12-adr-references)

---

## 1. Executive Summary

### 1.1 Vision

Build a self-hosted, production-grade realtime voice-to-voice inference platform that achieves sub-300ms end-to-end latency while supporting multiple inference providers and seamless integration with telephony infrastructure via RTP.

### 1.2 Key Differentiators

| Aspect | Traditional Approach | Our Approach |
|--------|---------------------|--------------|
| Architecture | REST request-response | Persistent streaming sessions |
| Latency | 2-5 seconds | < 300ms end-to-end |
| Provider Lock-in | Single vendor | Multi-provider with failover |
| Deployment | Cloud-only | Self-hosted + hybrid |
| Integration | HTTP webhooks | Native RTP + WebSocket |

### 1.3 Success Metrics

| Metric | Target | Measurement Method |
|--------|--------|-------------------|
| Voice-to-Voice Latency (P95) | < 300ms | Waveform timestamp analysis |
| First Audio Byte (TTS) | < 150ms | Server instrumentation |
| ASR Word Error Rate | < 10% | LibriSpeech test set |
| Concurrent Sessions/Node | > 100 | Load testing with realistic traffic |
| Provider Failover Time | < 50ms | Synthetic failure injection |
| System Availability | 99.9% | Uptime monitoring |

---

## 2. Problem Statement

### 2.1 Current State Analysis

Voice AI systems today suffer from **architectural latency** rather than model latency. The typical integration pattern:

```
User Speech → HTTP POST → ASR Service → Wait for complete text
    → HTTP POST → LLM Service → Wait for complete response  
    → HTTP POST → TTS Service → Wait for complete audio
    → Play Audio
```

**Measured latencies in production systems:**

| Component | Typical Latency | Source |
|-----------|----------------|--------|
| ASR (batch) | 500-800ms | Whisper API benchmarks |
| LLM (complete) | 800-2000ms | GPT-4 API measurements |
| TTS (batch) | 400-600ms | ElevenLabs API |
| Network overhead | 200-400ms | 3 round trips × RTT |
| **Total** | **2-4 seconds** | End-to-end measurement |

### 2.2 Root Causes

1. **Synchronous Processing**: Each component waits for complete input before starting
2. **No Streaming**: Text and audio generated as complete units
3. **Session Overhead**: New connection per request
4. **No State**: Context rebuilt on every interaction

### 2.3 Industry Benchmark

OpenAI Realtime API (released late 2024) demonstrated that sub-300ms latency is achievable through:

- Persistent WebSocket sessions
- Bidirectional audio streaming
- Server-side conversation state
- Token + audio as continuous streams

**Our goal: Replicate this capability with self-hosted infrastructure and multi-provider flexibility.**

---

## 3. Solution Overview

### 3.1 Core Principles

```
Principle 1: Never wait for complete input
Principle 2: Never generate complete output
Principle 3: Maintain persistent session state
Principle 4: Stream everything bidirectionally
Principle 5: Abstract provider selection
```

### 3.2 Operating Modes

#### Pipeline Mode (Recommended for CPU)

```
┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐
│   VAD   │───▶│   ASR   │───▶│   LLM   │───▶│   TTS   │
│(stream) │    │(stream) │    │(stream) │    │(stream) │
└─────────┘    └─────────┘    └─────────┘    └─────────┘
     │              │              │              │
     ▼              ▼              ▼              ▼
  10-20ms      partial text     tokens      audio chunks
```

**Characteristics:**
- Maximum control over each component
- Easier debugging and monitoring
- Can swap individual providers
- Works on CPU-only infrastructure

#### Omni Mode (Requires GPU)

```
┌─────────────────────────────────────────┐
│           Multimodal Model              │
│  (Qwen2.5-Omni / Qwen3-Omni)           │
│                                         │
│  Audio In ──────────▶ Audio + Text Out  │
└─────────────────────────────────────────┘
```

**Characteristics:**
- Single model, less integration complexity
- Potentially lower latency (no inter-component overhead)
- Requires GPU (minimum 8GB VRAM for 7B quantized)
- Less flexibility in component selection

### 3.3 Feature Scope

#### Phase 1 (MVP)
- [ ] RTP ingestion with G.711 codec support
- [ ] Pipeline mode with local providers
- [ ] Single-turn conversations
- [ ] WebSocket API for control plane
- [ ] Basic health monitoring

#### Phase 2
- [ ] Multi-turn conversation context
- [ ] Cloud provider integration
- [ ] Automatic failover
- [ ] Barge-in/interrupt support
- [ ] DTMF detection

#### Phase 3
- [ ] Omni mode support
- [ ] Multi-language switching
- [ ] Voice cloning integration
- [ ] Analytics dashboard
- [ ] Custom model fine-tuning pipeline

---

## 4. System Architecture

### 4.1 Layer Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                    Layer 4: Provider Abstraction                  │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐            │
│  │  Local   │ │  Cloud   │ │  Hybrid  │ │ Fallback │            │
│  │ Providers│ │ Providers│ │  Router  │ │  Chain   │            │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘            │
├──────────────────────────────────────────────────────────────────┤
│                    Layer 3: Inference Pipeline                    │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐            │
│  │   VAD    │ │   ASR    │ │   LLM    │ │   TTS    │            │
│  │ Provider │ │ Provider │ │ Provider │ │ Provider │            │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘            │
├──────────────────────────────────────────────────────────────────┤
│                    Layer 2: Session Manager                       │
│  ┌────────────────┐ ┌─────────────┐ ┌──────────────────┐        │
│  │ Session State  │ │ Backpressure│ │ Context Window   │        │
│  │   Machine      │ │   Control   │ │   Management     │        │
│  └────────────────┘ └─────────────┘ └──────────────────┘        │
├──────────────────────────────────────────────────────────────────┤
│                 Layer 1: Audio Transport Layer                    │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐            │
│  │   RTP    │ │  Jitter  │ │   AEC    │ │  Codec   │            │
│  │ Receiver │ │  Buffer  │ │  Filter  │ │  Decoder │            │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘            │
└──────────────────────────────────────────────────────────────────┘
```

### 4.2 Component Responsibilities

#### Layer 1: Audio Transport Layer

| Component | Responsibility | Interface |
|-----------|---------------|-----------|
| RTP Receiver | UDP socket management, packet parsing | `RTPPacket` events |
| Jitter Buffer | Packet reordering, timing normalization | `PCMFrame` at fixed intervals |
| AEC Filter | Echo cancellation using TTS reference | Cleaned `PCMFrame` |
| Codec Decoder | G.711/G.722/Opus → PCM16 conversion | `Int16Array` samples |

#### Layer 2: Session Manager

| Component | Responsibility | Interface |
|-----------|---------------|-----------|
| Session State Machine | Lifecycle: INIT → LISTENING → PROCESSING → SPEAKING | State events |
| Backpressure Control | Rate limiting when inference lags | Pause/resume signals |
| Context Manager | Conversation history, token budgeting | Context window |
| Interrupt Handler | Barge-in detection, TTS cancellation | Interrupt events |

#### Layer 3: Inference Pipeline

| Component | Responsibility | Interface |
|-----------|---------------|-----------|
| VAD | Speech boundary detection | `SpeechStart`/`SpeechEnd` events |
| ASR | Audio → text transcription | `PartialTranscript`/`FinalTranscript` |
| LLM | Text generation with context | `Token` stream |
| TTS | Text → audio synthesis | `AudioChunk` stream |

#### Layer 4: Provider Abstraction

| Component | Responsibility | Interface |
|-----------|---------------|-----------|
| Provider Registry | Available providers and capabilities | `ProviderInfo[]` |
| Router | Provider selection based on strategy | `SelectedProvider` |
| Health Monitor | Latency/error tracking, circuit breaker | `HealthStatus` |
| Failover Manager | Automatic provider switching | Transparent to pipeline |

### 4.3 Data Structures

```typescript
// Core frame type flowing through the system
interface AudioFrame {
  sessionId: string;
  timestamp: number;        // Unix timestamp in ms
  rtpTimestamp: number;     // Original RTP timestamp
  sequenceNumber: number;   // For ordering
  samples: Int16Array;      // PCM16 @ configured sample rate
  sampleRate: 8000 | 16000 | 48000;
  isSpeech?: boolean;       // Set by VAD
}

// Session state
interface Session {
  id: string;
  state: 'INIT' | 'LISTENING' | 'PROCESSING' | 'SPEAKING' | 'INTERRUPTED' | 'CLOSED';
  config: SessionConfig;
  context: ConversationContext;
  metrics: SessionMetrics;
  createdAt: number;
  lastActivityAt: number;
}

// Conversation context for multi-turn
interface ConversationContext {
  messages: Message[];
  tokenCount: number;
  maxTokens: number;
  systemPrompt: string;
}

// Provider-agnostic message format
interface Message {
  role: 'system' | 'user' | 'assistant';
  content: string;
  audioRef?: string;        // Reference to stored audio
  timestamp: number;
}
```

---

## 5. RTP Integration Specification

### 5.1 Overview

The system integrates with telephony infrastructure via Real-time Transport Protocol (RTP). This section specifies the complete integration including codec handling, timing, and network considerations.

### 5.2 Network Topology Options

#### Option A: Direct RTP (Simple Deployments)

```
┌─────────┐         RTP/UDP          ┌──────────────────┐
│   PBX   │ ◀────────────────────▶  │ Inference Server │
│  (SBC)  │                          │   (RTP Endpoint) │
└─────────┘                          └──────────────────┘
     │                                        │
     │          SIP Signaling                 │
     └────────────────────────────────────────┘
```

**Configuration:**
```yaml
rtp:
  bind_address: "0.0.0.0"
  port_range: [10000, 20000]
  external_ip: "${PUBLIC_IP}"  # For NAT traversal
  
srtp:
  enabled: true
  crypto_suite: "AES_CM_128_HMAC_SHA1_80"
  
sip:
  enabled: true
  port: 5060
  transport: ["udp", "tcp", "tls"]
```

#### Option B: RTP Proxy (Production Recommended)

```
┌─────────┐      RTP       ┌───────────┐    Internal    ┌──────────────────┐
│   PBX   │ ◀────────────▶ │ rtpengine │ ◀────────────▶ │ Inference Server │
│  (SBC)  │                │  (proxy)  │   Unix Socket  │                  │
└─────────┘                └───────────┘                └──────────────────┘
```

**Benefits:**
- NAT traversal handled by proxy
- SRTP termination at edge
- Load balancing across inference nodes
- Media recording/forking capability

**rtpengine Configuration:**
```ini
[rtpengine]
table = 0
interface = external/192.0.2.1;internal/10.0.0.1
listen-ng = 127.0.0.1:2223
port-min = 30000
port-max = 40000
recording-dir = /var/spool/rtpengine
log-level = 6
```

### 5.3 Supported Codecs

| Codec | PT | Sample Rate | Frame | Bandwidth | Priority |
|-------|-----|-------------|-------|-----------|----------|
| G.711 μ-law | 0 | 8000 Hz | 20ms | 64 kbps | Primary |
| G.711 A-law | 8 | 8000 Hz | 20ms | 64 kbps | Primary |
| G.722 | 9 | 16000 Hz | 20ms | 64 kbps | Secondary |
| Opus | dynamic | 48000 Hz | 20ms | 6-510 kbps | WebRTC |

**Codec Selection Logic:**
```typescript
function selectCodec(sdpOffer: SDP): Codec {
  const dominated = ['PCMU', 'PCMA', 'G722', 'opus'];
  const offered = parseCodecs(sdpOffer);
  
  for (const preferred of dominated) {
    if (offered.includes(preferred)) {
      return getCodec(preferred);
    }
  }
  
  throw new Error('No supported codec in offer');
}
```

### 5.4 Jitter Buffer Implementation

The jitter buffer normalizes packet timing to provide consistent frame delivery to the inference pipeline.

```typescript
interface JitterBufferConfig {
  minDelayMs: number;      // Minimum buffering (default: 20)
  maxDelayMs: number;      // Maximum before dropping (default: 80)
  targetDelayMs: number;   // Optimal operating point (default: 40)
  adaptationRate: number;  // How fast to adapt (default: 0.1)
}

class AdaptiveJitterBuffer {
  private buffer: Map<number, RTPPacket> = new Map();
  private currentDelay: number;
  private jitterEstimate: number = 0;
  
  constructor(private config: JitterBufferConfig) {
    this.currentDelay = config.targetDelayMs;
  }
  
  // Called when RTP packet arrives
  onPacket(packet: RTPPacket): void {
    // Calculate jitter using RFC 3550 algorithm
    const transit = Date.now() - packet.timestamp;
    const delta = Math.abs(transit - this.lastTransit);
    this.jitterEstimate += (delta - this.jitterEstimate) / 16;
    
    // Adapt buffer size
    this.adaptBufferSize();
    
    // Store packet
    this.buffer.set(packet.sequenceNumber, packet);
  }
  
  // Called at fixed intervals (e.g., every 20ms)
  getNextFrame(): AudioFrame | null {
    const targetSeq = this.expectedSequenceNumber;
    const packet = this.buffer.get(targetSeq);
    
    if (packet) {
      this.buffer.delete(targetSeq);
      this.expectedSequenceNumber++;
      return this.decodePacket(packet);
    }
    
    // Packet loss - apply concealment
    this.expectedSequenceNumber++;
    return this.concealLoss();
  }
  
  private adaptBufferSize(): void {
    // Exponential moving average
    const target = Math.min(
      this.config.maxDelayMs,
      Math.max(
        this.config.minDelayMs,
        this.jitterEstimate * 2  // 2x jitter as safety margin
      )
    );
    
    this.currentDelay = 
      (1 - this.config.adaptationRate) * this.currentDelay +
      this.config.adaptationRate * target;
  }
}
```

### 5.5 Echo Cancellation

Full-duplex voice requires acoustic echo cancellation (AEC) to prevent the TTS output from being detected as user speech.

```
┌─────────────────────────────────────────────────────────┐
│                    AEC Processing                        │
│                                                         │
│  RTP Input ─────┐                                       │
│                 ▼                                       │
│           ┌──────────┐     ┌──────────┐                │
│           │  AEC     │────▶│  Clean   │───▶ To VAD     │
│           │  Filter  │     │  Signal  │                │
│           └──────────┘     └──────────┘                │
│                 ▲                                       │
│                 │ Reference                             │
│                 │                                       │
│  TTS Output ────┘                                       │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

**Implementation using WebRTC AEC3:**
```typescript
import { AudioProcessingModule } from 'webrtc-audio-processing';

class EchoCanceller {
  private apm: AudioProcessingModule;
  
  constructor() {
    this.apm = new AudioProcessingModule({
      echoCancellation: {
        enabled: true,
        suppressionLevel: 'high',
        streamDelay: 0,
      },
      noiseSuppression: {
        enabled: true,
        level: 'moderate',
      },
      automaticGainControl: {
        enabled: true,
        targetLevel: -3,
      },
    });
  }
  
  // Process incoming audio with TTS reference
  process(
    nearEnd: Int16Array,    // Microphone input (user)
    farEnd: Int16Array      // Speaker output (TTS)
  ): Int16Array {
    // Feed reference signal
    this.apm.setFarEndSignal(farEnd);
    
    // Process and return cleaned signal
    return this.apm.processNearEndSignal(nearEnd);
  }
}
```

### 5.6 DTMF Detection

Support for Dual-Tone Multi-Frequency signaling for IVR integration.

**RFC 2833 (Telephony Events):**
```typescript
interface DTMFEvent {
  digit: string;           // '0'-'9', '*', '#', 'A'-'D'
  duration: number;        // ms
  volume: number;          // dBm0
}

function parseTelephonyEvent(packet: RTPPacket): DTMFEvent | null {
  if (packet.payloadType !== 101) return null;  // Typical dynamic PT
  
  const event = packet.payload[0];
  const endBit = (packet.payload[1] & 0x80) !== 0;
  const volume = packet.payload[1] & 0x3F;
  const duration = (packet.payload[2] << 8) | packet.payload[3];
  
  const digits = '0123456789*#ABCD';
  
  return {
    digit: digits[event],
    duration: duration / 8,  // Convert to ms
    volume: -volume,
    isEnd: endBit,
  };
}
```

**In-band Detection (Goertzel Algorithm):**
```typescript
const DTMF_FREQUENCIES = {
  low: [697, 770, 852, 941],
  high: [1209, 1336, 1477, 1633],
};

const DTMF_MAP: Record<string, [number, number]> = {
  '1': [697, 1209], '2': [697, 1336], '3': [697, 1477], 'A': [697, 1633],
  '4': [770, 1209], '5': [770, 1336], '6': [770, 1477], 'B': [770, 1633],
  '7': [852, 1209], '8': [852, 1336], '9': [852, 1477], 'C': [852, 1633],
  '*': [941, 1209], '0': [941, 1336], '#': [941, 1477], 'D': [941, 1633],
};

function detectDTMF(samples: Int16Array, sampleRate: number): string | null {
  const magnitudes: Record<number, number> = {};
  
  for (const freq of [...DTMF_FREQUENCIES.low, ...DTMF_FREQUENCIES.high]) {
    magnitudes[freq] = goertzel(samples, freq, sampleRate);
  }
  
  // Find dominant frequencies
  const lowFreq = findDominant(magnitudes, DTMF_FREQUENCIES.low);
  const highFreq = findDominant(magnitudes, DTMF_FREQUENCIES.high);
  
  if (!lowFreq || !highFreq) return null;
  
  // Map to digit
  for (const [digit, [low, high]] of Object.entries(DTMF_MAP)) {
    if (low === lowFreq && high === highFreq) {
      return digit;
    }
  }
  
  return null;
}
```

### 5.7 Timing and Synchronization

```typescript
interface RTPTiming {
  // RTP header fields
  sequenceNumber: number;   // 16-bit, wraps at 65535
  timestamp: number;        // 32-bit, increments by samples per packet
  ssrc: number;             // Synchronization source
  
  // Derived timing
  wallClockTime: number;    // When packet was received
  playoutTime: number;      // When to play (after jitter buffer)
}

// Clock drift compensation
class ClockSync {
  private rtpToWall: Map<number, number> = new Map();
  private driftEstimate: number = 0;
  
  recordMapping(rtpTs: number, wallTs: number): void {
    this.rtpToWall.set(rtpTs, wallTs);
    
    // Estimate drift using linear regression
    if (this.rtpToWall.size > 100) {
      this.driftEstimate = this.calculateDrift();
    }
  }
  
  rtpToWallClock(rtpTs: number): number {
    const baseRtp = this.rtpToWall.keys().next().value;
    const baseWall = this.rtpToWall.get(baseRtp)!;
    
    const rtpDelta = rtpTs - baseRtp;
    const expectedWallDelta = rtpDelta / this.sampleRate * 1000;
    
    return baseWall + expectedWallDelta + (this.driftEstimate * rtpDelta);
  }
}
```

---

## 6. Multi-Provider Architecture

### 6.1 Design Goals

1. **Unified Interface**: All providers implement identical streaming interfaces
2. **Hot Swapping**: Change providers mid-session for failover
3. **Health Monitoring**: Track latency, errors, availability per provider
4. **Cost Optimization**: Route based on cost/quality tradeoffs
5. **Capability Matching**: Select providers based on required features

### 6.2 Provider Interface Definition

```typescript
// Base interface for all streaming providers
interface StreamingProvider<TInput, TOutput> {
  readonly id: string;
  readonly name: string;
  readonly type: ProviderType;
  readonly capabilities: ProviderCapabilities;
  
  // Core streaming method
  stream(
    input: AsyncIterable<TInput>,
    options?: StreamOptions
  ): AsyncIterable<TOutput>;
  
  // Health and metrics
  getHealth(): HealthStatus;
  getMetrics(): ProviderMetrics;
  
  // Lifecycle
  initialize(): Promise<void>;
  shutdown(): Promise<void>;
}

type ProviderType = 'vad' | 'asr' | 'llm' | 'tts' | 'omni';

interface ProviderCapabilities {
  // Language support
  languages: string[];              // ISO 639-1 codes
  
  // Performance characteristics
  estimatedLatencyMs: number;
  maxConcurrency: number;
  
  // Features
  supportsStreaming: boolean;
  supportsInterrupt: boolean;
  supportsBargein: boolean;
  
  // Cost (optional, for routing decisions)
  costPerMinute?: number;           // USD
  costPerToken?: number;            // USD (for LLM)
  costPerCharacter?: number;        // USD (for TTS)
}

interface HealthStatus {
  healthy: boolean;
  latencyP50Ms: number;
  latencyP99Ms: number;
  errorRate: number;                // 0-1
  lastError?: Error;
  lastCheck: number;
}

interface ProviderMetrics {
  requestCount: number;
  errorCount: number;
  totalLatencyMs: number;
  bytesProcessed: number;
}
```

### 6.3 Provider Implementations

#### 6.3.1 VAD Providers

```typescript
// TEN VAD - Primary (Best precision/latency ratio)
class TenVadProvider implements StreamingProvider<AudioFrame, VadEvent> {
  readonly id = 'ten-vad';
  readonly type = 'vad';
  readonly capabilities = {
    languages: ['*'],  // Language-agnostic
    estimatedLatencyMs: 10,
    maxConcurrency: 1000,
    supportsStreaming: true,
    supportsInterrupt: true,
    supportsBargein: true,
  };
  
  async *stream(input: AsyncIterable<AudioFrame>): AsyncIterable<VadEvent> {
    const vad = new TenVad({ 
      threshold: 0.5,
      minSpeechDuration: 250,
      minSilenceDuration: 300,
    });
    
    for await (const frame of input) {
      const result = vad.process(frame.samples);
      
      if (result.speechStart) {
        yield { type: 'speech_start', timestamp: frame.timestamp };
      }
      if (result.speechEnd) {
        yield { type: 'speech_end', timestamp: frame.timestamp };
      }
    }
  }
}

// Silero VAD - Fallback
class SileroVadProvider implements StreamingProvider<AudioFrame, VadEvent> {
  readonly id = 'silero-vad';
  readonly type = 'vad';
  readonly capabilities = {
    languages: ['*'],
    estimatedLatencyMs: 15,
    maxConcurrency: 500,
    supportsStreaming: true,
    supportsInterrupt: true,
    supportsBargein: true,
  };
  
  // Implementation using ONNX runtime...
}
```

#### 6.3.2 ASR Providers

```typescript
// SimulStreaming - Primary for CPU
class SimulStreamingProvider implements StreamingProvider<AudioFrame, Transcript> {
  readonly id = 'simul-streaming';
  readonly type = 'asr';
  readonly capabilities = {
    languages: ['en', 'es', 'fr', 'de', 'pt', 'zh', 'ja', 'ko'],
    estimatedLatencyMs: 100,
    maxConcurrency: 10,
    supportsStreaming: true,
    supportsInterrupt: true,
    supportsBargein: true,
  };
  
  async *stream(input: AsyncIterable<AudioFrame>): AsyncIterable<Transcript> {
    const processor = new SimulStreamingProcessor({
      model: 'large-v3',
      language: this.config.language,
      task: 'transcribe',
    });
    
    for await (const frame of input) {
      processor.insertAudioChunk(frame.samples);
      
      const result = processor.processIter();
      if (result.text) {
        yield {
          type: result.isFinal ? 'final' : 'partial',
          text: result.text,
          confidence: result.confidence,
          timestamp: frame.timestamp,
        };
      }
    }
  }
}

// Deepgram Nova-3 - Cloud fallback
class DeepgramProvider implements StreamingProvider<AudioFrame, Transcript> {
  readonly id = 'deepgram-nova3';
  readonly type = 'asr';
  readonly capabilities = {
    languages: ['en', 'es', 'fr', 'de', 'pt', /* 30+ more */],
    estimatedLatencyMs: 150,
    maxConcurrency: 100,
    supportsStreaming: true,
    supportsInterrupt: true,
    supportsBargein: true,
    costPerMinute: 0.0043,
  };
  
  async *stream(input: AsyncIterable<AudioFrame>): AsyncIterable<Transcript> {
    const ws = new WebSocket('wss://api.deepgram.com/v1/listen', {
      headers: { Authorization: `Token ${this.apiKey}` },
    });
    
    // Bidirectional streaming implementation...
  }
}
```

#### 6.3.3 LLM Providers

```typescript
// llama.cpp - Primary for CPU
class LlamaCppProvider implements StreamingProvider<LLMInput, Token> {
  readonly id = 'llama-cpp';
  readonly type = 'llm';
  readonly capabilities = {
    languages: ['*'],
    estimatedLatencyMs: 150,  // Time to first token
    maxConcurrency: 4,
    supportsStreaming: true,
    supportsInterrupt: true,
    supportsBargein: false,
  };
  
  async *stream(input: AsyncIterable<LLMInput>): AsyncIterable<Token> {
    for await (const request of input) {
      const response = await fetch(`${this.endpoint}/completion`, {
        method: 'POST',
        body: JSON.stringify({
          prompt: this.formatPrompt(request),
          stream: true,
          n_predict: 256,
          temperature: 0.7,
        }),
      });
      
      const reader = response.body!.getReader();
      const decoder = new TextDecoder();
      
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        
        const chunk = decoder.decode(value);
        const data = JSON.parse(chunk.slice(6));  // Remove "data: "
        
        yield {
          text: data.content,
          isLast: data.stop,
        };
      }
    }
  }
}

// Anthropic Claude - Cloud for complex reasoning
class AnthropicProvider implements StreamingProvider<LLMInput, Token> {
  readonly id = 'anthropic-claude';
  readonly type = 'llm';
  readonly capabilities = {
    languages: ['*'],
    estimatedLatencyMs: 200,
    maxConcurrency: 50,
    supportsStreaming: true,
    supportsInterrupt: true,
    supportsBargein: false,
    costPerToken: 0.000003,  // Claude 3 Haiku input
  };
  
  // Implementation using Anthropic SDK with streaming...
}
```

#### 6.3.4 TTS Providers

```typescript
// Kokoro-82M - Primary for CPU (lightweight)
class KokoroProvider implements StreamingProvider<string, AudioChunk> {
  readonly id = 'kokoro-82m';
  readonly type = 'tts';
  readonly capabilities = {
    languages: ['en', 'es', 'fr', 'de', 'pt', 'ja', 'ko', 'zh'],
    estimatedLatencyMs: 50,
    maxConcurrency: 20,
    supportsStreaming: true,
    supportsInterrupt: true,
    supportsBargein: true,
  };
  
  async *stream(input: AsyncIterable<string>): AsyncIterable<AudioChunk> {
    for await (const text of input) {
      // Sentence-level streaming
      const sentences = this.splitSentences(text);
      
      for (const sentence of sentences) {
        const audio = await this.synthesize(sentence);
        
        // Chunk the audio for streaming
        for (let i = 0; i < audio.length; i += this.chunkSize) {
          yield {
            samples: audio.slice(i, i + this.chunkSize),
            sampleRate: 24000,
            isFinal: i + this.chunkSize >= audio.length,
          };
        }
      }
    }
  }
}

// CosyVoice2 - Best quality streaming
class CosyVoice2Provider implements StreamingProvider<string, AudioChunk> {
  readonly id = 'cosyvoice2';
  readonly type = 'tts';
  readonly capabilities = {
    languages: ['en', 'zh', 'ja', 'ko'],
    estimatedLatencyMs: 150,
    maxConcurrency: 5,
    supportsStreaming: true,
    supportsInterrupt: true,
    supportsBargein: true,
  };
  
  // Native streaming implementation with 150ms TTFB...
}
```

### 6.4 Provider Registry

```typescript
class ProviderRegistry {
  private providers: Map<string, StreamingProvider<any, any>> = new Map();
  private healthMonitor: HealthMonitor;
  
  register(provider: StreamingProvider<any, any>): void {
    this.providers.set(provider.id, provider);
    this.healthMonitor.startMonitoring(provider);
  }
  
  getByType(type: ProviderType): StreamingProvider<any, any>[] {
    return Array.from(this.providers.values())
      .filter(p => p.type === type);
  }
  
  getHealthy(type: ProviderType): StreamingProvider<any, any>[] {
    return this.getByType(type)
      .filter(p => this.healthMonitor.isHealthy(p.id));
  }
}
```

### 6.5 Routing Strategy

```typescript
interface RoutingConfig {
  mode: 'pipeline' | 'omni';
  strategy: 'latency' | 'cost' | 'quality' | 'hybrid';
  
  providers: {
    vad: ProviderPriority[];
    asr: ProviderPriority[];
    llm: ProviderPriority[];
    tts: ProviderPriority[];
    omni?: ProviderPriority[];
  };
  
  failover: FailoverConfig;
  
  // Strategy-specific weights
  weights?: {
    latency: number;   // 0-1
    cost: number;      // 0-1
    quality: number;   // 0-1
  };
}

interface ProviderPriority {
  providerId: string;
  priority: number;              // Lower = higher priority
  conditions?: RoutingCondition[];
}

interface RoutingCondition {
  type: 'language' | 'time' | 'load' | 'cost_budget';
  operator: 'eq' | 'ne' | 'gt' | 'lt' | 'in';
  value: any;
}

// Example configuration
const routingConfig: RoutingConfig = {
  mode: 'pipeline',
  strategy: 'hybrid',
  weights: { latency: 0.5, cost: 0.3, quality: 0.2 },
  
  providers: {
    vad: [
      { providerId: 'ten-vad', priority: 1 },
      { providerId: 'silero-vad', priority: 2 },
    ],
    asr: [
      { providerId: 'simul-streaming', priority: 1 },
      { providerId: 'deepgram-nova3', priority: 2, 
        conditions: [{ type: 'load', operator: 'gt', value: 0.8 }] },
    ],
    llm: [
      { providerId: 'llama-cpp', priority: 1 },
      { providerId: 'anthropic-claude', priority: 2,
        conditions: [{ type: 'language', operator: 'in', value: ['ja', 'zh'] }] },
    ],
    tts: [
      { providerId: 'kokoro-82m', priority: 1 },
      { providerId: 'cosyvoice2', priority: 2 },
    ],
  },
  
  failover: {
    maxRetries: 3,
    timeoutMs: 5000,
    circuitBreakerThreshold: 0.5,
    circuitBreakerWindowMs: 10000,
    cooldownMs: 30000,
  },
};
```

### 6.6 Failover Mechanism

```typescript
class CircuitBreaker {
  private state: 'CLOSED' | 'OPEN' | 'HALF_OPEN' = 'CLOSED';
  private failures: number = 0;
  private lastFailure: number = 0;
  private successCount: number = 0;
  
  constructor(private config: FailoverConfig) {}
  
  async execute<T>(fn: () => Promise<T>): Promise<T> {
    if (this.state === 'OPEN') {
      if (Date.now() - this.lastFailure > this.config.cooldownMs) {
        this.state = 'HALF_OPEN';
        this.successCount = 0;
      } else {
        throw new CircuitOpenError();
      }
    }
    
    try {
      const result = await Promise.race([
        fn(),
        this.timeout(this.config.timeoutMs),
      ]);
      
      this.onSuccess();
      return result;
    } catch (error) {
      this.onFailure();
      throw error;
    }
  }
  
  private onSuccess(): void {
    this.failures = 0;
    
    if (this.state === 'HALF_OPEN') {
      this.successCount++;
      if (this.successCount >= 3) {
        this.state = 'CLOSED';
      }
    }
  }
  
  private onFailure(): void {
    this.failures++;
    this.lastFailure = Date.now();
    
    if (this.failures >= this.config.maxRetries) {
      this.state = 'OPEN';
    }
  }
}

class FailoverManager {
  private circuitBreakers: Map<string, CircuitBreaker> = new Map();
  
  async executeWithFailover<T>(
    providers: ProviderPriority[],
    fn: (provider: StreamingProvider<any, any>) => Promise<T>
  ): Promise<T> {
    const sorted = [...providers].sort((a, b) => a.priority - b.priority);
    
    for (const { providerId } of sorted) {
      const provider = this.registry.get(providerId);
      const breaker = this.getBreaker(providerId);
      
      try {
        return await breaker.execute(() => fn(provider));
      } catch (error) {
        if (error instanceof CircuitOpenError) {
          continue;  // Try next provider
        }
        // Log error and try next
        console.error(`Provider ${providerId} failed:`, error);
      }
    }
    
    throw new AllProvidersFailedError();
  }
}
```

---

## 7. WebSocket API Specification

### 7.1 Connection

```
wss://api.example.com/v1/realtime
```

**Authentication:** Bearer token in `Authorization` header during WebSocket upgrade.

**Query Parameters:**
| Parameter | Required | Description |
|-----------|----------|-------------|
| `session_id` | No | Resume existing session |
| `protocol_version` | No | API version (default: "1.0") |

### 7.2 Message Format

All messages are JSON with required `type` field:

```typescript
interface BaseMessage {
  type: string;
  id?: string;              // Client-generated for request/response correlation
  timestamp?: string;       // ISO 8601
}
```

### 7.3 Client → Server Events

#### session.create

Create a new voice session.

```json
{
  "type": "session.create",
  "id": "msg_001",
  "config": {
    "mode": "pipeline",
    "language": "pt-BR",
    "voice": "nova",
    "system_prompt": "Você é um assistente prestativo.",
    "providers": {
      "asr": "simul-streaming",
      "llm": "llama-cpp",
      "tts": "kokoro-82m"
    },
    "rtp": {
      "mode": "direct",
      "codec": "PCMU"
    }
  }
}
```

#### audio.input

Send audio data (when not using RTP).

```json
{
  "type": "audio.input",
  "session_id": "sess_abc123",
  "format": "pcm16",
  "sample_rate": 16000,
  "data": "base64_encoded_audio..."
}
```

#### session.interrupt

Interrupt current TTS output (barge-in).

```json
{
  "type": "session.interrupt",
  "session_id": "sess_abc123"
}
```

#### session.update

Update session configuration.

```json
{
  "type": "session.update",
  "session_id": "sess_abc123",
  "config": {
    "voice": "alloy",
    "system_prompt": "New system prompt"
  }
}
```

#### session.close

End the session.

```json
{
  "type": "session.close",
  "session_id": "sess_abc123",
  "reason": "user_hangup"
}
```

### 7.4 Server → Client Events

#### session.created

Session successfully created.

```json
{
  "type": "session.created",
  "session_id": "sess_abc123",
  "rtp": {
    "host": "192.168.1.100",
    "port": 10042,
    "ssrc": 12345678
  }
}
```

#### speech.started

User started speaking.

```json
{
  "type": "speech.started",
  "session_id": "sess_abc123",
  "timestamp": "2026-01-22T10:30:00.000Z"
}
```

#### speech.ended

User stopped speaking.

```json
{
  "type": "speech.ended",
  "session_id": "sess_abc123",
  "timestamp": "2026-01-22T10:30:02.500Z",
  "duration_ms": 2500
}
```

#### transcript.partial

Partial transcription (streaming ASR).

```json
{
  "type": "transcript.partial",
  "session_id": "sess_abc123",
  "text": "Olá, como você",
  "confidence": 0.87
}
```

#### transcript.final

Final transcription.

```json
{
  "type": "transcript.final",
  "session_id": "sess_abc123",
  "text": "Olá, como você está?",
  "confidence": 0.94,
  "words": [
    {"word": "Olá", "start": 0.0, "end": 0.3, "confidence": 0.98},
    {"word": "como", "start": 0.4, "end": 0.6, "confidence": 0.95}
  ]
}
```

#### response.text.delta

Streaming LLM response.

```json
{
  "type": "response.text.delta",
  "session_id": "sess_abc123",
  "delta": "Estou ",
  "accumulated": "Olá! Estou "
}
```

#### response.text.done

LLM response complete.

```json
{
  "type": "response.text.done",
  "session_id": "sess_abc123",
  "text": "Olá! Estou bem, obrigado por perguntar. Como posso ajudá-lo hoje?"
}
```

#### response.audio.delta

Streaming TTS audio.

```json
{
  "type": "response.audio.delta",
  "session_id": "sess_abc123",
  "format": "pcm16",
  "sample_rate": 24000,
  "data": "base64_encoded_audio_chunk..."
}
```

#### response.audio.done

TTS audio complete.

```json
{
  "type": "response.audio.done",
  "session_id": "sess_abc123",
  "duration_ms": 3200
}
```

#### error

Error occurred.

```json
{
  "type": "error",
  "session_id": "sess_abc123",
  "code": "PROVIDER_UNAVAILABLE",
  "message": "ASR provider timed out",
  "recoverable": true
}
```

### 7.5 Error Codes

| Code | Description | Recoverable |
|------|-------------|-------------|
| `SESSION_NOT_FOUND` | Invalid session ID | No |
| `SESSION_EXPIRED` | Session timed out | No |
| `PROVIDER_UNAVAILABLE` | Provider failed, trying failover | Yes |
| `ALL_PROVIDERS_FAILED` | All providers exhausted | No |
| `RATE_LIMITED` | Too many requests | Yes |
| `INVALID_CONFIG` | Invalid configuration | No |
| `AUDIO_FORMAT_ERROR` | Unsupported audio format | No |

---

## 8. Session Management

### 8.1 Session Lifecycle

```
                    ┌─────────────────────────────────────┐
                    │                                     │
                    ▼                                     │
┌──────┐       ┌─────────┐       ┌────────────┐       ┌──────────┐
│ INIT │──────▶│LISTENING│──────▶│ PROCESSING │──────▶│ SPEAKING │
└──────┘       └─────────┘       └────────────┘       └──────────┘
    │               │                  │                   │
    │               │                  │                   │
    │               ▼                  │                   │
    │          ┌─────────────┐        │                   │
    │          │ INTERRUPTED │◀───────┼───────────────────┘
    │          └─────────────┘        │
    │               │                  │
    │               ▼                  │
    │          ┌────────┐             │
    └─────────▶│ CLOSED │◀────────────┘
               └────────┘
```

### 8.2 State Transitions

| From | To | Trigger | Action |
|------|-----|---------|--------|
| INIT | LISTENING | session.create | Start VAD, open RTP |
| LISTENING | PROCESSING | speech.started | Buffer audio, start ASR |
| PROCESSING | SPEAKING | transcript.final | Send to LLM, start TTS |
| SPEAKING | LISTENING | response.audio.done | Resume VAD |
| SPEAKING | INTERRUPTED | speech.started (barge-in) | Stop TTS, start ASR |
| INTERRUPTED | PROCESSING | - | Process interrupt speech |
| * | CLOSED | session.close / timeout | Cleanup resources |

### 8.3 Context Management

```typescript
class ConversationContext {
  private messages: Message[] = [];
  private tokenCount: number = 0;
  
  constructor(
    private maxTokens: number = 4096,
    private systemPrompt: string
  ) {
    this.addMessage({
      role: 'system',
      content: systemPrompt,
    });
  }
  
  addMessage(message: Message): void {
    this.messages.push(message);
    this.tokenCount += this.countTokens(message.content);
    
    // Trim old messages if over budget
    while (this.tokenCount > this.maxTokens && this.messages.length > 2) {
      const removed = this.messages.splice(1, 1)[0];  // Keep system prompt
      this.tokenCount -= this.countTokens(removed.content);
    }
  }
  
  getPrompt(): string {
    return this.messages
      .map(m => `${m.role}: ${m.content}`)
      .join('\n\n');
  }
  
  getMessagesForAPI(): Message[] {
    return [...this.messages];
  }
}
```

### 8.4 Timeout Configuration

```yaml
session:
  # Maximum idle time before closing
  idle_timeout_ms: 30000
  
  # Maximum total session duration
  max_duration_ms: 3600000  # 1 hour
  
  # Time to wait for speech after prompt
  speech_timeout_ms: 10000
  
  # Time to wait for provider response
  inference_timeout_ms: 5000
  
  # Keepalive interval
  keepalive_interval_ms: 15000
```

---

## 9. Latency Budget

### 9.1 Target Breakdown

Total budget: **< 300ms** voice-to-voice (P95)

| Component | Budget | Notes |
|-----------|--------|-------|
| Jitter Buffer | 40ms | Adaptive, network dependent |
| VAD Detection | 20ms | 2 frames for confirmation |
| ASR (streaming) | 100ms | Partial results |
| LLM (TTFT) | 100ms | Time to first token |
| TTS (TTFB) | 40ms | Time to first audio |
| **Total** | **300ms** | End-to-end |

### 9.2 Optimization Techniques

#### Speculative Execution

Start TTS before LLM completes using sentence boundaries:

```typescript
async function* speculativeTTS(
  llmStream: AsyncIterable<Token>,
  ttsProvider: TTSProvider
): AsyncIterable<AudioChunk> {
  let buffer = '';
  const sentenceEnders = /[.!?。！？]/;
  
  for await (const token of llmStream) {
    buffer += token.text;
    
    // Check for sentence boundary
    const match = buffer.match(sentenceEnders);
    if (match) {
      const sentence = buffer.slice(0, match.index! + 1);
      buffer = buffer.slice(match.index! + 1);
      
      // Start TTS immediately for completed sentence
      yield* ttsProvider.stream(asAsyncIterable(sentence));
    }
  }
  
  // Process remaining text
  if (buffer.trim()) {
    yield* ttsProvider.stream(asAsyncIterable(buffer));
  }
}
```

#### Prefetch and Caching

```typescript
// Cache common responses
const responseCache = new LRUCache<string, AudioBuffer>({
  max: 1000,
  ttl: 3600000,  // 1 hour
});

// Prefetch greetings
const commonGreetings = [
  "Olá! Como posso ajudá-lo?",
  "Bom dia! Em que posso ser útil?",
  "Oi! O que você precisa?",
];

async function prefetchGreetings(tts: TTSProvider): Promise<void> {
  for (const greeting of commonGreetings) {
    const audio = await tts.synthesize(greeting);
    responseCache.set(greeting, audio);
  }
}
```

### 9.3 Monitoring

```typescript
interface LatencyMetrics {
  // Per-component latencies
  vadLatency: Histogram;
  asrLatency: Histogram;
  llmTTFT: Histogram;
  ttsTTFB: Histogram;
  
  // End-to-end
  voiceToVoice: Histogram;
  
  // Derived
  p50(): number;
  p95(): number;
  p99(): number;
}

// Prometheus metrics
const voiceToVoiceLatency = new Histogram({
  name: 'voice_to_voice_latency_ms',
  help: 'End-to-end voice-to-voice latency',
  buckets: [100, 150, 200, 250, 300, 400, 500, 750, 1000],
  labelNames: ['provider_config'],
});
```

---

## 10. Non-Functional Requirements

### 10.1 Performance

| Requirement | Target | Validation |
|-------------|--------|------------|
| Concurrent sessions | 100+ per node | Load test |
| CPU usage per session | < 10% (1 core) | Profiling |
| Memory per session | < 100MB | Memory profiling |
| Startup time | < 5s | Cold start test |
| Graceful shutdown | < 10s | Signal handling test |

### 10.2 Reliability

| Requirement | Target | Validation |
|-------------|--------|------------|
| Availability | 99.9% | Uptime monitoring |
| MTTR | < 5 min | Incident response |
| Data durability | N/A (stateless) | Architecture |
| Failover time | < 50ms | Failure injection |

### 10.3 Security

| Requirement | Implementation |
|-------------|----------------|
| Transport encryption | TLS 1.3 (WebSocket), SRTP (RTP) |
| Authentication | JWT with short expiry (1h) |
| Authorization | Session-scoped tokens |
| Audit logging | All API calls logged |
| Data retention | Audio not stored by default |

### 10.4 Observability

```yaml
metrics:
  # Prometheus endpoint
  endpoint: /metrics
  
  # Key metrics
  - voice_to_voice_latency_ms
  - session_count
  - provider_health
  - error_rate
  
logging:
  # Structured JSON logs
  format: json
  level: info
  
  # Log sampling for high-volume events
  sampling:
    audio_frame: 0.01  # 1% of frames
    transcript_partial: 0.1  # 10% of partials
    
tracing:
  # OpenTelemetry
  exporter: otlp
  endpoint: ${OTEL_ENDPOINT}
  sampling_rate: 0.1
```

---

## 11. Deployment Architecture

### 11.1 Single Node (Development)

```yaml
# docker-compose.yml
version: '3.8'
services:
  inference-server:
    image: voice-platform:latest
    ports:
      - "8080:8080"      # WebSocket API
      - "10000-10100:10000-10100/udp"  # RTP
    environment:
      - MODE=pipeline
      - LOG_LEVEL=debug
    volumes:
      - ./models:/models
    deploy:
      resources:
        limits:
          cpus: '4'
          memory: 8G
```

### 11.2 Production (Kubernetes)

```yaml
# deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: voice-inference
spec:
  replicas: 3
  selector:
    matchLabels:
      app: voice-inference
  template:
    spec:
      containers:
      - name: inference
        image: voice-platform:latest
        ports:
        - containerPort: 8080
        resources:
          requests:
            cpu: "2"
            memory: "4Gi"
          limits:
            cpu: "4"
            memory: "8Gi"
        livenessProbe:
          httpGet:
            path: /health
            port: 8080
          initialDelaySeconds: 10
        readinessProbe:
          httpGet:
            path: /ready
            port: 8080
          initialDelaySeconds: 5
---
apiVersion: v1
kind: Service
metadata:
  name: voice-inference
spec:
  type: LoadBalancer
  ports:
  - port: 8080
    name: websocket
  - port: 10000
    protocol: UDP
    name: rtp-start
  selector:
    app: voice-inference
```

### 11.3 Scaling Strategy

```
┌──────────────────────────────────────────────────────────────────┐
│                        Load Balancer                              │
│                   (WebSocket sticky sessions)                     │
└──────────────────────────────────────────────────────────────────┘
                              │
         ┌────────────────────┼────────────────────┐
         │                    │                    │
         ▼                    ▼                    ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│ Inference Node 1│  │ Inference Node 2│  │ Inference Node 3│
│   100 sessions  │  │   100 sessions  │  │   100 sessions  │
└─────────────────┘  └─────────────────┘  └─────────────────┘
         │                    │                    │
         └────────────────────┼────────────────────┘
                              │
                              ▼
                    ┌─────────────────┐
                    │  RTP Proxy Pool │
                    │   (rtpengine)   │
                    └─────────────────┘
```

---

## 12. ADR References

The following Architecture Decision Records provide detailed rationale and evidence for key technical decisions:

| ADR | Title | Status |
|-----|-------|--------|
| [ADR-001](./ADR-001-VAD-Selection.md) | Voice Activity Detection Provider Selection | Accepted |
| [ADR-002](./ADR-002-ASR-Selection.md) | Automatic Speech Recognition Provider Selection | Accepted |
| [ADR-003](./ADR-003-LLM-Selection.md) | Large Language Model Provider Selection | Accepted |
| [ADR-004](./ADR-004-TTS-Selection.md) | Text-to-Speech Provider Selection | Accepted |
| [ADR-005](./ADR-005-Omni-Mode.md) | Omni Mode Architecture Decision | Proposed |
| [ADR-006](./ADR-006-RTP-Integration.md) | RTP Integration Strategy | Accepted |

---

## Appendix A: Glossary

| Term | Definition |
|------|------------|
| **AEC** | Acoustic Echo Cancellation |
| **ASR** | Automatic Speech Recognition |
| **DTMF** | Dual-Tone Multi-Frequency |
| **LLM** | Large Language Model |
| **RTP** | Real-time Transport Protocol |
| **SRTP** | Secure RTP |
| **TTFB** | Time To First Byte |
| **TTFT** | Time To First Token |
| **TTS** | Text-to-Speech |
| **VAD** | Voice Activity Detection |
| **WER** | Word Error Rate |

---

## Appendix B: References

1. RFC 3550 - RTP: A Transport Protocol for Real-Time Applications
2. RFC 3711 - The Secure Real-time Transport Protocol (SRTP)
3. RFC 2833 - RTP Payload for DTMF Digits, Telephony Tones and Signals
4. OpenAI Realtime API Documentation
5. WebRTC Audio Processing Module Documentation
6. NVIDIA NeMo ASR Documentation
7. Qwen2.5-Omni Technical Report (arXiv:2503.20215)
8. Qwen3-Omni Technical Report (arXiv:2509.17765)
