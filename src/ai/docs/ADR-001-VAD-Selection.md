# ADR-001: Voice Activity Detection Provider Selection

**Status:** Accepted  
**Date:** January 2026  
**Deciders:** Platform Architecture Team  
**Technical Story:** Select primary and fallback VAD providers for realtime voice pipeline

---

## Context

Voice Activity Detection (VAD) is the first component in the realtime voice pipeline. It determines when the user is speaking and when there is silence. The quality and latency of VAD directly impacts:

1. **User experience**: False positives cause interruptions; false negatives miss speech
2. **System efficiency**: Poor VAD wastes compute on silence or drops speech
3. **Barge-in capability**: Fast VAD enables interrupting the bot mid-response
4. **End-to-end latency**: VAD latency directly adds to voice-to-voice time

### Requirements

| Requirement | Priority | Target |
|-------------|----------|--------|
| Frame-level latency | Critical | < 20ms |
| Precision (speech detection) | High | > 95% |
| Recall (silence detection) | High | > 90% |
| CPU efficiency | High | < 5% single core |
| Streaming support | Critical | Yes |
| Multi-language support | Medium | Language-agnostic |

---

## Decision Drivers

1. **Latency is paramount**: In realtime voice, every millisecond counts
2. **CPU-first deployment**: Our target infrastructure is CPU-only (no GPU requirement)
3. **Production readiness**: Need battle-tested solutions, not research prototypes
4. **Integration ecosystem**: Compatibility with ASR pipelines (sherpa-onnx, faster-whisper)

---

## Considered Options

### Option 1: TEN VAD (TEN Framework)

**Source:** https://github.com/TEN-framework/ten-vad

**Evidence:**
> "TEN VAD is a real-time voice activity detection system designed for enterprise use, providing accurate frame-level speech activity detection. It shows superior precision compared to both WebRTC VAD and Silero VAD, which are commonly used in the industry. Additionally, TEN VAD offers lower computational complexity and reduced memory usage compared to Silero VAD. Meanwhile, the architecture's temporal efficiency enables rapid voice activity detection, significantly reducing end-to-end response and turn detection latency in conversational AI systems."
> — TEN Framework GitHub Repository (2025)

**Key characteristics:**
- Released June 2025, actively maintained
- ONNX model for cross-platform deployment
- Integrated into sherpa-onnx (July 2025)
- Supports Python, C, Golang, Java, WASM
- Apache 2.0 license with additional conditions

**Benchmarks (from TEN documentation):**

| Metric | TEN VAD | Silero VAD | WebRTC VAD |
|--------|---------|------------|------------|
| Precision | 97.2% | 94.8% | 89.3% |
| Recall | 95.1% | 93.2% | 91.7% |
| Latency (10ms frame) | 0.8ms | 1.2ms | 0.3ms |
| Memory | 12MB | 48MB | 2MB |

### Option 2: Silero VAD

**Source:** https://github.com/snakers4/silero-vad

**Evidence:**
- Industry standard since 2021
- Used in production by hundreds of companies
- Well-documented, extensive community support
- PyTorch and ONNX models available

**Key characteristics:**
- Mature, battle-tested
- 16kHz optimized (requires resampling for 8kHz telephony)
- Slightly higher memory footprint
- Extensive language testing

### Option 3: WebRTC VAD

**Source:** libwebrtc / py-webrtcvad

**Evidence:**
> "WebRTC VAD operates as a real-time algorithm that processes incoming audio streams to determine whether the signal contains human speech or not. The core of the algorithm analyzes short frames of audio (typically 10-30ms), extracting features like energy levels, zero-crossing rate, and spectral information."
> — VideoSDK WebRTC Guide (2025)

**Key characteristics:**
- Fastest option (sub-1ms)
- Lowest accuracy
- No neural network (rule-based)
- Embedded in many browsers/platforms

### Option 4: Pyannote VAD

**Source:** https://github.com/pyannote/pyannote-audio

**Evidence:**
- State-of-the-art accuracy
- Includes speaker diarization
- Heavy dependencies (PyTorch)
- Higher latency (~50ms)

**Key characteristics:**
- Best for offline/batch processing
- Overkill for streaming VAD
- GPU recommended for realtime

---

## Decision

**Primary: TEN VAD**  
**Fallback: Silero VAD**

### Rationale

1. **TEN VAD offers the best precision/latency tradeoff**
   - 97.2% precision exceeds our 95% requirement
   - Sub-1ms processing time leaves headroom in latency budget
   - Lower memory than Silero (12MB vs 48MB)

2. **sherpa-onnx integration is strategic**
   - Our ASR pipeline uses sherpa-onnx
   - Native integration reduces glue code
   - Same ONNX runtime for VAD and ASR

3. **Silero as fallback provides insurance**
   - More mature, better documented
   - Known entity if TEN VAD has issues
   - Easy to swap due to similar interface

4. **WebRTC VAD rejected despite speed**
   - 89% precision is below our 95% threshold
   - False positives would cause poor UX
   - Rule-based approach struggles with noise

5. **Pyannote rejected for streaming use case**
   - 50ms latency is too high
   - Speaker diarization not needed for single-caller
   - Heavy dependencies add operational complexity

---

## Implementation

### Configuration

```typescript
interface VADConfig {
  provider: 'ten-vad' | 'silero-vad';
  
  // Detection thresholds
  threshold: number;              // 0.0-1.0, default 0.5
  minSpeechDurationMs: number;    // Minimum speech to trigger, default 250
  minSilenceDurationMs: number;   // Minimum silence for speech_end, default 300
  
  // Audio parameters
  sampleRate: 8000 | 16000;
  frameSize: 10 | 20 | 30;        // ms
  
  // Advanced
  padStartMs: number;             // Audio to include before speech_start
  padEndMs: number;               // Audio to include after speech_end
}
```

### Provider Interface

```typescript
interface VADProvider {
  readonly id: string;
  
  // Process single frame, return speech probability
  processFrame(samples: Int16Array): number;
  
  // Get current state
  getState(): 'silence' | 'speech' | 'uncertain';
  
  // Reset internal state
  reset(): void;
}

// TEN VAD Implementation
class TenVADProvider implements VADProvider {
  readonly id = 'ten-vad';
  private model: TenVadModel;
  
  constructor(config: VADConfig) {
    this.model = new TenVadModel({
      modelPath: '/models/ten-vad.onnx',
      threshold: config.threshold,
    });
  }
  
  processFrame(samples: Int16Array): number {
    return this.model.predict(samples);
  }
}
```

### Integration with Pipeline

```typescript
class VADProcessor {
  private provider: VADProvider;
  private state: 'silence' | 'speech' = 'silence';
  private speechBuffer: AudioFrame[] = [];
  
  async *process(
    frames: AsyncIterable<AudioFrame>
  ): AsyncIterable<VADEvent> {
    for await (const frame of frames) {
      const probability = this.provider.processFrame(frame.samples);
      
      if (this.state === 'silence' && probability > this.config.threshold) {
        // Potential speech start
        this.speechBuffer.push(frame);
        
        if (this.speechBuffer.length * this.frameMs >= this.config.minSpeechDurationMs) {
          this.state = 'speech';
          yield { type: 'speech_start', timestamp: this.speechBuffer[0].timestamp };
        }
      } else if (this.state === 'speech' && probability < this.config.threshold) {
        // Potential speech end
        this.silenceFrames++;
        
        if (this.silenceFrames * this.frameMs >= this.config.minSilenceDurationMs) {
          this.state = 'silence';
          yield { type: 'speech_end', timestamp: frame.timestamp };
          this.speechBuffer = [];
          this.silenceFrames = 0;
        }
      }
    }
  }
}
```

---

## Consequences

### Positive

- **Sub-20ms VAD latency achieved**: TEN VAD processes in < 1ms, well under budget
- **High precision reduces false positives**: 97% precision means fewer interruptions
- **Memory efficient**: 12MB model fits easily in container limits
- **Future-proof**: Active development, WASM support for edge deployment

### Negative

- **Newer project risk**: TEN VAD is less battle-tested than Silero
- **License consideration**: Apache 2.0 with "additional conditions" requires review
- **8kHz resampling**: Both options optimized for 16kHz, need resample for telephony

### Mitigations

1. **Run parallel evaluation**: Shadow TEN VAD against Silero in production for 2 weeks
2. **Legal review**: Have legal team review TEN VAD license terms
3. **Resample at ingestion**: Add 8kHz → 16kHz resampler in Audio Transport Layer

---

## References

1. TEN VAD GitHub: https://github.com/TEN-framework/ten-vad
2. TEN VAD Hugging Face: https://huggingface.co/TEN-framework/ten-vad
3. Silero VAD GitHub: https://github.com/snakers4/silero-vad
4. sherpa-onnx Integration: https://github.com/k2-fsa/sherpa-onnx
5. Picovoice VAD Comparison (2025): https://picovoice.ai/blog/best-voice-activity-detection-vad-2025/
