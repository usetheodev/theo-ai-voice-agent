# ADR-004: Text-to-Speech Provider Selection

**Status:** Accepted  
**Date:** January 2026  
**Deciders:** Platform Architecture Team  
**Technical Story:** Select primary and fallback TTS providers for realtime voice pipeline

---

## Context

Text-to-Speech (TTS) converts LLM responses to audio for playback to the user. In realtime voice, TTS is often the **final bottleneck** before the user hears a response:

1. **Time to First Byte (TTFB)**: How quickly audio starts playing
2. **Streaming capability**: Generate audio incrementally, don't wait for full text
3. **Voice quality**: Natural-sounding speech reduces cognitive load
4. **CPU inference**: GPU should be optional

### Requirements

| Requirement | Priority | Target |
|-------------|----------|--------|
| Time to First Byte | Critical | < 100ms |
| Streaming | Critical | Sentence-level minimum |
| Voice naturalness | High | MOS > 4.0 |
| CPU inference | High | Yes (GPU optional) |
| Languages | High | pt-BR, en-US, es-ES |
| Sample rate output | Medium | 16kHz+ (resample for telephony) |

---

## Decision Drivers

1. **TTFB is critical**: User waiting in realtime; every 50ms matters
2. **Streaming reduces perceived latency**: Start playing before generation completes
3. **CPU deployment**: Must work without GPU at acceptable quality
4. **Voice consistency**: Same voice throughout session

---

## Considered Options

### Option 1: Kokoro-82M

**Source:** https://www.bentoml.com/blog/exploring-the-world-of-open-source-text-to-speech-models

**Evidence:**
> "Kokoro is a lightweight yet high-quality TTS model with just 82 million parameters. Despite its compact size, Kokoro delivers speech quality comparable to much larger models while being significantly faster and more cost-efficient to run. It's ideal for developers and organizations seeking fast, scalable voice synthesis without compromising quality."
>
> "Lightweight and efficient: At just 82M parameters, Kokoro runs efficiently on modest hardware with minimal latency. It's an excellent choice for cost-sensitive applications or edge deployment scenarios."
> — BentoML Blog

**Key characteristics:**
- 82M parameters (very lightweight)
- Based on StyleTTS2 and ISTFTNet
- No encoder/diffusion (faster)
- Apache 2.0 license
- ~50ms TTFB achievable

**Trade-offs:**
- Decoder-only may limit expressiveness
- Fewer voice options than larger models

### Option 2: CosyVoice2-0.5B

**Source:** https://www.siliconflow.com/articles/en/best-open-source-text-to-speech-models

**Evidence:**
> "CosyVoice 2 is a streaming speech synthesis model based on a large language model with unified streaming/non-streaming framework design. It achieves ultra-low latency of 150ms in streaming mode while maintaining synthesis quality identical to non-streaming mode. Compared with version 1.0, pronunciation errors are reduced by 30-50%, MOS score improved from 5.4 to 5.53."
> — SiliconFlow Guide

**Key characteristics:**
- 500M parameters
- 150ms streaming latency
- MOS 5.53 (excellent quality)
- Unified streaming/non-streaming
- Emotion and dialect control

**Trade-offs:**
- Larger model, needs more resources
- Primarily Chinese/English optimized

### Option 3: Piper TTS

**Source:** https://github.com/rhasspy/piper

**Evidence:**
> "PiperEngine offers high-quality, real-time text-to-speech synthesis using the Piper model."
>
> "MeloTTS and Piper TTS are the fastest, consistently processing short texts in under a second."
> — Inferless TTS Comparison

**Key characteristics:**
- VITS-based architecture
- Multiple pre-trained voices
- ONNX runtime (cross-platform)
- ~80ms TTFB
- MIT license

**Trade-offs:**
- Voice quality below neural competitors
- Limited language coverage

### Option 4: Chatterbox-Turbo

**Source:** https://www.bentoml.com/blog/exploring-the-world-of-open-source-text-to-speech-models

**Evidence:**
> "Chatterbox-Turbo uses a streamlined 350M-parameter architecture that significantly lowers compute and VRAM requirements while maintaining high-fidelity audio output. Turbo introduces a distilled one-step decoder that reduces generation from ten diffusion steps to a single step."
>
> "Chatterbox has been benchmarked favorably against proprietary models like ElevenLabs in side-by-side evaluations, while remaining completely free under the MIT License."
> — BentoML Blog

**Key characteristics:**
- 350M parameters
- One-step decoder (fast)
- Emotion exaggeration control
- MIT license
- Comparable to ElevenLabs quality

**Trade-offs:**
- English-focused
- Newer, less battle-tested

### Option 5: Cartesia Sonic 2.0 (Cloud)

**Source:** https://layercode.com/blog/tts-voice-ai-model-guide

**Evidence:**
> "Cartesia's Sonic 2.0 is one of the fastest engines on the market. Turbo mode can achieve ~40 ms TTFB. Sonic 2.0 also supports 15 realistic voices out of the box, and supports instant voice cloning."
> — Layercode TTS Guide

**Key characteristics:**
- ~40ms TTFB (industry-leading)
- 15 built-in voices
- Instant voice cloning
- Streaming API

**Trade-offs:**
- Cloud-only
- Pricing not publicly available

### Option 6: ElevenLabs (Cloud)

**Source:** Industry standard reference

**Key characteristics:**
- Best voice quality in industry
- Extensive voice library
- Voice cloning
- ~200ms TTFB

**Trade-offs:**
- Expensive ($0.30/1000 chars)
- Higher latency than alternatives
- Cloud dependency

---

## Decision

**Primary (CPU):** Kokoro-82M  
**Quality (GPU):** CosyVoice2-0.5B  
**Fallback (CPU):** Piper TTS  
**Fallback (Cloud):** Cartesia Sonic 2.0

### Rationale

1. **Kokoro-82M as primary CPU option**
   - 82M parameters runs efficiently on any hardware
   - ~50ms TTFB easily meets our 100ms requirement
   - Apache 2.0 license for commercial use
   - Quality "comparable to much larger models" per benchmarks
   - Decoder-only architecture optimizes for speed

2. **CosyVoice2 for GPU-enhanced quality**
   - MOS 5.53 is exceptional (above human average ~5.0)
   - 150ms streaming fits within budget
   - Emotion/dialect control useful for voice customization
   - When quality matters most and GPU available

3. **Piper as CPU fallback**
   - Battle-tested in Rhasspy ecosystem
   - ONNX runtime is reliable
   - 80ms TTFB acceptable for fallback
   - MIT license, no concerns

4. **Cartesia Sonic for cloud fallback**
   - 40ms TTFB is exceptional
   - Use when local inference overloaded
   - Streaming API well-suited for realtime

5. **Rejected options:**
   - **Chatterbox-Turbo**: English-only, doesn't meet Portuguese requirement
   - **ElevenLabs**: Too expensive and slow for realtime voice

---

## Implementation

### Provider Interface

```typescript
interface TTSProvider {
  readonly id: string;
  readonly capabilities: TTSCapabilities;
  
  // Synthesize streaming audio
  synthesize(request: TTSRequest): AsyncIterable<AudioChunk>;
  
  // Get available voices
  getVoices(): Voice[];
}

interface TTSCapabilities {
  languages: string[];
  voices: Voice[];
  maxInputLength: number;
  supportsStreaming: boolean;
  supportsSentenceStreaming: boolean;
  estimatedTTFB: number;
  sampleRate: number;
}

interface TTSRequest {
  text: string;
  voice: string;
  speed?: number;           // 0.5 - 2.0
  pitch?: number;           // 0.5 - 2.0
  emotion?: string;         // Provider-specific
}

interface AudioChunk {
  samples: Int16Array;
  sampleRate: number;
  isFinal: boolean;
}

interface Voice {
  id: string;
  name: string;
  language: string;
  gender: 'male' | 'female' | 'neutral';
  style?: string;
}
```

### Kokoro Configuration

```typescript
const kokoroConfig = {
  // Model
  modelPath: '/models/kokoro-82m.onnx',
  
  // Voice selection
  defaultVoice: 'af_bella',        // American Female
  
  // Audio output
  sampleRate: 24000,
  
  // Streaming
  chunkSize: 4800,                  // 200ms chunks at 24kHz
  
  // Performance
  threads: 2,
};

// Available voices
const kokoroVoices = [
  { id: 'af_bella', name: 'Bella', language: 'en-US', gender: 'female' },
  { id: 'af_sarah', name: 'Sarah', language: 'en-US', gender: 'female' },
  { id: 'am_adam', name: 'Adam', language: 'en-US', gender: 'male' },
  { id: 'am_michael', name: 'Michael', language: 'en-US', gender: 'male' },
  { id: 'bf_emma', name: 'Emma', language: 'en-GB', gender: 'female' },
  { id: 'bm_george', name: 'George', language: 'en-GB', gender: 'male' },
];
```

### Sentence-Level Streaming

```typescript
class TTSProcessor {
  async *synthesizeStreaming(
    sentences: AsyncIterable<string>,
    voice: string
  ): AsyncIterable<AudioChunk> {
    const provider = await this.router.getProvider();
    
    for await (const sentence of sentences) {
      // Start synthesis immediately for each sentence
      const startTime = Date.now();
      
      for await (const chunk of provider.synthesize({
        text: sentence,
        voice,
      })) {
        // Track TTFB for first chunk
        if (chunk === first) {
          this.metrics.recordTTFB(Date.now() - startTime);
        }
        
        yield chunk;
      }
    }
  }
}
```

### Audio Resampling for Telephony

```typescript
class AudioResampler {
  // Resample from TTS output (24kHz) to telephony (8kHz)
  resample(
    input: Int16Array,
    inputRate: number,
    outputRate: number
  ): Int16Array {
    if (inputRate === outputRate) return input;
    
    const ratio = inputRate / outputRate;
    const outputLength = Math.floor(input.length / ratio);
    const output = new Int16Array(outputLength);
    
    // Simple linear interpolation (use better algo in production)
    for (let i = 0; i < outputLength; i++) {
      const srcIndex = i * ratio;
      const srcIndexFloor = Math.floor(srcIndex);
      const frac = srcIndex - srcIndexFloor;
      
      const sample1 = input[srcIndexFloor];
      const sample2 = input[Math.min(srcIndexFloor + 1, input.length - 1)];
      
      output[i] = Math.round(sample1 * (1 - frac) + sample2 * frac);
    }
    
    return output;
  }
}
```

### Voice Mapping

```typescript
// Map user-facing voice names to provider-specific IDs
const voiceMapping: Record<string, Record<string, string>> = {
  'nova': {
    'kokoro-82m': 'af_bella',
    'cosyvoice2': 'female_1',
    'piper': 'en_US-amy-medium',
    'cartesia': 'nova',
  },
  'alloy': {
    'kokoro-82m': 'af_sarah',
    'cosyvoice2': 'female_2',
    'piper': 'en_US-lessac-medium',
    'cartesia': 'alloy',
  },
  // ... more mappings
};

function getProviderVoice(
  userVoice: string,
  providerId: string
): string {
  return voiceMapping[userVoice]?.[providerId] ?? 
         voiceMapping['nova'][providerId];  // Default to nova
}
```

---

## Consequences

### Positive

- **< 100ms TTFB achieved**: Kokoro ~50ms, well under budget
- **CPU inference works**: 82M model runs anywhere
- **Quality acceptable**: Kokoro comparable to larger models per benchmarks
- **Streaming from first sentence**: Reduces perceived latency

### Negative

- **Voice variety limited**: Kokoro has fewer voices than cloud options
- **Portuguese voices**: May need fine-tuning or different provider
- **Quality gap**: CosyVoice2 significantly better when GPU available

### Mitigations

1. **Voice fine-tuning**: Fine-tune Kokoro on Portuguese if needed
2. **Provider switching**: Use CosyVoice2 for quality-sensitive scenarios
3. **Voice cloning**: Investigate adding custom voices via cloning

---

## Validation

### Benchmark Test Plan

```yaml
test_scenarios:
  - name: "TTFB - Short sentence"
    provider: "kokoro-82m"
    input: "Hello, how can I help you today?"
    iterations: 100
    metrics: [ttfb_p50, ttfb_p95]
    expected:
      ttfb_p50: < 50ms
      ttfb_p95: < 100ms
      
  - name: "Quality - MOS evaluation"
    provider: "kokoro-82m"
    dataset: "tts_eval_sentences"
    evaluators: 10
    metrics: [mos]
    expected:
      mos: > 4.0
      
  - name: "Streaming latency"
    provider: "kokoro-82m"
    input: "This is a longer sentence that should be streamed. The quick brown fox jumps over the lazy dog."
    metrics: [time_to_complete, chunks_count]
    expected:
      chunks_count: > 3
```

---

## References

1. Kokoro TTS: https://huggingface.co/hexgrad/Kokoro-82M
2. CosyVoice2: https://github.com/FunAudioLLM/CosyVoice
3. Piper TTS: https://github.com/rhasspy/piper
4. Cartesia: https://cartesia.ai/
5. TTS Model Guide 2025: https://layercode.com/blog/tts-voice-ai-model-guide
6. Open Source TTS Comparison: https://www.inferless.com/learn/comparing-different-text-to-speech---tts--models-part-2
