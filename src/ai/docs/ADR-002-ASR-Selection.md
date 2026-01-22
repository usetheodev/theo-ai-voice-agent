# ADR-002: Automatic Speech Recognition Provider Selection

**Status:** Accepted  
**Date:** January 2026  
**Deciders:** Platform Architecture Team  
**Technical Story:** Select primary and fallback ASR providers for realtime voice pipeline

---

## Context

Automatic Speech Recognition (ASR) converts user speech to text for processing by the LLM. In a realtime voice system, ASR has unique requirements beyond traditional batch transcription:

1. **Streaming output**: Must emit partial results as speech is recognized
2. **Low latency**: Time from audio to text directly impacts voice-to-voice latency
3. **Accuracy under noise**: Telephony audio is often degraded
4. **Multi-language**: Must support at least Portuguese, English, Spanish

### Requirements

| Requirement | Priority | Target |
|-------------|----------|--------|
| Word Error Rate (WER) | High | < 10% (clean audio) |
| Streaming latency | Critical | < 150ms to partial result |
| CPU inference | High | Yes (GPU optional) |
| Languages | High | pt-BR, en-US, es-ES minimum |
| Partial results | Critical | Yes |

---

## Decision Drivers

1. **Streaming is non-negotiable**: Batch ASR adds 500ms+ latency
2. **CPU deployment priority**: GPU is optional enhancement, not requirement
3. **Quality vs speed tradeoff**: We can sacrifice some accuracy for latency
4. **Cost control**: Cloud ASR costs add up at scale

---

## Considered Options

### Option 1: SimulStreaming (WhisperStreaming successor)

**Source:** https://github.com/ufal/whisper_streaming

**Evidence:**
> "WhisperStreaming is becoming outdated in 2025. It is being replaced by a new project named SimulStreaming, by Dominik Macháček, the author of WhisperStreaming. SimulStreaming is much faster and higher quality than WhisperStreaming. It also adds an LLM translation model to be used in a cascade."
> — WhisperStreaming GitHub Repository

**Key characteristics:**
- Successor to widely-used WhisperStreaming
- Built on faster-whisper backend
- Native streaming with local agreement policy
- Self-adaptive latency
- Supports 99+ languages via Whisper

**Benchmarks:**

| Metric | SimulStreaming | WhisperStreaming |
|--------|----------------|------------------|
| Latency | ~100ms | ~200ms |
| Quality | Higher | Baseline |
| Features | +LLM translation | Basic |

### Option 2: NVIDIA Nemotron Speech ASR

**Source:** https://www.daily.co/blog/building-voice-agents-with-nvidia-open-models/

**Evidence:**
> "ASR (Automatic Speech Recognition) is the general term for machine learning models that process speech input, then output text. Previous generations of ASR models were generally designed for batch processing rather than realtime transcription. For example, the latency of the Whisper model is 600-800ms, and most commercial speech-to-text models today have latencies in the 200-400ms range."
>
> "Nemotron Speech ASR achieves sub-25ms transcription... The model is also very accurate. The industry standard for measuring ASR model accuracy is word error rate. Nemotron Speech ASR has a word error rate on all of our benchmarks roughly equivalent to the best commercial ASR models."
> — Daily.co Blog (January 2026)

**Key characteristics:**
- Sub-25ms latency (industry-leading)
- Cache-aware streaming architecture
- Comparable accuracy to commercial solutions
- Requires GPU for optimal performance
- Open weights, Apache 2.0 license

### Option 3: NVIDIA Parakeet TDT

**Source:** https://northflank.com/blog/best-open-source-speech-to-text-stt-model-in-2025-benchmarks

**Evidence:**
> "NVIDIA's Parakeet TDT models prioritize inference speed for real-time applications. The 1.1B parameter variant achieves RTFx near >2,000 (among the fastest models on Open ASR), as reported on the Hugging Face Open ASR leaderboard as of late 2026, processing audio dramatically faster than Whisper variants. The RNN-Transducer architecture enables streaming recognition with minimal latency."
>
> "Speed vs accuracy trade-off: Ranks 23rd in accuracy on Open ASR Leaderboard but processes audio 6.5x faster than Canary Qwen."
> — Northflank Blog

**Key characteristics:**
- RTFx ~2000 (processes 2000x faster than realtime)
- RNN-Transducer architecture for streaming
- Trained on 65,000 hours of English audio
- Trade-off: 23rd in accuracy vs speed leader
- Best for live captioning, real-time transcription

### Option 4: Kyutai (Moshi ASR)

**Source:** https://modal.com/blog/open-source-stt

**Evidence:**
> "Kyutai 1B sports a latency of just 1s after the initial audio chunk is streamed. However, Kyutai only supports English and French, with a slightly higher word error rate for French."
>
> "Kyutai is designed for real-time audio use cases. This includes real-time telecommunication software, such as phone trees, conversation simulators like sales role-play call training software, and voice interfaces."
> — Modal Blog

**Key characteristics:**
- 1 second latency after first chunk
- Designed for realtime telecoms
- Limited language support (English, French only)
- Not suitable for Portuguese requirement

### Option 5: Canary Qwen 2.5B

**Source:** https://modal.com/blog/open-source-stt

**Evidence:**
> "Canary Qwen 2.5B currently tops the Hugging Face Open ASR leaderboard with a 5.63% word error rate. What sets Canary apart is its new hybrid architecture that combines automatic speech recognition (ASR) with large language model (LLM) capabilities."
>
> "Canary Qwen has an RTFx score of 418, meaning that it can process audio 418 times faster than real-time. This is reasonably fast for most industry use cases, but other models, such as Parakeet TDT, do maintain RTFx scores of nearly 10x."
> — Modal Blog

**Key characteristics:**
- Best accuracy (5.63% WER)
- Hybrid ASR + LLM architecture
- 418x realtime processing
- English-only currently
- Requires NeMo toolkit

### Option 6: Deepgram Nova-3 (Cloud)

**Source:** https://northflank.com/blog/best-open-source-speech-to-text-stt-model-in-2025-benchmarks

**Evidence:**
> "Deepgram Nova-3: Independent AA-WER benchmarks report Nova-3 around 18% WER on mixed real-world datasets, with sub-300 ms latency. Pricing is roughly $4.30 per 1,000 minutes for basic transcription as of mid-2026."
> — Northflank Blog

**Key characteristics:**
- Sub-300ms latency
- 30+ languages
- Production-ready API
- $0.0043/minute cost
- Streaming WebSocket API

---

## Decision

**Primary (CPU):** SimulStreaming with faster-whisper backend  
**Primary (GPU):** Nemotron Speech ASR  
**Fallback (Cloud):** Deepgram Nova-3

### Rationale

1. **SimulStreaming for CPU deployments**
   - ~100ms streaming latency fits our budget
   - faster-whisper backend is mature and CPU-optimized
   - 99+ language support exceeds our requirements
   - Active development as WhisperStreaming successor

2. **Nemotron for GPU-enhanced deployments**
   - Sub-25ms latency is exceptional
   - Accuracy matches commercial solutions
   - When GPU is available, use the best option
   - Cache-aware architecture designed for streaming

3. **Deepgram as cloud fallback**
   - Handles overflow when local capacity exceeded
   - Sub-300ms latency is acceptable for fallback
   - Proven production reliability
   - $4.30/1000 minutes is cost-effective for overflow

4. **Rejected options:**
   - **Kyutai**: No Portuguese support
   - **Canary Qwen**: English-only, no streaming focus
   - **Parakeet TDT**: Too much accuracy sacrifice (23rd place)

---

## Implementation

### Provider Interface

```typescript
interface ASRProvider {
  readonly id: string;
  readonly capabilities: ASRCapabilities;
  
  // Start streaming session
  startStream(config: ASRStreamConfig): ASRStream;
}

interface ASRCapabilities {
  languages: string[];
  supportsPartialResults: boolean;
  estimatedLatencyMs: number;
  wordTimestamps: boolean;
  speakerDiarization: boolean;
}

interface ASRStream {
  // Feed audio chunk
  write(audio: Int16Array): void;
  
  // Get results (async iterator)
  results(): AsyncIterable<ASRResult>;
  
  // End stream
  end(): Promise<ASRResult>;
}

interface ASRResult {
  type: 'partial' | 'final';
  text: string;
  confidence: number;
  words?: WordTiming[];
  language?: string;
}
```

### SimulStreaming Configuration

```typescript
const simulStreamingConfig = {
  // Model selection
  model: 'large-v3',              // Whisper model size
  backend: 'faster-whisper',      // Use faster-whisper
  
  // Language
  language: 'pt',                 // ISO code or 'auto'
  task: 'transcribe',             // or 'translate'
  
  // Streaming parameters
  minChunkSize: 1.0,              // Minimum audio seconds before processing
  bufferTrimming: 'segment',      // How to manage buffer
  
  // VAD integration
  useVAD: true,                   // Use built-in VAD
  vadThreshold: 0.5,
};
```

### Nemotron Configuration

```typescript
const nemotronConfig = {
  // Model
  modelPath: '/models/nemotron-speech-asr',
  
  // Cache-aware streaming
  cacheSize: 1024,                // KV cache size
  chunkDurationMs: 80,            // Process every 80ms
  
  // Output
  outputPartials: true,
  partialMinConfidence: 0.6,
};
```

### Failover Logic

```typescript
class ASRRouter {
  private providers: Map<string, ASRProvider>;
  private healthMonitor: HealthMonitor;
  
  async getProvider(config: SessionConfig): Promise<ASRProvider> {
    // Check if GPU available and Nemotron healthy
    if (config.hasGPU && this.healthMonitor.isHealthy('nemotron-asr')) {
      return this.providers.get('nemotron-asr')!;
    }
    
    // Fall back to SimulStreaming
    if (this.healthMonitor.isHealthy('simul-streaming')) {
      return this.providers.get('simul-streaming')!;
    }
    
    // Cloud fallback
    if (this.healthMonitor.isHealthy('deepgram-nova3')) {
      console.warn('Using cloud ASR fallback');
      return this.providers.get('deepgram-nova3')!;
    }
    
    throw new Error('No healthy ASR providers available');
  }
}
```

---

## Consequences

### Positive

- **< 150ms streaming latency achieved**: SimulStreaming ~100ms, Nemotron ~25ms
- **Multi-language support**: Whisper-based solutions support 99+ languages
- **Cost control**: Local inference for normal load, cloud only for overflow
- **Quality maintained**: WER targets met with both primary options

### Negative

- **Complexity**: Three different ASR systems to maintain
- **GPU dependency for best latency**: Nemotron requires CUDA
- **Cloud cost exposure**: Deepgram costs during traffic spikes

### Mitigations

1. **Unified interface**: All providers implement same `ASRStream` interface
2. **Graceful GPU fallback**: Auto-detect GPU, fall back to CPU seamlessly
3. **Cost alerts**: Monitor Deepgram usage, alert if exceeds budget

---

## Validation

### Benchmark Test Plan

```yaml
test_scenarios:
  - name: "Clean speech - Portuguese"
    dataset: "common_voice_pt"
    metrics: [wer, latency_p95]
    expected:
      wer: < 0.10
      latency_p95: < 150ms
      
  - name: "Noisy telephony - English"
    dataset: "librispeech_noisy"
    snr: 10dB
    metrics: [wer, latency_p95]
    expected:
      wer: < 0.15
      latency_p95: < 200ms
      
  - name: "Concurrent sessions"
    concurrent: 50
    duration: 300s
    metrics: [latency_p99, error_rate]
    expected:
      latency_p99: < 300ms
      error_rate: < 0.01
```

---

## References

1. SimulStreaming: https://github.com/ufal/whisper_streaming
2. faster-whisper: https://github.com/SYSTRAN/faster-whisper
3. NVIDIA Nemotron Speech: https://huggingface.co/nvidia/nemotron-speech-asr
4. Deepgram Nova-3: https://deepgram.com/product/nova
5. Open ASR Leaderboard: https://huggingface.co/spaces/hf-audio/open_asr_leaderboard
6. Daily.co Voice Agents Guide: https://www.daily.co/blog/building-voice-agents-with-nvidia-open-models/
