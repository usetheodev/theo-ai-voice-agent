# Product Requirements Document
# Realtime Voice-to-Voice Platform with Ollama

**Version:** 2.0  
**Date:** January 2026  
**Status:** Implementation Ready  
**Target:** CPU-only, Single Node, 3-4 Concurrent Sessions

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [System Overview](#2-system-overview)
3. [Architecture](#3-architecture)
4. [Component Specifications](#4-component-specifications)
5. [Ollama Integration](#5-ollama-integration)
6. [RTP Integration](#6-rtp-integration)
7. [WebSocket Realtime API](#7-websocket-realtime-api)
8. [Data Flow & Timing](#8-data-flow--timing)
9. [Configuration](#9-configuration)
10. [Deployment](#10-deployment)
11. [Monitoring & Observability](#11-monitoring--observability)
12. [Implementation Roadmap](#12-implementation-roadmap)

---

## 1. Executive Summary

### 1.1 Objective

Build a production-ready, self-hosted realtime voice-to-voice inference platform optimized for:

- **3-4 concurrent voice sessions**
- **CPU-only infrastructure** (no GPU required)
- **Single node deployment**
- **Sub-300ms voice-to-voice latency**

### 1.2 Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| LLM Engine | **Ollama** | Simpler than vLLM/llama.cpp for low concurrency, OpenAI-compatible API |
| LLM Model | **Qwen2.5-7B-Instruct** | Best quality/performance ratio for CPU |
| Quantization | **Q4_K_M** | ~5GB RAM, maintains quality |
| ASR | **faster-whisper** | CPU-optimized, streaming support |
| VAD | **Silero VAD** | Proven, low latency, CPU efficient |
| TTS | **Piper TTS** | Fast CPU inference, good quality |

### 1.3 Success Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| Voice-to-Voice Latency (P95) | < 300ms | End-to-end timestamp analysis |
| LLM Time-to-First-Token | < 200ms | Ollama metrics |
| ASR Latency | < 150ms | faster-whisper streaming |
| TTS Time-to-First-Byte | < 100ms | Piper output timing |
| Concurrent Sessions | 4 | Load testing |
| CPU Utilization | < 80% | System monitoring |

---

## 2. System Overview

### 2.1 High-Level Architecture

```
                                    ┌─────────────────────────────────────┐
                                    │         Single Node Server          │
                                    │                                     │
 ┌──────────┐     RTP/UDP          │  ┌─────────────────────────────┐   │
 │   PBX    │◄────────────────────►│  │    Voice Pipeline Service   │   │
 │  / SIP   │                      │  │                             │   │
 └──────────┘                      │  │  ┌─────┐ ┌─────┐ ┌───────┐ │   │
                                    │  │  │ VAD │→│ ASR │→│Ollama │ │   │
      │                            │  │  └─────┘ └─────┘ └───────┘ │   │
      │ SIP Signaling              │  │      │               │      │   │
      ▼                            │  │      ▼               ▼      │   │
 ┌──────────┐     WebSocket        │  │  ┌─────────────────────┐   │   │
 │  Client  │◄────────────────────►│  │  │        TTS          │   │   │
 │   App    │                      │  │  └─────────────────────┘   │   │
 └──────────┘                      │  └─────────────────────────────┘   │
                                    │                                     │
                                    │  ┌─────────────────────────────┐   │
                                    │  │      Ollama Server          │   │
                                    │  │   (Qwen2.5-7B-Instruct)     │   │
                                    │  │      Port 11434             │   │
                                    │  └─────────────────────────────┘   │
                                    └─────────────────────────────────────┘
```

### 2.2 Design Principles

```
1. STREAMING EVERYWHERE
   - Never wait for complete input
   - Never generate complete output
   - Stream audio, text, and tokens

2. MINIMAL LATENCY
   - Each component optimized for TTFB
   - Speculative execution where possible
   - No unnecessary buffering

3. GRACEFUL DEGRADATION
   - Handle slow inference gracefully
   - Backpressure control
   - Session prioritization under load

4. OPERATIONAL SIMPLICITY
   - Single node deployment
   - Minimal dependencies
   - Easy to debug and monitor
```

---

## 3. Architecture

### 3.1 Component Diagram

```
┌────────────────────────────────────────────────────────────────────────────┐
│                              VOICE PLATFORM                                 │
├────────────────────────────────────────────────────────────────────────────┤
│                                                                            │
│  ┌──────────────────────────────────────────────────────────────────────┐ │
│  │                     TRANSPORT LAYER (Layer 1)                         │ │
│  │  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────┐     │ │
│  │  │    RTP     │  │   Jitter   │  │   Codec    │  │    AEC     │     │ │
│  │  │  Receiver  │─▶│   Buffer   │─▶│  Decoder   │─▶│   Filter   │     │ │
│  │  │  (UDP)     │  │  (40ms)    │  │  (G.711)   │  │            │     │ │
│  │  └────────────┘  └────────────┘  └────────────┘  └────────────┘     │ │
│  └──────────────────────────────────────────────────────────────────────┘ │
│                                      │                                     │
│                                      ▼                                     │
│  ┌──────────────────────────────────────────────────────────────────────┐ │
│  │                     SESSION LAYER (Layer 2)                           │ │
│  │  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────┐     │ │
│  │  │  Session   │  │ Backpres-  │  │  Context   │  │  Interrupt │     │ │
│  │  │  Manager   │  │   sure     │  │  Manager   │  │  Handler   │     │ │
│  │  └────────────┘  └────────────┘  └────────────┘  └────────────┘     │ │
│  └──────────────────────────────────────────────────────────────────────┘ │
│                                      │                                     │
│                                      ▼                                     │
│  ┌──────────────────────────────────────────────────────────────────────┐ │
│  │                    INFERENCE LAYER (Layer 3)                          │ │
│  │                                                                        │ │
│  │   ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐      │ │
│  │   │  Silero  │    │ faster-  │    │  Ollama  │    │  Piper   │      │ │
│  │   │   VAD    │───▶│ whisper  │───▶│  Client  │───▶│   TTS    │      │ │
│  │   │  (10ms)  │    │ (150ms)  │    │ (200ms)  │    │  (80ms)  │      │ │
│  │   └──────────┘    └──────────┘    └──────────┘    └──────────┘      │ │
│  │                                         │                             │ │
│  └─────────────────────────────────────────┼────────────────────────────┘ │
│                                            │                               │
│  ┌─────────────────────────────────────────┼────────────────────────────┐ │
│  │                    OLLAMA SERVER        │                             │ │
│  │                                         ▼                             │ │
│  │   ┌─────────────────────────────────────────────────────────────┐   │ │
│  │   │              Qwen2.5-7B-Instruct (Q4_K_M)                    │   │ │
│  │   │                                                              │   │ │
│  │   │   • OLLAMA_NUM_PARALLEL=4                                   │   │ │
│  │   │   • Context: 4096 tokens                                    │   │ │
│  │   │   • RAM: ~8GB                                               │   │ │
│  │   └─────────────────────────────────────────────────────────────┘   │ │
│  └──────────────────────────────────────────────────────────────────────┘ │
│                                                                            │
└────────────────────────────────────────────────────────────────────────────┘
```

### 3.2 Technology Stack

| Layer | Component | Technology | Version |
|-------|-----------|------------|---------|
| Runtime | Language | Node.js / TypeScript | 20 LTS |
| Transport | RTP | mediasoup / node-webrtc | Latest |
| Transport | WebSocket | ws / uWebSockets.js | Latest |
| Inference | VAD | Silero VAD (ONNX) | 5.x |
| Inference | ASR | faster-whisper | 1.x |
| Inference | LLM | Ollama | 0.5.x |
| Inference | TTS | Piper TTS | 2.x |
| Container | Runtime | Docker | 24.x |
| Monitoring | Metrics | Prometheus | 2.x |
| Monitoring | Logs | Loki / stdout | - |

---

## 4. Component Specifications

### 4.1 VAD (Voice Activity Detection)

**Selection:** Silero VAD v5

**Rationale:**
- Battle-tested in production
- ONNX runtime (cross-platform)
- ~10ms latency per frame
- Low CPU usage

**Configuration:**

```typescript
interface VADConfig {
  // Model
  modelPath: string;              // './models/silero_vad.onnx'
  
  // Detection thresholds
  threshold: number;              // 0.5 (speech probability)
  minSpeechDurationMs: number;    // 250ms
  minSilenceDurationMs: number;   // 300ms
  
  // Audio
  sampleRate: 16000;              // Required by Silero
  frameSize: 512;                 // 32ms frames
  
  // Padding
  speechPadMs: number;            // 30ms before speech
  silencePadMs: number;           // 100ms after speech
}
```

**Interface:**

```typescript
interface VADProcessor {
  // Process audio frame, return speech probability
  process(samples: Float32Array): number;
  
  // Get speech state
  isSpeaking(): boolean;
  
  // Reset state
  reset(): void;
}

// Events emitted
type VADEvent = 
  | { type: 'speech_start'; timestamp: number }
  | { type: 'speech_end'; timestamp: number; duration: number };
```

### 4.2 ASR (Automatic Speech Recognition)

**Selection:** faster-whisper (large-v3, int8 quantization)

**Rationale:**
- CTranslate2 backend (CPU optimized)
- 4x faster than original Whisper
- Streaming partial results
- int8 quantization reduces memory

**Configuration:**

```typescript
interface ASRConfig {
  // Model
  modelSize: 'large-v3';
  computeType: 'int8';            // CPU optimized
  device: 'cpu';
  
  // Language
  language: 'pt' | 'en' | 'es' | 'auto';
  task: 'transcribe';
  
  // Streaming
  beamSize: 5;
  patience: 1.0;
  
  // VAD filter (built-in)
  vadFilter: true;
  vadParameters: {
    threshold: 0.5;
    minSpeechDurationMs: 250;
    minSilenceDurationMs: 300;
  };
}
```

**Interface:**

```typescript
interface ASRProcessor {
  // Transcribe audio buffer
  transcribe(
    audio: Float32Array,
    config?: Partial<ASRConfig>
  ): AsyncIterable<TranscriptSegment>;
}

interface TranscriptSegment {
  text: string;
  start: number;
  end: number;
  confidence: number;
  isPartial: boolean;
}
```

### 4.3 LLM (Large Language Model)

**Selection:** Qwen2.5-7B-Instruct via Ollama

**Rationale:**
- Ollama simplifies deployment (single binary)
- OpenAI-compatible API
- Good multilingual (Portuguese, English, Spanish)
- 7B is sweet spot for CPU quality/speed

**Model Specifications:**

| Spec | Value |
|------|-------|
| Parameters | 7B |
| Quantization | Q4_K_M |
| Context Window | 4096 tokens |
| RAM Usage | ~5-6GB |
| Disk Size | ~4.4GB |

### 4.4 TTS (Text-to-Speech)

**Selection:** Piper TTS

**Rationale:**
- VITS-based (fast synthesis)
- ONNX runtime
- ~80ms TTFB
- Multiple voices/languages

**Configuration:**

```typescript
interface TTSConfig {
  // Model
  modelPath: string;              // './models/pt_BR-faber-medium.onnx'
  configPath: string;             // './models/pt_BR-faber-medium.onnx.json'
  
  // Audio output
  sampleRate: 22050;              // Piper default
  
  // Synthesis
  speakerId?: number;             // For multi-speaker models
  lengthScale: number;            // 1.0 (speed)
  noiseScale: number;             // 0.667
  noiseW: number;                 // 0.8
  
  // Streaming
  sentenceChunking: true;         // Split by sentences
}
```

**Available Voices:**

| Language | Voice | Quality | Notes |
|----------|-------|---------|-------|
| pt_BR | faber | medium | Male, clear |
| pt_BR | edresson | medium | Male, natural |
| en_US | amy | medium | Female, clear |
| en_US | ryan | medium | Male, natural |
| es_ES | carlfm | medium | Male |

---

## 5. Ollama Integration

### 5.1 Installation & Setup

```bash
# Install Ollama
curl -fsSL https://ollama.com/install.sh | sh

# Pull model
ollama pull qwen2.5:7b-instruct-q4_K_M

# Verify
ollama list
```

### 5.2 Server Configuration

**Environment Variables:**

```bash
# /etc/systemd/system/ollama.service.d/override.conf
[Service]
Environment="OLLAMA_HOST=0.0.0.0:11434"
Environment="OLLAMA_NUM_PARALLEL=4"
Environment="OLLAMA_MAX_LOADED_MODELS=1"
Environment="OLLAMA_KEEP_ALIVE=24h"
Environment="OLLAMA_NUM_GPU=0"
```

| Variable | Value | Purpose |
|----------|-------|---------|
| `OLLAMA_HOST` | `0.0.0.0:11434` | Listen on all interfaces |
| `OLLAMA_NUM_PARALLEL` | `4` | 4 concurrent requests |
| `OLLAMA_MAX_LOADED_MODELS` | `1` | Only Qwen loaded |
| `OLLAMA_KEEP_ALIVE` | `24h` | Keep model in memory |
| `OLLAMA_NUM_GPU` | `0` | Force CPU-only |

### 5.3 Modelfile (Custom Configuration)

```dockerfile
# Modelfile.voice-assistant
FROM qwen2.5:7b-instruct-q4_K_M

# Optimize for voice responses
PARAMETER temperature 0.7
PARAMETER top_p 0.9
PARAMETER top_k 40
PARAMETER repeat_penalty 1.1
PARAMETER num_ctx 4096
PARAMETER num_predict 150
PARAMETER stop "<|im_end|>"
PARAMETER stop "\n\nUser:"
PARAMETER stop "\n\nHuman:"

# System prompt for voice
SYSTEM """You are a helpful voice assistant. Follow these rules strictly:

1. Keep responses to 1-3 sentences maximum
2. Speak naturally and conversationally
3. Never use lists, bullets, numbers, or formatting
4. Never use emojis, asterisks, or special characters
5. If you need to list things, use natural language like "first... then... and finally..."
6. Ask clarifying questions if the request is ambiguous
7. Match the user's language (Portuguese, English, or Spanish)
8. Be concise - you are speaking, not writing

You are currently in a real-time voice call."""
```

```bash
# Create custom model
ollama create voice-assistant -f Modelfile.voice-assistant

# Use the custom model
ollama run voice-assistant
```

### 5.4 API Client Implementation

```typescript
import Ollama from 'ollama';

interface OllamaConfig {
  host: string;                   // 'http://localhost:11434'
  model: string;                  // 'voice-assistant'
  options: {
    temperature: number;          // 0.7
    top_p: number;                // 0.9
    num_predict: number;          // 150 (max tokens)
    num_ctx: number;              // 4096
  };
}

class OllamaClient {
  private client: Ollama;
  private config: OllamaConfig;
  
  constructor(config: OllamaConfig) {
    this.client = new Ollama({ host: config.host });
    this.config = config;
  }
  
  /**
   * Stream chat completion for voice response
   */
  async *chat(
    messages: Message[],
    options?: Partial<OllamaConfig['options']>
  ): AsyncIterable<string> {
    const response = await this.client.chat({
      model: this.config.model,
      messages: messages.map(m => ({
        role: m.role,
        content: m.content,
      })),
      stream: true,
      options: {
        ...this.config.options,
        ...options,
      },
    });
    
    for await (const chunk of response) {
      if (chunk.message?.content) {
        yield chunk.message.content;
      }
    }
  }
  
  /**
   * Stream with sentence detection for TTS
   */
  async *chatWithSentences(
    messages: Message[]
  ): AsyncIterable<{ sentence: string; isLast: boolean }> {
    let buffer = '';
    const sentenceEnders = /([.!?。！？])\s*/;
    
    for await (const token of this.chat(messages)) {
      buffer += token;
      
      // Check for complete sentence
      const match = buffer.match(sentenceEnders);
      if (match && match.index !== undefined) {
        const sentence = buffer.slice(0, match.index + 1).trim();
        buffer = buffer.slice(match.index + match[0].length);
        
        if (sentence) {
          yield { sentence, isLast: false };
        }
      }
    }
    
    // Yield remaining text
    if (buffer.trim()) {
      yield { sentence: buffer.trim(), isLast: true };
    }
  }
  
  /**
   * Health check
   */
  async isHealthy(): Promise<boolean> {
    try {
      await this.client.list();
      return true;
    } catch {
      return false;
    }
  }
  
  /**
   * Preload model into memory
   */
  async warmup(): Promise<void> {
    await this.client.chat({
      model: this.config.model,
      messages: [{ role: 'user', content: 'Hi' }],
      stream: false,
      options: { num_predict: 1 },
    });
  }
}
```

### 5.5 Conversation Context Management

```typescript
interface Message {
  role: 'system' | 'user' | 'assistant';
  content: string;
  timestamp?: number;
}

class ConversationContext {
  private messages: Message[] = [];
  private maxTokens: number;
  private systemPrompt: string;
  
  constructor(maxTokens: number = 4096) {
    this.maxTokens = maxTokens;
    this.systemPrompt = ''; // Set via Modelfile
  }
  
  addUserMessage(content: string): void {
    this.messages.push({
      role: 'user',
      content,
      timestamp: Date.now(),
    });
    this.trim();
  }
  
  addAssistantMessage(content: string): void {
    this.messages.push({
      role: 'assistant',
      content,
      timestamp: Date.now(),
    });
    this.trim();
  }
  
  getMessages(): Message[] {
    return [...this.messages];
  }
  
  /**
   * Trim old messages to fit context window
   * Keep system prompt and recent messages
   */
  private trim(): void {
    // Rough estimate: 4 chars per token
    const estimateTokens = (text: string) => Math.ceil(text.length / 4);
    
    let totalTokens = this.messages.reduce(
      (sum, m) => sum + estimateTokens(m.content),
      0
    );
    
    // Keep at least last 2 turns
    while (totalTokens > this.maxTokens * 0.8 && this.messages.length > 4) {
      const removed = this.messages.shift();
      if (removed) {
        totalTokens -= estimateTokens(removed.content);
      }
    }
  }
  
  clear(): void {
    this.messages = [];
  }
}
```

### 5.6 Performance Optimization

```typescript
// Pre-warm the model on startup
async function initializeOllama(client: OllamaClient): Promise<void> {
  console.log('Warming up Ollama model...');
  const start = Date.now();
  
  await client.warmup();
  
  console.log(`Model ready in ${Date.now() - start}ms`);
}

// Connection pool for concurrent requests
class OllamaPool {
  private semaphore: Semaphore;
  private client: OllamaClient;
  
  constructor(client: OllamaClient, maxConcurrent: number = 4) {
    this.client = client;
    this.semaphore = new Semaphore(maxConcurrent);
  }
  
  async *chat(messages: Message[]): AsyncIterable<string> {
    const release = await this.semaphore.acquire();
    
    try {
      for await (const token of this.client.chat(messages)) {
        yield token;
      }
    } finally {
      release();
    }
  }
}
```

---

## 6. RTP Integration

### 6.1 Network Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         NETWORK TOPOLOGY                             │
│                                                                      │
│   External Network                    Internal Network               │
│   ───────────────                    ─────────────────               │
│                                                                      │
│   ┌──────────┐        Firewall       ┌──────────────────────┐       │
│   │   PBX    │          │            │    Voice Platform    │       │
│   │  / SBC   │          │            │                      │       │
│   │          │          │            │  ┌────────────────┐  │       │
│   │ RTP ─────┼──────────┼────────────┼─▶│  RTP Endpoint  │  │       │
│   │ (10000-  │          │            │  │  UDP 10000-    │  │       │
│   │  20000)  │          │            │  │  20000         │  │       │
│   │          │          │            │  └────────────────┘  │       │
│   │ SIP ─────┼──────────┼────────────┼─▶│  SIP Handler   │  │       │
│   │ (5060)   │          │            │  │  TCP/UDP 5060  │  │       │
│   └──────────┘          │            │  └────────────────┘  │       │
│                         │            │                      │       │
│   ┌──────────┐          │            │  ┌────────────────┐  │       │
│   │  Client  │          │            │  │   WebSocket    │  │       │
│   │   App    │──────────┼────────────┼─▶│   API 8080     │  │       │
│   └──────────┘          │            │  └────────────────┘  │       │
│                         │            └──────────────────────┘       │
│                                                                      │
│   Firewall Rules:                                                   │
│   • UDP 10000-20000 (RTP)                                          │
│   • TCP/UDP 5060 (SIP)                                             │
│   • TCP 8080 (WebSocket API)                                       │
└─────────────────────────────────────────────────────────────────────┘
```

### 6.2 RTP Handler Implementation

```typescript
import dgram from 'dgram';

interface RTPPacket {
  version: number;
  padding: boolean;
  extension: boolean;
  csrcCount: number;
  marker: boolean;
  payloadType: number;
  sequenceNumber: number;
  timestamp: number;
  ssrc: number;
  payload: Buffer;
}

class RTPReceiver {
  private socket: dgram.Socket;
  private port: number;
  private jitterBuffer: JitterBuffer;
  
  constructor(port: number) {
    this.port = port;
    this.socket = dgram.createSocket('udp4');
    this.jitterBuffer = new JitterBuffer({ targetDelayMs: 40 });
  }
  
  start(): void {
    this.socket.on('message', (msg, rinfo) => {
      const packet = this.parseRTP(msg);
      this.jitterBuffer.push(packet);
    });
    
    this.socket.bind(this.port);
  }
  
  private parseRTP(buffer: Buffer): RTPPacket {
    return {
      version: (buffer[0] >> 6) & 0x03,
      padding: ((buffer[0] >> 5) & 0x01) === 1,
      extension: ((buffer[0] >> 4) & 0x01) === 1,
      csrcCount: buffer[0] & 0x0f,
      marker: ((buffer[1] >> 7) & 0x01) === 1,
      payloadType: buffer[1] & 0x7f,
      sequenceNumber: buffer.readUInt16BE(2),
      timestamp: buffer.readUInt32BE(4),
      ssrc: buffer.readUInt32BE(8),
      payload: buffer.slice(12),
    };
  }
  
  /**
   * Get PCM frames at regular intervals
   */
  async *getFrames(intervalMs: number = 20): AsyncIterable<Int16Array> {
    const timer = setInterval(() => {}, intervalMs);
    
    try {
      while (true) {
        await this.delay(intervalMs);
        const frame = this.jitterBuffer.pop();
        
        if (frame) {
          // Decode G.711 μ-law to PCM16
          const pcm = this.decodeUlaw(frame.payload);
          yield pcm;
        }
      }
    } finally {
      clearInterval(timer);
    }
  }
  
  private decodeUlaw(encoded: Buffer): Int16Array {
    const decoded = new Int16Array(encoded.length);
    
    for (let i = 0; i < encoded.length; i++) {
      let byte = ~encoded[i] & 0xff;
      const sign = byte & 0x80;
      const exponent = (byte >> 4) & 0x07;
      const mantissa = byte & 0x0f;
      
      let sample = ((mantissa << 3) + 0x84) << exponent;
      sample -= 0x84;
      
      decoded[i] = sign ? -sample : sample;
    }
    
    return decoded;
  }
  
  private delay(ms: number): Promise<void> {
    return new Promise(resolve => setTimeout(resolve, ms));
  }
  
  stop(): void {
    this.socket.close();
  }
}
```

### 6.3 Jitter Buffer

```typescript
interface JitterBufferConfig {
  minDelayMs: number;     // 20ms
  maxDelayMs: number;     // 80ms
  targetDelayMs: number;  // 40ms
}

class JitterBuffer {
  private buffer: Map<number, RTPPacket> = new Map();
  private nextSeq: number = -1;
  private config: JitterBufferConfig;
  
  constructor(config: Partial<JitterBufferConfig> = {}) {
    this.config = {
      minDelayMs: 20,
      maxDelayMs: 80,
      targetDelayMs: 40,
      ...config,
    };
  }
  
  push(packet: RTPPacket): void {
    this.buffer.set(packet.sequenceNumber, packet);
    
    // Initialize sequence tracking
    if (this.nextSeq === -1) {
      this.nextSeq = packet.sequenceNumber;
    }
    
    // Cleanup old packets (handle wrap-around)
    this.cleanup();
  }
  
  pop(): RTPPacket | null {
    const packet = this.buffer.get(this.nextSeq);
    
    if (packet) {
      this.buffer.delete(this.nextSeq);
      this.nextSeq = (this.nextSeq + 1) & 0xffff; // 16-bit wrap
      return packet;
    }
    
    // Packet loss - skip
    this.nextSeq = (this.nextSeq + 1) & 0xffff;
    return null;
  }
  
  private cleanup(): void {
    // Remove packets too old
    const threshold = 100; // packets
    if (this.buffer.size > threshold) {
      const seqs = Array.from(this.buffer.keys()).sort((a, b) => a - b);
      for (let i = 0; i < seqs.length - threshold; i++) {
        this.buffer.delete(seqs[i]);
      }
    }
  }
}
```

### 6.4 RTP Sender (TTS Output)

```typescript
class RTPSender {
  private socket: dgram.Socket;
  private remoteAddress: string;
  private remotePort: number;
  private sequenceNumber: number = 0;
  private timestamp: number = 0;
  private ssrc: number;
  
  constructor(remoteAddress: string, remotePort: number) {
    this.socket = dgram.createSocket('udp4');
    this.remoteAddress = remoteAddress;
    this.remotePort = remotePort;
    this.ssrc = Math.floor(Math.random() * 0xffffffff);
  }
  
  /**
   * Send PCM audio as RTP stream
   */
  async sendAudio(pcm: Int16Array, sampleRate: number = 8000): Promise<void> {
    // Resample if needed (Piper outputs 22050Hz)
    const resampled = this.resample(pcm, sampleRate, 8000);
    
    // Encode to G.711 μ-law
    const encoded = this.encodeUlaw(resampled);
    
    // Split into 20ms packets (160 samples at 8kHz)
    const packetSize = 160;
    
    for (let i = 0; i < encoded.length; i += packetSize) {
      const payload = encoded.slice(i, i + packetSize);
      const packet = this.createRTPPacket(payload);
      
      await this.send(packet);
      
      // Pace sending to match realtime
      await this.delay(20);
    }
  }
  
  private createRTPPacket(payload: Buffer): Buffer {
    const header = Buffer.alloc(12);
    
    // Version 2, no padding, no extension, no CSRC
    header[0] = 0x80;
    // Payload type 0 (PCMU)
    header[1] = 0x00;
    // Sequence number
    header.writeUInt16BE(this.sequenceNumber++ & 0xffff, 2);
    // Timestamp
    header.writeUInt32BE(this.timestamp, 4);
    this.timestamp += payload.length;
    // SSRC
    header.writeUInt32BE(this.ssrc, 8);
    
    return Buffer.concat([header, payload]);
  }
  
  private encodeUlaw(samples: Int16Array): Buffer {
    const encoded = Buffer.alloc(samples.length);
    
    for (let i = 0; i < samples.length; i++) {
      let sample = samples[i];
      const sign = sample < 0 ? 0x80 : 0;
      
      if (sample < 0) sample = -sample;
      sample = Math.min(sample, 32635);
      sample += 0x84;
      
      let exponent = 7;
      for (let mask = 0x4000; (sample & mask) === 0 && exponent > 0; exponent--) {
        mask >>= 1;
      }
      
      const mantissa = (sample >> (exponent + 3)) & 0x0f;
      encoded[i] = ~(sign | (exponent << 4) | mantissa) & 0xff;
    }
    
    return encoded;
  }
  
  private resample(input: Int16Array, fromRate: number, toRate: number): Int16Array {
    if (fromRate === toRate) return input;
    
    const ratio = fromRate / toRate;
    const outputLength = Math.floor(input.length / ratio);
    const output = new Int16Array(outputLength);
    
    for (let i = 0; i < outputLength; i++) {
      const srcIndex = i * ratio;
      const floor = Math.floor(srcIndex);
      const frac = srcIndex - floor;
      
      const s1 = input[floor] || 0;
      const s2 = input[floor + 1] || s1;
      
      output[i] = Math.round(s1 * (1 - frac) + s2 * frac);
    }
    
    return output;
  }
  
  private send(packet: Buffer): Promise<void> {
    return new Promise((resolve, reject) => {
      this.socket.send(packet, this.remotePort, this.remoteAddress, (err) => {
        if (err) reject(err);
        else resolve();
      });
    });
  }
  
  private delay(ms: number): Promise<void> {
    return new Promise(resolve => setTimeout(resolve, ms));
  }
}
```

---

## 7. WebSocket Realtime API

### 7.1 Connection

```
wss://api.example.com/v1/realtime
```

**Authentication:** Bearer token in query parameter or header.

```typescript
// Connection example
const ws = new WebSocket('wss://api.example.com/v1/realtime?token=xxx');
```

### 7.2 Message Protocol

All messages are JSON with a `type` field:

```typescript
interface BaseMessage {
  type: string;
  id?: string;           // Client-provided for correlation
  timestamp?: string;    // ISO 8601
}
```

### 7.3 Client → Server Events

#### session.create

```json
{
  "type": "session.create",
  "id": "msg_001",
  "config": {
    "language": "pt-BR",
    "voice": "faber",
    "mode": "conversation",
    "rtp": {
      "enabled": true,
      "codec": "PCMU"
    }
  }
}
```

#### audio.append

Send audio chunk (when not using RTP):

```json
{
  "type": "audio.append",
  "session_id": "sess_abc123",
  "audio": {
    "format": "pcm16",
    "sample_rate": 16000,
    "data": "<base64>"
  }
}
```

#### audio.commit

Signal end of user speech:

```json
{
  "type": "audio.commit",
  "session_id": "sess_abc123"
}
```

#### response.cancel

Cancel current response (barge-in):

```json
{
  "type": "response.cancel",
  "session_id": "sess_abc123"
}
```

#### session.close

End session:

```json
{
  "type": "session.close",
  "session_id": "sess_abc123"
}
```

### 7.4 Server → Client Events

#### session.created

```json
{
  "type": "session.created",
  "session_id": "sess_abc123",
  "rtp": {
    "address": "192.168.1.100",
    "port": 10042,
    "ssrc": 12345678
  }
}
```

#### input.speech_started

```json
{
  "type": "input.speech_started",
  "session_id": "sess_abc123",
  "timestamp": "2026-01-22T10:30:00.000Z"
}
```

#### input.speech_ended

```json
{
  "type": "input.speech_ended",
  "session_id": "sess_abc123",
  "timestamp": "2026-01-22T10:30:02.500Z",
  "duration_ms": 2500
}
```

#### input.transcript

```json
{
  "type": "input.transcript",
  "session_id": "sess_abc123",
  "transcript": {
    "text": "Olá, como você está?",
    "confidence": 0.94,
    "is_final": true
  }
}
```

#### response.text.delta

```json
{
  "type": "response.text.delta",
  "session_id": "sess_abc123",
  "delta": "Olá! ",
  "response_id": "resp_001"
}
```

#### response.text.done

```json
{
  "type": "response.text.done",
  "session_id": "sess_abc123",
  "response_id": "resp_001",
  "text": "Olá! Estou bem, obrigado por perguntar."
}
```

#### response.audio.delta

```json
{
  "type": "response.audio.delta",
  "session_id": "sess_abc123",
  "response_id": "resp_001",
  "audio": {
    "format": "pcm16",
    "sample_rate": 22050,
    "data": "<base64>"
  }
}
```

#### response.audio.done

```json
{
  "type": "response.audio.done",
  "session_id": "sess_abc123",
  "response_id": "resp_001",
  "duration_ms": 2100
}
```

#### response.done

```json
{
  "type": "response.done",
  "session_id": "sess_abc123",
  "response_id": "resp_001",
  "usage": {
    "input_tokens": 45,
    "output_tokens": 32
  }
}
```

#### error

```json
{
  "type": "error",
  "session_id": "sess_abc123",
  "error": {
    "code": "INFERENCE_TIMEOUT",
    "message": "LLM response timed out",
    "recoverable": true
  }
}
```

### 7.5 Error Codes

| Code | Description | Recoverable |
|------|-------------|-------------|
| `SESSION_NOT_FOUND` | Invalid session ID | No |
| `SESSION_LIMIT` | Max concurrent sessions reached | Yes (retry) |
| `INFERENCE_TIMEOUT` | Ollama/ASR/TTS timeout | Yes |
| `AUDIO_FORMAT` | Invalid audio format | No |
| `RATE_LIMITED` | Too many requests | Yes |
| `INTERNAL_ERROR` | Server error | Depends |

### 7.6 WebSocket Server Implementation

```typescript
import { WebSocketServer, WebSocket } from 'ws';

interface Session {
  id: string;
  ws: WebSocket;
  state: SessionState;
  context: ConversationContext;
  rtpReceiver?: RTPReceiver;
  rtpSender?: RTPSender;
  createdAt: number;
  lastActivityAt: number;
}

type SessionState = 
  | 'CREATED'
  | 'LISTENING'
  | 'PROCESSING'
  | 'SPEAKING'
  | 'CLOSED';

class RealtimeServer {
  private wss: WebSocketServer;
  private sessions: Map<string, Session> = new Map();
  private ollama: OllamaClient;
  private vad: VADProcessor;
  private asr: ASRProcessor;
  private tts: TTSProcessor;
  
  private readonly MAX_SESSIONS = 4;
  
  constructor(port: number) {
    this.wss = new WebSocketServer({ port });
    this.setupHandlers();
    this.initializeComponents();
  }
  
  private setupHandlers(): void {
    this.wss.on('connection', (ws, req) => {
      ws.on('message', (data) => this.handleMessage(ws, data));
      ws.on('close', () => this.handleDisconnect(ws));
      ws.on('error', (err) => this.handleError(ws, err));
    });
  }
  
  private async handleMessage(ws: WebSocket, data: any): Promise<void> {
    try {
      const message = JSON.parse(data.toString());
      
      switch (message.type) {
        case 'session.create':
          await this.handleSessionCreate(ws, message);
          break;
        case 'audio.append':
          await this.handleAudioAppend(message);
          break;
        case 'audio.commit':
          await this.handleAudioCommit(message);
          break;
        case 'response.cancel':
          await this.handleResponseCancel(message);
          break;
        case 'session.close':
          await this.handleSessionClose(message);
          break;
        default:
          this.sendError(ws, 'UNKNOWN_MESSAGE', `Unknown message type: ${message.type}`);
      }
    } catch (err) {
      this.sendError(ws, 'PARSE_ERROR', 'Invalid JSON message');
    }
  }
  
  private async handleSessionCreate(ws: WebSocket, message: any): Promise<void> {
    // Check session limit
    if (this.sessions.size >= this.MAX_SESSIONS) {
      this.sendError(ws, 'SESSION_LIMIT', 'Maximum concurrent sessions reached');
      return;
    }
    
    const sessionId = this.generateSessionId();
    const session: Session = {
      id: sessionId,
      ws,
      state: 'CREATED',
      context: new ConversationContext(),
      createdAt: Date.now(),
      lastActivityAt: Date.now(),
    };
    
    // Setup RTP if requested
    if (message.config?.rtp?.enabled) {
      const rtpPort = await this.allocateRTPPort();
      session.rtpReceiver = new RTPReceiver(rtpPort);
      session.rtpReceiver.start();
      
      // Start processing RTP audio
      this.processRTPAudio(session);
    }
    
    this.sessions.set(sessionId, session);
    session.state = 'LISTENING';
    
    // Send confirmation
    this.send(ws, {
      type: 'session.created',
      session_id: sessionId,
      rtp: session.rtpReceiver ? {
        address: this.getExternalIP(),
        port: session.rtpReceiver.port,
      } : undefined,
    });
  }
  
  private async processRTPAudio(session: Session): Promise<void> {
    if (!session.rtpReceiver) return;
    
    const audioBuffer: Int16Array[] = [];
    let isSpeaking = false;
    
    for await (const frame of session.rtpReceiver.getFrames(20)) {
      // Update activity
      session.lastActivityAt = Date.now();
      
      // Resample to 16kHz for VAD/ASR
      const resampled = this.resample(frame, 8000, 16000);
      
      // VAD processing
      const speechProb = this.vad.process(new Float32Array(resampled.buffer));
      
      if (speechProb > 0.5 && !isSpeaking) {
        isSpeaking = true;
        this.send(session.ws, {
          type: 'input.speech_started',
          session_id: session.id,
          timestamp: new Date().toISOString(),
        });
      }
      
      if (isSpeaking) {
        audioBuffer.push(resampled);
        
        if (speechProb < 0.3) {
          isSpeaking = false;
          
          // Process accumulated audio
          const audio = this.concatenateAudio(audioBuffer);
          audioBuffer.length = 0;
          
          await this.processUserSpeech(session, audio);
        }
      }
    }
  }
  
  private async processUserSpeech(session: Session, audio: Int16Array): Promise<void> {
    session.state = 'PROCESSING';
    
    // ASR
    let transcript = '';
    for await (const segment of this.asr.transcribe(new Float32Array(audio.buffer))) {
      transcript += segment.text;
      
      this.send(session.ws, {
        type: 'input.transcript',
        session_id: session.id,
        transcript: {
          text: transcript,
          confidence: segment.confidence,
          is_final: !segment.isPartial,
        },
      });
    }
    
    // Update context
    session.context.addUserMessage(transcript);
    
    // Generate response
    session.state = 'SPEAKING';
    await this.generateResponse(session);
    session.state = 'LISTENING';
  }
  
  private async generateResponse(session: Session): Promise<void> {
    const responseId = this.generateResponseId();
    let fullText = '';
    
    // Stream LLM response with sentence detection
    for await (const { sentence, isLast } of this.ollama.chatWithSentences(
      session.context.getMessages()
    )) {
      fullText += sentence + ' ';
      
      // Send text delta
      this.send(session.ws, {
        type: 'response.text.delta',
        session_id: session.id,
        response_id: responseId,
        delta: sentence + ' ',
      });
      
      // Synthesize and stream audio
      const audio = await this.tts.synthesize(sentence);
      
      // Send via WebSocket
      this.send(session.ws, {
        type: 'response.audio.delta',
        session_id: session.id,
        response_id: responseId,
        audio: {
          format: 'pcm16',
          sample_rate: 22050,
          data: Buffer.from(audio.buffer).toString('base64'),
        },
      });
      
      // Send via RTP if available
      if (session.rtpSender) {
        await session.rtpSender.sendAudio(audio, 22050);
      }
    }
    
    // Update context
    session.context.addAssistantMessage(fullText.trim());
    
    // Send completion events
    this.send(session.ws, {
      type: 'response.text.done',
      session_id: session.id,
      response_id: responseId,
      text: fullText.trim(),
    });
    
    this.send(session.ws, {
      type: 'response.done',
      session_id: session.id,
      response_id: responseId,
    });
  }
  
  private send(ws: WebSocket, message: any): void {
    if (ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({
        ...message,
        timestamp: new Date().toISOString(),
      }));
    }
  }
  
  private sendError(ws: WebSocket, code: string, message: string): void {
    this.send(ws, {
      type: 'error',
      error: { code, message },
    });
  }
  
  private generateSessionId(): string {
    return `sess_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 9)}`;
  }
  
  private generateResponseId(): string {
    return `resp_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 9)}`;
  }
}
```

---

## 8. Data Flow & Timing

### 8.1 Complete Request Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         VOICE-TO-VOICE DATA FLOW                            │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  TIME    COMPONENT        ACTION                           LATENCY          │
│  ────    ─────────        ──────                           ───────          │
│                                                                             │
│  T+0     RTP Receiver     Receive audio packet             -               │
│          │                                                                  │
│  T+20    Jitter Buffer    Buffer & reorder                 20ms            │
│          │                                                                  │
│  T+25    Codec            Decode G.711 → PCM               5ms             │
│          │                                                                  │
│  T+30    Resampler        8kHz → 16kHz                     5ms             │
│          │                                                                  │
│  T+40    Silero VAD       Detect speech                    10ms            │
│          │                                                                  │
│          ├── Speech Start Event ──────────────────────────────────────►    │
│          │                                                                  │
│  T+2500  VAD              Detect speech end                -               │
│          │                                                                  │
│  T+2520  faster-whisper   Transcribe audio                 150ms           │
│          │                                                                  │
│          ├── Transcript Event ────────────────────────────────────────►    │
│          │                                                                  │
│  T+2670  Ollama           Start generation                 -               │
│          │                                                                  │
│  T+2850  Ollama           First token (TTFT)               180ms           │
│          │                                                                  │
│          ├── Text Delta Event ────────────────────────────────────────►    │
│          │                                                                  │
│  T+2900  Sentence         Detect sentence end              50ms            │
│          Detector                                                           │
│          │                                                                  │
│  T+2980  Piper TTS        First audio byte (TTFB)          80ms            │
│          │                                                                  │
│          ├── Audio Delta Event ───────────────────────────────────────►    │
│          │                                                                  │
│  T+3000  RTP Sender       Send first audio packet          20ms            │
│          │                                                                  │
│  ════════════════════════════════════════════════════════════════════════  │
│          TOTAL LATENCY (speech end to audio start):        ~480ms          │
│          PERCEIVED LATENCY (includes speech duration):     varies          │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 8.2 Latency Budget

| Component | Budget | Expected | Notes |
|-----------|--------|----------|-------|
| Jitter Buffer | 40ms | 20-40ms | Adaptive |
| Codec Decode | 10ms | 5ms | G.711 is simple |
| Resampling | 10ms | 5ms | Linear interpolation |
| VAD | 20ms | 10ms | Per frame |
| ASR | 200ms | 150ms | faster-whisper streaming |
| LLM (TTFT) | 200ms | 180ms | Ollama warm |
| Sentence Detection | 50ms | 30ms | Buffer until punctuation |
| TTS (TTFB) | 100ms | 80ms | Piper |
| **Total** | **630ms** | **~480ms** | Under budget |

### 8.3 Optimization Strategies

#### 1. Speculative TTS Execution

```typescript
// Start TTS before sentence is complete
async function speculativeTTS(
  llmStream: AsyncIterable<string>,
  tts: TTSProcessor
): AsyncIterable<Int16Array> {
  let buffer = '';
  const minChars = 20;  // Start TTS after 20 chars
  
  for await (const token of llmStream) {
    buffer += token;
    
    // Check for natural break point
    const breakPoint = findBreakPoint(buffer, minChars);
    
    if (breakPoint > 0) {
      const chunk = buffer.slice(0, breakPoint);
      buffer = buffer.slice(breakPoint);
      
      yield* tts.synthesize(chunk);
    }
  }
  
  // Process remaining
  if (buffer.trim()) {
    yield* tts.synthesize(buffer);
  }
}

function findBreakPoint(text: string, minLength: number): number {
  if (text.length < minLength) return -1;
  
  // Priority: sentence end > clause > word
  const patterns = [
    /[.!?。！？]\s*/,    // Sentence
    /[,;:，；：]\s*/,    // Clause
    /\s+/,              // Word
  ];
  
  for (const pattern of patterns) {
    const match = text.slice(minLength).match(pattern);
    if (match && match.index !== undefined) {
      return minLength + match.index + match[0].length;
    }
  }
  
  return -1;
}
```

#### 2. Model Preloading

```typescript
// Keep model warm
async function keepModelWarm(ollama: OllamaClient): void {
  setInterval(async () => {
    try {
      await ollama.chat([{ role: 'user', content: 'ping' }], {
        num_predict: 1,
      });
    } catch (err) {
      console.error('Warmup failed:', err);
    }
  }, 60000);  // Every minute
}
```

#### 3. Audio Buffer Pre-allocation

```typescript
class AudioBufferPool {
  private pool: Int16Array[] = [];
  private readonly frameSize = 320;  // 20ms at 16kHz
  
  acquire(): Int16Array {
    return this.pool.pop() || new Int16Array(this.frameSize);
  }
  
  release(buffer: Int16Array): void {
    if (this.pool.length < 100) {  // Max pool size
      buffer.fill(0);
      this.pool.push(buffer);
    }
  }
}
```

---

## 9. Configuration

### 9.1 Environment Variables

```bash
# Server
PORT=8080
HOST=0.0.0.0
LOG_LEVEL=info
NODE_ENV=production

# Ollama
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=voice-assistant
OLLAMA_NUM_PARALLEL=4

# ASR
ASR_MODEL_SIZE=large-v3
ASR_COMPUTE_TYPE=int8
ASR_LANGUAGE=auto

# TTS
TTS_MODEL_PATH=./models/pt_BR-faber-medium.onnx
TTS_SAMPLE_RATE=22050

# VAD
VAD_MODEL_PATH=./models/silero_vad.onnx
VAD_THRESHOLD=0.5

# RTP
RTP_PORT_MIN=10000
RTP_PORT_MAX=20000
RTP_EXTERNAL_IP=auto

# Limits
MAX_SESSIONS=4
SESSION_TIMEOUT_MS=300000
INFERENCE_TIMEOUT_MS=30000
```

### 9.2 Configuration File

```yaml
# config.yaml
server:
  port: 8080
  host: 0.0.0.0
  
limits:
  maxSessions: 4
  sessionTimeoutMs: 300000
  inferenceTimeoutMs: 30000
  
ollama:
  host: http://localhost:11434
  model: voice-assistant
  options:
    temperature: 0.7
    top_p: 0.9
    num_predict: 150
    num_ctx: 4096
    
asr:
  modelSize: large-v3
  computeType: int8
  language: auto
  vadFilter: true
  
tts:
  modelPath: ./models/pt_BR-faber-medium.onnx
  sampleRate: 22050
  lengthScale: 1.0
  
vad:
  modelPath: ./models/silero_vad.onnx
  threshold: 0.5
  minSpeechDurationMs: 250
  minSilenceDurationMs: 300
  
rtp:
  portMin: 10000
  portMax: 20000
  externalIp: auto
  jitterBuffer:
    minDelayMs: 20
    maxDelayMs: 80
    targetDelayMs: 40
```

---

## 10. Deployment

### 10.1 System Requirements

| Resource | Minimum | Recommended |
|----------|---------|-------------|
| CPU | 8 cores | 16 cores |
| RAM | 16GB | 32GB |
| Storage | 50GB SSD | 100GB NVMe |
| Network | 100 Mbps | 1 Gbps |
| OS | Ubuntu 22.04 | Ubuntu 24.04 |

### 10.2 Directory Structure

```
/opt/voice-platform/
├── config/
│   └── config.yaml
├── models/
│   ├── silero_vad.onnx
│   ├── pt_BR-faber-medium.onnx
│   └── pt_BR-faber-medium.onnx.json
├── logs/
├── docker-compose.yml
└── .env
```

### 10.3 Docker Compose

```yaml
version: '3.8'

services:
  # Ollama LLM Server
  ollama:
    image: ollama/ollama:latest
    container_name: ollama
    ports:
      - "11434:11434"
    volumes:
      - ollama_data:/root/.ollama
    environment:
      - OLLAMA_NUM_PARALLEL=4
      - OLLAMA_MAX_LOADED_MODELS=1
      - OLLAMA_KEEP_ALIVE=24h
    deploy:
      resources:
        limits:
          cpus: '8'
          memory: 12G
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:11434/api/tags"]
      interval: 30s
      timeout: 10s
      retries: 3

  # Voice Pipeline Service
  voice-platform:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: voice-platform
    ports:
      - "8080:8080"
      - "10000-10100:10000-10100/udp"
    volumes:
      - ./config:/app/config:ro
      - ./models:/app/models:ro
      - ./logs:/app/logs
    environment:
      - NODE_ENV=production
      - OLLAMA_HOST=http://ollama:11434
    depends_on:
      ollama:
        condition: service_healthy
    deploy:
      resources:
        limits:
          cpus: '6'
          memory: 8G
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/health"]
      interval: 30s
      timeout: 10s
      retries: 3

volumes:
  ollama_data:

networks:
  default:
    driver: bridge
```

### 10.4 Dockerfile

```dockerfile
FROM node:20-slim

# Install dependencies for audio processing
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Install faster-whisper
RUN pip3 install faster-whisper --break-system-packages

WORKDIR /app

# Copy package files
COPY package*.json ./
RUN npm ci --only=production

# Copy application
COPY dist/ ./dist/
COPY config/ ./config/

# Create non-root user
RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8080
EXPOSE 10000-10100/udp

CMD ["node", "dist/index.js"]
```

### 10.5 Systemd Service (Non-Docker)

```ini
# /etc/systemd/system/voice-platform.service
[Unit]
Description=Voice Platform Service
After=network.target ollama.service
Requires=ollama.service

[Service]
Type=simple
User=voice
WorkingDirectory=/opt/voice-platform
ExecStart=/usr/bin/node dist/index.js
Restart=always
RestartSec=10
Environment=NODE_ENV=production

# Resource limits
LimitNOFILE=65535
LimitNPROC=4096

# Security
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/opt/voice-platform/logs

[Install]
WantedBy=multi-user.target
```

### 10.6 Initial Setup Script

```bash
#!/bin/bash
# setup.sh

set -e

echo "=== Voice Platform Setup ==="

# 1. Install Ollama
echo "Installing Ollama..."
curl -fsSL https://ollama.com/install.sh | sh

# 2. Configure Ollama
echo "Configuring Ollama..."
mkdir -p /etc/systemd/system/ollama.service.d
cat > /etc/systemd/system/ollama.service.d/override.conf << EOF
[Service]
Environment="OLLAMA_NUM_PARALLEL=4"
Environment="OLLAMA_MAX_LOADED_MODELS=1"
Environment="OLLAMA_KEEP_ALIVE=24h"
EOF

systemctl daemon-reload
systemctl restart ollama

# 3. Pull model
echo "Pulling Qwen2.5-7B model..."
ollama pull qwen2.5:7b-instruct-q4_K_M

# 4. Create custom model
echo "Creating voice-assistant model..."
cat > /tmp/Modelfile << 'EOF'
FROM qwen2.5:7b-instruct-q4_K_M

PARAMETER temperature 0.7
PARAMETER top_p 0.9
PARAMETER num_ctx 4096
PARAMETER num_predict 150

SYSTEM """You are a helpful voice assistant. Keep responses to 1-3 sentences. Speak naturally. Never use lists or formatting. Match the user's language."""
EOF

ollama create voice-assistant -f /tmp/Modelfile

# 5. Download models
echo "Downloading VAD and TTS models..."
mkdir -p /opt/voice-platform/models
cd /opt/voice-platform/models

# Silero VAD
wget -q https://github.com/snakers4/silero-vad/raw/master/files/silero_vad.onnx

# Piper TTS (Portuguese)
wget -q https://huggingface.co/rhasspy/piper-voices/resolve/main/pt/pt_BR/faber/medium/pt_BR-faber-medium.onnx
wget -q https://huggingface.co/rhasspy/piper-voices/resolve/main/pt/pt_BR/faber/medium/pt_BR-faber-medium.onnx.json

# 6. Verify
echo "Verifying installation..."
ollama list
curl -s http://localhost:11434/api/tags | jq .

echo "=== Setup Complete ==="
```

---

## 11. Monitoring & Observability

### 11.1 Health Endpoints

```typescript
// GET /health
{
  "status": "healthy",
  "version": "1.0.0",
  "uptime": 86400,
  "checks": {
    "ollama": "healthy",
    "asr": "healthy",
    "tts": "healthy",
    "sessions": {
      "active": 2,
      "max": 4
    }
  }
}

// GET /metrics (Prometheus format)
# HELP voice_sessions_active Current active sessions
# TYPE voice_sessions_active gauge
voice_sessions_active 2

# HELP voice_latency_seconds Voice-to-voice latency
# TYPE voice_latency_seconds histogram
voice_latency_seconds_bucket{le="0.3"} 850
voice_latency_seconds_bucket{le="0.5"} 950
voice_latency_seconds_bucket{le="1.0"} 1000

# HELP ollama_ttft_seconds Time to first token
# TYPE ollama_ttft_seconds histogram
ollama_ttft_seconds_bucket{le="0.1"} 200
ollama_ttft_seconds_bucket{le="0.2"} 800
ollama_ttft_seconds_bucket{le="0.3"} 980
```

### 11.2 Logging

```typescript
// Structured logging
{
  "timestamp": "2026-01-22T10:30:00.000Z",
  "level": "info",
  "service": "voice-platform",
  "session_id": "sess_abc123",
  "event": "response.complete",
  "metrics": {
    "asr_latency_ms": 145,
    "llm_ttft_ms": 178,
    "tts_ttfb_ms": 82,
    "total_latency_ms": 485
  }
}
```

### 11.3 Prometheus Configuration

```yaml
# prometheus.yml
scrape_configs:
  - job_name: 'voice-platform'
    static_configs:
      - targets: ['localhost:8080']
    scrape_interval: 15s
    
  - job_name: 'ollama'
    static_configs:
      - targets: ['localhost:11434']
    metrics_path: /api/metrics
```

### 11.4 Alert Rules

```yaml
# alerts.yml
groups:
  - name: voice-platform
    rules:
      - alert: HighLatency
        expr: histogram_quantile(0.95, voice_latency_seconds_bucket) > 0.5
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High voice-to-voice latency"
          
      - alert: SessionLimitReached
        expr: voice_sessions_active >= 4
        for: 1m
        labels:
          severity: warning
        annotations:
          summary: "Session limit reached"
          
      - alert: OllamaUnhealthy
        expr: up{job="ollama"} == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Ollama server is down"
```

---

## 12. Implementation Roadmap

### Phase 1: Foundation (Week 1-2)

- [ ] Setup development environment
- [ ] Implement Ollama client with streaming
- [ ] Implement basic WebSocket server
- [ ] Implement session management
- [ ] Unit tests for core components

**Deliverable:** Working Ollama chat via WebSocket

### Phase 2: Audio Pipeline (Week 3-4)

- [ ] Integrate Silero VAD
- [ ] Integrate faster-whisper ASR
- [ ] Integrate Piper TTS
- [ ] Implement audio streaming (WebSocket)
- [ ] End-to-end testing

**Deliverable:** Text-to-speech and speech-to-text working

### Phase 3: RTP Integration (Week 5-6)

- [ ] Implement RTP receiver
- [ ] Implement jitter buffer
- [ ] Implement G.711 codec
- [ ] Implement RTP sender
- [ ] SIP signaling (basic)

**Deliverable:** Working voice calls via RTP

### Phase 4: Production Hardening (Week 7-8)

- [ ] Performance optimization
- [ ] Error handling & recovery
- [ ] Monitoring & alerting
- [ ] Load testing
- [ ] Documentation

**Deliverable:** Production-ready deployment

### Phase 5: Advanced Features (Week 9+)

- [ ] Barge-in / interruption handling
- [ ] Multi-language support
- [ ] Voice selection API
- [ ] Analytics dashboard
- [ ] Custom fine-tuning pipeline

---

## Appendix A: API Quick Reference

### Session Lifecycle

```
Client                                  Server
   │                                       │
   │──── session.create ──────────────────▶│
   │◀─── session.created ─────────────────│
   │                                       │
   │──── audio.append (loop) ─────────────▶│
   │◀─── input.speech_started ────────────│
   │◀─── input.transcript ────────────────│
   │◀─── response.text.delta (loop) ──────│
   │◀─── response.audio.delta (loop) ─────│
   │◀─── response.done ───────────────────│
   │                                       │
   │──── session.close ───────────────────▶│
   │                                       │
```

### Error Handling

```typescript
// Retry with exponential backoff
async function withRetry<T>(
  fn: () => Promise<T>,
  maxRetries: number = 3
): Promise<T> {
  for (let i = 0; i < maxRetries; i++) {
    try {
      return await fn();
    } catch (err) {
      if (i === maxRetries - 1) throw err;
      await delay(Math.pow(2, i) * 1000);
    }
  }
  throw new Error('Max retries exceeded');
}
```

---

## Appendix B: Troubleshooting

### High Latency

1. Check Ollama model is loaded: `ollama ps`
2. Verify CPU usage: `htop`
3. Check ASR queue: logs for backpressure
4. Network latency: `ping` to RTP endpoint

### Ollama Errors

```bash
# Check Ollama logs
journalctl -u ollama -f

# Test Ollama directly
curl http://localhost:11434/api/generate -d '{
  "model": "voice-assistant",
  "prompt": "Hello",
  "stream": false
}'
```

### Memory Issues

```bash
# Check memory usage
free -h

# Ollama memory
curl http://localhost:11434/api/ps

# Reduce context if needed
PARAMETER num_ctx 2048  # In Modelfile
```

---

**Document End**
